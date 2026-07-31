# E6 参与约束：事前/事中做法的文献取证 + 代码接入点勘察

日期：2026-07-31
任务性质：只读文献取证 + 只读代码勘察。未运行实验、未改任何代码或封存产物。
执行说明：Codex CLI 配额耗尽至 2026-08-05 13:39，用户已就本任务单独授权终端 Claude 直接执行读文献/读代码/写报告；不涉及改代码，纪律照旧。

本任务不重复 `docs/handoff/allocation_mechanism_survey_20260731/report.md` 已做完的 14 篇文献分配方法普查，该报告的结论直接引用，不重查。本任务只回答用户这次真正问的问题：文献是怎么"论证"事后分配合理、或事前/事中保参与更合理的——原话是怎么写的。

---

## 第一块：Soriano et al. 2023 的原文论证

来源：Soriano, Gansterer, Hartl, "The multi-depot vehicle routing problem with profit fairness," *International Journal of Production Economics*, 255 (2023) 108669。本地全文：`/Users/zhouleixishu/Zotero/storage/PLSR8GG4/`。逐页读取（pdftotext 分页），以下页码为 PDF 物理页，与期刊排版页码一致（第 1 页起算）。

### 1.1 为什么不做事后分配——原文论证链条

论文摘要就把立场摆出来了（第 1 页）：

> "In practice, a posteriori gain sharing mechanisms rarely guarantee that all partners feel treated fairly."

中译（FACT，逐句翻译）：**"实践中，事后收益分配机制很少能保证所有合作方都感到被公平对待。"**

引言部分给出三层理由，每层都有对应原句：

**理由一：协商和签约成本高。**
> "setting up such schemes might be a hard job and need a fair amount of extra work for negotiation and contracting" （第 1 页，21 词）

中译："建立这类机制可能是一项艰巨的工作，需要相当多额外的谈判和签约工作。"

**理由二：分完之后不平感仍可能残留。**
> "after gains have been reallocated, the unfairness perception might still remain" （第 1 页，11 词）

中译："即使收益已经重新分配完毕，不公平的感受仍可能残留。"论文举的具体场景：有的合作方承担更多工作量，另一些合作方却以更低工作量保住利润——分配公式能补齐账面利润，但补不齐"谁干活多"这件事。

**理由三：反垄断监管环境下操作困难。**
> "such mechanisms might be difficult to implement in areas with strong antitrust-regulations" （第 1 页，13 词）

中译："在反垄断监管严格的地区，这类机制可能难以落地。"

引言还引用 Cruijssen et al. (2007) 的调研结论作为外部证据（第 1 页）：
> "two of the biggest impediments to cooperation are the insurmountable need for a fair allocation of benefits, and the difficulties in finding an appropriate mechanism to reallocate these benefits"

中译："合作的两大最大障碍是：对公平分配收益近乎刚性的需求，以及找到合适的收益再分配机制的困难。" 该调研还发现，合作方即便有经济收益，仍可能因觉得被不公对待而退出合作。

**第 2 页给出最直接的方法论表态**，也是这篇论文和 Frisk et al. (2010,即前面第一份普查报告已确认的事后分摊代表作) 的分野声明：

> "we do not present an alternative approach to traditional cost or profit sharing (e.g., Frisk et al., 2010)"（13 词）
> "we examine if solutions not requiring a posteriori cost sharing do exist"（13 词）

中译："我们提出的不是传统成本/利润分摊（如 Frisk et al., 2010）的替代方案；我们要考察的是：是否存在根本不需要事后成本分摊的解。"

这句话把 Soriano 和事后分摊文献（包括目标期刊的 Rao 2022/2019）明确分成两条不同的路，不是同一方法的两种实现，是两种不同的问题定义。

第 2 页的 Fig. 1 例子（两方合作，客户服务收益均为 50）把论证具体化：成本最优解可能让一方零客户零利润，"one partner is left with no customers and hence with no profits, refusing to accept such solution"（第 2 页，17 词，中译："一方最终没有客户、因而没有利润，拒绝接受这样的解"）；靠事后转移支付能把该方补到 70 单位利润，但论文指出这会被另一方视为不公平（"which will probably be considered unfair by the other partner, even if his profit increases by 21 units"）；只有在搜索阶段就让双方分摊工作量的"fairer solution"才更可能被双方接受，"in either presence or absence of transfer payments"（有没有转移支付都一样）。

