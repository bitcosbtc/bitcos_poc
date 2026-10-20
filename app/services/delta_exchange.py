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
        self.alt_base_url = "https://api.delta.exchange" if "india" in self.base_url else "https://api.india.delta.exchange"
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=15, pool_maxsize=30, max_retries=2)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
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
        
        if method == "GET":
            payload_str = ("?" + urllib.parse.urlencode(payload, doseq=True)) if payload else ""
        elif method in ["POST", "PUT", "DELETE"]:
            if payload is not None:
                payload_str = json.dumps(payload, separators=(',', ':'))
            else:
                payload_str = ""
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
                response = self.session.get(url, headers=headers, timeout=5)
            elif method == "POST":
                response = self.session.post(url, headers=headers, data=payload_str, timeout=5)
            elif method == "PUT":
                response = self.session.put(url, headers=headers, data=payload_str, timeout=5)
            elif method == "DELETE":
                response = self.session.delete(url, headers=headers, data=payload_str, timeout=5)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            # Failover to alternate Delta Exchange endpoint if primary domain encounters DNS/connection drop
            if hasattr(self, "alt_base_url") and self.alt_base_url:
                try:
                    alt_url = f"{self.alt_base_url}{endpoint}"
                    if method == "GET":
                        if payload: alt_url = f"{alt_url}{payload_str}"
                        alt_resp = self.session.get(alt_url, headers=headers, timeout=5)
                    elif method == "POST":
                        alt_resp = self.session.post(alt_url, headers=headers, data=payload_str, timeout=5)
                    elif method == "PUT":
                        alt_resp = self.session.put(alt_url, headers=headers, data=payload_str, timeout=5)
                    elif method == "DELETE":
                        alt_resp = self.session.delete(alt_url, headers=headers, data=payload_str, timeout=5)
                    alt_resp.raise_for_status()
                    # Swap active and alternate URL
                    self.base_url, self.alt_base_url = self.alt_base_url, self.base_url
                    return alt_resp.json()
                except Exception:
                    pass
            return {"error": "Connection to Delta Exchange failed across all endpoints", "success": False}
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
            "reduce_only": bool(reduce_only)
        }
        
        if dt_order_type == "limit_order":
            payload["time_in_force"] = "gtc"
        else:
            payload["time_in_force"] = "ioc"
        
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
            payload = {"id": int(order_id)}
            if product_id:
                payload["product_id"] = int(product_id)
            
            return self._make_request("DELETE", "/v2/orders", payload)
        except (ValueError, TypeError):
            payload = {"id": order_id}
            if product_id:
                payload["product_id"] = product_id
            return self._make_request("DELETE", "/v2/orders", payload)
            
    def cancel_all_orders(self, product_id: Optional[int] = None) -> Dict:
        payload = {}
        if product_id:
            payload["product_id"] = int(product_id)
        return self._make_request("DELETE", "/v2/orders/all", payload)
    
    def close_position(self, product_id: int) -> Dict:
        """
        Close a position on Delta Exchange by executing an opposite reduce-only market order.
        """
        try:
            pos = None
            pos_res = self.get_position(product_id)
            if pos_res.get("success", True) and pos_res.get("result"):
                pos = pos_res["result"]

            if not pos or not pos.get("size") or float(pos.get("size", 0)) == 0:
                all_res = self.get_positions()
                if all_res.get("success", True):
                    positions = all_res.get("result", [])
                    for p in positions:
                        if int(p.get("product_id", 0)) == int(product_id):
                            pos = p
                            break

            if pos and pos.get("size"):
                size = float(pos.get("size", 0))
                if size != 0:
                    opposite_side = "sell" if size > 0 else "buy"
                    abs_size = abs(int(size))
                    return self.place_order(
                        product_id=int(product_id),
                        side=opposite_side,
                        order_type="market_order",
                        size=abs_size,
                        reduce_only=True
                    )

            return {"success": True, "message": f"Position for product {product_id} is already closed", "result": {}}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def close_all_positions(self) -> Dict:
        """
        Close all open positions on Delta Exchange and cancel all open orders.
        """
        try:
            payload = {
                "close_all_portfolio": True,
                "close_all_isolated": True,
                "user_id": 0
            }
            self._make_request("POST", "/v2/positions/close_all", payload)
        except Exception:
            pass

        try:
            pos_res = self.get_positions()
            if pos_res.get("success", True):
                for p in pos_res.get("result", []):
                    size = float(p.get("size", 0))
                    pid = p.get("product_id")
                    if size != 0 and pid:
                        opposite_side = "sell" if size > 0 else "buy"
                        abs_size = abs(int(size))
                        self.place_order(
                            product_id=int(pid),
                            side=opposite_side,
                            order_type="market_order",
                            size=abs_size,
                            reduce_only=True
                        )
        except Exception:
            pass

        try:
            self.cancel_all_orders()
        except Exception:
            pass

        return {"success": True, "message": "All positions closed and orders cancelled"}
    
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

    def update_bracket_order(self, order_id: int, product_id: int, bracket_trail_amount: float) -> Dict:
        payload = {
            "id": int(order_id),
            "product_id": int(product_id),
            "bracket_trail_amount": str(bracket_trail_amount)
        }
        return self._make_request("PUT", "/v2/orders/bracket", payload)

