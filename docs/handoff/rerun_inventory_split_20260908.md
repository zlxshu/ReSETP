# 论文展品 → 生成器 → 数据目录 → 运行命令 全盘点（split 默认口径重跑前）

**日期**：2026-09-08　**性质**：只读盘点，未跑任何求解器、未改任何既有文件。
**配套产物**：`solver/reports/rerun_split_20260908/{joblist.txt, run_one.sh, README.md}`。

---

## 0. 前置事实：新默认已经生效

`solver/scripts/run_problem_hgs_private_technical.py:1888-1890`
的 `--public-station-candidate-mode` 默认值是 `SPLIT_PUBLIC_STATION_CANDIDATE_MODE`，
该常量在 `solver/src/setp_solver/algorithms/resetp_alns/support/charging.py:71` 定义为 `"split"`。

**注意一个容易踩的坑**：同一文件第 70 行的
`DEFAULT_PUBLIC_STATION_CANDIDATE_MODE = FALLBACK_PUBLIC_STATION_CANDIDATE_MODE`（即 `"fallback"`）
仍然是底层库函数的默认。两个默认不是一回事——**只有走正式入口脚本才拿到 split**。
重跑清单里的命令一律不写这个开关，靠入口默认生效。

---

## 0.5 展品编号对照（取自 `docs/paper_v2/paper_main.aux` 的 `\newlabel`，不是我数的）

| 编号 | label | 展品 |
|---|---|---|
| 表1–表6 | literature-comparison / unified-symbols / initial-nodes / public-stations / dynamic-nodes / parameters | 综述、符号、客户点、公共站、动态需求、参数 |
| 表7 | `tab:final-solution` | 仿真实验最终路径表 |
| 表8 | `tab:benchmark-results` | 标准算例结果表 |
| 表9 | `tab:component-ablation` | TVGCI-CMDMF-DVRP 模型实验（消融） |
| 表10 | `tab:fleet-config` | 不同动力配置下的配送方案对比 |
| 表11 | `tab:carbon-charging` | 不同充电安排下的配送方案对比 |
| 表12 | `tab:charging-windows` | 四种充电安排在各补电窗口… |
| 表13 | `tab:fleet-levels` | 不同碳减排政策下的配送方案对比（＝政策表，标签名有历史包袱） |
| 表14 | `tab:synergy` | 不同配送模式对比 |
| 表15 | `tab:allocation` | 协作配送成本分摊结果 |
| 表16 | `tab:allocation-methods` | 四企业算例下不同分摊方法的结果对比 |
| 表17 | `tab:dynamic` | 动态需求下不同处理方式的求解结果 |
| 图1 | `fig:algorithm-flow` | 算法流程图 |
| 图2 | `fig:experiment-carbon-intensity` | 逐时电网碳强度 |
| 图3 | `fig:convergence` | PR17B 收敛过程 |
| 图4 | `fig:tariff-carbon-windows` | 分时电价、电网碳强度与补电窗口 |
| 图5 | `fig:mechanism` | 机理图 |
| 图6 | `fig:carbon-price-sweep` | 不同单位碳价下的车队构成… |
| 图7 | `fig:collaboration-fairness-routes` | 不同配送模式的配送路径 |

## 1. 展品 → 生成器 → 数据目录 → 命令（正文顺序）

`\input` / `\includegraphics` 一栏写的是 `docs/paper_v2/` 下的相对路径。
"命令" 一栏：`metadata.json` 里**没有** `command` / `argv` / `cli` 字段——已在三个不同批次上逐字段核过
（`grid2x2_v3` 的 MTC-HGS run_01、`public28_formal_20260830/PR17B/run_01`、
`fleet_composition_formal_v3_20260904/3-3/A0-0_B3-3/run_1`，命令类字段 0 命中），
完整命令一律来自各批次目录下的 `joblist.txt`。

### 1.1 无数据依赖的展品（不需要重跑）

| 展品 | 位置 | 来源 |
|---|---|---|
| 表 1 相关研究内容比较 | tex 内硬编码 | 文献综述，手写 |
| 表 2 符号说明 | tex 内硬编码 | 手写 |
| 表 3 初始客户点和车场详细信息 | tex 内硬编码 | 算例静态数据 |
| 表 5 动态需求信息 | tex 内硬编码 | 算例静态数据 |
| 表 6 主要参数设置 | tex 内硬编码 | 参数权威文件 |
| 图 1 算法流程图 | `generated_figures/figure_1_algorithm_flow.pdf` | 同名 `.tex`（TikZ 手绘），无数据 |
| 图 5 机理图 | `\input{generated_figures/figure_5_mechanism.tikz}` | TikZ 概念图，明确"无数字" |

