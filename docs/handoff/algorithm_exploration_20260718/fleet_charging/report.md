# 混合车队、车型选择、SOC 与非线性补能联合机制：两轮算法探索报告

状态：`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`

本报告执行探索授权 EA-001。研究只形成候选、许可证证据、隔离功能探针和预算设计，没有修改正式求解器、`winner.py`、E7、物理模型、单位合同或正式实验合同，也没有启动 ReSETP 搜索。所有候选在用户逐项批准前均不得接入正式 ALNS、进入 E1–E7 或写成论文创新结论。

## 结论

两轮研究没有找到一个可以直接复制进 ReSETP、同时成熟解决混合燃油—电动车队、车型选择、跨趟 SOC、时间窗和非线性部分补能的单一开源求解器。现有高质量来源呈互补关系。Hiermann 等（2016）的 `Resize`、`RelocateAndResize` 和车型感知插入最直接地把客户路线变化与车型选择联动起来，但其充电假设是线性且到站充满；Froger 等（2019）及其开源实现 `frvcpy` 能对固定客户序列精确求解分段线性非线性充电计划，但不负责客户路径和车型选择；PyVRP 提供成熟的异构车队数据结构、颗粒化邻域和高性能增量评价，但不原生处理 SOC；Wang 等（2025）的 HEVRP-NL 方法在概念上最完整，却没有检索到官方代码，必须从论文独立重实现并重新验证。

因此，本轮推荐的不是把某一个库整体塞进现有内核，而是一个待审批的分层路线。第一层把 `frvcpy/Froger` 作为受影响路线的精确非线性充电预言机；第二层重实现 Hiermann 的车型—路线联合邻域；第三层再检验 Wang 的逐车型路线评价、`ReplacePath` 和有界路线池是否带来额外收益。自研候选 VMR-NL 把这些机制收敛为“车辆模式后悔值联合修复”：对每个未分配客户同时比较路线、位置、CV/EV 模式和充电路径，先用资源包络筛选，再对预注册的少量候选调用精确非线性预言机。这只是具有可证伪定义的候选，不是已证明的新算法。

## Cycle 1：广泛检索形成的候选地图

第一轮围绕 EVRPTW、heterogeneous fleet、electric fleet size and mix、charging insertion、joint route-vehicle repair、partial recharge、nonlinear charging 和 fixed-route charging 进行广泛检索，并优先保留原始论文、作者工作论文、期刊复现仓库和官方 GitHub。检索最先识别出 Hiermann 等（2016）的 E-FSMFTW：该问题同时决定车队构成、客户路线以及充电时间和位置，算法将 ALNS、嵌入式局部搜索和标签过程组合起来。论文中的关键不是一般随机移除或 regret 插入，而是把车辆类型作为分配属性，允许在路线不变时换车型，并允许在客户跨路线搬移时同步重选两条路线的车型（Hiermann et al., 2016）。

第一轮同时识别出固定路线车辆充电问题 FRVCP。Froger 等（2019）表明，给定客户顺序后，充电站、充电次数和充电量仍构成重要的非线性资源决策；其精确标签算法允许在两个非充电节点之间访问多个充电站，并通过 SOC 函数、预处理界和支配规则减少标签。作者报告，仅重新优化既有解的充电计划，就改善了 120 个 E-VRP-NL 最好已知解中的 23 个，这说明“路线不变时充电仍有独立价值”，也说明现有 ReSETP 若只做简单充电插入，可能系统性漏掉好解（Froger et al., 2019）。

第一轮还找到该标签算法的公开实现 `frvcpy`。软件论文和 INFORMS 复现仓库都明确说明，它支持非线性分段线性充电函数、不同充电技术和多次充电站访问，并可作为更大 EVRP 方法的嵌入子问题（Kullman et al., 2021）。这改变了初始判断：`frvcpy` 不是简单的恒功率充电修复器，而是当前候选中证据最完整的非线性固定路线精确组件。

