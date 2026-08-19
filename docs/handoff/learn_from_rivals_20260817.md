LEARN_RIVALS_DONE

# 师夷长技：公开强手源码与设计学习

## 0. 范围与先说结论

引用约定：下文 `PYVRP_ROOT` 指 `/opt/anaconda3/lib/python3.13/site-packages/pyvrp`；`OURS` 指 `solver/src/setp_solver/algorithms/problem_hgs`；`ETGA_PDF` 指 `baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/sources/papers/lei_hao_wu_mdfiha_2026_v1.pdf`；`VCGP_PDF` 指同目录下的 `vidal_hgsadc_2013.pdf`。论文页码按 PDF 页面上印出的页码引用。

- `FACT`：本项目复制内核来自 PyVRP `v0.12.2`、提交 `ea0c4211819edac6fd920413ad7508cc9ad56e0e`，改动边界是包名、导入、命名空间和构建路径的机械分离，算法行为在该边界保持不变；复制内核不作为本项目研究贡献。（`third_party/setp_hgs_kernel/README.md:3-25`）
- `FACT`：当前公开 28 题、同一 ×1000 口径、每题每臂 20 分钟、seed 11 下，我方对冻结 PyVRP 0.12.2 为 **13 胜 15 负**；我方平均偏差 1.016%，冻结 PyVRP 为 0.998%，双方结果都完成全部客户和需求并通过原始精度可行性复核。（`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1270-1274`）
- `INFERENCE`：PyVRP “又好又快”的核心不是单个算子，而是一条连续的减负链：**近邻裁剪 → 变化时间戳跳过旧组合 → 路线片段差量评价 → 非改善候选提前返回 → 只更新被接受的路线 → 原生紧凑数据复用**。搜索质量则由可行/不可行双池、自适应罚分、成本与多样性联合生存、修复、重启和跨路线重组共同维持。（`PYVRP_ROOT/search/neighbourhood.py:76-112`；`PYVRP_ROOT/cpp/search/LocalSearch.cpp:51-147`；`PYVRP_ROOT/cpp/CostEvaluator.h:269-317,328-413`；`PYVRP_ROOT/Population.py:35-151`；`PYVRP_ROOT/GeneticAlgorithm.py:171-237`）
- `FACT`：我方公开主路径已经复用原生局部搜索、原生罚分和原生种群；私有路线层也已把复制内核作为提案器，最终接受仍以完整 Duty 成本与可行性为准。（`OURS/public_search.py:15-34,328-364,471-512`；`OURS/kernel_proposals.py:45-177,397-456`；`OURS/integrated_private.py:1-7,1066-1122`）
- `INFERENCE`：当前最明确的公开侧拖累不是“缺 HGS 基础设施”，而是又在成熟 HGS 外面串接了自建的全局分配/旋转精修；两个留有分项账的实例中，它各占总墙钟约 **10.5%** 和 **10.7%**，并进行了 1945 万与 1.072 亿次旋转评价。（`OURS/public_search.py:97-186,366-469`；`solver/reports/public_v2_28_clean_ruler_20260810/PR11A_independent_seed11/decision.json:3-27`；`solver/reports/public_v2_28_clean_ruler_20260810/PR15B_independent_seed11_RERUN/decision.json:3-27`）
- `FACT`（更正已知起点）：`population.py` 确实自述独立重做 Vidal 式双池、罚分与多样性，但当前单目标私有主路径已经返回复制内核中的 `ExternalPopulation`；旧 `DutyPopulation` 只在未导出的退役 runner 中保留。因此它现在首先是重复维护与误导风险，不是当前主路径已经证实的运行热点。（`OURS/population.py:1-20,139-291`；`OURS/bi_objective_population.py:441-469`；`OURS/runner.py:303-327,551-567`；`OURS/__init__.py:36-45,49-84`）

本任务只读源码与论文；没有改源码、没有启动求解器、没有运行实验。

## 1. 第一层：优化思想与搜索设计

### 1.1 PyVRP 0.12.2 HGS 为什么快，也为什么不容易搜散

