# 算法来源与自研边界表

- 日期：2026-07-18
- 用途：回答“每个算法动作从哪里来、我们改了什么、凭什么算机制设计”
- 当前权限：允许补来源、做隔离开发和最小验证；不允许正式算例、China81、E2--E7 重跑或进入阶段二

## 一句话总故事

外层负责同时保留多个不同方案，避免只围着一个局部好解打转；内层用现有 ALNS 把每个方案修细；四个专用动作分别处理“选什么车和怎么充电”“合作中谁吃亏”“电价与碳排冲突”“新订单来了怎样少推翻旧计划”。外层框架本身不是本文创新，只有专用动作被证明真的解决对应机制、且组合在等算力下同时胜过纯 HGS 和纯 ALNS，才有资格形成论文创新故事。

## 来源、改造与验证责任

| 部分 | 已发表依据 | 本项目要做的实质改造 | 最便宜的证伪办法 |
|---|---|---|---|
| ALNS 内层改进 | Ropke 与 Pisinger（2006）提出按历史表现选择多组拆除/修复动作；Shaw（1998）提出相关客户成组移除 | 保留现有统一评价器、预算账和三阶段搜索，不把通用 ALNS 冒充自研创新 | 预算 0/1/2/5 精确计数；与现有 ALNS 同种子零漂对照 |
| HGS 外层管理 | Vidal 等（2012）给出群体、多样性和局部改进结合；Vidal（2022）公开 HGS-CVRP 与 SWAP* | 外层只管理多个方案和重组，内层局部改进改为 ReSETP ALNS；不得复制官方 C++ 到 Python | 同样完整评价次数下，与纯 HGS、纯 ALNS 三方同场；组合必须双赢 |
| 客户顺序切成路线 | Prins（2004）给出“先形成客户顺序、再切成路线”的动态规划 | 经典方法只懂同车型和简单容量；本项目需把车场、车型、固定出车费和可行充电接入，不能声称照搬即有效 | 先固定同一客户顺序，只比较旧切法与新切法的路线数、成本和违规 |
| 车队与补能动作 | Hiermann 等（2016）的换车型/搬客户同时重选车型；Froger 等（2019）和 Kullman 等（2021）的固定路线非线性充电求解 | 自研“车辆模式后悔修复”：每次插客户时同时比较路线、位置、燃油/电动车和可行充电，再只对少量候选精算 | 人工小例必须发生车型改变或充电改变；与穷举结果一致；无活动即失败 |
| 合作公平动作 | Soriano 等（2023）把利润公平直接放进插入和局部移动 | 自研“公平缺口定向修复”：优先帮助低于参与底线的车场，但完整成本和可行性仍由统一评价器裁决 | 构造一方吃亏的小例；动作必须改善最差一方且不制造违规；只改权重不算 |
| 碳—电价冲突动作 | Montoya 等（2017）、Froger 等（2019）、Liang 等（2021）支持固定路线上的非线性充电优化；Cheng 等（2022）支持碳感知充电 | 自研“双账对照充电”：先分别找最便宜时段和最低碳时段，只对两者冲突大且可移动的充电任务精调 | 同路线、同电量、同窗口下必须实际移动充电；联合结果优于随机移动且无违规 |
| 动态订单动作 | Pillac 等（2012）强调重规划稳定；Wang 等（2024）用车辆当前状态重建后续问题；Vallée 等（2020）用有限连锁腾挪接入难订单 | 自研“冻结前段的有限连锁修复”：已经执行的部分绝不动，只在未执行部分用后悔插入和有限深度腾挪 | 新订单小例中冻结部分逐位不变；可行接单率提高或新增车次减少；超时即失败 |
| 动作选择与接受 | Auer 等（2002）是置信上界选择依据；Kirkpatrick 等（1983）是模拟退火接受依据 | 只作为通用控制方法，不列为论文创新 | 方程、代码、参数和引用一致；关闭后只做控制消融 |

## 论文身份硬门

1. 若收益只来自“多放几个方案一起搜”，而四个机制动作没有独立效果，论文只能诚实称为 HGS 变体，不能讲“机制驱动创新”。
2. 若组合只赢纯 ALNS、却输纯 HGS，说明 ALNS 内层没有给 HGS 增值；若只赢纯 HGS、却输纯 ALNS，说明外层拖累了现有算法。两种情况都不得进入正式试验。
3. 三方比较必须使用相同开发题、配对种子、相同完整方案评价次数和同一最终复算器，同时报告墙钟时间。组合多调用的切分、充电精算和路线重组都必须单独记账，不能藏进“内部步骤”。
4. 最小门只决定“是否值得申请正式试验”，不生成论文性能结论。正式结论仍需用户另行批准后，在冻结测试集上完成。

