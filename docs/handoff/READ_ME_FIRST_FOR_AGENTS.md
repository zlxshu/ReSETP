# READ ME FIRST — ReSETP Agent 强制入口

适用对象：Codex、Claude、Claude Code、任何接手 ReSETP 的代码/实验代理。

本文件是仓库级启动门。除非用户明确说“只回答一个简单问题，不读项目上下文”，否则任何非平凡任务都必须先读本文件列出的入口材料。读完之前不得改代码、不得跑实验、不得下论文结论。所有旧合同、提示词和计划还必须服从用户 2026-08-01 固化的[长期工作方法](memory/user_operating_principles.md)：不得用代理自建规则给科学实验设卡，不得把已经替用户选好的方案包装成“请拍板”。

## 1. 每轮强制读取清单

每次新对话、恢复上下文、切换机器、切换分支、执行实验、写报告、改代码、生成 Codex 提示词前，必须按顺序读取：

0-A. **`docs/handoff/memory/user_operating_principles.md`**（用户长期工作方法，必须先读；它管“怎样做事”，不是具体实验设计）。

0-A00. 🔴 **`docs/handoff/t0_delta_20260806_evening_before_codex_takeover.md`**
   （**2026-08-06 晚，移交 Codex 之前的最新状态差；本清单里最晚的一份，冲突时它优先**）。
   与 `docs/handoff/t0_current_state_freeze_and_upstream_decisions_20260806.md` 冲突时以它为准。
   内容：D3/P13（跨时段充电按分钟精确切分，用户先选起始档后被实测推翻）、
   P14（不补线性化辅助变量，正文写"含分段线性项的混合整数模型，由启发式直接求值"）、
   D2/P12（用户选"对齐"，但 Claude 自查发现所依据的问题描述是错的——
   碳其实已经在路线搜索代理里，`pyvrp_adapter.py:966-968` 与 `:980-995`；
   **不得照字面施工**）、C3b 集合划分取证（判定 C 两者兼有，
   **对用户原问题的答案是"实现与模型不匹配，不是正文建模缺陷"**）、
   以及一份"已经测过、不要重测"清单（预算饥饿曲线、SP 零贡献、MIP 撞满、
   三臂碳强度、充电会话时长分布、PyVRP 版本身份）。
   `HALT_NOT_A_DECISION`：**P21（SP 处置）是未决**，用户原话"先不考虑，把问题计入文档"，
   四个候选均未被选中；任何代理不得把"SP 不再作为默认主算法"写成已决。
   对照 P19（多视角不再作为贡献、搜索内核用成熟 HGS）**是**已决，
   可提技术担忧但不得当未决重开。
   **"已决 vs 未决"的唯一权威表是 `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`**，
   不是任何叙述性文档。

0-A0. ✍️ **`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md`** 与
   **`docs/paper_gci_dmm_vrp_20260804/experiment_design_package.md`**
   （**2026-08-04 新论文当前写作入口**）。前者已搭好六章基础正文与全部结果占位，后者登记每节的
   问题、实验臂唯一改动、其余固定内容、展品、无明显效应时的诊断—修复—复验路径和技术准入门。
   **弱效应/零效应不是正文回填选项**；未通过入文门即返回诊断和返工。旧TeX未覆盖，旧失效数字回填0项。
   **“时间轴耦合”已于 2026-08-04 被用户撤销**（Claude 自造命题，其唯一检验实验一并作废），
   连“待检验命题”都不再是，任何文档不得带回；“减排杠杆转移”仍是待检验命题，
   不是已证结论。正式结果回填前必须先闭合
   求解一致性、预算、参数来源与代表实例登记。简要记录见
   `docs/handoff/memory/gci_dmm_vrp_manuscript_foundation_20260804.md`。
   **正文纯文字工艺门（用户08-04命令）**：Codex只负责内容初稿、论点/证据边界和事后校审；
   任何进入论文正文的纯文字必须由终端Claude Opus 4.6、`--effort max`最终落笔。
   Claude如果新增数据、机制或结论，退回Claude重写，不由Codex自行润色成终稿。
   **新旧稿继承口径（用户08-04纠正）**：另起炉灶指重建中心问题、证据链和全文结构，不是全盘舍弃旧论文。
   旧稿作为研究资产库按直接继承、核验/修复后继承、退役归档三类审计；陈雨蝶用于全文结构和叙事节奏参照，
   陈婉茹用于混合车队对照、组件消融和条件化结论参照。约束过载目前只是`RISK`，不是已证`FACT`；
   不为复杂而加约束，搜索未找到也不得在无独立证明时写成硬不可行。
   **最高决策权（用户08-04再次明确）**：一切研究决定权归用户，代理只提供真实选项、证据、建议和后果。
   上述两个陈的具体分工、旧稿三类处置、复杂度保护与接入顺序都只是待选方案，不是用户已经拍板。
   不得把代理建议写成`USER DECISION`，也不得用技术门、停止条件或默认值变相替用户选论文路线。


