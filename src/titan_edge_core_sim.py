#!/usr/bin/env python3
"""
Titan-Edge Digital Twin  --  integrated 3-layer simulator
==========================================================

    Sensor Node array  -->  Edge Control Unit  -->  Autonomous UAV
    (AquaGuardian)          (Green Box)             (Falcon Eye)

    MOD 1  Sub-surface sensing kernel : 31-sensor array, phase-coherence
           localisation of an anomalous impulse  ->  (chainage_m, t0)
    MOD 2  Power & edge scheduler     : FSM  DEEP_SLEEP -> ANOMALY_DETECTED
           -> HIGH_POWER_TRANSMIT -> DEEP_SLEEP, authenticated 22-byte
           low-power TriggerSignal over a LoRa-class link
    MOD 3  Trajectory & obstacle avoid: avian-inspired (looming / tau)
           decision kernel, dynamic obstacles, arrival + area-scan

WHAT THIS IS (and is not)
-------------------------
A software digital twin. Physics for MOD 1 is an idealised 1-D buried pipe
(homogeneous, mildly dispersive, with sound-speed / position / clock error
injected). All electrical and flight-power constants live in `Assumptions`
and are engineering placeholders, NOT measurements. Wall-clock compute
time is measured on the host CPU, not on a Cortex-M. No number produced
here is a field result.

Run:   python3 titan_edge_core_sim.py            (full benchmark, ~1-2 min)
       python3 titan_edge_core_sim.py --quick    (smaller Monte Carlo)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import butter, hilbert, iirnotch, sosfilt, tf2sos


# =============================================================================
# 0. Parameters  (every tunable / assumed constant is here, nowhere else)
# =============================================================================
@dataclass(frozen=True)
class Assumptions:
    # --- MOD 1: pipe & array ---------------------------------------------
    pipe_length_m: float = 3000.0
    n_sensors: int = 31
    c_nominal: float = 1200.0        # m/s  wave speed the localiser assumes
    c_error_sigma: float = 0.01      # 1 % true-vs-assumed speed error
    dispersion: float = 0.02         # relative speed change across the band
    atten_per_m: float = 8e-4        # 1/m amplitude attenuation
    pos_jitter_m: float = 0.5        # sensor survey error (1 sigma)
    sync_sigma_s: float = 1e-4       # inter-sensor clock error (1 sigma)
    fs_hz: float = 2000.0
    record_s: float = 8.0
    event_time_s: float = 2.5        # physical event time inside the record
    pulse_fc_hz: float = 60.0
    pulse_tau_s: float = 0.012
    band_hz: Tuple[float, float] = (20.0, 150.0)
    hum_amp: float = 1.5             # local 50 Hz pump hum, random phase/sensor
    mains_hz: float = 50.0           # notch removes stationary pump/mains hum
    sta_s: float = 0.03
    lta_s: float = 1.0
    sta_lta_thr: float = 6.0
    gather_window_s: float = 0.6     # edge waits this long for neighbours
    pulse_margin_s: float = 0.2      # + this for the pulse to finish
    min_sensors: int = 3
    max_sensors: int = 9             # cap -> bounded edge compute
    # --- MOD 2: electrical (ASSUMED, datasheet-class values) -------------
    v_supply: float = 3.3
    i_deep_sleep_a: float = 18e-6    # MCU stop-mode + RTC + wake comparator
    i_active_a: float = 25e-3        # MCU run + DSP
    i_tx_a: float = 120e-3           # +20 dBm LoRa-class radio
    i_sense_a: float = 8e-3          # one awake sensor front-end
    wake_latency_s: float = 2e-3
    link_latency_s: float = 10e-3    # sensor -> edge backhaul
    lora_sf: int = 9
    lora_bw_hz: float = 125e3
    tx_repeats: int = 3              # blind repeats for reliability
    tx_spacing_s: float = 0.05
    packet_loss: float = 0.05        # per-packet, independent
    battery_wh: float = 68.4         # 3.6 V x 19 Ah primary cell
    battery_usable: float = 0.70
    self_discharge_per_yr: float = 0.01   # primary-cell self discharge
    cell_shelf_life_yr: float = 15.0      # chemistry limit, caps the estimate
    heartbeat_period_s: float = 3600.0
    heartbeat_active_s: float = 0.2
    heartbeat_tx_s: float = 0.15
    events_per_year: float = 24.0
    # --- MOD 3: UAV (ASSUMED) --------------------------------------------
    uav_vmax: float = 18.0           # m/s
    uav_amax: float = 6.0            # m/s^2
    uav_radius_m: float = 1.5
    uav_spinup_s: float = 4.0        # arm + self-test + take-off
    uav_verify_s: float = 0.02       # HMAC + seq check
    p_cruise_w: float = 120.0
    p_scan_w: float = 100.0
    p_edge_ai_w: float = 5.0         # accelerator running during scan
    scan_speed: float = 8.0
    scan_swath_m: float = 30.0
    scan_aoi_m: float = 100.0
    dt_uav: float = 0.1
    avoid_horizon_s: float = 10.0
    avoid_margin_m: float = 18.0
    reflex_tau_s: float = 1.5
    arrive_radius_m: float = 10.0


A = Assumptions()


# =============================================================================
# 1. MOD 1  --  Sub-surface sensing kernel (AquaGuardian)
# =============================================================================
class SubSurfaceArray:
    """31-sensor buried array. Generates synthetic records for a source at
    chainage `xs` using frequency-domain propagation with attenuation,
    mild dispersion, and injected survey / clock / sound-speed errors."""

    def __init__(self, rng: np.random.Generator, a: Assumptions = A):
        self.a = a
        self.x_nom = np.linspace(0.0, a.pipe_length_m, a.n_sensors)
        self.x_true = self.x_nom + rng.normal(0, a.pos_jitter_m, a.n_sensors)
        self.sync_err = rng.normal(0, a.sync_sigma_s, a.n_sensors)
        self.c_true = a.c_nominal * (1.0 + rng.normal(0, a.c_error_sigma))
        self.hum_phase = rng.uniform(0, 2 * np.pi, a.n_sensors)

    def simulate(self, xs: Optional[float], snr_db: float,
                 rng: np.random.Generator) -> np.ndarray:
        """Return (n_sensors, n_samples). xs=None -> noise-only record."""
        a = self.a
        n = int(a.fs_hz * a.record_s)
        t = np.arange(n) / a.fs_hz
        sig = rng.normal(0.0, 1.0, (a.n_sensors, n))                 # white noise
        sig += a.hum_amp * np.sin(2 * np.pi * 50.0 * t[None, :]
                                  + self.hum_phase[:, None])         # local hum
        if xs is None:
            return sig
        f = np.fft.rfftfreq(n, 1.0 / a.fs_hz)
        tt = t - a.event_time_s
        pulse = (np.exp(-(tt / a.pulse_tau_s) ** 2)
                 * np.cos(2 * np.pi * a.pulse_fc_hz * tt))
        S = np.fft.rfft(pulse)
        d = np.abs(self.x_true - xs)[:, None]
        c_f = self.c_true * (1.0 + a.dispersion * (f - a.pulse_fc_hz) / a.pulse_fc_hz)
        c_f = np.clip(c_f, 0.5 * self.c_true, None)[None, :]
        H = (np.exp(-2j * np.pi * f[None, :] * (d / c_f + self.sync_err[:, None]))
             * np.exp(-a.atten_per_m * d))
        amp = 10 ** (snr_db / 20.0) / np.exp(-a.atten_per_m * 100.0)  # SNR @100 m
        sig += amp * np.fft.irfft(S[None, :] * H, n, axis=1)
        return sig


def mains_notch(sig: np.ndarray, a: Assumptions = A) -> np.ndarray:
    """Causal notch at the mains/pump frequency. The same filter is applied
    to every sensor, so it adds an identical phase to all channels and does
    not disturb the cross-sensor phase-coherence metric."""
    b, aa = iirnotch(a.mains_hz, Q=15.0, fs=a.fs_hz)
    return sosfilt(tf2sos(b, aa), sig, axis=1)


def sta_lta_detect(sig: np.ndarray, a: Assumptions = A) -> np.ndarray:
    """Causal band-pass + STA/LTA on a (notched) record. Returns per-sensor
    first-trigger time in seconds (np.inf when a sensor never triggers)."""
    sos = butter(4, a.band_hz, btype="band", fs=a.fs_hz, output="sos")
    e = sosfilt(sos, sig, axis=1) ** 2
    c = np.concatenate([np.zeros((sig.shape[0], 1)), np.cumsum(e, axis=1)], axis=1)
    ns, nl = int(a.sta_s * a.fs_hz), int(a.lta_s * a.fs_hz)
    k = np.arange(ns + nl, sig.shape[1])                    # warm-up skipped
    sta = (c[:, k + 1] - c[:, k + 1 - ns]) / ns
    lta = (c[:, k + 1 - ns] - c[:, k + 1 - ns - nl]) / nl
    hit = (sta / (lta + 1e-12)) > a.sta_lta_thr
    out = np.full(sig.shape[0], np.inf)
    anyhit = hit.any(axis=1)
    out[anyhit] = k[hit.argmax(axis=1)[anyhit]] / a.fs_hz
    return out


@dataclass
class DetectionReport:
    chainage_m: float
    t0_s: float                 # estimated event origin (record time)
    delta_t_s: float            # first-trigger time minus estimated origin
    confidence: float
    n_sensors_used: int
    t_first_trigger_s: float
    t_data_ready_s: float       # when the gather window closes (record time)
    compute_s: float            # host wall-clock for localisation


def phase_coherence_localize(sig: np.ndarray, x_nom: np.ndarray, sel: np.ndarray,
                             t_cut_s: float, a: Assumptions = A
                             ) -> Tuple[float, float, float]:
    """Phase-coherence localisation.

    For a candidate source position x, undo each sensor's propagation phase
    (2*pi*f*|x_i - x|/c). If x is the true source, the residual phases agree
    across sensors at every frequency (up to a common, unknown origin time),
    so the mean resultant length of the unit phasors is ~1. Amplitudes are
    discarded (phase-only), which makes the metric insensitive to
    attenuation. Frequencies are weighted by in-band signal energy.
    Returns (chainage_m, t0_s, confidence)."""
    n = sig.shape[1]
    seg = sig[sel].copy()
    seg[:, int(t_cut_s * a.fs_hz):] = 0.0                  # no look-ahead
    X = np.fft.rfft(seg, axis=1)
    f = np.fft.rfftfreq(n, 1.0 / a.fs_hz)
    m = (f >= a.band_hz[0]) & (f <= a.band_hz[1])
    fb, Xb = f[m], X[:, m]
    U = Xb / (np.abs(Xb) + 1e-12)
    w = np.abs(Xb).mean(axis=0)
    w /= w.sum()
    xi = x_nom[sel]

    def score(cands: np.ndarray) -> np.ndarray:
        out = np.empty(len(cands))
        for s in range(0, len(cands), 128):                # chunk -> bounded RAM
            cc = cands[s:s + 128]
            d = np.abs(cc[:, None] - xi[None, :])
            ph = np.exp(2j * np.pi * d[:, :, None] / a.c_nominal * fb[None, None, :])
            out[s:s + 128] = np.abs((ph * U[None]).mean(axis=1)) @ w
        return out

    coarse = np.arange(0.0, a.pipe_length_m + 1e-9, 4.0)
    sc = score(coarse)
    x0 = coarse[sc.argmax()]
    fine = np.arange(x0 - 6.0, x0 + 6.0 + 1e-9, 0.25)
    sf = score(fine)
    x_hat = float(fine[sf.argmax()])
    conf = float(np.clip((sf.max() - np.median(sc)) / (1.0 - np.median(sc) + 1e-12), 0, 1))

    # origin time: delay-and-sum at x_hat, peak of the stacked envelope
    d = np.abs(xi - x_hat)[:, None]
    Z = (Xb * np.exp(2j * np.pi * fb[None, :] * d / a.c_nominal)).sum(axis=0)
    full = np.zeros(len(f), dtype=complex)
    full[m] = Z
    stack = np.fft.irfft(full, n)
    t0_hat = float(np.argmax(np.abs(hilbert(stack))) / a.fs_hz)
    return x_hat, t0_hat, conf


def sensing_kernel(sig: np.ndarray, x_nom: np.ndarray, a: Assumptions = A
                   ) -> Optional[DetectionReport]:
    """Detect -> select neighbours -> localise. None if no event declared."""
    sig = mains_notch(sig, a)
    trig = sta_lta_detect(sig, a)
    srt = np.sort(trig)
    k = a.min_sensors
    with np.errstate(invalid="ignore"):
        ok = np.where(np.isfinite(srt[k - 1:]) &
                      ((srt[k - 1:] - srt[:len(srt) - k + 1]) <= a.gather_window_s))[0]
    if len(ok) == 0:                       # coincidence rule: >= k sensors in window
        return None
    t_first = float(srt[ok[0]])
    sel = np.where((trig >= t_first) & (trig <= t_first + a.gather_window_s))[0]
    sel = sel[np.argsort(trig[sel])][:a.max_sensors]       # earliest-arrival subset
    sel = np.sort(sel)
    t_ready = t_first + a.gather_window_s + a.pulse_margin_s
    t_wall = time.perf_counter()
    x_hat, t0_hat, conf = phase_coherence_localize(sig, x_nom, sel, t_ready, a)
    compute = time.perf_counter() - t_wall
    return DetectionReport(x_hat, t0_hat, t_first - t0_hat, conf, len(sel),
                           t_first, t_ready, compute)


# =============================================================================
# 2. MOD 2  --  Power & edge scheduler (Green Box)
# =============================================================================
class PState(Enum):
    DEEP_SLEEP = auto()
    ANOMALY_DETECTED = auto()
    HIGH_POWER_TRANSMIT = auto()


class PEvent(Enum):
    ANOMALY_IRQ = auto()       # wake comparator / upstream sensor trigger
    ANALYSIS_DONE = auto()     # localisation finished, confidence ok
    FALSE_ALARM = auto()       # confidence below floor
    TX_COMPLETE = auto()


# Explicit transition table == the table the FreeRTOS port would encode
# (events delivered by xTaskNotifyFromISR / xQueueSend to the scheduler task).
TRANSITIONS: Dict[Tuple[PState, PEvent], PState] = {
    (PState.DEEP_SLEEP, PEvent.ANOMALY_IRQ): PState.ANOMALY_DETECTED,
    (PState.ANOMALY_DETECTED, PEvent.ANALYSIS_DONE): PState.HIGH_POWER_TRANSMIT,
    (PState.ANOMALY_DETECTED, PEvent.FALSE_ALARM): PState.DEEP_SLEEP,
    (PState.HIGH_POWER_TRANSMIT, PEvent.TX_COMPLETE): PState.DEEP_SLEEP,
}


class PowerFSM:
    """Finite-state machine with per-state energy accounting.
    Time is supplied by the caller (discrete-event simulation)."""

    def __init__(self, a: Assumptions = A):
        self.a = a
        self.state = PState.DEEP_SLEEP
        self.t = 0.0
        self.ledger: Dict[PState, List[float]] = {s: [0.0, 0.0] for s in PState}
        self.log: List[str] = []
        self.current = {PState.DEEP_SLEEP: a.i_deep_sleep_a,
                        PState.ANOMALY_DETECTED: a.i_active_a,
                        PState.HIGH_POWER_TRANSMIT: a.i_tx_a}

    def dispatch(self, ev: PEvent, t: float) -> PState:
        nxt = TRANSITIONS.get((self.state, ev))
        if nxt is None:
            raise RuntimeError(f"illegal event {ev.name} in {self.state.name}")
        dt = t - self.t
        self.ledger[self.state][0] += dt
        self.ledger[self.state][1] += dt * self.current[self.state] * self.a.v_supply
        self.log.append(f"t={t*1e3:10.1f} ms  {self.state.name:>20} --{ev.name}--> {nxt.name}")
        self.state, self.t = nxt, t
        return nxt


def lora_airtime_s(payload_bytes: int, sf: int, bw: float, cr: int = 1,
                   preamble: int = 8) -> float:
    """Semtech SX127x time-on-air (explicit header, CRC on)."""
    tsym = (2 ** sf) / bw
    de = 1 if tsym > 0.016 else 0
    n_pay = 8 + max(math.ceil((8 * payload_bytes - 4 * sf + 28 + 16 - 0)
                              / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (preamble + 4.25 + n_pay) * tsym


# --- TriggerSignal wire format (22 bytes, little-endian) ----------------------
#  0  u8   magic 0xTE   1  u8 version   2  u16 node_id   4  u16 seq
#  6  u8   severity     7  u8 flags     8  f32 chainage_m
# 12  i32  dt_us (detect lag vs origin)  16 u8 confidence(0-255)
# 17  u8   reserved    18  u8[4] HMAC-SHA256 tag (truncated)
_TRIG_FMT = "<BBHHBBfiBB"
TRIGGER_LEN = struct.calcsize(_TRIG_FMT) + 4
TRIGGER_MAGIC = 0xE7


@dataclass
class TriggerSignal:
    node_id: int
    seq: int
    severity: int
    chainage_m: float
    dt_us: int
    confidence: float
    flags: int = 0

    def pack(self, key: bytes) -> bytes:
        body = struct.pack(_TRIG_FMT, TRIGGER_MAGIC, 1, self.node_id, self.seq,
                           self.severity, self.flags, self.chainage_m, self.dt_us,
                           int(round(self.confidence * 255)), 0)
        return body + hmac.new(key, body, hashlib.sha256).digest()[:4]

    @staticmethod
    def unpack(raw: bytes, key: bytes, last_seq: int) -> "TriggerSignal":
        if len(raw) != TRIGGER_LEN:
            raise ValueError("bad length")
        body, tag = raw[:-4], raw[-4:]
        if not hmac.compare_digest(hmac.new(key, body, hashlib.sha256).digest()[:4], tag):
            raise ValueError("bad HMAC")
        mg, _, node, seq, sev, flg, ch, dt, conf, _ = struct.unpack(_TRIG_FMT, body)
        if mg != TRIGGER_MAGIC:
            raise ValueError("bad magic")
        if seq <= last_seq:
            raise ValueError("replayed seq")
        return TriggerSignal(node, seq, sev, ch, dt, conf / 255.0, flg)


def battery_life_years(a: Assumptions = A) -> Dict[str, float]:
    """Average power & life for a heartbeat + rare-event duty cycle.
    Uses the same constants as the FSM; event cost taken from a nominal
    0.8 s analysis + 3 transmissions."""
    air = lora_airtime_s(TRIGGER_LEN, a.lora_sf, a.lora_bw_hz)
    hb_j = a.v_supply * (a.i_active_a * a.heartbeat_active_s + a.i_tx_a * a.heartbeat_tx_s)
    ev_j = a.v_supply * (a.i_active_a * (a.gather_window_s + a.pulse_margin_s + 0.05)
                         + a.i_tx_a * air * a.tx_repeats)
    year = 365.0 * 86400.0
    sleep_j = a.v_supply * a.i_deep_sleep_a * year
    hb_year = hb_j * year / a.heartbeat_period_s
    ev_year = ev_j * a.events_per_year
    usable_j = a.battery_wh * 3600.0 * a.battery_usable
    total_j = sleep_j + hb_year + ev_year
    avg_w = total_j / year
    loss_j = a.battery_wh * 3600.0 * a.self_discharge_per_yr
    life = min(usable_j / (total_j + loss_j), a.cell_shelf_life_yr)
    return {"avg_power_uW": avg_w * 1e6, "sleep_share_pct": 100 * sleep_j / total_j,
            "heartbeat_share_pct": 100 * hb_year / total_j,
            "event_share_pct": 100 * ev_year / total_j,
            "battery_life_years": life,
            "energy_limited_years": usable_j / (total_j + loss_j), "airtime_ms": air * 1e3}


# =============================================================================
# 3. MOD 3  --  Autonomous trajectory & obstacle avoidance (Falcon Eye)
# =============================================================================
@dataclass
class Obstacle:
    pos: np.ndarray
    vel: np.ndarray
    r: float
    kind: str


class AvianKernel:
    """Avian-inspired reactive decision kernel (2-D point-mass UAV).

    Three layers, mirroring how birds fly through clutter:
      1. goal pursuit      -- fly the line of sight to the target
      2. looming avoidance -- time-to-contact (tau) and predicted closest
         point of approach (CPA) drive a lateral steer *away from where the
         obstacle will be*; the chosen side is committed until the threat
         clears (no dithering)
      3. reflex            -- tau < reflex_tau or inside the keep-out ring
         overrides everything with a hard radial escape
    """

    def __init__(self, a: Assumptions = A):
        self.a = a
        self.commit: Dict[int, float] = {}
        self.clear_since: Dict[int, float] = {}
        self.reflex_events = 0

    def command(self, pos, vel, target, obs: List[Obstacle], t: float) -> np.ndarray:
        a = self.a
        to_t = target - pos
        dist = float(np.linalg.norm(to_t))
        g = to_t / (dist + 1e-9)
        v_goal = g * min(a.uav_vmax, math.sqrt(2 * 0.6 * a.uav_amax * max(dist - 3, 0)) + 2)
        if not obs:
            return v_goal
        P = np.array([o.pos for o in obs]) - pos
        V = np.array([o.vel for o in obs]) - vel
        r = np.array([o.r for o in obs]) + a.uav_radius_m
        d = np.linalg.norm(P, axis=1) + 1e-9
        vv = (V ** 2).sum(1) + 1e-9
        t_cpa = np.clip(-(P * V).sum(1) / vv, 0, None)
        cpa = P + V * t_cpa[:, None]
        d_cpa = np.linalg.norm(cpa, axis=1)
        closing = -(P * V).sum(1) / d
        tau = np.where(closing > 0.1, (d - r) / np.maximum(closing, 0.1), np.inf)
        keep = r + a.avoid_margin_m
        threat = (t_cpa < a.avoid_horizon_s) & (d_cpa < keep) & ((closing > 0) | (d < keep))
        steer = np.zeros(2)
        for i in np.where(threat)[0]:
            self.clear_since.pop(i, None)
            los = P[i] / d[i]
            nl = np.array([-los[1], los[0]])
            if i not in self.commit:                       # commit a side once
                side = float(np.dot(cpa[i], nl))
                self.commit[i] = -1.0 if side > 0 else 1.0 if side < 0 else 1.0
            urg = (1.0 - t_cpa[i] / a.avoid_horizon_s) ** 0.5
            urg = max(urg, 1.0 if d[i] < keep[i] * 1.3 else 0.0)
            away = self.commit[i] * nl - 0.25 * los
            steer += urg * 1.4 * a.uav_vmax * away / (np.linalg.norm(away) + 1e-9)
        for i in list(self.commit):                        # release stale commits
            if i < len(obs) and not threat[i]:
                self.clear_since.setdefault(i, t)
                if t - self.clear_since[i] > 3.0:
                    self.commit.pop(i); self.clear_since.pop(i)
        v_cmd = v_goal + steer
        sp = np.linalg.norm(v_cmd)
        if sp > a.uav_vmax:
            v_cmd *= a.uav_vmax / sp
        j = int(np.argmin(d - r))                          # 3. reflex layer
        if (d[j] - r[j]) < a.avoid_margin_m * 0.4 or (tau[j] < a.reflex_tau_s):
            self.reflex_events += 1
            vh = V[j] / (np.linalg.norm(V[j]) + 1e-9)       # escape sideways to the
            perp = np.array([-vh[1], vh[0]])                # obstacle's relative motion
            perp = perp if np.dot(perp, -P[j]) >= 0 else -perp
            v_cmd = (0.8 * perp - 0.2 * P[j] / d[j]) * a.uav_vmax
        return v_cmd


def build_world(rng: np.random.Generator, base: np.ndarray, target: np.ndarray,
                n_dyn: int = 8, n_static: int = 3) -> List[Obstacle]:
    """Obstacles are generated *on collision courses* with the nominal
    straight-line flight (stress test, not a friendly world)."""
    a = A
    D = np.linalg.norm(target - base)
    g = (target - base) / D
    nl = np.array([-g[1], g[0]])
    obs: List[Obstacle] = []
    for _ in range(n_static):                              # towers / masts
        fr = rng.uniform(0.15, 0.85)
        obs.append(Obstacle(base + g * D * fr + nl * rng.uniform(-12, 12),
                            np.zeros(2), 20.0, "static"))
    for _ in range(n_dyn):                                 # birds / drones
        fr = rng.uniform(0.1, 0.9)
        tau_meet = fr * D / a.uav_vmax + rng.uniform(-3, 3)
        meet = base + g * a.uav_vmax * max(tau_meet, 1.0)
        L = rng.uniform(120, 400)
        ang = rng.uniform(0, 2 * np.pi)
        start = meet + L * np.array([math.cos(ang), math.sin(ang)])
        v = (meet - start) / max(tau_meet, 1.0)
        sp = np.linalg.norm(v)
        if sp > 14.0:
            v *= 14.0 / sp
        obs.append(Obstacle(start, v, rng.uniform(2.0, 8.0), "dynamic"))
    return obs


def fly(rng: np.random.Generator, base: np.ndarray, target: np.ndarray,
        a: Assumptions = A) -> Dict[str, float]:
    """Simulate launch -> arrival -> area scan. Returns metrics."""
    obs = build_world(rng, base, target)
    kern = AvianKernel(a)
    pos, vel, t = base.astype(float).copy(), np.zeros(2), 0.0
    path_len, min_clear, collided, hit_info = 0.0, float("inf"), False, None
    straight = float(np.linalg.norm(target - base))
    while np.linalg.norm(target - pos) > a.arrive_radius_m and t < 600.0:
        v_cmd = kern.command(pos, vel, target, obs, t)
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
            if gap < 0 and not collided:
                collided = True
                hit_info = (o.kind, o.r, float(np.linalg.norm(o.vel)), round(t, 1))
    arrived = bool(np.linalg.norm(target - pos) <= a.arrive_radius_m)
    # lawn-mower scan of the AOI, coverage computed on a 2 m grid
    half, lanes = a.scan_aoi_m / 2, int(math.ceil(a.scan_aoi_m / (a.scan_swath_m * 0.85)))
    ys = np.linspace(-half + a.scan_swath_m / 2, half - a.scan_swath_m / 2, lanes)
    pts = []
    for k, y in enumerate(ys):
        xs_ = np.linspace(-half, half, 101)
        pts.append(np.stack([xs_ if k % 2 == 0 else xs_[::-1], np.full(101, y)], 1))
    route = np.concatenate(pts)
    scan_len = float(np.linalg.norm(np.diff(route, axis=0), axis=1).sum()
                     + (lanes - 1) * 0.0)
    gx, gy = np.meshgrid(np.arange(-half, half + 1, 2.0), np.arange(-half, half + 1, 2.0))
    cells = np.stack([gx.ravel(), gy.ravel()], 1)
    dmin = np.min(np.linalg.norm(cells[:, None, :] - route[None, ::5, :], axis=2), axis=1)
    coverage = float(np.mean(dmin <= a.scan_swath_m / 2))
    t_scan = scan_len / a.scan_speed
    fly.last_hit = hit_info
    return {"arrived": arrived, "collided": collided, "flight_s": t, "path_m": path_len,
            "straight_m": straight, "path_efficiency": straight / max(path_len, 1e-9),
            "min_clearance_m": min_clear, "reflex_events": kern.reflex_events,
            "scan_s": t_scan, "scan_coverage": coverage,
            "e_flight_wh": a.p_cruise_w * t / 3600.0,
            "e_scan_wh": (a.p_scan_w + a.p_edge_ai_w) * t_scan / 3600.0}


# =============================================================================
# 4. Orchestrator: one end-to-end episode
# =============================================================================
KEY = b"titan-edge-demo-key-NOT-FOR-PRODUCTION"


def run_episode(seed: int, xs: Optional[float] = None, snr_db: float = 12.0,
                say=None, a: Assumptions = A) -> Dict:
    rng = np.random.default_rng(seed)
    arr = SubSurfaceArray(rng, a)
    xs = float(rng.uniform(150, a.pipe_length_m - 150)) if xs is None else xs
    base = np.array([rng.uniform(800, 2200), rng.uniform(500, 900)])
    out: Dict = {"seed": seed, "true_chainage_m": xs, "snr_db": snr_db}

    say = say or (lambda msg: None)

    # ---- MOD 1 ---------------------------------------------------------------
    sig = arr.simulate(xs, snr_db, rng)
    rep = sensing_kernel(sig, arr.x_nom, a)
    if rep is None:
        out["status"] = "MISSED"
        return out
    err = abs(rep.chainage_m - xs)
    t_first_rel = rep.t_first_trigger_s - a.event_time_s       # vs physical event
    say(f"[MOD1] event @ chainage {xs:8.1f} m  (t=0)")
    say(f"[MOD1] first trigger      +{t_first_rel*1e3:8.1f} ms  (propagation + STA/LTA)")
    say(f"[MOD1] gather window closes +{(rep.t_data_ready_s-a.event_time_s)*1e3:6.1f} ms "
        f"using {rep.n_sensors_used}/{a.n_sensors} sensors")
    say(f"[MOD1] LOCALISED chainage {rep.chainage_m:8.2f} m   error {err:6.2f} m   "
        f"t0_hat err {(rep.t0_s-a.event_time_s)*1e3:+.1f} ms   dt={rep.delta_t_s*1e3:.1f} ms   "
        f"conf {rep.confidence:.2f}   host compute {rep.compute_s*1e3:.1f} ms")

    # ---- MOD 2 ---------------------------------------------------------------
    fsm = PowerFSM(a)
    t = t_first_rel                                            # clock: event = 0
    fsm.t = t                                                  # asleep until trigger
    t_wake = t + a.wake_latency_s
    fsm.dispatch(PEvent.ANOMALY_IRQ, t_wake)
    t_analysis_done = ((rep.t_data_ready_s - a.event_time_s) + a.link_latency_s
                       + rep.compute_s)
    fsm.dispatch(PEvent.ANALYSIS_DONE, t_analysis_done)
    trig = TriggerSignal(node_id=7, seq=1, severity=3, chainage_m=rep.chainage_m,
                         dt_us=int(rep.delta_t_s * 1e6), confidence=rep.confidence)
    raw = trig.pack(KEY)
    air = lora_airtime_s(len(raw), a.lora_sf, a.lora_bw_hz)
    t_tx_end = t_analysis_done + a.tx_repeats * air + (a.tx_repeats - 1) * a.tx_spacing_s
    fsm.dispatch(PEvent.TX_COMPLETE, t_tx_end)
    # first packet that survives the channel
    got, t_rx = None, None
    for k in range(a.tx_repeats):
        if rng.random() > a.packet_loss:
            got, t_rx = k, t_analysis_done + (k + 1) * air + k * a.tx_spacing_s
            break
    for line in fsm.log:
        say("[MOD2] " + line)
    say(f"[MOD2] TriggerSignal {len(raw)} B, airtime {air*1e3:.1f} ms x{a.tx_repeats}")
    e_sensing = (rep.n_sensors_used * a.i_sense_a * a.v_supply
                 * (rep.t_data_ready_s - rep.t_first_trigger_s))
    e_edge = {s.name: v[1] for s, v in fsm.ledger.items()}
    if got is None:
        out.update(status="TRIGGER_LOST")
        return out

    # ---- MOD 3 ---------------------------------------------------------------
    uav_ok = TriggerSignal.unpack(raw, KEY, last_seq=0)        # auth + replay check
    t_launch = t_rx + a.uav_verify_s
    t_airborne = t_launch + a.uav_spinup_s
    say(f"[MOD3] TriggerSignal RX +{t_rx*1e3:8.1f} ms (packet #{got+1}), HMAC ok, "
        f"target chainage {uav_ok.chainage_m:.1f} m")
    target = np.array([uav_ok.chainage_m, 0.0])
    fl = fly(rng, base, target, a)
    t_arrive = t_airborne + fl["flight_s"]
    t_scanned = t_arrive + fl["scan_s"]
    say(f"[MOD3] airborne          +{t_airborne:8.2f} s")
    say(f"[MOD3] flight {fl['flight_s']:.1f} s, path {fl['path_m']:.0f} m "
        f"(straight {fl['straight_m']:.0f} m, eff {fl['path_efficiency']:.2f}), "
        f"min clearance {fl['min_clearance_m']:.1f} m, reflex steps {fl['reflex_events']}, "
        f"collided={fl['collided']}")
    say(f"[MOD3] ARRIVED           +{t_arrive:8.2f} s ; AOI scan {fl['scan_s']:.0f} s, "
        f"coverage {fl['scan_coverage']*100:.0f} %  (Edge-AI classifier: STUB)")
    say(f"[MOD3] AREA SCANNED      +{t_scanned:8.2f} s")

    out.update(
        status="OK", loc_error_m=err, t0_error_ms=(rep.t0_s - a.event_time_s) * 1e3,
        confidence=rep.confidence, n_sensors_used=rep.n_sensors_used,
        compute_ms=rep.compute_s * 1e3,
        lat_event_to_first_trigger_ms=t_first_rel * 1e3,
        lat_trigger_to_tx_complete_ms=(t_tx_end - t_first_rel) * 1e3,
        lat_trigger_to_uav_rx_ms=(t_rx - t_first_rel) * 1e3,
        lat_trigger_to_airborne_s=t_airborne - t_first_rel,
        t_arrive_s=t_arrive, t_scanned_s=t_scanned,
        e_sensing_mJ=e_sensing * 1e3,
        e_edge_deep_sleep_mJ=e_edge["DEEP_SLEEP"] * 1e3,
        e_edge_anomaly_mJ=e_edge["ANOMALY_DETECTED"] * 1e3,
        e_edge_tx_mJ=e_edge["HIGH_POWER_TRANSMIT"] * 1e3,
        **{k: (float(v) if not isinstance(v, bool) else v) for k, v in fl.items()})
    return out


# =============================================================================
# 5. Benchmark harness
# =============================================================================
def pct(x, p):
    return float(np.percentile(x, p)) if len(x) else float("nan")


class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def __call__(self, s=""):
        print(s)
        self.f.write(s + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    n_mc = 20 if args.quick else 60
    n_loc = 20 if args.quick else 60
    n_fa = 50 if args.quick else 200
    log = Tee(os.path.join(args.out, "benchmark_log.txt"))
    results: Dict = {"assumptions": {k: (list(v) if isinstance(v, tuple) else v)
                                      for k, v in A.__dict__.items()}}

    log("=" * 78)
    log("TITAN-EDGE DIGITAL TWIN  --  benchmark log   (simulation; no field data)")
    log("=" * 78)

    # ---- A. one narrated end-to-end episode ------------------------------------
    log("\n--- A. Single narrated episode (seed %d, SNR@100m = 12 dB) ---" % args.seed)
    ep = run_episode(args.seed, say=log)
    results["narrated_episode"] = ep

    # ---- B. localisation accuracy vs SNR ---------------------------------------
    log("\n--- B. MOD 1 localisation vs SNR (%d random events per row) ---" % n_loc)
    log(f"{'SNR@100m':>9} {'detect%':>8} {'median err m':>13} {'p90 err m':>10} "
        f"{'<=10m %':>8} {'<=3m %':>7}")
    rows = []
    for snr in (0, 6, 12, 20):
        errs, miss = [], 0
        for s in range(n_loc):
            rng = np.random.default_rng(10_000 + 97 * s + snr)
            arr = SubSurfaceArray(rng)
            xs = float(rng.uniform(100, A.pipe_length_m - 100))
            rep = sensing_kernel(arr.simulate(xs, snr, rng), arr.x_nom)
            if rep is None:
                miss += 1
            else:
                errs.append(abs(rep.chainage_m - xs))
        e = np.array(errs)
        det = 100 * (n_loc - miss) / n_loc
        row = dict(snr_db=snr, detect_pct=det, median_err_m=pct(e, 50), p90_err_m=pct(e, 90),
                   within_10m_pct=100 * float(np.mean(e <= 10)) * (len(e) / n_loc) if len(e) else 0.0,
                   within_3m_pct=100 * float(np.mean(e <= 3)) * (len(e) / n_loc) if len(e) else 0.0)
        rows.append(row)
        log(f"{snr:>7} dB {det:>7.0f}% {row['median_err_m']:>13.2f} {row['p90_err_m']:>10.2f} "
            f"{row['within_10m_pct']:>7.0f}% {row['within_3m_pct']:>6.0f}%")
    results["localisation_vs_snr"] = rows

    # ---- C. false alarms ---------------------------------------------------------
    fa = 0
    for s in range(n_fa):
        rng = np.random.default_rng(50_000 + s)
        arr = SubSurfaceArray(rng)
        rep = sensing_kernel(arr.simulate(None, 0, rng), arr.x_nom)
        fa += rep is not None
    log(f"\n--- C. False alarms: {fa} declared events in {n_fa} noise-only "
        f"{A.record_s:.0f} s records (31 sensors) ---")
    results["false_alarms"] = {"events": fa, "records": n_fa, "record_s": A.record_s}

    # ---- D. end-to-end Monte Carlo -----------------------------------------------
    log(f"\n--- D. End-to-end Monte Carlo ({n_mc} episodes, SNR@100m = 12 dB, "
        f"8 moving + 3 fixed obstacles on collision courses) ---")
    eps = [run_episode(1000 + i) for i in range(n_mc)]
    ok = [e for e in eps if e["status"] == "OK"]
    keys = ["loc_error_m", "lat_event_to_first_trigger_ms", "lat_trigger_to_tx_complete_ms",
            "lat_trigger_to_uav_rx_ms", "lat_trigger_to_airborne_s", "flight_s",
            "t_arrive_s", "t_scanned_s", "min_clearance_m", "path_efficiency", "compute_ms",
            "e_sensing_mJ", "e_edge_deep_sleep_mJ", "e_edge_anomaly_mJ", "e_edge_tx_mJ",
            "e_flight_wh", "e_scan_wh"]
    summ = {k: {"median": pct([e[k] for e in ok], 50), "p95": pct([e[k] for e in ok], 95)}
            for k in keys}
    n_col = sum(bool(e["collided"]) for e in ok)
    n_arr = sum(bool(e["arrived"]) for e in ok)
    log(f"episodes OK {len(ok)}/{n_mc} | UAV arrived {n_arr}/{len(ok)} | "
        f"collisions {n_col}/{len(ok)} | status other: "
        f"{sorted(set(e['status'] for e in eps) - {'OK'})}")
    log(f"{'metric':<34}{'median':>12}{'p95':>12}")
    for k in keys:
        log(f"{k:<34}{summ[k]['median']:>12.2f}{summ[k]['p95']:>12.2f}")
    results["monte_carlo"] = {"n": n_mc, "ok": len(ok), "arrived": n_arr,
                              "collisions": n_col, "summary": summ}

    # ---- E. power budget ---------------------------------------------------------
    b = battery_life_years()
    log("\n--- E. Edge-node energy model (ASSUMED datasheet-class constants) ---")
    log(f"TriggerSignal: {TRIGGER_LEN} B, LoRa SF{A.lora_sf}/{A.lora_bw_hz/1e3:.0f} kHz "
        f"airtime {b['airtime_ms']:.1f} ms")
    log(f"Average draw {b['avg_power_uW']:.1f} uW  (sleep {b['sleep_share_pct']:.0f} %, "
        f"heartbeat {b['heartbeat_share_pct']:.0f} %, events {b['event_share_pct']:.1f} %)")
    log(f"Battery {A.battery_wh} Wh x {A.battery_usable:.0%} usable -> energy-limited "
        f"{b['energy_limited_years']:.0f} y, capped by cell shelf life to "
        f"{b['battery_life_years']:.0f} y  "
        f"({A.events_per_year:.0f} events/yr, 1 heartbeat/{A.heartbeat_period_s/3600:.0f} h)")
    results["power_budget"] = b

    log("\nCAVEATS: idealised 1-D homogeneous pipe; power constants are assumptions; "
        "compute time is host CPU; Edge-AI classifier is a stub; no hardware in loop.")
    with open(os.path.join(args.out, "benchmark_results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=float)
    return 0


if __name__ == "__main__":
    sys.exit(main())
