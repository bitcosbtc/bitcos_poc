from sqlalchemy import Column, Integer, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base

class MTMSettings(Base):
    __tablename__ = "mtm_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    sl_pct = Column(Float, default=10.0)
    tp_pct = Column(Float, default=20.0)
    trail_pct = Column(Float, default=1.0) # Move SL/TP by this much for every 1% profit
    is_active = Column(Boolean, default=False)
    peak_upnl_pct = Column(Float, default=0.0)
    
    user = relationship("User", back_populates="mtm_settings")
