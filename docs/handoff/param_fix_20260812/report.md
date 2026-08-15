PARAMFIX_DONE

# 2026-08-12 中国化参数修复与 A14 重算报告

## 一、结论与范围

`USER DECISION`：用户于 2026-08-12 明确选择“乙档”并指示“算”。本轮只执行 E1–E5；审计中其余 12 项没有改数值、没有改披露、没有顺手修复。

`FACT`：五项已完成，本轮没有运行正式实验，没有改算例几何、客户、需求、班次、算法参数或评价口径。旧 `solver/reports/instance_rebuild_20260811/` 未被覆盖；新的独立重算包保存在 `solver/reports/instance_rebuild_60kw_recompute_20260812/`。

`CORRECTION`：旧 A14 三个数 **148.50 kWh / 79.46 元 / 22.79 kgCO2e** 作废。60 kW 登记非线性曲线的重算结果为 **362.80 kWh / 194.13 元 / 55.69 kgCO2e**。

## 二、修改明细

| 项目 | 文件与当前行号 | 旧值／旧行为 | 新值／新行为 | 依据 |
|---|---|---|---|---|
| E1｜A14 死错 | `solver/scripts/build_private_instance_rebuild_20260811.py:69,376-388` | 计算常量 22 kW，写出的 `facilities.csv` 却是 60 kW | 计算常量统一为 60 kW；写出值保持 60 kW | P43-I 用户决定；咸宁市规划印刷页 23 的现场清单和印刷页 84 的 60 kW 一机一枪直流物流车场景；`pending_decisions.md:169-179` |
| E2｜A14 真实约束重算 | 同脚本 `:1178-1237,1634-1846`；新产物目录 | `charge_hours×22` 的线性外推，没有检查电池容量和 SOC—功率曲线 | 从实例 EV 电池容量、运行时车场功率和登记分段曲线计算 `reachable_energy_kwh`；另增只读旧见证、只写新报告的 CLI 路径 | 同一 P43-I 60 kW 口径；`charging_curve.py:86-106,319-347` 的登记曲线与共享积分核 |
| E3｜柴油排放因子 | `solver/src/setp_solver/china81.py:1055` | 2.70480534 kgCO2/L | 2.6419028944 kgCO2/L | 《陆上交通运输企业温室气体排放核算方法与报告指南（试行）》印刷页 10–11 式 (3)–(5)、印刷页 15 密度、印刷页 60 柴油参数 |
| E3｜因子生成链 | `baselines/e4_e5/build_china_policy_price_gate_20260717.py:180,259-300` | 用 6.88 元/L 与 8000 元/t 价格倒推 0.86 kg/L，输出 8 位小数 | 显式使用 0.84 t/m³、43.330 GJ/t、20.20×10⁻³ tC/GJ、98%、44/12，输出 10 位小数；源标记同时验 0.84 | 同上指南页码 |
| E4｜A06 权威断线 | `solver/src/setp_solver/china81.py:228-247,466-470,1002-1037` | 车型档案登记 `traction_energy_multiplier`，但 `_china_prices()` 沿用共享默认 `alpha_e` | `_china_prices()` 必须从 `vehicle_parameters["ev"].traction_energy_multiplier` 生成 `prices.alpha_e`；`China81Bundle.__post_init__` 在两者不同时立即失败 | 车型档案成为权威源，又有组合边界一致性断言 |
| E5｜A10 基础 loader 默认 | `solver/src/setp_solver/china81.py:1052,1062-1078` | 车场 22 kW；共享/车场三元组是 `M17_22KW_NORMAL_PWL` | 车场 60 kW；共享/车场三元组是 `M17_FAST_SHAPE_SCALED_60KW_PWL` | P43-I；登记曲线仍是 Montoya Fig. 8, p.13 形状从 44 kW 缩放到 60 kW，不写成中国实测曲线 |

`FACT`：`solver/src/setp_solver/prices.py:34-35` 的 `kappa_heat=44.0` 和 `psi_conv=737.0` 未改。它们是 CMEM 油耗模型的参数，不是本次柴油排放因子公式的密度。

`FACT`：E4 没有触及 `cost.py`、`check.py` 或 `search/evaluation.py`，也没有修改 `instance_loader.py`。`cost.py:1109-1119` 继续读 `prices.alpha_e`；本轮在加载边界把车型档案的值正确送入该字段。

