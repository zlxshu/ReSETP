# SCOUT3 探路结果的更正解读（2026-08-03）

本文件更正 `baselines/china_e3_e7/scout_three_mechanisms_20260803/` 各臂 `decision.json`
里 `status` 字段给出的表面结论。**以本文件为准。**

产物本身不改（它是已完成的原始记录）；改的是对它的解读。

---

## 一、非线性充电臂：`MEASURABLE_EFFECT` 不成立，实为零效应

`arm_nonlinear/decision.json` 写的是 `status: MEASURABLE_EFFECT` / `answer: 有效应`。
回原始数据核对后，这个判定不成立。

原始数字（`arm_nonlinear/decision.json` + `raw_runs.csv`，20 行）：

| 项 | 值 |
|---|---|
| `maximum_paired_difference.difference` | **0.0** |
| `maximum_paired_difference.relative_percent` | **0.0** |
| 线性对照 `L100_control` 目标值 | `0x1.1d2064a7ab27dp+12`（10 个种子全部相同） |
| 非线性 `NL90_mild` 目标值 | `0x1.1d2064a7ab27dp+12`（10 个种子全部相同，且与对照逐位相同） |
| `public_station_charging_count` | **0**（全部 20 行） |
| `between_trip_recharge_count` | **0**（全部 20 行） |
| `between_trip_recharge_energy_kwh` | **0**（全部 20 行） |
| `total_cost_cny` | 4562.024573963715（两臂、全部种子一致） |

判"有效应"的唯一依据是 `all_structure_equal: false`（充电结构 sha256 不同），
`effect_layers: ["charging"]`。即：**充电动作的内部结构有差别，但总成本一分钱没变。**

零次公共站充电、零次趟间补电，说明非线性充电曲线在本算例上一次都没被触发——
车辆全部在车场充满，满充条件下非线性与线性没有差别。

这与 `docs/handoff/memory/` 中已记录的 E3/E5 病灶同类：
**机制的作用条件在算例里不存在**，不是门禁问题，也不是效应。

**用户 08-03 裁定：非线性充电暂时挂起**，等碳强度 × 混合车队 × 动态需求三条主线稳住再说。

## 二、混合车队臂：效应存在，但报告口径要改两处

`arm_fleet/decision.json` 报 `status: MEASURABLE_EFFECT`，
`maximum_level_gap`: 档位 0 → 档位 50，差 −973.30 元 / −18.81%。

逐档核对 `arm_fleet/raw_runs.csv`（50 行）：

| 电动车占比 | 10 个种子的状态 | `aware_full_model_cost_cny` | 派 CV/EV | 评估次数 |
|---|---|---|---|---|
| 0% | 10/10 PASS | 5174.431221352166 | 12 / 0 | 80 |
| 25% | 10/10 PASS | 4562.024573963715 | 8 / 4 | 80 |
| 50% | 10/10 PASS | 4201.130262011535 | 5 / 7 | 80 |
| 75% | **10/10 `INFEASIBLE_OR_NOT_FOUND`** | 无 | 无 | 无 |
| 100% | **10/10 `INFEASIBLE_OR_NOT_FOUND`** | 无 | 无 | 无 |

### 更正 1：50% 是可行范围的上边缘，不是曲线上的一点

`pass_units: 30 / observed_units: 50`，缺的 20 个不是技术故障
（`technical_error_units: 0`），是 75% 与 100% 两档整档无解。
因此 −18.81% 应表述为"从纯燃油到本算例能跑通的最高电动化程度"，
而不是"电动化收益随占比单调递增"。

75%/100% 无解的成因（真实约束 vs 代码缺陷）**用户 08-03 裁定：先不查**，
先解决种子问题，一次只动一个变量。

### 更正 2：不能声称多种子稳健性

同一档位下 10 个种子的以下量**逐位完全相同**：

