# ReSETP 全仓库实验包资产盘点（ASSET1）

## 清单口径

本次在 `baselines/` 下识别 898 个实验包。目录只要含逐单元原始记录 CSV、`decision.json`、`metadata.json`、`done.json`，或含非空 `units/`、`solutions/` 子目录，即纳入；版本目录分别计数。点号开头的监控目录若含 `done.json` 也按给定目录判据单列。`units/`、`solutions/`、`tasks/` 等逐单元目录不再拆成独立包，其文件计入最近的实验包。AppleDouble `._*` 旁文件不计入产物份数，也不作为路径证据。

`artifact_count` 与 `artifact_kinds` 统计各文件归属到最近实验包后的全量产物；`csv_rows` 取该包的 `raw_runs.csv`，没有该文件时取已识别的同类逐单元原始记录 CSV。`has_raw_runs_csv` 只表示包根是否存在同名文件。时间使用文件系统最后修改时间并转为带时区 ISO 8601。

求解路径证据来自包内 JSON 的 engine/源文件字段、包内 runner，或能以输出目录常量对应到该包的上级 runner。P5 只使用明确的零搜索计数、`search_executed=false` 或同义字段；`formal_search_allowed=false` 单独不构成 P5。

## 分类计数

| 分类 | 包数 |
|---|---:|
| `AFFECTED_CONFIRMED` | 20 |
| `AFFECTED_LIKELY` | 76 |
| `NOT_AFFECTED_PATH` | 114 |
| `NO_SEARCH` | 129 |
| `UNDETERMINED` | 559 |
| 合计 | 898 |

全量 JSON 对指定字段的递归合计为：`archive_completion_attempts=184854`，`archive_candidates_completed=24526`。该合计覆盖 466 份含至少一个指定字段的 JSON；字段解析失败数为 0。

## AFFECTED_CONFIRMED 完整列表

1. `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h6_multiseed_route_pool_gate`

   路径：`P1`。证据：baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h6_multiseed_route_pool_gate/solution_witnesses.json:/cn-jjj-25c-03-V2-LOCATIONS::seed-1/view_epochs/cv_only/archive_candidates_completed=24

   指纹甲：attempts=0，completed=648。指纹乙：groups=3，single=1。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h6_multiseed_route_pool_gate/solution_witnesses.json:/cn-jjj-25c-03-V2-LOCATIONS::seed-1/view_epochs/cv_only/archive_candidates_completed=24；指纹乙成立（groups=3, single=1）

2. `baselines/china_e3_e7/candidate_pool_probe_20260803`

   路径：`P1`。证据：baselines/china_e3_e7/candidate_pool_probe_20260803/probe_pool.py:405: self.route_pool.run_hgs_route_pool_recombination

   指纹甲：attempts=该包无指定JSON字段；同义逐单元计数=216，completed=该包无指定JSON字段；同义逐单元计数=0。指纹乙：groups=0，single=0。指纹丙：该包无此信息：没有可用的目标值或路线结构值列。分类判据：baselines/china_e3_e7/candidate_pool_probe_20260803/probe_pool.py:405: self.route_pool.run_hgs_route_pool_recombination；指纹甲同义逐单元计数成立（completion_attempted/completion_succeeded=216/0；指定JSON字段缺失）

3. `baselines/china_e3_e7/e3_structural_20260731`

   路径：`P1`。证据：baselines/china_e3_e7/e3_structural_20260731/formal/task_status/cn-prd-50c-01-V2-LOCATIONS__seed09__ZONE.json:/termination_evidence/cv_only/archive_completion_attempts=108

   指纹甲：attempts=25587，completed=3449。指纹乙：groups=3，single=2。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/e3_structural_20260731/formal/task_status/cn-prd-50c-01-V2-LOCATIONS__seed09__ZONE.json:/termination_evidence/cv_only/archive_completion_attempts=108；指纹乙成立（groups=3, single=2）

4. `baselines/china_e3_e7/e3_zone_joint_20260731`

   路径：`P1`。证据：baselines/china_e3_e7/e3_zone_joint_20260731/formal/task_status/cn-prd-100c-02-V2-LOCATIONS__seed10__ZONE.json:/termination_evidence/cv_only/archive_completion_attempts=129

   指纹甲：attempts=39966，completed=5359。指纹乙：groups=4，single=1。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/e3_zone_joint_20260731/formal/task_status/cn-prd-100c-02-V2-LOCATIONS__seed10__ZONE.json:/termination_evidence/cv_only/archive_completion_attempts=129；指纹乙成立（groups=4, single=1）

5. `baselines/china_e3_e7/e6_fairness_v2_20260731`

   路径：`P1`。证据：baselines/china_e3_e7/e6_fairness_v2_20260731/formal/task_status/cn-prd-100c-02-V2-LOCATIONS__seed10__JOINT.json:/termination_evidence/cv_only/archive_completion_attempts=122

   指纹甲：attempts=6747，completed=0。指纹乙：groups=6，single=2。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/e6_fairness_v2_20260731/formal/task_status/cn-prd-100c-02-V2-LOCATIONS__seed10__JOINT.json:/termination_evidence/cv_only/archive_completion_attempts=122；指纹甲成立（attempts=6747, completed=0）；指纹乙成立（groups=6, single=2）

6. `baselines/china_e3_e7/e6_fairness_v3_20260731`

   路径：`P1`。证据：baselines/china_e3_e7/e6_fairness_v3_20260731/formal/task_status/cn-prd-100c-02-V2-LOCATIONS__seed10__JOINT.json:/termination_evidence/cv_only/archive_completion_attempts=122

   指纹甲：attempts=6747，completed=0。指纹乙：groups=6，single=2。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/e6_fairness_v3_20260731/formal/task_status/cn-prd-100c-02-V2-LOCATIONS__seed10__JOINT.json:/termination_evidence/cv_only/archive_completion_attempts=122；指纹甲成立（attempts=6747, completed=0）；指纹乙成立（groups=6, single=2）

7. `baselines/china_e3_e7/formal_ablation_200c_20260803`

   路径：`P1`。证据：baselines/china_e3_e7/formal_ablation_200c_20260803/units/G2__MV_HGS_NO_SP__S2026080210/search_trace.json:/cv_only/archive_completion_attempts=25, /cv_only/archive_candidates_completed=0

   指纹甲：attempts=900，completed=0。指纹乙：groups=3，single=3。指纹丙：不适用：存在迭代或评价预算列['max_hgs_iterations', 'max_no_improvement_iterations']，但没有同种子同配置的不同预算组。分类判据：baselines/china_e3_e7/formal_ablation_200c_20260803/units/G2__MV_HGS_NO_SP__S2026080210/search_trace.json:/cv_only/archive_completion_attempts=25, /cv_only/archive_candidates_completed=0；指纹甲成立（attempts=900, completed=0）；指纹乙成立（groups=3, single=3）

8. `baselines/china_e3_e7/formal_algorithm_20260802`

   路径：`P1`。证据：baselines/china_e3_e7/formal_algorithm_20260802/units/G2__MV_HGS_NO_SP__S2026080210/search_trace.json:/cv_only/archive_completion_attempts=25, /cv_only/archive_candidates_completed=0

   指纹甲：attempts=1620，completed=0。指纹乙：groups=8，single=8。指纹丙：不适用：存在迭代或评价预算列['max_hgs_iterations', 'max_no_improvement_iterations']，但没有同种子同配置的不同预算组。分类判据：baselines/china_e3_e7/formal_algorithm_20260802/units/G2__MV_HGS_NO_SP__S2026080210/search_trace.json:/cv_only/archive_completion_attempts=25, /cv_only/archive_candidates_completed=0；指纹甲成立（attempts=1620, completed=0）；指纹乙成立（groups=8, single=8）

9. `baselines/china_e3_e7/formal_fleet_levels_20260802`

   路径：`P1`。证据：baselines/china_e3_e7/formal_fleet_levels_20260802/preregistration.json:/source_files_sha256/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=3，single=3。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/formal_fleet_levels_20260802/preregistration.json:/source_files_sha256/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py；指纹乙成立（groups=3, single=3）

10. `baselines/china_e3_e7/scout_depot_ownership_20260803`

   路径：`P1`。证据：baselines/china_e3_e7/scout_depot_ownership_20260803/run_scout_d.py:70: from route_pool_sp import run_hgs_route_pool_recombination # noqa: E402

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=2，single=2。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/scout_depot_ownership_20260803/run_scout_d.py:70: from route_pool_sp import run_hgs_route_pool_recombination # noqa: E402；指纹乙成立（groups=2, single=2）

