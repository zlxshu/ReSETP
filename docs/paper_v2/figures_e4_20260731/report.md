# E4 充电时刻迁移机制图与正文主表交付报告

## 1. 交付状态

状态为 `COMPLETE`。双面板机制图、正文主表、绘图与制表脚本、聚合数据、图注源码和验证记录均已生成。全部计算为已封存 CSV 的确定性汇总，新增实验数为 0。

图中面板 (a) 给出三个城市群代表电网的典型日 48 时段碳强度；面板 (b) 给出全体 44,072 个会话日按充电电量加权的 ASAP 与 CARBON 开始时刻分布。正文主表按一行一指标组织，列出四项总量、共同分母和相对变化。

## 2. 封存输入核验

| 输入 | 行数 | 必需字段 | 当前 SHA-256 | 封存核验 |
|---|---:|---|---|---|
| `baselines/china_e3_e7/e4_carbon_timing_20260729/action_timing_audit.csv` | 44,072 | `task_id`、`instance_id`、`region`、`seed`、`grid_date`、`action_index`、`energy_kwh`、合法窗口、两臂开始时刻、两臂实际排放 | `a93cf85d31bcf11d3e37571379c50e488297eec5780be1087057b26d23269497` | 与 E4 `artifact_hashes.json` 一致 |
| `baselines/china_e3_e7/e4_carbon_timing_20260729/raw_runs.csv` | 11,340 | 解、日期、会话数、电量、两臂充电排放、系统排放、充电电费和完整模型成本 | `530f2b89f3a03ea10b6ac53b3945cc98ac75018ac5e37db74fa6fc82a46fd3f4` | 与 E4 `artifact_hashes.json` 一致 |
| `data/ChinaInstances/china81_runtime_parameter_authority_v3_20260723/tariff_carbon_48slot_calendar.csv` | 12,096 | 城市、区域、日期、半小时槽、日内分钟、碳强度、碳源列 | `54acbdc757c8a3a3b097d1e39cd35294e795ca2c1711bd56b12bc3b9af9b1c0b` | 与 E4 登记的 `calendar_sha256` 一致 |

三个输入的必需字段均齐全且无空值。44,072 个会话日动作键唯一；按 `task_id × instance_id × seed × grid_date` 聚合后，与 11,340 个配对解--日的会话数和充电电量逐行一致。两臂开始时刻均位于各自合法窗口和当日 0--24 h 范围内，正电量行 44,072 行。

## 3. 图的数据口径与设计

### 3.1 典型日规则

典型日采用固定日历位置规则：读取冻结日历中的 `2025-02-12`。该日期是项目结果盲批准的共同解释日，依据见 `docs/handoff/china_e3_e7_foundation_adapter_contract_20260723.md`。三个城市群的代表曲线固定为京津冀的北京、珠三角的广州（`Guangdong` 碳源列）和成渝的重庆；每条曲线均为该日 48 个半小时时段。日期、代表城市和碳源列均在脚本常量及 `validation_summary.json` 中登记。

### 3.2 全分母开始时刻分布

面板 (b) 使用 `action_timing_audit.csv` 的全部 44,072 行。每个会话日的 `energy_kwh` 全量归入其开始时刻所在的半小时槽，槽号为 `floor(start_second / 1800) + 1`；每槽占比为该槽电量除以全分母电量 `1,234,753.935547 kWh`。ASAP 和 CARBON 的分母电量完全相同，48 槽加总均回到该总量。

面板 (b) 保持一个总体聚合面板，不再按城市群拆分。该组织保留 44,072 个会话日的单一全分母，并使两臂的时段迁移在同一坐标中直接比较。图面信息为典型日碳曲线与开始时刻分布；四项结果幅度集中放入正文主表。

### 3.3 图注

