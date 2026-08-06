# X4：车队规模与电动化档位的自有推导

状态：`X4_FLEET_SIZING_PARTIAL`。结论先行：不能把母体的“6”搬入本文，也不能继续用 `ceil(0.25R_d)`。本文可采用“每场 `T_d=max(R_d,R_e)`、实例内按比例机械分配EV名额”的无系数候选设计；0%、25%、50%、75% 四档在81/81实例均有零搜索 witness，100%档在75/81实例有 witness。其余6个200客户成渝/京津冀实例受当前2×22 kW车场充电槽约束而未获认证，因此本任务按停止条件为 PARTIAL，不把“未认证”写成“不可行”。

## 第一部分：母体如何定数

`FACT—陈婉茹等（2023）`。p.3330 §4.2.1 不是直接给定6，而是用式(30)把71个客户的总需求除以两车型较小载重 `min(Q_e,Q_g)`，所得车辆需求再除以6个配送中心并双重向上取整；表7给出 `Q_e=3590 kg`、`Q_g=4480 kg`。所以“每场6辆”绑定总需求、较小载重和车场数，却没有绑定逐场需求不均衡、路网、时间窗、电池或充电。p.3331 §5.1/表9固定同一算例、每场可用总量6和其余参数，只把每场可用CV/EV从6/0扫到0/6；表内实际派遣总量可变。总成本先降后升的可比性来自相同算例与相同可用总量，不是实际出车数恒定。

`FACT—李得成等（2021）`。p.1006 §5.3.1只写“给定车队规模……为6辆车”，没有给出6与15客户需求、载重、时间窗、电池或充电条件的推导。pp.1006–1007固定所选数据与总量6，只把EV可用数0扫到6、CV相应减少；p.1007的结果是同等车队规模下成本下降，EV足够覆盖全部客户后形成平台，不是先降后升。

`FACT—另一种确有机制的定数法`。Hiermann et al. (2016) p.996说明FSMF可设无限可用车辆并对每辆计固定购置成本，p.997定义E-FSMFTW同时选择路线与车型，p.998式(2.1)对每辆实际离场车计购置成本，因此总量和构成由优化内生决定。它可用，但会把本文从“固定资产总量下释放车型替代自由度”改成“车辆购置—路径联合决策”，本任务不采用。

`DECISION`。同类论文可用方法是：总需求/较小载重并按车场分摊（陈婉茹等，p.3330式(30)）；固定总量后扫描构成（李得成等，pp.1006–1007，但其总量6未交代依据）；将车辆购置固定成本纳入目标令总量内生（Hiermann et al., pp.996–998）。本文借用“固定总量、只改构成”的比较原则，不借用数字6。

## 第二部分：本文自己的总车队规模

`FACT—现有R_d的正确性质`。`baselines/china_instances/build_china81_finite_fleet_authority_v2_20260731.py:12-16,111-178`显示，`R_d` 是按 `(due,ready,id)` 排序后的首次可行全CV构造路线数；`:262-280`只证明该构造解可行。它是未知最小车数的可行上界，不是数学下界。当前公式和无出处0.25见 `HANDOFF.md:4193-4206,5465-5477`；`fleet_caps.csv` 的 `fleet_parameter_class=CONSTRUCTED_DEMAND_TIME_WINDOW_ROAD_SCENARIO`、桩参数类为构造情景。

`FACT—输入与核算`。本文逐场先计算严格的全EV载重下界 `ceil(车场总需求/1700)`，再用同一 `(due,ready,id)` 首次可行规则构造EV路线 `R_e`；每条路线同时检查1700 kg、时间窗、77.28 kWh电池、初始电量0、同日发车前恰好够用充电。车型与电量见 `solver/src/setp_solver/china81.py:660-672,884-905`；每场2桩和22 kW见 `:573-579`及 `fleet_caps.csv`；检查器按30分钟槽计同时占用车辆见 `solver/src/setp_solver/check.py:489-550`。两桩排程只做有限状态可行性核算，没有改变客户顺序或启动路径搜索。

