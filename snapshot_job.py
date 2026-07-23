"""
Run this on a schedule (cron / Windows Task Scheduler / GitHub Actions) to
build your own first-party CSFloat price history, one skin+wear stratum at
a time.

Rate-limit safety:
  - Fixed delay between every request (config: request_delay, default 3s).
  - Checks CSFloat's real X-Ratelimit-Remaining/Reset headers, persisted to
    rate_state.json so even a BRAND NEW process checks status before
    sending a single request.
  - remaining <= stop_threshold (default 10)   -> refuses to run at all.
  - remaining <= warn_threshold (default 50)    -> runs, but prints a
    warning first.

Logging: every session appends a summary block to logs/snapshot_job.log
(created automatically). Nothing is overwritten - it's a running history.

Prerequisite: run discover_paint_indices.py first to generate skin_catalog.json.
"""
import argparse
import datetime
import json
import os
import statistics
import time
from collections import defaultdict

from clients.csfloat_client import CSFloatClient
from config_loader import load_config
from terminal_colors import cprint, format_strata_line, enable_windows_ansi, print_banner, divider
import db

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "snapshot_job.log")


def parse_args():
    parser = argparse.ArgumentParser(
        prog="snapshot_job.py",
        description=(
            "Pulls CSFloat listings for each configured skin+wear stratum and "
            "stores median predicted prices for later dip analysis. Normally "
            "resumes from wherever the previous run left off (see "
            "scan_position.json)."
        ),
        epilog="Example: python snapshot_job.py --restart",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help=(
            "Ignore the saved position in scan_position.json and start over "
            "from the very first stratum (index 0) instead of resuming where "
            "the last run left off. Use this if you've changed included "
            "weapons/skins and want a clean full pass, or just want to force "
            "a fresh sweep from the top."
        ),
    )
    return parser.parse_args()


def format_mmss(seconds):
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    return f"{seconds // 60}m {seconds % 60}s"


def build_strata(cfg, catalog):
    """
    Flat, deterministically-ordered list of (weapon_name, def_index,
    paint_index, skin_base_name, rarity_name, wear) tuples.
    Catalog entries are now {"name": ..., "rarity": ...} dicts - see
    discover_paint_indices.py.
    """
    strata = []
    for weapon_name in sorted(cfg["weapon_def_indices"].keys()):
        def_index = cfg["weapon_def_indices"][weapon_name]
        skins = catalog.get(weapon_name, {})
        for paint_index in sorted(skins.keys(), key=lambda k: int(k)):
            entry = skins[paint_index]
            skin_base_name = entry["name"] if isinstance(entry, dict) else entry
            rarity_name = entry.get("rarity", "") if isinstance(entry, dict) else ""
            for wear in cfg["allowed_wears"]:
                strata.append((weapon_name, def_index, int(paint_index),
                               skin_base_name, rarity_name, wear))
    return strata


def load_position(path, total_strata):
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        saved_total = data.get("total_strata")
        pos = data.get("index", 0)
        if saved_total is not None and saved_total != total_strata:
            cprint(
                f"Catalog size changed since last run ({saved_total} -> {total_strata} strata) - "
                f"resetting position to 0 to avoid landing on an unrelated stratum.",
                "WARNING",
            )
            return 0
        return pos if 0 <= pos < total_strata else 0
    except (json.JSONDecodeError, OSError):
        return 0


def save_position(path, index, total_strata):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "index": index,
            "total_strata": total_strata,
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }, f)


def log_session(summary_lines):
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n==== Session: {timestamp} ====\n")
        for line in summary_lines:
            f.write(line + "\n")
        f.write("====\n")


