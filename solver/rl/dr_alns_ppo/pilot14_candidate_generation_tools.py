from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import numpy as np

from setp_solver.check import check_solution
from setp_solver.search.alns_wouda import (
    AlnsState,
    SearchPolicy,
    _solution_changed,
)
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, score_candidate, score_reference
from setp_solver.search.feasible_repair import enumerate_feasible_insertions, route_customers
from setp_solver.search.fleet import FleetLimits, infer_fleet_limits, normalize_solution_vehicle_trips
from setp_solver.search.winner_operators import WinnerOperatorSet
from setp_solver.solution import Route, Solution


REQUIRED_WORKER_PYTHON = r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
REQUIRED_WORKER_NUMPY = "2.3.5"

READY_STATUS = "READY_FOR_PPO_INTERFACE"
READY_FOR_TRAINING_STATUS = "READY_FOR_PPO_TRAINING"
HALT_STATUS = "HALT_CANDIDATE_GENERATOR_NO_HEADROOM"

MIN_CHANGED_RATE = 0.20
MIN_IMPROVING_RATE = 0.02
MIN_ROLE_MEAN_RELATIVE = 0.30
MIN_NONWORSE_BUNDLES = 4

THREESHIFT_PROBE_BUNDLES: tuple[dict[str, str], ...] = (
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-01",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-01",
    },
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-02",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-02",
    },
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-03",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-03",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-01",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-01",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-02",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-02",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-03",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-03",
    },
)


@dataclass(frozen=True)
class CandidateVariant:
    name: str
    description: str


@dataclass(frozen=True)
class BundleSpec:
    bundle_role: str
    bundle_name: str
    bundle_path: str


def threeshift_probe_bundles() -> list[dict[str, str]]:
    return [dict(row) for row in THREESHIFT_PROBE_BUNDLES]


def default_candidate_variants() -> list[CandidateVariant]:
    return [
        CandidateVariant("route_compression_rebuild", "route-compression / route-rebuild"),
        CandidateVariant("stronger_insertion_repair", "criticality / regret-k / wider insertion repair"),
        CandidateVariant("ev_charging_aware_repair", "EV / charging-aware repair"),
    ]


def candidate_row_gate(row: dict[str, Any]) -> tuple[bool, str]:
    worker = str(row.get("worker_python_executable", ""))
    if worker != REQUIRED_WORKER_PYTHON:
        return False, f"worker drift: {worker}"
    numpy_version = str(row.get("worker_numpy_version", ""))
    if numpy_version != REQUIRED_WORKER_NUMPY:
        return False, f"NumPy mismatch: {numpy_version}"
    if int(row.get("violation_count", 0)) != 0:
        return False, f"violation_count={row.get('violation_count')}"
    if int(row.get("feasible_candidate_count", 0)) != int(row.get("candidate_count", 0)):
        return False, "not all generated candidate evaluations were feasible"
    if int(row.get("actual_evals", -1)) != int(row.get("eval_budget", -2)):
        return False, f"actual_evals mismatch: {row.get('actual_evals')} != {row.get('eval_budget')}"
    for key in ("baseline_obj", "best_candidate_obj", "best_relative_percent"):
        try:
            value = float(row.get(key, math.nan))
        except (TypeError, ValueError):
            return False, f"{key} is not finite"
        if not math.isfinite(value):
            return False, f"{key} is not finite"
    return True, ""


