"""Download real imagery (run this on a machine with internet access).

  python3 data_sources.py sentinel2 --bbox 56.30 25.05 56.55 25.25 \
          --time 2025-02-15/2025-03-15 --out data/fujairah_s2
  python3 data_sources.py tanager --item 20250223_165546_32_4001 --out data/tanager

Ported from the uploaded notebooks (Planetary Computer STAC for Sentinel-2 L2A,
Planet STAC for Tanager). NOT executed in the build sandbox, whose network
blocks both hosts; the file-reading side is tested on stand-in files.
Optional deps: pystac-client planetary-computer stackstac rioxarray requests
"""
from __future__ import annotations
import argparse, json, math, os
import numpy as np

SCL_BAD = [0, 1, 3, 8, 9, 10, 11]
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
TANAGER_BASE = "https://www.planet.com/data/stac/tanager-core-imagery"


def utm_epsg(lon: float, lat: float) -> int:
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1


def fetch_sentinel2(bbox, time_range, out_dir, cloud_max=30, max_scenes=5, resolution=20):
    """Cloud-masked (SCL) median composite of the least-cloudy scenes, written
    as float reflectance GeoTIFFs S2_B03/B04/B05/B08.tif + meta.json."""
    import pystac_client, planetary_computer, stackstac
    import rioxarray  # noqa: F401  (registers .rio)
    cat = pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=["sentinel-2-l2a"], bbox=bbox, datetime=time_range,
                            query={"eo:cloud_cover": {"lt": cloud_max}}).item_collection())
    if not items:
        raise RuntimeError("no Sentinel-2 scenes: widen time range or raise cloud_max")
    items = sorted(items, key=lambda i: i.properties.get("eo:cloud_cover", 100))[:max_scenes]
    epsg = utm_epsg((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    data = stackstac.stack(items, assets=["B03", "B04", "B05", "B08", "SCL"],
                           resolution=resolution, bounds_latlon=bbox, epsg=epsg,
                           dtype="float32", fill_value=np.float32("nan"), rescale=False,   # np.nan alone fails on NumPy 2
                           chunksize=1024).compute()
    bad = data.sel(band="SCL").drop_vars("band").isin(SCL_BAD)
    os.makedirs(out_dir, exist_ok=True)
    for b in ("B03", "B04", "B05", "B08"):
        refl = ((data.sel(band=b).drop_vars("band") / 10000.0) - 0.1).where(~bad)  # baseline>=04.00
        comp = refl.median("time", skipna=True).reset_coords(drop=True)
        comp.rio.write_crs(f"EPSG:{epsg}").rio.to_raster(os.path.join(out_dir, f"S2_{b}.tif"))
    dts = sorted(i.datetime for i in items)
    meta = {"source": "Sentinel-2 L2A (Planetary Computer)", "scenes": [i.id for i in items],
            "datetime": dts[len(dts) // 2].strftime("%Y-%m-%dT%H:%M:%SZ"), "bbox": list(bbox),
            "composite": f"median of {len(items)} scenes, SCL-masked"}
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
    return out_dir


def fetch_tanager(item_id, out_dir, collection="coastal-water-bodies"):
    """Download the STAC item JSON and the surface-reflectance HDF5 (1-5 GB)."""
    import requests
    os.makedirs(out_dir, exist_ok=True)
    base = f"{TANAGER_BASE}/{collection}"
    r = requests.get(f"{base}/{item_id}/{item_id}.json", timeout=60)
    r.raise_for_status()
    item = r.json()
    jp = os.path.join(out_dir, f"{item_id}.json")
    json.dump(item, open(jp, "w"))
    key = "ortho_sr_hdf5" if "ortho_sr_hdf5" in item["assets"] else "basic_sr_hdf5"
    url = item["assets"][key]["href"]
    hp = os.path.join(out_dir, os.path.basename(url))
    if not os.path.exists(hp):
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(hp, "wb") as f:
                for chunk in resp.iter_content(1024 * 1024):
                    f.write(chunk)
    return hp, jp


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("sentinel2")
    a.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    a.add_argument("--time", required=True)
    a.add_argument("--cloud-max", type=float, default=30)
    a.add_argument("--out", required=True)
    b = sub.add_parser("tanager")
    b.add_argument("--item", required=True)
    b.add_argument("--collection", default="coastal-water-bodies")
    b.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.cmd == "sentinel2":
        print("wrote", fetch_sentinel2(args.bbox, args.time, args.out, args.cloud_max))
    else:
        h5p, jp = fetch_tanager(args.item, args.out, args.collection)
        print("wrote", h5p, jp)
