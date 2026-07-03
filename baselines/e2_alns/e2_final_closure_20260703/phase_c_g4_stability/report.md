# Phase C G4 Stability

Verdict: `HALT_G4_SUSPECT`

本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。

```json
{
  "direction_rule": "(a) >=6/9 instance gaps >=0 and (b) pooled gap >=0 are hard gates; (c) gaps below -2% become documented exceptions unless exception_count >=3/9.",
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
  "failure_count": 0,
  "failure_sample": [],
  "g4_instances": 9,
  "halt_reason": "G4_DIRECTION_RULE_FAILED",
  "hard_direction_violation_count": 0,
  "hard_direction_violation_sample": [],
  "liveness_diagnostic_count": 9,
  "liveness_diagnostic_sample": [
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "78",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-100c-01__LNS__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "48",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-100c-02__LNS__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "51",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-100c-02__LNS__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "48",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-100c-03__LNS__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "54",
      "route_count_unique": "3",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-100c-03__LNS__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "56",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-100c-03__LNS__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "26",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-150c-02__LNS__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "78",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-150c-03__LNS__seed3",
      "scope": "run",
      "seed": "3",
      "verdict": "BASELINE_LIVENESS_FAIL"
    },
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "25",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-200c-02__LNS__seed2",
      "scope": "run",
      "seed": "2",
      "verdict": "BASELINE_LIVENESS_FAIL"
    }
  ],
  "liveness_suspect_count": 0,
  "liveness_suspect_sample": [],
  "majority_nonnegative_rule_ok": false,
  "nonnegative_gap_instances": 5,
  "pooled_gap_fraction": 0.02085891464891202,
  "pooled_gap_rule_ok": true,
  "schema": "setp-e2-final-phase-c-decision.v1",
  "verdict": "HALT_G4_SUSPECT",
  "worst_instance_gap_fraction": -0.021702123576003575
}
```
