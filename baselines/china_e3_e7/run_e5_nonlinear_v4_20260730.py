#!/usr/bin/env python3
"""E5 v4: preserve null-candidate evidence, classify it, then fail closed.

Search, candidate generation, acceptance, complete-model evaluation, common
initial solutions, arms, seeds, and cap semantics are inherited unchanged from
v3.  V4 changes runner-side evidence handling only:

* the full trace is atomically persisted before validation;
* caught exception type/message are classified by an explicit allow-list;
* legitimate complete-model infeasibility consumes budget normally;
* any technical-error candidate halts after its evidence has been persisted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_e5_nonlinear_v3_20260730 as v3

base = v3.base
TASK_ID = "E5-NONLINEAR-CHARGING-V4-20260730"
OUT = base.REPO / "baselines/china_e3_e7/e5_nonlinear_v4_20260730"
CHECKER = (
    base.REPO / "baselines/china_e3_e7/check_e5_nonlinear_v4_20260730.py"
)
SEMANTICS_PROOF = OUT / "diagnostics/search_semantics_unchanged_proof.json"

LEGITIMATE_INFEASIBILITY_PREFIXES = (
    "China81 route skeleton has no feasible all-CV completion:",
    "China81 route skeleton exceeds the registered total fleet",
    "China81 route skeleton cannot satisfy the registered CV cap",
)

base.TASK_ID = TASK_ID
base.OUT = OUT
base.PROTECTED = tuple(
    dict.fromkeys((*base.PROTECTED, base.PROTOTYPE / "epochal_hgs.py"))
)
base.LOCKED_SOURCES = tuple(
    dict.fromkeys(
        (
            Path(__file__).resolve(),
            CHECKER,
            SEMANTICS_PROOF,
            base.REPO
            / "baselines/china_e3_e7/run_e5_nonlinear_v3_20260730.py",
            *base.LOCKED_SOURCES,
        )
    )
)

_atomic_csv = v3._atomic_csv_v2
_atomic_json = v3._atomic_json_v2


def classify_trace(trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify every complete-model attempt without changing its meaning."""

    classified: list[dict[str, Any]] = []
    counts = {
        "feasible_candidates": 0,
        "infeasible_candidates": 0,
        "error_candidates": 0,
    }
    type_message_counts: dict[tuple[str, str, str], int] = {}
    examples: dict[str, list[dict[str, Any]]] = {
        "legitimate_infeasible": [],
        "technical_error": [],
    }
    for original in trace:
        row = dict(original)
        objective = row.get("complete_objective")
        status = str(row.get("status"))
        exc_type = row.get("exception_type")
        exc_message = row.get("exception_message")
        if objective is not None and status == "PASS":
            category = "FEASIBLE"
            counts["feasible_candidates"] += 1
        elif (
            objective is None
            and status == "INFEASIBLE_OR_ERROR"
            and exc_type == "ValueError"
            and isinstance(exc_message, str)
            and exc_message.startswith(LEGITIMATE_INFEASIBILITY_PREFIXES)
        ):
            category = "LEGITIMATE_INFEASIBLE"
            counts["infeasible_candidates"] += 1
        else:
            category = "TECHNICAL_ERROR"
            counts["error_candidates"] += 1
        row["failure_category"] = category
        classified.append(row)
        if category != "FEASIBLE":
            key = (
                category,
                str(exc_type or "MISSING_EXCEPTION_TYPE"),
                str(exc_message or "MISSING_EXCEPTION_MESSAGE"),
            )
            type_message_counts[key] = type_message_counts.get(key, 0) + 1
            bucket = (
                "legitimate_infeasible"
                if category == "LEGITIMATE_INFEASIBLE"
                else "technical_error"
            )
            if len(examples[bucket]) < 5:
                examples[bucket].append(
                    {
                        "evaluation_index": row.get("evaluation_index"),
                        "view": row.get("view"),
                        "source": row.get("source"),
                        "exception_type": exc_type,
                        "exception_message": exc_message,
                    }
                )
    breakdown = [
        {
            "failure_category": category,
            "exception_type": exc_type,
            "exception_message": message,
            "count": count,
        }
        for (category, exc_type, message), count in sorted(
            type_message_counts.items()
        )
    ]
    return {
        **counts,
        "classified_trace": classified,
        "exception_breakdown": breakdown,
        "examples": examples,
    }


def _halt_status(
    status_path: Path,
    status: dict[str, Any],
    code: str,
    detail: str,
) -> dict[str, Any]:
    halted = {
        **status,
        "status": code,
        "halt_detail": detail,
        "validated_at_utc": base.now_iso(),
    }
    base.atomic_json(status_path, halted)
    return halted


