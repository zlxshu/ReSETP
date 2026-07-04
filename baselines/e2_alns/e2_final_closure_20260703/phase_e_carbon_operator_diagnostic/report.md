# Phase E Carbon Operator Diagnostic

Verdict: `CARBON_OPS_WEAK`

本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。

```json
{
  "algorithm_win_loss_claim": false,
  "all_instance_summary": [
    {
      "carbon_best_cost_not_worse_all": false,
      "carbon_cost_carbon_all_lower": false,
      "carbon_cost_within_one_percent_all": false,
      "carbon_e_total_all_lower": false,
      "carbon_tier": "Tier1",
      "category": "threeshift",
      "instance": "e2-threeshift-150c-02",
      "mean_carbon_E_total": 1084.9123166212182,
      "mean_carbon_best_cost": 3537.2661730544046,
      "mean_carbon_cost_carbon": 54.61448601871213,
      "mean_right_E_total": 1056.7405903359452,
      "mean_right_best_cost": 3523.7568482306197,
      "mean_right_cost_carbon": 53.19632131751148,
      "pair_count": 3,
      "right_algorithm": "alns_e2_carbon_ablation"
    },
    {
      "carbon_best_cost_not_worse_all": false,
      "carbon_cost_carbon_all_lower": false,
      "carbon_cost_within_one_percent_all": false,
      "carbon_e_total_all_lower": false,
      "carbon_tier": "Tier1",
      "category": "threeshift",
      "instance": "e2-threeshift-200c-02",
      "mean_carbon_E_total": 1216.282688357112,
      "mean_carbon_best_cost": 4538.127565277276,
      "mean_carbon_cost_carbon": 61.22767053189702,
      "mean_right_E_total": 1120.670483542904,
      "mean_right_best_cost": 4374.864524563585,
      "mean_right_cost_carbon": 56.41455214154979,
      "pair_count": 3,
      "right_algorithm": "alns_e2_carbon_ablation"
    },
    {
      "carbon_best_cost_not_worse_all": false,
      "carbon_cost_carbon_all_lower": false,
      "carbon_cost_within_one_percent_all": false,
      "carbon_e_total_all_lower": false,
      "carbon_tier": "Tier1",
      "category": "threeshift",
      "instance": "e2-threeshift-200c-03",
      "mean_carbon_E_total": 1203.5494788064364,
      "mean_carbon_best_cost": 4528.753427348069,
      "mean_carbon_cost_carbon": 60.58668076311601,
      "mean_right_E_total": 1137.8774493151593,
      "mean_right_best_cost": 4481.788661743042,
      "mean_right_cost_carbon": 57.28075079852512,
      "pair_count": 3,
      "right_algorithm": "alns_e2_carbon_ablation"
    }
  ],
  "context_contrast": "alns_e2_carbon vs t3_main_alns (throughput+LOCAL_SEARCH)",
  "diagnostic_not_t3": true,
  "optional_failure_count": 0,
  "optional_failure_sample": [],
  "primary_contrast": "alns_e2_carbon vs alns_e2_carbon_ablation",
  "schema": "setp-e2-final-phase-e-carbon-decision.v1",
  "summary": [
    {
      "carbon_best_cost_not_worse_all": false,
      "carbon_cost_carbon_all_lower": false,
      "carbon_cost_within_one_percent_all": false,
      "carbon_e_total_all_lower": false,
      "carbon_tier": "Tier1",
      "category": "threeshift",
      "instance": "e2-threeshift-150c-02",
      "mean_carbon_E_total": 1084.9123166212182,
      "mean_carbon_best_cost": 3537.2661730544046,
      "mean_carbon_cost_carbon": 54.61448601871213,
      "mean_right_E_total": 1056.7405903359452,
      "mean_right_best_cost": 3523.7568482306197,
      "mean_right_cost_carbon": 53.19632131751148,
      "pair_count": 3,
      "right_algorithm": "alns_e2_carbon_ablation"
    },
    {
      "carbon_best_cost_not_worse_all": false,
      "carbon_cost_carbon_all_lower": false,
      "carbon_cost_within_one_percent_all": false,
      "carbon_e_total_all_lower": false,
      "carbon_tier": "Tier1",
      "category": "threeshift",
      "instance": "e2-threeshift-200c-02",
      "mean_carbon_E_total": 1216.282688357112,
      "mean_carbon_best_cost": 4538.127565277276,
      "mean_carbon_cost_carbon": 61.22767053189702,
      "mean_right_E_total": 1120.670483542904,
      "mean_right_best_cost": 4374.864524563585,
      "mean_right_cost_carbon": 56.41455214154979,
      "pair_count": 3,
      "right_algorithm": "alns_e2_carbon_ablation"
    },
    {
      "carbon_best_cost_not_worse_all": false,
      "carbon_cost_carbon_all_lower": false,
      "carbon_cost_within_one_percent_all": false,
      "carbon_e_total_all_lower": false,
      "carbon_tier": "Tier1",
      "category": "threeshift",
      "instance": "e2-threeshift-200c-03",
      "mean_carbon_E_total": 1203.5494788064364,
      "mean_carbon_best_cost": 4528.753427348069,
      "mean_carbon_cost_carbon": 60.58668076311601,
      "mean_right_E_total": 1137.8774493151593,
      "mean_right_best_cost": 4481.788661743042,
      "mean_right_cost_carbon": 57.28075079852512,
      "pair_count": 3,
      "right_algorithm": "alns_e2_carbon_ablation"
    }
  ],
  "t3_main_profile_locked": {
    "base_variant": "alns_e2_throughput",
    "selected_components": [
      "LOCAL_SEARCH"
    ]
  },
  "tier1_failure_count": 0,
  "tier1_failure_sample": [],
  "tier1_instance_count": 3,
  "tier1_ready": true,
  "user_decision_if_dominant": "If CARBON_OPS_DOMINANT, user decides whether to promote carbon or add a carbon-aware variant column.",
  "verdict": "CARBON_OPS_WEAK"
}
```
