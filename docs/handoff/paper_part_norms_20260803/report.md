# NORM：中英文同类论文“逐部分行情”实测摘录

状态：15 篇全文可访问；中文 5 篇、外文 10 篇。中文既有页数、一级章节、机制、表、实验块、参考文献计数直接沿用 `journal_fullness_calibration_20260803/`，本轮不重算；六部分字段见下文。英文校样或作者版没有期刊页码时标为“PDF正文页”；Vidal 使用 CIRRELT 作者版的印刷页。只报摘录、章节结构、计数与样本区间，不作评价、排序、打分、推荐或样本外推断。

计数口径：约束组按作者的成组说明句计；有显式约束组标题时同时说明。实验“单因素分析节数”按有编号的小节计，同一小节内测试多个水平仍计 1 节。机制数沿用中文上游口径；外文按问题定义中相对基础 VRP 明示的机制逐项计。完整字段和页码见 `norms_by_part.json`。

## 1. 问题定义

| 论文 | 定义原句摘录＋位置 | 问题名称／缩写 | 名称中的定语（个数） |
|---|---|---|---:|
| 陈雨蝶等 2025 | “本文建立了考虑同时送取货和时变路网的绿色多隔间冷链物流模型（…MCTDGVRPSPD）”（§1 p.3） | 绿色多隔间冷链物流模型；MCTDGVRPSPD | 冷链、绿色/低碳、多中心、同时送取货、时变路网、多隔间、多产品、时间窗（8，§1 p.3；第2章 pp.4-7） |
| 姜广田等 2024 | “本文研究的绿色物流配送下的多车型动态车辆路径优化（…MVDVROGLD）与传统VRP不同”（§2.1 p.2364） | 绿色物流配送下的多车型动态车辆路径优化；MVDVROGLD | 绿色物流、多车型、动态（3，§2.1 p.2364） |
| 陈婉茹等 2023 | “进一步提出碳交易机制下由传统燃油车和电动车构成的混合车队的配送路径-速度联合优化问题”（§1 p.3321） | 碳交易机制下多中心混合车队配送路径和速度联合优化问题；无缩写 | 碳交易机制、多中心、混合车队、路径-速度联合优化（4，§1 pp.3321-3322） |
| 李得成等 2021 | “带时间窗的电动车与燃油车混合车队配送问题（…E-VRPTWMF）是EVRP与HVRP结合的一个扩展”（§1 p.996） | 带时间窗的电动车与燃油车混合车队配送问题；E-VRPTWMF | 电动车与燃油车混合、时间窗、混合车队（3，§1 p.996） |
| 饶卫振等 2019 | “协作配送问题是典型的组合优化合作博弈问题，也可称为协作车辆路径问题”（摘要 p.1517） | 协作配送成本分摊问题/协作车辆路径问题；第3章用 MOCVRP | 协作配送、成本分摊、核仁解（3，摘要及§1 pp.1517-1519） |
| Vidal et al. 2013 | “The VRPTW aims to construct up to m vehicle routes, to visit each customer vertex once within its time window, while minimizing the total distance.”（§2 CIRRELT印刷p.2） | generalized PVRPTW；覆盖 MDVRPTW、SDVRPTW | periodic、time windows（2，§2印刷pp.2-4） |
| Zhao et al. 2024 | “The MT-TD-VRP is defined over a directed graph G = (V, A).”（§3 p.922） | multi-trip time-dependent VRP；MT-TD-VRP | multi-trip、time-dependent（2，§1与§3 pp.921-923） |
| Schneider et al. 2014 | “In this paper, we introduce the electric vehicle routing problem with time windows and recharging stations (E-VRPTW).”（§1 p.2） | electric VRP with time windows and recharging stations；E-VRPTW | electric vehicle、time windows、recharging stations（3，§1 p.2） |
| Goeke & Schneider 2015 | “We propose the Electric VRP with Time Windows and Mixed Fleet (E-VRPTWMF) to determine optimal routes … for a given mixed fleet of ECVs and ICCVs.”（§1 PDF正文p.2） | Electric VRP with Time Windows and Mixed Fleet；E-VRPTWMF | electric、time windows、mixed fleet（3，§1正文p.2） |
| Montoya et al. 2017 | “The E-VRP-NL is defined on a directed and complete graph G=(V,A).”（§2.1 PDF正文p.4） | electric VRP with nonlinear charging functions；E-VRP-NL | electric vehicle、nonlinear charging（2，§1-2正文pp.3-4） |
| Froger et al. 2022 | “In this paper we introduce the E-VRP-NL with capacitated CSs (E-VRP-NL-C).”（§1 PDF正文p.3） | E-VRP-NL with capacitated CSs；E-VRP-NL-C | electric vehicle、nonlinear charging、capacitated CSs（3，§1正文p.3） |
| Hiermann et al. 2016 | “The Electric Fleet Size and Mix Vehicle Routing Problem with Time Windows and Recharging Stations (E-FSMFTW) consists of finding admissible tours for vehicles of different types…”（§2 p.997） | E-FSMFTW | electric、fleet size and mix、time windows、recharging stations（4，§1-2 pp.995-997） |
| Zhen et al. 2020 | “In this paper, we define the above problem as a multi-depot multi-trip vehicle routing problem with time windows and release dates (Multi-D&T VRPTW-R).”（§1 PDF p.2） | Multi-D&T VRPTW-R | multi-depot、multi-trip、time windows、release dates（4，§1 PDF p.2） |
| Wang et al. 2023 | “The collaborative multidepot EV routing problem with time windows and shared charging stations (CMEVRPTW-SCS) is proposed and solved in this study.”（§1 PDF p.2） | CMEVRPTW-SCS | collaborative、multidepot、electric vehicle、time windows、shared CSs（5，§1 PDF p.2） |
| Wang et al. 2026 | “The study focuses on the vehicle charging station location selection and routing problem with partial recharging and shared fleets.”（§1 PDF p.2） | 无缩写 | CS location selection、routing、partial recharging、shared fleets（4，§1 PDF p.2） |

