# Winner Kernel Nondeterminism Diagnosis Log

## Phase 0 - Safety Snapshot Setup

- Current HEAD before nondeterminism work: `04fab62207f0bb92f9ea73ca142e20bf6205fe2e`.
- `git status --short --untracked-files=all`: clean.
- Recent commits:
  - `04fab62 Record restored winner baseline for final restoration head`
  - `024579d Clean restoration runner formal experiment grep guard`
  - `05e56c7 Diagnose winner kernel not regressed against gold baseline`
  - `970a3aa Diagnose winner gold solution scoring semantics`
  - `6725e80 Add winner restoration diagnostics runner`
  - `18ef753 Record degraded winner restoration safety snapshot`
  - `2aeb65e Snapshot degraded winner kernel + PPO v2 wiring before restoration`
  - `802d06f Refine reporting pipeline and paper generation outputs`
- Observed Git AppleDouble metadata before cleanup:
  - `.git/objects/pack/._pack-4ba8282de66e2ac5ed909a762387046fe9e28646.pack`
  - `.git/objects/pack/._pack-3c961803fec41ed112c31b7275e853d70d14c222.pack`
  - `.git/objects/pack/._pack-cede3e596865a3149f2ebebc8b3db2d85090359b.pack`
- Cleanup command: `find .git/objects/pack -maxdepth 1 -type f -name '._pack-*' -print -delete`.
- Scope guard: do not modify dependencies, do not start PPO training, and do not change model semantics or formal experiment outputs.

## Phase 1 - 2026-06-16 17:55:55

- Commit: `1ba776d758054072d935c97c1f0f3d1f448fd643`
- Command: `python -m setp_solver.search.winner_nondeterminism phase1 --seed 2 --eval-budget 16000 --max-runtime-seconds 900.0 --repeats 3 --workers 3`
- Stdout: `classification=environment_numeric_drift system=4779.053444002934 venv=4909.530249672552`
- Stderr: ``
- Conclusion: System Python and RL venv are each internally deterministic but converge to different anchors; use environment-local gates.

## Phase 2/3 - 2026-06-16 17:56:16

- Commit: `1ba776d758054072d935c97c1f0f3d1f448fd643`
- Command: `python -m setp_solver.search.winner_nondeterminism phase2-skipped`
- Stdout: `classification=environment_numeric_drift`
- Stderr: ``
- Conclusion: System Python and RL venv are each internally deterministic but converge to different anchors; use environment-local gates.

## Phase 4 - 2026-06-16 18:15:02

- Commit: `d07533d54c5da2c1eee6fb428eba6d04602a9e7a`
- Command: `python -m setp_solver.search.winner_nondeterminism phase4 --seeds 1,2,3,4,5,6,7,8,9,10 --eval-budget 16000`
- Stdout: `winner_mean=5696.142007406236 sa_mean=None gate=HALT_VENV_SELF_CHECK`
- Stderr: ``
- Conclusion: RL venv winner does not pass the same-environment PPO gate.

## Phase 4 - 2026-06-16 18:31:37

- Commit: `e7e173638bcba2bb72ed9fce53b32450a2af74ff`
- Command: `python -m setp_solver.search.winner_nondeterminism phase4 --seeds 1,2,3,4,5,6,7,8,9,10 --eval-budget 16000`
- Stdout: `winner_mean=5696.142007406236 sa_mean=5408.003789193207 gate=HALT_VENV_SELF_CHECK`
- Stderr: ``
- Conclusion: RL venv winner does not pass the same-environment PPO gate.

## Phase 5 - 2026-06-16 18:31:49

- Commit: `e7e173638bcba2bb72ed9fce53b32450a2af74ff`
- Command: `python -m setp_solver.search.winner_nondeterminism phase5`
- Stdout: `gate=HALT_VENV_SELF_CHECK`
- Stderr: ``
- Conclusion: Environment drift is confirmed, but the RL venv self-check did not pass the venv fairness gate.

## Reproducibility note - 2026-06-16 19:18:11

- Commit: `cc7b0485e76f33ae210d1dd2571fcfe613fe1f79`
- Command: `python -m setp_solver.search.winner_nondeterminism reproducibility-note`
- Stdout: `classification=floating_or_blas_numeric_drift`
- Stderr: ``
- Conclusion: NumPy default_rng probes match across environments, so the winner-cost drift is not explained by the sampled RNG stream; the remaining evidence points to numeric/BLAS/Python-version drift.

## Phase 5 system-worker self-check - 2026-06-16 19:57:47

- Commit: `b777079bd55d83d032a53e6161bdd7d80e45db07`
- Command: `python -m setp_solver.search.winner_nondeterminism system-worker-gate`
- Stdout: `gate=PASS_SYSTEM_WORKER_SELF_CHECK`
- Stderr: ``
- Conclusion: System-Python worker lane reproduces the winner anchor, beats fair SA, and has zero violations.

## Phase 4 system-worker gate - 2026-06-16 19:57:47

- Commit: `b777079bd55d83d032a53e6161bdd7d80e45db07`
- Command: `python -m setp_solver.search.winner_nondeterminism system-worker-gate --seeds 1,2,3,4,5,6,7,8,9,10 --eval-budget 16000`
- Stdout: `gate=PASS_SYSTEM_WORKER_SELF_CHECK winner_mean=4878.331796187524 alpha_mean=4878.331796187524 fair_sa_mean=5346.986857132418`
- Stderr: ``
- Conclusion: System-Python worker gate passes; PPO lane baselines are back on the audited winner environment.
