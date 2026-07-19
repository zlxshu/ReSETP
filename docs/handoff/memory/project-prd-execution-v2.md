---
name: project-prd-execution-v2
description: 全项目 PRD 与施工图 v2；用于 Codex 执行 ReSETP 宏观规划、E2 重点摸排、E1-E7 PDCA、DR-ALNS 接入、记录制度和风险门槛。
metadata:
  node_type: memory
  type: project
  updated: 2026-07-19
---

E7正式结果终验

2026-07-18 阶段二 G1 独立输入执行完成：静态 China81 输入、九城设施与中国成本情景、
统计阈值、六张区域 CV/EV 本地路网、1,578,948 个有向同路线三矩阵和 81 实例零搜索审计
全部闭合。权威矩阵 v9 不可达为 0，无欧氏/对称/直线回退；最终汇合包 81/81 通过。
机器判=`PASS_CHINA81_G1_INDEPENDENT_DATA_FROZEN__G1_PHYSICAL_SEARCH_ACCEPTANCE_HELD`。
唯一开放项是 `G1-FREEZE-MERGE`；正式 SOC、非线性补能、算法验收、China81 胜负和
E1--E7 仍等待 G1 冻结与阶段一统一。

2026-07-18 阶段一非算法最终收口：独立复核撤销旧“小路网4/4即完成”判断后，MC-005候选A已写入合同并重建81份/5805行权威位置分配，27格内三复本身份零重叠；九个普通设施形成WGS84情景道路接入点并在五份冻结PBF上完成CV/EV 18/18最小路线；OSRM 26.7.3完整功能门18/18覆盖高宽长重、hgv、单行、不可达、方向性距离/时间、注释和`Σ(v²d)`。用户批准MC-004方法并明确暂时不进入阶段二；最终独立审计判`PASS_PHASE1_NONALGORITHM_HANDOFF_READY`，待批0、错误0、搜索评价0。算法优化、全矩阵、正式China81实例和正式搜索均未启动。

2026-07-18 阶段一并行历史状态（已被上方后续授权与执行终局覆盖）：六线当时均推进到证据边界，总状态为`PHASE1_PARTIAL_COMPLETE_BLOCKED__STAGE2_NOT_STARTED`。G1a因RC三对零触发而停止完整G1；MC-002算力/功效和重庆池27格门闭合；覆盖九城的固定OSM 5/5验签。九主场0/9、两备选0/2、本地router和货运profile当时继续HALT；六项统计终裁、备选不替换决定、11点人工输入与MC-004重批当时未完成。详见`docs/handoff/phase1_parallel_status_and_user_gate_20260718.md`。

2026-07-18 G1阶段一最低成本筛选：SISR因R类三种子实际调用为0而淘汰；真正SWAP*通过独立活性门和当前源码C类统一预算接入门。追加四实例×三共同种子×两臂×B400的G1a，24/24任务和12/12共同起点全部闭合，平均改善`0.003918%`等数值门通过，但RC三对均零触发，未满足C/R/RC活性覆盖，判`STOP_TRUE_SWAPSTAR_BEFORE_FULL_G1`。完整G1共115,200次评价没有启动，本候选本轮关闭。后续开发严格按正式门暴露的瓶颈选择：路线数/固定成本→受控路线消除与有限深度ejection chain；同路线距离→granular局部搜索；车型、非线性补能、碳价、公平和动态机制→自有复杂模型开发集。详见`docs/handoff/e2_alns_g1_stage1_closeout_20260718.md`。

2026-07-18 ALNS完整方案评价预算G0闭合：新增统一评分边界与候选调用前硬停止，candidate/reference/repair-delta三账分离；局部搜索、RVND、scan、strong bridge、global repack、fleet-charge及strict E3路径纳入预算，碳特征与repair fallback隐藏完整评分移除。`baselines/e2_alns/e2_alns_budget_g0_20260718/`判`PASS_ALNS_BUDGET_G0_COMPLETE`，静态0阻断/0未分类、186项行为回归全过，0/1/2/3/7预算无target+1。旧E2预算HALT证据保持；只放行Homberger G1开发，旧胜负证据不得复活或与新版本拼接。

2026-07-02 新增 `docs/handoff/project_prd_execution_map_v2_20260702.md`。这是全项目级 PRD/施工图，不只是 E2 PRD。

2026-07-11早期主线纠偏（历史）：**E2算法性能闭合优先**。30次staged ALNS-LNS hybrid/LNS稳定性门完成前，电池容量/车型结构/充电活跃度复核和动态低碳均曾标记`DEFERRED / BLOCKED_BY_E2_ALGORITHM_FOUNDATION`。该状态已被同日后续E2收口和统一遗留任务计划覆盖；当前顺序见`docs/handoff/e2_legacy_items_1_6_9_execution_plan_20260711.md`，旧`m1_e2_deferred_tasks_20260711.md`只作历史挂账登记。

2026-07-11 E2全量最终收口：用户后续授权280 kWh作为投稿正面主场景，覆盖早期Goeke80唯一主场景口径；80 kWh保留独立稳健性。L-main v3九档×seeds1--5×6证据算法×4000评价共270行全部OK、满预算、零违规。正式方案总benchmark成本173139.284391，第二名LNS 185862.880926，总量领先6.845690%；配对25胜5平15负，平均/中位优势2.829832%/0.842029%，bootstrap均值95%区间0.982%--4.894%，平均名次第一且运行最快。碳消融45/45同路线同电量，40组实际移动并降碳。verdict=`E2_FULL_BENCHMARK_LEAD_SUPPORTED`；允许总量>5%主张，禁止每实例/配对均>5%主张。证据 `baselines/e2_alns/e2_submission_20260711/carbon_280/`，说明 `docs/handoff/e2_full_closeout_20260711.md`。E2算法冻结，不再rescue。

2026-07-11 M1项目5动态地基闭合：没有合并整个`dr-x86`，只把已经验证的动态实况合同迁回`codex/reporting-pipeline`。正常滚动和静态后见对照统一使用项目内独立`setp_solver.algorithms.resetp_alns`，动态源码对`run_alns_wouda`为零引用；车辆实时位置/在途进度、时间、剩余载重、SOC、未结束充电、物理车辆占用和锁定客户原车原序均进入规划或检查，收尾不再重启求解器重建全部剩余路线。52项动态/检查测试和1项最终违规停机测试通过；修改后重新回放冻结E2 270行仍全部零违规且成本一致。代码`96cbcbf7`，证据`baselines/e7_dynamic/m1_dynamic_truth_gate_20260711/`，verdict=`M1_DYNAMIC_LIVE_STATE_CONTRACT_SUPPORTED`。该判决只关闭正确性地基，不等于动态优化有效；“立即处理对允许合理延迟”的同事件流低碳机制门仍受投稿统一合同阻塞。

2026-07-11 E1--E7投稿合同机器闸门：只读源码确认旧E4入口仍是16000评价、fairness off和碳价×线性配额网格，不能冒充新的精细碳正式消融。新增`solver/src/setp_solver/search/submission_contract.py`与4项测试，要求正式提交合同必须有用户冻结状态、固定客户归属文件和hash、完整模型搜索期公平、binding-aware theta规则，以及碳配额仅作accounting的主张边界。`baselines/contract_audit/submission_contract_candidate_20260711/`基于L-main v3生成九档1425条最近车场归属和推荐合同草案；结构有效但故意拒绝正式开跑，verdict=`BLOCK_SUBMISSION_RUNS_PENDING_USER_CONFIRMATION`。用户确认前继续禁止项目4/5及E4--E7正式搜索。

2026-07-11 项目9零搜索长预算预案：从冻结E2的90条hybrid/LNS 4000评价真实耗时计算，不启动任何16000运行。代表门固定20c seed3、50c seed5、150c seed3三个旧负例和200c seed4最慢强胜保护组，共8任务；顺序线性/保守耗时3.376/4.220小时。若晋级九档五种子两算法90任务，顺序线性/保守估计21.902/27.378小时。预注册过门要求满16000、零违规、hash完整、四组汇总不输LNS、三负例至少两组改善自身4000成本且200c强胜不丢。证据`baselines/e2_alns/e2_16000_preflight_plan_20260711/`，verdict=`PROJECT9_PLANNED_NOT_AUTHORIZED`；项目4/5/6和投稿合同完成前不得启动。

2026-07-11 投稿合同文献复核：Soriano et al. 2022的MDVRP-PF以成本—公平双目标和epsilon约束构造前沿，其他协同多中心VRP研究常用Shapley或联盟收益分配；定向检索未发现95 GBP/跨场客户是行业统一主值。推荐继续采用0完全共享机制基线+10/25/50/95摩擦敏感性，非零论文主值需另有来源。EV时段充电研究把充电时刻/时长作为显式决策，支持同路线同电量择时消融。引用集中在`docs/handoff/e1_e7_submission_contract_decision_20260711.md`。

2026-07-11 用户在保留上述冻结证据的前提下重新打开旧遗留编号1--6、9，要求逐项做一次有界尝试。当前顺序改为：15负恢复/扩大领先→80 kWh→完整碳感知搜索→动态需求低碳→电池容量与车型结构→最后16000评价。只允许阶段串行、批内CPU并行。15负审计为平均落后2.270%、3组超过5%、11组路线更多、9组最佳停在中间强搜索阶段；首候选把3200强搜索拆成两个独立1600盆地并从当前最好解重启，总预算不变。首轮9组×旧/重启/LNS×1600虽27/27满预算零违规，但误用`introduce_ev=False`起点且LNS关闭正式共同预处理，与冻结E2合同不一致，判`RESTART_SHORT_GATE_INVALID_START_CONTRACT`并保留原始证据。runner改为`make_shared_initial_solution`+`common_flip_preprocess=True`后只纠正重跑相同27次；通过后仍必须用未见种子验证。合同见`docs/handoff/e2_legacy_items_1_6_9_execution_plan_20260711.md`，证据目录`baselines/e2_alns/e2_loss_recovery_20260711/`。

2026-07-11 正式起点纠正门完成并判退重启候选：27/27满1600、零违规、出处/hash齐全；重启相对旧staged全部9组平均+0.410%、6个开发负例+0.236%、guard最差0%，但同预算负例转不输LNS为0，150c seed3反而-9.737%，verdict=`RESTART_SHORT_GATE_REJECTED`。阶段分解显示150c连续800强搜索可改善，而拆成两个400后两段均无改善，故停止重启参数路线。下一候选不扩大矩阵，只在同总预算内把中段从“借LNS修复后端”改成“真实LNS策略阶段”，补齐staged ALNS-LNS hybrid的实现身份。

2026-07-11 true-LNS-middle短门完成：27/27满1600、零违规，验证器确认行数、预算、解、hash和执行提交`5be12db7`。相对旧staged全部9组平均改善1.536%、6个开发负例平均改善2.506%，100c seed2由负转正，50c seed5和150c seed3差距明显缩小；但只转回1个负例，未达预注册2个，guard最差-1.209%，verdict=`TRUE_LNS_MIDDLE_SHORT_GATE_REJECTED`。机制上，1600门使用固定`400+800+400`，LNS核心只占50%，而正式4000身份为`400+3200+400`、核心占80%。下一次唯一有界候选保持总预算和原晋级线不变，只把短门缩放为10%/80%/10%；仍不过则关闭true-LNS路线。

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

2026-07-02 Codex 执行 C1-R1a/R3 解码器边际增量修复 + 桥死因直方图（PROBE / 非正式 T3）：用户/Codex 拍板边界已落盘：**不改建模，只修 baseline decoder 实现偏差；固定成本仍按 `£/班次 / 每趟派遣` 口径，不改每实体车固定费，不引入 fleet-size-and-mix**。代码提交 `ee1f7bfb1ac8466322f671d453e20359335e2e63` 只改 `metaheuristic_baselines.py` 的 `_append_customer_to_cached_plan` 比较口径（边际公里成本 vs 新路线公里成本+`vehicle_fixed_cost`），新增 `solver/tests/test_decoder_marginal_repair.py` 和 `baselines/e2_alns/decoder_fix_validation.py`；未改 `cost.py`/`check.py`/`evaluation.py`/`prices.py` 默认值/TeX/ALNS 主路径。回归 `18 passed, 1 skipped`。产物 `baselines/e2_alns/decoder_fix_validation.md` 与 `decoder_fix_validation_data/`，metadata HEAD=`ee1f7bfb1ac8466322f671d453e20359335e2e63`，环境 `/opt/anaconda3/bin/python3.13` + numpy `2.3.5`，280kWh 只用内存 override。判决 `DECODER_FIXED_AND_BRIDGE_CAUSE_LOCATED`：修复前 GA/PSO decode route_count 恒 150、cost≈21000；修复后 decode rows 2496，route_count min/p50/max=`21/25/33`，unique route counts=13，decoded cost min=`5158.94347036807`、p50=`7296.815044758418`，`decoded_cost < 5174` 为 1/2496。桥尸检 200/200 为 `REPAIR_NONE`，15 个 destroy×repair 组合 dominant bucket 全 `REPAIR_NONE`、feasible/changed 均 0。结论只说明 baseline health：decoder 已能产多客户路线候选；strong ALNS bridge 死于 `repair_removed_customers(..., _ThinPolicy)` 返回 None。桥修复、翻转分账、liveness/operator provenance gate 仍需后续拍板；G4/G5 继续冻结，不得写算法胜负。

