# ReSETP — 项目总交接文档（HANDOFF）

> **单一事实源（Single Source of Truth）。**
> 任何机器上的 Claude 或 Codex，**开工前必须完整读完本文件 + `docs/handoff/memory/` 记忆快照**，否则禁止动手/下结论。
> 每次重大决策 / 任务 / 对话后，把变化追加到文末「变更日志」，让本文件始终最新。跨机器迁移、防偏差全靠它。
> 维护：Claude 更新本文件与 `docs/handoff/memory/`；Codex 每次跑完在「变更日志」追加一条 run log。

## 0. 一分钟速览
ReSETP = 投《系统工程理论与实践》的绿色车辆路径论文。多车场、油车(CV)+电车(EV)混合车队、EV 非线性充电（时变碳强度）、时间窗、收益公平、动态需求滚动重规划。
贡献 = 模型 + 机制（碳两层/协同/公平/动态）；算法也必须有创新，且要**打过文献主流算法**（GA-VNS/GA/PSO/ACO/VNS/LNS/GWO/IWD），不只赢 SA（SA 是地板，赢它只算"合格"）。
主线算法 = ALNS(winner kernel) + DR-ALNS（强化学习指挥 ALNS）。

## 1. ⚠️ 机器与环境（最重要，先读，踩了全盘皆输）
- **基准机 = M1 + 8G RAM（macOS, ARM）= 当前机 = 所有论文正式数字的唯一来源。**
- **GPU 机 = 5800H + RTX3060 6G + 16G RAM（操作系统待确认；很可能 Windows/Linux，不是 mac）。仅用于 DR 课程训练。**
- 金标准环境（M1）：`/opt/anaconda3/bin/python3.13` + numpy 2.3.5。锚：100-01 winner £4878.33 / 公平SA £5346.99（winner 碾 8.76pp）；L-main winner £8351 ≈ SA £8319（近最优、持平）。
- **致命坑①（ARM vs x86）**：M1(ARM) 与 5800H(x86) 浮点/BLAS 不同 → £4878 等锚在新机几乎必然变样（已被 venv numpy 漂移坑过一次：£4878→£5696、反输 SA）。**铁律：绝不把 M1 与 x86 的绝对数字放进同一张表/同一篇结论。**
- **致命坑②（可能 macOS→Win/Linux）**：若 5800H 非 mac，`/Volumes`、`/opt`、shell、`SETP_WORKER_PYTHON`、行尾、外置盘文件系统（APFS 跨平台读不了）全要变。**所有硬编码路径 `/Volumes/移动硬盘（512G）/ReSETP` 都会断**，需参数化为"仓库根"。
- **迁移分工（Claude 建议，待 user 最终确认）**：M1 = 唯一基准（E1-E7、所有表图、winner/SA/8基线对比都留 M1 跑）；5800H+3060 = 只做 DR 课程训练，DR 结果以**相对提升 %** 报（DR vs AlphaUCB vs SA 全在 5800H 同环境测，环境抵消，不与 M1 £4878 比绝对值）；训完迁回 M1。
- 新机要重建两套环境：① 系统 Python 3.13 + numpy 2.3.5 跑 solver（注意 x86≠ARM 数值）；② torch/CUDA venv 跑 PPO（3060）。`SETP_WORKER_PYTHON` 路径会变。**任何环境用前先验"同种子同结果"的内部确定性。**
- **同步：当前无 git remote，靠物理搬外置盘。强烈建议建私有 GitHub remote**（否则两机易分叉、盘坏即全失，且搬盘会中断 M1 上正在跑的 E1-E7）。
- 清理：仓库有 macOS AppleDouble 垃圾（`._*`，含 `.git/objects/pack/._*.idx`，git 报 non-monotonic index 警告）。迁到非 mac 机前 `dot_clean .` 或删 `._*`。

## 2. 三条工作线当前状态（2026-06-20）
- **图表（13 张）**：壳目录 + 数据适配完成；第四阶段"照壳填数据画图"等大重跑数字。详见 `docs/handoff/memory/figure-redesign-task.md`。
- **大重跑 E1-E7 + 表图重生成**：✅ **完成（2026-06-20, commit `9da7f8b`）= 论文正式数字锁死**。471/471 零失败零违约；**£4878 锚精确复现**（ALNS 4878.3318 / SA 5346.99）；T3-T9 + F1-F6/F5b 重生成到 `docs/paper_submission_final`，**F4 修好非空**；碳段 →**2330.7 kgCO2e**；latexmk 过；solver166/RL102 过；保护文件未动。报告 `solver/reports/formal_winner_20260619/`。小尾巴：E2 有 1 条 stale DR-ALNS provenance 行（T3 已排除，无害）。注：这是"正式数字 + 现有风格表图"完成；图表"顶刊级重设计"是否并入待确认（见 `docs/handoff/memory/figure-redesign-task.md`）。
- **ALNS winner kernel**：100-01 碾 SA 8.8%（£4878 vs £5347）健康；L-main 近最优持平。代码 `solver/src/setp_solver/search/winner_operators.py`。
- **DR-ALNS（block lane）**：离线探针 = **PROMISING**（有可学上下文信号，r2_delta≈1.05, CI[0.957,1.157]）。根因是训练不稳、非无信号。下一步 = 上 3060 做课程训练；方案在 `solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/probe/curriculum_training_plan.md`。代码 `solver/rl/dr_alns_ppo/`（block_env/async_block_policy/train_async_block_ppo/offline_probe）。
- **8 文献基线（轨②）**：已实现接入统一接口、零违约跑通，但 **HALT_BASELINE_THROUGHPUT**（eval/s 3.96–11.04 < 16000/900s 需的 17.78）。下一步 = 先 profile 提速（每个计数 eval ≈ 一次 evaluate，full check 延后/缓存 decode），仍不够再换等墙钟公平。**基线对比必须在基准机 M1 跑**（与 £4878 锚同环境）。代码 `solver/src/setp_solver/search/metaheuristic_baselines.py` + `metaheuristic_baseline_runner.py`；产物 `baselines/`。

