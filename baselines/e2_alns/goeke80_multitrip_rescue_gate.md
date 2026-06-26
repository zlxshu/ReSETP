# 09s Goeke-80 Multi-Trip Rescue Gate

Verdict: `RESCUE_SMOKE_COMPLETE`

Phase 2 algorithm smoke completed with SMOKE_OK; inspect paired ALNS/LNS rows before formal T3.

## Plain Reading

大白话：轻量算法 smoke 已经跑完，34/34 行零违约，没有 collection failure。早期信号是“语义卡点解除了、可以继续救”，不是“算法已经赢了”：17 个代表实例里 ALNS 在两个 10c 小实例赢 LNS，其余 15 个完全持平，基本说明小预算下两者大多还停在同一个 warm start。下一步若要判断算法对比能否真正救回来，必须做更高预算、多 seed 的正式 T3 预演。

## Phase 0 Parameter Audit

- Q_capacity: `3650.0` kg
- B_battery_kwh: `80.0` kWh
- v_speed_ms: `25.0`
- carbon_price: `0.05034`
- TeX table has B=80: `True`
- 280kWh retained only as diagnostic text: `True`

## Phase 1 Warm-Start Gate

- Rows: `69`
- OK: `69`
- Failures: `0`

| category | size | ok/instances | mean EV route share | mean CV physical | mean EV physical | mean max trips/vehicle |
|---|---:|---:|---:|---:|---:|---:|
| multidepot | 10 | 3/3 | 0.333 | 1.00 | 1.00 | 2.00 |
| multidepot | 15 | 3/3 | 0.222 | 1.67 | 0.67 | 1.67 |
| multidepot | 20 | 3/3 | 0.200 | 2.00 | 1.00 | 2.00 |
| multidepot | 25 | 3/3 | 0.200 | 2.00 | 1.00 | 2.00 |
| multidepot | 50 | 3/3 | 0.111 | 4.00 | 1.00 | 2.00 |
| multidepot | 75 | 3/3 | 0.082 | 5.67 | 1.00 | 2.00 |
| multidepot | 100 | 3/3 | 0.068 | 7.00 | 1.00 | 2.00 |
| multidepot | 150 | 3/3 | 0.046 | 10.00 | 1.00 | 2.67 |
| multidepot | 200 | 3/3 | 0.036 | 13.33 | 1.00 | 2.33 |
| threeshift | 50 | 3/3 | 0.120 | 4.00 | 1.00 | 2.00 |
| threeshift | 75 | 3/3 | 0.088 | 5.67 | 1.00 | 2.00 |
| threeshift | 100 | 3/3 | 0.068 | 7.00 | 1.00 | 2.00 |
| threeshift | 150 | 3/3 | 0.048 | 10.00 | 1.00 | 2.33 |
| threeshift | 200 | 3/3 | 0.036 | 13.33 | 1.00 | 2.33 |
| vanilla | 10 | 3/3 | 0.333 | 1.00 | 1.00 | 2.00 |
| vanilla | 15 | 3/3 | 0.194 | 1.67 | 0.67 | 2.00 |
| vanilla | 20 | 3/3 | 0.250 | 2.00 | 1.00 | 2.00 |
| vanilla | 25 | 3/3 | 0.233 | 2.00 | 1.00 | 2.00 |
| vanilla | 50 | 3/3 | 0.125 | 4.00 | 1.00 | 2.00 |
| vanilla | 75 | 3/3 | 0.086 | 5.67 | 1.00 | 2.00 |
| vanilla | 100 | 3/3 | 0.070 | 7.00 | 1.00 | 2.00 |
| vanilla | 150 | 3/3 | 0.048 | 10.00 | 1.00 | 2.00 |
| vanilla | 200 | 3/3 | 0.037 | 13.33 | 1.00 | 2.00 |

## Phase 2 Algorithm Smoke

- Gate: `SMOKE_OK`
- Rows: `34`
- Elapsed seconds: `243.57811562500137`
- OK rows: `34/34`
- Paired wins: `ALNS 2 / LNS 0 / tie 15`
- Interpretation: smoke confirms zero-violation comparability, but most pairs still return identical costs at `eval_budget=300`; this is not yet evidence that ALNS beats LNS/GLNS.

## Artifacts

- Data dir: `baselines/e2_alns/goeke80_multitrip_rescue_gate_data`
- Report: `baselines/e2_alns/goeke80_multitrip_rescue_gate.md`
- HEAD: `927af04de6079aecc2b4642481243d704eb64c14`
- Artifact commit hash: `8853d6aa5c1f042439529c477d902415a070860d`
