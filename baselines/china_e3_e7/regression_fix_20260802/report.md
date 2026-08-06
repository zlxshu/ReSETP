# W3 回归修复报告（2026-08-02）

## 结论

本任务判定为生产代码回归，不是 fleet authority v3 缺陷。两项指定测试已转绿，相关集合为 49/49，全量测试为 `909 passed, 1 skipped, 3 failed`；残留三项逐字匹配任务排除边界。81 算例 × 5 档零搜索复认证仍为 405/405，违反项为 0。终态为 `W3_REGRESSION_FIX_COMPLETE`，不触发 `HALT_AUTHORITY_DEFECT`。

## 1. FACT：authority 与测试契约

`data/ChinaInstances/china81_finite_fleet_authority_v3_20260802/fleet_caps.csv:50` 登记 `cn-jjj-10c-01-V2-LOCATIONS / D_beijing` 的 `T_d=2`，默认 25% 档为 `num_cv=1,num_ev=1`，同一行的 0% 档为 `num_cv=2,num_ev=0`。旧 v1 同一行（`...v1_20260723/fleet_caps.csv:50`）为 `2 CV+1 EV`、总上限 3。测试一在 `solver/tests/test_china81_shared_completion_20260720.py:33-48` 要求 completion 不劣于全 CV 参照；测试二在同文件 `:84-125` 明确给出 3 条路线并要求 2 条 CV trip、1 条 EV trip、1 次 mandatory assignment。

既有严格多趟实现 `solver/src/setp_solver/search/multitrip_schedule.py:902-1057` 会从 trip 时间构造物理车证书；其 CV 调度在 `:1069-1087` 只在上一趟返回不晚于下一趟出发时复用物理车。W3 直接复用该生产合同，没有另造放宽规则。

## 2. 根因一：错误的物理车标签制造了伪单调参照

修复前 `exact_china81_score`（任务开始时 `solver/src/setp_solver/china81_completion.py:84-105`）直接把传入 route id 交给 checker/evaluator。fixture 在 v3 全局 `num_cv=1` 下生成 `CV1#T1` 与 `CV1#T2`；checker 只取共同物理前缀 `CV1`，于是把两趟算作一台车并得到 499.75649570293297 元。

但两趟时间实际重叠：`CV1#T2` 在 43155.72188 秒出发、64295.04642 秒返回；`CV1#T1` 在 44177.6264 秒出发、63606.70414 秒返回。二者不能属于同一台物理 CV。严格多趟证书给出 2 台 CV；在 v3 同一 `T_d=2` 的 0% 档下，合法全 CV 参照是 669.7564957029331 元。默认 25% 档的 1 CV+1 EV 解为 577.531087595572 元，相对合法参照降低 92.22540810736109 元。因此数学单调性成立，坏的是旧评分路径对未经时序认证 `#T` 标签的信任。

修复后 `exact_china81_score` 在 `china81_completion.py:90-143` 显式区分 0% 全 CV 参照与活动混合车型上限；`:146-190` 先重建严格多趟物理车映射，再检查与计费。测试输入与内部 `baseline_all_cv_cost` 现在同为 669.7564957029331，最终 577.531087595572，二者均零违反。

## 3. 根因二：旧上限代码数的是路线，不是物理车

修复前 mandatory 路径（任务开始时 `china81_completion.py:226-249`）直接执行 `route_count > num_cv + num_ev`，因此 3 条路线面对 `1+1=2` 就抛出 `routes=3,num_cv=1,num_ev=1`；末端 `_require_finite_depot_fleet`（任务开始时 `:456-486`）也逐 route 累加车型数。

