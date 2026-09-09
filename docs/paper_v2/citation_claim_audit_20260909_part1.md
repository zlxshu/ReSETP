# 引用—论断逐条核验（第 1 部分：引言 + 模型建立）

核验对象：`docs/paper_v2/paper_main.tex`，`\section{引言}`（含表 `tab:literature-comparison`）与 `\section{模型建立}` 中的全部 `\cite`。
本轮**只读**，未改动 tex。行号为核验时（2026-09-09）的行号，另附锚句以防行号漂移。

判定词只用三种：**属实** / **有出入（写明出入）** / **未找到支撑（写明查了什么）**。

证据记号：Z=Zotero 条目键；PDF p.=该条目 PDF 的页码；GOV=政府门户原页；OA=OpenAlex/Semantic Scholar/出版商页。

本轮取证用到的 Zotero 条目键与本地 PDF 已全部实读（中文 PDF 先用已知短语测过抽取，
`陈婉茹 2023`、`巩亮 2026`、`姜广田 2024`、`高咏玲 2025`、`李阳 2022`、`饶卫振 2022`、`李得成 2021`
七篇抽取可用，未出现乱码，因此未走 pdftoppm 渲染路径）。


### 判定规则（先声明，避免同状态不同判）

本轮把“无本地 PDF、无页级引文”的情形分成两类，判法不同：

- **有独立第三方把该论断明确归属给被引文献** → 判 **属实**，并在证据栏写明归属链条。
  本轮只有一例：第 366 行的 `ref:montoya`——Froger 等 2022（`PDVQ5Z86`）PDF p.3 原文
  “Montoya et al. (2017)…modeled the charging process using concave piecewise linear functions”，
  且 p.6 给出与本文完全同构的断点集与 $φ^{-1}$ 形式。
- **只有出版方摘要能确认“该文涉及这个主题”，没有任何来源把**具体式子/具体做法**归给它** → 判 **未找到支撑**。
  `ref:94` 的三处公式与 `ref:deng` 的排放式属于此类。

---

## 一、引言正文（第 128–140 行）

