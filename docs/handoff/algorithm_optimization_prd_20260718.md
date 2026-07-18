# 算法优化 PRD：群体化 ALNS（碳/EV 感知 HGS）

- 编号：ALGO-OPT-PRD-001
- 日期：2026-07-18
- 状态：`APPROVED_ISOLATED_MECHANISM_HGS_ALNS_DEVELOPMENT_ONLY`（2026-07-18；允许来源补齐、独立目录组合实现、预算0/1/2/5行为门与少量非正式开发题三方比较；正式搜索仍为`formal_search_allowed=false`）
- 目标读者：Codex、任何接手 ReSETP 算法线的代理（冷启动可读，自包含）
- 关联：`docs/handoff/e2_alns_g1_stage1_closeout_20260718.md`、`docs/handoff/alns_mechanism_innovation_exploration_contract_20260718.md`、`docs/handoff/model_change_approval_register_20260718.md`、`docs/handoff/algorithm_exploration_20260718/fleet_charging/`、memory `baseline-algorithm-catalog`

---

## 2026-07-18 执行校正

用户批准“先走B，强烈向好则走A”。固定官方`vidalt/HGS-CVRP`提交`1a927955cd2861a29d978f0d359d6e647db9319c`在三个非冻结CVRP开发题、三种子、每次3秒的结果盲门中达到`GO_A_ENGINEERING_DISCOVERY`；随后本机固定安装、官方5项测试、Python到原生C++的严格CLI桥及独立可行性/距离复算均通过。

这只证明官方CVRP搜索引擎值得作为结构参考和隔离工程底座，不等于本PRD Phase 0完成。官方HGS-CVRP没有硬时间窗、异质车队、SOC、非线性充电、分时价格、碳、公平和多车场语义，不能冒充Solomon/Homberger VRPTW或完整ReSETP求解器。后续任何VRPTW/HGS式自研、EV-aware Split、ALNS education合入、正式测试集或E2--E7重跑仍须单独预注册与批准。

---

## 0. 一句话

当前"改进版 ALNS"在单解框架内的小修补已**连续碰壁**（十余个算子几乎全部蒸发；赢家内核与 LNS 同源），边际递减明显——这**不等于"已到理论天花板"**，但足以说明再在单解框架内叠算子性价比很低。一条**有依据、但尚未证明**的方向，是引入群体 + Split（HGS 类结构），把现有 ALNS 作为 education 内核。它**不是唯一可选方向**（路线池 + 集合划分、受控路线消除 + 有限深度 ejection chain 等同样有依据），只是当前**外部证据与项目内信号最集中**的一条。本 PRD 规定该方向的目标、架构、文献依据、分阶段过门、验收、风险、影响矩阵与治理边界；**成功预期一律按证据校准，不预设称霸**。

---

## 1. 文档定位、范围与治理边界

### 1.1 是什么
- 这是**算法内核**的优化规格，只管求解器性能与算法创新，不改建模、不改场景、不改统计终点。
- 它是提案层文档：定义"要造什么、凭什么、怎么分阶段验证、什么条件下叫成功、什么条件下叫失败要收手"。

### 1.2 不是什么
- 不是启动令。未获用户逐项批准前，任何阶段不得实施。
- 不是模型/单位/参数变更审批。凡触及 SOC、非线性充电曲线、成本口径、目标函数、可行性定义者，一律另走 `model_change_approval_register_20260718.md` 的八步审批。
- 不是把公开 VRPTW 成绩等同于机制有效性的通道（见 §7.4）。

### 1.3 绝对保护边界（未获明确批准不得改）
- `solver/src/setp_solver/cost.py`、`check.py`、`search/evaluation.py`、`prices.py` 默认值、TeX 参数表。
- 已冻结证据：E2 封存 tag `e2-submission-20260711`、E3/E4/E6/E7 已封存目录、`Reference Algorithm/ALNS-7.0.0@N-Wouda`。
- 冻结结果不得被新算法暗改；算法版本变化必须走 §10 影响矩阵重跑，而不是覆盖旧证据。

