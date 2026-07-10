# ReSETP 全项目 PRD 与施工图 v2

更新时间：2026-07-02
执行对象：Codex / M1 主仓 + x86 DR 线
状态：执行规划，不是实验结论

本文件把 ReSETP 从“单个 E2 卡点排查”升级为“全项目可执行 PRD 与施工图”。它继承 `docs/handoff/project_planning_map_20260701.md` 与 Claude worktree 里的 `docs/handoff/e2_prd_and_planning_map_20260702.md`，但修正两个时效事实：当前主工作区的 GA 长复核已补跑到 `16000/16000 OK`，所以 “GA 仍 9229/16000 HALT” 已过时；`5174.345121253789` 同值平台已由 C1 审计判为 `ARTIFICIAL_HOMOGENIZATION`，E2-G0 当前未过门。

`HANDOFF.md` 仍是单一事实源；本文件负责定义“目标、顺序、PDCA、停止条件、记录制度、Codex 任务队列”。冲突时先查 `HANDOFF.md` 和原始 CSV/JSON，再更新本文。

---

## 0. 一页结论

项目总目标不是把功能堆满，而是完成一篇可投稿《系统工程理论与实践》的统一证据链：动态需求、时变电网碳强度、多车场协同、收益公平、混合能源车队、ALNS/DR-ALNS 算法贡献必须在同一问题中互相咬合。

当前最大卡点仍是 **E2 算法有效性**。E2 不闭合，E1/E3/E4/E5/E6/E7 的正式数字都只是候选，因为求解器是否可信、算法贡献能否写、场景参数能否贯穿全文都还没有定稿。

当前 E2 的事实状态：

- Goeke80：物理上 EV/充电机制很弱，09y Stage0 标为 `Z_EV_PHYSICALLY_UNSUPPORTED_80KWH`；可作为文献基准场景，但不适合作为现代混合车队主故事。
- 280kWh：三班倒场景能保住 EV/充电机制；旧 Stage B 在 baseline 活性修复前为 `MECHANISM_BUT_TIE`，baseline 修复后单实例 `e2-threeshift-150c-01` 出现 ALNS 明显低于 GA/LNS/PSO/VNS 平台的信号。
- 最新同实例长复核：`ev_heavy_findability_gate_long_same_instance_v2_data/raw_runs.csv` 中 14 行全 `OK`，GA/LNS/PSO/VNS 两个 seed 全部为 `5174.345121253789`、EV share `0.6818181818181818`；ALNS 变体为 `3569-3653`。C1 审计 `baselines/e2_alns/e2_g0_same_value_platform_audit_20260702.md` 判定：四个 baseline 的 best 更新均由共享车型翻转通道在 eval≤42 内推到同一平台，之后至少 15958 eval 无 native best 更新；所以该 30% 不能写成对健康 baseline 的正式领先。
- 主 ALNS 还不独立：`alns_wouda.py` 仍通过 `Reference Algorithm/ALNS-7.0.0@N-Wouda` 引入 ALNS 骨架，`winner_operators.py:914` 仍 import `alns.accept.SimulatedAnnealing`。正式论文算法必须剥离。
- DR-ALNS 未 paper-ready：Track17/19/20/21/Pilot25 仍是证据修复和动作面 sanity 阶段，不能拿来救 E2 结论；但必须预留接口，并行推进。

推荐主线裁决：

1. **E2-G0 同值平台审计已完成但未过门**：verdict=`ARTIFICIAL_HOMOGENIZATION`。下一步不是扩跑，而是 C1-R1/C1-R2，把共享车型翻转通道从 baseline 算法成绩中剥离或单独记账，再重跑 G0。
2. **场景口径已由 user 06-26 拍板,不再重开**：主场景默认 = Goeke80（Q=3650kg, B=80kWh）；280kWh 只作诊断场景,明确不作当前默认、不作现代物流主张、禁止在其 EV-dominant 状态写"混合最优"（MASTER §33/§42）。**电池单参数路线已关门**（09l `BATTERY_ONLY_INSUFFICIENT`：19 个真实来源电池值无一能跨规模稳定 20-80% 混合），不要再调电池。混合车队主故事的正路是**现实运营约束**（车场充电桩容量/资本→公共桩稀缺→EV资本/长路线 eligibility），或诚实降级算法主张。**关键解耦**：E2（算法能不能赢）不依赖混合场景是否解决——ALNS vs 基线在 Goeke80 同一问题上就是有效对比,EV 高低不影响比较合法性。
3. 在任何正式 T3 前完成 **G1 ALNS 独立化剥离**。
4. E2 正式比较采用“双账本”：主账本等墙钟公平，副账本固定 eval 闭合子集；任何实际 eval 不足都必须报告，不准把 wall-clock OK 写成 16000 eval OK。
5. DR-ALNS 作为并行研发线：若过独立门槛，可成为第二算法/扩展表；若不过，写 future work，不污染 E2。

---

## 1. 宪政与纪律

### 1.1 事实源宪法

优先级：

1. `HANDOFF.md`：项目事实源、变更日志、当前门槛。
2. 原始数据：CSV/JSON/checkpoint/metadata/hash，优先于报告散文。
3. 本文档：规划、施工顺序、PDCA、任务队列。
4. `docs/handoff/memory/`：项目记忆与冷启动索引。
5. 旧 prompt：只能作历史，不得推翻新数据。

任何结论必须标注类别：

- `FACT`：已由文件/数据证明。
- `INFERENCE`：从数据推断，但仍需复核。
- `DECISION`：项目裁决，允许以后更新。
- `HALT_*`：未过门，停止推进。
- `VALID_BUT_WEAK`：合法但弱，不得包装成强结论。
- `MECHANISM_BUT_TIE`：机制存在，但算法没有赢。

