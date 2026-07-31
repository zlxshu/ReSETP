# 动态重规划文献取证报告

- 任务编号：`DYNAMIC-REPLANNING-LITERATURE-20260731`
- 日期：2026-07-31
- 性质：只读文献取证。未改代码、未改 TeX、未跑实验、未动封存产物。检索脚本在本目录 `scripts/`。
- 结论标签：`FACT` = 论文原文写着的内容或直接读到的数字；`INFERENCE` = 我的解读。
- 检索边界：本报告只针对**动态重规划**（新订单到达后对尚未执行的任务滚动重排）。
  随机需求 / 需求预测 / 前瞻性调度类文献只在方法学定义（动态度、拒单口径、重复次数）上取用，
  不作为可采用的路线展开。

---

## 0. 数据口径

**语料**（`scripts/extract_corpus.py`，输出到会话临时目录，不入库）：

- 从本地 Zotero 库 `/Users/zhouleixishu/Zotero/storage/` 抽出 **34 个 PDF 全文**，
  Zotero 重复条目已按论文去重（姜广田 3 份、范厚明 2 份、贾永基 2 份、邱莹莹期刊版 3 份，各只取一条）。
- 其中 **33 份文本层可用**，1 份（邱晗光等 2020）文本层为 CAJ 自造字编码、`pdftotext` 输出乱码，
  改用视觉读取 PDF 第 1—3 页与第 8—9 页。**没有任何一篇因抽取失败被静默丢弃。**
- **逐段核对并在本报告中引用的：19 篇**（下表）。
- **只做关键词扫描、未逐段核对的：15 篇**（Mardešić 2024、Wang 2025 ESWA、Ge 2025、He 2025、
  Zhao 2025、Wang & Chen 2025、范厚明 2022、侯莹 2026、卢福强 2026、石建力 2023、张文博 2016、
  邱莹莹 2024 期刊版、Fan 2021、Shi 2025、Lin 2021）。它们的命中/未命中计入第 1 节和第 6 节的否定证据。
- **仅可访问元数据、无本地全文：0 篇**。本报告没有转录任何未经本地核对的数字。

**全库扫描**（`scripts/q6_library_sweep.py`，专供第 6 节的否定结论用）：
对 Zotero 库中**全部 399 个 PDF**（排除 `._*`）逐个 `pdftotext` 后做精确正则匹配。
`mdfind`（Spotlight）对中文与词干做模糊匹配，命中数不能直接当证据，故不用其计数。
本报告第 6 节的"未找到"以该全库扫描为分母，扫描口径与结果见 §6.3。

**页码口径**：中文期刊按版面印刷页码（从抽出文本的版心页眉/页脚复核）。
Elsevier 文章号制期刊（Zhang & Van Woensel 2023 = 文章号 108751；Ojeda Rios 2021 = 107604）
按论文内部页码 1—36 / 1—23 标注。Voccia 等 2019 的本地 PDF 是
`Transportation Science, Articles in Advance, pp. 1–18` 版，**无最终卷期页码**，按该版内部页码标注。
邱莹莹学位论文按论文自身页码（PDF 物理页 − 12）。

### 逐段核对的 19 篇

| # | 论文 | 出处 | 本地状态 |
|---|---|---|---|
| 1 | Pillac, Gendreau, Guéret, Medaglia | *EJOR* 225(1): 1–11, 2013 | 全文 |
| 2 | Ojeda Rios, Xavier, Miyazawa 等 | *Computers & Industrial Engineering* 160: 107604, 2021 | 全文 |
| 3 | Zhang & Van Woensel | *Int. J. Production Economics* 256: 108751, 2023 | 全文 |
| 4 | Voccia, Campbell, Thomas | *Transportation Science*, Articles in Advance, pp.1–18 | 全文（预印版面） |
| 5 | Goodson, Ohlmann, Thomas | *Operations Research* 61(1): 138–154, 2013 | 全文 |
| 6 | 邱晗光, 周继祥, 龙跃 | 《中国管理科学》28(8): 114–126, 2020 | 全文（视觉读取） |
| 7 | 李阳, 范厚明, 张晓楠（= `ref:18`） | 《中国管理科学》30(8): 254–266, 2022 | 全文 |
| 8 | 邱莹莹（= `ref:71`） | 上海理工大学硕士学位论文, 2024 | 全文 |
| 9 | 林明锦, 王建新, 王超 | 《计算机集成制造系统》28(6): 1870–1887, 2022 | 全文 |
| 10 | 姜广田 等 | **《系统工程理论与实践》44(7): 2362–2380, 2024** | 全文 |
| 11 | 张晓楠 等 | **《系统工程理论与实践》45(1): 269–289, 2025** | 全文 |
| 12 | 徐小峰 等 | 《管理科学学报》24(10): 106–126, 2021 | 全文 |
| 13 | 贾永基 等 | 《工业工程与管理》27(2): 59–66, 2022 | 全文 |
| 14 | 葛显龙 等 | 《运筹与管理》31(8): 57–63, 2022 | 全文 |
| 15 | 张金良, 李超 | 《中国管理科学》30(9): 184–194, 2022 | 全文 |
| 16 | Dong, Wang, Zhang | *Sustainable Energy Technologies and Assessments* 58: 103366, 2023 | 全文 |
| 17 | Miyabe, Fujimoto, Hayashi | *Journal of Energy Storage* 132: 117626, 2025 | 全文 |
| 18 | Cheng, Bian, Shi, Chen | arXiv:2209.12373（*Carbon-Aware EV Charging*）, 2022 | 全文（预印本） |
| 19 | Wang, Cui, Cui 等 | *Energy Engineering* 123(1), 2026（网络版 doi:10.32604/ee.2025.069576） | 摘要+引言+方法节 |

---

## 1. 问题 1：新订单无法被可行服务时，文献怎么处理

### 1.0 一句话

**FACT：在核对的全部 19 篇里，没有任何一篇把"某个订单服务不了"升级为"该算例不可行"。
失败的单位始终是那一张订单，不是那一次实验。** 出口共找到 6 类，逐条列在 §1.1。

**FACT（唯一一处提到"算例不可行"的原文，而且是当作建模缺陷说的）**：
Ojeda Rios 等 2021, p.8：

> "the combination of hard time windows, no possibility of customer rejection and a finite number of vehicles may render problem instances infeasible"
> （硬时间窗、不允许拒单、车辆数有限，这三者同时存在可能使问题算例不可行。）

同页还写：

> "these two simultaneous situations can make many instances of the problem in hand unfeasible"
> （这两种情形同时出现会使手头问题的许多算例不可行。）

扩展原文（p.8）："there is a natural connection between hard time windows and the impossibility to reject clients, since these two simultaneous situations can make many instances of the problem in hand unfeasible"

**INFERENCE**：这句话描述的三件事——硬时间窗、不允许拒单、有限车队——正是 E7 的配置。
文献把它当作**建模时要避开的组合**来叙述，不是一种可以报告的实验结局。

**FACT（该文的计数）**：Ojeda Rios 等 2021, p.8：25 篇论文允许拒客，55 篇不允许
（"we found 25 papers considering problems where it is possible to reject customers ... and 55 papers that do not cover such a possibility"）。
同页还有一条结构性观察：不允许拒客的论文里，多数干脆不加车辆容量约束
（"when the possibility of rejecting customers is not present, most of the papers do not consider vehicle capacity constraints"）。

