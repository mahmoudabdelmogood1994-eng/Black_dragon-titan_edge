"""MOD 3  Autonomous trajectory + hyper-spectral rescan (Falcon Eye).

Reuses the avian-inspired reactive kernel from ../titan_edge_core_sim.py
(goal pursuit + looming/CPA avoidance + reflex). The drone flies to where the
bloom is NOW (satellite position advected by the current), runs a lawn-mower
micro-rescan and classifies the bloom by Spectral Angle Mapper against a
reference library.

HONESTY NOTES
* The spectral library below is ILLUSTRATIVE (pigment-feature shapes), and the
  "measured" spectra are generated from the same library plus noise. Accuracy
  here therefore says nothing about real-world classification; replace the
  library with measured field spectra and validate before relying on it.
* Obstacles (vessels, birds) are random and placed on collision courses.
* The output is an INTAKE-PROTECTION RECOMMENDATION to the operator, never an automatic
  action: it must be confirmed by the subsea sensors and approved by the operator. A real plant also needs an
  independent interlock, operator acknowledgement and a fail-safe design.
"""
from __future__ import annotations
import math, os, sys
from dataclasses import dataclass
from typing import Dict, List
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import titan_edge_core_sim as T          # AvianKernel, Obstacle, build_world, A
from config import Config
from geo import to_enu, to_latlon

WL = np.arange(450, 801, 5.0)            # nm


def _g(c, w, d):
    return d * np.exp(-0.5 * ((WL - c) / w) ** 2)


def _base():
    return 0.020 + 0.012 * np.exp(-(WL - 450) / 120.0)


def _algal(trough_nm, trough_w, trough_d, extra=0.0):
    s = _base() + _g(560, 40, 0.006) - _g(675, 12, 0.008) + _g(705, 15, 0.018)
    s = s - _g(trough_nm, trough_w, trough_d)
    return np.clip(s, 0.002, None)


LIBRARY: Dict[str, np.ndarray] = {
    "Clear water (no bloom)": _base() * np.exp(-(WL - 450) / 260.0),
    "Dinoflagellate (red-tide type)": _algal(525, 22, 0.012),
    "Cyanobacteria": np.clip(_algal(620, 14, 0.010) + _g(650, 10, 0.004), 0.002, None),
    "Diatom": _algal(540, 35, 0.005),
}
BLOOM_CLASSES = [k for k in LIBRARY if not k.startswith("Clear")]
_DEFAULT = (dict(LIBRARY), list(BLOOM_CLASSES))
REAL_BLOOM = "Suspect patch (top 1 % NDCI, Tanager scene)"
REAL_CLEAN = "Clear water (Tanager scene median-or-lower NDCI)"


def reset_library():
    global LIBRARY, BLOOM_CLASSES
    LIBRARY, BLOOM_CLASSES = dict(_DEFAULT[0]), list(_DEFAULT[1])


def set_reference_spectra(wl_nm, clean, suspect) -> bool:
    """Replace the illustrative library by two REAL spectra measured in a
    Tanager scene (clean water vs top-1 % NDCI patch), resampled to WL.
    Only bloom-vs-clean can then be separated, not species."""
    global LIBRARY, BLOOM_CLASSES
    out = []
    for s in (clean, suspect):
        ok = np.isfinite(s)
        if ok.sum() < 10:
            return False
        out.append(np.clip(np.interp(WL, wl_nm[ok], s[ok]), 1e-4, None))
    LIBRARY = {REAL_CLEAN: out[0], REAL_BLOOM: out[1]}
    BLOOM_CLASSES = [REAL_BLOOM]
    return True


def sam_angle(a: np.ndarray, b: np.ndarray) -> float:
    return float(math.acos(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1)))


def classify(spec: np.ndarray) -> Dict:
    ang = {k: sam_angle(spec, v) for k, v in LIBRARY.items()}
    order = sorted(ang, key=ang.get)
    best, second = order[0], order[1]
    conf = float(np.clip(1 - ang[best] / max(ang[second], 1e-9), 0, 1))
    return {"label": best, "confidence": conf, "angles_rad": ang}