**表 4 公共充电站信息表**（`\input{generated_tables/public_station_table.tex}`）
生成器 `solver/scripts/build_public_station_table.py`，只读算例
`data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/nodes.csv`
里 `node_type=station` 的行编号成 S01–S97，**不读任何 run 产物，不需要重跑**。

### 1.2 需要重跑的展品

| 展品 | 生成器 | 数据目录 | 臂/格 | 每格次数 | 单跑墙钟中位 | 命令模板出处 |
|---|---|---|---|---:|---:|---|
| **表 9** TVGCI-CMDMF-DVRP 模型实验（消融） | `solver/scripts/backfill_table8.py`（env `TABLE8_BATCH`）→ `generated_tables/table8_rows.tex` | `solver/reports/ablation_v6_20260906/`：`M-HGS` 本批真跑；`MT-HGS`/`MTC-HGS` 是**符号链接**指向 `grid2x2_v3_20260906/beijing/P=0.2/{MT-HGS,MTC-HGS}` | M / MT / MTC | 10 | M 臂 2.5 分 | `ablation_v6_20260906/joblist.txt`（10 条，只有 M 臂） |
| **表 11** 不同充电安排下的配送方案对比 | `solver/scripts/build_charging_arrangements_table.py` → `carbon_charging_table.tex` | `grid2x2_v3_20260906/beijing/P=0.2` ＋ `charging_arrangements_20260906` | 有电即充 / 只看电价 / 只看碳 / 电价＋碳价 | 10 | 3.6–5.2 分 | `charging_arrangements_20260906/joblist.txt`（20 条）＋ `grid2x2_v3_20260906/joblist.txt` |
| **表 12** 四种充电安排在各补电窗口的充电开始时刻、成本与碳排量 | `solver/scripts/build_charging_windows_table.py` → `charging_windows_table.tex` | 同表 11 四个目录 | 同上 | 10 | 同上 | 同上（同一批数据，**不额外跑**） |
| **图 4** 分时电价、电网碳强度与补电窗口的时段关系 | `solver/scripts/generate_tariff_carbon_window_figure.py` | 只读日历（不读 run 产物） | — | — | — | 无（画日历，**不需重跑**） |
| **表 13** 不同碳减排政策对比 | `solver/scripts/build_policy_table.py` → `policy_table.tex` | 见 §2 十行明细 | 10 行 | 3 或 10（逐行不同） | 3.4–6.9 分 | `policy_combos_20260907/joblist.txt` ＋ `joblist_acceptance.txt`；扫描两行来自 `carbon_price_sweep_v3_20260906/joblist.txt` |
| **图 6** 不同单位碳价下的车队构成、碳排量与首趟前补电时刻 | `solver/scripts/generate_carbon_price_response_figure.py` | `solver/reports/carbon_price_sweep_v3_20260906/P=*/run_*/best_solution.json` | 22 档 | 3 | 3.9 分（本批 15 档）/ 5.6 分（沿用 7 档） | `carbon_price_sweep_v3_20260906/joblist.txt`（45 条，只 15 档）＋ `carbon_price_sweep_v2_20260906/joblist.txt`（另 7 档，见 §3） |
| **四格对照批**（当前 tex 里没有独立表号；表 13 的基准／午谷／碳价 1.0 三行取自这里） | `solver/scripts/build_grid2x2_table.py`（当前 tex 未 `\input` 其输出，但 `build_policy_table.py` 复用它的目录） | `solver/reports/grid2x2_v3_20260906/{beijing,midday}/P={0.2,1.0}/{MT-HGS,MTC-HGS}` | 4 格 × 2 臂 | 10 | 3.6–6.9 分 | `grid2x2_v3_20260906/joblist.txt`（80 条） |

### 1.3 需要重跑但本清单未列入（原因逐条写明）

