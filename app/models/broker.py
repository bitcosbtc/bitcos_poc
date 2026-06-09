from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class Broker(Base):
    __tablename__ = "brokers"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    broker_name = Column(String, default="Delta Exchange")
    broker_login_id = Column(String, nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    secret_key_encrypted = Column(Text, nullable=False)
    totp_secret_encrypted = Column(Text, nullable=True)
    name_tag = Column(String, nullable=False)
    redirect_url = Column(String)
    status = Column(String, default="ACTIVE")
    access_token = Column(Text, nullable=True)
    token_generated_at = Column(DateTime, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="brokers")