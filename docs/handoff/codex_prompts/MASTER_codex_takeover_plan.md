# MASTER — Codex 接管总规划（Claude credits 将尽，转 Codex 思考+执行）

> 这是 Claude(M1)交给 Codex 的总纲。**Claude 之后基本不在场,Codex 既思考也执行。** 本文件 = 剩余全部规划(总体+局部) + 预备方案 + 行为铁律。每段对话先读 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`，再按其中清单读 `HANDOFF.md` + `docs/handoff/project_prd_execution_map_v2_20260702.md` + `docs/handoff/project_planning_map_20260701.md` + 本文件 + `docs/handoff/memory/MEMORY.md` + 相关 memory 节点，再动手。

## 0. 给 Codex 的行为铁律(每段对话自我约束,务必照做)
- **先读后做**:每轮先读 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md` 并执行其强制读取清单；读完前不得改代码、跑实验、下结论。Fable5/Claude 的合理规划可继承，但最终事实以 `HANDOFF.md` 和原始 CSV/JSON/checkpoint 为准。
- **诚实(最高优先)**:跑不出/没收敛/没赢就诚实 HALT 并如实写,**绝不注水、不混旧数据、不拿弱版/没跑满的结果充数、不把推断冒充实证**。哪个档输、和谁打平,照实报。
- **克制**:不自创算法、不无限加料硬刚;碰卡点先翻 Zotero 文献 + 上网找现成解,别重复造轮子;每个改动绑证据 + commit hash;拿不准停下报告,别擅自扩大范围。
- **边界(硬)**:禁改 `cost.py`/`check.py`/`evaluation.py` 语义(唯一真值源);系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5 + `PYTHONHASHSEED=0`;改核心代码立即 commit、数字绑 hash;分支 `codex/reporting-pipeline`。
- 与 user 平实中文;给出判断要带证据,不空谈。

## 1. 现状快照(2026-06-26,09s 后)
- **当前主线已由用户拍板回正到 Goeke 物理参数 + 实体车辆多趟语义**。09k-09q 的 280kWh、电池梯度和运营约束摸排全部保留为历史诊断链,但暂不再作为当前执行入口。当前默认参数为 `Q_capacity=3650kg`、`B_battery_kwh=80kWh`、`v_speed_ms=25.0`、`carbon_price=0.05034`;TeX 参数表和 `prices.py` 注释已同步保留 1600kg/280kWh 的历史痕迹。
- **09s 修正的核心不是新增论文模型,而是修代码翻译错误**:论文里的 `m^g/m^e` 是实体车辆硬上限,不是 route 数硬上限。一台实体车允许一天/一个阶段跑多趟;代码现在用 `CV1#T1`、`CV1#T2` 这类 trip id 保持 route/charging action 唯一,同时按 `CV1` 这个 physical vehicle prefix 计入车辆数上限。固定费暂不改,仍按每趟/每次派遣口径;若未来要改为每实体车固定费,必须另起成本语义审计。
- **09s gate 结果**:`baselines/e2_alns/goeke80_multitrip_rescue_gate.py` Phase1 让 69/69 个 E2 实例 warm start 在硬实体车上限下零违约通过;Phase2 代表集 seed1 小预算 smoke 34/34 行 OK, paired result 为 ALNS wins 2 / LNS wins 0 / ties 15。大白话:语义卡点已经清掉,可以继续救算法对比;但这不是正式胜利证据,因为多数 pair 在 `eval_budget=300` 下只是同成本持平。
- **09t 高预算预演结果**:`baselines/e2_alns/goeke80_multitrip_t3_preflight.py` 已跑。Phase0/smoke OK；Stage A 全 `-01` 梯度 × seeds1-3 × ALNS/LNS 跑满 138/138,0 采集失败,paired counts = ALNS 7 / LNS 2 / ties 60,说明 LNS 没在低预算全梯度上系统性压制 ALNS。但 Stage A 的 75-200 winner mean EV route share 仅约 0.057,所以 Goeke80 下混合故事偏弱。Stage B 尝试完整 69 实例 × seeds1-3 × 2 算法、`eval_budget=16000`,最终在 `e2-vanilla-150c-01` 的 LNS seed1/2 于 900s 上限内只跑到约 11.2k/16k eval,按规则 `HALT_COLLECTION_COST`（130/414 rows）。这不是算法输赢结论,而是“当前 Stage B 采集设定太贵/不闭合”。正式 T3 仍不能启动。