本部分样本区间：名称定语 2—8 个（n=15）；有缩写 13 篇、无缩写 2 篇（n=15）。来源为上表及 `ranges.json` 的 `part_1_problem_definition`。

## 2. 引言

| 论文 | 第一条贡献原文（如有，≤60词/字）＋位置 | 段落数 | 最后一段列编号创新点 | “研究不足”段及条数 |
|---|---|---:|---|---|
| 陈雨蝶等 2025 | “同时考虑冷链、时间窗、低碳、多中心、同时送取货、时变路网、多隔间、多产品等诸多因素建立复杂冷链物流模型”（p.3） | 8（§1 pp.2-3） | 是，4条（p.3；原文编号误将第4条再写为“3)”） | 有，2条（p.3） |
| 姜广田等 2024 | 无编号贡献列表 | 10（§1 pp.2363-2364） | 否 | 有，3条（p.2364） |
| 陈婉茹等 2023 | “构建决策混合车队路径方案与行驶速度的混合整数规划模型”（p.3322） | 6（§1 pp.3321-3322） | 是，3条（p.3322） | 有，3条（p.3322） |
| 李得成等 2021 | 无编号贡献列表 | 6（§1 pp.996-997，OCR保留段首） | 否 | 有，3条：充电站重复访问、客户时间窗、精确算法/管理意义（pp.996-997） |
| 饶卫振等 2019 | “构建考虑货物在配送中心调配的协作配送模型”（p.1519） | 10（§1 pp.1518-1519，OCR保留段首） | 是，2条（p.1519） | 有，2条：指数级约束/易错与核仁解仍难求（pp.1518-1519） |
| Vidal et al. 2013 | “a generalization of the concept of HGSADC to a large class of VRPTW variants”（§1印刷pp.1-2） | 4（§1印刷pp.1-2） | 否；贡献在倒数第2段列4条 | 有，2项不足（首段，印刷p.1） |
| Zhao et al. 2024 | 无编号贡献列表 | 6（§1 pp.921-922） | 否 | 无独立不足段；有2处非列表式不足陈述（pp.921-922） |
| Schneider et al. 2014 | 无编号贡献列表 | 9（§1 pp.1-3） | 否 | 无独立不足段，0条（§1 pp.1-3） |
| Goeke & Schneider 2015 | “Mixed fleet. We consider a mixed fleet composed of electric and conventional vehicles.”（§1正文p.2） | 7（§1正文pp.1-2） | 否；前文用2个非编号并列项 | 有，2项（正文pp.1-2） |
| Montoya et al. 2017 | “First, we introduce the electric vehicle routing problem with nonlinear charging functions (E-VRP-NL).”（§1正文p.3） | 11（§1正文pp.1-4） | 否；倒数第2段列5条 | 有，4项（正文pp.2-3） |
| Froger et al. 2022 | “First, we propose a mixed integer linear programming (MILP) formulation for the E-VRP-NL-C.”（§1正文p.4） | 13（§1正文pp.1-5） | 否；倒数第2段列2条 | 有，2项（正文pp.2-4） |
| Hiermann et al. 2016 | “We combine the streams of research on the EVRPTW and the FSMFTW and introduce a new vehicle routing problem”（§1.2 p.997） | 21（§1含§1.1-1.3，pp.995-997） | 否；§1.2有3个非编号贡献段 | 无独立不足段，0条（§1） |
| Zhen et al. 2020 | 无编号贡献列表 | 4（§1 PDF pp.1-2） | 否 | §1无；§2末有1条“不存在相关文献”，不计入引言（PDF p.3） |
| Wang et al. 2023 | 无编号贡献列表 | 4（§1 PDF pp.1-2） | 否 | §1无；§2.4末另列4条limitations，不计入引言（PDF pp.4-5） |
| Wang et al. 2026 | 无编号贡献列表 | 6（§1 PDF pp.1-2） | 否 | §1无；§2.4末另列4条challenges，不计入引言（PDF p.5） |

