# 机制作用条件在算例里不存在（2026-07-31）

- 编号：`FINDING-MECHANISM-CONDITION-ABSENT-20260731`
- 性质：只读复算，未跑实验、未改任何封存产物
- 触发：用户提问"哪些实验成功哪些失败、原因查清没有"，并提出怀疑
  "E5 零效应严重怀疑是我们的条条框框、思路不对、对比对象不对等基础设置的原因"

## 两条决定性 FACT

### E3：错配率 0/150，且按构造为零

`baselines/china_e3_e7/e3_zone_joint_20260731/input_assignments.csv` 共 300 行
（`cn-prd-50c-01` 50 客户 + `cn-prd-100c-02` 100 客户，各 ZONE/JOINT 两臂），
`registered_differs_from_nearest` 字段**全部为 `False`**。即两个正式算例上，
客户的行政登记车场与其最近车场 **100% 重合**。

成因见同目录 `depot_field_investigation.json`：
`loader_derivation = "customer city -> the unique depot in that same city"`，
实现于 `solver/src/setp_solver/china81.py:355`；而算例把客户放在有车场的城市内，
于是**错配按构造恒为零**，不是抽样偶然。

两个算例各只有 2 个车场（`D_guangzhou` / `D_shenzhen`）。
`decision.json` 另记 `ind_arm_run=false`、`IND_AND_ZONE_INPUTS_IDENTICAL_BY_PRE_SEARCH_FACT`
—— 三臂设计实际只跑了两臂。

**含义**：ZONE→JOINT 的 1.482937% 只能来自路径合并与共享，
被 E3 声称测量的"责任错配"杠杆在这两个算例上**没有任何实例**。

### E5：两臂逐会话完全相同，折减区既进不去也不稀缺

`baselines/china_e3_e7/e5_nonlinear_final_20260730/charging_sessions.csv`，196 个会话：

| 事实 | 数值 |
|---|---|
| L100 与 NL90 逐会话（实例×种子×车×会话序）起止 SOC 与充电量 | **键集相同、值全等** |
| 起始 SOC = 0% 的会话 | 160 / 196 |
| 起充时刻 = 第 0 秒（车场行前充电） | 140 / 196 |
| 终止 SOC 中位数 / 均值 | 37.03% / 46.95% |
| 充到 100% 的会话 | 36 / 196（18.37%） |
| 有非线性—线性时长差的会话 | **恰好同样是那 36 个** |
| 每个差值 | **全部等于 1264.6 秒（21.1 分钟）** |

非线性物理只改变了充电**时长**，没有改变任何**决策**；而那 21 分钟落在行前充电段
（第 0 秒起充、运营时域 06:00 才开始），不与任何稀缺资源竞争，故成本效应 0.000%。

`e5_literature_curve_20260731/decision.json` 已独立印证：换成 Montoya 2017 文献曲线，
受影响会话仍是同一批 36/196。

## 推论（INFERENCE）

E3 弱效应与 E5 零效应是**同一类问题**：机制的作用条件（错配、深度充电）在当前
算例构造与充电策略下按构造不存在，与门禁、预算、判据无关。这解释了为什么
2026-07-30 拆掉八条自建约束后 E3 仍停在 1.48%（见
`docs/handoff/journal_convention_alignment_20260730/`）。

E7 是**反方向的同一类病**：120 单元中 114 个 `LEGAL_INFEASIBLE`，
资产余量紧到零可行。三者共同轴线是**算例与参数标定**，不是搜索或门禁。

车队池化这条假设已于同日被探针证伪：`e3_pooling_probe_20260731`
POOLED 对 JOINT 三个种子 −0.038% / 0.000% / −0.036%。

## 未决（属改建模，需用户批准）

若要让 E3/E5 的机制真正 binding，必须动算例或参数：车场数量与分布、
错配的构造方式、电池容量与路线能耗之比、充电功率与充电时机。
这属于 `READ_ME_FIRST_FOR_AGENTS.md §4` 的禁止越权项，需用户明示批准并登记
`docs/handoff/model_change_approval_register_20260718.md`。本轮未擅动。

相关：`e3_zone_joint_20260731/`、`e5_nonlinear_final_20260730/`、
`e3_pooling_probe_20260731/`、`mechanism_lever_rethink_20260731/`。
