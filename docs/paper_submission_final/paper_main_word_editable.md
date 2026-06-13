% 兼顾收益公平与时变碳强度的动态协同多车场混合车队路径优化

周雷习书, 干宏程, 邱莹莹

上海理工大学 管理学院, 上海 200093

**摘要**  在动态城市配送中，电网碳强度的时段差异会通过电动汽车充电决策影响油电混合车队协同调度，同时多车场协同还需兼顾车场间收益公平。本文研究考虑动态需求、时变电网碳强度和收益公平的协同多车场混合车队车辆路径问题，构建以系统总运营成本最小化为目标、以车场协同收益公平下界为约束的优化模型，综合刻画共享车辆池、客户跨车场分配、车场间调拨、共享充电站容量、非线性部分充电、电动汽车充电侧间接碳排放和碳配额惩罚等机制。针对新增、取消及需求变化三类动态事件，设计定量–定时联合触发的滚动重规划机制，并在冻结已执行路径的基础上继承车辆位置、时间、载重、电量、充电站占用和已产生碳排放状态。求解部分暂保留与模型相匹配的算法接口骨架，包括阶段输入输出、可行性检查、动态状态继承和结果评价口径，具体主算法将在后续版本中确定。数值实验从算法有效性、静态基准、车型反事实、机制消融、碳强度与碳配额敏感性、收益公平阈值敏感性和动态滚动重规划等维度验证模型与算法的有效性。

**关键词**  协同多车场; 混合车队; 车辆路径问题; 动态需求; 时变电网碳强度; 收益公平

# Dynamic Collaborative Multi-depot Mixed-fleet Vehicle Routing with Profit Fairness and Time-varying Grid Carbon Intensity

ZHOU Leixishu, GAN Hongcheng, QIU Yingying

University of Shanghai for Science and Technology, Shanghai 200093, China

**Abstract**  In dynamic urban distribution, time-varying grid carbon intensity
affects mixed-fleet collaborative routing through electric-vehicle charging
decisions, while multi-depot collaboration must also maintain acceptable profit
fairness among depots. This paper studies a collaborative multi-depot mixed-fleet
vehicle routing problem with dynamic demand, time-varying grid carbon intensity
and profit fairness. A constrained optimization model is formulated to minimize
total system operating cost subject to lower-bound constraints on collaborative
depot-profit fairness. The model
integrates a shared vehicle pool, cross-depot customer assignment, inter-depot
transshipment, shared charging-station capacity, nonlinear partial recharging,
indirect emissions from electric-vehicle charging and carbon-quota penalties.
For order additions, cancellations and demand changes, a quantity–time triggered
rolling replanning mechanism is designed, where executed route segments are
frozen and vehicle locations, times, loads, battery states, charging-station
occupation and accumulated emissions are inherited. The solution section
currently keeps a minimal algorithmic interface skeleton, including stage-level
inputs and outputs, feasibility checks, dynamic state inheritance and
result-evaluation interfaces, while the final main algorithm will be determined
in a later version. Numerical experiments are organized to verify algorithmic
performance, static benchmark behavior, vehicle-type counterfactuals, mechanism
ablations, carbon-intensity and quota sensitivities, profit-fairness threshold
sensitivity and dynamic replanning continuity.

**Keywords**  collaborative multi-depot; mixed fleet; vehicle routing problem;
dynamic demand; time-varying grid carbon intensity; profit fairness

# 引言

2020年9月22日，中国提出二氧化碳排放力争2030年前达峰、2060年前实现碳中和[1]。在“双碳”目标和能源结构转型背景下，交通运输领域减排约束持续加强[2]。全球能源相关二氧化碳排放压力仍受到持续关注[3]。城市配送是交通运输的重要末端环节，既需要满足订单时效，也需要在车辆使用、能源消耗和碳排放之间取得平衡。

从车型结构看，燃油车补能便利、续航稳定，但运行过程直接碳排放较高；电动汽车运行成本较低、行驶阶段无尾气排放，但其减排效果受充电时段电网碳强度和充电设施可用性影响[4]。已有国际混合车队路径研究考虑了不同补能方式、车辆容量和时间窗约束[5]。国内电动车与燃油车混合车队研究进一步讨论了车型配置与路径优化问题[6]。但多数研究仍以静态需求为前提，对动态订单扰动下的电动车充电时刻和间接碳排放关注不足。

从组织方式看，多车场协同能够通过客户共享、车辆共享和车场间调拨降低系统成本，但也可能使个别车场收益被削弱。协同多车场电动车路径研究为客户跨场服务和共享充电站建模提供了基础[7]。收益公平研究说明多车场协同时需关注各参与方的利润保持水平[8]。协同物流收益分配研究进一步讨论了合作运输中的成本分摊和补贴稳定性[9]。最小补贴下的稳定公平分配为协同机制设计提供了另一类参考[10]。跨车场路径研究揭示了车场间路径连接对多车场VRP结构的影响[11]。容量受限充电站研究为共享充电设施约束提供了建模依据[12]。充电桩排队与时间窗研究说明充电设施容量会影响电动车路径可行性[13]。但现有研究较少同时刻画共享车辆池、共享充电站容量、碳配额惩罚和车场收益公平之间的联动关系。

从需求环境看，实际城市配送存在订单新增、取消和需求变更等动态事件。动态VRP经典研究指出，实时车辆路径需要随新信息滚动更新[14]。逆向物流协同配送研究展示了动态路径优化在城市配送中的应用[15]。两级车辆路径研究进一步讨论了动态度和时间窗约束[16]。动态客户需求下的协同网络设计说明需求扰动会影响配送网络结构[17]。周期性优化模型体现了将动态问题分批转化为阶段问题的处理思路[18]。中断情景下的取件路径研究说明动态扰动会改变路径可执行性[19]。随机需求精确算法研究为需求不确定性下的路径求解提供了参考[20]。冷链动态需求研究强调了需求变化对配送路径的影响[21]。实时车辆路径调度研究则说明在线调度需要快速更新可行方案[22]。然而，在油电混合车队和多车场协同背景下，动态重规划不仅要更新客户集合，还需继承车辆位置、时间、载重、电量、充电站占用和已产生碳排放等状态，否则容易出现路径不可执行或碳配额重复核算问题。

综上，现有研究仍存在以下不足：一是混合车队路径优化多以静态需求为前提，较少考虑订单新增、取消和需求变化下的状态继承；二是电动汽车充电侧间接碳排多作为结果统计，较少嵌入车型选择、充电时刻和路径决策；三是多车场协同研究多关注系统成本下降，对车场间收益公平关注不足。基于此，本文围绕"动态城市配送中，时变电网碳强度如何通过充电决策影响混合车队协同调度，同时保证车场收益公平"这一主线展开研究。