2026-07-02 Codex 执行 C3 / E2-G1 独立 ALNS 运行时剥离：本步只做等价剥离，不修 bridge、不调参、不改建模、不写算法胜负。代码提交 `b9663c6ab9d457dae33d60b63402f84a0554468d` 新增 `setp_solver.search.resetp_alns` 最小后端（N-Wouda/alns 7.0.0 MIT 来源说明；仅迁 `Outcome`、`HillClimbing`、`RecordToRecordTravel`、`SimulatedAnnealing`、`AlphaUCB`、`update()`），`alns_wouda.py`/`winner_operators.py` 主路径不再导入 `alns` 或注入 `Reference Algorithm/ALNS-7.0.0@N-Wouda`；`run_alns_wouda` 名称仅为兼容入口。`Reference Algorithm/ALNS-7.0.0@N-Wouda` 未改。新增 `solver/tests/test_resetp_alns_independence.py`，回归 `17 passed, 1 skipped`，主路径 grep gate 零命中，protected-file check 对 `cost.py/check.py/evaluation.py/prices.py/paper_main.tex/Reference Algorithm/ALNS-7.0.0@N-Wouda` 为空。产物 `baselines/e2_alns/alns_independence_migration_data/`，verdict=`ALNS_INDEPENDENCE_CONFIRMED`：pre `b6cf9b902f85d3f614704479161b25a358a70a5c` vs post `b9663c6ab9d457dae33d60b63402f84a0554468d`，Goeke80 `100-01-24h` seed2 cost/hash 一致（cost `2677.7953638343815`，旧期待 `4779.053444002934` 已是 current HEAD 前置陈旧锚）；280 诊断锚 `e2-threeshift-150c-01` seed1、B=280/carbon=0.05034、eval 2000 cost/hash 一致（cost `3561.080964207054`）。raw history/timing hash 差异仅来自 wall-clock/timing 统计，去 timing 的 operator counts 一致。后续 C1 bridge/liveness/E2 调试统一基于 independent backend；若后续 parity 漂移，按 `HALT_ALNS_PARITY_DRIFT` 冻结回查。

2026-07-02 Codex 执行 C1-R1b destroy/repair 桥侧修复（baseline health整改 / 非正式 T3）：代码提交 `dda5e6d1d008ec4ccd8301db3e21ad88ae76fbbf` 只改 `solver/src/setp_solver/search/candidates.py` 的 `_apply_strong_alns_destroy_repair` 桥侧 policy（从无限 `_ThinPolicy(max_cv=max_ev=1e9)` 改为实例真实 `num_cv/num_ev`，不改 `feasible_repair.py`、独立 ALNS 后端、ALNS 主路径、`cost.py`/`check.py`/`evaluation.py`/`prices.py` 默认值或 TeX），新增 `solver/tests/test_bridge_side_repair.py` 和 `baselines/e2_alns/bridge_fix_validation.py`。产物 `baselines/e2_alns/bridge_fix_validation_data/`，metadata HEAD=`dda5e6d1d008ec4ccd8301db3e21ad88ae76fbbf`，环境 `/opt/anaconda3/bin/python3.13` + numpy `2.3.5` + `PYTHONHASHSEED=0`，280kWh 只用内存 override。判决 `BRIDGE_FIXED`：Phase A 证实旧桥无限 policy 为 `FINAL_CHECK_FAILED` 200/200；ALNS 等价真实 fleet caps 下同批 trace 为 `REPAIRED_FEASIBLE` 57/200、`FALLBACK_FEASIBLE` 3/200、`INSERT_LOOP_EXHAUSTED` 140/200。D1 LNS 2000 eval 闭合，原生可行 20-40 路线候选 `1314` 个、route_count 21-33、native best updates=`19`、best cost=`3820.476792624678`（只说明 baseline 活性，不写算法胜负）。D2 独立 ALNS 锚点零漂：Goeke80 当前 Q3650 seed2 `2677.7953638343815`、280 三班 seed1 `3561.080964207054` 均逐位一致。D4 Q1600 legacy 复核跑出 `5480.399324501256`，未复现旧 `4878.331796187524`，标 `LEGACY_ANCHOR_UNEXPLAINED`，不作为桥修复失败。回归 `31 passed, 1 skipped`，protected-file check 与 `git diff --check` 均干净，artifact hash 排除 `._*`/`__pycache__`/`.pytest_cache`。

2026-07-03 Codex 执行 E2-G0 收官工程（baseline health / G0 gate，非正式 T3）：产物 `baselines/e2_alns/e2_g0_reaudit_20260702/`，runner `baselines/e2_alns/e2_g0_reaudit.py`，plateau 审计脚本支持新 G0 目录。C0 清理非 `.git` AppleDouble/cache 并重生涉证 hash；common flip preprocess 与 channel 记账已落地，liveness 字段包括 `native_best_updates`、`route_count_unique`、`common_lift/native_lift/flip_lift`；触碰 `metaheuristic_baselines.py` 后独立 ALNS 锚 `2677.7953638343815` / `3561.080964207054` 零漂。TRUE_REPAIR A/B 支持对齐：GA best `4629.8754212957→4596.373111001051`、native updates `1→2`；LNS best `4289.832864688266→3788.7364537265853`、updates `5→24`，吞吐可承受，因此 baseline 不再强制 `SETP_ALNS_CRUSH_TRUE_REPAIR=0`。G0 重审 15/15 rows `OK` 且 `16000/16000`；旧 5174 精确同质化未复发（12 条 baseline best cost/signature 全不同，identity suspect=0），但 PSO 三个 seed 与 VNS seed2 均 `NO_NATIVE_BEST_UPDATE`，所以 verdict=`G0_RESIDUAL_HOMOGENIZATION`，不是通过。场景合规 OK：默认 `B=80/Q=3650/carbon=0.05034`，`paper_main.tex` 口径一致，旧 generated table 的 280 命中只登记不改。旧锚考古用 `df608660` 旧代码+当前同名 bundle 得到 `4779.053444002934`，未复现 `4878.331796187524`，标 `LEGACY_ANCHOR_STILL_UNEXPLAINED`。G4/G5 继续冻结；后续只可针对 PSO/VNS liveness 失败做有界修复/降级裁决，不得扩跑或写正式算法胜负。

2026-07-03 Codex 执行 E2-G0 v2 起点修正重跑 + 锚谱系收尾（baseline health / G0 gate，非正式 T3）：修正上一轮共同起点错误，所有算法从 `shared warm start` 起跑，翻转闭包只记录 `reference_flip_closure_*`，不再更新 current/best，`common_lift=0`。产物 `baselines/e2_alns/e2_g0_reaudit_v2_20260703/`，15/15 rows `OK` 且 `16000/16000`；plateau 复核 verdict=`G0_PASS_BASELINES_HEALTHY`，旧 `5174.345121253789` 精确同质化未复发，12 条 baseline best cost/signature 全唯一，identity suspect=0，12/12 baseline run liveness 通过。台账成本仅作定位、非正式胜负：ALNS mean `3568.483474`、LNS mean `3599.130896`、VNS mean `4071.566126`、PSO mean `4576.538634`、GA mean `4591.542851`。场景合规 `SCENARIO_COMPLIANCE_OK`。锚谱系 `ANCHOR_LINEAGE_CLOSED`：`df608660` seed1-10 mean 精确复现 `4878.331796187524`，seed2 精确复现 `4779.053444002934`，因此 4878=旧代码/Q1600 时代均值、4779=同锚族 seed2。触碰 baseline/report 脚本后两独立 ALNS 锚零漂（`2677.7953638343815` / `3561.080964207054`）；相关回归在干净临时 worktree为 `35 passed, 1 skipped`；artifact hash 为 clean-files-only 且不含 `._*`/`__pycache__`/`.pytest_cache`。本任务不解冻 G4/G5；正式 T3、PSO/VNS 是否转 G3 文献重建、LNS 与 ALNS 接近/反超时论文姿态，均留给 user 拍板。

2026-07-03 Claude 判读 G0 v2 过门 + 交稿收官签发：公平 warm-start 台账 ALNS 3429.87/3568.48 全场第一（对 LNS +0.9%mean/+4.3%min、VNS +12.4%、PSO +22.0%、GA +22.3%）；上一轮"LNS 领跑"确认为起点偏置假象。碳算子按台账重开协议合法重开（09x/09y 测于同质化坏机器时代；健康重测=第一次真实测试,结果未出前不得预写有用）。拍板建议：G4/G5 解冻+前插 ALNS 定型 gate（碳消融+文献组件重消融,预注册自决策规则选 T3 主变体）；PSO/VNS 不做文献重建；G3=在库其余基线（ACO/GA-VNS/GWO/IWD）过同一健康门禁,过者进 T3；正式跑一律 Goeke80 默认零 override,280 仅限定型 gate 的诊断臂。收官顺序：定型 gate→G3 健康门→G4 稳定性→G5 正式 T3（双账本+resume+分级墙钟帽,素材产出不自动进 TeX）。

2026-07-03 Codex 执行 E2 交稿收官工程 Phase 0/A 后收口为 `ALNS_GATE_BLOCKED`：前置冻结通过（G0 v2 已过、Tier1 `-01` manifest=23、正式阶段 Goeke80 默认零 override、280 仅 diagnostic），但 Phase A 正式 Goeke80 carbon gate 出现硬 under-eval：`e2-threeshift-150c-01 / alns_e2_carbon / seed1` 在 `3602.891834s` 只完成 `5575/16000` eval。按 user 要求介入修正 runner：formal Goeke80 A1 批次先行，任一 formal blocker 立即写 `ALNS_GATE_BLOCKED` 并跳过 diagnostic 280 与组件 gate；同时修中断清理，避免 `.tasks` orphan worker 继续派发。产物 `baselines/e2_alns/e2_final_closure_20260703/`，总 `decision.json` 为 `final_material_verdict=ALNS_GATE_BLOCKED`、`blocked_phase=phase_a`，Phase B/C/D 未启动，T3/F2 素材未生成。验证：相关回归 `19 passed`，新增收官测试 `8 passed`，两独立 ALNS 锚零漂（`2677.7953638343815` / `3561.080964207054`），artifact hash 干净且 protected-file diff 为空。后续不得直接启动 G3/G4/G5；需 user 先决策 carbon gate 策略（接受 throughput-only、给 carbon 单独吞吐协议、或放弃 carbon 主变体）。

2026-07-03 user 拍板并由 Codex 修订 E2 交稿收官 Phase A：T3 主变体锁死 `alns_e2_throughput`；carbon 算子降级为等墙钟诊断线（DIAGNOSTIC/非 T3，不阻塞主链，也不悄悄放弃）。runner 已改为 Phase A 主账只跑 throughput 组件重消融，旧 carbon under-eval 证据归档到 `phase_a_carbon_gate_superseded_under_eval/`，新增 `carbon-diagnostic` 非阻塞入口。新 Phase A 在 `e2-threeshift-150c-01`、Goeke80 默认、seeds1-3、16000 eval、3600s 帽下闭合：A2 12/12 OK，A3 3/3 OK；verdict=`ALNS_GATE_READY`，T3 main profile=`alns_e2_throughput + LOCAL_SEARCH`。采纳证据：`LOCAL_SEARCH` mean 改善 `+1.1152%`、worst seed `-0.0619%`；`ROUTE_ELIMINATION` 单独过线但叠加 LOCAL 后 seed2 劣化 `-4.5409%`、回退；`RRT_TRUE_ACCEPTANCE` 明显劣化、拒绝。顶层 decision 刷新为 `blocked_phase=phase_b`（B/C/D 未运行），carbon diagnostic 未运行且非阻塞。验证：相关回归 `22 passed`，两独立 ALNS 锚 `2677.7953638343815` / `3561.080964207054` 零漂，artifact hash 排除且不含 `._*`/`__pycache__`/`.pytest_cache`/`.tasks`，protected-file diff 对成本/检查/评估/价格/TeX/feasible_repair/resetp_alns/ALNS 主路径为空。下一步可继续 Phase B G3 baseline health；carbon 等墙钟诊断可并行补采但不得改变 T3 主变体。

