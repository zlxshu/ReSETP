# Pilot15 Smoke Calibration

Status: `PASS_PILOT15_SMOKE_CALIBRATION`

Interpretation: this is only a short-run interface gate. It means the full-scale three-shift PPO interface is ready for a Pilot16 long run; it is not a DR-vs-baseline performance success.

Episodes: `68`; block steps: `324`; updates: `8`.
Bundles touched: `15/15`.
Candidate nondefault rate: `0.722`.
Search-control non-continue actions: `168`.
Throughput: `849.12` episodes/hour; projected 8h episodes: `6793.0`.
Memory: peak used `13912.2` MB; min available `2323.8` MB.

## Checks
- train_bundle_count_15: `True`
- all_15_bundles_touched: `True`
- route_to_energy: `True`
- energy_to_carbon: `True`
- zero_violations: `True`
- worker_py313: `True`
- numpy_235: `True`
- finite_rewards_objectives: `True`
- cuda: `True`
- candidate_nondefault_rate_ge_50pct: `True`
- search_control_sampled: `True`
- overnight_projection_ge_1000_episodes: `True`

## Phase Transitions

- 6 episodes: route -> energy
- 15 episodes: energy -> carbon
