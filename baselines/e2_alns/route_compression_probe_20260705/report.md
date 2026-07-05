# E2 Route Compression Probe

本探针只验证 hard subset 上的显式路线压缩组件，不是正式 T3，不写 TeX。

Verdict: `ROUTE_COMPRESSION_FIX_NOT_SUPPORTED`

## Current A0 vs LNS

- instances: `23`
- A0 wins/losses/ties vs LNS: `6/16/1`
- mean gap: `-0.007131889956741538`
- median gap: `-0.007964139782654098`
- hard subset count: `16`

## Root Cause Replay

- mean total delta A0-LNS: `23.77856434493994`
- mean route count delta A0-LNS: `0.3125`
- mean fixed cost delta A0-LNS: `25.0`
- route/fixed supported: `True`

## Profile Summary

| profile | wins | losses | mean gap | route delta vs A0 | infeasible | under-eval | eligible |
|---|---:|---:|---:|---:|---:|---:|---|
| A0_CURRENT | 0 | 16 | -0.016857446185637868 | 0.0 | 0 | 0 | False |
| A1_RELAXED_ROUTE_COMPRESSION | 4 | 12 | -0.013073362074800225 | -0.1041666666666666 | 0 | 0 | False |
| A2_RELAXED_ROUTE_COMPRESSION_LOCAL_SEARCH | 0 | 16 | -0.016189810717862328 | -2.220446049250313e-16 | 0 | 0 | False |

## Anchors

- parity ok: `True`

## Artifacts

- Data dir: `baselines/e2_alns/route_compression_probe_20260705`
- `decision.json`
- `report.md`
- `hard_subset_instances.csv`
- `profile_summary.csv`
- `raw_runs.csv`
- `cost_decomposition.csv`
- `anchor_parity.json`
- `metadata.json`
- `artifact_hashes.json`