2026-07-03 Codex 执行 E2 交稿收官 Phase B / G3 在库基线健康门：产物 `baselines/e2_alns/e2_final_closure_20260703/phase_b_g3_baseline_health/`，配置 `e2-threeshift-150c-01`、Goeke80 默认零 override、seeds1-3、16000 eval、3600s 帽。ACO、GA-VNS、GWO、IWD 共 12/12 rows 均 `OK` 且 `16000/16000`，run-level liveness 全过，verdict=`G3_BASELINE_SET_READY`，无 `WEAK_IMPLEMENTATION_EXCLUDED`。T3 baseline set 扩为 `{GA,LNS,PSO,VNS,ACO,GA-VNS,GWO,IWD}`；SA/TS 仍登记为 `NOT_IMPLEMENTED_FOR_T3_BOUNDARY`，是否写 limitation 留给 user。阶段成本只作健康门素材、非胜负：ACO `4424.76/4418.48/4484.53`，GA-VNS `4340.17/4207.02/4366.54`，GWO `4383.24/4223.14/4441.21`，IWD `4977.80/4960.06/4881.96`。顶层 decision 已推进到 `blocked_phase=phase_c`；下一步为 Phase C G4 三班稳定性复核，carbon 等墙钟诊断仍为非阻塞未运行支线。

2026-07-03 Codex 执行 E2 交稿收官 Phase C / G4 三班稳定性复核并早停：Goeke80 默认零 override，`t3_main_alns=alns_e2_throughput+LOCAL_SEARCH` 对 LNS，首个实例 `e2-threeshift-100c-01` seeds1-3 全部 `OK` 且 `16000/16000`。已完成实例触发预注册红线：ALNS mean `2745.3297058863445`、LNS mean `2687.0157578586277`，gap=`-0.021702123576003575`，超过“任一实例 ALNS 劣于 LNS 不得超过 2.0%”；且 LNS seed1 liveness fail（`LOW_ROUTE_COUNT_DIVERSITY`, `route_count_unique=4`）。因此停止剩余 Phase C 和 Phase D，verdict=`HALT_G4_SUSPECT`，顶层 `final_material_verdict=HALT_G4_SUSPECT`、`blocked_phase=phase_c`。本次同步修正收官 runner 的 Phase C 判决层：输出 `liveness_verdicts.csv`，并把 baseline liveness suspect 与已完成实例 hard direction violation 纳入 `decide_phase_c()`；回归 `46 passed, 1 skipped`，两独立 ALNS 锚 `2677.7953638343815` / `3561.080964207054` 零漂。产物 `baselines/e2_alns/e2_final_closure_20260703/phase_c_g4_stability/`；这不是正式 T3 素材，后续需 user 重新拍板 G4/论文姿态或 ALNS 定型策略。

2026-07-03 Codex 执行 G4 HALT 复核 A' / ROUTE_ELIMINATION-only 补测：产物 `baselines/e2_alns/e2_final_closure_20260703/phase_a_prime_route_elimination_retest/`。复用既有 Phase A/C 数据，只补跑缺口：100c-01 `alns_component_ROUTE_ELIMINATION` seeds1-3 与 150c-01 LNS seeds1-3，均 Goeke80 默认、16000/16000 OK。verdict=`ROUTE_RETEST_INCONCLUSIVE`：route-only 把 100c-01 均值缺口从 LOCAL_SEARCH-only 的 `-2.1702%` 改善到 `-1.4898%`，pooled 100c/150c 从 `-1.1243%` 改善到 `-0.9939%`，但 100c-01 最差 seed 仍为 `-2.6153%`，违反预注册“单 seed 不劣化超过 1%”安全线；150c-01 route-only 仍略劣于 LNS（`-0.6519%`）。因此不切换 T3 主 profile，顶层仍为 `alns_e2_throughput+LOCAL_SEARCH`、`blocked_phase=phase_c`、`final_material_verdict=HALT_G4_SUSPECT`。liveness 门禁已对称可见化：ALNS/组件的 `route_count_unique<5` 写成 `ALNS_ROUTE_COUNT_INFO`，不是 fail；baseline liveness 判决不变。验证：`solver/tests/test_e2_final_closure.py` = `15 passed`，当前集合 `49 passed, 1 skipped`，两独立 ALNS 锚零漂。A' 只说明 route-only 有改善但未过线，不能解除 G4 HALT，也不能证成结构性缺口；Phase D/G5 继续停止。

2026-07-03 Codex 执行 G4/G5 收尾恢复计划（证据 gate / 非正式 T3 / 不写 TeX）：按 user 新裁决，G4 判据 (c) “单实例 ALNS 劣于 LNS 超过 2%”不再硬停，而记录为 `DOCUMENTED_INSTANCE_EXCEPTION`；(a) `>=6/9` 实例不劣与 (b) pooled gap `>=0` 仍为硬门槛。runner/test 已改：Phase C 写 `documented_instance_exceptions`，Phase D/G5 可接受 `G4_PASS_WITH_EXCEPTIONS` 并支持 Tier1/2/3 manifest（23/46/69）、双账本和 T3 逐实例 exception 标注；但本轮未启动 Phase D。Phase C 在 `baselines/e2_alns/e2_final_closure_20260703/phase_c_g4_stability/` 完整闭合 9 个三班实例（54/54 rows，全部 `OK` 且 `16000/16000`）。exception=2：`e2-threeshift-100c-01` gap `-0.021702123576003575`，附 A' route-elimination 诊断证据和“LOCAL_SEARCH 不改路线数/该例需要路线压缩”机制脚注；`e2-threeshift-100c-02` gap `-0.020537221759442725`。其余实例中 100c-03、150c-02、200c-01、200c-02、200c-03 为不劣，150c-01/150c-03 小幅劣但未达 exception。总账 `nonnegative_gap_instances=5/9`、`pooled_gap_fraction=0.02085891464891202`、`documented_exception_count=2`，所以因硬条件 (a) 失败，Phase C 和顶层 final verdict 仍为 `HALT_G4_SUSPECT`、`blocked_phase=phase_c`、`halt_reason=G4_DIRECTION_RULE_FAILED`；不得推进 G5，不得写正式 T3。验证：最小回归 `32 passed`，两独立 ALNS 锚 `2677.7953638343815` / `3561.080964207054` 零漂，artifact hash 刷新且不含 `._*`/`__pycache__`/`.pytest_cache`/`.tasks`，protected solver/TeX 语义路径 diff 为空。

2026-07-04 Codex 执行 E2 收官终章（G4 record + Phase E' carbon + Phase D HALT）：仍在 `baselines/e2_alns/e2_final_closure_20260703/` 收口。G4 record-only 不改 raw，将 Phase C 记录为 `HEALTH_PASS_WITH_SIZE_DEPENDENT_PROFILE`，保留旧 `original_verdict=HALT_G4_SUSPECT`、9 实例 gap、两个 100c documented exception、`nonnegative_gap_instances=5/9`、`pooled_gap_fraction=0.02085891464891202` 和 user 选项②授权。Phase E' 碳算子等墙钟诊断 Tier1 已闭合 27/27 rows `OK`（三班高 EV 实例 × carbon/ablation/throughput × seeds1-3，允许 under-eval 如实入账），预注册 carbon vs ablation 判定 `CARBON_OPS_WEAK`；因此 T3 主变体仍是 `alns_e2_throughput+LOCAL_SEARCH`，碳算子素材应按 limitation/future work 口径处理。Phase D Tier1 启动后在 partial raw 发现同一实例内跨算法/跨 seed 完全相同 `best_cost`+`best_signature`，尤其 `e2-multidepot-10c-01` 多算法多 seed 复用两套签名，且 baseline liveness 多为 `BASELINE_LIVENESS_FAIL/LOW_ROUTE_COUNT_DIVERSITY`。按预注册唯一红线停止 Phase D，并新增 reporting 层 `phase-d-freeze` 冻结已落行数据：`material_rows=54`、`observed_instance_count=3`、`failure_count=0`、`exact_identity_suspect_count=3`、`homogeneity_suspect_count=6`、`record_only_freeze=true`；顶层 final verdict=`HALT_T3_HOMOGENIZATION`，不得包装为正式 T3。验证：最小回归 `42 passed`；两独立锚 `2677.7953638343815` / `3561.080964207054` 零漂；顶层与 Phase D `artifact_hashes.json` 均不含 `._*`、`__pycache__`、`.pytest_cache`、`.tasks`；protected solver/TeX 语义路径 diff 为空。

2026-07-04 Codex 执行 Phase D 同值簇四分类判则并闭合 Tier1：只改 runner/reporting/test，把 Phase D 同值簇改为 `NATURAL_CONVERGENCE`、`SECONDARY_ATTRACTOR`、`SHARED_STALL`、`HALT_T3_HOMOGENIZATION` 四分类。冻结 54 行重判后无 HALT，随后 resume Tier1；最终 `phase_d_g5_t3_material/raw_runs.csv` 621/621 rows 全部 `OK` 且 `16000/16000`，Phase D 与顶层 `decision.json` 均为 `T3_MATERIAL_READY`。`identity_clusters.csv` 汇总 33 个披露簇：`SHARED_STALL=22`、`NATURAL_CONVERGENCE=7`、`SECONDARY_ATTRACTOR=4`、`HALT=0`；`t3_table_material.csv` 已带 identity cluster 标注和脚注源。碳算子仍为 `CARBON_OPS_WEAK`，T3 主变体仍是 `alns_e2_throughput+LOCAL_SEARCH`；素材仅供 T3/F2，不自动写 TeX。验证：最小回归 `44 passed`；两独立锚 `2677.7953638343815` / `3561.080964207054` 零漂；artifact hash 无 AppleDouble/pycache/pytest/tasks 污染；protected solver/TeX diff 为空。

2026-07-05 Codex 执行 route-compression hard-subset probe（E2 ALNS 根因修复探针 / 非正式 T3）：新增显式诊断组件 `RELAXED_ROUTE_COMPRESSION`，默认 `ROUTE_ELIMINATION` 严格行为不变；未改 `cost.py`、`check.py`、`search/evaluation.py`、`prices.py`、TeX、模型、电池或 baseline。产物 `baselines/e2_alns/route_compression_probe_20260705/`。前置证据重算确认 A0=`alns_e2_throughput+LOCAL_SEARCH` 对 LNS 为 6 胜 / 16 负 / 1 平，mean gap `-0.007131889956741538`；hard subset 16 个实例上 A0-LNS mean total delta `23.77856434493994`、route_count delta `0.3125`、fixed-cost delta `25.0`，支持路线数/固定派车成本是主因。新跑 A1=`alns_e2_throughput+RELAXED_ROUTE_COMPRESSION` 与 A2=`+RELAXED_ROUTE_COMPRESSION+LOCAL_SEARCH`，96/96 rows 均 `OK` 且 `16000/16000`，0 infeasible、0 under-eval、0 identity HALT；两独立 ALNS 锚 `2677.7953638343815` / `3561.080964207054` 零漂。最终 verdict=`ROUTE_COMPRESSION_FIX_NOT_SUPPORTED`：A1 只到 4 胜 / 12 负、mean gap `-0.013073362074800225`、mean route_count_delta_vs_a0 `-0.1041666666666666`，A2 为 0 胜 / 16 负、mean gap `-0.016189810717862328`。结论边界：route-compression 假设被严格测试但未过支持门，不能解冻正式 T3，不能写 ALNS 战胜 LNS，也不能写创新算子有效。验证：指定回归 `51 passed, 1 skipped`，protected diff 和 `git diff --check` 为空，产物目录无 `._*`/`__pycache__`/`.pytest_cache`/`.tasks`。

2026-07-05 Codex 执行 route-compression trace audit（源码/trace 优先纠偏，非正式 T3）：按 user 修正，停止 oracle/ejection-chain/cross-exchange 方向；只读现有 evidence 与源码，新增 `baselines/e2_alns/route_compression_trace_audit.py` 和 `baselines/e2_alns/route_compression_trace_audit_20260705/`。前置 Git hygiene 清理 `.git` AppleDouble，`git fsck --no-progress` code=0；`.tasks` runner traces 从 `6dac85c76` 恢复并单独提交 `ae450285c`，不混入 evidence hash。审计结论：A1/A2 未过门的明确失败项是 `mean_gap_positive` 与 `wins_at_least_losses`，不是 under-eval、infeasible、identity halt 或 anchor parity；A0/A1/A2 winner history 对 route_count 和 revert/local-search route delta 仍是 `UNKNOWN`，需要最小 instrumentation；LNS best-update family counts 为 `lns_destroy_repair=1678`、`lns_vehicle_type_mutation=415`、`lns_scan_initial=33`、`shared_warm_start=48`。下一步只能基于该 trace 推荐审计 LNS destroy/repair acceptance 与 scheduler 行为；本轮不设计新算子，也不继续调 `RELAXED_ROUTE_COMPRESSION`。结论边界：被否的是“旧 route_elimination + relaxed acceptance + allow-new-route retry”，不是整个路线压缩方向。

