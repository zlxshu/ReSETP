# Final Track21 Reclaim Report

Final status: `HALT_100C_STILL_STARVED`

Plain conclusion: the fleet-policy bug was fixed and the winner kernel was revived, but the paper-grade 100c comparison still cannot be claimed from this x86 run. The 25c/50c comparison is legal and significant, but the margin is real-small, not a 10% sweep.

## What Was Fixed

- The capped-fleet `SearchPolicy` leak was fixed in the winner-kernel and related production paths. `SearchPolicy` still keeps `UNBOUNDED_FLEET` as the explicit "no cap supplied" default.
- Protected semantic files were not changed: `cost.py`, `check.py`, and `search/evaluation.py`.
- Worker integrity held: runner `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`, Python 3.13.12, NumPy 2.3.5.

## Winner Revival Evidence

- 100-01 seed901 300-eval probe: fixed winner best `2596.7756` vs warm `4079.0301`, zero violations; same-budget SA stayed at warm.
- 100c 4000-eval diagnostic: fixed winner best `2509.1028` vs SA `3518.6016`, zero violations; winner advantage vs SA `28.690%`.
- Formal 100c seed901 row: winner best `2500.5183`, evals `16000/16000`, unique solutions `45`, best updates `44`, violations `0`.

This means the old Track19 "winner stuck at warm" result is superseded. The fixed method can move and can beat SA on the tested 100c seed.

## 25c/50c Fair Comparison

Completed legal rows: 25c has 10 seeds x 7 methods, 50c has 10 seeds x 7 methods. All six baselines are `HEALTHY` on 25c/50c.

Aggregate mean gain, pooled over 25c+50c:

- GA: `20.534%`
- VNS: `6.415%`
- SA: `16.557%`
- GWO: `7.311%`
- ACO: `6.440%`
- IWD: `5.515%`

One-sided paired Wilcoxon p-values, pooled over 25c+50c:

- GA: `9.5367e-07`
- VNS: `4.4225e-05`
- SA: `9.5367e-07`
- GWO: `9.5367e-07`
- ACO: `1.9073e-06`
- IWD: `4.7684e-06`

Verdict for 25c/50c: `MARGIN_REAL`. The method is better than every healthy baseline on this x86 table, and the paired tests are significant, but the minimum aggregate gain is only `5.515%` vs IWD. The "every baseline >=10%" claim is not supported.

## 100c Halt

100c was resumed after the earlier Track22 closeout, but the formal table stopped by the predeclared gate:

- Seed901 winner row is healthy: `16000/16000` evals, best `2500.5183`, warm `4079.0301`, unique `45`, updates `44`, violations `0`.
- Seed901 SA is healthy: best `3054.4503`, unique `139`, updates `138`, violations `0`.
- Seed901 GA/VNS/GWO/ACO/IWD are `VALID_BUT_WEAK`: they run full budget but return warm start, with no best update.
- Seed902 winner row is `INVALID_NOT_RUN`: `11430/16000` evals, eval ratio `0.714375`, best `2561.6270`, unique `71`, updates `70`, violations `0`.

Therefore the final Track21 status is `HALT_100C_STILL_STARVED`. It is a runtime/eval-budget halt, not a proof that the fixed winner is weak on 100c. No paper claim should be made from the incomplete 100c table.

## Historical Cleanup

- Track17/Track19 winner rows are superseded by `SUPERSEDED_BY_TRACK21_FLEET_FIX`.
- Pilot20-25 learned-destroy/DR negatives remain contaminated with the pre-fix worker path unless re-evaluated on the fixed worker. Track21 did not retrain DR.
- PSO remains transparently excluded from the healthy-baseline quantitative claim.

## Evidence Files

- `solver/reports/dr_alns_ppo_v3/final_track21/track21_policy_construction_audit.md`
- `solver/reports/dr_alns_ppo_v3/final_track21/track21_fix_report.md`
- `solver/reports/dr_alns_ppo_v3/final_track21/track21_winner_revival.md`
- `solver/reports/dr_alns_ppo_v3/final_track21/track21_100c_4000eval_revival.md`
- `solver/reports/dr_alns_ppo_v3/final_track21/track21_dr_contamination_report.md`
- `solver/reports/dr_alns_ppo_v3/final_track21_reclaim/track21_reclaimed_fair_comparison.csv`
- `solver/reports/dr_alns_ppo_v3/final_track21_reclaim/track21_progress.log`
