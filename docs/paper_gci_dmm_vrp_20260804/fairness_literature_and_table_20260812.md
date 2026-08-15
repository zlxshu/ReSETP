FAIRNESS_DONE

# 公平文献取证与候选表骨架

本报告只逐篇记录原文中实际存在的定义、度量、比较状态、求解做法和结果表。下文没有把两篇论文拼成一个新的上位分类，也没有把文献综述中提到的方法写成作者自己的方法。三个候选是彼此独立的论文定位选项，不是“该领域的三层体系”，也不是用户已经作出的决定。

## 一、逐篇抽取（含页码、式号、图号原文照录）

### 1. Soriano, Gansterer, Hartl (2023)

**文献身份。** Soriano, A., Gansterer, M., Hartl, R. F. (2023), *The multi-depot vehicle routing problem with profit fairness*, *International Journal of Production Economics*, 255, 108669，DOI `10.1016/j.ijpe.2022.108669`。本地全文：`/Users/zhouleixishu/Zotero/storage/PLSR8GG4/Soriano 等 _ 2023 _ The multi-depot vehicle routing problem with profit fairness.pdf`；PDF 13 页，PDF 页码与论文印刷页码一致；SHA-256：`07bf3ac92303eab0b7d9e713606334b1db262097692eeedce6942056392544e2`。

#### 1.1 公平怎样定义

`FACT`（p.2、p.4）：作者把公平目标写成“最大化所有车场中，相对独立经营解的最差利润变化”。对车场 \(d\in\mathcal D\)，利润变化率是

\[
\hat p_d=\frac{P_d}{P_d^0},
\]

其中 \(P_d\) 是合作解中车场 \(d\) 的利润，\(P_d^0\) 是该车场独立经营解中的利润。公平目标为 p.4 式（2）：

\[
\max\left(\min_{d\in\mathcal D}\left\{\frac{P_d}{P_d^0}\right\}\right).
\tag{2}
\]

车场利润由 p.4 式（9）计算：

\[
P_d=
\sum_{i,j\in\mathcal N}\sum_{h\in\mathcal H}\sum_{k\in\mathcal K_{dh}}
(r_i-c_{ij})x_{ij}^k,
\tag{9}
\]

其中 \(r_i\) 是客户 \(i\) 的服务收入，\(c_{ij}\) 是弧 \((i,j)\) 的行驶成本，\(x_{ij}^k\) 表示车辆 \(k\) 是否经过该弧。

`FACT`（p.4）：作者用自适应 ε-constraint 方法时，保留成本最小化目标，把公平目标改写成 p.4 式（11）的利润下界：

\[
P_d\geq \hat P\,P_d^0,\qquad d\in\mathcal D,
\tag{11}
\]

其中 \(\hat P\) 是每个车场必须达到的最低利润变化率。p.5 明确写明：当 \(\hat P\geq 1\) 时，所有伙伴的合作利润均不低于独立经营利润。

`FACT`（p.9）：跨整个规划期汇总利润的是作者所称的 `horizon fairness`。作者另定义逐日最低利润比率：

\[
\Pi(S)=\min_{d\in\mathcal D,\,h\in\mathcal H}
\left\{\frac{P_{d,h}}{P_{d,h}^0}\right\},
\tag{17}
\]

并把逐日公平目标写成 p.9 式（(2^*)）：

\[
\max\left(\min_{d\in\mathcal D,\,h\in\mathcal H}
\left\{\frac{P_{d,h}}{P_{d,h}^0}\right\}\right).
\tag{2*}
\]

#### 1.2 作者实际使用的度量

`FACT`（§5.3，p.7）：作者明确列出六项前沿度量；这些式子没有独立式号。

1. **Fairness Cost**

\[
\frac{1}{|\{\hat P_i\}|}
\sum_{i=1}^{|\{\hat P_i\}|}
\frac{
\bigl(\phi(S^{\hat P_{i+1}})-\phi(S^{\hat P_i})\bigr)/\phi(S^{\hat P_i})
}{\hat P_{i+1}-\hat P_i}.
\]

原文文字把它称为：相对成本最小解 \(S^-\)，公平约束每提高 0.01 时的平均成本增量（percentage points）。但展示式以相邻解 \(\phi(S^{\hat P_i})\) 为分母，没有显式乘以 0.01，且求和末项还会访问 \(i+1\)。这三处在原文中没有被解释；本报告不替作者补写一个无歧义版本。

2. **(S^-) Fairness Rate Difference**

\[
\frac{\max_{d\in\mathcal D}\{\hat p_d\}}
{\min_{d\in\mathcal D}\{\hat p_d\}}.
\]

原文称它度量成本最小解 \(S^-\) 中最大与最小利润变化率的尺度差。需要同时保留一个原文内部矛盾：按该展示式所得值不可能小于 1，但 Table B.1 报有 0.167、0.191、0.357 等小于 1 的 `FairDiff`；论文没有说明数表是否另用了 \(\max/\min-1\) 或其他口径。

3. **All Better-Off Cost Difference**

若 \(\hat P_i\) 是前沿中首个满足 \(\hat P_i\geq 1\) 的公平水平，则

\[
\frac{\phi(S^{\hat P_i})-\phi(S^-)}{\phi(S^-)}.
\]

4. **(S^+) Minimum Fairness Rate**

\[
\min_{d\in\mathcal D}\left(\frac{P_d}{P_d^0}\right).
\]

5. **(S^+) Cost Difference**

\[
\frac{\phi(S^+)-\phi(S^-)}{\phi(S^-)}.
\]

6. **#Solutions**：近似 Pareto 前沿中的解数。

`FACT`（p.9–10）：作者还实际报告了以下量，但没有把它们并入新的分类体系：

- Table 3 的 `Total customers served` 与 `Original customers kept` 两类客户重分配率；正文给出文字口径，没有编号公式。
- Table 4 的车辆受限成本最小解平均公平率 `VL-\(\hat P\)`，以及它相对“原始 MDVRP-PF 中同等公平率解”的平均成本差 \(\hat c\)（percentage points）。
- 式（17）的逐日最低利润比率 \(\Pi(S)\)。
- Fig. 5–6 的相对独立经营成本比 \(\Phi(S)/\Phi(S^0)\)。

#### 1.3 作者实际使用的求解或分配做法

`FACT`（p.4–7）：作者自己的求解做法是：保留成本最小化式（1），用式（11）逐步提高最低利润率 \(\hat P\)；先求公平不受限的 \(S^-\)，令

