# CSFloat Dip Scanner

Builds your own daily price history for CS2 skins on CSFloat, then flags
live listings priced well below a skin's recent baseline, on the bet that
the price reverts. Comes with a local dashboard for exploring the data and
a calibration tool that tunes the strategy from your own history.

Everything runs on your machine (or in GitHub Actions) against the official
CSFloat API with your own key. Nothing is hosted.

## How it works

| Step | Script | What it does |
|---|---|---|
| 1 | `discover_def_indices.py` | Finds CSFloat's `def_index` for each weapon you want to track. |
| 2 | `discover_paint_indices.py` | Builds `skin_catalog.json`: every skin (and its rarity) for those weapons. |
| 3 | `snapshot_job.py` | Run daily. Records a median reference price per skin + wear into `deals.db`. Resumes where it stopped and respects the rate limit. |
| 4 | `calibrate_config.py` | Replays your history and recommends dip thresholds, baseline window and profit tiers. |
| 5 | `scanner.py` | Pulls live buy-now listings and flags ones far enough below baseline to clear the fee and your profit targets. |
| 6 | `app.py` | Local dashboard: collection health, market index, skins below baseline, per-skin price history, flagged deals. |

A skin is only considered by the scanner after it has
`min_snapshot_days_to_activate` days of history (80 in the shipped config),
so expect to run the snapshot job for a while before seeing any deals.

## Setup

Python 3.10+.

```bash
pip install -r requirements.txt
cp .env.example .env        # then put your key in .env
```

`CSFLOAT_API_KEY` comes from your CSFloat profile, Developer tab. Never
commit `.env`; it is already in `.gitignore`.

### Choose what to track

1. List the weapons you want and find their IDs:
   ```bash
   python discover_def_indices.py "AK-47" "M4A4" "AWP"
   ```
   Copy the numbers into `weapon_def_indices` in `config.json`.
2. Build the skin catalog:
   ```bash
   python discover_paint_indices.py
   ```
   Re-run it now and then to pick up newly released skins.

### Collect history every day

```bash
python snapshot_job.py              # resumes from scan_position.json
python snapshot_job.py --restart    # start a fresh pass from the first skin
```

Schedule it once a day (cron, Windows Task Scheduler, or GitHub Actions).
`.github/workflows/snapshot.yml` is a ready-made Actions schedule: add
`CSFLOAT_API_KEY` as a repository secret and it runs, then commits
`deals.db`, `scan_position.json` and the log back to the repo. Each run
stops on its own when the rate limit gets close, and the next run carries on
from the same place.

### Tune the strategy to your data

Once you have 40+ days of history:

```bash
python calibrate_config.py           # report only
python calibrate_config.py --write   # apply to config.json
```

It assumes a 7-day hold (the CS2 trade lock), tests baseline windows of
7–28 days, and finds which dip sizes actually recovered by more than the
fee. Re-run it every few weeks; the right values move with the market.

### Scan and view

```bash
python scanner.py   # one scan, prints and saves flagged deals
python app.py       # dashboard at http://127.0.0.1:5000, scans every 15 min
```

The dashboard only reads `deals.db`, so it also works without an API key
(scanning is just switched off). `PUBLIC_MODE=1 python app.py` hides the
Scan now / Clear buttons and blocks those endpoints.

`python export_dashboard.py` writes `dashboard_export.html`, a single
offline file with the current data baked in.

`.github/workflows/scan.yml` runs one scan in GitHub Actions on demand
(Actions tab → Dip Scan → Run workflow).

### Use the data in your own analytics

All history lives in SQLite, so any tool can read it:

```sql
-- deals.db
SELECT market_hash_name, snapshot_date, price, listing_count FROM snapshots;
SELECT * FROM deals ORDER BY found_at DESC;
```

From Python, `analytics.build_dataset(config)` returns the same per-skin
summaries, coverage and index the dashboard uses, as plain dicts.

## Configuration (`config.json`)

The shipped values were calibrated on 85 days of AK-47 / M4A4 data
(Jul–Oct 2026), a period when tracked prices fell about 22%. Calibrate on
your own data before relying on them.

| Key | Shipped | Meaning |
|---|---|---|
| `weapon_def_indices` | AK-47, M4A4 | Weapons to track, name → CSFloat `def_index`. |
| `allowed_wears` | FN, MW, FT | Wears to snapshot and scan. |
| `min_price` / `max_price` | 5 / 100 | USD price range of listings fetched. Keep it fixed once collecting, or old and new history won't be comparable. |
| `min_snapshot_days_to_activate` | 80 | Days of history a skin needs before it can be flagged. |
| `baseline_window_days` | 7 | Snapshots in the median baseline. In calibration a 7-day baseline was the only window whose 10%+ dips beat the fee. |
| `min_sales_in_window` | 5 | Snapshot days required inside the window, so gaps don't skew the baseline. |
| `min_dip_percentage` | 15 | Smallest dip flagged. Dips under 10% kept falling (−1% to −1.6% a week later). |
| `max_dip_percentage` | 30 | Deepest dip flagged. Deeper drops are more often repricings than bargains; none were observed in this data. |
| `recent_days_for_current_price` | 0 | Newest snapshot days left out of the baseline. |
| `csfloat_fee_percentage` | 2.0 | CSFloat seller fee, subtracted from estimated profit. |
| `dynamic_profit_targets` | 3 tiers | Per price tier, a deal must clear `min_profit_usd` **or** `min_profit_percentage`. Tiers split at the terciles of tracked prices; targets sit above each tier's typical weekly move (7% under $14, about 4% above). |
| `scanner_pages_per_stratum` | 2 | Pages of 50 listings fetched per weapon per scan. |
| `scan_interval_seconds` | 900 | Pause between scans when `app.py` runs the scanner in the background. |
| `request_delay` | 3.0 | Seconds between API requests. |
| `rate_limit_stop_threshold` | 10 | Stop when this many requests are left. |
| `rate_limit_warn_threshold` | 50 | Warn when this many requests are left. |
| `max_batch_seconds` | 600 | Time budget per snapshot run. |
| `scan_position_file`, `skin_catalog_file`, `rate_state_file` | | Where the jobs keep their state. |

## Limitations

- **Reference prices, not sales.** Snapshots store CSFloat's
  `predicted_price` for the cheapest listings in each stratum, not completed
  trades. The scanner compares a real asking price against that baseline.
- **No forecasting.** The strategy assumes prices revert. Calibration tells
  you how often that held in your history; it can't tell you about next
  week. In a falling market most dips keep falling.
- **Thin evidence at the extremes.** Deep dips are rare, so the upper
  thresholds rest on few events. The calibration report prints the counts.
- **Rate limits are shared.** The snapshot job, the scanner and anything else
  using your key draw from the same CSFloat allowance.
- **Buy orders aren't covered.** Only active buy-now listings are scanned.

## Files

| Path | Purpose |
|---|---|
| `clients/csfloat_client.py` | CSFloat API client with rate-limit tracking. |
| `db.py` | SQLite schema and helpers (`deals.db`). |
| `analytics.py` | Read-only summaries of the snapshot history. |
| `config_loader.py` | Merges `.env` secrets into `config.json`. |
| `terminal_colors.py` | Console colours (rarity-coloured skin names). |
| `debug_scan.py` | Shows what the scanner sees with no filters applied. |
| `templates/index.html` | The dashboard page. |
| `changelogs.txt` | Version history. |
