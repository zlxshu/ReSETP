# E5 非线性充电科学端点终局聚合

## 结论

本轮状态为 `COMPLETE`，四个预定端点全部回答。数据只来自 v4 已完成并认证的
40 个单元（2 算例 × 2 臂 × 10 种子）；本轮没有启动或重跑任何搜索，
`search_reruns=0`。v4 的 HALT 是文件枚举 bug：旧聚合器将 40 个真实 certificate
与 40 个同名 AppleDouble `._*` 旁文件一并计数为 80。该错误发生在独立证书全部
通过之后，不改变 40 个单元的搜索、方案、完整模型复算或证书内容；本轮只修枚举、
清旁文件并聚合已有证据。

科学结论是 `MECHANISM_BUT_TIE`：NL90 臂完整可行率为 **20/20（100.0%）**，
L100 假可行为 **0/20（0.0%）**，20/20 个共同 NL90 可行配对的平均成本变化为
**0.000%**。非线性曲线确实延长了部分
充电会话，但在本批算例中没有转化为完整可行性或成本差异。

## 文件枚举修复与 AppleDouble 清理

所有证书、plan、task status、封存树和最终产物枚举现在统一排除文件名以 `._`
开头的旁文件，并排除路径中的 `__pycache__` 与 `.pytest_cache`。修复点如下：

- `baselines/china_e3_e7/run_e5_nonlinear_v2_20260730.py`：sealed_tree_hashes, load_certificates, aggregate_and_close artifact manifest traversal。
- `baselines/china_e3_e7/run_e5_nonlinear_v3_20260730.py`：_status_lookup。
- `baselines/china_e3_e7/run_e5_nonlinear_v4_20260730.py`：_status_lookup。
- `baselines/china_e3_e7/check_e5_nonlinear_v2_20260730.py`：formal plan enumeration used by the v4 checker。

清理前 v4 目录有 **262 个真实文件**和 **68 个 AppleDouble 旁文件**；其中真实
plan 为 40、真实 certificate 为 40，certificate 旁文件为 40，plan 旁文件为 0。
精确删除 68 个 `._*` 后，真实文件仍为 **262**、plan 仍为 40、certificate 仍为
40、旁文件为 0；262 个真实文件的逐文件 SHA-256 清理前后完全一致。没有删除或
覆盖任何 v4 真实文件。

## 正式结果表

按期刊合同，一行一算例、每臂 10 次。Best/Avg/Gap% 只在该臂自身物理下完整可行的
运行上计算，`Gap%=(Avg−Best)/Best×100%`；车辆数写作“最佳解/可行运行平均”，
时间为每单元平均墙钟秒，实际评价数写作“均值 [最小–最大]”。时间仅作运行描述，
不据此推断机制快慢。

| Instance | L100 Best | L100 Avg | L100 Gap | L100 vehicles | L100 time(s) | L100 evals | L100 feasible | NL90 Best | NL90 Avg | NL90 Gap | NL90 vehicles | NL90 time(s) | NL90 evals | NL90 feasible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 2288.01 | 2288.23 | 0.0096% | 8/8.00 | 54.01 | 334.8 [298–376] | 10/10 (100.0%) | 2288.01 | 2288.23 | 0.0096% | 8/8.00 | 54.60 | 334.8 [298–376] | 10/10 (100.0%) |
| cn-prd-100c-02-V2-LOCATIONS | 4692.92 | 4706.84 | 0.2966% | 17/17.20 | 187.89 | 355.9 [313–396] | 10/10 (100.0%) | 4692.92 | 4706.84 | 0.2966% | 17/17.20 | 171.03 | 355.9 [313–396] | 10/10 (100.0%) |

机器可读的一行一算例表见 `formal_instance_summary.csv`，逐臂长表见
`formal_instance_arm_summary.csv`。

## 端点 1：NL90 完整可行率

| Instance | Feasible / runs | Rate |
|---|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 10/10 | 100.0% |
| cn-prd-100c-02-V2-LOCATIONS | 10/10 | 100.0% |
| OVERALL | 20/20 | 100.0% |

## 端点 2：L100 假可行数量与原因

“假可行”严格指在 L100 下完整可行、固定路线/车辆/站点/开始时刻/充电量后换到
NL90 物理即完整不可行的 L100 方案。

| Instance | False feasible / L100 runs | Rate |
|---|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 0/10 | 0.0% |
| cn-prd-100c-02-V2-LOCATIONS | 0/10 | 0.0% |
| OVERALL | 0/20 | 0.0% |

