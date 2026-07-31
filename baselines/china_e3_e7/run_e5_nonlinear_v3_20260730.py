#!/usr/bin/env python3
"""E5 nonlinear-charging experiment with complete-evaluation cap semantics.

This is a narrow v3 overlay on the verified v2 runner.  The search, common
initial solution, curve arms, seeds, instance order, progress logging,
independent checker, scientific endpoints, and closeout structure are reused.
Only runner-side budget interpretation and accounting change:

* the submitted complete-candidate budget is a hard upper cap;
* consumption below the cap is normal when the finite unique archive is
  exhausted;
* consumption above the cap is a fail-closed technical fault;
* each unit records consumed evaluations, the cap, and a factual termination
  reason.

No search, evaluator, cost, feasibility, route-pool, or epochal-HGS semantics
are modified here.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_e5_nonlinear_v2_20260730 as base

TASK_ID = "E5-NONLINEAR-CHARGING-V3-20260730"
OUT = base.REPO / "baselines/china_e3_e7/e5_nonlinear_v3_20260730"
CHECKER = (
    base.REPO / "baselines/china_e3_e7/check_e5_nonlinear_v3_20260730.py"
)
HUNDRED = 100

# Bind the reused v2 structure to a separate v3 identity and output root.
base.TASK_ID = TASK_ID
base.OUT = OUT
base.LOCKED_SOURCES = tuple(
    dict.fromkeys(
        (
            Path(__file__).resolve(),
            CHECKER,
            base.REPO
            / "baselines/china_e3_e7/run_e5_nonlinear_v2_20260730.py",
            *base.LOCKED_SOURCES,
        )
    )
)

_atomic_csv_v2 = base.atomic_csv
_atomic_json_v2 = base.atomic_json


def _round_up_to_hundred_with_natural_margin(value: int) -> int:
    """Return the first whole hundred strictly above or equal to ``value``.

    A non-multiple is rounded upward (331 -> 400).  An exact multiple receives
    one additional hundred so an observed natural endpoint is not converted
    into a quota (400 -> 500).
    """

    if value < 1:
        raise ValueError("evaluation count must be positive")
    rounded = int(math.ceil(value / HUNDRED) * HUNDRED)
    return rounded + HUNDRED if rounded == value else rounded


def _termination_reason(
    run: Any,
    *,
    consumed: int,
    cap: int,
) -> tuple[str, dict[str, Any]]:
    """Classify termination using counters already emitted by the search.

    ``epochal_hgs`` always builds a finite unique terminal population archive.
    A view whose archive completion attempts are below its configured limit and
    equal ``min(unique_native_candidates, limit)`` has exhausted that archive.
    The current route stack has no outer NoImprovement termination; if a future
    source reports one explicitly, it is recorded as NO_IMPROVEMENT.  Any other
    early-stop shape is ambiguous and therefore fails closed.
    """

    evidence: dict[str, Any] = {}
    for mode, epoch in run.view_epochs.items():
        stats = epoch.stats
        limit = int(stats["archive_candidate_limit"])
        actual = int(stats["archive_completion_attempts"])
        unique = int(stats["archive_unique_native_candidates"])
        evidence[mode] = {
            "archive_candidate_limit": limit,
            "archive_completion_attempts": actual,
            "archive_unique_native_candidates": unique,
            "hgs_stop_mode": stats["hgs_stop_mode"],
            "wallclock_safety_triggered": bool(
                stats["wallclock_safety_triggered"]
            ),
        }

    if consumed > cap:
        raise RuntimeError(
            f"HALT_E5_V3_BUDGET_CAP_EXCEEDED:{consumed}:{cap}"
        )
    if consumed == cap:
        return "BUDGET_CAP_REACHED", evidence

    no_improvement_modes = [
        mode
        for mode, row in evidence.items()
        if "NO_IMPROVEMENT" in str(row["hgs_stop_mode"]).upper()
    ]
    if no_improvement_modes:
        evidence["no_improvement_modes"] = no_improvement_modes
        return "NO_IMPROVEMENT", evidence

    shortfall_modes = [
        mode
        for mode, row in evidence.items()
        if int(row["archive_completion_attempts"])
        < int(row["archive_candidate_limit"])
    ]
    exhausted_modes = [
        mode
        for mode in shortfall_modes
        if int(evidence[mode]["archive_completion_attempts"])
        == min(
            int(evidence[mode]["archive_unique_native_candidates"]),
            int(evidence[mode]["archive_candidate_limit"]),
        )
    ]
    evidence["shortfall_modes"] = shortfall_modes
    evidence["exhausted_modes"] = exhausted_modes
    if shortfall_modes and exhausted_modes == shortfall_modes:
        return "CANDIDATES_EXHAUSTED", evidence

    raise RuntimeError(
        "HALT_E5_V3_AMBIGUOUS_EARLY_TERMINATION:"
        f"consumed={consumed}:cap={cap}:evidence={evidence}"
    )


def run_search_unit(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one unchanged search unit and apply cap-only accounting."""

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
            and int(existing.get("complete_candidate_budget_cap", -1)) == cap
            and existing.get("source_lock_id") == lock_id
        ):
            return existing
        raise RuntimeError(f"HALT_E5_V3_STALE_TASK_ARTIFACT:{status_path}")

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
    stats = run.stats
    consumed = int(stats["complete_candidate_evaluation_attempts"])
    configured_expected = int(stats["complete_candidate_budget_expected"])
    if bool(stats["wallclock_safety_triggered"]):
        raise RuntimeError(f"HALT_E5_V3_WALLCLOCK_SAFETY_TRIGGERED:{stem}")
    reason, termination_evidence = _termination_reason(
        run, consumed=consumed, cap=cap
    )
    trace = stats["complete_candidate_evaluation_trace"]
    if len(trace) != consumed or any(
        row.get("complete_objective") is None for row in trace
    ):
        raise RuntimeError(f"HALT_E5_V3_INVALID_COMPLETE_TRACE:{stem}")

    elapsed_wall = time.perf_counter() - started_wall
    elapsed_cpu = time.process_time() - started_cpu
    trace_payload = {
        "schema_version": f"E5-{phase.upper()}-SEARCH-TRACE-v3",
        "task_id": TASK_ID,
        **spec,
        "complete_candidate_budget_cap": cap,
        "complete_candidate_evaluations_consumed": consumed,
        "termination_reason": reason,
        "termination_evidence": termination_evidence,
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
    status = {
        "schema_version": f"E5-{phase.upper()}-SEARCH-UNIT-v3",
        "task_id": TASK_ID,
        **spec,
        "phase": phase,
        "budget": cap,
        "complete_candidate_budget_cap": cap,
        "complete_candidate_evaluations_consumed": consumed,
        "complete_candidate_evaluations_S": consumed,
        "configured_complete_candidate_budget_expected": configured_expected,
        "legacy_exact_consumption_flag": bool(
            stats["complete_candidate_budget_exactly_consumed"]
        ),
        "termination_reason": reason,
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
        "wallclock_safety_triggered": False,
        "elapsed_wall_seconds": elapsed_wall,
        "elapsed_cpu_seconds": elapsed_cpu,
        "common_initial_solution_sha256": base.initial_hash(initial),
        "search_total_cost_cny": float(run.completion.objective),
        "objective_status": "COMPLETE_MODEL_EVALUATED",
        "source_lock_id": lock_id,
        "search_trace_path": base.relative(trace_path),
        "search_trace_sha256": base.file_sha256(trace_path),
        "status": "PASS",
    }
    if phase == "formal":
        if plan_path is None:
            raise RuntimeError("formal plan path was not constructed")
        solution = base.solution_payload(run.solution)
        plan = {
            "schema_version": "E5-FORMAL-PLAN-v3",
            "task_id": TASK_ID,
            **spec,
            "budget": cap,
            "complete_candidate_budget_cap": cap,
            "complete_candidate_evaluations_consumed": consumed,
            "termination_reason": reason,
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


def analyze_probe(
    rows: list[dict[str, Any]], long_cap: int
) -> dict[str, Any]:
    """Write the full improvement curves and select a common formal cap."""

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
                f"HALT_E5_V3_UNEXPECTED_TERMINAL_TRACE:{status['arm']}"
            )
        search_trace = trace[:-2]
        search_objectives = [
            float(row["complete_objective"]) for row in search_trace
        ]
        if not search_objectives:
            raise RuntimeError(
                f"HALT_E5_V3_EMPTY_PROBE_SEARCH_TRACE:{status['arm']}"
            )
        final_search_best = min(search_objectives)
        terminal_best = min(float(row["complete_objective"]) for row in trace)
        incumbent = math.inf
        plateau_start: int | None = None
        for item in trace:
            objective = float(item["complete_objective"])
            incumbent = min(incumbent, objective)
            index = int(item["evaluation_index"])
            segment = (
                "TERMINAL_ROUTE_POOL_CLOSURE"
                if index > len(search_trace)
                else "MULTI_VIEW_SEARCH"
            )
            relative_gap = (
                (incumbent - final_search_best)
                / max(1.0, abs(final_search_best))
                if segment == "MULTI_VIEW_SEARCH"
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
                    "complete_objective_cny": objective,
                    "incumbent_best_cny": incumbent,
                    "relative_gap_to_final_search_best": (
                        relative_gap
                        if relative_gap is not None
                        else "NA_TERMINAL"
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
            selection_basis = "CANDIDATES_EXHAUSTED_AT_ACTUAL_CONSUMPTION"
            basis_evaluation = consumed
            recommended = _round_up_to_hundred_with_natural_margin(consumed)
        elif plateau_confirmed:
            selection_basis = "PLATEAU_CONFIRMED_WITH_200_EVALUATION_MARGIN"
            basis_evaluation = int(confirmation) + 2
            recommended = _round_up_to_hundred_with_natural_margin(
                basis_evaluation
            )
        else:
            selection_basis = "LONG_CAP_NO_CONFIRMED_PLATEAU"
            basis_evaluation = long_cap
            recommended = long_cap
        recommended = min(long_cap, int(recommended))

        arm_rows.append(
            {
                "arm": status["arm"],
                "long_complete_candidate_budget_cap": long_cap,
                "complete_candidate_evaluations_consumed": consumed,
                "termination_reason": reason,
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
                "budget_selection_basis": selection_basis,
                "budget_selection_basis_evaluation": basis_evaluation,
                "arm_recommended_budget_cap_rounded_to_100": recommended,
                "elapsed_wall_seconds": status["elapsed_wall_seconds"],
                "last_strict_improvement_evaluation_L_all_evaluations": status[
                    "last_strict_improvement_evaluation_L"
                ],
                "last_strict_improvement_fraction_L_over_S_diagnostic_only": (
                    status["last_strict_improvement_fraction_L_over_S"]
                ),
            }
        )

    selected = max(
        int(row["arm_recommended_budget_cap_rounded_to_100"])
        for row in arm_rows
    )
    base.atomic_csv(OUT / "probe" / "convergence_curve.csv", curve_rows)
    base.atomic_csv(OUT / "probe" / "convergence_summary.csv", arm_rows)
    summary = {
        "schema_version": "E5-CONVERGENCE-PROBE-v3",
        "task_id": TASK_ID,
        "status": "PASS",
        "created_at_utc": base.now_iso(),
        "instance_id": base.PROBE_INSTANCE,
        "seed": base.PROBE_SEED,
        "arms": list(base.ARMS),
        "long_complete_candidate_budget_cap": long_cap,
        "plateau_rule": {
            "search_segment": (
                "complete evaluations before the two deterministic terminal "
                "route-pool closure/certificate evaluations"
            ),
            "relative_band": base.PLATEAU_RELATIVE_BAND,
            "definition": (
                "earliest incumbent within relative_band of the final "
                "multi-view-search incumbent"
            ),
            "confirmation_window_evaluations": (
                base.PLATEAU_CONFIRMATION_EVALUATIONS
            ),
            "candidate_exhaustion_rule": (
                "round actual consumed evaluations upward to a whole hundred; "
                "if already a whole hundred, add one hundred"
            ),
            "common_cap": "maximum of the two arm recommendations",
        },
        "arm_results": arm_rows,
        "selected_common_formal_budget": selected,
        "selected_common_formal_budget_cap": selected,
        "selection_uses_L_over_S": False,
        "curve_path": base.relative(OUT / "probe" / "convergence_curve.csv"),
    }
    summary["probe_id"] = base.payload_sha256(summary)
    base.atomic_json(OUT / "probe" / "summary.json", summary)
    lock = {
        "schema_version": "E5-BUDGET-LOCK-v3",
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


def formal_table(
    certs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    status_by_key = {
        (row["instance_id"], int(row["seed"]), row["arm"]): row
        for row in statuses
    }
    rows: list[dict[str, Any]] = []
    for spec in base.INSTANCE_SPECS:
        instance_id = str(spec["instance_id"])
        for arm in base.ARMS:
            subset = [
                row
                for row in certs
                if row["instance_id"] == instance_id and row["arm"] == arm
            ]
            feasible = [
                row for row in subset if row["planning_physics_feasible"]
            ]
            costs = [
                float(row["planning_full_model_total_cost_cny"])
                for row in feasible
            ]
            if costs:
                best = min(costs)
                avg = base.arithmetic_mean(costs)
                gap = 100.0 * (avg - best) / best
                best_row = min(
                    feasible,
                    key=lambda row: float(
                        row["planning_full_model_total_cost_cny"]
                    ),
                )
                best_vehicles: int | str = int(
                    best_row["physical_vehicle_count"]
                )
            else:
                best = avg = gap = "NA_INFEASIBLE"
                best_vehicles = "NA_INFEASIBLE"
            vehicles = [
                int(row["physical_vehicle_count"]) for row in feasible
            ]
            unit_statuses = [
                status_by_key[(instance_id, int(row["seed"]), arm)]
                for row in subset
            ]
            times = [
                float(row["elapsed_wall_seconds"]) for row in unit_statuses
            ]
            evaluations = [
                int(row["complete_candidate_evaluations_consumed"])
                for row in unit_statuses
            ]
            reasons = sorted(
                {
                    str(row["termination_reason"])
                    for row in unit_statuses
                }
            )
            rows.append(
                {
                    "instance_id": instance_id,
                    "sample_role": spec["sample_role"],
                    "arm": arm,
                    "feasible_runs": len(feasible),
                    "runs": len(subset),
                    "Best_CNY": best,
                    "Avg_CNY": avg,
                    "Gap_pct_Avg_minus_Best_over_Best": gap,
                    "vehicles_best": best_vehicles,
                    "vehicles_avg": (
                        base.arithmetic_mean(
                            [float(value) for value in vehicles]
                        )
                        if vehicles
                        else "NA_INFEASIBLE"
                    ),
                    "time_avg_seconds": base.arithmetic_mean(times),
                    "time_total_seconds": sum(times),
                    "complete_candidate_budget_cap": int(
                        unit_statuses[0]["complete_candidate_budget_cap"]
                    ),
                    "evaluations_consumed_avg": base.arithmetic_mean(
                        [float(value) for value in evaluations]
                    ),
                    "evaluations_consumed_median": base.median(
                        [float(value) for value in evaluations]
                    ),
                    "evaluations_consumed_min": min(evaluations),
                    "evaluations_consumed_max": max(evaluations),
                    "termination_reasons": "|".join(reasons),
                }
            )
    return rows


def _format_number(value: Any, digits: int = 2, suffix: str = "") -> str:
    if isinstance(value, str):
        return value
    return f"{float(value):.{digits}f}{suffix}"


def render_report(
    probe: dict[str, Any],
    table_rows: list[dict[str, Any]],
    endpoints: dict[str, Any],
    cause_rows: list[dict[str, Any]],
    budget: int,
) -> str:
    probe_lines = [
        "| {arm} | {cap} | {used} | {reason} | {start} | {confirm} | "
        "{basis} | {recommended} |".format(
            arm=row["arm"],
            cap=row["long_complete_candidate_budget_cap"],
            used=row["complete_candidate_evaluations_consumed"],
            reason=row["termination_reason"],
            start=row["plateau_start_evaluation"],
            confirm=row["plateau_confirmation_evaluation"],
            basis=row["budget_selection_basis"],
            recommended=row["arm_recommended_budget_cap_rounded_to_100"],
        )
        for row in probe["arm_results"]
    ]
    formal_lines = [
        "| {instance} | {arm} | {feasible}/{runs} | {best} | {avg} | "
        "{gap} | {vehicles}/{vehicles_avg} | {time} | {used} | {cap} | "
        "{reason} |".format(
            instance=row["instance_id"],
            arm=row["arm"],
            feasible=row["feasible_runs"],
            runs=row["runs"],
            best=_format_number(row["Best_CNY"]),
            avg=_format_number(row["Avg_CNY"]),
            gap=_format_number(
                row["Gap_pct_Avg_minus_Best_over_Best"], 3, "%"
            ),
            vehicles=row["vehicles_best"],
            vehicles_avg=_format_number(row["vehicles_avg"]),
            time=_format_number(row["time_avg_seconds"]),
            used=(
                f"{float(row['evaluations_consumed_avg']):.1f} "
                f"[{row['evaluations_consumed_min']},"
                f"{row['evaluations_consumed_max']}]"
            ),
            cap=row["complete_candidate_budget_cap"],
            reason=row["termination_reasons"],
        )
        for row in table_rows
    ]
    endpoint_lines: list[str] = []
    direction_lines: list[str] = []
    for instance_id, row in endpoints.items():
        e1 = row["endpoint_1_NL90_complete_feasibility"]
        e2 = row["endpoint_2_linear_false_feasibility"]
        e3 = row["endpoint_3_common_feasible_cost_effect"]
        effect = e3["mean_NL90_minus_L100_pct"]
        endpoint_lines.append(
            f"| {instance_id} | {e1['feasible_count']}/{e1['denominator']} | "
            f"{e2['false_feasible_count']}/{e2['denominator']} | "
            f"{e3['coverage_count']}/{e3['denominator']} | "
            f"{'NA_NOT_IDENTIFIABLE' if effect is None else f'{float(effect):.3f}%'} |"
        )
        if effect is None:
            label = "共同可行分母不足，成本方向不可识别"
        elif abs(float(effect)) < 1.0e-9:
            label = "零效应"
        elif float(effect) > 0:
            label = "NL90 成本上升"
        else:
            label = "NL90 成本下降"
        direction_lines.append(
            f"- `{instance_id}`：{label}；共同可行配对 "
            f"{e3['coverage_count']}/{e3['denominator']}。"
        )
    cause_lines = [
        f"| {row['instance_id']} | {row['cause_category']} | "
        f"{row['affected_unit_count']} | {row['violation_count']} |"
        for row in cause_rows
    ]
    probe_consumed = ", ".join(
        f"{row['arm']}={row['complete_candidate_evaluations_consumed']}"
        for row in probe["arm_results"]
    )
    return f"""# E5 非线性充电机制正式实验（v3）

## 结论

本批完成收敛探针、主展示 50c-01 和稳健性 100c-02 的两臂正式实验；每个算例、每个臂使用共同种子 1--10 和同一共同初始解。正式完整候选评价预算为 **{budget} 次上限（cap）**，不是必须消费完的配额。实际消费不足 cap 但可由有限唯一候选耗尽解释时属于正常提前终止；只有消费超过 cap 才是预算控制故障。正式效应方向未用于选预算、换种子、换算例或改判据。

本轮识别并纠正了 v2 的第二类误报：v2 把配置 archive 上限当成精确消费配额，而 `epochal_hgs.py` 实际只评价真实 `proxy_ranked` 候选；目标期刊取证显示最大迭代和最大不改进条件允许正常提前停止，没有“必须跑满预算”的惯例。`route_pool_sp.py` 和 `epochal_hgs.py` 的搜索语义未改。

## 收敛探针与预算来源

探针固定在 `cn-prd-50c-01-V2-LOCATIONS`、seed=1，两臂 cap 均为 1500。实际消费为 {probe_consumed}。逐次目标和 incumbent 见 `probe/convergence_curve.csv`。

平台规则可复算：在去掉最后两次确定性路线池闭合/证书评价后的多视角搜索段，找首次进入最终搜索 incumbent 的 {base.PLATEAU_RELATIVE_BAND:.4%} 相对带；再保留 {base.PLATEAU_CONFIRMATION_EVALUATIONS} 次评价作确认余量并向上取整百。若有限唯一候选先耗尽，则用实际耗尽点向上取整百（整百耗尽时再加 100）作为自然余量。两臂取较大共同 cap。

| Arm | Probe cap | Consumed | Termination | Plateau start | Confirmation | Selection basis | Recommended cap |
|---|---:|---:|---|---:|---:|---|---:|
{chr(10).join(probe_lines)}

共同正式 cap 因而锁为 **{budget}**；`budget_lock.json` 绑定探针 ID 和源锁，正式结果方向不参与选择。

## 正式算法结果

一行对应一个算例×臂。Gap%=`(Avg−Best)/Best×100%`；实际评价数写作均值 `[min,max]`。车辆数写作最佳解/可行运行平均物理车辆数，时间为每个 seed-arm 平均墙钟秒。5 秒路线池 MIP 只代表限时 incumbent，不声称最优。

| Instance | Arm | Feasible | Best (CNY) | Avg (CNY) | Gap% | Vehicles best/avg | Time avg(s) | Actual evaluations avg [min,max] | Cap | Termination |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(formal_lines)}

## 四个科学端点

端点 3 在共同 NL90 物理下比较：L100 方案的路线、车辆、站点、开始时刻和充电量固定，只把充电占用时长换成 NL90 真值；仅两方案都完整可行的配对进入成本百分比。正值表示 NL90 搜索方案成本更高，负值表示更低。

| Instance | NL90 完整可行 | L100 假可行 | 共同可行配对 | NL90−L100 平均成本变化 |
|---|---:|---:|---:|---:|
{chr(10).join(endpoint_lines)}

{chr(10).join(direction_lines)}

假可行原因保留共同检查器的完整分类：

| Instance | Cause | Affected units | Violations |
|---|---|---:|---:|
{chr(10).join(cause_lines)}

端点 4 的逐会话实例、种子、臂、车辆、站点、起止 SOC、L100/NL90 时长和差值见 `charging_sessions.csv`。逐配对成本见 `paired_cost_effects.csv`，机器可读端点汇总见 `decision.json`。

## 独立复算与证据边界

40 个方案由独立进程 `check_e5_nonlinear_v3_20260730.py` 复算；它复用 v2 已验证的重建与固定决策 NL90 回放逻辑，不导入 v3 runner，并核对共同 `check_solution`/`evaluate` 与 `exact_china81_score` 的违反台账和成本分解。受保护 `cost.py`、`check.py`、`search/evaluation.py`、`route_pool_sp.py`、`epochal_hgs.py` 在运行前后锁定；任一漂移均为真故障。旧 `e5_nonlinear_20260729/` 和 `e5_nonlinear_v2_20260730/` 未覆盖或删除。

`raw_runs.csv` 对每个正式单元明确记录 `complete_candidate_evaluations_consumed`、`complete_candidate_budget_cap` 和 `termination_reason`。科学终态由四件套、本报告和最后写入的 `done.json` 共同定义；哈希清单排除 AppleDouble、缓存和监控运行目录。
"""


def _status_lookup() -> dict[tuple[str, int, str], dict[str, Any]]:
    rows: dict[tuple[str, int, str], dict[str, Any]] = {}
    for path in sorted(
        path
        for path in (OUT / "formal" / "task_status").glob("*.json")
        if base.is_real_artifact_file(path)
    ):
        row = json.loads(path.read_text(encoding="utf-8"))
        rows[(row["instance_id"], int(row["seed"]), row["arm"])] = row
    return rows


def atomic_csv_v3(path: Path, rows: list[dict[str, Any]]) -> None:
    if path == OUT / "raw_runs.csv":
        statuses = _status_lookup()
        enriched: list[dict[str, Any]] = []
        for row in rows:
            status = statuses[
                (row["instance_id"], int(row["seed"]), row["arm"])
            ]
            updated = dict(row)
            updated.update(
                {
                    "complete_candidate_evaluations_consumed": int(
                        status["complete_candidate_evaluations_consumed"]
                    ),
                    "complete_candidate_budget_cap": int(
                        status["complete_candidate_budget_cap"]
                    ),
                    "termination_reason": status["termination_reason"],
                }
            )
            enriched.append(updated)
        rows = enriched
    _atomic_csv_v2(path, rows)


def _consumed_values() -> list[int]:
    return [
        int(row["complete_candidate_evaluations_consumed"])
        for row in _status_lookup().values()
    ]


def atomic_json_v3(path: Path, payload: Any) -> None:
    if isinstance(payload, dict):
        payload = dict(payload)
        if path == OUT / "task_card.json":
            payload["schema_version"] = "E5-TASK-CARD-v3"
            payload["budget_semantics"] = "UPPER_CAP_NOT_QUOTA"
            payload["early_termination_policy"] = (
                "consumed<=cap is normal only with explicit termination reason; "
                "consumed>cap HALT"
            )
        elif path == OUT / "decision.json":
            payload["schema_version"] = "E5-DECISION-v3"
            payload["budget_cap"] = int(payload["budget_used"])
            payload["budget_semantics"] = "UPPER_CAP_NOT_QUOTA"
            payload["exact_budget_consumption_required"] = False
            payload["termination_reasons"] = sorted(
                {
                    row["termination_reason"]
                    for row in _status_lookup().values()
                }
            )
            payload.pop("decision_id", None)
            payload["decision_id"] = base.payload_sha256(payload)
        elif path == OUT / "metadata.json":
            payload["schema_version"] = "E5-METADATA-v3"
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
        elif path == OUT / "artifact_hashes.json":
            payload["schema_version"] = "E5-ARTIFACT-HASHES-v3"
            payload.pop("manifest_id", None)
            payload["manifest_id"] = base.payload_sha256(payload)
        elif path == OUT / "done.json":
            consumed = _consumed_values()
            payload["schema_version"] = "E5-DONE-v3"
            payload["budget_cap"] = int(payload["budget_used"])
            payload["median_evaluations_consumed"] = base.median(
                [float(value) for value in consumed]
            )
            payload["termination_reasons"] = sorted(
                {
                    row["termination_reason"]
                    for row in _status_lookup().values()
                }
            )
            decision = json.loads(
                (OUT / "decision.json").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (OUT / "artifact_hashes.json").read_text(encoding="utf-8")
            )
            payload["decision_id"] = decision["decision_id"]
            payload["manifest_id"] = manifest["manifest_id"]
            payload.pop("done_id", None)
            payload["done_id"] = base.payload_sha256(payload)
    _atomic_json_v2(path, payload)


def run_independent_checker() -> None:
    subprocess.run(
        [sys.executable, "-u", str(CHECKER), "--output-root", str(OUT)],
        cwd=base.REPO,
        env={**os.environ, **base.REQUIRED_THREAD_ENV},
        check=True,
    )


# Install the narrow v3 overrides into the reused v2 orchestration.
base.run_search_unit = run_search_unit
base.analyze_probe = analyze_probe
base.formal_table = formal_table
base.render_report = render_report
base.atomic_csv = atomic_csv_v3
base.atomic_json = atomic_json_v3
base.run_independent_checker = run_independent_checker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("probe", "formal", "finalize"))
    parser.add_argument(
        "--complete-eval-budget",
        required=True,
        type=int,
        help="hard upper cap on complete-candidate evaluations; no default",
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
