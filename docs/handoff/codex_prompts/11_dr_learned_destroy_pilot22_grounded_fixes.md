# Codex 提示词 11 — Pilot22 学习型破坏「文献依据修复」（自动化·分阶段·带闸·过夜）

> Claude 写定（2026-06-28）。Pilot21=`HALT_LEARNER_FLAT`，但读报告+查文献后判定：**HALT 大概率是判据误杀**（唯一失败项是"熵没降"，而 reward 在升+0.0046 斜率、loss/kl 健康），且我们的 reward/基线设计**没对齐已发表方法**。本提示词的修法**全部有出处**，不许再拍脑袋。Stage0 已证破坏有杠杆(25c 6.26%)，所以不放弃、是修学习器。冷启动、本文件自包含。

## 0. 开工前必读
`HANDOFF.md` 2026-06-27/28 段 + `docs/handoff/codex_prompts/10_*.md`(尤其 §9 自主过夜铁律，本文件全部沿用) + Pilot21 产物 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot21_learned_destroy_big/`(report/update_log/stage1_summary) + 现有 `learned_destroy.py`/`learned_destroy_policy.py`/`pilot21_*` 代码 + 参考 Cao `alns/ALNS.py`(reward_list)/NLNS/POMO。

## 1. 三条文献依据修法（必须照此改，附出处）
**修法1 — G1 收敛判据改对（删"熵必须降"）。** 依据：POMO(NeurIPS2020)核心是 *discourage premature convergence*——**熵不塌缩是健康的**；NCO 判收敛一律看**验证集 cost/gap，不看熵**。来源：POMO `proceedings.neurips.cc/paper/2020/file/f231f2107df69eab0a3862d50018a9b2-Paper.pdf`、RL4CO `arxiv.org/pdf/2306.17100`。
- **改法**：G1 改为"**周期在 held-out 上评 cost，验证改进达阈值或平台 + KL 稳定 + loss 有限**"；**移除 entropy_drop 判据**（熵仅作监控、不作闸）。

**修法2 — 上 POMO shared baseline（替代单轨迹 GAE 的高方差）。** 依据：POMO 同算例跑 N 轨迹、用**组内平均回报作基线** → 零均值低方差、训练稳、抗局部最优、抗过早收敛。来源：POMO 同上。
- **改法**：每个训练算例并行多 rollout，advantage 用**组内均值基线**（可并入现 PPO 的 advantage 归一化，或退化为 REINFORCE+shared baseline）；保留 value head 仅作辅助。

**修法3 — reward 换成验证过的设计（弃自创 120×scaling）。** 依据：DR-ALNS 选择型策略的验证 reward 是**离散结果分 5/3/1/0**（新best/接受改进/接受变差/拒绝）——Cao `alns/ALNS.py:34 reward_list=[5,3,1,0]`、Reijnen 同类；（连续增量+critic 是 NLNS 给学习型**修复**用的，我们学的是**破坏选择**，故首选 5/3/1/0）。
- **改法**：`learned_destroy_reward` 改为按候选结果归类给 **5/3/1/0**（沿用现成接受结果判定），保留"跑满有效预算才计成功"的防早停套利；**去掉 120×best_gain 自创式**。

## 2. 阶段执行（自动先后串行，带闸；§9 过夜铁律全用）

**Stage A — 现 ckpt 真实差距诊断（便宜、不训练、先跑）**：拿 Pilot21 的 ckpt（确定性 argmax）在 held-out 上 vs operator-select / random / worst_removal，**标注 `EXPLORATORY`、不算闸门证据**。算 learned vs operator-select 真实 gap%。
- **闸 GA（决定要不要大改重训）**：
  - 若现 ckpt 已把 Pilot20 的 ~−22% 明显缩小（如 ≤ −8%）→ 方向对，reward 代理可信 → 进 Stage B 全套修法重训。
  - 若仍 ≈ −20%（+7.3% reward 没转成差距缩小）→ 说明 **reward 代理在骗人**，修法3(reward 换 5/3/1/0)是首要根因 → 仍进 Stage B，但日志标注"reward 代理失真、以 5/3/1/0 为主修"。
  - （GA 不 HALT，只决定 Stage B 的侧重；两路都重训。）

**Stage B — 按三条修法改代码 + 重训 Stage1**：实现修法1/2/3；用修正后的 G1（held-out cost 判据）训练；课程 route→energy→carbon、CUDA、周期 checkpoint。**闸 G1(新)**：held-out cost 较初始改进达阈值(如 ≥+3%)且未塌缩 → 过；若放量后 held-out **无任何改进趋势** → `HALT_LEARNER_NO_VALIDATION_GAIN`+诊断（这次是真没学到，因为已按文献修了 reward/baseline/判据）。

**Stage C — 正式对比 + 判级**（仅 G1-new 过）：learned vs operator-select vs random vs worst_removal，held-out 多 seed 同预算同 worker py313。
- `PASS_LEARNED_DESTROY`：平均 ≥+2%、每规模≥0、稳超 random/worst_removal、零违约、worker py313/NumPy2.3.5 → 绿灯 Phase B。
- `WEAK`：0~+2%。`HALT_LEARNED_DESTROY`：≤0（已按文献修齐仍打不过 → 诚实负结果，转 future-work，论文押富问题 vs 弱场+机制）。

## 3. resume guard（user 明确要求）
入口脚本读 state：若 `final_status` 属 HALT 类（含 Pilot21 的 `HALT_LEARNER_FLAT`），**禁止 `--resume` 直接进后续 Stage**；只允许"按本提示词改了代码后的全新 Pilot22 run"或显式 `--force-exploratory`（仅跑 Stage A 标注 exploratory）。防止误绕过 HALT 当成闸门通过证据。

## 4. 绝对边界 + 过夜铁律（沿用 prompt 10 §9）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py`；worker 全程 py313+NumPy2.3.5（漂移 HALT_WORKER_INTEGRITY）；runner py312 cu124；只 x86 相对%；飞行前检查；周期 checkpoint+`--resume`(受 §3 guard 约束)；全局墙钟≤6h 到点停在 checkpoint；防 OOM(≤~12-13GB)；**禁过夜 push/rebase/强推**(dr-x86 留人工 reconcile)；只 force-add 小产物；增量写 `pilot22_progress.log`；同阶段连续 3 次自修失败→升级架构问题写诊断停。每个修法改动按"症状→文献出处→改哪→为什么只改这"记录。

## 5. 交付物
`pilot22_report.md/json`(Stage A 真实差距 + 三修法落地说明+出处 + G1-new 曲线 + Stage C 判级 + 人话"这对目标意味着什么")、`pilot22_stageA_exploratory.csv`、`pilot22_update_log.csv`(含 held-out 验证曲线)、`pilot22_phase_rows.csv`、best ckpt/小模型。最终人话报：现 ckpt 差距缩没缩、按文献修齐后学没学到、判级、下一步(Phase B/future-work)。

## 6. 资料顺序
先读 HANDOFF+Pilot21 产物+现 learned-destroy 代码 + Cao reward_list/POMO/NLNS，再按三修法单点改、阶段跑、带闸自停。不得用"我猜"替代查文献/读码。