## 3. 纪律铁律
- 禁改 `cost.py` / `check.py` / `evaluation.py` 语义（唯一真值源）。
- 公平对比：同 evaluate/check + 同预算（16000 eval 或等墙钟，见 §6 待决）+ 10 seed + scipy Wilcoxon + 零违约 + 暖启动 `make_shared_initial_solution`；每个基线目标计算走同一 `evaluate()/penalized_obj`、过 `EvalBudget` 计数、封顶预算。
- Codex 不自创算法，只复刻文献/适配现成；拿不准停下报告。
- 核心代码立即 commit；数字绑 commit hash；跑不出诚实 HALT 不注水。
- 角色：Claude 只思考/判断/写 Codex 提示词/写文档，不跑不改代码、不开 workflow；Codex 执行。关键核验才让 Claude 亲自读仓库。
- 与 user 对话用平实中文；给 Codex 的提示词要详尽自包含（它冷启动、读不了论文，要把目标/背景/实现/验收/边界/捷径全喂）。

## 4. 关键代码地图 + 公平对比接口
- `solver/src/setp_solver/cost.py` → `evaluate()`（真实目标，禁改）
- `solver/src/setp_solver/check.py` → `check_solution()`（可行性，禁改）
- `solver/src/setp_solver/search/evaluation.py` → `EvalBudget`、`penalized_obj/score_candidate/model_cost`
- `solver/src/setp_solver/solution.py` → `Solution{routes[Route(vehicle_id,vehicle_type,home_depot_id,node_sequence)], charging_actions[...], cross_site_services[...]}`
- `solver/src/setp_solver/search/candidates.py` → `run_candidate(label,bundle_dir,seed,eval_budget,max_runtime_seconds,initial_solution)`；`make_shared_initial_solution(bundle)`；现成构造/修复/插入/充电算子（基线解码复用它，别重造可行性）
- `solver/src/setp_solver/search/alns_crush_v2.py` → 公平 harness：`FAIR_SA_EVAL_BUDGET=16000`/`900s`；run_task1=公平SA→`fair_sa_reference_costs.json`；run_task3=winner vs SA + `_wilcoxon_vs_fair_sa` + 判级（碾压/小幅领先/持平/失败）
- `solver/src/setp_solver/search/alns_crush.py` → `INSTANCE_DIRS`：`100-01-24h`=models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113；`L-main`=…/E-UK24h-三班-01。150/200 未生成。
- `solver/src/setp_solver/search/winner_operators.py` → `run_winner_kernel(bundle_dir, WinnerKernelConfig(...))`
- `solver/rl/dr_alns_ppo/` → DR block lane（block_env 19维obs+5维动作；worker 用 SETP_WORKER_PYTHON=系统Python 跑算子）
> 深细节（8 基线设计转录、DR 同类偷的设计、harness 字段）见 `docs/handoff/memory/baseline-algorithm-catalog.md`。

## 5. 决策链 / 来龙去脉
- 真目标纠正：不是"碾 SA"（那只合格），是 **DR-ALNS 真训练+创新、干过 GA-VNS/GA/PSO 等文献主流**；退路 = 创新的普通 ALNS。
- DR "拉垮" 根因 = **训练不稳（非无信号）**；离线探针已证 PROMISING；**课程学习 + 动作掩码 + shared baseline 是修复捷径**（偷自 DR 同类论文 Daysalilar/Narayanan/Wan）。
- 两条便宜活并行：①探针优先（已 PROMISING）→ ②基线对比（已 HALT 在 throughput）。
- 公平口径：先提速保 16000/900s，不行再等墙钟；注意 16000 eval 对种群法（GA/PSO/GWO/IWD）可能偏少、反而低估基线。
- 迁移：M1 canonical，3060 只训 DR（相对 %）。

## 6. 待决 / 下一步
- **迁移三问（待 user）**：① 5800H 什么系统？外置盘什么文件系统（新机读得了吗）？② 仓库怎么过去——搬盘 / copy 一份 / 建 GitHub 私有 remote？③ 认 "M1 canonical + 3060 只训 DR（相对%）+ E1-E7/基线都留 M1" 这个分工吗？
- **轨②**：写第三条 Codex 提示词（profile → 提速 → 按选定公平口径出正式对比表）。
- **轨①**：迁移就绪后上 3060 课程训练（curriculum_training_plan.md 已 ready）。
- **顺手**：根目录 `AGENTS.md` / `CLAUDE-FABLE-5.md` 是 Claude 模型系统提示词（不是 ReSETP 项目说明）。Codex 按惯例读 AGENTS.md 会读到无关内容——考虑给 Codex 建一份真正的项目 AGENTS（指向本 HANDOFF），或在每条提示词显式写"先读 HANDOFF.md"。

## 7. 记忆快照
`docs/handoff/memory/` = M1 上 Claude 私有记忆（`~/.claude/.../memory/`）的快照，随仓库走。含 `MEMORY.md`（索引）+ project-plan-overview / baseline-algorithm-catalog / alns-crush-root-cause / algorithm-pivot-ca-alns / figure-redesign-task / deferred-instance-robustness / feedback_communication_style。深细节看这里。
已写好的两条 Codex 提示词（①离线探针 ②8基线复刻）应存到 `docs/handoff/codex_prompts/`（待补）。

