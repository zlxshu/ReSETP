COSTFIX_DONE

# 车型固定成本、利润／公平成本口径修复报告（2026-08-12）

## 一、结论与范围

`USER DECISION`：用户 2026-08-12 当次明确授权，只允许修改受保护文件 `solver/src/setp_solver/cost.py` 中车辆固定成本计算的那一处，并将口径定为燃油车 170 元/实体车·日、电动车 220 元/实体车·日；同时指定修复单位审计第 1、2、4、5 条。

`FACT`：J1—J4 已完成。当前活动链为：

- 车型固定成本由 `data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv:1-3` 读取，进入车型档案；精确总账、车场利润账、Problem-HGS 路线代理和 Duty-HGS 路线代理共用同一车型取值。
- CV 仍为 170 元/实体车·日，EV 为 220 元/实体车·日；多趟仍只按物理车计一次。
- 旧私有重建／Problem-HGS 外层的 `50 × EV 数` 不再重复加进 `cost_fix` 或 `total_cost`；`cost_fix_ev_premium` 只保留为审计分解字段。
- 利润／公平链现在按车型扣固定成本、按路线起点车场城市取柴油价，并计入与精确总账定义相同的路线时间成本。
- 未运行正式实验，未修改算例几何、算法参数或其他评价口径，未覆盖任何旧产物。

## 二、四项修复逐条核账

| 项目 | 文件与当前行号 | 旧值／旧写法 | 新值／新写法 | 依据 |
|---|---|---|---|---|
| J1 精确总账按车型计固定成本 | `solver/src/setp_solver/cost.py:170-181` | `(n_veh_cv+n_veh_ev) × vehicle_fixed_cost`，两型均按兼容标量 170 | `n_cv × instance.vehicle_fixed_cost_per_day("cv") + n_ev × ...("ev")`，当前为 170/220 | P43-F 的 F1、P43-H NOTE；权威 CSV `vehicle_costs.csv:1-3` |
| J1 权威值接线 | `instance_loader.py:65,265-274,497-503`；`china81.py:114-116,470-472,617-623,669-705,869-929,1128-1176` | 车型档案没有日固定成本；China81 只有共同标量 170 | 车型档案新增可选日固定成本；China81 从 CSV 读取、校验、登记来源路径，兼容标量仅保留 CV=170 回退 | 同一权威 CSV；非 China81／历史实例没有车型档案时仍走旧共同标量回退 |
| J1 搜索代理一致 | `problem_hgs/kernel_proposals.py:821-839`；`duty_hgs/pyvrp_proposals.py:384-403` | 两型代理 fixed cost 都取共同标量 170 | 两条代理均按 Duty 车型读取同一 Instance 档案，CV=170、EV=220 | 单位审计第 5 条；代理须与完整评价同口径 |
| J1 防止重复计费 | `private_instance_rebuild_20260811.py:347-374`；`problem_hgs/evaluation.py:833-873` | 完整 `evaluate()` 后再把 `50 × n_ev` 加进 `cost_fix/total_cost` | 不再外加；只从档案差值生成审计字段，并校验配置溢价与档案一致 | J1 已把 220 下沉到共享精确总账；继续外加会双算 |
| J2 EV 溢价进入利润／公平账 | `profit.py:95-118` | 每辆物理车统一扣共同固定费 170 | 按 `(vehicle_type, physical_vehicle_id)` 去重后，CV 扣 170、EV 扣 220，并归属其 `home_depot` | 单位审计第 1 条；与 `cost.py:164-181` 同一实体车口径 |
| J3 柴油价按路线起点城市 | `profit.py:127-132` | 每条 CV 路线乘算例城市均价 `prices.diesel_price` | 直接复用精确总账的 `diesel_price_for_route(route, instance, prices)` | 单位审计第 2 条；用户指定以精确总成本链为准 |
| J4 路线时间成本进入利润／公平账 | `profit.py:29-49,171-188,211-258` | 利润分解没有 `cost_time`，利润不扣路线时间成本 | 新增 `cost_time`；逐路线复用精确总账 `_e5_route_time_seconds`，按 `home_depot` 分摊并进入 `cost_total/profit` | 单位审计第 4 条；行驶时间＋公共站途中充电占用，车场充电占用不计 |
| J1 来源路径在派生套件中保留 | `run_problem_hgs_private_technical.py:835-854`；`build_china81_metro_suite_20260812.py:1790-1809` | PRDFIX/METRO 整体替换 `source_paths`，会丢失上游固定成本权威路径 | 合并模板来源后再覆盖派生套件路径 | 保证取值不仅数值来自权威档案，落盘来源身份也可追溯 |

`FACT`：CSV 当前两行分别为 CV `170.00+0.00=170.00`、EV `170.00+50.00=220.00`；EV 行来源栏登记 `Chen et al. 2023 Table 7`。中国化审计 `china_localization_repo_audit_20260812.md:94` 已将该 50 元判为可保留的中国文献情景；本轮按用户最新决定采用，不把它改写成企业实测成本。

## 三、受保护 `cost.py` 的完整 diff

以下是任务开始快照到当前文件的完整 diff；没有隐藏上下文、第二处改动或格式化改动：

```diff
diff --git a/solver/src/setp_solver/cost.py b/solver/src/setp_solver/cost.py
index 4f5a3fe9..6a07e0ac 100644
--- a/solver/src/setp_solver/cost.py
+++ b/solver/src/setp_solver/cost.py
@@ -167,7 +167,18 @@ def evaluate(
 
     # MC-W1-F2-DEPOT-CONCURRENCY-01: the fixed acquisition/activation charge
     # applies once per used physical vehicle, not once per delivery trip.
-    cost_fix = (n_veh_cv + n_veh_ev) * _price(prices, "vehicle_fixed_cost")
+    cost_fix = (
+        n_veh_cv
+        * instance.vehicle_fixed_cost_per_day(
+            "cv",
+            fallback=_price(prices, "vehicle_fixed_cost"),
+        )
+        + n_veh_ev
+        * instance.vehicle_fixed_cost_per_day(
+            "ev",
+            fallback=_price(prices, "vehicle_fixed_cost"),
+        )
+    )
     cost_km = sum(
         item.distance_m
         / 1000.0
```

