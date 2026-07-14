# E7旧服务时长口径的结果登记

2026-07-14 提交 `2f224f48` 将新增订单的服务时长由基础网络平均值改为其来源客户的原始值。五条事件流的客户、事件类型、出现时刻、需求、坐标、时间窗、来源客户和归属均未重抽；排除新增服务时长字段后的事件身份指纹保持为 `cb81442db4225fa5f38562372a019afac1f481fa195f6256069681b821b8d391`。

下列目录均在旧服务时长口径下产生，只保留为开发与停止记录，不得进入论文，也不得决定正式评价次数或动态可行性：

- `preflight/p2_single_event_draft/`
- `preflight/p2_single_event_probe/`
- `preflight/paired_two_stage/`
- `preflight/paired_ten_stage/`
- `preflight/two_worker_smoke/`
- `preflight/full_stream1_400/`
- `preflight/full_stream1_400_v2/`
- `preflight/full_stream1_400_v3/`
- `formal/`
- `preflight/failed_stage_budget_800/`

服务时长合同 V3 之后的结果必须使用 `E7_EVENT_STREAM_FREEZE_V3_SERVICE_TIME`，并重新执行相应的客户守恒、实体车接续和成本检查。旧目录不覆盖、不删除，便于追溯为什么停止和为什么更换输入语义。