\[
\mu=\min_d\{P_d/P_d^0\},\qquad \hat P=\mu+\epsilon,
\]

然后反复求解，直到公平最大解 \(S^+\)。正式实验取 \(\epsilon=0.005\)（p.7）。每个单目标子问题由 ALNS 加局部搜索求解：

- p.6 删除算子：`Random`、`Worst`、`Related`、`Route`、`Historical`、`Proximity`；
- p.6 插入算子：`Greedy Insertion`、`Regret-2 Insertion`、`Regret-3 Insertion`；
- p.6 局部搜索：`Relocate`、`Swap`、`2-Opt*`。

`FACT`（§5.4，p.9）：作者还实测了一个替代做法——把每个伙伴的可用车辆数限制为其独立经营解实际使用的车辆数，再与原始、车辆数不受该限制的 MDVRP-PF 比较。

`FACT`（§5.5，p.9–10）：作者比较 `horizon fairness` 与 `daily fairness`。

`FACT`（p.2–3）：Fig. 1 用转移支付解释不同解，但 MDVRP-PF 模型没有转移支付变量。作者明确说其分析独立于可能存在的转移支付，也没有把自己的方法称为传统成本/利润分摊方法的替代品。文献综述在 p.3 提到 Wang et al. (2017) 的 `improved Shapley value` 和 van Zon et al. (2021) 的 `core allocations`；这两项不是 Soriano 自己实验采用的方法。全文未出现 `nucleolus`，因此本报告不写“核仁”。

#### 1.4 作者实际比较的解状态或方案

`FACT`（Fig. 1，p.3）：五个子图的原文标题逐一为：

1. `(a) Graph with distances`
2. `(b) Stand-alone solution`
3. `(c) Cost-minimal solution`
4. `(d) Solution with fairness and transfer payments`
5. `(e) Solution with fairness and no transfer payments`

Fig. 1 图题第一句为 `Possible solutions to a coalition problem, from the cost-minimal solution to the fairness-maximal one.`；其后还说明圆形/三角形代表各伙伴的车场和原属客户，以及转移支付的字形标法。

`FACT`（Fig. 2，p.5）：图题为 `Solution types within a Pareto front. Each solution is characterized by its fairness objective value.` 图中和正文使用：

- \(S^0\)：各车场、各期分别求解的独立经营解；
- \(S^-\)：公平不受限的成本最小解；
- \(S^{\hat P}\)：给定最低公平水平 \(\hat P\) 的解；图中示例标为 \(S^{1.04}\)；
- `All partners better-off`：\(\hat P=1\) 右侧的区域；
- \(S^+\)：公平最大解；
- `ABOff`：Table 3 的简写，对应 §5.3 所述前沿中首个满足 \(\hat P\geq1\) 的解；论文没有另给一个名为 ABOff 的定义式。

`FACT`：作者还直接比较车辆受限与原始 MDVRP-PF（Table 4，p.9）、`Horizon Fairness` 与 `Daily Fairness`（Fig. 6，p.10），以及 ALNS-PF、PR-ALNS、HGSADC（Appendix A）。论文没有把这些对象整理成“分配机制/公平判据/实现方式”之类的上位层级。

#### 1.5 结果表的真实结构

`FACT`：全文结果表和相关非结果表如下。

- **Table 1，p.7，`General parameters.`** 不是公平结果表。列为 η、τ、ρ、μ₁、μ₂、μ₃、Γ⁰、(N_{IT})。
- **Table 2，p.8，`ALNS operators relevance and performance.`** 列组 `Removal` 下为 Random、Worst、Related、Route、Historical、Proximity；列组 `Insertion` 下为 Greedy、Regret。行是 `Cost dev.` 与 `% Utiliz.`，均为百分比。
- **Table 3，p.9，`Averaged customer redistribution rates per data type and size for the three key solutions in the Pareto front.`** 行组为 C_B、C_U、U_B、U_U，每组含 \(S^-\)、ABOff、\(S^+\)。顶层列是 `Total customers served` 和 `Original customers kept`；每组下分 2D_100C、3D_150C、4D_200C，再各分 avg、max、min；数据均为百分比。C_B 中 \(S^-\) 已全员不劣，所以原表的 \(S^-\) 与 ABOff 行相同；论文不保证 ABOff 必为一个不同于 \(S^-\) 的解。
- **Table 4，p.9，`Comparison of results for the MDVRP-PF with limited vehicles and original MDVRP-PF with unlimited vehicles.`** 行为 C_B、C_U、U_B、U_U；列为 `VL-\(\hat P\)`（无量纲）和 \(\hat c\)（percentage points）。
- **Table A.1，p.11，`Detailed results on benchmark MDVRP instances.`** 行为 p01–p23，末行 avg；列组为 PR-ALNS、HGSADC、ALNS，每组含 Avg、T (min)、Best。
- **Table A.2，p.11，题名首句 `Summary of results grouped and averaged by instance size.`** 行为七个实例规模组，末行为总计；列为 Instances、#Cust、ALNS-PF/#Best，以及相对 PR-ALNS 和 HGSADC 的 `% Avg`、`% T (min)`。
- **Table B.1，p.12，`Averaged MDVRP-PF results by instance class and sizes.`** 行组为 C_B、C_U、U_B、U_U，每组含 2D_100C、3D_150C、4D_200C；列为 `Inst class & Size`、`Fair_Cost`、\(S^-\) `FairDiff`、`B-Off cost`、\(S^+\) `MinRate`、\(S^+\) `Cost`、`#Sol`。`Fair_Cost` 的文字单位是每增加 0.01 公平要求的平均成本增量（percentage points）；`B-Off cost`、\(S^+\) `Cost` 为百分比；`FairDiff`、`MinRate` 为无量纲数值；`#Sol` 是同一实例类型与规模下的平均近似前沿解数，所以可为小数。

### 2. Sobhanan, Charkhgard, Dayarian：Zotero 条目与实际 PDF 分版本记录

#### 2.1 文件和版本身份

`FACT`：Zotero 主条目 key `L7JVNX7E` 的元数据仍是 2024 年 SSRN 预印本，DOI `10.2139/ssrn.4909090`。PDF 子附件 key 是 `R9NCAMNZ`，本地文件为 `/Users/zhouleixishu/Zotero/storage/R9NCAMNZ/Sobhanan 等 _ 2024 _ Equity-Driven Workload Allocation for Crowdsourced Last-Mile Delivery.pdf`。