0-A0a. 📐 **`docs/handoff/paper_framework_20260803.md`**
   （**2026-08-03 论文顶层框架，用户决定与候选判断的归属入口**）。
   问题命名已定 **GCI-DMM-VRP**（时变电网碳强度下的动态多车场混合车队多趟车辆路径问题）；
   含研究问题与时间耦合张力、选题合法性的期刊实证依据、研究不足两条、模型进出取舍、
   九子节实验矩阵、管理启示落点、判断归属分栏。该旧矩阵曾包含“零结果如何写”，
   **这一写法已被用户08-04纠正，不得继承到当前正文或实验合同**。
   **`paper_north_star_20260713.md` 在故事问题上已被它取代，且该文 §2 的全部数字不得引用**
   （来自受求解器缺陷影响的路径）。凡判断某项是“用户已定”还是“Claude候选”，必须以本文件§9为准；
   六条Claude判断和九子节中的独立交互实验不得自动升级为用户决定。当前章节与最小展品实现以0-A0新稿为准。

0-A1. ⚠️ **`docs/handoff/session_handoff_20260803_solver_root_cause.md`**
   （**2026-08-03 会话交接，自包含，接手请第一个读这份**）。它打包了：求解器根因的大白话版与技术版、
   四轮诊断产物与关键数字、898 包资产盘点结果、对既有结论的六条处置、
   本会话更正/收回的三条结论、用户 08-03 的全部裁定、落盘位置清单、
   下一步（第三步"改"，未开始）与停止条件。读完它再按需展开 0-A2 与 0-B。

0-A2. ⚠️ **`docs/handoff/memory/solver_completion_reject_root_cause_20260803.md`**
   （**2026-08-03 求解器根因确诊，实验事实的最高优先级入口，排在 0-B 之前**）。
   要点：PyVRP 代理问题不施加每车场实体车数上限，HGS 搜出的方案超编 1–5 辆，
   补全时 24 个候选全数被拒、异常在 `epochal_hgs.py:532-543` 静默吞掉，
   最终解恒为共同初始解 → **随机种子无效、迭代预算无效、结果恒定**。
   已确认 `formal_algorithm_20260802` 与 `formal_ablation_200c_20260803`
   两个正式包 2520 次补全尝试 0 次成功（即论文算法章的正式实验与正式消融实验）。
   **凡基于 China81 MV-HGS-SP 求解路径得出的算法性能结论，一律以本文件为准**；
   0-B 及其下游文档中与之冲突的部分作废。配套读
   `docs/handoff/scout3_corrected_reading_20260803.md`（SCOUT3 两个臂的更正解读）
   与 `docs/handoff/asset_audit_20260803/`（受影响实验包逐包盘点，ASSET1）。
   用户 2026-08-03 定的推进顺序：**先查清（已完成）→ 再验证资产 → 最后改；改完受影响实验须重跑**。

0-B. **`docs/handoff/diagnosis_and_remediation_master_20260731.md`（07-31 的实验事实入口，仅次于 0-A2：
   六组实验终态 / E3-E5-E7 三条根因确诊 / 43 项输入台账复查 / 三份文献取证合并裁定 /
   用户 2026-07-31 三条整改裁决 / 六条执行方案 / 七条未查清台账。**
   **它是 2026-07-31 之后 E3/E5/E7 整改工作的唯一入口，与之冲突的更早文档一律以它为准）**，随后读
   `docs/handoff/session_handoff_20260731_claude_night_shift.md`（前一夜状态：E2/E4/E5/E6 完成、
   TeX 僵尸内容修复、Codex 配额耗尽至 2026-08-05），随后读
   `docs/handoff/session_handoff_20260730_codex_to_new_claude.md`（前一夜状态与决策边界），随后完整读
   `docs/handoff/session_handoff_20260729_document_hierarchy_and_e5_e3e6_state.md`（老 Claude 完整历史、故障现场与文档层级校正）
