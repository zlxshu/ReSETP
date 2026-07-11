# Memory Index

- [Project plan overview](project-plan-overview.md) — global ReSETP paper plan: done / in-progress / left / ETA; role rule (Claude thinks+prompts only, Codex executes, no workflows)
- [Read me first for agents](../READ_ME_FIRST_FOR_AGENTS.md) — 强制启动入口: Codex/Claude 每轮先读, 再读 HANDOFF/PRD v2/planning map/memory/MASTER; 实验必须留四件套和 HANDOFF/memory 记录
- [Communication style](feedback_communication_style.md) — plain Chinese with user; Codex prompts must be precise, actionable, bounded, factual (no jargon, no overdo); always understand+confirm+ask before executing
- [Project PRD execution v2](project-prd-execution-v2.md) — 全项目 PRD/施工图 v2: 宏观路线、E2重点摸排、E1-E7 PDCA、DR-ALNS接入、记录制度、风险门槛; C1已判5174同值平台为ARTIFICIAL_HOMOGENIZATION，C1-R2=PARTIAL_OR_WEAK_SUPPORT(H2确认/H1未确认)，G4/G5冻结
- [Figure redesign task](figure-redesign-task.md) — remake paper figures to top-journal level via Zotero exemplars, pixel-locked specs, Codex only fills data; F4 is a blank/broken figure; blocked on Zotero connection
- [ALNS crush root cause](alns-crush-root-cause.md) — PPO/DR lane 全程日志; winner kernel £4878 健康 + venv 漂移教训; 2026-06-19 离线体检①=HALT_COLLECTION_COST + 监督探针破局设计; user纠正真目标=DR-ALNS真训练+创新干过GA-VNS/GA/PSO(非碾SA)
- [Algorithm pivot: CA-ALNS](algorithm-pivot-ca-alns.md) — 历史快照(2026-06-14/15); 注: 其"目标=碾压SA"口径已纠正(见 project-plan-overview 真目标=DR-ALNS真训练+创新, 干过GA-VNS/GA/PSO); rerun all experiments; carbon numbers change
- [Baseline algorithm catalog](baseline-algorithm-catalog.md) — Zotero整理: 各论文主流算法+item key+复刻来源+推荐基线集; keystone=周鲜成2021综述(在目标期刊); ALNS/DR-ALNS要赢过这些(GA/PSO/SA/TS/ACO/VNS/GA-VNS+混合)
- [Deferred instance robustness](deferred-instance-robustness.md) — later task: re-run carbon stress on three-shift 100/150/200c instances (150/200 not generated yet)

- [Instance lineage](instance-lineage.md) — formal L-main v2 = 9 threeshift ladders only; mixed23/100-01 ARCHIVE_ONLY
- [ReSETP ALNS full independence](resetp-alns-independence.md) — algorithms/resetp_alns package; no N-Wouda runtime; PROVENANCE
- [Control console](control-console.md) — root one-click CONTROL_CONSOLE + PARAMETERS; input/output layout
- [M1/全项目] 2026-07-11（7.31 收稿调度裁决）：研究计划按证据依赖串行推进，只有已经批准的实验批次内部按 instance/seed/algorithm/parameter task 并行运行以利用 CPU；不得把“实验任务并行”误写成 E2、机制、动态、DR 等研究线同时推进。当前 30 次 E2 稳定性门结束后冻结算法方向：通过则只做一次最小正式 E2，不通过则降低算法主张；两种情况都禁止继续 E2 rescue。路线与止损日期见 `docs/handoff/project_parallel_execution_plan_20260711.md`。
- [M1/全项目] 2026-07-11（白话总实验管理体系）：`docs/handoff/project_experiment_master_plan_20260711.md` 是E0--E7总施工图，逐项写明科学问题、设计、任务量、指标、通过/HALT、论文表图和降级路径；`docs/handoff/project_board_20260711.md` 是实时看板；`docs/handoff/templates/EXPERIMENT_CARD_TEMPLATE.md` 是每批实验启动门。管理规则为一个科学问题在制、批内任务并行、结果绑定四件套、7.28后禁止探索实验。
- [M1/E2] 2026-07-11（staged hybrid稳定性门完成）：100c/150c/200c×seeds1--5×hybrid/LNS共30次全部OK、零违规、全部4000/4000 eval；hybrid相对LNS三个规模平均改善6.4477%/0.6880%/14.0797%，11/15成本胜，verdict=`STAGED_HYBRID_STABILITY_SUPPORTED`。边界：280kWh诊断、非正式T3、碳算子关闭。依7.31计划冻结hybrid并拒绝九规模/长预算继续调试，下一步仅做健康基线体检和一次最小正式E2。
- [M1/E2/E1] 2026-07-11（E2冻结、E1主结构通过）：E2 tag=`e2-submission-20260711`固定commit `0124623e`和hash锚，不再改写。E1在commit `c20dae18`完成280kWh最小结构门：20条mixed+5条CV-only零违规满4000；200c mixed的EV客户/需求/距离份额约86.1%/87.2%/82.2%，约60次充电，相对CV-only 4胜1负、平均便宜0.671%。EV-only 5条为`NOT_FOUND`而非不可行证明。详见`docs/handoff/e1_280_structure_closeout_20260711.md`。
- [M1/E3] 2026-07-11（累积消融部分支持）：200c×M0--M5×5 seeds=30/30零违规满4000，commit `b9a59c46`。时变碳同路线充电5/5降EV间接排放、平均20.96%；协同成本4胜1平但跨场仅1/5触发；theta=1公平可行5/5但M4天然已满足，公平绑定0/5。verdict=`E3_PARTIAL_MECHANISM_SUPPORT`，碳转E4、公平转E6。见`docs/handoff/e3_cumulative_ablation_closeout_20260711.md`。
