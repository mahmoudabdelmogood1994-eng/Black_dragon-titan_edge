"""Scenario configuration for the Titan-Edge space twin.

Every constant that is an ASSUMPTION (not measured, not from a datasheet) is
marked ASSUMED. Replace them with site data before drawing any conclusion.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple
import json


@dataclass
class Config:
    # ---- site (illustrative location, not a real plant) -------------------
    plant_name: str = "Demo desalination plant (illustrative site)"
    plant_lat: float = 27.250
    plant_lon: float = 33.738
    # subsea sensors at the intake heads: (east_m, north_m) from the plant
    intake_xy_m: List[Tuple[float, float]] = field(default_factory=lambda: [
        (1100, -60), (1120, -20), (1140, 20), (1160, 60), (1180, -40), (1200, 40)])
    # optional: real intake-head coordinates [(lat, lon), ...]; if given they replace intake_xy_m
    intake_latlon: Optional[List[Tuple[float, float]]] = None
    # ---- ocean state (ASSUMED; replace with ADCP / model currents) ---------
    current_uv_ms: Tuple[float, float] = (-0.23, -0.10)   # (east, north) m/s
    # ---- satellite (MOD 1) -------------------------------------------------
    sensor: str = "sentinel2"                  # "sentinel2" | "landsat"
    acquisition_utc: str = "2026-10-07T08:15:00Z"
    data_latency_h: float = 3.0                # ASSUMED acquisition -> product
    ndci_threshold: float = 0.10               # ASSUMED; tune per water body
    min_area_km2: float = 0.25
    min_cluster_px: int = 8                    # notebook value (suggested 5-10)
    ndwi_threshold: float = 0.0                # water mask: NDWI > this
    coast_buffer_px: int = 0                   # drop water pixels this close to land (mixed pixels)
    max_range_km: float = 60.0                 # hotspots farther than this are not intake threats
    # ---- subsea intake (MOD 2) ---------------------------------------------
    turbidity_baseline_ntu: float = 0.6        # ASSUMED
    turbidity_limit_ntu: float = 3.0           # ASSUMED intake alarm limit
    precursor_amp_ntu: float = 0.20            # ASSUMED, see titan_ground_subsea.py
    plv_threshold: float = 0.85                # set above noise-only maxima
    plv_persist_min: int = 20
    # ---- air (MOD 3) -------------------------------------------------------
    scan_aoi_m: float = 400.0
    scan_swath_m: float = 60.0
    scan_speed_ms: float = 8.0
    sam_min_confidence: float = 0.60
    prearm: bool = False                       # launch on satellite ETA instead of waiting for the in-situ alarm
    prearm_eta_h: float = 6.0                  # ...when the modelled ETA is at most this many hours
    recommend_protection: bool = True          # the model only RECOMMENDS; execution needs subsea confirmation + operator approval (not modelled)

    def __post_init__(self):
        if self.intake_latlon:
            from geo import to_enu
            self.intake_xy_m = [tuple(float(v) for v in to_enu(la, lo, self.plant_lat, self.plant_lon))
                                for la, lo in self.intake_latlon]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_json(cls, path: str, base: "Config" = None) -> "Config":
        """Override fields from a site.json (keys starting with '_' are comments;
        null values are rejected so a half-filled template cannot run silently)."""
        cfg = base or cls()
        data = {k: v for k, v in json.load(open(path)).items() if not k.startswith("_")}
        nulls = [k for k, v in data.items() if v is None]
        if nulls:
            raise ValueError(f"site file {path} still has empty values: {', '.join(nulls)}")
        unknown = [k for k in data if not hasattr(cfg, k)]
        if unknown:
            raise ValueError(f"unknown keys in {path}: {', '.join(unknown)}")
        for k, v in data.items():
            setattr(cfg, k, [tuple(x) for x in v] if k in ("intake_latlon", "intake_xy_m") else
                    (tuple(v) if k == "current_uv_ms" else v))
        cfg.__post_init__()
        return cfg


# Presets taken from the uploaded notebooks. THRESHOLDS ARE UNCALIBRATED: the
# notebooks themselves say to calibrate against in-situ chlorophyll-a / a
# documented HAB event. INTAKE COORDINATES ARE ILLUSTRATIVE (notebook value).
PRESETS = {
    "fujairah": dict(plant_name="Fujairah intake (ILLUSTRATIVE coordinates from notebook)",
                     plant_lat=25.17, plant_lon=56.36),
    "sentinel2_real": dict(ndci_threshold=0.25, ndwi_threshold=0.0, min_area_km2=0.0,
                           min_cluster_px=8, coast_buffer_px=5),   # 5 px = 100 m at 20 m
    "tanager": dict(ndci_threshold=0.20, ndwi_threshold=0.1, min_area_km2=0.0,
                    min_cluster_px=8, sensor="tanager"),
}


def apply_presets(cfg: "Config", *names: str) -> "Config":
    for n in names:
        for k, v in PRESETS[n].items():
            setattr(cfg, k, v)
    return cfg
