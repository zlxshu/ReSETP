# 09y EV-heavy Feasibility Stage 0

Evidence level: **PROBE / 非正式 T3**. This report does not claim formal T3 dominance.

Verdict: `Z_EV_PHYSICALLY_UNSUPPORTED_80KWH`

## Plain Reading

代表大实例多数 CV→EV 失败来自续航或时间窗，80kWh 物理/时间窗不支持 EV-heavy。

本阶段只做构造与 referee 复评，不做搜索；目标是判断 Goeke80 大实例 EV-heavy 是搜索没找到、经济性差，还是物理/时间窗不支持。

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- HEAD: `402b2511345276b5fb887bb06587772ebeb9702f`

## Instance Summary

| instance | EV share | charging_action_count | cost gap % | E_total gap % | accepted | verdict | dominant failure |
|---|---:|---:|---:|---:|---:|---|---|
| e2-vanilla-150c-01 | 0.0952 | 3 | -0.2043 | -1.9161 | 1 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH | CHARGING_TIME_WINDOW_DETOUR |
| e2-vanilla-200c-01 | 0.0690 | 4 | 0.6655 | -2.1093 | 1 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH | CHARGING_TIME_WINDOW_DETOUR |
| e2-multidepot-150c-01 | 0.0909 | 4 | 0.5739 | -2.9668 | 1 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH | STATION_OR_DEPOT_CAPACITY |
| e2-multidepot-200c-01 | 0.0690 | 3 | 0.0083 | -2.2416 | 1 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH | STATION_OR_DEPOT_CAPACITY |
| e2-threeshift-150c-01 | 0.0909 | 3 | 0.1152 | -2.2830 | 1 | Z_EV_PHYSICALLY_UNSUPPORTED_80KWH | STATION_OR_DEPOT_CAPACITY |

## Failure Reasons

| instance | failure_reason | count |
|---|---|---:|
| e2-multidepot-150c-01 | ACCEPTED | 1 |
| e2-multidepot-150c-01 | CHARGING_TIME_WINDOW_DETOUR | 7 |
| e2-multidepot-150c-01 | STATION_OR_DEPOT_CAPACITY | 12 |
| e2-multidepot-200c-01 | ACCEPTED | 1 |
| e2-multidepot-200c-01 | CHARGING_TIME_WINDOW_DETOUR | 11 |
| e2-multidepot-200c-01 | STATION_OR_DEPOT_CAPACITY | 15 |
| e2-threeshift-150c-01 | ACCEPTED | 1 |
| e2-threeshift-150c-01 | CHARGING_TIME_WINDOW_DETOUR | 2 |
| e2-threeshift-150c-01 | STATION_OR_DEPOT_CAPACITY | 17 |
| e2-vanilla-150c-01 | ACCEPTED | 1 |
| e2-vanilla-150c-01 | CHARGING_TIME_WINDOW_DETOUR | 14 |
| e2-vanilla-150c-01 | STATION_OR_DEPOT_CAPACITY | 5 |
| e2-vanilla-200c-01 | ACCEPTED | 1 |
| e2-vanilla-200c-01 | CHARGING_TIME_WINDOW_DETOUR | 18 |
| e2-vanilla-200c-01 | STATION_OR_DEPOT_CAPACITY | 8 |

## Artifacts

- Data dir: `baselines/e2_alns/ev_heavy_regime_stage0_data`
- Report: `baselines/e2_alns/ev_heavy_regime_stage0.md`
- HEAD at run start: `402b2511345276b5fb887bb06587772ebeb9702f`
- Carbon price fixed at `0.05034`; protected solver semantics unchanged.
