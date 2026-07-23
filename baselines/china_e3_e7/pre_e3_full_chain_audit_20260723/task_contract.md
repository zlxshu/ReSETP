# PRE-E3-FULL-CHAIN-REVIEWER-AUDIT-001

本目录是 China81 / E3--E7 正式搜索前全链路审计的证据目录。

- 正式搜索：禁止。
- 搜索评价：0。
- 允许：来源核验、静态读取、哈希、bundle 加载、独立算术复算、单元/性质/故障注入测试。
- 不允许：运行 E3--E7 搜索、覆盖封存 raw、静默改变模型/参数/统计口径。
- 权威合同：
  `docs/handoff/china_e3_e7_preflight_full_chain_audit_contract_20260723.md`。
- 跟踪清单：`audit_checklist.csv`。

最终必须形成 `metadata.json`、`raw_runs.csv`、`decision.json`、
`artifact_hashes.json`、`report.md`，并单独给出 E2 影响矩阵和 E3
`GO/HOLD/HALT` 判定。
