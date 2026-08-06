# T22 仪表与接线（2026-08-05）

## FACT

终态 `T22_INSTRUMENTATION_BUILD_COMPLETE`。权威证据包为 `docs/handoff/instrumentation_build_20260805/`，新入口为 `baselines/china_e3_e7/run_t21_charging_timing_three_arms_20260805.py`。

HGS 全局安全墙钟已改为可选且默认不启用；只有传入正值才加入停止器。原代理目标比较处现在逐次记录视角、迭代、前值、后值和改善幅度，不新增完整评价；没有接入自动平缓停机。`charge_timing_policy` 已贯通到 shared completion，策略实现和默认 `carbon_min` 未变。

路线池 SciPy 1.16.3 `milp` 现在记录每次实际用时、初始/最终时限、提前结束和延长次数。该接口没有 incumbent callback 或 resumable handle，因此延长未实现且明确记录 `extension_supported=false`、`extension_count=0`。

唯一搜索冒烟为 JJJ / COST_CARBON / seed 2026080201：三视角各 60 次迭代，10 条改善事件，MIP 实耗 0.8706315840827301 秒；最终 100/100 客户、25972/25972 需求、违反 0、搜索/完整目标 4121.404744908565、闭合误差 0。策略夹具起点为 0/1800/5400 秒。`paper_claim_allowed=false`，正式 90 单元批没有启动。

回归为聚焦 20/20；solver 全量 `906 passed / 1 skipped / 6 failed`，六项与既有集合及断言值一致。三个受保护文件前后 SHA-256 一致。历史正式 runner、策略实现、shared completion 与 `audit_alns_budget_g0_20260718.py` 未编辑。

## INFERENCE

该冒烟只证明仪表与物化链贯通，不构成三臂效果证据。当前后端只能诚实支持 MIP 实耗和提前结束审计，不能支持“仍改善则延长”。

## DECISION

`paper_claim_allowed=false`；未登记“长期平缓”窗口。

## HALT_*

无新增 HALT；既有六个 solver 失败保留。
