from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class BrokerCreate(BaseModel):
    broker_name: str = "Delta Exchange"
    broker_login_id: str
    api_key: str
    secret_key: str
    totp_secret: Optional[str] = None
    name_tag: str
    redirect_url: Optional[str] = None

class BrokerUpdate(BaseModel):
    broker_login_id: Optional[str] = None
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    totp_secret: Optional[str] = None
    name_tag: Optional[str] = None
    status: Optional[str] = None

class BrokerResponse(BaseModel):
    id: int
    broker_name: str
    broker_login_id: str
    name_tag: str
    status: str
    token_generated_at: Optional[datetime]
    added_at: datetime
    
    app_id_masked: str
    app_secret_masked: str
    
    class Config:
        from_attributes = True