import os
import threading

from flask import Flask, render_template, jsonify

import analytics
import db
from scanner import DipScanner
from config_loader import load_config

app = Flask(__name__)

# The data dashboard only reads deals.db, so it works without an API key.
# Live scanning needs CSFLOAT_API_KEY and is switched off when it's missing.
CONFIG = load_config(require_api_key=False)

db.init_db()
scanner = DipScanner(CONFIG) if CONFIG.get("csfloat_api_key") else None

# PUBLIC_MODE=1 makes the site read-only for visitors: no Scan now / Clear,
# so strangers can't spend your CSFloat request allowance or wipe deals.
PUBLIC_MODE = os.environ.get("PUBLIC_MODE", "").lower() in ("1", "true", "yes")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dataset")
def api_dataset():
    data = analytics.build_dataset(CONFIG)
    data["scanner_enabled"] = scanner is not None
    data["public_mode"] = PUBLIC_MODE
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


if __name__ == "__main__":
    if scanner is not None:
        start_background_scanner()
    else:
        print("CSFLOAT_API_KEY not set - serving the dashboard without live scanning.")
    app.run(debug=False, port=5000)
