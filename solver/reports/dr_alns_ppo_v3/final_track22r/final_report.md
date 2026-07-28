# Track22-R Final Report

Final verdict: `HALT_R0_STAGE2_WALL_UNSTABLE_WITHOUT_VERDICT`

## 人话结论

这次 Track22-R 没有形成 DR 正负判级。R1 worker 崩溃诊断和回归测试已经完成，但 R2 主判据的 R0 预算闸没有稳定通过：25c equal-steps oracle 连续调到 4000 步后，仍出现墙钟 <60s 的 `UNDERPOWERED` 判级行。按“连续 3 次自修失败停写诊断”，停止 R2/R3/R4，不把欠功率数据拿去判 `NO_DESTROY_LEVERAGE` 或训练/碳结论。

## R0 预算完整性

- Stage2 equal-steps oracle partial rows: 10.
- OK rows: 9.
- UNDERPOWERED verdict rows: 1.
- Underpowered row: `E-UK25_12__curric_d2_s3_seed2212_24h`, seed `1201`, `operator_select`, target steps `4000`, actual evals `4000`, wall `50.953s`, eval ratio `2.000`, wall ratio `0.849`.
- Stage3: not run because Stage2 did not produce a valid verdict.
- Stage4: not run because the run stopped at R0/Stage2.

## R1 worker 崩溃修复

- Regression result: `28 passed in 23.01s`.
- Test command: `pytest solver/rl/tests/test_track22r_worker_crash.py solver/rl/tests/test_worker_contract.py solver/rl/tests/test_learned_destroy_phaseA.py solver/rl/tests/test_final_track22r.py -q`.
- The original Track22 05:31 learned-destroy silent worker exit did not reproduce on the targeted 50c/q=0.4/20-customer/50-step path.
- Confirmed instrumentation bug: worker failures could leave stderr empty. Fix: `worker_client.py` now allocates per-process crash logs, enables `PYTHONFAULTHANDLER`, and reports stderr/crash-log tails; `worker.py` records uncaught request exceptions to stderr and the crash log.
- Verified worker: `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`, NumPy `2.3.5`.

## R2 破坏杠杆

- Main equal-steps oracle: stopped before verdict because R0 wall-clock floor was unstable on 25c.
- Attempt 1: 25c `2000` steps hit a runner cap bug on best-of-k: `EvalBudget target reached: 12010 >= 12010`.
- Attempt 2: 25c `3000` steps still produced `UNDERPOWERED` at E-UK25_11 seed1202 operator_select, wall `58.829s`.
- Attempt 3: 25c `4000` steps still produced `UNDERPOWERED` at E-UK25_12 seed1201 operator_select, wall `50.953s`.
- Partial completed clean rows are retained in `track22r_destroy_leverage_equal_steps_rows.csv`, but they are not a verdict sample and must not be summarized as leverage evidence.
- Equal-eval reference and Pilot21 anchor were not run because the main R0 gate failed first.

## R3 learned-destroy

Not run. This is intentional: R3 may only run after R2 produces `DESTROY_LEVERAGE_CLEAN` or `LEVERAGE_MARGINAL` from R0-valid equal-steps rows.

## R4 碳时刻

Not run in this stopped run. No default carbon ceiling or EV-heavy conclusion is reported because the run stopped at R0/Stage2 before the carbon stage.

## 与首跑被驳回版的差异

- 首跑把 80 eval / 2-5 秒 / 等 eval 口径的 `-1.405%` 当成无杠杆结论；Track22-R 没有重复这个错误，R0 不过就不判级。
- 首跑 Stage3 的静默崩溃被修成有 stderr/crash log 的可诊断路径，并加了 50c 大移除回归测试。
- 首跑 Stage4 的 naive 候选缺失和 `cv=0` EV-heavy 构造 bug 已在 runner 中加硬闸/修法，但本次没有跑到 R4。

## 总判级

- Overall: `HALT_R0_STAGE2_WALL_UNSTABLE_WITHOUT_VERDICT`.
- 一句话回答：现在不能说 DR-ALNS 配或不配当未来主算法；这次被 R0/Stage2 仪器预算闸挡住，不能拿欠功率数据做正负结论。

## 证据文件

- `r1_regression_test_result.json`
- `track22_preflight.json`
- `track22_bundle_manifest.json`
- `track22r_destroy_leverage_equal_steps_rows.csv`
- `track22_progress.log`
- `track22_final_report.json`
