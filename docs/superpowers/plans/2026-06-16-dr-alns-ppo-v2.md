# DR-ALNS-PPO v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the isolated PPO lane so PPO learns operator selection on the Prompt1 winner-operator base, with a realistic target of matching the winner kernel on formal comparison instances.

**Architecture:** The RL lane stays under `solver/rl/` and reports stay under `solver/reports/dr_alns_ppo_v2/`. The PPO worker must import Prompt1's public winner operator module, record `operator_base_id` on every step/result row, and never reimplement destroy/repair logic locally. Training and evaluation are gated: no training until the random-action self-check proves the imported winner base behaves like the winner kernel on `100-01 + L-main`.

**Tech Stack:** Python, Gymnasium, Stable-Baselines3 PPO, existing `setp_solver` solution/evaluation/checker types, Prompt1 public module `setp_solver.search.winner_operators`.

---

## Scope And Non-Negotiables

- Do not modify `solver/src/setp_solver/search/formal_runner.py`, `PRIMARY_ALGORITHM`, formal E1-E7 outputs, manuscript files, `cost.py`, `check.py`, or `evaluation.py`.
- Do not copy logic from `alns_wouda.py`, `candidates.py`, `feasible_repair.py`, `repair_scoring.py`, or old `solver/rl/dr_alns_ppo/operator_manual.py` into the PPO operator path.
- New RL implementation files stay under `solver/rl/dr_alns_ppo/`.
- New reports, traces, checkpoints, curves, and comparison tables go only under `solver/reports/dr_alns_ppo_v2/`.
- Old `solver/reports/dr_alns_ppo/` and old 100k smoke are archival pipeline evidence only. Do not reuse old PPO models.
- Held-out learning can use non-overlapping SETP instances, but formal PPO comparison must be `100-01` plus `L-main`, not `E-UK100_03`.

## Critical Contract Finding

The current Task4 manifest exists at `solver/reports/alns_crush_v2/winner_operator_manifest.json` and declares:

```json
{
  "winner_operator_module": "setp_solver.search.winner_operators",
  "operator_base_id": "winner_kernel_v1",
  "public_api": [
    "WinnerKernelConfig",
    "winner_variant_flags",
    "run_winner_kernel",
    "run_winner_kernel_plus_route_elimination",
    "write_winner_manifest"
  ]
}
```

This proves the Prompt1 winner module exists, but it does not yet prove the module exposes a one-step operator API suitable for PPO actions. `run_winner_kernel()` runs a full kernel search; it cannot be used as one `env.step`, because one PPO step must equal one full candidate scoring event under the 16000-evaluation fairness budget.

Therefore Task 0 is a hard gate:

- If Prompt1 adds or already exposes a step-level API such as `apply_winner_action`, `WinnerOperatorAction`, or `WinnerOperatorSet.step_candidate`, continue.
- If the only public API remains full-run APIs, stop with `HALT_NO_STEP_API`.

## File Structure

- Modify `solver/rl/dr_alns_ppo/action_space.py`: replace legacy D/R labels with winner action labels from the imported winner module contract.
- Modify `solver/rl/dr_alns_ppo/operator_manual.py`: convert from hand-written operators into a thin import adapter around `setp_solver.search.winner_operators`.
- Modify `solver/rl/dr_alns_ppo/worker.py`: require winner adapter trace and emit `operator_base_id` per reset/step/close response.
- Modify `solver/rl/dr_alns_ppo/env.py`: keep one `env.step` equal to one candidate evaluation and expose operator-base audit fields in `info`.
- Modify `solver/rl/dr_alns_ppo/baselines.py`: add `winner_kernel` and fair-SA comparison rows with `operator_base_id`.
- Modify `solver/rl/dr_alns_ppo/evaluate_policy.py`: evaluate on formal `100-01 + L-main` for paper-aligned comparison.
- Modify `solver/rl/dr_alns_ppo/train_ppo.py`: write v2 config and forbid reusing old v1 checkpoints unless explicitly overridden.
- Modify `solver/rl/dr_alns_ppo/report_smoke.py`: write v2 self-check, curve, and comparison reports.
- Modify or add `solver/rl/dr_alns_ppo/bundle_manifest.py`: produce v2 train/eval manifests with training instances separated from formal comparison instances.
- Add `solver/rl/tests/test_winner_operator_adapter.py`: contract tests proving import, trace, and no local reimplementation.
- Add `solver/rl/tests/test_v2_manifest_alignment.py`: tests that formal eval uses `100-01 + L-main` and excludes `E-UK100_03`.
- Add `solver/rl/tests/test_v2_self_check_report.py`: tests that self-check reports halt gates and `operator_base_id`.
- Create `solver/reports/dr_alns_ppo_v2/`: output root only; generated at runtime.

