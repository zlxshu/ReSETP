# GR1 公式 ↔ 代码逐条对照审核

任务：GR1。审核对象：`docs/paper_v2/paper_main.tex` 当前活动正文。审核时间：2026-08-03（Asia/Singapore）。执行方式：只读源码与既有保存解；未改论文、求解器、HANDOFF、实验记录，未启动搜索或正式实验。只运行了行号/哈希/JSON 查询和零搜索算术核算。

## 结论先行

**FACT — 覆盖完整。** 当前 TeX 中共有 37 个 `\label{eq:...}` 编号公式，本审核覆盖 37/37；未覆盖清单为空。判定为：一致 21 条、不一致 15 条、未实现 1 条。终止状态为 `GR1_FORMULA_CODE_AUDIT_COMPLETE`。

**FACT — 用户提示中的既知 F2 代码状态已经漂移。** 当前 [`cost.py`](../../../solver/src/setp_solver/cost.py) 第 164–170 行不是“按路线数”，而是按去掉 `#T` 后的实体车 ID 去重计费；论文第 475–480 行仍明确按配送趟数 `n_kp` 计费。因此当前真实不一致是“论文按趟、代码按实体车”，不是“二者都按趟”。历史 handoff 也明确记录过“固定费暂按每趟，若改实体车必须另审”，但当前源码已经改成实体车口径。

**FACT — F2 已改变现有保存结果的绝对量级。** `formal_ablation_200c_20260803` 的 30/30 个终局均为 35 趟、22 辆实体车、`c_fix=170`、代码固定成本 3740 元、代码总目标 7820.1814723598745 元。论文 F2 应为 `35×170=5950` 元，差 2210 元；仅修正这一项，目标即为 10030.181472359875 元，比代码值高 28.2602%。这会改变绝对成本、车场利润和联盟价值；不同方案的排序是否改变取决于各自“趟数−实体车数”，只读审核不能替代全库重算。

**FACT — 另有五项高影响缺口。** `eq:batt_prop` 的 `Bmin` 没有进入代码，保存例 14 个 EV 趟中 10 个以 0 kWh 结束；`eq:trigger` 论文按累计需求 kg，代码按事件条数；`eq:station_cap` 论文对车场也有限容量，当前正式配置却是车场并发无上限；`eq:sp-recombination` 的 MIP 漏了论文两族车队约束；`eq:accumulation` 仅实现累计成本和排放，没有累计车场收益。

**INFERENCE — 科学影响边界。** 现有结果不能直接声称“完整执行了论文全部公式”。静态 China81 的预测/结算碳强度当前被构造成相等，因此 F1 的 forecast/actual 语义错位在该静态数据上数值为零；但动态预测误差场景会暴露差值。电池 `Bmin` 在论文中没有给数值，因此可以确认“代码未实现”，但不能在未由用户冻结 `Bmin` 前给出现有解的最终失效率。

**DECISION — 无。** 本审核不替用户选择修论文还是修代码，也不选择 `Bmin`、车场桩容量、触发阈值或固定费口径。

**HALT — 无。** 全部编号公式已覆盖，未触发 PARTIAL。

## 审核口径

实现判定以当前工作区实际源码为准，而不是旧提交、旧注释或屏幕状态。工作区在审核开始前已经有大量用户修改和未跟踪产物；GR1 没有改动这些既有文件。公式的“实现”既包括求值器，也包括硬可行性检查、严格多趟证书、E6 联盟计算、E7 动态触发和正式 SP 重组入口。启发式算法没有显式 `x/a/z` 数组时，若离散解表示与检查器等价实现公式，则判为一致；只有一部分实现时按完整编号公式判“未实现”或“不一致”。

不一致项都给了数值证据。零搜索最小算例只用于证明两个表达式可产生不同数值，不把构造参数升级为论文发现。既有影响量级只使用保存产物查询，未重新求解。

## 37 条编号公式逐条映射

下表给人读入口；关键表达式原文、完整数值证据和影响字段见 [`equation_map.json`](equation_map.json)。

