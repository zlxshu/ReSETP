# E2 ALNS Throughput Gate HALT

Conclusion: `HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT`.

09d fixed the engineering bottleneck enough to remove the "iteration starvation"
explanation, but the promoted E2 ALNS candidate still does not beat LNS on the
threeshift gate. This is a HALT, not a promotion. Stage 3-5 remain stopped.

Run commit: `c769600e1e746ae20c0e6136ddcf9876ba62f641`

Environment:

- Python: `/opt/anaconda3/bin/python3.13`
- NumPy: `2.3.5`
- `PYTHONHASHSEED=0`
- Gate output: `baselines/e2_alns/throughput_raw_runs.csv`
- Wall-clock protocol: 50/75/100c = `300s`, 150/200c = `900s`; `16000`
  evals are diagnostic only.

## Profile Evidence

Profile instance: `e2-threeshift-100c-01`, seed `1`, 256 evals.

| phase | eval/s | elapsed seconds | best cost | explained ratio |
|---|---:|---:|---:|---:|
| before caches | 6.517 | 39.279 | 5297.631436 | 1.134 |
| after caches | 24.655 | 10.383 | 5297.631436 | 0.939 |

The same-seed/same-budget best cost is unchanged. The main bottleneck remains
`regret2_insert_repair`, but route-local cost and structure caches reduce the
100c small-budget runtime by about 3.8x.

## Anchor Guard

Command:

```bash
SETP_ALNS_PARALLEL_WORKERS=4 PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m setp_solver.search.winner_restoration run-current --output-dir baselines/e2_alns/throughput_legacy_anchor --seeds 1-10 --eval-budget 16000 --max-runtime-seconds 900
```

Result: `PASS_CURRENT_RUN_CLASSIFIED`.

| metric | value |
|---|---:|
| mean current total cost | 4878.331796187524 |
| best / seed2 total cost | 4779.053444002934 |
| mean delta vs gold | 0.0 |
| zero-violation rows | 10/10 |

Legacy winner behavior is not regressed.

## Gate Evidence

Command:

```bash
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m setp_solver.search.e2_alns_throughput gate --seeds 1-5 --eval-budget 16000 --workers 3 --output-dir baselines/e2_alns
```

Stdout:

```text
GATE E2_ALNS_THROUGHPUT {"gate": "HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT", "elapsed_seconds": 12932.726694957993, "rows": 90}
```

All 90 rows returned finite zero-violation solutions. Timeout rows now return a
feasible incumbent instead of `inf`.

| status | rows |
|---|---:|
| OK | 50 |
| HALT_RUNTIME_UNDER_EVAL | 30 |
| HALT_HARD_TIMEOUT_WITH_INCUMBENT | 10 |

Threeshift gaps are still not acceptable:

| instance | ALNS gap vs LNS | ALNS/LNS eval/s ratio |
|---|---:|---:|
| e2-threeshift-50c-01 | 0.372173% | 4.027963 |
| e2-threeshift-75c-01 | -1.413421% | 3.664527 |
| e2-threeshift-100c-01 | 1.328747% | 3.783715 |
| e2-threeshift-150c-01 | 1.385658% | 3.498293 |
| e2-threeshift-200c-01 | 3.448227% | 3.888174 |

Paired threeshift result: ALNS wins `9/25`, loses `16/25`, ties `0/25`.
Wilcoxon reports LNS significantly better (`wilcoxon_lns_better=true`).

## Verdict

09d proves the previous "ALNS is merely iteration-starved" hypothesis is
insufficient. After throughput repair, ALNS is faster than LNS on every
threeshift size group, but still loses on mean cost in 4 of 5 threeshift groups
and loses the paired test.

Per the 09d decision tree, stop here and report to the user. Do not proceed to
Stage 3-5 and do not keep adding ALNS components in this lane.