## Task 0: Winner Step API Contract Gate

**Files:**
- Test: `solver/rl/tests/test_winner_operator_adapter.py`
- Read-only source: `solver/reports/alns_crush_v2/winner_operator_manifest.json`
- Read-only source: `solver/src/setp_solver/search/winner_operators.py`

- [ ] **Step 1: Write the failing contract test**

Add this test to `solver/rl/tests/test_winner_operator_adapter.py`:

```python
from __future__ import annotations

import importlib
import json
from pathlib import Path


MANIFEST = Path("solver/reports/alns_crush_v2/winner_operator_manifest.json")


def test_winner_manifest_exposes_step_level_public_api() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    module = importlib.import_module(manifest["winner_operator_module"])

    public_api = set(manifest["public_api"])
    step_api_names = {
        "apply_winner_action",
        "WinnerOperatorAction",
        "WinnerOperatorSet",
        "decode_winner_action",
    }

    missing = sorted(step_api_names - public_api)
    assert not missing, f"HALT_NO_STEP_API missing public_api={missing}"
    for name in step_api_names:
        assert hasattr(module, name), f"HALT_NO_STEP_API module lacks {name}"


def test_winner_manifest_operator_base_id_matches_module() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    module = importlib.import_module(manifest["winner_operator_module"])

    assert manifest["operator_base_id"] == module.operator_base_id
    assert manifest["operator_base_id"] == "winner_kernel_v1"
```

- [ ] **Step 2: Run the contract test and verify the right failure**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_winner_operator_adapter.py -q
```

Expected if current API is unchanged:

```text
FAILED ... HALT_NO_STEP_API missing public_api=['WinnerOperatorAction', 'WinnerOperatorSet', 'apply_winner_action', 'decode_winner_action']
```

If this fails exactly this way, stop implementation and report `HALT_NO_STEP_API`. Prompt1 must expose a step-level public API before PPO training can be truthful.

- [ ] **Step 3: Continue only if Prompt1 public API passes**

Continue only when the test passes without editing PPO production code first. The accepted step-level API must support one full candidate scoring per call and must return enough trace to audit:

```python
{
    "operator_base_id": "winner_kernel_v1",
    "destroy_id": "...",
    "repair_id": "...",
    "q_level": "...",
    "temperature": 100.0,
    "candidate_solution": solution,
    "candidate_obj": 5234.56,
    "accepted": True,
    "actual_evals_added": 1,
    "trace": {...},
}
```

## Task 1: Thin Winner Adapter

**Files:**
- Modify: `solver/rl/dr_alns_ppo/operator_manual.py`
- Test: `solver/rl/tests/test_winner_operator_adapter.py`

- [ ] **Step 1: Add test that forbids local destroy/repair implementation**

Append this test:

```python
from pathlib import Path


