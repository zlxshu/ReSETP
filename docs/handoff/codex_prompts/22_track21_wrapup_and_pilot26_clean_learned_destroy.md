# Track22 终局大工程：Track21 收口 + 干净仪器上的 DR-ALNS 生死判（一次跑完所有分支，自动串行带闸，不回头）

> 本提示词以 user 对话中粘贴的版本为准；此文件是仓库存档副本。
> 性质：这是一次性的终局工程。所有分支的结局都已预判，跑到哪个分支就按哪个分支收口，禁止自行加码、禁止回头重试已判死的路线。

## 0. 冷启动必读 + 环境铁律（不读完禁止动手）
- 完整读仓库根目录 `HANDOFF.md`，重点变更日志：2026-06-30「根因翻案·车队 policy 漏传」、2026-07-02「Track21 执行进展」、2026-07-03「Claude 决策·跨机情报整合」。
- 机器：x86 5800H，仓库 `D:\ReSETP`，分支 `dr-x86`。
- 环境：算子/评测 worker 一律 `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`（Python 3.13.12 + NumPy 2.3.5）；PPO 训练用 `C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe`（torch 2.5.1+cu124，device=cuda）。`PYTHONPATH=solver/src;models/src;solver/rl`。
- 一切数字只报 x86 机内相对 %，绝不与 M1 绝对值同表。
- **禁改语义**：`cost.py` / `check.py` / `search/evaluation.py`。**本任务额外禁改** `metaheuristic_baselines.py`（M1 正在修它，x86 再动=第三个分叉）。
- 禁 push / rebase / prune；commit 留 dr-x86 本地。每个 Stage 完成即 commit 一次。
- 连续 3 次自修失败 → 停写诊断报告，不 blind 重试。过夜按 §9 铁律：飞行前检查、周期 checkpoint、防 OOM（系统内存超 12GB 就降 actors）、禁过夜 push、resume guard 禁止绕过 HALT 状态。
- 产物统一根目录：`solver/reports/dr_alns_ppo_v3/final_track22/`。

## 1. 背景（一段话讲清为什么）
Track21 修复了车队 policy 漏传 bug，winner 复活（100-01 vs SA +28.7%），25c 正式 10 seeds 公平对比显示对健康基线只领先 6.45%~8.27% → WIN_REAL(每基线≥10%)数学上已不可能，且基线仍带 M1 已数学证明的解码器缺陷（`_append_customer_to_cached_plan` 绝对距离比较，修复未移植到 dr-x86），这张表注定被 M1 修复后的正式表取代。同时 Track21 Stage4 官方确认 Pilot20-25 的 learned-destroy 负结论全部被同一 bug 污染（见 `solver/reports/dr_alns_ppo_v3/final_track21/track21_dr_contamination_report.md`）——**DR 学习型破坏的真实上限从未被干净测过**（Pilot22 在坏仪器上尚见 held-out +11.5% 验证峰）。本工程：收口 Track21，然后在干净仪器上一次性判定 DR-ALNS 剩余两个未知数（学习型破坏 headroom、碳感知时刻杠杆），每个分支结局预判、跑完即终局。

