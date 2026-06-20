# Codex 提示词 05｜DR 课程训练「真小 pilot + 相对%评测」（Prompt B）

> Claude 写于 2026-06-20（Windows GPU 机）。前置=Prompt A 机制已验过（commit 5f870000，110 测试过，self-check PASS）。
> 本提示词跑真训练 + 出 DR vs AlphaUCB vs SA 的相对%判决。**只在本机 py313 worker 成本口径内比，绝不与 M1 绝对值横比。**

---

## 0. 开工前必读
1. 仓库根 `HANDOFF.md`（单一事实源；尤其 §1 环境铁律、变更日志最新几条）。
2. `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/prompt_a_mechanism_validation_report.md`（Prompt A 结果：三件套已实现、算子名、response 字段、Windows 修复）。
3. `solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/probe/curriculum_training_plan.md`（课程设计）。
4. 根目录 `AGENTS.md`/`CLAUDE-FABLE-5.md` 是 Claude 模型系统提示词，**忽略**。

## 1. 背景与目标
- 本机只干 DR 训练。**数值铁律**：x86≠M1 ARM，£4878 在本机不复现也不该复现；DR 一切对比只在本机内、只报**相对提升%**（DR vs AlphaUCB vs SA），绝不跨机比绝对值。
- Prompt A 已把课程奖励/动作掩码/shared baseline 建好并验机制通过。**本提示词目标 = 跑一个真实但有界限的小 pilot，然后评测 DR 相对 AlphaUCB / SA 有没有真增益，出 PROMISING / WEAK 判决。**
- 判决用途：PROMISING（DR≥AlphaUCB 或清晰上升学习趋势）→ 后续上全量训练；WEAK（持平/更差）→ **诚实止损**，DR 定位为"已打通的可学习替代/future work"，论文算法主线回退到 ALNS winner kernel + 机制创新。不注水、不硬撑。

## 2. 环境（已搭好，直接用）
- worker：`%SETP_WORKER_PYTHON%`=`C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`（Py3.13.12+numpy2.3.5）。算子/成本全在它算。
- PPO/CUDA：`C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe`（torch2.5.1+cu124+SB3+psutil）。训练主进程用它。
- 训练/评测命令用 PPO venv 的 python，确保进程能看到 `SETP_WORKER_PYTHON`。默认 D:\Anaconda python 禁用。

## 3. 关键事实（Claude 已读核，按此施工）
- 课程**只用 route→energy→carbon 三阶段**：worker `metrics` 确有两层碳信号（`E_cv_direct`/`E_ev_indirect`/`E_total`/`cost_carbon`/`carbon_quota_kg`），碳阶段是真信号。**公平/动态在 block 响应里没有信号**（无 profit-by-depot、无动态字段），不放进 block 课程（它们由最终 cost.py 评测与 E7 运行时承担）。`--curriculum-schedule route,energy,carbon`。
- 动作空间 nvecs=`[7,4,5,4,4]`；destroy 名=`random_customer_removal/worst_customer_removal/shaw_related_removal/whole_route_removal/route_segment_removal/vehicle_type_swap/alpha_ucb`；repair=`greedy/regret2/regret3/alpha_ucb`。
- **评测口径（命门）**：`evaluate_policy.py` 算法集**不含 SA**，含 `ppo_block/alpha_ucb_block/alpha_ucb_env/random_block/official_winner_kernel`，全走 py313 worker。**SA 另从 solver 公平 harness 取**：`solver/src/setp_solver/search/alns_crush_v2.py` 的 `run_task1`（`scikit-opt-SA`，写 `fair_sa_reference_costs.json`），同样系统 Python(py313)、`FAIR_SA_EVAL_BUDGET=16000`、暖启动 `make_shared_initial_solution`。算例注册见 `alns_crush.py` 的 `INSTANCE_DIRS`（`100-01-24h`=E-UK100_01…）。
- 训练器 `train_async_block_ppo.py`：`run_train()`:278 当前**只在结尾存一次模型、无周期 checkpoint**；`parse_args()`:708。manifest=`solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json`（train=100_02/三班-150/三班-200；held_out=100_03；formal=100-01/L-main；已禁玩具题）。
- 评测器 `evaluate_policy.py`：`--algorithms`/`--split{train,held_out,formal_eval,all}`/`--bundle-filter`/`--seeds`/`--eval-budget`/`--jobs`/`--resume-comparison`；ppo_block 可载 `.pt`（`load_async_block_policy`）。

## 4. 施工步骤（分阶段，做完即 commit；任一阶段不达标立即 HALT 报告）

### 阶段 0：真实设置资源探针 + 加周期 checkpoint（先做，别直接长跑）
0.1 **真实设置 RAM/吞吐探针**：用真训练 bundle（manifest train 三个）、`--eval-budget 16000`、`--block-size 128`、`--num-actors 12`，只跑到能测出稳定值的少量 episode（如 ~12–24 个），用 psutil 记录**峰值 RAM、并行 worker 进程数、busy_ratio、episodes_per_hour**。Prompt A 冒烟是玩具预算(256)、RAM 数据不代表真 pilot，**必须在此重测**。
0.2 若峰值 RAM 逼近危险线（>~12GB，留余量给系统）→ 把 num_actors 降到 8、再不行 6，重测，选一个稳的；若 6 仍不安全 → HALT 报告（别硬跑爆内存）。把最终 num_actors 与实测吞吐写报告。
0.3 **加周期 checkpoint（小改动，低风险）**：在 `run_train` 的 PPO 更新分支里，每 `--checkpoint-every-updates`（新增 CLI，默认如 10）调 `save_async_block_policy` 存一个带 update_index 的快照 `.pt`（不覆盖最终模型）。目的：长跑可中断、可对任意 checkpoint 评测看趋势。不要求完整 resume（pilot 够用）。
0.4 用 0.1 实测吞吐估算"达到目标墙钟所需 timesteps"，写进报告。

