# SCOUT-D 多车场客户归属重分探路（2026-08-03）

> ⚠️ **2026-08-03 结论待重估**：本文件的实验走 China81 MV-HGS-SP 求解路径，
> 该路径已确诊缺陷——PyVRP 代理问题不施加每车场实体车数上限，HGS 候选补全时被全数拒绝
> （异常在 `epochal_hgs.py:532-543` 静默吞掉），最终解恒为共同初始解，
> **随机种子与迭代预算对结果均无影响**。凡本文件中涉及算法性能、判别力、
> 臂间差异、"最优解"的表述一律以
> [solver_completion_reject_root_cause_20260803.md](solver_completion_reject_root_cause_20260803.md)
> 为准；受影响范围的逐包判定见 `docs/handoff/asset_audit_20260803/`。修复后须重跑。

## 终态与权威入口

任务终态为 `SCOUT_DEPOT_PARTIAL_RANDOM_HALT_NEAREST_COMPLETE`。权威包位于
`baselines/china_e3_e7/scout_depot_ownership_20260803/`；根目录和
`baseline_random/`、`baseline_nearest/` 均保留 metadata、raw、decision、artifact manifest
与 report。`done.json` 是原子终态，`formal_result=false`、`paper_eligible=false`，不得进入正文。

## 冻结合同

唯一算例为 `cn-cy-100c-01-V2-LOCATIONS`，种子为 1--10。每个执行臂使用 MV-HGS-SP 的
`cv_only`、`naive_ev`、`mechanism_ev` 三个视角，每视角恰好 25,000 次迭代，
`max_no_improvement_iterations_per_view=None`；没有使用 2000 次或 150 次无改善早停。两臂唯一
差异是 `hard_home_depot_lock=true/false`。当前合同为严格多趟、固定成本按实体车数计费且
`c_fix=170`、车场充电无限并发、fleet authority v3。

metadata 锁定 git `850cea5f3d3e11a21e073a7c1a45477a65a7a66f` 与 202 份相关源码/输入 SHA。
随机规则实现引用旧 `run_e3_capacity_rank_aligned.py:31-66`；新就近规则在
`run_scout_d.py:301-330`，采用车场到客户的有向路网距离并以 depot_id 破同距。

## 随机基准技术 HALT

旧正式 E3 规则明确使用 `source_p_sequences.csv` 的 `Uniform_Unbalanced`、replicate 01，源序列
是为四车场设计的四组标签。目标算例仅有 `D_chengdu` 与 `D_chongqing`，而前 100 标签仍包含
0、1、2、3。原容量排序函数的 `zip(..., strict=True)` 直接产生
`ValueError: zip() argument 2 is shorter than argument 1`。

仓库与任务卡均未给出 4→2 的批准映射。执行代理没有用取模、合组、删组或重新抽签替代，故
随机基准和对应处理臂的 10 个种子均在搜索前 HALT；`raw_runs.csv` 保留 20 个计划行。该基准
没有合法效应估计，两种基准改善幅度之差也不可估计；不得把技术 HALT 填成 0。

## 就近基准结果

就近映射与该算例原始 `customer_home_depot` 逐客户相同：成都 42、重庆 58；需求分别为
12013 kg、15280 kg。因为就近规则直接返回具体 depot_id，不再存在匿名组，容量排序对齐不适用；
若再排序会改写“就近”定义。

20/20 个种子--臂单元均 PASS，技术错误、违反、墙钟安全停止均为 0。每个单元三个视角均恰好
25,000 次。10 种子均值如下：

| 指标 | 基准臂 | 处理臂 | 改善 | 改善/% |
|---|---:|---:|---:|---:|
| 总成本/元 | 4562.024573963715 | 4562.024573963715 | 0 | 0% |
| 里程/km | 1758.910545079953 | 1758.910545079953 | 0 | 0% |
| 系统排放/kg | 415.8739123997247 | 415.8739123997247 | 0 | 0% |
| 实体车数 | 12 | 12 | 0 | 0% |
| 路线数 | 18 | 18 | 0 | 0% |
| 跨承包商改派客户 | 0/100 | 0/100 | 0 | 0% |

20 个入选解的 routing SHA 只有 1 个，初始解 SHA 也只有 1 个，`selected_source` 全部为
`best_exact_hgs_parent`。因此当前固定算例、归属规则和预算下，解除归属锁没有引发改派或其他
方案变化。该观察不做敏感性外推，也不能证明其他归属构造下必然零效应。旧 121.58/175=69.5%
仅作为历史构造基准的比对数字，不混入本轮 100 客户分母。

## 证据闭合与运行环境

根 `raw_runs.csv` 共 40 行：20 个随机 HALT、20 个就近 PASS。20 份完整 solution 文件的
`solution_sha256` 全部逐份重算通过。artifact manifest 为根 123 项、随机 4 项、就近 84 项，
全部零错配；根 manifest SHA-256 为
`fb68408355beb5e0448eb88a93eb4d27aaf2fe0c51ca1d48285347aa5d450209`。

首次启动在任何 HGS 单元前因受限 macOS 禁止查询 `SC_SEM_NSEMS_MAX` 而使
`ProcessPoolExecutor` 初始化失败。恢复只新增 Popen 编排器，4 个独立子进程仍调用冻结 runner 的
同一个 `run_unit`；`execution_recovery_metadata.json` 明确记录 `failed_search_units=0` 和
`scientific_contract_changed=false`。监控器随后因进程表不可见再次误报父进程退出，但实验自身
原子进度持续前进；两个异常现场均保留，未重启或复制已完成单元。

最终未修改 `docs/paper_v2/paper_main.tex`、`solver/src/setp_solver/check.py`、
`solver/src/setp_solver/search/evaluation.py`，也未覆盖旧
`e3_scattered_ownership_20260801/`。