| # | 公式 | TeX 行 | 实现位置 | 判定 | 核心证据/边界 |
|---:|---|---:|---|---|---|
| 1 | `eq:power` | 392–395 | `cost.py:871–874,895–950` | 不一致 | 无 profile 时同式；China81 改用 `sum(v²d)`。最小例论文 41333.589 W，代码等效 13801.312 W，差 −27532.277 W。 |
| 2 | `eq:electricity` | 400–403 | `cost.py:891–892,1046–1108` | 不一致 | 同一最小例 0.605258 vs 0.378930 kWh，差 −0.226328 kWh。 |
| 3 | `eq:fuel` | 400–403 | `cost.py:877–888,953–1043` | 不一致 | 同一最小例 0.182331 vs 0.164989 L，差 −0.017341 L。 |
| 4 | `eq:linear_energy` | 406–411 | `cost.py:871–892,1046–1108` | 不一致 | 线性退化只用于无 profile 分支；China81 正式评价不是该式。 |
| 5 | `eq:charge_duration` | 427–432 | `charging_curve.py:212–240,275–316`; `charging_action.py:25–50`; `cost.py:496–581` | 一致 | 分段能量除以 `π_s κ_l` 后求和，记录时长再由成本核验。 |
| 6 | `eq:charge_window` | 433–436 | `check.py:717–917`; `charging_curve.py:481–508` | 一致 | `latest_start=latest_finish−duration`，整段落窗。 |
| 7 | `eq:charge_overlap` | 438–442 | `cost.py:431–493,584–651`; `charging_curve.py:446–478` | 一致 | `max(0,min(end)−max(start))` 同构。 |
| 8 | `eq:carbon` | 449–457 | `cost.py:202–209,723–753,1111–1125`; `china81.py:846–860` | 不一致 | 评价器只返回 actual；10 kWh、100/200 g 时论文规划 1 kg，代码 2 kg，差 1 kg。 |
| 9 | `eq:F1` | 470–473 | `cost.py:202–214,723–753` | 不一致 | 上例 `p=0.05034` 时论文规划成本 0.05034，代码 0.10068，差 0.05034。 |
| 10 | `eq:F2` | 475–480 | `cost.py:164–170`; `solution.py:11–25` | 不一致 | 保存解论文 5950，代码 3740，差 −2210 元。 |
| 11 | `eq:F3` | 482–487 | `cost.py:158–160,171–179` | 一致 | 逐路线 km × 车型公里成本。 |
| 12 | `eq:F4` | 489–494 | `cost.py:161,180–185` | 一致 | 聚合式一致，但继承 `eq:fuel` 的底层差异。 |
| 13 | `eq:F5` | 496–504 | `cost.py:186–193,1128–1215` | 一致 | 分时电量乘价并加公共站占用费。 |
| 14 | `eq:F6` | 507–513 | `cost.py:200`; `china81_completion.py:67–109` | 不一致 | 裸评价依赖外部注释列表；1 个跨场客户、单价 25 时论文 25，未注释代码 0。正式 wrapper 会补注释。 |
| 15 | `eq:obj` | 522–525 | `cost.py:194–214` | 不一致 | 继承 F1/F2/F6，且多出 `cost_time`；保存例仅 F2 即差 −2210 元。 |
| 16 | `eq:trip_flow` | 526–529 | `check.py:553–589` | 一致 | 节点序列起讫唯一、同 home depot 闭合。 |
| 17 | `eq:flow_cons` | 530–533 | `check.py:437–454,553–589` | 一致 | 被访问客户在序列中有唯一前后继，全局恰服务一次。 |
| 18 | `eq:load_bounds` | 534–537 | `cost.py:858–868`; `check.py:592–637` | 一致 | 起点载重为需求总和，逐弧 `0≤L≤Q`。 |
| 19 | `eq:load_prop` | 538–541 | `cost.py:858–868`; `check.py:624–636` | 一致 | 选中弧上按需求精确递减。 |
| 20 | `eq:tw` | 542–545 | `cost.py:409–426`; `check.py:686–714` | 一致 | `start=max(arrival,ready)` 且检查 `start≤due`。 |
| 21 | `eq:time_prop` | 546–549 | `cost.py:350–428` | 一致 | 行驶、等待、服务和充电按时间递推。 |
| 22 | `eq:batt_prop` | 550–554 | `check.py:920–1007`; `multitrip_schedule.py:1462–1503` | 不一致 | 只查 0 与 B，不查 `Bmin`。构造 `Bmin=16`、余量 5 时低 11 kWh 仍通过。 |
| 23 | `eq:no_customer_charge` | 555–558 | `check.py:233–327` | 一致 | 充电 action 只允许 `d/f`，客户 `c` 被拒绝。 |
| 24 | `eq:trip_linkage` | 559–563 | `multitrip_schedule.py:1416–1526` | 一致 | 相邻趟不重叠、充完再出发、电量账等式连续。 |
| 25 | `eq:coverage` | 564–568 | `check.py:437–486`; `multitrip_schedule.py:1442–1547` | 一致 | 客户恰一次，实体车同场同型并受全局车数上限。 |
| 26 | `eq:station_cap` | 569–572 | `check.py:489–550,1120–1128`; `china81.py:592–636`; `model_config.py:26–47` | 不一致 | 车场当前 unbounded。两会话、论文 C=1 时超 1；代码回退 C=2 时超 0。 |
| 27 | `eq:stage_profit` | 574–580 | `profit.py:64–174,203–233` | 不一致 | 两趟同车时论文固定扣 340，代码扣 170，代码利润高 170；碳也用 actual。 |
| 28 | `eq:binary` | 581–584 | `solution.py:28–46`; `route_pool_sp.py:690–698` | 一致 | SP 为 0/1，启发式解也是离散记录。 |
| 29 | `eq:coalition_profit` | 610–613 | `run_pilot06_direct_15.py:534–543,568–574` | 一致 | 直接计算 `R(A)−C(A)`，但成本输入继承上游口径。 |
| 30 | `eq:shapley` | 615–620 | `e6_cooperative_game.py:24–35` | 一致 | 阶乘权重和边际贡献同式。 |
| 31 | `eq:core` | 621–626 | `e6_cooperative_game.py:38–66` | 一致 | 效率等式与所有真子联盟约束进入 LP。 |
| 32 | `eq:trigger` | 641–644 | `dynamic.py:58–65,998–1023` | 不一致 | 论文累计 kg，代码 `len(batch)>=q_bar`。500 kg 单事件：60 s vs 10800 s，差 10740 s。 |
| 33 | `eq:customer_update` | 646–650 | `dynamic.py:1026–1093` | 一致 | 已服务/取消移除、新增并入，另处理属性变更。 |
| 34 | `eq:accumulation` | 655–660 | `dynamic.py:272–277,329–369` | 未实现 | 仅累计成本和碳；没有 `barPi_d` 状态或递推。 |
| 35 | `eq:sp-recombination` | 753–769 | `route_pool_sp.py:628–711` | 不一致 | MIP 只有 exact cover；最小例论文受限最优 10，代码 surrogate 2，差 −8，后验完整检查才拒绝。 |
| 36 | `eq:charging-candidates` | 895–898 | `cost.py:654–693`; `charging_curve.py:481–508` | 一致 | 窗口端点与 `b−δ_l` 全生成并截窗。 |
| 37 | `eq:charging-rule` | 899–900 | `cost.py:654–720`; `run_e7_dynamic.py:513–531` | 不一致 | 核心默认按 actual，论文按 forecast；反向两槽例选择相差 1800 s。E7 v3 显式覆写 forecast。 |

