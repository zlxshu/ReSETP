# FIX-D2 任务书：路线层解码重复计算修复（发给 Codex，自包含）

仓库根：`/Volumes/移动硬盘（512G）/ReSETP`。本任务**允许改代码**，范围严格限定见下。

## 授权来源

`USER DECISION`（2026-08-17，P81 已落册）：批准修复 D2 重复计算。用户原话「同意，你去吧」。
`SCOPE`：D2 **不在 P78 冻结范围内**（P78 冻的是充电修复缓存与下界剪枝两处，仍待用户拍板）。
本任务**不得**触碰那两处。

## 先读（简版，不重读全套规矩）

`AGENTS.md`（项目规矩）｜`docs/handoff/lowlevel_defect_audit_20260817.md`（你自己的审计，D2 条目）｜
`docs/handoff/algorithm_followup_plan_20260817.md` §六。

## 缺陷（你自己审计出来的，此处复述以便自包含）

`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/hybrid_decoder.py:398-449` 的 `_split_block`，
把只依赖 `(position, end, 车型, 车场, 班次)` 的 `_probe_segment` 放在**每个存活 label 的内层**；
而分块长度由相邻客户的车场/车型/班次连续性决定（`:315-358`）。
即：**同一段区间，有多少个存活标签就被重算多少遍。**

`FACT`（实测）：N=1 包 441 次解码 760.9707096652419 秒（`sc10_education_depth_20260816/n1/best_solution.json:979-986`）；
SC8 包 10 次 0.0774687509983778 秒（`sc8_decoder_crossover_20260816/route_layer_900/best_solution.json:1177-1184`）。
即 1.725557 秒/次 vs 0.007746875 秒/次，**相差 222.742 倍**。

## 要做的（唯一一件）

在 `_split_block` 内，按 `(position, end)` 预计算或缓存 `_probe_segment` 的结果
（同一次 `_split_block` 调用内，车型/车场/班次由分块本身固定，故 `(position,end)` 足以作键；
**若你读码发现不足以唯一确定，改用完整键并在报告中说明**）。

**硬约束**：
- **不改**标签支配规则、不改选中规则、不改完整评价、不改候选顺序与并列裁决；
- 缓存对象必须**不可变**（audit 自己列的风险）；若 `_probe_segment` 返回可变对象，
  必须冻结或返回拷贝，**不得让下游就地修改污染缓存**；
- 缓存**只在单次 `_split_block` 调用内有效**，不得跨调用/跨候选/跨圈持有（避免状态泄漏）；
- **不碰三个受保护文件**（`cost.py`／`check.py`／`search/evaluation.py`）；
- 不改算例、不改测试断言、不动 P78 那两处（充电修复缓存、下界剪枝）。

## 验收（缺一不可）

1. **逐位一致**（这是纯提速的定义）：同算例 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`、
   同 seed、**固定迭代数**（用 `--iterations`，**不要用墙钟**——墙钟下提速本身会改变迭代数，
   逐位验收会被自己的成功搞垮；墙钟只设成不触发的安全上限）。
   修前 / 修后必须逐位相同：终解 fingerprint、成本、candidate 计数、gap 计数、
   接受/拒绝计数、完整评价结果、服务客户数与需求量。
   **任一项不同即视为改语义 → 立即回滚，如实报告，不得用速度收益抵消。**
2. **回归**：跑现有测试清单（`solver/reports/penalty_window_probe_20260816/regression_197.txt` 那 29 个文件），
   报 passed 数；**不许新增或修改测试断言把数字凑好看**。
3. **实测提速**：在上述固定迭代口径下报修前/修后的解码累计耗时与总墙钟。
   **不得预先承诺倍数**；实测多少报多少，哪怕很小。
4. **受保护文件哈希**前后一致，报出来。

## 输出

单一报告：`solver/reports/fix_d2_decoder_cache_20260817/report.md`，
首行 `FIX_D2_DONE` 或 `FIX_D2_HALT`，末行 `FIX_D2_END`；同目录落 `done.json`。
按四件套要求落 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`。
**所有产物落仓库内**（P80 铁律，严禁 /tmp）；报告须写明"若被中断如何续跑"。

报告须含：改了哪几行（贴 diff）｜缓存键是什么、为什么足够｜逐位一致逐项对照表｜
回归数｜实测提速｜受保护文件哈希｜**失败或不一致如实保留**。

## 边界

- 只改 `hybrid_decoder.py` 一处及其必要单测；改到别处即为越界，须停下报告。
- 发现别的问题：**记录一行**，不顺手修（授权边界是硬的）。
- 中文，说人话，结论逐条标 `FACT`/`INFERENCE`/`DECISION`/`UNKNOWN`。
