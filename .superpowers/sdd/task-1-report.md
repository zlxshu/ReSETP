# Task 1 — Dynamic truth tests and RED evidence

## Scope and provenance

- Worktree: `D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate`
- Branch: `codex/dynamic-truth-gate`
- Production code SHA under test: `9b4657ff15d6953f498e49a3a945f35bab84b50a`
- Interpreter: `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe` (`Python 3.13.12`, `pytest 9.1.1`)
- Import root: `PYTHONPATH=D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate\solver\src`
- Scope kept: tests and this report only. No file under `solver/src` was modified; no ALNS experiment was run; no scorer, checker, or rolling solver was mocked or monkeypatched.

## RED command

The four tests were first added without xfail markers. The following command exited 1 with `4 failed`:

```powershell
Set-Location -LiteralPath 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate'
$env:PYTHONPATH = 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate\solver\src'
& 'C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe' -m pytest -q solver/tests/test_dynamic_truth_gate.py --runxfail
```

## Four observed failures

### 1. Inherited clock is reset

Hand calculation: the vehicle is at `P0` at time 100 s. The new customer is 250 m away and speed is 25 m/s, so travel takes 10 s, arrival/service starts at 110 s, and due time 105 s implies exactly 5 s lateness.

Observed: `route_node_schedule` reported arrival `10.000 s`, and `check_solution(..., dynamic_context=...)` emitted no `TIME_WINDOW` violation. The failing assertion was `assert late` with the diagnostic `reset schedule observed arrival=10.000 s`.

Failure boundary: `DynamicVehicleState.current_time` is present in the real context but the dynamic checker schedules the route from the static node clock.

### 2. Inherited EV battery is reset

Hand calculation: the synthetic audited physics has zero drag, 1 N rolling resistance, distance 2000 m, and `alpha_e=3600`; therefore arc energy is `3600 * 1 * 2000 / 3,600,000 = 2 kWh`. With 1 kWh inherited, the post-arc battery is exactly `-1 kWh`.

Observed: the real `ev_arc_energy_kwh` returned `2.0 kWh`, but the checker emitted no `BATTERY` violation because the static initial battery was 80 kWh. The failing assertion was `assert depleted`.

Failure boundary: `DynamicVehicleState.remaining_battery_kwh` is not used as the EV ledger start.

### 3. Pre-boundary charger occupancy is lost

Hand calculation: EV1 charges at the one-charger station F1 from 0 to 1800 s. At the rolling boundary `t=600`, that use is active. EV2 is planned at F1 from 900 to 1500 s. Both occupy half-hour slot 0, so occupied vehicles are 2 while `C_s=1`, which is a hard conflict. C_PAST is at least 1000 s away on the reset schedule and 2800 s away when charging is included, so it is not completed at the boundary.

Observed: the real full-ledger `check_solution` detected `STATION_CAPACITY`; the real `_commit_executed_customers` returned an empty set; `_solution_for_committed_customers` carried `0` charging actions; and the stage-view checker emitted no station-capacity conflict. The failing assertion was `assert stage_conflicts`.

Failure boundary: cross-stage resource state is derived only from customer commit chunks, so a started charging use disappears while its downstream customer remains incomplete.

### 4. Committed cancellation is treated as open

Hand calculation: completed customers keep original demand/presence; open cancellation removes the customer and open demand change applies the new demand; committed-but-not-completed cancellation/demand change must preserve the frozen original or raise an explicit committed-state conflict.

Observed: completed cancel/change stayed at original values (`10`, `11`), open cancel removed its customer, open demand change became `311`, and committed demand remained frozen. But committed customer `C_COMMIT_CANCEL` was silently removed. The failing assertion was `assert event.customer_id in committed_lookup`.

Failure boundary: `_instance_after_events` treats a frozen-but-not-completed customer like open during cancellation; the later frozen-node override cannot re-add a node already removed.

## Strict expected-failure gate

Each test now has `@pytest.mark.xfail(strict=True, reason=...)`. The normal focused command exits 0 and reports exactly `4 xfailed`:

```powershell
Set-Location -LiteralPath 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate'
$env:PYTHONPATH = 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate\solver\src'
& 'C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe' -m pytest -q solver/tests/test_dynamic_truth_gate.py
```

Observed output: `xxxx [100%]` and `4 xfailed in 0.42s`.

Re-running the RED command with `--runxfail` after marking still exits 1 with the same four real failures (`4 failed in 0.45s`).

## Changed files

- `solver/tests/test_dynamic_truth_gate.py` — four real-object, real-function dynamic truth tests with strict xfail markers.
- `.superpowers/sdd/task-1-report.md` — this evidence report.

## Self-check

- [x] All four tests were observed failing before xfail markers were added.
- [x] Each RED failure is an assertion failure at the intended truth boundary, not an import/setup error.
- [x] Tests use real `Instance`, `Node`, `Solution`, `Route`, `ChargingAction`, `DynamicVehicleState`, `DynamicCheckContext`, and `DynamicEvent` objects.
- [x] Tests call real `route_node_schedule`, `ev_arc_energy_kwh`, `check_solution`, `_commit_executed_customers`, `_solution_for_committed_customers`, and `_instance_after_events` functions.
- [x] No mock/monkeypatch of `evaluate`, `check_solution`, or the rolling solver is present.
- [x] No production code was modified and no long experiment was run.
- [x] Normal focused run reports exactly four strict expected failures; `--runxfail` reproduces exactly four failures.
