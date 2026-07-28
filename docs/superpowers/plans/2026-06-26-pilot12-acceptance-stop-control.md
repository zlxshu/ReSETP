# Pilot12 Acceptance/Stop Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate the next x86 DR-ALNS rescue path by adding an evidence-first acceptance/stop control surface, proving it has measurable headroom before any long training, and only then training a small policy that must beat the best static/tuned meta baseline.

**Architecture:** This remains the x86 `dr-x86` lane. M1 09s alignment is only a semantic bug shield; it is not the mission. The mission is to make DR-ALNS effective by redesigning the learner interface identified by Pilot11, starting with acceptance/stop control because literature and reference code expose acceptance and stopping as explicit search-control levers while current ReSETP block PPO does not.

**Tech Stack:** Windows PowerShell, `D:\ReSETP`, PPO driver `C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe`, solver worker `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`, NumPy `2.3.5`, pytest, current `dr_alns_ppo` async PPO lane, `setp_solver.search.winner_operators`, local Zotero/literature dumps, and reference code under `Reference Algorithm/` plus `solver/reports/.../literature_materials/`.

---

## Non-Negotiable Direction

This plan inherits the x86 DR line, not the M1 paper-backbone line. M1 09s solved a solver-semantics bug: Goeke `Q=3650`, `B=80`, and physical-vehicle multi-trip counting. x86 synchronized that fix to avoid debugging against wrong semantics. The next work must not drift into M1 E2/T3 paper-baseline production.

The accumulated DR evidence is binding. Pilot08 showed healthy curriculum PPO can still end as `WEAK` against AlphaUCB-like search. Pilot09 showed operator selection has no reliable headroom, but search-parameter control has static headroom. Pilot10 showed dynamic `block_meta` does not beat best static meta, so q/threshold/exploration alone is not a learning contribution. Pilot11 gate is `NEEDS_INTERFACE_REDESIGN`; the next legitimate DR step is interface redesign, with Path A acceptance/stop control first.

The instance scope is binding too. Pilot12 must not use the old 100c-only Pilot08 split as its main diagnostic set. The user's target problem is the three-shift setting, and 100c is already expensive enough to hide cheap interface signals. Phase A/B use three-shift E2 benchmark bundles:

- Train-probe: `e2-threeshift-50c-01`, `e2-threeshift-50c-02`, `e2-threeshift-50c-03`.
- Held-probe: `e2-threeshift-75c-01`, `e2-threeshift-75c-02`, `e2-threeshift-75c-03`.
- Pressure only after a pass: `e2-threeshift-100c-*`.

The broader M1/E2 family has 23 representative `-01` main cases across vanilla, multidepot, and three-shift categories, but Pilot12 must not mix non-three-shift cases into the DR rescue gate.

Every future learning claim must compare against best static/tuned meta, not default AlphaUCB, SA, random, or M1 absolute numbers. A trained model is not a success unless it beats the accepted baseline under the quantitative gates below.

## Source Material That Must Be Used

Before code or experiment work, read and cite these local materials in the Pilot12 evidence report:

- `HANDOFF.md`, especially the x86 DR entries for Pilot07 through Pilot11 and the M1 09s sync note.
- `docs/handoff/dr_alns_project_rhythm_manual.md`.
- `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot11_interface_audit/pilot11_interface_audit.md`.
- `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot10/pilot10_final_report.md`.
- `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot09/rescue_full/literature_review.md`.
- `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/literature_materials/dr_alns_deep_read_master_20260626.md`.
- `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/literature_materials/dr_alns_gap_diagnosis_20260626.md`.
- `Reference Algorithm/DR-ALNS@RobbertReijnen/` if present.
- `Reference Algorithm/ALNS-7.0.0@N-Wouda/alns/accept/` and `Reference Algorithm/ALNS-7.0.0@N-Wouda/alns/stop/`.
- `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/literature_materials/external_repos/ppo-alns/`.

If a listed source is missing, write it in the evidence report as `MISSING_SOURCE` and continue only if enough local evidence remains to justify the next diagnostic. Do not replace missing literature with intuition.

## Files And Responsibilities