`CORRECTION`：该本地 PDF 的实际内容不是 2024 预印本，而是 2026 年正式发表版：Sobhanan, A., Charkhgard, H., Dayarian, I. (2026), *Equity-Driven Workload Allocation for Crowdsourced Last-Mile Delivery*, *Production and Operations Management*, 35(8), 3180–3203，DOI `10.1177/10591478261425875`。全文 24 页；PDF 第 1 页对应印刷页 3180；SHA-256：`68fca80217b9c582d49a440eaf149ffa33edab1de0eed40374ec9c5459548755`。

`FACT`：作者还在 Optimization Online 保存了 2024 年 40 页预印本，URL 为 `https://optimization-online.org/wp-content/uploads/2024/07/EquityDrivenLMD.pdf`，本轮下载副本 SHA-256 为 `7b28a441f1c9366f2bcf6fceb36df83058d0684b8ec0799833916e202117d789`。正式版印刷页 3187 把五个公平度量公式指向在线补充 EC.2；本地正式版 PDF 不含 EC.2。以下正文、结果表和页码以 2026 正式版为准；五个展开式明确标为 2024 预印本 Appendix A，不把预印本页码冒充正式版页码。

#### 2.2 公平怎样定义

`FACT`：正式版唯一的 `Definition 1` 定义的是 `proper mapping`，不是公平。它要求：把 (M+1) 维目标空间压到二维后，二维空间中的每个 Pareto 最优解仍是原 (M+1) 维空间的 Pareto 最优解（PDF 第 4 页/印刷 p.3183）。因此不能把 Definition 1 写成该文的“公平定义”。

`FACT`（PDF 第 2 页/印刷 p.3181）：作者用文字说明，公平工作量分配要让配送员在系统条件与个人能力基础上获得相等的利润机会。

`UNKNOWN`：正式版未找到一个以 `equity` 或 `fairness` 命名的编号定义式；该文实际给出的是下面的 adjusted-profit 效用式（1）、五种 equity measure 和双目标式（2a），不能把 `Definition 1` 改称公平定义。

`FACT`（§4.3，PDF 第 7–8 页/印刷 p.3186–3187）：作者自己明确区分两个概念：

- **Equity Metric**：代理人的效用函数，即希望被拉平的量；作者举例为利润、路线长度等。
- **Equity Measure**：评价已经实现的公平程度的数学函数；作者举例为极差、标准差等。

这一区分只照录到这里，不再由本报告往上增加第三层或新的总框架。

`FACT`（式（1），PDF 第 8 页/印刷 p.3187）：作者在本文实际拉平的量是每个配送员的 `adjusted profit`。令

\[
\mathcal N_m(x)=\{j\in\mathcal N:\exists i\in\bar{\mathcal N}\text{ 使得 }x_{ijm}=1\},
\]

则

\[
u_m(x)=
\left(\frac{\sum_{i\in\mathcal N_m(x)}p_i}{Q_m}\right)
\left(\frac{\sum_{i\in\mathcal N_m(x)}q_i}{Q_m}\right),
\tag{1}
\]

其中 \(p_i\) 是完成订单 \(i\) 的配送报酬，\(q_i\) 是订单量，\(Q_m\) 是配送员 \(m\) 的车辆容量，\(x_{ijm}\) 表示配送员 \(m\) 是否走弧 \((i,j)\)。由于作者设 \(p_i=\beta q_i\)，同页又写成

\[
u_m(x)=\beta\left(\frac{\sum_{i\in\mathcal N_m(x)}q_i}{Q_m}\right)^2.
\]

作者的成立条件是：平台全额补偿里程成本；一个 zone-wave 内的时间被视为已标准化；配送员之间剩余的差异资源是车辆容量（p.3186–3187）。

`FACT`（p.3187）：正式版实际考察的公平度量集合为

\[
\mathbb{EM}(x)\in
\{\operatorname{Range}(x),\operatorname{MAD}(x),\operatorname{SD}(x),
\operatorname{CV}(x),\operatorname{GINI}(x)\}.
\]

双目标模型为 PDF 第 9 页/印刷 p.3188 式（2a）：

\[
\min\{\mathbb C(x),\mathbb{EM}(x)\},
\tag{2a}
\]

其中

\[
\mathbb C(x)=\sum_{i\in\bar{\mathcal N}}\sum_{j\in\mathcal N}\sum_{m\in\mathcal M}c_{ij}x_{ijm}
\]

是平台承担的总路由成本，\(\mathbb{EM}(x)\) 是 adjusted profits 的差异。

#### 2.3 作者实际使用的五种公平度量原式及 Gini 快捷式

`FACT`：下面五种度量及 Gini 的升序快捷式来自同篇 **2024 预印本 Appendix A**。位置为预印本 PDF 第 30 页/Appendix 内部 p.1 的式（4）–（7），以及 PDF 第 31 页/Appendix 内部 p.2 的式（8）–（9）。预印本以 \(\bar p_m(x)\) 表示 adjusted profit，以

\[
\bar p(x)=\frac{\sum_{m\in\mathcal M}\bar p_m(x)}{M}
\]

表示其均值；正式版把单个配送员的符号改成了 \(u_m(x)\)，不能静默混用两个版本的符号。

1. **Range，式（4）**

\[
\operatorname{Range}(x)=
\max_{m\in\mathcal M}\bar p_m(x)-
\min_{m\in\mathcal M}\bar p_m(x).
\tag{4}
\]

2. **Mean Absolute Deviation (MAD)，式（5）**

\[
\operatorname{MAD}(x)=
\frac{\sum_{m\in\mathcal M}|\bar p_m(x)-\bar p(x)|}{M}.
\tag{5}
\]

3. **Standard Deviation (SD)，式（6）**

\[
\operatorname{SD}(x)=
\sqrt{\frac{\sum_{m\in\mathcal M}(\bar p_m(x)-\bar p(x))^2}{M}}.
\tag{6}
\]

4. **Coefficient of Variation (CV)，式（7）**

\[
\operatorname{CV}(x)=\frac{\operatorname{SD}(x)}{\bar p(x)}.
\tag{7}
\]

5. **Gini Coefficient (GINI)，式（8）**

\[
\operatorname{GINI}(x)=
\frac{
\frac{1}{2M^2}\sum_{m\in\mathcal M}\sum_{l\in\mathcal M}
|\bar p_m(x)-\bar p_l(x)|
}{\bar p(x)}.
\tag{8}
\]

adjusted profits 按升序排列后，作者给出的快速计算式为

