"""Offline smoke test of the Mirfa monitor (`s2` mode) on a SYNTHETIC scene with one
planted bloom 4 km from the assumed intake. Not satellite data. Run from the repo root:
    python3 tests/test_mirfa_pipeline.py
Needs: numpy scipy tifffile pyproj pillow"""
import json, os, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "mirfa_monitor"))
import titan_hab_pipeline as H
from pyproj import Transformer

bbox, epsg = [53.36, 24.04, 53.54, 24.20], 32639
tf = Transformer.from_crs(4326, epsg, always_xy=True)
x0, y1 = tf.transform(bbox[0], bbox[3]); x1, y0 = tf.transform(bbox[2], bbox[1])
res = 20.0; W, Hh = int((x1 - x0) / res), int((y1 - y0) / res)
yy, xx = np.mgrid[0:Hh, 0:W]; rng = np.random.default_rng(0)
land = yy > (Hh * 0.62 + 25 * np.sin(xx / 90.0))
bloom = np.exp(-(((xx - 300) / 25.) ** 2 + ((yy - 250) / 20.) ** 2))
base = {"B03": .060, "B04": .040, "B05": .041, "B08": .012}
add = {"B03": .006, "B04": .012, "B05": .040, "B08": .004}
lnd = {"B03": .25, "B04": .30, "B05": .31, "B08": .33}
script = os.path.join(os.path.dirname(__file__), "..", "src", "mirfa_monitor", "titan_hab_pipeline.py")


def run(with_bloom):
    d = tempfile.mkdtemp()
    r = np.random.default_rng(0)
    for k in base:
        a = np.where(land, lnd[k], base[k] + (add[k] * bloom if with_bloom else 0)) + r.normal(0, .0015, (Hh, W))
        H.write_geotiff(f"{d}/S2_{k}.tif", a.astype("float32"), x0, y1, res, epsg)
    json.dump({"source": "SYNTHETIC test", "bbox": bbox, "datetime": "2026-10-07T07:13:00Z",
               "aoi": "synthetic smoke test", "intake": [24.1393236, 53.4566472]}, open(f"{d}/meta.json", "w"))
    subprocess.run([sys.executable, script, "s2", "--dir", d, "--out", f"{d}/out"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(f"{d}/out/titan_edge_event.json"))


ev = run(True)                                    # planted bloom
assert ev["status"] == "ALERT_CANDIDATE" and ev["clusters_qualifying"] >= 1, ev["status"]
assert ev["clusters_near_intake"] >= 1
ctl = run(False)                                  # NEGATIVE CONTROL: clean water, no bloom
p99 = ctl["ndci_clean_water"]["p99"]
assert p99 == p99, "p99 must exist even in clean water"          # a top percentile always exists...
assert ctl["clusters_qualifying"] == 0 and ctl["status"] != "ALERT_CANDIDATE", ctl["status"]  # ...but is not an alert
print(f"mirfa monitor OK: planted bloom found ({ev['status']}); clean control gives {ctl['status']} "
      f"with p99={p99:.3f} < threshold 0.20 and 0 clusters")
