# Codex 提示词 15 — 终局方案：Track A 公平基线对比(真·论文赢点) + Track B 动态 DR(future-work)

> Claude 写定（2026-06-29）。**关键背景（必须懂）**：Pilot25 的"对弱场 +27.8%"是**假的**——`pilot25_test_rows.csv` 实锤 GA/PSO/ACO/IWD/VNS 的 best_cost 全=warm start(823.15)、哈希相同、各跑 0.2-0.6s，因为只给了 **120 次评估**，种群法(GA 200/ACO 20×100/IWD 20×100)连一代都跑不完，原样交回初始解。**这不是赢，是对手饿着上场。** 静态 DR 已 6 次证伪(Pilot17-25)，死。本提示词做两件真事：**A=把"赢弱场"用公平预算做成真结果（论文命根）**；**B=DR 挪到动态(唯一没证伪的方向，future-work)**。冷启动自包含、自动过夜、带闸。

## 0. 诚实边界
A 的结果**未知**：公平之后强方法可能仍 ≥10% 领先，也可能远小于 27.8%——**必须公平跑出来，禁止再拿饿肚子的基线充数**。B 不保证成。不许把"对手没跑起来"当赢、不许把欠训当 PASS。

## 1. 绝对边界 + 过夜铁律（沿用 `10_*.md` §9 全部）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py` 语义；worker py313+NumPy2.3.5；只 x86 同机相对%；飞行前检查；周期 checkpoint+resume guard；墙钟≤8h；防 OOM；**禁过夜 push/rebase**(dr-x86 留人工 reconcile；另：`.git` 有 `._*` bad-sha1 噪声，**别擅自 prune**)；只 force-add 小产物；增量 progress 日志；连续 3 次自修失败升级诊断停；每改动记"症状→出处→改哪→为什么"。

---

# Track A — 公平基线对比（真·论文 10% 赢点，优先）

## A1. 组强方法（接上 M1 已验证的好招式）
强方法 = winner kernel(`run_winner_kernel`/`e2_alns_*`) + **碳感知** + **最优充电插入(FRVCP，参 Cao `FRVCP.txt`/`charging.py`)** + **SISR/`route_segment_removal`** + **公平(`fairness.py`)** + 局部搜索(`local_search.py`)。先在 25/50c 上跑通、零违约。**并先证"强方法明显优于 plain ALNS"**(plain=基础随机破坏+greedy 修复)，否则强方法不成立、先修这。

## A2. 公平预算（命门，杜绝假 27.8%）
所有算法（强方法 + GA/PSO/ACO/IWD/VNS，能跑就加 TS/SA/GWO；用 `metaheuristic_baselines.py`/`metaheuristic_baseline_runner.py`）**同等充足预算**：**等墙钟**(首选，最公平) 或 **同 16000 次 evaluate**（HANDOFF §3 口径），**绝不是 120**；同一 warm start(`make_shared_initial_solution`)；10 seed；scipy Wilcoxon。
- **强制基线健康验证（防再假）**：每个基线必须 `actual_evals/budget ≥ 0.9` 且 `best_cost < warm_start_cost`(真改进了初始解)且解哈希≠warm start 哈希。**任一基线没消耗预算/没改进初始解 → 标 `HALT_BASELINE_NOT_RUNNING` 修它(throughput/解码/接口)，不许把它算进对比。** 这是 Pilot25 假 27.8% 的直接补丁。

## A3. 判级（诚实）
小规模(25/50c)公平对比，强方法 vs **健康跑起来的**弱场：
- `WIN_REAL`：每个基线都健康(A2 验证过) 且 强方法平均领先 ≥10% 且 Wilcoxon 显著 且 零违约 → **真·论文赢点** → 报告并建议推全规模(50-200c 三班倒，注意 throughput，必要时分批/等墙钟)。
- `MARGIN_SMALL`：基线健康但强方法领先 <10% → **诚实**：公平后差距没到 10%，需(a)再强化强方法(更多 FRVCP/分解/碳机制)或(b)接受真实数字、调整论文叙事。
- `HALT_BASELINE_NOT_RUNNING`：基线没跑起来 → 先修基线再比（这是当前最可能的拦路，优先解决）。

## A4. Track A 交付物
`trackA_fair_report.md/json`(强方法 vs plain ALNS + vs 各基线，每基线健康指标 actual_evals/改进/哈希 + 平均领先% + Wilcoxon + 判级 + 人话)、`trackA_rows.csv`(逐算法逐seed，含基线健康列)、强方法最优解。

---

# Track B — 动态 DR（future-work，DR 唯一没证伪的方向）

## B1. 设定
用 `dynamic.py` 的动态滚动重规划接口：分阶段、新需求到达；DR 学**在线决策**(来单后如何插入/重排，而非静态从零优化)；对照 = **每阶段用 ALNS 重新求解**(re-optimization baseline)。这是 RL 真本事所在(序贯决策/不确定性)，区别于已死的"静态控制 ALNS"。

## B2. 判级（诚实，future-work 级）
小规模动态算例上，DR-online vs ALNS-re-solve(同响应预算)：DR 显著更优(总成本/响应时延) → `DR_DYNAMIC_PROMISING`(值得 future-work 深做)；持平/更差 → `DR_DYNAMIC_FLAT`(诚实记录，DR 整体转 future-work)。**不保证成；不许把欠训当 PROMISING。**

## B3. Track B 交付物
`trackB_dynamic_report.md/json` + 对比 CSV + 小模型。人话：动态上 DR 比"每阶段重跑 ALNS"强不强、值不值得 future-work。

---

## 2. 执行顺序与总判级
**先 A 后 B**（A 是论文命根、B 是 future-work）。A 出 `WIN_REAL` → 论文头条到手，B 可选做。A 出 `HALT_BASELINE_NOT_RUNNING` → 全力修基线（这是真问题所在）。最终 `final_report.md` 人话汇总：A 公平后到底领先弱场多少(真数字)、强方法是否明显胜 plain ALNS、B 动态 DR 有无希望、下一步。

## 3. 资料顺序
先读 HANDOFF + `metaheuristic_baselines.py`(基线为何没跑起来) + `charging.py/local_search.py/fairness.py/winner_operators.py`(强招式) + `dynamic.py`(动态)。先证据、后改、带闸、不拍脑袋、不谄媚、不拿饿肚子基线/欠训当赢。
