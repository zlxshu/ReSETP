# Z1 阻塞项代码修复与全链回归报告

日期：2026-08-02  
终态：`HALT_FULL_TEST_SUITE_5_FAILED`  
是否运行正式实验或路径搜索：否

## 一、结论

四个指定阻塞项均已在授权边界内处理，三个受保护文件没有改动。Z1 新增及直接相关门禁 37/37 通过；E4 30 份与 E6 30 份保存解在显式多趟关闭配置下全部逐位重放一致，在显式多趟开启配置下全部生成合法证书并通过完整检查。

但用户把“全量既有测试全部通过”列为三项回归之一，并规定任一回归失败就必须 HALT。规范全量 `solver/tests` 最终为 **901 passed、1 skipped、5 failed**。因此本任务不能写 `Z1_BLOCKER_FIX_COMPLETE`，不能开始新实验改造，也没有为通过而放宽任何断言。

## 二、开工边界与输入锁定

开工前已完整读取 `docs/handoff/legacy_sweep_20260802/legacy_ledger.json` 与 `docs/handoff/legacy_sweep_round2_20260802/legacy_ledger_round2.json`，SHA-256 分别为 `78c73657...2d56b01` 与 `e678744c...586d7e6`。开工提交与收口提交均为 `850cea5f3d3e11a21e073a7c1a45477a65a7a66f`；工作树在开工前已经非干净，本轮只做精确补丁并保留其他已有及并发改动。

本轮没有删除文件、移动目录、覆盖既有实验结果目录，也没有启动正式实验或路径搜索。外置卷自动产生的 `._*` 旁车没有纳入任何哈希；由于任务明确禁止删除文件，本轮也没有删除这些旁车。

## 三、四项修复

### 1. X2-PD-003：显式模型配置，默认开启

根因是 `e3_multitrip_runtime.enabled()` 直接读取 `SETP_E3_STRICT_MULTITRIP` 且缺省为 `0`，主线在没有任何产物记录的情况下可能静默落回单趟 scorer。同一环境读取还散落在 ALNS 内核与修复算子中。

新增 `solver/src/setp_solver/model_config.py`，定义 `ModelConfig(strict_multitrip=True)`、上下文隔离的配置域、机器可读 `as_metadata()`，以及只供历史边界使用的环境变量转换器。求解器内部不再直接读取多趟环境变量；当前源码内该变量只在兼容模块出现一次。中国内存主入口 `run_winner_kernel_in_memory` 要求显式传 `model_config`，未传即抛出 `MissingModelConfigError`；返回的 `AlnsRunResult.model_config` 保存实际取值，供实验写入 `metadata.json`。本目录 `metadata.json` 同时写明关闭与开启两次重放的配置。

旧 China81 原型包没有被强制迁移到新默认。其两个入口显式调用 `legacy_model_config_from_environment()`，因此历史缺省仍为 0，旧的 0/1 值仍按原逻辑解释。这把兼容性限制在旧入口，而不是让新主线静默继承旧默认。

证据是主线缺配置时报错测试、默认值为真测试、旧 0/1 映射测试、返回 metadata 测试，以及 60 份双配置保存解重放。

### 2. X2-PD-001：中国入口不再回退英国价格

根因是底层循环仍允许 `prices=None` 并使用 `DEFAULT_PRICES`。该对象保留 Goeke/UK 的 3650 kg、80 kWh、GBP 价格及固定费等历史口径；若中国入口漏传，就会悄悄采用英国参数。

本轮没有修改 `prices.py`，其 SHA-256 前后均为 `36049112...dcb96`，英国历史 factory 得以保留。中国内存主入口现在在进入任何构造、评分或搜索前检查 `prices`，缺失即报 `China mainline in-memory entry requires explicit scenario prices`。现有三个非冻结调用点均显式传入 `bundle.prices`；测试覆盖缺失价格的 fail-closed 行为。

### 3. X2-RI-003：中性共享充电动作构造