### 1.1 找到的出口做法（逐条）

每条先给一句限长原文（英文 ≤25 词 / 中文 ≤40 字）与中译；需要上下文时，
在其后另起「扩展原文」一行给出完整段落，不计入限长。

#### (a) 拒单（rejection），可带惩罚或以"最大化被接受订单数/收益"体现

**FACT** Zhang & Van Woensel 2023, p.5：

> "service providers can reject the dynamic requests they are unable or unwilling to serve"
> （服务商可以拒绝那些自己无力服务或不愿服务的动态请求。）

扩展原文（p.5）："In many VRPDSRs, service providers can reject the dynamic requests they are unable or unwilling to serve. Under this setting, a new request should be accepted before being inserted into vehicle routes."

**FACT** 同文 p.14，给出拒单的判定规则本身：

> "a dynamic request is rejected only if it cannot be feasibly inserted into any vehicle's route"
> （只有当一个动态请求无法被可行地插入任何一辆车的路线时，它才被拒绝。）

扩展原文（p.14）："most rejection strategies adopted in DPDPs are reactive in the sense that a dynamic request is rejected only if it cannot be feasibly inserted into any vehicle's route."

**FACT** 同文 p.6，拒单进目标函数的方式：

> "maximizing the number or revenue of the accepted requests (or minimizing the penalty for rejections) is commonly incorporated into the objective function"
> （通常把"最大化被接受请求的数量或收益"（或"最小化拒单惩罚"）写进目标函数。）

**FACT** 同文 p.29 的统计：

> "Nearly 36% of the reviewed papers explicitly consider request rejections, but only 55% of them accept or reject new requests immediately upon request arrival."
> （约 36% 的被评论论文明确考虑请求拒绝，其中只有 55% 在请求到达时立刻做接受/拒绝决定。）

同文 p.21：13 篇当日达论文里 9 篇考虑对不可行（以及在用随机信息时的不盈利）请求拒单
（"Rejections of infeasible (and unprofitable, if stochastic information is used) delivery requests are considered in 9 out of the 13 SDDPs."）。
p.14：28% 的动态取送货问题允许拒单。

**FACT（中文文献里的直接先例）** 邱晗光等 2020,《中国管理科学》28(8), p.115：

> "快速决定是否接受新配送需求 r_a……否则，拒绝接受配送需求 r_a。"

扩展原文（p.115）："供应商需制定相应的订单接受策略（记为 Θ_t），检查现有 A_t ∪ {r_a} 订单集合的配送路径可行性和收益大小，快速决定是否接受新配送需求 r_a；若接受，则转为配送订单，纳入订单集合 A_t，获取服务收益；否则，拒绝接受配送需求 r_a。"

该文把**"拒绝订单数量"作为一行常规报告指标**放进每一张结果表（表 2、表 3、表 4、表 5，pp.121–122）。
表 2（相同时间窗偏差阈值）三种算法的拒绝订单数量：①FIFO 全部接受 RC201/RC206 = 0/0，
②交付方式静态分配 = 0/0，③服务选项动态分配 = 4/4；
表 3（差异化时间窗偏差阈值）为 0/0、0/1、0/0。
表 4（RC201，时间窗宽度 30→240 min 八档）的拒绝订单数量依次为 1、3、0、0、0、0、0、0；
表 5（RC206）为 0、2、2、0、0、1、0、2。
原文对其作用的说明（p.121）：

> "拒绝某些服务成本高于服务收益的配送需求，从而提高整个批次的配送利润"

**FACT** 葛显龙等 2022,《运筹与管理》31(8), p.59（电动车动态路径，拒单与顺延合用）：

> "路径 2 在该服务日内拒绝服务该动态客户点，而将服务时间推迟到下一服务日。"

扩展原文（p.59）："由于动态客户 2 距离路径 r2 较远使得其插入会引起新增换电次数至少两次，因此路径 2 在该服务日内拒绝服务该动态客户点，而将服务时间推迟到下一服务日。对于路径 1 和路径 3，都接受了新增动态需求客户。"

#### (b) 外包 / 第三方承运（outsourcing、subcontracting）

**FACT** Voccia 等 2019, p.4（Articles in Advance 版）：

> "we postpone that decision until we determine that it is infeasible for the delivery to be made by the existing fleet"
> （我们把那个决定推迟到确定现有车队无法可行完成该次交付之时。）

扩展原文（p.4）："Requests can be served by the existing fleet of vehicles or by a third party. We assume that it costs more to serve a request via the third party ... We model only the assignment of requests to the third party, but we postpone that decision until we determine that it is infeasible for the delivery to be made by the existing fleet of vehicles. **For requests served by the existing fleet, we do not allow a request's time constraints to be violated.**"

**INFERENCE**：这正是与 E7 直接对位的一段。Voccia 等对本车队保持**硬时间窗、不许违反**，
与 E7 一致；差别只在于当本车队做不到时，模型有一个第三方出口，因此失败的是那一张订单，
实验单元照常产出目标值（该文目标为"最大化现有车队可完成的请求期望数量"，p.4）。

**FACT** Zhang & Van Woensel 2023, p.26，把外包与即时拒单直接对比：

> "the requests that cannot be feasibly served are outsourced at high costs"
> （无法被可行服务的请求以高成本外包。）
>
> "the infeasible requests are rejected by the service provider immediately"
> （不可行请求被服务商立即拒绝。）

扩展原文（p.26）："In Angelelli et al. (2009), the requests that cannot be feasibly served are outsourced at high costs, while in Angelelli et al. (2010), the infeasible requests are rejected by the service provider immediately. The numerical experiments of Angelelli et al. (2010) reveal that the policy with outsourcing outperforms the policy with immediate acc[eptance]..."

同文 p.14 指出外包属于"隐式拒单"，且与显式拒单不同，不必立刻决定：

> "In contrast to the explicit rejections, subcontracting decisions have little impact on customer satisfaction and hence do not need to be made immediately."

#### (c) 软时间窗 / 迟到惩罚（把不可行降级为成本）

**FACT（用量）** Ojeda Rios 等 2021, p.8：

> "19 papers use hard time windows, 17 papers use soft time windows, 19 use other time constraints, and 25 have no time constraints."
> （19 篇用硬时间窗，17 篇用软时间窗，19 篇用其他时间约束，25 篇无时间约束。）

**FACT** 徐小峰等 2021,《管理科学学报》24(10), p.111，目标函数含晚到项：

> "c_l Σ_{n∈C_0} max{λ_np − LT_np, 0}"（晚于时间窗的总机会成本）

该文动态客户使用**梯形模糊时间窗**（四点式），附录表 A2（p.122）逐条给出，
如节点 28 `[65,105,155,195]`、节点 51 `[40,50,110,120]`、节点 52 `[30,60,340,370]`。

**FACT** 贾永基等 2022,《工业工程与管理》27(2), p.61：目标含"提前到达单位惩罚成本 C_E"
与"延迟服务单位惩罚成本 C_L"。同文 p.64 明确说明批处理粒度变粗时会发生什么：

> "会造成部分动态新增客户处理时刻晚于其最早服务时刻，导致违反客户时间窗的惩罚成本增加"

