# W1 模型公式与合同变更报告

日期：2026-08-02  
变更编号：`MC-W1-F2-DEPOT-CONCURRENCY-01`  
终态：`W1_FORMULA_CHANGE_COMPLETE`

## 一、结论

W1 已按“先登记、后改码”完成。车辆固定成本现在按去重后的实体车计费，同车第二趟及后续趟不再重复收取 170 元；车场充电并发默认不设上限，旧的每场 2 个 22 kW 充电位保留为 `finite_instance` 可选配置；公共站枪数语义未变。W2 的固定车队总量口径没有在本任务实施。

回归 1--3 全部满足：E4 单趟 30/30、E6 单趟 30/30 的新旧固定成本按 binary64 逐位相等；20/20 多趟证书均精确满足“新值＝旧值－（路线数－实体车数）×170”；全量锚由 1040 趟×170＝176800 元变为 693 辆×170＝117810 元，减少 58990 元，即精确 33.3653846154%，按一位小数报告为 33.4%。因此按用户停止条件记为 COMPLETE。

五档零搜索核算也完成：0%、25%、50%、75%、100% EV 的认证数从 81/81/81/81/75 变为 81/81/81/81/81。全量测试为 901 passed、1 skipped、7 failed；7 项均已逐项分类，未改断言求绿，其中没有真实 W1 算术或公共站回归。

## 二、登记与证据

本轮第一笔仓库写入是在 `docs/handoff/model_change_approval_register_20260718.md` 末尾追加正式记录，登记前后 SHA-256 为 `9539a8ff...90a8c` 与 `eaaef2d5...1498a`。记录包含用户原文、公式、代码位置、页码、影响范围和本交付目录；既有登记内容没有改写。

固定成本文献册为 `fixed_cost_billing_literature.json`。Zhao 等（2024）p.923 式(1)与约束(6)对每辆实际使用实体车计一次，第二趟不再收费；Wang 等（2024）p.11 式(11)同口径；Zhen 等（2020）p.4 式(1)不设货币固定成本。已核 9 篇无一篇按配送趟数重复收费。

充电并发文献册为 `charging_infrastructure_classified.json`。真正建模充电的 7 篇中，李得成、Montoya、Hiermann、Schneider、Wang 等（2023）共 5 篇不设并发上限；Froger 等（2022）pp.467--468 与 Wu 等（2022）pp.11--12 设有限容量。本文旧“每场 2 个 22 kW 加并发约束”为构造设定、没有观察来源，因此默认采用 5/7 主流口径，同时保留有限容量敏感性入口。

## 三、代码合同

`solver/src/setp_solver/cost.py:164-170` 复用既有 `physical_vehicle_id` 去重结果，把固定成本改为 `(n_veh_cv+n_veh_ev)×vehicle_fixed_cost`。`solver/src/setp_solver/profit.py:91-110` 同步按“车型、实体车 ID”组成的键只向一个车场账本扣一次固定成本；若同一实体车跨多个 home depot，账本 fail-closed 报错，避免总成本和分车场利润互相矛盾。

`solver/src/setp_solver/model_config.py:13-46` 将模型配置升级为 `setp-model-config.v2`，新增 `depot_charger_capacity_mode`。默认值 `unbounded`；旧包或 Froger 式敏感性可显式传 `finite_instance`。

`solver/src/setp_solver/china81.py:161-175,277-286,602-612` 接收并记录配置。默认模式把车场 `Node.station_chargers` 设为 `None`；现有静态检查器把它映射为不可能约束 China81 路线数的客户数上界，因而在 China81 合同内等价于不设并发上限。有限模式仍读取实例中的 2。公共站在 `china81.py:615-628` 仍读取 `station_gun_count`，没有顺带改动。

受保护但未获本任务授权的 `solver/src/setp_solver/check.py` 与 `solver/src/setp_solver/search/evaluation.py` 前后 SHA-256 完全不变，分别为 `86b81315...702b` 与 `c7215263...fc3`。多趟排程文件 `dynamic_multitrip_schedule.py` 也未改。`docs/paper_v2/paper_main.tex` 前后均为 `76425e69...096f`，本轮没有修改 TeX。

## 四、论文写作阶段应直接采用的 F2 文本

建议正文文字：

> 车辆固定成本按实际启用的实体车计取，而非按配送趟次重复计取。一辆实体车只要承担至少一趟配送即产生一次固定成本；同一实体车执行第二趟及后续趟不再新增该项费用。

建议公式：

```tex
F_2
= c_{\mathrm{fix}} \sum_{v\in\mathcal V} y_v
= c_{\mathrm{fix}}\left(
    \sum_{v\in\mathcal V^{g}} y_v
    + \sum_{v\in\mathcal V^{e}} y_v
  \right).
```

符号说明：`\mathcal V` 是可用实体车集合，`\mathcal V^{g}` 和 `\mathcal V^{e}` 分别是燃油实体车与电动实体车集合；若实体车 `v` 至少承担一趟配送，则二元变量 `y_v=1`，否则为 0；`c_{\mathrm{fix}}=170` 元/辆。若仍保留趟次变量 `z_{vp}`，应明确 `y_v=\max_p z_{vp}`，而不是再对趟次求和计费。