本部分样本区间：引言 4—21 段（n=15）；最后一段列编号创新点的论文 3 篇、未列 12 篇；引言内研究不足条数 0—4（n=15）。来源为上表及 `ranges.json` 的 `part_2_introduction`。

## 3. 模型章

| 论文 | 子节数与标题原文＋位置 | 目标函数项数 | 约束组数 | 可退化/包含经典问题原句 |
|---|---|---:|---:|---|
| 陈雨蝶等 2025 | 10：2.1 问题描述；2.2 目标函数；2.2.1-2.2.6 六类成本；2.3 时变速度函数；2.4 模型建立（pp.4-7） | 6项成本（§2.2 pp.4-6） | 10组（§2.4公式(15)-(25)说明，pp.6-7） | “设置配送中心数为1则适用于单中心VRP，设置隔间数为1则适用于单隔间VRP，设置取货量为0则适用于仅送货VRP”（§1 p.3） |
| 姜广田等 2024 | 7：2.1 问题描述；2.2 参数及变量定义；2.3 速度函数；2.4 油耗函数；2.5 数学模型；2.5.1 预优化阶段模型；2.5.2 动态调整策略与模型（pp.2364-2369） | 3项成本（§2.5 pp.2367-2369） | 数不清：两套模型无统一分组；预优化模型单独可数10组（§2.5.1 pp.2367-2368） | 未见（第2章） |
| 陈婉茹等 2023 | 6：2.1 问题描述和假设；2.2 符号说明；2.3 车辆能耗模型；2.4 数学模型；2.4.1 优化目标；2.4.2 模型约束（pp.3322-3325） | 3项成本（§2.4.1 p.3324） | 16组（§2.4.2式(6)-(26)说明，pp.3324-3325） | 未见（第2章） |
| 李得成等 2021 | 5：2.1 问题描述；2.2 模型参数及变量；2.3 数学模型；3.1 主问题模型；3.2 子问题模型（pp.997-999） | 2项：电动车、燃油车运输成本（§2.3 pp.997-998） | 14组（式(2)-(15)逐句说明，pp.997-998） | 未见（第2-3章） |
| 饶卫振等 2019 | 3：2.1 协作配送；2.2 协作配送的成本分摊；3 协作配送问题建模（pp.1519-1522） | 1项：协作配送总成本（第3章 p.1521） | 7组（式(2)-(15)成组说明，pp.1521-1522） | 未见（第3章） |
| Vidal et al. 2013 | 0个编号子节；§2整体建模（印刷pp.2-4） | 1项：total distance（印刷p.2） | 3组，作者原文“Three main groups…”（印刷p.3） | “The MDVRPTW … constitute[s] a special case of the generalized PVRPTW.”（§2印刷p.3） |
| Zhao et al. 2024 | 2：3.1 Time-dependent travel time model and function；3.2 Mathematical formulation（pp.922-924） | 2项（§3.2 pp.923-924） | 4组（式(2)-(18)说明，pp.923-924） | “the MTVRP … is a special case of the studied MT-TD-VRP”（§7.4 p.931；不在模型章） |
| Schneider et al. 2014 | 0个编号子节；§3整体建模（pp.4-6） | 2层目标：车辆数、距离（§3 p.5） | 5组（路线/流、时间、载重、电量、变量域，pp.5-6） | “The classical VRPTW represents a special case of E-VRPTW adequate for scenarios in which no recharges are necessary.”（§5.3.3 p.18） |
| Goeke & Schneider 2015 | 0个编号子节；§4整体建模（正文pp.4-6） | 3种目标版本，各含1/2/3项（§4正文pp.5-6） | 12组（约束(7)-(21)说明，正文pp.5-6） | “VRPTW and E-VRPTW, which are both special cases of the E-VRPTWMF”（§6.4正文p.15） |
| Montoya et al. 2017 | 4：2.1 Problem description；2.2 Modeling of battery charging functions；2.3 Illustrative example；2.4 MILP formulation（正文pp.4-8） | 2项：travel、charging time（§2.4正文p.7） | 15组（约束(2)-(38)说明，正文p.7） | “CVRP is a special case of our E-VRP-NL”（§3正文p.8） |
| Froger et al. 2022 | 0个编号子节；§3整体建模（正文pp.6-10） | 3项：driving、charging、waiting time（§3正文pp.7-9） | 20组（约束(2)-(42)说明，正文pp.8-9） | 未见（§3） |
| Hiermann et al. 2016 | 2：2.1 Mixed integer programming model；2.2 Set partitioning formulation（pp.997-999） | 主MIP 2项（§2.1 pp.997-998） | 主MIP 7组；§2.2另有3组（pp.997-999） | “It combines and subsumes the well known Fleet Size Mix Vehicle Routing Problem with Time Windows … and … E-VRPTW.”（§1 p.995） |
| Zhen et al. 2020 | 4：3.1 Problem description；3.2 Model formulation；3.2.1 Notations；3.2.2 Mathematical model（PDF pp.3-5） | 3个行程求和项（§3.2.2 PDF p.4） | 15组（式(2)-(20)说明，PDF p.5） | 未见（§3） |
| Wang et al. 2023 | 2：4.1 Assumptions and definitions；4.2 Model formulation（PDF pp.5-8） | 成本目标5项，另有EV数目标（§4.2 PDF pp.6-7） | 18个解释单元；显式标题3大组（PDF pp.7-8） | 未见（§4） |
| Wang et al. 2026 | 10：4.1；4.2；4.2.1-4.2.4；4.2.4.1-4.2.4.4，标题详见 `norms_by_part.json`（PDF pp.6-12） | 成本目标4项，另有NEV目标（§4.2.3 PDF pp.9-10） | 24个解释单元，分4个显式约束子节（§4.2.4 PDF pp.9-12） | 未见（§4） |

