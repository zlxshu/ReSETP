# S3-TRAJ-V4 observation-only trajectory rerun

Decision: `HALT_S3_TRAJ_OFFLINE_CURVE_GATE`.

The sealed S3 `raw_runs.csv` was read-only. The rerun used the registered representative instance, the same four arms, seeds 1--10, PyVRP 0.12.2, stopping criteria, continuation seeds, and SP time limit.

The only code addition was a local observer around the PyVRP 0.12.2 Python loop. It copied the translated route skeleton when the proxy global best improved. The observer did not call the exact scorer, completioner, repair code, RNG, or solver mutation. Completion and exact scoring were performed offline after each HGS unit ended.

Completed rows: 40/40.

HALT detail: offline curve final mismatch for mechanism_ev/seed10: curve=2364.589958517462, rerun=2365.8780971446868, sealed=2365.8780971446868

Final-cost exact equality: 40/40 completed rows.

Offline snapshot audit: 36 units; 0 completion errors and 0 infeasible snapshots were retained rather than filtered from the audit.

No algorithm, evaluator, protected raw ledger, or sealed S3 value is changed by this lane. The observation rerun authorizes only a presentation-level trajectory artifact if all 40 final costs are exactly equal to sealed S3.
