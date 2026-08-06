# 求解器根因确诊：代理问题不含实体车队上限，候选补全全数被拒（2026-08-03）

**状态**：`ROOT_CAUSE_CONFIRMED`，`formal_result=false`（诊断任务，非正式实验）。

**优先级说明**：本文件推翻或降级了多份基于 China81 MV-HGS-SP 求解路径的既有实验结论，
读到与本文件冲突的更早文档，一律以本文件为准。

---

## 一句话

**PyVRP 求解的代理问题不施加每车场的实体车数上限**，HGS 搜出的方案用车超标 1–5 辆；
补全环节逐个检查车队上限并一票否决，候选全数被拒；异常被静默吞掉；
最终解恒为"共同初始解"的补全。**搜索侧与检验侧用的不是同一套车队约束，中间没有反馈。**

后果：**随机种子无效、迭代预算无效、最终解恒定**。

---

## 三轮诊断的证据链

产物：
- 一轮 `baselines/china_e3_e7/seed_determinism_probe_20260803/`（COMPLETE，6/6 单元）
- 二轮 `baselines/china_e3_e7/seed_determinism_probe2_20260803/`（COMPLETE，18 行）
- 三轮 `baselines/china_e3_e7/candidate_pool_probe_20260803/`（COMPLETE，9 行）

统一条件：算例 `cn-cy-100c-01-V2-LOCATIONS`、电动车占比 25% 档、新合同全套
（固定成本按实体车 `c_fix=170`、严格多趟、车场充电无限并发、fleet authority v3）。

### 一轮：种子与迭代预算双双无效

| 迭代预算 | 种子 | 完整模型目标值 | 路线结构 sha256 | 评估次数 | 用时 |
|---|---|---|---|---|---|
| 100 | 1 / 2 | `0x1.1d2064a7ab27dp+12` | `16259adedecd…` | 80 | 35.79 / 35.79 s |
| 1000 | 1 / 2 | 同上 | 同上 | 80 | 68.85 / 69.18 s |
| 25000 | 1 / 2 | 同上 | 同上 | 80 | 857.63 / 861.11 s |

`FACT`：6 单元全部逐位相同，总成本恒为 4562.024573963715。
预算补丁确认生效——`hgs_iterations_by_view` 实测 100/1000/25000，
`stop_reasons_by_view` 三视角均 `MAX_ITERATIONS`。用时随预算单调增长，计算确实在跑。
25000 档复现原实验 level_025 的值，证明与原实验同一代码路径。

`FACT`：种子接线每一层都在，无断点——`epochal_hgs.py:239` `rng = RandomNumberGenerator(seed=int(seed))`、
`:241` 进 LocalSearch、`:310` `make_random(data, rng)`、`:206` `MaxIterations(...)`、
`:382-392` rng 进 `GeneticAlgorithm`。

### 二轮：搜索有效，差异消失在补全环节

`FACT——搜索有效`：代理侧 `proxy_best_cost` 18 行中有 **15 个不同取值**；
100 档与 1000 档跨种子不同，所有种子跨预算均不同；25000 档跨种子相同（代理问题已收敛）。
`cv_only` 视角种子 1：初始 `0x1.98ef7a0p+25`（≈5360 万）→ 100 次 `0x1.9499700p+21`（≈3,314,176）
→ 1000 次 `0x1.202d300p+21`（≈2,362,010）→ 25000 次 `0x1.1eaa200p+21`（≈2,347,584）。
约 4000 倍改进，100 次与 25000 次相差约 29%，`proxy_best_is_feasible` 全部为真。

`FACT——完整侧恒定`：同 18 行的 `objective_float_hex`、`route_structure_sha256`、
`charging_structure_sha256` 各自只有 **1 个取值**。15 种代理方案补全后产出同一套路线。

`FACT——种群全随机`：`min_pop_size = 25`、`warm_native_count = 0`、`random_count = 25`（18 行全部）。
故"热启动填满种群、随机成分为 0"这一解释被排除。

`FACT——重组环节空转`：`archive_candidate_count = 1`、`exact_elite_count = 1`、
`sp_route_pool_size = 18`（恰等于最终解路线数）、`sp_improved_over_parent = false`、
`selected_source = "best_exact_hgs_parent"`（18 行全部）。集合划分无组合空间，MILP 必然返回原解。

### 三轮：确诊——不是配置压的，是补全全灭

