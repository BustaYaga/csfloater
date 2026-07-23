"""
Thin client around the official CSFloat listings API.
Docs: https://docs.csfloat.com/  (GET /api/v1/listings)

Note: the official API is listings-only (current snapshot). It does NOT
provide historical sales data - see snapshot_job.py and db.py for
the first-party history solution.
"""
import json
import os
import time
import requests


class CSFloatClient:
    BASE_URL = "https://csfloat.com/api/v1/listings"

    def __init__(self, api_key: str, request_delay: float = 3.0,
                 rate_state_file: str = "rate_state.json"):
        self.api_key = api_key
        self.request_delay = request_delay  # fixed delay between every request
        self.rate_state_file = rate_state_file
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "User-Agent": "csfloat-dip-scanner/1.0",
        })
        # Real rate-limit state, learned from CSFloat's own response headers
        # (X-Ratelimit-Limit/Remaining/Reset). Persisted to disk so a NEW
        # process (e.g. the next scheduled run) can check status before
        # making any request at all.
        self.rate_limit = None
        self.rate_remaining = None
        self.rate_reset = None
        self._load_rate_state()

    def _load_rate_state(self):
        if not os.path.exists(self.rate_state_file):
            return
        try:
            with open(self.rate_state_file, encoding="utf-8") as f:
                data = json.load(f)
            self.rate_limit = data.get("limit")
            self.rate_remaining = data.get("remaining")
            self.rate_reset = data.get("reset")
        except (json.JSONDecodeError, OSError):
            pass

    def _save_rate_state(self):
        try:
            with open(self.rate_state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "limit": self.rate_limit,
                    "remaining": self.rate_remaining,
                    "reset": self.rate_reset,
                }, f)
        except OSError:
            pass

    def _update_rate_info(self, resp):
        headers = resp.headers
        try:
            if "X-Ratelimit-Limit" in headers:
                self.rate_limit = int(headers["X-Ratelimit-Limit"])
            if "X-Ratelimit-Remaining" in headers:
                self.rate_remaining = int(headers["X-Ratelimit-Remaining"])
            if "X-Ratelimit-Reset" in headers:
                self.rate_reset = int(headers["X-Ratelimit-Reset"])
            self._save_rate_state()
        except (TypeError, ValueError):
            pass  # malformed header - just keep using whatever we had before

    def seconds_until_reset(self):
        if self.rate_reset is None:
            return None
        return max(0, self.rate_reset - time.time())

    def check_rate_limit_status(self, stop_threshold: int = 10, warn_threshold: int = 50):
        """
        Returns ('ok'|'warning'|'stop', seconds_until_reset_or_None).
        If the last-known reset time has already passed, treats the window
        as having (probably) refreshed and returns 'ok' - we can't know the
        true remaining count without a request, but a passed reset means
        the old low number is stale.
        """
        if self.rate_remaining is None or self.rate_reset is None:
            return "ok", None  # never made a request yet - nothing to check

        remaining_seconds = self.seconds_until_reset()
        if remaining_seconds is not None and remaining_seconds <= 0:
            return "ok", None  # window should have reset since we last checked

        if self.rate_remaining <= stop_threshold:
            return "stop", remaining_seconds
        if self.rate_remaining <= warn_threshold:
            return "warning", remaining_seconds
        return "ok", remaining_seconds

    def fetch_listings(self, min_price_cents=None, max_price_cents=None,
                        max_pages=10, sort_by="most_recent", type_=None,
                        def_index=None, paint_index=None):
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
            if paint_index:
                params["paint_index"] = paint_index
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

        return all_items

    def _get_with_retry(self, params, max_retries=3):
        for attempt in range(max_retries):
            try:
                time.sleep(self.request_delay)
                resp = self.session.get(self.BASE_URL, params=params, timeout=30)
                self._update_rate_info(resp)
                if resp.status_code == 429:
                    # Shouldn't normally trigger now that we self-pace off real
                    # headers, but keep as a safety net (e.g. another process
                    # sharing this key, or a missed header).
                    wait = 300 * (attempt + 1)
                    print(f"[CSFloatClient] Rate limited (attempt {attempt+1}/{max_retries}). "
                          f"Waiting {wait}s...")
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
        print("[CSFloatClient] Giving up on this request after repeated failures.")
        return None