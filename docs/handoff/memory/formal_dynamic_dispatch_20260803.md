---
name: formal-dynamic-dispatch-20260803
description: "XC-RESUME 动态发车正式实验的续跑终态、失败保留、完整解审计与 metadata 字节恢复"
metadata:
  node_type: memory
  type: experiment_terminal
  effective_date: 2026-08-03
  status: active
---
> ⚠️ **2026-08-03 结论待重估**：本文件的实验走 China81 MV-HGS-SP 求解路径，
> 该路径已确诊缺陷——PyVRP 代理问题不施加每车场实体车数上限，HGS 候选补全时被全数拒绝
> （异常在 `epochal_hgs.py:532-543` 静默吞掉），最终解恒为共同初始解，
> **随机种子与迭代预算对结果均无影响**。凡本文件中涉及算法性能、判别力、
> 臂间差异、"最优解"的表述一律以
> [solver_completion_reject_root_cause_20260803.md](solver_completion_reject_root_cause_20260803.md)
> 为准；受影响范围的逐包判定见 `docs/handoff/asset_audit_20260803/`。修复后须重跑。

# XC-RESUME 动态发车正式实验终态（论文 5.3）

权威证据目录：`baselines/china_e3_e7/formal_dynamic_dispatch_20260802/`。
终态：`XC_DYNAMIC_FORMAL_COMPLETE`。这是网络断流前同一后台任务的续跑收口，未启动第二个
结果写入者、未重算已完成场景。

## FACT：执行终态

- 3 种策略 × 10 种子共 30 个配对场景全部落盘；`status.json` 为 30/30，
  `done.json` 与 `decision.json` 均为 `XC_DYNAMIC_FORMAL_COMPLETE`，运行时失败为 0。
- 场景结果为 15 个 `PASS`、14 个 `SEARCH_NOT_FOUND`、1 个 `HARD_INFEASIBLE`；三类均保留。
  各策略的搜索未找到数依次为逐单 5、固定 30 分钟 4、混合触发 5；硬不可行只出现在
  固定 30 分钟策略 seed 7。搜索未找到之后的剩余触发明确记为
  `NOT_ATTEMPTED_AFTER_RETAINED_FAILURE`，没有伪造终解。
- 60 个臂级汇总、914 行逐触发证据、1200 行逐事件状态、346 个成功的同冻结状态配对均已落盘。
  752 份保存解包括 60 份预优化解和 692 份动态阶段解；每份的解哈希、排班证书哈希、
  前态/后态哈希均独立复算零错配，所有保存证书均为 `PASS`。
- 实际调整次数没有锁成 3：臂级总数范围为 3--20，出现值为
  3/4/6/7/8/9/10/11/12/13/14/15/18/20。逐单、固定 30 分钟、混合触发的平均实际调整次数
  分别为 15.5、9.0、10.1。
- 346 个成功配对阶段全部满足同事件、同种子、同冻结状态。15 个阶段在碳感知减碳盲的
  充电动作、成本或排放中至少一项有差，其中 12 个阶段有成本或排放差；路线、车型、距离和
  实体车数配对差均为 0。
  机械判定为 `SUPPORTED_AS_REGISTERED_MECHANISM_OBSERVATION_NO_WINNER_CLAIM`；
  `paper_winner_selected=false`、`strategy_ranked_by_mean_cost=false`。

## FACT：合同与完整性

- `preregistration.json` SHA-256 前后均为
  `98053790d1be73ab9074aab408d5a447390683c1bfe93cbd0e2cb431e10136f6`。
- 聚合器曾自动把应冻结的 `metadata.json` 从开跑前哈希
  `67788d46ebd10763d87310885d0ff74e170e887e6506954ba6f50229bedfd7f4`
  改写为 `23cd3f47...`。续跑代理只在内存重建候选字节并确认候选哈希精确等于原哈希后，
  恢复原始 metadata；恢复证据在 `runtime_environment_addendum_resume6.json`。
  因此 metadata 终态仍是原来的 `XC_DYNAMIC_FORMAL_PREREGISTERED`，实验终态须看
  `status.json`、`done.json` 与 `decision.json`。
- 最终 `artifact_hashes.json` SHA-256 为
  `88c06fa952465763fd2406a202dcbc5f265b01459c7210da12213cb39981c2b1`，共 811 项，
  逐项重算零缺失、零错配；明确排除 `artifact_hashes.json`、`done.json`、`._*` 和
  `**/__pycache__/**`。
- 752 份保存解逐份满足 `cost_fix=170×实际使用实体车数`，车辆类型计数零错配，
  货币化等待成本非零数为 0。预注册锁定的全部源码与输入哈希重算零漂移。
- `failed_start1_empty_scenarios`、`failed_start2_thread_transport`、
  `failed_start3_thread_preoptimization_only` 三个失败启动目录原样保留；第三个目录仍保留
  6 份只完成碳感知预优化的现场文件。
- 代表事件仍是搜索前登记的 `ADD_016_C076`；双面板图
  `representative_route_adjustment.png` 已目视核对。未修改 `paper_main.tex`、`check.py` 或
  `search/evaluation.py`。

## BOUNDARY

本批不按平均成本给三种策略排名。14 个搜索未找到和 1 个硬不可行是正式结果的一部分，
不能删除、换种子或用后续补跑替换。机器标签只证明预注册的机制观察在本批中出现，
论文如何组织这些不利结果及是否保留 5.3 为主结果，由用户另行决定。
