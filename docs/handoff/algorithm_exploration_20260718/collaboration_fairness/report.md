# 多车场合作责任重划与参与公平算法探索

本报告执行 EA-001 与用户指定的两轮 `academic-deep-research`。它建立候选、证据和可证伪的探针设计，不修改正式求解器、`winner.py`、E7 或正式实验合同。结论状态固定为 `EXPLORATION_ONLY_AWAITING_USER_APPROVAL`：EA-001已授权独立隔离原型和预算0/1/2/5功能探针，但没有任何候选因此获得正式合入、正式实验或论文主张授权。

## 执行结论

当前 ReSETP 并不是“公平只在结果出来后筛选”。E6 已把独立经营利润、参与阈值和客户原始归属传入统一搜索上下文；完整候选、局部搜索和修复后的方案都会经过参与约束检查。因此，公平已经进入搜索可行性判断。真正的弱点是搜索引导过粗：完整评价只按“有几个车场违反约束”各加一个 `BIG_M`，不区分利润差一元还是差很多；现有公平专用结构主要是双方各移除一个边界客户，再用普通跨场修复尝试回到可行域。这容易形成大片等罚值平台，也无法主动构造多步责任重划。

两轮研究表明，最稳妥的增强不是换一个花哨的元启发式名称，而是把三层机制接到同一条可审计链上。第一层采用 Soriano、Gansterer 与 Hartl（2023）已经验证的公平修正插入，使未达到利润下界的成员在重构阶段获得方向性帮助。第二层采用 PyVRP/Vidal 的真实 SWAP-star、尾段交换和连续片段交换结构，并结合跨车场动态半径或限深 ejection chain，增强责任边界重构。第三层在固定检查点把已验证路线放入带成员参与下界的受限集合划分主问题，重组不同迭代产生的互补路线。三层全部仍需用户逐项批准、G0 预算闭合和隔离消融；当前没有性能胜负结论。

## Cycle 1：候选地图与最初假设

第一轮广泛检索覆盖 MDVRP、协同 VRP、责任分配、cyclic transfer/ejection chain、路线池集合划分、利润公平与 epsilon-constraint。最初假设是“公平论文多半只做事后分账”，但原文证据推翻了这个过度概括。Soriano 等（2023）把最差成员相对独立经营的利润比作为公平目标，用约束 \(P_d \geq \hat P P_d^0\) 形成一组单目标问题；更关键的是，其重构算子用公平修正项改变客户插入车场的优先级，局部搜索也只接受满足公平约束的移动。这是与当前 E6 最直接的外部方法锚点。

责任重划方面，Thompson 与 Psaraftis（1993）的 cyclic transfer 同时处理客户分配与车内排序，说明多步链能越过单点 relocate 的局部障碍。Soto 等（2017）把 ejection chain 用于多车场开放式路径并给出统一邻域表达，进一步支持把跨场交换组织成连续链。然而开放式路径无需回场，且未找到作者开放代码，因此该方法只能作为重实现候选，不能直接移植其可行性或性能结论。

路线池方面，Balinski 与 Quandt（1964）奠定了配送路线集合划分表达；Contardo 与 Martinelli（2014）把集合划分用于 MDVRP 精确算法；Montoya 等（2016）展示了“先生成路线池、再用集合划分组装方案”的高性能启发式。三者共同支持一个适合 E6 的结构：路线列可携带所属车场、客户覆盖、车型、成本和成员利润贡献，使参与约束进入路线组合主问题。不过路线池缺少关键列时无法创造新路线，因此它必须与强跨场生成算子配套。

第一轮留下三个缺口：文献方法是否有可复用代码；许可证是否允许；这些方法能否覆盖 ReSETP 的异质车队、充电、多趟实体车和当前利润核算。Cycle 2 专门核验这些缺口。

## Cycle 2：原文、代码、许可证与适配核验

Soriano 等（2023）的本机 Zotero 全文已重新抽取核验，PDF SHA256 为 `07bf3ac92303eab0b7d9e713606334b1db262097692eeedce6942056392544e2`。全文确认其 Section 4.3 不只设置公平硬约束，还用 \(f_d\) 修正插入分数；Proximity removal 按客户到其他车场的最近距离排序；局部搜索包含 relocate、swap 和 2-opt-star，并要求所有移动满足公平约束。没有找到作者源代码，因此候选 CF-EXT-01 的性质是“逐式重实现”，不是“开源移植”。论文模型也比 ReSETP 简单，不能照抄参数或假定其运行速度。

