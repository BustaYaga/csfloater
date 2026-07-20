import threading

from flask import Flask, render_template, jsonify

import db
from scanner import DipScanner
from config_loader import load_config

app = Flask(__name__)

CONFIG = load_config()

db.init_db()
scanner = DipScanner(CONFIG)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/deals")
def api_deals():
    return jsonify(db.get_recent_deals())


@app.route("/api/scan-now", methods=["POST"])
def scan_now():
    deals = scanner.run_once()
    return jsonify({"found": len(deals)})


@app.route("/api/clear", methods=["POST"])
def clear():
    db.clear_deals()
    return jsonify({"status": "cleared"})


def start_background_scanner():
    t = threading.Thread(target=scanner.run_continuous, daemon=True)
    t.start()


if __name__ == "__main__":
    start_background_scanner()
    app.run(debug=False, port=5000)
