import asyncio
import logging
from sqlalchemy.orm import Session
from ..database import SessionLocal, engine
from ..models.mtm import MTMSettings
from ..models.broker import Broker
from ..models.position import Position
from .cache import global_cache
from ..api.trading import get_delta_api
from ..api.websocket import manager
import json

logger = logging.getLogger(__name__)

class MTMManager:
    def __init__(self):
        self.is_running = False
        self._task = None

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._monitor_loop())
            logger.info("MTM Background Monitor Started")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("MTM Background Monitor Stopped")

    async def _monitor_loop(self):
        while self.is_running:
            try:
                db = SessionLocal()
                active_settings = db.query(MTMSettings).filter(MTMSettings.is_active == True).all()
                
                for settings in active_settings:
                    await self._process_user_mtm(db, settings)
                
                db.close()
            except Exception as e:
                logger.error(f"Error in MTM Monitor Loop: {e}")
            
            await asyncio.sleep(1) # Run every 1 second

    async def _process_user_mtm(self, db: Session, settings: MTMSettings):
        user_id = settings.user_id
        
        # 1. Calculate Total Capital and uPnL for this user
        total_wallet_usd = 0
        total_upnl = 0
        
        # Get active brokers for this user
        brokers = db.query(Broker).filter(Broker.user_id == user_id, Broker.status == "ACTIVE").all()
        
        for b in brokers:
            # Get balance from cache
            b_bals = global_cache.balances.get(b.id, {})
            # Delta usually uses USDT or USD
            usdt = b_bals.get('USDT') or b_bals.get('USD') or b_bals.get('USDC')
            if not usdt:
                # Try finding any USD-like asset
                usdt = next((val for val in b_bals.values() if isinstance(val, dict) and val.get('asset_symbol') in ['USDT', 'USD', 'USDC']), None)
            
            wallet_bal = float(usdt.get('balance', 0) or usdt.get('wallet_balance', 0) if usdt else 0)
            total_wallet_usd += wallet_bal
            
            # Get positions for this broker from cache
            # Cache keys are {product_id}_{broker_id}
            for key, pos in global_cache.positions.items():
                if str(key).endswith(f"_{b.id}"):
                    total_upnl += float(pos.get('unrealized_pnl', 0))

        if total_wallet_usd <= 0:
            return

        current_pct = (total_upnl / total_wallet_usd) * 100
        
        # 2. Trailing Logic
        if settings.peak_upnl_pct is None or current_pct > settings.peak_upnl_pct:
            # If it's the first run or we hit a new peak
            old_peak = settings.peak_upnl_pct if settings.peak_upnl_pct is not None else current_pct
            diff = current_pct - old_peak
            
            # Update peak
            settings.peak_upnl_pct = current_pct
            
            # Since we don't store current_sl/current_tp in DB yet (only the initial ones), 
            # we need to track the TRAILED levels.
            # For simplicity, we can calculate them relative to the peak.
            # Initial SL was (Initial_Pct - sl_pct). 
            # Trailed SL = Peak_Pct - sl_pct
        
        trailed_sl = (settings.peak_upnl_pct or 0) - (settings.sl_pct or 10)
        trailed_tp = (settings.peak_upnl_pct or 0) + (settings.tp_pct or 20)
        
        # 3. Check for Trigger
        # 4. Notify user via WebSocket
        asyncio.create_task(manager.send_personal_message(json.dumps({{
            "type": "mtm_update",
            "payload": {{
                "current_pct": current_pct,
                "trailed_sl": trailed_sl,
                "trailed_tp": trailed_tp,
                "peak_pct": settings.peak_upnl_pct,
                "total_cap": total_wallet_usd,
                "is_active": settings.is_active
            }}
        }}), user_id))

        if current_pct <= trailed_sl or current_pct >= trailed_tp:
            reason = "STOPLOSS" if current_pct <= trailed_sl else "TARGET"
            logger.info(f"MTM Triggered for User {user_id}: {reason} at {current_pct:.2f}% (SL: {trailed_sl:.2f}%, TP: {trailed_tp:.2f}%)")
            
            # Execute Square-off
            await self._execute_bulk_close(db, user_id, brokers)
            
            # Deactivate MTM
            settings.is_active = False
            db.commit()
            
            # Notify user via WebSocket (if possible)
            # We will implement a broadcast mechanism later
        else:
            # Update DB with new peak if changed
            db.commit()

    async def _execute_bulk_close(self, db: Session, user_id: int, brokers: list):
        for broker in brokers:
            try:
                # Import here to avoid circular imports if any
                from ..api.trading import get_delta_api
                delta_api = get_delta_api(broker.id, user_id, db)
                result = delta_api.close_all_positions()
                logger.info(f"MTM: Closed all positions for Broker {broker.id}. Result: {result}")
            except Exception as e:
                logger.error(f"MTM: Failed to close positions for Broker {broker.id}: {e}")

mtm_manager = MTMManager()
