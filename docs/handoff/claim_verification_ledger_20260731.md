# 断言核查台账：六组实验的问题与原因

- 编号：`CLAIM-VERIFICATION-LEDGER-20260731`
- 日期：2026-07-31
- 用途：把 Claude 在本会话作出的**每一条关于"实验有什么问题、原因是什么"的断言**，
  逐条拆成可独立核查的条目，交 Codex（gpt-5.6-sol，reasoning effort = max）独立复核。
- **本台账不做结论，只列断言与其证据位置。** 每条的最终状态由 Codex 复核后与 Claude 逐条对账确定。

## 状态标签

| 标签 | 含义 |
|---|---|
| `CLAUDE_COMPUTED` | Claude 本人从原始文件读取或复算得到，可复现 |
| `FILE_FIELD` | 直接取自产物文件的字段值，未做二次计算 |
| `SUBAGENT_REPORTED` | 来自派出的终端 Claude 任务报告，**Claude 本人未独立复算** |
| `UNVERIFIED` | 明确未查清，不得当作已知 |

## 核查要求（给复核方）

1. **每条独立复核**：从台账给出的原始文件重新读取或重算，不得引用本台账或任何二手报告作为证据。
2. **逐条给判定**：`CONFIRMED`（数字与语义均一致）／`PARTIAL`（部分一致，须写明哪部分不一致）／
   `REFUTED`（不成立，须给出正确值）／`NOT_CHECKABLE`（证据不足以判定，须写明缺什么）。
3. **数值一律给完整精度**，不得四舍五入后比对。
4. **发现台账没列到的问题要写出来**——这是核查的主要价值之一。
5. **不得为了让结论好看而调整判定。** 与 Claude 结论相反的发现要直接写。

---

## 一、E2 算法比较

**权威证据目录**：`baselines/algorithm_prototypes/china81_vs_opensource_20260727/`

| 编号 | 断言 | 证据位置 | 状态 |
|---|---|---|---|
| E2-1 | MV 对 O：354 胜 / 46 平 / 5 负；平均改善 `1.919118015025895%`；配对单元 405；`actual_rows` 2025 = `expected_rows` 2025 | `decision.json` | `FILE_FIELD` |
| E2-2 | 五级阶梯 O→F→E→M→MV 完整单调的单元数 = `299`（分母 405） | `decision.json:monotone_staircase_units` | `FILE_FIELD` |
| E2-3 | 逐层转移：`O_to_F` 268/22/115；`F_to_E` 290/29/86；**`E_to_M` 79 改善 / 77 回退 / 249 平**；`M_to_MV` 114/0/291 | `decision.json:transition_counts` | `FILE_FIELD` |
| E2-4 | `protocol_disclosure` 自陈：O 为新跑 `NoImprovement(3000)`；F/E/M/MV 为 sealed v7 fixed-iteration archive reuse；`same_batch_or_same_machine_claim_allowed: false`；`archive_wallclock_available: false` | `decision.json:protocol_disclosure` | `FILE_FIELD` |
| E2-5 | 公开 MDVRPTW 侧固定协议只复现 13/18 个目标，判 `STOP_NOT_ALL_TARGETS_REPRODUCED`；未复现 PR14A/PR15A/PR15B/PR16A/PR24A | `docs/handoff/e2_final_closeout_20260727.md` | `FILE_FIELD` |
| **E2-结论** | **E2 的问题是口径边界（非同批同机、阶梯非普遍单调），不是实验失败** | — | 待复核 |

**要求复核方额外回答**：`sealed_rows_reused = 1620` 与 `O_new_rows = 405` 相加是否等于 2025；
若 O 与 F/E/M/MV 停止规则不同，1.919118% 这个差值有多少可能来自停止规则而非算法本身——
**这一问只要证据能不能支持判断，不要求给出结论**。

---

## 二、E4 碳感知充电择时

**权威证据目录**：`baselines/china_e3_e7/e4_carbon_timing_20260729/`

| 编号 | 断言 | 证据位置 | 状态 |
|---|---|---|---|
| E4-1 | `evidence_status = PASS_COMPLETE_ZERO_SEARCH_REPLAY`；`verdict = POSITIVE` | `decision.json` | `FILE_FIELD` |
| E4-2 | 主要终点 `charging_emissions_reduction_pct = 54.97037199876627` | `decision.json` | `FILE_FIELD` |
| E4-3 | `observed_pair_rows = 11340` = `expected_pair_rows = 11340`；`all_rows_retained = true` | `decision.json` | `FILE_FIELD` |
| E4-4 | `search_candidate_count = 0`、`rescue_tuning = false` | `decision.json` | `FILE_FIELD` |
| **E4-结论** | **E4 无问题；证据链在六组里最完整** | — | 待复核 |