11. `baselines/china_e3_e7/scout_depot_ownership_20260803/baseline_nearest`

   路径：`P1`。证据：baselines/china_e3_e7/scout_depot_ownership_20260803/run_scout_d.py:70: from route_pool_sp import run_hgs_route_pool_recombination；同文件:94: BASELINES = ("baseline_random", "baseline_nearest")；同文件:809: run = run_hgs_route_pool_recombination(

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=2，single=2。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/scout_depot_ownership_20260803/run_scout_d.py:70: from route_pool_sp import run_hgs_route_pool_recombination；同文件:94: BASELINES = ("baseline_random", "baseline_nearest")；同文件:809: run = run_hgs_route_pool_recombination(；指纹乙成立（groups=2, single=2）

12. `baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_fleet`

   路径：`P1`。证据：baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_fleet/metadata.json:/source_files_sha256/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=3，single=3。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_fleet/metadata.json:/source_files_sha256/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py；指纹乙成立（groups=3, single=3）

13. `baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_nonlinear`

   路径：`P1`。证据：baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_nonlinear/metadata.json:/source_files_sha256/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=2，single=2。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_nonlinear/metadata.json:/source_files_sha256/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py；指纹乙成立（groups=2, single=2）

14. `baselines/china_e3_e7/seed_determinism_probe2_20260803`

   路径：`P1`。证据：baselines/china_e3_e7/seed_determinism_probe2_20260803/probe_proxy.py:303: self._original_exact_epoch = self.route_pool._run_exact_epoch

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=9，single=9。指纹丙：成立：可比较组=6，逐位单值组=6，迭代或评价预算列=['iterations']。分类判据：baselines/china_e3_e7/seed_determinism_probe2_20260803/probe_proxy.py:303: self._original_exact_epoch = self.route_pool._run_exact_epoch；指纹乙成立（groups=9, single=9）；指纹丙：可比较组=6，逐位单值组=6，迭代或评价预算列=['iterations']

15. `baselines/china_e3_e7/seed_determinism_probe_20260803`

   路径：`P1`。证据：baselines/china_e3_e7/seed_determinism_probe_20260803/probe_seed.py:423: "run_hgs_route_pool_recombination，该函数对三个视角逐一传给 "

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=3，single=3。指纹丙：成立：可比较组=2，逐位单值组=2，迭代或评价预算列=['iterations']。分类判据：baselines/china_e3_e7/seed_determinism_probe_20260803/probe_seed.py:423: "run_hgs_route_pool_recombination，该函数对三个视角逐一传给 "；指纹乙成立（groups=3, single=3）；指纹丙：可比较组=2，逐位单值组=2，迭代或评价预算列=['iterations']

16. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/full_gate`

   路径：`P1`。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=81，single=40。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py；指纹乙成立（groups=81, single=40）

17. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/full_gate`

   路径：`P1`。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=81，single=48。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py；指纹乙成立（groups=81, single=48）

18. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/full_gate`

   路径：`P1`。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=81，single=41。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py；指纹乙成立（groups=81, single=41）

19. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/full_gate`

   路径：`P1`。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=77，single=15。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/full_gate/metadata.json:/source_hashes/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py；指纹乙成立（groups=77, single=15）

20. `baselines/e2_final_campaign_20260720/p0_fuse/rebalance_gate`

   路径：`P1`。证据：baselines/e2_final_campaign_20260720/p0_fuse/run_c_rebalance_validation.py:43: from epochal_hgs import _run_exact_epoch  # noqa: E402；输出目录关联 baselines/e2_final_campaign_20260720/p0_fuse/run_c_rebalance_validation.py:36: OUT = PACKAGE / "rebalance_gate"

   指纹甲：attempts=该包无此信息，completed=该包无此信息。指纹乙：groups=3，single=2。指纹丙：不适用：该包无迭代或评价预算列。分类判据：baselines/e2_final_campaign_20260720/p0_fuse/run_c_rebalance_validation.py:43: from epochal_hgs import _run_exact_epoch  # noqa: E402；输出目录关联 baselines/e2_final_campaign_20260720/p0_fuse/run_c_rebalance_validation.py:36: OUT = PACKAGE / "rebalance_gate"；指纹乙成立（groups=3, single=2）

## UNDETERMINED 完整列表

1. `baselines`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/representative_seed1_route_diversity_after_archive_reuse.json:/views/cv_only/archive_candidates_completed=24 || baselines/e1_model/m1_e1_model_structure_runner.py:32: from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy

2. `baselines/algorithm_foundation/mda_ils_vns_adaptive_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mda_ils_vns_adaptive_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

3. `baselines/algorithm_foundation/mda_ils_vns_foundation_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mda_ils_vns_foundation_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

4. `baselines/algorithm_foundation/mda_ils_vns_late_stage_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mda_ils_vns_late_stage_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

5. `baselines/algorithm_foundation/mda_ils_vns_parameter_race_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mda_ils_vns_parameter_race_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

6. `baselines/algorithm_foundation/mpd_ils_vns_dual_regime_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpd_ils_vns_dual_regime_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

7. `baselines/algorithm_foundation/mpils_mvns_c2_a_constant_diagnosis_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_c2_a_constant_diagnosis_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

8. `baselines/algorithm_foundation/mpils_mvns_c2_g0_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_c2_g0_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

9. `baselines/algorithm_foundation/mpils_mvns_c2_g0_license_repair_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_c2_g0_license_repair_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

10. `baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

11. `baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_v2_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_v2_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

12. `baselines/algorithm_foundation/mpils_mvns_c2_g1_b_first_fire_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_c2_g1_b_first_fire_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

13. `baselines/algorithm_foundation/mpils_mvns_c2_g1_b_second_fire_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_c2_g1_b_second_fire_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

14. `baselines/algorithm_foundation/mpils_mvns_three_instance_sentinel_20260719`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/mpils_mvns_three_instance_sentinel_20260719/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

15. `baselines/algorithm_foundation/pyvrp_v13_time_quality_curve_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/pyvrp_v13_time_quality_curve_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

16. `baselines/algorithm_foundation/remix_hgs_supplier_bridge_20260719`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/remix_hgs_supplier_bridge_20260719/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

17. `baselines/algorithm_foundation/remix_hgs_supplier_bridge_v2_20260719`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/remix_hgs_supplier_bridge_v2_20260719/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

18. `baselines/algorithm_foundation/remix_pr17a_behavior_gate_20260719`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/remix_pr17a_behavior_gate_20260719/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

19. `baselines/algorithm_foundation/remix_pr17a_behavior_gate_v2_20260719`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/remix_pr17a_behavior_gate_v2_20260719/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

20. `baselines/algorithm_foundation/remix_same_path_equivalence_gate_20260719`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/remix_same_path_equivalence_gate_20260719/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

21. `baselines/algorithm_foundation/remix_v13_six_instance_development_20260719`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_foundation/remix_v13_six_instance_development_20260719/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

22. `baselines/algorithm_prototypes/algo_reset_20260719/exact_route_pool_microprobe`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/exact_route_pool_microprobe/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

23. `baselines/algorithm_prototypes/algo_reset_20260719/hgs_alns_offspring_fusion_microgate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/hgs_alns_offspring_fusion_microgate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

24. `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

25. `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

26. `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval4`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval4/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

27. `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval8`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval8/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

28. `baselines/algorithm_prototypes/algo_reset_20260719/homberger_headroom_audit`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/homberger_headroom_audit/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

29. `baselines/algorithm_prototypes/algo_reset_20260719/mechanism_normalized_fresh_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/mechanism_normalized_fresh_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

30. `baselines/algorithm_prototypes/algo_reset_20260719/mechanism_route_pool_incremental_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/mechanism_route_pool_incremental_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

31. `baselines/algorithm_prototypes/algo_reset_20260719/route_core_split_sweep`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/algo_reset_20260719/route_core_split_sweep/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

32. `baselines/algorithm_prototypes/carbon_nonlinear_charging_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/carbon_nonlinear_charging_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

33. `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h1_population_archive_gate`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h1_population_archive_gate/solution_witnesses.json:/cn-jjj-25c-01-V2-LOCATIONS::cv_only/stats/archive_candidates_completed=24

34. `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h2_fresh_population_archive_gate`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h2_fresh_population_archive_gate/solution_witnesses.json:/cn-jjj-25c-02-V2-LOCATIONS::cv_only/stats/archive_candidates_completed=24

35. `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h3_epochal_migration_gate`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h3_epochal_migration_gate/solution_witnesses.json:/cn-jjj-25c-01-V2-LOCATIONS/control/stats/archive_candidates_completed=24

36. `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h4_route_pool_gate`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h4_route_pool_gate/solution_witnesses.json:/cn-jjj-25c-01-V2-LOCATIONS/view_epochs/cv_only/archive_candidates_completed=24

37. `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h5_fresh_route_pool_gate`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h5_fresh_route_pool_gate/solution_witnesses.json:/cn-jjj-25c-03-V2-LOCATIONS/view_epochs/cv_only/archive_candidates_completed=24

38. `baselines/algorithm_prototypes/dual_guided_resource_order_20260725/.dual-guided-engineering-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/dual_guided_resource_order_20260725/.dual-guided-engineering-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

39. `baselines/algorithm_prototypes/dual_guided_resource_order_20260725/.dual-guided-engineering.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/dual_guided_resource_order_20260725/.dual-guided-engineering.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

40. `baselines/algorithm_prototypes/dual_guided_resource_order_20260725/engineering_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/dual_guided_resource_order_20260725/engineering_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

41. `baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/direct_improvement_gate_v1_abort_packaging`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/direct_improvement_gate_v1_abort_packaging/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

42. `baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/g0_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/g0_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

43. `baselines/algorithm_prototypes/fleet_charging_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/fleet_charging_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

44. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-g1-mechanical-release-chain-v1.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-g1-mechanical-release-chain-v1.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

45. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-g1-release-chain-v1.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-g1-release-chain-v1.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

46. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-real-bundle-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-real-bundle-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

47. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-real-bundle-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-real-bundle-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

48. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-worker-probe-g1-release-chain-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-worker-probe-g1-release-chain-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

49. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-micro-v5-decoder-repair.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-micro-v5-decoder-repair.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

50. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-micro-v6-coverage-contract.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-micro-v6-coverage-contract.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

51. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-six-worker-resource-probe-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-six-worker-resource-probe-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

52. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-six-worker-resource-probe-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-six-worker-resource-probe-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

53. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_mechanical_release_chain_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_mechanical_release_chain_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

54. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_release_chain_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_release_chain_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

55. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

56. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v3/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

57. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_v5_decoder_repair_abort`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_v5_decoder_repair_abort/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

58. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

59. `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v3/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

60. `baselines/algorithm_prototypes/hgs_ils_cross_domain_20260725/g0_preflight_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/hgs_ils_cross_domain_20260725/g0_preflight_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

61. `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-engineering-v1.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-engineering-v1.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

62. `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-engineering-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-engineering-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

63. `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-g0-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-g0-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

64. `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

65. `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

66. `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/g0_gate_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/g0_gate_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

67. `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-adaptive.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-adaptive.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

68. `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-foundation-rerun.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-foundation-rerun.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

69. `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-foundation.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-foundation.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

70. `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-late-stage.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-late-stage.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

71. `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-parameter-race.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-parameter-race.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

72. `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mpd-dual-regime-rerun.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mda_ils_vns_20260720/.mpd-dual-regime-rerun.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

73. `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mpd-dual-regime.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mda_ils_vns_20260720/.mpd-dual-regime.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

74. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_share_001`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_share_001/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

75. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_two_basin`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_two_basin/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

76. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_20c_b500_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_20c_b500_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

77. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_development_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_development_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

78. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/functional_two_basin`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/functional_two_basin/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

79. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_functional`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_functional/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

80. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_multidepot_scale_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_multidepot_scale_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

81. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_functional`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_functional/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

82. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_multidepot_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_multidepot_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

83. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v4_b100_minimal_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v4_b100_minimal_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

84. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

85. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_optimized_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_optimized_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

86. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_minimal_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_minimal_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

87. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v6_b100_shared_base_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v6_b100_shared_base_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

88. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v7_stage1_closeout_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v7_stage1_closeout_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

89. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v8_interleaved_microgate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v8_interleaved_microgate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

90. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v9_seeded_microgate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v9_seeded_microgate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

91. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_functional`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_functional/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

92. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_multidepot_scale_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_multidepot_scale_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

93. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_component_ablation`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_component_ablation/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

94. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_confirmation_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_confirmation_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

95. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_seed1_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_seed1_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

96. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_cheapest_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_cheapest_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

97. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_space_time_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_space_time_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

98. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_gate_25c`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_gate_25c/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

99. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_multidepot_scale_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_multidepot_scale_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

100. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_005`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_005/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

101. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_010`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_010/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

102. `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_015`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_015/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

103. `baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v1_no_failure_stop`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v1_no_failure_stop/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

104. `baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v2_pre_rng_fix`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v2_pre_rng_fix/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

105. `baselines/algorithm_prototypes/rce_hgs_misrank_20260725/.rce-hgs-misrank-engineering.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/rce_hgs_misrank_20260725/.rce-hgs-misrank-engineering.monitor/effective_config.json:仅记录受保护的pyvrp_adapter.py路径；status.json的runtime_seconds为监控耗时，未给出legacy分支调用

106. `baselines/algorithm_prototypes/rce_hgs_misrank_20260725/.rce-hgs-misrank-formal.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/rce_hgs_misrank_20260725/.rce-hgs-misrank-formal.monitor/effective_config.json:仅记录受保护的pyvrp_adapter.py路径；status.json的runtime_seconds为监控耗时，未给出legacy分支调用

107. `baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/g0_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/g0_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

108. `baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/g0_gate_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/g0_gate_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

109. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

110. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

111. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

112. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-g0-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-g0-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

113. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

114. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

115. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v3/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

116. `baselines/algorithm_prototypes/resource_slot_pricing_20260725/g0_gate_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/resource_slot_pricing_20260725/g0_gate_v3/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

117. `baselines/algorithm_prototypes/route_column_mip_assembly_20260725/direct_headroom_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/route_column_mip_assembly_20260725/direct_headroom_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

118. `baselines/algorithm_prototypes/route_column_mip_assembly_20260725/g0_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/route_column_mip_assembly_20260725/g0_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

119. `baselines/algorithm_prototypes/tailored_dp_vns_20260725/direct_improvement_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/tailored_dp_vns_20260725/direct_improvement_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

120. `baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/t0_engineering_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/t0_engineering_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

121. `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

122. `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_p1_failure_audit`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_p1_failure_audit/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

123. `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/initial_pool_gate_d1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/unified_mechanism_alns_20260719/initial_pool_gate_d1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

124. `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_regret_training_d1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_regret_training_d1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

125. `baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/direct_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/direct_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

126. `baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v1`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v1/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

127. `baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

128. `baselines/china_e3_e7/.e3-arm-semantics-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.e3-arm-semantics-v3.monitor/effective_config.json:仅记录受保护的pyvrp_adapter.py路径；status.json的runtime_seconds为监控耗时，未给出legacy分支调用

129. `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.artifact_watch.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.artifact_watch.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

130. `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.artifact_watch_resume.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.artifact_watch_resume.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

131. `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

132. `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry1.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry1.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

133. `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

134. `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

135. `baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

136. `baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor-v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor-v2/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

137. `baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor-v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor-v3/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

138. `baselines/china_e3_e7/.xd-attempt4-archive-recovery-20260803.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.xd-attempt4-archive-recovery-20260803.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

139. `baselines/china_e3_e7/.xd-attempt4-archive-recovery-v2-20260803.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/.xd-attempt4-archive-recovery-v2-20260803.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

140. `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid/.xd-carbon-timing-rescore-20260802-attached.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid/.xd-carbon-timing-rescore-20260802-attached.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

141. `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid/.xd-carbon-timing-rescore-20260802.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid/.xd-carbon-timing-rescore-20260802.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

142. `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt2_invalid/.xd-carbon-timing-rescore-20260802-attempt2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt2_invalid/.xd-carbon-timing-rescore-20260802-attempt2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

143. `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

144. `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3b.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3b.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

145. `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3c.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3c.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

146. `baselines/china_e3_e7/current_source_compatibility_20260801/saved_solution_replay_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/current_source_compatibility_20260801/saved_solution_replay_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

147. `baselines/china_e3_e7/e3_release_regression_v2_20260724`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_release_regression_v2_20260724/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

148. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-01-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-01-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

149. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-02-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-02-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

150. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-03-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-03-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

151. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-01-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-01-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

152. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-02-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-02-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

153. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-03-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-03-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

154. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-01-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-01-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

155. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-02-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-02-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

156. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-03-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-03-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

157. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-01-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-01-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

158. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-02-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-02-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

159. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-03-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-03-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

160. `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/panel_summary`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/panel_summary/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

161. `baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

162. `baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot_capacity_rank_aligned_v1_20260801`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/china_e3_e7/e3_scattered_ownership_20260801/run_e3_capacity_rank_aligned.py:164: result = base.run_hgs_route_pool_recombination(；输出目录关联 baselines/china_e3_e7/e3_scattered_ownership_20260801/run_e3_capacity_rank_aligned.py:23: OUTPUT = HERE / "pilot_capacity_rank_aligned_v1_20260801"

163. `baselines/china_e3_e7/e3_structural_20260731/probe`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/china_e3_e7/e3_structural_20260731/probe/task_status/cn-prd-50c-01-V2-LOCATIONS__seed01__JOINT.json:/termination_evidence/cv_only/archive_completion_attempts=124

164. `baselines/china_e3_e7/e4_carbon_timing_20260729`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_carbon_timing_20260729/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

165. `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

166. `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-01-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-01-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

167. `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-02-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-02-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

168. `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-03-V2-LOCATIONS`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-03-V2-LOCATIONS/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

169. `baselines/china_e3_e7/e4_joint_routing_20260801/probe`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/probe/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

170. `baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt1_no_ev_bug`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt1_no_ev_bug/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

171. `baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt2_pre_cost_tiebreak_fix`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt2_pre_cost_tiebreak_fix/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

172. `baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt3_legacy_pure_carbon_repair`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt3_legacy_pure_carbon_repair/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

173. `baselines/china_e3_e7/e4_joint_routing_20260801/probe_v2_hook_restore_20260801`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/china_e3_e7/e4_joint_routing_20260801/run_probe.py:23: from route_pool_sp import run_hgs_route_pool_recombination；输出目录关联 baselines/china_e3_e7/e4_joint_routing_20260801/run_probe.py:498: "--output", type=Path, default=HERE / "probe_v2_hook_restore_20260801"

174. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot02`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot02/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

175. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot03`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot03/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

176. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot04`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot04/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

177. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot05`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot05/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

178. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot07_seeds1to3_symmetric`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot07_seeds1to3_symmetric/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

179. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot08_fixed_schedule_execution_replay_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot08_fixed_schedule_execution_replay_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

180. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot09_montoya_l1_l2_pl_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot09_montoya_l1_l2_pl_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

181. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot10_montoya_l1_l2_pl_20260801`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/run_montoya_approximations.py:27: from route_pool_sp import run_hgs_route_pool_recombination；输出目录关联 baselines/china_e3_e7/e5_enroute_nonlinear_20260801/run_montoya_approximations.py:56: DEFAULT_OUTPUT = HERE / "pilot10_montoya_l1_l2_pl_20260801"

182. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot11_montoya_time_metric_reaccounting_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot11_montoya_time_metric_reaccounting_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

183. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot12_montoya_fs_l1_l2_pl_20260801`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/run_montoya_fs_approximations.py:30: from route_pool_sp import run_hgs_route_pool_recombination；输出目录关联 baselines/china_e3_e7/e5_enroute_nonlinear_20260801/run_montoya_fs_approximations.py:59: DEFAULT_OUTPUT = HERE / "pilot12_montoya_fs_l1_l2_pl_20260801"

184. `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_enroute_nonlinear_20260801/smoke/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

185. `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-160`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-160/raw_blind.csv:1: CSV表头=['instance_id', 'sample_role', 'seed', 'arm', 'budget', 'complete_candidate_evaluations_S', 'last_strict_improvement_evaluation_L', 'last_strict_improvement_fraction_L_over_S', 'starved_L_over_S_gt_0_5', 'wallclock_safety_triggered', 'elapsed_wall_seconds', 'elapsed_cpu_seconds', 'status']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

186. `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-240`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-240/raw_blind.csv:1: CSV表头=['instance_id', 'sample_role', 'seed', 'arm', 'budget', 'complete_candidate_evaluations_S', 'last_strict_improvement_evaluation_L', 'last_strict_improvement_fraction_L_over_S', 'starved_L_over_S_gt_0_5', 'wallclock_safety_triggered', 'elapsed_wall_seconds', 'elapsed_cpu_seconds', 'status']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

187. `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-32`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-32/raw_blind.csv:1: CSV表头=['instance_id', 'sample_role', 'seed', 'arm', 'budget', 'complete_candidate_evaluations_S', 'last_strict_improvement_evaluation_L', 'last_strict_improvement_fraction_L_over_S', 'starved_L_over_S_gt_0_5', 'wallclock_safety_triggered', 'elapsed_wall_seconds', 'elapsed_cpu_seconds', 'status']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

188. `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-56`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-56/raw_blind.csv:1: CSV表头=['instance_id', 'sample_role', 'seed', 'arm', 'budget', 'complete_candidate_evaluations_S', 'last_strict_improvement_evaluation_L', 'last_strict_improvement_fraction_L_over_S', 'starved_L_over_S_gt_0_5', 'wallclock_safety_triggered', 'elapsed_wall_seconds', 'elapsed_cpu_seconds', 'status']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

189. `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-80`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-80/raw_blind.csv:1: CSV表头=['instance_id', 'sample_role', 'seed', 'arm', 'budget', 'complete_candidate_evaluations_S', 'last_strict_improvement_evaluation_L', 'last_strict_improvement_fraction_L_over_S', 'starved_L_over_S_gt_0_5', 'wallclock_safety_triggered', 'elapsed_wall_seconds', 'elapsed_cpu_seconds', 'status']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

190. `baselines/china_e3_e7/e5_nonlinear_v4_20260730`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/china_e3_e7/e5_nonlinear_v4_20260730/formal/task_status/cn-prd-100c-02-V2-LOCATIONS__seed-10__NL90_mild.json:/termination_evidence/cv_only/archive_completion_attempts=122

191. `baselines/china_e3_e7/e5_nonlinear_v4_20260730/formal/manifests`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_nonlinear_v4_20260730/formal/manifests/cn-prd-100c-02-V2-LOCATIONS__manifest.csv:1: CSV表头=['instance_id', 'sample_role', 'seed', 'arm', 'budget', 'complete_candidate_evaluations_S', 'last_strict_improvement_evaluation_L', 'last_strict_improvement_fraction_L_over_S_diagnostic_only', 'elapsed_wall_seconds', 'elapsed_cpu_seconds', 'search_total_cost_cny', 'objective_status', 'common_initial_solution_sha256', 'plan_path', 'plan_file_sha256', 'search_trace_path', 'search_trace_sha256', 'status']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

192. `baselines/china_e3_e7/e5_nonlinear_v4_20260730/probe`：已定位P1，但现有可比记录未使任一指定指纹成立。证据：baselines/china_e3_e7/e5_nonlinear_v4_20260730/probe/tasks/cn-prd-50c-01-V2-LOCATIONS__seed-01__NL90_mild.json:/termination_evidence/cv_only/archive_completion_attempts=124

193. `baselines/china_e3_e7/e5_option_b_assessment_20260730`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e5_option_b_assessment_20260730/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

194. `baselines/china_e3_e7/e6_contractor_participation_20260801/.formal_e6a_panel_20260801.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e6_contractor_participation_20260801/.formal_e6a_panel_20260801.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

195. `baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/panel_raw_runs.csv:1: CSV表头=['instance_id', 'seed', 'mapping_sha256', 'coalition', 'coalition_member_count', 'initial_source', 'initial_sha256', 'initial_cost_cny', 'search_candidate_cost_cny', 'final_cost_cny', 'saving_from_initial_cny', 'selected_source', 'cross_contractor_customers', 'cross_contractor_quantity_kg', 'used_cv', 'used_ev', 'route_pool_records', 'complete_candidate_evaluations', 'elapsed_seconds', 'solution_sha256']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

196. `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot02`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e6_contractor_participation_20260801/pilot02/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

197. `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot07_physical_transfer_ledger_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e6_contractor_participation_20260801/pilot07_physical_transfer_ledger_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

198. `baselines/china_e3_e7/e7_dynamic_20260731/inputs`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_dynamic_20260731/inputs/event_manifest.csv:1: CSV表头=['add_count', 'cancel_count', 'canonical_sha256', 'demand_change_count', 'event_count', 'file_sha256', 'instance_id', 'path', 'scale', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

199. `baselines/china_e3_e7/e7_dynamic_v2_20260731/inputs`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_dynamic_v2_20260731/inputs/event_manifest.csv:1: CSV表头=['add_count', 'cancel_count', 'canonical_sha256', 'demand_change_count', 'event_count', 'file_sha256', 'instance_id', 'path', 'scale', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

200. `baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801-retry1.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801-retry1.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

201. `baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801-retry2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801-retry2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

202. `baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

203. `baselines/china_e3_e7/e7_o1_replanning_20260801/failed_attempt1_count_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/failed_attempt1_count_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

204. `baselines/china_e3_e7/e7_o1_replanning_20260801/failure_diagnosis_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/failure_diagnosis_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

205. `baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

206. `baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_count_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_count_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

207. `baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_v2_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_v2_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

208. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed10_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed10_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

209. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed1_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed1_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

210. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed2_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed2_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

211. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

212. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v2_clockfix_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v2_clockfix_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

213. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed4_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed4_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

214. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed5_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed5_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

215. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed6_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed6_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

216. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed7_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed7_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

217. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed8_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed8_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

218. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed9_eval8_v1_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed9_eval8_v1_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

219. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to10_eval8_aggregate_v1_all_pairwise_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to10_eval8_aggregate_v1_all_pairwise_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

220. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

221. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v2_clockfix_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v2_clockfix_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

222. `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v3_all_pairwise_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v3_all_pairwise_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

223. `baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_50c_seeds1to10_eval8_diagnostic_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_50c_seeds1to10_eval8_diagnostic_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

224. `baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_three_triggers_50c_seeds1to10_eval8_comparison_20260801`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_three_triggers_50c_seeds1to10_eval8_comparison_20260801/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

225. `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed01`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed01/solutions/carbon_aware/preoptimization.json:1: JSON顶层字段=['actual_parts', 'arm', 'certificate', 'certificate_sha256', 'hgs', 'perceived_objective', 'perceived_parts', 'phase', 'policy', 'solution', 'solution_sha256', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

226. `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed02`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed02/solutions/carbon_aware/preoptimization.json:1: JSON顶层字段=['actual_parts', 'arm', 'certificate', 'certificate_sha256', 'hgs', 'perceived_objective', 'perceived_parts', 'phase', 'policy', 'solution', 'solution_sha256', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

227. `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed03`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed03/solutions/carbon_aware/preoptimization.json:1: JSON顶层字段=['actual_parts', 'arm', 'certificate', 'certificate_sha256', 'hgs', 'perceived_objective', 'perceived_parts', 'phase', 'policy', 'solution', 'solution_sha256', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

228. `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed04`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed04/solutions/carbon_aware/preoptimization.json:1: JSON顶层字段=['actual_parts', 'arm', 'certificate', 'certificate_sha256', 'hgs', 'perceived_objective', 'perceived_parts', 'phase', 'policy', 'solution', 'solution_sha256', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

229. `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed05`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed05/solutions/carbon_aware/preoptimization.json:1: JSON顶层字段=['actual_parts', 'arm', 'certificate', 'certificate_sha256', 'hgs', 'perceived_objective', 'perceived_parts', 'phase', 'policy', 'solution', 'solution_sha256', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

230. `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed06`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed06/solutions/carbon_aware/preoptimization.json:1: JSON顶层字段=['actual_parts', 'arm', 'certificate', 'certificate_sha256', 'hgs', 'perceived_objective', 'perceived_parts', 'phase', 'policy', 'solution', 'solution_sha256', 'stream_seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

231. `baselines/china_e3_e7/foundation_20260723`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/foundation_20260723/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

232. `baselines/china_e3_e7/foundation_20260723/aggregates`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/foundation_20260723/aggregates/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

233. `baselines/china_e3_e7/foundation_20260723/figures`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/foundation_20260723/figures/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

234. `baselines/china_e3_e7/foundation_20260723/paper_tables`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/foundation_20260723/paper_tables/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

235. `baselines/china_e3_e7/scout_three_mechanisms_20260803/.experiment-monitor-attempt2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/scout_three_mechanisms_20260803/.experiment-monitor-attempt2/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

236. `baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/.experiment-monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/.experiment-monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

237. `baselines/china_instances/monitor_configs/.china-stage2-local-osrm-graphs-retry1.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_instances/monitor_configs/.china-stage2-local-osrm-graphs-retry1.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

238. `baselines/china_instances/monitor_configs/.china-stage2-local-osrm-graphs.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_instances/monitor_configs/.china-stage2-local-osrm-graphs.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

239. `baselines/china_instances/monitor_configs/.china81-stage2-road-pipeline.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/china_instances/monitor_configs/.china81-stage2-road-pipeline.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

240. `baselines/contract_audit/e1_e7_submission_contract_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/contract_audit/e1_e7_submission_contract_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

241. `baselines/contract_audit/submission_contract_candidate_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/contract_audit/submission_contract_candidate_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

242. `baselines/contract_audit/wp0_e0_check_20260712`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/contract_audit/wp0_e0_check_20260712/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

243. `baselines/contract_audit/wp0_e2_replay_20260712`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/contract_audit/wp0_e2_replay_20260712/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

244. `baselines/e1_model/e1_submission_20260711_committed/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e1_model/e1_submission_20260711_committed/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

245. `baselines/e1_model/e1_submission_20260711_committed/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e1_model/e1_submission_20260711_committed/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

246. `baselines/e2_alns/280kwh_fleet_composition_gate_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/280kwh_fleet_composition_gate_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

247. `baselines/e2_alns/alns_independence_migration_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/alns_independence_migration_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

248. `baselines/e2_alns/balanced_selector_probe_20260706`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/balanced_selector_probe_20260706/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

249. `baselines/e2_alns/battery_spectrum_transition_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/battery_spectrum_transition_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

250. `baselines/e2_alns/bridge_fix_validation_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/bridge_fix_validation_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

251. `baselines/e2_alns/carbon_aware_operator_probe_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/carbon_aware_operator_probe_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

252. `baselines/e2_alns/carbon_aware_operator_probe_phase0_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/carbon_aware_operator_probe_phase0_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

253. `baselines/e2_alns/carbon_aware_operator_probe_smoke_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/carbon_aware_operator_probe_smoke_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

254. `baselines/e2_alns/charging_infrastructure_operational_pilot_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/charging_infrastructure_operational_pilot_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

255. `baselines/e2_alns/convergence`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/convergence/e2-multidepot-100c-01__LNS__seed1.csv:1: CSV表头=['algorithm', 'best_cost', 'best_obj', 'current_cost', 'eval', 'instance', 'operator', 'seed', 'time_seconds']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

256. `baselines/e2_alns/convergence_throughput`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/convergence_throughput/e2-multidepot-100c-01__LNS__seed1.csv:1: CSV表头=['algorithm', 'best_cost', 'best_obj', 'eval', 'instance', 'operator', 'seed', 'time_seconds']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

257. `baselines/e2_alns/cvrplib_optimal_benchmark_20260716`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/cvrplib_optimal_benchmark_20260716/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

258. `baselines/e2_alns/decoder_fix_validation_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/decoder_fix_validation_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

259. `baselines/e2_alns/e2_12h_preflight_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_12h_preflight_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

260. `baselines/e2_alns/e2_16000_preflight_20260712/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_16000_preflight_20260712/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

261. `baselines/e2_alns/e2_16000_preflight_20260712/smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_16000_preflight_20260712/smoke/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

262. `baselines/e2_alns/e2_16000_preflight_plan_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_16000_preflight_plan_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

263. `baselines/e2_alns/e2_280_fleet_charging_audit_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_280_fleet_charging_audit_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

264. `baselines/e2_alns/e2_80k_robustness_20260711/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_80k_robustness_20260711/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

265. `baselines/e2_alns/e2_80k_robustness_20260711/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_80k_robustness_20260711/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

266. `baselines/e2_alns/e2_80k_robustness_fixed_20260711/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_80k_robustness_fixed_20260711/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

267. `baselines/e2_alns/e2_80k_robustness_repair_gate_20260711/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_80k_robustness_repair_gate_20260711/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

268. `baselines/e2_alns/e2_alns_budget_g0_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_alns_budget_g0_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

269. `baselines/e2_alns/e2_final_10seed_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_10seed_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

270. `baselines/e2_alns/e2_final_10seed_20260711/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_10seed_20260711/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

271. `baselines/e2_alns/e2_final_10seed_20260711/representative_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_10seed_20260711/representative_gate/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

272. `baselines/e2_alns/e2_final_10seed_20260711/smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_10seed_20260711/smoke/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

273. `baselines/e2_alns/e2_final_closure_20260703`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

274. `baselines/e2_alns/e2_final_closure_20260703/phase_a_alns_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/phase_a_alns_gate/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

275. `baselines/e2_alns/e2_final_closure_20260703/phase_a_carbon_gate_superseded_under_eval`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/phase_a_carbon_gate_superseded_under_eval/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

276. `baselines/e2_alns/e2_final_closure_20260703/phase_a_prime_route_elimination_retest`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/phase_a_prime_route_elimination_retest/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

277. `baselines/e2_alns/e2_final_closure_20260703/phase_b_g3_baseline_health`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/phase_b_g3_baseline_health/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

278. `baselines/e2_alns/e2_final_closure_20260703/phase_c_g4_stability`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/phase_c_g4_stability/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

279. `baselines/e2_alns/e2_final_closure_20260703/phase_d_g5_t3_material`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/phase_d_g5_t3_material/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

280. `baselines/e2_alns/e2_final_closure_20260703/phase_e_carbon_operator_diagnostic`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_final_closure_20260703/phase_e_carbon_operator_diagnostic/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

281. `baselines/e2_alns/e2_g0_closure_hygiene_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_g0_closure_hygiene_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

282. `baselines/e2_alns/e2_g0_reaudit_20260702`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_g0_reaudit_20260702/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

283. `baselines/e2_alns/e2_g0_reaudit_v2_20260703`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_g0_reaudit_v2_20260703/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

284. `baselines/e2_alns/e2_g0_same_value_platform_audit_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_g0_same_value_platform_audit_data/checkpoint_replay.csv:1: CSV表头=['instance', 'algorithm', 'seed', 'checkpoint', 'checkpoint_eval', 'checkpoint_operator', 'checkpoint_best_cost', 'replay_total_cost', 'replay_violation_count', 'signature_hash', 'raw_best_signature', 'signature_matches_raw', 'solution_json_sha256', 'route_count', 'cv_route_count', 'ev_route_count', 'charging_action_count', 'E_total', 'cost_carbon']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

285. `baselines/e2_alns/e2_loss_recovery_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_loss_recovery_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

286. `baselines/e2_alns/e2_loss_recovery_20260711/route_block_headroom_audit`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_loss_recovery_20260711/route_block_headroom_audit/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

287. `baselines/e2_alns/e2_refined_carbon_short_gate_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_refined_carbon_short_gate_20260711/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

288. `baselines/e2_alns/e2_submission_20260711`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_submission_20260711/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

289. `baselines/e2_alns/e2_submission_20260711/baseline_health`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_submission_20260711/baseline_health/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

290. `baselines/e2_alns/e2_submission_20260711/carbon_280`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_submission_20260711/carbon_280/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

291. `baselines/e2_alns/e2_submission_20260711/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/e2_submission_20260711/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

292. `baselines/e2_alns/ev_heavy_findability_gate_baseline_liveness_smoke_v2_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_baseline_liveness_smoke_v2_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

293. `baselines/e2_alns/ev_heavy_findability_gate_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

294. `baselines/e2_alns/ev_heavy_findability_gate_liveness_allalg_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_liveness_allalg_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

295. `baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

296. `baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

297. `baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

298. `baselines/e2_alns/ev_heavy_findability_gate_postfix_allalg_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_postfix_allalg_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

299. `baselines/e2_alns/ev_heavy_findability_gate_small_100c02_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_small_100c02_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

300. `baselines/e2_alns/ev_heavy_findability_gate_small_200c01_seed1_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_findability_gate_small_200c01_seed1_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

301. `baselines/e2_alns/ev_heavy_regime_stage0_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_regime_stage0_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

302. `baselines/e2_alns/ev_heavy_regime_stage0_smoke_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_heavy_regime_stage0_smoke_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

303. `baselines/e2_alns/ev_seeded_search_stage1_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/ev_seeded_search_stage1_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

304. `baselines/e2_alns/fleet_cap_operational_gate_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/fleet_cap_operational_gate_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

305. `baselines/e2_alns/global_repack_fleet_charge_probe_20260707`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/global_repack_fleet_charge_probe_20260707/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

306. `baselines/e2_alns/goeke80_multitrip_rescue_gate_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke80_multitrip_rescue_gate_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

307. `baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke/throughput_goeke80_multitrip_smoke_raw_runs.csv:1: CSV表头=['active_flags', 'actual_evals', 'algorithm', 'best_cost', 'category', 'commit_hash', 'convergence_path', 'cv_route_count', 'elapsed_seconds', 'ev_route_count', 'eval_budget_backstop', 'evals_per_second', 'feasible', 'gate_status', 'instance', 'numpy', 'python', 'route_count', 'runtime_cap_seconds', 'seed']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

308. `baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke/convergence_throughput`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke/convergence_throughput/e2-multidepot-100c-01__LNS__seed1.csv:1: CSV表头=['algorithm', 'best_cost', 'best_obj', 'eval', 'instance', 'operator', 'seed', 'time_seconds']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

309. `baselines/e2_alns/goeke80_multitrip_t3_preflight_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke80_multitrip_t3_preflight_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

310. `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke80_multitrip_t3_preflight_data/smoke/smoke_paired_summary.csv:1: CSV表头=['alns_cost', 'category', 'gap_pct_alns_minus_lns', 'instance', 'lns_cost', 'paired_winner', 'replicate', 'seed', 'size', 'winner_algorithm_for_composition', 'winner_all_cv', 'winner_all_ev', 'winner_cv_physical', 'winner_ev_physical', 'winner_ev_route_share', 'winner_max_trips_per_vehicle']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

311. `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_a`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_a/stage_a_paired_summary.csv:1: CSV表头=['alns_cost', 'category', 'gap_pct_alns_minus_lns', 'instance', 'lns_cost', 'paired_winner', 'replicate', 'seed', 'size', 'winner_algorithm_for_composition', 'winner_all_cv', 'winner_all_ev', 'winner_cv_physical', 'winner_ev_physical', 'winner_ev_route_share', 'winner_max_trips_per_vehicle']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

312. `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_b`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_b/stage_b_paired_summary.csv:1: CSV表头=['alns_cost', 'category', 'gap_pct_alns_minus_lns', 'instance', 'lns_cost', 'paired_winner', 'replicate', 'seed', 'size', 'winner_algorithm_for_composition', 'winner_all_cv', 'winner_all_ev', 'winner_cv_physical', 'winner_ev_physical', 'winner_ev_route_share', 'winner_max_trips_per_vehicle']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

313. `baselines/e2_alns/goeke_public_benchmark_feasibility_20260716`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/goeke_public_benchmark_feasibility_20260716/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

314. `baselines/e2_alns/hard_cap_feasibility_audit_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/hard_cap_feasibility_audit_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

315. `baselines/e2_alns/high_tension_separation_probe_09w_smoke_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/high_tension_separation_probe_09w_smoke_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

316. `baselines/e2_alns/high_tension_separation_probe_09w_stage_a_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/high_tension_separation_probe_09w_stage_a_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

317. `baselines/e2_alns/high_tension_separation_probe_smoke_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/high_tension_separation_probe_smoke_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

318. `baselines/e2_alns/high_tension_separation_probe_stage_a_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/high_tension_separation_probe_stage_a_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

319. `baselines/e2_alns/homberger_g1_sisr_micro_v2_20260718_aborted_path_bug`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/homberger_g1_sisr_micro_v2_20260718_aborted_path_bug/solutions/budget_smoke__C1_2_1__seed1__budget0__candidate_sisr.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

320. `baselines/e2_alns/instance_param_diagnostic_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/instance_param_diagnostic_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

321. `baselines/e2_alns/iwd_fidelity_gate_20260712`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/iwd_fidelity_gate_20260712/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

322. `baselines/e2_alns/iwd_fidelity_gate_20260712_rescue_zhang_scaled`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/iwd_fidelity_gate_20260712_rescue_zhang_scaled/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

323. `baselines/e2_alns/l_main_v3_activation`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/l_main_v3_activation/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

324. `baselines/e2_alns/largescale_allcv_diagnostic_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/largescale_allcv_diagnostic_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

325. `baselines/e2_alns/lns_acceptance_scheduler_audit_20260705`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/lns_acceptance_scheduler_audit_20260705/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

326. `baselines/e2_alns/lns_policy_kernel_probe_20260708`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/lns_policy_kernel_probe_20260708/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

327. `baselines/e2_alns/m1_fair_sa_recheck_20260710`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/m1_fair_sa_recheck_20260710/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

328. `baselines/e2_alns/m1_fleet_opportunity_20260710`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/m1_fleet_opportunity_20260710/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

329. `baselines/e2_alns/m1_staged_chain_150c_multiseed_20260710`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/m1_staged_chain_150c_multiseed_20260710/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

330. `baselines/e2_alns/m1_staged_chain_gate_20260710`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/m1_staged_chain_gate_20260710/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

331. `baselines/e2_alns/m1_staged_hybrid_stability_20260710`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/m1_staged_hybrid_stability_20260710/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

332. `baselines/e2_alns/modern_battery_regime_stage2_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/modern_battery_regime_stage2_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

333. `baselines/e2_alns/native_channel_autopsy_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/native_channel_autopsy_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

334. `baselines/e2_alns/official_hgs_a_bridge_smoke_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/official_hgs_a_bridge_smoke_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

335. `baselines/e2_alns/official_hgs_b_gate_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/official_hgs_b_gate_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

336. `baselines/e2_alns/parameter_evidence_review_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/parameter_evidence_review_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

337. `baselines/e2_alns/route_compression_probe_20260705`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/route_compression_probe_20260705/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

338. `baselines/e2_alns/route_compression_trace_audit_20260705`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/route_compression_trace_audit_20260705/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

339. `baselines/e2_alns/route_packing_reachability_audit_20260708`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/route_packing_reachability_audit_20260708/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

340. `baselines/e2_alns/selector_pathology_audit_20260706`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/selector_pathology_audit_20260706/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

341. `baselines/e2_alns/selector_sprint_failure_analysis_20260707`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/selector_sprint_failure_analysis_20260707/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

342. `baselines/e2_alns/selector_sprint_probe_20260706`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/selector_sprint_probe_20260706/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

343. `baselines/e2_alns/solomon_cpu_preflight_20260717`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/solomon_cpu_preflight_20260717/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

344. `baselines/e2_alns/solomon_cpu_preflight_20260717_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/solomon_cpu_preflight_20260717_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

345. `baselines/e2_alns/solomon_cpu_preflight_20260717_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/solomon_cpu_preflight_20260717_v3/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

346. `baselines/e2_alns/solomon_cpu_preflight_20260717_v4`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/solomon_cpu_preflight_20260717_v4/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

347. `baselines/e2_alns/solomon_cpu_preflight_20260717_v5`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/solomon_cpu_preflight_20260717_v5/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

348. `baselines/e2_alns/source_bound_mixed_band_gate_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/source_bound_mixed_band_gate_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

349. `baselines/e2_alns/source_bound_operational_mix_map_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/source_bound_operational_mix_map_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

350. `baselines/e2_alns/strong_bridge_backend_probe_20260705`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/strong_bridge_backend_probe_20260705/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

351. `baselines/e2_alns/strong_bridge_backend_probe_local_search_check_20260706`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/strong_bridge_backend_probe_local_search_check_20260706/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

352. `baselines/e2_alns/structural_mixed_band_investigation_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/structural_mixed_band_investigation_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

353. `baselines/e2_alns/structural_rescue_probe_20260707`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/structural_rescue_probe_20260707/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

354. `baselines/e2_alns/threeshift_280_stageA_generalization_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/threeshift_280_stageA_generalization_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

355. `baselines/e2_alns/threeshift_280_stageB_algorithm_comparison_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/threeshift_280_stageB_algorithm_comparison_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

356. `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

357. `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_stageA_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_stageA_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

358. `baselines/e2_alns/threeshift_280_stageB_full8_seed12_probe_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/threeshift_280_stageB_full8_seed12_probe_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

359. `baselines/e2_alns/threeshift_280_stageB_small_warmstart_probe_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/threeshift_280_stageB_small_warmstart_probe_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

360. `baselines/e2_alns/wallclock_battery_preflight_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/wallclock_battery_preflight_data/task_queue.csv:1: CSV表头=['algorithm', 'battery_kwh', 'comparison_mode', 'eval_budget', 'instance', 'prior_status', 'queue_action', 'replicate', 'runtime_cap_seconds', 'scenario', 'seed', 'size']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

361. `baselines/e2_alns/wallclock_battery_preflight_smoke_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/wallclock_battery_preflight_smoke_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

362. `baselines/e2_alns/wallclock_battery_preflight_stagea_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/wallclock_battery_preflight_stagea_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

363. `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

364. `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/chen_style_mechanism_case_trajectory/representative_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/chen_style_mechanism_case_trajectory/representative_gate/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

365. `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/staged_deepening_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/staged_deepening_gate/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

366. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/table4_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/table4_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

367. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/representative_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/representative_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

368. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/table4_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/table4_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

369. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/artifacts`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/artifacts/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

370. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/preflight_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/preflight_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

371. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/representative_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/representative_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

372. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/table4_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/table4_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

373. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-e2-result-strength-v4.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-e2-result-strength-v4.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

374. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-full-witness-replay-v4.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-full-witness-replay-v4.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

375. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/artifacts`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/artifacts/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

376. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/mechanism_case_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/mechanism_case_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

377. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/preflight_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/preflight_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

378. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/representative_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/representative_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

379. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/result_strength_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/result_strength_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

380. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/table4_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/table4_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

381. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-staged-v7-release-chain.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-staged-v7-release-chain.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

382. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-staged-v7-release-recovery-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-staged-v7-release-recovery-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

383. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-v7-paper-candidate-chain.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-v7-paper-candidate-chain.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

384. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_witness_replay`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_witness_replay/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

385. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/release_chain`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/release_chain/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

386. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/release_recovery_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/release_recovery_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

387. `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/result_strength_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/result_strength_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

388. `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_confirm`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_confirm/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

389. `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_dev`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_dev/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

390. `baselines/e2_final_campaign_20260720/p0_fuse/p0_gate/p0_resume_150c_log`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p0_fuse/p0_gate/p0_resume_150c_log/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

391. `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

392. `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

393. `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v6.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v6.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

394. `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

395. `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s4-v2-to-s5-chain-v4.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s4-v2-to-s5-chain-v4.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

396. `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s4-v2-to-s5-chain-v5.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s4-v2-to-s5-chain-v5.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

397. `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

398. `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

399. `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

400. `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v4.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v4.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

401. `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

402. `baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/.e2-s2-full-threeview.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/.e2-s2-full-threeview.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

403. `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

404. `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v2/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

405. `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v3/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

406. `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v4`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v4/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

407. `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/.e2-s3-representative.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/.e2-s3-representative.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

408. `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/.e2-s3-trajectory-v4-rerun.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/.e2-s3-trajectory-v4-rerun.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

409. `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/.e2-s3-trajectory-v4.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/.e2-s3-trajectory-v4.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

410. `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_01_instance_details`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_01_instance_details/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

411. `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v5`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v5/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

412. `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v6`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v6/raw_runs_v6.csv:1: CSV表头=['figure', 'series', 'source_row', 'x', 'y', 'source_path', 'source_sha256']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

413. `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v7`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v7/raw_runs_v7.csv:1: CSV表头=['figure', 'series', 'source_row', 'x', 'y', 'source_path', 'source_sha256']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

414. `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

415. `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

416. `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

417. `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

418. `baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

419. `baselines/e2_rerun_unified_01_20260727/.e2-rerun-unified-01-full-clean-restart.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_20260727/.e2-rerun-unified-01-full-clean-restart.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

420. `baselines/e2_rerun_unified_01_20260727/vehicle_feasibility_preflight/.e2-rerun-unified-01-vehicle-feasibility-preflight.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_20260727/vehicle_feasibility_preflight/.e2-rerun-unified-01-vehicle-feasibility-preflight.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

421. `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

422. `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v3.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v3.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

423. `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v4.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v4.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

424. `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v5.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v5.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

425. `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

426. `baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_engineering_import_halt/monitor_scene`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_engineering_import_halt/monitor_scene/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

427. `baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_monitor_schema_halts`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_monitor_schema_halts/raw_header_before_v4.csv:1: CSV表头=['instance_id', 'region', 'size_layer', 'customer_count', 'seed', 'arm', 'status', 'stop_iterations', 'last_strict_improvement_iteration', 'l_over_s', 'mv_critical_view', 'view_stop_iterations_json', 'view_last_improvements_json', 'view_l_over_s_json', 'trajectory_path', 'trajectory_sha256', 'final_cost', 'feasible', 'violation_count', 'cpu_seconds']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

428. `baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_non_sandbox_halt`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_non_sandbox_halt/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

429. `baselines/e3_ablation/e3_clock_semantics_governance_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_clock_semantics_governance_20260713/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

430. `baselines/e3_ablation/e3_clock_semantics_governance_20260713/attempt_01_wrong_bundle`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_clock_semantics_governance_20260713/attempt_01_wrong_bundle/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

431. `baselines/e3_ablation/e3_mismatch_formal_20260713_25`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_mismatch_formal_20260713_25/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

432. `baselines/e3_ablation/e3_mismatch_formal_20260713_50`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_mismatch_formal_20260713_50/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

433. `baselines/e3_ablation/e3_multitrip_formula_validation_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_formula_validation_20260713/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

434. `baselines/e3_ablation/e3_multitrip_model_gate_20260712`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_model_gate_20260712/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

435. `baselines/e3_ablation/e3_multitrip_search_gate_20260712`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_search_gate_20260712/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

436. `baselines/e3_ablation/e3_multitrip_structure_gate_20260712`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_structure_gate_20260712/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

437. `baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

438. `baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

439. `baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v3/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

440. `baselines/e3_ablation/e3_multitrip_structure_gate_v2_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_multitrip_structure_gate_v2_20260713/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

441. `baselines/e3_ablation/e3_story_forensic_audit_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_story_forensic_audit_20260713/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

442. `baselines/e3_ablation/e3_submission_20260711/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_submission_20260711/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

443. `baselines/e3_ablation/e3_submission_20260711/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_submission_20260711/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

444. `baselines/e3_ablation/e3_v10_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v10_clean_20260713/solutions/E3__200c__M0__seed1__fee0__eval200__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

445. `baselines/e3_ablation/e3_v10_clean_20260713/model_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v10_clean_20260713/model_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

446. `baselines/e3_ablation/e3_v10_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v10_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

447. `baselines/e3_ablation/e3_v10_clean_20260713/rehearsal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v10_clean_20260713/rehearsal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

448. `baselines/e3_ablation/e3_v11_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v11_clean_20260713/finalize_receipt.json:1: JSON顶层字段=['audit', 'carbon_timing_aggregate_reduction_pct_200c', 'carbon_timing_positive_seeds_200c', 'cooperation_mean_search_saving_pct_200c', 'cooperation_strict_wins_200c', 'cooperation_wilcoxon_greater_pvalue_200c', 'failures', 'fairness_all_min_profit_ratio_at_least_one', 'formal_run_count', 'story_classification', 'vehicle_reduction_seeds_200c', 'verdict']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

449. `baselines/e3_ablation/e3_v11_clean_20260713/final100`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v11_clean_20260713/final100/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

450. `baselines/e3_ablation/e3_v11_clean_20260713/formal70`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v11_clean_20260713/formal70/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

451. `baselines/e3_ablation/e3_v11_clean_20260713/model_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v11_clean_20260713/model_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

452. `baselines/e3_ablation/e3_v11_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v11_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

453. `baselines/e3_ablation/e3_v11_clean_20260713/promote100`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v11_clean_20260713/promote100/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

454. `baselines/e3_ablation/e3_v11_clean_20260713/rehearsal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v11_clean_20260713/rehearsal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

455. `baselines/e3_ablation/e3_v3_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v3_20260713/solutions/E3__200c__M0__seed1__fee0__eval8__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

456. `baselines/e3_ablation/e3_v3_20260713/smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v3_20260713/smoke/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

457. `baselines/e3_ablation/e3_v3_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v3_clean_20260713/solutions/E3__200c__M0__seed1__fee0__eval200__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

458. `baselines/e3_ablation/e3_v3_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v3_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

459. `baselines/e3_ablation/e3_v4_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v4_clean_20260713/solutions/E3__200c__M0__seed1__fee0__eval200__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

460. `baselines/e3_ablation/e3_v4_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v4_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

461. `baselines/e3_ablation/e3_v5_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v5_clean_20260713/solutions/E3__200c__M0__seed1__fee0__eval200__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

462. `baselines/e3_ablation/e3_v5_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v5_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

463. `baselines/e3_ablation/e3_v6_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v6_clean_20260713/solutions/E3__200c__M0__seed1__fee0__eval200__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

464. `baselines/e3_ablation/e3_v6_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v6_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

465. `baselines/e3_ablation/e3_v7_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v7_clean_20260713/model_gate/raw_runs.csv:1: CSV表头=['E_cv_direct', 'E_ev_indirect', 'E_total', 'actual_evals', 'adopted_source', 'battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'contract_sha256', 'cooperation_story_win', 'cost_carbon', 'cost_component_error', 'cost_elec', 'cost_fix', 'cost_fuel', 'cost_km', 'cost_occ', 'cost_transship', 'cross_site_accepted_candidates']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

466. `baselines/e3_ablation/e3_v7_clean_20260713/model_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v7_clean_20260713/model_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

467. `baselines/e3_ablation/e3_v7_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v7_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

468. `baselines/e3_ablation/e3_v7_clean_20260713/preflight/exhibit_smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v7_clean_20260713/preflight/exhibit_smoke/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

469. `baselines/e3_ablation/e3_v7_clean_20260713/rehearsal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v7_clean_20260713/rehearsal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

470. `baselines/e3_ablation/e3_v8_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v8_clean_20260713/solutions/E3__200c__M0__seed1__fee0__eval200__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

471. `baselines/e3_ablation/e3_v8_clean_20260713/model_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v8_clean_20260713/model_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

472. `baselines/e3_ablation/e3_v8_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v8_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

473. `baselines/e3_ablation/e3_v8_clean_20260713/preflight/exhibit_smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v8_clean_20260713/preflight/exhibit_smoke/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

474. `baselines/e3_ablation/e3_v8_clean_20260713/rehearsal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v8_clean_20260713/rehearsal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

475. `baselines/e3_ablation/e3_v9_clean_20260713`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v9_clean_20260713/solutions/E3__200c__M0__seed1__fee0__eval200__search.json:1: JSON顶层字段=['charging_actions', 'cross_site_services', 'routes']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

476. `baselines/e3_ablation/e3_v9_clean_20260713/model_gate`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v9_clean_20260713/model_gate/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

477. `baselines/e3_ablation/e3_v9_clean_20260713/preflight`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v9_clean_20260713/preflight/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

478. `baselines/e3_ablation/e3_v9_clean_20260713/rehearsal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e3_ablation/e3_v9_clean_20260713/rehearsal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

479. `baselines/e6_fairness/e6_participation_audit_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e6_fairness/e6_participation_audit_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

480. `baselines/e7_dynamic/e7_cross_depot_opportunity_probe_20260715`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_cross_depot_opportunity_probe_20260715/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

481. `baselines/e7_dynamic/e7_cross_depot_opportunity_probe_v2_20260715`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_cross_depot_opportunity_probe_v2_20260715/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

482. `baselines/e7_dynamic/e7_dynamic_emission_intensity_formal_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_dynamic_emission_intensity_formal_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

483. `baselines/e7_dynamic/e7_ex_post_participation_formal_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_ex_post_participation_formal_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

484. `baselines/e7_dynamic/e7_formal_shared_start_value_audit_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_formal_shared_start_value_audit_20260714/decision.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

485. `baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

486. `baselines/e7_dynamic/e7_full_mechanism_gate_v6_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_full_mechanism_gate_v6_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

487. `baselines/e7_dynamic/e7_full_mechanism_probe_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_full_mechanism_probe_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

488. `baselines/e7_dynamic/e7_full_mechanism_probe_v2_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_full_mechanism_probe_v2_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

489. `baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_4_v2_20260715`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_4_v2_20260715/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

490. `baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_50_v1_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_50_v1_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

491. `baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_v1_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_v1_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

492. `baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N114`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N114/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

493. `baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N221`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N221/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

494. `baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N322`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N322/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

495. `baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N114`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N114/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

496. `baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N221`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N221/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

497. `baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N322`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N322/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

498. `baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N114`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N114/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

499. `baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N221`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N221/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

500. `baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N322`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N322/stream_seed1.events.csv:1: CSV表头=['event_id', 'event_type', 't_appear', 'customer_id', 'old_demand', 'new_demand', 'x', 'y', 'delta_demand', 'old_ready_time', 'old_due_time', 'new_ready_time', 'new_due_time', 'time_window_action', 'demand_source', 'time_window_source', 'donor_instance_id', 'donor_customer_id', 'new_service_time', 'service_time_source']；未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

501. `baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

502. `baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715_pre_hygiene_patch_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715_pre_hygiene_patch_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

503. `baselines/e7_dynamic/e7_multinetwork_preflight_v3_halt_20260715`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_multinetwork_preflight_v3_halt_20260715/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

504. `baselines/e7_dynamic/e7_parent_child_recovery_gate_20260716`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_parent_child_recovery_gate_20260716/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

505. `baselines/e7_dynamic/e7_pre_recovery_gate_20260716`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_pre_recovery_gate_20260716/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

506. `baselines/e7_dynamic/e7_replay_invariants_audit_20260715`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_replay_invariants_audit_20260715/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

507. `baselines/e7_dynamic/e7_replay_invariants_audit_20260715_hash_contaminated_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_replay_invariants_audit_20260715_hash_contaminated_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

508. `baselines/e7_dynamic/e7_responsibility_scenario_design_20260714`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_responsibility_scenario_design_20260714/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

509. `baselines/e7_dynamic/e7_v2_20260714/formal`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/formal/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

510. `baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

511. `baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware_audit`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware_audit/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

512. `baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

513. `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_repair_known_stops`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/batched_repair_known_stops/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

514. `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stage1_8`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stage1_8/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

515. `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

516. `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400_asset_aware`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400_asset_aware/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

517. `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400_v2/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

518. `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_800`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_800/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

519. `baselines/e7_dynamic/e7_v2_20260714/hooks/failed_stage_budget_800_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/failed_stage_budget_800_v2/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

520. `baselines/e7_dynamic/e7_v2_20260714/hooks/failed_stage_service_time_v3_400`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/failed_stage_service_time_v3_400/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

521. `baselines/e7_dynamic/e7_v2_20260714/hooks/formal_batched_400_asset_aware`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/hooks/formal_batched_400_asset_aware/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

522. `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/formal_shared_start_400_route_fix_adaptive`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/monitor_runs/formal_shared_start_400_route_fix_adaptive/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

523. `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/formal_shared_start_400_route_fix_adaptive_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/monitor_runs/formal_shared_start_400_route_fix_adaptive_v3/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

524. `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_50_route_fix`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_50_route_fix/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

525. `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_8`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_8/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

526. `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_8_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_8_v2/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

527. `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stream1_400`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stream1_400/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

528. `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stream1_400_route_fix`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stream1_400_route_fix/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

529. `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_repair_known_stops`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/batched_repair_known_stops/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

530. `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stage1_8`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stage1_8/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

531. `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

532. `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_asset_aware`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_asset_aware/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

533. `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

534. `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_800`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_800/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

535. `baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_budget_800`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_budget_800/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

536. `baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_service_time_v3_400`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_service_time_v3_400/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

537. `baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

538. `baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

539. `baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v3`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v3/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

540. `baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_draft`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_draft/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

541. `baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_probe`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_probe/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

542. `baselines/e7_dynamic/e7_v2_20260714/preflight/paired_ten_stage`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/paired_ten_stage/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

543. `baselines/e7_dynamic/e7_v2_20260714/preflight/paired_two_stage`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/paired_two_stage/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

544. `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_50_route_fix`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_50_route_fix/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

545. `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_8`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_8/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

546. `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

547. `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400_route_fix`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400_route_fix/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

548. `baselines/e7_dynamic/e7_v2_20260714/preflight/two_worker_smoke`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/e7_v2_20260714/preflight/two_worker_smoke/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

549. `baselines/e7_dynamic/m1_dynamic_truth_gate_20260711/e2_replay_post_dynamic_port`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/e7_dynamic/m1_dynamic_truth_gate_20260711/e2_replay_post_dynamic_port/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

550. `baselines/experiment_infrastructure/absolute_execution_harness_20260725/.absolute-execution-harness-v1.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/experiment_infrastructure/absolute_execution_harness_20260725/.absolute-execution-harness-v1.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

551. `baselines/experiment_infrastructure/absolute_execution_harness_20260725/.absolute-execution-harness-v2.monitor`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/experiment_infrastructure/absolute_execution_harness_20260725/.absolute-execution-harness-v2.monitor/done.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

552. `baselines/experiment_infrastructure/absolute_execution_harness_20260725/integration_gate_v2`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/experiment_infrastructure/absolute_execution_harness_20260725/integration_gate_v2/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

553. `baselines/formal_20260621_10001_lmain_10seed`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/formal_20260621_10001_lmain_10seed/raw_runs.csv:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

554. `baselines/model_verification/china81_nonlinear_core_nl0_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/model_verification/china81_nonlinear_core_nl0_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

555. `baselines/model_verification/china81_nonlinear_dynamic_nl3a_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/model_verification/china81_nonlinear_dynamic_nl3a_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

556. `baselines/model_verification/china81_nonlinear_schedule_nl1_20260720`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/model_verification/china81_nonlinear_schedule_nl1_20260720/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

557. `baselines/model_verification/paper_math_audit_20260716`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/model_verification/paper_math_audit_20260716/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

558. `baselines/model_verification/two_layer_model_gate_20260716`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/model_verification/two_layer_model_gate_20260716/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

559. `baselines/statistics/mc002_compute_power_20260718`：缺少可区分P1-P5的engine、源文件绑定或runner调用证据。证据：baselines/statistics/mc002_compute_power_20260718/metadata.json:未出现可区分P1-P4的engine、源文件、runner导入或调用字段，且无明确零搜索字段

## 指纹乙分组键口径

对每个带 seed 或同义逐单元种子列的原始记录 CSV，以算例、实验组、算法/arm、视角、参数、预算上限等配置列分组；种子列、`unit_id`、任务 ID、实际耗时、状态/错误、结果度量和文件哈希不进入分组键。`max_runtime_seconds`、`mip_time_limit_seconds` 等上限列属于配置列。目标值侧按实际列名读取 objective、total cost、full-model cost、objective float hex 以及路线/解结构哈希。只有同一分组内至少有两个不同种子且存在非空目标值或结构值时，才计入 `fingerprint_b_groups`。下列内容逐包列出实际键、种子列、值列与种子数分布；无种子列或无可比较值的包也保留原始原因。

- `baselines`：source=baselines/raw_runs.csv; keys=['instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/algorithm_foundation/mda_ils_vns_adaptive_20260720`：source=baselines/algorithm_foundation/mda_ils_vns_adaptive_20260720/raw_runs.csv; keys=['instance', 'config', 'gap_percent', 'iterations']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_foundation/mda_ils_vns_foundation_20260720`：source=baselines/algorithm_foundation/mda_ils_vns_foundation_20260720/raw_runs.csv; keys=['instance', 'config', 'gap_percent', 'iterations']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_foundation/mda_ils_vns_late_stage_20260720`：source=baselines/algorithm_foundation/mda_ils_vns_late_stage_20260720/raw_runs.csv; keys=['instance', 'config', 'gap_percent', 'iterations']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_foundation/mda_ils_vns_parameter_race_20260720`：source=baselines/algorithm_foundation/mda_ils_vns_parameter_race_20260720/raw_runs.csv; keys=['instance', 'config', 'gap_percent', 'iterations']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719`：source=baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['index', 'instance', 'clients', 'depots', 'vehicles_per_depot', 'variant', 'split', 'representative', 'semantic_checks', 'semantic_failures', 'independent_bks_valid', 'pyvrp_bks_valid', 'current_verified_bks', 'vcgp_best_2013', 'vcgp_mean_2013', 'mdfiha_best_2026', 'mdfiha_mean_2026', 'mdfiha_etga_best_2026', 'mdfiha_etga_mean_2026', 'strongest_known_target', 'strongest_target_sources']

- `baselines/algorithm_foundation/mpd_ils_vns_dual_regime_20260720`：source=baselines/algorithm_foundation/mpd_ils_vns_dual_regime_20260720/raw_runs.csv; keys=['instance', 'arm', 'gap_percent', 'iterations']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_foundation/mpils_mvns_c2_a_constant_diagnosis_20260720`：source=baselines/algorithm_foundation/mpils_mvns_c2_a_constant_diagnosis_20260720/raw_runs.csv; keys=['instance', 'iterations']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_foundation/mpils_mvns_c2_g0_20260720`：source=baselines/algorithm_foundation/mpils_mvns_c2_g0_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['gate', 'repeat', 'iterations', 'mode', 'runtime_seconds', 'distance', 'routes', 'feasible', 'signature', 'independent_validation']

- `baselines/algorithm_foundation/mpils_mvns_c2_g0_license_repair_20260720`：source=baselines/algorithm_foundation/mpils_mvns_c2_g0_license_repair_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'upstream_sha256', 'local_sha256', 'byte_exact']

- `baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_20260720`：source=baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'detail']

- `baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_v2_20260720`：source=baselines/algorithm_foundation/mpils_mvns_c2_g0_source_hygiene_repair_v2_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed']

- `baselines/algorithm_foundation/mpils_mvns_c2_g1_b_first_fire_20260720`：source=baselines/algorithm_foundation/mpils_mvns_c2_g1_b_first_fire_20260720/raw_runs.csv; keys=['instance', 'candidate_gap_to_bks_percent']; seed=['seed']; values=['mother_objective', 'candidate_objective']; seed_counts={}

- `baselines/algorithm_foundation/mpils_mvns_c2_g1_b_second_fire_20260720`：source=baselines/algorithm_foundation/mpils_mvns_c2_g1_b_second_fire_20260720/raw_runs.csv; keys=['instance', 'candidate_gap_to_bks_percent']; seed=['seed']; values=['mother_objective', 'candidate_objective']; seed_counts={}

- `baselines/algorithm_foundation/mpils_mvns_three_instance_sentinel_20260719`：source=baselines/algorithm_foundation/mpils_mvns_three_instance_sentinel_20260719/raw_runs.csv; keys=['instance', 'mpils_mvns_gap_to_bks_percent', 'population_unique_insertions']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_foundation/pyvrp_v13_time_quality_curve_20260720`：source=baselines/algorithm_foundation/pyvrp_v13_time_quality_curve_20260720/raw_runs.csv; keys=['instance', 'gap_percent', 'iterations']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_foundation/remix_hgs_supplier_bridge_20260719`：source=baselines/algorithm_foundation/remix_hgs_supplier_bridge_20260719/raw_runs.csv; keys=['iterations']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_foundation/remix_hgs_supplier_bridge_v2_20260719`：source=baselines/algorithm_foundation/remix_hgs_supplier_bridge_v2_20260719/raw_runs.csv; keys=[]; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_foundation/remix_pr17a_behavior_gate_20260719`：source=baselines/algorithm_foundation/remix_pr17a_behavior_gate_20260719/raw_runs.csv; keys=['mode', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_foundation/remix_pr17a_behavior_gate_v2_20260719`：source=baselines/algorithm_foundation/remix_pr17a_behavior_gate_v2_20260719/raw_runs.csv; keys=['mode', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_foundation/remix_same_path_equivalence_gate_20260719`：source=baselines/algorithm_foundation/remix_same_path_equivalence_gate_20260719/raw_runs.csv; keys=['mode', 'iterations']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_foundation/remix_v13_six_instance_development_20260719`：source=baselines/algorithm_foundation/remix_v13_six_instance_development_20260719/raw_runs.csv; keys=['instance', 'remix_gap_to_bks_percent']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_foundation/x_cvrp_selection_20260719`：source=baselines/algorithm_foundation/x_cvrp_selection_20260719/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['index', 'name', 'customers', 'catalogue_k', 'capacity', 'bks', 'optimal', 'role', 'downloaded_and_audited', 'instance_url', 'bks_url', 'instance_sha256', 'instance_normalised_sha256', 'bks_solution_sha256', 'bks_all_checks_pass']

- `baselines/algorithm_prototypes/algo_reset_20260719/exact_route_pool_microprobe`：source=baselines/algorithm_prototypes/algo_reset_20260719/exact_route_pool_microprobe/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['budget', 'source_parents_available', 'complete_recombination_calls', 'candidate_found', 'additive_score', 'selected_sources', 'coverage_exact']

- `baselines/algorithm_prototypes/algo_reset_20260719/hgs_alns_offspring_fusion_microgate`：source=baselines/algorithm_prototypes/algo_reset_20260719/hgs_alns_offspring_fusion_microgate/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate`：source=baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval2`：source=baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval2/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval4`：source=baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval4/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval8`：source=baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate_interval8/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/homberger_headroom_audit`：source=baselines/algorithm_prototypes/algo_reset_20260719/homberger_headroom_audit/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/mechanism_normalized_fresh_gate`：source=baselines/algorithm_prototypes/algo_reset_20260719/mechanism_normalized_fresh_gate/raw_runs.csv; keys=[]; seed=['seed']; values=['baseline_v7_cost', 'candidate_cost']; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/mechanism_route_pool_incremental_gate`：source=baselines/algorithm_prototypes/algo_reset_20260719/mechanism_route_pool_incremental_gate/raw_runs.csv; keys=['hgs_internal_no_improvement_iterations']; seed=['seed']; values=['hgs_source_cost', 'alns_source_cost']; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/route_core_microgate`：source=baselines/algorithm_prototypes/algo_reset_20260719/route_core_microgate/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/algo_reset_20260719/route_core_split_sweep`：source=baselines/algorithm_prototypes/algo_reset_20260719/route_core_split_sweep/raw_runs.csv; keys=['instance', 'algorithm', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/boundary_probe_20260726`：source=baselines/algorithm_prototypes/boundary_probe_20260726/d1_raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['final_cost']; seed_counts={}

- `baselines/algorithm_prototypes/carbon_nonlinear_charging_20260718`：source=baselines/algorithm_prototypes/carbon_nonlinear_charging_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case_id', 'algorithm', 'budget', 'status', 'candidates_generated', 'complete_evaluations', 'feasible_evaluations', 'label_expansions', 'dominance_prunes', 'pointwise_match_to_exhaustive', 'best_plan_index', 'best_objective', 'best_finish_seconds', 'best_terminal_soc_kwh', 'best_price_cost', 'best_carbon_amount', 'charge_action_count', 'note']

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/adapter_g0_zero_search_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/adapter_g0_zero_search_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'arm', 'search_evaluations', 'objective', 'feasible', 'violation_count', 'solution_sha256', 'route_count', 'ev_route_count', 'charging_action_count', 'total_distance_m', 'total_emissions_kg', 'mechanism_query_count']

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g2_three_case_diagnostic`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g2_three_case_diagnostic/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g3_multiview_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g3_multiview_gate/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g4_equal_compute_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g4_equal_compute_gate/raw_runs.csv; keys=['instance_id', 'arm', 'population_count', 'population_seconds']; seed=['base_seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g5_adaptive_racing_diagnostic`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g5_adaptive_racing_diagnostic/raw_runs.csv; keys=['instance_id', 'arm']; seed=['base_seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h0_true_hgs_adapter_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h0_true_hgs_adapter_gate/raw_runs.csv; keys=['instance_id', 'engine_family']; seed=['seed']; values=['objective', 'initial_objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h1_population_archive_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h1_population_archive_gate/raw_runs.csv; keys=['instance_id', 'population_size']; seed=['seed']; values=['proxy_best_exact_objective', 'archive_best_exact_objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h2_fresh_population_archive_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h2_fresh_population_archive_gate/raw_runs.csv; keys=['instance_id', 'population_size']; seed=['seed']; values=['proxy_best_exact_objective', 'archive_best_exact_objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h3_epochal_migration_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h3_epochal_migration_gate/raw_runs.csv; keys=['instance_id']; seed=['base_seed']; values=['control_objective', 'candidate_objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h4_route_pool_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h4_route_pool_gate/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['best_parent_objective', 'final_objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h5_fresh_route_pool_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h5_fresh_route_pool_gate/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['best_parent_objective', 'final_objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h6_multiseed_route_pool_gate`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/h6_multiseed_route_pool_gate/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['best_parent_objective', 'final_objective']; seed_counts={3: 3}

- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pipeline_g1_one_case_smoke`：source=baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pipeline_g1_one_case_smoke/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/algorithm_prototypes/china81_vs_opensource_20260727`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/collaboration_fairness_20260718`：source=baselines/algorithm_prototypes/collaboration_fairness_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm_id', 'budget_limit', 'complete_evaluations', 'budget_respected', 'candidate_count', 'moves', 'initial_total_cost', 'initial_total_deficit', 'best_total_cost', 'best_total_deficit', 'best_assignment', 'best_profit', 'best_deficit', 'proximity_operator_enabled', 'fairness_operator_enabled', 'first_candidate_differs_from_base', 'independent_recompute_match']

- `baselines/algorithm_prototypes/dual_guided_columns_20260726`：source=baselines/algorithm_prototypes/dual_guided_columns_20260726/a3_raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'a3_cost', 'bks', 'a3_error_pct', 'seed_runs_best', 'pool_after_seeds', 'pool_final', 'guided_only_columns_selected', 'total_iterations', 'cpu_seconds']

- `baselines/algorithm_prototypes/dual_guided_resource_order_20260725/.dual-guided-engineering-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/dual_guided_resource_order_20260725/.dual-guided-engineering.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/dual_guided_resource_order_20260725/engineering_gate_v1`：source=baselines/algorithm_prototypes/dual_guided_resource_order_20260725/engineering_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['candidate_count', 'dp_states', 'error', 'instance_id', 'lp_primal_residual', 'lp_stationarity_residual', 'pairs_json', 'peak_rss_bytes', 'positive_scarcity_resources', 'route_pool_columns', 'status']

- `baselines/algorithm_prototypes/dynamic_replanning_20260718`：source=baselines/algorithm_prototypes/dynamic_replanning_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['probe_id', 'variant', 'budget', 'complete_evaluations', 'cheap_checks', 'activity_count', 'status', 'details_json']

- `baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/direct_improvement_gate_v1_abort_packaging`：source=baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/direct_improvement_gate_v1_abort_packaging/raw_runs.csv; keys=['instance_id', 'duplicate_fraction']; seed=['seed']; values=['input_objective', 'final_objective']; seed_counts={}

- `baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/direct_improvement_gate_v2_recovered_no_search`：source=baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/direct_improvement_gate_v2_recovered_no_search/raw_runs.csv; keys=['instance_id', 'duplicate_fraction']; seed=['seed']; values=['input_objective', 'final_objective']; seed_counts={}

- `baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/g0_gate_v1`：source=baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/g0_gate_v1/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['expected_objective', 'replayed_objective', 'candidate_complete_objective_evaluations']; seed_counts={}

- `baselines/algorithm_prototypes/fleet_charging_20260718`：source=baselines/algorithm_prototypes/fleet_charging_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['candidate_id', 'budget', 'status', 'complete_candidate_evaluations', 'screen_evaluations', 'route_oracle_calls', 'oracle_cache_hits', 'reference_evaluations', 'active', 'selected_mode', 'selected_candidate', 'objective_abstract', 'regret_abstract', 'independent_replay_pass', 'notes']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-g1-mechanical-release-chain-v1.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-g1-release-chain-v1.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-real-bundle-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-real-bundle-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g0-worker-probe-g1-release-chain-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-micro-v5-decoder-repair.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-micro-v6-coverage-contract.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-six-worker-resource-probe-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/.genuine-hybrid-g1-six-worker-resource-probe-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_mechanical_release_chain_v1`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_mechanical_release_chain_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['stage', 'status', 'decision', 'detail', 'workers']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_release_chain_v2`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_g1_release_chain_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['stage', 'status', 'decision', 'detail', 'workers']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v1`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'stratum', 'region', 'status', 'detail', 'customer_count', 'city_count', 'cities', 'scenario_date', 'time_profile_row_count', 'shenzhen_independent_price_area', 'witness_completion_cost', 'witness_emissions_kg', 'direct_violation_count', 'exact_violation_count', 'decoder_candidate_count', 'decoder_complete_evaluations', 'decoder_feasible_evaluations', 'decoder_selected_cost', 'decoder_depot_count', 'decoder_vehicle_types', 'decoder_cache_entries', 'decoder_cache_hits', 'decoder_cache_misses', 'projection_native_route_count', 'projection_route_identity_preserved', 'roundtrip_completion_cost', 'search_iterations']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v2`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'stratum', 'region', 'status', 'detail', 'customer_count', 'city_count', 'cities', 'scenario_date', 'time_profile_row_count', 'shenzhen_independent_price_area', 'witness_completion_cost', 'witness_emissions_kg', 'direct_violation_count', 'exact_violation_count', 'decoder_candidate_count', 'decoder_complete_evaluations', 'decoder_feasible_evaluations', 'decoder_selected_cost', 'decoder_diagnostics_json', 'decoder_depot_count', 'decoder_vehicle_types', 'decoder_cache_entries', 'decoder_cache_hits', 'decoder_cache_misses', 'projection_native_route_count', 'projection_route_identity_preserved', 'roundtrip_completion_cost', 'search_iterations']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v3`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_real_bundle_gate_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'stratum', 'region', 'status', 'detail', 'customer_count', 'city_count', 'cities', 'scenario_date', 'time_profile_row_count', 'shenzhen_independent_price_area', 'witness_completion_cost', 'witness_emissions_kg', 'direct_violation_count', 'exact_violation_count', 'decoder_candidate_count', 'decoder_complete_evaluations', 'decoder_feasible_evaluations', 'decoder_selected_cost', 'decoder_diagnostics_json', 'decoder_depot_count', 'decoder_vehicle_types', 'decoder_cache_entries', 'decoder_cache_hits', 'decoder_cache_misses', 'projection_native_route_count', 'projection_route_identity_preserved', 'roundtrip_completion_cost', 'search_iterations']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v10`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v10/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v11`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v11/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v12`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v12/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v13`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v13/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v2`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v3`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v4`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v4/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v5`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v5/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v6`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v6/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v7`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v7/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v8`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v8/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v9`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g0_static_semantics_gate_v9/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'status', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_gate_v6_coverage_contract`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_gate_v6_coverage_contract/raw_runs.csv; keys=['instance_id', 'arm', 'customer_count']; seed=['seed']; values=['initial_objective', 'best_objective', 'replay_objective']; seed_counts={}

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_v5_decoder_repair_abort`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_v5_decoder_repair_abort/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['stage', 'status', 'reason', 'partial_result_files_counted', 'objective_values_read', 'scientific_use']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v2`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['task_id', 'instance_id', 'replicate', 'status', 'elapsed_seconds', 'peak_rss_mb', 'detail']

- `baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v3`：source=baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_six_worker_resource_probe_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['task_id', 'instance_id', 'replicate', 'status', 'elapsed_seconds', 'peak_rss_mb', 'detail']

- `baselines/algorithm_prototypes/hgs_adaptive_elite_alns_20260719/postrun_record_sync_audit`：source=baselines/algorithm_prototypes/hgs_adaptive_elite_alns_20260719/postrun_record_sync_audit/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/hgs_adaptive_elite_alns_20260719/public_bks_microgate`：source=baselines/algorithm_prototypes/hgs_adaptive_elite_alns_20260719/public_bks_microgate/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/hgs_adaptive_elite_alns_20260719/public_bks_microgate_independent_audit`：source=baselines/algorithm_prototypes/hgs_adaptive_elite_alns_20260719/public_bks_microgate_independent_audit/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/hgs_ils_cross_domain_20260725/g0_preflight_v1`：source=baselines/algorithm_prototypes/hgs_ils_cross_domain_20260725/g0_preflight_v1/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['start_exact_objective', 'best_exact_objective']; seed_counts={}

- `baselines/algorithm_prototypes/hgs_safe_record_lns_20260719/public_bks_seed1_gate`：source=baselines/algorithm_prototypes/hgs_safe_record_lns_20260719/public_bks_seed1_gate/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/hgs_safe_record_lns_20260719/public_bks_seed1_gate_independent_audit`：source=baselines/algorithm_prototypes/hgs_safe_record_lns_20260719/public_bks_seed1_gate_independent_audit/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'detail', 'search_evaluations']

- `baselines/algorithm_prototypes/hgs_safe_record_lns_20260719/zero_search_safety_gate`：source=baselines/algorithm_prototypes/hgs_safe_record_lns_20260719/zero_search_safety_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/joint_decoder_headroom_20260725`：source=baselines/algorithm_prototypes/joint_decoder_headroom_20260725/m1_raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-engineering-v1.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-engineering-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/.jrc-exact-neighborhood-g0-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v1`：source=baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['status', 'real_instance_loaded', 'real_neighborhood_search_launched', 'six_customer_proof_executed', 'g0_launched']

- `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v2`：source=baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['task_id', 'instance_id', 'arm', 'start_cost', 'selected_customers', 'selected_customer_count', 'route_indices', 'old_pair_cost', 'worker_pid', 'worker_module_file', 'worker_cwd', 'peak_rss_mib', 'real_neighborhood_search_launched']

- `baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/g0_gate_v2`：source=baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/g0_gate_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['status']

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-adaptive.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-foundation-rerun.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-foundation.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-ils-vns-late-stage.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mda-parameter-race.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mpd-dual-regime-rerun.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/.mpd-dual-regime.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_share_001`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_share_001/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_two_basin`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/confirm_b100_two_basin/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_20c_b500_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_20c_b500_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 3}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_development_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/fleet_charge_280_development_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/functional_two_basin`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/functional_two_basin/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_functional`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_functional/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_multidepot_scale_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_multidepot_scale_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 15}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_functional`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_functional/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_multidepot_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/intensified_relocate_multidepot_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 15}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v4_b100_minimal_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v4_b100_minimal_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 15}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 15}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_optimized_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_decoder_optimized_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 15}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_minimal_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v5_carbon_b100_minimal_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 15}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v6_b100_shared_base_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v6_b100_shared_base_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 18}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v7_stage1_closeout_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v7_stage1_closeout_gate/raw_runs.csv; keys=['family', 'instance', 'algorithm', 'budget']; seed=['seed']; values=['cost']; seed_counts={3: 17}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v8_interleaved_microgate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v8_interleaved_microgate/raw_runs.csv; keys=['instance', 'algorithm', 'budget']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v9_seeded_microgate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v9_seeded_microgate/raw_runs.csv; keys=['instance', 'algorithm', 'budget']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_functional`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_functional/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_multidepot_scale_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/memetic_multidepot_scale_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 15}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_component_ablation`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_component_ablation/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 6}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_confirmation_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_confirmation_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 12}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_seed1_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_b100_seed1_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_cheapest_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_cheapest_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_space_time_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/official_v2_space_time_gate/raw_runs.csv; keys=['instance', 'budget', 'algorithm', 'reported_algorithm']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_gate_25c`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_gate_25c/raw_runs.csv; keys=['instance', 'switch_enabled', 'budget']; seed=['seed']; values=['alns_cost', 'hgs_cost', 'routed_cost']; seed_counts={3: 3}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_multidepot_scale_gate`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/regime_switch_multidepot_scale_gate/raw_runs.csv; keys=['instance', 'switch_enabled', 'budget']; seed=['seed']; values=['alns_cost', 'hgs_cost', 'routed_cost']; seed_counts={3: 5}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_005`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_005/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_010`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_010/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_015`：source=baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/tuning_share_015/raw_runs.csv; keys=['instance', 'budget', 'algorithm']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/mvhgssp_bks_reproduction_20260727`：source=baselines/algorithm_prototypes/mvhgssp_bks_reproduction_20260727/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'bks_2013', 'pure_hgs_warmstart', 'mvhgssp_warmstart', 'met_target', 'cpu_seconds']

- `baselines/algorithm_prototypes/mvhgssp_bks_reproduction_full_20260727`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate`：source=baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v1_no_failure_stop`：source=baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v1_no_failure_stop/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v2_pre_rng_fix`：source=baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/equal_time_development_gate_v2_pre_rng_fix/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=['cost']; seed_counts={3: 9}

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/appledouble_hash_manifest_repair_v1`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/appledouble_hash_manifest_repair_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['new_entries', 'new_manifest_valid', 'old_appledouble_entries', 'old_entries', 'ordinary_old_hashes_match', 'search_evaluations', 'target']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/bounded_segment_behavior_gate`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/bounded_segment_behavior_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'binding', 'mode', 'source_cost', 'candidate_present', 'candidate_cost', 'feasible', 'selected_distance_delta', 'selected_local_model_delta', 'source_shortlist', 'max_positions_per_source', 'candidate_build_attempts', 'exact_shortlist', 'completion_shortlist', 'complete_candidate_evaluations', 'activity_json']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/bounded_segment_behavior_gate_v2_china81_scope`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/bounded_segment_behavior_gate_v2_china81_scope/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'binding', 'mode', 'source_cost', 'candidate_present', 'candidate_cost', 'feasible', 'selected_distance_delta', 'selected_local_model_delta', 'source_shortlist', 'max_positions_per_source', 'candidate_build_attempts', 'exact_shortlist', 'completion_shortlist', 'complete_candidate_evaluations', 'activity_json']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/bounded_segment_behavior_gate_v3_china81_scope`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/bounded_segment_behavior_gate_v3_china81_scope/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'binding', 'mode', 'source_cost', 'candidate_present', 'candidate_cost', 'feasible', 'selected_distance_delta', 'selected_local_model_delta', 'source_shortlist', 'max_positions_per_source', 'candidate_build_attempts', 'exact_shortlist', 'completion_shortlist', 'complete_candidate_evaluations', 'activity_json']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/china81_private_fair_gate_preflight`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/china81_private_fair_gate_preflight/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v2`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v3_final`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v3_final/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v4_final_after_appledouble_repair`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v4_final_after_appledouble_repair/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v5_authoritative`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/independent_stage1_audit_v5_authoritative/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'detail', 'passed', 'search_evaluations']

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/public_bks_alns_warm_hgs_gate`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/public_bks_alns_warm_hgs_gate/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/public_bks_core_microgate`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/public_bks_core_microgate/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/outcome_first_hybrid_20260719/public_bks_dual_elite_hgs_gate`：source=baselines/algorithm_prototypes/outcome_first_hybrid_20260719/public_bks_dual_elite_hgs_gate/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/rce_hgs_misrank_20260725/.rce-hgs-misrank-engineering.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/rce_hgs_misrank_20260725/.rce-hgs-misrank-formal.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/g0_gate_v1`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/g0_gate_v2`：source=baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/g0_gate_v2/raw_runs.csv; keys=['instance_id', 'customer_count']; seed=['seed']; values=['incumbent_objective', 'decoded_objective', 'candidate_complete_objective_evaluations', 'validation_objective_replays']; seed_counts={}

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-g0-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v1`：source=baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['candidate_objectives_evaluated', 'error', 'status', 'task_id']

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v2`：source=baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['candidate_objectives_evaluated', 'error', 'instance_id', 'lane', 'status', 'task_id']

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v3`：source=baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['candidate_objectives_evaluated', 'complete_labels', 'error', 'extensions', 'instance_id', 'lane', 'negative_routes_observed_without_complete_scoring', 'peak_rss_bytes', 'positive_resource_prices', 'status', 'task_id']

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/g0_gate_v3`：source=baselines/algorithm_prototypes/resource_slot_pricing_20260725/g0_gate_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['complete_candidate_evaluations', 'error', 'instance_id', 'label_extensions', 'lane', 'output_objective', 'start_objective', 'status', 'task_id', 'violation_count']

- `baselines/algorithm_prototypes/route_column_mip_assembly_20260725/direct_headroom_gate_v1`：source=baselines/algorithm_prototypes/route_column_mip_assembly_20260725/direct_headroom_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['absolute_improvement', 'best_parent_objective', 'comparison_baseline', 'customer_count', 'error', 'generated_options_before_dedup', 'instance_id', 'new_boundary_columns', 'new_mip_charger_feasible', 'new_mip_dual_bound', 'new_mip_exact_cover', 'new_mip_fleet_feasible', 'new_mip_gap', 'new_mip_integral', 'new_mip_message', 'new_mip_node_count', 'new_mip_seconds', 'new_mip_status', 'new_mip_status_class', 'new_pool_columns', 'new_pool_objective', 'new_selected_routes', 'no_loss', 'old_mip_charger_feasible', 'old_mip_dual_bound', 'old_mip_exact_cover', 'old_mip_fleet_feasible', 'old_mip_gap', 'old_mip_integral', 'old_mip_message', 'old_mip_node_count', 'old_mip_seconds', 'old_mip_status', 'old_mip_status_class', 'old_pool_columns', 'old_pool_objective', 'old_selected_routes', 'parent_count', 'parent_objectives_json', 'peak_rss_bytes', 'relative_improvement_pct', 'selected_new_boundaries_json', 'selected_new_boundary_count', 'status', 'strict_improvement', 'wall_seconds', 'witness_path']

- `baselines/algorithm_prototypes/route_column_mip_assembly_20260725/g0_gate_v1`：source=baselines/algorithm_prototypes/route_column_mip_assembly_20260725/g0_gate_v1/raw_runs.csv; keys=['instance_id', 'customer_count']; seed=['seed']; values=['incumbent_objective', 'assembled_objective']; seed_counts={}

- `baselines/algorithm_prototypes/tailored_dp_vns_20260725/direct_improvement_gate_v1`：source=baselines/algorithm_prototypes/tailored_dp_vns_20260725/direct_improvement_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'input_objective', 'final_objective', 'improvement', 'improvement_pct', 'improved', 'complete_evaluations', 'feasible_evaluations', 'infeasible_evaluations', 'duplicate_evaluations', 'duplicate_fraction', 'elapsed_seconds', 'stop_reason']

- `baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/g0_gate`：source=baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/g0_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'arm', 'status', 'scientific_outcome_available', 'error_type', 'error']

- `baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/resource_activity_audit_v1`：source=baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/resource_activity_audit_v1/raw_runs.csv; keys=['instance_id', 'arm', 'customer_count', 'ev_customer_share']; seed=['seed']; values=[]; seed_counts={}

- `baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/t0_engineering_gate`：source=baselines/algorithm_prototypes/type_aware_resource_chromosome_20260725/t0_engineering_gate/raw_runs.csv; keys=['instance_id', 'customer_count']; seed=['seed']; values=['dp_proxy_cost']; seed_counts={2: 7}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['mode', 'budget', 'enabled', 'start_cost', 'evaluations', 'candidate_scores', 'actual_moves', 'raw_cost', 'final_cost', 'raw_exact_signature', 'raw_skeleton_signature', 'history_fingerprint', 'operator_fingerprint', 'main_rng_fingerprint', 'selector_rng_fingerprint', 'prescore_count', 'prescore_reference_replays', 'archive_count', 'archive_completion_call_count', 'archive_completion_reference_replays', 'raw_search_independent_replays', 'selected_final_independent_replays', 'independent_final_replays', 'post_search_full_solution_replays', 'route_local_exact_evaluations', 'route_proxy_evaluations', 'route_local_schedule_evaluations', 'mechanism_feasibility_checks', 'mechanism_candidate_evaluations', 'worker_recomputed_cost', 'worker_elapsed_seconds']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt1_control_prescore`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt1_control_prescore/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['mode', 'budget', 'enabled', 'evaluations', 'candidate_scores', 'actual_moves', 'raw_cost', 'final_cost', 'raw_exact_signature', 'raw_skeleton_signature', 'history_fingerprint', 'operator_fingerprint', 'main_rng_fingerprint', 'selector_rng_fingerprint', 'prescore_count', 'archive_count', 'mechanism_candidate_evaluations', 'worker_elapsed_seconds']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt2_underreported_ledgers`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt2_underreported_ledgers/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['mode', 'budget', 'enabled', 'evaluations', 'candidate_scores', 'actual_moves', 'raw_cost', 'final_cost', 'raw_exact_signature', 'raw_skeleton_signature', 'history_fingerprint', 'operator_fingerprint', 'main_rng_fingerprint', 'selector_rng_fingerprint', 'prescore_count', 'archive_count', 'mechanism_candidate_evaluations', 'worker_elapsed_seconds']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt4_missing_hard_assertions`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt4_missing_hard_assertions/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['mode', 'budget', 'enabled', 'start_cost', 'evaluations', 'candidate_scores', 'actual_moves', 'raw_cost', 'final_cost', 'raw_exact_signature', 'raw_skeleton_signature', 'history_fingerprint', 'operator_fingerprint', 'main_rng_fingerprint', 'selector_rng_fingerprint', 'prescore_count', 'prescore_reference_replays', 'archive_count', 'archive_completion_call_count', 'archive_completion_reference_replays', 'raw_search_independent_replays', 'selected_final_independent_replays', 'independent_final_replays', 'post_search_full_solution_replays', 'route_local_exact_evaluations', 'route_proxy_evaluations', 'route_local_schedule_evaluations', 'mechanism_feasibility_checks', 'mechanism_candidate_evaluations', 'worker_recomputed_cost', 'worker_elapsed_seconds']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt5_appledouble_detected`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_invalid_attempt5_appledouble_detected/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['mode', 'budget', 'enabled', 'start_cost', 'evaluations', 'candidate_scores', 'actual_moves', 'raw_cost', 'final_cost', 'raw_exact_signature', 'raw_skeleton_signature', 'history_fingerprint', 'operator_fingerprint', 'main_rng_fingerprint', 'selector_rng_fingerprint', 'prescore_count', 'prescore_reference_replays', 'archive_count', 'archive_completion_call_count', 'archive_completion_reference_replays', 'raw_search_independent_replays', 'selected_final_independent_replays', 'independent_final_replays', 'post_search_full_solution_replays', 'route_local_exact_evaluations', 'route_proxy_evaluations', 'route_local_schedule_evaluations', 'mechanism_feasibility_checks', 'mechanism_candidate_evaluations', 'worker_recomputed_cost', 'worker_elapsed_seconds']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_behavior_gate_monitor`：该包无逐单元原始记录CSV

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_p1_failure_audit`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_p1_failure_audit/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['record_type', 'status', 'usable_score_count', 'reason']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/contextual_expert_behavior_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/contextual_expert_behavior_gate/raw_runs.csv; keys=['budget']; seed=['seed']; values=['final_cost', 'objective_match']; seed_counts={}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/contextual_expert_p1_training_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/contextual_expert_p1_training_gate/raw_runs.csv; keys=['instance', 'arm', 'algorithm', 'budget', 'terminal_completion_enabled']; seed=['seed']; values=['objective_match']; seed_counts={}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/electrification_relocate_resize_behavior_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/electrification_relocate_resize_behavior_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['status', 'exception_type', 'message']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/electrification_relocate_resize_behavior_gate_execution_recovery_v2`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/electrification_relocate_resize_behavior_gate_execution_recovery_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['scenario', 'instance', 'source_arm', 'source_cost', 'final_cost', 'objective_delta', 'improvement_percent', 'source_cv_routes', 'final_cv_routes', 'cv_route_reduction', 'changed', 'feasible', 'enumerated_moves', 'neutral_feasible_moves', 'unique_neutral_moves', 'prescored_moves', 'prescore_selected_moves', 'terminal_completion_calls', 'counterfactual_terminal_completion_calls', 'total_terminal_completion_calls', 'terminal_full_solution_replays', 'terminal_route_local_exact_evaluations', 'terminal_route_proxy_evaluations', 'terminal_route_local_schedule_evaluations', 'terminal_feasibility_checks', 'counterfactual_full_solution_replays', 'counterfactual_feasibility_checks', 'counterfactual_independent_replays', 'exact_candidate_independent_replays', 'exact_candidate_feasibility_checks', 'source_full_solution_replays', 'source_feasibility_checks', 'neutral_candidate_attempts', 'neutral_feasibility_checks', 'neutral_normalization_failures', 'final_independent_replays', 'final_feasibility_checks', 'total_full_solution_replays', 'total_feasibility_checks', 'accepted_move_count', 'accepted_structure_change_count', 'accepted_segment_lengths_json', 'accepted_all_declared_transfer_verified', 'accepted_all_completed_transfer_verified', 'accepted_all_source_cv_to_ev', 'accepted_all_counterfactual_source_stays_cv', 'accepted_all_beat_source_only_counterfactual', 'accepted_all_independent_replays_close', 'candidate_fail_closed_count', 'enumeration_fail_closed_count', 'counterfactual_fail_closed_count', 'nonfinite_prescore_rejections', 'terminal_activity_record_count', 'counterfactual_activity_record_count', 'round_caps_closed', 'actual_round_caps_closed', 'activity_ledgers_reconciled', 'activity_ledger_audit_json', 'final_validation_failed_closed', 'runner_proof_audit_passed', 'runner_proof_audit_json', 'runner_outer_full_solution_replays', 'runner_outer_feasibility_checks', 'runner_proof_full_solution_replays', 'runner_proof_feasibility_checks', 'runner_total_validation_replays', 'runner_total_validation_checks', 'complete_route_search_evaluations', 'route_search_guard_attempts', 'route_search_guard_installed', 'source_full_content_sha256', 'final_full_content_sha256', 'elapsed_seconds', 'objective_match', 'activity_json']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/fresh_d2_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/fresh_d2_gate/raw_runs.csv; keys=['instance_id', 'budget', 'arm', 'reported_algorithm', 'algorithm_reference_replays_reported']; seed=['seed']; values=['reported_cost', 'recomputed_cost']; seed_counts={}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/fuel_route_retirement_ev_repack_behavior_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/fuel_route_retirement_ev_repack_behavior_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['scenario', 'bundle', 'source_cost', 'final_cost', 'objective_delta', 'improvement_percent', 'claimed_final_cost', 'claim_replay_error', 'source_feasible', 'final_feasible', 'customer_coverage_closed', 'source_cv_routes', 'final_cv_routes', 'source_route_count', 'final_route_count', 'changed', 'accepted_count', 'repair_attempts', 'one_level_ejection_attempts', 'unique_repack_candidates', 'candidate_completion_calls', 'counterfactual_completion_calls', 'total_completion_calls', 'candidate_full_replays', 'total_full_replays', 'complete_route_search_evaluations', 'source_full_content_sha256', 'final_full_content_sha256', 'source_semantic_sha256', 'final_semantic_sha256', 'source_route_skeleton_sha256', 'final_route_skeleton_sha256', 'exact_noop', 'activity_ledgers_closed', 'accepted_nonvacuous', 'accepted_all_source_retired', 'completed_skeletons_all_fixed', 'elapsed_seconds', 'activity_json']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/initial_pool_gate_d1`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/initial_pool_gate_d1/raw_runs.csv; keys=['instance_id', 'family']; seed=['seed']; values=['objective', 'route_signature']; seed_counts={}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_priced_pair_resplit_behavior_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_priced_pair_resplit_behavior_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['fixture', 'label', 'arm', 'source_cost', 'counterfactual_cost', 'output_cost', 'changed', 'feasible', 'exact_candidate_capacity', 'exact_candidates_completed', 'vehicle_patterns', 'joint_feasibility_checks', 'joint_complete_replays', 'independent_replays', 'accepted_moves', 'candidate_set_sha256', 'accepted_candidate_sha256', 'result_sha256', 'complete_route_search_evaluations']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_regret_training_d1`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_regret_training_d1/raw_runs.csv; keys=['instance_id', 'family']; seed=['seed']; values=['objective', 'route_signature']; seed_counts={}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_segment_generation_behavior_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_segment_generation_behavior_gate/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'binding', 'mode', 'source_cost', 'candidate_present', 'candidate_cost', 'terminal_cost', 'feasible', 'route_membership_changed', 'selected_segment_length', 'selected_distance_delta', 'selected_local_model_delta', 'distance_worse_model_better_candidates', 'complete_candidate_evaluations', 'activity_json']

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/segment_generation_fresh_warning_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/segment_generation_fresh_warning_gate/raw_runs.csv; keys=['arm', 'algorithm', 'budget']; seed=['seed']; values=['objective_match']; seed_counts={}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/segmented_pathology_gate`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/segmented_pathology_gate/raw_runs.csv; keys=['eval_budget', 'dominant_destroy_share']; seed=['seed']; values=['final_cost']; seed_counts={2: 1, 3: 1}

- `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/softmax_training_confirmation`：source=baselines/algorithm_prototypes/unified_mechanism_alns_20260719/softmax_training_confirmation/raw_runs.csv; keys=['instance_id', 'policy_id', 'eval_budget', 'first_temperature', 'final_temperature', 'mean_temperature']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/direct_gate_v1`：source=baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/direct_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['absolute_improvement', 'any_nonadjacent_parent_pair_headroom', 'baseline_objective', 'best_from_nonadjacent_parent_pair', 'best_pair_json', 'best_parent_objective', 'best_source', 'customer_count', 'decoder_cache_json', 'error', 'exact_candidate_evaluations', 'final_objective', 'instance_id', 'local_improvement_signals', 'no_loss', 'old_pool_columns', 'old_pool_mip_gap', 'old_pool_mip_seconds', 'old_pool_mip_status', 'old_pool_objective', 'pair_attempts', 'parent_objectives_json', 'peak_rss_bytes', 'relative_improvement_pct', 'status', 'strict_improvement', 'trace_path', 'wall_seconds', 'witness_path']

