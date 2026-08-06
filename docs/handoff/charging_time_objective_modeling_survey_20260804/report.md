# T1-CHARGE-OBJ-MODEL：充电时刻进入目标函数的现成建模取证

日期：2026-08-04  
任务性质：全文 PDF 逐页取证；零实验、零求解、零代码改动。  
页码口径：下文“PDF p.x”均指所列本机 PDF 的物理页码（从文件第一页起计）；若出版页码不同，另行注明。公式保留原文式号。Yao 等（2023）使用作者预印本 v4，式号和页码均按该预印本；其期刊出处和 DOI 已按出版元数据核实。

## 一、结论

有现成建模，而且至少有三种可以直接迁移的时间—充电成本连接方式。

第一种是“整时段二元占用”。Lin、Ghaddar 和 Nathwani（2021）把规划期划成等长时段，用二元变量表示某车在某站某时段充/放电，目标函数直接按该时段的买卖电价计费；到站时刻与时段起点之间的关系由式（6）和（14）保证。其限制是一次充电只能占用完整时段，非时段起点到达的车辆必须等待。

第二种是“连续充电区间对分段价格积分”。Shi 等（2025）令到站时刻和到站 SOC 都是路径决策的结果，充电费用写成

$$
P_E(\tau_i)=\int_{\tau_i}^{\tau_i+(B-y_i)/r}r\rho'(t)\,dt.
$$

这在数学上自动把跨越多个电价段的充电量按重叠时长拆分，但论文没有给出该分段积分的 MILP 辅助变量或线性化约束。

第三种是“连续到达时间 + 离散充电时段启停变量”。Yao 等（2023）用连续到站时刻 \(t_i\)、充电量 \(r_i^k\)、时段占用 \(B_{i\tau}\) 和开始变量 \(B_{i\tau}^{s}\) 联结路线、充电量和时空电价；式（10a）—（12b）把会话起点和时段序列连接起来。原文声称这消除了“只能在时段起点开始充电”的假设；但其费用仍按被占用的完整时段 \(B_{i\tau}\Delta\tau\) 计，式（11）还是不等式，未显式给出首尾时段的分数重叠量。

时变碳强度方面，Miyabe、Fujimoto 和 Hayashi（2025）已经给出了可以直接照抄结构的路径—充电—碳目标：在 5 分钟时间扩展网络上，用“车辆在充电点原地停留”的二元状态乘充电功率，再乘该时段电网碳强度。Cheng 等（2022）则给出固定到离站窗口下更简洁的充电功率模型：

$$
\min_u\sum_{t\in\mathcal T}\sum_{i\in\mathcal V}C(t)u_i(t)\Delta T+\cdots .
$$

前者已经联合优化路线，后者没有路线但可直接提供分时碳项、站级功率约束和固定会话窗口约束。

因此，问题“前人有没有现成的、可直接迁移的建模”答案为“有”。可直接迁移的是：时段集合、时段碳/价系数、充电占用或充电功率变量、SOC 递推，以及到站/返场时刻同后续行程的时间连接。不能原样搬用的是：现有任何一篇都没有同时覆盖本项目的混合车队、多车场、多趟、硬时间窗、车场与公共站两类充电点。必须组合而不是宣称单篇模型已经覆盖全部结构。

本次逐页阅读全文并纳入公式级取证 11 篇。其中 5 篇的目标函数直接含分时电价或分时碳强度；3 篇提供部分/非线性/有容量充电站建模；2 篇提供多趟返场时刻建模；1 篇用于澄清“时变排队”不是“分时电价”。下文只陈述这 11 篇中的观察，不外推为“主流做法”。

## 二、方向 1 与方向 5：分时电价，以及同一度电在不同时刻的价格成本

### 2.1 Lin, Ghaddar, and Nathwani（2021）

出处：Lin, B., Ghaddar, B., & Nathwani, J. (2021). Electric vehicle routing with charging/discharging under time-variant electricity prices. Transportation Research Part C: Emerging Technologies, 130, 103285. DOI: https://doi.org/10.1016/j.trc.2021.103285

本机全文：

/Users/zhouleixishu/Zotero/storage/LPDQN9V7/Lin 等 _ 2021 _ Electric Vehicle Routing and ChargingDischarging under Time-Variant Electricity Prices.pdf

原文位置：时间离散与假设见 PDF p.6；符号表和变量见 pp.6–7；模型见 pp.8–9；算例规模和时段见 pp.20–22；路线改变见 pp.25–26；时段粒度敏感性见 pp.29–30。

原式。目标式（1）为：

$$
\min
\sum_{k=1}^{K}\sum_{i\in V_{s,od}}\sum_{t\in T}
\left(r_{itk}P_{\mathrm{re}}^{t}-d_{itk}P_{\mathrm{dis}}^{t}\right)
+
\sum_{k=1}^{K}P_{\mathrm{night}}
\left[
B-b_{pk}-\sum_{t\in T}\delta(r_{ptk}-d_{ptk})
\right].
\tag{1}
$$

离开充电站的时间连接式（6）为：

$$
t\delta(r_{itk}+d_{itk})+t_{ij}x_{ijk}
-\delta|T|(1-x_{ijk})\le \tau_{jk}.
\tag{6}
$$

电池递推和充放电容量约束为：

$$
b_{jk}\le b_{ik}
+\sum_{t\in T}\delta r_{itk}
-\sum_{t\in T}\delta d_{itk}
-f_{ij}x_{ijk}+B(1-x_{ijk}),
\tag{10}
$$

$$
\sum_{t\in T}\delta r_{itk}\le B-b_{ik},
\tag{11}
$$

$$
\sum_{t\in T}\delta d_{itk}\le b_{ik},
\tag{12}
$$

$$
r_{itk}+d_{itk}\le1.
\tag{13}
$$

到达时刻与可占用时段的关键约束为：

$$
\tau_{ik}-(t-1)\delta
\le \delta|T|(1-d_{itk}-r_{itk}).
\tag{14}
$$

原文变量与集合定义：\(V_c=\{1,\ldots,N\}\) 为客户；\(V_s=\{N+1,\ldots,N+S\}\) 为充电站；\(V_{od}=\{0,N+S+1\}\) 为起终点车场副本；\(V_{s,od}=V_s\cup V_{od}\)；\(T\) 为充/放电时段集合；\(K\) 为同质 EV 数；\(\delta\) 为时段长度；\(C\) 为电池容量；\(\alpha\) 为恒定充电速度的倒数；\(B=\alpha C\) 为从空到满所需时间；\(g\) 为单位距离耗能率；\(a_{ij},t_{ij},c_{ij}=ga_{ij},f_{ij}=\alpha c_{ij}\) 分别为弧距离、行驶时间、耗能和补回该弧耗能所需充电时间。\(p_t^b,p_t^s\) 是时段 \(t\) 的买、卖电价；\(P_{\mathrm{re}}^t=(\delta/B)Cp_t^b\)，\(P_{\mathrm{dis}}^t=(\delta/B)Cp_t^s\)；\(P_{\mathrm{night}}=p_{\mathrm{night}}/\alpha\)。\(x_{ijk}\) 表示车 \(k\) 是否走弧 \((i,j)\)；\(r_{itk},d_{itk}\) 表示车 \(k\) 是否在节点 \(i\) 的时段 \(t\) 充/放电；\(\tau_{ik}\) 为到达时刻；\(b_{ik}\) 是以“充电时间”计的剩余能量；\(p=N+S+1\) 是返回车场。