Gauthier 与 Irnich 的机构全文以 CC BY 4.0 提供，本地 PDF SHA256 为 `30206febc6d919a957e23e038b209fbe0718d8d75d04b11d88c6d2de947868db`。该文严密区分多车场 2-opt 与 2-opt-star 的车场交换情形，并为动态半径剪枝加入修正项。它报告比字典序搜索高出百倍量级的某些邻域加速，但也明确承认：允许跨车场移动虽然平均得到更好的局部最优，最终 ILS 最好解却没有改善。这个反例使 CF-EXT-02 必须接受独立消融，不能预写成“必然提高性能”。

PyVRP 官方仓库和 v0.13.4 已克隆核验。该版本固定提交为 `18815548d04a90a0e5eea2a0bed53a81ea9d2d49`，MIT 许可证哈希为 `d9484b4905b1479240a99cdbe96b4f34d9a2c17347000d961819f8b177f3365b`。源码和测试确认存在 Exchange、SwapTails 和真实 SwapStar；真实 SWAP-star 允许交换客户后分别寻找自由重插位置，而仓库历史 `swapstar-lite` 只在原位置交换，二者不能混称。PyVRP 支持多车场，但不支持 ReSETP 的成员利润、碳配额分摊、充电时段容量和实体多趟连续性，所以只能借用算子结构和测试思想，所有落地候选仍必须经过项目统一评价器。

对当前代码的适配审计还发现一个路线池硬边界。当前 `profit.py` 的收入、固定费、里程、燃油、电费和跨场费通常可按路线归属车场累加；但当碳配额非零时，成员碳成本按总碳成本和成员排放占比分配，不再是简单路线可加项。因此 CF-EXT-04 不能在所有场景直接把每条路线的成员利润写成固定列系数。它只有在 E6 具体价格/配额口径证明可加时才能使用线性参与约束，否则必须增加统一评价器的完整复核和受控修复。这一限制会作为审批前置，不会用近似值悄悄绕过。

## 候选判断

CF-EXT-01 是最直接的短路径候选，因为它与现有 \(P_d \geq \theta P_d^0\) 语义同构，并明确让公平进入修复评分。它的风险是没有开源代码且论文物理约束较简单。按EA-001，第一项隔离原型只实现公平修正插入，与当前硬公平门、只加 Proximity removal、两者联合做四臂功能探针；在G0闭合和用户批准前不进入正式消融。

CF-EXT-03 是最可信的开源性能组件来源。MIT 许可证允许带署名适配，真实 SWAP-star、SwapTails 和 Exchange 都有源码和测试。它不能作为外部 solver 直接替换 ReSETP，也不能使用其内部迭代数冒充完整评价预算；合理做法是借用邻域定义，接入 ReSETP 的可行性和完整评价，并逐算子消融。

CF-EXT-04 的潜在上限最高，因为路线池可以组合不同迭代的互补优质路线，并把参与下界作为主问题约束。它也最容易出现隐藏语义错误：多趟实体车、共享充电桩和非可加碳分摊都可能跨路线耦合。批准原型前必须先完成“路线列可加性审计”，证明哪些资源可作为列属性，哪些必须由主问题外完整复核。

CF-EXT-02 与 CF-EXT-05 都适合扩大责任重划邻域，但实现风险高于前三项。动态半径有作者自己报告的最终最优无提升反例；ejection chain 则缺少开放代码且开放路径语义不适配回场闭环。二者应排在公平修正插入和真实 SWAP-star 之后，除非前两者的活性探针证明单步邻域仍无法跨越局部障碍。

CF-SELF-01 是精细自研候选“公平赤字导向的跨场链—路线池协同 ALNS”。它用归一化公平赤字而不是违规个数引导搜索；允许在单独档案中保存“物理完全可行但公平暂未闭合”的近可行解；用限深跨场链主动降低最大成员赤字；最后用带参与下界的路线池主问题闭合。该组合与任何单篇文献都不同，但目前只能称研究候选。是否允许近可行公平档案、如何处理非可加碳分摊、是否采用 MIT 代码适配，都属于新的方法决定，必须另经用户批准。

## 预算、消融与停止规则

G0 未闭合之前，任何候选只能做预算 0、1、2、5 的导入、活性、可行性、计数和速度探针，不能比较性能。G0 闭合且用户批准后，机制门必须使用共同起点、共同随机种子和相同完整评价预算。每个 ejection chain 落地解、路线池主问题输出解和外部算子应用后的完整解都必须消费一次完整评价；增量评分、剪枝次数、链展开数、路线池规模、MIP 节点与墙钟另列，不能当作免费工作。

