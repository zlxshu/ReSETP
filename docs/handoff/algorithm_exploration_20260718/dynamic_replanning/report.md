# E7动态滚动重规划算法探索报告

## 执行结论

本轮只形成候选池，不形成方法采纳。机器判决固定为 `EXPLORATION_ONLY_AWAITING_USER_APPROVAL`，`formal_search_allowed=false`。研究没有读取正在运行的E7中间结果，没有访问其方向性统计，没有修改E7保护文件、`winner.py`、正式求解器、事件流、预算或实验合同。所有关于性能的表述均是由论文、公开代码能力和静态接口核验支持的候选假设，不是ReSETP上的实测胜负。

研究支持五个外部候选方向和一个精细自研候选。当前最值得进入下一阶段隔离原型的组合不是整体替换ALNS，而是把“当前车辆状态重编码为伪车场或固定起点”“硬冻结已执行前缀”“时间窗兼容的快速插入”“有界regret/ejection修复”“路线稳定性目标”“责任重分配修复”和“固定路线碳调度”拆开验证。其中文献匹配度最高的是Wang等（2024）的多车场动态ALNS、Pillac等（2012）的路线稳定双目标ALNS，以及Vallée等（2020）的在线弹射重插入。源码复用价值最高的是OR-Tools的部分路线锁定、dvrpsim的事件状态接口、PyVRP的warm start和RoutingBlocks的EVRPTW站点邻域；但这些开源项目没有任何一个可以直接、完整地替代当前E7求解器。

## 研究边界与两轮方法

Cycle 1围绕dynamic/online VRP、rolling horizon、route freezing、regret/ejection insertion、stability objective和dynamic ALNS进行广泛检索。初始检索暴露出一个必须澄清的概念冲突：控制论文献中的“稳定性”常指随机到达队列是否有界，而E7需要的运营稳定性是新事件到来后少改司机已知路线、保持已执行动作和在途承诺不变。因此，队列稳定性论文只作为背景，不进入候选算法核心。Cycle 1进一步确认，经典ALNS提供多算子自适应选择和regret修复的通用基础，但动态重规划需要额外的状态继承、冻结边界和响应时间治理，不能把静态ALNS按事件重复调用就称作动态创新（Ropke & Pisinger, 2006; Pillac et al., 2013）。

Cycle 2回到原论文、官方代码、许可证和具体API。研究核验了六个公开仓库的许可证元数据或仓库文件，并固定了所审查提交。dvrpsim、PyVRP和N-Wouda/ALNS均为MIT；OR-Tools和Timefold Solver社区版为Apache-2.0。RoutingBlocks的各源文件带MIT文本，但仓库根目录没有独立LICENSE文件，故只能记为“源文件级MIT声明、仓库级许可证文件缺失”，在正式复用前还需用户批准并再次做许可证审查。代码核验表明，dvrpsim能在决策点导出时间、车辆状态、载货、当前位置和开放订单，并记录实际求解耗时；PyVRP的公开接口接受 `initial_solution`；OR-Tools源码明确说明可以锁住已经行驶的部分路线，并从既有assignment继续求解；RoutingBlocks公开了EVRPTW的站点邻域移除、相关移除和最佳插入算子。与此同时，PyVRP没有现成的硬冻结语义，dvrpsim不是求解算法，RoutingBlocks没有动态状态管理，OR-Tools也不原生表达本项目完整的责任、公平、非线性充电和碳调度。

## 与E7公开合同的适配边界

本轮只使用项目手册中已经公开冻结的E7语义：事件包含新增、取消和需求变化；重规划必须继承车辆当前位置、已执行或已开始动作、载货、剩余能力与电量；已发车承诺和锁定客户不得被重写；多车场合作允许在合法边界内重分配责任；充电调度需要保留因果信息边界。没有读取任何当前E7任务的阶段成本、可行率、方向、显著性或完成数量。

