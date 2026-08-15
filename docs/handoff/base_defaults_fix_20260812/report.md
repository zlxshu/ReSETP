BASEFIX_DONE

# 2026-08-12 基础默认值修复报告

## 一、最终结论与授权时间线

`USER DECISION`：用户于 2026-08-12 明确授权：“当然修，以最新的我的亲自决定为准。”本任务只处理 H1（电车非能源里程成本）、H2（车型固定成本）和 H3（英国无场景默认值）。

`FACT`：三项最终均已完成：

- H1：基础 China81 电车档案由 **0.6700 元/km** 改为用户已定的 **0.9145 元/km**；原本已经在外层使用 0.9145 的私有重建与 V3 套件没有重复加电池折旧。
- H2：最终为 **燃油车 170 元/实体车·日、电动车 220 元/实体车·日**，数值从权威车型成本档案进入基础精确总账、利润账和两条 HGS 路线代理；旧外层 50 元只保留为审计分解，不再重复计费。
- H3：四个英国值保留在明确命名的 `UK_2025_PRICES` 中；无场景 `DEFAULT_PRICES` 不再返回可参与计算的英国数。数值转换或运算会失败，China81 组合边界还会拒绝错误城市柴油价、错误柴油标量和错误中国碳参数。

`CORRECTION`（H2 授权时间线）：第一次施工时查明，若不改受保护的 `solver/src/setp_solver/cost.py` 固定成本 statement，就不可能让任意混合解按 170/220 分型。因此当时依用户原红线停止 H2，没有越权。随后用户在同日 21:39 明确答复“……批准。修复。”，并另发窄授权：只允许修改 `cost.py` 的该固定成本 statement，`check.py` 与 `search/evaluation.py` 禁止修改。后续任务已按该新授权完成，详细证据见 `docs/handoff/cost_model_fix_20260812/report.md`（首行 `COSTFIX_DONE`）。所以本报告的最终状态不再是“H2 等待批准”。

`FACT`：没有运行正式实验，没有改算例几何或算法参数，没有静默覆盖、删除旧产物。后续 H2 授权同时要求修复利润／公平账的相关口径；那些续篇内容在 `COSTFIX_DONE` 报告中完整交付，本报告只汇总与 H2 基础默认值及其影响边界直接相关的部分。

## 二、三项修改明细