**要求复核方额外回答**：`raw_runs.csv` 的行数与 11340 是否一致；
54.97037199876627% 能否从 `raw_runs.csv` 独立重算出来（给出重算值与差值）。

---

## 三、E5 非线性充电

**权威证据目录**：`baselines/china_e3_e7/e5_nonlinear_final_20260730/`

| 编号 | 断言 | 证据位置 | 状态 |
|---|---|---|---|
| E5-1 | 四个终点：NL90 完整可行率 20/20 = 100%；L100 假可行 0/20；共同可行配对成本变化 min=mean=median=max = **0.000%** | `decision.json` | `FILE_FIELD` |
| E5-2 | `charging_sessions.csv` 共 **196** 个会话（不含表头） | 同上 | `CLAUDE_COMPUTED` |
| E5-3 | 按 (instance_id, seed, vehicle_id, session_index) 配对，**L100_control 与 NL90_mild 的 `start_soc_pct`、`end_soc_pct`、`energy_kwh` 逐条完全相同**（键集相同、值全等） | 同上 | `CLAUDE_COMPUTED` |
| E5-4 | `start_soc_pct == 0.0` 的会话数 = **160 / 196** | 同上 | `CLAUDE_COMPUTED` |
| E5-5 | `charge_start_second == 0.0` 的会话数 = **140 / 196** | 同上 | `CLAUDE_COMPUTED` |
| E5-6 | `end_soc_pct` 中位数 = **37.03**、均值 = **46.95**（两臂相同） | 同上 | `CLAUDE_COMPUTED` |
| E5-7 | `end_soc_pct >= 99.9` 的会话数 = **36**；`nonlinear_minus_linear_seconds` 非零的会话数 = **36**；**两者是同一批会话** | 同上 | `CLAUDE_COMPUTED` |
| E5-8 | 那 36 个会话的时长差**取值只有一个**：`1264.6...` 秒（min = median = max） | 同上 | `CLAUDE_COMPUTED` |
| E5-9 | 文献曲线臂 `M17_22KW_NORMAL_PWL` 预测受影响会话 36/196 = 18.37%，`new_units_run = 0`，状态 `SKIPPED_CURVE_ALSO_UNEXPOSED` | `e5_literature_curve_20260731/decision.json` | `FILE_FIELD` |
| **E5-原因** | **车在车场从 0% 起充、充到够用即走 ⇒ 绝大多数会话到不了 90% 折减区；到得了的 36 个，其多出的 21.1 分钟落在运营时域开始前的行前充电段，不与任何约束竞争 ⇒ 成本效应必然为 0** | — | 待复核 |

**要求复核方额外回答**：
(a) 该 36 个会话的 `linear_duration_seconds` 是否都等于同一个值；
(b) 行前充电段（`charge_start_second == 0`）与运营时域起点之间的时间余量有多大——
**若余量小于 1264.6 秒，则"不与任何约束竞争"这一条不成立**；
(c) 是否存在任何一个会话，其非线性时长差导致了后续任务时刻的改变。

---

## 四、E3 跨场协同

**权威证据目录**：`baselines/china_e3_e7/e3_zone_joint_20260731/`

