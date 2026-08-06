# Y1 历史遗留彻查第二轮（穷尽版）

任务编号：`Y1`  
日期：2026-08-02  
状态：`Y1_SWEEP2_COMPLETE`  
边界：只读核查既有仓库；未修改、删除或移动既有文件，未启动求解器或实验。写入仅限本任务九项交付物。

## 结论

`FACT`。第一轮 32 项原样继承，本轮没有重复登记，新增 10 项，其中 8 项影响当前主线。五个未终态范围均已闭合：103/103 个 solver Python 文件完成逐行扫描与逐公开符号调用图；2,838/2,838 份 baselines metadata 完成三类哈希字段引用图；81 算例四条 authority 的 1,014 个登记文件全部重算并一致；当前论文图、表、数字与正式产物完成双向映射；689 份 handoff 范围文件完成逐字节/逐行覆盖关系扫描并形成无环图。

`FACT`。没有发现四条 authority 的文件哈希漂移：`1,014` 一致、`0` 不一致、`0` 未登记。真正的新缺口是运行包到输入的 provenance：当前 572 个唯一有效 authority 输入在 2,838 份正式/历史 metadata 的 `source_hashes`、`protected_hashes`、`expected_source_hashes` 中均没有直接声明；`orders.csv` 和车辆参数锁又位于用户指定四条 authority 之外，但同样被当前 loader 实际读取。

`FACT`。当前论文没有断开的 `\input`/`\includegraphics`/`\IfFileExists` 路径，也没有无法落到证据的实验数字。最初的 42 个精确字符串未命中项经人工核对后，39 个是正式高精度汇总的舍入/派生显示，3 个是参考文献文章号或页码。反向仍有 48 个孤儿或退役版本候选；另有 16 个虽未被 TeX 直接引用、却属于当前直接引用资产的支撑/溯源文件，不能当孤儿删除。

## 1. 103 个 Python 文件逐行与逐符号审计

### 1.1 完成证据

`FACT`。范围严格为 `solver/src/setp_solver/`，排除 `._*` 与 `__pycache__`。共 103 个 Python 文件、50,492 行；103/103 均成功解码、逐行枚举并通过 AST 解析。`symbol_call_graph.json` 对每个文件保存 SHA-256、行数、非空行数、用途一句话及用途证据。

共登记 1,833 个公开符号。每个符号都指向一个未截断的 `repository_caller_sets` 调用集合；集合按文件与调用机制分组，保留每处行号和上下文。扫描覆盖精确导入、普通调用/构造、属性访问、词法引用、`importlib`、模块 `__getattr__`、`getattr/setattr/hasattr`、`globals/locals`、字符串注册表、装饰器注册和环境变量分支。全局识别 118 处动态机制与 27 处环境变量分支。

`FACT`。初筛曾把 `reporting/runner.py` 的四个函数当作零调用；源码第 78、90、97、187 行的 `@register_runner(...)` 证明它们由字符串键进入 `RUNNERS`，再由第 228 行 `get_runner(args.runner)(args)` 调用。本轮已把这四项回填为精确动态调用者，不列死符号。

最终零仓库内调用者的公开符号候选为 24 个。其中 `multi_customer_removal` 与两份 `record_timing` 已由第一轮 `X2-DC-001`/`X2-RI-002` 覆盖，不重复登记；其余按性质进入 `X2-DC-005` 至 `X2-DC-007`。诊断 dataclass 字段和属性访问仍明确保留“可能由序列化、反射或仓库外 runner 使用”的边界，没有据零静态调用直接判可删。

### 1.2 与当前主线直接相关的符号事实

| 位置 | 符号 | 仓库内调用 | 判定 |
|---|---|---:|---|
| `search/dynamic.py:131-133` | `myopic_rolling_policy` | 0 | 动态主模块中的死入口候选 |
| `search/dynamic.py:897-898` | `dynamic_final_failure_payload_for_test` | 0 | 无测试调用的测试包装候选 |
| `prices.py:158-168` | 三个兼容属性 | 0 | 可能为仓库外兼容 API，不能直接删除 |
| `reporting/runner.py:78,90,97,187` | 四个 runner | 动态注册 4 | 活符号，不是死代码 |
| `search/instance_registry.py:24-42` | L-main/E2 反向别名与函数 | 0 | 退役兼容面候选 |
| `search/multitrip_schedule.py:37` | `LEGACY_CONTRACT_ID` | 0 | V1 历史名称候选；V2/V3 当前常量仍有调用 |

全量逐文件用途、符号、调用者和零调用边界见 `symbol_call_graph.json`。

## 2. `baselines/` 全量引用图

### 2.1 完成证据

`FACT`。遍历得到 2,838 份 `metadata.json`，解析失败 0。对每份文件递归读取 `source_hashes`、`protected_hashes`、`expected_source_hashes`，形成 34,092 条源码/产物哈希边和 680 条包到包边。正式状态识别中，metadata 明示 `NOT_FORMAL`/`NONFORMAL` 的否定优先于字符串 `FORMAL`，避免把 pilot 的否定标签当正式结果。

### 2.2 三类清单

