"""
GATE.io Futures API Client

Obsługuje autentykację HMAC-SHA512 i operacje na futures.
"""
import time
import hmac
import hashlib
import json
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode

import requests
import pandas as pd

from config import config


class GateIOError(Exception):
    """GATE.io API Error"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"GATE.io Error {code}: {message}")


class GateIOClient:
    """GATE.io Futures API Client"""

    def __init__(self):
        self.cfg = config.gate
        self.api_key = self.cfg.api_key
        self.api_secret = self.cfg.api_secret
        self.base_url = self.cfg.base_url
        self.session = requests.Session()

    def _sign(self, method: str, url: str, query_string: str = "",
              body: str = "") -> Dict[str, str]:
        """
        Generate HMAC-SHA512 signature for API request

        Signature = HEX(HMAC_SHA512(secret, signature_string))
        signature_string = method + "\n" + url + "\n" + query_string + "\n" +
                          HEX(SHA512(body)) + "\n" + timestamp
        """
        timestamp = str(int(time.time()))

        # Hash body
        body_hash = hashlib.sha512(body.encode()).hexdigest()

        # Build signature string
        sign_string = f"{method}\n{url}\n{query_string}\n{body_hash}\n{timestamp}"

        # Generate signature
        signature = hmac.new(
            self.api_secret.encode(),
            sign_string.encode(),
            hashlib.sha512
        ).hexdigest()

        return {
            "KEY": self.api_key,
            "Timestamp": timestamp,
            "SIGN": signature,
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str,
                 params: Dict = None, body: Dict = None,
                 signed: bool = False) -> Any:
        """Make API request"""
        url_path = f"/api/v4{endpoint}"
        full_url = f"{self.base_url.rstrip('/api/v4')}{url_path}"

        query_string = urlencode(params) if params else ""
        body_str = json.dumps(body) if body else ""

        headers = {}
        if signed:
            headers = self._sign(method, url_path, query_string, body_str)

        try:
            if method == "GET":
                response = self.session.get(
                    full_url,
                    params=params,
                    headers=headers,
                    timeout=10
                )
            elif method == "POST":
                response = self.session.post(
                    full_url,
                    params=params,
                    data=body_str,
                    headers=headers,
                    timeout=10
                )
            elif method == "DELETE":
                response = self.session.delete(
                    full_url,
                    params=params,
                    headers=headers,
                    timeout=10
                )
            else:
                raise ValueError(f"Unsupported method: {method}")

            data = response.json()

            # Check for error
            if isinstance(data, dict) and "label" in data:
                raise GateIOError(
                    response.status_code,
                    data.get("message", data.get("label", "Unknown error"))
                )

            return data

        except requests.RequestException as e:
            raise GateIOError(0, str(e))

    # ==========================================
    # Public Endpoints (no auth required)
    # ==========================================

    def get_contracts(self, settle: str = "usdt") -> List[Dict]:
        """Get all futures contracts"""
        return self._request("GET", f"/futures/{settle}/contracts")

    def get_contract(self, symbol: str, settle: str = "usdt") -> Dict:
        """Get single contract info"""
        return self._request("GET", f"/futures/{settle}/contracts/{symbol}")

    def get_tickers(self, symbol: str = None, settle: str = "usdt") -> List[Dict]:
        """Get futures tickers"""
        params = {}
        if symbol:
            params["contract"] = symbol
        return self._request("GET", f"/futures/{settle}/tickers", params)

    def get_ticker(self, symbol: str, settle: str = "usdt") -> Dict:
        """Get single ticker"""
        tickers = self.get_tickers(symbol, settle)
        return tickers[0] if tickers else {}

    def get_order_book(self, symbol: str, settle: str = "usdt",
                       limit: int = 20) -> Dict:
        """Get order book"""
        params = {"contract": symbol, "limit": limit}
        return self._request("GET", f"/futures/{settle}/order_book", params)

    def get_candlesticks(self, symbol: str, interval: str = "5m",
                         limit: int = 200, settle: str = "usdt") -> pd.DataFrame:
        """
        Get OHLCV candlesticks

        Intervals: 10s, 1m, 5m, 15m, 30m, 1h, 4h, 8h, 1d, 7d, 30d
        """
        params = {
            "contract": symbol,
            "interval": interval,
            "limit": limit
        }

        data = self._request("GET", f"/futures/{settle}/candlesticks", params)

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data, columns=["t", "v", "c", "h", "l", "o"])
        df = df.rename(columns={
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume"
        })

        # Convert timestamp to datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")

        # Convert to float
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        return df.sort_values("timestamp").reset_index(drop=True)

    def get_funding_rate(self, symbol: str, settle: str = "usdt") -> float:
        """Get current funding rate"""
        ticker = self.get_ticker(symbol, settle)
        return float(ticker.get("funding_rate", 0))

    # ==========================================
    # Private Endpoints (auth required)
    # ==========================================

    def get_account(self, settle: str = "usdt") -> Dict:
        """Get futures account info"""
        return self._request("GET", f"/futures/{settle}/accounts", signed=True)

    def get_positions(self, symbol: str = None, settle: str = "usdt") -> List[Dict]:
        """Get positions"""
        params = {}
        if symbol:
            params["contract"] = symbol
        return self._request("GET", f"/futures/{settle}/positions", params, signed=True)

    def get_position(self, symbol: str, settle: str = "usdt") -> Optional[Dict]:
        """Get single position"""
        positions = self.get_positions(symbol, settle)
        for pos in positions:
            if pos.get("contract") == symbol:
                return pos
        return None

    def create_order(self, symbol: str, size: int, price: float = None,
                     reduce_only: bool = False, settle: str = "usdt",
                     tif: str = "gtc") -> Dict:
        """
        Create futures order

        Args:
            symbol: Contract name (e.g., BTC_USDT)
            size: Order size (positive for long, negative for short)
            price: Limit price (None for market order)
            reduce_only: Only reduce position
            settle: Settlement currency
            tif: Time in force (gtc, ioc, poc)
        """
        body = {
            "contract": symbol,
            "size": size,
            "reduce_only": reduce_only,
            "tif": tif
        }

        if price:
            body["price"] = str(price)
        else:
            body["price"] = "0"  # Market order

        return self._request("POST", f"/futures/{settle}/orders", body=body, signed=True)

    def cancel_order(self, order_id: str, settle: str = "usdt") -> Dict:
        """Cancel order"""
        return self._request("DELETE", f"/futures/{settle}/orders/{order_id}", signed=True)

    def cancel_all_orders(self, symbol: str, settle: str = "usdt") -> List[Dict]:
        """Cancel all orders for symbol"""
        params = {"contract": symbol}
        return self._request("DELETE", f"/futures/{settle}/orders", params, signed=True)

    def get_orders(self, symbol: str = None, status: str = "open",
                   settle: str = "usdt", limit: int = 100) -> List[Dict]:
        """Get orders"""
        params = {"status": status, "limit": limit}
        if symbol:
            params["contract"] = symbol
        return self._request("GET", f"/futures/{settle}/orders", params, signed=True)

    def get_order(self, order_id: str, settle: str = "usdt") -> Dict:
        """Get single order"""
        return self._request("GET", f"/futures/{settle}/orders/{order_id}", signed=True)

    def update_position_leverage(self, symbol: str, leverage: int,
                                  settle: str = "usdt") -> Dict:
        """Update position leverage"""
        params = {"contract": symbol, "leverage": str(leverage)}
        return self._request("POST", f"/futures/{settle}/positions/{symbol}/leverage",
                            params, signed=True)

    def update_position_margin(self, symbol: str, change: float,
                               settle: str = "usdt") -> Dict:
        """Update position margin"""
        params = {"contract": symbol, "change": str(change)}
        return self._request("POST", f"/futures/{settle}/positions/{symbol}/margin",
                            params, signed=True)

    def close_position(self, symbol: str, settle: str = "usdt") -> Dict:
        """Close position at market price"""
        position = self.get_position(symbol, settle)
        if not position or position.get("size", 0) == 0:
            return {"message": "No position to close"}

        size = position["size"]
        # Reverse the position
        return self.create_order(symbol, -size, settle=settle)

    # ==========================================
    # Helper Methods
    # ==========================================

    def get_balance(self, settle: str = "usdt") -> float:
        """Get available balance"""
        account = self.get_account(settle)
        return float(account.get("available", 0))

    def get_equity(self, settle: str = "usdt") -> float:
        """Get total equity"""
        account = self.get_account(settle)
        return float(account.get("total", 0))

    def calculate_position_size(self, symbol: str, risk_percent: float,
                                stop_loss_distance: float,
                                settle: str = "usdt") -> int:
        """
        Calculate position size based on risk

        Args:
            symbol: Contract name
            risk_percent: Risk as % of account (e.g., 1.0 for 1%)
            stop_loss_distance: Distance to stop loss in price

        Returns:
            Position size in contracts
        """
        balance = self.get_balance(settle)
        contract = self.get_contract(symbol, settle)

        risk_amount = balance * (risk_percent / 100)
        contract_size = float(contract.get("quanto_multiplier", 1))

        # Size = Risk Amount / (Stop Loss Distance * Contract Size)
        size = int(risk_amount / (stop_loss_distance * contract_size))

        return max(1, size)

    def test_connection(self) -> bool:
        """Test API connection"""
        try:
            self.get_contracts()
            return True
        except Exception:
            return False

    def test_authentication(self) -> bool:
        """Test API authentication"""
        try:
            self.get_account()
            return True
        except GateIOError:
            return False
