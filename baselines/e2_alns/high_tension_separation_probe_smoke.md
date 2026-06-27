# 09v High-Tension ALNS vs LNS Separation Probe

Evidence level: **PROBE / 非正式 T3**. This report does not claim formal algorithm dominance.

Verdict: `INCONCLUSIVE_NO_NONDEGENERATE_TENSION`

## Plain Reading

09v PROBE 未找到非退化且充电/EV 机制真正咬合的高张力档；all-CV/all-EV 退化档的打平不证伪机制假设，但也不能支撑正式 T3。

本步服务的目标：验证 ALNS 在 Goeke80/100 下与 LNS 打平，是否只是因为 EV/充电/碳机制几乎不活跃；若电池档提高后机制咬合，ALNS-LNS 配对差是否随之分离。

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- 09s warm start rows OK: `True` with `69` rows

## Mechanism Separation Summary

| battery tier | mean EV route share (75-200) | mean charging actions | ALNS/tie/LNS | mean gap % ALNS-LNS | Wilcoxon p | majority all-CV/all-EV |
|---|---:|---:|---:|---:|---:|---:|
| 80 (Goeke old anchor) | 0.0519 | 1.00 | 0/2/0 | 0.0000 | 1 | False |
| 100 (boundary) | 0.0519 | 1.00 | 0/2/0 | 0.0000 | 1 | False |
| 150 (source-supported vehicle class) | 0.0519 | 1.00 | 0/2/0 | 0.0000 | 1 | False |
| 280 (modern truck) | 0.0519 | 1.00 | 0/2/0 | 0.0000 | 1 | False |

## Stage Decision

- Stage B recommended: `False`
- Stage B reason: Stage B not triggered by the preregistered Stage A rule.
- Stage B candidate scenarios: `[]`
- PASS candidate scenarios: `[]`

## Caveat

If a battery tier degenerates into majority all-CV or majority all-EV, a tie there is not evidence against the target hypothesis. The hypothesis concerns non-degenerate contested regimes where EV use and charging actually bind.

## Artifacts

- Data dir: `baselines/e2_alns/high_tension_separation_probe_smoke_data`
- Raw rows: `baselines/e2_alns/high_tension_separation_probe_smoke_data/raw_runs.csv`
- Paired summary: `baselines/e2_alns/high_tension_separation_probe_smoke_data/paired_summary.csv`
- Mechanism summary: `baselines/e2_alns/high_tension_separation_probe_smoke_data/mechanism_summary.csv`
- Wilcoxon summary: `baselines/e2_alns/high_tension_separation_probe_smoke_data/wilcoxon_summary.csv`
- Stage decision: `baselines/e2_alns/high_tension_separation_probe_smoke_data/stage_decision.json`
- Artifact hashes: `baselines/e2_alns/high_tension_separation_probe_smoke_data/artifact_hashes.json`
- Report: `baselines/e2_alns/high_tension_separation_probe_smoke.md`
- HEAD at run start: `9b6e2e2629fa88ad616f1d06fd76c2f4d96339b1`
- Artifact commit hash: `pending`

## Collection Failures

| scenario | instance | algorithm | seed | status | bucket |
|---|---|---|---:|---|---|
|  |  |  |  | none |  |

## Interpretation Rules

- `80/100/150/280kWh` are in-memory diagnostic battery overrides only.
- Carbon price stays fixed at `0.05034`; no cost/check/evaluation/default-parameter semantics are changed.
- Stage A is a trend probe. Stage B only runs if the preregistered Stage A signal appears.