| 项目 | 文件与当前行号 | 旧值／旧行为 | 最终值／最终行为 | 用户决定或问题出处 |
|---|---|---|---|---|
| H1｜基础 EV 非能源里程成本 | `solver/src/setp_solver/china81.py:869-929`，值在 `:914` | 福田 ES1（77.28 kWh）为 `0.6700` 元/km | `0.9145` 元/km，并登记电池折旧组合来源 | `pending_decisions.md:147-159` 的 P43-H NOTE；59000÷241350≈0.244458 元/km，按用户已定四位值取 0.2445；用户确认两个有文献出处的参数合用 |
| H1｜私有外层防双算 | `solver/src/setp_solver/private_instance_rebuild_20260811.py:117-144,182-199,424-433` | 从基础 EV 值再 `+0.2445`；基础改成 0.9145 后若不改会得到错误的 1.1590 | 只从 `vehicle_costs.csv` 的基础 0.6700 与折旧 0.2445 推导并核对有效值 0.9145，再显式写入 | H1 同一用户决定；这是防止同一折旧重复入账的必要接线 |
| H1｜V3 套件 | `solver/scripts/build_china81_suite_rebuild_20260812.py:107,959-972` | 构造器已直接写 0.9145 | 保持直接写 0.9145；来源 ID 去重 | H1 同一用户决定 |
| H2｜车型固定成本档案 | `data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv:1-3`；`solver/src/setp_solver/instance_loader.py:47-65,265-274`；`solver/src/setp_solver/china81.py:869-929` | 只有共用价格标量 170，车型档案没有日固定成本 | CV 档案 170、EV 档案 220；无车型档案的历史／非 China81 实例仍回退原共用标量 | `pending_decisions.md:109-131,147-167` 的 P43-F F1、P43-H NOTE 与 P43-I（`:165` 要求 50 元 EV 溢价进入真正成本模型）；EV 溢价来源为陈婉茹等（2023）目标期刊先例 |
| H2｜基础精确总账 | `solver/src/setp_solver/cost.py:164-181`，获批改动在 `:170-181` | `(n_cv+n_ev)×vehicle_fixed_cost`，China81 两型均按 170 | `n_cv×170+n_ev×220`，且同一物理车多趟仍只计一次 | P43-I 与用户 21:39 后续窄授权；`COSTFIX_DONE` 第三节给出完整 diff |
| H2｜代理与旧外层 | `problem_hgs/kernel_proposals.py:821-839`；`duty_hgs/pyvrp_proposals.py:384-403`；`private_instance_rebuild_20260811.py:347-374`；`problem_hgs/evaluation.py:833-873` | 两条搜索代理仍按 170/170；完整评价后外层再加 `50×EV数` | 代理按档案取 170/220；外层不再加总，只保留并核对 `cost_fix_ev_premium` 审计字段 | H2 后续授权及单位审计第 5 条；避免基础下沉后双算 |
| H3｜无场景默认价格 | `solver/src/setp_solver/prices.py:95-113,140-173,212-221` | `DEFAULT_PRICES` 静默带入柴油 1.4331 £/L、碳价 0.05034 £/kg、低碳价 0.04184 £/kg、柴油 EF 2.57082 kgCO2e/L | 四字段改为必须显式定场景的哨兵；英国原值逐位保留在 `UK_2025_PRICES` | 中国化审计 A01：`china_localization_repo_audit_20260812.md:38,62-64`；用户要求不能简单换成中国数字，必须堵住静默误用 |
| H3｜China81 第二道防线 | `solver/src/setp_solver/china81.py:234-272,1144-1207` | bundle 构造不拒绝英国对象；下游漏传仍可能回到英国默认 | 强制城市柴油价表非空且一致、柴油标量等于城市均值，并锁定中国碳价 0.07502、低值 0.05632、柴油 EF 2.6419028944 | 审计 A01；上一轮 `param_fix_20260812/report.md` 的中国排放因子与参数权威 |
| H3｜合法英国用途 | `reporting/samples.py:13,127-142,418-443`；`search/formal_runner.py:26,202-213,798-807,928-930,967,1025-1037`；已确认的旧 E2/E3 英国入口 | 借用无场景默认对象 | 明确传 `UK_2025_PRICES`；四个英国数不变 | 用户允许历史英国复算，但要求不能成为中国路径的静默后备 |

## 三、受保护文件与 H2 的完整授权改动

### 3.1 为什么第一次必须停止

`FACT`：旧 `PriceParameters` 只有一个 `vehicle_fixed_cost` 标量。旧精确评价器虽然先分别数出 `n_veh_cv`、`n_veh_ev`，但随后将二者相加再乘同一标量。全 CV 解要求标量为 170、全 EV 解要求标量为 220，一个标量不可能正确覆盖任意混合解。只在档案／加载器增加 170/220 不会被旧评价器读取；把 50 元摊进公里费会改变模型含义，逐入口手工补差则会继续留下漏网。因此第一次施工按红线停止是正确的。

### 3.2 后续窄授权的完整 `cost.py` diff

```diff
@@ -167,7 +167,18 @@ def evaluate(
-    cost_fix = (n_veh_cv + n_veh_ev) * _price(prices, "vehicle_fixed_cost")
+    cost_fix = (
+        n_veh_cv
+        * instance.vehicle_fixed_cost_per_day(
+            "cv",
+            fallback=_price(prices, "vehicle_fixed_cost"),
+        )
+        + n_veh_ev
+        * instance.vehicle_fixed_cost_per_day(
+            "ev",
+            fallback=_price(prices, "vehicle_fixed_cost"),
+        )
+    )
```

`FACT`：从任务开始快照到最终文件，`cost.py` 只有上述一个 hunk；`check.py` 与 `search/evaluation.py` 逐字节不变。独立终审已复核该 diff、权威档案接线、数值重放和作废目录清单，未发现需返工问题。

## 四、行为保持不变的路径及证据

### 4.1 H1：原本已经显式使用 0.9145 的路径

