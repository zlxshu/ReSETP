# S2 全量三视角补跑任务卡

本阶段只有在 `preflight_gate/decision.json` 为 `PASS_S1_THREEVIEW_PREFLIGHT` 时启动。

冻结范围：China81 全部 81 题，种子 1–5，新增 `cv_only` 与 `naive_ev` 两个单视角；每个单元沿用 P3 的 `mother` 单视角收敛逻辑、`TIER_CAPS`、`complete_china81_route_skeleton` 和 `exact_china81_score`。P3 的 `mother`（`mechanism_ev`）与 `full`（MV-HGS-SP）从只读 `p3_china81_gate/raw_runs.csv` 复用，不重跑、不改写。

接受条件：810 个新增单元各有一行且均为 exact-feasible；P3 复用键完整且无重复；附录 A1 生成 81 行。任一单元出现异常、violation 或复用账不完整，写 `HALT_S2_*` 并停止，不改评分器、实例、停止规则或视角定义。

断点规则：只跳过已有 `OK` 的 `(instance_id, seed, route_proxy_mode)`；已有非 `OK` 行不重写、不覆盖，直接进入 HALT，保留现场。

产物：`raw_runs.csv`、`appendix_a1.csv`、`appendix_a1_numeric.csv`、`metadata.json`、`decision.json`、`artifact_hashes.json`、`report.md` 和最后写出的 `done.json`。AppleDouble 旁车不进入哈希；发现时标记 `HASH_CONTAMINATED_APPLEDOUBLE`，清理后重算，不覆盖 raw。