本部分样本区间：编号子节 0—10（n=15）；目标项 1—6（n=15）；约束解释组 3—24（n=14，姜广田等因两套模型无统一分组排除）；有经典问题退化/包含原句 7 篇、未见 8 篇。来源为上表及 `ranges.json` 的 `part_3_model`。

## 4. 算法章

| 论文 | 编号子节数＋位置 | 流程图 | 步骤写法 | 参数表 |
|---|---:|---|---|---|
| 陈雨蝶等 2025 | 2（§3.1-3.2 pp.7-10） | 有，图1 p.8 | 编号步骤1-8（§3.2 pp.8-10） | 无；时变速度参数表不是算法参数表（§4.1.1 pp.10-11） |
| 姜广田等 2024 | 6（§3.1、3.1.1-3.1.4、3.2，pp.2369-2372） | 有，图3 p.2372 | 流程图＋叙述（§3.1-3.2） | 无（第3章） |
| 陈婉茹等 2023 | 9（§3.1-3.9 pp.3325-3328） | 有，图1 p.3326 | 流程图＋叙述（第3章） | 无；表3是邻域结构、表7是模型参数 |
| 李得成等 2021 | 9（§4.1、4.2、4.2.1-4.2.2、4.3、4.3.1-4.3.3、4.4，pp.999-1003） | 有，图1 p.1000 | 流程图＋编号Step（pp.1000-1002） | 无；参数在§5正文（pp.1003-1005） |
| 饶卫振等 2019 | 5（§5.1-5.5 pp.1524-1528） | 有，图4 p.1526 | 流程图＋编号Step（§5.3 pp.1525-1527） | 无（§5.5） |
| Vidal et al. 2013 | 10（§4.1-4.7含§4.5.1-4.5.3，印刷pp.8-15） | 无；Algorithm 1是伪代码（p.7） | 编号伪代码＋叙述 | 无汇总表；Table 1为参数组合表现（§5.1 pp.16-17） |
| Zhao et al. 2024 | 10（§4-6，pp.924-929） | 无 | Algorithms 1-4编号伪代码＋叙述（pp.925-929） | 有，Table 2 p.930 |
| Schneider et al. 2014 | 4（§4.1-4.4 pp.6-10） | 无；Figure 1为伪代码overview（p.7） | 伪代码＋叙述 | 有，Table 4 p.11 |
| Goeke & Schneider 2015 | 8（§5.1-5.4含§5.4.1-5.4.4，正文pp.6-9） | 有，Figure 2 p.6 | 流程图＋叙述 | 有，Table 3正文p.10 |
| Montoya et al. 2017 | 6（§3.1-3.6，正文pp.8-13） | 无 | 主文叙述；附录Algorithm 1编号伪代码 | 有，Table 2正文p.15 |
| Froger et al. 2022 | 7（§4.1-4.2及5个下级子节，正文pp.10-20） | 无 | Algorithms 1-9编号伪代码＋叙述 | 有，Table 4正文p.22 |
| Hiermann et al. 2016 | 18（精确算法§3共5个标题、启发式§4共13个，pp.999-1005） | 无 | Algorithms 1-2编号伪代码＋叙述 | 有，Table 1 p.1004 |
| Zhen et al. 2020 | 13（§4.1-4.2及11个下级子节，PDF pp.5-11） | 无；Figures 3-7为表示/算子图 | 叙述＋项目列表 | 无；§5.1正文给参数，Table 1非参数表（PDF p.11） |
| Wang et al. 2023 | 10（§5.1-5.3及7个下级子节，PDF pp.8-16） | 有，Figure 2 p.9 | 流程图＋Algorithms 1-3 | 有，算法参数表PDF p.16 |
| Wang et al. 2026 | 8（§5.1-5.3及5个下级子节，PDF pp.12-20） | 有，Figure 3 p.12 | 流程图＋Algorithms 1-2 | 有，Table 7 p.20、Table 12 p.25 |

