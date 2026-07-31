# `paper_main.tex` 转移支付表述修订稿

目标文件：`docs/paper_v2/paper_main.tex`

状态：仅供审阅，未应用到 TeX。以下行号均指修订前文件。

## P1 摘要：第 142、146、159、163 行

原文：

```tex
以可行配送趟—实体车排班两层结构刻画多趟衔接、趟间补电、成员参与和滚动状态继承, 并综合运营与碳成本.
进一步从责任错配与跨场协同、碳感知充电择时、非线性充电物理、公平参与保障和动态需求交互五方面开展机制实验.
A two-layer structure of feasible delivery trips and physical-vehicle schedules represents multi-trip connections, inter-trip charging, participation constraints, and rolling-state inheritance while accounting for operating and carbon costs.
Mechanism experiments examine responsibility mismatch and cross-depot collaboration, carbon-aware charging timing, nonlinear charging physics, fair participation guarantees, and dynamic-demand interactions.
```

修订后：

```tex
以可行配送趟—实体车排班两层结构刻画多趟衔接、趟间补电、成员结算参与和滚动状态继承, 并综合运营与碳成本.
进一步从责任错配与跨场协同、碳感知充电择时、非线性充电物理、无转移参与与Shapley事后结算、动态需求交互五方面开展机制实验.
A two-layer structure of feasible delivery trips and physical-vehicle schedules represents multi-trip connections, inter-trip charging, settlement-based participation, and rolling-state inheritance while accounting for operating and carbon costs.
Mechanism experiments examine responsibility mismatch and cross-depot collaboration, carbon-aware charging timing, nonlinear charging physics, participation without transfers and ex-post Shapley settlement, and dynamic-demand interactions.
```

## P2 引言：第 227--230、260--261、273--284 行

原文：

```tex
系统总收益增加并不表示每个参与方都获益,
Soriano等\cite{ref:8}因此在多车场路径中显式考虑利润公平.
Shi等\cite{ref:9}进一步联合讨论协同运输计划与利润分配.
Agussurja等\cite{ref:10}研究了维持稳定且公平分配所需的最小补贴.
...
3) 协同研究重视系统成本或事后收益分配,
但客户责任结构和参与底线如何共同压缩可实现的合作价值仍不清楚.
...
1) 同时考虑多车场协同、混合车队、实体车多趟、分时充电排放、成员参与和动态订单等诸多因素,
...
4) 从算法有效性、责任错配与跨场协同、碳感知充电择时、非线性充电物理、公平参与保障、动态需求交互等角度对仿真实验进行全面分析,
```

修订后：

```tex
系统总收益增加并不表示每个参与方都获益.
Wang等\cite{ref:7}在协同路径优化后采用Shapley值分配合作收益,
Soriano等\cite{ref:8}则在多车场路径中直接考虑运营利润公平.
Shi等\cite{ref:9}进一步联合讨论协同运输计划与利润分配,
Agussurja等\cite{ref:10}研究了维持稳定且公平分配所需的最小补贴.
...
3) 协同研究分别关注系统成本、运营利润公平或事后收益分配,
但同一批合作方案在无转移自然归集与转移后结算两种口径下的参与性差异仍缺少对照.
...
1) 同时考虑多车场协同、混合车队、实体车多趟、分时充电排放、成员结算参与和动态订单等诸多因素,
...
4) 从算法有效性、责任错配与跨场协同、碳感知充电择时、非线性充电物理、无转移参与与Shapley事后结算、动态需求交互等角度对仿真实验进行全面分析,
```

## P3 问题描述：第 335--337 行

原文：

```tex
模型的优化目标是在满足载重、时间窗、电量、站点容量和参与约束的前提下,
以运营成本和碳结算成本之和最小化确定车辆路径、车型选择和充电安排,
帮助企业合理制定运输方案, 减少运输成本和碳排放.
```

修订后：

```tex
模型的优化目标是在满足载重、时间窗、电量和站点容量等运行约束的前提下,
以运营成本和碳结算成本之和最小化确定车辆路径、车型选择和充电安排;
合作成员的参与性在方案生成后的结算层判定.
```

## P4 模型假设：第 348--349 行

原文：

```tex
8) 车场收益按实际执行车辆的所属车场归集, 不考虑事后转移支付,
成员是否参与合作由收益底线约束刻画, 利润分享机制留待后续研究.
```

修订后：

