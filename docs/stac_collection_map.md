# STAC collections and scene IDs used here

| Source | Catalogue | Used for |
|---|---|---|
| Planet Tanager (hyperspectral) | `https://www.planet.com/data/stac/tanager-core-imagery/coastal-water-bodies` | Water quality, chlorophyll, HAB (hackathon Themes 5 and 6) |
| Sentinel-2 L2A | `https://planetarycomputer.microsoft.com/api/stac/v1` (collection `sentinel-2-l2a`) | Wide-area macro-sensing, cloud-masked composite |

Item JSON pattern used by `data_sources.fetch_tanager`: `{collection URL}/{item_id}/{item_id}.json`.

## Scene IDs referenced in the notebooks

| Scene ID | Notebook 00 (HAB digital twin) | Notebook 01 (water quality) |
|---|---|---|
| `20250223_165546_32_4001` | ✓ | ✓ (default) |
| `20250225_153627_16_4001` | ✓ | |
| `20250302_030003_92_4001` | ✓ | |
| `20250311_061550_53_4001` | ✓ | |
| `20250406_170447_47_4001` | ✓ | ✓ |
| `20250511_074311_00_4001` | | ✓ |

Notebook 00 uses the AOI "Gulf of Oman coast near Fujairah" with an **illustrative** intake at (25.17, 56.36); notebook 01 searches the box `[51.0, 22.5, 57.0, 26.5]` (Arabian Gulf and UAE coast).

> Scene footprints were **not verified** while building this repository (the build sandbox could not reach planet.com). Not every listed scene necessarily covers a given intake; the pipeline reports "no threat" for any hotspot farther than `max_range_km` (60 km) from the intake instead of flying to it.
