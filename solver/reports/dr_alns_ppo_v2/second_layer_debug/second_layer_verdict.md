# Second-Layer PPO Verdict

- recommendation: `do_not_long_train_current_ppo`
- formal_10001_means: `{"ppo_full": 6085.923811179165, "random_full": 4765.0304160798305, "alpha_ucb_env": 4875.0470412240875}`

## Hypotheses

- `confirmed`: policy collapse is real. Evidence: max top action probability=0.999325; ppo formal mean=6085.923811
- `supported`: immediate reward can favor a globally weak fixed action. Evidence: ppo max accepted_rate=1.000000; ppo max improved_best_rate=0.010742; random formal mean=4765.030416
- `confirmed`: random_full is a strong operator-space baseline. Evidence: formal random_full mean=4765.030416; alpha_ucb_env mean=4875.047041
- `inconclusive`: observation aliasing limits conditional control. Evidence: max conflicting rounded-observation bucket rate=0.068510

## Next Repair Order

- operator_only_action_space
- reduced_q_threshold_action_space
- reward_shaping_after_reward_audit
- block_level_controller_if_small_repairs_fail