## 三、E2：60 kW 午休充电天花板重算

### 3.1 不变的结构输入

`FACT`：沿用旧 `health_summary.json` 的 seed 11 见证，共 5 条“上午返场后继续下午职责”。每条下午任务体积 6.5 m³，沿用旧装货口径 `0.1 h/m³`：

```text
装货时间 = 6.5 × 0.1 = 0.65 h
午休可用充电时间 = 2.00 - 0.65 = 1.35 h = 81 min
```

这 5 个见证 ID 均是 `CV_*`，所以此处是“如果这 5 条跨班职责改由 EV 承担”的反事实结构天花板，不是 5 辆实际 EV 的观测充电量。本轮没有修审计 A17；6.5 m³ 和 0.1 h/m³ 只是为了与旧三个数做同结构对照。

### 3.2 分段曲线积分

`FACT`：电池容量 77.28 kWh，车场额定功率 60 kW，登记曲线为 `M17_FAST_SHAPE_SCALED_60KW_PWL`，SOC 断点为 0/85%/95%/100%。由登记形状缩放得到三段功率：

```text
0%  – 85%  : 59.8240469208 kW
85% – 95%  : 27.2727272727 kW
95% – 100% :  9.0909090909 kW
```

从 0 kWh 起算是这条功率随 SOC 不增曲线下的最大电量增量。前 85% 与剩余时间的计算为：

```text
85% 电量 = 77.28 × 0.85 = 65.688 kWh
充到 85% 用时 = 65.688 / 59.8240469208 × 60
                 = 65.8812 min
剩余时间 = 81 - 65.8812 = 15.1188 min
第二段可充 = 27.2727272727 × 15.1188 / 60
               = 6.8721818182 kWh
每条职责上限 = 65.688 + 6.8721818182
                 = 72.5601818182 kWh
结束 SOC = 72.5601818182 / 77.28 = 93.8925748%
5 条合计 = 5 × 72.5601818182
           = 362.8009090909 kWh
```

### 3.3 瓶颈是否换了约束

`FACT`：线性算术下 `60×1.35=81.00 kWh`，高于 77.28 kWh 电池容量；如果忽略降功率，会误判为电池容量限制。但登记曲线从 0 kWh 充满需 **108.3852 min**，81 min 后仍差 **4.7198181818 kWh**。

`CORRECTION`：真实登记约束下，电池并未充满；最终瓶颈是 **81 min 午休可用时间 + 高 SOC 降功率**，不是电池容量已触顶。

### 3.4 新旧三数对照

| 指标 | 旧 22 kW 线性口径 | 新 60 kW 登记曲线 | 变化 |
|---|---:|---:|---:|
| 5 条职责午休可充电量 | 148.50 kWh | 362.8009090909 kWh（报告 362.80） | +214.30 kWh |
| 18:30 转到 12:00 的货币上限 | 79.46 元 | 194.1347664545 元（报告 194.13） | +114.67 元 |
| 对应排放上限 | 22.79 kgCO2e | 55.6899395455 kgCO2e（报告 55.69） | +32.90 kgCO2e |

时段输入差在广州和佛山两车场一致：

```text
电价差 = 1.32716875 - 0.79206875 = 0.5351 元/kWh
碳强度差 = 0.1756 - 0.0221 = 0.1535 kgCO2e/kWh
货币上限 = 362.8009090909 × 0.5351
             = 194.1347664545 元
排放上限 = 362.8009090909 × 0.1535
             = 55.6899395455 kgCO2e
```

`FACT`：旧报告目录的任务前后整树 SHA-256 摘要均为 `d38cfc046b48c398a665f4e1c9bbfea21e05f2427256c8c6bd619a14ead38fcf`。新包含 `raw_runs.csv`、`health_summary.json`、`metadata.json`、`decision.json`、`artifact_hashes.json` 和 `report.md`；其中 `formal_search_runs=0`。

## 四、E3：柴油排放因子独立重推

### 4.1 原始证据与公式

`FACT`：本地原文为 `data/Carbon/中国情景/raw_20260717/NDRC_land_transport_GHG_guideline.pdf`，SHA-256 为 `84aadb948141b5229f9339254dd305bbf54b435e140827244d9e3c69b289bb31`。