1. `HANDOFF.md`
2. `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`
3. `docs/handoff/project_prd_execution_map_v2_20260702.md` ⚠️ **历史，非当前入口**
4. `docs/handoff/project_planning_map_20260701.md` ⚠️ **历史，非当前入口**
5. `docs/handoff/memory/MEMORY.md`
6. `docs/handoff/memory/project-prd-execution-v2.md`
7. `docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md` ⚠️ **历史，非当前入口**
8. `CLAUDE.md`
9. `docs/handoff/model_change_approval_register_20260718.md`

> ⚠️ **第 3/4/7 项的定位（2026-07-29 校正，务必先看）**
>
> 这三份的正文主体是**已退役的英国轨**（Goeke80 主场景 / 280 kWh 诊断场景 /
> 09x-09y 排查链 / DR-ALNS 训练线 / E2-G0~G5 门链）。MASTER 第 5 行**自陈**被
> 2026-07-11 用户决定覆盖；PRD v2 的 E2 门链已被 2026-07-25 `FINAL_STOP` 与
> 2026-07-27 `e2_final_closeout_20260727.md` 整体作废。**照单全读会形成过时的项目
> 理解**，切勿据其规划当前工作。
>
> 它们**仍然有效**的部分（硬约束，不因降级而失效）：记录纪律（四件套+report、
> hash 排除 `._*`）、结论标签制（`FACT`/`INFERENCE`/`DECISION`/`HALT_*`/
> `VALID_BUT_WEAK`/`MECHANISM_BUT_TIE`）、禁改语义（`cost.py`/`check.py`/
> `search/evaluation.py`）、四同步链、**已关闭路线台账**（PRD v2 §Phase2 七条；
> 重提任一条前须书面说明"与当时失败条件有何不同"并经用户明示同意）、
> 不要做清单（planning map §9）。
>
> **当前权威链**：`e1_e7_submission_contract_decision_20260711`（唯一拍板单）→
> `e3_e7_experiment_product_design_20260712`（E3-E7 设计权威）→
> `paper_north_star_20260713`（迷路时先读）→ 07-17/20 China pivot →
> `e2_post_v7_algorithm_paper_action_contract_20260725` →
> `e2_final_closeout_20260727`（E2 终局）→
> `contract_e5e7_blind_01_20260728`（E5/E6/E7 结果盲合同）→
> `advisor_instance_selection_01_20260729`（算例选型裁决）。

启动后必须在第一条工作汇报里写明：

```text
已读强制入口：HANDOFF / READ_ME_FIRST / PRD v2 / planning map / memory index / project-prd memory / MASTER / CLAUDE / model-change approval register
已读用户长期工作方法：user_operating_principles
当前任务入口：
当前停止条件：
```

如果上下文预算不足，优先完整读取 `HANDOFF.md`、本文件、PRD v2、当前任务提示词；然后用 `rg` 精准读取 memory 相关节点。不得只凭聊天记忆或旧 prompt 执行。

## 2. 任务类型追加读取

E2 / 算法对比 / T3 / baseline 相关任务还必须读：

- `docs/handoff/memory/instance-lineage.md`（正式 9 阶三班倒）
- `docs/handoff/memory/resetp-alns-independence.md`（完全独立 ALNS 包）
- `docs/handoff/memory/baseline-algorithm-catalog.md`
- `docs/handoff/memory/alns-crush-root-cause.md`
- 历史：`docs/handoff/codex_prompts/20260702_c1_e2_g0_plateau_5174_audit.md`（已执行完，仅档案）
- `docs/handoff/alns_mechanism_innovation_exploration_contract_20260718.md`

动态需求 / E7 / T9 相关任务还必须读：

- `docs/handoff/memory/dynamic-demand-integration.md`

DR-ALNS / x86 / PPO / Track17-25 相关任务还必须读：

- `docs/handoff/memory/alns-crush-root-cause.md`
- `solver/rl/README.md`
- 对应 Track/Pilot 的报告和 prompt，先用 `rg "Track19|Track20|Track21|Pilot25|VALID_BUT_WEAK|HALT_100C_STILL_STARVED"` 定位。

图表 / 论文重灌 / LaTeX 相关任务还必须读：

- `docs/handoff/memory/figure-redesign-task.md`
- `docs/paper_submission_final/paper_main.tex` 中相关段落

参数 / 场景 / 280kWh / Goeke80 相关任务还必须读：

- PRD v2 的 G2 场景口径部分
- `solver/src/setp_solver/prices.py`
- `docs/paper_submission_final/paper_main.tex` 参数表
- `docs/handoff/model_change_approval_register_20260718.md`

