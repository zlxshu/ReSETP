# Next Action

problem_symptom -> 16000 hard-subset A7 residual losses vs LNS
evidence -> decision `ROUTE_PACKING_REACHABILITY_SUPPORTED` in decision.json
minimal_remedy -> implement A13 LNS policy parity kernel; do not implement A14 until A13 parity passes
pass_gate -> reachability_fraction >= 0.60 with feasible decoded solutions and no material total-cost blowup
fail_gate -> preflight issue, no losing rows, reachability_fraction < 0.60, protected diff, infeasible-only decoded candidates
