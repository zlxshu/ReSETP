# Next Action

problem_symptom -> A3 backend alignment did not pass the corrected main LOCAL_SEARCH direction-support gate
evidence -> see decision.json and a3_vs_a0_pair_comparison.csv
minimal_remedy -> stop backend tuning and split q-size, scheduler, and acceptance as separate one-variable probes
pass_gate -> a later single-variable probe passes without protected/under-eval/worker failures
fail_gate -> the same unsupported backend pattern repeats or UNKNOWN dominates trace fields

Boundary: no Tier1/Tier2/Tier3, no LNS weakening, no RELAXED_ROUTE_COMPRESSION tuning, no oracle/ejection-chain/cross-exchange.