上述合同决定了候选算法必须采用“固定前缀加可变后缀”的表示。新事件到来时，已执行前缀不进入destroy集合；在途车辆当前位置或当前服务节点成为后缀子问题的车辆专属起点；已装载但未交付订单继续绑定原实体车；只有尚未承诺的客户允许责任重分配；充电动作需要区分已经开始、已经承诺和仍可移动三类。任何外部求解器如果不能直接表达这些语义，只能作为局部可行性或候选生成器，不能作为最终裁决器。

## 候选一：当前状态伪车场与时间窗兼容动态ALNS

Wang、Sun和Huang（2024）把多车场动态带时间窗问题重写为一系列静态、确定性的多车场混合车队子问题，并在重优化时把部分当前客户视为具有专属车辆和容量的伪车场。该方法与E7“当前位置成为车辆专属新起点”的状态语义高度匹配。论文还提出两个动态移除算子，并把Nagata式时间窗兼容更新扩展到插入可行性检查，宣称单个候选位置的时间窗检查可达到常数时间。这里必须严格限定：常数时间只适用于预处理后单个位置的时间窗可行性更新，枚举客户、车辆、路线和插入位置的总体重规划仍随问题规模增长（Wang et al., 2024）。

该候选建议只移植两部分：车辆专属当前状态起点的表示，以及时间窗前向/后向标签支持的快速插入筛选。它不应整体复制论文算法，因为论文没有找到可核验的公开代码，且其电动补能、成员公平和时变碳语义与ReSETP不同。对E7的可证伪假设是：在相同完整评价预算下，快速筛选能够提高每秒合法插入候选数并缩短阶段响应时间，同时不改变最终独立可行性检查结果。若筛选与完整检查不一致，或完整评价吞吐不升反降，该候选即失败。

## 候选二：路线稳定双目标pBiALNS

Pillac、Guéret和Medaglia（2012）直接研究动态VRPTW中的路线稳定性，把运营成本和重规划前后路线变化同时作为目标，并用路线序列的Levenshtein编辑距离度量插入、删除和替换。其pBiALNS维护非支配解集，并可并行执行若干ALNS轨迹。这个候选解决的是E7目前最容易被忽略的运营目标：成本更低的方案如果大幅改写司机后续路线，可能并不适合实时执行。该论文只有会议稿和算法描述，本轮没有核验到可复用的官方实现，因此只能逐式重实现，不能声称“已有开源代码”。

直接使用完整Levenshtein距离会带来两个问题。第一，车辆之间的路线对应关系会影响编辑距离；第二，经典动态规划的序列编辑距离对每对长路线需要二次时间。更适合E7的探索版本是同时记录“客户换车数”“未来相邻弧变化数”“承诺后缀位置变化”三个可线性复算的稳定性分量，并把论文Levenshtein距离作为审计指标而非每次完整评价的唯一代价。对E7的可证伪假设是：启用稳定性层后，路线变化指标应下降，而合法新增订单接纳率、最终可行性和系统成本的代价必须透明报告；如果稳定性不降，或者只是通过拒绝新增订单实现表面稳定，则该候选失败。

## 候选三：有界regret/ejection在线重插入

Ropke和Pisinger（2006）的regret-k修复优先处理“现在不插入、以后会失去好位置”的请求，是ALNS中最成熟的前瞻式插入思想之一。Vallée、Oulamara和Ramdane Cherif-Khettaf（2020）进一步为动态Dial-a-Ride提出HDR、GH和IGH三种在线重插入，其中GH/IGH使用ejection chain，把一个难插的新请求通过有限连锁移位接入现有路线。Gschwind和Drexl（2019）的常数时间可行性测试说明，若容量与时间标签设计得当，复杂约束下也能显著降低单位置检查成本。三者共同支持一个适合E7的候选：先做regret-2/3插入，失败后启动有界深度的弹射链，链上的每一步都必须保留实体车状态、冻结前缀和完整评价记账。

弹射链的风险是分支数随深度快速增长，因此候选不能做无界搜索。探索版应预先冻结最大链深、每层候选数和完整评价上限；链内快速标签只用于筛选，每个完整方案仍记一次正式完整评价。对E7的可证伪假设是：相对于单纯直接插入，有界弹射应提高新事件后的可行修复率或降低新增独立车次，同时阶段响应时间保持在同一预注册限额内。若可行率不提高、完整评价调用失控、或者弹射触及冻结客户，该候选失败。

