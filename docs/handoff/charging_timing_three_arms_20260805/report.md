# T21 充电时刻三条线探索批报告

`HALT_T21_RUNNER_CONTRACT_UNAVAILABLE_NO_SEARCH`

## FACT

本批没有启动任何搜索，因此实际运行数为 0/90，`raw_runs.csv`、`improvement_trace.csv` 与 `slot_distribution.csv` 只保留了完整表头，`solution_witnesses.json` 中证据数为 0。没有服务量、违反、目标值、充电槽位或收敛方向可供判定。`paper_claim_allowed=false`。

`preregistration.json` 已在任何结果产生前落盘，固定了三个算例、三个充电择时臂、10 个种子、配对单位、保持不变的因素、否定条件和探索批边界。

只读核验确认现有最终 HGS 入口无法在不改代码的前提下执行 T21：

1. `epochal_hgs.py:198-216` 对确定性迭代模式强制要求正的 `wallclock_safety_seconds`，并将它加入停机条件。`route_pool_sp.py:162-168` 在多视角入口再次强制这一要求。这与 T21 “除路线池整数规划外不设墙钟”直接冲突。
2. `_CheckpointGeneticAlgorithm.run()` 在 `epochal_hgs.py:960-976` 每次迭代都能看到 `current_best` 与 `new_best`，但没有将改善事件追加到返回统计；`epochal_hgs.py:977-989` 只在每 100 次迭代调用检查点回调。因此现有 `search_trace.json` 不能事后重建“每一次目标值改善”的迭代号、改善前值、改善后值和幅度。
3. `route_pool_sp.py:697-706` 只向 `scipy.optimize.milp` 传入一个固定 `time_limit`；返回统计只记配置时限，没有独立 MIP 实际用时、时限内 incumbent 改善轨迹、延长次数或“早已收敛则提前结束”的证据。
4. `formal_algorithm_20260802/run_xa_formal.py:87-138` 硬编码为单一珠三角算例、8 个算法/消融臂、4 个 worker、连续 150 次无改善与 7200 秒 HGS 安全墙钟，并非 T21 的“3 算例 × 3 充电策略 × 10 种子”入口。直接调用会跑错实验。

三个受保护文件开工前 SHA-256 为：`cost.py=e7ea406d...b00d`、`check.py=1cdb6236...1072`、`search/evaluation.py=c7215263...6fc3`。收工后完整值见 `metadata.json` 和 `artifact_hashes.json`。

## INFERENCE

若忽略上述缺口直接复用 08-02 runner，产物不能证明 T21 的停机口径、收敛轨迹、路线池 MIP 实际用时与延长状态，也不能证明三臂仅 `charge_timing_policy` 不同。所以这不是可以通过命令行换参数解决的缺口。

## DECISION

本任务未对实验结果作任何“正确”或“合理”判定，也未登记“长期平缓”的窗口。决策权保留给派活方与用户。

## HALT_T21_RUNNER_CONTRACT_UNAVAILABLE_NO_SEARCH

要使本批可执行，必须发生的变更包括：建立精确的 T21 任务 manifest 与产物物化入口；使确定性 HGS 迭代路径能够不使用全局墙钟；在现有 HGS 循环中保存每一次改善事件；为路线池 MIP 增加独立实际用时、改善轨迹和延长/提前结束留痕；从未改的完整评价器与验解器物化 T21 指定的全部读数。本轮按用户铁律没有执行这些代码或算法行为变更。

本轮未运行 solver 测试，未启动监控器，因为没有合同正确的可执行命令可以交给监控器。
