# MASTER — Codex 接管总规划（Claude credits 将尽，转 Codex 思考+执行）

> 这是 Claude(M1)交给 Codex 的总纲。**Claude 之后基本不在场,Codex 既思考也执行。** 本文件 = 剩余全部规划(总体+局部) + 预备方案 + 行为铁律。每段对话先读本文件 + `CLAUDE-FABLE-5.md` + `HANDOFF.md` + `docs/handoff/memory/`，再动手。

## 0. 给 Codex 的行为铁律(每段对话自我约束,务必照做)
- **先读后做**:每轮先读 `CLAUDE-FABLE-5.md`(用它的思考方式:严谨认知、假设驱动、用代码/数据/文献坐实、不臆测、不停在表面猜测、证据与假设冲突就改假设) + 本文件 + `HANDOFF.md` + `docs/handoff/memory/`。
- **诚实(最高优先)**:跑不出/没收敛/没赢就诚实 HALT 并如实写,**绝不注水、不混旧数据、不拿弱版/没跑满的结果充数、不把推断冒充实证**。哪个档输、和谁打平,照实报。
- **克制**:不自创算法、不无限加料硬刚;碰卡点先翻 Zotero 文献 + 上网找现成解,别重复造轮子;每个改动绑证据 + commit hash;拿不准停下报告,别擅自扩大范围。
- **边界(硬)**:禁改 `cost.py`/`check.py`/`evaluation.py` 语义(唯一真值源);系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5 + `PYTHONHASHSEED=0`;改核心代码立即 commit、数字绑 hash;分支 `codex/reporting-pipeline`。
- 与 user 平实中文;给出判断要带证据,不空谈。

## 1. 现状快照(2026-06-24,09n 后)
- **09h/09i 的 280kWh 结论已被 09k 细化,不能再简单写成"根因已解决→直接重跑正式 E2"**。09h 证明了 280kWh 能让 mixed/EV 击败 all-CV fixed reference,但 280kWh fleet-composition gate 随后证明它把主问题推到另一端:代表集 winner 以 EV-heavy/all-EV 为主,不是稳定真混合。因此 **E2/T3 与 E1-E7 全量重跑继续暂停**。
- **09k evidence-bound battery spectrum gate 已跑满**:`baselines/e2_alns/battery_spectrum_transition.py` 用文献/车型明确 kWh 值构建谱系,不使用拍脑袋等距网格;冻结 `prices.py`/`cost.py`/`check.py`/`evaluation.py` 和算法语义,只做内存电池 override。screen 跑 21 个证据值;full gate 选 6 个锚点 `80/100/113/141/210/280kWh`,代表集 17 实例 × seeds1-3 × 3 variants 全跑满,918/918 rows,0 timeout/error。
- **09k 关键事实**:严格 balanced 只出现在旧文献锚 `80kWh`（mean EV share 0.408, 32/51 balanced winners）；当前车型证据没有稳健 balanced 候选。`100kWh` 是边界点（mean EV share 0.681）但 winner 多数已 EV-heavy（30/51）；`113/141/210/280kWh` 全部 EV-dominant（mean EV share 0.780/0.877/0.898/0.898）。报告 verdict=`BALANCED_EVIDENCE_BAND_FOUND`,但解释必须读全:这个 balanced 是旧文献锚,不是现代中型车主场景通行证。
- **当前默认代码仍是 280kWh(09i/09j commit `8500fd9c`)**,但它现在应视为 **modern-battery/EV-dominant scenario candidate**,不能直接作为"混合车队主场景"进入正式表图。旧 80kWh 结果也不能恢复成现代主场景,只能作为 Goeke/Chen 文献锚或历史 baseline。
- **09l 来源约束实践混合带 gate 已跑满 Stage A,电池单参数路线暂时关门**:`baselines/e2_alns/source_bound_mixed_band_gate.py` 对 19 个真实来源候选(60-291kWh,不含 80 主候选)跑全梯度 `-01` 实例 × seed1 × 3 variants,`1311/1311` rows 跑满、0 timeout/error。结论 `BATTERY_ONLY_INSUFFICIENT`(screen-gated,不是 Stage C confirmation):没有任何非 80kWh 来源候选 pass/near-pass。低端 81/82.6/89kWh 全局均值看似混合但跨规模失败;100kWh 只有 11/23 实例过带并已开始 EV-heavy;113kWh 起多数规模 EV-heavy/all-EV。Stage B/C 因无幸存候选不触发。
- **09m 首轮只读结构审计已完成**:`baselines/e2_alns/structural_mixed_band_investigation.py` 审计 69/69 实例结构并把 09l Stage A 限定到 75-200 拼接分析。结论:75-200 不是单一电池问题;地理包络相近,大规模客户密度更高且最近公共站距离下降,反而可能让 EV 更容易。最重要新线索是 fleet count:当前 `infer_fleet_limits()` 是 unbounded fleet,`check.py` 明确 fleet count 不再硬约束,而 metadata 仍有 `num_cv/num_ev`;EV-heavy 解常用几十条 EV route。下一步 09m 正式诊断优先查 EV 数量/资本约束,再查充电容量/站点可用性/长路线 eligibility。
- **09n 车辆数量上限诊断已跑到 Stage A 并 HALT**:`baselines/e2_alns/fleet_cap_operational_gate.py` 证实 unbounded fleet 线索真实:现有 winners 确实常超过 metadata 车辆数,280kWh 下 EV routes 可到约 70,而 Goeke/ReSETP metadata 在 75/100/150/200c 只有约 5/6-7/9-10/12-14 台 EV。但用 `SearchPolicy(max_ev/max_cv)` 诊断壳直接套原始车数并没有给出可正式化方案:`goeke_total_cap` 与 `depot_scaled_cap` 主要 `INIT_INFEASIBLE`,`goeke_ev_cap_only` 虽压住 EV-dominant,但均值落在下界外(route/customer/demand/distance 约 0.193/0.189/0.191/0.190)且有 fake-balance,加上 7 个 timeout/error,结论 `HALT_COLLECTION_COST`,Stage B/C 不触发。
- **诊断来龙去脉(供理解,别重做)**:E2 算法对比上 LNS 基线(=高娇娇2024 GLNS,扫描+LNS+SA、无 EV/碳机器的通用纯路由器)曾赢我们的 ALNS。80kWh 端 EV 续航不足,280kWh 端 EV 太强。真正的论文主线要在 **证据约束参数** 与 **现实运营约束** 之间选择,不能为了凑混合硬调电池。

