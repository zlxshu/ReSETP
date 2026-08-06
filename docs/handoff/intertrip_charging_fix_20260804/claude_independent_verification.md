# T10 监工独立复核（Claude，2026-08-04 晚）

状态：`FIX_WORKS_BUT_OVERBROAD__BLOCKS_EN_ROUTE_PUBLIC_CHARGING__NARROWING_REQUIRED`

所有复核数字由 Claude 从 `solution_witnesses.json`、`slot_distribution.csv`、
`raw_runs.csv` 与源码重算，未采信转述。

---

## 一、修对的部分（复核确认）

`FACT` 用**独立实现的重叠判定器**（`build_multitrip_certificate` 重建行程 +
半开区间相交）复核 T10 的 18 个解：**重叠 0 处**。
`FACT` 12:00—15:00 充电电量合计 **0.000000 kWh**（18 次全归零）。
`FACT` 服务量红线 18/18 通过，无一不足 50/50 与 13264/13264。
`FACT` `cost.py`、`search/evaluation.py` 的 SHA-256 逐位未变；`check.py` 按批准事项变化。
`FACT` 三个已知阳性样本 3/3 被新检查器判为 `CHARGING_TRIP_OVERLAP`；
T9 判为无重叠的 20 个解 20/20 无误报。

**结论：缺陷本身确实修掉了。**

---

## 二、但新约束过宽：它把"车开到公共站去充电"也一并禁了

`FACT`（源码，`check.py::_check_charging_trip_overlap`）新增的检查对**每一个充电动作**生效，
不区分充电地点是车场还是路上的公共充电站。其 docstring 自述
"Reject depot/public charging that overlaps the same physical vehicle's trip"。

`FACT` 而公共站充电在本模型里**本来就发生在行程当中**——充电站是路线节点序列上的一个点。
`solver/tests/test_public_station_multitrip_20260723.py:117-127` 的构造即为
路线 `D0 → F1 → …`，充电动作 `charge_start_second = travel_to_station + 300`，
即车开到 `F1` 之后在途中充电；行程证书里另有专门字段 `in_route_charge_energy_kwh` 承载它。

**因此按新约束，任何在途公共站充电都必然与"该车在外行程区间"相交，一律判违反。**
这不是物理不可能——车就在那个站上——而是约束写宽了。

`FACT` 14 个测试失败中，**7 个由此产生**（此前均为通过状态）：

| 测试 | Codex 的标注 | 复核判定 |
|---|---|---|
| `test_public_station_multitrip_20260723::test_public_station_route_closes_strict_clock_soc_and_certificate` | "correctly rejects in-trip public charging overlap" | **判错**，该拒绝不正确 |
| `test_public_station_multitrip_20260723::test_public_station_route_passes_mandatory_strict_runtime` | 同上 | **判错** |
| `test_refined_carbon_charging::test_integrated_route_repair_inserts_station_and_remains_fully_feasible` | "correctly rejects" | **判错** |
| `test_refined_carbon_charging::test_refined_reset_and_reconstruction_consumes_one_candidate_evaluation` | 同上 | **判错** |
| `test_search::test_h2_initial_solution_contains_deterministic_ev_charging_witness` | "removes the old in-trip charging witness" | **判错** |
| `test_search::test_h3_short_alns_has_nonzero_charging_signal` | 同上 | **判错** |
| `test_search::test_m0_evheavy_initial_solution_respects_fleet_limits_and_charges` | 同上 | **判错** |

`FACT` T7 收工时 `test_refined_carbon_charging.py` 为 `7 passed`；现其中 2 个失败，
证明这 7 个是本次新破的，不是既有失败。

`FACT` 另 6 个失败为既有失败（`test_e2_80k_robustness_gate`、`test_e5_ablation` ×2、
`test_ev_heavy_findability_gate`、`test_paper_evidence_boundaries`、
`test_strong_bridge_backend_alignment`），与本次修复无关。

### 这条为什么重要

用户 2026-08-04 晚**刚刚批准"允许电动车在客户点附近的公共充电站补电"**。
按当前实现，求解器**永远不可能**再产出任何在途公共站充电的解——
不是因为不划算，是因为检查器会判违反。这与用户批准的方向直接相反。

`FACT` 本次 18 次重跑的公共站充电动作数为 **0**，所以**这 18 个数字本身不受影响**，
可以当作"只在车场充电"这一情景下的有效结果使用。受影响的是**今后的所有搜索**。

---

## 三、还有一处语义变化，未被列为问题

`FACT` `test_china81_shared_completion_20260720` 的失败原因是：
修复后的生成器把首趟行前充电写成 `charge_day_offset = -1`（前一日），
而旧测试要求 `charge_day_offset = 0`。

`INFERENCE`（未逐行定位）：首趟行前充电被移到前一天，意味着它所对应的碳强度与电价
取自**前一日的时段表**，而不是当日。这在跨日碳强度差异较大时会改变充电排放的核算结果。
本次 18 次运行是否已受此影响，未查。**这属于核算口径变化，须查清后再决定是否保留。**

---

## 四、待处置（不由代理自选）

1. **把约束收窄**：只对"车场充电"施加"不得与在外行程相交"，
   在途公共站充电由路线时刻本身（到站、充电占用、离站）保证一致性，不受该约束管辖。
   收窄后上述 7 个测试应恢复通过；若仍不过，说明另有问题，不得靠改测试凑过。
2. **查清首趟充电 `charge_day_offset = -1`** 是否为有意设计，以及它对碳排核算的影响范围。
3. 本次 18 个数字可作为"仅车场充电"情景的有效结果保留，`paper_claim_allowed` 维持 `false`。
