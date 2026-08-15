# 时变电网碳强度下的混合车队动态配送路径优化模型及算法

英文标题待定。正文2.1节首次出现的问题全称为：时变电网碳强度下的动态多车场混合车队多趟车辆路径问题（Dynamic Multi-depot Mixed-fleet Multi-trip Vehicle Routing Problem with Time-varying Grid Carbon Intensity，GCI-DMM-VRP）。

> 作者工作稿说明（投稿前删除）：本文仍处于结果回填前的内容稿阶段。算法正式名称、正式参数、代表解、对比结果、机制结果和时变碳实验记账范围均以方括号占位，不由本稿预先决定。

## 摘要

在交通运输低碳转型背景下，电动配送车辆的运行阶段虽不产生尾气排放，但其充电排放随用电时段的电网碳强度变化。油电混合车队的车型指派、实体车辆的多趟衔接和订单动态到达，又共同限定了可调整的充电与发车窗口。针对这一问题，本文提出时变电网碳强度下的动态多车场混合车队多趟车辆路径问题（GCI-DMM-VRP），统一优化客户服务、车型指派、实体车多趟排班、充电时刻和动态发车决策，并以运营成本与碳价折算排放之和作为单一目标。根据问题结构，本文构建一条以成熟混合遗传搜索为基础、依次嵌入公开算例族针对性改进与完整问题导向算子的串行求解链。数值实验从中国城市群算例的最终解、公开算例求解质量、算法组件作用、充电时刻、车型指派和动态发车六个方面展开。结果显示【待回填：算法求解质量与计算代价】；充电时刻、车型指派和动态发车实验分别得到【待回填：不预设方向、幅度或单调性的实测结果】。研究为企业统筹配送成本与碳成本、为管理部门评估碳价和电网信息在配送调度中的作用提供量化依据。

关键词：时变电网碳强度；混合车队；动态需求；多车场；多趟车辆路径；混合遗传搜索

## Abstract

Electric delivery vehicles produce no tailpipe emissions during operation, but their charging emissions vary with the grid carbon intensity at the time of electricity use. Vehicle-type assignment, multi-trip schedules of physical vehicles, and dynamically arriving requests further restrict feasible charging and dispatch windows. This study formulates the dynamic multi-depot mixed-fleet multi-trip vehicle routing problem with time-varying grid carbon intensity (GCI-DMM-VRP). The model jointly determines customer service, vehicle-type assignment, multi-trip schedules, charging times, and dynamic dispatch decisions, and minimizes a single monetary objective consisting of operating cost and carbon-priced emissions. A serial solution framework is constructed on a mature hybrid genetic search, with benchmark-family-oriented kernel improvements followed by problem-oriented operators for the full GCI-DMM-VRP. The numerical experiments examine the final solution on Chinese city-cluster instances, benchmark solution quality, algorithmic components, charging-time decisions, vehicle-type assignment, and dynamic dispatch. The results show 【to be filled: solution quality and computational cost】. The three operational experiments yield 【to be filled: observed results without prespecifying direction, magnitude, or monotonicity】. The study provides quantitative support for corporate cost-and-carbon decisions and for policy evaluation of carbon prices and grid information in distribution operations.

Keywords: time-varying grid carbon intensity; mixed fleet; dynamic demand; multi-depot; multi-trip vehicle routing; hybrid genetic search

## 1 引言

