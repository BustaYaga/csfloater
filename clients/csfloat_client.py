# """
# Thin client around the official CSFloat listings API.
# Docs: https://docs.csfloat.com/  (GET /api/v1/listings)

# Note: the official API is listings-only (current snapshot). It does NOT
# provide historical sales data - see snapshot_job.py and db.py for the first-party history solution.
# """
import time
import requests


class CSFloatClient:
    BASE_URL = "https://csfloat.com/api/v1/listings"

    def __init__(self, api_key: str, request_delay: float = 2.5):
        self.api_key = api_key
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "User-Agent": "csfloat-dip-scanner/1.0",
        })

    def fetch_listings(self, min_price_cents=None, max_price_cents=None,
                        max_pages=10, sort_by="most_recent", type_=None,
                        def_index=None):
        """
        Pull listings across up to max_pages, following the opaque cursor.
        Returns a flat list of listing dicts.
        """
        all_items = []
        cursor = None

        for page in range(max_pages):
            params = {"sort_by": sort_by, "limit": 50}
            if min_price_cents is not None:
                params["min_price"] = min_price_cents
            if max_price_cents is not None:
                params["max_price"] = max_price_cents
            if type_:
                params["type"] = type_
            if def_index:
                params["def_index"] = def_index
            if cursor:
                params["cursor"] = cursor

            data = self._get_with_retry(params)
            if data is None:
                break

            # API has been observed to return either a bare list or a
            # {"data": [...], "cursor": "..."} envelope - handle both.
            if isinstance(data, list):
                page_items = data
                cursor = None
            else:
                page_items = data.get("data", [])
                cursor = data.get("cursor")

            if not page_items:
                break

            all_items.extend(page_items)

            if not cursor:
                break

            time.sleep(self.request_delay)

        return all_items

    def _get_with_retry(self, params, max_retries=3):
        for attempt in range(max_retries):
            try:
                resp = self.session.get(self.BASE_URL, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = 60
                    print(f"[CSFloatClient] Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 403:
                    print("[CSFloatClient] 403 Forbidden - check your API key in config.json")
                    return None
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                print(f"[CSFloatClient] Request error (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(3)
        return None