\[
\operatorname{GINI}(x)=
\frac{\sum_{l\in\mathcal M}(2l-M-1)\bar p_l(x)}
{M\sum_{m\in\mathcal M}\bar p_m(x)}.
\tag{9}
\]

`FACT`（正式版 p.3184、3187）：Theorem 1 证明，若 \(u(I)\) 随 \(\sum_{i\in I}q_i\) 增加，则任一公平度量都保证 proper mapping；Observation 1 指出本文的 \(u_m(x)\) 满足该单调性；Proposition 1 因而说本文效用函数与任一公平度量组合都提供 proper mapping。作者随后仍用计算实验比较五个度量，并未说它们的实际效果相同。

`FACT`（p.3189–3199）：作者还实际使用以下算法或结果指标，但它们不是新的公平度量：`Cardinality` 是近似非支配点数量；`Hypervolume (HV)` 在固定 reference point 下度量近似前沿支配区域，值越大表示近似越好；Table 8/11 报 `Improvement in CV (%)`；Fig. 5 报 `Cost Increase Ratio (CIR)`，正文只用文字说明它是相对最少配送员情形的成本增减比例；正文未给 CIR 的编号公式。

`FACT`（p.3196）：作者把 opportunity cost 写成公平感知解与 least-cost 解之间 adjusted profit 的 gain/loss；Table 9 用 \(\bar u_L\) 和 \(\bar u_H\) 分别展示低表现与高表现配送员的平均 adjusted profit。正文 p.3181 另用文字区分 operational cost 与 opportunity cost，但没有把它们写成新的公平度量。

#### 2.4 作者实际使用的求解或分配做法

`FACT`（Fig. 1 与正文，PDF 第 6 页/印刷 p.3185）：每个 zone-wave 依次求两个问题：

1. `crowdshipper selection problem`：按 first-come, first-served 选择完成全部订单所需的最少配送员；作者称其为 bin-packing 变体。
2. `workload allocation problem`：在已选配送员之间联合决定工作量分配与路线，并处理成本—公平权衡。

Figure 1 的原文图题为 `An outline of the dispatch zone-wave problem (DZWP) optimization workflow.`

`FACT`（2024 预印本 PDF 第 31–32 页/Appendix 内部 p.2–3）：选择问题的目标为

\[
\min\sum_{m\in\bar{\mathcal M}}z_m,
\tag{10a}
\]

并以客户唯一分配、容量约束及 (z_{m+1}\le z_m) 保证最少人数与先到先得。正式版把完整式移入在线补充 EC.1。

`FACT`（§5.1，p.3188–3189）：工作量分配用 `HYBRIDNSGAII` 近似非支配前沿。它结合 NSGA-II 与 Multi-Directional Local Search；采用 giant-tour + breakpoint 表示；用 Clarke–Wright、sweep、nearest-neighbor 和随机方法初始化；使用二元锦标赛、序列交叉、变异、Large Neighborhood Search、workload reassignment、不可行解修复/独立种群、自适应罚项和 diversity score。

`FACT`（§5.2，p.3190）：作者以 \(\gamma\) 表示平台允许相对最低成本增加的上限，并称其为 `equity budget`。在该成本上限内，选择公平值最好的可行非支配点。

`FACT`（§6，p.3190）：作者分别用五个度量生成前沿，再把每条前沿的解映射到其余 `cost + equity measure` 空间，删除映射后的支配点，并以该度量直接生成的近似前沿 `Approximation(θII, θII)` 为 benchmark 计算 HV gap；作者明确不保证该近似前沿是真实最优前沿。Table 7 后，作者选择 CV 用于 Part II。

#### 2.5 作者实际比较的状态或方案

`FACT`：正式版直接比较的对象包括：

- 五个度量：Range、MAD、SD、CV、GINI（p.3187；完整五度量运行时间比较见 Table 2，完整交叉映射见 Table 7，收敛示意见 Fig. 3）。Table 3 只比较 Range，Table 6 只比较 Range 与 MAD。
- 前沿两个端点：`pure cost-driven solution` 与 `pure equity-driven solution`（p.3192–3195；Tables 4–6）。
- `least-cost solution` 与 \(\gamma=2.5\%,5\%,7.5\%,10\%\) 四个公平预算（p.3196；Table 8 把 least-cost 单列为一组，再列四档改善；显式 \(\gamma=0.0\%\) 行见 Table 9）。这些是该文实验参数，不是本项目已批准参数。
- 配送员规模 \(M\)、\(1.5M\)、\(2M\)（p.3196–3198；Table 9）。
- 动态短缺方案：`No-Shortage`、`Postponement (PP) scenario`、`Additional Vehicles (AVs) scenario`（p.3198–3200）。
- PP 中的 \(\lambda=0,2,4,6,8,10\)（Table 10）；AV 中的 `+10% Bonus`、`+20% Bonus`、`+30% Bonus`（Table 12）。
- 算法验证：exact solver 与 HYBRIDNSGAII；HYBRIDNSGAII 与 Gurobi 的纯成本解；标准 HYBRIDNSGAII 与 Gurobi 解热启动版本；HYBRIDNSGAII 与 SCIP 的纯公平解（Tables 3–6）。

`FACT`：当前正式版和 2024 预印本均未检索到 `nucleolus`；正式版也未使用 Shapley value 或 cooperative game 分配器。

#### 2.6 图和结果表的真实结构

`FACT`：正文五幅图的原文标题或子图如下。

- **Figure 1，PDF 第 6 页/印刷 p.3185**：`An outline of the dispatch zone-wave problem (DZWP) optimization workflow.`
- **Figure 2，PDF 第 13 页/印刷 p.3192**：`Progression of HYBRIDNSGAII results until termination under GINI for two instances with N = 100.` 子图为 `(a) Hypervolume`、`(b) Cardinality`。
- **Figure 3，同页**：`Progression of HYBRIDNSGAII results under various equity measures for an instance with N = 100 and M = 10.` 子图为 `(a) Hypervolume`、`(b) Cardinality`。
- **Figure 4，PDF 第 18 页/印刷 p.3197**：`Approximate pareto-optimal frontier obtained for a specific zone-wave.`
- **Figure 5，PDF 第 20 页/印刷 p.3199**：`Average trends in equity, cost increase ratio, and adjusted profits when \(\gamma=2.5\%\).` 子图为 `(a) Zone 1` 至 `(e) Zone 5`。

`FACT`：Table 1（PDF 第 7 页/印刷 p.3186）只是模型符号表；结果表为 Tables 2–12：

