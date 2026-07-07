# Next Action

problem_symptom -> 16000 hard subset residual route/fixed dispatch gap against LNS
evidence -> see decision.json, route_fixed_cost_decomposition_by_budget.csv, repack_trace.csv, and fleet_charge_trace.csv
minimal_remedy -> continue only the supported branch to 8000
pass_gate -> route/fixed gap improves with zero HALT rows
fail_gate -> under-eval, protected diff, infeasible row, worker failure, or route/fixed gate failure

Boundary: no LNS weakening, no selector/backend/q/acceptance tuning, no formal Tier claim.