# T6-HOUSEKEEPING：测试失败归因核查与候选数据集入库封存

日期：2026-08-04

本报告只覆盖本任务的两项工作。结论按 FACT、INFERENCE、HALT 分开记录。

## 第一部分：测试失败归因核查

### FACT：全量测试结果

测试环境可用，执行命令为：

```text
PYTHONPATH=solver/src:models/src:.:/opt/anaconda3/lib/python3.13/site-packages:build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests -q
```

结果为：**909 passed / 3 failed / 1 skipped**，退出码为 1，用时 319.47 秒。

三个失败及完整错误摘要如下：

| 完整失败用例名 | 错误类型 | 错误摘要 |
|---|---|---|
| `solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables` | AssertionError | `run_e5_charging_ablation(Q1_BUNDLE_DIR, REAL_BUDGET_REPORT)` 返回的 `report["carbon_aware"]["feasible"]` 为 `False`，测试断言其应为 `True`。 |
| `solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts` | AssertionError | `run_ev_adoption_diagnostic(...)` 返回行的 `row["root_cause"]` 为 `"repair_logic_defect"`，测试断言其不应等于该值。 |
| `solver/tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps` | AssertionError | `candidate_obj=4954.204438573212` 不小于 `initial_obj=4923.553350198799`；测试断言 `candidate_obj < initial_obj`。 |

### FACT：历史失败登记检索

三个完整用例名均在用户指定检索范围内找到登记，均不是“未找到登记”：

| 失败 | 登记位置 | 登记内容 |
|---|---|---|
| E5 R1 | `docs/handoff/solver_fleetcap_fix_20260804/report.md:223-233`；`docs/handoff/memory/fleet_authority_v3_20260802.md:19-25`；`docs/handoff/memory/regression_fix_20260802.md:15-23`；`HANDOFF.md:5833` | 已登记为 E5 unresolved historical；描述为 carbon-aware route infeasible。 |
| E5 R2 | 同上 | 已登记为 E5 unresolved historical；描述为 `repair_logic_defect` 诊断残留。 |
| EV-heavy | 同上 | 已登记为旧的 candidate-strict-improvement contract；登记值为 candidate objective `4954.204438573212` 不小于 initial objective `4923.553350198799`。 |

因此，2026-08-02 的 901/1/5 是历史快照；本次当前全量结果中的 3 个失败全部已有登记。

### FACT：导入链和被测对象

T4 修改的五个文件是：

```text
baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py
baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py
baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py
baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/run_adapter_g0.py
baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/test_pyvrp_adapter.py
```

逐个失败的导入链核对结果：

| 失败 | 导入路径与被测函数 | 是否触及 T4 五文件 |
|---|---|---|
| E5 R1 | `solver/tests/test_e5_ablation.py:6-16,97-98` 调用 `setp_solver.search.e5_ablation.run_e5_charging_ablation`；实现位于 `solver/src/setp_solver/search/e5_ablation.py:54-68`，继续走 `search.charging` 的固定路线回放/评价路径。 | 否。测试文件、`e5_ablation.py` 及其直接导入链中未出现五个 T4 文件名。 |
| E5 R2 | `solver/tests/test_e5_ablation.py:6-16,109-110` 调用 `setp_solver.search.e5_ablation.run_ev_adoption_diagnostic`；实现位于 `solver/src/setp_solver/search/e5_ablation.py:98-118`，继续走充电回放与评价路径。 | 否。测试文件、`e5_ablation.py` 及其直接导入链中未出现五个 T4 文件名。 |
| EV-heavy | `solver/tests/test_ev_heavy_findability_gate.py:10-17,123-142` 调用 `score_reference` 和 `apply_winner_action`，动作是 `vehicle_type_swap`；`solver/src/setp_solver/search/winner_operators.py:1-20` 是到 `solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py:248-307,503,573` 的兼容门面/内核路径，初始解来自 `baselines/e2_alns/ev_heavy_findability_gate.py:459-462`。 | 否。该链路未出现 `pyvrp_adapter.py`、`epochal_hgs.py`、`route_pool_sp.py`、`run_adapter_g0.py` 或 `test_pyvrp_adapter.py`。 |

### INFERENCE：归因判断

三个失败均**与 T4 本次修改无关**。依据是每个失败的测试导入路径、被测函数和直接实现链均不触及 T4 的五个文件；三个失败分别属于已登记的 E5 历史路径和 EV-heavy 旧断言契约。本判断仅在上述静态导入链和被测对象边界内成立，不把“同一次全量运行”本身当作因果证据。

本部分没有修复任何失败，没有修改测试文件，也没有修改源码；`solver/src/setp_solver/cost.py`、`check.py`、`search/evaluation.py` 均未修改。

## 第二部分：候选数据集入库封存

