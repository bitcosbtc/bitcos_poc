import requests
import hmac
import hashlib
import time
import urllib.parse
import json
from typing import Optional, Dict

class DeltaExchangeAPI:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.india.delta.exchange"):
        self.api_key = api_key.strip() if api_key else ""
        self.api_secret = api_secret.strip() if api_secret else ""
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
    
    def _generate_signature(self, method: str, endpoint: str, payload: str = "") -> tuple:
        timestamp = str(int(time.time()))
        signature_data = method + timestamp + endpoint + payload
        signature = hmac.new(
            self.api_secret.encode(),
            signature_data.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature, timestamp
    
    def _make_request(self, method: str, endpoint: str, payload: Dict = None) -> Dict:
        url = f"{self.base_url}{endpoint}"
        
        if method == "GET" and payload:
            payload_str = "?" + urllib.parse.urlencode(payload, doseq=True)
        elif method in ["POST", "PUT", "DELETE"] and payload:
            payload_str = json.dumps(payload, separators=( ',', ':' ))
        else:
            payload_str = ""
            
        signature, timestamp = self._generate_signature(method, endpoint, payload_str)
        
        headers = {
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }
        
        try:
            if method == "GET":
                if payload:
                    url = f"{url}{payload_str}"
                response = self.session.get(url, headers=headers)
            elif method == "POST":
                response = self.session.post(url, headers=headers, data=payload_str)
            elif method == "PUT":
                response = self.session.put(url, headers=headers, data=payload_str)
            elif method == "DELETE":
                response = self.session.delete(url, headers=headers, data=payload_str)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    print("RAW DELTA ERROR RESPONSE:", error_data)  # Debugging line to see expected signature context
                    if "error" in error_data and isinstance(error_data["error"], dict):
                        error_msg = error_data["error"].get("message") or error_data["error"].get("code") or str(error_data["error"])
                    else:
                        error_msg = error_data.get("message", error_data.get("error", str(e)))
                except (ValueError, json.JSONDecodeError):
                    error_msg = e.response.text if e.response.text else str(e)
            return {"error": error_msg, "success": False, "status_code": e.response.status_code if e.response else 500}
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_assets(self) -> Dict:
        return self._make_request("GET", "/v2/assets")
        
    def get_profile(self) -> Dict:
        return self._make_request("GET", "/v2/profile")
        
    def get_tickers(self, contract_types: Optional[str] = None, underlying_symbols: Optional[str] = None) -> Dict:
        params = {}
        if contract_types:
            params["contract_types"] = contract_types
        if underlying_symbols:
            params["underlying_asset_symbols"] = underlying_symbols
        return self._make_request("GET", "/v2/tickers", payload=params)
        
    def get_wallet_balances(self, asset_id: Optional[int] = None) -> Dict:
        params = {}
        if asset_id:
            params["asset_id"] = asset_id
        return self._make_request("GET", "/v2/wallet/balances", params)
    
    def get_positions(self) -> Dict:
        return self._make_request("GET", "/v2/positions/margined")
    
    def get_position(self, product_id: int) -> Dict:
        return self._make_request("GET", f"/v2/positions/{product_id}")
    
    def get_products(self) -> Dict:
        return self._make_request("GET", "/v2/products")
    
    def get_product(self, symbol: str) -> Dict:
        return self._make_request("GET", f"/v2/products/{symbol}")
    
    def place_order(self, product_id: int, side: str, order_type: str, 
                   size: float, price: Optional[float] = None,
                   stop_price: Optional[float] = None,
                   reduce_only: bool = False) -> Dict:
        
        # Delta Exchange size is always integer representing number of contracts
        int_size = int(size)
        
        # Mapping order types to Delta's expected strings
        # Robust check to handle both "market" and "market_order"
        low_type = order_type.lower()
        if "market" in low_type:
            dt_order_type = "market_order"
        else:
            dt_order_type = "limit_order"
        
        payload = {
            "product_id": int(product_id),
            "size": int_size,
            "side": side.lower(),
            "order_type": dt_order_type,
            "time_in_force": "gtc",
            "reduce_only": reduce_only
        }
        
        # Delta Exchange expects limit_price as a string or number, better string
        if price is not None and price > 0:
            payload["limit_price"] = str(price)
        
        if stop_price is not None and stop_price > 0:
            payload["stop_price"] = str(stop_price)
            
        return self._make_request("POST", "/v2/orders", payload)
    
    def get_orders(self, product_id: Optional[int] = None, state: Optional[str] = None) -> Dict:
        params = {}
        if product_id:
            params["product_id"] = product_id
        if state:
            params["state"] = state
        return self._make_request("GET", "/v2/orders", params)
    
    def cancel_order(self, order_id: str, product_id: Optional[int] = None) -> Dict:
        try:
            # According to the REST API documentation (Step 1742),
            # individual cancellation is a DELETE to /v2/orders with a body.
            # Path-based deletion (/v2/orders/{id}) is likely not supported for all types.
            payload = {"id": int(order_id)}
            if product_id:
                payload["product_id"] = int(product_id)
            
            return self._make_request("DELETE", "/v2/orders", payload)
        except (ValueError, TypeError):
            # Fallback if IDs are not numeric
            payload = {"id": order_id}
            if product_id:
                payload["product_id"] = product_id
            return self._make_request("DELETE", "/v2/orders", payload)
            
    def cancel_all_orders(self, product_id: Optional[int] = None) -> Dict:
        payload = {}
        if product_id:
            payload["product_id"] = product_id
        return self._make_request("DELETE", "/v2/orders/all", payload)
    
    def close_position(self, product_id: int) -> Dict:
        return self._make_request("POST", f"/v2/positions/{product_id}/close")
    
    def close_all_positions(self) -> Dict:
        return self._make_request("POST", "/v2/positions/close_all")
    
    def add_stop_loss(self, product_id: int, stop_loss_price: float, 
                     trail_amount: Optional[float] = None) -> Dict:
        payload = {
            "product_id": int(product_id),
            "stop_loss_order": {
                "order_type": "market_order",
                "stop_price": str(stop_loss_price)
            },
            "bracket_stop_trigger_method": "last_traded_price"
        }
        if trail_amount:
            payload["stop_loss_order"]["trail_amount"] = str(trail_amount)
            
        return self._make_request("POST", "/v2/orders/bracket", payload)
    
    def add_take_profit(self, product_id: int, take_profit_price: float) -> Dict:
        payload = {
            "product_id": int(product_id),
            "take_profit_order": {
                "order_type": "market_order",
                "stop_price": str(take_profit_price)
            },
            "bracket_stop_trigger_method": "last_traded_price"
        }
        return self._make_request("POST", "/v2/orders/bracket", payload)
    
    def get_fills(self, product_id: Optional[int] = None) -> Dict:
        params = {}
        if product_id:
            params["product_id"] = product_id
        return self._make_request("GET", "/v2/fills", params)
    
    def get_order_history(self, product_id: Optional[int] = None) -> Dict:
        params = {}
        if product_id:
            params["product_id"] = product_id
        return self._make_request("GET", "/v2/orders/history", params)
    
    def get_stats(self) -> Dict:
        return self._make_request("GET", "/v2/profile")
    
    def get_orderbook(self, symbol: str) -> Dict:
        return self._make_request("GET", f"/v2/l2orderbook/{symbol}")
    def get_trades(self, symbol: str) -> Dict:
        return self._make_request("GET", f"/v2/trades/{symbol}")
        
    def get_ticker(self, symbol: str) -> Dict:
        return self._make_request("GET", f"/v2/tickers/{symbol}")

    def set_leverage(self, product_id: int, leverage: float) -> Dict:
        payload = {
            "product_id": int(product_id),
            "leverage": str(leverage)
        }
        return self._make_request("POST", "/v2/orders/leverage", payload)