### 1.2 文件与语义纪律

冻结语义，除非用户单独批准：

- 不改 `solver/src/setp_solver/cost.py` 的目标函数语义。
- 不改 `solver/src/setp_solver/check.py` 的可行性语义。
- 不改 `solver/src/setp_solver/search/evaluation.py` 的预算/评分语义。
- 不为救结果改 `prices.py` 默认值；参数变更必须走四同步链。

四同步链：

1. `solver/src/setp_solver/prices.py` 默认值与来源注释。
2. `docs/paper_submission_final/paper_main.tex` 参数表、说明、引用。
3. `HANDOFF.md` 与本文档。
4. 原始证据报告：来源、fixed replay、真实重优化、跨 family/size/seed 稳定性。

### 1.3 Codex 执行纪律

Codex/Claude 启动前必须先读 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`，并按其中强制清单读取入口文件。读完前不得改代码、跑实验或下论文结论。

Codex 每个任务必须先写任务卡：

```text
目标：
输入：
要读的事实源：
允许改的文件：
禁止改的文件：
命令：
验收：
停止条件：
产物：
```

每个实验必须留下：

- `metadata.json`：commit、branch、python、numpy、命令、参数、runner 版本。
- `raw_runs.csv`：所有 row，不删失败行。
- `decision.json`：verdict、门槛、失败原因。
- `artifact_hashes.json`：关键产物 hash；必须排除 `._*`、`__pycache__`、`.pytest_cache`、临时 checkpoint 和非论文证据。
- `report.md`：只解释数据，不夸张。
- `HANDOFF.md` 追加记录：数字、标签、下一步。

### 1.4 圆桌会议制度

重大方案必须先开圆桌，至少三席：

- 审稿人：专抓过度主张、对手单薄、统计口径、参数故事。
- 工程负责人：专抓可执行性、脏工作区、预算、回滚、记录。
- 算法/DR 负责人：专抓搜索机制、baseline 健康、DR 接口、算法创新。

圆桌输出不是最终事实，只作为裁决输入。最终裁决必须回到原始文件和数据。

### 1.4.1 本轮圆桌裁决

2026-07-02 本轮圆桌形成如下裁决，已写入本文后续施工图：

- 审稿人票：D1 曾推荐 `Modern-280 主场景`——**此裁决已作废**（Claude 2026-07-02 核查发现它违背 user 06-26 拍板：主场景锁 Goeke80、280 只作诊断、禁止 280 EV-dominant 下写混合最优。圆桌当时未读到 06-26 决策）。D2/D3/D4/D5 仍有效：`5174.345121253789` 同值平台不解释不能引用 30% 领先；正式 T3 前剥离 N-Wouda；DR 只能第二算法/future work；顺序 G0 先行。
- 工程负责人票：当前主工作区里 GA under-eval 已由 `16000/16000 OK` 修正，旧 PRD 不能再写成 open HALT；但 `5174.345121253789` 平台仍是最大风险。AppleDouble `._*` 已经污染至少一个 hash 清单的可能性很高，正式证据链必须先清理并重生 hash。
- 算法/DR 负责人票：DR-ALNS 架构可接入，但性能贡献未成立；`solver/rl` 与 x86 报告只能作为并行研发线，正式 E2 默认关闭 DR checkpoint。`_dynamic_reward` 在缺动态字段时信号不足，不能用 reward shaping 叙事代替动态决策证据。

最终裁决：本 v2 不是“立即扩跑许可”，而是“先关 G0 和场景/独立性/证据卫生门”的施工令。

### 1.5 仓库卫生纪律

当前主工作区有未提交实验数据和代码改动；Claude worktree 有 PRD v1 新文件；仓库还存在大量 AppleDouble `._*` 文件，`.git/objects/pack` 中也出现 `._pack-*.pack`。这些不是论文证据，必须在正式施工前单独处理。

禁止把仓库卫生清理混进算法结果 commit。建议先开 `C0` 任务：只做同步/清理/记录，不跑实验。

若任何 `artifact_hashes.json` 已包含 `._*` 或 `._artifact_hashes.json`，该 hash 文件只能标为 `HASH_CONTAMINATED_APPLEDOUBLE`，不得作为正式证据。处理顺序是先清理、再重算 hash、再在 `decision.json` 中说明旧 hash 作废原因。

---

## 2. 宏观施工图

### Phase 0：治理与事实冻结

目标：把当前散落在主工作区、Claude worktree、记忆和报告里的事实收成统一施工图。

Plan：

- 合并或复制 Claude worktree 的 PRD v1 内容到主线本文档，不直接覆盖当前主工作区事实。
- 记录当前 dirty worktree：哪些是数据补跑、哪些是代码修复、哪些是未归属实验。
- 清理 AppleDouble，更新 `.gitignore` 或清理脚本，避免 Git pack 警告复发。
- 建立 `docs/handoff/memory/project-prd-execution-v2.md`。

Do：

- 只改 docs/handoff 与 memory 索引。
- 不跑 solver。
- 不改 cost/check/evaluation。

Check：

- `git status --short --branch` 可解释。
- 新文档引用路径存在。
- `HANDOFF.md` 有本次规划记录。
- `artifact_hashes.json` 不含 `._*`、`__pycache__`、`.pytest_cache`。

Act：

- 若发现未归属实验数据，先登记为 `UNCLASSIFIED_ARTIFACT`，不得纳入结论。
- 若发现 hash 污染，标 `HASH_CONTAMINATED_APPLEDOUBLE`，先清理重算，不进入正式统计。

### Phase 1：E2 闭合

目标：把 E2 从长期调试转成可审稿的 T3/F2 算法有效性证据，或诚实降级。

顺序：

1. E2-G0：同值平台与 baseline 健康审计。
2. E2-G1：ALNS 独立化剥离。
3. E2-G2：场景口径合规核对（user 06-26 拍板的落实，不是重新裁决）。
4. E2-G3：基线集补全与预算协议。
5. E2-G4：三班稳定性小全量复核。
6. E2-G5：正式 T3/F2。

停止条件：任何 G0-G3 未过，不启动 G4/G5。

### Phase 2：场景与参数正式化

目标：让 Goeke80/280kWh/其他参数的角色在论文中清楚，不互相救场。

已拍板裁决（user 06-26，不重开）：

- **Goeke80（Q=3650kg, B=80kWh）= 当前默认工作场景 / Goeke 对齐基线**。它不是"现代混合车队主张"，只是参数对齐 + 算法可行性底座。
- **280kWh = 诊断场景，不作当前默认、不作主场景**；禁止在其 EV-dominant 状态写"混合最优"。
- **电池单参数路线已关门**（09l `BATTERY_ONLY_INSUFFICIENT`）：不再调电池凑混合。
- **混合车队主故事若要立起来，走现实运营约束**（车场充电桩容量/资本 → 公共桩稀缺 → EV资本/长路线 eligibility），先做证据矩阵 + 最小语义设计，可开关、旧语义可复现；否则诚实降级算法/混合主张。

停止条件：

- 不得为凑混合无来源地调电池或回潮把 80/280 包装成现代主场景。
- 运营约束路线是潜在长活（09m-09q 多次 HALT），不得为它无限长跑；每步用最小可判实验，跑不出就诚实降级。

**已关闭路线台账（历史已试尽；任何 agent 重提其中一条前，必须先说明"与当时失败条件有何不同"并经 user 明示同意）：**

1. **调电池凑混合** — 09l `BATTERY_ONLY_INSUFFICIENT`：19 个真实来源电池值（60-291kWh）全梯度跑满，无一跨规模稳住 20-80% 混合带。
2. **拿电池档当机制活跃度轴救 vanilla ALNS** — 09v/09w `INCONCLUSIVE_NO_NONDEGENERATE_TENSION`：80/100/150/280 四档在 75-200c 全部 0/12/0 平局、EV share 恒 ~0.057、充电动作恒 1.0，两次跑满均无分离。
3. **车队上限直接当混合故事** — 09n `HALT_COLLECTION_COST`：直接套 Goeke metadata cap 大面积 `INIT_INFEASIBLE`，`ev_cap_only` 假平衡出带。正确的实体车硬上限+多趟语义已由 09s 落地为代码事实；但 09s/09t/09u 证明 Goeke80 + 硬上限下 winner EV share 仍仅 ~0.057——**上限本身造不出混合，混合的前提是 EV 物理可行（电池够）**。
4. **"280+三班+上限能不能出混合"的小验证** — 已跑过且已过：09y Stage A `THREESHIFT_MIXED_GENERALIZES`（9 个三班 100/150/200c 实例 8 个过 EV≥30% 且零违约）。不需要再跑一遍。
5. **用小算例/低预算快跑先分算法胜负** — 系统性失败：09s smoke 15/17 平 → 09t Stage A 60/69 平 → 09u 等墙钟 20/23 平 → 09v/09w 全平 → 09y Stage B（280 三班正式对比,144/144 行零缺失）0/24/0 全平、mean gap 0.0000%。**低预算配对在本问题上判别力不足,平局是常态输出,不是信号。** 唯一出现过大差距的是 baseline 活性修复后的同实例长复核（5174 vs 3364）——其真伪正是 C1 要审计的对象。
6. **手写碳算子当算法贡献** — 09x `WEAK_CARBON_SIGNAL` + 09y Stage B carbon vs ablation 全平。**（2026-07-03 依本台账重开协议合法重开：09x/09y 的测量发生在 C1 确诊的同质化坏机器上——09y Stage B 连 ALNS 与 GA 都逐位打平即该假象本身；G0 v2 过门后测量装置已根本不同。重测=健康机器上的碳消融 gate；结果未出前,"碳算子有用"仍视为未证,不得预写进论文。）**
7. **280kWh 正式化为主场景** — user 06-26 否决（本 v2 圆桌曾误重开,2026-07-02 已作废）。

### Phase 3：E1/E3/E4/E5/E6/E7 实验重设计

目标：吸收 E2 的经验，避免后续实验只给总成本、不展示机制。

核心规则：

- 每个实验必须保留机制指标，不只看 best cost。
- 动态需求必须证明三交互：动态×协同、动态×公平、动态×时变碳。
- 如果场景里没有 EV 充电，动态×碳必须诚实降级。
- **最小充分实验集纪律（战略主编票）**：每个贡献句至少配一张表，多余实验一律不进投稿版。映射：贡献1（模型）→E1/T4 + 跨车场服务量>0；贡献2（碳入决策）→E4/T7/F5 充电时段迁移 + E3/T5 消融边际；贡献3（动态机制）→E7/T9 三交互（③做不出则贡献3 措辞收缩为"机制+接口"，不写四要素耦合）；贡献4（算法）→E2/T3/F2 健康基线 seeds≥5 Wilcoxon。E6/T8 公平 θ 扫描保留（公平是标题要素）。除此之外"看起来更全"的实验不进投稿版。

### Phase 4：DR-ALNS 并行研发与接入

目标：不让 DR 卡住主论文，但也不放弃算法创新上限。

路线：

- M1：只做独立 ALNS 接口预留，不训练 DR。
- x86：继续 Track19/20/21/Pilot25，按 bounded gates 推进。
- 合并条件：DR 只在同环境、同预算、健康 baseline 下证明超过独立 ALNS/AlphaUCB 后，才能进入正文主表。

### Phase 5：正式重跑与表图重灌

进入条件：

- E2-G5 通过或算法主张已明确降级。
- 主场景参数定稿。
- E7 三交互指标设计完成。
- 图表字段与论文叙事一致。

产物：

- E1-E7 全量 runner 结果。
- T3-T9、F1-F6/F5b。
- `latexmk` 编译记录。
- 回归测试记录。
- 最终 HANDOFF。

### Phase 6：论文叙事与失败史资产化

目标：把 09c-09y 的排查过程变成可信故事，而不是聊天残骸。

写法原则：

- 论文正文只写最终证据。
- 附录/方法补充可写“为何 Goeke80 作为默认基准、为何 280kWh 仅作诊断场景、baseline health gate”。
- HANDOFF 与报告保留失败史，服务未来答辩和复查。

---

## 3. E2 重点施工图

### 3.0 当前施工边界与挂账（2026-07-11）

当前唯一主线是 **E2 算法性能闭合**。在 30 次 `staged ALNS-LNS hybrid` 稳定性门完成、解复算和算法身份冻结前，电池/车型结构复核与动态低碳充电验证均标记为 `DEFERRED / BLOCKED_BY_E2_ALGORITHM_FOUNDATION`，不得抢跑。

挂账一：以后从 E2 已保存解补算 EV/CV 的路线、实体车辆、客户/需求/距离份额，充电动作与电量，以及充电时间可移动空间；必要时才做有界容量筛选，不为凑混合重跑历史电池梯度。

挂账二：以后先在固定车型、路线、客户分配和总充电电量下，对比最早可行充电与低碳时段充电，确认降碳来自时间移动；再验证动态需求是否创造该空间。若路线固定后不能移动充电，不得宣称动态需求促进低碳充电。

解冻条件：30 次稳定性门完整结束；保存解零违规且统一评价器复算通过；ALNS-LNS hybrid 相对 LNS 的稳定性结论明确；正式入口和算法身份冻结。解冻前不改求解器、评价器、价格、默认 80 kWh 或论文正文。

### E2 的最终定义

E2 = 算法有效性验证。它回答：在同一 ReSETP referee（`evaluate()` + `check_solution()` + `EvalBudget`）下，独立 ALNS/DR-ALNS 是否比健康文献基线更强。

硬门槛：

- 零违约。
- 健康 baseline。
- 同预算或等墙钟口径清楚。
- 多 seed。
- Wilcoxon 或明确 sign-test。
- 原始数据全保留。
- 机制指标随表输出。

### E2-G0：同值平台与 baseline 健康审计

目的：解释 `5174.345121253789` 平台，判断它是合理共同邻域收敛还是人为同质化。

2026-07-02 执行结果：`baselines/e2_alns/e2_g0_same_value_platform_audit_20260702.md` 已完成 C1 审计，输出目录 `baselines/e2_alns/e2_g0_same_value_platform_audit_data/`。verdict=`ARTIFICIAL_HOMOGENIZATION`，标签 `HASH_CONTAMINATED_APPLEDOUBLE`、`EV_MAXIMAL_REFERENCE_NOT_BOUND`。关键证据：8 条 baseline 行全部 `16000/16000 OK` 且 checkpoint 回放零违约，但 best cost/signature/EV share 跨 GA/LNS/PSO/VNS 与 seed1/2 完全相同；所有 best 更新均在 eval≤42 通过共享车型翻转通道完成，之后至少 15958 eval 无 native best 更新。

Plan：

- 输入：`baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data/raw_runs.csv`、checkpoint、`metaheuristic_baselines.py`。
- 核查 GA/LNS/PSO/VNS 的 `history_json`、`operator_counts`、`best_signature`、checkpoint solution。
- 比较四算法到达平台的路径：first improvement eval、关键 operator、route list、charging actions。
- 设计一个只读 replay：用冻结 `evaluate()`/`check_solution()` 复核平台解。
- 设计一个对照：关闭或替换共享 `_vehicle_type_mutation()` 通道，只在 smoke 小预算检查是否仍同值。

Do：

- 只读审计优先，必要时写 `baselines/e2_alns/plateau_5174_audit.py`。
- 不改 baseline 算法语义。

Check：

- 输出 `plateau_5174_audit.md/json`。
- 给出三类 verdict：
  - `HEALTHY_SHARED_LOCAL_OPTIMUM`：同值是不同算法在共同合法邻域内收敛到同一局部最优，可继续。
  - `ARTIFICIAL_HOMOGENIZATION`：共享 deterministic 通道主导搜索，使 baseline 壳算法失去差异，必须整改。
  - `BASELINE_HEALTH_UNRESOLVED`：证据不足，不能引用 30% 领先。

Act：

- 若 `HEALTHY_SHARED_LOCAL_OPTIMUM`：可进入 G1/G2。
- 若 `ARTIFICIAL_HOMOGENIZATION`：把车型翻转/充电修复改成各算法自有邻域或显式共同 repair layer，并重跑 G0。
- 若 unresolved：不得扩大实验。
- 当前 Act：按 `ARTIFICIAL_HOMOGENIZATION` 执行。G4/G5 冻结；单实例 30% 领先不得写入论文；下一步做 C1-R1 common preprocessing / common repair layer 分账与 C1-R2 operator provenance gate。

约束：

- 不许把“baseline 能动”直接写成“baseline 健康”。
- 不许把单实例 30% 写入论文。

### E2-G1：ALNS 独立化剥离

目的：让主算法不依赖 `Reference Algorithm/ALNS-7.0.0@N-Wouda` 文件。

Plan：

- 新建 `solver/src/setp_solver/search/resetp_alns/`。
- 拷贝剥离最小骨架：迭代循环、AlphaUCB、HillClimbing/RRT/SA 接受准则。
- 文件头保留 MIT 来源说明。
- 自有 destroy/repair/碳算子保持项目内。
- 对外 API 保持与 runner 兼容。

Do：

- 一次 commit 只做剥离，不做算法改进。
- 加单测（**多路径锚集**，单一 100-01 锚不够——它只覆盖 Goeke80 默认路径，覆盖不到 280 override、多趟 `CV1#T1` 语义、`FLEET_SIZE` 硬上限、分级墙钟帽这些新代码路径；审稿人若查算法出身，这些路径都要能证明剥离前后逐位一致）：
  - 无 `Reference Algorithm` / `from alns` / `import alns` 命中主算法路径。
  - 锚 1（Goeke80 默认）：100-01 `4878.331796187524` mean、seed2 `4779.053444002934`。
  - 锚 2（280 override + 多趟 + 硬上限）：`e2-threeshift-150c-01` 上 ALNS 主变体的 `best_cost`（当前 `3569-3653` 区间那组）+ best-solution history hash 剥离前后一致。
  - 若剥离前后任一锚有一位漂移：先做 adapter parity audit 定位（RNG 消耗顺序、浮点求和顺序是常见嫌疑点），可解释则重新钉锚并记录，不可解释不得继续。
  - `solver/tests/` 相关测试全绿。

