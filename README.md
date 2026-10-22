# CSFloat Dip Scanner (v0.4.1 prototype / demo)

Builds your own daily price history for CS2 skins on CSFloat, then flags
live listings priced well below a skin's recent baseline, on the bet that
the price reverts. Includes a dashboard, a calibration tool and a
**self-contained demo with synthetic data** so you can see the full flow
without an API key.

> **Branches.** `main` is the public demo/release: no real market data, keys
> or logs; everything in `demo/` is generated. `develop` carries the same code
> plus the real `deals.db`, logs and scan position, updated daily by the
> snapshot workflow. Live demo page: GitHub Pages for this repo (Settings >
> Pages > Source: GitHub Actions). See [SECURITY.md](SECURITY.md).

## Try the demo (no key, no network)

Fastest: open **`demo/demo.html`** in a browser. It is a single offline file
with the demo data baked in. You can browse the collection health, the
market index, skins below baseline, per-skin history and the flagged deals.

Or run it as the real app:

```bash
pip install -r requirements.txt
python run_demo.py            # http://127.0.0.1:5000, read-only
python run_demo.py --regenerate --export   # rebuild demo data and demo/demo.html
```

What you will see: ~130 skins × 100 days of synthetic prices, 9 skins that
end on a dip, and 8 flagged deals. The deals are produced by feeding fake
listings through the real `DipScanner.analyze_dip_deals()` (same baseline,
dip window, fee and profit-tier rules as production), not typed in by hand.
Scan / Clear are disabled in demo mode and the API key is never read.

## How it works

| Step | Script | What it does |
|---|---|---|
| 1 | `discover_def_indices.py` | Finds CSFloat's `def_index` for each weapon you want to track. |
| 2 | `discover_paint_indices.py` | Builds `skin_catalog.json`: every skin and its rarity. |
| 3 | `snapshot_job.py` | Run daily. Stores a median reference price per skin + wear in `deals.db`. Resumable, rate-limit aware. |
| 4 | `calibrate_config.py` | Replays your history and recommends dip thresholds, baseline window and profit tiers. |
| 5 | `scanner.py` | Pulls live buy-now listings; flags those far enough under baseline to clear fees and profit targets. |
| 6 | `app.py` | Dashboard on `deals.db`: collection health, market index, below-baseline skins, history, deals. |

A skin is scanned only after `min_snapshot_days_to_activate` days of history
(80 in the shipped config).

## Using it for real

```bash
pip install -r requirements.txt
cp .env.example .env          # put CSFLOAT_API_KEY in it (CSFloat profile > Developer tab)

python discover_def_indices.py "AK-47" "M4A4"   # copy ids into config.json
python discover_paint_indices.py                # builds skin_catalog.json
python snapshot_job.py                          # daily; --restart for a fresh pass
python calibrate_config.py [--write]            # after 40+ days of data
python scanner.py                               # one scan
python app.py                                   # dashboard + scan every 15 min
python export_dashboard.py                      # offline dashboard_export.html
```

Your data lives in `deals.db`, `scan_position.json`, `rate_state.json` and
`logs/`; all are git-ignored. **Do not commit them to a public repo.** Run the
snapshot job from cron/Task Scheduler, or let the bundled workflows do it:
`snapshot.yml` (daily) and `scan.yml` (manual) live on `main` because
scheduled workflows only run from the default branch, but they check out
`develop` and commit the data there. Add `CSFLOAT_API_KEY` as a repository
secret. Note that on a public repo that publishes `develop`'s data.

### Environment variables

| Variable | Purpose |
|---|---|
| `CSFLOAT_API_KEY` | Your key (real runs only). Never logged or served. |
| `CSFLOAT_DB` / `CSFLOAT_CONFIG` | Alternate database / config file (the demo uses these). |
| `DEMO_MODE=1` | Read-only, ignores the key. Set by `run_demo.py`. |
| `PUBLIC_MODE=1` | Read-only for visitors; no scan/clear. |
| `ALLOWED_HOSTS` | Comma list of Host headers to accept (default localhost). `*` disables. |

### Hosting publicly
Use `PUBLIC_MODE=1`, set `ALLOWED_HOSTS`, run behind a reverse proxy with
TLS and rate limiting, and use a production WSGI server (gunicorn/waitress)
instead of `app.py`'s dev server, which binds to `127.0.0.1` only.

## Configuration (`config.json`)

The shipped strategy values were calibrated on 85 days of AK-47 / M4A4 data
(Jul–Oct 2026), a period when prices fell about 22%. Re-calibrate on your own data.

| Key | Meaning |
|---|---|
| `weapon_def_indices` | Weapons to track, name → CSFloat `def_index`. |
| `allowed_wears` | Wears to snapshot and scan. |
| `min_price` / `max_price` | USD range of listings fetched. Keep fixed once collecting. |
| `min_snapshot_days_to_activate` | History a skin needs before it can be flagged. |
| `baseline_window_days` | Snapshots in the median baseline. |
| `min_sales_in_window` | Snapshot days required in the window. |
| `min_dip_percentage` / `max_dip_percentage` | Dip range flagged (deeper is usually a repricing). |
| `recent_days_for_current_price` | Newest days left out of the baseline. |
| `csfloat_fee_percentage` | Seller fee subtracted from estimated profit. |
| `dynamic_profit_targets` | Per price tier, a deal must clear `min_profit_usd` **or** `min_profit_percentage`. |
| `scanner_pages_per_stratum` | Pages of 50 listings per weapon per scan. |
| `scan_interval_seconds` | Pause between background scans in `app.py`. |
| `request_delay`, `rate_limit_stop_threshold`, `rate_limit_warn_threshold`, `max_batch_seconds` | Pacing and budget. |
| `scan_position_file`, `skin_catalog_file`, `rate_state_file`, `log_file` | Where state is kept. |

## Tests and checks

```bash
pip install pytest bandit pip-audit
python -m pytest -q tests
bandit -q -r . -x ./tests
pip-audit -r requirements.txt
```
CI (`.github/workflows/ci.yml`) runs the same, with read-only permissions and no secrets.

## Limitations

- **Reference prices, not sales.** Snapshots store CSFloat's `predicted_price`, not completed trades.
- **No forecasting.** Assumes reversion; in a falling market most dips keep falling.
- **Thin evidence at the extremes.** Deep dips are rare; the calibration report prints counts.
- **Shared rate limits** across the snapshot job, scanner and anything else on your key.
- **Buy orders aren't covered.** Only active buy-now listings are scanned.
- Not financial advice; the demo's numbers are fiction.

## Files

| Path | Purpose |
|---|---|
| `app.py` | Flask dashboard + API (`/api/dataset`, `/api/deals`, guarded `/api/scan-now`, `/api/clear`). |
| `run_demo.py` | Launches the demo. |
| `demo/` | `generate_demo_data.py`, `demo.db`, `config.demo.json`, `demo.html`, demo log/position. |
| `scanner.py`, `snapshot_job.py`, `calibrate_config.py`, `analytics.py` | Strategy, collection, tuning, summaries. |
| `clients/csfloat_client.py` | CSFloat API client with rate-limit tracking. |
| `db.py`, `config_loader.py`, `export_dashboard.py`, `terminal_colors.py`, `debug_scan.py` | Support. |
| `templates/index.html` | The dashboard page (self-contained). |
| `tests/` | pytest suite. |
| `SECURITY.md`, `changelogs.txt` | Security notes, version history. |