- **Table 2，PDF 第 12 页/印刷 p.3191，`Average run time of HYBRIDNSGAII across different equity measures.`** 行为 \((N,M)\) 规模组合，末行 Average；列为 Range、MAD、SD、CV、GINI 下的 Average CPU time (s)。
- **Table 3，PDF 第 14 页/印刷 p.3193，`Comparing HYBRIDNSGAII to an exact solver using range as the equity measure.`** 行为 \((N,M)\)；Exact solver 和 HYBRIDNSGAII 各含 Card.、HV、Time (s)，末列为 HV gap (%)。p.3193 明确说明：因 adjusted profit 非线性，该表为 exact comparison 临时改用车辆利用率 \(\sum_{i\in\mathcal N_m(x)}q_i/Q_m\) 的 Range；不是 Appendix A 式（4）的 adjusted-profit Range。
- **Table 4，同页，`Pure cost-driven performance comparison: HYBRIDNSGAII vs. Gurobi.`** 行为 \((N,M)\)；列含两法的 Average cost value、Gap (%)，Time (s) 只对应 Gurobi optimizer。
- **Table 5，PDF 第 15 页/印刷 p.3194，`Performance improvement by seeding HYBRIDNSGAII with the pure cost-driven solution reported by Gurobi.`** 原表行首写 \((N,D)\)；列组 Average HV 下为 HYBRIDNSGAII、HYBRIDNSGAII + Gurobi Solution，末列 Gap (%)。
- **Table 6，PDF 第 16 页/印刷 p.3195，`Pure equity-driven performance comparison: HYBRIDNSGAII vs. SCIP.`** 行为 \((N,M)\)；列分 Average range value 与 Average MAD value 两组，每组含两法数值、Gap (%)，Time (s) 只对应 SCIP。
- **Table 7，同页，`Mapping results: Hypervolume gaps.`** 四个 panel 为 (N=25,50,75,100)；每个 panel 行为 Map From：Range、MAD、SD、CV、GINI；列为 HV gap (%) using：Range、MAD、SD、CV、GINI、Average。
- **Table 8，PDF 第 17 页/印刷 p.3196，`Summary of results from simulating the entire decision horizon.`** 行为 Zone 1–5，末行 Average；列为 β、N、\(M_L\)、\(M_H\)、Card.；Least-cost solution 下的 Cost、\(\bar u\)、CV；以及四档 γ 下的 Improvement in CV (%)。
- **Table 9，PDF 第 19 页/印刷 p.3198，`Comparing the impacts of different numbers of crowdshippers.`** 行为 Zone 1–5 × Equity budget 0、2.5、5、7.5、10%；列分 (M\)、(1.5M\)、(2M\) 三组，每组含 Cost、CV、\(\bar u_L\)、\(\bar u_H\)。
- **Table 10，PDF 第 20 页/印刷 p.3199，`Least cost under the postponement (PP) scenario.`** 行为 Zone 1–5；列为 \(N_{defer}\) 及 \(\lambda=0,2,4,6,8,10\) 下的 Average cost。
- **Table 11，PDF 第 21 页/印刷 p.3200，`Summary of results under the PP scenario with \(\lambda=4\).`** 行为 Zone 1–5，末行 Average；列为 \(M_L\)、\(M_H\)、Card.；Least-cost solution 下的 Cost、\(\bar u\)、CV；以及四档 γ 下的 Improvement in CV (%)。
- **Table 12，同页，`Least-cost solutions under the AV scenario.`** 行为 Zone 1–5，末行 Average；列为 \(M_L\)、\(M_H\)、AV；再分 +10%、+20%、+30% Bonus 三组，每组含 Bonus、Total cost、\(\bar u\)、CV。

### 3. 表骨架所用目标期刊母版的定点复核

这一小节只核表形，不从该文引入新的公平概念。必读的 `journal_convention_contract_20260812.md` 指定陈雨蝶等（2025）《双碳背景下复杂冷链物流模型及求解算法》为总母版；本轮又直接复核了其本地 PDF。

`FACT`（陈雨蝶等，Table 9，PDF 物理第 17 页）：表题是“不同配送模式对比表”。三个绝对结果列依次为“独立配送、分区配送、联合配送”，随后是“联合配送 vs 独立配送、分区配送 vs 独立配送、联合配送 vs 分区配送”三列相对变化。行依次为：总成本、碳排放成本、固定成本、油耗成本、制冷成本、损坏成本、惩罚成本、总距离、总时间、车辆数、油耗、碳排放量、满足时间窗客户数、平均装载率；单位写在行名中。该表直接支持“指标作行、方案作列”和“总目标—成本分项—物理量—排放—服务”的展示次序。

`BOUNDARY`：后文只借这张表的展示工艺和行序；利润比率、ABOff、\(S^-\)、\(S^+\)、vehicle-limited 等科学含义仍只来自 Soriano。本文的燃油/电费/碳、多趟和服务量行只来自本文现行模型与项目规矩，不写成陈雨蝶或 Soriano 已使用的指标。

## 二、本文差异点

下面只是逐项事实对照，不是新的领域分类。

| 对照项 | Soriano et al. (2023) | Sobhanan et al.（2026 正式版） | 本文现行设定 |
|---|---|---|---|
| 经营主体 | 多个车场由不同伙伴经营（p.4） | 单个平台、单一车场，服务区域再划为多个 zone；公平对象是临时配送员（p.3184–3187） | 两个车场；利润账按车场输出 |
| 车辆 | 每车场、每日是 homogeneous vehicles（p.4） | 车辆容量异质，但未区分燃油/电动推进（p.3185） | 有限油电混合车队（正文第 45–49 行） |
| 趟次 | 每辆车每日最多形成一条本场闭合路线，式（5）（p.4） | 每个选中配送员在一个 zone-wave 内恰好执行一趟开放路线，不要求回场（p.3185） | 同一实体车日内可执行多趟，相邻趟必须满足时间与电量连续，正文式（10）（第 180–185 行） |
| 成本 | 弧行驶成本 \(c_{ij}\)，车场利润用收入减弧成本，式（9）（p.4） | 平台承担路由里程成本，配送报酬在 zone-wave 内固定（p.3186–3187） | 主目标是固定、里程、燃油、电费与碳价折算排放的一本钱账，正文式（2）、（4）（第 118–142 行） |
| 排放与充电 | 未建模燃油、电费、碳价、电网碳强度或充电 | 未建立推进能源、充电或排放模型 | 分列燃油车直接排放与电动车按时段充电的间接排放，正文式（1）（第 97–114 行） |
| 动态时间 | 多日规划期；比较 horizon fairness 与 daily fairness（p.9–10） | 多个 wave 动态到达；无短缺的 Table 9 实验中各 zone-wave 独立且不传递信息，PP 情景则把 at-risk orders 延至下一波（p.3196–3200） | 日内滚动重规划继承实体车位置、时刻、载重与电量，已执行前缀冻结（正文第 47、198–210 行） |
| 当前正式算例口径 | 人工生成的多类算例（p.7） | 随机实例与 Amazon-inspired 多 zone-wave 实验（p.3191、3196） | P53 已定主机制统一到京津冀单一算例；具体客户规模尚未由用户拍板（`pending_decisions.md` 第 265–284 行） |