| 设计选择 | 源码事实 | 它解决的开销或搜索困难 |
|---|---|---|
| 先算一次 granular neighborhood，再把每个客户的候选邻居限制为前 40 个 | `FACT`：默认 40 邻居；相近度同时考虑异质车型中最便宜的边成本、等待和 time warp，并排除自身、车场及互斥组；`solve()` 只在创建局部搜索时计算一次。（`PYVRP_ROOT/search/neighbourhood.py:13-49,76-112,154-186`；`PYVRP_ROOT/solve.py:173-183`） | `INFERENCE`：把客户两两组合从近似全图压到固定宽度候选表，是最前端、收益最大的剪枝；同时不只按欧氏距离选邻居，减少“地理近但时间窗不相容”的无效尝试。（`PYVRP_ROOT/search/neighbourhood.py:76-112,154-186`） |
| 节点小邻域和路线级强化分层 | `FACT`：默认节点算子为 Exchange(1,0)/(2,0)/(1,1)/(2,1)/(2,2)、SwapTails、RelocateWithDepot；路线算子为 SwapRoutes、SwapStar。节点搜索后再做路线级 intensify，直到路线级也不再更新。（`PYVRP_ROOT/search/__init__.py:23-36`；`PYVRP_ROOT/cpp/search/LocalSearch.cpp:15-32`） | `INFERENCE`：高频、便宜的局部动作承担日常爬坡，较贵的整路线动作只作强化；既保留大结构变化，又不让每个候选都付整路线代价。（`PYVRP_ROOT/cpp/search/LocalSearch.cpp:15-32,51-147`） |
| 用 `lastTested` / `lastUpdated` 跳过没有新信息的组合 | `FACT`：客户和路线各有最后测试时间，路线有最后更新时间；只有 U 或 V 所在路线自上次测试后改变，才重新尝试该组合。（`PYVRP_ROOT/cpp/search/LocalSearch.h:48-73`；`PYVRP_ROOT/cpp/search/LocalSearch.cpp:61-107,122-145`） | `INFERENCE`：局部搜索达到局部最优的过程中，大量路线对没有变化；时间戳把“又测一遍同一个失败动作”直接消掉。（`PYVRP_ROOT/cpp/search/LocalSearch.cpp:61-107,122-145`） |
| 路线保存前缀/后缀片段统计，候选只拼片段 | `FACT`：`Route` 缓存累计距离、前后缀载荷、前后缀时间段、距离成本、超距和 time warp；`Route::Proposal` 用少量片段合成新路线的距离、时长和超载，而不先复制整条路线。（`PYVRP_ROOT/cpp/search/Route.h:301-332,701-734,776-825,1001-1177`） | `INFERENCE`：常见交换只改几个连接点，评价成本取决于被移动片段而不是整条路线长度；这正是 HGS 教育阶段可以高频调用邻域的基础。（`PYVRP_ROOT/cpp/search/Route.h:1001-1177`；`VCGP_PDF`, pp.11-13） |
| 差量评价允许“已不可能改善”时提前停 | `FACT`：`CostEvaluator::deltaCost()` 先减旧路线的缓存成本，再逐项加新提案；非 exact 模式下，只要部分累计差量已不小于 0，就在载荷维或时长维之前返回。（`PYVRP_ROOT/cpp/CostEvaluator.h:269-317,328-413`） | `INFERENCE`：坏候选通常不必算完所有容量维、时间窗和第二条路线；越早证明不改善，越少进入昂贵部分。（`PYVRP_ROOT/cpp/CostEvaluator.h:297-317,372-413`） |
| 先评价、后原地应用，只重建受影响路线 | `FACT`：算子仅在 `deltaCost < 0` 时 `apply()`，随后只对 U/V 两条路线调用 `update()`，并同步路线算子缓存；未接受候选不改解。（`PYVRP_ROOT/cpp/search/LocalSearch.cpp:160-224,371-390`） | `INFERENCE`：避免为每个失败候选复制或重算完整解，也把缓存失效范围锁在真正改变的路线。（`PYVRP_ROOT/cpp/search/LocalSearch.cpp:160-224,371-390`） |
| 可行/不可行解分池，自适应罚分，失败子代可修复 | `FACT`：种群按可行性分流；每个子代先教育、入池并登记可行性；不可行子代按概率用放大罚分再教育，修成可行后再次入池。罚分初值由实例平均边成本与平均载荷/距离/时长尺度计算，并按近期目标可行比例逐维增减。（`PYVRP_ROOT/Population.py:35-109`；`PYVRP_ROOT/GeneticAlgorithm.py:211-237`；`PYVRP_ROOT/PenaltyManager.py:176-232,234-300`） | `INFERENCE`：不可行解不被立即丢弃，搜索可穿过可行域边界；罚分又会根据实际可行率回调，避免长期全可行而保守、或长期不可行而回不来。（`PYVRP_ROOT/GeneticAlgorithm.py:211-237`；`PYVRP_ROOT/PenaltyManager.py:234-300`） |
| 成本与结构多样性共同决定生存和配对 | `FACT`：新解入池时只计算它与现有解的 broken-pairs 距离并插入双方有序近邻表；淘汰时先去重复，再按成本排名与最近邻多样性排名的联合 fitness 删除最差者；父代二元竞赛后还要求两者距离落在多样性区间内。（`PYVRP_ROOT/cpp/SubPopulation.cpp:48-70,98-177`；`PYVRP_ROOT/cpp/diversity/broken_pairs_distance.cpp:5-31`；`PYVRP_ROOT/Population.py:111-151`） | `INFERENCE`：不让一批几乎相同的便宜解挤满种群，也不把算力浪费在毫无质量的“纯新奇”解上。（`PYVRP_ROOT/cpp/SubPopulation.cpp:98-177`；`PYVRP_ROOT/Population.py:111-151`） |
| SREX 交换空间相邻的路线块，并选重规划量更小的组合 | `FACT`：SREX 按路线质心极角排序父代路线，用 bitset 维护路线块客户集合，滑动两边的路线块以减少需重规划客户，构造两个子代后取罚分成本更低者。（`PYVRP_ROOT/crossover/selective_route_exchange.py:13-25,64-78`；`PYVRP_ROOT/cpp/crossover/selective_route_exchange.cpp:74-176,178-230`） | `INFERENCE`：它做的是成块结构跳跃，但通过空间相邻与集合差控制破坏量；比随机拆很多路线更容易把父代的好结构保留下来。（`PYVRP_ROOT/cpp/crossover/selective_route_exchange.cpp:74-176,178-230`） |
| 停滞后清空种群并用原始随机解重启 | `FACT`：达到连续无改进次数后清空种群，再装回初始随机解；随机初始化会打乱客户，异质车队时还打乱车型，以增加初始差异。（`PYVRP_ROOT/GeneticAlgorithm.py:171-199`；`PYVRP_ROOT/cpp/Solution.cpp:166-216`） | `INFERENCE`：长期停滞时不继续在同一族解上消耗；重启沿用同一算法合同，不另造第二套搜索器。（`PYVRP_ROOT/GeneticAlgorithm.py:171-199`） |
| 原生对象预分配和复用 | `FACT`：`LocalSearch` 构造时一次性按地点数、车辆数创建节点、路线和时间戳数组；装入/导出解时使用 `reserve()`，路线对象反复 `clear()`/重载。（`PYVRP_ROOT/cpp/search/LocalSearch.cpp:392-455,565-597`） | `INFERENCE`：热路径减少 Python 对象、哈希映射和反复分配，数据更紧凑，也更利于 CPU 缓存。（`PYVRP_ROOT/cpp/search/LocalSearch.cpp:392-455,565-597`） |

