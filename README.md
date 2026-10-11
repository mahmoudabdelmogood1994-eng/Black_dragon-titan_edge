# Titan-Edge · Early warning for desalination intakes (Mirfa IWPP, Abu Dhabi)

A **satellite → in-situ → drone** system for protecting seawater intakes from algal blooms, built for the *Arab Youth Space Hackathon: 813 Challenge* (Theme 6, Water Quality). A real Sentinel-2 monitor screens the Mirfa coast for chlorophyll anomalies near the intake; simulated subsea and drone layers show how a confirmed threat would be verified and answered.

> **Status.** The **space layer is real and runs on live data** (8 Sentinel-2 scenes, 9 Sep – 7 Oct 2026). The **ground (subsea sensor) and air (drone) layers are simulations**, with no hardware and no field measurements. The intake coordinate is an **assumption** (tip of the long pipe seen in imagery) pending operator confirmation. **No bloom has been confirmed.**

## Overview

Algal blooms can foul a seawater intake or force a plant to cut intake. Titan-Edge chains three layers so each one reduces the uncertainty left by the one before:

| Layer | Role | Status | Code |
|---|---|---|---|
| **Space** (Sentinel-2) | Clean-water mask → NDCI → clusters near the intake; series comparison, persistence, trend, recurring-site detection | **Real data, tested** | `src/mirfa_monitor/titan_hab_pipeline.py`, notebook `02` |
| **Ground** (subsea array) | Advection ETA, phase-coherence early warning, 24-byte authenticated low-power trigger | Simulation | `src/space_twin/titan_ground_subsea.py` |
| **Air** (drone) | Obstacle-avoiding flight, hyper-spectral rescan, intake-protection signal | Simulation | `src/space_twin/titan_air_drone.py` |

## Key results (Mirfa, real Sentinel-2)

Details and the full table: [docs/real_run/mirfa/README.md](docs/real_run/mirfa/README.md).

| | |
|---|---|
| Scenes analysed | 8 usable (cloud ≤ 7 %, valid fraction ≥ 98.5 %), 9 Sep – 7 Oct 2026 |
| Per-scene status | `ALERT_CANDIDATE` on 7 dates, `WATCH` on the latest (7 Oct); **series status WATCH** |
| Confirmed bloom | **None.** The latest scene has 0 qualifying clusters; trend stable (−0.007 NDCI/week) |
| Recurring fixed site | `(24.12415, 53.42829)`, 3.34 km from the intake, in **6 of 8 scenes** (max 33,600 m², NDCI max 0.625). Fixed-position recurrence is more typical of a shallow bottom, jetty, vessel or outfall than a drifting bloom; visual check requested |
| Revisit | Usable scenes were 2–5 days apart (median 5): the satellite leaves gaps that the in-situ and air layers are meant to cover (not built yet) |
| Response-chain drill (scenario) | Waiting for the in-situ alarm is too late for a 3 h approach (recommendation 222 min after the modelled front); pre-arming on the satellite ETA gives it 170 min before. The output is an **advisory recommendation** confirmed by sensors and the operator, never an automatic action |

The drill uses the real 2026-09-27 candidates but **assumed** current, sensor layout and latency; it shows the chain's logic, not a prediction about Mirfa.

## Repository structure

```
titan-edge-813/
├── README.md
├── requirements.txt
├── sites/mirfa.json                         ← site file: plant, intake, assumed sensor layout
├── notebooks/
│   ├── 02_mirfa_hab_monitor_v6.ipynb        ← MAIN: run-all monitor for Mirfa (series + recurring sites)
│   ├── 00_titan_edge_hab_digital_twin.ipynb ← earlier: Sentinel-2 + Tanager fusion exploration
│   ├── 01_titan_edge_tanager_water_quality.ipynb ← earlier: Tanager-only exploration
│   └── executed/                            ← executed copies (v4 Mirfa run, earlier runs)
├── src/
│   ├── mirfa_monitor/titan_hab_pipeline.py  ← real-data pipeline: fetch | series | s2 | tanager
│   ├── space_twin/                          ← response-chain simulation, drill, dashboard, loaders
│   └── titan_edge_core_sim.py               ← pipeline-security twin (shared drone kernel)
├── tests/                                   ← mirfa monitor smoke test, real-data reader tests
├── docs/
│   ├── real_run/mirfa/                      ← REAL Mirfa series, per-scene events, maps, drill
│   ├── real_run/earlier_exploration/        ← earlier Fujairah / Tanager runs and what they taught
│   ├── use_case_description.md (+ _ar)   ← the one-page description for submission
│   ├── validation/rak_2018.md            ← retrospective test on a documented bloom (to run)
│   ├── validity.md  judge_qa.md  tanager_availability.md  figures/
│   ├── architecture.md  spectral_indices_reference.md  tanager_data_guide.md
│   ├── stac_collection_map.md  where_to_put_real_values.md  sample_run/
└── assets/images/
```

## How to run

**1. The monitor (recommended): Google Colab, no uploads.** Open `notebooks/02_mirfa_hab_monitor_v6.ipynb`, then *Runtime → Run all*. It installs libraries, writes `titan_hab_pipeline.py`, downloads the latest cloud-filtered scenes from Earth Search, builds the series report and a downloadable zip. Edit cell 3 to change `INTAKE_LAT/LON`, `SERIES_DAYS` (60), `SERIES_CLOUD` (30), `MAX_SCENES` (8).

**2. The same from a terminal**

