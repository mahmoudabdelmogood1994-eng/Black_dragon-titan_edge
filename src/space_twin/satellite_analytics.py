"""MOD 1  Macro-sensing & spectral processing.

Reads GeoTIFF bands, computes NDWI (water mask) and NDCI (chlorophyll),
extracts hotspots above a threshold and scores their risk.

NDCI = (RedEdge - Red) / (RedEdge + Red)        Mishra & Mishra, 2012
  Sentinel-2: RedEdge = B5 (705 nm), Red = B4 (665 nm)
NDWI = (Green - NIR) / (Green + NIR)            water mask (B3, B8)

Landsat 8/9 has no red-edge band, so true NDCI is NOT computable there; the
code falls back to a labelled NIR-red proxy and says so in its output.
"""
from __future__ import annotations
import glob, math, os, re, time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform
from scipy import ndimage as ndi
from config import Config
from geo import dist_km

BANDS = {"sentinel2": {"green": "B0?3", "red": "B0?4", "rededge": "B0?5", "nir": "B0?8"},
         "landsat": {"green": "B0?3", "red": "B0?4", "nir": "B0?5"}}
SCALE = {"sentinel2": (1e-4, -0.1), "landsat": (2.75e-5, -0.2)}   # integer DN only
# Sentinel-2 L2A processing baseline >= 04.00 (since 2022) adds a +1000 DN offset:
# reflectance = DN/10000 - 0.1.  Float GeoTIFFs written by data_sources.py are already scaled.
SCL_BAD = (0, 1, 3, 8, 9, 10, 11)   # nodata, saturated, shadow, cloud, cirrus, snow
SCL_PAT = "SCL"


@dataclass
class Scene:
    bands: Dict[str, np.ndarray]
    transform: object
    crs: object
    sensor: str
    synthetic: bool
    files: Dict[str, str]
    meta: dict = None


@dataclass
class Hotspot:
    id: int
    lat: float
    lon: float
    area_km2: float
    n_px: int
    radius_km: float
    mean_index: float
    max_index: float
    dist_to_plant_km: float
    risk_pct: float
    index_name: str


def _find(data_dir: str, pat: str) -> Optional[str]:
    rx = re.compile(rf"(?:^|[_.\-]){pat}(?:[_.\-]|$)", re.I)
    hits = [f for f in glob.glob(os.path.join(data_dir, "**", "*"), recursive=True)
            if f.lower().endswith((".tif", ".tiff", ".nc")) and rx.search(os.path.basename(f))]
    return sorted(hits)[0] if hits else None


def load_scene(data_dir: str, sensor: str) -> Scene:
    """Load bands onto the grid of the first band (bilinear resample, e.g.
    Sentinel-2 B5 20 m -> 10 m). Integer DNs are converted to reflectance."""
    files, bands, ref = {}, {}, None
    scale, offset = SCALE[sensor]
    for name, pat in BANDS[sensor].items():
        f = _find(data_dir, pat)
        if f is None:
            if name == "rededge":
                continue
            raise FileNotFoundError(f"band '{name}' ({pat}) not found in {data_dir}")
        files[name] = f
        with rasterio.open(f) as ds:
            if ref is None:
                ref = (ds.transform, ds.crs, ds.height, ds.width)
            arr = ds.read(1, out_shape=(ref[2], ref[3]),
                          resampling=Resampling.bilinear).astype("float32")
            if np.issubdtype(np.dtype(ds.dtypes[0]), np.integer):
                nd = ds.nodata if ds.nodata is not None else 0
                arr = np.where(arr == nd, np.nan, arr * scale + offset)
            elif ds.nodata is not None:
                arr = np.where(arr == ds.nodata, np.nan, arr)
            bands[name] = arr
    f = _find(data_dir, SCL_PAT)                       # optional cloud/shadow mask
    if f is not None and "scl" not in files:
        with rasterio.open(f) as ds:
            scl = ds.read(1, out_shape=(ref[2], ref[3]), resampling=Resampling.nearest)
        bad = np.isin(scl, SCL_BAD)
        for k in bands:
            bands[k] = np.where(bad, np.nan, bands[k])
        files["scl"] = f
    meta = {}
    mp = os.path.join(data_dir, "meta.json")
    if os.path.exists(mp):
        import json
        meta = json.load(open(mp))
    synth = os.path.exists(os.path.join(data_dir, "README_SYNTHETIC.txt"))
    return Scene(bands, ref[0], ref[1], sensor, synth, files, meta)