### 1.2 MDFIHA-ETGA 2026：只摘它真正独到的部分

- `FACT`：MDFIHA 用序列拼接统计做动作评价，并在常见交换算子外增加 Depot-Insert 和 Depot-Replace；这是“把多车场选择放进教育动作”，不是在 HGS 外再跑一次完整枚举。（`baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/sources/papers/lei_hao_wu_mdfiha_2026_v1.pdf`, p.10）
- `FACT`：ETGA 把待评价动作编码成四维张量，以二值边掩码批量构造候选；论文明确只把它用于四个共同局部算子，而不是把所有逻辑都搬到 GPU。（`ETGA_PDF`, p.12）
- `FACT`：其 leader-follower 多动作策略先选一个最优 leader，再只接纳距离变化为负、罚分不变且与已选动作不冲突的 follower；冲突以共享路线判定。（`ETGA_PDF`, pp.13-14）
- `FACT`：DCREX 是多父代路线块交换，维护 20 个多样性层次，只取前 5 个路线对，并用 discounted UCB1 在 5 个插入动作间分配尝试。（`ETGA_PDF`, pp.14-16）
- `FACT`：在论文自己的同硬件、同单动作策略实验中，ETGA 相对串行版本的加速从 360 节点约 1.6 倍增长到 960 节点接近 7.5 倍，回归 `R²=0.99`；这是该论文内部的扩展性证据，不是与本项目 M1 的绝对时间对比。（`ETGA_PDF`, p.27）
- `INFERENCE`：对我方最有价值的思想是“把同构的小动作整理成紧凑批次”与“选一个主动作后，顺带提交无冲突的确定改善动作”。这两点适合以后替换有证据的串行热循环；不支持把私有完整 Duty 评价整体搬到 GPU。（`ETGA_PDF`, pp.12-14）
- `UNKNOWN`：当前能否取得作者源码尚未证明；论文只写明实现为 C++/CUDA、PyTorch C++ 并称源码将公开，因此本轮只能学设计，不能声称已有可直接移植的原始实现。（`ETGA_PDF`, p.20）