扩展原文（p.64）："随着 Δ 增加，总成本越来越高。这是因为 Δ 越大对动态客户的响应效率越低，会造成部分动态新增客户处理时刻晚于其最早服务时刻，导致违反客户时间窗的惩罚成本增加。"

**INFERENCE**：这是与 E7 失败机理最贴近的一条原文。"批处理时刻晚于订单时间窗"这一现象，
在该文里被显式承认为**重规划间隔 Δ 的正常后果**，其代价是惩罚成本上升；
文中没有把它处理成不可行。

**FACT** 张晓楠等 2025,《系统工程理论与实践》45(1), p.272：全篇不拒单，把迟到当目标：

> "假设所有订单均被服务。"
> 目标：`min E Σ_{r∈R} max{Dt_r − (t_r + t̄), 0}`（最小化延迟时间）

#### (d) 推迟到下一个规划周期 / 下一服务日

**FACT** 李阳等 2022,《中国管理科学》30(8), p.256（= `ref:18`）：

> "当前时间片内新客户点不会立刻处理，会传递至下一时间片参与实时优化，n_ts 越大，新客户点响应速度越快"

**FACT** 张晓楠等 2025, SETP 45(1), p.272：延迟分配是一个**决策动作**，不是失败：

> "订单的分配可以推迟，但是分配一旦做出，不能改变。"
> p.273："当 Σ_{v∈V} x_{r,v,k} = 0 时，订单 r 被延迟分配……当订单被延迟且一直没有新订单到来时，该延迟订单将在延迟达 σ 个单位时间时触发新决策状态。"
> 实验中 σ = 25 min，允许延迟分配的最大订单数量 μ_max = 3（p.282）。

**FACT** 葛显龙等 2022, p.59：推迟到下一服务日（引文见 §1.1(a)）。

**FACT** Zhang & Van Woensel 2023, p.21 提到延后到当日结束的做法
（"rejections to the end of the day, like those adopted in Klapp et al. (2018a,b)"）。

#### (e) 在重规划时刻**新增车辆**（这是 E7 现在做不到的一条）

**FACT** 张金良、李超 2022,《中国管理科学》30(9), p.186：

> "在重新规划配送路径时，除了在途车辆外，还需要派出新的配送车辆"

扩展原文（p.186）："在重新规划配送路径时，除了在途车辆外，还需要派出新的配送车辆，设从配送中心新派出的车辆编号为 h+1, h+2, …, m，所以配送车辆集合为 K = {1,2,3,…,h, h+1, h+2, …, m}。"
同文 p.187 说明校验口径："新派出的车辆检查是否超过最大载重量"。

**FACT** 姜广田等 2024,**《系统工程理论与实践》**44(7)，同一篇里出现三次：

> p.2365："当前派遣的车辆的载货量或油量不能完成配送任务，需新派 5 号车从配送中心出发"
>
> p.2374（实验 1，10:30 触发点）："当前的车辆载货量无法满足店铺配送，故由配送中心派出一辆 3 吨车继续完成配送任务"
>
> p.2377（实验 2，11:30 触发点）："当前的车辆载货量无法满足店铺配送，故由配送中心派出一辆 5 吨车完成配送任务"

扩展原文（p.2365）："因新增 3 个店铺及其他店铺需求变化等问题的调整，当前派遣的车辆的载货量或油量不能完成配送任务，需新派 5 号车从配送中心出发，进行新线路的配送。"
扩展原文（p.2374）："由于新增店铺 24、25 号店铺，当前的车辆载货量无法满足店铺配送，故由配送中心派出一辆 3 吨车继续完成配送任务；因 11 号店铺临时退货，而 1 号车的油量无法满足取货任务，故派 5 号车到达 11 号店铺完成取货并返回配送中心。"

**FACT** 邱莹莹学位论文（= `ref:71`）p.48：

> "配送中心重新派出一辆电动汽车，以满足这些动态需求客户的配送要求"

扩展原文（p.48）："在进行动态需求的更新后，出发车辆的负载无法满足动态顾客 21 和 22 的需求。因此，配送中心重新派出一辆电动汽车，以满足这些动态需求客户的配送要求。"
p.50 第二次更新："由于车辆负载和时间窗限制，配送中心需要再次重新派出一辆电动汽车来满足动态顾客 22 的需求。"

**FACT** 徐小峰等 2021, p.117："根据新需求的出现虚拟配送中心'5'和虚拟配送中心'23'的行驶路线都发生了调整，而且**增配了车辆**服务客户。"

**INFERENCE**：在这 4 篇里，"当前在途车辆吃不下新订单"是**触发新增车辆**的常规事件，
而不是终止事件。E7 的动态续排把资产池锁死在名义方案已动用的实体车上
（诊断报告 §5），这一点在核对到的动态重规划文献里没有找到对应先例。

#### (f) 判定整个算例不可行

**未找到**。19 篇逐段核对论文中 0 篇；15 篇关键词扫描论文中 0 篇。
全语料对 `instances? ... infeasible`、`no feasible solution`、`不可行`、`无可行解` 的检索，
只命中 §1.0 引的 Ojeda Rios 那一处（当作建模缺陷叙述）、
Mardešić 2024 的一处（说的是 MDP 状态空间穷举不可行，与算例无关）、
以及 Shi 等 2025 的一处（说的是邻域搜索本轮找不到可行解就跳过该次迭代，不是判算例失败）。

### 1.2 "到达时刻已晚于其最晚交付时刻"的订单，文献当合法情形还是数据错误

**先答"当合法还是当数据错误"：两个标签在文献里都没出现。**

`FACT`：19 篇逐段核对论文中，**没有一篇讨论"到达即已过期"的订单**——既没有把它列为合法情形处理，
也没有把它称作数据错误或异常输入。这种情形在这些论文里根本不会发生，
因为算例生成规则一律把时间窗从到达时刻向后构造（下表 8 条规则）。
`INFERENCE`：Pillac 等 2013 的 `de^TW` 取值区间 `[0,1]`（p.3）在定义上已排除 `l_i < t_i`，
所以这类订单落在通行度量的定义域之外；但这是我的推导，不是原文的判定。

**FACT：核对到的每一篇给出订单级到达时刻与时间窗数据的论文，都是按"时间窗从到达时刻向后构造"生成的；
没有找到任何一篇出现或允许"到达即已过期"的订单。** 逐条：