## 不一致的影响分级

| 级别 | 项目 | 已有结果影响 |
|---|---|---|
| 直接、已量化 | `F2`, `obj`, `stage_profit` | 200c 消融 30/30 个终局均少计 2210 元固定成本；车场利润和 E6 联盟价值输入同步偏高。 |
| 直接、可行域 | `batt_prop` | 保存例 10 个 EV 趟以 0 kWh 结束；只要最终采用 `Bmin>0`，这些终点即不满足论文。 |
| 直接、实验定义 | `trigger` | 当前 E7 是“事件数批处理”，不是论文“累计需求重量批处理”；触发次数和时刻均可能变。 |
| 直接、约束缺失 | `station_cap` | 当前正式结果属于“车场桩无上限”场景，不能支持论文对车场有限 `C_s` 的约束声称。 |
| 算法组件 | `sp-recombination` | 后验检查保护最终可行性，但 MIP 搜索空间与论文不同，可能错失可行改进或先选后拒。 |
| 物理计算 | `power/electricity/fuel/linear_energy` | China81 全部采用变速 profile 积分；代码可更精细，但论文公式没有定义这一正式计算。所有能源相关结果在“公式真实性”层面需要统一口径。 |
| 条件暴露 | `carbon/F1/charging-rule` | 静态 China81 因 actual=forecast 暂无数值差；预测与结算分离时立即改变规划成本/择时。 |
| 接口依赖 | `F6` | 正式 China81 wrapper 会注释且主值 `c_tr=0`；裸 evaluator 或非零摩擦路径有少计风险。 |
| 缺项 | `accumulation` | E7 没有逐阶段已执行车场收益守恒链，不能用终局 nominal/final 利润替代该公式。 |

