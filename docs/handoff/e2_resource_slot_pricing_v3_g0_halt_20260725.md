# E2 资源—时隙定价候选：v3 工程 PASS、G0 启动 HALT

- 日期：2026-07-25
- 编号：`E2-RESOURCE-SLOT-PRICING-V3-G0-HALT-032`
- 终态：`HALT_G0_WORKER_RESOLVED_ARCHIVED_RUNNER`

v1、v2 证据保持原样。用户明确覆盖此前工程不救援限制，只授权 v3 修复 spawned
worker 可导入性，并要求在真实算例加载前增加六进程零目标冒烟；不得改变算法、题、
起点、预算、阈值或停止规则。

## v3 工程门

v3 注册与 v2 的三题、两臂、五种子起点、config 和预算逐项相同；46 项源码、11 项
保护文件哈希闭合。正式工程门结果：

- spawn 冒烟 6/6，通过且为 6 个不同 PID；
- 冒烟通过前未加载真实算例；
- 真实零目标工程任务 6/6 PASS；
- 完整候选目标评价 0；
- 启动前可用内存 20.746%，预计六进程峰值 682508288 bytes；
- 判 `PASS_ZERO_OBJECTIVE_ENGINEERING_AND_SIX_WORKER_RESOURCE_GATE`。

## G0 终态

工程门通过后，按冻结合同启动六任务 G0、6 workers。六任务均报
`KeyError: 'k'`，完成 0/6。只读解析复核证明，spawn-safe worker 中的裸
`import run_g0` 被解析为已封存旧候选：

`baselines/algorithm_prototypes/dual_guided_resource_order_20260725/run_g0.py`

而不是本候选：

`baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_g0.py`

旧 runner 要求无关配置键 `k`，所以六任务在本候选搜索与完整候选评分前终止。
候选完整目标评价数为0；没有输出 witness；独立复算未启动；预登记性能门没有被
评价。因此该 HALT 只说明 G0 worker 解析到了错误 runner，不是算法效果结论。

按本轮授权，G0 失败后报告精确终态，不开启新的工程修复。不得创建 v4、重启 G0、
改变算法/预算/题/起点/阈值，或写入 China81 全量、公开 BKS/SOTA、E3、论文性能及
`1+1>2` 主张。

权威证据：

- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v3/`
- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/g0_gate_v3/`
- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-engineering-v3.monitor/`
- `baselines/algorithm_prototypes/resource_slot_pricing_20260725/.resource-slot-pricing-g0-v3.monitor/`
