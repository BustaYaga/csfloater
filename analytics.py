"""
Read-only views over the snapshot history that snapshot_job.py collects.

Everything here is derived from the `snapshots` table in deals.db plus the
job's own bookkeeping files (scan_position.json, logs/snapshot_job.log), so
it needs no API key and makes no network requests. app.py serves the result
as JSON and export_dashboard.py bakes it into a static HTML file.
"""
import datetime
import json
import math
import os
import re
import sqlite3
import statistics
from collections import defaultdict

import db

WEARS = ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]
STATTRAK_PREFIX = "StatTrak™ "

# An item whose newest snapshot is older than this (relative to the newest
# snapshot in the whole dataset) has dropped out of the rotation.
STALE_AFTER_DAYS = 7


def _parse_name(market_hash_name):
    name = market_hash_name
    stattrak = name.startswith(STATTRAK_PREFIX)
    if stattrak:
        name = name[len(STATTRAK_PREFIX):]
    wear = ""
    m = re.match(r"^(.*) \(([^()]+)\)$", name)
    if m and m.group(2) in WEARS:
        name, wear = m.group(1), m.group(2)
    weapon, _, skin = name.partition(" | ")
    return {"base_name": name, "weapon": weapon, "skin": skin or name,
            "wear": wear, "stattrak": stattrak}


def _rarity_lookup(catalog_path):
    """{'AK-47 | Redline': 'Classified', ...} from skin_catalog.json."""
    if not os.path.exists(catalog_path):
        return {}
    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)
    lookup = {}
    for skins in catalog.values():
        for entry in skins.values():
            if isinstance(entry, dict) and entry.get("name"):
                lookup[entry["name"]] = entry.get("rarity", "")
    return lookup


def _days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def _pct(new, old):
    if not old:
        return None
    return (new - old) / old * 100


def _price_on_or_before(history, target_date):
    """Price from the newest snapshot dated <= target_date, else None."""
    for date, price, _ in reversed(history):
        if date <= target_date:
            return price
    return None


def _summarize_item(name, history, rarity_lookup, dataset_end, baseline_window):
    meta = _parse_name(name)
    prices = [p for _, p, _ in history]
    counts = [c for _, _, c in history]
    first_date, last_date = history[0][0], history[-1][0]
    latest = prices[-1]

    # Same idea as scanner.py: the baseline is the median of the window, but
    # here the newest point is left out so "today" is compared against the
    # days before it rather than against itself.
    prior = prices[:-1][-baseline_window:]
    baseline = statistics.median(prior) if prior else None

    def change_since(days):
        target = (datetime.date.fromisoformat(last_date)
                  - datetime.timedelta(days=days)).isoformat()
        if target < first_date:
            return None
        then = _price_on_or_before(history, target)
        return _pct(latest, then) if then else None

    window = prices[-baseline_window:]
    if len(window) >= 3 and statistics.mean(window) > 0:
        volatility = statistics.pstdev(window) / statistics.mean(window) * 100
    else:
        volatility = None

    return {
        "name": name,
        **meta,
        "rarity": rarity_lookup.get(meta["base_name"], ""),
        "days": len(history),
        "first_date": first_date,
        "last_date": last_date,
        "stale": _days_between(last_date, dataset_end) > STALE_AFTER_DAYS,
        "latest_price": latest,
        "baseline_price": baseline,
        "vs_baseline_pct": _pct(latest, baseline) if baseline else None,
        "change_7d_pct": change_since(7),
        "change_30d_pct": change_since(30),
        "low": min(prices),
        "high": max(prices),
        "volatility_pct": volatility,
        "avg_listings": statistics.mean(counts) if counts else 0,
        # Compact [date, price, listing_count] triples, oldest first.
        "history": [[d, round(p, 4), c] for d, p, c in history],
    }


