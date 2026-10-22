"""
Empirically discovers the def_index for each weapon you name by
pulling live listings and cross-referencing market_hash_name -> def_index.
Run this once to build a trustworthy weapon_def_index map, instead of
hardcoding guessed IDs from the internet (wrong IDs fail silently).

Run: python discover_def_indices.py "AK-47" "AWP" "Desert Eagle"
     (no arguments = the weapons already in config.json's weapon_def_indices)
Then copy the printed numbers into weapon_def_indices in config.json.
"""
import sys
from collections import defaultdict

from clients.csfloat_client import CSFloatClient
from config_loader import load_config

cfg = load_config()
weapons = sys.argv[1:] or list(cfg["weapon_def_indices"].keys())
client = CSFloatClient(cfg["csfloat_api_key"])

# Pull a broad, unfiltered sample across a wide price range to maximize
# the chance of seeing every weapon at least once.
listings = client.fetch_listings(
    min_price_cents=100,       # $1
    max_price_cents=20000,     # $200
    max_pages=15,
    sort_by="most_recent",
    type_="buy_now",
)
print(f"Fetched {len(listings)} listings\n")

seen = defaultdict(set)  # weapon substring -> set of def_index values observed
unmatched_names = set()

for listing in listings:
    info = listing.get("item", {})
    name = info.get("market_hash_name", "")
    def_index = info.get("def_index")
    if not name or def_index is None:
        continue

    matched_any = False
    for weapon in weapons:
        if weapon in name:
            seen[weapon].add(def_index)
            matched_any = True
    if not matched_any and info.get("type") == "skin":
        unmatched_names.add(name)

print("=== def_index per weapon (from live data) ===")
for weapon in weapons:
    indices = seen.get(weapon)
    if not indices:
        print(f"{weapon:<15} NOT SEEN this run - try again, or check name casing")
    elif len(indices) == 1:
        print(f"{weapon:<15} def_index = {indices.pop()}  (consistent)")
    else:
        print(f"{weapon:<15} SAW MULTIPLE def_index VALUES: {indices}  <-- investigate, unexpected")

print(f"\n(Sampled {len(listings)} listings - weapons marked NOT SEEN may just need a bigger/wider sample, "
      f"not necessarily a wrong name. Re-run a few times and merge results if needed.)")