- `baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v1`：source=baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'route_pair_indices', 'before_objective', 'after_objective', 'fallback_columns', 'generated_segments', 'generated_options_before_dedup', 'columns_after_dedup', 'selected_routes', 'mip_status', 'mip_status_class', 'mip_dual_bound', 'mip_gap', 'mip_node_count', 'mip_seconds', 'mip_integral', 'mip_exact_cover', 'mip_fleet_feasible', 'mip_charger_feasible', 'exact_violation_count', 'direct_violation_count', 'wall_seconds']

- `baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v2`：source=baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/g0_gate_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'route_pair_indices', 'before_objective', 'after_objective', 'fallback_columns', 'fallback_objective', 'generated_segments', 'generated_options_before_dedup', 'columns_after_dedup', 'selected_routes', 'mip_status', 'mip_status_class', 'mip_dual_bound', 'mip_gap', 'mip_node_count', 'mip_seconds', 'mip_integral', 'mip_exact_cover', 'mip_fleet_feasible', 'mip_charger_feasible', 'exact_violation_count', 'direct_violation_count', 'wall_seconds']

- `baselines/china_e3_e7/.e3-arm-semantics-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.artifact_watch.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.artifact_watch_resume.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry1.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry2.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.formal_dynamic_dispatch_20260802.retry3.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor-v2`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.xb-formal-fleet-levels-20260802.monitor-v3`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.xd-attempt4-archive-recovery-20260803.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/.xd-attempt4-archive-recovery-v2-20260803.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/blocker_fix_20260802`：source=baselines/china_e3_e7/blocker_fix_20260802/raw_runs.csv; keys=['instance_id', 'variant', 'population_count', 'off_mismatch_fields']; seed=['seed']; values=['off_objective_bitwise_equal', 'current_objective', 'saved_objective']; seed_counts={2: 2, 8: 2, 10: 1}

