from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
from app.database import Base


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, index=True)
    trade_index = Column(String(50), index=True, nullable=False)  # "1", "1.1", "1.2", "2", ...
    parent_index = Column(String(50), index=True, nullable=True)  # "1", "2", ...
    is_parent = Column(Boolean, default=False, index=True)        # True for summary session row, False for leg

    ce_exe = Column(Integer, nullable=True)                        # 1 or None
    pe_exe = Column(Integer, nullable=True)                        # 1 or None
    
    entry_date = Column(String(50), nullable=True)                # e.g. "Tue, Dec 31, 2024"
    entry_time = Column(String(50), nullable=True)                # e.g. "9:30:00 PM"
    exit_date = Column(String(50), nullable=True)                 # e.g. "Thu, Jan 2, 2025"
    exit_time = Column(String(50), nullable=True)                 # e.g. "5:27:00 PM"
    
    option_type = Column(String(20), nullable=True)               # "CE", "PE", or "STRANGLE"
    strike = Column(Float, nullable=True)                         # 99600.0, 90000.0
    buy_sell = Column(String(10), nullable=True)                  # "Sell", "Buy"
    qty = Column(Float, nullable=True)                            # 0.5
    entry_price = Column(Float, nullable=True)                    # 267.83
    exit_price = Column(Float, nullable=True)                     # 0.1
    pnl = Column(Float, nullable=True)                            # 16917.55
    
    strategy = Column(String(50), default="0DTE/2DTE Strangle")
    created_at = Column(DateTime, default=datetime.utcnow)
