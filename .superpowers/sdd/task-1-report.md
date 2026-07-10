# Task 1 — dynamic truth gate final report

## Scope and provenance

- Worktree: `D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate`
- Branch: `codex/dynamic-truth-gate`
- Production code SHA under test: `9b4657ff15d6953f498e49a3a945f35bab84b50a`
- Existing test commits retained: `db5da1e9`, `17d97d8a`, and `fc606818`
- Interpreter: `C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe`
- Runtime: Python 3.12.13, pytest 9.1.1, numpy 2.5.1, scipy 1.18.0
- Import root: `PYTHONPATH=D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate\solver\src`
- Changed scope: `solver/tests/test_dynamic_truth_gate.py` and this report only. No file under `solver/src` changed.

## Gate design

The file contains exactly four `strict=True, raises=AssertionError` xfails. Each xfail covers one current production gap. Fixture, setup, rolling-stage structure, unexpected exceptions, and exact-event preconditions are ordinary assertions or `RuntimeError`s, so they cannot be swallowed as expected failures.

The inherited-clock example proves a real 250 m arc at 25 m/s takes 10 seconds from `P0`, while the inherited vehicle clock is 100 seconds. The xfail requires the checker to report arrival/service at 110 seconds and exactly 5 seconds of lateness.

The inherited-battery example proves the real energy function consumes exactly 2 kWh on the audited arc and the inherited battery is 1 kWh. The xfail requires the checker to report the resulting -1 kWh battery state.

## Charger occupancy: real rolling outputs only

The charger fixture calls the real `run_rolling_reoptimization` with a temporary on-disk bundle and no mocks or monkeypatches. In the current production path it reaches stages 0, 1, and 2. The test captures the previous-stage output only from `contexts[1].previous_plan` and the stage-1 output only from `contexts[2].previous_plan`.

Ordinary assertions require the real previous-stage output to contain exactly one EV charging action on the real `EV2#T1` route at F1 starting at 0 seconds for 30 minutes. They then require the real stage-1 output to contain exactly one EV charging action on the real `EV1#T1` route at F1 starting at 900 seconds for 10 minutes.

Review found that naively concatenating every route from both outputs also concatenated an unrelated stage-0 anchor route named `EV1#T1`. The complete checker then correctly returned `ROUTE_STRUCTURE @ EV1#T1` in addition to `STATION_CAPACITY @ F1@slot0`; filtering only station violations hid that defect. The corrected audit does not rename or mutate either real charging route. After the real route/action assertions pass, `_cross_stage_charging_ledger_for_audit` selects only the two actual charging routes and actions. The audit instance is reduced to exactly their two customers, `C_PAST` and `C_NEXT`, while retaining depots and stations. Ordinary assertions prove the audit instance and ledger both contain exactly those customers, preserve vehicle IDs `EV2#T1` and `EV1#T1`, and make the complete `check_solution` violation signature exactly one item: `STATION_CAPACITY @ F1@slot0`.

If production is fixed and rolling halts before a stage-1 output can be captured, the fixture accepts only an exact early halt: `HALT_E7_STAGE_CHECK`, `first_bad_stage == 1`, exactly one violation, type `STATION_CAPACITY`, location `F1@slot0`. Any other gate, stage, count, type, or location is an ordinary error.

The charger xfail itself requires that exact rolling halt. Current production instead completes stage 1 as feasible because the stage checker omits the earlier still-active station occupancy.

## Lifecycle: four explicit states and two independent runs

Cancellation and demand change use two separate calls to the real rolling runner and separate temporary bundles. Review found that the prior fixture caught any runner-level `ValueError` and could convert a matching string into accepted lifecycle evidence. That exception shortcut has been deleted. The fixture now attempts both independent runs, collecting exceptions only long enough to ensure one failure cannot prevent the other run from executing, and then raises an `ExceptionGroup`; no exception is returned or accepted as evidence.

Each real stage-0 output has these four deliberately distinct customers:

- `C_DONE`: present in the previous output and service starts at 0 seconds, so it is completed before the 100-second trigger.
- `C_LOCK`: present in the previous output and service starts at 150 seconds, so it is the near-term locked but not completed customer.
- `C_PLANNED_OPEN`: present in the previous output but service starts at 1000 seconds, so old-plan membership alone does not make it locked.
- `C_OPEN`: absent from the previous output, so it is completely unscheduled.

Ordinary assertions require each runner to return a normal report, contexts exactly `[0, 1]`, and no `gate`, `first_bad_stage`, or `violations` key. They require the previous output to contain exactly `C_DONE`, `C_LOCK`, and `C_PLANNED_OPEN`; require `served_customers == {C_DONE}`; and verify all four cancellation events or all four demand-change events are delivered in the real stage-1 context. They also require the completed customer to keep demand 10, while both open categories are really cancelled or receive demands 130 and 140. Any exception, halt, missing stage, missing event, or changed timing is therefore an ordinary failure outside xfail scope.

The lifecycle xfail covers only the missing locked-but-not-completed state. It requires `committed_customer_ids == {C_LOCK}` while `served_customers == {C_DONE}`, excludes both open categories from committed IDs, and requires `C_LOCK` to remain present with demand 20. Current production instead exposes `committed_customer_ids == {C_DONE}`; cancellation removes `C_LOCK`, and demand change rewrites it to 120.

## Fresh verification

Focused strict-xfail mode:

```powershell
Set-Location -LiteralPath 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate'
$env:PYTHONPATH = 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate\solver\src'
& 'C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe' -m pytest -q solver/tests/test_dynamic_truth_gate.py
```

Result: exit 0, `5 passed, 4 xfailed`.

Forced RED mode:

```powershell
& 'C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe' -m pytest -q solver/tests/test_dynamic_truth_gate.py --runxfail
```

Result: expected exit 1, `4 failed, 5 passed`. The failures are exactly inherited clock, inherited battery, cross-stage charger occupancy, and lifecycle lock-state truth.

Related checker coverage:

```powershell
& 'C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe' -m pytest -q solver/tests/test_check.py solver/tests/test_dynamic_truth_gate.py
```

Result: exit 0, `38 passed, 4 xfailed`.

`git diff --check` also exits 0.

## Remaining risk

The four production gaps are not fixed in this task; they remain deliberately visible as strict expected failures. This task closes the known false-pass routes in the tests. A future production fix must turn the relevant xfail into XPASS (and therefore fail under `strict=True`) before the marker is removed.