## 已核原始出处

- Shaw, P. (1998). *Using Constraint Programming and Local Search Methods to Solve Vehicle Routing Problems*. DOI: `10.1007/3-540-49481-2_30`.
- Ropke, S., & Pisinger, D. (2006). *An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows*. DOI: `10.1287/trsc.1050.0135`.
- Auer, P., Cesa-Bianchi, N., & Fischer, P. (2002). *Finite-time Analysis of the Multiarmed Bandit Problem*. DOI: `10.1023/A:1013689704352`.
- Kirkpatrick, S., Gelatt, C. D., & Vecchi, M. P. (1983). *Optimization by Simulated Annealing*. DOI: `10.1126/science.220.4598.671`.
- Prins, C. (2004). *A Simple and Effective Evolutionary Algorithm for the Vehicle Routing Problem*. DOI: `10.1016/S0305-0548(03)00158-8`.
- Vidal, T., Crainic, T. G., Gendreau, M., Lahrichi, N., & Rei, W. (2012). *A Hybrid Genetic Algorithm for Multidepot and Periodic Vehicle Routing Problems*. DOI: `10.1287/opre.1120.1048`.
- Vidal, T. (2022). *Hybrid Genetic Search for the CVRP: Open-source Implementation and SWAP* Neighborhood*. DOI: `10.1016/j.cor.2021.105643`.
- Hiermann, G., Puchinger, J., Ropke, S., & Hartl, R. F. (2016). *The Electric Fleet Size and Mix Vehicle Routing Problem with Time Windows and Recharging Stations*. DOI: `10.1016/j.ejor.2016.01.038`.
- Montoya, A., Guéret, C., Mendoza, J. E., & Villegas, J. G. (2017). *The Electric Vehicle Routing Problem with Nonlinear Charging Function*. DOI: `10.1016/j.trb.2017.02.004`.
- Froger, A., Mendoza, J. E., Jabali, O., & Laporte, G. (2019). *Improved Formulations and Algorithmic Components for the Electric Vehicle Routing Problem with Nonlinear Charging Functions*. DOI: `10.1016/j.cor.2018.12.013`.
- Kullman, N. D., Froger, A., Mendoza, J. E., & Goodson, J. C. (2021). *frvcpy: An Open-source Solver for the Fixed Route Vehicle Charging Problem*. DOI: `10.1287/ijoc.2020.1035`.
- Liang, Y., Dabia, S., & Luo, Z. (2021). *The Electric Vehicle Routing Problem with Nonlinear Charging Functions*. DOI: `10.48550/arXiv.2108.01273`.
- Soriano, A., Gansterer, M., & Hartl, R. F. (2023). *The Multi-depot Vehicle Routing Problem with Profit Fairness*. DOI: `10.1016/j.ijpe.2022.108669`.
- Pillac, V., Gendreau, M., Guéret, C., & Medaglia, A. L. (2012). *An Event-driven Optimization Framework for Dynamic Vehicle Routing*. DOI: `10.1016/j.dss.2012.06.007`.
- Vallée, S., Oulamara, A., & Ramdane Cherif-Khettaf, W. (2020). *New Online Reinsertion Approaches for a Dynamic Dial-a-Ride Problem*. DOI: `10.1016/j.jocs.2020.101199`.
- Wang, S., Sun, W., & Huang, M. (2024). *An Adaptive Large Neighborhood Search for the Multi-depot Dynamic Vehicle Routing Problem with Time Windows*. DOI: `10.1016/j.cie.2024.110122`.

## 当前结论

来源链已经足够支撑“为什么选这些动作”，但来源不能替代效果。最小三方门现已执行：通用组合未稳定胜纯ALNS；多车场开关只在25客户组强，在20和50客户组明显倒退，因此不能宣称组合有效，也不能按已观测规模事后设开关。四个机制动作仍只有隔离功能/活性证据。下一步只允许它们分别在自己的病灶开发门验证独立效果；未过门前不得形成论文创新主张。