def run_search_unit(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one unchanged search and persist its evidence before validation."""

    for name, value in base.REQUIRED_THREAD_ENV.items():
        os.environ[name] = value
    spec = dict(payload["spec"])
    phase = str(payload["phase"])
    cap = int(payload["budget"])
    lock_id = str(payload["lock_id"])
    root = Path(str(payload["output_root"]))
    stem = base.task_stem(spec)
    status_path, trace_path, plan_path = base.phase_paths(root, phase, stem)
    if status_path.is_file():
        existing = json.loads(status_path.read_text(encoding="utf-8"))
        if (
            existing.get("status") == "PASS"
            and int(existing.get("complete_candidate_budget_cap", -1))
            == cap
            and existing.get("source_lock_id") == lock_id
        ):
            return existing
        raise RuntimeError(f"HALT_E5_V4_STALE_TASK_ARTIFACT:{status_path}")

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    base_bundle = base.load_china81_bundle(
        base.REPO, str(spec["instance_id"])
    )
    bundle = base.curve_bundle(base_bundle, str(spec["arm"]))
    initial = base.load_initial(str(spec["instance_id"]))
    archives = base.archive_limits(cap)
    safety = (
        900.0
        if phase == "probe"
        else max(600.0, 4.0 * (len(bundle.instance.nodes) - 1))
    )
    run = base.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=int(spec["seed"]),
        hgs_seconds_per_view=None,
        exact_elites_per_view=base.EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=archives,
        sp_time_limit_seconds=base.MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=base.MAX_HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=safety,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    elapsed_wall = time.perf_counter() - started_wall
    elapsed_cpu = time.process_time() - started_cpu
    stats = run.stats
    consumed = int(stats["complete_candidate_evaluation_attempts"])
    configured_expected = int(
        stats["complete_candidate_budget_expected"]
    )
    diagnosis = classify_trace(
        list(stats["complete_candidate_evaluation_trace"])
    )
    trace = diagnosis.pop("classified_trace")

    termination_reason: str | None = None
    termination_evidence: dict[str, Any] = {}
    termination_error: str | None = None
    try:
        termination_reason, termination_evidence = v3._termination_reason(
            run, consumed=consumed, cap=cap
        )
    except RuntimeError as exc:
        termination_error = str(exc)

    trace_payload = {
        "schema_version": f"E5-{phase.upper()}-SEARCH-TRACE-v4",
        "task_id": TASK_ID,
        **spec,
        "persisted_before_validation": True,
        "complete_candidate_budget_cap": cap,
        "complete_candidate_evaluations_consumed": consumed,
        "termination_reason": termination_reason,
        "termination_evidence": termination_evidence,
        "termination_classification_error": termination_error,
        "candidate_diagnosis": diagnosis,
        "complete_candidate_evaluation_trace": trace,
        "view_epoch_stats": {
            mode: epoch.stats for mode, epoch in run.view_epochs.items()
        },
        "route_pool_stats": {
            key: value
            for key, value in stats.items()
            if key != "complete_candidate_evaluation_trace"
        },
    }
    base.atomic_json(trace_path, trace_payload)
    provisional = {
        "schema_version": f"E5-{phase.upper()}-SEARCH-UNIT-v4",
        "task_id": TASK_ID,
        **spec,
        "phase": phase,
        "budget": cap,
        "complete_candidate_budget_cap": cap,
        "complete_candidate_evaluations_consumed": consumed,
        "complete_candidate_evaluations_S": consumed,
        "configured_complete_candidate_budget_expected": (
            configured_expected
        ),
        "termination_reason": termination_reason,
        "termination_evidence": termination_evidence,
        "archive_candidates_per_view": archives,
        "last_strict_improvement_evaluation_L": int(
            stats["last_strict_improvement_evaluation"]
        ),
        "last_strict_improvement_fraction_L_over_S": float(
            stats["last_strict_improvement_fraction"]
        ),
        "L_over_S_role": "diagnostic_only_never_a_gate",
        "wallclock_safety_seconds_per_view": safety,
        "wallclock_safety_triggered": bool(
            stats["wallclock_safety_triggered"]
        ),
        "elapsed_wall_seconds": elapsed_wall,
        "elapsed_cpu_seconds": elapsed_cpu,
        "common_initial_solution_sha256": base.initial_hash(initial),
        "search_total_cost_cny": float(run.completion.objective),
        "objective_status": "COMPLETE_MODEL_EVALUATED",
        "source_lock_id": lock_id,
        "search_trace_path": base.relative(trace_path),
        "search_trace_sha256": base.file_sha256(trace_path),
        "feasible_candidates": diagnosis["feasible_candidates"],
        "infeasible_candidates": diagnosis["infeasible_candidates"],
        "error_candidates": diagnosis["error_candidates"],
        "persisted_before_validation": True,
        "status": "TRACE_PERSISTED_PENDING_VALIDATION",
    }
    base.atomic_json(status_path, provisional)

    if len(trace) != consumed:
        return _halt_status(
            status_path,
            provisional,
            "HALT_TRACE_COUNTER_MISMATCH",
            f"trace={len(trace)} consumed={consumed}",
        )
    if consumed > cap:
        return _halt_status(
            status_path,
            provisional,
            "HALT_BUDGET_CAP_EXCEEDED",
            f"consumed={consumed} cap={cap}",
        )
    if configured_expected != cap:
        return _halt_status(
            status_path,
            provisional,
            "HALT_CONFIGURED_CAP_MISMATCH",
            f"configured={configured_expected} cap={cap}",
        )
    if bool(stats["wallclock_safety_triggered"]):
        return _halt_status(
            status_path,
            provisional,
            "HALT_WALLCLOCK_SAFETY_TRIGGERED",
            stem,
        )
    if termination_error is not None or termination_reason is None:
        return _halt_status(
            status_path,
            provisional,
            "HALT_AMBIGUOUS_TERMINATION",
            str(termination_error),
        )
    if int(diagnosis["error_candidates"]) > 0:
        return _halt_status(
            status_path,
            provisional,
            "HALT_TECHNICAL_ERROR_CANDIDATE",
            json.dumps(
                diagnosis["exception_breakdown"],
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

    status = {
        **provisional,
        "validated_at_utc": base.now_iso(),
        "status": "PASS",
    }
    if phase == "formal":
        if plan_path is None:
            raise RuntimeError("formal plan path was not constructed")
        solution = base.solution_payload(run.solution)
        plan = {
            "schema_version": "E5-FORMAL-PLAN-v4",
            "task_id": TASK_ID,
            **spec,
            "budget": cap,
            "complete_candidate_budget_cap": cap,
            "complete_candidate_evaluations_consumed": consumed,
            "termination_reason": termination_reason,
            "curve_used_in_search": str(spec["arm"]),
            "common_nonlinear_replay_curve": base.NL90_MILD.curve_id,
            "common_initial_solution_sha256": base.initial_hash(initial),
            "solution": solution,
            "solution_sha256": base.payload_sha256(solution),
            "search_total_cost_cny": float(run.completion.objective),
            "search_trace_path": base.relative(trace_path),
            "search_trace_sha256": base.file_sha256(trace_path),
            "input_sha256": base.input_hashes(bundle),
            "source_lock_id": lock_id,
        }
        plan["plan_sha256"] = base.payload_sha256(plan)
        base.atomic_json(plan_path, plan)
        status.update(
            {
                "plan_path": base.relative(plan_path),
                "plan_file_sha256": base.file_sha256(plan_path),
            }
        )
    base.atomic_json(status_path, status)
    return status


def run_parallel(
    specs: list[dict[str, Any]],
    *,
    phase: str,
    budget: int,
    lock_id: str,
    workers: int,
) -> list[dict[str, Any]]:
    """Run one isolated worker sequentially on this memory-constrained host."""

    if workers != 1:
        raise RuntimeError(
            "HALT_E5_V4_HOST_MEMORY_REQUIRES_ONE_WORKER"
        )
    rows: list[dict[str, Any]] = []
    for completed, spec in enumerate(specs, start=1):
        payload = {
            "spec": spec,
            "phase": phase,
            "budget": budget,
            "lock_id": lock_id,
            "output_root": str(OUT),
        }
        with ProcessPoolExecutor(max_workers=1) as executor:
            row = executor.submit(run_search_unit, payload).result()
        rows.append(row)
        label = (
            "UNIT_COMPLETE"
            if row["status"] == "PASS"
            else "UNIT_HALT"
        )
        print(
            f"{label} instance={spec['instance_id']} "
            f"seed={int(spec['seed'])} arm={spec['arm']} "
            f"status={row['status']} "
            f"elapsed_seconds={float(row['elapsed_wall_seconds']):.3f} "
            f"feasible={int(row['feasible_candidates'])} "
            f"infeasible={int(row['infeasible_candidates'])} "
            f"errors={int(row['error_candidates'])} "
            f"progress={completed}/{len(specs)}",
            flush=True,
        )
        if phase == "formal" and row["status"] != "PASS":
            raise RuntimeError(
                f"{row['status']}:{base.task_stem(spec)}"
            )
    return sorted(
        rows,
        key=lambda row: (
            row["instance_id"],
            int(row["seed"]),
            row["arm"],
        ),
    )


def _probe_diagnosis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    totals = {
        "legitimate_infeasible": 0,
        "technical_error": 0,
        "feasible": 0,
        "complete_evaluations": 0,
    }
    for status in sorted(rows, key=lambda row: row["arm"]):
        trace_payload = json.loads(
            (base.REPO / status["search_trace_path"]).read_text(
                encoding="utf-8"
            )
        )
        candidate = trace_payload["candidate_diagnosis"]
        arm_row = {
            "arm": status["arm"],
            "complete_evaluations": int(
                status["complete_candidate_evaluations_consumed"]
            ),
            "feasible_candidates": int(
                candidate["feasible_candidates"]
            ),
            "legitimate_infeasible": int(
                candidate["infeasible_candidates"]
            ),
            "technical_error": int(candidate["error_candidates"]),
            "exception_breakdown": candidate["exception_breakdown"],
            "examples": candidate["examples"],
        }
        null_count = (
            arm_row["legitimate_infeasible"]
            + arm_row["technical_error"]
        )
        arm_row["null_objective_count"] = null_count
        arm_row["legitimate_pct_of_null"] = (
            100.0 * arm_row["legitimate_infeasible"] / null_count
            if null_count
            else 0.0
        )
        arm_row["technical_error_pct_of_null"] = (
            100.0 * arm_row["technical_error"] / null_count
            if null_count
            else 0.0
        )
        details.append(arm_row)
        totals["legitimate_infeasible"] += arm_row[
            "legitimate_infeasible"
        ]
        totals["technical_error"] += arm_row["technical_error"]
        totals["feasible"] += arm_row["feasible_candidates"]
        totals["complete_evaluations"] += arm_row[
            "complete_evaluations"
        ]
    null_total = (
        totals["legitimate_infeasible"] + totals["technical_error"]
    )
    diagnosis = {
        "schema_version": "E5-NULL-OBJECTIVE-DIAGNOSIS-v4",
        "task_id": TASK_ID,
        "instance_id": base.PROBE_INSTANCE,
        "seed": base.PROBE_SEED,
        "cap_per_arm": 1500,
        "classification_rule": {
            "legitimate_infeasible": (
                "ValueError from complete_china81_route_skeleton with an "
                "explicit complete-model infeasibility prefix"
            ),
            "technical_error": (
                "IndexError, KeyError, TypeError, unknown ValueError, missing "
                "diagnostics, or inconsistent status/objective"
            ),
            "allowed_value_error_prefixes": list(
                LEGITIMATE_INFEASIBILITY_PREFIXES
            ),
        },
        "totals": {
            **totals,
            "null_objective": null_total,
            "legitimate_pct_of_null": (
                100.0
                * totals["legitimate_infeasible"]
                / null_total
                if null_total
                else 0.0
            ),
            "technical_error_pct_of_null": (
                100.0 * totals["technical_error"] / null_total
                if null_total
                else 0.0
            ),
        },
        "arms": details,
    }
    diagnosis["diagnosis_id"] = base.payload_sha256(diagnosis)
    base.atomic_json(OUT / "probe/null_objective_diagnosis.json", diagnosis)
    rows_csv = []
    for arm in details:
        for item in arm["exception_breakdown"]:
            rows_csv.append(
                {
                    "arm": arm["arm"],
                    **item,
                    "arm_null_objective_count": arm[
                        "null_objective_count"
                    ],
                    "pct_of_arm_null": (
                        100.0
                        * int(item["count"])
                        / arm["null_objective_count"]
                        if arm["null_objective_count"]
                        else 0.0
                    ),
                }
            )
    if rows_csv:
        base.atomic_csv(
            OUT / "probe/null_objective_breakdown.csv", rows_csv
        )
    return diagnosis


def analyze_probe(
    rows: list[dict[str, Any]], long_cap: int
) -> dict[str, Any]:
    diagnosis = _probe_diagnosis(rows)
    if int(diagnosis["totals"]["technical_error"]) > 0:
        raise RuntimeError(
            "HALT_E5_V4_TECHNICAL_ERRORS_IN_PROBE:"
            f"{diagnosis['totals']['technical_error']}"
        )
    if any(row["status"] != "PASS" for row in rows):
        raise RuntimeError("HALT_E5_V4_PROBE_UNIT_INVALID")

    curve_rows: list[dict[str, Any]] = []
    arm_rows: list[dict[str, Any]] = []
    for status in sorted(rows, key=lambda row: row["arm"]):
        trace_payload = json.loads(
            (base.REPO / status["search_trace_path"]).read_text(
                encoding="utf-8"
            )
        )
        trace = trace_payload["complete_candidate_evaluation_trace"]
        if tuple(row["source"] for row in trace[-2:]) != (
            base.TERMINAL_CLOSURE_SOURCES
        ):
            raise RuntimeError(
                f"HALT_E5_V4_UNEXPECTED_TERMINAL_TRACE:{status['arm']}"
            )
        search_trace = trace[:-2]
        search_objectives = [
            float(row["complete_objective"])
            for row in search_trace
            if row.get("complete_objective") is not None
        ]
        if not search_objectives:
            raise RuntimeError(
                f"HALT_E5_V4_EMPTY_FEASIBLE_PROBE_TRACE:{status['arm']}"
            )
        final_search_best = min(search_objectives)
        terminal_objectives = [
            float(row["complete_objective"])
            for row in trace
            if row.get("complete_objective") is not None
        ]
        terminal_best = min(terminal_objectives)
        incumbent = math.inf
        plateau_start: int | None = None
        for item in trace:
            raw_objective = item.get("complete_objective")
            if raw_objective is not None:
                objective = float(raw_objective)
                incumbent = min(incumbent, objective)
            else:
                objective = None
            index = int(item["evaluation_index"])
            segment = (
                "TERMINAL_ROUTE_POOL_CLOSURE"
                if index > len(search_trace)
                else "MULTI_VIEW_SEARCH"
            )
            relative_gap = (
                (incumbent - final_search_best)
                / max(1.0, abs(final_search_best))
                if (
                    segment == "MULTI_VIEW_SEARCH"
                    and math.isfinite(incumbent)
                )
                else None
            )
            curve_rows.append(
                {
                    "instance_id": base.PROBE_INSTANCE,
                    "seed": base.PROBE_SEED,
                    "arm": status["arm"],
                    "complete_candidate_budget_cap": long_cap,
                    "complete_candidate_evaluations_consumed": status[
                        "complete_candidate_evaluations_consumed"
                    ],
                    "termination_reason": status["termination_reason"],
                    "evaluation_index": index,
                    "segment": segment,
                    "view": item["view"],
                    "source": item["source"],
                    "status": item["status"],
                    "failure_category": item["failure_category"],
                    "complete_objective_cny": (
                        objective
                        if objective is not None
                        else "NA_INFEASIBLE"
                    ),
                    "incumbent_best_cny": (
                        incumbent
                        if math.isfinite(incumbent)
                        else "NA_NO_FEASIBLE_INCUMBENT"
                    ),
                    "relative_gap_to_final_search_best": (
                        relative_gap
                        if relative_gap is not None
                        else "NA"
                    ),
                }
            )
            if (
                segment == "MULTI_VIEW_SEARCH"
                and plateau_start is None
                and relative_gap is not None
                and relative_gap <= base.PLATEAU_RELATIVE_BAND
            ):
                plateau_start = index
        confirmation = (
            None
            if plateau_start is None
            else plateau_start
            + base.PLATEAU_CONFIRMATION_EVALUATIONS
            - 1
        )
        plateau_confirmed = bool(
            confirmation is not None and confirmation <= len(search_trace)
        )
        consumed = int(status["complete_candidate_evaluations_consumed"])
        reason = str(status["termination_reason"])
        if reason == "CANDIDATES_EXHAUSTED":
            basis = "CANDIDATES_EXHAUSTED_AT_ACTUAL_CONSUMPTION"
            basis_evaluation = consumed
            recommended = v3._round_up_to_hundred_with_natural_margin(
                consumed
            )
        elif plateau_confirmed:
            basis = "PLATEAU_CONFIRMED_WITH_200_EVALUATION_MARGIN"
            basis_evaluation = int(confirmation) + 2
            recommended = v3._round_up_to_hundred_with_natural_margin(
                basis_evaluation
            )
        else:
            basis = "LONG_CAP_NO_CONFIRMED_PLATEAU"
            basis_evaluation = long_cap
            recommended = long_cap
        recommended = min(long_cap, int(recommended))
        arm_rows.append(
            {
                "arm": status["arm"],
                "long_complete_candidate_budget_cap": long_cap,
                "complete_candidate_evaluations_consumed": consumed,
                "termination_reason": reason,
                "feasible_candidates": status["feasible_candidates"],
                "infeasible_candidates": status[
                    "infeasible_candidates"
                ],
                "error_candidates": status["error_candidates"],
                "multi_view_search_evaluations": len(search_trace),
                "terminal_closure_evaluations": 2,
                "final_multi_view_search_best_cny": final_search_best,
                "terminal_route_pool_best_cny": terminal_best,
                "terminal_route_pool_change_pct_vs_search_best": (
                    100.0
                    * (terminal_best - final_search_best)
                    / final_search_best
                ),
                "plateau_relative_band": base.PLATEAU_RELATIVE_BAND,
                "plateau_start_evaluation": plateau_start,
                "plateau_confirmation_window": (
                    base.PLATEAU_CONFIRMATION_EVALUATIONS
                ),
                "plateau_confirmation_evaluation": confirmation,
                "plateau_confirmed": plateau_confirmed,
                "budget_selection_basis": basis,
                "budget_selection_basis_evaluation": basis_evaluation,
                "arm_recommended_budget_cap_rounded_to_100": recommended,
                "elapsed_wall_seconds": status["elapsed_wall_seconds"],
                "last_strict_improvement_evaluation_L_all_evaluations": (
                    status["last_strict_improvement_evaluation_L"]
                ),
                "last_strict_improvement_fraction_L_over_S_diagnostic_only": (
                    status[
                        "last_strict_improvement_fraction_L_over_S"
                    ]
                ),
            }
        )
    selected = max(
        int(row["arm_recommended_budget_cap_rounded_to_100"])
        for row in arm_rows
    )
    base.atomic_csv(OUT / "probe/convergence_curve.csv", curve_rows)
    base.atomic_csv(OUT / "probe/convergence_summary.csv", arm_rows)
    summary = {
        "schema_version": "E5-CONVERGENCE-PROBE-v4",
        "task_id": TASK_ID,
        "status": "PASS",
        "created_at_utc": base.now_iso(),
        "instance_id": base.PROBE_INSTANCE,
        "seed": base.PROBE_SEED,
        "arms": list(base.ARMS),
        "long_complete_candidate_budget_cap": long_cap,
        "null_objective_diagnosis": diagnosis["totals"],
        "plateau_rule": {
            "null_objectives": (
                "count as actual evaluations and are skipped only when "
                "updating the incumbent"
            ),
            "relative_band": base.PLATEAU_RELATIVE_BAND,
            "confirmation_window_evaluations": (
                base.PLATEAU_CONFIRMATION_EVALUATIONS
            ),
            "candidate_exhaustion_rule": (
                "round actual consumption upward to a whole hundred; add "
                "another hundred if already exact"
            ),
            "common_cap": "maximum of the two arm recommendations",
        },
        "arm_results": arm_rows,
        "selected_common_formal_budget": selected,
        "selected_common_formal_budget_cap": selected,
        "selection_uses_L_over_S": False,
        "curve_path": base.relative(OUT / "probe/convergence_curve.csv"),
    }
    summary["probe_id"] = base.payload_sha256(summary)
    base.atomic_json(OUT / "probe/summary.json", summary)
    lock = {
        "schema_version": "E5-BUDGET-LOCK-v4",
        "task_id": TASK_ID,
        "created_at_utc": base.now_iso(),
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "budget_source": "convergence_probe",
        "probe_id": summary["probe_id"],
        "long_probe_budget_cap": long_cap,
        "selected_common_formal_budget": selected,
        "selected_common_formal_budget_cap": selected,
        "source_lock_id": rows[0]["source_lock_id"],
    }
    lock["budget_lock_id"] = base.payload_sha256(lock)
    base.atomic_json(OUT / "budget_lock.json", lock)
    return summary


def _status_lookup() -> dict[tuple[str, int, str], dict[str, Any]]:
    rows: dict[tuple[str, int, str], dict[str, Any]] = {}
    for path in sorted(
        path
        for path in (OUT / "formal/task_status").glob("*.json")
        if base.is_real_artifact_file(path)
    ):
        row = json.loads(path.read_text(encoding="utf-8"))
        rows[(row["instance_id"], int(row["seed"]), row["arm"])] = row
    return rows


def atomic_csv_v4(path: Path, rows: list[dict[str, Any]]) -> None:
    if path == OUT / "raw_runs.csv":
        statuses = _status_lookup()
        enriched = []
        for row in rows:
            status = statuses[
                (row["instance_id"], int(row["seed"]), row["arm"])
            ]
            updated = dict(row)
            updated.update(
                {
                    "complete_candidate_evaluations_consumed": int(
                        status[
                            "complete_candidate_evaluations_consumed"
                        ]
                    ),
                    "complete_candidate_budget_cap": int(
                        status["complete_candidate_budget_cap"]
                    ),
                    "termination_reason": status["termination_reason"],
                    "feasible_candidates": int(
                        status["feasible_candidates"]
                    ),
                    "infeasible_candidates": int(
                        status["infeasible_candidates"]
                    ),
                    "error_candidates": int(
                        status["error_candidates"]
                    ),
                }
            )
            enriched.append(updated)
        rows = enriched
    _atomic_csv(path, rows)


def atomic_json_v4(path: Path, payload: Any) -> None:
    if isinstance(payload, dict):
        payload = dict(payload)
        if path == OUT / "task_card.json":
            payload["schema_version"] = "E5-TASK-CARD-v4"
            payload["budget_semantics"] = "UPPER_CAP_NOT_QUOTA"
            payload["trace_persistence_order"] = (
                "TRACE_AND_PROVISIONAL_STATUS_BEFORE_VALIDATION"
            )
            payload["null_objective_policy"] = (
                "allow-listed complete-model infeasibility consumes budget; "
                "technical errors halt"
            )
            payload["search_semantics_proof"] = base.relative(
                SEMANTICS_PROOF
            )
        elif path == OUT / "decision.json":
            probe_diag = json.loads(
                (OUT / "probe/null_objective_diagnosis.json").read_text(
                    encoding="utf-8"
                )
            )
            payload["schema_version"] = "E5-DECISION-v4"
            payload["budget_cap"] = int(payload["budget_used"])
            payload["budget_semantics"] = "UPPER_CAP_NOT_QUOTA"
            payload["null_objective_diagnosis"] = probe_diag["totals"]
            payload["error_candidate_halt_rule"] = "error_candidates>0"
            payload.pop("decision_id", None)
            payload["decision_id"] = base.payload_sha256(payload)
        elif path == OUT / "metadata.json":
            payload["schema_version"] = "E5-METADATA-v4"
            payload["budget_cap"] = int(payload["budget_used"])
            payload["budget_semantics"] = "UPPER_CAP_NOT_QUOTA"
            payload["runner"] = base.relative(Path(__file__).resolve())
            payload["independent_checker"] = {
                "path": base.relative(CHECKER),
                "reuses_verified_v2_low_level_checker": True,
                "independent_process": True,
                "verification_path": base.relative(
                    OUT / "independent_verification.json"
                ),
            }
            payload["search_semantics_unchanged_proof"] = (
                base.relative(SEMANTICS_PROOF)
            )
        elif path == OUT / "artifact_hashes.json":
            payload["schema_version"] = "E5-ARTIFACT-HASHES-v4"
            payload.pop("manifest_id", None)
            payload["manifest_id"] = base.payload_sha256(payload)
        elif path == OUT / "done.json":
            probe_diag = json.loads(
                (OUT / "probe/null_objective_diagnosis.json").read_text(
                    encoding="utf-8"
                )
            )
            payload["schema_version"] = "E5-DONE-v4"
            payload["budget_cap"] = int(payload["budget_used"])
            payload["null_objective_diagnosis"] = {
                "legitimate_infeasible": int(
                    probe_diag["totals"]["legitimate_infeasible"]
                ),
                "technical_error": int(
                    probe_diag["totals"]["technical_error"]
                ),
            }
            payload["search_semantics_unchanged_proof"] = True
            payload["instances_completed"] = [
                spec["instance_id"] for spec in base.INSTANCE_SPECS
            ]
            payload["seeds"] = 10
            payload["endpoints_answered"] = 4
            decision = json.loads(
                (OUT / "decision.json").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (OUT / "artifact_hashes.json").read_text(
                    encoding="utf-8"
                )
            )
            payload["decision_id"] = decision["decision_id"]
            payload["manifest_id"] = manifest["manifest_id"]
            payload.pop("done_id", None)
            payload["done_id"] = base.payload_sha256(payload)
    _atomic_json(path, payload)


def render_report(
    probe: dict[str, Any],
    table_rows: list[dict[str, Any]],
    endpoints: dict[str, Any],
    cause_rows: list[dict[str, Any]],
    budget: int,
) -> str:
    report = v3.render_report(
        probe, table_rows, endpoints, cause_rows, budget
    )
    diagnosis = json.loads(
        (OUT / "probe/null_objective_diagnosis.json").read_text(
            encoding="utf-8"
        )
    )
    totals = diagnosis["totals"]
    arm_lines = [
        "| {arm} | {complete} | {feasible} | {infeasible} | {errors} | "
        "{legit_pct:.3f}% |".format(
            arm=row["arm"],
            complete=row["complete_evaluations"],
            feasible=row["feasible_candidates"],
            infeasible=row["legitimate_infeasible"],
            errors=row["technical_error"],
            legit_pct=float(row["legitimate_pct_of_null"]),
        )
        for row in diagnosis["arms"]
    ]
    breakdown_lines = []
    for row in diagnosis["arms"]:
        for item in row["exception_breakdown"]:
            breakdown_lines.append(
                f"| {row['arm']} | {item['failure_category']} | "
                f"{item['exception_type']} | {item['count']} | "
                f"`{item['exception_message']}` |"
            )
    diagnostic_section = f"""## v3 二义性诊断

本轮先把完整 trace、候选状态、空目标、异常类名和消息原子写盘，再做校验。两臂合计 {totals['complete_evaluations']} 次完整评价，其中 {totals['null_objective']} 行目标为空；{totals['legitimate_infeasible']} 行（{float(totals['legitimate_pct_of_null']):.3f}%）由完整模型明确判为不可行，技术错误 {totals['technical_error']} 行。因技术错误为零，v3 的“任一空目标即 HALT”判据被证据证明过严；这些合法不可行行继续计入实际消费，incumbent 曲线仅在目标非空时更新。

| Arm | Complete evals | Feasible candidates | Legitimate infeasible | Technical errors | Legitimate share of null |
|---|---:|---:|---:|---:|---:|
{chr(10).join(arm_lines)}

| Arm | Category | Exception type | Count | Exact message |
|---|---|---|---:|---|
{chr(10).join(breakdown_lines)}

异常实例保存在 `probe/null_objective_diagnosis.json`，完整逐行证据保存在 `probe/search_traces/`。`diagnostics/search_semantics_unchanged_proof.json` 对比改动前后同 seed 最终方案、完整目标和去诊断字段后的逐评价 trace，证明纯诊断改动没有改变搜索语义。

"""
    report = report.replace(
        "# E5 非线性充电机制正式实验（v3）",
        "# E5 非线性充电机制正式实验（v4）",
        1,
    )
    marker = "## 收敛探针与预算来源\n"
    report = report.replace(marker, diagnostic_section + marker, 1)
    old = (
        "本轮识别并纠正了 v2 的第二类误报：v2 把配置 archive 上限当成"
        "精确消费配额，而 `epochal_hgs.py` 实际只评价真实 `proxy_ranked` "
        "候选；目标期刊取证显示最大迭代和最大不改进条件允许正常提前停止，"
        "没有“必须跑满预算”的惯例。`route_pool_sp.py` 和 "
        "`epochal_hgs.py` 的搜索语义未改。"
    )
    new = (
        "v3 已纠正预算配额误报，本轮完整保留其上限语义。v4 只增加异常"
        "诊断字段并修正 runner 判据；同 seed 逐位指纹证明最终方案、目标和"
        "去诊断字段后的评价轨迹不变，`route_pool_sp.py` 未改。"
    )
    report = report.replace(old, new)
    report = report.replace(
        "`raw_runs.csv` 对每个正式单元明确记录 "
        "`complete_candidate_evaluations_consumed`、"
        "`complete_candidate_budget_cap` 和 `termination_reason`。",
        "`raw_runs.csv` 对每个正式单元明确记录 "
        "`complete_candidate_evaluations_consumed`、"
        "`complete_candidate_budget_cap`、`termination_reason`、"
        "`feasible_candidates`、`infeasible_candidates` 和 "
        "`error_candidates`。",
    )
    return report


def run_independent_checker() -> None:
    subprocess.run(
        [sys.executable, "-u", str(CHECKER), "--output-root", str(OUT)],
        cwd=base.REPO,
        env={**os.environ, **base.REQUIRED_THREAD_ENV},
        check=True,
    )


base.run_search_unit = run_search_unit
base.run_parallel = run_parallel
base.analyze_probe = analyze_probe
base.formal_table = v3.formal_table
base.render_report = render_report
base.atomic_csv = atomic_csv_v4
base.atomic_json = atomic_json_v4
base.run_independent_checker = run_independent_checker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("probe", "formal", "finalize"))
    parser.add_argument(
        "--complete-eval-budget",
        required=True,
        type=int,
        help="hard upper cap on complete-model candidate evaluations",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--instance-id",
        choices=tuple(
            str(spec["instance_id"]) for spec in base.INSTANCE_SPECS
        ),
    )
    args = parser.parse_args()
    base.archive_limits(args.complete_eval_budget)
    if args.command == "probe":
        if args.instance_id is not None:
            parser.error("--instance-id is not valid for probe")
        base.run_probe(args.complete_eval_budget, args.workers)
    elif args.command == "formal":
        if args.instance_id is None:
            parser.error("--instance-id is required for formal")
        base.run_formal(
            args.instance_id, args.complete_eval_budget, args.workers
        )
    else:
        if args.instance_id is not None:
            parser.error("--instance-id is not valid for finalize")
        base.aggregate_and_close(args.complete_eval_budget, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
