# S3-TRAJ-V4 观察层轨迹重跑任务卡

本任务只在已封存的 S3 代表题四臂批次上增加求解过程观测，不重写 S3
`representative_gate/raw_runs.csv`，不改变算法、评价器、实例、种子、停止规则、
SP 时限或随机流。目标实例为已登记的
`cn-prd-50c-01-V2-LOCATIONS`，四臂为 `cv_only`、`naive_ev`、`mechanism_ev` 和
`MV-HGS-SP`，每臂种子 1--10。

运行器仅复制 PyVRP 0.12.2 的遗传算法主循环，在代理全局最优改善后复制当前路线骨架
和墙钟时间；回调不得调用完整评分、完成器、修复、随机数或求解器状态改变。每个 HGS
单元结束后，离线逐一完成骨架并用完整 `exact_china81_score` 复算，形成单调运行最小
完整成本曲线。

硬门：40 个单元的最终 `rerun_cost` 必须与封存 S3 raw 的 `cost` 逐位相等，且完整解
零违约；任一成本不等、不可行、验解异常、封存 raw 发生变化或保护文件漂移，立即保留
现场并判 HALT，不重跑、不换种子、不调参、不修评价器。通过后按预注册规则选择每臂
最终成本最接近该臂十种子均值的轨迹生成图4数据；该结果只授权观测层和呈现层产物。

正式命令使用仓库内 PyVRP 0.12.2 环境并发 6 workers：

`build/python_envs/pyvrp-hgs-0.12.2/bin/python baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/run_s3_trajectory_v4.py --workers 6`

产物包括新目录内的 `raw_runs.csv`、快照、离线复算、物化轨迹、`curve_data_v4.csv`、
`metadata.json`、`decision.json`、`artifact_hashes.json`、`report.md` 和 `done.json`。
`done.json` 只在 PASS 后写出；S3 原始 ledger、S3 witness、P3 raw 和保护文件均只读。