| 编号 | 断言 | 证据位置 | 状态 |
|---|---|---|---|
| E3-1 | `input_assignments.csv` 共 **300** 行（50c 50 客户 + 100c 100 客户，各 ZONE/JOINT 两臂） | 同上 | `CLAUDE_COMPUTED` |
| E3-2 | 字段 `registered_differs_from_nearest` **全部为 `False`**，即 **150 个客户错配 0 个** | 同上 | `CLAUDE_COMPUTED` |
| E3-3 | 登记车场推导规则 = `customer city -> the unique depot in that same city`，实现于 `solver/src/setp_solver/china81.py:355`；`literal_registered_depot_column_found: false` | `depot_field_investigation.json` | `FILE_FIELD` |
| E3-4 | 两个算例各只有 2 个车场（`D_guangzhou` / `D_shenzhen`），50c 分布 23/27，100c 分布 46/54 | `input_assignments.csv` | `CLAUDE_COMPUTED` |
| E3-5 | `ind_arm_run: false`，理由 `IND_AND_ZONE_INPUTS_IDENTICAL_BY_PRE_SEARCH_FACT` ⇒ 三臂设计实跑两臂 | `decision.json` | `FILE_FIELD` |
| E3-6 | 总体成本效应 `1.4829370445427614%`；50c `2.2727594138817997%`、100c `0.693114675203723%`；里程与碳排为**增加**（decision.json 中记为负的 reduction）；车辆数变化 −1.0 / −0.8 | `decision.json` | `FILE_FIELD` |
| E3-7 | 车队池化探针：POOLED 对 JOINT 三个种子分别 **−0.038% / 0.000% / −0.036%**（ZONE 2341.446790；JOINT 2289.318599 / 2288.011935 / 2288.011935；POOLED 2290.185753 / 2288.011935 / 2288.840467） | `e3_pooling_probe_20260731/raw_units/` | `CLAUDE_COMPUTED` |
| **E3-原因** | **算例把客户放在有车场的城市内，登记车场按"同城唯一车场"派生 ⇒ 错配按构造恒为零 ⇒ E3 声称测量的"责任错配"杠杆在正式算例上 0 实例；1.4829% 全部来自路径合并** | — | 待复核 |

**要求复核方额外回答**：
(a) `china81.py:355` 附近的实现是否真的排除了"客户所在城市没有车场"的情形；
若存在这种客户，它们被派给了谁；
(b) 81 个算例里是否**存在**错配非零的算例（不限于这两个正式算例）——
若存在，给出算例 id 与错配数；
(c) `e3_mismatch_20260731` 预注册的 6 个 150c/200c 算例的错配率分别是多少
（该任务 0 单元启动，但输入可能已构建）。

---

## 五、E6 参与与结算

**权威证据目录**：`baselines/china_e3_e7/e6_fairness_v3_20260731/` + `e6_allocation_20260731/`

| 编号 | 断言 | 证据位置 | 状态 |
|---|---|---|---|
| E6-1 | 无转移：`units_naturally_pareto = 0`、`units_f_equals_i = 20`、**`participation_satisfying_candidates_total = 0`** | `e6_fairness_v3/decision.json` | `FILE_FIELD` |
| E6-2 | 公平代价 `fairness_cost_pct = 1.511783666875632%` | 同上 | `FILE_FIELD` |
| E6-3 | 分配层 `route_search_executed: false`、`search_reruns: 0`、`data_source = e6_fairness_v3 certified I/U rows` ⇒ Shapley 为事后核算，未进入搜索 | `e6_allocation/decision.json` | `FILE_FIELD` |
| E6-4 | 有转移：19/20 可行；平均 Shapley 转移 `817.374756596798` 元；平均系统净节省 `45.35815099198` 元；比值 `18.020460241894`；人均净增 `22.67907549599` 元 | 同上 | `FILE_FIELD` |
| E6-5 | 1 个不可行单元：`cn-prd-100c-02-V2-LOCATIONS` seed 4，系统净节省 `−1.135377416539` 元，核为空 | 同上 | `FILE_FIELD` |
| **E6-结论** | **E6 不是失败；性质问题是公平机制事后核算、未参与搜索** | — | 待复核 |

**要求复核方额外回答**：`participation_satisfying_candidates_total = 0` 是在多大的候选池上得出的
（`candidate_pool_unique_total`、`candidate_full_evaluation_events` 分别是多少），
以及该 0 是"池子里确实没有"还是"池子太小"。

---

## 六、E7 动态需求 —— **本台账中问题最多、且明确未查清的一组**

**权威证据目录**：`baselines/china_e3_e7/e7_dynamic_v3_20260731/formal/{50c,100c,150c}/tasks/*.json`
**诊断报告**：`docs/handoff/e7_infeasibility_diagnosis_20260731/`

### 6.1 Claude 亲自复算的部分