未来建议的六臂消融是：当前 ALNS 加现有跨场算子和硬公平门；再单独加入公平修正插入；再加入真实 SWAP-star/SwapTails；在此基础上分别加入限深公平 ejection chain、带参与保障路线池主问题；最后测试完整组合。若出现未计数完整评分、路线池组合不能独立复算、公平可行率不升或系统成本明显恶化，候选立即停止升级。中国正式 81 实例和 Solomon 正式测试集不得用于调试或选择算子。

## 证据强度与剩余不确定性

“公平可以进入 ALNS 的修复和局部搜索”证据强度高，因为 Soriano 全文公式与当前代码都可直接核验。“PyVRP 邻域可作为高性能实现参考”证据强度高，因为论文、MIT 源码和测试相互闭合。“路线池 SP 能提升 ReSETP”目前只有中等证据，原因是路线池方法在其他 VRP 上有效，但 ReSETP 存在跨路线充电、多趟和利润分摊耦合。“公平赤字链—路线池组合具有论文级创新”目前只是可证伪假设，必须经过更广文献查重、隔离原型和消融后才能判断。

没有找到 Soriano MDVRP-PF、Gauthier–Irnich 动态半径或 Soto 等 MDOVRP ejection-chain 的作者开放实现。搜索缺失不能证明代码不存在，但在获得明确仓库前，许可证状态必须按“无可复用作者代码”处理。SSRN 直链曾返回 403，但本机 Zotero 全文消除了方法核验缺口；旧交接文档记录的文本抽取路径已经失效，这一漂移不影响 PDF 本体哈希。

## 推荐但未批准的下一步

EA-001下的最小风险探索顺序是先做 CF-EXT-01 公平修正插入隔离原型，再做 CF-EXT-03 真实 SWAP-star/SwapTails 适配，随后只做 CF-EXT-04 路线列可加性审计。三项都通过预算 0/1/2/5 后，再试 CF-SELF-01 的近可行档案、限深公平链和路线池主问题。任何候选要合入正式ALNS、进入E3/E6机制门或形成论文创新主张，仍须用户逐项批准。

## References

Balinski, M. L., & Quandt, R. E. (1964). On an integer program for a delivery problem. *Operations Research, 12*(2), 300–304. https://doi.org/10.1287/opre.12.2.300

Contardo, C., & Martinelli, R. (2014). A new exact algorithm for the multi-depot vehicle routing problem under capacity and route length constraints. *Discrete Optimization, 12*, 129–146. https://doi.org/10.1016/j.disopt.2014.03.001

Gauthier, J. B., & Irnich, S. (2022). *Inter-depot moves and dynamic-radius search for multi-depot vehicle routing problems* (Technical Report LM-2022-04). Johannes Gutenberg University Mainz. https://openscience.ub.uni-mainz.de/items/641f87af-aea7-4cf7-812a-bf4f26c24f0c

Montoya, A., Guéret, C., Mendoza, J. E., & Villegas, J. G. (2016). A multi-space sampling heuristic for the green vehicle routing problem. *Transportation Research Part C: Emerging Technologies, 70*, 113–128. https://doi.org/10.1016/j.trc.2015.09.009

Soriano, A., Gansterer, M., & Hartl, R. F. (2023). The multi-depot vehicle routing problem with profit fairness. *International Journal of Production Economics, 255*, 108669. https://doi.org/10.1016/j.ijpe.2022.108669

Soto, M., Sevaux, M., Rossi, A., & Reinholz, A. (2017). Multiple neighborhood search, tabu search and ejection chains for the multi-depot open vehicle routing problem. *Computers & Industrial Engineering, 107*, 211–222. https://doi.org/10.1016/j.cie.2017.03.022

Thompson, P. M., & Psaraftis, H. N. (1993). Cyclic transfer algorithm for multivehicle routing and scheduling problems. *Operations Research, 41*(5), 935–946. https://doi.org/10.1287/opre.41.5.935

Vidal, T. (2022). Hybrid genetic search for the CVRP: Open-source implementation and SWAP* neighborhood. *Computers & Operations Research, 140*, 105643. https://doi.org/10.1016/j.cor.2021.105643

Wouda, N. A., Lan, L., & Kool, W. (2024). PyVRP: A high-performance VRP solver package. *INFORMS Journal on Computing, 36*(4), 943–955. https://doi.org/10.1287/ijoc.2023.0055