| 论文 | 构造规则（原文） | 出处 |
|---|---|---|
| Voccia 等 2019 | "TW.d1: A 1-hour deadline is created by setting e_n = r_n and l_n = e_n + 1 hours."；"TW.f: ... setting e_n = r_n + 1 hour and l_n = e_n + 1 hour"；"TW.h / TW.r: a uniform distribution is used to select e_n from one of the **remaining** hours of the day" | p.10 |
| Voccia 等 2019（兜底规则） | "we require that all requests have a minimum time window width of one hour. This means that if a TW.f request is generated at 7.5 hours, we shift the time window so that e_n = 8 and l_n = 9. ... For the TW.d2 deadline case, requests that arrive at the end of the day have at least a one-hour deadline." | p.10 |
| 张晓楠等 2025（SETP） | "一个能保证食物新鲜度的最大交付期限 t_r + t̄"，实验中 t̄ = 50 min | p.272 / p.282 |
| 张晓楠等 2025（到达流兜底） | 基本流"订单的到达为覆盖整个运营期的均匀分布（**最后一小时除外，因为所有的订单都需要在有限的订购期限 T 内完成**）" | p.282 |
| 李阳等 2022（`ref:18`） | "除 T 外，配送中心还有订单截止时间 T_co，已有研究多设置 T_co = T/2，算例模拟求解时 t_i > T/2 的动态客户点视为预先已知静态客户点进行处理。"；约束式(10) `0 ≤ t_i < T` | p.256 |
| 邱莹莹（`ref:71`） | "配送中心在一定时间内接收动态需求信息……**在动态信息接收时间窗结束时，不再接收新的顾客需求**。车辆必须在时间窗内服务完所有的顾客" | 学位论文 p.10 |
| 邱晗光等 2020 | 时间窗由供应商预定义的候选集 SLOT 给出（如 9:00—10:00、12:00—13:00、14:00—15:00），顾客从中选择；"在时刻 T 停止接受本批次配送订单，时间窗为 [0,T)" | p.114—115；p.122 "时间窗宽度通常是由城市配送服务供应商预定义的" |
| 贾永基等 2022 | 表 5 逐条给出 9 个动态新增客户的到达时刻与时间窗（见下） | p.65 |

**FACT（可直接对照的逐单数字）** 贾永基等 2022, p.65 表 5（时间以配送中心最早服务时刻 7:00 为零点，单位 min）：

| 客户 | 到达时刻 | 时间窗 | 到达 → 窗左端 | 到达 → 窗右端 |
|---|---:|---|---:|---:|
| 26 | 91 | [240, 300] | +149 | +209 |
| 27 | 92 | [300, 360] | +208 | +268 |
| 28 | 105 | [180, 240] | +75 | +135 |
| 29 | 107 | [300, 360] | +193 | +253 |
| 30 | 156 | [240, 360] | +84 | +204 |
| 31 | 165 | [240, 420] | +75 | +255 |
| 32 | 174 | [180, 240] | **+6** | +66 |
| 33 | 361 | [420, 600] | +59 | +239 |
| 34 | 387 | [540, 660] | +153 | +273 |

**9/9 的订单在其时间窗开启之前到达**；最紧的一单（客户 32）距窗左端仍有 6 min、距窗右端 66 min。
该文的重规划间隔 Δ = 30 min，三次更新发生在 9:00、10:00、13:30（p.65）。

**FACT（Pillac 的度量本身就排除了"到达即过期"）** Pillac 等 2013, p.3 给出 Larsen 的带时间窗有效动态度：

> 反应时间定义为"the difference between the disclosure time t_i and the end of the corresponding time window l_i, highlighting that longer reaction times mean more flexibility to insert the request into the current routes"
> （公开时刻 t_i 与相应时间窗右端 l_i 之差；反应时间越长，把该请求插进当前路线的余地越大。）
>
> `de^TW = (1/n_tot) Σ_{i∈R} (1 − (l_i − t_i)/T)`
>
> "these three metrics only take values in the interval [0, 1]"（这三个指标的取值只落在 [0,1] 区间内。）

**INFERENCE**：若 `l_i < t_i`（到达即过期），则 `1 − (l_i − t_i)/T > 1`，
超出该文自述的取值区间。也就是说，通行的动态度量在定义上已假定 `t_i ≤ l_i`。
这不是一句禁令，但说明这类订单落在文献惯用的度量之外。

### 1.3 对甲/乙两条整改路线的证据归属

**两条都有文献支持，且在文献里是并存的，不是二选一。**

- **(甲) 模型缺出口**：`FACT`。拒单（§1.1a，含中文先例邱晗光 2020 把"拒绝订单数量"作为常规报告指标）、
  外包（§1.1b，Voccia 2019 的触发条件与 E7 完全对位）、软时间窗惩罚（§1.1c，贾永基 2022 明确把
  "批处理时刻晚于时间窗"当作 Δ 的正常代价）、顺延（§1.1d）、动态新增车辆（§1.1e，4 篇，含 2 篇
  目标期刊/母版论文）。Ojeda Rios 2021 p.8 还直接点名"硬时间窗 + 不许拒单 + 有限车队"会使算例不可行。
- **(乙) 事件数据留余量**：`FACT`。§1.2 表列 8 条构造规则，其中
  **订单截止时间 T_co = T/2**（李阳 2022 = `ref:18`，还写明 `t_i > T/2` 的订单改按静态客户处理）、
  **动态信息接收窗结束即停止接单**（邱莹莹 = `ref:71`）、
  **最后一小时不放单**（张晓楠 2025，SETP）、
  **最小时间窗宽度 1 小时并整体后移**（Voccia 2019）
  这四条是显式的"留余量"规则。

**INFERENCE**：文献里这两件事同时做——既按到达时刻向后构造时间窗，又保留一个订单级出口。
两者不冲突：前者保证正常情况下订单可服务，后者兜住车队饱和或几何位置不利的少数情况。

---

## 2. 问题 2：动态事件怎么生成

### 2.1 到达时刻与时间窗的关系

见 §1.2 表。归纳（`FACT`）：三种构造方式，全部从到达时刻向后长：

1. **窗随单生**：`e_n = r_n`，`l_n = e_n + 常数`（Voccia 2019 TW.d1/TW.d2：1 h / 2 h；
   张晓楠 2025：`l = t_r + t̄`，`t̄ = 50 min`）。
2. **窗在到达之后的剩余时段里抽**：`e_n` 从当日剩余整点中均匀抽（Voccia 2019 TW.h/TW.r），
   或由供应商预定义的候选时段集合 SLOT 中由顾客选择（邱晗光 2020, p.114）。
3. **窗独立给定，但订单只在前半天放**：李阳 2022 的 `T_co = T/2`；邱莹莹的
   `[t_0, t_n] = [08:00, 10:00]`（学位论文 p.47）。

**FACT（没有找到的东西）**：核对的 19 篇里，**没有一篇写出形如 `l_i − t_i ≥ 某个下界` 的显式不等式约束**。
留余量是通过上面三种构造方式实现的，不是通过写一条约束。李阳 2022 的约束式(10) `0 ≤ t_i < T`
只限制订单出现时刻不超出配送中心工作时间，不涉及该订单自身的时间窗。

### 2.2 动态度怎么定义、常用取值

**FACT** Pillac 等 2013, p.3，三个层次的定义：

- Lund 等：`d = n_d / n_tot`（动态请求数 / 总请求数）。
- Larsen 的有效动态度：`d_e = (1/n_tot) Σ_{i∈R} t_i / T`（公开时刻的归一化平均）。
- Larsen 的带时间窗有效动态度：`d_e^TW = (1/n_tot) Σ_{i∈R} (1 − (l_i − t_i)/T)`。
- 分级（`FACT`，同页）："Larsen et al. use the effective degree of dynamism to define a framework classifying D-VRPs among weakly, moderately, and strongly dynamic problems, with values of d_e being respectively lower than 0.3, comprised between 0.3 and 0.8, and higher than 0.8."

**FACT** 林明锦等 2022,《计算机集成制造系统》28(6), p.1872：

> "动态度指在车辆执行配送任务过程中动态客户与所有客户的比例。"

