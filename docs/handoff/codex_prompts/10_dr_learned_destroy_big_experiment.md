# Codex 提示词 10 — Pilot21 学习型破坏「大实验」（自动化·分阶段·带闸·先后串行）

> Claude 写定（2026-06-28）。Pilot20 Phase A 已证：当前 learned-destroy 在 25/50c 上对 operator-select 差 12-22% 且**训练曲线平**（reward 42.7→42.9，+0.48%）。读码诊断：(Q2 主因)学习机器太弱——reward `max(0,..)` 砍半信号、无解编码器、只 240 episode；(Q1 待证)小算例破坏杠杆可能本就低。**本提示词=一份自动化大实验：修学习机器 + 诊断杠杆 + 放量训练 + 正式对比，四阶段自动先后跑，阶段间带闸自停。** 冷启动、本文件自包含。

## 0. 开工前必读
`HANDOFF.md` 2026-06-27/28 段 + `docs/handoff/dr_alns_learned_destroy_plan.md` + `docs/handoff/codex_prompts/09_dr_learned_destroy_phaseA.md`(尤其 §4.1) + 现有 `solver/rl/dr_alns_ppo/` 的 `pilot20_learned_destroy_phaseA.py`/`learned_destroy.py`/`learned_destroy_policy.py`/`block_env.py`/`worker_client.py`+worker/`action_space.py` + `setp_solver/search/evaluation.py`(`penalized_obj`)。参考实现：Cao 代码 `工作-曹/CEVRP-NL/.../TEST/EVRP.py`+`net/dqn.py`、NLNS(学修复)、NeuOpt(学k-opt+GIRE)。

## 1. 目标与边界
**目标**：给 learned-destroy 一次**公平且强**的机会，并自动判定"修 / 换杠杆 / 转 future-work"。**绝对边界**：不改 `cost.py/check.py/search/evaluation.py/winner_operators.py` 语义；worker 全程 py313 `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`+NumPy `2.3.5`(漂移→`HALT_WORKER_INTEGRITY`)；runner 用 py312 cu124 venv；只 x86 同机相对%；commit `[x86/DR]`；只 force-add 小产物(报告+CSV+小模型)；**阶段间闸不过即自停**，不blind烧；每阶段周期 checkpoint、可中断恢复。

## 2. 自动化要求（先后串行）
单一入口脚本（如 `pilot21_learned_destroy_big.py`）**顺序执行 Stage0→1→2**，每阶段结束写阶段报告并**检查闸**：闸不过则写明 HALT 原因、跳过后续、产出最终报告并退出（非零码）。全程一条命令跑完，无需人工介入。

## 3. Stage 0 — 破坏杠杆诊断（先跑，便宜，回答 Q1）
对 25/50/100c 各 1-2 代表算例、固定预算、完整目标(penalized_obj)、worker py313，跑三臂同预算对比：
- `operator_select`(AlphaUCB destroy+repair，现成)
- `worst_removal_fixed`(固定按 `removal_saving` 拆最该拆的 + 同 repair 口径)
- `best_of_k_destroy`(每步随机生成 k 个破坏候选取最好；**消耗同一候选评估总预算**，作"破坏质量上界"探针)
量 `headroom_pct = (operator_select_best − best_of_k_best)/|operator_select_best|×100`（正=破坏有杠杆）。
**闸 G0**：若所有规模 `headroom ≤ +1%` 且 `worst_removal ≤ operator_select` → `HALT_NO_DESTROY_HEADROOM`：这些算例破坏杠杆太低（Pilot18/19 饱和同源），learned-destroy 是错杠杆 → 报告建议"换 DR 旋钮(学碳感知充电/出发时刻，有杠杆)或转 future-work"，**停**。否则记录"有杠杆的规模集合"，进 Stage 1（**优先在有杠杆的规模上训**；若仅大规模有杠杆，训练集纳入该规模代表算例）。

## 4. Stage 1 — 修学习机器 + 放量训练（仅 G0 过后；回答 Q2）
**必须先修这三处弱点，否则训练无意义**：
1. **奖励整形**：去掉 `learned_destroy_reward` 里的 `max(0,..)` 钳制，改**带符号 per-step delta**（best/current 改进为正、恶化为负，归一化），保留终局 final-gain 奖励与"跑满有效预算才计成功"的防早停套利；让策略对"坏破坏"也有梯度。
2. **加解编码器**：策略不再是裸 pointer——在 per-customer 特征上加一个**小自注意力/set-encoder**（如 1-2 层 multi-head attention 聚合全局上下文）再出每客户移除分 + value；让策略"看得见解结构"（对标 NeuOpt RDS / NLNS 注意力）。保持变长 padding+mask、PPO log-prob 可重算。
3. **放量训练**：train_episodes 提到能出学习曲线的量（起步 ≥1000，按 G0 杠杆规模与吞吐定；参考小算例 ~1000 ep/h），周期 checkpoint。课程 route→energy→carbon 照常，CUDA。
**闸 G1**：训练曲线必须有**明确学习信号**——reward 单调上行趋势 + entropy 合理下降不塌缩 + policy/value loss 收敛 + approx_kl 正常。若放量+修复后**连续 N 次 update 仍平**（如 reward 改善 <1% 跨前后半程）→ `HALT_LEARNER_FLAT` + 诊断（建议查 lr/entropy/credit/编码器容量），**停**（别再加 episode）。

