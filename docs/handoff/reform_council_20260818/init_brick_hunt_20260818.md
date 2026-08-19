# 带时间窗／班次意识的初始解构造零件：开源市场扫货报告

日期：2026-08-18
任务边界：只做仓内与公开市场取件调查；未改源码、未运行求解器、未下载候选进仓。

## 结论先说

**DECISION（代理推荐，尚未施工）：首选仓内已经存在的 PyVRP 0.12.2 `greedy_repair`。**

它不是名字相似的外部替代品，而是当前复制内核已经编译并暴露的上游修复算子。给每个物理车辆槽位先建一条空路线，再把全部客户交给它逐个插入，就能把“修复算子”直接用成“构造算子”。这一接法：

- 不引入新依赖；
- 不改上游 C++；
- 不改变当前每个物理车辆只有一个槽位的建模；
- 继续把趟切分、充电、SOC 和完整评价留给现役生产链；
- 预计只需约 **45–90 行**项目薄适配代码。

**FACT：它的时间窗约束是罚分，不是硬过滤。** 因此它最适合作为“时间窗大体可行的候选构造器”，最终仍须由现役硬评价拒绝违约解。这也是首选的最大风险。

若首选在同一冻结探针上被硬评价大量拒绝，第二选择是 **OR-Tools Routing 的 `PARALLEL_CHEAPEST_INSERTION`**：它通过 Time dimension 硬检查客户时间窗和车辆数，但要新接一套模型与依赖，预计约 170–240 行。第三选择是 VROOM／pyvroom；它也能硬守时间窗，但公开入口是整套求解器，不是干净的独立构造函数。

本轮没有找到同时满足以下四项的独立 Python 小包：**硬时间窗、有限车辆槽位、可固定 commit 与许可证、直接输出路线序列**。这不阻止首选施工，但这个缺口必须如实保留。

---

## 一、先钉死缺件接口

### 输入

- 客户集合：坐标、需求、服务时长、硬时间窗、AM／PM 班次归属；
- 已知车辆槽位数；在本项目里槽位还带物理车辆身份、车型和所属仓库；
- 距离／时间矩阵或可等价查询的旅行时间。

### 输出

- 每个已使用车辆槽位对应一条客户序列；
- 每个客户恰好出现一次；
- 使用路线数不超过车辆槽位数；
- 序列应尽量满足客户硬时间窗；
- 同一路线中 AM 客户应在 PM 客户之前。

### 明确不归本零件负责

- 多趟切分；
- 充电站选择与充电时长；
- SOC 演化；
- 完整 Duty 排程；
- 生产口径的成本、排放和可行性评价。

**FACT：现役链已经承担这些下游职责。** 当前 `_decode_changes()` 按 `route.vehicle_type()` 找回物理车辆槽位，随后 `_split_replacement_trips_by_shift()` 只在相邻班次边界切趟、不重排客户；证据见
`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:739-770` 与 `:679-710`。

---

## 二、AM／PM 能不能只靠时间窗表达

### 当前选中算例

**FACT：可以，而且数据已经这样表达，不需要再造“虚拟时间窗”。**

- 班次合同：AM 为 480–660 分钟，PM 为 780–1140 分钟；17 个 AM 客户、33 个 PM 客户。见
  `data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/shift_contract.json`。
- 50 个订单的实际窗口核算结果：
  - AM：最早到达下界 480.000000–602.753344，最晚到达上界 525.872298–633.479389；
  - PM：最早到达下界 780.000000–1081.004251，最晚到达上界 822.354562–1130.130691。
  原始行见同目录 `orders.csv` 的 `time_window_early_minute`、`time_window_late_minute` 和 `shift_id`。

**INFERENCE：若旅行与服务时间非负，且所有 AM 窗口上界严格早于所有 PM 窗口下界，那么任何硬时间窗可行路线都不可能出现“先 PM、后 AM”。** 当前算例满足这个分离条件。