- `baselines/china_e3_e7/candidate_pool_probe_20260803`：source=baselines/china_e3_e7/candidate_pool_probe_20260803/raw_pool.csv; keys=['iterations', 'view']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/carbon_timing_rescore_20260802`：source=baselines/china_e3_e7/carbon_timing_rescore_20260802/raw_runs.csv; keys=['population', 'instance_id', 'variant', 'frozen_invariants_match', 'metric_invariants_match']; seed=['seed']; values=['total_cost_delta_cny']; seed_counts={5: 162, 10: 9}

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid`：source=baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid/raw_runs.csv; keys=['population', 'instance_id', 'variant', 'frozen_invariants_match', 'metric_invariants_match']; seed=['seed']; values=['total_cost_delta_cny']; seed_counts={2: 2, 3: 2, 4: 6, 5: 154, 10: 9}

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid/.xd-carbon-timing-rescore-20260802-attached.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid/.xd-carbon-timing-rescore-20260802.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt2_invalid`：source=baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt2_invalid/raw_runs.csv; keys=['population', 'instance_id', 'variant', 'frozen_invariants_match', 'metric_invariants_match']; seed=['seed']; values=['total_cost_delta_cny']; seed_counts={10: 9}

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt2_invalid/.xd-carbon-timing-rescore-20260802-attempt2.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3b.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt3_interrupted/.xd-carbon-timing-rescore-20260802-attempt3c.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/current_source_compatibility_20260801/saved_solution_replay_20260801`：source=baselines/china_e3_e7/current_source_compatibility_20260801/saved_solution_replay_20260801/raw_runs.csv; keys=['instance_id', 'arm_or_mode_or_coalition', 'mismatch_metrics', 'locked_battery_kwh', 'current_battery_kwh', 'old_curve_action_count', 'old_curve_max_duration_abs_error_seconds', 'current_curve_max_duration_abs_error_seconds']; seed=['seed']; values=['expected_objective', 'current_objective']; seed_counts={3: 2, 4: 2, 5: 401, 10: 99}

- `baselines/china_e3_e7/e3_arm_semantics_gate_20260723`：source=baselines/china_e3_e7/e3_arm_semantics_gate_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'control_load_dimensions', 'treatment_load_dimensions', 'control_full_model_violation_count', 'control_cross_site_service_count', 'treatment_reciprocal_operator', 'treatment_active_node_operators', 'treatment_lock_removed', 'status', 'search_evaluations']

- `baselines/china_e3_e7/e3_arm_semantics_gate_v2_20260723`：source=baselines/china_e3_e7/e3_arm_semantics_gate_v2_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'control_load_dimensions', 'treatment_load_dimensions', 'control_full_model_violation_count', 'control_cross_site_service_count', 'treatment_reciprocal_operator', 'treatment_active_node_operators', 'treatment_lock_removed', 'status', 'search_evaluations']

- `baselines/china_e3_e7/e3_arm_semantics_gate_v3_20260723`：source=baselines/china_e3_e7/e3_arm_semantics_gate_v3_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'control_load_dimensions', 'treatment_load_dimensions', 'control_full_model_violation_count', 'control_cross_site_service_count', 'treatment_reciprocal_operator', 'treatment_active_node_operators', 'treatment_lock_removed', 'status', 'search_evaluations']

- `baselines/china_e3_e7/e3_arm_semantics_gate_v5_20260724`：source=baselines/china_e3_e7/e3_arm_semantics_gate_v5_20260724/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'control_load_dimensions', 'treatment_load_dimensions', 'control_full_model_violation_count', 'control_cross_site_service_count', 'treatment_reciprocal_operator', 'treatment_active_node_operators', 'treatment_lock_removed', 'status', 'search_evaluations']

- `baselines/china_e3_e7/e3_budget_pilot_20260723`：source=baselines/china_e3_e7/e3_budget_pilot_20260723/raw_runs.csv; keys=['instance_id', 'customer_count', 'arm_id']; seed=['seed']; values=['objective_values_recorded']; seed_counts={}

- `baselines/china_e3_e7/e3_budget_pilot_v4_20260724`：source=baselines/china_e3_e7/e3_budget_pilot_v4_20260724/raw_runs.csv; keys=['instance_id', 'customer_count', 'arm_id']; seed=['seed']; values=['objective_values_recorded']; seed_counts={}

- `baselines/china_e3_e7/e3_environment_authority_20260723`：source=baselines/china_e3_e7/e3_environment_authority_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['package', 'expected_version', 'observed_version', 'module_path', 'inside_formal_prefix', 'distribution_tree_sha256', 'status']

- `baselines/china_e3_e7/e3_mismatch_20260729`：source=baselines/china_e3_e7/e3_mismatch_20260729/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['stage', 'record_type', 'instance_id', 'mismatch_intensity_nominal_pct', 'eligible_multi_depot_instances', 'excluded_single_depot_instances', 'route_counts_by_depot', 'total_fleet_caps_by_depot', 'violation_count', 'search_evaluations', 'status', 'note']

- `baselines/china_e3_e7/e3_mismatch_20260729/gate2_d3`：source=baselines/china_e3_e7/e3_mismatch_20260729/gate2_d3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'depot_count', 'search_space_hard_lock', 'complete_candidate_guard', 'route_pool_first_filter_locked_records', 'route_pool_open_free_records', 'route_pool_mip_second_filter', 'final_certificate_guard', 'lock_cross_site_service_count', 'free_constructed_cross_site_service_count', 'search_evaluations', 'status']

