# Codex → 新 Claude 主交接（2026-07-30）

> **一句话状态**：E2 已封存，E4 已完成；E5 正式实验仍在结果盲 pilot HALT，E3/E6 旧运行停在预注册 56/135 且不应盲目重启，E7 尚无获批正式预算；Codex 只补齐了可审查的技术候选底座，三个方法决定仍全部留给用户，当前没有实验或项目看门狗在运行。

这份文档是新 Claude 的第一入口。它承接但不删除老 Claude 的完整交接：
`docs/handoff/session_handoff_20260729_document_hierarchy_and_e5_e3e6_state.md`。
老交接保存了文档层级校正、E5/E3E6 故障现场、看门狗教训和 Claude 自己的错误记录，必须完整阅读；其中“正在运行”“等待某个进程”等实时描述已过时，以本文件和当前进程/产物复核为准。

## 1. 新 Claude 冷启动顺序

先完整读本文件，再完整读老 Claude 交接，然后按
`docs/handoff/READ_ME_FIRST_FOR_AGENTS.md` 的强制清单读取 `HANDOFF.md`、两份历史规划图、memory、MASTER、`CLAUDE.md` 和模型变更批准表。历史规划图和 MASTER 仅保留记录纪律、标签制、禁改语义、四同步链、已关闭路线台账和不要做清单；它们不是当前实验入口。

第一条工作汇报必须复述：已读材料、当前任务入口、当前停止条件。不得只凭聊天摘要继续。

## 2. 角色与责任边界

老 Claude 完成了文档层级校正、顾问裁决落盘、E5 死亡现场与 E3/E6 重启循环取证、看门狗缺陷复盘，并提交了 E5 证据链。Codex 随后按用户“先把底座修好、只写必要代码”的要求，补了 E3--E7 的零搜索输入/规则底座、E5 方案 B 的隔离复判器和 E7 事件流往返校验；没有替用户批准任何方法，也没有启动正式效果搜索。

用户是唯一决策者。新 Claude 不得擅自：冻结 E3--E7 算例分工；在 E5 A/B 中选一个；批准或填写 E7 阶段预算；扩大车队上限、删实例、挑可行子集、换重指派表；把技术可构造写成方法已批准或科学结果。

## 3. Git 与现场事实

当前分支为 `codex/reporting-pipeline`；编写本交接前工作树干净，`HEAD` 与远端均为 `396e2931`。本交接及三处入口同步目前未提交，须保留审阅，不得误称已在远端。最近四个已存在提交：

| 提交 | 内容 |
|---|---|
| `dc5771fe` | 老 Claude 主交接、文档层级校正、HANDOFF 和 memory |
| `98d322fb` | E5 结果盲 pilot HALT 证据包 |
| `560ceaf0` | E5 runner/checker/closeout 源码，闭合 source lock |
| `396e2931` | Codex 技术候选底座、文档记录，以及旧 E3/E6 故障/中间现场 |

必须注意：`396e2931` 中有 805 个
`baselines/china_e3_e7/e3e6_formal_20260729/` 文件。它们是旧失败运行、diagnostics、monitor 和未验证中间实现的留档，不因被提交而升级为权威入口。旧
`run_e3e6_formal.py` 约 3790 行，当前不得直接重启或继续堆代码。

当前没有 E3/E6 runner、E5 runner、项目 monitor 或会话 watcher 在运行。仍有一个 PPID=1、状态 `T` 的孤儿 Python `resource_tracker`（核对时 PID 41251）；清理它属于改变运行现场，须用户明确授权，不能擅自 kill。

## 4. E2--E7 当前状态

| 实验 | 当前硬状态 | 能否写科学结论 | 下一步边界 |
|---|---|---|---|
| E2 | 已完成并封存 | 只按已封存证据写 | 不重启、不改已封存算法探索 |
| E3 | 多车场 D3 45/45 可构造；36 个单车场已排除；旧预注册 56/135 后故障停止 | 不能；没有正式 LOCK/FREE 结果 | 先由用户批准算例分工和多目的场规则，再建立小而可验证的新入口 |
| E4 | 405 个封存解 × 28 日固定路线零搜索复算完成 | 可以，但必须完整报告权衡 | CARBON 对 ASAP：充电排放 −54.9704%，系统排放 −9.7463%，电费 +134.8798% |
| E5 | `HALT_PILOT_STARVATION_SCHEDULE_NOT_CONSTRUCTIBLE`；正式两臂未跑 | 不能；四端点均 `NOT_RUN` | 用户先选 A 或 B；若选 B，从 320 档继续结果盲 pilot，不得直入正式实验 |
| E6 | 150c-01 四场责任显著不对称，但三状态效果尚未跑 | 不能 | 用户批准算例分工后，复用最小底座建立正式入口和独立检查器 |
| E7 | 三规模各五条候选事件流已冻结并可精确回读；无批准预算和正式 China81 runner | 不能 | 用户先批结果盲阶段预算选择器，再谈正式运行 |

