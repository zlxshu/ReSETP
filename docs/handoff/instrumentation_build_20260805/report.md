# T22 仪表与接线收工报告

`T22_INSTRUMENTATION_BUILD_COMPLETE`

## FACT

本轮只建立仪表、参数接线与独立 runner，没有运行 3 算例 × 3 臂 × 10 种子的批次。唯一一次真正进入搜索的冒烟为 `cn-jjj-100c-01-V2-LOCATIONS / COST_CARBON / 2026080201`，三个视角各 60 次迭代，总计 180 次；`paper_claim_allowed=false`。

全局 HGS 安全墙钟现在为可选项。确定性迭代模式在 `wallclock_safety_seconds` 缺失或非正时不追加墙钟停止器，传入正值时才追加；默认路径记录为 `DETERMINISTIC_ITERATIONS_NO_WALLCLOCK`。同步删除的只有本任务批准的同一组校验：`epochal_hgs.py` 内“确定性迭代必须有正墙钟”、`route_pool_sp.py` 内重复的同类校验，以及检查点对硬迭代上限存在性和整除性的依赖。检查点间隔必须为正、历史档案必须有检查点等其余校验保留。没有搬移、删除或弱化其他既有 `raise`、`assert` 或校验分支。

`_CheckpointGeneticAlgorithm` 在原有 `current_best/new_best` 比较处直接记录代理目标改善事件，字段为视角、迭代号、改善前值、改善后值和绝对改善幅度；没有为此新增完整模型评价。路线池按视角输出检查点、实际迭代数、停机模式、停机原因、墙钟启用/触发状态和改善轨迹。本轮没有接入任何自动“长期平缓”停机分支。

`charge_timing_policy` 已从两个 HGS/路线池入口贯通到 `complete_china81_route_skeleton()` 的既有策略入口。策略实现文件和 `china81_completion.py` 未修改，默认值仍是 `carbon_min`。`depot_charge_window_mode`、`public_station_candidate_mode`、首趟跨日口径、碳价与 `_TOL` 未改。

路线池每次 `scipy.optimize.milp` 调用现在单独用 `perf_counter()` 计量实际耗时，并记录初始/最终时限、是否触及时限、是否在时限前完成、incumbent 是否存在、是否延长及延长次数。当前 SciPy 1.16.3 的 `milp` 签名只有 `options`，其实现于 `/opt/anaconda3/lib/python3.13/site-packages/scipy/optimize/_milp.py:374` 单次调用 `_highs_wrapper`，随后在 `:394` 返回 `OptimizeResult`；没有 incumbent callback 或可继续求解句柄。因此本轮没有伪造延长机制：`extension_supported=false`、`incumbent_trace_supported=false`、`extension_count=0`，并保存不可实现原因。

新 runner 为 `baselines/china_e3_e7/run_t21_charging_timing_three_arms_20260805.py`。其冻结清单是 3 个 100 客户算例 × `asap/cost_min/cost_plus_carbon` × 10 个登记种子，共 90 个单元；`preregistration.json` 在结果前写入第三节六项。runner 输出逐运行读数、逐车场 48 槽分布、规范化路线/指派/有向弧签名、逐改善轨迹、MIP 用时审计、配对的层内和总量百分比、改善/变差/持平计数、代表性反例与完整 solution witness。历史正式 runner 没有修改。

冒烟原始输出位于 `smoke_raw/`。本次成功冒烟记录了 10 条改善事件，各视角内迭代号严格递增；96 行槽位记录对应 2 个车场 × 48 槽；MIP 实耗 `0.8706315840827301` 秒，初始/最终时限均为 10 秒，未触及时限、未延长。MIP 中间候选状态原样为 `REJECTED_COMPLETE_MODEL_VIOLATIONS`；最终完整解另行通过验解，违反数为 0，不能把两者混为一个状态。

最终完整解完成客户 `100/100`，完成需求 `25972.0/25972.0`，搜索目标与完整评价均为 `4121.404744908565`，闭合误差为 `0.0`。策略入口夹具得到起始时刻：`asap=0.0` 秒、`cost_min=1800.0` 秒、`cost_plus_carbon=5400.0` 秒，三个取值均可选且互异。所有 runner 必录运行字段都有值。

第一次冒烟启动在进入搜索前因脚本同目录的 `statistics.py` 遮蔽标准库而失败，最终异常为 `ModuleNotFoundError: No module named 'baselines'`；没有创建输出目录，也没有开始搜索。新 runner 随后隔离脚本目录，成功冒烟退出码为 0。另有两次测试/编译相对路径错误和一次初始 pytest 收集路径错误，均在 `smoke_command_log.txt` 原样登记；它们没有测试用例执行结果，未被包装成“正确拒绝”。

聚焦回归最终为 `20 passed in 5.60s`。solver 全量回归为 `906 passed / 1 skipped / 6 failed in 405.87s`，与既有六项的节点及断言值一致：

1. E2 冻结合同实际 `HALT_FROZEN_PROTECTED_CONTRACT`，期望 `FROZEN_PROTECTED_CONTRACT_OK`。
2. E5 R1 的 `carbon_aware.feasible` 实际为 `False`。
3. E5 R2 至少一行 `root_cause` 实际为 `repair_logic_defect`。
4. EV-heavy 的 `candidate_obj=4954.208671718898`，不小于 `initial_obj=4923.557583344485`。
5. E4 全局清单仍有 `multitrip_schedule.py` 与 `check.py` 两项哈希漂移。
6. Strong-bridge 实际 `HALT_STRONG_BRIDGE_BACKEND_PROFILE_ALIGNMENT`，期望 `A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED`。

三个受保护文件开工/收工 SHA-256 逐位一致：`cost.py=e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`、`check.py=1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`、`search/evaluation.py=c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。`china81_completion.py` 收工哈希仍为开工值 `cb0bb62eeba2ad6ebc92d39ecf36a2aa2592b11f1f6a02abd53b2cdcc34bffe9`。产物清单排除 `._*`、`__pycache__` 和 `.pytest_cache`。

## INFERENCE

冒烟证明本轮新增的轨迹、策略接线、MIP 用时与 runner 物化链能够工作；它不证明三个实验臂的科学效果。当前 MIP 后端证据只支持“实际耗时与提前结束可记录”，不支持“到点仍改善则延长”。

## DECISION

`paper_claim_allowed=false`。本轮状态只表示 T22 仪表与接线完成，不把冒烟或策略夹具升级为实验结果，也不登记“长期平缓”窗口。

## HALT_*

无新增 HALT。既有六个 solver 失败按原节点和原值保留。
