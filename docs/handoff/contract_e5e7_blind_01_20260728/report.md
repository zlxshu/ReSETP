<ama-doc>

# CONTRACT-E5E7-BLIND-01：E5—E7 结果盲证据合同

**合同编号**：`CONTRACT-E5E7-BLIND-01`  
**冻结日期**：2026-07-28  
**状态**：`REPORTING_CONTRACT_FROZEN__EXECUTION_NOT_AUTHORIZED`  
**适用章节**：E5“非线性充电物理的内生决策”、E6“公平参与约束与协同溢价”、E7“动态需求下的协同—公平—时变碳交互”  
**性质**：结果盲的证据、统计单位、表图字段和文字结局合同；不是搜索、试跑或正式批授权。

## 0. 合同边界与三节共用冻结规则

### 0.1 证据状态

本合同只使用设计文件、现有论文设计文字和实验写作标杆报告，不读取、引用或预测 E5、E6、E7 的待产出结果。合同不推荐任何结果方向，也不预设效应大小。

当前基础合同仍标记 `formal_search_allowed=false`；E3/E6 的 D2、D3、D4、STAT 方案在当前批准台账中仍是 `DRAFT_METHOD_AWAITING_USER_APPROVAL`。因此，本合同不把其中任何草案数值升级为批准项。凡依赖尚未批准的输入、适配器、数值预算或统计层，执行状态均为 HALT。

本合同冻结后，只允许在**首个任务产生任何目标值、可行率或臂间差异之前**，由用户批准一份独立、带哈希的执行清单，填写本合同明确要求的预算数值和组件身份。首个结果产生后不得修改本合同，也不得用“勘误”改变终点、分母、统计单位、对照臂、精度、加粗规则或结局模板；若确需变更，必须废止原批次，另立合同编号，从零生成新批。

### 0.2 样本层级与结果盲种子规则

冻结母体为 3 个地区、9 个客户规模和每个“地区×规模”3 张互斥地图，共 81 个实例。客户规模固定为：

`{10, 15, 20, 25, 50, 75, 100, 150, 200}`。

初始共同种子固定为 `{1, 2, 3, 4, 5}`。现有文件虽预留种子 6、7，但没有批准的数值扩种阈值；因此本合同不授权扩种。若未来需要种子 6、7，必须在看到任何臂标签、效应符号或效应大小之前另行批准一个只依赖失败率、运行时和掩码残差离散度的机械阈值。不得因方向、显著性、图形不好看或某一小节接近零而追加种子。

原始配对行的身份是：

`region × customer_size × map_index × seed × arm`。

主要报告单元是 27 个“地区×客户规模”单元。每个单元先在同一地图内对共同有效种子等权聚合，再对 3 张地图等权聚合。任何缺失配对都会触发该单元 HALT，不用剩余种子或地图重加权补齐。

### 0.3 伪重复的统一处理

81 个实例不是 81 个独立自然实验：同一地区的不同规模会复用客户 OSM 身份池和区域基础设施；同一地图的共同种子共享输入、起点及外生情景；同一动态会话的阶段又共享历史状态。因此：

1. 地图、种子、候选解、事件和阶段均不得各自当作独立样本增加 `n`。
2. 27 个地区—规模单元用于分层、配对的描述性矩阵，不无条件解释为 IID 样本。
3. 三节主要结论不以 `p` 值作为成败判据。若未来增加推断层，必须先经独立批准，作为补充层单独标注，并且不得改变本合同的描述性主要结论或删除不利单元。
4. 不得把 27 个单元再粗化为仅 3 个地区均值后替代主表，因为这样会掩盖规模边界；地区汇总只能作为附加汇总。

### 0.4 共同配对口径

同一节同一配对单元必须共享：

- 完全相同的实例、订单、需求、时间窗、车场入口、车辆与充电设施参数、日历、价格、碳强度及外生事件流；
- 完全相同的初始方案或初始日状态哈希；
- 完全相同的基础种子；确定性臂即使不消费随机数，也必须记录同一个种子身份并标注 `seed_used=false`；
- 搜索型臂完全相同的预算单位和预算数值；
- 完全相同的最终完整模型评价器、最终物理检查器和独立复算证书口径。

预算单位固定为“实际送入完整模型评价器的完整候选数”，不使用迭代数、接受次数、路线池大小或墙钟秒数替代。墙钟只能是安全熔断，不能是正常停止条件；必须另存进程 CPU 秒和墙钟秒。正式执行前，执行清单必须冻结 `budget_id`、每臂或每阶段的整数 `complete_candidate_budget`、预算计数器版本及其哈希。当前没有用户批准的 E5—E7 数值预算，因此在该清单获批前统一判：

`HALT_BUDGET_VALUE_NOT_APPROVED`。

不得把这个 HALT 状态改写成待填结果、默认 0 或沿用其他实验的预算。

最终评价器和检查器不得只写“相同版本”。每行必须记录 `evaluator_id`、`evaluator_sha256`、`checker_id`、`checker_sha256`、`independent_certificate_id` 和证书哈希。任一身份不一致，整组配对无效。

### 0.5 缺失、精度与加粗的统一规则

所有缺失值必须使用下列显式代码之一，表格不得留空，不得用破折号代替，不得补零：

- `NA_INFEASIBLE`：该臂经最终检查不可行，指标在数学上无定义；
- `NA_NOT_APPLICABLE`：指标对该臂结构上不适用；
- `NA_SERVICE_MISMATCH`：服务集合不一致，不能计算配对效应；
- `NA_BASELINE_NONPOSITIVE`：E6 独立收益基准不为正；
- `NA_NOT_RECORDED`：本应记录但证据缺失；该代码同时触发 HALT；
- `HALT_PAIR_INCOMPLETE`：配对臂不完整；
- `HALT_CERTIFICATE_MISSING`：独立证书不完整；
- `HALT_E7_EVIDENCE_INCOMPLETE`：E7 五项证据门至少一项未通过。