`FACT—三条候选判据`。判据一单独沿用 `R_d` 不能普遍成立：144个车场行中140行 `R_e=R_d`，2行 `R_e=R_d+1`，2行 `R_e=R_d-1`；而且6个大实例的固定EV构造还出现充电槽超载。判据二取 `T_d=max(R_d,R_e)`，在75/81实例上把五档全部认证，是当前证据中最强的无系数方案；但不能称为所有可能路线中的数学最小值。判据三的需求/容量式只给出下界，不能保证时间窗、电池和充电；Hiermann式内生总量则需要另一个正式模型与求解，不适合本节单因素设计。

`DECISION`。75个完整认证实例正式推荐 `T_d=max(R_d,R_e)`；其余6个实例仍列同式数值作为可复算暂定值，但不得进入正式五档面板，直到在不放宽约束的前提下得到100%档路线—充电 witness。全表如下，机器可读字段和全部决定量见 `fleet_sizing.json`。

| 算例 | 车场 | 车场客户 | 需求kg | 载重下界 | R_d | R_e | 推荐/候选总量 | 100% EV |
|---|---|---:|---:|---:|---:|---:|---:|---|
| cn-cy-100c-01-V2-LOCATIONS | D_chengdu | 42 | 12013.000 | 8 | 8 | 8 | 8（正式推荐） | 认证 |
| cn-cy-100c-01-V2-LOCATIONS | D_chongqing | 58 | 15280.000 | 9 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-cy-100c-02-V2-LOCATIONS | D_chengdu | 42 | 11877.000 | 7 | 8 | 8 | 8（正式推荐） | 认证 |
| cn-cy-100c-02-V2-LOCATIONS | D_chongqing | 58 | 15064.000 | 9 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-cy-100c-03-V2-LOCATIONS | D_chengdu | 42 | 10975.000 | 7 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-cy-100c-03-V2-LOCATIONS | D_chongqing | 58 | 14862.000 | 9 | 10 | 11 | 11（正式推荐） | 认证 |
| cn-cy-10c-01-V2-LOCATIONS | D_chongqing | 10 | 2360.000 | 2 | 2 | 2 | 2（正式推荐） | 认证 |
| cn-cy-10c-02-V2-LOCATIONS | D_chongqing | 10 | 2779.000 | 2 | 2 | 2 | 2（正式推荐） | 认证 |
| cn-cy-10c-03-V2-LOCATIONS | D_chongqing | 10 | 2709.000 | 2 | 2 | 2 | 2（正式推荐） | 认证 |
| cn-cy-150c-01-V2-LOCATIONS | D_chengdu | 63 | 17017.000 | 11 | 11 | 11 | 11（正式推荐） | 认证 |
| cn-cy-150c-01-V2-LOCATIONS | D_chongqing | 87 | 23405.000 | 14 | 16 | 15 | 16（正式推荐） | 认证 |
| cn-cy-150c-02-V2-LOCATIONS | D_chengdu | 63 | 17291.000 | 11 | 11 | 11 | 11（正式推荐） | 认证 |
| cn-cy-150c-02-V2-LOCATIONS | D_chongqing | 87 | 24373.000 | 15 | 15 | 15 | 15（正式推荐） | 认证 |
| cn-cy-150c-03-V2-LOCATIONS | D_chengdu | 63 | 17015.000 | 11 | 11 | 11 | 11（正式推荐） | 认证 |
| cn-cy-150c-03-V2-LOCATIONS | D_chongqing | 87 | 23752.000 | 14 | 15 | 15 | 15（正式推荐） | 认证 |
| cn-cy-15c-01-V2-LOCATIONS | D_chongqing | 15 | 3749.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-cy-15c-02-V2-LOCATIONS | D_chongqing | 15 | 3751.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-cy-15c-03-V2-LOCATIONS | D_chongqing | 15 | 3610.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-cy-200c-01-V2-LOCATIONS | D_chengdu | 84 | 21463.000 | 13 | 14 | 14 | 14（暂定） | 认证 |
| cn-cy-200c-01-V2-LOCATIONS | D_chongqing | 116 | 31742.000 | 19 | 20 | 20 | 20（暂定） | 未认证 |
| cn-cy-200c-02-V2-LOCATIONS | D_chengdu | 84 | 21601.000 | 13 | 14 | 14 | 14（暂定） | 认证 |
| cn-cy-200c-02-V2-LOCATIONS | D_chongqing | 116 | 31668.000 | 19 | 20 | 20 | 20（暂定） | 未认证 |
| cn-cy-200c-03-V2-LOCATIONS | D_chengdu | 84 | 21806.000 | 13 | 14 | 14 | 14（暂定） | 认证 |
| cn-cy-200c-03-V2-LOCATIONS | D_chongqing | 116 | 33205.000 | 20 | 21 | 21 | 21（暂定） | 未认证 |
| cn-cy-20c-01-V2-LOCATIONS | D_chongqing | 20 | 5487.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-cy-20c-02-V2-LOCATIONS | D_chongqing | 20 | 5139.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-cy-20c-03-V2-LOCATIONS | D_chongqing | 20 | 5417.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-cy-25c-01-V2-LOCATIONS | D_chongqing | 25 | 5971.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-cy-25c-02-V2-LOCATIONS | D_chongqing | 25 | 6806.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-cy-25c-03-V2-LOCATIONS | D_chongqing | 25 | 7083.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-cy-50c-01-V2-LOCATIONS | D_chengdu | 21 | 5834.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-cy-50c-01-V2-LOCATIONS | D_chongqing | 29 | 7432.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-cy-50c-02-V2-LOCATIONS | D_chengdu | 21 | 5417.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-cy-50c-02-V2-LOCATIONS | D_chongqing | 29 | 7150.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-cy-50c-03-V2-LOCATIONS | D_chengdu | 21 | 5833.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-cy-50c-03-V2-LOCATIONS | D_chongqing | 29 | 7987.000 | 5 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-cy-75c-01-V2-LOCATIONS | D_chengdu | 32 | 7777.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-cy-75c-01-V2-LOCATIONS | D_chongqing | 43 | 11112.000 | 7 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-cy-75c-02-V2-LOCATIONS | D_chengdu | 32 | 9168.000 | 6 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-cy-75c-02-V2-LOCATIONS | D_chongqing | 43 | 10555.000 | 7 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-cy-75c-03-V2-LOCATIONS | D_chengdu | 32 | 8125.000 | 5 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-cy-75c-03-V2-LOCATIONS | D_chongqing | 43 | 11110.000 | 7 | 8 | 8 | 8（正式推荐） | 认证 |
| cn-jjj-100c-01-V2-LOCATIONS | D_beijing | 73 | 18958.000 | 12 | 12 | 12 | 12（正式推荐） | 认证 |
| cn-jjj-100c-01-V2-LOCATIONS | D_tianjin | 27 | 7014.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-jjj-100c-02-V2-LOCATIONS | D_beijing | 73 | 19652.000 | 12 | 13 | 12 | 13（正式推荐） | 认证 |
| cn-jjj-100c-02-V2-LOCATIONS | D_tianjin | 27 | 7780.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-jjj-100c-03-V2-LOCATIONS | D_beijing | 73 | 19860.000 | 12 | 13 | 13 | 13（正式推荐） | 认证 |
| cn-jjj-100c-03-V2-LOCATIONS | D_tianjin | 27 | 7221.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-jjj-10c-01-V2-LOCATIONS | D_beijing | 10 | 3196.000 | 2 | 2 | 2 | 2（正式推荐） | 认证 |
| cn-jjj-10c-02-V2-LOCATIONS | D_beijing | 10 | 2431.000 | 2 | 2 | 2 | 2（正式推荐） | 认证 |
| cn-jjj-10c-03-V2-LOCATIONS | D_beijing | 10 | 2570.000 | 2 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-150c-01-V2-LOCATIONS | D_beijing | 98 | 24515.000 | 15 | 16 | 16 | 16（正式推荐） | 认证 |
| cn-jjj-150c-01-V2-LOCATIONS | D_shijiazhuang | 16 | 4166.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-150c-01-V2-LOCATIONS | D_tianjin | 36 | 9515.000 | 6 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-jjj-150c-02-V2-LOCATIONS | D_beijing | 98 | 26532.000 | 16 | 17 | 17 | 17（正式推荐） | 认证 |
| cn-jjj-150c-02-V2-LOCATIONS | D_shijiazhuang | 16 | 3543.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-150c-02-V2-LOCATIONS | D_tianjin | 36 | 9652.000 | 6 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-jjj-150c-03-V2-LOCATIONS | D_beijing | 98 | 26042.000 | 16 | 16 | 17 | 17（正式推荐） | 认证 |
| cn-jjj-150c-03-V2-LOCATIONS | D_shijiazhuang | 16 | 4444.000 | 3 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-jjj-150c-03-V2-LOCATIONS | D_tianjin | 36 | 9512.000 | 6 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-jjj-15c-01-V2-LOCATIONS | D_beijing | 15 | 4305.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-15c-02-V2-LOCATIONS | D_beijing | 15 | 4444.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-15c-03-V2-LOCATIONS | D_beijing | 15 | 4653.000 | 3 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-jjj-200c-01-V2-LOCATIONS | D_beijing | 131 | 35277.000 | 21 | 23 | 23 | 23（暂定） | 未认证 |
| cn-jjj-200c-01-V2-LOCATIONS | D_shijiazhuang | 22 | 5626.000 | 4 | 4 | 4 | 4（暂定） | 认证 |
| cn-jjj-200c-01-V2-LOCATIONS | D_tianjin | 47 | 13476.000 | 8 | 9 | 9 | 9（暂定） | 认证 |
| cn-jjj-200c-02-V2-LOCATIONS | D_beijing | 131 | 36181.000 | 22 | 23 | 23 | 23（暂定） | 未认证 |
| cn-jjj-200c-02-V2-LOCATIONS | D_shijiazhuang | 22 | 6736.000 | 4 | 5 | 5 | 5（暂定） | 认证 |
| cn-jjj-200c-02-V2-LOCATIONS | D_tianjin | 47 | 12015.000 | 8 | 8 | 8 | 8（暂定） | 认证 |
| cn-jjj-200c-03-V2-LOCATIONS | D_beijing | 131 | 35210.000 | 21 | 22 | 22 | 22（暂定） | 未认证 |
| cn-jjj-200c-03-V2-LOCATIONS | D_shijiazhuang | 22 | 6042.000 | 4 | 4 | 4 | 4（暂定） | 认证 |
| cn-jjj-200c-03-V2-LOCATIONS | D_tianjin | 47 | 12153.000 | 8 | 8 | 8 | 8（暂定） | 认证 |
| cn-jjj-20c-01-V2-LOCATIONS | D_beijing | 20 | 4791.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-20c-02-V2-LOCATIONS | D_beijing | 20 | 5348.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-jjj-20c-03-V2-LOCATIONS | D_beijing | 20 | 5280.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-jjj-25c-01-V2-LOCATIONS | D_beijing | 25 | 6042.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-jjj-25c-02-V2-LOCATIONS | D_beijing | 25 | 7015.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-jjj-25c-03-V2-LOCATIONS | D_beijing | 25 | 6878.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-jjj-50c-01-V2-LOCATIONS | D_beijing | 37 | 9931.000 | 6 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-jjj-50c-01-V2-LOCATIONS | D_tianjin | 13 | 3333.000 | 2 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-50c-02-V2-LOCATIONS | D_beijing | 37 | 9932.000 | 6 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-jjj-50c-02-V2-LOCATIONS | D_tianjin | 13 | 3611.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-50c-03-V2-LOCATIONS | D_beijing | 37 | 11114.000 | 7 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-jjj-50c-03-V2-LOCATIONS | D_tianjin | 13 | 3611.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-jjj-75c-01-V2-LOCATIONS | D_beijing | 55 | 15070.000 | 9 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-jjj-75c-01-V2-LOCATIONS | D_tianjin | 20 | 5277.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-jjj-75c-02-V2-LOCATIONS | D_beijing | 55 | 15279.000 | 9 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-jjj-75c-02-V2-LOCATIONS | D_tianjin | 20 | 5002.000 | 3 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-jjj-75c-03-V2-LOCATIONS | D_beijing | 55 | 15417.000 | 10 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-jjj-75c-03-V2-LOCATIONS | D_tianjin | 20 | 4790.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-prd-100c-01-V2-LOCATIONS | D_guangzhou | 46 | 10834.000 | 7 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-prd-100c-01-V2-LOCATIONS | D_shenzhen | 54 | 13609.000 | 9 | 9 | 9 | 9（正式推荐） | 认证 |
| cn-prd-100c-02-V2-LOCATIONS | D_guangzhou | 46 | 12292.000 | 8 | 8 | 8 | 8（正式推荐） | 认证 |
| cn-prd-100c-02-V2-LOCATIONS | D_shenzhen | 54 | 15699.000 | 10 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-prd-100c-03-V2-LOCATIONS | D_guangzhou | 46 | 11318.000 | 7 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-prd-100c-03-V2-LOCATIONS | D_shenzhen | 54 | 15002.000 | 9 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-prd-10c-01-V2-LOCATIONS | D_shenzhen | 10 | 3403.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-prd-10c-02-V2-LOCATIONS | D_shenzhen | 10 | 2292.000 | 2 | 2 | 2 | 2（正式推荐） | 认证 |
| cn-prd-10c-03-V2-LOCATIONS | D_shenzhen | 10 | 2224.000 | 2 | 2 | 2 | 2（正式推荐） | 认证 |
| cn-prd-150c-01-V2-LOCATIONS | D_dongguan | 20 | 5695.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-150c-01-V2-LOCATIONS | D_foshan | 21 | 5139.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-150c-01-V2-LOCATIONS | D_guangzhou | 50 | 13474.000 | 8 | 9 | 9 | 9（正式推荐） | 认证 |
| cn-prd-150c-01-V2-LOCATIONS | D_shenzhen | 59 | 15903.000 | 10 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-prd-150c-02-V2-LOCATIONS | D_dongguan | 20 | 5417.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-150c-02-V2-LOCATIONS | D_foshan | 21 | 5625.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-150c-02-V2-LOCATIONS | D_guangzhou | 50 | 14098.000 | 9 | 9 | 9 | 9（正式推荐） | 认证 |
| cn-prd-150c-02-V2-LOCATIONS | D_shenzhen | 59 | 15347.000 | 10 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-prd-150c-03-V2-LOCATIONS | D_dongguan | 20 | 5209.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-150c-03-V2-LOCATIONS | D_foshan | 21 | 5557.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-150c-03-V2-LOCATIONS | D_guangzhou | 50 | 12014.000 | 8 | 8 | 8 | 8（正式推荐） | 认证 |
| cn-prd-150c-03-V2-LOCATIONS | D_shenzhen | 59 | 15346.000 | 10 | 10 | 10 | 10（正式推荐） | 认证 |
| cn-prd-15c-01-V2-LOCATIONS | D_shenzhen | 15 | 4234.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-prd-15c-02-V2-LOCATIONS | D_shenzhen | 15 | 3820.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-prd-15c-03-V2-LOCATIONS | D_shenzhen | 15 | 4096.000 | 3 | 3 | 3 | 3（正式推荐） | 认证 |
| cn-prd-200c-01-V2-LOCATIONS | D_dongguan | 26 | 7361.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-200c-01-V2-LOCATIONS | D_foshan | 29 | 8055.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-200c-01-V2-LOCATIONS | D_guangzhou | 66 | 17293.000 | 11 | 11 | 11 | 11（正式推荐） | 认证 |
| cn-prd-200c-01-V2-LOCATIONS | D_shenzhen | 79 | 22014.000 | 13 | 14 | 14 | 14（正式推荐） | 认证 |
| cn-prd-200c-02-V2-LOCATIONS | D_dongguan | 26 | 8127.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-200c-02-V2-LOCATIONS | D_foshan | 29 | 7570.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-200c-02-V2-LOCATIONS | D_guangzhou | 66 | 19372.000 | 12 | 12 | 12 | 12（正式推荐） | 认证 |
| cn-prd-200c-02-V2-LOCATIONS | D_shenzhen | 79 | 20902.000 | 13 | 14 | 14 | 14（正式推荐） | 认证 |
| cn-prd-200c-03-V2-LOCATIONS | D_dongguan | 26 | 7013.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-200c-03-V2-LOCATIONS | D_foshan | 29 | 8474.000 | 5 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-prd-200c-03-V2-LOCATIONS | D_guangzhou | 66 | 19241.000 | 12 | 12 | 12 | 12（正式推荐） | 认证 |
| cn-prd-200c-03-V2-LOCATIONS | D_shenzhen | 79 | 21389.000 | 13 | 13 | 13 | 13（正式推荐） | 认证 |
| cn-prd-20c-01-V2-LOCATIONS | D_shenzhen | 20 | 5140.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-20c-02-V2-LOCATIONS | D_shenzhen | 20 | 5416.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-20c-03-V2-LOCATIONS | D_shenzhen | 20 | 5695.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-25c-01-V2-LOCATIONS | D_shenzhen | 25 | 6459.000 | 4 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-25c-02-V2-LOCATIONS | D_shenzhen | 25 | 7013.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-25c-03-V2-LOCATIONS | D_shenzhen | 25 | 6668.000 | 4 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-50c-01-V2-LOCATIONS | D_guangzhou | 23 | 5347.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-50c-01-V2-LOCATIONS | D_shenzhen | 27 | 6876.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-50c-02-V2-LOCATIONS | D_guangzhou | 23 | 5626.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-50c-02-V2-LOCATIONS | D_shenzhen | 27 | 7221.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-50c-03-V2-LOCATIONS | D_guangzhou | 23 | 6251.000 | 4 | 4 | 4 | 4（正式推荐） | 认证 |
| cn-prd-50c-03-V2-LOCATIONS | D_shenzhen | 27 | 7362.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-75c-01-V2-LOCATIONS | D_guangzhou | 34 | 8126.000 | 5 | 5 | 5 | 5（正式推荐） | 认证 |
| cn-prd-75c-01-V2-LOCATIONS | D_shenzhen | 41 | 12223.000 | 8 | 8 | 8 | 8（正式推荐） | 认证 |
| cn-prd-75c-02-V2-LOCATIONS | D_guangzhou | 34 | 8889.000 | 6 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-prd-75c-02-V2-LOCATIONS | D_shenzhen | 41 | 11391.000 | 7 | 7 | 7 | 7（正式推荐） | 认证 |
| cn-prd-75c-03-V2-LOCATIONS | D_guangzhou | 34 | 9583.000 | 6 | 6 | 6 | 6（正式推荐） | 认证 |
| cn-prd-75c-03-V2-LOCATIONS | D_shenzhen | 41 | 12294.000 | 8 | 8 | 8 | 8（正式推荐） | 认证 |

