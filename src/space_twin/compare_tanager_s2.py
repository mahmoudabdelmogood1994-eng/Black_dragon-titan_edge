#!/usr/bin/env python3
"""Compare NDCI from a Planet Tanager scene with NDCI from Sentinel-2 over the SAME area.

  python3 compare_tanager_s2.py --tanager-h5 X.h5 --tanager-json X.json --s2-dir DIR_WITH_S2_B03_B04_B05_B08 --out cmp/

Both indices use the same formula (red-edge - red)/(red-edge + red): Tanager 708/665 nm vs Sentinel-2 B5/B4.
Sentinel-2 NDCI is reprojected to the Tanager grid (mean of the finer pixels). Reports pixel counts, Pearson r,
bias (Tanager - S2) and RMSE on the pixels valid in both, and how many pixels each flags above the threshold.
Use scenes acquired on the SAME day (the script warns if the dates differ by more than 1 day); a 30 m Tanager
pixel and 20 m Sentinel-2 pixels never coincide exactly, so some scatter is expected.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import satellite_analytics as SAT
import tanager_loader as TAN
from config import Config, apply_presets


def _dt(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def compare(h5, js, s2dir, thr=0.20):
    cfg_t = apply_presets(Config(), "tanager")
    tan = TAN.load_tanager(h5, js)
    ind_t = SAT.compute_indices(tan, cfg_t)["index"]
    cfg_s = apply_presets(Config(), "sentinel2_real")
    s2 = SAT.load_scene(s2dir, "sentinel2")
    ind_s = SAT.compute_indices(s2, cfg_s)["index"]
    dst = np.full(ind_t.shape, np.nan, dtype="float32")
    reproject(source=ind_s.astype("float32"), destination=dst, src_transform=s2.transform, src_crs=s2.crs,
              dst_transform=tan.transform, dst_crs=tan.crs, resampling=Resampling.average,
              src_nodata=np.nan, dst_nodata=np.nan)
    ok = np.isfinite(ind_t) & np.isfinite(dst)
    out = {"n_common_pixels": int(ok.sum()), "tanager_scene": tan.meta.get("scene_id"),
           "tanager_datetime": tan.meta.get("datetime"), "s2_datetime": (s2.meta or {}).get("datetime")}
    if out["s2_datetime"]:
        gap = abs((_dt(out["tanager_datetime"]) - _dt(out["s2_datetime"])).total_seconds()) / 86400
        out["date_gap_days"] = round(gap, 2)
        if gap > 1:
            out["warning"] = "acquisition dates differ by more than 1 day: differences may be real change, not sensor disagreement"
    if ok.sum() < 100:
        out["verdict"] = "too few common valid pixels to compare (no overlap, clouds, or water mask)"
        return out, None
    a, b = ind_t[ok], dst[ok]
    out.update(pearson_r=float(np.corrcoef(a, b)[0, 1]), bias_tanager_minus_s2=float(np.mean(a - b)),
               rmse=float(np.sqrt(np.mean((a - b) ** 2))),
               tanager_pixels_above_thr=int((a > thr).sum()), s2_pixels_above_thr=int((b > thr).sum()),
               threshold=thr)
    return out, (a, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tanager-h5", required=True); ap.add_argument("--tanager-json", required=True)
    ap.add_argument("--s2-dir", required=True); ap.add_argument("--out", default="compare_out")
    ap.add_argument("--threshold", type=float, default=0.20)
    a = ap.parse_args()
    out, pair = compare(a.tanager_h5, a.tanager_json, a.s2_dir, a.threshold)
    os.makedirs(a.out, exist_ok=True)
    json.dump(out, open(os.path.join(a.out, "tanager_vs_s2.json"), "w"), indent=2)
    print(json.dumps(out, indent=2))
    if pair is not None:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5, 5))
        idx = np.random.default_rng(0).choice(len(pair[0]), min(20000, len(pair[0])), replace=False)
        ax.scatter(pair[1][idx], pair[0][idx], s=2, alpha=.3)
        lim = [min(pair[0].min(), pair[1].min()), max(pair[0].max(), pair[1].max())]
        ax.plot(lim, lim, "k--", lw=1); ax.set_xlabel("Sentinel-2 NDCI (B5/B4)"); ax.set_ylabel("Tanager NDCI (708/665)")
        ax.set_title(f"r = {out['pearson_r']:.2f}, bias = {out['bias_tanager_minus_s2']:+.3f}")
        fig.tight_layout(); fig.savefig(os.path.join(a.out, "tanager_vs_s2.png"), dpi=120)


if __name__ == "__main__":
    main()
