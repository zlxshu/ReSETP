# E3 行政—道路责任错配三臂结构对照

状态：`HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH`。81 个 China81 实例的输入复核和三臂预注册已经完成；正式搜索在源合同漂移门触发前尚未启动，探针与正式评价数均为 0。

## 错配复核

全量复核覆盖 81 个实例、5805 个客户，其中 45 个多车场实例、36 个单车场实例。复核确认 6 个非零错配实例，与对抗性审查报告完全一致；最近车场距离并列数为 0。

| 算例 | 错配客户 | 错配率 |
|---|---:|---:|
| cn-prd-150c-01-V2-LOCATIONS | 3/150 | 2.000% |
| cn-prd-150c-02-V2-LOCATIONS | 2/150 | 1.333% |
| cn-prd-150c-03-V2-LOCATIONS | 4/150 | 2.667% |
| cn-prd-200c-01-V2-LOCATIONS | 7/200 | 3.500% |
| cn-prd-200c-02-V2-LOCATIONS | 6/200 | 3.000% |
| cn-prd-200c-03-V2-LOCATIONS | 2/200 | 1.000% |

六个实例合计错配 24 个客户，占 China81 全部客户的 0.413437%。loader 的 `customer_home_depot` 由客户城市映射到同城唯一车场；有向道路距离复核发现，11 个东莞客户距离广州车场更近，13 个广州客户距离佛山车场更近。相对同城行政车场，道路距离缩短 920.837--6044.788 m，为行政距离的 2.996%--16.513%。

六个实例由三个 150c 和三个 200c 复本组成。预注册按输入错配率选 `cn-prd-200c-01` 为主展示，其余五个形成同规模复本和跨规模稳健性面板；所有六个自然非零错配实例均入选，实例选择不依赖搜索结果。

## 三臂预注册

IND 将每个客户硬锁给 `customer_home_depot`；ZONE 将客户改配到有向道路距离最近车场并保持硬锁；JOINT 复用 ZONE 责任图与初解骨架，解除责任锁。IND→ZONE 定义为空间组织价值，ZONE→JOINT 定义为剩余协同价值，IND→JOINT 定义为总价值。正值表示后一臂成本下降，负值和零值原样保留。

正式矩阵锁定六个实例、三臂、种子 1--10，共 180 个单元；执行顺序按输入错配率递减，每个实例 30 个单元完整落盘后再进入下一个。长探针预定为 `cn-prd-200c-01`、JOINT、seed 1、cap 1500，正式共同 cap 由预注册平台期规则产生，最低 400、最高 1500。由于探针未启动，本轮 `budget_cap=null`。

## 停止事件

预注册锁定的源合同 `docs/handoff/experiment_contract_v2_journal_aligned_20260730.md` 在等待 worker 期间发生外部写入：SHA-256 从 `075f0093...f503b5e` 变为 `0e10e8ea...742c35`，文件时间为 2026-07-30 15:13:17 +08:00。监控器于 15:13:23 +08:00 检出 `PROTECTED_FILE_DRIFT` 并暂停 E3 进程组。暂停时 `budget_lock.json` 不存在，probe/formal task status 均为 0，搜索评价数为 0。

`cost.py`、`check.py`、`search/evaluation.py`、`profit.py`、`route_pool_sp.py` 和 `epochal_hgs.py` 的关闭哈希均与任务锁定值一致。原合同字节没有被覆盖恢复，也没有用漂移后的哈希重签预注册。

## 结果面

本轮正式行数为 0/180，IND→ZONE、ZONE→JOINT、IND→JOINT 三项成本效应均为 `null`。零错配封存对照仍保留原值：`cn-prd-50c-01` 和 `cn-prd-100c-02` 的错配率均为 0，JOINT 相对 ZONE 分别节省 2.272759% 和 0.693115%。陈雨蝶（2025）表 9 报告联合相对分区总成本 −3.44%、碳排放 +2.86%、车辆 8→7；陈雨蝶（2023）表 5 报告总成本 −6.09%、距离 −6.34%、时间 −5.07%、碳排 −4.79%。

正文保留本报告的错配复核表与预注册定义。`input_audit/all_instances.csv`、`input_audit/all_customers.csv`、`input_audit/mismatched_customers.csv`、18 份输入证书、监控异常现场和源锁仅存档。没有正式结果图，也不设附录。
