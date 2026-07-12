"""Version-isolated E3 scoring adapter for physical multi-trip vehicles.

The frozen cost/evaluation/check modules remain unchanged.  Under the explicit
E3 flag, this adapter prepares one canonical physical schedule, carries battery
state between trips, and then delegates every unaffected rule to the legacy
checker and every monetary/carbon term to the canonical evaluator.
"""

from __future__ import annotations

import os
import json
from typing import Any

from ..check import (
    BATTERY,
    CHARGING_START,
    DynamicCheckContext,
    DynamicVehicleState,
    ROUTE_STRUCTURE,
    Violation,
    check_solution,
)
from ..cost import evaluate
from ..solution import Solution
from .evaluation import (
    BIG_M,
    EvaluationContext,
    _prices_with_carbon_weight,
    fairness_context_for_solution,
    model_cost as legacy_model_cost,
    score_candidate as legacy_score_candidate,
    score_reference as legacy_score_reference,
)
from .multitrip_schedule import (
    CONTRACT_ID,
    MultiTripCertificate,
    drop_multitrip_identity,
    prepare_multitrip_solution,
)


def enabled() -> bool:
    return os.environ.get("SETP_E3_STRICT_MULTITRIP", "0").lower() not in {"0", "false", "no"}


def prepare_solution(solution: Solution, context: EvaluationContext) -> tuple[Solution, MultiTripCertificate | None]:
    if not enabled():
        return solution, None
    context.score_counts["strict_multitrip_schedule_builds"] = int(
        context.score_counts.get("strict_multitrip_schedule_builds", 0)
    ) + 1
    return prepare_multitrip_solution(solution, context.instance, context.prices)


def hard_violations(solution: Solution, context: EvaluationContext) -> list[Any]:
    if not enabled():
        return check_solution(
            solution,
            context.instance,
            context.prices,
            fairness_context=fairness_context_for_solution(solution, context),
            fairness_enabled=context.fairness_enabled,
        )
    cached = context.score_breakdowns.get(id(solution), {})
    if (
        cached.get("strict_multitrip_ledger") is True
        and cached.get("_solution_signature") == _solution_signature(solution)
        and "_violations" in cached
    ):
        context.score_counts["strict_multitrip_check_cache_hits"] = int(
            context.score_counts.get("strict_multitrip_check_cache_hits", 0)
        ) + 1
        return list(cached["_violations"])
    try:
        prepared, certificate = prepare_solution(solution, context)
    except ValueError as exc:
        return [Violation(ROUTE_STRUCTURE, "", CONTRACT_ID, str(exc))]
    assert certificate is not None
    return _hard_violations_prepared(prepared, certificate, context)


def _hard_violations_prepared(
    prepared: Solution,
    certificate: MultiTripCertificate,
    context: EvaluationContext,
) -> list[Any]:
    prices = _prices_with_carbon_weight(context.prices, context.carbon_weight)
    dynamic_states = _dynamic_states(prepared, certificate, prices)
    violations = check_solution(
        prepared,
        context.instance,
        prices,
        fairness_context=fairness_context_for_solution(prepared, context, prices=prices),
        fairness_enabled=context.fairness_enabled,
        dynamic_context=DynamicCheckContext(vehicle_states=dynamic_states, allow_open_start=True),
    )
    later_trip_ids = {trip.route_id for trip in certificate.trips if trip.trip_index > 1}
    violations = [
        item
        for item in violations
        if not (
            item.type == CHARGING_START
            and item.vehicle_id in later_trip_ids
            and "depot charging starts before return" in item.detail
        )
    ]
    if context.instance.num_cv is not None and certificate.vehicle_counts["cv"] > int(context.instance.num_cv):
        violations.append(Violation(ROUTE_STRUCTURE, "", CONTRACT_ID, "实体油车数量超过上限"))
    if context.instance.num_ev is not None and certificate.vehicle_counts["ev"] > int(context.instance.num_ev):
        violations.append(Violation(ROUTE_STRUCTURE, "", CONTRACT_ID, "实体电车数量超过上限"))
    depot_caps = _depot_asset_caps()
    if depot_caps:
        used: dict[tuple[str, str], set[str]] = {}
        for trip in certificate.trips:
            used.setdefault((trip.home_depot_id, trip.vehicle_type), set()).add(trip.physical_vehicle_id)
        for depot_id, by_type in depot_caps.items():
            for vehicle_type in ("cv", "ev"):
                actual = len(used.get((depot_id, vehicle_type), set()))
                cap = int(by_type.get(vehicle_type, 0))
                if actual > cap:
                    violations.append(
                        Violation(
                            ROUTE_STRUCTURE,
                            "",
                            CONTRACT_ID,
                            f"车场{depot_id}的{vehicle_type}实体车需要{actual}辆，冻结上限为{cap}辆",
                        )
                    )
    return violations


def prepare_and_score_candidate(solution: Solution, context: EvaluationContext) -> tuple[Solution, float]:
    if not enabled():
        return solution, float(legacy_score_candidate(solution, context, label="candidate"))
    context.score_counts["candidate"] = int(context.score_counts.get("candidate", 0)) + 1
    if context.budget is not None:
        context.budget.record()
    # A route edit invalidates the old physical-vehicle labels. Rebuild the
    # packing for every complete candidate; references/final rechecks remain
    # idempotent and preserve their certified labels.
    return _prepare_and_score(drop_multitrip_identity(solution), context)


