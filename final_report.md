# Final Report: Track17 + Track18

## Top-Line Decision

Track17 did not produce a paper-safe 10% fair-comparison claim. It stopped correctly at `HALT_BASELINE_NOT_RUNNING` because GA failed the formal 100c health gate at `E-UK100_01__d2_s3_seed1_24h_20251113/seed901`.

Track18 found real dynamic anticipation headroom, but did not produce a DR win. It stopped at `HALT_DYNAMIC_POLICY_ENTRYPOINT`: the current checkout has no callable, non-cheating dynamic DR-online policy entrypoint to train and compare against myopic rolling ALNS.

## Track17: Paper Fallback

Final status: `HALT_BASELINE_NOT_RUNNING`

Reason: GA returned the warm-start solution exactly on the first 100c formal instance after full budget: eval_ratio=1.0, unique_solution_count=6300, best_update_count=0, candidates_better_than_warm=0, zero violations, diagnosis=`candidate_hashes_varied_but_all_scored_candidates_worse_than_warm`.

The selected main method is `winner_kernel_true_repair_adaptive_q` (`winner_kernel+true_repair+adaptive_q`). In Stage B validation it beat `plain_alns` by 3.2283%, so it is stronger than plain ALNS on that validation set. The full 25/50/100c formal comparison did not complete because GA failed at 100c.

The 10% weak-field claim is not real under the Track17 rules. On completed 25c/50c rows, the main method is better than the healthy baselines, but the smaller margins against ACO, GWO, IWD, and VNS are only around 5-7%. The partial Wilcoxon p-values are significant, but the 100c health halt makes them descriptive only, not a final paper claim.

PSO remains excluded from quantitative claims. Its Track16 root cause was: 3978 unique candidates, best_update_count=0, and no candidate improved on warm start; this is a search-direction failure, not a decoder/hash-collapse bug.

Key Track17 outputs:

- `solver/reports/dr_alns_ppo_v3/final_track17/track17_rows.csv`
- `solver/reports/dr_alns_ppo_v3/final_track17/track17_method_ablation_report.md`
- `solver/reports/dr_alns_ppo_v3/final_track17/track17_fair_comparison_report.md`
- `solver/reports/dr_alns_ppo_v3/final_track17/final_report.md`

## Track18: Dynamic DR

Final status: `HALT_DYNAMIC_POLICY_ENTRYPOINT`

Stage0 headroom status: `HEADROOM_REAL`

Headroom rows: 20/20 healthy.

Mean information_cost_pct: 43.993288689364284

Median information_cost_pct: 43.495413192075745

Scale summary:

- 25c: 10 rows, mean 37.90802955526038%, min 22.17%, max 58.33%
- 50c: 10 rows, mean 50.078547823468185%, min 22.85%, max 72.86%

This means myopic rolling ALNS is far above the full-information static control on these dynamic scenarios, so anticipation has real theoretical room.

But this is not a DR result. The policy audit found no current dynamic DR-online policy entrypoint:

- `run_rolling_reoptimization` exposes no policy callback and calls `_run_stage_plan` directly.
- `_run_stage_plan` accepts `initial_plan` but no reserve-capacity, commit-vs-defer, or vehicle-preposition action.
- `block_env` dynamic phase returns `0.0` when dynamic/rolling keys exist and otherwise falls back to static best-gain reward.
- Track15 already refused to label rolling ALNS control as DR because no trained dynamic DR-online policy entrypoint exists.

Key Track18 outputs:

- `solver/reports/dr_alns_ppo_v3/final_track18/track18_headroom.csv`
- `solver/reports/dr_alns_ppo_v3/final_track18/track18_rows.csv`
- `solver/reports/dr_alns_ppo_v3/final_track18/track18_dynamic_dr_report.md`
- `solver/reports/dr_alns_ppo_v3/final_track18/track18_policy_audit.md`
- `solver/reports/dr_alns_ppo_v3/final_track18/final_report.md`

## Next Decision

For the paper line, do not claim 10%. The honest Track17 statement is: the selected ALNS kernel is stronger than plain ALNS on validation and often better than healthy baselines on 25/50c, but formal 100c comparison halted because GA failed the required health gate.

For DR, there is a real dynamic opportunity, but the next work is engineering a real online policy control surface before training: reserve capacity/time slack, commit-vs-defer, or vehicle preposition actions injected into stage planning without changing `evaluate` or `check` semantics.