- 印刷页 10，式 (3)：`E_CO2 = Σ AD_i × EF_i`。
- 印刷页 10，式 (4)：`AD_i = NCV_i × FC_i`。
- 印刷页 11，式 (5)：`EF_i = CC_i × OF_i × 44/12`。
- 印刷页 15：柴油密度 `0.84 t/m³`。
- 印刷页 60：柴油低位发热量 `43.330 GJ/t`，单位热值含碳量 `20.20×10⁻³ tC/GJ`，碳氧化率 `98%`。

### 4.2 完整单位换算

```text
1. 体积转质量
   0.84 t/m³ × (1 m³ / 1000 L)
   = 0.00084 t/L = 0.84 kg/L

2. 每升柴油能量
   0.00084 t/L × 43.330 GJ/t
   = 0.03639720 GJ/L

3. 每升含碳量
   0.03639720 GJ/L × 0.02020 tC/GJ
   = 0.0007352234400 tC/L

4. 每升氧化碳
   0.0007352234400 tC/L × 0.98
   = 0.000720518971200 tC/L

5. 碳转二氧化碳
   0.000720518971200 tC/L × 44/12
   = 0.0026419028944 tCO2/L

6. 吨转千克
   0.0026419028944 tCO2/L × 1000 kg/t
   = 2.6419028944 kgCO2/L
```

`FACT`：独立结果与审计给出的 `2.6419028944` 逐位一致，因此没有触发停止条件。

`CORRECTION`：旧生成器用价格倒推 `6.88 / (8000/1000) = 0.86 kg/L`，再与单位质量排放量相乘，得 `2.704805344266…`，最后格式化为 `2.70480534`。新值比旧值低 `0.0629024456 kgCO2/L`，即 `2.325581%`。这一更正只改柴油燃烧 CO2 因子，不把 0.84 kg/L 机械抄到 CMEM 油耗模型。

## 五、作废与重算影响清单

下表逐项对照 `china_localization_repo_audit_20260812.md` 第三节。“作废”指不得再当作当前参数口径的数字或比较；历史文件本身保留，没有覆盖或删除。

| 审计结果家族 | 本轮确认或修正 | 处置 |
|---|---|---|
| `solver/reports/instance_rebuild_20260811` | A14 的 148.50/79.46/22.79 作废；E3 还使其 `per_km_vehicle_comparison.csv` 中 CV 排放和含碳价数字陈旧。14 趟、8 辆实体车、客户和路线结构见证不因 A14 自动作废 | 旧包保留为历史；三数由新 60 kW 包取代 |
| 私有重建与 `china81_suite_v3_20260812` 健康见证 | 审计该行的 A17 不在本轮授权内，本轮没有声称解决 7.2 m³/1735 kg/0.1 h/m³。E3/E5 只使能耗、CV 排放、临界里程、充电天花板等相关健康列需重算 | 坐标、客户身份、路网、需求等结构证据保留；A17 问题仍原样留待授权 |
| `solver/reports/mechanism_validation_v3_20260811` | 明确使用 22 kW/M17 旧口径；四种固定充电策略的时长、电费、排放和含 EV 方向短测不再是当前参数结果 | 须重算；本轮未跑 |
| 历史 E5 非线性正式 40 单元 | 车场 22 kW 会话的时长、可行性和端点作废；公共站 60 kW 行不因 E5 默认值单独变化，但整个正式端点不得迁移到新主参数 | 须按新参数重跑才能比较 |
| 历史 E4 联合路径/碳面板 | E5 影响实际车场充电解；E3 影响全部含 CV 排放、含碳价成本及可能的路线/车型选择 | 排放、含碳价成本与含充电解可行性须重算 |
| 历史 XA 算法比较 | 保存解属 22 kW/旧柴油 EF 参数时代 | 旧目标值、可行性与算法比较整体作废；不能只换报告数字 |
| 历史 XA2 200c 消融 | 同上 | 旧三臂数字整体作废；须同参数重跑 |
| 历史 XB 五档车队 | E5 直接影响实际车场充电的含 EV 档；全 CV 档不受充电功率直接影响，但受 E3 影响 | 全部比较面板不得当作当前参数结果 |
| 历史 XC 动态调度 | E5 影响车场充电的事件状态、动作和成本；E3 影响含 CV 排放和碳价 | 冻结状态、充电动作、成本和排放须重算 |
| E3 正式客户归属面板 | E3 使含 CV 排放及碳价目标陈旧；E5 仅直接影响实际车场充电的保存解 | 受影响行须重算；含碳价目标参与搜索时须重跑 |
| E6 承运商参与面板 | E3/E5 传播边界与上一行相同；成本、利润和参与性会受影响 | 受影响行须重算；本轮未重跑 |
| E2 v7 | 405 任务/1620 完整解属旧参数时代；E3 影响排放/碳价列，E5 影响实际车场充电解 | 旧数值作废；该包本来也不是当前可入文结果 |
| E4 carbon timing 固定解重放 | 审计原文的 CEF/充电时长影响继续成立；本轮还需补记 E3 使固定解的直接/系统排放和含碳价绝对值陈旧 | 405 个零搜索重放的排放与时序列须重算 |
| `baselines/e4_e5/china_policy_price_gate_20260717/emission_factors.csv` | 仍封存旧 `2.70480534`，其 manifest 与历史哈希不应手改 | 保留为 2026-07-17 历史包，不再作当前柴油 EF 证据；当前生成器已更正 |
| `solver/reports/depot_power_60kw_20260811/minimal_run_endogenous` | “60 kW 接线可加载”的技术事实仍保留；但它是全 CV 保存解，`E_total/E_cv_direct/cost_carbon/total_cost` 因 E3 陈旧 | 不因 E5 直接作废接线事实，但数值总账不得当作当前结果 |

