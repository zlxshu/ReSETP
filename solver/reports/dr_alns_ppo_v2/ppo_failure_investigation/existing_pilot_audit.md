# Existing Real3 Pilot Audit

- pilot_dir: `/Volumes/移动硬盘（512G）/ReSETP/solver/reports/dr_alns_ppo_v2/pilot_real3`
- eval_budget: `16000`
- phase_count: `326`
- rollout_timesteps_range: `3072..3072`
- phase_timesteps_lt_eval_budget: `True`
- monitor_status: `zero_episodes`
- episode_count: `0`
- zero_violation_rows: `True`
- budget_consistent_rows: `True`

## Cost And Action Summary

| split | algorithm | rows | mean | median | best | top action share | top destroy | top repair | top q |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| eval_10001 | alpha_ucb_env | 10 | 4878.331796 | 4848.619848 | 4779.053444 | 0.315800 | route_segment_removal | greedy_insert_repair |  |
| eval_10001 | ppo_full | 10 | 6085.923811 | 6085.923811 | 6085.923811 | 1.000000 | vehicle_type_swap | greedy_insert_repair | 0.166667 |
| eval_10001 | random_full | 10 | 4781.121851 | 4788.890407 | 4739.860025 | 0.017319 | vehicle_type_swap | regret3_insert_repair | 0.200000 |
| eval_held_out | alpha_ucb_env | 10 | 3902.509680 | 3951.963415 | 3471.164732 | 0.298431 | route_segment_removal | regret2_insert_repair |  |
| eval_held_out | ppo_full | 10 | 4222.785492 | 4222.785492 | 4222.785492 | 1.000000 | vehicle_type_swap | greedy_insert_repair | 0.166667 |
| eval_held_out | random_full | 10 | 3538.481527 | 3543.015348 | 3454.642943 | 0.017319 | vehicle_type_swap | regret3_insert_repair | 0.200000 |
| eval_train | alpha_ucb_env | 9 | 5680.789650 | 5758.276002 | 3573.719578 | 0.445437 | route_segment_removal | greedy_insert_repair |  |
| eval_train | ppo_full | 9 | 6055.491550 | 5900.199891 | 4467.097104 | 0.666667 | vehicle_type_swap | greedy_insert_repair | 0.166667 |
| eval_train | random_full | 9 | 5365.972939 | 5412.281684 | 3528.765009 | 0.057417 | random_customer_removal | regret3_insert_repair | 0.300000 |
