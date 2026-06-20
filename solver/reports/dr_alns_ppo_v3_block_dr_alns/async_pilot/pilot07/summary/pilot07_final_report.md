# Pilot07 x86 Reduced-Budget DR Trend Pilot

Status: `WEAK`.

This is a reduced-budget, single-training-bundle x86 trend pilot. All costs were generated on the same Windows x86 py313 worker environment and are reported only as within-machine relative percentages. No M1 absolute objective values are used or compared.

## Calibration

- Selected configuration: `eval_budget=1500`, `block_size=64`, `num_actors=6`.
- Calibration evidence: `45.266 episodes/hour`, projected `135.8 episodes` in 3 hours, max system memory used `11612.5 MB`.
- Rejected configurations: `1500/block32/8` exceeded the 12 GB memory safety line; `3000/block64/6` projected only `75.3 episodes` in 3 hours.

## Training

- Command family: `dr_alns_ppo.train_async_block_ppo train`.
- Output: `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot07/train_final/`.
- Completed `136` episodes and `3264` valid block steps in `7462.3` seconds.
- Curriculum transitions: route to energy at episode `33`; energy to carbon at episode `71`; final phase `carbon`.
- Phase counts: route `38`, energy `38`, carbon `60`.
- Gate: zero violations, finite rewards/objectives, worker path `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`, worker NumPy `2.3.5`, device `cuda`, shared baseline enabled.
- Training resource evidence: final throughput `65.614 episodes/hour`, peak system memory used `11380.0 MB`, minimum available memory `4856.1 MB`.
- Checkpoints: updates `0002`, `0004`, `0006`, `0008`, `0010`; trend evaluation used `0002`, `0006`, `0010`.

## Evaluation

Main DR vs AlphaUCB(block) used seeds `1,2,3,4,5`. Secondary algorithms and SA used seeds `1,2,3` because the full evaluation exceeded the 2-hour planning threshold. Every reported row passed the py313 worker, NumPy 2.3.5, eval-budget, zero-violation, and finite-objective gates.

Paired relative percentage uses `(baseline - ppo_block) / baseline * 100`; positive means DR is better.

| Bundle | Baseline | Paired n | Mean relative % | Std relative % |
|---|---:|---:|---:|---:|
| 100_02 train | alpha_ucb_block | 5 | -4.7740 | 8.5447 |
| 100_03 held_out | alpha_ucb_block | 5 | -6.0567 | 5.8744 |
| 100_01 formal | alpha_ucb_block | 5 | 1.6338 | 1.6869 |
| 100_02 train | random_block | 3 | -3.0509 | 8.4076 |
| 100_03 held_out | random_block | 3 | -6.1876 | 6.4195 |
| 100_01 formal | random_block | 3 | 3.6364 | 0.8883 |
| 100_02 train | scikit-opt-SA | 3 | 16.9028 | 4.2239 |
| 100_03 held_out | scikit-opt-SA | 3 | 10.7503 | 6.2096 |
| 100_01 formal | scikit-opt-SA | 3 | 22.5832 | 2.0605 |

Checkpoint trend versus AlphaUCB(block) did not support a PROMISING override. On 100_02 it moved from `0.4453%` at update 0002 to `1.3683%` at update 0006 and then down to `-1.4416%` at update 0010. On 100_03 it moved from `-0.7258%` to `0.3034%` and then down to `-4.7403%`.

## Verdict

`WEAK`: the pilot was valid and DR beat SA under the reduced-budget x86 worker口径, but it did not reliably match AlphaUCB(block). It was better on the 100_01 formal check, but worse on the training bundle 100_02 and held-out 100_03, and it did not consistently beat random_block. This is not enough to justify treating the current reduced-budget DR policy as a stronger controller than AlphaUCB.

Recommended interpretation: keep DR-ALNS as a learnable/future-work lane unless a later longer or redesigned reduced-cost training run changes the trend. The paper-critical algorithm line should continue to rely on the ALNS winner-kernel/mechanism path.
