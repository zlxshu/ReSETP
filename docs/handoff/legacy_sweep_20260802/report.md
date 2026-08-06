# X2 历史遗留问题地毯式扫描台账

- 任务编号：`X2`
- 扫描日期：2026-08-02
- 状态：`X2_LEGACY_SWEEP_PARTIAL`
- 边界：只读扫描与登记；除本目录四个交付文件外，未修改、删除、移动仓库资产，未运行实验。

## 结论

本轮登记 32 项：死代码 4、重复实现 5、退役资产 6、参数漂移 8、悬挂引用 3、文档失效 6；其中 23 项直接影响当前主线。

影响主线最强的不是“文件太多”本身，而是四条仍在活链上的历史语义：第一，正式 ALNS 一面声称使用 `algorithms/resetp_alns` 私有实现，一面反向依赖 `search/charging.py` 和以 E3 命名、默认关闭的多趟评分适配层；第二，`DEFAULT_PRICES` 仍是 Goeke/UK 单位和参数，而 China81 靠调用者显式覆盖；第三，China81 仍绑定 fleet authority v1，v2 虽数值全等，但两版共同继承无外部依据的 `num_ev=max(1,ceil(0.25R_d))`；第四，当前论文仍从旧 E2 campaign 直接输入表体，算法表的 raw runs 又锁定在旧源码哈希。

正向论文文件引用没有断链：7 个显式 `input/includegraphics/IfFileExists` 目标都存在。真正的问题是旧目录路径耦合和反向 provenance 缺口：E4 两份正式 decision 的数字已写进正文，但正文没有记录包路径或 decision hash。

本轮没有达到“`solver/src/setp_solver/` 107 个有效文件逐文件逐行人工通读”和“`baselines/` 所有子目录逐包 metadata 闭合”的完成门，因此不得写 `X2_LEGACY_SWEEP_COMPLETE`。已完成和未完成的精确边界见末节及 `done.json`。

## 总计数

| 类别 | 登记数 | 主要台账编号 |
|---|---:|---|
| 死代码 | 4 | `X2-DC-001`—`004` |
| 重复实现 | 5 | `X2-RI-001`—`005` |
| 退役资产 | 6 | `X2-RA-001`—`006` |
| 参数漂移 | 8 | `X2-PD-001`—`008` |
| 悬挂引用 | 3 | `X2-HR-001`—`003` |
| 文档失效 | 6 | `X2-DF-001`—`006` |
| 合计 | 32 | 影响当前主线 23 |

## 1. 求解器源码 `solver/src/setp_solver/`

### 1.1 文件清单与正式调用链

排除 `._*` 与 `__pycache__` 后，目录有 107 个文件，其中 103 个 Python 文件。静态审计脚本读取了 138 个输入项；其报出的 4 个 HIGH 均来自 `charging.py` 中 “No feasible charging insertion” 字符串被误识别成 SQL 关键字，人工复核后不是安全漏洞。

当前可证的正式链如下：

```text
setp_solver.algorithms.resetp_alns.api
  └─ run_resetp_alns = run_winner_kernel                 api.py:19-20
      ├─ kernel/winner.py / kernel/alns_core.py
      ├─ operators/*
      ├─ support/*
      └─ shared referees
          ├─ cost.py
          ├─ check.py
          └─ search/evaluation.py                       PROVENANCE.md:49-56

动态主入口 search/dynamic.py
  └─ from ..algorithms.resetp_alns import ...           dynamic.py:21-29
      ├─ full-information static call                   dynamic.py:713-721
      └─ rolling-stage call                             dynamic.py:1289-1295

历史兼容入口
  ├─ search/alns_wouda.py
  ├─ search/winner_operators.py
  └─ search/resetp_alns/*
      └─ re-export algorithms/resetp_alns               PROVENANCE.md:58-60
```

正式入口是 `algorithms/resetp_alns`，但“完全私有”只成立到一部分模块。`support/charging.py:27` 反向导入 `search.charging._curve_aware_action`；`runtime/budgeted_scoring.py:49,64,79` 反向导入 `search.e3_multitrip_runtime`；`winner.py` 还读取 `search.bundle`、`search.candidates`、`search.multitrip_schedule` 和 `search.metaheuristic_baselines`。因此不能把整个 `search/` 视为旧目录。

