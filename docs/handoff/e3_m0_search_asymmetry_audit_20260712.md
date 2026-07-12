# E3 M0 独立基准搜索不对称审计（封存前最后审查发现）

日期：2026-07-12
作者：Claude（只读代码与冻结产物审计，未运行/未修改任何代码）
状态：**待用户拍板**。本发现在 E3 v2 开跑前提出——跑前修正设计是预注册补丁，跑后再改就是"改定义救结果"（总设计明令禁止）。

## 一句话结论

E3 阶梯的地基 M0（独立经营基准）在搜索阶段实际上是"车队无上限"，而协同臂（M1--M5）从 M0 解热启动且开新 EV 路由的门被堵死；旧 E3 正式跑中 **5 个种子里 4 个的 M1 路由结构与 M0 逐位相同**（协同层对路由零操作）。总设计骨架 1 要求新跑与旧 runner"逐字一致"，只解锁了跨场费（95→0），没有触及这条结构链。若 fee=0 仍不足以让协同活起来，零效应可能是搜索假象而非机制真相，且当前设计无法区分这两者。

## 事实链（全部代码级坐实）

### A. M0 子算例没有车队上限

- `solver/src/setp_solver/search/fairness.py:313` `_subinstance_for_depot` 构造子算例只传 `nodes` 和 `distance_matrix`；`Instance.num_cv/num_ev` 默认 `None`（`instance_loader.py:38`）。
- `fairness.py:328` `_write_subbundle` 写出的 `instance.json`/`scenario_manifest.json` 均无 `num_cv/num_ev` 字段。
- 加载兜底 `infer_fleet_limits`（`support/fleet.py:108`）在子包目录找不到任何上限来源 → 回退 `UNBOUNDED_FLEET`。
- 结果：M0 每场子搜索的 `SearchPolicy.max_cv/max_ev = 无限`（`kernel/winner.py:2042-2055`）。

### B. 终局"打包"是纯改标签，安全网是死代码

- `support/fleet.py:58` `normalize_solution_vehicle_trips` 把第 pos 条路由 round-robin 分给 `slots[pos % cap]`，**不检查同一物理车两趟的时间衔接**。
- 它只在 cap≤0 或路由 id 冲突时抛错；M0 runner 里的 `HALT_M0_PACKING` 捕获（`m1_e3_cumulative_ablation_runner.py:209-217`）实际永远不会因"车太多"触发。
- 检查器 `check.py:_check_vehicle_count` 只数物理前缀（`EV5#T2` → `EV5`）是否 ≤ cap；全项目没有跨趟时间重叠校验。骨架 1 审计包第 1 项只查**充电**区间重叠，不查**行驶**区间。
- 含义：车队硬上限在全管线的实际语义 =「物理车号数 ≤ cap（靠改标签必然满足）」。这是 06-26 硬上限恢复后为解决全线 INIT_INFEASIBLE 引入的多趟语义的遗留面。

### C. 协同臂被锚死在 M0 解上

- `m1_e3_cumulative_ablation_runner.py:229,240`：M1--M5 全部以 M0 打包解为 `initial_solution`。
- 开新路由的门 `operators/feasible_repair.py:319-330` 数的是**原始路由条数**（趟数），不是物理车数：M0 解有 65--73 趟 ≥ 14 → **EV 侧开新路由永久被堵**（CV 侧 3--6 条 < 14 有余量）。
- 叠加已知的 07-10 根因（AlphaUCB 调度锁死，五种子零次车型切换；修复选项 `BALANCED_SELECTOR_FLAG` 等在 `winner.py:177-181` 标注 "Diagnostic only"，正式路径默认不开）。

### D. 冻结产物实证（`baselines/e3_ablation/e3_submission_20260711/formal/`）

- 5 种子 M0 全 OK；终解 EV 恰好压满 14、单车最多 5 趟（65--73 趟折叠而来）。
- **路由结构签名：seed1/2/3/5 的 M1 与 M0 完全相同**（`route_structure_signature` 逐位一致）；成本 Δ 分别为 -0.03%/-0.02%/-0.00%/+0.00%。只有 seed4（M0 恰好最差，10293）出现真重构：M1 -5.16%、跨场 2 客户（顶着 95 镑费用）。
- 跨场客户数几乎全 0（fee=95 锁，已由拍板①解决）。
- 解读：旧收口"协同成本 4 胜 1 平"中的 4 胜是充电/计时层面的化妆差异，路由层面协同为零操作。M1−M0 差值目前测的更像"M0 恰好有多差"，不是"协同值多少"。

