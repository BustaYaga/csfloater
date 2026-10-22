"""
Tune the strategy settings in config.json from your own snapshot history.

It replays every skin's history in deals.db: on each day it computes the
baseline the scanner would have used, measures how far the price sat below
it, and checks what the price did over the following holding period. From
that it recommends:

  baseline_window_days    the window whose dips recovered best
  min_dip_percentage      smallest dip that, on average, recovered by more
                          than the CSFloat fee
  max_dip_percentage      deepest dip that still recovered on average
                          (deeper "dips" are usually repricings, not bargains)
  min_sales_in_window     snapshot days required inside the window
  dynamic_profit_targets  price tiers split at the terciles of tracked
                          prices, each with a profit floor set above that
                          tier's normal week-to-week price noise

Run:
    python calibrate_config.py            # print the report only
    python calibrate_config.py --write    # also update config.json

Caveats: prices are CSFloat reference prices (what snapshot_job.py stores),
not completed sales, and the result reflects the market you collected in.
Re-run it every few weeks as history grows.
"""
import argparse
import json
import sqlite3
import statistics
from collections import defaultdict

import db

CANDIDATE_WINDOWS = [7, 10, 14, 21, 28]
# CS2 items bought on the market are trade-locked for 7 days, so a week is
# the shortest realistic hold before you can relist.
HOLD_DAYS = 7
DIP_EDGES = [1, 3, 5, 7, 10, 15, 20, 30, 50]   # dip buckets, % below baseline
MIN_SAMPLES = 10        # events a bucket needs before it can set min_dip
MIN_PRICE_FOR_STATS = 1.0  # sub-$1 skins move in whole-cent ticks; ignore them


def load_histories(db_path, min_days):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT market_hash_name, price FROM snapshots ORDER BY market_hash_name, snapshot_date"
    ).fetchall()
    conn.close()
    hist = defaultdict(list)
    for name, price in rows:
        if price and price > 0:
            hist[name].append(price)
    return {n: p for n, p in hist.items()
            if len(p) >= min_days and statistics.median(p) >= MIN_PRICE_FOR_STATS}


def dip_events(histories, window, hold):
    """(dip_pct, forward_return_pct, price) for every day with a full window and hold."""
    events = []
    for prices in histories.values():
        for t in range(window, len(prices) - hold):
            base = statistics.median(prices[t - window:t])
            dip = (base - prices[t]) / base * 100
            fwd = (prices[t + hold] - prices[t]) / prices[t] * 100
            events.append((dip, fwd, prices[t]))
    return events


def bucketize(events):
    out = []
    for lo, hi in zip(DIP_EDGES, DIP_EDGES[1:]):
        sel = [fwd for dip, fwd, _ in events if lo <= dip < hi]
        out.append({"lo": lo, "hi": hi, "n": len(sel),
                    "mean_fwd": statistics.mean(sel) if sel else None})
    return out


def score_window(events, fee):
    """Mean net return on dips of 10%+ - how well this window's dips paid off."""
    sel = [fwd - fee for dip, fwd, _ in events if dip >= 10]
    return (statistics.mean(sel) if len(sel) >= MIN_SAMPLES else float("-inf")), len(sel)


def pick_dip_range(buckets, fee):
    min_dip = max_dip = None
    for b in buckets:
        paid = b["mean_fwd"] is not None and b["mean_fwd"] > fee
        if min_dip is None:
            if paid and b["n"] >= MIN_SAMPLES:
                min_dip, max_dip = b["lo"], b["hi"]
        elif paid and b["n"] >= 3:
            max_dip = b["hi"]
        else:
            break
    return min_dip, max_dip


def weekly_noise(prices, hold):
    """75th percentile of absolute price change over `hold` days."""
    moves = sorted(abs(prices[i + hold] - prices[i]) / prices[i] * 100
                   for i in range(len(prices) - hold))
    return moves[int(0.75 * (len(moves) - 1))] if moves else None


