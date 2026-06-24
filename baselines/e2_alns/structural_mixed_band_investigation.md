# 09m Structural Mixed-Band Investigation

Status: read-only structural audit; no parameter/default/model semantics changed.

## Plain-Language Verdict

The 75-200 customer range does not look like a single clean battery-capacity problem. Existing 09l screen rows show some near-balanced pockets, but failures alternate between CV-side collapse and EV-heavy collapse depending on family, size, and facility layout. The strongest next hypotheses are therefore operational/geographic: station/depot coverage, public-charging availability, route eligibility, and EV fleet/charger capacity limits.

## Scope

- Instance structure audited: 69 / 69 E2 instances.
- Joined 09l Stage A rows restricted to 75-200 customers.
- 09l rows are screen evidence only: `-01`, seed 1, eval_budget 1000. They rank hypotheses but do not certify a paper setting.

## Best 75-200 Battery Pockets From Existing 09l Screen

| battery | pass rows | pass rate | mean EV route share | min-max | counts |
|---:|---:|---:|---:|---:|---|
| 81.0 | 7/12 | 0.583 | 0.406 | 0.000-0.769 | allCV=5, balanced=7, EVheavy=0, allEV=0; EVroutes>manifestEV=7 |
| 89.0 | 6/12 | 0.500 | 0.431 | 0.000-0.846 | allCV=4, balanced=6, EVheavy=2, allEV=0; EVroutes>manifestEV=8 |
| 82.6 | 6/12 | 0.500 | 0.316 | 0.000-0.778 | allCV=6, balanced=6, EVheavy=0, allEV=0; EVroutes>manifestEV=6 |
| 60.0 | 6/12 | 0.500 | 0.235 | 0.000-0.696 | allCV=6, balanced=6, EVheavy=0, allEV=0; EVroutes>manifestEV=6 |
| 100.0 | 4/12 | 0.333 | 0.525 | 0.000-0.910 | allCV=4, balanced=4, EVheavy=4, allEV=0; EVroutes>manifestEV=8 |
| 113.0 | 3/12 | 0.250 | 0.778 | 0.000-1.000 | allCV=1, balanced=3, EVheavy=6, allEV=2; EVroutes>manifestEV=11 |
| 150.0 | 2/12 | 0.167 | 0.739 | 0.000-0.981 | allCV=2, balanced=2, EVheavy=8, allEV=0; EVroutes>manifestEV=10 |
| 194.0 | 2/12 | 0.167 | 0.743 | 0.000-0.981 | allCV=2, balanced=2, EVheavy=8, allEV=0; EVroutes>manifestEV=10 |

## Geography And Facility Structure, 75-200

| family | size | depots | stations | stations/customer | bbox km | depot p90 km | station p90 km | nearest-customer p50 km | pairwise p90 km |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| multidepot | 75 | 2.0 | 8.0 | 0.107 | 229.7 | 71.8 | 46.3 | 7.9 | 130.0 |
| multidepot | 100 | 2.0 | 11.0 | 0.110 | 256.3 | 83.0 | 46.7 | 7.3 | 133.7 |
| multidepot | 150 | 2.0 | 16.0 | 0.107 | 243.4 | 77.4 | 33.1 | 5.6 | 120.8 |
| multidepot | 200 | 2.0 | 21.0 | 0.105 | 265.3 | 77.1 | 30.6 | 4.8 | 124.2 |
| threeshift | 75 | 2.0 | 8.0 | 0.107 | 247.1 | 64.1 | 52.1 | 7.2 | 127.4 |
| threeshift | 100 | 2.0 | 11.0 | 0.110 | 279.5 | 79.6 | 46.1 | 7.6 | 129.8 |
| threeshift | 150 | 2.0 | 16.0 | 0.107 | 253.7 | 80.7 | 37.8 | 5.7 | 121.7 |
| threeshift | 200 | 2.0 | 21.0 | 0.105 | 275.0 | 74.8 | 30.0 | 4.8 | 122.7 |
| vanilla | 75 | 1.0 | 8.0 | 0.107 | 229.7 | 91.0 | 46.3 | 7.9 | 130.0 |
| vanilla | 100 | 1.0 | 11.0 | 0.110 | 256.3 | 90.1 | 46.7 | 7.3 | 133.7 |
| vanilla | 150 | 1.0 | 16.0 | 0.107 | 243.4 | 88.2 | 33.1 | 5.6 | 120.8 |
| vanilla | 200 | 1.0 | 21.0 | 0.105 | 265.3 | 90.7 | 30.6 | 4.8 | 124.2 |

