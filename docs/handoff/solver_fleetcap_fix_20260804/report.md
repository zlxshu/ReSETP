# T4-SOLVER-FLEETCAP-FIX 修复与最小验证报告

> [FACT] V1–V4 已完成：修复后搜索候选补全为 **144/147 成功**，全部落盘补全评估（含共同初始解与独立证书复核）为 **164/167 成功**；固定预算只换种子时，3 个最终目标值的 binary64 十六进制表示和 3 个完整路线签名均不同；固定种子把预算从 100 增到 1000 时，搜索轨迹、最终目标值和最终路线签名均不同。
>
> [FACT] V5 已执行但并非全绿：定向集合 **80 passed / 0 failed / 0 skipped**；规范全量 `solver/tests` 为 **909 passed / 3 failed / 1 skipped**。3 项失败与仓库当前 W3 登记的历史失败逐项一致，不涉及本次修改文件，本任务没有修复它们。
>
> [FACT] 仍未闭合：修复后仍有 **3/147** 个搜索候选在共享精确补全中以实体车队上限异常失败；它们已带候选标识、原始异常和唯一分类完整落盘。正式包因任务明令禁止而未重跑，因此本报告不声称两个旧正式包已经恢复。
>
> [DECISION] 依据用户限定的终态条件“V1 成功数大于 0 且 V2 种子有效”，终态为 `SOLVER_FLEETCAP_FIX_COMPLETE`。

## 1. 根因复核与边界

[FACT] 冷启动材料所述根因与修复前代码一致：

> PyVRP 代理问题不施加每车场实体车数上限，HGS 搜出的方案超编 1 到 5 辆；补全成 China81 完整解时，全部候选被 ValueError "China81 route skeleton cannot satisfy the registered physical fleet caps" 拒绝；该异常在 baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py 约 532-543 行被静默吞掉；结果是最终解恒等于共同初始解，随机种子无效、迭代预算无效、结果恒定。已确认 formal_algorithm_20260802 与 formal_ablation_200c_20260803 两个正式包共 2520 次补全尝试 0 次成功。

[FACT] 修复前 `build_pyvrp_problem()` 在 `strict_multitrip=True` 时把 CV、EV 的 `num_available` 都设为 `len(customers)`，即把物理车队上限从代理问题移除。补全异常虽有部分原始字符串进入统计，但候选没有稳定标识、没有显式成功布尔值、没有原始异常类型与确定性失败分类，调用方会继续回退到共同初始解。

[FACT] 本任务未修改目标函数、成本或排放口径、算例、车队规模、车型参数、种子集合或预算定义；未放宽实体车队上限；未启动正式实验批次；未写论文正文；未修改 `HANDOFF.md` 或 `docs/handoff/memory/`。

## 2. 权威车队版本

[FACT] 仓库中发现 v1、v2、v3 三个 authority 目录，没有比 v3 更新的版本。本次使用：

`data/ChinaInstances/china81_finite_fleet_authority_v3_20260802/`

| 权威文件 | SHA-256 |
|---|---|
| `fleet_caps.csv` | `ed9a584a31cc257eb064d5df9042f2df82a6b1868b73657474a9629e425f00b1` |
| `manifest.json` | `6f409ea92a02198485f066e57e8a06047a3bfc1f7b176f83089180e349ee2929` |
| `metadata.json` | `31104bcadda1449059480a1e064f88b80cda495713c329d277d2c30d721711c0` |
| `artifact_hashes.json` | `7d6a5bde40e6b814ed4dc2b6bea52387d8b7ceaaddadc179f02928e7cf34e8d0` |

[FACT] 50 客户探针 `cn-prd-50c-01-V2-LOCATIONS` 在 25% 档的两个车场均为 `num_cv=3`、`num_ev=1`、`total_fleet_cap=4`。

## 3. 代码改动

[FACT] 工作树在任务开始前已有用户改动。本次先逐文件保存任务前工作树快照，随后只以这些快照为基线生成 [diff.patch](./diff.patch)，因此补丁不混入目标文件在本任务以前的改动。