def classify_candidate_generator_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": HALT_STATUS, "reason": "no rows"}

    failed = []
    for idx, row in enumerate(rows):
        ok, reason = candidate_row_gate(row)
        if not ok:
            failed.append({"row_index": idx, "reason": reason, "bundle_name": row.get("bundle_name"), "variant": row.get("variant")})
    if failed:
        return {
            "status": "HALT_CANDIDATE_ROW_GATE",
            "failed_row_reasons": [item["reason"] for item in failed],
            "failed_rows": failed[:10],
        }

    summaries = _variant_summaries(rows)
    best = _best_variant_summary(summaries)
    if best is None:
        return {"status": HALT_STATUS, "reason": "no variant summary"}
    passes = (
        float(best["changed_rate"]) >= MIN_CHANGED_RATE
        and float(best["improving_rate"]) >= MIN_IMPROVING_RATE
        and float(best["train_mean_relative_percent"]) >= MIN_ROLE_MEAN_RELATIVE
        and float(best["held_mean_relative_percent"]) >= MIN_ROLE_MEAN_RELATIVE
        and int(best["bundle_nonworse_count"]) >= MIN_NONWORSE_BUNDLES
    )
    status = READY_STATUS if passes else HALT_STATUS
    return {
        "status": status,
        "best_variant": best["variant"],
        "candidate_count": int(best["candidate_count"]),
        "changed_rate": float(best["changed_rate"]),
        "improving_rate": float(best["improving_rate"]),
        "train_mean_relative_percent": float(best["train_mean_relative_percent"]),
        "held_mean_relative_percent": float(best["held_mean_relative_percent"]),
        "overall_mean_relative_percent": float(best["overall_mean_relative_percent"]),
        "bundle_nonworse_count": int(best["bundle_nonworse_count"]),
        "required": {
            "changed_rate": MIN_CHANGED_RATE,
            "improving_rate": MIN_IMPROVING_RATE,
            "train_mean_relative_percent": MIN_ROLE_MEAN_RELATIVE,
            "held_mean_relative_percent": MIN_ROLE_MEAN_RELATIVE,
            "bundle_nonworse_count": MIN_NONWORSE_BUNDLES,
        },
        "variant_summary": summaries,
    }


