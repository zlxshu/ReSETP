# 09y Modern Battery Regime Stage 2

Evidence level: **PROBE / 非正式 T3**. Modern battery is diagnostic override only.

Verdict: `HALT_COLLECTION_COST`

## Plain Reading

280kWh 构造出现一个非退化混合实例，但 Stage 2 算法对比未能按 900s 单任务墙钟帽闭合；两条 worker 跑到约 1 小时仍未写出 raw_runs.csv。停止本次算法结论，只保留 headroom 与构造证据。

## Headroom

| instance | num_ev | route lower bound | EV share two-trip lb | ge 20% |
|---|---:|---:|---:|---|
| e2-vanilla-150c-01 | 10 | 20 | 1.0000 | True |
| e2-vanilla-200c-01 | 14 | 27 | 1.0000 | True |
| e2-multidepot-150c-01 | 10 | 20 | 1.0000 | True |
| e2-multidepot-200c-01 | 14 | 27 | 1.0000 | True |
| e2-threeshift-150c-01 | 10 | 20 | 1.0000 | True |

## Construction

| instance | EV share | charging_action_count | cost gap % | verdict |
|---|---:|---:|---:|---|
| e2-vanilla-150c-01 | 0.0952 | 2 | -0.4156 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH |
| e2-vanilla-200c-01 | 0.0345 | 1 | 0.0000 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH |
| e2-multidepot-150c-01 | 0.0909 | 2 | -0.4692 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH |
| e2-multidepot-200c-01 | 0.1379 | 4 | -1.3501 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH |
| e2-threeshift-150c-01 | 0.4545 | 10 | -6.7564 | X_SEARCH_MISSED_FEASIBLE_EV |

## Artifacts

- Data dir: `baselines/e2_alns/modern_battery_regime_stage2_data`
- Report: `baselines/e2_alns/modern_battery_regime_stage2.md`
- HEAD at run start: `402b2511345276b5fb887bb06587772ebeb9702f`
- Carbon price fixed at `0.05034`; protected solver semantics unchanged.
