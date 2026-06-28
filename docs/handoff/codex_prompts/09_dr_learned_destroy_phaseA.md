# Codex 提示词 09 — DR 学习型破坏 阶段A（小算力验核心假设，不全训）

> Claude 写定（2026-06-28），基于彻底文献+源码精读。**阶段A 唯一目的：用小算力证明「DR 学习型破坏(learned destroy) 真的比 DR 现在的"选算子"强」**。证了再进阶段B(FRVCP+碳感知+GLOP分解+全规模+GA/PSO擂台)。冷启动、读不了论文，本文件自包含。**先证据、后单点改、再短测**；连续3次猜测性修复失败→升级架构问题、停下写诊断。

## 0. 开工前必读（不读完不许动手）
- `HANDOFF.md` 全文 + 变更日志 2026-06-27/28 段（决定性结论、为何拉垮、策略）。
- 方案蓝图 `docs/handoff/dr_alns_learned_destroy_plan.md`（本提示词是其"阶段A"）。
- 代码：`solver/rl/dr_alns_ppo/block_env.py`(动作/obs/reward/掩码)、`worker_client.py`+worker 子进程(block_step 返回什么、怎么加逐客户特征与新算子)、`async_block_policy.py`(策略网，怎么加指针头)、`action_space.py`(`decode_block_action`)、`solver/src/setp_solver/search/evaluation.py`(`penalized_obj` BIG_M=GIRE 基础)、`winner_operators.py`(现成 destroy/repair)。
- 参考实现(取经"学习型破坏"接口)：`Reference Algorithm/CodeforADeepReinforcementLearning...曹/`(Cao DRL-ALNS：`net/dqn.py`、`TEST/EVRP.py` 算子)；网络 NLNS(ahottung/NLNS=神经修复)、NeuOpt(yining043/NeuOpt=学k-opt移动+GIRE 可行/不可行探索)。

## 1. 背景与目标（别跑偏）
- **DR 为何拉垮**：现 DR 动作=「在固定 destroy 算子里选下标」(`BLOCK_DESTROY_IDS`)，由算子自己决定拆哪些客户 → 上限≈调好的 ALNS（三方+Cao 源码断言实锤）。
- **升级**：把"选算子"换成"**策略对每个客户打移除分(pointer/attention)、自己学该拆谁**"——这是 learned 真能超手搓 ALNS 的唯一已验证途径(NLNS/NeuOpt)。
- **阶段A 目标**：实现该接口，在**小算例(25/50c)**上做**内部对比 learned-destroy vs operator-select**（同 evaluate/check/预算/修复），证明 learned-destroy 在富问题上**真有增量**。**不做 GA/PSO 擂台、不做精确解、不上全规模、不烧夜训**——那些是阶段B。

## 2. 绝对边界（违反即作废）
1. **小算力**：只用 25/50c 小算例；训练步数/时长设小上限(如 ≤1-2h、可中断 checkpoint)；**禁止全规模/过夜训**。
2. 不改 `cost.py`/`check.py`/`search/evaluation.py`/`winner_operators.py` 语义；只新增 DR lane(`solver/rl/`)代码。
3. worker/评测成本必经 py313 `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`、NumPy 2.3.5；PPO 用 cu124 py312 venv。
4. 只报 x86 同机相对%；先证据后单点改再短测；commit `[x86/DR]`；只 force-add 小产物(报告+CSV+小模型)。

## 3. 精确执行规范

### 3.1 worker 侧（新增，不改保护文件）
- **逐客户特征**：block_step 响应新增 `per_customer_features`（N×F，N=客户数）。每客户 F 维特征(富问题弹药)：归一化坐标x/y、demand、时间窗早/晚/宽度、所属车场 one-hot 或 id、是否 EV 服务(0/1)、距最近充电站、所在碳时隙强度 γ_t(由其当前服务时刻查 carbon_profile)、所属车场当前 profit(公平信号)、当前路线内前后弧成本和(移除节省)、是否在长弧上。**全部只读派生，不改 cost/check。**
- **新 destroy 算子 `remove_given_customers(ids)`**：按策略给定的客户 id 集合精确移除→交现成强 repair(regret2/3 + 2-opt，保持与 operator-select 基线**同一修复**以隔离变量)→充电修复保持现状(RH，FRVCP 留阶段B)。