## 3. 强制记录制度

运行并发遵循项目实验手册：安全时，8逻辑线程机器尽量使用6--8个独立进程，16逻辑线程机器按比例使用12--16个；任务数不足时只启动真实任务数，内存、温度、磁盘写冲突或总吞吐恶化时按证据降级。并发由实验运行器设置，监控器不得复制任务凑进程数。

新任务默认使用已安装的`codex-experiment-monitor`插件监控。配置前必须先读任务卡、运行入口、结果文件约定、停止条件和受保护文件。`progress_files`只填写任务本来就会持续更新的真实进度文件；若任务在全部计算结束后一次性写结果，必须留空，不得要求任务额外制造心跳或改变写盘节奏。正常运行时`ai.enabled=false`，本地检查不唤醒模型；只有异常、预先声明的阶段点、完成或人工明确检查时才生成最小信息包供判断。预计30分钟内、30--60分钟、超过1小时的任务，对话代理主动读取状态的最短间隔分别为5、10、15分钟；异常和完成事件可立即处理，本地监控器自身的低成本检查不受该间隔限制。

任何实验或会影响论文结论的任务必须留下四件套：

```text
metadata.json
raw_runs.csv
decision.json
artifact_hashes.json
```

并追加一份 `report.md`。`artifact_hashes.json` 必须排除 `._*`、`__pycache__`、`.pytest_cache`、临时 checkpoint、非论文证据。若发现 AppleDouble 污染，标 `HASH_CONTAMINATED_APPLEDOUBLE`，清理后重算 hash，不得覆盖旧 raw data。

任何重大决策、任务完成、HALT、参数变更、场景裁决、实验结论变更，必须同步：

1. `HANDOFF.md` 变更日志
2. `docs/handoff/memory/MEMORY.md` 索引，如新增/更新 memory 节点
3. 相关 `docs/handoff/memory/*.md`
4. 若是交给执行者的下一步，在对话中只下发一个有编号、含明确产物/验收/停止条件的小任务；不得让执行者产总计划，也不得把提示词写入仓库，除非用户明确要求归档

## 4. 禁止越权

未获用户明确批准，不得改：

- `solver/src/setp_solver/cost.py`
- `solver/src/setp_solver/check.py`
- `solver/src/setp_solver/search/evaluation.py`

未获用户明确批准，也不得把下列任何候选写成正式锁定或投入正式实验：单位/币种/物理量转换，观测数据代理化，目标函数或约束变化，默认参数与主情景，新算例生成/抽样/配额/插补/筛选方法，道路矩阵/能耗/充电构造方法，新算法机制，以及统计单位、主要终点、检验与多重校正方法。允许先做来源取证、描述统计和不改变正式入口的探针，但必须写 `HALT_*_AWAITING_USER_APPROVAL` 或 `DRAFT_METHOD_AWAITING_USER_APPROVAL`，并登记到 `docs/handoff/model_change_approval_register_20260718.md`。

上述“需批准”只针对会实质改变研究问题、模型语义、主要比较、正式参数方案或论文故事的选择。文献已经唯一确定、用户已经批准的机械实现，已经证实且不涉及制度选择的接线/记账缺陷修复，只读取证、测试、复算和记录更新，应当自主推进，不得反复请示。任何新增科学门槛、阈值、统计单位、多重校正、预算合格线或预注册条款，必须先给出目标期刊直接相关论文的原文页码；没有出处就不得设立。旧文档中与此冲突的代理自建门禁不再有效。

不得把 `VALID_BUT_WEAK`、`MECHANISM_BUT_TIE`、`HALT_*` 包装成胜利。不得用 x86 绝对成本和 M1 正式表混比。不得用 DR-ALNS 弱信号救 E2。

## 5. 当前最高优先级

2026-07-09 起正式算例与算法底座已拨正：

```text
正式算例 = L-main v2：9 阶三班倒 only（10..200，-01）
正式算法包 = setp_solver.algorithms.resetp_alns（完全独立，禁止半独立）
```

登记：`docs/handoff/memory/instance-lineage.md`、`docs/handoff/memory/resetp-alns-independence.md`。

E2 性能主线（目标：相对第二名约 +5%）必须在上述算例+独立包上重采；旧 e2 混族 / 100-01 结果仅 ARCHIVE。

历史 C1/G0 链（5174 平台等）已 closure 进 memory；不得用旧混族 T3 CSV 写新正式胜负。
