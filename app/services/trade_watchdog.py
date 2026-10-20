import asyncio
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from .analytics_service import analytics_service
from .ai_advisor_service import ai_advisor_service
from .notification_service import notification_service
from .delta_exchange import DeltaExchangeAPI
from ..config import settings


class TradeWatchdogBot:
    def __init__(self):
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.interval_seconds = 12
        self.last_run_timestamp: Optional[str] = None
        self.total_checks = 0
        self.total_alerts_dispatched = 0

        # State tracking for delta triggers
        self.last_decision: Optional[str] = None
        self.last_decision_time: float = 0

        # Cooldown trackers: alert_key -> timestamp
        self.cooldowns: Dict[str, float] = {}
        self.cooldown_period_seconds = 900  # 15 minutes per specific alert

        # User Bot Preferences (defaults)
        self.config = {
            "bot_enabled": True,
            "email_alerts_enabled": True,
            "telegram_alerts_enabled": True,
            "alert_on_setup": True,
            "alert_on_profit": True,
            "alert_on_risk": True,
            "target_decay_pct": 35.0,
            "target_profit_usd": 25.0,
            "wing_buffer_warning_pct": 25.0,  # Alert when spot is within 25% of strike
            "recipient_email": settings.ALERT_RECIPIENT_EMAIL or settings.EMAIL_HOST_USER,
            "telegram_bot_token": settings.TELEGRAM_BOT_TOKEN or "",
            "telegram_chat_id": settings.TELEGRAM_CHAT_ID or ""
        }

    def update_config(self, new_config: Dict[str, Any]):
        self.config.update(new_config)

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "interval_seconds": self.interval_seconds,
            "last_run": self.last_run_timestamp,
            "total_checks": self.total_checks,
            "total_alerts_dispatched": self.total_alerts_dispatched,
            "config": self.config,
            "openai_connected": bool(settings.OPENAI_API_KEY),
            "email_configured": bool(settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD),
            "telegram_configured": bool(self.config.get("telegram_bot_token") and self.config.get("telegram_chat_id")),
            "last_decision": self.last_decision
        }

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        print("🤖 [Bitcos AI Watchdog Bot] Started 24/7 background monitoring loop.")

    async def stop(self):
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("🛑 [Bitcos AI Watchdog Bot] Stopped background monitoring loop.")

    def _can_send_alert(self, key: str, custom_cooldown: Optional[int] = None) -> bool:
        now = time.time()
        cd = custom_cooldown or self.cooldown_period_seconds
        last_sent = self.cooldowns.get(key, 0)
        if now - last_sent >= cd:
            self.cooldowns[key] = now
            return True
        return False

    async def _watchdog_loop(self):
        while self.is_running:
            try:
                await self.perform_check_cycle()
            except Exception as e:
                print(f"⚠️ [Bitcos Watchdog Bot Error]: {e}")
            await asyncio.sleep(self.interval_seconds)

    async def perform_check_cycle(self):
        """
        Executes a single quantitative evaluation of the market and active positions.
        """
        if not self.config.get("bot_enabled", True):
            return

        self.total_checks += 1
        self.last_run_timestamp = datetime.utcnow().isoformat()

        # 1. Fetch current regime analytics
        regime = await analytics_service.get_all_regime_analytics(underlying="BTC")
        if not regime.get("success"):
            return

        expiries = regime.get("expiries", [])
        if not expiries:
            return

        active_exp = expiries[0]
        scores = active_exp.get("scores", {})
        unified = scores.get("unified_conclusion", {})
        trade_model = active_exp.get("trade_model", {})
        market = regime.get("market", {})
        spot = market.get("spot_price", 0)

        current_decision = unified.get("final_decision", "WAIT / CASH")
        lead_score = unified.get("preferred_score", 0)
        dominance_gap = unified.get("dominance_gap", 0)

        # 2. Check 1: Best Setup Identified
        if self.config.get("alert_on_setup"):
            is_high_edge = (
                lead_score >= 65 and
                dominance_gap >= 10 and
                "FINAL" in current_decision
            )

            # If decision changed or edge just crossed threshold
            if is_high_edge and self.last_decision != current_decision:
                alert_key = f"setup_{current_decision}_{active_exp.get('label')}"
                if self._can_send_alert(alert_key, custom_cooldown=1800):  # 30 min cooldown
                    advisory_res = await ai_advisor_service.generate_market_advisory(regime)
                    adv = advisory_res.get("advisory", {})
                    summary = adv.get("executive_summary_hinglish") or unified.get("executive_summary")

                    msg = (
                        f"🎯 <b>Optimal Setup Identified:</b> {current_decision}\n"
                        f"• Underlying: BTC (${spot:,.1f})\n"
                        f"• Expiry: {active_exp.get('label')} ({active_exp.get('expiry_date')})\n"
                        f"• Trade: {unified.get('trade_selection')}\n"
                        f"• Model Score: {lead_score}/100 (Dominance: +{dominance_gap} pts)\n"
                        f"• AI Advisory: {summary}\n"
                        f"• Rule: Lock profit upon reaching target 35% decay ($25 USD)."
                    )

                    await self._dispatch(
                        title=f"Best Setup Alert: {current_decision}",
                        message=msg,
                        alert_type="SETUP",
                        metadata={"decision": current_decision, "spot": spot}
                    )
                    self.last_decision = current_decision

        # 3. Check 2: Wing Breach & Risk Watchdog against active Trade Model wings
        if self.config.get("alert_on_risk"):
            put_strike = trade_model.get("put_strike", 0)
            call_strike = trade_model.get("call_strike", 0)

            if spot > 0 and put_strike > 0 and call_strike > 0:
                dist_to_put = spot - put_strike
                dist_to_call = call_strike - spot

                # Total buffer from entry spot
                total_put_buffer = spot - put_strike
                total_call_buffer = call_strike - spot

                # Check if spot breached strikes (CRITICAL LOSS RISK)
                if spot <= put_strike:
                    alert_key = f"critical_breach_put_{int(spot // 100)}"
                    if self._can_send_alert(alert_key, custom_cooldown=300):  # 5 min cooldown
                        msg = (
                            f"🚨 <b>CRITICAL RISK ALERT — PUT STRIKE BREACHED!</b>\n"
                            f"• Spot BTC: ${spot:,.1f} <= Put Strike ${put_strike:,.1f}\n"
                            f"• Breach Amount: -{abs(dist_to_put):,.1f} pts\n"
                            f"• ACTION REQUIRED: Immediately close or hedge position to prevent severe drawdown!"
                        )
                        await self._dispatch(
                            title="🚨 CRITICAL: Put Wing Breached!",
                            message=msg,
                            alert_type="CRITICAL",
                            metadata={"spot": spot, "put_strike": put_strike}
                        )

                elif spot >= call_strike:
                    alert_key = f"critical_breach_call_{int(spot // 100)}"
                    if self._can_send_alert(alert_key, custom_cooldown=300):
                        msg = (
                            f"🚨 <b>CRITICAL RISK ALERT — CALL STRIKE BREACHED!</b>\n"
                            f"• Spot BTC: ${spot:,.1f} >= Call Strike ${call_strike:,.1f}\n"
                            f"• Breach Amount: +{abs(dist_to_call):,.1f} pts\n"
                            f"• ACTION REQUIRED: Immediately close or hedge position to prevent severe drawdown!"
                        )
                        await self._dispatch(
                            title="🚨 CRITICAL: Call Wing Breached!",
                            message=msg,
                            alert_type="CRITICAL",
                            metadata={"spot": spot, "call_strike": call_strike}
                        )

                # Warning Proximity Check (Within 25% of strike boundary)
                elif dist_to_put <= 0.25 * total_put_buffer:
                    alert_key = f"warning_near_put_{int(spot // 100)}"
                    if self._can_send_alert(alert_key, custom_cooldown=600):  # 10 min cooldown
                        msg = (
                            f"⚠️ <b>RISK WARNING — Spot Approaching Put Wing!</b>\n"
                            f"• Current Spot: ${spot:,.1f}\n"
                            f"• Put Strike: ${put_strike:,.1f} (Only {dist_to_put:,.1f} pts remaining!)\n"
                            f"• Wing buffer is 75%+ exhausted. Closely monitor position and prepare stop-loss."
                        )
                        await self._dispatch(
                            title="⚠️ Risk Warning: Near Put Wing",
                            message=msg,
                            alert_type="RISK_WARNING",
                            metadata={"spot": spot, "distance": dist_to_put}
                        )

                elif dist_to_call <= 0.25 * total_call_buffer:
                    alert_key = f"warning_near_call_{int(spot // 100)}"
                    if self._can_send_alert(alert_key, custom_cooldown=600):
                        msg = (
                            f"⚠️ <b>RISK WARNING — Spot Approaching Call Wing!</b>\n"
                            f"• Current Spot: ${spot:,.1f}\n"
                            f"• Call Strike: ${call_strike:,.1f} (Only {dist_to_call:,.1f} pts remaining!)\n"
                            f"• Wing buffer is 75%+ exhausted. Closely monitor position and prepare stop-loss."
                        )
                        await self._dispatch(
                            title="⚠️ Risk Warning: Near Call Wing",
                            message=msg,
                            alert_type="RISK_WARNING",
                            metadata={"spot": spot, "distance": dist_to_call}
                        )

        # 4. Check 3: Profit Booking Alert (35% Decay or Target ROC)
        if self.config.get("alert_on_profit"):
            # If current decay model indicates target net profit is viable
            target_usd = self.config.get("target_profit_usd", 25.0)
            target_decay = self.config.get("target_decay_pct", 35.0)

            # Check if execution model net profit exceeds target
            model_net = trade_model.get("target_net_profit_usd", 25.0)
            if model_net >= target_usd and active_exp.get("dte", 0) <= 0.2:  # Later in session
                alert_key = f"profit_target_{active_exp.get('label')}"
                if self._can_send_alert(alert_key, custom_cooldown=3600):  # 1 hr cooldown
                    msg = (
                        f"💰 <b>PROFIT BOOKING RECOMMENDATION:</b>\n"
                        f"• Target Profit (${target_usd} USD / {target_decay}% decay) target zone reached!\n"
                        f"• Expiry: {active_exp.get('label')} ({active_exp.get('hours_to_expiry')} hrs remaining)\n"
                        f"• Recommendation: Close positions to flatten Greeks and secure target gains."
                    )
                    await self._dispatch(
                        title=f"💰 Profit Booking Alert: Target Achieved",
                        message=msg,
                        alert_type="PROFIT",
                        metadata={"target_net": model_net}
                    )

    async def _dispatch(self, title: str, message: str, alert_type: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Dispatches alert via NotificationService using active configuration.
        """
        self.total_alerts_dispatched += 1
        recipient_email = self.config.get("recipient_email") if self.config.get("email_alerts_enabled") else None
        tg_token = self.config.get("telegram_bot_token") if self.config.get("telegram_alerts_enabled") else None
        tg_chat_id = self.config.get("telegram_chat_id") if self.config.get("telegram_alerts_enabled") else None

        await notification_service.broadcast_alert(
            title=title,
            message=message,
            alert_type=alert_type,
            recipient_email=recipient_email,
            telegram_token=tg_token,
            telegram_chat_id=tg_chat_id,
            metadata=metadata
        )


trade_watchdog = TradeWatchdogBot()
