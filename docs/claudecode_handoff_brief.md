# Claude 到 Codex 接管说明

这份文档不是逐字日志，也不是全量堆栈。它只保留能让 Codex 继续接手的内容：已经确认的结论、当前冲突、未完成的门禁，以及对应的原始来源。

## 1. 时间线

### 2026-06-10：碳交易车队优化的实例生成对齐
- Claude 和 Codex 在 `models/src/setp_instance_lab/` 上做的是“碳强度时间对齐”，不是求解器/评估器。
- 已生成 `carbon_profile.csv`，UTC anchor 选在 `2025-11-19 08:00`，时间步长是 30 分钟，覆盖到 `15:30`。
- 这一步的意义是把实例生成器和碳数据对齐，为后面的论文/实验准备一致的数据入口。
- 相关来源：`[2026-06-10T16-33-00-ZAZH-10min-memory-summary.md](/Users/zhouleixishu/.codex/memories/extensions/chronicle/resources/2026-06-10T16-33-00-ZAZH-10min-memory-summary.md)`，`[2026-06-10T08-29-34-AmBL-rebuild_python_generator_goeke_migration_mobile_disk_resetp.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-10T08-29-34-AmBL-rebuild_python_generator_goeke_migration_mobile_disk_resetp.md)`。

### 2026-06-11：模型验证和论文参数表
- 验证重点是 `cost.py`、`prices.py`、`test_cost.py`，尤其是 CMEM、distance cost、EV electricity、charging indirect emissions。
- `paper_main.tex` 的 4.1 节开始进入参数表整理，目标是把模型参数、来源和单位讲清楚。
- 这一段已经把“模型/论文一致性校验”与“后续求解器实现”分开了，后者还没真正开始。
- 相关来源：`[2026-06-11T05-00-00-gqBq-10min-memory-summary.md](/Users/zhouleixishu/.codex/memories/extensions/chronicle/resources/2026-06-11T05-00-00-gqBq-10min-memory-summary.md)`，`[2026-06-11T05-08-29-7MvK-paper_main_4_1_parameter_table_supertabular_justified_notes.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-11T05-08-29-7MvK-paper_main_4_1_parameter_table_supertabular_justified_notes.md)`。

### 2026-06-12：正式运行门禁、E2/E7 污染控制、S2 准备
- 当时的主线是正式运行的门禁和回填污染控制，`formal_runner_manifest.json` 被当作真值来源。
- `E2` 已经有较完整的运行记录，但 `E7` 仍然有未消化的行为问题，不适合直接把 S2 当成“可放心长跑”。
- 这一阶段已经明确：S2 点火之前要先做隔离的 E7 probe，不要直接把长跑当成验收通过。
- 相关来源：`[2026-06-12T08-05-25-uRsX-w2_formal_run_takeoff_r0_e2_rerun_and_partial_halt.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-12T08-05-25-uRsX-w2_formal_run_takeoff_r0_e2_rerun_and_partial_halt.md)`，`[2026-06-12T02-29-55-APLW-resep_w1_candidate_adapter_collapse_halt.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-12T02-29-55-APLW-resep_w1_candidate_adapter_collapse_halt.md)`，`[2026-06-13T02-35-00-uwNZ-10min-memory-summary.md](/Users/zhouleixishu/.codex/memories/extensions/chronicle/resources/2026-06-13T02-35-00-uwNZ-10min-memory-summary.md)`。

