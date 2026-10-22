# Security notes

## Threat model
A single-user tool that stores price history in a local SQLite file and
calls the CSFloat API with your key. The dashboard is meant for
`127.0.0.1`. Publishing it needs a reverse proxy, `PUBLIC_MODE=1` and
`ALLOWED_HOSTS` (see README).

## Controls (CIA)
**Confidentiality**
- The API key is read only from the environment or `.env` (git-ignored) and is sent only in the `Authorization` header to `https://csfloat.com`. It is never logged, stored in the DB or returned by any endpoint.
- `DEMO_MODE=1` never reads the key at all.
- `deals.db`, `scan_position.json`, `rate_state.json` and `logs/` are git-ignored. On `main` they are absent. The snapshot/scan workflows commit real data only to `develop`; on a public repo that data is public. Make the repo private if that matters.
- The page makes no third-party requests (no CDN, no fonts) and the CSP (`default-src 'none'`, `connect-src 'self'`) blocks any. `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.

**Integrity**
- All SQL is parameterised. All dynamic HTML is escaped; deal links must match `https://csfloat.com/item/<token>`; listing ids are validated server-side.
- State-changing endpoints are POST-only, require an `X-Requested-With` header (CSRF) and are refused entirely in `PUBLIC_MODE`/`DEMO_MODE`.
- Host-header allowlist against DNS rebinding.
- Dependencies are pinned and audited with `pip-audit` in CI.

**Availability**
- Public mode stops visitors from spending your CSFloat rate limit or clearing data.
- The rate-limit gate stops requests when the allowance is nearly spent.

## Known limits
- `script-src` needs `'unsafe-inline'` because the dashboard is one self-contained file.
- No authentication: don't expose a non-public-mode instance to a network.
- Flask's dev server is not a production server; use gunicorn/waitress behind a proxy for public hosting.
- The dashboard has no rate limiting of its own; do that in the proxy.

Report issues privately to the repository owner.