| 文件与当前行 | 本次改动 | 任务前 SHA-256 | 任务后 SHA-256 |
|---|---|---|---|
| `pyvrp_adapter.py:57-59, 271-375, 414-590, 690-911, 1002-1140` | authority cap、PyVRP Route/Trip 多趟映射、稳定候选 ID、逐候选完成台账、消息分类 | `7556b5ec29a1d2db28b131d0fe4e3c3e5833d8fd993c60c0428d5a7453aed845` | `a00bfe1f6d43acd5539856a2324de077f8ff8d88de3576382156f08d1538a3bc` |
| `epochal_hgs.py:258, 337-402, 472-573, 585-703, 724-858` | warm-start 多趟投影；检查点、终态档案、共同初始解、代理最优解逐次记录原始结果 | `15e2233837b63eea4ea7e729482ce24e787199815cd5af1cbcb9a35cbb0ec6ff` | `661969f95ef7e86660d4ee250a48f8921c37990eb7721448d6126240677d6fbd` |
| `route_pool_sp.py:346-377` | route-pool 最终两次补全复核写入同一字段合同 | `7b570ba5a793f7ca2c5484779eb8d91b3b7e0d048a8e15311fcd01429acf355c` | `58dd67eff098bc038865744a2b6e00d559960d4a0f4428ff9305b38d257eb6e1` |
| `run_adapter_g0.py:61-66` | 适配 `_project_initial_solution(..., bundle)` 新签名并使用直接运行的解 | `0629fcc2b538b18a9dfe597bb0ade628bb58d50212b70013951a22f1437e68b2` | `d62e58f337762de660a67e093234f869eb4628516955ed9e407885d59ecd9f6f` |
| `test_pyvrp_adapter.py:160-168, 201-239, 275-347` | cap、Trip 边界、失败字段与消息分类定向回归 | `1a65a0e3f8f31384557892f121903b291a0fa405027eaefa0940aa97233c6f17` | `796f252af3b38529852a22a59541fa0456e85efa866400565ed5c0366341818f` |

[FACT] 补丁统计为：`pyvrp_adapter.py` +344/-80，`epochal_hgs.py` +95/-11，`route_pool_sp.py` +8/-1，`run_adapter_g0.py` +2/-1，`test_pyvrp_adapter.py` +114/-2。完整 1101 行 unified diff 已单独落在 `diff.patch`。

### 3.1 修复 A 的关键 diff

```diff
-        cv_available = len(customers) if strict_multitrip else physical_cv_cap
-        ev_available = len(customers) if strict_multitrip else physical_ev_cap
+        cv_available = (
+            physical_total_cap
+            if normalized_mode == "cv_only"
+            else physical_cv_cap
+        )
+        ev_available = physical_ev_cap
+        reload_kwargs = (
+            {
+                "reload_depots": [location_object[depot.node_id]],
+                "max_reloads": max(0, len(customers) - 1),
+            }
+            if strict_multitrip
+            else {}
+        )
```

[FACT] PyVRP 0.12.2 原生支持一个 `Route` 内含多个 `Trip`。修复后，一个 PyVRP `Route` 表示一台实体车，内部 `Trip` 表示该车的多趟车场—车场派遣；`num_available` 因而直接取 authority 的物理车数。混合视图分别使用 `num_cv` 与 `num_ev`；`cv_only` 继续使用共享完整评分器定义的全燃油参照总车数 `total_fleet_cap`。零辆车型不再伪造一辆，而是不创建该车型。

[FACT] 严格多趟代理的固定成本仍为修复前的 `0`；本次没有把每趟固定成本重新加入代理，也没有修改任何精确成本函数。warm start 先通过共享补全得到物理车—趟证书，再投影为 `Route([Trip, ...])`；HGS 解翻译回项目骨架时，每个 Trip 使用唯一 `PYVRP-xxxx#Tn` 标识。

```diff
+    certificate = build_multitrip_certificate(
+        normalized_routes,
+        bundle.instance,
+        bundle.prices,
+        charging_actions=...,
+    )
+    for trip in certificate.trips:
+        trips_by_physical_vehicle.setdefault(
+            trip.physical_vehicle_id, []
+        ).append(trip)
...
+        routes.append(PyVRPRoute(data, pyvrp_trips, vehicle_type))
```

