# SEL：贯通全文的唯一代表算例事先选择

终态：`SEL_REPRESENTATIVE_INSTANCE_COMPLETE`

## 结论

`DECISION`：唯一代表算例冻结为 **`cn-cy-100c-01-V2-LOCATIONS`**，冻结时刻为 **2026-08-03T01:10:38+08:00**。规则先于候选身份展开写入 `selection_rule.json`；其 SHA-256 为 `020f270ea8308388c106ec24ea76173ae3c4b6528de1b29c0ec96f0e29c26293`。此后不得因任何新实验的方向、幅度、显著性或图形效果更换算例、种子、阈值或口径。

这不是“旧结果最好看”的算例。规则先把代表题限制在目标期刊既有的 51--149 客户私有算例形态，再要求四个判别维度全部达到事先由 81 题分布确定的阈值；合格后只按客户数最大和字典序破同规模并列。共有 7 题合格，其中 6 题为 100 客户；所选题只是冻结破同分规则的首项。

## 证据覆盖与零搜索边界

`FACT`：判别力矩阵完整覆盖 81 题。算法先验为 2025 行旧车型记录；车队为 authority v3 的 405 行全 `CERTIFIED` 零搜索见证；碳择时为 44,072 条动作--日期审计；动态为 H0/G2 冻结生成器在 81 题×5 流上的 405 条流、5805 条事件统计。SEL 没有调用路线求解、元启发式或正式实验，搜索评价数为 0。

旧算法批采用 140.41 kWh 车型和旧车队上限，所以只决定“是否有组件判别空间”，不作为现行车型效果。碳维度同样只使用固定路线动作的可移动窗口与低/高碳机会，不把旧成本或减排百分比当选例排名。

## 先冻结的规则

四个阈值为：M→MV 在 5 个旧种子中至少 3 个严格改善（81 题上四分位数，同时也是非零支持集下四分位数）；五档实际派遣 CV/EV 构成的 L1 直径至少 14（全体中位数）；至少 15 个唯一充电动作在 28 日中出现过较 ASAP 更低碳的可选时点（全体中位数）；H0/G2 每流至少 10 个新订单（全体中位数），且事件后 `due−appear` 的题内 P10 至少 5206.138 秒（全体题内 P10 的下四分位数）。完整定义、容差、分位数方法、哈希与不放宽规则见 `selection_rule.json`。

## 所选题的四维取值

| 维度 | 取值 | 阈值 | 来源 |
|---|---:|---:|---|
| 算法部件 | M→MV 改善 5/5，持平 0，退化 0；平均旧成本差 2.872300 元 | ≥3 个种子 | `baselines/algorithm_prototypes/china81_vs_opensource_20260727/raw_runs.json` |
| 车队五档 | 可用构成 L1 跨度 32；实派构成 L1 跨度 27 | 实派跨度 ≥14 | `baselines/china_e3_e7/fleet_authority_v3_20260802/raw_runs.csv` |
| 碳择时 | 25/25 个唯一充电动作有低碳时点机会；动作--日 696/700；窗口中位数 37274.959 秒 | ≥15 个动作 | `baselines/china_e3_e7/e4_carbon_timing_20260729/action_timing_audit.csv` |
| 动态 | 每流 20 个新订单；`due−appear` P10=5968.646 秒、中位数=15956.273 秒；`ready−appear` P10=2988.208 秒 | ≥10 且 P10≥5206.138 秒 | `baselines/china_e3_e7/e7_h0_g2_foundation_20260801/stream.py` + 本题 nodes.csv |

结构中性量为：100 个客户、2 个车场、2 个公共充电站、总需求 27293 kg；客户时间窗宽度中位数 2861.030 秒；服务节点有向路网最大跨度 341.962 km。这些量完整写入矩阵，但没有构造加权“综合得分”。

五档可用/实派 CV--EV 依次为：0% `16/0 → 12/0`，25% `12/4 → 12/0`，50% `8/8 → 8/7`，75% `4/12 → 3/12`，100% `0/16 → 0/15`。

## 合格候选与落选原因

