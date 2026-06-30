# 09y — 决定性根问题：Goeke80 大算例下 EV-heavy 解"存不存在/划不划算"（构造+评估，非搜索）

日期：2026-06-27　提出：Claude（基于 09v/09w/09x 三探针收敛诊断）　执行：Codex　决策权：user
> 这是 09v(电池)/09w(swap+预算)/09x(碳算子) 三次 WEAK 的**共同根**的直接检验。三次都因"大算例解近全-CV、无 EV 实质可挖"而打平。本步**不靠搜索**，用构造+评估在几分钟内答死：EV-heavy 在 Goeke80 大算例到底**可行吗/划算吗**。

## 0. 先读 + 铁律
- 读 `HANDOFF.md` + `docs/handoff/memory/`（尤其 `alns-crush-root-cause.md`）+ 09v/09w/09x 报告。
- **禁改 `cost.py`/`check.py`/`evaluation.py`/`prices.py`/TeX。** 只用现成构造/充电/检查 API + 内存读数。
- 碳价钉死 0.05034；口径 `Q=3650,B=80,v=25`；系统 py313/numpy2.3.5/`PYTHONHASHSEED=0`；数字绑 commit。
- 这是**诊断**，不是 T3。拿不准/造不出就如实 HALT，**重点是诚实报告"为什么造不出"**。

## 1. 目标（一句话）
不靠 ALNS 搜索，**直接构造**一个"在硬上限内尽量多 EV"的可行解，评估其 cost/carbon，与现有近全-CV 解比，判定大算例 EV 塌缩是**真经济**还是**搜索找不到**。

## 2. 方法（构造，不搜索）
对代表大算例（至少 `e2-vanilla-150c-01 / 200c-01`、`e2-multidepot-150c-01 / 200c-01`、`e2-threeshift-150c-01`）：
1. 取 09s/09w 的近全-CV incumbent 作 baseline_all_cv（评 cost/carbon）。
2. **构造 EV-maximal 可行解**：从 incumbent 出发，逐条把路线尝试转 EV（用现有 `vehicle_type_swap` 逻辑 + `charging.py:_best_station_insert` 插充电、优先低碳时段、允许部分充电），直到触及 `num_ev` 硬上限或不能再转。每条转 EV 后用 `check_solution` 修复到可行（时间窗/电量/站容量）。
3. **逐条记录失败原因**（关键诊断）：某路线转 EV 失败时，是 80kWh **续航不够**（能量>容量）、还是充电绕行**违反时间窗**、还是**站容量**满？分类计数。
4. 对成功的 EV-maximal 解评 cost/carbon。

## 3. 预注册判决（三选一，每条都给明确下一步）
- **(X) SEARCH_GAP**：EV-maximal 可行 **且** cost/carbon 不差于 all-CV incumbent（≤ +ε，如 +2%）→ **EV 在 Goeke80 大算例划算，是搜索找不到**（warm start 锚死/预算不足）→ 下一步=EV-seeded 暖启动重测，届时 09x 碳算子/vehicle_type_swap 才有实质可挖。混合故事在 Goeke80 **活着**。
- **(Y) REAL_CV_DOMINANT**：EV-maximal 可行但**明显更贵**（即便最优低碳充电）→ **EV 在 Goeke80/80kWh 大算例真不划算**（真经济）→ Goeke80 是 CV 主导 regime；混合故事**需现代电池或改叙事**。
- **(Z) EV_INFEASIBLE_AT_80KWH**：EV-maximal **造不出**（多数长路线 80kWh 续航不够/充电违时窗）→ **80kWh 对大算例跨城物理上不支持 EV**（闭环 09f/09h "80kWh 太小"）→ 必须上现代电池场景（09w prices 贯通已可正确测）或改叙事。

## 4. 验收 + 报告
- 每代表算例给：all_cv cost/carbon、ev_maximal cost/carbon（或 INFEASIBLE）、EV 路线数达到/上限、失败原因分类表（续航/时窗/站容量各几条）。
- 判决给 §3 之一；人话先行、标清这是构造诊断非 T3。
- 回归测试相关项过；产物 commit；HANDOFF 追加 `[M1]`：判决 X/Y/Z + 下一步 + **建议把 09v/09w/09x/09y 提示词一并 git add 提交（user 反映找不到未跟踪文件）**。

## 5. 不要做的事
- 不跑 16000-eval ALNS 来"找" EV 解（那正是被质疑会找不到的东西）；本步是构造。
- 不碰保护文件/不改默认参数/不调碳价。
- 不把构造结果当正式 T3；造不出就如实报 Z，别注水。