### 1.4 诚实纪律
- 不得把 `HOLD_*`、`WEAK`、`PARTIAL`、单预算侥幸结果包装成胜利。
- M1(ARM) 与 x86 绝对数字不可跨机比较；正式数字以 M1 为唯一基准。
- 预算必须按 §8 分账，杜绝"local search 偷烧评价"类假象（历史实测偷烧 ~13.8 倍）。

---

## 2. 背景：为什么单解 ALNS 的小修补连续碰壁（证据）

四条证据共同说明：**在单解 ALNS 框架内继续叠算子，边际收益已很低。**（这是"小修补连续碰壁"，不是"理论到顶"——受控路线消除、路线池等理论上仍可能改善，只是历史上都未过门。）

1. **赢家 ALNS ≡ LNS 引擎**。当前赢家（staged hybrid / TVCI-ALNS）的强中段调用 `_apply_strong_alns_destroy_repair`（`winner.py:596`），与 LNS 基线调用的（`metaheuristic_baselines.py:1758`）是**同一函数**。"让 ALNS 赢 LNS"≈"让一个东西赢它自己"。
2. **残差分差是一个 £80 的离散台阶**。`cost.py:125` 的 `cost_fix = 路线数 × vehicle_fixed_cost(80.0)`；硬子集上 ALNS 对 LNS 的全部分差 ≈ `0.3125 路线 × £80 ≈ 25`，几乎等于总分差 `23.77`。算法不是"路排得差"才输，是偶尔"少删一条路线"才输；而增量邻域（relocate/swap/2-opt/SWAP*）在固定路线数内挪客户，结构上删不动路线。
3. **headroom 存在、可行、且只在"客户顺序空间"可达**。`route_packing_reachability_audit_20260708`：解码出 105 个更少路线的候选，**0 个不可行**；且是靠"固定成本感知的客户顺序解码"够到的。
4. **A11 顺序重排是唯一真赢过 LNS 的机制，但被埋没**。`global_repack_fleet_charge_probe_20260707`：A11 在正式 4000 预算下对 LNS **25 胜 16 负**、路线/固定成本缺口砍 60%、平均 gap +0.70%、过全部门；但 8000 衰减（临时贪心解码器是天花板），且其好结果产在 07-09 架构拨正前，当前默认关闭（`winner.py` 三个正式配置 `GLOBAL_ORDER_REPACK=0`）。

**结论（方向性，非定论）**：病灶=车队规模（41% 成本）的离散台阶；**最可能的**钥匙=顺序空间的最优切分（Split）+ 多样性来源（群体）。这是当前证据最支持的一条**假设**，**不是唯一路**——路线池 + 集合划分、受控路线消除 + 有限深度 ejection chain 是同级候选；选它，只因外部证据与项目内 A11 信号目前集中在 Split/群体这一条，而非它已被证明胜出。

---

## 3. 目标、非目标与成功判据

### 3.1 目标
1. **公开 benchmark 通用求解能力达到有竞争力/接近强方法**：在标准 VRPTW（Solomon/Homberger）上逼近已发布 BKS、与强参照差距可控；EVRP-NL 类公开集上对照文献强方法不明显落后。**不预设"称霸"**——公开 CVRP 上 HGS 引擎强是已知事实，但能否迁移到本模型（时间窗/EV/充电/多车场/碳/公平）尚未证明。
2. **自有中国实例上稳健领先**：把当前对 LNS 的 ~15 个配对负例转正，取得逐网统计显著（Wilcoxon+Holm，对齐 MC-002 原则）。
3. **算法创新可解释**：每个机制专用算子有干净消融，能一句话说清它凭什么起作用（陈雨蝶式机制内化）。

