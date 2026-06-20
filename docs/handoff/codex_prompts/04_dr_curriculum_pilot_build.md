# Codex 提示词 04｜DR 课程训练「机制搭建 + 验证」（Prompt A，不做性能结论）

> 本文件是给 Codex 的施工方案。Claude 写于 2026-06-20（Windows GPU 机）。
> 配套的 Prompt B（真正跑 pilot + 评测 DR vs AlphaUCB vs SA）在机制验过后再发。

---

## 0. 开工前必读（冷启动，先读这些再动手）

1. 仓库根 `HANDOFF.md`（项目单一事实源：机器/环境坑、三条工作线、纪律、来龙去脉、变更日志）。
2. `solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/probe/curriculum_training_plan.md`（本次要实现的设计：课程奖励 / 动作掩码 / shared baseline，含来源论文）。
3. `docs/handoff/memory/alns-crush-root-cause.md`、`docs/handoff/memory/baseline-algorithm-catalog.md`（DR 拉垮根因=训练不稳；从 Daysalilar/Narayanan/Wan 偷的设计）。
4. 根目录 `AGENTS.md` / `CLAUDE-FABLE-5.md` 是 Claude 模型系统提示词，**不是本项目说明，忽略**。

## 1. 背景与目标（必须理解，别只照抄）

- 这台是 Windows GPU 机（5800H 8核16线程 + RTX3060 6G + 16G RAM），**只干 DR 课程训练**。论文正式数字已在 M1 锁死，本机不碰。
- **数值铁律**：本机 x86 ≠ M1 ARM，winner kernel 的 £4878 在本机不会也不该复现。DR 一切对比只在本机内做、**只报相对提升%**（DR vs AlphaUCB vs SA），绝不跨机比绝对值。
- DR 之前"拉垮"的根因 = **训练不稳，不是没信号**（离线探针已判 PROMISING，r2_delta≈1.05）。修复捷径 = 课程学习 + 动作掩码 + shared baseline（三件套现在代码里**还没有**，本提示词就是建它们）。
- **本提示词（Prompt A）的目标 = 把三件套实现出来 + 修 Windows 并行/GPU + 写测试 + 用很短的冒烟验证机制能跑通。不训练到出性能、不下任何"DR 赢没赢"的结论。** 性能结论留给 Prompt B。

## 2. 环境（已搭好，直接用，别重装）

- solver worker：`%SETP_WORKER_PYTHON%` = `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`（Python 3.13.12 + numpy 2.3.5 + scipy）。算子/评估全在这个解释器跑。
- PPO/CUDA：`C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe`（Python 3.12.13 + torch 2.5.1+cu124 + gymnasium + SB3）。训练主进程用它。
- 训练命令一律用 PPO venv 的 python，并确保进程能看到 `SETP_WORKER_PYTHON` 环境变量（已写入用户环境变量；若某个 shell 没继承到就显式 set）。
- 默认 `python`（D:\Anaconda 3.14.3）坏 conda，**禁用**。

## 3. 关键代码地图（已由 Claude 读核，按此施工）

