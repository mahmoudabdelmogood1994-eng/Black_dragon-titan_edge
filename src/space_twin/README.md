# Titan-Edge Space Twin — Satellite → Subsea → Drone (hackathon PoC)

```
SPACE   satellite_analytics.py   GeoTIFF bands → NDWI mask → NDCI → hotspots (lat/lon, area, risk %)
GROUND  titan_ground_subsea.py   advection ETA → 6-sensor intake sim → phase-coherence alarm → 24 B trigger
AIR     titan_air_drone.py       avian obstacle-avoidance flight → lawn-mower hyper-spectral rescan → SAM → intake-protection recommendation
        pipeline.py / main.py    simulated-clock timeline, benchmarks      dashboard.py   Streamlit + Folium
```

## Run

```bash
pip install -r requirements.txt
python3 main.py --bench          # timeline.log, results.json, dashboard_map.html, ndci.png, subsea.png in ./output
streamlit run dashboard.py       # interactive: map + animated drone, timeline, sensor plots
```

## Using real satellite data

The two uploaded notebooks pull imagery from Planetary Computer (Sentinel-2 L2A) and Planet (Tanager). The build sandbox could not reach either host, so **no real imagery is bundled**; the logic is ported and the file readers are tested on small stand-in files (`python3 tests/test_real_data_paths.py`). On a machine with internet:

```bash
pip install pystac-client planetary-computer stackstac rioxarray requests h5py
# Sentinel-2: cloud-masked median composite -> data/fujairah_s2/S2_B03/B04/B05/B08.tif + meta.json
python3 data_sources.py sentinel2 --bbox 56.30 25.05 56.55 25.25 --time 2025-02-15/2025-03-15 --out data/fujairah_s2
python3 main.py --preset fujairah sentinel2_real --data-dir data/fujairah_s2

# Tanager hyperspectral (1-5 GB HDF5 + STAC JSON)
python3 data_sources.py tanager --item 20250223_165546_32_4001 --out data/tanager
python3 main.py --preset fujairah tanager --tanager-h5 data/tanager/<file>.h5 --tanager-json data/tanager/20250223_165546_32_4001.json
```

Or paste the same paths in the dashboard sidebar. Hand-downloaded Sentinel-2 files also work (file names containing `B03/B04/B05/B08`, optional `SCL`): integer DNs get `/10000 - 0.1` (processing baseline >= 04.00; the earlier version of this project omitted the offset) and SCL cloud/shadow/cirrus classes are masked.

Notebook settings carried over (presets): Fujairah AOI/intake `(25.17, 56.36)` (**illustrative, replace with the real intake**); NDCI threshold 0.25 (Sentinel-2) / 0.20 (Tanager); clusters of at least 8 connected pixels. The notebooks themselves state the thresholds must be calibrated against in-situ chlorophyll-a or a documented HAB event. Tanager scenes are placed from their STAC bbox (approximate), and a scene farther than 60 km from the intake is reported as "no threat" instead of being flown to. With Tanager, the drone's reference spectra become the scene's real clean-water and top-1 % NDCI spectra (bloom-vs-clean only, no species). The drone camera itself remains simulated.

## The index

`NDCI = (RedEdge − Red) / (RedEdge + Red)` with Sentinel-2 **B5 (705 nm)** and **B4 (665 nm)** (Mishra & Mishra, 2012). The brief lists B4/B8/B3 only: B8 (NIR) and B3 (green) are used here for the NDWI water mask, and **B5 must be added** to compute true NDCI. Landsat 8/9 has no red-edge band, so there the code computes a clearly labelled NIR-red proxy, *not* NDCI. The risk score (45 % severity, 25 % extent, 30 % proximity) is a heuristic, uncalibrated.

## What is real and what is not

| Item | Status |
|---|---|
| GeoTIFF reading, NDWI/NDCI, hotspot extraction | Real code; **tested only on the synthetic scene** |
| Satellite scene in `data/synthetic_scene/` | **Synthetic** (labelled in files, log, map and dashboard) |
| Ocean current, data latency (3 h), turbidity/viscosity responses, power, drone constants | **Assumed**, all in `config.py` / source |
| Phase-coherence early warning | Works only if intake water carries an advected, coherent precursor. The simulator injects one; the sensitivity table shows the benefit appears at ≈0.15 NTU and below that it alarms *later* than a plain threshold. Validate on real intake data |
| Spectral library and classification | Illustrative; "measurements" are generated from the same library, so accuracy proves nothing. Species confidence is low (0.42) in the demo and is reported as such |
| Response speed | No instant response is claimed. Trigger transmission is ~0.2 s; alarm→airborne ≈ 4 s (mostly assumed spin-up); satellite data latency, revisit (2–5 days observed) and bloom travel time dominate |
| Intake protection | Output is a **recommendation** to the operator, confirmed by subsea sensors and approved by the operator; the model never acts automatically |

Drone kernel and trigger framing are reused from `../titan_edge_core_sim.py`.