Check：

- `rg "Reference Algorithm|from alns|import alns" solver/src/setp_solver` 主算法路径零命中。
- E2 runner 只调用独立 ALNS。

Act：

- 若数值漂移：先做 adapter parity audit，不能带漂移继续。

### E2-G2：场景口径（已拍板，不重开）

目的：**不是重新裁决场景**——user 06-26 已锁 Goeke80 为默认、280 只作诊断、电池路线关门（见 Phase 2 与 §0）。本节只做两件事：(a) 确保 E2 正式跑用 Goeke80 默认参数,不用内存 override 冒充默认;(b) 若后续要把混合车队主故事立起来,单独走"运营约束"设计（另起 gate,不在 E2 关键路径上,不阻塞 E2 算法结论）。

关键解耦（省时间的核心）：

- **E2 = 算法能不能赢,在 Goeke80 上就能答**。EV 占比高低不影响"ALNS vs 基线"这个对比的合法性。别再为了让 EV 活跃而反复换场景——那正是 21 天长跑无果的根源。
- 混合车队 / 时变碳 / 动态×碳 的"可见性"是 **E3/E4/E7 的模型侧问题**,靠运营约束或诚实降级解决,不该拖着 E2 一起卡。

Check：

- E2 正式跑 `prices.py` 默认 = Goeke80,不用 override。
- 若启动运营约束设计,先证据矩阵 + 最小语义 + 可开关,不改 cost/check/evaluation。

