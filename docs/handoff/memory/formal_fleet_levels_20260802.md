# XB 车队电动化五档正式实验（2026-08-02）

> ⚠️ **2026-08-03 结论待重估**：本文件的实验走 China81 MV-HGS-SP 求解路径，
> 该路径已确诊缺陷——PyVRP 代理问题不施加每车场实体车数上限，HGS 候选补全时被全数拒绝
> （异常在 `epochal_hgs.py:532-543` 静默吞掉），最终解恒为共同初始解，
> **随机种子与迭代预算对结果均无影响**。凡本文件中涉及算法性能、判别力、
> 臂间差异、"最优解"的表述一律以
> [solver_completion_reject_root_cause_20260803.md](solver_completion_reject_root_cause_20260803.md)
> 为准；受影响范围的逐包判定见 `docs/handoff/asset_audit_20260803/`。修复后须重跑。

## DECISION / terminal

- 权威结果目录：`baselines/china_e3_e7/formal_fleet_levels_20260802/`。
- `metadata.json` / `decision.json` / `done.json` 终态均为
  `XB_FLEET_LEVELS_FORMAL_COMPLETE`。
- 完成 50/50 个预注册单元（0/25/50/75/100% × 种子 1--10）；
  每个单元固定执行 `COST_ONLY` 和 `COST_PLUS_CARBON` 两臂，共 100 个 arm 尝试。
- 正式实例为 `cn-prd-100c-01-V2-LOCATIONS`。选例规则在第一次搜索前写入
  `preregistration.json`：保留论文主区域 PRD，使用符合 51--149 客户范围的
  `-01` 100 客户复制，不读取历史结果排名。

## FACT / frozen contract

- 严格多趟开启；固定成本按去重实体车计费，`c_fix=170`；登记号
  `MC-W1-F2-DEPOT-CONCURRENCY-01`；车场充电并发 `unbounded`。
- authority 为 `china81_finite_fleet_authority_v3_20260802`；全 81 实例总量 943，
  本实例五档总量均为 13，Hamilton 分配依次为
  `13/0`、`10/3`、`6/7`、`3/10`、`0/13`（CV/EV）。
- HGS 每个原生视角的停止条件为最先到达 2000 迭代或连续 150 次无改善。
  墙钟保险不是合法科学停止；若触发只能记技术 HALT。
- git commit 为 `850cea5f3d3e11a21e073a7c1a45477a65a7a66f`；源码树 SHA-256 为
  `b73b05e8131847f16107f0a0c745cf8e358d4232a0c35618cbfb1e988fc82b73`。
- 正式并行后端为 3 个独立 Python 子进程。这只是因受管 macOS 沙箱拒绝
  `SC_SEM_NSEMS_MAX` 而替代 `ProcessPoolExecutor`，没有改变单元、种子、搜索、停止或复核合同。

## FACT / five-level results

| EV 档位 | 可用 CV/EV | 可行配对 | 实派 CV/EV（碳感知均值） | 实体车/路线 | 相对碳盲排放差 | 充电/车型/路线改变 | 违反项 |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0% | 13/0 | 10/10 | 10/0 | 10/16 | 0 | 0/0/0 | 无 |
| 25% | 10/3 | 10/10 | 7/3 | 10/16 | 0 | 0/0/0 | 无 |
| 50% | 6/7 | 10/10 | 4/6 | 10/16 | 0 | 0/0/0 | 无 |
| 75% | 3/10 | 0/10 | NA | NA | NA | 0/0/0 | 广州车场 `overage=(2,0,0)` |
| 100% | 0/13 | 0/10 | NA | NA | NA | 0/0/0 | 广州车场 `overage=(3,0,0)` |

- 0/25/50% 档的碳感知与碳盲解在三个登记决策层都没有变化；
  25% 档运营成本差的 `4.547473508864641e-13` 是 binary64 舍入噪声，排放差为 0。