`FACT——配置正常`：`run_formal_fleet_levels_xb_20260802.py:76` `ARCHIVE_CANDIDATES_PER_VIEW = 24`、
`:536` 显式传入；`:75` `EXACT_ELITES_PER_VIEW = 8`、`:535` 显式传入；
`route_pool_sp.py:117-130` 归一化走 else 分支为三视角各生成 24，`:207-208` 传入。
`epochal_hgs.py:430-443` 的切片在补全循环之前，故上限限制的是补全**尝试**数。

`FACT——补全成功率为 0`（9 行全部一致）：

| 量 | 值 |
|---|---|
| `proxy_ranked_count` | 86 ~ 123 |
| `max_archive_candidates_effective` | **24**（不是 1） |
| `completion_attempted` | 24 |
| `completion_succeeded` | **0** |
| `completion_failed` | **24** |
| `archive_completions_count` | 1（= 共同初始解的补全） |
| `elite_completions_count` | 1 |
| `distinct_full_objective_among_succeeded` | 0 |

`FACT——失败原因原文`（绝大多数）：

```
ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps
at 'D_chengdu': overage=(1, 0, 1)        # overage 取值 (1,0,1) 到 (5,0,5)
```

个别落在 `'D_chongqing'`；另有 1 次
`ValueError: E3_STRICT_MULTITRIP_V2: route CH81-0018 misses C055's time window`。

`FACT——静默丢弃`：异常在 `epochal_hgs.py:532-543` 被
`except (IndexError, KeyError, TypeError, ValueError)` 捕获后不加入 `exact_candidates`，
**无计数、无告警**。这是缺陷长期未被发现的直接原因。

`FACT——候选被丢弃的全部位置`（`epochal_hgs.py`）：
`:427-429` 按 native key 去重、`:430-443` 按上限截断、`:499-512` 硬 home-depot 锁过滤
（本路径 `hard_home_depot_lock=False`，不触发）、`:532-543` 异常捕获丢弃（**实际全灭点**）、
`:594` 对 `elite_completions` 按 `exact_elite_count` 截断。

---

## 完整链条

HGS 在代理问题上搜出好解（有效、可行、改进约 4000 倍）
→ 取前 24 个候选去补全
→ **24 个全部因超出实体车队上限被拒**
→ 异常静默丢弃
→ `archive_completions` 只剩共同初始解（`epochal_hgs.py:544-594` 的 `common_completion`）
→ 集合划分拿到的是它的 18 条路线，无组合空间
→ 输出恒定，与种子、迭代预算均无关。

---

## 已确认受影响的实验资产

全仓库只读扫描 `baselines/**/search_trace.json` 与 `**/solution_witnesses.json` 共 2256 份：

| 实验包 | 有 `archive_completion_attempts` 的份数 | 尝试 | 成功 |
|---|---|---|---|
| `baselines/china_e3_e7/formal_algorithm_20260802` | 60 | 1620 | **0** |
| `baselines/china_e3_e7/formal_ablation_200c_20260803` | 20 | 900 | **0** |
| **合计** | **80** | **2520** | **0** |

这两个包即**论文算法章的正式算法实验与正式消融实验**。

### ⚠️ 上表不可外推——ASSET1 全量盘点的修正

`docs/handoff/asset_audit_20260803/`（ASSET1，COMPLETE，898 个包，纯只读）全量扫描得出：
全仓库 `archive_completion_attempts` 合计 **184,854**、`archive_candidates_completed`
合计 **24,526**，成功率 **13.3%**。**缺陷不是全局归零。**

| 日期 | 实验包 | 尝试 | 成功 | 成功率 |
|---|---|---|---|---|
| 07-30 | `e3_structural_20260731` | 25,587 | 3,449 | 13.5% |
| 07-30 | `e3_structural_20260731/probe` | 969 | 139 | 14.3% |
| 07-30 | `e3_zone_joint_20260731` | 39,966 | 5,359 | 13.4% |
| 07-30 | `e5_nonlinear_v4_20260730` | 40,482 | 5,418 | 13.4% |
| 07-30 | `e5_nonlinear_v4_20260730/probe` | 1,938 | 278 | 14.3% |
| 07-30 | `e6_fairness_v2_20260731` | 6,747 | **0** | **0%** |
| 07-30 | `e6_fairness_v3_20260731` | 6,747 | **0** | **0%** |
| 08-03 | `formal_ablation_200c_20260803` | 900 | **0** | **0%** |
| 08-03 | `formal_algorithm_20260802` | 1,620 | **0** | **0%** |