| 编号 | 断言 | 状态 |
|---|---|---|
| E7-1 | 120 个单元：114 个 `status = LEGAL_INFEASIBLE`，6 个 `status = PASS`。50c 34/6、100c 40/0、150c 40/0 | `CLAUDE_COMPUTED` |
| E7-2 | 那 6 个 PASS 单元**没有 `feasible` 字段**，只有 `status` 与 `final_total_cost`；其余 114 个 `feasible = False`、`final_total_cost = None` | `CLAUDE_COMPUTED` |
| E7-3 | 种子到事件流映射 `stream_seed = ((algorithm_seed − 1) mod 5) + 1`；10 个算法种子只对应 5 条事件流 | `CLAUDE_COMPUTED` |
| E7-4 | 6 个 PASS 全部是 50c 的 seed 4 与 seed 9，两者共用 `stream_seed = 4`，各含三个滚动臂 | `CLAUDE_COMPUTED` |
| E7-5 | `STATIC_FIXED_RECOURSE` 在**全部 40 个** 50c 单元上均为 `LEGAL_INFEASIBLE`（含唯一跑通的 stream 4） | `CLAUDE_COMPUTED` |
| E7-6 | seed 9 的 CARBON_BLIND / FULL_ROLLING / NO_COOPERATION 的 `final_total_cost` **全部等于 5462.484679661239**；seed 4 的 CARBON_BLIND 与 FULL_ROLLING 均为 5975.267331229614，NO_COOPERATION 为 7217.318971600578 | `CLAUDE_COMPUTED` |
| E7-7 | 6 个 PASS 单元的 `carbon_aware_charging_shift_after_event = False`、`moved_charge_actions_after_event = 0`、`cross_depot_reassignment_after_event = False` | `CLAUDE_COMPUTED` |

### 6.2 助手报告、Claude 未独立复算的部分

| 编号 | 断言 | 状态 |
|---|---|---|
| E7-8 | 84/84 个滚动臂失败单元的 `actual_evaluations` 恰等于 `completed_stage_count × 1200 + 600` | `SUBAGENT_REPORTED` |
| E7-9 | 28/28 组三臂的失败文本**逐字节相同**（含 `top_rejections` 的路线名与计数） | `SUBAGENT_REPORTED` |
| E7-10 | A 块 24 个单元：新增订单在被处理时时间窗已过期；50c 上"首个含过期订单的阶段"与"滚动臂实际失败阶段" **5/5 精确相等**；最极端 `due − trigger = −5415.4` 秒 | `SUBAGENT_REPORTED` |
| E7-11 | 代码链：`dynamic_multitrip_schedule.py:1237-1248 / :719 / :743 / :466-469` | `SUBAGENT_REPORTED` |
| E7-12 | 碳开关接线缺陷：`run_e7_dynamic.py:504-571` 的 `corrected_initial_plan(arm,…)` 读 `arm` 只做合法性校验，`:539-540` 无条件送 aware，`:564` 硬写 `"strategy":"aware"` | `SUBAGENT_REPORTED` |
| E7-13 | `ARM_CONFIGS` 的 `route_policy`/`cooperation`/`participation`/`charging` 四键全仓库无读取点 | `SUBAGENT_REPORTED` |
| E7-14 | 150c 的 40 个单元共用 1 个名义方案 sha256（50c/100c 各 10 个） | `SUBAGENT_REPORTED` |
| E7-15 | 资产池封闭在名义方案已动用实体车上；合法车队上限 50c 12 vs 8、100c 23 vs 17、150c 35 vs 27 | `SUBAGENT_REPORTED` |

### 6.3 明确未查清

| 编号 | 事项 | 状态 |
|---|---|---|
| **E7-U1** | **100c/150c 的 60 个失败单元，具体卡在 `_dynamic_assignment_candidates`（`:702-747`）四个条件（车型 / 车场 / 最晚发车 / EV 电量）中的哪一个——不知道。** 落盘只保留 top-3 被拒路线名与计数，无条件级分解 | `UNVERIFIED` |
| **E7-U2** | **`per_search_pass_cap = 600` 只在 50c seed1 stream1 FULL_ROLLING 单阶段探针上标定，100c/150c 从未做过预算探针。故"预算不足"与"结构性无解"不可区分** | `UNVERIFIED` |
| **E7-U3** | B 块 30 个静态臂失败被称为"设计使然、跑前已写进自检通过条件（`run_e7_dynamic.py:1364-1377`）"——Claude 未独立核对该行 | `UNVERIFIED` |

**要求复核方优先处理 6.2 与 6.3**：6.2 的每一条都要从原始文件独立重算；
6.3 的三条要判断**在不重跑实验的前提下能查到什么程度**，并明确写出"要查清还差什么"。

---

## 七、基础设施类断言

