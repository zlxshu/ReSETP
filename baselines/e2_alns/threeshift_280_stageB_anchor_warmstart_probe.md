# 09y Stage B EV-Seeded Carbon-Regime Algorithm Comparison

Evidence level: **PROBE / 非正式 T3**. This is a gated diagnostic comparison, not formal T3 until user approves scenario formalization.

Verdict: `CARBON_REGIME_ALNS_WINS`

## Plain Reading

EV 在场时，alns_e2_carbon 对 LNS/GA/PSO/VNS 达到预注册显著胜出门槛；可进入正式 T3 候选。

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- Diagnostic battery override: `280.0` kWh
- HEAD: `73cd0fe80d62a30358d2242de445f3563490af52`

## Selected Instances

| instance | size | Stage A EV share | Stage A cost gap % | Stage A E_total gap % |
|---|---:|---:|---:|---:|
| e2-threeshift-100c-02 | 100 | 0.4286 | -4.9878 | -21.3974 |
| e2-threeshift-150c-01 | 150 | 0.4545 | -6.7564 | -28.4787 |
| e2-threeshift-200c-01 | 200 | 0.4074 | -5.5628 | -24.5370 |

## Collection

- Rows: `36/36`
- Collection failures: `0`
- Mean ALNS EV route share: `0.7355829036863519`
- EV retained: `True`
- Carbon ablation significant: `False` (p_less=`0.5625`)

## ALNS vs Baselines

| baseline | pairs | wins/ties/losses | mean gap % | p_less | significant win |
|---|---:|---:|---:|---:|---|
| GA | 6 | 6/0/0 | -20.4715 | 0.015625 | True |
| LNS | 6 | 6/0/0 | -18.9815 | 0.015625 | True |
| PSO | 6 | 6/0/0 | -20.4715 | 0.015625 | True |
| VNS | 6 | 6/0/0 | -20.4715 | 0.015625 | True |

## Artifacts

- Data dir: `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data`
- Report: `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe.md`
- HEAD at run start: `73cd0fe80d62a30358d2242de445f3563490af52`
- Carbon price fixed at `0.05034`; protected solver semantics unchanged.
- Raw rows: `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data/raw_runs.csv`
- Baseline pairs: `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data/paired_vs_baselines.csv`
- Ablation pairs: `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data/paired_vs_ablation.csv`
- Wall-clock caps: 100c=900s, 150c=1800s, 200c=2700s; rows record actual eval counts.
- Battery capacity was applied only with in-memory `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)`.