本文主要贡献如下：1) 构建考虑动态需求、时变电网碳强度和收益公平的协同多车场混合车队路径模型，将共享车辆池、客户跨车场分配、车场间调拨和共享充电站容量纳入统一框架；2) 将电动汽车充电侧间接碳排、碳配额惩罚和分时电网碳强度嵌入车型选择、充电时刻和车场协同决策，使低碳因素进入优化过程而非仅作为事后统计；3) 设计面向动态事件的定量–定时滚动重规划机制，并保留与后续求解算法衔接的状态继承、可行性核验和结果评价接口；4) 通过算法有效性、机制消融、碳强度情景、碳配额敏感性、收益公平阈值敏感性和动态重规划实验验证模型与算法的有效性。

# 问题描述及模型建立

## 问题描述与假设

本文研究动态城市配送环境下的协同多车场混合车队路径优化问题。配送网络由车场、客户、共享充电站和道路弧段构成，车辆包括燃油车和电动车两类。客户具有需求量、服务时间和硬时间窗；电动车可在配送途中访问共享充电站进行补能，充电过程服从充电站给定的非线性充电函数；充电产生的间接碳排放由充电时段对应的电网碳强度决定。若系统设置碳排放配额，则实际排放与可用配额之间的差额按照碳交易价格计入成本。配送执行过程中可能出现新增订单、订单取消和需求变化，因此本文采用滚动重规划方式处理动态需求。车辆能耗、碳交易、时变碳强度、非线性充电、协同多车场和收益公平等机制分别在后续模型中给出。

在重规划时刻 $\tau$，系统只优化尚未执行的配送任务。已经服务的客户、已经行驶的弧段、已经消耗的时间、载重、电量、成本和碳排放均不再调整，而是由执行日志转化为当前车辆状态和累计指标。设 $N^\tau$ 为时刻 $\tau$ 的有效待服务客户集合，则动态客户集合按下式更新：

$$
N^{\tau}=\left(N^{\tau-1}\setminus N_{\mathrm{ser}}^{\tau}\setminus N_{\mathrm{can}}^{\tau}\right)\cup N_{\mathrm{new}}^{\tau} .
$$

(1)

其中，$N_{\mathrm{ser}}^{\tau}$、$N_{\mathrm{can}}^{\tau}$ 和 $N_{\mathrm{new}}^{\tau}$ 分别表示上一轮已经服务、取消和新增的客户集合。对仍需服务且需求发生变化的客户，当前需求量按式 (2) 更新：

$$
q_i^\tau=
\begin{cases}
q_i^{\tau-1}+\Delta q_i^\tau, & i\in N^{\tau-1}\setminus N_{\mathrm{ser}}^{\tau}\setminus N_{\mathrm{can}}^{\tau},\\
q_i^{\mathrm{new}}, & i\in N_{\mathrm{new}}^{\tau}.
\end{cases}
$$

(2)

为界定研究范围，提出如下假设：1) 每个有效客户由一辆车一次服务；2) 车辆配送过程中不允许超载；3) 客户时间窗为硬时间窗，车辆可提前到达并等待，但服务开始时间不晚于右时间窗；4) 每辆车从滚动阶段继承位置出发，最终返回指定车场；5) 电动车可在共享充电站进行途中非线性部分补能，充电站同一时段可用充电桩数量有限；6) 燃油车碳排放来自燃油消耗，电动车碳排放来自充电电量与对应时段电网碳强度；7) 客户可由非原归属车场车辆服务，由此产生的跨车场调拨或结算成本计入目标函数；8) 行驶速度和时段电网碳强度作为外生参数，本文不涉及路径–速度联合优化和电源侧发电组成优化；若实验实际使用电源结构数据，则仅在数据预处理阶段计算时段电网碳强度；9) 碳成本采用限额碳交易口径，阶段可用碳配额记为 $CE^\tau$，其含义不同于历史已执行排放 $\bar E^\tau$；10) 数学模型刻画当前重规划阶段的优化问题，搜索算子、非线性充电构造过程和重规划触发规则在算法章节说明。

## 符号说明

模型主要符号见表 1。为保持正文可读性，车辆能耗中的物理常数和燃油折算系数在表中合并说明；所有成本均以 GBP 计量，电网碳强度单位为 kgCO$_2$/kWh。

表 1 主要符号说明