- Create `solver/rl/dr_alns_ppo/pilot12_acceptance_stop_tools.py`.
  This file owns no-training audits, static acceptance/stop probes, row gates, relative summaries, and Pilot12 report generation. It must not change solver semantics.

- Create `solver/rl/tests/test_pilot12_acceptance_stop_tools.py`.
  This file covers evidence schema, row gates, relative-percent signs, acceptance/stop policy mapping, halt/pass gate classification, and report rendering.

- Modify `solver/rl/dr_alns_ppo/action_space.py` only if Phase B passes.
  Add an opt-in action-space extension for acceptance/stop control. Default `BLOCK_ACTION_NVECS` behavior must remain unchanged unless a new mode is explicitly requested.

- Modify `solver/rl/dr_alns_ppo/block_env.py` only if Phase B passes.
  Add an opt-in environment mode such as `accept_stop_mode=True`, expose the new action head, include acceptance/stop context in observations if the diagnostic proves it is needed, and keep default behavior unchanged.

- Modify `solver/rl/dr_alns_ppo/worker.py` only if Phase B passes.
  Thread acceptance/stop decisions through `block_step` behind an explicit mode flag. The existing default threshold rule must remain byte-for-byte behaviorally equivalent when the flag is off.

- Modify `solver/rl/dr_alns_ppo/train_async_block_ppo.py` only if Phase B passes.
  Add CLI/config propagation for the new opt-in mode. Existing `train`, `audit`, and `self-check` behavior must remain default-compatible.

- Create ignored outputs under `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot12/`.
  Curated small reports may be force-added only when the user asks to commit.

## Phase 0: Preflight And Evidence Lock

- [ ] **Step 0.1: Verify x86 lane and clean state**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
git rev-parse --abbrev-ref HEAD
git status --short --untracked-files=all
git rev-parse HEAD origin/dr-x86
```

Expected: branch is `dr-x86`; worktree is clean or contains only user-approved docs; local and origin should normally match before starting. If not, stop and report exact output.

- [ ] **Step 0.2: Verify runtime split**

Run:

```powershell
Set-Location -LiteralPath "D:\ReSETP"
$env:SETP_WORKER_PYTHON="C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
$env:PYTHONPATH="D:\ReSETP\models\src;D:\ReSETP\solver\rl;D:\ReSETP\solver\src"
& "C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe" - <<'PY'
import sys, numpy
print(sys.executable)
print(numpy.__version__)
PY
```

Expected: worker path is exactly `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`; NumPy is `2.3.5`. If not, stop.

- [ ] **Step 0.3: Write Pilot12 evidence ledger**

Create `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot12/evidence_ledger.md` summarizing the specific source files read, the acceptance/stop ideas extracted from literature/reference code, and how those ideas map to ReSETP. The ledger must include: source path, exact local claim used, ReSETP implication, and whether it supports Phase A, B, C, or final validation.

Quantitative gate: at least 6 local evidence items must be recorded, including at least 1 Pilot08-10 result, 1 Pilot11 interface gap, 1 ALNS acceptance/stop reference-code item, and 1 DRL/ALNS literature item. If fewer than 6 are available, write `HALT_PILOT12_EVIDENCE`.

## Phase A: No-Training Acceptance/Stop Observability Audit

- [ ] **Step A.1: Add tests for the audit schema**

Create `solver/rl/tests/test_pilot12_acceptance_stop_tools.py` with tests requiring these public functions:

```python
from dr_alns_ppo.pilot12_acceptance_stop_tools import (
    acceptance_row_gate,
    classify_acceptance_observability,
    paired_relative_percent,
    render_pilot12_report,
)
```

Required test cases:

```python
def test_paired_relative_percent_positive_means_policy_better():
    assert paired_relative_percent(policy_cost=90.0, baseline_cost=100.0) == 10.0

def test_acceptance_row_gate_rejects_worker_drift():
    row = {
        "worker_python_executable": "C:/bad/python.exe",
        "worker_numpy_version": "2.3.5",
        "violation_count": 0,
        "best_obj": 100.0,
        "actual_evals": 600,
        "eval_budget": 600,
        "elapsed_seconds": 1.0,
    }
    ok, reason = acceptance_row_gate(row)
    assert not ok
    assert "worker" in reason

