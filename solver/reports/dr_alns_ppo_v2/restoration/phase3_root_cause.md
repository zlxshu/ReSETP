# Phase 3 Root Cause

- classification: `environment_numeric_drift`
- system_anchor: 4779.053444002934
- venv_anchor: 4909.530249672552
- conclusion: System Python and the RL venv are each internally deterministic, but they converge to different anchors. Per policy, do not change dependencies; use environment-local PPO gates.