只有数学上确为零且有证据闭合时才能填 `0`。例如，公平约束不激活且无约束方案与公平方案哈希一致时，公平溢价可以为 0；不可行、未运行、未记录或不适用均不能填 0。

统一显示精度为：

- 成本、收益和溢价：人民币元，2 位小数；
- 成本、收益和溢价相对变化：百分比，2 位小数；
- 可行率、激活率、服务率和份额：百分点或百分比，1 位小数；
- 排放：`kgCO2e`，3 位小数；
- 电量：`kWh`，2 位小数；
- 比率：无量纲，3 位小数；
- CPU 和墙钟时间：秒，1 位小数；
- 计数：整数。

计算和判决使用未四舍五入值；显示精度只用于排版和“接近零”文字分类。三节结果表中的**数值一律不加粗**，只允许加粗预注册的主要终点列名和表头。不得按最优值、显著性、期望方向或论文叙事临时加粗。

### 0.6 “正向、接近零、负向”与有效区间的统一判定

“正向”和“负向”只描述相对于本合同预先规定方向的观测差异，不等于统计显著，也不等于一般规律。若同一主要终点的多个组成量方向冲突，必须写“混合/权衡”，不得强塞入正向或负向。

“接近零”固定指：主要配对差异在上述显示精度下四舍五入为 0，并且没有守恒、可行性、服务或参与约束的反向变化。该定义只是报告分类，不是实际重要性阈值，也不是等效性检验。

有效区间只沿预注册的客户规模轴

`10 → 15 → 20 → 25 → 50 → 75 → 100 → 150 → 200`

划定。某一规模上的主要差异若按规定精度不再为 0，则该规模属于“观测作用档”；相邻作用档合并成闭区间 `[s_L, s_U]`。若有多个不相邻区间，必须全部报告；不得只挑最大或方向最好的一段。若没有作用档，固定写“在预注册的 10—200 客户规模轴上未识别到有效区间”。所有规模仍留在表图和分母中。

### 0.7 共同来源与优先级

本合同的设计依据依次为：

1. `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md` 及其强制读取清单；
2. `HANDOFF.md` 与 `docs/handoff/model_change_approval_register_20260718.md` 的当前批准状态；
3. `data/ChinaInstances/china_e3_e7_foundation_contract_v1_20260723.json`；
4. `docs/paper_v2/paper_main.tex` 中 E5、E6、E7 三小节的现有设计文字；
5. `docs/handoff/research_benchmark_expsection_01/report.md` 的标杆刊写作审计。

若旧文件与当前批准台账冲突，以当前批准台账为准。标杆报告只支持机制实验采用描述性效应和有效区间写法；其中的历史效应范围不作为本合同的预期、门槛或成功标准。

---

## 第一章 E5：非线性充电物理的内生决策

### 1.1 唯一主问题

**在完全相同的实例、起点、种子、搜索预算和最终非线性裁判下，把非线性补能物理从事后复算前移为搜索内生约束，是否改变全样本的非线性可行性—成本配对结果？**

该问题可被证伪：若两臂在全部预注册配对单元上的非线性可行性和全样本成本序位均相同，则本问题的观测机制效应为接近零；若内生臂更差，则记录负向结果。

### 1.2 主要终点与次要终点

#### 1.2.1 主要终点

主要终点是一个预先冻结的二分量向量，不压缩成一个可被任意权重操纵的综合分数。

**主要终点 A：非线性补能可行率**

`nonlinear_feasible_rate_pct = 100 × nonlinear_feasible_n / N_expected`

其中 `nonlinear_feasible=1` 仅当最终完整非线性评价器、物理检查器和独立复算证书均通过。单位为 `%`。分母 `N_expected` 是该汇总层所有预注册配对单元；不可行、超时、错误和缺证书单元均不得从分母剔除。缺证书会使该节 HALT，而不是减少分母。

主要配对差异为：

`nonlinear_feasible_rate_diff_pp = rate(integrated_nonlinear_search) - rate(linear_plan_replay_nonlinear)`，

单位为百分点。

**主要终点 B：全样本可行性优先的成本序位效应**

为避免给不可行方案虚构罚值，给每个方案定义扩展成本：最终非线性可行时为完整模型成本，不可行时为 `+∞`。每个配对单元按下列固定规则分类：

- `cost_win`：内生非线性臂可行而复算臂不可行，或两臂均可行且内生臂成本更低；
- `cost_loss`：复算臂可行而内生臂不可行，或两臂均可行且内生臂成本更高；
- `cost_tie`：两臂均可行且未四舍五入的完整模型成本完全相同；
- `both_infeasible`：两臂均不可行。

全样本必须同时报告四类计数和比例，并报告：

`full_sample_cost_net_win_pp = 100 × (cost_win_n - cost_loss_n) / N_expected`。

单位为百分点。`both_infeasible` 留在 `N_expected` 中，但不被伪装成成本为 0。这是本合同所称“全样本成本效应”；不得用只保留共同可行样本的均值替代。

#### 1.2.2 次要终点

1. **旧线性方案在非线性物理下的假可行数**：
   `false_feasible_n = Σ I(linear_checker_pass=1 and nonlinear_checker_pass=0)`，单位为个；同时报告 `false_feasible_rate_pct = 100 × false_feasible_n / N_expected`。必须给出按冻结违规代码分组的原因计数。
2. **共同可行样本成本效应**：
   对两臂均可行的配对单元计算
   `paired_cost_effect_pct = 100 × (C_replay - C_integrated) / C_replay`，
   报告均值、中位数、最小值、最大值以及 `both_feasible_n / N_expected`。该指标必须明确标注“共同可行条件性结果”，不得称全样本效应。
3. **完整模型成本**：`full_model_total_cost_cny`，单位为元，来源为最终非线性完整评价器的成本分解闭合值。
4. **充电排放**：`charging_emissions_kgco2e`，单位为 `kgCO2e`，来源为实际充电电量、时槽和冻结碳强度的完整复算。
5. **运行时间**：`runtime_cpu_s` 和 `runtime_wall_s`，单位为秒；CPU 为资源口径，墙钟只用于安全审计。
6. **不可行原因**：`infeasibility_reason_code` 及各代码整数计数；不得只给一个总数。