| 符号 | 含义 |
|---|---|
| $\tau,t$ | 滚动重规划时刻和离散充电时段索引 |
| $i,j,k,d,s$ | 节点、车辆、车场和充电站索引 |
| $D,N^\tau,S$ | 车场集合、时刻 $\tau$ 的有效待服务客户集合和共享充电站集合 |
| $K^\tau,K^{g,\tau},K^{e,\tau},K_d^\tau$ | 可用车辆集合、燃油车集合、电动车集合以及车场 $d$ 当前可调用车辆集合 |
| $T$ | 离散充电时段集合 |
| $V_k^\tau,\mathcal{A}_k^\tau$ | 车辆 $k$ 在时刻 $\tau$ 可访问节点集合和可行弧集合 |
| $o_k^\tau,h_k,d_i^0$ | 车辆 $k$ 的当前继承位置、最终返回车场和客户 $i$ 的原归属车场 |
| $q_i^\tau,\Delta q_i^\tau,R_i$ | 客户 $i$ 的当前需求量、需求变化量和服务收入 |
| $s_i,[e_i,l_i]$ | 客户 $i$ 的服务时间和服务时间窗，车场和充电站服务时间取 0 |
| $d_{ij},v_{ij}^\tau$ | 弧 $(i,j)$ 的距离和阶段 $\tau$ 给定行驶速度 |
| $Q_k,L_k^\tau,H_k$ | 车辆 $k$ 的载重容量、当前剩余载重能力和阶段最长工作时间 |
| $B_k,\underline B_k,\bar b_k^\tau$ | 电动车 $k$ 的电池容量、最低安全电量和当前剩余电量 |
| $\bar a_k^\tau$ | 车辆 $k$ 在时刻 $\tau$ 的当前时间 |
| $\Delta_t,[\underline T_t,\overline T_t)$ | 充电时段 $t$ 的长度及其对应时间区间 |
| $C_s,\phi_s(\cdot),\delta_{sk}^{\tau}$ | 充电站 $s$ 的可用充电桩数量、非线性充电函数和起点放行参数；若车辆 $k$ 在阶段 $\tau$ 的继承位置为充电站 $s$，则 $\delta_{sk}^{\tau}=1$，否则为 0 |
| $\gamma_t,\lambda^g$ | 时段 $t$ 的电网碳强度和单位燃油碳排放因子 |
| $c_k^{fix},c_k^{km}$ | 派遣车辆固定成本和非能源里程成本 |
| $p^f,p_t^e,p^{car},c_s^{occ}$ | 燃油价格、时段电价、单位碳交易价格和充电站 $s$ 的单位占用成本 |
| $CE^\tau$ | 重规划阶段 $\tau$ 对未执行配送部分分配或剩余的可用碳排放配额，单位 kgCO$_2$ |
| $c_{id}^{tr}$ | 客户 $i$ 由车场 $d$ 服务时的跨车场调拨或结算成本，单位 GBP/customer |
| $\bar Z^\tau,\bar E^\tau,\bar\Pi_d^\tau$ | 时刻 $\tau$ 前已经发生的累计成本、累计碳排放和车场 $d$ 已实现收益 |
| $\Pi_d^{0,\tau},\theta$ | 车场 $d$ 独立运营基准收益和收益公平比例下界参数；使用公平下界前需验证 $\Pi_d^{0,\tau}>0$ |
| $M$ | 足够大的正数 |
| $c_D,\rho^a,A_k,g_0,c_R,m_k$ | 空气阻力系数、空气密度、迎风面积、重力加速度、滚阻系数和车辆空重 |
| $\alpha_k^e,\beta_{0k}^g,\beta_{1k}^g$ | 电耗折算系数以及燃油消耗折算系数 |
| $P_{ijk}^\tau,e_{ijk}^\tau,f_{ijk}^\tau$ | 弧段牵引功率、电动车弧段电耗和燃油车弧段油耗 |
| $\Delta E^\tau,E^\tau,C_{\mathrm{car}}^\tau$ | 当前阶段新增碳排放、滚动累计碳排放和碳交易成本 |
| $C_d^\tau,\Pi_d^\tau$ | 当前阶段分摊至车场 $d$ 的运营成本和协同累计收益 |
| $x_{ijk}^\tau,z_k^\tau$ | 弧选择变量和车辆派遣变量 |
| $u_{ijk}^\tau,a_{ik}^\tau$ | 弧段载货量和节点开始服务时间；对充电站表示开始充电时间 |
| $b_{ik}^\tau$ | 电动车到达节点 $i$ 时的剩余电量 |
| $g_{skt}^\tau,\Delta_{sk}^{\tau}$ | 电动车在充电站 $s$、时段 $t$ 的实际充电占用时长和总充电时长 |
| $y_{skt}^\tau,\chi_{skt}^\tau$ | 电动车在充电站 $s$、时段 $t$ 的充电量和充电占用变量 |
| $h_{id}^\tau$ | 客户 $i$ 是否由车场 $d$ 的车辆服务 |

注：$h_k$（车辆 $k$ 的返回车场）与 $h_{id}^\tau$（客户 $i$ 是否由车场 $d$ 服务）含义不同，前者用于路径返场约束，后者用于收益归属与跨车场成本核算；衰减系数 $\alpha_T$ 与收益公平比例下界 $\theta$ 为不同参数。

## 车辆能耗与碳排放模型

车辆在弧段上以给定速度 $v_{ij}^\tau$ 匀速行驶，不考虑坡度和加减速。车辆 $k$ 通过弧 $(i,j)$ 时的牵引功率由速度、车辆空重和弧段载重共同决定：

$$
P_{ijk}^{\tau}=\frac{1}{2}c_D\rho^a A_k (v_{ij}^{\tau})^{3}+\left(m_k+u_{ijk}^{\tau}\right)g_0c_Rv_{ij}^{\tau},\qquad (i,j)\in \mathcal{A}_k^\tau .
$$

(3)

电动车在弧 $(i,j)$ 上的电耗为：

$$
e_{ijk}^{\tau}=\alpha_k^e P_{ijk}^{\tau}\frac{d_{ij}}{v_{ij}^{\tau}},\qquad k\in K^{e,\tau},\ (i,j)\in \mathcal{A}_k^\tau .
$$

(4)

燃油车在弧 $(i,j)$ 上的油耗为：

$$
f_{ijk}^{\tau}=\left(\beta_{0k}^g+\beta_{1k}^gP_{ijk}^{\tau}\right)\frac{d_{ij}}{v_{ij}^{\tau}},\qquad k\in K^{g,\tau},\ (i,j)\in \mathcal{A}_k^\tau .
$$

(5)

在本文固定行驶速度 $v_{ij}^{\tau}=v$ 设定下，式 (4) 可等价退化为按里程的线性电耗式，用于与实验参数表中的电耗参数对接：

$$
e_{ijk}^{\tau}=g_v d_{ij}+\omega^E u_{ijk}^{\tau}d_{ij},\quad
g_v=\alpha_k^e\left(\tfrac{1}{2} c_D\rho^a A_k v^{2}+m_k g_0 c_R\right),\quad
\omega^E=\alpha_k^e g_0 c_R .
$$

(6)

实验参数表中的空载电耗 $g_v$ 与载重电耗 $\omega^E$ 即由式 (6) 取定；燃油侧系数 $\beta_{0k}^g,\beta_{1k}^g$ 由发动机参数按 CMEM 油耗率折算。电动车整备质量 $m_k$ 的取值见实验参数表（占位待填）。

式 (3)–(5) 参照混合车队路径优化研究中的"载重–速度–能耗"建模方式[23]。与仅统计燃油车尾气排放的处理不同，本文将电动车充电产生的电力侧间接排放纳入配送碳排放。当前重规划阶段新增碳排放和滚动累计碳排放分别为：

$$
\Delta E^{\tau}=\lambda^g\sum_{k\in K^{g,\tau}}\sum_{(i,j)\in \mathcal{A}_k^\tau}f_{ijk}^{\tau}x_{ijk}^{\tau}+\sum_{k\in K^{e,\tau}}\sum_{s\in S}\sum_{t\in T}\gamma_t y_{skt}^{\tau},\qquad
E^{\tau}=\bar E^{\tau}+\Delta E^{\tau} .
$$

(7)

其中，$\bar E^{\tau}$ 为上一阶段已经执行路径继承下来的累计碳排放，$\Delta E^{\tau}$ 为当前阶段新增碳排放，二者均为排放统计量，区别于阶段可用碳配额。$\Delta E^{\tau}$ 由当前阶段燃油车直接排放和电动车充电间接排放组成。$\gamma_t$ 为外生给定的时段电网碳强度，单位为 kgCO$_2$/kWh，可由碳强度数据直接读取；仅当实验实际使用电源结构数据时，才在数据预处理阶段按各电源出力和排放因子加权计算 $\gamma_t$[24]，该计算不进入主优化模型。由于 $\gamma_t$ 随时段变化，电动车充电时段选择会直接影响碳排放和碳交易成本。

