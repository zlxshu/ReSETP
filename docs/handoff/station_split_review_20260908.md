# 公共站 split 候选：对抗式代码审查

日期：2026-09-07（审查执行日；被审改动标注日 2026-09-08）
审查人：Claude（只读审查，未改任何仓库文件，未跑求解器搜索）
被审对象：
- `solver/src/setp_solver/algorithms/resetp_alns/support/charging.py`
- `solver/scripts/run_problem_hgs_private_technical.py`
- `solver/tests/test_public_station_split_charging.py`

复现环境：`.public-hgs-venv/bin/python3`，
`PYTHONPATH=$PWD:$PWD/solver/src:$PWD/third_party/setp_hgs_kernel:$PWD/models/src`。
本审查跑过的东西只有：单测、`solver/reports/station_split_probe_20260908/replay_repair_layer.py`、
`compare.py`，以及三段自写的只读脚本（充电修复层重放 + 车场起充电量扫描），
没有启动任何一次求解器搜索。

---

## 总判

**需修后接受。** split 这一层的电量、时间、计价三项守恒都走既有的同一条构建与校验路径，
没有发现"评了分但没校可行性"的口子（A 属实）。但有两个问题必须先处理：

1. **断点枚举漏掉了本算例上最优的那个点，而且漏得很系统**（B）。
   在唯一一趟 split 严格更优的行程上，均匀扫描找到的最好方案比枚举出来的最好方案
   再便宜 **2.17～2.26 元**；而 split 相对 parallel 自己号称的收益只有 **0.28 元**。
   漏掉的正是代码注释里"故意不要"的那个上端点，而它被排除的理由
   （"车场全包 + 一段没意义的绕行，必被车场方案支配"）在本算例里是错的——
   绕行是负的（−1305 m），所以那个点不但没被支配，还比车场方案便宜。
   **代码用来解释 split 为什么能赢的那条理由，恰好推翻了它用来剪掉最优点的那条理由。**
   要修的是那条错的理由，**不是**把那个点加回候选集——那个点上站只买 1e-6 kWh，
   加回去等于把"绕道反而更短"这个矩阵伪影当成 split 的成果（详见 B 与 H-7）。
2. **正式静态主线的默认口径被悄悄改了，这件事得你拍板**（D）。
   改动前命令行没有这个开关、`_policy` 里写死 `parallel`；改动后命令行默认 `split`。
   仓库里已落盘的所有正式结果都是 parallel 跑出来的，且旧结果包的 metadata 里
   根本没有这个字段（`compare.py` 打印 `mode=(not recorded)`），无法从产物反查口径。
   是改回 parallel 还是保留 split 并在交接里写死"两批数字不同源"，见修改清单第 2 条。

同时要说清楚一件事：**四次短跑里 split 的最终解总成本都比 parallel 差**
（+3.80 元 / +22.22 元），四次最终解的站充电量全部为 0。也就是说，
到目前为止这套新增的候选在端到端上没有拿出任何正收益，只有额外开销。

---

## A. 正确性：候选是否被评分而未校可行性

**结论：属实（未发现漏检路径）。**

- split 候选与 fallback / parallel 候选**共用同一个构建函数**
  `_repair_route_charging_candidate`（charging.py:1036）。
  `build_forced`（charging.py:805-830）只改 `depot_precharge_target_kwh` 与
  `forced_station_path` 两个入参，不绕开任何规则分支。
- **电量守恒**：车场侧由 `_depot_precharge_action`（charging.py:1368）校验，
  1414-1422 行显式拒绝 `target < initial_battery` 或 `> battery_cap`；
  站侧由 `_best_station_insert` 按到达电量算充到目标位。
  沿线电量由 `_first_direct_infeasible_offset`（charging.py:1240）逐弧递减并检查，
  **回场那一弧也在检查范围内**（它先减电再判负，之后才因遇到 d/f 节点返回 None）。
