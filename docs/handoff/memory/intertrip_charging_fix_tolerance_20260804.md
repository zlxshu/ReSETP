# T12 容差回归（2026-08-05）

`FACT` T12 在 `_check_charging_trip_overlap` 中复用 `FEASIBILITY_TOL=1e-9`，公共站 2 项门禁恢复；精细充电 2 项和搜索 3 项仍失败，定向结果 `36 passed / 5 failed`，状态 `HALT_REGRESSION_FAILED`，未跑全量。

`FACT` 三个原缺陷阳性仍命中 `CHARGING_TRIP_OVERLAP`，重叠秒数为 `6563.0712245500035`、`6365.9078330282355`、`6239.742124296223`；T10 18/18 与 T9 20/20 仍合法。`paper_claim_allowed=false`。

权威产物：`docs/handoff/intertrip_charging_fix_tolerance_20260804/`。
