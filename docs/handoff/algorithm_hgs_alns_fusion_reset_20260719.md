# HGS与ALNS真融合低成本复核及止损

- 日期：2026-07-19
- 判定：`STOP_CURRENT_GENERIC_EDUCATORS__GATE_NOT_FORMAL_DOUBLE_WIN_EVIDENCE`
- 边界：`formal_search_allowed=false`、`stage2_allowed=false`

## 结论

本轮把大邻域改进真正放进HGS每个子代进入群体之前，不是先跑HGS再跑ALNS。两类教育器都没有达到“同时胜纯HGS与纯ALNS”的冻结底线。

项目现有ALNS教育器只在2/6个实例上被接受，胜纯HGS 0/6、胜纯ALNS 2/6、双赢0/6。成熟依据的成段移除加后悔插入教育器在每个子代都发动时，4/6个实例有真实接受，但只胜纯HGS 1/6、胜纯ALNS 3/6、双赢1/6；六题总分`3923524.447669`，仍略差于纯HGS的`3922596.633687`。改成每2、4、8个子代偶发一次，三档仍全部失败。

因此这两种通用教育器停止，不围绕同六题继续调频率、移除长度或阈值。HGS继续作公开benchmark强对照；候选保持“机制驱动ALNS”身份，预算转向完整ReSETP中的机制专用教育和路线仓库精确重组。

## 公平口径与证据

六个Homberger-200代表题使用同一确定性可行起点、同一单种子、每臂名义2秒、单线程和同一独立复算器。后续红队审计发现：融合臂复用了旧批次基线；项目ALNS实际墙钟最高2.80秒；HGS另有随机起点池而ALNS没有；六题已经反复用于开发；跨题大惩罚总分不可直接相加。因此本包只能淘汰当前教育器，**不能证明任一算法公平地胜过或输给原装HGS/ALNS**。

权威目录：

- `baselines/algorithm_prototypes/algo_reset_20260719/route_core_microgate/`
- `baselines/algorithm_prototypes/algo_reset_20260719/hgs_alns_offspring_fusion_microgate/`
- `baselines/algorithm_prototypes/algo_reset_20260719/hgs_sisr_regret_fusion_microgate/`
- 同目录后缀 `_interval2`、`_interval4`、`_interval8`
- `baselines/e2_alns/pyvrp_hgs_0122_tool_freeze_20260719/`

各小门含`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`和`report.md`；候选解全部通过独立可行性与距离复算。来源与许可证见`docs/handoff/algorithm_source_and_license_register_20260719.md`。

## 完整模型后续两刀（同日）

第一刀不是再把ALNS塞进HGS，而是保留HGS与ALNS各自完整路线，把两边路线放进精确集合划分仓库，再统一经过跨场责任、车型--补能和碳择时专家。人工互补路线功能门通过，但真实多车场25/50客户预登记筛选中，精确程序分别只选4/8条ALNS路线、HGS路线0条，最终成本逐位等于ALNS父解。判`STOP_ROUTE_POOL_FUSION_NO_STRONG_INCREMENTAL_SIGNAL`，路线仓库方向停止。

第二刀把车型--补能和碳择时提前到ALNS每个完整候选参加接受/淘汰之前。源码先冻结，再用既有完整源三班生成方法、donor02和25/50源规模生成两道新结果盲多车场开发题（实际60/112客户）。候选完整评价与v7均为100次且可行，但候选相对v7倒退7.207%和5.416%；机制虽分别产生15/36次局部改善，却额外做1456/2297次路线代理评价，并把搜索过早牵引到较差结构。判`STOP_MECHANISM_NORMALIZED_ACCEPTANCE_NO_STRONG_SIGNAL`，不扩三种子、不调频率或阈值。

两刀共同说明：当前有效互补来自“路线搜索完成后，机制专家补齐HGS/普通ALNS不会表达的决策”；把HGS路线硬混进来或让机制专家支配每一步搜索，都没有增益。阶段一保留v7作为候选，但不恢复旧“9/9胜原装”的正式资格。

新增证据：

- `baselines/algorithm_prototypes/algo_reset_20260719/mechanism_route_pool_incremental_gate/`
- `baselines/algorithm_prototypes/algo_reset_20260719/fresh_donor02_mechanism_bundles/`
- `baselines/algorithm_prototypes/algo_reset_20260719/mechanism_normalized_fresh_gate/`
