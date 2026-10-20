from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from ..services.trade_watchdog import trade_watchdog
from ..services.notification_service import notification_service
from ..services.ai_advisor_service import ai_advisor_service
from ..services.analytics_service import analytics_service
from ..config import settings


router = APIRouter(prefix="/api/bot", tags=["AI Watchdog Bot & Alerts"])


class BotConfigUpdate(BaseModel):
    bot_enabled: Optional[bool] = None
    email_alerts_enabled: Optional[bool] = None
    telegram_alerts_enabled: Optional[bool] = None
    alert_on_setup: Optional[bool] = None
    alert_on_profit: Optional[bool] = None
    alert_on_risk: Optional[bool] = None
    target_decay_pct: Optional[float] = None
    target_profit_usd: Optional[float] = None
    recipient_email: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


class TestTelegramRequest(BaseModel):
    bot_token: str
    chat_id: str


class TestEmailRequest(BaseModel):
    recipient_email: str


@router.get("/status")
async def get_bot_status() -> Dict[str, Any]:
    """
    Returns live operational status of the 24/7 AI Watchdog Bot.
    """
    return {
        "success": True,
        "status": trade_watchdog.get_status()
    }


@router.post("/toggle")
async def toggle_bot(enabled: bool = Body(..., embed=True)) -> Dict[str, Any]:
    """
    Starts or pauses the background watchdog bot.
    """
    if enabled:
        await trade_watchdog.start()
        trade_watchdog.update_config({"bot_enabled": True})
    else:
        trade_watchdog.update_config({"bot_enabled": False})
    return {
        "success": True,
        "message": f"Watchdog bot {'started' if enabled else 'paused'}",
        "status": trade_watchdog.get_status()
    }


@router.get("/alerts")
async def get_recent_alerts(limit: int = 30) -> Dict[str, Any]:
    """
    Returns recent alerts dispatched by the AI Watchdog Bot.
    """
    alerts = notification_service.get_recent_alerts(limit=limit)
    return {
        "success": True,
        "count": len(alerts),
        "alerts": alerts
    }


@router.post("/config")
async def update_bot_config(update: BotConfigUpdate) -> Dict[str, Any]:
    """
    Updates the bot configuration, alert thresholds, and notification credentials.
    """
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    trade_watchdog.update_config(data)
    return {
        "success": True,
        "message": "Bot configuration updated successfully",
        "config": trade_watchdog.config
    }


@router.post("/test-telegram")
async def test_telegram_connection(req: TestTelegramRequest) -> Dict[str, Any]:
    """
    Sends a test message to the specified Telegram bot and chat ID.
    """
    res = await notification_service.test_telegram_connection(req.bot_token, req.chat_id)
    if res.get("success"):
        # Auto-save credentials in bot config on successful test
        trade_watchdog.update_config({
            "telegram_bot_token": req.bot_token,
            "telegram_chat_id": req.chat_id,
            "telegram_alerts_enabled": True
        })
    return res


@router.post("/test-email")
async def test_email_connection(req: TestEmailRequest) -> Dict[str, Any]:
    """
    Sends a test email to the specified recipient using configured SMTP settings.
    """
    res = await notification_service.send_email(
        subject="Bitcos AI Bot Test Alert",
        body_text="Congratulations! Your Bitcos AI Trading & Risk Alert Bot email integration is active and working.",
        recipient=req.recipient_email
    )
    if res.get("success"):
        trade_watchdog.update_config({"recipient_email": req.recipient_email, "email_alerts_enabled": True})
    return res


@router.get("/ai-advisory")
@router.post("/ai-advisory")
async def get_live_ai_advisory(underlying: str = "BTC") -> Dict[str, Any]:
    """
    Generates on-demand ChatGPT advisory based on current 11-factor regime metrics.
    """
    regime = await analytics_service.get_all_regime_analytics(underlying=underlying.upper())
    if not regime.get("success"):
        raise HTTPException(status_code=500, detail="Failed to fetch regime metrics")

    advisory_res = await ai_advisor_service.generate_market_advisory(regime)
    return {
        "success": True,
        "timestamp": regime.get("timestamp"),
        "underlying": underlying,
        "spot_price": regime.get("market", {}).get("spot_price"),
        "advisory": advisory_res.get("advisory"),
        "model": advisory_res.get("model", "rule-based")
    }


@router.post("/trigger-check")
async def trigger_manual_check() -> Dict[str, Any]:
    """
    Triggers an immediate evaluation cycle of the market and risk checks.
    """
    await trade_watchdog.perform_check_cycle()
    return {
        "success": True,
        "message": "Manual watchdog check cycle completed",
        "last_run": trade_watchdog.last_run_timestamp,
        "total_checks": trade_watchdog.total_checks
    }


class ChatMessageRequest(BaseModel):
    message: str
    underlying: str = "BTC"
    history: Optional[List[Dict[str, str]]] = None


@router.post("/chat")
async def chat_with_bot(req: ChatMessageRequest) -> Dict[str, Any]:
    """
    Interactive prompt input box endpoint: Allows user to converse directly with the AI Trading Copilot
    with live Delta Exchange BTC regime & options context injected into every query.
    """
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    regime = await analytics_service.get_all_regime_analytics(underlying=req.underlying.upper())
    res = await ai_advisor_service.answer_user_query(
        user_message=req.message.strip(),
        regime_metrics=regime,
        conversation_history=req.history
    )
    return {
        "success": True,
        "reply": res.get("reply"),
        "model": res.get("model"),
        "spot_price": regime.get("market", {}).get("spot_price"),
        "timestamp": regime.get("timestamp")
    }