## 候选四：OR-Tools冻结前缀可行修复器

OR-Tools的 `ApplyLocksToAllVehicles` 源码说明明确提到在线路由场景中锁定已经行驶的部分路线；`SolveFromAssignmentWithParameters` 和 `FastSolveFromAssignmentWithParameters` 可以从既有解继续改进，许可证为Apache-2.0。它适合做一个独立的“冻结前缀可行修复器”或对照方法：将已经执行的节点锁定，把剩余客户和新事件交给短时限局部搜索，再由ReSETP独立评价器复算。

该候选不适合直接成为正式主算法。OR-Tools通用RoutingModel并不原生覆盖当前模型的非线性充电曲线、共享充电资源、成员收益约束和时变碳调度；如果为这些机制大量重写维度和回调，移植成本可能超过收益。对E7的可证伪假设是：它应在严格短时限内更快地产生冻结一致的可行后缀，作为当前ALNS的紧急修复或外部对照；若独立评价器发现语义不一致，或接口转换时间抵消求解速度，它就不应进入正式机制门。

## 候选五：开源状态与算子供体组合

dvrpsim、PyVRP和RoutingBlocks适合拆开使用而不是合成一个新名字。dvrpsim提供事件驱动状态—决策接口和真实求解耗时记录，可用于校验E7的状态包是否完整；PyVRP提供显式warm start和高性能局部搜索，可作为不含完整能源/公平语义的强后缀重优化对照；RoutingBlocks提供EVRPTW的站点邻域移除、相关移除和最佳插入，可作为充电相关算子供体。N-Wouda/ALNS只提供通用算子选择、接受准则和停止准则，不构成动态创新。

这一组合的最大价值是给自研算子提供可核验的外部参照，而不是把不同代码库拼接进正式runner。RoutingBlocks的仓库级许可证缺口、PyVRP的冻结语义缺口、dvrpsim的求解器缺口都必须保留。按EA-001可在独立目录逐个原型化；合入正式runner、引入正式依赖或进入实验时，再按一个候选一个审批单推进。

## 自研候选：事件条件稳定—责任—碳联合ALNS

自研候选暂命名为“事件条件稳定—责任—碳联合ALNS”，只作为描述性工作名，不作为论文正式算法名。其核心不是增加一层调参器，而是把E7四类难点分别映射为可见的搜索动作。第一层是事件条件破坏：新增事件优先激活空间—时间邻近客户，取消事件释放其后继弧，需求变化事件优先检查同车容量/SOC风险，不允许随机破坏冻结前缀。第二层是稳定修复：使用regret插入与有界弹射链，在边际系统成本之外显式记录客户换车、未来弧变化和承诺后缀变化。第三层是责任修复：只有尚未承诺且多车场可行的客户进入跨场候选，边际值同时计算系统成本、成员收益余量和车场负荷。第四层是碳修复：路线后缀确定后，仅对仍可移动的充电动作调用固定路线充电重排，不允许借碳调度改变已冻结路线或已开始充电。

该候选与标准ALNS的实质差异在于事件类型决定邻域资格，冻结边界进入算子定义，责任和碳不是目标函数中的被动权重，而是各自具有可开关的专用修复层。复杂度由候选筛选、插入位置、弹射深度和充电时段数共同决定；因此必须通过候选列表、标签缓存和有界链限制响应时间。所有快速增量值只能用于候选排序，正式预算仍按完整候选方案评价记账。G0未闭合前只能做预算0/1/2/5的功能、活性和计数探针，不能比较性能胜负。

## 可证伪消融设计

正式消融必须在用户批准后才实施，当前冻结候选结构并允许独立微例功能探针。基础臂保留当前动态重规划语义，但不读取或利用本轮E7结果。稳定性消融只关闭稳定代价和稳定接受规则，其他算子不变；响应时间消融关闭时间窗标签缓存与候选剪枝，比较合法候选吞吐、完整评价次数和阶段墙钟；责任消融禁止尚未承诺客户跨场，比较动态订单的合法跨场吸收、系统成本和成员约束；碳消融保留完全相同的路线与责任修复，但把固定路线充电重排改为碳盲时序。完整臂同时启用四层。