def test_operator_manual_is_import_adapter_not_local_reimplementation() -> None:
    source = Path("solver/rl/dr_alns_ppo/operator_manual.py").read_text(encoding="utf-8")

    assert "from setp_solver.search.winner_operators import" in source
    assert "winner_kernel_v1" in source
    forbidden_markers = [
        "def _insertion_options(",
        "def _route_customer_ids(",
        "def _solution_without_customers(",
        "math.exp(-float(delta)",
        "q = min(0.40, max(0.10",
        "_path_repair_delta_score",
    ]
    for marker in forbidden_markers:
        assert marker not in source, f"HALT_OPERATOR_FORK local marker still present: {marker}"
```

- [ ] **Step 2: Run and verify failure against old adapter**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_winner_operator_adapter.py::test_operator_manual_is_import_adapter_not_local_reimplementation -q
```

Expected: fail because old `operator_manual.py` still contains local D1-D5/R1-R3 logic.

- [ ] **Step 3: Replace `operator_manual.py` with a thin adapter**

After the step API exists, replace local implementation with this shape:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from setp_solver.search.winner_operators import (
    WinnerOperatorAction,
    apply_winner_action,
    decode_winner_action,
    operator_base_id,
    winner_operator_module,
)


@dataclass(frozen=True)
class WinnerAdapterTrace:
    operator_base_id: str
    winner_operator_module: str
    destroy_id: str
    repair_id: str
    q_level: int
    temperature: float
    raw_action: tuple[int, ...]


def decode_action(raw: tuple[int, ...] | list[int], *, base_temperature: float) -> WinnerOperatorAction:
    return decode_winner_action(raw, base_temperature=base_temperature)


def apply_action(solution: Any, context: Any, rng: Any, action: WinnerOperatorAction) -> dict[str, Any]:
    result = apply_winner_action(solution, context, rng, action)
    result["operator_base_id"] = operator_base_id
    result.setdefault("trace", {})
    result["trace"]["winner_operator_module"] = winner_operator_module
    result["trace"]["operator_base_id"] = operator_base_id
    return result
```

- [ ] **Step 4: Run adapter test**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_winner_operator_adapter.py -q
```

Expected: pass.

## Task 2: Winner Action Space

**Files:**
- Modify: `solver/rl/dr_alns_ppo/action_space.py`
- Test: `solver/rl/tests/test_action_space.py`

- [ ] **Step 1: Write failing tests for winner action decoding**

Add:

```python
from dr_alns_ppo.action_space import ACTION_SPACE_NVEC, decode_action


def test_v2_action_space_comes_from_winner_api() -> None:
    assert len(ACTION_SPACE_NVEC) == 4
    assert ACTION_SPACE_NVEC[0] >= 1
    assert ACTION_SPACE_NVEC[1] >= 1
    assert ACTION_SPACE_NVEC[2] >= 1
    assert ACTION_SPACE_NVEC[3] == 100


def test_v2_decode_action_returns_winner_operator_base_id() -> None:
    action = decode_action([0, 0, 0, 50], base_temperature=100.0)

    assert action.operator_base_id == "winner_kernel_v1"
    assert action.temperature > 0.0
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_action_space.py -q
```

Expected: fail because old `DecodedAction` has no `operator_base_id` and uses legacy D/R arrays.

- [ ] **Step 3: Implement action decoding through winner API**

Change `action_space.py` to import `decode_winner_action` and expose `ACTION_SPACE_NVEC` from Prompt1. If Prompt1 does not expose an action-space vector, add `HALT_NO_STEP_API` to Task 0 instead of guessing values locally.

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_action_space.py -q
```

Expected: pass.

## Task 3: Worker Uses Imported Winner Operator

**Files:**
- Modify: `solver/rl/dr_alns_ppo/worker.py`
- Test: `solver/rl/tests/test_worker_contract.py`
- Test: `solver/rl/tests/test_winner_operator_adapter.py`

- [ ] **Step 1: Add worker trace audit test**

Add:

```python
from dr_alns_ppo.action_space import decode_action
from dr_alns_ppo.worker_client import WorkerClient


