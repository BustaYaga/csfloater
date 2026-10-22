import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# Demo data only: must be set before app/db are imported.
os.environ["DEMO_MODE"] = "1"
os.environ["CSFLOAT_DB"] = os.path.join(ROOT, "demo", "demo.db")
os.environ["CSFLOAT_CONFIG"] = os.path.join(ROOT, "demo", "config.demo.json")
os.environ["CSFLOAT_API_KEY"] = "must-never-be-used"
