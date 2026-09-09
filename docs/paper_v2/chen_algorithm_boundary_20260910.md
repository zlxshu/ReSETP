# 陈雨蝶2025 算法章边界写法取证与本文两句改写方案

日期：2026-09-10　来源：Zotero item 6KCQCP66 / 附件 AYDB6KXP
`/Users/zhouleixishu/Zotero/storage/AYDB6KXP/陈雨蝶 等 _ 2025 _ 双碳背景下复杂冷链物流模型及求解算法.pdf`
（24页，算法章＝第3章，PDF第8–10页）。以下引文逐字摘自该 PDF 文本层。

## 一、她的"算法基于什么"那句（框架句）

第3.1节唯一一段，逐字：

> 为应对这些挑战, 设计一种具有变邻域搜索操作和动态灾变机制的多种群遗传算法(Multiple Population Genetic Algorithm with Variable Neighborhood Search and Dynamic Catastrophe Mechanism,MPGA-VNS), 算法流程如图1所示. 该算法以遗传算法为主体, 通过改进两点交叉、动态灾变机制和多种群并行进化进行优化, 增强其全局搜索能力. 同时, 采用变邻域搜索操作对当前最优解进行优化, 以提升局部搜索能力.

**该框架句所带引用数 = 0。**"以遗传算法为主体""采用变邻域搜索操作"都不给出处。

**整个第3章（3.1＋3.2 步骤1–8）引用数 = 0**（对第608–679行做 `[数字]` 标记检索，零命中）。
对照：本文第4章算法部分（tex 第682–790行）共 8 处 `\cite`，键为
`ref:76, ref:77, ref:12, ref:hgs-cvrp-2022`(×2)`, ref:srex, ref:64, ref:91`。

## 二、她怎么介绍标准算子——一律直接命名，一个引用都不给

> 步骤4：遗传操作. 遗传操作包括选择、交叉、变异. 选择操作采用轮盘赌算法和精英保留策略. 交叉操作采用改进两点交叉, 随机选取两个染色体和交叉部分, 将交叉部分分别添加到另一个染色体的前端和后端, 然后剔除相同基因得到两个子代, 交叉概率用Pc 表示……变异操作采用两点互换变异, 变异概率用Pm 表示.

> 本文设计五种路径内邻域结构和四种路径间邻域结构. 路径内邻域操作包括1)insert-1：r1 的一个客户移动至r1 不同位置;……4)exchange：互换r1 的两个客户;5)reverse：倒转r1 连续客户……路径间邻域操作包括1)shift(1,0)……4)crossover(m1,m2)：r1 、r2 部分客户倒转后互换.

> 步骤3：计算适应度. 解的适应度越高, 代表其越优秀, 选取公式(14)的倒数为适应度函数.

结论：**既不是"每个算子一条引用"，也不是"给算子家族补一条总引用"，而是零引用**——轮盘赌、精英保留、两点互换变异、insert/exchange/reverse/shift/swap 全部只报名字加一句机制说明。她的省引用不是靠含糊，而是靠把算子讲清楚。

## 三、她的自有贡献句与所用动词

引言创新点第3条，逐字：

> 3) 结合遗传算法和变邻域搜索算法的优势设计混合遗传算法, 采用改进两点交叉、动态灾变机制和多种群并行进化等策略，显著提升算法的性能和求解效率。

动词：**设计、采用、改进**（章内另有"本文设置动态灾变规模N""本文设计五种路径内邻域结构"）。
她**确实对单个算子主张自有设计**（改进两点交叉、动态灾变规模、九种邻域结构），但**不用"提出/首次/创新"给单个算子加冕**，也不为任何一个算子附引用。边界表述只有一句、放在引言创新点里，正文算法章不再重复交代来源。

## 四、软件/代码/开源/库/版本号/仓库——**无**

全文检索 MATLAB、Python、Gurobi、CPLEX、开源、源码、代码、软件、github、版本、C++、运行环境，结果：

- 算法与实现层面：**零命中**。她不写用什么语言、什么求解器、什么库、什么版本。
- 仅有的两个 URL 都是**数据**不是代码：CVRP 标准算例集 `http://vrp.atd-lab.inf.puc-rio.br/`（第4.2.1节）、广州车速数据集 `https://github.com/sysuits/urban-traffic-speed-dataset-Guangzhou`（第4.1.1节）。
- 表6 中的 "CPU" 是求解耗时列名，不是硬件配置交代。

**这一条是本文步骤3那句的直接判据**：本文"代码沿用其开源实现PyVRP"这种软件出处声明，在目标期刊范文里没有任何对应物。

## 五、她的算法章体量

- 2个小节：3.1 算法流程图（1段，7句）、3.2 算法步骤（8个步骤段＋1个邻域清单段）。
- 全章约 9 段。
- **花在"算法来自哪里"上的句子：3句**——即3.1中"设计一种……MPGA-VNS""该算法以遗传算法为主体，通过……进行优化""同时，采用变邻域搜索操作……"。其余全部讲本文自己怎么做。

---

## 六、本文各部件归属判定（依据仓库）