def test_worker_step_reports_winner_operator_base_id() -> None:
    client = WorkerClient("models/data_bundle/generated_instances/verify_20251113", seed=1, max_evals=3)
    try:
        client.reset()
        response = client.step(decode_action([0, 0, 0, 50], base_temperature=100.0))
    finally:
        client.close()

    assert response["ok"] is True
    assert response["operator_base_id"] == "winner_kernel_v1"
    assert response["trace"]["operator_base_id"] == "winner_kernel_v1"
    assert response["trace"]["winner_operator_module"] == "setp_solver.search.winner_operators"
    assert response["actual_evals"] == 1
    assert response["candidate_scores"] == 1
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_worker_contract.py::test_worker_step_reports_winner_operator_base_id -q
```

Expected: fail because old worker does not emit `operator_base_id`.

- [ ] **Step 3: Update worker step**

Change `worker.py` so `JsonlWorker.step()` calls:

```python
winner_result = apply_action(
    state.current_solution,
    state.context,
    state.rng,
    decoded_action,
)
candidate = winner_result["candidate_solution"]
candidate_obj, candidate_summary = self._score_solution(candidate, record_candidate=True)
```

The step response must include:

```python
"operator_base_id": operator_base_id,
"trace": {
    "op": "step",
    "operator_base_id": operator_base_id,
    "winner_operator_module": winner_operator_module,
    "destroy_id": winner_result["trace"]["destroy_id"],
    "repair_id": winner_result["trace"]["repair_id"],
    "temperature": winner_result["trace"]["temperature"],
    "actual_evals_added": 1,
}
```

- [ ] **Step 4: Verify one-step accounting**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_worker_contract.py -q
```

Expected: all worker tests pass and `actual_evals == candidate_scores == eval_budget` at episode end.

## Task 4: V2 Bundle Manifest And Formal Eval Alignment

**Files:**
- Modify: `solver/rl/dr_alns_ppo/bundle_manifest.py`
- Add: `solver/rl/tests/test_v2_manifest_alignment.py`
- Output: `solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json`

- [ ] **Step 1: Add manifest alignment tests**

Create `solver/rl/tests/test_v2_manifest_alignment.py`:

```python
from __future__ import annotations

from dr_alns_ppo.bundle_manifest import build_v2_manifest


def test_v2_formal_eval_uses_100_01_and_l_main_not_euk100_03() -> None:
    manifest = build_v2_manifest()

    eval_names = {item["name"] for item in manifest["formal_eval"]}
    eval_paths = " ".join(item["bundle_dir"] for item in manifest["formal_eval"])

    assert eval_names == {"100-01-24h", "L-main"}
    assert "E-UK100_01__d2_s3_seed1_24h" in eval_paths
    assert "E-UK24h-三班-01" in eval_paths
    assert "E-UK100_03" not in eval_paths


def test_v2_training_excludes_formal_eval_bundles() -> None:
    manifest = build_v2_manifest()

    train_paths = {item["bundle_dir"] for item in manifest["train"]}
    eval_paths = {item["bundle_dir"] for item in manifest["formal_eval"]}
    assert train_paths.isdisjoint(eval_paths)
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_v2_manifest_alignment.py -q
```

Expected: fail until `build_v2_manifest()` exists.

- [ ] **Step 3: Implement `build_v2_manifest()`**

Implement:

```python
def build_v2_manifest() -> dict[str, Any]:
    return {
        "schema_version": "dr-alns-ppo-v2-bundle-manifest.v1",
        "train": [
            {"name": "train-small-1", "bundle_dir": "models/data_bundle/generated_instances/verify_20251113"},
            {"name": "train-100-03", "bundle_dir": "models/data_bundle/generated_instances/E-UK100_03__d2_s3_seed1_24h_20251113"},
        ],
        "formal_eval": [
            {"name": "100-01-24h", "bundle_dir": "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"},
            {"name": "L-main", "bundle_dir": "models/data_bundle/generated_instances/E-UK24h-三班-01"},
        ],
        "held_out_learning": [
            {"name": "E-UK100_03", "bundle_dir": "models/data_bundle/generated_instances/E-UK100_03__d2_s3_seed1_24h_20251113"}
        ],
    }
```

