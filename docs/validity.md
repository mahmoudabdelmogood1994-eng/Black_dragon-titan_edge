# Scientific validity: what the detector claims, and what it does not

## 1. The top percentile is not the alert criterion

Every image has a highest pixel and a 99th percentile, even over clean water. Titan-Edge therefore never alerts on either. A scene becomes an `ALERT_CANDIDATE` only if **connected clusters of at least 18 clean-water pixels (≥ 7,200 m² at 20 m) have NDCI above 0.20**, and a bloom is only treated as real after confirmation on **two or more dates**.

Evidence from the real Mirfa series (`docs/figures/mirfa_series.png`):

| Scene | NDCI p99 | Max pixel | Pixels > 0.20 | Qualifying clusters | Status |
|---|---|---|---|---|---|
| 2026-09-09 | 0.139 | 0.285 | 1,195 | 10 | ALERT_CANDIDATE |
| 2026-09-12 | 0.108 | 0.361 | 204 | 3 | ALERT_CANDIDATE |
| 2026-09-17 | 0.083 | 0.412 | 127 | 3 | ALERT_CANDIDATE |
| 2026-09-22 | 0.076 | 0.296 | 33 | 1 | ALERT_CANDIDATE |
| 2026-09-27 | 0.091 | 0.625 | 222 | 4 | ALERT_CANDIDATE |
| 2026-09-29 | 0.058 | 0.594 | 63 | 1 | ALERT_CANDIDATE |
| 2026-10-02 | 0.061 | 0.311 | 18 | 1 | ALERT_CANDIDATE |
| 2026-10-07 | 0.068 | 0.427 | 21 | **0** | WATCH |

* The 99th percentile is **below 0.20 in all 8 scenes**, while the maximum pixel is above it in all 8. Neither number drives the status; clusters do (the 7 Oct scene has a 0.43 maximum pixel and no cluster, so it is only `WATCH`).
* **Negative control** (`tests/test_mirfa_pipeline.py`): a synthetic clean-water scene still has a p99 (0.033) but produces 0 clusters and status `NONE`; the same scene with a planted bloom produces a cluster and `ALERT_CANDIDATE`.
* An earlier notebook version alerted on the single maximum pixel (NDCI 0.79 in Fujairah); those pixels were 20 m from land. The monitor now applies a shore buffer and reports mask sensitivity per scene.

## 2. NDCI and the shallow, saline Gulf

NDCI = (R705 − R665) / (R705 + R665) for Sentinel-2 B5 and B4 (Mishra & Mishra, 2012). It was proposed for **estuarine and coastal turbid productive waters**, not specifically for the shallow saline Arabian Gulf, so its behaviour there must be checked locally. Known confounders: bright shallow seabed, suspended sediment, sun glint and surface foam, vessels and floating material, and aerosol/atmospheric-correction errors (one Fujairah May composite showed a flat ~0.09 reflectance in every band including NIR over open sea, so that scene was unusable).

What the pipeline already does: clean-water mask (NDWI > 0.1 and NIR below a ceiling), removal of small water bodies, a 3 px shore buffer, per-scene detection of the reflectance offset, a minimum cluster size, a sanity cap on NDCI, a recurring-site test (a candidate at the same position in most scenes is more likely a fixed feature), and a status of `INCONCLUSIVE` when too little clean water remains.

What it does not do: convert NDCI to chlorophyll-a concentration. NDCI is reported as a **screening index**. No empirical chlorophyll model is applied because none has been calibrated for these waters.

**Calibration plan:** (1) obtain in-situ chlorophyll-a (the plant operator's intake monitoring or the national red-tide programme) matched to Sentinel-2 passes within ±1 day; (2) fit or reject a local NDCI–chlorophyll relation and choose the threshold from the match-ups (the 0.20 used now is a screening default, not a calibrated value); (3) test alternative indices on the same match-ups; (4) re-derive the false-alarm rate on a full autumn–winter season.

## 3. Replaying documented events

See `docs/validation/README.md`. The first prepared test is the January 2018 Ras Al Khaimah bloom (Sentinel-2 era); it is described by the ministry as limited and low-biomass, so a miss would not be conclusive. The 2008–2009 bloom precedes Sentinel-2 and would need ENVISAT MERIS data (whose bands were used to develop red-edge algorithms), which this pipeline does not read.

## 4. References (checked)

* Mishra, S., & Mishra, D. R. (2012). Normalized difference chlorophyll index: A novel model for remote estimation of chlorophyll-a concentration in turbid productive waters. *Remote Sensing of Environment*, 117, 394–406. doi:10.1016/j.rse.2011.10.016
* McFeeters, S. K. (1996). The use of the Normalized Difference Water Index (NDWI) in the delineation of open water features. *International Journal of Remote Sensing*, 17(7), 1425–1432. doi:10.1080/01431169608948714