`FACT`：E4 修复前后车型档案与共享默认值当前数字相同，因此 E4 本身不会数值性作废已有产物；它修的是未来“改了车型档案但评价仍静默读旧值”的风险。

`FACT`：不因本轮参数更正自动作废的是：客户/设施身份、坐标、路网矩阵与哈希、纯几何距离、时间窗身份、客户覆盖和需求量；公开 Solomon/Goeke/MDVRPTW 基准和国际算法血统也不因 China81 参数更正作废。

## 六、受保护文件 SHA-256

| 文件 | 任务前 | 任务后 | 结论 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | `ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1` | `ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1` | 一致，未修改 |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | 一致，未修改 |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | 一致，未修改 |

E4 没有触线；不需要停下等待 `cost.py` 修改授权。

## 七、验证结果

1. 定向回归：

   ```text
   PYTHONDONTWRITEBYTECODE=1 \
   PYTHONPATH=solver/src:third_party/setp_hgs_kernel \
   /opt/anaconda3/bin/python3.13 -m pytest -q -p no:cacheprovider \
     solver/tests/test_china81_bundle_20260720.py \
     solver/tests/test_private_rebuild_search_adapter.py \
     solver/tests/test_station_specific_charging_curves.py \
     solver/tests/test_china81_shared_completion_20260720.py \
     solver/tests/test_china81_in_memory_winner_20260720.py \
     solver/tests/test_china81_endogenous_fleet_parameters.py \
     solver/tests/test_china81_profiled_road_matrices_nl3b_20260720.py \
     solver/tests/test_problem_hgs_schedule_oracle.py \
     solver/tests/test_china_policy_price_gate_20260717.py \
     solver/tests/test_cost.py \
     solver/tests/test_charging_curve.py
   ```

   结果：`77 passed in 3.02s`。

2. E4 新测试确认：车型 `traction_energy_multiplier` 改值时 `_china_prices()` 的 `alpha_e` 同步改变；人为造成 bundle 两值不一致时立即抛错。

3. E3 新测试确认：当前生成器返回精确 `2.6419028944`；基础 China81 bundle 运行时也读到该值。旧 `20260717` 证据包哈希测试继续只证明历史包未被篡改。

4. E2 产物验证：`artifact_hashes.json` 中 5 个非 manifest 文件全部逐个哈希通过；精确总电量和瓶颈标记二次读回通过。

5. `git diff --check` 对本轮已跟踪代码/测试文件通过；新报告目录中新生 AppleDouble `._*` 边车文件已清除。

## 八、产物索引

- 本轮总报告：`docs/handoff/param_fix_20260812/report.md`。
- A14 60 kW 独立重算：`solver/reports/instance_rebuild_60kw_recompute_20260812/`。
- 旧 A14 历史包：`solver/reports/instance_rebuild_20260811/`，未覆盖。
- 排放因子原文：`data/Carbon/中国情景/raw_20260717/NDRC_land_transport_GHG_guideline.pdf`。

