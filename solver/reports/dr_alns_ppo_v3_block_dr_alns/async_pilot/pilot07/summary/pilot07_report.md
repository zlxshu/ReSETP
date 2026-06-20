# Pilot07 Reduced-Budget DR Trend Report

Verdict: `WEAK`.
Reason: Valid reduced-budget pilot completed, but DR did not non-worsen AlphaUCB(block) on the required train/formal checks and no sufficient trend override was present.

This report uses same-machine relative percentages only. It does not compare x86 absolute objectives to M1 results.

## Integrity

- ok: `True`
- row_count: `66`
- worker_mismatches: `0`
- numpy_mismatches: `0`
- budget_mismatches: `0`
- violations: `0`

## Training

- episode_count: `136`
- phases_seen: `['carbon', 'energy', 'route']`
- entered_carbon: `True`
- reward_slope: `0.022405249644739937`

## Paired Relative Percent

- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 ppo_block vs alpha_ucb_block: mean=1.6338% n=5
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 ppo_block vs alpha_ucb_env: mean=0.8828% n=3
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 ppo_block vs official_winner_kernel: mean=0.8828% n=3
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 ppo_block vs random_block: mean=3.6364% n=3
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 ppo_block vs scikit-opt-SA: mean=22.5832% n=3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 ppo_block vs alpha_ucb_block: mean=-4.7740% n=5
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 ppo_block vs alpha_ucb_env: mean=-1.2042% n=3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 ppo_block vs official_winner_kernel: mean=-1.2042% n=3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 ppo_block vs random_block: mean=-3.0509% n=3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 ppo_block vs scikit-opt-SA: mean=16.9028% n=3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 ppo_block vs alpha_ucb_block: mean=-6.0567% n=5
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 ppo_block vs alpha_ucb_env: mean=4.4352% n=3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 ppo_block vs official_winner_kernel: mean=4.4352% n=3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 ppo_block vs random_block: mean=-6.1876% n=3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 ppo_block vs scikit-opt-SA: mean=10.7503% n=3