Act：

- 若正式 E2 入口仍依赖 280kWh 内存 override 冒充默认，或 `prices.py` / TeX / HANDOFF 三处口径不一致：标 `SCENARIO_COMPLIANCE_BLOCKED`，停止正式 E2，仅允许继续 C1 审计和 C3 剥离。

### E2-G3：基线集补全与预算协议

目的：避免“对手单薄”。

基线候选：

- 必做：GA、PSO、VNS、LNS、ACO、GA-VNS、GWO、IWD。
- SA：保留为地板。
- TS：仅当现成可适配。
- NSGA-II：若 TeX 仍承诺，必须补或改 TeX。

预算协议：

- 主账本：等墙钟公平，报告 actual evals、elapsed、checkpoint recovery。
- 副账本：固定 eval 子集，只纳入所有算法都能达到 `16000/16000` 的行。
- 大规模若固定 eval 不闭合，不准静默改成 OK；只能写 wall-clock OK。

健康门槛：

- `returned_initial_signature=false`。
- `best_improvement_count>0`。
- `first_improvement_eval` 合理。
- checkpoint 可读。
- 解通过 frozen check。
- 不存在无法解释的跨算法同值。

### E2-G4：三班稳定性小全量复核

目的：在正式 T3 前，用小全量判断单实例信号是否能泛化。