If a listed training bundle does not exist, replace it with another non-formal SETP bundle discovered by `rg --files models/data_bundle/generated_instances`.

- [ ] **Step 4: Write v2 manifest file**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m dr_alns_ppo.bundle_manifest \
  --v2 \
  --output solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json
```

Expected: manifest exists and formal eval contains only `100-01-24h` and `L-main`.

## Task 5: Random-Action Winner Base Self-Check

**Files:**
- Modify: `solver/rl/dr_alns_ppo/baselines.py`
- Modify: `solver/rl/dr_alns_ppo/report_smoke.py`
- Add: `solver/rl/tests/test_v2_self_check_report.py`
- Output: `solver/reports/dr_alns_ppo_v2/self_check/`

- [ ] **Step 1: Add self-check report test**

Create `solver/rl/tests/test_v2_self_check_report.py`:

```python
from __future__ import annotations

from dr_alns_ppo.report_smoke import self_check_gate


def test_self_check_gate_requires_winner_operator_trace_and_100_01_quality() -> None:
    rows = [
        {
            "algorithm": "random_action",
            "instance": "100-01-24h",
            "best_obj": 4878.0,
            "operator_base_id": "winner_kernel_v1",
            "actual_evals": 16000,
            "feasible": True,
        },
        {
            "algorithm": "random_action",
            "instance": "L-main",
            "best_obj": 8600.0,
            "operator_base_id": "winner_kernel_v1",
            "actual_evals": 16000,
            "feasible": True,
        },
    ]

    gate = self_check_gate(rows, expected_operator_base_id="winner_kernel_v1")

    assert gate["gate"] == "SELF_CHECK_PASS"


def test_self_check_gate_halts_when_operator_trace_missing() -> None:
    rows = [
        {
            "algorithm": "random_action",
            "instance": "100-01-24h",
            "best_obj": 4878.0,
            "operator_base_id": "",
            "actual_evals": 16000,
            "feasible": True,
        }
    ]

    gate = self_check_gate(rows, expected_operator_base_id="winner_kernel_v1")

    assert gate["gate"] == "HALT_OPERATOR_FORK"
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_v2_self_check_report.py -q
```

Expected: fail until `self_check_gate()` exists.

- [ ] **Step 3: Implement `self_check_gate()`**

Implement a pure function with these gates:

```python
def self_check_gate(rows: list[dict[str, Any]], *, expected_operator_base_id: str) -> dict[str, Any]:
    if any(row.get("operator_base_id") != expected_operator_base_id for row in rows):
        return {"gate": "HALT_OPERATOR_FORK"}
    if any(int(row.get("actual_evals", 0)) != 16000 for row in rows):
        return {"gate": "HALT_BUDGET_MISMATCH"}
    if any(not bool(row.get("feasible")) for row in rows):
        return {"gate": "HALT_VIOLATION"}
    hundred = [row for row in rows if row.get("instance") == "100-01-24h"]
    if not hundred or min(float(row["best_obj"]) for row in hundred) > 5200.0:
        return {"gate": "HALT_BASELINE_WIRING"}
    return {"gate": "SELF_CHECK_PASS"}
```

The `5200.0` bound is intentionally loose around the expected winner-kernel neighborhood near 4878; if this proves too strict after honest random-action runs, adjust only with a report-backed reason.

- [ ] **Step 4: Run self-check**

Run random-action on formal eval only:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m dr_alns_ppo.evaluate_policy \
  --manifest solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json \
  --model solver/reports/dr_alns_ppo_v2/dummy_unused_model.zip \
  --eval-budget 16000 \
  --seeds 1,2,3 \
  --output-dir solver/reports/dr_alns_ppo_v2/self_check \
  --jobs 3 \
  --random-only
```

