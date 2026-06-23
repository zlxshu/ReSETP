# MASTER — Codex 接管总规划（Claude credits 将尽，转 Codex 思考+执行）

> 这是 Claude(M1)交给 Codex 的总纲。**Claude 之后基本不在场,Codex 既思考也执行。** 本文件 = 剩余全部规划(总体+局部) + 预备方案 + 行为铁律。每段对话先读本文件 + `CLAUDE-FABLE-5.md` + `HANDOFF.md` + `docs/handoff/memory/`，再动手。

## 0. 给 Codex 的行为铁律(每段对话自我约束,务必照做)
- **先读后做**:每轮先读 `CLAUDE-FABLE-5.md`(用它的思考方式:严谨认知、假设驱动、用代码/数据/文献坐实、不臆测、不停在表面猜测、证据与假设冲突就改假设) + 本文件 + `HANDOFF.md` + `docs/handoff/memory/`。
- **诚实(最高优先)**:跑不出/没收敛/没赢就诚实 HALT 并如实写,**绝不注水、不混旧数据、不拿弱版/没跑满的结果充数、不把推断冒充实证**。哪个档输、和谁打平,照实报。
- **克制**:不自创算法、不无限加料硬刚;碰卡点先翻 Zotero 文献 + 上网找现成解,别重复造轮子;每个改动绑证据 + commit hash;拿不准停下报告,别擅自扩大范围。
- **边界(硬)**:禁改 `cost.py`/`check.py`/`evaluation.py` 语义(唯一真值源);系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5 + `PYTHONHASHSEED=0`;改核心代码立即 commit、数字绑 hash;分支 `codex/reporting-pipeline`。
- 与 user 平实中文;给出判断要带证据,不空谈。

## 1. 现状快照(2026-06-23,参数刚正式化)
- **E2"全油车退化"根因已查实并修复**:真因 = `B_battery_kwh=80`(2013 Goeke/Davis-Figliozzi 老值)对跨城高速(90km/h)路线续航不足→EV 被逼贵公共快充→不划算→优化器选全油。**证据约束诊断(09h)+ 真实重优化确认**:保持跨城 90km/h(route-regime 确认 100/150/200c=regional_cross_city_like,40km/h 仅作 urban/local fork 不用于主算例),电池更新到现代配送电动卡车 **280kWh**(Volvo FL/FE Electric 证据下界)。200c reopt:mixed mean 8616.45 < all-CV 8979.13(gap −4.04%),6 触发场景 seeds1-5 跑满、30/30 reopt OK、零违约。verdict=`HIGHWAY_BATTERY_UPDATE_SUPPORTED`。
- **参数已正式化(09i/09j, commit `8500fd9c`)**:`prices.py` DEFAULT `B_battery_kwh` 80→280(80 历史注释保留);**v=90km/h、carbon=0.05034 未动**;`paper_main.tex` 同步(B 80→280 + Volvo 引用);测试 70 passed;latexmk 过。
- **⚠️ 后果:所有旧正式数字全部作废为历史产物**——£4878 锚、9da7f8b 的 E1-E7、全部 T3-T9/F1-F6、09e/09f/09h 诊断、旧图表,都是 80kWh 时代的;**新参数(280kWh)下必须重跑后才能引用**。这是接下来最大的工作量。
- **诊断来龙去脉(供理解,别重做)**:E2 算法对比上 LNS 基线(=高娇娇2024 GLNS,扫描+LNS+SA、**无 EV/碳机器的通用纯路由器**)曾赢我们的 ALNS。四个工程杠杆(算子09/扫描09b/SA接受09c/吞吐09d)全试过,80kWh 下仍输——因为 80kWh 下最优是全油,我们的碳/EV 感知是死重。**280kWh 下混合最优,GLNS 无 EV 机器找不到最优混合解,我们的 ALNS 理应反超**(待第3步实证)。

## 2. 第一步必查(promote 280 后,防"反向退化")
280kWh 会不会让最优变成**全电动 all-EV**(另一种退化,同样架空"混合车队"故事)?
- **重跑 E1 车型反事实(cv_only/ev_only/mixed)跨规模(25–200c),确认新最优是"真混合"(CV 与 EV 都被用),不是 all-EV。**
- 若多数档变 all-EV → 280 偏高,回退到更保守的证据下界(查 Volvo FL ~265kWh / 中型配送车更低值,Zotero+官方源),重新 09h 式确认。**别为了"混合"硬调,以证据为准,如实报。**
- 通过(真混合)→ 进第3步。
- 2026-06-23 Codex 已把 gate 扩成可恢复队列并跑满 Stage1（代表集 17 实例 × seeds1-3 × 3 variants, 153/153 raw rows, 51/51 winners, 0 timeout）。结论 `HALT_EV_DOMINANT`:51 个 winner 中 34 个 `ev_heavy_mixed`、16 个 `all_ev`、0 个 `balanced_mixed`, mean EV share 多数实例 >0.9。**§2 未通过,Stage2 不启动,E2/T3 与 E1-E7 全量重跑继续暂停。下一步不是进 §3,而是重新决策 280kWh 是否只作为 modern-battery/EV-dominant scenario、是否回退到证据下界电池,或是否接受“现代电池下算例 EV 主导”的论文叙述。**