| 部件 | 判定 | 一句话证据 |
|---|---|---|
| 种群框架（双种群、偏置适应度、自适应罚系数） | 沿用 | `solver/src/setp_solver/algorithms/problem_hgs/PROVENANCE.md` 明写 "Population, penalty, SREX/OX crossover, and compiled local-search modules … copied from PyVRP 0.12.2 commit ea0c421… under the MIT license"，对应文件 `third_party/setp_hgs_kernel/setp_hgs_kernel/Population.py`、`PenaltyManager.py`。 |
| 客户重定位／客户交换／路段反转 | 沿用 | 编译内核 `third_party/setp_hgs_kernel/setp_hgs_kernel/cpp/search/` 下的 `Exchange.h`、`LocalSearch.cpp` 等，随内核整体拷入。 |
| SWAP*／尾段交换 | 沿用 | 同目录 `SwapStar.cpp/.h`、`SwapTails.cpp/.h`、`SwapRoutes.cpp/.h`、`RelocateWithDepot.cpp`、`DepotSplit.cpp`。 |
| 交叉算子（选择性路径交换 SREX／有序交叉） | 沿用 | `third_party/setp_hgs_kernel/setp_hgs_kernel/crossover/selective_route_exchange.py`、`ordered_crossover.py`；`README.md` 载明公开与私有路径都用内核 SREX。 |
| 分段线性充电 | 沿用 | `FRVCPY_LICENSE_NOTICE.md`：定路径充电决策直接加载未修改的 frvcpy 2020.1035 快照（Apache-2.0），经 `frvcpy_adapter.py` 调用。 |
| Shapley 分摊 | 沿用 | 教科书公式，稿中已随式子引 `\cite{ref:91}`；仓库仅在 `solver/scripts/coalition_accounting_adapter.py` 等脚本层按该公式实现，不含新方法。 |
| 多趟衔接与趟间电量继承 | 本文（在既有框架上适配） | 项目自有包 `problem_hgs/charging.py` 文件头 v1–v4 记录 duty 级多趟充电重建与"anchor every depot action to the preceding trip's actual end energy"；`PROVENANCE.md` 将 Duty 表示与 charging repair 划归项目自有。 |
| 车型置换邻域 | 本文 | 项目自有 `problem_hgs/education.py` 的 `include_whole_duty_type_exchange` 与 `educate_best_improvement`，开关经 `runner.py:182 type_exchange_enabled`、`initialization.py:574` 贯通；内核 `cpp/search/` 无对应算子。 |
| 时变碳充电安排 | 本文 | `problem_hgs/charging.py` 引入 `setp_solver.charge_timing` 的 `charge_timing_objective_value` / `select_charge_timing_start`，按电价时段与电网碳强度择时；上游内核与 frvcpy 均无碳强度维度。 |

---

## 七、两句最小改写（逐字替换对）

### 改写1：算法步骤第3步（tex 第720行）

原文：
```
\textbf{步骤~3：}路径搜索。在近似问题上运行HGS-CVRP算法\cite{ref:hgs-cvrp-2022}，代码沿用其开源实现PyVRP\cite{ref:64}：
```
替换为：
```
\textbf{步骤~3：}路径搜索。在近似问题上运行HGS-CVRP算法\cite{ref:hgs-cvrp-2022,ref:64}：
```
- 字数：39 → 24 汉字（不计 `\cite`），更短。
- 引用：仍是原有两个键，**未新增任何引用**；框架引用 `ref:hgs-cvrp-2022` 保留。
- `ref:64` 全文只在此处被 `\cite` 一次（另有第1616行 `\bibitem`）。合并为方法引用而非删除，可避免留下孤立 bibitem，符合"bibitem==cite 每次编译核"的稿面要求。
- 若另一代理更愿意**彻底删掉** PyVRP：把该句写成 `……运行HGS-CVRP算法\cite{ref:hgs-cvrp-2022}：`，但**必须同时删除第1616行的 `\bibitem{ref:64}`**，否则参考文献表出现未被引用条目。

### 改写2：引言贡献边界句（tex 第188–189行）

原文（166字，零引用）：
```
上述工作中，混合遗传搜索的种群框架与客户重定位、客户交换、路段反转、SWAP*等邻域，非线性充电的分段线性表示，以及Shapley值成本分摊均沿用既有方法；
针对本文问题在上述方法上适配了多趟衔接、油电混合车队与多中心结构，新增了充电电量、费用与时变碳强度下间接排放的同时段统一核算、车型置换邻域和考虑时变碳强度与分时电价的充电安排。
```
替换为（110字，零引用，仍为一句）：
```
本文算法以混合遗传搜索为主体，其种群框架、客户重定位、客户交换、路段反转、SWAP*等邻域、非线性充电的分段线性表示和Shapley值成本分摊沿用既有方法，针对本问题设计了多趟衔接、车型置换邻域和时变碳强度下的充电安排。
```
- 字数 166 → 110，缩短 56 字；**未新增引用**（该句原本就无引用，故不为它补 `ref:76`）。
- 句式对齐她的"该算法以遗传算法为主体，通过……进行优化"，动词只用"沿用/设计"，与她的"设计/采用/改进"同档，不给单个算子加"提出/创新"。
- 三项自有贡献＝多趟衔接、车型置换邻域、时变碳充电安排，与创新点第3条列举的三件完全一致。
- **须知的取舍**：改写删去了原句尾"充电电量、费用与时变碳强度下间接排放的同时段统一核算"。这一条本属创新点第2条的**模型**贡献，留在算法边界句里会把模型贡献混进算法边界；它在创新点第2条已完整表述，删去不丢信息。同时删去"油电混合车队与多中心结构"的适配说明——这两项在创新点第1条已交代。