范围：

- 三班 `100c/150c/200c` 的 `-01/-02/-03`。
- seeds 至少 3。
- 算法：独立 ALNS 主变体、carbon ablation、GA/LNS/PSO/VNS、至少一个强混合基线。

Check：

- ALNS 对健康 baseline mean gap >= 10%。
- 方向一致。
- 机制指标可见：EV share、charging actions、E_total、E_cv_direct、E_ev_indirect。
- 采集失败为 0，或失败行明确排除并说明。

Act：

- 若 30% 单实例优势消失：停止“ALNS 显著胜出”叙事，转为算法设计/DR 或降级。

### E2-G5：正式 T3/F2

目的：给论文正式算法表。

范围：

- 全 69 个 E2 实例，或经用户批准的正式子集。
- seeds >= 5，目标 10。
- M1 系统 Python `/opt/anaconda3/bin/python3.13` + numpy `2.3.5` + `PYTHONHASHSEED=0`。

交付：

- T3 表。
- F2 收敛图。
- 机制指标表。
- baseline health appendix。
- `HANDOFF.md` 记录。

停止条件：

- 任一核心算法无法健康运行。
- 关键规模 gap < 10% 且无合理解释。
- DR/ALNS 环境混表。

---

## 4. E1-E7 逐实验 PDCA

### E1 静态主解结构

目的：证明主场景下完整模型能产生可解释调度结构。

Plan：

- 选定主场景参数和独立 ALNS。
- 输出 route、vehicle、charging、carbon、fairness、cross-site 分解。

Do：

- 跑正式主解。
- 用 `evaluate()` 分项对账。

Check：

- 零违约。
- 成本分解合计闭合。
- EV/CV 结构非退化。
- 充电动作非退化。
- 跨车场服务或资源共享可见。