### 1.3 对照臂定义

**臂 E5-C：`linear_plan_replay_nonlinear`。** 搜索和候选可行性使用冻结的线性充电近似；产出的最终方案必须原样送入共同的非线性完整评价器和非线性物理检查器复算。禁止在复算失败后修补充电时刻、换车、改路线或二次搜索。

**臂 E5-T：`integrated_nonlinear_search`。** 搜索评分、候选守卫和最终检查均使用同一冻结的非线性充电曲线、充电功率、枪数、并发约束和公共可用性口径。

两臂共享实例、订单、时间窗、车场、车辆、充电设施、日历、价格、碳强度、初始方案哈希、种子、完整候选预算、最终非线性评价器、最终非线性检查器、独立证书及确定性平局规则。唯一设计差异是：搜索阶段使用线性近似，还是把非线性物理内生到搜索。控制臂额外记录线性评价器和线性检查器身份；最终科学裁判对两臂完全相同。

正式运行前必须冻结：

`start_solution_sha256`、`budget_id`、`complete_candidate_budget`、`linear_evaluator_sha256`、`linear_checker_sha256`、`nonlinear_evaluator_sha256`、`nonlinear_checker_sha256` 和独立复算器哈希。

任何一项缺失，判 `HALT_E5_ARM_IDENTITY_NOT_FROZEN`。

### 1.4 统计单位与伪重复处理

E5 原始配对单位是同一“地区×规模×地图×种子”下的两臂结果；主要报告单位是 27 个地区—规模单元。选择 27 单元是因为机制暴露随地区和规模变化，粗化为 3 个地区会吞掉规模边界；地图、种子和候选级记录又共享输入、起点和基础设施，细化后不能当作独立重复。

地图内先对共同种子的配对差异等权聚合，再对该地区—规模的 3 张地图等权聚合。候选评价、充电动作和单条路线仅用于诊断，绝不增加样本量。跨规模复用客户身份池和区域充电基础设施的风险必须在表注中明写，因此主报告只给 27 单元分层矩阵、地区汇总和全母体计数，不用 IID `p` 值决定 E5 成败。

### 1.5 表字段与图字段

#### 1.5.1 原始证据表 `e5_unit_evidence`

固定列顺序如下：

| 列名 | 单位/格式 | 定义 |
|---|---:|---|
| `contract_id` | 文本 | 固定为 `CONTRACT-E5E7-BLIND-01` |
| `region` | 类别 | `jjj/prd/cy` |
| `customer_size` | 客户数，整数 | 预注册九档之一 |
| `instance_id`、`map_index`、`seed`、`pair_id` | 文本/整数 | 配对身份 |
| `arm` | 类别 | E5-C 或 E5-T |
| `input_manifest_sha256`、`start_solution_sha256` | 哈希 | 输入与共同起点 |
| `budget_id`、`complete_candidate_budget`、`complete_candidate_count` | 文本/整数 | 批准预算、目标数与实际数 |
| `linear_checker_pass` | 0/1/`NA_NOT_APPLICABLE` | 线性检查；E5-T 不适用 |
| `nonlinear_feasible` | 0/1 | 最终非线性可行性 |
| `false_feasible` | 0/1/`NA_NOT_APPLICABLE` | 线性通过而非线性失败 |
| `infeasibility_reason_code` | 类别 | 冻结违规代码 |
| `full_model_total_cost_cny` | 元，2 位 | 不可行填 `NA_INFEASIBLE` |
| `charging_emissions_kgco2e` | kgCO2e，3 位 | 不可行填 `NA_INFEASIBLE` |
| `runtime_cpu_s`、`runtime_wall_s` | 秒，1 位 | 分别记录 |
| `evaluator_id`、`checker_id`、`independent_certificate_id` | 文本 | 身份 |
| `solution_sha256`、`certificate_sha256` | 哈希 | 方案和证书 |

#### 1.5.2 主汇总表 `e5_feasibility_cost_summary`

固定列为：

`region`、`customer_size`、`n_expected`、`n_observed`、`arm`、**`nonlinear_feasible_n`**、**`nonlinear_feasible_rate_pct`**、`nonlinear_feasible_rate_diff_pp`、`false_feasible_n`、`false_feasible_rate_pct`、**`cost_win_n`**、**`cost_loss_n`**、`cost_tie_n`、`both_infeasible_n`、**`full_sample_cost_net_win_pp`**、`both_feasible_n`、`both_feasible_coverage_pct`、`paired_cost_effect_pct_mean`、`paired_cost_effect_pct_median`、`charging_emissions_kgco2e_mean`、`runtime_cpu_s_mean`、`runtime_wall_s_mean`、`evidence_status`。

只加粗上述主要终点列名；任何数值不加粗。`n_observed` 必须等于 `n_expected` 才能发布主要汇总，否则整行填 `HALT_PAIR_INCOMPLETE`，不能缩小分母。

#### 1.5.3 图 `e5_feasibility_cost`

图固定为双面板：

- 面板 A：横轴 `customer_size`（客户数），纵轴 `nonlinear_feasible_rate_pct`（%），颜色为 `arm`，分面为 `region`；
- 面板 B：横轴 `customer_size`（客户数），纵轴 `full_sample_cost_net_win_pp`（百分点），分面为 `region`；同时在每个点旁标 `cost_win_n/cost_loss_n/cost_tie_n/both_infeasible_n`，不得只画共同可行样本。

轴范围不得按结果截断以放大差异；可行率轴固定为 0%—100%，净胜份额轴固定为 −100—100 个百分点。缺失点必须显示相应缺失代码，不得连线跨过。共同可行成本百分比只能作为附图，并必须同时画出覆盖率。

### 1.6 预注册结局写法

**正向模板**

