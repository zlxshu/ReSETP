# Track24-R2 Commit Chunk Legality Debug And Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix or conclusively disprove the remaining Track24-R `HALT_E7_COMMIT_CHUNK_CHECK` root cause for `E-UK50_01`, seed `907`, action `stage_budget_event_density`, without training PPO or weakening legality checks.

**Architecture:** Treat the remaining failure as a commit-replay legality bug, not a final pending bug. First reproduce the C32 failure and compare original planned schedule versus extracted commit chunk schedule; then implement the smallest source fix that preserves commit semantics while keeping `check.py`, `cost.py`, `search/evaluation.py`, `search/metaheuristic_baselines.py`, and TeX untouched. Validation must resume only failed Track24-R rows and must not convert mixed-code evidence into a breakthrough claim.

**Tech Stack:** Python 3.13 venv at `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`, pytest, PowerShell, `setp_solver.search.dynamic`, Track24 runner `solver/rl/dr_alns_ppo/track24_breakthrough_audit.py`.

---

## Current Ground Truth

Track24 original Stage3 completed `260/260` but had `124` health failures, so the old `8.4867 pp` mean reduction is invalid as breakthrough evidence. Track24-R fixed the final pending/final repair path in `solver/src/setp_solver/search/dynamic.py`, but failure-only validation stopped at one remaining row:

```json
{
  "bundle": "E-UK50_01__curric_d2_s3_seed1_24h",
  "seed": 907,
  "action_id": "stage_budget_event_density",
  "gate": "HALT_E7_COMMIT_CHUNK_CHECK",
  "first_bad_stage": 2,
  "first_violation": {
    "constraint_type": "TIME_WINDOW",
    "nodes": "C32",
    "route_id": "S2_2_EV1#T1",
    "detail": "late by 228.326 s (due l=19232.000, start=19460.326)"
  }
}
```

The likely source path is:

```python
# solver/src/setp_solver/search/dynamic.py
newly_committed = _commit_executed_customers(previous_plan, previous_instance, trigger, served_customers)
chunk = _solution_for_customer_subset(previous_plan, previous_instance, bundle.carbon_profile, newly_committed, ...)
chunk_violations = check_solution(chunk, _subinstance_for_customers(previous_instance, newly_committed), prices)
```

`_solution_for_customer_subset()` currently rebuilds routes as `[home_depot, *group, home_depot]`. For a committed customer that was originally served inside a longer EV route, this can change arrival/service time and create a false `TIME_WINDOW` violation. This is the primary hypothesis, but the plan below requires proving it before fixing.

---

## Files And Responsibilities

- Modify: `solver/src/setp_solver/search/dynamic.py`
  - Add debug/audit helpers only if they are production-neutral or gated through tests.
  - Fix commit chunk extraction or commit chunk checking semantics.
  - Keep final repair logic intact.

- Modify: `solver/tests/test_formal_runner.py`
  - Add RED tests for C32-style commit replay.
  - Add focused unit tests for the selected fix.

- Modify: `solver/rl/dr_alns_ppo/track24_breakthrough_audit.py`
  - Only if resume/failure-only summary needs stricter status handling after the fix.
  - Do not change Stage4 gate to allow training.

- Optional create: `solver/tools/track24r_commit_chunk_probe.py`
  - One-off deterministic evidence script that emits a small JSON summary for C32.
  - It must not write long logs to chat; write full evidence under `solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/debug/`.

- Do not modify:
  - `solver/src/setp_solver/cost.py`
  - `solver/src/setp_solver/check.py`
  - `solver/src/setp_solver/search/evaluation.py`
  - `solver/src/setp_solver/search/metaheuristic_baselines.py`
  - `*.tex`

---

## Task 1: Reproduce C32 Failure And Capture Minimal Evidence

**Files:**
- Create: `solver/tools/track24r_commit_chunk_probe.py`
- Evidence output: `solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/debug/commit_chunk_c32_probe.json`

- [ ] **Step 1: Create the probe script**

