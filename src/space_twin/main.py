#!/usr/bin/env python3
"""Titan-Edge space twin: run the full SPACE -> GROUND -> AIR chain.

  python3 main.py                         synthetic demo scene
  python3 main.py --data-dir /path/bands  real Sentinel-2 GeoTIFFs (B03,B04,B05,B08)
  python3 main.py --sensor landsat ...    Landsat 8/9 (no red edge: proxy index!)
  python3 main.py --preset fujairah tanager --tanager-h5 X.h5 --tanager-json X.json
  python3 main.py --bench                 + sensitivity / false-alarm / drone Monte Carlo
Outputs (./output): timeline.log, results.json, dashboard_map.html, ndci.png, subsea.png
"""
import argparse, json, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P
import titan_ground_subsea as G
import titan_air_drone as AIR
import viz
from config import Config, apply_presets


def summary(res):
    out = {"status": res["status"], "synthetic_scene": res["synthetic"],
           "index": res["ind"]["index_name"], "seed": res["seed"],
           "hotspots": [h.__dict__ for h in res["hotspots"]]}
    if res["status"] == "OK":
        g, a, arr = res["ground"], res["air"], res["arrival"]
        out.update(
            eta_h=arr.eta_from_detection_s / 3600, predicted_peak_ntu=arr.peak_turbidity_ntu,
            predicted_viscosity_ratio=arr.peak_viscosity_ratio,
            coherence_alarm_after_detection_h=g["t_alarm_s"] / 3600,
            coherence_lead_vs_threshold_min=(g["lead_vs_threshold_s"] or 0) / 60,
            trigger_bytes=g["trigger_len"], trigger_airtime_ms=g["airtime_s"] * 1e3,
            alarm_to_drone_rx_ms=(res["t_rx"] - res["t_alarm"]) * 1e3,
            alarm_to_airborne_s=res["t_rx"] - res["t_alarm"] + a["t_spin_s"],
            flight_s=a["t_flight_s"], path_km=a["path_m"] / 1000,
            min_clearance_m=a["min_clearance_m"], collided=a["collided"],
            scan_s=a["t_scan_s"], class_label=a["class_label"],
            class_confidence=a["class_confidence"], bloom_confirmed=a["bloom_confirmed"],
            protection_recommendation=a["protection_recommendation"],
            alarm_to_recommendation_min=(res["t_cls"] - res["t_alarm"]) / 60,
            margin_before_front_min=res.get("margin_s", float("nan")) / 60,
            drone_energy_wh=a["energy_wh"])
    return out


def bench(cfg, res, log):
    h, arr = res["target"], res["arrival"]
    log("\n--- Sensitivity: coherence alarm vs assumed precursor amplitude (10 seeds each) ---")
    log(f"{'precursor NTU':>14} {'alarm rate':>11} {'median lead vs threshold':>26}")
    rows = []
    for amp in (0.0, 0.05, 0.10, 0.15, 0.20, 0.40):
        leads, det = [], 0
        for sd in range(10):
            r = G.run_ground(np.random.default_rng(sd), cfg, h, arr, precursor_amp_ntu=amp)
            if r["t_alarm_s"] is not None:
                det += 1
                if r["t_threshold_alarm_s"]:
                    leads.append((r["t_threshold_alarm_s"] - r["t_alarm_s"]) / 60)
        med = float(np.median(leads)) if leads else float("nan")
        rows.append({"precursor_ntu": amp, "alarm_rate": det / 10, "median_lead_min": med})
        log(f"{amp:>14.2f} {det/10:>10.0%} {med:>22.0f} min")
    fa, n, hrs = G.false_alarm_rate(cfg, 100)
    log(f"\n--- False alarms: {fa} in {n} noise-only {hrs:.0f} h records (6 sensors) ---")
    log("\n--- Drone Monte Carlo: 30 flights, 6 moving obstacles on collision courses ---")
    ok = col = 0
    clear = []
    for k in range(30):
        a = AIR.run_air(np.random.default_rng(100 + k), cfg, {}, np.array([3000.0, 1200.0]),
                        next(iter(AIR.BLOOM_CLASSES)), 0)
        ok += 1; col += a["collided"]; clear.append(a["min_clearance_m"])
    log(f"arrived {ok}/30, collisions {col}/30, median min clearance {np.median(clear):.1f} m")
    return {"sensitivity": rows, "false_alarms": {"events": fa, "runs": n, "hours": hrs},
            "drone_mc": {"flights": 30, "collisions": col}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--sensor", default="sentinel2", choices=["sentinel2", "landsat"])
    ap.add_argument("--tanager-h5", default=None, help="Tanager surface-reflectance HDF5")
    ap.add_argument("--tanager-json", default=None, help="its STAC item JSON")
    ap.add_argument("--preset", nargs="*", default=[],
                    help="fujairah | sentinel2_real | tanager (notebook values, uncalibrated)")
    ap.add_argument("--site", default=None, help="site.json with the real plant/intake/current values")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    args = ap.parse_args()
    cfg = apply_presets(Config(sensor=args.sensor), *args.preset)
    if args.site:
        cfg = Config.from_json(args.site, cfg)
    tan = (args.tanager_h5, args.tanager_json) if args.tanager_h5 else None
    if tan and not args.tanager_json:
        ap.error("--tanager-h5 needs --tanager-json")
    if args.threshold is not None:
        cfg.ndci_threshold = args.threshold
    os.makedirs(args.out, exist_ok=True)
    lines = []

    def log(s=""):
        print(s); lines.append(s)

    res = P.run_pipeline(cfg, args.data_dir, args.seed, tan)
    log("TITAN-EDGE SPACE TWIN  --  timeline (simulated clock; "
        + ("SYNTHETIC scene" if res["synthetic"] else "real scene") + ")")
    log(P.timeline_text(res))
    if res["status"] == "OK":
        s = summary(res)
        log(f"\nSATELLITE -> OPERATOR RECOMMENDATION: {P.fmt(res['t_cls'])} after acquisition "
            f"(of which {cfg.data_latency_h:.1f} h is the ASSUMED data latency)")
        log(f"COHERENCE ALARM -> DRONE AIRBORNE: {s['alarm_to_airborne_s']:.1f} s ; "
            f"-> RECOMMENDATION: {s['alarm_to_recommendation_min']:.1f} min ; "
            f"margin before modelled front: {s['margin_before_front_min']:.0f} min")
    else:
        s = summary(res)
        log(f"\nstatus: {res['status']}")
    if args.bench and res["status"] == "OK":
        s["benchmark"] = bench(cfg, res, log)
    with open(os.path.join(args.out, "timeline.log"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump(s, f, indent=2, default=float)
    viz.build_map(res).save(os.path.join(args.out, "dashboard_map.html"))
    viz.fig_satellite(res).savefig(os.path.join(args.out, "ndci.png"), dpi=110)
    fg = viz.fig_ground(res)
    if fg:
        fg.savefig(os.path.join(args.out, "subsea.png"), dpi=110)
    log(f"\nwrote {args.out}/ (timeline.log, results.json, dashboard_map.html, ndci.png, subsea.png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