def lawnmower(aoi: float, swath: float):
    lanes = int(math.ceil(aoi / (swath * 0.85)))
    ys = np.linspace(-aoi / 2 + swath / 2, aoi / 2 - swath / 2, lanes)
    pts = []
    for k, y in enumerate(ys):
        xs = np.linspace(-aoi / 2, aoi / 2, 41)
        pts.append(np.stack([xs if k % 2 == 0 else xs[::-1], np.full(41, y)], 1))
    return np.concatenate(pts)


def run_air(rng, cfg: Config, trigger: Dict, bloom_xy_m: np.ndarray, true_class: str,
            t_launch_s: float) -> Dict:
    """Fly plant -> bloom, rescan, classify, decide. Times are seconds since
    the trigger was received. bloom_xy_m: bloom centre NOW (east, north) m."""
    a = T.A
    base = np.zeros(2)
    obs = T.build_world(rng, base, bloom_xy_m, n_dyn=6, n_static=0)
    kern = T.AvianKernel(a)
    pos, vel, t = base.copy(), np.zeros(2), 0.0
    path = [(0.0, pos[0], pos[1])]
    min_clear, collided, path_len = float("inf"), False, 0.0
    spin = a.uav_spinup_s
    while np.linalg.norm(bloom_xy_m - pos) > a.arrive_radius_m and t < 3600:
        v_cmd = kern.command(pos, vel, bloom_xy_m, obs, t)
        dv = v_cmd - vel
        n = np.linalg.norm(dv)
        if n > a.uav_amax * a.dt_uav:
            dv *= a.uav_amax * a.dt_uav / n
        vel = vel + dv
        step = vel * a.dt_uav
        pos = pos + step
        path_len += float(np.linalg.norm(step))
        t += a.dt_uav
        for o in obs:
            o.pos = o.pos + o.vel * a.dt_uav
            gap = float(np.linalg.norm(o.pos - pos)) - o.r - a.uav_radius_m
            min_clear = min(min_clear, gap)
            collided = collided or gap < 0
        if int(round(t / a.dt_uav)) % 50 == 0:                 # log every 5 s
            path.append((t, pos[0], pos[1]))
    t_arrive = t
    path.append((t, pos[0], pos[1]))
    # --- hyper-spectral micro-rescan ---------------------------------------
    route = lawnmower(cfg.scan_aoi_m, cfg.scan_swath_m)
    seg = np.linalg.norm(np.diff(route, axis=0), axis=1)
    t_scan = float(seg.sum() / cfg.scan_speed_ms)
    for k in range(0, len(route), 8):                          # waypoint trail
        tt = t_arrive + float(seg[:k].sum() / cfg.scan_speed_ms)
        path.append((tt, bloom_xy_m[0] + route[k, 0], bloom_xy_m[1] + route[k, 1]))
    n_samples = 12
    votes = []
    truth = LIBRARY[true_class]
    for _ in range(n_samples):
        meas = truth * rng.uniform(0.9, 1.1) + rng.normal(0, 0.0015, truth.shape)
        votes.append(classify(np.clip(meas, 1e-4, None)))
    labels = [v["label"] for v in votes]
    label = max(set(labels), key=labels.count)
    conf = float(np.mean([v["confidence"] for v in votes if v["label"] == label]))
    frac = labels.count(label) / n_samples
    t_class = t_arrive + t_scan + 0.5
    # Bloom presence (algal vs clear water) drives the intake decision: any dense
    # bloom can foul an RO intake. Species confidence only selects the response.
    confirmed = (label in BLOOM_CLASSES) and frac >= 0.6
    species_ok = conf >= cfg.sam_min_confidence
    e_wh = (a.p_cruise_w * t_arrive + (a.p_scan_w + a.p_edge_ai_w) * t_scan) / 3600
    return {"path": path, "t_spin_s": spin, "t_flight_s": t_arrive, "path_m": path_len,
            "straight_m": float(np.linalg.norm(bloom_xy_m)), "min_clearance_m": min_clear,
            "collided": collided, "reflex_steps": kern.reflex_events,
            "t_scan_s": t_scan, "t_classified_s": spin + t_class,
            "class_label": label, "class_confidence": conf, "vote_fraction": frac,
            "bloom_confirmed": bool(confirmed), "species_confident": bool(species_ok), "energy_wh": e_wh,
            "protection_recommendation": bool(confirmed and cfg.recommend_protection)}