**结论（FACT）**：Soriano 没有说事后分配"数学上不可行"，论文的立场是事后分配即使技术上可行也常常解决不了合作稳定性问题——协商成本、残留不公平感、监管障碍三层，加上"分钱不等于分工作量"这一具体机制性缺陷。这是这篇论文选择"把公平做进优化"而不是"先优化再分钱"的原始动机陈述。

### 1.2 公平度量和参与约束的确切数学形式

第 4 页，问题定义 (Section 3)。设 $\mathcal{D}$ 为车场集合，每个车场 $d$ 的利润：

$$P_d = \sum_{(i,j)\in\mathcal A}\sum_{h\in\mathcal H}\sum_{k\in\mathcal K_{dh}} (r_i - c_{ij})x^k_{ij} \qquad (9)$$

公平比率定义为 $\hat p_d = P_d / P_{d0}$，其中 $P_{d0}$ 是该车场的单干（stand-alone）利润，**是优化前给定的输入参数**（原文："in the optimization problem, the latter is a given input parameter (i.e., $P_{d0}$ is calculated a priori)"，第 4 页）。

公平目标函数（第 4 页，公式 2）：

$$\max_{\mathcal D} \left(\min_{d\in\mathcal D}\{P_d/P_{d0}\}\right)$$

通过 $\epsilon$-约束法把它变成约束（第 4 页，公式 11）：

$$P_d \ge \hat P \cdot P_{d0}, \quad \forall d\in\mathcal D$$

这条约束**没有转移支付变量**，也不涉及 Shapley/核/MCRS 中的任何联盟值计算；它只要求每个车场自己的账面利润达到自身单干利润的 $\hat P$ 倍。

### 1.3 约束在算法哪几个环节生效

Soriano 用 ALNS（自适应大邻域搜索），第 4-6 页有完整算法细节：

- **初始解构造**：用 Solomon (1987) 的 I1 构造启发式从零建一个初始解 $S=S^0$（第 5 页），这一步**不含公平逻辑**，公平只在后续迭代中起作用。
- **重构（reconstruction）**：这是公平真正"软性介入"搜索的地方。插入分数公式（第 6 页，公式 15）为
  $$\lambda^m_{ikd} = C_{ik}\cdot f_d$$
  其中 $f_d$ 是公平分数修正因子（公式 16）：
  $$f_d = \begin{cases}1 - \dfrac{\hat P\cdot P_{d0} - P_d}{r(R)} & \text{if } P_d < \hat P\cdot P_{d0}\\ 1 & \text{otherwise}\end{cases}$$
  含义：车场利润没达标时，插入到该车场的客户会得到更低（更优先）的插入分数——即算法主动把客户"喂"给还没达标的车场，但这只是加权引导，**不是硬约束**。
- **局部搜索**：这里是硬约束生效点。原文明确写（第 6 页）："Only moves that satisfy all constraints, including the fairness constraint (11), are allowed."（只有满足所有约束，包括公平约束 (11) 的移动才被允许，13 词）。中译同上。
- **接受准则**：Algorithm 1（第 5 页）里，一个候选解要成为 $S^{Best}$ 或被接受为新的 $S$，前提是它是可行解（"if $S'$ is feasible and $\Phi(S')<\Phi(S^{Best})$"），而"可行"就包含约束 (11)——因为公式 (11) 是整数规划 M1 里的一条硬约束（第 4 页，Eqs.1-10），不是 (11) 就直接判定该完整解不可行。

**结论（FACT）**：公平约束贯穿构造之后的全过程——重构阶段是软性引导（提高对未达标车场插入的偏好），局部搜索和整体接受判断是硬性过滤（不满足约束 (11) 的解直接不可行）。用户问的"事中就预判好"，Soriano 这篇论文对应的正是这种"软引导+硬过滤"的双层机制，不是简单的"过滤掉不好的解"。