```tex
8) 车场运营收益仍按实际执行车辆的所属车场归集;
在此基础上允许合作成员进行预算平衡的事后转移支付.
成员是否参与合作由转移后的结算利润相对于独立经营基准的收益下界判定,
并保留无转移的自然归集口径作为制度对照.
```

## P5 符号表：第 383--384 行后

原文：

```tex
$d(k)$ & 车辆$k$所属车场 & $\theta_d$ & 车场$d$的参与比例系数\\
$d_i^0$ & 客户$i$的原责任车场 & $\Pi_d^0$ & 车场$d$独立经营的基准收益(元)\\
```

修订后：

```tex
$d(k)$ & 车辆$k$所属车场 & $\theta_d$ & 车场$d$的参与比例系数\\
$d_i^0$ & 客户$i$的原责任车场 & $\Pi_d^0$ & 车场$d$独立经营的基准收益(元)\\
$C_I,C_U,\Delta$ & 独立经营成本、联合配送成本及系统净节省(元)
& $\phi_d$ & 车场$d$的Shapley节省分配(元)\\
$s_d,\Pi_d^{\mathrm{set}}$ & 车场$d$收到的有符号转移额及结算利润(元)
& $t_{B\to A}$ & 车场$B$向车场$A$支付的正转移额(元)\\
```

## P6 参与约束解释与结算定义：第 607--611 行后

原文：

```tex
公式(\ref{eq:stage_profit})定义车场$d$的阶段收益, 其中$G_{kp}^{e}$为模式$p$的充电总成本(即公式(\ref{eq:F5})的模式项),
$n_{kp}^{\mathrm{tr}}=\sum_{i\in N}A_{ikp}\mathbf 1_{d(k)\neq d_i^0}$为跨场服务客户数.
公式(\ref{eq:participation})为参与约束和0-1变量, $\theta_d=1$表示各车场均不劣于独立经营基准,
其中基准收益$\Pi_d^0$由同一算法在同等评价预算下, 按车场$d$仅服务自身责任客户、禁用跨场服务的独立经营情形求得;
$\bar\Pi_d^\tau$为截至上次重规划的累计收益, 静态情形取0, 其滚动累计规则见2.6节.
```

修订后：

```tex
公式(\ref{eq:stage_profit})按实际执行车辆的所属车场计算转移前运营收益,
其中$G_{kp}^{e}$为模式$p$的充电总成本(即公式(\ref{eq:F5})的模式项),
$n_{kp}^{\mathrm{tr}}=\sum_{i\in N}A_{ikp}\mathbf 1_{d(k)\neq d_i^0}$为跨场服务客户数.
式(\ref{eq:participation})的参与下界及$\theta_d=1$保持不变;
其中基准收益$\Pi_d^0$由同一算法在同等评价预算下,
按车场$d$仅服务自身责任客户、禁用跨场服务的独立经营情形求得,
$\bar\Pi_d^\tau$为截至上次重规划的累计收益, 静态情形取0, 其滚动累计规则见2.6节.

对两车场$G$和$S$, 记独立经营与联合配送的系统成本为$C_I$和$C_U$,
系统净节省为$\Delta=C_I-C_U$.
相对于独立经营基准定义节省博弈
$v(\varnothing)=v(\{G\})=v(\{S\})=0$、$v(\{G,S\})=\Delta$,
则两名成员的Shapley值为
\[
\phi_G=\phi_S=\frac{\Delta}{2}.
\]
令$s_d$为车场$d$在结算中收到的有符号转移额, 转移后的结算利润为
\[
s_d=\Pi_d^I+\phi_d-\Pi_d^U,\qquad
\Pi_d^{\mathrm{set}}=\Pi_d^U+s_d,\qquad
\sum_{d\in\{G,S\}}s_d=0.
\]
若$A$为联合配送下利润受损方、$B$为另一方, 正转移额表示$B$向$A$支付, 则
\[
t_{B\to A}=(\Pi_A^I-\Pi_A^U)+\frac{\Delta}{2}.
\]
该式先补偿联合配送造成的既有利润转移, 再由双方平分系统净节省.
式(\ref{eq:participation})在结算利润$\Pi_d^{\mathrm{set}}$上判定;
无转移对照取$s_d=0$, 两种口径均在数值实验中报告.
```

## P7 算法完整复核：第 713--716 行

原文：

```tex
每个视角将去重档案中的候选送入完整方案补全:
按统一评价函数执行车型指派、趟间衔接、非线性充电、分时电价、
时段碳排放和跨场责任核算, 并核验时间窗、载重、电量、站点容量和参与约束,
任一条件不满足的候选均判为不可行.
```