Act：

- 若结构退化，回到场景或实例解释，不改目标函数救场。

### E2 算法有效性

见第 3 节。E2 是全项目关键路径。

### E3 车型反事实与模型消融

目的：证明 mixed/CV/EV 与模型层级各自有边际贡献。

Plan：

- 车型反事实：all-CV、all-EV、mixed。
- 模型消融：M0-M5，逐层加入协同、EV 间接碳、时变碳、碳配额、收益公平。

Do：

- 固定实例、seed、预算。
- 只改被测机制，其他冻结。

Check：

- 每层差异方向可解释。
- 反事实不因 infeasible 被误写成差。
- M0-M3 不得偷用 M4/M5 的碳交易或公平口径。

Act：

- 若边际贡献不显著，写机制不强或场景退化，不改实验定义。

### E4 碳强度/配额/碳价敏感性

目的：证明时变电网碳强度和碳价/配额会改变充电、车型和路径。

Plan：

- 扫 γ_t 情景、CE 配额、carbon price。
- 保留 0.05034 主碳价与 0.04184 低值锚。
- 设计碳盲对照。

Do：

- 用独立 ALNS 主场景。
- 输出 EV 充电时段平均碳强度。

Check：

- 有 EV 充电时段迁移。
- 有 E_cv_direct / E_ev_indirect 分解。
- 单调性或拐点可解释。

Act：

- 若 Goeke80 退化为无 EV，E4 只能写 CV 主导或碳机制不可见；modern-280 才能支撑时变碳机制。

### E5 补能技术参数

目的：证明充电功率、非线性充电曲线、车场/公共桩参数对解有影响。

Plan：

- 先裁决 E5 是否独立实验，还是并入 E4。
- 若独立，参数必须有来源。

Do：

- 扫 π_s、充电曲线、车场桩容量、公共桩可用性。

Check：

- 充电动作、等待、成本、碳排有可见响应。
- 参数来源写清。

Act：

- 若旧 471 跑量没有 E5，不能事后虚构；要么补跑，要么改论文结构。

### E6 收益公平阈值敏感性

目的：证明协同不是牺牲某个车场换总成本。

Plan：

- 先验证各车场独立基准收益 Π_d^0。
- 扫公平阈值 θ。

Do：

- 固定场景和算法。
- 输出各车场收益、公平比、总成本、碳排。

Check：

- Π_d^0 > 0，否则公平比解释失效。
- 出现公平价格曲线：θ 越高，总成本/协同范围如何变化。

Act：

- 若公平只作为评价指标而非约束，必须明示。

### E7 动态滚动重规划

目的：证明动态需求是三机制压力测试，而不是“订单变了再跑一次”。

Plan：

- 审计 `run_rolling_reoptimization` 每阶段是否使用完整目标。
- 设计三类事件：新增、取消、需求变化。
- 设计三交互指标。

Do：

- 动态×协同：记录跨车场吸收比例、案例、无协同基线。
- 动态×公平：逐阶段车场收益、公平比、约束状态。
- 动态×时变碳：EV/CV 分工、充电时段碳强度、新增碳排、碳盲对比。

Check：

- 三交互至少各有一个指标或案例成立。
- 若 `min_fairness_ratio=off`，不能写公平参与动态决策。
- 若无 EV 充电，不能写时变碳参与动态决策。

Act：

- 若三交互不成立，E7 降级为滚动接口与状态继承可行性实验。

---

## 5. DR-ALNS 施工图

### 5.1 当前可信状态

可信事实：

- 早期 offline block probe 有 `PROMISING` 信号，但不等于 paper-ready。
- Track17/19 暴露 baseline health 与合法比较问题，部分结论只能到 `VALID_BUT_WEAK`。
- Track18/20 是动作面 sanity，不是胜利证据。
- Track21/VBS gap 是 oracle 上界诊断，不是 DR 证明。
- Pilot25 需要 reconcile `progress.log`、final JSON/CSV、report，不能只信标题。

当前结论：

- DR-ALNS 不能作为 E2 救火工具。
- DR-ALNS 可以作为并行上限线和 future work 线。
- 若最终过门，可加入正文第二算法或扩展表。

### 5.2 M1 接口预留

独立 ALNS 必须支持策略注入：

- `SelectorPolicy`：选择 destroy/repair/q/acceptance/exploration。
- 默认：AlphaUCB / fixed q / HillClimbing or RRT。
- DR：block policy，每 N 步输出动作。
- 单测：假策略能改变算子序列，且不改变默认结果。

边界：

- M1 不训练 DR。
- M1 不混 x86 绝对成本。
- M1 只保证接口和 E2 主线不被焊死。

### 5.3 x86 DR PDCA

> **执行地点约束（Claude 2026-07-02 核查）**：Track17/18/19/20/21/Pilot25 的报告**不在 M1 主盘**（`grep` 只命中提到这些标签的规划文档，`solver/rl` 下无对应报告）。它们在 x86 `D:\ReSETP` 的 `dr-x86` 分支/机器上。因此 DR-G0~G4 **只能在 x86 执行**；M1 侧对 DR 的唯一动作是 §5.2 接口预留。M1 的 Codex 不要尝试在本盘"汇总 Track 报告"，会扑空。

DR-G0：证据整合（x86 only）

- Plan：汇总 Track17/18/19/20/21/Pilot25。
- Check：每条有 verdict、数据路径、当前 blocker。
- Act：无法定位的旧报告标 `STALE_OR_UNRECONCILED`。

DR-G1：Track19 合法比较修复

- 目的：分清 baseline unhealthy 与 main method weak。
- 验收：`HEALTHY` 或 `VALID_BUT_WEAK` 标签清楚；`HALT_100C_STILL_STARVED` 不得改写。

