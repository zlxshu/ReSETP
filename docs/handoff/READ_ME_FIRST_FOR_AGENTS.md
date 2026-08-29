# READ ME FIRST — ReSETP 简明入口

适用对象：Codex、Claude、Claude Code，以及任何接手本项目的代理。

## 开工前只读这两份项目事实

1. `docs/handoff/CURRENT_PROJECT_CONTEXT.md`
   当前目标、来时路、真实完成度、病灶、停止现场和证据地图。
2. `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`
   用户已定与未决事项的唯一精确登记。

项目行为规矩由仓库根目录 `AGENTS.md` 承担；支持该文件的代理会自动加载。Claude 另受根目录 `CLAUDE.md` 约束。这些是规矩，不是额外的项目事实入口。

读完上述两份事实之前，不改代码、不跑实验、不下论文结论。第一条对用户的汇报只需用人话说明当前任务和停止边界，不再罗列几十份“已读文件”。

## 当前最高状态

- `docs/paper_v2/paper_main.tex` 与同目录 PDF 是唯一正式论文入口；8 月 29 日的最新 20 页稿已整体提升到该位置，
  旧 18 页底座、施工副本、候选稿、快照、备份稿和编译副本均已移出工作树。
- 当前论文是模型目标、两种协同比较口径和动态事件表的唯一语义源；代码、数据与后续实验均向论文对齐。
- 目标函数只保留论文中的五项；论文外另列的三项成本从目标及其接线中删除。
- 动态实验唯一事件源为
  `data/dynamic_streams/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_mixed_events/events.tsv`；
  后续重跑并回填论文，本轮不启动长跑。
- 基本代码对齐已经完成：五项目标、两种协同口径、mixed events、重复次数和停滞停止规则已进入现行入口；
  短测试 230 项通过，本轮没有启动长跑，也没有回填新实验数字。

更完整的事实、数字和边界以 `CURRENT_PROJECT_CONTEXT.md` 为准，不要根据本页摘要自行下新结论。

## 旧材料怎么用

以下材料全部保留，但都不是冷启动必读：

- `HANDOFF.md`：历史时间线和变更日志；
- `docs/handoff/memory/MEMORY.md`：历史主题索引；
- `docs/handoff/memory/`：专题记忆和证据摘要；
- `docs/handoff/project_prd_execution_map_v2_20260702.md`、
  `docs/handoff/project_planning_map_20260701.md`、
  `docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md`：旧路线、旧计划和已关闭路线的历史证据；
- `docs/handoff/` 下其他报告：特定源码、实验、文献或决定的证据包。

只有在核对某个具体数字、决定出处、失败原因、文献页码或代码时代时，才按 `CURRENT_PROJECT_CONTEXT.md` 的证据地图定点读取。不得全文扫描后把旧状态重新带回当前主线。

## 冲突时的顺序

1. 用户当前对话中的明确指示；
2. 全局和项目 `AGENTS.md` 中的现行规矩；
3. `pending_decisions.md` 中的精确用户决定；
4. `CURRENT_PROJECT_CONTEXT.md` 中的当前事实；
5. 原始代码、原始实验包、正式文献和用户原话；
6. `HANDOFF.md`、memory、旧计划、旧提示词和代理总结。

如果当前事实与原始证据冲突，停止推断，核原始证据并把更正写回当前事实源；不得挑对自己方便的一份继续。

## 按任务定点补读

- 改算法或跑测试：读相关源码、测试和 `CURRENT_PROJECT_CONTEXT.md` 指向的当前算法证据。
- 做实验：读本轮获批实验合同、原始数据和评价器；先说明动作、影响和预计耗时，再按授权开跑。
- 改论文：读当前论文基础稿、实验合同和已批准结果；纯文字终稿仍由终端 Claude 完成。
- 查文献或公式：读原文页码、章节、公式和适用前提，不能只看摘要或代理转述。
- 查用户是否拍板：只查 `pending_decisions.md`；若登记与原话冲突，再查原话证据册。
- 查历史失败路线：先看 `CURRENT_PROJECT_CONTEXT.md` 的“不得从历史材料复活的做法”，需要细节再追原报告。

## 任何任务都不能越过的边界

- 三个受保护文件未经用户当次明确批准不得修改：
  `solver/src/setp_solver/cost.py`、`solver/src/setp_solver/check.py`、
  `solver/src/setp_solver/search/evaluation.py`。
- 任何结果都同时报告完成客户数和完成需求量；少服务不能换成本或排放下降。
- M1 与 5800H 的绝对数字不可跨机器比较；M1 是论文正式数字的唯一基准。
- 实验保留真实运行数据、完成客户数、完成需求量、可行性和失败情况；不设固定文件套件，
  不要求哈希、SHA、指纹或复现证书。
- 不指定、冻结或记录随机种子；论文明确规定重复次数的按论文执行，没有规定的只运行一次。
- 不设墙钟时限或迭代次数上限；沿用现有连续 500 次迭代无改善时停止的规则。
- 本轮不启动长跑；不得隐藏失败或把构造情景写成现实观察。

## 收口怎么记

发生重大任务、用户决定、状态变化或纠错时：

1. 更新 `CURRENT_PROJECT_CONTEXT.md` 的当前状态；
2. 只有用户决定变化时才更新 `pending_decisions.md`；
3. 在 `HANDOFF.md` 文末追加一条时间线；
4. 在 `docs/handoff/memory/MEMORY.md` 登记证据入口。

优先更新现有事实源，不再为同一现场新增另一份“最新交接”。历史专题报告可以保留，但不能取代这套两文档入口。
