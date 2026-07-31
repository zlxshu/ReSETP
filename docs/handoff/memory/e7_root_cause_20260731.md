# E7 不可行根因（2026-07-31，只读诊断）

- 权威交付：`docs/handoff/e7_infeasibility_diagnosis_20260731/`
- 性质：只读。未重跑 E7、未改代码、未动封存产物。120 个单元 JSON 全部在盘。

## 114 个失败拆成三块（FACT）

| 块 | 单元 | 范围 | 机制 |
|---|---:|---|---|
| A | 24 | 50c 三个滚动臂 | **新增订单被处理时时间窗已过期** |
| B | 30 | 三规模全部 STATIC_FIXED_RECOURSE | **静态臂零自由度**，evaluations=0 |
| C | 60 | 100c/150c 三个滚动臂 | 阶段 1 即死，机制未定位到条件级 |

### A 块：订单一出生就过期

逐条比较 add 事件的 `new_due_time` 与其批次 `trigger_time`：50c 上"首个含过期订单的阶段"
与"滚动臂实际失败阶段" **5/5 精确相等，零例外**；唯一无过期订单的 stream 4 正是唯一 PASS 的流。
最极端 due − trigger = **−5415.4 秒**（订单出现时，最晚送达时刻已经过去一个半小时）。

代码链（`dynamic_multitrip_schedule.py`）：`:1237-1248` 由末节点 due 反推最晚发车；
`:719` `boundary = max(stage_start, asset.available_second) ≥ 触发时刻`；
`:743` `departure > latest_departure_second` 即跳过该资产；全部跳过后 `:466-469` 抛
`no inherited asset can serve open route`。**与车队余量无关，加多少车都无解。**

根因：事件生成与 `delta_t=10800` 分批粒度的时钟口径未对齐。

### B 块：静态臂的失败是设计出来的

`static_fixed_stage` 唯一自由度是新增趟次的 cv/ev 选择。该失败在正式跑之前就已被写进
接线自检的通过条件（`run_e7_dynamic.py:1364-1377`）。

### C 块：未查清 + 一个必须记住的边界

100c/150c 全部 80 单元 `failure_stage=1`，该阶段 add 订单无一过期。失败文本
`initial_feasible=False, changed=600(594), executable=0`。落盘只保留 top-3 被拒路线名与计数，
未保留条件级分解。

**边界（FACT）**：`per_search_pass_cap=600` 只在 **50c seed1 stream1 FULL_ROLLING 单阶段探针**
上标定（`pre_registration.json` / `budget_lock.json`），**100c 与 150c 从未做过预算探针**。
故"600 不够"与"结构性无解"在现有落盘证据下**不可区分**。

## 两条独立于失败之外的严重发现

### 1. 84 个滚动臂失败单元里，臂差异化搜索从未执行

`probe._controlled_stage:823-849` 第一件事是跑与臂无关的影子基准 `_same_state_no_cooperation`
（配额 600），臂特定搜索在 `:884-931` 才发生，完整阶段共 1200。

**84/84 个滚动臂失败单元的 `actual_evaluations` 恰为 `completed×1200+600`**，
且 **28/28 组三臂失败文本逐字节相同**（含 top_rejections 路线名与计数）。
⇒ 失败阶段只烧掉了第一趟共享基准。**不是"四臂打平"，是"四臂对照没开始"。**

### 2. 碳开关有一半没接线（真接线缺陷）

`e7_dynamic_v3_20260731/run_e7_dynamic.py:504-571` `corrected_initial_plan(arm, …)`：
`:509-510` 读 `arm` 只做合法性校验；`:513-532` 同时算 immediate 与 aware；
`:539-540` **无条件送 aware**；`:564` **硬写 `"strategy":"aware"`**；`arm` 此后再未使用。
⇒ **CARBON_BLIND 臂的日初名义方案也是碳感知的**。6 个 PASS 单元四臂
`nominal_timing.strategy` 全为 `aware`、`moved_action_count` 全为 3、route/energy 哈希逐位相同。

缺陷早于 v3：`baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py:544-605` 同病，v3 原样复制。

**易误导之处**：接线自检报告里 CARBON_BLIND 的目标值 2305.468523 与另三臂不同，看似开关生效；
但该值由 `:1346` 单独挑出**只用于填自检表**，与正式任务实际使用的名义方案不是同一个东西。

事件后那一半接线正常，但 6 个 PASS 单元 `moved_charge_actions_after_event=0`，不 binding。

另：`ARM_CONFIGS` 的 route_policy / cooperation / participation / charging 四个键
**全仓库没有任何读取点**，只进自检报告行。

## 当前 E7 唯一可信的对照观测

协同开关在 **50c seed4** 上真 binding：NO_COOPERATION 比 FULL_ROLLING 贵 **20.786545%**，
成本、利润、排放、充电量、两车场分账全部分化。这是目前 E7 里唯一一个真实的臂对照。

## 用户"屎山代码"假设的裁定

**部分成立，但不是 114 个失败的主因。** 真实接线缺陷只有碳开关日初那一半 + 四个死配置键；
失败主因是事件数据的时钟口径（A 块）与静态臂的设计（B 块）。

## 其他

150c 的 40 个单元共用 **1 个**名义方案（50c/100c 各 10 个），种子维度退化。

相关：[[mechanism_condition_absent_20260731]]（E3/E5 同类问题的反方向版本）、
`dynamic-demand-integration`（动态必须证明三机制真参与，本诊断显示碳机制那一路目前不成立）。
