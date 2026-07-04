# Track23 Stage C 24d No-Tuning Parity

Verdict: `NO_TUNING_PARITY_CLEAN`
Reason: DR stayed within -2% of the strongest non-DR opponent on every bundle; min_gap=-1.926%.

## Bundles

- E-UK100_01__d2_s3_seed1_24h_20251113: DR mean=2601.616320, strongest=best_static_meta mean=2552.459038, gap=-1.926%
- E-UK100_02__u0_seed2_24h_20251113: DR mean=1769.593532, strongest=best_static_meta mean=1763.686225, gap=-0.335%
- E-UK100_03__u0_seed3_24h_20251113: DR mean=1761.301376, strongest=best_static_meta mean=1762.919963, gap=0.092%

## 24d Training

- Best checkpoint: `solver/reports/dr_alns_ppo_v3/final_track23/stage_c_train24/best_val_async_block_ppo.pt`
- Validation mean best_obj: 720.476657

## Pilot16 Sidecar

- Role: `sidecar_only_not_stage_c_gate`
- Clean mean gap vs strongest non-DR: -43.870%