- **时间可行性**：构建函数本身**不比对客户 due_time**，但这不是漏洞——
  候选出去后由 `_rebuild_ev_duty`（problem_hgs/charging.py:2053）
  调 `prepare_multitrip_solution` + `validate_multitrip_certificate`，
  而 `prepare_multitrip_solution` 的 `tolerate_infeasible` 默认 **False**
  （multitrip_schedule.py:2066），于是超时间窗的候选在 `route_timing` 里
  直接 raise（multitrip_schedule.py:602/635），被 1341/1415 行的 `except` 丢掉，
  **是"剔除"不是"扣分"**。这一点很关键：如果是软惩罚，split 更大的候选表
  就会给违窗方案更多中标机会；现在不是。
- **实测**：把 4 个已落盘运行包的全部 EV 行程重放，两种模式下的**每一个**候选
  都过 `route_timing(validate_battery=True, tolerate_time_warp=False)`：
  parallel 441 个候选 0 个不可行，split 512 个候选 0 个不可行，中标者也全部可行。
- **电费与碳按各自时段计价**：车场与站是两条独立的 `ChargingAction`，
  各带自己的 `charge_start_second` / `charge_day_offset`，
  由 `charging_action_electricity_cost` / `charging_action_emissions_kg` 分别按
  半小时槽积分；服务费走 `public_total_cny_per_kwh`，只对站那条动作生效。
- **绕行的电耗与时间进目标**：进。绕行改的是 `route.node_sequence`，
  `evaluate()` 按新序列算距离/能耗/时间，`route_model_cost` 就是拿它算的。

**一处需要澄清、但不是本次引入的**：charging.py:1125
`coverage_targets = future_targets if depot_precharge_target_kwh is not None else ...`
——只要给了车场起充电量，站就按"覆盖整条剩余路线"来定充电量。
这条对 parallel 和 split 完全一样，是既有行为，不记在本次改动头上。

**一处残留风险（未观测到实例）**：`repair_route_charging`（charging.py:554）
是"直接取成本最低的一个"，中间没有可行性筛。它被
`_repair_one_ev_duty`（problem_hgs/charging.py:1729）用。
split 把候选表做大以后，理论上可能出现"新的最便宜候选恰好过不了 duty 级校验、
于是整个 duty 修复抛错"，而 parallel 时选中的是能过的那个。
我在 4 个运行包上没有观测到这种情况（见上，0/512），
但这是 split 引入的一个新暴露面，值得知道。

## B. 断点论证：会不会漏掉严格更优的 x

**结论：不属实——会漏，而且在本算例上漏掉的就是最优点。**

先说枚举本身的方向性：在**起充时刻固定**的前提下，
`_split_depot_launch_levels`（charging.py:917）的断点集合是**超集**，这一点站得住——
车场侧对 `initial_battery → upper` 整段跨槽边界取反函数，
站侧用的是"发车电量最低"那个建构下的会话时长，也就是**最长**的一次站充，
更高的 x 只会让站充变短，跨的槽边界是这个集合的子集。
执行方自己承认起充时刻会随 x 重选，因此这只是候选集不是最优性证明——这句话本身对。

问题不在这里，在**被故意排除的上端点**。函数 docstring 写：

> 上端点（站不充电）被故意排除：它是"车场方案 + 一段没意义的绕行"，
> 被列表里已有的车场方案支配。

这条推理**只在绕行为正时成立**。而执行方给出的 split 获胜原因恰恰是
"车场→站→客户比直达短 1305 m"——绕行是负的。绕行为负时，
上端点不是被支配，而是全场最便宜。

实测（`grid2x2_midday_p1_parallel` 的第 13 趟，
路线 `D_OSM_WAY_1071205721 → C005 → C045 → C021 → 回场`）：