def test_observability_gate_passes_when_acceptance_has_variance_and_cost_signal():
    rows = [
        {"accepted_rate": 0.10, "accepted_worse_rate": 0.01, "best_obj": 100.0, "policy_label": "strict"},
        {"accepted_rate": 0.45, "accepted_worse_rate": 0.12, "best_obj": 96.0, "policy_label": "moderate"},
        {"accepted_rate": 0.80, "accepted_worse_rate": 0.30, "best_obj": 103.0, "policy_label": "loose"},
    ]
    gate = classify_acceptance_observability(rows)
    assert gate["status"] == "PASS_ACCEPTANCE_OBSERVABLE"
```

- [ ] **Step A.2: Implement no-training audit tooling**

Implement `pilot12_acceptance_stop_tools.py` so it can collect and summarize block-level acceptance data without training. It should support a CLI:

```powershell
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" `
  -m dr_alns_ppo.pilot12_acceptance_stop_tools audit `
  --threeshift-probe `
  --output-dir solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot12/audit_accept_stop `
  --eval-budget 600 `
  --block-size 32 `
  --seeds 1,2,3 `
  --jobs 1
```

The audit rows must include: bundle, seed, policy label, eval budget, block size, actual evals, elapsed seconds, worker path, NumPy version, violation count, best objective, current objective, accepted rate, rejected rate, accepted-worse rate, improved-current rate, improved-best rate, stagnation ratio, and stop reason.

- [ ] **Step A.3: Run Phase A audit**

Run the audit on three-shift 50c and 75c first, not on 100c or all final cases. Use `eval_budget=600`, `block_size=32`, seeds `1,2,3`, jobs `1`.

Quantitative PASS gate:

- Every row worker path is py313 and NumPy is `2.3.5`.
- Every row has `actual_evals == eval_budget`.
- Every row has zero violations, feasible finite objective, and elapsed time greater than zero.
- Across static acceptance policies, accepted-rate spread is at least `0.20`.
- At least one non-default acceptance-threshold policy changes mean best objective by at least `0.30%` on held-probe 75c relative to best static meta.
- No policy creates systematic infeasibility or non-finite objective.

If any runtime/gate row fails, write `HALT_PILOT12_ACCEPTANCE_AUDIT`. If rows are valid but acceptance/stop does not change acceptance behavior or objective meaningfully, write `HALT_NO_ACCEPTANCE_SIGNAL`.

## Phase B: Static Acceptance/Stop Headroom Probe

- [ ] **Step B.1: Define static policies**

The static probe must compare these implemented labels:

- `best_static_meta`: current Pilot10 best static meta, q `0.40`, threshold `0.0025`, exploration `0.15`.
- `strict_accept`: no worse-candidate acceptance, q `0.40`, threshold `0.0`, exploration `0.15`.
- `loose_accept`: q `0.40`, threshold `0.0075`, exploration `0.15`.
- `very_loose_accept`: q `0.40`, threshold `0.02`, exploration `0.15`.

These labels are currently unimplemented and must be reported as `UNIMPLEMENTABLE_STATIC_POLICY`, not silently approximated: `early_stop`, `adaptive_stop`, and `restart_on_stagnation`. The current worker exposes threshold acceptance but does not expose early stop/restart control without a later opt-in interface change.

- [ ] **Step B.2: Run static probe**

Run:

```powershell
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" `
  -m dr_alns_ppo.pilot12_acceptance_stop_tools static-probe `
  --threeshift-probe `
  --output-dir solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot12/static_probe `
  --eval-budget 1500 `
  --block-size 32 `
  --seeds 1,2,3,4,5 `
  --jobs 1