本部分样本区间：编号子节 2—18（n=15）；有流程图 8 篇、无流程图 7 篇；有算法参数汇总表 8 篇、无 7 篇。来源为上表及 `ranges.json` 的 `part_4_algorithm`。

## 5. 实验章

### 5.1 每篇实验子节标题原文

| 论文 | 实验子节标题原文＋位置 |
|---|---|
| 陈雨蝶等 2025 | 4.1 实验设计和最终解分析；4.1.1 实验设计；4.1.2 最终解分析；4.2 算法有效性分析；4.2.1 CVRP标准算例实验；4.2.2 MCTDGVRPSPD模型实验；4.3 碳交易机制分析；4.4 不同决策目标对比分析；4.5 不同配送模式对比分析；4.6 不同速度函数对比分析；4.7 独立送取货和同时送取货对比分析；4.8 使用单隔间和多隔间车辆对比分析；4.9 数值实验分析讨论（第4章 pp.10-21） |
| 姜广田等 2024 | 4.1 实验1:21个店铺；4.2 实验2:60个店铺；5.1 调整策略分析；5.2 算法分析（第4-5章 pp.2372-2378） |
| 陈婉茹等 2023 | 4.1 基准测试算例实验；4.2 仿真算例实验；4.2.1 算例及参数说明；4.2.2 算例求解结果；5.1 车队动力配置；5.2 碳交易机制；5.2.1 碳交易机制对配送方案的影响；5.2.2 碳交易机制对派遣车辆的影响；5.3 速度优化（第4-5章 pp.3328-3333） |
| 李得成等 2021 | 5.1 较小规模算例求解；5.2 较大规模算例求解；5.3 灵敏度分析；5.3.1 电动车/燃油车可用数量；5.3.2 电动车/燃油车最大载重；5.3.3 电池容量与充电率（第5章 pp.1003-1008） |
| 饶卫振等 2019 | 6.1 AIA求解协作配送问题核仁解；6.2 AIA求解策略的有效性；6.3 AIA与传统方法的比较（第6章 pp.1528-1533） |
| Vidal et al. 2013 | 5.1 Parameter calibration；5.2 Comparison of performances；5.3 Sensitivity analysis on method components（§5印刷pp.15-23） |
| Zhao et al. 2024 | 7.1 Effectiveness of the MQO technique；7.2 Parameter tuning；7.3 Results on CVRP；7.4 Comparison on MTVRP instances；7.5 Case study: Singapore food and beverage company data；7.5.1 Comparison of initialization methods using different clustering algorithms；7.5.2 Performance on sub-sampled small cases instances compared with Gurobi；7.5.3 Effect of changing parameters in constraints on MT-TD-VRP（§7 pp.929-934） |
| Schneider et al. 2014 | 5.1 Experimental Environment and Parameter Setting；5.2 Experiments on E-VRPTW Instances；5.2.1 Generation of E-VRPTW Benchmark Instances；5.2.2 Performance of VNS/TS on Small E-VRPTW Instances；5.2.3 Analyzing the Effect of the VNS/TS Components；5.3 Performance on Benchmark Instances of Related Problems；5.3.1 Multidepot VRP with Interdepot Routes；5.3.2 Green VRP；5.3.3 VRP with Time Windows（§5 pp.10-19） |
| Goeke & Schneider 2015 | 6.1 Experimental environment and parameter setting；6.2 Generation of E-VRPTWMF instances；6.3 Experiments on E-VRPTWMF instances；6.3.1 Influence of surrogate cost function；6.3.2 Effect of considering distribution of load on solution quality；6.3.3 Assessment of different objective functions and cost contribution；6.4 Performance on benchmark instances of related problems；6.4.1 Performance on VRPTW；6.4.2 Performance on E-VRPTW（§6正文pp.9-16） |
| Montoya et al. 2017 | 4.1 Test instances for E-VRP-NL；4.2 Benefits of better approximating charging function；4.3 Results of ILS+HC；4.3.1 Experimental environment；4.3.2 Parameter settings；4.3.3 Performance of hybrid metaheuristic；4.3.4 Characteristics of good E-VRP-NL solutions（§4正文pp.13-18） |
| Froger et al. 2022 | 5.1 Results for the E-VRP-NL-C formulation；5.2 Results for the E-VRP-NL；5.3 Results for the E-VRP-NL-C（§5正文pp.20-26） |
| Hiermann et al. 2016 | 5.1 E-FSMFTW benchmark instances；5.2 Results on small E-FSMFTW instances；5.3 Results on larger E-FSMFTW instances；5.4 Sensitivity analysis of the E-FSMFTW instances（§5 pp.1004-1011） |
| Zhen et al. 2020 | 5.1 Parameters setting；5.2 Performance of the HPSO and the HGA；5.3 Experiments on algorithm settings（§5 PDF pp.11-15） |
| Wang et al. 2023 | 6.1 Algorithm comparison；6.2 Data description；6.3 Optimization results；6.3.1 Clustering results；6.3.2 Vehicle routing optimization with shared charging stations；6.3.3 Profit allocation results；6.4 Analysis and discussion；6.4.1 Comparison of various collaboration mechanisms；6.4.2 Comparison of various alliances with or without shared CSs；6.5 Management insights（§6 PDF pp.17-27） |
| Wang et al. 2026 | 6.1 Data description；6.2 Parameter stability and sensitivity analysis；6.3 Clustering results；6.4 Optimization results；6.5 Analysis and discussion；6.5.1 Comparison of optimization results under different recharging levels；6.5.2 Comparison of optimization results under different resource sharing models；6.5.3 Comparison of different collaboration modes；6.6 Management insights（§6 PDF pp.20-31；算法比较另在§5.3 pp.18-20） |