修订后：

```tex
每个视角将去重档案中的候选送入完整方案补全:
按统一评价函数执行车型指派、趟间衔接、非线性充电、分时电价、
时段碳排放和跨场责任核算, 并核验时间窗、载重、电量和站点容量等运行约束;
同时记录各车场的转移前运营收益, 供结算层计算Shapley转移和判定参与下界.
任一运行约束不满足的候选均判为不可行.
```

## P8 E6 实验：第 1479--1514 行

原文：

```tex
\subsection{公平参与约束与协同溢价}

本节比较独立经营与公平协同.
公平不是事后把总节省按比例分配,
而是在搜索和完整复算中直接记录每个成员的收益、最低成员收益和参与约束激活状态.
主要判定要求系统节省为正且所有成员收益不为负;
同时把参与约束激活率和激活条件下的公平溢价分开报告.
结果如表\ref{tab:e6-summary}和图\ref{fig:e6-fairness}所示.
%% DATA_PLACEHOLDER: E6报告参与激活率、最低成员收益、系统节省及公平溢价;不能把嵌套候选当独立样本.

\begin{table}[H]
\centering
\caption{公平参与约束与协同结果}
\label{tab:e6-summary}
\setptabsetup
\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}cccccc@{}}
\toprule
运行臂 & 系统成本(元) & 系统节省(元) & 最低成员收益(元) & 公平比 & 参与约束激活率(\%)\\
\midrule
独立经营 & --- & --- & --- & --- & ---\\
公平协同 & --- & --- & --- & --- & ---\\
\bottomrule
\end{tabular*}
\tabnote{注：公平约束在搜索阶段启用；所有成员收益和参与约束证书由独立复算器核验。}
\end{table}

\begin{figure}[H]
\centering
\IfFileExists{generated_figures/e6_fairness.pdf}{%
  \includegraphics[width=0.82\linewidth]{generated_figures/e6_fairness.pdf}%
}{%
  \fbox{\parbox[c][3.4cm][c]{0.86\linewidth}{\centering 待封存数据生成：系统成本与最低成员收益的公平边界}}%
}
\caption{公平参与约束的系统成本—成员收益边界}
\label{fig:e6-fairness}
\end{figure}
```

修订后：

```tex
\subsection{无转移参与与Shapley事后结算}

本节在同一批独立经营$I$与联合配送$U$方案上并列比较两种制度口径.
无转移口径直接以实际执行车辆所属车场的运营收益判定参与下界;
事后结算口径保持$U$的路线、车辆和充电安排不变,
按两人Shapley值在成员之间进行预算平衡转移, 再以结算利润判定参与下界.

20个算例--种子配对单元中, 无转移时$U$自然满足双方参与下界为0/20,
参与保障方案在20/20个单元回退到$I$, 两条算例行等权的公平代价为1.511784\%.
采用Shapley事后结算后, 19/20个单元满足双方参与下界;
可行单元的平均转移额为817.374757元, 每名成员相对$I$的平均净增为22.679075元.
其余1个单元为100客户算例seed 4,
$\Delta=-1.135377$元, 核区间下界1.135377元高于上界0元,
预算平衡的内部转移不能同时满足双方参与下界.
结果如表\ref{tab:e6-summary}和图\ref{fig:e6-fairness}所示.

\begin{table}[H]
\centering
\caption{无转移参与与Shapley事后结算结果}
\label{tab:e6-summary}
\setptabsetup
\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}cccccc@{}}
\toprule
制度口径 & 可参与单元 & 不合作或不可行单元 & 平均转移额(元) & 成员较$I$平均净增(元) & 公平代价(\%)\\
\midrule
无转移自然归集 & 0/20 & 20/20 & --- & --- & 1.511784\\
Shapley事后结算 & 19/20 & 1/20 & 817.374757 & 22.679075 & ---\\
\bottomrule
\end{tabular*}
\tabnote{注：Shapley转移额和成员净增的均值按19个核非空单元计算; 负协同单元保留在20个单元的可行性分母中. 结算只采用单元内预算平衡转移, 不使用外部补贴或跨单元补偿.}
\end{table}

\begin{figure}[H]
\centering
\IfFileExists{generated_figures/e6_fairness.pdf}{%
  \includegraphics[width=0.82\linewidth]{generated_figures/e6_fairness.pdf}%
}{%
  \fbox{\parbox[c][3.4cm][c]{0.86\linewidth}{\centering 待生成：无转移与Shapley事后结算的参与结果比较}}%
}
\caption{无转移与Shapley事后结算的参与结果}
\label{fig:e6-fairness}
\end{figure}
```