### 3.2 修复 B 的关键 diff

```diff
+                {
+                    "candidate_id": candidate_id,
+                    "source": "terminal_population_archive",
+                    "iteration": None,
+                    "completion_succeeded": False,
+                    "complete_objective": None,
+                    "status": "INFEASIBLE_OR_ERROR",
+                    "exception_type": type(exc).__name__,
+                    "exception_message": str(exc),
+                    "failure_category": _completion_failure_category(str(exc)),
+                }
```

[FACT] 候选标识是候选完整 Route/Trip 结构的规范 JSON SHA-256，不依赖 Python 对象地址。检查点、终态种群档案、共同初始解、代理最优解以及 route-pool 最终复核全部写入统一字段。成功记录同样落盘，`exception_type/message/failure_category` 为 `null`；失败记录保留原始异常类型与原始消息。

[FACT] 分类规则只依赖异常消息，按下列顺序唯一确定：消息以 `SEARCH_NOT_FOUND:` 开头归为 `搜索未找到`；以 `BUSINESS_HARD_INFEASIBLE:` 开头归为 `业务硬不可行`；其余非空的补全异常消息归为 `代理找到但完成失败`；空消息直接抛出 `RuntimeError`，不允许猜测分类。

## 4. 验证设计

[FACT] 这是小型非正式探针，不是正式实验。实例为 `cn-prd-50c-01-V2-LOCATIONS`；种子为 1、2、3；短预算为每视图 100 HGS iteration；长预算为每视图 1000 iteration；checkpoint 间隔 100；每视图终态档案上限 8；exact elites 每视图 2；SP 时限 0.5 秒。两档预算相差一个数量级，配置没有在观察结果后调参。

[FACT] 运行环境为 Python 3.13.9、NumPy 2.3.5、PyVRP 0.12.2、SciPy 1.16.3、`PYTHONHASHSEED=0`。探针由实验监控器冻结 authority、三个受保护文件和三份主要原型源码；最终 post 运行状态 `COMPLETED`、findings 为空，监控记录的生产文件哈希与本报告任务后哈希一致。

[FACT] `probe_raw.csv` 共 334 条逐次补全评估记录（pre 167、post 167）。`raw_runs.csv` 共 8 条逐运行汇总，并保留完整路线签名 JSON、binary64 十六进制目标值以及轨迹哈希。

## 5. V1：补全是否恢复

| 口径 | 尝试 | 成功 | 失败 |
|---|---:|---:|---:|
| 修复后搜索候选：checkpoint + terminal archive + proxy best | 147 | **144** | 3 |
| 修复后全部落盘补全评估：另含共同初始解和最终独立复核 | 167 | **164** | 3 |

[DECISION] V1 通过，成功数大于 0。

[FACT] 修复前同一 50c 探针并非形式包的“全数失败”：搜索候选为 64/147 成功；但四个最终解仍全部等于共同初始解。该小探针的偶然成功不推翻 100c/200c 两个正式包 0/2520 的既有审计事实。

## 6. V2：只换种子

固定预算为每视图 100 iteration，其余配置相同。

| seed | 最终目标值 | binary64 精确表示 | 路线签名 SHA-256 |
|---:|---:|---|---|
| 1 | 1930.5499913454935 | `0x1.e2a3330ee67e9p+10` | `70cbaf4a3c791216c195d86e519cfe0b2912064e5c19d224c9b714d532cdadcf` |
| 2 | 1899.1067069707444 | `0x1.dac6d44979669p+10` | `55c2267b6e5aa9791b50dfba7e41eaeb950b26d46e32089f2fcf923217e4a448` |
| 3 | 1861.5953792129237 | `0x1.d1661ab16a0e7p+10` | `84b5c5d706073bb5402bd8a67a7c872ef8654cc6b890339c310bab4e5720215d` |

[FACT] 三个 binary64 位模式两两不等，三个路线签名哈希两两不等。目标差为 seed2-seed1 `-31.443284374749055`、seed3-seed1 `-68.95461213256976`、seed3-seed2 `-37.51132775782071`。路线签名不是仅凭摘要构造；它定义为排序后的 `[vehicle_type, home_depot_id, node_sequence]` 完整序列，完整 JSON 已写入 `raw_runs.csv` 与 `metadata.json`。

