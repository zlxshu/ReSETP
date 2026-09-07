# 4.4 节「时变电网碳强度为什么值得引入」的文献 / 数据 / 理论口子

**日期**：2026-09-05
**范围**：只读文献与数据；**未修改仓库任何文件，未跑求解器**。
**目标段落**：`docs/paper_v2/paper_main.tex` L1138–1200（4.4.1），现无引用的那句
「理论上，把充电时刻与路线、车型一并优化，应同时优于有可用时段即充电与只改充电时刻两种做法。」
**页码口径**：下文「PDF p.x」指所列本机 PDF 的物理页码；Miyabe 一文经核，PDF 页码与文内印刷页码相同。

---

## 零、先说三句最要紧的（含两处需要用户裁决的问题）

1. **口子不用新找，论文自己已经有了。** 引言 L120 已写「电网碳排放强度在一天中随发电结构变化而波动，
   Li 等\cite{ref:52} 的研究表明，合理安排充电时段可以降低电动车充电环节的碳排放」，
   参考文献 L1591 的 `ref:52` = Li Z, Chen Z, Li H, et al. *On the value of orderly electric vehicle charging
   in carbon emission reduction*, TR-D, 2024, 135: 104383（**作者顺序经 Crossref 核对无误**，见 §二表注）。
   4.4.1 的毛病是这条引用没有往下带，不是全篇缺出处。**最小改动＝把 `ref:52` 引到 4.4.1 开头并补一个数字。**
2. **「路线也跟着变」这一句有直接的一手证据，且是最贴的口子**：Miyabe 等（2025，*Journal of Energy Storage*）
   把逐时段电网碳强度写进联合「路线—充电」目标，56 个算例平均排放 25.7 kg-CO₂，
   比普通 VRP（30.8）低 16.6%、比普通 EVRP（32.7）低 21.4%；**普通 EVRP 反而比普通 VRP 高约 6.2%**，
   原因正是「只加了充电可行性、没把时变碳写进目标」。这一句比任何「理论上应当」都更能立住建模要素。
3. **两处需要用户裁决的写法问题（不是我能自己改的）**：
   - 4.4.1 写的是「**应同时优于**」，但可行域嵌套只能推出「**不劣于**」。写成「优于」，
     下文自己报的「理论上应当出现的『路线重优化优于路线不变』并未出现」就变成自打脸。
     改成「不劣于」，再把观察到的倒挂归给启发式抽样波动（极差 33.10 元 vs 择时收益 7.19 元，4.6 倍），
     矛盾就消失了。**这一句不需要引用**（详见 §三）。
   - 4.1 节 L841、L870 把碳强度数据说成「公开发布的中国分省电力碳排放因子数据集」「北京代表日逐时电网碳强度数据」，
     读起来像实测值。但仓库合同 `docs/handoff/china_policy_scenario_contract_20260717.md` §2 明文规定：
     该数据「只能称『省级逐时模拟/投影碳强度』，不得称『官方』『实测』『实时』或『逐时边际排放』」。
     现稿措辞与合同有距离，审稿人若查数据源会问。建议在 4.1 补一句性质说明。

---

## 一、数据事实：电网碳强度在一天内显著变化