### 5.2 指定计数

| 论文 | 子节总数 | 算法有效性占几节 | 单因素分析占几节 | 最终解详细拆解 | 集中讨论节 | 机制数 ↔ 单因素节数 |
|---|---:|---:|---:|---|---|---|
| 陈雨蝶等 2025 | 13（第4章） | 2：4.2.1-4.2.2 | 6：4.3-4.8 | 有，4.1.2 | 有，4.9 | 8 ↔ 6（§1 p.3；§4） |
| 姜广田等 2024 | 4（第4-5章） | 1：5.2 | 1：5.1 | 有，4.1-4.2路线表 | 有，第5章 | 8 ↔ 1（§1 p.2364；§4-5） |
| 陈婉茹等 2023 | 9（第4-5章） | 1：4.1；4.2.2内另有未成节的算法消融 | 4：5.1、5.2.1、5.2.2、5.3 | 有，4.2.2 | 无 | 6 ↔ 4（§1-2；§4-5） |
| 李得成等 2021 | 6（第5章） | 2：5.1-5.2 | 3：5.3.1-5.3.3 | 无 | 无 | 7 ↔ 3（§2；§5） |
| 饶卫振等 2019 | 3（第6章） | 2：6.2-6.3 | 0 | 有，6.1表2 | 无 | 5 ↔ 0（§3-5；§6） |
| Vidal et al. 2013 | 3（§5） | 1：5.2 | 1：5.3 | 无 | 无 | 5 ↔ 1（§2；§5） |
| Zhao et al. 2024 | 8（§7） | 4：7.1、7.3、7.4、7.5.2 | 2：7.5.1、7.5.3 | 无 | 无 | 2 ↔ 2（§1/3；§7） |
| Schneider et al. 2014 | 9（§5） | 4：5.2.2、5.3.1-5.3.3 | 1：5.2.3 | 无 | 无 | 4 ↔ 1（§1/3；§5） |
| Goeke & Schneider 2015 | 9（§6） | 3：6.3.1、6.4.1-6.4.2 | 3：6.3.1-6.3.3 | 无 | 无 | 5 ↔ 3（§1/4；§6） |
| Montoya et al. 2017 | 7（§4） | 1：4.3.3 | 1：4.2 | 无；4.3.4为全部BKS汇总 | 无 | 5 ↔ 1（§2；§4） |
| Froger et al. 2022 | 3（§5） | 3：5.1-5.3 | 1：5.3 | 无；Table 8为多解汇总 | 无 | 5 ↔ 1（§2；§5） |
| Hiermann et al. 2016 | 4（§5） | 2：5.2-5.3 | 1：5.4 | 无 | 无 | 4 ↔ 1（§1/2；§5） |
| Zhen et al. 2020 | 3（§5） | 1：5.2 | 1：5.3 | 无 | 无 | 4 ↔ 1（§1/3；§5） |
| Wang et al. 2023 | 10（§6） | 1：6.1 | 2：6.4.1-6.4.2 | 有，6.3.2-6.3.3 | 有，6.4 | 5 ↔ 2（§1-3；§6） |
| Wang et al. 2026 | 9（§6） | 1：5.3（算法章末） | 4：6.2、6.5.1-6.5.3 | 有，6.4表15/图14 | 有，6.5 | 6 ↔ 4（§3-4；§5-6） |

