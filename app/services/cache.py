import asyncio
from typing import Dict, Any, Set

class GlobalCache:
    def __init__(self):
        self.mark_prices: Dict[str, float] = {}
        self.positions: Dict[str, Any] = {} # Key: product_id_broker_id
        self.balances: Dict[int, Dict[str, Any]] = {} # Key: broker_id
        self.orders: Dict[int, Dict[str, Any]] = {} # Key: broker_id, Value: Dict[str, Any] (Key: order_id)
        
        # State flags to track if cache has been warmed (via WS snapshot or initial REST query)
        self.balances_warmed: Set[int] = set()
        self.positions_warmed: Set[int] = set()
        self.orders_warmed: Set[int] = set()

    def update_price(self, symbol: str, price: float):
        self.mark_prices[symbol] = price

    def update_position(self, key: str, pos_data: Dict[str, Any]):
        self.positions[key] = pos_data

    def update_balances(self, broker_id: int, balances: Dict[str, Any]):
        self.balances[broker_id] = balances
        self.balances_warmed.add(broker_id)

    def update_order(self, broker_id: int, order_data: Dict[str, Any]):
        if broker_id not in self.orders:
            self.orders[broker_id] = {}
        order_id = str(order_data.get("id") or order_data.get("order_id") or "")
        if order_id:
            self.orders[broker_id][order_id] = order_data
        self.orders_warmed.add(broker_id)

    def set_positions_warmed(self, broker_id: int):
        self.positions_warmed.add(broker_id)

    def set_orders_warmed(self, broker_id: int):
        self.orders_warmed.add(broker_id)

global_cache = GlobalCache()