### 3.2 非目标
- 不追求用通用 solver（如直接拿 PyVRP）报成绩替代自研算法。PyVRP 仅作参照/外部基线。
- 不把公开 VRPTW 成绩写成"复杂补能机制有效"的证据。
- 不为制造混合车队/删负例而改惩罚、改车队比例、筛结果。

### 3.3 成功判据（预注册，见各阶段 §6 细化）
- **双赢硬门**：组合算法在相同开发题、配对种子、相同完整方案评价次数和同一最终复算器下，必须同时优于纯HGS与纯ALNS；只赢一个、靠额外算力取胜或墙钟失控均不通过。
- **通用能力门**：最小 HGS 在 Solomon 代表子集上，车辆数命中 BKS 的实例比例 ≥ 预注册阈值，且距离 gap ≤ 预注册阈值。
- **自有实例门**：Population/Memetic TVCI-ALNS 在同起点、同完整评价预算、配对种子下，对 LNS 与当前赢家均**总成本不劣且逐网显著**；EV-aware Split 开/关消融**改变路线数**。
- **可解释门**：至少三个机制算子（Split / SWAP* / 充电或公平算子）各自给出方向一致、可复算的消融证据。

### 3.4 失败/收手判据（同样预注册，防止白努力）
- Phase 0：最小 HGS 连 Solomon 代表子集的 BKS 都逼不近（超出预注册 gap 上限），或整合层反复不可行 → **判 `HGS_ENGINE_NOT_SUPPORTED`，整体收手**，回落"有竞争力但不称霸"+机制故事。
- Phase 1：EV-aware Split 在开发集上既不降路线数也不降成本 → 停 Split 分支，只保留通用 HGS 收益，不硬推机制算子当性能来源。
- 任何阶段出现同值同质化、identity 簇、under-eval、保护文件漂移 → 立即 HALT，不得续跑。

---

## 4. 算法架构：Population/Memetic TVCI-ALNS

### 4.1 解表达
- **giant tour（无路线分隔的客户顺序）+ Split 解码**为核心表达；同时保留现有 `Solution{routes, charging_actions, cross_site_services}` 作为评价/检查的落地结构。
- Split 负责"顺序 → 若干条路线"的最优切分，天然处理"每条路线 £80 固定成本"这一离散项。

### 4.2 四件套（标注已有/新建）

| 组件 | 作用 | 状态 | 权威源 |
|---|---|---|---|
| 群体 + 多样性管理 | 可行/不可行双池；biased fitness = 成本贡献 × 多样性贡献；周期性幸存者选择 | **新** | Vidal 2012/2022；PyVRP 参照 |
| **EV-aware Split** ⭐ | 顺序→DP 最优切分；切分时**联合定价 CV/EV 车型 + 非线性充电**；分层筛选后仅对 top-B 段调精确充电预言机 | 种子=A11(已验)；预言机=frvcpy(**已核 Apache-2.0**) | Prins 2004；Froger 2019；Wang 2025 |
| 交叉算子 | SREX/OX/边重组；**尊重多车场责任结构** | **新** | Vidal 2012；Wang 2025 |
| Education（现有 ALNS 内核） | 强化：true SWAP* + 粒度 relocate/2-opt + 机制算子（碳择时重排/公平赤字修复） | **大部分已有**（SWAP* 阶段一、carbon-aware 已有；公平赤字待建） | Vidal 2022 SWAP*；Hiermann 2016；Soriano 2023 |

⭐ **EV-aware Split 是本方向最有希望的候选算子，但不是已证的胜负手**：它同时是自研精细性能算子（对应 Wang 逐车型路线评价）和陈雨蝶式机制内化算子（把碳/车型/充电焊进切分），**思路上**能修 A11 的 8000 衰减病根（临时贪心 → 最优 DP）。