| 路径 | 修复前 | 修复后 | 不变证据 |
|---|---:|---:|---|
| 私有重建 loader 的 EV 每公里成本 | `0.67+0.2445=0.9145000000000001`，IEEE-754 为 `0x1.d4395810624dep-1` | 仍从合同同两列推导，得到同一位串 | 逐位一致；基础档案不再参与这次加法，因此不会变为 1.1590 |
| `china81_suite_v3` 及 depot-pair、PRD-fix、metro 派生包 | 构造器直接赋 0.9145 | 仍直接赋 0.9145 | 构造器 6 项测试通过；套件登记 `formal_search_evaluations=0`，无正式搜索结果因 H1 作废 |
| 已保存私有混合解的 H1 账单 | 已按 0.9145 评价 | 同一固定解仍按 0.9145 | `solver/reports/combat_prescreen_speedup_20260812/equivalence_before_3cycles/best_solution.json` 的保存里程账可由 `127.2514589063×0.78+968.38736988123×0.9145` 复得 |

`BOUNDARY`：上述结论只说明 H1 下沉没有再次改变同一固定解的里程账。H2 后来揭示旧搜索代理仍按 EV 170 看候选，所以这些旧搜索包的“当前模型搜索证据”身份仍失效，不能由 H1 账单不变推出整组实验仍有效。

### 4.2 H2：纯 CV 与原外层已补差的同一固定解

零搜索动态重放使用同一当前 Instance、价格、碳档案和同一保存 `prepared_solution`，分别加载任务开始快照和最终评价器：

| 固定解 | 物理车 | 旧基础总成本 | 旧外层补差后 | 新基础总成本 | 结果 |
|---|---:|---:|---:|---:|---|
| `combat_v2.../closure_type_exchange_final/best_solution.json` | 8 CV / 0 EV | 3315.241658757535 | 3315.241658757535 | 3315.241658757535 | `float.hex()` 均为 `0x1.9e67bbab258cfp+11`，逐位不变 |
| `combat_v2.../combat_v2_5cycles_final/best_solution.json` | 3 CV / 5 EV | 2647.9202579809003 | 2897.9202579809003（外层 +250） | 2897.9202579809003（基础分型计费） | 同一固定解顶层总价保持，`cost_fix_ev_premium=250` 只作审计，不再二次相加 |

`BOUNDARY`：混合解顶层账单保持不等于旧搜索结果可保留。旧代理在生成／排序候选时看到的是 170/170；现在是 170/220，搜索轨迹、算子统计和 incumbent 身份均可能变化。

### 4.3 H3：已经显式定场景的中国与英国路径

显式 China81 四字段的浮点位串修复前后相同：

```text
diesel_price       0x1.dc28f5c28f5c3p+2
carbon_price       0x1.33482be8bc16ap-4
carbon_price_low   0x1.cd5f99c38b04bp-5
diesel_ef          0x1.5229dfc153ef5p+1
```

具名英国对象也与旧英国默认逐位相同：

```text
diesel_price       0x1.6edfa43fe5c92p+0   (=1.4331)
carbon_price       0x1.9c62a1b5c7cd9p-5   (=0.05034)
carbon_price_low   0x1.56c0d6f544bb2p-5   (=0.04184)
diesel_ef          0x1.4910a137f38c5p+1   (=2.57082)
```

`FACT`：典型 China81 精确评分、Problem-HGS、Duty-HGS 均显式传 `bundle.prices`，H3 对这些路径只增加拒绝错误上下文的断言，不改变数值。合法英国样表 `solver/reports/reporting_samples/tables/t2_parameters.csv` 没有覆盖，SHA-256 仍为 `07bb84e94ea6b655deaa172e6d657c3758352bfdceda0031e6e301c3e7227eda`；具名英国对象的四个数字未变，既有英国结果不因 H3 作废。

## 五、行为发生改变的路径、保存结果与作废边界

### 5.1 H1：基础 China81 从 0.67 改为 0.9145

基础 `load_china81_bundle()` 后直接使用车型档案的路径现在按 0.9145 评价。活动代表包括：

- `solver/src/setp_solver/china81_completion.py` 的 `exact_china81_score()`；
- `solver/scripts/run_mixed_fleet_experiment.py`；
- `solver/scripts/run_duty_hgs_private_technical.py`；
- `solver/scripts/run_problem_hgs_private_technical.py` 的通用 China81 分支；
- 历史 E3、E4、E5、E6、XA、XA2、XB、XC 与 E2 v7 中直接加载基础 China81 的入口；完整家族见 `china_localization_repo_audit_20260812.md:143-170`。

