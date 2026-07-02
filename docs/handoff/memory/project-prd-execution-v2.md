---
name: project-prd-execution-v2
description: 全项目 PRD 与施工图 v2；用于 Codex 执行 ReSETP 宏观规划、E2 重点摸排、E1-E7 PDCA、DR-ALNS 接入、记录制度和风险门槛。
metadata:
  node_type: memory
  type: project
  updated: 2026-07-02
---

2026-07-02 新增 `docs/handoff/project_prd_execution_map_v2_20260702.md`。这是全项目级 PRD/施工图，不只是 E2 PRD。

同日新增强制启动入口 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`，并已挂入 `AGENTS.md`、`CLAUDE.md`、`docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md`、`docs/handoff/codex_prompts/README.md`。Codex/Claude 每轮非平凡任务必须先读该入口和其清单，读完前不得动手。

核心裁决：E2 是关键路径。`5174.345121253789` 同值平台 C1 审计已完成，verdict=`ARTIFICIAL_HOMOGENIZATION`，所以当前 E2-G0 未过门；C1-R2 探针已完成但只到 `PARTIAL_OR_WEAK_SUPPORT`（H2 确认、H1 未确认），所以后续不是扩跑，而是做 C1-R1，把共享车型翻转通道从 baseline 算法成绩中剥离/单独记账，并加 operator provenance gate，同时重新设计解码/表达能力审计后再重审 G0。ALNS 独立化、场景口径合规核对（06-26 拍板的落实，非重新裁决）、基线补全、多实例复核、正式 T3 仍在后面，但 G4/G5 必须继续冻结。

宏观纪律：`HANDOFF.md` 是单一事实源；原始 CSV/JSON 优先于报告散文；禁止为救结果改 `cost.py`/`check.py`/`evaluation.py`；参数变更必须四同步；固定 eval 与等墙钟必须双账本；DR-ALNS 不得污染 E2，只有过同环境同预算健康 baseline 门槛后才能进正文。

2026-07-02 圆桌裁决补充：DR-ALNS 目前只能作为可插拔策略层和 x86 并行研发线；M1 正式 E2 默认关闭 DR checkpoint。若 `_dynamic_reward` 缺少真实动态字段，只能标 `DYNAMIC_REWARD_SIGNAL_MISSING`。AppleDouble `._*` 若进入 `artifact_hashes.json`，该 hash 必须标 `HASH_CONTAMINATED_APPLEDOUBLE` 并清理重算。

已完成 Codex C1 审计：报告 `baselines/e2_alns/e2_g0_same_value_platform_audit_20260702.md`，数据 `baselines/e2_alns/e2_g0_same_value_platform_audit_data/summary.json`。不要再把 `docs/handoff/codex_prompts/20260702_c1_e2_g0_plateau_5174_audit.md` 当待发任务；它已经执行完。

E7 动态需求必须保留三交互门槛：动态×协同、动态×公平、动态×时变碳。若 `min_fairness_ratio=off` 或无 EV 充电，必须诚实降级。

2026-07-02 第二次纠偏（user 指出 Claude 重提已试尽路线）：v2 已补**已关闭路线台账**（Phase 2 停止条件下）：①调电池凑混合（09l 关门）；②电池档救 vanilla ALNS（09v/09w 无分离）；③车队上限直接当混合故事（09n HALT；09s 正确语义落地后 Goeke80 EV share 仍 ~0.057，上限造不出混合）；④"280+三班+上限出混合"小验证已跑过=09y Stage A `THREESHIFT_MIXED_GENERALIZES`（8/9 过），勿重跑；⑤小算例/低预算快跑分胜负系统性产出平局（09s/t/u/v/w/y 六连平），判别力不足；⑥手写碳算子（09x WEAK + 09y carbon≈ablation）；⑦280 正式化主场景（user 06-26 否决）。C2 从"场景拍板包"改为"场景合规包"，无需 user 重新决策。算法主线出口只剩：C1 裁决 5174 平台真伪 → 真则 ALNS 领先成立 / 假则按 MASTER 预案诚实降级或转 DR-ALNS。

2026-07-02 Claude 核验补丁（只读核查 + 文档加固，未跑 solver）：GA under-eval 确已修（主盘 `16000/16000 OK`）；同值平台 `5174.345121253789` 是**种子不变**的（GA/LNS/PSO/VNS 跨 seed 零方差=同质化强嫌疑，已进 C1 硬判据）；AppleDouble 污染实锤（`._` 已进多个 `artifact_hashes.json` 含 C1 审计目标，repo 14394 个 `._*`，风险升"高"）；DR Track17-25 报告不在 M1 主盘=DR-G0~G4 为 x86-only，M1 只做接口预留。G1 锚集扩多路径；C2/C3 可并行；补最小充分实验集纪律 + 审稿弹药索引。

2026-07-02 Codex 复核 pasted Claude 二次纠偏：主盘已正确落入已关闭路线台账与 C2 场景合规包；又清理三处残留旧口径，防止下轮 agent 重开场景：E2-G2 Act 改为 `SCENARIO_COMPLIANCE_BLOCKED`，Phase6 不再写"选择 modern battery"，风险登记改为"场景口径漂移 / override 污染正式 E2"。当前唯一待发任务仍是 C1 同值平台审计。

2026-07-02 Codex 执行 C1/E2-G0 同值平台审计：新增 `baselines/e2_alns/plateau_5174_audit.py`、报告 `baselines/e2_alns/e2_g0_same_value_platform_audit_20260702.md`、数据目录 `baselines/e2_alns/e2_g0_same_value_platform_audit_data/`。结论：8 条 baseline 行全部 `16000/16000 OK`，checkpoint 用 `B=280kWh, carbon=0.05034` 回放均零违约且 cost/signature 匹配；但 GA/LNS/PSO/VNS 两 seed 的 best cost/signature/EV share 完全同值，所有 best 更新均在 eval≤42 由共享车型翻转通道完成，之后至少 15958 eval 无 native best 更新。verdict=`ARTIFICIAL_HOMOGENIZATION`，附加 `HASH_CONTAMINATED_APPLEDOUBLE`（输入目录 51 个 `._*` 且旧 hash 污染）和 `EV_MAXIMAL_REFERENCE_NOT_BOUND`（`closed_gap_fraction>1` 因 EV-maximal reference 非下界）。单实例 30% 不得写成健康 baseline 下正式领先；G4/G5 继续冻结。

2026-07-02 Claude 根因分析（只读代码，INFERENCE 待 C1-R2 探针证实）：原生搜索 15958 eval 零改进的三机制——①baseline `_alns_neighbor` 强制 `SETP_ALNS_CRUSH_TRUE_REPAIR=0`（`metaheuristic_baselines.py:1397-1412`），插入评分退化为纯距离增量（`repair_scoring.py:31-32`），E2 ALNS 用 =1 成本感知修复；280 EV-heavy 下距离代理失效。②共享解码器天花板：贪心尾插构路+CV-only 可行测+EV 只是整条重标注+check 失败静默回退全油解（`805-835/880-923`），表达不了 ALNS 的多趟/充电结构。③翻转通道闭包不动点与顺序无关→跨 seed/算法逐位同值。21 天僵局解释：8 基线共享一套脚手架,Goeke80 下翻转死→全员平局被误读为"场景无张力"→电池/约束绕路；"真在搜索"硬门禁(跨seed std>0)从未执行。下一步=C1-R2 最小探针（LNS TRUE_REPAIR 0/1 A/B + 解码回退率计量），证实后再做 C1-R1 修复。

2026-07-02 Codex 执行 C1-R2 原生通道死因定位探针（PROBE / 非正式 T3）：runner commit `b30c9f2eb9972b13e86a31a2d26000f26e7f23a8`，报告 `baselines/e2_alns/native_channel_autopsy.md`，数据 `baselines/e2_alns/native_channel_autopsy_data/`。环境 `/opt/anaconda3/bin/python3.13` + numpy `2.3.5` + `PYTHONHASHSEED=0`，280kWh 只用内存 override；`raw_runs.csv` 8004 rows、`decode_events.csv` 5214 rows、4/4 planned runs OK、0 collection failures，hash 清单干净。判决 `PARTIAL_OR_WEAK_SUPPORT`：H1 未确认，因为 TRUE_REPAIR=0 与 TRUE_REPAIR=1 两个 LNS A/B 都没有 native best update，best 都停在 `5174.345121253789`；H2 确认，因为 GA/PSO 排列解码候选低于 `5174.345121253789` 的比例均为 0，但 fallback rate 也均为 0，所以不要把 H2 写成“高回退率”证据。翻转闭包 seed1/seed2/确定性枚举均等于 5174、accepted flips=14、EV share=0.6818。结论边界：未达到 `NATIVE_CHANNEL_DEAD_CONFIRMED`，也未达到 `HYPOTHESES_REFUTED`；C1-R1 不能押注“只打开 TRUE_REPAIR”。

2026-07-02 Claude 解读 C1-R2 数据（根因链闭合,详见 HANDOFF 同日条目）：①解码器构造级 bug（FACT 可证明）：`_append_customer_to_cached_plan` 拿候选路线**绝对总距离**比较"追加 vs 新开单客路线",三角不等式⇒追加永不严格更优⇒解码器只产一客一车解（探针实证 LNS/PSO 原生候选 route_count 100%=150、cost≈21000;平台解 22 路线=5174）；GA/PSO/VNS/ACO/GWO/IWD 排列搜索+LNS 兜底全被锁死。②`_apply_strong_alns_destroy_repair` 桥在平台解上 ~100% 失效（TRUE_REPAIR 0/1 候选统计逐位同=flag 在死点下游）,微观死因待 C1-R3 直方图（`repair_removed_customers` None vs 违约类型）。③唯一活通道=翻转闭包→同值平台。C1-R2 的 `PARTIAL_OR_WEAK_SUPPORT` 全解释:H1 不可测、H2 真机制=解码器 bug 而非回退率。修复令 R1a(解码器边际增量修复)→R1b(桥死因直方图)→R1c(翻转通道共同预处理+双通道记账)→R1d(liveness 硬门禁自动化)。历史"GA/PSO/VNS 在搜索"结论全部无效。

关联：[[dynamic-demand-integration]] [[baseline-algorithm-catalog]] [[alns-crush-root-cause]] [[project-plan-overview]] [[e2-prd-gates]]