```bash
pip install numpy scipy tifffile pyproj pillow pystac-client odc-stac
cd src/mirfa_monitor
python3 titan_hab_pipeline.py series --out out_series --intake 24.1393236 53.4566472 --days 60 --max-cloud 30 --max-scenes 8
python3 titan_hab_pipeline.py fetch  --out out_mirfa  --intake 24.1393236 53.4566472 --max-cloud 30   # latest scene only
```

**3. Response-chain drill and simulation**

```bash
pip install -r requirements.txt
python3 src/space_twin/drill_mirfa.py                      # Mirfa drill, both variants -> docs/real_run/mirfa/drill/
cd src/space_twin && python3 main.py --bench               # synthetic demo scene
streamlit run dashboard.py                                  # interactive map, timeline, sensor plots
```

**4. Replay a documented bloom** (not yet run: needs internet; result unknown): see [docs/validation/rak_2018.md](docs/validation/rak_2018.md), which uses the new `--start/--end` options.

**5. Tests (repo root):** `python3 tests/test_mirfa_pipeline.py` (planted bloom found, clean-water control gives NONE), `python3 tests/test_real_data_paths.py`, `python3 tests/test_compare_tanager_s2.py`.

**6. Tanager over your area:** `python3 src/space_twin/find_tanager_scenes.py --bbox 53.36 24.04 53.54 24.20 --intake 24.1393236 53.4566472` (needs internet), then `compare_tanager_s2.py` if a scene overlaps. See [docs/tanager_availability.md](docs/tanager_availability.md).

## Replacing assumptions with real values

Open items, in priority order: (1) confirm the **intake coordinate** with the operator (EWEC / plant), then edit `INTAKE_LAT/LON` (notebook cell 3) and `sites/mirfa.json`; (2) obtain **in-situ chlorophyll-a** to calibrate the NDCI threshold (0.20 now); (3) real **sea-current** data (the drill's 0.15 m/s is an assumption); (4) inspect the recurring fixed site on the Google Maps link in `series_report.html`. See [docs/where_to_put_real_values.md](docs/where_to_put_real_values.md).

## Known issues and caveats

- **NDCI is a spectral proxy,** not a chlorophyll measurement; sun glint, shallow bottom and vessels can mimic it. Statuses are screening levels; an ALERT needs confirmation on ≥ 2 dates.
- **Mask sensitivity.** On 7 Oct one cluster qualifies with a 1 px shore buffer and none with 3 px. The first notebook version's `ALERT` came from shoreline pixels.
- **No hyperspectral result for Mirfa** (details and a same-scene Tanager-vs-Sentinel-2 comparison tool: `docs/tanager_availability.md`). The only UAE Tanager scene found (`20250511_074311_00_4001`, 53.63–53.89 E) does not overlap the Mirfa AOI (east edge 53.54 E). Earlier Tanager and Fujairah runs are in `docs/real_run/earlier_exploration/`.
- **Ground and air layers are simulations;** the coherence early warning depends on an unproven coastal precursor and arrived too late in the drill. The output is an advisory recommendation, not an automatic shutdown; a real plant needs independent interlocks and operator approval.
- **Reflectance offset.** The monitor detects per scene whether the provider already removed the 0.1 offset (`nir_dn_p2` in each event); the Fujairah-era code applied it blindly.

## Evaluation criteria (self-assessment)

| Criterion | Where this project stands |
|---|---|
| 🌍 Impact | Protects a named, operating desalination plant's intake; economic or population impact not quantified here |
| 💡 Creativity | Series persistence + recurring-site test to separate fixed features from drifting blooms; pre-arming on satellite ETA |
| 🔬 Validity | Real near-real-time data, one rule for all scenes, sensitivity tables, false alarms found and explained; **weak:** no in-situ data, uncalibrated threshold, assumed intake, simulated lower layers, and the detector has not yet been shown to flag a documented bloom (test prepared) |
| 🎯 Relevance | Fits the water-quality theme with a concrete operational use case |
| 🎤 Presentation | Interactive maps, per-scene reports, drill timelines |

## Key dates

The hackathon README supplied by the team lists **two PoC deadlines** (26 October 2026 in the phase table, 11 October 2026 in the key-dates list). Confirm the real one and the submission channel on spaceacademy-hackathons.space.gov.ae before submitting.

## FAQ

**Is any of this tested on real satellite data?** Yes, the space layer: 8 Sentinel-2 scenes over Mirfa. The sensor and drone layers are simulated.
**Does it close valves automatically?** No: it recommends, the subsea sensors confirm, and the operator decides.
**Is the 99th percentile your alert?** No: an alert needs a cluster of ≥ 18 pixels above 0.20 and confirmation on two dates (`docs/validity.md`).
**Is there a bloom at Mirfa?** Not confirmed. The data show repeated candidates, one of them at a fixed position; they need a visual check and in-situ data.
**Is the intake coordinate verified?** No: it is the tip of the long pipe seen in imagery, assumed to be the intake.
**Why does the drill say the in-situ alarm is too late?** With a 3 h approach, a coherence monitor with 3 h smoothing had not settled; launching on the satellite ETA fixes it in the model.

## License & attribution

Choose a licence for the code before publishing (the hackathon starter code is MIT). Notebook structure adapts the hackathon starter notebooks.

Contains modified Copernicus Sentinel-2 data (2026), accessed through the Earth Search STAC catalogue. Earlier explorations used Planet Tanager data (CC BY 4.0): *"Tanager STAC Data, available at www.planet.com/data/stac © [YEAR] Planet Labs PBC. All Rights Reserved."*

## Contact

Team name: Black Dragon
