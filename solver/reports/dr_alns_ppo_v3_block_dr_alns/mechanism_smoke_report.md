# V3 Block DR-ALNS Mechanism Smoke

## Verdict

`PASS_MECHANISM_SMOKE`.

This is only a wiring and integrity check. It does not prove that PPO learns or that V3 beats AlphaUCB/random_full.

## What changed

V3 adds a block-level DR-ALNS controller. One RL action controls a block of winner-kernel ALNS moves instead of one candidate move. This follows the Reijnen DR-ALNS pattern more closely: the neural policy configures destroy/repair, destruction level, acceptance threshold, and exploration pressure while the existing ALNS kernel performs the search.

## Smoke command

```bash
export SETP_WORKER_PYTHON=/opt/anaconda3/bin/python3.13
export PYTHONHASHSEED=0
PYTHONPATH=solver/rl:solver/src:models/src \
  solver/rl/.venv/bin/python -m dr_alns_ppo.evaluate_policy \
  --manifest solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json \
  --algorithms random_block,alpha_ucb_block,official_winner_kernel \
  --split formal_eval \
  --bundle-filter E-UK100_01 \
  --eval-budget 256 \
  --seeds 1,2 \
  --jobs 3 \
  --block-size 64 \
  --official-max-runtime-seconds 120 \
  --output-dir solver/reports/dr_alns_ppo_v3_block_dr_alns/mechanism_smoke
```

## Result

| algorithm | seed | best_obj | actual_evals | violation_count | worker |
|---|---:|---:|---:|---:|---|
| alpha_ucb_block | 1 | 5267.330004 | 256 | 0 | /opt/anaconda3/bin/python3.13, numpy 2.3.5 |
| official_winner_kernel | 1 | 5323.350284 | 256 | 0 | /opt/anaconda3/bin/python3.13, numpy 2.3.5 |
| random_block | 1 | 5167.719786 | 256 | 0 | /opt/anaconda3/bin/python3.13, numpy 2.3.5 |
| alpha_ucb_block | 2 | 5165.929678 | 256 | 0 | /opt/anaconda3/bin/python3.13, numpy 2.3.5 |
| official_winner_kernel | 2 | 5106.795778 | 256 | 0 | /opt/anaconda3/bin/python3.13, numpy 2.3.5 |
| random_block | 2 | 5024.498646 | 256 | 0 | /opt/anaconda3/bin/python3.13, numpy 2.3.5 |

## Integrity notes

All 6 rows reached the requested `eval_budget=256`, all 6 rows had `violation_count=0`, and all rows used the audited system worker environment. The short budget is intentionally not used for any performance claim.

Next valid step is a full V3 gate: `eval_budget=16000`, seeds 1-10, `official_winner_kernel/random_full/alpha_ucb_env/random_block/alpha_ucb_block`, then only if that gate passes, train `ppo_block`.
