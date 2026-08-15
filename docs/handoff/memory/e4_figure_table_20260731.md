# E4-FIGURE-TABLE-01 记忆节点（2026-07-30）

## 状态与权威目录

- 任务：`E4-FIGURE-TABLE-01`
- 状态：`COMPLETE`
- 交付目录：`docs/paper_v2/figures_e4_20260731/`
- 数据模式：只读封存数据汇总
- 新增实验数：0
- 求解器、搜索、E4 封存目录写入数：0

## 封存输入

1. `baselines/china_e3_e7/e4_carbon_timing_20260729/action_timing_audit.csv`：44,072 个会话日，SHA-256 `a93cf85d31bcf11d3e37571379c50e488297eec5780be1087057b26d23269497`。
2. `baselines/china_e3_e7/e4_carbon_timing_20260729/raw_runs.csv`：11,340 个配对解--日，SHA-256 `530f2b89f3a03ea10b6ac53b3945cc98ac75018ac5e37db74fa6fc82a46fd3f4`。
3. `data/ChinaInstances/china81_runtime_parameter_authority_v3_20260723/tariff_carbon_hourly_calendar.csv`：9 城×28 日×48 槽，SHA-256 `54acbdc757c8a3a3b097d1e39cd35294e795ca2c1711bd56b12bc3b9af9b1c0b`。

三个当前哈希均与 E4 `artifact_hashes.json` 的登记值一致。必需字段无缺失；44,072 个动作键唯一，按解--日聚合的会话数和电量与 11,340 行 `raw_runs.csv` 逐行一致。合法窗口违约、日界外开始、非正电量均为 0。

## 图形口径

面板 (a) 的典型日规则为固定日历位置 `2025-02-12`，对应项目结果盲批准的共同解释日。京津冀、珠三角、成渝分别固定读取北京、广州（`Guangdong` 碳源列）和重庆的 48 个半小时槽。

面板 (b) 使用全部 44,072 个会话日。每次充电的 `energy_kwh` 归入两臂各自开始时刻所属的半小时槽，分母为 `1,234,753.935547482166 kWh`；ASAP 和 CARBON 的 48 槽总量均精确回到该分母。图形保持一个总体聚合面板，不拆分全分母。

图注登记路径、车辆、客户服务关系和充电总量完全固定，两臂唯一变动量为充电开始时刻。颜色沿用 E2 蓝/红/绿项目色系，策略线为灰色虚线与红色实线。PDF 无栅格对象，macOS `STHeiti Light` 中文字体嵌入；PNG 为 300 dpi。

## 正文主表

表格按一行一指标组织，共同分母为 405 个固定解×28 日＝11,340 个配对解--日：

| 指标 | ASAP | CARBON | 相对变化 |
|---|---:|---:|---:|
| 充电排放（kg CO2e） | 475,317.335 | 214,033.628 | −54.9704% |
| 系统排放（kg CO2e） | 2,680,860.542 | 2,419,576.835 | −9.7463% |
| 充电电费（CNY） | 528,422.79 | 1,241,158.27 | +134.8798% |
| 完整模型成本（CNY） | 37,560,607.87 | 38,253,741.85 | +1.8454% |

相对变化统一按 `(CARBON − ASAP) / ASAP × 100%` 计算。LaTeX 源码已通过 XeLaTeX 独立编译，无版面越界。

## 交付与接线状态

目录内含矢量 PDF、300 dpi PNG、图与图注 TeX、两份绘图数据 CSV、正文主表 TeX/CSV、构建脚本、验证摘要、报告、哈希清单和终态记录。`paper_main.tex` 尚未接入本批图表；后续接入直接引用 `figure_e4_timing_migration.pdf`、`figure_e4_timing_migration_caption.tex` 和 `table_e4_main.tex`。