### 1.2 已无当前调用者的函数和模块

确认两个正式内核死函数：`multi_customer_removal` 和 `identity_repair`。当前 destroy/repair 注册表不含它们，全仓符号检索只命中定义，`identity_repair` 另有一项测试明确断言它不应出现在活动 repair 计数中。详见 `X2-DC-001/002`。

确认两个只服务旧诊断链的当前无调用模块：`search/e2_alns_scan_bridge.py` 是退役 E2 gate CLI，`search/lns_policy_kernel.py` 只被旧 A13 probe 与测试调用。二者不能直接删除，因为旧包仍需要复现；建议是随父证据包归档。详见 `X2-DC-003/004`。

### 1.3 同语义多份实现

`search/` 与正式 `algorithms/resetp_alns/support/` 有九对同名模块：

| 语义 | search 行数/哈希前缀 | formal support 行数/哈希前缀 | 当前正式链 |
|---|---|---|---|
| charging | 837 / `c1cf2efe` | 1081 / `09eb2bc4` | formal，但反向依赖 search helper |
| construction | 628 / `d0a7598b` | 628 / `344220f7` | formal |
| elite_archive | 67 / `ac1f02a1` | 67 / `0dbf1b2e` | formal |
| fleet | 320 / `e3644199` | 320 / `40066c29` | formal |
| fleet_charge_corepair | 143 / `a9a4f5f0` | 165 / `29e77b18` | formal |
| global_order_repack | 146 / `feed646a` | 172 / `6beef128` | formal |
| order_decoder | 287 / `89dd66d7` | 287 / `4894198f` | formal |
| route_pool | 101 / `1ba0e98e` | 101 / `42996573` | formal |
| timing | 55 / `218eb77b` | 55 / `218eb77b` | 两份逐字节相同 |

PROVENANCE 的正式约定是 ALNS 用 formal 私有副本，baseline 保留 search 副本，故八对差异实现没有逐函数等价证明前不应机械合并。`timing.py` 是明确的完全重复；`charging.py` 则因交叉依赖不能独立归档。详见 `X2-RI-002/003`。

此外，`search/formal_runner.py` 仍保留 E0-E7 通用正式 runner，`solver/scripts/run_winner_formal_export.sh:30-82` 等脚本仍调用它；2026-08-01 China 实验已改为 `baselines/china_e3_e7/` 各专包 runner。这是两条正式执行路径并存，详见 `X2-RI-005`。

### 1.4 三个受保护文件中的历史开关或分支

| 文件 | 历史兼容分支 | 当前判定 |
|---|---|---|
| `cost.py:73-93` | `n_slots=None` 使用旧 NESO 18 槽；China81 实际 48 槽 | 影响当前主线，漏参会静默错槽；`X2-PD-002` |
| `cost.py:110-123` | 没有 city 字段时接受历史共享 time profile | 历史兼容仍有用；不得仅因英国轨退役删除 |
| `cost.py:494-523` | 旧 L100 ChargingAction 可缺省曲线 metadata；NL90 会 fail closed | 保留历史复算，当前 NL90 不会静默降级 |
| `check.py:39-65,179` | 公平硬约束默认关闭，仅显式 `FairnessContext` 启用 | 公平已降为模型组件，保留公式接口，不作为当前正式实验开关 |
| `check.py:79-103` | DynamicCheckContext 为可选，静态检查仍默认 | 动态需求是当前柱子，应保留并在正式入口显式启用 |
| `search/evaluation.py:54-60` | fairness 默认 false；allow_cross_depot 默认 true | 保留当前主线默认；旧 E3 owner-lock 分支见 `:125-143` |
| `search/evaluation.py:125-143` | 注释明确是 controlled E3 arm，默认 permissive | 已退役实验分支；当前只作为模型兼容，不应被新 runner 隐式开启 |

