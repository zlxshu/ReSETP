# DR-ALNS Project Rhythm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the ReSETP DR-ALNS work into an evidence-first rhythm, then prepare the next safe implementation step: Pilot11 interface audit.

**Architecture:** Planning and handoff documents live under `D:\ReSETP\docs\handoff\` and `D:\ReSETP\docs\superpowers\plans\`. The next code-bearing step, Pilot11, must be diagnostic-only: it may add a reporting/audit tool and tests, but it must not train, evaluate performance claims, or modify solver semantics.

**Tech Stack:** Markdown handoff documents, Python diagnostic tooling under `solver/rl/dr_alns_ppo/`, pytest tests under `solver/rl/tests/`, existing ReSETP solver/RL modules.

---

## Scope And Non-Negotiables

This plan is not permission to resume long DR training. It is permission to document the project rhythm and, after review, implement a no-training interface audit.

Protected files remain protected: `D:\ReSETP\solver\src\setp_solver\cost.py`, `D:\ReSETP\solver\src\setp_solver\check.py`, and `D:\ReSETP\solver\src\setp_solver\search\evaluation.py` must not be modified.

Future comparisons must use same-machine relative percentages and must compare learned DR against best static/tuned meta baselines, not only default AlphaUCB.

## File Structure

- Create: `D:\ReSETP\docs\handoff\dr_alns_project_rhythm_manual.md`
  - Responsibility: human-readable operating manual for project rhythm, stop lines, DR evidence, and next-step gates.
- Create: `D:\ReSETP\docs\superpowers\plans\2026-06-26-dr-alns-project-rhythm.md`
  - Responsibility: executable task plan for the handbook and the next Pilot11 interface audit.
- Future create: `D:\ReSETP\solver\rl\dr_alns_ppo\pilot11_interface_audit.py`
  - Responsibility: no-training diagnostic report generator that maps current ReSETP state/action/reward interface against literature/reference-code patterns.
- Future create: `D:\ReSETP\solver\rl\tests\test_pilot11_interface_audit.py`
  - Responsibility: tests for schema, missing-field classification, feasible action-head mapping, and halt/pass gates.
- Future output, ignored unless curated: `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot11_interface_audit\`
  - Responsibility: generated markdown/json/csv audit outputs.

## Task 1: Project Rhythm Manual

**Files:**
- Create: `D:\ReSETP\docs\handoff\dr_alns_project_rhythm_manual.md`
- Create: `D:\ReSETP\docs\superpowers\plans\2026-06-26-dr-alns-project-rhythm.md`

- [x] **Step 1: Verify branch and clean worktree**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
git rev-parse --abbrev-ref HEAD
git status --short
```

Expected:

```text
dr-x86
```

and no status rows before writing the manual.

- [x] **Step 2: Create the rhythm manual**

Create `D:\ReSETP\docs\handoff\dr_alns_project_rhythm_manual.md` with these required sections:

```markdown
# ReSETP DR-ALNS Project Rhythm Manual

## 1. Current Project Truth
## 2. Non-Negotiable Boundaries
## 3. Workstream Priorities
## 4. The Required Loop
## 5. Communication Rhythm
## 6. DR Stop Lines
## 7. Next Correct Step: Pilot11 Interface Audit
## 8. Pilot11 Gate Design
## 9. Candidate Step 2 Paths After Pilot11
## 10. What Not To Do Next
## 11. Files To Read Before Any DR Action
## 12. Commit And Artifact Rules
## 13. Immediate Subplans
```

Expected content:

```text
The manual states that Pilot08/Pilot09/Pilot10 stopped same-shape PPO, that tuned/static meta is the honest baseline, that no long DR training starts before a diagnostic gate, and that Pilot11 is an interface audit rather than a training run.
```

- [x] **Step 3: Create this execution plan**

Create `D:\ReSETP\docs\superpowers\plans\2026-06-26-dr-alns-project-rhythm.md` with the required plan header and task checkboxes.

Expected content:

```text
The plan separates documentation work from future Pilot11 code work and keeps protected solver files out of scope.
```

