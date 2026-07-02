# Codex 提示词 21 — Track21：彻底修复 winner-kernel 车队 policy 漏传 bug，并清算所有被污染的结论

> Claude 写定（2026-06-30），第一手读穿代码定位。**这不是验证式任务，是根因修复 + 全面清算任务。** 根因已认定（证据见下）：`winner_operators.py` 的 winner-kernel 主循环构造 `SearchPolicy` 时**漏传 `max_cv/max_ev`**，静默落到 `UNBOUNDED_FLEET`(100万)，导致修复算子无视真实车队上限(100-01 只有 10 CV+10 EV)疯狂新开路线，候选被 `check.py` 真实车队约束判违约、被接受准则全拒→跑满 16000 eval 仍 `unique_solution_count=1` 卡死。**目标：彻底修干净这个 bug 及其所有同类漏传点，让 winner-kernel 复活，然后把所有可能被此 bug 污染的对比结论全部重跑、作废旧数字。** 冷启动自包含、自动过夜、不谄媚、不拿旧污染数字当结论。

## 0. 根因认定（已由 Claude 第一手核实，无需再"验证是否存在"，只需锁死无第二坑）
- **BUG 点**：`solver/src/setp_solver/search/winner_operators.py` 第 ~656 行 `_run_winner_kernel_loop` 内 `policy = SearchPolicy(require_charging_signal=config.require_charging_signal)`——**未传 `max_cv/max_ev`**。类默认 = `UNBOUNDED_FLEET`。
- **正确模板（仓库已存在）**：`alns_wouda.py:120` = `SearchPolicy(..., max_cv=limits.cv, max_ev=limits.ev)`；`root_cause.py:244` 同样写对。**说明此坑曾被局部修过，但没同步进 winner_operators.py。**
- **传导链**：`feasible_repair.py:239/246` 用 `policy.max_cv/max_ev` 判可否新开路线(无限→乱开)；`:360-361` 归一化多趟(`#Tn`)也用同一无限值(压缩失效)→候选真实车队超编→`check.py`(按 `instance.num_cv=10`)判违约→`penalized_obj` 加 BIG_M→HillClimbing 全拒。
- **时间线佐证**：`13989832 Restore Goeke battery and physical fleet trips` 收紧车队为物理车计数(10+10)后，此前隐性的漏传 bug 变为必现卡死；`winner_operators.py` 从未加过 `max_cv=limits.cv`。

## 1. Stage 0 — 锁死"无第二个坑"（≤15 分钟，不是验证 bug 在不在）
唯一未 100% 锁死的点：SA 为何在同算例不卡死。快速确认 SA/fair-SA 走的 `SearchPolicy` 构造路径**已正确带车队上限**(走 `alns_wouda.py:120` 默认或显式传参)，即确认"漏传"仅存在于 winner-kernel 侧、非全局。同时全仓 grep 所有 `SearchPolicy(` 构造点，列出**每一处是否正确传了 `max_cv/max_ev`**，形成 `track21_policy_construction_audit.md`。**若发现除 winner_operators.py 外还有漏传点，一并纳入 Stage 1 修复。** 锁死后立即进入修复，不停下等人。

## 2. Stage 1 — 彻底修复（一次修干净所有漏传点）
- 在 `_run_winner_kernel_loop`（及 `winner_operators.py` 内任何其它构造 `SearchPolicy` 却没传车队上限处）改为从 bundle 实例推断并传入真实上限：
  ```python
  from .fleet import infer_fleet_limits
  limits = infer_fleet_limits(instance)   # 用 root_cause.py:244 同款
  policy = SearchPolicy(require_charging_signal=config.require_charging_signal, max_cv=limits.cv, max_ev=limits.ev)
  ```
  （`instance` 用该函数作用域内的 bundle 实例；与 `_run_winner_variant` 里传给循环的实例一致。）
- 修复 Stage 0 审计发现的**所有**其它漏传点，统一走 `infer_fleet_limits`。
- **不改** `cost.py/check.py/search/evaluation.py` 的评分/可行性语义；**不改** `SearchPolicy` 的类默认(保留 `UNBOUNDED_FLEET` 作为"未指定=不限"的合法语义，只在 winner 入口显式传真值)。
- 加/更新单测：断言 winner-kernel 在带 `num_cv/num_ev` 的实例上，其内部 policy 的 `max_cv/max_ev` == 实例真实上限（防回归再漏传）。