### 2026-06-13：E7 滚动重优化、站点容量、S2 门禁
- `E7` 的关键问题不是“有没有单车充电站”，而是 `C_s=1` 这一容量语义是否被正确执行，以及滚动重优化时有没有把同一时间窗里的占位搞冲突。
- 这一天的结论是：先做单 seed 的隔离 E7 probe，再谈 S2 继续跑，不要因为一个看起来“能跑”的命令就把门禁放掉。
- `formal_runner` 的长跑判断也被校正为看进程状态、manifest、以及有没有真正的 E7 JSON，而不是只看 stdout 是否安静。
- 相关来源：`[2026-06-13T06-58-33-wBFQ-e7_station_capacity_cs1_verification.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-13T06-58-33-wBFQ-e7_station_capacity_cs1_verification.md)`，`[2026-06-13T13-18-54-ksZn-resep_e34_realtime_monitoring_and_rescue_ready_rerun.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-13T13-18-54-ksZn-resep_e34_realtime_monitoring_and_rescue_ready_rerun.md)`，`[2026-06-13T01-53-18-1W6l-parallel_r2_dryrun_launcher_and_gate_refusal.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-13T01-53-18-1W6l-parallel_r2_dryrun_launcher_and_gate_refusal.md)`。

### 2026-06-14：DR-ALNS 真伪核验、PPO 可行性、parallel R2
- 这一天最重要的结论是：ReSETP 里的 `_run_dr_alns_path` 不是 upstream Reijnen 意义上的真 DR-ALNS。
- 原因很直接：当前路径只有 weighted destroy selection、`weights[destroy] += 0.2`、regret reinsertion 这一类反应式 ALNS 逻辑，没有 `PPO.load`、没有 `model.predict`、没有训练循环、也没有 RL 环境控制。
- upstream `RobbertReijnen/DR-ALNS` 的核心是 DRL agent / PPO 控制 destroy/repair、破坏强度、接受温度；所以“名字叫 DR-ALNS”不等于“机制上就是 DR-ALNS”。
- 这天还把“真 PPO 驱动的 DR-ALNS 的可行性”单独拆成报告，强调如果不接 RL，论文和表格不能把它当作真正的 Reijnen 方法来写。
- 相关来源：`[2026-06-14T12-06-49-aqDw-resep_dr_alns_truthfulness_and_alns_wouda_strong_validation.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-14T12-06-49-aqDw-resep_dr_alns_truthfulness_and_alns_wouda_strong_validation.md)`，`[2026-06-14T12-25-21-iaqh-resep_true_dr_alns_ppo_feasibility_report.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-14T12-25-21-iaqh-resep_true_dr_alns_ppo_feasibility_report.md)`，`[2026-06-14T17-32-13-X4H2-dr_alns_ppo_isolated_lane_ppo_smoke_heldout_halt_random.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-14T17-32-13-X4H2-dr_alns_ppo_isolated_lane_ppo_smoke_heldout_halt_random.md)`。

### 2026-06-15：PPO 进展审计、基线不一致、held-out 解释
- 这一段把“训练真的在跑”与“结果是否可信”分开了。
- `HALT_RANDOM` 的历史、`official_winner_kernel` 的对齐、以及 `alpha_ucb_env` 和当前环境的一致性，都被当作独立门禁处理。
- 早期 smoke / held-out 结果里出现 `random_action` 或 PPO 不占优，不应该直接解读成“策略失败”，因为那时还混有中间态、环境差异和 manifest 污染。
- 相关来源：`[2026-06-15T07-32-43-lO0C-dr_alns_ppo_progress_audit_and_human_summary.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-15T07-32-43-lO0C-dr_alns_ppo_progress_audit_and_human_summary.md)`，`[2026-06-15T15-42-16-a9Wj-dr_alns_ppo_v2_wiring_halt_baseline_mismatch.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-15T15-42-16-a9Wj-dr_alns_ppo_v2_wiring_halt_baseline_mismatch.md)`。