| 条目 | 关键发现（带数字） | 出处（页/段/文件行） | 可用于哪一句 | 可信度 |
|---|---|---|---|---|
| **D1**　Li Y, Zhang S, Li W, Liu Y, Qin Y, Wei H, Kang C, Zhang N, Du E. *High temporal and spatial resolution projected electricity carbon emission factors of China from 2025–2060*. **Scientific Data, 2026, 13: 926**. DOI 10.1038/s41597-026-07272-6；数据集 figshare DOI 10.6084/m9.figshare.28953545（CC BY 4.0）**＝论文现有 `ref:82`** | 中国大陆 **31 个省级行政区**、2025–2060、**逐小时（每年 8760 点）**电力碳排放因子；五个电力系统发展情景；与官方数据比对的 MAPE **低于 2.525%**。摘要原文：“offering a temporal resolution of one hour and covering 31 provinces … yielding Mean Absolute Percentage Errors (MAPEs) below 2.525%.”；正文另称 “midday period exhibits the lowest emission factors due to peak photovoltaic output” | nature.com 文章页（本次 WebFetch 直接读取，2026-09-05）；本机快照 `data/Carbon/中国情景/cef_dataset_full_20260731/`（含 `Annotation_of_the_dataset.pdf`、S1–S5 xlsx、`figshare_article_28953545.json`，后者内 `citation` 字段给出完整作者名单） | 4.1 数据来源句；4.4.1 引入句的「数据支撑」半句 | **一手**（期刊页 + 本机数据集快照） |
| **D2**　本文算例日历实际取值（北京，2025-02-12，48 个半小时槽） | 逐时碳强度 **最低 0.1541、最高 0.6439 kgCO₂e/kWh**；**极差 0.4898**、**峰谷比 4.18 倍**。低谷落在 13:00–15:00（0.1541–0.1553），高峰落在 00:00–02:00（0.6433–0.6439）。同一天电价谷段 00:00–07:00 的碳强度 0.5849–0.6439，为全天最高——**电价谷段与碳强度谷段完全错开** | 本机 `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv`（本次直接读表统计；city=beijing, date=2025-02-12, 48 行） | 4.1 图注旁的「峰谷差接近 0.5」（现稿 L873 已写，数字对）；4.4.1 可直接说「4.18 倍」以给出量级 | **一手**（仓库冻结数据） |
| **D3**　数据性质的强制口径 | 「TVCI 数据是 2025 年省级逐小时**情景投影**，经相邻复制扩展为 48 个半小时槽；**不得称实测、实时或边际排放因子**」；48 槽由小时值阶梯复制，须过日积分守恒检查 $0.5\sum_{q=1}^{48}\gamma_q=\sum_{h=1}^{24}\gamma_h$ | `docs/handoff/china_carbon_tariff_calendar_alignment_contract_v2_20260718.md` L44、L46；`docs/handoff/china_policy_scenario_contract_20260717.md` §2「CN-TVCI」 | 约束 4.1 和 4.4.1 的措辞，不是引用素材 | **一手**（仓库合同） |
| **D4**（备选，本次**未取到一手**）中国官方年度固定电力碳排放因子 | 上海 0.5737、华东 0.5500、全国 0.5306 kg CO₂/kWh（2023 年，生态环境部/国家统计局）；本机有 `MEE_2023_power_CO2_factors.pdf` | `docs/handoff/china_policy_scenario_contract_20260717.md` §2「CN-FIXED」；本机 PDF `data/Carbon/中国情景/raw_20260717/MEE_2023_power_CO2_factors.pdf`（本次**未逐页打开核对**） | 若要写「官方口径只给年度均值、无日内信息」，用它做对照 | **二手转述**（未核 PDF 原文页） |

> **可直接落笔的数据句（两种口径任选）**
> a）保守：「电网碳强度在一日内随发电结构变化而波动，北京代表日的逐时碳强度在 0.154 至 0.644 kgCO₂e/kWh 之间，峰谷差接近 0.5 kgCO₂e/kWh\cite{ref:82}。」（现稿 L873 已是这个意思）
> b）加量级：「……峰谷比达 4.18 倍，且碳强度低谷（13:00—15:00）与电价谷段（00:00—07:00）在时段上相互错开\cite{ref:82}。」

---

## 二、文献发现

### 2A 「按时变碳强度安排充电能减排」——有大量证据，且有中国算例