| 行号（锚句） | cite key | 句子把什么归给该文献 | 证据（键 / 页 / 引文≤30字） | 判定 |
|---|---|---|---|---|
| 128（“加快交通运输领域低碳转型”） | ref:tdf1555 | 《“十五五”碳达峰行动方案》提出加快交通运输领域低碳转型、持续增加新能源汽车保有量、加快公共领域车辆电动化 | GOV gov.cn/zhengce/content/202607/content_7074826.htm，第（十一）条：“持续增加新能源汽车保有量”“加快公共领域车辆电动化” | 属实 |
| 128（“零碳物流园区”） | ref:wlw2026 | 《物流网建设实施方案》提出推广绿色设施设备、加快建设零碳物流园区、建设物流碳排放核算与管理公共服务平台 | 方案正文：“加快建设零碳物流园区”“建设物流碳排放核算与管理公共服务平台”。**注：bibitem 里的 ndrc 官方页只有通知壳与附件链接，正文不在该页**；上述引文取自第三方全文镜像 055110.com/law/1/61396.html | 属实 |
| 130（“李得成等…联合优化车型配置与配送路径”） | ref:6 | 建立油电混合车辆路径模型；设计分支定价算法**联合优化车型配置与配送路径** | Z `R4MW8E32`，PDF p.1 摘要“就车型配比、载重、电池容量、充电率等因素…进行了灵敏度分析”；p.11 图 6“电动车/燃油车可用数量灵敏度分析” | 有出入（车型配比/两类车可用数量是**外生参数**，只做灵敏度分析；模型内生的是路径与每条路径的车型指派，不是车队配置的联合优化） |
| 130（“陈婉茹等…机械功率模型”） | ref:23 | 多车场混合车队、速度影响能耗、机械功率模型分别算两类车能耗、碳交易成本进目标 | Z `NKRC4JZU`，p.3323（PDF p.4）§2.3：“基于机械功率计算车辆在行驶过程中产生的电耗和油耗”；摘要“多配送中心…碳交易成本” | 属实 |
| 130（“碳排放限额与碳交易”） | ref:qiu2024 | 把碳排放限额与碳交易纳入混合车队路径优化 | Z `QLD6M6FA`，p.5720 摘要“carbon cap, carbon tax, carbon trading, and carbon offsetting” | 属实 |
| 130（“城市低排放区对燃油车的通行限制”） | ref:bruglieri2025 | 低排放区对燃油车通行限制进混合车队路径优化 | Z `FSPIDSY3`，p.1 摘要“restrict the access of internal combustion engine vehicles (ICEVs) to urban centers” | 属实 |
| 130（“车队更新政策”） | ref:gao2025 | 车队更新政策纳入混合车队路径优化，考察政策约束下两类车的配置与路径 | Z `M53I5HBR`，p.156 摘要“分别建立了由燃油车和电动车组成的混合车队更新和路径优化模型” | 属实 |
| 132（“多车场多趟…分支定价”） | ref:44 | 带时间窗和释放时间的多车场多趟问题已有分支定价算法 | Z `BLADDV8J`，p.1 摘要“multi-depot multi-trip vehicle routing problem with time windows and release dates”；正文“they must operate multiple trips” | 属实 |
| 132（“其异质车队扩展”） | ref:sahin | 异质车队扩展已有分支定价算法 | Z `DA9LEIID`，PDF p.7“Each vehicle is allowed to perform several trips”；p.8 式(1)–(5)分支定价 | 属实 |
| 132（“混合遗传搜索与动态规划相结合”） | ref:zhao2024 | 时间依赖多趟问题已有混合遗传搜索＋动态规划解法 | Z `3J4VMNNY`，摘要“Time-Dependent SPlit Algorithm (TD-SPA), which is a dynamic programming…”；题名含 hybrid genetic search | 属实 |
| 134（“自1959年…提出VRP”） | ref:dantzig | Dantzig 和 Ramser 1959 提出 VRP | CR 10.1287/mnsc.6.1.80，Management Science 6(1):80–91, 1959，题名 The truck dispatching problem | 属实 |
| 136（“同一路段上的差异化能耗”） | ref:27 | 刻画油电两类车型在同一路段的差异化能耗 | Z `LT38HLC9`/`SGA85GX4`，p.81 摘要“a realistic energy consumption model that incorporates speed, gradient and cargo load” | 属实 |
| 136（“部分充电策略”） | ref:45 | 电动车按后续路径需要灵活补电的部分充电策略 | Z `WNDTM5L3`，p.111 题名与摘要“Partial recharge strategies” | 属实 |
| 136（“分段线性函数表示的电池非线性充电过程”） | ref:montoya | 以分段线性函数表示电池非线性充电过程 | Z `UKVXPMKB` 摘要“the function is nonlinear…extend current E-VRP models”；旁证：Z `PDVQ5Z86` PDF p.3“Montoya et al. (2017)…modeled the charging process using concave piecewise linear functions” | 属实 |
| 136（“充电站的容量限制”） | ref:12 | 充电站容量限制 | Z `PDVQ5Z86`，PDF p.2 摘要“explicitly accounting for the number of chargers available” | 属实 |
| 136（“行驶速度时变时的非线性能耗与部分充电策略”） | ref:zhou2026 | 时变速度下的非线性能耗与部分充电策略 | Z `KTUD9BPC` 摘要“采用非线性能耗模型测度能耗…建立基于时变速度的部分充电策略模型” | 属实 |
| 136（“充电定价方案…作用”） | ref:deng | 充电定价方案对车队运营成本与充电决策的作用 | OA/S2 DOI 10.1016/j.trd.2022.103333；出版方摘要“three variants considering contract, spot, and time-of-use (TOU) schemes…shifting of charging demands to low-priced periods” | 属实 |
| 136（“分时电价…作用”） | ref:shi2025 | 分时电价对车队运营成本与充电决策的作用 | Z `JY2IQSFS`，p.1 摘要“incorporating order selection and time-of-use electricity pricing” | 属实 |
| 136（“按碳强度安排充电时段可降低充电碳排放”） | ref:52 | 按电网碳强度安排充电可降低充电碳排放 | DOI 10.1016/j.trd.2024.104383 出版方摘要“by administering charging control to all BEVs in Shanghai, the above emission could be curtailed by 39%” | 属实 |
| 136（“低碳需求响应…可观减排潜力”） | ref:du2025 | 低碳需求响应引导充电在我国有可观减排潜力 | Z `LRLMX429`，p.1 摘要“could reduce carbon emissions by up to 15 % by 2035” | 属实 |
| 136（“电价信号与碳强度信号方向不一致…反而可能增加排放”） | ref:martin2025 | ①电价信号与碳强度信号方向不一致；②大量车辆跟随同一信号→排放反而增加 | Z `V8ZHKLU3`，p.1 摘要“can inadvertently increase grid emissions when…too many electric vehicles follow the same signal”；p.9“we do not make any inferences about…any electricity price structure” | 有出入（②属实；①**该文根本不建模电价信号**，“电价与碳强度方向不一致”不是它的结论） |
| 138（“允许交叉服务对方区域客户”） | ref:49 | 允许交叉服务对方区域客户的协作配送模型 | DOI 10.1016/j.ejor.2017.08.051 出版方摘要“some of their customers have demand of service for more than one carrier…collaboration…for the service of the shared customers” | 有出入（协作对象限于**共同客户**——同时向多家承运人下单的那些客户，不是“对方区域”的任意客户） |
| 138（“多车场电动车充电站共享框架”） | ref:7 | 多车场电动车充电站共享 | Z `6Z9A3BFA`，p.1 摘要“Sharing charging stations (CSs) is presented as a critical strategy” | 属实 |
| 138（“时间依赖路网下多车场协作与资源共享”） | ref:wang2024 | 时间依赖路网多车场协作与资源共享的路径优化 | Z `6JQKAQER`，p.1 题名与摘要“multidepot time-dependent vehicle routing problem with time windows…resource configu-ration” | 属实 |
| 138（“协作收益在成员之间的公平分配”） | ref:8 | 给出协作收益在成员间公平分配的方法 | Z `IF3WEZZJ`，p.1 摘要“adds a fairness objective function to the classical cost minimization function” | 属实（口径提示：是把公平**作为优化目标内生**，不是事后分摊算法） |
| 138（“考虑企业间服务质量差异的成本分摊”） | ref:91 | 考虑服务质量差异的成本分摊方法 | Z `UIVEWQC2`，摘要“结合Shapley值法求解规则,提出成本分摊结果调整思路” | 属实 |
| 140（“Psaraftis 提出动态车辆路径问题的研究框架”） | ref:14 | 提出 DVRP 研究框架 | TRID 记录 309530 摘要“put dynamic vehicle routing into perspective within the broader area of vehicle routing”，含 dynamic 与 static 的区分、动态过程设计要素 | 属实 |
| 140（“重规划时刻设定与静态子问题分解”） | ref:18 | 重规划时刻设定与静态子问题分解 | Z `R7NZFUZC` 摘要“依据滚动时域对配送中心工作时间进行划分…对各时间片内子问题进行连续迭代优化” | 属实 |
| 140（“多车型动态路径优化”） | ref:51 | 多车型动态路径优化 | Z `GKCQ5LXR`，p.2364（PDF p.3）“使用不同类型车辆…预优化配送路径和动态调整后配送路径” | 属实 |
| 140（“定时与定量联合触发策略”） | ref:71 | 定时与定量联合触发策略 | 查了：Zotero 全库（只有同作者 2024 期刊文《低碳背景下混合车队车辆路径优化研究》`4U7I5H4P`，该文为**静态单车场**，全文只出现 4 次“动态”且均在文献综述，无“定量/批处理/重规划”）；Web 检索 3 次（含精确题名）均未找到该硕士学位论文任何条目或全文 | 未找到支撑 |
| 140（“预测性策略扩展到近似动态规划与深度强化学习”） | ref:mardesic2024 | SDVRP 解法由预测性策略扩展到 ADP 与深度强化学习 | Z `T6LVLNAK`，p.28 摘要“proactive and anticipatory systems…model-based and model-free reactive solution approaches…recent approaches explore solutions using deep learning” | 属实 |
| 140（“结合强化学习与变邻域搜索的求解框架”） | ref:shahbazian2025 | 多车场电动车动态路径的 RL＋VNS 框架 | Z `HE3R5GCH`，p.1 摘要“knowledge-guided multi-agent deep reinforcement learning (MARL) and a variable neighborhood search (VNS)” | 属实 |

