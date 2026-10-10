"""Test of compare_tanager_s2.py on STAND-IN files (same bloom seen by both sensors). Not real data.
Run from the repo root: python3 tests/test_compare_tanager_s2.py"""
import json, os, sys, tempfile
import numpy as np, h5py, rasterio
from rasterio.transform import from_bounds
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "space_twin"))
import compare_tanager_s2 as C

rng = np.random.default_rng(2); d = tempfile.mkdtemp()
bbox = [56.30, 25.05, 56.55, 25.25]
def bloom(h, w): yy, xx = np.mgrid[0:h, 0:w]; return np.exp(-(((xx - .75 * w) / (.07 * w)) ** 2 + ((yy - .5 * h) / (.1 * h)) ** 2))
# Tanager stand-in (140 bands, 120x160)
nb, H, W = 140, 120, 160; wl = np.linspace(380, 2500, nb); b = bloom(H, W)
sr = np.full((nb, H, W), 0.02, dtype="float32")
# same physical scene as the Sentinel-2 stand-in: identical baseline and bloom increments in the four bands
for wv, base_, dv in ((560, .032, .006), (665, .012, .006), (708, .010, .022), (860, .004, .003)):
    sr[int(np.argmin(abs(wl - wv)))] = base_ + dv * b
sr = np.clip(sr + rng.normal(0, .0004, sr.shape).astype("float32"), .0005, 1)
with h5py.File(f"{d}/T.h5", "w") as f:
    g = f.create_group("HDFEOS/GRIDS/HYP/Data Fields"); g.create_dataset("surface_reflectance", data=sr)
    for n in ("beta_cloud_mask", "nodata_pixels", "beta_cirrus_mask"): g.create_dataset(n, data=np.zeros((H, W), "uint8"))
json.dump({"id": "STANDIN", "bbox": bbox, "properties": {"datetime": "2025-02-23T07:00:00Z"},
           "assets": {"ortho_sr_hdf5": {"href": "x", "bands": [{"eo:center_wavelength": v / 1000} for v in wl]}}}, open(f"{d}/T.json", "w"))
# Sentinel-2 stand-in (float reflectance, EPSG:4326, 300x400), same bloom
h, w = 300, 400; b2 = bloom(h, w)
refl = {"B03": .032 + .006 * b2, "B04": .012 + .006 * b2, "B05": .010 + .022 * b2, "B08": .004 + .003 * b2}
os.makedirs(f"{d}/s2"); tr = from_bounds(*bbox, w, h)
for k, v in refl.items():
    with rasterio.open(f"{d}/s2/S2_{k}.tif", "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:4326", transform=tr) as o:
        o.write((v + rng.normal(0, .0004, (h, w))).astype("float32"), 1)
json.dump({"datetime": "2025-02-23T07:10:00Z"}, open(f"{d}/s2/meta.json", "w"))
out, pair = C.compare(f"{d}/T.h5", f"{d}/T.json", f"{d}/s2", 0.10)
assert out["n_common_pixels"] > 1000 and out["pearson_r"] > 0.8 and abs(out["bias_tanager_minus_s2"]) < 0.01, out
assert abs(out["tanager_pixels_above_thr"] - out["s2_pixels_above_thr"]) <= 0.1 * out["s2_pixels_above_thr"], out
assert "warning" not in out
print(f"compare OK on stand-ins: r={out['pearson_r']:.2f}, bias={out['bias_tanager_minus_s2']:+.3f}, n={out['n_common_pixels']}")
