# 2026-07-19 机制路线仓库增量门任务卡

目标：

在不改正式求解器和模型裁判的前提下，检验一个很窄的问题：HGS 与
ALNS 各自给出的完整模型可行路线，交给同一组 ReSETP 机制专家处理后，
再用精确集合划分拼接，能否严格优于两个父解。

输入：

- 旧多车场开发题只用于筛错，不用于确认或论文胜负；
- HGS 中性适配输出只叫 `hgs_adapter_route_source`，不叫完整模型纯 HGS；
- 项目 ALNS 输出叫 `alns_route_source`；
- 机制专家固定为跨车场责任、车型--补能、固定时长低碳择时。

要读的事实源：

- `HANDOFF.md`
- `docs/handoff/algorithm_hgs_alns_fusion_reset_20260719.md`
- `docs/handoff/algorithm_source_and_license_register_20260719.md`
- `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/v7_responsibility_solver.py`
- `baselines/algorithm_prototypes/algo_reset_20260719/exact_route_pool_recombiner.py`

允许改的文件：

- `baselines/algorithm_prototypes/algo_reset_20260719/`
- 本任务的五件套证据
- 本轮交接与 memory 记录

禁止改的文件：

- `solver/src/setp_solver/cost.py`
- `solver/src/setp_solver/check.py`
- `solver/src/setp_solver/search/evaluation.py`
- 历史证据目录与历史算法版本
- China81 并行工作文件

命令：

先跑单测和预算 0 功能门，再只跑预先固定的多车场 25c、50c，seed=1。
不得看结果后换题、改仓库大小、改筛选分数或扩大种子。

验收：

- 精确拼接解恰好覆盖全部客户且完整检查零违规；
- 拼接结果必须真实选用 HGS 与 ALNS 两个来源；
- 经完全相同机制专家处理后，拼接结果必须严格优于两个父解；
- 输出 `metadata.json`、`raw_runs.csv`、`decision.json`、
  `artifact_hashes.json`、`report.md`。

停止条件：

- 两个预登记题均未出现“真实混合且严格双胜”，立即停止该路线仓库方向；
- 任何完整复算不闭合、预算或来源账不清，立即 HALT；
- 旧题只允许给出开发信号，不得据此扩成正式胜负主张。

产物：

`baselines/algorithm_prototypes/algo_reset_20260719/mechanism_route_pool_incremental_gate/`
