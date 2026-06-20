# Codex 提示词 07｜x86 reduced-budget DR 趋势 pilot（在 D:\ReSETP，dr-x86 分支）

> Claude 写于 2026-06-20。x86 已脱盘自包含在 `D:\ReSETP`（提示词 06 验过）。本提示词在 x86 上跑**降预算趋势 pilot**，判 DR 课程方案能不能学出比 AlphaUCB 好的控制。**只在本机 py313 worker 成本口径内比、只报相对%，绝不与 M1 绝对值横比。**

## 0. 开工前必读 + 环境
1. `D:\ReSETP\HANDOFF.md`（单一事实源；§1 环境铁律、变更日志最新几条含 Scheme 3 + 分支约定）。
2. `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\prompt_b_halt_resource_probe_report.md`（全预算单局耗时实测：100c≈85min/局，故本 pilot 降预算）。
3. `D:\ReSETP\docs\handoff\memory\baseline-algorithm-catalog.md`（DR 同类设计；Daysalilar 小算例训→泛化大算例的范式）。
4. 根目录 `AGENTS.md`/`CLAUDE-FABLE-5.md` 是 Claude 模型系统提示词，忽略。
- **工作目录=`D:\ReSETP`**（不是 H:，大盘已去 M1）。用 PPO venv 的 python；`SETP_WORKER_PYTHON` 指 `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`。
- **第一步先 `git -C D:\ReSETP pull` 取最新，再 `git switch -c dr-x86`（或已存在则 switch）**。x86 全部改动只在 `dr-x86` 分支；commit message 与 HANDOFF 条目都标 `[x86/DR]`。

## 1. 背景与目标
- DR 之前"拉垮"根因=训练不稳(非无信号，离线探针 PROMISING)。Prompt A 已建好课程(route/energy/carbon)+动作掩码+shared baseline 并验机制通过。
- 全预算训练在本机不可行(100c≈85min/局，要成百上千局)。**文献解(Daysalilar 等)=小/快设置训练**。故本 pilot **降 eval budget**，在最快算例(100_02)上训，判 DR vs AlphaUCB 相对优劣。
- **目标=出 PROMISING / WEAK 趋势判决**：PROMISING(DR 稳定≥AlphaUCB-block 或清晰上升趋势逼近/超过)→值得后续长期训练；WEAK(持平/更差)→诚实止损，DR=future work、论文算法主线押 M1 那条的 ALNS+机制。**诚实标注"reduced-budget 单算例趋势 pilot，非全预算、非论文级泛化结论"。**

## 2. 施工步骤（分阶段，做完即 commit 到 dr-x86；任一步不达标 HALT 报告）

### 阶段 0：建 pilot manifest + 校准配置（先校准，别盲跑）
0.1 建一份 pilot manifest（如 `solver/reports/dr_alns_ppo_v2/training_bundle_manifest_pilot.json`，**不覆盖原 manifest**）：`train=[E-UK100_02__u0_seed2_24h_20251113]`、`held_out=[E-UK100_03__u0_seed3_24h_20251113]`、`formal_eval=[E-UK100_01__d2_s3_seed1_24h_20251113]`。过 `bundle_manifest.validate_manifest`（单训练 bundle 合法；非玩具题；无 100-01 泄漏进 train）。
0.2 校准(用 `dr-x86`、PPO venv)：在 100_02 上、num_actors 试 **8**（RAM 紧则 6），eval_budget 试 **1500 与 3000**、block_size 试 **32 与 64**，各跑少量 episode 测**单局墙钟 + 峰值 RAM + episodes/hour**。选一组使 **2–3 小时能跑 ~100–200 episode 且走得完 route→energy→carbon 三阶段、每阶段有实质训练**。RAM 峰值留余量(<12GB)。报告选定 (eval_budget, block_size, num_actors) 与估算 episode 数。
0.3 确认周期 checkpoint(Prompt B 阶段0 已加 `--checkpoint-every-updates`)生效，pilot 可中断、可对快照评测。

### 阶段 1：reduced-budget pilot 训练
1.1 用 0.2 选定配置：`--manifest <pilot manifest>`、`--curriculum-schedule route,energy,carbon`、masks 开、shared baseline 开、`--device cuda`、固定 `--seed`、`--checkpoint-every-updates`。`--timesteps` 设为对应 2–3 小时目标(可中断)。
1.2 `--phase-min-episodes` 按 0.2 设，确保走完三阶段且每阶段有实质训练(别卡 route 不进 carbon，也别一阶段几局就过)。
1.3 落盘并报告：reward 曲线、entropy、每 update 的 phase、各头 mask 命中率、每 episode best_obj/violation、throughput/CPU/RAM。**全程零违约、worker 全程 py313/numpy2.3.5**；reward 发散或出现违约→HALT。