关联：[[dynamic-demand-integration]] [[baseline-algorithm-catalog]] [[alns-crush-root-cause]] [[project-plan-overview]] [[e2-prd-gates]]

2026-07-05 Codex 执行 LNS scheduler/acceptance trace audit（最小 instrumentation，非正式 T3）：新增 `SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC=1`，默认关闭时 formal history/schema 不变；开启时 ALNS history 补 `route_count/signature`，candidate trace 记录 route_count 前后、accepted/accepted_worse/best_improved、hard violation、revert reason、local_search 前后 objective/route_count；LNS trace 将 `lns_destroy_repair` 拆成 `strong_bridge` 与 `fallback_relocate`，并单独记录 `vehicle_type_mutation` 与 `scan_initial`。新脚本/产物为 `baselines/e2_alns/lns_acceptance_scheduler_audit.py` 与 `baselines/e2_alns/lns_acceptance_scheduler_audit_20260705/`，hard subset 16 实例 × seeds1-3 × `{LNS_TRACE,A0_TRACE}`，eval_budget=4000，96/96 rows `OK`，verdict=`TRACE_AUDIT_COMPLETE`、`diagnostic_only=true`、`formal_t3=false`。关键数值：LNS best_improved by path = `strong_bridge=1334`、`vehicle_type_mutation=339`、`scan_initial=33`、`fallback_relocate=19`；因此下一步应继续查 repair/acceptance/scheduler 的 strong bridge 路径，而不是设计 oracle/ejection-chain/cross-exchange 或继续调 `RELAXED_ROUTE_COMPRESSION`。ALNS revert summary 目前是 `unchanged=103460`、`candidate_usable=87751`，说明 A0 候选层仍需进一步拆 scheduler/acceptance 细节。验证：trace/throughput/closure 回归 `52 passed`，protected diff 与 `git diff --check` 为空；AppleDouble sidecar 运行中出现后已清理，artifact hash 排除 `._*`/`__pycache__`/`.pytest_cache`/`.tasks`，clean fsck log 无 `bad sha1/error/fatal/missing/corrupt`。

2026-07-06 Codex 执行 A3 strong-bridge backend alignment 第一刀算法探针（诊断 profile / 非正式 T3）：新增显式诊断 flag `SETP_ALNS_CRUSH_STRONG_BRIDGE_BACKEND=1`，默认关闭；仅在 3×3 pair（`random_customer_removal` / `shaw_related_removal` / `worst_customer_removal` × `greedy_insert_repair` / `regret2_insert_repair` / `regret3_insert_repair`）上把 official ALNS candidate backend 对齐到 LNS 已证实有效的 `_apply_strong_alns_destroy_repair()`，后续仍走既有 candidate evaluation、local search、hard violation、revert、acceptance 与 selector update；不改 q-size、scheduler、acceptance、vehicle mutation、local search 深度、`RELAXED_ROUTE_COMPRESSION`、`cost.py`、`check.py`、`search/evaluation.py`、`prices.py`、`search/feasible_repair.py` 或 TeX。新增 runner/产物为 `baselines/e2_alns/strong_bridge_backend_probe.py` 与 `baselines/e2_alns/strong_bridge_backend_probe_20260705/`，hard subset 16 实例 × seeds1-3 × `{A0_TRACE,A3_STRONG_BRIDGE_BACKEND,LNS_TRACE_REFERENCE}`，eval_budget=4000，144/144 rows `OK`、0 fail、0 infeasible、0 under-eval，`diagnostic_only=true`、`formal_t3=false`、`algorithm_win_loss_claim=false`。最终 verdict=`A3_STRONG_BRIDGE_BACKEND_NOT_SUPPORTED`：A3 unchanged_rate 从 A0 的 `0.5410776576661385` 小降到 `0.5409924374758114`，best_improved_rate 从 `0.010956482629137445` 升到 `0.013765258412392917`，但 mean gap vs LNS 从 A0 的 `-0.0027550841310447025` 恶化为 A3 的 `-0.01268965932170772`，A3 vs A0 为 20 胜 / 24 负 / 4 平，未过 `mean_gap` 与 `wins_vs_A0>=losses_vs_A0` 门。结论边界：第一刀 backend alignment 不支持继续调 backend；下一步应停止 backend 叠加，单变量拆 q-size、scheduler、acceptance。

2026-07-06 Codex 修正 A3 backend probe profile alignment（只修诊断口径 / 非正式 T3）：源码预检确认旧 A3 probe 未显式打开 `SETP_ALNS_CRUSH_LOCAL_SEARCH=1`，因此旧结果只代表 throughput-only backend probe，不代表当前 T3 main profile `alns_e2_throughput+LOCAL_SEARCH`。runner 已改为五臂：`A0_THROUGHPUT_ONLY`、`A3_BACKEND_ONLY`、`A0_MAIN_LOCAL_SEARCH`、`A3_BACKEND_LOCAL_SEARCH`、`LNS_TRACE_REFERENCE`，并输出 `flags_by_profile.json`；`decision.json` 分开报告 `BACKEND_ONLY` 和 `MAIN_LOCAL_SEARCH`，顶层 verdict 以 main-local-search 为准。新产物 `baselines/e2_alns/strong_bridge_backend_probe_local_search_check_20260706/`，240/240 rows `OK`、0 fail、0 HALT。结果：backend-only 复现旧负结论；corrected main-local-search 仍为 `A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED`，A3 vs A0 为 16 胜 / 24 负 / 8 平，A3 mean gap `-0.013673594831823434` vs A0 `-0.004385253026182812`，A3 unchanged_rate `0.5445287696596597` 高于 A0 `0.5219023910633224`，best_improved_rate 虽从 `0.011338200531347405` 升至 `0.013980783614291468` 但未过门。结论：不升 8000，不进 Tier1；下一步才允许拆 q-size / scheduler / acceptance 三个单变量探针。本轮未改 solver 主算法语义；验证 `61 passed`，protected diff 与 `git diff --check` 为空，artifact hash 排除 AppleDouble/pycache/pytest/tasks，新大型 trace 由 Git LFS 管理；外置盘源仓库 `fsck` 会被 `com.apple.provenance` 反复污染，最终使用无硬链接 `/tmp` clean clone 的空 `git fsck` 日志作对象完整性证据。

2026-07-06 Codex 执行 ALNS selector pathology audit（只读根因审计 / 非正式 T3）：新增 `baselines/e2_alns/selector_pathology_audit.py` 与产物 `baselines/e2_alns/selector_pathology_audit_20260706/`，只读现有 A0/A3/LNS trace，不跑新算法、不改 solver。`decision.json` verdict=`SELECTOR_PATHOLOGY_SUPPORTED`，支持门为：A0/A3 pair entropy 明显低于 LNS strong_bridge、top pair share 明显高于 LNS、A3 best-improved 集中在少数 pair、`AlphaUCB` value bound 显示 exploration 追不上 reward=8/20。关键数值：A0 normalized entropy `0.5479450509066646`、top1/top2 `0.5102399430998055/0.7646329728259733`；A3 normalized entropy `0.6103431771914223`、top1/top2 `0.4624746980767923/0.6931550125267403`；LNS strong_bridge normalized entropy `0.9812637638712004`、top1/top2 `0.14778803564757992/0.289631250333529`。未试 pair value 在 iter=100/1000/4000/16000 仅 `1.607626/1.743438/1.814582/1.880018`，远低于 reward=8/20。结论：下一步才允许单变量 scheduler 修复探针 `SETP_ALNS_CRUSH_BALANCED_SELECTOR=1`；不得升 8000、不得 Tier1、不得继续 backend 或 route-compression tuning。

2026-07-06 Codex 执行 A4 balanced-selector 单变量修复探针（诊断 profile / 非正式 T3）：新增 `BalancedAlphaUCB` 与显式 flag `SETP_ALNS_CRUSH_BALANCED_SELECTOR=1`，默认关闭且 legacy `AlphaUCB` 行为不变；A4 只改 operator selection，先每个合法 pair warmup 10 次，再用现有 AlphaUCB exploit + `epsilon=0.10` 均匀探索合法 pair，不改 q-size/backend/acceptance/local search。新增 `baselines/e2_alns/balanced_selector_probe.py` 与产物 `baselines/e2_alns/balanced_selector_probe_20260706/`，hard subset 16 实例 × seeds1-3 × `{A0_MAIN_LOCAL_SEARCH,A4_BALANCED_SELECTOR_LOCAL_SEARCH,LNS_TRACE_REFERENCE}`，eval_budget=4000，144/144 rows `OK`。verdict=`A4_BALANCED_SELECTOR_PROMISING`：A4 mean gap vs LNS `0.00048527397136235187` 优于 A0 `-0.004385253026182812`；A4 vs A0 为 23 胜 / 18 负 / 7 平；normalized entropy 从 `0.5479450509066646` 升至 `0.8227620351716587`；top1/top2 pair share 从 `0.5102399430998055/0.7646329728259733` 降至 `0.24319320523414537/0.4628254343482945`。A4 best_improved_rate 低于 A0（`0.009241341798897525` vs `0.011338200531347405`），但均值更好，支持“pair diversity 修复”方向。下一步只允许 8000 eval hard subset 复验 A4；不得直接 Tier1，不得叠加 backend/q-size/acceptance。

2026-07-08 Codex 执行 A11 global-order repack + A12 fleet-charge co-repair 探针（诊断 profile / 非正式 T3）：停止继续 selector/backend/q/acceptance、`STRONG_BRIDGE_BACKEND`、`RELAXED_ROUTE_COMPRESSION` 和 A8/A9/A10 小修线。新增公共 `solver/src/setp_solver/search/order_decoder.py`，把 LNS order decoder/cache feasibility/distance/append 逻辑抽成 `OrderDecodeContext` 下的公开函数；`metaheuristic_baselines.py` 只保留兼容 wrapper，不改变 LNS 行为。新增 A11/A12 互斥诊断 flags，默认关闭：A11 在停滞或 late-stage 从 current/best 提取 customer order，经 current/two-opt/double-bridge/depot-group-shuffle 扰动后用公共 order decoder 重解码，再走现有 check/evaluate/acceptance；A12 尝试 CV/EV flip 与 charging replay，以 total cost 为准，记录 fuel/electric/carbon/fixed delta。runner `baselines/e2_alns/global_repack_fleet_charge_probe.py` 的 corrected run 产物为 `baselines/e2_alns/global_repack_fleet_charge_probe_20260707/`，432/432 rows `OK`、0 fail、0 HALT，verdict=`GLOBAL_REPACK_FLEET_CHARGE_4000_ONLY`。A11 4000 过门并降低 route/fixed gap（mean gap vs LNS `0.006961686839843399`，vs A7 17 胜 / 14 负，route_count_delta_vs_lns `0.041666666666666664` vs A7 `0.10416666666666667`，cost_fix_delta_vs_lns `3.3333333333333335` vs A7 `8.333333333333334`）；A12 4000 未过门且 route/fixed gap 与 A7 相同。A11 升 8000 后未过门（vs A7 2 胜 / 4 负，route/fixed gap 回到 A7 水平 `0.125`/`10.0`），所以不跑 16000、不进 Tier1。并行文献根审计 `source_literature_root_audit_20260707/` 通过 OpenAlex 产出 300 行矩阵、30 篇 deepread 摘要和源码映射。验证：targeted regression `60 passed`，`git diff --check` 为空，protected solver/TeX diff 为空，artifact hash 不含 AppleDouble/pycache/pytest/tasks。结论：A11 小预算能命中 route/fixed 病灶但不能稳定放大，A12 单独无效；后续不得继续纯 ALNS 小修，应考虑 hybrid LNS/HGS-style 主算法或接受 LNS 第一梯队现实。