## 2. 当前用户纠偏后的判据
不要继续自动进入 E2/T3。09k 之后的正确目标不是找 1:1 混合,也不是把 80kWh 当退路,而是找 **来源真实、可解释、跨规模稳定的实践混合带**。

- **80kWh 已不能作为现代主场景候选**。它在 09k full gate 下平衡,但这正是之前被 09f/09h 推翻的旧电池问题:大规模/跨城下 80kWh 续航太小,导致全-CV/EV 不可用机制。80kWh 只保留为 Goeke/Chen 文献锚和历史参考,不得再包装成现代参数主场景。
- **电池值必须来自真实来源**:2020 年后文献、Zotero PDF、或真实车型/官方资料明确给出的 kWh。不得用等距网格、插值、或为了凑混合自造 90/95/105 这类值。没有来源就不能解释,后期论文也站不住。
- **未来若拍板任何新默认电池容量,必须同步三处事实源**:不能只改 `prices.py`。必须同时更新 `docs/paper_submission_final/paper_main.tex` 的参数表/参数说明、补齐或更新 bibliography 中的新来源引用、并在 `solver/src/setp_solver/prices.py` 注释中写清"旧参数值+旧来源"与"新参数值+新来源+诊断证据"。旧 Goeke/Davis-Figliozzi 80kWh 与当前 280kWh 证据链都要保留痕迹,不能被静默覆盖。
- **比例标准改成实践混合带**:不要求 1:1,允许研究趋势偏 EV,但 winner 的 EV/CV 实际占比至少应落在 20%-80% 区间内。主指标先用 `EV route share`；报告还应尽量补 `served customers / distance / demand` share,避免路线数假平衡。
- **不能只看全局均值或单个算例**:必须按 family × size 梯度逐项报告,并包含稳定性校验算例。一个电池值只有在所有梯度规模、稳定性实例、seeds 下多数 winner 都维持 20%-80% 实践混合,才算故事立住。
- **09l/09m/09n 已给出下一步方向**:真实来源电池容量单参数不足,原始车辆数量上限的 SearchPolicy 诊断壳也不足以直接支撑跨规模 20%-80% 实践混合带。不要继续微调无来源电池,也不要直接把 Goeke 车数写成硬约束。下一步应进入更真实的运营约束设计,优先查场站充电容量、公共桩稀缺/可用性、EV 资本预算、路线 eligibility；若继续研究 fleet count,必须先正式定义车辆复用/车次数学语义。任何运营约束都要先有证据矩阵和最小语义设计,不能直接改 `cost.py/check.py/evaluation.py`。

