# Codex 提示词 18 — Track18：动态 DR（DR 唯一有理论优势的战场，先量 headroom 再训）

> Claude 写定（2026-06-29），第一手读穿 `solver/src/setp_solver/search/dynamic.py`。**静态 DR 已死(6 次+读穿 Cao 源码：RL 在静态优化上是摆设，因强 ALNS 已近最优)。动态不同**：事件滚动到达、需边来边决策，RL 的本事(序贯/不确定下决策、anticipation)在此才有理论优势。但**先量"预判有没有空间"，没空间就别训**。冷启动自包含、自动过夜、带闸、不谄媚、不拿欠训当赢。本线只服务 DR 效能，独立于 Track17(论文保底)。

## 0. 第一手事实（已读 dynamic.py，执行者须懂）
- 已有 `run_rolling_reoptimization`：add/cancel/demand_change 事件分阶段(q_bar=8 / delta_t 触发)，**每阶段 `_run_stage_plan` 用 `run_alns_wouda` 重新求解**=**myopic 重优化基线**(不预判未来)。
- 它已算 `information_cost = dynamic_final_control.total_cost − static_revealed_control.total_cost`（动态解 − 全信息静态解）。**这个 gap = anticipation 能省的上限 = DR 在动态上唯一的发力空间。**
- DR 要赢的对象 = 这个**已经用强 ALNS 的 myopic 重优化**（强基线，不是稻草人）。

## 1. 边界 + 过夜铁律（沿用 `10_*.md` §9）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py/dynamic.py 的求解语义`(可新增动态 DR 模块/调用，不改既有评分与可行性)；worker py313+NumPy2.3.5；只 x86 相对%；飞行前检查；周期 checkpoint+resume guard；墙钟≤8h；防 OOM；禁过夜 push/rebase/prune；只 force-add 小产物；增量 progress 日志；连续 3 次自修失败升级诊断停；每改动记"症状→出处→改哪→为什么"。

## 2. Stage 0 — 量 anticipation headroom（廉价、不训练、决定性，先做）
在多个动态算例(25/50c，≥10 seeds，复用 `load_or_generate_dynamic_events` 的事件流)上跑现成 `run_rolling_reoptimization`，聚合 **`information_cost` 占比 = (dynamic − static)/static × 100%**。同时核：每阶段 ALNS 重优化健康(零违约、真在求解)、全信息静态解健康。
- **闸 G0**：
  - 平均 `information_cost%` **≥ ~5%**（myopic 重优化离全信息有可观差距）→ **anticipation 有空间** → 进 Stage 1。
  - **< ~2%**（myopic 重优化已逼近全信息上限）→ `HALT_NO_ANTICIPATION_HEADROOM`：**即便完美预判也省不了多少 → 动态 DR 也封顶**，诚实记录、DR 整体转 future-work、停。（这是动态版"先量 headroom"，杜绝静态覆辙。）
  - 2–5% → `THIN_HEADROOM`：空间小，记录；可选谨慎进 Stage 1，但成功 bar 调低、预期诚实。
- 产出 `track18_headroom.csv`(逐 seed information_cost% + 基线健康字段)。

## 3. Stage 1 — anticipatory DR（仅 G0 有空间）
- **决策面**：在每个滚动阶段，DR 策略做**预判性决策**（非纯 myopic 重解）——例如：给预期到达(add)预留运力/时间窗松弛、决定哪些客户先承诺/哪些延后、车辆预定位；动作接到现有 stage 规划入口(`_run_stage_plan` 的初始解/约束注入处)，**不改 evaluate/check 语义**。
- **状态**：当前已揭示需求、已承诺路线/车辆状态、阶段进度、历史事件率(add/cancel/change 频率)等。
- **reward**：负的阶段增量成本(+终局相对全信息的 gap 缩小)；防早停/防退化套利。
- **训练**：在**大量新生成的动态场景**(fresh per batch、足量，远超个位数；POMO baseline、target-KL、LR 退火，沿用前几轮已验证的稳定化)；同规模训测不重叠。
- **闸 G1**：held-out 动态场景上，DR vs myopic 重优化的总成本改进达阈值且稳定(KL ok、不退化、零违约) → 过；否则 `HALT_DR_DYNAMIC_NO_GAIN`(数据/稳定都做对仍学不到→诚实)。

## 4. Stage 2 — 正式判级（决定性）
独立动态 held-out(≥10 seeds、同事件流口径、同 worker py313)，DR-anticipatory vs **myopic 重优化(强基线)**，同响应预算：
- `DR_DYNAMIC_REAL_GAIN`：DR 总成本显著优于 myopic(如 ≥+5%、Wilcoxon 显著、零违约、稳定) → **DR 终于有真增量**(罕见则是大新闻；这是 DR 唯一可立的效能贡献)。
- `DR_DYNAMIC_FLAT`：DR ≈ myopic(±) → **动态 DR 也封顶** → DR 整体诚实 future-work，论文押 Track17。

## 5. 交付物
`track18_dynamic_dr_report.md/json`(headroom 占比 + DR vs myopic 真数字 + 判级 + 人话"动态上 DR 到底有没有用、DR 去留")、`track18_headroom.csv`、`track18_rows.csv`(逐场景)、best ckpt。最终人话：information_cost 有多大、DR 有没有把它缩小、DR 是否值得作为效能贡献。

## 6. 资料顺序
先读 HANDOFF + `dynamic.py`(rolling/information_cost/`_run_stage_plan`) + 动态 RL 文献(Ulmer 等 anticipatory policy for dynamic VRP；RL 在 information_cost gap 大时才赢)。先量 headroom、再训、带闸、不拿欠训/无空间硬训当赢、不谄媚。
