# Metaheuristic Baselines Formal Status

One-line conclusion: HALT. No ALNS / fair-SA vs 8-baseline win, loss, or tie claim is valid from this run, because the formal gate did not produce full-budget comparable baseline rows and the runner-side winner rows do not match the 100-01 anchor values.

## Current Evidence

- Environment: `/opt/anaconda3/bin/python3.13`, numpy `2.3.5`.
- Implementation commits: `16941ae7` baseline decode/cache speedup, `7de2c847` profile/convergence runner, `520890f4` runtime fallback completion support.
- Protected semantics: no diff in `solver/src/setp_solver/cost.py`, `solver/src/setp_solver/check.py`, `solver/src/setp_solver/search/evaluation.py`, `solver/src/setp_solver/search/winner_operators.py`, or `solver/src/setp_solver/search/candidates.py` at the time of this report.
- Unit test command passed: `PYTHONPATH=solver/src /opt/anaconda3/bin/python3.13 -m unittest solver.tests.test_metaheuristic_baselines`.

## Phase 0 Profile

Profile output is in `baselines/profile_report.md`, `baselines/profile_summary.csv`, and `baselines/profile_timings.csv`. On the 100-eval diagnostic gate, the optimized baselines looked fast enough on `100-01-24h`: ACO `149.542` eval/s, GWO `26.154`, IWD `102.692`, VNS `41.453`, and winner-kernel ALNS `21.045`.

That profile was only diagnostic. The formal 16000-eval run below showed that the short profile underestimates the cost of long-run budget-out repair/sort work.

## Formal 900s Run

Formal output directory: `baselines/formal_20260621_10001_lmain_10seed`.

The run wrote complete raw artifacts, but its manifest status is `HALT_BASELINE_INCOMPARABLE`. It produced 200 raw rows: 130 `OK` and 70 `HALT_RUNTIME_UNDER_EVAL`. All recorded rows had zero violations, but 70 rows failed the strict `evaluations == 16000` gate.

Under-budget rows by instance and algorithm:

| instance | algorithm | runs | min evals | max evals | mean evals |
|---|---:|---:|---:|---:|---:|
| 100-01-24h | GA | 10 | 9229 | 9229 | 9229.0 |
| 100-01-24h | GWO | 10 | 11086 | 11859 | 11624.9 |
| L-main | GA | 10 | 9229 | 9229 | 9229.0 |
| L-main | GA-VNS | 10 | 7726 | 8007 | 7848.5 |
| L-main | GWO | 10 | 2162 | 2296 | 2207.5 |
| L-main | LNS | 10 | 9184 | 9752 | 9499.9 |
| L-main | VNS | 10 | 7138 | 7577 | 7398.0 |

Because those rows are under-budget, `comparison_table.csv`, `wilcoxon.csv`, `verdicts.csv`, and `convergence_curves.csv` inside that directory are HALT artifacts only, not publishable formal comparisons.

## 3600s Fallback Attempt

Fallback output directory: `baselines/formal_20260621_10001_lmain_10seed_fallback3600`.

After adding `complete-fallback`, I started a 3600s fallback completion run using the 900s directory as input. The first four fallback worker processes were still CPU-bound at `01:04:46`, already beyond the 3600s per-run cap, with no formal CSVs written. I terminated the process tree rather than letting 70 fallback tasks run unbounded. Evidence is recorded in `baselines/formal_20260621_10001_lmain_10seed_fallback3600/HALT_FALLBACK_OVERRUN.md`.

The overrun stack sample showed Python `sorted/list_sort` hotspots, consistent with the remaining budget-out insertion/repair enumeration bottleneck. This means the current baseline implementation is still not at the required per-eval cost level for formal comparison.

## Winner Anchor

The 900s formal runner's `100-01-24h` winner rows do not match the user-provided anchor: observed winner mean `4844.796180674237`, seed2 `4731.514705663005`, zero violations. The required anchor is mean `4878.33`, seed2 `4779.05`, zero violations.

I did not modify winner code or shared `candidates.py` / evaluation semantics, so no winner rollback was triggered by code edits. Still, this runner output is not anchor-comparable and must not be used for a formal ALNS-vs-baseline claim.

## Do Not Use

Do not use root-level `baselines/comparison_table.csv`, `baselines/raw_runs.csv`, `baselines/wilcoxon.csv`, or `baselines/verdicts.csv` as current formal outputs. They predate this HALT run. The current run's authoritative status is this report plus the timestamped HALT directories above.

## Required Next Step

Before any formal table can be published, the remaining budget-out repair/sort work must be removed or bounded inside the baseline-only layer, and the runner must enforce a hard per-task timeout so a single repair pass cannot overrun the 3600s cap. After that, rerun the winner anchor and the 16000-eval formal gate from a clean timestamped directory.