### 2026-06-16 到 2026-06-17：非确定性、worker Python、CPU/GPU 真值
- 系统 worker 修复后，许多“看起来像算法失败”的现象被重新解释成环境/解释器差异。
- 通过 device check 重新确认：当前 RL 运行实际上落在 CPU 侧，不要凭 worker 数或主机硬件想当然地判断 GPU 在参与。
- 这意味着后续如果继续做 PPO 独立线，必须把“解释器、依赖、device、manifest”当成一组一起验证。
- 相关来源：`[2026-06-16T08-53-00-EeHj-10min-memory-summary.md](/Users/zhouleixishu/.codex/memories/extensions/chronicle/resources/2026-06-16T08-53-00-EeHj-10min-memory-summary.md)`，`[2026-06-16T14-20-00-Ayer-10min-memory-summary.md](/Users/zhouleixishu/.codex/memories/extensions/chronicle/resources/2026-06-16T14-20-00-Ayer-10min-memory-summary.md)`，`[2026-06-17T08-43-18-FsMi-resep_dr_alns_ppo_cpu_vs_gpu_device_check.md](/Users/zhouleixishu/.codex/memories/rollout_summaries/2026-06-17T08-43-18-FsMi-resep_dr_alns_ppo_cpu_vs_gpu_device_check.md)`。

## 2. 现在应该把这几件事当成“已定”

- `DR-ALNS` 这个名字在当前 ReSETP 里是有风险的，因为实现和 upstream Reijnen 方法不是一回事。
- `E7` 不是简单的“能不能跑”，而是容量语义 `C_s=1` 和滚动重优化是否产生冲突。
- `S2` 不能直接开长跑，必须先过隔离 E7 probe。
- `cost.py`、`prices.py`、`paper_main.tex` 相关的模型/论文一致性已经比前面稳定得多，当前更像是“实验门禁和运行真值”问题，不是基础公式没定。
- `PPO` 这条线和正式论文比较线要分开；它已经是一个独立 lane，不该和正式 runner 混成同一条叙述。

## 3. 现在仍然冲突或未完成的点

- `candidates.py` 里的 `_run_dr_alns_path` 仍然只是薄适配器，若论文/表格继续写成真 DR-ALNS，会误导读者。
- E7 rolling reoptimization bug 还没有被完全定位到是“容量冲突、时间窗冲突、还是调度分配冲突”。
- 早期 PPO smoke 里出现的 `random_action` 优势，不应该被当成最终结论，必须先排除中间态、manifest 污染和解释器差异。
- `actual_evals=15156/16000` 这类 under-budget 行不能和真正完成的 `16000/16000` 行混成同一种比较。
- `verify_*` / `demo_carbon` 这类样例污染需要继续从正式比较里隔离出去。

## 4. Codex 接手时的优先顺序

- 先把 `DR-ALNS` 的命名与机制对齐：要么改名成薄适配器，要么真的接 PPO / RL 环境。
- 再回到 E7 rolling reoptimization：按单 seed、单 stage、单 probe 去找冲突源。
- 然后再决定 S2 是否可以继续长跑。
- 如果要继续论文写作，就把“模型验证已完成”和“实验门禁未完成”分开写，不要混在一起。

## 5. 关键代码锚点

- `[solver/src/setp_solver/search/candidates.py](/Volumes/移动硬盘（512G）/ReSETP/solver/src/setp_solver/search/candidates.py)`：`_run_dr_alns_path` 的真实执行路径。
- `[solver/src/setp_solver/check.py](/Volumes/移动硬盘（512G）/ReSETP/solver/src/setp_solver/check.py)`：E7 / station capacity / slot 检查。
- `[docs/paper_submission_final/paper_main.tex](/Volumes/移动硬盘（512G）/ReSETP/docs/paper_submission_final/paper_main.tex)`：论文正文与参数表。
- `[Reference Algorithm/DR-ALNS@RobbertReijnen/](/Volumes/移动硬盘（512G）/ReSETP/Reference%20Algorithm/DR-ALNS@RobbertReijnen)`：upstream DRL 版本的对照源。
- `[solver/rl/](/Volumes/移动硬盘（512G）/ReSETP/solver/rl)`：隔离的 PPO 独立线，不要和正式 runner 混写。

## 6. 这份接管说明的真正目的

- 让后续 Codex 能直接接手“判断”和“执行”，而不是先花时间读一堆重复 UI 噪声。
- 以后再看这些记录，优先看“已经定了什么”和“还卡在哪里”，不要再看逐条界面话术。
