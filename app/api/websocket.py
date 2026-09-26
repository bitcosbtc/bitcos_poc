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
        self.active_connections: dict[int, list[WebSocket]] = {} # user_id -> [WS]

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

def normalize_expiry_to_ddmmyy(expiry: str) -> str:
    if len(expiry) == 6 and expiry.isdigit():
        first_two = int(expiry[0:2])
        last_two = int(expiry[4:6])
        middle_two = int(expiry[2:4])
        
        # If the last two digits represent the year (e.g., 26 for 2026), it's already DDMMYY
        if 20 <= last_two <= 40 and 1 <= middle_two <= 12:
            return expiry
            
        # If the first two digits represent the year (e.g., 26 for 2026), it is YYMMDD, convert to DDMMYY
        if 20 <= first_two <= 40 and 1 <= middle_two <= 12:
            yy = expiry[0:2]
            mm = expiry[2:4]
            dd = expiry[4:6]
            return f"{dd}{mm}{yy}"
            
    return expiry

# ── Server-side trade signal store ────────────────────────────────────
# Keyed by broker_id → list of pending trade signals
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


# ── Global Cache Update Helper ───────────────────────────────────────────
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
        
        elif t in ["user_balances", "v2/user_balances", "wallets", "v2/wallets"] and b_id:
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


