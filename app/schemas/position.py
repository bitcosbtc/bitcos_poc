from pydantic import BaseModel
from typing import Optional

class PositionResponse(BaseModel):
    id: int
    symbol: str
    product_id: Optional[int]
    size: float
    entry_price: float
    mark_price: Optional[float]
    index_price: Optional[float]
    notional: Optional[float]
    margin: Optional[float]
    unrealized_pnl: Optional[float]
    realized_pnl: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    
    class Config:
        from_attributes = True

class StopLossRequest(BaseModel):
    product_id: int
    stop_loss_price: float
    trail_amount: Optional[float] = None

class TakeProfitRequest(BaseModel):
    product_id: int
    take_profit_price: float