2026-07-08 Codex 执行 route-packing reachability audit + A13 parity scaffold（诊断 / 非正式 T3）：按最新路线先证明 LNS-like 低路线数结构可达。新增 `baselines/e2_alns/route_packing_reachability_audit.py` 与产物 `baselines/e2_alns/route_packing_reachability_audit_20260708/`；正式 run 对 21 个 A7-losing rows 中 14 个达到 LNS route count 或把 route-count delta 至少砍半，`reachable_fraction=0.6666666666666666`，`decision.json` verdict=`ROUTE_PACKING_REACHABILITY_SUPPORTED`，允许进入 A13。随后新增 `solver/src/setp_solver/search/lns_policy_kernel.py` 和 `baselines/e2_alns/lns_policy_kernel_probe.py`，抽出 A13 LNS policy kernel scaffold，包含 angle scan initial、35% vehicle-type mutation、strong bridge destroy/repair、fallback order relocate、Metropolis wandering、温度衰减与 1000 iter reheating；LNS baseline 行为未改。只跑 smoke：`/tmp/resetp_a13_smoke`，2/2 rows OK，verdict=`A13_PARITY_SMOKE_SUPPORTED`，这不是完整 parity gate，不能启动 A14 或 hybrid。验证：带 `PYTHONPATH=solver/src` 的 targeted pytest 为 `55 passed`，`git diff --check` 与 protected diff 均为空；无 `PYTHONPATH` 的首次 pytest collection 失败仅为本地 import path 问题。下一步必须运行完整 A13 hard-subset parity；若不达 `A13_PARITY_SUPPORTED`，停止并写 `parity_failure_report.md`，不得跳到 A14/hybrid。

2026-07-09 执行拨正：正式算例改为 L-main v2 **9 阶三班倒 only**；ALNS **完全独立包** `algorithms/resetp_alns`（非半独立）。详见 instance-lineage.md / resetp-alns-independence.md。E2 性能目标（约超第二名 5%）须在新底座上重采。

2026-07-10 Codex 独立根因接管第一轮：L-main v3 九阶三班族已从 commit `48efe1208d2a5f56d481dd1defff4c143eb09bc0` 重建、审计并激活，实际客户数 `22/34/45/55/114/163/221/322/449`，verdict=`LMAIN_V3_READY`；formal runner 加 manifest+audit hash 门并修复不存在的主实例名和 E0 23/9 漂移。独立化 `fca004fad` 遗留三处真实运行断点已由失败测试复现并修复：bundle loader 名称错误、独立 strong-bridge 缺依赖/类型/dataclass、DR lazy runner 拼写和双调用错误。完整根因报告 `docs/handoff/m1_independent_root_cause_20260710.md`。

同日当前-v3机制证据：`m1_structure_reachability_20260710` verdict=`ALNS_SCHEDULER_OR_MULTI_STEP_BARRIER`，否定“ALNS算子完全不能改车队结构”；CURRENT_THROUGHPUT 在55实际客户/280kWh下，CV起点 90 次得42个结构候选（28个立即改善），shared-one-EV起点24个且全部立即改善。`m1_scheduler_realization_20260710` verdict=`DEFAULT_SELECTOR_STARVATION_CONFIRMED`：同起点/同seed/400 eval下，shared-one-EV默认 AlphaUCB 五个种子全部零 vehicle swap、dominant share 平均0.9964、最终固定1条EV；balanced coverage 5/5 更优，平均降178.873473并到6--8条EV。CV起点 balanced 仅3胜2负，且旧hard-subset selector在16000仍未过LNS门，所以 selector starvation 是确定根因但 balanced 不是最终解。旧 fair-SA runner 起点不一致，3.23% claim 未找到原始行，09y Stage B 全平只证构造机制。下一步冻结唯一M1身份与公平起点合同，测试按动作家族的最低覆盖和固定路线车队组成机会图；不再续旧 route patch，不为混合比例改 evaluator/物理合同。

2026-07-10 上述两项最小方案已执行并改变下一步。Minimum coverage 的预注册400-eval窄门槛虽为 `MINIMUM_COVERAGE_400_SUPPORTED`（10组6胜4负），但 trace 出现反向锁死，部分400步中 vehicle swap 被选300次、路线数仍为8，CV起点仅2胜3负；判为表面通过、不升4000、不继续selector线。`m1_fleet_opportunity_20260710` 对6个保存的7--8路线集合精确枚举全部CV/EV组合：280kWh为5个全EV最优、1个7EV+1CV最优，verdict=`FIXED_ROUTES_ROUTING_DEPENDENT`，全EV集合的最佳混合只贵0.68%--1.64%；80kWh为6/6固定路线混合，但路线来自280搜索，只证存在性。`m1_fair_sa_recheck_20260710` 同起点400-eval结果为 `SA_SHORT_ADVANTAGE_NOT_REPRODUCED`，SA对默认ALNS 0胜10负，mean差+430.767930，路线数始终不降。下一条只允许测试“路线重分组→车型/充电闭包”的顺序联合headroom（旧A11/A12是互斥单测），跨小中大多来源路线有稳定headroom才接入ALNS；否则停止。正式胜负仍需唯一M1合同+同起点4000/8000/16000。

2026-07-10 预算审计覆盖上述下一条：联合headroom在3规模×3算法×3种子为14/27，未过60%预注册门，判partial、不接主循环；路线重排单独仅2/27。车型闭包10/27改善，T3 ALNS为3/9且漏失约209/242/570，优先级高于联合动作。`m1_local_search_budget_20260710` 判定 `LOCAL_SEARCH_BUDGET_UNDERCOUNT_CONFIRMED`：9个标称100-eval的T3运行额外完整评价11547次，单次760--2164，mean有效/报告比13.83；因此旧 `throughput+LOCAL_SEARCH` T3身份和同预算排名撤销，按次计费前local-search必须关闭。控制组另有1次101/100边界。动态碳算子继续 `CARBON_OPS_WEAK`，静态E2关闭；15c档实际34客户且num_ev=0，SA vehicle flip的fleet-packing崩溃已由失败测试修为安全拒绝。下一步只修严格预算+低频车型收口，再做小/中/难三档短门。

2026-07-10 staged-chain 独立ALNS快速门：确认400→4000退化的实现根因是 selector/acceptance 每400步重启但 destroy progress 仍按总预算计算；修为阶段内 progress 后，221客户 seed1/4000 从5536.079448降至5025.535884。114客户离线17→16审计中，17条路线逐条删除×3 repair共51次全退回，最弱路线客户在其余16条路线全位置不可插，支持“需要多路线同步重组”而不是继续调旧路线消除。新增 `run_staged_chain_alns()`，总预算严格拆为400普通+中段strong repair+400普通。`m1_staged_chain_gate_20260710` 九阶v3/seed1/4000/同CV起点/280kWh下，18保存解完整复算成本差0、全零违规；aggregate cost gain vs LNS=5.636972%，runtime gain=72.331226%，成本7胜1平1负、时间9胜。仍为diagnostic：mean instance gain=3.035910%，仅2/9单实例过5%，322客户档反输10.185173%；不得写正式冠军，下一步只对失败档+中档+最难档做少量多种子4000复核。

2026-07-10 322客户多种子纠偏：`m1_staged_chain_150c_multiseed_20260710` 补齐 ALNS/LNS seeds1--3 同起点4000配对。ALNS 2胜1负，均值8522.020379对8768.601737，低2.812094%；平均时间低78.079697%。seed1反输10.185173%未复现，seed2/3分别胜5.270602%/12.923540%，故旧“结构性失败”降级为“种子稳定性不足”。verdict=`STAGED_CHAIN_150C_MULTISEED_PARTIAL`；该档仍未稳定过5%，不得升格正式冠军结论。

2026-07-10 正式稳定性入口预检：新增公开 `run_staged_alns_lns_hybrid()`，身份固定为hybrid且不替换旧winner入口；新增可恢复 runner `m1_staged_hybrid_stability_gate.py`，冻结30任务=`100c/150c/200c × seeds1--5 × hybrid/LNS`、4000 eval、900s、280kWh显式诊断覆盖。论文和prices默认仍80kWh；碳算子关闭，其余合同不改。任务矩阵与2-eval落盘烟雾通过，30次尚未启动。

## 2026-07-11 E2十二小时收口与碳调度小门

- 新混合路线搜索身份冻结为 `staged ALNS-LNS hybrid`；不再 rescue 调参，也不静默覆盖旧 `ALNS-Wouda`。
- 正式候选在路线搜索后执行固定路线碳感知充电调度，消融为立即充电。历史粗糙碳 destroy/repair 继续关闭。
- 复用280kWh稳定性门15个hybrid保存解：15/15 aware/naive重放成功、总充电量一致、双方零违规，625次充电实际移动，15/15的 `E_ev_indirect` 下降，平均降幅约9.87%。该结果是机制小门，不是正式E4/E5或T3。
- 正式正面主场景合同：280kWh任务内覆盖，L-main v3九实例 × seeds1--5 × `carbon-aware hybrid/immediate-charge ablation/LNS/GA/PSO/VNS` × 4000 eval，共270项；先跑100/150/200c seed1 × 六算法 × 400 eval的18项小门。80kWh保留Goeke稳健性对照，源码默认不改。
- 默认6 workers；任务独立落盘、主进程汇总、支持resume；正常监控30--60分钟一次，异常事件立即汇报。
- 入口修复：Tier1清单校验由旧23改为当前9；混合入口如实回报碳开关并保存三阶段原始算子计数。62项相关测试通过；另有旧 `scan_all_cv_solution` 超油车上限失败，未纳入正式入口且不得当健康基线。
- 完整协议见 `docs/handoff/e2_12h_finalization_protocol_20260711.md`。
## 2026-07-11 E2冻结与E1主结构收口

E2正式证据已用tag `e2-submission-20260711`冻结在commit `0124623e`，并新增`E2_FREEZE.json`记录三项hash锚、正式合同与禁止改写规则。后续E1--E7可以通过新wrapper复用算法，但不得覆盖E2证据；改变算法语义必须视为新身份。

E1 280 kWh结构门在commit `c20dae18`执行。正式目录`baselines/e1_model/e1_submission_20260711_committed/formal/`含20条从冻结E2无改动复用的mixed证据、5条200c CV-only 4000评价搜索和5条EV-only可行性审计。mixed/CV-only全部零违规、成本分项闭合；200c mixed的EV客户/需求/距离份额均值为0.861/0.872/0.822，平均59.8次充电，相对CV-only 4胜1负、平均成本优势0.671%。EV-only五条均为`NOT_FOUND`，原因是直接路线转换时至少一条CV路线没有可行车场充电窗口；不得表述为数学不可行。判决`E1_280_STRUCTURE_SUPPORTED`，E3解锁。

## 2026-07-11 E3累积消融正式收口

E3新runner绑定staged hybrid、280kWh、200c、seeds1--5、每层4000评价；M0总预算在两个独立车场间平分，并在候选期实时重建跨场服务计费。30/30零违规满预算，hash和保存解完整。最终判决`E3_PARTIAL_MECHANISM_SUPPORT`：固定路线时变碳充电5/5降EV间接排放，平均20.96%，总电量一致；M1对M0成本4胜1平、平均低1.042%，但跨场服务仅seed4出现2个客户；M5 theta=1全部可行，但M4对应解本已全部满足最小收益比>=1，公平绑定0/5。E3不包装六层全强，碳进入E4，公平进入E6。正式证据在`baselines/e3_ablation/e3_submission_20260711/formal/`，解释见`docs/handoff/e3_cumulative_ablation_closeout_20260711.md`。

## 2026-07-11 E2负例恢复比例候选收口

`proportional_true_lns_middle_gate` 27/27满1600评价、零违规，保存解、算子记录、hash和运行提交`7b164f6a`独立验收通过。候选相对staged全部9组平均-0.329026%，6个开发负例平均+0.095425%，负例只转回1组，最差保护样本-3.005064%，判`PROPORTIONAL_TRUE_LNS_MIDDLE_SHORT_GATE_REJECTED`。具体是100c seed2改善+11.712%，但50c seed5、75c seed1和75c seed5分别退化-7.773%/-4.737%/-3.005%，阶段比例改变不具稳定跨规模效果。true-LNS比例路线关闭，不启动57次未见种子4000门。下一步只读已保存staged/LNS/restart/true-LNS解的route-signature互补性；无广泛可行整路块headroom则直接停止E2恢复并转80 kWh。

## 2026-07-11 E2 15负恢复最终收口

整路块审计从staged、LNS、restart、true-LNS和proportional true-LNS的已保存解中提取路线，用set-partitioning+no-good枚举整路组合，新搜索0次。9组45父解零违规；6/6开发负例有可行混合组合，但0/6比当组最好父解便宜>=0.25%，0/6多救回负例，verdict=`ROUTE_BLOCK_HEADROOM_NOT_SUPPORTED`。这证明不同运行有路线多样性，但现有整路块没有可组合的性能headroom；HGS/SREX不解锁、未见种子和论文种子恢复矩阵取消。项目1/2以冻结E2的25胜5平15负、总成本领先LNS 6.845690%收口；当前主线转项目3的80 kWh稳健性镜像门。