---

## 二、表 1 `tab:literature-comparison` 逐格核验（第 162–173 行，12 行 × 5 列 = 60 格）

列的判定口径（本表核验时采用，与正文表述一致）：
**混合车队**＝模型中同时含燃油车与电动（或其他新能源）车；
**分时充电排放**＝把充电电量按时段与随时间变化的电网碳强度（或时段化排放因子）核算充电碳排放；
**多车场**＝模型含两个及以上车场；
**成本分摊**＝给出联盟成本/收益在成员间的分摊或公平化方法；
**动态需求**＝需求在运营中到达或变化并触发重规划。

| 行号 | 文献 | 混合车队 | 分时充电排放 | 多车场 | 成本分摊 | 动态需求 | 判定 |
|---|---|---|---|---|---|---|---|
| 162 | Goeke和Schneider ref:27 | ✓ 属实：`LT38HLC9` p.81“a mixed fleet of electric commercial vehicles (ECVs) and conventional…” | — 属实：全文只算行驶能耗，无电网碳强度/时段排放；PDF 检索 “carbon/emission factor” 无排放核算式 | — 属实：PDF p.4“a mixed vehicle fleet…is positioned at **the depot**”（单车场） | — 属实：全文 “allocat/Shapley” 命中 1 次且为 “cargo load distribution” 语境，无分摊 | — 属实：全文 “dynamic” 10 次全为 “aerodynamic” 与 “dynamically adjusted penalty”，无动态需求 | 全行属实 |
| 163 | 陈婉茹等 ref:23 | ✓ 属实：`NKRC4JZU` 摘要“由传统燃油车和电动车构成的混合动力车队” | — 属实：p.3322“电动车…在离开配送中心前充满电, 在途中不充电”，排放只算 λ＝燃油排放因子 | ✓ 属实：摘要“多配送中心车辆路径-速度联合优化” | — 属实：全文检索“分摊/Shapley/联盟/博弈”命中 0 次 | — 属实：全文检索“动态需求/实时”命中 0 次 | 全行属实 |
| 164 | Wang等 ref:7 | — 属实：全为电动车；“mixed fleet/conventional vehicle” 3 次均在综述与参考文献表（PDF p.3、p.28） | — 属实：目标为运营成本与车辆数，无碳强度/时段排放项 | ✓ 属实：`6Z9A3BFA` 题名“Collaborative multidepot” | **— 有出入** | — 属实：全文 “dynamic” 3 次均在综述，无动态到达/重规划 | **有出入**：该文有 Shapley 分摊。p.1 摘要“a Shapley value model…is proposed to find the best profit allocation scheme”；p.15–16 §5.3.1/5.3.2 专节。该格应为 ✓ |
| 165 | Soriano等 ref:8 | — 属实：PDF p.4“a set 𝑑ℎ of **homogeneous** vehicles at disposal for each depot” | — 属实：非电动车问题 | ✓ 属实：`IF3WEZZJ` 题名“multi-depot vehicle routing problem” | ✓ 属实：p.1“adds a fairness objective function”（公平化收益分配，内生于优化） | — 属实：全文 “dynamic” 命中 0 次，规划期为多天静态排程 | 全行属实 |
| 166 | 邱莹莹 ref:71 | ✓ | — | — | — | ✓ | **未找到支撑**：该硕士学位论文在 Zotero 与 3 次网络检索（含精确题名）中均未找到；同作者 2024 期刊文 `4U7I5H4P` 为静态单车场混合车队，无动态需求，不能替代 |
| 167 | 姜广田等 ref:51 | — 属实：`GKCQ5LXR` 只有燃油车（约束用“车辆油量”），“多车型”指载重不同的燃油车型 | — 属实：无充电 | — 属实：p.2364 单一配送中心（动态时把在途点设为“虚拟配送中心”，非多车场） | — 属实：全文检索“分摊/Shapley/联盟”命中 0 次 | ✓ 属实：摘要“预优化和动态调整两阶段…店铺需求变化…临时退货” | 全行属实 |
| 168 | Li等 ref:52 | — 属实：出版方摘要对象为上海 3777 辆纯电动车充电调度，无燃油车、无配送路径 | ✓ 属实：出版方摘要“optimizes each EV driver's charging schedule to diminish the total carbon emissions”，下层为电力调度，碳排随时段发电结构变化 | — 属实：非路径问题，无车场 | — 属实：摘要无联盟/分摊 | — 属实：摘要无动态需求 | 全行属实（三个 `---` 由出版方摘要判定，本地无 PDF） |
| 169 | Qiu等 ref:qiu2024 | ✓ 属实：`QLD6M6FA` 摘要“both internal combustion engine vehicles (ICEVs) and electric vehicles” | — 属实：碳排放按里程/油耗核算，无电网碳强度分时 | — 属实：PDF p.5“0 is the origin depot and 0′ is the destination depot”（单车场） | — 属实：全文 “allocat” 3 次均为监管方分配碳配额与“resource allocation”政策语，无成员间分摊 | — 属实：PDF p.16 把 “dynamic customer demand” 明列为**后续研究方向** | 全行属实 |
| 170 | Wang等 ref:wang2024 | — 属实：全文无油电两类车队设定，“electric vehicle” 仅见于参考文献 | — 属实：排放来自行驶速度-油耗；全文 “charging” 仅 2 次且在文献表 | ✓ 属实：`6JQKAQER` 题名“multidepot time-dependent” | — 属实：全文检索 Shapley/profit allocation/cost allocation 仅命中参考文献表（PDF p.38），正文无分摊模型 | — 属实：全文检索 “dynamic demand” 命中 0 次 | 全行属实 |
| 171 | Shi等 ref:shi2025 | ✓ 属实：`JY2IQSFS` 摘要“A mixed fleet leverages the strengths of both vehicle types” | — 属实：PDF p.4 排放只按油耗“emissions are linearly related to fuel consumption…carbon emission rate (CER) factor”，分时电价只进成本不进排放 | — 属实：PDF p.4“Vertices 0 and N+1 correspond to the **same depot**” | — 属实：去中心化协作靠**订单选择**，全文 0 次 Shapley，无分摊机制 | — 属实：静态 | 全行属实 |
| 172 | Du等 ref:du2025 | — 属实：电力系统研究 | ✓ 属实：`LRLMX429` HIGHLIGHTS“Using dynamic carbon emission factors as guidance signals”，高时空分辨率碳排因子 | — 属实：全文无车场/配送路径模型 | — 属实：全文 “allocat” 1 次，为福建碳配额分配文件标题 | — 属实：需求侧响应模拟，无动态订单 | 全行属实 |
| 173 | Shahbazian等 ref:shahbazian2025 | — 属实：`HE3R5GCH` 无本地 PDF，证据取自 Zotero 全文缓存 `4B78YF6A/.zotero-ft-cache`：“mixed fleet” 1 次且在参考文献表 | — 属实：全文缓存 “emission” 3 次均为定性表述（“restricting the emission of harmful greenhouse gases”），无排放核算式，“time-of-use” 0 次 | ✓ 属实：摘要“dynamic multi-depot electric vehicle routing problem”；全文 “depot” 82 次 | — 属实：全文缓存 “allocat” 2 次均为“region allocation 把客户分给最近车场”与算法参数，无成员分摊 | ✓ 属实：摘要“Real-time decision-making…respond effectively to dynamic changes” | 全行属实（证据为出版商全文缓存，非 PDF 页码） |