`HALT—六个边界`。当前固定EV路线构造的必要累计桩槽条件已经失败：

cn-cy-200c-01-V2-LOCATIONS / D_chongqing：前 14 个发车作业需 55 个半小时桩槽，可提供 52 个，超出 3 个。
cn-cy-200c-02-V2-LOCATIONS / D_chongqing：前 14 个发车作业需 55 个半小时桩槽，可提供 52 个，超出 3 个。
cn-cy-200c-03-V2-LOCATIONS / D_chongqing：前 14 个发车作业需 56 个半小时桩槽，可提供 52 个，超出 4 个。
cn-jjj-200c-01-V2-LOCATIONS / D_beijing：前 15 个发车作业需 54 个半小时桩槽，可提供 52 个，超出 2 个。
cn-jjj-200c-02-V2-LOCATIONS / D_beijing：前 14 个发车作业需 53 个半小时桩槽，可提供 52 个，超出 1 个。
cn-jjj-200c-03-V2-LOCATIONS / D_beijing：前 14 个发车作业需 54 个半小时桩槽，可提供 52 个，超出 2 个。

这些超载证明当前固定路线集不能在两桩、同日发车前完成充电；不同路线分组可能改变充电量与发车截止，因此不能升级为全局不可行结论。

## 第三部分：电动化档位

