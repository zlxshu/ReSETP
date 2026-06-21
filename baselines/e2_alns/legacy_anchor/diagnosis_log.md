# Winner Kernel Restoration Diagnosis Log

## Phase 2 - 2026-06-21 22:17:40

- Commit: `b1ffa7567f2ad2c5f998c95b33aaf82be39874d7`
- Command: `PYTHONHASHSEED=0 SETP_ALNS_PARALLEL_WORKERS=6 python -m setp_solver.search.winner_restoration run-current --seeds 1,2,3,4,5,6,7,8,9,10 --eval-budget 16000 --max-runtime-seconds 900.0`
- Stdout: `mean_current=4878.331796 mean_gold=4878.331796 mean_delta=0.000000 classification=not_regressed`
- Stderr: ``
- Conclusion: Current winner is not worse than gold on mean; restoration should not change search logic without more evidence.
