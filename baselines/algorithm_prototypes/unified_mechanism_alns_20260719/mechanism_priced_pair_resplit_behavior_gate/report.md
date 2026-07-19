# 双路线重切零搜索行为门

结论：`PASS_MECHANISM_PRICED_PAIR_RESPLIT_BEHAVIOR`。

本门只验证人工小夹具上的动作、归因、联合资源检查和账本；
没有调用ALNS、HGS、正式winner或任何完整路线搜索。

## 关键数字

- 输入成本：`249.811408459947`。
- 原骨架机制完成反事实：`249.811408459947`。
- 机制计价臂：`150.064923953565`。
- 里程删减臂：`249.811408459947`。
- 共同候选：`39`个。
- 独立穷举最优在里程排序中第`13`名。

## 机械检查

- PASS：`oracle_candidate_count_at_least_6`。
- PASS：`oracle_best_not_in_distance_top4`。
- PASS：`oracle_best_in_mechanism_top4`。
- PASS：`solver_pool_matches_independent_oracle`。
- PASS：`solver_scores_match_independent_oracle`。
- PASS：`caps_exact_0_1_2_4`。
- PASS：`cap_zero_exact_noop`。
- PASS：`mechanism_strictly_beats_source`。
- PASS：`mechanism_strictly_beats_counterfactual`。
- PASS：`mechanism_strictly_beats_distance_arm`。
- PASS：`distance_arm_does_not_fake_improvement`。
- PASS：`same_candidate_pool_both_arms`。
- PASS：`same_exact_capacity_both_arms`。
- PASS：`same_joint_work_binding_fixture`。
- PASS：`mechanism_matches_independent_oracle`。
- PASS：`mechanism_field_really_changes`。
- PASS：`nonbinding_mechanism_exact_noop`。
- PASS：`nonbinding_distance_exact_noop`。
- PASS：`joint_left_control_feasible`。
- PASS：`joint_right_control_feasible`。
- PASS：`joint_public_station_conflict_rejected`。
- PASS：`joint_public_station_actions_entered_completion`。
- PASS：`public_station_retime_positive_control`。
- PASS：`all_tamper_checks_rejected`。
- PASS：`zero_complete_route_search_evaluations`。
- PASS：`all_outputs_feasible`。
- PASS：`protected_hashes_unchanged`。

## 边界

即使本门通过，也只允许为两道全新小题另立极小搜索合同。
本证据不授权正式搜索、全量benchmark、China81、E2--E7重跑或阶段二。
行为门使用两条改动路线各占一辆不同实体车的受限语义；
可复用实体车的公共站多趟衔接尚未被本门证明。
