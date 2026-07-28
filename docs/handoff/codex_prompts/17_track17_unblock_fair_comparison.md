# Codex 提示词 17 — Track17：解锁公平对比（PSO 按 Track16 Stage4 排除，跑 Stage2-3 出真结论）

> Claude 写定（2026-06-29）。Track16 已让 **6/7 基线健康(GA/VNS/SA/GWO/ACO/IWD)**；PSO 根因查清=**搜索方向弱**(3978 个唯一候选但 best_update_count=0、无一优于 warm start，非编码 bug)，且已累计 >3 轮修复。**按 user 自己 Track16 Stage4 规则：PSO 根因查清后透明排除、不再 patch、10% 只基于健康基线。** 本提示词把卡在 Stage1 的硬停解开，跑完 Stage2(主方法选择)+Stage3(公平对比)出真结论。冷启动自包含、自动过夜、带闸、不谄媚、不拿坏基线当输家、不强行凑。

## 0. 边界 + 过夜铁律（沿用 `10_*.md` §9）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py` 语义；worker py313+NumPy2.3.5；只 x86 同机相对%；飞行前检查；周期 checkpoint+resume guard；墙钟≤8h；防 OOM；**禁过夜 push/rebase/prune .git**(留人工)；只 force-add 小产物(报告+CSV+解)；增量 progress 日志；每改动记"症状→出处→改哪→为什么"。

## 1. Stage A — 冻结基线集（PSO 透明排除）
锁定健康基线集 = {GA, VNS, SA, GWO, ACO, IWD}(各须满足 Track16 健康闸：eval≥0.9、best<warm、hash≠warm、零违约、candidate 多样、best_update_count>0；沿用 `track16_baseline_health_matrix.csv`)。**PSO 排除**，在所有报告写死一句：*"PSO adapter failed the common-referee health gate (3978 unique candidates but best_update_count=0, no candidate improved on warm start; search-direction failure, not an encoding bug); excluded from quantitative claims; root cause documented."* **PSO 不得作为输家计入任何领先%。** TS/SA/GWO 若接口在且健康可一并纳入。

## 2. Stage B — 主方法选择（ablation，不硬焊，必须胜 plain ALNS）
同一批 25/50c bundle、同 seed、同预算，比：`plain_alns`、`winner_kernel`、`winner_kernel+local_search`、`winner_kernel+charging_aware`、`winner_kernel+carbon_aware`、`winner_kernel+fairness`。
- **规则**：每个组件**单独加**、只有"加了不掉分(验证集 cost 不升)"才保留；多个有益组件可叠加但每步都要验证不掉分。**Track15 已证硬焊全组件会拖后腿(strong_method −3.69% vs plain)，禁止重蹈。**
- **选主方法** = 验证集上稳定最低、且**必须 ≥ plain_alns**。若没有任何配置明显胜 plain_alns，则 **plain_alns/winner_kernel 本身就是主方法**(它已 +8.5% vs 健康 GA，够)。
- 闸 `HALT_MAIN_NOT_STRONG`：连 winner_kernel 都不 ≥ plain_alns 时报（理论上不该，winner kernel 碾 SA 8.76%；若出现要查 winner_kernel 接入是否对）。
- 产出 `track17_method_ablation.csv`(每配置 vs plain 的验证集 gain + 保留/剔除决定)。

## 3. Stage C — 正式公平对比（出论文数字）
选定主方法 vs 全部健康基线（{GA,VNS,SA,GWO,ACO,IWD}）：
- 规模 25c→50c→(算力允许)100c；每规模 **≥10 seeds**；同 warm start；**同 16000 eval 或严格等墙钟**(健康字段必须完整记录)；scipy **Wilcoxon paired**。
- 报告：平均/中位/分规模领先%、p-value、失败实例数、每基线健康字段。
- **判级**：
  - `WIN_REAL`：主方法 vs **每个**健康基线平均 ≥10% 且 Wilcoxon 显著 且每规模不反向 → **论文赢点到手** → 建议推全规模(50-200c 三班倒，throughput 注意，分批/等墙钟)。
  - `MARGIN_REAL`：健康公平但最小领先 <10% → **诚实报真数字**(如对 GA +8.5%、对 VNS +x%…)；建议(a)按 Stage B 再叠一个有益组件冲 10%，或(b)按真实数字调论文叙事(领先幅度因基线而异是正常、可写)。
  - `HALT_MAIN_NOT_STRONG`：主方法不胜 plain → 先查主方法接入。

## 4. Stage D — 最终报告
`track17_fair_comparison_report.md/json` + `track17_rows.csv`(逐算法逐seed逐规模 + 健康字段) + `track17_method_ablation.csv` + 更新 `final_report.md`。人话回答：①主方法是不是 plain_alns 还是 winner_kernel(+哪个组件)、是否胜 plain；②对**每个**健康基线领先的**真数字**、是否到 10%；③PSO 根因与排除声明；④DR=future-work(不在本线)；⑤下一步(推全规模/调叙事)。

## 5. 资料顺序
先读 HANDOFF + `track16_baseline_health_matrix.csv`/health_report + `winner_operators.py`(winner kernel/各组件开关)/`local_search.py`/`charging.py`/`fairness.py` + `metaheuristic_baseline_runner.py`(公平 harness)。先证据、单点改、带闸、不拿坏基线/欠训当赢、不谄媚。
