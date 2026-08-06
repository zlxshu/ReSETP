"""Isolated E4 scorer for a 60%-20%-80%-at-least-60% SOC cycle."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import math
from typing import Any

from setp_solver.algorithms.resetp_alns.support import charging as charging_module
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeTimingChoice,
    ScoredChargeOption,
    charge_start_candidates,
    score_charge_option,
)
from setp_solver.check import (
    BATTERY,
    FLEET_SIZE,
    STATION_CAPACITY,
    Violation,
    check_solution,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    annotate_cross_site_services,
)
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    evaluate,
    ev_instance_arc_energy_kwh,
    route_departure_second,
    route_node_schedule,
)
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.search.multitrip_schedule import (
    ContinuousSOCContract,
    E4_CONTINUOUS_SOC_CONTRACT_ID,
)


COST_ONLY = "COST_ONLY"
COST_PLUS_CARBON = "COST_PLUS_CARBON"
PURE_CARBON = "PURE_CARBON"
MODES = (COST_ONLY, COST_PLUS_CARBON, PURE_CARBON)
SOC_INITIAL = 0.60
SOC_MIN = 0.20
SOC_MAX = 0.80
TOL = 1.0e-8

_MODE_BY_BUNDLE: dict[int, str] = {}


def multitrip_soc_contract(
    terminal_charges: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> ContinuousSOCContract:
    """Expose E4's existing SOC cycle to the generic multi-trip adapter."""

    return ContinuousSOCContract(
        contract_id=E4_CONTINUOUS_SOC_CONTRACT_ID,
        soc_initial=SOC_INITIAL,
        soc_min=SOC_MIN,
        soc_max=SOC_MAX,
        soc_final_minimum=SOC_INITIAL,
        terminal_charges=tuple(dict(row) for row in terminal_charges),
    )


@dataclass(frozen=True)
class FixedScore:
    solution: Solution
    objective: float
    breakdown: dict[str, float]
    violations: tuple[Violation, ...]
    terminal_charges: tuple[dict[str, Any], ...]
    soc_rows: tuple[dict[str, Any], ...]


