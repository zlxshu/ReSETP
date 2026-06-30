# Codex 提示词 16 — 最后一次尝试：Track A 拿下论文赢点 + Track C 给 DR 按"已发表做法"的最终公道一枪

> Claude 写定（2026-06-29），第一手读穿证据后定。**结论已硬**：①静态"AI 指挥 ALNS"到顶 +1~2%（6 次实验 + 读穿 Cao `ALNS.py:540-658` 训练循环——AI 只每 `iter_per_action` 步挑算子，真正干活的是带 **2-opt×10** 的重修复 + 充电插入，且脚本硬写"赢不了就报错丢弃"）。②论文赢点是真的且近：Track15 公平数据，**普通 ALNS 已比健康 GA 领先 8.5%**；拦路虎是**基线没跑起来(PSO 给满 16000 评估仍返回起点解)**与**"强方法"焊错(比普通 ALNS 差 3.69%)**。本提示词：A=把赢点做成真；C=给 DR 一次"按 Cao 真做法(重修复+编排)"的最终一枪以彻底定论。冷启动自包含、自动过夜、带闸、不谄媚、不拿坏基线/欠训当赢。

## 0. 绝对边界 + 过夜铁律（沿用 `10_*.md` §9）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py` 语义；worker py313+NumPy2.3.5；只 x86 同机相对%；飞行前检查；周期 checkpoint+resume guard；墙钟≤8h；防 OOM；**禁过夜 push/rebase/prune .git**(留人工)；只 force-add 小产物；增量 progress 日志；连续 3 次自修失败升级架构问题写诊断停；每改动记"症状→出处→改哪→为什么"。

---

# Track A — 拿下论文赢点（优先，winnable）

## A1. 深挖修活基线（真问题所在，别再修壳）
**根因 PSO 等为何给满 16000 评估仍返回起点解**：单步 trace 一次 PSO——它生成的候选解**有没有真的不同？有没有被 evaluate？best 有没有更新？解码后是否始终塌回起点？** 定位是 decode/operator/最优追踪哪一环坏了，**修真实机制**（可能是多个基线共用的同一 bug）。验证标准：每个基线产出**与起点不同、且更优**的解。
- **基线健康闸(强制)**：每基线须 `actual_evals/budget≥0.9` 且 `best_cost<warm_start` 且 `hash≠warm_start_hash` 且零违约。任一不过 → 继续修该基线，**不许跳过、不许当对手缺席就 claim 赢**。
- 8 基线尽量全活：GA(已修通)/PSO/ACO/IWD/VNS(+TS/SA/GWO 若接口在)。

## A2. 用验证过的方法（别用焊坏的"强方法"）
**先证 winner kernel ≥ 普通 ALNS**(同预算同 warm start)；若 winner kernel 也不明显更优，则**普通 ALNS 就是我们的方法**(它已 +8.5% vs GA，够)。碳感知/FRVCP/SISR/公平这些零件**只有逐个证明"加上去不变差"才保留**，否则剔除——**不许再出"强方法比普通 ALNS 还差"。**

## A3. 公平对比 + 判级
方法 vs 全部**健康**基线：**同等充足预算(等墙钟 或 16000 eval)**、同 warm start、10 seed、scipy Wilcoxon、零违约。先 25/50c。
- `WIN_REAL`：所有基线健康 且 方法平均领先 ≥10% 且 显著 → **论文赢点到手** → 建议推全规模(50-200c，throughput 注意，分批/等墙钟)。
- `MARGIN_REAL_BELOW_10`：基线健康但领先 X%(<10%) → **诚实报真数字 X%**；建议(a)强化方法(FRVCP/分解/碳机制，逐个证不变差)冲 10%，或(b)按真实 X% 调论文叙事。
- `HALT_BASELINE_STILL_BROKEN`：基线修不活 → 写诊断，这是 throughput/decode 的真硬骨头，需专门攻。

---

# Track C — DR 最终公道一枪（按 Cao 已发表真做法，彻底定论）

## C1. 这次按"会赢的写法"建 DR（我们从没这么做过）
前几轮 DR 用的是**弱修复 + 学破坏**；Cao 的真做法是 **AI 编排 + 重修复**。本轮照搬其结构在我们问题上做一次：
- **重修复**：destroy 后用 regret + **2-opt×k 局部搜索(`local_search.py`)** + **FRVCP 充电插入** 的强修复（与对照组同口径共享）。
- **AI 编排**：DQN/PPO 每 `iter_per_action` 步选 destroy/repair/charging 组合（macro-action，非每步重选）。
- **reward**：5/3/1/0 − 停滞惩罚（Cao 口径）。
- **训练**：在长搜索轨迹内 replay 训练(Cao 式) 或 我们的 episodic，但**重修复一致**、练够、POMO baseline、target-KL。

## C2. 判级（诚实，定论）
**关键对照**：DR 编排重修复 vs **AlphaUCB/随机编排同一套重修复**（隔离"AI 编排"本身的增量）。同预算同 worker。
- `DR_REAL_GAIN`：DR 编排显著超 AlphaUCB 编排(如 ≥+5%)、零违约稳定 → DR 有真增量(罕见，若出现则大新闻)。
- `DR_CLOSED`：DR 编排 ≈ AlphaUCB 编排(±2%内) → **彻底定论**：即便按已发表做法(重修复+编排)，AI 编排对调好的 ALNS 也无实质增量 → 静态 DR 正式 future-work，第一手复刻坐实。

---

## 2. 执行顺序 + 总判级
**先 A 后 C**。A 是论文命根、必须做到底(基线修活)；C 是给 DR 的最终定论。最终 `final_attempt_report.md` 人话汇总：①公平后方法领先弱场的**真数字**、是否到 10%、基线是否全活；②winner kernel/普通 ALNS 哪个是方法、是否胜 plain；③DR 按已发表做法的最终增量(有/无)、DR 去留定论；④下一步。

## 3. 资料顺序
先读 HANDOFF + Track15 报告/`trackA_rows.csv`(基线坏在哪) + `metaheuristic_baselines.py`(PSO decode) + `winner_operators.py`/`local_search.py`/`charging.py`(强招式) + Cao `ALNS.py`(重修复+编排做法)。先证据、单点改、带闸、不拿坏基线/欠训当赢、不谄媚。