对任一固定解，H1 增量为：

```text
0.2445 × EV 行驶里程(km)
```

零搜索单 EV 路线的最小载荷为：`vehicle_id=EV_BASE_PROBE`、`vehicle_type=ev`、`home_depot_id=D_shenzhen`、节点序列 `D_shenzhen-C001-D_shenzhen`，充电动作与跨场动作均为空。其解 SHA-256 前后均为 `6c6c5d959ff860b852177e2b3d438c896790f3f08fef33f9b090c0acdd913dcb`，距离 55.672432598059 km。该哈希的规范是：对 `dataclasses.asdict(solution)` 执行 `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`，再对 UTF-8 字节取 SHA-256；因此哈希只覆盖同一固定解结构，不混入成本值：

| 阶段 | `cost_km` | `cost_fix` | `total_cost` |
|---|---:|---:|---:|
| H1/H2 前基础值 | 37.30052984069953 | 170 | 207.30052984069954 |
| 只应用 H1 | 50.91243961092495 | 170 | 220.91243961092493 |
| H1＋获批 H2 最终值 | 50.91243961092495 | 220 | 270.91243961092493 |

H1 增加 13.611909770225417 元；`0.2445×55.672432598059=13.611909770225424`，在 `1e-12` 内一致。H2 再增加恰好 50 元。

历史直接物证：

`baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-01-V2-LOCATIONS/solutions/seed1_cost_only.json`

- 文件 SHA-256：`059725ba60ef2e042e78793392efbc65d60affe784eb57d32a1b8c13e0d1609d`；保存语义 solution SHA 为 `81b11d7b68fc33c8f0f64cca95dde1994828e0717ba89cb56eb0ffec242373af`。
- CV 363.764248476792 km、EV 230.70500083653 km、6 CV/3 EV；旧 `cost_km=438.3084643723729` 与 0.78/0.67 旧公式逐位吻合。
- 同一固定解的 H1 新 `cost_km=494.71583707690445`，增加 56.407372704531554；H2 固定费由 1530 增至 1680，再增加 150；合计增加 **206.40737270453155 元**。

该保存结果及其旧搜索比较属于旧参数时代，因为旧值参与过候选排序，不能只给最终解补账。

### 5.2 H2：原 170/170 的基础和搜索代理改为 170/220

`FACT`：对没有旧外层补差的任一固定解，H2 精确增量为 `50×n_veh_ev`；对搜索路径，车型与路线候选排序也会改变。当前受影响路径包括通用 `cost.evaluate()`／`exact_china81_score()`、Problem-HGS 与 Duty-HGS 路线代理、利润／公平消费者以及所有允许 EV 且在旧代理下搜索的运行入口。

保存产物边界由独立选择器逐目录核对，完整清单在 `COSTFIX_DONE` 第七节：

- **56 个 V3 运行目录**：旧搜索代理按 170/170；其 incumbent 身份、轨迹、算子统计、聚合 `decision/report` 不能再作为当前 220 口径的搜索证据。其中同一固定解的顶层账单原已由外层补 50，不需要再加一次。
- 上述 56 个目录中，**15 个最终解含 EV**：旧 depot profit／participation margin 数值直接作废；这些包均 `fairness_enabled=false`，不存在保存的正式公平判定翻转。
- **27 个旧含 EV、无 V3 外层补费且无 margin 的目录**：旧搜索身份失效；其中 16 个保存成本分解，`cost_fix/total_cost` 本身按 `50×n_ev` 增加，另外 11 个只保存路线／充电动作，重算该固定解时同样应增加 50 或 100 元。逐目录清单见 `COSTFIX_DONE` 第 7.4 节。
- **149 个 V2 含 EV margin 目录**：保存 `cost_fix/total_cost` 先按 `50×n_ev` 增加；旧 EV 固定成本也没有进入利润账，相关 depot profit、Pi0、margin、fairness 及旧搜索身份作废或继续保持此前已作废状态。其中成渝 44＋京津冀 53＝97 个目录还受路线城市柴油价对齐影响。
- 因此，没有 V3 外层补费、且已经保存含 EV 固定解的目录合计 **176 个（27＋149）**；这与 56 个 V3 目录是不同集合。
- `mechanism_validation_v3_20260811` 的预检、全因子、扩种子表及由其生成的汇总同样是旧代理时代搜索证据。

