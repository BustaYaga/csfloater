# CSFloat Dip Scanner v0.4: prototype and demo release

A prototype that builds its own daily price history for CS2 skins on CSFloat. It flags live buy-now listings priced far below their recent baseline, on the bet that the price reverts. This release includes a dashboard and a built-in demo with synthetic data. You can try it with no API key and no network.

**Live demo page:** https://bustayaga.github.io/csfloater/ (appears once GitHub Pages is switched on)

## Use case

Buy-now listings sometimes appear well under the usual price for a skin and wear. This tool:

1. **Collects history.** A daily job stores one median reference price per skin and wear, so you own your price history instead of paying for a data source.
2. **Sets a baseline.** It takes the median of the last N snapshots for each skin.
3. **Flags dips.** It scans live listings and flags those inside your dip range (15–30% in the shipped config). The estimated profit after CSFloat's fee must also clear your per-price-tier targets.
4. **Tunes itself.** A calibration tool replays your history and recommends dip thresholds, baseline window and profit tiers.
5. **Shows the data.** The dashboard covers collection health, a market index, skins below baseline, per-skin history and the flagged deals.

## What's in v0.4

- **Dashboard** (`app.py`): works without an API key, and the page makes no third-party requests.
- **Calibration** (`calibrate_config.py`): assumes a 7-day hold, tests baseline windows of 7–28 days and reports which dip sizes recovered by more than the fee.
- **Scanner rules:** 80-day history required before a skin can be flagged, rate-limit gate, per-tier profit targets.
- **Demo mode:**
  - `demo/demo.html` is an offline copy; just open it in a browser.
  - `python run_demo.py` runs the full app read-only on bundled synthetic data (about 130 skins over 100 days, 8 flagged deals). The deals come from the real scanner logic.
  - Scan and Clear are disabled in demo mode, and the API key is never read.
- **Security hardening:**
  - Patched dependencies: Flask 3.1.3, requests 2.34.2, python-dotenv 1.2.3. The old pins had 8 known CVEs.
  - CSRF header on POSTs, Host-header allowlist, and CSP and other security headers.
  - Escaped output, strict link validation and listing-ID validation.
  - Loopback-only bind.
  - See [SECURITY.md](SECURITY.md).
- **Tests and CI:** 8 pytest tests, plus bandit and pip-audit in CI with read-only permissions.
- **Workflows:**
  - Daily snapshot and manual scan run from `main` but commit data to `develop`.
  - A Pages workflow publishes the demo.

## Requirements

| For | You need |
|---|---|
| Demo | Python 3.10+ and `pip install -r requirements.txt` |
| Real use | The above, plus a CSFloat API key (profile → Developer tab) in `.env` as `CSFLOAT_API_KEY` |
| Automated snapshots | `CSFLOAT_API_KEY` as a GitHub repository secret |
| Pages demo | Settings → Pages → Source: GitHub Actions |
| Checks (optional) | `pytest`, `bandit`, `pip-audit` |

## Quick start

```bash
pip install -r requirements.txt
python run_demo.py          # http://127.0.0.1:5000
```

For real use, copy `.env.example` to `.env` and add your key. Then run `discover_def_indices.py`, `discover_paint_indices.py`, and `snapshot_job.py` daily. Run `calibrate_config.py` after 40+ days of data, and `scanner.py` or `app.py` to scan.

## Branches

- **`main`** is this release: code, demo and docs, with no real data, keys or logs.
- **`develop`** has the same code plus the real `deals.db`, logs and scan position, updated daily by the snapshot workflow.

## Known limitations

- **Reference prices, not sales.** Snapshots store CSFloat's predicted price, not completed trades.
- **No forecasting.** It assumes prices revert. In a falling market most dips keep falling.
- **Thin evidence at the extremes.** Deep dips are rare, so the upper thresholds rest on few events.
- **Shared rate limit.** The snapshot job, scanner and anything else on your key draw from one allowance.
- **Buy orders aren't covered.** Only active buy-now listings are scanned.
- **Shipped thresholds are calibrated on one dataset.** They came from 85 days of AK-47 and M4A4 data (Jul–Oct 2026). Re-calibrate on your own.
- **No authentication on the dashboard.** The dev server is local only. For public hosting use `PUBLIC_MODE=1`, `ALLOWED_HOSTS`, a reverse proxy and a production WSGI server.
- **The CSP needs `'unsafe-inline'`** because the dashboard is a single self-contained file.
- **`develop` publishes your real data** if the repo stays public.

Not financial advice. The demo's prices and deals are synthetic.

## Version notes

The changelog calls this `v0.4.1-demo`, the first demo release on top of v0.4. Tag it as `v0.4` or `v0.4.1-demo`, whichever you prefer, and update `changelogs.txt` to match.
