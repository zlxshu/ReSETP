# Track21 Reclaim Closeout (Track22 Stage0)

Verdict: `MARGIN_REAL_PROVISIONAL_X86`

Plain conclusion: the fleet-policy bug was fixed and the main method is alive again, but the x86 25c/50c fair comparison does not support a paper claim that the main method beats every healthy baseline by at least 10%. This table is provisional because the baselines still carry the M1-proven decoder defect; it is not a paper-number table.

## Scope

- Included rows: 140 rows = 25c and 50c, 10 seeds, main method plus six healthy baselines.
- Partial 100c rows: 1 row(s), marked `PARTIAL_NOT_CONCLUSIVE` in `track21_reclaimed_fair_comparison_track22_closed.csv` and excluded from all claims.
- 100c official fair comparison status: `NOT_RUN_SUPERSEDED`; it belongs on M1 after the baseline decoder and repair bridge are reconciled.
- Worker/referee: py313 + NumPy 2.3.5 on x86; all percentages below are x86-relative only.

## Mean Costs

| Scale | Algorithm | n | Mean best_cost |
|---|---:|---:|---:|
| 25 | `winner_kernel_true_repair_adaptive_q` | 10 | 553.189266 |
| 25 | `GA` | 10 | 603.081852 |
| 25 | `VNS` | 10 | 595.142060 |
| 25 | `SA` | 10 | 640.281988 |
| 25 | `GWO` | 10 | 595.068384 |
| 25 | `ACO` | 10 | 594.059213 |
| 25 | `IWD` | 10 | 591.324412 |
| 50 | `winner_kernel_true_repair_adaptive_q` | 10 | 846.337858 |
| 50 | `GA` | 10 | 1158.076255 |
| 50 | `VNS` | 10 | 900.313814 |
| 50 | `SA` | 10 | 1036.937431 |
| 50 | `GWO` | 10 | 914.855570 |
| 50 | `ACO` | 10 | 901.797331 |
| 50 | `IWD` | 10 | 889.898642 |

## Main vs Baselines

| Baseline | 25c mean gain | 25c Wilcoxon p | 50c mean gain | 50c Wilcoxon p | Combined mean gain | Combined p |
|---|---:|---:|---:|---:|---:|---:|
| `GA` | 8.252% | 0.0009766 | 26.797% | 0.0009766 | 17.525% | 9.537e-07 |
| `VNS` | 7.046% | 0.0009766 | 5.994% | 0.0009766 | 6.520% | 4.422e-05 |
| `SA` | 13.140% | 0.0009766 | 18.215% | 0.0009766 | 15.677% | 9.537e-07 |
| `GWO` | 7.031% | 0.0009766 | 7.415% | 0.0009766 | 7.223% | 9.537e-07 |
| `ACO` | 6.880% | 0.0009766 | 6.101% | 0.001953 | 6.490% | 1.907e-06 |
| `IWD` | 6.439% | 0.0009766 | 4.898% | 0.004883 | 5.669% | 4.768e-06 |

Min combined gain vs healthy baselines: 5.669%. Max combined gain: 17.525%.

## 100c Partial Row

- One 100c main-method row landed before the Track21 runner exited: seed 901, best_cost 2500.518330, warm 4079.030056, evals 16000/16000, unique 45, updates 44, violations 0. It proves continued 100c liveness, not a fair 100c comparison.

## Caveat

本表基线仍带 M1 已证明的解码器缺陷，4-8% 是“对残障基线”的上界，不是论文数字。

## Historical Status

- Track17/Track19 winner-family rows: `SUPERSEDED_BY_TRACK21_FLEET_FIX`.
- Pilot16-Pilot25 DR negative rows: contaminated by the fleet-policy bug and require fixed-worker re-evaluation under Track22.
- Clean negative still standing: operator-selection DR is approximately a tuned ALNS controller, supported by Pilot07-Pilot10 plus the Cao source-code check.
- PSO is still transparently excluded from the healthy-baseline quantitative claim.

## Next

Track22 starts from this closeout: run the instrument health gate, re-measure clean destroy leverage, then only train learned-destroy or carbon timing if the cheap leverage gates justify it.