```

Quantitative PASS gate:

- `best_static_meta` rows reproduce Pilot10-style row gates: py313, NumPy `2.3.5`, zero violation, finite objective.
- At least one acceptance-threshold policy beats `best_static_meta` on held-probe 75c by mean relative `>= +0.50%` with paired wins ratio `>= 0.60`.
- The same policy is not worse than `-0.25%` on train-probe 50c.
- Runtime remains within `1.50x` of `best_static_meta` for the same budget.

If this fails, write `HALT_ACCEPT_STOP_NO_HEADROOM` and stop. Do not train.

## Phase C: Opt-In Acceptance/Stop Interface Implementation

Only start this phase if Phase B passes.

- [ ] **Step C.1: Add action-space tests**

Add tests that default block action space remains `(7, 4, 5, 4, 4)` and the new opt-in mode adds exactly one acceptance/stop head. The test must require the best static meta action remains representable.

- [ ] **Step C.2: Implement opt-in action head**

Modify `action_space.py` with new constants such as:

```python
BLOCK_ACCEPT_STOP_CHOICES = ("default", "strict", "moderate", "loose", "adaptive_stop")
```

Add a decoder for the opt-in mode without changing `decode_block_action()` default behavior. Default existing tests must still pass without callers knowing about the new head.

- [ ] **Step C.3: Thread opt-in mode through environment and worker**

Modify `block_env.py` and `worker.py` behind a flag such as `accept_stop_mode=True`. Required behavior:

- When off, existing trace and acceptance results remain unchanged.
- When on, action head controls acceptance/stop behavior.
- Every trace row records requested accept/stop label, accepted-worse count, stopped-early count, and stop reason.

- [ ] **Step C.4: Add trainer CLI propagation**

Modify `train_async_block_ppo.py` with `--accept-stop-mode`, and write it to config JSON. The default must be false.

Required tests:

```powershell
& "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe" -m pytest `
  solver\rl\tests\test_async_block_ppo.py `
  solver\rl\tests\test_pilot12_acceptance_stop_tools.py -q