def run_surgery(
    *,
    output_dir: Path,
    seeds: Iterable[int],
    eval_budget: int,
    bundle_names: set[str] | None = None,
    variant_names: set[str] | None = None,
    include_route_elimination: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = [variant for variant in default_candidate_variants() if not variant_names or variant.name in variant_names]
    if not variants:
        raise ValueError("no candidate variants selected")
    bundles = _selected_bundles(bundle_names)
    if not bundles:
        raise ValueError("no bundles selected")
    rows: list[dict[str, Any]] = []
    partial_path = output_dir / "pilot14_candidate_rows.partial.csv"
    for bundle in bundles:
        for seed in seeds:
            for variant in variants:
                row = probe_variant(
                    bundle=bundle,
                    seed=int(seed),
                    variant=variant,
                    eval_budget=int(eval_budget),
                    include_route_elimination=include_route_elimination,
                )
                rows.append(row)
                write_rows_csv(partial_path, rows)

    variant_summary = _variant_summaries(rows)
    gate = classify_candidate_generator_gate(rows)
    summary = {
        "scope": "Pilot14 candidate-generation surgery; no PPO training",
        "bundle_names": [bundle.bundle_name for bundle in bundles],
        "seeds": [int(seed) for seed in seeds],
        "eval_budget": int(eval_budget),
        "variants": [variant.__dict__ for variant in variants],
        "row_count": len(rows),
        "gate": gate,
        "variant_summary": variant_summary,
        "rows": rows,
    }
    write_rows_csv(output_dir / "pilot14_candidate_rows.csv", rows)
    write_rows_csv(output_dir / "pilot14_variant_summary.csv", variant_summary)
    (output_dir / "pilot14_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "pilot14_candidate_generation_report.md").write_text(render_pilot14_report(summary), encoding="utf-8")
    if gate.get("status") != READY_STATUS:
        (output_dir / "HALT_CANDIDATE_GENERATOR_NO_HEADROOM.md").write_text(render_pilot14_report(summary), encoding="utf-8")
    return summary


def probe_variant(
    *,
    bundle: BundleSpec,
    seed: int,
    variant: CandidateVariant,
    eval_budget: int,
    include_route_elimination: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    search_bundle = load_search_bundle(bundle.bundle_path)
    context = EvaluationContext(
        search_bundle.instance,
        search_bundle.carbon_profile,
        budget=EvalBudget(limit=int(eval_budget), target=int(eval_budget)),
    )
    limits = infer_fleet_limits(bundle.bundle_path)
    initial = build_initial_solution(
        search_bundle.instance,
        search_bundle.carbon_profile,
        fleet_limits=limits,
        introduce_ev=False,
        require_charging_signal=False,
    )
    baseline_obj = score_reference(initial, context)
    policy = SearchPolicy(require_charging_signal=False, max_cv=limits.cv, max_ev=limits.ev)
    state = AlnsState(initial, context, objective_value=baseline_obj, policy=policy)
    candidates = _generate_candidates_for_variant(
        state=state,
        seed=int(seed),
        variant_name=variant.name,
        include_route_elimination=include_route_elimination,
        fleet_limits=limits,
    )
    return _score_candidate_batch(
        bundle=bundle,
        seed=int(seed),
        variant=variant,
        baseline=initial,
        baseline_obj=float(baseline_obj),
        context=context,
        candidates=candidates,
        eval_budget=int(eval_budget),
        elapsed_started=started,
    )


def render_pilot14_report(summary: dict[str, Any]) -> str:
    gate = dict(summary.get("gate", {}) or {})
    lines = [
        "# Pilot14 Candidate-Generation Surgery",
        "",
        f"Gate: `{gate.get('status', 'UNKNOWN')}`",
        "",
        "Scope: no PPO training, no policy performance claim, and no protected solver semantic changes.",
        "",
        "Human reading: Pilot14 checks whether the solver can create feasible changed candidates before any PPO training resumes.",
        "",
        "Instance rule: three-shift 50c/75c probes first; ordinary instances and M1 absolute numbers are out of scope.",
        "",
        "## Gate Detail",
        "",
        "```json",
        json.dumps(gate, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Variant Summary",
        "",
    ]
    for row in summary.get("variant_summary", []):
        lines.append(
            "- {variant}: candidates={candidate_count}, changed_rate={changed_rate:.4f}, improving_rate={improving_rate:.4f}, train_mean={train:.4f}%, held_mean={held:.4f}%, nonworse_bundles={nonworse}".format(
                variant=row["variant"],
                candidate_count=int(row["candidate_count"]),
                changed_rate=float(row["changed_rate"]),
                improving_rate=float(row["improving_rate"]),
                train=float(row["train_mean_relative_percent"]),
                held=float(row["held_mean_relative_percent"]),
                nonworse=int(row["bundle_nonworse_count"]),
            )
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            _decision_text(str(gate.get("status", "UNKNOWN"))),
        ]
    )
    return "\n".join(lines) + "\n"


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _generate_candidates_for_variant(
    *,
    state: AlnsState,
    seed: int,
    variant_name: str,
    include_route_elimination: bool,
    fleet_limits: FleetLimits,
) -> list[Solution]:
    if variant_name == "route_compression_rebuild":
        return _route_compression_candidates(state)
    if variant_name == "stronger_insertion_repair":
        return _stronger_insertion_candidates(state, seed=seed, include_route_elimination=include_route_elimination)
    if variant_name == "ev_charging_aware_repair":
        return _ev_charging_candidates(state, fleet_limits=fleet_limits)
    raise ValueError(f"unknown candidate variant: {variant_name}")


def generate_candidate_solutions(
    *,
    state: AlnsState,
    seed: int,
    variant_name: str,
    include_route_elimination: bool = True,
    fleet_limits: FleetLimits | None = None,
) -> list[Solution]:
    """Generate feasible Pilot14 candidate solutions for opt-in PPO diagnostics."""

    limits = fleet_limits
    if limits is None:
        limits = FleetLimits(cv=999_999, ev=999_999)
    return _generate_candidates_for_variant(
        state=state,
        seed=int(seed),
        variant_name=str(variant_name),
        include_route_elimination=bool(include_route_elimination),
        fleet_limits=limits,
    )


def _route_compression_candidates(state: AlnsState) -> list[Solution]:
    candidates: list[Solution] = []
    routes = list(state.solution.routes)
    route_order = sorted(range(len(routes)), key=lambda idx: (len(route_customers(routes[idx], state.context.instance)), idx))
    for route_idx in route_order:
        removed_route = routes[route_idx]
        pending = route_customers(removed_route, state.context.instance)
        if not pending:
            continue
        partial = Solution(
            routes=[route for idx, route in enumerate(routes) if idx != route_idx],
            charging_actions=[action for action in state.solution.charging_actions if action.vehicle_id != removed_route.vehicle_id],
            cross_site_services=state.solution.cross_site_services,
        )
        for mode in ("greedy", "regret2", "criticality"):
            repaired = _wide_complete_repair(
                partial,
                pending,
                state.context,
                state.policy,
                mode=mode,
                allow_new_route=False,
                option_rank=0,
            )
            if repaired is not None:
                candidates.append(repaired)
    return _unique_feasible_candidates(candidates, state.context)


def _stronger_insertion_candidates(
    state: AlnsState,
    *,
    seed: int,
    include_route_elimination: bool,
) -> list[Solution]:
    candidates: list[Solution] = []
    op_set = WinnerOperatorSet.create(include_route_elimination=include_route_elimination)
    customer_count = _customer_count(state.solution, state.context)
    remove_counts = sorted({max(1, int(math.ceil(customer_count * fraction))) for fraction in (0.10, 0.16, 0.23, 0.30, 0.40)})
    for destroy_index, (destroy_id, destroy_op) in enumerate(op_set.destroy_ops):
        if destroy_id == "vehicle_type_swap":
            continue
        for remove_count in remove_counts:
            rng = np.random.default_rng(int(seed) * 100_000 + destroy_index * 100 + remove_count)
            destroyed = destroy_op(state, rng, progress=0.0, remove_count_q=remove_count)
            pending = list(destroyed.removed_customers)
            if not pending:
                continue
            for mode in ("greedy", "regret2", "regret3", "criticality"):
                for option_rank in (0, 1, -1):
                    repaired = _wide_complete_repair(
                        destroyed.solution,
                        pending,
                        destroyed.context,
                        destroyed.policy,
                        mode=mode,
                        allow_new_route=destroyed.allow_new_route_repair,
                        option_rank=option_rank,
                    )
                    if repaired is not None:
                        candidates.append(repaired)
    return _unique_feasible_candidates(candidates, state.context)


def _ev_charging_candidates(state: AlnsState, *, fleet_limits: FleetLimits) -> list[Solution]:
    candidates: list[Solution] = []
    ev_routes = sum(1 for route in state.solution.routes if route.vehicle_type.lower() == "ev")
    if ev_routes >= fleet_limits.ev:
        return candidates
    for route_idx, route in enumerate(state.solution.routes):
        if route.vehicle_type.lower() != "cv":
            continue
        ev_id = f"EV_P14_{route_idx + 1}"
        ev_route = Route(ev_id, "ev", route.home_depot_id, list(route.node_sequence))
        try:
            repaired_route, actions = repair_route_charging(ev_route, state.context.instance, state.context.carbon_profile, state.context.prices)
        except ValueError:
            continue
        routes = list(state.solution.routes)
        routes[route_idx] = repaired_route
        candidate = Solution(
            routes=routes,
            charging_actions=[
                action for action in state.solution.charging_actions if action.vehicle_id != route.vehicle_id
            ]
            + actions,
            cross_site_services=state.solution.cross_site_services,
        )
        try:
            candidate = normalize_solution_vehicle_trips(candidate, state.context.instance, max_cv=fleet_limits.cv, max_ev=fleet_limits.ev)
        except ValueError:
            continue
        candidates.append(candidate)
    return _unique_feasible_candidates(candidates, state.context)


def _wide_complete_repair(
    partial_solution: Solution,
    pending_customers: list[str],
    context: EvaluationContext,
    policy: SearchPolicy,
    *,
    mode: str,
    allow_new_route: bool,
    option_rank: int,
) -> Solution | None:
    current = partial_solution
    pending = list(dict.fromkeys(pending_customers))
    guard = 0
    while pending:
        guard += 1
        if guard > 500:
            return None
        selection = _select_next_insertion(
            current,
            pending,
            context,
            policy,
            mode=mode,
            allow_new_route=allow_new_route,
            option_rank=option_rank,
        )
        if selection is None:
            return None
        customer_id, next_solution = selection
        current = next_solution
        pending.remove(customer_id)
    if check_solution(current, context.instance, context.prices):
        return None
    try:
        return normalize_solution_vehicle_trips(current, context.instance, max_cv=policy.max_cv, max_ev=policy.max_ev)
    except ValueError:
        return None


def _select_next_insertion(
    solution: Solution,
    pending: list[str],
    context: EvaluationContext,
    policy: SearchPolicy,
    *,
    mode: str,
    allow_new_route: bool,
    option_rank: int,
) -> tuple[str, Solution] | None:
    rows: list[tuple[float, float, str, Solution]] = []
    node_lookup = {node.node_id: node for node in context.instance.nodes}
    for customer_id in pending:
        options = enumerate_feasible_insertions(
            solution,
            customer_id,
            context,
            policy,
            max_route_candidates=10_000,
            max_positions_per_route=10_000,
            allow_new_route=allow_new_route,
        )
        if not options:
            continue
        rank = _bounded_option_rank(option_rank, len(options))
        chosen = options[rank]
        scores = [float(option.score) for option in options]
        best = scores[0]
        if mode == "greedy":
            primary = chosen.score
        elif mode == "regret2":
            comparison = scores[1] if len(scores) > 1 else scores[0]
            primary = -(comparison - best)
        elif mode == "regret3":
            comparison = scores[2] if len(scores) > 2 else scores[-1]
            primary = -(comparison - best)
        elif mode == "criticality":
            node = node_lookup[customer_id]
            tw_width = max(1.0, float(node.due_time) - float(node.ready_time))
            primary = -(float(node.demand) / tw_width)
        else:
            raise ValueError(f"unknown Pilot14 repair mode: {mode}")
        rows.append((float(primary), float(chosen.score), customer_id, chosen.solution))
    if not rows:
        return None
    _, _, customer_id, next_solution = min(rows, key=lambda item: (item[0], item[1], item[2]))
    return customer_id, next_solution


def _score_candidate_batch(
    *,
    bundle: BundleSpec,
    seed: int,
    variant: CandidateVariant,
    baseline: Solution,
    baseline_obj: float,
    context: EvaluationContext,
    candidates: list[Solution],
    eval_budget: int,
    elapsed_started: float,
) -> dict[str, Any]:
    feasible_count = 0
    changed_count = 0
    improving_count = 0
    violation_count = 0
    best_obj = float(baseline_obj)
    best_changed_obj = math.inf
    unique_candidates = len(candidates)
    for eval_idx in range(int(eval_budget)):
        candidate = candidates[eval_idx] if eval_idx < len(candidates) else baseline
        violations = check_solution(candidate, context.instance, context.prices)
        if violations:
            violation_count += len(violations)
        else:
            feasible_count += 1
        obj = float(score_candidate(candidate, context))
        changed = bool(_solution_changed(baseline, candidate))
        if changed and not violations:
            changed_count += 1
            best_changed_obj = min(best_changed_obj, obj)
        if changed and not violations and obj < float(baseline_obj) - 1e-9:
            improving_count += 1
        best_obj = min(best_obj, obj)
    actual_evals = int(context.budget.count if context.budget else eval_budget)
    best_relative = _paired_relative_percent(candidate_cost=best_obj, baseline_cost=baseline_obj)
    return {
        "bundle_role": bundle.bundle_role,
        "bundle_name": bundle.bundle_name,
        "bundle_path": bundle.bundle_path,
        "seed": int(seed),
        "variant": variant.name,
        "variant_description": variant.description,
        "worker_python_executable": sys.executable,
        "worker_numpy_version": np.__version__,
        "eval_budget": int(eval_budget),
        "actual_evals": int(actual_evals),
        "candidate_count": int(eval_budget),
        "unique_candidate_count": int(unique_candidates),
        "feasible_candidate_count": int(feasible_count),
        "changed_candidate_count": int(changed_count),
        "improving_candidate_count": int(improving_count),
        "violation_count": int(violation_count),
        "baseline_obj": float(baseline_obj),
        "best_candidate_obj": float(best_obj),
        "best_changed_candidate_obj": float(best_changed_obj),
        "best_relative_percent": float(best_relative),
        "baseline_route_count": int(len(baseline.routes)),
        "best_route_count": None,
        "elapsed_seconds": float(time.perf_counter() - elapsed_started),
    }


def _variant_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["variant"]), []).append(row)
    summaries: list[dict[str, Any]] = []
    for variant, values in sorted(grouped.items()):
        candidate_count = sum(int(row["candidate_count"]) for row in values)
        changed_count = sum(int(row["changed_candidate_count"]) for row in values)
        improving_count = sum(int(row["improving_candidate_count"]) for row in values)
        train_rel = [float(row["best_relative_percent"]) for row in values if row["bundle_role"] == "train_probe"]
        held_rel = [float(row["best_relative_percent"]) for row in values if row["bundle_role"] == "held_probe"]
        bundle_means = _bundle_mean_relatives(values)
        summaries.append(
            {
                "variant": variant,
                "rows": len(values),
                "candidate_count": int(candidate_count),
                "unique_candidate_count": sum(int(row.get("unique_candidate_count", 0)) for row in values),
                "changed_candidate_count": int(changed_count),
                "improving_candidate_count": int(improving_count),
                "changed_rate": 0.0 if candidate_count == 0 else changed_count / candidate_count,
                "improving_rate": 0.0 if candidate_count == 0 else improving_count / candidate_count,
                "train_mean_relative_percent": mean(train_rel) if train_rel else -math.inf,
                "held_mean_relative_percent": mean(held_rel) if held_rel else -math.inf,
                "overall_mean_relative_percent": mean(float(row["best_relative_percent"]) for row in values),
                "bundle_nonworse_count": sum(1 for value in bundle_means.values() if value >= -1e-9),
                "bundle_mean_relatives": bundle_means,
            }
        )
    return summaries


def _best_variant_summary(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not summaries:
        return None
    return max(
        summaries,
        key=lambda row: (
            float(row["train_mean_relative_percent"]) >= MIN_ROLE_MEAN_RELATIVE
            and float(row["held_mean_relative_percent"]) >= MIN_ROLE_MEAN_RELATIVE,
            float(row["overall_mean_relative_percent"]),
            float(row["changed_rate"]),
            float(row["improving_rate"]),
        ),
    )


def _bundle_mean_relatives(rows: list[dict[str, Any]]) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(row["bundle_name"]), []).append(float(row["best_relative_percent"]))
    return {name: mean(values) for name, values in sorted(grouped.items())}


def _unique_feasible_candidates(candidates: list[Solution], context: EvaluationContext) -> list[Solution]:
    out: list[Solution] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in candidates:
        if check_solution(candidate, context.instance, context.prices):
            continue
        key = _solution_signature(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _solution_signature(solution: Solution) -> tuple[Any, ...]:
    return (
        tuple((route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence)) for route in solution.routes),
        tuple(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.charge_start_second), 3),
                round(float(action.energy_kwh), 3),
            )
            for action in solution.charging_actions
        ),
    )


