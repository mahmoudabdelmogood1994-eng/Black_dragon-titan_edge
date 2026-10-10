# Mirfa IWPP: real Sentinel-2 monitoring series (9 Sep – 7 Oct 2026)

**Site.** Mirfa IWPP desalination plant, Abu Dhabi. AOI `[53.36, 24.04, 53.54, 24.20]` (EPSG:32639, 20 m). Intake `(24.1393236, 53.4566472)` = tip of the long pipe seen in imagery, **assumed** to be the seawater intake and **not yet confirmed with the operator**. Plant point `(24.121, 53.447)` is approximate (WRI Global Power Plant Database).

**Method.** `src/mirfa_monitor/titan_hab_pipeline.py` (notebook `02_mirfa_hab_monitor_v6`): latest cloud-filtered Sentinel-2 L2A scenes (Earth Search STAC), reflectance offset detected per scene, clean-water mask (NDWI + NIR ceiling, small water bodies removed, 3 px shore buffer), NDCI (red-edge B5 / red B4), one rule for all scenes: NDCI > 0.20 and clusters ≥ 7,200 m² (18 px). Statuses: NONE / WATCH / ALERT_CANDIDATE / INCONCLUSIVE; an ALERT is only raised after confirmation on ≥ 2 dates. NDCI is a spectral proxy, not a chlorophyll measurement.

## Series (8 usable scenes, cloud ≤ 7 %, valid fraction ≥ 98.5 %)

| Date | Status | NDCI max | Qualifying clusters | Nearest cluster to intake | Cloud % |
|---|---|---|---|---|---|
| 2026-09-09 | ALERT_CANDIDATE | 0.285 | 10 | 3.22 km | 0.3 |
| 2026-09-12 | ALERT_CANDIDATE | 0.361 | 3 | 3.39 km | 0.3 |
| 2026-09-17 | ALERT_CANDIDATE | 0.412 | 3 | 6.26 km | 6.9 |
| 2026-09-22 | ALERT_CANDIDATE | 0.296 | 1 | 3.37 km | 0.2 |
| 2026-09-27 | ALERT_CANDIDATE | 0.625 | 4 | 3.33 km | 0.1 |
| 2026-09-29 | ALERT_CANDIDATE | 0.594 | 1 | 3.35 km | 0.1 |
| 2026-10-02 | ALERT_CANDIDATE | 0.311 | 1 | 3.31 km | 0.4 |
| 2026-10-07 | **WATCH** | 0.427 | 0 | none | 0.8 |

**Observed revisit:** consecutive usable scenes were 3, 5, 5, 5, 2, 3 and 5 days apart (median 5), so the satellite leaves gaps of several days that the in-situ and air layers are meant to cover.

**Series status: WATCH.** Trend of the NDCI p99: stable (slope −0.007 per week, n = 5).

## What the series says, and what it does not

* Seven of eight scenes carried candidate clusters, but **no bloom is confirmed**. The latest scene has none (only 21 isolated pixels above 0.20).
* **A recurring fixed site** at `(24.12415, 53.42829)`, 3.34 km from the intake, appears in 6 of 8 scenes (max 84 px, 33,600 m², NDCI max 0.625). Recurrence at the same position is more typical of a fixed feature (shallow bottom, jetty, vessel, outfall) than of a drifting bloom; the pipeline asks for a visual check (Google Maps link in `series_report.html`). Two further recurring sites sit ~9.6 km away (3 of 8 scenes).
* The latest scene's mask sensitivity matters: with a 1 px shore buffer one cluster qualifies, with 3 px none (`single_scene_2026-10-07/titan_edge_event.json`). The earlier v1 `ALERT` (NDCI 0.438) came from shoreline pixels.
* No in-situ chlorophyll-a was used, so nothing is calibrated. The nearest Tanager scene on record (`20250511_074311_00_4001`, 53.63–53.89 E) lies east of this AOI without overlap, so no hyperspectral result is claimed for Mirfa.

## Response-chain drill (scenario, not a detection)

`python3 src/space_twin/drill_mirfa.py` feeds the **real** 2026-09-27 candidates into the simulated ground and air layers (`drill/`). Assumed: 0.15 m/s current from the candidate toward the intake, a 6-sensor array around the tip, 3 h satellite latency.

| Variant | Trigger sent | Operator recommendation vs modelled front |
|---|---|---|
| A: wait for the in-situ coherence alarm | 6.5 h after detection | 222 min **after** (too late); the recommendation is advisory and needs subsea confirmation and operator approval |
| B: pre-arm on the satellite ETA (3.0 h ≤ 6 h) | at detection | 170 min **before** |

With a 3 h ETA the coherence monitor (3 h smoothing) had not settled in time, which is why variant A fails; the design needs satellite-ETA pre-arming for short approaches. Drone flight 1.3 km / 74 s (B). These are model outputs under assumptions, not predictions about Mirfa.

## Files

`series_table.csv`, `series_summary.json`, `series_report.html`, `latest_map.html`, `scenes/<date>/` (event + meta per scene), `single_scene_2026-10-07/`, `drill/`.