> E4固定路径、车辆、客户服务关系与充电总量条件下的典型日电网碳强度和全分母能量加权充电开始时刻分布：(a) 固定日历位置2025年2月12日的京津冀、珠三角和成渝代表电网48个半小时时段碳强度；(b) 44,072个会话日按单次充电电量加权的ASAP与CARBON开始时刻分布；两臂的唯一变动量为充电开始时刻。

同一图注已保存为 `figure_e4_timing_migration_caption.tex`。

### 3.4 样式与格式验收

配色沿用 `figures_e2_v2_20260730` 的项目色系：京津冀蓝 `#1F77B4`、珠三角红 `#D62728`、成渝绿 `#2CA02C`；策略分布使用灰色虚线表示 ASAP、红色实线表示 CARBON。坐标轴仅保留左、下边框，不加网格，图例置于图内。

矢量文件 `figure_e4_timing_migration.pdf` 为单页 438.04 × 335.42 pt，`pdfimages -list` 未检出栅格对象。Arial 与 macOS `STHeiti Light` 中文字体已嵌入 PDF。PNG 尺寸为 1826 × 1398 像素，DPI 元数据为 299.9994 × 299.9994；原始尺寸视觉检查确认中文标签、图例和面板标记无方框、无遮挡。

## 4. E4 正文主表

采用一行一指标。E4 只有一组固定解、固定路径的 ASAP--CARBON 配对比较，而四项终点分属排放与成本两种单位；按指标排成四行可以在同一组数值列中直接读取绝对值与相对变化，并把共同分母统一写入表注。

| 指标 | 单位 | ASAP 总量 | CARBON 总量 | 相对变化 |
|---|---|---:|---:|---:|
| 充电排放 | kg CO2e | 475,317.335 | 214,033.628 | −54.9704% |
| 系统排放 | kg CO2e | 2,680,860.542 | 2,419,576.835 | −9.7463% |
| 充电电费 | CNY | 528,422.79 | 1,241,158.27 | +134.8798% |
| 完整模型成本 | CNY | 37,560,607.87 | 38,253,741.85 | +1.8454% |

共同分母为 `405 个固定解 × 28 个日历日 = 11,340 个配对解--日`。各绝对值为相应 11,340 行的总量，相对变化按 `(CARBON − ASAP) / ASAP × 100%` 计算。LaTeX 源码 `table_e4_main.tex` 已通过 XeLaTeX 独立编译检查，无 overfull/underfull 报告；机器可读明细保存在 `table_e4_main.csv`。

## 5. 复现与核验

在项目根目录执行：

```bash
python3 docs/paper_v2/figures_e4_20260731/build_e4_figure_table.py
```

脚本启动时先核对三个封存输入的 SHA-256 和必需字段，再进行全分母勾稽、48 槽聚合、四项总量汇总与图表生成。绘图使用本机已安装的 XeLaTeX/PGFPlots 和 macOS 字体，PNG 由矢量 PDF 以 300 dpi 转换。脚本不调用求解器、搜索程序或实验运行器。

## 6. 交付文件

| 文件 | 内容 |
|---|---|
| `figure_e4_timing_migration.pdf` | 双面板矢量正文图 |
| `figure_e4_timing_migration.png` | 300 dpi 正文图 |
| `figure_e4_timing_migration.tex` | PGFPlots 图形源码 |
| `figure_e4_timing_migration_caption.tex` | 中性名词短语图注源码 |
| `e4_typical_day_carbon.csv` | 三条代表电网的 48 槽绘图数据 |
| `e4_energy_weighted_start_distribution.csv` | 全分母两臂能量加权开始时刻分布 |
| `table_e4_main.tex` | 正文主表 LaTeX 源码 |
| `table_e4_main.csv` | 正文主表机器可读数据 |
| `build_e4_figure_table.py` | 可复现构建与验证脚本 |
| `validation_summary.json` | 输入哈希、分母、勾稽和输出配置记录 |
| `artifact_hashes.json` | 交付文件 SHA-256 清单 |
| `done.json` | 终态记录，最后写入 |