`DECISION`。采用比例而非绝对辆数，设0%、25%、50%、75%、100%五档。绝对辆数会使10至200客户、1至4车场的相同数字代表完全不同资产强度；比例把“可替代油电运力份额”保持为同一处理。每个实例先按 `round_half_up(p×Σ_dT_d)` 得EV总名额，再用Hamilton最大余数法按 `pT_d` 分到车场，平余数按车场ID；CV名额为 `T_d-EV_d`。这是一条整数化规则，不引入经验系数。

`FACT`。零搜索核算的逐档覆盖为：0%=81/81，25%=81/81，50%=81/81，75%=81/81，100%=75/81。边界档都保留；6个100%未认证行在表中显示 `NOT_CERTIFIED` 及桩槽不足原因，不删除、不改载重、时间窗、电池、桩数、功率或服务时域。完整405个“实例×档位”记录见 `levels_design.json`。

`INFERENCE—服务第5.2节`。表的处理变量应是“可用EV比例”，同时报告可用与实际派遣CV/EV、路线/车型是否改变、充电开始时刻是否改变、成本和系统排放。这样才能识别：低电动化档时变碳强度是否主要通过充电择时起作用，名额增加后作用是否转向车型指派和路线重组；只报“EV越多排放越低”不能回答该主张。