## 3. 剩余总路线图(拍板后再执行)
1. **8 基线做到文献最优 + 收敛(已写 `10_e2_baselines_literature_best.md`)**:GA/PSO/VNS/ACO/GA-VNS/LNS/GWO/IWD 按源论文重做、文献标准参数、"真在搜索"硬门禁(std>0 + 改善暖启动 + 收敛曲线明显收敛)。`baseline-algorithm-catalog.md` 有设计转录。
2. **E2 算法对比正式跑出 T3/F2**:只有在第2节主叙事确定并通过相应 gate 后才跑。不要在 280kWh EV-dominant 状态下写"混合最优"故事。
3. **E1-E7 全量重跑 = 新正式数字**:参数/约束主场景确定后再重跑。旧 9da7f8b、旧 80kWh 和 280kWh 暂态结果均不得直接灌正式表图。
4. **图表顶刊级填数画图(已规划 `docs/handoff/memory/figure-redesign-task.md`)**:壳已锁,用新数字填→画→user 审→进正式。F4 修渲染、F6 补 θ 网格。
5. **动态需求整合(`docs/handoff/memory/dynamic-demand-integration.md`)**:E7/T9 必须证明 车场协同/收益公平/时变碳 真参与动态路径决策(动态×协同、动态×公平、动态×碳 三交互证据),否则=堆砌。先查 `run_rolling_reoptimization` 每阶段是否解完整目标。
6. **§3 算法章 + §4.4 算法对比重写**(user 手工定稿文字;Codex 备好 T3/收敛/gap 素材)。
7. **(可选,不阻塞)DR-ALNS**:x86 lane 的锦上添花/future work,训出来再补 T3 的 DR 列;**未训练前不进算法主线、不用于救场**。

## 4. 各步预备方案(contingencies,诚实优先)
- **09l 已确认真实来源候选均不跨规模通过;09m/09n 确认 fleet/operation 是真线索但原始车数 cap 不足以直接提升**:不要继续向下微调电池找刀刃;后续主线进入运营结构诊断。
- **运营约束退路**:先做证据矩阵和最小语义设计,不要一上来改 `cost.py/check.py/evaluation.py`;任何新增约束必须有现实解释、可关开关、旧语义可复现。09n 后优先级调整为:场站充电容量、公共桩稀缺/可用性、EV 资本预算、跨城长路线 EV eligibility；车辆数上限仍是线索,但不能直接使用 Goeke metadata cap,除非先正式建模车辆复用/车次数学语义并有文献/场景支持。
- **参数正式化退路**:无论最后是电池容量、运营约束还是场景分叉,只要进入默认参数/论文主场景,就必须同步代码默认值、代码注释来源、TeX 参数表、TeX 表下注释、bibliography、HANDOFF,并显式说明旧参数为什么保留为历史/文献锚而不是当前主场景。
- **第3步(E2)若强化 ALNS 仍输 LNS**(在已拍板并通过 gate 的主参数/约束场景下):先查是不是又回到"算法方差/可靠性"问题(09c/09d 的残留);文献找现成稳定化(SA 降温重调/多起点);**仍不过则诚实定位"ALNS 与 LNS 同档第一梯队、差异化靠碳感知机制+DR",不硬刚不注水**(符合既定 bar:对手更强+贴近最优+创新清晰,非碾弱对手)。绝不退回旧数据凑赢。
- **E1-E7 重跑算力**:各 10seed×16000eval=天级以内,resumable;200c 单期慢→硬超时返回 incumbent(09d 已修)。
- **图表数字**:必须来自最终拍板主场景重跑后的 CSV,旧数字一律不灌。
- **跨机**:x86 dr-x86 分支的 DR 小产出经 GitHub/U盘合并;HANDOFF 冲突 x86 标 `[x86/DR]`、M1 标 `[M1]` 两边保留。

## 5. 索引(已有资产,别重造)
- 提示词:`08`(算例已生成)/`09`系列(ALNS 强化历程,e2_alns_final 已实现)/`09b-09h`(扫描/SA/吞吐/诊断,均历史证据)/`10`(基线)/`11`(E2 协议)。
- 记忆:`docs/handoff/memory/` = project-plan-overview / baseline-algorithm-catalog(8基线设计+harness接口) / figure-redesign-task / dynamic-demand-integration / alns-crush-root-cause / deferred-instance-robustness / feedback-communication-style。
- 诊断产物:`baselines/e2_alns/`(09b-09h 报告/数据,80kWh 时代,作历史参考)。
- 算例:`models/data_bundle/generated_instances/e2_benchmark/`(69 算例;正式评价需绑定最终拍板的参数/约束场景)。

## 一句话给 Codex
09l/09m/09n 已证明:真实来源电池值单参数不能让非 80kWh 候选跨所有梯度规模稳定维持 20%-80% 实践混合带;unbounded fleet 是真实线索,但原始 Goeke/ReSETP 车辆数 cap 用 SearchPolicy 壳诊断后没有给出可正式化方案。**不要自驱进入 E2/T3,也不要继续调无来源电池值或直接硬套车辆数上限;下一步应写新的运营约束方案,重点查充电容量/公共桩稀缺/EV 资本预算/路线 eligibility,并先做证据矩阵+最小语义设计,再由 user 拍板是否实现。** 全程诚实+克制+用 fable5 思考方式约束自己,跑不出就 HALT、绝不注水。