[DECISION] V2 通过，随机种子对最终解有效。

## 7. V3：固定种子只改预算

固定 seed=1；预算从 100 增至 1000，每个视图实际迭代数均从 100 增至 1000。

| budget | 最终目标值 | binary64 精确表示 | 路线签名 SHA-256 | 搜索轨迹 SHA-256 |
|---:|---:|---|---|---|
| 100 | 1930.5499913454935 | `0x1.e2a3330ee67e9p+10` | `70cbaf4a3c791216c195d86e519cfe0b2912064e5c19d224c9b714d532cdadcf` | `332cda23435ba64799b80985b46cc1808fec251f4069e9ec0589f3b5293a6aea` |
| 1000 | 1922.1983391919891 | `0x1.e08cb196ddc6fp+10` | `5adff5a6c19f106e2b4af071ef4a79444c8fbd1f738e0aa1ff8ae4e957eaa882` | `b1b685e1366f930dcda5de2d4e91852624dc87257152b4c67e59744ff6a537cd` |

[FACT] 长预算最终目标值比短预算低 `8.351652153504347`，binary64、路线签名和完整搜索轨迹均不同。各视图 checkpoint 的共享完整模型目标值如下；括号前为 iteration，全部精确候选 ID 与十六进制值见 `metadata.json` 和 `probe_raw.csv`。

| 视图 | budget=100 | budget=1000 |
|---|---|---|
| `cv_only` | 100: 2087.1669012477587 | 100: 2087.1669012477587; 200: 2085.059104428066; 300–700: 2248.847162812714; 800–1000: 2245.5226865423256 |
| `naive_ev` | 100: 2159.343882291147 | 100: 2159.343882291147; 200: 2103.769574901767; 300–400: 2090.8600513163483; 500–1000: 2089.5901333176716 |
| `mechanism_ev` | 100: 2192.699308770718 | 100–1000: 2192.699308770718 |

[INFERENCE] checkpoint 的精确目标值不要求随 HGS 的代理目标单调下降；本任务只据具体序列、候选 ID 和轨迹哈希判断预算确实改变了搜索过程，不把该序列解释为算法优越性。

[DECISION] V3 通过，预算对搜索轨迹与最终解有效。

## 8. V4：修复前后失败分类

同一 4 个配置、同一 147 个搜索候选补全计数口径：

| run | pre 成功/尝试 | post 成功/尝试 | pre `代理找到但完成失败` | post `代理找到但完成失败` |
|---|---:|---:|---:|---:|
| seed1 / budget100 | 5/30 | 29/30 | 25 | 1 |
| seed2 / budget100 | 7/30 | 29/30 | 23 | 1 |
| seed3 / budget100 | 6/30 | 29/30 | 24 | 1 |
| seed1 / budget1000 | 46/57 | 57/57 | 11 | 0 |
| 合计 | **64/147** | **144/147** | **83** | **3** |

[FACT] `搜索未找到` 为 pre 0、post 0；`业务硬不可行` 为 pre 0、post 0。全部落盘评估口径为 pre 84/167 成功、post 164/167 成功。

[FACT] post 的 3 个失败均来自 `terminal_population_archive`，候选 ID 分别为：

`d16b183843e4bfe5ab1339ecee441cebf7ff4dcba7031e43a09b0569f3759a62`

`6c3fa629ee863e714fca8ad56e13c6a05fe3510517010ca27a9aca0d7184d337`

`13f850467079788030098d812b145c22841c9ac4f4e54e194cdf987019514beb`

三者原始异常均为：

```text
ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_shenzhen': overage=(1, 0, 1)
```

[FACT] 这 3 条均按唯一消息规则归为 `代理找到但完成失败`，没有被吞掉或改写成笼统状态。

## 9. V5：定向与全量回归

### 9.1 定向回归

[FACT] 先定位并运行了下列既有测试文件：

