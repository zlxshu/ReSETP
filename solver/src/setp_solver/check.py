from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .cost import (
    _arc_loads,
    charging_slot_breakdown,
    ev_arc_energy_kwh,
    route_next_day_departure_second,
    route_node_schedule,
    route_return_arrival_without_charging,
)
from .instance_loader import Instance, Node
from .prices import DEFAULT_PRICES, PriceParameters
from .solution import ChargingAction, Route, Solution, physical_vehicle_id


# v2026-06-11: expose paper-facing hard-constraint names through Violation.type.
CUSTOMER_COVERAGE = "CUSTOMER_COVERAGE"
FLOW_BALANCE = "FLOW_BALANCE"
FLEET_SIZE = "FLEET_SIZE"
CAPACITY = "CAPACITY"
TIME_WINDOW = "TIME_WINDOW"
BATTERY = "BATTERY"
CHARGING_STATION_UNIQUENESS = "CHARGING_STATION_UNIQUENESS"
ROUTE_STRUCTURE = "ROUTE_STRUCTURE"
CHARGING_START = "CHARGING_START"
CHARGING_POWER = "CHARGING_POWER"
STATION_CAPACITY = "STATION_CAPACITY"
PROFIT_FAIRNESS = "PROFIT_FAIRNESS"
FEASIBILITY_TOL = 1e-9
# v2026-06-11: freeze profit fairness by default; enabling it requires an explicit FairnessContext.
FAIRNESS_ENABLED = False


@dataclass(frozen=True)
class Violation:
    type: str
    vehicle_id: str
    location: str
    detail: str
    severity: str = "hard"


@dataclass(frozen=True)
class FairnessContext:
    """Inputs for the optional depot profit-fairness hard check.

    v2026-06-11: Implements paper_main.tex lines 485-512. The paper defines
    depot profit as ``Pi_d = prior_profit + assigned_revenue - allocated_cost``
    and enforces ``Pi_d >= theta * Pi_d0``. Use this context only after the
    external experiment code has computed consistent depot profits and positive
    independent baselines; the default checker leaves this frozen off.
    """

    depot_profit: dict[str, float]
    independent_profit: dict[str, float]
    theta: float


@dataclass(frozen=True)
class DynamicVehicleState:
    """Inherited vehicle state for one rolling-reoptimization stage."""

    vehicle_id: str
    position_node_id: str
    current_time: float
    remaining_load_kg: float
    remaining_battery_kwh: float


@dataclass(frozen=True)
class DynamicCheckContext:
    """Optional rolling-stage checks; static checks remain the default.

    v2026-06-12: W2b exposes the paper's dynamic interface fields to the
    checker. ``allow_open_start`` permits a route to start at the inherited
    vehicle position, while ``frozen_prefixes`` proves committed route prefixes
    are not rewritten by later stages.
    """

    vehicle_states: dict[str, DynamicVehicleState] = field(default_factory=dict)
    frozen_prefixes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reserved_charging_actions: tuple[ChargingAction, ...] = ()
    reserved_physical_vehicle_ids: tuple[str, ...] = ()
    allow_open_start: bool = False


