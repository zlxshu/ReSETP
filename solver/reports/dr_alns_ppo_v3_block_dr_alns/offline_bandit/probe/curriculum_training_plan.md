# Curriculum Training Plan

Code commit for this offline-probe design: `d137b9b597d9204dc25a5b2784a223a6320ef1fd`.

This is an implementation plan only. It must not change `solver/src/setp_solver/cost.py`, `solver/src/setp_solver/check.py`, or `solver/src/setp_solver/search/evaluation.py`; final evaluation always uses the true solver objective and feasibility checks.

## Source Ideas

Daysalilar et al. 2026, ["A curriculum-based deep RL framework for the EVRP"](https://arxiv.org/abs/2601.15038), motivates a staged constraint curriculum: learn route topology first, then energy, then time-window/full EV routing. Wan et al. 2025, ["Deep Reinforcement Learning for Solving the Fleet Size and Mix Vehicle Routing Problem"](https://arxiv.org/abs/2512.24251), motivates reducing instance-level return variance with same-instance shared baselines. Narayanan et al. 2022, ["A Reinforcement Learning Approach for Electric Vehicle Routing Problem with Vehicle-to-Grid Supply"](https://arxiv.org/abs/2204.05545), motivates masking infeasible or degenerate actions before selection.

## Reward Curriculum

Add a phase argument in `solver/rl/dr_alns_ppo/block_env.py`, store it as `self.curriculum_phase`, and branch only inside `_reward()`. Phase A should keep route-count and distance/current-improvement terms, suppressing EV, carbon, fairness, and dynamic terms. Phase B should add EV charging efficiency signals from `charge_ratio`, requested q/threshold, and block improvement rates. Phase C should add carbon and fairness-shaped terms from worker response metrics when present, while still treating `violation_count` as a hard negative signal. Phase D should add dynamic-demand or rolling-replan terms only when the worker response exposes those fields.

The CLI in `solver/rl/dr_alns_ppo/train_async_block_ppo.py` should accept `--curriculum-schedule route,energy,carbon,dynamic`, `--phase-min-episodes`, and phase-specific `--learning-rate`, `--entropy-coef`, `--clip-range`, and value/advantage clipping settings. Stage switching should require both a minimum episode count and stable feasibility: zero violations plus non-degrading median best objective over the most recent completed same-bundle rollout window.

## Action Masking

Add an optional `action_mask` to the `info` dictionary returned by the block environment step path, shaped as one boolean vector per MultiDiscrete head. The mask should be computed from current response fields and observation-derived facts, not by running extra solver evaluations. Mask `vehicle_type_swap` when `ev_share` is effectively 0 or 1 and the solution is homogeneous. Mask route-removal style choices when `route_gap <= 0` or recent `route_delta`/best improvement data says route elimination cannot reduce routes. Mask oversized q values in late budget or high rejection/stagnation states when they repeatedly yield no block improvement.

Update `solver/rl/dr_alns_ppo/async_block_policy.py` so `BlockActorCritic.forward()` can accept masks and set invalid logits to a large negative value before constructing `Categorical` distributions. Update `act()` and `evaluate_actions()` to consume masks during rollout and PPO update, and log mask hit rates in `train_async_block_ppo.py` to detect accidental always-on masks.

## Shared Baseline

In `solver/rl/dr_alns_ppo/train_async_block_ppo.py`, collect rollout batches in same-bundle groups before calling `flatten_episodes()`. For each bundle group with N completed rollouts, compute the group mean return and subtract it from each episode return before advantage normalization. Keep the current critic value head, but make this shared baseline an additional variance-reduction step before the existing standardized advantage calculation.

Acceptance for the later GPU run is still external: after training, evaluate with the gold system-Python worker and true `cost.py` objective on the formal seed set. Curriculum reward is training shaping only, not a paper metric.