| 条目 | 关键发现（带数字） | 出处 | 可用于哪一句 | 可信度 |
|---|---|---|---|---|
| **L1**　Li Z, Chen Z, Li H, Guan C, Zhong M. *On the value of orderly electric vehicle charging in carbon emission reduction*[J]. TR-D, 2024, 135: 104383. DOI 10.1016/j.trd.2024.104383　**＝现有 `ref:52`** | 双层模型：上层在**不影响出行计划**的前提下重排每辆电动车的充电时刻以最小化碳排，下层以最小调度成本满足电力需求。用**上海 3777 辆纯电动车 11 个月真实运行数据**＋本地电厂数据，期间总碳排 1 176 637 吨；**对全部纯电动车实施充电控制可削减 39%** | Crossref 记录（作者顺序、卷期、文章号本次已核）；摘要文字与 39% 数字来自 ScienceDirect 摘要页的检索摘要 + TRID 条目 `https://trid.trb.org/View/2425680`，**两处独立二手互证** | 4.4.1 第一句的直接依据；且它已在引言用过，编号现成 | 书目**一手**（Crossref）；**39% 这个数字是二手**，写进正文前应打开原文核一次 |
| **L2**　Du B, Jia H, Zhang B, Li Y, Wang H, Yan J, Du E, Zhang N. *Evaluating the carbon-emission reduction potential of employing low-carbon demand response to guide electric-vehicle charging: A Chinese case study*[J]. **Applied Energy, 2025, 397: 126196**. DOI 10.1016/j.apenergy.2025.126196 | 摘要原文：“The results indicate that EVs produce **73 %** less carbon emissions during driving than traditional gasoline vehicles. Using low-carbon demand response to guide EV charging could **reduce carbon emissions by up to 15 % by 2035**.” 常州＋全国真实数据；用**高时空分辨率的动态碳排放因子作为引导信号** | 本机全文 PDF p.1（Zotero item `CK4NG97T`，本次逐页读取，摘要与作者单位清晰无乱码） | 4.4.1「中国情景下已被验证」半句；**与 D1 是同一批清华作者（Li Yaowang、Du Ershun、Zhang Ning），数据源与引导方法自洽** | **一手**（本机 PDF 逐页） |
| **L3**　Cheng K-W, Bian Y, Shi Y, Chen Y. *Carbon-Aware EV Charging*. 2022 IEEE SmartGridComm, 186–192. DOI 10.1109/SmartGridComm52983.2022.9960988 | 目标式 (2a) $\min_u\sum_t\sum_i C(t)u_i(t)\Delta T+\lambda\sum_i|x_i(T)-x_{i,\text{depart}}|$，$C(t)$ 为时变电网碳强度，$\Delta T=5$ min 与 CAISO 碳强度测量对齐。**交付电量不变时平均减排 3.81%**；调整权衡后**可减排 26.00%，但总交付能量减少 12.61%** | `docs/handoff/charging_time_objective_modeling_survey_20260804/report.md` §3.2（PDF p.3–4 公式、pp.1–2 与 p.7 结果，已逐页取证）；本机 PDF `/Users/zhouleixishu/Zotero/storage/57ITRNUI/` | 用来说明「碳目标与服务完成度之间存在权衡」，或作为 4.4.1「收益有限」的前置铺垫 | **一手**（仓库已逐页取证；会议论文，非期刊） |
| **L4**（备选）Powell S, Martin S, Rajagopal R, Azevedo I M L, de Chalendar J. *Future-proof rates for controlled electric vehicle charging: Comparing multi-year impacts of different emission factor signals*[J]. Energy Policy, 2024, 190: 114131 | 主题＝**不同排放因子信号**（平均 vs 边际）多年期效果比较。本次只取到题录，**未取具体数字** | Zotero item `4KL9BJ6V`（题录一手；正文未读） | 若要交代「本文用平均碳强度而非边际碳强度」，用它做依据 | **一手题录 / 内容未核** |

### 2B 「时变碳排放因子进入车辆路径或车队调度模型，并改变路线或充电安排」——**只找到一篇正面例子**