时间离散与重叠：规划期由 \(|T|\) 个长度 \(\delta\) 的连续离散段构成，\(t\) 表示 \([\delta(t-1),\delta t)\)。原文明确规定，占用某时段就必须充/放整段；若到站不在时段起点，必须等到下一个时段。式（14）禁止在到达前或时段起点前开始，式（6）强制后继节点到达不早于最后一个被占用时段的末端。它没有计算“首、尾时段的分数重叠量”，而是用整段占用回避该量。

前提：同质 EV；恒定单位距离耗能；线性、恒功率充/放电；每个时段只能充或放一种；允许 V2G；规划期末用固定夜间价格补满；客户硬时间窗；单车场；没有多趟和站容量/排队。

对本项目：可直接迁移 \(T,\delta,r_{itk}\) 与分时系数的目标结构，以及式（6）、（10）—（14）的“路线—SOC—时段”联结。需改为车辆类型索引并给 ICEV 保留燃料/排放项；把单车场节点扩为多车场；增加同一实体车的多趟返场—再出发连接；车场与公共站分别设置可用时段、功率和容量；若本项目允许会话跨半小时边界并按实际 kWh 精确计碳，则不能沿用整时段占用，必须增加分数重叠量或用更细时间扩展网络。

### 2.2 Shi, Wang, Zhou, and He（2025）

出处：Shi, W., Wang, N., Zhou, L., & He, Z. (2025). The bi-objective mixed-fleet vehicle routing problem under decentralized collaboration and time-of-use prices. Expert Systems with Applications, 273, 126875. DOI: https://doi.org/10.1016/j.eswa.2025.126875

本机全文：

/Users/zhouleixishu/Zotero/storage/K4WVSUAB/Shi 等 _ 2025 _ The bi-objective mixed-fleet vehicle routing problem under decentralized collaboration and time-of-u.pdf

原文位置：集合、变量、分时电价和目标见 PDF p.4；时间与充电约束见 pp.4–5；规模与算法见 pp.9–10；固定价与 TOU 比较见 p.12。

原式。分时价格函数和折算到电池侧的价格为：

$$
\rho(t)=
\begin{cases}
price_1,&t\in T_1,\\
price_2,&t\in T_2,\\
price_3,&t\in T_3,
\end{cases}
\qquad
\rho'(t)=\eta\rho(t).
$$

到站时电量为 \(y_i\)、从 \(y_i\) 充满至 \(B\) 的费用（原文无独立式号）为：

$$
P_E(\tau_i)
=\int_{\tau_i}^{\tau_i+(B-y_i)/r}r\rho'(t)\,dt.
$$

利润目标式（3）为：

