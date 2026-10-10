#!/usr/bin/env python3
"""Response-chain DRILL on the real Mirfa satellite candidates.

The satellite layer here is the Mirfa monitor (src/mirfa_monitor): its recorded
candidates from the 2026-09-27 scene (the strongest of the series) are fed into
the GROUND and AIR simulations to show what the chain would do IF that
candidate were a drifting bloom heading for the intake.

IMPORTANT: this is a scenario exercise, not a detection. The series report
says the nearest candidate recurs at a FIXED position (6 of 8 scenes), which is
more typical of a fixed feature than a drifting bloom. Scenario assumptions:
  * sea current 0.15 m/s directed from the candidate toward the intake
  * 6 subsea sensors in an assumed layout around the intake tip
  * satellite data latency 3 h, power/flight constants from config.py / source
  * mean NDCI of the cluster was not recorded, so the 0.20 threshold is used
    (lowest possible severity)
"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pipeline as P, viz
import satellite_analytics as SAT
from config import Config, apply_presets
from geo import dist_km, to_enu

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
EVENT = os.path.join(ROOT, "docs", "real_run", "mirfa", "scenes", "2026-09-27")
OUT = os.path.join(ROOT, "docs", "real_run", "mirfa", "drill")


def main():
    cfg = Config.from_json(os.path.join(ROOT, "sites", "mirfa.json"))
    ev = json.load(open(os.path.join(EVENT, "titan_edge_event.json")))
    meta = json.load(open(os.path.join(EVENT, "meta.json")))
    cfg.acquisition_utc = meta["datetime"]
    cfg.ndci_threshold = ev["parameters"]["ndci_threshold"]
    ilat, ilon = cfg.intake_latlon[0]
    hs = []
    for c in ev["qualifying_clusters"]:
        d_plant = dist_km(cfg.plant_lat, cfg.plant_lon, c["lat"], c["lon"])
        area = c["area_m2"] / 1e6
        hs.append(SAT.Hotspot(0, c["lat"], c["lon"], area, c["pixels"], math.sqrt(area / math.pi),
                              cfg.ndci_threshold, c["ndci_max"], d_plant,
                              SAT._risk(cfg.ndci_threshold, cfg.ndci_threshold, area, d_plant),
                              "NDCI (Mirfa monitor, S2 20 m)"))
    hs.sort(key=lambda h: -h.risk_pct)
    for i, h in enumerate(hs, 1):
        h.id = i
    top = hs[0]
    e, n = to_enu(ilat, ilon, top.lat, top.lon)               # candidate -> intake
    u = np.array([float(e), float(n)]) / math.hypot(float(e), float(n)) * 0.15
    cfg.current_uv_ms = (float(u[0]), float(u[1]))
    os.makedirs(OUT, exist_ok=True)
    label = "Mirfa monitor candidates, scene " + meta["datetime"][:10]
    summary = {"scenario": "drill", "intake": [ilat, ilon], "scene_datetime": meta["datetime"],
               "current_uv_ms": cfg.current_uv_ms, "candidates": [h.__dict__ for h in hs], "variants": {}}
    head = ("DRILL (scenario exercise, not a detection). Satellite candidates: real, from the Mirfa series.\n"
            "Current, sensor layout and latency are ASSUMED.\n")
    for name, prearm in (("A_wait_for_insitu_alarm", False), ("B_prearm_on_satellite_eta", True)):
        cfg.prearm = prearm
        res = P.run_pipeline(cfg, seed=7, hotspots=hs, label=label)
        text = head + f"\nVARIANT {name}\n\n" + P.timeline_text(res)
        v = {"status": res["status"]}
        if res["status"] == "OK":
            a_, arr = res["air"], res["arrival"]
            v.update(eta_h=arr.eta_from_detection_s / 3600,
                     trigger_after_detection_min=(res["t_alarm"] - res["t_det"]) / 60,
                     recommendation_after_detection_min=(res["t_cls"] - res["t_det"]) / 60,
                     margin_before_front_min=res["margin_s"] / 60 if "margin_s" in res else None,
                     in_time=bool(res.get("margin_s", -1) >= 0),
                     alarm_to_airborne_s=res["t_rx"] - res["t_alarm"] + a_["t_spin_s"],
                     flight_s=a_["t_flight_s"], path_km=a_["path_m"] / 1000, collided=a_["collided"],
                     drone_energy_wh=a_["energy_wh"])
            text += (f"\n\nOperator recommendation {abs(v['margin_before_front_min']):.0f} min "
                     f"{'BEFORE' if v['in_time'] else 'AFTER'} the modelled front; "
                     f"{v['trigger_after_detection_min']:.0f} min after satellite detection the trigger is sent.")
        print(text, "\n" + "=" * 100)
        open(os.path.join(OUT, f"drill_{name}.log"), "w").write(text + "\n")
        viz.build_map(res).save(os.path.join(OUT, f"drill_{name}_map.html"))
        fg = viz.fig_ground(res)
        if fg:
            fg.savefig(os.path.join(OUT, f"drill_{name}_subsea.png"), dpi=110)
        summary["variants"][name] = v
    json.dump(summary, open(os.path.join(OUT, "drill_results.json"), "w"), indent=2, default=float)


if __name__ == "__main__":
    main()