`INFERENCE`：Soriano 的模型事实是没有车型选择、油电成本、时变充电排放和实体车多趟。因此，“公平要求如何通过车型、充电时刻和多趟衔接改变利润与总账”这一联动结果不能由其设定产生。

`INFERENCE`：Sobhanan 的 adjusted profit 式（1）依赖单车容量、单个 zone-wave、单趟开放路线和平台全额补偿里程；本文的公平对象是两个车场，实体车可以多趟。因而车场投入不能直接用原式的 \(Q_m\) 表示；把该式直接改名成“车场调整后利润”必须另造一个聚合定义，本报告不这样做。

`FACT`：P28 已定，独立经营利润基准必须由每个车场只服务自己的责任客户、使用自己的车辆与设施，最终 Duty-HGS 跑 10 个种子并取最好利润冻结（`pending_decisions.md` 第 42 行）。P44 已定主目标为运营成本加碳价折算排放的一本钱账（第 207–217 行）。P52 已定每个机制对照臂各自从头重优化路线，再用同一完整评价器算分（第 303–313 行）。P53 已定机制实验统一到一个京津冀算例（第 265–284 行）。

## 三、三个候选定位及各自的数据可得性

以下三项均标为 `DECISION`，含义是代理提出的候选，不是用户决定；三者不是层级关系。

### 候选一：把 Soriano 的利润公平前沿原样扩展到混合车队、时变碳与实体车多趟

**借用什么。** 直接使用 Soriano p.4 式（2）的最差车场利润比率和式（11）的利润下界。Fig. 2（p.5）提供 \(S^-\)、\(S^+\) 与 `All partners better-off` 边界；Table 3（p.9）才提供 ABOff 简写及 \(S^-\)—ABOff—\(S^+\) 的比较次序。若 \(S^-\) 已满足全员不劣，ABOff 可以与 \(S^-\) 重合。

**本文新增什么。** 利润 \(P_d\) 不再只由服务收入减弧成本决定，而由两车场在混合车队、实体车多趟、实际充电时刻、时变电网碳强度及本文成本账下的重优化解决定。

**为什么 Soriano 的设定中不可能出现。** 其车辆同质、每车每日最多一条路线，成本只有弧成本；没有油电车型、充电、电网碳强度或实体车跨趟状态，因此同一公平水平下的车型—充电—多趟联动不存在。

**数据现在能否算。** 对一个已经给定的完整解，`DepotProfitBreakdown` 可直接给每车场收入、八项代码成本、总成本、利润、服务客户与需求、总排放、燃油车直接排放、电动车间接排放和两类充电量（`profit.py:29–50`）；总里程、实体车数和趟数还要从 `Solution`/排班证书聚合。当前不能正式回填，原因有三项：① P28 的正式 \(P_d^0\) 尚未冻结；②正文五项成本与利润账八项成本尚未统一；③现行正式入口具备无公平约束与 \(\theta=1\) 两种运行口径，但未冻结求 \(S^+\) 和完整前沿的外层扫描协议。也就是说，代码能评价给定解，\(S^-\) 与 ABOff 在前两项解决后可分别重优化；\(S^+\) 和完整前沿还不能仅凭现有字段得到。

### 候选二：只把“全员不劣”作为参与保障，报告它相对成本最小解的代价

**借用什么。** 使用 Soriano p.5 的 \(\hat P\geq1\) 状态和 p.7 的 `All Better-Off Cost Difference`；比较 \(S^-\) 与前沿中首个满足 \(\hat P\geq1\) 的 ABOff。这里 ABOff 是原文的解状态，不把它改写成新的分配机制；若 \(S^-\) 已全员不劣，两者可以重合。

**本文新增什么。** 在本文完整的一本钱账和两车场利润账下，回答“让两个车场都不低于各自 P28 独立经营利润，最低要增加多少总账；成本变化由车型、充电与多趟怎样传导”。

**为什么 Soriano 的设定中不可能出现。** 其 ABOff 只在同质车、每辆车每日最多一条本场闭合路线和弧成本下形成；无法区分本文的固定成本、燃油、电费、碳成本、两类排放、实体车数与趟数变化。

**数据现在能否算。** 对给定解，ABOff 判定所需的 \(P_d\) 和成本、排放、服务分项已有接口；里程、实体车数和趟数需另从 `Solution`/排班证书聚合。当前仍缺 P28 正式 \(P_d^0\)、正文与利润账的统一成本口径，以及按 P52 分别重优化的 \(S^-\) 与 \(\theta=1\) 解。因此是“给定解可评价，正式比较数尚不可得”。

### 候选三：检验 Soriano 的“独立车数上限”能否替代直接利润约束

**借用什么。** 使用 Soriano §5.4、Table 4（p.9）的原始 MDVRP-PF 与 vehicle-limited MDVRP-PF 比较：每个伙伴的可用车辆数限制为独立经营解实际使用的车辆数，再和原始模型中同等公平率的解比较成本。

**本文新增什么。** 在混合车型和实体车多趟下检验：一个简单的实体车数量上限，能否达到与直接利润下界相近的参与结果，以及它对车型、趟数、充电与排放的影响。

**为什么 Soriano 的设定中不可能出现。** Soriano 的原文做法是用车数限制避免显著的工作量转移；其车辆同质且每车每日最多一条路线。本文一辆实体车可执行多趟，油车和电车的容量、成本、能耗与充电约束也不同，因此“限制多少辆车”在本文中多出总车数与分车型车数两种不同语义。

**数据现在能否算。** 对给定解，利润、成本、排放与服务量可由利润账取得；实体车数、配送趟次和里程需从完整 `Solution`/排班证书聚合。当前不能形成正式比较：P28 独立经营解实际启用的实体车数尚未冻结；正文与利润账的成本口径尚未统一；“按总实体车数限制”还是“按油/电车型分别限制”仍是 `UNKNOWN`；相应 vehicle-limited 对照臂也尚无获批的正式求解协议。

