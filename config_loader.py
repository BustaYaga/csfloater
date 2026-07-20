# """
# Single point where secrets (.env) and strategy config (config.json) are
# merged into one settings dict. Everything else in the project should import
# from here instead of touching os.environ or config.json directly.
# """
import json
import os
from dotenv import load_dotenv

load_dotenv()


def load_config(path="config.json"):
    with open(path) as f:
        config = json.load(f)

    csfloat_key = os.environ.get("CSFLOAT_API_KEY")

    if not csfloat_key:
        raise RuntimeError("CSFLOAT_API_KEY not set — copy .env.example to .env and fill it in")

    config["csfloat_api_key"] = csfloat_key
    return config