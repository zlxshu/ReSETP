# B2 Pilot08 Curriculum Training Report

Scope: training only. No baseline evaluation and no DR-vs-baseline performance verdict is made here.

## Run Summary
- Output directory: `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final`
- Final model: `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\async_block_ppo_model.pt`
- Completed episodes: 8422
- Valid steps total: 160018
- Total PPO updates: 350
- Final curriculum phase: carbon
- Device: `cuda`
- Train bundles in config: 12
- Shared baseline enabled: True

## Curriculum Phases
- route: 105 episodes
- energy: 105 episodes
- carbon: 8212 episodes
- Transitions:
  - route -> energy at episodes=100, valid_steps=1900
  - energy -> carbon at episodes=205, valid_steps=3895

## Throughput And Memory
- Final throughput: 1131.93 episodes/hour
- Final busy ratio: 0.9892
- Worker failures: 0
- Peak system memory used: 11098.3 MB
- Minimum system memory available: 5137.7 MB

## Entropy
- First / mid / final / min entropy: 7.1108 / 6.4105 / 5.9044 / 5.8880
- Possible near-zero collapse: False

## Shared Baseline
- Shared baseline groups min / median / final: 9 / 12.0 / 12
- Shared baseline skipped groups max / final: 3 / 0

## Checkpoints
- Checkpoint count: 35
- Checkpoint updates: [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320, 330, 340, 350]
- Checkpoint paths:
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0010.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0020.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0030.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0040.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0050.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0060.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0070.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0080.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0090.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0100.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0110.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0120.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0130.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0140.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0150.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0160.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0170.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0180.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0190.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0200.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0210.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0220.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0230.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0240.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0250.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0260.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0270.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0280.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0290.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0300.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0310.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0320.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0330.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0340.pt`
  - `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot08\train_final\checkpoints\async_block_ppo_update_0350.pt`

## Gates
- train_bundles_12: True
- device_cuda: True
- shared_baseline_enabled: True
- worker_py313: True
- numpy_2_3_5: True
- zero_violations: True
- finite_reward_objective_fields: True
- worker_failures_zero: True
- worker_python_executable values: ['C:\\Users\\zlxshu\\.venvs\\resetp-solver-py313\\Scripts\\python.exe']
- worker_numpy_version values: ['2.3.5']
- finite columns checked: ['reward_sum', 'best_obj']

## Notes
- Reports, logs, model, and checkpoints remain under ignored `solver/reports/`; nothing was staged or pushed in B2.
