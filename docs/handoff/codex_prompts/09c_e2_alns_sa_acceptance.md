# 提示词⑨c — E2 ALNS 根因修复：接入标准模拟退火接受 + 降温表（阶段②续，关键）

> 先读 `HANDOFF.md` + `baselines/e2_alns/{diagnosis,ablation,final_report.md}` + `scan_bridge_verdict.json`。M1 系统 Python、`codex/reporting-pipeline`。承接 09/09b 两次 HALT。

## 根因（已用代码+对照坐实，别再当未知）
方差/塌缩的根因 = **接受准则**，不是构造、不是算子能力：
- `alns_wouda.py:232 _make_acceptance_criterion`：winner ALNS 默认 `HillClimbing()`（纯爬山），flag 打开也只是 `RecordToRecordTravel`（RRT 阈值）。**从未接入标准 ALNS 的模拟退火(SA)接受。**
- **对照铁证**：LNS 基线 `metaheuristic_baselines._run_lns` 用 `accept_metropolis` + 几何降温（SA，高娇娇 GLNS Φ=0.05/μ=0.95）→ 这正是 LNS 稳（std 7–29）的原因；winner ALNS 用爬山 → 不稳（std 58–604）、200c 塌缩。
- 09b 数据佐证：ALNS 的 **best 多档比 LNS 的 mean 还低**（能找到更好解），但 **mean 被巨大方差拖垮**——典型"爬山路径依赖"，正是 SA 要解决的。
- 09b 把 RRT 在 128 eval 上判"有害"= 测错了（RRT≠SA，且 128 eval 退火表跑不开）。

## 目标
把 **标准 Ropke-Pisinger 模拟退火接受 + 几何降温表**接入 E2 ALNS（与已 promote 的 TRUE_REPAIR+ADAPTIVE_Q+扫描构造组合），按墙钟预算调好降温，使 **方差降到 LNS 量级、在 69 基准（含 threeshift 全档）稳定追平/超过 LNS、收敛曲线平滑可见**。**这是成熟 ALNS 的标准配置，不是自创**（Ropke & Pisinger 2006；N-Wouda `alns` 库已是依赖，`alns.accept` 里有 `SimulatedAnnealing`）。

## Phase 1 — 接入 SA 接受 + 调降温（照文献）
1. 在 `_make_acceptance_criterion` 增加 **SA 分支**（新 flag 如 `SETP_ALNS_CRUSH_SA_ACCEPTANCE`，给 E2 ALNS 用；legacy `run_winner_kernel` 默认仍 HillClimbing 不动，保锚）。用 `alns.accept.SimulatedAnnealing`（或等价 Metropolis exp(-Δ/T)）。
2. **降温表按文献标准设定**：起始温度用 Ropke-Pisinger 规则——令"比初始解差 w%（如 5%）的解以 0.5 概率被接受"反推 start_temp（`alns` 库的 `SimulatedAnnealing.autofit(init_obj, w, 0.5, num_iters)` 可直接用）；几何降温到接近 0（末段纯爬山式利用）。
3. **降温随墙钟预算自适应**：因 E2 是等墙钟、不同规模迭代数不同，降温步长要按**预估迭代数/剩余预算**定，保证 temperature 在预算末段降到近 0（大算例 200c 别还停在高温乱跳）。可用一次短预跑估每秒迭代数再设。
4. 也把 LNS 同款参数（Φ=0.05/μ=0.95 几何降温）作为对照备选，二者取在 Phase 2 表现好的。

## Phase 2 — 在真实墙钟预算重测（决定性，别再用 128 eval）
- 预算 = 已锁的规模阶梯：**threeshift 50–100c=300s / 150–200c=900s**，vanilla/multidepot 同档；seed≥5（降方差判定噪声）。
- 子集：**threeshift 全 5 档(50/75/100/150/200c)** + vanilla/multidepot 各 2 档交叉。
- 对每算例记 mean/best/**std**/CV-EV/时间/零违约 + **收敛曲线**（best-so-far vs 时间）。
- **判定门（必须同时满足）**：① ALNS-SA 的 **std 降到 LNS 量级**（不再 200c 塌缩）；② threeshift 全档 **mean 追平或超过 LNS**（gap ≤ 0 或不显著为正，Wilcoxon 不再支持 LNS 更好）；③ 收敛曲线平滑收敛（给图用）；④ 零违约。
- 输出 `baselines/e2_alns/sa_acceptance_gate.md` + `sa_raw_runs.csv` + `verdict.json` + 收敛曲线数据。

## Phase 3 — 守锚 + 定稿
- 重跑 `winner_restoration run-current`（seeds1-10/16000eval），确认 legacy `100-01` 锚仍 £4878.331796/零违约/delta 0.0（SA 只进 E2 路径，legacy 不动）。
- 过门则把 SA 接受写进 `run_e2_alns_final()` 的 promote flag 组合，更新 `final_report.md`（含降温参数 + Ropke-Pisinger 出处 + 与 LNS 的 std/mean 对照）。

## 诚实出口
- 若 **SA 调好、真实预算下 ALNS 仍被 LNS 系统性击败**（不太可能，但若发生）→ 报告、列出 SA 降温的具体设定，回头查是否降温表/起温没调对（Ropke-Pisinger/IALNS-SA 文献），**不臆造新机制、不退回 DR-ALNS 救场**（user 定：DR-ALNS 是锦上添花、未训练，不用于救场）。

## 边界
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义；不动 legacy `run_winner_kernel`（锚必复现）。
- 不自创：SA 接受+降温照 Ropke-Pisinger 2006 / N-Wouda `alns` 库 / 高娇娇 GLNS 参数；拿不准停下报告。
- 系统 Python + `PYTHONHASHSEED=0`；内部确定；每改动绑 commit；单测过。

## 交付
`baselines/e2_alns/{sa_acceptance_gate.md, sa_raw_runs.csv, verdict.json, 收敛曲线}` + SA 接受代码 + 单测 + 锚守门证据 + 多次 commit（写 hash + 降温参数 + 文献出处）。