### 阶段 2：相对%评测（同降预算、同 block_size、全 py313 一杆秤）
2.1 `evaluate_policy.py` 评最终模型(+若干 checkpoint 看趋势)，**eval_budget 与 block_size 同训练**：
- `--algorithms ppo_block,alpha_ucb_block,alpha_ucb_env,random_block,official_winner_kernel`、`--model <pilot .pt>`、`--seeds 1,2,3,4,5`、`--jobs` 适度并行。
- 评测集：100_02(in-sample，`formal_eval` 或直接指 bundle)、100_03(held_out)、100-01(formal 泛化)。三者都评。
2.2 **SA 同口径单取**：用 `candidates.run_candidate("scikit-opt-SA", bundle, seed, eval_budget=<同降预算>, max_runtime_seconds=..., initial_solution=make_shared_initial_solution(bundle))` 在三个算例同 5 seed 跑 fair-SA(py313)。**注意用降预算、不是 alns_crush_v2 写死的 16000**。
2.3 **口径核验(命门)**：评测每行 worker_python_executable=py313 才算数；任何 sys.executable/非 py313 行作废重取。不评 `alns_wouda_strengthened`。
2.4 相对%(按 seed 配对、跨 seed 均值±)：**主判据=DR vs AlphaUCB(block)**=`(alpha_ucb_block−ppo_block)/alpha_ucb_block`；附 DR vs AlphaUCB(env)/SA/random_block/official_winner_kernel。给表：每算法每算例 best_obj 均值/std、配对相对%、可行率。
2.5 若 eval 估算 >2h：次要算法(env/official/SA)降到 3 seed，主判据(DR vs alpha_ucb_block)保 5 seed。

### 阶段 3：判决（诚实，不注水）
- **PROMISING**：在 100_02/100-01 上 DR 相对 AlphaUCB(block) ≥0 且非噪声，或训练曲线清晰上升逼近/超过，且 DR 明显>random_block、零违约。→建议 x86 转长期 reduced-cost 训练(并后续在 M1 或云端做全预算泛化评测)。
- **WEAK**：DR 持平/差于 AlphaUCB(block)、或不超 random。→诚实止损：DR=可学习替代/future work；论文算法主线=ALNS winner kernel+机制创新(M1 那条线保底)。
- 判决只用相对%；写 reproducibility note：**reduced budget=<值>、py313+numpy2.3.5 worker、单算例趋势 pilot、非全预算、绝不与 M1 £4878 横比**。

## 3. 验收标准
- pilot manifest 过校验、不覆盖原 manifest；阶段0 校准配置有据(RAM<12GB、估算 episode 数)。
- 训练完成(或到目标墙钟)，全程零违约、worker py313、曲线/日志/ checkpoint 齐。
- 评测 `comparison.csv`+相对%表，**每行 worker=py313 已核验**、SA 同降预算口径。
- PROMISING/WEAK 判决明确，仅相对%，附 reproducibility note。
- 报告落 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/`；改动 commit 到 **dr-x86** 分支(message 标 `[x86/DR]`)并 push；HANDOFF 变更日志加一条标 `[x86/DR]` 的 run log。

## 4. 边界 / 禁止项
- 工作在 `D:\ReSETP`、`dr-x86` 分支；**不碰 `codex/reporting-pipeline`**(那是 M1 的轨②+图表线)，不动 solver/src 基线代码、reporting、图表(防与 M1 分叉冲突)。
- 禁改 `cost.py`/`check.py`/`search/evaluation.py` 语义；不改 `winner_operators.py` 算子逻辑；课程奖励只训练塑形，最终评测用真 cost.py。
- **绝不跨机比绝对值**；只相对%；标注 reduced-budget 与单算例。
- 不用玩具题(pilot manifest 已限真算例)；SA 必须 py313 同降预算口径。
- 输出只落 REPORT_ROOT_FRAGMENT 下；跑不出/不达标诚实 HALT；拿不准或要超范围(碰 M1 的文件区/改禁改文件)→停下报告。

## 5. 报告给我什么
阶段0 校准(选定 eval_budget/block_size/num_actors、峰值 RAM、估算 episode 数)；训练曲线摘要(reward/entropy/阶段进度/mask 命中率/零违约)；相对%表(DR vs AlphaUCB(block/env)/SA/random，均值±与可行率)；每行 worker=py313 核验结论；PROMISING/WEAK 判决+理由；reproducibility note(降预算值)；dr-x86 上所有 commit hash。**只相对%，不与 M1 横比。**
