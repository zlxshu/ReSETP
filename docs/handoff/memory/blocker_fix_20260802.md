# Z1 阻塞项代码修复与全链回归（2026-08-02）

## 终态

`HALT_FULL_TEST_SUITE_5_FAILED`。四个指定阻塞项均已在边界内完成，Z1 定向门禁与两类保存解重放全部通过；但用户规定“任一回归项失败即 HALT”，规范全量测试仍有 5 项失败，因此不得写 `Z1_BLOCKER_FIX_COMPLETE`，也不得开始新实验改造。

## 已完成的代码边界

`X2-PD-003`：新增 `solver/src/setp_solver/model_config.py`。`ModelConfig()` 默认开启严格多趟；中国内存主入口要求显式 `model_config`，缺失即抛出 `MissingModelConfigError`。运行结果携带 `model_config` 字典，可直接写入实验 `metadata.json`。历史 China81 原型入口把旧环境变量的 0/1 值显式转换成配置对象，保留旧包语义。

`X2-PD-001`：中国内存主入口要求显式传入场景 `prices`，缺失即报错，不再回退英国 `DEFAULT_PRICES`。`prices.py` 未改，英国历史 factory 仍可供旧包复现。

`X2-RI-003`：原 `_curve_aware_action` 原样提升到中性模块 `solver/src/setp_solver/charging_action.py`；正式实现与历史实现都直接依赖该模块，正式包不再反向导入 `search.charging`。

`X2-PD-002`：受保护 `cost.py` 未改。风险、未来建议改法与 HALT 条件登记在 `docs/handoff/carbon_slot_explicit_parameter_risk_20260802.md`；新增 AST 测试确保仓库调用点显式传 `n_slots`。

## 回归事实

定向门禁：37 passed。代码审计扫描 143 个求解器源码文件，报告的 4 个 high 均把错误消息 `No feasible charging insert ...` 误识别为 SQL；对应文件没有 SQL 执行，判静态规则误报，未为消警改动数值代码。

零搜索重放：从 E4 的 90 份与 E6 的 900 份保存解中各确定性分层抽取 30 份。显式关闭多趟时，60/60 的目标值与 13 个关键分项均按 binary64 逐位一致；显式开启多趟时，60/60 均有有效证书、完整检查零违反、场站车队上限零违反。没有启动路径搜索或正式实验。

规范全量测试命令使用系统 Python 3.13、NumPy 2.3.5，并从仓库封存环境补充 PyVRP 0.12.2。结果为 901 passed、1 skipped、5 failed。失败包括旧 E2 冻结合同漂移、两项 E5 既有失败、外部 candidate probe 源码哈希漂移，以及 E4 全局 manifest 与现行源码漂移。最后一项会包含本次授权修改的 `e3_multitrip_runtime.py`，而任务禁止覆盖既有实验结果，故保留失败证据并 HALT。

## 证据入口

权威目录：`baselines/china_e3_e7/blocker_fix_20260802/`。`raw_runs.csv` 每个保存解一行；`replay_details.jsonl` 保留完整证书与逐位比较明细；六件套给出源码前后哈希、测试清单、判决、受保护文件门禁及目录哈希。
