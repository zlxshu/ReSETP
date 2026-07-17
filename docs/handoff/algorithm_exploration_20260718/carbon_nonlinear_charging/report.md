# 算法探索主题3：时变碳、分时电价、充电调度与非线性充电

状态：`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`

研究日期：2026-07-18

## 研究问题与边界

本轮只回答一个问题：哪些已经发表或开源的方法，能够针对 ReSETP 的时变碳、分时电价、固定路线充电重排、共享充电容量和非线性充电难点，形成可单独消融的 ALNS 增强候选。EA-001 允许检索、许可证核验、隔离原型和非正式功能探针，但不允许候选自动进入正式 ALNS、E4、E5、E7 或论文创新结论。本轮没有修改 `winner.py`、正式 solver、E7 运行目录、目标函数、充电曲线、单位或默认参数，也没有运行正式搜索。

用户已经批准探索本身，包括独立目录中的原型和非正式功能探针，但没有批准任何候选进入正式算法或实验。报告中出现的状态变量、目标分解、时间离散、SOC 离散、标签支配、碳价权重、充电曲线映射和对照臂都只是备选设计；原型只能使用人工微例或接口桩。它们如需进入正式代码、模型或实验，仍须按照 EA-001 和建模审批登记完成单项批准。

## 两轮研究过程

Cycle 1 对 time-dependent EVRP、carbon-aware charging、resource-constrained shortest path、charging scheduling、partial nonlinear charging 五组关键词进行广泛检索。首轮确认了四个相互区别的问题层：路线与发车时刻的时间依赖优化；固定路线上的充电站、时刻和电量联合优化；车场多车共享桩或变压器容量下的充电排程；非线性充电曲线下的 SOC 可行性和最优充电量。首轮也发现，很多“碳感知”开源项目只是碳数据接口，很多 EVRP 论文只有公式而没有许可证明确的代码，不能把两者混称为可移植算法。

Cycle 2 逐项回到原论文、作者仓库、机构页面和许可证正文。Montoya 等（2017）证明忽略非线性充电会造成不可行或过度保守的方案，并提出固定路线充电决策优化邻域。Froger 等（2019）进一步给出更强的弧/路径表示和标签算法。Liang、Dabia 与 Luo（2021）把非线性充电递归函数嵌入定价标签，并在启发式中周期性地对固定客户序列求最优充电站、时刻和电量。这条方法链与当前 E5 的 `NL→NL` 缺口高度一致，但没有找到带可复用许可证的作者实现，因此只能列为“根据论文独立重实现”的候选，不能复制未知来源代码。

Lin、Ghaddar 与 Nathwani（2021）联合优化时变电价下的路线与充放电，采用循环交换的 VNS、2-opt*、exchange、relocate、充电站插删和 Tabu Search。其“路线改变后重新优化充电时段”的结构可以借鉴，但论文允许 V2G 放电，而当前 ReSETP 是配送车辆充电模型。未经模型审批，不得把放电收益、离散充放电约束或加拿大电价参数移入中国场景。Lu 等（2020）的 TDEVRP 使用 O(1) 拼接评价、VND 与发车时间/速度优化，适合未来有分时拥堵道路矩阵时研究；它不是当前碳择时的直接替代，也没有找到官方开源实现。

碳感知调度方面，Cheng 等（2022）建立了带车辆到离场、SOC、单车功率和站级变压器功率限制的滚动时域充电优化，并公开比较碳感知、分时电价、最早期限优先和等分功率方案。GitHub 仓库 `kaicheng0824/carbon_aware_ev_charging` 的提交者姓名为第一作者 Kai-Wen Cheng，README 与论文数据和四个对照脚本一致，因而可视为作者实现。但是仓库没有 LICENSE；它可以作为公式和结果的复现线索，不能复制进入 ReSETP。该论文采用线性 SOC 动力学和五分钟槽，也不能直接证明适合本项目的非线性充电。

RCSP 工程链中，`cspy` 有 JOSS 软件论文、MIT 许可证、Python/C++ 接口和自定义资源扩展函数，法律和集成摩擦最低，但主分支最后一次代码推送为 2024-06-10。PathWyse 有 2024 年期刊论文，仓库在 2026-07 仍更新，支持双向动态规划、DSSR、NG-path、自定义非线性资源、标签支配和 join，技术适配度更高；其许可证是 GPLv3，若链接、修改或分发可能给当前仓库带来许可证义务，必须在实施前单独批准。两者都只是通用 RCSP 引擎；SOC 状态、非线性扩展、价格/碳弧成本和支配规则仍需 ReSETP 自己定义，不能把调用库包装成论文算法创新。

车场共享容量方面，SAP 的 `emobility-smart-charging` 依据 Frendo、Gaertner 与 Stuckenschmidt（2019），提供按 15 分钟槽生成多车充电计划、分时价格目标和层级熔断/供电容量约束，采用 Apache-2.0。仓库在 2026-07-16被归档，适合做参考实现或隔离对照，不适合作为无人维护的长期核心依赖。它不处理车辆路径、非线性充电和碳目标，所以只能补 E5 的车场并发排程部分。

## 候选判断

