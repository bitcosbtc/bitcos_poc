from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class OrderCreate(BaseModel):
    product_id: int
    side: str
    order_type: str
    size: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    reduce_only: Optional[bool] = False

class OrderResponse(BaseModel):
    id: int
    order_id: str
    symbol: str
    product_id: Optional[int]
    side: str
    order_type: str
    size: float
    price: Optional[float]
    stop_price: Optional[float]
    status: str
    filled_size: float
    created_at: datetime
    
    class Config:
        from_attributes = True