> 在全部 `N_expected` 个预注册配对单元中，非线性内生臂相对线性方案复算臂的非线性可行率变化为 `[x]` 个百分点；全样本成本序位为 `[W]` 胜、`[L]` 负、`[T]` 平、`[B]` 个两臂均不可行，净胜份额为 `[z]` 个百分点。旧线性方案在非线性物理下有 `[k]` 个假可行单元。共同可行单元的条件性成本变化为 `[y]%`，覆盖 `[n_both]/[N_expected]`。这些结果支持的范围仅限本合同冻结的实例、物理和预算。

**接近零模板**

> 在全部 `N_expected` 个单元且不可行单元保留在分母的口径下，非线性可行率差和全样本成本净胜份额按预注册精度均接近零。沿预注册客户规模轴，观测有效区间为 `[s_L, s_U]`；区间外差异接近零。若不存在作用档，则写“在预注册的 10—200 客户规模轴上未识别到有效区间”。全部九个规模和三地区均保留，未删除单元或挑选子集。

若存在多个不相邻区间，模板中的区间改为完整列表；不得合并穿过零作用档。

**负向模板**

> 在完整分母下，非线性内生臂的可行率和/或全样本成本序位相对复算臂变差：可行率变化 `[x]` 个百分点，成本序位 `[W/L/T/B]`，净胜份额 `[z]` 个百分点。该负向结果原样保留，不通过删去不可行单元、改用共同可行子集或增加预算救援。

若可行率与成本方向冲突，固定写“可行性—成本权衡”，并分别报告，不得给单一胜负标签。

### 1.7 STOP / HALT 条件

满足任一条件即停止 E5 科学报告，不做救援调参、不补跑有利子集：

1. 数值预算、输入、起点、种子、评价器、检查器或独立复算器未在结果前批准并封存；
2. 两臂完整候选预算不一致，或墙钟实际充当正常停止预算；
3. 控制臂在非线性复算失败后被修补、二次搜索或更换路线；
4. 最终非线性评价器或检查器在两臂之间不一致；
5. 任一预注册单元缺臂、缺证书、缺违规原因或预算计数不闭合；
6. 把不可行单元从可行率、假可行率或全样本成本序位分母中删除；
7. 给不可行成本补 0、任意大罚值或只报共同可行成本而冒充全样本效应；
8. 候选、路线、充电动作或种子被当作独立样本；
9. 观察结果后改变客户规模区间、精度、终点、加粗或结局措辞。

对应机械裁决为：

`HALT_E5_CONTRACT_OR_EVIDENCE_FAILURE`。

---

## 第二章 E6：公平参与约束与协同溢价

### 2.1 唯一主问题

**在同一独立收益基准、同一起点、同一候选预算和同一完整裁判下，要求每个成员合作收益不低于其独立经营收益，是否实际激活参与约束，并以何种系统节省和公平溢价实现最低成员收益保障？**

该问题可被证伪：若无约束合作方案在所有预注册单元中天然满足参与条件，且公平选择与无约束选择一致，则参与约束在本区间内不激活，不能宣称公平机制改变了方案。

### 2.2 主要终点与次要终点

#### 2.2.1 主要终点

**主要终点 A：最低成员收益**

对成员车场 `d` 定义：

`member_benefit_d_cny = profit_d(fair_cooperation) - profit_d(independent_operation)`。

`member_min_benefit_cny = min_d member_benefit_d_cny`。

单位为元，来源为同一完整利润复算器；利润必须使用相同订单归属、收入、路线成本、跨场成本、碳成本和配额口径。主参与阈值固定为 `θ = 1.000`，即每个成员的公平合作利润不得低于独立经营利润。另报：

`member_min_ratio = min_d profit_d(fair_cooperation) / profit_d(independent_operation)`，

单位为无量纲。任一独立利润不大于 0 时不得计算比率，整配对判 `NA_BASELINE_NONPOSITIVE` 并 HALT。

**主要终点 B：参与激活率**

先对同一配对单元得到无参与约束的合作方案 `unconstrained_cooperation`。定义：

`participation_active = 1`

当且仅当该无约束方案至少一个成员的
`profit_d(unconstrained_cooperation) - profit_d(independent_operation) < 0`；
否则为 0。

`participation_activation_rate_pct = 100 × Σ participation_active / N_expected`。

单位为 `%`。该指标回答约束是否真正有机会改变选择，不能用公平臂最终满足约束这一必然结果代替。

#### 2.2.2 次要终点

1. **系统节省**：
   `system_savings_cny = C_independent - C_fair`；
   `system_savings_pct = 100 × (C_independent - C_fair) / C_independent`。
   单位分别为元和 `%`。
2. **公平溢价**：
   `fairness_premium_cny = C_fair - C_unconstrained`；
   `fairness_premium_pct = 100 × (C_fair - C_unconstrained) / C_unconstrained`。
   单位分别为元和 `%`。同时报告全样本值和 `participation_active=1` 单元的条件性值及覆盖数；条件性值不得替代全样本值。
3. **公平比率**：`member_min_ratio`，无量纲。
4. **成员级收益**：每个成员的独立利润、无约束合作利润、公平合作利润及两种合作相对独立的收益，单位为元。
5. **参与违规数**：`participation_violation_count`，单位为个；公平臂正式可行结果必须为 0。
6. **跨场协同范围**：`cross_site_service_count`（客户数，整数）和 `cross_site_demand_kg`（kg，2 位），用于解释系统节省与溢价，不作为新增样本。
7. **运行时间**：CPU 秒和墙钟秒，分别报告。

### 2.3 对照臂定义

E6 有两个正式运行臂和一个必要的嵌套比较状态：

**臂 E6-I：`independent_operation`。** 每个客户锁定原责任车场，禁止跨场服务；为每个成员产生独立利润基准 `profit_d^0`。同一配对单元的全部后续比较必须复用该方案、利润和哈希。

**状态 E6-U：`unconstrained_cooperation`。** 允许跨场服务，不施加成员收益下界。它是公平溢价和激活率的必要比较状态。

