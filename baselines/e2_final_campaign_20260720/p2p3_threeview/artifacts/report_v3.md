# S5-REV-V3 unified artifacts

Decision: PASS_S5_ARTIFACTS; revision: S5-REV-V3.

This was a deterministic presentation repair over the sealed S5 v2 materialization. No solver was run, no raw CSV, witness, evaluator, protected TeX, or statistical input was modified. All v2 files and the v2 artifact hash manifest are preserved.

## Repairs

Table 5 now has the requested columns: VCGP Best error, MDFIHA Best error, MDFIHA-ETGA Best error, PyVRP-HGS Best/avg error, and MV-HGS-SP Best/avg error, all relative to BKS; BKS remains the reference-value column. Its final Avg row uses P1 decision.json avg_row_error_pct for the Best columns and sealed P1 raw_runs.csv for the ten-seed average columns. Row-wise minimum errors are bold.

Table 6 bolds only the minimum cost in every seed and Min/Avg/Max row; CPU values are not bold. The China81 summary independently bolds the minimum Best and avg cost in every row.

For Table 4, the route-level definition is maximum actual load divided by vehicle capacity. The total row therefore uses the additive capacity-weighted quantity sum(route maximum actual loads) divided by sum(route capacities): 12223.000 kg / 12675.000 kg = 96.433925 percent. Only the total-row 装载率 cell differs from table4_route_details_v2.csv.

The registered S2 exception S2-INFEASIBLE-UNIT-001 remains unchanged; HGS-E is feasible on 404/405 units and the affected instance uses four feasible seeds for Best/avg. No failed row was rerun or replaced.

Figure 4, its curve data, and the paired-test CSV are copied byte-for-byte from v2 because none of the four requested repairs changes their values.

Integrity flag: HASH_CONTAMINATED_APPLEDOUBLE; AppleDouble sidecars were removed before hash refresh.
