from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, status, Request
from sqlalchemy.orm import Session
from datetime import datetime
import json
import asyncio
import websockets
import time
import hmac
import hashlib
from jose import JWTError, jwt

from ..database import get_db, SessionLocal
from ..models.broker import Broker
from ..models.user import User
from ..services.cache import global_cache
from ..services.encryption import encryption_service
from ..services.delta_exchange import DeltaExchangeAPI
from ..config import settings

router = APIRouter(prefix="/api/ws", tags=["Websocket"])

# ── WebSocket Connection Manager ──────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, list[WebSocket]] = {} # user_id -> [WS]

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(message)
                except Exception:
                    pass

manager = ConnectionManager()

# ── Server-side trade signal store ────────────────────────────────────
# Keyed by broker_id → list of pending trade signals
# iframe POSTs signals here, app.py polls to get them and update basket
_trade_signals: dict[int, list] = {}


@router.post("/trade-signal/{broker_id}")
async def post_trade_signal(broker_id: int, request: Request):
    """Called by Option Chain iframe when user clicks Bid/Ask."""
    try:
        body = await request.json()
        if broker_id not in _trade_signals:
            _trade_signals[broker_id] = []
        _trade_signals[broker_id].append(body)
        print(f"SUCCESS: Trade Signal stored → broker={broker_id} symbol={body.get('symbol')} action={body.get('action')}")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/trade-signal/{broker_id}")
async def get_trade_signals(broker_id: int):
    """Polled by app.py to retrieve and clear pending trade signals."""
    signals = _trade_signals.pop(broker_id, [])
    return {"signals": signals}