## 第四部分：与现有E4/E6的关系

`DECISION`。现有结果不作废：E4固定路线择时仍是冻结405个解上的真实时序效应，E4联合面板与E6仍是旧构造车队上限下的真实结果。但它们不能自动当作新档位特例。旧口径是每场 `CV=R_d` 再额外给 `EV=ceil(0.25R_d)`，0.25不是总车队EV占比，且总分母通常大于新 `T_d`；E4 180/180、E6 1909/1920个车场—解单元触及EV上限（`docs/handoff/memory/codex_audit_independent_verification_20260802.md:24-28`），说明边界是活跃约束。E4联合面板中 `COST_PLUS_CARBON` 相对 `COST_ONLY` 只有2/30改变路线或车型（`formal_panel_20260801/decision.json:5-12`），只能解释旧边界下的响应。

只有四个条件同时成立，旧结果才可作为某一新档的特例：逐场CV/EV可用向量与该档机械向量完全相等；保存解在新上限和同一物理/充电/checker合同下复验通过；所有比较臂共享同一总量与构成；若只是某个保存解碰巧装得下而可行域不同，只能称可行 witness，不能称该档优化结果。当前没有完成这种逐行等价，因此 `legacy_relation.json` 的结论是“保留为legacy constructed-cap evidence，不映射新档”。

## 终局

`HALT`。81个算例全部完成了需求载重下界、CV/EV确定性构造和五档核算；但100%档只认证75个实例。按任务停止条件，状态为 `X4_FLEET_SIZING_PARTIAL`，未启动路径搜索或正式实验，`search_evaluations=0`。