**Split 适配的诚实风险（须正视）**：经典 Split 只在"给定顺序、单一同质车、简单可加路线成本"下才是最优 DP。本模型的多车场、车型选择、SOC 连续演化、非线性充电、跨趟实体车和公平约束都会破坏 Split 的可加性假设——把它们塞进 Split **不是套用现成算法，而是重新设计一个可能昂贵的新子算法**（最坏含指数级 FRVCP），其收益未证。因此它是"值得先隔离验证的自研候选"，**不能当"已知有效的现成件"**。

### 4.3 身份保留说明与身份风险
拟让 ALNS 成为 HGS 的 education（intensification）内核；对外名称 `Population/Memetic TVCI-ALNS`，保留 `staged_hybrid_carbon_aware` 兼容标识护旧证据。定位是"面向本模型机制专门化的 HGS"，不是"全新基础 ALNS"，也不是"通用 HGS"。

**身份风险（须正视，不回避）**：若性能增量主要来自群体 + Split + 交叉、而非 ALNS 内核，则论文主算法**事实上会变成"HGS（内嵌 ALNS 局部搜索）"，不再是你想要的"改进版 ALNS"**。四臂消融（纯 ALNS / 直接强重组 / 群体化 / 群体化 + 机制算子）必须能定位增量来源；若增量几乎全来自群体 + Split，应诚实按 HGS 变体署名，或据此重新决定是否走这条路——**不得用"education 内核"的措辞把 HGS 包装成 ALNS**。

### 4.4 Phase-2 加速器（可选，冲 BKS 最后几个点）
精英路线池 + 集合划分（set-partitioning）重组，Wang 2025 靠它刷 65 个新 BKS。诚实边界：仓库早期"静态小池 SP=0/6 headroom"是**小池**结论；HGS 大精英池是不同 regime，值得在 Phase-2 单独验证，不得据旧小池结论提前否决，也不得据文献提前宣称有效。

---

## 5. 文献与证据依据映射（"不拍脑袋"的核心）

| 主张 | 依据类型 | 具体出处 |
|---|---|---|
| 病灶=车队规模离散台阶 | 仓库硬证据 | `cost.py:125`；hard-subset 分账 |
| headroom 只在顺序空间可达 | 仓库硬证据 | `route_packing_reachability_audit_20260708`（105 解码 0 不可行）|
| 顺序空间能压路线数 | 仓库实测 | A11 `global_repack_fleet_charge_probe_20260707`（4000 胜 LNS）|
| Split 是最优切分的权威方法 | 文献 | Prins 2004（route-first cluster-second + DP split）|
| HGS 是 VRP benchmark 冠军范式 | 文献 | Vidal 2012（HGS）；Vidal 2022（HGS-CVRP + SWAP*）；PyVRP/DIMACS |
| VRPTW benchmark 车辆数优先计分，正对车队病灶 | 公开评测惯例 | Solomon/Gehring-Homberger 计分：先最小化车辆数再距离 |
| 固定路线充电可独立增值 | 文献 | Froger 2019（只重优化充电改进 120 个 EVRP 最优解中 23 个）；Kullman 2021 frvcpy |
| 车型—路线联动算子 | 文献 | Hiermann 2016（Resize / RelocateAndResize）|
| 逐车型路线评价 + 路线池 + SP | 文献 | Wang 2025 HEVRP-NL（65 新 BKS）|
| 公平修正插入偏向未达标车场 | 文献 | Soriano 2023 |
| 异构车队工程与增量评价参照 | 开源 | PyVRP（MIT，已锁提交）|

**必须补进 Zotero**（当前库缺，是 A 轨地基）：Prins 2004；Vidal 2012 HGS；Vidal 2022 SWAP*。已在库/已核：Hiermann 2016、Froger 2019、Kullman 2021(frvcpy)、Wang 2025、Wouda 2024(PyVRP)、陈雨蝶 2025（目标期刊母版）。

---

## 6. 分阶段开发计划（每阶段：范围 / 交付 / 过门 / 收手）

总原则：**公开 benchmark 先行去风险；不改模型语义的先做；跨模型边界的走审批；证据不足不进下一阶段。**