在异构车队工程实现方面，第一轮保留 PyVRP。其官方仓库明确支持不同容量、固定与变动成本、班次、最大距离、路网剖面和车场的车辆类型，并提供交换、搬移、尾交换、颗粒化邻域和缓存路线段评价。它不能直接解决 SOC，但可作为车型感知局部搜索的数据结构和增量评价参照，也可作为未来外部强基线，避免把本项目自己的算法只和弱手写方法比较（Wouda et al., 2024）。

Cycle 1 的主要缺口有三个。其一，Hiermann 方法的充电物理口径落后于本项目要求；其二，`frvcpy` 不决定车型和客户路径；其三，PyVRP 不建模 SOC。搜索还发现 Wang 等（2025）的 HEVRP-NL 恰好联合异构车队和非线性充电，因此第二轮将其作为完整架构候选重点核验。

## Cycle 2：原论文、官方仓库、许可证与可移植性核验

第二轮直接克隆官方仓库并固定提交。`e-VRO/frvcpy` 固定在提交 `508333090a29b98125824c7f2fb914d14f2a20ec`，许可证为 Apache-2.0；INFORMS Journal on Computing 复现快照固定在 `d50ad0dfedce3e8b8d5f741be6473a27012ece02`，许可证同为 Apache-2.0。PyVRP 固定在提交 `58592ec7ea822e8678e9e978fc522a5855547c7a`，许可证为 MIT。两种许可证都允许研究修改和再分发，但未来若复用源码，必须保留相应版权、许可证和修改说明。Hiermann 和 Wang 候选没有找到官方代码，因此只能依据论文做 clean-room 独立重实现，不能写成“移植作者开源算法”。

对 Hiermann 原文的第二轮复核确认，同车型的有限边交换和节点搬移可利用预处理序列做常数时间增量评价；当车型改变时，需要按新车型对受影响序列做线性重算。`Resize` 只改车型，`RelocateAndResize` 同时移动客户并尝试改变两条路线的车型；顺序插入和并行 regret 插入也会在载重或能量约束需要时改变车型。其固定路线标签过程会重新放置充电站，但假定相邻非充电节点之间至多一个充电站且到站充满。这个限制说明它适合提供“车型—路线联动”部分，不适合单独承担 ReSETP 的 NL→NL 核心（Hiermann et al., 2016）。

对 Froger 原文和 `frvcpy` 源码的复核确认，标签由分段线性的 SOC 函数表示，在充电站按曲线断点扩展，并结合能量和时间预处理界及标签支配。FRVCP 是 NP-hard，最坏标签数量指数增长；论文中 29,443 条路线的平均精确求解约为 1 毫秒，软件论文的独立软件测试平均约 5.6 毫秒。两组数字来自不同测试和硬件，不能直接当作 ReSETP 速度承诺，但足以支持先做隔离原型。ReSETP 的人民币成本、时变电价、碳价、实体车跨趟 SOC 和充电枪容量并不在原包默认目标中，任何适配公式都属于建模变化，必须另行提交审批，不能在算法探索中暗改（Froger et al., 2019; Kullman et al., 2021）。

对 PyVRP 源码的复核确认，其局部搜索会在颗粒化客户邻域中应用 `Exchange`、`SwapTails` 等算子，维护“可能有改善”的客户集合，并在空路线搜索中遍历车辆类型。它的车辆类型对象含容量、固定成本、单位距离成本、时间范围、班次、最大距离、路网剖面和车场。它的优势是工程成熟和增量评价可靠，弱点是现有约束缓存中没有非线性 SOC 函数。若直接改 C++ 核心，集成面很大；更稳妥的用途是借鉴数据结构、设计独立外部基线，或仅重实现与本模型匹配的局部邻域，而不是先把整个库嵌入正式内核（Wouda et al., 2024）。

Wang 等（2025）的期刊论文和公开 GERAD 工作论文显示，HEVRP-NL 对每条客户路线遍历全部车辆类型并选择最低广义成本，采用非线性路线评价、六类 VND 邻域和专用 `ReplacePath` 算子。`ReplacePath` 在两个非充电端点不变时更换中间充电路径；可行路线进入有界池，路线池满后按重复客户集合、支配关系和约化成本过滤，再用集合划分重组完整解。论文明确指出精确 FRVCP 最坏呈指数增长，因此在局部搜索中使用快速启发式路线评价；集合划分同样会随路线池扩大而变贵。该方法在文献基准上报告了 32 个 E-VRP-NL 和 33 个 E-FSMFTW-PR 新最好解，但没有官方代码，且其快评不是精确 NL→NL 预言机。因此它是最贴题的架构蓝本，而不是可以不验证就采用的现成实现（Wang et al., 2025）。

