# E2-RERUN-UNIFIED-01 China81 全量统一重跑

当前状态：`CLEAN_RESTART_RUNNING`。洁净批由 PID 23367、PGID 23367 启动，
监控目录为 `.e2-rerun-unified-01-full-clean-restart.monitor/`。

本批为洁净重启批。发现时旧批约完成 163 行；通过安全终止完成写盘时为 165 个完整
尝试行，已整体归档至 `contaminated_partial_run_oversubscribed/`。旧行是在双池
超订条件下产生，限时 MIP 的墙钟求解工作不可比，全部作废，不得用于论文数字或
臂间比较。

洁净批并发固定为 4 workers。理由是按项目实验手册在总吞吐恶化时按证据降级，并为
限时 MIP 留出稳定的墙钟求解质量。其余冻结合同不变：81 题、5 种子、O/F/E/M/MV
五臂、`NoImprovement(K=3000)` 起步、MV 三视角逐轮各自独立收敛、外层轮次循环，
以及按臂与规模层执行的 L/S 饥饿加倍规则。

每个尝试单元的 S、L、L/S、CPU 秒、墙钟秒和峰值 RSS 将写入 `raw_runs.csv`；
MV 的逐视角逐轮 S、L、L/S 另写入对应 JSON 字段与轨迹文件。