### 1.5 默认值与正式取值不一致

确认四个直接影响当前主线的默认错位：`DEFAULT_PRICES` 是 UK/Goeke 而正式 China81 显式覆盖；碳时段默认 18 而正式为 48；严格多趟环境开关默认 0 而论文按多趟叙述；fleet loader 默认 v1 而 v2 已生成。另有 E5 专用时间价值 75 CNY/h 与默认 0 的有意差异，因 E5 已退役为实验柱子，当前应保持 0。详见 `X2-PD-001`—`004`、`008`。

### 1.6 本范围未完成边界

已完成 107 文件清单、AST/符号级无调用筛查、正式入口及其反向依赖、九对重复模块的哈希比较、三个受保护文件关键历史分支核对。未完成其余 103 个 Python 文件逐文件逐行人工通读，也未为每个公开符号建立仓库外调用者证明；所以本范围不是终态。

## 2. 实验目录 `baselines/`

下表的“外部 metadata 引用”是：在 `baselines/**/metadata.json` 中命中该顶层路径、且引用文件不位于该目录自身的文件数。文件数排除 `._*` 与 `__pycache__`。论文引用按 `paper_main.tex` 的实际 TeX 转义路径人工核对。

| 顶层目录 | 有效文件 | 当前属性 | paper_main.tex 引用 | 外部 metadata 引用 | 能否直接安全归档 |
|---|---:|---|---|---:|---|
| `algorithm_foundation` | 528 | 旧算法基础/门链 | 否 | 2 | 否，先保引用映射 |
| `algorithm_prototypes` | 2983 | 混合：大量退役原型 + 当前 4.2 raw data | 是，`:1296` | 2253 | 否 |
| `china_e3_e7` | 7013 | 混合：当前 E4、E7 设计诊断 + 旧 E3/E5/E6/E7 | 数值引用、无路径 | 4 | 否 |
| `china_instances` | 122 | 当前 China81 authority builders + 旧版本 | 否 | 5 | 否 |
| `contract_audit` | 33 | 旧合同审计 | 否 | 0 | 是，仅就本次两类引用面 |
| `e1_model` | 64 | 旧 E1 | 否 | 0 | 是，仅就本次两类引用面 |
| `e2_alns` | 14309 | 英国轨/280 kWh/09x-y/DR/E2 门链 | 否 | 24 | 否 |
| `e2_final_campaign_20260720` | 15033 | 混合：旧 campaign + 当前论文表体 | 是，`:964,:1240` | 13 | 否 |
| `e2_rerun_unified_01_20260727` | 9180 | 旧统一重跑 | 否 | 1 | 否 |
| `e2_rerun_unified_01_step0_20260727` | 216 | 旧 step0 | 否 | 0 | 是，仅就本次两类引用面 |
| `e3_ablation` | 3405 | 旧 E3 路线 | 否 | 13 | 否 |
| `e4_e5` | 231 | 旧 E4/E5 路线 | 否 | 6 | 否 |
| `e6_fairness` | 1510 | 旧 E6 正式实验路线 | 否 | 11 | 否 |
| `e7_dynamic` | 1306 | 旧 E7/T9 路线 | 否 | 4 | 否 |
| `experiment_infrastructure` | 42 | 共用 absolute harness，是否复用待定 | 否 | 0 | 暂不归档，仍是共用工具候选 |
| `formal_20260621_10001_lmain_10seed` | 212 | 旧 L-main 正式包 | 否 | 0 | 是，仅就本次两类引用面 |
| `formal_..._fallback3600` | 5 | 旧 fallback | 否 | 0 | 是，仅就本次两类引用面 |
| `model_verification` | 52 | China 非线性/动态/公式核验，模型组件证据 | 否 | 1 | 否，当前第 2 章仍可能引用其模型闭合证据 |
| `paper_story` | 12 | 旧稿故事生成器 | 否 | 0 | 是，仅就本次两类引用面 |
| `statistics` | 9 | 旧 MC002 power gate | 否 | 0 | 是，仅就本次两类引用面 |