关闭后补做HGS-CVRP、PyVRP/SREX、混合车队HGA、多车场绿色VNS与仓库现有SWAP*-lite的源码/文献复核。更强方法理论上仍可能改善个别负例，但需要新的种群、完整SWAP*、route elimination、SREX修复和ReSETP充电/多车场/多趟适配，是新求解器项目。现有SWAP*-lite只原位交换、不减路线数，且通过`score_reference()`绕过`EvalBudget`，不能公平直开。因此E2恢复继续关闭，不宣称绝对无解，但不再为15负投入当前论文周期。

用户随后要求不删除更强方法：“种群搜索+完整SWAP*+路线消除+SREX+充电修复”统一登记为后续遇到路线生成瓶颈时的长期备案，不作当前E2第四轮rescue。遗留编号1--6、9只在`docs/handoff/e2_legacy_items_1_6_9_execution_plan_20260711.md`维护统一顺序和解冻条件。

80 kWh项目3已解锁并完成接线短门。新runner从冻结tag `e2-submission-20260711`/commit `0124623e`的独立worktree运行算法，读取激活的L-main v3 manifest，不复用纯CV起点旧脚本或旧ALNS通用入口。50c seed1的pair/LNS各200评价接线门2/2搜索、3/3展开证据行全部满预算零违规，`E2_80K_PREFLIGHT_READY`。正式矩阵固定24搜索任务/36证据行，任务账本与展开表分离，默认2 workers和30分钟低频watchdog；等runner/验收器提交后启动正式门。

80 kWh首轮正式门在20/24时按规则停止：200c staged-hybrid-carbon-pair的seeds1--3都被checker抓到后续客户时间窗违规。根因是`_fixed_charge_latest()`只根据直接successor计算充电最晚时刻，碳择时可以在下一客户不迟到的情况下拖迟更后客户。修复为从路线末端反向传播全部due time。原三个失败保存解在不重新搜索时回放均为零违规；42项定向回归通过。修复冻结于`40bd2883`，200c seed1的pair/LNS各200评价短门2/2满预算、零违规并独立验收通过。这是正确性修复，不改时间窗、成本、检查器或预算。重跑时不强拉并发，保持2 workers，仅将大任务优先调度以避免尾部单核等待。

80 kWh修复后正式门已收口：24/24搜索、36/36证据行、全部满4000评价零违规，独立复算与全套hash合同通过。12组hybrid/LNS为9胜0平3负，平均优势4.677%，汇总优势10.370%。但15c、50c规模均值小幅为负，只有2/4规模不输，未过事前3/4门；50/100/200c则全部通过EV工作量和充电可见门。verdict=`E2_80K_MECHANISM_VISIBLE_ALGORITHM_NOT_ROBUST`，项目3停止扩跑、保留为敏感性证据；主线进入项目4精细碳感知搜索。

## 2026-07-11 E2最终十次统一比赛合同

用户否决单独的完整模型复核层，要求E2本身成为全体算法统一比赛：9个L-main v3自有算例×9算法×每组10次×4000评价，共810行。算法集为staged hybrid、GA、PSO、VNS、ACO、GA-VNS、LNS、GWO、IWD；旧ALNS-Wouda不参赛，立即充电版移交E3消融。冻结225行主表在同合同下复用，只补585行。长跑前先做27项200评价接线门和18项4000评价代表门，两关只检正确性、预算、活性、保存解和恢复，不按输赢筛结果。

280 kWh为正面主场景，80 kWh为备用；E2关闭公平、跨场费0。自有算例不制作BKS/AVG/Gap%标准表，仍保留十次均值、标准差、最好值、时间、可行率与配对统计。公开标准算例的BKS/AVG/Gap%以及未经改动Goeke原始算法挂为E2完成后的补实验。E2最终收口后立即准备E3；客户原始归属、非零跨场费用和线性碳配额参考建模继续挂账，不得阻塞E2。

## 2026-07-11 算法创新口径冻结（写作挂账，不阻塞E2）

当前算法的诚实定位是：面向本问题的分阶段 ALNS--LNS 混合求解框架，外加固定路线下的碳感知充电重调度。它不是已证明的全新 ALNS：ALNS 基础动作、AlphaUCB、SA、强重组、贪婪/后悔修复和低碳充电均有已有来源；中段 strong-bridge 是项目既有 LNS 强重组的隔离复用，`chain_ucb` 也只是既有 AlphaUCB 奖励设置。独立执行包只证明不再误走旧入口，并不自动构成理论创新。

E2只检验统一预算下的性能，不能以排名替代创新证明。论文当前允许写“提出分阶段 ALNS--LNS 混合求解框架，并嵌入固定路线下的碳感知充电重调度模块”；禁止写“全新 ALNS”或“全联合碳感知路径搜索”。E2后以最近文献对照、四臂消融（普通独立 ALNS / 直接强重组 / 分阶段混合 / 分阶段混合加充电重调度）、流程与来源、复杂度和局限说明来决定最终创新力度；若证据不足，就降为有效的混合求解框架。详细合同在`docs/handoff/e1_e7_submission_contract_decision_20260711.md`，问题登记册B4a负责跟踪。

## 2026-07-11 E2十次代表门验收逻辑修正并通过

50c/150c × 九算法 × seed6 的18项代表门均完成4000评价、零违规、保存解和hash齐全，当前检查器18/18复算。初始门禁把`algorithm_specific_update_count >= 1`当成“算法真实活动”的唯一证据，因IWD两项未超过共同起点而误判暂停；源码和操作台账显示两项均执行3810次`iwd_construct_sa`和190次`iwd_iteration_best_lns`，只是没有找到更优解。验收现改为：算法专属更新或非空算法专属操作台账任一成立，仍无两者才停。定向测试5项通过；不改变任何算法、预算、评价器、成本、物理约束或既有解。最终代表门`E2_10SEED_REPRESENTATIVE_READY`，18行可复用，正式还需567项。

## 2026-07-11 线性碳配额文献核对闭合

本项目目标函数中的`p_car(DeltaE-CE)`与目标期刊陈婉茹等（2023）式(5)以及Liu等（2020）式(15)一致。陈婉茹等在第5.2.1节直接说明，碳限额与决策变量没有直接关系，理论上改变限额不会改变最佳配送路径；Liu等也报告碳配额不决定路径，只改变碳成本和总成本。结论是：当前限额交易公式属于正确的会计建模，不需要为了让配额“起作用”而改模型；但论文必须停止把CE敏感性写成路线机制实验。真正能改变解的是碳价对可变排放的边际惩罚，以及本文时变电网碳强度对不同充电时刻排放的改变。CE参数表和绝对成本口径仍需统一；若未来要让配额本身改变路线，必须明确改成硬上限、分段交易价或其他非线性政策，并视为新模型。

## 2026-07-11 客户原始归属文献核对闭合

源码和算例审计确认，L-main节点结构没有客户owner或公司成员字段；现有1425条`customer_owner_manifest.json`的规则明确为`nearest_depot_by_bundle_distance`，属于事后构造，不是从原始Goeke数据恢复。文献也不存在统一的“客户天然归最近车场”规则。目标期刊陈婉茹等（2023）的正式模型允许客户由任一车场车辆服务，最近车场只是初始解构造；Soriano等（2023）在合作前给每个客户一个明确所属车场`d_i`并把它当输入；Liu等（2020）以各公司合作前自有客户定义原始关系；王勇等（2023）则在自己的资源共享场景中采用时空聚类后最近配送中心指派。当前建议因此收紧为：最近车场可以作为L-main自有算例中性、可复现的**合成独立经营基线归属**，但论文必须明确它是场景假设，不能称原始数据真值或行业常数。E3/E6使用前仍需用户拍板并冻结映射/hash；若另做历史客户簇或不均衡公司成员关系，应作为独立敏感场景，不得静默替换。

## 2026-07-11 跨场费用来源与量纲核对闭合

定向核对同行原始论文后，未发现`95 GBP/跨场客户`是行业统一价格；仓库`prices.py`本身也把95标为研究代理。同行对合作成本的处理依赖真实业务含义：Gansterer等（2021）和Soriano等（2023）最小化实际线路成本，并用客户保留、利润下界或事后补偿处理企业间利益；Fernández等（2018）的SCC-VRP在货物确需先移到服务车场时，按每对车场是否发生一次往返收固定启动费`F`，测试`F={0,20,50}`，明确不是每个客户各收费，也不是英镑报价；王勇等（2023）的资源共享模型按集中运输时间/距离计费。由此判定，当前`cross_site_cost × 跨场客户数`把物理货物搬运和企业间补偿混为一谈，95又大于现有整车启动费，不能继续作为唯一主值。0可保留为共址/货物已共享的完全共享基线；若货物必须搬运，非零成本应由车场间往返距离、时间、车辆启动和载荷构成；若只是企业结算，应进入收益分配而非重复加到物理成本。若投稿周期内保留每客户代理，只能标为未校准的摩擦敏感性并相对客户收入和线路成本解释。最终规则仍须用户批准，事实核对本身不改变正在运行的E2。

## 2026-07-12 E2十种子长跑并行调整

正式矩阵原以2个工作进程运行至608/810且无HALT/Traceback。旧父进程未响应自然切换，已安全停止旧父进程和当时两个在途子任务，确认不再有旧runner后从608/810断点启动唯一的6-worker runner。机器为8逻辑核、8GB内存；6 workers为当前上限，保留系统余量。该调整只改变任务并行度，不改变算法、预算、成本、物理约束、场景、评价器、种子或任务矩阵；若资源异常或速度反而下降，立即退回4个工作进程。X86迁移清单见`docs/handoff/e2_x86_migration_handoff_20260712.md`。
- [M1/E2正式收口 2026-07-12] E2十种子正式矩阵已封闭主证据：810行=9算法×9个L-main自有算例×10种子，每行4000完整评价，810/810零违规、当前checker复算和解/hash完整；`staged_hybrid_carbon_aware`总排名第一，决策`E2_10SEED_PRIMARY_LEAD_SUPPORTED`。F2曲线和基线参数附录已生成。8项16000长预算预检仅作补充稳健性证据，不改变E2主表。
- [M1/E2封存 2026-07-12] 8项16000评价代表预检完成并通过：每项精确16000评价、零违规、解/hash齐全；hybrid总成本低于LNS，三个旧负例全部改善，200c强胜守门样本未丢。E2主表仍是810行×4000完整评价，16000结果只作稳健性补充，不再继续E2 rescue；研究主线转E3准备。

## 2026-07-12 WP0投稿合同与E0地基

E2封存后先完成WP0，不启动E3–E7正式搜索。投稿合同已冻结为：280 kWh主场景、80 kWh稳健性对照；客户归最近车场的1425条映射作为合成独立经营基线并锁hash；c_tr=0为完全共享主值，10/25/50/95仅作无现实标定的摩擦敏感性；默认碳配额=0且只作会计项；公平默认关闭，仅E6/E7公平交互臂在搜索阶段启用。`prices.py`默认跨场费已从95改为0并保留旧代理痕迹，TeX参数表同步c_tr主值，四项TeX欠账登记在`docs/handoff/tex_sync_debt_20260712.md`。

WP0机器证据：合同判决`E1_E7_CONTRACT_FROZEN_BY_USER`；E0九个L-main v3算例的registry/manifest/hash/正式入口和共享起点检查全部通过、零违规（`baselines/contract_audit/wp0_e0_check_20260712/`）；3个E2冻结解在280 kWh覆盖下以新默认c_tr=0复算，零违规且成本逐位一致（`baselines/contract_audit/wp0_e2_replay_20260712/`）。本阶段没有启动E3–E7搜索，下一步才是WP0通过后的E3短门。

## 2026-07-12 TVCI-ALNS名称同步

当前创新算法的公开名称暂定为`TVCI-ALNS: Time-Varying Carbon-Intensity-Guided ALNS`，中文为“时变碳强度引导的自适应大邻域搜索”。代码提供新名称的展示/API入口，同时保留`staged_hybrid_carbon_aware`兼容标识以保护已封存E2数据和历史脚本。该名称只统一表达现有组合式方法：分阶段ALNS--LNS路径搜索内核，加上固定路线下按时变碳强度重调度充电时刻；不把它写成全新基础ALNS或路线、车型、充电站、充电时刻的全联合碳搜索。本次同步未启动实验，也未改变模型语义。

## 2026-07-14 E2—E3主稿整合与统计拨正

