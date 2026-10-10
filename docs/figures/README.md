# Figures for the report and slides

| File | What it shows | Source |
|---|---|---|
| `mirfa_series.png` | Mirfa series: NDCI 99th percentile vs the 0.20 threshold, and qualifying clusters per scene | `docs/real_run/mirfa/scenes/*/titan_edge_event.json` |
| `mirfa_event_excerpt_2026-10-07.json` | Real event record (latest scene): status, data quality, NDCI statistics, cluster counts, parameters | `docs/real_run/mirfa/single_scene_2026-10-07/` |
| `tanager_uae_2x2_panel.png` | Tanager 2×2 panel (true colour, NDCI, NDWI, turbidity proxy), UAE scene `20250511_074311_00_4001` | notebook 01, executed |
| `tanager_uae_spectra.png` | Tanager mean spectra, clean water vs top-1 % NDCI (notebook output, 708 nm red-edge region) | notebook 01, executed |

**Not produced here:** the HyperCoast interactive explorer is a live widget in notebook 01; take a screenshot after running that notebook. The Tanager scene does not cover Mirfa (it lies east of the AOI), so the two Tanager figures illustrate the sensor, not the Mirfa result.