def register_objective(bundle: China81Bundle, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown E4 objective: {mode}")
    _MODE_BY_BUNDLE[id(bundle)] = mode


def objective_for(bundle: China81Bundle) -> str:
    try:
        return _MODE_BY_BUNDLE[id(bundle)]
    except KeyError as exc:
        raise RuntimeError("E4 objective was not registered for this bundle") from exc


def physical_soc_prices(bundle: China81Bundle) -> Any:
    """Return the virtual ledger used by the unchanged checker.

    The checker uses zero as its lower battery bound.  Subtracting the physical
    20% reserve maps physical 20%-80% to virtual 0%-60%; physical 60% therefore
    enters the unchanged ledger as virtual 40%.
    """

    capacity = bundle.instance.battery_capacity_kwh(
        fallback=float(bundle.prices.B_battery_kwh)
    )
    return replace(
        bundle.prices,
        initial_ev_battery_kwh=(SOC_INITIAL - SOC_MIN) * capacity,
    )


@contextmanager
def route_pool_hooks() -> Any:
    """Temporarily route exact HGS-SP candidate scores through this model."""

    import epochal_hgs
    import route_pool_sp

    originals = (
        epochal_hgs.complete_china81_route_skeleton,
        route_pool_sp.complete_china81_route_skeleton,
        route_pool_sp.exact_china81_score,
        route_pool_sp._single_route_cost,
    )
    try:
        epochal_hgs.complete_china81_route_skeleton = complete_route_skeleton
        route_pool_sp.complete_china81_route_skeleton = complete_route_skeleton
        route_pool_sp.exact_china81_score = exact_score
        route_pool_sp._single_route_cost = single_route_objective
        yield
    finally:
        (
            epochal_hgs.complete_china81_route_skeleton,
            route_pool_sp.complete_china81_route_skeleton,
            route_pool_sp.exact_china81_score,
            route_pool_sp._single_route_cost,
        ) = originals


def complete_route_skeleton(
    skeleton: Solution,
    bundle: China81Bundle,
) -> China81CompletionResult:
    mode = objective_for(bundle)
    canonical = _canonical_all_cv(skeleton, bundle)
    routes = list(canonical.routes)
    actions_by_index: dict[int, tuple[ChargingAction, ...]] = {}
    option_by_index: dict[int, tuple[Route, tuple[ChargingAction, ...], float]] = {}

    for index, route in enumerate(routes):
        cv_objective = single_route_objective(route, (), bundle)
        ev_route = replace(route, vehicle_type="ev")
        try:
            repaired, actions = _repair_ev_without_depot_precharge(
                ev_route,
                bundle,
                mode,
            )
            ev_objective = single_route_objective(
                repaired,
                tuple(actions),
                bundle,
            )
        except (TypeError, ValueError):
            continue
        option_by_index[index] = (
            repaired,
            tuple(actions),
            float(ev_objective - cv_objective),
        )

    selected: set[int] = set()
    for depot_id in sorted(bundle.fleet_caps_by_depot):
        indices = [
            index
            for index, route in enumerate(routes)
            if route.home_depot_id == depot_id
        ]
        caps = bundle.fleet_caps_by_depot[depot_id]
        cv_cap = int(caps["num_cv"])
        ev_cap = int(caps["num_ev"])
        required_ev = max(0, len(indices) - cv_cap)
        if len(indices) > cv_cap + ev_cap:
            raise ValueError(f"fleet total exceeded at {depot_id}")
        candidates = sorted(
            (option_by_index[index][2], index)
            for index in indices
            if index in option_by_index
        )
        if len(candidates) < required_ev:
            raise ValueError(
                f"no 60-20-80 EV assignment meets the CV cap at {depot_id}"
            )
        selected.update(index for _, index in candidates[:required_ev])
        for delta, index in candidates[required_ev:]:
            if len(selected.intersection(indices)) >= ev_cap or delta >= -TOL:
                break
            selected.add(index)

    completed_routes: list[Route] = []
    completed_actions: list[ChargingAction] = []
    for index, route in enumerate(routes):
        if index in selected:
            route, actions, _ = option_by_index[index]
            actions_by_index[index] = actions
        vehicle_id = f"E4-{route.vehicle_type.upper()}-{index + 1:04d}"
        completed_routes.append(replace(route, vehicle_id=vehicle_id))
        completed_actions.extend(
            replace(action, vehicle_id=vehicle_id)
            for action in actions_by_index.get(index, ())
        )

    solution = annotate_cross_site_services(
        Solution(completed_routes, completed_actions),
        bundle.customer_home_depot,
    )
    score = score_fixed_solution(solution, bundle, validate_full=True)
    if score.violations:
        summary = "; ".join(
            f"{row.type}:{row.vehicle_id}:{row.detail}"
            for row in score.violations[:6]
        )
        raise ValueError(f"E4 completion is infeasible: {summary}")
    return China81CompletionResult(
        solution=score.solution,
        objective=score.objective,
        breakdown=score.breakdown,
        activity={
            "schema_version": "resetp.e4-joint-soc-wrapper.v1",
            "objective_mode": mode,
            "soc_initial": SOC_INITIAL,
            "soc_min": SOC_MIN,
            "soc_max": SOC_MAX,
            "soc_final_minimum": SOC_INITIAL,
            "terminal_charges": list(score.terminal_charges),
            "soc_rows": list(score.soc_rows),
        },
    )


def exact_score(
    solution: Solution,
    bundle: China81Bundle,
) -> tuple[float, dict[str, float], list[Violation]]:
    score = score_fixed_solution(solution, bundle, validate_full=True)
    return score.objective, score.breakdown, list(score.violations)


def single_route_objective(
    route: Route,
    actions: tuple[ChargingAction, ...],
    bundle: China81Bundle,
) -> float:
    score = score_fixed_solution(
        Solution(routes=[route], charging_actions=list(actions)),
        bundle,
        validate_full=False,
    )
    if score.violations:
        raise ValueError(score.violations[0].detail)
    return score.objective


def score_fixed_solution(
    solution: Solution,
    bundle: China81Bundle,
    *,
    validate_full: bool,
) -> FixedScore:
    mode = objective_for(bundle)
    solution = annotate_cross_site_services(
        solution,
        bundle.customer_home_depot,
    )
    prices = physical_soc_prices(bundle)
    violations = (
        check_solution(solution, bundle.instance, prices)
        if validate_full
        else []
    )
    violations.extend(_depot_fleet_violations(solution, bundle))

    terminal_actions: list[ChargingAction] = []
    terminal_rows: list[dict[str, Any]] = []
    soc_rows: list[dict[str, Any]] = []
    actions_by_vehicle: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        actions_by_vehicle.setdefault(action.vehicle_id, []).append(action)
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            continue
        try:
            soc, terminal = _soc_and_terminal_charge(
                route,
                tuple(actions_by_vehicle.get(route.vehicle_id, ())),
                bundle,
                mode,
            )
        except ValueError as exc:
            violations.append(
                Violation(BATTERY, route.vehicle_id, route.home_depot_id, str(exc))
            )
            continue
        soc_rows.append(soc)
        if terminal is not None:
            terminal_actions.append(terminal[0])
            terminal_rows.append(terminal[1])
    violations.extend(_terminal_capacity_violations(terminal_rows, bundle))

    zero_carbon_prices = replace(prices, carbon_price=0.0)
    base = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        zero_carbon_prices,
        carbon_quota_kg=math.inf,
    )
    terminal_cost = sum(
        charging_action_electricity_cost(
            action,
            bundle.instance,
            bundle.time_profile,
            prices,
        )
        for action in terminal_actions
    )
    terminal_emissions = sum(
        charging_action_emissions_kg(
            action,
            bundle.instance,
            bundle.time_profile,
            prices,
        )
        for action in terminal_actions
    )
    operating_cost = float(base["total_cost"]) + terminal_cost
    total_emissions = float(base["E_total"]) + terminal_emissions
    carbon_cost = total_emissions * float(bundle.prices.carbon_price)
    cost_plus_carbon = operating_cost + carbon_cost
    objective = {
        COST_ONLY: operating_cost,
        COST_PLUS_CARBON: cost_plus_carbon,
        PURE_CARBON: total_emissions,
    }[mode]
    breakdown = dict(base)
    breakdown.update(
        {
            "objective_value": objective,
            "operating_cost_cny": operating_cost,
            "cost_plus_carbon_cny": cost_plus_carbon,
            "total_cost": cost_plus_carbon,
            "cost_elec": float(base["cost_elec"]) + terminal_cost,
            "cost_carbon": carbon_cost,
            "E_total": total_emissions,
            "E_ev_indirect": float(base["E_ev_indirect"]) + terminal_emissions,
            "electricity_kwh": float(base["electricity_kwh"])
            + sum(float(action.energy_kwh) for action in terminal_actions),
            "depot_charging_kwh": sum(
                float(action.energy_kwh) for action in terminal_actions
            ),
            "terminal_charging_cost_cny": terminal_cost,
            "terminal_charging_emissions_kg": terminal_emissions,
        }
    )
    return FixedScore(
        solution,
        float(objective),
        breakdown,
        tuple(violations),
        tuple(terminal_rows),
        tuple(soc_rows),
    )


