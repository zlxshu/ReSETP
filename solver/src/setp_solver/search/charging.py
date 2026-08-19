"""Shared EV charging repair for search states.

v2026-06-11: Provides the algorithm-side repair hook for paper_main.tex
lines 428-457. Given a route and carbon profile, it inserts station visits
when needed and constructs ``ChargingAction`` values using the existing
Solution/ChargingAction schema. Use ``repair_route_charging`` when route
nodes may need stations; fixed-route controls use ``solve_charging_fixed_route``.
"""

from __future__ import annotations

from dataclasses import replace
import math
from collections.abc import Mapping
from typing import Any

from ..charging_action import _curve_aware_action
from ..charge_timing import (
    DEFAULT_CHARGE_TIMING_POLICY,
    select_charge_timing_start,
    validate_charge_timing_policy,
)
from ..cost import (
    CARBON_SLOT_SECONDS,
    best_charging_action_start,
    charging_action_emissions_kg,
    ev_instance_arc_energy_kwh,
    route_next_day_departure_second,
    route_return_arrival_without_charging,
    time_profile_rows_for_node,
)
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution
from .multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    certified_depot_charge_window,
    route_timing,
    select_certified_depot_charge_start,
    validate_depot_charge_window_mode,
)


def solve_charging_naive(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    depot_charge_window_mode: str = "full_gap",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
) -> list[ChargingAction]:
    """Return fixed-route actions using immediate return/arrival charging."""

    # v2026-06-12: S0 charging-policy ablation baseline. This keeps the same
    # power and energy construction as carbon-aware replay, but depot charging
    # starts immediately at route return instead of minimizing carbon.
    return solve_charging_fixed_route(
        route,
        instance,
        gamma_profile,
        prices,
        strategy="naive",
        depot_charge_window_mode=depot_charge_window_mode,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
    )