这里的“可以归档”只表示本次扫描未发现论文或外部 metadata 路径依赖，不表示可以删除。凡外部 metadata 引用数大于 0，均未判为可删。

### 2.1 当前主线证据

当前必须保留的证据包括：`algorithm_prototypes/china81_vs_opensource_20260727`（论文 4.2）、`e2_final_campaign_20260720` 中两份论文表体、`china_e3_e7/e4_carbon_timing_20260729`、`china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801`、China81 当前 authority 和 `model_verification` 中仍服务第 2 章模型组件的核验包。

`china_e3_e7/e7_o2_dispatch_20260801/zero_search_15_streams_20260801/decision.json:2-13` 明确 `formal_result=false`、`solver_runs=0`、`status=PASS_E7_O2_ZERO_SEARCH_TIMING_DIAGNOSTIC`，只能作为第 5.3 设计输入，不能当动态需求正式结果。

### 2.2 已退役路线

已明确退役的主群是英国轨、280 kWh 诊断、DR-ALNS 训练线、E2 门链、E3/E5/E7 历次 HALT 包，以及旧 E6 公平正式实验。它们的科学权威已失效，但 provenance 仍有效；处置只能是完整归档，不是散删。`china_e3_e7/e7_dynamic_20260731/decision.json` 的终态是 `HALT_PROBE_STARTUP_KEYERROR_INSTANCE_PATH` 与 `NO_E7_SCIENTIFIC_RESULT`，是典型的“保留故障证据、撤销活入口”。

### 2.3 AppleDouble 污染

扫描计得 `solver/src/setp_solver` 151、`baselines` 16857、`docs/handoff` 294 个 `._*`。新哈希必须继续排除它们；但至少 35 份现存 metadata/decision/artifact manifest 已记录这些路径，所以本轮没有把它们判为可直接删除。详见 `X2-RA-006`。

### 2.4 本范围未完成边界

已完成 20 个顶层目录的文件计数、论文正向引用、外部 metadata 路径引用计数，以及指定英国轨/280/DR/E2/E3/E5/E7 资产的终态抽查。未完成 56265 个有效基线文件逐包读取，也未为每个二级/三级 attempt 建立完整归档边界；顶层“可归档”结论只能按表中限定使用。

## 3. 配置与算例

### 3.1 China81 当前显式 authority

`china81.py:37-55` 当前绑定：static corrected v3、matrix corrected v10、order GIS v2、vehicle lock v2、runtime parameter authority v4、finite fleet authority v1。`baselines/china_instances/` 同时保留早期 draft、matrix v2/v9、runtime v3、fleet v2 等生成器，不能靠文件名自动选择。详见 `X2-PD-007`。

### 3.2 v1/v2 fleet authority

v1 与 v2 `decision.json` 都是 81 instances、144 fleet rows、reserve factor 1.25；两份 `fleet_caps.csv` 逐行数值相同。v2 builder 2-9 行宣称按新 EV 参数重算，但定容函数仍只用 CV 载重与时间窗，EV 数仍由 `ceil(0.25R_d)` 派生。最新 `HANDOFF.md:5458-5477` 已确认 0.25 无外部依据并导致 E4/E6 EV 上限触顶。

所以这不是“v1 旧、v2 新，切路径即可”的普通版本漂移，而是两个版本共享同一无出处构造规则。当前第 5.2 要解决的是车队规模/构成权威本身，非版本号。

### 3.3 价格和模型默认

| 字段 | `DEFAULT_PRICES` | China81 `_china_prices` | 判定 |
|---|---:|---:|---|
| `Q_capacity` | 3650 kg | 1735 kg | 场景不同 |
| `B_battery_kwh` | 80 kWh | 77.28 kWh | 场景不同；China 注释称 compatibility field |
| 柴油价 | 1.4331 GBP/L | 9 城市 7.43—7.50 CNY/L | 单位和来源都不同 |
| 公共电价 | 0.82 GBP/kWh | 48 槽城市 profile 均值 | 时序结构不同 |
| 固定费 | 80 GBP/dispatch | 170 CNY | 单位不同 |
| `c_km` | 0.35 GBP/km | 0.78 CNY/km | 单位不同 |
| 充电曲线 | L100 | NL90 mild | 物理语义不同 |

