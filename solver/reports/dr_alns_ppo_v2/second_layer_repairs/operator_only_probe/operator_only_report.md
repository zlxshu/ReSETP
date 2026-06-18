# Operator-Only PPO Repair Probe

## Verdict

- verdict: `FAILED_OPERATOR_ONLY`
- train episode_count: `9`
- env episode_count: `9`

## Cost Summary

| split | algorithm | rows | mean | median | best | std | violations |
|---|---|---:|---:|---:|---:|---:|---:|
| eval_10001 | alpha_ucb_env | 10 | 4878.332 | 4848.620 | 4779.053 | 90.390 | 0 |
| eval_10001 | ppo_operator_only | 10 | 5457.406 | 5438.790 | 5221.149 | 125.493 | 0 |
| eval_10001 | random_full | 10 | 4781.122 | 4788.890 | 4739.860 | 23.252 | 0 |
| eval_held_out | alpha_ucb_env | 10 | 3902.510 | 3951.963 | 3471.165 | 147.532 | 0 |
| eval_held_out | ppo_operator_only | 10 | 4225.422 | 4231.410 | 4084.521 | 70.060 | 0 |
| eval_held_out | random_full | 10 | 3538.482 | 3543.015 | 3454.643 | 32.909 | 0 |

## Plain English

Operator-only 没有救起 PPO。当前 per-step PPO 结构可能更深层不适合，需要转 block-level 或 imitation。

100-01: PPO vs Alpha gap `11.87%`, PPO vs random gap `14.14%`.
held-out: PPO vs Alpha gap `8.27%`, PPO vs random gap `19.41%`.
