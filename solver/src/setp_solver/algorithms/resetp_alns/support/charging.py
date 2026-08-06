"""Shared EV charging repair for search states.

v2026-06-11: Provides the algorithm-side repair hook for paper_main.tex
lines 428-457. Given a route and carbon profile, it inserts station visits
when needed and constructs ``ChargingAction`` values using the existing
Solution/ChargingAction schema. Use ``repair_route_charging`` when route
nodes may need stations; use ``solve_charging`` when only actions are needed.
"""

from __future__ import annotations

from dataclasses import replace
import math
from collections.abc import Mapping
from typing import Any

from setp_solver.charge_timing import (
    DEFAULT_CHARGE_TIMING_POLICY,
    select_charge_timing_start,
    validate_charge_timing_policy,
)
from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    best_charging_action_start,
    ev_instance_arc_energy_kwh,
    route_next_day_departure_second,
    route_return_arrival_without_charging,
    time_profile_rows_for_node,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.charging_action import _curve_aware_action
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.station_copies import physical_station_id
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeOption,
    select_charge_option,
)
from setp_solver.search.multitrip_schedule import (
    certified_depot_charge_window,
    route_timing,
    select_certified_depot_charge_start,
    validate_depot_charge_window_mode,
)
from setp_solver.search.evaluation import EvaluationContext, record_repair_delta
from setp_solver.algorithms.resetp_alns.operators.repair_scoring import (
    route_model_cost_delta,
)


CHARGE_AMOUNT_STRATEGIES = (
    "just_enough",
    "max_coverage",
    "soc_85",
    "soc_95",
    "full",
)
PUBLIC_STATION_CANDIDATE_MODES = frozenset({"fallback", "parallel"})
DEFAULT_PUBLIC_STATION_CANDIDATE_MODE = "fallback"


def validate_public_station_candidate_mode(mode: str) -> str:
    """Validate the public-station candidate-generation policy."""

    if mode not in PUBLIC_STATION_CANDIDATE_MODES:
        raise ValueError(
            "unknown public station candidate mode: "
            f"{mode!r}; expected one of "
            f"{sorted(PUBLIC_STATION_CANDIDATE_MODES)}"
        )
    return mode


