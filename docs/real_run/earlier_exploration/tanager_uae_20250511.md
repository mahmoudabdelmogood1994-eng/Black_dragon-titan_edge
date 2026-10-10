# Real-data run: Planet Tanager, UAE coast, 11 May 2025

Scene `20250511_074311_00_4001`, bbox `[53.63, 23.99, 53.89, 24.19]` (inside the notebook\x27s Gulf/UAE search box), ortho SR HDF5, 426 bands, ~30 m. Executed notebook: `notebooks/executed/01_titan_edge_tanager_water_quality_EXECUTED.ipynb`. Figures: `assets/images/tanager_uae_20250511_*.png`. Event log: `tanager_event_20250511.json`.

| Quantity | Value |
|---|---|
| Valid pixels | 38.6 % (cloud 40.6 %, no-data 20.8 %) |
| NDCI over water | median −0.101, p99 0.054, max 0.144 |
| Threshold / min cluster | 0.20 / 8 px |
| Qualifying clusters | **0** → `anomaly_status: NONE`, next action `standby` |

Reading: no chlorophyll anomaly in the valid part of this scene. The panel shows a shallow coastal area with straight man-made channels and basins; low, uniform NDCI is consistent with that, but without in-situ data this is a spectral proxy statement only. 40 % of the scene is cloud, so absence of a bloom is not shown for the masked area. The "bloom-candidate" spectrum in the notebook is simply the top 1 % of NDCI in a scene with no anomaly, so it is not evidence of a bloom.

**Not the same place as the Fujairah Sentinel-2 run** (Gulf of Oman, 56.3–56.55 E): the two results cannot be fused. The nearest desalination site found while building this repo, Mirfa IWPP (~24.12 N, 53.45 E, approximate, from a power-plant database), lies about 18 km west of this scene\x27s western edge, so the scene does not cover it. The notebook\x27s last cell is a copy of the Fujairah export cell with a stray indent and undefined variables (`event` exists, `r03`, `s2_items`, `UTM_EPSG` do not); use the export cell given in the chat instead.
