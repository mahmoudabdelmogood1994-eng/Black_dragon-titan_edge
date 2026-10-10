> **Update:** the project's main site is now **Mirfa IWPP** (`sites/mirfa.json`, `notebooks/02_mirfa_hab_monitor_v5.ipynb`). The intake `(24.1393236, 53.4566472)` is the pipe tip *assumed* to be the intake; confirm it with the operator. The Fujairah examples below are kept as a worked example of the same procedure.

# Real coordinates and numbers: what is verified, what you must obtain, where it goes

## 1. Verified public data (plant sites and capacities)

Plant coordinates are **plant sites, not seawater intake heads** (the intake is offshore of the plant).

| Site | Coordinates (lat, lon) | Water capacity | Source |
|---|---|---|---|
| Fujairah F2 IWPP, Qidfa | 25.30194, 56.37278 | 591,500 m³/day (Wikipedia); 130 MIGD net (operator FAPCO) | Wikipedia "Fujairah F2 IWPP"; fapco.ae |
| Fujairah F1 IWPP, Qidfa | 25.31444, 56.37278 | 100 MIGD ≈ 455,000 m³/day | Wikipedia "Fujairah F1 IWPP"; accgroup.com |
| Mirfa IWPP, Abu Dhabi (approx.) | 24.121, 53.447 | 52.5 MIGD (≈ 238,665 m³/day) | WRI Global Power Plant Database via inzonex.co.uk; GDF Suez press release |

Both Fujairah plants lie **north of the earlier test box** (`[56.30, 25.05, 56.55, 25.25]`) and Mirfa lies ~18 km **west of** the Tanager scene `20250511_074311_00_4001`. Check the details on the operator's own pages before quoting them in a submission.

## 2. Values you must obtain (nothing here can be looked up generically)

| Value | How to get it | Goes in |
|---|---|---|
| **Intake-head coordinates** | Google Earth/Maps satellite view of the plant: find the offshore intake channel or pipe head, right-click → copy lat, lon. Confirm with the operator or the plant's environmental impact assessment | `intake_latlon` in `site.json`; notebook `INTAKE_LATLON` |
| **Sea-surface current** (east u, north v, m/s) | Copernicus Marine Service surface-current product for the plant's grid cell around the scene date (`copernicusmarine` Python package), or an ADCP at the plant | `current_uv_ms` in `site.json` (currently an unmeasured assumption) |
| **Satellite data latency** (hours) | Time from acquisition to availability: inspect the STAC item `properties` for a creation/publication time (field name not verified here); otherwise keep the 3 h assumption and say so | `data_latency_h` |
| **Intake turbidity alarm limit** (NTU) | The plant's SWRO pre-treatment design/alarm limits | `turbidity_limit_ntu` |
| **NDCI threshold** | Calibrate against in-situ chlorophyll-a (operator or national monitoring) or a documented bloom event | `ndci_threshold`; notebook `HAB_THRESHOLD` |

## 3. Where to put them

**A. Python pipeline: one file.** Copy `docs/site_template.json` to `site.json`, fill every `null`, then:

```bash
cd src/space_twin
python3 main.py --preset sentinel2_real --site ../../site.json --data-dir <folder with S2_B03/B04/B05/B08.tif>
```

The program refuses to start while any value is `null`. Sensor positions are converted from your lat/lon into metres from the plant automatically. Add more `intake_latlon` pairs for more sensors; the default demo uses six.

**B. Notebook 00, cell 3 (Theme / AOI setup):**

```python
bbox = [56.25, 25.18, 56.50, 25.42]      # Qidfa example: contains F1/F2 (25.30N, 56.37E) + sea
time_range = "2025-05-01/2025-05-21"     # window with cloud-free scenes
UTM_EPSG = 32640                         # = 32600 + zone, zone = floor((lon + 180) / 6) + 1  (Qidfa: zone 40; Mirfa: zone 39 -> 32639)
INTAKE_LATLON = (..., ...)               # YOUR real intake head
HAB_THRESHOLD = 0.25                     # your calibrated value
```

**C. Tanager:** a scene only counts if it overlaps your `bbox`. Run `find_scenes_over_aoi()` in notebook 00 (or notebook 01's search box) after changing the bbox; if none overlaps, either move the bbox to where a scene exists or do not claim a Tanager result.

## 4. Order of work

1. Pick one plant (section 1). 2. Get its real intake coordinates (section 2). 3. Set cell 3 (section 3B) and re-run notebook 00. 4. Fill `site.json`, run the pipeline (3A). 5. Quote only numbers that came out of those runs, and say which are assumptions.
