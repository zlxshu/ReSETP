# 提示词⑨b — E2 ALNS：补 GLNS 扫描构造，跨过 ALNS-vs-LNS 那道门（阶段②续）

> 先读 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md` + `baselines/e2_alns/{diagnosis.md,ablation.md,final_report.md}`。M1 系统 Python、`codex/reporting-pipeline`。**承接阶段②（提示词09）的 HALT_ALNS_NOT_PROMOTED。**

## 上一轮结论（已确认，别重做）
- 锚守门 PASS：`100-01` legacy winner mean `£4878.331796` / seed2 `£4779.0534` / 10/10 零违约 / delta 0.0——改动未污染旧路径。
- 强化候选 `TRUE_REPAIR=1 + ADAPTIVE_Q=1` 在 `e2-vanilla-100c-01`（6023 < LNS 6120，赢）、`e2-multidepot-100c-01` 上改善；但在 `L-main` 输 LNS（8828 vs 8281）。
- **精确诊断**：LNS 优势来自**扫描/sweep 全油车构造**——ALNS 从暖启动（差的全油车）做破坏-修复、纯爬山过不去山脊→滑进电车盆地；LNS 一上来就拼出好的全油车解。缺的是这套**构造**，不是某个 destroy/repair 开关。

## 目标
把 **高娇娇2024 GLNS [TAQUPN3F] 的扫描构造 + 整路重建**作为**显式 ALNS 组件（flag）**加入，让 ALNS 也能到达好的全油车盆地，跨过“不被 LNS 系统性击败”的门。**设计照 GLNS 文献，禁止自创**；ALNS 仍是更丰富的框架（扫描构造只是它众多算子之一 + 自适应选择）。

## Phase 1 — 实现扫描构造组件（照 GLNS，做成 flag）
在 `winner_operators.py`/`alns_wouda.py` 加一个新组件（建议 flag `SETP_ALNS_CRUSH_SCAN_RESTART` 或 `SCAN_CONSTRUCTION`），两种实现取其一或都做成可选：
1. **多起点/扫描重启**：周期性（或停滞 K 步时）用**扫描/sweep 构造**生成一个全油车候选起点（复用基线里已验证有效的扫描构造路径，如 `_angle_scan_order` + `_all_cv_solution_for_session`），并入 ALNS 的接受/best 比较——给搜索一个能到全油车盆地的“逃生起点”。
2. **GLNS 式整路重建大邻域**：destroy 移除大批整路客户 → 用扫描/最远-后悔 repair **优先重建为 CV 路线**（成本感知，复用阶段②的 TRUE_REPAIR），仅当总成本下降才接受。
- 与已 promote 的 `TRUE_REPAIR + ADAPTIVE_Q` 组合；扫描组件默认状态由 Phase 2 消融定。
- 不改 `run_winner_kernel()` legacy 路径；只扩 `run_e2_alns_final()`。

## Phase 2 — 在“真实预算”重测（关键，别再用 128 eval 下结论）
上一轮探针只有 128 eval=太小、且测在不在基准内的 L-main。本轮：
- **预算贴近正式协议**：每 run 给**有意义的墙钟**（建议 ≥120s，或几千 eval），而非 128 eval。
- **测在 69 基准算例上**（重点 threeshift 50/75/100/150/200c——三班是 EV 真正相关、最易输的一档；外加 vanilla/multidepot 各几档；L-main 仅作旁证、不作门）。
- 每算例对 **强化后 ALNS（+扫描）vs LNS 基线**，多 seed，记 best/mean/CV-EV/时间/零违约。
- **门**：ALNS（+扫描）在 69 基准上**不再被 LNS 系统性击败**（threeshift 档追平或更优、其余档领先），且零违约 → 该组件 promote；写进 `run_e2_alns_final()`。

## Phase 3 — 重守锚 + 定稿
- 重跑 `winner_restoration run-current`（seeds 1-10/16000eval），确认 `100-01` legacy 锚仍 £4878.331796 / 零违约 / delta 0.0。
- 更新 `baselines/e2_alns/{ablation.md, final_report.md}`：扫描组件的消融证据 + 最终 promote 的 flag 组合 + 文献出处（GLNS 高娇娇2024）。

## 诚实出口（必须执行，防止硬刚）
- 若**加了扫描构造、在真实预算下 ALNS 仍只能追平而非超过 LNS**（尤其 threeshift 最难档）→ **不要再无限加料硬刚**。如实报“ALNS 与 LNS 同属大邻域、在最难档并列第一梯队”，停下来交 user 决定是否接受“并列领先 + 机制差异化”的诚实定位（这与项目既定 bar“对手更强+贴近最优+创新点清晰”一致，并非失败）。
- 若仍被**系统性击败**（多数档输）→ 报告，回头再查 GLNS/Ropke-Pisinger 是否还有没补的关键组件,不臆造。

## 边界
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义；不动 legacy `run_winner_kernel()`；锚必须复现。
- 不自创：扫描构造/整路重建照 GLNS；拿不准停下报告。
- 系统 Python + `PYTHONHASHSEED=0`；内部确定；每改动绑 commit；单测过；跑不出诚实 HALT。

## 交付
更新后的 `baselines/e2_alns/{ablation.md, final_report.md}` + 扫描构造组件代码 + 单测 + 锚守门证据 + 多次 commit（写 hash + flag 组合 + GLNS 出处）。
