# C4：砍掉多视角、改用开源 HGS 直接开发的代价与影响面

编号：`MV-AUDIT-C4-20260806`
执行：Codex（只读取证；首轮 `019fd5a6-dc98-79a3-a893-488b8e9395c6` / `task-msh3ungq-kvju88`，
完整报告由 `task-msh4erm8-9j24lj` 重跑交回）
落盘：终端 Claude（codex 沙箱对本外置盘只读，`mkdir` 与 `apply_patch` 均被拒，故由 Claude 代写）
状态：`AUDIT_COMPLETE`（取代同名 `PARTIAL` 版本）

> 以下为 Codex 交回的报告全文，未经改写。
> 本报告只给代价、影响面和事实，不含路线建议——P19 的选择权在用户。

---

## 前提说明

[FACT] 本报告把“非必要情况下不保留自研算法、倾向基于 HGS 开发”视为用户当前倾向，不视为已拍板决定。

[FACT] 当前登记册将“自研多视角算法（MV-HGS-SP）是保留还是改为基于 HGS 开发”列为 P19，状态为“待决”；同一条明确写着该倾向“不是拍板”。`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:33`

[FACT] 本报告只盘点正文、实验臂、贡献主张、原则适用边界和文献证据缺口，不形成路线选择或采用结论。

## Q1：当前论文正文中依赖 MV-HGS-SP 自研算法贡献前提的部分

