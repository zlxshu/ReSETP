# Foundation gate startup incident 001

- Time: 2026-07-20 02:45 +08:00
- Scope: monitoring/preflight only
- Algorithm runs completed: 0
- Result files created: 0
- Failure: the monitor created its untracked run directory inside the repository
  before the gate checked `git status --porcelain`. The gate correctly refused
  to start from a dirty worktree.
- Additional setup defect: the monitor interpreted the relative `workdir`
  against its copied configuration location, so protected and result paths were
  reported under the prototype directory instead of the repository root.
- Correction: ignore only the prototype's transient monitor run directories and
  pin the monitor workdir to the absolute ReSETP repository path.
- Scientific impact: none. No instance was solved, no result was exposed, and
  the frozen algorithm, configurations, instances, seeds, budgets, gates, and
  verdict rules were not changed.
