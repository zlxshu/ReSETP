# ReMIX PR17A behavior gate

This prototype implements the pre-registered
`REMIX-BEHAVIOR-PR17A-001` diagnostic only.

It combines:

1. three tiny PyVRP 0.13.4 ILS islands;
2. multi-parent route exchange;
3. bounded multi-depot/time-window destroy and regret repair;
4. PyVRP's official local search;
5. an exact SciPy MILP route-pool recombination.

The code is not a paper configuration and must not be used to claim
performance. Run it with the repository-pinned PyVRP environment:

```bash
build/python_envs/pyvrp-0.13.4/bin/python \
  baselines/algorithm_prototypes/remix_pr17a_behavior_20260719/run_behavior_gate.py
```

All generated evidence remains under
`baselines/algorithm_foundation/remix_pr17a_behavior_gate_20260719/`.
