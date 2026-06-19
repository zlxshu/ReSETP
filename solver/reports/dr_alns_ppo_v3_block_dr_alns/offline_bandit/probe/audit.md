# Offline Probe Audit

Status: `PASS`.
Dataset: `solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/dataset/block_trace_rows.csv`.
Rows: 1625. Columns: 54. Episodes: 13.

Required columns are present.

| collection_policy | rows |
| --- | ---: |
| alpha_ucb_block | 375 |
| random_block | 125 |
| stratified_random | 1125 |

`random_block` behavior probability is `1/2240` = `0.000446428571`.
`alpha_ucb_block` and `stratified_random` are excluded from IS because they are deterministic collection policies in this dataset.
