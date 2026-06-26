"""Initial solution construction for search gates.

v2026-06-11: Builds a deterministic feasible seed for paper_main.tex
lines 541-553 algorithm-interface work: nearest-depot assignment, regret-2
customer insertion, and a placeholder dynamic-state inheritance hook. Use
``build_initial_solution`` before ALNS adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..check import check_solution
from ..cost import route_node_schedule
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution
from .charging import repair_route_charging
from .fleet import FleetLimits, UNBOUNDED_FLEET, normalize_solution_vehicle_trips, route_ev_energy_summary


@dataclass
class _RoutePlan:
    depot_id: str
    customer_ids: list[str]


def build_initial_solution(
    instance: Instance,
    carbon_profile: list[dict[str, Any]] | None = None,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    max_cv: int | None = None,
    fleet_limits: FleetLimits | None = None,
    introduce_ev: bool = True,
    require_charging_signal: bool = True,
) -> Solution:
    """Construct a feasible seed solution for the generated instance.

    v2026-06-11: H2 EV-enabled E5 seed. The first phase remains the original
    deterministic CV seed; when a carbon profile is available, the second
    phase moves one customer to an EV route and invokes the shared charging
    repair so E5 has a real charging signal.
    """

    limits = fleet_limits or FleetLimits(
        cv=int(instance.num_cv) if instance.num_cv is not None else UNBOUNDED_FLEET,
        ev=int(instance.num_ev) if instance.num_ev is not None else UNBOUNDED_FLEET,
        source="instance.num_cv/num_ev physical fleet caps",
    )
    # v2026-06-26: final solutions must respect CV/EV fleet caps, but the
    # deterministic warm start is still built as a temporary CV packing before
    # routes are electrified. When EVs are available, let that temporary seed
    # use the total available fleet count; otherwise low CV caps can falsely
    # block instances that become feasible after EV conversion.
    effective_max_cv = max_cv if max_cv is not None else limits.cv
    active_limits = replace(limits, cv=effective_max_cv)
    # v2026-06-26: a route is a trip/dispatch, not a physical vehicle. Build
    # as many trips as capacity/time windows require, then retag trips onto the
    # finite physical fleet before the final check.
    seed_route_limit = UNBOUNDED_FLEET
    route_budget = _seed_route_budget(instance, prices, max_cv=seed_route_limit)
    seed_max_budget = _customer_count(instance)
    enforce_seed_fleet_count = False
    solution = _build_cv_seed_with_retry(
        instance,
        prices,
        start_budget=route_budget,
        max_budget=seed_max_budget,
        enforce_fleet_count=enforce_seed_fleet_count,
    )
    if introduce_ev and carbon_profile is not None and active_limits.ev > 0:
        if active_limits.cv <= 0:
            solution = introduce_ev_heavy_routes(
                solution,
                instance,
                carbon_profile,
                prices,
                fleet_limits=active_limits,
                require_charging_signal=require_charging_signal,
            )
        else:
            solution = introduce_ev_routes(
                solution,
                instance,
                carbon_profile,
                prices,
                fleet_limits=active_limits,
                require_charging_signal=require_charging_signal,
            )
    solution = normalize_solution_vehicle_trips(solution, instance, max_cv=active_limits.cv, max_ev=active_limits.ev)
    violations = check_solution(solution, instance, prices)
    if violations:
        details = "; ".join(f"{v.type}:{v.vehicle_id}:{v.location}:{v.detail}" for v in violations[:8])
        raise ValueError(f"Initial solution is infeasible after fleet-trip retagging: {details}")
    return _inherit_dynamic_state(solution)


def _build_cv_seed(
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    max_cv: int,
    enforce_fleet_count: bool = True,
) -> Solution:
    """Build the original deterministic CV-only seed."""

    node_lookup = {node.node_id: node for node in instance.nodes}
    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    customers = [node for node in instance.nodes if node.node_type.lower() == "c"]
    plans: list[_RoutePlan] = []
    assigned: dict[str, list[Node]] = {depot.node_id: [] for depot in depots}
    for customer in customers:
        depot = min(depots, key=lambda item: instance.distance(item.node_id, customer.node_id))
        assigned[depot.node_id].append(customer)

    for depot_id, depot_customers in assigned.items():
        plans.extend(_regret2_pack(depot_id, depot_customers, plans, instance, prices, max_cv))

    routes = [
        Route(f"CV{idx + 1}", "cv", plan.depot_id, [plan.depot_id, *plan.customer_ids, plan.depot_id])
        for idx, plan in enumerate(plans)
    ]
    solution = Solution(routes=routes)
    if enforce_fleet_count:
        solution = normalize_solution_vehicle_trips(solution, instance, max_cv=max_cv, max_ev=0)
    check_instance = instance if enforce_fleet_count else replace(instance, num_cv=None, num_ev=None)
    violations = check_solution(solution, check_instance, prices)
    if violations:
        details = "; ".join(f"{v.type}:{v.vehicle_id}:{v.location}:{v.detail}" for v in violations[:8])
        raise ValueError(f"Initial solution is infeasible: {details}")
    return solution


def _build_cv_seed_with_retry(
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    start_budget: int,
    max_budget: int,
    enforce_fleet_count: bool = True,
) -> Solution:
    """Build the first feasible CV seed within the supplied route budget.

    v2026-06-26: ``max_budget`` is the temporary seed ceiling. With finite
    mixed-fleet caps this can be CV+EV, because route electrification happens
    after the deterministic CV packing. Final fleet-count feasibility is still
    checked on the returned solution. ``enforce_fleet_count=False`` is only
    used for this temporary all-CV packing step before EV conversion.
    """

    last_error: Exception | None = None
    for budget in range(max(1, start_budget), max_budget + 1):
        try:
            return _build_cv_seed(instance, prices, max_cv=budget, enforce_fleet_count=enforce_fleet_count)
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"Initial solution is infeasible even with {max_budget} routes: {last_error}")


def introduce_ev_routes(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    fleet_limits: FleetLimits | None = None,
    require_charging_signal: bool = True,
) -> Solution:
    """Move one CV-served customer to an EV route with charging repair.

    v2026-06-11: H2 construction helper for paper_main.tex lines 541, 665,
    and 673. It treats vehicle type as an algorithm dispatch choice inside
    the available fleet: remove one customer from a CV route, create a single
    customer EV route, and call ``repair_route_charging`` to insert any needed
    station visit/actions. The returned ``Solution`` still uses the frozen
    ``Solution``/``ChargingAction`` schema.
    """

    limits = fleet_limits or FleetLimits()
    if _count_routes(solution, "ev") >= limits.ev:
        return solution
    candidates: list[tuple[float, str, str, Solution]] = []
    for customer_id in _customer_ids(solution, instance):
        for depot_id in _depot_ids(instance):
            ev_id = _next_vehicle_id(solution, "EV")
            base_route = Route(ev_id, "ev", depot_id, [depot_id, customer_id, depot_id])
            energy = route_ev_energy_summary(base_route, instance, prices).ev_kwh
            if require_charging_signal and energy <= _price(prices, "B_battery_kwh") + 1e-9:
                continue
            try:
                repaired_route, actions = repair_route_charging(base_route, instance, carbon_profile, prices)
            except ValueError:
                continue
            if require_charging_signal and not actions:
                continue
            candidate = normalize_solution_vehicle_trips(
                _replace_customer_with_ev(solution, customer_id, repaired_route, actions),
                instance,
                max_cv=limits.cv,
                max_ev=limits.ev,
            )
            violations = check_solution(candidate, instance, prices)
            if violations:
                continue
            candidates.append((energy, customer_id, depot_id, candidate))
    if not candidates:
        if require_charging_signal:
            raise ValueError("HALT_H2: no feasible EV route with a nonzero charging action")
        return solution
    # v2026-06-11: deterministic witness prefers the smallest route that truly
    # needs charging; verify_20251113 resolves to D0->C3->F2->D0.
    _, _, _, best_solution = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    return best_solution


def introduce_ev_heavy_routes(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    fleet_limits: FleetLimits,
    require_charging_signal: bool = True,
) -> Solution:
    """Electrify a seed solution until the EV-heavy fleet counts are met.

    v2026-06-12: M0/M1 high-electrification E5 variant for paper_main.tex
    lines 665-673. This is a search-shell construction step, not a model
    change: it first moves high-energy single customers to repaired EV routes
    with real ``ChargingAction`` objects, then converts whole CV routes to EV
    while checking the frozen ``check_solution`` constraints.
    """

    current = solution
    if _count_routes(current, "ev") >= fleet_limits.ev:
        return current

    guard = 0
    while _count_routes(current, "cv") > fleet_limits.cv:
        guard += 1
        if guard > 100:
            raise ValueError("HALT_M0: EV-heavy construction loop exceeded guard limit")
        if _count_routes(current, "ev") >= fleet_limits.ev:
            break
        candidate = _best_route_electrification(current, instance, carbon_profile, prices)
        if candidate is None:
            candidate = _best_route_split_electrification(
                current,
                instance,
                carbon_profile,
                prices,
                max_new_ev=fleet_limits.ev - _count_routes(current, "ev"),
            )
            if candidate is None:
                break
        current = normalize_solution_vehicle_trips(candidate, instance, max_cv=fleet_limits.cv, max_ev=fleet_limits.ev)

    # v2026-06-12: Q2 makes depot precharge a real charging signal, so reduce
    # CV count by route electrification before spending remaining EV slots on
    # single-customer charge-bearing witnesses.
    while _count_routes(current, "ev") < fleet_limits.ev:
        candidate = _best_charged_customer_electrification(current, instance, carbon_profile, prices)
        if candidate is None:
            break
        current = normalize_solution_vehicle_trips(candidate, instance, max_cv=fleet_limits.cv, max_ev=fleet_limits.ev)

    cv_count = _count_routes(current, "cv")
    ev_count = _count_routes(current, "ev")
    charge_kwh = sum(float(action.energy_kwh) for action in current.charging_actions)
    if cv_count > fleet_limits.cv or ev_count > fleet_limits.ev:
        raise ValueError(
            "HALT_M0: unable to satisfy EV-heavy fleet limits "
            f"(cv={cv_count}/{fleet_limits.cv}, ev={ev_count}/{fleet_limits.ev})"
        )
    if require_charging_signal and charge_kwh <= 1e-9:
        raise ValueError("HALT_H3: EV-heavy seed has no nonzero charging signal")
    return current


def _best_charged_customer_electrification(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> Solution | None:
    candidates: list[tuple[float, float, str, str, Solution]] = []
    used_stations = _used_station_ids(solution)
    for customer_id in _customer_ids(solution, instance):
        for depot_id in _depot_ids(instance):
            ev_id = _next_vehicle_id(solution, "EV")
            route = Route(ev_id, "ev", depot_id, [depot_id, customer_id, depot_id])
            energy = route_ev_energy_summary(route, instance, prices).ev_kwh
            try:
                repaired_route, actions = repair_route_charging(route, instance, carbon_profile, prices)
            except ValueError:
                continue
            if not actions or _actions_touch_used_station(actions, used_stations):
                continue
            candidate = normalize_solution_vehicle_trips(
                _replace_customer_with_ev(solution, customer_id, repaired_route, actions),
                instance,
                max_cv=UNBOUNDED_FLEET,
                max_ev=UNBOUNDED_FLEET,
            )
            if check_solution(candidate, instance, prices):
                continue
            charge_energy = sum(float(action.energy_kwh) for action in actions)
            candidates.append((-charge_energy, -energy, customer_id, depot_id, candidate))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1], item[2], item[3]))[4]


def _best_route_electrification(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> Solution | None:
    candidates: list[tuple[int, float, str, Solution]] = []
    used_stations = _used_station_ids(solution)
    for route in solution.routes:
        if route.vehicle_type.lower() != "cv" or not _route_customer_ids(route, instance):
            continue
        ev_id = _next_vehicle_id(solution, "EV")
        ev_route = replace(route, vehicle_id=ev_id, vehicle_type="ev")
        try:
            repaired_route, actions = repair_route_charging(ev_route, instance, carbon_profile, prices)
        except ValueError:
            continue
        if _actions_touch_used_station(actions, used_stations):
            continue
        routes = [repaired_route if item.vehicle_id == route.vehicle_id else item for item in solution.routes]
        preserved_actions = [
            action
            for action in solution.charging_actions
            if action.vehicle_id != route.vehicle_id and action.vehicle_id != ev_id
        ]
        candidate = normalize_solution_vehicle_trips(
            replace(solution, routes=routes, charging_actions=[*preserved_actions, *actions]),
            instance,
            max_cv=UNBOUNDED_FLEET,
            max_ev=UNBOUNDED_FLEET,
        )
        if check_solution(candidate, instance, prices):
            continue
        energy = route_ev_energy_summary(ev_route, instance, prices).ev_kwh
        candidates.append((len(actions), energy, route.vehicle_id, candidate))
    if not candidates:
        return None
    # v2026-06-12: prefer no-new-station conversions first because station
    # uniqueness is a frozen hard constraint and charge-bearing witnesses were
    # already selected above.
    return min(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def _best_route_split_electrification(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    max_new_ev: int,
) -> Solution | None:
    """Replace one CV route by single-customer EV routes when direct conversion fails."""

    if max_new_ev <= 0:
        return None
    candidates: list[tuple[int, float, str, Solution]] = []
    for route in solution.routes:
        if route.vehicle_type.lower() != "cv":
            continue
        customer_ids = _route_customer_ids(route, instance)
        if not customer_ids or len(customer_ids) > max_new_ev:
            continue
        used_stations = _used_station_ids(solution)
        used_vehicle_ids = {item.vehicle_id for item in solution.routes}
        new_routes: list[Route] = []
        new_actions: list[ChargingAction] = []
        feasible = True
        for customer_id in customer_ids:
            ev_id = _next_vehicle_id_from_used(used_vehicle_ids, "EV")
            used_vehicle_ids.add(ev_id)
            ev_route = Route(ev_id, "ev", route.home_depot_id, [route.home_depot_id, customer_id, route.home_depot_id])
            try:
                repaired_route, actions = repair_route_charging(ev_route, instance, carbon_profile, prices)
            except ValueError:
                feasible = False
                break
            if _actions_touch_used_station(actions, used_stations):
                feasible = False
                break
            used_stations.update(node_id for node_id in repaired_route.node_sequence if node_id.startswith("F"))
            new_routes.append(repaired_route)
            new_actions.extend(actions)
        if not feasible:
            continue
        routes = [item for item in solution.routes if item.vehicle_id != route.vehicle_id]
        preserved_actions = [action for action in solution.charging_actions if action.vehicle_id != route.vehicle_id]
        candidate = normalize_solution_vehicle_trips(
            replace(solution, routes=[*routes, *new_routes], charging_actions=[*preserved_actions, *new_actions]),
            instance,
            max_cv=UNBOUNDED_FLEET,
            max_ev=UNBOUNDED_FLEET,
        )
        if check_solution(candidate, instance, prices):
            continue
        charge_energy = sum(float(action.energy_kwh) for action in new_actions)
        candidates.append((len(customer_ids), -charge_energy, route.vehicle_id, candidate))
    if not candidates:
        return None
    # v2026-06-12: use the smallest split that reduces CV count, then prefer
    # the split with stronger real charging stake.
    return min(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def _inherit_dynamic_state(solution: Solution) -> Solution:
    # v2026-06-11: static gate placeholder for later rolling-state inheritance.
    return solution


def _regret2_pack(
    depot_id: str,
    customers: list[Node],
    existing_plans: list[_RoutePlan],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    max_cv: int,
) -> list[_RoutePlan]:
    unassigned = sorted(customers, key=lambda node: (float(node.ready_time), float(node.due_time), node.node_id))
    plans: list[_RoutePlan] = []
    while unassigned:
        scored: list[tuple[float, float, str, int | None, int, Node]] = []
        for customer in unassigned:
            options = _insertion_options(depot_id, plans, existing_plans, customer, instance, prices, max_cv)
            if not options:
                raise ValueError(f"No feasible insertion for customer {customer.node_id}")
            best = options[0]
            second_cost = options[1][0] if len(options) > 1 else best[0]
            regret = second_cost - best[0]
            scored.append((-regret, best[0], customer.node_id, best[1], best[2], customer))
        _, _, _, plan_idx, insert_pos, customer = min(scored)
        if plan_idx is None:
            plans.append(_RoutePlan(depot_id, [customer.node_id]))
        else:
            plans[plan_idx].customer_ids.insert(insert_pos, customer.node_id)
        unassigned.remove(customer)
    return plans


def _insertion_options(
    depot_id: str,
    plans: list[_RoutePlan],
    existing_plans: list[_RoutePlan],
    customer: Node,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    max_cv: int,
) -> list[tuple[float, int | None, int]]:
    options: list[tuple[float, int | None, int]] = []
    for plan_idx, plan in enumerate(plans):
        for insert_pos in range(len(plan.customer_ids) + 1):
            candidate = list(plan.customer_ids)
            candidate.insert(insert_pos, customer.node_id)
            if _route_plan_feasible(depot_id, candidate, instance, prices):
                delta = _route_distance(depot_id, candidate, instance) - _route_distance(depot_id, plan.customer_ids, instance)
                options.append((delta, plan_idx, insert_pos))
    if len(existing_plans) + len(plans) < max_cv and _route_plan_feasible(depot_id, [customer.node_id], instance, prices):
        options.append((_route_distance(depot_id, [customer.node_id], instance), None, 0))
    return sorted(options, key=lambda item: (item[0], 9999 if item[1] is None else item[1], item[2]))


def _route_plan_feasible(
    depot_id: str,
    customer_ids: list[str],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> bool:
    node_lookup = {node.node_id: node for node in instance.nodes}
    if sum(float(node_lookup[node_id].demand) for node_id in customer_ids) > _price(prices, "Q_capacity") + 1e-9:
        return False
    route = Route("CV_TMP", "cv", depot_id, [depot_id, *customer_ids, depot_id])
    for row in route_node_schedule(route, instance, prices):
        if row.t_start > float(node_lookup[row.node_id].due_time) + 1e-9:
            return False
    return True


def _seed_route_budget(instance: Instance, prices: PriceParameters | dict[str, float] | Any, *, max_cv: int) -> int:
    total_demand = sum(float(node.demand) for node in instance.nodes if node.node_type.lower() == "c")
    demand_bound = int((total_demand + _price(prices, "Q_capacity") - 1e-9) // _price(prices, "Q_capacity"))
    if total_demand > demand_bound * _price(prices, "Q_capacity") + 1e-9:
        demand_bound += 1
    if max_cv >= UNBOUNDED_FLEET:
        return max(1, demand_bound)
    return max(1, min(max_cv, _customer_count(instance)))


def _seed_route_limit(limits: FleetLimits, *, introduce_ev: bool) -> int:
    if not introduce_ev or limits.ev <= 0:
        return limits.cv
    if limits.cv >= UNBOUNDED_FLEET or limits.ev >= UNBOUNDED_FLEET:
        return UNBOUNDED_FLEET
    return max(1, int(limits.cv) + int(limits.ev))


def _customer_count(instance: Instance) -> int:
    return sum(1 for node in instance.nodes if node.node_type.lower() == "c")


def _route_distance(depot_id: str, customer_ids: list[str], instance: Instance) -> float:
    seq = [depot_id, *customer_ids, depot_id]
    return sum(instance.distance(a, b) for a, b in zip(seq, seq[1:]))


def _replace_customer_with_ev(
    solution: Solution,
    customer_id: str,
    ev_route: Route,
    actions: list,
) -> Solution:
    routes: list[Route] = []
    removed = False
    for route in solution.routes:
        if customer_id not in route.node_sequence:
            routes.append(route)
            continue
        seq = [node_id for node_id in route.node_sequence if node_id != customer_id]
        removed = True
        if _route_has_customer(seq):
            routes.append(replace(route, node_sequence=seq))
    if not removed:
        return solution
    filtered_actions = [action for action in solution.charging_actions if action.vehicle_id != ev_route.vehicle_id]
    return replace(solution, routes=[*routes, ev_route], charging_actions=[*filtered_actions, *actions])


def _route_has_customer(node_sequence: list[str]) -> bool:
    return len(node_sequence) > 2


def _customer_ids(solution: Solution, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    ids = []
    for route in solution.routes:
        if route.vehicle_type.lower() != "cv":
            continue
        for node_id in route.node_sequence:
            node = node_lookup.get(node_id)
            if node is not None and node.node_type.lower() == "c":
                ids.append(node_id)
    return sorted(dict.fromkeys(ids), key=_natural_id_key)


def _route_customer_ids(route: Route, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    ]


def _used_station_ids(solution: Solution) -> set[str]:
    return {
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id.startswith("F")
    }


def _actions_touch_used_station(actions: list[ChargingAction], used_stations: set[str]) -> bool:
    return any(action.station_id in used_stations for action in actions)


def _depot_ids(instance: Instance) -> list[str]:
    return sorted((node.node_id for node in instance.nodes if node.node_type.lower() == "d"), key=_natural_id_key)


def _count_routes(solution: Solution, vehicle_type: str) -> int:
    return sum(1 for route in solution.routes if route.vehicle_type.lower() == vehicle_type.lower())


def _next_vehicle_id(solution: Solution, prefix: str) -> str:
    used = {route.vehicle_id for route in solution.routes}
    return _next_vehicle_id_from_used(used, prefix)


def _next_vehicle_id_from_used(used: set[str], prefix: str) -> str:
    idx = 1
    while f"{prefix}{idx}" in used:
        idx += 1
    return f"{prefix}{idx}"


def _natural_id_key(value: str) -> tuple[str, int]:
    prefix = "".join(ch for ch in value if not ch.isdigit())
    digits = "".join(ch for ch in value if ch.isdigit())
    return prefix, int(digits or "0")


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
