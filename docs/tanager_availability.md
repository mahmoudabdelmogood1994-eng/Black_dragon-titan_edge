# Planet Tanager over Mirfa: what is known

**Decision rule used in this project:** Sentinel-2 is the base data source; Tanager is an extra experiment shown only where a scene actually overlaps the area.

| Question | Answer (from the executed notebooks) |
|---|---|
| Is there open Tanager coverage of the Mirfa AOI `[53.36, 24.04, 53.54, 24.20]`? | **None found.** The only UAE scene located, `20250511_074311_00_4001` (11 May 2025, bbox `[53.63, 23.99, 53.89, 24.19]`), starts at 53.63 E: about **9 km east** of the AOI's east edge and ~17 km from the assumed intake |
| How good is that scene? | 38.6 % valid pixels (cloud 40.6 %, no-data 20.8 %); NDCI max 0.144 (below the 0.20 threshold), status NONE |
| Other scenes tried | Five scenes in the Fujairah notebook all returned `intersects AOI: False` (e.g. `20250223_165546_32_4001` lies at about 88.5° W, 13° N) |
| Is coverage guaranteed? | No. The notebooks load a hand-picked list of scenes. Tanager open data comes in themed collections, not a repeat-pass service |

**How to look for coverage:** run `python3 src/space_twin/find_tanager_scenes.py --bbox 53.36 24.04 53.54 24.20 --intake 24.1393236 53.4566472` (or `find_scenes_over_aoi()` in notebook `00`), and keep only scenes whose `bbox` contains the intake. Report the scene ID and date.

**If a scene overlapping Mirfa is found:** run the same-scene comparison with Sentinel-2:

```bash
python3 src/mirfa_monitor/titan_hab_pipeline.py fetch --out s2_cmp --intake 24.1393236 53.4566472 --start <tanager date -1> --end <tanager date +1>
python3 src/space_twin/compare_tanager_s2.py --tanager-h5 X.h5 --tanager-json X.json --s2-dir <folder with S2_B03/B04/B05/B08.tif> --out cmp
```

It reports Pearson r, bias and RMSE between the two NDCIs on common pixels and how many pixels each flags above the threshold, and warns if the dates differ by more than a day. The script is tested only on stand-in files (r = 0.88, bias ≈ 0 where both sensors see the same synthetic scene); no real Tanager-vs-Sentinel-2 result exists yet.