表 1 逐格小计：60 格中 54 格属实、5 格未找到支撑（ref:71 整行 5 格）、1 格有出入（ref:7 的成本分摊）。

两条附带核对：

- **第 176 行表后段**（“由表\ref{tab:literature-comparison}可知……”）只讲“既有研究围绕一类或数类特征展开”
  与非线性充电/分时电价/碳强度缺少统一时段、趟次衔接与状态继承不完善三点，**不依赖 ref:7 的成本分摊那一格**，
  该格由 `---` 改 `✓` 后这一段不需要改。
- **“本文”行的成本分摊 ✓**：模型建立章（第 188–678 行）没有任何分摊/合作博弈的formulation，
  这一格是靠数值实验章的 Shapley 分摊那一节兑现的。审稿人最先戳的就是这格，
  建议在表注或该行处点明兑现位置（“成本分摊见 4.6 节”），否则表与模型章看起来对不上。

---

## 三、模型建立章（第 188–678 行，共 13 处 `\cite`）

已核对：第 188–678 行无 `\input`/`\include`，符号表内无任何 `\cite`，本节 13 处即全部。

| 行号（锚句） | cite key | 句子把什么归给该文献 | 证据（键 / 页 / 引文≤30字） | 判定 |
|---|---|---|---|---|
| 317（“采用实际能耗模型…电耗和油耗”） | ref:23 | 机械功率式、电耗式、单位时间油耗率式、弧段油耗式四式的出处 | Z `NKRC4JZU` p.3323（PDF p.4）§2.3 式(1)–(4)：“基于机械功率计算车辆…电耗和油耗”，符号 T^k_ij / b^k_ij / G^k_ij / f^k_ij 与本文 P/电耗/油耗率/弧段油耗一一对应 | 属实（提示：该文自己写明“采用文献[16]中的实际能耗模型”，[16]＝Demir 等，可考虑一并注明源头） |
| 351（“非线性充电函数采用分段线性形式”） | ref:94 | 分段线性充电函数 Φ_s(τ) 的形式 | 查了：Zotero 全库无该条目（作者 Adulyasak/题名均 0 命中）；ScienceDirect 正文页 403；OpenAlex 与 Semantic Scholar 均无摘要；仅从出版商摘要转述确认该文含“nonlinear charging… time-of-use electricity pricing”，**未取得任何页级证据表明其给出断点式分段线性函数** | 未找到支撑 |
| 366（“充电时长为”） | ref:montoya | Δ_h = Φ⁻¹(B^d) − Φ⁻¹(B^a) | Z `UKVXPMKB` 摘要“extend current E-VRP models to consider nonlinear charging functions”；页级公式取自旁证 Z `PDVQ5Z86` PDF p.6“given by φ_j(∆ + φ_j⁻¹(q))”与断点集 B_j＝(charging time, SoC) 对，且该页 p.3 明确把凹分段线性充电函数归给 Montoya et al. (2017)。**Montoya 原文无开放获取版本，未能直接读到该式所在页** | 属实 |
| 385（“电价与电网碳强度采用统一的时段集合”） | ref:94 | 电价**与电网碳强度**共用同一时段端点集 U_0<…<U_{|T|} | 同上，只能确认该文有 time-of-use 电价的时段化；该文不建模电网碳强度 | 有出入（分时电价的时段离散化可归于该文；把**碳强度**并入同一时段集是本文自己的做法，不是它的） |
| 398（“其在日历时刻 U_t 的电量为”） | ref:94 | 充电过程在时段端点 U_t 的电量表达式 B_ht | 同 351，未取得页级证据 | 未找到支撑 |
| 428（“燃油车直接排放按油耗量和燃油排放因子计算”） | ref:95 | E^g = λ^g·G，λ^g 单位 kgCO₂e/L | Z `HADEF6XR` p.1341（PDF p.4）式(14)与释义：“δ 为碳排放因子, 单位为 kgCO2/L” | 属实 |
| 429（“电动车充电间接排放按不同时段的补电量和电网碳强度计算”） | ref:deng | E^e = Σ_t γ_t·e_ht（**按时段**的碳强度乘补电量） | 查了：Zotero 全库无该条目；ScienceDirect 403；OpenAlex/S2 无摘要；出版方摘要与两次网络检索显示该文是**成本最优**的充电定价（contract/spot/TOU）研究，只定性提到“environmental benefits”，未见按时段碳强度核算排放的公式 | 未找到支撑 |
| 440（“多趟配送按同一车辆在一个运营日内依次执行多个配送趟”） | ref:44 | 多趟配送的建模方式 | Z `BLADDV8J` PDF p.1“due to the limited capacity and the goal of minimizing fleet size, they must operate multiple trips” | 属实 |
| 460（“充电过程集合为空时，前后电量直接继承”） | ref:12 | **趟间**电量继承（无充电时前后趟电量直接衔接） | Z `PDVQ5Z86`：全文 “multi-trip / multiple trips” 命中 0 次，该模型是单趟 E-VRP，不存在“趟间”这一层；其电量传递只在一条路线内部的相邻节点之间 | 有出入（Froger 只支持路线内电量传递，不支持趟与趟之间的继承；趟间衔接的出处应是 ref:44 / ref:sahin） |
| 461（“充电设施容量依据容量受限充电站的并发占用原则”） | ref:12 | 充电站并发占用容量约束 | Z `PDVQ5Z86` PDF p.2“explicitly accounting for the number of chargers available at privately managed CSs”；p.3“each CS has a fixed and often small number of chargers” | 属实 |
| 463（“车辆方案选择采用集合划分形式”） | ref:sahin | 以“整日方案”为列的集合划分主问题 | Z `DA9LEIID` PDF p.7–8：workday 变量 z_p^v，式(2) Σ_{v∈V_j}Σ_{p:j∈J_p} z_p^v = 1 ∀j∈J，“Constraints (2) impose that each customer is visited exactly once” | 属实 |
| 479（“动态阶段沿用文献…保留既有成本并重新规划待执行任务的结构”） | ref:71 | 动态阶段的成本保留＋重规划结构 | 同引言 140 行：该学位论文未找到（Zotero 全库 + 3 次网络检索含精确题名）；同作者 2024 期刊文为静态模型 | 未找到支撑 |
| 521（“动态需求采用定时、定量联合批处理策略”） | ref:71 | 定时＋定量联合批处理触发；新增订单/取消/需求量增减三类动态信息 | 同上 | 未找到支撑 |