**臂 E6-F：`fair_cooperation`。** 允许跨场服务，并在候选评分、接受、最终选择和最终检查中同时施加
`profit_d ≥ 1.000 × profit_d^0`。只在报告末端筛选一个看似公平的结果不算 E6-F。

E6-U 与不同参与阈值下的可行候选集合是嵌套结构；候选解不是独立样本。正式搜索必须为每个候选保存其来源轨迹、共同父池身份和完整评价计数；候选级点只能解释边界，不能进入样本数、标准误或胜负计数。

三种状态共享实例、订单、时间窗、车场、车辆、充电设施、日历、价格、碳强度、基础种子、共同起点、最终评价器、最终物理/利润/公平检查器和独立证书。E6-U 与 E6-F 的搜索型预算必须相同；E6-I 的两个成员预算之和必须按同一“完整候选评价”单位冻结并与合作臂可比。区别仅为客户跨场权利及 E6-F 的参与下界。

确定性选择规则固定为：先排除物理或参与不可行候选，再按未四舍五入总成本升序；完全同成本时按总排放升序；仍相同时按规范化方案哈希字典序。不得见结果后更换平局规则。

若 `participation_active=0`，且 E6-U 与 E6-F 的最终规范化方案哈希一致，则公平溢价的 0 是有证据的真实零。若哈希不同，必须照实报告差异并标记 `SEARCH_PATH_DIFFERENCE_WHILE_CONSTRAINT_INACTIVE`，不得把差异自动解释为公平机制效应。

### 2.4 统计单位与伪重复处理

E6 原始配对单位仍是“地区×规模×地图×种子”，主要报告单位仍是 27 个地区—规模单元。该层级既保留公平约束随地区和规模激活的边界，又避免把共同起点、共同独立基准和共同候选池衍生出的多个方案当作重复实验。

同一单元内的成员、候选、阈值和候选池筛选结果均为嵌套观测，不是独立样本。尤其不得把一个候选池内的数十个候选或多个参与阈值当作数十个 `n`。地图内先聚合共同种子的配对差异，再对 3 张地图等权聚合；27 单元仅作分层描述性矩阵。地区内跨规模共享客户身份与基础设施的伪重复风险必须写进表注。

### 2.5 表字段与图字段

#### 2.5.1 原始证据表 `e6_unit_evidence`

固定列为：

`contract_id`、`region`、`customer_size`、`instance_id`、`map_index`、`seed`、`pair_id`、`arm_or_state`、`input_manifest_sha256`、`start_solution_sha256`、`independent_solution_sha256`、`independent_profit_baseline_sha256`、`theta`、`budget_id`、`complete_candidate_budget`、`complete_candidate_count`、`candidate_pool_id`、`parent_candidate_pool_id`、`candidate_pool_size_diagnostic_only`、`physical_feasible`、`profit_d0_cny_by_member`、`profit_unconstrained_cny_by_member`、`profit_fair_cny_by_member`、`member_benefit_cny_by_member`、`member_min_benefit_cny`、`member_min_ratio`、`participation_active`、`participation_violation_count`、`system_total_cost_cny`、`system_savings_cny`、`system_savings_pct`、`fairness_premium_cny`、`fairness_premium_pct`、`cross_site_service_count`、`cross_site_demand_kg`、`runtime_cpu_s`、`runtime_wall_s`、`evaluator_id`、`checker_id`、`independent_certificate_id`、`solution_sha256`、`certificate_sha256`、`evidence_status`。

成员收益和成本为元，2 位；比率 3 位；百分比 1 位或相对效应 2 位；计数为整数；时间为秒，1 位。成员向量必须以固定成员 ID 顺序展开或存为规范化 JSON，不得按结果重排。

#### 2.5.2 主汇总表 `e6_fairness_summary`

固定列为：

`region`、`customer_size`、`n_expected`、`n_observed`、**`participation_active_n`**、**`participation_activation_rate_pct`**、**`member_min_benefit_cny_mean`**、`member_min_benefit_cny_min`、`member_min_ratio_mean`、`system_cost_independent_cny_mean`、`system_cost_unconstrained_cny_mean`、`system_cost_fair_cny_mean`、**`system_savings_cny_mean`**、**`system_savings_pct_mean`**、**`fairness_premium_cny_mean`**、**`fairness_premium_pct_mean`**、`fairness_premium_active_only_pct_mean`、`active_only_n`、`cross_site_service_count_mean`、`participation_violation_count_sum`、`search_path_difference_inactive_n`、`evidence_status`。

只加粗预注册主要终点和四个必须披露的经济量列名；数值不加粗。全样本和激活子集必须并列，不能只展示激活子集。

#### 2.5.3 图 `e6_fairness_activation_premium`

固定为双面板：

- 面板 A：横轴 `customer_size`（客户数），纵轴 `participation_activation_rate_pct`（%），分面为 `region`；
- 面板 B：横轴 `fairness_premium_pct`（%），纵轴 `system_savings_pct`（%），点为 27 个地区—规模单元，颜色为 `region`，直接标注 `customer_size`。

候选级或阈值级点不得混入 27 个单元点；如另画候选前沿，图题必须写“同一嵌套候选池诊断，非独立样本”，且不能给独立误差条。激活率轴固定 0%—100%；其余轴必须包含 0 线并使用三地区共同范围，不能按分面裁剪放大。缺失点显示缺失代码。

### 2.6 预注册结局写法

**正向模板**

> 在完整的 `N_expected` 个配对单元中，参与约束在 `[a]%` 的单元激活；公平合作的最低成员收益为 `[b]` 元，最低观测值为 `[b_min]` 元，参与违规为 0。相对独立经营，系统节省为 `[s]%`；相对无约束合作，公平溢价为全样本 `[p]%`、激活单元 `[p_active]%`。该结果仅表明在冻结候选预算内观测到参与保障与系统代价/节省的配对关系，不宣称全局最优。

**接近零模板**