| 方案 | 车场取电 kWh | 站取电 kWh | 单趟目标成本 |
|---|---|---|---|
| 纯车场（depot_fallback） | 全量 | 0 | 316.659 |
| split 枚举出的最好点（唯一的内部断点，x=5.055） | 5.055 | 4.937 | **316.377** |
| 均匀扫描找到的最好点（x=9.988，逼近上端点） | 9.988 | 0.0045 | **314.397** |
| 换一个站 S_OSM_WAY_1348314458 的上端点（x=9.8626） | 9.863 | 1e-6 | **314.121** |

也就是说：枚举拿到的收益是 316.659−316.377 = **0.283 元**，
而它漏掉的收益是 316.377−314.121 = **2.256 元**，差了 8 倍。

放大到全部重放行程（6 个运行包、39 趟含公共站候选的行程、
每趟每站 200 点均匀扫描）：**4/39 趟**的均匀扫描严格优于断点枚举，
累计漏掉 **3.65 元**（同口径单趟目标成本）。
而 split 在这 39 趟里自己拿到的严格收益只有 1 趟 0.28 元。

**关于"要不要在断点之间补少量均匀档位"：不建议补，而且也不建议直接把上端点加回来。**
本算例上的缺口全部集中在被排除的上端点，但看清楚那个点是什么：
在 `x = upper − 1e-6` 处站只买 **1e-6 kWh**——它根本不是一个"分摊"方案，
是"车场全包 + 顺路从站门口开过去"。把它当作 split 候选加回来，
等于让这个功能的招牌收益变成一个绕行伪影借充电功能上桌。
均匀档位只在"起充时刻随 x 重选导致成本函数在段内非线性"时才有额外价值，
这一部分我没有测出证据。

**所以真正的缺陷不是"排除了上端点"，而是"排除它时给的理由是错的"。**
docstring 里"被车场方案支配"这句话只在绕行非负时成立；
在本算例上它不成立，而且不成立的方向恰好是执行方用来解释 split 为什么能赢的那个方向。
这条证据的价值在于：它说明 split 在这个算例上拿到的 0.28 元，
主体也是路线抄近道，不是车场/站的电价套利。要不要把这条抄近道收进模型，
是 H-7 那道题，不是这个函数该自作主张的事。

**另一层要提醒的**：这 2.26 元的来源不是充电套利，是**距离抄近道**——
在 x=9.99 那个方案里站只充 0.0045 kWh，几乎不充电，
收益全部来自"绕道经过站点反而比直达短 1305 m"。
路网矩阵是最快路径距离，本算例 3241644 个三元组里有 **50906 个（1.57%）违反三角不等式，
最严重的一个短 7588 m**。这意味着：充电修复层正在被当成一个**改路线的算子**用，
而路由搜索本身不会把站点当普通节点插入。
如果这条抄近道被留在正式结果里，那"split 的收益"讲出来其实是"矩阵不满足三角不等式"，
不是充电决策的改进。**这件事本身值得单独定夺，不是 split 的锅，但 split 把它放大了。**

## C. 逐位不变：parallel 候选 ⊂ split 候选

**结论：属实（我独立复现了）。**

执行方留的重放脚本 `solver/reports/station_split_probe_20260908/replay_repair_layer.py`
比的是**完整候选表**（`plans` 列表逐项 in 判断），不是只比中标者——这一点先核过了，
它确实在测它声称的东西。

我在 **6 个运行包** 上跑了它（执行方只报了 44 趟，我跑到 70 趟）：

| 运行包 | 趟数 | parallel 候选 | split 候选 | split_levels | parallel⊂split | 中标改变 |
|---|---|---|---|---|---|---|
| policy_combos/midday_subsidy/run_01 | 13 | 107 | 116 | 19 | 是 | 0 |
| grid2x2_v3/midday/P=1.0/MTC-HGS/run_01 | 13 | 74 | 86 | 27 | 是 | 0 |
| probe/midday_subsidy_split | 12 | 167 | 195 | 38 | 是 | 0 |
| probe/grid2x2_midday_p1_split | 10 | 108 | 130 | 32 | 是 | 0 |
| probe/midday_subsidy_parallel | 8 | 50 | 56 | 17 | 是 | 0 |
| probe/grid2x2_midday_p1_parallel | 14 | 210 | 254 | 56 | 是 | **1（严格更优）** |
| 合计 | 70 | 716 | 837 | 189 | 全是 | 1 |