`paper_main.tex` 字面直接引用两个 baselines 包：

| 包 | TeX 证据 |
|---|---|
| `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724/artifacts` | `paper_main.tex:1240` 输入机制表 |
| `baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_01_instance_details` | `paper_main.tex:964` 输入节点明细表 |

`FACT`。被其他正式包通过三类 hash 字段引用的目标包只有 1 个：`baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a`，共有 72 条入边，来自 E3 正式单题包与 E6 单元包。完整逐边来源在 `referenced_by_other_formal_packages`。

`FACT`。严格孤立定义为“入度 0、三类 hash 字段条目 0、TeX 直接引用 0”。共有 480 个；其中 21 个仍带正式状态标记，包括当前 E3 `panel_summary`、E4 三个正式单题包及旧 E3/E7 正式包。孤立只说明图上无边，不等于可以删除；这 21 项登记为 `X2-HR-005`。

另有 2,252 个包满足“入度 0 且没有外部包引用”，但其中部分仍有自己的 source hash，因此没有并入更严格的 480 项清单。两种口径均在 `baselines_reference_graph.json` 分开保存。

## 3. 81 算例逐文件 SHA-256 重算

### 3.1 当前四条 authority

`china81.py:37-55` 锁定：

| authority | 路径 | 文件数（不含自身 artifact manifest） | 重算结果 |
|---|---|---:|---:|
| static v3 | `china81_stage2_static_inputs_corrected_v3_20260723` | 见审计 JSON | 全部一致 |
| matrix v10 | `china81_local_directed_matrices_corrected_v10_20260723` | 见审计 JSON | 全部一致 |
| runtime v4 | `china81_runtime_parameter_authority_v4_20260723` | 见审计 JSON | 全部一致 |
| fleet v1 | `china81_finite_fleet_authority_v1_20260723` | 见审计 JSON | 全部一致 |

四目录共 1,018 个文件；排除四份 `artifact_hashes.json` 后 1,014 个登记对象。逐文件实算 SHA-256 与各 authority manifest 比对：一致 1,014，不一致 0，manifest 外未登记 0。不一致项清单为空。

### 3.2 有效输入与 metadata 差异

`FACT`。按 81 个实例的实际装载关系去重，四条 authority 贡献 572 个有效输入：各实例 nodes、CV/EV 的距离/时间/能耗矩阵，以及共享 catalog、node-city、facility、runtime calendar/register、fleet cap 等。正式包 metadata 对这 572 个路径的直接三字段声明为 0，见 `X2-HR-004`。

`FACT`。loader 还读取 `china81_order_attributes_gis_v2_20260723/orders.csv` 与 `china_parameter_lock_v2_20260718.json`；两者 SHA-256 分别为 `a36b833228f9313f02a5e7796156b1f1e0b1a39982e5427c017d25522349c982`、`05078ffd735fc0f17f22b47d0c4d709dab2ba6838c002ab7cd85436010e155a8`，也没有正式包三字段声明。

`FACT`。static v3 的内容哈希完整，但其 `metadata.json:5-7` 仍写 `draft_only=true`、`formal_search_allowed=false`，第 20-21 行仍绑定 runtime v3；当前 loader 默认用 static v3 加 runtime v4。这是状态/绑定字段漂移，不是文件内容哈希漂移，登记为 `X2-PD-009`。

## 4. `docs/paper_v2` 资产双向映射

### 4.1 论文到产物

`FACT`。当前稿识别出 5 张图、15 张表、2,034 个数字 token；其中 1,834 个属于正文、表格或参数，200 个属于公式编号/结构控制。所有显式依赖路径都存在，悬挂文件引用为 0。

五个直接引用的正式资产为：

| 论文位置 | 资产 |
|---|---|
| `paper_main.tex:693` | `generated_figures/algorithm_flow.tex` |
| `paper_main.tex:1051` | `generated_figures/figure3_carbon_profile_v14.pdf` |
| `paper_main.tex:1246` | `generated_figures/figure4_convergence_v14.pdf` |
| `paper_main.tex:1354-1355` | `figures_e2_v2_20260730/fig_e2_performance_profile.pdf` |
| `paper_main.tex:1462-1463` | `figures_e4_20260731/figure_e4_timing_migration.pdf` |

论文两张 `\input` 表分别映射到第 2 节列出的两个 E2 包。其余正文内联表与数字在 `paper_to_artifact.tables`、`paper_to_artifact.numbers` 中逐项给出产物路径或舍入来源。

### 4.2 产物到论文

`FACT`。反向范围内有 69 个正式图表资产：5 个直接引用，16 个是这 5 个直接资产对应的 CSV、PNG、TeX 源、validation、done 或哈希支撑，48 个为真正的孤儿/退役版本候选。`artifact_to_paper` 为每个文件给 SHA-256、TeX 引用边和三类角色；48 项完整路径另列 `orphan_artifacts`。

`FACT`。E3/E4/E6 的当前数字均能回到正式高精度汇总。E4 的机器来源缺边已由第一轮 `X2-HR-002` 登记；本轮只新增 E3/E6 的同类问题 `X2-HR-006`。

## 5. `docs/handoff` 覆盖关系 DAG

