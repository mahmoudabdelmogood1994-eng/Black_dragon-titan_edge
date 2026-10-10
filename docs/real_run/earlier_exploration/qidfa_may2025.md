# Real-data run: Sentinel-2, Qidfa (Fujairah F1/F2 area), 1–21 May 2025

AOI `[56.25, 25.18, 56.50, 25.42]`, 8 scenes (1.0–23.8 % cloud), median composite dated 2025-05-07, EPSG:32640. "Intake" set to `(25.30194, 56.37278)`, which is the F2 **plant site** (Wikipedia), not an offshore intake.

| Check | Result |
|---|---|
| Old notebook rule (max pixel) | `ALERT` (max NDCI 0.444); only 45 px (0.0087 % of water) exceed 0.25, median 20 m from land |
| Cluster rule (≥ 8 px above 0.25) | 0 clusters → `NORMAL` |
| After 100 m coast buffer | max NDCI 0.153; no pixel above 0.25 |
| Water mask | 30.6 % of AOI, **speckled**: only 0.9 % of the AOI survives a 100 m erosion |
| Open-sea reflectance (offshore sample) | green 0.094, red 0.093, red-edge 0.096, **NIR 0.094** (medians): a flat spectrum |
| Is the "intake" point in the sea? | **No**, the pixel at that coordinate is land |
| Tanager overlap | None (same five scenes, all outside the AOI) |

**Interpretation.** Clear open water has near-zero NIR reflectance (a few thousandths). A flat ~0.09 in all four bands, including NIR, means the sea pixels are contaminated (likely aerosol/dust, sun glint, or an atmospheric-correction failure; cause not diagnosed here) or the composite mixes poor dates. NDWI is ≈ 0 there, so the NDWI>0 water mask is unreliable and the NDCI map over water is not trustworthy. `NORMAL` therefore means "no usable evidence of a bloom", not "no bloom". Check per-scene sea NIR and use only clean dates; consider the SCL water class (6) for the mask.