def _basket_index(items_hist, dates):
    """
    Equal-weighted price index (start = 100) over the items that were
    snapshotted on at least 90% of all collection days, so a change in which
    skins happened to be scanned on a given day doesn't move the line.
    Sub-$1 items are left out: a one-cent tick on a $0.02 skin is a 50% move
    and would swamp everything else. Uses the geometric mean of each item's
    price relative to its own first snapshot.
    """
    if not dates:
        return {"members": 0, "points": []}
    need = math.ceil(len(dates) * 0.9)
    members = {n: dict((d, p) for d, p, _ in h)
               for n, h in items_hist.items()
               if len(h) >= need and statistics.median(p for _, p, _ in h) >= 1.0}
    if not members:
        return {"members": 0, "points": []}
    starts = {n: next(iter(series.values())) for n, series in members.items()}
    points = []
    for d in dates:
        logs = [math.log(series[d] / starts[n])
                for n, series in members.items()
                if d in series and series[d] > 0 and starts[n] > 0]
        if len(logs) >= max(3, len(members) // 2):
            points.append([d, round(100 * math.exp(statistics.mean(logs)), 3), len(logs)])
    return {"members": len(members), "points": points}


def _read_runs(log_path, limit=12):
    """Newest-first list of session summaries from logs/snapshot_job.log."""
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as f:
        text = f.read()
    runs = []
    for ts, body in re.findall(r"==== Session: (\S+) ====\n(.*?)\n====", text, re.S):
        fields = {}
        for line in body.splitlines():
            key, sep, value = line.partition(":")
            if sep:
                fields[key.strip().lower()] = value.strip()
        outcome = fields.get("outcome", "")
        if not outcome and body.startswith("TERMINATED"):
            outcome = "rate_limit - terminated before start"
        strata = fields.get("strata processed", "")
        runs.append({
            "started_at": ts,
            "outcome": outcome.split(" ")[0] if outcome else "unknown",
            "outcome_text": outcome,
            "strata_processed": strata,
            "skins_indexed": fields.get("skins indexed", ""),
            "elapsed": fields.get("elapsed", ""),
            "rate_limit_left": fields.get("rate limit left", ""),
        })
    return list(reversed(runs))[:limit]


def build_dataset(config, db_path=None):
    """Everything the dashboard needs, in one JSON-serialisable dict."""
    db_path = db_path or db.DB_PATH
    baseline_window = config.get("baseline_window_days", 14)
    activate_days = config.get("min_snapshot_days_to_activate", 14)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT market_hash_name, snapshot_date, price, listing_count
        FROM snapshots
        ORDER BY market_hash_name, snapshot_date
    """).fetchall()
    deals_count = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='deals'").fetchone() else 0
    conn.close()

    items_hist = defaultdict(list)
    per_day = defaultdict(lambda: [0, 0])
    for name, date, price, count in rows:
        items_hist[name].append((date, price, count or 0))
        per_day[date][0] += 1
        per_day[date][1] += count or 0

    dates = sorted(per_day)
    dataset_end = dates[-1] if dates else datetime.date.today().isoformat()
    rarity_lookup = _rarity_lookup(config.get("skin_catalog_file", "skin_catalog.json"))

    items = [_summarize_item(n, h, rarity_lookup, dataset_end, baseline_window)
             for n, h in items_hist.items()]
    items.sort(key=lambda i: i["name"])

    position = None
    pos_path = config.get("scan_position_file", "scan_position.json")
    if os.path.exists(pos_path):
        try:
            with open(pos_path, encoding="utf-8") as f:
                position = json.load(f)
        except (OSError, json.JSONDecodeError):
            position = None

    active = [i for i in items if not i["stale"]]
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "settings": {
            "baseline_window_days": baseline_window,
            "min_snapshot_days_to_activate": activate_days,
            "stale_after_days": STALE_AFTER_DAYS,
            "scan_interval_seconds": config.get("scan_interval_seconds", 900),
            "min_price": config.get("min_price"),
            "max_price": config.get("max_price"),
            "weapons": sorted(config.get("weapon_def_indices", {}).keys()),
            "wears": config.get("allowed_wears", []),
        },
        "overview": {
            "snapshot_rows": len(rows),
            "listings_sampled": sum(c for _, _, c in
                                    (r for h in items_hist.values() for r in h)),
            "items": len(items),
            "items_in_rotation": len(active),
            "items_ready": sum(1 for i in active if i["days"] >= activate_days),
            "collection_days": len(dates),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
            "calendar_span_days": _days_between(dates[0], dates[-1]) + 1 if dates else 0,
            "deals_recorded": deals_count,
            "scan_position": position,
        },
        "coverage": [{"date": d, "items": per_day[d][0], "listings": per_day[d][1]}
                     for d in dates],
        "basket_index": _basket_index(items_hist, dates),
        "runs": _read_runs(config.get("log_file", os.path.join("logs", "snapshot_job.log"))),
        "items": items,
    }
