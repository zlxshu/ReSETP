# 算法来源与自研边界表

- 日期：2026-07-18
- 用途：回答“每个算法动作从哪里来、我们改了什么、凭什么算机制设计”
- 当前权限：允许补来源、做隔离开发和最小验证；不允许正式算例、China81、E2--E7 重跑或进入阶段二

## 一句话总故事

当前候选不再讲“HGS 和 ALNS 拼在一起”。ALNS 负责把客户分组、排顺序；专用步骤分别处理“每条路线用什么车、怎样充电”“合作中谁吃亏”“电价与碳排冲突”“新订单来了怎样少推翻旧计划”。官方 HGS 保留为必须击败的强开源对照，不再冒充内部贡献。只有某个专用步骤在拿掉它之后确实变差，而且整套算法在同算力下胜过原装开源对照和当前项目 ALNS，那个机制才有资格进入论文故事。

## 来源、改造与验证责任

| 部分 | 已发表依据 | 本项目要做的实质改造 | 最便宜的证伪办法 |
|---|---|---|---|
| ALNS 内层改进 | Ropke 与 Pisinger（2006）提出按历史表现选择多组拆除/修复动作；Shaw（1998）提出相关客户成组移除 | 保留现有统一评价器、预算账和三阶段搜索，不把通用 ALNS 冒充自研创新 | 预算 0/1/2/5 精确计数；与现有 ALNS 同种子零漂对照 |
| HGS 强开源对照 | Vidal 等（2012）给出群体、多样性和局部改进结合；Vidal（2022）公开 HGS-CVRP 与 SWAP* | 固定官方 C++ 提交，通过同一中性转换进入开发对照；直接插入和路线育种都未证明贡献，所以不再列为候选内部组件 | 同题、同种子、同完整评价次数下，候选必须严格胜官方 HGS；直接接入还必须胜“拿掉 HGS”的版本，否则删除该接入 |
| “通用搜索框架 + 问题专用动作”的设计法 | Liu、Luo 与 Yu（2024）把遗传搜索和大邻域搜索结合并让参数/接受规则随实例调整；Zhao、Archetti、Pham 与 Vidal（2025）为库存—路径耦合专门设计整户访问移除—重插动作，再放入 HGS | 只借“先找真实耦合病灶，再做专用动作并拆件验证”的研究方法；不把换框架本身当创新，也不照搬其问题、代码或结论 | 每个动作单独设一个会触发该病灶的小门；完整版必须严格胜拿掉该动作的版本 |
| 客户顺序切成路线 | Prins（2004）给出“先形成客户顺序、再切成路线”的动态规划 | 经典方法只懂同车型和简单容量；本项目需把车场、车型、固定出车费和可行充电接入，不能声称照搬即有效 | 先固定同一客户顺序，只比较旧切法与新切法的路线数、成本和违规 |
| 车队与补能动作 | Hiermann 等（2016）的换车型/搬客户同时重选车型；Froger 等（2019）和 Kullman 等（2021）的固定路线非线性充电求解 | 已实现“车型—充电整套方案选择”：先为各路线生成可行燃油车/电动车方案，再在所有路线之间一次选完整组合；局部代理只筛选，最佳完整组合只接受一次统一评分 | 预算账和独立复算均闭合；在当前静态门中，25/50客户六项为绑定严格改善，20客户三项联合选择不绑定。整套v7仍9/9胜当前ALNS，结论只限开发面 |
| 多车场责任动作 | Soriano 等（2023）把多车场合作、利润分配和跨场访问放入同一资源受限路径问题 | 自研“跨场责任重分配”：只在不同车场路线间做客户移交或双方互换，先按距离和归属便宜筛选，再用真实路线账核算；最终与完全绕过该步骤的下游分支取较优者 | 10--75客户十八项中4项绑定并改善1.265%--5.673%，14项精确零倒退；三个强对照任务为事后确认，不作正式抽样 |
| 合作公平动作 | Soriano 等（2023）把利润公平直接放进插入和局部移动 | 自研“公平缺口定向修复”：以各车场最强独立经营收益为基准，低于100%才定向移交客户；先消除归一化缺口，再选代价最低的合格方案 | 20客户三种子中1项绑定并修复、2项已达标且零动作；完整搜索预算不变、收益账另计。当前只证明行为和一个绑定效果，不证明统计稳定性 |
| 充电碳时机动作 | Cheng 等（2022）在车辆可用时间、变压器与电池约束下优化碳感知充电；Froger 等（2019）和 Kullman 等（2021）支持把固定路线充电子问题嵌入大搜索 | 固定路线、车型、电量和充电时长，只枚举可行窗口端点、碳信号断点及反向对齐点，寻找最低真实碳账的开始时刻；不把它冒充尚未实现的非线性充电或分时电价联合优化 | 旧20客户平台从621.291324降到621.083114且零违规；v6碳择时相对删减版9/9严格改善、完整路线搜索评价增加0。分时电价和非线性曲线仍等阶段二接口 |
| 动态订单动作 | Pillac 等（2012）强调重规划稳定；Wang 等（2024）用车辆当前状态重建后续问题；Vallée 等（2020）用有限连锁腾挪接入难订单 | 自研“冻结前段的有限连锁修复”：已经执行和在途部分绝不动，先把新增订单放入可编辑未来路线；直接放不下时才启用有界后悔—弹射链 | 冻结E7单事件中57个位置有8个可行，最佳方案未来路线少1条、成本降29.675379；0/1/2/5深度二功能账重新验签。一个事件不能替代正式动态统计 |
| 动作选择与接受 | Auer 等（2002）是置信上界选择依据；Kirkpatrick 等（1983）是模拟退火接受依据 | 只作为通用控制方法，不列为论文创新 | 方程、代码、参数和引用一致；关闭后只做控制消融 |
| 算子选择稳定底盘 | Ropke、Pisinger（2006）及Pisinger、Ropke（2007）用分段轮盘按每次调用的平均成绩更新算子权重；Wouda、Lan（2023）提供成熟ALNS软件接口 | 项目独立实现“平均成绩分段轮盘”，只修复通用搜索的早期垄断，不把它包装成机制创新；Softmax组合已因旧题训练明显倒退而停止 | 先在已知垄断旧题做2起点×3种子×400次的短门；只有成本、覆盖和墙钟同时过门才允许旧题交叉确认 |

