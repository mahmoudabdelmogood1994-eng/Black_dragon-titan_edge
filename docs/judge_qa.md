# Hard questions from the judges, with honest answers

Fill the bracketed items; nothing in brackets is claimed by this project.

1. **What actually works today?** The space layer: a Sentinel-2 monitor on real data over Mirfa (8 scenes, 9 Sep–7 Oct 2026, one rule for every scene, tests included). The subsea sensors and the drone are simulations; no hardware exists.
2. **Have you shown it detects a real bloom?** Not yet. All real runs gave "no confirmed bloom". A replay of the January 2018 Ras Al Khaimah bloom is prepared (`docs/validation/rak_2018.md`) but has not been run, and that bloom was low-biomass. We will report the result either way.
3. **Isn't your "99th percentile" just the brightest pixels?** We do not alert on it: the p99 was below 0.20 in all 8 scenes. An alert needs a cluster of ≥ 18 pixels above 0.20, then confirmation on two dates. A clean-water control test gives status NONE (`docs/validity.md`).
4. **Does NDCI work in shallow, saline Gulf water?** It was proposed for turbid productive coastal waters, so local behaviour is unproven. We use it as a screening index, mask shallows/shore and report mask sensitivity, and we plan calibration against in-situ chlorophyll-a (`docs/validity.md`).
5. **A satellite passes every few days; where is the real-time protection?** Over Mirfa the usable passes were 2–5 days apart (median 5). That gap is why the design has in-situ sensors and a drone between passes. Those layers are not built yet, and we do not claim zero latency: in the drill the in-situ monitor needed hours to settle, so the model launches on the satellite ETA instead.
6. **Will it shut my plant automatically?** No. The output is a recommendation that must be confirmed by the subsea sensors and approved by the operator; automatic action is outside the scope.
7. **Who operates it and what does it cost?** Operator: [the plant's environment/operations team, with our monitor delivering alerts]. Cost: not estimated; the space layer uses free Sentinel-2 data, and the cost of subsea sensors, drone and operations is [to be quoted by suppliers].
8. **How is this different from the national red-tide monitoring?** The ministry already uses satellite monitoring at national scale. Titan-Edge targets one intake, with a plant-specific alert rule, persistence checks and a response plan; it is complementary, and we would validate against the ministry's records.
9. **Is your intake coordinate real?** It is the tip of a long pipe visible in imagery, assumed to be the intake; to be confirmed with the operator [EWEC / plant].
10. **Why is there no Tanager result for Mirfa?** The only UAE Tanager scene found lies about 9 km east of the Mirfa AOI and is 40 % cloud (`docs/tanager_availability.md`). Sentinel-2 is the base; Tanager is a documented side experiment.

## Facts to verify before quoting

* **Desalination share of drinking water.** Sources disagree for the UAE: about 42 % (Arab Center Washington DC), about 80 % (Majalla), and "more than 90 %" (a minister's older statement); Kuwait is about 90 %. Abu Dhabi's total water supply was reported as 30 % desalination, 60 % groundwater, 10 % recycled (a 2022 forum). **Do not use "90 % of drinking water" for the UAE.** Safer: "Desalination is the main drinking-water source in the Gulf, and the share varies by country and source."
* **Plant capacity and coordinates** (Mirfa 52.5 MIGD; plant point approximate): confirm on the operator's pages.
* **References:** NDCI (Mishra & Mishra 2012) and NDWI (McFeeters 1996) citations are in `docs/validity.md`.
