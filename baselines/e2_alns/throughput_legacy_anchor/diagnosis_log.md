# Winner Kernel Restoration Diagnosis Log

## Phase 2 - 2026-06-22 22:22:29

- Commit: `c769600e1e746ae20c0e6136ddcf9876ba62f641`
- Command: `PYTHONHASHSEED=0 SETP_ALNS_PARALLEL_WORKERS=6 python -m setp_solver.search.winner_restoration run-current --seeds 1,2,3,4,5,6,7,8,9,10 --eval-budget 16000 --max-runtime-seconds 900.0`
- Stdout: `mean_current=4878.331796 mean_gold=4878.331796 mean_delta=0.000000 classification=not_regressed`
- Stderr: ``
- Conclusion: Current winner is not worse than gold on mean; restoration should not change search logic without more evidence.
