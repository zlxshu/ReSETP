# E7 动态扰动实验 v2：启动契约硬停报告

## 结论

本轮没有形成 E7 科学结果，状态为 `HALT_PROBE_STARTUP_CURVE_CALENDAR_CONTRACT`。上一轮的 `KeyError: 'instance_json'` 已经查清并修复，但最小启动验证在进入 `probe.run_probe_arm` 之前暴露出两个后续的共享初始计划契约缺口。依据“崩溃立即停”的硬约束，本轮没有继续修改代码、没有启动收敛探针，也没有运行任何正式单元。

累计搜索评价次数为 0。50c、100c、150c 均未运行；正式预算上限未选定；`static_degradation_pct`、`dynamic_recovery_pct` 均不可报告。四个预注册臂没有被替换或删改，但它们都经过同一个共享初始计划，因此当前代码下全部被同一启动契约阻断。

## KeyError 的真实原因与修复

旧动态框架使用单文件 `bundle_dir/instance.json`，其搜索源字段叫 `instance_path`，旧适配器因此错误地读取 `bundle.source_paths["instance_json"]`。当前 China81 不是单文件 bundle；它的真实源字段为 `catalog`、`facilities`、`finite_fleet_authority`、`nodes`、`orders`、`road_matrices`、`tariff_carbon_calendar` 和 `vehicle_parameter_lock`，不存在 `instance_json`。

v2 适配器没有使用 `dict.get`、默认值或伪造的 JSON 路径，而是严格要求上述八个字段恰好齐全，解析为项目内绝对路径，并分别记录哈希。零搜索回归检查 `source_contract_check.json` 通过，状态为 `PASS_ZERO_SEARCH_SOURCE_CONTRACT`。因此 `keyerror_fixed=true`。

## 最小启动验证为何仍然硬停

监控启动验证调用 50c、seed 1、stream 1、`FULL_ROLLING`，每个搜索 pass 上限为 10，目标是完成一个阶段。程序越过了原 KeyError，但仍在共享 `_initial_plan` 中、进入 `probe.run_probe_arm` 之前崩溃，异常为：

```text
ValueError: E3_STRICT_MULTITRIP_V3_NL: certificate curve id disagrees with prices
```

只读诊断证明数据自身没有冲突。certificate 与 China81 prices 的曲线 id 都是 `NL90_mild`，参数哈希同为 `605f66b1…1e54`，物理参数哈希同为 `3350c262…de6`，电池容量同为 77.28 kWh。真实原因是共享 E7 `_initial_plan` 的两次 `reschedule_between_trip_charging` 调用都没有传 `prices=sources["prices"]`，函数因而退回旧的 `DEFAULT_PRICES`，把线性默认价格契约与 NL90 certificate 比较。

为确认诊断，使用显式 China81 prices 做了零搜索调用：`naive` 调度通过，得到 8 条路线和 4 个充电动作；`aware` 调度随后触发第二个明确缺口：`missing carbon profile for charge_day_offset=-1`。当前 v2 源只提供 day offset 0，而非线性首趟的前夜充电需要权威的 day offset −1 碳曲线。这里不能把当日曲线复制成前夜曲线，否则会伪造碳感知机制输入。

需要的新授权不是改变四臂或搜索语义，而是在新尝试中同时完成两项启动契约修复：向共享重调度显式传入 China81 prices；从已冻结的权威日历构造并验证 day offset −1 曲线。两项修复都应先通过新的零搜索回归检查。

## 四臂与机制参与

`STATIC_FIXED_RECOURSE`、`FULL_ROLLING`、`NO_COOPERATION`、`CARBON_BLIND` 全部保留原预注册定义；本轮没有默默换臂。由于共享初始计划先于臂执行，四臂当前均为 `BLOCKED_BY_SHARED_INITIAL_PLAN`，不是某一臂单独失败。

跨场责任重分配、成员收益格局变化和碳强度驱动的充电时刻变化均为“未观察”，不能解释为实证上的“没有发生”。为满足机器接口，`done.json` 中三个布尔值写为 `false`，其语义由 `decision.json` 明确限定为 `NOT_OBSERVED_BECAUSE_NO_ARM_ENTERED`。

## 正文位置与图表政策

本轮没有科学结果，因此不推荐任何图或表进入论文正文：`recommended_main_figure` 与 `recommended_main_table` 均为 `NONE_NO_SCIENTIFIC_RESULT`。`raw_runs.csv`、源契约检查、曲线/日历诊断、监控日志和哈希清单全部仅作为证据存档，不进入正文。项目仍不设附录；未来形成可认证结果时，E7 最多推荐一张主图和一张主表。

## 上游脉络

E3、E4、E5、E6 的封存结果均未重跑或覆盖。本轮不能把这些背景结果外推成 E7 结论，也不能回答“扰动后静态方案恶化多少、动态重规划挽回多少”。E7 在全文中的既定作用仍是检验事件驱动重规划是否提供独立于 E3 静态协同、E4 固定路线碳时序、E5 非线性充电可行性和 E6 公平约束之外的动态价值；该作用尚未被本轮证据实现。