def check_solution(
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    fairness_context: FairnessContext | None = None,
    fairness_enabled: bool | None = None,
    dynamic_context: DynamicCheckContext | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
    node_lookup = {node.node_id: node for node in instance.nodes}
    charging_by_vehicle_node = _charging_index(solution.charging_actions)

    violations.extend(_check_structure(solution, node_lookup))
    violations.extend(_check_dynamic_context(solution, dynamic_context))
    violations.extend(_check_customer_service(solution, node_lookup))
    violations.extend(_check_vehicle_count(solution, instance))
    violations.extend(_check_station_capacity(solution, node_lookup, instance, dynamic_context))

    for route in solution.routes:
        if not _route_nodes_valid(route, node_lookup):
            continue
        dynamic_state = None if dynamic_context is None else dynamic_context.vehicle_states.get(route.vehicle_id)
        violations.extend(_check_route_flow(route, node_lookup, dynamic_context))
        violations.extend(
            _check_capacity(
                route,
                node_lookup,
                prices,
                dynamic_state=dynamic_state,
                allow_open_start=bool(dynamic_context and dynamic_context.allow_open_start),
            )
        )
        violations.extend(
            _check_time_windows(
                route,
                instance,
                node_lookup,
                solution.charging_actions,
                prices,
                dynamic_state=dynamic_state,
                allow_open_start=bool(dynamic_context and dynamic_context.allow_open_start),
            )
        )
        if route.vehicle_type.lower() == "ev":
            violations.extend(
                _check_charging_start_and_power(
                    route,
                    instance,
                    node_lookup,
                    solution.charging_actions,
                    prices,
                    dynamic_state=dynamic_state,
                    allow_open_start=bool(dynamic_context and dynamic_context.allow_open_start),
                )
            )
            violations.extend(
                _check_battery(
                    route,
                    instance,
                    node_lookup,
                    charging_by_vehicle_node,
                    prices,
                    dynamic_state=dynamic_state,
                    allow_open_start=bool(dynamic_context and dynamic_context.allow_open_start),
                )
            )

    violations.extend(_check_profit_fairness(fairness_context, FAIRNESS_ENABLED if fairness_enabled is None else fairness_enabled))
    return violations

def _charging_index(actions: list[ChargingAction]) -> dict[tuple[str, str], list[ChargingAction]]:
    out: dict[tuple[str, str], list[ChargingAction]] = defaultdict(list)
    for action in actions:
        out[(action.vehicle_id, action.station_id)].append(action)
    return out


def _check_structure(solution: Solution, node_lookup: dict[str, Node]) -> list[Violation]:
    violations: list[Violation] = []
    vehicle_ids = Counter(route.vehicle_id for route in solution.routes)
    for vehicle_id, count in vehicle_ids.items():
        if count > 1:
            violations.append(
                Violation(
                    ROUTE_STRUCTURE,
                    vehicle_id,
                    vehicle_id,
                    (
                        f"route/trip vehicle_id appears {count} times; use distinct "
                        f"{physical_vehicle_id(vehicle_id)}#Tn ids for reusable physical vehicles"
                    ),
                )
            )
    physical_vehicle_type: dict[str, str] = {}
    for route in solution.routes:
        if not route.node_sequence:
            violations.append(Violation(ROUTE_STRUCTURE, route.vehicle_id, "", "route has empty node_sequence"))
            continue
        physical_id = physical_vehicle_id(route.vehicle_id)
        vehicle_type = route.vehicle_type.lower()
        previous = physical_vehicle_type.get(physical_id)
        if previous is None:
            physical_vehicle_type[physical_id] = vehicle_type
        elif previous != vehicle_type:
            violations.append(
                Violation(
                    ROUTE_STRUCTURE,
                    route.vehicle_id,
                    physical_id,
                    (
                        "physical vehicle id reused with inconsistent type: "
                        f"first={previous}, current={vehicle_type}"
                    ),
                )
            )
        for node_id in route.node_sequence:
            if node_id not in node_lookup:
                violations.append(Violation(ROUTE_STRUCTURE, route.vehicle_id, node_id, f"unknown node id {node_id}"))
    return violations


def _check_dynamic_context(solution: Solution, context: DynamicCheckContext | None) -> list[Violation]:
    if context is None:
        return []
    routes = {route.vehicle_id: route for route in solution.routes}
    violations: list[Violation] = []
    reserved = set(context.reserved_physical_vehicle_ids)
    for route in solution.routes:
        physical_id = physical_vehicle_id(route.vehicle_id)
        if physical_id in reserved:
            violations.append(
                Violation(
                    ROUTE_STRUCTURE,
                    route.vehicle_id,
                    physical_id,
                    "in-progress vehicle is unavailable to the new planning stage",
                )
            )
    for vehicle_id, prefix in context.frozen_prefixes.items():
        route = routes.get(vehicle_id)
        if route is None:
            violations.append(Violation(ROUTE_STRUCTURE, vehicle_id, vehicle_id, "frozen prefix route is missing"))
            continue
        expected = list(prefix)
        actual = route.node_sequence[: len(expected)]
        if actual != expected:
            violations.append(
                Violation(
                    ROUTE_STRUCTURE,
                    vehicle_id,
                    "->".join(expected),
                    f"frozen prefix changed: expected {expected}, got {actual}",
                )
            )
    return violations


def _check_customer_service(solution: Solution, node_lookup: dict[str, Node]) -> list[Violation]:
    visits: Counter[str] = Counter()
    for route in solution.routes:
        for node_id in route.node_sequence:
            node = node_lookup.get(node_id)
            if node and node.node_type.lower() == "c":
                visits[node_id] += 1

    violations: list[Violation] = []
    for node in node_lookup.values():
        if node.node_type.lower() != "c":
            continue
        count = visits[node.node_id]
        if count == 0:
            violations.append(Violation(CUSTOMER_COVERAGE, "", node.node_id, "customer not served"))
        elif count > 1:
            violations.append(Violation(CUSTOMER_COVERAGE, "", node.node_id, f"customer served {count} times"))
    return violations


def _check_vehicle_count(solution: Solution, instance: Instance) -> list[Violation]:
    """Enforce structural CV/EV fleet availability when the instance provides it."""

    violations: list[Violation] = []
    vehicles_by_type: dict[str, set[str]] = defaultdict(set)
    for route in solution.routes:
        vehicles_by_type[route.vehicle_type.lower()].add(physical_vehicle_id(route.vehicle_id))
    max_cv = getattr(instance, "num_cv", None)
    max_ev = getattr(instance, "num_ev", None)
    cv_count = len(vehicles_by_type["cv"])
    ev_count = len(vehicles_by_type["ev"])
    if max_cv is not None and cv_count > int(max_cv):
        violations.append(
            Violation(
                FLEET_SIZE,
                "",
                "cv",
                f"CV physical vehicles {cv_count} exceed available fuel vehicles {int(max_cv)}",
            )
        )
    if max_ev is not None and ev_count > int(max_ev):
        violations.append(
            Violation(
                FLEET_SIZE,
                "",
                "ev",
                f"EV physical vehicles {ev_count} exceed available electric vehicles {int(max_ev)}",
            )
        )
    return violations


def _check_station_capacity(
    solution: Solution,
    node_lookup: dict[str, Node],
    instance: Instance,
    dynamic_context: DynamicCheckContext | None = None,
) -> list[Violation]:
    """Check paper C_s capacity by station/depot and half-hour slot.

    v2026-06-12: Z0b replaces the old public-station uniqueness shortcut with
    the actual eq:station_capacity semantics. A vehicle occupying the same
    station in the same slot is counted once even if an action splits within
    the slot; depots use a static large charger count when no value is stored.
    """

    customer_count = sum(1 for node in node_lookup.values() if node.node_type.lower() == "c")
    occupied: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    actions = [*solution.charging_actions]
    if dynamic_context is not None:
        actions.extend(dynamic_context.reserved_charging_actions)
    for action in actions:
        node = node_lookup.get(action.station_id)
        if node is None or node.node_type.lower() not in {"d", "f"}:
            continue
        for slot in charging_slot_breakdown(
            float(action.charge_start_second),
            float(action.occupancy_minutes) * 60.0,
            float(action.energy_kwh),
            instance,
            n_slots=48,
            cyclic=True,
        ):
            occupied[(action.station_id, int(action.charge_day_offset), slot.slot_index)].add(action.vehicle_id)

    violations: list[Violation] = []
    for (station_id, day_offset, slot_index), vehicle_ids in sorted(occupied.items()):
        station = node_lookup[station_id]
        capacity = _station_chargers(station, customer_count)
        if len(vehicle_ids) > capacity:
            location = f"{station_id}@slot{slot_index}" if day_offset == 0 else f"{station_id}@day{day_offset}:slot{slot_index}"
            day_detail = "" if day_offset == 0 else f", day={day_offset}"
            violations.append(
                Violation(
                    STATION_CAPACITY,
                    ",".join(sorted(vehicle_ids)),
                    location,
                    f"occupied vehicles={len(vehicle_ids)} exceeds C_s={capacity} at {station_id}{day_detail}, slot={slot_index}",
                )
            )
    return violations


def _check_route_flow(route: Route, node_lookup: dict[str, Node], dynamic_context: DynamicCheckContext | None = None) -> list[Violation]:
    violations: list[Violation] = []
    first = node_lookup[route.node_sequence[0]]
    last = node_lookup[route.node_sequence[-1]]
    dynamic_state = None if dynamic_context is None else dynamic_context.vehicle_states.get(route.vehicle_id)
    open_start_allowed = bool(dynamic_context and dynamic_context.allow_open_start and dynamic_state is not None)
    if open_start_allowed and route.node_sequence[0] != dynamic_state.position_node_id:
        violations.append(
            Violation(
                FLOW_BALANCE,
                route.vehicle_id,
                route.node_sequence[0],
                f"route start does not match inherited position {dynamic_state.position_node_id}",
            )
        )
    elif not open_start_allowed and first.node_type.lower() != "d":
        violations.append(Violation(FLOW_BALANCE, route.vehicle_id, route.node_sequence[0], "route does not start at a depot"))
    if last.node_type.lower() != "d":
        violations.append(Violation(FLOW_BALANCE, route.vehicle_id, route.node_sequence[-1], "route does not end at a depot"))
    if not open_start_allowed and route.node_sequence[0] != route.node_sequence[-1]:
        violations.append(Violation(FLOW_BALANCE, route.vehicle_id, f"{route.node_sequence[0]}->{route.node_sequence[-1]}", "route is not closed"))
    if route.home_depot_id not in node_lookup or node_lookup.get(route.home_depot_id, first).node_type.lower() != "d":
        violations.append(Violation(FLOW_BALANCE, route.vehicle_id, route.home_depot_id, "home_depot_id is not a valid depot"))
    elif (not open_start_allowed and route.node_sequence[0] != route.home_depot_id) or route.node_sequence[-1] != route.home_depot_id:
        violations.append(Violation(FLOW_BALANCE, route.vehicle_id, route.home_depot_id, "route endpoints do not match home_depot_id"))
    return violations


def _check_capacity(
    route: Route,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    dynamic_state: DynamicVehicleState | None = None,
    allow_open_start: bool = False,
) -> list[Violation]:
    if allow_open_start and dynamic_state is not None:
        return _check_inherited_capacity(route, node_lookup, prices, dynamic_state)
    loads = _arc_loads(route.node_sequence, node_lookup)
    violations: list[Violation] = []
    if loads and loads[0] > _price(prices, "Q_capacity"):
        violations.append(Violation(CAPACITY, route.vehicle_id, route.node_sequence[0], f"initial load {loads[0]:.6f} exceeds Q={_price(prices, 'Q_capacity'):.6f}"))
    for idx, load in enumerate(loads):
        arc = f"{route.node_sequence[idx]}->{route.node_sequence[idx + 1]}"
        if load < -1e-9:
            violations.append(Violation(CAPACITY, route.vehicle_id, arc, f"arc load is negative: {load:.6f}"))
        if idx > 0 and load > loads[idx - 1] + 1e-9:
            violations.append(Violation(CAPACITY, route.vehicle_id, arc, f"arc load increases from {loads[idx - 1]:.6f} to {load:.6f}"))
    for idx, node_id in enumerate(route.node_sequence[1:], start=1):
        node = node_lookup[node_id]
        if node.node_type.lower() != "c" or idx >= len(route.node_sequence) - 1:
            continue
        delivered = loads[idx - 1] - loads[idx]
        if abs(delivered - float(node.demand)) > 1e-6:
            violations.append(Violation(CAPACITY, route.vehicle_id, node_id, f"delivered {delivered:.6f}, expected demand {float(node.demand):.6f}"))
    return violations


def _check_inherited_capacity(
    route: Route,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
    dynamic_state: DynamicVehicleState,
) -> list[Violation]:
    capacity = _price(prices, "Q_capacity")
    remaining = float(dynamic_state.remaining_load_kg)
    violations: list[Violation] = []
    if remaining < -1e-9:
        violations.append(Violation(CAPACITY, route.vehicle_id, route.node_sequence[0], f"remaining load is negative: {remaining:.6f}"))
    if remaining > capacity + 1e-9:
        violations.append(
            Violation(
                CAPACITY,
                route.vehicle_id,
                route.node_sequence[0],
                f"inherited remaining load {remaining:.6f} exceeds Q={capacity:.6f}",
            )
        )

    for index, node_id in enumerate(route.node_sequence):
        node = node_lookup[node_id]
        if node.node_type.lower() != "c":
            continue
        demand = float(node.demand)
        if demand > remaining + 1e-9:
            violations.append(
                Violation(
                    CAPACITY,
                    route.vehicle_id,
                    node_id,
                    f"customer demand {demand:.6f} exceeds inherited remaining load {remaining:.6f}",
                )
            )
        remaining -= demand
        if remaining < -1e-9 and index + 1 < len(route.node_sequence):
            arc = f"{node_id}->{route.node_sequence[index + 1]}"
            violations.append(Violation(CAPACITY, route.vehicle_id, arc, f"arc load is negative: {remaining:.6f}"))
    return violations


def _check_time_windows(
    route: Route,
    instance: Instance,
    node_lookup: dict[str, Node],
    charging_actions: list[ChargingAction],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    dynamic_state: DynamicVehicleState | None = None,
    allow_open_start: bool = False,
) -> list[Violation]:
    violations: list[Violation] = []
    # v2026-06-11: TIME_WINDOW consumes the scorer's shared route schedule, including service_time and charging occupancy.
    for row in route_node_schedule(route, instance, prices, charging_actions=charging_actions):
        node = node_lookup[row.node_id]
        due = float(node.due_time)
        start = float(row.t_start) + (
            float(dynamic_state.current_time) if allow_open_start and dynamic_state is not None else 0.0
        )
        if start > due + FEASIBILITY_TOL:
            late = start - due
            violations.append(
                Violation(
                    TIME_WINDOW,
                    route.vehicle_id,
                    row.node_id,
                    f"late by {late:.3f} s (due l={due:.3f}, start={start:.3f})",
                )
            )
    return violations


def _check_charging_start_and_power(
    route: Route,
    instance: Instance,
    node_lookup: dict[str, Node],
    charging_actions: list[ChargingAction],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    dynamic_state: DynamicVehicleState | None = None,
    allow_open_start: bool = False,
) -> list[Violation]:
    violations: list[Violation] = []
    # v2026-06-11: use charging-aware schedule so later stations inherit earlier waiting/occupancy.
    schedule = {row.node_id: row for row in route_node_schedule(route, instance, prices, charging_actions=charging_actions)}
    route_node_ids = set(route.node_sequence)
    for action in charging_actions:
        if action.vehicle_id != route.vehicle_id:
            continue
        if action.station_id not in route_node_ids or action.station_id not in node_lookup:
            continue
        station = node_lookup[action.station_id]
        station_type = station.node_type.lower()
        if station_type not in {"d", "f"}:
            continue

        # v2026-06-12: S0 depot charge is allowed only at the origin depot and
        # must lie in the overnight window from route return to next departure.
        charge_start = float(action.charge_start_second)
        occupancy_sec = float(action.occupancy_minutes) * 60.0
        if station_type == "d":
            if action.station_id != route.node_sequence[0] or action.station_id != route.home_depot_id:
                violations.append(
                    Violation(
                        CHARGING_START,
                        route.vehicle_id,
                        action.station_id,
                        "depot charging is only allowed at the route origin depot before departure",
                    )
                )
                continue
            day_offset = int(action.charge_day_offset)
            if day_offset < 0:
                absolute_completion = charge_start + day_offset * 86_400.0 + occupancy_sec
                if charge_start < -FEASIBILITY_TOL or charge_start >= 86_400.0 + FEASIBILITY_TOL:
                    violations.append(
                        Violation(
                            CHARGING_START,
                            route.vehicle_id,
                            action.station_id,
                            f"pre-horizon depot charge clock={charge_start:.3f} is outside one representative day",
                        )
                    )
                if absolute_completion > FEASIBILITY_TOL:
                    violations.append(
                        Violation(
                            CHARGING_START,
                            route.vehicle_id,
                            action.station_id,
                            f"pre-horizon depot charge ends after day 0 by {absolute_completion:.3f} s",
                        )
                    )
            else:
                completion = charge_start + occupancy_sec
                earliest = route_return_arrival_without_charging(route, instance, prices)
                departure_deadline = route_next_day_departure_second(route, instance, prices)
                if charge_start < earliest - FEASIBILITY_TOL:
                    early = earliest - charge_start
                    violations.append(
                        Violation(
                            CHARGING_START,
                            route.vehicle_id,
                            action.station_id,
                            f"depot charging starts before return by {early:.3f} s (return={earliest:.3f}, start={charge_start:.3f})",
                        )
                    )
                if completion > departure_deadline + FEASIBILITY_TOL:
                    late = completion - departure_deadline
                    violations.append(
                        Violation(
                            CHARGING_START,
                            route.vehicle_id,
                            action.station_id,
                            f"depot charging completion={completion:.3f} misses departure deadline={departure_deadline:.3f} by {late:.3f} s",
                        )
                    )
            station_power_kw = _price(prices, "depot_charge_power_kw")
            power_symbol = "pi_d"
        else:
            # v2026-06-11: CHARGING_START enforces paper a_sk^tau cannot precede arrival/ready time.
            station_time = schedule[action.station_id]
            schedule_offset = (
                float(dynamic_state.current_time) if allow_open_start and dynamic_state is not None else 0.0
            )
            earliest = max(float(station_time.t_arrive) + schedule_offset, float(station.ready_time))
            station_power_kw = getattr(station, "charge_power_kw", None)
            power_symbol = "pi_s"
        charge_start = float(action.charge_start_second)
        if station_type != "d" and charge_start < earliest - FEASIBILITY_TOL:
            early = earliest - charge_start
            violations.append(
                Violation(
                    CHARGING_START,
                    route.vehicle_id,
                    action.station_id,
                    f"charge_start={charge_start:.3f} is early by {early:.3f} s (earliest={earliest:.3f})",
                )
            )

        # v2026-06-11: CHARGING_POWER uses the uniform-rate B-full specialization, so one action yields one violation.
        energy_kwh = float(action.energy_kwh)
        if station_power_kw is None:
            violations.append(
                Violation(
                    CHARGING_POWER,
                    route.vehicle_id,
                    action.station_id,
                    f"charge_power_kw is missing; cannot verify {power_symbol}",
                )
            )
            continue
        if occupancy_sec <= FEASIBILITY_TOL:
            if energy_kwh > FEASIBILITY_TOL:
                violations.append(
                    Violation(
                        CHARGING_POWER,
                        route.vehicle_id,
                        action.station_id,
                        f"positive energy {energy_kwh:.6f} kWh with zero occupancy",
                    )
            )
            continue
        rate_kw = energy_kwh / (occupancy_sec / 3600.0)
        if rate_kw > float(station_power_kw) + FEASIBILITY_TOL:
            excess = rate_kw - float(station_power_kw)
            violations.append(
                Violation(
                    CHARGING_POWER,
                    route.vehicle_id,
                    action.station_id,
                    f"rate={rate_kw:.6f} kW exceeds {power_symbol}={float(station_power_kw):.6f} kW by {excess:.6f}",
                )
            )
    return violations


def _check_battery(
    route: Route,
    instance: Instance,
    node_lookup: dict[str, Node],
    charging_by_vehicle_node: dict[tuple[str, str], list[ChargingAction]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    dynamic_state: DynamicVehicleState | None = None,
    allow_open_start: bool = False,
) -> list[Violation]:
    # v2026-06-12: Q2 aligns EV departure energy with paper line 391:
    # b_departure = bbar + depot charging <= B, rather than implicit full B.
    battery_cap = _price(prices, "B_battery_kwh")
    battery = (
        float(dynamic_state.remaining_battery_kwh)
        if allow_open_start and dynamic_state is not None
        else _price(prices, "initial_ev_battery_kwh")
    )
    violations: list[Violation] = []
    loads = _arc_loads(route.node_sequence, node_lookup)
    start_node_id = route.node_sequence[0]
    if battery > battery_cap + 1e-9:
        violations.append(
            Violation(
                BATTERY,
                route.vehicle_id,
                start_node_id,
                f"start battery bbar is {battery:.6f} kWh > B={battery_cap:.6f}",
            )
        )
    if node_lookup[start_node_id].node_type.lower() == "d":
        depot_energy = _charging_energy(route.vehicle_id, start_node_id, charging_by_vehicle_node)
        if depot_energy > FEASIBILITY_TOL:
            battery += depot_energy
            if battery > battery_cap + 1e-9:
                violations.append(
                    Violation(
                        BATTERY,
                        route.vehicle_id,
                        start_node_id,
                        f"start battery after depot charging is {battery:.6f} kWh > B={battery_cap:.6f}",
                    )
                )

    for idx, ((from_node_id, to_node_id), load_kg) in enumerate(zip(zip(route.node_sequence, route.node_sequence[1:]), loads)):
        distance_m = instance.distance(from_node_id, to_node_id)
        use_kwh = ev_arc_energy_kwh(distance_m, load_kg, prices)
        battery -= use_kwh
        arc = f"{from_node_id}->{to_node_id}"
        if battery < -1e-9:
            violations.append(Violation(BATTERY, route.vehicle_id, arc, f"battery after arc is {battery:.6f} kWh < 0"))

        to_node = node_lookup[to_node_id]
        if to_node.node_type.lower() == "f":
            battery += _charging_energy(route.vehicle_id, to_node_id, charging_by_vehicle_node)
            if battery > battery_cap + 1e-9:
                violations.append(Violation(BATTERY, route.vehicle_id, to_node_id, f"battery after charging is {battery:.6f} kWh > B={battery_cap:.6f}"))
    return violations


def _route_nodes_valid(route: Route, node_lookup: dict[str, Node]) -> bool:
    return bool(route.node_sequence) and all(node_id in node_lookup for node_id in route.node_sequence)


def _charging_energy(vehicle_id: str, node_id: str, charging_by_vehicle_node: dict[tuple[str, str], list[ChargingAction]]) -> float:
    return sum(float(action.energy_kwh) for action in charging_by_vehicle_node.get((vehicle_id, node_id), []))


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _station_chargers(node: Node, customer_count: int) -> int:
    raw = getattr(node, "station_chargers", None)
    if raw is not None:
        return max(0, int(raw))
    if node.node_type.lower() == "d":
        return max(1, int(customer_count))
    if node.node_type.lower() == "f":
        return 1
    return 0


def _check_profit_fairness(
    context: FairnessContext | None,
    enabled: bool,
) -> list[Violation]:
    if not enabled:
        return []
    if context is None:
        return [
            Violation(
                PROFIT_FAIRNESS,
                "",
                "fairness_context",
                "FairnessContext is required when PROFIT_FAIRNESS is enabled",
            )
        ]

    violations: list[Violation] = []
    theta = float(context.theta)
    for depot_id, baseline in context.independent_profit.items():
        baseline_value = float(baseline)
        if baseline_value <= FEASIBILITY_TOL:
            violations.append(
                Violation(
                    PROFIT_FAIRNESS,
                    "",
                    depot_id,
                    f"independent profit Pi0={baseline_value:.6f} must be positive before applying fairness",
                )
            )
            continue
        profit = float(context.depot_profit.get(depot_id, 0.0))
        required = theta * baseline_value
        if profit < required - FEASIBILITY_TOL:
            violations.append(
                Violation(
                    PROFIT_FAIRNESS,
                    "",
                    depot_id,
                    f"profit Pi={profit:.6f} below theta*Pi0={required:.6f} (theta={theta:.6f}, Pi0={baseline_value:.6f})",
                )
            )
    return violations