### 1.4 阈值 P̂ 怎么定的，怎么辩护

**关键事实（FACT）**：$\hat P$ 不是拍一个固定值，而是通过 $\epsilon$-约束扫描法系统性地**扫出整条帕累托前沿**（第 4-5 页）：

1. 先求公平不受限的解 $S^-$（普通 MDVRP，成本最低），得到当前最弱车场的比率 $\mu = \min_d\{P_d/P_{d0}\}$；
2. 设 $\hat P = \mu + \epsilon$，重新求解，得到新解，更新 $\mu$ 为该解的最弱比率；
3. 重复直到无可行解为止（此时达到 $S^+$，最大可行公平水平）。

论文用 $\epsilon = 0.005$（第 7 页），"a small value allows us to explore almost all possible solutions along the Pareto front"（一个小的取值让我们能探索帕累托前沿上几乎所有可能的解，第 7 页）。

**Soriano 对阈值取法的辩护不是"选一个数然后论证它合理"，而是"不选——把所有能达到的公平水平都算出来，交给决策者挑"**。原文第 5 页明确这一立场："The ultimate goal of the MDVRP-PF is to provide the decision maker with a set of choices from which to choose the one satisfying coalition requirements the most."（MDVRP-PF 的最终目标是给决策者提供一组选择，供其挑出最符合联盟要求的那个，第 2 页也有近似表述）。

这与本项目当前 E6 的"单一 θ=1.0 判据"在方法论姿态上不同：Soriano 报告的是整条权衡曲线，不预设唯一正确阈值。

### 1.5 报告的成本—公平权衡量级

**Table 4（第 9 页）**——限制车队规模后的成本变化，四种数据类型的平均值：

| 数据类型 | VL-P̂（限车队后的公平比率均值） | ĉ（相对同公平水平的常规 MDVRP-PF 的成本增量） |
|---|---:|---:|
| C_B（聚集客户，均衡收入） | 1.267 | 3.79% |
| C_U（聚集客户，不均衡收入） | 1.084 | 4.82% |
| U_B（均匀客户，均衡收入） | 1.137 | 0.34% |
| U_U（均匀客户，不均衡收入） | 1.102 | 1.26% |

这张表回答的是"限制车辆数（简单公平手段）比专门公平优化贵多少"，不是整体公平代价上限。

**全文结论段（第 11 页）给出总体量级**（FACT）：

> "increases in total costs for each 1% increment of fairness requirements stay generally below 1%, increasing up to 4.44% in the case of clustered-balanced instances"（19 词，中译："公平要求每提高 1%，总成本的增量通常低于 1%，聚集-均衡类实例最高达到 4.44%"）

> "some instances exhibit a profit increase of over 30% for all partners"（13 词，中译："部分实例中，即便要求最大公平，所有合作方的利润仍能提高超过 30%"）——这是指 $S^+$（公平最大化解）相对单干基准的利润增幅，不是成本代价。

摘要里的总口径："the economic cost of fairness remains below 5%"（第 1 页）。

### 1.6 事后转移支付这条路，讨论了没有、怎么处理的

**FACT**：讨论了，在第 2 页正面处理，态度是"承认事后分配是既有主流做法，但本文选择研究另一条路，不否定事后分配本身"。原文原话已在 1.1 节引用（"we do not present an alternative approach to traditional cost or profit sharing (e.g., Frisk et al., 2010)"）。论文也承认公平解可以作为事后分配机制的**起点**而非替代（第 2 页）："Fairer solutions can still be the starting point for a gain sharing mechanism: mistrust barriers to profit redistribution become smaller with an increase of fairness perception among coalition partners."（更公平的解仍可以作为收益分配机制的起点：随着联盟成员公平感知的提升，利润再分配的互信壁垒会变小）。

**结论（INFERENCE）**：Soriano 没有把"事中保参与"和"事后转移支付"设成互斥选项，而是设成互补关系——先用公平约束把方案做得不那么需要转移支付，如果还需要转移支付，公平的方案更容易谈成。这和用户"事后分配感觉不太现实"的直觉部分吻合（转移支付需要谈判、监管、互信），但论文本身并未断言事后分配"不现实"，只是给出了另一条路并系统性比较其代价。