根因是正式包 `algorithms/resetp_alns/support/charging.py` 反向导入历史目录 `search.charging._curve_aware_action`，使正式实现依赖历史实现的私有符号。

本轮把函数体原样提升到 `solver/src/setp_solver/charging_action.py`。历史 `search.charging` 与正式 `support.charging` 都直接导入这一中性实现；正式文件对 `setp_solver.search.charging` 已零命中。测试同时断言两层获得的是同一个函数对象，并验证能量、起止 SOC、占用时长与曲线标识字段。没有调整曲线、浮点截断、边界容差或异常行为。

### 4. X2-PD-002：18 槽埋雷登记与调用点门禁

`cost.py:73` 的 `n_slots=None -> 18` 是未来非 18 槽场景的静默风险，但用户禁止修改该文件。本轮仅把历史锚点测试改成显式 `n_slots=CARBON_N_SLOTS`，新增 `solver/tests/test_carbon_slot_call_contract.py`，以 AST 扫描仓库 Python 调用点并要求每一处都有关键字参数 `n_slots`。风险、建议签名和未来 HALT 条件登记在 `docs/handoff/carbon_slot_explicit_parameter_risk_20260802.md`。

## 四、回归证据

### 4.1 Z1 定向门禁

最终命令使用规范 Python/依赖路径，结果为 `37 passed in 33.76s`。覆盖显式配置、主线 fail-closed、共享充电依赖、碳时段调用契约、碳锚点、多趟排班与公共站多趟运行时。

代码审计技能扫描 143 个求解器源码文件，报告 0 critical、4 high。四条 high 均把 `ValueError("No feasible charging insert between ...")` 的英文错误消息误识别为 SQL 拼接；两个文件没有 SQL 执行，故判为静态规则误报。没有为消除误报修改数值代码。

### 4.2 多趟关闭的零搜索逐位重放

从 E4 的 90 份保存解和 E6 的 900 份保存解中，按排序记录号覆盖首尾并等距选取各 30 份。每份在 `ModelConfig(strict_multitrip=False)` 的显式配置域内重算目标值及 13 个关键分项：`cost_fix`、`cost_km`、`cost_fuel`、`cost_elec`、`cost_occ`、`cost_transship`、`E_cv_direct`、`E_ev_indirect`、`E_total`、`distance_total`、`electricity_kwh`、`n_veh_cv`、`n_veh_ev`。

结果为 E4 30/30、E6 30/30 全部按 binary64 逐位一致，违反数为 0，没有 mismatch 字段。逐份原值、现值、SHA-256 和选择索引见 `raw_runs.csv` 与 `replay_details.jsonl`。

### 4.3 多趟开启的可用性

同一批 60 份保存解在 `ModelConfig(strict_multitrip=True)` 下构造排班证书。E4 30/30 为 `PASS_E4_MULTITRIP_SOC_INTERFACE`，E6 30/30 为 `PASS_E6_MULTITRIP_COMPLETE_CHECK`；60/60 证书有效、60/60 接口可直接使用、完整检查违反数为 0、车场车队上限违反数为 0。没有失败原始原因；所有证书和完整检查明细保存在 `replay_details.jsonl`。

### 4.4 全量既有测试

权威命令为：

```text
PYTHONPATH=solver/src:models/src:.:/opt/anaconda3/lib/python3.13/site-packages:build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests -q
```

环境为 Python 3.13.9、NumPy 2.3.5、PyVRP 0.12.2。最终结果为 **901 passed、1 skipped、5 failed，耗时 300.79 秒**。失败清单如下：

1. `solver/tests/test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`。当前分支八个语义文件均不同于历史 commit `40bd2883...`；本轮没有修改这八个文件中的任何一个，因此保留该历史合同失败。
2. `solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`。碳感知臂仍不合法。
3. `solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`。至少一个翻转仍被诊断为 `repair_logic_defect`。
4. `solver/tests/test_external_baseline_freeze_builder_20260717.py::test_candidate_probe_is_bound_to_current_adapter`。冻结 probe 的源码哈希与当前 probe source 不同；本轮没有修改该 probe。
5. `solver/tests/test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`。E4 全局 manifest 对五个现行源码报漂移，其中包含本次授权修改的 `e3_multitrip_runtime.py`，也包含本轮未改的 `cost.py`、`check.py`、`multitrip_schedule.py` 与 `formal_runner.py`。任务禁止覆盖既有实验结果目录，因此没有改写旧 manifest。