---

## 四、合计

| 判定 | 引言正文（32） | 表 1（60 格） | 模型章（13） | 合计（105） |
|---|---|---|---|---|
| 属实 | 28 | 54 | 6 | **88** |
| 有出入 | 3 | 1 | 2 | **6** |
| 未找到支撑 | 1 | 5 | 5 | **11** |

---

## 五、非“属实”条目的具体改法（17 条：6 条有出入 + 11 条未找到支撑，逐条给动作）

### A. 有出入（6 条）

1. **第 130 行 ref:6（李得成等）**——现写“设计分支定价算法**联合优化车型配置**与配送路径”。
   该文车型配比是外生参数、只做灵敏度分析。
   **改法（改句）**：“李得成等\cite{ref:6}建立带时间窗的电动车与燃油车混合车辆路径模型，
   设计分支定价算法求解，并就车型配比、载重、电池容量等因素做灵敏度分析。”

2. **第 136 行 ref:martin2025**——现句把“电价信号与碳强度信号方向不一致”也算在该文名下，
   但该文明确不建模电价（p.9“we do not make any inferences about…any electricity price structure”）。
   **改法（改句，只保留该文真有的那半句）**：“……然而当大量车辆跟随同一碳排放因子信号或信号本身含噪时，
   按单一信号安排充电反而可能增加电网排放\cite{ref:martin2025}。”
   若确需保留“电价与碳强度方向不一致”这层意思，本文自己的 4.x 实验就是证据，应在实验章说，
   引言不挂文献；或另找同时含电价与碳信号对比的文献（Zotero 已有 Powell 等 2024
   *Future-proof rates for controlled electric vehicle charging*，键 `4KL9BJ6V`，可入库后引用）。