- `baselines/china_e3_e7/e3_mismatch_20260731`：source=baselines/china_e3_e7/e3_mismatch_20260731/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e3_parameter_coherence_gate_20260723`：source=baselines/china_e3_e7/e3_parameter_coherence_gate_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'parameter_class', 'observed', 'required', 'status']

- `baselines/china_e3_e7/e3_parameter_coherence_gate_v1_halt_20260723`：source=baselines/china_e3_e7/e3_parameter_coherence_gate_v1_halt_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'parameter_class', 'observed', 'required', 'status']

- `baselines/china_e3_e7/e3_parameter_coherence_gate_v3_20260724`：source=baselines/china_e3_e7/e3_parameter_coherence_gate_v3_20260724/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'parameter_class', 'observed', 'required', 'status']

- `baselines/china_e3_e7/e3_release_regression_v2_20260724`：source=baselines/china_e3_e7/e3_release_regression_v2_20260724/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['test_id', 'classification', 'registered', 'message']

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-01-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-01-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-02-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-02-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-03-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-03-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-01-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-01-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-02-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-02-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-03-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-03-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-01-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-01-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-02-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-02-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-03-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-03-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-01-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-01-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-02-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-02-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-03-V2-LOCATIONS`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-03-V2-LOCATIONS/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/panel_summary`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/panel_summary/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot/cn-prd-150c-01-V2-LOCATIONS__Uniform_Balanced__seed-01__raw_runs.csv; keys=['instance_id', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot_capacity_rank_aligned_v1_20260801`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot_capacity_rank_aligned_v1_20260801/raw_runs.csv; keys=['instance_id', 'candidate_family', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={3: 2}

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot_existing_fleet_v1_20260801`：source=baselines/china_e3_e7/e3_scattered_ownership_20260801/pilot_existing_fleet_v1_20260801/raw_runs.csv; keys=['instance_id', 'source_family', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e3_structural_20260731`：source=baselines/china_e3_e7/e3_structural_20260731/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={5: 2, 8: 1}

- `baselines/china_e3_e7/e3_structural_20260731/probe`：source=baselines/china_e3_e7/e3_structural_20260731/probe/convergence_curve.csv; keys=['instance_id', 'arm', 'view']; seed=['seed']; values=['complete_objective_cny']; seed_counts={}

- `baselines/china_e3_e7/e3_zone_joint_20260731`：source=baselines/china_e3_e7/e3_zone_joint_20260731/raw_runs.csv; keys=['instance_id', 'sample_role', 'arm', 'hard_home_depot_lock', 'complete_candidate_budget_cap']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 4}

- `baselines/china_e3_e7/e3e6_binding_preflight_01_20260727`：source=baselines/china_e3_e7/e3e6_binding_preflight_01_20260727/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['audit_id', 'area', 'status', 'formal_search_started', 'search_evaluations', 'hard_evidence', 'open_binding']

- `baselines/china_e3_e7/e3e6_formal_20260729/.e3e6-formal-preregistration-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e3e6_formal_20260729/.e3e6-formal-preregistration-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e3e6_formal_20260729/.e3e6-formal-preregistration-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e3e6_formal_20260729/.e3e6-formal-preregistration.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e3e6_formal_20260729/gate2_d3`：source=baselines/china_e3_e7/e3e6_formal_20260729/gate2_d3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'depot_count', 'search_space_hard_lock', 'complete_candidate_guard', 'route_pool_first_filter_locked_records', 'route_pool_open_free_records', 'route_pool_mip_second_filter', 'final_certificate_guard', 'lock_cross_site_service_count', 'free_constructed_cross_site_service_count', 'search_evaluations', 'status']

- `baselines/china_e3_e7/e3e6_gates_01_20260729`：source=baselines/china_e3_e7/e3e6_gates_01_20260729/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['gate', 'status', 'search_evaluations', 'reason']

- `baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a`：source=baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'depot_count', 'customer_count', 'route_count', 'violation_count', 'cross_site_service_count', 'witness_sha256', 'status', 'search_evaluations']

- `baselines/china_e3_e7/e3e6_gates_01_20260729/gate2_d3`：source=baselines/china_e3_e7/e3e6_gates_01_20260729/gate2_d3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'depot_count', 'control_load_dimensions', 'treatment_load_dimensions', 'search_space_hard_lock_pass', 'control_full_model_violation_count', 'control_cross_site_service_count', 'complete_candidate_guard_source_pass', 'route_pool_first_filter_control_record_count', 'route_pool_open_treatment_record_count', 'route_pool_mip_second_filter_status', 'final_certificate_guard_source_pass', 'treatment_lock_removed', 'treatment_exchange11_active', 'treatment_cross_site_constructible', 'adversarial_cross_site_service_count', 'topology_note', 'status', 'search_evaluations']

- `baselines/china_e3_e7/e3e6_gates_01_20260729/gate3_d4`：source=baselines/china_e3_e7/e3e6_gates_01_20260729/gate3_d4/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['gate', 'status', 'reason', 'pilot_started', 'arm_costs_read_or_reported', 'search_evaluations']

- `baselines/china_e3_e7/e4_carbon_timing_20260729`：source=baselines/china_e3_e7/e4_carbon_timing_20260729/raw_runs.csv; keys=['instance_id', 'region', 'movable_energy_share_pct', 'immovable_energy_share_pct', 'fixed_invariants_match']; seed=['seed']; values=['asap_full_model_cost_cny', 'carbon_full_model_cost_cny']; seed_counts={2: 12, 3: 10, 4: 8, 5: 56}

- `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801`：source=baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={10: 3}

- `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-01-V2-LOCATIONS`：source=baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-01-V2-LOCATIONS/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={10: 1}

- `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-02-V2-LOCATIONS`：source=baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-02-V2-LOCATIONS/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={10: 1}

- `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-03-V2-LOCATIONS`：source=baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-03-V2-LOCATIONS/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={10: 1}

- `baselines/china_e3_e7/e4_joint_routing_20260801/probe`：source=baselines/china_e3_e7/e4_joint_routing_20260801/probe/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={3: 1}

- `baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt1_no_ev_bug`：source=baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt1_no_ev_bug/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={3: 1}

- `baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt2_pre_cost_tiebreak_fix`：source=baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt2_pre_cost_tiebreak_fix/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={3: 1}

- `baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt3_legacy_pure_carbon_repair`：source=baselines/china_e3_e7/e4_joint_routing_20260801/probe_attempt3_legacy_pure_carbon_repair/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={3: 1}

- `baselines/china_e3_e7/e4_joint_routing_20260801/probe_v2_hook_restore_20260801`：source=baselines/china_e3_e7/e4_joint_routing_20260801/probe_v2_hook_restore_20260801/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_mode', 'objective_value', 'objective_unit', 'cost_plus_carbon_cny', 'typed_path_hash']; seed_counts={3: 1}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/.e5-b2-low-cost-20260801.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_low_cost_diagnostic_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_low_cost_diagnostic_20260801/raw_runs.csv; keys=['instance_id', 'curve_id', 'battery_capacity_kwh', 'initial_ev_battery_kwh']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_opportunity_audit_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_opportunity_audit_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'region', 'customer_count', 'replicate', 'route_index', 'source_vehicle_id', 'route_energy_kwh', 'route_soc_pct', 'route_exceeds_85_pct', 'selected_as_ev_by_default_completion', 'just_enough_public_stops', 'just_enough_action_count', 'just_enough_route', 'max_coverage_public_stops', 'max_coverage_action_count', 'max_coverage_route', 'max_coverage_reduces_public_stop']

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_wang95_range_opportunity_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_wang95_range_opportunity_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'region', 'customer_count', 'replicate', 'route_index', 'source_vehicle_id', 'arc_count', 'ev_road_distance_m', 'ev_road_distance_km', 'reference_range_km', 'exceeds_reference_range', 'excess_km', 'formal_six_instance']

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot02`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot02/raw_runs.csv; keys=['instance_id', 'curve_id']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot03`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot03/raw_runs.csv; keys=['instance_id', 'curve_id']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot04`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot04/raw_runs.csv; keys=['instance_id', 'curve_id']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot05`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot05/raw_runs.csv; keys=['instance_id', 'curve_id']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot06_seed1_symmetric`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot06_seed1_symmetric/raw_runs.csv; keys=['instance_id', 'curve_id', 'max_public_charge_end_soc_pct']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot07_seeds1to3_symmetric`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot07_seeds1to3_symmetric/raw_runs.csv; keys=['instance_id', 'curve_id', 'max_public_charge_end_soc_pct']; seed=['seed']; values=['total_cost_cny']; seed_counts={2: 4, 3: 4}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot08_fixed_schedule_execution_replay_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot08_fixed_schedule_execution_replay_20260801/raw_runs.csv; keys=['instance_id', 'only_duration_and_curve_changed']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot09_montoya_l1_l2_pl_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot09_montoya_l1_l2_pl_20260801/raw_runs.csv; keys=['instance_id', 'curve_id', 'max_public_charge_end_soc_pct', 'fixed_pl_only_duration_and_curve_changed']; seed=['seed']; values=['total_cost_cny']; seed_counts={2: 7, 3: 6}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot10_montoya_l1_l2_pl_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot10_montoya_l1_l2_pl_20260801/raw_runs.csv; keys=['instance_id', 'curve_id', 'max_public_charge_end_soc_pct', 'fixed_pl_only_duration_and_curve_changed']; seed=['seed']; values=['total_cost_cny']; seed_counts={2: 7, 3: 6}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot11_montoya_time_metric_reaccounting_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot11_montoya_time_metric_reaccounting_20260801/raw_runs.csv; keys=['instance_id', 'curve_id', 'own_minus_pl_percent']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot12_montoya_fs_l1_l2_pl_20260801`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/pilot12_montoya_fs_l1_l2_pl_20260801/raw_runs.csv; keys=['instance_id', 'curve_id', 'departure_energy_kwh_configured', 'max_public_charge_end_soc_pct', 'fixed_pl_only_duration_and_curve_changed']; seed=['seed']; values=['total_cost_cny']; seed_counts={2: 13, 3: 13}

- `baselines/china_e3_e7/e5_enroute_nonlinear_20260801/smoke`：source=baselines/china_e3_e7/e5_enroute_nonlinear_20260801/smoke/raw_runs.csv; keys=['instance_id', 'curve_id']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_literature_curve_20260731`：source=baselines/china_e3_e7/e5_literature_curve_20260731/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_20260729`：source=baselines/china_e3_e7/e5_nonlinear_20260729/raw_runs.csv; keys=['budget', 'instance_id', 'arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-160`：source=baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-160/raw_blind.csv; keys=['instance_id', 'arm', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-240`：source=baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-240/raw_blind.csv; keys=['instance_id', 'arm', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-32`：source=baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-32/raw_blind.csv; keys=['instance_id', 'arm', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-56`：source=baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-56/raw_blind.csv; keys=['instance_id', 'arm', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-80`：source=baselines/china_e3_e7/e5_nonlinear_20260729/pilot/budget-80/raw_blind.csv; keys=['instance_id', 'arm', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_final_20260730`：source=baselines/china_e3_e7/e5_nonlinear_final_20260730/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_v2_20260730`：source=baselines/china_e3_e7/e5_nonlinear_v2_20260730/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_v3_20260730`：source=baselines/china_e3_e7/e5_nonlinear_v3_20260730/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['objective']; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_v4_20260730`：source=baselines/china_e3_e7/e5_nonlinear_v4_20260730/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e5_nonlinear_v4_20260730/formal/manifests`：source=baselines/china_e3_e7/e5_nonlinear_v4_20260730/formal/manifests/cn-prd-100c-02-V2-LOCATIONS__manifest.csv; keys=['instance_id', 'arm', 'budget']; seed=['seed']; values=['objective_status']; seed_counts={10: 2}

- `baselines/china_e3_e7/e5_nonlinear_v4_20260730/probe`：source=baselines/china_e3_e7/e5_nonlinear_v4_20260730/probe/convergence_curve.csv; keys=['instance_id', 'arm', 'view']; seed=['seed']; values=['complete_objective_cny']; seed_counts={}

- `baselines/china_e3_e7/e5_option_b_assessment_20260730`：source=baselines/china_e3_e7/e5_option_b_assessment_20260730/raw_runs.csv; keys=['instance_id', 'arm', 'budget']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_allocation_20260731`：source=baselines/china_e3_e7/e6_allocation_20260731/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/.formal_e6a_panel_20260801.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6_serving_revenue_ledger_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6_serving_revenue_ledger_20260801/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/panel_raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6s2_nucleolus_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6s2_nucleolus_20260801/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot02`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot02/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['method', 'coalition', 'member_count', 'cost_cny', 'revenue_cny', 'profit_cny', 'route_count', 'theta', 'feasible', 'cost_closure_abs_cny', 'profit_closure_abs_cny', 'profit_D_dongguan', 'profit_D_foshan', 'profit_D_guangzhou', 'profit_D_shenzhen']

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot03`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot03/raw_runs.csv; keys=['instance_id', 'owner_family', 'business_scenario', 'method', 'customer_count']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot04_rank_aligned_direct_screen_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot04_rank_aligned_direct_screen_20260801/raw_runs.csv; keys=['instance_id', 'business_scenario', 'theta']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot05_grand_coalition_recovery_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot05_grand_coalition_recovery_20260801/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot06_direct_15_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot06_direct_15_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['record_type', 'coalition', 'coalition_member_count', 'objective_cny', 'selected_source', 'solution_sha256', 'route_pool_records', 'status', 'violation_type', 'violation_location', 'violation_detail']

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot07_physical_transfer_ledger_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot07_physical_transfer_ledger_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['original_owner', 'actual_service_depot', 'vehicle_type', 'customer_count', 'quantity_kg', 'payload_capacity_kg', 'minimum_trip_count', 'outbound_distance_km_per_trip', 'return_distance_km_per_trip', 'outbound_minutes_per_trip', 'return_minutes_per_trip', 'one_way_vehicle_km', 'closed_vehicle_km', 'outbound_tonne_km', 'non_energy_cost_cny_per_km', 'one_way_non_energy_cost_cny', 'closed_non_energy_cost_cny']

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot08_direct_natural_profit_ledger_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot08_direct_natural_profit_ledger_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['contractor', 'original_customer_revenue_cny', 'standalone_cost_cny', 'standalone_profit_cny', 'grand_actual_service_revenue_cny', 'grand_actual_service_cost_cny', 'grand_natural_profit_cny', 'grand_natural_minus_standalone_profit_cny', 'grand_natural_profit_below_standalone']

- `baselines/china_e3_e7/e6_contractor_participation_20260801/pilot09_direct_15_independent_initial_20260801`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/pilot09_direct_15_independent_initial_20260801/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e6_contractor_participation_20260801/smoke`：source=baselines/china_e3_e7/e6_contractor_participation_20260801/smoke/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['method', 'coalition', 'member_count', 'cost_cny', 'revenue_cny', 'profit_cny', 'route_count', 'theta', 'feasible', 'cost_closure_abs_cny', 'profit_closure_abs_cny', 'profit_D_dongguan', 'profit_D_foshan', 'profit_D_guangzhou', 'profit_D_shenzhen']

- `baselines/china_e3_e7/e6_fairness_20260731`：source=baselines/china_e3_e7/e6_fairness_20260731/raw_runs.csv; keys=['instance_id', 'sample_role', 'state', 'source_arm', 'theta']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 6}

- `baselines/china_e3_e7/e6_fairness_v2_20260731`：source=baselines/china_e3_e7/e6_fairness_v2_20260731/raw_runs.csv; keys=['instance_id', 'sample_role', 'state', 'theta']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 6}

- `baselines/china_e3_e7/e6_fairness_v2_20260731/attempt_history/preflight_01`：source=baselines/china_e3_e7/e6_fairness_v2_20260731/attempt_history/preflight_01/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['objective_float_bits_identical']; seed_counts={}

- `baselines/china_e3_e7/e6_fairness_v2_20260731/monitor_runtime_corrected`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e6_fairness_v3_20260731`：source=baselines/china_e3_e7/e6_fairness_v3_20260731/raw_runs.csv; keys=['instance_id', 'sample_role', 'state', 'theta']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 6}

- `baselines/china_e3_e7/e7_dynamic_20260731`：source=baselines/china_e3_e7/e7_dynamic_20260731/raw_runs.csv; keys=['instance_id', 'arm', 'stream_seed']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_dynamic_20260731/inputs`：source=baselines/china_e3_e7/e7_dynamic_20260731/inputs/event_manifest.csv; keys=['instance_id']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_dynamic_v2_20260731`：source=baselines/china_e3_e7/e7_dynamic_v2_20260731/raw_runs.csv; keys=['instance_id', 'arm', 'stream_seed']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_dynamic_v2_20260731/inputs`：source=baselines/china_e3_e7/e7_dynamic_v2_20260731/inputs/event_manifest.csv; keys=['instance_id']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_dynamic_v2_20260731/monitor_runs/startup`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801-retry1.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801-retry2.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e7_o1_replanning_20260801/.e7-o1-count-20260801.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/e7_o1_replanning_20260801/failed_attempt1_count_20260801`：source=baselines/china_e3_e7/e7_o1_replanning_20260801/failed_attempt1_count_20260801/raw_runs.csv; keys=['demand_threshold_kg', 'instance_id', 'policy', 'threshold_trigger_count']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_o1_replanning_20260801/failure_diagnosis_20260801`：source=baselines/china_e3_e7/e7_o1_replanning_20260801/failure_diagnosis_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['accepted_addition_count', 'addition_count', 'appearance_second', 'asset_available_at_trigger', 'asset_future_release', 'asset_never_started', 'asset_total', 'batch_index', 'count20_trigger_cause', 'count20_trigger_second', 'customer_id', 'depot_id', 'due_second', 'event_ids', 'failure_reason', 'failure_stage', 'fixed_trigger_cause', 'fixed_trigger_second', 'information_wait_seconds', 'latest_departure_second', 'operationally_identical', 'policy', 'preferred_departure_second', 'reachable_at_trigger', 'ready_second', 'record_type', 'replay_matches_original', 'seconds_trigger_after_latest', 'seconds_trigger_after_shenzhen_cv_latest', 'service_second', 'shenzhen_cv_latest_departure_second', 'stage_evaluation_budget', 'status', 'trigger_second', 'vehicle_type']

- `baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_20260801`：source=baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_20260801/raw_runs.csv; keys=['demand_threshold_kg', 'instance_id', 'policy']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_count_20260801`：source=baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_count_20260801/raw_runs.csv; keys=['demand_threshold_kg', 'instance_id', 'policy', 'threshold_trigger_count']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_v2_20260801`：source=baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_v2_20260801/raw_runs.csv; keys=['demand_threshold_kg', 'instance_id', 'policy']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_o2_dispatch_20260801/zero_search_15_streams_20260801`：source=baselines/china_e3_e7/e7_o2_dispatch_20260801/zero_search_15_streams_20260801/raw_runs.csv; keys=['instance_id']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed10_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed10_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed1_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed1_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'violation_count', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed2_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed2_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'violation_count', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'violation_count', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v2_clockfix_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed3_eval8_v2_clockfix_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed4_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed4_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed5_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed5_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed6_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed6_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed7_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed7_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed8_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed8_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed9_eval8_v1_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seed9_eval8_v1_20260801/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['actual_cv_count', 'actual_ev_count', 'actual_vehicle_count', 'arm', 'charging_action_count', 'completed_customer_count', 'completion_rate_pct', 'delivery_cost_cny', 'evaluation_count', 'legal', 'rejected_customer_count', 'rejected_customer_ids', 'rejected_revenue_cny', 'route_count', 'status', 'total_cost_with_lost_revenue_cny', 'trigger_count', 'validated_stage_count', 'validation_method', 'violation_count', 'violation_types', 'wall_seconds']

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to10_eval8_aggregate_v1_all_pairwise_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to10_eval8_aggregate_v1_all_pairwise_20260801/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=['total_cost_with_lost_revenue_cny']; seed_counts={10: 4}

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_20260801/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=['total_cost_with_lost_revenue_cny']; seed_counts={3: 4}

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v2_clockfix_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v2_clockfix_20260801/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=['total_cost_with_lost_revenue_cny']; seed_counts={3: 4}

- `baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v3_all_pairwise_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/pilot_50c_seeds1to3_eval8_aggregate_v3_all_pairwise_20260801/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=['total_cost_with_lost_revenue_cny']; seed_counts={3: 4}

- `baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_50c_seeds1to10_eval8_diagnostic_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_50c_seeds1to10_eval8_diagnostic_20260801/raw_runs.csv; keys=['policy']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_three_triggers_50c_seeds1to10_eval8_comparison_20260801`：source=baselines/china_e3_e7/e7_trigger_policies_20260801/qiu_accept_all_three_triggers_50c_seeds1to10_eval8_comparison_20260801/raw_runs.csv; keys=['policy']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/fleet_authority_v3_20260802`：source=baselines/china_e3_e7/fleet_authority_v3_20260802/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['record_type', 'record_id', 'instance_id', 'target_ev_share', 'target_ev_percent', 'depot_count', 'total_fleet_cap', 'target_ev_available', 'target_cv_available', 'physical_cv_used', 'physical_ev_used', 'violation_count', 'violations_json', 'status', 'route_search_executed', 'search_evaluations']

- `baselines/china_e3_e7/formal_ablation_200c_20260803`：source=baselines/china_e3_e7/formal_ablation_200c_20260803/raw_runs.csv; keys=['group', 'instance_id', 'arm_id', 'algorithm', 'max_hgs_iterations', 'max_no_improvement_iterations']; seed=['seed']; values=['objective_cny', 'solution_structure_sha256']; seed_counts={10: 3}

- `baselines/china_e3_e7/formal_ablation_200c_20260803/.experiment-monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_algorithm_20260802`：source=baselines/china_e3_e7/formal_algorithm_20260802/raw_runs.csv; keys=['group', 'instance_id', 'arm_id', 'algorithm', 'max_hgs_iterations', 'max_no_improvement_iterations']; seed=['seed']; values=['objective_cny']; seed_counts={10: 8}

- `baselines/china_e3_e7/formal_algorithm_20260802/.experiment-monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_algorithm_20260802/.experiment-monitor-attempt2`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_dynamic_dispatch_20260802`：source=baselines/china_e3_e7/formal_dynamic_dispatch_20260802/raw_runs.csv; keys=['arm', 'policy', 'policy_label', 'response_rate_pct']; seed=['stream_seed']; values=['total_cost_cny']; seed_counts={5: 6}

- `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed01`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed02`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed03`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed04`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed05`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/failed_start3_thread_preoptimization_only/per_order__seed06`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formal_fleet_levels_20260802`：source=baselines/china_e3_e7/formal_fleet_levels_20260802/raw_runs.csv; keys=['instance_id', 'fleet_level_percent']; seed=['seed']; values=['aware_full_model_cost_cny', 'blind_rescored_full_model_cost_cny']; seed_counts={10: 3}

- `baselines/china_e3_e7/formal_fleet_levels_20260802_presearch_halt_sem_nsems_max`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/formula_change_20260802`：source=baselines/china_e3_e7/formula_change_20260802/raw_runs.csv; keys=['instance_id', 'variant', 'population_count', 'target_ev_share']; seed=['seed']; values=['old_fixed_cost', 'predicted_new_fixed_cost', 'actual_new_fixed_cost']; seed_counts={2: 7, 8: 2, 10: 1}

- `baselines/china_e3_e7/foundation_20260723`：source=baselines/china_e3_e7/foundation_20260723/raw_runs.csv; keys=['family', 'instance_id', 'region', 'arm', 'service_level', 'fairness_ratio', 'carbon_aware_charging_share', 'algorithm_id']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/china_e3_e7/foundation_20260723/aggregates`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/foundation_20260723/figures`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/foundation_20260723/paper_tables`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/mechanism_foundation_20260730`：source=baselines/china_e3_e7/mechanism_foundation_20260730/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['family', 'instance_id', 'cell', 'check', 'status', 'search_evaluations', 'artifact_sha256']

- `baselines/china_e3_e7/multitrip_interface_completion_20260802`：source=baselines/china_e3_e7/multitrip_interface_completion_20260802/raw_runs.csv; keys=['instance_id', 'variant', 'single_trip_mismatch_fields']; seed=['seed']; values=['single_trip_objective_bitwise_equal']; seed_counts={2: 5, 6: 1, 7: 2}

- `baselines/china_e3_e7/multitrip_saved_solution_repack_20260801`：source=baselines/china_e3_e7/multitrip_saved_solution_repack_20260801/raw_runs.csv; keys=['instance_id', 'variant']; seed=['seed']; values=[]; seed_counts={}

- `baselines/china_e3_e7/pre_e3_full_chain_audit_20260723`：source=baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['record_type', 'record_id', 'status', 'checks', 'passed', 'failed', 'skipped', 'search_evaluations', 'evidence']

- `baselines/china_e3_e7/regression_fix_20260802`：source=baselines/china_e3_e7/regression_fix_20260802/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['record_type', 'record_id', 'status', 'passed', 'failed', 'skipped', 'certification_units', 'violation_count', 'route_search_executed', 'search_evaluations', 'command', 'details']

- `baselines/china_e3_e7/scout_depot_ownership_20260803`：source=baselines/china_e3_e7/scout_depot_ownership_20260803/raw_runs.csv; keys=['baseline_type', 'instance_id', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/scout_depot_ownership_20260803/.scout-d-depot-ownership-20260803-recovery.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/scout_depot_ownership_20260803/.scout-d-depot-ownership-20260803.monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/scout_depot_ownership_20260803/baseline_nearest`：source=baselines/china_e3_e7/scout_depot_ownership_20260803/baseline_nearest/raw_runs.csv; keys=['baseline_type', 'instance_id', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={10: 2}

- `baselines/china_e3_e7/scout_depot_ownership_20260803/baseline_random`：source=baselines/china_e3_e7/scout_depot_ownership_20260803/baseline_random/raw_runs.csv; keys=['baseline_type', 'instance_id', 'arm']; seed=['seed']; values=['total_cost_cny']; seed_counts={}

- `baselines/china_e3_e7/scout_three_mechanisms_20260803`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/.experiment-monitor-attempt2`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_fleet`：source=baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_fleet/raw_runs.csv; keys=['instance_id', 'fleet_level_percent']; seed=['seed']; values=['aware_full_model_cost_cny', 'blind_rescored_full_model_cost_cny', 'aware_objective_float_hex', 'blind_objective_float_hex', 'aware_route_structure_sha256', 'blind_route_structure_sha256']; seed_counts={10: 3}

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_nonlinear`：source=baselines/china_e3_e7/scout_three_mechanisms_20260803/arm_nonlinear/raw_runs.csv; keys=['curve_id']; seed=['seed']; values=['objective', 'objective_float_hex', 'total_cost_cny', 'route_structure_sha256']; seed_counts={10: 2}

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt`：source=baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'status', 'answer', 'maximum_difference', 'effect_layers']

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/.experiment-monitor`：该包无逐单元原始记录CSV

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/arm_dynamic`：source=baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/arm_dynamic/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'status', 'error', 'traceback', 'retained_at']

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/arm_fleet`：source=baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/arm_fleet/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'status', 'error', 'traceback', 'retained_at']

- `baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/arm_nonlinear`：source=baselines/china_e3_e7/scout_three_mechanisms_20260803/attempt_01_technical_halt/arm_nonlinear/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'status', 'error', 'traceback', 'retained_at']

- `baselines/china_e3_e7/seed_determinism_probe2_20260803`：source=baselines/china_e3_e7/seed_determinism_probe2_20260803/raw_probe2.csv; keys=['iterations', 'view']; seed=['seed']; values=['objective_float_hex', 'total_cost_cny', 'route_structure_sha256']; seed_counts={2: 9}

- `baselines/china_e3_e7/seed_determinism_probe_20260803`：source=baselines/china_e3_e7/seed_determinism_probe_20260803/raw_probe.csv; keys=['iterations']; seed=['seed']; values=['objective_float_hex', 'total_cost_cny', 'route_structure_sha256']; seed_counts={2: 3}

- `baselines/china_instances/monitor_configs/.china-stage2-local-osrm-graphs-retry1.monitor`：该包无逐单元原始记录CSV

- `baselines/china_instances/monitor_configs/.china-stage2-local-osrm-graphs.monitor`：该包无逐单元原始记录CSV

- `baselines/china_instances/monitor_configs/.china81-stage2-road-pipeline.monitor`：该包无逐单元原始记录CSV

- `baselines/contract_audit/e1_e7_submission_contract_20260711`：source=baselines/contract_audit/e1_e7_submission_contract_20260711/e2_replay_rows.csv; keys=['algorithm', 'cross_site_cost_if_enabled', 'instance']; seed=['seed']; values=['replayed_free_cross_site_cost', 'reported_cost']; seed_counts={2: 21, 3: 10, 4: 6, 5: 4}

- `baselines/contract_audit/submission_contract_candidate_20260711`：source=baselines/contract_audit/submission_contract_candidate_20260711/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'ok']

- `baselines/contract_audit/wp0_e0_check_20260712`：source=baselines/contract_audit/wp0_e0_check_20260712/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'customer_count', 'active_bundle_path', 'registry_order_match', 'manifest_instance_match', 'bundle_hashes_match', 'shared_start_routes', 'shared_start_charging_actions', 'shared_start_cost_gbp', 'violation_count', 'shared_start_hash']

- `baselines/contract_audit/wp0_e2_replay_20260712`：source=baselines/contract_audit/wp0_e2_replay_20260712/raw_runs.csv; keys=['instance', 'algorithm']; seed=['seed']; values=['expected_cost', 'current_cost']; seed_counts={}

- `baselines/e1_model/e1_submission_20260711_committed/formal`：source=baselines/e1_model/e1_submission_20260711_committed/formal/raw_runs.csv; keys=['instance', 'variant', 'eval_budget', 'battery_kwh', 'ev_customer_share', 'ev_demand_share']; seed=['seed']; values=['total_cost']; seed_counts={5: 1}

- `baselines/e1_model/e1_submission_20260711_committed/preflight`：source=baselines/e1_model/e1_submission_20260711_committed/preflight/raw_runs.csv; keys=['battery_kwh', 'ev_customer_share', 'ev_demand_share', 'eval_budget', 'instance', 'variant']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e2_alns`：source=baselines/e2_alns/sa_raw_runs.csv; keys=['algorithm', 'category', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={5: 27}

- `baselines/e2_alns/280kwh_fleet_composition_gate_data`：source=baselines/e2_alns/280kwh_fleet_composition_gate_data/raw_runs.csv; keys=['B_battery_kwh', 'category', 'eval_budget', 'instance', 'variant']; seed=['seed']; values=['total_cost']; seed_counts={3: 51}

- `baselines/e2_alns/alns_independence_migration_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/balanced_selector_probe_20260706`：source=baselines/e2_alns/balanced_selector_probe_20260706/raw_runs.csv; keys=['category', 'instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 32}

- `baselines/e2_alns/battery_spectrum_transition_data`：source=baselines/e2_alns/battery_spectrum_transition_data/fixed_replay.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={5: 378}

- `baselines/e2_alns/bridge_fix_validation_data`：source=baselines/e2_alns/bridge_fix_validation_data/lns_b1_raw_runs.csv; keys=['algorithm', 'eval_budget']; seed=['seed']; values=['candidate_objective', 'best_cost']; seed_counts={}

- `baselines/e2_alns/carbon_aware_operator_probe_data`：source=baselines/e2_alns/carbon_aware_operator_probe_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'low_carbon_charging_share', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/carbon_aware_operator_probe_phase0_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/carbon_aware_operator_probe_smoke_data`：source=baselines/e2_alns/carbon_aware_operator_probe_smoke_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'low_carbon_charging_share', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/charging_infrastructure_operational_pilot_data`：source=baselines/e2_alns/charging_infrastructure_operational_pilot_data/raw_runs.csv; keys=['B_battery_kwh', 'category', 'depot_charging_energy_share', 'eval_budget', 'instance', 'public_charging_energy_share', 'variant']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e2_alns/convergence`：source=baselines/e2_alns/convergence/e2-multidepot-100c-01__LNS__seed1.csv; keys=['algorithm', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/convergence_throughput`：source=baselines/e2_alns/convergence_throughput/e2-multidepot-100c-01__LNS__seed1.csv; keys=['algorithm', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/cvrplib_optimal_benchmark_20260716`：source=baselines/e2_alns/cvrplib_optimal_benchmark_20260716/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'customers', 'capacity', 'advertised_min_vehicles_k', 'capacity_lower_bound', 'published_solution_routes', 'published_optimum', 'independent_reconstruction', 'resetp_distance_only_evaluation', 'all_customers_once', 'capacity_feasible', 'resetp_violation_count', 'max_route_load', 'instance_sha256', 'solution_sha256', 'passed']

- `baselines/e2_alns/decoder_fix_validation_data`：source=baselines/e2_alns/decoder_fix_validation_data/raw_runs.csv; keys=['algorithm', 'category', 'instance', 'size', 'battery_kwh', 'eval_budget', 'seed_source']; seed=['seed']; values=['candidate_objective', 'best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/e2_12h_preflight_20260711`：该包无逐单元原始记录CSV

- `baselines/e2_alns/e2_16000_preflight_20260712/formal`：source=baselines/e2_alns/e2_16000_preflight_20260712/formal/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_16000_preflight_20260712/smoke`：source=baselines/e2_alns/e2_16000_preflight_20260712/smoke/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_16000_preflight_plan_20260711`：source=baselines/e2_alns/e2_16000_preflight_plan_20260711/raw_runs.csv; keys=['instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['4000_cost']; seed_counts={}

- `baselines/e2_alns/e2_280_fleet_charging_audit_20260711`：source=baselines/e2_alns/e2_280_fleet_charging_audit_20260711/raw_audit_rows.csv; keys=['ev_customer_share', 'ev_demand_share', 'ev_physical_vehicle_share', 'instance', 'low_carbon_charging_share', 'size']; seed=['seed']; values=['same_route_structure']; seed_counts={2: 1, 3: 1, 5: 1}

- `baselines/e2_alns/e2_80k_robustness_20260711/formal`：source=baselines/e2_alns/e2_80k_robustness_20260711/formal/task_manifest.csv; keys=['category', 'instance', 'algorithm', 'eval_budget', 'scenario_type']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/e2_80k_robustness_20260711/preflight`：source=baselines/e2_alns/e2_80k_robustness_20260711/preflight/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_80k_robustness_fixed_20260711/formal`：source=baselines/e2_alns/e2_80k_robustness_fixed_20260711/formal/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_80k_robustness_repair_gate_20260711/preflight`：source=baselines/e2_alns/e2_80k_robustness_repair_gate_20260711/preflight/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_alns_budget_closure_static_20260717`：source=baselines/e2_alns/e2_alns_budget_closure_static_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['source', 'function', 'callee', 'occurrence', 'line', 'phase', 'solution_scope', 'accounting', 'closure_status', 'rationale']

- `baselines/e2_alns/e2_alns_budget_g0_20260718`：source=baselines/e2_alns/e2_alns_budget_g0_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['kind', 'source', 'function', 'callee', 'line', 'channel', 'status', 'detail']

- `baselines/e2_alns/e2_final_10seed_20260711`：source=baselines/e2_alns/e2_final_10seed_20260711/task_manifest.csv; keys=['instance', 'algorithm', 'eval_budget', 'scenario']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/e2_final_10seed_20260711/formal`：source=baselines/e2_alns/e2_final_10seed_20260711/formal/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={2: 41, 3: 15, 4: 6, 5: 2, 6: 1, 10: 5}

- `baselines/e2_alns/e2_final_10seed_20260711/representative_gate`：source=baselines/e2_alns/e2_final_10seed_20260711/representative_gate/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_final_10seed_20260711/smoke`：source=baselines/e2_alns/e2_final_10seed_20260711/smoke/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_final_closure_20260703`：该包无逐单元原始记录CSV

- `baselines/e2_alns/e2_final_closure_20260703/phase_a_alns_gate`：source=baselines/e2_alns/e2_final_closure_20260703/phase_a_alns_gate/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/e2_final_closure_20260703/phase_a_carbon_gate_superseded_under_eval`：source=baselines/e2_alns/e2_final_closure_20260703/phase_a_carbon_gate_superseded_under_eval/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/e2_final_closure_20260703/phase_a_prime_route_elimination_retest`：source=baselines/e2_alns/e2_final_closure_20260703/phase_a_prime_route_elimination_retest/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/e2_final_closure_20260703/phase_b_g3_baseline_health`：source=baselines/e2_alns/e2_final_closure_20260703/phase_b_g3_baseline_health/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 1, 3: 1}

- `baselines/e2_alns/e2_final_closure_20260703/phase_c_g4_stability`：source=baselines/e2_alns/e2_final_closure_20260703/phase_c_g4_stability/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 2}

- `baselines/e2_alns/e2_final_closure_20260703/phase_d_g5_t3_material`：source=baselines/e2_alns/e2_final_closure_20260703/phase_d_g5_t3_material/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 44, 3: 85}

- `baselines/e2_alns/e2_final_closure_20260703/phase_e_carbon_operator_diagnostic`：source=baselines/e2_alns/e2_final_closure_20260703/phase_e_carbon_operator_diagnostic/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/e2_g0_closure_hygiene_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/e2_g0_reaudit_20260702`：source=baselines/e2_alns/e2_g0_reaudit_20260702/raw_runs.csv; keys=['algorithm', 'eval_budget', 'max_runtime_seconds']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 5}

- `baselines/e2_alns/e2_g0_reaudit_v2_20260703`：source=baselines/e2_alns/e2_g0_reaudit_v2_20260703/raw_runs.csv; keys=['algorithm', 'eval_budget', 'max_runtime_seconds', 'start_policy']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 5}

- `baselines/e2_alns/e2_g0_same_value_platform_audit_data`：source=baselines/e2_alns/e2_g0_same_value_platform_audit_data/checkpoint_replay.csv; keys=['instance', 'algorithm']; seed=['seed']; values=['checkpoint_best_cost', 'replay_total_cost']; seed_counts={2: 7}

- `baselines/e2_alns/e2_homberger_200_source_gate_20260717`：source=baselines/e2_alns/e2_homberger_200_source_gate_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'class', 'series_member', 'source_member', 'source_member_sha256', 'node_count', 'customer_count', 'customer_id_min', 'customer_id_max', 'duplicate_id_count', 'ids_contiguous_0_200', 'vehicle_limit', 'capacity', 'total_customer_demand', 'demand_min', 'demand_max', 'demand_exceeds_capacity_count', 'depot_ready', 'depot_due', 'customer_ready_min', 'customer_due_max', 'customer_tw_width_min', 'customer_tw_width_max', 'customer_tw_width_mean', 'tw_order_violation_count', 'negative_demand_count', 'negative_service_count', 'x_min', 'x_max', 'y_min', 'y_max', 'source_gate_pass', 'search_evaluations']

- `baselines/e2_alns/e2_homberger_200_source_gate_20260717_v2`：source=baselines/e2_alns/e2_homberger_200_source_gate_20260717_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'class', 'series_member', 'source_member', 'source_member_sha256', 'node_count', 'customer_count', 'customer_id_min', 'customer_id_max', 'duplicate_id_count', 'ids_contiguous_0_200', 'vehicle_limit', 'capacity', 'total_customer_demand', 'demand_min', 'demand_max', 'demand_exceeds_capacity_count', 'depot_ready', 'depot_due', 'customer_ready_min', 'customer_due_max', 'customer_tw_width_min', 'customer_tw_width_max', 'customer_tw_width_mean', 'tw_order_violation_count', 'negative_demand_count', 'negative_service_count', 'x_min', 'x_max', 'y_min', 'y_max', 'source_gate_pass', 'search_evaluations']

- `baselines/e2_alns/e2_loss_recovery_20260711`：source=baselines/e2_alns/e2_loss_recovery_20260711/all_pairs.csv; keys=['instance', 'runtime_ratio']; seed=['seed']; values=['hybrid_cost', 'lns_cost']; seed_counts={}

- `baselines/e2_alns/e2_loss_recovery_20260711/proportional_true_lns_middle_gate`：source=baselines/e2_alns/e2_loss_recovery_20260711/proportional_true_lns_middle_gate/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['cost']; seed_counts={2: 9}

- `baselines/e2_alns/e2_loss_recovery_20260711/route_block_headroom_audit`：source=baselines/e2_alns/e2_loss_recovery_20260711/route_block_headroom_audit/candidate_attempts.csv; keys=['instance']; seed=['seed']; values=['cost']; seed_counts={2: 3}

- `baselines/e2_alns/e2_loss_recovery_20260711/short_gate`：source=baselines/e2_alns/e2_loss_recovery_20260711/short_gate/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['cost']; seed_counts={2: 9}

- `baselines/e2_alns/e2_loss_recovery_20260711/short_gate_formal_start`：source=baselines/e2_alns/e2_loss_recovery_20260711/short_gate_formal_start/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['cost']; seed_counts={2: 9}

- `baselines/e2_alns/e2_loss_recovery_20260711/true_lns_middle_gate`：source=baselines/e2_alns/e2_loss_recovery_20260711/true_lns_middle_gate/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['cost']; seed_counts={2: 9}

- `baselines/e2_alns/e2_refined_carbon_short_gate_20260711`：source=baselines/e2_alns/e2_refined_carbon_short_gate_20260711/raw_runs.csv; keys=['arm', 'eval_budget', 'instance']; seed=['seed']; values=['total_cost', 'route_signature']; seed_counts={3: 4}

- `baselines/e2_alns/e2_solomon_dimacs_adapter_20260717`：source=baselines/e2_alns/e2_solomon_dimacs_adapter_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'class', 'customers', 'max_vehicles', 'capacity', 'reference_value', 'optimal_flag', 'standardized_time_limit_s', 'zip_member', 'instance_sha256', 'official_byte_equal', 'node_structure_ok', 'distance_matrix_sha256', 'distance_rule', 'search_evaluations']

- `baselines/e2_alns/e2_solomon_external_baseline_preflight_20260717`：source=baselines/e2_alns/e2_solomon_external_baseline_preflight_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['baseline_id', 'available', 'version', 'module_origin', 'compatibility', 'e7_attestation_exists', 'tool_freeze_exists', 'search_evaluations']

- `baselines/e2_alns/e2_solomon_external_baseline_preflight_pyvrp0134_20260717`：source=baselines/e2_alns/e2_solomon_external_baseline_preflight_pyvrp0134_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['baseline_id', 'available', 'version', 'module_origin', 'compatibility', 'e7_attestation_exists', 'tool_freeze_exists', 'search_evaluations']

- `baselines/e2_alns/e2_solomon_sintef_bks_audit_20260717`：source=baselines/e2_alns/e2_solomon_sintef_bks_audit_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'display_name', 'class', 'bks_vehicles', 'bks_distance', 'reference_code', 'comment', 'solution_url', 'max_vehicles', 'capacity', 'computed_vehicles', 'computed_distance_double', 'computed_distance_rounded_2', 'vehicle_match', 'distance_match', 'solution_feasible', 'solution_sha256', 'search_evaluations']

- `baselines/e2_alns/e2_submission_20260711`：该包无逐单元原始记录CSV

- `baselines/e2_alns/e2_submission_20260711/baseline_health`：source=baselines/e2_alns/e2_submission_20260711/baseline_health/raw_runs.csv; keys=['algorithm', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2_submission_20260711/carbon_280`：source=baselines/e2_alns/e2_submission_20260711/carbon_280/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={2: 5, 3: 1}

- `baselines/e2_alns/e2_submission_20260711/preflight`：source=baselines/e2_alns/e2_submission_20260711/preflight/raw_runs.csv; keys=['algorithm', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={}

- `baselines/e2_alns/e2b_component_ablation_formal_20260715`：source=baselines/e2_alns/e2b_component_ablation_formal_20260715/raw_runs.csv; keys=['between_trip_gap_hours', 'charging_strategy', 'configured_search_budget', 'instance']; seed=['seed']; values=['total_cost', 'route_signature']; seed_counts={2: 1, 3: 2, 4: 2, 5: 1}

- `baselines/e2_alns/ev_heavy_findability_gate_baseline_liveness_smoke_v2_data`：source=baselines/e2_alns/ev_heavy_findability_gate_baseline_liveness_smoke_v2_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 4}

- `baselines/e2_alns/ev_heavy_findability_gate_data`：source=baselines/e2_alns/ev_heavy_findability_gate_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 7}

- `baselines/e2_alns/ev_heavy_findability_gate_liveness_allalg_data`：source=baselines/e2_alns/ev_heavy_findability_gate_liveness_allalg_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 4}

