# Pilot19 Route Pool + Set-Partitioning Headroom Probe

Status: `NO_ROOM_SP`.
Scales: `[50, 75, 100, 150, 200]`; seeds: `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]`.
Budget: eval_budget=`20`, block_size=`4`.
Worker: `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`; NumPy: `2.3.5`.

This is x86 same-machine relative evidence only. Pilot19 does not train PPO and does not change reward, cost, feasibility, evaluation, or winner semantics.

## Verdict Rules

`headroom_sp% >= 10` => `ROOM_CONFIRMED`; `2 <= headroom_sp% < 10` => `MODEST_ROOM`; all `< 2` => `NO_ROOM_SP`.

## Scale Summary

| scale | bundle | best single | SP cost | headroom % | pool | selected | MILP | feasible | verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| 50 | e2-threeshift-50c-03 | 1770.782 | 1770.782 | 0.000 | 58 | 8 | `0` | 1 | `NO_ROOM_SP` |
| 75 | e2-threeshift-75c-03 | 2478.310 | 2478.310 | 0.000 | 85 | 10 | `0` | 1 | `NO_ROOM_SP` |
| 100 | e2-threeshift-100c-03 | 3335.937 | 3335.937 | 0.000 | 114 | 14 | `0` | 1 | `NO_ROOM_SP` |
| 150 | e2-threeshift-150c-03 | 5017.380 | 5017.380 | 0.000 | 169 | 19 | `0` | 1 | `NO_ROOM_SP` |
| 200 | e2-threeshift-200c-03 | 6568.755 | 6568.755 | 0.000 | 228 | 28 | `0` | 1 | `NO_ROOM_SP` |