每个消融都必须同时报告机制活性和结果。稳定层若没有实际拒绝或重排任何高扰动候选，即使最终路线变化较小也不能算贡献；快速层若只减少完整评价次数而没有提高单位时间合法候选数，不能算加速；责任层若没有任何多车场可行客户进入候选集，不能据成本差声称机制有效；碳层必须记录被移动的充电动作、电量、原时段和新时段，若没有动作移动就不能声称动态碳调度有效。显著性检验、主要统计单位和多重校正仍属于MC-002待批准事项，本包不替用户作决定。

## 推荐顺序与未决风险

按EA-001先做不碰正式solver的四个最小探针：当前状态伪车场的序列化与回读、OR-Tools冻结前缀一致性、regret/ejection在人工微例上的活性和预算计数、稳定性指标的独立复算。四项通过后，再把责任和碳修复接到一个隔离的最小后缀问题中。PyVRP和RoutingBlocks只作外部对照或算子阅读来源，不建议第一步就引入正式依赖。

当前最大不确定性有四个。Wang等（2024）和Vallée等（2020）未找到官方开源代码，需要逐式重实现；RoutingBlocks缺仓库级LICENSE文件；外部求解器的快速局部结果必须经ReSETP完整评价器复算；当前G0尚未闭合，所以任何“更快”都只能先指局部候选生成或墙钟，不得冒充统一完整评价预算下的算法优越性。这些风险没有被隐藏，且全部写入 `candidates.json` 和 `decision.json`。

## 参考文献

Chen, S., Chen, R., Wang, G.-G., Gao, J., & Sangaiah, A. K. (2018). An adaptive large neighborhood search heuristic for dynamic vehicle routing problems. *Computers & Electrical Engineering, 67*, 596–607. https://doi.org/10.1016/j.compeleceng.2018.02.049

Gschwind, T., & Drexl, M. (2019). Adaptive large neighborhood search with a constant-time feasibility test for the dial-a-ride problem. *Transportation Science, 53*(2), 480–491. https://doi.org/10.1287/trsc.2018.0837

Horváth, M., & Tamási, T. (2025). A general modeling and simulation framework for dynamic vehicle routing. *EURO Journal on Transportation and Logistics, 14*, 100159. https://doi.org/10.1016/j.ejtl.2025.100159

Pillac, V., Gendreau, M., Guéret, C., & Medaglia, A. L. (2012). An event-driven optimization framework for dynamic vehicle routing. *Decision Support Systems, 54*(1), 414–423. https://doi.org/10.1016/j.dss.2012.06.007

Pillac, V., Gendreau, M., Guéret, C., & Medaglia, A. L. (2013). A review of dynamic vehicle routing problems. *European Journal of Operational Research, 225*(1), 1–11. https://doi.org/10.1016/j.ejor.2012.08.015

Pillac, V., Guéret, C., & Medaglia, A. L. (2012). Route stability in dynamic vehicle routing: A bi-objective approach. *ROADEF 2012*. https://hal.science/hal-00674440

Ropke, S., & Pisinger, D. (2006). An adaptive large neighborhood search heuristic for the pickup and delivery problem with time windows. *Transportation Science, 40*(4), 455–472. https://doi.org/10.1287/trsc.1050.0135

Vallée, S., Oulamara, A., & Ramdane Cherif-Khettaf, W. (2020). New online reinsertion approaches for a dynamic Dial-a-Ride Problem. *Journal of Computational Science, 47*, 101199. https://doi.org/10.1016/j.jocs.2020.101199

Wang, S., Sun, W., & Huang, M. (2024). An adaptive large neighborhood search for the multi-depot dynamic vehicle routing problem with time windows. *Computers & Industrial Engineering, 191*, 110122. https://doi.org/10.1016/j.cie.2024.110122
