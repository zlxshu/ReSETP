# E3 结构性对照输入完成、正式批技术 HALT（2026-07-30）

## 终态

任务终态为
`HALT_TECHNICAL_ERROR_CROSS_SITE_CANDIDATE_UNDER_HARD_LOCK`，不是
`COMPLETE`，也不是 `PARTIAL_AWAITING_IND_DEFINITION`。正式三效应没有聚合，
18 个故障前 PASS 单元不得进入论文效应表。

权威交付目录：
`baselines/china_e3_e7/e3_structural_20260731/`

## 旧扫描停机

接手精确核查时 PGID 7965 已不存在；补发 SIGTERM 返回 `No such process`，随后
确认无目标进程组和无旧 `build_inputs.py`/C++ 构造进程。旧目录保持原样：

- 106 个权威终态不删不改，其中 13 个仍是严格 `INFEASIBLE_INPUT`；
- 历史 C++/Python First-Fit 等价为 56/56、0 不一致；
- 8 个当时活动单元和 21 个排队单元共 29 个，另册登记为
  `NOT_BUILT_SUPERSEDED_DESIGN`；
- 该标签表示设计被取代，不是不可行、超时不可知或技术失败。

## IND 字段调查

China81 实例文件没有字面 `registered_depot`、`administrative_assignment` 或
客户车场 ID 列。现成的等价行政归属由三层证据构成：

1. `nodes.csv` 的客户 `city` 字段；
2. `node_city_membership.csv` 的逐客户 `declared_city` 与
   `PASS_DECLARED_CITY_BOUNDARY` 证书；
3. `solver/src/setp_solver/china81.py` 把客户城市映射到同城唯一车场并写入
   `customer_home_depot`。

因此 IND 不需要新构造参数。准确说法是“找到现成行政字段及既有 loader 映射”，
不是发现一列真实企业历史登记。边界证书属于
`COMPUTATIONAL_VALIDATION_BOUNDARY_NOT_OFFICIAL_CHINA_SURVEY`，不能冒充官方调查。

两个合同指定算例的描述统计为：

- `cn-prd-50c-01-V2-LOCATIONS`：登记车场不等于最近车场 0/50，0%；
- `cn-prd-100c-02-V2-LOCATIONS`：登记车场不等于最近车场 0/100，0%。

所以 IND 与 ZONE 的责任映射、First-Fit 初解和硬锁搜索问题完全相同。

未采用的合成 IND 备选仍需用户另批：距离次近方案有客观距离排序但人为制造错配；
更细行政区划方案需要新增可靠边界和车场对应来源；容量均分有资源平衡依据但不是
历史或行政登记。不得用任一备选自动修复本次技术 HALT。

## 输入与预算

IND、ZONE、JOINT 各构造 2 份输入，共 6 份。每份使用上一轮冻结 C++ First-Fit，
由 Python `_pack_depot` 逐组复算，并对完整初解重新验约束。六份均
`PASS_INPUT_CONSTRUCTED_AND_INDEPENDENTLY_CHECKED`，违规 0；最慢构造约 0.419 秒，
没有组合爆炸。

1500-cap 收敛探针只运行 50c、seed1、JOINT。实际消费 331 个完整候选后
`CANDIDATES_EXHAUSTED`，技术错误 0；平台起点为 135，200 评价确认点为 334，
没有假称平台已确认。按自然耗尽点向上取整并留余量，正式共同 cap 冻结为 400。
预算语义是上限，不是配额。

## 正式批异常

正式矩阵固定为 2 算例 × IND/ZONE/JOINT × seeds 1--10，共 60 单元，2 workers。
当 26 个单元已经形成完整 trace 时：

- 18 个单元 PASS；
- 8 个单元 trace 已持久化但因真技术错误 HALT；
- 34 个单元未运行或未形成权威 trace；
- 8 个 HALT 单元均为 50c 的 IND/ZONE、seeds 3/5/6/7；
- 技术错误候选累计 14 个，原文均为
  `hard home-depot control candidate contains cross-site service`。

合法容量/时间窗不可行候选继续按白名单计入预算；上述异常不在白名单，且表示硬责任
锁下仍生成跨场候选，不能重分类为合法不可行。监控器先暂停进程组保存现场，再停止；
没有删除异常候选、修搜索、重跑、换种子或改预算。

独立 HALT checker 在单独进程中复算 18/18 PASS 解：目标不一致 0、解哈希不一致
0、违规 0；同时核验 8/8 HALT trace 的技术错误字符串和 14 个计数。四个受保护文件
哈希与任务起点一致。

## 论文边界

60 单元全分母未完成，因此 Best/Avg/Gap%、车辆数、时间、实际评价数主表不生成；
IND→ZONE、ZONE→JOINT、IND→JOINT 正式效应均为
`NOT_AGGREGATED_DUE_TO_TECHNICAL_HALT`。输入身份可以说明两个指定算例上的
IND→ZONE 对照机械重合，但不能用 18 个 PASS 行拼出正式三臂效果。旧 L-main 的
16.55%/24.72% 只留作历史方向信号，未进入本次判决或论文证据。