`BOUNDARY`：本报告不另列一个“把 Sobhanan adjusted profit 直接用于车场”的候选。那样必须为车场自造 \(Q_d\) 或其他投入归一化量，并决定多趟下如何计容量与时间，已超出文献原式和本轮授权。

## 四、每个候选一张表骨架

以下都是内容骨架。正式排版时表题置于表上，使用无竖线三线表；单位写在指标名中。所有数据格均为“待回填”，没有表注。

### 候选一表骨架

来源拆分如下，避免把适配后的整表冒充文献原表：三种对照臂及次序直接取自 Soriano Table 3（p.9）；最低利润比率取自 Soriano 式（2）及 Table B.1（p.12）；客户重分配指标取自 Soriano Table 3；“指标作行、方案作列”及行序模仿陈雨蝶等 Table 9（PDF 物理第 17 页）。本文五项成本、能源、排放与服务量行来自本文式（1）、（2）、（4）和项目强制报告项，不声称 Soriano 已报告这些分项。

**表 X　利润公平前沿三个关键解的成本、运营与服务结果**

| 指标（单位） | \(S^-\)：公平不受限的成本最小解 | ABOff：首个全员不劣解（可与 \(S^-\) 重合） | \(S^+\)：公平最大解 |
|---|---|---|---|
| 单目标总账 \(Z\)（元） | 待回填 | 待回填 | 待回填 |
| 最低利润比率 \(\min_d(P_d/P_d^0)\)（无量纲） | 待回填 | 待回填 | 待回填 |
| 车场 1 利润比率 \(P_1/P_1^0\)（无量纲） | 待回填 | 待回填 | 待回填 |
| 车场 2 利润比率 \(P_2/P_2^0\)（无量纲） | 待回填 | 待回填 | 待回填 |
| 车场 1 利润（元） | 待回填 | 待回填 | 待回填 |
| 车场 2 利润（元） | 待回填 | 待回填 | 待回填 |
| 联盟总收入（元） | 待回填 | 待回填 | 待回填 |
| 运营成本 \(C^{\mathrm{op}}\)（元） | 待回填 | 待回填 | 待回填 |
| 固定成本（元） | 待回填 | 待回填 | 待回填 |
| 里程成本（元） | 待回填 | 待回填 | 待回填 |
| 燃油成本（元） | 待回填 | 待回填 | 待回填 |
| 充电电费（元） | 待回填 | 待回填 | 待回填 |
| 碳价折算成本（元） | 待回填 | 待回填 | 待回填 |
| 总里程（km） | 待回填 | 待回填 | 待回填 |
| 启用实体车数（辆） | 待回填 | 待回填 | 待回填 |
| 配送趟次（趟） | 待回填 | 待回填 | 待回填 |
| 车场充电量（kWh） | 待回填 | 待回填 | 待回填 |
| 公共站充电量（kWh） | 待回填 | 待回填 | 待回填 |
| 配送作业总排放（kgCO₂e） | 待回填 | 待回填 | 待回填 |
| 燃油车直接排放（kgCO₂e） | 待回填 | 待回填 | 待回填 |
| 电动车充电间接排放（kgCO₂e） | 待回填 | 待回填 | 待回填 |
| 完成客户数（个） | 待回填 | 待回填 | 待回填 |
| 完成需求量（kg） | 待回填 | 待回填 | 待回填 |
| 各车场服务客户数相对独立经营比例—平均（%） | 待回填 | 待回填 | 待回填 |
| 各车场服务客户数相对独立经营比例—最大（%） | 待回填 | 待回填 | 待回填 |
| 各车场服务客户数相对独立经营比例—最小（%） | 待回填 | 待回填 | 待回填 |
| 原属客户保留率—平均（%） | 待回填 | 待回填 | 待回填 |
| 原属客户保留率—最大（%） | 待回填 | 待回填 | 待回填 |
| 原属客户保留率—最小（%） | 待回填 | 待回填 | 待回填 |

### 候选二表骨架

来源拆分如下：\(S^-\) 与 ABOff 的臂名取自 Soriano Table 3（p.9）；`All Better-Off Cost Difference` 的定义和 `B-Off cost` 列分别取自 p.7 与 Table B.1（p.12）；绝对结果臂并列和行序模仿陈雨蝶等 Table 9（PDF 物理第 17 页）。Soriano 的 `B-Off cost` 只定义总成本差，因此本骨架不再给每个成本、车辆和排放指标自造一整列“变化率”；该指标由前两列的单目标总账计算。

**表 X　全员不劣参与保障相对成本最小解的代价**

| 指标（单位） | \(S^-\)：公平不受限的成本最小解 | ABOff：首个全员不劣解（可与 \(S^-\) 重合） |
|---|---|---|
| 单目标总账 \(Z\)（元） | 待回填 | 待回填 |
| All Better-Off Cost Difference（%，仅 ABOff 列回填两臂配对值） | 待回填 | 待回填 |
| 最低利润比率 \(\min_d(P_d/P_d^0)\)（无量纲） | 待回填 | 待回填 |
| 车场 1 利润比率 \(P_1/P_1^0\)（无量纲） | 待回填 | 待回填 |
| 车场 2 利润比率 \(P_2/P_2^0\)（无量纲） | 待回填 | 待回填 |
| 车场 1 利润（元） | 待回填 | 待回填 |
| 车场 2 利润（元） | 待回填 | 待回填 |
| 联盟总收入（元） | 待回填 | 待回填 |
| 运营成本 \(C^{\mathrm{op}}\)（元） | 待回填 | 待回填 |
| 固定成本（元） | 待回填 | 待回填 |
| 里程成本（元） | 待回填 | 待回填 |
| 燃油成本（元） | 待回填 | 待回填 |
| 充电电费（元） | 待回填 | 待回填 |
| 碳价折算成本（元） | 待回填 | 待回填 |
| 总里程（km） | 待回填 | 待回填 |
| 启用实体车数（辆） | 待回填 | 待回填 |
| 配送趟次（趟） | 待回填 | 待回填 |
| 车场充电量（kWh） | 待回填 | 待回填 |
| 公共站充电量（kWh） | 待回填 | 待回填 |
| 配送作业总排放（kgCO₂e） | 待回填 | 待回填 |
| 燃油车直接排放（kgCO₂e） | 待回填 | 待回填 |
| 电动车充电间接排放（kgCO₂e） | 待回填 | 待回填 |
| 完成客户数（个） | 待回填 | 待回填 |
| 完成需求量（kg） | 待回填 | 待回填 |