### 6.0 当前实际批准范围（用户 2026-07-18 选 B）—— 优先于以下 Phase 草案
用户批准的是**最小侦察**，不是直接建完整 HGS。侦察只回答两问：
- **B-(a) 强 HGS 参照是否明显优于当前算法**：**已完成**。官方 `vidalt/HGS-CVRP` 桥接在 3 个 CVRP 开发题上对当前 ALNS 中位改善 11.22%/12.16%/12.74%，2/3 题少用路线（13v14、13v15、8v8），判 `GO_A_ENGINEERING_DISCOVERY`。**诚实边界**：这是**纯 CVRP**，而当前 ALNS 为本模型（碳/EV/多车场）专门化、跑纯 CVRP 属**出设计域**，故 11–12% 幅度**被放大、不能 1:1 迁移到本模型**；且这是整台 HGS，**未隔离 Split**。它只证明"HGS 搜索机器值得作结构参考 + 隔离工程底座"，不证明本 PRD 的组合会赢。
- **B-(b) 经典 Split 单独是否真能减少路线**：**未做**。这是下一步最便宜、最能验证本 PRD 核心论点（"headroom 在顺序空间、Split 是钥匙"）的隔离探针。
**下列 Phase 0–2 均为草案、均未批准**；其中"建最小 HGS（群体 + 交叉 + Split + 多样性）"**并不便宜**，是 B 通过后另行审批的工程阶段，不属于 B。

### 6.0A 用户追加批准：机制化组合的隔离开发

在官方HGS桥出现强阳性后，用户进一步批准“把ALNS装进HGS”，并要求形成“每个机制一个算法”的可解释故事。该批准只放行独立目录中的最小组合开发、四个机制原型接线、预算0/1/2/5行为门和少量非正式开发题三方比较，不放行任何正式算例或下一阶段。

开发身份固定为：HGS式外层负责保留和重组多个不同方案；现有ReSETP ALNS作为内层精修器；车型补能、公平、碳价冲突和动态订单分别由独立可开关动作处理。HGS框架不是创新点。若机制动作无实际触发、无独立增益，或组合收益只来自通用群体管理，必须收回“陈雨蝶式机制创新”的叙事。

三方停止线固定为：同题、同种子、同完整评价次数、同最终复算器下，组合必须同时胜纯HGS和纯ALNS，并报告墙钟及内部调用账。未双赢则回到设计层，不进入正式试验；出现强阳性也只向用户申请正式试验批准，不自动升级。

### 6.0B 最低成本骨架门实测结论

隔离骨架已完成预算0/1/2/5计数门。25客户三结构×三种子×B100的通用组合仅6/9同时胜纯HGS式外层与纯ALNS，未过用户硬门。多起点教育从6/9降为3/9，已停止，不再调比例。

用户提出“多车场才开启”后，开发了不读取结果的显式合同开关：仅在至少两个车场、场景合同标明`multidepot`且无多班次标记时启用，否则精确退回纯ALNS。25客户小门达到启用3/3双赢、禁用6/6零漂；但10/15/20/25/50客户放大门仅4/15双赢，其中20和50客户中位退步5.97%和6.22%，只有25客户中位改善7.58%。因此当前判`HOLD_MULTIDEPOT_SWITCH`。按“25客户”再设阈值属于结果后拟合，禁止采用。

后续不再优化通用外壳或开关阈值。只有车型补能、公平、碳价冲突和动态冻结四个动作分别在自己的病灶开发门取得独立增益，才允许重新组合；正式搜索继续禁止。