同文 p.1881 案例：100 个静态客户 + 32 个动态客户（`INFERENCE`：按其定义 = 32/132 ≈ 24.2%）。

**FACT** 贾永基等 2022, p.64：

> "动态率是反映动态复杂度的一个指标，是指动态客户数量与总客户数量的比值"

表 3 逐档取值：**0%、10%、20%、40%、60%、80%**，
对应目标平均值 4998.4 / 5068.8 / 5082.2 / 5121.9 / 5195.5 / 5379.2，
与动态率 0（静态问题）的差距分别为 0 / 1.4% / 1.7% / 2.5% / 4.0% / 7.6%。
该文另在 4.5 节以 `50_R201` 为例设"前 25 个客户为静态、后 25 个为动态新增"（p.64），即动态率 50%。

**FACT** Dong 等 2023, p.8：动态度由两个参数刻画——变化率 τ（每 τ 代）与变化程度 φ；
`τ ∈ {50, 100, 150}`，`φ ∈ {0.1, 0.5, 1.0}`，组合出 **9 条动态实验序列**。
（`INFERENCE`：该文的"动态"以算法迭代代数为时钟、改的是客户需求量，不重生成时间窗，
与本项目的"按钟点到达的新订单"不是同一口径。）

### 2.3 一个运营日多少次事件、多少个新订单

`FACT`，逐篇：

| 论文 | 静态规模 | 事件数 | 新增订单数 | 触发次数 |
|---|---|---|---|---|
| 邱莹莹（`ref:71`）学位论文 p.47 | 20 客户 + 5 充电站 | 8（5 新增 / 2 取消 / 1 需求减少） | 5（= 静态的 25%） | 4（08:30 / 09:00 / 09:30 / 10:00） |
| 姜广田 2024 SETP 实验 1，p.2374 表 5 | 21 店铺 | 10 | 3 新增客户（14.3%） | 3（9:06 / 10:00 / 10:30） |
| 姜广田 2024 SETP 实验 2，p.2376 表 11 | 60 店铺 | 13 | 3 新增店铺（5.0%） | 5（9:30 / 10:30 / 11:30 / 12:36 / 12:48） |
| 贾永基 2022，p.65 表 5 | 25 静态客户 | 9 | 9（36%） | 3（9:00 / 10:00 / 13:30） |
| 徐小峰 2021，附录表 A2（p.122） | 27 静态节点 | 28 动态节点 | 28（`INFERENCE`：动态度 ≈ 51%） | 1（T1 = T0 + t，t = 100，p.116） |
| 林明锦 2022，p.1881、p.1883 | 100 静态客户 | 32 动态客户 | 24 个新增客户 + 8 个原有客户追加需求转成的新客户 | 1（在 (T_i + T_{i+1})/2 时刻） |

**FACT** 姜广田 2024 SETP p.2374 表 5 的列头是"序号 | 店铺号 | 坐标 | 动态时间 | 动态类型 | 服务时间"——
**新增客户没有时间窗列**。该文只对少数店铺预设硬性交付时刻
（p.2374："本文设定 10、50、17 号店铺为紧急配送店铺，需要在 9:30 完成配送，35 号店铺需要在 [10:30–11:00] 之间完成配送"）。

---

## 3. 问题 3：重规划怎么触发 + ref:18 / ref:71 核对

### 3.1 文献里的三种触发

**定时（等分时间片 / 固定间隔）** —— 最常见。

| 论文 | 参数 | 出处 |
|---|---|---|
| 李阳 2022（`ref:18`） | 时间片数目 `n_ts`，每片时长 `T/n_ts`；实验取 `n_ts = 25` | p.256（定义，"借鉴 Kilby 等[6]"）、p.260（取值） |
| 贾永基 2022 | 时域长度 Δ；敏感性取 **10 / 20 / 30 / 60 / 90 min**；动态算例取 Δ = 30 min | p.64 表 4、p.65 |
| 徐小峰 2021 | "用'时间片'驱动策略规划行驶路径，即设定固定的时间间隔 t 进行车辆调度"；实验 t = 100 | p.113、p.116 |
| 姜广田 2024 SETP | "本文设计周期性优化事件为 0.5 h" | p.2375 |
| 林明锦 2022 | 在配送周期中点 (T_i + T_{i+1})/2 触发 | p.1883 |
| 张晓楠 2025 SETP | 延迟订单达 σ 未被安排即触发，`t_k = t_{k−1} + σ`；σ = 25 min | p.272—273、p.282 |

**定量（累计量达上限即触发）** —— 只在 `ref:71` 里找到成文定义（见 §3.2）。

**事件驱动（每来一单即处理）**：

- **FACT** 李阳 2022, p.256 把动态策略二分为"周期性优化策略及连续性优化策略"，
  该文自身走周期性；p.254 综述里写另一路"每当新客户点出现时即进行优化"。
- **FACT** 张晓楠 2025 SETP, p.272："决策点 k 可能被新订单触发，也可能被在决策点 k−1 的延迟订单触发。
  在第一种情况下，令 t_new 为新订单的到来时间，决策点 k 的决策时刻为 t_k = t_new。"
  （`INFERENCE`：这是"事件驱动 + 定时兜底"的组合，不是"定时 + 定量"。）
- **FACT** Zhang & Van Woensel 2023, p.5：重优化在"continuously, periodically, or at event-triggered decision epochs"发生。

**三种触发的直接对照实验（罕见，且就在目标期刊）** —— **FACT** 姜广田 2024 SETP, p.2377，
表 14 把周期性优化 / 连续性优化 / 本文调整策略放在同一算例上比：

| 调整策略 | 车辆使用数 | 方案调整次数 | 行驶距离(km) | 总成本(元) | 动态响应率 |
|---|---:|---:|---:|---:|---:|
| 周期性优化 | 5 | 3 | 429.08 | 1421.29 | 90% |
| 连续性优化 | 5 | 10 | 436.16 | 1446.51 | 100% |
| 本文调整策略 | 5 | 4 | 429.08 | 1407.57 | 100% |

原文的解释（同页）："采用周期性优化策略时，不能及时响应实验 1 中的动态事件 2，一号车服务完一号店铺时间为 9:14，
需要等待 16 分钟，才到达周期性优化调整时间窗口，故降低了配送系统的效率。采用连续性优化策略时，
配送方案调整次数远多本文的调整策略，使得车辆路线频繁变更，增加系统运行次数及配送成本。"

### 3.2 `paper_main.tex:630—643` 的两条引用核对

正文写的是"参照动态需求批处理研究 \cite{ref:18,ref:71}，本文同时考虑定时和定量两种批事件触发策略"，
并给出 `τ_m = min{ min{u : W(τ_{m−1}, u) ≥ W̄}, τ_{m−1} + T^int }`。

| 引用 | 定时触发 | 定量触发 | 出处 |
|---|---|---|---|
| `ref:18` 李阳等 2022 | **支持**：等分时间片 `T/n_ts`，`n_ts = 25` | **不支持** | p.256、p.260 |
| `ref:71` 邱莹莹学位论文 | **支持** | **支持** | p.24 §3.3.2 |

