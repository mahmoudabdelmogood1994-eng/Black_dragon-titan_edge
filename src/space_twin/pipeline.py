"""End-to-end orchestration:  SPACE (satellite) -> GROUND (subsea) -> AIR (UAV)
-> PLANT (intake-protection recommendation to the operator), with a simulated-clock timeline log."""
from __future__ import annotations
import math, os, tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import numpy as np
import synthetic
import tanager_loader as TAN
import satellite_analytics as SAT
import titan_ground_subsea as GND
import titan_air_drone as AIR
from config import Config
from geo import to_enu, to_latlon

HERE = os.path.dirname(os.path.abspath(__file__))
SYNTH_DIR = os.path.join(HERE, "data", "synthetic_scene")


def rel(dt_s: float) -> str:
    """'12:03 before' / '09:25 AFTER' (positive = before the modelled front)."""
    return f"{fmt(abs(dt_s))} " + ("before" if dt_s >= 0 else "AFTER")


def fmt(dt_s: float) -> str:
    s = int(round(abs(dt_s)))
    return f"{'-' if dt_s < 0 else ''}{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _parse_utc(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def run_pipeline(cfg: Config, data_dir: Optional[str] = None, seed: int = 7,
                 tanager: Optional[tuple] = None, hotspots=None,
                 label: str = "external satellite candidate") -> Dict:
    """tanager = (hdf5_path, stac_item_json) -> hyperspectral scene instead of band folder.
    hotspots = list of satellite_analytics.Hotspot from another detector (e.g. the Mirfa
    monitor): the space layer is skipped and only the response chain is simulated."""
    rng = np.random.default_rng(seed)
    AIR.reset_library()
    if hotspots is not None:
        sc, ind, t_compute = None, {"index_name": label, "index": None, "water": None}, 0.0
    elif tanager:
        sc = TAN.load_tanager(*tanager)
        sc, ind, hotspots, t_compute = SAT.analyse_scene(sc, cfg)
        data_dir = os.path.dirname(os.path.abspath(tanager[0]))
    elif hotspots is None:
        if data_dir is None:
            data_dir = synthetic.make_scene(SYNTH_DIR, cfg)
        sc, ind, hotspots, t_compute = SAT.analyse(data_dir, cfg)
    if sc is not None and sc.meta and sc.meta.get("datetime"):
        cfg.acquisition_utc = sc.meta["datetime"]
    t_acq = _parse_utc(cfg.acquisition_utc)
    true_class = "Dinoflagellate (red-tide type)"
    ref_note = ""
    if tanager:
        wl, clean, susp = TAN.reference_spectra(sc, ind["index"])
        if AIR.set_reference_spectra(wl, clean, susp):
            true_class = AIR.REAL_BLOOM
            ref_note = " Reference spectra: real Tanager clean-vs-suspect (bloom vs clean only, no species)."
    events: List[Dict] = []

    def ev(t_s: float, layer: str, msg: str):
        events.append({"t_s": t_s, "utc": (t_acq + timedelta(seconds=t_s)).strftime("%H:%M:%S"),
                       "layer": layer, "event": msg})

    lat_s = cfg.data_latency_h * 3600.0
    ev(0.0, "SPACE", f"Satellite acquisition ({cfg.sensor}"
       + (f", {sc.meta['scene_id']}" if sc is not None and sc.meta and sc.meta.get('scene_id') else "")
       + ("); " + label + " (satellite layer supplied externally)." if sc is None else
          f"); scene is {'SYNTHETIC' if sc.synthetic else 'REAL data (historical replay)'}.{ref_note}"))
    ev(lat_s, "SPACE", f"Product available (ASSUMED latency {cfg.data_latency_h:.1f} h)")
    t_det = lat_s + t_compute
    top = hotspots[0] if hotspots else None
    ev(t_det, "SPACE", f"{ind['index_name']} analysis done in {t_compute*1e3:.0f} ms: "
       f"{len(hotspots)} hotspot(s)" + (f"; top risk {top.risk_pct:.0f} % at "
       f"({top.lat:.4f}, {top.lon:.4f}), {top.area_km2:.3g} km2" if top else ""))
    res: Dict = {"cfg": cfg, "scene": sc, "ind": ind, "hotspots": hotspots, "events": events,
                 "data_dir": data_dir, "synthetic": bool(sc.synthetic) if sc is not None else False, "seed": seed,
                 "compute_s": t_compute, "t_acq": t_acq}
    # pick the highest-risk hotspot that the current actually carries to the intake
    arrivals = {h.id: GND.predict_arrival(h, cfg) for h in hotspots}
    threats = [h for h in hotspots if math.isfinite(arrivals[h.id].eta_from_detection_s)
               and h.dist_to_plant_km <= cfg.max_range_km]
    res["arrivals"] = arrivals
    if not threats:
        near = min((h.dist_to_plant_km for h in hotspots), default=None)
        why = ("no hotspots above threshold" if not hotspots else
               f"nearest hotspot is {near:.0f} km from the intake (limit {cfg.max_range_km:.0f} km) "
               "or the current carries it away")
        ev(t_det, "SPACE", f"No hotspot threatens the intake: {why}. Watch only")
        res["status"] = "NO_THREAT"
        return res
    h = threats[0]
    arr = arrivals[h.id]
    res.update(target=h, arrival=arr)
    ev(t_det, "SPACE>GROUND", f"Threat message: hotspot #{h.id}, bloom edge {arr.edge_dist_m/1000:.1f} km "
       f"from intake, closing {arr.closing_ms*100:.0f} cm/s, ETA +{fmt(arr.eta_from_detection_s)} after detection; "
       f"predicted peak {arr.peak_turbidity_ntu:.1f} NTU, viscosity x{arr.peak_viscosity_ratio:.2f}")
    g = GND.run_ground(rng, cfg, h, arr)
    res["ground"] = g
    t_front = t_det + arr.eta_from_detection_s
    prearm = bool(cfg.prearm and arr.eta_from_detection_s <= cfg.prearm_eta_h * 3600)
    if g["status"] != "ALARM" and not prearm:
        ev(t_det, "GROUND", "Phase-coherence monitor never alarmed")
        res["status"] = "NO_ALARM"
        return res
    if g["status"] == "ALARM":
        ev(t_det + g["t_alarm_s"], "GROUND", f"Phase-coherence ALARM (R >= {cfg.plv_threshold}, "
           f"{cfg.plv_persist_min} min); {rel(t_front - (t_det + g['t_alarm_s']))} the modelled front arrival")
    else:
        ev(t_det + g.get("t_threshold_alarm_s", 0) if g.get("t_threshold_alarm_s") else t_front,
           "GROUND", "Phase-coherence monitor had not alarmed by the end of the record")
    if g.get("t_threshold_alarm_s") is not None:
        extra = (f"; coherence lead = {g['lead_vs_threshold_s']/60:+.0f} min"
                 if g.get("lead_vs_threshold_s") is not None else "")
        ev(t_det + g["t_threshold_alarm_s"], "GROUND",
           f"(baseline) simple turbidity > {cfg.turbidity_limit_ntu} NTU alarm would fire here{extra}")
    if prearm:                                   # launch on the satellite ETA, not on the in-situ alarm
        t_alarm = t_det
        raw = GND.pack_trigger(11, 1, h.lat, h.lon, int(arr.eta_from_detection_s / 60), h.risk_pct)
        ev(t_det, "SPACE>GROUND", f"PRE-ARM: satellite ETA {arr.eta_from_detection_s/3600:.1f} h <= "
           f"{cfg.prearm_eta_h:.0f} h, trigger sent now instead of waiting for the in-situ alarm")
    else:
        t_alarm = t_det + g["t_alarm_s"]
        raw = g["trigger"]
    air_t = GND.lora_airtime_s(len(raw))
    tlen = len(raw)
    # --- low-power trigger: 3 blind repeats, 5 % loss each (ASSUMED) -----------
    got = next((k for k in range(3) if rng.random() > 0.05), None)
    if got is None:
        ev(t_alarm + 3 * air_t, "GROUND", "TriggerSignal lost on all repeats")
        res["status"] = "TRIGGER_LOST"
        return res
    t_rx = t_alarm + 0.002 + (got + 1) * air_t + got * 0.05
    ev(t_alarm + 0.002, "GROUND>AIR",
       f"Low-power off-grid trigger sent: {tlen} B, airtime {air_t*1e3:.0f} ms, 3 repeats")
    trig = GND.unpack_trigger(raw)
    ev(t_rx, "AIR", f"Trigger received (copy {got+1}), HMAC ok, target ({trig['lat']:.4f}, {trig['lon']:.4f}), "
       f"risk {trig['risk']} %")
    # --- where is the bloom NOW? satellite position advected by the current ---
    e0, n0 = to_enu(h.lat, h.lon, cfg.plant_lat, cfg.plant_lon)
    u = np.array(cfg.current_uv_ms)
    bloom_now = np.array([float(e0), float(n0)]) + u * (t_rx)
    a = AIR.run_air(rng, cfg, trig, bloom_now, true_class, t_rx)
    res["air"] = a
    t_air = t_rx + a["t_spin_s"]
    ev(t_air, "AIR", f"Airborne (ASSUMED spin-up {a['t_spin_s']:.0f} s)")
    ev(t_air + a["t_flight_s"], "AIR", f"Arrived over bloom: {a['path_m']/1000:.2f} km flown, min clearance "
       f"{a['min_clearance_m']:.1f} m, collided={a['collided']}")
    t_cls = t_rx + a["t_classified_s"]
    ev(t_cls, "AIR", f"Hyper-spectral rescan done ({a['t_scan_s']:.0f} s): {a['class_label']}, "
       f""
       f"{'bloom/clean separation' if AIR.REAL_BLOOM in AIR.LIBRARY else 'species confidence'} "
       f"{a['class_confidence']:.2f} ({'ok' if a['species_confident'] else 'LOW'}), "
       f"bloom confirmed={a['bloom_confirmed']}")
    if a["protection_recommendation"]:
        ev(t_cls + 0.05, "PLANT", "RECOMMENDATION to operator: consider intake protection "
           "(advisory; needs subsea-sensor confirmation and operator approval, execution not modelled) - "
           f"{rel(t_front - t_cls)} the modelled front arrival"
           + ("" if t_front >= t_cls else ": TOO LATE, would need satellite-ETA pre-arming"))
        res["margin_s"] = t_front - t_cls
    else:
        ev(t_cls, "PLANT", "No recommendation (bloom not confirmed by the rescan, or recommendations disabled)")
    ev(t_front, "GROUND", "Modelled bloom front reaches the intake (reference)")
    events.sort(key=lambda e: e["t_s"])
    res.update(status="OK", t_det=t_det, t_alarm=t_alarm, t_rx=t_rx, t_front=t_front,
               t_cls=t_cls, bloom_now=bloom_now)
    return res


def timeline_text(res: Dict) -> str:
    out = [f"{'sim UTC':>9} {'T+acq':>9} {'delta':>9}  {'layer':<13} event", "-" * 110]
    prev = None
    for e in res["events"]:
        d = "" if prev is None else "+" + fmt(e["t_s"] - prev) if e["t_s"] - prev >= 1 \
            else f"+{(e['t_s']-prev)*1e3:.0f}ms"
        out.append(f"{e['utc']:>9} {fmt(e['t_s']):>9} {d:>9}  {e['layer']:<13} {e['event']}")
        prev = e["t_s"]
    return "\n".join(out)