### FACT：筛选和实际入库

输入清单为 `docs/handoff/instance_data_source_survey_20260804/candidates.json`，共 17 个候选。筛选条件是：许可明确允许下载与再分发、存在直接数据文件、单个数据集压缩后不超过 200 MB。

实际入库 5 个候选，共 52 个原始文件：

| 候选 | 目录 | 文件数 | 下载载荷字节数 | 许可 |
|---|---|---:|---:|---|
| C01 SN Data | `data/ExternalCandidates_20260804/C01_SN-Data/` | 4 | 1,909,257 | CC BY 4.0 |
| C02 JD mobile battery swapping | `data/ExternalCandidates_20260804/C02_JD-mobile-battery-swapping/` | 1 | 239,657 | CC BY 4.0 |
| C11 Goeke–Schneider EVRPTW-MF | `data/ExternalCandidates_20260804/C11_Goeke-Schneider-EVRPTW-MF/` | 1 | 5,490,493 | CC BY 4.0 |
| C15 MFVRP-LEZ | `data/ExternalCandidates_20260804/C15_MFVRP-LEZ/` | 3 | 486,747 | CC BY 4.0 |
| C17 Consistent Collaborative Vehicle Utilization | `data/ExternalCandidates_20260804/C17_CCVUP/` | 43 | 738,135 | CC BY 4.0 |

每个入库目录包含 `SOURCE.md`，其中记录名称、链接、DOI、Creative Commons Attribution 4.0 International 全称及许可链接、下载完成/核验时间、原始文件名、下载 URL、文件 SHA-256 和数据页字段清单。C11 文件名保持为数据接口返回的原始名 `instances_EVRPTWMF.zip`。C17 按 basename 平铺保存，但原始目录标签和 Dataverse file ID 已在其 `SOURCE.md` 中保留。

顶层库存说明见 `data/ExternalCandidates_20260804/README.md`。这些文件只下载和封存，未解析、未转换、未解压、未生成算例、未进入任何代码或正式实验输入。

### FACT：明确排除清单

下列 12 个候选逐一排除，均未下载：

| 候选 | 排除理由 |
|---|---|
| C03 Meituan–INFORMS TSL | CC BY-NC 4.0，且 `License.txt` 明确附有“未经许可不得向第三方再分发”条款。 |
| C04 Shanghai VRPTW/MDVRPTW | 文章为 CC BY 4.0，但 GitHub 数据目录无独立 LICENSE；不能把文章许可扩大到数据目录。 |
| C05 大连水产品 25 单 | 需要作者授权，许可未声明，且只有网页图片/OCR 表格，没有直接机器可读数据文件。 |
| C06 Solomon VRPTW | 可公开下载，但数据许可证未声明。 |
| C07 Gehring & Homberger | 可公开下载，但数据许可证未声明。 |
| C08 Cordeau MDVRPTW | 数据页未声明许可证，不能推定允许再分发。 |
| C09 Uchoa X/CVRPLIB | CVRPLIB/DIMACS 未声明统一数据许可证。 |
| C10 Schneider E-VRPTW | CC BY-NC 3.0，含非商业限制。 |
| C12 Montoya E-VRP-NL | DIMACS/VRP-REP 数据许可未声明。 |
| C13 Froger E-VRP-NL-C | DIMACS/VRP-REP 数据许可未声明。 |
| C14 Amazon Last Mile | CC BY-NC 4.0，含非商业限制。 |
| C16 EVRP-TW-D | 虽为 CC BY 4.0 且有直接下载，但唯一压缩包 `EVRP-TW-D-B-v1.0.tar.gz` 为 527,733,122 bytes，超过 200 MB 上限。 |

完整机器可读清单见 `docs/handoff/housekeeping_20260804/inventory.json`。

### INFERENCE：库存边界

本次入库仅表示满足本任务筛选规则并完成原始文件封存，不表示数据已经适配 ReSETP 模型，也不表示可以直接作为正式实验输入。任何后续使用仍需用户另行批准；本任务没有作字段转换、算例生成或实验接入。

### HALT

测试环境没有触发停止条件；下载端点没有失败；已入库候选没有许可或再分发疑问。没有活动中的 HALT。被排除候选按各自理由停止处理，未下载。

## 共同产物

本目录包含：

- `report.md`：本报告。
- `test_failures.json`：三个失败的名称、错误类型、历史登记位置、T4 相关性和判断依据。
- `inventory.json`：5 个入库候选和 12 个排除候选及理由。
- `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`：本任务记录四件套；`search_evaluations` 为 0。

任务级 `artifact_hashes.json` 排除了 `._*`、`__pycache__`、`.pytest_cache`、库存目录下原始数据文件本体以及其自身；原始数据本体的 SHA-256 只记录在各自 `SOURCE.md` 中。