def _nd(a, b):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (a - b) / (a + b)


def compute_indices(sc: Scene, cfg: Config) -> Dict:
    b = sc.bands
    water = _nd(b["green"], b["nir"]) > cfg.ndwi_threshold      # NDWI mask
    if "rededge" in b:
        idx, name = _nd(b["rededge"], b["red"]), "NDCI"
    else:
        idx, name = _nd(b["nir"], b["red"]), "NIR-red proxy (NOT NDCI)"
    if cfg.coast_buffer_px > 0:                     # land-adjacent pixels are mixed (adjacency effect)
        water = ndi.binary_erosion(water, structure=np.ones((3, 3)), iterations=cfg.coast_buffer_px)
    idx = np.where(water, idx, np.nan)
    return {"index": idx, "water": water, "index_name": name}


def _px_area_km2(sc: Scene, lat: float) -> float:
    a, e = abs(sc.transform.a), abs(sc.transform.e)
    if sc.crs is not None and sc.crs.is_geographic:
        return a * 111320 * math.cos(math.radians(lat)) * e * 110574 / 1e6
    return a * e / 1e6


def _risk(mean_idx, thr, area, dist) -> float:
    """Heuristic, UNCALIBRATED: 45 % severity + 25 % extent + 30 % proximity."""
    sev = np.clip((mean_idx - thr) / 0.30, 0, 1)
    ext = np.clip(area / 5.0, 0, 1)
    prox = np.clip(1 - dist / 30.0, 0, 1)
    return float(100 * (0.45 * sev + 0.25 * ext + 0.30 * prox))


def detect_hotspots(sc: Scene, ind: Dict, cfg: Config) -> List[Hotspot]:
    idx = ind["index"]
    mask = np.nan_to_num(idx, nan=-9) > cfg.ndci_threshold
    mask = ndi.binary_opening(mask, structure=np.ones((3, 3)))   # drop speckle
    lab, n = ndi.label(mask)
    out: List[Hotspot] = []
    for k in range(1, n + 1):
        m = lab == k
        r, c = np.nonzero(m)
        x, y = sc.transform * (c.mean() + 0.5, r.mean() + 0.5)
        lons, lats = warp_transform(sc.crs, "EPSG:4326", [x], [y])
        lat, lon = float(lats[0]), float(lons[0])
        area = float(m.sum() * _px_area_km2(sc, lat))
        if area < cfg.min_area_km2 or m.sum() < cfg.min_cluster_px:
            continue
        d = dist_km(cfg.plant_lat, cfg.plant_lon, lat, lon)
        mean_i = float(np.nanmean(idx[m]))
        out.append(Hotspot(0, lat, lon, area, int(m.sum()), math.sqrt(area / math.pi), mean_i,
                           float(np.nanmax(idx[m])), d,
                           _risk(mean_i, cfg.ndci_threshold, area, d), ind["index_name"]))
    out.sort(key=lambda h: -h.risk_pct)
    for i, h in enumerate(out, 1):
        h.id = i
    return out


def extent(sc: Scene):
    h, w = next(iter(sc.bands.values())).shape
    t = sc.transform
    (x0, y0), (x1, y1) = t * (0, 0), t * (w, h)
    lons, lats = warp_transform(sc.crs, "EPSG:4326", [x0, x1], [y0, y1])
    return min(lons), min(lats), max(lons), max(lats)


def analyse(data_dir: str, cfg: Config):
    return analyse_scene(load_scene(data_dir, cfg.sensor), cfg)


def analyse_scene(sc: Scene, cfg: Config):
    t = time.perf_counter()
    ind = compute_indices(sc, cfg)
    hs = detect_hotspots(sc, ind, cfg)
    return sc, ind, hs, time.perf_counter() - t