数值反例证明该判定不成立：全 CV 时 `R1` 为 40091.03456–46062.83456 秒，`R3` 为 48168.19208–65303.70414 秒，满足 `R1.return < R3.departure`，故两者可由同一 CV 执行第 1/2 趟；`R2` 为 43379.50364–51156.70364 秒，与 `R1` 重叠，全部三条路线只需 2 台 CV，而非 3 台车。把 `R2` 转为 EV 后，`R1→R3` 使用 1 台 CV，`R2` 使用 1 台 EV，恰好满足默认 `1 CV+1 EV`，最终成本 732.2834405333646，零违反。

修复后的物理车集合计数位于 `china81_completion.py:193-255`。mandatory 路径在 `:409-485` 只接受使 `(CV overage,EV overage,total overage)` 严格下降的候选；本例从 `(1,0,0)` 降到 `(0,0,0)`，转换 `route_index=1`。最终解在 `:526-539` 写入认证后的 `physical_vehicle#T` 标识，末端上限在 `:617-652` 按唯一物理车集合执行。测试仍保留 3 条路线、2 条 CV trip、1 条 EV trip和原全部断言，未改测试文件。

## 4. authority 缺陷判定

没有触发 `HALT_AUTHORITY_DEFECT`。反例不是 `T_d=2` 不足，而是旧代码把 trip 数误当实体车数。该车场 0% 档的 2 台 CV 覆盖和默认档的 1 CV+1 EV 覆盖都有明确时序见证；两项修复后均零违反。W3 没有改 v3 authority、没有恢复旧 `max(1,ceil(0.25·R_d))` 公式。

## 5. 回归与残留失败

两项目标节点首次修复后为 `2 passed in 0.30s`；最终源码复跑整个目标文件为 `3 passed in 0.40s`。China81 bundle、v3 authority、shared completion、multitrip scheduler 与 E3 capacity-rank 相关集合为 `49 passed in 4.04s`。

全量命令为：

```text
PYTHONPATH=solver/src:models/src:.:/opt/anaconda3/lib/python3.13/site-packages:build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests -q --tb=short
```

结果为 `3 failed, 909 passed, 1 skipped in 284.25s`。残留项分类如下：

1. `unresolved_historical`：`solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`，仍为 carbon-aware `feasible=False`。
2. `unresolved_historical`：`solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`，仍为 `root_cause=repair_logic_defect`。
3. `old_contract`：`solver/tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps`，当前表现为 candidate 4954.204438573212 不小于 initial 4923.553350198799；按 W2/W3 任务边界不处理。

没有剩余 `real_regression`。

## 6. 405 单元零搜索复认证

执行 `baselines/china_instances/build_china81_finite_fleet_authority_v3_20260802.py --audit-only`。输出为 0/25/50/75/100% 各 81，合计 405；`authority_total_physical_cap=943`、`depot_rows=144`、`x4_single_trip_total=1042`、`route_search_executed=false`、`search_evaluations=0`。构造器只做登记 EDF 路线族与兼容 DAG 路径覆盖复算，没有写回既有 authority 或 W2 结果目录，没有执行正式实验或路径搜索。

## 7. 文件边界与工作树

W3 唯一生产代码改动为 `solver/src/setp_solver/china81_completion.py`，净变动 215 行增加、49 行删除。没有修改测试。`git diff --quiet -- solver/src/setp_solver/check.py` 与 `git diff --quiet -- solver/src/setp_solver/search/evaluation.py` 均返回 0；`docs/paper_v2/paper_main.tex` 也返回 0。

`solver/src/setp_solver/cost.py` 在 W3 启动前已经是继承工作树中的 modified，W3 未编辑它；收口 SHA-256 为 `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`。最终审计时 `git diff --stat` 为 `36 files changed, 6190 insertions(+), 216 deletions(-)`；该总数包含继承改动与持续变化的 watchdog 日志，且不包含未跟踪的 W3 六件套，不能解释为 W3 独占差异。

## 8. DECISION

`W3_REGRESSION_FIX_COMPLETE`。两项真实回归已由生产代码适配 v3；全量剩余失败仅为明确排除的历史/旧契约项；405/405 零搜索认证保持成立。
