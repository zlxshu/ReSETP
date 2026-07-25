# HGS-ILS-XD G0 complementarity preflight

Verdict: `STOP_HGS_ILS_XD_G0_NO_FEASIBLE_COMPLEMENTARITY`

Selected workers: 6

This gate tests only whether independent ILS creates full-model-feasible customer orders outside the sealed v7 HGS-family route pool and adds value after an HGS handoff. It is not a performance, BKS, SOTA, paper, or E3 result.

## Gate counts

- exact-feasible tasks: 2/6
- cold-start feasible instances: 1/3
- instances with a route outside the sealed reference pool: 2/3
- warm-start instances with changed customer adjacency: 1/3
- warm-start instances strictly improved by ILS: 0/3
- instances where warm ILS beats cold ILS: 0/3

No parameter, instance, seed, completion, scorer, or stop rule was changed after results.
