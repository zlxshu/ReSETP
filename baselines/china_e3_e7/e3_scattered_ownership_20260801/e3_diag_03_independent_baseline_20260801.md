# E3-DIAG-03 基准对象与误报终止复核

- interpreter: `/Volumes/移动硬盘（512G）/ReSETP/build/python_envs/pyvrp-hgs-0.12.2/bin/python`
- executed_at_utc: `2026-07-31T22:34:38.931741+00:00`
- seed: `1`; budget: `100 iter/view`, archive: `8`; mapping/input caps/targets unchanged.

## Ruling after diagnosis

`locked_combined` and `joint` both completed normally for seed 1, each with
32 complete candidate evaluations and a legal full-model assessment. The first
singleton attempt stopped with exit code 1 before optimisation: its reduced
sub-bundle retained other depot nodes while its finite-fleet map retained only
Dongguan, so `build_pyvrp_problem` raised `ValueError: China81 finite fleet has
no depot 'D_foshan'`. This is an adapter construction failure, not native
termination.

The sealed v1 rows are also internally matched: every seed has 32 complete
candidate evaluations for both `HISTORICAL_STANDALONE` and `JOINT_OPTIMIZED`,
with fixed 100 iter/view and archive 8; all six rows are `PASS`. For subsequent
E3 prose, call the first arm `HISTORICAL_ASSIGNMENT_FIXED`: it fixes historical
scattered customer assignment while retaining the same global optimisation and
shared charging capacity. Do not replace it with singleton concatenation: the
separate singleton-concatenation check records two public-station capacity
conflicts, so it is not an E3 feasible baseline. No v2 scientific run was
completed or adopted.

| stage | exit code |
|---|---:|
| locked_combined | 0 |
| joint | 0 |
| independent:D_dongguan | 1 |

## locked_combined

start/end were recorded by parent; child exit code: `0`.

```text
STAGE_START locked_combined
STAGE_END locked_combined legal=True runtime={'complete_candidate_evaluations': 32, 'elapsed_seconds': 19.17589712503832}
STAGE_START locked_combined
/Volumes/移动硬盘（512G）/ReSETP/build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp/PenaltyManager.py:255: PenaltyBoundWarning: 
            A penalty parameter has reached its maximum value. This means PyVRP
            struggles to find a feasible solution for this instance, either
            because the instance has no feasible solution, or it is hard to
            find one - possibly due to large data scaling differences. Check
            the instance carefully to determine if a feasible solution exists.
            
  warn(msg, PenaltyBoundWarning)
STAGE_END locked_combined legal=True runtime={'complete_candidate_evaluations': 32, 'elapsed_seconds': 19.17589712503832}
```

## joint

start/end were recorded by parent; child exit code: `0`.

```text
STAGE_START joint
STAGE_END joint legal=True runtime={'complete_candidate_evaluations': 32, 'elapsed_seconds': 17.043474208097905}
STAGE_START joint
STAGE_END joint legal=True runtime={'complete_candidate_evaluations': 32, 'elapsed_seconds': 17.043474208097905}
```

## independent:D_dongguan

start/end were recorded by parent; child exit code: `1`.

```text
STAGE_START independent:D_dongguan
STAGE_START independent:D_dongguan
Traceback (most recent call last):
  File "/Volumes/移动硬盘（512G）/ReSETP/baselines/china_e3_e7/e3_scattered_ownership_20260801/diagnose_e3_independent_baseline.py", line 74, in <module>
    child(args.child)
    ~~~~~^^^^^^^^^^^^
  File "/Volumes/移动硬盘（512G）/ReSETP/baselines/china_e3_e7/e3_scattered_ownership_20260801/diagnose_e3_independent_baseline.py", line 35, in child
    solution, runtime = runner._solve(bundle, initial, seed=1, hard_lock=hard_lock)
                        ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Volumes/移动硬盘（512G）/ReSETP/baselines/china_e3_e7/e3_scattered_ownership_20260801/run_e3_independent_baseline.py", line 94, in _solve
    run = base.run_hgs_route_pool_recombination(
        bundle, initial, seed=seed, hgs_seconds_per_view=None,
    ...<4 lines>...
        exact_checkpoint_interval_iterations=None,
    )
  File "/Volumes/移动硬盘（512G）/ReSETP/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py", line 143, in run_hgs_route_pool_recombination
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode=mode,
        hard_home_depot_lock=hard_home_depot_lock,
    )
  File "/Volumes/移动硬盘（512G）/ReSETP/baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py", line 251, in build_pyvrp_problem
    raise ValueError(
        f"China81 finite fleet has no depot {depot.node_id!r}"
    )
ValueError: China81 finite fleet has no depot 'D_foshan'
```