## 隔离功能探针

本轮在 `/private/tmp` 的独立虚拟环境中安装了 `frvcpy 0.1.1` 和 `PyVRP 0.13.4`，没有导入 ReSETP 正式求解器。`frvcpy` 的出版示例在 Python 3.13.9 上返回时长 `7.338904`，并在固定客户序列 `0-40-12-33-38-16-0` 中插入充电站 48，与示例预期一致。这个结果只证明软件接口和标签机制在当前环境可运行。

PyVRP 探针使用两个客户和两种车辆类型：两台载重 5 的小车与一台载重 10 的大车。求解器返回一条由车辆类型索引 1 承担两个客户的可行路线，成本为 50。这个结果只证明异构车型和固定成本机制活跃。由于探针没有 SOC，它不能证明该解在 ReSETP 中电量可行，也不能作为算法性能比较。

Hiermann、Wang 和 VMR-NL 候选目前只完成了可执行探针合同，没有写原型代码。原因不是禁止探索，而是它们一旦涉及 ReSETP 成本、SOC、单位、曲线或跨趟实体车语义，就会跨过模型变更边界。EA-001允许下一步先在独立目录中使用完全合成的小例实现预算 0/1/2/5、活性、可行性和速度门；凡需改变正式成本、SOC、单位、曲线或跨趟语义的部分必须停在接口桩，等待用户批准。E7结束和 G0闭合前仍不能宣称性能胜负。

## 自研候选 VMR-NL

VMR-NL 的全称是 Vehicle-Mode Regret Repair with Tiered Nonlinear Charging Oracle。它把标准 regret-k 的选择空间从“路线和插入位置”扩展为“路线、插入位置、车辆模式和充电路径”。车辆模式至少区分 CV、无需途中充电的 EV、需要场内或公共补能的 EV；每个模式必须读取同一份已批准物理合同。对每个未分配客户，算法先用载重、时间窗和 SOC 前后缀包络排除明显不可行模式，再只对结果盲固定的 top-B 候选调用精确非线性预言机。后悔值取最佳模式与次佳独立模式的完整成本差，使“这个客户如果现在不分配给唯一适合的 EV 或 CV 模式，未来会损失多少”成为修复优先级。

这个候选与当前 `vehicle_type_swap` 的区别是，车型不是在完整路线形成后再翻转，而是在客户插入决策中与 SOC 和补能计划一起比较；与 Wang 的逐车型路线评价相比，它把模式差异直接用于 regret 优先级，并允许精确预言机只作用于筛选后的候选；与 Hiermann 的 `RelocateAndResize` 相比，它允许部分非线性充电并显式区分 CV/EV 补能模式。它仍可能与既有 vehicle-aware insertion 或 mode-aware regret 文献重叠，因此必须在原型后再做一次专门新颖性检索，当前不得称为原创算法。

VMR-NL 的朴素复杂度为 `O(uRPK·L)`，其中 `u` 是未分配客户数，`R` 是路线数，`P` 是平均插入位置数，`K` 是车型数，`L` 是非线性路线预言机代价。由于精确 `L` 最坏指数增长，分层筛选是必要条件而不是调参装饰。top-B 必须在开发阶段预注册，并通过小例穷举证明不会在合同覆盖范围内删掉最佳模式；不能看到正式结果后扩大或缩小 B。

## 预算记账与科学边界

所有候选必须区分包络筛选、路线预言机、修复增量、完整候选和独立复算。包络与下界只记 `screen_evaluations`；每次非线性充电子问题记 `route_oracle_calls`、标签扩展数、支配删除数和缓存命中；任何被用于排序、接受或更新最好解的完整解，必须在评分前预留并记一次 `complete_candidate_evaluations`；终局独立复算记 `reference_evaluations`。局部路线调用再多也不能掩盖完整解评分，完整解评分也不能因缓存而漏记。预算为 0 时不得生成或评分候选；预算为 1、2、5 时都必须在超限前停止。

