# DR-ALNS-PPO Real3 Pilot

- verdict: `WEAK_AFTER_VALID_TRAINING`
- reason: Episode-safe training completed, but PPO did not show the required reward trend plus 100-01 AlphaUCB proximity.
- system_worker_python: `/opt/anaconda3/bin/python3.13`
- reward_up: `False`
- episode_count: 72
- first_third_mean_reward: 2001.6399916666667
- last_third_mean_reward: 1919.2486291666667
- reward_slope: -4.500528683516626

## Median Cost By Split

- train: `{}`
- 100-01: `{"alpha_ucb_env": 4848.619847811227, "ppo_full": 6085.923811179165, "random_full": 4788.89040673416}`
- held_out: `{"alpha_ucb_env": 3951.9634151920627, "ppo_full": 4222.7854921365815, "random_full": 3543.0153484069533}`

## Integrity

- ok: `True`
- budget_mismatches: 0
- violations: 0
- non_system_worker: 0