def _customer_count(solution: Solution, context: EvaluationContext) -> int:
    node_types = {node.node_id: node.node_type.lower() for node in context.instance.nodes}
    return sum(1 for route in solution.routes for node_id in route.node_sequence if node_types.get(node_id) == "c")


def _bounded_option_rank(rank: int, count: int) -> int:
    if count <= 0:
        raise ValueError("count must be positive")
    if rank < 0:
        return count - 1
    return min(int(rank), count - 1)


def _paired_relative_percent(*, candidate_cost: float, baseline_cost: float) -> float:
    baseline = float(baseline_cost)
    candidate = float(candidate_cost)
    if not math.isfinite(baseline) or abs(baseline) <= 1e-12:
        raise ValueError(f"baseline_cost must be finite and non-zero: {baseline_cost!r}")
    if not math.isfinite(candidate):
        raise ValueError(f"candidate_cost must be finite: {candidate_cost!r}")
    return (baseline - candidate) / baseline * 100.0


def _selected_bundles(bundle_names: set[str] | None) -> list[BundleSpec]:
    specs = [BundleSpec(**row) for row in threeshift_probe_bundles()]
    if bundle_names:
        specs = [spec for spec in specs if spec.bundle_name in bundle_names]
    return specs


def _parse_csv_set(value: str) -> set[str] | None:
    parsed = {item.strip() for item in str(value).split(",") if item.strip()}
    return parsed or None


