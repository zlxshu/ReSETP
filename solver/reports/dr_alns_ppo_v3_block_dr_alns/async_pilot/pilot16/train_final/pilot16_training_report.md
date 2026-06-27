# Pilot16 Training Health Report

Status: `PASS_PILOT16_TRAINING_HEALTH`

Interpretation: this is a training-health gate only. It proves the long all-scale run completed cleanly enough to evaluate; it is not a DR-vs-baseline performance verdict.

Episodes: `11280`; valid steps: `50003`; updates: `375`; checkpoints: `37`.
Selected config: actors `6`, eval_budget `20`, block_size `4`.
Throughput final: `910.42` episodes/hour; busy ratio `0.982`.
Memory: peak used `13831.7` MB; min available `2404.3` MB.
Candidate nondefault rate: `0.645`; search-control noncontinue rate: `0.496`.
Entropy first/mid/final/min: `9.194` / `8.712` / `8.679` / `8.319`.

## Phase Counts

- carbon: `10270` episodes
- energy: `505` episodes
- route: `505` episodes

## Scale Counts

- 100c: `2256` episodes
- 150c: `2256` episodes
- 200c: `2256` episodes
- 50c: `2256` episodes
- 75c: `2256` episodes

## Checks

- completed_episodes_ge_5000: `True`
- completed_episodes_ge_8000: `True`
- all_15_train_bundles_touched: `True`
- route_energy_carbon_present: `True`
- zero_violations: `True`
- feasible_all: `True`
- worker_py313: `True`
- numpy_235: `True`
- device_cuda: `True`
- finite_rewards: `True`
- finite_best_obj: `True`
- checkpoint_count_ge_5: `True`
- candidate_nondefault_rate_ge_40pct: `True`
- search_noncontinue_rate_ge_5pct: `True`
- entropy_not_collapsed: `True`
- large_scale_not_sustained_worse: `True`

## Large-Scale Trend

- 150c: `{'episode_rows': 2256, 'normalized_best_obj_thirds': [0.9969380772815352, 0.9960009074688461, 0.9959995595015549], 'sustained_worse': False}`
- 200c: `{'episode_rows': 2256, 'normalized_best_obj_thirds': [0.9997746432281507, 0.9994994480663512, 0.9994086989537546], 'sustained_worse': False}`