| 展品 | 生成器 / 数据目录 | 为什么不列入 |
|---|---|---|
| **表 10** 不同动力配置下的配送方案对比（7 档） | `solver/scripts/run_fleet_composition_one.sh`；数据 `solver/reports/fleet_composition_formal_v3_20260904/{0-6…6-0}/` | **受影响**（充电成本列 0→217.97 非零）。但它的 `joblist.txt`（84 条）与 `joblist_reps.txt`（28 条）存的是 `0/0\|0/6\|1` 这种**规格行**，不是完整命令，消费者是专用 shell，与本批 `run_one.sh` 的"整行即命令"格式不兼容，要另起一份清单。另注：该 runner 的参数集比现行批**旧**——没有 `--stop-after-nonimproving-rounds 2`、没有 `--tariff-calendar-authority`、没有 `--first-trip-window prev_return`。 |
| **表 14** 不同配送模式对比 / **表 15** 协作配送成本分摊 | `solver/scripts/run_synergy_batch_20260819.py`（12 个子跑：独立×3、联合×3、ENT_A×3、ENT_B×3）＋ `run_two_enterprise_allocation.py` ＋ `coalition_accounting_adapter.py` | 该驱动写死的输出根 `solver/reports/paper_aligned_collaboration_20260829/` **在磁盘上不存在**（已被清理，git 里也查不到）。且驱动的参数集陈旧：碳价 `0.07502`、`--frvcpy-charging`、用 `/opt/anaconda3/bin/python3.13` 而非 `.public-hgs-venv`、无 `--first-trip-window` / 无 `--stop-after-nonimproving-rounds`。**要先由用户裁定用哪套参数**，不能照抄重跑。 |
| **表 16** 四企业算例下不同分摊方法的结果对比 | 数据 `solver/reports/coalition_prd150_20260830/{D1..D4, pairs_seeded}` | 算例是 `cn-prd-150c-01-V3-TWO-SHIFT-PRDFIX`——**PRDFIX 系退役算例**。且磁盘上只有 4 个单企业与部分两两联盟，正文声称的"枚举全部 15 个联盟"在这个目录里凑不齐；也没有驱动脚本。**须用户裁定**。 |
| **表 8** 标准算例结果表 / **图 3** PR17B 收敛过程 | 数据 `solver/reports/public28_formal_20260830/PR{11..24}{A,B}/run_01..10`；图 3 取 `PR17B/run_09_trajectory.csv` | 目标函数是纯行驶距离的多车场带时间窗，`metadata.json` 里 `purpose = "independent Problem-HGS public run"`、无任何充电/碳字段——**充电修复层动不了它**。且该目录下**没有 joblist / launcher.log / README**，完整命令无从复原（不猜）。生成器脚本也未找到（`figure_2_public_pr17b_convergence` 与 `figure_experiment_carbon_intensity` 在全仓 `*.py` 里 0 命中）。 |
| **图 2** 逐时电网碳强度 | `generated_figures/figure_experiment_carbon_intensity.pdf` | 画的是算例日历，不依赖 run 产物；生成器脚本未找到（见上）。 |
| **图 7** 不同配送模式的配送路径 | `solver/scripts/generate_route_schematic_figure.py` | 只读 `solver/scripts/assets_route_schematic_geometry.json`（示意几何，写死），不读 run 产物。若表 14 重跑后路线变了，这张示意图要人工复核。 |
| **表 7** 仿真实验最终路径表 | `solver/scripts/generate_final_solution_table.py` → `final_solution_trip_rows.tex` | **不需要新批次**：脚本把 run 目录当 `argv[1]` 收，默认值是 `solver/reports/ablation_reseed_20260901/MTC-HGS/run_1`。重跑后把它指向新的 MTC-HGS 最优 run 即可。**但请注意**：这个 09-01 的批次现行流水线里已经没有别的展品在用，最终解和表 9/表 11 的最优解不是同一批。 |
| **表 17** 动态需求下不同处理方式的求解结果 | 见 §4 | 按派工指令**只盘点、不列入清单**。 |

---

## 2. 表 13（不同碳减排政策下的配送方案对比）十行明细

生成器 `solver/scripts/build_policy_table.py` 的 `ROWS`（第 116–155 行），
聚合口径 `ROW_STATISTIC = "mean"`：**不带 `runs=` 字段的行取该目录下全部
`best_solution.json` 的算术均值**；碳价扫描两行走另一条路——
把 `carbon_price_sweep_v3_20260906/` 下**全部 66 个** `best_solution.json`
按该行目标碳价重新核算总成本后取最低者（`CARBON_SWEEP_POOL_DIR`）。

