import os
import threading

from flask import Flask, abort, jsonify, render_template, request

import analytics
import db
from scanner import DipScanner
from config_loader import load_config

app = Flask(__name__)

# DEMO_MODE=1 serves bundled synthetic data only: no API key is read, no
# scanner is built, and every write endpoint is refused.
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

# PUBLIC_MODE=1 makes the site read-only for visitors: no Scan now / Clear,
# so strangers can't spend your CSFloat request allowance or wipe deals.
PUBLIC_MODE = DEMO_MODE or os.environ.get("PUBLIC_MODE", "").lower() in ("1", "true", "yes")

# The data dashboard only reads the database, so it works without an API key.
# Live scanning needs CSFLOAT_API_KEY and is switched off when it's missing.
CONFIG = load_config(require_api_key=False)
if DEMO_MODE:
    CONFIG["csfloat_api_key"] = None

db.init_db()
scanner = DipScanner(CONFIG) if CONFIG.get("csfloat_api_key") and not PUBLIC_MODE else None

# Host-header allowlist (blocks DNS-rebinding against the local server).
# Set ALLOWED_HOSTS="example.com,www.example.com" when hosting publicly,
# or "*" to turn the check off.
_hosts = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
ALLOWED_HOSTS = {h.strip().lower() for h in _hosts.split(",") if h.strip()}

CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
       "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")


@app.before_request
def guard():
    if "*" not in ALLOWED_HOSTS:
        host = request.host.lower()
        if host.startswith("["):
            hostname = host.split("]")[0] + "]"
        else:
            hostname = host.split(":")[0]
        if hostname not in ALLOWED_HOSTS:
            abort(400)
    # State-changing calls must carry a custom header, which a cross-site
    # form or <img> can't add (CSRF), and are limited to POST.
    if request.method == "POST" and request.headers.get("X-Requested-With") != "csfloater":
        abort(403)


@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/dataset")
def api_dataset():
    data = analytics.build_dataset(CONFIG)
    data["scanner_enabled"] = scanner is not None
    data["public_mode"] = PUBLIC_MODE
    data["demo_mode"] = DEMO_MODE
    return jsonify(data)


@app.route("/api/deals")
def api_deals():
    return jsonify(db.get_recent_deals())


@app.route("/api/scan-now", methods=["POST"])
def scan_now():
    if PUBLIC_MODE:
        return jsonify({"error": "Scanning is disabled on the public site."}), 403
    if scanner is None:
        return jsonify({"error": "CSFLOAT_API_KEY is not set, so live scanning is off."}), 503
    deals = scanner.run_once()
    return jsonify({"found": len(deals)})


@app.route("/api/clear", methods=["POST"])
def clear():
    if PUBLIC_MODE:
        return jsonify({"error": "Clearing is disabled on the public site."}), 403
    db.clear_deals()
    return jsonify({"status": "cleared"})


def start_background_scanner():
    t = threading.Thread(target=scanner.run_continuous, daemon=True)
    t.start()


def main(port=5000):
    if scanner is not None:
        start_background_scanner()
    elif DEMO_MODE:
        print("DEMO_MODE: serving synthetic data, read-only, no API key used.")
    else:
        print("Live scanning is off (no CSFLOAT_API_KEY or PUBLIC_MODE) - serving the dashboard only.")
    # Bound to loopback on purpose; put a reverse proxy in front to expose it.
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
