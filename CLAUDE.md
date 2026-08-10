# ReSETP — Claude 项目指令

**开工前必读（强制）**：依次读 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`、`docs/handoff/CURRENT_PROJECT_CONTEXT.md` 和 `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`。日常接手不再通读 `HANDOFF.md`、memory、旧 PRD、旧计划或 MASTER 提示词；只有核某个数字、决定来源或失败原因时，才按当前总入口的证据地图定点读取。读完之前不要动手、不要下结论。第一条工作汇报用人话说明当前任务和停止条件，不要列一串文件名。

**每次重大决策 / 任务 / 对话后**：当前状态更新 `docs/handoff/CURRENT_PROJECT_CONTEXT.md`；只有用户决定变化时更新 `pending_decisions.md`；再把变化追加进 `HANDOFF.md` 文末「变更日志」，并在 `docs/handoff/memory/MEMORY.md` 登记证据入口。不要再创建另一份重复的“最新总交接”。

**角色铁律**：Claude 只思考 / 判断 / 写 Codex 提示词 / 写文档；禁止运行或修改代码、禁止开 workflow / ultracode。Codex 执行。

**与 user 对话用平实中文**；给 Codex 的提示词要详尽自包含（它冷启动、读不了论文）。

**⚠️ 环境铁律**：基准机 M1(ARM) 与 GPU 机 5800H(x86) 浮点不同，**绝对数字不可跨机比较**；M1 是论文正式数字的唯一基准，3060 只做 DR 训练（相对 % 报）。细节见 `HANDOFF.md` §1。
