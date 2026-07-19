"""Fuel-route retirement with EV-aware regret repacking.

This isolated mechanism operator does not run ALNS, HGS, or any other route
search.  It removes every customer from one CV route, deterministically
rebuilds the existing route slots with regret-2 insertion, and optionally
seeds one bounded ejection from another route.  Once the customer skeleton is
complete, the existing fixed-route fleet/charging and carbon decoders may only
choose vehicle types, charging, and charging times.

The implementation follows the pre-registered contract in
``docs/handoff/fuel_route_retirement_ev_repack_contract_20260719.md``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable

from fast_mechanism_completion import apply_fast_route_local_completion
from setp_solver.check import check_solution
from setp_solver.cost import evaluate, route_node_schedule
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Route, Solution
from v4_mechanism_alns_solver import _route_variants
from v7_responsibility_solver import annotate_cross_site_services


TOL = 1.0e-9


@dataclass(frozen=True)
class FuelRouteRetirementConfig:
    max_source_routes: int = 2
    max_ejection_seeds_per_source: int = 8
    repair_candidate_capacity: int = 10
    exact_candidate_capacity: int = 4
    max_rounds: int = 2


@dataclass(frozen=True)
class RoutePlan:
    original_index: int
    home_depot_id: str
    customers: tuple[str, ...]


@dataclass(frozen=True)
class RoutePlanScore:
    proxy_cost: float
    variant_count: int
    cv_proxy_cost: float
    ev_proxy_cost: float | None

    @property
    def ev_feasible(self) -> bool:
        return self.ev_proxy_cost is not None


@dataclass(frozen=True)
class RepairOption:
    customer_id: str
    plan_position: int
    insertion_position: int
    delta: float
    resulting_score: float
    resulting_customers: tuple[str, ...]

    @property
    def sort_key(self) -> tuple[Any, ...]:
        return (
            float(self.delta),
            int(self.plan_position),
            int(self.insertion_position),
            self.resulting_customers,
        )


@dataclass(frozen=True)
class RepackCandidate:
    source_original_index: int
    seed_kind: str
    ejected_original_index: int | None
    ejected_customer_id: str | None
    plans: tuple[RoutePlan, ...]
    neutral_solution: Solution
    plan_to_output: tuple[tuple[int, int], ...]
    prescore: float
    route_skeleton_sha256: str
    repair_trace: dict[str, Any]

    @property
    def sort_key(self) -> tuple[Any, ...]:
        return (
            float(self.prescore),
            int(self.source_original_index),
            0 if self.seed_kind == "direct" else 1,
            -1
            if self.ejected_original_index is None
            else int(self.ejected_original_index),
            self.ejected_customer_id or "",
            self.route_skeleton_sha256,
        )


@dataclass(frozen=True)
class FuelRouteRetirementResult:
    solution: Solution
    cost: float
    source_cost: float
    feasible: bool
    changed: bool
    activity: dict[str, Any]


class RoutePlanScorer:
    """Cache route-local feasibility and best CV/EV/charge proxy costs."""

    def __init__(
        self,
        context: EvaluationContext,
        owners: dict[str, str],
        activity: dict[str, Any],
    ) -> None:
        self.context = context
        self.owners = owners
        self.activity = activity
        self.cache: dict[
            tuple[str, tuple[str, ...]],
            RoutePlanScore | None,
        ] = {}

    def __call__(self, plan: RoutePlan) -> RoutePlanScore | None:
        if not plan.customers:
            return RoutePlanScore(0.0, 0, 0.0, None)
        key = (plan.home_depot_id, plan.customers)
        if key in self.cache:
            self.activity["route_plan_proxy_cache_hits"] += 1
            return self.cache[key]
        self.activity["route_plan_local_feasibility_checks"] += 1
        if not _cv_route_locally_feasible(plan, self.context):
            self.cache[key] = None
            return None
        route = Route(
            vehicle_id=f"CV_REPACK_PLAN_{plan.original_index + 1}",
            vehicle_type="cv",
            home_depot_id=plan.home_depot_id,
            node_sequence=[
                plan.home_depot_id,
                *plan.customers,
                plan.home_depot_id,
            ],
        )
        variants = _route_variants(
            route,
            current_actions=(),
            instance=self.context.instance,
            carbon_profile=self.context.carbon_profile,
            prices=self.context.prices,
        )
        self.activity["route_plan_variant_calls"] += 1
        self.activity["route_plan_charge_repair_calls"] += 1
        self.activity["route_plan_proxy_evaluations"] += len(variants)
        cv_variant = variants.get("cv")
        if cv_variant is None:
            self.cache[key] = None
            return None
        cross_site_cost = sum(
            _price(self.context.prices, "cross_site_cost")
            for customer_id in plan.customers
            if self.owners.get(customer_id) is not None
            and self.owners.get(customer_id) != plan.home_depot_id
        )
        cv_cost = float(cv_variant.proxy_cost) + cross_site_cost
        ev_variant = variants.get("ev")
        ev_cost = (
            None
            if ev_variant is None
            else float(ev_variant.proxy_cost) + cross_site_cost
        )
        best = min(value for value in (cv_cost, ev_cost) if value is not None)
        if not all(math.isfinite(float(value)) for value in (best, cv_cost)) or (
            ev_cost is not None and not math.isfinite(float(ev_cost))
        ):
            raise RuntimeError("route-plan proxy is non-finite")
        scored = RoutePlanScore(
            proxy_cost=float(best),
            variant_count=len(variants),
            cv_proxy_cost=float(cv_cost),
            ev_proxy_cost=(None if ev_cost is None else float(ev_cost)),
        )
        self.cache[key] = scored
        return scored


def apply_fuel_route_retirement_ev_repack(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    prices: Any = DEFAULT_PRICES,
    config: FuelRouteRetirementConfig | None = None,
) -> FuelRouteRetirementResult:
    """Apply at most two bounded fuel-route retirement rounds."""

    return _apply_fuel_route_retirement_ev_repack(
        bundle_dir,
        solution,
        prices=prices,
        config=config,
        ejection_seed_limit=8,
        algorithm_label="fuel_route_retirement_ev_repack",
    )


def apply_fuel_route_retirement_without_ejection(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    prices: Any = DEFAULT_PRICES,
    config: FuelRouteRetirementConfig | None = None,
) -> FuelRouteRetirementResult:
    """Symmetric ablation: keep route retirement and disable ejection seeds."""

    return _apply_fuel_route_retirement_ev_repack(
        bundle_dir,
        solution,
        prices=prices,
        config=config,
        ejection_seed_limit=0,
        algorithm_label="fuel_route_retirement_regret_no_ejection",
    )


def _apply_fuel_route_retirement_ev_repack(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    prices: Any,
    config: FuelRouteRetirementConfig | None,
    ejection_seed_limit: int,
    algorithm_label: str,
) -> FuelRouteRetirementResult:
    cfg = config or FuelRouteRetirementConfig()
    _validate_config(cfg)
    if ejection_seed_limit not in {
        0,
        cfg.max_ejection_seeds_per_source,
    }:
        raise ValueError(
            "ejection seed limit must be the frozen full arm or zero ablation"
        )
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
    source_violations = check_solution(
        solution,
        bundle.instance,
        prices,
    )
    if source_violations:
        raise ValueError(
            f"fuel-route retirement source is infeasible: {source_violations[:8]}"
        )
    source_coverage = _customer_counter(solution, context.instance)
    if any(count != 1 for count in source_coverage.values()):
        raise ValueError("fuel-route retirement source customer coverage is not unique")

    activity = _new_activity(solution)
    best = solution
    objective = float(source_cost)
    scorer = RoutePlanScorer(context, owners, activity)

    for round_index in range(cfg.max_rounds):
        round_number = round_index + 1
        round_source = best
        round_cost = float(objective)
        round_cv = _cv_route_count(round_source)
        if round_cv == 0:
            activity["round_summaries"].append(
                {
                    "round": round_number,
                    "source_cv_routes": 0,
                    "sources_considered": 0,
                    "repair_candidates": 0,
                    "exact_attempted": 0,
                    "eligible_candidates": 0,
                    "accepted": False,
                    "stop_reason": "no_cv_route_exact_noop",
                }
            )
            activity["stop_reason"] = "no_cv_route_exact_noop"
            break

        try:
            candidates = _enumerate_repack_candidates(
                round_source,
                context,
                scorer,
                cfg,
                ejection_seed_limit,
                activity,
            )
        except (ArithmeticError, RuntimeError, ValueError) as exc:
            activity["enumeration_fail_closed"].append(
                {
                    "round": round_number,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            activity["stop_reason"] = "enumeration_failed_closed"
            break

        selected = candidates[: cfg.repair_candidate_capacity]
        exact_selected = selected[: cfg.exact_candidate_capacity]
        summary = {
            "round": round_number,
            "source_cv_routes": round_cv,
            "sources_considered": min(
                round_cv,
                cfg.max_source_routes,
            ),
            "repair_candidates": len(candidates),
            "prescore_selected": len(selected),
            "exact_attempted": len(exact_selected),
            "eligible_candidates": 0,
            "accepted": False,
        }
        if not exact_selected:
            summary["stop_reason"] = "no_repack_candidate"
            activity["round_summaries"].append(summary)
            activity["stop_reason"] = "no_repack_candidate"
            break

        try:
            completion_records_before = len(activity["completion_activity_records"])
            activity["counterfactual_completion_calls"] += 1
            counterfactual = apply_fast_route_local_completion(
                round_source,
                bundle,
                prices=prices,
            )
            _accumulate_completion_activity(
                activity,
                counterfactual.activity,
                kind="counterfactual",
            )
            if not _same_route_skeleton(
                round_source,
                counterfactual.solution,
                context.instance,
            ):
                raise RuntimeError(
                    "counterfactual fixed-route completion changed customers"
                )
            counterfactual_cost = _model_cost(
                counterfactual.solution,
                context,
            )
            activity["counterfactual_full_replays"] += 1
            counterfactual_violations = check_solution(
                counterfactual.solution,
                bundle.instance,
                prices,
            )
            activity["counterfactual_feasibility_checks"] += 1
            if counterfactual_violations:
                raise RuntimeError(
                    "counterfactual completion is infeasible: "
                    f"{counterfactual_violations[:8]}"
                )
        except (ArithmeticError, RuntimeError, ValueError) as exc:
            if (
                len(activity["completion_activity_records"])
                == completion_records_before
            ):
                activity["completion_activity_records"].append(
                    {
                        "kind": "counterfactual_failure",
                        "activity": None,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
            activity["round_fail_closed"].append(
                {
                    "round": round_number,
                    "stage": "counterfactual",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            summary["stop_reason"] = "counterfactual_failed_closed"
            activity["round_summaries"].append(summary)
            activity["stop_reason"] = "counterfactual_failed_closed"
            break

        counterfactual_cv = _cv_route_count(counterfactual.solution)
        exact_rows: list[
            tuple[
                float,
                tuple[Any, ...],
                RepackCandidate,
                Solution,
                dict[str, Any],
            ]
        ] = []
        for candidate in exact_selected:
            candidate_full_replay_attempts = 0
            candidate_feasibility_check_attempts = 0
            base_row = {
                "round": round_number,
                "source_cost": float(round_cost),
                "source_cv_routes": round_cv,
                "source_route_skeleton_sha256": _route_skeleton_hash(
                    round_source,
                    context.instance,
                ),
                "source_full_content_sha256": _full_content_hash(round_source),
                "source_semantic_sha256": _semantic_solution_hash(round_source),
                "source_solution_snapshot": asdict(round_source),
                "counterfactual_cost": float(counterfactual_cost),
                "counterfactual_cv_routes": counterfactual_cv,
                "counterfactual_route_skeleton_sha256": (
                    _route_skeleton_hash(
                        counterfactual.solution,
                        context.instance,
                    )
                ),
                "counterfactual_full_content_sha256": (
                    _full_content_hash(counterfactual.solution)
                ),
                "counterfactual_semantic_sha256": (
                    _semantic_solution_hash(counterfactual.solution)
                ),
                "counterfactual_solution_snapshot": asdict(counterfactual.solution),
                "source_original_index": (candidate.source_original_index),
                "seed_kind": candidate.seed_kind,
                "ejected_original_index": (candidate.ejected_original_index),
                "ejected_customer_id": (candidate.ejected_customer_id),
                "prescore": float(candidate.prescore),
                "neutral_route_skeleton_sha256": (candidate.route_skeleton_sha256),
                "neutral_full_content_sha256": _full_content_hash(
                    candidate.neutral_solution
                ),
                "neutral_semantic_sha256": _semantic_solution_hash(
                    candidate.neutral_solution
                ),
                "neutral_solution_snapshot": asdict(candidate.neutral_solution),
                "plan_to_output": [list(item) for item in candidate.plan_to_output],
                "plans": [asdict(plan) for plan in candidate.plans],
                "repair_trace": candidate.repair_trace,
            }
            try:
                completion_records_before = len(activity["completion_activity_records"])
                activity["candidate_completion_calls"] += 1
                completion = apply_fast_route_local_completion(
                    candidate.neutral_solution,
                    bundle,
                    prices=prices,
                )
                _accumulate_completion_activity(
                    activity,
                    completion.activity,
                    kind="candidate",
                )
                skeleton_preserved = _same_route_skeleton(
                    candidate.neutral_solution,
                    completion.solution,
                    context.instance,
                )
                activity["candidate_full_replays"] += 1
                candidate_full_replay_attempts += 1
                candidate_cost = _model_cost(
                    completion.solution,
                    context,
                )
                activity["candidate_full_replays"] += 1
                activity["candidate_independent_replays"] += 1
                candidate_full_replay_attempts += 1
                candidate_replay_cost = _independent_model_cost(
                    completion.solution,
                    context,
                )
                candidate_replay_error = abs(
                    float(candidate_cost) - float(candidate_replay_cost)
                )
                candidate_feasibility_check_attempts += 1
                activity["candidate_feasibility_checks"] += 1
                violations = check_solution(
                    completion.solution,
                    bundle.instance,
                    prices,
                )
                coverage_closed = (
                    _customer_counter(
                        completion.solution,
                        context.instance,
                    )
                    == source_coverage
                )
                cv_after = _cv_route_count(completion.solution)
                route_count_closed = len(completion.solution.routes) <= len(
                    round_source.routes
                )
                structure_changed = not _same_route_skeleton(
                    round_source,
                    completion.solution,
                    context.instance,
                )
                source_retired = _source_route_retired(
                    candidate,
                    completion.solution,
                )
                ejection_holds = _ejection_holds(
                    candidate,
                    completion.solution,
                    context.instance,
                )
                finite = all(
                    math.isfinite(float(value))
                    for value in (
                        candidate_cost,
                        candidate_replay_cost,
                        candidate_replay_error,
                    )
                )
                eligible = bool(
                    finite
                    and candidate_replay_error <= 1.0e-7
                    and skeleton_preserved
                    and not violations
                    and coverage_closed
                    and route_count_closed
                    and structure_changed
                    and source_retired
                    and ejection_holds
                    and candidate_cost < round_cost - TOL
                    and candidate_cost < counterfactual_cost - TOL
                    and cv_after <= round_cv - 1
                    and cv_after <= counterfactual_cv - 1
                )
                row = {
                    **base_row,
                    "candidate_failed_closed": False,
                    "completed_cost": float(candidate_cost),
                    "independent_replay_cost": float(candidate_replay_cost),
                    "independent_replay_error": float(candidate_replay_error),
                    "candidate_full_replay_attempts": (candidate_full_replay_attempts),
                    "candidate_feasibility_check_attempts": (
                        candidate_feasibility_check_attempts
                    ),
                    "cost_delta_vs_source": float(candidate_cost - round_cost),
                    "cost_delta_vs_counterfactual": float(
                        candidate_cost - counterfactual_cost
                    ),
                    "cv_routes_before": round_cv,
                    "cv_routes_counterfactual": counterfactual_cv,
                    "cv_routes_after": cv_after,
                    "route_count_before": len(round_source.routes),
                    "route_count_after": len(completion.solution.routes),
                    "fixed_skeleton_preserved": skeleton_preserved,
                    "route_structure_changed": structure_changed,
                    "source_route_retired": source_retired,
                    "ejection_holds": ejection_holds,
                    "customer_coverage_closed": coverage_closed,
                    "route_count_not_increased": route_count_closed,
                    "feasible": not violations,
                    "eligible": eligible,
                    "completed_route_skeleton_sha256": (
                        _route_skeleton_hash(
                            completion.solution,
                            context.instance,
                        )
                    ),
                    "completed_full_content_sha256": (
                        _full_content_hash(completion.solution)
                    ),
                    "completed_semantic_sha256": (
                        _semantic_solution_hash(completion.solution)
                    ),
                    "completed_solution_snapshot": asdict(completion.solution),
                    "completion_activity": completion.activity,
                }
                activity["exact_candidates"].append(row)
                if eligible:
                    summary["eligible_candidates"] += 1
                    exact_rows.append(
                        (
                            float(candidate_cost),
                            candidate.sort_key,
                            candidate,
                            completion.solution,
                            row,
                        )
                    )
            except (ArithmeticError, RuntimeError, ValueError) as exc:
                if (
                    len(activity["completion_activity_records"])
                    == completion_records_before
                ):
                    activity["completion_activity_records"].append(
                        {
                            "kind": "candidate_failure",
                            "activity": None,
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
                activity["candidate_completion_failures"] += 1
                activity["exact_candidates"].append(
                    {
                        **base_row,
                        "candidate_failed_closed": True,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                        "eligible": False,
                        "candidate_full_replay_attempts": (
                            candidate_full_replay_attempts
                        ),
                        "candidate_feasibility_check_attempts": (
                            candidate_feasibility_check_attempts
                        ),
                    }
                )

        if not exact_rows:
            summary["stop_reason"] = "no_strict_cost_and_cv_retirement"
            activity["round_summaries"].append(summary)
            activity["stop_reason"] = "no_strict_cost_and_cv_retirement"
            break

        _, _, accepted_candidate, accepted_solution, accepted_row = min(
            exact_rows,
            key=lambda item: (item[0], item[1]),
        )
        best = accepted_solution
        objective = float(accepted_row["completed_cost"])
        summary["accepted"] = True
        activity["accepted_moves"].append(
            {
                **accepted_row,
                "source_solution_snapshot": asdict(round_source),
                "source_full_content_sha256": _full_content_hash(round_source),
                "counterfactual_solution_snapshot": asdict(counterfactual.solution),
                "counterfactual_cost": float(counterfactual_cost),
                "accepted_seed_kind": accepted_candidate.seed_kind,
            }
        )
        activity["round_summaries"].append(summary)
    else:
        activity["stop_reason"] = "round_limit_reached"

    try:
        recomputed = _model_cost(best, context)
        activity["final_full_replays"] += 1
        final_violations = check_solution(
            best,
            bundle.instance,
            prices,
        )
        activity["final_feasibility_checks"] += 1
        if final_violations:
            raise RuntimeError(
                "fuel-route retirement final solution infeasible: "
                f"{final_violations[:8]}"
            )
        if abs(recomputed - objective) > 1.0e-7:
            raise RuntimeError(
                f"fuel-route retirement objective mismatch: {objective} != {recomputed}"
            )
        if recomputed > source_cost + TOL:
            raise RuntimeError("fuel-route retirement violated monotone envelope")
        if _customer_counter(best, context.instance) != source_coverage:
            raise RuntimeError("fuel-route retirement final customer coverage drifted")
    except (ArithmeticError, RuntimeError, ValueError) as exc:
        activity["discarded_accepted_moves"] = list(activity["accepted_moves"])
        activity["accepted_moves"] = []
        activity["final_fail_closed"] = {
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
        best = solution
        recomputed = float(source_cost)
        final_violations = []

    activity["final_recomputed_cost"] = float(recomputed)
    activity["objective_closure_error"] = abs(
        float(recomputed)
        - (float(source_cost) if not activity["accepted_moves"] else float(objective))
    )
    activity["final_cv_route_count"] = _cv_route_count(best)
    activity["changed"] = bool(activity["accepted_moves"])
    activity["elapsed_seconds"] = time.perf_counter() - started
    activity["config"] = asdict(cfg)
    activity["algorithm_label"] = algorithm_label
    activity["effective_ejection_seed_limit"] = int(ejection_seed_limit)
    activity["total_completion_calls"] = int(
        activity["counterfactual_completion_calls"]
    ) + int(activity["candidate_completion_calls"])
    activity["total_full_replays"] = sum(
        int(activity[name])
        for name in (
            "source_full_replays",
            "counterfactual_full_replays",
            "candidate_full_replays",
            "final_full_replays",
        )
    )
    activity["total_feasibility_checks"] = sum(
        int(activity[name])
        for name in (
            "source_feasibility_checks",
            "counterfactual_feasibility_checks",
            "candidate_feasibility_checks",
            "final_feasibility_checks",
            "completion_full_feasibility_checks",
        )
    )
    return FuelRouteRetirementResult(
        solution=best,
        cost=float(recomputed),
        source_cost=float(source_cost),
        feasible=not final_violations,
        changed=bool(activity["accepted_moves"]),
        activity=activity,
    )


def _enumerate_repack_candidates(
    solution: Solution,
    context: EvaluationContext,
    scorer: RoutePlanScorer,
    config: FuelRouteRetirementConfig,
    ejection_seed_limit: int,
    activity: dict[str, Any],
) -> list[RepackCandidate]:
    original_plans = tuple(
        RoutePlan(
            original_index=index,
            home_depot_id=route.home_depot_id,
            customers=tuple(_customer_ids(route, context.instance)),
        )
        for index, route in enumerate(solution.routes)
    )
    source_rows: list[tuple[Any, ...]] = []
    for index, route in enumerate(solution.routes):
        if route.vehicle_type.lower() != "cv":
            continue
        plan = original_plans[index]
        if not plan.customers:
            continue
        score = scorer(plan)
        if score is None:
            continue
        gap = (
            math.inf
            if score.ev_proxy_cost is None
            else score.ev_proxy_cost - score.cv_proxy_cost
        )
        source_rows.append(
            (
                0 if score.ev_proxy_cost is None else 1,
                -float(gap),
                index,
            )
        )
    selected_sources = [
        row[2] for row in sorted(source_rows)[: config.max_source_routes]
    ]
    activity["source_routes_considered"] += len(selected_sources)
    unique: dict[str, RepackCandidate] = {}
    source_coverage = Counter(
        customer_id for plan in original_plans for customer_id in plan.customers
    )
    for source_index in selected_sources:
        source_customers = original_plans[source_index].customers
        empty_source_plans = list(original_plans)
        empty_source_plans[source_index] = replace(
            empty_source_plans[source_index],
            customers=(),
        )
        seeds: list[
            tuple[
                str,
                int | None,
                str | None,
                tuple[RoutePlan, ...],
                tuple[str, ...],
                dict[str, int],
            ]
        ] = [
            (
                "direct",
                None,
                None,
                tuple(empty_source_plans),
                source_customers,
                {},
            )
        ]
        if ejection_seed_limit:
            ejection_rows: list[tuple[float, int, str, tuple[RoutePlan, ...]]] = []
            for plan_position, plan in enumerate(empty_source_plans):
                if plan_position == source_index:
                    continue
                base_score = scorer(plan)
                if base_score is None:
                    continue
                for customer_id in plan.customers:
                    activity["ejection_seed_scoring_attempts"] += 1
                    reduced_customers = tuple(
                        item for item in plan.customers if item != customer_id
                    )
                    reduced_plan = replace(
                        plan,
                        customers=reduced_customers,
                    )
                    reduced_score = scorer(reduced_plan)
                    if reduced_score is None:
                        continue
                    release = base_score.proxy_cost - reduced_score.proxy_cost
                    seeded = list(empty_source_plans)
                    seeded[plan_position] = reduced_plan
                    ejection_rows.append(
                        (
                            -float(release),
                            plan_position,
                            customer_id,
                            tuple(seeded),
                        )
                    )
            for _, origin, customer_id, seeded_plans in sorted(
                ejection_rows,
                key=lambda item: (item[0], item[1], item[2]),
            )[:ejection_seed_limit]:
                seeds.append(
                    (
                        "one_level_ejection",
                        origin,
                        customer_id,
                        seeded_plans,
                        (*source_customers, customer_id),
                        {customer_id: origin},
                    )
                )

        for (
            seed_kind,
            ejected_origin,
            ejected_customer,
            seed_plans,
            pending,
            blocked,
        ) in seeds:
            activity["repair_attempts"] += 1
            if seed_kind == "one_level_ejection":
                activity["one_level_ejection_attempts"] += 1
            repaired, trace = _regret2_repair(
                seed_plans,
                pending,
                scorer,
                blocked_original_indices=blocked,
                activity=activity,
            )
            if repaired is None:
                activity["repair_failures"] += 1
                continue
            repaired_coverage = Counter(
                customer_id for plan in repaired for customer_id in plan.customers
            )
            if repaired_coverage != source_coverage:
                activity["coverage_rejections"] += 1
                continue
            if _plans_signature(repaired) == _plans_signature(original_plans):
                activity["unchanged_repair_rejections"] += 1
                continue
            if (
                ejected_origin is not None
                and ejected_customer is not None
                and ejected_customer in repaired[ejected_origin].customers
            ):
                activity["ejection_return_rejections"] += 1
                continue
            neutral, plan_to_output = _solution_from_plans(
                solution,
                repaired,
                context,
            )
            skeleton_hash = _route_skeleton_hash(
                neutral,
                context.instance,
            )
            score_rows = [scorer(plan) for plan in repaired]
            if any(row is None for row in score_rows):
                activity["repair_failures"] += 1
                continue
            prescore = sum(
                float(row.proxy_cost) for row in score_rows if row is not None
            )
            if not math.isfinite(prescore):
                activity["nonfinite_prescore_rejections"] += 1
                continue
            candidate = RepackCandidate(
                source_original_index=source_index,
                seed_kind=seed_kind,
                ejected_original_index=ejected_origin,
                ejected_customer_id=ejected_customer,
                plans=repaired,
                neutral_solution=neutral,
                plan_to_output=plan_to_output,
                prescore=float(prescore),
                route_skeleton_sha256=skeleton_hash,
                repair_trace=trace,
            )
            activity["repack_candidates_built"] += 1
            prior = unique.get(skeleton_hash)
            if prior is not None:
                activity["duplicate_skeleton_candidates"] += 1
            if prior is None or candidate.sort_key < prior.sort_key:
                unique[skeleton_hash] = candidate
    activity["unique_repack_candidates"] += len(unique)
    return sorted(unique.values(), key=lambda item: item.sort_key)


def _regret2_repair(
    seed_plans: tuple[RoutePlan, ...],
    pending_customers: tuple[str, ...],
    scorer: Callable[[RoutePlan], RoutePlanScore | None],
    *,
    blocked_original_indices: dict[str, int],
    activity: dict[str, Any] | None = None,
) -> tuple[tuple[RoutePlan, ...] | None, dict[str, Any]]:
    """Deterministic regret-2 insertion over existing route slots."""

    pending = list(dict.fromkeys(pending_customers))
    if len(pending) != len(pending_customers):
        return None, {
            "failed": True,
            "reason": "duplicate_pending_customer",
        }
    plans = list(seed_plans)
    expected_coverage = Counter(
        customer_id for plan in plans for customer_id in plan.customers
    ) + Counter(pending)
    trace: dict[str, Any] = {
        "pending_initial": list(pending),
        "blocked_original_indices": dict(sorted(blocked_original_indices.items())),
        "insertions": [],
        "failed": False,
    }
    while pending:
        choices: list[
            tuple[
                tuple[Any, ...],
                str,
                RepairOption,
                list[RepairOption],
            ]
        ] = []
        for customer_id in pending:
            options = _insertion_options(
                plans,
                customer_id,
                scorer,
                blocked_original_index=(blocked_original_indices.get(customer_id)),
                activity=activity,
            )
            if not options:
                continue
            best = options[0]
            constrained = len(options) == 1
            regret = 0.0 if constrained else float(options[1].delta - best.delta)
            priority = (
                -int(constrained),
                -float(regret),
                float(best.delta),
                customer_id,
            )
            choices.append((priority, customer_id, best, options))
        if not choices:
            trace["failed"] = True
            trace["reason"] = "no_feasible_insertion"
            trace["pending_at_failure"] = list(pending)
            return None, trace
        _, customer_id, selected, options = min(
            choices,
            key=lambda item: item[0],
        )
        plan = plans[selected.plan_position]
        plans[selected.plan_position] = replace(
            plan,
            customers=selected.resulting_customers,
        )
        pending.remove(customer_id)
        actual_coverage = Counter(
            item for route_plan in plans for item in route_plan.customers
        ) + Counter(pending)
        if activity is not None:
            activity["coverage_invariant_checks"] += 1
        if actual_coverage != expected_coverage:
            trace["failed"] = True
            trace["reason"] = "coverage_invariant_failed"
            return None, trace
        trace["insertions"].append(
            {
                "customer_id": customer_id,
                "plan_original_index": plan.original_index,
                "insertion_position": (selected.insertion_position),
                "delta": float(selected.delta),
                "feasible_option_count": len(options),
                "only_feasible_position": len(options) == 1,
                "regret2": (
                    0.0
                    if len(options) == 1
                    else float(options[1].delta - options[0].delta)
                ),
            }
        )
    trace["pending_final"] = []
    return tuple(plans), trace


def _insertion_options(
    plans: list[RoutePlan],
    customer_id: str,
    scorer: Callable[[RoutePlan], RoutePlanScore | None],
    *,
    blocked_original_index: int | None,
    activity: dict[str, Any] | None,
) -> list[RepairOption]:
    options: list[RepairOption] = []
    for position, plan in enumerate(plans):
        if (
            blocked_original_index is not None
            and plan.original_index == blocked_original_index
        ):
            continue
        base_score = scorer(plan)
        if base_score is None:
            continue
        for insert_at in range(len(plan.customers) + 1):
            if activity is not None:
                activity["insertion_positions_evaluated"] += 1
            customers = list(plan.customers)
            customers.insert(insert_at, customer_id)
            candidate_plan = replace(
                plan,
                customers=tuple(customers),
            )
            candidate_score = scorer(candidate_plan)
            if candidate_score is None:
                continue
            delta = candidate_score.proxy_cost - base_score.proxy_cost
            if not math.isfinite(float(delta)):
                continue
            options.append(
                RepairOption(
                    customer_id=customer_id,
                    plan_position=position,
                    insertion_position=insert_at,
                    delta=float(delta),
                    resulting_score=float(candidate_score.proxy_cost),
                    resulting_customers=candidate_plan.customers,
                )
            )
    return sorted(options, key=lambda item: item.sort_key)


def _solution_from_plans(
    source: Solution,
    plans: tuple[RoutePlan, ...],
    context: EvaluationContext,
) -> tuple[Solution, tuple[tuple[int, int], ...]]:
    routes: list[Route] = []
    preserved_vehicle_ids: set[str] = set()
    mapping: list[tuple[int, int]] = []
    for plan in plans:
        if not plan.customers:
            continue
        original = source.routes[plan.original_index]
        original_customers = tuple(_customer_ids(original, context.instance))
        if (
            plan.customers == original_customers
            and plan.home_depot_id == original.home_depot_id
        ):
            route = original
            preserved_vehicle_ids.add(original.vehicle_id)
        else:
            route = Route(
                vehicle_id=original.vehicle_id,
                vehicle_type="cv",
                home_depot_id=plan.home_depot_id,
                node_sequence=[
                    plan.home_depot_id,
                    *plan.customers,
                    plan.home_depot_id,
                ],
            )
        mapping.append((plan.original_index, len(routes)))
        routes.append(route)
    neutral = Solution(
        routes=routes,
        charging_actions=[
            action
            for action in source.charging_actions
            if action.vehicle_id in preserved_vehicle_ids
        ],
        cross_site_services=list(source.cross_site_services),
    )
    owners = context.customer_home_depot or {}
    neutral = annotate_cross_site_services(neutral, owners)
    return neutral, tuple(mapping)


def _source_route_retired(
    candidate: RepackCandidate,
    completed: Solution,
) -> bool:
    mapping = dict(candidate.plan_to_output)
    output_index = mapping.get(candidate.source_original_index)
    if output_index is None:
        return True
    if output_index >= len(completed.routes):
        return False
    return completed.routes[output_index].vehicle_type.lower() == "ev"


def _ejection_holds(
    candidate: RepackCandidate,
    completed: Solution,
    instance: Any,
) -> bool:
    if candidate.seed_kind == "direct":
        return (
            candidate.ejected_original_index is None
            and candidate.ejected_customer_id is None
        )
    if (
        candidate.ejected_original_index is None
        or candidate.ejected_customer_id is None
    ):
        return False
    mapping = dict(candidate.plan_to_output)
    output_index = mapping.get(candidate.ejected_original_index)
    if output_index is None:
        return True
    if output_index >= len(completed.routes):
        return False
    return candidate.ejected_customer_id not in _customer_ids(
        completed.routes[output_index],
        instance,
    )


def _cv_route_locally_feasible(
    plan: RoutePlan,
    context: EvaluationContext,
) -> bool:
    node_lookup = {node.node_id: node for node in context.instance.nodes}
    if any(customer_id not in node_lookup for customer_id in plan.customers):
        return False
    demand = sum(
        float(node_lookup[customer_id].demand) for customer_id in plan.customers
    )
    if demand > _price(context.prices, "Q_capacity") + TOL:
        return False
    route = Route(
        vehicle_id="CV_REPACK_FEASIBILITY",
        vehicle_type="cv",
        home_depot_id=plan.home_depot_id,
        node_sequence=[
            plan.home_depot_id,
            *plan.customers,
            plan.home_depot_id,
        ],
    )
    try:
        schedule = route_node_schedule(
            route,
            context.instance,
            context.prices,
        )
    except (KeyError, ValueError):
        return False
    return all(
        row.t_start <= float(node_lookup[row.node_id].due_time) + TOL
        for row in schedule
    )


def _source_obstruction_key(
    score: RoutePlanScore,
    index: int,
) -> tuple[Any, ...]:
    gap = (
        math.inf
        if score.ev_proxy_cost is None
        else score.ev_proxy_cost - score.cv_proxy_cost
    )
    return (
        0 if score.ev_proxy_cost is None else 1,
        -float(gap),
        int(index),
    )


def _same_route_skeleton(
    left: Solution,
    right: Solution,
    instance: Any,
) -> bool:
    return _route_skeleton_signature(
        left,
        instance,
    ) == _route_skeleton_signature(right, instance)


def _route_skeleton_signature(
    solution: Solution,
    instance: Any,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            route.home_depot_id,
            tuple(_customer_ids(route, instance)),
        )
        for route in solution.routes
    )


def _plans_signature(
    plans: tuple[RoutePlan, ...],
) -> tuple[tuple[int, str, tuple[str, ...]], ...]:
    return tuple(
        (
            plan.original_index,
            plan.home_depot_id,
            plan.customers,
        )
        for plan in plans
    )


def _route_skeleton_hash(
    solution: Solution,
    instance: Any,
) -> str:
    payload = json.dumps(
        _route_skeleton_signature(solution, instance),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _full_content_hash(solution: Solution) -> str:
    payload = json.dumps(
        asdict(solution),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _semantic_solution_hash(solution: Solution) -> str:
    """Hash meaning while ignoring top-level collection order."""

    raw = asdict(solution)

    def canonical(item: Any) -> str:
        return json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    normalized = {
        "routes": sorted(raw["routes"], key=canonical),
        "charging_actions": sorted(
            raw["charging_actions"],
            key=canonical,
        ),
        "cross_site_services": sorted(
            raw["cross_site_services"],
            key=canonical,
        ),
    }
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _customer_counter(
    solution: Solution,
    instance: Any,
) -> Counter[str]:
    return Counter(
        customer_id
        for route in solution.routes
        for customer_id in _customer_ids(route, instance)
    )


def _customer_ids(route: Route, instance: Any) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None
        and node_lookup[node_id].node_type.lower() == "c"
    ]


def _cv_route_count(solution: Solution) -> int:
    return sum(route.vehicle_type.lower() == "cv" for route in solution.routes)


def _model_cost(
    solution: Solution,
    context: EvaluationContext,
) -> float:
    value = float(
        evaluate(
            solution,
            context.instance,
            context.carbon_profile,
            context.prices,
            carbon_quota_kg=context.carbon_quota_kg,
        )["total_cost"]
    )
    if not math.isfinite(value):
        raise RuntimeError("full model cost is non-finite")
    return value


def _independent_model_cost(
    solution: Solution,
    context: EvaluationContext,
) -> float:
    """Replay one candidate independently through the protected evaluator."""

    value = float(
        evaluate(
            solution,
            context.instance,
            context.carbon_profile,
            context.prices,
            carbon_quota_kg=context.carbon_quota_kg,
        )["total_cost"]
    )
    if not math.isfinite(value):
        raise RuntimeError("independent full model replay is non-finite")
    return value


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _accumulate_completion_activity(
    activity: dict[str, Any],
    completion: dict[str, Any],
    *,
    kind: str,
) -> None:
    if "complete_route_search_evaluations" not in completion:
        raise RuntimeError("fixed-route completion omitted its route-search ledger")
    route_search_raw = completion["complete_route_search_evaluations"]
    if (
        isinstance(route_search_raw, bool)
        or not isinstance(route_search_raw, int)
        or route_search_raw < 0
    ):
        raise RuntimeError(
            "fixed-route completion returned an invalid route-search ledger"
        )
    route_search = int(route_search_raw)
    for key in (
        "route_proxy_evaluations",
        "route_local_schedule_evaluations",
        "full_feasibility_checks",
        "complete_candidate_evaluations",
        "search_candidate_score_calls",
    ):
        raw = completion.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise RuntimeError(
                f"fixed-route completion returned an invalid {key} ledger"
            )
    if not (
        int(completion["complete_candidate_evaluations"])
        == route_search
        == int(completion["search_candidate_score_calls"])
    ):
        raise RuntimeError("fixed-route completion search ledgers disagree")
    activity["completion_activity_records"].append(
        {"kind": kind, "activity": completion}
    )
    activity["completion_route_proxy_evaluations"] += int(
        completion["route_proxy_evaluations"]
    )
    activity["completion_route_local_schedule_evaluations"] += int(
        completion["route_local_schedule_evaluations"]
    )
    activity["completion_full_feasibility_checks"] += int(
        completion["full_feasibility_checks"]
    )
    activity["complete_route_search_evaluations"] += route_search
    if route_search:
        raise RuntimeError("fixed-route completion reported route-search evaluations")


def _new_activity(solution: Solution) -> dict[str, Any]:
    return {
        "source_cv_route_count": _cv_route_count(solution),
        "source_full_replays": 1,
        "source_feasibility_checks": 1,
        "source_routes_considered": 0,
        "repair_attempts": 0,
        "one_level_ejection_attempts": 0,
        "ejection_seed_scoring_attempts": 0,
        "repair_failures": 0,
        "coverage_rejections": 0,
        "unchanged_repair_rejections": 0,
        "ejection_return_rejections": 0,
        "nonfinite_prescore_rejections": 0,
        "repack_candidates_built": 0,
        "duplicate_skeleton_candidates": 0,
        "insertion_positions_evaluated": 0,
        "coverage_invariant_checks": 0,
        "new_route_attempts": 0,
        "recursive_ejection_attempts": 0,
        "route_plan_local_feasibility_checks": 0,
        "route_plan_variant_calls": 0,
        "route_plan_charge_repair_calls": 0,
        "route_plan_proxy_evaluations": 0,
        "route_plan_proxy_cache_hits": 0,
        "unique_repack_candidates": 0,
        "counterfactual_completion_calls": 0,
        "candidate_completion_calls": 0,
        "candidate_completion_failures": 0,
        "completion_route_proxy_evaluations": 0,
        "completion_route_local_schedule_evaluations": 0,
        "completion_full_feasibility_checks": 0,
        "counterfactual_full_replays": 0,
        "candidate_full_replays": 0,
        "candidate_independent_replays": 0,
        "final_full_replays": 0,
        "counterfactual_feasibility_checks": 0,
        "candidate_feasibility_checks": 0,
        "final_feasibility_checks": 0,
        "completion_activity_records": [],
        "exact_candidates": [],
        "accepted_moves": [],
        "round_summaries": [],
        "enumeration_fail_closed": [],
        "round_fail_closed": [],
        "complete_route_search_evaluations": 0,
    }


def _validate_config(config: FuelRouteRetirementConfig) -> None:
    expected = FuelRouteRetirementConfig()
    if config != expected:
        raise ValueError(
            "fuel-route retirement uses frozen configuration "
            f"{asdict(expected)}, got {asdict(config)}"
        )
