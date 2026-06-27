# Pilot17 All-Scale DR-ALNS Evaluation

Status: `ACCEPTABLE_PASS`.
Reason: DR was non-worse across scales and positive on the main large scales, but did not reach +10% average.

Budget: eval_budget `20`, block_size `4`.
Best model: `final` update `375`.

This is x86 same-machine, same-budget relative evaluation only. It is not an M1 absolute-number comparison.

Only 15 generated all-scale three-shift bundles are present locally. Checkpoint selection uses the *-03 subset; formal comparison reports all 15 bundles but is not an independent held-out benchmark.

## Scale Gate

| scale | strongest baseline | mean relative % vs strongest | min bundle % | wins/n |
| --- | --- | ---: | ---: | ---: |
| 50 | alpha_ucb_block | 0.119 | 0.000 | 5/15 |
| 75 | alpha_ucb_block | 0.383 | 0.000 | 5/15 |
| 100 | alpha_ucb_block | 1.006 | 0.000 | 5/15 |
| 150 | alpha_ucb_block | 0.989 | 0.000 | 5/15 |
| 200 | alpha_ucb_block | 0.358 | 0.000 | 10/15 |

## Underbudget

PPO rows that stopped before the full budget: `120`. If this is nonzero, any positive result is caveated because the learned stop head changed budget use.

## Baselines

Formal comparison includes `alpha_ucb_block`, tuned `alpha_ucb_meta_tuned`, `random_block`, `scikit-opt-SA`, and `official_winner_kernel`.