### 历史诊断链(保留供理解,当前不作为入口)
- **09h/09i 的 280kWh 结论已被 09k 细化,不能再简单写成"根因已解决→直接重跑正式 E2"**。09h 证明了 280kWh 能让 mixed/EV 击败 all-CV fixed reference,但 280kWh fleet-composition gate 随后证明它把主问题推到另一端:代表集 winner 以 EV-heavy/all-EV 为主,不是稳定真混合。因此 **E2/T3 与 E1-E7 全量重跑继续暂停**。
- **09k evidence-bound battery spectrum gate 已跑满**:`baselines/e2_alns/battery_spectrum_transition.py` 用文献/车型明确 kWh 值构建谱系,不使用拍脑袋等距网格;冻结 `prices.py`/`cost.py`/`check.py`/`evaluation.py` 和算法语义,只做内存电池 override。screen 跑 21 个证据值;full gate 选 6 个锚点 `80/100/113/141/210/280kWh`,代表集 17 实例 × seeds1-3 × 3 variants 全跑满,918/918 rows,0 timeout/error。
- **09k 关键事实**:严格 balanced 只出现在旧文献锚 `80kWh`（mean EV share 0.408, 32/51 balanced winners）；当前车型证据没有稳健 balanced 候选。`100kWh` 是边界点（mean EV share 0.681）但 winner 多数已 EV-heavy（30/51）；`113/141/210/280kWh` 全部 EV-dominant（mean EV share 0.780/0.877/0.898/0.898）。报告 verdict=`BALANCED_EVIDENCE_BAND_FOUND`,但解释必须读全:这个 balanced 是旧文献锚,不是现代中型车主场景通行证。
- **当时默认代码曾被提升到 280kWh(09i/09j commit `8500fd9c`)**,但后续 gate 证明它应视为 **modern-battery/EV-dominant scenario candidate**,不能直接作为"混合车队主场景"进入正式表图。09s 之后当前默认已回到 Goeke `80kWh` baseline;这只是参数对齐与算法救援基线,不是现代物流主张。
- **09l 来源约束实践混合带 gate 已跑满 Stage A,电池单参数路线暂时关门**:`baselines/e2_alns/source_bound_mixed_band_gate.py` 对 19 个真实来源候选(60-291kWh,不含 80 主候选)跑全梯度 `-01` 实例 × seed1 × 3 variants,`1311/1311` rows 跑满、0 timeout/error。结论 `BATTERY_ONLY_INSUFFICIENT`(screen-gated,不是 Stage C confirmation):没有任何非 80kWh 来源候选 pass/near-pass。低端 81/82.6/89kWh 全局均值看似混合但跨规模失败;100kWh 只有 11/23 实例过带并已开始 EV-heavy;113kWh 起多数规模 EV-heavy/all-EV。Stage B/C 因无幸存候选不触发。
- **09m 首轮只读结构审计已完成**:`baselines/e2_alns/structural_mixed_band_investigation.py` 审计 69/69 实例结构并把 09l Stage A 限定到 75-200 拼接分析。结论:75-200 不是单一电池问题;地理包络相近,大规模客户密度更高且最近公共站距离下降,反而可能让 EV 更容易。最重要新线索是 fleet count:当前 `infer_fleet_limits()` 是 unbounded fleet,`check.py` 明确 fleet count 不再硬约束,而 metadata 仍有 `num_cv/num_ev`;EV-heavy 解常用几十条 EV route。下一步 09m 正式诊断优先查 EV 数量/资本约束,再查充电容量/站点可用性/长路线 eligibility。
- **09n 车辆数量上限诊断已跑到 Stage A 并 HALT**:`baselines/e2_alns/fleet_cap_operational_gate.py` 证实 unbounded fleet 线索真实:现有 winners 确实常超过 metadata 车辆数,280kWh 下 EV routes 可到约 70,而 Goeke/ReSETP metadata 在 75/100/150/200c 只有约 5/6-7/9-10/12-14 台 EV。但用 `SearchPolicy(max_ev/max_cv)` 诊断壳直接套原始车数并没有给出可正式化方案:`goeke_total_cap` 与 `depot_scaled_cap` 主要 `INIT_INFEASIBLE`,`goeke_ev_cap_only` 虽压住 EV-dominant,但均值落在下界外(route/customer/demand/distance 约 0.193/0.189/0.191/0.190)且有 fake-balance,加上 7 个 timeout/error,结论 `HALT_COLLECTION_COST`,Stage B/C 不触发。
- **09o 充电基础设施小试探已完成,仍 HALT 但给出下一优先级**:`baselines/e2_alns/charging_infrastructure_operational_pilot.py` 只测 280kWh/200c 小样本,冻结所有 solver 语义。结果 6 raw rows 中 3 个 `free_mixed` OK、3 个 `ev_shell` timeout,所以 verdict=`HALT_COLLECTION_COST`,不能写成因果证明。可用线索是 3 个 OK 行完全同向:EV share 0.627/0.681/0.840,充电能量 100% 来自车场,公共充电路线数 0,单车场峰值并发 24/15/62;而生成实例车场容量是 `customer_count_route_upper_bound`(200c vanilla/multidepot 200 个桩,threeshift 节点 91 个),公共站通常 1 个桩。下一步优先查 **车场充电桩容量/充电资本预算** 的真实来源与正式 gate;公共快充稀缺在这批 OK 行里不是主要支撑机制。下一步提示词为 `docs/handoff/codex_prompts/09p_depot_charger_capacity_evidence_gate.md`。
- **09q 综合摸排 runner 已建立,但正式全矩阵未跑满**:`baselines/e2_alns/source_bound_operational_mix_map.py` 把 09l 真实电池梯度、09n 车辆/资本约束线索、09o 场站充电线索放进同一张诊断矩阵。user 已纠偏:不能只测 280,也不能只看 75-200;实例范围已扩大为 E2 可用 `10-200` 全规模梯度,共 69 稳定性实例。当前只完成 Phase0 和 smoke(12 rows, verdict=`SMOKE_ONLY`),证明 runner/override/resume 链路可用;完整 Stage A 默认任务量 `19 batteries × 7 constraints × 23 -01 instances × 3 variants = 9177` 子任务,必须按可恢复队列另行长跑,不能把 smoke 写成科学结论。正式入口为 `docs/handoff/codex_prompts/09q_source_bound_operational_mix_map.md`；09p 车场容量只作为其中一个子线索,不再单独替代综合摸排。
- **诊断来龙去脉(供理解,别重做)**:E2 算法对比上 LNS 基线(=高娇娇2024 GLNS,扫描+LNS+SA、无 EV/碳机器的通用纯路由器)曾赢我们的 ALNS。80kWh 端 EV 续航不足,280kWh 端 EV 太强。真正的论文主线要在 **证据约束参数** 与 **现实运营约束** 之间选择,不能为了凑混合硬调电池。

