# DR-ALNS-PPO Real3 Pilot

- verdict: `WEAK`
- reason: The medium pilot did not show a convincing reward trend plus training-set AlphaUCB proximity.
- system_worker_python: `/opt/anaconda3/bin/python3.13`
- reward_up: `False`
- episode_count: 0
- first_third_mean_reward: None
- last_third_mean_reward: None
- reward_slope: None

## Median Cost By Split

- train: `{"alpha_ucb_env": 5758.276001970554, "ppo_full": 5900.199891327239, "random_full": 5412.281684326282}`
- 100-01: `{"alpha_ucb_env": 4848.619847811227, "ppo_full": 6085.923811179165, "random_full": 4788.89040673416}`
- held_out: `{"alpha_ucb_env": 3951.9634151920627, "ppo_full": 4222.7854921365815, "random_full": 3543.0153484069533}`

## Integrity

- ok: `True`
- budget_mismatches: 0
- violations: 0
- non_system_worker: 0