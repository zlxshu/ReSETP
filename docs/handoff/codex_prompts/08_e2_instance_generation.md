# 提示词⑧ — E2 算法对比基准：69 算例生成（阶段①）

> 先完整读仓库根 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md`。本任务在 **M1 基准机、系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5**、分支 `codex/reporting-pipeline` 跑。本阶段**只生成算例、不碰任何算法代码、不跑对比**。

## 背景 / 目标
为 E2（算法对比 → T3/F2）建一套 **69 个跨规模算例的标准基准**，结构 = 3 类别 × 规模阶梯：
- **vanilla（原味，单车场）**：直接用 Goeke 原算例本体（`models/data_bundle/raw_instances/goeke_uk/` 里的 `E-UK{N}_{xx}.txt`，N∈{10,15,20,25,50,75,100,150,200}），保持其单车场结构。
- **multidepot（多车场）**：在同一批 Goeke 算例基础上加到 **2 个车场**。
- **threeshift（三班多车场）**：在 multidepot 基础上做三班合成，**仅 50c 及以上**（50/75/100/150/200）。
- **每个（规模×类别）格子取 3 个 donor 实例**（建议固定取每规模的 `_01/_02/_03`，可复现）。

计数：vanilla 9×3=27 + multidepot 9×3=27 + threeshift 5×3=15 = **69 个算例**。

> 口径说明（写进 manifest，不要在本阶段改求解器）：这 69 个算例最终都按 **ReSETP 口径**（UK 成本 + 两层碳）评测、**不挂任何外部 BKS**。Goeke 的美元 BKS 因参数体系不同不适用，本基准用 best-found 参照。

## Phase 0 — audit（先报告再动手）
1. 读 `models/data_bundle/raw_instances/goeke_uk/` 格式（`StringID/Type/x/y/demand/ReadyTime/DueDate/ServiceTime` + `m numVeh/numPetrolVeh/numElectroVeh` + `DistanceMatrix`），确认 9 个规模、每规模文件数。
2. 读生成管线接口：`models/src/setp_instance_lab/cli.py`（`generate` 子命令：`--base-id`/`--depots`/`--stations`/`--customers`/`--num-cv`/`--num-ev`/`--coord-mode`/`--data-root`…）、`catalog.py`（`migrate_goeke_instances`/`resolve_goeke_instance`/`donor_instance_paths`）、`io.py`（`write_scenario_bundle`）、`models/scripts/build_three_shift_instance.py` 与 `build_scale_three_shift_instances.py`（三班合成：每班独立生成→时间窗后移→第3班超时客户丢弃→设施共享；标签=合并后最终客户数）。
3. 弄清两件关键事实并写进 audit：① `--base-id` + `--empirical-exact-base` 且**不带** `--synthetic-only` 是否保留 Goeke 的坐标/需求/时间窗原值（vanilla 必须 1:1 用 Goeke 原件，不得重采样）；② 多车场是“在 Goeke 客户布局上新增第 2 个车场”，原车场 D0 保留。
4. 确认一个 bundle 需要哪些文件（instance.json / carbon_profile / manifest 等），对照现有 `generated_instances/E-UK100_01__u0_*` 的结构。
5. 输出 `models/data_bundle/generated_instances/e2_benchmark/audit.md`：管线能力、字段映射、三班"标签=最终客户数"的实测换算（每班≈target/2.27）、以及下面命名/参数表是否可行。若某规模三班合成无法对齐目标客户数，报实际值、勿事后删客户凑整。

## Phase 1 — 生成（命令式，逐类别）
所有产物落 `models/data_bundle/generated_instances/e2_benchmark/<category>/`，三类别子目录 `vanilla/`、`multidepot/`、`threeshift/`。**车队规模 `--num-cv/--num-ev` 与 Goeke 该规模一致或按客户数线性设定**（audit 里定一个规则并固定，例如沿用现有算例的 m^g=m^e 或 Goeke Table6 的 mIC/mE 量级），写进 manifest。
- **vanilla**：对每规模 N∈{10,15,20,25,50,75,100,150,200} 的 donor `_01/_02/_03`，用 `--base-id E-UK{N}_{xx} --depots 1 --empirical-exact-base` 且**不要加** `--synthetic-only`（保留 Goeke 原件，单车场）转成 bundle。命名 `e2-vanilla-{N}c-{xx}`。
- **multidepot**：同样 donor，`--depots 2`，命名 `e2-multidepot-{N}c-{xx}`。车场放置用生成器默认策略（`min_depot_distance` 等），audit 里报第 2 车场怎么定位。
- **threeshift**：N∈{50,75,100,150,200} 的 donor `_01/_02/_03`，用三班脚本在 multidepot（2 车场）基础上合成，目标最终客户数=N（每班基数由 `choose_child_counts` 反推），命名 `e2-threeshift-{N}c-{xx}`。

## Phase 2 — 校验 + 清单
- 对全部 69 个 bundle 跑**可行性自检**（复用 `candidates.make_shared_initial_solution` 能产出零违约暖启动 + `check_solution` 通过）。任何一个产不出零违约可行解 → 标 HALT 并报哪个、为什么，不硬过。
- 写 `models/data_bundle/generated_instances/e2_benchmark/e2_benchmark_manifest.json`：每算例 `{instance_id, category, n_customers_target, n_customers_actual, n_depots, n_stations, num_cv, num_ev, donor_goeke_id, bundle_dir, three_shift_per_shift_counts(若适用), feasible_warmstart_cost}`。
- 写 `e2_benchmark/README.md`：一句话说明这是 E2 的 69 算例基准、3 类别 × 9(或5) 规模 × 3、ReSETP 口径 best-found、不挂 BKS。

## 验收
- 69 个 bundle 全部生成、全部零违约可行（或诚实 HALT 列出哪个不行）；manifest + audit + README 齐全。
- vanilla 严格 1:1 来自 goeke_uk 原件（坐标/需求/时间窗未改）；multidepot=2 车场；threeshift=50c 起、标签=最终客户数。
- 每数字/产物绑 commit hash；分多次 commit；系统 Python 金标准环境。
- 诚实：哪个规模/类别没生成成功、为什么，如实写。

## 边界
- **只生成算例**：不碰 `cost.py`/`check.py`/`evaluation.py`/`winner_operators.py`/`metaheuristic_baselines.py`/任何搜索算法。
- 不动 `goeke_uk/` 原始 .txt（只读取/迁移，不修改）。
- 不在本阶段跑算法对比（那是阶段④⑤）。
- 系统 Python 金标准环境，别在 RL venv 跑。

## 交付
`e2_benchmark/{audit.md, README.md, e2_benchmark_manifest.json, vanilla/, multidepot/, threeshift/}` + 多次 commit（报告写 hash）。