## 数学模型

### 优化目标

限额碳交易机制下，当前阶段新增排放与阶段可用配额的差额形成碳交易成本[23]：

$$
C_{\mathrm{car}}^{\tau}=p^{car}\left(\Delta E^{\tau}-CE^{\tau}\right).
$$

(8)

其中，$CE^\tau$ 表示重规划阶段 $\tau$ 分配给未执行配送部分的可用碳排放配额，或由总配额扣除已结算已执行部分后得到的剩余配额，其口径与当前阶段新增碳排放 $\Delta E^\tau$ 一致；$\bar E^\tau$ 为已执行路径累计碳排放，二者含义不同。当 $\Delta E^{\tau}>CE^{\tau}$ 时，式 (8) 表示购买额外碳配额产生的成本；当 $\Delta E^{\tau}<CE^{\tau}$ 时，该项为负，表示出售剩余配额获得的收益。

在重规划时刻 $\tau$，模型以系统滚动累计总成本最小为目标，收益公平要求通过式 (35) 约束体现：

$$
\begin{aligned}
\min Z^{\tau}=&\ \bar Z^{\tau}+\sum_{k\in K^\tau}c_k^{fix}z_k^{\tau}+\sum_{k\in K^\tau}\sum_{(i,j)\in \mathcal{A}_k^\tau}c_k^{km}d_{ij}x_{ijk}^{\tau}
+p^f\sum_{k\in K^{g,\tau}}\sum_{(i,j)\in \mathcal{A}_k^\tau}f_{ijk}^{\tau}x_{ijk}^{\tau}\\
&+\sum_{k\in K^{e,\tau}}\sum_{s\in S}\sum_{t\in T}p_t^e y_{skt}^{\tau}
+\sum_{k\in K^{e,\tau}}\sum_{s\in S}\sum_{t\in T}c_s^{occ}g_{skt}^{\tau}
+\sum_{i\in N^\tau}\sum_{d\in D}c_{id}^{tr}h_{id}^{\tau}
+C_{\mathrm{car}}^{\tau}.
\end{aligned}
$$

(9)

式 (9) 中，$\bar Z^\tau$ 是已执行部分累计成本，不影响当前决策但用于保持滚动结果可累计。车辆固定成本按派遣车辆计费，里程成本按车辆行驶距离计费且不含燃油、电费、充电占用成本和碳交易成本；燃油成本按燃油车油耗计费，电费按电动车实际充电量和充电时段电价计费，充电占用成本按电动车在共享充电站各时段的实际占用时长计费；跨车场成本按客户被实际服务车场计费，同车场服务可令 $c_{i,d_i^0}^{tr}=0$；碳交易成本按式 (8) 计入。若在对比实验中设置无碳交易情景，可令 $p^{car}=0$，但式 (7) 的碳排放统计仍予保留。

### 约束条件

每个有效待服务客户必须且只能被一辆车服务一次：

$$
\sum_{k\in K^\tau}\sum_{j\in V_k^\tau\setminus\{i\}}x_{jik}^{\tau}=1,\qquad i\in N^\tau .
$$

(10)

车辆若被派遣，则从当前继承位置出发：

$$
\sum_{j\in V_k^\tau\setminus\{o_k^\tau\}}x_{o_k^\tau jk}^{\tau}=z_k^\tau,
\qquad k\in K^\tau .
$$

(11)

被派遣车辆最终返回指定车场：

$$
\sum_{i\in V_k^\tau\setminus\{h_k\}}x_{ih_kk}^{\tau}=z_k^\tau,
\qquad k\in K^\tau .
$$

(12)

客户和充电站节点满足车辆流平衡：

$$
\sum_{j\in V_k^\tau\setminus\{i\}}x_{ijk}^{\tau}=\sum_{j\in V_k^\tau\setminus\{i\}}x_{jik}^{\tau},
\qquad i\in (N^\tau\cup S)\setminus\{o_k^\tau\},
\ k\in K^\tau .
$$

(13)

客户服务车场由实际服务车辆决定：

$$
h_{id}^{\tau}=\sum_{k\in K_d^\tau}\sum_{j\in V_k^\tau\setminus\{i\}}x_{jik}^{\tau},
\qquad i\in N^\tau,
\ d\in D .
$$

(14)

式 (10)–(14) 是经典 VRP 路径约束在协同多车场场景下的直接扩展，并与协同多车场配送中的客户跨场服务思想一致[7]。共享车辆池和资源共享口径与协同多车场时间依赖车辆路径研究保持一致[25]。客户不再被限定只能由原归属车场服务，但每辆车在阶段 $\tau$ 具有唯一收益归属车场，客户服务车场由进入该客户节点的实际车辆确定。

车辆到达客户后完成交付，载重随客户需求减少：

$$
\sum_{h\in V_k^\tau\setminus\{i\}}u_{hik}^{\tau}-\sum_{j\in V_k^\tau\setminus\{i\}}u_{ijk}^{\tau}=q_i^\tau\sum_{h\in V_k^\tau\setminus\{i\}}x_{hik}^{\tau},
\qquad i\in (N^\tau\cup S)\setminus\{o_k^\tau\},
\ k\in K^\tau .
$$

(15)

车辆在任意弧段上的载重不得超过容量：

$$
0\le u_{ijk}^{\tau}\le Q_kx_{ijk}^{\tau},
\qquad (i,j)\in \mathcal{A}_k^\tau,
\ k\in K^\tau .
$$

(16)

滚动阶段开始时，车辆后续可配送货量受继承剩余载重能力限制：

$$
\sum_{j\in V_k^\tau\setminus\{o_k^\tau\}}u_{o_k^\tau jk}^{\tau}\le L_k^\tau z_k^\tau,
\qquad k\in K^\tau .
$$

(17)

式 (15)–(17) 保证车辆不超载，并将滚动重规划时车辆的剩余载重状态带入当前阶段。车场和充电站作为零需求节点处理，即对充电站 $s\in S$ 取 $q_s^\tau=0$，式 (15) 在 $s$ 处退化为 $\sum_h u_{hsk}^{\tau}=\sum_j u_{sjk}^{\tau}$，故车辆访问这些节点不改变载重；继承起点 $o_k^\tau$ 的出发载重由式 (17) 单独约束。

车辆沿弧段行驶时，服务时间、行驶时间和充电占用时间共同决定后继节点开始服务时间：

$$
a_{jk}^{\tau}\ge a_{ik}^{\tau}+s_i+\frac{d_{ij}}{v_{ij}^{\tau}}+\sum_{t\in T}g_{ikt}^{\tau}-M\left(1-x_{ijk}^{\tau}\right),
\qquad (i,j)\in \mathcal{A}_k^\tau,
\ k\in K^\tau .
$$