Expected: `SELF_CHECK_PASS` before any PPO training. If the CLI still requires a model for random-only mode, implement `--random-only` first using TDD.

## Task 6: PPO Smoke Training On Winner Base

**Files:**
- Modify: `solver/rl/dr_alns_ppo/train_ppo.py`
- Modify: `solver/rl/dr_alns_ppo/evaluate_policy.py`
- Output: `solver/reports/dr_alns_ppo_v2/smoke_100k/`

- [ ] **Step 1: Add config guard test**

Add a test to reject old v1 output roots:

```python
from pathlib import Path

from dr_alns_ppo.train_ppo import validate_v2_training_args


def test_v2_training_rejects_old_report_root() -> None:
    result = validate_v2_training_args(Path("solver/reports/dr_alns_ppo/smoke_100k"))

    assert result["gate"] == "HALT_OLD_PPO_ARTIFACT_ROOT"
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests -q
```

Expected: fail until guard exists.

- [ ] **Step 3: Train 100k only after self-check pass**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m dr_alns_ppo.train_ppo \
  --manifest solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json \
  --timesteps 100000 \
  --eval-budget 16000 \
  --seed 1 \
  --output-dir solver/reports/dr_alns_ppo_v2/smoke_100k \
  --vec-env subproc \
  --n-steps 1024 \
  --batch-size 256 \
  --n-epochs 5 \
  --learning-rate 3e-4
```

Long-run probe cadence: check after 10-15 minutes, then every 30-60 minutes if stable.

- [ ] **Step 4: Evaluate 100k model**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m dr_alns_ppo.evaluate_policy \
  --manifest solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json \
  --model solver/reports/dr_alns_ppo_v2/smoke_100k/model.zip \
  --eval-budget 16000 \
  --seeds 1,2,3 \
  --output-dir solver/reports/dr_alns_ppo_v2/smoke_100k/eval \
  --jobs 3
```

Expected gates:

- PPO beats `random_action` on `100-01-24h`.
- PPO is in the winner-kernel neighborhood, or the report says exactly how far away it is.
- Every row has `operator_base_id=winner_kernel_v1`.
- Every row has `actual_evals=16000`.

If PPO does not beat random: stop with `HALT_RANDOM`.

## Task 7: Fair Comparison Report

**Files:**
- Modify: `solver/rl/dr_alns_ppo/report_smoke.py`
- Modify: `solver/rl/dr_alns_ppo/baselines.py`
- Output: `solver/reports/dr_alns_ppo_v2/comparison/`

- [ ] **Step 1: Add report test for required columns**

Add:

```python
from dr_alns_ppo.report_smoke import required_v2_comparison_columns


def test_v2_comparison_columns_include_audit_and_fairness_fields() -> None:
    columns = set(required_v2_comparison_columns())

    assert "operator_base_id" in columns
    assert "actual_evals" in columns
    assert "winner_kernel_best_obj" in columns
    assert "fair_sa_best_obj" in columns
    assert "gap_vs_fair_sa_pp" in columns
    assert "gap_vs_winner_kernel_pp" in columns
    assert "violation_count" in columns
```

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_v2_self_check_report.py -q
```

- [ ] **Step 3: Implement comparison report**

The report must include:

```text
algorithm, instance, seed, total_cost, actual_evals, candidate_scores,
operator_base_id, feasible, violation_count,
winner_kernel_best_obj, fair_sa_best_obj,
gap_vs_winner_kernel_pp, gap_vs_fair_sa_pp,
wilcoxon_p_vs_fair_sa, wilcoxon_p_vs_winner_kernel
```

Baseline sources:

- Winner kernel: `setp_solver.search.winner_operators.run_winner_kernel`.
- Fair SA: `solver/reports/alns_crush_v2` fair-SA reference, not the weaker old Phase2 SA.

- [ ] **Step 4: Produce 10-seed formal comparison**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m dr_alns_ppo.evaluate_policy \
  --manifest solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json \
  --model solver/reports/dr_alns_ppo_v2/smoke_100k/model.zip \
  --eval-budget 16000 \
  --seeds 1,2,3,4,5,6,7,8,9,10 \
  --output-dir solver/reports/dr_alns_ppo_v2/comparison/formal_10seed \
  --jobs 6
```

