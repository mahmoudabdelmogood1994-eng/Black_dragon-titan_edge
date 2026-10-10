"""Planet Tanager hyperspectral loader (ported from the uploaded notebooks).

Reads the surface-reflectance HDF5 of a Tanager Core Imagery scene
(`HDFEOS/GRIDS/HYP/Data Fields/...`) and its STAC item JSON (for the band
wavelengths and footprint). Only the 4 bands needed for the indices are read
into the Scene; the full cube is touched only (strided) to average spectra.

CAVEATS carried over from the notebooks:
* The scene is placed on the map from its STAC bbox (north-up ortho product),
  so positions are APPROXIMATE (basic, non-ortho products are not north-up).
* NDCI here is a spectral proxy, not ground-truth chlorophyll-a.
"""
from __future__ import annotations
import json, warnings
from typing import Dict, Tuple
import numpy as np
import h5py
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from satellite_analytics import Scene

ROOT = "HDFEOS/GRIDS/HYP/Data Fields"
TARGETS = {"green": 560, "red": 665, "rededge": 708, "nir": 860}   # nm (notebook)
BAD_RANGES = [(1350, 1450), (1800, 1950)]
SWIR_EDGE_NM = 2450


def _wavelengths(item: dict, sr_key: str) -> np.ndarray:
    meta = item["assets"][sr_key].get("bands") or item["assets"][sr_key].get("eo:bands") or []
    wl = [b.get("eo:center_wavelength", b.get("center_wavelength")) for b in meta]
    wl = np.array([w for w in wl if w is not None], dtype=float)
    if wl.size and wl.max() < 10:                    # micrometres -> nanometres
        wl *= 1000.0
    return wl


def load_tanager(h5_path: str, item_json: str) -> Scene:
    item = json.load(open(item_json))
    sr_key = "ortho_sr_hdf5" if "ortho_sr_hdf5" in item["assets"] else "basic_sr_hdf5"
    wl = _wavelengths(item, sr_key)
    with h5py.File(h5_path, "r") as f:
        cloud = f[f"{ROOT}/beta_cloud_mask"][:]
        nodata = f[f"{ROOT}/nodata_pixels"][:]
        cirrus = f[f"{ROOT}/beta_cirrus_mask"][:]
        sr = f[f"{ROOT}/surface_reflectance"]
        if sr.shape[0] != len(wl):
            raise ValueError(f"band count {sr.shape[0]} != wavelength count {len(wl)}")
        valid = (nodata == 0) & (cloud == 0) & (cirrus == 0)
        idx = {k: int(np.argmin(np.abs(wl - t))) for k, t in TARGETS.items()}
        bands = {}
        for k, i in idx.items():
            a = sr[i, :, :].astype("float32")
            a[~valid] = np.nan
            a[a < 0] = np.nan
            bands[k] = a
    h, w = valid.shape
    west, south, east, north = item["bbox"]
    meta = {"scene_id": item["id"], "datetime": item["properties"]["datetime"],
            "bbox": item["bbox"], "product": sr_key, "valid_pct": float(valid.mean() * 100),
            "wavelengths_nm": wl.tolist(), "band_index": idx, "h5_path": h5_path,
            "position": "approximate (STAC bbox)" if sr_key == "ortho_sr_hdf5"
                        else "NOT north-up: basic product, position unreliable"}
    return Scene(bands, from_bounds(west, south, east, north, w, h), CRS.from_epsg(4326),
                 "tanager", False, {"h5": h5_path, "stac": item_json}, meta)


def reference_spectra(sc: Scene, index: np.ndarray, stride: int = 3
                      ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Clean-water (NDCI <= scene median) and suspect-patch (NDCI >= p99)
    mean spectra over water pixels, exactly as in the notebooks.
    Returns (wavelengths_nm, clean, suspect); water-vapour / SWIR-edge bands = NaN."""
    wl = np.array(sc.meta["wavelengths_nm"])
    fin = np.isfinite(index)
    p50, p99 = np.nanpercentile(index[fin], 50), np.nanpercentile(index[fin], 99)
    clean_m, susp_m = fin & (index <= p50), fin & (index >= p99)
    bad = np.zeros(len(wl), bool)
    for lo, hi in BAD_RANGES:
        bad |= (wl >= lo) & (wl <= hi)
    bad |= wl > SWIR_EDGE_NM
    with h5py.File(sc.meta["h5_path"], "r") as f:
        cube = f[f"{ROOT}/surface_reflectance"][:, ::stride, ::stride].astype("float32")
    cube[bad] = np.nan
    cube[cube < 0] = np.nan

    def mean_spec(m):
        m = m[::stride, ::stride]
        if m.sum() == 0:
            return np.full(cube.shape[0], np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN bad bands
            return np.nanmean(cube[:, m], axis=1)

    return wl, mean_spec(clean_m), mean_spec(susp_m)
