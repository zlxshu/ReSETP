# ReSETP 图表样板数据契约

所有 mock 数值均为样例数据/非实验结果。正式重跑只能按本契约灌入 CSV，不得在表图层修改结论。全文碳口径只使用：直接排放（燃油）、充电间接排放、总排放（=两者之和）。

## T1

本表证明：算例规模、碳强度槽和数据锚点可核验。

CSV：`mock_data/t1_instances.csv`

字段：
- `instance`：算例
- `customers`：客户数
- `depots`：车场数
- `stations`：充电站数
- `total_demand_kg`：总需求/kg
- `window_width_h`：平均时间窗宽/h
- `isolated_customer_share_pct`：孤立客户占比/\%
- `gamma_slots`：$\gamma$槽数
- `anchor_day`：碳强度锚定日

## T3

本表证明：主算法在相同预算下相对文献基线更优且有统计标记。

CSV：`mock_data/t3_algorithm_comparison.csv`

字段：
- `instance`：算例
- `algorithm`：算法
- `best`：最优/£
- `mean`：均值/£
- `std`：标准差
- `observed_gap_pct`：相对已观测最优偏差/\%
- `feasible_rate_pct`：可行率/\%
- `equal_eval_time_s`：等eval耗时/s
- `equal_wallclock_score`：等墙钟成绩
- `significance`：显著性

## T4

本表证明：混合车队在成本与两类排放之间形成可解释折中。

CSV：`mock_data/t4_solution_decomposition.csv`

字段：
- `metric`：指标
- `cv_only`：仅油车
- `ev_only`：仅电车
- `mixed`：混合

## T5

本表证明：每个建模层都有可见边际贡献。

CSV：`mock_data/t5_ablation.csv`

字段：
- `step`：消融层级
- `mean_std_cost`：成本均值±std/£
- `delta_vs_full_pct`：相对完整模型Δ/\%
- `significance`：显著性
- `total_carbon_kg`：总排放/kgCO$_2$e
- `ev_routes`：电车路线数
- `cross_site_customers`：跨场服务数
- `min_fairness_ratio`：最小公平比

## T6

本表证明：减排来自车队电动化与充电择时两层。

CSV：`mock_data/t6_two_layer_carbon.csv`

字段：
- `case`：方案
- `total_cost`：总成本/£
- `diesel_carbon_kg`：直接排放（燃油）/kgCO$_2$e
- `charging_carbon_kg`：充电间接排放/kgCO$_2$e
- `total_carbon_kg`：总排放/kgCO$_2$e
- `mean_intensity_gco2_per_kwh`：充电加权碳强度/(gCO$_2$/kWh)
- `delta_emission_prev_pct`：相对上一行Δ排放/\%

## T7

本表证明：现实邻域碳价只产生边际响应。

CSV：`mock_data/t7_carbon_sensitivity.csv`

字段：
- `carbon_price_level`：碳价档
- `total_cost`：总成本/£
- `fuel_liters`：燃油量/L
- `charging_kwh`：充电量/kWh
- `charging_centroid_h`：充电时段重心/h
- `carbon_trading_cost`：碳交易成本/£
- `diesel_carbon_kg`：直接排放（燃油）/kgCO$_2$e
- `charging_carbon_kg`：充电间接排放/kgCO$_2$e
- `total_carbon_kg`：总排放/kgCO$_2$e
- `ev_routes`：电车路线数

## T8

本表证明：公平约束有代价曲线和可行边界。

CSV：`mock_data/t8_fairness_threshold.csv`

字段：
- `theta`：$\theta$
- `pi_ratio_by_depot`：各场$\Pi_d/\Pi_d^0$
- `min_ratio`：最小比值
- `total_cost`：总成本/£
- `total_carbon_kg`：总排放/kgCO$_2$e
- `cross_site_customers`：跨场服务数
- `feasible`：可行

## T9

本表证明：动态重规划状态闭合且三机制持续参与。

CSV：`mock_data/t9_dynamic.csv`

字段：
- `event_flow`：事件流
- `event_counts`：事件数(新增/取消/变更)
- `replans`：重规划次数
- `final_cost`：最终成本/£
- `hindsight_cost`：静态后见基线/£
- `information_cost`：信息成本
- `total_carbon_kg`：总排放/kgCO$_2$e
- `cross_site_customers`：跨场服务数
- `min_fairness_ratio`：公平比最低值
- `low_carbon_charge_share_pct`：低碳时段充电占比/\%
- `conservation_audit`：守恒审计

## F1 主解路线图
本图证明：混合车队分工与跨场协同的空间形态。CSV：`f1_route_nodes.csv`, `f1_route_lines.csv`。

## F2 算法性能
本图证明：主算法收敛更快、终值更优更稳。重跑硬要求：逐 eval 收敛日志、seed、参考已观测最优、等墙钟账本。

## F3 两层减碳
本图证明：同 T6 的三行链条能分解动力替换与充电择时的贡献。

## F4 48槽碳强度与充电负荷
本图证明：碳感知充电把充电量移向低碳时段。

## F5 碳价响应
本图证明：现实邻域边际起效，宽域压力下才出现明显阈值。

## F6 公平前沿
本图证明：公平收紧会压缩协同空间并提高成本；重跑硬要求：θ 细网格覆盖 binding 区间。

## F7 动态时间线
本图证明：事件到达触发重规划，同时协同、公平和低碳充电在阶段间持续活跃；重跑硬要求：事件、冻结段、静态后见基线、阶段公平比、跨场服务数、低碳时段充电占比。

若真实数据中协同≈0、公平不 binding 或动态三交互缺列，结论应为实验设计回炉，不得靠表格掩饰。