Expected: comparison rows for PPO, random-action, winner kernel, and fair SA on `100-01-24h` plus `L-main`.

## Task 8: Pilot Gate

**Files:**
- Output: `solver/reports/dr_alns_ppo_v2/pilot_1m/`
- Output: `solver/reports/dr_alns_ppo_v2/pilot_2m/`

- [ ] **Step 1: Start only if 100k gate passes**

Required gate:

```text
smoke_100k gate == SMOKE_PASS
ppo_mean_total_cost < random_action_mean_total_cost on 100-01-24h
all rows operator_base_id == winner_kernel_v1
all rows actual_evals == 16000
```

- [ ] **Step 2: Train 1M pilot**

Run:

```bash
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m dr_alns_ppo.train_ppo \
  --manifest solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json \
  --timesteps 1000000 \
  --eval-budget 16000 \
  --seed 1 \
  --output-dir solver/reports/dr_alns_ppo_v2/pilot_1m \
  --vec-env subproc
```

- [ ] **Step 3: Evaluate pilot**

Run the Task 7 formal 10-seed comparison with model `pilot_1m/model.zip`.

Acceptance:

- If PPO matches winner kernel within a small report-declared band and beats fair SA on `100-01`, mark `PILOT_MATCH_KERNEL`.
- If PPO is far below winner kernel but beats random, mark `PILOT_FUTURE_WORK`.
- If PPO loses to random, mark `HALT_RANDOM`.

## Verification Checklist

- [ ] `PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests -q` passes.
- [ ] `PYTHONPATH=solver/src python -m unittest discover -s solver/tests -p 'test_*.py'` still passes after any shared test additions.
- [ ] `rg -n "def _insertion_options|_path_repair_delta_score|math.exp\\(-float\\(delta\\)|q = min\\(0\\.40" solver/rl/dr_alns_ppo/operator_manual.py` returns no matches.
- [ ] Every v2 output row includes `operator_base_id=winner_kernel_v1`.
- [ ] No v2 output is written under `solver/reports/dr_alns_ppo/`.
- [ ] Formal comparison instances are exactly `100-01-24h` and `L-main`.
- [ ] `E-UK100_03` appears only in training or held-out learning metadata, never in the formal comparison table.

## Self-Review

Spec coverage:

- Direct import/reuse of Prompt1 winner module is covered by Tasks 0-3.
- No local operator fork is covered by Task 1 and the grep verification.
- Self-check before training is covered by Task 5.
- Formal eval alignment to `100-01 + L-main` is covered by Task 4 and Task 7.
- 100k smoke and 1-2M pilot gates are covered by Tasks 6 and 8.
- Fair comparison against winner kernel and fair SA is covered by Task 7.
- Escape gates `HALT_NO_STEP_API`, `HALT_OPERATOR_FORK`, `HALT_BASELINE_WIRING`, `HALT_RANDOM`, and `PILOT_FUTURE_WORK` are explicitly named.

Placeholder scan:

- No `TBD`, `TODO`, or "similar to" placeholders remain.
- The plan intentionally stops at Task 0 if the current full-run-only public API is not expanded to a step-level API. This is not a placeholder; it is a correctness gate.

Type consistency:

- `operator_base_id` is consistently `winner_kernel_v1`.
- `winner_operator_module` is consistently `setp_solver.search.winner_operators`.
- Formal eval names are consistently `100-01-24h` and `L-main`.
