# CSFloat Dip Scanner

Finds CS2 pistol (or any category you set) listings on CSFloat that are priced
well below their recent baseline sale price, on the bet that price reverts
toward the baseline — your mean-reversion strategy, automated.

## How it works

1. **csfloat_client.py** pulls live `buy_now` listings from CSFloat's official
   API (paginated, rate-limit aware).
2. **history_client.py** pulls each item's recent daily sale price/volume from
   cs2.sh (`/v1/archive/csfloat`) — CSFloat's own API doesn't expose history,
   so this fills that gap.
3. **scanner.py** computes a baseline price (median of the last N days,
   excluding the most recent couple of days) per item, and flags listings
   that are priced X–Y% below that baseline with enough sales volume to be
   confident you can resell.
4. Results are stored in **deals.db** (SQLite) and shown on a small
   **Flask dashboard** (`app.py` + `templates/index.html`).

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your keys:
- `CSFLOAT_API_KEY` — from your CSFloat profile → Developer tab
- `CS2SH_API_KEY` — from cs2.sh once you sign up

Edit `config.json` for strategy tuning:
- `included_weapons` — substrings matched against `market_hash_name`
   (defaults to common pistols)
- tune `min_dip_percentage` / `max_dip_percentage` / `baseline_window_days` /
  `min_sales_in_window` to taste — start conservative and loosen once you've
  sanity-checked a few flagged deals by eye

## Run

One-off scan (prints to console, saves to DB):
```bash
python scanner.py
```

Dashboard with background auto-scanning:
```bash
python app.py
```
Then open http://127.0.0.1:5000

## Before you trust it with real money

- **`history_client.py` is a stub.** I built it against cs2.sh's public
  marketing description, not a confirmed API schema — once you have your key,
  hit `/v1/archive/csfloat` manually (curl/Postman), compare the real response
  shape to what `get_sales_history()` expects, and adjust field names /
  auth header if needed. Everything else in the project only depends on
  `get_sales_history()`'s return shape, so that's the only place you should
  need to touch.
- **Liquidity check is coarse.** `sales_in_window` sums raw `volume` fields
  across baseline days — sanity check a few flagged items manually before
  trusting the number.
- **This doesn't distinguish "temporary dip" from "permanent repricing."**
  A dip caused by a case leaving the drop pool, a nerf, or a large one-time
  dump won't revert. Eyeball the flagged list before buying, at least at first.
- **Buy orders aren't covered yet.** This only scans active `buy_now`
  listings. If you want a similar scan against your open/potential buy
  orders, that's a small addition to `csfloat_client.py` (CSFloat's buy-order
  endpoints aren't in the official public docs but exist — some unofficial
  Python wrappers like `Rushifakami/csfloat_api` cover them if you want a
  reference).