---

## 第二块：有没有"事前预判 / 事前约定"这一类做法

用户的分类 (a)(b)(c) 逐条核对：

### (a) 优化过程中实时保证每个成员不吃亏

**已有先例，就是 Soriano 2023（见第一块）**。不重复列。

### (b) 优化之前先公布分配规则、各方承诺，优化只需满足该规则

**FACT，找到两篇本地全文，均非 VRP/物流场景，属供应链契约设计文献**：

**Ahn, Çetinkaya, Duenyas, Zhang, "Benefits of Collaboration on Capacity Investment and Allocation," *Production and Operations Management*, 2024, 33(1):128–145。** 本地全文：`/Users/zhouleixishu/Zotero/storage/ETUZRJK4/`。

模型是两阶段：第一阶段（需求不确定性尚未消除时）双方谈判确定容量投资和转移支付 $\eta$；第二阶段观测到需求后各自生产。第 10 页（期刊页码 137）原文：

> "the firms agree to a deal if their (ex-ante) profits are at least as large as their disagreement payoffs"（19 词）

中译："只有当双方的（事前）利润不低于各自的破裂支付（即不合作时各自的最优利润）时，双方才会达成协议。"

数学形式（公式 16，同页）：转移支付 $\eta$ 和容量 $K_1,K_2$ 由纳什议价解 (NBS) 求解，约束为
$$\pi_1^{\mathfrak s*}(K_1,K_2)-\eta \ge \pi_1^d,\qquad \pi_2^{\mathfrak s*}(K_1,K_2)+\eta\ge \pi_2^d$$
其中 $\pi_i^d$ 是不合作时的均衡利润（disagreement payoff）。这条参与约束**在需求实现之前、基于事前期望利润就已经锁定**，不是等结果出来再算。

**Dong & Li, "Achieving Economic and Environmental Sustainability With Supply Chain Contracts," *Production and Operations Management*, 2025, 34(7):1632–1649。** 本地全文：`/Users/zhouleixishu/Zotero/storage/2JIJNEAP/`。

供应商设计一个收入分成契约 $(w,\phi)$——批发价加收入分成比例——**先公布**，零售商在此契约下**再决定**订货量 $q$（决策顺序是 Stackelberg：供应商先动）。第 8 页（期刊页码 1639）原文（公式 11 的 IR 约束前一句）：

> "the retailer's profit under the revenue-sharing contract should not be less than her optimal profit under the price-only contract"（19 词）

中译："收入分成契约下零售商的利润，不应低于她在纯批发价契约下能拿到的最优利润。"

契约参数 $w,\phi$ 一旦定下，零售商的订货决策（对应到本项目语境里就是"路径/运营决策"）是在给定分配规则下自动求解的，不需要再回头分钱。

**INFERENCE**：这两篇都是(b)类精确对应——把分配规则（转移支付公式 / 收入分成比例）定在运营决策之前，运营决策只需要在给定规则下最优响应。但都不是车辆路径问题场景，是产能投资和供应链订货场景；把这套逻辑搬到"两配送中心联合路径优化"上，需要把"契约参数"重新定义成路径问题里的什么（比如：预先约定好客户归属规则或跨场费率，而不是逐单元事后算 Shapley）——这是方法迁移的空当，本次检索没有找到直接在 VRP/共同配送场景使用这种"先契约后路径"结构的文献。

### (c) 用预测/期望值在合作开始前估计各方收益、据此决定是否合作

**FACT**：Ahn et al. 2024（同上）同时也是这一类的先例——第一阶段的容量投资决策本身就是"合作是否值得"的事前判断，双方基于对未来需求分布的期望效用比较合作收益与不合作收益，据此决定投资多少、要不要谈成。

本次检索范围内，**没有找到**专门针对"多车场/多配送中心 VRP 场景、在路径优化之前先用预测收益决定是否合作"的文献。

