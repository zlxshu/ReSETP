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
