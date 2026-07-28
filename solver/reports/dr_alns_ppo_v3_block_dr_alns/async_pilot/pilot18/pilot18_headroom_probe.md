# Pilot18 DR-ALNS Headroom Probe

Status: `VERDICT_NO_HEADROOM`.
Reason: All scales are below the pre-registered 3% headroom threshold.

Budget B: `20`; block_size: `4`.
Extended budgets: `[20, 80, 320]`; seeds: `[1, 2, 3]`.
Worker: `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`; NumPy: `2.3.5`.
DR action_nvec: `(7, 4, 5, 4, 4, 4, 3)`.

This is x86 same-machine relative evidence only. Pilot18 does not train PPO and does not change reward, cost, feasibility, evaluation, or winner semantics.

## Verdict Rules

Pre-registered rules: `<3%` headroom is `VERDICT_NO_HEADROOM`; baseline late gain after DR early stop is `VERDICT_DR_INTERFACE_GAP`; `>10%` is `VERDICT_ROOM_EXISTS`; otherwise `VERDICT_MODEST_ROOM`.

## Scale Summary

| scale | bundle | mean headroom % | late gain after DR stop % | DR eval fraction | capped seeds | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 50 | e2-threeshift-50c-03 | 0.000 | 0.000 | 0.400 | 0 | `VERDICT_NO_HEADROOM` |
| 75 | e2-threeshift-75c-03 | 0.000 | 0.000 | 0.400 | 0 | `VERDICT_NO_HEADROOM` |
| 100 | e2-threeshift-100c-03 | 0.000 | 0.000 | 0.400 | 0 | `VERDICT_NO_HEADROOM` |
| 150 | e2-threeshift-150c-03 | 0.000 | 0.000 | 0.400 | 0 | `VERDICT_NO_HEADROOM` |
| 200 | e2-threeshift-200c-03 | 0.000 | 0.000 | 0.400 | 0 | `VERDICT_NO_HEADROOM` |

## Integrity

Integrity ok: `True`; run rows: `90`; wall-clock capped rows: `0`.