- [x] **Step 4: Self-check the documents**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
$placeholderPattern = ("TO" + "DO") + "|" + ("TB" + "D") + "|" + ("PLACE" + "HOLDER")
rg -n $placeholderPattern docs\handoff\dr_alns_project_rhythm_manual.md docs\superpowers\plans\2026-06-26-dr-alns-project-rhythm.md
rg -n "default AlphaUCB as the only serious opponent|Pilot11 Interface Audit" docs\handoff\dr_alns_project_rhythm_manual.md docs\superpowers\plans\2026-06-26-dr-alns-project-rhythm.md
git status --short
```

Expected:

```text
No placeholder-marker rows.
git status shows only the two intended new markdown files.
```

## Task 2: Pilot11 Interface Audit Design

**Files:**
- Create: `D:\ReSETP\solver\rl\dr_alns_ppo\pilot11_interface_audit.py`
- Create: `D:\ReSETP\solver\rl\tests\test_pilot11_interface_audit.py`
- Read: `D:\ReSETP\solver\rl\dr_alns_ppo\block_env.py`
- Read: `D:\ReSETP\solver\rl\dr_alns_ppo\action_space.py`
- Read: `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\literature_materials\dr_alns_gap_diagnosis_20260626.md`

- [x] **Step 1: Write schema tests first**

Create `D:\ReSETP\solver\rl\tests\test_pilot11_interface_audit.py` with tests that require this public API:

```python
from __future__ import annotations

from dr_alns_ppo.pilot11_interface_audit import (
    CURRENT_BLOCK_INTERFACE,
    REQUIRED_LITERATURE_SIGNALS,
    build_gap_rows,
    classify_gate,
)


def test_current_block_interface_names_existing_heads() -> None:
    assert CURRENT_BLOCK_INTERFACE["obs_dim"] == 19
    assert CURRENT_BLOCK_INTERFACE["action_heads"] == [
        "destroy",
        "repair",
        "q_ratio",
        "threshold_ratio",
        "exploration_ratio",
    ]
    assert "charging_strategy" not in CURRENT_BLOCK_INTERFACE["action_heads"]
    assert "accept_stop" not in CURRENT_BLOCK_INTERFACE["action_heads"]


def test_required_literature_signals_include_domain_state_and_control() -> None:
    names = {row["name"] for row in REQUIRED_LITERATURE_SIGNALS}
    assert "route_sequence_state" in names
    assert "customer_time_window_state" in names
    assert "vehicle_energy_state" in names
    assert "charging_strategy_control" in names
    assert "acceptance_or_stop_control" in names


def test_gap_rows_mark_missing_route_and_charging_controls() -> None:
    rows = build_gap_rows()
    by_name = {row["name"]: row for row in rows}
    assert by_name["route_sequence_state"]["status"] == "missing"
    assert by_name["charging_strategy_control"]["status"] == "missing"
    assert by_name["q_threshold_exploration_control"]["status"] == "present"


def test_gate_requires_feasible_action_control_point() -> None:
    rows = build_gap_rows()
    gate = classify_gate(rows)
    assert gate["status"] == "NEEDS_INTERFACE_REDESIGN"
    assert "acceptance_or_stop_control" in gate["recommended_first_audit"]
```

- [x] **Step 2: Run schema tests and verify failure**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
$env:PYTHONPATH="D:\ReSETP\models\src;D:\ReSETP\solver\rl;D:\ReSETP\solver\src"
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" -m pytest solver\rl\tests\test_pilot11_interface_audit.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'dr_alns_ppo.pilot11_interface_audit'
```

- [x] **Step 3: Implement the minimal audit module**

Create `D:\ReSETP\solver\rl\dr_alns_ppo\pilot11_interface_audit.py` with this structure:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


CURRENT_BLOCK_INTERFACE = {
    "obs_dim": 19,
    "action_heads": ["destroy", "repair", "q_ratio", "threshold_ratio", "exploration_ratio"],
    "known_limits": [
        "No route sequence state",
        "No customer time-window feature table",
        "No direct charging strategy head",
        "No accept or stop head",
        "No learned repair insertion decision",
    ],
}