| # | 类别 | 行 | 数据目录 | 磁盘次数 | 入表次数 | 本次重跑条数 |
|---:|---|---|---|---:|---:|---:|
| 1 | 基准 | 北京现行时段，碳价 0.20 | `grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS` | 10 | 10 | 10（在 grid2x2 80 条内） |
| 2 | 价格信号协调 | 充换电设施谷段设在午间 | `grid2x2_v3_20260906/midday/P=0.2/MTC-HGS` | 10 | 10 | 10（同上） |
| 3 | 价格信号协调 | 午间充电按谷价补贴 | `policy_combos_20260907/green_window` | 3 | 3 | 3 |
| 4 | 碳定价 | 碳价降至现行 0.075 | `carbon_price_sweep_v3_20260906/P=0.07502` | 3（**符号链接→v2，旧窗口**） | 池内择优 | 3（本批首次真跑） |
| 5 | 碳定价 | 碳价升至 1.0 | `grid2x2_v3_20260906/beijing/P=1.0/MTC-HGS` | 10 | 10 | 10（在 grid2x2 内） |
| 6 | 碳定价 | 碳价升至 1.5 | `carbon_price_sweep_v3_20260906/P=1.5` | 3 | 池内择优 | 3（在扫描 66 条内） |
| 7 | 碳定价 | 碳配额与交易（配额 200 kg） | `policy_combos_20260907/quota200` | 3 | 3 | 3 |
| 8 | 车队经济性 | 购置补贴（折 24 元/日） | `policy_combos_20260907/subsidy_alone` | **10** | **10** | **10** |
| 9 | 组合 | 谷段设在午间＋碳价升至 1.0 | `grid2x2_v3_20260906/midday/P=1.0/MTC-HGS` | 10 | 10 | 10（在 grid2x2 内） |
| 10 | 组合 | 谷段设在午间＋购置补贴 | `policy_combos_20260907/midday_subsidy` | 10 | **只取 run_01–03** | 3 |

正文自己也写明了这个 3/10 混合口径（`paper_main.tex` 第 1241–1242 行）：
"其中现行碳价、碳价1.5元/kgCO₂e、午间充电按谷价补贴、碳配额以及谷段设在午间＋购置补贴
五种情形运行3次，其余情形运行10次"。上表与这句逐行对得上。

第 10 行的 `runs=("run_01","run_02","run_03")` 是代码里第 148–153 行那条
2026-09-08 的用户裁定。**与之冲突的一条事实**：
`docs/handoff/CURRENT_PROJECT_CONTEXT.md` 顶部 09-08 00:30 那条记着这一行补到 10 次后
是 −104.99 元 / −61.44 kg，并写明"3 次的 −80 kg 坍成 −61 kg，'相互增强'删"。
即：3 次能重建表格那一行，重建不出正文引用的 10 次数字，而 3 次恰是已被证明在这一行上不稳的深度。
本次按派工指令列 3 条，**要不要补到 10 条须用户拍板**。

### 正文里手工引用、不经生成器的数字

| 数字 | 出处 |
|---|---|
| 天花板"再减少 15.7 kgCO₂e（8%）"、盈亏平衡碳价 1.48 元/kgCO₂e | 只读诊断 `solver/scripts/diagnose_charging_windows_20260906.py`（读 `grid2x2_v3_20260906/beijing/P=0.2/{MT-HGS,MTC-HGS}` ＋ `charging_arrangements_20260906/{cost_min,carbon_min}`），报告 `docs/handoff/charging_window_root_cause_20260906.md` |
| 公共桩多付 0.67 元/kWh 换 0.45 kg | `docs/handoff/station_topup_algorithm_design_20260907.md` 第 159 行（离线上限探针，产物 `solver/reports/probe_station_topup_20260907/`） |
| 最优车队在 1.24 与 1.52 元/kgCO₂e 两处翻转 | 方案池重核算，`solver/scripts/generate_carbon_price_curve_figure.py` / `generate_carbon_price_response_figure.py`，池 = `carbon_price_sweep_v3_20260906` 全部 66 个解 |
| 46.97 元/日补贴档（新情形用） | `docs/handoff/combo_margin_design_20260908.md`；口径写死在 `solver/scripts/probe_combo_margin_20260908.py:95-96,207`，产物 `solver/reports/probe_combo_margin_20260908/margin_table.csv` |

这四处**都只依赖上面那些 run 目录**，重跑后重算即可，没有额外批次。

---

## 3. 碳价扫描目录的符号链接问题

`solver/reports/carbon_price_sweep_v3_20260906/` 下 22 个 `P=` 目录里，
**只有 15 个是本批真跑**（`P=0.0` 与 `P=0.7 … P=2.0`，`joblist.txt` 45 条）；
另外 7 个（`P=0.07502`、`P=0.1` … `P=0.6`）是指向
`carbon_price_sweep_v2_20260906/` 的符号链接，里面的解是用**旧窗口 `same_day`** 跑的
（v3 自己的 `README.md` 写明了这一点和沿用条件）。

表 13 第 4 行（碳价 0.075）和图 6 的低碳价段都落在这 7 档里。
重跑清单按 v3 README 记录的派生规则把这 7 档补成真跑
（逐字取 v2 同名行、目录改到 v3_split、行尾补 `--first-trip-window prev_return`），
**这是它们第一次在统一窗口口径下真跑**。