- `aware_full_model_cost_cny`、`aware_objective_float_hex`
- `aware_route_structure_sha256`、`aware_charging_structure_sha256`
- `aware_dispatched_cv`、`aware_dispatched_ev`、`aware_used_physical_vehicles`、`aware_route_count`
- `aware_complete_candidate_evaluation_attempts`（三档均为 80）

同一档位下随种子变化的列只有：`unit_id`、`seed`、`elapsed_seconds`、
以及含 `unit_id` 的两个文件名 hash。

即 **"10 个种子"实际是同一个结果的 10 份副本**，没有任何离散度，
不能报标准差、不能做统计检验、不能写"多种子稳健"。

`aware_charging_structure_sha256` 在 0% 档为 `4f53cda18c2b...`，
即 `sha256("[]")`，是空结构——0% 电动车时无充电动作，符合预期，不是异常。
25%/50% 档该 hash 不同，说明确有充电决策。

## 三、种子零变异的接线核查（静态，已完成）

种子从入口到随机数生成器每一层都在，没有断点：

| 层 | 位置 | 原文要点 |
|---|---|---|
| 派发 | `scout_three_mechanisms_20260803_runner.py:525` | `"--seed", str(seed)` |
| worker | 同文件 `fleet_worker()` | `old.run_unit(level, seed, ...)` |
| 单元 | `run_formal_fleet_levels_xb_20260802.py:788` | `def run_unit(level, seed, ...)` |
| 中间 | 同文件 `:533` | `seed=int(seed)` |
| 混合器 | `china81_mechanism_hybrid_20260720/hybrid.py` | 多处 `seed=seed` |
| 随机数 | `china81_mechanism_hybrid_20260720/pyvrp_adapter.py:553` | `rng = RandomNumberGenerator(seed=int(seed))` |

`_configure_fleet()` 中替换的 `build_pyvrp_problem` 闭包
（runner:465-470）只重建问题实例，签名里不含 seed，不构成种子丢失点。

关键反证：若种子确实驱动了搜索、只是集合划分阶段把结果收敛到同一最优，
则 `complete_candidate_evaluation_attempts` 应随种子波动。实测三档均恒为 80。

另：全仓库历史 `raw_runs.csv` 扫描，未找到任何种子产生不同结果的记录。

## 四之二、SEEDPROBE 判别结果（2026-08-03 18:49 完成，6/6 单元）

产物：`baselines/china_e3_e7/seed_determinism_probe_20260803/`（`status: COMPLETE`）

| 迭代预算 | 种子 | 状态 | 目标值 hex | 成本 | 路线 hash | 充电 hash | 派 CV/EV | 路线数 | 评估次数 | 用时(s) |
|---|---|---|---|---|---|---|---|---|---|---|
| 100 | 1 | PASS | `0x1.1d2064a7ab27dp+12` | 4562.024573963715 | `16259adedecd` | `4486a90585ab` | 8/4 | 18 | 80 | 35.794 |
| 100 | 2 | PASS | 同上 | 同上 | 同上 | 同上 | 8/4 | 18 | 80 | 35.788 |
| 1000 | 1 | PASS | 同上 | 同上 | 同上 | 同上 | 8/4 | 18 | 80 | 68.854 |
| 1000 | 2 | PASS | 同上 | 同上 | 同上 | 同上 | 8/4 | 18 | 80 | 69.178 |
| 25000 | 1 | PASS | 同上 | 同上 | 同上 | 同上 | 8/4 | 18 | 80 | 857.63 |
| 25000 | 2 | PASS | 同上 | 同上 | 同上 | 同上 | 8/4 | 18 | 80 | 861.11 |

**结论超出原假设范围。** 原设计只想区分"种子有没有用"，实测发现：

1. **种子无影响**：种子 1 与 2 在三个预算档下均逐位相同。
2. **迭代预算同样无影响**：100 次与 25000 次（250 倍差距）产出逐位相同的解，
   `complete_candidate_evaluation_attempts` 恒为 80。