## 5. Stage 2 — held-out 正式对比 + 判级（仅 G1 过后）
held-out 小/中算例、多 seeds、同预算同 worker py313，比 `learned_destroy` vs `operator_select` vs `random` vs `worst_removal_fixed`。
**判级（写死）**：
- `PASS_LEARNED_DESTROY`：held-out 平均相对 operator_select ≥ **+2%**、每规模 ≥0、稳超 random 与 worst_removal_fixed、learned 零违约、全行 worker py313/NumPy2.3.5 → **绿灯 Phase B**(FRVCP+碳感知+全规模+GA/PSO 擂台+精确解锚)。
- `WEAK_LEARNED_DESTROY`：0~+2% → 记录，给后续调参方向，不进 Phase B。
- `HALT_LEARNED_DESTROY`：≤0 或违约 → 学到了仍打不过（注意：G1 已确保学到了）→ **诚实负结果**：learned-destroy 在本问题不优于自适应 ALNS 破坏，转 future-work，论文主线押"富问题 vs 弱场 + 机制"。

## 6. 突发预案
- worker 漂/NumPy≠2.3.5/非有限成本/learned 违约 → `HALT_WORKER_INTEGRITY` 或 `HALT_INTEGRITY`，查根因不硬跑。
- PPO 指针+编码器不稳：先贪心(worst_removal)监督预热 N 步再 PPO；降 lr/调 entropy；仍崩→`HALT_POLICY_UNSTABLE` 诊断。
- 吞吐/内存超：降 actors/eval_budget/编码器宽度；不过夜 blind，靠 checkpoint。
- 连续 3 次猜测性修复失败→升级架构问题、停下写诊断。

## 7. 交付物
`pilot21_big_report.md/json`(三阶段结果+各闸判定+最终 verdict+"这对目标意味着什么"人话)、`pilot21_stage0_headroom.csv`、`pilot21_update_log.csv`(训练曲线)、`pilot21_phase_rows.csv`(Stage2 对比)、best checkpoint/小模型。最终回复人话说：Q1(杠杆有没有)、Q2(修后学没学到)、最终判级、下一步(Phase B / 换杠杆 / future-work)。

## 8. 资料顺序
先读 HANDOFF+蓝图+现有 learned-destroy 代码 + Cao/NLNS/NeuOpt 参考，再单点改、阶段跑、带闸自停。不得用"我猜"替代读码。

## 9. 自主过夜执行铁律（user 睡觉，goal 模式无人值守，必须周到）
- **全自动不等人**：一条入口命令跑完 Stage0→1→2；任何不确定**按本文件保守选项自决+记日志**，绝不停下等人。
- **先飞行前检查再开跑**（缺啥立刻 HALT，别跑几小时才发现）：py313 worker 存在且 NumPy=2.3.5、py312+torch+CUDA 可用、训练/held-out bundle 全存在、输出目录可写、磁盘充足。
- **崩溃可恢复**：周期 checkpoint（每 N updates + 每阶段末）；入口支持 `--resume` 从最新 checkpoint 续，**会话/机器中断后不从零重跑**。
- **资源安全（16GB 机，防 OOM 拖死）**：actors/eval_budget/编码器宽度按开跑前 ~10 分钟校准定，峰值内存留边际(≤~12-13GB)；**全局墙钟封顶（≤6h）**，到点停在最近 checkpoint 并出报告；GPU 只承担策略更新。
- **git 安全**：本地 `[x86/DR]` 提交可以；**禁止过夜自动 push/rebase/强推**（dr-x86 现 ahead4/behind1，留早上人工 reconcile）；只 force-add 小产物。
- **增量留痕**：每阶段/每次 update 即时写 `pilot21_progress.log` + 阶段报告，**即使中途 HALT/崩溃，早上也能看到跑到哪、为什么停**。
- **自决边界**：可自行校准 actors/budget/lr/选算例(在 G0 杠杆规模内)、可监督预热、可降配抗 OOM；但**不可改保护文件语义、不可绕 worker py313、不可放宽判级阈值、不可拿 smoke 当结论**。
- **三振出局**：同一阶段连续 3 次自修失败 → 升级架构问题、写诊断、停该阶段、出最终报告（别无限重试烧整夜）。
- **早上交付**：无论 PASS/WEAK/HALT/中断，都留一份 `pilot21_big_report.md`，人话写清：Q1 杠杆有没有、Q2 修后学没学到、判级、下一步，以及"跑到哪一阶段/为何停"。