## ⚠️ 工作顺序（单盘物理迁移 = 串行，必读）
仓库在外置盘上，盘在哪台机、另一台就停（含 M1 上正在跑的 E1-E7）。GitHub 备份只有 46M 代码+文档，**没有大数据/instances/reports**，所以 Windows 机不能靠 GitHub 独立干完整实验。因此严格串行：
1. **先在 M1 跑完**：E1-E7 重跑（进行中）+ 轨② 基线提速与正式对比（canonical 数字）。
2. **再移盘到 Windows**：装环境 → DR 课程训练（相对 % 报，不与 M1 绝对值比）。
3. **迁回 M1**：整合 DR 结果。

## 变更日志（每次对话/决策/Codex run 追加一行）
- 2026-06-20 建本文件；记忆快照入 `docs/handoff/memory/`。探针 PROMISING（r2_delta≈1.05）；8 基线 HALT_BASELINE_THROUGHPUT。提出迁移策略（M1 canonical + 3060 训 DR）。
- 2026-06-20（续）user 确认：GPU 机 = Windows 5800H，外置盘 exFAT 直插 Windows 干活，训完迁回，授权上 GitHub。已建私有备份 `github.com/zlxshu/ReSETP`（46M 快照 = 代码+文档+记忆；大数据/reports/venv 不在内，留盘上）。清理 .git 内 AppleDouble 垃圾。确立"单盘=串行"工作顺序（见上）。handoff 文档已提交进盘上仓库（commit 38e6356）。
- 2026-06-20（续2）写了轨②提速提示词，三条 Codex 提示词存入 `docs/handoff/codex_prompts/`（01 探针 / 02 基线 / 03 提速，+ README）。
- 2026-06-20 E1-E7 进度快照（user 报）：~51/60 单元、414/470 记录、0 失败；E1 完 / E2 ~130-140 / E3 52-60 / E4 135-160 / E6 58-70 / E7 9-10；剩 E4 网格 + E6 theta + E3 长尾；6 worker。ETA 纯算 2-4h + 收尾（合并 manifest / export-backfill / 修正文碳段 / 查表图 F4 / solver+RL 测试 + commit）1-2h = 整体 3-6h。不降规格、不混旧数据。**下一步：在 M1 跑完 E1-E7 + 发提示词③做轨②正式对比，再移盘 Windows 训 DR。**
- 🎯 2026-06-20 **E1-E7 大重跑完成（commit `9da7f8b`）= 论文正式数字锁死**：471/471 零失败零违约；£4878 锚精确复现；T3-T9 + F1-F6/F5b 重生成（F4 修好）；碳段 →2330.7 kgCO2e；latexmk 过；solver166/RL102 过；保护文件未动。**M1 现已空闲 → 下一步发提示词③做轨②基线正式对比，再移盘 Windows 训 DR。** 未 push（GitHub 备份待刷新）。
- 🖥️ 2026-06-20（Windows 机接手）**外置盘已直插 5800H+RTX3060 6G，仓库在 `H:\ReSETP`**。Claude 只读环境探针结果（未安装未跑项目代码）：
  - **GPU**：RTX 3060 6G，驱动 596.21，CUDA 13.2，可用（当前仅 Zotero/Claude 占 844MiB）。PPO 网络小（11-19 维 obs+小 MLP），6G 够；真瓶颈是 CPU 样本效率（1 episode=16000 eval=一整轮 ALNS）。
  - **现成 Python**：PATH 默认 `python`=3.14.3；`D:\Anaconda\python.exe`=**3.14.3 + numpy 2.4.4**；`conda` 命令坏了（`No module named 'conda'`，环境管理用不了）。**3.14 太新，torch+CUDA 轮子大概率还不支持** → PPO venv 建议用 Python 3.12/3.13。
  - **⚠️ 致命坑②实锤（硬编码 M1 路径，会拦死训练）**：`train_async_block_ppo.py:24`/`second_layer_debug.py:23`/`report_pilot.py:13` 硬编码 `SYSTEM_WORKER_PYTHON="/opt/anaconda3/bin/python3.13"` + `SYSTEM_WORKER_NUMPY="2.3.5"`；`worker_client.py:206-207` 回退候选是 `/opt/anaconda3`、`/opt/homebrew` 等 Mac 路径。多处强校验 `SETP_WORKER_PYTHON must be {required}`（train_async_block_ppo.py:703 / offline_bandit.py:914 / second_layer_debug.py:772 / diagnose_pilot_failure.py:498）在 Windows 必然报错。`train_async_block_ppo.py:720` 有 `--required-worker-python` CLI 覆盖可绕过，但 offline_bandit 等是否可覆盖待查。**需 Codex 把这些 M1 硬编码参数化（指向本机 Python），属 RL lane 代码、未碰 cost/check/evaluation 保护文件。**
  - **未发现现成 RL venv**（`solver/rl/.venv` 不存在）。
  - **环境策略（Claude 建议，待 user 拍板）**：本机只报相对%、所有对手（winner/AlphaUCB/SA/random/PPO）同环境跑→漂移自抵消，故**建议本机统一单环境**（一个 Python 3.12 venv：torch+CUDA + numpy + 可编辑装 setp_solver；`SETP_WORKER_PYTHON` 指它自己），比 M1 的"双环境"更干净、最省跨环境漂移；唯一硬要求=**本机内部确定性**（同种子同结果，用前先验）。不必复刻 M1 的 numpy 2.3.5。
