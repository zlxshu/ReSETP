# E2-G0 Closure Reaudit

本任务目标：把 E2-G0 从同质化假象整改到可重审状态，输出 baseline health / G0 gate 证据。它不是正式 T3，不写算法胜负。

Verdict: `G0_RESIDUAL_HOMOGENIZATION`

- HEAD: `cd4742ef51f735b19b68eb7599576fde76926044`
- G0 rows: `15`
- TRUE_REPAIR decision: `TRUE_REPAIR_ALIGNMENT_RECOMMENDED`
- Scenario compliance: `SCENARIO_COMPLIANCE_OK`
- Legacy anchor: `LEGACY_ANCHOR_STILL_UNEXPLAINED`
- Suspect count: `4`
- Failure count: `0`

## Plain Reading

采集闭合，但仍触发 liveness 或同质化嫌疑；按预注册停下，不扩跑 G4/G5。

## Key Findings

- 采集闭合：15/15 行均为 OK 且 eval 跑满；没有把 under-eval 包装成 16000 OK。
- 旧的 5174 精确同质化没有复现：跨 seed / 跨算法逐位同签名嫌疑数为 0。这说明旧平台假象已清掉，但还不足以让 G0 过门。
- liveness 仍有 4 条 baseline run 未过：G0_PSO_seed1, G0_PSO_seed2, G0_PSO_seed3, G0_VNS_seed2。这些失败全部是 `NO_NATIVE_BEST_UPDATE`。
- best-cost 只作定位台账，不作算法胜负主张：ALNS: min=3630.111838, mean=3785.039108, seeds=3 | GA: min=4110.049789, mean=4368.494881, seeds=3 | LNS: min=3554.040068, mean=3563.296463, seeds=3 | PSO: min=4752.195758, mean=4772.622803, seeds=3 | VNS: min=4138.244919, mean=4143.154067, seeds=3。
- TRUE_REPAIR 评分对齐：TRUE_REPAIR_ALIGNMENT_RECOMMENDED。GA: updates 1→2, best 4629.875421→4596.373111; LNS: updates 5→24, best 4289.832865→3788.736454。
- 场景合规：SCENARIO_COMPLIANCE_OK；`DEFAULT_PRICES` 与 `paper_main.tex` 口径一致，1 个历史生成表命中只登记、不改表。
- 旧锚考古：LEGACY_ANCHOR_STILL_UNEXPLAINED；旧代码 + 当前同名 bundle 得到 4779.053444002934，目标旧锚为 4878.331796187524，所以 4878 谱系仍未解释。

## Artifacts

- `metadata.json`, `preflight.json`, `true_repair_ab.csv`, `raw_runs.csv`, `best_trajectory.csv`, `channel_lift.csv`, `liveness_verdicts.csv`
- `true_repair_decision.json`, `scenario_compliance.json`, `legacy_anchor.json`, `decision.json`, `artifact_hashes.json`

## Suspect Sample

```json
[
  {
    "scope": "run",
    "algorithm": "PSO",
    "seed": "1",
    "run_id": "G0_PSO_seed1",
    "verdict": "BASELINE_LIVENESS_FAIL",
    "flags": "NO_NATIVE_BEST_UPDATE",
    "native_best_updates": "0",
    "route_count_unique": "13"
  },
  {
    "scope": "run",
    "algorithm": "PSO",
    "seed": "2",
    "run_id": "G0_PSO_seed2",
    "verdict": "BASELINE_LIVENESS_FAIL",
    "flags": "NO_NATIVE_BEST_UPDATE",
    "native_best_updates": "0",
    "route_count_unique": "12"
  },
  {
    "scope": "run",
    "algorithm": "PSO",
    "seed": "3",
    "run_id": "G0_PSO_seed3",
    "verdict": "BASELINE_LIVENESS_FAIL",
    "flags": "NO_NATIVE_BEST_UPDATE",
    "native_best_updates": "0",
    "route_count_unique": "12"
  },
  {
    "scope": "run",
    "algorithm": "VNS",
    "seed": "2",
    "run_id": "G0_VNS_seed2",
    "verdict": "BASELINE_LIVENESS_FAIL",
    "flags": "NO_NATIVE_BEST_UPDATE",
    "native_best_updates": "0",
    "route_count_unique": "10"
  }
]
```
