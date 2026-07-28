# Codex 提示词 19 — Track19：修 100c 预算，让公平比较合法（论文线，先证据后结论）

> Claude 写定（2026-06-30）。**Track17 在 100c 停在 `HALT_BASELINE_NOT_RUNNING`(GA 不健康)——但第一手复核发现真根因不是 GA**：`track17_rows.csv` 里**主方法 `winner_kernel_true_repair_adaptive_q` 在 100c 也只跑了 4234/16000 评估(ratio 0.264)、也返回 warm start**。即 **100c 下 900s/16000 预算不够、主方法与基线都被饿死**(老 HALT_BASELINE_THROUGHPUT 再现)，非 GA 专属 bug。本轮**只修预算+健康门口径，让比较合法，报真数字**，不硬凑赢。冷启动自包含、自动过夜、带闸、不谄媚、不拿饿死/欠算当赢。

## 0. 边界 + 过夜铁律（沿用 `10_*.md` §9）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py` 语义；worker py313+NumPy2.3.5；只 x86 相对%；飞行前检查；周期 checkpoint+resume guard；墙钟≤8h；防 OOM；禁过夜 push/rebase/prune；只 force-add 小产物；增量 progress 日志；每改动记"症状→出处→改哪→为什么"。

## 1. Stage 0 — 诊断 100c 预算饿死（先证据）
在 100c/seed901 复核**主方法 + 每个基线**的 `actual_evals/eval_budget`、`best<warm?`、`unique_candidate_count`、`best_update_count`。确认主因：**主方法 ratio≪1（如 0.264）= 900s 墙钟先到、评估没用满 → 饿死**。产出 `track19_budget_audit.csv`。

## 2. Stage 1 — 修预算 + 修健康门口径
- **预算**：给 100c **足够预算**——把 `max_runtime_seconds`/`eval_budget` 调到**主方法能达 eval ratio ≥0.9**（或对所有算法严格**等墙钟**且该墙钟足够主方法用满评估）。25/50c 保持原设。**目的=让所有算法在 100c 真跑起来，不是让谁赢。**
- **健康门修正（关键，别再混两件事）**：
  - `INVALID_NOT_RUN`：`eval_ratio<0.9` 或 `unique_candidate_count` 过低(没探索) → 无效，需修预算/接口。
  - `VALID_BUT_WEAK`：`eval_ratio≥0.9` 且 探索充分(unique 多) 但 `best≥warm` → **合法的弱基线，算它=warm 的输，计入对比、不 HALT**（同 warm start + 同预算下没改进 = 真弱，非"没跑"）。
  - `HEALTHY`：`eval_ratio≥0.9` 且 `best<warm` 且 `hash≠warm` 且零违约。
  - **只有 INVALID_NOT_RUN 才阻断**；VALID_BUT_WEAK 与 HEALTHY 都进对比。

## 3. Stage 2 — 重跑 100c(及 25/50c) 正式公平比较 + 判级
主方法(=Track17 选出的 `winner_kernel_true_repair_adaptive_q`，或按 ablation 重确认) vs 全部**非 INVALID** 基线：同 warm start、修好后的预算/等墙钟、≥10 seed、Wilcoxon。
- `WIN_REAL`：所有必选基线非 INVALID 且 主方法平均领先 ≥10% 且 显著 且每规模不反向 → 论文赢点到手。
- `MARGIN_REAL`：合法但 <10% → **诚实报真数字**(分规模、分基线)；论文按真实幅度写(领先因基线/规模而异是正常、可写)。
- `HALT_100C_STILL_STARVED`：加预算后主方法在 100c 仍 ratio<0.9 → 100c 吞吐是真硬骨头，写诊断(是否 profile 提速/缩 100c 规模到可解)，**此时论文可先押 25/50c 合法结论 + 诚实标注 100c 待解**。

## 4. 交付物
`track19_fair_report.md/json`(预算审计 + 健康门三态分类 + 各规模各基线真领先% + Wilcoxon + 判级 + 人话)、`track19_rows.csv`、更新 `final_report.md`。人话：100c 饿死修没修好、主方法对每个非INVALID基线的**真数字**、到不到 10%、下一步。

## 5. 资料顺序
先读 HANDOFF + `track17_rows.csv`(100c 主方法/基线 ratio) + `metaheuristic_baseline_runner.py`/`alns_crush_v2.py`(预算/等墙钟口径)。先证据、单点改、带闸、不拿饿死/欠算当赢、不谄媚。