## 2. 当前用户纠偏后的判据
不要把 09s smoke 写成正式算法结论。当前可以从“能不能跑”进入“更高预算、多 seed 预演能不能救回算法对比”,但仍不能跳过 gate 直接进入正式 E2/T3。

- **80kWh 当前是 Goeke 对齐基线,不是现代物流主张**。它可以用于测试“参数对齐 + 实体车辆多趟语义”能否救回算法对比;不要再把它包装成现代中型车主场景。280kWh 也只保留为现代电池诊断场景,不再作为当前默认。
- **电池值必须来自真实来源**:2020 年后文献、Zotero PDF、或真实车型/官方资料明确给出的 kWh。不得用等距网格、插值、或为了凑混合自造 90/95/105 这类值。没有来源就不能解释,后期论文也站不住。
- **未来若拍板任何新默认电池容量,必须同步三处事实源**:不能只改 `prices.py`。必须同时更新 `docs/paper_submission_final/paper_main.tex` 的参数表/参数说明、补齐或更新 bibliography 中的新来源引用、并在 `solver/src/setp_solver/prices.py` 注释中写清"旧参数值+旧来源"与"新参数值+新来源+诊断证据"。旧 Goeke/Davis-Figliozzi 80kWh 与当前 280kWh 证据链都要保留痕迹,不能被静默覆盖。
- **比例标准改成实践混合带**:不要求 1:1,允许研究趋势偏 EV,但 winner 的 EV/CV 实际占比至少应落在 20%-80% 区间内。主指标先用 `EV route share`；报告还应尽量补 `served customers / distance / demand` share,避免路线数假平衡。
- **不能只看全局均值或单个算例**:必须按 family × size 梯度逐项报告,并包含稳定性校验算例。一个电池值只有在所有梯度规模、稳定性实例、seeds 下多数 winner 都维持 20%-80% 实践混合,才算故事立住。
- **下一步优先级**:先处理 09t 的采集策略决策,不要直接正式 T3。可选方向包括:把预演改成 wall-clock 公平而非固定 16000 eval,或降低 Stage B eval budget 到 LNS 能在 900s 内闭合的水平,或优化/替换 LNS 收集路径后再重跑 Stage B。若只看现有证据,Goeke80 + 多趟实体车语义下 ALNS 有竞争力迹象,但 EV 使用偏低,更像 Goeke baseline/算法可行性测试,不能包装成稳定现代混合车队主故事。