3. **第 138 行 ref:49（Fernández 等）**——“允许交叉服务**对方区域客户**”过宽。
   **改法（改句）**：“既有研究提出了承运人之间相互服务**共同客户**的协作配送模型\cite{ref:49}……”

4. **第 164 行 表 1 ref:7 的“成本分摊”格**——现为 `---`，该文有完整 Shapley 分摊模型与专节。
   **改法（改表）**：把该格改为 `$\checkmark$`。
   连带检查：正文第 176 行“由表\ref{tab:literature-comparison}可知……”一段若据此格立论，需同步复核。

5. **第 385 行 ref:94（统一时段集合）**——该文只有分时电价的时段化，没有电网碳强度。
   **改法（缩小归属范围，改句）**：“电价按时段离散核算\cite{ref:94}；本文进一步令电网碳强度
   与电价共用同一时段集合~$\mathcal T$，且 $U_0<U_1<\cdots<U_{|\mathcal T|}$，则……”
   这样既保住引用，又把“两种信号同一时段体系”明确留成本文贡献 2）。

6. **第 460 行 ref:12（趟间电量继承）**——Froger 是单趟模型，无“趟间”一层。
   **改法（换引用）**：该句改引 `ref:44`（Zhen 等 2020 多趟）或 `ref:sahin`（Şahin 与 Yaman 2022 整日 workday），
   即“趟间间隔包括必要等待及相应充电时间；充电过程集合为空时，前后电量直接继承\cite{ref:44}。”
   第 461 行的 `ref:12` 保持不动（那处属实）。

