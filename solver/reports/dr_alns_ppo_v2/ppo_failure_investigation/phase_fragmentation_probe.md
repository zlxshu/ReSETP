# Phase Fragmentation Probe

- train_bundle: `models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113`
- worker_python: `/opt/anaconda3/bin/python3.13`
- skip_train_probes: `False`

| probe | eval_budget | rollout_timesteps | rollout<budget | expected_episode | monitor | episodes |
|---|---:|---:|---:|---:|---|---:|
| schedule_current_shape | 16000 | 3072 | True | False |  |  |
| schedule_episode_possible | 32 | 64 | False | True |  |  |
| actual_no_episode | 256 | 64 | True | False | zero_episodes | 0 |
| actual_episode_possible | 32 | 64 | False | True | has_episodes | 2 |
