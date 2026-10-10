# Validation plan: show that the detector can see a real bloom

Status: **nothing here has been run yet.** All real results so far are "no confirmed bloom", so the detector has not been shown to flag a documented one.

| # | Test | Data | Status | What counts as success |
|---|---|---|---|---|
| 1 | Ras Al Khaimah bloom, January 2018 (ministry announcement 24 Jan 2018, fishermen's report 22 Jan) | Sentinel-2, `--start/--end`; see `rak_2018.md` | Prepared, needs internet | Candidates near the reported area on dates around 22–24 Jan and not on clear dates before/after. The bloom was described as limited and low-biomass, so a miss is not conclusive |
| 2 | Same event, compare with the ministry's satellite imagery | Ministry release | Manual | Spatial agreement with the reported patch |
| 3 | 2008–2009 Gulf of Oman / Gulf bloom (documented as large, lasting nearly a year) | ENVISAT MERIS (before Sentinel-2); needs a separate reader and ESA archive access | **Not possible with the current pipeline** | Would show the index works for a large, harmful event; the pipeline does not read MERIS |
| 4 | Continue the Mirfa series through autumn–winter | Sentinel-2, run weekly | Ongoing | Any confirmed event, and the false-alarm rate over a season |
| 5 | Match-ups with in-situ chlorophyll-a | Operator / national monitoring | Needs data | Local NDCI–chlorophyll relation and a calibrated threshold |

**Metrics to report for tests 1 and 4:** hit (a candidate within the reported area/date window), false alarms per scene on dates with no event, and the fraction of scenes that were usable (cloud, mask).

**What to say if the result is negative:** the detector did not flag a low-biomass patch at 20 m resolution under this rule; explore the sensitivity table in each event JSON before concluding anything, and do not change the threshold to make the test pass.