| 条目 | 关键发现（带数字） | 出处 | 可用于哪一句 | 可信度 |
|---|---|---|---|---|
| **L5**　Miyabe R, Fujimoto Y, Hayashi Y. *Low-carbon routing and charging planning for electric freight trucks utilizing local surplus solar power*[J]. **Journal of Energy Storage, 2025, 132: 117626**. DOI 10.1016/j.est.2025.117626 | ① 目标式 (3) 把**逐时段电网碳强度 $e_{t_o}^{\mathrm{grid}}$ 直接乘该时段购电量**，与路线变量 $x^k_{i,j,t_o}$ 在同一 5 分钟时间扩展网络上联合优化（PDF p.8）。② **56 个算例平均排放 25.7 kg-CO₂/case，比普通 VRP（30.8）低 16.6%，比普通 EVRP（32.7）低 21.4%**；原文并注明差异经 Wilcoxon 符号秩检验稳健（PDF p.13）。③ **普通 EVRP 排放最高，因为绕行充电增加里程而目标里没有激励低碳时段充电**——原文：“The ordinary EVRP, lacking an objective function to incentivize this behavior, potentially underperformed the VRP in terms of emissions.”（PDF p.13）。④ 2023-05-17 上午算例：EVRP 相对 VRP **充电需求增加 10.0%，碳排放却减少 66.1%**，且路线图不同（PDF p.15） | 本机全文 PDF `/Users/zhouleixishu/Zotero/storage/MP2SVFTJ/Miyabe 等 _ 2025 …pdf`，**本次直接抽取 p.13–15 原文逐句核对**（PDF 页码＝文内印刷页码）；公式与建模细节另见 `docs/handoff/charging_time_objective_modeling_survey_20260804/report.md` §3.1、§七、§八 | **4.4.1 最核心的一句**：「已有研究把时变碳强度写入路线—充电联合目标，并观察到路线与排放随之改变」。第 ③ 点尤其有力：证明这一建模要素不是装饰 | **一手**（本机 PDF 逐页，两处独立取证一致） |
| **L6**（同类但信号是电价不是碳）Lin B, Ghaddar B, Nathwani J. *Electric vehicle routing with charging/discharging under time-variant electricity prices*[J]. TR-C, 2021, 130: 103285 | 提高峰时放电奖励后，车辆为择时充放电而**绕行**：Scheme A 夏/冬距离 154.89 / 143.42 km，Scheme B 为 187.29 / 180.75 km，平均多约 **32 km**（PDF pp.25–26, Table 7）。另：时段从 60 min 细到 30/15 min，冬季电费从 −29.74 改善到 −60.19/−65.83 美分，但**距离从 143.42 增至 148.67/149.14 km**（PDF pp.29–30, Table 10） | `docs/handoff/charging_time_objective_modeling_survey_20260804/report.md` §2.1、§七、§八（已逐页取证）；本机 PDF `/Users/zhouleixishu/Zotero/storage/LPDQN9V7/` | 「时段信号进入目标后路线会变」的**定量**旁证；也是「更细时间建模改善能源目标却可能拉长距离」的旁证 | **一手**（仓库已逐页取证） |
| **L7**（对照，非碳）Zhao J, Poon M, Tan V Y F, Zhang Z. *A hybrid genetic search and dynamic programming-based split algorithm for the multi-trip time-dependent vehicle routing problem*[J]. **European Journal of Operational Research, 2024, 317(3): 921–935**. DOI 10.1016/j.ejor.2024.04.011 | 与恒定行驶时间模型相比，**88 个实例中只有 2 个最佳路线相同**；79 个实例经重新选路改进，平均目标改善 **7.47%**（PDF p.11 / 出版 p.931, Table 5） | 同上 §5.2、§七 | 若要论证「时变量进入目标一般会改变路线」的普遍性，可作旁证（但它是时变行驶时间，不是碳） | **一手**（仓库已逐页取证） |

---

## 三、理论：「联合优化不劣于固定路线」这一句要不要引用

**结论：不需要引用。**

- 这是**同一个模型内部的限制（restriction）论证**：「有可用时段即充电」与「只重排充电时刻」都是把
  路线、车型变量固定在某个取值上求解，其可行集是联合优化可行集的子集；同一目标函数在子集上的最小值
  不小于在全集上的最小值。这是最优化里的常识性事实，**目标期刊母版（陈婉茹等 2023, 43(11)）
  在同类地方也不给引用**——它写「理论上该值的变化不会改变最佳配送路径」时没有挂参考文献
  （`docs/paper_gci_dmm_vrp_20260804/journal_language_kit_20260904.md`，A-17 逐字段落）。
  为这句话去找一条参考文献是白花预算。

- **真正要改的是措辞的强度**：现稿写「**应同时优于**」＝严格优于。嵌套只支持「**不劣于**」。
  写「优于」，就与 4.4.1 结论段自己写的「理论上应当出现的『路线重优化优于路线不变』并未出现」
  直接冲突，等于给审稿人递刀。改成「不劣于」，再补一句「本文实验中该不等式未在数值上体现，
  原因是启发式搜索的抽样波动（10 次极差 33.10 元）已超过充电时刻本身的货币效应（7.19 元）」，
  这条冲突就从「理论失灵」降格为「方法学说明」。**这两个数字 4.4.1 结论段已经有了，不用新增。**

