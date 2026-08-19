BUILD_SPEC_DRAFT_CODEX

# 成品双规划之二：施工详情方案（Codex 草案）

## 0. 文档边界

`FACT`：本文件是设计书 V3 的施工详情草案，不是代码补丁，也不是正式实验报告。本轮不修改求解器、不运行求解器、不生成正式实验结果；截至本轮，正式实验数仍为 0。

`USER DECISION`：用户已经授权代理自主推进到“最终设计方案＋施工详情方案”，但明确要求用户亲自批准后才施工。因此本文件只描述施工动作、接口、验收和回滚，不执行这些动作。

`FACT`：S0/S1/S2 的修复已写入当前工作区。S1 已把生成器和检查器的出发时钟统一到 `route_departure_second`；S2 已在未受保护的评价层加入单班次候选路线核验。对应完整 diff 见 `solver/reports/fix_s1s2_20260816/report.md`。

`INFERENCE`：当前真正卡住的是候选解生产，而不是再增加一个搜索算子。Round 3 的技术双父代轨迹显示，候选仍集中在初始可行解，失败原因还没有形成可用于构造反馈的完整记录。所以施工顺序先修候选合同和记录链，再谈方向性效果。

`UNKNOWN`：本文件没有把任何“会产生多少可行解、会提高多少 EV 使用、会减少多少秒”写成保证。具体运行时长、种子数、迭代量和正式比较协议等待 P06 与本机标定，不在本轮预设。

### 0.1 当前共同施工合同

以下是所有施工件都必须遵守的共同对象；它们是验收不变量，不是新增数值门槛。

| 对象 | 施工时必须保留的含义 |
|---|---|
| 候选身份 | 每个候选保留 `DutyIndividual.fingerprint`；完整评价仍保留 `evaluation_context_sha256` 和评价来源。不得把“修复后路线”静默替换成另一候选。 |
| 服务量 | 当前选定私有实例保持完成客户数 `50/50`、完成需求量 `13264 kg`。成本或排放变化不能来自少服务客户。 |
| 物理身份 | `EV_<depot>_<i>` / `CV_<depot>_<i>`、home depot、trip index、锁定前缀和锁定充电决定由实体车账本保持，不能由抽象 vehicle id 偷换。 |
| 班次与时钟 | 每条候选路线只属于一个班次；生成、充电修复和完整评价使用同一套 S1 出发时钟。 |
| 缺口表达 | C2 的失败不再只有一个“修复失败”字符串；目标接口是最好努力候选加 `CHARGING_GAP=(missing_kWh, window_shortage_seconds)`，两项分别进入 A2 装配层。 |
| 默认开关 | 新增或改接的逐位一致相关开关默认关闭；请求值、有效值、引擎身份和元数据必须一致，不能被 `combat` 或其他配置静默改写。 |
| 受保护边界 | `cost.py`、`check.py`、`search/evaluation.py` 不改。若某个硬约束改造确实绕不开，先停在单独报批，不把它混进本施工合同。 |

### 0.2 共同候选接口（目标接口，当前尚不存在完整实现）

`DECISION`：三处候选来源——初始化、教育、交叉——都交给同一个候选合同检查。建议接口包含：候选个体、来源和动作 ID、变更实体集合、服务覆盖摘要、班次/容量/趟数摘要、充电状态、`CHARGING_GAP`、锁定项摘要、解指纹和失败原因。返回值分为：

1. `READY`：可以进入完整评价；
2. `BEST_EFFORT`：保留候选和二元缺口，进入未受保护的装配层；
3. `REJECTED`：没有可安全装配的候选，保留类型化原因和可用的原始候选快照；
4. `INTERNAL_ERROR`：接口或数据错误，不能伪装成普通不可行。

这不是新增合格线。它只是把“候选怎么来的、还缺什么、最后由谁判定”放进一个可追踪接口。最终是否可行，仍由 `DutyFullEvaluator` 和现有完整检查链判定。

## SC0｜C0 构造式初始化

### 动作

`DECISION`：把当前“随机骨架尝试—完整评价—大量候选在生成前后被拒”的路径，改成两个可追踪的构造来源，并让三处候选生产共用同一候选合同：

- **见证扰动路径**：读取已经封存的两班次完整服务见证，围绕见证的实体车、班次、客户序列和充电安排做受控扰动；不得重新手工拼一条漂亮路线，也不得把见证结果写成搜索结果。
- **时空聚类路径**：按班次窗口、客户空间关系和同一实体车可连续服务的时序构造候选，再交给统一候选合同和完整评价。聚类只是构造顺序，不是可行性证明。
- 两条路径都输出同一候选对象；教育和交叉生成的新候选也必须经过同一合同，不能各自保留一套“半成品路线”语义。
- 接通后，使用 copied HGS defaults 的 25 成员口径重新测量。该重测是施工验证，不是正式实验；要完整保留每个成员的构造失败、评价违规、教育轮数、惩罚登记/更新、终止状态和最终解。

### 文件与函数

`FACT`：当前初始化入口是 `solver/src/setp_solver/algorithms/problem_hgs/initialization.py:394-554`，其中 `build_initial_population` 在 `:455-520` 尝试构造、班次合同、车队激活、充电修复并处理拒绝，在 `:521-554` 收集并返回结果。当前文件开头 `:1-6` 已说明 kernel 只负责随机骨架，物理身份、多趟、充电和完整可行性在 Duty 层。

`FACT`：教育入口是 `solver/src/setp_solver/algorithms/problem_hgs/education.py:328-539`；候选通过 `evaluate_move`（`:76-145`）先做锁定、车队、单班次核验，再进入修复和评价。交叉入口是 `solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:389-650`。

`FACT`：见证文件由 `solver/scripts/build_instance_depot_swap_jjj_20260813.py:923-1024` 的 `main` 调用 `base.build_witness`，并在 `:1026-1050` 开始写入实例见证文件；较早的重建脚本提供 `build_witness`（`solver/scripts/build_private_instance_rebuild_20260811.py:873-945`）。

`UNKNOWN`：当前只读核对没有找到一个已经被私有 HGS runner 直接消费的“时空聚类候选生产器”，也没有证明外部见证对象可以直接转成 `DutyIndividual`。施工前需在不改代码的前提下补齐这个调用链；若不存在可复用函数，批准后才在未受保护层补一个最小适配器，不复制一套新的路线评价器。

`FACT`：copied defaults 的参数对象在 `solver/src/setp_solver/algorithms/problem_hgs/population.py:35-71`，runner 的参数入口在 `solver/scripts/run_problem_hgs_private_technical.py:458-496`；初始化及结果汇总挂点在 `:3167-3235`。这三个位置是 25 成员重测的现有接线入口。

### 接口契约（输入、输出、失败返回）

输入：实例 bundle、统一企业归属映射、班次/客户窗口、实体车注册表、copied defaults 的人口参数、随机源、见证资产和聚类排序所需的客户时空字段。

输出：统一候选结果。`READY` 返回完整 `DutyIndividual`；`BEST_EFFORT` 返回尽可能完整的 `DutyIndividual` 和缺口/违规集合；`REJECTED` 返回来源、动作、变更实体和类型化原因；`INTERNAL_ERROR` 只表示接口或数据问题。所有返回都带候选 fingerprint 或“没有可装配候选”的明确说明。

