# Phase A ALNS Gate

Verdict: `ALNS_GATE_READY`

本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。

```json
{
  "algorithm_win_loss_claim": false,
  "carbon_evidence": {
    "carbon_operators": "diagnostic evidence only; never changes T3 main variant in this run",
    "t3_main_variant_locked_by_user": "alns_e2_throughput"
  },
  "carbon_operator_policy": "DIAGNOSTIC_WALLCLOCK_NONBLOCKING",
  "component_decisions": [
    {
      "adopted": true,
      "component": "LOCAL_SEARCH",
      "mean_improvement_fraction": 0.011152094227722956,
      "worst_seed_improvement_fraction": -0.0006193831623859448
    },
    {
      "adopted": true,
      "component": "ROUTE_ELIMINATION",
      "mean_improvement_fraction": 0.00759838670430705,
      "worst_seed_improvement_fraction": -0.003378403659833712
    },
    {
      "adopted": false,
      "component": "RRT_TRUE_ACCEPTANCE",
      "mean_improvement_fraction": -0.16213691250168805,
      "worst_seed_improvement_fraction": -0.5523263679748186
    }
  ],
  "component_stack_results": [
    {
      "adopted": false,
      "components": [
        "LOCAL_SEARCH",
        "ROUTE_ELIMINATION"
      ],
      "mean_improvement_fraction": 0.0017380702209806181,
      "rows": 3,
      "worst_seed_improvement_fraction": -0.04540915048458177
    }
  ],
  "schema": "setp-e2-final-phase-a-decision.v1",
  "selected_components": [
    "LOCAL_SEARCH"
  ],
  "superseded_carbon_gate_archive": "baselines/e2_alns/e2_final_closure_20260703/phase_a_carbon_gate_superseded_under_eval",
  "t3_main_profile": {
    "base_variant": "alns_e2_throughput",
    "selected_components": [
      "LOCAL_SEARCH"
    ]
  },
  "t3_main_variant": "alns_e2_throughput",
  "verdict": "ALNS_GATE_READY"
}
```