```

Expected: all selected tests pass.

## Phase D: Smoke Training Only

Only start this phase if Phase C tests pass.

- [ ] **Step D.1: Run short smoke**

Run one short curriculum smoke using the Pilot08 curriculum manifest, `--accept-stop-mode`, `num_actors=4`, `eval_budget=600`, `block_size=32`, `timesteps=240`, and output `pilot12/smoke_accept_stop`.

Quantitative smoke gate:

- `train_bundles` length is 12.
- At least 12 unique curriculum bundles are touched.
- `route -> energy` transition appears.
- All episodes zero violation.
- Worker path py313, NumPy `2.3.5`.
- `resolved_device` or `device` is cuda.
- The action log shows at least 2 distinct acceptance/stop choices used.

If this fails, write `HALT_ACCEPT_STOP_SMOKE`.

## Phase E: Bounded Pilot Training

Only start this phase after smoke passes and the user explicitly authorizes a bounded training run.

- [ ] **Step E.1: Train bounded accept-stop policy**

Use Pilot08 curriculum settings as the base: `num_actors=6`, `eval_budget=600`, `block_size=32`, `device=cuda`, route/energy/carbon schedule, stable phase LR/clip/entropy settings from B2, and output `pilot12/train_final`. Use checkpoints every 10 updates. Do not exceed the B2 wall-clock scale unless separately authorized.

Training health gates:

- At least `8000` episodes unless stopped by explicit halt.
- At least `300` PPO updates.
- All episodes zero violation.
- Worker path py313 and NumPy `2.3.5`.
- Entropy not collapsed: final entropy must be at least `30%` of first-10-update median, unless a deterministic policy is explicitly intended.
- At least 3 distinct acceptance/stop choices remain active in the final 25% of updates.
- Shared baseline remains enabled.
- route, energy, and carbon phases are all reached.

If any health gate fails, write `HALT_ACCEPT_STOP_TRAINING_HEALTH` and do not evaluate performance.

## Phase F: Same-Machine x86 Validation

Only start this phase after Phase E health passes.

- [ ] **Step F.1: Select checkpoint on held-out**

Cheap-screen all checkpoints on held-probe `e2-threeshift-75c-*` with budget 600 seed 1. Refine top 3 plus final on the same held-probe bundles with a calibrated 75c budget, seeds `1,2,3`. Select by lowest mean best objective. Record final rank.

- [ ] **Step F.2: Formal x86 comparison**

Compare `accept_stop_best` against `best_static_meta` on three-shift 50c train-probe and 75c held-probe with seeds `1..5`, calibrated same-budget settings, block size `32`, jobs `1`. If and only if this passes, run three-shift 100c pressure rows. Also report default AlphaUCB, random, SA, and official winner as context, but they are not the success bar.

Quantitative success gate for a learning contribution:

- On three-shift 50c train-probe: mean relative vs `best_static_meta` is `> +1.00%` and wins ratio `>= 0.80`.
- On three-shift 75c held-probe: mean relative vs `best_static_meta` is `> +1.00%` and wins ratio `>= 0.80`.
- One-sided Wilcoxon on held-probe 75c has `p <= 0.05` when enough paired rows exist.
- Three-shift 100c pressure is reported as generalization evidence; it cannot rescue failure on 50c/75c.
- Runtime for the learned policy must be no more than `1.25x` `best_static_meta` under the same budget. If runtime is higher, report a runtime caveat and do not call the result strong.

Verdict mapping:

- `PROMISING_ACCEPT_STOP`: train and held-out gates pass, but runtime or formal evidence is mixed.
- `STRONG_ACCEPT_STOP`: train and held-out gates pass, held-out Wilcoxon passes, 100c pressure is non-negative if run, and runtime is within `1.25x`.
- `WEAK_ACCEPT_STOP`: training is healthy but gates fail.
- `HALT_ACCEPT_STOP`: any row gate, worker, feasibility, objective, or runtime validity gate fails.

## Phase G: Main-Case Readiness, Not M1 Drift

If Phase F is `PROMISING_ACCEPT_STOP` or stronger, prepare a handoff for later main-case validation. This is not a pivot into M1 work. It is a readiness package.

Read the M1 line's 23 main-case manifest only at this stage. The final aspirational target is average relative improvement `>= +10%` over the current second-best algorithm, with wins on at least `18/23` representative main cases if that broader package is later used, zero violations, same worker semantics, and no M1/x86 absolute-number mixing. The DR rescue gate itself remains three-shift-first. If this target is not met later, the result can still be a publishable future-work candidate only if Phase F proves real learning against best static meta.

## Communication And Runtime Cadence

Short diagnostics: report at phase boundaries and failures.

Stable long training: low-frequency status only, using `已经做完 / 正在做 / 之后做什么 / 还要多久 / 有没有偏离预期`. Increase frequency only on errors, memory pressure, worker drift, or gate failure.

Never start Phase E or Phase F without explicit user authorization after Phase B/C/D evidence is available.

## Commit Policy

Commit only after verified tests or reports:

- Phase A/B commit: code/tests/report only, message `[x86/DR] Audit acceptance-stop control headroom`.
- Phase C/D commit: opt-in interface code/tests/smoke report, message `[x86/DR] Add opt-in accept-stop PPO interface`.
- Phase E/F commit: curated model/report only if training and validation complete, message `[x86/DR] Evaluate accept-stop DR rescue`.

Do not commit raw logs, long partial CSVs, all checkpoints, or generated data bundles unless the user explicitly asks for evidence preservation.

## Protected Boundaries

Do not modify `cost.py`, `check.py`, `search/evaluation.py`, protected feasibility semantics, vehicle-count semantics, or M1 paper report paths.

Do not compare x86 absolute objectives to M1 absolute objectives.

Do not call a default-AlphaUCB win a DR success.

Do not rerun same-shape block PPO or block_meta long training.

Do not weaken manifest validation, worker py313 gates, NumPy `2.3.5` gates, zero-violation gates, or budget/runtime row gates.

Do not proceed past a failed gate by changing thresholds mid-run. Write the halt report and stop.

## Goal-Mode Start Prompt

Use this prompt to start execution:

```text
Goal: Execute Pilot12 Acceptance/Stop Control on D:\ReSETP / dr-x86 to rescue DR-ALNS by redesigning the learner interface, not by repeating same-shape PPO. Use the existing literature/repository evidence from Pilot09-11 and reference code. Start with Phase 0 and Phase A only: preflight, evidence ledger, no-training acceptance/stop observability audit, tests, and halt/pass report. Do not train, do not evaluate performance claims, and do not modify solver semantics unless Phase B later passes and I explicitly authorize implementation. Keep x86 as the DR lane; M1 alignment is only a semantic bug shield. Quantitative gates are those in docs/superpowers/plans/2026-06-26-pilot12-acceptance-stop-control.md. Stop on any failed gate and report exact evidence.
```
