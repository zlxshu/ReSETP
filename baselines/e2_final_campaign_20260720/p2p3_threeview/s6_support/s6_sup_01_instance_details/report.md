# S6-SUP-01 仿真算例详细信息表

机器判定：`PASS_S6_SUP_01_INSTANCE_DETAILS`。

从冻结节点源导出 50 个客户和 2 个车场，共 52 行；客户编号为 1--50，车场按城市排序为广州 51、深圳 52。

经纬度来自节点源的 longitude/latitude 字段并格式化为四位小数；ET/LT 来自订单源的分钟-of-day 字段，按本地时刻四舍五入到 HH:MM。完整小数源值另存于 `source_extract.csv`，没有手填或从图表反推。车场 ET/LT 使用冻结加载器的 06:00--22:00 时域，需求量和服务时长留 `-`。

输入文件及 SHA-256 已写入 `metadata.json` 和 `raw_runs.csv`；主 TeX、评价器和封存输入没有修改。