> 参与激活率和公平溢价按预注册精度接近零；无约束合作方案在当前冻结样本中已基本满足成员参与条件。沿预注册客户规模轴，参与约束的观测有效区间为 `[s_L, s_U]`；区间外约束不激活或没有改变最终方案。若无作用档，则写“在预注册的 10—200 客户规模轴上未识别到公平参与约束的有效区间”。所有未激活单元仍保留在全样本分母，不删除、不改阈值、不只报激活子集。

E6 的“作用档”固定指：该规模至少一个有效配对单元 `participation_active=1`，且公平方案通过参与检查；或该规模的公平溢价按 0.01% 精度不为 0。多个不相邻区间必须全部报告。

**负向模板**

> 公平合作虽满足预注册参与下界，但相对独立经营的系统节省为 `[s]%`，相对无约束合作的公平溢价为 `[p]%`，显示在本合同冻结样本和预算内存在系统代价或协同收缩。该结果原样报告，不通过降低独立收益基准、放松 `θ=1.000`、删除高溢价单元或扩充候选预算救援。

若公平臂未满足参与下界，这不是“负向科学结果”，而是实验合同失败，转入 HALT。

### 2.7 STOP / HALT 条件

满足任一条件即停止 E6 科学报告：

1. 任一成员独立利润不大于 0，或独立收益基准在 E6-U/E6-F 间不一致；
2. 参与约束只在最终报告中事后计算，没有进入候选评分、接受和最终检查；
3. E6-U 与 E6-F 起点、种子、完整候选预算、评价器或检查器不一致；
4. 跨场服务成本、成员利润和系统总成本不能在同一完整口径下闭合；
5. 公平臂存在任何参与违规或物理违规；
6. 嵌套候选、成员、阈值或阶段被当作独立样本；
7. 只报激活单元、可行阈值或有利成员，删除未激活、高溢价或不可行单元；
8. 为得到正向结果而降低独立基准、改变 `θ=1.000`、补阈值、换种子或增加预算；
9. 缺少独立方案、利润基准、候选池来源、最终方案或证书哈希；
10. 数值预算及依赖的 D2/D3/D4 方法尚未获用户批准。

对应机械裁决为：

`HALT_E6_CONTRACT_OR_PARTICIPATION_FAILURE`。

---

## 第三章 E7：动态需求下的协同—公平—时变碳交互

### 3.1 唯一主问题

**在同一冻结事件流和初始日状态下，完整动态重规划、参与公平约束与可见时变碳信号的预注册消融，是否在客户守恒和物理可执行性成立时改变全日服务、成本、排放与成员收益？**

该问题可被证伪：若五项证据门全部通过但预注册对比在全部规模上的主要差异接近零，则只能报告未识别到一般动态交互效应；若仅接口和状态接线通过，则不能回答该主问题。

### 3.2 主要终点与次要终点

#### 3.2.1 填数前的五项共同证据门

以下五项必须**全部**通过，才允许在 E7 结果表中填任何科学数值：

1. **事件流完整**：每个事件的 `event_id`、时间、类型、受影响客户、旧值、新值、顺序和事件流哈希闭合；五臂共享完全相同的外生事件流，不读取未来事件。
2. **状态继承完整**：每个阶段保存并验证上一阶段已执行前缀、车辆 ID、当前位置/车场、当前时间、SOC、载荷、车上订单、已启动充电动作和冻结动作哈希；不得重置到日初或另一臂状态。
3. **客户守恒完整**：每阶段对初始、到达、变更、取消、待服务、车上、已完成和合法拒绝客户集合做集合恒等式检查；客户不得丢失、重复、复活或被静默忽略。
4. **充电并发完整**：逐站点逐时槽验证充电占用不超过枪数，且充电窗口、功率、SOC 连续性和已开始动作均满足冻结非线性物理。
5. **独立证书完整**：由与运行器分离、带独立身份和哈希的复算器重新验证全日成本、排放、客户集合、车辆轨迹、充电并发、成员利润与所有违规计数。

任一项缺失时，E7 所有科学数值单元统一填 `HALT_E7_EVIDENCE_INCOMPLETE`。不得先填已完成的成本、运行时或部分阶段数字。

#### 3.2.2 主要终点

在五项门全部通过后，主要终点为：

**全日完整模型总成本**

`full_day_total_cost_cny`，单位为元，来源为独立复算后的全日完整成本分解。

主要对比固定为：

`dynamic_vs_static_cost_pct = 100 × (C_static_no_replan - C_full_dynamic) / C_static_no_replan`。

只有两臂的最终应服务客户集合、已完成客户集合和已完成需求量哈希完全一致时才计算该百分比。若服务集合不同，仍报告各臂服务结果，但成本对比填 `NA_SERVICE_MISMATCH`，不能用较少服务带来的低成本作为改善。

主要服务守卫为：

`dynamic_completed_customers`（客户数，整数）和
`completed_demand_kg`（kg，2 位）。

这两个字段不是可从分母中删掉的协变量，而是成本可比性的前置条件。

#### 3.2.3 次要终点

1. **动态相对顺序插入的成本效应**：
   `dynamic_vs_simple_insertion_cost_pct`，定义与主要成本效应相同，并要求服务集合一致。
2. **时变碳信号效应**：
   `carbon_signal_emissions_effect_pct = 100 × (E_carbon_blind - E_full_dynamic) / E_carbon_blind`，
   单位为 `%`；两臂均用真实实现碳强度做最终复算。
3. **总排放**：`full_day_total_emissions_kgco2e`，单位 `kgCO2e`。
4. **碳感知充电份额**：
   `carbon_aware_charging_share_pct`，分子和分母必须在执行清单中按充电电量口径冻结；无充电电量时填 `NA_NOT_APPLICABLE`，不得填 0。
5. **跨场吸收**：
   `cross_site_absorbed_customers`（整数）和
   `cross_site_absorption_rate_pct`（%）；分母固定为事件后需要分派且最终进入服务集合的客户数。
6. **公平交互**：
   `member_min_benefit_cny`、`member_min_ratio`、`participation_violation_count` 和
   `dynamic_fairness_premium_pct = 100 × (C_full_dynamic_fair - C_full_dynamic) / C_full_dynamic`。
