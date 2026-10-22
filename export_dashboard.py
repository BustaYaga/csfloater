"""
Write the dashboard as one self-contained HTML file with the current data
baked in, so it can be opened offline or shared without running app.py.

    python export_dashboard.py                  # -> dashboard_export.html
    python export_dashboard.py -o report.html
"""
import argparse
import json
import os

import analytics
import db
from config_loader import load_config

TEMPLATE = "templates/index.html"


def _script_json(obj):
    # Safe to drop inside <script>: no "</script>" or HTML comment openers.
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("-o", "--output", default="dashboard_export.html")
    args = parser.parse_args()

    config = load_config(require_api_key=False)
    db.init_db()
    dataset = analytics.build_dataset(config)
    dataset["demo_mode"] = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")
    deals = db.get_recent_deals()

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    payload = (f"<script>window.__DATASET__={_script_json(dataset)};"
               f"window.__DEALS__={_script_json(deals)};</script>\n")
    marker = '<div id="tip" hidden></div>'
    if marker not in html:
        raise RuntimeError(f"Couldn't find {marker!r} in {TEMPLATE}")
    html = html.replace(marker, marker + "\n" + payload, 1)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    o = dataset["overview"]
    print(f"Wrote {args.output}: {o['snapshot_rows']} snapshots, {o['items']} skins, "
          f"{o['collection_days']} days ({o['first_date']} to {o['last_date']}).")


if __name__ == "__main__":
    main()