第一优先候选是“固定客户序列的非线性充电标签优化器”。它沿用 Montoya—Froger—Liang 的方法链：对一条路线允许跳过充电站或在相邻客户间插入候选充电站，用前向/后向的时间—SOC 函数和支配规则决定何时、何地、充多少。它直接解决当前线性重放中出现的趟间不可行和方向反转，也能在 ALNS 路线改变后重建 SOC 账本。其证据强、问题匹配高，但需要 clean-room 重实现，且正式接入必须等 E7 结束、G0 闭合和非线性物理语义获批。

第二优先候选是“RCSP 充电调度 oracle”。短期隔离原型优先评估 MIT 的 `cspy`，因为可直接在 Python 中定义时间、SOC 和充电可用性资源；若速度不足，再在单独进程中评估 GPLv3 的 PathWyse，且不把它合入正式仓库。这个候选的作用是给固定路线充电重排提供可重复的精确或有界子问题，不替代 ALNS 的路线搜索。任何性能比较必须把 oracle 内部计算计入 wall time，并按照 G0 区分完整方案评价与子问题调用次数。

第三优先候选是“碳感知滚动充电排程”。根据 Cheng 等（2022）独立实现同一模型家族，可同时生成碳感知、分时电价、最早期限优先和均分功率四个调度器。它特别适合 E4 的固定路线机制验证和 E7 的动态到达场景，但论文原代码无许可证，只能看公式后自行实现。当前中国 30 分钟碳/价槽与论文五分钟槽不同，是否采用 30 分钟、细分为更小槽或连续时间候选必须另行审批，不能在探索包中替用户决定。

第四候选是“时变价 VNS/TS 联合邻域”。可借鉴 Lin 等（2021）的循环交换、2-opt*、exchange、relocate 与站点插删，并在每个路线变化后调用固定路线充电 oracle。V2G 放电、加拿大电价和其特定离散约束全部排除。该候选与标准 ALNS 的区别必须体现在“路线邻域与充电子问题的联合接受”，而不是只更换温度或算子权重。

第五候选是“车场共享容量排程参考器”。SAP 代码可用于验证多车共享桩/供电容量的输入输出和对照，但由于仓库已归档且是 Java 服务，不建议直接成为 ReSETP 的运行时依赖。更稳妥的用途是从论文独立实现一个小型线性/整数排程 oracle，并用 SAP 的公开样例做非正式交叉检查。

## 自研候选：双 oracle 碳—价冲突充电邻域

自研候选暂名 `DUAL_ORACLE_CARBON_PRICE_CONFLICT_CHARGING`，简称 DO-CPC，但名称本身不构成创新主张。它先在完全相同的固定路线、车辆、候选充电站、到离场窗口、初始/终止 SOC、非线性曲线、桩容量和离散精度下求两个充电调度：价格 oracle 只读取分时电价，碳 oracle 只读取时变碳强度。两个 oracle 在每条路线和每次充电动作上的时段分歧形成“碳—价冲突分数”。ALNS 只对冲突高且仍有时间/SOC 松弛的路线启用专门破坏；修复时由联合 oracle 在正式目标函数下选择充电站、时刻和电量。

这个设计的可证伪点不是“是否总能降碳”，而是三个明确问题：冲突分数是否带来非零算子活性；在同样完整评价预算下是否优于没有冲突排序的随机充电重排；在相同路线和总电量下是否改善正式目标或碳排而不增加违规。若冲突分数与改进无关、只在单一日期有效、或计算成本吞掉路线搜索预算，候选应被否决。该方法还需要用户批准冲突分数定义、两个 oracle 的目标语义、联合 oracle 的多目标处理和任何 SOC/时间离散。

## 碳贡献的可识别对照

E4 的“碳机制贡献”和 ALNS 的“碳算子贡献”必须分开识别。机制层对照固定路线、客户、车辆、充电站候选、总充电量、非线性曲线、桩容量和调度算法，仅改变调度目标。`COST_ONLY_BLIND` 读取分时电价但将逐槽碳系数置零；`CARBON_ONLY` 读取碳强度但将逐槽电价系数置零；`JOINT_COST_CARBON` 同时读取二者。三臂必须使用同一个 oracle、候选集合、可行性检查和停止条件。`JOINT_COST_CARBON - COST_ONLY_BLIND` 的成对差才是碳信号在调度机制中的增量影响，不能把立即充电或不同算法当作唯一碳盲基线。

算法层对照保持正式成本—碳评价器完全相同，只开关碳引导算子。`ALNS_SAME_OBJECTIVE_CARBON_OPERATOR_OFF` 与 `ALNS_SAME_OBJECTIVE_CARBON_OPERATOR_ON` 使用相同起点、随机种子、候选完整评价预算、非碳算子、接受准则和最终独立复算；唯一差异是碳冲突破坏/修复是否进入算子池。这样得到的是算子对搜索性能的贡献，而不是目标函数变化。为了防止“开算子同时多做计算”，报告还必须记录算子调用数、产生候选数、完整方案评价数、子问题调用数和 wall time。