# ── Shared Delta Connection Pool ─────────────────────────────────────────
class DeltaConnectionPool:
    def __init__(self):
        # broker_id -> list of active browser WebSockets
        self.clients: dict[int, list[WebSocket]] = {}
        # broker_id -> asyncio Task running the private WS stream
        self.private_tasks: dict[int, asyncio.Task] = {}
        # broker_id -> asyncio Task running the public WS stream
        self.public_tasks: dict[int, asyncio.Task] = {}
        # broker_id -> set of active symbols subscribed on public WS
        self.public_symbols: dict[int, set[str]] = {}
        # broker_id -> asyncio Queue to send subscription updates to the public WS task
        self.public_subscription_queues: dict[int, asyncio.Queue] = {}
        self.connection_lock = asyncio.Lock()
        self.last_connection_time = 0.0

    async def throttle_connection(self):
        """Stagger WebSocket connections with a minimum 250ms interval to avoid 429 rate limit."""
        async with self.connection_lock:
            now = time.time()
            elapsed = now - self.last_connection_time
            if elapsed < 0.25:
                await asyncio.sleep(0.25 - elapsed)
            self.last_connection_time = time.time()

    async def broadcast_raw(self, broker_id: int, message: str):
        if broker_id in self.clients:
            for ws in list(self.clients[broker_id]):
                try:
                    await ws.send_text(message)
                except Exception:
                    self.remove_client(broker_id, ws)

    async def broadcast(self, broker_id: int, message: dict):
        if broker_id in self.clients:
            for ws in list(self.clients[broker_id]):
                try:
                    await ws.send_json(message)
                except Exception:
                    self.remove_client(broker_id, ws)

    async def add_client(self, broker_id: int, ws: WebSocket, api_key: str, secret_key: str, private_url: str, public_url: str, initial_symbols: list[str]):
        if broker_id not in self.clients:
            self.clients[broker_id] = []
        self.clients[broker_id].append(ws)
        print(f"DEBUG: Added client to broker {broker_id}. Total: {len(self.clients[broker_id])}")

        # Initialize public symbols with default index and initial_symbols
        if broker_id not in self.public_symbols:
            self.public_symbols[broker_id] = set([".BTCUSD"])
        for s in initial_symbols:
            self.public_symbols[broker_id].add(s)

        # Start private task if not running or done
        if broker_id not in self.private_tasks or self.private_tasks[broker_id].done():
            self.private_tasks[broker_id] = asyncio.create_task(
                self.stream_private_shared(broker_id, api_key, secret_key, private_url)
            )

        # Start public task if not running or done
        if broker_id not in self.public_tasks or self.public_tasks[broker_id].done():
            self.public_subscription_queues[broker_id] = asyncio.Queue()
            self.public_tasks[broker_id] = asyncio.create_task(
                self.stream_public_shared(broker_id, public_url)
            )

    def remove_client(self, broker_id: int, ws: WebSocket):
        if broker_id in self.clients:
            if ws in self.clients[broker_id]:
                self.clients[broker_id].remove(ws)
                print(f"DEBUG: Removed client from broker {broker_id}. Remaining: {len(self.clients[broker_id])}")
            if not self.clients[broker_id]:
                print(f"DEBUG: No clients left for broker {broker_id}. Stopping shared WS connections.")
                if broker_id in self.private_tasks:
                    self.private_tasks[broker_id].cancel()
                    del self.private_tasks[broker_id]
                if broker_id in self.public_tasks:
                    self.public_tasks[broker_id].cancel()
                    del self.public_tasks[broker_id]
                if broker_id in self.public_symbols:
                    del self.public_symbols[broker_id]
                if broker_id in self.public_subscription_queues:
                    del self.public_subscription_queues[broker_id]

    def update_symbols(self, broker_id: int, new_symbols: list[str]):
        if broker_id in self.public_symbols:
            current_syms = self.public_symbols[broker_id]
            added = False
            for s in new_symbols:
                if s not in current_syms:
                    current_syms.add(s)
                    added = True
            
            if added:
                queue = self.public_subscription_queues.get(broker_id)
                if queue:
                    queue.put_nowait(current_syms)

    async def stream_private_shared(self, broker_id: int, api_key: str, secret_key: str, url: str):
        retry = 3
        while broker_id in self.clients and len(self.clients[broker_id]) > 0:
            print(f"DEBUG: Shared Private WS connecting for broker {broker_id}...")
            try:
                await self.throttle_connection()
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=10, open_timeout=15
                ) as priv_ws:
                    # Auth
                    ts  = str(int(time.time()))
                    sig = hmac.new(secret_key.encode(), ("GET" + ts + "/live").encode(), hashlib.sha256).hexdigest()
                    await priv_ws.send(json.dumps({
                        "type": "auth",
                        "payload": {"api-key": api_key, "signature": sig, "timestamp": ts}
                    }))
                    
                    auth_raw = await asyncio.wait_for(priv_ws.recv(), timeout=6.0)
                    auth_msg = json.loads(auth_raw)
                    print(f"DEBUG: Shared Private WS auth response for broker {broker_id}: {auth_raw[:200]}")
                    if auth_msg.get("type") == "error":
                        err_msg = auth_msg.get("message", "Unknown error")
                        print(f"ERROR: Shared Private WS auth failed for broker {broker_id}: {err_msg}")
                        await self.broadcast(broker_id, {
                            "type": "delta_error",
                            "message": f"Delta auth failed: {err_msg}"
                        })
                        await asyncio.sleep(30)
                        continue

                    # Subscribe private channels
                    await priv_ws.send(json.dumps({
                        "type": "subscribe",
                        "payload": {"channels": [
                            {"name": "wallets", "symbols": ["all"]},
                            {"name": "positions", "symbols": ["all"]},
                            {"name": "orders", "symbols": ["all"]},
                        ]}
                    }))
                    print(f"SUCCESS: Shared Private WS subscribed: wallets, positions, orders for broker {broker_id}")

                    async for raw in priv_ws:
                        if broker_id not in self.clients or not self.clients[broker_id]:
                            break
                        try:
                            update_global_cache(raw, broker_id)
                            await self.broadcast_raw(broker_id, raw)
                        except Exception as e:
                            print(f"ERROR: Failed processing private WS message: {e}")
                retry = 3
            except asyncio.CancelledError:
                print(f"DEBUG: Shared Private WS task cancelled for broker {broker_id}")
                break
            except Exception as e:
                print(f"DEBUG: Shared Private WS error for broker {broker_id} ({e}), retry in {retry}s")
                await asyncio.sleep(retry)
                retry = min(retry * 2, 30)

    async def stream_public_shared(self, broker_id: int, url: str):
        retry = 2
        while broker_id in self.clients and len(self.clients[broker_id]) > 0:
            print(f"DEBUG: Shared Public WS connecting for broker {broker_id}...")
            try:
                queue = self.public_subscription_queues.get(broker_id)
                if not queue:
                    break
                await self.throttle_connection()
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=10, open_timeout=15
                ) as pub_ws:
                    print(f"SUCCESS: Shared Public WS connected for broker {broker_id}")
                    
                    async def subscription_handler():
                        while broker_id in self.clients and len(self.clients[broker_id]) > 0:
                            try:
                                symbols = await queue.get()
                                if symbols:
                                    print(f"DEBUG: Shared Public WS subscribing to: {symbols}")
                                    await pub_ws.send(json.dumps({
                                        "type": "subscribe",
                                        "payload": {"channels": [{"name": "ticker", "symbols": list(symbols)}]}
                                    }))
                                queue.task_done()
                            except asyncio.CancelledError:
                                break
                            except Exception as ex:
                                print(f"ERROR: subscription_handler error: {ex}")
                                
                    sub_task = asyncio.create_task(subscription_handler())
                    
                    try:
                        current_syms = self.public_symbols.get(broker_id, set())
                        if current_syms:
                            await pub_ws.send(json.dumps({
                                "type": "subscribe",
                                "payload": {"channels": [{"name": "ticker", "symbols": list(current_syms)}]}
                            }))
                        
                        async for raw in pub_ws:
                            if broker_id not in self.clients or not self.clients[broker_id]:
                                break
                            try:
                                update_global_cache(raw, broker_id)
                                await self.broadcast_raw(broker_id, raw)
                            except Exception:
                                pass
                    finally:
                        sub_task.cancel()
                retry = 2
            except asyncio.CancelledError:
                print(f"DEBUG: Shared Public WS task cancelled for broker {broker_id}")
                break
            except Exception as e:
                print(f"DEBUG: Shared Public WS error for broker {broker_id} ({e}), retry in {retry}s")
                await asyncio.sleep(retry)
                retry = min(retry * 2, 30)