同一天（07-30）既有 13.4% 也有 0%，故**不是版本回归，是约束一收紧成功率就塌到 0**——
公平约束（e6）与新合同固定车队总量（两个 formal 包）都触发归零。
**即便最好情形也只有约 13.4%，86.6% 的候选一直在被丢弃。**

`FACT——分类计数`（898 个包）：`AFFECTED_CONFIRMED` 20、`AFFECTED_LIKELY` 76、
`NOT_AFFECTED_PATH` 114、`NO_SEARCH` 129、`UNDETERMINED` 559。

`FACT——指纹乙`：182 个包有可比分组，合计 4,988 组，
种子无变异的 **1,842 组占 36.9%**；**157 个包存在真实种子变异**，这些包里搜索确实影响了结果。

`FACT——UNDETERMINED 的缺口`：559 条中 546 条缺少可区分求解路径的
engine／源文件绑定／runner 调用证据，13 条已定位 P1 但记录不足以使任一指纹成立。

`FACT——盘点自身的口径限制`：`898` 被嵌套目录抬高（子目录与父目录各计一个包），
`baselines` 根目录本身也被计为一个包并汇总下级数字（上表已剔除）；
部分数值列含中文说明串（"该包无此信息"），数值统计须过滤。

`FACT——由此解释的既有现象`：此前"100c 五臂全部 3621.569908、200c 三臂全部 7820.181472、
判别力为零"，当时归因为迭代预算不足，**实为候选补全全灭、各臂共用同一个共同初始解**。
消融臂 `MV_HGS_NO_SP`、`HGS_M_SP_NO_MULTIVIEW` 消融的是搜索组件，
而搜索输出被整体丢弃，故消融必然无差异。

`FACT——附带解释`：SCOUT3 车队臂 75% 与 100% 两档 10/10 全部 `INFEASIBLE_OR_NOT_FOUND`
（见 [scout3_corrected_reading](../scout3_corrected_reading_20260803.md)）——
电动车占比升高时车队约束更紧，连共同初始解也构造不出。

其余 2176 份产物**没有该字段**，不能据此判定受不受影响，
逐包盘点见 `docs/handoff/asset_audit_20260803/`（ASSET1，只读，五类分类，每条须附判据）。

---

## 对既有结论的处置

1. **迭代预算标定作废**：`V7_FIXED_25000_ITERATIONS_PER_VIEW` 对结果无作用；
   此前"2000 次 vs 25000 次"的全部讨论无意义。参见
   [标定与标准的分界](../../../CLAUDE.md)所述"内部标定来自我们自己的数据"——
   这条标定当时就没有自己的数据支撑，本次实测证伪。
2. **算法性能主张全部无依据**：论文算法章（MV-HGS-SP）目前拿不出"搜索带来改进"的证据。
3. **全文"最优""优化得到"的表述一律要改**。
4. **机制对比的数字仍可用但要改口径**：三个档位成本
   （0%: 5174.43 / 25%: 4562.02 / 50%: 4201.13）是同一确定性补全流程在不同配置下的产物，
   该流程对配置敏感（不同电动车占比给出不同成本与派车结构），作机制对比成立，
   但**不是搜索得到的解**。

---

## 用户 2026-08-03 定的推进顺序

**先查清 → 再验证资产 → 最后改。**

- 第一步"查清"：已完成（本文件）。
- 第二步"验证资产"：ASSET1 进行中，交付 `docs/handoff/asset_audit_20260803/`。
- 第三步"改"：未开始。**修复后所有受影响实验须重跑。**

## 同轮更正的两条 SCOUT3 结论

见 [scout3_corrected_reading_20260803.md](../scout3_corrected_reading_20260803.md)：

- 非线性充电臂 `MEASURABLE_EFFECT` 不成立，实为零效应
  （两臂成本差 `0.0`/`0.0%`，`public_station_charging_count` 与
  `between_trip_recharge_count` 全部为 0，机制一次未触发；
  Codex 判"有效应"的唯一依据是充电结构 sha256 不同）。用户裁定：暂时挂起。
- 车队臂 `pass_units 30/50`，缺的 20 个是 75%/100% 两档整档无解，
  故 −18.81% 是可行范围上边缘而非曲线上一点。

## 相关

- [机制作用条件在算例里不存在](mechanism_condition_absent_20260731.md) —— 不同的病，
  但同样表现为"零效应"，判别方法是查机制触发计数是否为 0。
- [fleet authority v3](fleet_authority_v3_20260802.md) —— 本次被违反的车队上限即出自该权威表。
