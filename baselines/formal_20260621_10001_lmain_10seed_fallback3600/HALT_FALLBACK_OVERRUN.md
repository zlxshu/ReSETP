# Fallback Overrun HALT

One-line conclusion: the 3600s fallback completion run was stopped because the first fallback workers exceeded the per-run wall-clock cap without returning control to the runner.

## Command

```text
PYTHONPATH=solver/src SETP_META_PARALLEL_WORKERS=4 /opt/anaconda3/bin/python3.13 -m setp_solver.search.metaheuristic_baseline_runner complete-fallback --repo-root . --previous-output-dir baselines/formal_20260621_10001_lmain_10seed --output-dir baselines/formal_20260621_10001_lmain_10seed_fallback3600 --fallback-max-runtime-seconds 3600
```

## Evidence

The process tree was still running at `01:04:46`, with all four worker processes CPU-bound:

```text
PID    STAT  ELAPSED   %CPU  COMMAND
68120  Ss    01:04:47  0.0   metaheuristic_baseline_runner complete-fallback ...
68186  R     01:04:46  95.8  python3.13 multiprocessing-fork
68187  R     01:04:46  96.9  python3.13 multiprocessing-fork
68188  R     01:04:46  94.6  python3.13 multiprocessing-fork
68189  R     01:04:46  94.7  python3.13 multiprocessing-fork
```

The fallback directory still contained only preflight files at termination time, so no fallback-completed `raw_runs.csv` or `comparison_table.csv` exists.

## Diagnosis

A stack sample from worker `68186` showed Python `builtin_sorted` / `list_sort` as the dominant sampled frames. That matches the remaining baseline-only budget-out insertion/repair enumeration bottleneck. Because the runner only receives control after each task returns, this also exposed that the current runner does not hard-kill an individual task exactly at 3600s.

## Action Taken

The process tree was terminated after confirming it had overrun the 3600s cap. This directory is HALT evidence only and must not be treated as a formal completed comparison.
