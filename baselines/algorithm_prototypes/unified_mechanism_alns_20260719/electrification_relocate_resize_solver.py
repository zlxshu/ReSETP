"""Mechanism-specific cross-route relief for near-electrifiable CV routes.

The operator is deliberately terminal and bounded.  It does not start a new
ALNS/HGS search.  A short customer string is moved out of a CV route, the two
affected routes are reset to a neutral CV representation, and the frozen v7
terminal completion jointly reselects responsibility, vehicle types, charging,
and charging time.  A move is accepted only when complete cost decreases and
the number of CV routes decreases.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any

from setp_solver.algorithms.resetp_alns.support.fleet import (
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Route, Solution
from terminal_completion import apply_terminal_completion
from v4_mechanism_alns_solver import _route_variants
from v7_responsibility_solver import annotate_cross_site_services


TOL = 1.0e-9


@dataclass(frozen=True)
class ElectrificationRelocateResizeConfig:
    max_segment_length: int = 2
    insertion_positions_per_target: int = 2
    prescore_capacity: int = 12
    exact_capacity: int = 3
    max_rounds: int = 2


@dataclass(frozen=True)
class ElectrificationCandidate:
    source_index: int
    target_index: int
    segment_start: int
    segment: tuple[str, ...]
    insertion_position: int
    neutral_solution: Solution
    neutral_full_content_sha256: str
    prescore_delta: float
    declared_transfer_verified: bool

    @property
    def sort_key(self) -> tuple[Any, ...]:
        return (
            float(self.prescore_delta),
            int(self.source_index),
            int(self.target_index),
            len(self.segment),
            int(self.segment_start),
            int(self.insertion_position),
            self.neutral_full_content_sha256,
        )


@dataclass(frozen=True)
class ElectrificationRelocateResizeResult:
    solution: Solution
    cost: float
    source_cost: float
    feasible: bool
    changed: bool
    activity: dict[str, Any]


def apply_electrification_relocate_resize(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    prices: Any = DEFAULT_PRICES,
    config: ElectrificationRelocateResizeConfig | None = None,
) -> ElectrificationRelocateResizeResult:
    """Apply at most two protected relocate-resize rounds."""

    cfg = config or ElectrificationRelocateResizeConfig()
    _validate_config(cfg)
    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    source_cost = _model_cost(solution, context)
    _require_finite("source_cost", source_cost)
    source_violations = check_solution(solution, bundle.instance, prices)
    if source_violations:
        raise ValueError(
            "electrification relocate-resize source is infeasible: "
            f"{source_violations[:8]}"
        )

    best = solution
    objective = float(source_cost)
    activity: dict[str, Any] = {
        "enumerated_moves": 0,
        "neutral_feasible_moves": 0,
        "unique_neutral_moves": 0,
        "distance_insertion_evaluations": 0,
        "route_proxy_evaluations": 0,
        "route_proxy_cache_hits": 0,
        "prescored_moves": 0,
        "prescore_selected_moves": 0,
        "terminal_completion_calls": 0,
        "terminal_full_solution_replays": 0,
        "terminal_route_local_exact_evaluations": 0,
        "terminal_route_proxy_evaluations": 0,
        "terminal_route_local_schedule_evaluations": 0,
        "terminal_feasibility_checks": 0,
        "counterfactual_terminal_completion_calls": 0,
        "counterfactual_full_solution_replays": 0,
        "counterfactual_route_local_exact_evaluations": 0,
        "counterfactual_route_proxy_evaluations": 0,
        "counterfactual_route_local_schedule_evaluations": 0,
        "counterfactual_feasibility_checks": 0,
        "counterfactual_independent_replays": 0,
        "exact_candidate_independent_replays": 0,
        "exact_candidate_feasibility_checks": 0,
        "source_full_solution_replays": 1,
        "source_feasibility_checks": 1,
        "neutral_candidate_attempts": 0,
        "neutral_feasibility_checks": 0,
        "neutral_normalization_failures": 0,
        "final_independent_replays": 0,
        "final_feasibility_checks": 0,
        "terminal_activity_records": [],
        "counterfactual_activity_records": [],
        "candidate_fail_closed": [],
        "enumeration_fail_closed": [],
        "nonfinite_prescore_rejections": 0,
        "accepted_moves": [],
        "exact_candidates": [],
        "round_summaries": [],
        "complete_route_search_evaluations": 0,
        "source_cv_route_count": _cv_route_count(solution),
    }

    for round_index in range(cfg.max_rounds):
        round_source = best
        round_source_cost = float(objective)
        round_source_hash = _full_content_hash(round_source)
        round_source_semantic = _semantic_hash(round_source)
        round_source_vehicle_types = [
            route.vehicle_type.lower() for route in round_source.routes
        ]
        nonfinite_before = int(
            activity["nonfinite_prescore_rejections"]
        )
        try:
            candidates = _enumerate_candidates(
                round_source,
                context,
                owners,
                cfg,
                activity,
            )
        except (ArithmeticError, RuntimeError, ValueError) as exc:
            activity["enumeration_fail_closed"].append(
                {
                    "round": round_index + 1,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            activity["stop_reason"] = "enumeration_failed_closed"
            break
        selected = candidates[: cfg.prescore_capacity]
        activity["prescore_selected_moves"] += len(selected)
        round_summary = {
            "round": round_index + 1,
            "unique_candidates": len(candidates),
            "prescore_selected": len(selected),
            "exact_attempted": min(
                len(selected),
                cfg.exact_capacity,
            ),
            "eligible_candidates": 0,
            "accepted": False,
            "counterfactual_started": False,
            "nonfinite_prescore_rejections": (
                int(activity["nonfinite_prescore_rejections"])
                - nonfinite_before
            ),
        }
        if round_summary["nonfinite_prescore_rejections"] > 0:
            activity["round_summaries"].append(round_summary)
            activity["stop_reason"] = (
                "nonfinite_prescore_failed_round_closed"
            )
            break
        if not selected:
            activity["round_summaries"].append(round_summary)
            activity["stop_reason"] = "no_prescored_candidate"
            break

        try:
            activity["counterfactual_terminal_completion_calls"] += 1
            counterfactual = apply_terminal_completion(
                bundle_dir,
                round_source,
                prices=prices,
            )
            _accumulate_terminal_activity(
                activity,
                counterfactual.activity,
                kind="counterfactual",
                round_index=round_index + 1,
            )
            counterfactual_recomputed = _model_cost(
                counterfactual.solution,
                context,
            )
            activity["counterfactual_full_solution_replays"] += 1
            activity["counterfactual_independent_replays"] += 1
            counterfactual_violations = check_solution(
                counterfactual.solution,
                bundle.instance,
                prices,
            )
            activity["counterfactual_feasibility_checks"] += 1
            _require_finite(
                "counterfactual_cost",
                counterfactual.cost,
                counterfactual_recomputed,
            )
            counterfactual_error = abs(
                counterfactual_recomputed - counterfactual.cost
            )
            if (
                not counterfactual.feasible
                or counterfactual_violations
                or counterfactual_error > 1.0e-7
            ):
                raise RuntimeError(
                    "source-only terminal counterfactual did not close"
                )
        except (ArithmeticError, RuntimeError, ValueError) as exc:
            round_summary["counterfactual_error"] = {
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
            activity["round_summaries"].append(round_summary)
            activity["stop_reason"] = "counterfactual_failed_closed"
            break

        counterfactual_cost = float(counterfactual_recomputed)
        counterfactual_cv = _cv_route_count(counterfactual.solution)
        round_summary.update(
            {
                "counterfactual_started": True,
                "counterfactual_cost": counterfactual_cost,
                "counterfactual_cost_delta": (
                    counterfactual_cost - round_source_cost
                ),
                "counterfactual_cv_routes": counterfactual_cv,
                "counterfactual_full_content_sha256": (
                    _full_content_hash(counterfactual.solution)
                ),
                "counterfactual_semantic_sha256": _semantic_hash(
                    counterfactual.solution
                ),
                "counterfactual_independent_replay_error": (
                    counterfactual_error
                ),
                "counterfactual_solution_snapshot": asdict(
                    counterfactual.solution
                ),
            }
        )
        exact_rows: list[
            tuple[
                float,
                tuple[Any, ...],
                ElectrificationCandidate,
                Any,
                dict[str, Any],
            ]
        ] = []
        before_cv = _cv_route_count(round_source)
        before_skeleton = _route_skeleton_hash(
            round_source,
            context.instance,
        )
        for candidate in selected[: cfg.exact_capacity]:
            base_row = {
                "round": round_index + 1,
                "source_index": candidate.source_index,
                "target_index": candidate.target_index,
                "segment_start": candidate.segment_start,
                "segment": list(candidate.segment),
                "insertion_position": candidate.insertion_position,
                "source_full_content_sha256": round_source_hash,
                "source_semantic_sha256": round_source_semantic,
                "source_vehicle_types": round_source_vehicle_types,
                "source_solution_snapshot": asdict(round_source),
                "neutral_full_content_sha256": (
                    candidate.neutral_full_content_sha256
                ),
                "neutral_semantic_sha256": _semantic_hash(
                    candidate.neutral_solution
                ),
                "neutral_solution_snapshot": asdict(
                    candidate.neutral_solution
                ),
                "declared_transfer_verified_before_completion": (
                    candidate.declared_transfer_verified
                ),
                "prescore_delta": float(candidate.prescore_delta),
                "counterfactual_cost": counterfactual_cost,
                "counterfactual_cv_routes": counterfactual_cv,
                "counterfactual_source_route_vehicle_type": (
                    _route_vehicle_type(
                        counterfactual.solution,
                        candidate.source_index,
                    )
                ),
            }
            try:
                activity["terminal_completion_calls"] += 1
                completion = apply_terminal_completion(
                    bundle_dir,
                    candidate.neutral_solution,
                    prices=prices,
                )
                _accumulate_terminal_activity(
                    activity,
                    completion.activity,
                    kind="candidate",
                    round_index=round_index + 1,
                )
                candidate_recomputed = _model_cost(
                    completion.solution,
                    context,
                )
                activity["exact_candidate_independent_replays"] += 1
                candidate_violations = check_solution(
                    completion.solution,
                    bundle.instance,
                    prices,
                )
                activity["exact_candidate_feasibility_checks"] += 1
                _require_finite(
                    "candidate_complete_cost",
                    completion.cost,
                    candidate_recomputed,
                )
                closure_error = abs(
                    candidate_recomputed - completion.cost
                )
                if closure_error > 1.0e-7:
                    raise RuntimeError(
                        "candidate terminal objective did not close"
                    )
            except (ArithmeticError, RuntimeError, ValueError) as exc:
                failure_row = {
                    **base_row,
                    "eligible": False,
                    "candidate_failed_closed": True,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
                activity["candidate_fail_closed"].append(failure_row)
                activity["exact_candidates"].append(failure_row)
                continue

            after_cv = _cv_route_count(completion.solution)
            after_skeleton = _route_skeleton_hash(
                completion.solution,
                context.instance,
            )
            structure_changed = after_skeleton != before_skeleton
            completed_transfer_verified = (
                _completed_transfer_holds(
                    completion.solution,
                    context.instance,
                    candidate.source_index,
                    candidate.target_index,
                    candidate.segment,
                )
            )
            source_route_cv_before = (
                round_source.routes[
                    candidate.source_index
                ].vehicle_type.lower()
                == "cv"
            )
            source_route_ev_after = (
                _route_vehicle_type(
                    completion.solution,
                    candidate.source_index,
                )
                == "ev"
            )
            counterfactual_source_stays_cv = (
                _route_vehicle_type(
                    counterfactual.solution,
                    candidate.source_index,
                )
                == "cv"
            )
            eligible = bool(
                completion.feasible
                and not candidate_violations
                and candidate_recomputed < objective - TOL
                and candidate_recomputed < counterfactual_cost - TOL
                and after_cv <= before_cv - 1
                and after_cv <= counterfactual_cv - 1
                and candidate.declared_transfer_verified
                and completed_transfer_verified
                and source_route_cv_before
                and source_route_ev_after
                and counterfactual_source_stays_cv
            )
            row = {
                **base_row,
                "candidate_failed_closed": False,
                "completed_cost": float(candidate_recomputed),
                "completion_claimed_cost": float(completion.cost),
                "independent_replay_error": float(closure_error),
                "complete_cost_delta": float(
                    candidate_recomputed - objective
                ),
                "counterfactual_cost_delta": float(
                    candidate_recomputed - counterfactual_cost
                ),
                "cv_routes_before": before_cv,
                "cv_routes_after": after_cv,
                "cv_routes_counterfactual": counterfactual_cv,
                "route_structure_before_sha256": before_skeleton,
                "route_structure_after_sha256": after_skeleton,
                "route_structure_changed": structure_changed,
                "completed_full_content_sha256": _full_content_hash(
                    completion.solution
                ),
                "completed_semantic_sha256": _semantic_hash(
                    completion.solution
                ),
                "completed_solution_snapshot": asdict(
                    completion.solution
                ),
                "completed_transfer_verified": (
                    completed_transfer_verified
                ),
                "source_route_vehicle_type_before": (
                    round_source.routes[
                        candidate.source_index
                    ].vehicle_type.lower()
                ),
                "source_route_vehicle_type_after": (
                    _route_vehicle_type(
                        completion.solution,
                        candidate.source_index,
                    )
                ),
                "target_route_vehicle_type_before": (
                    round_source.routes[
                        candidate.target_index
                    ].vehicle_type.lower()
                ),
                "target_route_vehicle_type_after": (
                    _route_vehicle_type(
                        completion.solution,
                        candidate.target_index,
                    )
                ),
                "counterfactual_source_stays_cv": (
                    counterfactual_source_stays_cv
                ),
                "eligible": eligible,
                "selected_branch": completion.selected_branch,
            }
            activity["exact_candidates"].append(row)
            if eligible:
                round_summary["eligible_candidates"] += 1
                exact_rows.append(
                    (
                        float(candidate_recomputed),
                        candidate.sort_key,
                        candidate,
                        completion,
                        row,
                    )
                )
        activity["round_summaries"].append(round_summary)
        if not exact_rows:
            activity["stop_reason"] = "no_strict_cost_and_cv_improvement"
            break

        _, _, accepted, completion, accepted_row = min(
            exact_rows,
            key=lambda item: (item[0], item[1]),
        )
        prior_cost = objective
        prior_cv = before_cv
        best = completion.solution
        objective = float(accepted_row["completed_cost"])
        round_summary["accepted"] = True
        activity["accepted_moves"].append(
            {
                **accepted_row,
                "cost_before": float(prior_cost),
                "cost_after": float(objective),
                "objective_delta": float(objective - prior_cost),
                "cv_routes_before": prior_cv,
                "cv_routes_after": _cv_route_count(best),
                "route_structure_before_sha256": before_skeleton,
                "route_structure_after_sha256": _route_skeleton_hash(
                    best,
                    context.instance,
                ),
                "vehicle_types_before": round_source_vehicle_types,
                "vehicle_types_after": [
                    route.vehicle_type.lower() for route in best.routes
                ],
            }
        )
    else:
        activity["stop_reason"] = "round_limit_reached"

    try:
        recomputed = _model_cost(best, context)
        activity["final_independent_replays"] += 1
        _require_finite("final_cost", objective, recomputed)
        if abs(recomputed - objective) > 1.0e-7:
            raise RuntimeError(
                "electrification relocate-resize objective mismatch: "
                f"{objective} != {recomputed}"
            )
        if recomputed > source_cost + TOL:
            raise RuntimeError(
                "electrification relocate-resize violated monotone "
                f"envelope: {recomputed} > {source_cost}"
            )
        violations = check_solution(best, bundle.instance, prices)
        activity["final_feasibility_checks"] += 1
        if violations:
            raise RuntimeError(
                "final solution infeasible: "
                f"{violations[:8]}"
            )
    except (ArithmeticError, RuntimeError, ValueError) as exc:
        activity["discarded_infeasible_accepted_moves"] = list(
            activity["accepted_moves"]
        )
        activity["accepted_moves"] = []
        activity["final_fail_closed"] = {
            "reason": "final_validation_failed_closed",
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
        best = solution
        recomputed = float(source_cost)
        objective = float(source_cost)
        violations = []
    activity["final_recomputed_cost"] = float(recomputed)
    activity["objective_closure_error"] = abs(recomputed - objective)
    activity["final_cv_route_count"] = _cv_route_count(best)
    activity["elapsed_seconds"] = time.perf_counter() - started
    activity["config"] = asdict(cfg)
    activity["changed"] = bool(activity["accepted_moves"])
    activity["total_terminal_completion_calls"] = (
        int(activity["terminal_completion_calls"])
        + int(activity["counterfactual_terminal_completion_calls"])
    )
    activity["total_full_solution_replays"] = sum(
        int(activity[name])
        for name in (
            "source_full_solution_replays",
            "terminal_full_solution_replays",
            "counterfactual_full_solution_replays",
            "exact_candidate_independent_replays",
            "final_independent_replays",
        )
    )
    activity["total_feasibility_checks"] = sum(
        int(activity[name])
        for name in (
            "source_feasibility_checks",
            "neutral_feasibility_checks",
            "terminal_feasibility_checks",
            "counterfactual_feasibility_checks",
            "exact_candidate_feasibility_checks",
            "final_feasibility_checks",
        )
    )
    return ElectrificationRelocateResizeResult(
        solution=best,
        cost=float(recomputed),
        source_cost=float(source_cost),
        feasible=not violations,
        changed=bool(activity["accepted_moves"]),
        activity=activity,
    )


def _enumerate_candidates(
    solution: Solution,
    context: EvaluationContext,
    owners: dict[str, str],
    config: ElectrificationRelocateResizeConfig,
    activity: dict[str, Any],
) -> list[ElectrificationCandidate]:
    route_customers = [
        _customer_ids(route, context.instance) for route in solution.routes
    ]
    baseline_proxy = {
        index: _best_existing_route_proxy(route, solution, context, activity)
        for index, route in enumerate(solution.routes)
    }
    local_cache: dict[
        tuple[str, tuple[str, ...]],
        tuple[float, str],
    ] = {}
    unique: dict[str, ElectrificationCandidate] = {}
    for source_index, source_route in enumerate(solution.routes):
        if source_route.vehicle_type.lower() != "cv":
            continue
        source_customers = route_customers[source_index]
        max_length = min(
            config.max_segment_length,
            len(source_customers) - 1,
        )
        for segment_length in range(1, max_length + 1):
            for segment_start in range(
                len(source_customers) - segment_length + 1
            ):
                segment = tuple(
                    source_customers[
                        segment_start : segment_start + segment_length
                    ]
                )
                reduced_source = [
                    customer
                    for index, customer in enumerate(source_customers)
                    if not (
                        segment_start
                        <= index
                        < segment_start + segment_length
                    )
                ]
                for target_index, target_route in enumerate(solution.routes):
                    if target_index == source_index:
                        continue
                    target_customers = route_customers[target_index]
                    positions = _best_insertion_positions(
                        target_route.home_depot_id,
                        target_customers,
                        segment,
                        context,
                        count=config.insertion_positions_per_target,
                        activity=activity,
                    )
                    for insertion_position in positions:
                        activity["enumerated_moves"] += 1
                        expanded_target = list(target_customers)
                        expanded_target[
                            insertion_position:insertion_position
                        ] = segment
                        neutral = _neutral_candidate(
                            solution,
                            context,
                            owners,
                            source_index,
                            reduced_source,
                            target_index,
                            expanded_target,
                            activity,
                        )
                        if neutral is None:
                            continue
                        declared_transfer_verified = (
                            _declared_transfer_holds(
                                solution,
                                neutral,
                                context.instance,
                                source_index,
                                target_index,
                                segment_start,
                                segment,
                                insertion_position,
                            )
                        )
                        if not declared_transfer_verified:
                            activity["candidate_fail_closed"].append(
                                {
                                    "stage": "neutral_transfer_proof",
                                    "source_index": source_index,
                                    "target_index": target_index,
                                    "segment_start": segment_start,
                                    "segment": list(segment),
                                    "insertion_position": (
                                        insertion_position
                                    ),
                                }
                            )
                            continue
                        activity["neutral_feasible_moves"] += 1
                        exact = _full_content_hash(neutral)
                        try:
                            source_proxy = _best_neutral_route_proxy(
                                neutral.routes[source_index],
                                context,
                                local_cache,
                                activity,
                            )
                            target_proxy = _best_neutral_route_proxy(
                                neutral.routes[target_index],
                                context,
                                local_cache,
                                activity,
                            )
                            cross_delta = (
                                len(neutral.cross_site_services)
                                - len(solution.cross_site_services)
                            ) * _price(
                                context.prices,
                                "cross_site_cost",
                            )
                            delta = (
                                source_proxy
                                + target_proxy
                                - baseline_proxy[source_index]
                                - baseline_proxy[target_index]
                                + cross_delta
                            )
                            _require_finite(
                                "candidate_prescore",
                                delta,
                            )
                        except (
                            ArithmeticError,
                            RuntimeError,
                            ValueError,
                        ):
                            activity[
                                "nonfinite_prescore_rejections"
                            ] += 1
                            continue
                        candidate = ElectrificationCandidate(
                            source_index=source_index,
                            target_index=target_index,
                            segment_start=segment_start,
                            segment=segment,
                            insertion_position=insertion_position,
                            neutral_solution=neutral,
                            neutral_full_content_sha256=exact,
                            prescore_delta=float(delta),
                            declared_transfer_verified=(
                                declared_transfer_verified
                            ),
                        )
                        prior = unique.get(exact)
                        if prior is None or candidate.sort_key < prior.sort_key:
                            unique[exact] = candidate
    activity["unique_neutral_moves"] += len(unique)
    activity["prescored_moves"] += len(unique)
    return sorted(unique.values(), key=lambda item: item.sort_key)


def _neutral_candidate(
    solution: Solution,
    context: EvaluationContext,
    owners: dict[str, str],
    source_index: int,
    source_customers: list[str],
    target_index: int,
    target_customers: list[str],
    activity: dict[str, Any],
) -> Solution | None:
    activity["neutral_candidate_attempts"] += 1
    routes = list(solution.routes)
    changed_ids = {
        routes[source_index].vehicle_id,
        routes[target_index].vehicle_id,
    }
    for index, customers in (
        (source_index, source_customers),
        (target_index, target_customers),
    ):
        route = routes[index]
        routes[index] = replace(
            route,
            vehicle_type="cv",
            node_sequence=[
                route.home_depot_id,
                *customers,
                route.home_depot_id,
            ],
        )
    neutral = Solution(
        routes=routes,
        charging_actions=[
            action
            for action in solution.charging_actions
            if action.vehicle_id not in changed_ids
        ],
        cross_site_services=list(solution.cross_site_services),
    )
    try:
        neutral = normalize_solution_vehicle_trips(
            neutral,
            context.instance,
        )
    except ValueError:
        activity["neutral_normalization_failures"] += 1
        return None
    neutral = annotate_cross_site_services(neutral, owners)
    violations = check_solution(
        neutral,
        context.instance,
        context.prices,
    )
    activity["neutral_feasibility_checks"] += 1
    return None if violations else neutral


def _declared_transfer_holds(
    before: Solution,
    neutral: Solution,
    instance: Any,
    source_index: int,
    target_index: int,
    segment_start: int,
    segment: tuple[str, ...],
    insertion_position: int,
) -> bool:
    """Prove that neutralisation changed only the declared customer transfer."""

    if (
        source_index == target_index
        or source_index < 0
        or target_index < 0
        or len(before.routes) != len(neutral.routes)
        or source_index >= len(before.routes)
        or target_index >= len(before.routes)
        or before.routes[source_index].vehicle_type.lower() != "cv"
        or neutral.routes[source_index].vehicle_type.lower() != "cv"
        or neutral.routes[target_index].vehicle_type.lower() != "cv"
    ):
        return False
    before_customers = [
        _customer_ids(route, instance) for route in before.routes
    ]
    neutral_customers = [
        _customer_ids(route, instance) for route in neutral.routes
    ]
    declared = list(segment)
    source_before = before_customers[source_index]
    if (
        not declared
        or source_before[
            segment_start : segment_start + len(declared)
        ]
        != declared
    ):
        return False
    expected_source = (
        source_before[:segment_start]
        + source_before[segment_start + len(declared) :]
    )
    target_before = before_customers[target_index]
    if not 0 <= insertion_position <= len(target_before):
        return False
    expected_target = list(target_before)
    expected_target[insertion_position:insertion_position] = declared
    for index, (prior, after) in enumerate(
        zip(before_customers, neutral_customers)
    ):
        expected = prior
        if index == source_index:
            expected = expected_source
        elif index == target_index:
            expected = expected_target
        if after != expected:
            return False
        if (
            neutral.routes[index].home_depot_id
            != before.routes[index].home_depot_id
        ):
            return False
    return True


def _completed_transfer_holds(
    completed: Solution,
    instance: Any,
    source_index: int,
    target_index: int,
    segment: tuple[str, ...],
) -> bool:
    """Prove the terminal experts did not undo the declared transfer."""

    if (
        source_index == target_index
        or source_index < 0
        or target_index < 0
        or source_index >= len(completed.routes)
        or target_index >= len(completed.routes)
        or not segment
    ):
        return False
    source = _customer_ids(completed.routes[source_index], instance)
    target = _customer_ids(completed.routes[target_index], instance)
    declared = list(segment)
    if any(customer in source for customer in declared):
        return False
    contiguous = any(
        target[index : index + len(declared)] == declared
        for index in range(len(target) - len(declared) + 1)
    )
    return contiguous and all(
        target.count(customer) == 1 for customer in declared
    )


def _accumulate_terminal_activity(
    activity: dict[str, Any],
    terminal: dict[str, Any],
    *,
    kind: str,
    round_index: int,
) -> None:
    """Aggregate every terminal ledger, including route-search evidence."""

    required = {
        "full_solution_replays",
        "route_local_exact_evaluations",
        "route_proxy_evaluations",
        "route_local_schedule_evaluations",
        "full_feasibility_checks",
        "complete_route_search_evaluations",
    }
    missing = sorted(required - set(terminal))
    if missing:
        raise RuntimeError(
            f"terminal activity omitted required ledgers: {missing}"
        )
    route_search = int(
        terminal["complete_route_search_evaluations"]
    )
    if route_search < 0:
        raise RuntimeError("negative terminal route-search ledger")
    common = {
        "full_solution_replays": int(
            terminal["full_solution_replays"]
        ),
        "route_local_exact_evaluations": int(
            terminal["route_local_exact_evaluations"]
        ),
        "route_proxy_evaluations": int(
            terminal["route_proxy_evaluations"]
        ),
        "route_local_schedule_evaluations": int(
            terminal["route_local_schedule_evaluations"]
        ),
        "feasibility_checks": int(
            terminal["full_feasibility_checks"]
        ),
    }
    if any(value < 0 for value in common.values()):
        raise RuntimeError("negative terminal accounting value")
    if kind == "candidate":
        mapping = {
            "full_solution_replays": "terminal_full_solution_replays",
            "route_local_exact_evaluations": (
                "terminal_route_local_exact_evaluations"
            ),
            "route_proxy_evaluations": (
                "terminal_route_proxy_evaluations"
            ),
            "route_local_schedule_evaluations": (
                "terminal_route_local_schedule_evaluations"
            ),
            "feasibility_checks": "terminal_feasibility_checks",
        }
        records = activity["terminal_activity_records"]
    elif kind == "counterfactual":
        mapping = {
            "full_solution_replays": (
                "counterfactual_full_solution_replays"
            ),
            "route_local_exact_evaluations": (
                "counterfactual_route_local_exact_evaluations"
            ),
            "route_proxy_evaluations": (
                "counterfactual_route_proxy_evaluations"
            ),
            "route_local_schedule_evaluations": (
                "counterfactual_route_local_schedule_evaluations"
            ),
            "feasibility_checks": (
                "counterfactual_feasibility_checks"
            ),
        }
        records = activity["counterfactual_activity_records"]
    else:
        raise ValueError(f"unknown terminal activity kind: {kind}")
    for source_name, target_name in mapping.items():
        activity[target_name] += common[source_name]
    activity["complete_route_search_evaluations"] += route_search
    records.append(
        {
            "kind": kind,
            "round": int(round_index),
            **common,
            "complete_route_search_evaluations": route_search,
        }
    )


def _best_existing_route_proxy(
    route: Route,
    solution: Solution,
    context: EvaluationContext,
    activity: dict[str, Any],
) -> float:
    actions = tuple(
        action
        for action in solution.charging_actions
        if action.vehicle_id == route.vehicle_id
    )
    variants = _route_variants(
        route,
        current_actions=actions,
        instance=context.instance,
        carbon_profile=context.carbon_profile,
        prices=context.prices,
    )
    activity["route_proxy_evaluations"] += len(variants)
    return float(
        min(variant.proxy_cost for variant in variants.values())
    )


def _best_neutral_route_proxy(
    route: Route,
    context: EvaluationContext,
    cache: dict[tuple[str, tuple[str, ...]], tuple[float, str]],
    activity: dict[str, Any],
) -> float:
    key = (
        str(route.home_depot_id),
        tuple(_customer_ids(route, context.instance)),
    )
    cached = cache.get(key)
    if cached is not None:
        activity["route_proxy_cache_hits"] += 1
        return float(cached[0])
    variants = _route_variants(
        route,
        current_actions=(),
        instance=context.instance,
        carbon_profile=context.carbon_profile,
        prices=context.prices,
    )
    activity["route_proxy_evaluations"] += len(variants)
    best = min(
        variants.values(),
        key=lambda variant: (
            float(variant.proxy_cost),
            variant.vehicle_type,
        ),
    )
    cache[key] = (float(best.proxy_cost), str(best.vehicle_type))
    return float(best.proxy_cost)


def _best_insertion_positions(
    home_depot_id: str,
    customers: list[str],
    segment: tuple[str, ...],
    context: EvaluationContext,
    *,
    count: int,
    activity: dict[str, Any],
) -> list[int]:
    base = _route_distance(home_depot_id, customers, context)
    ranked: list[tuple[float, int]] = []
    for position in range(len(customers) + 1):
        expanded = list(customers)
        expanded[position:position] = segment
        ranked.append(
            (
                _route_distance(home_depot_id, expanded, context) - base,
                position,
            )
        )
        activity["distance_insertion_evaluations"] += 1
    return [
        position
        for _, position in sorted(ranked)[: max(1, int(count))]
    ]


def _route_distance(
    home_depot_id: str,
    customers: list[str],
    context: EvaluationContext,
) -> float:
    sequence = [home_depot_id, *customers, home_depot_id]
    return sum(
        float(context.instance.distance(left, right))
        for left, right in zip(sequence, sequence[1:])
    )


def _customer_ids(route: Route, instance: Any) -> list[str]:
    nodes = {str(node.node_id): node for node in instance.nodes}
    return [
        str(node_id)
        for node_id in route.node_sequence
        if str(node_id) in nodes
        and str(nodes[str(node_id)].node_type).lower() == "c"
    ]


def _cv_route_count(solution: Solution) -> int:
    return sum(
        route.vehicle_type.lower() == "cv" for route in solution.routes
    )


def _route_vehicle_type(solution: Solution, index: int) -> str:
    if index < 0 or index >= len(solution.routes):
        return "__missing__"
    return solution.routes[index].vehicle_type.lower()


def _route_skeleton_hash(solution: Solution, instance: Any) -> str:
    payload = sorted(
        (
            str(route.home_depot_id),
            tuple(_customer_ids(route, instance)),
        )
        for route in solution.routes
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _model_cost(
    solution: Solution,
    context: EvaluationContext,
) -> float:
    return float(
        evaluate(
            solution,
            context.instance,
            context.carbon_profile,
            context.prices,
            carbon_quota_kg=context.carbon_quota_kg,
        )["total_cost"]
    )


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _full_content_hash(solution: Solution) -> str:
    payload = json.dumps(
        asdict(solution),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _semantic_hash(solution: Solution) -> str:
    """Hash full values while ignoring top-level list order only."""

    payload = asdict(solution)
    for key in (
        "routes",
        "charging_actions",
        "cross_site_services",
    ):
        payload[key] = sorted(
            payload[key],
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_config(config: ElectrificationRelocateResizeConfig) -> None:
    values = asdict(config)
    frozen = asdict(ElectrificationRelocateResizeConfig())
    if values != frozen:
        raise ValueError(
            "formal relocate-resize entry requires the exact frozen "
            f"configuration: expected={frozen}, received={values}"
        )


def _require_finite(label: str, *values: float) -> None:
    if not all(math.isfinite(float(value)) for value in values):
        raise RuntimeError(f"{label} contains non-finite values: {values}")