**FACT（`ref:18` 的否定证据，含正反两面）**：对该文全文去空白后逐词计数：
`触发` 0、`累计` 0、`阈值` 0、`达到` 0、`定量` 0、`批量` 0、`满足条件` 0；
`上限` 1、`个数` 1（均与触发无关）。
正面一侧：`时间片` 70、`周期性` 25、`连续性` 3。
该文只有等分时间片，且明确按"周期性优化策略"自我定位（p.256、p.257）。
它的另一条与本项目相关的设定是**订单截止时间 `T_co = T/2`**（p.256），
以及**车辆订单预通知时间 `T_ac`**，实验取 `T_ac = 0`（p.260）。

**FACT（`ref:71` 的支持证据，逐字）** 邱莹莹学位论文 p.24 §3.3.2：

> "批事件处理策略是指当特定时间点的动态需求满足物流系统中预先定义的条件时，批量处理将接收到的动态信息。该策略包含定时优化和定量优化。定时优化将配送中心的配送时间窗分成 n 等份，每一时间段的动态需求都在该时间段末集中处理……定量优化处理则是提前设置处理需求顾客个数等的上限，达到该上限就立刻对累积的动态需求进行处理。"
>
> "本文的动态需求处理策略同时考虑了定时和定量两种批事件处理策略……配送中心的服务时间窗为 [e_0, l_0]，设定在 [t_0, t_n] 时刻内接受动态需求信息，将该时段均分为 n 个时间区间 [u(0), u(1), u(2), …, u(n−1), u(n)]。设置动态需求和上限为 q̄，当顾客需求总量达到该上限时，将顾客加入待配送行列。同时，设置动态需求处理时间间隔 T，当需求总量未达到上限，经过一个时间间隔也能够处理动态顾客……则 u(t) 取值如式子(3-2)：
> `u(t) = min{ u_q, u(t−1) + T, t_n }`  (3-2)
> `u_q = min{ u_q | q(u(t−1), u_q) ≥ q̄, u(t−1) > u_q }`  (3-3)
> 其中，u(0) = t_0，u(n) = t_n。"

（式 (3-2)、(3-3) 已按 PDF 第 36 物理页视觉核对，符号逐个对照。`pdftotext` 文本层丢失了
`|`、`≥`、`>` 与 `q̄` 的上划线，本报告以视觉读取为准。）

**参数取值（`FACT`，学位论文 p.47）**：`[t_0, t_n] = [08:00, 10:00]`，`q = 500 kg`，`T = 30 min`；
实际触发 4 次：08:30、09:00、09:30、10:00。

**两处必须记录的差异（`FACT`）**：

1. **`ref:18` 不支持定量那一半。** 正文把两条引用并列挂在"定时和定量两种批事件触发策略"之后，
   但定量触发只有 `ref:71` 一个来源。
2. **`ref:71` 的式 (3-2) 是三项取小，本项目的式 `eq:trigger` 是两项取小。**
   源文献的第三项 `t_n` 是**动态需求接收窗的右端**，即"到 t_n 就不再接新单、也不再另开重规划"。
   本项目的公式没有这一项。`ref:71` 对 `t_n` 的作用另有正文说明（学位论文 p.10）：
   "在动态信息接收时间窗结束时，不再接收新的顾客需求。车辆必须在时间窗内服务完所有的顾客，并返回配送中心。"

**与 E7 现场的对应关系（须写明一次）**：
`FACT` —— `ref:71` 式 (3-2) 的第三项 `t_n` 是动态信息接收窗右端，实验取 `t_n = 10:00`
（学位论文 p.47），配送时间窗则延到当日结束；本项目 `eq:trigger`（`paper_main.tex:634–639`）
没有对应项。
`INFERENCE` —— E7 事件流中被诊断为 `new_due_time` 早于其批次 `trigger_time` 的订单
（`docs/handoff/e7_infeasibility_diagnosis_20260731/report.md` §3.4，最极端 −5415.4 s），
其发生区间正是 `t_n` 这一项所治的区间：接单窗与配送窗未分开时，
新单可以出现在"再重规划一次也来不及"的时段。

---

## 4. 问题 4：对照臂怎么设计、报什么指标

### 4.1 对照臂的先例（按"对照的是什么"分类）

**(A) 触发策略之间互比** —— 姜广田 2024 SETP p.2377 表 14：周期性优化 / 连续性优化 / 本文策略。见 §3.1。

**(B) "有动态处理策略" vs "无动态处理策略"** —— **FACT** 邱莹莹学位论文 p.55 §5.4.2：

> "该对比实验在配送过程中不考虑动态化需求，也忽略需求处理间隔 T 和需求和上限 q 等因素。将动态需求作为已知的需求，加入原有的配送客户中……在不考虑动态需求处理策略的情况下，配送中心需要额外派出两辆电动汽车来满足新增的配送需求。"

报告指标（同页）：车辆数量、平均负载率。

**(C) 全部接受（无策略）作基线，与两种接受策略比** —— **FACT** 邱晗光等 2020, pp.121—122，三臂：
①FIFO 全部接受、②交付方式静态分配、③服务选项动态分配。

**(D) 机制盲 / 机制感知对照（碳）** —— **FACT** Miyabe 等 2025, p.12，三臂：

> "one is a case where no en-route charging is performed, and charging occurs only at the depot after the completion of delivery operations (hereafter, 'ordinary VRP' or 'VRP'), and the other is a case where en-route charging is performed without considering CO₂ emissions from the charging power (hereafter, 'ordinary EVRP')."

即：普通 VRP（不途中充电）/ 普通 EVRP（途中充电但不考虑充电电力的碳）/ 本文低碳 EVRP。
**INFERENCE**：其中"ordinary EVRP"就是一个碳盲臂，与 E7 的 `CARBON_BLIND` 同构。

**(E) 短视策略（myopic policy）作对照** —— **FACT** Zhang & Van Woensel 2023, p.28：
"their nVFA policy outperforms a myopic policy and the policy of Angelelli et al. (2009)"。

**(F) 算法之间在同一动态时点比** —— **FACT** 姜广田 2024 SETP p.2378 表 16/表 17：
IAGA / PSO / GA 在每个触发时刻（9:06、10:00、10:30 / 9:30、10:30、11:30、12:36、12:48）
各报 Best / Ave / T(s) / Dev%。
徐小峰 2021 p.118 表 6 是 MOIGA / NSGA-II / MOIA 在动态阶段的对比。

**FACT（没有找到的）**：核对到的动态重规划论文里，**没有出现"静态方案完全不调整"这种臂**。
最接近的是邱莹莹的 (B)——但那是"终局全知静态"（把动态需求当已知），不是"冻结原方案硬扛"。

### 4.2 报什么指标来说明"动态重规划挽回了多少"

`FACT`，按论文汇总：

