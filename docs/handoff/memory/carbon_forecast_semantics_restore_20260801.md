---
name: carbon-forecast-semantics-restore-20260801
description: "恢复预测碳强度用于排程、事后核算碳强度用于结果复算的论文语义"
metadata:
  node_type: memory
  type: completed_task
  task_id: REG-20260801-C01
  status: complete
---

# 碳强度双字段语义恢复（2026-08-01）

## 决定与范围

`DECISION`：用户先明确回答“当然要撤销”，随后批准按已核实方案开始执行。本任务只修复 `docs/paper_v2/paper_main.tex` 的碳强度符号、公式和数据说明，不改代码、数据、算例、实验参数或 E4 数值。

2026-07-31 的 `CARBON-FORECAST-MINIMAL-FIX-20260731` 把预测字段从论文中删除，其依据后来被代码复核推翻。本记录取代该任务的当前结论；旧目录保留为历史错误现场，不覆盖。

## 代码事实

- `instance_loader.py` 同时读取 `forecast_gco2_per_kwh` 与 `actual_gco2_per_kwh`。
- `china81.py` 把同一条 S1-2025 省级情景投影序列写入两个字段，所以 China81 中逐槽有 `forecast=actual`。
- 动态充电重排默认读取 forecast；静态多趟接口允许显式指定 forecast；完整成本和排放复算读取 actual。
- E4 运行器对每个候选时刻同时计算 predicted 与 actual，按 predicted 选择时刻，结果表输出 actual。

因此，预测/事后核算的双字段架构是真实存在的；但不能泛化成“所有调度函数都默认读取 forecast”。

## 已执行修改

1. 符号表恢复 `\widehat\gamma_t,\gamma_t`，名称改为“预测与结算碳强度”，避免把 China81 的 actual 字段误写成独立观测；同时登记 `\widehat E_{kp},E_{kp}`。
2. 式 `eq:carbon` 同时定义预测排放与执行后核算排放。规划目标 `F_1`、规划阶段车场收益和充电择时规则分别使用 `\widehat E_{kp}`、`\widehat\gamma_t`；结果报告使用 `E_{kp}`、`\gamma_t`。
3. 数据说明写明：使用 S1 情景 2025 年表；该数据是模型模拟的省级情景投影，不是官方实测、实时或边际碳强度；China81 没有独立事后观测序列，因此 `\widehat\gamma_t=\gamma_t`。
4. E4 正文写明：按预测字段选充电时刻、按核算字段复算；本批两字段同值，所以现有 E4 数值反映充电择时，不含预测误差影响。
5. 未恢复旧稿“两者之差刻画预测误差对减排效果的影响”的说法，因为本项目没有预测误差实验。

独立顾问 C01 对字段、调用链、旧 before/after 差异和 A-1 批准范围逐项只读核对，结论与上述修改一致；并纠正首轮草稿一度漏保留的省级情景投影来源披露，该披露已补回。

## 验证

- XeLaTeX/latexmk：成功，25 页，未定义引用 0，错误 0。
- 数学审计：36 通过、1 个既有“未引用公式标签”警告、0 错误。
- 视觉检查：符号表与双排放公式所在第 4--6 页无裁切、重叠或新增溢出。
- 编译日志只保留两处既有版面提示：表格 3.22958 pt overfull、英文参考文献 1 处 underfull，均不在本次修改位置。
- `paper_main.tex` SHA-256：`c23da3166f49f79cf25897ff55aa80167893768727eb063a5499199beab3d7fd`。
- `paper_main.pdf` SHA-256：`254df4621ba071568451500ff0f839ce9a347656fa05ef17151ba0edb9995bca`。

## 结果

`FACT`：A-1 已关闭。论文模型语义与现有双字段调用链重新一致，China81 的同值数据限制也已在实验设置与 E4 结果段直接说明。E4 的 11340 个配对单元和全部既有数值未重算、未改变。