### B. 未找到支撑（11 条：第 7–17 项）

**第 7 项＝第 351 行 ref:94；第 8 项＝第 398 行 ref:94。**
该条目本地无 PDF、出版商页 403、OpenAlex 与 Semantic Scholar 均无摘要，拿不到任何页级证据。
**改法（换成已核实的等价出处）**：
- 第 351 行分段线性充电函数 → 改引 `ref:montoya`（源头）与 `ref:12`
  （Froger 等 2022 PDF p.6 直接给出断点集“(charging time, SoC) pair”，与本文 $B^c_{sn},T^c_{sn}$ 完全同构），
  写成 `\cite{ref:montoya,ref:12}`；
- 第 398 行时段端点电量 $B_{ht}$ → 改引 `ref:12`（同页 $φ_j(∆+φ_j^{-1}(q))$ 即该式的连续时间形式）。
- 若坚持保留 `ref:94`，须先拿到该文 PDF 补页码证据，否则这两处（连同上面第 5 项）都是无据引用。

**第 9 项＝第 429 行 ref:deng。** Deng 等 2022 是成本导向的充电定价研究，未见按时段碳强度算排放的式子。
**改法（换引用，文献表里已有更合适的）**：
- “电量 × 电网排放因子”的结构式可直接用 `ref:95`——巩亮等 2026 p.1341 式(12)“$C_{i2}=E_{ie}\times F^e$，
  $F^e$ 为电网排放因子”，与第 428 行同源，两句合成
  “燃油车直接排放按油耗量和燃油排放因子计算、电动车充电间接排放按补电量和电网排放因子计算\cite{ref:95}”；