DR-G2：Track20 动作面 sanity

- 目的：确认 reserve capacity、commit/defer、vehicle preposition、information_cost 真的进入决策。
- 验收：动态 reward/action interface 有非零、可解释、可复现影响；若 `_dynamic_reward` 因缺少动态字段而近似无信号，只能标 `DYNAMIC_REWARD_SIGNAL_MISSING`，不能升级为 DR 成功。

DR-G3：Track21 winner root cause

- 目的：用 VBS gap 作为上界线索，定位 100c winner/fleet policy bug。
- 验收：`_next_vehicle_id`、`physical_vehicle_id`、`allow_new_route_repair` 等根因有明确 pass/fail。

DR-G4：Pilot25 endgame

- 目的：判断 learned-destroy / PPO 是否有真实突破。
- 验收标签只能是 `PASS_DR_BREAKTHROUGH`、`PARTIAL_WIN_NO_DR`、`HALT_BOTH`，不许新增暧昧成功词。

### 5.4 DR 入论文门槛

主算法门槛：

- DR 在同环境、同预算、同 referee 下显著胜独立 ALNS/AlphaUCB。
- baseline 健康。
- 多实例、多 seed 成立。
- 动作面解释成立。

第二算法/扩展表门槛：

- DR 未必全面胜，但在动态/碳/公平某类场景有稳定优势。
- 能解释为何优势出现。

future work 门槛：

- 有工程管线、动作面或离线信号，但未形成胜利证据。

禁止：

- 用 DR 的弱信号救 E2。
- 用 x86 绝对值与 M1 表混比。
- 把 VBS/oracle 上界写成 DR 结果。

---

## 6. 风险登记册

| 风险 | 当前等级 | 触发信号 | 应对 |
|---|---:|---|---|
| E2 同值平台不可解释 | 高 | GA/LNS/PSO/VNS 同 cost/EV share | E2-G0 一票否决 |
| 主 ALNS 不独立 | 高 | `from alns` / `Reference Algorithm` | E2-G1 剥离 |
| 场景口径漂移 / override 污染正式 E2 | 高 | 正式跑仍用 280kWh 内存 override 冒充默认，或 `prices.py` / TeX / HANDOFF 不一致 | C2 场景合规核对；不重开 280 主场景 |
| 动态需求割裂 | 高 | T9 只报动态成本/累计碳 | E7 三交互门槛 |
| 对手单薄 | 高 | 只比 SA 或 4 个弱 baseline | G3 补全基线 |
| 固定 eval 与等墙钟混写 | 高 | status OK 但 actual_evals<16000 | 双账本 |
| DR 线过度包装 | 高 | `VALID_BUT_WEAK` 写成 win | DR 入论文门槛 |
| AppleDouble 污染证据链 | 高（已实锤，非隐患） | `._*` 已进入 `artifact_hashes.json`（含 C1 审计目标 `long_same_instance_v2_data`）；repo 有 14394 个 `._*` 文件；`.git/objects/pack` 有 `._pack-*` | C0 先清理再重算 hash；受污染 hash 标 `HASH_CONTAMINATED_APPLEDOUBLE`，不作正式证据 |
| 旧 471 数字污染新场景 | 中 | 表图混旧参数 | Phase 5 前清单 |
| carbon 算子无增益 | 中 | carbon≈ablation | E2 主变体预注册 |

---

## 7. Codex 任务队列

### C0 仓库卫生与 PRD 合并

目标：让主仓看到 v2 规划并清楚当前脏状态。

步骤：

1. 记录主工作区和 Claude worktree status。
2. 将本文档、memory、HANDOFF 变更落盘。
3. 单独清理 AppleDouble，或先写清理清单等用户确认。
4. 检查现有 `artifact_hashes.json` 是否包含 `._*`，污染者标 `HASH_CONTAMINATED_APPLEDOUBLE`。
5. 不跑实验。

验收：

- `git status` 中 docs 改动与实验数据改动可区分。
- 不改 solver 语义。
- 正式候选数据目录均有四件套：`metadata.json`、`raw_runs.csv`、`decision.json`、干净 `artifact_hashes.json`。

### C1 E2-G0 5174 平台审计

目标：解释同值平台。

状态：2026-07-02 已完成，未过门。报告 `baselines/e2_alns/e2_g0_same_value_platform_audit_20260702.md`；数据 `baselines/e2_alns/e2_g0_same_value_platform_audit_data/summary.json`；verdict=`ARTIFICIAL_HOMOGENIZATION`。禁止继续把 `5174 vs 3569-3653` 写成健康 baseline 下的 30% 正式领先。

执行提示词：`docs/handoff/codex_prompts/20260702_c1_e2_g0_plateau_5174_audit.md`。

输入：

- `ev_heavy_findability_gate_long_same_instance_v2_data/raw_runs.csv`
- checkpoints
- `metaheuristic_baselines.py`

步骤：

1. 逐算法解析 `history_json`。
2. 比较 best solution signature、route、charging actions。
3. 查 `_vehicle_type_mutation`、`_order_to_solution`、charging repair、normalize 是否形成共同 deterministic channel。
4. 写 `plateau_5174_audit.md/json`。

验收：

- verdict 三选一：`HEALTHY_SHARED_LOCAL_OPTIMUM` / `ARTIFICIAL_HOMOGENIZATION` / `BASELINE_HEALTH_UNRESOLVED`。
- 实际验收：`ARTIFICIAL_HOMOGENIZATION`。后续任务改为 C1-R1/C1-R2 整改与重审，不启动 C5/C6。

### C2 E2-G2 场景合规包（不是重新裁决）

场景口径 user 06-26 已拍板、不重开：Goeke80 默认、280kWh 只作诊断（见 Phase 2 已拍板裁决 + 已关闭路线台账第 7 条）。本包只做合规落实：