- ✅ 2026-06-20（Windows 环境搭建完成，Codex commit `b6b984df`，**未训练**）：user 先前已下发"环境 audit+搭建"提示词给 Codex（要求双环境），Codex 完成：
  - **solver worker 环境**：`C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe` = Python 3.13.12 + numpy 2.3.5 + scipy 1.18.0（注：numpy 对齐了 M1 金标准，但 x86≠ARM 仍不能比绝对值）。`SETP_WORKER_PYTHON` 已写入用户环境变量指向它。
  - **PPO/CUDA 环境**：`C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe` = Python 3.12.13 + numpy 1.26.4 + **torch 2.5.1+cu124（CUDA 12.4，cuda.is_available()=True，RTX3060 Laptop）** + gymnasium 1.0.0 + SB3 2.4.1。
  - **确定性**：verify_20251113 / seed7 / budget32，连跑两次均 £1013.534044477906、路线签名一致 → 本机内部确定（**仅证串行小 case；并行 async 训练下的确定性须另验**）。
  - **Windows 坑已修**：git core.autocrlf=false；清掉 .git/objects/pack 的 AppleDouble `._*.idx`（non-monotonic 警告消失）。commit `b6b984df` 把 DR 入口里硬编码的 `/opt/anaconda3/bin/python3.13` 默认改成优先读 `SETP_WORKER_PYTHON`，并修 Windows 反斜杠导致的 async report 路径校验误判；未碰 cost/check/evaluation。测试 test_async_block_ppo 7 passed、metaheuristic_baselines OK。默认 `python` 仍是坏 conda 的 D:\Anaconda 3.14.3，禁用，一律显式走两个 venv。
  - **🧠 Claude 把关判断（关键，单/双环境之争的真相）**：我先前建议"单环境"是为了"一杆秤"（所有对手同环境算成本→相对%可信）。Codex 按先前提示词建了"双环境"，但**双环境在本机同样满足"一杆秤"**——因为 RL env 的算子执行全部经 `WorkerClient`→子进程→`SETP_WORKER_PYTHON`(py313) 计算（block_env.py:10/40 用 WorkerClient；baselines.run_official_winner_kernel:199 也用 worker_python 子进程）。torch venv(py312) 只当"大脑"，**不计算任何解的成本**。故 AlphaUCB（run_alpha_ucb_env_policy 走 env）、DR（run_ppo_block_policy 走 env）、official winner（worker_python 子进程）三者都在 py313 一杆秤上 → 相对比有效。**判断=保留双环境，不重建**（py312+torch2.5.1+cu124 是成熟组合，硬塞单环境反而 numpy 版本会和 torch 打架）。
  - **⚠️ 残留漂移风险（写进训练/评测验收）**：`run_alns_wouda_strengthened`(baselines.py:282) 用 `[sys.executable]` 子进程跑——若从 torch venv(py312/numpy1.26.4) 调用就**不在 py313 一杆秤上**（旧 M1 trap 同型）。这是冷门"强化 ALNS-Wouda"基线、非核心 DR-vs-AlphaUCB-vs-SA 对比。**铁律：最终上报的 DR/AlphaUCB/SA 对比，每个对手成本必须经 py313 worker；SA(fair-SA)的解释器路径须在评测前确认走 py313，任何 sys.executable 路径要审。**
  - **🖥️ GPU/CPU 利用（回应 user "别全让 CPU 干"）**：DR-ALNS 是 learning-to-search，策略网是小 MLP（~19维obs+MultiDiscrete头）→ GPU 必然只占小头，这是架构本质（也是论文卖点：保 ALNS 质量、只学自适应），强行做大网不会加速训练。**真加速杠杆=CPU 并行**：`train_async_block_ppo.py` 是异步 PPO，可在 16 线程上并行跑多个 ALNS rollout worker（每个 worker 纯 CPU/numpy 无 torch，不抢 6G 显存）→ 直击"1 局=16000eval、样本效率低=天级"瓶颈。计划：训练用并行 async（worker 数按 16 线程+16G 内存调，防 OOM）；GPU 跑策略网；**最终上报的对比评测改用受控串行、保确定可复现**。
- 📋 2026-06-20（Claude 读训练码 + 写 Prompt A）：user 拍板 ①本机环境=保留 Codex 的双环境（不重建，理由见上方把关判断）②DR 第一版=**先跑小 pilot 验路子**（非直接大规模）。Claude 精读 `block_env.py`/`action_space.py`/`async_block_policy.py`/`train_async_block_ppo.py`/`worker_client.py`/`bundle_manifest.py` 后定论：
  - 动作空间 `BLOCK_ACTION_NVECS=(7,4,5,4,4)`=destroy(6算子+alpha_ucb)/repair(3+alpha_ucb)/q(5)/threshold(4)/exploration(4)。obs=19 维。
  - **课程/掩码/shared-baseline 三件套代码里都还没有**（`curriculum_training_plan.md` 是"待建"清单）：`_reward()`(block_env.py:70)单一无分阶段；policy 无掩码接口；`flatten_episodes()`(:161)全局标准化无按 bundle 分组。
  - **训练清单已干净**：`training_bundle_manifest.json` train=E-UK100_02/三班-150/三班-200，held_out=100_03，formal=100-01/L-main；`bundle_manifest.validate_manifest` 硬禁玩具题(verify/demo/E-UK25)+禁 100-01 泄漏。三班 150/200 算例已存在。历史"误用玩具题"坑已堵。
  - **当前异步训练器压根没用 GPU**（model 全程 CPU），且 `_cpu_probe_row()`(:546)用 Unix `ps` → Windows 失效。`self-check` 子命令已有把关闸（worker=py313 / numpy=2.3.5 / 零违约 / busy_ratio≥0.60）。并行=`ProcessPoolExecutor(num_actors)` 默认 6，可上调（测 RAM 防 OOM）。
  - **小 pilot 拆两条 Codex 提示词**（省 credits=烧训练算力前先验新代码）：**Prompt A**=建三件套+修 Windows 并行监控(psutil)+GPU 接管梯度更新+单测+self-check+极短冒烟（只验机制：阶段切换/掩码命中率/零违约/并行/内存/内部确定性），**不下性能结论**；已写入 `docs/handoff/codex_prompts/04_dr_curriculum_pilot_build.md`，待 user 发 Codex。**Prompt B**（A 机制验过再写）=跑真小 pilot + 100-01 上 DR vs AlphaUCB vs SA 相对%评测，无增益诚实 HALT；时长按 A 测出的并行速度定。
  - **残留待办/盯防**：HANDOFF 有未提交改动（让 Codex 随下批 commit + 刷新 GitHub 备份）；最终评测须确认 SA/fair-SA 也走 py313 worker（防 `run_alns_wouda_strengthened` 式 sys.executable 漂移）。
