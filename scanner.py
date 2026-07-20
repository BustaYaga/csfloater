"""
Dip / mean-reversion scanner.

Strategy: for each CSFloat listing in our watch categories, pull the item's
recent sales history from cs2.sh, compute a baseline price (median over
`baseline_window_days`, excluding the most recent `recent_days_for_current_price`),
and flag it if the current listing is meaningfully below that baseline AND
has enough sales volume to be confident you can exit later.

This directly implements the pattern described: "was $8 a week ago, is $5
now -> buy, expect reversion toward $8."
"""
import statistics
import time

from clients.csfloat_client import CSFloatClient
from clients.history_client import HistoryClient
import db


class DipScanner:
    def __init__(self, config):
        self.config = config
        self.csfloat = CSFloatClient(config["csfloat_api_key"])
        self.history = HistoryClient(config["cs2sh_api_key"])
        self._history_cache = {}  # market_hash_name -> (timestamp, records)

    # ---------- data gathering ----------

    def fetch_candidate_listings(self):
        cfg = self.config
        return self.csfloat.fetch_listings(
            min_price_cents=int(cfg["min_price"] * 100),
            max_price_cents=int(cfg["max_price"] * 100),
            max_pages=cfg["scan_pages"],
            sort_by="most_recent",
            type_="buy_now",
        )

    def _get_history(self, market_hash_name):
        cached = self._history_cache.get(market_hash_name)
        if cached and (time.time() - cached[0]) < 3600:
            return cached[1]
        records = self.history.get_sales_history(
            market_hash_name, days=self.config["history_lookback_days"]
        )
        self._history_cache[market_hash_name] = (time.time(), records)
        return records

    # ---------- strategy ----------

    def is_profitable(self, profit, base_price):
        if base_price <= 0:
            return False
        profit_pct = (profit / base_price) * 100
        for tier in self.config.get("dynamic_profit_targets", []):
            if base_price <= tier["max_skin_price"]:
                return profit >= tier["min_profit_usd"] or profit_pct >= tier["min_profit_percentage"]
        return False

    def analyze_dip_deals(self, listings):
        cfg = self.config
        deals = []
        included = cfg["included_weapons"]

        for item in listings:
            try:
                info = item.get("item", {})
                name = info.get("market_hash_name", "")
                if not name or not any(w in name for w in included):
                    continue
                if info.get("is_souvenir"):
                    continue

                listing_price = item.get("price", 0) / 100.0

                records = self._get_history(name)
                if len(records) < cfg["min_sales_in_window"]:
                    continue  # not enough data / not liquid enough

                recent_cutoff_days = cfg["recent_days_for_current_price"]
                baseline_window = cfg["baseline_window_days"]

                # split records into "recent" (informs current price context,
                # excluded from baseline) and "baseline" windows
                baseline_records = records[:-recent_cutoff_days] if recent_cutoff_days else records
                baseline_records = baseline_records[-baseline_window:]

                if len(baseline_records) < cfg["min_sales_in_window"]:
                    continue

                baseline_prices = [r["price"] for r in baseline_records]
                baseline_price = statistics.median(baseline_prices)
                sales_in_window = sum(r.get("volume", 1) for r in baseline_records)

                if baseline_price <= 0:
                    continue

                dip_pct = ((baseline_price - listing_price) / baseline_price) * 100

                if not (cfg["min_dip_percentage"] <= dip_pct <= cfg["max_dip_percentage"]):
                    continue

                fee = listing_price * (cfg["csfloat_fee_percentage"] / 100.0)
                est_profit = (baseline_price - listing_price) - fee

                if not self.is_profitable(est_profit, listing_price):
                    continue

                est_profit_pct = (est_profit / listing_price) * 100 if listing_price > 0 else 0

                deals.append({
                    "listing_id": item.get("id"),
                    "market_hash_name": name,
                    "strategy": "Historical Dip / Mean Reversion",
                    "current_price": listing_price,
                    "baseline_price": baseline_price,
                    "dip_percentage": dip_pct,
                    "est_profit": est_profit,
                    "est_profit_percentage": est_profit_pct,
                    "sales_in_window": sales_in_window,
                    "url": f"https://csfloat.com/item/{item.get('id')}",
                    "details": {
                        "baseline_window_days": baseline_window,
                        "recent_sale_prices": baseline_prices[-5:],
                    },
                })
            except Exception as e:
                print(f"[DipScanner] Error analyzing {item.get('id')}: {e}")

        return deals

    # ---------- run loop ----------

    def run_once(self):
        print("[DipScanner] Fetching listings...")
        listings = self.fetch_candidate_listings()
        print(f"[DipScanner] Got {len(listings)} listings, checking history...")
        deals = self.analyze_dip_deals(listings)
        if deals:
            saved = db.save_deals(deals)
            print(f"[DipScanner] Found {len(deals)} candidate deals, saved {saved} new.")
            for d in deals:
                print(f"  - {d['market_hash_name']:<40} ${d['current_price']:.2f} "
                      f"(baseline ${d['baseline_price']:.2f}, dip {d['dip_percentage']:.1f}%, "
                      f"est. profit ${d['est_profit']:.2f})")
        else:
            print("[DipScanner] No qualifying deals this cycle.")
        return deals

    def run_continuous(self):
        db.init_db()
        interval = self.config.get("scan_interval_seconds", 900)
        while True:
            try:
                self.run_once()
            except Exception as e:
                print(f"[DipScanner] CRITICAL error in scan cycle: {e}")
            print(f"[DipScanner] Sleeping {interval}s...\n")
            time.sleep(interval)


if __name__ == "__main__":
    from config_loader import load_config
    cfg = load_config()
    db.init_db()
    DipScanner(cfg).run_once()