### 检索范围说明

优先查了本地 Zotero 库（`/Users/zhouleixishu/Zotero/storage/`，423 个条目，用 Spotlight 内容检索 + Zotero SQLite 元数据检索），命中的两篇均已读原文核对。Guajardo & Rönnqvist (2016) 的分配方法综述、Cruijssen (2006/2007) 的合作壁垒研究——这两个是 Soriano 论文反复引用的关键背景文献——**本地库中没有找到独立全文**，只在 Soriano 论文里作为引用出现，因此这两篇本身的原始论证未能核实，如实标注"未找到"。

---

## 第三块：目标期刊 Rao 2022 / Rao 2019 怎么给自己辩护

**结论：未找到（工具限制，不是文献本身没有内容）。**

具体情况（FACT）：

- 本地 Zotero 库（423 个条目，SQLite 元数据逐条检索作者名"饶"、标题关键词"分摊""核仁""Shapley"）**没有这两篇论文的 PDF 附件**——它们不在本地库里，第一份普查报告标注的"全文核对"应是通过当时可用的其他渠道完成，本次任务的可用工具复现不了那条路径。
- 尝试通过 DOI 访问期刊官网：`https://doi.org/10.12011/SETP2021-3282`（Rao 2022）和 `https://doi.org/10.12011/1000-6788-2018-1668-18`（Rao 2019），两个 DOI 都跳转到 `sysengi.cjoe.ac.cn`（《系统工程理论与实践》官网），能确认期号页码（2022, 42(10):2721-2739；2019, 39(6):1517-1534），但页面摘要区域是前端模板占位符（`{{article.zhaiyao_cn}}`），说明该站是前端 JS 动态渲染，本次可用的抓取工具拿不到渲染后的正文，只能拿到静态壳。
- 尝试搜索引擎检索论文标题、作者名，找到的都是该刊其他相关论文或引用该文的三方页面，没有拿到这两篇的摘要或正文原句。

**因此**：block 3 要求的"摘原话+页码"或"没有专门论证，直接采用"这两种判断，本次都给不出——不是"检查后发现没有专门论证"，而是"本次工具条件下没有拿到全文，无法判断"。这一点和 block 2 的"未找到"性质不同，需要用户知道区别：block 2 是查过、确实没有这类文献；block 3 是这两篇文献大概率存在相关表述，但本次访问不到。

如果用户需要坐实这一块，需要用户本人通过有 CNKI/机构订阅权限的账号下载这两篇 PDF，放入本地 Zotero 库或直接提供文件路径，本任务可以在下一轮直接读取核对。

---

## 第四块：Soriano 式内生参与约束在当前引擎上的接入点（只读勘察，未实现）

### 4.1 当前 E6 正式链路，从入口往上追

调用链（FACT，全部给出文件路径 + 行号）：

```
run_e6_fairness_v3.py  （最外层，只做"生成候选池→逐个算利润→事后过滤"）
  └─ run_unit()  第590行起，line 625:
       run = e3.run_hgs_route_pool_recombination(bundle, initial, seed=seed, ...)
       # e3 = 通过 load_e3() 动态加载的 run_e3_zone_joint.py 的 load_e3()
  └─ run_e3_zone_joint.py:load_e3()  第235-236行
       返回 load_module("_e3_structural_source", E3_RUNNER)
       # E3_RUNNER = e3_mismatch_20260729/run_e3_mismatch.py  （第43-46行）
  └─ run_e3_mismatch.py
       第51行: from epochal_hgs import HgsExactEpoch
       第54-57行: from route_pool_sp import (..., run_hgs_route_pool_recombination)
       第1131行: run = run_hgs_route_pool_recombination(...)  # 真正的搜索调用
  └─ route_pool_sp.py
       第56行: def run_hgs_route_pool_recombination(...)  # 真正的搜索函数体
         内部先按 cv_only/naive_ev/mechanism_ev 三个"view"分别跑 HGS（依赖
         epochal_hgs.py 的 HgsExactEpoch / _run_exact_epoch，第43/163行），
         拿到各 view 的精英路线，汇入路线池；
       第587行: def _solve_set_partitioning(...)  # 路线池 MILP 重组
         用 scipy.optimize.milp 做集合划分问题，从路线池里选一批路线拼出一个
         完整解；目标函数 c=costs（第638-641/690-699行）只有路线成本，
         没有利润/收入项；约束里已经按 depot_id 分车队上限（第670-689行）。
```

