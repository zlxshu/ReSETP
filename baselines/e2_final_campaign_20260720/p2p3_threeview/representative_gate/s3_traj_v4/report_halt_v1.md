# S3-TRAJ-V4 observation-only trajectory rerun

Decision: `HALT_S3_TRAJ_OFFLINE_CURVE_GATE`.

The sealed S3 `raw_runs.csv` was read-only. The rerun used the registered representative instance, the same four arms, seeds 1--10, PyVRP 0.12.2, stopping criteria, continuation seeds, and SP time limit.

The only code addition was a local observer around the PyVRP 0.12.2 Python loop. It copied the translated route skeleton when the proxy global best improved. The observer did not call the exact scorer, completioner, repair code, RNG, or solver mutation. Completion and exact scoring were performed offline after each HGS unit ended.

Completed rows: 40/40.

HALT detail: [Errno 21] Is a directory: '/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4'

Final-cost exact equality: 40/40 completed rows.

No algorithm, evaluator, protected raw ledger, or sealed S3 value is changed by this lane. The observation rerun authorizes only a presentation-level trajectory artifact if all 40 final costs are exactly equal to sealed S3.
