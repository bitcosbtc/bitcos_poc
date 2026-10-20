from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from datetime import datetime
from app.database import Base


class TradeAudit(Base):
    """
    Trade Audit & Continuous Machine Learning Feedback Database Model.
    Tracks every historical & live trade execution, evaluates if the trade was
    'PERFECT' or 'FAILED', documents root cause ('Kyon Galat Gaya'),
    and prescribes automated corrective actions ('Kaise Shi Karein')
    to prevent recurring failure patterns.
    """
    __tablename__ = "trade_audits"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(String(50), index=True, nullable=False)
    setup_type = Column(String(50), index=True, nullable=False)  # SHORT_STRANGLE, LONG_STRADDLE, etc.
    symbol = Column(String(20), default="BTCUSD")
    
    entry_time = Column(String(50), nullable=True)
    exit_time = Column(String(50), nullable=True)
    spot_price_entry = Column(Float, nullable=True)
    strikes_recommended = Column(String(100), nullable=True)
    entry_premium = Column(Float, nullable=True)
    exit_premium = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    roi_pct = Column(Float, nullable=True)

    trade_status = Column(String(30), index=True, default="PERFECT_PROFIT")  # PERFECT_PROFIT, ACCEPTABLE_WIN, STOPPED_OUT_LOSS
    is_perfect = Column(Boolean, default=True, index=True)

    why_it_succeeded_or_failed = Column(Text, nullable=True)  # Root cause: kyon galat gaya / kyon sahi raha
    corrective_action = Column(Text, nullable=True)           # Actionable adjustment: kaise sahi karein
    avoidance_rule_violated = Column(Text, nullable=True)     # "Kya nahi karna tha" violation flag
    
    market_regime = Column(String(50), nullable=True)         # Mean-reverting, High Vol, etc.
    macro_zone = Column(String(50), nullable=True)            # HIGH_PROFIT_70_PCT, HIGH_RISK_70_PCT, NO_TRADE_ZONE
    
    created_at = Column(DateTime, default=datetime.utcnow)