7. **充电并发诊断**：
   `max_station_concurrency`、`charger_capacity`、`concurrency_violation_count`，单位为枪数/整数。
8. **运行时间**：全日及逐阶段的 CPU 秒和墙钟秒。阶段值只作诊断，不作为独立样本。

### 3.3 对照臂定义

五臂固定为：

1. **E7-S：`static_no_replan`**。按冻结日初计划执行，不在事件后做搜索重规划；事件仍须进入日志、守恒和服务结果，不能被静默忽略。
2. **E7-I：`simple_insertion`**。事件后只使用冻结的简单顺序插入规则，不调用完整动态搜索。
3. **E7-D：`full_dynamic`**。事件后继承本臂真实物理状态，使用完整动态重规划，允许冻结合同规定的协同权利，不施加成员参与下界。
4. **E7-F：`full_dynamic_fair`**。与 E7-D 相同，但在每阶段候选评分、接受和最终检查中施加 E6 冻结的 `θ=1.000` 参与下界。
5. **E7-B：`full_dynamic_carbon_blind`**。与 E7-D 相同，但搜索决策看不到预注册的未来/当前时变碳信号；最终评价仍使用真实已实现碳强度。除信息可见性外不得改变电价、路线权利、预算或物理。

五臂共享日初实例、订单、事件流、初始状态、基础种子、最终完整评价器、最终物理/守恒/利润检查器和独立证书。五臂在日初状态相同；事件发生后，每臂必须继承**本臂上一阶段实际执行后的状态**。不得为了制造“同起点”而把各臂每阶段重置到共同状态，因为这会删除政策路径效应。

E7-D、E7-F、E7-B 三个搜索型臂必须逐阶段共享相同的完整候选预算数值和计数规则。E7-S 不搜索，E7-I 只执行固定插入规则；其搜索预算字段填 `NA_NOT_APPLICABLE`，但必须记录实际完整检查次数。它们是政策基线，不得称为与三个搜索型臂“等算力算法对照”。五臂仍共享事件时刻、决策机会、最终评价器和检查器。

E7-B 的“碳盲”只能隐藏搜索信息，不能在最终裁判中使用平坦碳强度；否则它不再是信息消融。

### 3.4 统计单位与伪重复处理

E7 原始会话配对单位是同一“地区×规模×地图×种子×事件流身份”下的五臂全日结果。事件流与种子若由同一规则绑定，则它们构成一个嵌套会话身份，不能拆成两个独立重复。主要报告单位仍为 27 个地区—规模单元。

阶段、事件、客户和充电动作是同一会话的重复观测，共享状态历史，绝不是独立样本。逐阶段表只用于证明状态继承、守恒和并发门；主要效应先汇总成每个全日会话的一行，再按地图内共同种子、3 张地图的顺序聚合到 27 单元。

不采用更细单位，是为了避免把同一事件流的阶段复制成虚假样本量；不采用仅 3 个地区的更粗单位，是为了保留动态机制可能随客户规模出现或消失的边界。跨规模共享客户身份与基础设施的风险仍须明写，因此主要层为分层描述，不把 27 单元无条件视为 IID。

### 3.5 表字段与图字段

#### 3.5.1 五项门表 `e7_evidence_gate`

固定列为：

`contract_id`、`region`、`customer_size`、`instance_id`、`map_index`、`seed`、`event_stream_id`、`arm`、`event_stream_sha256`、`initial_state_sha256`、`executed_prefix_chain_sha256`、`state_inheritance_certificate_id`、`customer_conservation_certificate_id`、`charging_concurrency_certificate_id`、`independent_recalc_certificate_id`、`event_stream_complete`、`state_inheritance_complete`、`customer_conservation_complete`、`charging_concurrency_complete`、`independent_certificate_complete`、`all_five_gates_pass`、`evidence_status`。

五个门字段只能填 0/1；任一为 0 时，`all_five_gates_pass=0` 且科学结果表不得填数。

#### 3.5.2 全日结果表 `e7_full_day_summary`

只有 `all_five_gates_pass=1` 才允许填数。固定列为：

`region`、`customer_size`、`instance_id`、`map_index`、`seed`、`event_stream_id`、`arm`、`n_events`、`n_stages`、**`full_day_total_cost_cny`**、`full_day_total_emissions_kgco2e`、**`dynamic_completed_customers`**、**`completed_demand_kg`**、`required_service_set_sha256`、`completed_service_set_sha256`、`cross_site_absorbed_customers`、`cross_site_absorption_rate_pct`、`member_min_benefit_cny`、`member_min_ratio`、`participation_violation_count`、`charging_energy_kwh`、`carbon_aware_charging_share_pct`、`max_station_concurrency`、`charger_capacity`、`concurrency_violation_count`、`runtime_cpu_s`、`runtime_wall_s`、`budget_id`、`stage_complete_candidate_budget`、`complete_candidate_count_total`、`evaluator_id`、`checker_id`、`independent_certificate_id`、`solution_sha256`、`certificate_sha256`、`evidence_status`。

主对比汇总表另含：

**`dynamic_vs_static_cost_pct`**、`dynamic_vs_simple_insertion_cost_pct`、`carbon_signal_emissions_effect_pct`、`dynamic_fairness_premium_pct`、`service_set_match`、`n_expected`、`n_observed`。

只加粗主要成本和服务守卫列名；数值不加粗。服务集合不匹配时，配对成本效应必须填 `NA_SERVICE_MISMATCH`。

#### 3.5.3 阶段诊断表 `e7_stage_diagnostic`

固定列为：

`session_id`、`arm`、`stage_index`、`event_id`、`event_time`、`event_type`、`pre_state_sha256`、`inherited_state_sha256`、`post_state_sha256`、`executed_prefix_sha256`、`initial_customer_n`、`arrived_customer_n`、`changed_customer_n`、`cancelled_customer_n`、`onboard_customer_n`、`pending_customer_n`、`completed_customer_n`、`legally_rejected_customer_n`、`duplicate_customer_n`、`missing_customer_n`、`charging_action_n`、`max_station_concurrency`、`concurrency_violation_count`、`stage_complete_candidate_count`、`stage_cpu_s`、`stage_wall_s`、`stage_certificate_sha256`。