### 4.2 成员利润在哪一步算出来的、能不能在候选被接受前拿到

**FACT，file:line**：

- 利润计算函数本体：`solver/src/setp_solver/profit.py` 的 `calculate_depot_profits`（受保护文件，本任务未读其内部实现，只确认调用点）。
- E6 v3 里唯一的调用点：`run_e6_fairness_v3.py:263-276`（`member_breakdowns()`），需要输入一个**已经完整生成、已做过跨场服务标注（`annotate_cross_site_services`）的 `Solution` 对象**，以及 `bundle.instance / bundle.time_profile / bundle.prices / bundle.customer_home_depot`。
- 实际调用发生在 `persist_candidate_pool()`（`run_e6_fairness_v3.py:361-587`）内部循环里，每处理一个来自 `run.stats["complete_candidate_evaluation_trace"]` 的候选，第406行 `breakdowns = member_breakdowns(annotated, bundle)`，算出该候选的每车场利润，第421-431行算出相对 I 基准的边际（`margins`）和是否满足参与（`participation_satisfied`）。
- **过滤发生在候选池已经完整生成之后**：第538行 `fair = [row for row in candidates if row["participation_satisfied"]]`，再从满足参与的候选里挑成本最低的一个（第539-549行），一个都不满足就整批回退到 I（`f_fallback_to_I`，第573行）。

**结论（FACT）**：当前链路里，利润计算依赖一个"已完整生成的解"，不能在候选生成过程中间拿到——因为 `calculate_depot_profits` 需要跨场服务标注后的完整 `Solution`，而这个标注和收入/成本的精确账面（尤其跨场费）只有在整条路径、整个客户归属都确定之后才能算准。这也解释了为什么现有 E6 是"先生成一堆候选，再挨个验参与约束"的结构，而不是"搜索时实时判断"。

### 4.3 若要加"每个车场利润不低于单干利润 θ 倍"的判据，最小改动落在哪里

**INFERENCE，基于代码结构的工程判断**：

真正能拿到"每条候选路线归属哪个车场"信息、又还没生成完整解的环节，是 `route_pool_sp.py` 里的 `_solve_set_partitioning`（第587行）——这是个 MILP 集合划分问题，每个候选路线记录 `RoutePoolRecord`（第37-43行）已经带 `route.home_depot_id` 和 `route_cost`，约束里已经按 `depot_id` 分组统计车队上限（第670-689行）。这是当前架构里唯一同时具备"按车场分组"和"选解之前介入"两个条件的环节。

要在这里加参与约束，理论上的最小改动是：

1. 给 `RoutePoolRecord` 增加每条路线对应车场的**收入贡献**和**跨场费**字段（目前只有 `route_cost`），这两项数据源已经在 `bundle`（`bundle.prices`、`bundle.time_profile`、`bundle.customer_home_depot`）里，不需要新数据源；
2. 在 `_solve_set_partitioning` 的约束列表里，给每个 depot 加一条线性不等式：该车场被选中路线的（收入 − 成本 − 跨场费）之和 ≥ θ × 该车场单干利润；
3. `run_hgs_route_pool_recombination`（`route_pool_sp.py:56`）签名要新增 θ 和各车场单干利润输入，一路传给 `_solve_set_partitioning`；
4. 需要一个新的 E6/E3 runner（不是改 `run_e6_fairness_v3.py`，是新建一个，因为现有的做"位对位重跑校验"，任何算法侧改动都会让它的哈希校验直接 HALT）。

**这个方案是否碰四个受保护文件**：
- `cost.py` / `check.py` / `search/evaluation.py`：不需要碰。约束加在 MILP 里，不改变底层成本/检查逻辑。
- `profit.py`：不需要改，`calculate_depot_profits` 可以被新代码**调用**（不修改）用来算单干基准 P_d0，或者在 MILP 里用简化的线性近似（收入和跨场费按路线可加性拆分，绕开需要完整 Solution 才能跑的那套逻辑）。