- `baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data`：source=baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 4}

- `baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe_data`：source=baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/ev_heavy_findability_gate_postfix_allalg_data`：source=baselines/e2_alns/ev_heavy_findability_gate_postfix_allalg_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 4}

- `baselines/e2_alns/ev_heavy_findability_gate_small_100c02_data`：source=baselines/e2_alns/ev_heavy_findability_gate_small_100c02_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 3}

- `baselines/e2_alns/ev_heavy_findability_gate_small_200c01_seed1_data`：source=baselines/e2_alns/ev_heavy_findability_gate_small_200c01_seed1_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'gap_vs_initial_pct', 'gap_to_ev_maximal_pct', 'closed_gap_fraction', 'initial_ev_share', 'eval_budget', 'seed_mode', 'seed_source']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/ev_heavy_regime_stage0_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/ev_heavy_regime_stage0_smoke_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/ev_seeded_search_stage1_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/fleet_cap_operational_gate_data`：source=baselines/e2_alns/fleet_cap_operational_gate_data/raw_runs.csv; keys=['B_battery_kwh', 'battery_kwh', 'cap_scenario', 'category', 'ev_customer_share', 'ev_demand_share', 'eval_budget', 'instance', 'size', 'variant']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e2_alns/global_repack_fleet_charge_probe_20260707`：source=baselines/e2_alns/global_repack_fleet_charge_probe_20260707/raw_runs.csv; keys=['budget', 'category', 'instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 64}

- `baselines/e2_alns/goeke80_multitrip_rescue_gate_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke`：source=baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke/throughput_goeke80_multitrip_smoke_raw_runs.csv; keys=['algorithm', 'category', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke/convergence_throughput`：source=baselines/e2_alns/goeke80_multitrip_rescue_gate_data/phase2_smoke/convergence_throughput/e2-multidepot-100c-01__LNS__seed1.csv; keys=['algorithm', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/goeke80_multitrip_t3_preflight_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/smoke`：source=baselines/e2_alns/goeke80_multitrip_t3_preflight_data/smoke/smoke_paired_summary.csv; keys=['category', 'gap_pct_alns_minus_lns', 'instance', 'size', 'winner_algorithm_for_composition']; seed=['seed']; values=['alns_cost', 'lns_cost']; seed_counts={}

- `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_a`：source=baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_a/stage_a_paired_summary.csv; keys=['category', 'gap_pct_alns_minus_lns', 'instance', 'size', 'winner_algorithm_for_composition']; seed=['seed']; values=['alns_cost', 'lns_cost']; seed_counts={3: 22}

- `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_b`：source=baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_b/stage_b_paired_summary.csv; keys=['category', 'gap_pct_alns_minus_lns', 'instance', 'size', 'winner_algorithm_for_composition']; seed=['seed']; values=['alns_cost', 'lns_cost']; seed_counts={2: 4, 3: 16}

- `baselines/e2_alns/goeke_public_benchmark_adapter_gate_20260716`：source=baselines/e2_alns/goeke_public_benchmark_adapter_gate_20260716/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'route_index', 'vehicle_type', 'sequence', 'customer_count', 'distance_m', 'initial_load_kg', 'end_time_s', 'minimum_battery_kwh', 'recharge_visits', 'capacity_feasible', 'time_window_feasible', 'battery_feasible', 'ends_empty']

- `baselines/e2_alns/goeke_public_benchmark_feasibility_20260716`：source=baselines/e2_alns/goeke_public_benchmark_feasibility_20260716/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'customers', 'published_best_distance_km', 'published_mean_runtime_min', 'published_runs', 'published_status', 'published_total_vehicles', 'published_used_ev', 'derived_published_used_cv', 'raw_num_veh_field', 'raw_num_petrol_veh_field', 'raw_num_electro_veh_field', 'published_counts_match_raw_composition', 'raw_sha256']

- `baselines/e2_alns/hard_cap_feasibility_audit_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/high_tension_separation_probe_09w_smoke_data`：source=baselines/e2_alns/high_tension_separation_probe_09w_smoke_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/high_tension_separation_probe_09w_stage_a_data`：source=baselines/e2_alns/high_tension_separation_probe_09w_stage_a_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/high_tension_separation_probe_smoke_data`：source=baselines/e2_alns/high_tension_separation_probe_smoke_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/high_tension_separation_probe_stage_a_data`：source=baselines/e2_alns/high_tension_separation_probe_stage_a_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/homberger_200_development_bundles_20260717`：source=baselines/e2_alns/homberger_200_development_bundles_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'class', 'customers', 'max_vehicles', 'capacity', 'source_sha256', 'bundle_instance_sha256', 'bundle_matrix_sha256', 'bundle_carbon_sha256', 'source_gate_pass', 'generic_loader_match', 'search_evaluations']

- `baselines/e2_alns/homberger_g1_sisr_micro_20260718`：source=baselines/e2_alns/homberger_g1_sisr_micro_20260718/raw_runs.csv; keys=['algorithm_best_obj', 'arm', 'eval_budget', 'instance']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/homberger_g1_sisr_micro_v2_20260718`：source=baselines/e2_alns/homberger_g1_sisr_micro_v2_20260718/raw_runs.csv; keys=['algorithm_best_obj', 'arm', 'eval_budget', 'instance']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/homberger_g1_sisr_micro_v2_20260718_aborted_path_bug`：该包无逐单元原始记录CSV

- `baselines/e2_alns/homberger_g1_true_swapstar_integration_smoke_20260718`：source=baselines/e2_alns/homberger_g1_true_swapstar_integration_smoke_20260718/raw_runs.csv; keys=['eval_budget', 'instance']; seed=['seed']; values=['expected_objective', 'objective']; seed_counts={}

- `baselines/e2_alns/homberger_g1_true_swapstar_integration_smoke_v2_20260718`：source=baselines/e2_alns/homberger_g1_true_swapstar_integration_smoke_v2_20260718/raw_runs.csv; keys=['eval_budget', 'instance']; seed=['seed']; values=['expected_objective', 'objective']; seed_counts={}

- `baselines/e2_alns/homberger_g1_true_swapstar_integration_smoke_v3_20260718`：source=baselines/e2_alns/homberger_g1_true_swapstar_integration_smoke_v3_20260718/raw_runs.csv; keys=['eval_budget', 'instance']; seed=['seed']; values=['expected_objective', 'objective']; seed_counts={}

- `baselines/e2_alns/homberger_g1_true_swapstar_micro_20260718`：source=baselines/e2_alns/homberger_g1_true_swapstar_micro_20260718/raw_runs.csv; keys=['arm', 'eval_budget', 'instance']; seed=['seed']; values=['algorithm_objective']; seed_counts={3: 4}

- `baselines/e2_alns/homberger_g1_true_swapstar_risk_gate_20260718`：source=baselines/e2_alns/homberger_g1_true_swapstar_risk_gate_20260718/raw_runs.csv; keys=['arm', 'eval_budget', 'instance']; seed=['seed']; values=['expected_objective', 'objective']; seed_counts={}

- `baselines/e2_alns/homberger_g1_true_swapstar_risk_gate_v2_20260718`：source=baselines/e2_alns/homberger_g1_true_swapstar_risk_gate_v2_20260718/raw_runs.csv; keys=['arm', 'eval_budget', 'instance']; seed=['seed']; values=['expected_objective', 'objective']; seed_counts={}

- `baselines/e2_alns/homberger_g1a_true_swapstar_20260718`：source=baselines/e2_alns/homberger_g1a_true_swapstar_20260718/raw_runs.csv; keys=['algorithm_best_obj', 'arm', 'eval_budget', 'geometry_family', 'instance']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/homberger_headroom_blind_bundles_20260719`：source=baselines/e2_alns/homberger_headroom_blind_bundles_20260719/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['family', 'instance', 'selection_rule', 'candidate_count', 'source_member', 'source_sha256', 'bundle_instance_sha256', 'bundle_matrix_sha256', 'bundle_carbon_sha256', 'generic_loader_match', 'search_evaluations']

- `baselines/e2_alns/instance_param_diagnostic_data`：source=baselines/e2_alns/instance_param_diagnostic_data/phase1_cost_breakdown.csv; keys=['instance', 'variant', 'eval_budget', 'max_runtime_seconds']; seed=['seed']; values=['total_cost']; seed_counts={3: 9}

- `baselines/e2_alns/iwd_fidelity_gate_20260712`：source=baselines/e2_alns/iwd_fidelity_gate_20260712/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'arm', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'parameter_notes_json', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={3: 6}

- `baselines/e2_alns/iwd_fidelity_gate_20260712_rescue_zhang_scaled`：source=baselines/e2_alns/iwd_fidelity_gate_20260712_rescue_zhang_scaled/raw_runs.csv; keys=['algorithm', 'algorithm_specific_update_count', 'arm', 'category', 'charging_strategy', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'parameter_notes_json', 'parameter_profile', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature', 'route_structure_signature']; seed_counts={3: 6}

- `baselines/e2_alns/l_main_v3_activation`：source=baselines/e2_alns/l_main_v3_activation/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'source_scale', 'merged_customer_count', 'carbon_slot_count', 'initial_solution_violation_count', 'failures']

- `baselines/e2_alns/largescale_allcv_diagnostic_data`：source=baselines/e2_alns/largescale_allcv_diagnostic_data/phase0_dominance.csv; keys=['instance', 'mean_gap_pct_mixed_minus_allcv']; seed=['best_allcv_seed', 'best_mixed_seed']; values=['best_allcv_cost', 'best_mixed_cost', 'mean_allcv_cost', 'mean_mixed_cost']; seed_counts={}

- `baselines/e2_alns/legacy_anchor`：source=baselines/e2_alns/legacy_anchor/phase2_current_vs_gold.csv; keys=['algorithm', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={10: 1}

- `baselines/e2_alns/lns_acceptance_scheduler_audit_20260705`：source=baselines/e2_alns/lns_acceptance_scheduler_audit_20260705/alns_candidate_trace.csv; keys=['remove_fraction', 'temperature', 'category', 'instance']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/lns_policy_kernel_probe_20260708`：source=baselines/e2_alns/lns_policy_kernel_probe_20260708/raw_runs.csv; keys=['algorithm', 'budget', 'category', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 96}

- `baselines/e2_alns/m1_chain_fast_distance_large_20260710`：source=baselines/e2_alns/m1_chain_fast_distance_large_20260710/raw_runs.csv; keys=['algorithm', 'dominant_pair_share', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_chain_hardest_20260710`：source=baselines/e2_alns/m1_chain_hardest_20260710/raw_runs.csv; keys=['algorithm', 'dominant_pair_share', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_chain_lazy_sort_large_20260710`：source=baselines/e2_alns/m1_chain_lazy_sort_large_20260710/raw_runs.csv; keys=['algorithm', 'dominant_pair_share', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_chain_monotone_fleet_20260710`：source=baselines/e2_alns/m1_chain_monotone_fleet_20260710/raw_runs.csv; keys=['algorithm', 'dominant_pair_share', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_chain_selector_20260710`：source=baselines/e2_alns/m1_chain_selector_20260710/raw_runs.csv; keys=['algorithm', 'dominant_pair_share', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_dominant_pair_autopsy_20260710`：source=baselines/e2_alns/m1_dominant_pair_autopsy_20260710/raw_runs.csv; keys=['dominant_pair_share']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_fair_sa_recheck_20260710`：source=baselines/e2_alns/m1_fair_sa_recheck_20260710/raw_runs.csv; keys=['dominant_operator_share', 'eval_budget']; seed=['seed']; values=['best_cost']; seed_counts={2: 2}

- `baselines/e2_alns/m1_fair_selector_20260710`：source=baselines/e2_alns/m1_fair_selector_20260710/raw_runs.csv; keys=['algorithm', 'dominant_pair_share', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={2: 1, 3: 3}

- `baselines/e2_alns/m1_fleet_opportunity_20260710`：source=baselines/e2_alns/m1_fleet_opportunity_20260710/raw_runs.csv; keys=['battery_kwh']; seed=['source_seed']; values=['total_cost']; seed_counts={3: 2}

- `baselines/e2_alns/m1_joint_repack_fleet_headroom_20260710`：source=baselines/e2_alns/m1_joint_repack_fleet_headroom_20260710/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['best_joint_cost', 'best_repack_cost', 'fleet_only_cost', 'initial_cost', 'source_cost']; seed_counts={}

- `baselines/e2_alns/m1_joint_repack_fleet_headroom_seeds2_3_20260710`：source=baselines/e2_alns/m1_joint_repack_fleet_headroom_seeds2_3_20260710/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['best_joint_cost', 'best_repack_cost', 'fleet_only_cost', 'initial_cost', 'source_cost']; seed_counts={2: 9}

- `baselines/e2_alns/m1_local_search_budget_20260710`：source=baselines/e2_alns/m1_local_search_budget_20260710/raw_runs.csv; keys=['effective_to_official_ratio', 'eval_budget', 'instance']; seed=['seed']; values=['best_cost']; seed_counts={3: 3}

- `baselines/e2_alns/m1_normalized_ucb_20260710`：source=baselines/e2_alns/m1_normalized_ucb_20260710/raw_runs.csv; keys=[]; seed=['seed']; values=['candidate_cost', 'reference_cost']; seed_counts={3: 1}

- `baselines/e2_alns/m1_normalized_ucb_20260710/candidate`：source=baselines/e2_alns/m1_normalized_ucb_20260710/candidate/raw_runs.csv; keys=['dominant_pair_share']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_repair_breadth_20260710`：source=baselines/e2_alns/m1_repair_breadth_20260710/raw_runs.csv; keys=[]; seed=['seed']; values=['candidate_cost', 'reference_cost']; seed_counts={2: 1}

- `baselines/e2_alns/m1_repair_breadth_20260710/candidate`：source=baselines/e2_alns/m1_repair_breadth_20260710/candidate/raw_runs.csv; keys=['dominant_pair_share']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_repair_cache_20260710`：source=baselines/e2_alns/m1_repair_cache_20260710/raw_runs.csv; keys=['dominant_pair_share']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/m1_scheduler_realization_20260710`：source=baselines/e2_alns/m1_scheduler_realization_20260710/raw_runs.csv; keys=['dominant_pair_share', 'eval_budget']; seed=['seed']; values=['best_cost']; seed_counts={3: 1}

- `baselines/e2_alns/m1_staged_chain_150c_multiseed_20260710`：source=baselines/e2_alns/m1_staged_chain_150c_multiseed_20260710/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['cost']; seed_counts={3: 2}

- `baselines/e2_alns/m1_staged_chain_gate_20260710`：source=baselines/e2_alns/m1_staged_chain_gate_20260710/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/e2_alns/m1_staged_hybrid_stability_20260710`：source=baselines/e2_alns/m1_staged_hybrid_stability_20260710/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'eval_budget', 'instance']; seed=['seed']; values=['cost']; seed_counts={5: 6}

- `baselines/e2_alns/m1_structure_reachability_20260710`：该包无逐单元原始记录CSV

- `baselines/e2_alns/modern_battery_regime_stage2_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/native_channel_autopsy_data`：source=baselines/e2_alns/native_channel_autopsy_data/raw_runs.csv; keys=['algorithm', 'category', 'instance', 'size', 'battery_kwh', 'eval_budget', 'seed_source']; seed=['seed']; values=['candidate_objective', 'best_cost', 'best_signature']; seed_counts={}

- `baselines/e2_alns/official_hgs_a_bridge_smoke_20260718`：source=baselines/e2_alns/official_hgs_a_bridge_smoke_20260718/raw_runs.csv; keys=['algorithm', 'instance', 'time_limit_seconds']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/e2_alns/official_hgs_b_gate_20260718`：source=baselines/e2_alns/official_hgs_b_gate_20260718/raw_runs.csv; keys=['algorithm', 'instance', 'gap_pct']; seed=['seed']; values=['cost']; seed_counts={3: 1}

- `baselines/e2_alns/parameter_evidence_review_data`：source=baselines/e2_alns/parameter_evidence_review_data/dominance.csv; keys=['instance', 'mean_gap_pct_mixed_minus_allcv']; seed=['best_allcv_seed', 'best_mixed_seed']; values=['best_allcv_cost', 'best_mixed_cost', 'mean_allcv_cost', 'mean_mixed_cost']; seed_counts={}

- `baselines/e2_alns/pyvrp_0134_tool_probe_20260717`：source=baselines/e2_alns/pyvrp_0134_tool_probe_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'formal_solomon_search_evaluations', 'synthetic_probe_iterations']

- `baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v2`：source=baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'formal_solomon_search_evaluations', 'synthetic_probe_iterations']

- `baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v3`：source=baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'formal_solomon_search_evaluations', 'synthetic_probe_iterations']

- `baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v4_repo_runtime`：source=baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v4_repo_runtime/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'formal_solomon_search_evaluations', 'synthetic_probe_iterations']