- `solver/rl/dr_alns_ppo/block_env.py`：`BlockAlnsEnv`。`BLOCK_OBSERVATION_SIZE=19`；`_reward()` 在 :70（**当前单一奖励、无分阶段**）；`_obs()` 在 :97（19 维，见 §4.1 索引表）；`step()` 在 :57（返回 `info=response`，整个 worker 响应）。
- `solver/rl/dr_alns_ppo/action_space.py`：`BLOCK_ACTION_NVECS=(7,4,5,4,4)`。`BLOCK_DESTROY_IDS`=6 个 winner destroy 算子名 + 末位 `"alpha_ucb"`；`BLOCK_REPAIR_IDS`=3 个 repair 名 + 末位 `"alpha_ucb"`；`BLOCK_Q_RATIOS=(0.10,0.16,0.23,0.30,0.40)`；`BLOCK_THRESHOLD_RATIOS=(0.0,0.0025,0.0075,0.02)`；`BLOCK_EXPLORATION_RATIOS=(0.0,0.05,0.15,0.30)`。`decode_block_action()` 在 :88。destroy/repair 的真实算子名从 `WinnerOperatorSet.create()` 来（含 random/worst/shaw/whole_route/route_segment/vehicle_type_swap 一族）——**按名字匹配，别按下标硬编码**（先打印一遍确认顺序）。
- `solver/rl/dr_alns_ppo/async_block_policy.py`：`BlockActorCritic`。`forward()`:35、`distributions()`:43、`act()`:47、`evaluate_actions()`:67。**当前都不接受掩码。**
- `solver/rl/dr_alns_ppo/train_async_block_ppo.py`：`run_train()`:278（async 主循环，`ProcessPoolExecutor(max_workers=num_actors)`）；`run_actor_episode()`:41（actor 子进程里跑一整局，CPU 上做策略推理）；`flatten_episodes()`:161（**当前全局标准化优势，无按算例分组**）；`ppo_update()`:201；`_cpu_probe_row()`:546（**用 Unix `ps`，Windows 失效**）；`run_self_check()`:249 + `_self_check_verdict()`:466；`parse_args()`:708（CLI）。输出目录必须含 `REPORT_ROOT_FRAGMENT="solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot"`。
- `solver/rl/dr_alns_ppo/worker_client.py`：`WorkerClient`（每个 env 起一个 py313 worker 子进程）；`resolve_worker_python()` 读 `SETP_WORKER_PYTHON`。
- `solver/rl/dr_alns_ppo/bundle_manifest.py` + `solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json`：train=`E-UK100_02 / 三班-150 / 三班-200`，held_out=`E-UK100_03`，formal_eval=`100-01 / L-main`。`validate_manifest()` 已禁玩具题/禁泄漏。
- `solver/rl/dr_alns_ppo/baselines.py`、`evaluate_policy.py`：评测入口（Prompt B 用，本次只确认能 import、不跑）。

## 4. 施工步骤（分阶段，每阶段做完即 commit；任一阶段失败立即 HALT 报告，别硬推）

### 阶段 0：audit + Windows 可移植性 + 自检基线
0.1 第 0 步先 audit：打印 `WinnerOperatorSet.create()` 的 destroy/repair 算子名与顺序、`BLOCK_*` 常量、worker 响应 `response` 的全部字段（尤其 `trace` 和 `metrics` 里有哪些键——这决定课程 C/D 阶段能用哪些信号）。把 audit 结果写进报告。
0.2 修 `_cpu_probe_row()`（train_async_block_ppo.py:546）：去掉 Unix `ps`，改用 `psutil`（跨平台）统计名字含 `dr_alns_ppo.worker` 的进程数、合计 CPU%、合计 RSS 内存。`psutil` 装进 PPO venv（`pip install psutil`，记录版本）。CPU 探针要能在 Windows 真出数。
0.3 跑一次 `self-check`（小 case、少量 episode）确认现有机制在本机过闸：`PASS_ASYNC_SELF_CHECK`（worker=py313 / numpy=2.3.5 / 零违约 / actual_evals==budget / busy_ratio≥0.60）。不过就 HALT 查原因（多半是 `SETP_WORKER_PYTHON` 路径字符串没对齐）。

