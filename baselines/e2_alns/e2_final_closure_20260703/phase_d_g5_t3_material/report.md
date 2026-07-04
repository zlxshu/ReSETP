# Phase D G5 T3/F2 Material

Verdict: `HALT_T3_HOMOGENIZATION`

本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。

```json
{
  "algorithm_win_loss_claim": false,
  "baseline_set": [
    "GA",
    "LNS",
    "PSO",
    "VNS",
    "ACO",
    "GA-VNS",
    "GWO",
    "IWD"
  ],
  "documented_exception_count": 2,
  "documented_instance_exceptions": [
    {
      "category": "threeshift",
      "direction": "LNS_LOWER",
      "evidence_source": "phase_a_prime_route_elimination_retest/decision.json;phase_a_prime_route_elimination_retest/variant_vs_lns.csv;phase_c_g4_stability/g4_gap_by_instance.csv",
      "exception_note": "ALNS+LOCAL_SEARCH is 2.17% worse than LNS on 100c-01; route-elimination-only improved the mean gap but was inconclusive and did not justify a T3 profile switch.",
      "exception_reason": "ALNS_WORSE_THAN_LNS_BY_MORE_THAN_TWO_PERCENT",
      "exception_status": "DOCUMENTED_INSTANCE_EXCEPTION",
      "gap_fraction": -0.021702123576003575,
      "instance": "e2-threeshift-100c-01",
      "mean_alns": 2745.3297058863445,
      "mean_lns": 2687.0157578586277,
      "mechanism_explanation": "LOCAL_SEARCH does not change route count; this instance appears to need route compression. ROUTE_ELIMINATION-only evidence is retained as diagnostic support, not as the selected main profile."
    },
    {
      "category": "threeshift",
      "direction": "LNS_LOWER",
      "evidence_source": "phase_c_g4_stability/g4_gap_by_instance.csv",
      "exception_note": "ALNS is worse than LNS by more than 2% on this instance under the revised G4 rule.",
      "exception_reason": "ALNS_WORSE_THAN_LNS_BY_MORE_THAN_TWO_PERCENT",
      "exception_status": "DOCUMENTED_INSTANCE_EXCEPTION",
      "gap_fraction": -0.020537221759442725,
      "instance": "e2-threeshift-100c-02",
      "mean_alns": 2535.087836309658,
      "mean_lns": 2484.0719008161955,
      "mechanism_explanation": "Record as a documented instance exception; do not change the T3 main profile from alns_e2_throughput+LOCAL_SEARCH."
    }
  ],
  "exact_identity_suspect_count": 3,
  "exact_identity_suspect_sample": [
    {
      "algorithm": "GA|GA-VNS|PSO",
      "best_cost": "2894.1244745663066",
      "category": "multidepot",
      "flags": "exact_cost_and_signature_repeated_within_instance",
      "instance": "e2-multidepot-100c-01",
      "run_count": 3,
      "scope": "phase_d_instance_exact_identity",
      "seed": "1|3",
      "signature_prefix": "b80ab177a9dac862",
      "verdict": "CROSS_ALGO_OR_SEED_EXACT_IDENTITY_SUSPECT"
    },
    {
      "algorithm": "GA|GA-VNS|LNS|VNS|t3_main_alns",
      "best_cost": "371.9993673208387",
      "category": "multidepot",
      "flags": "exact_cost_and_signature_repeated_within_instance",
      "instance": "e2-multidepot-10c-01",
      "run_count": 11,
      "scope": "phase_d_instance_exact_identity",
      "seed": "1|2|3",
      "signature_prefix": "af2703e54ec34282",
      "verdict": "CROSS_ALGO_OR_SEED_EXACT_IDENTITY_SUSPECT"
    },
    {
      "algorithm": "GA|GWO|PSO|t3_main_alns",
      "best_cost": "387.9007343319535",
      "category": "multidepot",
      "flags": "exact_cost_and_signature_repeated_within_instance",
      "instance": "e2-multidepot-10c-01",
      "run_count": 9,
      "scope": "phase_d_instance_exact_identity",
      "seed": "1|2|3",
      "signature_prefix": "e912d411804e6ecf",
      "verdict": "CROSS_ALGO_OR_SEED_EXACT_IDENTITY_SUSPECT"
    }
  ],
  "expected_instance_count": 23,
  "failure_count": 0,
  "failure_sample": [],
  "freeze_reason": "Phase D was stopped after a pre-registered homogeneity red line was observed in partial raw_runs.csv.",
  "homogeneity_suspect_count": 6,
  "homogeneity_suspect_sample": [
    {
      "algorithm": "GA|GA-VNS|LNS|VNS|t3_main_alns",
      "flags": "shared_signature=af2703e54ec342829fe77a826735a17f481316c42fe3c058bfcf010a64da731d",
      "run_id": "",
      "scope": "cross_algorithm",
      "seed": "",
      "verdict": "CROSS_ALGO_IDENTITY_SUSPECT"
    },
    {
      "algorithm": "GA|GA-VNS|PSO",
      "flags": "shared_signature=b80ab177a9dac86214e7bfd23c63ecc053b649735bed7fe417a0edfbdf32b820",
      "run_id": "",
      "scope": "cross_algorithm",
      "seed": "",
      "verdict": "CROSS_ALGO_IDENTITY_SUSPECT"
    },
    {
      "algorithm": "GA|GWO|PSO|t3_main_alns",
      "flags": "shared_signature=e912d411804e6ecf628a63c74039a895c2c57ece27acdb7f93879d282d362c2b",
      "run_id": "",
      "scope": "cross_algorithm",
      "seed": "",
      "verdict": "CROSS_ALGO_IDENTITY_SUSPECT"
    },
    {
      "algorithm": "GA|GA-VNS|PSO",
      "best_cost": "2894.1244745663066",
      "category": "multidepot",
      "flags": "exact_cost_and_signature_repeated_within_instance",
      "instance": "e2-multidepot-100c-01",
      "run_count": 3,
      "scope": "phase_d_instance_exact_identity",
      "seed": "1|3",
      "signature_prefix": "b80ab177a9dac862",
      "verdict": "CROSS_ALGO_OR_SEED_EXACT_IDENTITY_SUSPECT"
    },
    {
      "algorithm": "GA|GA-VNS|LNS|VNS|t3_main_alns",
      "best_cost": "371.9993673208387",
      "category": "multidepot",
      "flags": "exact_cost_and_signature_repeated_within_instance",
      "instance": "e2-multidepot-10c-01",
      "run_count": 11,
      "scope": "phase_d_instance_exact_identity",
      "seed": "1|2|3",
      "signature_prefix": "af2703e54ec34282",
      "verdict": "CROSS_ALGO_OR_SEED_EXACT_IDENTITY_SUSPECT"
    },
    {
      "algorithm": "GA|GWO|PSO|t3_main_alns",
      "best_cost": "387.9007343319535",
      "category": "multidepot",
      "flags": "exact_cost_and_signature_repeated_within_instance",
      "instance": "e2-multidepot-10c-01",
      "run_count": 9,
      "scope": "phase_d_instance_exact_identity",
      "seed": "1|2|3",
      "signature_prefix": "e912d411804e6ecf",
      "verdict": "CROSS_ALGO_OR_SEED_EXACT_IDENTITY_SUSPECT"
    }
  ],
  "material_rows": 54,
  "observed_instance_count": 3,
  "record_only_freeze": true,
  "schema": "setp-e2-final-phase-d-decision.v1",
  "suspect_count": 51,
  "suspect_sample": [
    {
      "algorithm": "ACO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "19",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__ACO__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "ACO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "23",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__ACO__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "ACO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "24",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__ACO__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GA",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "3",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GA__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GA",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "4",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GA__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GA",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "6",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GA__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GA-VNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "3",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GA-VNS__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GA-VNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "3",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GA-VNS__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GA-VNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "6",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GA-VNS__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GWO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "4",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GWO__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "GWO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "12",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__GWO__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "IWD",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "18",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__IWD__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "IWD",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "25",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__IWD__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "IWD",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "28",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__IWD__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "67",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__LNS__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "44",
      "route_count_unique": "3",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__LNS__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "67",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__LNS__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "PSO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "2",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__PSO__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "PSO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "2",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__PSO__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "PSO",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "2",
      "route_count_unique": "2",
      "run_id": "D_G5_TIER1__formal_goeke80__multidepot__e2-multidepot-100c-01__PSO__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    }
  ],
  "tier": "Tier1",
  "verdict": "HALT_T3_HOMOGENIZATION"
}
```