| 论文 | 指标 |
|---|---|
| 姜广田 2024 SETP, p.2377 表 14 | 车辆使用数、方案调整次数、行驶距离、总成本、**动态响应率** |
| 邱莹莹 学位论文 p.50/p.55 表 5.9/5.15/5.16 | 启动成本、行驶成本、油耗成本、耗电成本、碳排放成本、总成本（逐个触发时刻一行）；车辆数量、平均负载率 |
| 邱晗光 2020 pp.121—122 表 2—5 | RB/AHD 总收益、行驶距离、RB/AHD 订单数量、**拒绝订单数量**、车辆数量、平均接受决策耗时、平均路径更新耗时、平均策略调整耗时、利润 |
| 徐小峰 2021 p.117 表 5 | 企业成本 Z、客户满意度 S（双目标，报 Pareto 非劣解集） |
| 贾永基 2022 p.64 表 3/表 4 | 最优值、最差值、平均值、**与静态问题（动态率 0）平均值的差距 %** |
| Voccia 2019 | 目标为"最大化现有车队可完成的请求期望数量"（p.4），未完成部分外包 |
| Miyabe 2025 pp.13—14 | 总 CO₂ 排放（主指标），按季节拆分；与 ordinary VRP 比降幅 22.7% / 17.9% / 19.6% / 7.2%；Wilcoxon 检验 p = 6.099×10⁻⁷ |

**INFERENCE**：跨这几篇，说明"动态重规划挽回了多少"最常用的一组是
**总成本 + 车辆使用数 + 一个"这次动态到底被吃下多少"的量**
（动态响应率 / 拒绝订单数量 / 完成请求数 / 与静态口径的差距 %）。
姜广田的"动态响应率"和邱晗光的"拒绝订单数量"是同一件事的正反两面。

---

## 5. 问题 5：统计单位与呈现

`FACT`，逐篇：

| 论文 | 每算例几条事件流 / 几次运行 | 聚合方式 | 呈现 |
|---|---|---|---|
| Voccia 2019, p.10 | "For each geography and time window type, **25 random request streams** are generated" | "we report the **average results across the 25 request streams**" | 表 |
| Goodson 2013, pp.148—149 | "For each of the 216 problem instances, we randomly generate **500 realizations** according to the specified probability distributions for customer demand (a total of 108,000 realizations)." | "averages of estimates of the expected demand served for each of 500 realizations in each of 54 problem instances" | 表 |
| 张晓楠 2025 SETP, p.282 | 10 个算例（订单规模 30/60/120/240，骑手 5/10，COV 0/0.3/0.6）；离线训练 MaxN = 2000，**测试 1000 个在线问题** | MIN / MAX / MEAN | 表 1、表 3、表 4 |
| 姜广田 2024 SETP, p.2378 | "每种算法**运行 10 次**" | 最满意解 Best、平均解 Ave、平均求解时间 T/s、改进幅度 Dev% | 表 15—17 + 收敛图（图 18、19） |
| 李阳 2022（`ref:18`）, p.260 | "在每个预设 t_sd 下分别对其求解 **10 次**" | Best、Aver、%Dev、%Dev1 | 表 1—4 |
| 贾永基 2022, p.63—64 | "每个算例均**运行 10 次**，取运算结果的平均值"；动态率/时域长度分析各 10 次 | 最优值 / 最差值 / 平均值 / 差距% | 表 2—4 |
| 林明锦 2022, p.1879 | "分别对算法**运行 10 次**"（R101、R105、C101、C105、RC101、RC105） | 图 5 展示 10 次结果 | 图 |
| 邱莹莹（`ref:71`）, 学位论文 p.36 | "采用了 MATLAB 软件对混合车队进行了 **10 次的重复试验**"（写在算法检验一节；第 5 章动态算例未重申次数） | 未逐次列出 | 表 |
| Dong 2023, p.8 | "Each experiment is run **10 times independently**"，9 条动态序列 | t 检验（表 B3，符号 s+ / s−） | 表 |
| 邱晗光 2020, p.121 | "三种调整算法**重复运行 20 次**"（仅计算耗时） | 最大值、最小值、中位数、两个四分位数 | 箱型图（图 9） |
| Miyabe 2025, p.13 | 逐日仿真，按季节聚合 | 均值 + Wilcoxon 检验、Diebold–Mariano 检验 | 表 + 图 |

**INFERENCE（能看出的惯例）**：中文期刊侧几乎一律 **每算例 10 次运行**，报 Best / Ave（部分加 %Dev），
不报标准差，多数不做假设检验——这与
`docs/handoff/journal_convention_alignment_20260730/report.md` 对目标期刊六篇的结论一致。
英文侧的"多条事件流"是另一条独立的重复轴：Voccia 每算例 25 条请求流并**只报流间均值**，
Goodson 每算例 500 条实现。两条轴是分开的：随机算法的重复运行次数，与事件流的条数，
在这些论文里不互相顶替。

**FACT**：Voccia 2019, p.10 把 25 条请求流与采样流公开在
`http://ir.uiowa.edu/tippie_pubs/65/`。

---

## 6. 问题 6：时变碳强度是已知外生参数还是待预测量

### 6.1 结论

**FACT：在核对到的语料里，"调度用预测碳强度 / 事后结算用实际碳强度"这一对区分，
在路径优化（VRP）论文中未找到；在充电调度论文中找到 2 篇明确做了这件事。
另有 1 篇路径优化论文明确写出它把电网排放因子在规划与评估两端用同一套值，并把这一点写进正文。**

### 6.2 找到的三篇

**(1) Cheng, Bian, Shi, Chen（2022），*Carbon-Aware EV Charging*，arXiv:2209.12373**
（`INFERENCE`：这是充电站调度，不是车辆路径。）

`FACT`，p.4：

> "In this section, we propose a forecasting module to inform charging station operators day-ahead carbon intensity, and extend the framework described in Sec III to real-time settings."
>
> "Offline algorithm assumes we have access to all the information including future arrival statistics. While in the real-time algorithm, we assume we can only decide charging rate based on the **predicted** carbon intensity and information of arrived electric vehicles."

预测值怎么生成（`FACT`，p.4，式 (3)）：以 2021 年 CAISO 数据与 CAISO 日前负荷预测拟合线性回归：

> `Ĉ(t) = β₀ + β₁·Minute + β₂·Hour + β₃·Day + β₄·Month + β₅·Load(t) + β₆·MA(C(t))₂₄ + β₇·MA(C(t))₁₂ + β₈·MA(C(t))₁`
>
> 其中 `MA(·)_a` 为过去 a 小时的滑动平均。

误差怎么报（`FACT`，p.4）：

> "For the CAISO case study, the overall testing mean squared absolute error is 0.0085."

同页图 4 标题：**"The ground truth (blue) and predicted carbon intensity (red) for two-day sample in January and July respectively."**

口径说明（`FACT`，p.4）：

> "We calculate and forecast the **average** carbon intensity rather than marginal carbon intensity, as in this study, we focus on the operating strategies for single EV charging station."

**(2) Wang, Cui, Cui 等（2026），*Energy Engineering* 123(1)，doi:10.32604/ee.2025.069576**
（`INFERENCE`：同样是充电负荷调度，不是路径优化。）

`FACT`，摘要 p.1：

> "this paper proposes a coordinated scheduling strategy that integrates dynamic carbon factor prediction and multi-objective optimization. First, a dual-convolution enhanced improved Crossformer prediction model is constructed ... Based on high-precision predictions, a carbon-electricity cost joint optimization model is further designed"

p.2："data-driven methods, particularly deep learning, have emerged as a promising alternative for **forecasting nodal carbon factors**"。

**(3) Miyabe, Fujimoto, Hayashi（2025），*Journal of Energy Storage* 132: 117626**
—— 唯一一篇**路径优化**论文，且它把这条边界写明了。

`FACT`，p.12：