def prepare_and_score_reference(solution: Solution, context: EvaluationContext) -> tuple[Solution, float]:
    if not enabled():
        return solution, float(legacy_score_reference(solution, context))
    return _prepare_and_score(solution, context)


def prepared_model_cost(solution: Solution, context: EvaluationContext) -> tuple[Solution, float]:
    if not enabled():
        return solution, float(legacy_model_cost(solution, context))
    prepared, _ = prepare_solution(solution, context)
    prices = _prices_with_carbon_weight(context.prices, context.carbon_weight)
    value = evaluate(
        prepared,
        context.instance,
        context.carbon_profile,
        prices,
        carbon_quota_kg=context.carbon_quota_kg,
    )["total_cost"]
    return prepared, float(value)


def _prepare_and_score(solution: Solution, context: EvaluationContext) -> tuple[Solution, float]:
    try:
        prepared, certificate = prepare_solution(solution, context)
        assert certificate is not None
        prices = _prices_with_carbon_weight(context.prices, context.carbon_weight)
        cost = float(
            evaluate(
                prepared,
                context.instance,
                context.carbon_profile,
                prices,
                carbon_quota_kg=context.carbon_quota_kg,
            )["total_cost"]
        )
        violations = _hard_violations_prepared(prepared, certificate, context)
        cross_site_count = len(prepared.cross_site_services)
        context.score_counts["cross_site_complete_candidates"] = int(
            context.score_counts.get("cross_site_complete_candidates", 0)
        ) + int(cross_site_count > 0)
        if cross_site_count > 0 and not violations:
            context.score_counts["cross_site_legal_candidates"] = int(
                context.score_counts.get("cross_site_legal_candidates", 0)
            ) + 1
        if cross_site_count > 0:
            for violation_type in {str(item.type) for item in violations if hasattr(item, "type")}:
                key = f"cross_site_reject_{violation_type.lower()}"
                context.score_counts[key] = int(context.score_counts.get(key, 0)) + 1
        for violation_type in {str(item.type) for item in violations if hasattr(item, "type")}:
            key = f"strict_reject_{violation_type.lower()}"
            context.score_counts[key] = int(context.score_counts.get(key, 0)) + 1
        objective = cost + BIG_M * len(violations)
        context.score_breakdowns[id(prepared)] = {
            "raw_cost": cost,
            "objective": float(objective),
            "penalty": float(BIG_M * len(violations)),
            "violation_count": len(violations),
            "feasible": not violations,
            "strict_multitrip_ledger": True,
            "_solution_signature": _solution_signature(prepared),
            "_violations": tuple(violations),
        }
        return prepared, float(objective)
    except ValueError as exc:
        if "public-station trips are unsupported" in str(exc):
            context.score_counts["strict_public_station_incompatibility"] = int(
                context.score_counts.get("strict_public_station_incompatibility", 0)
            ) + 1
        context.score_counts["strict_multitrip_prepare_failures"] = int(
            context.score_counts.get("strict_multitrip_prepare_failures", 0)
        ) + 1
        context.score_breakdowns[id(solution)] = {
            "raw_cost": BIG_M,
            "objective": BIG_M,
            "penalty": BIG_M,
            "violation_count": 1,
            "feasible": False,
            "strict_multitrip_ledger": False,
            "_solution_signature": _solution_signature(solution),
            "reason": str(exc),
        }
        return solution, float(BIG_M)


def _solution_signature(solution: Solution) -> tuple[Any, ...]:
    return (
        tuple(
            (route.vehicle_id, route.vehicle_type, route.home_depot_id, tuple(route.node_sequence))
            for route in solution.routes
        ),
        tuple(
            (
                action.vehicle_id,
                action.station_id,
                float(action.energy_kwh),
                float(action.occupancy_minutes),
                float(action.charge_start_second),
            )
            for action in solution.charging_actions
        ),
        tuple(
            (service.customer_id, service.served_by_depot_id)
            for service in solution.cross_site_services
        ),
    )


def _dynamic_states(
    solution: Solution,
    certificate: MultiTripCertificate,
    prices: Any,
) -> dict[str, DynamicVehicleState]:
    by_vehicle: dict[str, list[Any]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    routes = {route.vehicle_id: route for route in solution.routes}
    initial_battery = float(getattr(prices, "initial_ev_battery_kwh", 0.0) if not isinstance(prices, dict) else prices.get("initial_ev_battery_kwh", 0.0))
    capacity = float(getattr(prices, "Q_capacity", 0.0) if not isinstance(prices, dict) else prices.get("Q_capacity", 0.0))
    states: dict[str, DynamicVehicleState] = {}
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        for index, trip in enumerate(ordered):
            route = routes[trip.route_id]
            before_charge = initial_battery if index == 0 else float(ordered[index - 1].end_battery_kwh or 0.0)
            states[trip.route_id] = DynamicVehicleState(
                vehicle_id=trip.route_id,
                position_node_id=route.node_sequence[0],
                current_time=0.0,
                remaining_load_kg=capacity,
                remaining_battery_kwh=before_charge if trip.vehicle_type == "ev" else 0.0,
            )
    return states


def _depot_asset_caps() -> dict[str, dict[str, int]]:
    raw = os.environ.get("SETP_E3_DEPOT_ASSET_CAPS_JSON", "").strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    return {
        str(depot): {str(vehicle_type).lower(): int(value) for vehicle_type, value in dict(by_type).items()}
        for depot, by_type in dict(payload).items()
    }