## 3. 剩余总路线图(拍板后再执行)
1. **8 基线做到文献最优 + 收敛(已写 `10_e2_baselines_literature_best.md`)**:GA/PSO/VNS/ACO/GA-VNS/LNS/GWO/IWD 按源论文重做、文献标准参数、"真在搜索"硬门禁(std>0 + 改善暖启动 + 收敛曲线明显收敛)。`baseline-algorithm-catalog.md` 有设计转录。
2. **E2 算法对比正式跑出 T3/F2**:只有在第2节主叙事确定并通过相应 gate 后才跑。不要在 280kWh EV-dominant 状态下写"混合最优"故事。
3. **E1-E7 全量重跑 = 新正式数字**:参数/约束主场景确定后再重跑。旧 9da7f8b、旧 80kWh 和 280kWh 暂态结果均不得直接灌正式表图。
4. **图表顶刊级填数画图(已规划 `docs/handoff/memory/figure-redesign-task.md`)**:壳已锁,用新数字填→画→user 审→进正式。F4 修渲染、F6 补 θ 网格。
5. **动态需求整合(`docs/handoff/memory/dynamic-demand-integration.md`)**:E7/T9 必须证明 车场协同/收益公平/时变碳 真参与动态路径决策(动态×协同、动态×公平、动态×碳 三交互证据),否则=堆砌。先查 `run_rolling_reoptimization` 每阶段是否解完整目标。**2026-07-01 明确规划门槛:** 后续 T9 不能只报告动态成本、累计碳、冻结路线和可行性;必须新增或产出三类交互指标:①动态新增/变更需求被跨车场或共享车辆池吸收的比例/案例;②逐阶段车场收益与公平比/公平约束状态,若 `min_fairness_ratio=off` 则明示未完成;③动态重规划对 EV/CV 分工、充电动作、充电时段平均碳强度或新增碳排的影响。若三项无法成立,动态需求只能写作滚动接口与状态继承可行性,不得写成四要素耦合贡献。
6. **§3 算法章 + §4.4 算法对比重写**(user 手工定稿文字;Codex 备好 T3/收敛/gap 素材)。
7. **(可选,不阻塞)DR-ALNS**:x86 lane 的锦上添花/future work,训出来再补 T3 的 DR 列;**未训练前不进算法主线、不用于救场**。

