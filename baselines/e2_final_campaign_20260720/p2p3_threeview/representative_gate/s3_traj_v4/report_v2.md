# S3-TRAJ-CURVE-DEF-001 v2 offline materialization

Decision: `PASS_S3_TRAJ_CURVE_UNDER_REGISTERED_DEFINITION`.

This v2 step reads the existing 40 S3-TRAJ solver snapshots and the sealed S3 final-cost ledger. It does not rerun HGS, change the random stream, alter the evaluator, or rewrite the v1 HALT decision.

Figure 4 uses the historical snapshot skeletons after offline full-model completion and exact scoring. The plotted quantity is the monotone running minimum (best-so-far), so it may be lower than the sealed runner's final accepted candidate when proxy and complete-model rankings disagree.

All 40 final rerun costs equal sealed S3 exactly; all complete solutions have zero violations. 1 unit(s) have a historical curve best below their sealed final cost.

The registered example is HGS-M (`mechanism_ev`)/seed10: curve best `2364.589958517462`; sealed table cost `2365.8780971446868`. This difference remains trajectory-only and is not used in Table 6/Table 8 or any summary statistic.

Figure 4 seed selection remains pre-registered: for each arm choose the seed whose sealed final cost is closest to that arm's ten-seed average, with the smaller seed breaking ties.

The S3-TRAJ v1 HALT and both v1/v2 evidence families are preserved. This v2 decision authorizes only the registered presentation definition; it authorizes no new algorithm or superiority claim.
