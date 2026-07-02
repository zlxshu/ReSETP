# Final Track19/Track20 Report

## Track19 100c Legal Comparison

Final status: HALT_MAIN_100C_WEAK

Evidence chain:
- Track17 100c audit confirmed the prior 100c comparison was illegal: the selected main method only used 4234/16000 evals, eval_ratio=0.264625, and returned the warm start.
- Track19 calibration fixed the budget starvation: winner_kernel_true_repair_adaptive_q reached 16000/16000 evals on 100c seed901.
- After budget was fixed, the same method remained VALID_BUT_WEAK: best_cost equaled warm_start_cost, best_update_count=0, and all 16000 operator attempts were rejected.
- Partial formal 100c rows showed SA was HEALTHY on seeds 901-903 and improved the same warm start by roughly 20-25%, while the main method stayed at warm on seeds 901-904.
- A 100c diagnostic over seven Track19 ALNS candidates at 4000 evals each found no candidate improving the warm start; every winner-kernel variant had accepted_move_count=0.

Decision: do not resume the formal 100c paper claim with the current Track19 main method. The budget issue was real and is now fixed; the remaining problem is method strength at 100c, not budget legality.

Primary artifacts:
- solver/reports/dr_alns_ppo_v3/final_track19/track19_budget_audit.csv
- solver/reports/dr_alns_ppo_v3/final_track19/track19_100c_calibration.csv
- solver/reports/dr_alns_ppo_v3/final_track19/track19_100c_method_diagnostic.csv
- solver/reports/dr_alns_ppo_v3/final_track19/final_report.md

## Track20 Dynamic Action Sanity

Final status: HEURISTIC_FLAT

Evidence chain:
- Track18 headroom was real: 20/20 healthy rows, mean information_cost_pct about 43.99%.
- Track20 added a real policy_callback hook to run_rolling_reoptimization without changing evaluate/check semantics.
- Myopic callback regression reproduced the Track18 baseline exactly on the checked row: dynamic_cost, static_revealed_cost, information_cost, and information_cost_pct deltas were all 0.
- Broad reserve/defer smoke was harmful on seed901: information_cost worsened by 35.27%.
- Lighter 5% reserve/defer smoke was still harmful on seed901: information_cost worsened by 20.06%.
- Conservative defer_adds full run was healthy on 20/20 rows but did not pass the action-headroom gate: mean reduction 2.42%, wins=9/20, Wilcoxon p=0.1244.

Decision: current reserve/defer action surface does not eat the Track18 dynamic headroom strongly enough to justify training DR now. It reduced only about 3.31% of mean information_cost in absolute share terms, leaving about 96.69% as remaining/unexplained headroom under this action design.

Primary artifacts:
- solver/reports/dr_alns_ppo_v3/final_track20/track20_myopic_callback_regression.csv
- solver/reports/dr_alns_ppo_v3/final_track20/track20_rows.csv
- solver/reports/dr_alns_ppo_v3/final_track20/track20_action_sanity_report.md
- solver/reports/dr_alns_ppo_v3/final_track20/final_report.md
- solver/reports/dr_alns_ppo_v3/final_track20_smoke_broad/track20_action_sanity_report.md
- solver/reports/dr_alns_ppo_v3/final_track20_smoke_reserve005/track20_action_sanity_report.md

## Human Conclusion

The honest paper line is not a 10% all-scale ALNS claim and not a dynamic DR claim yet.

Track19 says: the static/fair-comparison route is blocked at 100c because the selected ALNS main method is legally run but weak there.

Track20 says: dynamic headroom exists, but the first real non-learning online action only gives a small, non-significant reduction. DR training should not start until the action interface is redesigned or a stronger non-learning heuristic can move the information_cost gap reliably.