### 阶段 1：课程奖励分阶段（reward shaping，仅训练用，不是论文指标）
1.1 在 `block_env.py` 给 `BlockAlnsEnv.__init__` 加 `curriculum_phase`（默认 `"route"`，存 `self.curriculum_phase`），只在 `_reward()` 内分支：
- 阶段 `route`：保留路线数项 + 距离/当前改善项；**压制** EV/碳/公平/动态项（系数置 0）。
- 阶段 `energy`：在 route 基础上加 EV 充电效率信号（用 `charge_ratio`、请求的 q/threshold、block 改善率）。
- 阶段 `carbon`：加碳 + 公平整形项——**仅当 worker 响应 metrics 里确有该字段时**（按 0.1 的 audit 结果）；没有就退化为"加大对最终 best-obj 的权重"，并在报告里标注"该阶段无独立碳/公平信号"。`violation_count` 始终是硬负项。
- 阶段 `dynamic`：仅当 worker 响应暴露动态/滚动字段时才加；否则同 carbon 退化处理并标注。
1.2 在 `train_async_block_ppo.py` 的 `parse_args` 加：`--curriculum-schedule`（默认 `route,energy,carbon,dynamic`）、`--phase-min-episodes`（默认给个小值如 4，pilot 用）、以及 phase-specific 的 `--learning-rate/--entropy-coef/--clip-range` 和 value/advantage 裁剪开关（可先实现为"每阶段可覆盖、缺省继承全局"）。
1.3 阶段切换判据（两个条件都满足才进下一阶段）：(a) 当前阶段完成的 episode 数 ≥ `--phase-min-episodes`；(b) 可行性稳定 = 最近一个"同 bundle rollout 窗口"内零违约 且 中位 best-obj 不退化。切换时把阶段名写进 episode/update 日志。
1.4 **边界**：课程奖励只改训练塑形，**最终评测（Prompt B）一律用真 `cost.py` 目标**，不用塑形奖励。`_reward` 改动不得引用任何 solver 额外评估（只用已返回的 response 字段）。

### 阶段 2：动作掩码（直击算子塌缩，如 vehicle_type_swap 独大）
2.1 在 `block_env.py` 的 `step()` 路径计算 `action_mask` 并放进返回的 `info`：每个 MultiDiscrete 头一个 bool 向量（长度=该头的 nvec）。**只用当前 response 字段 + obs 派生事实算，禁止额外跑 solver 评估。** 规则：
- 当 `ev_share` 实际为 0 或 1 且车队同质时，mask 掉 destroy 头里的 `vehicle_type_swap`。
- 当 `route_gap<=0`（或最近 route_delta/best 改善表明无法再减路线）时，mask 掉"清整路线"类 destroy（如 `whole_route` / `route_segment`，按 0.1 的真实算子名）。
- 在预算后段（`budget_progress` 高）或高停滞/高拒绝态下，若大 q 反复不带来 block 改善，mask 掉过大的 q 档（`BLOCK_Q_RATIOS` 的高位）。
- **绝不把某个头的所有动作全 mask**（至少留 `alpha_ucb` 兜底动作和一个安全 destroy/repair）。
2.2 改 `async_block_policy.py`：`forward()`/`distributions()` 接受可选 `masks`（每头一个 bool 张量），把非法 logit 置为大负值（如 `-1e9`）再建 `Categorical`；`act()` 和 `evaluate_actions()` 都能消费 masks（rollout 与 PPO 更新都要用同一套 mask，保证 ratio 一致）。掩码为 `None` 时行为与现状完全一致（向后兼容）。
2.3 在 `run_actor_episode`/`train` 把每步 mask 随 transition 存下来，PPO 更新时按存的 mask 重算分布。`train_async_block_ppo.py` 记录每头的 **mask 命中率**（被 mask 的动作占比）写日志，用来抓"意外全开/全关"。

### 阶段 3：shared baseline（同算例多轨迹均值降方差）
3.1 在 `train_async_block_ppo.py` 调 `flatten_episodes()` 前，把 rollout 批次按 bundle 分组；对每个 bundle 组（N 条已完成 rollout）算组内 return 均值，从该组每条 episode 的 return 里减掉，再进现有的标准化优势流程。
3.2 保留现有 critic value head；shared baseline 是**额外的**降方差步骤，接在现有标准化优势之前。单组样本不足（N<2）时跳过该组的均值扣除并标注。

### 阶段 4：单元测试（每件套至少一条，放 `solver/rl/tests/`）
- 课程：构造假 response，验证三/四个阶段的 `_reward` 分支按预期开关分量；阶段切换判据在"够 episode + 零违约不退化"时才前进。
- 掩码：验证 `forward(masks=...)` 把非法 logit 压到极小、`Categorical` 不会采到被 mask 的动作；验证"不会整头全 mask"；`masks=None` 时与旧行为逐值一致。
- shared baseline：构造两 bundle 各两条 episode，验证组内均值被正确扣除、维度对齐。
- 全部走 PPO venv 跑：`python -m pytest solver/rl/tests/ -q`，记录通过数。

