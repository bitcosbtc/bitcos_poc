import asyncio
from typing import Dict, Any

class GlobalCache:
    def __init__(self):
        self.mark_prices: Dict[str, float] = {}
        self.positions: Dict[str, Any] = {} # Key: product_id_broker_id
        self.balances: Dict[int, Dict[str, Any]] = {} # Key: broker_id

    def update_price(self, symbol: str, price: float):
        self.mark_prices[symbol] = price

    def update_position(self, key: str, pos_data: Dict[str, Any]):
        self.positions[key] = pos_data

    def update_balances(self, broker_id: int, balances: Dict[str, Any]):
        self.balances[broker_id] = balances

global_cache = GlobalCache()