- **可选的「启发式可能违反该嵌套关系」的常规表述**：本次**未找到**一条专门讨论这一点、
  可直接引用的运筹学文献。最接近的替代是仓库已取证的两条**同类现象**：
  Keskin 和 Çatay（2016）「允许部分充电的 ALNS 在部分实例上仍比全充策略差；原文说明全充解对部分充电模型
  本来可行，因此这些变差是启发式搜索未找到更好解，而不是模型最优值更差」
  （`charging_time_objective_modeling_survey_20260804/report.md` §八第 5 条，PDF pp.14–15）——
  **这正是本文遇到的同一现象，且原文自己给出了「是搜索不是模型」的解释**，可以直接引用作类比。
  这是本次找到的最贴的一条，建议采用（`ref:45` 论文已引，编号现成）。

---

## 四、明确「未找到」的项

1. **中文期刊上「时变碳强度改变电动车充电或路线决策」且带可核实减排数字的文献**：未找到。
   - 一轮中文网络检索（含目标期刊方向）只命中电动车全生命周期碳排放核算类文章，
     没有把逐时碳排放因子写进调度或路径模型并报数字的中文期刊条目。
   - 另**逐条查了本文参考文献里最接近的中文候选**：`ref:95`＝巩亮, 郑世龙, 许得杰, 等.
     低碳视角下油电混合车队配送路径优化研究[J]. 控制与决策, 2026, 41(5): 1338–1347。
     其摘要为「针对道路行驶速度随时间变化……构建**时变交通**下油车-电车混合车队货物配送路径优化模型」，
     **时变的是行驶速度，不是碳排放因子**，标签也只有「时变交通」。**用不上。**
   - 替代方案：用 L1（上海 3777 辆车真实数据）和 L2（常州＋全国、清华团队）填补「中国情景」这一格，
     两篇都是中国作者、中国算例，只是发在英文刊。
2. **同时覆盖「多车场 ＋ 分时充电碳 ＋ 混合车队 ＋ 实体车多趟」的单篇文献**：未找到。
   这一条**已在仓库逐页取证过**（`charging_time_objective_modeling_survey_20260804/report.md` §十）：
   Miyabe（2025）最接近，但算例只有一个车场、无燃油车、无多趟；Shi 等（2025，`ref:93`）有混合车队与分时电价但无碳强度、无多趟；
   Zhen 等（2020，`ref:44`）有多车场多趟但无充电碳。**这就是本文第 2 条贡献的文献依据，可以正面写。**
3. **把「连续充电会话跨半小时边界、按真实分钟/电量分摊后再乘分时碳强度」写成完整 MILP 的文献**：未找到
   （同上 §十末段，11 篇逐页读全文均无）。**这是本文第 2 条贡献里「同一时段体系」那半句的直接支撑。**
4. **EVRP with time-dependent / marginal emission factors 的成规模文献群**：未找到。
   本次英文检索命中的基本都是**充电侧**（智能充电、碳感知充电、边际排放因子引导充电），
   不含路径决策。含路径的只有 L5 一篇。
5. **`ref:52`（Li 等 2024）「39%」这个数字的一手核对**：未完成。ScienceDirect 正文页 403，
   Semantic Scholar 无摘要字段；目前是两处二手互证。写进正文前需打开原文核一次。
6. **数据事实 D4（生态环境部 2023 年电力碳排放因子）的一手页码核对**：未完成（PDF 在本机但本次未打开）。

---

## 五、两个候选写法（4.4.1 引入段）

> 说明：两稿都照母版句式——先「谁做过什么、发现了什么（带数字）」，再「因此」，再「然而现有研究……」，
> 最后「本文……」。方括号里的编号为本文现有或需新增的参考文献标签。
> **两稿都把「应同时优于」改成了「不劣于」**，理由见 §三。
> **两稿都没有承诺大效应**，只承诺「检验它是否起作用」——因为 4.4.1 自己的结论是收益每日不足 10 元、占总成本 0.27%。

### 候选一：以「已有证据」为主线（最小改动，只新增 1 条参考文献）