## 五、可预测不变量

`raw_runs.csv` 共 486 行。其中 60 行为单趟不变量：从 90 份 E4 与 900 份 E6 保存解的完整排序总体中分别等距取 30 份，均满足路线数等于实体车数，旧值与当前 evaluator 的 `cost_fix` 逐位相等。

20 行为多趟不变量：从既有已认证且确有节车的证书中取 E4 10 份、E6 10 份，当前接口重新构造并验证证书后逐份计算。20 份均节省 1 辆实体车，所以每份实际新值均恰比旧值少 170 元，并与预测值逐位相等。逐份路线数、实体车数、旧值、预测值、实际值、源文件 SHA-256 和准备后解 SHA-256 均在 CSV 中。

1 行为全量算术锚：`1040×170=176800`，`693×170=117810`，差额 `-58990`。该行的预测值与实际值逐位相等。

## 六、车场并发五档零搜索复核

`raw_runs.csv` 保存全部 405 个实例--档位单元。旧口径中 399 行已认证，100% EV 档的 6 个 200 客户成渝/京津冀实例只因 `charger_schedule/deadline_dp_infeasible` 未认证。源 witness 已完成载重、时间窗、电池和单车同日发车前恰好够用充电检查，且六行的公共站或其他充电动作数均为 0。

本轮对六个实例分别加载默认与 `finite_instance` 配置：默认下所有车场 `station_chargers=None`，有限模式下均为 2；两种模式的公共站 ID 与枪数逐项相同。解除唯一的车场共享容量耦合后，六个登记 witness 获得认证，其余 399 行保持认证。因此前后五档为：

| EV 档位 | 0% | 25% | 50% | 75% | 100% |
|---|---:|---:|---:|---:|---:|
| 变更前认证数 | 81 | 81 | 81 | 81 | 75 |
| 变更后认证数 | 81 | 81 | 81 | 81 | 81 |

这是保存 witness 的零搜索可行性重算，没有启动路径搜索或正式实验。

## 七、测试结果与失败分类

聚焦测试覆盖成本、利润账本、China81 默认/有限模式、公共站不变和显式模型配置，结果为 32 passed。

权威全量命令保持原断言：

```text
PYTHONPATH=solver/src:models/src:.:/opt/anaconda3/lib/python3.13/site-packages:build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests -q --tb=short
```

结果为 901 passed、1 skipped、7 failed，耗时 299.18 秒。变更前权威基线为 901 passed、1 skipped、5 failed。本轮新增了 2 个通过的精确合同测试，同时 2 个原本通过的旧合同断言转为失败，所以 passed 数恰好仍为 901。

1. `test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`：变更前已失败；历史冻结保护合同与当前多份源码不一致，本次获批 `cost.py` 哈希变化又与旧冻结值不一致。归类为“既有失败＋批准后的旧保护哈希断言”，不是真实 W1 回归。
2. `test_e5_ablation.py::...test_r1_ablation_report...`：变更前已失败，碳感知臂仍不可行。归类为既有、与 W1 无关的真实未解缺陷。
3. `test_e5_ablation.py::...test_r2_ev_adoption_diagnostic...`：变更前已失败，仍报 `repair_logic_defect`。归类为既有、与 W1 无关的真实未解缺陷。
4. `test_ev_heavy_findability_gate.py::...test_winner_vehicle_type_swap...`：直接断言旧按趟计费下的改善。旧口径为 5803.553350198799→5754.204438573212；新口径下初始解复用 11 辆实体车、候选用 12 辆，故为 4923.553350198799→4954.204438573212。归类为“断言旧计费口径”；原断言保留未改。
5. `test_external_baseline_freeze_builder_20260717.py::test_candidate_probe_is_bound_to_current_adapter`：变更前已失败，冻结 probe 与当前 adapter 哈希漂移。归类为既有、与 W1 无关的实验产物哈希失败。
6. `test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`：变更前已失败，E4 全局 manifest 已有 5 项漂移；本次批准的 `cost.py` 变化也不能与旧 manifest 一致。归类为“既有失败＋批准后的旧哈希断言”。
7. `test_strong_bridge_backend_alignment.py::...test_decision_gate_reports...`：组件判断仍分别为 `A3_BACKEND_ONLY_PROMISING` 和 `A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED`，顶层只因 `protected_diff=['solver/src/setp_solver/cost.py']` 返回 HALT。归类为“批准后失效的旧保护哈希断言”；原断言保留未改。

真实 W1 回归数为 0。这里的“0”只指本任务批准的实体车计费、车场默认无并发和公共站保持不变合同；两项 E5 既有缺陷并未被本任务解决或掩盖。

## 八、影响与边界

所有既有成本数字在数值上作废。旧的目标值、排序、成本差、百分比、合作节省、Shapley/核仁输入及利润分配结果，都必须在新合同下重新核验；单趟保存解本轮数值恰好不变，不等于旧包可免除新口径登记。

本轮没有删除、移动或覆盖任何旧结果，没有运行正式实验或路径搜索，没有修改 TeX、`check.py` 或 `search/evaluation.py`。W2 才能实施固定车队总量口径；W1 不替 W2 作决定。