China81 正常 loader 显式覆盖这些值，真正风险在于正式算法多个函数的参数默认仍是 `DEFAULT_PRICES`：漏传时不会自动知道自己在 China 场景。详见 `X2-PD-001`。

### 3.4 正式包锁定哈希与当前源码

| 文件 | China81 vs opensource metadata 锁定 | 当前 SHA-256 | 一致 |
|---|---|---|---|
| `china81.py` | `df082b6a...` | `c70133cf...` | 否 |
| `check.py` | `9c81e254...` | `86b81315...` | 否 |
| `cost.py` | `2717b4b4...` | `7f59a47a...` | 否 |
| `search/evaluation.py` | `c7215263...` | `c7215263...` | 是 |

论文 `:1296` 锁定的 raw data 本身哈希 `4291ee...` 当前仍一致；不一致的是生成它的源码快照与当前模型源码。它可以作为封存算法比较，但不能无说明地称为“当前模型下结果”。详见 `X2-PD-006`。

### 3.5 碳字段

`china81.py:803-817` 用同一 `carbon_factor` 同时生成 forecast 与 actual。论文 `:1043-1054` 已正确披露 `forecast=actual`，所以当前时变碳主线成立，预测误差主张不成立。详见 `X2-PD-005`。

### 3.6 本范围未完成边界

已核对 `china81.py`、`prices.py`、四条核心 authority、fleet v1/v2 和论文算法包的关键 source hash。未对 81 个算例的每个 `nodes.csv`、矩阵块、48 槽日历与所有正式包锁定哈希做全量逐文件重算；也未审完 59 个 China builder 的每个字段覆盖关系。

## 4. 论文与产物悬挂引用

### 4.1 正向核对

| TeX 行 | 目标 | 存在 | SHA-256 前缀 |
|---:|---|---|---|
| 693 | `generated_figures/algorithm_flow.tex` | 是 | `e1d5ca3d` |
| 964 | `e2_final_campaign.../instance_details_table_body.tex` | 是 | `4f99e5b0` |
| 1051 | `generated_figures/figure3_carbon_profile_v14.pdf` | 是 | `942b2e39` |
| 1240 | `e2_final_campaign.../table8a_mechanism_case.tex` | 是 | `6dcad72d` |
| 1246 | `generated_figures/figure4_convergence_v14.pdf` | 是 | `f83a387a` |
| 1354-1357 | `figures_e2_v2_20260730/fig_e2_performance_profile.pdf` | 是 | `479ca2d3` |
| 1462-1465 | `figures_e4_20260731/figure_e4_timing_migration.pdf` | 是 | `6d059040` |

没有发现路径不存在的正向表图引用。`\IfFileExists` 两处当前也确实存在，不会落入占位框。

### 4.2 反向核对

两份当前 E4 decision 的数值在 TeX `:1431-1458` 中逐项出现，但 TeX 未记录包路径。`e4_joint_routing` decision 的 `paired_unit_count=30,row_count=90,status=PASS_E4_FORMAL_PANEL_AGGREGATED`；`e4_carbon_timing` decision 的 `observed_pair_rows=expected_pair_rows=11340,status=PASS_COMPLETE_ZERO_SEARCH_REPLAY`。这是当前主线最需要补记的反向来源，详见 `X2-HR-002`。

算法 `raw_runs.json` 则相反：TeX 已给路径和哈希，但包锁定旧源码快照。路径存在不等于语义当前，详见 `X2-PD-006`。

### 4.3 结构悬挂

当前稿 `:1472` 仍进入“合作收益与联盟分配”，而 `:1471` 把 E7 留在待正式设计状态。这与已批准骨架相反：协同/分账应回第 2 章模型组件，动态需求必须形成第 5.3 正式结果。详见 `X2-HR-003`。

### 4.4 本范围未完成边界