### Phase 0（草案，未批，非"便宜"）—— 最小 HGS 工程
- **范围**：实现最小 HGS = giant tour + 经典（固定成本感知）Split + OX 交叉 + 基础群体 + true SWAP*/2-opt education，在**纯 VRPTW 归约**（EV/碳/多车场关闭）下运行。
- **复用**：公开算例 harness 已存在——`build_solomon_dimacs_bundles_20260717.py`、`build_solomon_sintef_bundles_20260717.py`、`audit_solomon_sintef_bks_20260717.py`、Homberger loaders、`instance_loader.py:load_instance`。Phase 0 只做算法，不重造加载器。
- **开发集**：Solomon R1/C1/RC1 代表子集 + Homberger-200 少量；**仅作开发去风险**，不作正式 BKS 表（见 §7.4）。
- **过门 `HGS_ENGINE_SUPPORTED`（预注册阈值，实施前与用户确认具体数字）**：车辆数命中 BKS 的实例比例 ≥ 阈值；距离 mean gap ≤ 阈值；零不可行；预算分账干净；两独立 ALNS 锚零漂。
- **收手 `HGS_ENGINE_NOT_SUPPORTED`**：逼不近 BKS 或整合层反复不可行 → 整体收手。
- **交付**：五件套（metadata/raw_runs/decision/artifact_hashes/report）+ 最小 HGS 源码在独立目录、不进正式 runner。
- **边界**：不改 `cost.py/check.py/evaluation.py`；不触发 §10 重跑；不宣称对本模型的性能胜负。

### Phase 1 —— 机制专门化（跨模型边界，需 MC 审批）
- **范围**：EV-aware Split（frvcpy 逐段定价车型+非线性充电）+ 机制算子（碳择时重排已有→接入；公平赤字修复新建）。
- **审批前置**：EV-aware Split 触及 SOC/充电/成本语义 → 必须先过 `model_change_approval_register` 八步（编号建议 `EA-001-*` 系或新 `ALGO-*`）。审批通过前只做接口桩 + 预算 0/1/2/5 功能探针。
- **开发集**：**模型自有复杂开发集**（另冻结，非 China81 正式 81 实例、非 Solomon 正式测试集）。Homberger 只证通用能力，不能替机制验证。
- **过门 `MECHANISM_SPLIT_SUPPORTED`**：同起点/同完整评价预算/配对种子下，对 LNS 与当前赢家总成本不劣且路线数下降；EV-aware Split 开/关消融改变路线数；充电/公平算子各有方向一致消融。
- **收手**：Split 在开发集既不降路线也不降成本 → 停 Split 分支，仅保留通用 HGS 收益。

### Phase 2 —— 整合、加速器与正式重跑
- **范围**：SP 路线池加速器（可选）+ 全整合冻结算法版本 + 按 §10 影响矩阵重跑 E2–E7。
- **过门 `ALGO_V2_FROZEN_AND_REVALIDATED`**：统计合同（MC-002 原则：27 单元、配对、Holm）逐网显著；公开 BKS 正式表（若届时获授权，见 §7.4）闭合；所有旧结论按影响矩阵重采、无暗改。
- **交付**：冻结代码/配置/hash + 影响矩阵 + 五件套 + HANDOFF/memory 同步。

---

## 7. 实验、开发集与统计验收设计

### 7.1 三类算例严格分层
- **公开开发集**（Solomon/Homberger 子集）：Phase 0 去风险、调参。
- **模型自有开发集**（另冻结）：Phase 1 机制验证、调参。
- **正式测试集**（China81 正式 81 实例、Solomon 完整正式集）：**只用于最终验收，禁止用于调参/选择候选**。

### 7.2 公平口径
- 所有臂同起点（`make_shared_initial_solution`）、同完整评价预算、配对种子、同墙钟报告、同 `evaluate()/check_solution` 单一真值源。
- 群体法每代 Split 解码 + education 的每次完整评分都必须过 `EvalBudget` 计数（见 §8）。

### 7.3 统计合同（对齐 MC-002 已批准原则）
- 主统计单元 = 27 个"地区×客户规模"；严格配对；五检验族 Holm 校正；结果盲暴露门。
- 最低种子数、效应量阈值等 MC-002 待冻结项，须待算力表+功效分析另行冻结后填入，不得以本 PRD 提前锁死。

