# 09x Carbon-Aware ALNS Operator Probe

Evidence level: **PROBE / 非正式 T3**. This report does not claim formal algorithm dominance.

Verdict: `PHASE0_OK`

## Plain Reading

只完成Phase0。

本步只检验 `alns_e2_carbon` 是否通过搜索算子读取两层碳与分时电碳信号；`cost.py`、`check.py`、`evaluation.py`、默认参数和最终 referee 均保持不变。

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- 09s warm start rows OK: `True` with `69` rows

## Carbon Comparison Summary

| comparison | pairs | mean gap % left-right | mean E_total delta kg | left/tie/right | Wilcoxon p | method |
|---|---:|---:|---:|---:|---:|---|
|  | 0 | nan | nan | 0/0/0 | nan |  |

## Stage Decision

- Stage B recommended: `None`
- Stage B reason: 

## Artifacts

- Data dir: `baselines/e2_alns/carbon_aware_operator_probe_phase0_data`
- Raw rows: `baselines/e2_alns/carbon_aware_operator_probe_phase0_data/raw_runs.csv`
- Carbon pair summary: `baselines/e2_alns/carbon_aware_operator_probe_phase0_data/carbon_pair_summary.csv`
- Carbon comparison summary: `baselines/e2_alns/carbon_aware_operator_probe_phase0_data/carbon_comparison_summary.csv`
- Stage decision: `baselines/e2_alns/carbon_aware_operator_probe_phase0_data/stage_decision.json`
- Artifact hashes: `baselines/e2_alns/carbon_aware_operator_probe_phase0_data/artifact_hashes.json`
- Report: `baselines/e2_alns/carbon_aware_operator_probe_phase0.md`
- HEAD at run start: `6fbf6103e6f73b39ee12d52abd9aad3b9fc62051`
- Artifact commit hash: `pending`

## Collection Failures

| scenario | instance | algorithm | seed | status | bucket |
|---|---|---|---:|---|---|
|  |  |  |  | none |  |

## Interpretation Rules

- `alns_e2_carbon_ablation` keeps the same carbon-aware operator registry but sets operator-level carbon bias to zero.
- All reported costs and emissions are replayed through the unchanged evaluator/checker after each worker returns a solution.
- `PASS_CARBON_AWARE_OPERATORS` is only a probe signal; formal T3 requires a separate locked experiment.