唯一那趟严格更优的确认在 `grid2x2_midday_p1_parallel` 第 13 趟，
316.659246577 → 316.376580387，中标方案里确有一次真实公共站会话（4.937 kWh）。
**"1305 m" 这个数字我单独核过：`d(场,站)+d(站,C005)−d(场,C005) = −1305.28 m`，逐位吻合。**

## D. 默认值分层

**结论：部分不属实——库内默认没问题，但正式静态主线的默认口径确实被改了。**

活的调用点（排除 `solver/reports/` 下的历史快照与测试）：

| 位置 | 传不传模式 | 传什么 |
|---|---|---|
| `algorithms/problem_hgs/charging.py:1172` (`build_dynamic_ev_duty_charging_candidates`) | 传 | **写死 `"parallel"`** |
| `algorithms/problem_hgs/charging.py:1325` (`trip_options`) | 传 | `policy.public_station_candidate_mode` |
| `algorithms/problem_hgs/charging.py:1729` (`_repair_one_ev_duty`) | 传 | `policy.public_station_candidate_mode` |
| `china81_completion.py:420` | 传 | 函数入参，默认 `fallback` |

- `ChargingRepairPolicy`（problem_hgs/charging.py:577）**没有默认值**，
  注释写"no hidden defaults"，属实——每个构造点都得显式给。
- 全仓只有**一个**活的 `ChargingRepairPolicy(...)` 构造点：
  `run_problem_hgs_private_technical.py:332`（`_policy`）。其余全在测试里。
- `complete_china81_route_skeleton`（china81_completion.py:330）
  **在活代码里没有调用者**（只出现在 `tools/quality/vulture_whitelist.py:231`），
  它那个 `fallback` 默认不影响任何正式结果。

**真正的问题：默认从 parallel 翻到了 split。**
`git show HEAD` 对照：改动前命令行**根本没有** `--public-station-candidate-mode`，
`_policy` 里写死 `public_station_candidate_mode="parallel"`；
改动后 `_policy` 默认 `SPLIT_PUBLIC_STATION_CANDIDATE_MODE`（runner:330），
命令行 `default=SPLIT_PUBLIC_STATION_CANDIDATE_MODE`（runner:1890）。

后果：
1. **仓库里已落盘的正式静态结果全部是 parallel 跑的**，从今往后不加开关重跑就是 split，
   两批数字不同源。
2. 旧结果包的 metadata 里没有这个字段（`compare.py` 对参照运行打印
   `mode=(not recorded)`），**无法从产物反查口径**。新写的
   `metadata["public_station_candidate_mode"]`（runner:3071）取的是策略生效值，
   这个做法对，但只对新跑的包有用。
3. 动态实验那条线（`build_dynamic_ev_duty_charging_candidates`）写死 parallel，
   不受这次默认翻转影响——静态与动态两条线现在用**两种不同的候选口径**。

## E. 删除安全

**结论：属实。**

被删的六个名字在 `solver/src/setp_solver/algorithms/resetp_alns/support/charging.py`
里确实没有残留引用，全仓其余引用**全部指向另一个分叉**
`solver/src/setp_solver/search/charging.py`（该文件未被本次改动触及），
以及从该分叉 import 的测试：

| 名字 | 剩余引用 |
|---|---|
| `solve_charging_fixed_route` | `search/charging.py:69`、`algorithms/problem_hgs/mechanical_baseline.py:21,617`、`tests/test_e5_ablation.py`、`tests/test_nonlinear_cost_check_nl2_20260720.py` |
| `solve_charging_naive` | `search/charging.py:44`、`tests/test_e5_ablation.py:12,68` |
| `replay_fixed_route_charging` | `search/charging.py:215`、`tests/test_e5_ablation.py:10,81-82` |
| `_energy_to_next_chargeable` | 仅 `search/charging.py:100,381` |
| `_select_charge_start` | 仅 `search/charging.py:136,170,555` |
| `_earliest_slot_start` | 仅 `search/charging.py:571,575` |