## 论文身份硬门

1. 若收益只来自换一个通用搜索框架，而专用动作没有独立效果，就不能讲“机制驱动创新”。本轮 HGS 直接插入已按此规则删除。
2. 候选若只赢当前 ALNS、却输原装 HGS 或原装 ALNS，未达到 E2 的开源底线；若只赢原装开源对照、却不能稳定胜当前项目 ALNS，也不能替换现有算法。两种情况都不得进入正式试验。
3. 五方比较必须使用相同开发题、配对种子、相同完整方案评价次数和同一最终复算器，同时报告墙钟时间。代理筛选、充电求解和路线重组都必须单独记账，不能藏进“内部步骤”。
4. 最小门只决定“是否值得申请正式试验”，不生成论文性能结论。正式结论仍需用户另行批准后，在冻结测试集上完成。

## 已核原始出处

- Shaw, P. (1998). *Using Constraint Programming and Local Search Methods to Solve Vehicle Routing Problems*. DOI: `10.1007/3-540-49481-2_30`.
- Ropke, S., & Pisinger, D. (2006). *An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows*. DOI: `10.1287/trsc.1050.0135`.
- Pisinger, D., & Ropke, S. (2007). *A General Heuristic for Vehicle Routing Problems*. DOI: `10.1016/j.cor.2005.09.012`.
- Auer, P., Cesa-Bianchi, N., & Fischer, P. (2002). *Finite-time Analysis of the Multiarmed Bandit Problem*. DOI: `10.1023/A:1013689704352`.
- Wouda, N. A., & Lan, L. (2023). *ALNS: a Python implementation of the adaptive large neighbourhood search metaheuristic*. DOI: `10.21105/joss.05028`.
- Kirkpatrick, S., Gelatt, C. D., & Vecchi, M. P. (1983). *Optimization by Simulated Annealing*. DOI: `10.1126/science.220.4598.671`.
- Prins, C. (2004). *A Simple and Effective Evolutionary Algorithm for the Vehicle Routing Problem*. DOI: `10.1016/S0305-0548(03)00158-8`.
- Vidal, T., Crainic, T. G., Gendreau, M., Lahrichi, N., & Rei, W. (2012). *A Hybrid Genetic Algorithm for Multidepot and Periodic Vehicle Routing Problems*. DOI: `10.1287/opre.1120.1048`.
- Vidal, T. (2022). *Hybrid Genetic Search for the CVRP: Open-source Implementation and SWAP* Neighborhood*. DOI: `10.1016/j.cor.2021.105643`.
- Liu, W., Luo, Y., & Yu, Y. (2024). *An Adaptive Hybrid Genetic and Large Neighborhood Search Approach for Multi-Attribute Vehicle Routing Problems*. arXiv: `2402.18903`.
- Zhao, J., Archetti, C., Pham, T. A., & Vidal, T. (2025). *Large Neighborhood and Hybrid Genetic Search for Inventory Routing Problems*. arXiv: `2506.03172`.
- Hiermann, G., Puchinger, J., Ropke, S., & Hartl, R. F. (2016). *The Electric Fleet Size and Mix Vehicle Routing Problem with Time Windows and Recharging Stations*. DOI: `10.1016/j.ejor.2016.01.038`.
- Montoya, A., Guéret, C., Mendoza, J. E., & Villegas, J. G. (2017). *The Electric Vehicle Routing Problem with Nonlinear Charging Function*. DOI: `10.1016/j.trb.2017.02.004`.
- Froger, A., Mendoza, J. E., Jabali, O., & Laporte, G. (2019). *Improved Formulations and Algorithmic Components for the Electric Vehicle Routing Problem with Nonlinear Charging Functions*. DOI: `10.1016/j.cor.2018.12.013`.
- Kullman, N. D., Froger, A., Mendoza, J. E., & Goodson, J. C. (2021). *frvcpy: An Open-source Solver for the Fixed Route Vehicle Charging Problem*. DOI: `10.1287/ijoc.2020.1035`.
- Cheng, K.-W., Bian, Y., Shi, Y., & Chen, Y. (2022). *Carbon-Aware EV Charging*. DOI: `10.1109/SMARTGRIDCOMM52983.2022.9960988`; arXiv: `2209.12373`.
- Liang, Y., Dabia, S., & Luo, Z. (2021). *The Electric Vehicle Routing Problem with Nonlinear Charging Functions*. DOI: `10.48550/arXiv.2108.01273`.
- Soriano, A., Gansterer, M., & Hartl, R. F. (2023). *The Multi-depot Vehicle Routing Problem with Profit Fairness*. DOI: `10.1016/j.ijpe.2022.108669`.
- Pillac, V., Gendreau, M., Guéret, C., & Medaglia, A. L. (2012). *An Event-driven Optimization Framework for Dynamic Vehicle Routing*. DOI: `10.1016/j.dss.2012.06.007`.
- Vallée, S., Oulamara, A., & Ramdane Cherif-Khettaf, W. (2020). *New Online Reinsertion Approaches for a Dynamic Dial-a-Ride Problem*. DOI: `10.1016/j.jocs.2020.101199`.
- Wang, S., Sun, W., & Huang, M. (2024). *An Adaptive Large Neighborhood Search for the Multi-depot Dynamic Vehicle Routing Problem with Time Windows*. DOI: `10.1016/j.cie.2024.110122`.

## 当前结论

来源链已经足够支撑“为什么按机制做专用动作”，但来源不能替代效果。官方 HGS 的直接插入和路线育种都没有证明内部贡献，已止损；官方 HGS 只保留为外部强对照。统一开发门中，机制驱动 ALNS 在静态九项上同时严格胜官方 HGS、原装 ALNS 和当前项目 ALNS 9/9，旧20客户共同值也被不改路线与电量的精确碳择时严格突破。车型—补能、碳择时、多车场责任、公平缺口和动态新增订单均有各自的绑定现场、删减或无动作对照、预算分账和独立复算，机器判定=`PASS_STAGE1_ALGORITHM_INFRASTRUCTURE_DEVELOPMENT_CLOSEOUT`。

该PASS只说明阶段一算法基础设施已经形成一套值得进入下一轮审批的候选，不是论文性能证明。多车场只有4个绑定项且3个强对照属于事后确认；公平只有1个绑定项；动态只有1个真实事件；非线性充电和分时电价尚未接入。正式 E2、公开benchmark、China81、E2--E7重跑、正式solver合入和阶段二仍为`false`，必须另批后在冻结样本和统计合同下检验。