在 G0 尚未闭合时，本轮只允许功能、活性和接口探针。任何候选未来若获批准进入机制门，必须先比较标准 ALNS、单一车型—路线联合邻域、单一非线性预言机和二者组合，保持同一起点、同一完整评价预算、同一墙钟报告和独立可行性复算。中国正式 81 实例和 Solomon 最终测试集都不能用于调候选；开发只能使用另行冻结的开发集。若车辆参数本身使全 EV 或全 CV 支配，算法不得通过惩罚、删结果或人为车队比例制造混合车队。

## 风险与待批准事项

目前最重要的技术风险是目标适配。`frvcpy` 主要最小化路线完成时间，而 ReSETP 还包含人民币车辆固定成本、电价、碳价和可能的充电占用成本。把这些量塞入标签不是纯代码适配，而是目标和单位口径变化，必须先提交公式、单位检查、来源和影响分析。第二个风险是跨趟 SOC：固定路线预言机通常从给定初始 SOC 出发，而 ReSETP 的实体车可能连续执行多趟；缓存键和可行性检查必须包含实体车、出发时刻和初始 SOC。第三个风险是充电站容量和排队；本轮来源大多假定无限服务或外生等待，不能自动等价于中国车场枪数合同。

EA-001下先探索 FC-C02 的独立适配原型，再探索 FC-C05 和 FC-C01 的小例原型。FC-C04 的路线池与集合划分放在后面，因为它既无源码又引入 MILP 调用；FC-C03 保留为工程参照和外部基线。任何候选要接入正式ALNS、改变正式模型语义、进入机制门或形成论文主张，必须获得用户逐项批准并写入审批登记。

## 参考文献

Froger, A., Mendoza, J. E., Jabali, O., & Laporte, G. (2019). Improved formulations and algorithmic components for the electric vehicle routing problem with nonlinear charging functions. *Computers & Operations Research, 104*, 256–294. https://doi.org/10.1016/j.cor.2018.12.013

Hiermann, G., Puchinger, J., Ropke, S., & Hartl, R. F. (2016). The electric fleet size and mix vehicle routing problem with time windows and recharging stations. *European Journal of Operational Research, 252*(3), 995–1018. https://doi.org/10.1016/j.ejor.2016.01.038

Kullman, N. D., Froger, A., Mendoza, J. E., & Goodson, J. C. (2021). frvcpy: An open-source solver for the fixed route vehicle charging problem. *INFORMS Journal on Computing, 33*(4), 1277–1283. https://doi.org/10.1287/ijoc.2020.1035

Liang, Y., Dabia, S., & Luo, Z. (2021). *The electric vehicle routing problem with nonlinear charging functions* [Preprint]. arXiv. https://arxiv.org/abs/2108.01273

Wang, W., Adulyasak, Y., Cordeau, J.-F., & He, G. (2025). The heterogeneous-fleet electric vehicle routing problem with nonlinear charging functions. *Transportation Research Part C: Emerging Technologies, 170*, 104932. https://doi.org/10.1016/j.trc.2024.104932

Wouda, N. A., Lan, L., & Kool, W. (2024). PyVRP: A high-performance VRP solver package. *INFORMS Journal on Computing, 36*(4), 943–955. https://doi.org/10.1287/ijoc.2023.0055

## 检索与复现说明

检索日期为 2026-07-18。Cycle 1 使用广义主题组合识别问题族、原始论文和公开实现；Cycle 2 逐一回到原论文、作者工作论文、官方 GitHub、许可证文件和源代码。检索没有发现 Hiermann 或 Wang 方法的官方代码仓库，这一“未发现”只表示本轮检索结果，不能证明代码绝对不存在。外部仓库只克隆到 `/private/tmp`，不属于正式项目源码；功能探针也只在临时虚拟环境运行。详细来源、提交、许可证、哈希、候选字段和失败风险分别见 `source_evidence.csv` 与 `candidates.json`。