`docs/handoff/station_topup_algorithm_design_20260907.md:177-178` 里对这几个名字的
行号引用现在过期了（指的是被删的那一份），文档层面的小账，不影响代码。

## F. 旧分叉 `search/charging.py` 在动态实验里到底给谁用

**结论：查清了。不是"路线不变的对照"，不违反 09-06 那条令。**

调用链：
`run_dynamic_experiment.py` → `main3b_backend.py:59` import
`mechanical_baseline.{insert_initial_customer, insert_revealed_customer}` →
`_insert_one_customer` → `_evaluate_candidate`（mechanical_baseline.py:544）→
`_with_current_first_trip_depot_charge`（同文件 572）→
`solve_charging_fixed_route(strategy="naive")`（同文件 617）。

论文里的三条臂（`run_dynamic_experiment.py:36-38` ↔ `paper_main.tex:1421-1452`）：

| 代码常量 | 论文名 |
|---|---|
| `ARM_MECHANICAL = "sequential_insertion"` | 顺序插入策略 |
| `ARM_DYNAMIC = "rolling_reoptimization"` | 滚动重优化策略 |
| `ARM_STATIC = "full_information_reference"` | 完全信息静态参考 |

关键在 mechanical_baseline.py:585：
`if evaluator.context.dynamic_state is not None: return candidate`。
两条在线臂用的评价上下文都由 `_build_stage` 造，带 `dynamic_state`
（main3b_backend.py:1093/1101），所以**在两条在线臂里这个函数是空转**。
它真正生效的地方是 `dynamic_state=None` 的静态上下文，
其中最明确的一处是 `full_information_static`（main3b_backend.py:641）
逐个塞动态客户建静态参考时（同文件 715）。

所以：
- 它**不是一条臂**，是"插入一个客户之后，把这辆静态 EV 第一趟的车场补电重算一遍"的
  内部工具。所谓 fixed-route 只是"在给定这一条序列时定价"，不是"整条方案不许改路线"。
- 论文那张表里的三条臂**没有一条**是"路线不变、只重排充电"的对照。
  完全信息静态参考是拿全天订单重新完整求解，不是回放。
- **但有一处口径分叉值得单独报**：完全信息静态参考那条臂的第一趟车场补电，
  是用**旧分叉**的 `solve_charging_fixed_route(strategy="naive")` 算的，
  不走新的 split/parallel 修复层。也就是说，动态那张表里的静态参考，
  和正文其他静态实验用的充电决策规则**不是同一套**。
  这跟本次改动无关（是既有状态），但一旦以后要解释"静态参考 4137.86 元怎么来的"，
  这条会被问到。

## G. 测试

**结论：4 个测试全过，但需要先设 PYTHONPATH；第 4 个测试的名字比它测的东西大。**

- 仓库**没有 conftest.py，pyproject 里也没有 pytest 的 pythonpath 配置**。
  按任务里给的命令原样跑**会失败**：
  `ModuleNotFoundError: No module named 'setp_solver'`，收集阶段就中断。
  必须补 `PYTHONPATH=$PWD:$PWD/solver/src:$PWD/third_party/setp_hgs_kernel:$PWD/models/src`
  才能跑，补上后 `4 passed in 0.12s`。
  也就是说，执行方"pytest 395 passed"这句话**按字面复现不了**，
  它隐含了一个没写出来的环境前提。补上前提之后数字是对的（见文末）。
