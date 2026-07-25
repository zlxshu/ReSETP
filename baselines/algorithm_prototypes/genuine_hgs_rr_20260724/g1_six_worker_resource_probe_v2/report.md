# G1 six-worker resource probe

Decision: `PASS_G1_SIX_WORKERS_RESOURCE_PROBE`.

Six zero-search real-bundle wiring tasks ran concurrently.
No objective value is included in this resource decision.

- All tasks passed: True
- Minimum free-memory percentage: 62%
- Aggregate worker peak RSS: 371.828 MB

This gate only selects six or three parallel independent G1 tasks. It does not change any task's algorithm, random stream, budget, evaluator, or acceptance threshold.
