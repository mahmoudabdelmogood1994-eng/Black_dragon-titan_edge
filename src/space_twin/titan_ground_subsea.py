"""MOD 2  Subsea intake coherence & alarm trigger.

1. Arrival prediction: advect the satellite hotspot with the intake current
   (and subtract the satellite data latency, during which it kept moving).
2. Simulate the subsea array (turbidity + viscosity ratio) at the intake.
3. Phase-coherence monitor: a causal narrow-band phase estimate per sensor,
   delay-aligned for the known sensor geometry, mean resultant length R(t).
   Independent noise gives R ~ 0.4 (1/sqrt(6)); a coherent advected
   structure drives R toward 1.
4. On alarm, emit a 24-byte authenticated Low-Power Off-Grid Trigger.

PHYSICAL PREMISE (ASSUMED, NOT VALIDATED): a bloom's leading edge carries
filament-scale patchiness that reaches the intake hours before the main front
and appears coherently, with fixed lags, across the sensors. The simulator
injects such a precursor; whether real intakes show one must be established
with real intake data. The simple turbidity-threshold alarm is simulated next
to it so the lead time is reported against a baseline, not in isolation.
Turbidity/viscosity responses are assumed demo relations, not calibrations.
"""
from __future__ import annotations
import hashlib, hmac, math, struct
from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
from scipy.signal import lfilter
from config import Config
from geo import to_enu, to_latlon
from satellite_analytics import Hotspot

DT = 60.0                                  # sensor sample period [s]
KEY = b"titan-space-demo-key-NOT-FOR-PRODUCTION"
_FMT = "<BBHHBBffHBB"                      # 20 B body + 4 B tag = 24 B


@dataclass
class Arrival:
    eta_from_detection_s: float            # inf if the current carries it away
    closing_ms: float
    edge_dist_m: float
    chl_proxy: float                       # 0..1 from the hotspot index
    peak_turbidity_ntu: float
    peak_viscosity_ratio: float
    drift_en_m: tuple


def predict_arrival(h: Hotspot, cfg: Config) -> Arrival:
    ic = np.mean(np.array(cfg.intake_xy_m), axis=0)
    e, n = to_enu(h.lat, h.lon, cfg.plant_lat, cfg.plant_lon)
    rel = ic - np.array([float(e), float(n)])           # bloom -> intake
    d = float(np.hypot(*rel))
    u = np.array(cfg.current_uv_ms)
    closing = float(np.dot(u, rel / d))
    edge = max(d - h.radius_km * 1000.0, 0.0)
    lat_s = cfg.data_latency_h * 3600.0
    eta = (edge / closing - lat_s) if closing > 0.02 else math.inf
    chl = float(np.clip((h.mean_index - cfg.ndci_threshold) / 0.30 + 0.3, 0, 1))
    peak = cfg.turbidity_baseline_ntu + 1.5 + 10.0 * chl            # ASSUMED
    visc = 1.0 + 0.8 * chl + 2.0 * chl ** 2                         # ASSUMED, nonlinear
    return Arrival(max(eta, 0.0), closing, edge, chl, peak, visc, tuple(u * lat_s))


def sensor_geometry(cfg: Config):
    xy = np.array(cfg.intake_xy_m, float)
    u = np.array(cfg.current_uv_ms)
    up = -u / np.linalg.norm(u)                        # unit vector pointing upstream
    s = xy @ up
    delay = -(s - s.mean()) / np.linalg.norm(u)        # >0: sees the pattern later
    return xy, delay


def simulate_intake(rng, cfg: Config, arr: Optional[Arrival], hours: float,
                    precursor_h: float = 4.0, precursor_amp_ntu: Optional[float] = None) -> Dict:
    """Return time axis [s], turbidity [NTU] (n,T) and viscosity ratio (n,T).
    arr=None -> noise-only record (for false-alarm statistics)."""
    xy, delay = sensor_geometry(cfg)
    n, T = len(xy), int(hours * 3600 / DT)
    t = np.arange(T) * DT
    noise = np.zeros((n, T))
    w = rng.normal(0, 0.012, (n, T))
    for k in range(1, T):                              # AR(1), ~20 min memory
        noise[:, k] = 0.95 * noise[:, k - 1] + w[:, k]
    turb = cfg.turbidity_baseline_ntu + noise
    if arr is not None and math.isfinite(arr.eta_from_detection_s):
        eta = arr.eta_from_detection_s
        periods = np.array([2700.0, 3300.0, 3900.0])
        ph = rng.uniform(0, 2 * np.pi, 3)
        amp = cfg.precursor_amp_ntu if precursor_amp_ntu is None else precursor_amp_ntu
        for i in range(n):
            tt = t - delay[i]
            ramp = 1 / (1 + np.exp(-(tt - (eta - precursor_h * 3600)) / 1800.0))
            turb[i] += ramp * amp * sum(np.sin(2 * np.pi * tt / p + f)
                                        for p, f in zip(periods, ph)) / 3
            front = 1 / (1 + np.exp(-(tt - eta) / 900.0))
            turb[i] += front * (arr.peak_turbidity_ntu - cfg.turbidity_baseline_ntu)
    exc = np.clip((turb - cfg.turbidity_baseline_ntu)
                  / max(arr.peak_turbidity_ntu - cfg.turbidity_baseline_ntu, 1e-6)
                  if arr else 0 * turb, 0, 1.5)
    chl = exc * (arr.chl_proxy if arr else 0.0)
    visc = 1.0 + 0.8 * chl + 2.0 * chl ** 2           # nonlinear, ASSUMED
    return {"t": t, "turb": turb, "visc": visc, "delay": delay}


