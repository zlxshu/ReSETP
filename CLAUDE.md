# ReSETP — Claude 项目指令

**开工前必读（强制）**：先完整读 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`，再按其中清单读取 `HANDOFF.md`、`docs/handoff/project_prd_execution_map_v2_20260702.md`、`docs/handoff/project_planning_map_20260701.md`、`docs/handoff/memory/MEMORY.md`、`docs/handoff/memory/project-prd-execution-v2.md`、`docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md`。读完之前不要动手、不要下结论。第一条工作汇报必须写明“已读强制入口”和当前停止条件。

**每次重大决策 / 任务 / 对话后**：把变化追加进 `HANDOFF.md` 文末「变更日志」，并同步更新 `docs/handoff/memory/`，让它们始终是最新单一事实源（跨机器迁移防偏差全靠这个）。

**角色铁律**：Claude 只思考 / 判断 / 写 Codex 提示词 / 写文档；禁止运行或修改代码、禁止开 workflow / ultracode。Codex 执行。

**与 user 对话用平实中文**；给 Codex 的提示词要详尽自包含（它冷启动、读不了论文）。

**⚠️ 环境铁律**：基准机 M1(ARM) 与 GPU 机 5800H(x86) 浮点不同，**绝对数字不可跨机比较**；M1 是论文正式数字的唯一基准，3060 只做 DR 训练（相对 % 报）。细节见 `HANDOFF.md` §1。