def profit_tiers(histories, cfg, hold):
    lo_price, hi_price = cfg["min_price"], cfg["max_price"]
    in_range = {n: p for n, p in histories.items() if lo_price <= statistics.median(p) <= hi_price}
    medians = sorted(statistics.median(p) for p in in_range.values())
    if len(medians) < 6:
        return None, []
    cuts = [medians[len(medians) // 3], medians[2 * len(medians) // 3]]
    # Round tier edges to friendly numbers.
    cuts = [round(c) if c < 20 else round(c / 5) * 5 for c in cuts]
    edges = [lo_price] + cuts + [hi_price]
    tiers, report = [], []
    for a, b in zip(edges, edges[1:]):
        noise = [weekly_noise(p, hold) for p in in_range.values() if a < statistics.median(p) <= b]
        noise = [x for x in noise if x is not None]
        if not noise:
            continue
        pct = max(cfg.get("csfloat_fee_percentage", 2.0) * 2, statistics.median(noise))
        pct = round(pct)
        usd = round(a * pct / 100 * 2) / 2 or 0.5   # pct of the tier's floor, to $0.50
        tiers.append({"max_skin_price": float(b), "min_profit_usd": usd,
                      "min_profit_percentage": float(pct)})
        report.append((a, b, len(noise), statistics.median(noise), usd, pct))
    return tiers, report


def main():
    ap = argparse.ArgumentParser(description="Tune config.json from your snapshot history.")
    ap.add_argument("--write", action="store_true", help="write the recommended values into config.json")
    ap.add_argument("--config", default="config.json")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    fee = cfg.get("csfloat_fee_percentage", 2.0)

    min_days = max(CANDIDATE_WINDOWS) + HOLD_DAYS + 5
    histories = load_histories(db.DB_PATH, min_days)
    print(f"Skins with {min_days}+ days of history priced ${MIN_PRICE_FOR_STATS:.0f}+: {len(histories)}")
    if len(histories) < 10:
        print("Not enough history to calibrate yet - keep snapshot_job.py running and try again later.")
        return

    print(f"\nHolding period: {HOLD_DAYS} days (CS2 trade lock). Fee: {fee}%.\n")
    print("Window | dips >=10% | mean net return after fee")
    best = None
    for w in CANDIDATE_WINDOWS:
        score, n = score_window(dip_events(histories, w, HOLD_DAYS), fee)
        shown = f"{score:+.2f}%" if score != float("-inf") else "too few events"
        print(f"  {w:>3}d | {n:>9} | {shown}")
        if best is None or score > best[1]:
            best = (w, score)
    window = best[0]

    buckets = bucketize(dip_events(histories, window, HOLD_DAYS))
    print(f"\nWith a {window}-day baseline, return {HOLD_DAYS} days after buying a dip:")
    for b in buckets:
        mf = f"{b['mean_fwd']:+.1f}%" if b["mean_fwd"] is not None else "-"
        print(f"  {b['lo']:>2}-{b['hi']:<2}% below baseline | n={b['n']:<5} | {mf}")
    min_dip, max_dip = pick_dip_range(buckets, fee)
    if min_dip is None:
        print("\nNo dip size recovered by more than the fee on average. Keeping the current dip range.")
        min_dip, max_dip = cfg["min_dip_percentage"], cfg["max_dip_percentage"]

    tiers, tier_report = profit_tiers(histories, cfg, HOLD_DAYS)
    if tier_report:
        print(f"\nProfit tiers (tier floor x target, rounded; target >= max(2x fee, median {HOLD_DAYS}-day noise)):")
        for a, b, n, noise, usd, pct in tier_report:
            print(f"  ${a:>5.0f}-${b:<5.0f} | {n:>3} skins | typical {HOLD_DAYS}-day move {noise:4.1f}% | "
                  f"min ${usd:.2f} or {pct}%")

    recommended = {
        "baseline_window_days": window,
        "min_sales_in_window": max(3, round(window * 0.7)),
        "min_dip_percentage": float(min_dip),
        "max_dip_percentage": float(max_dip),
    }
    if tiers:
        recommended["dynamic_profit_targets"] = tiers

    print("\nRecommended settings:")
    for k, v in recommended.items():
        old = cfg.get(k)
        mark = "" if old == v else f"   (was {json.dumps(old)})"
        print(f"  {k}: {json.dumps(v)}{mark}")

    if args.write:
        cfg.update(recommended)
        with open(args.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"\nWrote {args.config}.")
    else:
        print("\nRun with --write to apply these to config.json.")


if __name__ == "__main__":
    main()