- “按**时段**取碳强度”这一层，改引已在文献表中的 `ref:woody2021`（Woody 等 2021，配送电动车按时变电网排放因子安排充电）
  或 `ref:52` / `ref:82`；
- `ref:deng` 保留在第 136 行（那处属实），此处删去。

**第 10–17 项＝ref:71（邱莹莹学位论文）全部 8 处**：引言第 140 行（第 10 项）、模型章第 479 行（第 11 项）、
第 521 行（第 12 项），以及表 1 第 166 行的五个格（第 13–17 项）。
这份学位论文在 Zotero 全库与三次网络检索（含精确题名）中均无任何条目或全文，无法核对其内容；
同作者 2024 年期刊文《低碳背景下混合车队车辆路径优化研究》（`4U7I5H4P`）为静态单车场模型，
全文“动态”只出现 4 次且均在文献综述，不能替代。
**改法（三选一，须用户定）**：
- (a) 补齐原文：拿到该学位论文 PDF 后重核这 8 处——这是唯一能保住现有写法的路；
- (b) 换引用：动态触发策略改引 `ref:18`（李阳等 2022，滚动时域分时间片＋子问题连续优化，已核实）
  或 `ref:51`（姜广田等 2024，预优化＋动态调整两阶段，已核实），表 1 该行随之换成对应文献并重核五格；
- (c) 删除：删掉 ref:71 的三处正文引用与表 1 该行，动态阶段的“保留既有成本＋重规划待执行任务”
  与“定时定量联合批处理”改按本文自述写（本来也可以是本文自己的设定）。

---

## 六、核验方法与可复现信息

- Zotero 条目均在本机库中实读；PDF 由 `pdftotext -layout` 抽取到
  `<scratchpad>/audit1/*.txt` 后按页定位（页号即 PDF 页，中文期刊另注明刊印页码）。
- 政策文件用官方门户实取；`ref:wlw2026` 的官方页只挂附件、无正文，正文引文取自第三方全文镜像，
  已在表中注明——若期刊要求，可改为引用附件 PDF 的落地链接。
- `ref:94`、`ref:deng`、`ref:52`、`ref:49`、`ref:14`、`ref:71` 本地无 PDF：
  前五条用 CrossRef/OpenAlex/Semantic Scholar/TRID/出版方摘要取证（表中已注明证据强度），
  `ref:71` 完全未找到。