delta_pool = DeltaConnectionPool()


@router.websocket("/trading/{broker_id}")
async def trading_websocket(
    websocket: WebSocket,
    broker_id: int,
    token: str = Query(...)
):
    print(f"DEBUG: WebSocket request received for broker {broker_id}")

    from ..database import SessionLocal
    db = SessionLocal()
    try:
        user = await get_current_user_ws(token, db)
        if not user:
            await websocket.accept()
            await websocket.send_json({"type": "error", "message": "Authentication failed"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        
        await manager.connect(user.id, websocket)
        print(f"SUCCESS: WebSocket connection established and managed for user {user.id}, broker {broker_id}")

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
    private_ws_url = "wss://socket.india.delta.exchange"      if is_india else "wss://socket.delta.exchange"
    public_ws_url  = "wss://public-socket.india.delta.exchange" if is_india else "wss://socket.delta.exchange"

    print(f"SUCCESS: Using Private={private_ws_url}")
    print(f"SUCCESS: Using Public={public_ws_url}")

    alive = {"browser": True}
    inbox = asyncio.Queue()

    async def browser_reader():
        try:
            while alive["browser"]:
                raw = await websocket.receive_text()
                await inbox.put(raw)
        except (WebSocketDisconnect, Exception) as e:
            print(f"DEBUG: Browser disconnected: {e}")
            alive["browser"] = False
            await inbox.put(None)

    async def message_processor():
        while alive["browser"]:
            raw = await inbox.get()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
                t   = msg.get("type", "")

                if t == "subscribe_symbols":
                    symbols    = msg.get("symbols", [])
                    expiry     = msg.get("expiry")
                    underlying = msg.get("underlying", "BTC")

                    pub_syms = []
                    
                    if not symbols and expiry and underlying:
                        try:
                            normalized_expiry = normalize_expiry_to_ddmmyy(expiry)
                            delta_api = DeltaExchangeAPI(api_key, secret_key, base_url)
                            products_res = await asyncio.to_thread(delta_api.get_products)
                            if products_res.get("success"):
                                for p in products_res.get("result", []):
                                    sym = p.get("symbol", "")
                                    c_type = p.get("contract_type", "")
                                    if c_type in ["call_options", "put_options"]:
                                        if sym.endswith(f"-{normalized_expiry}") and f"-{underlying}-" in sym:
                                            pub_syms.append(sym)
                                print(f"SUCCESS: Auto-subscribed {len(pub_syms)} options symbols for {underlying} on {normalized_expiry}")
                        except Exception as e:
                            print(f"ERROR: Failed to auto-fetch option symbols: {e}")

                    if not pub_syms:
                        for s in (symbols if symbols else [".BTCUSD"]):
                            pub_syms.append(str(s).split(":", 1)[-1])

                    if ".BTCUSD" not in pub_syms:
                        pub_syms.append(".BTCUSD")

                    delta_pool.update_symbols(broker_id, pub_syms)

                elif t == "trade_signal":
                    symbol = msg.get("symbol")
                    action = msg.get("action")
                    strike = msg.get("strike")
                    print(f"SUCCESS: Trade Signal → {symbol} ({action}) @ Strike {strike}")

            except Exception as e:
                print(f"DEBUG: Message processor error: {e}")

    # Fetch open position symbols for initial public subscription
    open_symbols = await asyncio.to_thread(get_open_symbols, api_key, secret_key, base_url)

    # Register client in the shared pool
    await delta_pool.add_client(
        broker_id=broker_id,
        ws=websocket,
        api_key=api_key,
        secret_key=secret_key,
        private_url=private_ws_url,
        public_url=public_ws_url,
        initial_symbols=open_symbols
    )

    await websocket.send_json({
        "type": "delta_connected",
        "message": "Delta Exchange live",
        "symbols": open_symbols,
    })

    # Run browser reader and message processor concurrently for this connection
    await asyncio.gather(
        browser_reader(),
        message_processor(),
        return_exceptions=True
    )
    
    # Cleanup client on disconnect
    delta_pool.remove_client(broker_id, websocket)
    manager.disconnect(user.id, websocket)
    print(f"DEBUG: WS handler done for broker {broker_id}")
