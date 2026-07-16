# ALNS 评价预算闭合静态审计（零搜索）

判定：`HALT_ALNS_BUDGET_CLOSURE_REQUIRED`。

本任务没有启动求解器、没有运行算例、没有读取 E7 中间结果，`search_evaluations=0`。审计仅解析当前 `resetp_alns` 源码，并复核 2026-07-10 封存诊断的四个输入表面哈希。

## 已确认的不利证据

历史 9 次 CURRENT_T3 运行产生 11547 次未计入正式预算的完整解评分；单次为 760--2164 次，实际/报告评价数均值比为 13.830。这些数值由封存 `raw_runs.csv` 重新计算，不是从旧报告抄写。

当前源码共识别 31 个相关评分调用点，其中 5 个明确走预算化完整候选通道，24 个仍不满足 G0 闭合标准，未分类调用点 0 个。

阻断位置（按函数去重）：

- `kernel/alns_core.py:_repair_solution_delta_score`
- `kernel/alns_core.py:_run_adaptive_sa_alns`
- `kernel/alns_core.py:objective`
- `kernel/alns_core.py:run_alns_wouda`
- `kernel/winner.py:_candidate_change_and_violations`
- `kernel/winner.py:_maybe_write_e2_checkpoint`
- `kernel/winner.py:_reschedule_staged_result`
- `kernel/winner.py:_run_staged_hybrid_entry`
- `kernel/winner.py:_run_winner_kernel_loop`
- `kernel/winner.py:_run_winner_variant`
- `kernel/winner.py:_winner_history_entry`
- `kernel/winner.py:run_true_lns_middle_alns_hybrid`
- `operators/carbon_operators.py:_solution_carbon_kg`
- `operators/feasible_repair.py:_solution_cost`
- `operators/local_search.py:_score_internal_solution`
- `support/fleet_charge_corepair.py:_feasible_model_cost`
- `support/fleet_charge_corepair.py:propose_fleet_charge_corepair`
- `support/global_order_repack.py:_feasible_model_cost`

`raw_runs.csv` 逐行区分：搜索期完整候选、初始/终局/历史/断点参考评分、路线局部增量以及结构搜索评分。允许留在正式搜索预算之外的参考评分目前也没有独立计数，因此仍不能宣称预算口径闭合。

## E7 后 G0 验收标准

1. 每次参与候选选择、局部搜索、修复或结构重组的完整解评分，恰好调用一次 `EvalBudget.record()`。
2. 初始、终局、历史和断点复算可不占搜索预算，但必须进入独立的 `reference_full_solution` 计数。
3. 路线局部或未完成修复增量必须进入独立计数，且不得被用作未收费的完整候选选择器。
4. 静态审计不得残留 `BLOCK` 或未分类调用点；随后用零/极小预算行为测试验证候选计数与预算一一对应。
5. 上述标准全部通过前，不得启动正式 Solomon/Homberger 算法胜负测试，也不得声称算法性能领先。

本次 HALT 是口径门禁，不是算法胜负结论。共享算法内核未在本任务中修改。