(18)

为书写简洁，若 $i\notin S$，约定 $g_{ikt}^{\tau}=0,\ y_{ikt}^{\tau}=0$；当 $i\in S$ 时，$g_{ikt}^{\tau}$ 与 $g_{skt}^{\tau}(i=s)$ 对应，且 $y_{ikt}^{\tau}$ 与 $y_{skt}^{\tau}(i=s)$ 对应。

客户必须在时间窗内开始服务：

$$
e_i-M\left(1-\sum_{j\in V_k^\tau\setminus\{i\}}x_{jik}^{\tau}\right)\le a_{ik}^{\tau}\le l_i+M\left(1-\sum_{j\in V_k^\tau\setminus\{i\}}x_{jik}^{\tau}\right),
\qquad i\in N^\tau,
\ k\in K^\tau .
$$

(19)

车辆从当前继承时刻继续执行：

$$
a_{o_k^\tau k}^{\tau}=\bar a_k^\tau,
\qquad k\in K^\tau .
$$

(20)

车辆当前阶段工作时间不得超过上限：

$$
a_{h_kk}^{\tau}-\bar a_k^\tau\le H_k+M(1-z_k^\tau),
\qquad k\in K^\tau .
$$

(21)

式 (18)–(21) 是经典 VRPTW 时间约束的滚动重规划版本。已执行路段不会再次优化，当前车辆时间通过 $\bar a_k^\tau$ 继承。

电动车在当前阶段起点的剩余电量由执行日志给出：

$$
b_{o_k^\tau k}^{\tau}=\bar b_k^\tau,
\qquad k\in K^{e,\tau} .
$$

(22)

若电动车从节点 $i$ 行驶到节点 $j$，则到达 $j$ 时的电量由到达 $i$ 时电量、在 $i$ 处充电量和弧段耗电共同决定：

$$
b_{jk}^{\tau}\ge b_{ik}^{\tau}+\sum_{t\in T}y_{ikt}^{\tau}-e_{ijk}^{\tau}-M\left(1-x_{ijk}^{\tau}\right),
\qquad (i,j)\in \mathcal{A}_k^\tau,
\ k\in K^{e,\tau} .
$$

(23)

$$
b_{jk}^{\tau}\le b_{ik}^{\tau}+\sum_{t\in T}y_{ikt}^{\tau}-e_{ijk}^{\tau}+M\left(1-x_{ijk}^{\tau}\right),
\qquad (i,j)\in \mathcal{A}_k^\tau,
\ k\in K^{e,\tau} .
$$

(24)

其中，若 $i\notin S$，约定 $y_{ikt}^{\tau}=0$。

电动车到达任意访问节点时应满足安全电量要求：

$$
\underline B_k\sum_{j\in V_k^\tau\setminus\{i\}}x_{jik}^{\tau}\le b_{ik}^{\tau},
\qquad i\in V_k^\tau,
\ k\in K^{e,\tau} .
$$

(25)

电动车在节点补能后的电量不得超过电池容量：

$$
b_{ik}^{\tau}+\sum_{t\in T}y_{ikt}^{\tau}\le B_k,
\qquad i\in V_k^\tau,
\ k\in K^{e,\tau} .
$$

(26)

当电动车访问充电站 $s$ 时，每次充电对应一个实际充电区间。该区间由车辆到达时间、充电桩释放时间和充电持续时间共同确定，并按 $[\underline T_t,\overline T_t)$ 划分为各离散时段的占用时长 $g_{skt}^{\tau}$、占用变量 $\chi_{skt}^{\tau}$ 和充电量 $y_{skt}^{\tau}$。因此，充电占用时段与车辆路径时序一致；若车辆等待低碳时段后再充电，等待时间通过 $a_{sk}^{\tau}$ 进入式 (18) 的后续时间递推。具体构造方法在算法部分说明。

为刻画电动车充电过程的非线性特征，参照容量受限充电站 EVRP 中的非线性充电曲线处理方式[12]，设 $\phi_s(\cdot)$ 为充电站 $s$ 在有效充电区间内单调非减且可逆的充电函数，可由充电曲线断点进行分段近似，其逆 $\phi_s^{-1}(\cdot)$ 表示给定电量状态对应的等效充电时间。若电动车 $k$ 到达充电站 $s$ 时的电量为 $b_{sk}^{\tau}$，总充电时长为 $\Delta_{sk}^{\tau}=\sum_{t\in T}g_{skt}^{\tau}$，则本次充电获得的电量满足：

$$
\sum_{t\in T}y_{skt}^{\tau}
=\phi_s\left(\Delta_{sk}^{\tau}+\phi_s^{-1}(b_{sk}^{\tau})\right)-b_{sk}^{\tau},
\qquad s\in S,
 k\in K^{e,\tau} .
$$

(27)

式 (27) 刻画充电时长与补能量之间的非线性关系。具体分段曲线断点、充电开始时间、充电结束时间和分时段充电量的生成规则在算法部分说明。

充电占用变量与占用时长之间满足：

$$
0\le g_{skt}^{\tau}\le \Delta_t\chi_{skt}^{\tau},
\qquad s\in S,
\ k\in K^{e,\tau},
\ t\in T .
$$

(28)

分时段充电量只能在车辆实际占用充电桩的时段产生，并受充电功率上限约束：

$$
0\le y_{skt}^{\tau}\le \pi_s\, g_{skt}^{\tau},
\qquad s\in S,
\ k\in K^{e,\tau},
\ t\in T .
$$

(29)

其中 $\pi_s$ 为充电站 $s$ 的额定充电功率上限（占位参数，取值由实验给定）。式 (29) 保证未占用时段（$g_{skt}^{\tau}=0$）的充电量为零，使分时电网碳强度 $\gamma_t$ 正确作用于实际充电时段，避免将充电量分配到未占用的低碳时段以虚降碳排。

车辆只有访问充电站后才能在该站充电；若车辆在阶段开始时已经位于充电站，则允许其在该站即时充电：

$$
\chi_{skt}^{\tau}\le \sum_{i\in V_k^\tau\setminus\{s\}}x_{isk}^{\tau}+\delta_{sk}^{\tau}z_k^\tau,
\qquad s\in S,
\ k\in K^{e,\tau},
\ t\in T .
$$

(30)

每辆车在单个重规划阶段内至多访问同一充电站一次，以保证站点级时间、电量与充电变量 $a_{sk}^{\tau},b_{sk}^{\tau},g_{skt}^{\tau},y_{skt}^{\tau}$ 的良定义：

$$
\sum_{i\in V_k^\tau\setminus\{s\}}x_{isk}^{\tau}\le 1,
\qquad s\in S,
\ k\in K^{e,\tau} .
$$