def solve_charging_fixed_route(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    strategy: str = "aware",
    depot_charge_window_mode: str = "full_gap",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
) -> list[ChargingAction]:
    """Construct charging actions for an existing route without changing nodes."""

    if route.vehicle_type.lower() != "ev":
        return []
    node_lookup = {node.node_id: node for node in instance.nodes}
    if not route.node_sequence:
        return []

    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    battery = _price(prices, "initial_ev_battery_kwh")
    validate_depot_charge_window_mode(depot_charge_window_mode)
    time_s = float(node_lookup[route.node_sequence[0]].ready_time)
    remaining_customers = [node_id for node_id in route.node_sequence if node_lookup[node_id].node_type.lower() == "c"]
    actions: list[ChargingAction] = []

    for idx, node_id in enumerate(route.node_sequence[:-1]):
        node = node_lookup[node_id]
        node_type = node.node_type.lower()
        if node_type in {"d", "f"}:
            segment_need = _energy_to_next_chargeable(idx, route.node_sequence, node_lookup, instance, prices, remaining_customers)
            if segment_need > battery_cap + 1e-9:
                raise ValueError(f"Fixed route segment from {node_id} requires {segment_need:.6f} kWh > B={battery_cap:.6f}")
            energy_needed = max(0.0, segment_need - battery)
            if energy_needed > 1e-9:
                power_kw = _charge_power_kw(node, prices)
                action = _curve_aware_action(
                    vehicle_id=route.vehicle_id,
                    station_id=node_id,
                    start_energy_kwh=battery,
                    energy_kwh=energy_needed,
                    reference_power_kw=power_kw,
                    prices=prices,
                    instance=instance,
                )
                occupancy_sec = float(action.occupancy_minutes) * 60.0
                node_profile = time_profile_rows_for_node(
                    instance,
                    node_id,
                    gamma_profile,
                )
                earliest, latest = _fixed_charge_window(
                    idx,
                    route,
                    node_lookup,
                    instance,
                    prices,
                    occupancy_sec,
                    time_s,
                    len(node_profile),
                    depot_charge_window_mode=depot_charge_window_mode,
                    charging_actions=actions,
                )
                if latest + 1e-9 < earliest:
                    raise ValueError(f"No feasible fixed-route charging window for {route.vehicle_id} at {node_id}")
                if node_type == "d" and depot_charge_window_mode == "full_gap" and carbon_profiles_by_day_offset is None:
                    charge_start = _select_charge_start(
                        earliest,
                        latest,
                        node_profile,
                        strategy,
                        node_type=node_type,
                    )
                    charge_day_offset = 0
                elif node_type == "d":
                    charge_start, charge_day_offset = select_certified_depot_charge_start(
                        action,
                        earliest,
                        latest,
                        instance,
                        prices,
                        gamma_profile,
                        mode=depot_charge_window_mode,
                        strategy="integrated" if strategy == "aware" else "naive",
                        charge_timing_policy=(
                            "carbon_min" if strategy == "aware" else "asap"
                        ),
                        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
                    )
                else:
                    charge_start = (
                        best_charging_action_start(
                            action,
                            earliest_start_second=earliest,
                            latest_start_second=latest,
                            instance=instance,
                            carbon_profile=gamma_profile,
                            prices=prices,
                        )
                        if strategy == "aware"
                        else _select_charge_start(
                            earliest,
                            latest,
                            node_profile,
                            strategy,
                            node_type=node_type,
                        )
                    )
                    charge_day_offset = 0
                actions.append(
                    replace(
                        action,
                        charge_start_second=charge_start,
                        charge_day_offset=charge_day_offset,
                    )
                )
                battery += energy_needed
                if node_type != "d":
                    time_s = max(time_s, charge_start + occupancy_sec)

        next_id = route.node_sequence[idx + 1]
        load_kg = sum(float(node_lookup[customer_id].demand) for customer_id in remaining_customers)
        battery -= ev_instance_arc_energy_kwh(
            instance,
            node_id,
            next_id,
            load_kg,
            prices,
        )
        if battery < -1e-7:
            raise ValueError(f"Fixed route battery below zero after {node_id}->{next_id}: {battery:.6f} kWh")
        _, travel, _ = instance.arc_metrics(
            node_id,
            next_id,
            "ev",
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        next_node = node_lookup[next_id]
        time_s = max(time_s + travel, float(next_node.ready_time)) + float(next_node.service_time)
        if next_node.node_type.lower() == "c":
            remaining_customers.remove(next_id)

    return actions


def replay_fixed_route_charging(
    solution: Solution,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    strategy: str = "aware",
    depot_charge_window_mode: str = "full_gap",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
) -> Solution:
    """Strip charging actions and replay charging on unchanged route sequences."""

    actions: list[ChargingAction] = []
    for route in solution.routes:
        actions.extend(
            solve_charging_fixed_route(
                route,
                instance,
                gamma_profile,
                prices,
                strategy=strategy,
                depot_charge_window_mode=depot_charge_window_mode,
                carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
            )
        )
    return replace(solution, charging_actions=actions)


def repair_route_charging(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    depot_charge_window_mode: str = "full_gap",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
) -> tuple[Route, list[ChargingAction]]:
    """Insert station visits and actions sufficient for battery feasibility."""

    if route.vehicle_type.lower() != "ev":
        return route, []
    validate_depot_charge_window_mode(depot_charge_window_mode)
    validate_charge_timing_policy(charge_timing_policy)
    node_lookup = {node.node_id: node for node in instance.nodes}
    stations = [node for node in instance.nodes if node.node_type.lower() == "f"]

    original_targets = [node_id for node_id in route.node_sequence[1:] if node_lookup[node_id].node_type.lower() != "f"]
    repaired = [route.node_sequence[0]]
    actions: list[ChargingAction] = []
    # v2026-06-12: Q2 starts EV routes from bbar and makes depot precharge a
    # first-class decision before preserving the existing en-route station logic.
    battery = _price(prices, "initial_ev_battery_kwh")
    time_s = route_timing(
        route,
        instance,
        prices,
        charging_actions=[],
        validate_battery=False,
    ).earliest_departure_second
    remaining_customers = [node_id for node_id in original_targets if node_lookup[node_id].node_type.lower() == "c"]
    depot_action = _depot_precharge_action(
        route,
        original_targets,
        node_lookup,
        instance,
        gamma_profile,
        prices,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
    )
    if depot_action is not None:
        actions.append(depot_action)
        battery += float(depot_action.energy_kwh)
        # v2026-06-12: S0 depot action is the previous-return/next-departure
        # overnight charge that supplies departure battery; it must not delay
        # the current-day route clock used for station repair.

    current = route.node_sequence[0]
    for target_idx, target in enumerate(original_targets):
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in remaining_customers)
        needed_direct = ev_instance_arc_energy_kwh(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        future_targets = original_targets[target_idx:]
        failure_offset = _first_direct_infeasible_offset(
            current,
            future_targets,
            battery,
            node_lookup,
            instance,
            prices,
            remaining_customers,
        )
        should_insert = failure_offset is not None
        if should_insert:
            coverage_targets = future_targets[: int(failure_offset) + 1] if failure_offset is not None else [target]
            available_stations = [station for station in stations if station.node_id not in repaired]
            if not available_stations and battery + 1e-9 < needed_direct:
                raise ValueError("No charging stations available for EV charging repair")
            candidate = _best_station_insert(
                current,
                target,
                coverage_targets,
                remaining_customers,
                load_kg,
                battery,
                time_s,
                available_stations,
                node_lookup,
                instance,
                gamma_profile,
                prices,
                route.vehicle_id,
                charge_timing_policy=charge_timing_policy,
            )
            if candidate is None:
                if battery + 1e-9 < needed_direct:
                    raise ValueError(f"No feasible charging insert between {current} and {target}")
            else:
                station_id, action, _arrive_station, depart_station, battery_after_charge = candidate
                repaired.append(station_id)
                actions.append(action)
                battery = battery_after_charge
                time_s = depart_station
                current = station_id

        _, travel, _ = instance.arc_metrics(
            current,
            target,
            "ev",
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        battery -= ev_instance_arc_energy_kwh(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        time_s = max(time_s + travel, float(node_lookup[target].ready_time)) + float(node_lookup[target].service_time)
        repaired.append(target)
        if node_lookup[target].node_type.lower() == "c":
            remaining_customers.remove(target)
        current = target

    repaired_route = replace(route, node_sequence=repaired)
    actions = _reanchor_depot_actions(
        repaired_route,
        actions,
        instance,
        gamma_profile,
        prices,
        depot_charge_window_mode=depot_charge_window_mode,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        strategy="integrated",
        charge_timing_policy=charge_timing_policy,
    )
    return repaired_route, actions


def _energy_to_next_chargeable(
    start_idx: int,
    node_sequence: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    remaining_customers: list[str],
) -> float:
    total = 0.0
    local_remaining = list(remaining_customers)
    for idx in range(start_idx, len(node_sequence) - 1):
        from_node_id = node_sequence[idx]
        to_node_id = node_sequence[idx + 1]
        load_kg = sum(float(node_lookup[customer_id].demand) for customer_id in local_remaining)
        total += ev_instance_arc_energy_kwh(
            instance,
            from_node_id,
            to_node_id,
            load_kg,
            prices,
        )
        to_node = node_lookup[to_node_id]
        if to_node.node_type.lower() == "c":
            local_remaining.remove(to_node_id)
        elif idx + 1 > start_idx and to_node.node_type.lower() in {"d", "f"}:
            break
    return total


def _first_direct_infeasible_offset(
    current: str,
    future_targets: list[str],
    battery: float,
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    remaining_customers: list[str],
) -> int | None:
    """Return the target offset where direct travel first depletes EV battery."""

    local_current = current
    local_battery = float(battery)
    local_remaining = list(remaining_customers)
    for offset, target in enumerate(future_targets):
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in local_remaining)
        local_battery -= ev_instance_arc_energy_kwh(
            instance,
            local_current,
            target,
            load_kg,
            prices,
        )
        if local_battery < -1e-9:
            return offset
        if node_lookup[target].node_type.lower() == "c" and target in local_remaining:
            local_remaining.remove(target)
        if node_lookup[target].node_type.lower() in {"d", "f"}:
            return None
        local_current = target
    return None


def _charge_power_kw(node: Node, prices: PriceParameters | dict[str, float] | Any) -> float:
    node_type = node.node_type.lower()
    if node_type == "d":
        power = _price(prices, "depot_charge_power_kw")
    else:
        power = float(node.charge_power_kw) if node.charge_power_kw is not None else 0.0
    if power <= 1e-9:
        raise ValueError(f"Charging power is missing or nonpositive at {node.node_id}")
    return power


def _fixed_charge_earliest(node: Node, node_type: str, arrival_second: float) -> float:
    if node_type == "d":
        return float(node.ready_time)
    return max(float(arrival_second), float(node.ready_time))


def _fixed_charge_window(
    idx: int,
    route: Route,
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    occupancy_sec: float,
    arrival_second: float,
    n_slots: int,
    *,
    depot_charge_window_mode: str,
    charging_actions: list[ChargingAction],
) -> tuple[float, float]:
    node_id = route.node_sequence[idx]
    node = node_lookup[node_id]
    if node.node_type.lower() == "d":
        if depot_charge_window_mode == "full_gap":
            period = float(n_slots) * CARBON_SLOT_SECONDS
            return (
                route_return_arrival_without_charging(route, instance, prices),
                route_next_day_departure_second(
                    route,
                    instance,
                    prices,
                    period_seconds=period,
                )
                - occupancy_sec,
            )
        earliest, latest, _ = certified_depot_charge_window(
            route,
            instance,
            prices,
            occupancy_seconds=occupancy_sec,
            mode=depot_charge_window_mode,
            charging_actions=charging_actions,
        )
        return earliest, latest
    return _fixed_charge_earliest(node, node.node_type.lower(), arrival_second), _fixed_charge_latest(
        idx,
        route.node_sequence,
        node_lookup,
        instance,
        prices,
        occupancy_sec,
    )


def _fixed_charge_latest(
    idx: int,
    node_sequence: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    occupancy_sec: float,
) -> float:
    node_id = node_sequence[idx]
    node = node_lookup[node_id]
    latest = float(node.due_time)
    if node.node_type.lower() == "d":
        latest -= occupancy_sec
    if idx + 1 < len(node_sequence):
        # A charging delay propagates through the entire remaining route, not
        # only to the immediate successor.  Work backwards from every
        # downstream due time so a green slot cannot make a later customer
        # infeasible while the next customer still looks feasible.
        speed = _price(prices, "v_speed_ms")
        successor_id = node_sequence[-1]
        latest_successor_start = float(node_lookup[successor_id].due_time)
        for pos in range(len(node_sequence) - 2, idx, -1):
            current_id = node_sequence[pos]
            current = node_lookup[current_id]
            _, travel_to_successor, _ = instance.arc_metrics(
                current_id,
                successor_id,
                "ev",
                fallback_speed_mps=speed,
            )
            latest_successor_start = min(
                float(current.due_time),
                latest_successor_start - float(current.service_time) - travel_to_successor,
            )
            successor_id = current_id
        _, travel_to_successor, _ = instance.arc_metrics(
            node_id,
            successor_id,
            "ev",
            fallback_speed_mps=speed,
        )
        latest = min(
            latest,
            latest_successor_start - occupancy_sec - travel_to_successor,
        )
    return latest


def _select_charge_start(
    earliest: float,
    latest: float,
    gamma_profile: list[dict[str, Any]],
    strategy: str,
    *,
    node_type: str,
) -> float:
    if strategy == "aware":
        start, _ = _lowest_gamma_slot_start(earliest, latest, gamma_profile)
        return start
    if strategy == "naive":
        if node_type == "d":
            # v2026-06-12: S0 naive baseline is realistic return-to-depot
            # immediate plug-in, not earliest half-hour boundary optimization.
            return float(earliest)
        return _earliest_slot_start(earliest, latest)
    raise ValueError(f"Unsupported charging strategy: {strategy}")


def _earliest_slot_start(earliest: float, latest: float) -> float:
    slot = math.ceil(float(earliest) / CARBON_SLOT_SECONDS) * CARBON_SLOT_SECONDS
    if slot <= latest + 1e-9:
        return float(slot)
    return float(earliest)


def _depot_precharge_action(
    route: Route,
    original_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    depot_charge_window_mode: str,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None,
) -> ChargingAction | None:
    depot_id = route.node_sequence[0]
    depot = node_lookup[depot_id]
    if depot.node_type.lower() != "d":
        return None
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    initial_battery = _price(prices, "initial_ev_battery_kwh")
    route_need = _direct_route_energy_need(depot_id, original_targets, node_lookup, instance, prices)
    energy_needed = min(max(0.0, battery_cap - initial_battery), max(0.0, route_need - initial_battery))
    if energy_needed <= 1e-9:
        return None
    power_kw = _price(prices, "depot_charge_power_kw")
    if power_kw <= 1e-9:
        raise ValueError("Depot charge power pi_d must be positive")
    action = _curve_aware_action(
        vehicle_id=route.vehicle_id,
        station_id=depot_id,
        start_energy_kwh=initial_battery,
        energy_kwh=energy_needed,
        reference_power_kw=power_kw,
        prices=prices,
        instance=instance,
    )
    occupancy_sec = float(action.occupancy_minutes) * 60.0
    synthetic_route = Route(route.vehicle_id, route.vehicle_type, route.home_depot_id, [route.node_sequence[0], *original_targets])
    earliest, latest, _ = certified_depot_charge_window(
        synthetic_route,
        instance,
        prices,
        occupancy_seconds=occupancy_sec,
        mode=depot_charge_window_mode,
        charging_actions=[],
    )
    charge_start, charge_day_offset = select_certified_depot_charge_start(
        action,
        earliest,
        latest,
        instance=instance,
        prices=prices,
        base_profile=gamma_profile,
        mode=depot_charge_window_mode,
        strategy="integrated",
        charge_timing_policy=charge_timing_policy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
    )
    return replace(
        action,
        charge_start_second=charge_start,
        charge_day_offset=charge_day_offset,
    )


def _reanchor_depot_actions(
    route: Route,
    actions: list[ChargingAction],
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    depot_charge_window_mode: str,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None,
    strategy: str,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
) -> list[ChargingAction]:
    """Recompute depot charging against the final certificate route clock."""

    depot_indices = [
        index
        for index, action in enumerate(actions)
        if action.vehicle_id == route.vehicle_id
        and action.station_id == route.home_depot_id
    ]
    if not depot_indices:
        return actions
    if len(depot_indices) != 1:
        raise ValueError(
            f"expected one depot charging action for {route.vehicle_id}, "
            f"found {len(depot_indices)}"
        )
    index = depot_indices[0]
    action = actions[index]
    earliest, latest, _ = certified_depot_charge_window(
        route,
        instance,
        prices,
        occupancy_seconds=float(action.occupancy_minutes) * 60.0,
        mode=depot_charge_window_mode,
        charging_actions=actions,
    )
    start, offset = select_certified_depot_charge_start(
        action,
        earliest,
        latest,
        instance,
        prices,
        gamma_profile,
        mode=depot_charge_window_mode,
        strategy=strategy,
        charge_timing_policy=charge_timing_policy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
    )
    updated = list(actions)
    updated[index] = replace(
        action,
        charge_start_second=start,
        charge_day_offset=offset,
    )
    return updated


def _direct_route_energy_need(
    depot_id: str,
    original_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    remaining_customers: list[str] | None = None,
) -> float:
    total = 0.0
    current = depot_id
    local_remaining = (
        [node_id for node_id in original_targets if node_lookup[node_id].node_type.lower() == "c"]
        if remaining_customers is None
        else list(remaining_customers)
    )
    for target in original_targets:
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in local_remaining)
        total += ev_instance_arc_energy_kwh(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        if node_lookup[target].node_type.lower() == "c" and target in local_remaining:
            local_remaining.remove(target)
        current = target
    return total


def _route_travel_lower_bound(
    depot_id: str,
    original_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    stations = [node for node in node_lookup.values() if node.node_type.lower() == "f"]
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    battery = min(battery_cap, _price(prices, "initial_ev_battery_kwh") + battery_cap)
    total = 0.0
    current = depot_id
    remaining_customers = [node_id for node_id in original_targets if node_lookup[node_id].node_type.lower() == "c"]
    for target in original_targets:
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in remaining_customers)
        direct_distance, direct_time, _ = instance.arc_metrics(
            current,
            target,
            "ev",
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        direct_energy = ev_instance_arc_energy_kwh(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        if direct_energy <= battery + 1e-9:
            best_time = direct_time
            battery -= direct_energy
        else:
            best_candidate: tuple[float, float] | None = None
            for station in stations:
                _, time_to_station, _ = instance.arc_metrics(
                    current,
                    station.node_id,
                    "ev",
                    fallback_speed_mps=_price(prices, "v_speed_ms"),
                )
                energy_to_station = ev_instance_arc_energy_kwh(
                    instance,
                    current,
                    station.node_id,
                    load_kg,
                    prices,
                )
                if energy_to_station > battery + 1e-9:
                    continue
                _, time_to_target, _ = instance.arc_metrics(
                    station.node_id,
                    target,
                    "ev",
                    fallback_speed_mps=_price(prices, "v_speed_ms"),
                )
                energy_station_to_target = ev_instance_arc_energy_kwh(
                    instance,
                    station.node_id,
                    target,
                    load_kg,
                    prices,
                )
                if energy_station_to_target > battery_cap + 1e-9:
                    continue
                travel_time = time_to_station + time_to_target
                battery_after_target = battery_cap - energy_station_to_target
                candidate = (travel_time, battery_after_target)
                if best_candidate is None or candidate[0] < best_candidate[0]:
                    best_candidate = candidate
            if best_candidate is None:
                best_time = direct_time
                battery = max(0.0, battery - direct_energy)
            else:
                best_time, battery = best_candidate
        total += best_time
        total += float(node_lookup[target].service_time)
        if node_lookup[target].node_type.lower() == "c":
            remaining_customers.remove(target)
        current = target
    return total


def _best_station_insert(
    current: str,
    target: str,
    coverage_targets: list[str],
    remaining_customers: list[str],
    load_kg: float,
    battery: float,
    depart_current: float,
    stations: list[Node],
    node_lookup: dict[str, Node],
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    vehicle_id: str,
    *,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
) -> tuple[str, ChargingAction, float, float, float] | None:
    best: tuple[float, float, str, ChargingAction, float, float, float] | None = None
    for station in stations:
        to_station, time_to_station, _ = instance.arc_metrics(
            current,
            station.node_id,
            "ev",
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        energy_to_station = ev_instance_arc_energy_kwh(
            instance,
            current,
            station.node_id,
            load_kg,
            prices,
        )
        if battery + 1e-9 < energy_to_station:
            continue
        battery_at_station = battery - energy_to_station
        station_to_target, time_to_target, _ = instance.arc_metrics(
            station.node_id,
            target,
            "ev",
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        energy_to_target = ev_instance_arc_energy_kwh(
            instance,
            station.node_id,
            target,
            load_kg,
            prices,
        )
        battery_cap = instance.battery_capacity_kwh(
            fallback=_price(prices, "B_battery_kwh"),
        )
        if energy_to_target > battery_cap + 1e-9:
            continue
        segment_need_from_station = _direct_route_energy_need(
            station.node_id,
            coverage_targets,
            node_lookup,
            instance,
            prices,
            remaining_customers=remaining_customers,
        )
        if segment_need_from_station > battery_cap + 1e-9:
            continue
        target_charge_level = segment_need_from_station
        energy_needed = max(0.0, target_charge_level - battery_at_station)
        if energy_needed <= 1e-9:
            continue
        if station.charge_power_kw is None:
            continue
        action = _curve_aware_action(
            vehicle_id=vehicle_id,
            station_id=station.node_id,
            start_energy_kwh=battery_at_station,
            energy_kwh=energy_needed,
            reference_power_kw=float(station.charge_power_kw),
            prices=prices,
            instance=instance,
        )
        occupancy_sec = float(action.occupancy_minutes) * 60.0
        arrive = depart_current + time_to_station
        earliest = max(arrive, float(station.ready_time))
        target_node = node_lookup[target]
        latest = min(
            float(station.due_time),
            float(target_node.due_time) - occupancy_sec - time_to_target,
        )
        if latest + 1e-9 < earliest:
            continue
        charge_start = select_charge_timing_start(
            action,
            earliest_start_second=earliest,
            latest_start_second=latest,
            instance=instance,
            carbon_profile=gamma_profile,
            prices=prices,
            charge_timing_policy=charge_timing_policy,
        )
        depart = charge_start + occupancy_sec
        action = replace(action, charge_start_second=charge_start)
        carbon_kg = charging_action_emissions_kg(
            action,
            instance,
            gamma_profile,
            prices,
        )
        direct_distance, _, _ = instance.arc_metrics(
            current,
            target,
            "ev",
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        detour = to_station + station_to_target - direct_distance
        key = (
            carbon_kg,
            detour,
            station.node_id,
            action,
            arrive,
            depart,
            battery_at_station + energy_needed,
        )
        if best is None or (key[0], key[1], key[2]) < (best[0], best[1], best[2]):
            best = key
    if best is None:
        return None
    _, _, station_id, action, arrive, depart, battery_after = best
    return station_id, action, arrive, depart, battery_after


def _lowest_gamma_slot_start(earliest: float, latest: float, gamma_profile: list[dict[str, Any]]) -> tuple[float, float]:
    candidates: list[tuple[float, float]] = []
    period = float(len(gamma_profile)) * CARBON_SLOT_SECONDS
    if period <= 0.0:
        raise ValueError("gamma_profile must be non-empty")
    first_cycle = math.floor(float(earliest) / period) - 1
    last_cycle = math.ceil(float(latest) / period) + 1
    for row in gamma_profile:
        base_start = float(row["horizon_second_start"])
        for cycle in range(first_cycle, last_cycle + 1):
            slot_start = base_start + cycle * period
            if earliest - 1e-9 <= slot_start <= latest + 1e-9:
                candidates.append((float(row["actual_gco2_per_kwh"]), slot_start))
    if not candidates:
        slot = math.ceil(earliest / CARBON_SLOT_SECONDS) * CARBON_SLOT_SECONDS
        start = slot if slot <= latest + 1e-9 else earliest
        wrapped = start % period
        gamma = min(gamma_profile, key=lambda row: abs(float(row["horizon_second_start"]) - wrapped))["actual_gco2_per_kwh"]
        return float(start), float(gamma)
    gamma, start = min(candidates, key=lambda item: (item[0], item[1]))
    return start, gamma


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
