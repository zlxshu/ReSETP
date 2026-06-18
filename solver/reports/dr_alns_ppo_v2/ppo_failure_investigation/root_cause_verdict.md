# PPO Failure Root-Cause Verdict

## bucketed phases reset before 16000-eval episodes terminate

- status: `confirmed`
- evidence: phase_timesteps=3072 < eval_budget=16000 and monitor has zero episode rows; tiny probe restores monitor rows when eval_budget <= phase_timesteps

## reward signal is sparse and lacks terminal credit in the observed training horizon

- status: `partially_supported`
- evidence: max_nonzero_reward_rate=0.578125; max_terminal_count=0

## policy collapse is only a deterministic-evaluation artifact

- status: `rejected`
- evidence: collapsed_actions=True; max_policy_top_prob=0.997962; deterministic_mean=6085.923811; stochastic_mean=5391.396590; alpha_ucb_mean=4878.331796; random_full_mean=4781.121851

## random_full is a strong random policy over winner-kernel operators, not a weak random solution generator

- status: `confirmed`
- evidence: random_full samples destroy/repair/q choices inside the restored winner action space and beats ppo_full in existing comparison CSVs

## Conclusion

The confirmed hard root cause is bucketed phase fragmentation: training resets environments before 16000-eval episodes terminate, so monitor/evaluation-credit episode endings are absent. Reward/terminal-credit observability is partially supported rather than fully proven, because short traces still contain nonzero immediate rewards but no terminal rewards. The saved PPO policy is genuinely collapsed, not merely a deterministic-eval display issue.

No fix is proposed here; next task should repair episode continuity/reward observability before any longer PPO training.