本部分样本区间：编号实验子节 3—13（n=15）；算法有效性 1—4 节（n=15）；单因素分析 0—6 节（n=15）；机制 2—8 个（n=15）；有最终解详细拆解 6 篇、无 9 篇；有集中讨论节 4 篇、无 11 篇。来源为上表及 `ranges.json` 的 `part_5_experiments`。机制数与单因素节数只逐篇并列，不据此推断应当一一对应。

## 6. 结论

| 论文 | 管理启示原句（如有，≤60词/字）＋位置 | 段落数 | 是否含管理启示；对象类别 |
|---|---|---:|---|
| 陈雨蝶等 2025 | “政府应完善碳交易机制，在合理区间内采取高价格高配额策略”（§4.9 p.21） | 2（§5 p.21） | 有；企业、政府（§4.9及§5 p.21） |
| 姜广田等 2024 | “合理选择配送路径可以降低物流成本，提高资源利用率，减少碳排放”（§6 p.2378） | 2（§6 pp.2378-2379） | 有；其他：物流运营 |
| 陈婉茹等 2023 | “政府实行限额碳交易政策只能初步推进新能源车辆在物流配送中的使用”（§6 p.3333） | 5（§6 pp.3333-3334） | 有；企业、政府 |
| 李得成等 2021 | “当企业配置的电动车容量较小时应优先选择快充模式”（§6 p.1008） | 2（§6 p.1008） | 有；企业 |
| 饶卫振等 2019 | 无 | 3（§7 p.1533） | 无 |
| Vidal et al. 2013 | 无 | 3（§6印刷p.24） | 无 |
| Zhao et al. 2024 | 无 | 2（§8 p.934） | 无 |
| Schneider et al. 2014 | “our method seems able to successfully assist routing and recharging decisions for ECVs employed in real-world delivery operations”（§6 p.19） | 4（§6 p.19） | 有；企业、其他：运输市场/绿色物流 |
| Goeke & Schneider 2015 | 无 | 3（§7正文pp.16-17） | 无 |
| Montoya et al. 2017 | 无 | 2（§5正文p.18） | 无 |
| Froger et al. 2022 | 无 | 2（§6正文p.26） | 无 |
| Hiermann et al. 2016 | 无 | 4（§6 pp.1010-1011） | 无 |
| Zhen et al. 2020 | 无；§5.2有企业观察但结论未写管理启示 | 2（§6 PDF pp.15-16） | 无 |
| Wang et al. 2023 | “the collaborative mechanism and the CS sharing strategy should be encouraged to construct sustainable and economic logistics networks”（§7 PDF p.27） | 4（§7 PDF pp.27-28） | 有；企业、政府、其他：系统/方法；另有§6.5三条管理启示 |
| Wang et al. 2026 | “Governments can promote collaboration by planning shared charging infrastructure to improve utilization”（§6.6 PDF p.31） | 3（§7 PDF pp.31-34） | §7本身无条目；§6.6单列管理启示，企业、政府、其他：多主体/智能技术 |

本部分样本区间：结论 2—5 段（n=15）；结论或紧邻的专设管理启示节含管理启示 7 篇、未含 8 篇。Wang et al. 2026 的启示位置是 §6.6，不是 §7。来源为上表及 `ranges.json` 的 `part_6_conclusion`。

## 全文访问情况与停止状态

指定外文 10 篇均取得全文；中文 5 篇沿用已核全文并补齐六部分字段。本轮不可访问全文为 0 篇，未用摘要补齐。状态：`PART_NORMS_COMPLETE`。