(31)

共享充电站在同一时段内的充电车辆数不得超过可用充电桩数量：

$$
\sum_{k\in K^{e,\tau}}\chi_{skt}^{\tau}\le C_s,
\qquad s\in S,
\ t\in T .
$$

(32)

式 (22)–(32) 是 EVRP 电量和充电约束。其中，式 (27) 保留非线性充电函数的核心语义，式 (28)–(32) 用于约束分时段占用和共享充电站容量。充电量同时进入电费和式 (7) 的电力侧碳排放，因而时变电网碳强度直接进入方案评价。每次充电的开始时间、结束时间、占用时段、时段重叠时长、分时段充电量和充电曲线断点在算法求解与算例分析中给出。

车场 $d$ 在当前协同方案下的累计收益为：

$$
\Pi_d^\tau=\bar\Pi_d^\tau+\sum_{i\in N^\tau}R_i h_{id}^{\tau}-C_d^\tau,
\qquad d\in D .
$$

(33)

进一步地，车场 $d$ 当前阶段运营成本的归集口径为：

$$
\begin{aligned}
C_d^{\tau}=&\sum_{k\in K_d^\tau}c_k^{fix}z_k^{\tau}
+\sum_{k\in K_d^\tau}\sum_{(i,j)\in \mathcal{A}_k^\tau}c_k^{km}d_{ij}x_{ijk}^{\tau}
+p^f\sum_{k\in K_d^\tau\cap K^{g,\tau}}\sum_{(i,j)\in \mathcal{A}_k^\tau}f_{ijk}^{\tau}x_{ijk}^{\tau}\\
&+\sum_{k\in K_d^\tau\cap K^{e,\tau}}\sum_{s\in S}\sum_{t\in T}p_t^e y_{skt}^{\tau}
+\sum_{k\in K_d^\tau\cap K^{e,\tau}}\sum_{s\in S}\sum_{t\in T}c_s^{occ}g_{skt}^{\tau}
+\sum_{i\in N^\tau}c_{id}^{tr}h_{id}^{\tau}
+C_{\mathrm{car},d}^{\tau},
\qquad d\in D .
\end{aligned}
$$

(34)

其中 $C_{\mathrm{car},d}^{\tau}$ 为按车场 $d$ 所属车辆排放贡献分摊的碳交易成本，且 $\sum_{d\in D}C_d^{\tau}$ 与式 (9) 当前阶段成本项一致，不重复核算。
其中，$C_d^\tau$ 由同一求解结果中的车辆固定成本、非能源里程成本、能源成本、充电占用成本、跨车场调拨成本和新增碳排放成本按车辆所属或服务车场汇总得到。固定成本、非能源里程成本、燃油成本、电费和充电占用成本按执行车辆当前服务车场归集；跨车场调拨成本按客户实际服务车场归集；新增碳排放成本按车辆对应排放贡献归集。上述归集口径与式 (9) 一致，避免重复核算。

参考多车场车辆路径问题中的收益公平建模思想[8]，本文采用相对独立运营基准的比例公平下界表示收益公平：

$$
\Pi_d^\tau\ge \theta\Pi_d^{0,\tau},
\qquad d\in D .
$$

(35)

式 (33) 和式 (35) 不要求各车场绝对利润相同，而是限制每个车场协同后的收益不低于其独立运营基准的一定比例。该写法要求独立运营基准收益 $\Pi_d^{0,\tau}$ 为正值，且 $\Pi_d^\tau$ 与 $\Pi_d^{0,\tau}$ 采用一致的时间口径。因此，使用式 (35) 前应先由独立运营模型求得基准收益并验证 $\Pi_d^{0,\tau}>0$；若某一算例无法满足该条件，则比例公平下界不适用于该算例，收益公平仅作为实验评价指标报告。通过改变 $\theta$，可在实验中扫描公平要求对总成本、碳排放和跨车场协同范围的影响。

变量取值范围为：

$$
x_{ijk}^{\tau},z_k^\tau,\chi_{skt}^{\tau},h_{id}^{\tau}\in\{0,1\} .
$$

(36)

$$
u_{ijk}^{\tau},a_{ik}^{\tau},b_{ik}^{\tau},y_{skt}^{\tau},g_{skt}^{\tau},y_{ikt}^{\tau},g_{ikt}^{\tau}\ge0 .
$$

(37)

上述模型在每个重规划时刻只对 $N^\tau$ 中的未服务客户和当前可用车辆进行优化；已执行路径不再参与当前阶段重优化，其影响通过 $o_k^\tau$、$\bar a_k^\tau$、$L_k^\tau$、$\bar b_k^\tau$、$\bar Z^\tau$、$\bar E^\tau$ 和 $\bar\Pi_d^\tau$ 继承。算法章节和结果输出中逐阶段给出车辆位置、当前时间、剩余载重、剩余电量、累计成本、累计碳排放、累计收益、已服务客户和未服务客户，以反映已执行决策与后续优化之间的衔接关系。

# 求解算法框架（待完善）

## 算法定位

本节暂不指定具体求解算法，仅保留与第2节模型和第4节实验相衔接的最小骨架。后续正式确定主算法后，应在本节补充算法选择依据、核心流程、关键参数、对比基准和复杂度或终止条件说明。本占位节不构成最终算法贡献。

## 输入输出接口

在任一重规划时刻 $\tau$，算法输入包括有效待服务客户集合 $N^\tau$、可用车辆集合 $K^\tau$、车辆当前位置 $o_k^\tau$、当前时间 $\bar a_k^\tau$、剩余载重 $L_k^\tau$、剩余电量 $\bar b_k^\tau$、共享充电站状态、阶段碳配额 $CE^\tau$ 以及历史累计成本、碳排放和车场收益。算法输出应至少包括车辆路径、服务车场归属、充电站访问与充电量、阶段成本、阶段碳排放、车场收益、公平值和约束核验结果。

## 可行性处理骨架

无论后续采用元启发式算法、精确算法还是混合求解框架，候选方案均需按照统一口径核验客户唯一服务、车辆流平衡、载重、时间窗、续航安全电量、共享充电站容量、碳配额和收益公平约束。若主算法允许产生临时不可行方案，则需明确不可行方案的修复或惩罚规则，并保证最终报告方案满足第2节模型约束。

## 动态重规划接口

动态需求场景下，算法只重规划尚未执行的配送任务。每次触发重规划时，已服务客户、已执行弧段、已发生时间、载重消耗、电量消耗、充电占用、成本、碳排放和车场收益均作为历史状态继承，不再回滚修改。新增、取消和需求变化事件先更新 $N^\tau$ 与 $q_i^\tau$，再以当前车辆状态作为新阶段初始条件生成后续路径。