`FACT`：当前可直接入文的正式结果仍为 0 组，因此没有损失一组已批准入文数字；失效的是技术包、历史 formal 包和候选证据。客户／设施身份、坐标、路网矩阵与哈希、需求、时间窗、纯几何距离不因 H1/H2 自动作废。

### 5.3 H3：漏传场景不再静默得到英国数

`CORRECTION`：属性访问本身返回的是哨兵对象，不是“访问属性立刻报错”。`float(DEFAULT_PRICES.diesel_price)` 等数值转换会给出带字段名的 `ValueError`；直接乘加等运算会失败而不会产出英国数字。这满足 fail-closed，但报告不把两种异常形式混写。

行为改变的主要分组如下；这些路径只有在省略 `prices` 且实际进入四个敏感字段时才失败。当前 `solver/src/setp_solver` 中仍引用 `DEFAULT_PRICES` 的完整静态文件清单可由 `rg -l '\bDEFAULT_PRICES\b' solver/src/setp_solver --glob '*.py' | sort` 复核（当前 35 个文件）：

1. 核心默认 API：`cost.py`、`check.py`、`profit.py`、`charge_timing.py`；`search/evaluation.py`、`charging.py`、`construction.py`、`fleet.py`、`order_decoder.py`、`multitrip_schedule.py`、`dynamic.py`、`dynamic_multitrip_schedule.py`、`fairness.py`、`execution_accounting.py`、`certificate_execution.py`、`candidates.py`、`e5_ablation.py`、`e5_probe.py`、`e2_alns_throughput.py`、`metaheuristic_baselines.py`、`metaheuristic_baseline_runner.py`，以及 `algorithms/resetp_alns` 的 kernel/support 层。
2. 可执行诊断／恢复入口：`search/root_cause.py`、`alns_crush.py`、`alns_crush_v2.py`、`alns_crush_v3.py`、`alns_scale_crush.py`、`winner_restoration.py`、`winner_nondeterminism.py`，以及 `solver/rl/dr_alns_ppo/worker.py`。未显式定场景的当前重跑会停止，而不再偷偷按英国数继续。
3. 历史脚本：`baselines/e1_model/m1_e1_model_structure_runner.py`，以及仍直接消费／`replace(DEFAULT_PRICES, ...)` 的 `algorithm_prototypes`、`e2_alns`、`e3_ablation`、E7 trigger policy 和 contract-audit 家族。它们多为旧英国或合成场景；重跑前必须明确选择具名英国对象或具体场景，不能由代理猜身份。

已确认的合法英国路径已经显式化，包括 `reporting/samples.py`、`search/formal_runner.py`、E2 scan/SA/throughput、E3 v3、EV-heavy 两个历史入口以及 metaheuristic 历史 CLI。它们的英国数值逐位不变；通用 API 的默认仍是哨兵。

真实中国漏参反例见 `baselines/china_e3_e7/e7_dynamic_v2_20260731/report.md:17-27`：两次重排调用漏传 prices 后退回英国默认并触发契约冲突。该包在搜索前停止，评价次数 0，没有科学结果需要作废；v3 已显式传 China81 prices。

`BOUNDARY`：H3 改变了上述旧脚本的当前可复跑行为，但不等于它们已经保存的英国数值自动作废。现有英国四值未变。除 E7 v2 的零评价失败包外，本轮没有获得“某个已保存中国科学结果确实由这四个英国默认数生成”的直接证据；未知旧入口继续按中国化审计台账处理，不以 JSON 没出现四个字段作为充分无污染证明。

## 六、验证结果

`FACT`：下列均为真实测试记录，各组有文件重叠，不能把 passed 数机械相加：

