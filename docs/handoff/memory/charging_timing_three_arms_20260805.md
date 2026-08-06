# T21 充电时刻三条线跑前合同 HALT（2026-08-05）

## 终态

`HALT_T21_RUNNER_CONTRACT_UNAVAILABLE_NO_SEARCH`。T21 预注册已在任何搜索结果前落盘，但现有入口与用户冻结合同冲突；按“必须改代码才能跑则停”的铁律，未启动搜索。权威产物为 `docs/handoff/charging_timing_three_arms_20260805/`。

## FACT

- 预期 manifest 为 3 算例 × 3 个 `charge_timing_policy` 臂 × 10 种子 = 90 次；实际运行 0，无科学结果，`paper_claim_allowed=false`。
- `epochal_hgs.py:198-216` 强制确定性迭代模式使用正的 HGS 墙钟安全条件；`route_pool_sp.py:162-168` 在多视角入口重复强制。
- `_CheckpointGeneticAlgorithm.run()` 能在内存中看到每次迭代的改善，但只持久化每 100 次的检查点，不能事后重建 T21 要求的逐改善轨迹。
- `_solve_set_partitioning()` 只把单一固定 `time_limit` 传给 `scipy.optimize.milp`，没有独立 MIP 实际用时、incumbent 改善轨迹、延长次数或提前结束留痕。
- 08-02 runner 硬编码为单一 PRD 算例、8 个算法/消融臂、4 worker、150 次无改善与 7200 秒安全墙钟，不是 T21 runner。
- 本轮未修改任何代码、算法行为、模型语义、审计器或论文目录。三个受保护文件前后哈希一致。

## INFERENCE

直接复用 08-02 runner 会产生错误的实验 manifest，且无法证明 T21 的停机口径、逐改善轨迹和 MIP 动态时限留痕。这不是只换命令行参数可以补齐的缺口。

## DECISION

未登记“长期平缓”窗口，未对任何结果作正确性或合理性判断，未将工具要求升级为用户科学决定。

## 恢复边界

证据包 `metadata.json` 已逐项列出为使冻结合同可执行而必须发生、但本轮没有执行的 runner/仪器化变更。这些变更不得在 T21 名下隐式实施。