该表不得用作独立样本的统计表。

#### 3.5.4 图字段

主图 `e7_interaction_panel` 固定为三个并列面板，横轴均为 `customer_size`，颜色为 `region`，每个点是一个地区—规模单元：

- 面板 A 纵轴：`dynamic_vs_static_cost_pct`（%），服务集合不匹配时显示 `NA_SERVICE_MISMATCH`；
- 面板 B 纵轴：`dynamic_fairness_premium_pct`（%），并在点旁标 `member_min_benefit_cny`；
- 面板 C 纵轴：`carbon_signal_emissions_effect_pct`（%），并在点旁标 `carbon_aware_charging_share_pct`。

每个面板必须画 0 线，三地区使用同一纵轴范围；不得按结果裁剪分面。任何未通过五项门的点以 `HALT_E7_EVIDENCE_INCOMPLETE` 文本占位，不得连线。

诊断图 `e7_stage_diagnostics` 的横轴为 `stage_index`，纵轴只允许使用 `pending_customer_n`、`completed_customer_n`、`max_station_concurrency` 或 `stage_complete_candidate_count`，按 `session_id` 连线。图题必须注明“阶段为嵌套诊断，不是独立样本”。

### 3.6 预注册结局写法

E7 的三个机制对比必须分别写，不能用一个总方向掩盖成本、排放、公平或服务之间的冲突。

**正向模板**

> 五项证据门全部通过，且比较臂服务集合一致。完整动态相对静态不重规划的全日成本变化为 `[x]%`，相对顺序插入为 `[y]%`；加入参与公平后最低成员收益为 `[b]` 元、公平溢价为 `[p]%`；可见时变碳信号相对碳盲消融的全日排放变化为 `[e]%`。这些是冻结事件流、样本和预算内的分项观测结果，不外推为所有动态需求环境的一般规律。

只有某一分项方向为正时，才对该分项使用“正向”；不得要求三项都正，也不得把一项正向扩写成整个 E7 正向。

**接近零模板**

> 五项证据门全部通过，但 `[指定对比]` 的主要差异按预注册精度接近零。沿预注册客户规模轴，观测有效区间为 `[s_L, s_U]`；区间外差异接近零。若无作用档，则写“在预注册的 10—200 客户规模轴上未识别到 `[动态重规划/公平/时变碳信号]` 的有效区间”。全部地区、规模、事件流和无效应单元均保留，未删数据或挑子集。

三个对比分别按各自主要百分比是否在 0.01% 精度下为 0 划定作用档；服务集合不匹配或五项门失败的规模不属于“零效应”，而属于不可判定/HALT，不能拿来缩小有效区间。

如果仅机械接线和状态继承成立，固定使用下句：

> 本实验仅支持接口可行性和状态继承，不支持一般动态协同—公平—时变碳机制结论。

**负向模板**

> 五项证据门和服务可比性均通过，但 `[指定对比]` 在冻结样本中呈负向：全日成本变化 `[x]%`、排放变化 `[e]%`、最低成员收益 `[b]` 元、服务变化 `[q]`。该结果原样保留，不通过删除失败阶段、改事件流、重置状态、增预算、换种子或只报有利规模救援。

若成本、服务、排放和公平方向冲突，必须写“动态机制呈现权衡”，逐项给值，不给单一胜负结论。

### 3.7 STOP / HALT 条件

满足任一条件即停止 E7 科学结果报告：

1. 事件流、状态继承、客户守恒、充电并发、独立证书五项中任一不完整；
2. 五臂事件流、日初状态、外生输入、基础种子、最终评价器或检查器不一致；
3. 任一阶段把状态重置到日初、另一臂状态或未执行的计划状态；
4. 客户丢失、重复、静默忽略，或服务集合不一致却仍计算成本改善；
5. 已开始的路线或充电动作被无证据改写，或站点并发未逐时槽检查；
6. 碳盲臂在最终裁判中也使用平坦/错误碳强度；
7. 三个搜索型臂的逐阶段预算不同，或墙钟成为正常预算；
8. 把静态臂和顺序插入臂宣称为与搜索型臂等算力；
9. 把阶段、事件、客户或充电动作当作独立样本；
10. 只保存接口可行或少数阶段机械通过，却填写全日机制数字；
11. 任一预注册臂、地图、种子或事件流缺失后被静默删除；
12. 观察结果后修改事件流、有效区间轴、主要对比、服务守卫、精度或图轴；
13. E7 执行清单、完整适配器、预算数值或必要的用户批准尚未闭合。

对应机械裁决为：

`HALT_E7_CONTRACT_OR_FIVE_GATE_FAILURE`。

---

## 4. 发布前机械核对表

一节只有在以下答案全部为“是”时，才能从占位状态转为可报告状态：

1. 合同和执行清单是否都在首个结果产生前封存并记录哈希？
2. 是否完整保留所有预注册地区、规模、地图、种子和臂？
3. 是否没有把不可行、未激活、负向或近零单元从分母删除？
4. 是否按本合同的统计层级聚合，且没有把候选、成员、事件或阶段当作独立样本？
5. 是否使用共同的最终完整评价器、检查器和独立复算证书？
6. 是否使用显式缺失代码，且没有空白或补零？
7. 是否遵守固定精度、固定加粗规则和固定图轴？
8. 是否分别套用正向、接近零、负向或混合模板，而没有按结果改写问题？
9. 是否把有效区间沿完整预注册客户规模轴报告，并保留区间外数据？
10. E5 是否保留不可行单元、报告假可行数和全样本成本序位；E6 是否报告激活率、最低成员收益、系统节省、公平溢价并声明候选嵌套；E7 是否五项证据门全过后才填数？

任一答案为“否”，该节维持 HALT，不生成论文数字、图或一般机制结论。

</ama-doc>