$$
\max f_1=
\sum_{i\in V}p_i z_i
-\sum_{i\in V'_0}\sum_{j\in V'_{N+1}}x^E_{ij}d_{ij}\lambda_E
-\sum_{i\in V'_0}\sum_{j\in V'_{N+1}}x^{IC}_{ij}d_{ij}\lambda_{IC}
-\sum_{i\in F}\sum_{j\in V'_{N+1}}x^E_{ij}P_E(\tau_i).
\tag{3}
$$

充电站离开后的时间连接式（12）为：

$$
\tau_i+t_{ij}x^E_{ij}+r(B-y_i)x^E_{ij}
-(l_0+rB)(1-x^E_{ij})\le\tau_j,
\quad i\in F,\ j\in V'_{N+1},\ i\ne j.
\tag{12}
$$

原文变量与集合定义：\(G\) 为配送网络；\(V\) 为客户；\(F\) 为充电站的虚拟副本集合；\(V'_0,V'_{N+1}\) 分别是含起点/终点车场的扩展节点集；\(T_1,T_2,T_3\) 为峰、平、谷价格时段集合；\(m_E,m_{IC}\) 为 EV 与内燃车数量；\(B\) 为电池容量；\(r\) 为充满单位能量所需时间，即线性充电率的时间表示；\(\eta\) 为充电效率折算；\(\tau_i\) 为节点 \(i\) 到达时刻；\(y_i\) 为到站 SOC；\(p_i\) 为服务收益；\(z_i\) 表示客户是否被服务；\(x^E_{ij},x^{IC}_{ij}\) 为两类车弧变量；\(d_{ij},t_{ij}\) 为距离和行驶时间；\(\lambda_E,\lambda_{IC}\) 为单位距离成本；\(P_E(\tau_i)\) 为从到站时刻开始充满的分时费用。

时间离散与重叠：价格由三个分段常数集合 \(T_1,T_2,T_3\) 定义，但到站和充电持续时间是连续的。积分上下限把连续会话 \([\tau_i,\tau_i+(B-y_i)/r]\) 与每个价格段的交集自动计入；这是本次全文中最简洁的“跨段重叠”数学写法。论文没有给出将该积分转成 MILP 的时段重叠变量、上下界或线性化，因此不能把“积分写法”误报为已给出可直接编码的精确线性重叠约束。

前提：两类车混合；单车场；EV 在站点线性充电且每次充满；恒定充电效率；允许连续到达和跨价格段；硬时间窗；没有多趟、多车场、公共站容量和排队。

对本项目：混合车队索引、两类弧成本和 \(P_E(\tau_i)\) 可直接迁移；把 \(\rho'(t)\) 替换或并列为电网碳强度 \(c_t\) 即得到分时碳项。需把“每次充满”改为充电量决策；补出会话—半小时段的显式重叠量与线性化；增加多车场归属、同一实体车跨趟时序、两类充电点容量和功率。ICEV 仍不参与充电变量。

### 2.3 Yao, Chen, Salazar, and Yang（2023）

出处：Yao, C., Chen, S., Salazar, M., & Yang, Z. (2023). Joint Routing and Charging Problem of Electric Vehicles With Incentive-Aware Customers Considering Spatio-Temporal Charging Prices. IEEE Transactions on Intelligent Transportation Systems, 24(11), 12215–12226. DOI: https://doi.org/10.1109/TITS.2023.3286952

本机全文（作者预印本 v4；PDF 页码按此文件）：

/Volumes/移动硬盘（512G）/ReSETP/docs/handoff/charging_time_objective_modeling_survey_20260804/source_pdfs/Yao_et_al_2023_arXiv2201.02311.pdf

原文位置：集合和路径变量见 PDF p.4；路线、电量和时间式（1）—（9）见 pp.5–6；关键时段启停和目标见 pp.6–7；实验时段与规模见 pp.14–16；无激励基准完整模型见 p.18。

原式。电量递推：

$$
-M(1-x^k_{ij})
\le -E^k_j+E^k_i+r^k_i-e_{ij}x^k_{ij}
\le M(1-x^k_{ij}),
\quad i\in C,\ j\in V\setminus v_1,\ k\in K.
\tag{6}
$$

时段开始与占用关系：

$$
B^s_{i\tau}\ge B_{i\tau}-B_{i(\tau-1)},
\quad i\in C,\ \tau\in\Lambda,
\tag{10a}
$$

$$
\sum_{\tau\in\Lambda}B^s_{i\tau}\le1,
\quad i\in C.
\tag{10b}
$$

充电持续时间与占用时段总长：

$$
r_i^k g_i\le\sum_{\tau\in\Lambda}B_{i\tau}\Delta\tau,
\quad i\in C.
\tag{11}
$$

连续到站时刻与开始时段：

$$
\sum_{\tau\in\Lambda}B^s_{i\tau}\tau\Delta\tau\le t_i,
\quad i\in C,
\tag{12a}
$$

$$
t_i\le
\sum_{\tau\in\Lambda}B^s_{i\tau}(\tau+1)\Delta\tau,
\quad i\in C.
\tag{12b}
$$

Problem 1 的目标行没有独立式号，原样为：

$$
\min_{x^k_{ij},B_{i\tau},B^s_{i\tau}\in\mathbb B,\,
r_i^k,q_j,t_j\in\mathbb R}
\sum_{i\in R}\sum_{\tau\in\Lambda}
\frac{p_{i\tau}B_{i\tau}\Delta\tau}{g_i}
+
\sum_{k\in K}\sum_{i\in V}\sum_{j\in V}
(c_i+\omega_TT_{ij}+\omega_Tr_i^kg_i)x^k_{ij}
+
\sum_{j\in R}q_j\delta_j^*
\sum_{i\in V}\sum_{k\in K}x^k_{ij},
$$

subject to (1)–(13)。注意：第一项求和下标在原文印为 \(i\in R\)，而正文把充电节点定义为 \(C\)；本报告不擅自改成 \(C\)，只记录这个原文下标不一致。

原文变量与集合定义：\(G(V,E)\) 为网络；\(V=\{v_1,C,R,v_n\}\) 含起点车场、充电节点集 \(C\)、客户/请求集 \(R\) 和终点车场；\(K\) 为 EV 集；\(\Lambda=\{1,\ldots,\xi\}\) 为等长 \(\Delta\tau\) 的时段集；\(x^k_{ij}\) 为弧变量；\(t_i\) 为连续到达时刻；\(r_i^k\) 为车 \(k\) 在站 \(i\) 的充电量；\(g_i\) 为每 kWh 充电所需时间；\(B_{i\tau}\) 表示站节点副本 \(i\) 的充电会话是否占用时段 \(\tau\)；\(B^s_{i\tau}\) 表示是否在该时段开始；\(E_i^k\) 为到节点的电量；\(e_{ij}=\phi d_{ij}\) 为弧耗能；\(p_{i\tau}\) 是站点—时段电价；\(T_{ij}\) 为行驶时间；\(c_i\) 合并车辆启用费和负的配送收入；\(\omega_T\) 为时间价值；\(q_j\) 为给客户的单位灵活性补偿；\(\delta_j^*\) 为客户选择的时间窗灵活度。

时间离散与重叠：24 小时分为 288 个 5 分钟时段。式（10a）识别 0→1 的开始，式（10b）使一个站点副本最多出现一个连续会话；多个会话通过复制充电节点实现。式（12a）—（12b）把连续到站 \(t_i\) 放进唯一开始时段；式（11）保证占用时段总长不少于实际充电持续时间。目标按每个占用时段的 \(p_{i\tau}\) 计费。因此它允许连续到达且会话跨时段，但没有首尾时段的分数重叠变量；价格正时目标会压缩多余占用，但“实际重叠分钟数”并非独立连续变量。

前提：同质 EV；单车场；线性恒功率充电；充电站可复制以容纳多次会话；没有站容量、排队、ICEV、多趟和多车场；客户时间窗可通过激励变宽，因此不是本项目的硬时间窗设定。

对本项目：可直接迁移 \(r_i^k,B_{i\tau},B^s_{i\tau}\)、节点复制以及式（6）、（10）—（12）的连接；\(p_{i\tau}\) 可替换/并列为 \(c_\tau\) 与分时电费。需把站点副本加车辆/趟索引；硬时间窗下删除客户激励层；给多车场和两类充电点分别建副本与容量；增加 ICEV 路径；若要求半小时边界两侧按真实分钟精确分摊，仍要把 \(B_{i\tau}\) 改成会话与时段的连续重叠量，而不是只计整段。

## 三、方向 2：时变电网碳强度进入目标

### 3.1 Miyabe, Fujimoto, and Hayashi（2025）

出处：Miyabe, R., Fujimoto, Y., & Hayashi, Y. (2025). Low-carbon routing and charging planning for electric freight trucks utilizing local surplus solar power. Journal of Energy Storage, 132, 117626. DOI: https://doi.org/10.1016/j.est.2025.117626

本机全文：

/Users/zhouleixishu/Zotero/storage/MP2SVFTJ/Miyabe 等 _ 2025 _ Low-carbon routing and charging planning for electric freight trucks utilizing local surplus solar p.pdf

原文位置：符号表见 PDF p.2；5 分钟时间扩展建模见 p.8；目标式（3）见 p.8；SOC 和车辆状态约束见 pp.9–10；算例和求解设置见 p.11；排放结果见 pp.13–17。

原式。低碳路径与充电计划的核心式（3）为：

$$
\{\hat{x}_{i,j,t_o}^{k},\hat{z}_{i,t_o}\}
=
\arg\min_{x_{i,j,t_o}^{k},z_{i,t_o}}
\sum_{t_o\in T_o}\sum_{i\in F}
\left[
e_{t_o}^{\mathrm{grid}}z_{i,t_o}
+e^{\mathrm{PV}}
\left(
\sum_{k\in K}x_{i,i,t_o}^{k}g_i-z_{i,t_o}
\right)
\right].
\tag{3}
$$

SOC 可行性式（9）为：

$$
\underline Q
\le q_k^0
+\sum_{t_o\le\tau}\sum_{i\in F}x_{i,i,t_o}^{k}g_i
-\sum_{t_o\le\tau}
\sum_{\substack{i,j\in V\\i\ne j}}
x_{i,j,t_o}^{k}v_kh_k
\le\overline Q.
\tag{9}
$$

每车每时段唯一状态：

$$
\sum_{i\in V}\sum_{j\in V}x_{i,j,t_o}^{k}=1.
\tag{13}
$$

购电量定义：

$$
z_{i,t_o}
=
\left[
\sum_{k\in K}x_{i,i,t_o}^{k}g_i-\hat d_{t_o}^{i}
\right]_+,
\quad i\in F,\ t_o\in T_o.
\tag{17}
$$

原文变量与集合定义：\(C,D,F,K,T_o\) 分别为客户、车场、充电点、EDV 和优化时段集合；\(V=D\cup C\cup F\)。\(x^k_{i,j,t_o}=1\) 表示车 \(k\) 在时段 \(t_o\) 从状态节点 \(i\) 转向 \(j\)；\(i=j\) 表示留在该点，若 \(i\in F\) 就表示该时段充电。\(z_{i,t_o}\) 为充电点 \(i\) 在时段 \(t_o\) 从电网购入的电量；\(e_{t_o}^{\mathrm{grid}}\) 为分时电网碳强度；\(e^{\mathrm{PV}}\) 为本地 PV 碳强度；\(g_i\) 为充电点每时段的充电量；\(\hat d_{t_o}^i\) 为预测的本地剩余 PV；\(q_k^0\) 为初始电量；\(\underline Q,\overline Q\) 为电池上下限；\(v_k\) 为车辆速度；\(h_k\) 为单位距离耗能。帽号变量是优化解或预测量。

时间离散与重叠：预测数据原为 30 分钟，模型插值/细分成 5 分钟的 \(T_o\)。充电不是连续会话，而是每个 5 分钟状态 \(x^k_{i,i,t_o}=1\)；目标直接乘该时段的碳强度。式（13）保证同一车辆每个时段只能处于一个状态，式（9）把所有已发生的充电槽累计进 SOC，式（17）把本地 PV 先抵扣后得到电网购电。没有连续会话—时段的分数重叠，因为所有状态已经与 5 分钟格点对齐。

前提：EDV 同类车辆；固定 50 kW 恒功率充电；时间扩展状态；无排队；日前预测；目标只计充电电力的生命周期碳系数；公共站与车场充电点均可出现在 \(F\)，但算例只有一个车场；没有 ICEV、多趟和硬时间窗的完整 ReSETP 结构。原文求解达到 6 小时上限时采用“找到的最好解”，不能转述为全部全局最优。

对本项目：式（3）是最直接可迁移的碳目标，\(e_{t_o}^{\mathrm{grid}}\sum xg\) 可原样变成半小时碳强度乘充电量；式（9）、（13）、（17）可提供精确时段 SOC/状态联结。需为 ICEV 增加行驶排放并禁止充电；为多车场、多趟增加实体车—趟索引及返场连接；为车场/公共站分别加入容量和可用性；硬时间窗应映射到允许访问状态。若保持连续行驶/充电而非 5 分钟全离散，不能直接使用 \(x_{i,i,t_o}\)，需改成重叠量。

### 3.2 Cheng, Bian, Shi, and Chen（2022）

出处：Cheng, K.-W., Bian, Y., Shi, Y., & Chen, Y. (2022). Carbon-Aware EV Charging. 2022 IEEE International Conference on Communications, Control, and Computing Technologies for Smart Grids (SmartGridComm), 186–192. DOI: https://doi.org/10.1109/SmartGridComm52983.2022.9960988

本机全文：

/Users/zhouleixishu/Zotero/storage/57ITRNUI/Cheng 等 _ 2022 _ Carbon-Aware EV Charging.pdf

原文位置：碳强度定义见 PDF p.3；充电优化式（2a）—（2g）及变量定义见 pp.3–4；在线算法见 p.4；数据规模与结果见 pp.5–7。

原式：

$$
\min_u
\sum_{t\in\mathcal T}\sum_{i\in\mathcal V}
C(t)u_i(t)\Delta T
+\lambda\sum_{i\in\mathcal V}
\left|x_i(T)-x_{i,\mathrm{depart}}\right|.
\tag{2a}
$$

$$
x_i(0)=x_{i,\mathrm{arrival}},
\tag{2b}
$$

$$
x_i(t)=x_i(t-1)+\frac{\delta u_i(t)}{E_i},
\quad t\ge1,
\tag{2c}
$$

$$
0\le x_i(t)\le\bar x_i,
\tag{2d}
$$

$$
0\le u_i(t)\le\bar u_i,
\tag{2e}
$$

$$
\sum_{i\in\mathcal V}u_i(t)\le\bar P,
\quad t\in\mathcal T,
\tag{2f}
$$

$$
u_i(t)=0,
\quad t\notin[t_{i,\mathrm{arrival}},t_{i,\mathrm{depart}}).
\tag{2g}
$$

原文变量与集合定义：\(\mathcal T=\{1,\ldots,T\}\) 为离散时段；\(\mathcal V\) 为接入充电站的 EV；\(C(t)\) 是时变电网碳强度；\(u_i(t)\) 是车 \(i\) 在时段 \(t\) 的充电功率；\(x_i(t)\) 是 SOC；\(x_{i,\mathrm{arrival}},x_{i,\mathrm{depart}}\) 是到达和期望离开 SOC；\(t_{i,\mathrm{arrival}},t_{i,\mathrm{depart}}\) 是到、离站时段索引；\(E_i\) 是电池容量；\(\bar x_i,\bar u_i\) 是 SOC 和充电功率上限；\(\bar P\) 是站级变压器功率上限；\(\Delta T\) 是时段长度；\(\delta\) 合并充电效率和时段长度；\(\lambda\) 权衡碳排与未满足的离开 SOC。

时间离散与重叠：\(\Delta T=5\) 分钟，与 CAISO 碳强度测量对齐。到离站时刻外生且已落在格点上，式（2g）使窗口外功率严格为零；式（2c）逐槽累计能量；式（2f）保证同一时段站级总功率不超限。不存在连续会话与时段边界的重叠计算。

前提：车辆到达、离开、初始和目标 SOC 已知；不含路径；允许每槽连续调功率而非固定功率；站级总功率有限；可离线或滚动在线求解；碳强度使用平均而非边际碳强度；没有车辆路径、多车场、多趟、客户时间窗。

对本项目：目标式（2a）、SOC 式（2c）、单车功率式（2e）和站容量式（2f）可直接嵌入车场或公共站。需将外生 \(t_{i,\mathrm{arrival}},t_{i,\mathrm{depart}}\) 改为路线/多趟产生的到离站决策，并用激活/重叠约束替代式（2g）；给充电点和车辆/趟增加索引；混合车队中只对 EV 建这些变量。

## 四、方向 3：部分充电、非线性充电量和有容量充电站

### 4.1 Keskin and Çatay（2016）

出处：Keskin, M., & Çatay, B. (2016). Partial recharge strategies for the electric vehicle routing problem with time windows. Transportation Research Part C: Emerging Technologies, 65, 111–127. DOI: https://doi.org/10.1016/j.trc.2016.01.013

本机全文：

/Users/zhouleixishu/Zotero/storage/9BB85AR9/Keskin和Çatay _ 2016 _ Partial recharge strategies for the electric vehicle routing problem with time windows.pdf

原文位置：符号和完整模型见 PDF pp.4–5；小实例结果见 p.13；100 客户结果见 pp.14–15。

原式。距离目标：

$$
\min
\sum_{\substack{i\in V'_0,\ j\in V'_{N+1}\\i\ne j}}
d_{ij}x_{ij}.
\tag{1}
$$

充电量直接进入离站时间：

$$
s_i+t_{ij}x_{ij}+g(Y_i-y_i)
-(l_0+gQ)(1-x_{ij})\le s_j,
\quad i\in F',\ j\in V'_{N+1},\ i\ne j.
\tag{6}
$$

电量递推及部分充电上下界：

$$
0\le y_j\le
Y_i-(hd_{ij})x_{ij}+Q(1-x_{ij}),
\tag{11}
$$

$$
y_i\le Y_i\le Q.
\tag{12}
$$

原文变量与集合定义：\(V\) 为客户；\(F\) 为充电站，\(F'\) 为允许重复访问的站点副本；\(V'_0,V'_{N+1}\) 为扩展节点集；\(d_{ij},t_{ij}\) 为距离和时间；\(Q\) 为电池容量；\(h\) 为单位距离耗电；\(g\) 为单位能量充电时间；\(x_{ij}\) 为弧变量；\(s_i\) 为到达时刻；\(y_i\) 为到达电量；\(Y_i\) 为离开节点电量。\(Y_i-y_i\) 就是连续的部分充电量。

时间离散与重叠：没有时段集合，也没有价格/碳强度；充电持续时间是连续量 \(g(Y_i-y_i)\)。式（6）把该持续时间插入路线时钟，式（11）—（12）保证电量可行；不存在会话—时段重叠约束。

前提：单车场、同质 EV、硬时间窗、线性恒速充电、无站容量/排队、多趟、ICEV。

对本项目：可直接迁移 \(y_i,Y_i\) 与 \(Y_i-y_i\) 的部分充电量，以及将充电量加入后续到达时刻的式（6）。需给这些变量增加车辆、趟和站点类型索引，再与半小时碳/价时段的重叠量相连；增加混合车队、多车场、实体车跨趟和站容量。

### 4.2 Montoya, Guéret, Mendoza, and Villegas（2017）

出处：Montoya, A., Guéret, C., Mendoza, J. E., & Villegas, J. G. (2017). The electric vehicle routing problem with nonlinear charging function. Transportation Research Part B: Methodological, 103, 87–110. DOI: https://doi.org/10.1016/j.trb.2017.02.004

本机全文：

/Users/zhouleixishu/Zotero/storage/72THJGSQ/Montoya 等 _ 2017 _ The electric vehicle routing problem with nonlinear charging function.pdf

原文位置：符号和分段充电曲线见 PDF p.4；目标和变量见 p.5；分段线性化、充电时间和路线时钟见 pp.6–7；规模与方法见 pp.13–15。

原式。目标把行驶时间与实际充电时间相加：

$$
\min
\sum_{i,j\in V}t_{ij}x_{ij}
+\sum_{i\in F^*}\Theta_i.
\tag{1}
$$

分段凸组合：

$$
q_i=\sum_{k\in B}\alpha_{ik}a_{ik},
\tag{11}
$$

$$
s_i=\sum_{k\in B}\alpha_{ik}c_{ik},
\tag{12}
$$

原文式（13）—（17）用 \(\alpha_{ik}\)、\(\lambda_{ik}\) 保证只在相邻断点间插值。实际充电时间：

$$
\Theta_i=d_i-s_i.
\tag{25}
$$

路线时间连接：

$$
\tau_i+\Theta_j+t_{ij}x_{ij}
-(S_{\max}+T_{\max})(1-x_{ij})\le\tau_j.
\tag{27}
$$

原文变量与集合定义：\(I\) 为客户；\(F\) 为充电站，\(F^*\) 为副本；\(V\) 为所有节点；\(B\) 为非线性充电函数断点；\(a_{ik}\) 是断点电量；\(c_{ik}\) 是达到该电量的累计充电时间；\(\alpha_{ik}\) 为凸组合权重；\(\lambda_{ik}\) 为选择相邻断点段的二元变量；\(q_i,o_i\) 为到达/离开电量；\(s_i,d_i\) 为充电曲线上对应的到达/离开累计时间坐标；\(\Theta_i\) 为实际充电时长；\(\tau_i\) 为到达时刻；\(x_{ij}\) 为弧变量；\(t_{ij}\) 为行驶时间。

时间离散与重叠：没有日内价格时段；离散的是充电曲线 SOC 断点，不是时间轴。式（11）—（17）保证充电量只在一个相邻断点段内插值，式（25）得到连续充电时长，式（27）推进路线时间。不存在会话—价格时段重叠约束。

前提：同质 EV；单车场；允许部分充电；非线性充电曲线已知且以分段线性函数近似；无分时电价/碳、站容量、多趟和 ICEV。

对本项目：可直接迁移充电曲线断点、凸组合和 \(\Theta_i\)，使不同 SOC 区间的有效充电功率不再假定恒定。需再把连续区间 \([\tau_i,\tau_i+\Theta_i]\) 分解到半小时段；增加车辆类型差异、车场/公共站不同曲线、多车场、多趟和容量。

### 4.3 Froger, Jabali, Mendoza, and Laporte（2022）

出处：Froger, A., Jabali, O., Mendoza, J. E., & Laporte, G. (2022). The Electric Vehicle Routing Problem with Capacitated Charging Stations. Transportation Science, 56(2), 460–482. DOI: https://doi.org/10.1287/trsc.2021.1111

本机全文：

/Users/zhouleixishu/Zotero/storage/DS4ZEACC/Froger 等 _ 2022 _ The electric vehicle routing problem with capacitated charging stations.pdf

原文位置：本机 HAL 稿物理 PDF 页比文稿印刷页多 1 页。符号和路径模型见 PDF pp.7–9（文稿 pp.6–8）；充电站容量/排序流式（30）—（35）见 PDF pp.9–10；规模与算法见 PDF pp.20–27。

原式。路径模型目标：

$$
[F^{path}]\qquad
\min\sum_{p\in P}
\left(
t(p)x_p+\sum_{l=1}^{n(p)}(\Delta_{pl}+\nabla_{pl})
\right).
\tag{1}
$$

部分充电时长：

$$
\Delta_{pl}=\bar a_{pl}-a_{pl}.
\tag{24}
$$

会话开始和结束：

$$
\tau_p+t_{\operatorname{org}(p),cs(p,1)}x_p+\nabla_{p1}=s_{p1},
\tag{27}
$$

$$
\bar s_{p,l-1}
+t_{cs(p,l-1),cs(p,l)}x_p+\nabla_{pl}=s_{pl},
\tag{28}
$$

$$
\bar s_{pl}=s_{pl}+\Delta_{pl}.
\tag{29}
$$

同一充电站会话不重叠的排序约束：

$$
\sum_{p:cs(p,l(o))=j}s_{p,l(o)}
-\sum_{p:cs(p,l(o'))=j}\bar s_{p,l(o')}
\ge T_{\max}(u_{o'o}-1),
\tag{34}
$$

$$
f_{oo'}\le
\min\{C(o),C(o')\}u_{oo'}.
\tag{35}
$$

原文变量与集合定义：\(P\) 为候选路径；\(p\) 为一条路径；\(n(p)\) 为其充电站访问数；\(l\) 为路径上的站访问位置；\(cs(p,l)\) 是相应充电站；\(x_p\) 表示是否选路径；\(t(p)\) 为行驶时间；\(\tau_p\) 为路径起始延迟；\(a_{pl},\bar a_{pl}\) 为充电曲线上的到达/离开时间坐标；\(\Delta_{pl}\) 为充电持续时间；\(\nabla_{pl}\) 为等待；\(s_{pl},\bar s_{pl}\) 为会话开始和结束；\(O_j\) 为站 \(j\) 的充电操作；\(C_j\) 为站容量；\(u_{oo'}\) 表示操作 \(o\) 是否先于 \(o'\)；\(f_{oo'}\) 是排序网络流；\(C(o)\) 为操作所在站容量。

时间离散与重叠：所有会话起止是连续时间，不分价格段。式（27）—（29）精确定义会话区间；式（34）—（35）借助先后关系和容量流，保证共享充电资源的操作不重叠/不超容量。这里计算的是“会话—会话重叠”，不是“会话—价格时段重叠”。

前提：单车场、同质 EV、非抢占部分充电、可预订且有容量的充电站、连续时间、非线性充电；没有 TOU/碳、ICEV、多车场和多趟。

对本项目：式（27）—（35）可直接提供公共站/车场充电资源冲突控制，并保留连续会话起止。需按车场与公共站分别设容量；再将 \([s_{pl},\bar s_{pl}]\) 与半小时段求交形成分时碳/电费；增加混合车队、多车场和多趟实体车连接。

## 五、方向 4：多趟/多车场中车辆返场时刻

### 5.1 Zhen, Ma, Wang, Xiao, and Zhang（2020）

出处：Zhen, L., Ma, C., Wang, K., Xiao, L., & Zhang, W. (2020). Multi-depot multi-trip vehicle routing problem with time windows and release dates. Transportation Research Part E: Logistics and Transportation Review, 135, 101866. DOI: https://doi.org/10.1016/j.tre.2020.101866

本机全文：

/Users/zhouleixishu/Zotero/storage/4QNKCCAE/Zhen 等 _ 2020 _ Multi-depot multi-trip vehicle routing problem with time windows and release dates.pdf

原文位置：假设、符号和完整模型见 PDF pp.4–5；算法见 pp.5–10；规模与结果见 pp.12–17。

原式。总行驶时间目标：

$$
\min Z=
\sum_{k\in K}\sum_{w\in W}\sum_{i\in N}\sum_{j\in N}
t^N_{i,j}\xi_{i,j,k,w}
+
\sum_{k\in K}\sum_{w\in W}\sum_{i\in N}
t_{k,i}\mu_{k,i,w}
+
\sum_{k\in K}\sum_{w\in W}\sum_{i\in N}
t_{k,i}\eta_{k,i,w}.
\tag{1}
$$

释放时刻、返场与下一趟连接：

$$
\tau^L_{k,w}
\ge\lambda_{k,i,w}(t_i^R+t_k^D)
-M(1-\gamma_{k,w}),
\tag{10}
$$

$$
\tau^L_{k,w+1}
\ge\tau^B_{k,w}+t_k^D
-M(1-\gamma_{k,w+1}),
\tag{11}
$$

$$
\tau_{k,i,w}
\ge\tau^L_{k,w}+t_{k,i}
-M(1-\mu_{k,i,w}),
\tag{12}
$$

$$
\tau^B_{k,w}
\ge\max\{\tau_{k,i,w},e_i\}+t_i^S+t_{k,i}
-M(1-\eta_{k,i,w}),
\tag{13}
$$

$$
\tau_{k,j,w}
\ge\max\{\tau_{k,i,w},e_i\}+t_i^S+t^N_{i,j}
-M(1-\xi_{i,j,k,w}).
\tag{14}
$$

原文变量与集合定义：\(N,K,W\) 是客户、车辆和每车潜在趟次集合；\(e_i,l_i\) 是硬服务时间窗；\(t_i^R\) 是订单释放时刻；\(t_i^S\) 是服务时间；\(t^N_{i,j}\) 是客户间行驶时间；\(t_k^D\) 是车辆 \(k\) 所属车场处理时间；\(t_{k,i}\) 是该车场到客户 \(i\) 的时间；\(\tau^L_{k,w}\) 和 \(\tau^B_{k,w}\) 是趟 \(w\) 的离场和返场时刻；\(\tau_{k,i,w}\) 是到客户时刻；\(\gamma_{k,w}\) 表示是否执行该趟；\(\xi_{i,j,k,w}\) 是趟内弧变量；\(\lambda_{k,i,w}\) 表示是否服务客户；\(\mu,\eta\) 表示首、末客户。

时间离散与重叠：连续时间，没有时段集合。式（11）保证同一实体车下一趟离场不早于上一趟返场加车场作业时间，即趟间不重叠。式（13）定义返场时刻。没有充电会话或价格段。

前提：多车场、多趟、同质容量车、客户硬时间窗与订单释放时刻；每辆车固定归属一个车场；同一趟从其车场出发并返回；没有 EV、SOC、充电或分时成本。

对本项目：\(\tau^L,\tau^B\) 和式（10）—（14）可直接作为多趟时钟骨架；可把式（11）中的固定 \(t_k^D\) 改为返场充电/装卸结束时刻，并把返场后的充电区间接到下一趟离场。需按车型加入 EV/ICEV 能量状态和排放目标；为不同车场与公共站建立充电资源；保持本项目硬时间窗。

### 5.2 Zhao, Poon, Tan, and Zhang（2024）

出处：Zhao, J., Poon, M., Tan, V. Y. F., & Zhang, Z. (2024). A hybrid genetic search and dynamic programming-based split algorithm for the multi-trip time-dependent vehicle routing problem. European Journal of Operational Research, 317(3), 921–935. DOI: https://doi.org/10.1016/j.ejor.2024.04.011

本机全文：

/Users/zhouleixishu/Zotero/storage/YRTBDEXW/Zhao 等 _ 2024 _ A hybrid genetic search and dynamic programming-based split algorithm for the multi-trip time-depend.pdf

原文位置：模型、变量和目标见 PDF pp.3–4（出版 pp.923–924）；时区和多趟约束见 p.4；算法见 pp.5–9；路线变化与规模见 pp.10–12。

原式：

$$
\min
\sum_{k\in\mathcal K}\sum_{r\in\mathcal R}
\left(\tilde t_{n+1}^{k,r}-\tilde t_0^{k,r}\right)
+P\sum_{k\in\mathcal K}z_k.
\tag{1}
$$

最后一弧的返场时间：

$$
\tilde t_{n+1}^{k,r}
\ge
t_{i,n+1}^{k,r,m}
+\tau_{i,n+1}\!\left(t_{i,n+1}^{k,r,m}\right)
-M(1-x_{i,n+1}^{k,r,m}).
\tag{8}
$$

连续两趟不重叠：

$$
\tilde t_0^{k,r}-\tilde t_{n+1}^{k,r-1}\ge0,
\quad k\in\mathcal K,\ r=2,\ldots,R.
\tag{11}
$$

原文变量与集合定义：\(\mathcal K\) 为车辆；\(\mathcal R\) 为潜在趟次；\(H_{ij}^m=[w_{ij}^m,w_{ij}^{m+1})\) 为弧 \((i,j)\) 的出发时间区间；\(x_{ij}^{k,r,m}\) 表示车 \(k\) 的趟 \(r\) 是否在时区 \(m\) 走弧；\(t_{ij}^{k,r,m}\) 为相应出发时刻；\(\tau_{ij}(t)\) 为时变行驶时间；\(\tilde t_0^{k,r},\tilde t_{n+1}^{k,r}\) 为趟的离场/返场时刻；\(z_k\) 表示是否使用车辆；\(P\) 为启用车罚值。

时间离散与重叠：行驶时间函数按出发时刻区间 \(H_{ij}^m\) 分段，但离返场时刻连续。式（8）把最后一弧的时变行驶时间计入返场，式（11）精确禁止同车趟间重叠。没有充电会话。

前提：单车场、同质车、多趟、时变路况；不含 EV、充电、分时电价/碳；核心实证没有本项目的多车场和混合车队组合。

对本项目：式（8）、（11）可作为“返场时刻是决策变量”的第二套现成结构；时区 \(H_{ij}^m\) 的分段激活方法也可类比半小时碳时段。需把趟间空档细分为装卸/充电，并增加多车场归属、SOC、两类充电点和 ICEV。

## 六、边界反例：时变排队不是分时电价

### 6.1 Keskin, Çatay, and Laporte（2021）

出处：Keskin, M., Çatay, B., & Laporte, G. (2021). A simulation-based heuristic for the electric vehicle routing problem with time windows and stochastic waiting times at recharging stations. Computers & Operations Research, 125, 105060. DOI: https://doi.org/10.1016/j.cor.2020.105060

本机全文：

/Users/zhouleixishu/Zotero/storage/CCE5YQGB/Keskin 等 _ 2021 _ A simulation-based heuristic for the electric vehicle routing problem with time windows and stochast.pdf

原文位置：符号、目标和式（6）见 PDF p.3；排队二阶段模型见 pp.5–7；规模与结果见 pp.10–14。

原式：

$$
\min f(x)=
c_e\sum_{k\in K}\sum_{i\in V''}
\sum_{j\in V'_{n+1}\setminus\{i\}}d_{ij}x^k_{ij}
+c_d\sum_{k\in K}s^k_{n+1}
+c_f\sum_{j\in V'}\sum_{k\in K}x^k_{0j}.
\tag{1}
$$

$$
s_i^k+t_{ij}x_{ij}^k+g(Y_i^k-y_i^k)+\tilde x_i
-l_0(1-x_{ij}^k)\le s_j^k.
\tag{6}
$$

变量与集合：\(K\) 为 EV；\(V',V''\) 为含站点副本的扩展节点集；\(x_{ij}^k\) 是弧变量；\(s_i^k\) 是到达时刻；\(Y_i^k-y_i^k\) 是部分充电量；\(g\) 是单位能量充电时间；\(\tilde x_i\) 是期望等待时间；\(c_e,c_d,c_f\) 是能耗距离、工时和车辆固定成本系数。

时间离散与重叠：没有 TOU 时段。排队等待来自 M/G/1 与离散事件模拟，式（6）只把期望等待插入路线时钟。因此它不能作为“分时电价进入目标”的证据。

前提与迁移边界：单车场、同质 EV、硬时间窗、部分充电、随机站等待；无多趟、混合车队和分时碳/价格。它只能为公共站等待/拥堵提供补充，不能替代会话—碳时段重叠。

## 七、判断题 A：充电时刻进目标后，路线本身是否改变

明确回答：有。

1. Lin 等（2021），PDF pp.25–26，Table 7。提高放电奖励后，车辆为了在峰时放电、随后再充电而绕行。Scheme A 的夏/冬距离分别为 154.89/143.42 km；Scheme B 为 187.29/180.75 km。原文明确写明 Scheme B 比 Scheme A 平均多约 32 km，并解释为峰时放电奖励使车辆绕行到站补能。这是“分时电价进入联合路线—充放电目标后路线距离改变”的直接定量证据。

2. Miyabe 等（2025），PDF pp.14–15，Fig. 8 及正文。5 月 17 日的低碳方案与普通 VRP/普通 EVRP 路线图不同；低碳方案的充电需求增加 10%，同时排放减少 66.1%。论文没有报告这一天路线距离变化的单独数值，因此本报告不从图中估算距离。

3. Zhao 等（2024），PDF p.11（出版 p.931），Table 5。这个证据是“时变行驶时间 + 多趟”，不是充电。与恒定行驶时间模型相比，88 个实例中只有 2 个得到相同最佳路线；79 个实例通过重新选路线改进，平均目标改善 7.47%。它证明多趟出发/返场时刻进入时变成本后路线通常可变，但不能冒充充电碳目标的直接实证。

Shi 等（2025）报告 TOU 使平均充电成本下降 5.12%、利润提高 3.96%（PDF p.12），并称需要重排配送活动，但没有给出路线拓扑、距离或换边比例，故不把这两个百分比写成“路线变化幅度”。

## 八、判断题 B：加入后成本变差或没有变化的证据

明确回答：有“无变化”和“成本/距离变差”的相关失败模式；但这 11 篇中没有一篇用同一物理可行域、同一单一目标，证明“增加一个正确计入的分时碳项后全局最优的原目标必然变差”。以下只按各文原指标陈述。

1. Froger 等（2022），PDF p.26（文稿 p.25），Table 10。把充电站容量从无限改为一个充电器时，53/119 个原无容量最优解不可行；其中 4/53 改变路线数，平均目标增加 0.29%；36% 实例路线完全相同，10% 只需延迟，54% 路线改变。两个充电器时，12/120 个不可行，1/12 改变路线数，平均增加 0.16%；38% 路线相同、7% 只延迟、55% 路线改变。这里“无变化/变差”来自容量约束，不是分时价格。

2. Miyabe 等（2025），PDF p.13。普通 VRP、普通 EVRP、低碳方案的平均排放分别为 30.8、32.7、25.7 kg-CO2。普通 EVRP 因为充电绕行反而比普通 VRP 高约 6.2%；低碳联合目标则分别低 16.6% 和 21.4%。这直接说明“只加充电可行性、却不把时变碳写入目标”可能使排放变差。

3. Cheng 等（2022），PDF pp.1–2、p.7。在线碳感知方案在交付能量不变时平均减排 3.81%；调整权衡后可减排 26.00%，但总交付能量减少 12.61%。这是碳目标与服务完成度之间的明确变差项。

4. Montoya 等（2017），PDF pp.14–15。用不准确充电近似代替非线性曲线时，FS 方案平均目标高 2.70%，20 个案例中 9 个实际不可行且 3 个多用车辆；L2 平均高 1.45% 且 2 个多用路线。这是“充电时间建模不精确”的失败模式。

5. Keskin 和 Çatay（2016），PDF pp.14–15。允许部分充电的 ALNS 在总体上有改善，但部分实例的启发式解仍比全充策略差；原文说明全充解对部分充电模型本来可行，因此这些变差是启发式搜索未找到更好解，而不是部分充电模型的最优值更差。

6. Lin 等（2021），PDF pp.29–30，Table 10。时段从 60 分钟缩到 30/15 分钟后夏季总电费从 \(-9.36\) 降至 \(-47.84/-48.15\) 美分，冬季从 \(-29.74\) 降至 \(-60.19/-65.83\) 美分，但冬季距离从 143.42 增至 148.67/149.14 km，平均计算时间从 45 增至 110/160 分钟。更细的时间建模改善能源目标，同时可能增加路线距离和计算成本。

## 九、判断题 C：规模上限与求解方法

以下“上限”仅指每篇论文实际报告的最大测试规模，不推断可推广规模。

| 论文 | 报告的最大规模 | 时间段/充电维度 | 方法与结果边界 |
|---|---:|---:|---|
| Lin et al. 2021 | 启发式 35 客户、3–5 辆 EV；精确模型测试 5/10/15 客户 | 基准 19 个 60 分钟段；敏感性 38/76 个 30/15 分钟段 | CPLEX 对 5 客户通常可解，10 客户显著困难，15 客户多数失败；拉格朗日松弛 + VNS/TS 对 35 客户在 2 h 内 |
| Shi et al. 2025 | 1000 客户、100 站、160 辆车（EV/ICEV 各半） | 3 类 TOU 价格区间，连续积分 | \(\epsilon\)-约束、聚类和混合进化算法；最大实例约 8070.8 s |
| Yao et al. 2023 | 41 个节点；11/21/31 节点达到 0% 上下界差，41 节点 2 h 时差 12% | 288 个 5 分钟段 | 精确重构 + strengthened generalized Benders decomposition；41 节点触及 2 h |
| Miyabe et al. 2025 | 14–16 客户、5 个充电点、3 辆 EDV，56 个场景 | 5 分钟段；30 分钟预测细分 | Gurobi 11，6 h；到时限采用当前最好解，不应写成全部最优 |
| Cheng et al. 2022 | 每日约 5 到 40+ 辆接入车辆，单站 | 288 个 5 分钟段 | 离线凸优化与滚动在线优化；论文未报告专用求解器名称 |
| Keskin & Çatay 2016 | 100 客户；表中最多约 18 辆车 | 连续部分充电，无日内时段 | CPLEX 对 5/10/15 客户；ALNS 对 100 客户，25,000 次迭代 |
| Montoya et al. 2017 | 320 客户 | 连续时间，非线性充电曲线断点 | Gurobi 精确只做到 10 客户/3 站且给 100 h；ILS+HC 到 320 客户 |
| Froger et al. 2022 | 320 客户，1 或 2 个充电器/站设置 | 连续会话、站容量 | 路径 MILP 对小例精确；ILS 路线生成 + branch-and-cut 组装器到 320 客户，约 30 min |
| Zhen et al. 2020 | 200 客户、20 车场、40 辆车、每车最多 5 趟 | 连续离返场时间 | CPLEX 到 25 客户；30 客户在 3 h 未得可行解；HPSO/HGA 到 200 客户，HGA 最大约 8203.5 s |
| Zhao et al. 2024 | 核心 MT-TD 实例 150 客户、平均约 9.5 辆车；另测传统基准到 199 客户 | 连续时间 + 分段时变路况 | HGS + 动态规划 split + 单调队列；120–150 客户组约 853 s；Gurobi 10 客户可到 12 h |
| Keskin et al. 2021 | 100 客户 | 连续部分充电 + 随机等待 | ALNS + 离散事件模拟；25,000 次迭代、每方案 1000 次模拟 |

## 十、逐项对应本项目的迁移边界

本项目五个结构与现有文献的对应如下，仍只记录已有证据。

混合车队：Shi 等（2025）已经把 EV/ICEV 弧变量、单位距离成本和 EV 分时充电费用放在同一目标；这部分可直接迁移。其余充电论文大多只有 EV。

多车场：Zhen 等（2020）提供多车场、多趟和返场时刻；Miyabe 等（2025）的集合定义允许多个车场，但算例没有验证多车场规模。没有一篇同时给出“多车场 + 分时充电碳 + 混合车队”。

多趟：Zhen 等（2020）式（11）和 Zhao 等（2024）式（11）给出同一实体车连续趟次不重叠；需把返场后的充电会话插入两趟之间。Lin、Shi、Yao、Miyabe 都没有实体车多趟。

硬时间窗：Lin（2021）、Shi（2025）、Keskin 和 Çatay（2016）、Zhen（2020）有硬时间窗。Yao（2023）的核心机制是购买时间窗灵活性，不能原样作为本项目硬时间窗。

车场与公共站两类充电点：Miyabe（2025）算例含车场与 4 个公共站；Froger（2022）提供站容量/排队前等待的连续会话排序；Cheng（2022）提供站级总功率上限。三者需组合，单篇均未同时覆盖两类点、多趟和混合车队。

会话与半小时碳时段重叠：Lin（2021）用整段占用，Miyabe（2025）和 Cheng（2022）用细格点状态/功率，Shi（2025）用连续区间积分，Yao（2023）用连续到达 + 离散启停。若本项目要求“一次会话可跨半小时边界且按真实分钟/能量分摊”，本次 11 篇中没有一篇同时给出：连续起止、首尾分数重叠变量、与路线到达的线性连接、再乘分时碳强度的完整 MILP。最接近的是 Shi 的积分表达与 Yao 的启停连接；Froger 的连续会话起止可补资源冲突。

## 十一、取证边界

本报告没有把摘要、检索结果或二手综述当作公式证据。未取得可逐页阅读全文的候选统一列在 inaccessible.json。Keskin、Laporte 和 Çatay（2019）的“time-dependent waiting times”属于排队等待，不是 TOU；本机缺其全文，因此没有用它支持分时电价结论。所有数值均来自上述 PDF 的表、图或正文，未由图形自行测量，未运行模型或复算实验。
