# E2-JRC 精确小邻域 v2 最终停止

- 科学合同：`E2-JRC-EXACT-NH-001`
- 执行版本：v2 absolute harness
- 终态：`FINAL_STOP_JRC_EXACT_NH_EXECUTION_FAILURE_V2`
- 日期：2026-07-25

JRC v1 启动失败证据保持不改。v2 逐项继承 v1 的三题、两臂、起点、8客户邻域、
每任务一次完整候选评分、30秒上限、六进程、效果阈值和停止规则，仅使用已验收的
绝对路径执行框架。

工程门通过：6客户独立无剪枝穷举与候选求解均得到规范最优值147；六个真实起点
全部完整复算可行，均选择出恰好8个客户；六个不同进程合计峰值330.71875 MiB，
低于4096 MiB上限；监督器 `COMPLETED` 且无异常。该阶段没有启动真实邻域效果搜索。

随后唯一一次六任务G0中，至少一个冻结任务在30秒安全上限内未能穷尽8客户邻域并
证明最优，抛出 `ExactNeighborhoodTimeout: frozen 30-second neighborhood limit
reached before proof`。因此没有形成完整六任务结果，也没有进入独立复算或效果阈值
判定。监督器看到的CSV字段缺失来自终止占位行，不是另一个科学结论。

按冻结规则，该候选最终停止：不延长时限、不缩小或扩大邻域、不换题/起点、不调
剪枝、不重试，也不以未证明最优的部分搜索结果作性能结论。没有获得匹配A/B/A+B
下一门、China81全量、公开BKS/SOTA、E3或论文主张授权。受保护三视角
`MV-HGS-SP` 未修改、未重跑，继续作为保底。

证据：

- 工程门：`baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v2/`
- G0终止：同目录 `g0_gate_v2/`
- 监督现场：同目录 `.jrc-exact-neighborhood-engineering-v2.monitor/` 与
  `.jrc-exact-neighborhood-g0-v2.monitor/`
