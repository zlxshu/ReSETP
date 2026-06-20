# 提示词① — DR 离线探针 + 课程预备（已跑，verdict = PROMISING）

> 先完整读仓库根 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md`。本任务只做离线分析，不跑 solver、不用 GPU、不训练。结果已落盘（probe verdict=PROMISING，r2_delta≈1.05, CI[0.957,1.157]；Probe B INCONCLUSIVE_SUPPORT）；本文件留作复现/参考。

```
任务：用现有 block traces 便宜地判定"DR 的 block 动作选择有没有可学的上下文信号"（决定值不值得上 GPU），不训练、不跑正式 100-01 对照。探针完成后，产出课程式重训的设计文档（只写不跑）。

铁律：
- 不改 cost.py / check.py / evaluation.py；offline runner 不调用正式 E1–E7。
- 不注水：数据不足以判就如实 INCONCLUSIVE，并据估计量推导出需要的最小行数（取代旧的拍脑袋 4000）。
- 环境一致：RL venv 或系统 Python 二选一并固定，报告里写明；结果 commit，绑 commit hash。

Phase 0 — audit（先报告，三问）：
(a) 现有 block traces 是哪个策略采的？有没有记录动作 propensity？（决定探针 B 能否做）
(b) 一"行"是什么决策粒度？block 状态特征向量有哪些、维度多大？（决定探针 A 可不可信）
(c) offline_bandit collect 是单进程还是可并行？（决定将来补数据的便宜路子）

Phase 1 — 探针 A（监督式上下文可学性，用现有 ~1625 行）：
- 拟合两个模型预测 block 收益：①上下文感知模型（用状态特征）②无上下文基线（仅 block 边际均值）。
- 小样本用 k-fold + 重复交叉验证（必须按 episode_index 分组防泄漏），比 held-out 预测力（R²/秩相关/AUC）的提升量。
- 判据：上下文模型显著优于边际均值 → DR 对 AlphaUCB 有 headroom = PROMISING；打平 → WEAK。

Phase 2 — 探针 B（仅当 Phase 0 确认有 propensity，random_block 子集）：
- IS / doubly-robust 估计"贪心策略 vs 采集策略"的价值差。无 propensity / 确定性策略则跳过并注明。

Verdict：PROMISING / WEAK / INCONCLUSIVE（INCONCLUSIVE 时给据估计量推导的最小行数）。

Phase 3 — 课程方案预备（产出 curriculum_training_plan.md，不执行训练）：
- 课程式约束分解（学 Daysalilar CB-DRL）：做在 RL 奖励层 block_env._reward、不动 cost/evaluation 真实目标：阶段 A 只优化路线数/距离 → B 加 EV 充电 → C 加碳+公平 → D 加动态；逐阶段激活罚项 + phase-specific 超参 + value/advantage clipping。
- 动作掩码（学 Narayanan）：async_block_policy 出 logits 时对无效/退化动作置 -inf（治 vehicle_type_swap 塌缩）。
- shared baseline（学 Wan）：train_async_block_ppo 用同 bundle 的 N 条 rollout 平均回报做优势基线。
- 映射到 env.py（19 维 obs、5 维动作）/ worker.py（系统 Python 跑算子）/ 训练脚本：列出改哪、怎么改、阶段切换条件与奖励口径。

交付：探针报告 md + curriculum_training_plan.md + 单元测试（合成数据上 verdict 翻转 PROMISING/WEAK 锁逻辑）+ commit。
```

## 实际产物（已跑）
- 代码 `solver/rl/dr_alns_ppo/offline_probe.py`（+ `solver/rl/tests/test_offline_probe.py`）
- 报告 `solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/probe/`：`offline_probe_report.md` / `audit.md` / `curriculum_training_plan.md`
- 测试 21 passed；commit d137b9b / 70b1df0
- 关键数据：block 动作 = 5 维 (destroy,repair,q,threshold,exploration)；obs = 19 维；数据 `…/offline_bandit/dataset/block_trace_rows.csv` ~1625 行；random_block propensity = ∏1/nvec。