E4 的百分比来自同一批 405 个封存 MV 固定解、28 个电网日下 CARBON 与 ASAP 两种充电时序的逐对比较；它不是路线搜索优越性，也不是动态预测鲁棒性。

## 5. Codex 已补的最小技术底座

权威候选目录：

- `baselines/china_e3_e7/mechanism_foundation_20260730/decision.json`：`PASS_TECHNICAL_FOUNDATION_OPTIONS_READY`，同时明确 `formal_search_allowed=false`、`scientific_result_claim_allowed=false`。
- `baselines/china_e3_e7/e5_option_b_assessment_20260730/decision.json`：`OPTION_B_CONSTRUCTIBLE_HIGHER_BLIND_PILOT_REQUIRED`，同时明确 `option_b_approved=false`、`option_b_active=false`、共同预算为空。
- 实现：`mechanism_foundation.py`、`build_mechanism_foundation_20260730.py`、`test_mechanism_foundation_20260730.py`、`assess_e5_option_b_20260730.py`，以及 `e3_exhibits.py` 的 import-shadow 修复。

已验证 33 项测试通过；底座 56 个产物哈希、B 复判包 5 个产物哈希通过；15 条 E7 JSON/TSV 事件流逐字段往返一致；`cost.py`、`check.py`、`search/evaluation.py` 未改。

候选算例分工仅供用户审批，不是批准结论：E3 用 50c-01 主展示、100c-02 稳健性（均做 0/25/50%）；E5 尽量复用 50c-01 与 100c-02；E6 用 150c-01；E7 用 50c/100c/150c 三规模压力测试。这样在机制暴露和图形可读性之间只保留三个题，不能再错误追求单一算例——150c-01 的 40 次充电无一进入 >90% SOC 折半段，不能展示 E5 非线性机制。

## 6. E5 的真正问题与两个待批方案

旧合同下五档预算 32/56/80/160/240 的两臂饥饿数均为 12/11/12/13/13（分母 15）。根因不是单纯预算小：最终路线池重组固定在 `S-1`，独立证书固定在 `S`，若最后严格改进来自重组，则 `L/S=(S-1)/S` 永远超过 0.5。

方案 A 是改变调度，在最终重组之后保留确定性的候选评价预算；这是执行顺序的方法变更，五档需全部重跑，并可能牵动共用路线池语义。Codex 没有实现 A。

方案 B 是只在随机搜索饥饿窗口中排除终端路线池比较和独立证书，但仍把二者保留在总评价账本。Codex 只用 150 条既有布尔改进序列作了隔离、结果盲复判，没有读目标值或成本方向：五档变为 12/9/7/5/5。它消除了 `S-1` 的结构死锁，但 240 档仍是 5/15=33.3%，高于 20% 门槛。因此 B 只是“技术可构造”；用户若批准 B，下一步是 320 档结果盲 pilot，而不是正式 E5。

## 7. 仍须用户亲自决定的三件事

1. 是否批准上述 E3--E7 三题候选分工；若不批，执行代理只报告替代方案和代价，不自行换题。
2. E5 选 A 还是 B；在用户明确选择前，两者都保持 inactive。
3. E7 采用什么结果盲阶段预算选择规则及数值；没有批准前不得用“技术底座已好”代替预算授权。

此外，是否清理 PID 41251 的孤儿 `resource_tracker`、是否调整 deadline/范围，也都由用户决定。它们不能被技术代理顺带处理。

## 8. 新 Claude 接手后的正确动作

先在当前分支重新核对 `git status`、上述两个 `decision.json`、进程表和产物哈希，确认本交接没有漂移。然后只向用户清楚陈述三项待批决定及后果，等待用户拍板。获得具体决定后，一次只恢复一个实验；先写/更新预注册、失败闭合与独立检查器，再启动；每个任务使用只绑定自身权威产物的独立 monitor/watchdog，以产物推进和终态为判据，不能只看进程存活，更不能等全局作业池清空。

未经用户决定，不得以赶 7/31 为由修改方法、降门、扩大算例、跳过 pilot 或把 HALT 包装成弱结果。时间压力是真实风险，但范围和时间怎么动仍由用户决定。

## 9. 关键上游文档与证据

- 老 Claude 完整交接：`docs/handoff/session_handoff_20260729_document_hierarchy_and_e5_e3e6_state.md`
- 算例顾问裁决：`docs/handoff/advisor_instance_selection_01_20260729/report.md`
- 结果盲合同：`docs/handoff/contract_e5e7_blind_01_20260728/report.md`
- E5 终态：`baselines/china_e3_e7/e5_nonlinear_20260729/decision.json`、`report.md`、`done.json`
- 技术候选说明：`docs/handoff/memory/mechanism_foundation_options_20260730.md`
- 项目总变更日志：`HANDOFF.md`

本交接只纠正实时状态和串联证据，不批准任何科学方法或论文结论。