E7 的碳盲臂应采用同样原则：完整滚动机制、事件流、冻结状态、非线性物理、价格目标、公平和合作均保持不变，仅让充电调度和算子看不到未来碳强度；最终评价仍用同一真实碳曲线结算。若碳盲臂改用简单插入而碳知臂使用精确 oracle，差异会同时包含算法强弱，不能识别碳机制。

## 与当前 E4/E5 的关系

当前 E4 的优点是已经固定路线、服务关系、车辆和总充电量，能够隔离充电时机；缺点是证据基于线性充电口径，且历史总运营排放改善较小。新候选不能通过挑日期或删不利日来制造显著性。正式方法若获批，应保留完整 28 日，以结果盲的可移动充电暴露门保证机制确实有发挥空间，并把默认日期只用于展示。

当前 E5 没有正式 `NL→NL`，固定方案复算已发现非线性不可行和方向反转。主题3最有价值的算法升级因此不是增加更多碳权重，而是让路线搜索、SOC 可行性、充电动作持续时间、分时电量积分和固定路线重排调用同一非线性内核。Montoya—Froger—Liang 标签链提供了最直接的算法依据；RCSP 开源库提供工程候选；Cheng 与 SAP 提供碳/价和共享容量对照。它们可以组成一条科学链，但尚未获批组成正式算法。

## 推荐给用户的后续裁决

最小风险探索路径是先做一个完全隔离的 `cspy` 功能原型，用人工构造的微型路线验证时间、SOC、非线性充电和价格/碳目标是否能正确扩展，并与穷举结果逐位一致。第二步再做 Montoya—Froger—Liang 固定路线标签法的 clean-room 原型。只有这两个原型在预算 0/1/2/5、可行性、活性和速度门通过，且 E7 已结束、G0 已闭合，才向用户申请进入正式机制门。

PathWyse 只作为隔离性能备选；测试可按EA-001进行，但任何链接、修改、分发或正式依赖必须先批准GPLv3使用边界。Cheng 作者代码只作阅读证据，不复制。SAP只作归档参考和交叉检查，不作为核心依赖。Lu的时间依赖IVNS暂不实施，等待中国正式有向道路矩阵是否包含分时交通后再判断。

## 局限

本轮没有找到 Montoya、Froger、Liang、Lin 或 Lu 方法的许可证明确作者代码。作者代码不存在或检索不到不等于论文不可复现，但会增加重实现偏差和验证成本。PathWyse 的高性能结论来自通用 RCSP 基准，不直接证明它在 ReSETP 非线性充电标签上更快。Cheng 的作者实现没有许可证，且使用美国五分钟数据和线性 SOC；SAP 代码已归档；这些边界均已写入机器候选表。

本轮没有改变任何单位，也没有决定时间槽、SOC 断点、碳价权重、曲线拟合或桩容量。这些决定会直接改变模型含义，必须在独立审批单中溯源、核验和由用户拍板。

## 参考文献

Basso, S., Giuffrida, V., & Salani, M. (2024). PathWyse: A flexible, open-source library for the resource constrained shortest path problem. *Optimization Methods and Software, 39*(2). https://doi.org/10.1080/10556788.2023.2296978

Cheng, K.-W., Bian, Y., Shi, Y., & Chen, Y. (2022). Carbon-aware EV charging. In *2022 IEEE International Conference on Communications, Control, and Computing Technologies for Smart Grids*. https://doi.org/10.1109/SMARTGRIDCOMM52983.2022.9960988

Frendo, O., Gaertner, N., & Stuckenschmidt, H. (2019). Real-time smart charging based on precomputed schedules. *IEEE Transactions on Smart Grid, 10*(6), 6921–6932. https://doi.org/10.1109/TSG.2019.2914274

Froger, A., Mendoza, J. E., Jabali, O., & Laporte, G. (2019). Improved formulations and algorithmic components for the electric vehicle routing problem with nonlinear charging functions. *Computers & Operations Research, 104*, 256–294. https://doi.org/10.1016/j.cor.2018.12.013

Liang, Y., Dabia, S., & Luo, Z. (2021). The electric vehicle routing problem with nonlinear charging functions. arXiv. https://doi.org/10.48550/arXiv.2108.01273

Lin, B., Ghaddar, B., & Nathwani, J. (2021). Electric vehicle routing with charging/discharging under time-variant electricity prices. *Transportation Research Part C: Emerging Technologies, 130*, 103285. https://doi.org/10.1016/j.trc.2021.103285

Lu, J., Chen, Y., Hao, J.-K., & He, R. (2020). The time-dependent electric vehicle routing problem: Model and solution. *Expert Systems with Applications, 161*, 113593. https://doi.org/10.1016/j.eswa.2020.113593

Montoya, A., Guéret, C., Mendoza, J. E., & Villegas, J. G. (2017). The electric vehicle routing problem with nonlinear charging function. *Transportation Research Part B: Methodological, 103*, 87–110. https://doi.org/10.1016/j.trb.2017.02.004

Torres Sanchez, D. (2020). cspy: A Python package with a collection of algorithms for the (resource) constrained shortest path problem. *Journal of Open Source Software, 5*(49), 1655. https://doi.org/10.21105/joss.01655
