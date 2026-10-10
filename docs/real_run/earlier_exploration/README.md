# Real-data run: Sentinel-2, Fujairah, Feb–Mar 2025

Inputs: median composite of 7 Sentinel-2 L2A scenes (21 Feb – 8 Mar 2025, cloud 1.9–26 %, tiles T40RDN/T40RDP), SCL-masked, 20 m, EPSG:32640, AOI `[56.30, 25.05, 56.55, 25.25]` (1114 × 1266 px, 74.5 % water). Executed notebook: `notebooks/executed/00_titan_edge_hab_digital_twin_EXECUTED.ipynb`. Intake `(25.17, 56.36)` is still the **illustrative** notebook value.

## Findings

| Question | Result |
|---|---|
| Did Planet Tanager cover the AOI? | **No.** All 5 scenes tried returned `intersects AOI: False` (the downloaded scene lies at lon −88.5, lat 13.1). Nothing from Tanager is fused into any alert here |
| Notebook decision | `ALERT` because the single maximum pixel (NDCI 0.787) exceeded 0.25 |
| Is that alert credible? | **No.** 99th percentile NDCI is 0.164; 0.197 % of water pixels exceed 0.25; the 152 pixels above 0.5 sit at a median 20 m from land (shoreline mixed pixels, not an open-water bloom) |
| With a 100 m coastal buffer | max NDCI 0.79 → 0.51; share above 0.25 drops 0.197 % → 0.047 % (4×) |
| Pipeline (clusters ≥ 8 px, threshold 0.25) | **0 hotspots → NO_THREAT** (`pipeline_thr0.25/`) |
| Lower thresholds | 0.15 → 17 tiny clusters (≤ 0.03 km²); 0.10 with ≥ 0.25 km² → 1 cluster, 0.48 km², mean NDCI 0.17, ~10 km south of the illustrative intake near the shoreline (`pipeline_thr0.10_whatif_timeline.log`). The assumed current does not carry it to the intake, so also NO_THREAT |
| Larger elevated area | A broad region of NDCI ≈ 0.10–0.17 continues past the **south edge** of the AOI; its extent and nature (bloom, turbid shallows, seabed) are unknown. Extend the bbox south and check against in-situ data |

## Caveats

* Composite of several dates and two tiles: horizontal striping and seams are visible; analyse one clear date (e.g. 3 Mar 2025, cloud 1.9 %) for anything quantitative.
* NDCI is a proxy. No in-situ chlorophyll-a was used, so no bloom is *confirmed* or *ruled out*; only "no coherent ≥ 0.25 NDCI cluster ≥ 8 px was found".
* The event timestamp in `notebook_event.json` (2026-10-08) is processing time; the imagery is historical (replay).
* The notebook's printed text "Planet Tanager & Sentinel-2 Fusion Engine" is hard-coded and wrong when Tanager is outside the AOI. Replace the decision cell with a cluster rule (see the project chat/README snippet): label connected components above the threshold, keep those ≥ 8 px, and print `event["sources"]`.