**这个方案是否碰未被用户点名、但已被当前实验哈希锁死的文件**：
- **会碰。** `route_pool_sp.py` 和 `epochal_hgs.py` 虽然不在用户点名的四个受保护文件里，但它们被 `run_e3_zone_joint.py` 的 `PROTECTED`/`EXPECTED_PROTECTED_HASHES`（第93-108行）和 `LOCKED_SOURCES`（第124-125行）锁死，也被 `run_e6_fairness_v3.py` 的 `PROTECTED_HASHES`（约第60-76行）锁死。改 `route_pool_sp.py` 一行代码，现有 E3/E6 v3 runner 的 `verify_protected()` / `verify_source_lock()` 就会直接 `HALT_PROTECTED_HASH_DRIFT`。这不是能不能改的技术问题，是"改了就必须承认这是一次新的算法身份、需要新的实验编号和证据链"的纪律问题——和第一份普查报告 6.1 节的结论一致。

**一个未验证的关键假设**：上面第2步默认"跨场费和收入可以按路线可加性拆分，不依赖其他路线怎么选"。这一点本任务没有去读 `china81_completion.py` / `profit.py` 内部实现去证实或证伪——仓库里此前有过"跨场费漏计"的教训（07-11 发现的 c^tr 缺口），说明跨场费的计算不是想当然地简单。如果跨场费实际上依赖整体解的其他部分（比如同一客户在不同候选组合里被不同车场服务，跨场费定义会变），那么 MILP 里的线性可加近似就不成立，需要换一种更贵的方案（比如生成完整解后再用 Lagrangian/割平面往回加约束，或者放弃 MILP 内生化，改成"多次生成完整解+局部修复"这种更接近 ALNS 局部搜索过滤的做法）。这一步在正式立项前应该先花小半天单独核实。

### 4.4 诚实的工作量区间

**INFERENCE，估计依据见下**：

- 若第4.3节的可加性假设成立（跨场费和收入可按路线独立拆分）：给 `RoutePoolRecord` 加字段、给 MILP 加约束、改函数签名、写一个新 runner 校验单元哈希一致性——大约 **2-4 人日**。这个估计基于：MILP 框架已经存在且已经按 depot 分组约束（不是从零建模型），需要新增的主要是数据字段和线性表达式，属于"扩展现有结构"而不是"重新设计"。
- 若可加性假设不成立，需要先花时间核实跨场费的计算逻辑（可能半天到一天），再决定是否改用生成完整解后再筛选/修复的方案（这条路更接近现有 E6 的"生成→过滤"架构，但要把"过滤"从"一次性挑选"改成"迭代修复直到参与约束满足或达到预算"，工程量会显著上升）：**再加 2-4 人日**，总计 **4-8 人日**。
- 以上都不含：跑正式实验的计算时间、独立校验器编写、写进论文的方法章节改写。这个区间和第一份普查报告 6.1 节给出的"3-8 人日"范围一致，两次独立估计互相印证。

---

## 附：本任务的检索边界

- Soriano 2023：全文逐页核对，13 页全读。
- Ahn 2024、Dong & Li 2025：全文核对（关键论证段落定点读，非逐页通读）。
- Sobhanan 2024（Equity-Driven Workload Allocation for Crowdsourced Last-Mile Delivery）：读了摘要和引言，属于"优化中做公平"的同类思路（众包配送场景），但检索"ex ante/ex-post"关键词未命中论文原话使用这类表述，因此没有列入第二块的正式先例，只作为背景一并记录：本地路径 `/Users/zhouleixishu/Zotero/storage/R9NCAMNZ/`。
- Guajardo & Rönnqvist (2016)、Cruijssen (2006/2007)：本地库无独立全文，未找到。
- Rao 2022、Rao 2019：本地库无 PDF；期刊官网 JS 渲染，工具读不到正文；未找到（工具限制）。