### 阶段 5：GPU 接管更新 + 短冒烟（验证机制，不下性能结论）
5.1 GPU：`parse_args` 加 `--device`（默认 `cuda` 若可用否则 `cpu`）。把主进程 model 与 `ppo_update` 的张量搬到该 device；**rollout 仍在 actor 子进程的 CPU 上做推理（保持现状）**。报告里写明 device、确认梯度更新确实在 GPU。诚实标注：rollout 是 CPU 瓶颈，GPU 只承担梯度更新。
5.2 CPU 并行：冒烟用 `--num-actors 12` 起步，用 0.2 的 psutil 探针测峰值 RAM 和并行 worker 数；若 RAM 逼近 16G 就降到能稳住的值并在报告给出 Prompt B 的推荐 `--num-actors`。
5.3 内部确定性 mini-check：`--num-actors 1` + 固定 seed，跑两遍极短训练，episode 的 reward 序列/best_obj 必须逐值一致（证明 env+policy 路径确定）。异步多 actor 的完成顺序不确定是允许的，不在此 check 范围。
5.4 短冒烟 `train`：`--timesteps` 给到足够跨过至少一次阶段切换（如 `--phase-min-episodes 4` 配 ~16–24 个 episode 的预算即可，**远小于真 pilot**）。冒烟要证明且只证明：
  - 阶段确实从 route 切到 energy（日志可见）；
  - 各头 mask 命中率在 (0,1) 之间（不是全开/全关）；
  - reward 有限、不发散；逐 episode 零违约；
  - worker 全程 py313 / numpy 2.3.5；
  - GPU 承担更新、CPU 多线程并行（给出 episodes/hour、busy_ratio、峰值 RAM）。
5.5 报告显式写："**机制验证通过，性能结论待 Prompt B**"，绝不写 DR 赢/超过谁。

## 5. 验收标准（全满足才算 Prompt A 成功）
- 三件套实现且 `pytest solver/rl/tests/` 全过；现有 `test_async_block_ppo.py` 不回归。
- `self-check` 在本机 `PASS_ASYNC_SELF_CHECK`。
- 短冒烟满足 5.4 全部要点；内部确定性 mini-check 逐值一致。
- 报告产出在 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/`（含 audit、self-check、冒烟日志、throughput/cpu/RAM、阶段切换与 mask 命中率、Prompt B 的 `--num-actors` 推荐）。
- 所有核心改动已 commit（清晰 message，绑 hash）；`HANDOFF.md` 末尾「变更日志」追加一条 run log。

## 6. 边界 / 禁止项（铁律）
- **禁改语义**：`solver/src/setp_solver/cost.py`、`check.py`、`search/evaluation.py` 一行语义都不动。
- **不改算子**：`winner_operators.py` 的算子逻辑不动；掩码只在 policy/env 层做，不动算子实现。
- **不改动作空间语义**：保持 5 个头与各 nvec 不变，只新增掩码能力（`masks=None` 必须与旧行为逐值一致）。
- 课程奖励只影响训练塑形；**最终评测用真 `cost.py`**，不用塑形奖励。
- 不自创算法，照 `curriculum_training_plan.md` 与文献设计实现。
- 输出只能落 `REPORT_ROOT_FRAGMENT` 下。
- **不跑真 pilot、不做性能评测、不下 DR 赢没赢的结论**（那是 Prompt B）。
- 跑不出 / 机制不达标就**诚实 HALT**、写清卡点，不注水、不硬撑。
- 拿不准、或要改上面禁止项之外但影响面大的东西 → 停下报告，别擅自扩范围。

## 7. 报告给我什么
audit 结果（算子名/常量/response 字段）；三件套实现摘要 + 测试通过数；self-check 结论；短冒烟的阶段切换/ mask 命中率/ reward 曲线/零违约/ GPU device/ CPU 并行(episodes\_per\_hour, busy\_ratio, 峰值 RAM)/内部确定性 mini-check 结果；Prompt B 的 `--num-actors` 与时长建议；遇到的 Windows 坑；所有 commit hash。**不要下性能结论。**