REQUIRED_LITERATURE_SIGNALS = [
    {
        "name": "route_sequence_state",
        "source": "Wang CEVRP / Johnn-style current-solution state",
        "current_status": "missing",
        "resetp_candidate_source": "Solution.routes[].node_sequence",
        "why_it_matters": "Operator value depends on current route structure.",
    },
    {
        "name": "customer_time_window_state",
        "source": "PPO-ALNS VRPTW observation dictionary",
        "current_status": "missing",
        "resetp_candidate_source": "instance.json customer fields",
        "why_it_matters": "Repair and insertion quality depends on demand, service, and time windows.",
    },
    {
        "name": "vehicle_energy_state",
        "source": "EVRP and fleet-routing DRL literature",
        "current_status": "missing",
        "resetp_candidate_source": "vehicle table, route vehicle_type, charging actions",
        "why_it_matters": "EV charging and carbon decisions require vehicle-specific energy context.",
    },
    {
        "name": "charging_strategy_control",
        "source": "CEVRP DRL-ALNS energy operator head",
        "current_status": "missing",
        "resetp_candidate_source": "candidates.py charging repair functions",
        "why_it_matters": "Carbon/energy phases need an action that directly affects charging behavior.",
    },
    {
        "name": "acceptance_or_stop_control",
        "source": "Reijnen DR-ALNS and PPO-ALNS acceptance/stop actions",
        "current_status": "missing",
        "resetp_candidate_source": "winner search loop acceptance threshold",
        "why_it_matters": "The policy needs direct control over accepting worse candidates or stopping search.",
    },
    {
        "name": "q_threshold_exploration_control",
        "source": "Pilot09/Pilot10 meta headroom",
        "current_status": "present",
        "resetp_candidate_source": "action_space.py BLOCK_Q_RATIOS/BLOCK_THRESHOLD_RATIOS/BLOCK_EXPLORATION_RATIOS",
        "why_it_matters": "Static tuning helps, but dynamic policy did not beat best static meta.",
    },
]


def build_gap_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for signal in REQUIRED_LITERATURE_SIGNALS:
        status = "present" if signal["current_status"] == "present" else "missing"
        rows.append(
            {
                "name": signal["name"],
                "status": status,
                "source": signal["source"],
                "resetp_candidate_source": signal["resetp_candidate_source"],
                "why_it_matters": signal["why_it_matters"],
            }
        )
    return rows


def classify_gate(rows: list[dict[str, str]]) -> dict[str, object]:
    missing = [row["name"] for row in rows if row["status"] == "missing"]
    return {
        "status": "NEEDS_INTERFACE_REDESIGN" if missing else "NO_INTERFACE_GAP",
        "missing_count": len(missing),
        "missing": missing,
        "recommended_first_audit": ["acceptance_or_stop_control", "charging_strategy_control"],
    }


