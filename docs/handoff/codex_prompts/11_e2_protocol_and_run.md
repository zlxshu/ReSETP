# 提示词⑪ — E2：等墙钟公平协议 + 正式对比出 T3（阶段④+⑤）

> 先读 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md`。M1 系统 Python、`codex/reporting-pipeline` 分支。**依赖阶段①（69 算例）+ ②（强化后 ALNS）+ ③（文献最优 8 基线）全部就绪。**

## 口径：改用等墙钟（已定）
03 HALT 实证：**等评估次数（16000 eval）对慢基线在大算例上根本跑不完**（GWO L-main 900s 仅 2208/16000；3600s 单任务 >1h 未返回）。E2/T3 的学术标准 = **最终成本 + 时间，对 best-found**（user 已确认）。故 **E2 一律用等墙钟**：每个算法每个算例给**同样的墙钟预算**，报时间内最优解。放弃 16000-eval 口径。

## Phase 0 — 协议 + 硬超时（先修基础设施）
在 `solver/src/setp_solver/search/metaheuristic_baseline_runner.py`：
1. **等墙钟模式**：每个 run 给 `max_runtime_seconds = T(n)`，T 随规模设定（小算例少、大算例多；定一个**可辩护的规则**并写进报告，例如按客户数分档：10–25c=60s / 50–100c=300s / 150–200c=900s，或线性 T=base×n。规则一旦定就对**所有算法一视同仁**）。
2. **硬超时（修 03 的 fallback overrun bug）**：03 发现 runner 只在任务返回后才夺回控制权→单个 repair 能跑 >1h。加**每任务硬墙钟 kill**（到点强制终止该 run、记其当时 best），保证总时长可控。
3. **best-found 参照**：每算例的参照值 = 该算例上**所有参赛算法**跑出的最好可行解；表里该算例最好解加粗，gap% 对它算。**不挂任何外部 BKS**。
4. 输出 `baselines/e2_formal/protocol.md`（墙钟规则 + 硬超时实现 + best-found 定义）。

## Phase 1 — 正式跑（69 算例 × 全算法 × N seed）
- 算法集：**强化后 ALNS（阶段②）+ 公平 SA + 8 个文献最优基线（阶段③）**。（DR-ALNS 列留空，等 x86 pilot 合并后补；本轮不含。）
- N seed：建议 **10**（小算例可全 10、超大算例若墙钟紧可降到 5 并注明）。
- 每算例每算法记：best/mean/std 总成本、路线数、CV/EV 混合、违约数（**必须零**）、墙钟、评估数、**收敛曲线**（best-so-far vs 时间，作 F2 源）。
- 暖启动统一 `make_shared_initial_solution`；**每个算法的成本必须过同一 `score_candidate/EvalBudget`**；任何 `sys.executable` 子进程路径要审（防 `run_alns_wouda_strengthened` 式漂移）。
- 全程系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5 + `PYTHONHASHSEED=0`；并行可用 `SETP_META_PARALLEL_WORKERS`，但**最终上报数字要可复现/内部确定**。

## Phase 2 — 出表（T3）+ 收敛图（F2）
- `baselines/e2_formal/t3_comparison.csv`：行=算例（按 category + 规模排序）、列=各算法的 best/mean/std/time/routes/cv-ev；每算例最好加粗标记；每算法 vs **强化后 ALNS** 的 gap% + scipy Wilcoxon p + 配对胜场；分**类别×规模组**与**总体**汇总均值。
- `baselines/e2_formal/convergence/`：收敛曲线数据（F2 源）。
- `baselines/e2_formal/report.md`：**结论一句话放开头**——在 vanilla/multidepot/threeshift 三类、9 档规模上，强化后 ALNS 对这 8 个文献最优基线 + 公平 SA 各是什么结果（赢/平/输，多少 gap%，Wilcoxon 显著否）。**诚实**：哪个算例/规模 ALNS 没赢、和谁打平（尤其 LNS）、哪个近最优地板大家并列，如实写。

## 验收
- 等墙钟协议 + 硬超时实现并验证（无单任务超时失控）；墙钟规则写明、对所有算法一致。
- 69 算例 × 全算法 × N seed 跑完、**零违约**；T3 表 + Wilcoxon + 收敛曲线齐全；best-found 参照、gap% 正确。
- 每数字绑 commit；系统 Python 金标准；多次 commit。
- 诚实：ALNS 第一梯队但与 LNS 并列/在近最优地板打平=如实报，不强行包装“碾压”；机制差异化（碳感知/协同/公平/动态）是另一篇的事，不在 T3 里硬凑。

## 边界
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义；协议只动 runner 层。
- 不动算法逻辑（阶段②③已定稿）；本阶段只跑 + 出表。
- 系统 Python 金标准；跑不出诚实 HALT，不注水、不混旧数据。

## 交付
`baselines/e2_formal/{protocol.md, t3_comparison.csv, convergence/, report.md, manifest.json}` + runner 等墙钟+硬超时改动 + 单测 + 多次 commit（写 hash）。
