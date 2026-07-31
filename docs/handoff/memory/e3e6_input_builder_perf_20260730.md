# E3/E6 输入构造性能攻坚中间状态（2026-07-30）

## 权威状态

- 任务边界仅为输入责任映射和未分车型 First-Fit 路线骨架；正式效果搜索 0，完整候选目标评价 0。
- 最终 C++ 构造器在历史 56 单元上的逐单元等价核验为 56/56 一致、0 不一致；历史产物按文件 SHA-256 字节复用。
- 135 个单元已有 106 个权威终态，其中 13 个为严格 `INFEASIBLE_INPUT`；29 个未终态。
- PGID 7965 下有 8 个 150/200c、50% 高负载单元持续精确运行，另 21 个排队。高 CPU、低 RSS、无输出不是崩溃或不可行证书。
- 因任务二未完成，`docs/handoff/e3e6_input_builder_perf_20260730/done.json` 尚未写。不得把中间状态写成 `COMPLETE`。

## 方法结论

- 给定完整责任映射后，冻结 `due/ready/id` 顺序 First-Fit 是确定性多项式构造，不需要 Z3。
- 在每个改派客户的多个目的场选项中寻找词典序最小且完整 First-Fit 路线数不超 D2-A 上限的映射，仍是组合存在性问题。第 2029 行旧 Z3 任意路线槽分区比冻结 First-Fit 语义更宽，不是等价实现。
- 新构造器不使用 Z3，严格重放冻结 First-Fit，并由现有 Python `_pack_depot` 独立复核；常规已知卡点 `cn-prd-150c-01/50%` 从原 C++ 25.437438 秒降至 5.896163 秒，映射、路线组和搜索计数一致。
- 不得未经用户批准把精确存在性改成逐客户贪心、任意可行路线分区、有限超时 `UNKNOWN` 或放宽车队上限。

## 完整证据

主报告：`docs/handoff/e3e6_input_builder_perf_20260730/report.md`

机器可读中间状态：`docs/handoff/e3e6_input_builder_perf_20260730/interim_status.json`

输入构造目录：`baselines/china_e3_e7/e3e6_inputs_20260730/`

## 后续状态（2026-07-30）

期刊对齐合同
`docs/handoff/experiment_contract_v2_journal_aligned_20260730.md`
已整体取代本任务服务的 0/25/50% 错配扫描。接手时 PGID 7965 已不存在；本目录和
旧输入目录均保持不改。29 个未终态单元已在
`baselines/china_e3_e7/e3_structural_20260731/superseded_units.csv`
登记为 `NOT_BUILT_SUPERSEDED_DESIGN`，明确不是 `INFEASIBLE_INPUT` 或技术失败。
后续结构性三臂输入、正式批技术 HALT 与证据边界见
`docs/handoff/memory/e3_structural_20260731.md`。