## 四、必须证明的数值事实

### 4.1 J1：纯燃油逐位不变；含电车差额恰为 `50 × EV 数`

复算方法：同一当前 Instance、价格、碳档案和同一保存 `prepared_solution`，分别动态加载任务开始时备份的旧 `cost.py` 与当前 `cost.py`；不使用保存 JSON 顶层旧时代总成本拼接。

| 固定解 | 来源 | 物理车 | 旧 `cost_fix` | 新 `cost_fix` | 旧总成本 | 新总成本 | 浮点十六进制（旧→新） | 差额 |
|---|---|---:|---:|---:|---:|---:|---|---:|
| 纯 CV | `solver/reports/combat_v2_20260812/closure_type_exchange_final/best_solution.json` | 8 CV / 0 EV | 1360.0 | 1360.0 | 3315.241658757535 | 3315.241658757535 | `0x1.9e67bbab258cfp+11` → 同值 | 0.0 |
| 混合车队 | `solver/reports/combat_v2_20260812/combat_v2_5cycles_final/best_solution.json` | 3 CV / 5 EV | 1360.0 | 1610.0 | 2647.9202579809003 | 2897.9202579809003 | `0x1.4afd72c0dd7b3p+11` → `0x1.6a3d72c0dd7b3p+11` | **250.0 = 50 × 5** |

`FACT`：纯 CV 总成本的 Python `float.hex()` 也完全相同，不只是显示小数相同。混合解经 `evaluate_rebuild_solution()` 重放仍为 2897.9202579809003，审计字段为 250.0，证明外层没有再加一次。

`FACT`：上述“旧总成本”是旧共享评价器本身的同条件重放。历史 V3 包当时在外层已经补过 250 元，因此保存的该固定 incumbent 总成本不会因 J1 再增加 250；失效的是旧搜索代理产生 incumbent 的过程证据，而不是把同一固定解再改一次账。

### 4.2 J2：EV 溢价进入车场利润和参与公平派生值

同一混合固定解、同一当前价格档案、路线时间费率 0，分别加载旧／新 `profit.py`：

| 车场 | EV 实体车 | 旧固定费 | 新固定费 | 旧利润 | 新利润 | 利润差 |
|---|---:|---:|---:|---:|---:|---:|
| 佛山 | 2 | 340.0 | 440.0 | 3739.81336853826 | 3639.81336853826 | **-100.0 = -50 × 2** |
| 广州 | 3 | 1020.0 | 1170.0 | 11946.76637348084 | 11796.76637348084 | **-150.0 = -50 × 3** |

公平传播的受控派生检查（`theta=1`，Pi0 固定为新旧利润中点）：

| 车场 | 固定 Pi0 | 旧 margin／判定 | 新 margin／判定 |
|---|---:|---:|---:|
| 佛山 | 3689.81336853826 | +50.0／通过 | -50.0／不通过 |
| 广州 | 11871.76637348084 | +75.0／通过 | -75.0／不通过 |

`FACT`：保存包本身 `fairness_enabled=false`，所以这里的通过／不通过是固定阈值的因果测试，不冒充该历史包的正式公平结果。按该包保存时代原值直接修正，单位审计记录的 margin 应由佛山 3739.81336853826、广州 11946.654583145597 分别变为 3639.81336853826、11796.654583145597。

### 4.3 J3：利润账与精确总账按同一路线起点城市柴油价

受控双城 fixture：两个 CV 车场路线油耗相同；旧利润账使用错误的共同均价 8 元/L，新账分别使用路线起点城市 Alpha=7、Beta=9 元/L。Pi0 固定为每个车场新旧利润的中点：

| 车场 | 旧燃油费 | 新燃油费 | 旧利润 | 新利润 | 利润差 | 固定 Pi0 | 旧 margin／判定 | 新 margin／判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D0 / Alpha | 2.924014329180543 | 2.558512538032975 | 97.07598567081946 | 97.44148746196703 | +0.3655017911475653 | 97.25873656639325 | -0.18275089557378976／不通过 | +0.18275089557377555／通过 |
| D1 / Beta | 2.924014329180543 | 3.289516120328111 | 97.07598567081946 | 96.71048387967188 | -0.3655017911475795 | 96.89323477524567 | +0.18275089557378976／通过 | -0.18275089557378976／不通过 |

`FACT`：每个车场的新燃油费均与该单路线的 `cost.evaluate()` 相等，两个车场燃油费之和与完整精确总账相等。

历史成渝保存解的单位审计复核：总油耗 58.22000612111442 L、精确燃油费 436.3400808677855 元，对应成都约 15.4982520286 L、重庆约 42.7217540925 L；在已经先应用 J2 的条件下，J3 使成都利润增加 0.154982520286、重庆利润减少 0.427217540924。该包的 Pi0 也是旧错误函数生成，缺少 Pi0 分场油耗，故真实新 margin 与公平结论必须连同 Pi0 重算；本轮没有把“固定旧 Pi0 的诊断值”冒充正式结果。

### 4.4 J4：路线时间成本进入利润和公平约束

受控多趟 EV fixture 包含：1 小时路线行驶、30 分钟公共站 `f` 占用、60 分钟车场 `d` 占用。精确定义只计前两项，因此时间为 1.5 小时；费率 75 元/小时：

| 派生值 | 旧账（费率字段存在但利润漏记） | 新账 |
|---|---:|---:|
| `cost_time` | 0.0 | **112.5** |
| 利润 | 100.0 | **-12.5** |
| 固定 Pi0=100 的 margin | 0.0 | **-112.5** |

`FACT`：新利润分解的 `cost_time=112.5` 与精确总账逐位一致；第二趟和车场充电动作没有让公共站占用重复计费。