> 电网碳强度采用图\ref{fig:experiment-carbon-intensity}所示的 TVGCI-CMDMF-DVRP 算例逐小时数据\cite{ref:82}，
> 其日内取值介于 0.154 至 0.644 kgCO₂e/kWh 之间，峰谷比达 4.18 倍。Li 等\cite{ref:52} 利用上海纯电动车的实际运行数据
> 建立双层模型，指出在不改变出行计划的前提下重排充电时刻可显著降低充电环节的碳排放。
> Miyabe 等\cite{ref:miyabe} 进一步将逐时段电网碳强度写入路线与充电的联合优化目标，发现只考虑充电可行性
> 而不将时变碳强度纳入目标时，电动车路径方案的排放反而高于常规车辆路径方案；将其纳入目标后，
> 路线与充电安排同时改变，平均排放较两类对照方案分别下降 16.6% 和 21.4%。
> 上述结果表明，充电时刻既直接改变充电成本与充电排放，也通过趟间补电时间改变可行的发车与回场时刻，
> 进而改变车型指派与配送路线；由于联合优化的可行域包含固定路线的可行域，其最优值不劣于后者。
> 然而已有研究或只调度充电而不涉及路径，或不含燃油车与实体车多趟，因此本文在北京现行分时电价与
> 单位碳价 0.20 元/kgCO₂e 的条件下设置三种充电安排，检验时变碳强度在混合车队多趟运营下的实际作用。

（5 句。若需再短，可删去「上述结果表明」一句中「充电时刻既直接改变……进而改变车型指派与配送路线」的前半，
只保留「由于联合优化的可行域包含固定路线的可行域，其最优值不劣于后者」。）

*新增参考文献 1 条*：`ref:miyabe` = Miyabe R, Fujimoto Y, Hayashi Y. Low-carbon routing and charging planning
for electric freight trucks utilizing local surplus solar power[J]. Journal of Energy Storage, 2025, 132: 117626.

### 候选二：以「中国情景」为主线（新增 2 条参考文献，中国味更足）

> 电网碳强度采用图\ref{fig:experiment-carbon-intensity}所示的分省逐时电力碳排放因子数据\cite{ref:82}，
> 碳强度在正午前后随清洁电源出力增加降至 0.154 kgCO₂e/kWh，而凌晨高达 0.644 kgCO₂e/kWh，峰谷比达 4.18 倍。
> Li 等\cite{ref:52} 基于上海纯电动车的实际运行数据指出，在不影响出行计划的前提下重排充电时刻
> 可显著降低充电环节的碳排放；Du 等\cite{ref:du} 以常州和全国算例进一步表明，
> 以高时空分辨率的动态碳排放因子作为引导信号安排充电，至 2035 年可使充电碳排放最多下降 15%。
> 在车辆路径层面，Miyabe 等\cite{ref:miyabe} 将逐时段电网碳强度写入路线与充电的联合优化目标，
> 观察到路线与充电安排随之改变，平均排放较不考虑碳强度的两类方案分别下降 16.6% 和 21.4%。
> 因此，把充电时刻与路线、车型一并优化，其可行域包含固定路线的可行域，最优值不劣于后者。
> 然而上述研究均未同时考虑燃油车与实体车多趟，本文在北京现行分时电价与单位碳价 0.20 元/kgCO₂e 的
> 条件下设置三种充电安排，检验时变碳强度在混合车队多趟运营的现实参数下是否仍具有可识别的作用。

*新增参考文献 2 条*：`ref:miyabe`（同上）；`ref:du` = Du B, Jia H, Zhang B, et al. Evaluating the carbon-emission
reduction potential of employing low-carbon demand response to guide electric-vehicle charging: A Chinese case
study[J]. Applied Energy, 2025, 397: 126196.

### 关于「碳谷与电价谷错开」这句要不要放进引入段——**建议不放**

初稿曾把「且碳强度低谷与电价谷段在时段上相互错开」写进候选二第一句，现已删掉。原因：
这句话正文里**已经出现两次**——L1072–1073（碳价机制那一节：「谷段电价的 00:00 至 07:00 时段，
碳强度介于 0.5849 和 0.6439 kgCO₂e/kWh 之间，为全天最高」）和 L1220–1221（充电时刻那一节的制约因素分析第 1 条，
把它作为**结论**给出）。放进引入段就是第三次，而且会把 4.4.2 的结论提前剧透。
**若用户仍想在引入段用它，条件是同时删掉 L1072–1073 那处**（那处是碳价分析里的旁白，最可删），
不能三处并存。