### 1.3 VCGP 2013 / MDFIHA 2026：只保留未被上面覆盖的点

- `FACT`：VCGP 2013 用不含路线分隔符的 giant tour 表示染色体，再用 Split 最短路解码成路线；这是冻结 PyVRP 0.12.2 默认 SREX 路线表示之外的一种结构分解。（`VCGP_PDF`, p.8；`PYVRP_ROOT/solve.py:192-196`）
- `INFERENCE`：该表示的独到价值是把“客户次序遗传”和“如何切成路线”分开；但当前公开成绩我方已对 VCGP 22:6，且 PyVRP 已提供更贴近当前代码的成熟路线级 SREX，因此没有证据支持为 giant-tour/Split 再开一套实现。（`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1270-1272`；`VCGP_PDF`, p.8）
- `INFERENCE`：MDFIHA 2026 的顺序拼接、车场动作、双池和多样性管理已经分别被上面的 PyVRP 与 MDFIHA-ETGA 条目覆盖；在这些已核设计中，没有看到一个比首要对象更适合当前替换的额外基础设施。（`ETGA_PDF`, pp.6-10,17；`PYVRP_ROOT/cpp/search/Route.h:301-332,1001-1177`；`PYVRP_ROOT/Population.py:35-151`）

## 2. 第二层：代码架构对照

