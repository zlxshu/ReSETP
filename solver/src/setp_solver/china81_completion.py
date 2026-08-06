"""Shared China81 route-skeleton completion and exact scoring.

Every algorithm arm may propose customer groups and visit order, but no arm is
allowed to use a cheaper physical model.  This module converts the common
route skeleton into an all-CV reference, first assigns any EV routes required
by the registered depot fleet caps, and then greedily tests additional EV and
nonlinear charging variants under the same project evaluator and checker.

After the mandatory finite-fleet assignment, the decoder is deliberately
monotone: an optional variant is accepted only when the complete solution
remains feasible and its exact model cost strictly falls.
"""

from __future__ import annotations

from datetime import date, timedelta
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from setp_solver.charge_timing import (
    DEFAULT_CHARGE_TIMING_POLICY,
    validate_charge_timing_policy,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    DEFAULT_PUBLIC_STATION_CANDIDATE_MODE,
    normalize_charge_amount_strategies,
    repair_route_charging_candidates,
    validate_public_station_candidate_mode,
)
from setp_solver.check import FLEET_SIZE, Violation, check_solution
from setp_solver.china81 import China81Bundle, _load_time_profile
from setp_solver.cost import evaluate
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    MultiTripCertificate,
    prepare_multitrip_solution,
    validate_depot_charge_window_mode,
)
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    physical_vehicle_id,
)


TOL = 1.0e-9
DEFAULT_CHARGE_AMOUNT_STRATEGIES = ("just_enough",)


def _china81_depot_profiles_by_day_offset(
    bundle: China81Bundle,
    mode: str,
) -> dict[int, list[dict[str, Any]]]:
    """Load only registered calendar dates needed by one depot-window mode."""

    validate_depot_charge_window_mode(mode)
    if mode == "prev_night":
        offsets = (-1, 0)
    elif mode == "same_day_predeparture":
        offsets = (0,)
    else:
        offsets = (-1, 0, 1)
    calendar_value = bundle.source_paths.get("tariff_carbon_calendar")
    if not calendar_value:
        raise ValueError("China81 bundle has no tariff/carbon calendar source")
    repo_root = Path(__file__).resolve().parents[3]
    calendar_path = Path(calendar_value)
    if not calendar_path.is_absolute():
        calendar_path = repo_root / calendar_path
    cities = {
        str(node.city).strip().lower()
        for node in bundle.instance.nodes
        if node.city is not None
    }
    base_date = date.fromisoformat(bundle.date)
    profiles: dict[int, list[dict[str, Any]]] = {}
    for offset in offsets:
        if offset == 0:
            profiles[offset] = bundle.time_profile
            continue
        profile_date = base_date + timedelta(days=offset)
        profiles[offset] = _load_time_profile(
            calendar_path,
            cities=cities,
            date=profile_date.isoformat(),
            require_explicit_mapping=True,
        )
    return profiles


@dataclass(frozen=True)
class RouteCompletionVariant:
    """One feasible fixed-customer route type/charging proposal."""

    route_index: int
    label: str
    route: Route
    actions: tuple[ChargingAction, ...]
    route_cost: float
    saving_from_cv: float
    charge_amount_strategy: str = "just_enough"


@dataclass(frozen=True)
class China81CompletionResult:
    """Completed solution plus a transparent mechanism ledger."""

    solution: Solution
    objective: float
    breakdown: dict[str, float]
    activity: dict[str, Any]


def annotate_cross_site_services(
    solution: Solution,
    customer_home_depot: dict[str, str] | Any,
) -> Solution:
    """Rebuild cross-site records from route ownership."""

    services = [
        CrossSiteService(
            customer_id=node_id,
            served_by_depot_id=route.home_depot_id,
        )
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if customer_home_depot.get(node_id) is not None
        and customer_home_depot[node_id] != route.home_depot_id
    ]
    return Solution(
        routes=list(solution.routes),
        charging_actions=list(solution.charging_actions),
        cross_site_services=services,
    )


