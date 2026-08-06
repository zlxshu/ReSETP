# T11 收窄充电重叠约束与首趟跨日核查

## 回归验证（最前）

`FACT` 收窄改动已写入 `solver/src/setp_solver/check.py::_check_charging_trip_overlap`：对 `route_timing` 同一公共站识别条件（站点类型为 `f`、站点在路线 `node_sequence` 中、`charge_day_offset == 0`）跳过在途公共站动作；未改 `cost.py` 或 `search/evaluation.py`。

`FACT` 七个强制恢复测试仍为 **0 passed / 7 failed**，触发 `HALT_REGRESSION_FAILED`，因此没有运行全量测试套件。T10 基线为 `898 passed / 1 skipped / 14 failed`；本任务不报告新的全量计数。

`FACT` 三个阳性见证仍全部被判违反：`C_seed2_budget1000`、`C_seed1_budget100`、`C_seed3_budget1000` 均命中 1 个 `CHARGING_TRIP_OVERLAP`。

`FACT` 对 T10 的 18 个已归档解只读复核：18/18 服务量红线通过，当前检查器违反数为 0，公共站充电动作数为 0；未重跑这 18 次搜索。

七项失败细节见 `regression_results.json`。其中公共站文件的两项仍有一个独立的跨日浮点端点误报（前一日车场动作绝对结束时刻为 `4.55e-13 s`，被算作与 `[0,2395.810388)` 相交）；精细充电文件的两项含有车场动作 `[8000,21090.909091)` 与 `route_timing` 外行程 `[0,10492.783666)` 的相交；搜索文件三项以 `HALT_H2: no feasible EV route with a nonzero charging action` 退出。没有修改测试文件或继续放宽约束。

## 保护文件与改动范围

`FACT` 开工前 SHA-256：

`cost.py` = `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；
`check.py` = `886e91108f666c4c4dcb379020b5ec4e055e9a6150fdb42d69bd1ffc9e5ad38c`；
`search/evaluation.py` = `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

`FACT` 收工后 SHA-256：

`cost.py` = `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；
`check.py` = `93139ea143d361d1b4cde7e9e2a34506bf90b95fe718809c1a467c2fd97b7f73`；
`search/evaluation.py` = `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

`FACT` 本任务的代码差异限于 `check.py` 的公共站跳过判据和说明文字。`cost.py`、`search/evaluation.py`、碳价、碳数据、电价、算例、车队合同、目标函数经济含义和论文目录均未改。

## 首趟充电跨日

`FACT` 这不是 T10 引入的新行为。当前源码中：

`solver/src/setp_solver/search/multitrip_schedule.py:44-45` 定义 `STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET = -1` 与 `STATIC_PREHORIZON_SECONDS = 86400.0`；`solver/src/setp_solver/search/multitrip_schedule.py:1724-1747` 用前置日长减去充电时长构造首趟充电窗口，并把动作写成 `charge_day_offset=STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET`。`git blame` 显示这两处行为来自提交 `90654b3e`（2026-07-13，`Fix overnight depot charge handling and update E3 handoff`），早于 T10；T10 的当前工作树差异没有新增这两行。现有 `solver/tests/test_multitrip_schedule.py:322-327` 也把证书首趟偏移固定为该常量，`solver/tests/test_nonlinear_charging_robustness_runner_20260717.py:51-79` 明确区分首趟 `-1` 与后续趟间 `0`。

`FACT` 当前结算链实际不按 `charge_day_offset` 选择日期表。`solver/src/setp_solver/china81.py:734-911` 的加载器按 bundle 的 `date` 只加载该日 48 槽并把 `date` 写入 profile 行；`solver/src/setp_solver/cost.py:584-648` 的 `charging_action_slot_breakdown` 用 `charge_start_second` 映射槽位，不读取 `charge_day_offset`；`solver/src/setp_solver/cost.py:723-753` 和 `1145-1201` 分别用传入的单日 profile 结算碳排与电价。因此 T10 18 次的实际结算 profile 是运行日 `2025-02-12`，不是 `2025-02-11`。

`FACT` 实际动作复算例：`C_seed2_budget1000` 的 `EV_D_beijing_1#T1` 首趟车场动作是 `charge_day_offset=-1`、`charge_start_second=20660.424789122`、`27.74184851091978 kWh`。当前成本链实际命中的行全部为 `date=2025-02-12`、`city=beijing`：半小时槽 12 的碳值 `593.7 gCO2e/kWh`、槽 13/14 的碳值 `584.9 gCO2e/kWh`，三行车场电价均为 `0.56328575 CNY/kWh`。这些行和能量分摊已落在 `regression_results.json`，可由 `regression_verify_narrowing.py` 重算。

`FACT` 18 次影响范围：18/18 次含首趟 `-1`，共 36 个首趟车场动作，涉及 `940.1574033147 kWh`。按当前代码实际使用的运行日表，合计充电排放为 `644.4711899761618 kgCO2e`，电费为 `485.6262571494881 CNY`。

`FACT` 为回答“若按前一日表再改成当日表”的反事实对照，使用同一批动作分别命中 `2025-02-11` 与 `2025-02-12`：前一日表为 `548.979730381574 kgCO2e`，当日表为 `644.4711899761618 kgCO2e`，当日减前一日为 **`+95.49145959458781 kgCO2e`**；两日对应电费均为 `485.6262571494881 CNY`。

`INFERENCE` 因此必须区分两个问题：若只是把当前动作字段从 `-1` 改成 `0`，当前 `cost.py` 已经使用 `2025-02-12` 的单日 profile，核算差额为 `0 kgCO2e`；若未来把 `-1` 解释为真正取 `2025-02-11` 的时段表，再改为运行日核算，则本 18 次批的排放会增加 `95.49145959458781 kgCO2e`。后者是日期语义的反事实计算，不是本任务实施的核算逻辑修改。

## 决策与停止

`DECISION` 不修改首趟跨日核算逻辑；是否保留 `charge_day_offset=-1` 属于建模选择，未替用户拍板。

`DECISION` `paper_claim_allowed=false`，本任务产物只支持技术审计边界。

`HALT_REGRESSION_FAILED` 七个强制恢复测试未全部通过。依任务停止条件，不继续全量测试，不修改测试文件，不修改 `cost.py` 或 `search/evaluation.py`，也不以调整核算口径救回回归。