任务开始快照的旧 `profit.py` 与当前 `profit.py` 还用同一非零费率直接重放了另一固定 fixture：旧利润 46.0，新利润 42.66666666666667，新 `cost_time=3.3333333333333335`，利润差为 `-3.3333333333333286`（仅浮点减法末位差）。这排除了把“费率 0→75”的参数变化误当成 J4 代码变化。

实际公平入口回归：同一解只把费率从 0 改为 75，Pi0=40、`theta=1` 时，利润由 41.0（margin=+1，通过）变为 37.66666666666667（margin=-2.33333333333333，不通过），搜索目标由原始成本变为 `原始成本 + BIG_M`，并保存 1 条公平违规。

## 五、三个受保护文件 SHA-256

| 文件 | 任务开始 | 任务结束 | 结论 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | `ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | 必然改变；完整 diff 见第三节，只有获批固定成本 statement |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | SHA 相同且与任务开始备份逐字节 `cmp` 相同 |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | SHA 相同且与任务开始备份逐字节 `cmp` 相同 |

## 六、测试与零搜索验证

最终不重复计数的本轮相关测试为 **84 passed**：

- Python 3.14：成本、利润、公平传播、E5 时间成本、China81 权威接线、profiled 路网、非线性成本、动态多趟、Problem-HGS 与 Duty-HGS 路线代理，共 **71 passed**。
- Python 3.14：formal runner 中与成本／利润／碳账相关的 3 个定向用例，共 **3 passed**。
- Python 3.13（匹配仓库 `setp_hgs_kernel.cpython-313-darwin.so`）：私有重建完整／增量评价及 50 元审计字段，共 **4 passed**。
- Python 3.14 隔离依赖环境：中国价格／柴油排放因子门，共 **6 passed**。
- PRDFIX 与 METRO 各做一个零搜索加载探针：两者都保存 `vehicle_cost_authority` 路径，运行时分别读到 CV=170、EV=220。
- 修改的生产模块与两个派生适配器均通过 `py_compile`；相关 diff 通过 `git diff --check`。

新增的漂移敏感测试：

1. 直接读取权威 CSV，锁定 CV=170、EV=220、溢价=50 和陈婉茹 2023 来源；任一值漂移即失败（`test_china81_bundle_20260720.py:65-81`）。
2. monkeypatch 权威 loader 为 171/223，断言 Instance 档案和兼容价格随之改变，防止未来把 170/220 偷换成代码字面量（`:84-106`）。
3. 精确总账锁定 CV+EV=390、同一 EV 多趟只收 220，并故意把共同 fallback 改为 999 证明没有偷走回退值（`:109-150`）。
4. 两条搜索代理分别锁定 CV=170、EV=220（`test_problem_hgs_route_proxy.py:174-187`；`test_duty_hgs_route_proxy.py:136-145`）。
5. 私有／Problem-HGS 包装器锁定“审计溢价=50，但总成本不再双算”（`test_china81_bundle_20260720.py:393-420`；`test_problem_hgs_route_proxy.py:190-236`）。
6. 利润账分别锁定车型固定费、城市柴油价、公共站时间定义、精确总账闭合和公平 pass/fail 翻转（`test_profit.py:114-266,356-406`）。
7. 同一非零时间费率直接加载任务开始快照的旧 `profit.py` 与当前实现对照，锁定旧利润与新利润的差恰为新账 `cost_time`（`test_profit.py:268-304`）。

`FACT`：最初用系统 Python 3.14 收集私有适配器测试时，3.13 编译扩展不可导入；已切换到仓库匹配的 Python 3.13 并补齐隔离测试依赖，最终 4/4 通过。中国价格门最初缺 `bs4`，在隔离依赖环境补齐后 6/6 通过。一次误触整份 `test_formal_runner.py` 的宽测试已及时终止且不计入通过数，随后只运行上述 3 个相关用例。最终复核还如实保留三类命令入口错误：主测试第一次漏设 `PYTHONPATH=src`；私有适配器先复用了 3.14 环境、隔离环境又依次缺 `numpy/vrplib`；价格门第一次未把仓库根加入 `PYTHONPATH`。这些尝试均停在收集阶段；修正后对应命令分别为 **71/71、4/4、6/6**，formal runner 定向组为 **3/3**。终止后没有残留 pytest 进程。以上均是测试，不是求解实验。

## 七、作废产物与仍可保留的部分

### 7.1 判定口径

`FACT`：本轮没有删除或覆盖旧产物。以下“作废”表示不能再当作当前成本模型的搜索、利润或公平证据；原文件仍保留为历史审计材料。

- 对 J1：旧代理把 EV 固定费看成 170，所以凡是允许 EV 的旧搜索，其候选排序、轨迹、算子统计和所达 incumbent 都不是当前 220 口径的搜索证据；即使最后解全 CV，也不能证明搜索过程不受影响。
- 对同一已保存固定解：56 个 V3 包原已由外层补过 `50 × n_ev`，所以仅由 J1 而言，其精确 `cost_fix/total_cost` 数值不需要再加一次；失效的是“它由当前搜索口径找到”的身份。
- 对 J2：含 EV 的旧车场利润、Pi0、participation margin 和 fairness 判定作废；精确系统总成本不因 J2 再变。
- 对 J3：多城市旧 depot profit、Pi0、margin、fairness 作废；精确 `cost_fuel/total_cost` 原本已按路线城市计价，不因 J3 改变。
- 对 J4：当前生产费率为 0，仓库未检出非零费率保存包，因此本轮没有仅由 J4 数值性作废的保存结果。

### 7.2 本轮后不能继续作为当前搜索证据的 56 个 V3 运行目录

这些目录均保存 `cost_fix_ev_premium`，搜索空间允许 EV；其 `best_solution` 的 incumbent 身份、`raw_runs.csv`、由搜索结论生成的 `decision.json/report.md` 以及其中 36 份 `trajectory.jsonl` 作废。`metadata.json` 与 `artifact_hashes.json` 继续保留为历史身份和完整性凭据。

```text
solver/reports/charge_window_fix_20260811/baseline_after_off
solver/reports/charge_window_fix_20260811/baseline_before_valid
solver/reports/charge_window_fix_20260811/baseline_prevnight_off_session
solver/reports/charge_window_fix_20260811/gate0_on
solver/reports/charge_window_fix_20260811/gate0_prevnight_on_session
solver/reports/charge_window_fix_20260811/gate0_v2_off
solver/reports/charge_window_fix_20260811/gate0_v2_on
solver/reports/charge_window_fix_20260811/gate1_round3_seed11_off_120s
solver/reports/charge_window_fix_20260811/gate1_round3_seed11_on_120s
solver/reports/charge_window_fix_20260811/gate1_seed11_off_120s
solver/reports/charge_window_fix_20260811/gate1_seed11_on_120s
solver/reports/charging_rejection_diagnosis_20260812/step1_equivalence_after_1cycle
solver/reports/charging_rejection_diagnosis_20260812/step1_instrumented_20cycles
solver/reports/charging_rejection_diagnosis_20260812/step1_reason_text_1cycle
solver/reports/charging_rejection_diagnosis_20260812/step2_capture_2cycles
solver/reports/charging_rejection_diagnosis_20260812/step2_capture_hook_default_off_1cycle
solver/reports/charging_rejection_diagnosis_20260812/step4_prescreen_off_1cycle
solver/reports/combat_prescreen_speedup_20260812/combat_5cycles_trajectory_off
solver/reports/combat_prescreen_speedup_20260812/equivalence_after_3cycles_audit2000
solver/reports/combat_prescreen_speedup_20260812/equivalence_before_3cycles
solver/reports/combat_prescreen_speedup_20260812/smoke_1cycle
solver/reports/combat_readiness_20260812/combat_5cycles
solver/reports/combat_readiness_20260812/default_off_hash
solver/reports/combat_v2_20260812/closure_charge_timing_1cycle
solver/reports/combat_v2_20260812/closure_charge_timing_final
solver/reports/combat_v2_20260812/closure_cross_depot_1cycle
solver/reports/combat_v2_20260812/closure_cross_depot_final
solver/reports/combat_v2_20260812/closure_multi_trip_1cycle
solver/reports/combat_v2_20260812/closure_multi_trip_final
solver/reports/combat_v2_20260812/closure_type_exchange_1cycle
solver/reports/combat_v2_20260812/closure_type_exchange_final
solver/reports/combat_v2_20260812/combat_v2_5cycles
solver/reports/combat_v2_20260812/combat_v2_5cycles_final
solver/reports/combat_v2_20260812/default_after_3cycles
solver/reports/combat_v2_20260812/default_after_omitted_3cycles
solver/reports/combat_v2_20260812/default_before_3cycles
solver/reports/combat_v2_20260812/smoke_combat_1cycle
solver/reports/convergence_calibration_20260812/probe5_seed1_1cycle
solver/reports/depot_power_60kw_20260811/minimal_run_endogenous
solver/reports/duty_operators_build_20260811/off_after
solver/reports/duty_operators_build_20260811/off_baseline_before
solver/reports/duty_operators_build_20260811/on_shortest
solver/reports/dynamic_insertion_operator_20260812/off_after_private
solver/reports/dynamic_insertion_operator_20260812/off_baseline_private_before
solver/reports/dynamic_insertion_operator_20260812/on_shortest_private
solver/reports/fingerprint_cache_20260811/after
solver/reports/fingerprint_cache_20260811/before
solver/reports/frvcpy_integration_20260811/off_after
solver/reports/frvcpy_integration_20260811/off_baseline_before
solver/reports/frvcpy_integration_20260811/on_shortest
solver/reports/metro_rebuild_20260812/cn-cy-50c-01_1cycle_probe
solver/reports/real_population_calibration_20260812/regression_after_technical
solver/reports/real_population_calibration_20260812/regression_before_technical
solver/reports/real_population_calibration_20260812/speed_probe_20cycles
solver/reports/station_restore_20260812/after_20cycles
solver/reports/station_restore_20260812/before_20cycles_current_code
```

另外逐条登记以下没有进入上面 56 个 `best_solution.json` 选择器、但同样使用旧代理的保存搜索／汇总产物：

- `solver/reports/convergence_calibration_20260812/probe_seed1_1cycle`
- `solver/reports/convergence_calibration_20260812/probe2_seed1_1cycle`
- `solver/reports/search_budget_diagnosis_20260811`
- `solver/reports/mechanism_validation_v3_20260811/preflight_seed11`
- `solver/reports/mechanism_validation_v3_20260811/factorial_2seed_30s`
- `solver/reports/mechanism_validation_v3_20260811/factorial_3seed_30s`
- `solver/reports/mechanism_validation_v3_20260811/seeds_extended_raw.csv`
- `solver/reports/mechanism_validation_v3_20260811/{raw_runs.csv,decision.json,report.md}`
- 上述 56 个运行目录的家族级汇总 `decision.json/report.md`，凡其结论由这些运行聚合而来者一并作废。

### 7.3 其中因 J2 直接使已保存利润／margin 数值作废的 15 个 V3 目录

```text
2 EV  solver/reports/charging_rejection_diagnosis_20260812/step1_instrumented_20cycles
6 EV  solver/reports/combat_prescreen_speedup_20260812/combat_5cycles_trajectory_off
6 EV  solver/reports/combat_prescreen_speedup_20260812/equivalence_after_3cycles_audit2000
6 EV  solver/reports/combat_prescreen_speedup_20260812/equivalence_before_3cycles
6 EV  solver/reports/combat_readiness_20260812/combat_5cycles
5 EV  solver/reports/combat_v2_20260812/closure_charge_timing_1cycle
5 EV  solver/reports/combat_v2_20260812/closure_charge_timing_final
6 EV  solver/reports/combat_v2_20260812/closure_cross_depot_1cycle
6 EV  solver/reports/combat_v2_20260812/closure_cross_depot_final
5 EV  solver/reports/combat_v2_20260812/combat_v2_5cycles
5 EV  solver/reports/combat_v2_20260812/combat_v2_5cycles_final
5 EV  solver/reports/combat_v2_20260812/smoke_combat_1cycle
2 EV  solver/reports/real_population_calibration_20260812/speed_probe_20cycles
2 EV  solver/reports/station_restore_20260812/after_20cycles
2 EV  solver/reports/station_restore_20260812/before_20cycles_current_code
```

这 15 个包都 `fairness_enabled=false`，所以没有保存的公平可行判定翻转；作废的是 depot profit／participation margin 数值。其余 41 个 V3 最终解全 CV，利润数值不因 J2 改变，但仍因 J1 旧 EV 代理而失去当前搜索证据身份。

### 7.4 因 J1 作废的 27 个无外层补费、无利润字段的旧 EV 目录

这些旧目录含 EV，但既没有 V3 的 `cost_fix_ev_premium` 外层补费，也没有 `participation_margin`。其中 16 个保存了成本分解：它们不仅失去旧代理的搜索证据身份，保存固定解的 `cost_fix/total_cost` 本身也要按 `50 × n_ev` 增加。下表“新值”只隔离施加本轮固定成本更正，不混入其他参数时代变化：

```text
2 EV  1190→1290  2316.97883865434→2416.97883865434  baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/dynamic_system_jjj50_v1_20260808
2 EV  1190→1290  2283.6863576513056→2383.6863576513056  solver/reports/duty_hgs_dynamic_technical/jjj50_seed11_iter10_v3_20260808
2 EV  1190→1290  2316.97883865434→2416.97883865434  solver/reports/duty_hgs_dynamic_technical/jjj50_seed11_iter1_20260808
2 EV  1190→1290  2316.97883865434→2416.97883865434  solver/reports/duty_hgs_dynamic_technical/jjj50_seed11_iter1_v2_20260808
2 EV  1190→1290  2316.97883865434→2416.97883865434  solver/reports/duty_hgs_dynamic_technical/jjj50_trigger43200_iter1_final_structure_v3_20260808
2 EV  1190→1290  2283.6863576513056→2383.6863576513056  solver/reports/duty_hgs_dynamic_technical/jjj50_trigger43200_iter2_final_structure_v3_20260808
2 EV  1190→1290  2283.6863576513056→2383.6863576513056  solver/reports/duty_hgs_dynamic_technical/jjj50_trigger43200_iter2_final_structure_v4_determinism_20260808
2 EV  1190→1290  2270.7549714085662→2370.7549714085662  solver/reports/duty_hgs_dynamic_three_region_probe_20260809/cy_system_iter5_seed11
2 EV  1190→1290  2257.55526974779→2357.55526974779  solver/reports/duty_hgs_dynamic_three_region_probe_20260809/jjj_system_iter5_seed11
1 EV  850→900    1868.072748818845→1918.072748818845    solver/reports/duty_hgs_dynamic_three_region_probe_20260809/prd_system_iter5_seed11
1 EV  340→390    561.1475064958792→611.1475064958792     solver/reports/problem_hgs_dynamic_independence_probe_v2_20260809
2 EV  1190→1290  2152.7132491168227→2252.7132491168227  solver/reports/problem_hgs_dynamic_jjj50_copied_hgs_route_elite_20260809
2 EV  1190→1290  2316.97883865434→2416.97883865434    solver/reports/problem_hgs_dynamic_public_station_chain_smoke_jjj_20260809
2 EV  1190→1290  2316.97883865434→2416.97883865434    solver/reports/problem_hgs_dynamic_public_station_chain_smoke_jjj_v2_20260809
2 EV  1190→1290  2283.6863576513056→2383.6863576513056  solver/reports/problem_hgs_dynamic_public_station_chain_smoke_jjj_v3_20260809
2 EV  1190→1290  2237.804972603461→2337.804972603461    solver/reports/problem_hgs_serial_dynamic_jjj50_smoke_v2_20260810
```

另 11 个 G1 micro-work `best_solution.json` 只保存路线／充电动作，没有成本分解；其旧搜索身份作废，若重算该固定解，仍应按其中 1 或 2 辆 EV 分别增加 50 或 100 元固定成本：

```text
2 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v5_decoder_repair/tasks/G1__cn-cy-150c-03-V2-LOCATIONS__seed1__B_RR
2 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v5_decoder_repair/tasks/G1__cn-jjj-25c-02-V2-LOCATIONS__seed1__AB_COOP_HGS_RR
1 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v5_decoder_repair/tasks/G1__cn-jjj-25c-02-V2-LOCATIONS__seed1__B_RR
1 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v5_decoder_repair/tasks/G1__cn-prd-100c-03-V2-LOCATIONS__seed1__B_RR
2 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v6_coverage_contract/tasks/G1__cn-cy-150c-03-V2-LOCATIONS__seed1__AB_COOP_HGS_RR
2 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v6_coverage_contract/tasks/G1__cn-cy-150c-03-V2-LOCATIONS__seed1__A_HGS
2 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v6_coverage_contract/tasks/G1__cn-cy-150c-03-V2-LOCATIONS__seed1__B_RR
2 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v6_coverage_contract/tasks/G1__cn-jjj-25c-02-V2-LOCATIONS__seed1__AB_COOP_HGS_RR
2 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v6_coverage_contract/tasks/G1__cn-jjj-25c-02-V2-LOCATIONS__seed1__A_HGS
1 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v6_coverage_contract/tasks/G1__cn-jjj-25c-02-V2-LOCATIONS__seed1__B_RR
1 EV  baselines/algorithm_prototypes/genuine_hgs_rr_20260724/g1_micro_work_v6_coverage_contract/tasks/G1__cn-prd-100c-03-V2-LOCATIONS__seed1__B_RR
```

### 7.5 因 J1/J2 作废旧 EV 成本、利润／margin 的 149 个 V2 目录（并标出 J3 子集）

下列选择器要求 `best_solution.json` 同时保存 `participation_margin`、`n_veh_ev>0` 且没有 V3 外层 `cost_fix_ev_premium`；得到 **CY 44 + JJJ 53 + PRD 52 = 149**。它们的保存 `cost_fix/total_cost` 先因 J1 增加 `50 × n_ev`，旧 depot profit／margin 再因 J2 作废。所有 CY/JJJ 行共 **97** 个，还是 J3 的多城市 diesel/Pi0/margin 作废子集；PRD 52 只受 J1/J2，不受 J3（广州、佛山同为 7.44 元/L）。

```text
CY  solver/reports/duty_hgs_private_three_region_probe_20260809/cy_system_iter5_seed11
PRD solver/reports/duty_hgs_private_three_region_probe_20260809/prd_mechanism_only_iter5_seed11
PRD solver/reports/duty_hgs_private_three_region_probe_20260809/prd_route_only_iter5_seed11
PRD solver/reports/duty_hgs_private_three_region_probe_20260809/prd_system_iter5_seed11
JJJ solver/reports/duty_hgs_private_three_region_probe_20260809/jjj_mechanism_only_iter5_seed11
JJJ solver/reports/duty_hgs_private_three_region_probe_20260809/jjj_route_only_iter5_seed11
JJJ solver/reports/duty_hgs_private_three_region_probe_20260809/jjj_system_iter5_seed11
CY  solver/reports/duty_hgs_private_three_region_probe_20260809/cy_mechanism_only_iter5_seed11
CY  solver/reports/duty_hgs_private_three_region_probe_20260809/cy_route_only_iter5_seed11
PRD solver/reports/harness_inertia_fix_20260811/old_path_120s_reference
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search11_readiness_observedmax_converged_v4_inituntilfeasible_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search11_readiness_none_converged_v4_inituntilfeasible_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search1_readiness_observedmax_converged_v2_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search11_readiness_observedmax_converged_v2_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search1_readiness_none_converged_v2_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search2_readiness_none_converged_v3_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search2_readiness_observedmax_converged_v3_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search1_readiness_observedmax_converged_v1_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search11_readiness_none_converged_v1_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_stream2_search11_readiness_observedmax_converged_v1_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_seed2_readiness_observedmax_v5_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_seed2_readiness_none_v2_20260809
CY  solver/reports/problem_hgs_dynamic_cy50_seed2_readiness_none_v1_20260809
JJJ solver/reports/problem_hgs_dynamic_jjj50_seed2_readiness_none_v1_20260809
CY  solver/reports/problem_hgs_dynamic_cy50_seed2_readiness_observedmax_v2_20260809
JJJ solver/reports/problem_hgs_dynamic_jjj50_seed2_readiness_observedmax_v2_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_seed2_readiness_observedmax_v4_20260809
JJJ solver/reports/problem_hgs_dynamic_jjj50_warm_exact_seed2_perorder_populationfix_v8_20260809
CY  solver/reports/problem_hgs_dynamic_cy50_warm_exact_seed2_perorder_populationfix_v7_20260809
PRD solver/reports/problem_hgs_private_prd50_route_then_final_mechanism_v1_20260809
PRD solver/reports/problem_hgs_private_prd50_route_elite_populationfix_pair_v7_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_then_final_mechanism_v1_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_elite_populationfix_pair_v7_20260809
CY  solver/reports/problem_hgs_private_cy50_route_elite_populationfix_pair_v7_20260809
CY  solver/reports/problem_hgs_private_cy50_route_then_final_mechanism_v1_20260809
JJJ solver/reports/problem_hgs_dynamic_jjj50_warm_exact_seed2_perorder_v6_20260809
CY  solver/reports/problem_hgs_dynamic_cy50_mechanical_seed2_perorder_v6_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_warm_exact_seed2_perorder_v6_20260809
CY  solver/reports/problem_hgs_dynamic_cy50_warm_exact_seed2_perorder_v6_20260809
CY  solver/reports/problem_hgs_dynamic_cy50_mechanical_fixed30_v3_20260809
JJJ solver/reports/problem_hgs_dynamic_jjj50_mechanical_perorder_v3_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_mechanical_fixed30_v3_20260809
JJJ solver/reports/problem_hgs_dynamic_jjj50_warm_exact_perorder_stage5_v3_20260809
CY  solver/reports/problem_hgs_dynamic_cy50_warm_exact_stage5_v3_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_warm_exact_stage5_v3_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_warm_insert_randomfill_stage5_v2_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_warm_insert_stage5_v1_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_frozen_initial_stage30_v1_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_frozen_initial_stage5_v1_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_disclosure_noleak_route_elite_v1_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_disclosure_noleak_probe_v2_20260809
PRD solver/reports/problem_hgs_dynamic_prd50_disclosure_probe_v2_20260809
CY  solver/reports/problem_hgs_private_cy50_copied_bpd_route_elite_v6_20260809
PRD solver/reports/problem_hgs_private_prd50_copied_bpd_route_elite_v6_20260809
JJJ solver/reports/problem_hgs_private_jjj50_copied_bpd_route_elite_v6_20260809
JJJ solver/reports/problem_hgs_private_jjj50_hgs_semantics_route_elite_v5_20260809
CY  solver/reports/problem_hgs_private_cy50_hgs_semantics_route_elite_v5_20260809
PRD solver/reports/problem_hgs_private_prd50_hgs_semantics_route_elite_v5_20260809
PRD solver/reports/problem_hgs_private_prd50_copied_population_route_elite_v4_20260809
JJJ solver/reports/problem_hgs_private_jjj50_copied_population_route_elite_v4_20260809
CY  solver/reports/problem_hgs_private_cy50_copied_population_route_elite_v4_20260809
CY  solver/reports/problem_hgs_private_cy50_route_elite_feedback_convergence_v3_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_elite_feedback_convergence_v3_20260809
PRD solver/reports/problem_hgs_private_prd50_route_elite_feedback_convergence_v3_20260809
PRD solver/reports/problem_hgs_private_prd50_route_elite_convergence_v2_20260809
CY  solver/reports/problem_hgs_private_cy50_route_elite_convergence_v2_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_elite_convergence_v2_20260809
PRD solver/reports/problem_hgs_private_prd50_route_only_convergence_v2_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_only_convergence_v2_20260809
CY  solver/reports/problem_hgs_private_cy50_route_only_convergence_v2_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_only_convergence_v1_20260809
CY  solver/reports/problem_hgs_private_cy50_route_only_convergence_v1_20260809
PRD solver/reports/problem_hgs_private_prd50_route_only_convergence_v1_20260809
PRD solver/reports/problem_hgs_private_prd50_system_attribution_v1_20260809
JJJ solver/reports/problem_hgs_private_jjj50_system_attribution_v1_20260809
CY  solver/reports/problem_hgs_private_cy50_system_attribution_v1_20260809
PRD solver/reports/problem_hgs_private_prd50_route_elite_attribution_v1_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_elite_attribution_v1_20260809
CY  solver/reports/problem_hgs_private_cy50_route_elite_attribution_v1_20260809
CY  solver/reports/problem_hgs_private_cy50_route_only_attribution_v1_20260809
PRD solver/reports/problem_hgs_private_prd50_route_only_attribution_v1_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_only_attribution_v1_20260809
PRD solver/reports/problem_hgs_private_prd50_system50_incumbent_isolated_v4_20260809
JJJ solver/reports/problem_hgs_private_jjj50_system50_incumbent_isolated_v4_20260809
CY  solver/reports/problem_hgs_private_cy50_system50_incumbent_isolated_v4_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route50_incumbent_v4_20260809
PRD solver/reports/problem_hgs_private_prd50_route50_incumbent_v4_20260809
CY  solver/reports/problem_hgs_private_cy50_route50_incumbent_v4_20260809
PRD solver/reports/problem_hgs_private_prd50_system50_incumbent_v4_20260809
JJJ solver/reports/problem_hgs_private_jjj50_system50_incumbent_v4_20260809
CY  solver/reports/problem_hgs_private_cy50_system50_incumbent_v4_20260809
CY  solver/reports/problem_hgs_private_cy50_route50_staged_restart_20260809
PRD solver/reports/problem_hgs_private_prd50_system50_staged_restart_20260809
PRD solver/reports/problem_hgs_private_prd50_route50_staged_restart_20260809
JJJ solver/reports/problem_hgs_private_jjj50_system50_staged_restart_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route50_staged_restart_20260809
CY  solver/reports/problem_hgs_private_cy50_system50_staged_restart_20260809
CY  solver/reports/problem_hgs_private_cy50_system50_staged_20260809
CY  solver/reports/problem_hgs_private_cy50_system50_lean_20260809
CY  solver/reports/problem_hgs_private_cy50_system20_open_trip_20260809
CY  solver/reports/problem_hgs_private_cy50_system100_180s_fairness_20260809
CY  solver/reports/problem_hgs_private_cy50_system5_fairnessvectors_20260809
CY  solver/reports/problem_hgs_private_cy50_system5_fairnessmoves_20260809
CY  solver/reports/problem_hgs_private_cy50_system5_attributionfix_20260809
CY  solver/reports/problem_hgs_private_cy50_route_only5_attributionfix_20260809
CY  solver/reports/problem_hgs_private_cy50_system5_floatfix_repeat_20260809
CY  solver/reports/problem_hgs_private_cy50_route_only5_floatfix_repeat_20260809
PRD solver/reports/problem_hgs_private_prd50_mechanism_only5_floatfix_20260809
CY  solver/reports/problem_hgs_private_cy50_mechanism_only5_floatfix_20260809
CY  solver/reports/problem_hgs_private_cy50_route_only5_floatfix_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_only5_floatfix_20260809
PRD solver/reports/problem_hgs_private_prd50_route_only5_floatfix_20260809
JJJ solver/reports/problem_hgs_private_jjj50_system5_floatfix_20260809
CY  solver/reports/problem_hgs_private_cy50_system5_floatfix_20260809
PRD solver/reports/problem_hgs_private_prd50_system5_floatfix_20260809
JJJ solver/reports/problem_hgs_private_jjj50_mechanism_only5_floatfix_20260809
CY  solver/reports/problem_hgs_private_cy50_mechanism_only5_20260809
PRD solver/reports/problem_hgs_private_prd50_mechanism_only5_20260809
JJJ solver/reports/problem_hgs_private_jjj50_route_only5_20260809
CY  solver/reports/problem_hgs_private_cy50_route_only5_20260809
PRD solver/reports/problem_hgs_private_prd50_route_only5_20260809
JJJ solver/reports/problem_hgs_private_jjj50_system5_20260809
PRD solver/reports/problem_hgs_private_prd50_system5_20260809
CY  solver/reports/problem_hgs_private_cy50_system5_20260809
JJJ solver/reports/problem_hgs_private_independence_probe_v2_20260809
JJJ solver/reports/problem_hgs_private_independence_probe_20260809
JJJ solver/reports/duty_hgs_private_technical/jjj50_seed11_iter2_final_structure_v4_determinism_20260808
JJJ solver/reports/duty_hgs_private_technical/jjj50_seed11_iter2_final_structure_v3_20260808
JJJ solver/reports/duty_hgs_private_technical/jjj50_seed11_iter1_final_structure_v3_20260808
JJJ solver/reports/duty_hgs_private_technical/jjj10_seed11_iter2_fast_fallback_v3_20260808
JJJ solver/reports/duty_hgs_private_technical/jjj10_seed11_iter2_trip_assignment_v2_20260808
PRD solver/reports/oldpath_check
JJJ solver/reports/duty_hgs_private_technical/jjj50_seed11_iter10_system_v3_20260808
JJJ solver/reports/duty_hgs_private_technical/jjj50_seed11_iter1_system_v2_20260808
JJJ solver/reports/duty_hgs_private_technical/jjj50_seed11_iter1_system_20260808
JJJ solver/reports/duty_hgs_private_technical/jjj10_seed11_iter1_system_20260808
PRD baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/unified_education_prd50_01_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/unified_education_jjj50_01_20260807
CY  baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/unified_education_cy50_01_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/unified_education_probe_jjj10_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/preformal_final_streaming_restart_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/preformal_final_sentinel_off_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/preformal_streaming_restart_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/preformal_sentinel_off_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/real_input_one_cycle_20260807_final
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/preformal_restart_ignition_20260807
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/real_input_one_cycle_20260807_after_scope_fix
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/preformal_provenance_reverify_20260807/replays/final_replay
JJJ baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/real_input_one_cycle_20260807
```

`FACT`：149 个目录中的原始路线／充电动作仍可作为历史固定解输入；作废的是旧车型固定成本下的 `cost_fix/total_cost`、depot profit、Pi0、margin、fairness 以及由旧搜索代理得到当前 incumbent 的身份。CY/JJJ 97 个是本节的 J3 子集，和 V3 的 56 个目录交集为 0。

### 7.6 与单位审计、中国化审计的交叉核对

| 审计项 | 本轮核对结果 |
|---|---|
| 单位审计第 1 条 | 已修。V3 15 个含 EV 包的利润／margin 数值作废；旧 V2 含 EV margin 包 149 个作废或继续保持已作废身份。J2 本身不改变精确总成本；这 149 个包的旧精确成本另因 J1 改变。 |
| 单位审计第 2 条 | 已修。CY 44 + JJJ 53 = 97 个多城市 V2 包的 depot profit、Pi0、margin、fairness 作废；PRD／PRDFIX／METRO 当前车场同价，J3 数值影响 0。 |
| 单位审计第 4 条 | 已修活动 `profit.py` 链。当前生产费率 0，保存包数值影响 0；75 元/小时仍只用于测试／敏感性构造。 |
| 单位审计第 5 条 | 已修 Problem-HGS 与 Duty-HGS 两条代理。V3 56 个运行目录、旧无外层补费的 176 个含 EV 固定解目录、机制验证／标定补充包及其聚合结论不能继续作为新模型搜索证据；其中无 margin 的 27 个目录已在 7.4 逐条补齐。 |
| 中国化审计 A04 | 审计指出 170 和路线时间 75 的来源身份风险；本轮没有替换用户已定 170，也没有启用 75 为生产默认。CSV 与报告明确把数值身份保留为已定情景，不包装成企业实测。 |
| 中国化审计 K05 | 50 元来自陈婉茹等 2023 第 5 节／表 7，审计判可作为中国文献情景保留；本轮值与用户 P43-F/P43-H 决定一致。 |
| 中国化审计影响表 `:149-166` | E3/E4/E5/E6/XA/XA2/XB/XC 与 E2 v7 已因更早 H1/A09/充电参数时代作废；本轮只追加固定成本／利润／柴油价原因，不把它们重新算作可用。E6 的 60 单元／900 联盟记录尤其不能继续使用旧利润公平账。 |

`FACT`：当前可直接入文的正式实验仍为 **0 组**，所以本轮没有损失一组已批准论文正式结果；失效的是技术包、历史 formal 包和候选证据。纯几何坐标、客户身份、路网哈希、需求量和时间窗身份不因 J1—J4 自动作废。

## 八、修改文件、回滚与停止边界

生产代码的本轮必要改动：

- `solver/src/setp_solver/instance_loader.py`：车型固定成本字段、统一 accessor、数值校验。
- `solver/src/setp_solver/china81.py`：读取／校验／登记权威 CSV，将 170/220 接进车型档案。
- `solver/src/setp_solver/cost.py`：仅第三节所示获批 statement。
- `solver/src/setp_solver/profit.py`：J2—J4 三项利润分解对齐。
- `solver/src/setp_solver/private_instance_rebuild_20260811.py`、`algorithms/problem_hgs/evaluation.py`：去掉外层重复计费，只保留审计分解和一致性校验。
- `algorithms/problem_hgs/kernel_proposals.py`、`algorithms/duty_hgs/pyvrp_proposals.py`：J1 的两条搜索代理对齐。
- `solver/scripts/run_problem_hgs_private_technical.py`、`solver/scripts/build_china81_metro_suite_20260812.py`：派生套件保留上游 `vehicle_cost_authority` 来源路径。
- 相关测试文件：锁定权威值、来源接线、代理、无双算、利润／公平和时间定义。

`FACT`：任务开始时已在 `/tmp/resetp-costfix-20260812.wxMhZT/` 保存本轮相关文件快照；旧保存产物没有静默覆盖。回滚时可逐文件按该快照／本报告 diff 反向应用。该临时目录不是长期档案，长期证据以本报告和 Git diff 为准。

`FACT`：`solver/src/setp_solver/search/execution_accounting.py` 是当前无生产调用的历史 realized ledger，单位审计第 4 条没有把它列为活动利润／公平链；它还存在本轮范围外的多趟实体车固定费逐路线重复问题。本轮没有为顺手“闭合”而改它。J4 已覆盖 `calculate_depot_profits` 及通用搜索、Problem-HGS、Duty-HGS 实际公平消费者。

`FACT`：利润与精确总账闭合结论针对通过结构校验的有效解；无匹配路线的孤立 charging action 本来会被 checker 判非法，不据此宣称任意非法 `Solution` 也能闭合。

`FACT`：没有修改 `pending_decisions.md`，因为本轮没有新增或改变用户决定；只在当前事实入口、历史时间线和记忆索引登记本报告入口。
