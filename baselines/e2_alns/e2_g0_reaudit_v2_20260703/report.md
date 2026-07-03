# E2-G0 Closure Reaudit

本任务目标：修正上一轮 G0 的起点扭曲，所有算法从 shared warm start 起跑；翻转闭包只作为 reference 字段记录。它不是正式 T3，不写算法胜负。

Verdict: `G0_PASS_BASELINES_HEALTHY`

- HEAD: `04f2d2be1e5a206d67a7d1c5333ebe7caa572835`
- G0 rows: `15`
- TRUE_REPAIR decision: `MISSING`
- Scenario compliance: `SCENARIO_COMPLIANCE_OK`
- Legacy anchor: `ANCHOR_LINEAGE_CLOSED`
- Suspect count: `0`
- Failure count: `0`

## Plain Reading

四个 baseline 的 liveness 门禁通过，未触发 seed/cross-algorithm 同质化嫌疑；这里只说明 G0 健康门通过，不构成正式 T3 胜负主张。

## Key Findings

- 采集闭合：15/15 行均为 OK 且 eval 跑满；没有把 under-eval 包装成 16000 OK。
- 旧的 5174 精确同质化没有复现：跨 seed / 跨算法逐位同签名嫌疑数为 0。这说明旧平台假象已清掉，G0 健康门在本次证据上通过。
- liveness 门禁：12/12 baseline run 通过，未标 `WEAK_IMPLEMENTATION`。
- best-cost 只作定位台账，不作算法胜负主张：ALNS: min=3429.873454, mean=3568.483474, seeds=3 | GA: min=4512.349883, mean=4591.542851, seeds=3 | LNS: min=3584.208793, mean=3599.130896, seeds=3 | PSO: min=4469.892560, mean=4576.538634, seeds=3 | VNS: min=3931.793682, mean=4071.566126, seeds=3。
- TRUE_REPAIR 评分对齐：MISSING。没有可用 A/B 摘要。
- 场景合规：SCENARIO_COMPLIANCE_OK；`DEFAULT_PRICES` 与 `paper_main.tex` 口径一致，1 个历史生成表命中只登记、不改表。
- 锚谱系：ANCHOR_LINEAGE_CLOSED；全 seed 均值 4878.331796187524，seed2 4779.053444002934，目标 mean/seed2 分别为 4878.331796187524 / 4779.053444002934。

## Artifacts

- `metadata.json`, `preflight.json`, `raw_runs.csv`, `best_trajectory.csv`, `channel_lift.csv`, `liveness_verdicts.csv`
- `scenario_compliance.json`, `legacy_anchor.json`, `anchor_lineage.json`, `anchor_lineage.csv`, `decision.json`, `artifact_hashes.json`
