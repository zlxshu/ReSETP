# Phase A ALNS Gate

Verdict: `ALNS_GATE_BLOCKED`

本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。

```json
{
  "algorithm_win_loss_claim": false,
  "block_reason": "Formal Goeke80 Phase-A run did not close; diagnostic and component gates were not started.",
  "failure_count": 1,
  "failure_sample": [
    {
      "reason": "Stopped at 5575/16000 evaluations.",
      "run_id": "A1_CARBON_GATE__formal_goeke80__threeshift__e2-threeshift-150c-01__alns_e2_carbon__seed1",
      "status": "HALT_RUNTIME_UNDER_EVAL"
    }
  ],
  "schema": "setp-e2-final-phase-a-decision.v1",
  "skipped_component_gate": true,
  "skipped_diagnostic_280": true,
  "verdict": "ALNS_GATE_BLOCKED"
}
```
