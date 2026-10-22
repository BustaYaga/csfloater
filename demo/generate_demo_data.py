"""
Build the synthetic demo dataset. Nothing here touches the network, an API
key or any real market data: prices come from a seeded random walk, so the
output is reproducible.

    python demo/generate_demo_data.py            # -> demo/demo.db, logs, scan position
    python demo/generate_demo_data.py --seed 7 --days 100

It also feeds a handful of fake live listings through the real
DipScanner.analyze_dip_deals(), so the "Flagged deals" table is produced by
the actual strategy code rather than hard-coded rows.
"""
import argparse
import datetime
import json
import math
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

WEAR_MULT = {"Factory New": 1.45, "Minimal Wear": 1.15, "Field-Tested": 1.0}
RARITY_PRICE = {  # (low, high) USD for a Field-Tested baseline
    "Consumer Grade": (4, 9), "Industrial Grade": (4, 10), "Mil-Spec Grade": (5, 14),
    "Restricted": (6, 22), "Classified": (9, 40), "Covert": (14, 70), "Contraband": (40, 70),
}


def build_items(rng, catalog, per_weapon):
    items = []
    for weapon, skins in catalog.items():
        entries = sorted(skins.values(), key=lambda e: e["name"])
        for entry in rng.sample(entries, min(per_weapon, len(entries))):
            lo, hi = RARITY_PRICE.get(entry.get("rarity"), (5, 20))
            base = math.exp(rng.uniform(math.log(lo), math.log(hi)))
            for wear, mult in WEAR_MULT.items():
                items.append({"name": f"{entry['name']} ({wear})", "price": base * mult,
                              "rarity": entry.get("rarity", "")})
    return items


def simulate(rng, item, dates, end_dip):
    """Daily median reference price: slow drift + noise, pulled back toward
    a moving anchor. end_dip (e.g. 0.2) knocks the last day down by 20%."""
    price = anchor = item["price"]
    drift = rng.uniform(-0.0015, 0.0008)
    popularity = rng.uniform(2, 24)
    rows = []
    for i, d in enumerate(dates):
        anchor *= 1 + drift + rng.gauss(0, 0.004)
        price += (anchor - price) * 0.25 + price * rng.gauss(0, 0.013)
        p = max(price, 1.0)
        if end_dip and i == len(dates) - 1:
            p *= 1 - end_dip
        count = max(1, int(rng.gauss(popularity, popularity * 0.35)))
        rows.append((d, round(p, 2), count))
    return rows


def write_log(path, rng, end, strata):
    lines = []
    for back in range(13, -1, -1):
        day = end - datetime.timedelta(days=back)
        ts = datetime.datetime.combine(day, datetime.time(19, 55, 3),
                                       tzinfo=datetime.timezone.utc).isoformat()
        roll = rng.random()
        done = strata if roll < 0.7 else int(strata * rng.uniform(0.55, 0.9))
        outcome = "full_lap - terminated cleanly" if done == strata else "time_budget - paused, resumable"
        lines += [f"\n==== Session: {ts} ====",
                  f"Strata processed:   {done}/{strata}",
                  f"Skins indexed:      {rng.randint(60, 120)}",
                  f"Elapsed:            {rng.randint(420, 590)}s",
                  f"Rate limit left:    {rng.randint(40, 160)}/200",
                  f"Resumes at index:   {0 if done == strata else done}",
                  f"Outcome: {outcome}", "===="]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--days", type=int, default=100)
    ap.add_argument("--per-weapon", type=int, default=22, help="skins per weapon (x3 wears)")
    ap.add_argument("--end", default=None, help="last snapshot date, YYYY-MM-DD (default: today)")
    ap.add_argument("--out", default=HERE)
    args = ap.parse_args()

    os.environ["CSFLOAT_DB"] = os.path.join(args.out, "demo.db")
    import db  # imported after CSFLOAT_DB is set
    from scanner import DipScanner

    rng = random.Random(args.seed)  # nosec B311 - seeded synthetic data, not security
    end = datetime.date.fromisoformat(args.end) if args.end else datetime.date.today()
    dates = [(end - datetime.timedelta(days=args.days - 1 - i)).isoformat() for i in range(args.days)]

    with open(os.path.join(ROOT, "skin_catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    items = build_items(rng, catalog, args.per_weapon)
    rng.shuffle(items)

    # Which items end on a dip, which are brand new, which dropped out of rotation.
    dip_items = items[:9]
    new_items = items[9:15]
    stale_items = items[15:20]

    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()

    records, history = [], {}
    for it in items:
        window = dates
        if it in new_items:
            window = dates[-rng.randint(6, 25):]
        if it in stale_items:
            window = dates[:-rng.randint(10, 30)]
        end_dip = rng.uniform(0.17, 0.27) if it in dip_items else (
            rng.uniform(0.04, 0.12) if rng.random() < 0.12 else 0)
        rows = [r for r in simulate(rng, it, window, end_dip) if rng.random() < 0.94 or r[0] == window[-1]]
        history[it["name"]] = rows
        records += [{"market_hash_name": it["name"], "date": d, "price": p, "listing_count": c}
                    for d, p, c in rows]
    db.save_snapshot(records)

    # Fake live listings, priced around the baseline, run through the real strategy.
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    cfg["csfloat_api_key"] = "demo-not-a-real-key"
    cfg["rate_state_file"] = os.path.join(args.out, ".rate_state_unused.json")
    scanner = DipScanner(cfg)
    listings = []
    for n, it in enumerate(dip_items + rng.sample(items[20:], 14)):
        base = statistics.median(p for _, p, _ in history[it["name"]][-8:-1])
        factor = rng.uniform(0.74, 0.86) if it in dip_items else rng.uniform(0.9, 1.05)
        wear = it["name"].rsplit("(", 1)[1].rstrip(")")
        listings.append({"id": f"demo-{n:04d}", "price": int(base * factor * 100),
                         "item": {"market_hash_name": it["name"], "wear_name": wear}})
    deals = scanner.analyze_dip_deals(listings)
    for d in deals:
        d["url"] = ""  # demo listings don't exist on csfloat.com
    db.save_deals(deals)

    write_log(os.path.join(args.out, "snapshot_job.log"), rng, end, strata=len(items))
    with open(os.path.join(args.out, "scan_position.json"), "w", encoding="utf-8") as f:
        json.dump({"index": 0, "total_strata": len(items),
                   "saved_at": datetime.datetime.combine(end, datetime.time(20, 5), tzinfo=datetime.timezone.utc).isoformat()}, f)

    print(f"Wrote {db.DB_PATH}: {len(records)} snapshots, {len(items)} skins, "
          f"{args.days} days to {end}, {len(deals)} flagged deals.")


if __name__ == "__main__":
    main()