def normalize_charge_amount_strategies(
    strategies: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Return a unique ordered tuple of supported charge targets."""

    normalized = tuple(str(value).strip().lower() for value in strategies)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ValueError("charge amount strategies must be non-empty and unique")
    unknown = set(normalized) - set(CHARGE_AMOUNT_STRATEGIES)
    if unknown:
        raise ValueError(f"unknown charge amount strategies: {sorted(unknown)}")
    return normalized


def charge_amount_target_kwh(
    strategy: str,
    *,
    just_enough_kwh: float,
    max_coverage_kwh: float,
    capacity_kwh: float,
) -> float:
    """Map one shared physical charge target to an end-of-charge energy."""

    name = normalize_charge_amount_strategies((strategy,))[0]
    capacity = float(capacity_kwh)
    just_enough = min(capacity, float(just_enough_kwh))
    if name == "just_enough":
        return just_enough
    if name == "max_coverage":
        return min(capacity, float(max_coverage_kwh))
    if name == "soc_85":
        return max(just_enough, 0.85 * capacity)
    if name == "soc_95":
        return max(just_enough, 0.95 * capacity)
    return capacity


def solve_charging(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    depot_charge_window_mode: str = "full_gap",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
) -> list[ChargingAction]:
    """Return charging actions for a repaired version of ``route``."""

    _, actions = repair_route_charging(
        route,
        instance,
        gamma_profile,
        prices,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
    )
    return actions


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
                if node_type == "d":
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
        battery -= _ev_energy(
            instance,
            node_id,
            next_id,
            load_kg,
            prices,
        )
        if battery < -1e-7:
            raise ValueError(f"Fixed route battery below zero after {node_id}->{next_id}: {battery:.6f} kWh")
        travel = _ev_travel_time(
            instance,
            node_id,
            next_id,
            prices,
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
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    depot_charge_window_mode: str = "full_gap",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    public_station_candidate_mode: str = DEFAULT_PUBLIC_STATION_CANDIDATE_MODE,
) -> tuple[Route, list[ChargingAction]]:
    """Insert station visits and actions sufficient for battery feasibility.

    ``legacy`` preserves the frozen E2 behavior.  ``integrated`` is isolated
    for the item-4 mechanism gate and compares complete charging intervals and
    station detours in common monetary units.
    """

    candidates = repair_route_charging_candidates(
        route,
        instance,
        gamma_profile,
        prices,
        strategy=strategy,
        carbon_weight=carbon_weight,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy=charge_amount_strategy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        public_station_candidate_mode=public_station_candidate_mode,
    )
    if len(candidates) == 1:
        _, repaired, actions = candidates[0]
        return repaired, actions
    context = EvaluationContext(
        instance=instance,
        carbon_profile=gamma_profile,
        prices=prices,
        carbon_weight=carbon_weight,
    )
    scored_candidates = []
    for index, (_, candidate_route, candidate_actions) in enumerate(candidates):
        record_repair_delta(context)
        scored_candidates.append(
            (
                route_model_cost_delta(candidate_route, candidate_actions, context),
                index,
                candidate_route,
                candidate_actions,
            )
        )
    _, _, repaired, actions = min(scored_candidates)
    return repaired, actions


def repair_route_charging_candidates(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    depot_charge_window_mode: str = "full_gap",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    public_station_candidate_mode: str = DEFAULT_PUBLIC_STATION_CANDIDATE_MODE,
) -> list[tuple[str, Route, list[ChargingAction]]]:
    """Build the legacy depot path and, when enabled, a public-only path."""

    validate_public_station_candidate_mode(public_station_candidate_mode)
    fallback_route, fallback_actions = _repair_route_charging_candidate(
        route,
        instance,
        gamma_profile,
        prices,
        strategy=strategy,
        carbon_weight=carbon_weight,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy=charge_amount_strategy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        depot_precharge_target_kwh=None,
    )
    candidates = [("depot_fallback", fallback_route, fallback_actions)]
    if public_station_candidate_mode == DEFAULT_PUBLIC_STATION_CANDIDATE_MODE:
        return candidates
    node_types = {node.node_id: node.node_type.lower() for node in instance.nodes}
    if route.vehicle_type.lower() != "ev" or not route.node_sequence:
        return candidates
    node_lookup = {node.node_id: node for node in instance.nodes}
    remaining_customers = [
        node_id
        for node_id in route.node_sequence[1:]
        if node_types.get(node_id) == "c"
    ]
    load_kg = sum(float(node_lookup[node_id].demand) for node_id in remaining_customers)
    initial_battery = _price(prices, "initial_ev_battery_kwh")
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    stations = _available_station_visits(
        [node for node in instance.nodes if node.node_type.lower() == "f"],
        [],
    )
    start_node = route.node_sequence[0]
    launch_targets: set[float] = set()
    for station in stations:
        launch_target = max(
            initial_battery,
            _ev_energy(
                instance,
                start_node,
                station.node_id,
                load_kg,
                prices,
            ),
        )
        if launch_target > battery_cap + 1e-9:
            continue
        rounded_target = round(float(launch_target), 12)
        if rounded_target in launch_targets:
            continue
        launch_targets.add(rounded_target)
        try:
            public_route, public_actions = _repair_route_charging_candidate(
                route,
                instance,
                gamma_profile,
                prices,
                strategy=strategy,
                carbon_weight=carbon_weight,
                depot_charge_window_mode=depot_charge_window_mode,
                charge_timing_policy=charge_timing_policy,
                charge_amount_strategy=charge_amount_strategy,
                carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
                depot_precharge_target_kwh=launch_target,
            )
        except ValueError:
            continue
        public_station_ids = [
            action.station_id
            for action in public_actions
            if node_types.get(action.station_id) == "f"
        ]
        if not public_station_ids:
            continue
        if any(
            candidate_route == public_route and candidate_actions == public_actions
            for _, candidate_route, candidate_actions in candidates
        ):
            continue
        candidates.append(
            (
                f"public_station_{public_station_ids[0]}",
                public_route,
                public_actions,
            )
        )
    return candidates


def _repair_route_charging_candidate(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    strategy: str,
    carbon_weight: float,
    depot_charge_window_mode: str,
    charge_timing_policy: str,
    charge_amount_strategy: str,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None,
    depot_precharge_target_kwh: float | None,
) -> tuple[Route, list[ChargingAction]]:
    """Build one charging path without changing any feasibility rule."""

    if strategy not in {"legacy", "integrated"}:
        raise ValueError(f"unknown charging-repair strategy: {strategy}")
    validate_depot_charge_window_mode(depot_charge_window_mode)
    validate_charge_timing_policy(charge_timing_policy)
    charge_amount_strategy = normalize_charge_amount_strategies(
        (charge_amount_strategy,)
    )[0]

    if route.vehicle_type.lower() != "ev":
        return route, []
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
        strategy=strategy,
        carbon_weight=carbon_weight,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy=charge_amount_strategy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        target_charge_level_kwh=depot_precharge_target_kwh,
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
        needed_direct = _ev_energy(
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
            coverage_targets = (
                future_targets
                if depot_precharge_target_kwh is not None
                else future_targets[: int(failure_offset) + 1]
                if failure_offset is not None
                else [target]
            )
            available_stations = _available_station_visits(stations, repaired)
            if not available_stations and battery + 1e-9 < needed_direct:
                raise ValueError("No charging stations available for EV charging repair")
            candidate = _best_station_insert(
                current,
                target,
                coverage_targets,
                future_targets,
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
                strategy=strategy,
                carbon_weight=carbon_weight,
                charge_timing_policy=charge_timing_policy,
                charge_amount_strategy=charge_amount_strategy,
            )
            if candidate is None:
                if battery + 1e-9 < needed_direct:
                    raise ValueError(f"No feasible charging insert between {current} and {target}")
            else:
                station_id, action, arrive_station, depart_station, battery_after_charge = candidate
                repaired.append(station_id)
                actions.append(action)
                battery = battery_after_charge
                time_s = depart_station
                current = station_id

        travel = _ev_travel_time(
            instance,
            current,
            target,
            prices,
        )
        battery -= _ev_energy(
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
        strategy=strategy,
        carbon_weight=carbon_weight,
        charge_timing_policy=charge_timing_policy,
    )
    return repaired_route, actions


def _available_station_visits(
    stations: list[Node], repaired: list[str]
) -> list[Node]:
    """Expose one unused visit identity per physical station."""

    used = set(repaired)
    physical_seen: set[str] = set()
    available: list[Node] = []
    for station in stations:
        physical = physical_station_id(station)
        if station.node_id in used or physical in physical_seen:
            continue
        physical_seen.add(physical)
        available.append(station)
    return available


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
        total += _ev_energy(
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
        local_battery -= _ev_energy(
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
            earliest = route_return_arrival_without_charging(route, instance, prices)
            latest = (
                route_next_day_departure_second(
                    route,
                    instance,
                    prices,
                    period_seconds=period,
                )
                - occupancy_sec
            )
            return earliest, latest
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
        successor_id = node_sequence[idx + 1]
        successor = node_lookup[successor_id]
        latest = min(
            latest,
            float(successor.due_time)
            - occupancy_sec
            - _ev_travel_time(
                instance,
                node_id,
                successor_id,
                prices,
            ),
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
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    depot_charge_window_mode: str = "same_day_predeparture",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    target_charge_level_kwh: float | None = None,
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
    if target_charge_level_kwh is None:
        target_charge_level = charge_amount_target_kwh(
            charge_amount_strategy,
            just_enough_kwh=route_need,
            max_coverage_kwh=route_need,
            capacity_kwh=battery_cap,
        )
    else:
        target_charge_level = float(target_charge_level_kwh)
        if (
            not math.isfinite(target_charge_level)
            or target_charge_level < initial_battery - 1e-9
            or target_charge_level > battery_cap + 1e-9
        ):
            raise ValueError(
                "depot launch charge target must lie within battery bounds"
            )
    energy_needed = max(0.0, target_charge_level - initial_battery)
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
        instance,
        prices,
        gamma_profile,
        mode=depot_charge_window_mode,
        strategy=strategy,
        carbon_weight=carbon_weight,
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
    carbon_weight: float = 1.0,
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
        carbon_weight=carbon_weight,
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
        total += _ev_energy(
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
        direct_time = _ev_travel_time(instance, current, target, prices)
        direct_energy = _ev_energy(
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
                time_to_station = _ev_travel_time(
                    instance,
                    current,
                    station.node_id,
                    prices,
                )
                energy_to_station = _ev_energy(
                    instance,
                    current,
                    station.node_id,
                    load_kg,
                    prices,
                )
                if energy_to_station > battery + 1e-9:
                    continue
                time_station_to_target = _ev_travel_time(
                    instance,
                    station.node_id,
                    target,
                    prices,
                )
                energy_station_to_target = _ev_energy(
                    instance,
                    station.node_id,
                    target,
                    load_kg,
                    prices,
                )
                if energy_station_to_target > battery_cap + 1e-9:
                    continue
                travel_time = time_to_station + time_station_to_target
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
    future_targets: list[str],
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
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
) -> tuple[str, ChargingAction, float, float, float] | None:
    best: tuple[float, float, str, ChargingAction, float, float, float] | None = None
    refined: list[tuple[ChargeOption, float, float]] = []
    for station in stations:
        to_station = _ev_distance(
            instance,
            current,
            station.node_id,
            prices,
        )
        time_to_station = _ev_travel_time(
            instance,
            current,
            station.node_id,
            prices,
        )
        energy_to_station = _ev_energy(
            instance,
            current,
            station.node_id,
            load_kg,
            prices,
        )
        if battery + 1e-9 < energy_to_station:
            continue
        battery_at_station = battery - energy_to_station
        station_to_target = _ev_distance(
            instance,
            station.node_id,
            target,
            prices,
        )
        time_station_to_target = _ev_travel_time(
            instance,
            station.node_id,
            target,
            prices,
        )
        energy_to_target = _ev_energy(
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
        max_coverage_need = _direct_route_energy_need(
            station.node_id,
            future_targets,
            node_lookup,
            instance,
            prices,
            remaining_customers=remaining_customers,
        )
        target_charge_level = charge_amount_target_kwh(
            charge_amount_strategy,
            just_enough_kwh=segment_need_from_station,
            max_coverage_kwh=max_coverage_need,
            capacity_kwh=battery_cap,
        )
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
            float(target_node.due_time)
            - occupancy_sec
            - time_station_to_target,
        )
        if strategy == "integrated":
            latest = min(
                latest,
                _latest_charge_start_for_downstream(
                    station.node_id,
                    future_targets,
                    node_lookup,
                    instance,
                    prices,
                    occupancy_sec,
                ),
            )
        if latest + 1e-9 < earliest:
            continue
        detour = (
            to_station
            + station_to_target
            - _ev_distance(instance, current, target, prices)
        )
        detour_seconds = (
            time_to_station
            + time_station_to_target
            - _ev_travel_time(instance, current, target, prices)
        )
        if strategy == "integrated":
            refined.append(
                (
                    ChargeOption(
                        station_id=station.node_id,
                        node_type=station.node_type,
                        earliest_start_second=earliest,
                        latest_start_second=latest,
                        energy_kwh=energy_needed,
                        power_kw=float(station.charge_power_kw),
                        detour_m=detour,
                        detour_seconds=detour_seconds,
                        occupancy_seconds_override=occupancy_sec,
                        start_energy_kwh=action.start_energy_kwh,
                        end_energy_kwh=action.end_energy_kwh,
                        charging_curve_id=action.charging_curve_id,
                    ),
                    arrive,
                    battery_at_station + energy_needed,
                )
            )
            continue
        station_profile = time_profile_rows_for_node(
            instance,
            station.node_id,
            gamma_profile,
        )
        charge_start, gamma = _lowest_gamma_slot_start(
            earliest,
            latest,
            station_profile,
        )
        if charge_timing_policy != "carbon_min":
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
        key = (gamma, detour, station.node_id, action, arrive, depart, battery_at_station + energy_needed)
        if best is None or (key[0], key[1], key[2]) < (best[0], best[1], best[2]):
            best = key
    if strategy == "integrated":
        if not refined:
            return None
        if not isinstance(prices, PriceParameters):
            raise TypeError("integrated charging repair currently requires PriceParameters")
        scored = select_charge_option(
            [item[0] for item in refined],
            instance,
            gamma_profile,
            prices,
            carbon_weight=carbon_weight,
            charge_timing_policy=charge_timing_policy,
        )
        option = scored.option
        _, arrive, battery_after = next(item for item in refined if item[0] == option)
        depart = scored.timing.start_second + option.occupancy_seconds
        action = replace(
            option.action_at(scored.timing.start_second),
            vehicle_id=vehicle_id,
        )
        return option.station_id, action, arrive, depart, battery_after
    if best is None:
        return None
    _, _, station_id, action, arrive, depart, battery_after = best
    return station_id, action, arrive, depart, battery_after


def _latest_charge_start_for_downstream(
    station_id: str,
    future_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    occupancy_sec: float,
) -> float:
    """Protect every downstream due time after an inserted station."""

    if not future_targets:
        return float(node_lookup[station_id].due_time) - float(occupancy_sec)
    successor_id = future_targets[-1]
    latest_successor_start = float(node_lookup[successor_id].due_time)
    for current_id in reversed(future_targets[:-1]):
        current = node_lookup[current_id]
        travel = _ev_travel_time(
            instance,
            current_id,
            successor_id,
            prices,
        )
        latest_successor_start = min(
            float(current.due_time),
            latest_successor_start - float(current.service_time) - travel,
        )
        successor_id = current_id
    return latest_successor_start - float(occupancy_sec) - _ev_travel_time(
        instance,
        station_id,
        successor_id,
        prices,
    )


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


def _ev_distance(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    distance, _, _ = instance.arc_metrics(
        from_node_id,
        to_node_id,
        "ev",
        fallback_speed_mps=_price(prices, "v_speed_ms"),
    )
    return distance


def _ev_travel_time(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    _, travel, _ = instance.arc_metrics(
        from_node_id,
        to_node_id,
        "ev",
        fallback_speed_mps=_price(prices, "v_speed_ms"),
    )
    return travel


def _ev_energy(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    return ev_instance_arc_energy_kwh(
        instance,
        from_node_id,
        to_node_id,
        load_kg,
        prices,
    )


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