### 候选三表骨架

来源拆分如下：两种方案的比较关系、`VL-\(\hat P\)` 和 \(\hat c\) 只取自 Soriano Table 4（p.9）；两绝对结果臂并列和行序模仿陈雨蝶等 Table 9（PDF 物理第 17 页）。Soriano 的 \(\hat c\) 只定义 VL 解相对原模型同等公平率解的总成本差，因此本骨架不把它扩成所有行的变化率。

**表 X　直接利润约束与独立车数上限的结果比较**

| 指标（单位） | 原始利润公平模型：与 VL 同等公平率的重优化解 | VL：成本最小解（总车数或分车型上限口径待用户决定） |
|---|---|---|
| 单目标总账 \(Z\)（元） | 待回填 | 待回填 |
| \(\hat c\)：VL 相对原始模型同等公平率解的成本差（百分点，仅 VL 列回填两臂配对值） | 待回填 | 待回填 |
| 最低利润比率 \(\min_d(P_d/P_d^0)\)（无量纲；VL 列即原文 `VL-\(\hat P\)`） | 待回填 | 待回填 |
| 车场 1 利润比率 \(P_1/P_1^0\)（无量纲） | 待回填 | 待回填 |
| 车场 2 利润比率 \(P_2/P_2^0\)（无量纲） | 待回填 | 待回填 |
| 车场 1 利润（元） | 待回填 | 待回填 |
| 车场 2 利润（元） | 待回填 | 待回填 |
| 联盟总收入（元） | 待回填 | 待回填 |
| 运营成本 \(C^{\mathrm{op}}\)（元） | 待回填 | 待回填 |
| 固定成本（元） | 待回填 | 待回填 |
| 里程成本（元） | 待回填 | 待回填 |
| 燃油成本（元） | 待回填 | 待回填 |
| 充电电费（元） | 待回填 | 待回填 |
| 碳价折算成本（元） | 待回填 | 待回填 |
| 总里程（km） | 待回填 | 待回填 |
| 启用实体车数（辆） | 待回填 | 待回填 |
| 配送趟次（趟） | 待回填 | 待回填 |
| 车场充电量（kWh） | 待回填 | 待回填 |
| 公共站充电量（kWh） | 待回填 | 待回填 |
| 配送作业总排放（kgCO₂e） | 待回填 | 待回填 |
| 燃油车直接排放（kgCO₂e） | 待回填 | 待回填 |
| 电动车充电间接排放（kgCO₂e） | 待回填 | 待回填 |
| 完成客户数（个） | 待回填 | 待回填 |
| 完成需求量（kg） | 待回填 | 待回填 |

## 五、本轮查不到或存疑的清单

1. `CORRECTION`：Zotero 主条目 `L7JVNX7E` 是 2024 SSRN 元数据，但实际本地附件是 2026 POM 正式版。引用时必须按所用内容分版本，不能把 2026 的表和结果标成 2024 预印本。
2. `UNKNOWN`：正式版在线补充 EC.2 未保存在本地 Zotero 附件中；本轮能核到的五个展开式来自同篇 2024 预印本 Appendix A。不能把预印本 PDF 第 30–31 页写成正式版 p.3187。
3. `UNKNOWN`：P28 正式独立经营利润 \(P_d^0\) 尚无冻结产物；因此任何利润变化率、ABOff、\(S^+\) 或 Fairness Cost 目前都不能正式回填。
4. `UNKNOWN`：候选三若进入设计，需要用户决定混合车队的 vehicle limit 是限制每场总实体车数，还是分别限制油车和电车数。Soriano 的同质车设定没有回答这个问题。
5. `FACT`：`DepotProfitBreakdown` 没有总里程、实体车数、趟数和 `Original customers kept` 字段。这些量可从完整 `Solution`、排班证书和客户原属场映射另行聚合，但不能说是利润账现成字段。
6. `CORRECTION`：现行正文式（2）、（4）把固定、里程、燃油、电费与碳价折算排放写入主账；当前 `profit.py` 的 `cost_total` 还含充电占用费、路线时间成本、跨场服务成本。正式回填前必须统一两者口径，否则分项和不会闭合到同一个“总成本”。本轮不改模型、不改代码，只保留这一差异。
7. `UNKNOWN`：P53 已定京津冀单一算例，但 50 客户只是代理建议，用户尚未拍板具体客户规模；表题不预填规模。
8. `FACT`：Soriano p.4 在解释 \(P_d^0\) 后括号误写成“\(P_d\) is calculated a priori”；按上下文应指 \(P_d^0\)。本报告保留为原文笔误，不静默把它当成新的定义。
9. `UNKNOWN`：Soriano p.7 的 Fairness Cost 存在三处未解释的不一致：文字以 \(S^-\) 为参照，展示式却以相邻解为分母；文字说每增加 0.01，展示式没有显式乘 0.01；求和末项会访问 \(i+1\)。本报告只照录原式，不替作者修式。
10. `UNKNOWN`：Soriano p.7 的 \(S^-\) Fairness Rate Difference 展示式是 \(\max_d\{\hat p_d\}/\min_d\{\hat p_d\}\)，理论上不小于 1；但 Table B.1 有多项 `FairDiff` 小于 1。原文未说明数表是否使用了另一口径。
11. `FACT`：Soriano 的 `ABOff` 只在 Table 3 中作简称；正文可把它对应到“首个 \(\hat P\geq1\) 的解”，但论文没有单独的 ABOff 定义式，也不保证它与 \(S^-\) 不同。
12. `UNKNOWN`：现行正式运行入口只核到无公平约束和 \(\theta=1\) 两种口径（`run_problem_hgs_private_technical.py:655–706`）；尚未冻结求 \(S^+\) 或扫描完整前沿的外层协议。
13. `FACT`：两篇指定论文都没有使用“排放偏斜比”“利润+碳双维公平”或“分配机制/公平判据/实现方式三层体系”；当前 PDF 也没有核仁。上述名词不进入候选和表骨架。
14. `FACT`：本轮没有运行求解器、没有修改代码或算例。唯一项目交付文件是本报告。
15. `FACT`：三个受保护文件任务开始与任务结束的 SHA-256 完全一致：`cost.py` 开始/结束均为 `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989`；`check.py` 开始/结束均为 `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`；`search/evaluation.py` 开始/结束均为 `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。