## Critical Fleet-Count Finding

The current search/checker uses an unbounded fleet policy: `infer_fleet_limits()` returns 1,000,000 CV/EV as a diagnostic default, and `check.py` explicitly says fleet count is no longer a hard feasibility cap. Existing instance metadata still records values such as `num_cv=10` and `num_ev=10`, but the optimizer can return dozens of EV routes. This is probably the cleanest operational explanation for the 280kWh EV-dominant result: modern EVs are cheap enough, and the model is effectively allowed to buy/use as many EV routes as fixed cost permits.

This does not mean we should silently re-enable a hard cap. It means the next diagnostic should treat EV availability/capital budget as a first-class, source-backed scenario variable, then test whether realistic EV fleet limits keep 75-200 customer instances in the 20%-80% practical mixed band.

## Strongest Correlation Clues

| battery | metric | n | Pearson vs EV route share |
|---:|---|---:|---:|
| 89.0 | roundtrip_depot_empty_kwh_p90 | 12 | 0.620 |
| 89.0 | nearest_depot_p90_km | 12 | 0.620 |
| 194.0 | pairwise_p90_km | 12 | 0.547 |
| 200.0 | pairwise_p90_km | 12 | 0.547 |
| 210.0 | pairwise_p90_km | 12 | 0.547 |
| 150.0 | pairwise_p90_km | 12 | 0.542 |
| 81.0 | station_per_customer | 12 | 0.542 |
| 194.0 | nearest_customer_p50_km | 12 | 0.536 |
| 200.0 | nearest_customer_p50_km | 12 | 0.536 |
| 210.0 | nearest_customer_p50_km | 12 | 0.536 |
| 150.0 | nearest_customer_p50_km | 12 | 0.524 |
| 194.0 | size | 12 | -0.521 |

## What This Means

1. Size alone is not the right explanatory variable. The 75, 100, 150, and 200 groups share similar geographic envelopes, while customer density increases and station coverage improves as size grows.
2. Some batteries create mixed pockets, but the same battery can be all-CV in one family-size cell and EV-heavy in another. That is exactly the pattern expected when geography/facility design or operational rules, not battery alone, is controlling the split.
3. The next honest route is not to tune another unsupported battery value. The next gate should test source-backed operational mechanisms that can make CV and EV specialize naturally: charger capacity, public-station scarcity/eligibility, EV fleet-count or capital limits, and long-route EV eligibility.

## Next Hypotheses To Test

| priority | hypothesis | why it is plausible | next check |
|---:|---|---|---|
| 1 | EV fleet/capital limit | Current checker/search is unbounded while real fleets have finite EV stock; 09h/09l EV-heavy solutions often use far more EV routes than `num_ev` metadata. | Evidence matrix for mixed-fleet papers and real fleet adoption ratios, then in-memory `SearchPolicy(max_ev=...)` gate. |
| 2 | Charger capacity / depot charging capacity | `check.py` enforces station slot capacity, but generated depots have very large charger counts; this may make overnight/depot charging too easy. | Audit actual charging concurrency and run source-backed depot/public charger-cap scenarios. |
| 3 | Public station availability and placement | Station/customer ratio stays about 0.105 and nearest-station p90 improves at larger sizes, which may push large cases EV-heavy. | In-memory station-scarcity or station-eligibility counterfactual, justified by infrastructure evidence. |
| 4 | Long-route EV eligibility | Cross-city route lengths may make some routes operationally unsuitable for EV despite theoretical charging feasibility. | Label route distance/duration bands and test EV-forbidden long-route policy as a diagnostic, not default. |
| 5 | Economic proxies | Public electricity price, occupancy fee, fixed cost, and depot electricity price can alter EV/CV tradeoffs. | Reuse 09f/09h fixed replay, then only reopt source-backed near-flips. |

## Files

- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/instance_structure.csv`
- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/instance_structure_by_family_size.csv`
- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/stage_a_75_200_joined.csv`
- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/candidate_75_200_summary.csv`
- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/family_size_75_200_summary.csv`
- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/driver_correlations.csv`
- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/failure_examples_75_200.csv`
- `/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/structural_mixed_band_investigation_data/metadata.json`
