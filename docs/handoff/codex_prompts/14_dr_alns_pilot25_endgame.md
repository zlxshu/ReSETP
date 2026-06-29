# Codex 提示词 14 — Pilot25「DR-ALNS 终局」（满配·吃透·双保险·自动过夜）

> Claude 写定（2026-06-28）。前 5 轮(Pilot20-24)只证明了"RL 在**弱通用算子**里**挑算子**≈调好的 ALNS(+1~2%)"，但**从没**：①给 DR 用仓库里验证过的**强招式**(charging/local_search/fairness/SISR/carbon-aware)；②试文献里真正赢的**学习变体**(NLNS 学修复 / NeuOpt 学 k-opt / 高杠杆碳感知时刻)；③**练够**(只 250)；④**逐行吃透**别人源码。本轮把这些全补上，给 DR 满配真机会；**且设计成双保险——不管 DR 成不成，都拿到"对弱场领先 10%"的可发表结果**。冷启动、自包含、自动过夜。

## 0. 诚实边界（写在最前，不许吹）
不保证 DR 达 10%：富问题 eval 贵、到不了 POMO 千万级数据、富约束泛化是公认难题(ACM *Applicability of NCO: A Critical View*)。本方案保证的是：**给 DR 满配机会 + 无论成败都给可发表结论**。判级诚实，禁止把过拟合/欠训当 PASS。

## 1. 绝对边界 + 过夜铁律（沿用 `10_*.md` §9 全部）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py` 语义(只读/只调用/只新增)；worker py313+NumPy2.3.5；runner py312 cu124；只 x86 同机相对%；飞行前检查；周期 checkpoint + resume guard(禁 `--resume` 绕 HALT)；全局墙钟（本轮放宽到 ≤8h，到点停在 checkpoint 出报告）；防 OOM；**禁过夜 push/rebase**(dr-x86 留人工 reconcile)；只 force-add 小产物；增量 `pilot25_progress.log`；同阶段连续 3 次自修失败→升级架构问题写诊断停；每改动记"症状→出处→改哪→为什么"。保留 Pilot22-24 已生效：POMO shared baseline、5/3/1/0 reward、target-KL early stop、LR 退火、validation-cost 判据、best-val checkpoint、fresh-per-batch、训测同规模不重叠。

## 2. Stage 0 — 吃透别人 + 接上强招式（先做，补齐前几轮没做的）
**(a) 逐行吃透赢家源码并产出实证清单**：读 `Reference Algorithm/` 下 Cao DRL-ALNS-EVRP(`net/dqn.py`/`alns/ALNS.py train_dlns_multi`/`TEST/EVRP.py` 的 RH 充电与 SISR)、N-Wouda ALNS；GitHub/arXiv 读 **NeuOpt(yining043/NeuOpt: 学 k-opt S/I/E-move + GIRE)**、**NLNS(ahottung/NLNS: 学修复)**、**POMO**(shared baseline)、**Learning-to-Delegate / GLOP**(大规模分解)。产出 `pilot25_absorption.md`：**"它们凭什么赢 / 我们漏了什么 / 本轮采纳哪几条"**（具体到机制，不空话）。
**(b) 给 DR 接上仓库已验证的强招式**(替掉烧火棍)：把 `charging.py`(充电插入；若为启发式，按 Cao RH/FRVCP 思路升级为更优插入)、`local_search.py`(2-opt/or-opt 抛光)、SISR/`route_segment_removal`、以及**碳感知/公平感知**(`fairness.py`/碳时隙)算子，接进 learned 环境的破坏-修复闭环；与对照组**同口径共享**(防变量不干净)。
**闸 G0**：强招式接通 + 相关 targeted tests 过 + `pilot25_absorption.md` 写完 → 过。

## 3. Stage 1 — 真正的学习变体 + 好课程 + 练够
**(a) 学习变体**(按 Stage0 实证选，至少一种"非挑算子"的真变体)：① **碳感知时刻控制**=DR 学"何时/在哪充电与出发以咬住电网清洁时隙"(你独有结构、最高杠杆，周鲜成同思路上顶刊)；②（可选，按 absorption）**学修复/学 k-opt 影响**(NLNS/NeuOpt 式)。**不再只做"挑算子"。**
**(b) 好课程**：Daysalilar 式 **小→大** 课程(先 25c 学会、再 50c)，route→energy→carbon 阶段；fresh-per-batch、同规模训测不重叠、完整 bundle(断言含 carbon_profile)。
**(c) 练够**：训练量提到**墙钟(≤8h)能跑的最大**(远超 250；周期 checkpoint、可中断续)。
**闸 G1**：在独立同规模 val 上 best-validation 改进达阈值(≥+3%)且**稳定保持**(KL ok、不回落超阈、零违约) → 过；否则 `HALT_NO_VALIDATION_GAIN`+诊断(注明本轮已满配，故为更强证据)。

## 4. Stage 2 — 双重判级（终局·双保险）
best-val checkpoint 在**独立同规模 test**(与 train/val 全不重叠)上，**同预算同 worker py313**，对比三组：
- **(A) DR 增量**：learned vs operator-select vs **plain-ALNS**(基础破坏-修复，无强招式) vs random/worst_removal。
- **(B) 对弱场领先(论文 10% 目标)**：我们的强方法(强 ALNS±DR) vs **GA/PSO/蚁群(ACO)/水滴(IWD)/VNS**(用 `metaheuristic_baselines.py`，正常发挥不削弱；小规模 25/50c 上吞吐可行)。
- **(C) 近最优锚(可选)**：小规模(≤10c)对 CPLEX/精确(若可得) gap。
**判级(写死)**：
- `PASS_DR_BREAKTHROUGH`：DR 显著超 operator-select 与 plain-ALNS(如 ≥+5%) 且 方法对弱场 ≥+10% 且 零违约稳定 → **DR 真突破** → 全力 Phase B/写论文。
- `PARTIAL_WIN_NO_DR`：DR≈ALNS(小)，**但 强方法对弱场 ≥+10%** → **论文照样成立**(头条=富问题+机制+强 ALNS 碾弱场；DR 写成诚实 future-work) → 这是**不空手而归的保底**。
- `HALT_BOTH`：DR 没增量 **且** 对弱场也没拉开 10% → 诚实记录，回头查强招式/弱场口径(此时问题在非 DR 部分，需先夯实强 ALNS)。

## 5. 交付物
`pilot25_endgame_report.md/json`(吃透清单 + 强招式接通证明 + 学习变体与课程 + Stage2 三组对比 + 判级 + 人话"DR 成没成、对弱场 10% 拿没拿到、下一步")、`pilot25_absorption.md`、`pilot25_data_manifest.json`、`pilot25_update_log.csv`、`pilot25_test_rows.csv`(A/B/C 三组)、best-val ckpt。最终人话报：满配后 DR 到底成不成、论文的 10% 保底拿到没、DR 去还是留。

## 6. 资料顺序
先吃透(Stage0 absorption)→接强招式→好课程练够→双重判级。先证据后改、阶段带闸自停、不拍脑袋、不谄媚、不把欠训/过拟合当成功。