| 同一职责 | PyVRP 0.12.2 在哪里 | 我方现在在哪里 | 对照结论 |
|---|---|---|---|
| 解的表示 | C++ `Solution` 聚合路线统计，`search::Route` 保存节点、车辆类型与前后缀缓存。（`PYVRP_ROOT/cpp/Solution.cpp:21-48`；`PYVRP_ROOT/cpp/search/Route.h:301-332`） | 私有侧顶层是完整 `DutyIndividual`，包含物理车辆日任务；路线层临时投影为内核 `Solution`，内核改善后再解码成 Duty 变更。（`OURS/model.py:431-469`；`OURS/kernel_proposals.py:397-456`） | `FACT`：我方多了一层“完整业务解 ↔ 路由骨架”边界。该层对充电、多趟和物理车辆语义是必要差异；不能把路线代理成本当完整真值。（`OURS/integrated_private.py:1-7`） |
| 评价 | `CostEvaluator` 直接读取路线缓存，以 `Route::Proposal` 做一条或两条路线的差量。（`PYVRP_ROOT/cpp/CostEvaluator.h:269-413`） | `DutyFullEvaluator` 是完整真值；`DutyIncrementalEvaluator` 缓存未改变 Duty 的准备与成本，并可对保留候选做完整真值哨兵复核。（`OURS/evaluation.py:499-535,834-875`；`OURS/education.py:412-520`） | `FACT`：我方不是每个动作都盲目全量重算；路线层先由原生内核筛选，完整层再做 Duty 差量。剩余额外成本来自完整模型边界，而非 PyVRP 路线评价器缺失。（`OURS/kernel_proposals.py:397-456`；`OURS/evaluation.py:834-875`；`OURS/education.py:412-520`） |
| 邻域与算子 | `LocalSearch` 持有 granular 邻居、节点算子和路线算子，原生循环直到局部最优。（`PYVRP_ROOT/search/__init__.py:23-36`；`PYVRP_ROOT/cpp/search/LocalSearch.cpp:15-147`） | `IndependentKernelDutyRouteProposalEngine` 已用同一默认邻域和算子；此外还有充电、排程、机制等完整 Duty 教育。（`OURS/kernel_proposals.py:45-177`；`OURS/education.py:328-559`） | `INFERENCE`：纯路由公开赛道不应在原生邻域之外默认叠加大规模自建全扫描；私有侧只有不能由路线内核表达的机制动作才有保留理由。（`OURS/public_search.py:97-186`；`OURS/integrated_private.py:1-7`） |
| 种群 | 原生 `Population` 把解分入可行/不可行 C++ 子池，缓存成对邻近度并做 biased fitness。（`PYVRP_ROOT/Population.py:35-151`；`PYVRP_ROOT/cpp/SubPopulation.cpp:48-177`） | 公开侧已用 `NativePopulationAdapter` 包原生种群；私有单目标用泛型 Python `ExternalPopulation`；旧 `DutyPopulation` 仍留在源码但不在当前导出主路径。（`OURS/public_search.py:471-512`；`OURS/bi_objective_population.py:441-469`；`OURS/population.py:291-486`；`OURS/runner.py:551-567`） | `FACT`：公开侧已完成替换；私有侧因候选是 `DutyIndividual + FullEvaluation`，目前仍有一层自建泛型人口适配。原生种群不能不改接口就直接接收 Duty。（`third_party/setp_hgs_kernel/setp_hgs_kernel/ExternalPopulation.py:43-135`；`third_party/setp_hgs_kernel/setp_hgs_kernel/NativePopulationAdapter.py:14-94`） |
| 罚分 | 原生 `PenaltyManager` 只登记各载荷维、time warp、超距，并按近期可行率调整。（`PYVRP_ROOT/PenaltyManager.py:263-300`） | 公开侧直接用原生罚分；私有侧 `AdaptivePenaltyManager` 按完整模型中的任意 violation type 登记并计价。（`OURS/public_search.py:349-364,471-490`；`OURS/population.py:139-288`；`OURS/integrated_private.py:224-227,1066-1077`） | `FACT`：调节思想重复，但违反类型接口并不相同。`UNKNOWN`：在没有“每种 Duty 违反如何映射到载荷/time-warp/超距”的明确适配前，不能声称原生罚分可以整件无损替掉私有罚分。（`PYVRP_ROOT/PenaltyManager.py:263-300`；`OURS/population.py:161-207,274-288`） |
| 交叉 | 默认多车问题用 SREX，TSP 用 OX。（`PYVRP_ROOT/solve.py:187-196`） | 公开集成路径同样用 SREX/OX；私有侧可由 adapter 的 `breed` 生成完整 Duty 子代。（`OURS/public_search.py:492-512`；`OURS/integrated_private.py:1069-1082`） | `FACT`：公开主线已经采用老师的成熟交叉；旧 `PublicDCREXHGS` 和 DCREX 修复工作台仍留作历史/辅助依赖。（`OURS/public.py:1-40,120-225`） |
| 控制流、修复、重启 | `GeneticAlgorithm` 负责选亲、交叉、教育、入池、罚分登记、不可行修复和停滞重启。（`PYVRP_ROOT/GeneticAlgorithm.py:171-237`） | 公开/私有共用 `IntegratedGeneticAlgorithm`，通过 adapter 插入完整评价、refine、breed、repair、finalise；当前 runner 只导出集成入口，旧外循环保留但不导出。（`third_party/setp_hgs_kernel/setp_hgs_kernel/IntegratedGeneticAlgorithm.py:75-226`；`OURS/runner.py:303-548,551-567`；`OURS/__init__.py:36-45,49-84`） | `INFERENCE`：共用控制流本身方向正确；公开侧若移除自建 refine，已具备退回近乎原生 HGS 数据流的条件，不需要再造控制器。（`PYVRP_ROOT/GeneticAlgorithm.py:171-237`；`OURS/public_search.py:353-364,471-512`） |
| 预计算与数据布局 | 邻居表一次计算；节点、路线、时间戳向量按实例规模预建；路线前后缀缓存只在接受动作后更新。（`PYVRP_ROOT/solve.py:173-183`；`PYVRP_ROOT/cpp/search/LocalSearch.cpp:371-390,565-597`） | 私有 route engine 在构造时一次建问题、邻居、算子和罚分；公开 builder 为主搜索、路线 refine、客户 refine 各建一个 `LocalSearch`。（`OURS/kernel_proposals.py:90-177`；`OURS/public_search.py:328-377`） | `INFERENCE`：私有路线提案层已学到复用方式；公开侧额外两个 `LocalSearch` 的存在只服务自建 compound refine，移除该 refine 后可随之消失。（`OURS/kernel_proposals.py:90-177`；`OURS/public_search.py:328-377`） |

## 3. 第三层：最能体现“又好又快”的原始写法

### 3.1 热循环只遍历近邻，并用时间戳决定是否值得再测

```cpp
for (auto const vClient : neighbours_[uClient]) {
    if (lastUpdated[U->route()->idx()] > lastTested
        || lastUpdated[V->route()->idx()] > lastTested)
        applyNodeOps(U, V, costEvaluator);
}
```

- `FACT`：真实实现位于 `PYVRP_ROOT/cpp/search/LocalSearch.cpp:61-102`，时间戳数组定义于 `PYVRP_ROOT/cpp/search/LocalSearch.h:62-64`。
- `INFERENCE`：这段写法同时做了“空间剪枝”和“状态剪枝”。我方公开 compound refine 的 `while` 外循环会继续调用分配/旋转扫描，虽然内部有旋转缓存，却没有同等级的“路线未变则整个组合不再测”边界。（`OURS/public_search.py:116-186`；`OURS/vidal_compound.py:30-44`）

### 3.2 候选不是复制整条路线，而是把旧路线片段拼成 Proposal

