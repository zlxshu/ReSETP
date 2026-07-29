# READ ME FIRST — ReSETP Agent 强制入口

适用对象：Codex、Claude、Claude Code、任何接手 ReSETP 的代码/实验代理。

本文件是仓库级启动门。除非用户明确说“只回答一个简单问题，不读项目上下文”，否则任何非平凡任务都必须先读本文件列出的入口材料。读完之前不得改代码、不得跑实验、不得下论文结论。

## 1. 每轮强制读取清单

每次新对话、恢复上下文、切换机器、切换分支、执行实验、写报告、改代码、生成 Codex 提示词前，必须按顺序读取：

0. **`docs/handoff/session_handoff_20260730_codex_to_new_claude.md`（先读，当前状态与决策边界）**，随后完整读
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
4. 若是交给 Codex 的下一步，写入 `docs/handoff/codex_prompts/*.md`

## 4. 禁止越权

未获用户明确批准，不得改：

- `solver/src/setp_solver/cost.py`
- `solver/src/setp_solver/check.py`
- `solver/src/setp_solver/search/evaluation.py`

未获用户明确批准，也不得把下列任何候选写成正式锁定或投入正式实验：单位/币种/物理量转换，观测数据代理化，目标函数或约束变化，默认参数与主情景，新算例生成/抽样/配额/插补/筛选方法，道路矩阵/能耗/充电构造方法，新算法机制，以及统计单位、主要终点、检验与多重校正方法。允许先做来源取证、描述统计和不改变正式入口的探针，但必须写 `HALT_*_AWAITING_USER_APPROVAL` 或 `DRAFT_METHOD_AWAITING_USER_APPROVAL`，并登记到 `docs/handoff/model_change_approval_register_20260718.md`。

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