### 3.2 policy 侧（`async_block_policy.py` 加指针头）
- 新增对**变长客户集**的 attention/pointer 头：吃 `per_customer_features` → 每客户输出移除分 → **采样 q 个客户(无放回，q 由现 q_ratio 控制或固定)** 作为 destroy 集合；log-prob=所选 q 个 categorical log-prob 之和(PPO 可训)。
- 新增 env `control_mode="learned_destroy"`：动作=客户子集(经上面采样)，其余旋钮(repair/q/threshold)沿用现有；obs 增 per-customer 矩阵(注意变长 N，按规模分组或 padding+mask)。

### 3.3 GIRE 约束处理（白捡，最小改动）
- learned-destroy 产生的候选**用现成 `penalized_obj`(BIG_M 违约罚)评分**，允许暂时不可行(电量/TW 超)被探索，不对 learned-destroy 加硬掩码(保留明显非法的轻剪枝)。这就是 NeuOpt 的 GIRE，我们 evaluation.py 天然支持。

### 3.4 训练 + 对比
- 训练：复用 `train_async_block_ppo`(PPO+异步+课程 route→energy→carbon+entropy 防塌缩)，**小设置**(25/50c bundles、小步数、6 actors、CUDA)。reward 沿用 Δbest+终局 gain，但**确保"持续产出有效候选"被奖励、早停不套利**(防 Pilot17 早停套利重演)。
- **核心对比(内部、同口径)**：同小算例、同预算、同修复、同 evaluate/check、同 seeds，比 **learned-destroy DR**  vs  **operator-select DR(现有)** vs **random-destroy(地板)**。留出 held-out 小算例评测。

## 4. 预写死判级（写进报告，禁止事后改）
- learned-destroy 在 held-out 小算例上平均比 operator-select **≥ +2%**(每规模 ≥0)、且稳超 random、零违约、worker py313 → **`PASS_LEARNED_DESTROY`** → 绿灯阶段B(补 FRVCP+碳感知+GLOP+全规模+GA/PSO擂台+精确解锚)。
- `0 ~ +2%` → **`WEAK_LEARNED_DESTROY`**：有方向但增量小，需先调特征/reward/采样再判，不进阶段B。
- `≤0` → **`HALT_LEARNED_DESTROY`**：学习型破坏在富问题小算例上没加值，**诚实记录负结果**，回蓝图重想(可能需更强特征/神经修复 NLNS 式/或换 NeuOpt 式学移动)。

### 4.1 判级有效性前提（防"欠训误杀"，铁律）
判级只有在 **learned 策略确实训练充分**时才算数。`PASS` 可直接信（欠训还能赢=方向硬）；**但 `WEAK`/`HALT` 不得直接当作"learned-destroy 没用"的结论**，必须先验训练是否到位：
- 看 `pilot20_update_log.csv` 训练曲线：reward 是否上行、entropy 是否合理下降、policy/value loss 是否收敛、approx_kl 是否正常。
- **若曲线平/没学（欠训）**：把 `--train-episodes`（默认 8 太小）调大重跑——25/50c 很便宜，可到几十~一两百 episode、必要时同时增大 `--eval-budget`/`--rollout-min-episodes`，**直到出现明确学习信号**，才让 `WEAK`/`HALT` 算数。
- 只有"学到了却仍不赢"才是真负结果；"没学到就输"是欠训、不是结论。报告里必须写明本次 learned 是否训练充分及依据。

## 5. 突发预案
- 指针头 PPO 不稳/不收敛：先用"按移除节省的贪心 destroy"做监督预热，或降 lr/加 entropy；仍不稳→记 `HALT_POLICY_UNSTABLE` 诊断。
- 吞吐/内存超：降 actors/eval_budget；worker 漂到 py312 或 NumPy≠2.3.5 或非有限成本→立即 `HALT_INTEGRITY` 查根因，不改参硬跑。
- 早停套利重现(actual_evals 远小于预算还说赢)：检查 reward，按"跑满有效预算才记成功"口径修。

## 6. 交付物
- 新增 DR lane 代码(worker 逐客户特征+remove_given_customers、policy 指针头、env learned_destroy 模式)+单测。
- `pilotXX_learned_destroy_phaseA_report.md/json` + 对比 CSV(learned-destroy / operator-select / random，各规模 best/mean/gap%/violation/worker/numpy/runtime/判级)+ 小模型。
- 最终回复用人话说：learned-destroy 比 operator-select 到底强多少、落在哪个判级、该不该进阶段B。

## 7. 资料顺序（先证据后动手）
先读 HANDOFF+蓝图+我们的 block_env/worker/policy 代码 + Cao/NLNS/NeuOpt 参考实现，再单点改、再短测。不得用"我猜"替代读码；接口拿不准→停下报告。