## 待补充内容

正式算法确定后，本节需补充以下内容：1) 主算法类型及其适用理由；2) 解表示或决策变量调用方式；3) 约束修复、可行性检查或精确求解接口；4) 动态状态继承流程；5) 参数设置与终止准则；6) 与基准算法或消融算法的公平比较方式。

# 实验设计

## 算例设置与参数说明

本文以Goeke和Schneider混合车队路径研究为基础[27]，采用EVRPTW-MF公开实例构造协同多车场混合车队算例[28]。算例保留原始客户、充电站、时间窗、服务时间、车辆容量、电池容量和非对称距离矩阵，并在不改变原始客户需求与道路结构的前提下扩展第二车场，用于刻画客户跨场服务、共享车辆池和共享充电站容量约束。具体节点规模、车队配置、车辆容量和参数取值不在正文展开，后续实验结果应由统一的数据配置文件和结果导出脚本给出。

本文成本统一采用英镑口径。电网碳强度采用NESO发布的Great Britain范围actual national carbon intensity，并按固定时间粒度换算为kgCO₂/kWh[29]；Carbon Intensity API用于核对碳强度接口和时间粒度[30]。柴油CO₂因子、柴油价格、电价和碳交易价格分别来自GOV.UK温室气体转换因子、道路燃油价格、非居民部门电价和UK ETS碳价相关资料[31,32,33,34,35]。充电占用成本$c_s^{occ}$作为补能技术场景参数处理，不引用非同口径的工资或车辆租赁报价。

车辆能耗参数与第2节模型保持一致。燃油车油耗和碳排放按CMEM相关公式计算，电动汽车行驶阶段不计直接尾气排放，充电侧间接碳排放由实际充电量和对应时段电网碳强度确定。求解算法尚未最终确定，因此正文不列出具体算法参数；后续确定主算法后，应统一说明主算法、基准算法、共同评价函数、终止准则和独立运行次数。

## 实验组织与结果呈现

实验设计围绕算法有效性、静态基准与车型反事实、机制消融、碳情景敏感性、收益公平阈值敏感性、补能技术参数和动态滚动重规划展开。除反事实实验明确改变的因素外，其余成本、碳排放、收益公平和可行性核验口径保持一致。正式结果补齐前，正文不展示具体图表、数值结果或生成文件，仅说明各实验模块需要回答的问题和应保留的评价口径。后续若加入结果表或图，应确保所有数值均来自统一CSV导出，不以经验判断替代实验结果。

## 算法有效性验证

算法有效性实验将在主算法确定后展开。为保证比较公平，主算法与基准算法需采用相同算例、相同约束口径、相同评价函数和相同计算预算。若无公开BKS的论文专用算例仅能报告相对已观测最优可行解的偏差，则不得称为BKS gap。正式版本可报告最优值、均值、标准差、可行率、运行时间和显著性检验，但当前稿件暂不展示具体算法结果。

## 静态基准与车型反事实结果

静态基准实验用于说明完整碳感知协同模型下的车辆分配、服务序列、共享充电站访问、载重、电量、等待、成本、碳排和收益公平核算方式。车型反事实仅改变可用车型集合，固定客户、时间窗、容量、道路距离、调拨规则和碳配额口径，用于比较混合车队、纯燃油车队和可行纯电车队的决策差异。当前稿件仅保留实验目的和控制变量，不展示具体路线、成本或碳排数据。

## 机制消融实验

机制消融按"协同机制、EV间接碳排、时变碳强度、碳配额、收益公平下界约束"逐步加入，用于识别各建模层的边际贡献。正式分析应同时解释车型分工、客户跨场分配、调拨关系、充电时刻和收益公平的变化。当前稿件不展示消融表或具体实验数据。

## 碳强度、碳配额与碳价敏感性

碳情景实验用于判断低碳信号是否真实进入决策。在可买可卖的限额碳交易口径下，式 (8) 既刻画超额排放购买配额的成本，也刻画剩余配额出售获得的收益；因此，碳强度、配额水平和碳价均可能通过碳交易项影响充电时刻、车型选择和调拨关系。正式分析应同时观察充电时段、车型分工、碳交易成本和总成本变化，但当前稿件不展示碳强度曲线、充电负荷图或具体情景数据。

## 收益公平阈值敏感性

收益公平实验采用多个$\theta$水平设置收益公平下界约束，比较公平要求变化对系统总成本、碳排放、跨车场服务和车场收益保持水平的影响。正式分析应报告$\Pi_d$、$\Pi_d^0$、$\Pi_d/\Pi_d^0$和最差车场公平水平，避免只用系统总成本评价协同有效性。当前稿件不展示公平前沿图或具体收益数据。

## 动态需求滚动重规划

动态实验引入新增、取消和需求变化事件，按$\overline q$与$\Delta t$触发滚动重规划。每次更新应记录冻结路径、已服务顾客、车辆位置、剩余载重、剩余电量、剩余碳配额、阶段新增碳惩罚和收益公平值。动态/静态对比仅在同一已揭示需求集合下进行。当前稿件仅保留动态实验的状态继承和闭合核验口径，不展示阶段结果表、实例快照或具体事件数据。

## 管理启示

管理启示应从真实实验结论中提炼，不单独拔高。当前稿件仅保留管理启示的讨论方向，即围绕碳交易机制下的充电时段引导、车场协同收益补偿、共享充电站容量配置和动态订单批处理阈值设置解释模型可能产生的管理含义；具体结论待实验结果完成后补充。

# 结论

本文围绕动态城市配送中时变电网碳强度、混合车队协同调度和车场收益公平之间的耦合关系，构建了考虑共享车辆池、车场间调拨、共享充电站容量、非线性部分充电、EV充电间接碳排、碳配额惩罚和动态需求扰动的协同多车场混合车队路径模型，并保留面向该模型的求解算法接口骨架与滚动重规划机制。

实验分析从算法对比、碳配额绑定情景、收益公平阈值变化和动态滚动重规划四个方面展开，用于检验后续主算法求解表现、时变电网碳强度对充电和车型分工的影响、收益公平下界约束带来的成本变化，以及不可回滚条件下车辆状态继承和剩余碳配额核算的闭合性。

本文仍存在一定局限。电动车能耗已考虑载重影响，但尚未显式刻画速度波动、坡度和天气等因素；动态方案与一次性静态方案的信息条件不同，后续需在同等信息和同等求解预算下进一步比较其边界性能。

# 参考文献

