# 碳强度"预测/实际"最小化改动

- 编号：`CARBON-FORECAST-MINIMAL-FIX-20260731`
- 依据：用户 2026-07-31 裁决——"碳强度可以学习文献的做法，如果建模本身就是预测或者说不需要
  怎么改，那就做最小化改动即可。"
- 性质：**纯 TeX 文字与符号改动，不触及任何计算，不使任何实验结果作废。**

## 一、改之前是什么问题

**FACT（2026-07-31 复核）**：
- `paper_main.tex:360` 符号表定义 $\widehat\gamma_t,\gamma_t$ 为"时段 $t$ 的预测与实际碳强度"；
- `:456` 正文写"调度时使用预测碳强度 $\widehat\gamma_t$，事后结算采用实际碳强度 $\gamma_t$，
  两者之差刻画预测误差对减排效果的影响"；
- `:1040` 第 4 节写"调度使用预测序列，排放结算使用实际序列"。

但数据只有一条序列：
`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_48slot_calendar.csv`
**只有一列** `carbon_factor_kgco2e_per_kwh`；`solver/src/setp_solver/china81.py:817` 把同一个值
直接标成 `forecast_gco2_per_kwh`。

且该序列本身不是实测：`docs/handoff/ledger_input_provenance_01_20260728/report.md` 的
**L24** 记为**构造情景**——Li 等 S1-2025 省级逐小时投影（Figshare DOI
`10.6084/m9.figshare.28953545.v3`），"不是官方、实测、实时或边际碳强度"；
**L25** 记 `forecast_gco2_per_kwh = actual_gco2_per_kwh` 为**工程假设**，
"任何预测稳健性结论均无数据支撑"。两条均登记"正文是否披露来源类型：**否**"。

⇒ 正文声明的信息结构在数据层面两头落空。

## 二、文献依据

`docs/handoff/dynamic_replanning_literature_20260731/`（Zotero 全库 399 个 PDF 扫描）：

1. **车辆路径论文中未找到任何一篇同时定义"调度用预测碳强度"与"事后结算实际碳强度"**，
   也未找到对电网碳强度预测误差建模并评估其对路径决策影响的论文。严格共现仅 1 篇
   （Cheng 等 2022 arXiv:2209.12373），且为充电站调度、不含路径决策。
2. **有出处的正面写法**：Miyabe, Fujimoto, Hayashi (2025)
   《Journal of Energy Storage》132:117626 第 12 页原文——该路径优化论文对光伏余电走
   "预测调度/实际结算"，但 "**the same pre-calculated values were used for the emission
   factors of the grid at both the planning and evaluation stages**"，并在正文写明这一点。

⇒ 本项目数据的实情正是"两端同一组预先给定的值"；照 Miyabe 的写法显式声明即为有先例的合规表述。

## 三、实际改了什么（12 处，全部在 `docs/paper_v2/paper_main.tex`）

| 位置 | 改前 | 改后 |
|---|---|---|
| 符号表 :360 | $\widehat\gamma_t,\gamma_t$ 预测与实际碳强度 | $\gamma_t$ 电网碳强度 |
| :450 | 模式 $p$ 的**预测**碳排放为 | 模式 $p$ 的碳排放为 |
| eq:carbon :452-453 | $\widehat E_{kp}$、$\widehat\gamma_t$ | $E_{kp}$、$\gamma_t$ |
| :456-457 | "调度时使用预测碳强度，事后结算采用实际碳强度，两者之差刻画预测误差…" | "时段碳强度序列 $\gamma_t$ 在调度与排放核算两端使用同一组预先给定的值，不区分调度用序列与结算用序列。" |
| :465 | 模式 $p$ 的**预测**碳排放 $\widehat E_{kp}$ | 模式 $p$ 的碳排放 $E_{kp}$ |
| :470 (F_1) | $\widehat E_{kp}$ | $E_{kp}$ |
| :514-515 | $\widehat E_{kp}$；**预测**碳排放 | $E_{kp}$；碳排放 |
| :575 | $\widehat E_{kp}$ | $E_{kp}$ |
| :887 | 因此**预测**充电排放关于开始时刻分段线性 | 因此充电排放关于开始时刻分段线性 |
| eq:charging-rule :894 | $\widehat\gamma_t$ | $\gamma_t$ |
| :1040 | 调度使用预测序列，排放结算使用实际序列 | **"该数据集为省级情景投影，不是官方实测、实时或边际碳强度；调度与排放核算两端使用同一组预先给定的序列。"**（同时补上 L24 要求的来源类型披露） |
| :1426 | 按**预测**碳强度选择合法窗口 | 按碳强度选择合法窗口 |
| :1627 (局限) | 碳强度预测误差也未进入模型 | 碳强度序列为省级情景投影且两端同值，其不确定性未进入模型 |

`$E_{kp}$` 此前未被占用（原文只有 $E_q^{\mathrm{ch}}$），无符号冲突。
`:1628` 的未来工作句保留"含碳强度预测误差的滚动场景"——那是展望，不是对本文数据的断言。

## 四、验证

- `rg -n 'widehat|预测' docs/paper_v2/paper_main.tex` 在改后**只剩 :1628 未来工作一处**，
  正文与建模章的预测断言全部清除。
- `latexmk -xelatex` 编译成功，**25 页**（与改前基线一致，未增减页）；
  **未定义引用 0**；无 LaTeX Warning；Overfull/Underfull 计数 **2**，与改前日志逐一致
  （非本轮引入）。

## 五、影响面

- **不触及任何计算**。E4 的充电排放 −54.9704% 由该单一序列算出，数字不变。
- 不使任何封存结果作废。
- 未改动 `solver/` 下任何文件；`china81.py:817` 的 `forecast_gco2_per_kwh` 字段名未动
  （改字段名会触及受保护源码哈希，且与论文表述无关）。**这一点留给后续决定是否重命名。**
