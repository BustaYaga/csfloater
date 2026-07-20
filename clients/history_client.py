"""
Client for cs2.sh's historical price/volume data.

This is intentionally a thin, easily-adjustable wrapper. cs2.sh's
publicly described endpoints (see https://cs2.sh/csfloat-api) are:

  - /v1/archive/csfloat   -> daily completed-sale price & volume, back to 2022
                             (this is the one we want for your dip strategy)
  - /v1/prices/history    -> continuously updating ask/bid OHLC candles
                             (5m/30m/1h/1d), useful if you want live ask/bid
                             tracking instead of/in addition to sales

Once you have your key, double check the exact request/auth shape against
cs2.sh's own docs (param names below are my best-effort placeholder based on
their marketing page, not a confirmed schema) and adjust `_request()` and
`get_sales_history()` accordingly. Everything downstream in scanner.py just
expects get_sales_history() to return the list-of-dicts shape documented below,
so as long as you keep that return shape, nothing else needs to change.
"""
import requests


class HistoryClient:
    BASE_URL = "https://cs2.sh"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        # TODO: confirm auth header name/format against cs2.sh docs once you
        # have a key - this is a common pattern but may need adjusting.
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
        })

    def get_sales_history(self, market_hash_name: str, days: int = 30):
        """
        Returns a list of daily sale records, oldest first:
            [{"date": "2026-06-20", "price": 5.23, "volume": 4}, ...]

        Backed by cs2.sh's /v1/archive/csfloat endpoint (true completed
        sales, not just listings).
        """
        params = {
            "market_hash_name": market_hash_name,
            "market": "csfloat",
            "days": days,
        }
        data = self._request("/v1/archive/csfloat", params)
        if not data:
            return []

        # Normalize whatever shape comes back into our flat list-of-dicts
        # contract. Adjust the key names below once you see a real response.
        records = data.get("data", data if isinstance(data, list) else [])
        normalized = []
        for r in records:
            try:
                normalized.append({
                    "date": r.get("date") or r.get("timestamp"),
                    "price": float(r.get("price")),
                    "volume": int(r.get("volume", 0)),
                })
            except (TypeError, ValueError):
                continue
        return normalized

    def _request(self, path, params):
        try:
            resp = self.session.get(f"{self.BASE_URL}{path}", params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"[HistoryClient] Error fetching history: {e}")
            return None