失败返回不得用“随机重试直到看起来够多”替代。构造失败、班次混合、客户重复/缺失、实体车冲突、充电缺口和完整评价违规要分开记录。

### 不变量

- 每个被接纳或被记录的候选都有解 fingerprint；完整评价仍可追到评价上下文 hash。
- 25 成员重测的每个候选都必须能核对 `50/50` 和 `13264 kg`，否则记为失败，不删行。
- 候选来源、见证扰动参数和聚类排序进入元数据；不把见证的成本当成搜索成本。
- 三处候选生产都使用同一合同；教育和交叉不得绕过 C0 的结构检查。
- 保持三个受保护文件的 hash 不变：`cost.py=525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989`，`check.py=1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`，`search/evaluation.py=c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。
- 默认关闭逐位一致相关开关；关闭状态下不引入隐藏构造分支。

### 验收动作

Claude 可复核：逐成员检查来源和候选 fingerprint；逐成员核对服务客户数、需求量、班次纯度、实体车身份、充电状态和完整违规类型；检查教育轮数、惩罚注册/更新和终止状态是否真实来自运行记录；检查见证路径与聚类路径是否都经过同一候选合同；检查 25 成员重测只使用 copied defaults 口径。这里不设置新的数值门槛，也不把重测写成正式结果。

### 回滚

保留施工前的 `initialization.py`、`education.py`、`integrated_private.py` 和相关新适配器快照。若共同合同使旧技术探针不能启动，关闭新增构造配置并恢复当前初始化调用链；不回滚 S0/S1/S2，也不回滚受保护文件。回滚后本轮只能报告“构造式初始化未接通”，不能把旧探针结果冒充新设计证据。

### 是否触及受保护文件

不触及。C0 可以在 `initialization.py`、教育/交叉装配层和新建的未受保护适配器中完成；若有人提出通过修改 `check.py` 放宽初始硬拒绝，必须单独报批，目前可绕开。

### 依赖

依赖 S1/S2 已落地的时钟和单班次合同、实体车注册表、实例见证文件、copied defaults 参数入口。最终 25 成员重测还依赖 SC1 的归属同源接线和 SC2 的开关元数据闭合；否则测到的是旧归属或隐式开关。

### 风险

见证扰动可能只复制一个局部形状，聚类可能改善构造顺序但不能保证充电和班次可行；两者都可能把“更容易生成”误读成“算法更好”。因此必须保留逐成员失败原因和完整评价，不得事后挑某一条路径或某几个成员写故事。

## SC1｜企业归属接线

### 动作

`DECISION`：建立唯一的企业归属源：`enterprise_assignment.csv` 中的 `way/...` 企业场站标识先转换成实例节点 ID，再形成 `customer_id → bundle.customer_home_depot`。路线生成、班次/归属约束、跨场站成本和利润分账都读取这一份规范化映射；不再让 `orders.csv` 的派生 `home_depot_id`、最近场站推断和利润层各自形成一份主人归属。

输入文件要保留 assignment 的来源、规则和 hash；规范化转换必须能从 `way/...` 逐项追到 `D_OSM_WAY_...` 节点。缺失、重复、未知场站或客户集合不一致时返回类型化错误，不静默退回最近场站。

### 文件与函数

`FACT`：V3 bundle loader 在 `solver/scripts/run_problem_hgs_private_technical.py:823-900` 读取节点和订单，当前 `customer_home_depot` 在 `:896-900` 直接来自订单行的 `home_depot_id`；bundle 的源文件登记在 `:1093-1116`，当前没有登记 `enterprise_assignment.csv`。

`FACT`：完整评价在 `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:511-513` 用 `bundle.customer_home_depot` 标注跨场站服务，并在 `:566-679` 的 `DutyFullEvaluator._evaluate_prepared` 中把同一映射传给利润计算。

`FACT`：利润归属入口是 `solver/src/setp_solver/profit.py:68-204`；显式归属在 `:74-90` 被接收，路线成本和跨场站服务分配在 `:97-169`，总排放/时间等分配在 `:171-203`。现有最近场站回退函数是 `:55-65`，施工后不能作为 assignment 缺失时的隐式回退。

`FACT`：候选交叉在 `solver/src/setp_solver/algorithms/problem_hgs/crossover.py:286-419` 接受 `customer_home_depot_by_id`，私有集成交叉调用在 `solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:450-456` 传入该映射；重建路线约束的数据合同在 `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:86-123`。

`UNKNOWN`：当前代码没有找到已存在的 `way/... → D_OSM_WAY_...` 通用转换函数。施工时应先复用 `nodes.csv` 和实例 provenance 的节点身份；不要新造第二套场站编号。

### 接口契约（输入、输出、失败返回）

输入：assignment CSV、节点表、实例 ID、客户全集和企业规则 ID。

输出：不可变的 `customer_home_depot` 映射、企业 ID 映射、规范化源文件路径、源 hash、规范化映射 hash。所有使用者只接收这份 bundle 字段。

失败返回：缺客户、重复客户、未知 `way`、节点转换失败、assignment 与当前实例客户集合不一致时返回 `ASSIGNMENT_CONTRACT_ERROR`；禁止返回“推断成功”的最近场站结果。

### 不变量

- `bundle.customer_home_depot`、路线约束和 `calculate_depot_profits` 的主人归属同源。
- 50 个客户的企业分配、25/25 结构和 `50/50`、`13264 kg` 服务口径保持可核对；25/25 是当前实例合同，不是新算法门槛。
- 候选 fingerprint、评价上下文 hash、assignment 源 hash 都进入元数据。
- 不能改变 protected hashes；默认关闭逐位一致开关仍保持关闭。

### 验收动作

Claude 可逐行抽查 assignment 的 `way/...`、节点表中的规范化 ID、bundle 映射、候选约束输入和利润调用；再用一条跨场站候选核对路线成本、服务收入和利润分账是否引用同一主人。检查 assignment 缺失时是否明确失败，而不是调用最近场站。

### 回滚

保留当前 loader 的原始文件和一份只读映射快照。若规范化转换失败，回滚到未接 SC1 的代码状态并停止 25 成员重测；不得用旧订单字段和新 assignment 混合运行。

### 是否触及受保护文件

不触及。所有接线可在 runner、bundle 装载和未受保护的 route/evaluation context 适配层完成。若要改 protected checker 中的主人判定，当前没有必要，须单独报批。

### 依赖

依赖实例 `enterprise_assignment.csv`、节点身份文件、V3 bundle loader 和当前利润函数；是 SC0 最终重测、SC4 公平账本和 SC5 偏置表的上游依赖。

### 风险

`way/...` 与 `D_OSM_WAY_...` 是两种身份表达，转换错一位就会把路线归属、利润和公平一起改错；最近场站回退还会让错误看起来“能运行”。因此把源 hash 和规范化 hash 一起登记，并把转换失败作为数据错误。

## SC2｜C1 两开关接线

### 动作

`DECISION`：把 C1 的两个开关——`rebuilt_volume_capacity_enabled` 与 `rebuilt_shift_neighbours_only`——从 runner 明确传到 `IndependentKernelDutyRouteProposalEngine`，并让请求值、有效值、引擎身份和元数据四者可核对。默认值保持关闭；`combat` 不得在没有明确请求时偷偷打开它们。`depot_assignment_operator` 是另一个既有开关，不与 C1 两开关混称。

每次启动都写出 requested/effective/source identity。接线核验同时检查 C1 开、关两种配置，但具体运行时长和种子数不在本轮设置。

### 文件与函数

`FACT`：runner 的 named configuration 在 `solver/scripts/run_problem_hgs_private_technical.py:2917-2923`；`combat_enabled`、机制关闭解析和有效值计算在 `:2990-3013`。当前 `combat` 会在 `:3140-3145` 把三个 route-engine 选项写成 `True`，并在 `:3152-3160` 构造引擎。

`FACT`：route engine 的开关和候选接线在 `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:45-63`、`:356-374`、`:583-641`；其中 shift 邻域当前只是缩窄邻域，不等于完整候选合同。

`FACT`：runner 元数据已在 `solver/scripts/run_problem_hgs_private_technical.py:3584-3624` 记录 proposal config、mechanism enabled、三个 combat route 选项、节点算子和 shift-aware proxy，这里是新增 C1 核验字段的现有登记位置。

### 接口契约（输入、输出、失败返回）

输入：两个布尔请求值、proposal config、机制关闭列表和当前实例。

输出：`requested → effective → engine_identity` 的不可变接线记录，以及明确的 route-engine 行为对象。关闭时两个 effective 值都为关闭；开启时只能由明确请求打开。

失败返回：请求值和有效值不一致、元数据和引擎参数不一致、默认关闭却出现开启算子时，返回 `SWITCH_WIRING_MISMATCH`，不进入搜索；不要用“combat 语义”解释掉不一致。

### 不变量

- 默认关闭状态与施工前相同，要求逐位一致；开关状态写进身份 hash/元数据。
- 候选 fingerprint、服务 `50/50`、`13264 kg`、S1/S2 合同不变。
- 三个受保护文件 hash 不变。
- 不因开关接线顺手增加迭代、时间或种子门槛。

### 验收动作

Claude 可只读核对 runner 请求值、effective 值、route-engine 构造参数和输出元数据，确认默认关闭时四处一致；再核对开启时只有明确开关改变对应行为，不影响另一个开关。验收只检查接线，不把开关开启后的结果当成性能证据。

### 回滚

删除新参数的传递并恢复当前 `proposal-config` 行为；保留元数据中已发现的不一致记录，不删除失败证据。若 `combat` 的既有行为需要保留，必须把它作为旧配置身份回滚，而不是继续让新 C1 逻辑隐式覆盖。

### 是否触及受保护文件

不触及。runner 和 `kernel_proposals.py` 都是未受保护代码；没有理由修改 `search/evaluation.py`。

### 依赖

依赖 SC0 的候选合同、SC1 的归属输入和现有 S1/S2 接线；C1 验收完成后才能解释后续短循环吞吐。

### 风险

当前 `combat` 会自动打开多个选项，且 C1 两开关与 `depot_assignment_operator` 相邻；如果只看最终元数据，很容易把配置组误读成单个开关效果。必须逐项记录，不能把“combat 开了”当成 C1 证据。

## SC3｜C2 充电缺口捕获

### 动作

`DECISION`：把当前 `ChargingRepairFailure` 的硬拒绝路径改成“最好努力解＋二元缺口”的透明候选路径。对已生成的 route/vehicle 结构，计算：

`CHARGING_GAP = (missing energy in kWh, shortage of feasible window in seconds)`。

两项分别保存，不能压成一个分数。候选仍交给未受保护的装配层，装配层把两项映射为 A2 的独立搜索惩罚/违规记录；完整可行性仍由现有 `DutyFullEvaluator` 和 protected checker 判定。若连候选对象都无法安全装配，则返回带原因的 `REJECTED`，不能伪造最好努力解。

S1 的统一时钟必须直接复用，不重新计算一套“充电时间”。

### 文件与函数

`FACT`：当前单一修复在 `solver/src/setp_solver/algorithms/problem_hgs/charging.py:530-634`，EV 修复失败在 `:625-629` 包装为 `ChargingRepairFailure`；已有候选替代生成器在 `:637-675` 开始，但当前主路径并不自动把缺口送进 A2。

`FACT`：当前错误编码在 `charging.py:75-169`，包括 `charging_rejection_reason` 和 `ChargingRepairFailure`。它是现有失败证据，不能被新接口吞掉。

`FACT`：S1 时钟入口在 `charging.py:1266-1274`、`:1907-1925`，并在 `solver/src/setp_solver/search/multitrip_schedule.py:738-763` 采用同一 `route_departure_second` 语义。

`FACT`：未受保护的候选记录骨架在 `solver/src/setp_solver/algorithms/problem_hgs/contracts.py:30-65` 的 `CandidateStatus/CandidateOutcome`，教育调用链在 `education.py:76-145`；完整装配入口是 `evaluation.py:469-528`，违规和 A2 输入在 `:566-679`。

`FACT`：`FullEvaluation` 在 `evaluation.py:244-264` 保存 `violations`、`violation_magnitudes`、breakdown 和 participation margin；当前 `_evaluate_prepared` 在 `:577-645` 计算利润、调用 protected `check_solution` 并追加未受保护的路线/车队违规。

### 接口契约（输入、输出、失败返回）

输入：参考个体、原始候选、变化的 duty 集合、S1 充电政策、bundle 时钟/价格/站点容量和锁定充电决策。

输出：候选、`CHARGING_GAP`、原因代码、受影响 duty、时钟证书和 fingerprint。没有缺口时二元组为两个零值；有缺口时保留两个独立量，并标明 `BEST_EFFORT`。随后由装配层生成 A2 可读的 violation/magnitude，不修改 protected checker。

失败返回：若缺少 route、实体车或锁定信息，返回 `REJECTED_INTERFACE`；若 route 可保留但充电不足，返回 `BEST_EFFORT`；若没有任何可安全装配的候选，返回 `REJECTED_CHARGING` 加缺口和原因。不要把窗口不足误写成能量不足，也不要只保留字符串。

### 不变量

- 同一候选的 energy gap 和 window gap 可分别复算，且使用 S1 统一时钟。
- `CHARGING_GAP` 进入 A2 前经过未受保护装配层；完整评价仍保留原始 violations、breakdown、fingerprint 和评价上下文 hash。
- 50/50、13264 kg、实体车身份和受保护 hashes 不变。
- 充电缺口不是一条新的硬阈值；`CHARGING_GAP` 为零与否由数据算出。
- 默认关闭逐位一致开关不因 C2 自动打开。

### 验收动作

Claude 可从一个已知充电修复失败快照重算二元组，核对能量项、窗口项、统一时钟、A2 装配记录和最终 `FullEvaluation`；再核对缺口候选是否仍保留服务客户和实体车信息。验收应同时覆盖可修复、最好努力和无法装配三类返回，不设新的数值门槛。

### 回滚

保留当前 `ChargingRepairFailure` 路径和现有 schedule capture。若缺口装配导致评价上下文或原始错误丢失，关闭 C2 新接口，恢复原硬拒绝并保存失败快照；不修改 protected checker 来“救”接线。

### 是否触及受保护文件

不触及。C2 可在 `charging.py`、`contracts.py`、`evaluation.py` 的未受保护装配处完成。若方案改成修改 `check.py` 的硬约束语义，须单独报批；本方案可以绕开。

### 依赖

依赖 S1 时钟统一、C0/SC1 的合法候选和 `CandidateOutcome` 记录骨架；SC4 的公平软账本应读取 C2 装配后的完整评价，而不是读修复异常字符串。

### 风险

最好努力候选可能被误当成可行解，或者 gap 的两个单位被重复计入 A2。施工时必须保留“候选状态”和“完整可行性”两个字段，并在账本中记录原始 gap，不允许用一个总惩罚倒推缺口来源。

## SC4｜C7 公平软账本

### 动作

`DECISION`：按设计书 V2 的良定义版，在每一代/每次代际评价记录公平软账本，不把公平软账本直接变成硬拒绝。对每个候选计算规则集合：等额分配、按业务量、独立成本、Shapley、nucleolus；得到 `c(N)`、`c({i})`、`x_i` 以及

`V(S,r)=Σ_i max(0, x_i-c({i}))`。

在 `min V` 大于零时保留并列规则并把 `PARTICIPATION` 作为软项；在 `min V` 为零但仍并列时使用已冻结的公平指标，若该指标尚未提供则按 V2 退回 r1，同时记录退回原因和 rule id。这里不替用户决定尚未冻结的公平指标。

主双场站算法也运行规则选择；由于规则可能退化为同一结果，主报告只展示一个规则。四场站只承担可见的规则比较实验，不承担“算法平时才选择规则”的唯一入口。

### 文件与函数

`FACT`：现有利润分解在 `solver/src/setp_solver/profit.py:29-52`、`:68-204`；现有评价在 `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:566-679` 形成 `depot_profit`、participation margin 和完整 breakdown。

`FACT`：候选结果与逐动作记录在 `solver/src/setp_solver/algorithms/problem_hgs/contracts.py:67-220`；教育会在 `education.py:380-539` 记录轮数、候选结果和接受动作。私有算法的惩罚注册挂点是 `solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:786-797`，人口的可行/不可行分离在 `solver/src/setp_solver/algorithms/problem_hgs/population.py:204-284`。

`UNKNOWN`：当前代码已有 participation margin 和动作记录，但没有逐代保存五套分配规则、`V(S,r)` 和选择原因的完整公平账本。施工需要在未受保护的 accounting/trajectory 层增加记录对象，而不是假装已有字段就是 C7 账本。

### 接口契约（输入、输出、失败返回）

输入：完整 `FullEvaluation`、企业归属映射、独立成本、规则集合、当前代际/候选身份、软阶段配置和公平指标身份。

输出：一条不可变 ledger entry，至少含候选 fingerprint、代际/迭代、全部规则计算、最小 V、并列规则、最终选择 rule id、`x_i`、`c({i})`、服务客户/需求量和软项输入。选择结果供 A2/人口排序使用，但在软阶段不直接硬淘汰。

失败返回：规则计算缺输入、企业集合不全或结果不能复算时返回 `FAIRNESS_LEDGER_ERROR`；不得退回旧的路线拥有成本账而不记录。公平指标未冻结时返回 `METRIC_OPEN_FALLBACK_R1` 并保留原因，不把 r1 写成用户已决。

### 不变量

- 每条候选/每一代账本都能回到 fingerprint、评价上下文 hash 和利润 breakdown。
- 主双场站和四场站使用同一规则选择接口；“四场站才启用选择”不是实现边界。
- 50/50、13264 kg、受保护 hashes、默认关闭开关不变。
- 软账本不改变既有硬约束语义；`PARTICIPATION` 只是记录和 A2 软项，何时转硬需等待 P28 冻结。
- 不新增公平数值门槛，不在结果出来后挑选最有利的 rule。

### 验收动作

Claude 可选一条候选逐项复算五个规则、`V(S,r)`、并列保持和选择 tie-break；检查主双场站是否执行同一选择但只报告一个退化规则；检查 ledger 与 `FullEvaluation.depot_profit`、服务量和成本 breakdown 同源；检查公平指标未冻结时的明确 fallback 记录。

### 回滚

只移除新增 ledger 写入和软项适配，保留现有利润、participation margin、惩罚和完整评价；不删账本历史文件，不把软阶段改成硬阶段。

### 是否触及受保护文件

不触及。C7 软账本放在未受保护 accounting/evaluation assembly 层即可。若将 `PARTICIPATION` 写进 protected `check.py` 的硬判定，须单独报批；本施工方案不需要。

### 依赖

依赖 SC1 的唯一企业归属、SC3 的完整/最好努力评价、现有利润分解和 P28 对参与约束的后续冻结。C7 账本应在 SC3 装配完成后接入，避免公平数字建立在漏算充电缺口的成本上。

### 风险

“规则选择”和“报告只展示一个规则”容易被混成“只算一个规则”；“软账本”和“硬可行性”也容易混淆。账本必须保存全部规则和选择过程，报告层才做主场景的压缩呈现。

## SC5｜C3 Δ_c 偏置协议落地

### 动作

`DECISION`：在搜索前从已选 synergy ranking 生成冻结的客户偏置表。对每个客户用 `direct_costs_by_customer_json` 取其企业归属成本与所有候选归属中的最小成本，定义 `Δ_c=owner_cost−min_cost`；按 `Δ_c` 降序、`customer_id` 升序固定顺序。表的来源文件 hash、生成规则、实例 ID 和表 hash 写入 runner 元数据。

偏置只影响候选提议/排序，不改利润真值、完整评价或服务量；未找到表时应明确关闭 C3，而不是用默认偏置补齐。

### 文件与函数

`FACT`：设计书指定的来源是 `solver/reports/instance_reselect_synergy_20260815/synergy_ranking.csv`，使用字段为 `direct_costs_by_customer_json`。本文件是协议来源，不是本轮新生成的正式结果。

`FACT`：结构动作现由 `solver/src/setp_solver/algorithms/problem_hgs/proposals.py:125-152` 调用 `generate_problem_moves`，底层动作入口在 `solver/src/setp_solver/algorithms/problem_hgs/operators.py:766-805`；跨场站/整趟动作在 `proposals.py:231-265`。

`FACT`：现有 hash 记录方式可参考 `solver/scripts/run_problem_hgs_private_technical.py:3591-3604` 的 mapping hash 以及 `:3672-3677` 的 `pi0` hash；最终登记位置是 runner `metadata.json`。

`UNKNOWN`：当前 proposal engine 没有发现一个已经存在的 `Δ_c` 偏置表消费者。施工需要先接在候选生成顺序层，不能把它直接乘进受保护成本。

### 接口契约（输入、输出、失败返回）

输入：来源 CSV、实例 ID、规范化企业归属、客户集合和字段解析规则。

输出：每个客户一行的 `customer_id、owner_id、owner_cost、min_cost、delta_c、rank`，加源 hash、表 hash和版本身份；提议动作带 rank 但完整评价仍读真实成本。

失败返回：CSV 缺失、JSON 解析失败、客户集合不全、owner 不在 SC1 映射或数值无法复算时返回 `DELTA_C_TABLE_ERROR`；来源 hash 变动时不能复用旧表。

### 不变量

- Δ_c 表与 SC1 归属源同源；同一客户不出现两份 owner。
- 表的排序和 hash 可确定性复算，候选 fingerprint 和完整评价成本不被改写。
- 50/50、13264 kg、protected hashes、默认关闭状态保持。
- 不因偏置强行接受候选，不设置新的 Δ_c 截断值、权重或门槛。

### 验收动作

Claude 可从来源 CSV 逐客户复算 Δ_c、排序和 hash；抽查偏置消费者只改变提议顺序/优先级，完整 `FullEvaluation` 仍读 A1/A2 真值；检查 metadata 同时记录来源和生成表 hash。

### 回滚

删去偏置表消费者，保留源表和已登记 hash；恢复未启用 C3 的提议顺序。不得修改 synergy 原始文件，不得用另一份临时表替代。

### 是否触及受保护文件

不触及。C3 是生成/提议协议，可在未受保护的 proposal 和 runner metadata 层完成。

### 依赖

依赖 SC1 的归属同源、SC0 的候选合同和现有 synergy 表；在 C0 25 成员重测前只能做表生成核验，不能把偏置后的搜索结果写成正式效果。

### 风险

Δ_c 是偏置方向，不是算法收益；若把它接进真实成本或只保留偏置成功案例，会产生双重记账和选择性报告。源 hash 变化、客户缺失和 tie-break 都要保留。

## SC6｜C4 `|d−d*|` 偏置表生成与登记

### 动作

`DECISION`：在候选提议前生成车辆/趟次的距离接近度表，使用已登记的三个 `d*` 参考值，按 `|d−d*|` 升序、车辆 ID 作为 tie-break。表只负责把候选注意力放到接近切换位置的实体车/路线；不把“接近”写成 EV 优势已发生，也不改变 A1/A2 真值。

每次生成登记 `d*` 来源 hash、实例矩阵/距离来源、生成表 hash、排序规则和偏置是否启用。

### 文件与函数

`FACT`：三个参考值在 `solver/scripts/run_mechanism_validation_v3_step_c.py:41-46` 的 `THRESHOLDS_KM`；对应参考推导中的 `EV_DAILY_FIXED_PREMIUM_CNY / saving` 在 `solver/scripts/build_private_instance_rebuild_20260811.py:1174-1176`。

`FACT`：当前实体车和路线结构在 `solver/src/setp_solver/algorithms/problem_hgs/model.py:328-428`；整车类型交换候选在 `solver/src/setp_solver/algorithms/problem_hgs/operators.py:572-620`；native asset 问题构造和当前 reload 参数在 `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:644-922`，runner 登记位置在 `solver/scripts/run_problem_hgs_private_technical.py:3607-3649`。

`UNKNOWN`：当前没有找到可直接消费 `|d−d*|` 表的提议函数。施工应新增最小偏置读取接口，并保留“参考表生成”和“候选是否被完整评价”两件事。

### 接口契约（输入、输出、失败返回）

输入：实例距离矩阵、当前实体车/趟次距离、参考 `d*` 表及其 source hash。

输出：实体车/趟次、当前 `d`、参考类别、`d*`、绝对差、稳定排序和表 hash；候选动作只读取排序，不改车辆身份和距离。

失败返回：参考类别缺失、距离来源不匹配、车辆 ID 不在当前注册表或表 hash 不能复算时返回 `DISTANCE_BIAS_TABLE_ERROR`，关闭 C4。

### 不变量

- `d*` 的来源、单位和曲线类别不变，距离只来自当前实例矩阵。
- 车辆 tie-break 稳定；不引入新的距离截断、权重或合格线。
- 候选 fingerprint、服务 `50/50`、`13264 kg`、受保护 hashes、默认关闭保持。

### 验收动作

Claude 可独立用矩阵和参考表复算每一行的绝对差、排序和 hash；抽查候选选择只读取表，不改 FullEvaluation 的成本、排放和服务量；检查 metadata 记录表版本及 source hash。

### 回滚

关闭偏置消费者，保留参考表和错误记录；恢复无 C4 偏置的候选生成。不能换一套未登记的 `d*`。

### 是否触及受保护文件

不触及。C4 可在未受保护的偏置表/提议层实现。受保护评价只负责真实成本和约束，不需要知道偏置排序。

### 依赖

依赖实例矩阵、实体车注册表、SC1/SC7 的车辆与归属身份，以及 SC5 的偏置表登记习惯。

### 风险

参考 `d*` 是机制定位工具，不是结果；若把接近切换点的候选数量多写成 EV 优势，或把偏置表改成事后挑路线，都会越过证据边界。当前三个数只作为设计输入，不是正式实验结果。

## SC7｜C5 趟数上限参数化

### 动作

`CORRECTION`（2026-08-16，SC8 步零自查 HALT 后由 Claude 查证改判，无须用户新决定）：
**本算例族不存在"每车趟数上限"这种约束，此前本卡要求接线的上限是个不存在的东西。**

`FACT`（求解器执行路径无趟数上限）：`check.py` 全文无趟数上限判定（`trip` 相关行仅涉及
车辆 ID 唯一性、充电与趟次重叠、静态趟不得含中途场）；`RebuiltRouteConstraintContract`
（`algorithms/problem_hgs/evaluation.py:86-123`）字段只有客户班次、客户体积、班次窗、车辆体积容量，
无趟数字段；`solver` 全树 `.py` 中 `max_trips_per_vehicle`／`maxTrips`／`max_num_trips`／`trip_upper`
的全部命中都在**造算例脚本的体检统计**里，无一在求解或校验路径。

`FACT`（造算例脚本自述）：`scripts/build_private_instance_rebuild_20260811.py:1477` 原文写明
"实测单车最多 3 趟，**没有人为设置两趟上限**"——3 是涌现观测值，算例方从未设过上限。

`DECISION`（改判后的本卡内容）：**趟数不设计数上限，由"班次时间窗＋充电可行"自然卡死。**
1. Split/labeling 枚举趟次的**停止条件是时间与充电可行性**（每趟的出发/返场落在所属班次窗内、
   午休回场约束成立、跨趟 SOC 连续且充电窗可行），用标签法的时间支配剪枝实现；
   **任何情况下不得引入计数上限**（不得用 3、不得用客户数、不得自拟一个数）。
2. 超时/超电的候选按既有类型化缺口返回（时间窗类、充电窗类），走原有不可行池；
   `TRIP_COUNT_LIMIT` 这一缺口类型**作废**——本算例族没有它的所指，不再要求实现。
3. `kernel_proposals.py:859` 的 `max_reloads = max(0, len(customers)-1)` 占位值**保留不动**：
   它是**非绑定**的（49 远大于时间可行域，先被时间窗卡死），改它属于无收益改动。
   本卡由"接线一个上限"降级为"确认没有上限、并确认时间可行性是真正的约束"。
4. **须区分两种上限，别混**：**每车趟数上限＝不存在**；**每场车队规模上限＝存在且是真权威**
   （`fleet_caps_by_depot`），槽位表必须遵守，不得凭空造车。

### 文件与函数

`FACT`：当前 kernel 在 `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:857-912` 构造 vehicle type，`:859` 仍用 `max(0, len(customers)-1)` 形成 `max_reloads`，`:891-912` 把它写入 native vehicle type。这是占位接线，不是已批准的科学上限。

`FACT`：实体车、连续 trip index 和充电会在 `solver/src/setp_solver/algorithms/problem_hgs/model.py:328-428` 校验；完整评价追加车队违规在 `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:639-645`。

`FACT`：runner 已在 `solver/scripts/run_problem_hgs_private_technical.py:3597-3604` 记录参考/最终最大趟数，在 `:3625-3645` 记录 native reload contract；这些是登记挂点，不代表当前上限正确。

### 接口契约（输入、输出、失败返回）

（本节按上述 `CORRECTION` 改写）

输入：实体车注册表（实体 ID／车型／home depot／可用班次）、班次窗与午休合同、充电合同、
每场车队规模上限 `fleet_caps_by_depot`、路线分割参数和候选。**输入中没有"趟数上限"这一项。**

输出：候选实际趟数**如实报告**（含逐实体车趟数分布），不与任何上限比对；
可行性由时间窗与充电窗判定，最终由完整评价裁决。

失败返回：时间窗类、充电窗类缺口按既有类型返回，进不可行池并保留 fingerprint 与实体车；
不得悄悄截断趟次、重编号或把额外趟次塞进另一辆抽象车。`TRIP_COUNT_LIMIT` 已作废，不再返回。

### 不变量

- 不把“当前观察到最多 3 趟”升级成用户决定或正式参数（本条不变，且现在更强：任何计数上限都不许引入）。
- 时间与充电可行性贯穿路线生成、分割、实体车装配和完整评价；不得在任一层塞入计数上限代替可行性判断。
- 若解码器产出的逐车趟数分布明显偏离见证解（如出现 5–6 趟的碎趟），**如实报告为发现**，不得据此加限。
- 50/50、13264 kg、fingerprint、protected hashes、默认关闭开关保持。
- 不新增数值门槛；本卡只参数化已有语义。

### 验收动作

Claude 可读取 authority、检查 hash、构造含不同趟数的候选并核对 native/分割/实体车三层的同一返回类型；检查 runner 元数据写出来源和实际值。验收不设新的上限数。

### 回滚

恢复当前 native adapter 的代码路径但同时关闭 C5 参数化，并把该状态标成未接通；不把占位 `max_reloads` 当作正式结果。保留超限候选及错误记录。

### 是否触及受保护文件

不触及。上限可在 kernel adapter、route contract、model assembly 和 metadata 接通。若有人要求在 protected checker 中新增硬上限，须单独报批；本方案不需要。

### 依赖

依赖实例 authority、fleet registry、SC0 候选合同、SC7 前的实体身份以及 SC8 混合解码的 trip-cut owner。

### 风险

最危险的是把观察值、native reload 占位值和实例合同混为一谈；另一个风险是只在某一层限制而其它层继续接受多趟。施工验收必须按同一候选逐层核对。

## SC8｜C6 混合解码器＋路线层交叉（第二段）

### 动作

`USER DECISION`：P67-3 已确定混合造法，并坚持“一个决定一个负责人”。因此第二段施工只允许按以下责任分工落地：

| 决定 | 唯一负责人 |
|---|---|
| 客户相对顺序、跨路线的路线层交叉 | route-layer crossover；只处理客户顺序和路线片段，不负责趟次切分或实体车重排。 |
| 一条路线如何切成班次/趟次 | Split/labeling；只负责 trip cut，不复制改变客户后的旧 separator。 |
| 物理车辆、车场、车辆类型和 trip index | canonical physical-vehicle slot table / fleet registry。 |
| 充电、SOC、共享充电时序 | C2 充电缺口装配和修复层。 |
| 最终结构、班次、容量、车队和完整成本 | `PhysicalVehicleDuty` 加 `DutyFullEvaluator`/完整检查链。 |

路线客户发生变化后，必须重新切趟、重新分配物理槽位、重新形成充电/SOC 候选，再做完整评价；禁止把抽象 vehicle id 当作 `EV_`/`CV_` 实体车，禁止直接复制旧 separator。

### 文件与函数

`FACT`：现有 DCREX 路线层入口是 `solver/src/setp_solver/algorithms/problem_hgs/crossover.py:65-168`，路线基因在 `:171-186`；现有 trip assignment 候选入口是 `:286-419`，构造候选在 `:422-475`，当前做法会追加 donor trip 并清理重复客户，尚未覆盖完整混合责任合同。

`FACT`：私有集成交叉施工挂点是 `solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:389-650`；当前候选在 `:513-532` 做单班次/车队核验并在 `:526-580` 做充电修复，随后在 `:593-650` 完整评价和记录结果。

`FACT`：实体车职责在 `solver/src/setp_solver/algorithms/problem_hgs/model.py:328-428`；车队槽位注册和激活在 `solver/src/setp_solver/algorithms/problem_hgs/fleet_registry.py:12-108`；C2 修复挂点在 `charging.py:530-634`。

### 接口契约（输入、输出、失败返回）

输入：两个父代 `DutyIndividual`、同一 canonical fleet registry、客户归属/班次/坐标、route-layer 交叉选择、trip-cut 参数、物理槽位表、C2 充电上下文和完整评价上下文。

输出：一组带来源和 owner 的混合候选；每个候选明确记录客户顺序、trip cuts、物理槽位、充电状态、unserved 客户和 `CHARGING_GAP`，再返回 `READY/BEST_EFFORT/REJECTED`。最终选择只看完整评价和现有接受逻辑。

失败返回：父代 canonical registry 不同、锁定项冲突、客户重复/缺失、趟数超合同、无法分配实体槽位或充电无法装配时分别返回类型化原因；不得把旧 separator 或旧充电安排作为静默 fallback。

### 不变量

- 一个决定只有一个负责人，负责人之间通过显式数据接口传递，不互相覆盖。
- 客户顺序变化后 trip cuts、physical slot、charging/SOC 都重新生成。
- `DutyIndividual.fingerprint`、50/50、13264 kg、S1/S2 合同和 protected hashes 保持。
- 默认关闭逐位一致开关不因第二段自动打开；没有用户批准不进入第二段施工或正式运行。

### 验收动作

Claude 可对一个父代对逐候选画出五步责任链：顺序→切趟→实体槽位→充电/SOC→完整评价；检查每一步只有一个写入者；检查没有复制旧 separator、没有抽象车冒充 EV/CV；检查失败候选仍有 fingerprint/原因/缺口记录。验收只查接线和责任，不设新数值门槛。

### 回滚

第二段单独放在隔离分支/配置中。若混合候选的责任链不能保持，关闭 C6 第二段，回到现有 `trip_assignment_exchange_candidates` 和完整评价路径；保留失败候选快照和责任链错误，不回滚 C0、C1 或 S1/S2。

### 是否触及受保护文件

不触及。路线交叉、分割、槽位、充电装配和完整评价接线都可在未受保护层完成。若要改 protected checker 以容纳旧 separator 或抽象车语义，须单独报批；本方案明确绕开。

### 依赖

依赖 SC0 共同候选合同、SC1 归属、SC2 开关、SC3 C2、SC5/SC6 偏置表和 SC7 趟数合同。设计完成不等于已授权施工；第二段仍受用户批准门控制。

### 风险

混合解码器最容易出现“顺序已经换了，但旧切分、旧车辆或旧充电还在”的伪可行候选。另一个风险是 route-layer 交叉的改善被误记为完整算法改善。所有责任链字段必须落到候选记录中。

## SC9｜C9 公开侧瓶颈定位记录格式

### 动作

`DECISION`：先落记录格式，不先改公开侧搜索。每个实例族/实验臂保存一行可复核的瓶颈记录，并把“候选生产、交叉、插入、局部搜索、完整评价、写出”分开。记录同预算的 before/after，记录瓶颈位置和拒绝分布；若要进入正式臂，记录“是否纳入”的决定来源，不把未跑的内容写成结果。

### 文件与函数

`FACT`：公开侧主循环在 `solver/src/setp_solver/algorithms/problem_hgs/public.py:281-475`，每轮已有交叉动作、局部搜索前后成本、奖励、耗时、工作量和终止状态字段（`:438-466`）。

`FACT`：公开侧候选评分入口在 `solver/src/setp_solver/algorithms/problem_hgs/public.py:1064-1201`；集成公开 HGS 入口在 `solver/src/setp_solver/algorithms/problem_hgs/public_search.py:310-517`；技术 runner 的输出包入口在 `solver/scripts/run_problem_hgs_public_technical.py:157-296`。

`UNKNOWN`：当前已有 trajectory 和 technical runner 字段，但没有针对“公开侧瓶颈定位”的统一一行格式，也没有证明所有 rejection cause 都能从当前公开侧字段直接还原。施工只先补记录适配，不顺手改搜索逻辑。

### 接口契约（输入、输出、失败返回）

输入：实例族、实验臂身份、代码/参数/评价器 hash、种子和预算身份、公开侧 trajectory、候选/拒绝计数、服务客户/需求量和终止状态。

输出：`public_bottleneck_record`，至少包含：实例/臂/版本/种子、同预算 before/after 摘要、候选生产与交叉/插入/局部搜索/完整评价的调用和拒绝分布、主要瓶颈位置、墙钟分解、服务量、是否正式臂、证据文件路径和 hash。每个数都带口径，不用“快/慢”“高/低”替代。

失败返回：缺 trajectory、预算身份、服务量或 hash 时返回 `RECORD_INCOMPLETE`；进程退出/超时/异常终止分别记录，不能只等待成功文件。

### 不变量

- before/after 使用同一评价器、同一输入、同一预算口径；不跨机器比较绝对数字。
- 同时记录完成客户数和完成需求量；不能用少服务解释成本下降。
- 记录 solution fingerprint、代码/参数 hash 和受保护 hashes；默认开关状态明确。
- 记录格式不创造新的性能门槛，不把技术探针升级成正式结果。

### 验收动作

Claude 可从一条公开侧 trajectory 重建记录，核对调用数、拒绝原因、耗时字段、before/after 成本和服务量；检查异常终态、缺字段和未完成批次是否被标记；检查同预算和同评价器声明存在。验收不设置新的秒数、接受率或提升率阈值。

### 回滚

删除新增记录适配器，保留公开搜索原 trajectory 和已写出的原始文件；若格式解析不全，返回 `RECORD_INCOMPLETE`，不修改公开搜索去迎合记录格式。

### 是否触及受保护文件

不触及。C9 只读现有公开侧 trajectory 和 runner 输出；protected evaluator 只作为版本 hash 记录。

### 依赖

依赖现有公开侧 trajectory、统一实验身份和后续 C0/SC3 的候选失败分类方式；可与私有施工并行设计，但不能拿公开侧记录代替私有候选证据。

### 风险

“瓶颈”是记录字段，不是事后给算法贴标签。若同一预算或评价器不一致，before/after 没有可比性；若只记录成功候选，公开侧的真实瓶颈会被隐藏。

## A. 施工总顺序与闸门

`DECISION`：施工按以下顺序推进；这是代理根据 V3、Round 3 和 S1/S2 diff 整理出的执行方案，不是用户已经批准的施工授权。

1. **不变量先行**：先接 SC1 归属同源、SC2 开关逐项核验和共同候选合同的静态检查；确认不碰 protected hashes、服务量字段和默认关闭语义。
2. **C0 构造落地**：接 SC0 的见证扰动与时空聚类两条路径、共同候选合同，然后按 copied defaults 25 成员口径做重测，完整保存失败和终止证据。
3. **秒级吞吐观察**：只在候选身份、服务量和评价器一致后，测量构造、装配、完整评价、充电修复和记录各自耗时；不先预设某个秒数合格线。
4. **短循环计数**：记录实际教育轮数、候选数、完整评价数、接受数、充电缺口类型和人口登记；短循环是诊断，不是正式结论。
5. **方向与第二段**：在前述证据完整后，接 SC3、SC4、SC5、SC6、SC7；C6 混合解码器是第二段，施工仍需用户批准。
6. **配对确认**：最后才做相同输入、评价器、预算和参数身份下的配对确认；C9 先记录公开侧瓶颈，不用公开结果救私有结果。

时长、种子数、迭代预算、评价预算和正式实验重复协议全部等待 P06 与本算法/本算例/本机器的标定；本文件没有预设任何新数值门槛。

## B. 测量依赖声明

以下判断必须等 SC0 实际落地并完成 copied defaults 25 成员重测后才能下：

- 初始化瓶颈究竟来自构造失败、班次/容量合同、充电缺口、实体车装配还是评价器接线；当前只能说候选生产弱，不能提前归因。
- 教育“不动”和交叉“不动”是否源于初始多样性不足；没有 25 成员的候选来源、fingerprint、教育轮数和拒绝分类，不能下算法方向判断。
- C2 最好努力候选是否真正进入 A2、两个 gap 分量是否可复算；当前 `ChargingRepairFailure` 只能证明旧路径硬拒绝，不能证明新装配已经有效。
- EV 不出现是场景不给机会、候选合同缺失、充电修复失败、车辆槽位/趟数限制还是算法选择问题；必须等 C0 产生可追踪候选后拆分四类原因。
- C7 公平软账本是否改变候选排序、是否与利润/服务量同源；没有 SC1 和 SC3 的上游一致性，公平数字不可靠。
- C5/C6 偏置是否只改变提议顺序而没有改真值成本；必须有表 hash、候选 fingerprint 和完整评价的配对证据。
- P47 私有吞吐是否达到可继续标定的状态；先看真实候选/评价耗时，再决定是否值得投入长任务。

`UNKNOWN`：本轮不对上述问题给方向性答案。25 成员重测是施工后的第一批诊断，不是正式实验，也不能替代 P06 标定。

## C. 用户假想对照的承载关系

| 用户假想 | 主要承载施工件 | 说明 |
|---|---|---|
| 分钱上层联立 | SC1、SC4 | SC1 统一企业归属；SC4 记录规则集合、`V(S,r)`、软参与项和逐代账本。四场站只承担可见规则比较，不是唯一算法入口。 |
| 油电优势切换 | SC6、SC8、SC3 | SC6 用 `|d−d*|` 定位切换附近候选；SC8 负责实体车/路线结构；SC3 负责充电可行性和缺口。最终优势仍由完整评价给出。 |
| F1 调校 | SC0、SC2、SC5、SC6、SC9 | SC0 提供可用候选，SC2 控制开关身份，SC5/SC6 只做有来源的提议偏置，SC9 记录公开侧瓶颈。它们不能把调参数字伪装成科学结论。 |
| P32 复合移动 | SC8，辅以 SC3、SC7 | SC8 分配“顺序→切趟→槽位→充电→完整评价”的责任；SC3 和 SC7 分别处理充电缺口和趟数合同。 |
| 一本钱账 | SC1、SC3、SC4 | SC1 保证 owner 同源，SC3 把充电缺口纳入 A2 装配，SC4 读取完整利润分解做软公平账本；不能把不同来源的成本拼成一个数字。 |
| 三尺度 | SC5、SC6、SC9 | SC5 是客户归属偏置，SC6 是车辆/距离切换尺度，SC9 是公开侧运行/瓶颈尺度。三者是记录和构造层，不是三个新目标。 |
| 三充电臂 | SC3 | C2 的最好努力候选、能量缺口和窗口缺口应能支撑三种充电策略/臂的统一比较；具体臂定义和正式重复协议仍以已批准实验合同为准。 |
| 多曲线收敛图 | SC0、SC3、SC4、SC9 | SC0 提供候选来源，SC3 提供充电缺口/可行性轨迹，SC4 提供公平软项和账本，SC9 提供运行轨迹/瓶颈字段。图只能使用已保存的可复核轨迹，不能另跑一条更好看的种子。 |

`FACT`：上述八项都已有对应施工承载件，没有另开一个“总控模块”来重复计算。`UNKNOWN`：三充电臂的确切正式臂定义、多曲线图最终曲线集合和 P32 是否进入正式实验，当前材料没有给出本轮可执行的唯一答案；本文件只说明接线位置，未替用户拍板。

## D. 对设计书 V3 的异议清单

### D.1 C7 的“两场站只报一个、四场站才启用选择”需要按 P67-4 改写

`FACT`：V3 的 C7 表述把四场站写成启用完整规则枚举/选择的场景；但 `pending_decisions.md` 的 P67-4 明确要求分配规则选择是算法的正常行为，双场站规则可能退化为同一结果，四场站只是规则差异可见的特别实验。

`INFERENCE`：如果按 V3 原句只在四场站启用规则选择，主双场站就无法证明算法平时确实具有上层联立行为；报告只展示一个规则不能等于算法只计算一个规则。

`DECISION`：本施工书按 P67-4 执行：同一 C7 选择接口在主双场站和四场站都运行，主双场站因退化只呈现一个结果，四场站另做规则比较。这个异议不阻塞施工书，但需要设计书 V3 正文与施工实现保持一致。

### D.2 V3 对 C0“现成见证/构造件可直接接入”的程度说得过满

`FACT`：当前确实存在 EDF 见证生成和输出路径，但本轮只读核对没有找到私有 HGS runner 已经直接消费见证对象、也没有找到完整时空聚类候选生产器的现成 runtime 接口。

`INFERENCE`：如果把“有见证文件”直接写成“C0 已有可插拔构造器”，施工时很可能另造转换器或绕过统一候选合同，反而重演旧的候选断裂。

`DECISION`：C0 施工前把见证文件、转换适配器和时空聚类生产器分成三个可核对接口；能复用就复用，找不到消费者就标 `UNKNOWN`，批准后只补最小未受保护适配层。不影响 V3 的两条构造路线设计，但收紧“现成可直接接入”的实现表述。

### D.3 C2 的“最好努力解”不能被写成已经能穿过当前评价入口

`FACT`：当前充电修复失败在 `charging.py:625-629` 仍包装为 `ChargingRepairFailure`，教育/交叉会在 `integrated_private.py:526-580` 等位置捕获并拒绝；当前 `FullEvaluation` 的完整入口是 `evaluation.py:566-679`。

`INFERENCE`：V3 的目标方向正确，但如果不把最好努力候选放入未受保护装配层，C2 仍只是“把错误名字改成 gap”，不会形成 A2 可用证据。

`DECISION`：施工卡把 C2 明确写成候选返回、gap 双元组、未受保护装配和完整评价四步；这是一项实现细化，不是对 V3 研究目标的重开。

## F. 预工课一后的增补（2026-08-16，Claude 修订；证据 `solver/reports/prework_speed_c0_20260816/`）

**F.1 速度施工件（新增三件；剖析推翻旧直觉——新算例第一大耗时是提案生成 74.044%，充电修复 19.493%）**

| 件 | 动作 | 依据 | 状态（2026-08-16 施工后） |
|---|---|---|---|
| **SC-V1 提案生成提速** | ~~压缩 Python 候选流~~ | ~~剖析表：提案生成 74.044%~~ | **`CORRECTION` 后关闭原形态**（`scv12_speedup_20260816/`）：低开销逐 `next()` 计时下 74% 归因**不复现**——copied-defaults 口径提案流仅约 18.7 秒/31,569 项；缓存探针 0 命中/10 未命中，无重复输入可复用；试探代码已全部撤除，不留假优化。**剩余提速杠杆改记为"evaluate_move 链内"**（总 114.6 秒，其中充电修复 48.8 秒已被 SC-V2 部分缓存），待收敛形状探针证明标定不可行时再立新件 |
| **SC-V2 充电修复结果复用** | ✅ **已落地过闸**：缓存作用域扩至整个 integrated search context（交叉+教育共用），键含完整 context/policy 身份（`charging.py:491-546`） | 1681 命中/2149 未命中 | **终解指纹逐位不变、逐通道计数全同**；142.78→**124.17 秒/循环（−13.03%）**；回归 199 全过 |
| **SC-V3 停止收尾诊断** | 420 秒 stop 后 142.91 秒收尾未拆清 | 剖析 `timings.json` | 未动，排队（与任意件并行诊断） |

施工顺序修订：SC0 → SC2 → **SC-V1/V2（提速，标定可行性的前提）** → SC1 → SC3 → …（其余不变）；
SC-V3 可与任意件并行诊断。

**F.2 SC0 落点修订（按勘察实情）**：
"见证→DutyIndividual"的**内联转换已存在**于 `run_problem_hgs_private_technical.py:1669-1728`
（读见证 CSV→Route/Solution→`DutyIndividual.from_solution`），SC0 第一步＝把它抽成可复用可测试的
适配器（落点 `initialization.py` 或同层新建 `c0_witness_adapter.py`），并显式接充电/SOC 补全
（见证 CSV **无充电字段**，字段清单见勘察报告 B.1）；时空聚类生产器**仓库确认没有**，
须按王勇 2023 步骤新写。两路径各自逐候选记 READY/REJECTED/合同类型/指纹，不许用偶发成功者代表路径。

**F.3 动态天花板依赖（主实验③）**：动态需求的效应天花板**只能在订单流于统一算例重建后计算**
——列入测量依赖声明；流重建仍属第二座桥，但天花板计算在流建成后立即做、先于任何动态实验。

## E. 本轮停止点与现场核对

`FACT`：本轮只写本文件和唯一完成信号 `solver/reports/build_spec_task_20260816/done.json`；没有运行求解器，没有修改 protected 三文件，也没有新增正式实验包。

`FACT`：任务开始与本轮结束应保持以下 protected hashes：

```text
solver/src/setp_solver/cost.py                         525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989
solver/src/setp_solver/check.py                        1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072
solver/src/setp_solver/search/evaluation.py             c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3
```

`FACT`：当前工作区在本任务开始前已经有 S0/S1/S2 代码和多份设计文档的既有修改；本轮不回滚、不覆盖、不整理这些用户已有改动。交付核对只允许再出现本文件和 `done.json` 两个本任务产物。

`UNKNOWN`：本文件是草案，用户尚未批准施工；因此不能把任何 SC0–SC9 写成“已完成”，也不能把 25 成员重测、短循环或配对确认写成正式数字。