原因计数允许同一单元落入多个类别；本批结果不存在：假可行单元为 0，因此各原因计数均为 0，也没有重叠原因组合。容量、时间窗、SOC/电量、
充电时长/功率和其余检查器类别均保留在机器表中，没有用近似字段替代。

## 端点 3：共同可行配对的成本变化

每个 seed 在共同 NL90 物理下比较：L100 方案固定决策回放 NL90 后的完整成本作为
分母，NL90 方案的完整成本作为分子；表中总体值是 20 个合格 seed 配对百分比的
等权均值。

| Instance | Eligible / pairs | Mean | Median | Min–max |
|---|---:|---:|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 10/10 | 0.000% | 0.000% | [0.000%, 0.000%] |
| cn-prd-100c-02-V2-LOCATIONS | 10/10 | 0.000% | 0.000% | [0.000%, 0.000%] |
| OVERALL | 20/20 | 0.000% | 0.000% | [0.000%, 0.000%] |

逐 seed 结果见 `paired_cost_effects.csv`。

## 端点 4：逐会话 SOC 与充电时长差

共持久化 196 个充电会话。以下会话行是嵌套的描述性观测，不当作 196 个独立实验
样本。每个原始会话的实例、种子、臂、车辆、站点、起止 SOC、两种时长和差值见
`charging_sessions.csv`。

| Instance | Sessions | Start SOC mean | median | max | End SOC mean | median | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 80 | 7.195 | 0.000 | 29.247 | 53.367 | 44.172 | 100.000 |
| cn-prd-100c-02-V2-LOCATIONS | 116 | 3.281 | 0.000 | 25.784 | 42.530 | 35.545 | 100.000 |
| OVERALL | 196 | 4.878 | 0.000 | 29.247 | 46.953 | 37.033 | 100.000 |

| Instance | Linear mean(s) | median | max | NL90 mean(s) | median | max | Δ mean(s) | median | max | Positive Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 5417.638 | 4264.931 | 12645.818 | 5733.783 | 4264.931 | 13910.400 | 316.145 | 0.000 | 1264.582 | 20/80 (25.0%) |
| cn-prd-100c-02-V2-LOCATIONS | 4674.107 | 3293.305 | 12645.818 | 4848.532 | 3293.305 | 13910.400 | 174.425 | 0.000 | 1264.582 | 16/116 (13.8%) |
| OVERALL | 4977.589 | 3369.143 | 12645.818 | 5209.859 | 3369.143 | 13910.400 | 232.270 | 0.000 | 1264.582 | 36/196 (18.4%) |

所有端点所需字段均已持久化；没有“字段未持久化”项，也没有重跑搜索补字段。

## 可直接用于正文的中文段落

表中两算例的 NL90 臂完整可行率均为 100.0%（总体 20/20）。在 L100 物理下可行的 20 个方案固定决策回放至 NL90 物理后仍全部可行，假可行数量为 0/20；在两臂均于共同 NL90 物理下可行的 20 个配对中，NL90 相对 L100 的完整模型成本变化在两个算例及总体均为 0.000%。尽管 196 个充电会话的非线性时长相对线性时长平均增加 232.27 s、中位数为 0.00 s、最大增加 1264.58 s，该物理差异未转化为本批次的可行性或成本差异。结果表明，在所选 50/100 客户算例和当前 SOC 暴露范围内，线性近似未高估可行性，非线性充电效应很小；该结论不外推到更高 SOC 暴露或更紧时窗场景。

## 完整性与证据边界

本目录包含 `metadata.json`、`raw_runs.csv`、`decision.json`、
`artifact_hashes.json`、`report.md`，并以最后写入的 `done.json` 作为完成信号。
`artifact_hashes.json` 排除其自身、`done.json`、`._*`、`__pycache__`、
`.pytest_cache` 和监控运行态。源清单见 `source_inventory.json`。

聚合前已逐一复核 40 个 plan 内容 ID、40 个 certificate 内容 ID、证书声明的 plan
文件 SHA-256、solution ID、40 个 task status、40 行 v4 `raw_runs.csv`、共同初始解
配对和 `independent_verification.json`；不一致项为 0。受保护的 `cost.py`、
`check.py`、`search/evaluation.py`、`route_pool_sp.py` 与 v4 source lock
逐文件一致。本轮没有修改这些文件，也没有覆盖 v1/v2/v3/v4 的真实产物。
