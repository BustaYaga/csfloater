"""
Start the dashboard on the bundled synthetic demo data. No API key, no
network, read-only.

    python run_demo.py                 # http://127.0.0.1:5000
    python run_demo.py --port 8000
    python run_demo.py --regenerate    # rebuild demo/demo.db first
    python run_demo.py --export        # also rewrite demo/demo.html (offline copy)
"""
import argparse
import os
import subprocess  # nosec B404 - only runs this repo's own scripts
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(ROOT, "demo")

# Must be set before db/config_loader/app are imported.
os.environ["DEMO_MODE"] = "1"
os.environ["CSFLOAT_DB"] = os.path.join(DEMO, "demo.db")
os.environ["CSFLOAT_CONFIG"] = os.path.join(DEMO, "config.demo.json")
os.chdir(ROOT)


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--regenerate", action="store_true")
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()

    if args.regenerate or not os.path.exists(os.environ["CSFLOAT_DB"]):
        subprocess.run([sys.executable, os.path.join(DEMO, "generate_demo_data.py")], check=True)  # nosec B603
    if args.export:
        subprocess.run([sys.executable, "export_dashboard.py", "-o", os.path.join(DEMO, "demo.html")],
                       check=True)  # nosec B603

    import app
    print(f"Demo dashboard: http://127.0.0.1:{args.port}")
    app.main(port=args.port)


if __name__ == "__main__":
    main()