### 7.4 公开 BKS 治理（重要，勿越界）
- `submission_contract.py` 已把已发布 BKS 对照锁为 `standard_benchmark_status = deferred_post_e2`，且"自建 L-main 不得当已发布 BKS 表"。
- 因此：**Phase 0/1 用公开算例=开发去风险，允许**；**把 BKS-gap 表写成正式论文结果=正式门（对应主计划步骤 21），须另行授权、须与"证明通用能力≠证明补能机制有效"的边界一并声明**。两者不得混同。

---

## 8. 预算记账与探针纪律（沿用 EA-001 四分账）
- `screen_evaluations`：包络/下界筛选。
- `route_oracle_calls`：每次非线性充电子问题（标签扩展数、支配删除数、缓存命中分别记）。
- `complete_candidate_evaluations`：任何用于排序/接受/更新最好解的完整解，评分前预留并计一次。
- `reference_evaluations`：终局独立复算。
- 预算 0 不生成/评分候选；1/2/5 必须在超限前停止。局部调用再多不得掩盖完整解评分；缓存不得漏记。
- G0 已闭合（`PASS_ALNS_BUDGET_G0_COMPLETE`）；新组件必须保持该预算语义，任何新的隐藏完整评分视为回归失败。

---

## 9. 风险登记与缓解

| # | 风险 | 严重度 | 缓解 |
|---|---|---|---|
| R1 | 公开 benchmark 称霸 ≈ 确定，但**自有中国实例 headroom 可能天生低**，任何算法都拉不开 | 高 | Phase 0 先锁定公开 benchmark 那半个高确定收益；自有实例领先以"转负例+显著性"为现实目标，不承诺绝对成本悬崖 |
| R2 | **7/31 deadline**：HGS 是真算法工程 + 强制 E2–E7 重跑 | 高 | 分阶段可中止；Phase 0 便宜早决；若时间不足，冻结在"通用 HGS 已验证+机制故事"的中间态交付 |
| R3 | 精确 FRVCP 最坏指数增长 | 中 | 分层筛选（包络先筛，top-B 才调预言机）；top-B 预注册并用小例穷举证明不漏最佳模式 |
| R4 | SP 路线池随池增大变贵、且历史小池零 headroom | 中 | 作 Phase-2 可选加速器；大精英池单独验证；不达标即弃 |
| R5 | 身份漂移（ALNS→memetic）引审稿质疑 | 中 | 明确定位"ALNS 作 education 内核的 memetic HGS"；四臂消融（纯 ALNS/直接强重组/群体化/群体化+机制算子）说清增量来源 |
| R6 | 跨机浮点（M1 vs x86） | 中 | 正式数字只用 M1；x86 只做相对% |
| R7 | 调参污染正式测试集 | 高 | §7.1 三层算例硬隔离；正式集只进最终验收 |

---

## 10. 影响矩阵（算法版本变化强制重跑）
算法内核冻结为新版本后，以下必须按新版本重采，旧证据仅作历史/诊断，不得拼接：
- **E2**（性能主线）：必重跑（这是算法版本的直接下游）。
- **E3/E6**（机制消融/公平）：依赖搜索结果，必重跑。
- **E4**（时变碳择时）：若 education 的充电重排语义变化则重跑；仅群体外壳变化而充电语义不变时按只读复算核对。
- **E7**（动态滚动）：依赖内核，必重跑其正式载荷。
- **E1**（结构门）：按新版本复核。
- 具体重跑清单在 Phase 2 冻结时逐项落 `影响矩阵` 附表，并同步 HANDOFF/memory。

---

## 11. 治理、审批与保护文件边界
- Phase 0 不需模型审批（不碰模型语义）；**Phase 1 必须先过 `model_change_approval_register` 八步**（EV-aware Split 触及 SOC/充电/成本）。
- 保护文件（§1.3）未获批不得改。
- 机器合同在批准前保持 `DRAFT_METHOD_AWAITING_USER_APPROVAL` / `formal_search_allowed=false`。
- 探索原型进独立目录，不由正式 runner 导入；不得读取正在进行的 E7 中间结果。