- 四条断言各自测的东西：
  1. `test_split_beats_both_endpoints_with_a_real_public_session`——
     真的在测"内部点严格优于两个端点"，并且校了站充电量 > 0、车场取电严格夹在两端点之间。**扎实。**
     但要注意：这个合成算例里 F1 被造在 D0→C1 的正中间（30000+30000=60000），
     **绕行恰好为零**，所以它没有测到绕行代价，也没有测到本审查发现的负绕行情形。
  2. `test_winning_split_level_is_one_of_the_enumerated_breakpoints`——
     只测"赢家在枚举出的断点里"，**不测"枚举出的断点里有全局最优"**。
     这正是 B 里漏掉的那件事，测试测不到。
  3. `test_fallback_and_parallel_candidates_survive_unchanged_under_split`——
     测子集关系，方法对。
  4. `test_service_fee_calendar_leaves_the_depot_plan_on_top`——
     **不是数值巧合，但也不是它标题说的那件事。** 它不会因为凑巧过：
     该日历下公共价 = 车场价 + 0.40，逐时段严格更贵，车场必赢。
     但它同时叠了另一个更强的条件——车场有一个 0.30 的便宜半小时而其余全是 **3.00**，
     且这个便宜槽在发车窗内、站充只能在白天。所以"车场赢"里有多少来自服务费、
     多少来自那个独占的便宜槽，测试分不开。而且 3.00 元/kWh 不是真实中国算例的车场价，
     docstring 说"保持真实价格形态"，只在服务费那一项上成立。

（全量 `pytest solver/tests -q` 我另起了一次，结果见文末补记。）

## H. 其他

1. **`SPLIT_DEPOT_LEVEL_TOLERANCE_KWH = 1e-6` 没有取值依据。**
   对 77.28 kWh 的电池来说这是 1.3e-8 的相对量，实质是浮点精确去重，
   不是"两个决策是否相同"的物理阈值——差 1e-5 kWh 的两个档位会各建一次。
   但 `add_public` 会用 route + actions 全等再去一次重，所以**不会让候选表膨胀，
   只是白跑 rebuild**。实测：6 个运行包共枚举 189 个档位，最终只接受 121 个候选（64%），
   剩下 36% 是重复或建构失败（x 过高时站充电量归零，
   `station_insertions < len(forced_station_path)` 抛错，`build_forced` 吞掉返回 None）。
   建议按性能项处理，不当缺陷。
2. **计数器无溢出风险**（Python int），接线正确：
   `station_split_levels` 在 143 行初始化、
   `charging_repair_runtime_diagnostics()` 的 `totals` 里有 `"split_levels"`（335 附近）、
   `diagnostics()` 输出 `"split_levels"`（376 附近），三处一致。
3. **metadata 字段兼容性没问题。** `run_problem_hgs_private_technical.py:2785-2800`
   和 3143-3153 都是**按 key 遍历**做前后差，新增 `split_levels` 不会打断；
   `public_station_candidate_mode` 是新增顶层键，也是加法。
   **但反过来有个证据链缺口**：旧运行包没有这个键，
   `compare.py` 对两个参照运行打印 `mode=(not recorded)`，
   现有正式数字的候选口径无法从产物里读出来，只能靠"改动前写死 parallel"这条代码史推断。
4. **fallback 哨兵的改法对。** 原来是 `== DEFAULT_PUBLIC_STATION_CANDIDATE_MODE`，
   现在是 `== FALLBACK_PUBLIC_STATION_CANDIDATE_MODE`（charging.py:708）。
   今天两者取值相同、行为不变，但把"哨兵"和"默认值"解耦了，
   以后再改默认值不会顺手改掉 fallback 的语义。这是个好改动。
5. **复杂度 +8～18% 大致属实，下限偏乐观。**
   六次重放的修复层墙钟：+2.1% / +7.5% / +12.0% / +16.3% / +10.0% / +14.9%，
   候选数 716 → 837（+16.9%）。真实短跑里 `candidate_rebuilds` 30026 → 33862（+12.8%）。
   所以区间应写作 **+2%～+17%**，不是 +8%。