def _repair_ev_without_depot_precharge(
    route: Route,
    bundle: China81Bundle,
    mode: str,
) -> tuple[Route, list[ChargingAction]]:
    prices = physical_soc_prices(bundle)
    original_depot = charging_module._depot_precharge_action
    original_selector = charging_module.select_charge_option
    charging_module._depot_precharge_action = lambda *args, **kwargs: None
    if mode == COST_ONLY:
        charging_module.select_charge_option = _select_cost_only_charge_option
    elif mode == PURE_CARBON:
        charging_module.select_charge_option = _select_pure_carbon_charge_option
    try:
        return charging_module.repair_route_charging(
            route,
            bundle.instance,
            bundle.time_profile,
            prices,
            strategy="integrated",
            carbon_weight=(0.0 if mode == COST_ONLY else 1.0),
            depot_charge_window_mode="same_day_predeparture",
        )
    finally:
        charging_module._depot_precharge_action = original_depot
        charging_module.select_charge_option = original_selector


def _select_cost_only_charge_option(
    options: Any,
    instance: Any,
    carbon_profile: list[dict[str, object]],
    prices: Any,
    *,
    carbon_weight: float = 0.0,
) -> ScoredChargeOption:
    scored = [
        score_charge_option(
            option,
            instance,
            carbon_profile,
            prices,
            carbon_weight=0.0,
        )
        for option in options
    ]
    if not scored:
        raise ValueError("at least one charge option is required")
    return _select_cost_only_scored(scored)


