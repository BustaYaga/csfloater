"""
Diagnostic only - shows what the scanner actually sees per item, with NO
filters applied, so you can see real dip%/baseline numbers instead of
guessing why deals=0. Doesn't touch deals.db or config.json.

Run: python debug_scan.py
"""
import statistics

from clients.csfloat_client import CSFloatClient
from config_loader import load_config
import db

cfg = load_config()
client = CSFloatClient(cfg["csfloat_api_key"])

listings = client.fetch_listings(
    min_price_cents=int(cfg["min_price"] * 100),
    max_price_cents=int(cfg["max_price"] * 100),
    max_pages=cfg["scan_pages"],
    sort_by="most_recent",
    type_="buy_now",
)
print(f"Fetched {len(listings)} listings\n")

# --- Dump the FULL raw JSON of one listing so we can see CSFloat's actual
# field names instead of guessing. This is the ground truth.
import json
print("=== RAW listing JSON (first item) ===")
if listings:
    print(json.dumps(listings[0], indent=2))
print()

included = cfg["included_weapons"]
matched = 0
have_snapshots = 0
missing_reference = 0
rows = []

for listing in listings:
    info = listing.get("item", {})
    name = info.get("market_hash_name", "")
    if not name or not any(w in name for w in included):
        continue
    matched += 1

    listing_price = listing.get("price", 0) / 100.0

    # FIX: reference is top-level on the listing, not nested under "item"
    reference = listing.get("reference") or {}
    base_price_raw = reference.get("base_price")
    predicted_price_raw = reference.get("predicted_price")
    base_price = base_price_raw / 100.0 if isinstance(base_price_raw, (int, float)) and base_price_raw > 0 else None
    predicted_price = predicted_price_raw / 100.0 if isinstance(predicted_price_raw, (int, float)) and predicted_price_raw > 0 else None
    if base_price is None and predicted_price is None:
        missing_reference += 1

    days_tracked = db.count_snapshot_days(name)
    records = db.get_snapshot_history(name, days=cfg["baseline_window_days"] + 5)

    if days_tracked == 0:
        continue
    have_snapshots += 1

    baseline_price = statistics.median([r["price"] for r in records]) if records else None
    dip_pct = ((baseline_price - listing_price) / baseline_price * 100) if baseline_price else None
    # dip against CSFloat's float/pattern-adjusted predicted price (per-listing, no history needed)
    pred_dip_pct = ((predicted_price - listing_price) / predicted_price * 100) if predicted_price else None

    rows.append((name, listing_price, baseline_price, dip_pct, predicted_price, pred_dip_pct, days_tracked, len(records)))

print(f"Matched included_weapons filter: {matched}")
print(f"Of those, have >=1 snapshot day: {have_snapshots}")
print(f"Of those matched, missing reference entirely: {missing_reference}\n")

rows.sort(key=lambda r: (r[3] is None, r[3] if r[3] is not None else 0))
print(f"{'name':<40} {'current':>8} {'baseline':>9} {'dip%':>7} {'predicted':>9} {'pred_dip%':>10} {'days':>5} {'#recs':>6}")
for name, price, baseline, dip, pred, pred_dip, days, n in rows[:30]:
    dip_str = f"{dip:.1f}" if dip is not None else "N/A"
    baseline_str = f"{baseline:.2f}" if baseline is not None else "N/A"
    pred_str = f"{pred:.2f}" if pred is not None else "N/A"
    pred_dip_str = f"{pred_dip:.1f}" if pred_dip is not None else "N/A"
    print(f"{name:<40} {price:>8.2f} {baseline_str:>9} {dip_str:>7} {pred_str:>9} {pred_dip_str:>10} {days:>5} {n:>6}")