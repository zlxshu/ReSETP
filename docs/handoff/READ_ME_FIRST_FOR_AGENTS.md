# READ ME FIRST — ReSETP Agent 强制入口

适用对象：Codex、Claude、Claude Code、任何接手 ReSETP 的代码/实验代理。

本文件是仓库级启动门。除非用户明确说“只回答一个简单问题，不读项目上下文”，否则任何非平凡任务都必须先读本文件列出的入口材料。读完之前不得改代码、不得跑实验、不得下论文结论。

## 1. 每轮强制读取清单

每次新对话、恢复上下文、切换机器、切换分支、执行实验、写报告、改代码、生成 Codex 提示词前，必须按顺序读取：

1. `HANDOFF.md`
2. `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`
3. `docs/handoff/project_prd_execution_map_v2_20260702.md`
4. `docs/handoff/project_planning_map_20260701.md`
5. `docs/handoff/memory/MEMORY.md`
6. `docs/handoff/memory/project-prd-execution-v2.md`
7. `docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md`
8. `CLAUDE.md`

启动后必须在第一条工作汇报里写明：

```text
已读强制入口：HANDOFF / READ_ME_FIRST / PRD v2 / planning map / memory index / project-prd memory / MASTER / CLAUDE
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

## 3. 强制记录制度

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