## 反向核对：代码有而论文编号公式无

共 9 项，详见 [`code_only_terms.json`](code_only_terms.json)：路线时间货币成本、变速道路剖面积分、车场并发无上限默认、可选 `Pi>=theta Pi0` 利润门、重复公共站访问禁令、碳时段越界延拓规则、F6 外部注释合同、动态冻结/保留守卫、SP 可选责任车场硬锁。这里没有把异常处理或字段完整性检查凑数。

其中最重要的目标项是 `cost_time`：默认值为 0，所以主线静态目标不受影响；若按 E5-P1 设为 75 CNY/h，一小时路线会比论文目标多 75 元。`profit.py` 又没有相同扣项，因此该灵敏度下系统目标和车场利润无法闭合。

## 覆盖、证据和边界检查

- TeX 标签枚举：37；`equation_map.json` 条目：37；标签重复：0；未覆盖：0。
- 每个条目都包含 `eq_label`、`tex_lines`、`impl_file`、`impl_lines`、`verdict`、`numeric_evidence`、`impact`。
- 15 个“不一致”条目全部给出论文值、代码值和差值；1 个“未实现”条目明确指出只实现了哪两部分。
- 保存解证据只读取 `baselines/china_e3_e7/formal_ablation_200c_20260803/units/.../solution.json`；未改、未重算、未筛种子。
- 产物哈希排除 `._*`；`artifact_hashes.json` 不自哈希，避免自引用。

## 源码快照

本报告绑定以下当前工作区 SHA-256，避免后续源码继续变化后把 GR1 误当作实时结论：

| 文件 | SHA-256 |
|---|---|
| `docs/paper_v2/paper_main.tex` | `76425e69ee7e0c0ffe7697dcad72eaf9e6803b95a10ce6ccd383410ffa81096f` |
| `solver/src/setp_solver/cost.py` | `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d` |
| `solver/src/setp_solver/check.py` | `86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b` |
| `solver/src/setp_solver/profit.py` | `54d7ce3a0a27fd35d01a829c575854b9717375e4028795d336bd0f4428b56b44` |
| `solver/src/setp_solver/search/dynamic.py` | `f494156dec17bfef67fd3ecd13f0e22cb24f279ce888de120942d87940f0d22c` |
| `solver/src/setp_solver/search/multitrip_schedule.py` | `1274da792bdf03d9544f0f3afc74612f06f2d1324e9e75d1bc225e5bb3e94d13` |
| `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py` | `7b570ba5a793f7ca2c5484779eb8d91b3b7e0d048a8e15311fcd01429acf355c` |

最终状态：`GR1_FORMULA_CODE_AUDIT_COMPLETE`。
