# TEX-EVIDENCE-RECONCILIATION-01 记忆节点（2026-07-31）

## 状态与权威目录

- 任务：全篇 `paper_main.tex` 数字与封存证据逐一核对
- 执行者：终端 Claude（临时替代 Codex，因 Codex CLI 配额耗尽至 2026-08-05 13:39；用户已授权本轮由 Claude 直接执行核查、不派发 Codex 提示词）
- 状态：`COMPLETE`（只读核查，未改 TeX、未改 solver、未跑实验）
- 交付目录：`docs/handoff/tex_evidence_reconciliation_20260731/`（`report.md` + `done.json`）
- 触发原因：`docs/handoff/e2_e3_reframing_20260731/` 发现 E2/E3 两处僵尸内容后，用户要求把全篇查一遍

## 统计

34 处数值/设计断言：19 MATCHED、5 STALE、4 UNSOURCED、6 PLACEHOLDER；另有 2 处描述了与冻结设计不符的实验（均落在 E7）。致命问题 4 项、高优先级 5 项，均待用户看过报告后决定是否修复。

## 四项致命发现

1. **`tab:china81-summary` 九层表未闭合**：E2/E3 改写任务（`e2_e3_reframing_20260731`）第15行已点名"城市群分层表(tab:china81-summary)中的数字...与...权威数字...完全不同"，但那一轮只把表下方 prose 的自相矛盾百分比(0.776%→0.711%)改成与旧表自洽，**没有替换旧表本身的9行绝对成本数据**。本轮用当前唯一权威 E2 来源 `baselines/algorithm_prototypes/china81_vs_opensource_20260727/raw_runs.json` 重新聚合（按"层内5种子均值→9层算术平均"或按405单元flat均值两种口径），均与表中数字（如总体O=3346.8/MV=3323.0）相差7%-33%，确认表格本身仍是陈旧批次。
2. **燃油价陈旧**：正文（989-991行）用6.87/6.83/6.90元/L，但 `solver/src/setp_solver/prices.py` 第120-134行注释自证这批值"came from the 2026-07 official snapshots...superseded"，当前批准值（`china81_runtime_parameter_authority_v4_20260723`，approved）为分城市7.48(北京/成都)/7.43(天津/石家庄)/7.44(广州系)/7.50(重庆)。
3. **EV车型表陈旧**：`tab:vehicle` EV列（140.41kWh电池、1000kg载重、3300kg整备质量、"智蓝ES1·140"）是2026-07-27已批准变更（`docs/handoff/model_change_approval_register_20260718.md`第2129-2160行"E2-RERUN-UNIFIED-01-STEP1-040"）**之前**的旧车型。当前封存批（即本文全部数值结果的来源）实际用"智蓝ES1快递版栏板配置"：77.28kWh、1700kg载重、2600kg整备质量。独立佐证：`baselines/china_e3_e7/e5_literature_curve_20260731/report.md`第32行明确写"按本项目77.28 kWh电池"。
4. **E7设计描述与冻结设计不符**：4.7节文字（含中英文摘要145/162-163行、创新点第4条272-273行）描述"五臂(含顺序插入/完整动态加结算参与)"、"27个地区--规模单元"为统计单位，且用完成时态声称已"考察/quantify/test"动态需求交互。但 `baselines/china_e3_e7/e7_dynamic_v3_20260731/pre_registration.json`（继承 `e7_dynamic_20260731` 冻结设计，`scientific_design_changes: []`）显示实际只有**4臂**(STATIC_FIXED_RECOURSE/FULL_ROLLING/NO_COOPERATION/CARBON_BLIND)×**3算例**(50c/100c/150c)×种子1-10，完整候选搜索评价数为0，尚无任何正式结果。"27个地区--规模单元"疑似从 `e4_carbon_timing_20260729` 的27单元聚合网格，或 `model_change_approval_register_20260718.md`第2126行另一个无关的80/56/32固定梯blind-pilot任务表述误植而来。

## 高优先级发现（数据已存在但未写入/路径未接线）

- `tab:e5-summary`全占位符"---"，但 `e5_nonlinear_final_20260730/report.md` 证据已 `COMPLETE`（`MECHANISM_BUT_TIE`：NL90可行率20/20、L100假可行0/20、共同可行成本变化20/20单元均0.000%），数字已存在只是没写进正文。
- `fig:e4-charging` 引用路径 `generated_figures/e4_charging.pdf` 不存在（该图从未接入正文，见 `e4_figure_table_20260731.md` 末尾"paper_main.tex 尚未接入本批图表"），但E4已有完整正式图 `docs/paper_v2/figures_e4_20260731/figure_e4_timing_migration.pdf`，只是路径未接上。
- 4.1节"十次运行"（1051行）与权威来源（`china81_vs_opensource_20260727`）实际只有5个种子（且5个种子结果完全相同，`selected_source=protected_stage_1`）不符。
- TOU电价表尖峰列（广东珠三角1.6521、深圳1.4372）在当前权威2025年2月日历（`china81_runtime_parameter_authority_v3/v4_20260723`）中找不到来源；全日历唯一有`sharp_peak`价档的城市是石家庄(1.1348，已核对一致)。

## 未完全覆盖（如实列出，供后续核查）

- `tab:v13-results`（28道公开算例基础对比表）未定位到单一权威来源目录（`baselines/algorithm_prototypes/`下30余个算法原型子目录）；但其扩展表`tab:v13-improved`已在`mvhgssp_bks_reproduction_full_20260727`找到并逐位核对一致。
- TOU电价表仅抽查北京/深圳/广州三行，天津/河北南网/四川/重庆四行未逐行复算。

## 后续处理原则

修复须按报告优先级表逐条处理，且不能只改 prose 不改表格本身（吸取本次审计发现的"C1类"教训：上一轮只改了百分比措辞、没换表格数据）。E7 相关4项在数据补齐前只能先改文字口径（臂数/统计单位/摘要措辞），不能等数据；E5 的 H1 不需要等新实验，只需要把已完成的结果填入正文。修复完成后应有新一轮复核，确认本报告列出的 STALE/UNSOURCED/PLACEHOLDER 项目清零而非部分处理。
