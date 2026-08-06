# T6-HOUSEKEEPING（2026-08-04）

## FACT

- 全量 `solver/tests` 在指定 Python/pytest 环境中完成，结果为 `909 passed / 3 failed / 1 skipped`；测试环境可用。
- 三个失败为 `test_e5_ablation.py` 的 R1/R2 和 `test_ev_heavy_findability_gate.py` 的 vehicle-type-swap 断言。三个完整名称均已在仓库既有 handoff/memory 登记，本次没有修复测试、修改测试或修改源码。
- 逐项核对测试导入链和被测函数后，三个失败都未触及 T4 修改的 `pyvrp_adapter.py`、`epochal_hgs.py`、`route_pool_sp.py`、`run_adapter_g0.py`、`test_pyvrp_adapter.py`。
- 17 个候选中仅 C01、C02、C11、C15、C17 满足明确 CC BY 4.0、直接数据文件和 200 MB 压缩体积边界，已封存 52 个原始文件；12 个候选未下载并逐项记录理由。

## INFERENCE

在本次静态导入链核查边界内，三个测试失败与 T4 修改无关。候选目录是未使用库存，不是正式实验输入，不进入算例生成链路。

## BOUNDARY

权威任务记录为 `docs/handoff/housekeeping_20260804/report.md`、`test_failures.json`、`inventory.json`、`metadata.json`、`raw_runs.csv`、`decision.json` 和 `artifact_hashes.json`。候选原始数据只下载、哈希和封存，未解析、转换、解压或接入代码；使用前须另行获得用户批准。
