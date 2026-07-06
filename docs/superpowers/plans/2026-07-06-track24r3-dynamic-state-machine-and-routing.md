# Track24-R3 Dynamic State Machine And Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide whether Track24-R dynamic DR is a real algorithmic direction or only a legality cleanup, by running a fixed-code Stage3 confirmation and, in parallel, correcting the rolling dynamic decision semantics into an explicit request lifecycle state machine. Stop PPO/Stage4 unless fixed-code Stage3 is fully healthy and delivers at least 2 percentage points mean reduction.

**Architecture:** Four bounded workstreams run under a shared health gate. `DYN` confirms Track24-R2 on fixed code and refactors dynamic rolling semantics. `E2` probes route-compression/stability exceptions as an alternate main paper route. `CARBON` only audits whether carbon/charging actions have real mechanism value or are proxy labels. `HEALTH` enforces evidence hygiene: no mixed-code breakthrough claims, no protected solver/checker drift, no under-eval OK rows, no unsafe resume, and no worker/hash pollution.

**Tech Stack:** Python 3.13, pytest, PowerShell, current repo `D:\ReSETP`, solver package under `solver/src/setp_solver`, DR audit runner under `solver/rl/dr_alns_ppo`, reports under `solver/reports/dr_alns_ppo_v3`.

---

## Non-Negotiable Facts And Stop Rules

- [ ] Treat current Track24-R2 result as legality evidence only, not as proof that the DR direction works. The prior failure-only result was mixed-code reference evidence: carried rows from old code plus rerun failed rows.
- [ ] Do not run PPO training, Stage4 imitation, or bandit follow-up until a full fixed-code 260-row Stage3 is healthy and mean reduction is at least `2.0` percentage points.
- [ ] Do not modify protected semantics files without explicit approval: `solver/src/setp_solver/cost.py`, `solver/src/setp_solver/check.py`, `solver/src/setp_solver/search/evaluation.py`, `solver/src/setp_solver/baselines/metaheuristic_baselines.py`, and any TeX source.
- [ ] Stop and report immediately on any protected diff, TeX diff, anchor drift, worker death, hash pollution, unsafe resume, output structure anomaly, or under-eval row marked OK.
- [ ] If fixed-code Stage3 is unhealthy, stop the dynamic line and report the first failing payload samples.
- [ ] If fixed-code Stage3 is healthy but mean reduction is below `2.0pp`, stop dynamic PPO and route effort to E2/E6 paper-safe mechanisms.
- [ ] If the observed gain is mainly from `stage_budget_event_density`, describe it as budget allocation / anytime-control evidence, not as reserve/defer/charging mechanism evidence.
- [ ] If `capacity_reserve_*` or `ev_charging_slack_reserve_*` remain proxy semantics, either rename them in reports or implement true depot-capacity / SOC-slack features before any mechanism claim.

## Long-Run Protocol

- [ ] All long-run logs go to files under the active report directory, for example `logs/full_run.log`.
- [ ] Chat updates during long runs must be a single JSON line or at most three summary lines.
- [ ] Probe normal long runs at most once every 15 minutes.
- [ ] Only report when a phase completes, a new large instance or phase starts, rows increase by at least `30`, a fail/HALT/worker death/protected diff/hash/resume issue occurs, or user decision is needed.
- [ ] Use this status shape for every long-run update:

```json
{"phase":"...","rows":"current/expected","ok":0,"fail":0,"halt":false,"current_instance":"...","workers":0,"decision_needed":false}
```

---

## Workstream DYN-A: Fixed-Code Track24-R Stage3 Confirmation

### Purpose

This is the first hard gate. It answers whether the Track24-R legality fix survives a clean full fixed-code 260-row Stage3 run. It must not reuse old healthy rows for a breakthrough claim.

### Tasks

- [ ] Confirm clean branch state before running:

```powershell
Set-Location D:\ReSETP
git status --short --branch
git diff --name-only
```

- [ ] Verify the current commit contains Track24-R2 legality fixes and no local report-only drift:

```powershell
git log --oneline -5
git diff -- solver/src/setp_solver/search/dynamic.py solver/tests/test_formal_runner.py solver/rl/dr_alns_ppo/track24_breakthrough_audit.py
```

- [ ] Create a fresh report directory and never merge old Track24-R rows into its final verdict:

```text
solver/reports/dr_alns_ppo_v3/final_track24r3_full_fixed/
```

- [ ] Run Stage3 only plus its required summaries. Do not run Stage4/PPO in this command. Use the runner's existing resume mechanism only if the new directory already contains a verified partial fixed-code run.

```powershell
$env:PYTHONPATH = "solver\rl;solver\src;models\src"
C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe -m dr_alns_ppo.track24_breakthrough_audit run `
  --output-dir solver/reports/dr_alns_ppo_v3/final_track24r3_full_fixed `
  --stages 0,1,2,3,5,6,7
```

- [ ] While running, monitor only summarized state. Do not paste full CSV or logs into chat.

- [ ] After run completion, read and record only these evidence files:

```text
solver/reports/dr_alns_ppo_v3/final_track24r3_full_fixed/stage3_dynamic_oracle_rows.csv
solver/reports/dr_alns_ppo_v3/final_track24r3_full_fixed/track24_breakthrough_summary.json
solver/reports/dr_alns_ppo_v3/final_track24r3_full_fixed/track24_breakthrough_summary.md
```

- [ ] Compute and write a compact fixed-code verdict to:

```text
solver/reports/dr_alns_ppo_v3/final_track24r3_full_fixed/track24r3_fixed_code_gate.json
solver/reports/dr_alns_ppo_v3/final_track24r3_full_fixed/track24r3_fixed_code_gate.md
```

The JSON must include:

```json
{
  "stage3_rows": 260,
  "health_failure_count": 0,
  "mixed_code_result": false,
  "mean_reduction_pp": 0.0,
  "dominant_action_family": "",
  "stage4_allowed": false,
  "ppo_allowed": false,
  "verdict": ""
}
```

### Acceptance Gate

- [ ] Pass only if `stage3_rows=260`, `health_failure_count=0`, `mixed_code_result=false`, no worker/hash/resume/protected issues, and output structure is valid.
- [ ] If `mean_reduction_pp < 2.0`, set `verdict=STOP_DYNAMIC_DR_WEAK_SIGNAL`, `stage4_allowed=false`, `ppo_allowed=false`.
- [ ] If `mean_reduction_pp >= 2.0`, set `verdict=DYNAMIC_SIGNAL_REQUIRES_MECHANISM_AUDIT`, `stage4_allowed=true` only for imitation/contextual-bandit planning, `ppo_allowed=false`.

---

## Workstream DYN-B: Dynamic Request Lifecycle State Machine

### Purpose

Track24-R2 fixed final pending and commit replay bugs. It did not fully fix the underlying semantic weakness: rolling dynamic requests are still centered around `active_ids`. The runner needs an explicit lifecycle state for each customer so a policy cannot silently delete, incorrectly defer, or mislabel requests.

### Target Semantics

Each dynamic customer must be in exactly one lifecycle category at each stage:

```text
unreleased -> active_unplanned -> planned_now -> committed_served
                         |              |
                         v              v
                    deferred_pending -> repaired_final
                         |
                         v
                   cancelled_or_invalid
```

`active_ids` remains supported for backward compatibility, but new code and reports should prefer:

- `mandatory_ids`: active requests that must be served in the current stage because they are already pending, close to deadline, locked by a previous plan, or unsafe to defer.
- `plan_now_ids`: active requests selected for current-stage service.
- `defer_ids`: active requests explicitly deferred into pending state.
- `pending_customer_ids`: accumulated deferred requests visible in `RollingPolicyContext`.
- `committed_customer_ids`: requests already executed and no longer eligible for replanning.

### Tests First

Add tests in `solver/tests/test_formal_runner.py` before production edits:

- [ ] `test_dynamic_policy_decision_explicit_defer_ids_keeps_customer_pending`
- [ ] `test_dynamic_policy_decision_plan_now_ids_preserves_budget_override`
- [ ] `test_dynamic_policy_decision_rejects_overlap_between_plan_now_and_defer`
- [ ] `test_dynamic_mandatory_ids_cannot_be_deferred_by_policy`
- [ ] `test_dynamic_pending_customer_promotes_to_mandatory_near_due_time`
- [ ] `test_dynamic_committed_customer_is_never_replanned`
- [ ] `test_dynamic_lifecycle_trace_has_no_customer_disappearing_between_stages`

Run the RED subset:

```powershell
pytest solver/tests/test_formal_runner.py -k "dynamic_policy_decision or dynamic_mandatory or dynamic_pending or dynamic_committed or dynamic_lifecycle" -q
```

Expected RED behavior:

- [ ] Tests fail because old code lacks explicit `plan_now_ids/defer_ids/mandatory_ids`, not because fixtures or imports are broken.
- [ ] If any test fails for unrelated reasons, fix the test before touching production code.

### Production Changes

Edit only `solver/src/setp_solver/search/dynamic.py` unless tests reveal a narrow runner serialization need.

- [ ] Extend `RollingPolicyDecision`:

```python
@dataclass(frozen=True)
class RollingPolicyDecision:
    active_ids: set[str] | None = None  # legacy alias for plan_now_ids
    plan_now_ids: set[str] | None = None
    defer_ids: set[str] | None = None
    mandatory_ids: set[str] | None = None
    stage_eval_budget: int | None = None
    stage_max_runtime_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] Extend `RollingPolicyContext` with:

```python
pending_customer_ids: set[str]
committed_customer_ids: set[str]
mandatory_customer_ids: set[str]
```

- [ ] Normalize legacy `active_ids` as `plan_now_ids` only when `plan_now_ids` is absent.
- [ ] Preserve budget fields when coercing decisions from both dataclasses and dictionaries.
- [ ] Reject conflicting decisions:

```text
plan_now_ids ∩ defer_ids != empty
defer_ids ∩ mandatory_ids != empty
plan_now_ids contains committed_customer_ids
defer_ids contains committed_customer_ids
unknown ids outside current active/pending set
```

- [ ] Maintain `pending_deferred_ids` as runner state:

```text
pending before stage = previous pending - cancelled - served - invalid
active candidates = newly active + pending before stage
mandatory = pending close to deadline + explicitly locked + unsafe-to-defer
policy plan_now/defer choices are applied only after mandatory guard
served by stage plan is removed from pending
unserved defer_ids remain pending
```

- [ ] Keep Track20/Track24 callbacks compatible by populating legacy `active_ids` in policy traces.
- [ ] Add lifecycle trace fields to every stage payload:

```json
{
  "pending_count_before": 0,
  "pending_count_after": 0,
  "mandatory_count": 0,
  "plan_now_count": 0,
  "defer_count": 0,
  "committed_count": 0,
  "cancelled_removed_count": 0,
  "served_removed_from_pending_count": 0,
  "lifecycle_violation_count": 0,
  "lifecycle_first_violation": null
}
```

### Acceptance Gate

- [ ] New lifecycle tests pass.
- [ ] Existing Track24-R2 tests for final repair, commit chunk, payload counts, and budget preservation still pass.
- [ ] No changes to cost/check/evaluation/baseline semantics.

---

## Workstream DYN-C: Defer Feasibility Guard

### Purpose

A policy must not be allowed to defer a request that is no longer realistically serviceable. This is the real guard separating dynamic control from silent deletion.

### Guard Rules

For every candidate in `defer_ids`, compute conservative feasibility under the current stage instance:

- [ ] Hard time-window guard: if depot-to-customer-to-depot earliest service cannot meet due time, customer is mandatory.
- [ ] Capacity guard: if demand cannot fit any legal vehicle class in the current instance, halt as infeasible evidence rather than defer.
- [ ] Previous pending guard: if a customer has been pending beyond configured age or is near due time, promote to mandatory.
- [ ] Optional EV/SOC guard only if the current instance exposes real SOC/charging features. If not, label EV slack as `proxy_semantics`.

### Tests First

Add tests in `solver/tests/test_formal_runner.py`:

- [ ] `test_dynamic_defer_guard_promotes_customer_with_imminent_due_time`
- [ ] `test_dynamic_defer_guard_halts_on_infeasible_pending_customer`
- [ ] `test_dynamic_defer_guard_does_not_claim_ev_slack_without_soc_feature`

Run:

```powershell
pytest solver/tests/test_formal_runner.py -k "defer_guard" -q
```

### Production Changes

- [ ] Add a private helper in `dynamic.py`:

```python
def _classify_defer_eligibility(
    instance: ProblemInstance,
    customer_ids: set[str],
    *,
    current_time: float,
    pending_ages: Mapping[str, int],
    guard_config: RollingPolicyGuardConfig,
) -> DeferGuardResult:
    ...
