# V3 Block DR-ALNS Full Gate: 100-01

## Verdict
HALT. Do not train PPO until the block gate is repaired.

Rows: 50/50. All rows used `actual_evals=16000`: False. Zero violations: True. Worker: `/opt/anaconda3/bin/python3.13`, numpy `2.3.5`.

## Summary
| algorithm | n | mean £ | median £ | best £ | std £ | delta vs official |
|---|---:|---:|---:|---:|---:|---:|
| random_full | 10 | 4781.121851 | 4788.890407 | 4739.860025 | 24.509629 | -97.209945 |
| random_block | 10 | 4789.365363 | 4783.328549 | 4732.715110 | 34.365484 | -88.966433 |
| alpha_ucb_env | 10 | 4878.331796 | 4848.619848 | 4779.053444 | 95.279550 | 0.000000 |
| official_winner_kernel | 10 | 4878.331796 | 4848.619848 | 4779.053444 | 95.279550 | 0.000000 |
| alpha_ucb_block | 10 | 4905.204016 | 4892.718678 | 4837.032377 | 50.249433 | 26.872220 |

## Plain-English Read
The solver ground truth is intact: `official_winner_kernel` reproduces the known system anchor exactly, and `alpha_ucb_env` matches it seed by seed. The block control layer is not obviously broken because `random_block` is competitive and even beats the official mean in this run. However, the strongest baseline is not weak random search: `random_full` and `random_block` are both very strong operator-space random baselines. The next PPO pilot is therefore allowed, but it must beat or approach these strong baselines to count as learning.

## Next Gate
Run a small block-PPO pilot only. Do not launch long training yet. If PPO cannot beat or approach `random_block` / `random_full`, stop and redesign the learning target rather than scaling compute.
