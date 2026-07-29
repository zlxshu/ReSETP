# E3-RESPONSIBILITY-MISMATCH-01（2026-07-29）

权威目录为 `baselines/china_e3_e7/e3_mismatch_20260729/`，当前判决为
`HALT_PREREGISTRATION_METHOD_APPROVAL_REQUIRED`。这不是 E3 的效应结论；
结果盲 pilot 与正式 LOCK/FREE 搜索均未启动，也未读取任何臂间成本差异。

门二已按用户更正只在多车场适用域上用当前源码重放。45/45 个多车场实例的
搜索空间硬锁、完整候选守卫、路线池初筛与 MIP 二次过滤、最终证书守卫均通过；
LOCK 跨场数全为 0，FREE 在全部 45 个实例均可构造跨场。36 个单车场实例因
没有跨场拓扑而排除，完整清单在
`gate2_d3/excluded_single_depot_instances.csv`。该门搜索评价数为 0，旧 PASS
没有复用。

主展品 `cn-prd-50c-01-V2-LOCATIONS` 的 0%、25%、50% 输入预检均通过。
重指派客户数分别为 0、13、25；共同初始解路线数均为 9，并在 D2-A 的广州
总上限 5、深圳总上限 7 内完成 CV/EV 与充电动作分配。三个共同初始解均由
`check_solution` 和 `evaluate` 独立复算为 0 违约。这只证明输入可行，不是
LOCK/FREE 性能证据。

稳定性面板在冻结预注册前暴露两项需用户批准的方法边界。第一，当前结果盲哈希
排序的 50% 错配使 `cn-jjj-100c-01-V2-LOCATIONS` 的天津责任车场需要 10 条
确定性路线，而 D2-A 批准的 CV+EV 总上限为 7。第二，45 个多车场实例中有
6 个三车场和 6 个四车场实例，用户给出的“改派到另一车场”没有唯一目的地规则。
不得由执行代理自行扩大或跨场池化 D2 上限、删除稳定性实例、挑选可行子集、
引入未服务惩罚，或按结果更换重指派表。

恢复执行前必须由用户明确批准下列边界之一：为三/四车场冻结目的地规则，并允许
只按硬可行性条件化重指派；批准 D2/部分服务模型变更；或授权只运行已证明输入
可行的主展品并把稳定性面板保留为 HALT。在获批前不得启动防饥饿 pilot。

本轮为支持 D4 防饥饿观察，在未受保护的 `epochal_hgs.py` 和
`route_pool_sp.py` 增加了与既有完整候选计数对齐的评价轨迹、L 与 L/S 记录，并
在 E3 执行器中实现了 32/56/80 及向上加档逻辑；静态检查通过。但预注册未封口，
因此这些观测逻辑没有进入 pilot。`cost.py`、`check.py`、
`search/evaluation.py` 未修改，哈希见 E3 `decision.json`。

目录下 31 个中断前生成的输入子目录是
`UNSEALED_DO_NOT_USE_AS_FORMAL_EVIDENCE`；根 `artifact_hashes.json` 明确排除
它们。可引用的当前证据仅为根四件套、`report.md` 与已自封存的
`gate2_d3/artifact_hashes.json`。