def _select_cost_only_scored(
    scored: list[ScoredChargeOption],
) -> ScoredChargeOption:
    """Break equal monetary cost without consulting carbon emissions."""

    return min(
        scored,
        key=lambda item: (
            item.total_incremental_cost,
            item.option.detour_m,
            item.option.station_id,
            item.timing.start_second,
        ),
    )


def _select_pure_carbon_charge_option(
    options: Any,
    instance: Any,
    carbon_profile: list[dict[str, object]],
    prices: Any,
    *,
    carbon_weight: float = 1.0,
) -> ScoredChargeOption:
    del carbon_weight
    scored: list[ScoredChargeOption] = []
    for option in options:
        emissions, start = min(
            (
                charging_action_emissions_kg(
                    option.action_at(candidate),
                    instance,
                    carbon_profile,
                    prices,
                ),
                candidate,
            )
            for candidate in charge_start_candidates(
                option.earliest_start_second,
                option.latest_start_second,
                option.occupancy_seconds,
            )
        )
        action = option.action_at(start)
        electricity_cost = charging_action_electricity_cost(
            action, instance, carbon_profile, prices
        )
        occupancy_cost = (
            0.0
            if option.node_type.lower() == "d"
            else option.occupancy_seconds / 60.0 * float(prices.occupancy_fee)
        )
        detour_cost = float(option.detour_m) / 1000.0 * float(prices.c_km)
        scored.append(
            ScoredChargeOption(
                option=option,
                timing=ChargeTimingChoice(start, emissions, -1),
                electricity_cost=electricity_cost,
                occupancy_cost=occupancy_cost,
                detour_cost=detour_cost,
                carbon_cost=emissions * float(prices.carbon_price),
                total_incremental_cost=emissions,
            )
        )
    if not scored:
        raise ValueError("at least one charge option is required")
    return _select_pure_carbon_scored(scored)


def _select_pure_carbon_scored(
    scored: list[ScoredChargeOption],
) -> ScoredChargeOption:
    """Choose charging by emissions without consulting monetary cost."""

    return min(
        scored,
        key=lambda item: (
            item.timing.carbon_kg,
            item.option.detour_m,
            item.option.station_id,
            item.timing.start_second,
        ),
    )