已完成 `paper_main.tex` 全部 7 组论文资产 `input/includegraphics/IfFileExists` 目标的存在性与哈希核对，以及 E4/E2 关键产物的反向核对；第 18 行另有一个用户字体绝对路径的条件检查，它有内置回退且不属于实验产物。未对正文每一个手写数字、每张内嵌表、全部 87 个 paper_v2 图/TeX/PDF 资产建立逐字段 source map，因此反向“哪些正式产物已无处引用”仍不是全量终态。

## 5. 文档层失效关系

### 5.1 当前覆盖关系

| 旧文档 | 旧自称地位 | 当前覆盖者 | 仍有效部分 |
|---|---|---|---|
| `project_prd_execution_map_v2_20260702.md` | 全项目 PRD/施工图 | `HANDOFF.md:5141-5164,5411-5442` | 记录纪律、禁改语义、闭路台账 |
| `project_planning_map_20260701.md` | 规划地图 | 同上 | 事实源优先级与证据诚实边界 |
| `codex_prompts/MASTER_codex_takeover_plan.md` | 接管总规划 | READ_ME `:30-43` 已判主体历史；HANDOFF 8/2 定主线 | 保护文件、四同步、旧路线教训 |
| `e1_e7_submission_contract_decision_20260711.md` | 唯一投稿拍板单 | HANDOFF 8/2 用户新决定 | 旧 E2-E7 包的决策 provenance |
| `e3_e7_experiment_product_design_20260712.md` | E3-E7 设计权威 | HANDOFF `:5148-5157` | 历史实验设计和产物解释 |
| `paper_north_star_20260713.md` | 迷路入口 | HANDOFF `:5411-5442` | 旧协同故事来路 |
| `diagnosis_and_remediation_master_20260731.md` | E3/E5/E7 整改唯一入口 | memory index `:56-58`、HANDOFF 8/1-8/2 | 失败根因历史 |
| 两份 7/29-7/30 session handoff | 冷启动第一入口 | 8/1 重建正文、8/2 HANDOFF | 故障现场和 watchdog 教训 |

### 5.2 最危险的内部冲突

`READ_ME_FIRST_FOR_AGENTS.md` 一边正确说明 PRD/planning/MASTER 主体退役，一边仍把 20260711-29 E3-E7 合同列为“当前权威链”，又把 L-main v2/E2 重采写成“当前最高优先级”。由于它是每个代理的强制第一入口，这个冲突比普通旧文档更危险。详见 `X2-DF-001`。

`diagnosis_and_remediation_master_20260731.md:873-874` 说 v1/v2 数值全等所以是否切换不影响任何计算；这个算术事实仍真，但其管理推论已被最新发现覆盖：两版共用的无出处 0.25 规则会锁死车队电动化自由度。详见 `X2-DF-005`。

### 5.3 本范围未完成边界

`docs/handoff/` 当前有约 660 个有效文件。本轮完成强制入口、旧权威链、两份 session handoff、diagnosis master、memory index 和当前主线附近文档的覆盖关系；未逐文件阅读其余数百份专题报告、prompt、memory 节点并建立完整 DAG。因此这里只登记已证冲突，不宣称文档层全盘完成。

## 扫描完成边界

本轮完成到以下可复核边界：

1. 范围 1：完成文件清单、静态调用图、正式链、重复模块哈希、死符号候选和受保护文件关键分支；未完成 103 个 Python 文件逐行人工通读。
2. 范围 2：完成 20 个 baselines 顶层目录、论文引用和外部 metadata 引用计数；未完成每个子包四/五件套逐条闭合。
3. 范围 3：完成 China81 当前 authority、fleet v1/v2、默认价格/时段/多趟和关键 source hash；未完成 81 算例全文件 hash 重算。
4. 范围 4：完成全部显式 TeX 文件引用；未完成所有手写数字和全部正式产物的全量双向映射。
5. 范围 5：完成最危险旧权威文档的覆盖关系；未完成 `docs/handoff/` 全文件 DAG。

因此终态为 `X2_LEGACY_SWEEP_PARTIAL`。所有具体处置建议仅登记在 `legacy_ledger.json`，本轮未执行。
