# 算法比较基础 v3：V13-MDVRPTW-28 + China81

日期：2026-07-19

用户要求模仿陈雨蝶的选择逻辑，而不是照抄其 CVRP 题名：先确定有资格的经典强手、
当前开源强手和最新相近混合算法，再从它们共同使用、带逐题 BKS 和原始开放文件的
算例中选公开主场；China81 是唯一完整模型算例。

现行公开主场为 `V13-MDVRPTW-28`，即 `PR11A/B` 至 `PR24A/B` 共 28 道
360--960 客户的大型多车场带时间窗题。公开主表按职责比较当前可验 BKS、经典
VCGP/HGSADC、PyVRP 0.13.4、MDFIHA、MDFIHA-ETGA 和本文完整算法。
`PR17A` 单独承担母体、独立破坏重建/精修、部分混合和完整混合的血缘解释。

开发块为 `PR11A/B、PR17A/B、PR21A/B`；确认块为
`PR16A/B、PR20A/B、PR24A/B`；其余 16 题封存。划分只依据车场层级、规模与
A/B 身份，不看算法结果。X-100 的零搜索审计继续保留，但它是未入选候选，不再
决定论文主表。

China81 最终只比较共享同一个 ReSETP 完成器的母体、独立机制 ALNS 和完整机制化
混合体。先用前两臂封存 `China81-BKS-v0`，再打开完整混合体；实例、解和检查器未
共同公开前，只能称“本研究当前最好可行解”。

零搜索证据
`baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/` 判
`PASS_MDVRPTW_V13_COMPARISON_FOUNDATION_ZERO_SEARCH`：28/28 原题语义匹配，
28/28 当前 BKS 经 PyVRP 和独立检查器双过，28/28 论文值抽取成功，求解器调用和
搜索评价均为 0。当前可验 BKS 在 28/28 题上均优于 2026 MDFIHA-ETGA 论文值。

同路径证据
`baselines/algorithm_foundation/remix_same_path_equivalence_gate_20260719/` 判
`PASS_REMIX_SAME_PATH_EQUIVALENCE`：母体、增强关闭和增强零预算在
`PR11A/seed1/5迭代`上解签名相同，组件调用为 0，独立验解通过。两份证据哈希
另行复核均为 0 失败。

多重混合蓝图允许多群体、ALNS、VNS/局部精修、精英路线池精确重组和以后经证据
支持的其他成熟组件，共享同一解、评价器、精英库和贡献账。组件数量和算法标签不设
人为上限，但无贡献组件必须删除。

用户后续批准了最低成本行为门和六题开发门。行为与接线均通过，但第一个完整 ReMIX
候选对同机较强核心为 `0 胜、0 平、6 负`，新 BKS 为 0；六题最强核心全部是
PyVRP 0.13.4 ILS。死因是削短 ILS 后，HGS 首解、五轮外置增强和末尾路线会审没有
偿还时间。权威判定=`STOP_CURRENT_REMIX_V13_CANDIDATE_ALL_LOSS`。当前停下复盘，
China81、确认块、完整 28 题、阶段二和论文优胜结论均未启动。
