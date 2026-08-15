#!/usr/bin/env python3
"""Rewrite constraints: every constraint gets its own equation environment."""

filepath = "/Volumes/移动硬盘（512G）/ReSETP/docs/paper_v2/RETIRED_paper_main.tex"
with open(filepath, 'r') as f:
    content = f.read()

old_start = r"""\subsection{模型建立}

本文模型以运输总成本最小化为目标, 综合考虑碳排放成本、固定成本、里程成本、
油耗成本、充电成本和跨场责任成本.
\begin{equation}
\min F = F_1+F_2+F_3+F_4+F_5+F_6. \label{eq:total_cost}
\end{equation}

对趟$r$, 令$V_r=N\cup S\cup\{d_r^+,d_r^-\}$, $d_r^+$和$d_r^-$为源、汇车场副本"""

old_end = r"""\section{算法设计}"""

start_idx = content.find(old_start)
end_idx = content.find(old_end)

if start_idx == -1 or end_idx == -1:
    print(f"ERROR: start={start_idx}, end={end_idx}")
    exit(1)

new_constraints = r"""\subsection{模型建立}

本文模型以运输总成本最小化为目标:
\begin{equation}
\min F = F_1+F_2+F_3+F_4+F_5+F_6. \label{eq:total_cost}
\end{equation}

对趟$r$, 令$V_r=N\cup S\cup\{d_r^+,d_r^-\}$, $d_r^+$和$d_r^-$为源、汇车场副本,
$x_{ijr}=1$表示趟$r$使用弧$(i,j)$, $a_{ir}=1$表示趟$r$服务客户$i$.
\begin{equation}
\sum_{j\in V_r\setminus\{d_r^+\}}x_{d_r^+jr}=1,\quad
\sum_{i\in V_r\setminus\{d_r^+\}}x_{id_r^+r}=0.
\label{eq:depot_source}
\end{equation}
\begin{equation}
\sum_{i\in V_r\setminus\{d_r^-\}}x_{id_r^-r}=1,\quad
\sum_{j\in V_r\setminus\{d_r^-\}}x_{d_r^-jr}=0.
\label{eq:depot_sink}
\end{equation}
\begin{equation}
\sum_{j\in V_r}x_{jir}=\sum_{j\in V_r}x_{ijr}=a_{ir},\qquad i\in N.
\label{eq:flow_conservation}
\end{equation}

令$L_{ir}$为车辆离开节点$i$时的剩余载重, $q_i$为客户$i$的需求量.
\begin{equation}
L_{d_r^+r}=\sum_{i\in N}q_i a_{ir}.
\label{eq:load_initial}
\end{equation}
\begin{equation}
0\le L_{ir}\le Q,\qquad i\in V_r.
\label{eq:load_bounds}
\end{equation}
\begin{equation}
-Q(1-x_{ijr})\le L_{jr}-L_{ir}+q_j\le Q(1-x_{ijr}),\qquad i,j\in V_r.
\label{eq:load_propagation}
\end{equation}

令$T_{ir}$为服务开始时刻, $\sigma_i$为节点占用时长, $t_{ij}$为行驶时间,
$[\underline t_i,\overline t_i]$为客户时间窗.
\begin{equation}
\underline t_i a_{ir}\le T_{ir}\le \overline t_i+M(1-a_{ir}),\qquad i\in N.
\label{eq:time_window}
\end{equation}
\begin{equation}
T_{jr}\ge T_{ir}+\sigma_i+t_{ij}-M(1-x_{ijr}),\qquad i,j\in V_r.
\label{eq:time_propagation}
\end{equation}

对电动车趟, $\varepsilon_{ir}$为到达节点$i$时的电量, $Y_{ir}$为补电量(非充电节点取0),
$e_{ij}$按式(\ref{eq:electricity})--(\ref{eq:ev_energy_fixed_speed})计算.
\begin{equation}
B^{\min}\le\varepsilon_{ir}\le B,\qquad i\in V_r.
\label{eq:battery_bounds}
\end{equation}
\begin{equation}
-M(1-x_{ijr})\le\varepsilon_{jr}-\varepsilon_{ir}-Y_{ir}+e_{ij}
\le M(1-x_{ijr}),\qquad i,j\in V_r.
\label{eq:battery_propagation}
\end{equation}

模式$p$中相邻配送趟$r_h,r_{h+1}$之间的趟间衔接满足:
\begin{equation}
0\le Y_h^D\le B-\varepsilon_{r_h}^{\rm end}.
\label{eq:intertrip_energy}
\end{equation}
\begin{equation}
\varepsilon_{r_{h+1}}^{\rm start}=\varepsilon_{r_h}^{\rm end}+Y_h^D.
\label{eq:intertrip_energy_link}
\end{equation}
\begin{equation}
t_{r_{h+1}}^{\rm out}\ge t_{r_h}^{\rm in}+\frac{3600Y_h^D}{\pi_{d(k)}},\qquad
\text{燃油车取}Y_h^D=0.
\label{eq:intertrip_time}
\end{equation}

以上约束定义并复核可行模式, 主问题通过模式变量$z_{kp}$间接引用.
\begin{equation}
\sum_{k\in K}\sum_{p\in\Omega_k}A_{ikp}z_{kp}=1,\qquad i\in N.
\label{eq:customer_coverage}
\end{equation}
\begin{equation}
\sum_{p\in\Omega_k}z_{kp}\le1,\qquad k\in K.
\label{eq:vehicle_pattern}
\end{equation}
\begin{equation}
\sum_{k\in K}\sum_{p\in\Omega_k}O_{skp}(u)z_{kp}\le C_s,\qquad s\in S\cup D,\; u\in[0,H).
\label{eq:station_capacity}
\end{equation}

车场$d$的阶段经营收益由该车场车辆完成客户所获收入减去归集成本:
\begin{align}
\Pi_d^{\mathrm{stage}}&=\sum_{k\in K_d}\sum_{p\in\Omega_k}\Bigl(\sum_{i\in N}R_iA_{ikp}
-C_{kp}^{\mathrm{op}}-C_{kp}^{\mathrm{tr}}-p^{\mathrm{car}}\widehat E_{kp}\Bigr)z_{kp}
+p^{\mathrm{car}}CE_d,
\label{eq:stage_profit}\\
\Pi_d&=\bar\Pi_d+\Pi_d^{\mathrm{stage}}.
\label{eq:cumulative_profit}
\end{align}
其中$R_i=\rho q_i$为配送收入, $C_{kp}^{\mathrm{op}}$为模式直接运营成本.
\begin{equation}
\Pi_d\ge\theta_d\Pi_d^{0},\qquad d\in D.
\label{eq:participation}
\end{equation}
\begin{equation}
z_{kp}\in\{0,1\},\qquad k\in K,\; p\in\Omega_k.
\label{eq:binary}
\end{equation}

公式(\ref{eq:total_cost})表示运输总成本最小化;
公式(\ref{eq:depot_source})--(\ref{eq:depot_sink})保证车辆从源车场出发并返回汇车场;
公式(\ref{eq:flow_conservation})保证客户访问满足流守恒;
公式(\ref{eq:load_initial})--(\ref{eq:load_propagation})保证配送全程不超过载重容量且载重按服务次序逐弧递减;
公式(\ref{eq:time_window})--(\ref{eq:time_propagation})保证服务开始时刻满足硬时间窗约束且时间逐弧递推;
公式(\ref{eq:battery_bounds})--(\ref{eq:battery_propagation})保证电量在允许范围内并逐弧传播;
公式(\ref{eq:intertrip_energy})--(\ref{eq:intertrip_time})保证同一车辆相邻趟次之间的电量与时间衔接;
公式(\ref{eq:customer_coverage})保证每个客户只服务一次;
公式(\ref{eq:vehicle_pattern})保证每车至多选择一个全天模式;
公式(\ref{eq:station_capacity})保证充电站并发充电数不超过站点容量;
公式(\ref{eq:stage_profit})--(\ref{eq:cumulative_profit})定义车场经营收益的归集;
公式(\ref{eq:participation})定义合作参与底线, $\theta_d=1$表示各车场均不劣于独立经营基准;
公式(\ref{eq:binary})表示0-1变量.

"""

content = content[:start_idx] + new_constraints + content[end_idx:]

with open(filepath, 'w') as f:
    f.write(content)

print(f"Constraints rewritten. {len(new_constraints)} chars")