E2与E3已直接并入 `docs/paper_submission_final/paper_main.tex` 并生成18页主PDF。E2统计单位由90次重复运行拨正为9张独立网络：先在网络内汇总，再做Friedman总体检验和TVCI-ALNS对8种算法的精确Wilcoxon检验并作Holm校正；“IWD 90胜0平0负”的旧表头方向歧义已消除，真实含义是TVCI-ALNS在90次运行中全部优于IWD。正文结论收紧为显著优于6种对照算法，对LNS和GA-VNS不宣称显著。

2026-07-14 E4经只读复算后进入主TeX：不重跑路线，仅核对`e4_forecast_timing_formal_20260713`封存数据。9072行结果、132300条充电动作、3024个基础配对和262个清单文件全部闭合；四情境充电排放下降3.888%--4.877%，运营总排放下降0.352%--0.523%，日改善18--20/28，95.46%--99.71%的净减排来自前夜首趟窗口。主张边界固定为“择时是附加小杠杆，协同没有跨网络与跨电网日的稳定放大”；碳价重优化臂挂账。主PDF21页编译通过，E4一图一主表、逐日附表和Cheng等(2022)准确引用已入稿。

2026-07-14 E4正式关账：终审再次从原始行复算四情境全部头条数字，验证3024对路线/服务/用电量不变、9072行零硬约束和时钟违规、262项哈希零漂移，并重新编译21页主PDF。E4不再追加为追求方向而设计的正式批；碳价重优化降为全文主体完成后的挂账敏感性。远端标签`e3-paper-freeze-20260714`指向`de0ce77d`，保证E3及以前可独立回退；E6/E7从此分批提交。

E3正文以同一九网络呈现“地理组织先取得效率、合作再取得剩余增量”的两层结果；9/9同向的重复计数和概率值统一放入表注，不再占据每一行。算法收敛图按陈雨蝶等（2025）同型图改为九算法全展示，算法名统一英文缩写，图例固定在图内右上角并通过扩展坐标范围留白避让。正文常规表统一为0.84倍行宽，附录宽表为0.92倍行宽。E2、E3及充电复算使用同一九网络；E6/E7尚无正式结果，先以114客户中位网络做不入论文统计的小探针，通过后才扩展到同一九网络。

## 2026-07-15 E3趋势补强与E6多级保障准备

E3在既有地理责任与空间交错责任之间增加一档跑前冻结的中等责任图，不改变任何旧结果。中等图只读取客户编号、需求、两种既有责任标签、客户到两场距离、班次和需求档，不读取成本或搜索结果；九张图的责任偏离度约为原交错图的一半。正式增量批固定为九网络×三种子×固定责任/开放合作两组，共54次同起点、同4000评价搜索；开放合作保留固定责任方案作为合法保底。旧地理责任4.157%的原始已观测结果和5.309%的零搜索包络预览必须并列，禁止静默替换。

E6从单一“双方均不比各自经营差”的端点扩为五档参与保障。每组先由无约束合作解确定较弱车场的收益比，再等距提高到1；自然已经满足参与条件时复用同一解，避免四次无价值重复搜索。正式展示使用跑前声明的固定候选池筛选已观测前沿，并同时保存每档原始搜索，正文必须披露每个前沿点实际接触的候选池和总评价次数。上述两项只是运行器和输入冻结，尚无正式新增搜索结果。

## 2026-07-15 E2b、E3与E6新增正式证据

E2b四臂45个成对单元全部闭合：分阶段B相对连续A平均变差77.166，专用跨场C相对B平均改善292.681，固定配送后的充电择时D在39/45单元降低间接排放。E3中等责任档27对搜索完成，三档网络斜率9/9为正但严格单调仅4/9；方向性关系成立，逐网单调不成立。E6五档54组、270点完成，174次实际搜索、96档复用；保障推进到1时地理聚集/空间交错的网络等权平均成本增幅为1.8956%/0.3857%。这些结果覆盖本文件此前“尚未正式搜索”的旧状态，旧行保留为开跑前历史。

## 2026-07-15 E7三网络正式合同与当前状态

正式矩阵冻结为3网络×2责任×5流×4臂=120任务。新增订单必须在两类责任下归属一致且对应车场可直接响应；完整机制、禁止合作、不设参与底线和一次顺序插单使用同一冻结流，不按结果方向筛选。封闭预算内找不到可执行延续时保留为臂失败；只有四臂均完成的网络—责任—流才进入成对差。全日充电28日复算固定路线、车辆、客户服务和电量，并保存每次充电的合法窗口见证以保持事件触发时车辆状态。V5 120任务预检及840行干运行通过，50次评价正式矩阵已启动。可提交正式载荷以`sessions.json`为准，断点`.tasks/`不进入权威哈希清单。

## 2026-07-15 研究—实验—写作质量门与E7预封存审计

用户提供的运筹优化论文方法已选择性转化为`docs/handoff/resetp_research_experiment_writing_quality_gates_20260715.md`。项目主线固定为重要运营问题、可被结果否定的主张、必要方法、有解释力的对照证据和适用边界；不机械补齐所有实验，不把算法必须显著最好设为成立条件。论文引言改为现实决策矛盾优先，贡献由四项清单收束为三项。E7正式运行仍只由hooks监控；预封存代码增加精确120任务/30×28日电网日/经济闭合/失败臂/响应时限检查。因冻结重放脚本不写滚动窗口和桩容量计数，另加`audit_e7_replay_invariants_20260715.py`在重放后生成独立四件套并逐行复算窗口、桩容量、路线/电量哈希和排放闭合；总审计和论文反向审计均必须直接验证该包。正式结果、28日重放和独立审计仍未完成，不能将pending审计当作PASS。

完整目标终验另补E1/E2不可漂移证明：历史`file_count/files`清单按原结构逐项验哈希，不用新格式误判或倒填；E1完整目录与`28c91128`、E2完整目录与封存tag解引用提交`1180abf3`再做Git树路径和字节比较。E2两份与封存提交同时加入、但未进入旧清单的基线参数表只作为显式历史例外，由Git树覆盖。论文终审同时要求统一中英文题目、无附录、五章顺序、E1/E2判决数字和IWD简化适配边界一致。

论文构建终验于2026-07-16接入：统一XeLaTeX入口当前生成24页A4，实际21个TeX/类文件/表图输入不晚于PDF，日志无致命或未定义引用，核心正文可提取，代表页视觉无裁切。macOS `STHeitiSC-Medium`在旧MiKTeX/xdvipdfmx下缺ToUnicode，黑体标题文本提取不完整；临时Tectonic无可用产物且无安全替代CJK黑体，因此保持期刊版式并显式列warning。最终E7表格生成后必须重编，否则输入时序门自动失败。

E7结果叙事门于2026-07-16接入：最终展品不止三张汇总表，还必须由封存逐流证据自动生成中英文摘要、结果解释和结论。摘要同时列三类对照，不按方向挑选；正文必须披露完整配对与失败身份、三类对照的改善/变差/持平和极值单元、经济账本/服务量分解、阶段时限，以及28日固定配送方案重放的方向计数与范围。不得把均值方向解释为单一机制因果或把零搜索重放写成联合优化。故事审计从封存CSV重算四段文字后逐字比较，四套E7决策未齐时七件展品均不得存在。当前只完成代码、条件挂钩、17项测试和pending稿重编，正式状态仍等待hooks事件。

最终交付物完整性门同步接入：E2b/E3/E6与最终四套E7证据必须逐目录具备metadata、raw runs、decision、artifact hashes和report五个文件；最终模式还必须在HANDOFF、总memory、动态memory和本文件同步落正式收口标记。该标记不作pending占位，只有四套E7决策、七件论文展品和终稿编译通过后才能写入。相关定向回归当前为19项通过。

总目标完成矩阵已落`docs/handoff/resetp_goal_completion_matrix_20260716.md`：逐项列出统一主线、封存不漂、E2b/E3/E6、E7及28日重放、七件展品、记录同步和最终编译回归的权威证据与当前判定，并冻结hooks事件后的十步收口顺序。E7及其下游仍明确标为未证明，任何单一PASS不得替代总目标完成。

2026-07-16新增E2b/E3/E6原始身份矩阵终验。故事审计不再只核对五记录面、哈希和汇总判决：E2b从`raw_runs.csv`与`task_manifest.csv`重建九网络×五种子×四方案的180行证据、135行实际搜索及45个成对单元，并复算三组递进差异；E3重建九网络×三种子×两方案的54行和27对，复算原始/保底节约率；E6重建九网络×两责任×三种子×五档的270行，复核174搜索/96复用、参与阈值和成本增幅。三项终验均通过，未接触E7运行状态或保护源；E7及其重放、独立审计、七件展品和终稿仍等待hooks完成事件。

同日补齐E4时变碳主证据在总目标矩阵中的遗漏。新增审计从132300条充电动作聚合回9072行三种时机，再重建3024个种子—日期配对、1008个种子平均单元及网络/日期/四情境汇总；路线、服务、能量、充电量和燃油直接排放均须在同一配对内不变，预测择时的目标值、实际结算排放、实际先验下界及动作账本均独立闭合。262项全局清单零漂移，正文减排区间、18--20个改善日、负向反转、前夜首趟贡献和协同效应两轴不一致均由原始量复算。该项只强化E4既有封存证据，不新增搜索，也不读取E7运行态。

2026-07-16正式E7出现的唯一监控异常为原12小时上限触发。原事件包显示暂停前运行健康，且原runtime登记的7个保护对象经当前文件逐项重算均零漂移；因此按监控器恢复合同续跑同一PID/PGID 96207，而非重启或增加预算。六个原worker恢复后各约占一个核心。v2配置仅将监控窗口延长到172800秒，并沿用正式命令、6 workers、`RUN_FINISHED.json`和三项结果文件；`resetp-e7`心跳已改为只接收新监控目录事件。该恢复不产生论文结果，也不改变E7及下游仍为未证明的总目标判定。

同日完成E7收口链可执行性审计。修复非保护的不变量审计脚本在加入仓库根路径前导入项目包、从普通命令行直接执行会失败的问题，并新增无`PYTHONPATH`、仓库外工作目录的隔离加载测试；独立总审计对非空旧输出目录改为硬拒绝，避免失败残留静默进入新清单。冻结的28日重放源保持不动，完成矩阵只增加“输出目录非空即保留并停止”的运行门。29项E7与论文聚焦回归通过；E7正式及其下游证据仍等待hooks事件。

进一步确认原监控暂停会污染阶段墙钟：动态阶段使用`time.perf_counter()`，且超出下一触发间隔会终止。旧事件和runtime核准SIGSTOP为13934秒，已固化事件证据及哈希。新增重放前只读门，任何PASS阶段耗时不小于该时长即拒绝；独立总审计和故事审计重复强制。若外部暂停导致当前运行退出，只允许用相同合同、断点、种子和预算重跑未获得无污染完成的原任务，不把治理事故写成算法失败，也不按方向挑任务。同步假执行器证明失败任务不写完成断点、同合同恢复只补缺失任务；35项聚焦测试通过。

2026-07-16全量回归边界：项目金标准Python下`solver/tests`为633 passed、1 skipped、5 failed（639 collected）；五项已归类为旧E2保护commit、旧E5车队上限/修复诊断、native autopsy旧字符串契约或未提交论文工作树保护，不进入正式E7/论文通过证据。扫描/规模单测按当前九张正式三班倒注册表和实体车硬上限修正，AppleDouble sidecar已从源码审计排除；E7/论文聚焦套件35 passed。

2026-07-16数学审计与两层模型门：`paper_math_audit_20260716.py`为PASS（14项通过、0项失败、1项警告），`two_layer_model_gate_20260716.py`为7/7通过并授权TeX重构。唯一警告是固定碳配额在单一价格下只产生目标常数平移，正文必须限定会计范围；这不改写封存实验数字，也不代表E7或终稿已完成。此前`HALT_FORMALIZATION`仅为过时快照，已修正当前入口文档。

2026-07-16充电时间量纲显式化：主稿在连续充电核算段声明连续时间变量统一以秒计，30 min电网时段换算为1800 s，功率以kW计；未改公式、程序账本或封存实验数字。重新编译后为20页A4，pending故事审计、数学14/0/1、两层7/7通过，改动后的22项模型/E7/故事定向测试通过；E7正式及下游终验仍未完成。
# 2026-07-18 中国V2正式月份、价格与车场阶段门

中国主实验正式碳年份回退为真实可核的2025，不使用构造2026碳值。结果盲筛选锁定2025年2月全28日为正式稳健性面板；默认展示日由用户在A/B/C/D决策面中预选，选后不得按正式结果换日。