def write_audit_report(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = build_gap_rows()
    gate = classify_gate(rows)
    payload = {"current_interface": CURRENT_BLOCK_INTERFACE, "gap_rows": rows, "gate": gate}
    (output_dir / "pilot11_interface_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = ["# Pilot11 Interface Audit", "", f"Gate: `{gate['status']}`", ""]
    for row in rows:
        lines.append(f"- `{row['name']}`: {row['status']} — {row['why_it_matters']}")
    (output_dir / "pilot11_interface_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload
```

- [x] **Step 4: Run tests and py_compile**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
$env:PYTHONPATH="D:\ReSETP\models\src;D:\ReSETP\solver\rl;D:\ReSETP\solver\src"
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" -m pytest solver\rl\tests\test_pilot11_interface_audit.py -q
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" -m py_compile solver\rl\dr_alns_ppo\pilot11_interface_audit.py
```

Expected:

```text
4 passed
```

- [x] **Step 5: Generate the local ignored audit report**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
$env:PYTHONPATH="D:\ReSETP\models\src;D:\ReSETP\solver\rl;D:\ReSETP\solver\src"
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" - <<'PY'
from pathlib import Path
from dr_alns_ppo.pilot11_interface_audit import write_audit_report
write_audit_report(Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot11_interface_audit"))
PY
```

Expected files:

```text
solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot11_interface_audit/pilot11_interface_audit.json
solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot11_interface_audit/pilot11_interface_audit.md
```

Do not force-add the generated report unless the user asks for curated evidence.

## Task 3: Pilot11 Review Gate

**Files:**
- Read: `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot11_interface_audit\pilot11_interface_audit.md`
- Optional modify after user approval: `D:\ReSETP\HANDOFF.md`

- [x] **Step 1: Review the audit output**

Open the markdown report and confirm it names at least these missing pieces:

```text
route_sequence_state
customer_time_window_state
vehicle_energy_state
charging_strategy_control
acceptance_or_stop_control
```

- [x] **Step 2: Choose the next small prototype**

Choose exactly one next path:

```text
Path A: acceptance or stop control
Path B: charging strategy control
Path C: richer-state trace dataset
Path D: static meta retune packaging
```

Do not run training at this gate.

- [x] **Step 3: Record the decision**

If a path is selected, append a short HANDOFF run log with this shape:

```markdown
- 2026-06-26 [x86/DR] Pilot11 interface audit completed: gate=`NEEDS_INTERFACE_REDESIGN`; selected next path=`Path A acceptance or stop control`; no training/evaluation run; protected solver semantics unchanged.
```

If no path is selected, append:

```markdown
- 2026-06-26 [x86/DR] Pilot11 interface audit completed: gate=`NEEDS_INTERFACE_REDESIGN`; no implementation path selected; DR remains stopped pending user choice.
```

## Task 4: Commit Hygiene

**Files:**
- Stage only files intentionally created or modified by the selected task.

- [x] **Step 1: Inspect status**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
git status --short
```

Allowed after Task 1 only:

```text
?? docs/handoff/dr_alns_project_rhythm_manual.md
?? docs/superpowers/plans/2026-06-26-dr-alns-project-rhythm.md
```

Allowed after Task 2:

```text
?? docs/handoff/dr_alns_project_rhythm_manual.md
?? docs/superpowers/plans/2026-06-26-dr-alns-project-rhythm.md
?? solver/rl/dr_alns_ppo/pilot11_interface_audit.py
?? solver/rl/tests/test_pilot11_interface_audit.py
```

- [x] **Step 2: Run targeted tests**

Run after Task 2:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
$env:PYTHONPATH="D:\ReSETP\models\src;D:\ReSETP\solver\rl;D:\ReSETP\solver\src"
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" -m pytest solver\rl\tests\test_pilot11_interface_audit.py solver\rl\tests\test_pilot10_block_meta_tools.py solver\rl\tests\test_pilot09_rescue_tools.py -q
```

Expected:

```text
All selected tests pass.
```

- [ ] **Step 3: Commit only after user approves the implemented scope**

For Task 1 only:

```powershell
git add docs/handoff/dr_alns_project_rhythm_manual.md docs/superpowers/plans/2026-06-26-dr-alns-project-rhythm.md
git commit -m "[x86/DR] Add DR project rhythm manual"
```

For Task 1 plus Task 2:

```powershell
git add docs/handoff/dr_alns_project_rhythm_manual.md docs/superpowers/plans/2026-06-26-dr-alns-project-rhythm.md solver/rl/dr_alns_ppo/pilot11_interface_audit.py solver/rl/tests/test_pilot11_interface_audit.py
git commit -m "[x86/DR] Add pilot11 interface audit plan and tool"
```

Do not push unless the user explicitly asks for push.

## Self-Review Checklist

- The plan does not authorize long training.
- The plan keeps protected solver semantics out of scope.
- The plan records Pilot08/Pilot09/Pilot10 as evidence, not as something to rerun.
- The plan makes best static/tuned meta the comparison bar for future DR learning claims.
- The plan gives a concrete next diagnostic tool and tests.
- The plan avoids generated reports and model files in git unless explicitly curated.