async def get_current_user_ws(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None
    return db.query(User).filter(User.username == username).first()


def get_open_symbols(api_key: str, secret_key: str, base_url: str) -> list:
    """Fetch open position symbols via REST (blocking, called in thread)."""
    try:
        delta = DeltaExchangeAPI(api_key, secret_key, base_url)
        result = delta.get_positions()
        symbols = []
        for pos in result.get("result", []):
            size = pos.get("size", 0)
            if size and float(size) != 0:
                sym = (
                    pos.get("symbol")
                    or (pos.get("product") or {}).get("symbol")
                    or pos.get("product_symbol")
                )
                if sym and sym not in symbols:
                    symbols.append(sym)
        print(f"DEBUG WS: Open position symbols: {symbols}")
        return symbols
    except Exception as e:
        print(f"DEBUG WS: Could not fetch open symbols: {e}")
        return []


@router.websocket("/trading/{broker_id}")
async def trading_websocket(
    websocket: WebSocket,
    broker_id: int,
    token: str = Query(...)
):
    print(f"DEBUG: WebSocket request received for broker {broker_id}")
    # We will accept after auth check if possible, or accept now
    # await websocket.accept()

    from ..database import SessionLocal
    db = SessionLocal()
    try:
        # ── Authenticate user ──────────────────────────────────────────────
        user = await get_current_user_ws(token, db)
        if not user:
            await websocket.accept()
            await websocket.send_json({"type": "error", "message": "Authentication failed"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        
        await manager.connect(user.id, websocket)
        print(f"SUCCESS: WebSocket connection established and managed for user {user.id}, broker {broker_id}")

        # ── Get broker credentials ─────────────────────────────────────────
        broker = db.query(Broker).filter(
            Broker.id == broker_id, Broker.user_id == user.id
        ).first()
        if not broker:
            await websocket.send_json({"type": "error", "message": "Broker not found"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            api_key    = encryption_service.decrypt(broker.api_key_encrypted)
            secret_key = encryption_service.decrypt(broker.secret_key_encrypted)
        except Exception as decrypt_err:
            print(f"ERROR: Decryption failed for broker {broker_id}: {decrypt_err}")
            await websocket.send_json({"type": "error", "message": "Credential decryption failed"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        base_url   = broker.redirect_url or "https://api.india.delta.exchange"
    except Exception as e:
        print(f"CRITICAL WS ERROR: {e}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    finally:
        db.close()
        
    is_india   = "india" in base_url

    # Delta Exchange (as of April 2026) has TWO separate WS pods:
    # PUBLIC pod  → ticker, mark_price (no auth needed)
    # PRIVATE pod → positions, orders, user_balances (auth required)
    private_ws_url = "wss://socket.india.delta.exchange"      if is_india else "wss://socket.delta.exchange"
    public_ws_url  = "wss://public-socket.india.delta.exchange" if is_india else "wss://socket.delta.exchange"

    print(f"SUCCESS: Using Private={private_ws_url}")
    print(f"SUCCESS: Using Public={public_ws_url}")

    # Shared state
    alive = {"browser": True}
    # Queue for messages from browser iframe → we process them here
    inbox = asyncio.Queue()

    await websocket.send_json({"type": "connected", "message": "Connecting to Delta Exchange..."})

    # ──────────────────────────────────────────────────────────────────
    # TASK 1: Read all browser messages into queue (single receiver)
    # ──────────────────────────────────────────────────────────────────
    def update_global_cache(raw: str, b_id: int = None):
        try:
            msg = json.loads(raw)
            t = msg.get("type", "")
            payload = msg.get("payload", [])
            if not isinstance(payload, list):
                payload = [payload]

            if t in ["mark_price", "v2/mark_price", "ticker", "v2/ticker"]:
                symbol = msg.get("symbol") or (payload[0].get("symbol") if payload and isinstance(payload[0], dict) else None)
                price = msg.get("price") or (payload[0].get("mark_price") if payload and isinstance(payload[0], dict) else None) or (payload[0].get("price") if payload and isinstance(payload[0], dict) else None)
                if symbol and price:
                    global_cache.update_price(symbol, float(price))
            
            elif t in ["user_balances", "v2/user_balances"] and b_id:
                bals = {}
                for b in payload:
                    if not isinstance(b, dict): continue
                    sym = b.get("asset_symbol") or b.get("symbol")
                    if sym:
                        bals[sym] = b
                global_cache.update_balances(b_id, bals)

            elif t in ["positions", "v2/positions"] and b_id:
                for p in payload:
                    if not isinstance(p, dict): continue
                    pid = p.get("product_id")
                    if pid:
                        uk = f"{pid}_{b_id}"
                        global_cache.update_position(uk, p)
        except Exception as e:
            print(f"DEBUG: Cache update error: {e}")

    async def browser_reader():
        try:
            while alive["browser"]:
                raw = await websocket.receive_text()
                await inbox.put(raw)
        except (WebSocketDisconnect, Exception) as e:
            print(f"DEBUG: Browser disconnected: {e}")
            alive["browser"] = False
            await inbox.put(None)  # Sentinel to unblock processors

    # ──────────────────────────────────────────────────────────────────
    # TASK 2: Stream public ticker (spot price + options) → browser
    # ──────────────────────────────────────────────────────────────────
    async def stream_public(symbols: list):
        """Subscribe to Delta public WS and forward all ticker messages to browser."""
        print(f"DEBUG: Public WS connecting for symbols: {symbols}")
        retry = 2
        while alive["browser"]:
            try:
                async with websockets.connect(
                    public_ws_url, ping_interval=20, ping_timeout=10, open_timeout=15
                ) as pub_ws:
                    await pub_ws.send(json.dumps({
                        "type": "subscribe",
                        "payload": {"channels": [{"name": "ticker", "symbols": symbols}]}
                    }))
                    print(f"SUCCESS: Public WS live. Streaming ticker for: {symbols}")
                    async for raw in pub_ws:
                        if not alive["browser"]:
                            return
                        try:
                            update_global_cache(raw)
                            await websocket.send_text(raw)
                        except Exception:
                            alive["browser"] = False
                            return
                retry = 2
            except Exception as e:
                print(f"DEBUG: Public WS error ({e}), retry in {retry}s")
                await asyncio.sleep(retry)
                retry = min(retry * 2, 30)

    # ──────────────────────────────────────────────────────────────────
    # TASK 3: Private WS (user data) — auth + subscribe + forward
    # ──────────────────────────────────────────────────────────────────
    async def stream_private():
        retry = 3
        while alive["browser"]:
            print(f"DEBUG: Private WS connecting...")
            try:
                async with websockets.connect(
                    private_ws_url, ping_interval=20, ping_timeout=10, open_timeout=15
                ) as priv_ws:
                    # Auth
                    ts  = str(int(time.time()))
                    sig = hmac.new(secret_key.encode(), ("GET" + ts + "/live").encode(), hashlib.sha256).hexdigest()
                    await priv_ws.send(json.dumps({
                        "type": "auth",
                        "payload": {"api-key": api_key, "signature": sig, "timestamp": ts}
                    }))
                    try:
                        auth_raw = await asyncio.wait_for(priv_ws.recv(), timeout=6.0)
                        auth_msg = json.loads(auth_raw)
                        print(f"DEBUG: Auth response: {auth_raw[:200]}")
                        if auth_msg.get("type") == "error":
                            err_msg = auth_msg.get("message", "Unknown error")
                            print(f"ERROR: Delta private WS auth failed: {err_msg}")
                            await websocket.send_json({
                                "type": "delta_error",
                                "message": f"Delta auth failed: {err_msg}"
                            })
                            # Don't return — wait and retry (IP whitelist may update)
                            await asyncio.sleep(30)
                            continue
                    except asyncio.TimeoutError:
                        print("DEBUG: Auth timeout")

                    # Subscribe private channels
                    await priv_ws.send(json.dumps({
                        "type": "subscribe",
                        "payload": {"channels": [
                            {"name": "user_balances"},
                            {"name": "positions"},
                            {"name": "orders"},
                        ]}
                    }))
                    print("SUCCESS: Private WS subscribed: user_balances, positions, orders")

                    # Forward all messages from private WS to browser
                    async for raw in priv_ws:
                        if not alive["browser"]:
                            return
                        try:
                            update_global_cache(raw, broker_id)
                            await websocket.send_text(raw)
                        except Exception:
                            alive["browser"] = False
                            return
                retry = 3
            except Exception as e:
                print(f"DEBUG: Private WS error ({e}), retry in {retry}s")
                await asyncio.sleep(retry)
                retry = min(retry * 2, 30)

    # ──────────────────────────────────────────────────────────────────
    # TASK 4: Process browser messages (subscribe_symbols, trade_signal)
    # ──────────────────────────────────────────────────────────────────
    public_tasks = {}  # expiry → task

    async def message_processor():
        while alive["browser"]:
            raw = await inbox.get()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
                t   = msg.get("type", "")

                if t == "subscribe_symbols":
                    # Browser iframe sends this when option chain opens
                    symbols    = msg.get("symbols", [])
                    expiry     = msg.get("expiry")
                    underlying = msg.get("underlying", "BTC")

                    # Strip prefixes (ticker:, v2:, etc.) for Delta compatibility
                    pub_syms = []
                    for s in (symbols if symbols else [".BTCUSD"]):
                        pub_syms.append(str(s).split(":", 1)[-1])
                    
                    if expiry and f"{underlying}-{expiry}" not in pub_syms:
                        pub_syms.append(f"{underlying}-{expiry}")

                    task_key = expiry or "default"
                    # Cancel previous task for same key
                    if task_key in public_tasks:
                        public_tasks[task_key].cancel()

                    print(f"SUCCESS: Option Chain subscription request → launching public WS for: {pub_syms}")
                    public_tasks[task_key] = asyncio.create_task(stream_public(pub_syms))

                elif t == "trade_signal":
                    symbol = msg.get("symbol")
                    action = msg.get("action")
                    strike = msg.get("strike")
                    print(f"SUCCESS: Trade Signal → {symbol} ({action}) @ Strike {strike}")
                    # (relay logic can be added here if needed)

            except Exception as e:
                print(f"DEBUG: Message processor error: {e}")

    # ──────────────────────────────────────────────────────────────────
    # Launch everything concurrently
    # ──────────────────────────────────────────────────────────────────
    # Fetch open position symbols for initial public subscription
    open_symbols = await asyncio.to_thread(get_open_symbols, api_key, secret_key, base_url)

    # Initial public subscription: always include .BTCUSD for index spot price
    initial_pub_syms = [".BTCUSD"] + open_symbols
    public_tasks["initial"] = asyncio.create_task(stream_public(initial_pub_syms))

    await websocket.send_json({
        "type": "delta_connected",
        "message": "Delta Exchange live",
        "symbols": open_symbols,
    })

    # Run all 3 tasks concurrently; exit when browser disconnects
    await asyncio.gather(
        browser_reader(),
        stream_private(),
        message_processor(),
        return_exceptions=True
    )
    
    manager.disconnect(user.id, websocket)

    # Cleanup all public tasks
    for task in public_tasks.values():
        task.cancel()

    print(f"DEBUG: WS handler done for broker {broker_id}")
