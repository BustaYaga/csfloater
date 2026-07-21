# """
# Run this once a day (cron / Windows Task Scheduler) to build your own
# first-party CSFloat price history. This IS your history source going
# forward — no third-party data needed.

# Windows Task Scheduler: trigger daily, action `python snapshot_job.py`,
# start-in set to the project folder.
# Cron (Linux/Mac): 0 6 * * * cd /path/to/csfloat-scanner && python snapshot_job.py
# """
import datetime
import statistics
from collections import defaultdict

from clients.csfloat_client import CSFloatClient
from config_loader import load_config
import db


def take_snapshot():
    cfg = load_config()
    client = CSFloatClient(cfg["csfloat_api_key"])

    listings = client.fetch_listings(
        min_price_cents=int(cfg["min_price"] * 100),
        max_price_cents=int(cfg["max_price"] * 100),
        max_pages=cfg["scan_pages"],
        sort_by="most_recent",
    )

    by_item = defaultdict(list)
    for listing in listings:
        info = listing.get("item", {})
        name = info.get("market_hash_name", "")
        if not name or not any(w in name for w in cfg["included_weapons"]):
            continue
        if info.get("is_souvenir"):
            continue
        if info.get("wear_name") not in cfg["allowed_wears"]:
                    continue
        reference = listing.get("reference") or {}
        predicted_raw = reference.get("predicted_price")
        predicted = predicted_raw / 100.0 if isinstance(predicted_raw, (int, float)) and predicted_raw > 0 else None
        if predicted:
            by_item[name].append(predicted)

    today = datetime.date.today().isoformat()
    records = [
        {
            "market_hash_name": name,
            "date": today,
            "price": statistics.median(prices),
            "listing_count": len(prices),
        }
        for name, prices in by_item.items()
    ]

    db.init_db()
    db.save_snapshot(records)
    print(f"[snapshot_job] Saved {len(records)} item snapshots for {today}.")


if __name__ == "__main__":
    take_snapshot()