### 5.1 完成证据

`FACT`。范围为 `docs/handoff/` 加根目录 `HANDOFF.md`，排除本轮输出目录与 `._*`。共 689 个文件全部逐字节哈希；其中 676 个可解码文本逐行扫描，13 个二进制按字节纳入清单。扫描识别 2,053 处“当前/权威”措辞和 479 处“历史/覆盖/作废”措辞。

自动规则给出 24 条候选、21 条唯一候选；逐条回读证据后剔除 7 条把“引用/取证/扩展”误判为覆盖的边，保留 17 条带明确覆盖范围的 `superseded_by` 边。图无环，拒绝成环边 0。每条边都带 `coverage_scope`，所以不会把“当前状态被覆盖”误写成“整份历史证据可删”。

### 5.2 当前有效权威面

| 文档 | 当前有效范围 |
|---|---|
| `HANDOFF.md` | 当前决定与终态事实 |
| `READ_ME_FIRST_FOR_AGENTS.md` | 启动纪律与历史链定位；其旧“当前权威链”标签存在冲突 |
| `TODO_施工总清单_20260802.md` | 当前用户拍板、阻塞项与授权面 |
| `model_scope_reduction_review_20260802/report.md` | 当前模型组件必要性与保留多趟决定 |
| `e2_final_closeout_20260727.md` | E2 封存终局 |
| `memory/carbon_forecast_semantics_restore_20260801.md` | 预测/事后碳字段当前语义 |
| `paper_main.tex` | 当前稿件正文；不自动等于当前科学权威 |
| `model_change_approval_register_20260718.md` | 审批历史；M1/M2 未决状态已被覆盖 |

17 条被覆盖文档、覆盖者、范围和证据行全部列在 `docs_supersede_dag.json`。其中新确认的关键边是 `model_change_approval_register:2487-2493` 的 M1/M2 未决状态已由 `TODO:20-33` 的用户“打开多趟”决定覆盖。

### 5.3 无完整覆盖关系的冲突对

| 文档 A | 文档 B | 冲突 |
|---|---|---|
| `READ_ME_FIRST_FOR_AGENTS.md:45-50` | `HANDOFF.md:5141-5164,5411-5442` | 前者仍把旧 E3-E7/北极星链称当前权威，后者已改写主线与章节角色；READ_ME 的启动纪律仍有效，故不能画整篇覆盖边 |
| `experiment_contract_v2_journal_aligned_20260730.md:4,27-35` | `HANDOFF.md:5141-5164` | 前者无范围地标 ACTIVE，后者已把协同、分账、非线性充电降为组件；合同红线仍有效，故只能登记局部冲突 |

## 6. 新增台账汇总

| ID | 类别 | 影响主线 | 核心事实 |
|---|---|---|---|
| X2-DC-005 | 死代码 | 是 | 动态主模块两个公开入口零仓库调用 |
| X2-DC-006 | 死代码 | 否 | L-main/E2 与 V1 合同公开兼容符号零调用 |
| X2-DC-007 | 死代码 | 是 | 16 个公开属性/字段零静态调用，须区分序列化接口 |
| X2-RA-007 | 退役资产 | 否 | 48 个论文资产为孤儿/退役版本候选 |
| X2-PD-009 | 参数漂移 | 是 | static v3 metadata 的草稿/禁止正式搜索/runtime v3 字段与当前 loader 不同 |
| X2-HR-004 | 悬挂引用 | 是 | 572 个当前 authority 有效输入没有正式包直接哈希边 |
| X2-HR-005 | 悬挂引用 | 是 | 480 个严格孤立包中 21 个仍带正式状态 |
| X2-HR-006 | 悬挂引用 | 是 | E3/E6 论文数字可复核但缺机器来源边 |
| X2-DF-007 | 文档失效 | 是 | approval register 的 M1/M2 未决状态已被“打开多趟”覆盖 |
| X2-DF-008 | 文档失效 | 是 | ACTIVE 实验合同的机制实验角色与当前主线冲突，纪律部分仍有效 |

新增 10 项，影响当前主线 8 项。逐项完整字段、事实位置、建议处置和风险见 `legacy_ledger_round2.json`。

## 7. 五项终态

| 范围 | 完成度 | 终态证据 |
|---|---:|---|
| 103 Python 逐行、公开符号与调用者 | 100% | 103/103，50,492 行，1,833 符号，完整调用集合，24 死候选，118 动态机制，27 环境分支 |
| baselines 全量引用图 | 100% | 2,838/2,838 metadata，34,092 source edges，680 package edges，0 parse error |
| 81 算例逐文件哈希 | 100% | 1,014/1,014 匹配，0 不一致，0 未登记；572 个有效输入逐项列明 |
| paper_v2 双向资产图 | 100% | 5 图、15 表、2,034 数字；0 悬挂依赖、0 未映射实验数字；69 资产反向分类 |
| handoff 覆盖 DAG | 100% | 689 文件；676 文本逐行、13 二进制逐字节；17 边、0 环、8 权威面、2 无整篇覆盖冲突对 |

终态：`Y1_SWEEP2_COMPLETE`。