- 碳感知均值：0% 档运营成本 4120.089913814464 元、系统排放
  490.3455438542953 kg；25% 档为 3597.1597161778627 元、325.38245253188006 kg；
  50% 档为 3421.19395714174 元、255.6862152772453 kg。
- 75% 和 100% 是 `INFEASIBLE_OR_NOT_FOUND`，不是全局不可行证明；准确边界是：
  登记的 MV-HGS-SP 共享 completion 在真实 v3 上限下未能构造合法完整解。
  W2 的 405/405 零搜索 authority 认证只是车队/见证路线可用性证据，不得改写为正式搜索的全检查可行性。

## DECISION / preregistered claim check

- 触发 `FALSIFIER_NO_DECISION_RESPONSE`、`FALSIFIER_NO_CROSS_LEVEL_LAYER_SHIFT`和
  `FALSIFIER_SERVICE_OR_FEASIBILITY_CONFOUND`；未触发 `FALSIFIER_SCORE_ONLY_DIFFERENCE`。
- 论文 5.2 拟支撑的“时变碳强度着力点随可替代运力变化，且变化发生在充电/车型/路线某层”
  被本次预注册否定条件拒绝：
  `NOT_SUPPORTED_BY_ONE_OR_MORE_REGISTERED_FALSIFIERS`。
- 不得改写为“电车越多越低碳”，也不得将 75/100% 删除后只报三个可行档。

## FACT / evidence verification

- `raw_runs.csv` 50 行主键唯一；`arm_runs.csv` 100 行；`fleet_level_summary.csv` 5 行。
- 30 个可行配对保存 60 份完整 arm 解；20 个不可行/未找到单元保存两臂失败记录、
  完整的登记初始 solution witness、`registered_initial_solution_sha256`和
  `failure_evidence_sha256`。因不存在完整可行终解，这 20 个文件不得称为“完整可行双臂解”；
  原 `report.md` 证据边界中“每个配对单元的完整双臂解”应按本段限定理解。
- 独立终验：50 个 solution/evidence SHA、50 个 worker receipt、100 个 arm 和 157 个 artifact 哈希全部闭合；
  60 份可行 arm 解重新送入当前 checker/evaluator，60/60 零违反、成本逐项一致；
  30 个配对的决策层变化计数重放一致。实体车固定成本逐 arm 均满足
  `cost_fix = 170 × used_total`。
- `artifact_hashes.json` 不包含 `._*`、`__pycache__`或 `.pytest_cache`；157 个登记项重算零不匹配。
  `decision.json` SHA-256 为 `343b196f24767d5a95b7e05bdb276ed5466fb258a54a8010c04aa7fc77021b3a`；
  `artifact_hashes.json` SHA-256 为 `19f1ff6f82725e4a66d41c8502a472237daea24f615f3e833e890874e3c9a28b`。
- 定向回归 103 passed；`paper_main.tex`、`check.py`、`search/evaluation.py` 未改。

## HALT / operational scenes retained

- 第一个监控场景因受管沙箱无法 `ps` 而在创建正式目录前误暂停；
  现场保留在 `.xb-formal-fleet-levels-20260802.monitor/`。暂停 PID 71369 无科学输出，
  当前沙箱无权对其发送恢复/终止信号；若外部恢复，runner 会因正式目录已存在而 fail-closed。
- 第二个场景在 0/50 时因 `SC_SEM_NSEMS_MAX` 权限错误终止；零结果目录已原样保留为
  `formal_fleet_levels_20260802_presearch_halt_sem_nsems_max/`，监控现场为
  `.xb-formal-fleet-levels-20260802.monitor-v2/`。
- 权威完成监控场景为 `.xb-formal-fleet-levels-20260802.monitor-v3/`。
- `progress.json.status=RUNNING` 是最后一帧运行期快照，不是终态权威；终态只读
  `done.json` / `decision.json` / `metadata.json`。