6. **四次短跑最终解站充电量全为 0，属实**，但同一批数据还有一件没被报的事：
   **split 的最终解总成本两次都比 parallel 差**（2523.81→2527.61，+3.80；
   2723.17→2745.38，+22.22）。单次跑、内核种子每次新抽，
   不能据此断定 split 更差，但也**不能拿这四次跑说 split 无害**。

---

## 修改清单

必改：
1. **改掉 `_split_depot_launch_levels` docstring 里那条错的支配论证。**
   现在写的是"上端点＝车场方案＋一段没意义的绕行，被列表里的车场方案支配"，
   这句话只在绕行非负时成立；本算例上绕行是 −1305 m，那个点不但没被支配，
   还是全场最便宜（314.12 对 316.38）。要改成"仅当绕行非负时成立"，
   并在函数注释或本文件里记下这条实测。
   **不要顺手把上端点加进候选集**——那个点站只买 1e-6 kWh，加进去等于把绕行伪影
   当成 split 的成果，要不要收这条抄近道是下面第 7 条那道题。
2. **默认口径翻转这件事必须让用户拍板，不许代理自己定。** 事实是：
   改动前命令行没有这个开关、`_policy` 写死 `parallel`；改动后默认 `split`。
   已落盘的正式数字全是 parallel 跑的，且旧包 metadata 没有这个字段可查。
   两个选项二选一：
   (a) 把 `_policy`（runner:330）和命令行（runner:1890）的默认改回 `parallel`，
       split 只在显式传开关时生效——代价是这个功能默认不参与任何跑；
   (b) 保留 split 默认，但在交接文档里写明"2026-09-07 之前落盘的全部正式结果
       都是 parallel 口径，此后重跑的是另一条线，两批数字不得混用"。
   我给的证据支持"这件事必须挑明"，但不支持替用户挑哪一个。

建议改：
3. 补一条测试，测**函数真正声称的那条性质**：在起充时刻固定的前提下，
   枚举出的档位覆盖了车场侧与站侧跨过的全部时段边界与充电曲线折点。
   不要写成"均匀扫描不优于枚举"——那条今天就会红，而且会被"把上端点加回来"
   这个错误的改法修绿。现有第 2 条测试只测"赢家在断点里"，测不到覆盖性。
4. 把第 4 条测试的车场贵价档从 3.00 降到真实量级，或者拆成两条
   （一条只变服务费、一条只变便宜槽），否则标题声称的"真实价格形态"名不副实。
5. 给 `SPLIT_DEPOT_LEVEL_TOLERANCE_KWH` 写一句取值依据；
   或者干脆调到有物理含义的量级（比如 1e-3 kWh），省掉 36% 的白跑 rebuild。
6. 更新 `docs/handoff/station_topup_algorithm_design_20260907.md:177-178` 里
   对已删函数的行号引用。

需要用户拍板、不属于代码修改：
7. **"绕道经过站点比直达短 1305 m"这件事怎么办。**
   本算例路网矩阵 1.57% 的三元组违反三角不等式（最严重 −7588 m）。
   split 拿到的收益、以及修好上端点之后会拿到的更大收益，
   主体都不是充电套利而是这条抄近道。若留在正式结果里，
   "split 的收益"讲出来其实是矩阵性质，不是充电决策。
   两条路：(a) 承认并在正文说明最快路径矩阵不满足三角不等式；
   (b) 只把站点当充电点，禁止它产生净负绕行收益。这需要用户定。

---

## 补记：全量测试

补上 PYTHONPATH 后跑 `pytest solver/tests -q`：

```
395 passed, 9 warnings, 23 subtests passed in 265.23s (0:04:25)
```

**执行方声称的 395 属实**（在补齐 PYTHONPATH 的前提下）。
过程中有 9 条 warning，其中包括 `test_runner_improvement_trace.py` 的
`PyVRP PenaltyBoundWarning`（惩罚参数打到上限），是既有噪声，与本次改动无关。