```cpp
auto const uProposal = Route::Proposal(uRoute->before(U->idx() - 1),
                                       uRoute->after(U->idx() + N));
auto const vProposal = Route::Proposal(vRoute->before(V->idx()),
    uRoute->between(U->idx(), U->idx() + N - 1),
    vRoute->after(V->idx() + 1));
```

- `FACT`：Exchange 算子把前缀、移动片段、后缀直接组成两条提案，再交给统一差量评价器。（`PYVRP_ROOT/cpp/search/Exchange.h:85-137,148-189`；`PYVRP_ROOT/cpp/search/Route.h:1001-1177`）
- `FACT`：我方私有路线提案已经通过复制内核 `LocalSearch` 使用这套实现，而不是在 Python 中逐位置重建路由；改良后 SISR 也已接入 `Route::Proposal` / `insertCost()` / 完整 `deltaCost`，微基准约快 26.15 倍。（`OURS/kernel_proposals.py:424-456`；`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1416-1420`）
- `INFERENCE`：今后发现新的串行位置扫描时，首选动作应是把它表达成现有 Route/Proposal 原语，而不是再写一套路线成本函数。（`PYVRP_ROOT/cpp/search/Exchange.h:85-189`；`OURS/kernel_proposals.py:397-456`）

### 3.3 非 exact 差量一旦已非负就结束

```cpp
if constexpr (!exact)
    if (out >= 0)
        return false;
```

- `FACT`：这个短路分别出现在单路线和双路线的载荷维循环以及进入时长计算之前。（`PYVRP_ROOT/cpp/CostEvaluator.h:297-307,372-410`）
- `INFERENCE`：关键不是少写几行，而是按“便宜且最可能淘汰候选的项在前，昂贵项在后”组织热路径。我方完整 Duty 评价必须保留真值，但提案阶段应尽量让内核先淘汰显然不改善的路线骨架。（`OURS/integrated_private.py:1-7`；`OURS/kernel_proposals.py:397-456`）

### 3.4 只有被接受的两条路线才原地更新缓存

```cpp
if (deltaCost < 0) {
    nodeOp->apply(U, V);
    update(rU, rV);
}
```

- `FACT`：节点/路线算子都遵循“先纯评价，改善才 apply”，`update()` 只刷新 U/V 及与它们关联的路线算子缓存。（`PYVRP_ROOT/cpp/search/LocalSearch.cpp:160-224,371-390`）
- `FACT`：我方教育层也只提交 best/first 改善候选，并可在保留前用完整真值核对；这部分架构与老师方向一致。（`OURS/education.py:428-520,539-559`）
- `INFERENCE`：差距不在接受协议，而在某些自建 refiner 为了找到一个可接受候选，先枚举了过多全局组合。（`OURS/public_search.py:116-186`；`solver/reports/public_v2_28_clean_ruler_20260810/PR11A_independent_seed11/decision.json:12-27`；`solver/reports/public_v2_28_clean_ruler_20260810/PR15B_independent_seed11_RERUN/decision.json:12-27`）

### 3.5 成对多样性只算一次，并直接插入有序表

```cpp
auto place = std::lower_bound(oProx.begin(), oProx.end(), div, cmp);
oProx.emplace(place, div, solution.get());
```

- `FACT`：原生 C++ 种群添加新解时计算一次新旧解距离，并把同一数值写入双方有序 proximity；broken-pairs 本身线性遍历已缓存的前驱/后继。（`PYVRP_ROOT/cpp/SubPopulation.cpp:48-65`；`PYVRP_ROOT/cpp/diversity/broken_pairs_distance.cpp:5-31`）
- `FACT`：私有单目标当前 `ExternalPopulation` 也缓存 proximity，但每次 `bisect_left` 前都会用列表推导新建纯距离列表；选择时仍在 Python 更新 fitness。（`third_party/setp_hgs_kernel/setp_hgs_kernel/ExternalPopulation.py:76-135`）
- `INFERENCE`：这是清楚的原始书写差距；但其总耗时占比尚无剖析证据，不能仅凭这段代码就把它列为第一性能病灶。（`PYVRP_ROOT/cpp/SubPopulation.cpp:48-65`；`third_party/setp_hgs_kernel/setp_hgs_kernel/ExternalPopulation.py:76-135`）

## 4. 反向审我方：哪些无效、低效或拖累