## 3. Stage 2 — 确认 winner-kernel 复活（100-01 + 100c）
修复后在 100-01（`E-UK100_01__d2_s3_seed1_24h_20251113`，10CV+10EV）跑 winner-kernel：**期望 `unique_solution_count ≫ 1`、`best_update_count>0`、best_cost 显著低于 warm，并逼近/复现历史 £4878 锚点(注意 M1 锚为 ARM，x86 数值会漂，比"是否恢复到碾 SA 量级"而非绝对值)**。同环境同预算下 winner vs SA：**期望 winner 重新 ≥ SA**。若修复后仍卡死→说明还有未定位的坑，深挖 candidate hash/接受拒因写 `HALT_STILL_STUCK` 诊断(此时才回到取证模式)。

## 4. Stage 3 — 清算并重跑被污染的结论（关键，别留旧脏数字）
此 bug 影响**所有**经 winner-kernel/`e2_alns_*` 且实例带车队上限的历史对比。逐项处理：
- **作废并标注**：Track17/Track19 里凡 winner 系方法参与的对比行，标 `SUPERSEDED_BY_TRACK21_FLEET_FIX`，写明"旧数字受车队 policy 漏传 bug 污染，不可引用"。
- **重跑公平对比**（复用 Track19 已修好的预算/等墙钟 + Track16 健康门三态 + 6 健康基线，PSO 透明排除）：修复后的 winner-kernel/最优 ablation 方法 vs 健康基线，25/50/100c、≥10 seed、同 warm start、Wilcoxon。
- **重跑主方法 ablation**：修复后重新确认 `winner_kernel(+组件)` vs plain_alns 的真实优势(此前 +3.23% 也可能被污染)。
- 判级：`WIN_REAL`(修复后主方法 vs 每个健康基线 ≥10% 显著且每规模不反向)/`MARGIN_REAL`(真实幅度 <10%，诚实写)/`HALT_100C_STILL_STARVED`(100c 吞吐仍不足→押 25/50c)。

## 4b. Stage 4 — DR 的连带清算（重要，别漏）
DR 的 learned-destroy 环境经 worker 调 winner 系算子/评分——若 DR 训练/评测也吃了这个漏传 bug（候选被车队违约压制），则 Pilot20-25 的"DR≈ALNS/+1~2%/学不到"结论**可能也部分被污染**。**核实 DR worker 侧的 policy 是否同样漏传车队上限**；若是，标注"DR 历史负结论需在修复后重评估，不能仍断言 DR 死"，并记入 HANDOFF。**（不在本轮重训 DR，只诚实标注污染范围、留给后续。）**

## 5. 边界 + 过夜铁律（沿用 `10_*.md` §9）
worker py313+NumPy2.3.5；只 x86 相对%；飞行前检查；周期 checkpoint；墙钟≤8h；防 OOM；禁过夜 push/rebase/prune；只 force-add 小产物；增量 `track21_progress.log`；每改动记"症状→出处→改哪→为什么"；连续 3 次自修失败升级诊断停。**不改保护文件语义。**

## 6. 交付物
`track21_policy_construction_audit.md`(所有 SearchPolicy 构造点是否传车队上限)、`track21_fix_report.md/json`(修了哪些点+单测)、`track21_winner_revival.md`(100-01/100c 修复前后 unique_count/best/vs SA)、`track21_reclaimed_fair_comparison.md/csv`(重跑的干净对比+判级)、DR 污染范围标注、更新 `HANDOFF.md`+`final_report.md`。人话结论：①bug 修了没、winner 复活没(unique_count/vs SA)、②清算后主方法对健康基线的**真实**领先%、到不到 10%、③哪些历史结论作废、④DR 负结论是否需重评估。

## 7. 资料顺序
先读本提示词根因段 + `winner_operators.py:656`/`feasible_repair.py:234-362`/`fleet.py infer_fleet_limits`/`root_cause.py:244`(正确模板) + Track17/19 报告(待作废项)。先锁死无第二坑→彻底修→确认复活→清算重跑→标注 DR 污染。不谄媚、不拿旧污染数字/欠算当赢。