[FACT] 当前稿件作者说明将封面交付定义为“模型与算法”两项，且算法章被称为论文所要求的科学合同；算法能力在搜索侧和实体车队上限尚未闭合前不得写成已验证能力。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:5`

| 位置 | 当前正文证据 | 砍掉多视角后的影响 |
|---|---|---|
| 摘要、关键词 | [FACT] 中文摘要直接写“设计多视角混合遗传搜索—路线池集合划分算法”，关键词包含“混合遗传搜索”。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:9-11` | [INFERENCE] 摘要中的算法对象和算法关键词不再对应当前方法身份；模型、排放核算和三层机制部分不因多视角本身自动消失。 |
| English Abstract、Keywords | [FACT] 英文摘要明确写出 “A multi-view hybrid genetic search with route/schedule-pool set partitioning (MV-HGS-SP) is developed”，关键词包含 hybrid genetic search。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:15-17` | [INFERENCE] 英文摘要中关于 MV-HGS-SP 的方法贡献句失去当前对象；模型问题和排放叙述仍有独立内容。 |
| 引言中的方法定义 | [FACT] 引言末段把 GCI-DMM-VRP 与 MV-HGS-SP 绑定，称后者由互补代理视角扩展候选结构，再由完整模型和实体车排班约束统一评价与重组。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:33` | [INFERENCE] 该句的“求解方面”身份会从自研多视角算法改成其他搜索内核与问题特化评价/补全组件的组合，原句不能原样保留。 |
| 引言贡献清单第三项 | [FACT] 当前第三项贡献是“设计 MV-HGS-SP 算法”，并以公开算例、同协议算法比较和逐组件消融检验外部求解质量与内部组件贡献。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:35` | [INFERENCE] “MV-HGS-SP 作为算法贡献”以及“多视角内部组件贡献”属于直接丧失项；第一项模型贡献和第二项机制实验设计不以 MV 名称为逻辑对象。 |
| 第 3 章整章 | [FACT] 当前正文的 `## 3 算法设计` 从第 209 行开始，到第 248 行结束，标题、框架、图、步骤 1—8 均围绕 MV-HGS-SP 展开。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:209-248` | [FACT] 按当前章节编排，算法章整章就是为 MV-HGS-SP 设立的；当前稿没有另设一个独立的通用 HGS 主算法章。 |
| 第 3.1 节算法框架 | [FACT] 第 3.1 节将算法定义为“候选生成、完整补全和路线—排班重组”三阶段，并明确第一阶段由多个互补代理视角探索路线结构。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:211-215` | [INFERENCE] 多视角作为章节主线被移除后，三阶段中的完整补全和重组仍可作为技术组件存在，但“多个互补代理视角”不再承担算法身份。 |
| 图 1 | [FACT] 图 1 占位文字直接命名为“MV-HGS-SP 总体流程”，流程包括多视角 HGS 候选、实体车补全、模式池、集合划分和独立验解。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:217` | [INFERENCE] 图 1 的名称和“多视角 HGS 候选”节点失效；完整评价、实体车排班、充电核算和模式池节点属于可单独识别的技术内容。 |
| 第 3.2 节步骤 1—3 | [FACT] 步骤 1定义共同可行起点，步骤 2定义燃油、电动和机制三个代理视角，步骤 3定义各视角内的混合遗传搜索，并提到可使用 PyVRP 组件。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:219-225` | [INFERENCE] 步骤 2的多视角内容直接消失；共同起点和单一 HGS 搜索可作为其他算法实现的技术描述，但不再支持当前的多视角创新主张。 |
| 第 3.2 节步骤 4—8 | [FACT] 步骤 4—8分别规定实体车多趟补全、充电与碳核算、路线—日排班模式池、集合划分、独立验解和动态滚动调用。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:227-248` | [INFERENCE] 这些内容的算法依附性存在，但其问题特化功能不等同于多视角本身；它们可转写为 HGS 外围的完整评价、补全、重组和动态调用组件。 |
| 第 4.1 节及表 1、表 2、图 2、表 3 | [FACT] 代表实例、参数表、路线图和实体车排班表均写成从“完整算法正式运行”中提取；同时明确该展品只说明模型如何落到可执行方案，不承担算法优越性证明。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:250-268` | [INFERENCE] 这些展品不直接证明 MV-HGS-SP 的自研贡献；它们仍可承担模型可执行性展示，但其生成器和算法身份随搜索内核变化。 |
| 第 4.2 节及表 4 | [FACT] 第 4.2 节比较“本文算法退化版本”、公开最好值、文献算法和同机开源求解器，且明确该节只检验基础路径搜索能力。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:270-276` | [INFERENCE] 该节不是多视角消融的直接证据；其对象可转为 HGS 或基础路径搜索实现的验证，但“本文算法退化版本”的当前措辞会发生变化。 |
| 第 4.3 节及表 5、图 3 | [FACT] 第 4.3 节直接比较完整 MV-HGS-SP、删除多视角变体和删除集合划分重组变体；表 5报告三臂指标，图 3展示三臂收敛过程，正文结论句直接回填“删除多视角后目标值变化”。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:278-286` | [INFERENCE] 这是当前正文中受影响最大的实验小节；多视角删除臂作为消融对象的存在理由消失，表 5、图 3及对应结论句失去原有归因对象。 |
| 第 5 章及表 6—10、图 4—5 | [FACT] 第 5 章考察充电时刻、车型指派和动态发车，表 6—10及图 4—5均以完整方案、统一排放公式和动态状态继承为展示对象，没有在章节标题或问题定义中把 MV-HGS-SP写成机制贡献。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:288-330` | [INFERENCE] 第 5 章不因多视角被砍而逻辑上整章消失；但其数值结果仍依赖某个可运行且可复核的搜索器，当前“完整算法”来源、运行记录和结果解释会受到下游影响。 |
| 第 6 章算法结论句 | [FACT] 结论段同时写统一模型、MV-HGS-SP 算法、公开算例、完整模型比较和删除式消融，并预留“算法结论”回填位。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:332-334` | [INFERENCE] 当前算法结论句中关于 MV-HGS-SP 的部分直接失效；同一段中的统一模型和全口径排放部分不由多视角单独决定。 |
| 第 6 章机制结论句 | [FACT] 结论下一段分别回填充电时刻、车型指派和动态发车三个层级的结果。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:336` | [INFERENCE] 这些结论的科学对象是模型机制和决策层级，不是多视角组件本身；但数值结果仍须来自替代后的有效求解链。 |
| 框架中的算法有效性承接 | [FACT] 框架把 4.2定义为与开源求解器、文献算法的对照，把 4.3定义为算法组件消融；同时记载当前算法性能数据因搜索输出被丢弃而无效。`docs/handoff/paper_framework_20260803.md:217-248` | [INFERENCE] 框架中的“算法有效性”仍可作为一个章节功能，但“MV-HGS-SP 自研算法有效性”这一具体承载对象会被替换。 |

## Q2：实验设计包中以多视角消融或对照为存在理由的实验臂

### 当前实验设计包的 4.3 三臂