### 适用边界

- 对 OR-Tools、VROOM、jsprit 这类硬时间窗构造器，当前时间窗本身就会强制 AM→PM；
- 对 PyVRP `greedy_repair` 这类罚分构造器，分离窗口会引导顺序，但不构成硬保证；
- 若未来某个算例的 AM／PM 原始窗口重叠，把窗口强行压到上午／下午只有在这本来就是获批班次合同的机械编码时才成立；否则会改变可行域，不属于“接零件”。

---

## 三、仓内已囤构件复筛

### `third_party/harvested_materials/*`

**FACT：八类材料目录已按“是否含可调用的初始构造器”重新筛过。**

- **VROOM**：有真正的时间窗插入构造，进入候选表；
- **jsprit**：有约束管理器和初始插入工厂，进入候选表，但 Java 接口代价高；
- **KAYROS**：有 Python binding 暴露的 `greedy_makespan()`，进入候选表；
- **EURO/NeurIPS 2022 quickstart**：仓内快照只有 README、环境与控制器，没有落下 HGS-VRPTW C++ 构造源码；本轮另在其公开仓固定 commit 核了源码；
- FRVCP、carbon-aware computing、动态请求／仿真／控制器、pyCoopGame、pymoo：分别服务充电、碳时变、动态调度、合作博弈和多目标优化，没有本任务所需的路线初始构造入口。

### `third_party/harvested_operators/*`

- **复制 PyVRP 0.12.2**：`greedy_repair` 与 `nearest_route_insert` 都已在当前内核中；
- **MA-FIRD**：有可行插入／regret 插入，但 C++ 状态耦合重，且会自行增开路线；
- **open-source SISR VRPTW**：初始解是一客户一路，修复函数是类内私有流程；
- **SISRs Python**：同样是一客户一路，不看时间窗与车辆上限；
- **yangwusi MDVRPTW**：所谓 greedy repair 操作的是单一客户排列，完整 `calObj()` 再切路线，不是可直接拿走的有限槽位时间窗构造器；
- 其余 depot split、reload、covering、route-depot assignment 构件没有本接口。

---

## 四、主候选表

行数均为未来项目薄适配件的工程估算，不含测试；本轮没有实际施工。

