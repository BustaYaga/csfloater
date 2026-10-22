"""
Empirically builds a skin catalog per weapon: paint_index -> base skin name
(wear stripped off), discovered from live listing data. Avoids hand-curating
a skin list that goes stale every time a new case/collection releases.

Run: python discover_paint_indices.py
Re-run periodically (e.g. monthly) to pick up newly released skins.
"""
import json
import re
from collections import defaultdict

from clients.csfloat_client import CSFloatClient
from config_loader import load_config

cfg = load_config()
client = CSFloatClient(cfg["csfloat_api_key"])

WEAR_SUFFIX = re.compile(r"\s*\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)\s*$")

catalog = {}  # weapon_name -> {paint_index: base_skin_name}

for weapon_name, def_index in cfg["weapon_def_indices"].items():
    print(f"Scanning {weapon_name} (def_index={def_index})...")
    listings = client.fetch_listings(
        def_index=def_index,
        max_pages=6,          # wide net per weapon to catch as many distinct skins as possible
        sort_by="most_recent",  # NOT lowest_price - that would bias toward cheap skins only
        type_="buy_now",
    )
    skins = {}
    for listing in listings:
        info = listing.get("item", {})
        name = info.get("market_hash_name", "")
        paint_index = info.get("paint_index")
        if not name or paint_index is None:
            continue
        if info.get("is_souvenir"):
            continue
        base_name = WEAR_SUFFIX.sub("", name).replace("StatTrak\u2122 ", "").strip()
        rarity_name = info.get("rarity_name", "")
        skins[paint_index] = {"name": base_name, "rarity": rarity_name}
    catalog[weapon_name] = skins
    print(f"  found {len(skins)} distinct skins")

with open("skin_catalog.json", "w", encoding="utf-8") as f:
    json.dump(catalog, f, indent=2, ensure_ascii=False)

total = sum(len(v) for v in catalog.values())
print(f"\nSaved skin_catalog.json - {total} total distinct skins across {len(catalog)} weapons.")
print("Re-run this periodically; a single pass won't catch every skin in one go "
      "(rare/expensive skins have fewer listings and may need multiple runs to surface).")