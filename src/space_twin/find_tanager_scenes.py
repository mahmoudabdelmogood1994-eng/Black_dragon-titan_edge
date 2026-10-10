#!/usr/bin/env python3
"""List Planet Tanager open-data scenes that overlap an area (needs internet; not run in the build sandbox).

  python3 find_tanager_scenes.py --bbox 53.36 24.04 53.54 24.20 --intake 24.1393236 53.4566472

Scans every item of the coastal-water-bodies collection (one small JSON per scene) and prints the scenes
whose footprint intersects the bbox, marking those that also contain the intake. Footprints come from the
STAC `bbox`, so they are approximate. Use --collection for another Tanager theme.
"""
import argparse
from urllib.parse import urljoin
import requests

BASE = "https://www.planet.com/data/stac/tanager-core-imagery"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    ap.add_argument("--intake", nargs=2, type=float, metavar=("LAT", "LON"))
    ap.add_argument("--collection", default="coastal-water-bodies")
    a = ap.parse_args()
    url = f"{BASE}/{a.collection}/collection.json"
    col = requests.get(url, timeout=60).json()
    links = [l for l in col.get("links", []) if l.get("rel") == "item"]
    print(f"{len(links)} scenes in '{a.collection}'; checking footprints...")
    W, S, E, N = a.bbox
    hits = 0
    for l in links:
        try:
            it = requests.get(urljoin(url, l["href"]), timeout=60).json()
            w, s, e, n = it["bbox"]
        except Exception as exc:                      # a broken item must not stop the scan
            print("skipped item:", exc)
            continue
        if w <= E and e >= W and s <= N and n >= S:
            hits += 1
            inside = bool(a.intake) and (w <= a.intake[1] <= e and s <= a.intake[0] <= n)
            print(f"{it['id']}  {it['properties']['datetime'][:10]}  bbox=[{w:.2f}, {s:.2f}, {e:.2f}, {n:.2f}]"
                  + ("  CONTAINS INTAKE" if inside else ""))
    if not hits:
        print("No scene overlaps this area: use Sentinel-2 only and say so.")


if __name__ == "__main__":
    main()