| 编号 | 断言 | 证据位置 | 状态 |
|---|---|---|---|
| INF-1 | 车队定容判据 `_route_feasible` 只使用 `payload_capacity_kg("cv")`（1735 kg）与时间窗/路网；`num_ev(d) = max(1, ceil(0.25 R_d))` 由 `R_d` 派生；**EV 载重与电池不进入车队定容** | `baselines/china_instances/build_china81_finite_fleet_authority_v1_20260723.py:97-122, 202-212` | `CLAUDE_COMPUTED` |
| INF-2 | 提交 `54d78421`（2026-07-28）只改动 EV 字段（车型号、载重 1000→1700、整备质量 3300→2600、迎风面积、电池 140.41→77.28），**CV 侧无字段变化** | `git show 54d78421 -- solver/src/setp_solver/china81.py` | `CLAUDE_COMPUTED` |
| INF-3 | v2 重算与 v1 **逐行全等**：144 行差异 0；总 `R_d` 1040=1040；`num_cv` 1040=1040；`num_ev` 309=309；81 个 witness 的目标值与路线逐个全等，唯一不同字段是 `schema` | `data/ChinaInstances/china81_finite_fleet_authority_v2_20260731/comparison_vs_v1.json` | `CLAUDE_COMPUTED` |
| INF-4 | ⇒ 台账 L33 的前提（"旧 EV 载重推出的 `R_d` 不再有效"）**不成立**，因为 EV 参数从未进入 `R_d` | 推论 | 待复核 |
| INF-5 | **但**：`num_ev = 0.25 R_d` 的 0.25 来自储备系数 1.25（登记为构造情景），**且全过程从未校验 EV 77.28 kWh 能否完成分给它的路线** | 同 INF-1 | `CLAUDE_COMPUTED` |
| INF-6 | 碳日历 `tariff_carbon_hourly_calendar.csv` 只有一列 `carbon_factor_kgco2e_per_kwh`（12096 行）；`china81.py:816-817` 把同一值同时赋给 `actual_gco2_per_kwh` 与 `forecast_gco2_per_kwh` | 两文件 | `CLAUDE_COMPUTED` |
| INF-7 | **预测/实际机制在代码里是通的**：调度侧 `search/dynamic_multitrip_schedule.py:557` 默认 `forecast`；核算侧 `cost.py:652/740`、`search/multitrip_schedule.py:1402/1529` 默认 `actual`；**E4 本身 `run_e4_carbon_timing.py:568` 与 `:574` 按两个字段各算一遍** | 各文件 | `CLAUDE_COMPUTED` |
| INF-8 | 碳数据集 `10.6084/m9.figshare.28953545.v3` 共 7 个文件；本项目此前只下载 S1 与说明 PDF；2026-07-31 已补齐，7/7 MD5 与出版方公布值一致 | `data/Carbon/中国情景/cef_dataset_full_20260731/download_manifest.json` | `CLAUDE_COMPUTED` |
| INF-9 | 数据集自述为 **projected**（规划情景投影），逐小时值为"average emission intensity … calculated through power system operation simulation … not instantaneous values" | `Annotation_of_the_dataset.pdf` | `CLAUDE_COMPUTED` |

**要求复核方额外回答**：
(a) INF-5——在 81 个算例上，若把 `num_ev` 辆 EV 按 77.28 kWh 投入使用，是否存在
"该车场的 EV 无论如何都跑不完分给它的任一条路线"的情形？**只读判断，不跑搜索**；
(b) INF-7——除已列出的位置外，仓库内是否还有其他读取 `forecast_gco2_per_kwh` 的地方，
以及 E2/E3/E5/E6 的正式链是否用到了该字段。

---

## 八、Claude 在本会话已自我更正的两处（须一并复核）

| 编号 | 原结论 | 更正后 | 依据 |
|---|---|---|---|
| COR-1 | "本项目没有预测建模，故删除论文中预测/实际的区分"（已执行 `REG-20260731-B`，改了 12 处 TeX） | **该前提不成立**：预测/实际在代码中是真机制且 E4 本身用到（见 INF-7）。**改动方向错，需回退重做** | `docs/handoff/carbon_forecast_minimal_fix_20260731/` |
| COR-2 | "车队重算全等 ⇒ 好消息，可以往下走" | 重算全等是事实，但**它不等于车队构成合理**；EV 配额 25% 无依据且未校验续航（见 INF-5）；台账 L33 指错了对象（见 INF-4） | `HANDOFF.md` 2026-07-31 条 |

**要求复核方判定**：这两处更正本身是否成立；以及 COR-1 若成立，回退方案（建模章保留机制、
实验章说明中国算例两端同值）在文献与代码两侧是否都站得住。

---

*本台账由 Claude 于 2026-07-31 整理，共 6 组实验 + 基础设施 + 2 处自我更正。
台账本身不作结论。核查结果与逐条对账另存 `docs/handoff/claim_verification_result_20260731/`。*