3. **计算确实在跑**：用时随预算单调增长（35.8 s → 68.9 s → 858 s）。
4. **路径一致性对照通过**：25000 档复现原实验 level_025 的 4562.024573963715，
   证明探针与原实验走同一条代码路径。

迭代预算补丁确认生效（`hgs_iterations_by_view` 实测为 100 / 1000 / 25000，
`stop_reasons_by_view` 三视角均为 `MAX_ITERATIONS`），三档不是同一预算的重复。

**已测量到的事实**：搜索的输出不改变最终的完整模型目标值。

**尚未证明的机制**：为什么不改变。至少有两种解释，本轮数据分不开：

- **甲′｜代理层已饱和**：HGS 搜索的是代理问题（`build_pyvrp_problem` 的
  `route_proxy_mode`），完整模型目标值只在其后的确定性补全步骤才出现。
  若传入的 `common_initial_solution` 在代理问题上已达最优，则 HGS 在 100 次和
  25000 次都改进不了，用时照样随预算增长，每次补全结果相同。
  注意 `epochal_hgs.py:303-311`：`random_count = max(0, min_pop_size - len(warm_native))`
  ——若热启动解数量已达种群下限，**随机初始解数量为 0**，种群里没有随机成分。
- **乙′｜补全步骤吞掉了差异**：代理层的解确实随种子/预算变化，但确定性补全
  （排班、充电、多趟打包）把不同的代理解映射到了同一个完整解。

判别办法：记录**代理侧目标值**（每个视角的 `result.best` 代价）与路线池规模。
本轮探针只记了完整模型目标值，没记代理侧。
- 代理侧目标值随种子/预算变化、完整模型目标值逐位不变 → 乙′
- 代理侧目标值也逐位不变 → 甲′

### 静态取证（`findings.json` 的 `static_forensics`，逐条带行号原文）

接线本身全部正确，没有断点：

- `epochal_hgs.py:239` `rng = RandomNumberGenerator(seed=int(seed))`
- `epochal_hgs.py:241` `local_search = LocalSearch(data, rng, neighbours)`
- `epochal_hgs.py:310` `NativeSolution.make_random(data, rng)`（补足种群的随机初始解）
- `epochal_hgs.py:206` `criteria = [MaxIterations(int(max_hgs_iterations))]`
- `epochal_hgs.py:382-392` rng 作为构造参数进入 `GeneticAlgorithm`
- `route_pool_sp.py:196-208` 三个视角逐一调用 `_run_exact_epoch(..., seed=int(seed), max_hgs_iterations=...)`

最终解的挑选路径（`route_pool_sp.py`，均为确定性、不接收随机数）：

- `:225` `parent_completion = min(..., key=lambda item: item.objective)` — HGS 完整候选中取最优父解
- `:255` `recombined, sp_stats = _solve_set_partitioning(...)` — 集合划分重组
- `:305` `selected_source, completion = min(..., key=lambda item: item[1].objective)` — 父解与重组解取最优
- `:690` `result = milp(...)`，`:698` `options={"time_limit": ...}` — 集合划分是 MILP

`hybrid.py:346-347` 的内部多种子群体机制（`base_seed + 1_009*index`）**未在本条代码路径上启用**。

### SEEDPROBE2 判别结果（2026-08-03 20:05 完成，6 单元 × 3 视角 = 18 行）

产物：`baselines/china_e3_e7/seed_determinism_probe2_20260803/`（`status: COMPLETE`）
所有观测量均取到，`unobtainable_quantities` 为空。取数方式见其 `report.md` 第 9-19 行
（代理值经 monkeypatch 从 `Result.cost()` 取；种群构成从 `Population._params` 与
`HgsExactEpoch.stats.warm_elite_count` 取；集合划分三项直接读 `HgsRoutePoolRun.stats`）。

**判定：乙′成立，甲′排除。**

