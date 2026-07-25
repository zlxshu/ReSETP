# E2 联合路线—充电精确小邻域最终停止

- 合同：`E2-JRC-EXACT-NH-001`
- 终态：`FINAL_STOP_JRC_EXACT_NH_ENGINEERING_LAUNCH_FAILURE`
- 日期：2026-07-25

该候选完成了隔离实现和六任务注册，但第一次受监督工程门启动时，监督器把相对工作
目录解析为候选包目录，造成命令路径和全部保护路径无效。子进程在导入工程门之前退出，
没有执行六客户等价证明，没有加载真实算例，没有运行任何真实目标搜索，也没有产生
性能结果。

冻结合同规定工程阶段任一失败均最终停止、不得救援。故不修监控路径、不建立 v2、
不重试工程门或 G0。该候选不能据此评价性能，也不得换名复活。受保护三视角
`MV-HGS-SP` 全程未修改、未重跑，继续作为保底。

证据目录：
`baselines/algorithm_prototypes/joint_route_charge_exact_neighborhood_20260725/engineering_gate_v1/`
与同目录下 `.jrc-exact-neighborhood-engineering-v1.monitor/`。