《2030年前碳达峰行动方案》提出推动运输工具装备低碳转型，建设绿色高效交通运输体系[[1]](https://www.gov.cn/zhengce/content/2021-10/26/content_5644984.htm)。这一政策要求落实到城市配送环节，既要扩大新能源车辆应用，也要回答车辆在何时充电、企业是否愿意采用低碳调度以及碳价能否改变经营选择等具体问题。本文因此把企业可核算的运营账与配送作业阶段排放放入同一优化目标，用人民币成本呈现经营结果，并另列排放量供政策评价。

从车辆路径问题的理论脉络看，经典车辆路径问题研究车场、客户与车辆之间的服务组织[[2]](https://doi.org/10.1287/mnsc.6.1.80)。本文沿四个方向扩展这一基本结构：车队维度由单一车型扩展为油电混合车队，空间维度由单车场扩展为多车场，时间维度由单趟静态路线扩展为实体车多趟与动态重规划，环境维度则把充电时刻对应的电网碳强度纳入路线评价。由此形成的问题不是若干独立机制的简单叠加，而是路线、车型、实体车排班和充电时刻共用同一可行解的组合优化问题。

城市群与区域配送中，物流企业需要在多个车场之间组织车辆、客户与补能资源。电动车在运行阶段不产生尾气排放，但配送任务仍对应充电用电产生的间接排放；若以单一日均排放因子核算全部充电电量，调度时刻与排放之间的联系便无法体现。Miyabe等的算例还显示，补能绕行可能改变电动车配送的排放表现[[3]](https://doi.org/10.1016/j.est.2025.117626)。因此，电动车的使用比例、充电时刻和实际配送组织需要在同一作业边界内核算。

电网碳强度的日内波动使同一笔充电电量在不同时刻具有不同的间接排放。围绕这一特征，充电调度研究已经形成较为系统的结论。Li等基于大规模电动车运行数据量化了有序充电的减排潜力[[4]](https://doi.org/10.1016/j.trd.2024.104383)。Cheng等在车辆可用时段、站端功率容量与电池状态约束下研究了碳感知充电策略[[5]](https://doi.org/10.1109/SmartGridComm52983.2022.9960988)。这类研究回答了“何时充电”，其共同前提是车辆的出行计划外生给定，充电时刻可在车辆闲置期内自由安排。在配送场景中，该前提并不成立：车辆何时闲置、闲置多久，恰恰是路径与排班决策的结果。

混合车队路径研究关注燃油车与电动车在载重、续航、能耗与固定成本上的差异如何改变车队配置。Goeke和Schneider建立了燃油车—电动车混合车队路径模型，并以载重与行驶状态刻画能耗[[6]](https://doi.org/10.1016/j.ejor.2015.01.049)。李得成等研究了带时间窗混合车队的车型配置与路径联合决策[[7]](https://doi.org/10.12011/SETP2019-1371)。陈婉茹等在多配送中心场景下分析了车队配置、路径与速度的联合优化[[8]](https://doi.org/10.12011/SETP2022-2971)。这些研究表明可用车队结构决定了成本与排放的可行空间，但其排放核算多以固定排放因子为基础。当充电侧排放随时刻变化时，增加电动车名额能否转化为实际派遣，以及车型结构变化与充电时刻变化各自贡献多少减排，需要在统一核算口径下重新辨析。

动态车辆路径研究关注信息逐步揭示条件下的实时调度。Gendreau等较早采用并行禁忌搜索处理实时车辆路径与调度问题[[9]](https://doi.org/10.1287/trsc.33.4.381)。姜广田等针对绿色物流中的多车型动态车辆路径问题比较了不同调整策略[[10]](https://doi.org/10.12011/SETP2023-0524)。在多车场多趟场景中，配送趟的生成还须与实体车辆的日内衔接相协调。Zhen等对带释放时间的多车场多趟问题进行了系统建模[[11]](https://doi.org/10.1016/j.tre.2020.101866)。对本文问题而言，动态重规划不仅要更新待服务客户集合，还须继承车辆位置、最早可用时刻、剩余载重、剩余电量以及已经发生的成本与排放，否则新计划可能撤回已执行任务或重复占用同一辆实体车。

复杂物流问题的建模经验表明，可按“问题描述—模型构建—算法设计—数值实验”组织多类现实约束。陈雨蝶等在双碳背景下将多中心、时变路网与多类配送约束纳入同一冷链物流模型[[12]](https://doi.org/10.12011/SETP2024-2027)。就本文关注的问题而言，时变电网碳强度、油电混合车队与动态需求均已有各自的研究基础，但现有研究通常分别处理充电、车型与动态调度，尚缺少面向多车场实体车多趟执行过程的统一比较。

由此可以归纳出两点研究不足。其一，混合车队、多车场、实体车多趟、硬时间窗以及车场与公共充电站两类补能点通常分散在不同模型中，难以用同一成本和排放口径比较。其二，充电研究常在给定行程后优化充电，而配送车辆的可用充电窗口实际由路线和多趟排班共同形成。电价与电网碳强度在日内的变化还可能并不一致，具体关系需要由中国分时电价和中国时变碳强度数据共同检验。

针对上述问题，本文提出GCI-DMM-VRP并建立日内滚动优化模型。模型区分燃油车行驶直接排放与电动车充电间接排放，以实体车辆而非配送趟计取固定成本，要求同一辆车相邻配送趟之间时间与电量连续，并使充电窗口由车辆到场与离场时刻内生确定。动态事件发生后，模型冻结已执行路径前缀，仅对尚未执行的客户与可用车辆重规划。求解方面，本文采用一条可逐项解释和消融的串行改进链；其正式名称和算子组合在算法定型后回填。

本文的工作体现在三个方面。第一，建立同时考虑时变电网碳强度、混合车队、多车场、实体车多趟与动态需求的统一模型，使静态计划与动态执行共用同一套车辆状态和成本排放核算。第二，基于中国真实OSM点位、冻结路网、中国分时电价和中国时变电网碳强度构造数值实验，分别考察充电时刻、车型指派和动态发车，不预设三个实验的结果方向。第三，在成熟混合遗传搜索基础上，分别面向公开算例族改进搜索内核、面向完整GCI-DMM-VRP加入串行问题导向算子，并通过同机等墙钟比较与逐组件消融检验其作用。

## 2 问题描述与模型

### 2.1 问题描述

考虑一个由多个车场、若干客户和公共充电站组成的区域配送系统。每个车场拥有数量有限的燃油车和电动车，每辆实体车具有唯一所属车场，可在一个运营日内完成一趟或多趟配送任务。客户具有需求量、服务时间和硬时间窗；每个客户由一辆车完整服务一次。车辆完成一趟任务后可以返回允许的车场补能并继续执行后续任务。多车场在模型中用于定义车辆初始位置、所属关系、车队上限和客户分配，不单独形成一项机制实验。

电网碳强度与电价按离散时段给定。燃油车排放由实际燃油消耗计算，电动车排放由各时段充电量与该时段电网碳强度的乘积计算。规划者需要同时决定客户—路线关系、实体车及车型、各车的多趟顺序、充电地点与开始时刻。运营过程中，新订单、取消或改量事件逐步出现；每次重规划均继承当前车辆状态，已经完成、已经发车或正在执行的路径前缀不可撤回。

以某城市群配送企业的日常运营为例，企业在若干物流园区设置车场，同时使用燃油轻卡与纯电动轻卡。车辆上午完成一轮配送后，可回场补能并在下午继续执行任务；运营中还可能收到新增、取消或改量订单。管理者需要在客户时间窗、车辆容量、电量和有限车队约束下，同时安排客户归属、车型、路线、多趟衔接、充电和重规划。据此构造匿名企业运营场景并建立如下模型。

模型采用以下基本假设：1）在每个决策时刻，已出现订单、路网、车辆和碳强度信息已知；2）客户需求不可拆分，且服务一次完成；3）车辆满足载重、硬时间窗和运营时域约束；4）实体车辆数量有限，固定成本按实际启用的实体车计取，与该车执行的配送趟数无关；5）电动车允许部分充电，采用SOC相关的分段充电功率；6）车场和公共充电站的容量约束按设施配置设置；7）动态重规划不重复结算已发生的成本和排放。

### 2.2 符号说明

为避免符号表被非主线组件占据，表1只列进入正文模型的集合、参数、状态和决策变量。投稿排版时可按期刊版面拆成双栏符号表。

| 类别 | 符号 | 含义 | 单位或取值域 |
|---|---|---|---|
| 集合 | $D,N,S,T,K$ | 车场、客户、充电设施、电网时段、实体车辆集合 | — |
| 集合 | $K_d,K^E,K^F$ | 车场$d$所属车辆、电动车、燃油车集合 | — |
| 集合 | $\Omega_k$ | 实体车$k$的可行日排班模式集合；一个模式可含多趟 | — |
| 路网参数 | $d_{ij},t_{ij}$ | 节点$i$至$j$的距离与行驶时间 | km，min |
| 客户参数 | $q_i,[e_i,l_i],s_i$ | 客户需求、时间窗和服务时长 | kg，min |
| 车辆参数 | $Q_k,B_k,b_k^{\min},P_s,C_s$ | 载重上限、电池容量、最低允许电量、充电功率和可用接口数 | kg，kWh，kW，个 |
| 时序参数 | $\gamma_t,p^e_{s,t}$ | 时段$t$的电网碳强度与站点$s$电价 | kgCO$_2$e/kWh，元/kWh |
| 能耗参数 | $\lambda^F$ | 燃油排放因子 | kgCO$_2$e/L |
| 成本参数 | $c_k^{\mathrm{fix}},c_k^{\mathrm{km}},p^F,p^{\mathrm{car}}$ | 实体车固定成本、里程成本、油价和单位碳价 | 相应单位 |
| 路线变量 | $x_{ijr},a_{ir}$ | 趟$r$是否使用弧$(i,j)$、是否服务客户$i$ | 0–1 |
| 状态变量 | $L_{ir},T_{ir},b_{ir}$ | 离开节点$i$时的载重、服务时刻和电量 | kg，min，kWh |
| 充电变量 | $Y_{ir},Y_q,h_q,\Delta_q,y_{qt},O_{skpt}$ | 节点补电量、会话总电量、开始/持续时间、分时段电量和并发会话数 | kWh，min，个 |
| 模式变量 | $A_{ikp},D_{kp},F_{kp}$ | 模式$p$是否覆盖客户$i$、总里程和总油耗 | 0–1，km，L |
| 模式变量 | $z_{kp},u_k$ | 车辆$k$是否选择模式$p$、车辆$k$是否启用 | 0–1 |
| 动态状态 | $o_k^\tau,t_k^\tau,\ell_k^\tau,b_k^\tau$ | 时刻$\tau$车辆位置、最早可用时刻、剩余载重和电量 | — |

### 2.3 能耗、充电与时变碳排放核算

在给定行驶速度的条件下，车辆逐弧能耗可写为距离与载重的函数。为与当前实现保持线性可计算性，采用物理功率模型在固定速度下的约化形式：

$$
e^E_{ij,k}=(\alpha_{0k}^E+\alpha_{1k}^E L_{ir})d_{ij},\qquad k\in K^E,
$$

$$
f^F_{ij,k}=(\alpha_{0k}^F+\alpha_{1k}^F L_{ir})d_{ij},\qquad k\in K^F,
$$

其中，$e^E_{ij,k}$和$f^F_{ij,k}$分别为电动车电耗和燃油车油耗。系数【待按正式车型参数、单位与能耗模型回填】。载重相关能耗结构参照Goeke和Schneider[[6]](https://doi.org/10.1016/j.ejor.2015.01.049)。

电动车允许部分充电。设会话$q$发生于站点$s(q)$，额定功率为$P_{s(q)}$，SOC相关功率比例为$\eta(b)$，其与电网时段$t$的重叠时长为

$$
g_{qt}=\left[\min\{h_q+\Delta_q,\bar T_t\}-\max\{h_q,\underline T_t\}\right]_+,
$$

则该时段充电量由$P_{s(q)}\eta(b)$在重叠区间内积分得到，并满足$\sum_{t\in T}y_{qt}=Y_q$。部分充电建模参考Keskin和Çatay[[13]](https://doi.org/10.1016/j.trc.2016.01.013)。充电站容量约束参考Froger等[[14]](https://doi.org/10.1287/trsc.2021.1111)。车场额定功率依据中国物流场站配置取60 kW。SOC—功率曲线形状参考Montoya等图8并按60 kW峰值缩放[[15]](https://doi.org/10.1016/j.trb.2017.02.004)。

对实体车$k$的排班模式$p$，燃油车直接排放和电动车充电侧间接排放分别为

$$
E_{kp}^{F}=\lambda^F\sum_{r\in\mathcal R_{kp}}\sum_{(i,j)\in r}f^F_{ij,k},
$$

$$
E_{kp}^{E}=\sum_{q\in\mathcal Q_{kp}}\sum_{t\in T}\gamma_ty_{qt}.
$$

配送作业阶段总排放为

$$
E^{\mathrm{sys}}=\sum_{k\in K}\sum_{p\in\Omega_k}(E_{kp}^{F}+E_{kp}^{E})z_{kp}.
\tag{1}
$$

式（1）核算燃油车行驶直接排放与电动车充电间接排放。充电时刻、车型指派和动态发车分别设置实验；三类实验之间是否形成统一规律，由正式结果回填。

### 2.4 目标函数与约束

运营成本由实体车固定成本、里程成本、燃油成本和充电电费构成：

$$
C^{\mathrm{op}}=
\sum_{k\in K}c_k^{\mathrm{fix}}u_k+
\sum_{k\in K}\sum_{p\in\Omega_k}
\left(c_k^{\mathrm{km}}D_{kp}+p^FF_{kp}+\sum_{q\in\mathcal Q_{kp}}\sum_{t\in T}p^e_{s(q),t}y_{qt}\right)z_{kp}.
\tag{2}
$$

其中，$D_{kp}$和$F_{kp}$分别为模式$p$的总里程和总油耗。固定成本按启用的实体车计取，故定义

$$
u_k=\sum_{p\in\Omega_k}z_{kp},\qquad \sum_{p\in\Omega_k}z_{kp}\le 1.
\tag{3}
$$

在当前单目标实现口径下，以单位碳价把排放纳入统一目标：

$$
\min Z=C^{\mathrm{op}}+p^{\mathrm{car}}E^{\mathrm{sys}}.
\tag{4}
$$

数值实验分别报告运营成本、碳价折算成本和配送作业阶段总排放。

每个客户由一个实体车排班模式恰好覆盖：

$$
\sum_{k\in K}\sum_{p\in\Omega_k}A_{ikp}z_{kp}=1,\qquad i\in N,
\tag{5}
$$

其中$A_{ikp}=1$表示模式$p$服务客户$i$。每个模式内部的配送趟满足起讫、流守恒、载重和时间窗约束：

$$
\sum_jx_{ijr}=\sum_jx_{jir}=a_{ir},\qquad i\in N,
\tag{6}
$$

$$
0\le L_{ir}\le Q_k,\qquad
L_{jr}\le L_{ir}-q_j+M(1-x_{ijr}),
\tag{7}
$$

$$
e_i a_{ir}\le T_{ir}\le l_i+M(1-a_{ir}),\qquad
T_{jr}\ge T_{ir}+s_i+t_{ij}-M(1-x_{ijr}).
\tag{8}
$$

电动车电量沿弧传播，并在允许地点补能：

$$
b_k^{\min}\le b_{ir}\le B_k,\qquad
b_{jr}\le b_{ir}+Y_{ir}-e^E_{ij,k}+M(1-x_{ijr}),\qquad k\in K^E,
\tag{9}
$$

客户点不允许补电，即$Y_{ir}=0$（$i\in N$）；补电只可发生于车场或已登记公共充电站。

对同一实体车的相邻配送趟$r\rightarrow r'$，要求前一趟返回后才能开始后一趟，且电量连续：

$$
T_{d^+_{r'}r'}\ge T_{d^-_rr}+\sum_{q\in\mathcal Q_{kp}^{rr'}}\Delta_q,\qquad
b_{d^+_{r'}r'}=b_{d^-_rr}+\sum_{q\in\mathcal Q_{kp}^{rr'}}Y_q.
\tag{10}
$$

充电站在任一时段的并发会话数不得超过其可用接口数$C_s$：

$$
\sum_{k\in K}\sum_{p\in\Omega_k}O_{skpt}z_{kp}\le C_s,
\qquad s\in S,\ t\in T.
\tag{11}
$$

式（11）同时适用于车场与公共充电站。多车场车型上限和总车队规模直接作用于实体车辆集合$K_d$，候选生成、排班补全和最终检查使用同一套上限。

设第$m$次重规划时刻为$\tau_m$。有效待服务客户集合按已服务、取消和新增事件更新：

$$
N^{\tau_m}=\left(N^{\tau_{m-1}}\setminus N_{\mathrm{served}}^{\tau_m}\setminus N_{\mathrm{cancel}}^{\tau_m}\right)\cup N_{\mathrm{new}}^{\tau_m}.
\tag{12}
$$

车辆$k$继承状态$(o_k^{\tau_m},t_k^{\tau_m},\ell_k^{\tau_m},b_k^{\tau_m})$。已执行成本和排放分别累计为

$$
\bar C^{\tau_m}=\bar C^{\tau_{m-1}}+\Delta C^{\tau_{m-1}},\qquad
\bar E^{\tau_m}=\bar E^{\tau_{m-1}}+\Delta E^{\tau_{m-1}},
\tag{13}
$$

新一轮优化仅计算剩余问题，并将冻结路径前缀作为不可撤销约束。通过收缩集合与参数，本模型可退化为静态需求、单车场、单趟、纯燃油车队、纯电动车队或固定电网排放因子下的相应车辆路径问题。

## 3 算法设计

### 3.1 算法框架

GCI-DMM-VRP同时包含客户路径、车型选择、实体车日内多趟、充电排程和动态状态继承。为求解该问题，本文按一条串行改进链组织算法：公开侧围绕所采用的公开算例族改进独立HGS搜索内核，私有侧在同一控制流程中加入面向GCI-DMM-VRP的问题导向算子，并由完整模型统一评价候选。正式算法名称、搜索内核改动和问题导向算子待算法定型后回填。

该串行链始终读取同一算例、同一实体车上限和同一动态状态快照。路线层候选依次经过车型与车场调整、实体车多趟排班、充电排程和完整成本排放核算；未通过时间窗、容量、电量或车队上限检查的候选不进入种群。最终方案再由独立检查程序复核客户服务、车辆身份和状态连续性。

【图1占位：本文算法总体流程。实例与动态状态→HGS搜索内核→公开算例族针对性改进→车型/车场/路线串行联合改进→实体车多趟与充电补全→完整模型评价→独立验解→输出。】

### 3.2 算法步骤

**步骤1：构造状态快照与可行起点。** 静态阶段读取完整订单、车场、有限实体车队和碳强度序列；动态阶段读取式（12）—（13）定义的剩余客户与车辆状态。算法先构造一份通过完整模型检查的可行解。

**步骤2：执行HGS基础搜索。** 算法维护单一种群，通过选择、交叉、教育和多样性管理更新路线候选。HGS框架参考Vidal等[[16]](https://doi.org/10.1287/opre.1120.1048)。公开侧的具体搜索内核改动为【待算法定型后回填】。

**步骤3：串行执行问题导向改进。** 在同一子代上依次执行【待回填：车型/车场与路线联合改进】、【待回填：客户移动联合改进】及其他获批问题导向算子，每代只把串行链末端形成的候选送入完整评价。各部件的作用通过第4.3节逐项消融检验。

**步骤4：完成实体车排班与完整评价。** 将路线候选分配给具体实体车，按时间顺序衔接多趟，并补齐电量、充电会话、时变电价和时变碳排放。任何时间窗、容量、电量、充电接口或实体车上限违反均判为不可接受；只有通过完整评价的候选进入种群。

**步骤5：更新种群与在职最好解。** 通过完整评价的候选按适应度和多样性规则进入种群；若其目标值改善，则更新在职最好解。候选的完整目标值和可行性均由同一评价口径确定。

**步骤6：独立验解与动态滚动调用。** 算法终止后，独立检查最终解的客户唯一服务、车队、时间窗、载重、电量和充电约束。事件触发时冻结已执行前缀，更新式（12）—（13）的车辆状态，再对剩余问题重复步骤1—5。

算法间比较在同一台净机上采用相同墙钟预算，并同时报告目标值、实际运行时间和完成代数。正式墙钟长度先由本算法在相应算例和机器上的长预算收敛曲线标定，再用于对比实验。

## 4 数值实验设计与算法有效性

### 4.1 算例设置与最终解分析

#### 4.1.1 算例与参数设置

本文使用中国城市群构造算例开展复杂模型实验。客户位置基于中国OpenStreetMap道路与设施点位构造[[17]](https://www.openstreetmap.org)。道路距离和行驶时间由冻结的OSM/OSRM路网计算[[18]](https://doi.org/10.1145/2093973.2094062)。订单属性参考Zhang开放数据的分布形状，08:00—11:00和13:00—19:00两个作业时段由该数据说明迁移[[19]](https://doi.org/10.6084/m9.figshare.28113608.v1)。本文的客户点、车场组合与班次订单均为构造仿真输入。

【表1占位：算例、事件流与碳日历。列：对象；规模/范围；来源或生成规则；固定版本/种子；在4.1、4.3、5.1—5.3中的用途。】

车辆采用中国4.5 吨级轻型物流车参数。电动车规格参考总质量4495 kg的福田欧马可智蓝ES1官方产品资料[[20]](https://aumark.foton.com.cn/profile/upload/2025/08/08/%E6%AC%A7%E9%A9%AC%E5%8F%AF%E6%99%BA%E8%93%9DES1%E5%8D%95%E9%A1%B5-NEW_20250808124334A003.pdf)。更换电池成本参考长江证券（2024）的100 kWh轻卡测算[[21]](https://reportify-1252068037.cos.ap-beijing.myqcloud.com/media/production/s_0232f12d_0232f12d70229944881f25f11df9ebfa.pdf)。电池行驶寿命参考Goeke和Schneider（2015）[[6]](https://doi.org/10.1016/j.ejor.2015.01.049)。据此将电池折旧费设为0.2445 元/km。电动车固定成本溢价参考陈婉茹等（2023）表7的油电车辆固定成本差额，设为50 元/车日[[8]](https://doi.org/10.12011/SETP2022-2971)。

充电设施设计参照GB/T 50966—2024，额定输出按场站供电能力与服务车辆充电需求确定[[22]](https://xxgk.qinshui.gov.cn/xzf/qsnyj/fdzdgknr/gzdt/202508/t20250825_2190036.shtml)。参考咸宁市新能源汽车充（换）电设施专项规划及物流场站实际配置，设置车场充电功率为60 kW[[23]](https://fgw.xianning.gov.cn/xxgk/fdzdgknr/ghjh/202301/P020250303636637394908.pdf)。分时电价采用算例所在地2025年工商业分时电价表，具体来源在表2逐项列示。电网碳强度采用Li等（2026）发布的S1-2025省级逐小时情景投影数据，并将每个小时值复制到两个半小时积分槽，形成48行存储表示[[24]](https://doi.org/10.1038/s41597-026-07272-6)。算法参数由收敛曲线标定确定。

【表2占位：模型与算法参数。列：参数/符号；数值与单位；适用决策层；来源及页码/数据版本；证据类型；最终处置。】

#### 4.1.2 最终解分析

为展示模型如何形成可执行的日配送方案，本节选取预先登记的代表实例，对正式算法输出的最终解作逐项分析。代表实例、种子和解的提取规则均在结果生成前确定。

【图2占位：代表实例的节点分布与路线。面板(a)节点分布；面板(b)路线及车型。】

【表3占位：代表解实体车排班。列：实体车；所属车场；车型；趟链/客户序列；各趟发车—返回；充电地点—开始时刻—电量；服务客户数；完成需求量；里程；油/电耗；直接/充电排放；运营成本。】

1）从成本构成看，最终解的人民币运营成本为【待回填】元，碳价折算成本为【待回填】元，单目标总账为【待回填】元；车辆固定成本、里程成本、燃油成本和电费分别为【待回填】元。

2）从服务与资源使用看，最终解完成【待回填】个客户、完成需求量【待回填】kg，启用【待回填】辆燃油车和【待回填】辆电动车，共执行【待回填】趟、行驶【待回填】km；未服务客户数和未完成需求量均为【待回填】。

3）从可执行性看，客户唯一服务、硬时间窗、车辆容量、实体车多趟衔接、最低SOC和充电接口约束的复核结果分别为【待回填】。同一辆车相邻两趟的返回、补能和再次发车关系见表3。

4）从能源与排放看，燃油车油耗、电动车充电量、燃油车直接排放和电动车充电排放分别为【待回填】；各充电会话的开始时刻、电量和SOC变化见表3。

综上，图2和表3给出最终解的成本、服务量、车辆使用、时间衔接和能源排放明细；该解中各结构是否产生性能或机制效应，由后续对比实验回答。

### 4.2 公开算例上的求解质量

公开算例实验用于回答本文搜索内核在标准问题上的求解质量与计算代价。实验采用预先登记的公开算例族，比较已发表方法、冻结HGS参照和本文算法。各算法在同一台净机上使用相同墙钟预算，表中同时报告运行时间和完成代数；墙钟长度由收敛标定确定。Vidal等的算例与混合遗传算法为公开比较提供基准[[25]](https://doi.org/10.1016/j.cor.2012.07.018)。

【表4占位：公开算例求解质量。列：算例；公开最好值及版本；已发表方法；冻结HGS；本文Best/Avg；相对差距；运行时间；完成代数；可行运行数。】

由表4可知，本文算法在【待回填算例数】个公开算例上的解质量、运行时间和完成代数分别为【待回填】。与已发表方法和冻结HGS相比的逐例结果为【待回填：包括改善、持平或变差】。综上，本节对公开算例的求解表现作出【待回填】评价。

### 4.3 算法组件贡献分析

为识别问题导向组件是否改变完整GCI-DMM-VRP的求解表现，本节以“只看路线”的基础臂为参照，在同一条串行链上按预先登记顺序逐个加入获批组件。各臂使用同一实例、初始解、随机种子和同机等墙钟预算，并同时报告终值、运行时间、完成代数和完整可行率。

【表5占位：串行组件消融。列：算法臂；新增组件；Best；Avg；相对基础臂变化；运行时间；完成代数；完整可行运行数。】

【图3占位：各算法臂收敛过程。横轴为实际运行时间，纵轴为在职最好完整目标值；正式预算取曲线进入平台期后留有余量的位置。】

由表5可知，逐项加入组件后，目标值、完成代数和完整可行率分别发生【待回填：改善、持平或变差】；图3显示各臂在搜索过程中的【待回填】。综上，各组件是否形成可重复的增益由表5和图3的正式结果判定。

## 5 机制实验与分析

本章分别考察充电时刻、车型指派和动态发车。三节均报告人民币成本、完成客户数、完成需求量、车辆与趟次、燃油车直接排放和电动车充电排放。时变碳实验采用充电侧账还是全系统总账作为主判定口径，待记账范围确定后回填；两种分项均保留在结果表中。

### 5.1 充电时刻层

充电时刻实验用于回答：当路线、车型和充电量固定时，不同充电规则是否改变人民币总账和排放。本节比较有空即充、电费最省和碳感知三种策略；三者使用相同排班、充电地点、充电量和可行窗口。

【表6占位：固定排班下的三种充电策略。列：策略；完成客户数；完成需求量；可移动电量；电费；碳价折算成本；充电侧账；全系统总账；充电排放；系统排放；配对变化。】

【图4占位：时变碳强度、电价与充电响应。面板(a)横轴为30分钟积分槽；碳强度以24个逐小时值的阶梯线展示，电价以分时类别的阶梯线展示，不能标成48个独立观测；面板(b)横轴相同，纵轴为三种策略的分时充电量。】

表6和图4显示，三种策略在充电开始时刻、分时电量、人民币账和排放上的差异为【待回填：允许改善、持平、反转或零动作】。综上，在本算例与参数下，调整充电时刻产生【待回填】结果。

### 5.2 车型指派层

车型指派实验用于回答：在各车场具有有限但充足的油电车辆上限时，模型实际选择何种车型组合，以及该组合对应怎样的成本与排放。本节固定订单、路网、车辆参数、充电规则和算法预算，只比较预先登记的车队参数类；每一档同时报告可用名额和实际派遣数量。

【表8占位：车队可用结构与实际车型指派。列：可用CV/EV；实际派遣CV/EV；实体车数；固定成本；油耗成本；电耗成本；总运营成本；配送作业阶段总排放；未服务/不可行/搜索未找到状态。】

表8显示，各参数类下实际派遣的燃油车与电动车数量、人民币成本和排放为【待回填：包括纯油、混合、纯电或未找到可行解】。综上，车型构成是否改变及其变化方向由正式结果确定。

### 5.3 发车时机层

动态发车实验用于回答：在不知道未来订单的条件下，碳感知在线策略相对机械在线策略是否改变服务、发车、充电、成本与排放。所有策略面对同一订单事件流、初始计划和车辆状态，已经执行的路径前缀冻结；完全信息静态方案只作理论参照。必要外包计入人民币成本，并与完成客户数和完成需求量一并报告。

【表9占位：代表动态事件与状态继承。列：事件时刻；事件类型/需求；触发时刻；待服务客户；车辆位置；剩余容量；剩余电量；最晚服务余量；冻结前缀；新增车辆。】

【图5占位：代表事件触发前后路线。统一坐标；面板(a)触发前；面板(b)触发后；区分冻结弧、未执行弧、新订单和虚拟起点。】

由表9和图5可知，事件发生后【A】条已执行弧保持不变，【B】条未执行路线被重组，车辆【C】的发车或充电窗口由【D】变为【E】。该展品用于证明滚动方案继承真实执行状态，而非从零重算全天计划。

【表10占位：动态发车策略完整日比较。列：策略；完成客户数/响应率；完成需求量；拒绝或外包订单；外包成本；实际车辆数；调整次数；里程；人民币总账；燃油直接排放；充电排放；运行时间。】

表9和图5记录状态继承与路线调整，表10给出机械在线策略和碳感知在线策略的服务量、人民币账与排放结果【待回填：允许改善、持平、反转或零动作】。综上，动态发车规则在本实验中的作用为【待回填】。

### 5.4 数值实验分析讨论

本节集中讨论第4章和第5章的数值实验结果。第一，结合表4、表5和图3回答搜索内核改进与问题导向组件分别带来何种解质量和计算代价【待回填】。第二，结合表6、表8和表10比较充电时刻、车型指派与动态发车的实测结果，不预先假定三者存在共同方向或层级规律【待回填】。第三，从企业角度比较人民币运营成本、碳价折算成本与服务量；从管理部门角度比较配送作业阶段排放及碳价情景下的决策变化【待回填】。第四，讨论模型退化为静态、单车场、单趟或单一车型情形时的适用关系【待回填】。

本文数值实验采用确定性路网时间和给定电网碳强度序列。中国OSM点位、开放订单属性和省级电网碳强度分别提供空间、订单与电网输入，组合形成构造仿真场景，参数表逐项列示各自来源。算法表现、机制结果和管理启示均在正式数据产生后据表图回填。综上，本文能够支持的讨论范围为【待回填】。

## 6 结语

本文研究时变电网碳强度下的动态多车场混合车队多趟车辆路径问题，建立同时考虑有限油电车队、实体车多趟、充电排程和动态状态继承的单目标模型，并以运营成本与碳价折算排放之和核算人民币总账。在成熟HGS基础上，本文按一条串行链组织公开算例族搜索内核改进和完整问题导向算子。数值实验所得算法表现、最终解特征、三类机制结果与管理启示分别为【待正式结果回填】。

后续研究可从以下方面展开：

1）引入随机行驶时间与动态订单预测，研究不确定信息下的滚动调度；

2）纳入电网碳强度预测误差，比较预测值与结算值偏差对调度结果的影响；

3）结合企业车场运行记录、车辆充电日志和实测SOC—功率曲线，对模型参数与算例进行进一步校准。

## 参考文献

[1] 国务院. 2030年前碳达峰行动方案[EB/OL]. 2021-10-26. https://www.gov.cn/zhengce/content/2021-10/26/content_5644984.htm

[2] Dantzig G B, Ramser J H. The truck dispatching problem[J]. *Management Science*, 1959, 6(1): 80–91. https://doi.org/10.1287/mnsc.6.1.80

[3] Miyabe R, Fujimoto Y, Hayashi Y. Low-carbon routing and charging planning for electric freight trucks utilizing local surplus solar power[J]. *Journal of Energy Storage*, 2025, 132: 117626. https://doi.org/10.1016/j.est.2025.117626

[4] Li Z, Chen Z, Li H, et al. On the value of orderly electric vehicle charging in carbon emission reduction[J]. *Transportation Research Part D: Transport and Environment*, 2024, 135: 104383. https://doi.org/10.1016/j.trd.2024.104383

[5] Cheng K W, Bian Y, Shi Y, et al. Carbon-aware EV charging[C]//2022 IEEE International Conference on Communications, Control, and Computing Technologies for Smart Grids. 2022: 186–192. https://doi.org/10.1109/SmartGridComm52983.2022.9960988

[6] Goeke D, Schneider M. Routing a mixed fleet of electric and conventional vehicles[J]. *European Journal of Operational Research*, 2015, 245(1): 81–99. https://doi.org/10.1016/j.ejor.2015.01.049

[7] 李得成, 陈彦如, 张宗成. 基于分支定价算法的电动车与燃油车混合车辆路径问题研究[J]. 系统工程理论与实践, 2021, 41(4): 995–1009. https://doi.org/10.12011/SETP2019-1371

[8] 陈婉茹, 徐光明, 张得志, 等. 碳交易机制下多中心混合车队配送路径和速度优化研究[J]. 系统工程理论与实践, 2023, 43(11): 3320–3335. https://doi.org/10.12011/SETP2022-2971

[9] Gendreau M, Guertin F, Potvin J Y, et al. Parallel tabu search for real-time vehicle routing and dispatching[J]. *Transportation Science*, 1999, 33(4): 381–390. https://doi.org/10.1287/trsc.33.4.381

[10] 姜广田, 纪皎月, 董佳伟. 绿色物流配送下的多车型动态车辆路径优化[J]. 系统工程理论与实践, 2024, 44(7): 2362–2380. https://doi.org/10.12011/SETP2023-0524

[11] Zhen L, Ma C, Wang K, et al. Multi-depot multi-trip vehicle routing problem with time windows and release dates[J]. *Transportation Research Part E: Logistics and Transportation Review*, 2020, 135: 101866. https://doi.org/10.1016/j.tre.2020.101866

[12] 陈雨蝶, 干宏程, 程亮, 等. 双碳背景下复杂冷链物流模型及求解算法[J/OL]. 系统工程理论与实践. https://doi.org/10.12011/SETP2024-2027

[13] Keskin M, Çatay B. Partial recharge strategies for the electric vehicle routing problem with time windows[J]. *Transportation Research Part C: Emerging Technologies*, 2016, 65: 111–127. https://doi.org/10.1016/j.trc.2016.01.013

[14] Froger A, Jabali O, Mendoza J E, et al. The electric vehicle routing problem with capacitated charging stations[J]. *Transportation Science*, 2022, 56(2): 460–482. https://doi.org/10.1287/trsc.2021.1111

[15] Montoya A, Guéret C, Mendoza J E, et al. The electric vehicle routing problem with nonlinear charging function[J]. *Transportation Research Part B: Methodological*, 2017, 103: 87–110. https://doi.org/10.1016/j.trb.2017.02.004

[16] Vidal T, Crainic T G, Gendreau M, et al. A hybrid genetic algorithm for multidepot and periodic vehicle routing problems[J]. *Operations Research*, 2012, 60(3): 611–624. https://doi.org/10.1287/opre.1120.1048

[17] OpenStreetMap contributors. OpenStreetMap[DB/OL]. https://www.openstreetmap.org

[18] Luxen D, Vetter C. Real-time routing with OpenStreetMap data[C]//*Proceedings of the 19th ACM SIGSPATIAL International Conference on Advances in Geographic Information Systems*. New York: ACM, 2011: 513–516. https://doi.org/10.1145/2093973.2094062

[19] Zhang J. A collaborative freight delivery problem with time windows under a crowdsourcing environment[J]. *PLOS ONE*, 2025, 20(2): e0318432. https://doi.org/10.1371/journal.pone.0318432；数据集：https://doi.org/10.6084/m9.figshare.28113608.v1

[20] 北汽福田汽车股份有限公司. 欧马可智蓝ES1产品资料[EB/OL]. 2025. https://aumark.foton.com.cn/profile/upload/2025/08/08/%E6%AC%A7%E9%A9%AC%E5%8F%AF%E6%99%BA%E8%93%9DES1%E5%8D%95%E9%A1%B5-NEW_20250808124334A003.pdf

[21] 邬博华, 曹海花, 叶之楠. 经济性驱动，新能源轻重卡兑现爆发式增长[R]. 长江证券研究所, 2024: 5.

[22] 中华人民共和国住房和城乡建设部. GB/T 50966—2024 电动汽车充电站设计标准[S]. 2024: 7–8.

[23] 咸宁市发展和改革委员会. 咸宁市新能源汽车充（换）电设施专项规划（2022—2035年）[R]. 2022: 23, 84.

[24] Li Y, Zhang S, Li W, et al. High temporal and spatial resolution projected electricity carbon emission factors of China from 2025–2060[J]. *Scientific Data*, 2026, 13: 926. https://doi.org/10.1038/s41597-026-07272-6

[25] Vidal T, Crainic T G, Gendreau M, et al. A hybrid genetic algorithm with adaptive diversity management for a large class of vehicle routing problems with time-windows[J]. *Computers & Operations Research*, 2013, 40(1): 475–489. https://doi.org/10.1016/j.cor.2012.07.018