def take_snapshot(args=None):
    if args is None:
        args = parse_args()

    enable_windows_ansi()
    cfg = load_config()
    client = CSFloatClient(
        cfg["csfloat_api_key"],
        request_delay=cfg.get("request_delay", 3.0),
        rate_state_file=cfg.get("rate_state_file", "rate_state.json"),
    )

    stop_threshold = cfg.get("rate_limit_stop_threshold", 10)
    warn_threshold = cfg.get("rate_limit_warn_threshold", 50)

    # --- Rate-limit gate: checked BEFORE any request is sent, using
    # persisted state from the last run (if any). Status is always shown,
    # not just on warning/stop, so you always know where you stand. ---
    status, seconds_left = client.check_rate_limit_status(stop_threshold, warn_threshold)

    if client.rate_remaining is not None and client.rate_limit is not None:
        rate_line = f"Requests remaining: {client.rate_remaining}/{client.rate_limit} (resets in {format_mmss(seconds_left)})"
    else:
        rate_line = "Requests remaining: unknown (no prior rate data - first request will reveal it)"
    cprint(rate_line, "INFO")

    if status == "stop":
        msg = (f"Terminating process: rate limit threshold reached "
               f"({client.rate_remaining}/{client.rate_limit} left, "
               f"resets in {format_mmss(seconds_left)})")
        cprint(msg, "TERMINATED")
        log_session([f"TERMINATED before start - {msg}"])
        return

    if status == "warning":
        msg = (f"Warning: rate limit is {client.rate_remaining} or lower. "
               f"You may get rate limited if using the web UI. "
               f"Rate limit reset timer: {format_mmss(seconds_left)}")
        cprint(msg, "WARNING")

    # --- Load skin catalog ---
    catalog_path = cfg.get("skin_catalog_file", "skin_catalog.json")
    if not os.path.exists(catalog_path):
        raise RuntimeError(
            f"{catalog_path} not found - run discover_paint_indices.py first "
            f"to build the skin catalog."
        )
    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    strata = build_strata(cfg, catalog)
    total_strata = len(strata)
    if total_strata == 0:
        cprint("No strata to scan - is skin_catalog.json empty?", "WARNING")
        return

    position_path = cfg.get("scan_position_file", "scan_position.json")
    if args.restart:
        cprint("--restart flag set: starting from stratum 0 instead of resuming.", "WARNING")
        start_index = 0
    else:
        start_index = load_position(position_path, total_strata)
    max_seconds = cfg.get("max_batch_seconds", 600)

    by_item = defaultdict(list)
    start_time = time.time()
    processed = 0
    index = start_index
    completion_reason = None  # "full_lap" | "time_budget" | "rate_limit"
    completion_detail = None

    print_banner("CSFloat Snapshot Job", [
        f"Total strata:  {total_strata}",
        f"Starting at:   index {start_index}",
        f"Time budget:   {max_seconds}s",
    ], color="#00BFFF")
    divider()

    while True:
        elapsed = time.time() - start_time
        if elapsed >= max_seconds:
            completion_reason = "time_budget"
            break
        if processed >= total_strata:
            completion_reason = "full_lap"
            break

        weapon_name, def_index, paint_index, skin_base_name, rarity_name, wear = strata[index]

        # Real-time per-stratum line, printed as soon as it starts. Shows the
        # ABSOLUTE position in the full strata list (continues correctly
        # across runs) rather than a session-local counter that would reset
        # to 1 every time. Only the skin name itself is coloured by rarity.
        print(format_strata_line(index, total_strata, skin_base_name, wear, rarity_name))

        listings = client.fetch_listings(
            def_index=def_index,
            paint_index=paint_index,
            min_price_cents=int(cfg["min_price"] * 100),
            max_price_cents=int(cfg["max_price"] * 100),
            max_pages=1,
            sort_by="lowest_price",
            type_="buy_now",
        )

        for listing in listings:
            info = listing.get("item", {})
            name = info.get("market_hash_name", "")
            if not name or info.get("is_souvenir"):
                continue
            if info.get("wear_name") != wear:
                continue
            reference = listing.get("reference") or {}
            predicted_raw = reference.get("predicted_price")
            predicted = (
                predicted_raw / 100.0
                if isinstance(predicted_raw, (int, float)) and predicted_raw > 0
                else None
            )
            if predicted:
                by_item[name].append(predicted)

        processed += 1
        index = (index + 1) % total_strata

        # Mid-run rate-limit check - stop cleanly rather than let the client
        # eventually hit a hard 429 wall.
        status, seconds_left = client.check_rate_limit_status(stop_threshold, warn_threshold)
        if status == "stop":
            completion_detail = (
                f"rate limit threshold reached mid-run "
                f"({client.rate_remaining}/{client.rate_limit} left, "
                f"resets in {format_mmss(seconds_left)})"
            )
            cprint(f"Terminating process: {completion_detail}", "TERMINATED")
            completion_reason = "rate_limit"
            break

        # Periodic live countdown so the reset timer is visibly ticking down
        # during a run, not just shown once at startup.
        if processed % 10 == 0:
            cprint(f"Live check - {client.rate_remaining}/{client.rate_limit} requests left, "
                   f"reset in {format_mmss(seconds_left)}", "INFO")

    save_position(position_path, index, total_strata)

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
    elapsed = time.time() - start_time

    summary_lines = [
        f"Strata processed:   {processed}/{total_strata}",
        f"Skins indexed:      {len(records)}",
        f"Elapsed:            {elapsed:.0f}s",
        f"Rate limit left:    {client.rate_remaining}/{client.rate_limit}",
        f"Resumes at index:   {index}",
    ]

    if completion_reason == "full_lap":
        summary_lines.append("Result: FULL CATALOG SCAN COMPLETE - every stratum processed this session.")
        print_banner("Snapshot Job Finished Successfully", summary_lines, color="#32CD32")
        log_session(summary_lines + ["Outcome: full_lap - terminated cleanly"])
        return  # done - full catalog covered, nothing more to do this run

    if completion_reason == "rate_limit":
        summary_lines.append(f"Stopped early: {completion_detail}")
        print_banner("Session Ended Early (Rate Limit)", summary_lines, color="#FF3B30")
        log_session(summary_lines + ["Outcome: rate_limit - terminated early"])
        return

    # completion_reason == "time_budget" - normal, expected pause; not an
    # error, just resumable progress. Neutral colour, not red/green.
    summary_lines.append("Result: time budget reached - will resume next run.")
    print_banner("Session Paused (Time Budget Reached)", summary_lines, color="#00BFFF")
    log_session(summary_lines + ["Outcome: time_budget - paused, resumable"])


if __name__ == "__main__":
    take_snapshot(parse_args())