Use `apply_patch` to add this file:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from setp_solver.check import check_solution
from setp_solver.cost import route_node_schedule
from setp_solver.search import dynamic as dynamic_module
from setp_solver.search.dynamic import RollingParameters, _solution_for_customer_subset, _subinstance_for_customers
from setp_solver.solution import Solution


BUNDLE_DIR = Path("models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h")
OUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/debug")
OUT_JSON = OUT_DIR / "commit_chunk_c32_probe.json"


def route_with_customer(solution: Solution, customer_id: str):
    for route in solution.routes:
        if customer_id in route.node_sequence:
            return route
    return None


def schedule_row(route: Any, instance: Any, customer_id: str) -> dict[str, Any]:
    for row in route_node_schedule(route, instance):
        if row.node_id == customer_id:
            return {
                "node_id": row.node_id,
                "t_arrive": float(row.t_arrive),
                "t_start": float(row.t_start),
                "t_depart": float(row.t_depart),
            }
    return {}


def node_state(instance: Any, customer_id: str) -> dict[str, Any]:
    node = next(node for node in instance.nodes if node.node_id == customer_id)
    return {
        "node_id": node.node_id,
        "demand": float(node.demand),
        "ready_time": float(node.ready_time),
        "due_time": float(node.due_time),
        "x": float(node.x),
        "y": float(node.y),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    captured: dict[str, Any] = {}
    original_run_stage_plan = dynamic_module._run_stage_plan

    def wrapped_run_stage_plan(*args, **kwargs):
        result = original_run_stage_plan(*args, **kwargs)
        stage_bundle_dir = Path(args[3])
        if stage_bundle_dir.name == "stage_001":
            captured["previous_plan"] = result.solution
            captured["previous_instance"] = result.instance
        return result

    dynamic_module._run_stage_plan = wrapped_run_stage_plan
    try:
        payload = dynamic_module.run_rolling_reoptimization(
            BUNDLE_DIR,
            output_json_path=OUT_DIR / "seed907_stage_budget_event_density_probe_payload.json",
            seed=907,
            eval_budget=2000,
            max_runtime_seconds=180.0,
            stage_eval_budget=2000,
            stage_max_runtime_seconds=120.0,
            params=RollingParameters(stages=4),
            policy_callback=None,
        )
    finally:
        dynamic_module._run_stage_plan = original_run_stage_plan

    previous_plan = captured.get("previous_plan")
    previous_instance = captured.get("previous_instance")
    if previous_plan is None or previous_instance is None:
        OUT_JSON.write_text(json.dumps({"error": "missing stage_001 capture", "payload_gate": payload.get("gate")}, indent=2), encoding="utf-8")
        return 2

    route = route_with_customer(previous_plan, "C32")
    chunk = _solution_for_customer_subset(previous_plan, previous_instance, [], {"C32"}, prefix="S2_", prices=dynamic_module.DEFAULT_PRICES)
    chunk_route = route_with_customer(chunk, "C32")
    summary = {
        "payload_gate": payload.get("gate", ""),
        "original_route_id": getattr(route, "vehicle_id", ""),
        "original_sequence": list(getattr(route, "node_sequence", [])),
        "chunk_route_id": getattr(chunk_route, "vehicle_id", ""),
        "chunk_sequence": list(getattr(chunk_route, "node_sequence", [])),
        "node_state": node_state(previous_instance, "C32"),
        "original_c32_schedule": schedule_row(route, previous_instance, "C32") if route is not None else {},
        "chunk_c32_schedule": schedule_row(chunk_route, previous_instance, "C32") if chunk_route is not None else {},
        "chunk_violations": [
            {
                "type": getattr(v, "type", ""),
                "vehicle_id": getattr(v, "vehicle_id", ""),
                "location": getattr(v, "location", ""),
                "detail": getattr(v, "detail", ""),
                "severity": getattr(v, "severity", ""),
            }
            for v in check_solution(chunk, _subinstance_for_customers(previous_instance, {"C32"}))
        ],
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"phase": "probe_done", "gate": summary["payload_gate"], "out": str(OUT_JSON)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$env:PYTHONPATH='solver\src;solver\rl;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe solver\tools\track24r_commit_chunk_probe.py
```

Expected: one-line JSON in stdout and a full evidence JSON at `solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/debug/commit_chunk_c32_probe.json`.

- [ ] **Step 3: Interpret the probe**

Open only the small fields:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$p='solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/debug/commit_chunk_c32_probe.json'
$j=Get-Content -LiteralPath $p -Raw | ConvertFrom-Json
[pscustomobject]@{
  original_route_id=$j.original_route_id
  chunk_route_id=$j.chunk_route_id
  original_start=$j.original_c32_schedule.t_start
  chunk_start=$j.chunk_c32_schedule.t_start
  due=$j.node_state.due_time
  violation=($j.chunk_violations[0] | ConvertTo-Json -Compress)
} | ConvertTo-Json -Compress
```

Expected for Hypothesis A: original schedule is feasible or materially different, while chunk schedule starts around `19460.326` and violates C32 due time `19232.000`.

- [ ] **Step 4: Commit evidence script only if it is useful for future regression**

If the script gives clear evidence and is not too brittle:

```powershell
git add solver/tools/track24r_commit_chunk_probe.py
git commit -m "test: add Track24R commit chunk probe"
```

If it is too brittle, leave it untracked and move the useful logic into pytest in Task 2.

---

## Task 2: Add RED Test For Commit Chunk Replay Semantics

**Files:**
- Modify: `solver/tests/test_formal_runner.py`

- [ ] **Step 1: Add a minimal synthetic failing test**

Add this test near the existing dynamic tests. The test models the core bug: a customer is committed from a route whose original schedule is valid because earlier route timing is preserved, but `_solution_for_customer_subset()` rebuilds the committed route as depot-customer-depot and can change schedule semantics.

```python
def test_dynamic_commit_chunk_preserves_original_planned_service_time(self) -> None:
    instance = _synthetic_dynamic_instance(
        [("C1", 1.0, 10.0, 0.0), ("C2", 1.0, 1000.0, 0.0)],
        stations=[],
    )
    plan = Solution(routes=[Route("EV1#T1", "ev", "D0", ["D0", "C1", "C2", "D0"])])
    committed = {"C2"}

    chunk = _solution_for_customer_subset(
        plan,
        instance,
        _flat_carbon_profile(),
        committed,
        prefix="S2_",
    )

    self.assertEqual(chunk.routes[0].node_sequence, ["D0", "C1", "C2", "D0"])
```

This should fail before the fix because current `_solution_for_customer_subset()` returns `["D0", "C2", "D0"]`.

- [ ] **Step 2: Run only the RED test**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$env:PYTHONPATH='solver\src;solver\rl;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m pytest solver\tests\test_formal_runner.py::FormalRunnerTests::test_dynamic_commit_chunk_preserves_original_planned_service_time -q
```

Expected: FAIL showing the current chunk route is rebuilt without predecessor context.

- [ ] **Step 3: Add a second RED test for the real gate path**

Add a test that forces `HALT_E7_COMMIT_CHUNK_CHECK` under the old replay behavior, then expects no halt after the fix:

```python
def test_dynamic_commit_chunk_uses_committed_route_context(self) -> None:
    instance = _synthetic_dynamic_instance(
        [("C1", 1.0, 10.0, 0.0), ("C2", 1.0, 1000.0, 0.0)],
        stations=[],
    )
    bundle = SimpleNamespace(instance=instance, carbon_profile=_flat_carbon_profile(), bundle_dir=str(FIXTURE_DIR))
    first_plan = Solution(routes=[Route("EV1#T1", "ev", "D0", ["D0", "C1", "C2", "D0"])])
    calls = {"count": 0}

    def fake_stage_plan(*args, **kwargs):
        calls["count"] += 1
        return StagePlanResult(first_plan if calls["count"] == 1 else Solution(), instance, 1, True, [])

    def fake_commit(plan, _instance, trigger, already_served):
        _ = plan, _instance, trigger, already_served
        return {"C2"} if calls["count"] >= 1 else set()

    with tempfile.TemporaryDirectory() as tmp, patch.object(dynamic_module, "load_search_bundle", return_value=bundle), patch.object(
        dynamic_module, "load_or_generate_dynamic_events", return_value=[formal_runner.dynamic_event_for_test("1", "demand_change", 1.0, "C1", new_demand=1.0)]
    ), patch.object(dynamic_module, "_run_stage_plan", fake_stage_plan), patch.object(
        dynamic_module, "_commit_executed_customers", fake_commit
    ), patch.object(
        dynamic_module, "run_alns_wouda", return_value=SimpleNamespace(best_solution=Solution(), feasible=True, evaluations=0)
    ), patch.object(dynamic_module, "evaluate", return_value={"total_cost": 100.0, "E_total": 10.0}), patch.object(
        dynamic_module, "check_solution", return_value=[]
    ):
        report = run_rolling_reoptimization(
            FIXTURE_DIR,
            output_json_path=Path(tmp) / "payload.json",
            seed=1,
            eval_budget=1,
            stage_eval_budget=1,
            params=RollingParameters(delta_t_seconds=2.0, q_bar=8),
        )

    self.assertNotEqual(report.get("gate"), "HALT_E7_COMMIT_CHUNK_CHECK")
```

- [ ] **Step 4: Run both tests and confirm RED**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$env:PYTHONPATH='solver\src;solver\rl;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m pytest solver\tests\test_formal_runner.py -k "commit_chunk" -q
```

Expected: at least the route-context test fails before implementation.

---

## Task 3: Fix Commit Chunk Extraction Without Weakening Checkers

**Files:**
- Modify: `solver/src/setp_solver/search/dynamic.py`
- Test: `solver/tests/test_formal_runner.py`

- [ ] **Step 1: Add a dedicated commit extraction helper**

Implement a new helper immediately before `_solution_for_customer_subset()`:

```python
def _solution_for_committed_customers(
    plan: Solution | None,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    customer_ids: set[str],
    *,
    prefix: str,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> Solution:
    if plan is None or not customer_ids:
        return Solution()
    node_lookup = {node.node_id: node for node in instance.nodes}
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    vehicle_map: dict[str, str] = {}
    for route in plan.routes:
        committed_on_route = [node_id for node_id in route.node_sequence if node_id in customer_ids and node_id in node_lookup]
        if not committed_on_route or route.home_depot_id not in node_lookup:
            continue
        last_index = max(route.node_sequence.index(node_id) for node_id in committed_on_route)
        prefix_sequence = [node_id for node_id in route.node_sequence[: last_index + 1] if node_id in node_lookup]
        if not prefix_sequence or prefix_sequence[0] != route.home_depot_id:
            prefix_sequence = [route.home_depot_id, *prefix_sequence]
        if prefix_sequence[-1] != route.home_depot_id:
            prefix_sequence = [*prefix_sequence, route.home_depot_id]
        vehicle_id = f"{prefix}{len(routes) + 1}_{route.vehicle_id}"
        vehicle_map[route.vehicle_id] = vehicle_id
        candidate = Route(vehicle_id, route.vehicle_type.lower(), route.home_depot_id, prefix_sequence)
        if candidate.vehicle_type == "ev":
            repaired_route, route_actions = repair_route_charging(candidate, instance, carbon_profile, prices)
            routes.append(repaired_route)
            actions.extend(route_actions)
        else:
            routes.append(candidate)
    actions.extend(
        replace(action, vehicle_id=vehicle_map[action.vehicle_id])
        for action in plan.charging_actions
        if action.vehicle_id in vehicle_map and action.station_id in node_lookup
    )
    return Solution(routes=routes, charging_actions=actions)
```

This preserves route prefix context for committed customers while still producing a standalone route from depot back to depot for `check_solution()`.

- [ ] **Step 2: Replace commit chunk extraction only**

In `run_rolling_reoptimization()`, replace this call inside the `newly_committed` block:

```python
chunk = _solution_for_customer_subset(
    previous_plan,
    previous_instance,
    bundle.carbon_profile,
    newly_committed,
    prefix=f"S{stage_index}_",
    prices=prices,
)
```

with:

```python
chunk = _solution_for_committed_customers(
    previous_plan,
    previous_instance,
    bundle.carbon_profile,
    newly_committed,
    prefix=f"S{stage_index}_",
    prices=prices,
)
```

Do not change final repair, stage plan checks, or static/dynamic final checks.

- [ ] **Step 3: Export helper for tests only if needed**

If tests import the helper directly, add it to the existing import block in `solver/tests/test_formal_runner.py`:

```python
from setp_solver.search.dynamic import (
    RollingParameters,
    RollingPolicyDecision,
    StagePlanResult,
    generate_dynamic_events,
    myopic_rolling_policy,
    run_rolling_reoptimization,
    _solution_for_committed_customers,
    _solution_for_customer_subset,
)
```

- [ ] **Step 4: Run commit chunk tests**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$env:PYTHONPATH='solver\src;solver\rl;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m pytest solver\tests\test_formal_runner.py -k "commit_chunk" -q
```

Expected: PASS.

- [ ] **Step 5: If Task 1 disproves Hypothesis A, stop this task**

If the probe proves the original stage plan itself is infeasible before extraction, do not implement `_solution_for_committed_customers()`. Instead proceed to Task 4.

---

## Task 4: Check Node-State And Stage-Plan Health Hypotheses

**Files:**
- Modify only if evidence points here: `solver/src/setp_solver/search/dynamic.py`
- Evidence: `solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/debug/commit_chunk_c32_node_states.json`

- [ ] **Step 1: Compare C32 node state across instances**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$payload='solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/stage3_payloads/E-UK50_01__curric_d2_s3_seed1_24h_seed907_stage_budget_event_density.json'
$j=Get-Content -LiteralPath $payload -Raw | ConvertFrom-Json
[pscustomobject]@{
  gate=$j.gate
  first_bad_stage=$j.first_bad_stage
  first_violation=($j.violations[0] | ConvertTo-Json -Compress)
  stage_rows=($j.stage_rows | Measure-Object).Count
  policy_trace=($j.policy_trace | Measure-Object).Count
} | ConvertTo-Json -Compress
```

Expected: confirms the remaining gate is still `HALT_E7_COMMIT_CHUNK_CHECK` before any new fix.

- [ ] **Step 2: If original stage plan has a violation, fix stage gate**

If Task 1 shows `check_solution(previous_plan, previous_instance)` already contains `TIME_WINDOW C32`, then the root cause is stage gate leakage. Add this test:

```python
def test_dynamic_stage_plan_full_instance_violation_halts_before_commit(self) -> None:
    from setp_solver.check import Violation

    violation = Violation("TIME_WINDOW", "EV1", "C32", "late by 1.0")
    stage_plan = StagePlanResult(Solution(routes=[Route("EV1", "ev", "D0", ["D0", "C32", "D0"])]), _synthetic_dynamic_instance([("C32", 1.0, 10.0, 0.0)], stations=[]), 1, True, [violation])

    def fake_stage_plan(*args, **kwargs):
        _ = args, kwargs
        return stage_plan

    with patch.object(dynamic_module, "_run_stage_plan", fake_stage_plan), patch.object(
        dynamic_module, "load_or_generate_dynamic_events", return_value=[]
    ):
        report = run_rolling_reoptimization(FIXTURE_DIR, seed=1, eval_budget=1, stage_eval_budget=1)

    self.assertEqual(report["gate"], "HALT_E7_STAGE_CHECK")
```

Then fix the exact stage gate path. Do not bypass or downgrade `check_solution()`.

- [ ] **Step 3: If C32 node state differs incorrectly, fix planned-against state**

If Task 1 shows C32 due/demand in commit subinstance differs from the node state used by the original planned route, adjust the commit path to use the planned-against `previous_instance` node state. Add this assertion to the commit test:

```python
self.assertEqual(
    next(node for node in previous_instance.nodes if node.node_id == "C32").due_time,
    next(node for node in commit_instance.nodes if node.node_id == "C32").due_time,
)
```

Expected: the commit instance and previous planned instance agree on C32 state.

---

## Task 5: Confirm RollingPolicyDecision Budget Retention Is Still Covered

**Files:**
- Read: `solver/src/setp_solver/search/dynamic.py`
- Read: `solver/tests/test_formal_runner.py`

- [ ] **Step 1: Verify existing tests still exist**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
rg -n "test_policy_decision_preserves_active_subset_and_budget_override|test_dict_policy_decision_preserves_budget_override" solver/tests/test_formal_runner.py
```

Expected: both tests exist.

- [ ] **Step 2: Run budget-retention tests**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$env:PYTHONPATH='solver\src;solver\rl;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m pytest solver\tests\test_formal_runner.py -k "policy_decision_preserves" -q
```

Expected: PASS. If FAIL, fix `_policy_decision_for_stage()` and `_coerce_policy_decision()` before continuing.

---

## Task 6: Run Focused Regression Suite

**Files:**
- Test only.

- [ ] **Step 1: Run dynamic runner targeted tests**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$env:PYTHONPATH='solver\src;solver\rl;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m pytest solver\tests\test_formal_runner.py -k "dynamic_policy or dynamic_final or policy_decision or dynamic_payload or commit_chunk" -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run Track24/Track18/Track23 report tests**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$env:PYTHONPATH='solver\src;solver\rl;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m pytest solver\rl\tests\test_track24_breakthrough_audit.py solver\rl\tests\test_final_track18.py solver\rl\tests\test_final_track23.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Check protected diffs**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
git diff --check
git diff -- solver/src/setp_solver/cost.py solver/src/setp_solver/check.py solver/src/setp_solver/search/evaluation.py solver/src/setp_solver/search/metaheuristic_baselines.py
git diff -- '*.tex'
```

Expected: no output from all three checks.

- [ ] **Step 4: Commit source fix**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
git add solver/src/setp_solver/search/dynamic.py solver/tests/test_formal_runner.py
git commit -m "fix: preserve dynamic commit chunk legality"
```

Do not stage report CSVs or long logs.

---

## Task 7: Resume Only Failed Track24-R Row

**Files:**
- Evidence output: `solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/`

- [ ] **Step 1: Remove only the failed rerun row from Track24-R rows**

Do not delete old Track24 evidence. Create a backup first:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$rows='solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/stage3_dynamic_oracle_rows.csv'
Copy-Item -LiteralPath $rows -Destination "$rows.before_commit_chunk_fix.bak" -Force
$data=Import-Csv $rows
$filtered=$data | Where-Object {
  -not ($_.bundle -eq 'E-UK50_01__curric_d2_s3_seed1_24h' -and $_.seed -eq '907' -and $_.action_id -eq 'stage_budget_event_density')
}
$filtered | Export-Csv -LiteralPath $rows -NoTypeInformation -Encoding UTF8
```

Expected: row count decreases by one. If any other row is removed, restore from backup and stop.

- [ ] **Step 2: Resume failure-only Track24-R**

Run as a long task with full logs to file:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$outDir='solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality'
$logDir=Join-Path $outDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:PYTHONPATH='solver\rl;solver\src;models\src'
$stdout=Join-Path $logDir 'track24r2_failure_only_resume.log'
$stderr=Join-Path $logDir 'track24r2_failure_only_resume.err.log'
$p=Start-Process -FilePath 'C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe' -ArgumentList @(
  '-m','dr_alns_ppo.track24_breakthrough_audit','run',
  '--output-dir',$outDir,
  '--stages','3,4,7',
  '--stage3-rerun-health-failures-only',
  '--stage3-source-rows','solver/reports/dr_alns_ppo_v3/final_track24_breakthrough_audit/stage3_dynamic_oracle_rows.csv'
) -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
Set-Content -LiteralPath (Join-Path $logDir 'track24r2.pid') -Value $p.Id
```

- [ ] **Step 3: Monitor with low-token status only**

Probe at most every 15 minutes unless a failure appears:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$rows='solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/stage3_dynamic_oracle_rows.csv'
$r=Import-Csv $rows
$fail=$r | Where-Object {$_.health_status -ne 'HEALTHY' -and $_.health_status -ne ''}
[pscustomobject]@{
  phase='stage3_resume'
  rows="$($r.Count)/260"
  ok=($r | Where-Object {$_.health_status -eq 'HEALTHY'}).Count
  fail=$fail.Count
  halt=($fail.Count -gt 0)
  current_instance=if($r.Count){ "$($r[-1].bundle):$($r[-1].seed):$($r[-1].action_id)" } else { "" }
  workers=1
  decision_needed=$false
} | ConvertTo-Json -Compress
```

Stop immediately if `fail > 0`, worker dies, protected diff appears, or output structure is malformed.

---

## Task 8: Recompute Verdict And Decide Whether Dynamic Line Continues

**Files:**
- Read: `solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/stage3_dynamic_oracle_summary.json`
- Read: `solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/track24_decision.json`

- [ ] **Step 1: Summarize health**

Run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$summary='solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/stage3_dynamic_oracle_summary.json'
$j=Get-Content -LiteralPath $summary -Raw | ConvertFrom-Json
[pscustomobject]@{
  status=$j.status
  rows=$j.row_count
  planned=$j.planned_row_count
  health_failure_count=$j.health_failure_count
  mean_reduction_pp=$j.mean_information_cost_reduction_pp
  mixed_code=$j.mixed_code_result
  carried=$j.carried_forward_pre_fix_count
  rerun=$j.rerun_fixed_code_count
} | ConvertTo-Json -Compress
```

Expected after fixing the last row: `health_failure_count=0`. Status may still be `TRACK24R_FAILURE_ONLY_HEALTHY_MIXED_REFERENCE` because carried rows are pre-fix code.

- [ ] **Step 2: Apply decision gates**

Use these exact gates:

```text
If health_failure_count > 0:
  Stop. Report remaining root cause. Do not Stage4.

If health_failure_count == 0 and mixed_code_result == true:
  Do not claim breakthrough. Decide whether to run full fixed-code 260 confirmation.

If full fixed-code Stage3 mean reduction < 2 pp:
  Stop dynamic PPO line. Report HALT_DYNAMIC_ACTION_SPACE_FLAT.

If full fixed-code Stage3 mean reduction >= 2 pp and all health checks pass:
  Stage4 imitation/bandit design may start in a separate plan.
```

- [ ] **Step 3: If needed, launch full fixed-code Stage3 only after explicit decision**

Do not run this automatically after failure-only health passes. Full 260 confirmation is expensive and should be a separate controlled long run:

```powershell
Set-Location -LiteralPath 'D:\ReSETP'
$outDir='solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality_full_fixed'
$env:PYTHONPATH='solver\rl;solver\src;models\src'
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m dr_alns_ppo.track24_breakthrough_audit run --output-dir $outDir --stages 0,1,2,3,4,5,6,7 --no-resume
```

Expected: only after full fixed-code rows are all healthy can any Stage4 planning begin.

---

## Task 9: Final Report Format

When work stops, report in this exact shape:

```text
Verdict:
Rows:
OK / fail / HALT:
Commits:
Files changed:
Evidence files:
Remaining risk:
Next step:
```

Required statements:

- If any commit/final chunk HALT remains, say dynamic PPO is still blocked.
- If only failure-only mixed-code evidence is healthy, say it is not a breakthrough claim.
- If full fixed-code Stage3 has not been run, say that explicitly.
- If mean reduction is below `2 pp`, stop the dynamic DR line.

---

## Self-Review

Spec coverage:

- Root cause investigation before fix: Task 1 and Task 4.
- Four hypotheses A/B/C/D: Task 1 proves A, Task 4 covers B/C, Task 5 covers D.
- RED tests before source fix: Task 2.
- Protected files untouched: Task 6.
- Failure-only resume: Task 7.
- Recompute headroom and stop gates: Task 8.
- No Stage4/PPO before oracle gate: Task 8 and Task 9.

Placeholder scan:

- No `TBD`, `TODO`, or undefined later work is used as a required implementation step.
- Every command is concrete and scoped to `D:\ReSETP`.

Type consistency:

- All referenced public types already exist: `RollingParameters`, `StagePlanResult`, `Route`, `Solution`.
- New helper `_solution_for_committed_customers()` is intentionally private and used only from `run_rolling_reoptimization()` commit chunk path.
