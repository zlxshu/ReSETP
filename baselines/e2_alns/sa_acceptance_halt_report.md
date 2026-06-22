# E2 ALNS SA Acceptance Gate HALT

Conclusion: `HALT_HARD_TIMEOUT_NOT_PROMOTED`. The generated runner verdict is
`HALT_INFEASIBLE` because 35 rows did not return a finite solution before the
hard timeout. The underlying row status is hard timeout, not model infeasibility:
all 100 rows that returned a solution had zero violations.

Run commit: `8ae7727ee6fd2b6d68b75a631e0476107e60cb32`

Environment:

- Python: `/opt/anaconda3/bin/python3.13`
- NumPy: `2.3.5`
- `PYTHONHASHSEED=0`
- Gate output: `baselines/e2_alns/sa_raw_runs.csv`
- Runtime policy: wall-clock cap by instance size plus `15s` hard-timeout grace;
  `16000` evals are a diagnostic backstop only.

Command:

```bash
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m setp_solver.search.e2_alns_sa_acceptance --seeds 1-5 --eval-budget 16000 --workers 3 --output-dir baselines/e2_alns
```

Stdout:

```text
GATE E2_ALNS_SA_ACCEPTANCE {"gate": "HALT_INFEASIBLE", "manifest": "baselines/e2_alns/sa_manifest.json", "elapsed_seconds": 25232.211484875006}
```

## Row Status

| status | rows |
|---|---:|
| OK | 74 |
| HALT_RUNTIME_UNDER_EVAL | 26 |
| HALT_HARD_TIMEOUT | 35 |

`HALT_RUNTIME_UNDER_EVAL` rows returned feasible incumbent solutions before
wall-clock expiry and are counted as gate-OK diagnostic rows. `HALT_HARD_TIMEOUT`
rows returned no finite solution to the parent process before `runtime_cap+15s`
and therefore block the gate.

By algorithm:

| algorithm | OK-gate rows | hard-timeout rows | zero-violation returned rows |
|---|---:|---:|---:|
| LNS | 35 | 10 | 35/35 |
| alns_sa_autofit | 31 | 14 | 31/31 |
| alns_sa_lns_cooling | 34 | 11 | 34/34 |

Hard timeouts occurred in the 200c cross-checks and the largest threeshift ALNS
rows:

| instance | algorithm | hard-timeout rows |
|---|---:|---:|
| e2-multidepot-200c-01 | LNS | 5 |
| e2-multidepot-200c-01 | alns_sa_autofit | 5 |
| e2-multidepot-200c-01 | alns_sa_lns_cooling | 5 |
| e2-vanilla-200c-01 | LNS | 5 |
| e2-vanilla-200c-01 | alns_sa_autofit | 5 |
| e2-vanilla-200c-01 | alns_sa_lns_cooling | 5 |
| e2-threeshift-200c-01 | alns_sa_autofit | 4 |
| e2-threeshift-200c-01 | alns_sa_lns_cooling | 1 |

## Threeshift Completed-Row Evidence

Even ignoring hard-timeout rows, SA-ALNS does not meet the promotion bar. The
better of the two SA variants is `alns_sa_lns_cooling`, but it only beats LNS on
`e2-threeshift-75c-01`; it loses on the other threeshift sizes.

| instance | LNS mean | alns_sa_autofit mean | autofit gap vs LNS | alns_sa_lns_cooling mean | lns-cooling gap vs LNS |
|---|---:|---:|---:|---:|---:|
| e2-threeshift-50c-01 | 2358.247888 | 2378.095811 | 0.841639% | 2367.024640 | 0.372173% |
| e2-threeshift-75c-01 | 3605.423331 | 3686.590654 | 2.251256% | 3554.463503 | -1.413421% |
| e2-threeshift-100c-01 | 4944.487761 | 5250.266550 | 6.184236% | 5017.082864 | 1.468203% |
| e2-threeshift-150c-01 | 7451.731179 | 8176.700150 | 9.728866% | 7556.930429 | 1.411742% |
| e2-threeshift-200c-01 | 8989.413172 | 10073.969917 | 12.064823% | 9434.057382 | 4.946310% |

For `e2-threeshift-200c-01`, the ALNS means above are computed only from
returned rows: `1/5` for `alns_sa_autofit` and `4/5` for
`alns_sa_lns_cooling`. The missing rows are hard timeouts, so these numbers are
diagnostic only and cannot be used for promotion.

## Verdict

The 09c gate does not pass:

- No infeasible returned solution was observed; returned rows were zero-violation.
- The full gate is blocked by `35/135` hard-timeout rows with no finite solution.
- On completed threeshift rows, the SA-ALNS candidates still do not beat LNS
  consistently enough to satisfy the user requirement that ALNS win and
  stabilize.

Stage 3-5 remain stopped. Do not use these rows as a formal comparison table;
they are HALT evidence for Stage 2.
