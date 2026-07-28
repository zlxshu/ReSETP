# Pilot08 C 900s Equal-Wall-Clock Evaluation

Verdict: `WEAK`.
Reason: DR(BEST) did not stably beat AlphaUCB on both 100_02 and 100_03.

This report uses same-machine x86 relative percentages only. It does not compare x86 absolute objectives to M1 results.

## Budget And Model

- EVAL_BUDGET_900: `13100`
- BEST_MODEL: `checkpoint_0240` update `240`
- Final model refine rank: `3`

## Equal-Wall-Clock Check

SA and official winner rows used true timed mode and stayed near 900s on mean runtime. Budget-mode block algorithms shared EVAL_BUDGET_900, but observed runtimes were not uniformly near 900s: alpha_ucb_block on E-UK100_01__d2_s3_seed1_24h_20251113 mean=422.5s, random_block on E-UK100_01__d2_s3_seed1_24h_20251113 mean=1614.7s, alpha_ucb_block on E-UK100_02__u0_seed2_24h_20251113 mean=371.1s, random_block on E-UK100_02__u0_seed2_24h_20251113 mean=1661.0s, alpha_ucb_block on E-UK100_03__u0_seed3_24h_20251113 mean=388.4s, random_block on E-UK100_03__u0_seed3_24h_20251113 mean=1644.0s. Interpret relative percentages with this same-machine runtime caveat.

## Runtime

- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 alpha_ucb_block: mean 422.5s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 official_winner_kernel: mean 901.5s (timed), mean evals 56044.3
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 ppo_block_best: mean 831.9s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 ppo_block_final: mean 831.9s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 random_block: mean 1614.7s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 scikit-opt-SA: mean 901.3s (timed), mean evals 145857.0
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 alpha_ucb_block: mean 371.1s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 official_winner_kernel: mean 902.5s (timed), mean evals 50422.0
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 ppo_block_best: mean 905.9s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 ppo_block_final: mean 837.6s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 random_block: mean 1661.0s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 scikit-opt-SA: mean 902.4s (timed), mean evals 105353.0
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 alpha_ucb_block: mean 388.4s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 official_winner_kernel: mean 901.8s (timed), mean evals 52305.0
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 ppo_block_best: mean 912.0s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 ppo_block_final: mean 862.2s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 random_block: mean 1644.0s (budget), mean evals 13100.0
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 scikit-opt-SA: mean 901.6s (timed), mean evals 102652.7

## Paired Relative Percent

- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs alpha_ucb_block: mean=1.2824% wins=5/5
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs official_winner_kernel: mean=-0.0593% wins=1/3
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs ppo_block_final: mean=1.9216% wins=3/3
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs random_block: mean=-0.8419% wins=0/3
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs scikit-opt-SA: mean=1.4503% wins=3/3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs alpha_ucb_block: mean=0.6881% wins=3/5
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs official_winner_kernel: mean=2.7951% wins=2/3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs ppo_block_final: mean=3.1838% wins=2/3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs random_block: mean=-1.9506% wins=0/3
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs scikit-opt-SA: mean=0.6283% wins=2/3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs alpha_ucb_block: mean=0.2436% wins=2/5
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs official_winner_kernel: mean=8.9163% wins=3/3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs ppo_block_final: mean=7.9159% wins=3/3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs random_block: mean=-1.5023% wins=1/3
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs scikit-opt-SA: mean=-0.5678% wins=1/3

## Wilcoxon

- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs alpha_ucb_block: n=5 wins=5 p=0.03125
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs official_winner_kernel: n=3 wins=1 p=
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs ppo_block_final: n=3 wins=3 p=
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs random_block: n=3 wins=0 p=
- models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113 DR(BEST) vs scikit-opt-SA: n=3 wins=3 p=
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs alpha_ucb_block: n=5 wins=3 p=0.3125
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs official_winner_kernel: n=3 wins=2 p=
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs ppo_block_final: n=3 wins=2 p=
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs random_block: n=3 wins=0 p=
- models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 DR(BEST) vs scikit-opt-SA: n=3 wins=2 p=
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs alpha_ucb_block: n=5 wins=2 p=0.5
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs official_winner_kernel: n=3 wins=3 p=
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs ppo_block_final: n=3 wins=3 p=
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs random_block: n=3 wins=1 p=
- models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 DR(BEST) vs scikit-opt-SA: n=3 wins=1 p=

## Gates

- integrity_ok: `True`
- row_count: `66`