## 4. 各步预备方案(contingencies,诚实优先)
- **09s 后续若仍失败**:不要立刻回到 280kWh 或无来源调参。先分清失败类型:若全 CV 退化,说明 Goeke80 仍是旧电池故事问题;若 mixed 存在但 ALNS 不赢,是算法可靠性/方差问题;若 LNS/GLNS 仍强,应诚实定位而不是注水。
- **运营约束退路**:先做证据矩阵和最小语义设计,不要一上来改 `cost.py/check.py/evaluation.py`;任何新增约束必须有现实解释、可关开关、旧语义可复现。09o 后优先级调整为:车场充电桩容量/充电资本预算第一,公共桩稀缺/可用性第二,EV 资本预算和跨城长路线 EV eligibility 作为组合退路；车辆数上限仍是线索,但不能直接使用 Goeke metadata cap,除非先正式建模车辆复用/车次数学语义并有文献/场景支持。
- **参数正式化退路**:无论最后是电池容量、运营约束还是场景分叉,只要进入默认参数/论文主场景,就必须同步代码默认值、代码注释来源、TeX 参数表、TeX 表下注释、bibliography、HANDOFF,并显式说明旧参数为什么保留为历史/文献锚而不是当前主场景。
- **第3步(E2)若强化 ALNS 仍输 LNS**(在已拍板并通过 gate 的主参数/约束场景下):先查是不是又回到"算法方差/可靠性"问题(09c/09d 的残留);文献找现成稳定化(SA 降温重调/多起点);**仍不过则诚实定位"ALNS 与 LNS 同档第一梯队、差异化靠碳感知机制+DR",不硬刚不注水**(符合既定 bar:对手更强+贴近最优+创新清晰,非碾弱对手)。绝不退回旧数据凑赢。
- **E1-E7 重跑算力**:各 10seed×16000eval=天级以内,resumable;200c 单期慢→硬超时返回 incumbent(09d 已修)。
- **图表数字**:必须来自最终拍板主场景重跑后的 CSV,旧数字一律不灌。
- **跨机**:x86 dr-x86 分支的 DR 小产出经 GitHub/U盘合并;HANDOFF 冲突 x86 标 `[x86/DR]`、M1 标 `[M1]` 两边保留。

## 5. 索引(已有资产,别重造)
- 总图:`docs/handoff/project_planning_map_20260701.md`(2026-07-01 新增;先读它理解算法贡献、场景参数、动态需求和正式重跑四条主线的顺序与 gate)。
- 提示词:`08`(算例已生成)/`09`系列(ALNS 强化历程,e2_alns_final 已实现)/`09b-09h`(扫描/SA/吞吐/诊断,均历史证据)/`10`(基线)/`11`(E2 协议)。
- 记忆:`docs/handoff/memory/` = project-plan-overview / baseline-algorithm-catalog(8基线设计+harness接口) / figure-redesign-task / dynamic-demand-integration / alns-crush-root-cause / deferred-instance-robustness / feedback-communication-style。
- 诊断产物:`baselines/e2_alns/`(09b-09h 报告/数据,80kWh 时代,作历史参考)。
- 算例:`models/data_bundle/generated_instances/e2_benchmark/`(69 算例;正式评价需绑定最终拍板的参数/约束场景)。

## 一句话给 Codex
M1 当前算法线已越过一个新门槛: `metaheuristic_baselines.py` 修复 GA/PSO/LNS/VNS baseline 活性后,单实例 `e2-threeshift-150c-01`、280kWh 门控显示非 ALNS 已能从 `5803.55` 到 `5174.35` 的 EV-heavy 平台,ALNS 变体仍到约 `3701/3639/3364`,最好约 `3364.77`。这只能说明 baseline 已正常发挥且单实例 ALNS 仍强,**不能**写成全实例正式胜利或 carbon-aware 算子胜利。下一步是同实例更长复核:确认非 ALNS 的 `5174` 平台是否会继续下降、ALNS 的 `33xx-37xx` 是否稳定;若稳定,再小范围扩实例。x86 DR 线独立运行,本 M1 线不要接管或混入判断。