1. 成本、利润、通用搜索、充电与多趟调度核心组：`90 passed in 139.19s`。
2. China81、无场景默认、显式英国、私有防双算和旧 formal runner 定向组：`57 passed in 112.76s`。
3. `china81_suite_v3` 构造器：`6 passed in 0.84s`。
4. 旧 UK 夹具与高层 prices 贯穿回归：`167 passed in 11.95s`。
5. 与 cp313 扩展匹配的 Python 3.13 Problem-HGS 组：`28 passed, 1 skipped in 18.67s`。
6. E2 scan／SA／throughput 显式英国贯穿：`26 passed in 4.39s`。
7. 英国报告样表：`15 passed in 4.42s`。
8. H2 续篇最终不重复计数相关测试：`84 passed`；其中 71 项成本／利润／代理回归、3 项 formal 定向、4 项 Python 3.13 私有适配器、6 项中国价格门。独立终审核对了日志与新增漂移敏感断言。

新增回归会在以下漂移发生时失败：基础 EV 不再是 0.9145；权威 CSV 不再是 CV170/EV220/溢价50；精确总账不再按车型计且每实体车只计一次；私有／Problem-HGS 再次双算 50；无场景四字段重新可用；China81 接受英国对象或错误柴油标量；搜索代理与完整总账分型不一致。

`FACT`：本轮实际运行的测试集合中，由 H3 哨兵暴露的旧英国漏接线失败均已处理；没有用 monkeypatch 隐藏生产接线。两条原来断言“隐式默认等于显式默认”的旧测试，已按新合同改成“显式英国对象可重复”，不是宣称所有旧断言逐字不变。

如实保留的非 H1/H2/H3 失败：一组广泛历史搜索回归为 `84 passed, 3 failed, 1 skipped`。三个失败均不再命中 H3 哨兵，且英国四值前后逐位相同，本任务没有改算法或断言迎合结果：

```text
solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables
solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts
solver/tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps
```

前两项实际遇到旧车队数超限；第三项候选成本 4954.208671718898 高于初始解 4923.557583344485。另有 1 项按原测试条件跳过。没有为求全绿而改值。

本任务没有启动正式搜索／正式实验，因此不产生新的实验四件套。

## 七、受保护文件 SHA-256

| 文件 | 本任务最初基线 | 最终现场 | 结论 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | `ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | 第一次因红线未改；后续获用户窄授权后只改第三节所示固定成本 hunk |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | 前后 SHA 相同，逐字节不变 |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | 前后 SHA 相同，逐字节不变 |

## 八、修改文件与交接边界

H1/H3 的主要生产改动：

- `solver/src/setp_solver/china81.py`、`prices.py`、`private_instance_rebuild_20260811.py`、`build_china81_suite_rebuild_20260812.py`；
- `reporting/samples.py`、`search/formal_runner.py`、`search/e5_probe.py`、`search/candidates.py`、`search/metaheuristic_baselines.py`、`search/metaheuristic_baseline_runner.py`；
- `algorithms/resetp_alns/kernel/alns_core.py`、`kernel/winner.py`；
- `search/e2_alns_scan_bridge.py`、`e2_alns_sa_acceptance.py`、`e2_alns_throughput.py`；
- `baselines/e3_ablation/e3_v3_runner.py`、`baselines/e2_alns/ev_heavy_findability_gate.py`、`ev_heavy_regime_decision_probe.py`。

H2 后续授权的主要生产改动：`instance_loader.py`、`china81.py`、获批的 `cost.py` statement、`profit.py`、私有／Problem-HGS 完整评价包装器、Problem-HGS／Duty-HGS 两条代理，以及派生套件来源路径接线。完整清单、利润／公平对照和逐目录作废表只保留在 `COSTFIX_DONE` 报告，避免本报告再复制 200 余行目录而漂移。

测试文件只新增业务断言，或把原来依赖隐式英国默认的历史英国／合成夹具改为显式 `UK_2025_PRICES`／显式场景；没有修改搜索预算、算法参数、正式阈值或算例几何。

`FACT`：旧产物均原地保留为历史审计材料，未覆盖。`CURRENT_PROJECT_CONTEXT.md`、`HANDOFF.md` 和 `docs/handoff/memory/MEMORY.md` 已登记 H1/H3 初次停止与 H2 后续授权完成的时间线；`pending_decisions.md` 不由本报告改写，因为本任务没有新增参数决定。