| 名称 | 许可证 | 人类出处证据（一行） | 精确 API／入口 | 时间窗支持？ | 班次可表达？ | 接入成本 | 判定 |
|---|---|---|---|---|---|---:|---|
| **PyVRP 0.12.2 `greedy_repair`**；[仓库](https://github.com/PyVRP/PyVRP)；commit [`ea0c4211819edac6fd920413ad7508cc9ad56e0e`](https://github.com/PyVRP/PyVRP/tree/ea0c4211819edac6fd920413ad7508cc9ad56e0e) | MIT | PyVRP／ORTEC RoutingLab 人类团队；公开论文、release 与 DIMACS VRPTW 竞赛血统 | `greedy_repair(routes: list[Route], unplanned: list[int], data: ProblemData, cost_evaluator: CostEvaluator) -> list[Route]`；[上游签名](https://github.com/PyVRP/PyVRP/blob/ea0c4211819edac6fd920413ad7508cc9ad56e0e/pyvrp/repair/_repair.pyi) | **软支持**：插入增量包含 time-warp 与超载罚分，不是硬过滤 | 当前分离窗会强烈引导 AM→PM，但仍须硬评价确认 | **45–90 行** | **需薄适配／首选** |
| **Google OR-Tools Routing**；[仓库](https://github.com/google/or-tools)；commit [`98c165af62df62b3056c2ee0fca66b24e79097cb`](https://github.com/google/or-tools/tree/98c165af62df62b3056c2ee0fca66b24e79097cb) | Apache-2.0 | Google 官方维护，长期公开发布；策略枚举源码直接引用 Clarke–Wright | `RoutingIndexManager(n, k, depot)` → `RoutingModel` → `AddDimension(...)` → `CumulVar(i).SetRange(a,b)` → `first_solution_strategy=PARALLEL_CHEAPEST_INSERTION`／`SAVINGS` → `SolveWithParameters()`；[官方 VRPTW 示例](https://github.com/google/or-tools/blob/98c165af62df62b3056c2ee0fca66b24e79097cb/ortools/constraint_solver/samples/vrp_time_windows.py) | **硬支持**：Time dimension 与传播过滤器检查窗口 | 分离窗直接强制 AM→PM | **170–240 行**＋新依赖 | **需薄适配／第二选择** |
| **VROOM 1.15 系／pyvroom 1.15.2**；[VROOM](https://github.com/VROOM-Project/vroom) commit [`07be776fc20b8d6c85d9f78797e38a9f4e44ec44`](https://github.com/VROOM-Project/vroom/tree/07be776fc20b8d6c85d9f78797e38a9f4e44ec44)；[pyvroom](https://github.com/VROOM-Project/pyvroom) commit [`bb4ea9c2b19c0e76d57dc07d62d36e377282f381`](https://github.com/VROOM-Project/pyvroom/tree/bb4ea9c2b19c0e76d57dc07d62d36e377282f381) | BSD-2-Clause | VROOM Project／Verso Technologies 公开维护；多年版本与命名维护者 | 内部 `heuristics::basic(...)` 明注 “variant of Solomon I1”；公开可用 `vroom -i input.json -x 0 -t 1`，或 pyvroom `Input()`／`add_vehicle()`／`add_job()`／`solve(exploration_level=0, nb_threads=1)` | **硬支持**：插入前调用 `is_valid_addition_for_tw`；但完整求解允许任务留在 `unassigned` | 分离窗直接强制 AM→PM；必须拒绝任何 `unassigned` | **120–190 行**＋binary／wheel | **需薄适配／第三选择**；公开入口不是独立构造器 |
| **ORTEC HGS-VRPTW 构造段**；[仓库](https://github.com/ortec/euro-neurips-vrp-2022-quickstart)；commit [`77a1a24e6b30baf3aab8931c020302c3975ca77e`](https://github.com/ortec/euro-neurips-vrp-2022-quickstart/tree/77a1a24e6b30baf3aab8931c020302c3975ca77e/baselines/hgs_vrptw) | MIT | 许可证列明 Vidal 原 HGS-CVRP 与 ORTEC 2022 追加贡献；公开 HGS-VRPTW 论文／竞赛基线 | C++ `LocalSearch::constructIndividualWithSeedOrder(int toleratedCapacityViolation, int toleratedTimeWarp, bool furthest, Individual*)`；另有 `constructIndividualBySweep(...)` | 以 `toleratedTimeWarp=0` 硬过滤插入；**但路线用尽后会把未分配客户追加到最后一路** | 正常插入阶段可由窗口表达；兜底追加会破坏保证 | **>250 行**，需搬 `Params/Individual/LocalSearch/TWData` 或加绑定 | **不适配直接接**；算法证据好，零件边界不干净 |
| **KAYROS 1.6.0**；[仓库](https://github.com/0nyr/kayros)；commit [`ad3fdec229dfd0a75e619bccce47838adee2c5de`](https://github.com/0nyr/kayros/tree/ad3fdec229dfd0a75e619bccce47838adee2c5de) | MIT | Florian Rascoussier 的博士研究项目，具作者、引用、测试和版本史；仓库同时披露大量 AI 辅助，不是匿名空壳 | Python binding：`kayros._core.greedy_makespan(instance) -> (ok, routes)`；C++：`bool greedy_makespan(const Instance&, vector<vector<int32_t>>& routes_out)` | 构造时检查时间窗、容量与回仓 | 分离窗可以表达 | **120–200 行**＋新二进制依赖 | **需薄适配但不推荐优先**：构造函数可产生多于 `num_vehicles` 的路线，另一个完整评价函数才判超车数 |
| **MA-FIRD**；[仓库](https://github.com/leizy1008/MA-FIRD)；commit [`065464169231e8fc6cc4edd67c04bf41354df9c4`](https://github.com/leizy1008/MA-FIRD/tree/065464169231e8fc6cc4edd67c04bf41354df9c4) | MIT | Zhenyu Lei、Jin-Kao Hao；IEEE Transactions on Evolutionary Computation 论文公开实现 | `Insertion::setContext(Random*, Parameters*, Data*)`；`Insertion::run(vector<Route*>& routes, vector<Node*>& nodes, int opt)`，`opt=0` best feasible、`opt=1` regret | 检查反向时间窗与容量 | 可由窗口表达 | **>250 行**＋C++ 绑定／模型映射 | **不适配直接接**：无可行插入时自行创建新 `Route`，不守有限槽位 |
| **jsprit**；[仓库](https://github.com/graphhopper/jsprit)；commit [`c8d94631543ac8154b17d31fd03e67d1f72a23f1`](https://github.com/graphhopper/jsprit/tree/c8d94631543ac8154b17d31fd03e67d1f72a23f1) | Apache-2.0 | GraphHopper 长期人类维护项目，公开文档、版本和贡献者 | `new BestInsertionBuilder(vrp, fleetManager, stateManager, constraintManager).build()` → `new InsertionInitialSolutionFactory(insertionStrategy, costCalc).createSolution(vrp)`；客户 `Service.Builder.addTimeWindow(earliest, latest)` | 约束管理器硬检查时间窗，支持 finite fleet | 可由窗口表达 | **>250 行**或 Java subprocess／服务桥 | **登记但不推荐**：技术适配，语言与部署成本不适配本项目 |

### 对首选源码的额外核验

**FACT：当前复制内核已经暴露同一个 API。** 本地签名见
`third_party/setp_hgs_kernel/setp_hgs_kernel/repair/_repair.pyi:22-33`。

**FACT：固定 commit 的上游 `greedy_repair.cpp`、`repair.cpp` 与本地复制件把命名空间统一还原后无字节差异。** 本地核心逻辑见：

- `greedy_repair.cpp:21-61`：已有路线为空且客户非空才报错；对每个未插客户遍历所有路线与所有插入位置，选罚分增量最小处；
- `repair.cpp:25-52`：输入有几条路线就导出几条路线，并原样保留每条路线的 `vehicleType`。

[上游测试](https://github.com/PyVRP/PyVRP/blob/ea0c4211819edac6fd920413ad7508cc9ad56e0e/tests/repair/test_greedy_repair.py) 还直接验证了两件事：它会使用预先存在的空路线；它不会自行创建新路线。由此，预建“一物理车辆一空路线”可以把车辆槽位上限结构性地钉住。

`nearest_route_insert` 没有排到首选：它先按路线重心选路线，已有非空路线时不利于均衡启用空槽位；而本任务首先需要的是在所有槽位、所有位置间比较时间窗罚分后的插入代价。

---

## 五、其余市场候选与拒绝原因

| 名称 | 许可证 | 人类出处证据（一行） | 精确 API／入口 | 时间窗支持？ | 班次可表达？ | 接入成本 | 判定 |
|---|---|---|---|---|---|---:|---|
| **RoutingBlocks 0.2.1**；[仓库](https://github.com/tumBAIS/RoutingBlocks)；commit [`2d2ee06c79b5d458b1aeeafd95a2b42b5441079a`](https://github.com/tumBAIS/RoutingBlocks/tree/2d2ee06c79b5d458b1aeeafd95a2b42b5441079a) | **UNKNOWN**：`pyproject.toml` 分类器写 MIT，但该 commit 根目录没有本项目自己的许可证正文；只有 vendored 小库许可证 | TUM BAIS 公开研究项目，有作者和文档，不是空壳 | `BestInsertionOperator(instance, move_selector).apply(evaluation, solution, vertex_ids)` | 由调用方自写 `Evaluation`；示例通常用罚分 | 可以自定义，但不是现成能力 | **180–250 行**＋自写评价 | **不接**：许可证证据不完整，且核心约束仍要我们自写 |
| **open-source SISR VRPTW**；[仓库](https://github.com/hankarudova/open-source-sisr-routing)；VRPTW commit [`857c8eeafd95cbdf8245620486d309369f1aab20`](https://github.com/hankarudova/open-source-sisr-routing/tree/857c8eeafd95cbdf8245620486d309369f1aab20) | Apache-2.0 | Masaryk University／CPAIOR 作者与配套论文 | `Sisrs::createInitialSolution()` 为私有方法；公开入口是完整 `localSearch()`／CLI | VRPTW 搜索支持；初始解却是一客户一路 | 单客户路线天然无逆序，但完全不守本项目车辆槽位 | **>250 行** | **不适配**：修复侧不是公开构造零件，初始法也不合接口 |
| **Vidal HGS-CVRP v2.0.0**；[仓库](https://github.com/vidalt/HGS-CVRP)；commit [`b062d5fccb1f64864dd65a94dac35929059ab089`](https://github.com/vidalt/HGS-CVRP/tree/b062d5fccb1f64864dd65a94dac35929059ab089) | MIT | Thibaut Vidal 的公开参考实现与论文 | 完整 HGS C++；没有独立 VRPTW 构造 API | **不支持时间窗** | 不能 | **>250 行** | **不适配**；不能拿 CVRP 构造为 VRPTW 叙事。时间窗版的可核公开构造段已在上表单列 |
| **VeRyPy**；[仓库](https://github.com/yorak/VeRyPy)；commit [`8698f910ffcfb4bc8743aedbf203d6de72fbe006`](https://github.com/yorak/VeRyPy/tree/8698f910ffcfb4bc8743aedbf203d6de72fbe006) | MIT | 面向经典 VRP 启发式的公开研究实现，含原论文复现实验 | `parallel_savings_init(D, d, C, L=None, minimize_K=False, savings_callback=...)`；另有 sequential savings | **不支持客户时间窗**；README 明确是对称 CVRP | 不能直接表达 | 若补时间窗将 **>250 行**且改算法 | **不适配**：Clarke–Wright 实现干净，但缺的恰好是本任务核心约束 |
| **vrpy `_ClarkeWright`**；[仓库](https://github.com/Kuifje02/vrpy)；commit [`ff325cbe64c08d53969fc54b7ff9f7a9b2fa1d63`](https://github.com/Kuifje02/vrpy/tree/ff325cbe64c08d53969fc54b7ff9f7a9b2fa1d63) | MIT | 有作者、发布史、文档与公开用户，不是匿名空壳 | `_ClarkeWright(G, load_capacity=None, duration=None, num_stops=None).run()` | 此初始化只检查容量、总时长、停点数，不逐客户检查 ready／due | 不能直接表达 | 接完整 vrpy 约 **180–250 行**；抽初始化仍需重写 | **不适配** |
| **py-ga-VRPTW**；[仓库](https://github.com/iRB-Lab/py-ga-VRPTW)；commit [`5949e3f0359ae0ad69a63a7adffe432a60456ec4`](https://github.com/iRB-Lab/py-ga-VRPTW/tree/5949e3f0359ae0ad69a63a7adffe432a60456ec4) | MIT | iRB-Lab 大学课程／实验室公开仓，具长期可见使用量 | `ind2route(individual, instance)` | 名为 VRPTW，但切路只检查容量与回仓 due time，未逐客户检查 ready／due | 不保证 AM→PM | **80–150 行**但仍需另写约束 | **不适配**：名字支持不等于构造阶段支持 |
| **SISRs_Python**；[仓库](https://github.com/isaacbalster/SISRs_Python)；commit [`e7135e8601fcb0f7bdfc3043101ff17f3251c97e`](https://github.com/isaacbalster/SISRs_Python/tree/e7135e8601fcb0f7bdfc3043101ff17f3251c97e) | MIT；仓内保留许可证原文 | 有具名作者，但仓内来源审查发现公开活动很短、无论文／学位论文／基准取证，不能确认相关实现血统；所需算子实际也不存在 | `SISRs.get_initial_sol(capacity, dist_matrix, sites, tours)` | 无时间窗；每客户新建一路 | 无逆序但车辆数等于客户数 | 小于 50 行调用，但输出语义错误 | **不适配** |
| **yangwusi MDVRPTW**；[仓库](https://github.com/yangwusi/Algorithms_for_solving_VRP)；commit [`e96ec997a7372f3f087008c9e303d40e411c79f6`](https://github.com/yangwusi/Algorithms_for_solving_VRP/tree/e96ec997a7372f3f087008c9e303d40e411c79f6) | LGPL-3.0；仓内保留许可证原文 | 具名公开教学／算法仓 | `createGreedyRepair(remove_list, model, sol)` | 通过每次完整 `calObj()` 间接评价；输入输出是单一客户排列 | 不是车辆槽位路线构造接口 | 抽取需重写模型 | **不适配** |
| **PyPI `tsp_cw` 1.0.4**；[PyPI](https://pypi.org/project/tsp-cw/) | PyPI 元数据称 MIT；**无可核仓库正文** | 元数据列作者 Le Sy Thuc；所链 GitHub 仓当前不可达 | 未取得可固定源码 API | TSP／Clarke–Wright，无已证时间窗 | 不能 | 无法可靠估算 | **拒绝**：没有 commit 与可复核源码，不进入供应链 |
| **PyPI `pyevrp` 0.2.1**；[PyPI](https://pypi.org/project/pyevrp/) | 只有分类器声明，链接仓库不可达 | Alpha 包；未取得可复核作者仓与引用 | 未取得固定 API／commit | 未证实构造阶段时间窗 | 未证实 | 无法可靠估算 | **拒绝**：出处、commit、许可证正文三项不闭合 |

**FACT：在本轮逐项核过的独立 Python 候选中，没有发现一份合格的 Solomon I1 + 硬时间窗 + 有限车辆槽位小包。** 这是有边界的检索结果，不等于宣称整个互联网绝对不存在。

---

## 六、文献原件与最后手段

### Solomon 1987

Marius M. Solomon, “Algorithms for the Vehicle Routing and Scheduling Problems with Time Window Constraints,” *Operations Research*, 35(2), 254–265, DOI: [10.1287/opre.35.2.254](https://doi.org/10.1287/opre.35.2.254)。

- [出版社原始 PDF](https://pubsonline.informs.org/doi/pdf/10.1287/opre.35.2.254)
- 插入后时间窗可行性的递推与判定：**论文页 255–256，Lemma 1.1**；
- I1 构造的种子客户、插入位置代价、客户选择与循环：**论文页 257–258，§1.3**；
- 对 savings 法加入时间窗检查的说明：**论文页 256，§1.1**。

### Clarke–Wright 1964

G. Clarke and J. W. Wright, “Scheduling of Vehicles from a Central Depot to a Number of Delivery Points,” *Operations Research*, 12(4), 568–581, DOI: [10.1287/opre.12.4.568](https://doi.org/10.1287/opre.12.4.568)。

- [出版社原始 PDF](https://pubsonline.informs.org/doi/epdf/10.1287/opre.12.4.568)
- savings 推导：**论文页 570–572**；
- 简单仓库 savings `d(0,y)+d(0,x)-d(y,x)` 与计算步骤：**论文页 572–575**。

**FACT：Clarke–Wright 1964 原法没有客户时间窗。** 若以后走“忠实实现”最后手段，不能只照 Clarke–Wright；至少要按 Solomon 1987 第 256 页给每次合并／插入补上时间窗可行性检查。更直接的最后手段是按 Solomon 1987 第 255–258 页忠实实现 I1。

**DECISION：现在不走自写。** 当前已有三个可接开源层级，按 P106 顺序先试仓内 PyVRP，再试 OR-Tools／VROOM；只有它们用真实硬评价证明不适配后，才把“按原论文页码忠实实现 I1”交给用户作为第三级选项。

---

## 七、推荐顺序

1. **PyVRP 0.12.2 `greedy_repair` + 每个物理槽位一条空路线。**
   最薄、无需新依赖、上游血统与现役内核完全同源，且车辆身份不会丢。
2. **OR-Tools `PARALLEL_CHEAPEST_INSERTION` + Time dimension。**
   若首选的软时间窗导致硬评价拒绝率不可接受，它是最干净的硬约束替代；代价是模型桥接和新依赖。
3. **VROOM／pyvroom，固定 exploration level 0，并把任何 `unassigned` 当失败。**
   时间窗强，但公共入口混入整套引擎，零件边界不如前两项。
4. **按 Solomon 1987 页 255–258 忠实实现 I1。**
   仅在前三项都以同一接口证据证明不合格时启用；这是 P106 的最后手段，不是当前推荐。

HGS-VRPTW、MA-FIRD、KAYROS、RoutingBlocks、jsprit 都有值得借鉴的构造思想，但不是比前三项更干净的可接零件：要么 C++／Java 状态耦合超过薄适配件，要么车辆数兜底不守合同，要么许可证证据不完整。

---

## 八、首选零件的蓝图六栏增补草案

### A. 现状取证

1. **FACT：原生 `make_random` 不看 AM／PM 顺序。** 现役下游只按连续班次块切趟，不会把 PM→AM 重排回来；先前静态计算中，25 个随机解至少一个满足班次顺序必要条件的上界为 ENT_A 0.50%、联合见证 0.062%。证据见 `native_init_scout_20260818.md:137-159`。
2. **FACT：当前内核已有上游 `greedy_repair` Python binding。** 无需新增 C++ 或第三方目录。
3. **FACT：当前 `RouteProposalEngine` 已有唯一物理车辆槽位映射，并持有 `PenaltyManager.init_from(...).booster_cost_evaluator()`；见 `kernel_proposals.py:197-202`、`:986-1039`。
4. **FACT：当前实例的 AM／PM 硬窗已经分离。** 不需改数据或新增班次排序规则。

### B. 积木清单

| 积木 | 出处 | 用途 | 是否改动 |
|---|---|---|---|
| `Route(data, [], vehicle_type)` | PyVRP 0.12.2 现有绑定 | 为每个物理车辆槽位预建空容器 | 不改 |
| `repair.greedy_repair(...)` | PyVRP 0.12.2 现有绑定 | 在所有槽位和所有位置中逐客插入 | 不改 |
| 现役 `booster_cost_evaluator()` | 当前 `RouteProposalEngine` | 给距离、时间窗违约、容量违约统一增量代价 | 不改参数 |
| 现役随机数流／`make_random` | PyVRP 0.12.2 | 只提供客户插入顺序的多样性 | 纯上游探针保持原样；新构造臂单列 |
| `_decode_changes()` 与 shift split | 当前生产链 | 找回物理车、按相邻班次切趟 | 零改动 |
| Duty completion／charging／full evaluator | 当前生产链 | 完整物理可行性与正式记账 | 零改动 |

### C. 拼装步骤

未来施工时，建议新增一个独立的“上游插入构造”入口，不改 P105 的纯 `make_random` 探针：

1. 从当前 `_data` 和 `_vehicle_type_by_duty_id` 取得客户位置编号与全部物理槽位；
2. 对每个物理槽位创建 `Route(self._data, [], vehicle_type_index)`；
3. 用现役上游随机流生成一次客户排列。最少自写的做法是把一次 `make_random` 的所有路线展平成客户排列，只借它的随机次序，不接受它的分车结果；
4. 调用：

   ```python
   repaired_routes = greedy_repair(
       empty_slot_routes,
       customer_order,
       self._data,
       self._cost_evaluator,
   )
   ```

5. 只在组装 `Solution` 时去掉空路线；非空路线保留原 `vehicle_type`，交给现役 `_decode_changes()`；
6. 后续原样经过班次边界切趟、Duty completion、充电、SOC 与完整评价；
7. 硬评价拒绝时记录原始原因，不按班次排序、不增加抽样、不调罚分来救结果。

**INFERENCE：这条接法比把客户先按 AM／PM 排序更干净。** 时间窗是否足以诱导正确顺序由上游插入代价和现役硬评价共同给出证据；代理不另写一条“班次优先”算法。

### D. 缺口如实

- **UNKNOWN：真实硬可行通过率。** 本任务禁止跑求解器，因此尚无一次动态结果；
- **UNKNOWN：客户插入顺序对通过率和多样性的影响。** `greedy_repair` 按 `unplanned` 顺序逐个处理；
- **FACT：`greedy_repair` 总会选一个罚分最小位置，不会因所有位置都时间窗违约而停止。** 因此输出可能仍含 time warp；
- **FACT：它不会新建路线。** 车辆槽位数量和身份可由输入空路线结构保证；
- **HALT（只针对更强接口）：没有找到可直接接入、许可证与 commit 都闭合的“独立 Python 硬时间窗 + 有限槽位构造函数”。** 若用户要求构造器自身必须硬可行，当前首选不够，应转 OR-Tools，而不是在 PyVRP 下游自写硬插入算法。

### E. 施工轮验收

本轮不执行；未来施工轮应在同一冻结数据、同一物理槽位、同一完整评价上核：

1. 固定 PyVRP commit、MIT 许可证与本地 namespace-only 差异；
2. 证明输入几条空槽位路线，输出仍是同样数量和同样 `vehicle_type`；
3. 每个客户恰好一次；同时报告完成客户数和完成需求量；
4. 每条序列中不得出现 PM 后再 AM；
5. 完整评价的客户硬时间窗、车辆时钟、容量、SOC、充电全部通过；
6. P105 纯 `make_random` 探针原样保留，新构造臂的结果另记，不混写；
7. 失败种子和原始拒绝原因全部保留，不额外重抽或改参数。

这里没有新设科学阈值；是否比原生随机更适合作为生产初始化，由同批结果如实比较。

### F. 净行数预算

- 本报告轮：生产源码 **+0／-0**；
- 未来施工估算：薄适配生产代码 **+45–90 有效行**；
- 未来测试估算：**+60–100 行**；
- 上游 C++、`third_party/`、受保护评价器：**0 行改动**；
- 按现行“薄适配件不超过 250 有效行”规则，预计有充足余量。若真实施工逼近 250 行，说明它已不是薄接，应如实报告并比较 OR-Tools 方案，不能把额外算法藏进适配层。

---

## 九、最终 HALT 与最大风险

**本次扫货整体不 HALT：首选零件已经找到，而且就在当前冻结内核中。**

仍然 HALT 的只有更强主张：目前没有证据说首选构造出来的每一条路线都硬时间窗可行，也没有动态证据说它能显著提高 ENT_A／联合见证的可物化率。这个结论只能留给下一施工轮的真实硬评价。

直接说首选的最大风险：**PyVRP `greedy_repair` 把时间窗违约当罚分，而不是禁行。它可能把所有客户都漂亮地塞进固定车辆槽位，却仍留下 PM→AM 或其他 time warp，最后在现役 Duty 硬评价处整批被拒。**
