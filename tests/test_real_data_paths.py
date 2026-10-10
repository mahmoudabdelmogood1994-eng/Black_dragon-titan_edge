"""Self-test of the REAL-data code paths using small STAND-IN files that copy
the structure the notebooks read (Sentinel-2 uint16 DN GeoTIFFs with the
+1000 offset and an SCL file; Tanager HDF5 + STAC JSON). Not real imagery.
Run from the repo root: python3 tests/test_real_data_paths.py"""
import json, os, sys, tempfile
import numpy as np, h5py, rasterio
from rasterio.transform import from_origin
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "space_twin"))
import satellite_analytics as S, tanager_loader as T
from config import Config, apply_presets

rng = np.random.default_rng(1)
tmp = tempfile.mkdtemp()

# ---- Sentinel-2 style ----
h = w = 300; tr = from_origin(56.30, 25.25, 0.0007, 0.0007)
yy, xx = np.mgrid[0:h, 0:w]; sea = xx > 60
bl = np.exp(-(((xx - 200) / 25.) ** 2 + ((yy - 150) / 25.) ** 2))
refl = {"B03": .032 + .006 * bl, "B04": .012 + .010 * bl, "B05": .010 + .024 * bl, "B08": .004 + .004 * bl}
for k, v in refl.items():
    dn = ((np.where(sea, v, .25) + .1) * 1e4 + rng.normal(0, 10, (h, w))).astype("uint16")
    with rasterio.open(f"{tmp}/T40_{k}_20m.tif", "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="uint16", crs="EPSG:4326", transform=tr, nodata=0) as d:
        d.write(dn, 1)
scl = np.full((h, w), 6, "uint8"); scl[:40, 100:160] = 9
with rasterio.open(f"{tmp}/T40_SCL_20m.tif", "w", driver="GTiff", height=h, width=w, count=1,
                   dtype="uint8", crs="EPSG:4326", transform=tr) as d:
    d.write(scl, 1)
sc = S.load_scene(tmp, "sentinel2")
med = float(np.nanmedian(sc.bands["red"][:, 100:]))
assert abs(med - 0.012) < 0.001, f"DN offset not applied: {med}"
assert np.isnan(sc.bands["red"][:40, 100:160]).all(), "SCL cloud mask not applied"
cfg = apply_presets(Config(), "sentinel2_real"); cfg.ndci_threshold = 0.15
_, ind, hs, _ = S.analyse_scene(sc, cfg)
assert len(hs) >= 1 and hs[0].n_px >= 8
print("sentinel-2 path OK: offset, SCL mask, hotspot found")

# ---- Tanager style ----
nb, H, W = 140, 120, 160
wl = np.linspace(380, 2500, nb); yy, xx = np.mgrid[0:H, 0:W]
bloom = np.exp(-(((xx - 120) / 10.) ** 2 + ((yy - 60) / 9.) ** 2))
sr = (0.03 * np.exp(-(wl - 380) / 500)[:, None, None] * np.ones((nb, H, W))).astype("float32")
for wv, dv in ((560, .004), (665, .006), (708, .022), (860, .003)):
    sr[int(np.argmin(abs(wl - wv)))] += dv * bloom
sr[:, :, :30] = 0.2
sr = np.clip(sr + rng.normal(0, .0008, sr.shape).astype("float32"), .0005, 1)
with h5py.File(f"{tmp}/T.h5", "w") as f:
    g = f.create_group("HDFEOS/GRIDS/HYP/Data Fields")
    g.create_dataset("surface_reflectance", data=sr)
    for n in ("beta_cloud_mask", "nodata_pixels", "beta_cirrus_mask"):
        g.create_dataset(n, data=np.zeros((H, W), "uint8"))
json.dump({"id": "STANDIN", "bbox": [56.30, 25.05, 56.55, 25.25],
           "properties": {"datetime": "2025-02-23T16:55:46Z"},
           "assets": {"ortho_sr_hdf5": {"href": "x", "bands": [{"eo:center_wavelength": v / 1000} for v in wl]}}},
          open(f"{tmp}/T.json", "w"))
sc = T.load_tanager(f"{tmp}/T.h5", f"{tmp}/T.json")
cfg = apply_presets(Config(), "fujairah", "tanager")
sc, ind, hs, _ = S.analyse_scene(sc, cfg)
assert len(hs) == 1 and 56.40 < hs[0].lon < 56.55, hs
wl2, clean, susp = T.reference_spectra(sc, ind["index"])
i708, i665 = int(np.argmin(abs(wl2 - 708))), int(np.argmin(abs(wl2 - 665)))
assert susp[i708] - clean[i708] > susp[i665] - clean[i665], "red-edge rise missing"
print("tanager path OK: bands, masks, hotspot, clean-vs-suspect spectra")
