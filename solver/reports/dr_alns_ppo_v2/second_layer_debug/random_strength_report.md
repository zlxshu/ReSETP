# Random-Full Strength Decomposition

| split | algorithm | rows | mean | median | best | std | violations |
|---|---|---:|---:|---:|---:|---:|---:|
| formal_10001 | alpha_operator_random_q | 3 | 4866.232 | 4850.280 | 4788.918 | 70.547 | 0 |
| formal_10001 | alpha_operator_random_threshold | 3 | 5044.337 | 5082.149 | 4961.225 | 58.848 | 0 |
| formal_10001 | alpha_ucb_env | 3 | 4875.047 | 4791.037 | 4779.053 | 127.376 | 0 |
| formal_10001 | ppo_full | 3 | 6085.924 | 6085.924 | 6085.924 | 0.000 | 0 |
| formal_10001 | random_full | 3 | 4765.030 | 4767.645 | 4739.860 | 19.572 | 0 |
| formal_10001 | random_operator_only | 3 | 4856.842 | 4874.147 | 4801.647 | 39.923 | 0 |
| held_out | alpha_operator_random_q | 3 | 3696.267 | 3590.033 | 3554.884 | 175.678 | 0 |
| held_out | alpha_operator_random_threshold | 3 | 3717.272 | 3724.175 | 3579.104 | 110.103 | 0 |
| held_out | alpha_ucb_env | 3 | 3948.081 | 3948.955 | 3940.317 | 6.014 | 0 |
| held_out | ppo_full | 3 | 4222.785 | 4222.785 | 4222.785 | 0.000 | 0 |
| held_out | random_full | 3 | 3555.010 | 3551.146 | 3549.429 | 6.716 | 0 |
| held_out | random_operator_only | 3 | 3873.190 | 3881.261 | 3837.945 | 26.114 | 0 |

Interpretation: random_full is strong because it explores the winner-kernel action space, not because it is a weak random solution generator.
