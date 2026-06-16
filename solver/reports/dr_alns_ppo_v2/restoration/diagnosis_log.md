# Winner Kernel Restoration Diagnosis Log

## Phase 0 - Safety Snapshot Setup

- Current HEAD before restoration snapshot: `802d06f4701c0fb0b94f289c50623693a1b9cdfd`.
- Observed git AppleDouble noise before cleanup:
  - `.git/objects/pack/._pack-3c961803fec41ed112c31b7275e853d70d14c222.idx`
  - `.git/objects/pack/._pack-3c961803fec41ed112c31b7275e853d70d14c222.pack`
  - `.git/objects/pack/._pack-3c961803fec41ed112c31b7275e853d70d14c222.rev`
  - `.git/objects/pack/._pack-4ba8282de66e2ac5ed909a762387046fe9e28646.idx`
  - `.git/objects/pack/._pack-4ba8282de66e2ac5ed909a762387046fe9e28646.pack`
  - `.git/objects/pack/._pack-4ba8282de66e2ac5ed909a762387046fe9e28646.rev`
- Cleanup command: `rm -f .git/objects/pack/._pack-*.idx .git/objects/pack/._pack-*.pack .git/objects/pack/._pack-*.rev`.
- Post-cleanup observation: `git status --short --untracked-files=all` no longer emits non-monotonic pack index errors.
- Important current-state correction: restoration started from HEAD `802d06f`, not `520e8a2`; the degraded winner/PPO code is already tracked in HEAD, while models and solver reports are ignored by `.gitignore` and must be force-added selectively.
- Snapshot staging policy: include restoration-relevant code/reports/instances, exclude `.venv`, `__pycache__`, `._*`, and do not add new Reference Algorithm files.
- Safety snapshot commit: `2aeb65ed98de78ad38bcd0fb14e63ec9c010c247` (`Snapshot degraded winner kernel + PPO v2 wiring before restoration`).
- Commit created a new macOS AppleDouble pack metadata set under `.git/objects/pack/._pack-7c6b...`; it was cleaned with the same `rm -f .git/objects/pack/._pack-*` pattern before continuing.

## Phase 1 - 2026-06-16 14:35:32

- Commit: `6725e800649ef7c2db37254c0704caf03f7ff353`
- Command: `python -m setp_solver.search.winner_restoration verify-gold`
- Stdout: `gate=PASS_GOLD_RECOMPUTE mean=4878.331796187524 best=4779.053444002934 max_abs_delta=0`
- Stderr: ``
- Conclusion: Scoring semantics match gold solutions.

## Phase 2 - 2026-06-16 14:54:39

- Commit: `970a3aabdf5c1bc4eefe4897c6d6ddc4f8b7cf2b`
- Command: `PYTHONHASHSEED=0 SETP_ALNS_PARALLEL_WORKERS=6 python -m setp_solver.search.winner_restoration run-current --seeds 1,2,3,4,5,6,7,8,9,10 --eval-budget 16000 --max-runtime-seconds 900.0`
- Stdout: `mean_current=4878.331796 mean_gold=4878.331796 mean_delta=0.000000 classification=not_regressed`
- Stderr: ``
- Conclusion: Current winner is not worse than gold on mean; restoration should not change search logic without more evidence.

## Phase 2 - 2026-06-16 15:09:45

- Commit: `970a3aabdf5c1bc4eefe4897c6d6ddc4f8b7cf2b`
- Command: `PYTHONHASHSEED=0 SETP_ALNS_PARALLEL_WORKERS=6 python -m setp_solver.search.winner_restoration run-current --seeds 1,2,3,4,5,6,7,8,9,10 --eval-budget 16000 --max-runtime-seconds 900.0`
- Stdout: `mean_current=4878.331796 mean_gold=4878.331796 mean_delta=0.000000 classification=not_regressed`
- Stderr: ``
- Conclusion: Current winner is not worse than gold on mean; restoration should not change search logic without more evidence.

## Phase 4/5 - 2026-06-16 15:09:45

- Commit: `970a3aabdf5c1bc4eefe4897c6d6ddc4f8b7cf2b`
- Command: `python -m setp_solver.search.winner_restoration verify-restored`
- Stdout: `gate=PASS_RESTORED_BASELINE mean=4878.331796`
- Stderr: ``
- Conclusion: Restored winner baseline established.
