# S2 Full three-view China81 gate — v2 registered exception

Decision: PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT.

## Preserved v1 evidence

The original decision.json remains HALT_S2_VIEW_INFEASIBLE_OR_ERROR, and the original report.md and raw_runs.csv were not rewritten. This v2 file is a separate statistical closeout under approval-register entry S2-INFEASIBLE-UNIT-001.

## Ledger

All 810/810 new rows are present. There are 809 OK rows and one raw ERROR row classified as INFEASIBLE; there are zero duplicate keys and zero violation rows. HGS-F/cv_only is 405/405, HGS-E/naive_ev is 404/405, and the P3 read-only reuse ledger supplies HGS-M/mechanism_ev 405/405 and MV-HGS-SP 405/405.

The deterministic exception is cn-jjj-200c-01-V2-LOCATIONS, seed 2, HGS-E/naive_ev. The exact completion failed because C099 was late by 0.388 seconds (due l=49305.189, start=49305.576). No rerun, seed replacement, time-window relaxation, completioner change, or evaluator change was performed.

## Statistical rule

For this instance only, HGS-E Best/avg use the four feasible seeds: Best=9479.071097753, Avg=9486.113184235. The table note is: “HGS-E在1个算例的1个种子上无完整模型可行解（简化代理时间窗误差）”. The failed raw row remains in the ledger and the 404/405 feasibility rate is reported.

This case is retained as empirical evidence for why every candidate must be judged by the complete model: a simplified electric proxy can produce a route that fails the exact time-window referee by a small but decisive margin, while the complete MV-HGS-SP unit is feasible.

## Chain rule

S3 and later stages use this v2 decision. The same registered exception is recorded rather than filtered; a stage stops only if its single-arm failure rate exceeds 5 percent or another registered quality gate fails.

AppleDouble sidecars were observed and removed before this v2 hash refresh; the integrity flag is HASH_CONTAMINATED_APPLEDOUBLE. Raw data were not overwritten.
