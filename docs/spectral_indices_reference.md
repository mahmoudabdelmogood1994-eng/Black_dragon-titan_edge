# Spectral indices & decision quantities used in this repository

Band choices follow the notebooks (Tanager wavelength in nm; Sentinel-2 band in brackets). Thresholds are **uncalibrated defaults** taken from the notebooks; calibrate them against in-situ chlorophyll-a or a documented bloom event before relying on any alert.

## Water and chlorophyll indices

| Index | Formula | Bands | Interpretation | Code |
|---|---|---|---|---|
| NDWI | (Green − NIR) / (Green + NIR) | Tanager 560 / 860 · S2 B3 / B8 | > threshold = open water (mask). Default 0.0 (S2), 0.1 (Tanager preset) | `satellite_analytics.compute_indices` |
| NDCI | (RedEdge − Red) / (RedEdge + Red) | Tanager 708 / 665 · S2 **B5** / B4 | Chlorophyll / algal biomass proxy. Notebook alert thresholds: 0.25 (S2), 0.20 (Tanager) | same |
| Turbidity proxy | (Red − Green) / (Red + Green) | Tanager 665 / 560 | > 0 = sediment-laden water (notebook 01) | notebook 01 |

NDCI follows Mishra & Mishra (2012). **Landsat 8/9 has no red-edge band**, so true NDCI cannot be computed there; the code then uses a clearly labelled NIR-red proxy.

## Sentinel-2 reflectance scaling

For Level-2A processing baseline ≥ 04.00, `reflectance = DN / 10000 − 0.1`. Because NDCI is a ratio, omitting the offset shifts the index. `satellite_analytics.SCALE` applies it to integer files; float GeoTIFFs written by `data_sources.py` are already scaled. Cloud/shadow/cirrus pixels are masked with the SCL classes (0, 1, 3, 8, 9, 10, 11).

## Hotspot extraction and risk score

1. Water mask (NDWI), optionally eroded by `coast_buffer_px` (preset: 5 px = 100 m) to drop land-adjacent mixed pixels → index > threshold → 3×3 binary opening (drops speckle).
2. Connected components; keep clusters with ≥ `min_cluster_px` (8) pixels and ≥ `min_area_km2`.
3. Risk % = 100 × (0.45 · severity + 0.25 · extent + 0.30 · proximity), with severity = clip((mean NDCI − thr)/0.30), extent = clip(area/5 km²), proximity = clip(1 − distance/30 km). **Heuristic, not calibrated.**

## Subsea intake quantities (simulation)

| Quantity | Definition |
|---|---|
| ETA | (distance to bloom edge ÷ current component toward the intake) − satellite data latency |
| Phase-coherence R | Causal narrow-band phase per sensor (periods 45/55/65 min), aligned by the known along-flow delays, mean resultant length across the 6 sensors, 3 h smoothing. Independent noise gives R ≈ 0.4–0.8 over 24 h; alarm at R ≥ 0.85 for 20 min (set above noise-only maxima) |
| Turbidity / viscosity response | Assumed demo relations (viscosity ratio = 1 + 0.8·c + 2.0·c², c from the NDCI excess); not calibrations |

## Drone rescan

Spectral Angle Mapper (SAM) against a reference library. With a Tanager scene the library is two real spectra (clean water vs top-1 % NDCI patch), so only *bloom vs clean* can be separated. Without one, an illustrative pigment-feature library is used and species accuracy proves nothing.