> "We used the total CO2 emissions during the EDV operations as the primary comparison indicator. While the planning phase employed the **predicted** PV surplus data, CO2 emissions were computed using the **actual** surplus PV values, thus reflecting a realistic emission comparison. **On the other hand, the same pre-calculated values were used for the emission factors of the grid at both the planning and evaluation stages.**"
> （规划阶段用预测的光伏余电数据，而 CO₂ 排放用实际余电值计算，从而反映真实的排放比较。另一方面，电网排放因子在规划和评估两个阶段使用同一组预先计算的值。）

**INFERENCE**：这句话把两件事分开了——被预测的量（本地光伏余电）走"预测调度 / 实际结算"，
而**电网排放因子在两端是同一条序列**，且论文把这一点当作方法说明写出来，而不是回避。
这与本项目 `paper_main.tex:456` 声明的"调度用预测、事后用实际"是**相反的口径**，
但与本项目数据中只有一列 `carbon_factor_kgco2e_per_kwh` 的实际状态是**同一种做法**。

该文对被预测量的误差怎么报（`FACT`）：

- p.12 式 (20)：`MAE = (1/T) Σ_t |d^m_{t+24hr} − d̂^m_{t+24hr}|`（单位 kWh/30 min）。
- p.13 表 5：5 个充电站，持续法基线 MAE 分别 2.48 / 0.74 / 1.03 / 1.45 / 3.03，
  本文模型 1.95 / 0.51 / 0.76 / 1.20 / 2.55，改进率 27.0% / 44.9% / 36.5% / 21.1% / 18.8%，
  Diebold–Mariano 检验 p 值 2.05×10⁻³ / 9.33×10⁻⁸ / 9.67×10⁻⁶ / 5.60×10⁻³ / 1.58×10⁻²，5% 水平全部拒绝 H₀。
- p.17 附录 B：另用 MAPE，并挑高精度日（2024-01-19，MAPE 11.04%）与低精度日
  （2024-01-16，MAPE 121.96%）对照。
- p.17 §4.4.6：控制变量式的预测误差敏感性——选实际余电相差 <9% 但预测精度差近一倍的两天
  （2023-05-16 与 05-18），低精度日的排放为 8.73 kg-CO₂，高精度日为 5.57 kg-CO₂。

### 6.3 未找到的部分（否定证据的检索口径与分母）

否定结论不是基于那 34 篇语料，而是基于 **Zotero 全库 399 个 PDF 的逐篇正则扫描**
（`scripts/q6_library_sweep.py`）。扫描分三组词：

- **A 组（时变/电网碳强度类）**：`carbon intensity`、`grid emission factor`、
  `emission factor of the grid`、`marginal emission`、`time-varying carbon`、
  `碳强度`、`电网碳`、`排放因子`。
- **B 组（预测/实际对举类）**：`forecast`、`predicted carbon`、`day-ahead`、
  `prediction error`、`预测`、`日前`、`事后结算`、`实际碳`。
- **C 组（"预测/实际"直接修饰"碳强度/排放因子"）**：
  `forecast(ed) (average|marginal) carbon intensity`、`predicted … carbon intensity`、
  `carbon intensity forecast|prediction`、`forecast(ed)/predicted/actual emission factor`、
  `emission factor forecast`、`realized carbon`、`actual carbon intensity`、
  `碳强度预测`、`预测碳强度`、`预测的碳强度`、`碳排放因子预测`、`预测排放因子`、
  `预测碳排放因子`、`实际碳强度`。

`FACT`，扫描结果：

| 组 | 命中篇数 / 399 |
|---|---:|
| A | 24 |
| B | 117 |
| A ∧ B（同一篇内共现） | 15 |
| **C（严格共现）** | **1** |

**C 组唯一命中**：`57ITRNUI/Cheng 等 _ 2022 _ Carbon-Aware EV Charging.pdf`
——即 §6.2(1) 已逐段核对的那一篇，是充电站调度而非车辆路径。

A ∧ B 的 15 篇已逐条查看文件名与 A 组命中词：其中 11 篇的 A 组命中词只是 `排放因子`
（邱莹莹学位论文、陈婉茹 2023 及其副本、白雪 2022、巩亮 2026 及其副本、巩炜 2024、
刘长石 2025、徐苏花 2023、张凌玮 2025），`INFERENCE`：这些是车辆油耗/电耗折算用的**固定系数**，
不是随时段变化的电网碳强度；其余 4 篇为 Cheng 2022、Wang 2025（Crossformer）、
Wang & Chen 2025（IEEE TSG）、Miyabe 2025，均已在 §6.2 交代。
另有 Wang 等 2024（*Applied Energy*，重型卡车鲁棒路径）命中 `carbon intensity`，
但 B 组命中词与之无共现关系，未落入 C 组。

据此：

- **未找到**任何一篇**车辆路径**论文同时定义"调度时使用的预测碳强度"与"事后结算的实际碳强度"两个符号。
- **未找到**任何一篇对**电网碳强度预测误差**建模、并在路径决策中评估其影响的论文。
  Miyabe 2025 做的是**光伏余电**的预测误差；其电网排放因子在规划与评估两端同值，且原文写明（§6.2(3)）。
- 找到的两篇做"预测碳 → 调度"的论文（Cheng 2022、Wang 2025 Crossformer）都是**充电负荷调度**，不含路径决策。

**这条否定的残余盲区（`FACT`，须记录）**：全库 399 个 PDF 中，
3 个完全无文本层（`R5PGGPIU/多仓库带时间窗的车辆路径问题及智能优化算法研究.pdf`、
`S9BBU5SD/衣霄翔 2012 消费视角下的居住区商业服务设施配建体系研究`、`Z67C8SY7/mnsc.6.1.80.pdf`）；
另在 191 个中文标题 PDF 中，**13 个正文抽取不出中文**（CAJ 自造字编码或纯扫描件），
清单为：考虑碳排放的冷链物流网络结构研究 / S 工业气体公司同时取送货车辆路径优化研究 /
基于深度学习的车辆路径规划算法 / 快时尚服装产品配送电动物流车路径规划研究 /
"双碳"背景下冷链物流车辆路径问题研究 / 邱晗光等 2020 / 低碳经济视角下的城市物流配送路径优化研究 /
带回收机制的绿色物流配送路径优化研究 / 供应链风险管理研究——以 B 公司为例 /
多仓库带时间窗的车辆路径问题及智能优化算法研究 / 衣霄翔 2012 / 双碳背景下冷链物流配送路径优化研究 /
李进和张江华 2014 碳交易机制对物流配送路径决策的影响研究。
其中邱晗光 2020 已视觉读取（与碳无关）。**剩下 12 篇只按标题判断与本节无关，未逐页核对。**

---

## 7. 交付物

| 文件 | 内容 |
|---|---|
| `report.md` | 本文件 |
| `scripts/extract_corpus.py` | 把 28 篇候选 PDF 抽成文本（只读；输出写到会话临时目录） |
| `scripts/grep_pages.py` | 关键词检索并给出 PDF 物理页号与页眉，用于定位版面印刷页码 |
| `scripts/q6_library_sweep.py` | 第 6 节用的全库（399 个 PDF）精确正则扫描，产 `q6_library_sweep.json` |
| `done.json` | 完成信号 |

脚本全部只读，输出写在会话临时目录，不入库、不改任何既有文件。