## P9 动态实验：第 1521--1524 行

原文：

```tex
五个运行臂为静态不重规划、顺序插入、完整动态、完整动态加公平和完整动态但碳盲.
其中协同交互报告动态需求由非原车场吸收的数量与比例,
公平交互逐阶段报告成员收益和参与状态,
时变碳交互报告车辆分工、充电动作和充电时段碳强度的变化.
```

修订后：

```tex
五个运行臂为静态不重规划、顺序插入、完整动态、完整动态加结算参与和完整动态但碳盲.
其中协同交互报告动态需求由非原车场吸收的数量与比例,
结算参与交互逐阶段报告成员的转移前运营收益、Shapley转移额、结算利润和参与状态,
时变碳交互报告车辆分工、充电动作和充电时段碳强度的变化.
```

## P10 实验讨论：第 1571--1583 行

原文：

```tex
未能同时涵盖动态订单、分时充电排放和成员参与约束.
本文建立一个涵盖上述因素的协同路径优化模型,
...
五组机制实验的方向、效应量和显著性尚待正式封存后填写.
%% DATA_PLACEHOLDER: 由适配器从五个family的统计汇总自动生成“机制作用—效应量—适用边界”讨论段.
在结果揭示前, 本文只保留待检验的问题结构:
...
公平约束的激活是否带来可量化的协同溢价,
以及动态订单是否真正激活协同、公平和时变碳三类机制.
```

修订后：

```tex
未能同时涵盖动态订单、分时充电排放和成员结算参与.
本文建立一个涵盖上述因素的协同路径优化模型,
...
E6已按同一批$I/U$方案并列报告无转移与Shapley事后结算.
无转移时20/20个单元回退到独立经营;
允许单元内预算平衡转移后19/20个单元满足双方参与下界,
表明成员运营收益迁移与系统净节省需要在结算层分别处理.
其余机制实验的方向、效应量和显著性按各自封存结果填写.
%% DATA_PLACEHOLDER: 由适配器从其余family的统计汇总自动生成“机制作用—效应量—适用边界”讨论段.
后续讨论依次回答:
...
无转移自然归集与Shapley事后结算如何改变成员参与结果,
以及动态订单是否真正激活协同、结算参与和时变碳三类机制.
```

## P11 结语：第 1603--1616 行

原文：

```tex
本文研究时变碳强度下多车场动态协同路径优化问题,
考虑多车场协同、混合车队、实体车多趟、分时充电排放、成员参与和动态订单等因素,
...
分别检验责任错配、碳感知充电、非线性物理、公平参与以及动态需求下三类机制的交互.
五组机制实验的方向、效应量、显著性和管理启示须待正式数据封存及独立复算后写入,
本稿当前不对这些机制作结果性判断.

后续研究可以对以下方面进行探索:
1) 探讨协同配送模式下各车场之间的成本和收益分配问题,
建立公平有效的利润分享机制.
```

修订后：

```tex
本文研究时变碳强度下多车场动态协同路径优化问题,
考虑多车场协同、混合车队、实体车多趟、分时充电排放、成员结算参与和动态订单等因素,
...
分别检验责任错配、碳感知充电、非线性物理、无转移参与与Shapley事后结算, 以及动态需求下三类机制的交互.
E6在同一批20个配对单元上表明, 无转移自然归集时0/20个联合方案满足双方参与下界,
采用Shapley事后结算后19/20个单元实现双方相对独立经营的利润改善.
其余机制实验的方向、效应量、显著性和管理启示按各自封存及独立复算结果写入.

后续研究可以对以下方面进行探索:
1) 将两人Shapley事后结算扩展到多车场联盟,
比较核仁、服务质量修正和多阶段结算规则.
```

## 审阅边界

- 式 `\Pi_d^\tau \ge \theta\Pi_d^{0,\tau}` 对应的参与下界形式不改，`\theta=1` 不改。
- 目标函数、路线变量、物理约束和求解流程不增加转移变量。
- 转移额在既定 I/U 方案上解析计算，属于结算层。
- `docs/paper_v2/paper_main.tex` 及其他 TeX 文件均未修改。