步骤：

1. 盘点代码/runner 中所有 280 内存 override 使用点，确认正式 E2 入口用 `prices.py` 默认参数（Goeke80）、不用 override 冒充默认。
2. 核对 `prices.py` 注释、TeX 参数表、HANDOFF 三处口径一致（Goeke80 默认 + 80/280 历史痕迹保留）；发现漂移只登记并报 user，不擅自改 TeX 主张。
3. 280kWh 诊断产物（09y 三班混合泛化、5174 平台链）在论文中只进"诊断/机制"叙述位，不进主场景表图。

验收：

- 正式 E2 运行配置 = 默认 `prices.py`，零 override。
- 三处事实源口径一致，或差异已登记报 user。
- 全程不需要 user 重新拍板场景。

### C3 E2-G1 独立 ALNS 剥离

目标：主算法脱离 N-Wouda 文件依赖。

步骤：

1. 新建 `resetp_alns/`。
2. 迁移最小骨架。
3. 保持默认结果 parity。
4. 加 grep 和锚测试。

验收：

- 主算法路径零开源 import。
- 锚复现。

### C4 E2-G3 基线与预算协议实现

目标：让正式比较对手和预算不被审稿击穿。

步骤：

1. 固化双账本输出字段。
2. 增加 baseline health gate。
3. 补 SA/ACO/GA-VNS/GWO/IWD 等或改 TeX 承诺。

验收：

- 每个 baseline 都有 liveness、health、actual evals。

### C5 E2-G4 三班稳定性复核

目标：验证单实例优势是否泛化。

步骤：

1. 三班 100/150/200 × -01/-02/-03 × seeds>=3。
2. 独立 ALNS + baseline。
3. 输出 paired summary 和机制指标。

验收：

- 方向一致、gap>=10%，或诚实降级。

### C6 E2-G5 正式 T3

目标：论文正式算法表。

步骤：

1. 全 69 或批准子集。
2. seeds>=5。
3. 双账本。
4. T3/F2/appendix 生成。

验收：

- `decision.json` 为正式通过，或明确 `HALT_FORMAL_E2`。

### DR-C1 DR 证据整合（x86 only）

目标：把 x86 DR 线从散点变成 gate 表。

输入：Track17/18/19/20/21/Pilot25 报告（在 x86 `dr-x86`，不在 M1 主盘）。

验收：每条线有 verdict、blocker、下一步、是否可入论文。

（任务代号用 `DR-C1`/`DR-C2`/`E7-C1`，避免与圆桌决策标签 D1-D5 混淆。）

### DR-C2 DR 接口预留（M1 侧最小实现）

目标：独立 ALNS 提供策略注入点。

验收：假策略单测通过，默认结果不变。

### E7-C1 E7 动态三交互设计

目标：正式跑 E7 前先设计指标。

验收：`run_rolling_reoptimization` 目标审计 + 三交互指标表。

---

## 8. 失败史如何变成未来故事

09c-09y 不是浪费，它们给论文和答辩留下了方法学资产：

- 09c/09d：证明采集成本与 checkpoint 回收必须制度化。
- 09e-09h：证明参数故事必须来源约束，不能靠调参救算法。
- 09k-09q：证明电池单参数不足，运营约束与车辆/充电结构会支配混合性。
- 09r/09s：容量和实体车辆多趟语义是模型翻译错误，不是算法问题。
- 09x：碳算子弱，不能把“算子运行了”写成“碳感知有效”。
- 09y：机制存在不等于算法赢，`MECHANISM_BUT_TIE` 必须保留。
- baseline liveness：赢不会动的 baseline 不算赢。

这些内容不一定进正文，但必须进入 HANDOFF、appendix 候选和答辩材料。

**叙事三分置（战略主编票）**：正文只留"结晶"（三个建模级修正的终态作为模型定义如实写：`m^g/m^e` 实体车硬上限 + 多趟 `CV1#T1` 语义进 §2/§3，`Q=3650` Goeke 口径进参数表；至多一句"实现经过多轮语义审计"），失败链留作审稿回复"弹药"，全史留 HANDOFF/reports。后续应新建一份 `docs/handoff/review_rebuttal_ammunition_index.md`（Claude 写文档职责内）：预先把常见质疑映射到证据——"基线是否健康"→liveness 修复 + C1 审计链；"参数为何 280"→09h/09l/09y 时间线（参数选择先于且独立于算法胜负）；"多趟语义依据"→`fleet_hard_cap` 证据文档。

---

## 9. 下一步裁决

短期最小返工顺序：

1. C0：本 v2 入主线、仓库卫生、事实冻结。
2. C1：`5174.345` 平台审计。
3. C2：Goeke80/280kWh 场景合规核对（06-26 拍板的落实，无需 user 重新决策）。
4. C3：ALNS 独立化。
5. C4：预算协议与 baseline health gate。
6. C5：三班稳定性复核。
7. C6：正式 E2。
8. E7-C1：E7 三交互设计。
9. Phase 5：正式 E1-E7 重跑与论文重灌。

C1、C2、C3 三者的依赖关系：C1（G0 审计）是硬前置，必须先过。C2（场景合规核对，纯文档/配置核对，无需 user 决策）与 C3（ALNS 独立化剥离，纯代码）**相互独立、可并行**——C3 的锚集已设计成不依赖 C2（见 G1 多路径锚集）。两者都必须在 C5/C6 正式跑之前完成，但彼此不阻塞，不强制串行。

若 C1 失败，不做 C5/C6。若 C2 合规核对未过（正式跑仍依赖 override 冒充默认或三处口径漂移未登记），不做正式重跑。若 C3 漂移，不做正式 T3。若 DR 未过门，只写 future work。
