# ALNS Crush V2 Summary

## Task1: Fair SA Baseline

- Prompt1 Phase2 SA was weaker by configuration: Phase0 used `eval_budget=16000,max_runtime=900s`; Prompt1 Phase2 used `eval_budget=4000,max_runtime=600s`.
- Phase0 SA seed1 on `100-01-24h` was exactly reproduced: `5331.576889799002`.
- Fair SA baseline is therefore `scikit-opt-SA, eval_budget=16000, max_runtime=900s`, same instance bundles and warm seed path.

| instance | fair SA mean | fair SA best | fair SA std | mean routes | zero violations |
|---|---:|---:|---:|---:|---:|
| 100-01-24h | 5346.986857 | 5166.498854 | 82.283460 | 32.700 | 10/10 |
| L-main | 8319.837849 | 8180.722121 | 113.675307 | 64.900 | 10/10 |

## Task2: True Headroom

| instance | 80k winner true-best | fair SA mean | gap vs fair SA | weak lower bound | verdict |
|---|---:|---:|---:|---:|---|
| 100-01-24h | 4779.053444 | 5346.986857 | -10.622% | 3980.111560 | headroom supports crush |
| L-main | 8333.507479 | 8319.837849 | +0.164% | 6910.662684 | headroom thin or not proven |

The lower bound is only a weak capacity-plus-distance relaxation and is not a proof of optimality.

## Task3: Lean ALNS vs Fair SA

Wilcoxon is paired by instance and seed against Task1 fair SA rows, not against Prompt1 Phase2 SA or a moving best denominator.

| instance | variant | mean | best | std | wins | p-value | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| 100-01-24h | winner_kernel_only | 4878.331796 | 4779.053444 | 95.279550 | 10/10 | 0.0009765625 | crush |
| 100-01-24h | winner_kernel_route_elimination | 4893.225562 | 4779.051859 | 104.859701 | 10/10 | 0.0009765625 | strict failure because std gate misses 1.25x SA |
| L-main | winner_kernel_only | 8351.639755 | 8138.269147 | 127.302744 | 5/10 | 0.65234375 | failure |
| L-main | winner_kernel_route_elimination | 8424.043977 | 8225.616335 | 117.566588 | 2/10 | 0.9755859375 | failure |

V2 does not support the claim that route elimination is the crush driver. The strongest measured V2 layer is `winner_kernel_only` on `100-01-24h`; route elimination is not retained as the default winner configuration.

## Task4: Public Winner Operator Module

- Module: `setp_solver.search.winner_operators`
- Operator base id: `winner_kernel_v1`
- Public API: `WinnerKernelConfig`, `winner_variant_flags`, `run_winner_kernel`, `run_winner_kernel_plus_route_elimination`, `write_winner_manifest`
- Manifest: `solver/reports/alns_crush_v2/winner_operator_manifest.json`
- Default flags disable Prompt1 harmful add-ons: true-cost repair, route elimination, true acceptance, local search, and adaptive q are all off by default.

## Integrity Notes

- All V2 experiment artifacts were written under `solver/reports/alns_crush_v2/`.
- No formal E1-E7 runner was invoked.
- Violation counts are zero for all reported rows: Task1 `20/20`, Task2 `6/6`, Task3 `40/40`.
- Current dirty worktree already had diffs in protected model-adjacent files before V2 task runs (`cost.py`, `alns_wouda.py`, `candidates.py`, `evaluation.py` in preflight). V2 did not revert or reinterpret those changes.
- `PRIMARY_ALGORITHM` remains `ALNS-Wouda`.