## 3. 剩余总路线图(按依赖顺序,Codex 自驱执行)
1. **8 基线做到文献最优 + 收敛(已写 `10_e2_baselines_literature_best.md`)**:GA/PSO/VNS/ACO/GA-VNS/LNS/GWO/IWD 按源论文重做、文献标准参数、"真在搜索"硬门禁(std>0 + 改善暖启动 + 收敛曲线明显收敛)。`baseline-algorithm-catalog.md` 有设计转录。
2. **E2 算法对比正式跑出 T3/F2(已写 `11_e2_protocol_and_run.md` + 09c/09d 实现的强化 ALNS)**:强化 ALNS(SA 接受+吞吐提速,`run_e2_alns_final`)+ 公平 SA + 8 基线,**在 69 算例基准(已生成,280kWh 重评)等墙钟**跑;best-found 参照、gap%、Wilcoxon、收敛曲线。**关键预期+必验**:280kWh 混合最优下碳/EV 感知 ALNS 反超 GLNS;**逐档诚实报,若某档仍输 LNS 如实写**(见 §4 预备方案)。
3. **E1-E7 全量重跑(280kWh)= 新正式数字**:设强化 ALNS 为 PRIMARY,重跑 E1-E7,重生成 T3-T9/F1-F6/F5b,碳数字重出、§4.6 碳段更新,latexmk 过。**supersede 9da7f8b,建立 280kWh 时代新锚(绑 commit)。**
4. **图表顶刊级填数画图(已规划 `docs/handoff/memory/figure-redesign-task.md`)**:壳已锁,用新数字填→画→user 审→进正式。F4 修渲染、F6 补 θ 网格。
5. **动态需求整合(`docs/handoff/memory/dynamic-demand-integration.md`)**:E7/T9 必须证明 车场协同/收益公平/时变碳 真参与动态路径决策(动态×协同、动态×公平、动态×碳 三交互证据),否则=堆砌。先查 `run_rolling_reoptimization` 每阶段是否解完整目标。
6. **§3 算法章 + §4.4 算法对比重写**(user 手工定稿文字;Codex 备好 T3/收敛/gap 素材)。
7. **(可选,不阻塞)DR-ALNS**:x86 lane 的锦上添花/future work,训出来再补 T3 的 DR 列;**未训练前不进算法主线、不用于救场**。

## 4. 各步预备方案(contingencies,诚实优先)
- **第2步若 all-EV**:回退电池到证据下界(265/中型车值),别硬保混合;若证据下界仍 all-EV,如实报"现代电池下该算例 EV 主导"=也是真发现。
- **第3步(E2)若强化 ALNS 仍输 LNS**(280kWh、混合最优下):先查是不是又回到"算法方差/可靠性"问题(09c/09d 的残留);文献找现成稳定化(SA 降温重调/多起点);**仍不过则诚实定位"ALNS 与 LNS 同档第一梯队、差异化靠碳感知机制+DR",不硬刚不注水**(符合既定 bar:对手更强+贴近最优+创新清晰,非碾弱对手)。绝不退回旧 80kWh 数据。
- **E1-E7 重跑算力**:各 10seed×16000eval=天级以内,resumable;200c 单期慢→硬超时返回 incumbent(09d 已修)。
- **图表数字**:必须来自 280kWh 重跑后的 CSV,旧数字一律不灌。
- **跨机**:x86 dr-x86 分支的 DR 小产出经 GitHub/U盘合并;HANDOFF 冲突 x86 标 `[x86/DR]`、M1 标 `[M1]` 两边保留。

## 5. 索引(已有资产,别重造)
- 提示词:`08`(算例已生成)/`09`系列(ALNS 强化历程,e2_alns_final 已实现)/`09b-09h`(扫描/SA/吞吐/诊断,均历史证据)/`10`(基线)/`11`(E2 协议)。
- 记忆:`docs/handoff/memory/` = project-plan-overview / baseline-algorithm-catalog(8基线设计+harness接口) / figure-redesign-task / dynamic-demand-integration / alns-crush-root-cause / deferred-instance-robustness / feedback-communication-style。
- 诊断产物:`baselines/e2_alns/`(09b-09h 报告/数据,80kWh 时代,作历史参考)。
- 算例:`models/data_bundle/generated_instances/e2_benchmark/`(69 算例,280kWh 下重评)。

## 一句话给 Codex
根因已解决(电池 80→280,证据约束+reopt 确认);**现在按 §2→§3 顺序自驱重跑出 280kWh 时代的正式数字**;全程诚实+克制+用 fable5 思考方式约束自己,跑不出就 HALT、绝不注水。
