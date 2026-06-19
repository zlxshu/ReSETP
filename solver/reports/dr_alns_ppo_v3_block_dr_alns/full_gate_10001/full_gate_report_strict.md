# V3 Block DR-ALNS Full Gate: 100-01

## Verdict
PASS for a small block-PPO pilot. This is an integrity pass, not proof that PPO will win.

One original row, `official_winner_kernel seed10`, hit the 900-second runtime cap at 15,827 evals. I reran only that row with a 1,800-second cap; it completed 16,000 evals with the same objective. `comparison_strict.csv` is the strict table used below.

Strict rows: 50/50. All rows `actual_evals=16000`: True. Zero violations: True. Worker: `/opt/anaconda3/bin/python3.13`, numpy `2.3.5`.

## Cost Summary
| algorithm | n | mean £ | median £ | best £ | std £ | delta vs official |
|---|---:|---:|---:|---:|---:|---:|
| random_full | 10 | 4781.121851 | 4788.890407 | 4739.860025 | 24.509629 | -97.209945 |
| random_block | 10 | 4789.365363 | 4783.328549 | 4732.715110 | 34.365484 | -88.966433 |
| alpha_ucb_env | 10 | 4878.331796 | 4848.619848 | 4779.053444 | 95.279550 | 0.000000 |
| official_winner_kernel | 10 | 4878.331796 | 4848.619848 | 4779.053444 | 95.279550 | 0.000000 |
| alpha_ucb_block | 10 | 4905.204016 | 4892.718678 | 4837.032377 | 50.249433 | 26.872220 |

## Plain-English Read
The system-worker ground truth is intact: `official_winner_kernel` reproduces the known system anchor exactly, and `alpha_ucb_env` matches it seed by seed. The block layer is not broken because `random_block` is competitive and beats the official mean here. But this gate also says something uncomfortable: `random_full` and `random_block` are extremely strong baselines. PPO is only meaningful if it can beat or at least approach those, not merely beat SA.

## Next Step
Run only a small block-PPO pilot next. Do not launch long training yet. If PPO cannot beat or approach `random_block` / `random_full`, stop scaling compute and redesign the learning target.
