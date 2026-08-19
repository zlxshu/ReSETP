# 对撞第九轮·任务书（发给 Codex，自包含冷启动）

你是 ReSETP 项目设计期的**平级设计师**（不是施工方），与 Claude 对撞。用户 2026-08-17 凌晨指令：
「你们只知道怎么做做什么，**不知道如何验收、且验收合理、而不是自己给自己埋坑定条条框框**。
你和 Codex 互相交流讨论，制定一份能实现目的的、灵活的后续设计规划，可基于前期双方案
（设计书 V3＋施工书）拓展。**开始前务必逐字逐句通读每一条规则**。」

仓库根：`/Volumes/移动硬盘（512G）/ReSETP`（下文相对路径均以此为根）。

## 你必须先知道的今晚新事实（你上次收工后发生的，文档里已落）

1. **P80 已立**（`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md` 文末）：
   昨晚"在跑的长跑"产物落在 /tmp，已随清理全灭——收敛形态**零数据**；
   铁律＝长跑落仓库、交接的是产物不是进程、登记完成信号与续跑说明。
2. **8.8% 噪声数字已降级为无产物**（P73 表内 CORRECTION）：消融格 2989.748…的原始包同样丢在 /tmp，
   三项效应量（2.3%/4.2%/8.8%）一并降级，**不得再引用为噪声量级**。
3. `speedfix_cache_20260816/` 从未生成——是用户叫停后被主动终止的，零源码残留，不是失败。
4. 现在**没有任何任务在跑**。
5. 新导航索引 `docs/handoff/DOC_INDEX_20260816.md` 已建。

## 第零步（强制）：通读规则并背诵

按顺序完整读：
1. `/Users/zhouleixishu/.codex/AGENTS.md`（全局规范 v3）
2. 仓库根 `AGENTS.md`（项目规矩，370 行）
3. `docs/handoff/memory/user_operating_principles.md`（§1–§20）
4. `docs/handoff/algorithm_design_charter_20260815.md`（设计章程：围栏、探针边界、九项完成标准）
5. `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`
6. `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`——P43 起**全文**读到 P80；
   P01–P42 至少读登记表行。重点：P36/37/40/42/43-K/45/47/63-2/65/66/67/68/69/70/71/72/73/74/75/76/77/78/79/80。
7. `docs/handoff/CURRENT_PROJECT_CONTEXT.md` 顶部「接手即读」＋「五之十完整问题清单」＋证据地图。

**你的输出文件第一节必须是"规则背诵"**：用你自己的话逐条列出本轮生效的约束（≥20 条，每条注出处），
证明你读完了。没有这一节的输出视为无效。

## 第一步：写你的独立方案（先不看 Claude 的）

读完规则与下列材料后，**在读 Claude 立场书之前**，先写出你自己的：
- 后续工作的排序（哪个先哪个后，为什么）；
- **验收框架**（每类工作怎么验收、谁判、失败后走哪条路；如何做到"验收合理且不自设门槛"——
  这是用户点名的核心缺口）；
- 你认为"算法定稿"的定义。

材料：
- 双方案本体：`docs/handoff/algorithm_full_design_20260816.md`（设计书 V3）、
  `docs/handoff/algorithm_build_spec_20260816.md`（施工书 SC0–SC9）
- 近期证据包（按需）：`solver/reports/` 下 08-16 各包（sc0/sc1/sc2/sc8/sc10/sc11、speed_diag、
  penalty_window_probe、c7_fairness_ledger、c8_stream、main3b_backend）

把这一部分完整写成输出文件的第二节，之后不得回改（对撞记录要能看出你的独立立场是什么）。

## 第二步：读 Claude 立场书并逐点对撞

读 `docs/handoff/algorithm_design_debate_20260815/round9_claude_position.md`，逐节裁：
同意/反驳/补充，**每条主张必须带三种证据之一——文献页码／代码行号／已存产物数字**；
空口主张自判无效。特别要答它第七节的 Q1–Q8，其中：

- **Q1 必须核代码**：读 `solver/src/setp_solver/algorithms/problem_hgs/runner.py` 与
  `solver/scripts/run_problem_hgs_private_technical.py`，查清现有停止条件（墙钟/迭代/停滞各有哪些、
  行号）、有没有现成迭代封顶开关；裁定"提速甲的逐位验收必须用固定迭代口径"是否成立。
- **Q5 逐件清点**：施工书剩余件（SC3/SC4/SC5/SC6/SC7/SC9…）各自现状——已被 08-16 事实吸收/推翻/仍必须，
  给指向（你是施工书作者，这题你最有资格）。
- Q2/Q4/Q8 给出**最便宜的验证动作**设计（不跑，只设计；预估机时）。

## 第三步：合并提案

给出你版本的最终规划骨架：主链、无悔集、分支表、决策捆绑包（选择题形式）、对双方案的修订清单。
与 Claude 不一致处**保留分歧并写明双方证据**——分歧交用户裁，你我都无裁决权。
明确列一节：**「Claude 错在哪」**（有则逐条，无则写"未发现"，不客套）。

## 边界（硬）

- 只写一个文件：`docs/handoff/algorithm_design_debate_20260815/round9_codex_response.md`。
  **不改任何其他文件**（包括两本双方案——修订建议写在你的响应里，不直接动书）。
- 零求解器运行、零实验、零代码改动；只读代码。
- 不碰三个受保护文件（`cost.py`/`check.py`/`search/evaluation.py`）。
- 结论逐条标 `FACT`/`INFERENCE`/`DECISION`/`UNKNOWN`；你的建议是 `DECISION`，不是用户决定。
- 中文，说人话。

## 完成协议

输出文件第一行必须是 `ROUND9_CODEX_RESPONSE`，最后一行必须是 `ROUND9_END`。
写完即结束，不做额外动作。
