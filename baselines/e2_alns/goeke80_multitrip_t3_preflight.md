# 09t Goeke80 Multi-Trip T3 Preflight

Verdict: `HALT_COLLECTION_COST`

## Plain Reading

大白话：数据没有收完整或有 timeout/违约/环境漂移；不能下科学结论，先修采集问题。

## Phase 0

- Phase0 OK: `True`
- Q/B/v/carbon: `3650.0` / `80.0` / `25.0` / `0.05034`
- 09s warm start rows OK: `True` with `69` rows
- 09s rescue report OK: `True`

## Smoke

- Verdict: `SMOKE_OK`
- Stage gate: `STAGE_SMOKE_OK`
- Rows: `6/6`
- Paired counts: `{"alns": 1, "tie": 2}`
- LNS-dominant groups: `[]`
- Mean EV route share, 75-200 winners: `0.051852`
- All-CV winner share, 75-200: `0.000000`
- Raw rows: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/smoke/smoke_raw_runs.csv`
- Paired summary: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/smoke/smoke_paired_summary.csv`
- Scale summary: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/smoke/smoke_scale_summary.csv`

## Stage A

- Verdict: `STAGE_A_PASS`
- Stage gate: `STAGE_PASS_TO_NEXT`
- Rows: `138/138`
- Paired counts: `{"alns": 7, "lns": 2, "tie": 60}`
- LNS-dominant groups: `[]`
- Mean EV route share, 75-200 winners: `0.057343`
- All-CV winner share, 75-200: `0.000000`
- Raw rows: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_a/stage_a_raw_runs.csv`
- Paired summary: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_a/stage_a_paired_summary.csv`
- Scale summary: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_a/stage_a_scale_summary.csv`

## Stage B

- Verdict: `HALT_COLLECTION_COST`
- Stage gate: `STAGE_HALT`
- Rows: `69/414`
- Paired counts: `{"alns": 5, "lns": 10, "tie": 18}`
- LNS-dominant groups: `[]`
- Mean EV route share, 75-200 winners: `0.000000`
- All-CV winner share, 75-200: `0.000000`
- Raw rows: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_b/stage_b_raw_runs.csv`
- Paired summary: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_b/stage_b_paired_summary.csv`
- Scale summary: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data/stage_b/stage_b_scale_summary.csv`

## Artifacts

- Data dir: `baselines/e2_alns/goeke80_multitrip_t3_preflight_data`
- Report: `baselines/e2_alns/goeke80_multitrip_t3_preflight.md`
- HEAD at run start: `d14ac63da231185de0e084c2ffd0157cefe06c06`
- Artifact commit hash: `pending`
