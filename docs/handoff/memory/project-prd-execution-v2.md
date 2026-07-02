---
name: project-prd-execution-v2
description: 全项目 PRD 与施工图 v2；用于 Codex 执行 ReSETP 宏观规划、E2 重点摸排、E1-E7 PDCA、DR-ALNS 接入、记录制度和风险门槛。
metadata:
  node_type: memory
  type: project
  updated: 2026-07-02
---

2026-07-02 新增 `docs/handoff/project_prd_execution_map_v2_20260702.md`。这是全项目级 PRD/施工图，不只是 E2 PRD。

同日新增强制启动入口 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`，并已挂入 `AGENTS.md`、`CLAUDE.md`、`docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md`、`docs/handoff/codex_prompts/README.md`。Codex/Claude 每轮非平凡任务必须先读该入口和其清单，读完前不得动手。

核心裁决：E2 是关键路径；先做 `5174.345121253789` 同值平台审计，再做 ALNS 独立化、场景口径裁决、基线补全、多实例复核、正式 T3。当前主工作区中 GA 长复核已补到 `16000/16000 OK`，所以旧 PRD 里的 GA under-eval 已过时；但 GA/LNS/PSO/VNS 同值平台仍是一票否决级风险。

宏观纪律：`HANDOFF.md` 是单一事实源；原始 CSV/JSON 优先于报告散文；禁止为救结果改 `cost.py`/`check.py`/`evaluation.py`；参数变更必须四同步；固定 eval 与等墙钟必须双账本；DR-ALNS 不得污染 E2，只有过同环境同预算健康 baseline 门槛后才能进正文。

2026-07-02 圆桌裁决补充：DR-ALNS 目前只能作为可插拔策略层和 x86 并行研发线；M1 正式 E2 默认关闭 DR checkpoint。若 `_dynamic_reward` 缺少真实动态字段，只能标 `DYNAMIC_REWARD_SIGNAL_MISSING`。AppleDouble `._*` 若进入 `artifact_hashes.json`，该 hash 必须标 `HASH_CONTAMINATED_APPLEDOUBLE` 并清理重算。

下一步 Codex 自包含提示词：`docs/handoff/codex_prompts/20260702_c1_e2_g0_plateau_5174_audit.md`，只做 C1/E2-G0 平台审计，不启动 G4/G5 正式扩跑。

E7 动态需求必须保留三交互门槛：动态×协同、动态×公平、动态×时变碳。若 `min_fairness_ratio=off` 或无 EV 充电，必须诚实降级。

关联：[[dynamic-demand-integration]] [[baseline-algorithm-catalog]] [[alns-crush-root-cause]] [[project-plan-overview]]