```

- [ ] Add `RollingPolicyGuardConfig` with conservative defaults and make it internal unless existing runner configuration already has a suitable place.
- [ ] Include first guard failure details in payload and HALT payloads:

```json
{
  "halt_class": "HALT_DYNAMIC_DEFER_GUARD",
  "customer_id": "C32",
  "reason": "time_window_impossible_after_defer",
  "current_time": 0.0,
  "earliest_service_time": 0.0,
  "due_time": 0.0
}
```

### Acceptance Gate

- [ ] A deferred customer can never disappear from lifecycle accounting.
- [ ] A mandatory customer cannot be deferred by policy output.
- [ ] A truly infeasible pending customer produces HALT evidence, not OK.

---

## Workstream DYN-D: Action Semantics And Report Naming

### Purpose

The paper/report must not claim mechanism semantics the code does not implement. The current risk is that action names such as `capacity_reserve_*` and `ev_charging_slack_reserve_*` may behave as proxy labels rather than true depot capacity or SOC controls.

### Tasks

- [ ] Extend `solver/rl/dr_alns_ppo/track24_breakthrough_audit.py` Stage3 summary with an action-family table:

```text
action_name
selected_count
ok_count
health_fail_count
mean_reduction_pp
mechanism_semantics: true|proxy|unknown
evidence_note
```

- [ ] Mark action semantics as:

```text
stage_budget_event_density -> true_budget_control
defer/request lifecycle actions -> true only after DYN-B/C passes
capacity_reserve_* -> proxy unless depot capacity state is read and enforced
ev_charging_slack_reserve_* -> proxy unless SOC/charging slack state is read and enforced
```

- [ ] Add tests in `solver/rl/tests/test_track24_breakthrough_audit.py`:

```text
test_stage3_summary_reports_action_family_semantics
test_stage3_summary_marks_capacity_reserve_as_proxy_without_capacity_state
test_stage3_summary_does_not_allow_proxy_action_as_mechanism_claim
```

- [ ] If proxy actions are dominant in fixed-code Stage3, write the final summary language as:

```text
The observed gain is an anytime budget/control allocation effect. It is not yet evidence for depot capacity reserve or EV charging slack reserve.
```

### Acceptance Gate

- [ ] No report uses proxy actions as mechanism evidence.
- [ ] If proxy labels remain, downstream Stage4 stays blocked even when mean reduction is above `2pp`.

---

## Workstream E2: Route Compression / Stability Probe

### Purpose

If DYN is weak or only budget-control, the likely paper-safe route is not PPO. It is to find a concrete deterministic mechanism such as route compression, reduced fragmentation, lower reoptimization churn, or fairness-safe repair.

### Input Evidence

Use the documented 100-customer exceptions and current Stage3 route-level outputs. Do not start with a full new campaign.

### Tasks

- [ ] Create a read-only probe:

```text
solver/tools/e2_route_compression_probe.py
```

- [ ] The probe reads existing row payloads and writes:

```text
solver/reports/dr_alns_ppo_v3/final_track24r3_e2_route_compression/e2_route_compression_probe.json
solver/reports/dr_alns_ppo_v3/final_track24r3_e2_route_compression/e2_route_compression_probe.md
```

- [ ] Measure at least these fields by instance/action/seed:

```json
{
  "route_count_delta": 0,
  "mean_route_length_delta": 0.0,
  "total_distance_delta": 0.0,
  "late_violation_delta": 0,
  "capacity_violation_delta": 0,
  "unserved_delta": 0,
  "reoptimization_churn_delta": 0.0,
  "fairness_proxy_delta": 0.0
}
```

- [ ] Identify whether improvement comes from:

```text
route compression
stability / lower churn
more evaluations / budget only
fairness-safe repair
carbon/charging-specific behavior
noise or unhealthy baseline
```

- [ ] Add tests for the probe's parsing and aggregation using small synthetic payloads:

```text
solver/rl/tests/test_e2_route_compression_probe.py
```

Run:

```powershell
pytest solver/rl/tests/test_e2_route_compression_probe.py -q
```

### Acceptance Gate

- [ ] If route compression/stability produces clear healthy gain, prioritize E2 deterministic mechanism over PPO.
- [ ] If fairness-safe repair is the actual source, route to an E6 repair plan.
- [ ] If only budget/evaluation count explains gain, do not call it DR mechanism innovation.

---

## Workstream CARBON: Carbon / Charging Mechanism Audit

### Purpose

Carbon/charging should not consume a large run unless there is local evidence it creates route-level improvement relevant to E2 or E4/E5. This is an audit, not a campaign.

### Tasks

- [ ] Read only existing carbon/charging report artifacts and action traces first. Do not launch a new full run.
- [ ] Create a compact audit script only if existing summaries cannot answer the question:

```text
solver/tools/carbon_charging_mechanism_audit.py
```

- [ ] Write results to:

```text
solver/reports/dr_alns_ppo_v3/final_track24r3_carbon_audit/carbon_charging_mechanism_audit.json
solver/reports/dr_alns_ppo_v3/final_track24r3_carbon_audit/carbon_charging_mechanism_audit.md
```

- [ ] Classify carbon/charging evidence as one of:

```text
NO_LOCAL_SIGNAL
PROXY_ONLY
E2_ROUTE_COMPRESSION_SUPPORT
E4_E5_CARBON_OBJECTIVE_SUPPORT
INVALID_HEALTH
```

### Acceptance Gate

- [ ] If carbon/charging is `NO_LOCAL_SIGNAL` or `PROXY_ONLY`, do not run a large carbon branch.
- [ ] If it supports E2 route compression, merge its observation into E2 mechanism planning.
- [ ] If it only supports carbon objective behavior, route it to E4/E5, not Track24 dynamic PPO.

---

## Workstream HEALTH: Evidence Hygiene And Protected Diff Gate

### Purpose

This workstream prevents a false win. It runs before and after every DYN/E2/CARBON result.

### Tasks

- [ ] Create a health audit helper:

```text
solver/tools/track24r3_health_gate.py
```

- [ ] The helper must read a report directory and emit:

```json
{
  "report_dir": "",
  "row_count": 0,
  "ok_count": 0,
  "health_failure_count": 0,
  "halt_classes": {},
  "mixed_code_result": false,
  "under_eval_marked_ok_count": 0,
  "worker_failure_count": 0,
  "hash_pollution_count": 0,
  "resume_safe": true,
  "protected_diff_clean": true,
  "tex_diff_clean": true,
  "output_structure_ok": true,
  "first_failure_sample": null
}
```

- [ ] Protected diff check:

```powershell
git diff -- solver/src/setp_solver/cost.py solver/src/setp_solver/check.py solver/src/setp_solver/search/evaluation.py solver/src/setp_solver/baselines/metaheuristic_baselines.py
git diff -- "*.tex"
git diff --check
```

- [ ] Add tests:

```text
solver/rl/tests/test_track24r3_health_gate.py
```

Required cases:

```text
test_health_gate_rejects_mixed_code_breakthrough
test_health_gate_rejects_under_eval_marked_ok
test_health_gate_reports_first_halt_sample
test_health_gate_rejects_missing_required_output_files
```

Run:

```powershell
pytest solver/rl/tests/test_track24r3_health_gate.py -q
```

### Acceptance Gate

- [ ] No Track24-R3 conclusion is valid unless `track24r3_health_gate.py` passes on the report directory.
- [ ] Any health gate failure blocks Stage4/PPO and becomes the final report's main verdict.

---

## Integrated Test Plan

Run the smallest meaningful test group after each production edit:

```powershell
pytest solver/tests/test_formal_runner.py -k "dynamic_policy or dynamic_final or policy_decision or dynamic_payload or commit_chunk or defer_guard or lifecycle" -q
```

Run DR report regressions after runner/report edits:

```powershell
pytest solver/rl/tests/test_track24_breakthrough_audit.py solver/rl/tests/test_final_track18.py solver/rl/tests/test_final_track23.py -q
```

Run new probe tests:

```powershell
pytest solver/rl/tests/test_e2_route_compression_probe.py solver/rl/tests/test_track24r3_health_gate.py -q
```

Run final hygiene:

```powershell
git diff --check
git diff -- solver/src/setp_solver/cost.py solver/src/setp_solver/check.py solver/src/setp_solver/search/evaluation.py solver/src/setp_solver/baselines/metaheuristic_baselines.py
git diff -- "*.tex"
```

---

## Final Decision Matrix

- [ ] `DYN_FULL_FIXED_UNHEALTHY`: stop. Report failing rows, halt classes, first payload samples. No Stage4/PPO.
- [ ] `DYN_FULL_FIXED_HEALTHY_WEAK`: health is fixed but mean reduction `<2pp`. Stop dynamic PPO. Route to E2/E6.
- [ ] `DYN_FULL_FIXED_HEALTHY_BUDGET_ONLY`: mean reduction `>=2pp` but dominated by budget/event-density action. Write budget-control result only. No mechanism claim for reserve/defer/charging.
- [ ] `DYN_FULL_FIXED_HEALTHY_MECHANISM_VALID`: mean reduction `>=2pp`, lifecycle guard passes, action semantics are true not proxy. Allow a separate imitation/contextual-bandit plan. PPO remains blocked until that simpler controller fails to explain the signal.
- [ ] `E2_ROUTE_COMPRESSION_VALID`: prioritize deterministic route-compression/stability mechanism for the paper path.
- [ ] `E6_FAIRNESS_REPAIR_VALID`: prioritize fairness-safe repair mechanism and keep dynamic DR as secondary.
- [ ] `CARBON_ONLY_VALID`: route to E4/E5 carbon objective work, not Track24 dynamic PPO.
- [ ] `HEALTH_INVALID`: stop all claims and fix evidence hygiene first.

---

## Final Report Format

Every implementing agent must close with this exact shape:

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

The final report must explicitly separate:

```text
Legality fixed?
Fixed-code full Stage3 healthy?
Mean reduction >= 2pp?
Mechanism semantics true or proxy?
Stage4 allowed?
PPO allowed?
```

---

## Recommended Execution Order

- [ ] First execute `HEALTH` preflight on current repo and previous Track24-R2 evidence.
- [ ] Then execute `DYN-A` fixed-code full Stage3.
- [ ] In parallel with long-run waiting only if compute is idle, implement `DYN-B/C` tests and minimal state-machine fix.
- [ ] After DYN-A finishes, run `DYN-D` action semantics summary.
- [ ] If DYN gate is weak or budget-only, execute `E2`.
- [ ] Execute `CARBON` only as a read-only audit unless E2 shows carbon/charging contributes to route compression.
- [ ] Produce one final gate report and do not proceed to Stage4/PPO unless the decision matrix allows it.