甲′排除的直接证据：`min_pop_size = 25`、`warm_native_count = 0`、`random_count = 25`
（18 行全部如此）。热启动解一个都没进种群，种群 25 个初始解**全部是随机生成的**。
所以不存在"热启动填满种群、随机成分为 0"的情形。

乙′成立的直接证据：

| 层 | 跨种子 | 跨预算 | 取值个数 |
|---|---|---|---|
| **代理侧** `proxy_best_cost` | 100 档、1000 档均**不同**；25000 档相同 | 全部**不同** | 18 行中 **15** 个不同取值 |
| **完整模型** `objective_float_hex` | 相同 | 相同 | 18 行中 **1** 个取值 |
| **完整模型** `route_structure_sha256` | 相同 | 相同 | 18 行中 **1** 个取值（`16259adedecd…`） |
| **完整模型** `charging_structure_sha256` | 相同 | 相同 | 18 行中 **1** 个取值（`4486a90585ab…`） |

代理侧 `cv_only` 视角实测（种子 1）：

| 预算 | 代理初始最优 | 代理最终最优 | 十进制约值 |
|---|---|---|---|
| 100 | `0x1.98ef7a0p+25` | `0x1.9499700p+21` | ≈ 3,314,176 |
| 1000 | `0x1.98ef7a0p+25` | `0x1.202d300p+21` | ≈ 2,362,010 |
| 25000 | `0x1.98ef7a0p+25` | `0x1.1eaa200p+21` | ≈ 2,347,584 |

HGS 在代理问题上把目标值从 ~5360 万降到 ~235 万（约 4000 倍改进），
100 次与 25000 次之间还差约 **29%**，且 `proxy_best_is_feasible` 全部为真。
**搜索确实在有效工作。**

**这 15 种不同的代理侧方案，补全后产出同一套路线（路线结构 sha256 只有 1 个取值）。**

补全与重组环节的实测（18 行全部一致）：

- `archive_candidate_count = 1` —— 每个视角实际送入路线池的完成解只有 **1 个**
- `exact_elite_count = 1`
- `sp_route_pool_size = 18` —— 送进集合划分 MILP 的路线 18 条，恰等于最终解的路线数
- `sp_improved_over_parent = false` —— 集合划分**从未**改进过 HGS 父解
- `selected_source = "best_exact_hgs_parent"` —— 最终解恒取 HGS 父解

即：25 个种群、25000 次迭代演化出来的解集，最后只有 1 个被完成；
集合划分拿到的路线池就是那一个解的 18 条路线，没有组合空间，MILP 必然返回原解。

**代理问题的目标与完整模型的解脱钩**：代理成本相差 29% 的两批方案，
补全后的路线结构逐位相同。搜索在优化的东西，不决定最终答案。

### 直接后果（三条，均无需进一步判别即成立）

1. **迭代预算这个旋钮是无效的。** 之前关于"2000 次 vs 25000 次"的全部讨论、
   以及 `V7_FIXED_25000_ITERATIONS_PER_VIEW` 这个标定，对结果没有任何作用。
2. **不能声称任何算法性能。** 论文算法章（MV-HGS-SP）目前拿不出"搜索带来改进"的证据。
3. 凡出现"最优""优化得到"的表述一律要改——不同配置确实产出不同成本
   （0%: 5174.43 / 25%: 4562.02 / 50%: 4201.13），但这些不是搜索得到的最优解。

**第 3 条的附带判断（SEEDPROBE2 后已定）**：判定为乙′。
三个成本值（5174.43 / 4562.02 / 4201.13）是同一个确定性补全流程在不同配置下的产物。
该流程对配置是敏感的（不同电动车占比给出不同成本与不同派车结构），
因此**作为机制对比仍然可用**——但它们不是搜索得到的解，不能称"最优"。

### SEEDPROBE3 确诊（2026-08-03 21:12 完成，3 单元 × 3 视角 = 9 行）

