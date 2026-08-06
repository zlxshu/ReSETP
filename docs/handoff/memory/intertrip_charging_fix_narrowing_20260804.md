# T11 收窄充电重叠约束与首趟跨日核查（2026-08-04）

状态：`HALT_REGRESSION_FAILED`，`paper_claim_allowed=false`。

`FACT` `check.py::_check_charging_trip_overlap` 已按 `route_timing` 的同一公共站判据跳过在途公共站动作：站点类型 `f`、站点在路线 `node_sequence` 中、`charge_day_offset=0`。`cost.py` 与 `search/evaluation.py` 未改。

`FACT` 七个强制测试为 0/7；三个阳性样本 3/3 命中 `CHARGING_TRIP_OVERLAP`；T10 18 个保存解当前复核 0 违反、服务量全过、公共站动作数 0。因七项门禁未闭合，未跑全量测试套件。

`FACT` 首趟 `charge_day_offset=-1` 是 2026-07-13 提交 `90654b3e` 的既有 overnight 设计，当前 T10 没有引入。当前 China81 评价器加载运行日 `2025-02-12` 的单日 profile，成本函数按 `charge_start_second` 找槽而不按 `charge_day_offset` 换日期。18 次共 36 个首趟动作、940.1574033147 kWh；当前代码排放 644.4711899761618 kgCO2e。真正使用 `2025-02-11` 的反事实表为 548.979730381574 kgCO2e；当日减前一日为 +95.49145959458781 kgCO2e。仅把字段改为 0 的当前代码差额为 0。

证据与脚本：`docs/handoff/intertrip_charging_fix_narrowing_20260804/`。