---

## 4. 动态需求实验（只盘点，不列入清单）

- **正文位置**：4.9 节「不同动态处理策略对比分析」，表 17。
  另有 4.1 节表 5「动态需求信息」（算例静态数据，与本节数据不同源）。
- **脚本**：`solver/scripts/run_dynamic_experiment.py`，
  签名 `run_dynamic_experiment.py <output_dir> [--data-repo-root ...] [--dry-run] ...`。
- **数据目录**：`solver/reports/submission_fallback_20260824/56_dynamic_formal_seed1_single_seed_corrected/`
  （同一份产物镜像在 `solver/reports/paper_submission_supplement_20260829/dynamic/seed_2396617133/`）。
  表 17 的数字与 `paired_results.csv` 逐位吻合：
  `mechanical_realized_cost = 3823.798108983845`（正文的"顺序插入策略"）、
  `dynamic_realized_cost = 4263.144930919208`（"滚动重优化策略"）、
  `static_reference_cost = 4137.861664078202`（"完全信息静态参考"）。
- **规模**：**1 个种子（seed=1）、1 条事件流、3 条臂**（`rolling_dynamic`、
  `mechanical_online_p38`、`full_information_static_reference`）；
  6 个触发批次，12 行逐次揭示记录，1 行配对结果。正文也写明"表中采用一次完整运行结果"。
- **单跑墙钟**：`metadata.json` 的 `wall_clock_seconds_per_decision = 64.5`。
  该目录没有 launcher.log，没有整跑总墙钟字段；按 6 个批次 × 3 臂粗估
  一次完整实验在十几分钟到半小时量级，**这是推算不是实测**。
- **⚠️ 必须报给用户的一条**：这个目录自己的 `decision.json` 写着
  `status = MAIN3B_FAILED`、`accepted = false`，
  失败原因含 `"termination was not normal"`、`"required audit did not pass"`、
  `"seed=1 arm=rolling_dynamic budget/call mismatch"`；
  `report.md` 首行是 `MAIN3B_FAILED`，并明确写着
  "这些小预算接线结果不支持算法性能、成本改善、排放改善或论文主张"、
  `run_class = main3b_small_wiring_trial`（接线小试）。
  **论文表 17 现在用的就是这一包被自己判为失败的接线小试的数字。**
  重跑与否之前，这件事本身要先有裁定。

---

## 5. 静态重跑清单汇总

产物：`solver/reports/rerun_split_20260908/joblist.txt`，**201 条**，
去重（同一目录被多个展品引用只跑一次）后按目录分布：

| 目录（均为原名 + `_split_20260908`） | 条数 |
|---|---:|
| `grid2x2_v3_20260906_split_20260908`（4 格 × 2 臂 × 10） | 80 |
| `carbon_price_sweep_v3_20260906_split_20260908`（22 档 × 3） | 66 |
| `charging_arrangements_20260906_split_20260908`（2 臂 × 10） | 20 |
| `ablation_v6_20260906_split_20260908/M-HGS`（× 10） | 10 |
| `policy_combos_20260907_split_20260908`（4 行 ＋ 2 新情形） | 25 |
| **合计** | **201** |

预计时长：串行约 15.1 小时；**并行 3 约 5.0 小时**
（各批自己的 launcher.log 中位加总；262 条历史样本的总中位是 4.32 分/跑，
最长实测 13.7 分，中位掩盖长尾，实际会更长）。
详细跑法、派生规则、53.03 元溢价的推导见
`solver/reports/rerun_split_20260908/README.md`。

---

## 6. 顺带发现（不影响本次重跑，但要登记）

**表 9（消融表）的回填是陈的**：`docs/paper_v2/generated_tables/table8_rows.tex` 现在的内容是
`M 2704.00 / MT 2518.13 / MTC 2504.97`（`ablation_v6_20260906` 新口径），
而 `paper_main.tex` 表 9 里写的还是
`M 2704.00 / MT 2657.41 / MTC 2605.70`（旧批）。
`ablation_v6_20260906/README.md` 写明重做原因是用户 09-06 改了"即充"定义
（首趟前补电由仿真日 00:00 起改为前一晚回场即充），
并写明正文第 3 点"时变碳充电安排使排放减少 4.29%"依赖旧定义的假象、须撤。
**这只是回填没做，不改变本次重跑什么**——派工指令的"消融 M 臂 10"
正好对上 v6 的结构（MT/MTC 是指向 grid2x2_v3 的符号链接，不用另跑）。