def _soc_and_terminal_charge(
    route: Route,
    actions: tuple[ChargingAction, ...],
    bundle: China81Bundle,
    mode: str,
) -> tuple[
    dict[str, Any],
    tuple[ChargingAction, dict[str, Any]] | None,
]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    capacity = bundle.instance.battery_capacity_kwh(
        fallback=float(bundle.prices.B_battery_kwh)
    )
    floor = SOC_MIN * capacity
    virtual_cap = (SOC_MAX - SOC_MIN) * capacity
    initial_virtual = (SOC_INITIAL - SOC_MIN) * capacity
    battery = initial_virtual
    minimum = battery
    maximum = battery
    remaining = [
        node_id
        for node_id in route.node_sequence
        if nodes[node_id].node_type.lower() == "c"
    ]
    by_station: dict[str, list[ChargingAction]] = {}
    for action in actions:
        if nodes[action.station_id].node_type.lower() == "d":
            raise ValueError("day-start depot precharge is not allowed in this SOC cycle")
        by_station.setdefault(action.station_id, []).append(action)
    for left, right in zip(route.node_sequence, route.node_sequence[1:]):
        load = sum(float(nodes[node_id].demand) for node_id in remaining)
        battery -= ev_instance_arc_energy_kwh(
            bundle.instance,
            left,
            right,
            load,
            bundle.prices,
        )
        minimum = min(minimum, battery)
        if battery < -TOL:
            raise ValueError("physical SOC fell below 20%")
        for action in by_station.get(right, ()):
            battery += float(action.energy_kwh)
            maximum = max(maximum, battery)
            if battery > virtual_cap + TOL:
                raise ValueError("physical SOC exceeded 80%")
        if nodes[right].node_type.lower() == "c" and right in remaining:
            remaining.remove(right)
    terminal_energy = max(0.0, initial_virtual - battery)
    return_soc = (floor + battery) / capacity
    if terminal_energy <= TOL:
        return (
            {
                "vehicle_id": route.vehicle_id,
                "departure_soc": SOC_INITIAL,
                "minimum_soc": (floor + minimum) / capacity,
                "return_soc_before_terminal_charge": return_soc,
                "final_soc_after_terminal_charge": return_soc,
                "maximum_soc": (floor + maximum) / capacity,
            },
            None,
        )
    power = float(bundle.prices.depot_charge_power_kw)
    schedule = route_node_schedule(
        route,
        bundle.instance,
        bundle.prices,
        charging_actions=list(actions),
    )
    earliest = float(schedule[-1].t_arrive)
    action = charging_module._curve_aware_action(
        vehicle_id=route.vehicle_id,
        station_id=route.home_depot_id,
        start_energy_kwh=battery,
        energy_kwh=terminal_energy,
        reference_power_kw=power,
        prices=physical_soc_prices(bundle),
        instance=bundle.instance,
    )
    duration = float(action.occupancy_minutes) * 60.0
    next_departure = route_departure_second(
        route, bundle.instance, bundle.prices
    ) + 86_400.0
    while next_departure <= earliest + TOL:
        next_departure += 86_400.0
    latest = next_departure - duration
    if latest < earliest - TOL:
        raise ValueError("terminal restoration does not fit before next departure")
    action = replace(
        action,
        charge_start_second=_best_terminal_start(
            action, earliest, latest, bundle, mode
        ),
    )
    emissions = charging_action_emissions_kg(
        action, bundle.instance, bundle.time_profile, bundle.prices
    )
    cost = charging_action_electricity_cost(
        action, bundle.instance, bundle.time_profile, bundle.prices
    )
    physical_min = floor + minimum
    row = {
        "vehicle_id": route.vehicle_id,
        "station_id": route.home_depot_id,
        "energy_kwh": terminal_energy,
        "power_kw": power,
        "occupancy_minutes": duration / 60.0,
        "start_second_absolute": float(action.charge_start_second),
        "start_clock_second": float(action.charge_start_second) % 86_400.0,
        "day_offset": int(float(action.charge_start_second) // 86_400.0),
        "earliest_second_absolute": earliest,
        "latest_second_absolute": latest,
        "electricity_cost_cny": cost,
        "emissions_kg": emissions,
        "start_soc": return_soc,
        "end_soc": SOC_INITIAL,
        "end_second_absolute": float(action.charge_start_second) + duration,
    }
    soc = {
        "vehicle_id": route.vehicle_id,
        "departure_soc": SOC_INITIAL,
        "minimum_soc": physical_min / capacity,
        "return_soc_before_terminal_charge": return_soc,
        "final_soc_after_terminal_charge": SOC_INITIAL,
        "maximum_soc": (floor + maximum) / capacity,
    }
    return soc, (action, row)


def _best_terminal_start(
    action: ChargingAction,
    earliest: float,
    latest: float,
    bundle: China81Bundle,
    mode: str,
) -> float:
    candidates = charge_start_candidates(
        earliest,
        latest,
        action.occupancy_minutes * 60.0,
    )

    def key(start: float) -> tuple[float, float]:
        shifted = replace(action, charge_start_second=start)
        cost = charging_action_electricity_cost(
            shifted, bundle.instance, bundle.time_profile, bundle.prices
        )
        if mode == COST_ONLY:
            return cost, start
        emissions = charging_action_emissions_kg(
            shifted, bundle.instance, bundle.time_profile, bundle.prices
        )
        value = (
            cost + emissions * float(bundle.prices.carbon_price)
            if mode == COST_PLUS_CARBON
            else emissions
        )
        return value, start

    return min(candidates, key=key)


def _canonical_all_cv(skeleton: Solution, bundle: China81Bundle) -> Solution:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    depots = set(bundle.fleet_caps_by_depot)
    routes: list[Route] = []
    for source in skeleton.routes:
        if source.home_depot_id not in depots:
            raise ValueError(f"unknown home depot {source.home_depot_id}")
        customers = [
            node_id
            for node_id in source.node_sequence
            if node_id in nodes and nodes[node_id].node_type.lower() == "c"
        ]
        if customers:
            routes.append(
                Route(
                    f"E4-CV-{len(routes) + 1:04d}",
                    "cv",
                    source.home_depot_id,
                    [source.home_depot_id, *customers, source.home_depot_id],
                )
            )
    return annotate_cross_site_services(
        Solution(routes=routes), bundle.customer_home_depot
    )


def _depot_fleet_violations(
    solution: Solution,
    bundle: China81Bundle,
) -> list[Violation]:
    violations: list[Violation] = []
    for depot_id, caps in bundle.fleet_caps_by_depot.items():
        for vehicle_type in ("cv", "ev"):
            count = sum(
                route.home_depot_id == depot_id
                and route.vehicle_type.lower() == vehicle_type
                for route in solution.routes
            )
            cap = int(caps[f"num_{vehicle_type}"])
            if count > cap:
                violations.append(
                    Violation(
                        FLEET_SIZE,
                        "",
                        depot_id,
                        f"{vehicle_type} routes {count} exceed cap {cap}",
                    )
                )
    return violations


def _terminal_capacity_violations(
    rows: list[dict[str, Any]],
    bundle: China81Bundle,
) -> list[Violation]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    violations: list[Violation] = []
    for station_id in sorted({str(row["station_id"]) for row in rows}):
        station_rows = [row for row in rows if row["station_id"] == station_id]
        capacity = int(nodes[station_id].station_chargers or 1)
        events = []
        for row in station_rows:
            events.append((float(row["start_second_absolute"]), 1))
            events.append((float(row["end_second_absolute"]), -1))
        active = 0
        for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
            active += delta
            if active > capacity:
                violations.append(
                    Violation(
                        STATION_CAPACITY,
                        "",
                        station_id,
                        f"terminal charging concurrency {active} exceeds {capacity}",
                    )
                )
                break
    return violations


def score_payload(score: FixedScore) -> dict[str, Any]:
    return {
        "objective": score.objective,
        "breakdown": score.breakdown,
        "violations": [asdict(row) for row in score.violations],
        "terminal_charges": list(score.terminal_charges),
        "soc_rows": list(score.soc_rows),
    }