## 对 E3 之外的传导

- **E6**：Stage A 的 r0 与独立基准收益复用 E3 的 M4/M0 行——M0 若带搜索假象，公平网格的锚点跟着漂。
- **E7**：B3 臂 = "M0 语义的动态版"；逐阶段公平基准按"M0 同法"重算——同一套无上限子包语义会逐阶段复制。至少是**一致**的（基准全程同口径），但须在论文里如实交代。
- **审稿风险**：「独立基准与协同臂的搜索自由度不同」是一句话就能提出的质疑；目前论文与设计文档都没有披露句。

## 为什么不能"顺手修"

- 给子包塞 `num_cv/num_ev` ⇒ 开新路由门按趟数生效 ⇒ 每场 14 趟造不出 ~225 客户的解 ⇒ M0 构造期直接死。06-26 的 warm-start 探针（全实例 `Initial solution is infeasible`）已经证明过这条死路。
- 把门的语义改成数物理车 ⇒ 改动冻结搜索内核 ⇒ E2 封存一致性被破坏，全部机制实验的"冻结 hybrid"口径失效。**绝对不要走这条路。**

## 处置选项（待拍板）

**选项一（推荐，零模型改动、约 5 次额外搜索）**：设计骨架 1 增补两条预注册诊断——
1. 每种子报告 M1 vs M0 的 `route_structure_signature` 是否相同 + 跨场客户数（零成本，字段已有）；
2. 加 5 次"无锚定 M1"对照探针：M1 口径但不从 M0 热启动、用与 M0 子搜索同源的新鲜构造 + 同预算 4000。若 fee=0 后主梯协同已活，探针只是稳健性注脚；若主梯仍平而探针能动，则拿到"零效应=锚定假象"的因果证据，降级话术升级为有据的机制讨论；若两者都平，降级话术照写且免疫审稿质疑。
3. 审计包第 1 项扩展：跨趟重叠检查从"充电区间"扩到"行驶+充电区间"（零搜索，从保存解重建排程），把 B 的检查器盲区一并交代。
4. 论文加一句披露：M0 子问题搜索阶段车队上限松弛、终解经车次归并满足物理车数上限；多趟语义为"物理车数上限+车次标签归并"，跨趟时间衔接由审计报告核验。

**选项二（不推荐现在做）**：把阶梯语义改成对称口径（全臂无锚定或全臂同起点重定义）。属实验定义变更，需重新论证 + 全量重跑，威胁 7/31。

**选项三（什么都不做）**：接受预注册降级话术。风险=零效应无法归因 + 审稿人不对称质疑无披露句。

## 证据定位速查

| 事实 | 位置 |
|---|---|
| 子算例构造无上限 | `solver/src/setp_solver/search/fairness.py:313-352` |
| Instance 默认 None | `solver/src/setp_solver/instance_loader.py:38` |
| 兜底找不到上限 | `solver/src/setp_solver/algorithms/resetp_alns/support/fleet.py:143-172` |
| 打包=改标签、无时间检查 | `support/fleet.py:58-105,131-141` |
| 检查器只数前缀 | `solver/src/setp_solver/check.py:269-299` |
| 开新路由门数趟数 | `operators/feasible_repair.py:316-338` |
| M0 无上限跑+打包 | `baselines/e3_ablation/m1_e3_cumulative_ablation_runner.py:177-218` |
| 协同臂热启动 M0 | 同上 `:221-254` |
| 调度修复默认不开 | `kernel/winner.py:177-181` |
| 实证（签名/成本/趟数） | `baselines/e3_ablation/e3_submission_20260711/formal/raw_runs.csv`、`solutions/` |
| 固定成本按趟计（打包不改成本） | `solver/src/setp_solver/cost.py:120-125` |
| 多趟语义由来 | `docs/handoff/fleet_hard_cap_multidepot_evidence_20260626.md` |
| 调度锁死根因 | `docs/handoff/m1_independent_root_cause_20260710.md` |
