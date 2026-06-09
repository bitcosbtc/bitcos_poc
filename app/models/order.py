from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime
from ..database import Base

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    broker_id = Column(Integer, ForeignKey("brokers.id"), nullable=False)
    order_id = Column(String, unique=True)
    symbol = Column(String, nullable=False)
    product_id = Column(Integer)
    side = Column(String)
    order_type = Column(String)
    size = Column(Float)
    price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    status = Column(String)
    filled_size = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)