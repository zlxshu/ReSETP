# Pilot10 Block-Meta Rescue

Verdict: `WEAK_RETUNE`.

This report uses same-machine x86 relative percentages only. It does not compare x86 absolute objectives to M1 results.

## D1 Static Meta

- status: `PASS_D1`
- BEST_STATIC_META: `meta_q0.40_t0.0025_e0.15` q=0.4 threshold=0.0025 exploration=0.15
- train relative vs default: `1.0671454318809936`
- held relative vs default: `1.9076305917112837` wins `4/5`

## Training Health

- ok: `True`
- episodes: `8483`
- updates: `595`

## Paired Relative Percent

- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 block_meta_best vs best_static_meta: mean=0.1467% wins=2/5
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 block_meta_best vs best_static_meta: mean=0.5756% wins=2/5
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 block_meta_best vs best_static_meta: mean=-1.0830% wins=1/5

## Wilcoxon

- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 vs best_static_meta: n=5 wins=2 p=0.5
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 vs best_static_meta: n=5 wins=2 p=0.40625
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 vs best_static_meta: n=5 wins=1 p=0.9375

## Reason

Static meta beat default, but learned block_meta did not beat BEST_STATIC_META on train and held-out with positive mean and >=4/5 wins.

