# China81 versus open-source distance-only HGS

This campaign follows the user-authorized later Claude correction: reuse the
sealed F/E/M/MV rows and run only the new O arm.

Development execution:

```bash
PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
build/python_envs/pyvrp-hgs-0.12.2/bin/python \
baselines/algorithm_prototypes/china81_vs_opensource_20260727/run_comparison.py \
  --workers 6
```

Use `--preflight-only` for the six-process environment gate,
`--finalize-only` to rebuild reports without search, and `--confirmation` only
after a separate authorization to run all 81 instances with seeds 1--5.

Protocol disclosure: O is a new `NoImprovement(3000)` run. F/E/M/MV are
read-only imports from the sealed 2026-07-24 v7 fixed-iteration batch. They
must not be described as same-batch, same-machine, same-stop-rule, or
equal-compute evidence.
