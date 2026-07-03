# Phase C G4 Stability

Verdict: `HALT_G4_SUSPECT`

本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。

```json
{
  "completed_rows_before_stop": 6,
  "direction_rule": ">=6/9 gap>=0, pooled gap>=0, no instance below -2%",
  "early_stop": true,
  "early_stop_reason": "Complete instance e2-threeshift-100c-01 already violated the pre-registered G4 rule: no instance may have ALNS worse than LNS by more than 2.0%; LNS seed1 also failed liveness route_count diversity.",
  "failure_count": 0,
  "failure_sample": [],
  "g4_instances": 1,
  "hard_direction_violation_count": 1,
  "hard_direction_violation_sample": [
    {
      "category": "threeshift",
      "direction": "LNS_LOWER",
      "gap_fraction": -0.021702123576003575,
      "instance": "e2-threeshift-100c-01",
      "mean_alns": 2745.3297058863445,
      "mean_lns": 2687.0157578586277
    }
  ],
  "liveness_suspect_count": 1,
  "liveness_suspect_sample": [
    {
      "algorithm": "LNS",
      "flags": "LOW_ROUTE_COUNT_DIVERSITY",
      "native_best_updates": "78",
      "route_count_unique": "4",
      "run_id": "C_G4_STABILITY__formal_goeke80__threeshift__e2-threeshift-100c-01__LNS__seed1",
      "scope": "run",
      "seed": "1",
      "verdict": "BASELINE_LIVENESS_FAIL"
    }
  ],
  "nonnegative_gap_instances": 0,
  "planned_rows": 54,
  "pooled_gap_fraction": -0.021702123576003575,
  "schema": "setp-e2-final-phase-c-decision.v1",
  "stopped_before_phase_d": true,
  "verdict": "HALT_G4_SUSPECT",
  "worst_instance_gap_fraction": -0.021702123576003575
}
```