[FACT] 当前实验设计矩阵把 4.3 的唯一问题写成“多视角和集合划分重组各自是否形成可复现贡献”，实验臂为完整、删多视角、删重组。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:85-95`

| 实验臂 | 当前存在理由 | 砍掉多视角后的状态 |
|---|---|---|
| 完整 MV-HGS-SP | [FACT] 作为多视角与集合划分均开启的完整臂。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:137-143` | [INFERENCE] 作为“完整多视角算法”全废；其单一 HGS 搜索、完整评价和集合划分部分可作为另一个算法配置，但这已经不是当前臂的原存在理由。 |
| 删除多视角、保留单一视角 | [FACT] 当前定义是只保留经批准的单一视角，其余完整评价和重组保持不变。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:141-143` | [INFERENCE] 作为多视角消融臂全废；砍掉多视角后，它与新的单一视角完整配置发生身份重合，原本的“多视角相对单视角”对照不再存在。 |
| 删除集合划分重组、保留多视角 | [FACT] 当前定义是保留多视角和完整评价，但不执行路线—日排班模式池重组。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:141-145` | [INFERENCE] 可改造成“单一视角 + 无集合划分”与“单一视角 + 有集合划分”的对照，但这不再隔离集合划分在多视角背景下的作用；当前实验合同没有写入这种改造后的角色。 |
| 同时删除两个组件 | [FACT] 当前实验包明确不新增“同时删除两个组件”的第四臂。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:145` | [FACT] 当前设计没有一个现成的“双删”臂可以直接承接砍掉多视角后的联合对照。 |

[FACT] 当前实验包把三臂配对、完整模型评价、候选完成成功数、模式池增量和重组采纳记录作为 4.3 的解释条件。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:147-154`

[FACT] 历史正式包中出现过 `MV_HGS_NO_SP` 和 `HGS_M_SP_NO_MULTIVIEW` 两个名称，但同一取证记录说明两个正式包成功率为 0、搜索输出被整体丢弃，因此这些历史臂没有形成可用的多视角效果证据。`docs/handoff/session_handoff_20260803_solver_root_cause.md:149-152`

[INFERENCE] `HGS_M_SP_NO_MULTIVIEW`若仅按名称理解，是“无多视角但保留 SP”；`MV_HGS_NO_SP`若仅按名称理解，是“保留多视角但无 SP”；砍掉多视角后，前者可成为单一 HGS+SP 配置，后者会退化为单一 HGS+无 SP 配置，但二者都不再承担原来的多视角隔离含义。

### China81 的 O/F/E/M/MV 五臂

[FACT] China81 对照设计是独立成文、日期为 2026-07-27 的五臂设计，O/F/E/M/MV 分别代表原始距离、燃油代理、简化电动代理、完整机制代理和“三视角 + 集合划分”。`docs/handoff/china81_vs_opensource_design_20260727.md:1-5,20-28`

| 臂 | 当前存在理由 | 砍掉多视角后的状态 |
|---|---|---|
| O | [FACT] O 是“真正的开源 HGS 直接用”，搜索代理只看原始距离。`docs/handoff/china81_vs_opensource_design_20260727.md:22-33` | [FACT] O 不依赖多视角，作为纯距离开源 HGS 对照臂仍有原定义。 |
| F | [FACT] F 是 `cv_only` 燃油成本代理。`docs/handoff/china81_vs_opensource_design_20260727.md:22-27` | [INFERENCE] F 不依赖多视角，可继续作为燃油成本代理 HGS 臂；其“位于 O 与后续机制臂之间”的阶梯位置仍可存在。 |
| E | [FACT] E 是含电动但不含时变成本的 `naive_ev` 代理。`docs/handoff/china81_vs_opensource_design_20260727.md:22-27` | [INFERENCE] E 不依赖多视角，可继续作为简化电动代理臂。 |
| M | [FACT] M 是含电动、分时电价和碳强度的 `mechanism_ev` 代理。`docs/handoff/china81_vs_opensource_design_20260727.md:22-28` | [INFERENCE] M 不依赖多视角，可继续作为完整机制代理臂。 |
| MV | [FACT] MV 是三视角加集合划分的完整体，且原设计把 MV 对 O 的配对比较作为“干过开源”的直接证据，把 O→F→E→M→MV 作为机制阶梯。`docs/handoff/china81_vs_opensource_design_20260727.md:28,55-62` | [INFERENCE] MV 臂作为多视角终点和 MV 对 O 的多视角对照全废；O→F→E→M 的四级代理比较仍具有独立的原设计对象，但不再是当前五级阶梯。 |