def _parse_seeds(value: str) -> list[int]:
    return [int(item.strip()) for item in str(value).split(",") if item.strip()]


def _decision_text(status: str) -> str:
    if status == READY_STATUS:
        return (
            "Candidate generation has enough measurable headroom to design an opt-in PPO action interface. "
            "This is not yet a PPO-training success claim; the next gate is a short PPO smoke that proves the new action head is used and creates changed feasible candidates."
        )
    if status == READY_FOR_TRAINING_STATUS:
        return "Pilot14 has passed both candidate-generation and PPO-smoke gates. PPO training may start in a separate authorized run."
    if status == "HALT_CANDIDATE_ROW_GATE":
        return "A row failed the runtime/feasibility/budget gate. Stop and inspect the failed rows before any training."
    return (
        "The literature-backed candidate generator did not create enough improving changed candidates. "
        "Do not train PPO on this interface; either redesign repair/construction again or stop the DR lane."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pilot14 candidate-generation surgery diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run candidate-generation surgery gate")
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--seeds", default="1,2,3")
    run.add_argument("--eval-budget", type=int, default=300)
    run.add_argument("--bundle-names", default="")
    run.add_argument("--variants", default="")
    run.add_argument("--no-route-elimination", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        summary = run_surgery(
            output_dir=args.output_dir,
            seeds=_parse_seeds(args.seeds),
            eval_budget=int(args.eval_budget),
            bundle_names=_parse_csv_set(args.bundle_names),
            variant_names=_parse_csv_set(args.variants),
            include_route_elimination=not bool(args.no_route_elimination),
        )
        print(json.dumps({"gate": summary["gate"], "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))
        return 0
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