---

## 12. 交付物与记录制度
- 每个过门产五件套：`metadata.json` / `raw_runs.csv` / `decision.json` / `artifact_hashes.json` + `report.md`；`artifact_hashes.json` 排除 `._*`/`__pycache__`/`.pytest_cache`/`.tasks`，AppleDouble 污染标记后清理重算。
- 重大结论/HALT/审批/版本冻结同步：HANDOFF 变更日志、`memory/MEMORY.md` 索引、相关 `memory/*.md`、（若派 Codex）`codex_prompts/*.md`。
- 本 PRD 批准后，其状态由 `DRAFT_AWAITING_USER_APPROVAL` 改为对应实施阶段，并登记审批链。

---

## 附录 A：权威参考文献
- Prins, C. (2004). A simple and effective evolutionary algorithm for the vehicle routing problem. *Computers & Operations Research*, 31(12), 1985–2002.（giant tour + Split）
- Vidal, T., Crainic, T. G., Gendreau, M., Lahrichi, N., & Rei, W. (2012). A hybrid genetic algorithm for multidepot and periodic vehicle routing problems. *Operations Research*, 60(3), 611–624.（HGS）
- Vidal, T. (2022). Hybrid genetic search for the CVRP: Open-source implementation and SWAP* neighborhood. *Computers & Operations Research*, 140, 105643.（HGS-CVRP + SWAP*）
- Hiermann, G., Puchinger, J., Ropke, S., & Hartl, R. F. (2016). The electric fleet size and mix VRP with time windows and recharging stations. *EJOR*, 252(3), 995–1018.
- Froger, A., Mendoza, J. E., Jabali, O., & Laporte, G. (2019). Improved formulations and algorithmic components for the EVRP with nonlinear charging functions. *Computers & Operations Research*, 104, 256–294.
- Kullman, N. D., Froger, A., Mendoza, J. E., & Goodson, J. C. (2021). frvcpy: An open-source solver for the fixed route vehicle charging problem. *INFORMS Journal on Computing*, 33(4), 1277–1283.
- Wang, W., Adulyasak, Y., Cordeau, J.-F., & He, G. (2025). The heterogeneous-fleet EVRP with nonlinear charging functions. *Transportation Research Part C*, 170, 104932.
- Wouda, N. A., Lan, L., & Kool, W. (2024). PyVRP: A high-performance VRP solver package. *INFORMS Journal on Computing*, 36(4), 943–955.
- 陈雨蝶, 干宏程, 程亮, 等 (2025). 双碳背景下复杂冷链物流模型及求解算法. *系统工程理论与实践*. DOI:10.12011/SETP2024-2027.（目标期刊母版）
- Soriano 等 (2023). 多车场公平/协同路由（公平修正插入）。
- 综述锚：周鲜成 2021《绿色 VRP 模型与求解算法综述》，系统工程理论与实践（目标期刊算法三层分类）。

## 附录 B：术语表
- **Split**：给定客户顺序（giant tour），用辅助图最短路 DP 把它切成成本最优的若干条路线，天然处理每路线固定成本。
- **HGS**：群体 + Split 解码 + 交叉 + education 局部搜索 + 惩罚式可行性的混合遗传搜索。
- **SWAP\***：跨路线交换两客户但各自在对方路线中重插最佳位置（Vidal 2022），非原位互换。
- **FRVCP**：固定路线车辆充电问题；给定路线求最优充电站/次数/量的非线性子问题。
- **SREX/OX**：VRPTW/CVRP 常用交叉算子（route/order 层重组）。
- **biased fitness**：HGS 幸存者选择的适应度 = 成本排名 + 多样性排名，兼顾质量与多样性。
