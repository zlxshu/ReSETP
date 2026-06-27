# 09v — 高碳张力 regime 下 ALNS vs LNS 分离性探针（PROBE，非正式 T3）

日期：2026-06-27　提出：Claude（战略）　执行：Codex　决策权：用户

---

## 0. 先读（开工前必须做，否则禁止动手）

1. 完整读 `HANDOFF.md`（单一事实源）+ `docs/handoff/memory/`（记忆快照）。
2. 读 `CLAUDE-FABLE-5.md` / `AGENTS.md` 里的诚实/克制/反迎合原则（忽略其中 Claude 产品细节）。
3. 读这两份本周复盘，吃透"上一程为什么失败"，别再犯同样的错：
   - `docs/handoff/codex_prompts/ALGORITHM_COMPARISON_FULL_RETROSPECTIVE_20260627.md`
   - `docs/handoff/codex_prompts/FEEDBACK_codex_claude_workflow_retrospective_20260627.md`

**行为铁律（这条任务尤其要守）：**
- 禁改 `cost.py` / `check.py` / `evaluation.py` 语义和算法语义；禁改 `prices.py` 默认值；禁改 TeX。
- 碳价**全程钉死** `carbon_price=0.05034`，**绝不**当调参旋钮。
- 电池只用**内存** `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=x)` 覆盖，且 x 只能取**有真实来源**的值（见下），不许等距网格/插值。
- 系统 Python（`/opt/anaconda3/bin/python3.13`，numpy 2.3.5），`PYTHONHASHSEED=0`；数字绑 commit hash。
- **这是 PROBE，不是正式 T3。** 任何结果都不许写成"算法正式胜负"。smoke/Stage A/probe 一律标清证据层级。
- 报告**人话先行**：先写"这步在干什么、结论的人话含义"，再放内部标签（`HALT_*`/`winner`/`gap` 等）。报告**开头第一段必须复述本步服务的目标**（见 §1）。
- 拿不准、提示词有矛盾、或采集没闭合 → **停下来诚实 HALT 报告**，不要把没跑满的结果凑成结论，不要自行把诊断线索推进成默认参数或论文结论。

---

## 1. 这一步服务的目标（一句话，报告开头要复述）

**验证一个结构性假设：ALNS 之所以在 Goeke80 上只和 LNS 打平，是因为那个 regime 里 EV≈6%、几乎没有充电/碳决策可供它的"碳感知/EV 感知"算子发挥；只要换到机制真正"咬合"的 regime（更高续航 → 更多 EV 路线 + 更多充电调度），ALNS 对 LNS 的优势应当显现。**

这一步**不是**为了"逼出混合车队"，也**不是**为了挑一个能让 ALNS 赢的电池值。它是把"电池档"当 x 轴、把"ALNS−LNS 配对差"当 y 轴，**画出"机制活跃度 ↑ 时，ALNS 是否拉开 LNS"这条曲线**。这条曲线同时回答论文两个卡点：故事在哪有意思、算法在哪能赢。

---

## 2. 背景（自包含，冷启动也能懂）

- E2 算法对比的硬指标：ALNS（含 DR-ALNS）必须**打过**主流基线（LNS/GLNS/GA-VNS/GA/PSO…），不只赢 SA。
- 最新事实（09u，`baselines/e2_alns/wallclock_battery_preflight_wallclock_retry.md`）：在 Goeke80（`Q=3650,B=80,v=25,carbon=0.05034`，实体车多趟语义）下，等墙钟比较，23 个 -01 算例里 **ALNS 2 胜 / LNS 1 胜 / 20 平**，75-200c winner 的 EV route share 仅约 **5.7%**。100kWh 同样没改变。
- 关键观察：**20/23 打平 = 两个算法都摸到了几乎同一个近最优解**。在一个几乎没有 EV、没有充电调度的算例上，碳/EV 感知的 ALNS 武器全用不上，所以它和什么都不懂的纯路由 LNS 打平。**这是"战场选错"，不一定是"ALNS 弱"**——证据：在原始 canonical 算例 100-01 上 winner kernel 碾 fair-SA 8.76pp、L-main 近最优（见 `HANDOFF.md` §1）。
- 09h 已有线索：在 280kWh、三班 100/150/200c 上，mixed/EV 真实重优化能压过 all-CV（200c gap≈-4%）。当时把 280kWh 判"失败"只是因为它没满足"20-80% 混合"这个**假门槛**——而那个门槛本就不是论文贡献。
- 因此本探针撤掉"20-80% 混合"门槛，改问一个更本质的问题（见 §1）。

---

## 3. 复用现成代码（不要重造）

主体复用 `baselines/e2_alns/wallclock_battery_preflight.py`（上一程已修好硬超时从可读 checkpoint 闭合，commit `793ab399`）。它已经具备：
- `ALGORITHMS = ("alns_e2_throughput", "LNS")`，并在 `by_pair` 里做好 ALNS vs LNS 配对（wins/ties/losses + mean gap% + EV route share）。
- `SCENARIOS` 字典（每档 `{battery_kwh, mode, eval_budget, label}`，mode 支持 `wallclock`），`apply_battery_override()` 做内存电池覆盖。
- 等墙钟帽 `runtime_cap(size)`：小算例 300s / 50c 600s / 75-200c 900s，可用 `--cap-scale`/`--max-cap-seconds` 调。
- 实例选择 `select_instances("gradient01")` = vanilla/multidepot 10-200c + threeshift 50-200c 的 -01 梯度；`--seeds` 控制种子。
- winner 指标已含 `winner_ev_route_share` / `ev_route_count` / `ev_physical_vehicle_count`。

