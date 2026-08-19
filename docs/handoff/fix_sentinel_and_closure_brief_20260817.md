# FIX-SENTINEL+CLOSURE 任务书：先修验收器分类，再原样重做闭包 A（发给 Codex）

先读 `docs/handoff/codex_standing_charter_20260817.md` 与你自己的
`solver/reports/fix_init_closure_20260817/report.md`。**本件执行你在该报告结尾的建议。**

## Claude 认错（说明为什么要重做）

`CORRECTION`（Claude 的任务书缺陷）：上一件我写死"逐级任一不过即回滚"，
**没有留"失败原因若不在本次授权范围内则保留改动并报告"的口子**，
导致你一个**五项全过**的闭包修复被白白回滚。你没有靠关路线层/关哨兵绕过、老实回滚——做得对。
本件补回这个口子（见"失败处置"一节）。

## 已钉死的事实

`FACT`（你查的）：1 圈实际接受只有 `hgs_population: 2` 与 `route_layer_crossover: 1`，
无 education channel 接受；但 runner `:3578-3589` 把**所有非 `hgs_population` 的接受动作**
相加命名为 `accepted_education_moves`，于是路线层交叉接受被误算成 education 接受；
而路线层候选走完整评价、不经过 education 增量 sentinel，`sentinel_evaluations` 合理为 0
→ 总验收误报失败。**这是验收器分类缺陷，不是算法缺陷。**

## 两件，按序

### 第一件｜修 runner 的 sentinel 验收分类

- 只把**真正经过 education 增量评价**的接受 channel 计入 `accepted_education_moves`；
  路线层交叉等走完整评价的通道**另计**，不得要求 education 的增量 sentinel。
- 补一条回归：**"路线层交叉接受、education 未接受"时总验收应通过**。
- **明令禁止的绕过办法**（写死，违反即任务失败）：
  ①不许关闭路线层交叉；②不许关闭 truth sentinel；③不许改三臂机制清单；
  ④不许放宽或删除既有真值校验。**这些是砸体温计，不是退烧。**

### 第二件｜原样重做闭包方案 A

按 `attempted_change.diff` 原样重做（该补丁上一轮五项验收全过）：
`initialization.py` 加结构闭包参数/回调、move.apply 后充电修复前按休眠项拒绝车型/场站变化；
runner 传入 `mechanism_enabled`；补初始化车型与跨场站两类回归。
**通用闭包，不要只给 type-flip 打特例补丁。**

## 验收（逐级）

1. 闭包五项：初始种群 25/25、车型闭包、场站闭包、服务 50/50、需求 13264/13264；
2. **1 圈 runner 总 verdict 通过**（第一件修好后应当通过）；
3. 全开（不传休眠项）200 圈与修复前 oracle **逐位一致**（除 wall 字段）——
   上一轮已录 oracle：200/200 圈、成本 `3532.2672464613343`、可行 0 违规、50/50、13264/13264；
4. 回归 197 断言不动 ＋ 新增三条测试（车型闭包、场站闭包、sentinel 分类）；
5. 五个冻结文件哈希不变（`cost.py` 现行 `13ae664b…`）。

## 失败处置（补上一轮缺的口子）

- 失败原因**在本次授权范围内**（闭包或 sentinel 分类本身写错）→ 回滚该处并 HALT 报告；
- 失败原因**不在本次授权范围内**（又是别的验收器/别处缺陷）→
  **保留已通过的改动、不回滚**，把新缺陷如实登记为下一件，HALT 报告。
  **不许为了让总 verdict 通过而动授权范围外的东西。**

## 通过后立刻接着做（同一任务内）

跑时变碳三臂：`asap`／`cost_min`／`cost_plus_carbon`，统一算例、seed 11、**各 200 圈**。
产出每臂总成本、总排放、**充电时刻分布**、充电电量加权碳强度、电费、碳成本、CV/EV 台数、
服务量红线、可行性，并给相对 `asap` 的成本差与排放差三臂并排表。
**须明写这是 200 圈技术读数、非正式结果**（正式按 P79 十种子）。

## 产物

`solver/reports/fix_sentinel_closure_20260817/report.md`，首行 `SENT_CLOSURE_DONE`／`_PARTIAL`／`_HALT`、
末行 `SENT_CLOSURE_END`；含两件的 diff、逐级验收表、三臂并排表（若跑到）、四件套、done.json、resume。
单进程串行，单次 ≤10 分钟。结尾按章程答"接下来该干什么"。