## 2. 判级总表（先读，所有分支的结局在此预判）
| 阶段 | 判级 | 后续动作（自动，不请示） |
|---|---|---|
| Stage0 Track21 收口 | `MARGIN_REAL_PROVISIONAL_X86` | 固定判级，进 Stage1 |
| Stage1 仪器健康闸 | PASS → 继续；FAIL → `HALT_INSTRUMENT` | FAIL 则全线停，写诊断 |
| Stage2 破坏杠杆探针 | ≥3% `DESTROY_LEVERAGE_CLEAN` → 进 Stage3；1~3% `LEVERAGE_MARGINAL` → 仍进 Stage3 但报告标注；<1% `NO_DESTROY_LEVERAGE_CLEAN` → 跳过 Stage3 直进 Stage4 |
| Stage3 learned-destroy 训练+判级 | ≥+2% 且每组≥0 且稳超 random/worst 且零违约 → `PASS_LEARNED_DESTROY_CLEAN`；0~+2% → `WEAK_LEARNED_DESTROY_CLEAN`；≤0 → `HALT_NO_GAIN_CLEAN` | 无论何值都进 Stage4 |
| Stage4 碳时刻杠杆探针 | ≥2% `CARBON_TIMING_LEVERAGE` → 训练；0.5~2% → `CARBON_TIMING_DIAGNOSTIC_ONLY` 不训练只记录；<0.5% `NO_CARBON_TIMING_LEVERAGE` → 不训练，记录"默认场景无碳杠杆=场景问题非算法问题" |
| Stage5 总判级 | Stage3 PASS（±Stage4 PASS）→ `DR_COMPETITIVE_CANDIDATE`（绿灯移植 M1）；仅一项弱正 → `DR_PARTIAL`；全 flat/no-leverage → `DR_CLEAN_NEGATIVE`（DR 定格 future-work，论文主线=M1 的 ALNS+机制擂台） | 写终局报告，工程结束 |

总算力预算：Stage0 等待不计；Stage2 ≤3h；Stage3 训练 ≤8h + 评测 ≤3h；Stage4 探针 ≤2h、训练（若触发）≤6h + 评测 ≤2h。全程 checkpoint 可断点续跑。

## Stage 0：Track21 收口（先做）
1. Track21 runner（07-02 21:04 启动的两个 python，输出 `solver/reports/dr_alns_ppo_v3/final_track21_reclaim/`）：若 50c 未跑满 seed901-910，等跑满；**50c 最后一行落盘后优雅停止**（等当前行写完 CSV，禁止 kill 半行）。若已进 100c，让当前行写完后停，已落盘 100c 行保留并标 `PARTIAL_NOT_CONCLUSIVE`。此后不再启动任何 100c 行。
2. 生成最终 `final_track21_reclaim/final_report.md`，判级 `MARGIN_REAL_PROVISIONAL_X86`，人话写清四点：
   - 25c 完整 10 seeds + 50c 全部已有 seeds 的分规模分基线均值差 + scipy Wilcoxon p 值；vs SA 的 +13.6%/+15.0% 单独列（SA 只是地板）。
   - 100c 标 `NOT_RUN_SUPERSEDED`（正式 100c 公平表归 M1 修完基线解码器+桥之后做）。
   - caveat 原文：本表基线仍带 M1 已证明的解码器缺陷，4-8% 是「对残障基线」的上界，不是论文数字。
   - 历史结论状态表：Track17/19 winner 系行 SUPERSEDED；Pilot16-25 全部「受车队 policy 污染、由本 Track22 复验」；唯一干净负结论=选算子范式≈调好的 ALNS（Pilot07-10 + Cao 源码）。

## Stage 1：仪器健康闸（几分钟，便宜）
用当前修复后代码在 100-01 seed901 跑 300-eval winner probe（与 Track21 复活探针同口径）。通过标准：best_cost 落 2500-2700 量级（warm≈4079）、`unique_solution_count≫1`、零违约、worker=py313+NumPy2.3.5。不过 → `HALT_INSTRUMENT` 全线停。

## Stage 2：破坏杠杆探针（干净重测，≤3h）
背景：Pilot21 Stage0 曾测出 best-of-k 比 operator-select 高 6.26% 的破坏杠杆，但那是坏仪器量的，必须重测；没杠杆则 learned-destroy 没戏，直接跳过 Stage3 不烧训练。
- 数据：用 `models/src/setp_instance_lab/build_curriculum_instances.py` 按新 seed 生成 fresh 算例（25c ≥3 个 + 50c ≥2 个，必须含 carbon_profile.csv 且 validation.passed=True；这批 seed 记入 manifest，后续 train/val/test 都不得复用）。
- 方法：复用 Pilot21 Stage0 的探针工具（best-of-k 破坏上界 vs operator-select，同预算同 warm start 同 evaluate/check，worker 走 Track21 修复后路径），每算例 ≥3 seeds。
- 判级见总表。杠杆值、逐算例数字写 `final_track22/stage2_destroy_leverage.md` + CSV。