def _ema(x, tau_s):
    a = DT / tau_s
    return lfilter([a], [1, -(1 - a)], x, axis=-1)


def coherence_monitor(turb: np.ndarray, delay: np.ndarray,
                      periods_s=(2700.0, 3300.0, 3900.0)) -> Dict:
    """Causal phase-coherence order parameter R(t), averaged over three
    narrow bands and smoothed over 3 h."""
    n, T = turb.shape
    t = np.arange(T) * DT
    xd = turb - _ema(turb, 10800.0)                       # remove slow trend
    Rs, amps = [], []
    for p in periods_s:
        w = 2 * np.pi / p
        z = lfilter([DT / 2400.0], [1, -(1 - DT / 2400.0)],
                    xd * np.exp(-1j * w * t)[None, :], axis=-1)
        ph = np.angle(z) + w * delay[:, None]             # align known lags
        Rs.append(np.abs(np.exp(1j * ph).mean(axis=0)))
        amps.append(np.abs(z).mean(axis=0))
    R = np.mean(Rs, axis=0)
    return {"R": _ema(R, 10800.0), "R_inst": R, "amp": np.mean(amps, axis=0)}


def first_persistent(x, thr, persist, t):
    run = 0
    for k, v in enumerate(x):
        run = run + 1 if v >= thr else 0
        if run >= persist:
            return float(t[k - persist + 1 + persist - 1])
    return None


def lora_airtime_s(payload, sf=9, bw=125e3, cr=1):
    ts = 2 ** sf / bw
    de = 1 if ts > 0.016 else 0
    npay = 8 + max(math.ceil((8 * payload - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (8 + 4.25 + npay) * ts


def pack_trigger(node: int, seq: int, lat: float, lon: float, eta_min: int,
                 risk_pct: float, severity: int = 3) -> bytes:
    body = struct.pack(_FMT, 0xE8, 1, node, seq, severity, 0, lat, lon,
                       min(eta_min, 65535), int(round(risk_pct)), 0)
    return body + hmac.new(KEY, body, hashlib.sha256).digest()[:4]


def unpack_trigger(raw: bytes, last_seq: int = 0) -> Dict:
    body, tag = raw[:-4], raw[-4:]
    if not hmac.compare_digest(hmac.new(KEY, body, hashlib.sha256).digest()[:4], tag):
        raise ValueError("bad HMAC")
    m, v, node, seq, sev, fl, lat, lon, eta, risk, _ = struct.unpack(_FMT, body)
    if m != 0xE8 or seq <= last_seq:
        raise ValueError("bad magic or replayed seq")
    return dict(node=node, seq=seq, severity=sev, lat=lat, lon=lon, eta_min=eta, risk=risk)


def run_ground(rng, cfg: Config, h: Hotspot, arr: Arrival,
               precursor_amp_ntu: Optional[float] = None) -> Dict:
    if not math.isfinite(arr.eta_from_detection_s):
        return {"status": "NO_THREAT_TO_INTAKE", "reason": "current carries the bloom away"}
    hours = min(arr.eta_from_detection_s / 3600 + 4.0, 60.0)
    sim = simulate_intake(rng, cfg, arr, hours, precursor_amp_ntu=precursor_amp_ntu)
    mon = coherence_monitor(sim["turb"], sim["delay"])
    t = sim["t"]
    t_alarm = first_persistent(mon["R"], cfg.plv_threshold, cfg.plv_persist_min, t)
    t_base = first_persistent(sim["turb"].mean(axis=0), cfg.turbidity_limit_ntu, 5, t)
    out = {"status": "ALARM" if t_alarm is not None else "NO_ALARM", "sim": sim, "mon": mon,
           "t_alarm_s": t_alarm, "t_threshold_alarm_s": t_base,
           "eta_s": arr.eta_from_detection_s,
           "lead_vs_threshold_s": (t_base - t_alarm) if (t_alarm is not None and t_base) else None}
    if t_alarm is not None:
        eta_left = max(arr.eta_from_detection_s - t_alarm, 0)
        raw = pack_trigger(11, 1, h.lat, h.lon, int(eta_left / 60), h.risk_pct)
        out.update(trigger=raw, airtime_s=lora_airtime_s(len(raw)), trigger_len=len(raw))
    return out


def false_alarm_rate(cfg: Config, n_runs: int = 100, hours: float = 24.0, seed: int = 900):
    fa = 0
    for k in range(n_runs):
        s = simulate_intake(np.random.default_rng(seed + k), cfg, None, hours)
        m = coherence_monitor(s["turb"], s["delay"])
        fa += first_persistent(m["R"], cfg.plv_threshold, cfg.plv_persist_min, s["t"]) is not None
    return fa, n_runs, hours