```text
baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/test_pyvrp_adapter.py
baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/test_route_pool_mip.py
solver/tests/test_china81_bundle_20260720.py
solver/tests/test_china81_fleet_authority_v3_20260802.py
solver/tests/test_china81_shared_completion_20260720.py
solver/tests/test_multitrip_schedule.py
solver/tests/test_dynamic_multitrip_schedule.py
solver/tests/test_nonlinear_multitrip_schedule_20260720.py
solver/tests/test_route_pool_recombination.py
solver/tests/test_public_station_multitrip_20260723.py
```

[FACT] 规范 Python 3.13 环境结果：**80 passed / 0 failed / 0 skipped**，6.161 秒。新增的 `test_pyvrp_adapter.py` 子集为 10/10 通过。

### 9.2 全量 `solver/tests`

权威命令环境为：

```text
PYTHONPATH=solver/src:models/src:.:/opt/anaconda3/lib/python3.13/site-packages:build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests -q
```

[FACT] 结果：**909 passed / 3 failed / 1 skipped**，281.355 秒。失败用例为：

```text
solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables
solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts
solver/tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps
```

[FACT] 前两项是仓库 W3 已登记的 E5 `unresolved_historical`；第三项是 EV-heavy 旧“候选必须严格改善”合同，实际仍为 `4954.204438573212` 不小于 `4923.553350198799`。它们均未引用本次修改的五个文件，且与当前仓库 `docs/handoff/memory/regression_fix_20260802.md` 登记的 909/1/3 完全一致。

[FACT] 用户提示的 901 passed / 1 skipped / 5 failed 是 08-02 更早的 Z1 快照；W2/W3 后当前登记基线已变为 909/1/3。本次以当前 checkout 的规范环境实跑结果为准，没有为了转绿修改这 3 项历史测试。

[FACT] 曾用 PyVRP 封存解释器直接跑出 906/1/6；其中两项只因解释器不是测试硬编码的 `/opt/anaconda3/bin/python3.13`。该轮已标为非权威诊断，最终 V5 只采用上述规范环境结果。

## 10. 受保护文件与停止条件

| 受保护文件 | 任务前 SHA-256 | 任务后 SHA-256 | 本任务编辑 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d` | `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d` | 否 |
| `solver/src/setp_solver/check.py` | `86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b` | `86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b` | 否 |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | 否 |

[FACT] `cost.py` 在任务启动前已显示为脏文件，但任务前后内容哈希完全相同；本任务没有覆盖用户的既有修改。

[HALT] 四个停止条件均未触发：修复不需要改受保护文件；V1 成功数不是 0；根因描述与代码实际一致；最终改动仍限定在代理物理车 cap/Route-Trip 表示、补全尝试记录及相应适配和测试。

## 11. 仍未闭合的问题与结论边界

[FACT] 代理层已经把每车场物理车数量编码进 PyVRP `num_available`；50c 探针每个混合视图的类型上限为 CV 3、EV 1，每条 PyVRP 物理车 Route 可含多趟 Trip。

[INFERENCE] post 的 3 条残余失败来自代理多趟 Route/Trip 分组与共享精确补全的排班抽象并不完全等价：HGS 的一个 Route 内 Trip 顺序满足代理 cap，但共享补全会根据每趟独立最早出发时间重新构造实体车排班，少数骨架因此仍得到总量超 1。这个解释由代码路径和相同原始异常支持，但本任务没有为消除这 3 条而修改共享补全或放宽上限，因为那会越出修复 A/B 的窄边界。

[FACT] 正式 `formal_algorithm_20260802` 与 `formal_ablation_200c_20260803` 没有重跑；本报告只证明小型 50c 探针已从“最终解恒等、种子/预算无效”恢复为补全成功且种子/预算有效，不把探针升级为正式科学结果。

[DECISION] `SOLVER_FLEETCAP_FIX_COMPLETE`。机器可读终态与全部判据见 [decision.json](./decision.json)；逐次原始记录见 [probe_raw.csv](./probe_raw.csv)；逐运行完整路线签名和数值见 [raw_runs.csv](./raw_runs.csv)；环境、哈希、测试和完整 V3 checkpoint 序列见 [metadata.json](./metadata.json)。