## Stage 3：learned-destroy 干净训练+判级（仅 Stage2 有杠杆时进入）
目标：干净仪器上重答 Pilot24 想答的问题。所有部件都是现成代码，不新造算法。
- 数据（Pilot24 设计，细节见 `docs/handoff/codex_prompts/13_*.md`）：`build_curriculum_instances.py` 批量生成**同规模** 25c fresh bundle（吞吐允许再加 50c），train/val/test 三个 seed 段互不重叠，训练 fresh-per-batch，严禁复用固定几个算例，排除一切遗留旧 bundle（如缺 carbon_profile 的 E-UK25_01）。
- 配方（Pilot22/23 已实现验证过的稳定化件，全部启用）：POMO shared baseline、5/3/1/0 离散 reward、target-KL early stop、LR 退火、best-validation checkpoint 保存与选择。num_actors 从 6 起步，内存超 12GB 降。训练墙钟 ≤8h，checkpoint 可中断。
- 评测（独立同规模 test，同 warm start/预算/evaluate/check，每算例组 ≥5 seeds，Wilcoxon）：learned-destroy vs operator-select vs random-destroy vs worst_removal。判级见总表。
- 产物 `final_track22/stage3_learned_destroy/`（训练健康指标 KL/entropy/best-val 曲线 + 对比 CSV + 报告）。

## Stage 4：碳感知时刻杠杆探针（≤2h）+（仅 ≥2% 时）训练
背景：两层时变碳是本模型独有机制，是 DR 理论上的高杠杆旋钮；但 M1 09x 静态碳算子=WEAK，且默认 Goeke80 场景 EV 占比低，可能根本没碳可挪。先量杠杆再定。
- 探针：取 Stage2/3 产出的每规模 ≥5 个最终解，在**不改路线拓扑**的前提下，用现有充电机制（`charging.py` 的充电修复/插入）对充电时段做有界搜索（把充电动作在可行时窗内平移/重排，对着 carbon_profile 找最低碳成本时段），量「重排时刻能省多少总成本」。所有候选过真 `check_solution`、真 `evaluate`。同时报每解的 EV 里程占比（解释杠杆大小）。
- 默认 25/50c fresh 算例量完后，若杠杆 <0.5%，再对**一个** EV 权重更高的诊断性算例（用生成器参数造，标注 DIAGNOSTIC_ONLY，不进论文口径）重复探针，回答"是场景没碳可挪，还是机制本身没用"。
- 判级见总表。若 `CARBON_TIMING_LEVERAGE`（≥2%）：在 learned-destroy 同一套训练框架上加碳时刻控制头（动作=充电时段选择，观测已含 worker 的 E_cv_direct/E_ev_indirect/cost_carbon 字段），训练 ≤6h，评测同 Stage3 口径，对照=Stage3 最优配置（或 operator-select，若 Stage3 未跑），bar 同 ≥+2%。
- 产物 `final_track22/stage4_carbon_timing/`。

## Stage 5：终局报告（人话，必答清单）
写 `final_track22/final_report.md`，逐条回答：
1. Track21 最终判级与 caveat 落盘了没；100c 是否确实没再烧。
2. 仪器健康闸结果。
3. 干净仪器上破坏杠杆还剩多少（对比坏仪器时代的 6.26%）。
4. learned-destroy 判级 + 分组数字；碳时刻杠杆值 + EV 占比解释 +（若训练）判级。
5. 总判级（`DR_COMPETITIVE_CANDIDATE` / `DR_PARTIAL` / `DR_CLEAN_NEGATIVE`）+ 一句话回答「DR-ALNS 配不配当未来主算法」。
6. 历史结论最终状态表（哪些作废、哪些复验后确认、哪些是新结论）。
7. 若为 COMPETITIVE/PARTIAL：列出移植 M1 需要带走的最小文件/接口清单（不执行移植）。
最后在 `HANDOFF.md` 变更日志追加一条 run log，commit。