| 算例 | 客户 | 算法 | 车队跨度 | 碳机会动作 | 动态订单 / due P10秒 | 处理 |
|---|---:|---:|---:|---:|---:|---|
| cn-cy-100c-01-V2-LOCATIONS | 100 | 5 | 27 | 25 | 20 / 5968.646 | 选中 |
| cn-cy-100c-02-V2-LOCATIONS | 100 | 3 | 27 | 25 | 20 / 6588.292 | same_maximum_customer_count_but_later_in_frozen_lexicographic_tiebreak |
| cn-cy-100c-03-V2-LOCATIONS | 100 | 3 | 24 | 25 | 20 / 6655.821 | same_maximum_customer_count_but_later_in_frozen_lexicographic_tiebreak |
| cn-jjj-100c-01-V2-LOCATIONS | 100 | 5 | 24 | 27 | 20 / 5545.153 | same_maximum_customer_count_but_later_in_frozen_lexicographic_tiebreak |
| cn-jjj-100c-02-V2-LOCATIONS | 100 | 5 | 29 | 30 | 20 / 6139.258 | same_maximum_customer_count_but_later_in_frozen_lexicographic_tiebreak |
| cn-prd-100c-02-V2-LOCATIONS | 100 | 3 | 26 | 28 | 20 / 6467.931 | same_maximum_customer_count_but_later_in_frozen_lexicographic_tiebreak |
| cn-jjj-75c-03-V2-LOCATIONS | 75 | 3 | 17 | 20 | 15 / 5927.850 | smaller_customer_count |

因此 `cn-cy-100c-02/03`、`cn-jjj-100c-01/02` 与 `cn-prd-100c-02` 都不是判别力不足，而是与所选题同为 100 客户后落在冻结字典序之后；`cn-jjj-75c-03` 四维合格，但客户数小于合格的 100 客户题。

另有下列规模域内题仅差一个阈值；全部恰好缺算法部件判别力，未用其余三维的较大数值补偿：

| 算例 | 客户 | 未过维度 | 实测 | 阈值 |
|---|---:|---|---|---|
| cn-jjj-100c-03-V2-LOCATIONS | 100 | algorithm_component | 2 | 3 |
| cn-prd-100c-01-V2-LOCATIONS | 100 | algorithm_component | 0 | 3 |
| cn-prd-100c-03-V2-LOCATIONS | 100 | algorithm_component | 1 | 3 |
| cn-cy-75c-01-V2-LOCATIONS | 75 | algorithm_component | 0 | 3 |
| cn-cy-75c-02-V2-LOCATIONS | 75 | algorithm_component | 0 | 3 |
| cn-cy-75c-03-V2-LOCATIONS | 75 | algorithm_component | 2 | 3 |
| cn-jjj-75c-02-V2-LOCATIONS | 75 | algorithm_component | 2 | 3 |
| cn-prd-75c-01-V2-LOCATIONS | 75 | algorithm_component | 0 | 3 |
| cn-prd-75c-02-V2-LOCATIONS | 75 | algorithm_component | 0 | 3 |
| cn-prd-75c-03-V2-LOCATIONS | 75 | algorithm_component | 0 | 3 |

## 其余 80 题稳定性校验

`DECISION`：新实验不得反向重开选例。代表题按目标期刊的 10 次运行形态承担正文展品；其余 80 题对同一合同做稳定性校验并进入完整附录。每题、每方法/变体/档位/策略固定 10 次：算法五方法 4000 次搜索，三变体消融 2400 次，五档车队 4000 次，动态三策略 2400 个日场景（1 次预优化+3 次调整，等价 9600 次求解调用）；碳择时复用每题 10 个完整方法保存解，在冻结的 28 个 2025 年 2 月日期上做 ASAP/CARBON 共 44,800 次零搜索重打分。

10 次依据来自陈婉茹等（2023）p.3328；完整+两个删除变体来自该文 p.3331 表8；车队配置来自 p.3331 表9及李得成等（2021）pp.1006--1007；动态三策略×10来自姜广田等（2024）p.2377 表14，种群120/最多2000代来自 p.2372，三个调整时点来自 pp.2373--2374。陈雨蝶等（2025）pp.13--14 表6也使用单一私有算例、三算法、10次逐次报告。80 题是用户指定的稳定性总体，不冒充期刊强制数量；碳的 28 日来自已冻结完整月份，不冒充目标期刊设置。

稳定性汇总的统计单位是算例：每题先汇总 10 个种子，再在 80 题上报告改善/持平/退化/不可执行数及中位数、四分位距；完整 80 行逐题表进入附录。失败、未找到、零效应与反向效应不得删除，也不得把种子或日期膨胀成独立算例。

若稳定性校验显示某项效应只存在于 **`cn-cy-100c-01-V2-LOCATIONS`**，结果与讨论必须明确写出“该效应只在事先选定的代表算例出现”，不得隐去、换题或改口径。

## 冻结登记与交付

`selection_rule.json` 是先冻结规则；`discriminating_power_matrix.json` 是 81×4 完整矩阵；`selected_instance.json` 保存选定值、7 个合格候选与单阈值近似候选；`stability_check_plan.json` 保存 80 题名单、规模、报告量和出处；`done.json` 与 `artifact_hashes.json` 负责终态及逐文件闭合。

`SEL_REPRESENTATIVE_INSTANCE_COMPLETE`