- ✅ 2026-06-20（Codex Prompt A 机制搭建 + 验证完成，**未跑真 pilot、无性能结论**）：
  - 分阶段 commits：`77200af8` audit + Windows psutil probe；`b17ac8e5` curriculum phases/controller/CLI；`c89f2ed8` action mask + policy mask plumbing；`550a7819` shared baseline + `--device auto|cpu|cuda`；`90ea6670` Windows RL validation guards + PPO requirements pin；`5f870000` actor rollout RNG seeding for single-actor determinism。
  - 环境锚：PPO venv `C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe` = Python 3.12.13 + NumPy 1.26.4 + torch 2.5.1+cu124 + CUDA available=True + sklearn 1.5.2 + scipy 1.14.1 + psutil 7.2.2；worker `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe` = Python 3.13.12 + NumPy 2.3.5；GPU probe = RTX 3060 Laptop 6G。
  - 验证：`solver/rl/tests/` = **110 passed**；`test_async_block_ppo.py` = 15 passed；最终 self-check `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/self_check_final_seeded/` = `PASS_ASYNC_SELF_CHECK`（12 episodes、零违约、worker py313/numpy2.3.5、busy_ratio≈0.700）；内部确定性 mini-check `determinism_c` vs `determinism_d`（num_actors=1、seed=123）首个 episode `reward_sum` 与 `best_obj` 逐值一致。
  - 短冒烟 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/smoke_final/`：参数 `--num-actors 12 --eval-budget 256 --block-size 16 --timesteps 384 --rollout-min-episodes 4 --phase-min-episodes 4 --device auto`；阶段切换 route→energy→carbon→dynamic；37 episodes、384 valid steps、零违约、reward finite、device=`cuda`、shared baseline enabled；destroy-head mask invalid rate 约 0.241-0.411；throughput final busy_ratio≈0.838、episodes_per_hour≈127.84、worker_failure_count=0；psutil 66 samples、max total_worker_pcpu≈1130.7、max worker RSS≈505.8MB、probe_error 空。
  - Windows 坑：本会话 shell `workdir` 会落回 `C:\`，实际命令用 `git -C H:\ReSETP` / `Set-Location -LiteralPath`；PPO venv 初始无 pip，`ensurepip` 后首次装最新版 sklearn 拉到 NumPy 2.4.6 与 SB3 冲突，已修回 NumPy 1.26.4 并 pin `scikit-learn==1.5.2`/`scipy==1.14.1`；Windows path 分隔符修了 offline bandit/probe guards；测试夹具去掉 `/opt` worker 硬编码；`operator_manual` 的 `id(instance)` cache 加节点签名，防测试间 stale depot；actor 子进程按 episode seed 设 torch/NumPy RNG。
  - 报告：`solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/prompt_a_mechanism_validation_report.md`。Prompt B 建议：可从 12 actors 起步继续真小 pilot，继续采 psutil；GPU 只承担 PPO update，CPU rollout 仍是瓶颈；所有 DR/AlphaUCB/SA 相对%必须同在本机 py313 worker 成本口径内，绝不和 M1 绝对数横比。
- 📋 2026-06-20（Claude 核 Prompt A 报告 + audit + 写 Prompt B）：Claude 亲读报告与 audit，判定**机制真过关非表面**（掩码命中率 0.24-0.41 真在动、确定性 reward+best_obj 逐值一致、四阶段按"够 episode+零违约不退化"真切换、GPU 接管更新、worker 全程 py313；Windows 三个真 bug 修了）。从 `async_pilot/audit/audit.md` 得三条定计划的事实：
  - **碳信号是真的**：worker `metrics` 含两层碳 `E_cv_direct/E_ev_indirect/E_total`+`cost_carbon`+`carbon_quota_kg` → 碳阶段真信号。**但公平/动态在 block 响应无信号**（无 profit-by-depot/无动态字段）→ 诚实课程表=**route→energy→carbon 三阶段**，公平/动态不进 block 课程（由最终 cost.py 评测与 E7 运行时承担）。
  - **冒烟 RAM 数据不算数**：smoke 是玩具预算(eval_budget=256/block16)，max worker RSS 仅 505MB、探针见最多 24 worker 进程（12 actor 切换重叠）。真 pilot(16000eval+真算例+block128)内存大得多，**Prompt B 必须先在真实设置重测 RAM 再定 num_actors**，不能信"没逼近 14GB"。
  - **评测口径命门**：`evaluate_policy.py` 算法集**不含 SA**（只有 ppo_block/alpha_ucb_block/alpha_ucb_env/random_block/official_winner_kernel，全 py313 worker）。**SA 须另从 solver `alns_crush_v2.run_task1`(scikit-opt-SA, py313, 16000eval, 暖启动) 取**，才能和 DR/AlphaUCB 同一杆秤。Prompt B 写死"每行 worker=py313 核验 + 不评 alns_wouda_strengthened"。
  - **Prompt B 已写入 `docs/handoff/codex_prompts/05_dr_curriculum_pilot_run.md`**（待 user 发 Codex）：阶段0 真实设置资源探针+加周期 checkpoint→阶段1 有界限小 pilot(route,energy,carbon / masks / shared baseline / device cuda / 默认目标墙钟≈2-3h 可中断)→阶段2 100-01+held_out 评 DR vs AlphaUCB(block/env)/SA/random 相对%(全 py313 核验)→阶段3 PROMISING/WEAK 判决(只相对%, 不与 M1 横比, WEAK 则诚实止损 DR=future work)。主判据=DR vs AlphaUCB(block)。pilot 时长=2-3h、评测 seed=5（user 确认）。
- ⛔ 2026-06-20（Codex Prompt B 阶段0 实测后 `HALT_RESOURCE_PROBE`，**未训练未评测无性能结论**，commits `41eba3c0`/`401953f4`/`7814cf72`，测试 19/114 passed）：**关键硬事实=全预算 DR 训练在本机不可行（迁回 M1 也要知道）**：
  - **单局墙钟（16000 eval，12 actors 竞争 8 核/16 线程下）**：100c(E-UK100_02) **均 5122s≈85 分钟/局**(min4439/max6013)；150c(三班-150) **均 15078s≈4.2 小时/局**；200c(三班-200) **一局未完**。RL 要成百上千局 → 全预算训练=几天到跑不动（HANDOFF 早警告"几千局=几千万步=几天算力"，现被实测坐实）。
  - **内存**：12 actors 峰值 system used **14.16GB**、available 低至 **2.07GB**(87.2%)，越过计划 12GB 安全线。**主因仍是单局太慢**，内存只是雪上加霜（注：每个 actor 子进程在 Windows spawn 下各自 import torch≈内存大头；future 优化=actor 用 numpy 前向、不载 torch，可大降内存让 16 线程真并行——本 pilot 不做）。
  - 吞吐 final **2.26 episodes/hour** → 2-3h 仅 ~6-7 局，达不到 12 局底线、走不完 route→energy→carbon。Codex 还修了"超额提交 actor episode、到点仍空等"的 bug(`401953f4`)。
  - **Claude 判断（纠正先前"内存thrash"猜测）**：瓶颈是**单局原生耗时**非纯内存。**唯一能在本机出学习信号的配置=降 eval budget(如~3000)+只用最快 bundle(100_02)+降 actors 到 6-8 的"趋势 pilot"**（同降预算下 DR vs AlphaUCB vs SA 相对%仍有效，诚实标注"reduced-budget trend pilot 非全预算"）。Option2(更长墙钟+少 actors)即便过夜也仅~50-60 局且 150/200 无望；Option3(止损 DR=future work)是诚实退路但**在试过 reduced-budget 前过早**。**战略提示(待 user)**：若 reduced-budget pilot=PROMISING 而论文需全量训练，本笔记本与 M1(8G RAM 更紧)都可能不够→需讨论云端 GPU/CPU。已 ask user 选 scope；新提示词(06)按所选 scope 写。
- 🧭 2026-06-20（user 战略决策：两条工作线并行 + Scheme 3 迁移）：
  - **两条线并行**：①**x86(本机)=长期 DR-ALNS 训练机**（DR 是面向未来工作的长期追求）；②**M1=论文刚需保底**——轨②的 8 个 ALNS 文献基线对比(现 HALT 在 throughput, 提示词 03 已草) + 图表壳复印。ALNS 是现阶段论文刚需，至少做好保底；DR 是上限/future work，不卡论文。
  - **user 工作纪律(新, 通用)**：DR/ALNS 碰到卡点/瓶颈/进度慢，**先上网 + 翻 Zotero 文献找现成解法，别重复造轮子**（"我们碰到的问题大多前人早研究透了"）。已记入 [[feedback-communication-style]]。**眼下"训练太贵"卡点的文献解=Daysalilar 课程 DRL 在小算例(N=10)训→零样本泛化大算例(N=100)**（见 [[baseline-algorithm-catalog]]）→ x86 DR 应"小/快设置训练、全预算只评测验泛化"，非 85min/局硬灌。
  - **迁移=Scheme 3（user 选定，比其原方案省一次大盘往返+M1 停工）**：关键事实=`.gitignore` 排除 `models/`+`solver/reports/`+`*.npy`（算例/DR报告/模型都不在 GitHub），但 **DR 产出极小**(模型~几十KB + 几个CSV/MD)→不必倒腾大盘回来，U盘/网盘/`git add -f` 即可。流程：①现在 push 刷新 GitHub→②整盘复制到 x86 本地 `D:\ReSETP`(先验 D 盘空间)→③验 x86 脱盘能训(self-check from D:, 注意 venv 勿 editable 钉在 H:)→④拔盘单程去 M1 并留在 M1(M1 拉 GitHub 跑轨②+图表)→⑤x86 在 `dr-x86` 分支训 DR, 代码 push GitHub、小产出 U盘/`git add -f`→⑥M1 拉 dr-x86 整合。大盘全程不回 x86。
  - **下一步**：提示词 06=x86 迁移准备(push+复制到D:+脱盘验证, 不训练不删 H:)；之后 x86 跑 reduced-budget DR 趋势 pilot；M1 那条线另写(轨② 03 提速 + 图表)。
- ✅ 2026-06-20（Codex 提示词 06 迁移准备完成，**未训练、未删 H:**）：GitHub push 成功，分支 `codex/reporting-pipeline` HEAD=`5ad097e8ededcaded97d7a7001ccdfb158588864`（两机以后靠它同步代码）。整仓复制 `H:\ReSETP`→`D:\ReSETP`（源 2.64GB，robocopy exit 0 无失败，D 盘复制后剩 103.65GiB）。`D:\ReSETP` 是有效 git 仓库(远程仍 zlxshu/ReSETP, autocrlf=false)。**脱盘 self-check 在 D 盘 PASS_ASYNC_SELF_CHECK**(4 episodes/零违约/worker py313/numpy2.3.5/busy0.66)；脱 H 核查通过：repo_root/PYTHONPATH/worker import 全指 `D:\ReSETP`，无 editable 钉在 H，无 H: 路径回落。**大盘可安全拔去 M1。**
  - **🔀 两机分工 + 分支约定（防分叉，关键）**：**x86 在 `D:\ReSETP`、开 `dr-x86` 分支**只动 DR lane(solver/rl/)；**M1 在大盘、留 `codex/reporting-pipeline` 分支**做轨②(ALNS 基线)+图表(动 solver/src 基线代码、reporting、docs 图表)。两边代码经 GitHub 同步(push/pull 各自分支)。DR 小产出(模型.pt+相对%报告)经 `git add -f` 或 U盘传，大盘不回 x86。**HANDOFF 变更日志冲突**：x86 的 DR 条目标 `[x86/DR]`、M1 标 `[M1]`，合并时两边追加行都保留(Claude 在 merge 时reconcile)。两机不动对方的文件区，冲突面最小。
  - **并行下一步**：①**x86**=提示词 07(reduced-budget DR 趋势 pilot, 在 D:\ dr-x86 分支)；②**M1**=拔盘到 M1 后开新会话, M1 的 Claude **先读本 HANDOFF**, 接手轨②(提示词 `docs/handoff/codex_prompts/03_baseline_speedup.md`)+图表壳复印(`docs/handoff/memory/figure-redesign-task.md`)。
- 🛑 2026-06-20（Codex Prompt B 阶段0 真实资源探针 HALT，**未跑 pilot/未评测/无性能结论**）：新增并提交 `--checkpoint-every-updates` + 系统内存探针（commit `41eba3c0`，RL tests 113 passed），随后修复训练器尾部过量提交导致到点后等待多余长 episode 的问题（commit `401953f4`，RL tests 114 passed）。真预算 12 actors 资源探针 `prompt_b_resource_probe_12/` 跑 `eval_budget=16000/block_size=128/timesteps=1536`，完成 13 episode、零违约、worker 全程 py313/numpy2.3.5，但系统内存 used 峰值≈14.16GB、available 最低≈2.07GB，且吞吐仅≈2.26 episodes/hour；按锁定的 2-3h pilot 只能完成约 6-7 episode，不足 12 episode 底线、也不足以可靠走 route→energy→carbon。已停止残留 worker，报告 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/prompt_b_halt_resource_probe_report.md`。下一步必须显式改 scope：降 eval budget/只用快 bundle 做趋势 pilot，或放宽到更长墙钟并降 actors 到 8/6，或停止 DR pilot、保留 Prompt A 机制证明。
- [M1] 2026-06-22（09c E2 ALNS SA acceptance gate HALT，**阶段③④⑤继续停止**）：commit `df608660` 已实现 E2 专用 SA acceptance + scan bridge runner，legacy `100-01` 锚精确不漂（mean `4878.331796187524`、seed2 `4779.053444002934`、zero violations、delta `0.0`），但正式 09c gate 未过。报告 `baselines/e2_alns/sa_acceptance_halt_report.md` 记录：135 row 中 100 row returned zero-violation finite solution，35 row `HALT_HARD_TIMEOUT`；200c vanilla/multidepot 上 LNS 与两种 SA-ALNS 全部 timeout，threeshift-200c 上 ALNS 也有 timeout。已确认 09c 不是可包装通过的结果，不能启动基线重做或 69 实例正式 T3。
- [M1] 2026-06-22（09d 吞吐根因计划锁定）：基于 `baselines/e2_alns/sa_raw_runs.csv` 独立复核，threeshift completed rows 显示 LNS 约 `87/52/33/18/11 evals/s`（50/75/100/150/200c），`alns_sa_lns_cooling` 约 `109/54/11/12/6 evals/s` 且方差大；ALNS 在 50/75c 能跑够迭代时追平/赢，但 100c+ 明显迭代不足。当前工作假设从"SA 不够"更新为"每步太贵导致迭代饿死"，下一步只做 09d：先 profile、再做最小工程提速、修 timeout 返回 incumbent，真实墙钟 gate 仍必须赢稳 LNS 才能继续。若提速到 LNS 级吞吐后仍系统性输 LNS，则输出 `HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT`，交 user 决策，不再无限加料或退 DR-ALNS 救场。提示词已写入 `docs/handoff/codex_prompts/09d_e2_alns_throughput.md`。
- [M1] 2026-06-23（09e E2 算例/参数根因诊断启动）：09d 已产出 `HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT`，说明单纯吞吐/迭代饿死不足以解释 ALNS 输 GLNS/LNS；当前主线判断转为先审计算例经济口径：GLNS/LNS 在这些 E2 小门上本质吃到"全油车最优"盆地，而病根可能是 Goeke 物理参数（80kWh 电池、90km/h 速度）叠加 UK 2025 经济参数（公共快充/占用费）使 EV 在真实碳价 £50.34/t 下无经济性。09e 只做诊断：新增 `baselines/e2_alns/instance_param_diagnostic.py` + `baselines/e2_alns/instance_param_diagnostic.md`，全程 `carbon_price=0.05034` 钉死，只用 `dataclasses.replace(DEFAULT_PRICES, ...)` 做内存覆盖，不改 `prices.py`/bundle/`cost.py`/`check.py`/`evaluation.py`/算法语义；先 Phase0 证明覆盖能穿透 `evaluate/check/charging/run_alns_wouda`，再 Phase1 拆全油/全电/混合成本，最后 Phase2 扫电池、速度、公共电价、占用费单变量。阶段③④⑤继续停止，等 09e 说清"全油车退化"真因后再决定是否用非碳现实参数重标算例并回测 ALNS vs GLNS；winner 不放弃，也不把 GLNS 直接当底座。
- [M1] 2026-06-23（09f 大算例 all-CV 诊断修正）：09e 结果反证原假设过粗：小算例 `25c/50c` 在固定真实碳价下 mixed 已经 3/3 低于 cv_only，不能诊断"全油退化"；CV 碳也已确认正确计入（`E_cv_direct = fuel_liters * diesel_ef`，并入 `E_total * carbon_price`，不是漏算）。09f 已写入 `docs/handoff/codex_prompts/09f_largescale_allcv_diagnostic.md`，诊断对象改为 09d 中 LNS/all-CV 占优的大算例 checkpoint，且必须区分两种真因：经济/参数导致长路线 EV 被 80kWh 续航与公共快充/占用费压垮，还是 mixed 好解存在但大规模搜索不稳定。执行时继续全程 `carbon_price=0.05034` 钉死、只做内存 `dataclasses.replace(DEFAULT_PRICES, ...)` 覆盖、不改 `prices.py`/bundle/`cost.py`/`check.py`/`evaluation.py`/算法语义；100c/150c 若表现为 best mixed 已存在但 mean 输，应诚实写成搜索可靠性/方差问题，200c 才是优先判定经济参数真凶的主战场。
- [M1] 2026-06-23（Claude worktree 接手整理 + HANDOFF 单一事实源修复）：已核对主仓 `HANDOFF.md`、`.claude/worktrees/compassionate-lamport-ebd93b/HANDOFF.md`、09f/09g 提示词与 09f 报告；Claude 旧 worktree 里有一段未进主仓的 `[M1]` 战略链（09c/09d 双 HALT、GLNS/LNS 其实是无 EV/碳的通用纯路由基线、全油主导 regime 让 ReSETP 的碳/EV 感知搜索变成负担、Goeke 物理参数 vs UK 经济参数拆分、09e/09f 诊断演进）。本条已把其归并回主仓事实源；以后以主仓 `HANDOFF.md` 为准。限制：不可见 Claude UI 历史不能被 Codex 直接读取，本条只基于仓库文件、worktree 文件、用户粘贴内容与当前 appshot。
- [M1] 2026-06-23（09g 暂停为证据先行；速度/电池参数纠偏）：09f 的 40km/h fixed-replay 翻盘只是机制证据，不能直接证明主算例应改成城市配送速度。用户纠偏成立：当前大算例偏跨城/大区域，真实物流多数会走高速，`v_speed_ms=25.0`(90km/h)与 UK Strategic Road Network 2025 平均约 56.6mph≈91km/h 相容；40km/h 更像城市/local-A-road 场景。更可疑的是 `B_battery_kwh=80` 仍属 Goeke/Davis-Figliozzi 2013 口径，对现代中重型跨城配送可能偏小，但不能拍脑袋改。已新增 `docs/handoff/parameter_evidence_brief_20260623.md` 与 `docs/handoff/codex_prompts/09h_parameter_evidence_review.md` / `09i_evidence_bound_reopt_confirmation.md`：下一步先做 2020+ Zotero/文献/行业证据矩阵、路线 regime 审计、证据约束 fixed replay；只有证据成立且 near-flip/flip 的场景才做真实重优化。`09g_urban_reopt_confirmation.md` 保留但降级为“城市场景草案”，不得作为跨城主线直接执行。后续每轮 Codex 需读 `AGENTS.md`/`CLAUDE-FABLE-5.md` 的诚实/克制/反迎合原则（忽略 Claude 产品细节），宁可写 HALT，也不把 fixed replay 包装成重优化证明。
- [M1] 2026-06-23（09h 证据约束参数诊断完成，artifact commit=a0d5951be1aeae121bf4962d46607c4dbf881370）：新增 `baselines/e2_alns/parameter_evidence_review.py` 与报告/数据，严格不改 `prices.py`/bundle/`cost.py`/`check.py`/`evaluation.py`/算法语义，`carbon_price=0.05034` 全程钉死。Phase0 checkpoint/CSV 审计 30/30 OK；route-regime 审计把 100/150/200c best all-CV 与 best mixed 全部标为 `regional_cross_city_like`（p75 约 130-157km、max 237-285km），因此 40km/h 只保留为 urban/local fork，不作跨城主线。Fixed replay 显示 200c 在 280kWh 下仍 near-flip（E: +0.506%，H 60mph+280kWh: +0.327%），自动触发真实重优化；6 个强证据触发点（100/150/200c × 280kWh / 60mph+280kWh）均 seeds 1-5 跑满，30/30 reopt row `OK`、零违约、无 `HALT_REOPT_COLLECTION_COST`。结论 `HIGHWAY_BATTERY_UPDATE_SUPPORTED`：保持跨城/高速 regime、不改碳价时，现代配送车 280kWh 电池足以让 mixed/EV 方案在真实重优化中跨 100/150/200c 明确优于 all-CV fixed reference（200c E_distribution_truck_280 mean 8616.45 vs all-CV fixed 8979.13，mean gap -4.04%，EV routes mean 67.2）。下一步不是立刻改 `prices.py`，而是走 09i/参数正式化：确认 280kWh 与当前车辆质量/固定费/载重口径是否作为主场景标定，或作为 modern-battery scenario 分表呈现；随后再回测 ALNS vs GLNS/LNS 正式 T3。
- [M1] 2026-06-23（09i/09j 参数正式化：默认电池 80→280）：按 09h `HIGHWAY_BATTERY_UPDATE_SUPPORTED` 结论，正式将 `solver/src/setp_solver/prices.py` 的 `B_battery_kwh` 从 Goeke/Davis-Figliozzi 2013 原值 80 kWh 提升为现代中型电动配送卡车证据约束下界 280 kWh；保留 `v_speed_ms=25.0`(90 km/h)、`carbon_price=0.05034`、公共/车场电价、占用费、固定费、`cost.py`/`check.py`/`evaluation.py` 与算法语义不变。`docs/paper_submission_final/paper_main.tex` 参数表和表下注释同步说明 Goeke 原值与 Volvo FL/FE 280 kWh 证据边界。旧 09e/09f/09h 报告和既有图表仍是历史产物；后续 T3/正式表图必须在新默认参数下重跑后再引用。
