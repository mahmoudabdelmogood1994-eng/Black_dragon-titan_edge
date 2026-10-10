# Titan-Edge: use-case description

**Theme 6 — Water Quality · Site: Mirfa IWPP seawater intake, Abu Dhabi · Team: [name]**

**Coordinates.** Intake (assumed): **24.1393236 N, 53.4566472 E**, the tip of a long pipe visible in imagery, not yet confirmed with the operator. Plant point (approximate, WRI database): 24.121 N, 53.447 E. Study area: `[53.36, 24.04, 53.54, 24.20]`.

## Problem
Desalination is the main drinking-water source in the Gulf (the share varies by country and source). Harmful algal blooms ("red tides") recur in the Arabian Gulf and Gulf of Oman and have affected desalination: a 2008–2009 bloom reportedly led Gulf governments to order desalination plants to shut down, and high bloom concentrations have in the past clogged UAE plant filters (sources below). Studies of the Gulf find blooms mainly in autumn and winter. Operators need to know early whether chlorophyll anomalies near an intake are a real, approaching bloom or a false alarm from shorelines, shallow seabed or vessels, because shutting an intake is costly and ignoring a real bloom is worse.

## Who benefits
Desalination operators and water utilities (first user: the Mirfa plant), and national environment authorities that already run satellite red-tide monitoring.

## Solution
Titan-Edge chains three layers so each reduces the doubt left by the last:
1. **Space (built, real data).** A monitor downloads the latest cloud-filtered Sentinel-2 scenes around the intake, builds a clean-water mask, computes NDCI from the red-edge band, applies one rule to every scene (NDCI > 0.20, clusters ≥ 7,200 m²) and compares scenes over time. Output levels: NONE / WATCH / ALERT_CANDIDATE / INCONCLUSIVE; an alert needs confirmation on at least two dates. A recurring-site test separates fixed features from drifting blooms. Over Mirfa the usable scenes were **2–5 days apart (median 5)**, so the satellite alone cannot protect the days in between.
2. **Ground (simulated).** Meant to cover the gap between satellite passes: a subsea sensor array confirms the approach (advection ETA, phase-coherence early warning) and sends a 24-byte authenticated low-power trigger.
3. **Air (simulated).** A drone flies to the candidate with obstacle avoidance and runs a hyper-spectral check. The system's output is an **intake-protection recommendation to the operator**, to be confirmed by the subsea sensors and approved by the operator; it never acts automatically.

## What was done and what it shows
- Eight Sentinel-2 scenes over Mirfa (9 Sep – 7 Oct 2026): seven `ALERT_CANDIDATE`, latest `WATCH`, series status **WATCH**; **no bloom confirmed**.
- The closest candidate recurs at the **same position, 3.34 km from the assumed intake, in 6 of 8 scenes**, which is typical of a fixed feature rather than a drifting bloom; a visual check is requested.
- An earlier version of the notebook raised an alert from shoreline pixels; the current rule and mask removed it, and mask sensitivity is reported with every scene.
- A response-chain drill on the real candidates (assumed current and sensor layout) shows that waiting for the in-situ alarm is too late for a ~3 h approach, while launching on the satellite ETA gives the recommendation ~170 min before the modelled front. We do not claim zero latency.
- Code, notebooks and tests are in the repository and run from a clean copy.

## Evidence (real record, latest scene)

Figure: `docs/figures/mirfa_series.png` (p99 vs threshold, clusters per scene). Excerpt of `docs/figures/mirfa_event_excerpt_2026-10-07.json`:

```json
{
  "status": "WATCH",
  "scene_datetime": "2026-10-07T07:13:00.119000Z",
  "ndci_clean_water": {
    "max": 0.4269,
    "p99": 0.0676,
    "p50": 0.0213,
    "pixels_with_usable_signal": 441522
  },
  "pixels_above_threshold": 21,
  "clusters_qualifying": 0,
  "clusters_near_intake": 0
}
```

The 99th percentile is below the 0.20 threshold in all 8 scenes, so it is not what raises a status; clusters are (`docs/validity.md`).

## Limitations (stated openly)
The intake coordinate is the tip of a pipe seen in imagery, assumed to be the intake; NDCI is a proxy with no in-situ chlorophyll-a calibration; the ground and air layers are simulations with assumed currents and latencies; no Planet Tanager scene overlaps the Mirfa area; the detector has not yet been shown to flag a documented bloom (retrospective test prepared: `docs/validation/rak_2018.md`).

## Validity plan
(1) Confirm the intake position with the operator; (2) compare NDCI with in-situ chlorophyll-a; (3) replay documented bloom events; (4) keep monitoring through the autumn–winter season; (5) test real subsea sensors and current data before any operational claim.

## Data and attribution
Contains modified Copernicus Sentinel-2 data (2026), via the Earth Search STAC catalogue. Earlier explorations: Planet Tanager data, CC BY 4.0, "Tanager STAC Data, available at www.planet.com/data/stac © Planet Labs PBC".

## Sources for the problem statement
The National, "Saadiyat closed to swimmers due to a harmful algal bloom" (filters clogged in the past); KustReview, "Red alert" (2008–09 shutdown orders); International Journal of Remote Sensing 37(8), 2016, "Monitoring HABs in the shallow Arabian Gulf using a qualitative satellite-based index" (autumn/winter seasonality). Verify each before quoting.