**需要新增（都是小改动）：**
1. 在 `SCENARIOS` 增加两档高续航 wallclock 场景（**只用来源值**）：`wc150`（`battery_kwh=150.0`）、`wc280`（`battery_kwh=280.0`）。连同已有 `wc80`/`wc100`，构成 **80 → 100 → 150 → 280** 的"机制活跃度阶梯"（150/280 均在 09l 来源候选清单内：…113/123.9/140/141/150/176/180/194/200/210/240/280…）。`carbon_price` 全程保持 0.05034 不动。
2. 每行额外记录一个充电活跃度代理：`charging_action_count = len(solution.charging_actions)`（机制是否"咬合"= EV 用得多 **且** 充电调度真在发生）。
3. 新增一个**电池档 × ALNS-LNS 分离性**汇总（见 §5）和**预注册判决**（见 §6），写进报告。

新建独立报告/数据目录，**不要覆盖** 09u 的产物：
- runner 可直接扩展 `wallclock_battery_preflight.py`，但输出指向新目录，例如 `baselines/e2_alns/high_tension_separation_probe_data/` 与报告 `baselines/e2_alns/high_tension_separation_probe.md`。

---

## 4. 执行步骤

**Phase 0（必做核验）**：确认当前默认仍是 `Q=3650, B=80, v=25, carbon=0.05034`、numpy 2.3.5、worker=系统 py313；确认 09s warm start 69/69 仍 OK；确认内存电池覆盖能穿透 `evaluate/check/charging/run_alns_wouda`（沿用 runner 已有的 override audit）。Phase0 不过就 HALT。

**Stage A（便宜趋势，先只 seed1）**：4 档电池（wc80/wc100/wc150/wc280）× `gradient01`（-01 梯度）× **seed1** × {alns_e2_throughput, LNS}，等墙钟帽。要求 **0 采集失败**（每行返回零违约 incumbent），否则按规则 `HALT_COLLECTION_COST`、不下结论。

**Stage B（条件触发，仅当 Stage A 见到信号）**：把 seeds 扩到 **1-3**，但**只在 75-200c 子集**（高规模才是机制咬合处，省算力）。Stage A 若完全没信号，**不要**自动跑 Stage B，直接进 §6 判决。

每档电池产出：ALNS vs LNS 的 wins/ties/losses、mean gap%（gap = (alns_obj − lns_obj)/lns_obj×100，**负 = ALNS 更优**）、scipy Wilcoxon p、mean EV route share、mean charging_action_count。

---

## 5. 核心汇总（报告必须有这张表）

| 电池档(来源) | mean EV route share (75-200) | mean charging actions | ALNS胜/平/负 | mean gap% (ALNS−LNS) | Wilcoxon p |
|---|---:|---:|---|---:|---:|
| 80 (Goeke 旧锚) | … | … | … | … | … |
| 100 (边界) | … | … | … | … | … |
| 150 (来源车型) | … | … | … | … | … |
| 280 (现代卡车) | … | … | … | … | … |

读法（人话）：从上往下，EV/充电活跃度升高时，**ALNS 的 gap 是否变得更负、胜场是否变多、p 是否变显著**？

---

## 6. 预注册判决规则（开跑前就定死，防止又把问题重新打开）

- **PASS_MECHANISM_SEPARATION**：存在至少一个高活跃度档（EV share 明显高于 80kWh 那档、且充电在发生），ALNS 对 LNS 出现**清晰且统计支持**的优势——Wilcoxon `p<0.05` **且** 在有区分的配对里 ALNS 胜场占多数，且 gap 明显比 Goeke80 那档更偏向 ALNS。
  - 含义：机制感知搜索确实在"机制咬合处"拉开了通用搜索。**下一步**（另起提示词）：把该 regime 正式化为论文场景，并在那里跑正式 T3（含 8 文献基线）。
- **INCONCLUSIVE / FAIL_NO_SEPARATION**：跨**所有**电池档（包括 EV 高、充电多的档），ALNS 始终与 LNS 打平或落后。
  - 含义：vanilla ALNS 的机制感知**不带来搜索优势**；论文的算法创新必须落在 **DR-ALNS**（离线探针已 PROMISING）。这是干净、诚实的岔路，**到此停止用电池/regime 调算法**，不要再试更多电池值。
- **重要 caveat（必须写进报告，防误读）**：若某档电池在多数算例上**退化为 all-CV 或 all-EV**（EV share≈0 或≈1），则该档"张力低"与电池无关——**该档打平不算证伪假设**。假设说的是"被真实争夺的 regime（EV 适中 + 充电绑定）"，不是"EV 越多越好"。判决以"张力真实存在的档"为准。

无论哪种结果：**这是 PROBE，不是正式 T3**，报告标题与结论都要标清。

---

## 7. 验收

- Phase0 OK；Stage A 4×gradient01×seed1 全行零违约闭合（或诚实 HALT_COLLECTION_COST 并说明卡在哪个算例/算法/墙钟）。
- §5 汇总表完整；§6 判决明确给出 PASS / INCONCLUSIVE 之一，并附 caveat 解读。
- 回归测试：`solver/tests/test_cost.py solver/tests/test_check.py solver/tests/test_search.py solver/tests/test_e2_alns_throughput.py -q` 全过。
- 产物 commit；报告记 HEAD 与 artifact hash。
- HANDOFF `变更日志`追加一行 `[M1]`：本探针目标、判决、下一步。

## 8. 不要做的事
- 不要为了出 PASS 去试清单外/无来源的电池值，或动碳价、油价、电价。
- 不要把任一 smoke/Stage A 行写成"ALNS 正式赢 LNS"。
- 不要在 Stage A 没信号时硬跑 Stage B 烧算力。
- 不要改默认参数 / TeX / 保护文件；不要新增模型约束。
- 不要用术语堆报告；先人话，后标签。