def exact_china81_score(
    solution: Solution,
    bundle: China81Bundle,
    *,
    depot_charge_window_mode: str = DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
) -> tuple[float, dict[str, float], list[Violation]]:
    """Return the exact full-model objective and violations.

    Route ids supplied by an algorithm are trip labels, not authoritative
    physical-vehicle assignments.  Rebuild that assignment with the shared
    strict multi-trip scheduler before checking or charging fixed vehicle
    costs.  A pure all-CV solution is the registered 0% electrification
    reference and therefore uses each depot's fixed total cap ``T_d``; mixed
    solutions use the bundle's active per-type caps.
    """

    annotated, _ = _physicalize_multitrip_solution(
        annotate_cross_site_services(
            solution,
            bundle.customer_home_depot,
        ),
        bundle,
        depot_charge_window_mode=depot_charge_window_mode,
    )
    all_cv_reference = bool(annotated.routes) and all(
        route.vehicle_type.lower() == "cv"
        for route in annotated.routes
    )
    check_instance = bundle.instance
    if all_cv_reference:
        check_instance = replace(
            bundle.instance,
            num_cv=sum(
                int(caps["total_fleet_cap"])
                for caps in bundle.fleet_caps_by_depot.values()
            ),
            num_ev=0,
        )
    violations = check_solution(
        annotated,
        check_instance,
        bundle.prices,
    )
    violations.extend(
        _depot_fleet_violations(
            annotated,
            bundle,
            all_cv_reference=all_cv_reference,
        )
    )
    breakdown = evaluate(
        annotated,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    return float(breakdown["total_cost"]), breakdown, violations


def _physicalize_multitrip_solution(
    solution: Solution,
    bundle: China81Bundle,
    *,
    depot_charge_window_mode: str = DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
) -> tuple[Solution, MultiTripCertificate]:
    """Replace route labels with a certified physical-vehicle trip packing."""

    # ``prepare_multitrip_solution`` intentionally preserves a certificate
    # when its input already has ``PHYSICAL#Tn`` ids.  Completion candidates,
    # however, can contain legacy route-local ids that merely look physical;
    # strip that presentation before scheduling so each call recomputes the
    # real vehicle timeline and its depot charging windows.
    temporary_ids = {
        route.vehicle_id: f"T10_ROUTE_{index:04d}"
        for index, route in enumerate(solution.routes, start=1)
    }
    legacy_routes = [
        replace(route, vehicle_id=temporary_ids[route.vehicle_id])
        for route in solution.routes
    ]
    legacy_actions = [
        replace(
            action,
            vehicle_id=temporary_ids.get(action.vehicle_id, action.vehicle_id),
        )
        for action in solution.charging_actions
    ]
    legacy_solution = Solution(
        routes=legacy_routes,
        charging_actions=legacy_actions,
        cross_site_services=list(solution.cross_site_services),
    )
    physicalized, certificate = prepare_multitrip_solution(
        legacy_solution,
        bundle.instance,
        bundle.prices,
        depot_charge_window_mode=depot_charge_window_mode,
    )
    return annotate_cross_site_services(
        physicalized,
        bundle.customer_home_depot,
    ), certificate


def _depot_physical_counts(
    solution: Solution,
) -> dict[tuple[str, str], int]:
    used: dict[tuple[str, str], set[str]] = {}
    for route in solution.routes:
        key = (
            route.home_depot_id,
            route.vehicle_type.lower(),
        )
        used.setdefault(key, set()).add(
            physical_vehicle_id(route.vehicle_id)
        )
    return {
        key: len(vehicle_ids)
        for key, vehicle_ids in used.items()
    }


def _depot_fleet_violations(
    solution: Solution,
    bundle: China81Bundle,
    *,
    all_cv_reference: bool,
) -> list[Violation]:
    counts = _depot_physical_counts(solution)
    violations: list[Violation] = []
    for depot_id, caps in bundle.fleet_caps_by_depot.items():
        cv_count = counts.get((depot_id, "cv"), 0)
        ev_count = counts.get((depot_id, "ev"), 0)
        cv_cap = (
            int(caps["total_fleet_cap"])
            if all_cv_reference
            else int(caps["num_cv"])
        )
        ev_cap = 0 if all_cv_reference else int(caps["num_ev"])
        total_cap = int(caps["total_fleet_cap"])
        for vehicle_type, count, cap in (
            ("cv", cv_count, cv_cap),
            ("ev", ev_count, ev_cap),
        ):
            if count > cap:
                violations.append(
                    Violation(
                        FLEET_SIZE,
                        "",
                        f"{depot_id}:{vehicle_type}",
                        "physical vehicles "
                        f"{count} exceed registered depot cap {cap}",
                    )
                )
        if cv_count + ev_count > total_cap:
            violations.append(
                Violation(
                    FLEET_SIZE,
                    "",
                    f"{depot_id}:total",
                    "physical vehicles "
                    f"{cv_count + ev_count} exceed registered total "
                    f"cap {total_cap}",
                )
            )
    return violations


def _depot_fleet_overage(
    solution: Solution,
    bundle: China81Bundle,
    depot_id: str,
) -> tuple[int, int, int]:
    physicalized, _ = _physicalize_multitrip_solution(solution, bundle)
    counts = _depot_physical_counts(physicalized)
    caps = bundle.fleet_caps_by_depot[depot_id]
    cv_count = counts.get((depot_id, "cv"), 0)
    ev_count = counts.get((depot_id, "ev"), 0)
    return (
        max(0, cv_count - int(caps["num_cv"])),
        max(0, ev_count - int(caps["num_ev"])),
        max(
            0,
            cv_count
            + ev_count
            - int(caps["total_fleet_cap"]),
        ),
    )


def complete_china81_route_skeleton(
    skeleton: Solution,
    bundle: China81Bundle,
    *,
    charge_amount_strategies: tuple[str, ...] = DEFAULT_CHARGE_AMOUNT_STRATEGIES,
    depot_charge_window_mode: str = DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    public_station_candidate_mode: str = DEFAULT_PUBLIC_STATION_CANDIDATE_MODE,
) -> China81CompletionResult:
    """Complete one route skeleton with a common monotone physics decoder.

    The input contributes only customer grouping, visit order, and home depot.
    The common decoder first builds a feasible all-CV solution, then tests
    integrated, low-carbon, and immediate-timing EV variants.  Every accepted
    change is replayed through the complete checker and evaluator.
    """

    charge_amount_strategies = normalize_charge_amount_strategies(
        charge_amount_strategies
    )
    validate_depot_charge_window_mode(depot_charge_window_mode)
    validate_charge_timing_policy(charge_timing_policy)
    validate_public_station_candidate_mode(public_station_candidate_mode)
    carbon_profiles_by_day_offset = _china81_depot_profiles_by_day_offset(
        bundle,
        depot_charge_window_mode,
    )
    baseline = _canonical_all_cv_solution(skeleton, bundle)
    baseline_obj, baseline_breakdown, baseline_violations = exact_china81_score(
        baseline,
        bundle,
        depot_charge_window_mode=depot_charge_window_mode,
    )
    baseline_nonfleet_violations = [
        violation
        for violation in baseline_violations
        if violation.type != FLEET_SIZE
    ]
    if baseline_nonfleet_violations:
        raise ValueError(
            "China81 route skeleton has no feasible all-CV completion: "
            + _violation_summary(baseline_nonfleet_violations)
        )

    all_variants: list[RouteCompletionVariant] = []
    generation_failures: list[dict[str, Any]] = []
    # ``legacy`` chooses a minimum-carbon slot directly and therefore is not
    # an operating-cost-only completion.  Keep it available for a carbon-priced
    # arm, but do not let it silently change the O/P control objective when the
    # bundle carries zero carbon price.  The integrated zero-weight variant is
    # the objective-consistent immediate/electricity completion in that case.
    variant_specs = [
        (
            "ev_integrated",
            "integrated",
            1.0,
            charge_timing_policy,
        ),
        (
            "ev_immediate",
            "integrated",
            0.0,
            (
                "asap"
                if charge_timing_policy == DEFAULT_CHARGE_TIMING_POLICY
                else charge_timing_policy
            ),
        ),
    ]
    if float(bundle.prices.carbon_price) > TOL:
        variant_specs.insert(
            1,
            (
                "ev_low_carbon",
                "legacy",
                1.0,
                charge_timing_policy,
            ),
        )
    for route_index, route in enumerate(baseline.routes):
        cv_cost = _single_route_cost(route, (), bundle)
        for label, strategy, carbon_weight, timing_policy in variant_specs:
            for charge_amount_strategy in charge_amount_strategies:
                ev_route = Route(
                    vehicle_id=route.vehicle_id,
                    vehicle_type="ev",
                    home_depot_id=route.home_depot_id,
                    node_sequence=list(route.node_sequence),
                )
                try:
                    candidate_repairs = repair_route_charging_candidates(
                        ev_route,
                        bundle.instance,
                        bundle.time_profile,
                        bundle.prices,
                        strategy=strategy,
                        carbon_weight=carbon_weight,
                        depot_charge_window_mode=depot_charge_window_mode,
                        charge_timing_policy=timing_policy,
                        carbon_profiles_by_day_offset=(
                            carbon_profiles_by_day_offset
                        ),
                        charge_amount_strategy=(
                            charge_amount_strategy
                        ),
                        public_station_candidate_mode=(
                            public_station_candidate_mode
                        ),
                    )
                except (TypeError, ValueError) as exc:
                    generation_failures.append(
                        {
                            "route_index": route_index,
                            "label": label,
                            "charge_amount_strategy": (
                                charge_amount_strategy
                            ),
                            "reason": str(exc),
                        }
                    )
                    continue
                for path_label, repaired, actions in candidate_repairs:
                    route_cost = _single_route_cost(
                        repaired,
                        tuple(actions),
                        bundle,
                    )
                    variant_label = (
                        label
                        if charge_amount_strategy == "just_enough"
                        else f"{label}__{charge_amount_strategy}"
                    )
                    if public_station_candidate_mode == "parallel":
                        variant_label = f"{variant_label}__{path_label}"
                    all_variants.append(
                        RouteCompletionVariant(
                            route_index=route_index,
                            label=variant_label,
                            route=repaired,
                            actions=tuple(actions),
                            route_cost=route_cost,
                            saving_from_cv=float(cv_cost - route_cost),
                            charge_amount_strategy=(
                                charge_amount_strategy
                            ),
                        )
                    )

    ranked = sorted(
        all_variants,
        key=lambda item: (
            -item.saving_from_cv,
            item.route_index,
            item.route_cost,
            item.label,
        ),
    )
    current = baseline
    current_obj = baseline_obj
    accepted_route_indices: set[int] = set()
    attempted = 0
    rejected_infeasible = 0
    rejected_non_improving = 0
    mandatory_fleet_assignments: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    routes_by_depot: dict[str, list[int]] = {}
    for route_index, route in enumerate(current.routes):
        routes_by_depot.setdefault(
            route.home_depot_id,
            [],
        ).append(route_index)
    for depot_id in sorted(routes_by_depot):
        if depot_id not in bundle.fleet_caps_by_depot:
            raise ValueError(
                f"China81 completion has no finite fleet for "
                f"{depot_id!r}"
            )
        current_overage = _depot_fleet_overage(
            current,
            bundle,
            depot_id,
        )
        while any(current_overage):
            assigned = False
            for variant in ranked:
                route = current.routes[variant.route_index]
                if (
                    route.home_depot_id != depot_id
                    or variant.route_index in accepted_route_indices
                ):
                    continue
                attempted += 1
                candidate = _replace_route_variant(
                    current,
                    route_index=variant.route_index,
                    route=variant.route,
                    actions=variant.actions,
                    customer_home_depot=bundle.customer_home_depot,
                )
                candidate_obj, _, candidate_violations = (
                    exact_china81_score(
                        candidate,
                        bundle,
                        depot_charge_window_mode=depot_charge_window_mode,
                    )
                )
                candidate_nonfleet_violations = [
                    violation
                    for violation in candidate_violations
                    if violation.type != FLEET_SIZE
                ]
                if candidate_nonfleet_violations:
                    rejected_infeasible += 1
                    continue
                candidate_overage = _depot_fleet_overage(
                    candidate,
                    bundle,
                    depot_id,
                )
                if sum(candidate_overage) >= sum(current_overage):
                    rejected_infeasible += 1
                    continue
                mandatory_fleet_assignments.append(
                    {
                        "depot_id": depot_id,
                        "route_index": variant.route_index,
                        "label": variant.label,
                        "charge_amount_strategy": (
                            variant.charge_amount_strategy
                        ),
                        "before_cost": float(current_obj),
                        "after_cost": float(candidate_obj),
                        "cost_change": float(
                            candidate_obj - current_obj
                        ),
                        "charging_action_count": len(
                            variant.actions
                        ),
                        "physical_fleet_overage_before": list(
                            current_overage
                        ),
                        "physical_fleet_overage_after": list(
                            candidate_overage
                        ),
                    }
                )
                current = candidate
                current_obj = candidate_obj
                current_overage = candidate_overage
                accepted_route_indices.add(variant.route_index)
                assigned = True
                break
            if not assigned:
                raise ValueError(
                    "China81 route skeleton cannot satisfy the registered "
                    f"physical fleet caps at {depot_id!r}: "
                    f"overage={current_overage}"
                )

    finite_fleet_reference_obj = current_obj
    for variant in ranked:
        if variant.route_index in accepted_route_indices:
            continue
        attempted += 1
        candidate = _replace_route_variant(
            current,
            route_index=variant.route_index,
            route=variant.route,
            actions=variant.actions,
            customer_home_depot=bundle.customer_home_depot,
        )
        candidate_obj, _, candidate_violations = exact_china81_score(
            candidate,
            bundle,
            depot_charge_window_mode=depot_charge_window_mode,
        )
        if candidate_violations:
            rejected_infeasible += 1
            continue
        if candidate_obj >= current_obj - TOL:
            rejected_non_improving += 1
            continue
        accepted.append(
            {
                "route_index": variant.route_index,
                "label": variant.label,
                "charge_amount_strategy": (
                    variant.charge_amount_strategy
                ),
                "before_cost": float(current_obj),
                "after_cost": float(candidate_obj),
                "improvement": float(current_obj - candidate_obj),
                "charging_action_count": len(variant.actions),
            }
        )
        current = candidate
        current_obj = candidate_obj
        accepted_route_indices.add(variant.route_index)

    current, _ = _physicalize_multitrip_solution(current, bundle)
    final_obj, final_breakdown, final_violations = exact_china81_score(
        current,
        bundle,
        depot_charge_window_mode=depot_charge_window_mode,
    )
    if final_violations:
        raise RuntimeError(
            "shared China81 completion returned an infeasible solution: "
            + _violation_summary(final_violations)
        )
    _require_finite_depot_fleet(current, bundle)
    if final_obj > finite_fleet_reference_obj + TOL:
        raise RuntimeError(
            "shared China81 completion violated its post-fleet "
            "monotone contract"
        )

    activity: dict[str, Any] = {
        "schema_version": "resetp.china81-shared-completion.v1",
        "depot_charge_window_mode": depot_charge_window_mode,
        "charge_timing_policy": charge_timing_policy,
        "public_station_candidate_mode": public_station_candidate_mode,
        "baseline_all_cv_cost": float(baseline_obj),
        "finite_fleet_reference_cost": float(
            finite_fleet_reference_obj
        ),
        "final_cost": float(final_obj),
        "strict_improvement": bool(
            final_obj < finite_fleet_reference_obj - TOL
        ),
        "improvement": float(
            finite_fleet_reference_obj - final_obj
        ),
        "route_count": len(current.routes),
        "ev_route_count": sum(
            route.vehicle_type.lower() == "ev"
            for route in current.routes
        ),
        "charging_action_count": len(current.charging_actions),
        "cross_site_service_count": len(current.cross_site_services),
        "mechanism_experts_queried": [
            "vehicle_type_and_nonlinear_charging",
            "time_varying_electricity_and_carbon",
            "multi_depot_responsibility_accounting",
        ],
        "variant_count": len(all_variants),
        "charge_amount_strategies": list(
            charge_amount_strategies
        ),
        "charge_amount_strategy_generation": {
            name: {
                "generated": sum(
                    item.charge_amount_strategy == name
                    for item in all_variants
                ),
                "failed": sum(
                    item["charge_amount_strategy"] == name
                    for item in generation_failures
                ),
            }
            for name in charge_amount_strategies
        },
        "charge_amount_strategy_acceptance": {
            name: sum(
                item["charge_amount_strategy"] == name
                for item in (
                    *mandatory_fleet_assignments,
                    *accepted,
                )
            )
            for name in charge_amount_strategies
        },
        "variant_attempts": attempted,
        "variant_generation_failures": generation_failures,
        "mandatory_fleet_assignment_count": len(
            mandatory_fleet_assignments
        ),
        "mandatory_fleet_assignments": (
            mandatory_fleet_assignments
        ),
        "rejected_infeasible": rejected_infeasible,
        "rejected_non_improving": rejected_non_improving,
        "accepted_variants": accepted,
        "baseline_breakdown": baseline_breakdown,
        "final_breakdown": final_breakdown,
    }
    return China81CompletionResult(
        solution=current,
        objective=float(final_obj),
        breakdown=final_breakdown,
        activity=activity,
    )


def _require_finite_depot_fleet(
    solution: Solution,
    bundle: China81Bundle,
) -> None:
    used = _depot_physical_counts(solution)
    for (depot_id, vehicle_type), count in used.items():
        if vehicle_type not in {"cv", "ev"}:
            raise RuntimeError(
                f"unsupported China81 vehicle type {vehicle_type!r}"
            )
        try:
            cap = int(
                bundle.fleet_caps_by_depot[depot_id][
                    f"num_{vehicle_type}"
                ]
            )
        except KeyError as exc:
            raise RuntimeError(
                f"missing China81 fleet cap for {depot_id!r}"
            ) from exc
        if count > cap:
            raise RuntimeError(
                "shared China81 completion exceeded the registered "
                f"fleet cap: {depot_id}:{vehicle_type}:{count}>{cap}"
            )
    for depot_id, caps in bundle.fleet_caps_by_depot.items():
        total = used.get((depot_id, "cv"), 0) + used.get(
            (depot_id, "ev"),
            0,
        )
        total_cap = int(caps["total_fleet_cap"])
        if total > total_cap:
            raise RuntimeError(
                "shared China81 completion exceeded the registered total "
                f"fleet cap: {depot_id}:total:{total}>{total_cap}"
            )


def _canonical_all_cv_solution(
    skeleton: Solution,
    bundle: China81Bundle,
) -> Solution:
    node_lookup = {
        node.node_id: node
        for node in bundle.instance.nodes
    }
    depots = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    routes: list[Route] = []
    for route_index, route in enumerate(skeleton.routes):
        if route.home_depot_id not in depots:
            raise ValueError(
                f"route {route_index} has unknown home depot "
                f"{route.home_depot_id!r}"
            )
        customers = [
            node_id
            for node_id in route.node_sequence
            if node_id in node_lookup
            and node_lookup[node_id].node_type.lower() == "c"
        ]
        if not customers:
            continue
        routes.append(
            Route(
                vehicle_id=f"CH81-{len(routes) + 1:04d}",
                vehicle_type="cv",
                home_depot_id=route.home_depot_id,
                node_sequence=[
                    route.home_depot_id,
                    *customers,
                    route.home_depot_id,
                ],
            )
        )
    return annotate_cross_site_services(
        Solution(routes=routes),
        bundle.customer_home_depot,
    )


def _single_route_cost(
    route: Route,
    actions: tuple[ChargingAction, ...],
    bundle: China81Bundle,
) -> float:
    partial = annotate_cross_site_services(
        Solution(
            routes=[route],
            charging_actions=list(actions),
        ),
        bundle.customer_home_depot,
    )
    return float(
        evaluate(
            partial,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )["total_cost"]
    )


def _replace_route_variant(
    solution: Solution,
    *,
    route_index: int,
    route: Route,
    actions: tuple[ChargingAction, ...],
    customer_home_depot: dict[str, str] | Any,
) -> Solution:
    old_vehicle_id = solution.routes[route_index].vehicle_id
    routes = list(solution.routes)
    routes[route_index] = route
    kept_actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id != old_vehicle_id
    ]
    candidate = Solution(
        routes=routes,
        charging_actions=[*kept_actions, *actions],
    )
    return annotate_cross_site_services(candidate, customer_home_depot)


def _violation_summary(violations: list[Violation]) -> str:
    return "; ".join(
        f"{item.type}:{item.vehicle_id}:{item.location}:{item.detail}"
        for item in violations[:8]
    )
