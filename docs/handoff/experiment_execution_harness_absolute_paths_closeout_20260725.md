# 实验启动器绝对路径基础设施验收

- 合同：`EXPERIMENT-ABSOLUTE-HARNESS-001`
- 执行版本：v2
- 结论：`PASS_EXPERIMENT_ABSOLUTE_HARNESS_V1`
- 日期：2026-07-25

v1 集成测试已原样保留：六个零算例 worker 已启动，但监督器的命令文字检查把 Python
真实目标路径与启动符号链接混为一谈，并因系统进程命令文本截断而看不到位于末尾的
`--workers 6`，故暂停。该现场是共用启动器验收失败，不是任何候选的算法证据。

v2 同时登记 Python 的“绝对启动路径”和“解析后真实路径”，将关键并发字段放到主
脚本之后的命令前部，并继续要求项目根、监督器、脚本、保护文件、结果文件、完成
标记和监督目录全部为存在的绝对路径。正式监督运行判 `COMPLETED`，findings 为 0；
6 行结果来自 6 个不同进程，全部回报同一仓库根、同一 worker 模块绝对路径和同一
Python，且 `real_instance_loaded=false`。结果目录 4 项哈希逐项复核一致。

证据：

- 注册：`baselines/experiment_infrastructure/absolute_execution_harness_20260725/registration_v2.json`
- 监督配置：同目录 `monitor_integration_v2.json`
- 五件套：同目录 `integration_gate_v2/`
- 监督现场：同目录 `.absolute-execution-harness-v2.monitor/`

严格边界：这只证明共用启动基础设施可用。JRC v1 启动失败现场保持不改，候选算法、
科学协议、算例、预算和阈值均未改变；本验收不自动授权重跑 JRC。