九城2025年2月绝对电价已由七套同月价表覆盖，价格数据本身不再缺城；正式接入继续等待九个普通商业车场的合同电压、单/两部制、容量、计量和利用小时档。九城普通商业车场设施身份来源9/9验签，但货车入口、外来配送准入和现场车辆桩仍0/9。有向道路矩阵只在WGS84货车门与充电节点锁定、E7计时隔离解除后生成。

当前中国参数锁验证仍为FAIL且恰有30个明确阻断：门/运营/充电各9，订单属性重校准、PPS位置重校准和英国核心退役各1。该FAIL是正式搜索禁令，不影响继续做来源取证、地图候选和零搜索构造。
## 2026-07-18 E7步骤1--6闭合

用户批准成对时效验收v2后，E7九项清洁计时检查点完成零重算收口。父系四项在5%相对误差内复现历史真实耗时，子系五项移除的共同暂停偏移为5964.73--6812.21秒，全部非计时载荷一致、历史包未修改、结果方向未参与纳入。暂停门、28日840行零搜索重放、重放不变量、120任务独立总审计、七件论文展品和最终步骤1--6证明均通过；2个受控失败继续保留。最终证明只关闭当前搜索版本，不代表ALNS预算G0、公开基准、非线性核心、中国方案正式接入、受影响E2--E7统一重跑或论文终稿已经完成。任何算法、物理或参数版本变化仍须用户批准并按影响矩阵重跑。

## 2026-07-18 官方HGS B门与A桥

用户批准官方HGS“先B，强向好则A”。固定`vidalt/HGS-CVRP`提交`1a927955cd2861a29d978f0d359d6e647db9319c`在三个非冻结CVRP开发题、三种子、每次3秒的预注册门中18/18有效；HGS三题中位gap为0%、0.0178%、0.9187%，相对当前ALNS中位成本改善11.2198%、12.1617%、12.7406%，机械判定`GO_A_ENGINEERING_DISCOVERY`。随后完成MIT许可与二进制哈希冻结、本机C++构建、官方5项测试、Python CLI桥和独立客户覆盖/容量/目标复算，A桥判`HGS_CPP_PYTHON_BRIDGE_READY`。

该结果只证明官方CVRP引擎是值得继续研究的结构底座。官方实现不支持硬时间窗、异质车队、SOC、非线性充电、分时价格、碳、公平或多车场，不能作为Solomon/Homberger或完整ReSETP求解器。当前未改正式ALNS、三份保护文件和封存证据，未授权China81、E2--E7重跑或阶段二。

## 2026-07-18 中国订单属性补充终裁

订单属性方法审批已闭合：容量占比需求代理、文献案例服务时长和交付时间窗完整经验行联合重采样均获批并同步主TeX。机器合同继续保持`formal_search_allowed=false`，因为本批准不启动阶段二，不能替代道路全矩阵、零搜索可行性见证和能源见证。独立Python验证、现有数学审计、两层模型门与XeLaTeX双编译均通过；搜索评价为0。

## 2026-07-18 机制化HGS--ALNS开发门

执行权限为隔离开发，不是正式试验。来源追溯与主TeX引用已经闭合；最小骨架的预算0/1/2/5行为门通过。通用三方门在25客户三结构×三种子×B100下仅6/9同时胜纯HGS式外层和纯ALNS，未达到用户硬门。多车场单时段结果盲开关在单一25客户门出现3/3双赢，但扩到10/15/20/25/50客户后仅4/15双赢，且20、50客户出现明显中位退步，故不允许以事后规模阈值挽救。当前机器判定=`HOLD_MULTIDEPOT_SWITCH`、`formal_search_allowed=false`。下一执行单元改为四个机制动作各自的病灶开发门；只有独立效果成立后才能重组，不得启动正式算例、China81、E2--E7重跑或阶段二。

用户随后取消开关。真正交错的HGS式子代+短ALNS教育在多车场五规模十五个B100任务仅1/15双赢；改成保留80% ALNS预算、固定追加跨场责任移动和车型—补能收口后为5/15，跨场动作仍大多失活。280kWh诊断开发面提供了第一条受限强阳性：25/50客户六任务6/6双赢；20客户B100为1负2平，B500时组合与纯ALNS三种子均精确到`621.2913242409613`。现有“每任务严格双赢、平局失败”门未过，故仍禁止正式实验和阶段二。下一步一方面继续为公平、碳价冲突和动态修复建立机制活跃开发门，另一方面等待用户决定是否允许“共同饱和值平局=非退步通过”的规则修订；不得删除20客户或设置结果后规模开关。

## 2026-07-18 阶段二 G1 独立输入线

用户批准在 G1 开发期间提前完成不依赖 G1 的输入、数据和治理工作。该授权覆盖本地道路图/矩阵、九城基础设施与中国参数证据、MC-001 订单属性、China81 数据层、零搜索数据检查以及统计、运行器、监控和审计基础设施。

正式验收仍受 G1 冻结门约束。G1 冻结并与阶段一统一前，不得把这些中间产物解释为正式 China81 算法结果，也不得启动正式公开算例胜负、强基线比较、非线性机制验收或论文结论。执行合同见 `docs/handoff/china_stage2_g1_independent_execution_contract_20260718.md`，审批登记为 MC-007。

首批执行产物已经形成：MC-001 订单层覆盖 81 实例和 5805 条订单；本地 OSRM 图按五份冻结 PBF 和 CV/EV profile 顺序构建；可恢复有向三矩阵执行器严格使用同路线 annotation；正式搜索守卫在 G1、China81 和待批参数未闭合时 fail closed。九城公共站 OSM 候选覆盖 8/9 城，但功率、枪数及运营方来源正式充分性仍为 0/9；成本代理、车场/公共站情景和 E5/E7 数值效应阈值继续挂账，不得静默采用。

## 2026-07-18 原装开源底线已过、完整合同仍 HOLD

用户进一步明确 E2 的底线是新算法必须胜原装开源算法，并把具体设计交由本 Codex。等预算拆件先否定 HGS 内嵌：官方 HGS 直接插入只在 1/6 对优于去掉 HGS 的版本，原生 HGS 路线进入路线池也未在两题 seed1 探针产生最终改善。按止损规则，HGS 不再作为候选内部组件，只保留为固定强对照；算法身份转为机制优先 ALNS。

最新固定 280 kWh、20/25/50 客户、三共同种子、B100 五方小门中，候选同时严格胜官方 Vidal HGS-CVRP 中性适配和原装 `alns 7.0.0` 中性适配 9/9，满足原装开源开发底线；相对当前项目 ALNS 为 6 胜、3 平、0 负。九任务总墙钟比当前 ALNS 约慢 11.9%，但快于两套原装开源对照；该短门不作正式速度结论。车型—充电整套方案选择在 25/50 客户六对相对自身消融 6/6 严格胜出，20 客户三对停在共同值 `621.2913242409613`。多车场责任、公平、碳—电价和动态订单仍无独立效果证据。

跑前完整合同把平局判失败，故机器总判仍为`HOLD_FULL_CONTRACT_SMALL_SATURATION_OR_COMPONENT_GAP`、`formal_search_allowed=false`。开发小门不能冒充正式 E2；正式合入、China81、E2--E7 重跑和阶段二继续禁止。只有改平局验收规则或启动正式试验时需要用户另批。

## 2026-07-18 阶段二 G1 独立输入自主冻结

用户明确授权把全部不依赖 G1 的工作一次性做完并由代理自主解决。MC-008 据此将此前待批项
冻结为透明情景，而非观测事实：场充 22 kW×2 枪，公共充电 60 kW×1 枪及
0.40 CNY/kWh 构造服务费，中国成本代理和 E5/E7 数值阈值均在正式结果前锁定。
`china81_stage2_static_inputs_v1_20260718` 已覆盖 81 实例、5805 订单、九城设施和
12096 条 2025-02 电价—碳槽。道路依赖链使用京津冀河北整图、广东整图和四川—重庆合并图，
为 CV/EV 共物化 1,578,948 个有向同路线三指标节点对，完成后自动执行零搜索审计。
正式搜索、非线性 SOC 和算法验收仍等待 G1。

## 2026-07-18 阶段一算法基础设施统一收口

没有改动“平局失败”合同。固定路线、车型、电量和充电时长的精确碳择时将旧20客户共同值
`621.2913242409613`严格降至`621.0831141941019`且零违规，旧“已到最优平台”解释作废。
当前算法身份为机制驱动ALNS，HGS只保留为强开源对照；跨车场责任、车型—补能整套选择、
固定时长碳择时、参与收益缺口和冻结历史新增订单五个部件均有独立账、绑定现场和无动作/删减对照。

统一证据位于
`baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v7_stage1_closeout_gate/`，
机器判定=`PASS_STAGE1_ALGORITHM_INFRASTRUCTURE_DEVELOPMENT_CLOSEOUT`。静态九任务9/9同时严格胜
官方HGS中性适配、原装`alns 7.0.0`中性适配和当前项目ALNS；多车场十八项中4项绑定改善
`1.2652%--5.6731%`、14项精确不倒退；固定100%独立收益底线在1个绑定种子修复、2个已达标种子
零动作；冻结E7单事件少1条未来路线并降成本`29.675379`。62行原始记录、六件主展品和上游哈希
经独立重算通过，15项回归通过，三份保护文件零差异。

这只关闭阶段一算法开发，不是正式benchmark或论文性能证据。公平仅1个绑定任务、动态仅1个真实
事件、三个多车场强对照属于事后确认；非线性充电和分时电价仍依赖阶段二接口。
`formal_search_allowed=false`、`formal_solver_integration_allowed=false`、`stage2_allowed=false`；
正式E2、China81、E2--E7重跑和阶段二必须用户另批。

## 2026-07-19 China81 G1 独立链失败关闭复核

逆向复核发现矩阵构建、诊断、最终冻结和一键入口存在四类“文件存在或上游自报即可
PASS”的漏洞，现已改为校验关键记录面哈希、独立静态计数、81/5805 全量身份覆盖和
关键判决字段。首次复算因审计器把实例内有向对并集误写为区域坐标笛卡尔积而 HALT；
修正审计口径并加回归后，既有冻结数据重新得到六批计数一致、1,578,948 对、81/81、
包级违规 0。复核五记录包判
`PASS_CHINA81_FAIL_CLOSED_REVIEW__FORMAL_G1_GATE_REMAINS`；没有启动 G1 或算法
搜索，正式验收仍等待 `G1-FREEZE-MERGE`。

## 2026-07-19 燃油路线减负—电动化联动搬移行为门

首次行为门在任何场景成绩持久化前因验收程序读取账本层级错误失败，失败现场原样封存。
恢复版只修验收程序并冻结算法、输入、阈值和预算；7件制品、19个输入、130个源依赖、
4个保护文件、账本和哈希经独立审计全部闭合，ALNS/HGS/完整路线搜索调用均为0。

绑定20客户场景构造44个中性搬移，得到10个可行唯一候选并完整收尾3个；三者均被通用
责任—车型补能—碳收尾恢复成原解，成本保持`621.0831141941019`、燃油路线`1→1`、
接受动作0。非绑定25客户全电对照保持`603.1548339805785`和完整内容逐位不变，收尾调用0。
机器判`STOP_ELECTRIFICATION_RELOCATE_RESIZE_BEHAVIOR`；旧三题、新D3、正式搜索、全量和
阶段二均不放行。后续若另立候选，必须把真实电动化边界放进筛选、固定已声明的客户搬移，
只在该骨架上联合选择车型、补能和碳时机，并用新鲜结果盲题验收，不得回头调本批。

## 2026-07-19 燃油路线退役—电动重整行为门

新候选把整条燃油路线放回待安置区，按后悔规则重组客户，必要时只做一级让位；
客户骨架固定后再联合选择车型、补能和碳时刻。测试、账本篡改探针和独立代码审计通过后，
唯一零搜索行为门在20客户绑定题形成9个唯一骨架并按预登记精算前4个。最低候选成本
`661.4407527272798`，唯一把燃油路线`1→0`的候选成本`685.7079097063714`，均高于源解
`621.0831141941019`，所以接受0；25客户全电对照严格零动作，路线搜索0。

首次调用结束后移动硬盘生成AppleDouble旁文件，封存程序按失败关闭。原始CSV和事故现场
先验签保留；恢复工具不重跑算法，只从已保存快照做8次独立成本/可行性复算，重建STOP判决。
最终13/13制品、原事故6/6哈希和四个候选快照独立闭合，旁文件0。机器判
`STOP_FUEL_ROUTE_RETIREMENT_EV_REPACK_BEHAVIOR`；同一20客户题调参救援、D3、正式比较、
全量和阶段二均不放行。下一候选必须把路线、车型、补能和车场在搜索中共同形成，先用新鲜
最低成本门证伪，不能把已失败的事后退役包装成创新。