| 我方部件 | 当前证据与判断 | PyVRP/复制内核现成替代 | 替换难度与风险 |
|---|---|---|---|
| 公开侧 `_VidalCompoundRefiner`：分配、车型槽、旋转、客户搬移串行精修 | `FACT`：公开干净对照显式启用 compound 和客户 relocation。（`solver/scripts/run_public_v2_28_clean_ruler.py:367-378`）`FACT`：PR11A 中精修 10.740/102.245 秒、1945 万次旋转；PR15B 重跑中 86.911/814.729 秒、1.072 亿次旋转，分别约占总时长 10.5% 与 10.7%，且确有 18/53 次接受。（`solver/reports/public_v2_28_clean_ruler_20260810/PR11A_independent_seed11/decision.json:3-27`；`solver/reports/public_v2_28_clean_ruler_20260810/PR15B_independent_seed11_RERUN/decision.json:3-27`）`INFERENCE`：它是当前证据最强的公开侧耗时拖累，但“净收益是否为负”仍 `UNKNOWN`，因为现有账没有给出同一运行去掉它后的反事实成本。（`OURS/public_search.py:116-186,380-469`） | `FACT`：成熟 `LocalSearch` 已有 RelocateWithDepot、SwapRoutes、SwapStar 等，并已在主搜索启用；公开控制流可直接使用原生 `GeneticAlgorithm`，或保留当前集成控制但让 `refine` 原样返回。（`PYVRP_ROOT/search/__init__.py:23-36`；`PYVRP_ROOT/solve.py:173-196`；`OURS/public_search.py:328-364,471-512`） | `INFERENCE`：代码替换难度低到中；功能风险是失去少量 compound 接受动作，科学风险是未经同口径对照不能断言成绩一定提高。按用户已定“禁止自造”，它应是**第一个替换对象**，但本只读任务不执行替换。（`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:1542-1549`） |
| 公开集成 wrapper 在原生 GA 外再做一层 adapter | `FACT`：当前 wrapper 复刻了选亲、教育、入池、修复和重启，并通过 adapter 调用公开评价/refine；当自建 refine 关闭时，公开候选本来就是原生 `Solution`。（`third_party/setp_hgs_kernel/setp_hgs_kernel/IntegratedGeneticAlgorithm.py:75-226`；`OURS/public_search.py:353-364,471-512`）`UNKNOWN`：没有剖析证明 wrapper 本身造成可见时间损失。 | `FACT`：`PYVRP_ROOT/GeneticAlgorithm.py:171-237` 已有完整原生控制流，`PYVRP_ROOT/solve.py:173-197` 给出组装方式。 | `INFERENCE`：替换难度中；风险主要在现有分项账、停止口径和产物字段需要保持，而不是算法语义。不能把它与 compound 热点混成一个已证实性能问题。（`OURS/public_search.py:71-95`；`third_party/setp_hgs_kernel/setp_hgs_kernel/IntegratedGeneticAlgorithm.py:106-225`） |
| `population.py` 中 `DutyPopulation` 与旧双池/biased fitness | `FACT`：文件明确自述 independently implement；`DutyPopulation` 自己维护双池、距离、fitness、去重和淘汰。（`OURS/population.py:1-20,291-486`）`FACT`：当前单目标私有主路径已用 `ExternalPopulation`，导出入口是 `run_integrated_problem_hgs`，旧 `DutyPopulation` 只由退役 runner 保留。（`OURS/bi_objective_population.py:441-469`；`OURS/runner.py:303-327,551-567`；`OURS/__init__.py:36-45,49-84`）`INFERENCE`：它是重复维护、误读和未来误接回主线的拖累，不是当前已证实的运行热点。 | `FACT`：当前已有 `ExternalPopulation`；公开原生解已有 `Population` / `NativePopulationAdapter`。（`third_party/setp_hgs_kernel/setp_hgs_kernel/ExternalPopulation.py:43-135`；`third_party/setp_hgs_kernel/setp_hgs_kernel/NativePopulationAdapter.py:14-94`） | `INFERENCE`：清理难度中；风险是退役 runner 和历史复算入口仍引用它，不能把“从默认路径移除”误做成无差别删除历史证据入口。（`OURS/runner.py:551-567`） |
| 私有 `AdaptivePenaltyManager` | `FACT`：它仍在私有集成主路径实例化和登记，按任意 violation type 维护窗口、系数和完整成本。（`OURS/integrated_private.py:224-227,1066-1077`；`OURS/population.py:139-288`）`INFERENCE`：自适应调节政策与 PyVRP 重复；按业务违反类型计价的接口则是私有模型差异。 | `FACT`：原生 `PenaltyManager` 已有数据定标初值、目标可行率调整和 booster，但只认各载荷维、time warp、超距。（`PYVRP_ROOT/PenaltyManager.py:176-300`） | `UNKNOWN`：没有现成的无损整件替换；若先写薄适配，只复用更新器、保留 violation 映射与完整成本，难度中、语义风险中。若强行把所有 Duty 违反塞进三类原生量，风险高，会改变完整评价含义。（`PYVRP_ROOT/PenaltyManager.py:176-300`；`OURS/population.py:139-288`） |
| 私有单目标 `ExternalPopulation` | `FACT`：它是当前主路径人口容器，保持可行/不可行双池与多样性配对，但以 Python 列表和回调承载完整 Duty 评价。（`OURS/bi_objective_population.py:441-469`；`third_party/setp_hgs_kernel/setp_hgs_kernel/ExternalPopulation.py:43-135`）`INFERENCE`：它是基础设施层仍未完全原生化的地方；原始书写比 C++ `SubPopulation` 多出 Python 分配和回调。`UNKNOWN`：没有当前 profile 证明它是主要墙钟热点。 | `FACT`：原生 `SubPopulation` / `Population` 更紧凑，但类型固定为内核 `Solution` 与 `CostEvaluator`；`NativePopulationAdapter` 也依赖原生 Solution。（`PYVRP_ROOT/cpp/SubPopulation.cpp:48-177`；`PYVRP_ROOT/Population.py:75-151`；`third_party/setp_hgs_kernel/setp_hgs_kernel/NativePopulationAdapter.py:14-94`） | `INFERENCE`：替换难度高，风险是把路由投影的便宜成本误用于完整 Duty 生存选择。只有原生容器能接收外部 objective/feasibility/fingerprint 回调时，才可能不改科学语义地替换。（`OURS/integrated_private.py:1-7,1069-1106`） |
| `public.py` 的旧 `PublicDCREXHGS` 与大批辅助代码 | `FACT`：文件仍拥有独立控制循环和 DCREX 修复工作台；当前公开默认 builder 明说历史 customer-reassignment builder 不再默认，但 `vidal_compound.py` 和 `public_assignment.py` 仍从 `public.py` 导入插入工作台与解/基因转换辅助函数。（`OURS/public.py:1-40,120-225`；`OURS/public_search.py:1-6`；`OURS/vidal_compound.py:23-30`；`OURS/public_assignment.py:15-25`） | `FACT`：默认控制和种群已有复制内核实现；真正仍被引用的是少数辅助函数，不是整套旧 solver。（`OURS/public_search.py:15-34,471-512`） | `INFERENCE`：应替换/拆出的对象是依赖的辅助原语，之后才能让旧 solver 与热路径解耦；难度中，风险是直接删整文件会误删 compound 当前依赖。它主要是架构拖累，未证明是运行热点。（`OURS/public.py:120-225`；`OURS/vidal_compound.py:23-30`；`OURS/public_assignment.py:15-25`） |
| SISR 自建扫描线 | `FACT`：它已改用复制内核增量原语并获得约 26.15 倍微基准提速，但五题仍三负两平、每题每代累计扫描 1.141 亿至 4.045 亿个位置，已按预注册条件停止；默认关闭。（`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1414-1424`）`FACT`：用户已将 SC3 判为低效并要求不用自造基础设施。（`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:1535-1558`） | `FACT`：路线差量已替换为内核 `Route::Proposal` / `insertCost`；剩余全扫描不是内核缺少差量函数，而是 SISR 算法形态本身。（`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1416-1424`） | `INFERENCE`：不再继续为它造扫描优化；保持关闭即可。若未来需要同类结构跳跃，优先使用成熟 SREX 或有源码的已发表实现，而不是复活当前 SISR。（`PYVRP_ROOT/crossover/selective_route_exchange.py:13-25`；`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1414-1424`） |

## 5. 接下来该干什么

- `FACT`：用户已经拍板的下一步是**单一算例、最小预算的全流程贯通试验**，只检查从公开 benchmark 到最后机制实验能否跑通，不追性能、不长跑。（`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:1539-1549`）
- `INFERENCE`（执行建议）：落实这一步时，公开段应以冻结 PyVRP/复制内核现成路径为基线，不再给自建 compound 或 SISR 默认开火；本报告已经指出首先该换掉的对象和可以接上的现成部件，但本只读任务不实施替换、不启动贯通试验。（`OURS/public_search.py:310-320,400-469`；`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1414-1424`；`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:1542-1549`）
- `UNKNOWN`：私有 `AdaptivePenaltyManager` 与 `ExternalPopulation` 尚无无损的原生整件替代。下一次真正施工前，只需要先核清这两个接口如何保留完整 Duty 真值；不能为了“换成原生”把完整模型降成路由代理评价。（`OURS/integrated_private.py:1-7,1066-1106`；`PYVRP_ROOT/PenaltyManager.py:273-300`）

LEARN_RIVALS_END