产物：`baselines/china_e3_e7/candidate_pool_probe_20260803/`（`status: COMPLETE`）

**配置正常，是补全全数失败。**

| 量 | 9 行实测值 |
|---|---|
| `proxy_ranked_count`（HGS 排出的候选） | 86 ~ 123 |
| `max_archive_candidates_effective` | **24**（不是 1） |
| `completion_attempted` | 24 |
| `completion_succeeded` | **0** |
| `completion_failed` | **24** |
| `archive_completions_count` | 1（= 共同初始解的补全） |
| `elite_completions_count` | 1 |
| `distinct_full_objective_among_succeeded` | 0 |

配置链取证：`run_formal_fleet_levels_xb_20260802.py:76` `ARCHIVE_CANDIDATES_PER_VIEW = 24`、
`:75` `EXACT_ELITES_PER_VIEW = 8`，均显式传入，`route_pool_sp.py:117-130` 归一化正常。
`epochal_hgs.py:430-443` 的切片在补全循环之前，故该上限限制的是补全**尝试**数。

失败原因原文（绝大多数）：

```
ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps
at 'D_chengdu': overage=(1, 0, 1)      # overage 取值 (1,0,1) 到 (5,0,5)
```

个别落在 `'D_chongqing'`；另有 1 次
`ValueError: E3_STRICT_MULTITRIP_V2: route CH81-0018 misses C055's time window`。

异常在 `epochal_hgs.py:532-543` 被 `except (IndexError, KeyError, TypeError, ValueError)`
捕获后不加入 `exact_candidates`，**静默丢弃、无计数、无告警**——这是两个月未被发现的原因。

### 确诊结论

**PyVRP 求解的代理问题不施加每车场的实体车数上限**，搜出的方案用车超标 1–5 辆；
补全侧逐个检查车队上限并一票否决，24 个候选全数被拒；
最终解恒为共同初始解（`epochal_hgs.py:544-594` 的 `common_completion`）的补全。

链条：HGS 搜出好解（代理侧有效）→ 24 个候选全部补全失败 → 静默丢弃 →
只剩共同初始解 → 集合划分拿到的是它的 18 条路线，无组合空间 → 输出恒定。

**搜索侧与检验侧用的不是同一套车队约束，中间没有反馈。**

**附带解释 75%/100% 整档无解**：电动车占比升高时车队约束更紧，
连共同初始解也构造不出。此项此前裁定"先不查"，现由本根因一并解释。

## 四、原判别设计（已由上节结果取代，保留备查）

两种互斥解释：

- **甲｜算例太松**：25000 次迭代已充分收敛，不同种子殊途同归。
- **乙｜代码缺陷**：随机数未被搜索消费，种子只作标签记录。

判别设计（用户 08-03 批准）：固定算例 `cn-cy-100c-01-V2-LOCATIONS`、
固定 25% 档，只改种子（1、2）与迭代预算（100、1000、25000），共 6 个单元。
100 次迭代对 100 客户算例绝不可能收敛：若此时两种子仍逐位相同 → 支持乙；
若不同 → 支持甲。25000 那两个单元兼作路径一致性对照，
应复现 4562.024573963715。

交付：`baselines/china_e3_e7/seed_determinism_probe_20260803/`

**在该判别出结果之前，不重启 4 车场探路**——否则会产出同样不可复现的数据。

## 五、本轮的执行记录（如实）

- 因本机 8 核 / 8GB、负载 7.09、交换区已用 93.7%（剩 709 MB），
  用户批准"停一个探路让另一个独占资源"。
- 选项文本写的是保留 4 车场那组，实际停的是 4 车场、保留 2 车场
  （理由：2 车场已完成 3 臂中的 2 臂）。**这是执行时换了批准对象，
  当时未重新征询**，已当面向用户说明。4 车场那组当时刚起步，可随时重开。
- 当前仍在跑：SCOUT3 的动态需求臂（已运行约 4h42m）、SEEDPROBE。
