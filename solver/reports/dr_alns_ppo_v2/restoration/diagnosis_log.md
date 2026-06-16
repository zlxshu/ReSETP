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