### 两稿取舍

| | 候选一 | 候选二 |
|---|---|---|
| 句数 | 5 | 5 |
| 新增参考文献 | 1 条（Miyabe） | 2 条（Miyabe、Du） |
| 中国证据密度 | 一条（上海） | 两条（上海＋常州/全国） |
| 最有力的一句 | 「不把时变碳写进目标，电动车路径方案排放反而更高」——直接回答「为什么这个建模要素不是装饰」 | 「以动态碳排放因子为引导信号，到 2035 年充电排放最多降 15%」——中国情景更足 |
| 数据句 | 只给区间与峰谷比 | 另点出「正午低谷源于清洁电源出力」，与图形态呼应 |

**倾向候选一**：句子更省，只新增一条参考文献，而且它的核心论据（不写进目标反而更差）
恰好正面回答审稿人会问的那句「为什么必须建这个模」。候选二适合用户想加重中国情景分量时使用。

---

## 六、写进正文前必须做掉的三件小事

1. 打开 `ref:52` 原文，核实「39%」及其口径（是全上海纯电动车、11 个月、相对无控充电）。目前是二手。
2. 4.1 节补一句数据性质说明，例如「该数据集为电力系统规划与运行模拟得到的省级逐时投影值，
   非实测或逐时边际排放因子」，以符合仓库合同 `china_policy_scenario_contract_20260717.md` §2 的口径要求。
3. 4.4.1 把「应同时优于」改为「不劣于」，并在结论第 2 条把倒挂归因于搜索抽样波动
   （可类比 `ref:45` 中「启发式未找到更好解、而非模型最优值更差」的表述）。

---

## 附：本次核对过的一手材料清单

| 材料 | 位置 | 本次动作 |
|---|---|---|
| 论文正文 | `docs/paper_v2/paper_main.tex` L99–165、L838–882、L1138–1230、L1578–1615 | 读 |
| 逐时日历 | `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv` | 读并统计北京 2025-02-12 全 48 槽 |
| 数据集元数据与说明 | `data/Carbon/中国情景/cef_dataset_full_20260731/{figshare_article_28953545.json, Annotation_of_the_dataset.pdf}` | 读 |
| 数据口径合同 | `docs/handoff/china_policy_scenario_contract_20260717.md` §2、`china_carbon_tariff_calendar_alignment_contract_v2_20260718.md` L44–46 | 读 |
| 建模取证报告（11 篇逐页） | `docs/handoff/charging_time_objective_modeling_survey_20260804/{report.md, papers.json}` | 读 §一、§三、§七、§八、§九、§十、§十一 |
| Miyabe 全文 | `/Users/zhouleixishu/Zotero/storage/MP2SVFTJ/…pdf` p.13–15 | 抽取原文逐句核对 |
| Du 等 2025 全文 | Zotero `CK4NG97T` p.1–2 | 逐页读取摘要与作者 |
| `ref:52` 书目 | Crossref `api.crossref.org/works/10.1016/j.trd.2024.104383` | 核对作者顺序（TRID 该条目首作者写成 Xu Zhengtian，与出版商存缴记录不符；以 Crossref 为准，**论文现有写法正确**） |
| Miyabe 书目 | Crossref `api.crossref.org/works/10.1016/j.est.2025.117626` | 核对卷号 132、文章号 117626、作者三人，与仓库取证报告一致 |
| `ref:95`（最近的中文候选） | Zotero `HADEF6XR` / `TYSLAQU8` 题录与摘要 | 核对是否含时变碳要素——结论：只有时变交通，无碳强度 |
| Scientific Data 文章页 | `nature.com/articles/s41597-026-07272-6` | WebFetch 取题录与摘要 |
| 效应上限台账 | `docs/handoff/carbon_relevance_ladder_20260905.md` | 读结论与口径节 |
| 母版句式 | `docs/paper_gci_dmm_vrp_20260804/journal_language_kit_20260904.md` | 读 §1.1–1.3 |