裸仓库根 `pytest -q` 曾在执行前因 vendored 第三方测试与缺失依赖产生 132 个 collection error；随后两个试跑又分别暴露 PyVRP 缺失和封存 venv 的 NumPy 2.5.1 污染。这些都没有冒充全量结果。最终通过显式把系统 site-packages 放在封存 PyVRP site-packages 前面，固定了上面的权威环境与结果。

## 五、受保护文件

三条命令结果均为退出码 0：

```text
git diff --quiet -- solver/src/setp_solver/cost.py                 # 0
git diff --quiet -- solver/src/setp_solver/check.py                # 0
git diff --quiet -- solver/src/setp_solver/search/evaluation.py    # 0
```

三文件开工前后 SHA-256 分别恒为 `7f59a47a...77333`、`86b81315...702b`、`c7215263...fc3`。没有触发 `HALT_NEEDS_PROTECTED_FILE_CHANGE`。

## 六、`git diff --stat` 全文

以下为 2026-08-02 17:14（Asia/Singapore）执行 `git diff --stat` 的完整标准输出。工作树开工前已非干净，且存在并发记录与监控日志写入，因此该输出是整个工作树快照，不等于 Z1 独占改动；未跟踪的新文件按 Git 命令本身的规则不出现在其中。

```text
 HANDOFF.md                                         | 1084 ++++++++++++++++++++
 .../china81_mechanism_hybrid_20260720/hybrid.py    |    2 +
 .../run_adapter_g0.py                              |    3 +
 ...ose_saved_solution_multitrip_repack_20260801.py |  604 ++++++++++-
 .../e4_joint_routing_20260801/joint_soc_wrapper.py |   19 +
 docs/handoff/RESUME_HERE_20260802_diagnosis.md     |    9 +-
 ...eriment_contract_v2_journal_aligned_20260730.md |    9 +
 docs/handoff/memory/MEMORY.md                      |   43 +
 ...odex_audit_independent_verification_20260802.md |   65 +-
 .../model_change_approval_register_20260718.md     |    8 +
 .../algorithms/resetp_alns/kernel/alns_core.py     |    6 +-
 .../algorithms/resetp_alns/kernel/winner.py        |   26 +-
 .../resetp_alns/operators/feasible_repair.py       |    3 +-
 .../algorithms/resetp_alns/support/charging.py     |    2 +-
 .../setp_solver/search/certificate_execution.py    |    6 +-
 solver/src/setp_solver/search/charging.py          |   47 +-
 .../src/setp_solver/search/e3_multitrip_runtime.py |  127 ++-
 .../src/setp_solver/search/multitrip_schedule.py   |  618 ++++++++++-
 solver/tests/test_carbon_gate.py                   |    6 +-
 .../test_china81_in_memory_winner_20260720.py      |   28 +
 solver/tests/test_multitrip_schedule.py            |  122 ++-
 tools/claude_quota_watchdog/daemon.log             |  977 ++++++++++++++++++
 tools/claude_quota_watchdog/state.json             |  357 ++++++-
 tools/claude_quota_watchdog/watchdog.log           |  977 ++++++++++++++++++
 24 files changed, 5000 insertions(+), 148 deletions(-)
```

## 七、停止与下一步边界

本轮停止原因不是 60 份双配置重放失败，而是全量测试仍有 5 个失败。根据用户原始停止条件，`done.json.status` 必须为 `HALT_FULL_TEST_SUITE_5_FAILED`。在这五项逐一通过或由用户另行改变回归合同以前，不得把 Z1 升级为 COMPLETE，也不得据此启动新实验改造。