[FACT] China81 五臂共用同一个完整完成器和精确评分器，差异位于搜索阶段的代理成本。`docs/handoff/china81_vs_opensource_design_20260727.md:35-37`

[INFERENCE] 因此，砍掉多视角不会使 O/F/E/M 的共同完成和精确评分基础设施全废；受影响的是 MV 臂、M→MV 比较、五级阶梯和围绕“多视角是否优于开源 HGS”的归因。

[FACT] China81 设计文档中的历史确认结果曾报告 MV 对 O 为 354 胜、46 平、5 负，但该结果是否能作为当前论文证据另受 C1 污染审计约束，见“顺带发现”。`docs/handoff/china81_vs_opensource_design_20260727.md:97-121`

## Q3：砍掉之后的贡献主张分类

[FACT] 当前 foundation 将贡献分为统一模型、三层配对实验和 MV-HGS-SP 算法三方面。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:33-35`

[FACT] 框架将时变碳强度、混合车队、动态需求、多车场、多趟和全口径排放列为模型内容，并将 4.2、4.3分别列为算法有效性和组件消融。`docs/handoff/paper_framework_20260803.md:181-207,217-248`

[FACT] “三机制交互 2×2×2”已被当前逻辑文件列为已废，不计入当前贡献清单。`docs/paper_gci_dmm_vrp_20260804/settled_logic_20260804.md:188-198`

| 类别 | 当前贡献或组件 | 证据 | 砍掉多视角后的状态 |
|---|---|---|---|
| [FACT] (a) 完全不依赖自研算法 | [FACT] GCI-DMM-VRP 统一模型同时包含时变电网碳强度、混合车队、多车场、实体车多趟和动态需求。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:35,39-45` | [INFERENCE] 该模型贡献对象仍在；数值展示仍有求解器运行依赖，但不依赖“多视角是自研算法贡献”这一主张。 |
| [FACT] (a) 完全不依赖自研算法 | [FACT] 电动车充电侧排放按实际充电时段碳强度核算，燃油车直接排放与电动车充电侧间接排放相加形成系统全口径排放。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:91-108` | [INFERENCE] 全口径排放核算属于模型与评价口径贡献，不因多视角删除而消失。 |
| [FACT] (a) 完全不依赖自研算法 | [FACT] 充电窗口由实体车辆排班、到场/离场时刻和多趟状态内生决定，动态重规划继承车辆位置、时间、电量和已发生成本排放。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:41-45,174-207` | [INFERENCE] 问题特化的状态继承和可充电窗口定义仍在；其执行结果改由替代后的求解链产生。 |
| [FACT] (a) 完全不依赖自研算法 | [FACT] 第 5 章保留充电时刻、车型指派和动态发车三个层级，并规定配对实验与统一排放口径。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:288-330`; `docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:85-97,155-220` | [INFERENCE] 三层机制问题和实验结构仍在；原有算法结果不能直接沿用，原因是求解器身份和搜索输出发生变化。 |
| [FACT] (a) 完全不依赖自研算法 | [FACT] 代表解展品只承担模型如何落到可执行方案，不承担算法优越性或机制效果证明。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:254-268` | [INFERENCE] 代表解、路线图和实体车排班表的模型展示功能可保留；它们不再自动证明 MV-HGS-SP。 |
| [FACT] (b) 依赖自研算法、砍掉即失去 | [FACT] 当前正文把 MV-HGS-SP 定义为针对 GCI-DMM-VRP 的算法贡献，并把互补多视角、完整评价、实体车补全和集合划分组合成统一算法。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:33,213-248` | [INFERENCE] “MV-HGS-SP 是自研主算法贡献”这一整体主张按当前措辞消失。 |
| [FACT] (b) 依赖自研算法、砍掉即失去 | [FACT] 第 4.3 节的直接问题是多视角和集合划分是否各自形成可复现贡献，且表 5、图 3和结论句都包含删除多视角后的结果位。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:87-91,137-154`; `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:278-286` | [INFERENCE] 多视角的内部组件贡献、删除多视角的消融归因和对应收敛图结论失去原有对象。 |
| [FACT] (b) 依赖自研算法、砍掉即失去 | [FACT] 结论段预留的是 MV-HGS-SP 的算法表现结论。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:332-334` | [INFERENCE] 当前“本文算法”的性能结论不能继续指向 MV-HGS-SP；可保留的只是某个替代求解器的运行结果，不是当前自研算法结论。 |
| [FACT] (c) 依赖算法但可改写为问题特化组件 | [FACT] 完整补全包括实体车分配、多趟衔接、电量、充电会话、时变电价和碳排放，并把失败原因写入评价链。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:227-229` | [INFERENCE] 这些内容可作为 HGS 搜索外部的问题特化完成器和统一评价器保留；其功能不等同于多视角创新。 |
| [FACT] (c) 依赖算法但可改写为问题特化组件 | [FACT] 集合划分重组在当前实验包中被作为与多视角可分离的独立删除项。`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:141-145` | [INFERENCE] SP 可作为单独组件继续出现，但它是否承担算法贡献仍受 P21约束，当前没有已定的贡献级别。`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:35` |
| [FACT] (c) 依赖算法但可改写为问题特化组件 | [FACT] 当前稿把碳感知充电时刻枚举、动态事件触发和状态继承写入算法调用流程。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:246-248`; `docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:200-220` | [INFERENCE] 这些内容可表述为问题特化的充电排程和滚动重规划过程，不必继续承担多视角的自研身份。 |
| [FACT] (c) 依赖算法但可改写为问题特化组件 | [FACT] 公开算例章节的目的被限定为检验退化问题上的基础路径搜索能力，比较对象包括公开最好值、文献算法和同机开源求解器。`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:270-276`; `docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md:121-135` | [INFERENCE] 公开算例对照可转为 HGS 或问题特化实现的基础搜索验证，但当前“本文算法”的身份表述会随 MV 删除而变化。 |

## Q4：§15 原则、历史出处与适用边界

### Q4-a：原文、完整小节与 rg 搜索位置

[FACT] 本轮执行了 `rg` 关键词搜索，关键词包括：`承担创新主张`、`主算法不得依赖`、`基线允许直接使用`、`血统必须干净`、`半独立`、`第三方开源实现`、`主算法`、`运行时依赖`、`runtime dependency`、`依赖占比`、`代码行数`、`接口耦合`、`可替换`、`可替代`、`判别标准`，以及 Q5 的 `PyVRP`、`OR-Tools`、`VRPSolver`、`HGS-CVRP`。

[FACT] `rg` 定位到 §15 的完整正文为 `docs/handoff/memory/user_operating_principles.md:113-121`。

[FACT] §15 原文逐字如下，引用块中的文字不含本报告的审计标记：

> **对比要制造张力。** 用户原话："必须有有解释力的对比，不能一门心优化单一目标；对比要制造张力。"每个实验必须写明比较对象、改变因素、保持不变的因素、配对单位和要回答的问题；不接受"完整模型对空白基线"这种没有信息量的对照。
>
> **开跑之前先写下什么结果能否定自己。** 研究卡强制包含"可能失效处"与"可反驳主张"，实验合同强制包含"可能否定主张的结果"；组件平均变差、非单调、失败臂、指标未移动等否定证据必须原样保留。这与§1"不设关卡"不冲突：前者是科学诚实，后者禁止的是行政性通过门。
>
> **每条线按自己的标准过门，不许互相救场。** 参数、算法、机制三条线各自独立验收；算法不给力不得靠模型创新遮掩，机制没效应不得靠算法表现补位。
>
> **承担创新主张的东西血统必须干净。** 主算法不得依赖第三方开源实现且禁止"半独立"，基线允许直接使用开源或复刻文献实现。用来当参照的东西怎么方便怎么来，用来主张贡献的东西必须可验证地独立。

[FACT] §15 的前一行标题是“实验设计”，而文件状态写为 `DECISION`、自 2026-08-01 起长期有效，并明确适用于 Claude、Codex、子代理、终端执行者和监控器。`docs/handoff/memory/user_operating_principles.md:11-15`

[FACT] §15 所在的第二部分说明，§14—§20的来源是 2026-06 至 2026-07 期间用户的纠正、拦下与拍板动作，以及项目自身的失败记录；两部分同等有效。`docs/handoff/memory/user_operating_principles.md:95-97`

[FACT] 与原则直接相关的其他有效或历史位置如下：

| 位置 | rg 命中内容及证据地位 |
|---|---|
| `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md:188-197` | [FACT] 记录 2026-07-09 正式算法包为 `setp_solver.algorithms.resetp_alns`，写明“完全独立，禁止半独立”。 |
| `docs/handoff/memory/project-prd-execution-v2.md:186` | [FACT] 记录 2026-07-09 ALNS 为“完全独立包（非半独立）”。 |
| `docs/handoff/memory/resetp-alns-independence.md:11-23` | [FACT] 记录一个更具体的历史包规则：无运行时依赖于旧 ALNS、第三方 `alns` 包和与基线共享的算法实现文件；允许共享的范围是问题裁判文件；同时记录运行时子集曾由 N-Wouda/alns 7.0.0 改编。 |
| `docs/handoff/model_change_approval_register_20260718.md:599-601` | [FACT] 记录官方 HGS 两次接入止损，HGS 从候选内部组件降为强制外部对照，不再以“HGS--ALNS 成功融合”申请论文身份。 |
| `docs/handoff/session_handoff_20260803_solver_root_cause.md:149-158` | [FACT] 记录 MV-HGS-SP 当前算法性能主张无依据，历史消融臂搜索输出被整体丢弃。 |
| `docs/handoff/bks_borrowing_and_hybrid_design_20260719.md:117` | [FACT] 记录一份历史设计文本曾把路由核心描述为借自 PyVRP/AILS-II、创新落在强化层；该文件不是 §15 原则正文。 |
| `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:225` | [FACT] 当前稿写有“实现可使用 PyVRP 提供的高性能车辆路径搜索组件”；该句是论文草稿中的实现表述，不是对 §15 的解释。 |
| `docs/handoff/mv_multiview_evidence_audit_20260806/C4_drop_multiview_impact.md:21-24` | [FACT] `rg` 还命中一份同编号部分稿中的原则复制文本；该文件第 6 行自标为 `PARTIAL`，因此它不是独立权威来源。 |

### Q4-b：这是通用硬性要求，还是某次历史事件的规则

[FACT] 从当前权威链看，这条规矩属于用户的长期通用硬性要求，而不是只对某一个实验包生效的临时合同：文件状态为 `DECISION`，长期有效，适用对象覆盖多个执行主体。`docs/handoff/memory/user_operating_principles.md:13-15`

[FACT] 2026-08-01 的提交 `665becdcdb37c7787e92915e7b0138e1c8bd29d4` 将 §14—§20追加到 `user_operating_principles.md`；提交日期为 2026-08-01，提交说明明确把 §15概括为“主算法血统必须独立”，并说明来源是 2026-06 至 2026-07 的用户纠正、拦下、拍板动作与项目失败记录。

[FACT] 2026-07-09 的提交 `fca004fadb5c1f8bceecf6f0c51d3a2cd4dc12d3` 建立了“fully independent ALNS”历史算法包；对应的具体规则和 provenance 记录在 `docs/handoff/memory/resetp-alns-independence.md:11-23`。

[FACT] 2026-07-18 的审批登记记录了 HGS 直接接入和 HGS 放入路线池重组的开发止损，并将 HGS 降为强制外部对照。`docs/handoff/model_change_approval_register_20260718.md:599`

[UNDETERMINED] §15 原句究竟由 2026-07-09 的独立 ALNS 事件、2026-07-18 的 HGS 外部基线裁决，还是多次事件共同促成，当前无法唯一定位到一个具体历史事件。

[UNDETERMINED] 针对该问题搜索过的关键词包括 `主算法不得依赖第三方开源实现`、`主算法血统必须独立`、`半独立`、`PyVRP`、`HGS`、`完全独立`、`运行时依赖`；精确原句的历史搜索只定位到 2026-08-01 的 `665becdc` 提交，未定位到更早的逐字原句或唯一用户裁决记录。

### Q4-c：开源 HGS 搜索内核加问题特化组件是否属于“依赖”

[FACT] §15明确禁止“主算法不得依赖第三方开源实现且禁止‘半独立’”，同时明确“基线允许直接使用开源或复刻文献实现”。`docs/handoff/memory/user_operating_principles.md:121`

[FACT] §15没有给出“主算法”“依赖”“半独立”三个词的操作性定义，也没有给出依赖占比、代码行数占比、接口耦合程度、可替换性、运行时调用层级或其他量化判据。`docs/handoff/memory/user_operating_principles.md:113-121`

[FACT] `rg` 对 `依赖占比`、`代码行数`、`行数占比`、`接口耦合`、`可替换`、`可替代`、`判别标准`等词的搜索没有在 §15中找到对应判别规则；搜索到的 `resetp-alns-independence.md:13-19` 是某一历史算法包的“无运行时依赖”和“只共享问题裁判”规则，不是 §15正文中声明的通用判别标准。

[UNDETERMINED] 仅依据 §15原文，无法确定“使用开源 HGS 作为搜索内核，再叠加自研问题特化组件”是否属于该条所称的第三方依赖或“半独立”。

[UNDETERMINED] 原文没有给出足以对该组合进行合规/不合规分类的量化标准或明确质化测试，因此本报告不替用户对该组合与 §15是否冲突下结论。

## Q5：目标期刊层级的开源求解器主算法先例

### Q5-a：仓库内已有来源与检索结果

[FACT] 当前框架把目标期刊写为《系统工程理论与实践》。`docs/handoff/paper_framework_20260803.md:10`

[FACT] 仓库内已有 `docs/handoff/journal_story_survey_20260803/`，调查范围是《系统工程理论与实践》2019—2025年车辆路径、低碳物流和协同配送方向；有效样本为 5 篇，五篇均取得全文，访问不到的论文为 0 篇。`docs/handoff/journal_story_survey_20260803/report.md:1-5,63-67`

[FACT] 现有综述表的字段是论文、机制、机制是否自创、贡献原句、归类和启示位置，没有“PyVRP、OR-Tools、VRPSolver、HGS-CVRP或其他开源实现关系”字段。`docs/handoff/journal_story_survey_20260803/report.md:7-15`

[FACT] `rg` 在 `docs/handoff/journal_story_survey_20260803/` 内搜索 `PyVRP|OR-Tools|OR Tools|VRPSolver|HGS-CVRP|HGS.?CVRP|开源求解器|开源算法|open source solver`，没有命中。

[FACT] `papers.json`记录了五篇样本的全文 PDF 路径、官方或首发页和贡献摘录，但没有记录上述开源求解器关系字段。`docs/handoff/journal_story_survey_20260803/papers.json:5-12,91-109,141-157,194-211,248-263`

[FACT] 仓库内当前稿的 `paper_main_foundation.md:225` 出现 PyVRP，`paper_main_foundation.md:272` 出现同机开源求解器，`paper_main_foundation.md:368` 出现 PyVRP 参考文献；这些是本项目稿件或参考文献位置，不是目标期刊样本论文的实现关系证据。

[FACT] 本轮还对目标期刊官网进行了 `PyVRP`、`OR-Tools`、`HGS-CVRP`、`VRPSolver`、`开源求解器`等定向搜索，并打开了若干官方文章页；定向搜索没有得到 3—5篇可核实的目标期刊“主算法直接基于这些开源求解器改造”的正例集合。

### Q5-b：数量、缺口与已核验样本

[UNDETERMINED] 《系统工程理论与实践》已发表论文中符合“主算法直接基于 PyVRP、OR-Tools、VRPSolver、HGS-CVRP 等开源求解器改造”这一条件的全体篇数，当前无法确定。

[FACT] 本轮检索得到的、能够同时核对作者、年份、期刊和开源实现关系原文位置的正例数量为 0；这不是对该期刊全体论文作“0篇”断言。

| 已核验样本 | 作者、年份、期刊 | 论文对自身算法/实现关系的描述 | 位置与结果 |
|---|---|---|---|
| 陈雨蝶、于宏程、程亮、温金鹏，2025 | [FACT] 《双碳背景下复杂冷链物流模型及求解算法》，《系统工程理论与实践》网络首发。`docs/handoff/journal_story_survey_20260803/papers.json:7-12` | [FACT] 论文把主算法写成具有变邻域搜索操作的 MPGA-VNS 混合遗传算法，未在仓库摘录中写成 PyVRP、OR-Tools、VRPSolver 或 HGS-CVRP 改造。 | [FACT] 贡献位置为引言末段第 3 页和结论首段第 21 页。`docs/handoff/journal_story_survey_20260803/papers.json:25-57` |
| 姜广田、纪皎月、董佳伟，2024 | [FACT] 《绿色物流配送下的多车型动态车辆路径优化》，《系统工程理论与实践》44(7):2362—2380；官方文章页列出作者、卷期和页码。[官方文章页](https://sysengi.cjoe.ac.cn/CN/10.12011/SETP2023-0524) | [FACT] 论文把主算法写成改进自适应遗传算法；本地全文的第 3 节标题为“算法设计及实现”，实验实现记录为 MATLAB R2022a，并与 PSO 和 Matlab 遗传算法工具箱比较，未出现目标开源求解器关系。 | [FACT] 仓库调查把本文新增内容记为集成建模与改进自适应遗传算法，位置为引言第 2363—2364 页及算法设计部分。`docs/handoff/journal_story_survey_20260803/report.md:12`; `docs/handoff/journal_story_survey_20260803/papers.json:91-109` |
| 陈婉茹、徐光明、张得志、曹健，2023 | [FACT] 《碳交易机制下多中心混合车队配送路径和速度优化研究》，《系统工程理论与实践》43(11):3320—3335；官方文章页列出作者、卷期和页码。[官方文章页](https://sysengi.cjoe.ac.cn/CN/10.12011/SETP2022-2971) | [FACT] 论文第 3 节把主算法写成考虑速度优化的并行改进变邻域算法，全文实验记录为 MATLAB R2016a，并列出 VNS、AVNS、VTNS 等算法比较，未出现目标开源求解器关系。 | [FACT] 仓库调查把新增内容记为联合模型和求解算法，位置为引言第 3321—3322 页及算法部分。`docs/handoff/journal_story_survey_20260803/report.md:13`; `docs/handoff/journal_story_survey_20260803/papers.json:141-157` |
| 李得成、陈彦如、张宗成，2021 | [FACT] 《基于分支定价算法的电动车与燃油车混合车辆路径问题研究》，《系统工程理论与实践》41(4):995—1009；官方文章页列出作者、卷期和页码。[官方文章页](https://sysengi.cjoe.ac.cn/CN/10.12011/SETP2019-1371) | [FACT] 论文标题、引言和结论把主算法描述为分支定价及配套初始解算法，而不是 PyVRP、OR-Tools、VRPSolver 或 HGS-CVRP 的改造。 | [FACT] 仓库调查定位为引言第 995—997 页及结论第 1008 页。`docs/handoff/journal_story_survey_20260803/report.md:14`; `docs/handoff/journal_story_survey_20260803/papers.json:194-211` |
| 饶卫振、张云东、刘从虎、于灏、侯艳辉，2019 | [FACT] 《一种求解协作配送成本分摊问题核仁解的近似迭代算法》，《系统工程理论与实践》39(6):1517—1534；官方文章页列出作者、卷期和页码。[官方文章页](https://sysengi.cjoe.ac.cn/CN/10.12011/1000-6788-2018-1668-18) | [FACT] 论文把主算法描述为 AIA 迭代逼近算法，未出现目标开源求解器关系。 | [FACT] 仓库调查定位为摘要与引言第 1517—1519 页。`docs/handoff/journal_story_survey_20260803/report.md:15`; `docs/handoff/journal_story_survey_20260803/papers.json:248-263` |

[UNDETERMINED] 上表是已审计样本中的非正例对照，不是用户要求的 3—5篇开源求解器主算法正例；它们只能说明当前仓库样本没有提供所需正例证据。

[UNDETERMINED] 仓库内数据缺口：已有五篇全文样本，但现有综述没有记录开源求解器实现关系，且目标关键词在综述目录内没有命中。`docs/handoff/journal_story_survey_20260803/report.md:3-15`

[UNDETERMINED] 外部检索缺口：本轮已执行目标期刊官网关键词检索和若干官方文章页核验，但没有完成覆盖该期刊全部已发表论文的逐篇、逐节实现来源普查，因此全体篇数和 3—5篇正例集合仍未闭合。

[UNDETERMINED] 文献真实性缺口：本报告没有把作者、年份、期刊或实现关系未能同时核实的候选文献列为正例；因此不存在可安全引用的 3—5篇开源求解器正例，而不是存在已发现但真实性不足的正例被隐去。

## 顺带发现

[FACT] P19仍为待决，且 P21“集合划分重组组件怎么处置”、P22“主线代表算例选哪个地区”、P23“是否先补回集合划分模型中的车队上限约束”也仍为待决。`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:33-37`

[FACT] C1审计把 2026-07-27 的 MV 对 O 结果标为受影响证据，并明确该结果不能证明多视角有用，也不能证明多视角是噱头。`docs/handoff/mv_multiview_evidence_audit_20260806/C1_0720_contamination.md:51-68`

[FACT] 当前根因记录明确写着算法性能主张无依据、两个正式包成功率为 0、搜索输出被整体丢弃，且历史消融因此必然无差异。`docs/handoff/session_handoff_20260803_solver_root_cause.md:149-158`