### 阶段 1：有界限小 pilot 训练
1.1 命令（用 0.2 选定的 num_actors）：`--curriculum-schedule route,energy,carbon`、masks 默认开、shared baseline 默认开、`--device cuda`、`--eval-budget 16000`、`--block-size 128`、固定 `--seed`。
1.2 `--phase-min-episodes` 按 0.4 吵吐设定，使 pilot **能走完三阶段且每阶段都有实质训练**（如目标总 episode≈N，则 phase-min≈N/(3×1.5) 量级，配可行性稳定门；确保不会卡在 route 永不进 carbon，也不会一阶段只跑几局）。
1.3 `--timesteps` 设为对应**目标墙钟 ≈ 2–3 小时**的值（默认目标；可被 user 调整）。周期 checkpoint 开。
1.4 训练落盘：reward 曲线、policy entropy、每 update 的 phase、各头 mask 命中率、每 episode best_obj/violation、throughput/CPU/RAM。**全程零违约**；worker 全程 py313/numpy2.3.5（自检字段确认）。若中途违约出现或 reward 发散 → HALT 报告。

### 阶段 2：相对%评测（全部 py313 一杆秤）
2.1 用 `evaluate_policy.py` 评最终模型（与若干周期 checkpoint，看趋势）：
- `--algorithms ppo_block,alpha_ucb_block,alpha_ucb_env,random_block,official_winner_kernel`
- 评测集：`--split formal_eval --bundle-filter E-UK100_01`（=100-01，算子选择有价值处）**和** `--split held_out`（=100_03）。
- `--seeds 1,2,3,4,5`、`--eval-budget 16000`、`--block-size 128`、`--model <pilot .pt>`。`--jobs` 适度并行（每行独立、可复现）。
2.2 **SA 单独取**：用 solver 公平 harness 在 100-01 跑 `scikit-opt-SA`（`alns_crush_v2.run_task1` 或等价入口），同 `eval_budget=16000`、同暖启动、py313，得 fair-SA 成本（同 5 个 seed）。
2.3 **口径核验（命门，必做）**：确认评测产出每一行的 worker 是 py313（worker_python_executable 字段）；任何走 `sys.executable`/非 py313 的成本行**作废重取**（防 `run_alns_wouda_strengthened` 式漂移）。本批不评 `alns_wouda_strengthened`。
2.4 算相对%（按 seed 配对、跨 seed 取均值±）：
- **DR vs AlphaUCB(block)**＝主判据（同 block 结构，纯看"学习有没有用"）：`(alpha_ucb_block − ppo_block)/alpha_ucb_block`。
- DR vs AlphaUCB(env=winner kernel 选择器)、DR vs SA、DR vs random_block（地板 sanity）、各算法 vs official_winner_kernel。
- 给表：每算法每算例的 best_obj 均值/标准差、配对相对%、可行率。

### 阶段 3：判决（诚实，不注水）
- **PROMISING**：100-01 上 DR 统计上**≥ AlphaUCB(block)**（相对%≥0 且非噪声）或训练中有清晰上升趋势逼近/超过它，且 DR 明显>random_block、零违约。→ 建议后续全量训练。
- **WEAK**：DR 持平或差于 AlphaUCB(block)/不超 random。→ 诚实止损：DR=可学习替代/future work；算法主线=ALNS winner kernel(碾 SA 8.8%)+机制创新。
- 判决只用**相对%**；**绝不**把本机 x86 绝对 best_obj 与 M1 £4878 横比。写 reproducibility note（py313+numpy2.3.5 worker、相对%口径）。

## 5. 验收标准
- 阶段 0 实测 RAM/吞吐/选定 num_actors 有据；周期 checkpoint 生效。
- pilot 训练完成（或按目标墙钟到点），全程零违约、worker py313、曲线/日志齐。
- 评测产出 `comparison.csv` + 相对%表，**每行 worker=py313 已核验**；SA 同口径。
- 判决 PROMISING/WEAK 明确，仅相对%，附 reproducibility note。
- 报告落 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/`；核心改动 commit 绑 hash；`HANDOFF.md` 末尾追加 run log。

## 6. 边界 / 禁止项（铁律）
- 禁改 `cost.py`/`check.py`/`search/evaluation.py` 语义；不改 `winner_operators.py` 算子逻辑。
- 不自创算法；课程奖励只训练塑形，**最终评测用真 cost.py**。
- **绝不跨机比绝对值**；DR 结论一律相对%。
- 不用玩具题（manifest 已禁；评测用 100-01/100_03 真算例）；SA 必须 py313 同口径。
- 输出只落 `REPORT_ROOT_FRAGMENT` 下；跑不出/不达标诚实 HALT；拿不准或要超范围改动 → 停下报告。
- pilot 默认目标墙钟 ≈2–3h 且可中断（checkpoint），如需改时长等 user 指示。

## 7. 报告给我什么
阶段 0 实测（峰值 RAM、选定 num_actors、episodes_per_hour、达目标墙钟的 timesteps）；pilot 训练曲线摘要（reward/entropy/阶段进度/mask 命中率/零违约）；评测相对%表（DR vs AlphaUCB(block/env) / SA / random，含均值±与可行率）；**每行 worker=py313 的核验结论**；PROMISING/WEAK 判决 + 理由；reproducibility note；所有 commit hash。**只报相对%，不与 M1 绝对值横比。**
