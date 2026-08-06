# W2 车队 authority v3、冻结基线重锚与旧结果登记

终态：`W2_FLEET_AUTHORITY_V3_COMPLETE`。

## 1. 边界与批准

本任务执行用户 2026-08-02 的“口径 B，总量固定”“④更新”及“以前的数据和设计几乎全部作废，以最新的为准”。未修改 `docs/paper_v2/paper_main.tex`、`solver/src/setp_solver/check.py` 或 `solver/src/setp_solver/search/evaluation.py`；未删除、移动、覆盖任何旧结果目录；未运行正式实验或路径搜索。

## 2. 新 fleet authority

旧公式 `num_ev(d)=max(1,ceil(0.25*R_d))` 已废止。v1/v2 原目录、文件和哈希均保留，且仍可通过 `load_china81_bundle(..., fleet_authority=...)` 显式选择。`solver/src/setp_solver/china81.py` 的默认绑定已切换到 `data/ChinaInstances/china81_finite_fleet_authority_v3_20260802/`。

v3 在 W1 新合同下构造：多趟开启、车场并发默认不设、固定成本按实体车计费。每个车场先构造 CV-prefix 与 EV-prefix 两族确定性 EDF 路线见证，再对同型路线兼容 DAG 求精确最小路径覆盖。五档车型数继续用 Hamilton 最大余数分配。每场 `fleet_determinants.csv` 登记客户数、需求、载荷下界、端点路线数、兼容边数、最大匹配、最大同时占用、端点下界、选定 `T_d` 和旧 X4 上界；`witnesses/*.json` 给逐实例路线与排班见证。

结果如下：144 个车场的 `T_d` 合计 943，范围 2--22；端点下界合计 830。为同时覆盖五档，有 85 个车场在端点下界上增加合计 113 辆。81 个实例中 52 个检查了一个以上总量向量，单实例最多检查 34 个。旧 X4 单趟总量为 1042，因此 v3 少 99 辆，即 9.500959692898%。

最小性边界必须保留：943 是登记的两族确定性 EDF 路线见证与兼容 DAG 路径覆盖下的最小固定总量向量，不冒充所有潜在客户路径集合上的全局车队最优。

## 3. 五档零搜索认证与 W1 对照

`raw_runs.csv` 有 405 个数据行。0/25/50/75/100% 五档分别认证 81/81/81/81/81；违反项合计 0，故没有不可行行或违反项可列。路径搜索、正式实验和搜索评价数均为 0。

W1 的旧有限车场并发、旧 1042 车队为 81/81/81/81/75；W1 放开并发后，同一 1042 车队为 81/81/81/81/81；W2 换成 v3 的 943 车队后仍为 81/81/81/81/81。这里证明的是登记见证可行性，不是新路径优化结果。

## 4. 冻结基线重锚

详细前后表在 `docs/handoff/frozen_baseline_reanchor_20260802.md`。四类长期红灯分别是 E2 80 kWh 的八个活动语义文件、PyVRP candidate probe、E4 manifest 的五个活动源码项、strong-bridge 对 W1 `cost.py` 的工作树保护锚。旧 commit、旧 manifest、旧 probe metadata 和旧哈希全部原样保留；只新增/替换精确活动 SHA 锚。

v3 默认绑定还触发 `test_china81_bundle_20260720.py` 的三个旧车队数字面锚：2/1、3/1、2/1 均更新为 v3 的 1/1。没有删除断言、放宽比较或增加 skip/xfail。上述重锚及 v3 authority 定向测试合计 11/11 通过。

## 5. 旧结果逐包作废登记

`docs/handoff/superseded_results_register_20260802.md` 已逐包登记 E2 China81 五算法批、E3 正式包、E4 405×28 与 90 行包、E5、E6 900 行及其收入账/核仁下游、E7、v1/v2 和两条旧车队诊断。每项都有路径、原数值、失效原因和“不得作为结果引用”标记。

没有笼统宣布全部作废。公开 MDVRPTW 算例上的算法质量仍在原范围内有效；W1 新合同的算术和开关测试有效；旧保存解的逐位重放、记账恒等式和多趟接口只保留工程证据，不升级为科学结果；7 篇多趟车队文献的页级依据仍有效。

## 6. 全量回归

规范命令为：

```text
PYTHONPATH=solver/src:models/src:.:/opt/anaconda3/lib/python3.13/site-packages:build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests -q --tb=short
```

最终结果：`907 passed, 1 skipped, 5 failed in 286.88s`。

### 真实回归（2）

1. `solver/tests/test_china81_shared_completion_20260720.py::test_shared_completion_is_feasible_monotone_and_complete`：v3 的 10c 默认车队为 1 CV+1 EV，全燃油方案不再满足车型上限；mandatory EV 转换后的 577.531087595572 元不能与不满足 v3 上限的 499.756495702933 元伪参照比较。
2. `solver/tests/test_china81_shared_completion_20260720.py::test_shared_completion_enforces_depot_vehicle_type_caps`：旧 completion 直接执行 `route_count <= num_cv + num_ev`，把 3 条可多趟排班的路线当成 3 辆车，因 v3 的 1 CV+1 EV 抛出 `routes=3, num_cv=1, num_ev=1`。这是旧 completion 未接多趟实体车排班的接口回归，不能只改冻结值转绿，原断言保留。

### 未解决历史项（2）

1. `solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`：carbon-aware 保存路线仍不可行。
2. `solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`：仍返回 `root_cause=repair_logic_defect`。

### 旧契约（1）

1. `solver/tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps`：旧按趟计费合同要求候选严格改善；新按实体车计费后 `candidate_obj=4954.204438573212` 不小于 `initial_obj=4923.553350198799`。原断言保留，待该历史门另行重定义。

## 7. Git 与保护文件核验

交付时快照中，包含用户既有改动的完整工作树 `git diff --stat` 汇总为 `35 files changed, 5880 insertions(+), 167 deletions(-)`；这包括 W2 之前已经存在的 W1、其他未提交改动和仍在增长的 watchdog 日志，且 Git 的 diff 不显示未跟踪的 W2 新目录/文件。因此该数字是交付时快照，不是 W2 独占改动量。W2 路径的逐项 `git status --short` 已在执行记录中核对，没有删除或移动项。

保护文件的命令结果如下：

```text
git diff --quiet -- solver/src/setp_solver/check.py                 # exit 0
git diff --quiet -- solver/src/setp_solver/search/evaluation.py     # exit 0
git diff --quiet -- docs/paper_v2/paper_main.tex                    # exit 0
```

三项均无 Git diff。
