# Codex 提示词 13 — Pilot24 学习型破坏「数据/泛化根因修复」（最后一次数据修·自动·过夜）

> Claude 写定（2026-06-28）。**Pilot20-23 的真根因已定位到数据，不是算法**：Pilot22/23 已修好训练动力学(POMO baseline + 5/3/1/0 reward + target-KL，KL 已稳)，能在训练/验证分布上学到 +12%，但**独立 test −17.7%**=过拟合+跨规模。原因：**只在 ~9 个固定算例上训、25c 训却 50-100c 测**，严重违反神经 CO 的数据要求(POMO/AM 在 ~1 亿个**每批新生成、同规模**算例上训)。本轮唯一目标=**满足数据要求后看它到底泛不泛化**。**user 已拍板：这是最后一次数据修，再不行就止损 DR 转 future-work。** 冷启动、本文件自包含。

## 0. 开工前必读
`HANDOFF.md` 2026-06-28 段(Pilot20-23 全链 + 数据根因) + Pilot22/23 产物与代码(`pilot22_*`/`pilot23_*`/`learned_destroy*`) + `models/src/setp_instance_lab/build_curriculum_instances.py`(生成器，写完整 bundle 含 carbon_profile，按 seed 参数化) + `docs/handoff/codex_prompts/10_*.md`§9(过夜铁律)/`11`/`12`(已落地的修法).

## 1. 证明逻辑链（执行者须理解，别跑偏）
P1 实测 val +12% / 独立 test −17.7% = 过拟合+跨规模；P2 文献 NCO 泛化需"大量·每批新生成·同规模"分布(POMO/AM ~1 亿新算例、同规模)；P3 我们 ~9 固定算例+跨规模 → 违反 P2；C 故失败是数据所致，修数据即移除成因；满足数据后仍不泛化=稳健真负→止损。**诚实边界：富问题 eval 贵、到不了 POMO 规模，故不保证 PASS，只保证"直击根因+必给定论"。** 来源：POMO NeurIPS2020、IJCAI2024 generalizable neural solvers、LEHD、Rethinking-NCO-constraint-tightness、ACM"Applicability of NCO: A Critical View"。

## 2. 绝对边界
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py`；worker py313+NumPy2.3.5(漂移 HALT_WORKER_INTEGRITY)；runner py312 cu124；只 x86 相对%；§9 过夜铁律全用(飞行前检查/周期 checkpoint+resume guard/墙钟≤6h/防 OOM/禁过夜 push·rebase/增量 `pilot24_progress.log`/连续3次自修失败升级诊断停)；只 force-add 小产物。**保留 Pilot22/23 已生效修法**：POMO shared baseline、5/3/1/0 reward、target-KL early stop、LR 退火、validation-cost G1、best-validation checkpoint、熵地板。

## 3. Stage 0 — 造充足且正确的样本（核心，先做）
- 用 `build_curriculum_instances.py`（或最小扩展）**按 seed 批量生成同一规模的新算例**：选**算力能扛的最小规模**（优先 25c；若 25c worker 太快/信号弱可用 50c，二选一、训测同一规模）。
- **三不重叠 seed 段**：`train` 池尽量大（目标数百~上千个 distinct，按吞吐定）、`val`(选 ckpt，~30)、`test`(报结果，~30-50)，**seed 区间互不相交**。
- **每个 bundle 必须完整**：飞行前断言含 `instance.json/distance_matrix.npy/carbon_profile.csv/scenario_manifest.json` 且 `validation.passed=True`；**任何缺 carbon_profile 的遗留旧 bundle(如 E-UK25_01)一律排除**。
- 记录 manifest（train/val/test 各自 bundle 列表 + overlap=false 证明）。
- **闸 G0**：train 池 distinct 数 ≥ 阈值(如 ≥200，按吞吐定)、三集零重叠、全部完整且 validation_passed → 过；否则 `HALT_INSUFFICIENT_DATA` 报原因。

## 4. Stage 1 — POMO 式 fresh-per-batch 训练（同规模）
- **每个 rollout/批从 train 池随机取新算例**（POMO fresh-per-batch；**严禁复用固定 9 个**），同规模；课程 route→energy→carbon、CUDA、周期 checkpoint、存 best-validation。
- 沿用 target-KL early stop + LR 退火 + POMO baseline + 5/3/1/0 reward。
- **闸 G1**：在 `val`(同规模、与 train 不重叠)上周期评，best-validation 改进达阈值(如 ≥+3%)且**稳定保持**(KL ok、不回落超阈)、零违约 → 过；若 val **无任何泛化改进趋势** → `HALT_NO_VALIDATION_GAIN`（数据修后仍学不到可泛化的）。

## 5. Stage 2 — 独立同规模 test 正式判级（决定性）
best-validation checkpoint 在 **`test`(同规模、与 train/val 全不重叠)** 上确定性评 vs operator-select / random / worst_removal，同预算 worker py313。
- `PASS_LEARNED_DESTROY`：test 平均 ≥+2%、稳超 random/worst_removal、零违约、worker py313/NumPy2.3.5 → **真泛化的正结果** → 绿灯 Phase B（FRVCP+碳感知+全规模+GA/PSO 擂台+精确解锚）。
- `WEAK`：0~+2%。
- `HALT_NO_GENERALIZATION`：≤0 → **数据做对了仍不泛化=稳健真负结果** → 按 user 拍板**止损 DR**，转 future-work（有干净的家：NCO 综述"富约束 VRP 泛化是开放难题"），论文主线锁回富问题 vs 弱场 + 机制。

## 6. 交付物
`pilot24_report.md/json`(逻辑链复述 + 样本 manifest+overlap 证明 + Stage1 val 曲线 + Stage2 独立 test 判级 + 人话"这对目标意味着什么、最终去留")、`pilot24_data_manifest.json`、`pilot24_update_log.csv`、`pilot24_independent_test.csv`、best-val ckpt。最终人话报：样本够不够/干不干净、同规模独立 test 上泛不泛化、判级、**DR 去还是留**。

## 7. 资料顺序
先读 HANDOFF+Pilot22/23 产物+生成器代码 + POMO/IJCAI2024/LEHD 数据-泛化做法，再单点改、阶段跑、带闸自停。不得用"我猜"替代查文献/读码。每改动记"症状→出处→改哪→为什么"。
