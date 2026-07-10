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

## Review correction — real rolling-path evidence

This section supersedes the earlier scenario 3/4 evidence and the earlier
interpreter line.  The first version hand-assembled a stage view for charging
and called `_instance_after_events` directly for lifecycle state.  Those were
useful probes but did not prove the real `run_rolling_reoptimization` path, so
they are no longer the acceptance evidence.

### Corrected environment and xfail boundary

The corrected rolling tests use:

- Interpreter: `C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe`
- Python: `3.12.13`
- pytest: `9.1.1`
- numpy: `2.5.1`
- scipy: `1.18.0`
- real `alns` package loaded from that interpreter's `site-packages`

The preferred py313 environment does not contain `alns`.  Running the revised
suite there produced two intended assertion failures, two passing setup tests,
and five `ModuleNotFoundError: No module named 'alns'` errors.  The rolling
tests did **not** xfail those setup errors.  Every gap marker now specifies
both `strict=True` and `raises=AssertionError`; each rolling fixture is first
consumed by an ordinary passing test, and unexpected callback/stage structure
raises `RuntimeError`.

### Corrected real rolling fixtures

Both scenarios create a minimal temporary bundle containing real
`instance.json`, `distance_matrix.npy`, `carbon_profile.csv`, and
`dynamic_events.tsv`.  They invoke the real `run_rolling_reoptimization`,
real stage bundle writer/loader, real ALNS entry, real evaluator, and real
checker.  There is no mock or monkeypatch.  The public `policy_callback`
returns deterministic initial plans.  The charging scenario uses stage/global
evaluation budget zero so the resource witness cannot be mutated by a vehicle
type swap; the lifecycle scenario uses budget one.  Both still exercise the
real rolling, solver-initialization, evaluation, checking, commit, event,
final-repair, and static-control path.  One focused run remains below one
second.

Five prerequisite facts are ordinary passing tests rather than xfails:

1. The clock fixture is exactly a 250 m / 25 m/s = 10 s arc from the inherited position, and its dynamic state says time 100 s.
2. The EV fixture's real energy function returns exactly 2 kWh and the inherited battery is 1 kWh.
3. The real charger run reaches stages 0 and 1; stage 1 receives a real `previous_plan` with one action starting at 0 s; the full-ledger checker reports exactly `F1@slot0`; and the current stage-1 row contains one new charging action and is marked feasible.
4. The real lifecycle stage-1 callback receives all six cancel/change events; its real `previous_plan` contains both locked customers and excludes both open customers.
5. In that same real context, completed cancel/change preserve demands 10/11, while open cancel removes its customer and open demand-change becomes 311.

### Corrected RED command and four failures

```powershell
Set-Location -LiteralPath 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate'
$env:PYTHONPATH = 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate\solver\src'
& 'C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe' -m pytest -q solver/tests/test_dynamic_truth_gate.py --runxfail
```

Fresh pre-commit observation: exit 1, `4 failed, 5 passed in 0.61s`.

1. Clock: the checker still emits no 5-second `TIME_WINDOW` violation at start 110 s.
2. Battery: the checker still emits no `-1.000000 kWh` depletion violation for inherited 1 kWh minus the exact 2 kWh arc.
3. Charging: EV1 occupies the one-charger F1 from 0–1800 s; the rolling boundary is 600 s; EV2 is planned at 900–1500 s.  The real full-ledger checker reports `F1@slot0`, and stage 1's captured `previous_plan` contains EV1's action, but the real rolling report has no `HALT_E7_STAGE_CHECK` and treats the one-action stage plan as feasible.  Fixing only a helper cannot satisfy this assertion: the real runner must include historical resource occupancy in the actual stage check.
4. Lifecycle: the real stage-1 event batch executed both locked-customer operations.  Cancellation produced `present=False, demand=None`; demand-change independently produced `observed=211.0, expected=21.0`.  The same callback context reports committed IDs only as `C_DONE_CANCEL` and `C_DONE_CHANGE`, even though `previous_plan` contains `C_LOCK_CANCEL` and `C_LOCK_CHANGE`.  Thus locked-but-incomplete and open customers are not distinct in the real rolling state.

### Corrected strict-xfail and coverage commands

Normal focused command:

```powershell
Set-Location -LiteralPath 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate'
$env:PYTHONPATH = 'D:\ReSETP\.claude\worktrees\codex-dynamic-truth-gate\solver\src'
& 'C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe' -m pytest -q solver/tests/test_dynamic_truth_gate.py
```

Fresh pre-commit observation: exit 0, `5 passed, 4 xfailed in 0.61s`.

Related checker coverage:

```powershell
& 'C:\Users\zlxshu\AppData\Local\Temp\resetp-codex-py312\Scripts\python.exe' -m pytest -q solver/tests/test_check.py solver/tests/test_dynamic_truth_gate.py
```

Fresh pre-commit observation: exit 0, `38 passed, 4 xfailed in 0.66s`.

An additional attempt to run the two existing tests selected by
`dynamic_new_customer_visible_only_after_arrival or
dynamic_rolling_gate_conservation_assertions_pass` was unavailable in this
worktree: both failed during setup with `FileNotFoundError` for
`models/data_bundle/generated_instances/verify_20251113/instance.json`
(`2 failed, 53 deselected`).  The models fixture junction had been removed and
isolated outside this task; it was not restored or modified.  This result is
recorded as an unavailable legacy-fixture check, not as a production
regression.  The corrected truth tests do not depend on that missing fixture;
they build their own temporary on-disk bundles.

### Corrected self-check

- [x] Scenarios 3 and 4 now enter real `run_rolling_reoptimization` on temporary on-disk bundles.
- [x] No solver, evaluator, checker, bundle loader, or lifecycle function is mocked or monkeypatched.
- [x] All four xfail markers are strict and limited to `AssertionError`.
- [x] Correct setup/fixture/lifecycle facts are covered by five ordinary passing tests.
- [x] Cancellation and demand-change are both executed in the same real event batch and have separate observed evidence.
- [x] Focused normal mode reports exactly four xfails; `--runxfail` reports exactly four failures.
- [x] No file under `solver/src` is modified, and no long ALNS experiment is run.
