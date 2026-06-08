from pydantic import BaseModel
from typing import Optional

class MTMSettingsBase(BaseModel):
    sl_pct: float
    tp_pct: float
    trail_pct: float = 1.0
    is_active: bool = False

class MTMSettingsUpdate(MTMSettingsBase):
    peak_upnl_pct: Optional[float] = None

class MTMSettingsResponse(MTMSettingsBase):
    id: int
    user_id: int
    peak_upnl_pct: float

    class Config:
        from_attributes = True
