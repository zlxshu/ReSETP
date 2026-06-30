# 09x Carbon-Aware ALNS Operator Probe

Evidence level: **PROBE / 非正式 T3**. This report does not claim formal algorithm dominance.

Verdict: `WEAK_CARBON_SIGNAL`

## Plain Reading

09x PROBE 未证明 carbon-aware 算子在同一 referee 下稳定优于消融/throughput/LNS；不把它升级为正式 T3 主张。

本步只检验 `alns_e2_carbon` 是否通过搜索算子读取两层碳与分时电碳信号；`cost.py`、`check.py`、`evaluation.py`、默认参数和最终 referee 均保持不变。
Raw rows include `cost_carbon`, `E_total`, `E_cv_direct`, `E_ev_indirect`, `low_carbon_charging_share`, and carbon-operator attempt/improvement counts.

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- 09s warm start rows OK: `True` with `69` rows

## Carbon Comparison Summary

| comparison | pairs | mean gap % left-right | mean E_total delta kg | left/tie/right | Wilcoxon p | method |
|---|---:|---:|---:|---:|---:|---|
| carbon_vs_ablation | 23 | 1.8304 | 4.1531 | 0/21/2 | 1 | scipy_wilcoxon_less |
| carbon_vs_lns | 23 | -2.0534 | -6.2292 | 2/20/1 | 0.25 | scipy_wilcoxon_less |
| carbon_vs_throughput | 23 | -0.0110 | -0.0925 | 1/22/0 | 0.5 | scipy_wilcoxon_less |

## Stage Decision

- Stage B recommended: `False`
- Stage B reason: Stage B not triggered by the preregistered Stage A rule.

## Artifacts

- Data dir: `baselines/e2_alns/carbon_aware_operator_probe_data`
- Raw rows: `baselines/e2_alns/carbon_aware_operator_probe_data/raw_runs.csv`
- Carbon pair summary: `baselines/e2_alns/carbon_aware_operator_probe_data/carbon_pair_summary.csv`
- Carbon comparison summary: `baselines/e2_alns/carbon_aware_operator_probe_data/carbon_comparison_summary.csv`
- Stage decision: `baselines/e2_alns/carbon_aware_operator_probe_data/stage_decision.json`
- Artifact hashes: `baselines/e2_alns/carbon_aware_operator_probe_data/artifact_hashes.json`
- Report: `baselines/e2_alns/carbon_aware_operator_probe.md`
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