[1] 习近平. 在第七十五届联合国大会一般性辩论上的讲话[EB/OL]. [2020-09-22]. https://www.gov.cn/gongbao/content/2020/content_5549875.htm.
[2] 中共中央, 国务院. 关于完整准确全面贯彻新发展理念做好碳达峰碳中和工作的意见[EB/OL]. [2021-09-22]. https://www.gov.cn/zhengce/2021-10/24/content_5644613.htm.
[3] International Energy Agency. CO₂ Emissions in 2023[EB/OL]. [2024-03-01]. https://www.iea.org/reports/co2-emissions-in-2023.
[4] International Energy Agency. Global EV Outlook 2024: Outlook for emissions reductions[EB/OL]. [2024-04-23]. https://www.iea.org/reports/global-ev-outlook-2024/outlook-for-emissions-reductions.
[5] Amiri A, Zolfagharini H, Amin S H. Routing a mixed fleet of conventional and electric vehicles for urban delivery problems: considering different charging technologies and battery swapping[J]. International Journal of Systems Science: Operations & Logistics, 2023, 10(1).
[6] 李得成, 陈彦如, 张宗成. 基于分支定价算法的电动车与燃油车混合车辆路径问题研究[J]. 系统工程理论与实践, 2021, 41(4): 995-1009.
[7] Wang Y, Zhou J, Sun Y, Fan J, Wang Z, Wang H. Collaborative multidepot electric vehicle routing problem with time windows and shared charging stations[J]. Expert Systems with Applications, 2023, 219: 119654.
[8] Soriano A, Gansterer M, Hartl R F. The multi-depot vehicle routing problem with profit fairness[J]. International Journal of Production Economics, 2023, 255: 108669.
[9] Shi Y, Lin N, Han Q, Zhang T, Shen W. A method for transportation planning and profit sharing in collaborative multi-carrier vehicle routing[J]. Mathematics, 2020, 8(10): 1788.
[10] Agussurja L, Lau H C, Cheng S F. Achieving stable and fair profit allocation with minimum subsidy in collaborative logistics[C]. Proceedings of the AAAI Conference on Artificial Intelligence, 2016, 30(1).
[11] Crevier B, Cordeau J F, Laporte G. The multi-depot vehicle routing problem with inter-depot routes[J]. European Journal of Operational Research, 2007, 176(2): 756-773.
[12] Froger A, Mendoza J E, Jabali O, Laporte G. The electric vehicle routing problem with capacitated charging stations[J]. Transportation Science, 2022, 56(2): 460-482.
[13] 胡路, 乐诗彤, 朱娟秀. 考虑多充电桩排队和时间窗的电动货车路径规划[J]. 西南交通大学学报, 2025, 60(2): 299-307.
[14] Psaraftis H N. Dynamic vehicle routing problems[J]. Vehicle Routing: Methods and Studies, 1988, 16: 223-248.
[15] 徐小峰, 姜明月, 邓忆瑞. 整合逆向物流协同配送动态路径优化问题研究[J]. 管理科学学报, 2021, 24(10): 106-126.
[16] 林明锦, 王建新, 王超. 考虑动态度和时间窗的两级车辆路径问题[J]. 计算机集成制造系统, 2022, 28(6): 1870-1887.
[17] Wang Y, Zhe J, Wang X, et al. Collaborative multicenter reverse logistics network design with dynamic customer demands[J]. Expert Systems with Applications, 2022, 206: 117926.
[18] 李阳, 范厚明, 张晓楠. 动态需求下车辆路径问题的周期性优化模型及求解[J]. 中国管理科学, 2022, 30(8): 254-266.
[19] Giménez-Palacios I, Parreño F, Álvarez-Valdés R, et al. First-mile logistics parcel pickup: Vehicle routing with packing constraints under disruption[J]. Transportation Research Part E: Logistics and Transportation Review, 2022, 164: 102839.
[20] Florio A M, Hartl R F, Minner S. New exact algorithm for the vehicle routing problem with stochastic demands[J]. Transportation Science, 2020, 54(4): 1073-1090.
[21] 杨沙. 考虑动态需求的冷链物流配送路径优化研究[D]. 沈阳: 沈阳工业大学, 2022.
[22] Gendreau M, Guertin F, et al. Parallel tabu search for real-time vehicle routing and dispatching[J]. Transportation Science, 1999, 33(4): 381-390.
[23] 陈婉茹, 徐光明, 张得志, 等. 碳交易机制下多中心混合车队配送路径和速度优化研究[J]. 系统工程理论与实践, 2023, 43(11): 3320-3335.
[24] Cheng A J, Tarroja B, Shaffer B, Samuelsen S. Carbon-aware electric vehicle charging[J]. Electric Power Systems Research, 2022, 208: 107847.
[25] Wang Y, Wei Z, Luo S, Zhou J, Zhen L. Collaboration and resource sharing in the multidepot time-dependent vehicle routing problem with time windows[J]. Transportation Research Part E: Logistics and Transportation Review, 2024, 192: 103798.
[26] Kumar A A, Susheel Y, et al. A genetic algorithm model for optimizing vehicle routing problems with perishable products under time-window and quality requirements[J]. Decision Analytics Journal, 2022, 5.
[27] Goeke D, Schneider M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99.
[28] Goeke D, Schneider M. EVRPTW-MF[DB/OL]. Mendeley Data, 2022, V1. DOI: 10.17632/bd7rm5fw6k.1. https://data.mendeley.com/datasets/bd7rm5fw6k.
[29] National Energy System Operator. National Carbon Intensity Forecast[DB/OL]. [2026-06-01]. https://www.neso.energy/data-portal/national-carbon-intensity-forecast/national_carbon_intensity_forecast.
[30] National Energy System Operator. Carbon Intensity API[DB/OL]. [2026-06-01]. https://carbonintensity.org.uk/.
[31] Department for Energy Security and Net Zero. Greenhouse gas reporting: conversion factors 2025[EB/OL]. [2025-06-04]. https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025.
[32] Department for Energy Security and Net Zero. Weekly road fuel prices[DB/OL]. [2026-06-01]. https://www.gov.uk/government/statistics/weekly-road-fuel-prices.
[33] Department for Energy Security and Net Zero. Gas and electricity prices in the non-domestic sector[DB/OL]. [2026-03-31]. https://www.gov.uk/government/statistical-data-sets/gas-and-electricity-prices-in-the-non-domestic-sector.
[34] UK ETS Authority. UK ETS: Carbon price for use in civil penalties, 2025[EB/OL]. [2024-11-28]. https://www.gov.uk/government/publications/determinations-of-the-uk-ets-carbon-price/uk-ets-carbon-prices-for-use-in-civil-penalties-2025.
[35] Department for Energy Security and Net Zero. Determinations of the UK ETS carbon price[EB/OL]. [2025-11-28]. https://www.gov.uk/government/publications/determinations-of-the-uk-ets-carbon-price.