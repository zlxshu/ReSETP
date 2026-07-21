# 论文V2 数学审计报告 (China81 重写版)

- 通过: 35
- 警告: 1
- 错误: 0

## 通过项

- PASS A1 线性电耗符号推导: eq:electricity 展开减 eq:linear_energy = 0 (应为0)
- PASS A2 功率量纲: ½cDρAv³:[kg/m³][m²][m³/s³]=kg·m²/s³=W; (m+u)g0cRv:[kg][m/s²][m/s]=W
- PASS B1 时长退化式: L=1: Δ=3600.000s == 3600·E/π=3600.000s
- PASS B2 NL90满充闭式: Δ=6600.0s == 1.1·3600B/π=6600.0s
- PASS B3 重叠恒等式: 500组随机会话: Σ_t g_qt == Δ_q
- PASS B4 能量守恒: 500组随机会话(含NL90): Σ_t y_qt == E^ch
- PASS B5 择时候选集最优性: 120组随机(恒功率+NL90)中候选集劣于稠密网格的组数=0 (应为0)
- PASS C1 标签唯一: 重复标签: 无
- PASS C2 引用闭合: 未定义的\ref: 无
- PASS C4 旧口径[AlgoTBD]: 算法占位名残留
- PASS C4 旧口径[\pounds]: 英镑符号残留
- PASS C4 旧口径[£]: 英镑残留
- PASS C4 旧口径[NESO]: 英国电网源残留
- PASS C4 旧口径[GRIDSERVE]: 英国充电价残留
- PASS C4 旧口径[9个网络]: 旧UK实验口径残留
- PASS C4 旧口径[UCB]: 旧ALNS内部机制残留
- PASS C5 符号表[A_{ikp}]: 关键符号在表2登记
- PASS C5 符号表[O_{skpt}]: 关键符号在表2登记
- PASS C5 符号表[a_q^{\mathrm{ch}}]: 关键符号在表2登记
- PASS C5 符号表[y_{qt}]: 关键符号在表2登记
- PASS C5 符号表[E_q^{\mathrm{ch}}]: 关键符号在表2登记
- PASS C5 符号表[\Delta_q]: 关键符号在表2登记
- PASS C5 符号表[p_{s,t}^{e}]: 关键符号在表2登记
- PASS C5 符号表[\rho]: 关键符号在表2登记
- PASS C5 符号表[\Pi_d^0]: 关键符号在表2登记
- PASS C5 符号表[\theta_d]: 关键符号在表2登记
- PASS C5 符号表[\kappa_l]: 关键符号在表2登记
- PASS C5 符号表[\Omega_k]: 关键符号在表2登记
- PASS C5 符号表[\overline W,T^{\mathrm{int}}]: 关键符号在表2登记
- PASS C6 占位符盘点: 共 39 处 DATA_PLACEHOLDER 待实验回填
- PASS D1 载重传播: 初始500.0→服务后0.0 (递减到0)
- PASS D2 电量传播: ε_j=45.0 ∈ [0,100.0]
- PASS D3 超容检测: 补电至超过B的方案应不可行(80+30>100)
- PASS D4 集合划分语义: 最优组合=('r3',), 成本=17.0 (r1+r2同车冲突被排除, r3=17优于不可行的19)
- PASS E1 配额仿射性: F1 中配额 CE 为常数项: 不改变任意两方案的成本差(决策无关), 仅影响结算金额——正文对碳交易的表述须与此性质一致(4.3节报告结算效应)

## 警告项

- WARN C3 公式标签使用: 未被引用的公式标签: ['eq:F2', 'eq:F3', 'eq:F4', 'eq:F6', 'eq:charge_window', 'eq:charging-candidates', 'eq:charging-rule', 'eq:linear_energy', 'eq:sp-recombination']