- `baselines/e2_alns/pyvrp_hgs_0122_tool_freeze_20260719`：source=baselines/e2_alns/pyvrp_hgs_0122_tool_freeze_20260719/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'formal_search_evaluations', 'synthetic_probe_iterations']

- `baselines/e2_alns/route_compression_probe_20260705`：source=baselines/e2_alns/route_compression_probe_20260705/raw_runs.csv; keys=['algorithm', 'category', 'display_algorithm', 'eval_budget', 'instance', 'low_carbon_charging_share', 'scenario_type', 'size']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={2: 10, 3: 18}

- `baselines/e2_alns/route_compression_trace_audit_20260705`：source=baselines/e2_alns/route_compression_trace_audit_20260705/alns_operator_contribution.csv; keys=['category', 'instance', 'display_algorithm']; seed=['seed']; values=['best_cost', 'route_elimination_objective_improve_count']; seed_counts={3: 48}

- `baselines/e2_alns/route_packing_reachability_audit_20260708`：source=baselines/e2_alns/route_packing_reachability_audit_20260708/decoder_reachability.csv; keys=['category', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={2: 4, 3: 1}

- `baselines/e2_alns/sa_acceptance_legacy_anchor`：source=baselines/e2_alns/sa_acceptance_legacy_anchor/phase2_current_vs_gold.csv; keys=['algorithm', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={10: 1}

- `baselines/e2_alns/scan_bridge_legacy_anchor`：source=baselines/e2_alns/scan_bridge_legacy_anchor/phase2_current_vs_gold.csv; keys=['algorithm', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={10: 1}

- `baselines/e2_alns/selector_pathology_audit_20260706`：source=baselines/e2_alns/selector_pathology_audit_20260706/pair_concentration_vs_gap.csv; keys=['category', 'instance', 'top1_pair_share', 'top2_pair_share', 'top3_pair_share']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/selector_sprint_failure_analysis_20260707`：该包无逐单元原始记录CSV

- `baselines/e2_alns/selector_sprint_probe_20260706`：source=baselines/e2_alns/selector_sprint_probe_20260706/raw_runs.csv; keys=['budget', 'category', 'instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 96}

- `baselines/e2_alns/solomon_cpu_preflight_20260717`：source=baselines/e2_alns/solomon_cpu_preflight_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['machine', 'chip', 'physical_cores', 'performance_cores', 'efficiency_cores', 'passmark_single_thread', 'time_factor', 'search_evaluations']

- `baselines/e2_alns/solomon_cpu_preflight_20260717_v2`：source=baselines/e2_alns/solomon_cpu_preflight_20260717_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['machine', 'chip', 'physical_cores', 'performance_cores', 'efficiency_cores', 'passmark_single_thread', 'time_factor', 'search_evaluations']

- `baselines/e2_alns/solomon_cpu_preflight_20260717_v3`：source=baselines/e2_alns/solomon_cpu_preflight_20260717_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['machine', 'chip', 'physical_cores', 'performance_cores', 'efficiency_cores', 'passmark_single_thread', 'time_factor', 'search_evaluations']

- `baselines/e2_alns/solomon_cpu_preflight_20260717_v4`：source=baselines/e2_alns/solomon_cpu_preflight_20260717_v4/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['machine', 'chip', 'physical_cores', 'performance_cores', 'efficiency_cores', 'passmark_single_thread', 'time_factor', 'search_evaluations']

- `baselines/e2_alns/solomon_cpu_preflight_20260717_v5`：source=baselines/e2_alns/solomon_cpu_preflight_20260717_v5/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['machine', 'chip', 'physical_cores', 'performance_cores', 'efficiency_cores', 'passmark_single_thread', 'time_factor', 'search_evaluations']

- `baselines/e2_alns/solomon_dimacs_formal_bundles_20260717`：该包无逐单元原始记录CSV

- `baselines/e2_alns/solomon_sintef_formal_bundles_20260717`：该包无逐单元原始记录CSV

- `baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v2`：source=baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'class', 'customers', 'max_vehicles', 'capacity', 'bks_vehicles', 'bks_distance', 'bks_reference_code', 'source_solution_sha256', 'bundle_instance_sha256', 'bundle_matrix_sha256', 'bundle_carbon_sha256', 'generic_loader_match', 'search_evaluations']

- `baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3`：source=baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'class', 'customers', 'max_vehicles', 'capacity', 'bks_vehicles', 'bks_distance', 'bks_reference_code', 'source_solution_sha256', 'bundle_instance_sha256', 'bundle_matrix_sha256', 'bundle_carbon_sha256', 'generic_loader_match', 'search_evaluations']

- `baselines/e2_alns/source_bound_mixed_band_gate_data`：source=baselines/e2_alns/source_bound_mixed_band_gate_data/raw_runs.csv; keys=['B_battery_kwh', 'battery_kwh', 'category', 'ev_customer_share', 'ev_demand_share', 'eval_budget', 'instance', 'variant']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e2_alns/source_bound_operational_mix_map_data`：source=baselines/e2_alns/source_bound_operational_mix_map_data/raw_runs.csv; keys=['battery_kwh', 'category', 'constraint_scenario', 'depot_charging_energy_share', 'ev_customer_share', 'ev_demand_share', 'eval_budget', 'instance', 'public_charging_energy_share', 'size', 'variant', 'cap_precheck_cv_seed_cv_routes', 'cap_precheck_cv_seed_routes']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e2_alns/strong_bridge_backend_probe_20260705`：source=baselines/e2_alns/strong_bridge_backend_probe_20260705/raw_runs.csv; keys=['category', 'instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 32}

- `baselines/e2_alns/strong_bridge_backend_probe_local_search_check_20260706`：source=baselines/e2_alns/strong_bridge_backend_probe_local_search_check_20260706/raw_runs.csv; keys=['category', 'instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 32}

- `baselines/e2_alns/structural_mixed_band_investigation_data`：source=baselines/e2_alns/structural_mixed_band_investigation_data/stage_a_75_200_joined.csv; keys=['battery_kwh', 'category', 'cv_shell_ev_customer_share', 'cv_shell_ev_demand_share', 'ev_shell_ev_customer_share', 'ev_shell_ev_demand_share', 'free_mixed_ev_customer_share', 'free_mixed_ev_demand_share', 'instance', 'size', 'winner_ev_customer_share', 'winner_ev_demand_share', 'winner_variant', 'structure_instance', 'family', 'station_strategy', 'depot_strategy']; seed=['seed']; values=['cv_shell_cost', 'ev_shell_cost', 'free_mixed_cost', 'winner_total_cost']; seed_counts={}

- `baselines/e2_alns/structural_rescue_probe_20260707`：source=baselines/e2_alns/structural_rescue_probe_20260707/raw_runs.csv; keys=['budget', 'category', 'instance', 'algorithm', 'eval_budget']; seed=['seed']; values=['best_cost', 'best_signature']; seed_counts={3: 32}

- `baselines/e2_alns/threeshift_280_stageA_generalization_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/threeshift_280_stageB_algorithm_comparison_data`：source=baselines/e2_alns/threeshift_280_stageB_algorithm_comparison_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'eval_budget', 'low_carbon_charging_share', 'seed_source']; seed=['seed']; values=['best_cost']; seed_counts={3: 48}

- `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data`：source=baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'eval_budget', 'low_carbon_charging_share', 'seed_source']; seed=['seed']; values=['best_cost']; seed_counts={2: 5}

- `baselines/e2_alns/threeshift_280_stageB_anchor_warmstart_probe_stageA_data`：该包无逐单元原始记录CSV

- `baselines/e2_alns/threeshift_280_stageB_full8_seed12_probe_data`：source=baselines/e2_alns/threeshift_280_stageB_full8_seed12_probe_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'eval_budget', 'low_carbon_charging_share', 'seed_source']; seed=['seed']; values=['best_cost']; seed_counts={2: 12}

- `baselines/e2_alns/threeshift_280_stageB_small_warmstart_probe_data`：source=baselines/e2_alns/threeshift_280_stageB_small_warmstart_probe_data/raw_runs.csv; keys=['stage', 'category', 'instance', 'size', 'algorithm', 'battery_kwh', 'eval_budget', 'low_carbon_charging_share', 'seed_source']; seed=['seed']; values=['best_cost']; seed_counts={2: 6, 3: 1}

- `baselines/e2_alns/throughput_legacy_anchor`：source=baselines/e2_alns/throughput_legacy_anchor/phase2_current_vs_gold.csv; keys=['algorithm', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={10: 1}

- `baselines/e2_alns/wallclock_battery_preflight_data`：source=baselines/e2_alns/wallclock_battery_preflight_data/task_queue.csv; keys=['algorithm', 'battery_kwh', 'eval_budget', 'instance', 'scenario', 'size']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_alns/wallclock_battery_preflight_smoke_data`：source=baselines/e2_alns/wallclock_battery_preflight_smoke_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/wallclock_battery_preflight_stagea_data`：source=baselines/e2_alns/wallclock_battery_preflight_stagea_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data`：source=baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data/raw_runs.csv; keys=['algorithm', 'battery_kwh', 'category', 'instance', 'scenario', 'scenario_label', 'size']; seed=['seed']; values=['best_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/.e2-history-archive-small-instance-v1.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/chen_style_mechanism_case_trajectory/representative_gate`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/chen_style_mechanism_case_trajectory/representative_gate/raw_runs.csv; keys=['arm']; seed=['seed']; values=['cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/chen_style_mechanism_case_trajectory/representative_gate/trajectories`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/chen_style_mechanism_case_trajectory/representative_gate/trajectories/raw_runs.csv; keys=['algorithm', 'curve_point_count']; seed=['selected_seed']; values=['sealed_final_cost', 'rerun_final_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/history_archive_small_instance_v1`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/history_archive_small_instance_v1/raw_runs.csv; keys=['instance_id', 'view', 'stage']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/history_diverse_route_pool_gate`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/history_diverse_route_pool_gate/raw_runs.csv; keys=['instance_id', 'customer_count', 'historical_population_archive_enabled', 'historical_population_snapshot_count', 'historical_population_candidate_references', 'HGS-F_curve_points', 'HGS-E_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'main_curve_gate']; seed=['seed']; values=['protected_stage_1_cost', 'candidate_final_cost', 'HGS-F_cost', 'HGS-E_cost', 'HGS-M_cost', 'best_current_single_view_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/mip_integrity_staged_gate`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/mip_integrity_staged_gate/raw_runs.csv; keys=['instance_id', 'customer_count', 'HGS-F_curve_points', 'HGS-E_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'main_curve_gate']; seed=['seed']; values=['protected_stage_1_cost', 'candidate_final_cost', 'HGS-F_cost', 'HGS-E_cost', 'HGS-M_cost', 'best_current_single_view_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/multiview_portfolio_confirmation`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/multiview_portfolio_confirmation/raw_runs.csv; keys=['instance_id', 'customer_count', 'historical_population_archive_enabled', 'historical_population_snapshot_count', 'historical_population_candidate_references', 'HGS-F_curve_points', 'HGS-E_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'main_curve_gate']; seed=['seed']; values=['protected_stage_1_cost', 'candidate_final_cost', 'HGS-F_cost', 'HGS-E_cost', 'HGS-M_cost', 'best_current_single_view_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/online_exact_checkpoint_gate`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/online_exact_checkpoint_gate/raw_runs.csv; keys=['instance_id', 'customer_count', 'HGS-F_curve_points', 'HGS-E_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'main_curve_gate']; seed=['seed']; values=['control_cost', 'candidate_cost', 'HGS-F_cost', 'HGS-E_cost', 'HGS-M_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/staged_deepening_confirmation_gate`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/staged_deepening_confirmation_gate/raw_runs.csv; keys=['HGS-E_curve_points', 'HGS-F_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'customer_count', 'instance_id', 'main_curve_gate']; seed=['seed']; values=['HGS-E_cost', 'HGS-F_cost', 'HGS-M_cost', 'candidate_final_cost', 'protected_stage_1_cost', 'best_current_single_view_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/staged_deepening_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/staged_deepening_v2_gate`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/staged_deepening_v2_gate/raw_runs.csv; keys=['instance_id', 'customer_count', 'HGS-F_curve_points', 'HGS-E_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'main_curve_gate']; seed=['seed']; values=['protected_stage_1_cost', 'candidate_final_cost', 'HGS-F_cost', 'HGS-E_cost', 'HGS-M_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/type_preserving_staged_gate`：source=baselines/e2_final_campaign_20260720/algorithm_repair_diagnostic_20260724/type_preserving_staged_gate/raw_runs.csv; keys=['instance_id', 'customer_count', 'HGS-F_curve_points', 'HGS-E_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'main_curve_gate']; seed=['seed']; values=['protected_stage_1_cost', 'candidate_final_cost', 'HGS-F_cost', 'HGS-E_cost', 'HGS-M_cost', 'best_current_single_view_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/convergence_gate/gate`：source=baselines/e2_final_campaign_20260720/convergence_gate/gate/raw_runs.csv; keys=['instance_id', 'cpu_ratio']; seed=['seed']; values=['mother_cost', 'hybrid_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-china81-e2-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-china81-e2-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-china81-e2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-china81-e2.monitor-v2`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-china81-e2.monitor-v3`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-china81-e2.monitor-v4`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-s3-trajectories-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-s3-trajectories-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-s3-trajectories.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-s3-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-s3-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-s3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/.d6-corrected-v3-preflight.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/full_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/full_gate/raw_runs.csv; keys=['instance_id', 'region', 'mip_time_limit_seconds']; seed=['seed']; values=['mip_objective']; seed_counts={5: 81}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/public_p1_no_search_replay`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/public_p1_no_search_replay/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['mother_cost', 'hybrid_cost']; seed_counts={10: 28}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/representative_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/representative_gate/raw_runs.csv; keys=['instance_id', 'n', 'arm']; seed=['seed']; values=['cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/representative_gate/trajectories`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/representative_gate/trajectories/raw_runs.csv; keys=['algorithm', 'curve_point_count']; seed=['selected_seed']; values=['sealed_final_cost', 'rerun_final_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_20260723/table4_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/full_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/full_gate/raw_runs.csv; keys=['instance_id', 'region', 'mip_time_limit_seconds']; seed=['seed']; values=['mip_objective']; seed_counts={5: 81}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/full_witness_replay`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/full_witness_replay/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['recorded_cost', 'replayed_cost']; seed_counts={5: 324}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/representative_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/representative_gate/raw_runs.csv; keys=['instance_id', 'n', 'arm']; seed=['seed']; values=['cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/representative_gate/trajectories`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/representative_gate/trajectories/raw_runs.csv; keys=['algorithm', 'curve_point_count']; seed=['selected_seed']; values=['sealed_final_cost', 'rerun_final_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v2_20260723/table4_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/artifacts`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/full_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/full_gate/raw_runs.csv; keys=['instance_id', 'region', 'mip_time_limit_seconds']; seed=['seed']; values=['mip_objective']; seed_counts={5: 81}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/full_witness_replay`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/full_witness_replay/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['recorded_cost', 'replayed_cost']; seed_counts={5: 324}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/preflight_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/preflight_gate/raw_runs.csv; keys=['instance_id', 'region', 'mip_time_limit_seconds']; seed=['seed']; values=['mip_objective']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/representative_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/representative_gate/raw_runs.csv; keys=['instance_id', 'n', 'arm']; seed=['seed']; values=['cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/representative_gate/trajectories`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/representative_gate/trajectories/raw_runs.csv; keys=['algorithm', 'curve_point_count']; seed=['selected_seed']; values=['sealed_final_cost', 'rerun_final_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v3_20260724/table4_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-china81-e2-v4-archive-route-reuse.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-e2-result-strength-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-full-witness-replay-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-s3-mechanism-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-s3-representative-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/.d6-corrected-s3-trajectories-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/artifacts`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/full_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/full_gate/raw_runs.csv; keys=['instance_id', 'region', 'mip_time_limit_seconds']; seed=['seed']; values=['mip_objective']; seed_counts={2: 3, 3: 1, 4: 3, 5: 70}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/full_witness_replay`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/full_witness_replay/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['recorded_cost', 'replayed_cost']; seed_counts={5: 324}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/mechanism_case_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/mechanism_case_gate/raw_runs.csv; keys=['instance_id', 'n', 'arm']; seed=['seed']; values=['cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/mechanism_case_gate/trajectories`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/mechanism_case_gate/trajectories/raw_runs.csv; keys=['algorithm', 'curve_point_count']; seed=['selected_seed']; values=['sealed_final_cost', 'rerun_final_cost', 'observed_minimum_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/preflight_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/preflight_gate/raw_runs.csv; keys=['instance_id', 'region', 'mip_time_limit_seconds']; seed=['seed']; values=['mip_objective']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/representative_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/representative_gate/raw_runs.csv; keys=['instance_id', 'n', 'arm']; seed=['seed']; values=['cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/result_strength_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/table4_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v5_staged_portfolio_20260724/.d6-corrected-china81-e2-staged-v5.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v6_budget_recheck_20260724/.d6-corrected-china81-e2-staged-v6-budget-recheck-retry.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v6_budget_recheck_20260724/.d6-corrected-china81-e2-staged-v6-budget-recheck.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.d6-corrected-china81-e2-staged-v7-formal.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.d6-corrected-china81-e2-staged-v7-preflight.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-staged-v7-release-chain.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-staged-v7-release-recovery-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/.e2-v7-paper-candidate-chain.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate/raw_runs.csv; keys=['HGS-E_curve_points', 'HGS-F_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points', 'budget_padding_reference_arm', 'historical_population_candidate_references', 'historical_population_snapshot_count', 'instance_id', 'mip_time_limit_seconds_per_stage', 'region']; seed=['seed']; values=['base_mip_objective', 'expanded_mip_objective']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_witness_replay`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_witness_replay/raw_runs.csv; keys=['instance_id', 'arm']; seed=['seed']; values=['recorded_cost', 'replayed_cost']; seed_counts={5: 324}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/mechanical_release_gate_v1`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/mechanical_release_gate_v1/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['stage', 'observed', 'required', 'done_present', 'count_checks', 'manifest_entries', 'manifest_failures', 'status']

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/preflight_gate`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/preflight_gate/raw_runs.csv; keys=['instance_id', 'region', 'budget_padding_reference_arm', 'historical_population_snapshot_count', 'historical_population_candidate_references', 'mip_time_limit_seconds_per_stage', 'HGS-F_curve_points', 'HGS-E_curve_points', 'HGS-M_curve_points', 'MV-HGS-SP_curve_points']; seed=['seed']; values=['base_mip_objective', 'expanded_mip_objective']; seed_counts={}

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/release_chain`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/release_recovery_v2`：source=baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/release_recovery_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['stage', 'status', 'observed', 'required', 'returncode', 'manifest_entries', 'detail']

- `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/result_strength_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_china_rep`：source=baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_china_rep/raw_runs.csv; keys=['instance_id', 'cpu_ratio']; seed=['seed']; values=['mother_cost', 'hybrid_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_confirm`：source=baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_confirm/raw_runs.csv; keys=['instance_id', 'cpu_ratio', 'mother_gap_to_bks_percent', 'hybrid_gap_to_bks_percent', 'percent_of_mother_gap_closed']; seed=['seed']; values=['mother_cost', 'hybrid_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_dev`：source=baselines/e2_final_campaign_20260720/mv_hgs_sp_final/gate_dev/raw_runs.csv; keys=['instance_id', 'cpu_ratio', 'mother_gap_to_bks_percent', 'hybrid_gap_to_bks_percent', 'percent_of_mother_gap_closed']; seed=['seed']; values=['mother_cost', 'hybrid_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate`：source=baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate/raw_runs.csv; keys=['instance_id', 'cpu_ratio']; seed=['seed']; values=['mother_cost', 'hybrid_cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p3_china81_gate`：source=baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p3_china81_gate/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['mother_cost', 'ablation_cost', 'full_cost']; seed_counts={5: 81}

- `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p4_bks_sprint`：source=baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p4_bks_sprint/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['sprint_cost']; seed_counts={2: 15}

- `baselines/e2_final_campaign_20260720/p0_fuse/p0_gate`：source=baselines/e2_final_campaign_20260720/p0_fuse/p0_gate/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_final_campaign_20260720/p0_fuse/p0_gate/p0_resume_150c_log`：source=baselines/e2_final_campaign_20260720/p0_fuse/p0_gate/p0_resume_150c_log/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e2_final_campaign_20260720/p0_fuse/rebalance_gate`：source=baselines/e2_final_campaign_20260720/p0_fuse/rebalance_gate/raw_runs.csv; keys=['instance_id', 'C2_backbone_share']; seed=['seed']; values=['C2_rebalanced_cost']; seed_counts={5: 3}

- `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain-v6.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s2-to-s5-chain.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s4-v2-to-s5-chain-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/.e2-s4-v2-to-s5-chain-v5.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/.e2-s5-artifacts.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['cost']; seed_counts={5: 81}

- `baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/.e2-s2-full-threeview.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['cost']; seed_counts={}

- `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v2`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v3`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/.e2-s1-threeview-preflight.monitor-v4`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/raw_runs.csv; keys=['instance_id', 'n', 'arm']; seed=['seed']; values=['cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/.e2-s3-representative.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/raw_runs.csv; keys=['instance_id', 'n', 'arm']; seed=['seed']; values=['sealed_cost', 'rerun_cost']; seed_counts={10: 4}

- `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/.e2-s3-trajectory-v4-rerun.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/.e2-s3-trajectory-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_01_instance_details`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_01_instance_details/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['source_role', 'source_path', 'sha256', 'row_count', 'selected_row_count']

- `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v5`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v5/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['figure', 'series', 'source_row', 'x', 'y', 'source_path', 'source_sha256']

- `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v6`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v6/raw_runs_v6.csv; 该CSV无seed或同义逐单元种子列；header=['figure', 'series', 'source_row', 'x', 'y', 'source_path', 'source_sha256']

- `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v7`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_02_figure_v7/raw_runs_v7.csv; 该CSV无seed或同义逐单元种子列；header=['figure', 'series', 'source_row', 'x', 'y', 'source_path', 'source_sha256']

- `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_03_pyvrp_education_neighborhoods`：source=baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_03_pyvrp_education_neighborhoods/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['record_type', 'operator', 'kind', 'supports_representative', 'source_file', 'source_line']

- `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/.e2-s4-route-detail.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/engineering`：source=baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/engineering/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['exact_objective']; seed_counts={}

- `baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/formal`：source=baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/formal/raw_runs.csv; keys=['instance_id']; seed=['seed']; values=['exact_objective']; seed_counts={2: 3}

- `baselines/e2_rerun_unified_01_20260727/.e2-rerun-unified-01-full-clean-restart.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_20260727/vehicle_feasibility_preflight`：source=baselines/e2_rerun_unified_01_20260727/vehicle_feasibility_preflight/raw_runs.csv; keys=['instance_id', 'region', 'customer_count', 'ev_customer_share']; seed=['seed']; values=['final_cost']; seed_counts={}

- `baselines/e2_rerun_unified_01_20260727/vehicle_feasibility_preflight/.e2-rerun-unified-01-vehicle-feasibility-preflight.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_step0_20260727`：source=baselines/e2_rerun_unified_01_step0_20260727/raw_runs.csv; keys=['instance_id', 'region', 'customer_count', 'arm']; seed=['seed']; values=['final_cost']; seed_counts={}

- `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v3.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v4.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence-v5.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_step0_20260727/.e2-rerun-unified-01-step0-convergence.monitor`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_engineering_import_halt/monitor_scene`：该包无逐单元原始记录CSV

- `baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_monitor_schema_halts`：source=baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_monitor_schema_halts/raw_header_before_v4.csv; keys=['instance_id', 'region', 'customer_count', 'arm']; seed=['seed']; values=['final_cost']; seed_counts={}

- `baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_non_sandbox_halt`：source=baselines/e2_rerun_unified_01_step0_20260727/halt_history/20260727_non_sandbox_halt/raw_runs.csv; keys=['instance_id', 'region', 'customer_count', 'arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_clock_semantics_governance_20260713`：source=baselines/e3_ablation/e3_clock_semantics_governance_20260713/raw_runs.csv; keys=['instance']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_clock_semantics_governance_20260713/attempt_01_wrong_bundle`：source=baselines/e3_ablation/e3_clock_semantics_governance_20260713/attempt_01_wrong_bundle/raw_runs.csv; keys=['instance']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_common_fleet_envelope_design_20260713`：source=baselines/e3_ablation/e3_common_fleet_envelope_design_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'source_scale', 'condition', 'ownership_map_sha256', 'source_num_cv', 'source_num_ev', 'common_cap_cv', 'common_cap_ev', 'witness_cv', 'witness_ev', 'trip_count', 'depot_counts_json', 'violation_count', 'status']

- `baselines/e3_ablation/e3_common_fleet_envelope_design_v2_20260713`：source=baselines/e3_ablation/e3_common_fleet_envelope_design_v2_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'source_scale', 'condition', 'ownership_map_sha256', 'source_num_cv', 'source_num_ev', 'common_cap_cv', 'common_cap_ev', 'witness_cv', 'witness_ev', 'trip_count', 'depot_counts_json', 'violation_count', 'status']

- `baselines/e3_ablation/e3_common_fleet_envelope_design_v3_20260713`：source=baselines/e3_ablation/e3_common_fleet_envelope_design_v3_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance', 'source_scale', 'condition', 'ownership_map_sha256', 'source_num_cv', 'source_num_ev', 'common_cap_cv', 'common_cap_ev', 'witness_cv', 'witness_ev', 'trip_count', 'depot_counts_json', 'violation_count', 'status']

- `baselines/e3_ablation/e3_medium_ownership_diagnostic_20260715`：source=baselines/e3_ablation/e3_medium_ownership_diagnostic_20260715/raw_runs.csv; keys=['instance', 'customer_count', 'cross_site_customer_share', 'cross_site_demand_share']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_medium_paired_cost_formal_20260715`：source=baselines/e3_ablation/e3_medium_paired_cost_formal_20260715/raw_runs.csv; keys=['arm', 'between_trip_gap_hours', 'budget', 'cross_site_customer_share', 'cross_site_demand_share', 'instance', 'raw_search_between_trip_gap_hours', 'raw_search_cross_site_customer_share', 'raw_search_cross_site_demand_share', 'random_seed']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e3_ablation/e3_medium_paired_cost_formal_20260715/compatibility`：source=baselines/e3_ablation/e3_medium_paired_cost_formal_20260715/compatibility/endpoint_reproduction_probe.csv; keys=['instance', 'arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_mismatch_formal_20260713_25`：source=baselines/e3_ablation/e3_mismatch_formal_20260713_25/raw_runs.csv; keys=['share', 'map_seed']; seed=['seed']; values=['total_cost']; seed_counts={10: 1}

- `baselines/e3_ablation/e3_mismatch_formal_20260713_50`：source=baselines/e3_ablation/e3_mismatch_formal_20260713_50/raw_runs.csv; keys=['share', 'map_seed']; seed=['seed']; values=['total_cost']; seed_counts={10: 1}

- `baselines/e3_ablation/e3_multitrip_formula_validation_20260713`：source=baselines/e3_ablation/e3_multitrip_formula_validation_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'status', 'detail']

- `baselines/e3_ablation/e3_multitrip_model_gate_20260712`：source=baselines/e3_ablation/e3_multitrip_model_gate_20260712/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'status', 'evaluations', 'wall_seconds', 'strict_violation_count', 'initial_cost', 'best_cost', 'improvement_percent']

- `baselines/e3_ablation/e3_multitrip_search_gate_20260712`：source=baselines/e3_ablation/e3_multitrip_search_gate_20260712/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'status', 'evaluations', 'wall_seconds', 'strict_violation_count']

- `baselines/e3_ablation/e3_multitrip_structure_gate_20260712`：source=baselines/e3_ablation/e3_multitrip_structure_gate_20260712/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'status', 'route_count', 'customer_count', 'physical_cv', 'physical_ev', 'wall_seconds', 'route_violation_count']

- `baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712`：source=baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'recharge_mode', 'status', 'route_count', 'customer_count', 'physical_cv', 'physical_ev', 'depot_charge_power_kw', 'charge_energy_kwh', 'max_trips_per_vehicle', 'wall_seconds', 'route_violation_count']

- `baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v2`：source=baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'recharge_mode', 'status', 'route_count', 'customer_count', 'physical_cv', 'physical_ev', 'depot_charge_power_kw', 'charge_energy_kwh', 'max_trips_per_vehicle', 'wall_seconds', 'route_violation_count']

- `baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v3`：source=baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v3/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'recharge_mode', 'status', 'route_count', 'customer_count', 'physical_cv', 'physical_ev', 'depot_charge_power_kw', 'charge_energy_kwh', 'max_trips_per_vehicle', 'wall_seconds', 'route_violation_count']

- `baselines/e3_ablation/e3_multitrip_structure_gate_v2_20260713`：source=baselines/e3_ablation/e3_multitrip_structure_gate_v2_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['case', 'recharge_mode', 'status', 'route_count', 'customer_count', 'physical_cv', 'physical_ev', 'depot_charge_power_kw', 'charge_energy_kwh', 'max_trips_per_vehicle', 'wall_seconds', 'route_violation_count']

- `baselines/e3_ablation/e3_ownership_class_design_20260713`：source=baselines/e3_ablation/e3_ownership_class_design_20260713/raw_runs.csv; keys=['instance', 'customer_count', 'moved_customer_share']; seed=['map_seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_ownership_class_design_v2_20260713`：source=baselines/e3_ablation/e3_ownership_class_design_v2_20260713/raw_runs.csv; keys=['instance', 'customer_count', 'moved_customer_share']; seed=['map_seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_ownership_class_design_v3_20260713`：source=baselines/e3_ablation/e3_ownership_class_design_v3_20260713/raw_runs.csv; keys=['instance', 'customer_count', 'moved_customer_share']; seed=['map_seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_ownership_class_design_v4_20260713`：source=baselines/e3_ablation/e3_ownership_class_design_v4_20260713/raw_runs.csv; keys=['instance', 'customer_count', 'moved_customer_share']; seed=['map_seed']; values=[]; seed_counts={}

- `baselines/e3_ablation/e3_paired_cost_formal_20260713`：source=baselines/e3_ablation/e3_paired_cost_formal_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['run_id']

- `baselines/e3_ablation/e3_paired_cost_formal_v2_20260713`：source=baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/raw_runs.csv; keys=['arm', 'between_trip_gap_hours', 'budget', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={2: 4, 3: 6}

- `baselines/e3_ablation/e3_same_start_wiring_probe_20260713`：source=baselines/e3_ablation/e3_same_start_wiring_probe_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'allow_cross_depot', 'start_sha256', 'budget', 'evaluations', 'elapsed_seconds', 'status', 'violation_count', 'total_cost', 'cost_component_error', 'cross_site_customer_count', 'cross_site_complete_candidates', 'cross_site_legal_candidates', 'cross_site_accepted_candidates', 'physical_cv', 'physical_ev', 'physical_total', 'trip_count', 'vehicle_work_hours', 'between_trip_gap_hours', 'max_trips_per_vehicle']

- `baselines/e3_ablation/e3_same_start_wiring_probe_v2_20260713`：source=baselines/e3_ablation/e3_same_start_wiring_probe_v2_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'allow_reassignment', 'start_sha256', 'expected_start_sha256', 'budget', 'evaluations', 'elapsed_seconds', 'status', 'violation_count', 'total_cost', 'cost_component_error', 'cross_site_customer_count', 'cross_site_complete_candidates', 'cross_site_legal_candidates', 'cross_site_accepted_candidates', 'physical_cv', 'physical_ev', 'physical_total', 'trip_count', 'vehicle_work_hours', 'between_trip_gap_hours', 'max_trips_per_vehicle']

- `baselines/e3_ablation/e3_static_clock_probe_20260713`：source=baselines/e3_ablation/e3_static_clock_probe_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['strategy', 'route_fingerprint', 'total_charging_kwh', 'first_trip_charge_day_offset', 'hard_violation_count', 'hard_violation_types', 'hard_violation_sample', 'first_trip_charge_after_departure', 'first_trip_charge_wrong_day_offset', 'same_vehicle_charge_trip_overlaps', 'same_vehicle_charge_charge_overlaps', 'total_cost', 'ev_charging_emissions_kg']

- `baselines/e3_ablation/e3_story_forensic_audit_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_submission_20260711/formal`：source=baselines/e3_ablation/e3_submission_20260711/formal/raw_runs.csv; keys=['battery_kwh', 'carbon_quota_kg', 'eval_budget', 'instance', 'min_profit_ratio', 'variant']; seed=['seed']; values=['total_cost', 'route_structure_signature']; seed_counts={5: 4}

- `baselines/e3_ablation/e3_submission_20260711/preflight`：source=baselines/e3_ablation/e3_submission_20260711/preflight/raw_runs.csv; keys=['battery_kwh', 'carbon_quota_kg', 'eval_budget', 'instance', 'min_profit_ratio', 'variant']; seed=['seed']; values=['total_cost', 'route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v10_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v10_clean_20260713/model_gate`：source=baselines/e3_ablation/e3_v10_clean_20260713/model_gate/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v10_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v10_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v10_clean_20260713/rehearsal`：source=baselines/e3_ablation/e3_v10_clean_20260713/rehearsal/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v11_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v11_clean_20260713/final100`：source=baselines/e3_ablation/e3_v11_clean_20260713/final100/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={3: 1}

- `baselines/e3_ablation/e3_v11_clean_20260713/formal70`：source=baselines/e3_ablation/e3_v11_clean_20260713/formal70/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={3: 1}

- `baselines/e3_ablation/e3_v11_clean_20260713/model_gate`：source=baselines/e3_ablation/e3_v11_clean_20260713/model_gate/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v11_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v11_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v11_clean_20260713/promote100`：source=baselines/e3_ablation/e3_v11_clean_20260713/promote100/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v11_clean_20260713/rehearsal`：source=baselines/e3_ablation/e3_v11_clean_20260713/rehearsal/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v3_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v3_20260713/smoke`：source=baselines/e3_ablation/e3_v3_20260713/smoke/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v3_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v3_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v3_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v4_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v4_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v4_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v5_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v5_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v5_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v6_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v6_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v6_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v7_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v7_clean_20260713/model_gate`：source=baselines/e3_ablation/e3_v7_clean_20260713/model_gate/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v7_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v7_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v7_clean_20260713/preflight/exhibit_smoke`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v7_clean_20260713/rehearsal`：source=baselines/e3_ablation/e3_v7_clean_20260713/rehearsal/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v8_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v8_clean_20260713/model_gate`：source=baselines/e3_ablation/e3_v8_clean_20260713/model_gate/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v8_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v8_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v8_clean_20260713/preflight/exhibit_smoke`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v8_clean_20260713/rehearsal`：source=baselines/e3_ablation/e3_v8_clean_20260713/rehearsal/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v9_clean_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_v9_clean_20260713/model_gate`：source=baselines/e3_ablation/e3_v9_clean_20260713/model_gate/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v9_clean_20260713/preflight`：source=baselines/e3_ablation/e3_v9_clean_20260713/preflight/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_v9_clean_20260713/rehearsal`：source=baselines/e3_ablation/e3_v9_clean_20260713/rehearsal/raw_runs.csv; keys=['battery_kwh', 'between_trip_gap_hours', 'budget', 'carbon_quota_kg', 'depot_charge_power_kw', 'fairness_enabled', 'fee', 'fee_override_verified', 'instance', 'layer', 'machine', 'min_profit_ratio', 'scenario_role', 'size', 'strict_contract_id']; seed=['seed']; values=['total_cost', 'route_structure_signature', 'search_route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_warmstart_controlled_20260713`：该包无逐单元原始记录CSV

- `baselines/e3_ablation/e3_warmstart_controlled_20260713/gate`：source=baselines/e3_ablation/e3_warmstart_controlled_20260713/gate/raw_runs.csv; keys=['arm', 'battery_kwh', 'budget', 'depot_charge_power_kw', 'fairness_enabled', 'fairness_theta', 'fee', 'instance', 'min_profit_ratio', 'size']; seed=['seed']; values=['total_cost', 'route_structure_signature']; seed_counts={}

- `baselines/e3_ablation/e3_warmstart_controlled_20260713/preflight`：source=baselines/e3_ablation/e3_warmstart_controlled_20260713/preflight/raw_runs.csv; keys=['arm', 'battery_kwh', 'budget', 'depot_charge_power_kw', 'fairness_enabled', 'fairness_theta', 'fee', 'instance', 'min_profit_ratio', 'size']; seed=['seed']; values=['total_cost', 'route_structure_signature']; seed_counts={}

- `baselines/e4_e5/china_2025_formal_month_selection_20260718`：source=baselines/e4_e5/china_2025_formal_month_selection_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'observed', 'expected', 'status']

- `baselines/e4_e5/china_2026_july_explanatory_cases_20260718`：source=baselines/e4_e5/china_2026_july_explanatory_cases_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'observed', 'expected', 'status']

- `baselines/e4_e5/china_policy_price_gate_20260717`：该包无逐单元原始记录CSV

- `baselines/e4_e5/china_policy_price_gate_beijing_20260717`：source=baselines/e4_e5/china_policy_price_gate_beijing_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['region', 'access_date', 'raw_snapshot_count', 'official_first_party_source_count', 'tariff_source_status', 'diesel_source_status', 'charging_service_fee_status', 'cea_reuse_status', 'search_evaluations', 'solver_evaluations', 'source_gate_pass', 'decision']

- `baselines/e4_e5/china_policy_price_gate_beijing_20260717/v2_official_fee_deep_dive_20260717`：该包无逐单元原始记录CSV

- `baselines/e4_e5/china_policy_price_gate_chongqing_20260717`：source=baselines/e4_e5/china_policy_price_gate_chongqing_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['region', 'access_date', 'raw_snapshot_count', 'official_first_party_source_count', 'tariff_source_status', 'diesel_source_status', 'charging_service_fee_status', 'cea_reuse_status', 'search_evaluations', 'solver_evaluations', 'source_gate_pass', 'decision']

- `baselines/e4_e5/china_policy_price_gate_chongqing_20260717/v2_official_fee_deep_dive_20260717`：该包无逐单元原始记录CSV

- `baselines/e4_e5/china_policy_price_gate_guangdong_20260717`：source=baselines/e4_e5/china_policy_price_gate_guangdong_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['region', 'access_date', 'raw_snapshot_count', 'official_first_party_source_count', 'tariff_source_status', 'diesel_source_status', 'charging_service_fee_status', 'cea_reuse_status', 'search_evaluations', 'solver_evaluations', 'source_gate_pass', 'decision']

- `baselines/e4_e5/china_policy_price_gate_guangdong_20260717/v2_official_fee_deep_dive_20260717`：该包无逐单元原始记录CSV

- `baselines/e4_e5/china_region_price_source_gate_20260717`：source=baselines/e4_e5/china_region_price_source_gate_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['source_id', 'region_scope', 'source_type', 'publisher', 'title', 'source_date', 'price_effective_date', 'raw_file', 'raw_sha256', 'bytes', 'direct_url', 'fetched_at_utc', 'license_or_use_restriction', 'extraction', 'fetch_status']

- `baselines/e4_e5/china_tvci_2026_interpolated_july_panel_20260718`：source=baselines/e4_e5/china_tvci_2026_interpolated_july_panel_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'observed', 'expected', 'status']

- `baselines/e4_e5/china_tvci_representative_days_jjj_prd_cy_20260718`：source=baselines/e4_e5/china_tvci_representative_days_jjj_prd_cy_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['run_id', 'check', 'scope', 'observed', 'expected', 'search_evaluations', 'status']

- `baselines/e4_e5/china_tvci_source_gate_20260717`：source=baselines/e4_e5/china_tvci_source_gate_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['year', 'expected_hours', 'observed_hours', 'column_count', 'column_sequence_match', 'invalid_time_count', 'null_count', 'non_numeric_count', 'negative_count', 'nonfinite_count', 'above_2_tCO2_per_MWh_count', 'search_evaluations', 'source_gate_pass']

- `baselines/e4_e5/china_tvci_source_gate_20260717_v2`：source=baselines/e4_e5/china_tvci_source_gate_20260717_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['year', 'expected_hours', 'observed_hours', 'column_count', 'column_sequence_match', 'invalid_time_count', 'null_count', 'non_numeric_count', 'negative_count', 'nonfinite_count', 'above_2_tCO2_per_MWh_count', 'search_evaluations', 'source_gate_pass']

- `baselines/e4_e5/e4_forecast_timing_formal_20260713`：source=baselines/e4_e5/e4_forecast_timing_formal_20260713/raw_runs.csv; keys=['instance', 'arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e4_e5/e4_four_cell_probe_20260713`：source=baselines/e4_e5/e4_four_cell_probe_20260713/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'timing_rule', 'route_fingerprint', 'service_fingerprint', 'energy_ledger_fingerprint', 'timing_fingerprint', 'source_replay_max_difference', 'hard_violation_count', 'hard_violation_types', 'first_trip_wrong_day_offset', 'charge_outside_legal_window', 'same_vehicle_charge_trip_overlaps', 'same_vehicle_charge_charge_overlaps', 'total_cost', 'total_operational_emissions_kg', 'direct_fuel_emissions_kg', 'charging_emissions_kg', 'total_charging_kwh', 'pre_day_charging_kwh', 'between_trip_charging_kwh', 'pre_day_charging_emissions_kg', 'between_trip_charging_emissions_kg', 'eligible_pre_day_kwh', 'eligible_between_trip_kwh', 'slot_energy_closure_error']

- `baselines/e4_e5/e4_multiday_forecast_probe_20260713`：source=baselines/e4_e5/e4_multiday_forecast_probe_20260713/raw_runs.csv; keys=['arm']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e4_e5/nonlinear_charging_robustness_replay_20260717`：source=baselines/e4_e5/nonlinear_charging_robustness_replay_20260717/raw_runs.csv; keys=['instance', 'arm', 'curve', 'curve_role', 'above_constant_power_end_pct']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e4_e5/nonlinear_multitrip_formula_gate_20260717`：source=baselines/e4_e5/nonlinear_multitrip_formula_gate_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'case', 'expected', 'actual', 'absolute_error', 'pass']

- `baselines/e4_e5/shenzhen_2025_02_tariff_closure_20260723`：source=baselines/e4_e5/shenzhen_2025_02_tariff_closure_20260723/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['evidence_id', 'evidence_type', 'source_path', 'source_sha256', 'claim', 'observed', 'status']

- `baselines/e6_fairness/e6_participation_audit_20260714`：source=baselines/e6_fairness/e6_participation_audit_20260714/raw_runs.csv; keys=['instance', 'participation_premium_vs_unrestricted_pct']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e6_fairness/e6_participation_formal_20260714`：source=baselines/e6_fairness/e6_participation_formal_20260714/raw_runs.csv; keys=['arm', 'between_trip_gap_hours', 'budget', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={2: 2, 3: 5}

- `baselines/e6_fairness/e6_participation_formal_20260714/superseded/461f05ee25ed`：source=baselines/e6_fairness/e6_participation_formal_20260714/superseded/461f05ee25ed/raw_runs.csv; keys=['arm', 'between_trip_gap_hours', 'budget', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e6_fairness/e6_participation_formal_20260714/superseded/9b6219b381aa`：source=baselines/e6_fairness/e6_participation_formal_20260714/superseded/9b6219b381aa/raw_runs.csv; keys=['arm', 'between_trip_gap_hours', 'budget', 'instance']; seed=['seed']; values=['total_cost']; seed_counts={}

- `baselines/e6_fairness/e6_profit_guarantee_frontier_20260715`：source=baselines/e6_fairness/e6_profit_guarantee_frontier_20260715/raw_runs.csv; keys=['alpha', 'alpha_label', 'between_trip_gap_hours', 'budget', 'effective_theta', 'fairness_enabled', 'formula_theta', 'instance', 'source_alpha']; seed=['seed']; values=['total_cost']; seed_counts={2: 6, 3: 2}

- `baselines/e7_dynamic/e7_certificate_clock_p0_20260714`：source=baselines/e7_dynamic/e7_certificate_clock_p0_20260714/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check_id', 'category', 'subject_id', 'boundary', 'event_second', 'epsilon_seconds', 'expected', 'observed', 'passed', 'search_evaluations', 'detail']

- `baselines/e7_dynamic/e7_cross_depot_opportunity_probe_20260715`：source=baselines/e7_dynamic/e7_cross_depot_opportunity_probe_20260715/raw_runs.csv; keys=['stage']; seed=['stream_seed']; values=['best_cross_future_cost', 'reference_future_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_cross_depot_opportunity_probe_v2_20260715`：source=baselines/e7_dynamic/e7_cross_depot_opportunity_probe_v2_20260715/raw_runs.csv; keys=['stage']; seed=['stream_seed']; values=['best_cross_future_cost', 'reference_future_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714`：source=baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['status', 'search_evaluations', 'failure']

- `baselines/e7_dynamic/e7_dynamic_emission_intensity_formal_20260714`：source=baselines/e7_dynamic/e7_dynamic_emission_intensity_formal_20260714/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=['total_cost']; seed_counts={5: 2}

- `baselines/e7_dynamic/e7_ex_post_participation_formal_20260714`：source=baselines/e7_dynamic/e7_ex_post_participation_formal_20260714/raw_runs.csv; keys=[]; seed=['stream_seed']; values=['cooperative_cost', 'independent_cost']; seed_counts={5: 1}

- `baselines/e7_dynamic/e7_formal_shared_start_value_audit_20260714`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714`：source=baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=['full_day_total_cost']; seed_counts={5: 2}

- `baselines/e7_dynamic/e7_full_mechanism_gate_v6_20260714`：source=baselines/e7_dynamic/e7_full_mechanism_gate_v6_20260714/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_full_mechanism_gate_v6_20260715`：source=baselines/e7_dynamic/e7_full_mechanism_gate_v6_20260715/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_full_mechanism_probe_20260714`：source=baselines/e7_dynamic/e7_full_mechanism_probe_20260714/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['stream_seed']; values=['future_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_full_mechanism_probe_v2_20260714`：source=baselines/e7_dynamic/e7_full_mechanism_probe_v2_20260714/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['stream_seed']; values=['future_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_4_v2_20260715`：source=baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_4_v2_20260715/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_50_v1_20260714`：source=baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_50_v1_20260714/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_v1_20260714`：source=baselines/e7_dynamic/e7_full_mechanism_two_condition_gate_v1_20260714/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715`：source=baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['network', 'condition', 'stream', 'arm', 'operating_day', 'route_sha256', 'energy_sha256', 'charging_kwh', 'completed_demand', 'direct_emissions_kg', 'immediate_actual_charging_emissions_kg', 'aware_actual_charging_emissions_kg', 'actual_charging_saving_kg', 'charging_reduction_pct', 'total_operational_reduction_pct', 'timing_shifted_action_count', 'route_hash_preserved', 'energy_hash_preserved']

- `baselines/e7_dynamic/e7_multinetwork_event_streams_20260715`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/raw_runs.csv; keys=['donor_instance_id', 'modifiable_in_both_fixed_seed1_plans']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N114`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N114/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N221`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N221/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N322`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_20260715/N322/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/raw_runs.csv; keys=['donor_instance_id', 'modifiable_in_both_fixed_seed1_plans']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N114`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N114/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N221`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N221/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N322`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715/N322/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/raw_runs.csv; keys=['donor_instance_id', 'modifiable_in_both_fixed_seed1_plans']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N114`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N114/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N221`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N221/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N322`：source=baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/N322/stream_seed1.events.csv; keys=['donor_instance_id']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_formal_20260715`：source=baselines/e7_dynamic/e7_multinetwork_formal_20260715/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={5: 12}

- `baselines/e7_dynamic/e7_multinetwork_formal_timing_clean_rerun_20260717`：source=baselines/e7_dynamic/e7_multinetwork_formal_timing_clean_rerun_20260717/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['task_id', 'stage', 'lineage', 'mode', 'historical_elapsed_seconds', 'rerun_elapsed_seconds', 'delta_seconds', 'relative_delta', 'child_shift_deviation_from_median_seconds', 'accepted', 'search_evaluations_reused']

- `baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715`：source=baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['network', 'condition', 'stream', 'all_four_arms_executable', 'full_minus_no_cooperation_net_profit', 'full_minus_no_cooperation_revenue', 'full_minus_no_cooperation_cost', 'full_minus_no_cooperation_completed_customer_count', 'full_minus_no_cooperation_completed_demand', 'full_minus_no_participation_net_profit', 'full_minus_no_participation_revenue', 'full_minus_no_participation_system_cost', 'full_minus_no_participation_completed_customer_count', 'full_minus_no_participation_completed_demand', 'full_minus_simple_insertion_net_profit', 'full_minus_simple_insertion_revenue', 'full_minus_simple_insertion_cost', 'full_minus_simple_insertion_completed_customer_count', 'full_minus_simple_insertion_completed_demand', 'simple_insertion_minus_full_actual_total_emissions_kg', 'full_day_participation_floor_met']

- `baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715_pre_hygiene_patch_20260718`：source=baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715_pre_hygiene_patch_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['network', 'condition', 'stream', 'all_four_arms_executable', 'full_minus_no_cooperation_net_profit', 'full_minus_no_cooperation_revenue', 'full_minus_no_cooperation_cost', 'full_minus_no_cooperation_completed_customer_count', 'full_minus_no_cooperation_completed_demand', 'full_minus_no_participation_net_profit', 'full_minus_no_participation_revenue', 'full_minus_no_participation_system_cost', 'full_minus_no_participation_completed_customer_count', 'full_minus_no_participation_completed_demand', 'full_minus_simple_insertion_net_profit', 'full_minus_simple_insertion_revenue', 'full_minus_simple_insertion_cost', 'full_minus_simple_insertion_completed_customer_count', 'full_minus_simple_insertion_completed_demand', 'simple_insertion_minus_full_actual_total_emissions_kg', 'full_day_participation_floor_met']

- `baselines/e7_dynamic/e7_multinetwork_preflight_v3_halt_20260715`：source=baselines/e7_dynamic/e7_multinetwork_preflight_v3_halt_20260715/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_multinetwork_preflight_v4_20260715`：source=baselines/e7_dynamic/e7_multinetwork_preflight_v4_20260715/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={5: 12}

- `baselines/e7_dynamic/e7_multinetwork_preflight_v5_20260715`：source=baselines/e7_dynamic/e7_multinetwork_preflight_v5_20260715/raw_runs.csv; keys=['arm', 'charging_strategy', 'stage']; seed=['main_search_seed', 'shadow_search_seed', 'stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={5: 12}

- `baselines/e7_dynamic/e7_parent_child_recovery_gate_20260716`：source=baselines/e7_dynamic/e7_parent_child_recovery_gate_20260716/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'authorized_lineage', 'condition', 'network', 'stream', 'task_id']

- `baselines/e7_dynamic/e7_pre_recovery_gate_20260716`：source=baselines/e7_dynamic/e7_pre_recovery_gate_20260716/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['arm', 'checkpoint_status', 'condition', 'error', 'evaluations', 'execution_status', 'network', 'stages', 'stream', 'task_id']

- `baselines/e7_dynamic/e7_replay_invariants_audit_20260715`：source=baselines/e7_dynamic/e7_replay_invariants_audit_20260715/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['network', 'condition', 'stream', 'arm', 'operating_day', 'window_violation_count', 'immediate_station_capacity_violation_count', 'aware_station_capacity_violation_count', 'route_hash_preserved', 'energy_hash_preserved', 'immediate_emissions_residual_kg', 'aware_emissions_residual_kg', 'emissions_recalculation_pass']

- `baselines/e7_dynamic/e7_replay_invariants_audit_20260715_hash_contaminated_20260718`：source=baselines/e7_dynamic/e7_replay_invariants_audit_20260715_hash_contaminated_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['network', 'condition', 'stream', 'arm', 'operating_day', 'window_violation_count', 'immediate_station_capacity_violation_count', 'aware_station_capacity_violation_count', 'route_hash_preserved', 'energy_hash_preserved', 'immediate_emissions_residual_kg', 'aware_emissions_residual_kg', 'emissions_recalculation_pass']

- `baselines/e7_dynamic/e7_responsibility_scenario_design_20260714`：source=baselines/e7_dynamic/e7_responsibility_scenario_design_20260714/raw_runs.csv; keys=['customer_count']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/event_streams`：source=baselines/e7_dynamic/e7_v2_20260714/event_streams/raw_runs.csv; keys=['donor_instance_id', 'modifiable_in_both_fixed_seed1_plans']; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/formal`：source=baselines/e7_dynamic/e7_v2_20260714/formal/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={2: 32, 3: 4, 4: 41, 5: 33}

- `baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware`：source=baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={5: 14}

- `baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware_audit`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix`：source=baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed', 'stage_search_seed']; values=['future_cost', 'running_total_cost']; seed_counts={5: 14}

- `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_repair_known_stops`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stage1_8`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400_asset_aware`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_400_v2`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/batched_stream1_800`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/failed_stage_budget_800_v2`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/failed_stage_service_time_v3_400`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/hooks/formal_batched_400_asset_aware`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/formal_shared_start_400_route_fix_adaptive`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/formal_shared_start_400_route_fix_adaptive_v3`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_50_route_fix`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_8`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stage1_8_v2`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stream1_400`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/monitor_runs/shared_start_stream1_400_route_fix`：该包无逐单元原始记录CSV

- `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_repair_known_stops`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/batched_repair_known_stops/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stage1_8`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stage1_8/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_asset_aware`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_asset_aware/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_v2`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_v2/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_800`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_800/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_budget_800`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_budget_800/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_service_time_v3_400`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_service_time_v3_400/raw_runs.csv; keys=['arm']; seed=['stream_seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v2`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v2/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v3`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/full_stream1_400_v3/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_draft`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_draft/raw_runs.csv; keys=[]; seed=['seed']; values=[]; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_probe`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_probe/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['evaluation', 'destroy_operator', 'repair_operator', 'changed', 'dynamic_feasible', 'accepted', 'candidate_future_cost', 'current_future_cost', 'best_future_cost']

- `baselines/e7_dynamic/e7_v2_20260714/preflight/paired_ten_stage`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/paired_ten_stage/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/paired_two_stage`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/paired_two_stage/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_50_route_fix`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_50_route_fix/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed', 'stage_search_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_8`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stage1_8/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed', 'stage_search_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed', 'stage_search_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400_route_fix`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/shared_start_stream1_400_route_fix/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed', 'stage_search_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/e7_v2_20260714/preflight/two_worker_smoke`：source=baselines/e7_dynamic/e7_v2_20260714/preflight/two_worker_smoke/raw_runs.csv; keys=['arm', 'stage']; seed=['stream_seed']; values=['future_cost', 'running_total_cost']; seed_counts={}

- `baselines/e7_dynamic/m1_dynamic_truth_gate_20260711`：source=baselines/e7_dynamic/m1_dynamic_truth_gate_20260711/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['all_zero_violation_and_cost_match', 'backend_label_present', 'check', 'command', 'independent_entry_reference_count', 'internal_comparison_still_valid', 'legacy_alns_reference_count', 'ok', 'output', 'passed', 'returncode', 'rows']

- `baselines/e7_dynamic/m1_dynamic_truth_gate_20260711/e2_replay_post_dynamic_port`：source=baselines/e7_dynamic/m1_dynamic_truth_gate_20260711/e2_replay_post_dynamic_port/e2_replay_rows.csv; keys=['algorithm', 'cross_site_cost_if_enabled', 'instance']; seed=['seed']; values=['replayed_free_cross_site_cost', 'reported_cost']; seed_counts={2: 21, 3: 10, 4: 6, 5: 4}

- `baselines/experiment_infrastructure/absolute_execution_harness_20260725/.absolute-execution-harness-v1.monitor`：该包无逐单元原始记录CSV

- `baselines/experiment_infrastructure/absolute_execution_harness_20260725/.absolute-execution-harness-v2.monitor`：该包无逐单元原始记录CSV

- `baselines/experiment_infrastructure/absolute_execution_harness_20260725/integration_gate_v2`：source=baselines/experiment_infrastructure/absolute_execution_harness_20260725/integration_gate_v2/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['worker_index', 'pid', 'module', 'module_file', 'cwd', 'project_root', 'python', 'real_instance_loaded']

- `baselines/formal_20260621_10001_lmain_10seed`：source=baselines/formal_20260621_10001_lmain_10seed/raw_runs.csv; keys=['algorithm', 'eval_budget', 'instance', 'max_runtime_seconds']; seed=['seed']; values=['best_cost']; seed_counts={10: 20}

- `baselines/model_verification/china81_nonlinear_core_nl0_20260720`：source=baselines/model_verification/china81_nonlinear_core_nl0_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'status', 'observed', 'expected', 'detail']

- `baselines/model_verification/china81_nonlinear_cost_check_nl2_20260720`：source=baselines/model_verification/china81_nonlinear_cost_check_nl2_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'status', 'observed', 'expected', 'detail']

- `baselines/model_verification/china81_nonlinear_dynamic_nl3a_20260720`：source=baselines/model_verification/china81_nonlinear_dynamic_nl3a_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'passed', 'value']

- `baselines/model_verification/china81_nonlinear_schedule_nl1_20260720`：source=baselines/model_verification/china81_nonlinear_schedule_nl1_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'status', 'observed', 'expected', 'detail']

- `baselines/model_verification/china81_vehicle_road_profiles_nl3b_20260720`：source=baselines/model_verification/china81_vehicle_road_profiles_nl3b_20260720/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['instance_id', 'region', 'customer_count', 'node_count', 'city_count', 'cities', 'time_profile_rows', 'num_cv_cap', 'num_ev_cap', 'fleet_cap_semantics', 'diesel_price_cny_per_l', 'diesel_price_source_id', 'cv_formula_abs_error', 'ev_formula_abs_error', 'charging_cost_abs_error', 'charging_emissions_abs_error', 'curve_parameter_sha256', 'curve_physical_sha256', 'battery_capacity_kwh', 'reference_power_kw', 'cv_ev_road_profiles_loaded', 'cv_ev_road_profiles_differ', 'dynamic_subset_profiles_preserved', 'dynamic_new_node_rejected', 'formal_search_allowed', 'passed']

- `baselines/model_verification/china_order_attribute_formula_validation_20260718`：source=baselines/model_verification/china_order_attribute_formula_validation_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['volume_m3', 'demand_kg', 'expected_demand_kg', 'service_minutes', 'expected_service_minutes', 'capacity_share_rounding_error', 'status']

- `baselines/model_verification/paper_math_audit_20260716`：source=baselines/model_verification/paper_math_audit_20260716/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'status', 'evidence', 'required_repair']

- `baselines/model_verification/two_layer_model_gate_20260716`：source=baselines/model_verification/two_layer_model_gate_20260716/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['check', 'status', 'detail']

- `baselines/statistics/mc002_compute_power_20260718`：source=baselines/statistics/mc002_compute_power_20260718/raw_runs.csv; 该CSV无seed或同义逐单元种子列；header=['record_type', 'metric', 'value', 'unit', 'assumption_or_boundary']

## 不可读包

无。
