"""Cost and shared route timing helpers.

v2026-06-11: Added ``route_node_schedule`` as the single route time-recursion
helper shared by the scorer and hard-constraint checker. It computes
``NodeTime(node_id, t_arrive, t_start, t_depart)`` in SI units using
``t_arrive_j = t_depart_i + d_ij / v``, ``t_start_j = max(t_arrive_j, e_j)``,
and ``t_depart_j = t_start_j + s_j``. Here ``e_j`` and ``s_j`` correspond to
the paper's time-window lower bound and service-time symbols, while ``v`` is
``prices.v_speed_ms``. Use it whenever route-derived timing is needed, for
example carbon-slot lookup at a charging station or hard TIME_WINDOW checks.

v2026-06-11: Added B-full charging-slot construction for paper_main.tex
lines 428-457. Historical actions without curve metadata retain the sealed
uniform-rate interpretation under the explicit L100 control. Current actions
carry start/end energy and a curve id; ``charging_action_slot_breakdown``
integrates their true piecewise power over the same multi-period grid.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
from typing import Any

from .charging_curve import (
    ChargingCurveError,
    L100_CONTROL,
    PiecewiseChargingCurve,
    spec_from_parameters,
    slot_energy_kwh,
)
from .instance_loader import Instance, Node
from .prices import DEFAULT_PRICES, PriceParameters
from .solution import ChargingAction, Route, Solution, physical_vehicle_id


# v2026-06-11: fixed NESO experiment grid, 2025-11-13 08:00-17:00 UTC.
CARBON_ORIGIN_UTC = datetime(2025, 11, 13, 8, 0, 0, tzinfo=timezone.utc)
CARBON_ORIGIN_OFFSET_SECONDS = 0.0
CARBON_SLOT_SECONDS = 1800.0
CARBON_N_SLOTS = 18
# v2026-06-11: make NESO gCO2/kWh -> kgCO2e/kWh conversion explicit.
GCO2_PER_KGCO2 = 1000.0
_CARBON_PROFILE_SORT_CACHE: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]], list[float]]] = {}


@dataclass(frozen=True)
class RouteEnergy:
    vehicle_id: str
    vehicle_type: str
    distance_m: float
    fuel_liters: float
    ev_drive_kwh: float


@dataclass(frozen=True)
class NodeTime:
    node_id: str
    t_arrive: float
    t_start: float
    t_depart: float


@dataclass(frozen=True)
class ChargingSlot:
    slot_index: int
    g_skt_sec: float
    y_skt_kwh: float


def carbon_slot_index(t_second: float, *, n_slots: int | None = None, cyclic: bool = False) -> int:
    """Return the clamped NESO half-hour slot for a solver schedule time.

    v2026-06-11: B_GATE anchor helper for the 2025-11-13 08:00-17:00 UTC
    experiment grid. Solver schedule time ``t=0`` corresponds to
    ``CARBON_ORIGIN_UTC``; slots are 1800 s wide and clamped to the 18-slot
    generated carbon profile. Use this as the single source for time-to-slot
    mapping in cost diagnostics and multi-period charging.
    """

    # v2026-06-12: Q1 24h bundles pass n_slots=48 while legacy smoke tests
    # keep the previous 18-slot default.
    slot_count = CARBON_N_SLOTS if n_slots is None else int(n_slots)
    raw = math.floor((float(t_second) - CARBON_ORIGIN_OFFSET_SECONDS) / CARBON_SLOT_SECONDS)
    if cyclic:
        # v2026-06-12: S0 overnight depot charging uses the 48-slot daily
        # carbon table cyclically when charging crosses midnight.
        if raw < 0:
            raise ValueError("charge_start_second is before the first carbon profile slot")
        return int(raw) % slot_count
    return max(0, min(slot_count - 1, int(raw)))


def carbon_profile_row_for_slot(carbon_profile: list[dict[str, Any]], slot_index: int) -> dict[str, Any]:
    """Return the carbon-profile row for a clamped NESO slot index.

    v2026-06-11: B_GATE gamma round-trip helper. The slot index is normalized
    through ``carbon_slot_index`` so cost, diagnostics, and tests share the
    same 18-slot 2025-11-13 UTC grid before applying previous-hold lookup.
    """

    # v2026-06-12: canonicalize against the actual profile length so 48-slot
    # Q1 bundles do not clamp to the legacy 18-slot default.
    canonical_slot = carbon_slot_index(float(slot_index) * CARBON_SLOT_SECONDS, n_slots=len(carbon_profile))
    return _previous_hold_carbon_row(carbon_profile, float(canonical_slot) * CARBON_SLOT_SECONDS)


def time_profile_rows_for_node(
    instance: Instance,
    node_id: str,
    time_profile: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one node's city-specific rows or the historical shared rows."""

    profile_cities = {
        str(row["city"]).strip().lower()
        for row in time_profile
        if row.get("city") not in {None, ""}
    }
    if not profile_cities:
        return time_profile
    try:
        node = instance.nodes[instance.node_index[node_id]]
    except KeyError as exc:
        raise ValueError(
            f"time profile requested for unknown node {node_id!r}"
        ) from exc
    if node.city is None or not str(node.city).strip():
        raise ValueError(
            f"node {node_id!r} has no city for a city-specific time profile"
        )
    city = str(node.city).strip().lower()
    rows = [
        row
        for row in time_profile
        if str(row.get("city", "")).strip().lower() == city
    ]
    if not rows:
        raise ValueError(
            f"time profile has no rows for node {node_id!r} city {city!r}"
        )
    return rows


def evaluate(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    carbon_quota_kg: float = 0.0,
) -> dict[str, float]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    route_energy = [_evaluate_route(route, instance, node_lookup, prices) for route in solution.routes]

    distance_total = sum(item.distance_m for item in route_energy)
    distance_cv = sum(item.distance_m for item in route_energy if item.vehicle_type == "cv")
    distance_ev = sum(item.distance_m for item in route_energy if item.vehicle_type == "ev")
    fuel_liters = sum(item.fuel_liters for item in route_energy if item.vehicle_type == "cv")
    ev_drive_kwh = sum(item.ev_drive_kwh for item in route_energy if item.vehicle_type == "ev")

    n_veh_cv = len({physical_vehicle_id(route.vehicle_id) for route in solution.routes if route.vehicle_type.lower() == "cv"})
    n_veh_ev = len({physical_vehicle_id(route.vehicle_id) for route in solution.routes if route.vehicle_type.lower() == "ev"})
    electricity_kwh = sum(float(action.energy_kwh) for action in solution.charging_actions)

    # MC-W1-F2-DEPOT-CONCURRENCY-01: the fixed acquisition/activation charge
    # applies once per used physical vehicle, not once per delivery trip.
    cost_fix = (n_veh_cv + n_veh_ev) * _price(prices, "vehicle_fixed_cost")
    cost_km = sum(
        item.distance_m
        / 1000.0
        * instance.non_energy_distance_cost_per_km(
            item.vehicle_type,
            fallback=_price(prices, "c_km"),
        )
        for item in route_energy
    )
    cost_fuel = sum(
        item.fuel_liters
        * diesel_price_for_route(route, instance, prices)
        for route, item in zip(solution.routes, route_energy)
        if item.vehicle_type == "cv"
    )
    # v2026-06-12: Q2 depot precharge has depot electricity price and no public occupancy fee.
    cost_elec = _charging_electricity_cost(
        solution,
        instance,
        carbon_profile,
        prices,
    )
    cost_occ = _charging_occupancy_cost(solution, node_lookup, prices)
    route_time_seconds = _e5_route_time_seconds(solution, instance, node_lookup, prices)
    cost_time = (
        route_time_seconds
        / 3600.0
        * _optional_price(prices, "route_time_cost_per_hour")
    )
    cost_transship = len(solution.cross_site_services) * _price(prices, "cross_site_cost")

    e_cv_direct = fuel_liters * _price(prices, "diesel_ef")
    e_ev_indirect = _ev_indirect_emissions(
        solution,
        instance,
        carbon_profile,
        prices,
    )
    e_total = e_cv_direct + e_ev_indirect
    # v2026-06-12: Z0a keeps the buy/sell carbon-trading term for finite CE,
    # and treats CE=inf as the no-quota baseline with a zero carbon-cost term.
    quota = float(carbon_quota_kg)
    cost_carbon = 0.0 if math.isinf(quota) else (e_total - quota) * _price(prices, "carbon_price")
    total_cost = cost_fix + cost_km + cost_fuel + cost_elec + cost_occ + cost_time + cost_transship + cost_carbon

    return {
        "total_cost": total_cost,
        "cost_fix": cost_fix,
        "cost_km": cost_km,
        "cost_fuel": cost_fuel,
        "cost_elec": cost_elec,
        "cost_occ": cost_occ,
        "cost_time": cost_time,
        "cost_transship": cost_transship,
        "cost_carbon": cost_carbon,
        "E_total": e_total,
        "E_cv_direct": e_cv_direct,
        "E_ev_indirect": e_ev_indirect,
        "n_veh_cv": n_veh_cv,
        "n_veh_ev": n_veh_ev,
        "distance_total": distance_total,
        "distance_cv": distance_cv,
        "distance_ev": distance_ev,
        "fuel_liters": fuel_liters,
        "electricity_kwh": electricity_kwh,
        "route_time_hours": route_time_seconds / 3600.0,
        "depot_charging_kwh": _charging_energy_by_node_type(solution, node_lookup, {"d"}),
        "station_charging_kwh": _charging_energy_by_node_type(solution, node_lookup, {"f"}),
        "carbon_quota_kg": quota,
        "ev_drive_kwh": ev_drive_kwh,
    }


def diesel_price_for_route(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Return the diesel price for a route's origin-depot city.

    Historical scenarios have no city map and retain ``diesel_price``. A
    China81 formal bundle supplies a non-empty city map, in which case a
    missing depot city or missing city price is a hard data error.
    """

    raw_mapping = (
        prices.get("diesel_price_by_city", ())
        if isinstance(prices, dict)
        else getattr(prices, "diesel_price_by_city", ())
    )
    if not raw_mapping:
        return _price(prices, "diesel_price")
    mapping = {
        str(city).strip().lower(): float(value)
        for city, value in raw_mapping
    }
    try:
        depot = instance.nodes[instance.node_index[route.home_depot_id]]
    except KeyError as exc:
        raise ValueError(
            f"diesel settlement requested for unknown depot "
            f"{route.home_depot_id!r}"
        ) from exc
    if depot.node_type.lower() != "d":
        raise ValueError(
            f"diesel settlement origin is not a depot: "
            f"{route.home_depot_id!r}"
        )
    city = "" if depot.city is None else str(depot.city).strip().lower()
    if not city:
        raise ValueError(
            f"diesel settlement depot {route.home_depot_id!r} has no city"
        )
    try:
        return mapping[city]
    except KeyError as exc:
        raise ValueError(
            f"diesel price map has no route-origin city {city!r}"
        ) from exc


def _evaluate_route(
    route: Route,
    instance: Instance,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
) -> RouteEnergy:
    vehicle_type = route.vehicle_type.lower()
    if vehicle_type not in {"cv", "ev"}:
        raise ValueError(f"Unsupported vehicle_type: {route.vehicle_type}")
    if len(route.node_sequence) < 2:
        return RouteEnergy(route.vehicle_id, vehicle_type, 0.0, 0.0, 0.0)

    loads = _arc_loads(route.node_sequence, node_lookup)
    distance_m = 0.0
    fuel_liters = 0.0
    ev_drive_kwh = 0.0

    for (from_node_id, to_node_id), load_kg in zip(zip(route.node_sequence, route.node_sequence[1:]), loads):
        leg_distance_m, time_s, sum_v2d = instance.arc_metrics(
            from_node_id,
            to_node_id,
            vehicle_type,
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        distance_m += leg_distance_m
        if instance.road_profiles is None:
            power_w = _mechanical_power_w(load_kg, prices)
            if vehicle_type == "cv":
                fuel_liters += _fuel_liters(power_w, time_s, prices)
            else:
                ev_drive_kwh += _ev_drive_kwh(power_w, time_s, prices)
        elif vehicle_type == "cv":
            fuel_liters += _profile_arc_fuel_liters(
                leg_distance_m,
                time_s,
                sum_v2d,
                load_kg,
                prices,
                instance=instance,
                vehicle_type="cv",
            )
        else:
            ev_drive_kwh += (
                _price(prices, "alpha_e")
                * _profile_mechanical_energy_j(
                    leg_distance_m,
                    sum_v2d,
                    load_kg,
                    prices,
                    instance=instance,
                    vehicle_type="ev",
                )
                / 3_600_000.0
            )

    return RouteEnergy(route.vehicle_id, vehicle_type, distance_m, fuel_liters, ev_drive_kwh)


def route_node_schedule(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    charging_actions: list[ChargingAction] | None = None,
) -> list[NodeTime]:
    """Return service-time-aware arrival/start/departure times for a route.

    v2026-06-11: Implements the shared SI-unit timing recursion for paper
    time-window symbols ``e_i`` and service times ``s_i``. The first depot
    departs from its time-window lower bound; downstream nodes wait until
    ``ready_time`` if early, then add ``service_time`` before the next arc.

    v2026-06-11: For charging stations, ``t_start`` is paper ``a_sk^tau``
    (charge_start_second) and ``t_depart`` is charge start plus occupancy,
    matching paper_main.tex lines 428-438 and time-flow line 359.

    A depot action with a negative ``charge_day_offset`` belongs to a day
    before this static route horizon. It supplies departure energy but cannot
    delay the current-day origin departure.
    """

    if not route.node_sequence:
        return []

    node_lookup = {node.node_id: node for node in instance.nodes}
    charging_by_node = _charging_actions_for_route(route.vehicle_id, charging_actions or [])
    first = node_lookup[route.node_sequence[0]]
    first_arrive = float(first.ready_time)
    first_start = max(first_arrive, float(first.ready_time))
    first_depart = first_start + float(first.service_time)
    # v2026-06-12: depot pre-departure charging completes before the route leaves the origin depot.
    first_actions = charging_by_node.get(first.node_id, []) if first.node_type.lower() == "d" else []
    if first_actions:
        # v2026-06-12: S0 depot actions after route return belong to the
        # overnight return-to-next-departure window and do not delay the same
        # day's route schedule. Pre-return actions still behave as legacy
        # pre-departure charging so invalid starts remain visible to check.py.
        first_actions = [
            action
            for action in first_actions
            if int(action.charge_day_offset) >= 0
            and not is_overnight_depot_charge(action, route, instance, prices)
        ]
    if first_actions:
        first_depart = max(
            first_depart,
            max(float(action.charge_start_second) + float(action.occupancy_minutes) * 60.0 for action in first_actions),
        )
    schedule = [
        NodeTime(
            node_id=first.node_id,
            t_arrive=first_arrive,
            t_start=first_start,
            t_depart=first_depart,
        )
    ]

    for from_node_id, to_node_id in zip(route.node_sequence, route.node_sequence[1:]):
        to_node = node_lookup[to_node_id]
        _, travel_time, _ = instance.arc_metrics(
            from_node_id,
            to_node_id,
            route.vehicle_type,
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        arrive = schedule[-1].t_depart + travel_time
        # v2026-06-11: charging stations use the action's charge_start and occupancy to push downstream time.
        station_actions = charging_by_node.get(to_node_id, [])
        if to_node.node_type.lower() == "f" and station_actions:
            start = min(float(action.charge_start_second) for action in station_actions)
            depart = max(float(action.charge_start_second) + float(action.occupancy_minutes) * 60.0 for action in station_actions)
        else:
            start = max(arrive, float(to_node.ready_time))
            depart = start + float(to_node.service_time)
        schedule.append(NodeTime(to_node.node_id, arrive, start, depart))

    return schedule


def charging_slot_breakdown(
    charge_start_sec: float,
    occupancy_sec: float,
    energy_kwh: float,
    instance: Instance,
    *,
    n_slots: int | None = None,
    cyclic: bool = False,
) -> list[ChargingSlot]:
    """Construct paper ``g_skt`` and ``y_skt`` values for one charging action.

    v2026-06-11: This is the single source for B-full multi-period charging
    accounting. It implements the paper_main.tex charging interval statement
    at lines 428-438 and the charging-power constraint at lines 449-457:
    split ``[charge_start, charge_start + occupancy]`` over the 18 half-hour
    NESO slots, set ``g_skt`` to overlap seconds, and uniformly allocate
    ``y_skt = energy * g_skt / occupancy``. Use it from both cost and check;
    it does not enforce ``pi_s`` itself.
    """

    _ = instance
    start = float(charge_start_sec)
    duration = float(occupancy_sec)
    energy = float(energy_kwh)
    if duration < 0.0:
        raise ValueError("occupancy_sec must be non-negative")
    if start < 0.0:
        raise ValueError("charge_start_second is before the first carbon profile slot")
    if duration == 0.0:
        return []

    end = start + duration
    rows: list[ChargingSlot] = []
    slot_count = CARBON_N_SLOTS if n_slots is None else int(n_slots)
    if cyclic:
        # v2026-06-12: S0 cyclic split preserves exact g_skt/y_skt across the
        # midnight boundary instead of clamping the final slot.
        cursor = start
        while cursor < end - 1e-12:
            slot_index = carbon_slot_index(cursor, n_slots=slot_count, cyclic=True)
            next_boundary = (math.floor(cursor / CARBON_SLOT_SECONDS) + 1) * CARBON_SLOT_SECONDS
            overlap_end = min(end, next_boundary)
            overlap = overlap_end - cursor
            if overlap > 0.0:
                rows.append(ChargingSlot(slot_index, overlap, energy * overlap / duration))
            cursor = overlap_end
        return rows
    first_slot = carbon_slot_index(start, n_slots=slot_count)
    last_slot = carbon_slot_index(end, n_slots=slot_count)
    for slot_index in range(first_slot, last_slot + 1):
        slot_start = slot_index * CARBON_SLOT_SECONDS
        # v2026-06-12: use the actual profile length. Feasible Q1/Q2 gates
        # keep route deadlines inside the carbon window, so no final-slot
        # infinite hold is needed for valid solutions.
        slot_end = (slot_index + 1) * CARBON_SLOT_SECONDS if slot_index < slot_count - 1 else slot_count * CARBON_SLOT_SECONDS
        overlap_start = max(start, slot_start)
        overlap_end = min(end, slot_end)
        overlap = overlap_end - overlap_start
        if overlap <= 0.0:
            continue
        rows.append(ChargingSlot(slot_index, overlap, energy * overlap / duration))

    return rows


def charging_curve_for_action(
    action: ChargingAction,
    instance: Instance,
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
) -> tuple[PiecewiseChargingCurve, float, float] | None:
    """Validate and return the physical curve state for one charging action.

    Historical L100 actions may omit the three appended metadata fields. A
    nonlinear action may not: silently reconstructing it as uniform charging
    would change both feasibility and time-slot carbon accounting.
    """

    metadata = (
        action.start_energy_kwh,
        action.end_energy_kwh,
        action.charging_curve_id,
    )
    try:
        spec = spec_from_parameters(prices)
    except ChargingCurveError as exc:
        raise ValueError(f"invalid charging curve parameters: {exc}") from exc
    if all(value is None for value in metadata):
        if spec.curve_id != L100_CONTROL.curve_id:
            raise ValueError(
                "nonlinear charging action is missing start/end energy "
                "and curve id"
            )
        return None
    if any(value is None for value in metadata):
        raise ValueError("charging action has incomplete curve metadata")
    nodes = {node.node_id: node for node in instance.nodes}
    station = nodes.get(action.station_id)
    if station is None or station.node_type.lower() not in {"d", "f"}:
        raise ValueError(
            f"charging action uses unknown or non-charging node "
            f"{action.station_id!r}"
        )
    if station.node_type.lower() == "d":
        reference_power_kw = _price(prices, "depot_charge_power_kw")
    else:
        if station.charge_power_kw is None:
            raise ValueError(
                f"charging station {station.node_id!r} has no charge power"
            )
        reference_power_kw = float(station.charge_power_kw)
    curve = spec.scale(
        capacity_kwh=instance.battery_capacity_kwh(
            fallback=_price(prices, "B_battery_kwh"),
        ),
        reference_power_kw=reference_power_kw,
    )
    if action.charging_curve_id != curve.curve_id:
        raise ValueError(
            f"charging action curve {action.charging_curve_id!r} disagrees "
            f"with prices curve {curve.curve_id!r}"
        )

    start_energy = float(action.start_energy_kwh)
    end_energy = float(action.end_energy_kwh)
    tolerance = 1e-7
    if (
        not math.isfinite(start_energy)
        or not math.isfinite(end_energy)
        or start_energy < -tolerance
        or end_energy > curve.capacity_kwh + tolerance
        or end_energy < start_energy - tolerance
    ):
        raise ValueError("charging action energy states violate battery bounds")
    start_energy = min(curve.capacity_kwh, max(0.0, start_energy))
    end_energy = min(curve.capacity_kwh, max(start_energy, end_energy))
    recorded_energy = float(action.energy_kwh)
    if abs((end_energy - start_energy) - recorded_energy) > tolerance:
        raise ValueError(
            "charging action energy disagrees with start/end energy states"
        )
    expected_duration = (
        0.0
        if end_energy - start_energy <= tolerance
        else curve.duration_seconds(start_energy, end_energy)
    )
    recorded_duration = float(action.occupancy_minutes) * 60.0
    if abs(expected_duration - recorded_duration) > tolerance:
        raise ValueError(
            "charging action occupancy disagrees with the charging curve"
        )
    return curve, start_energy, end_energy


def charging_action_slot_breakdown(
    action: ChargingAction,
    instance: Instance,
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
    *,
    n_slots: int | None = None,
    cyclic: bool = False,
) -> list[ChargingSlot]:
    """Split one action using its exact curve, with L100 legacy compatibility."""

    curve_state = charging_curve_for_action(action, instance, prices)
    if curve_state is None:
        return charging_slot_breakdown(
            float(action.charge_start_second),
            float(action.occupancy_minutes) * 60.0,
            float(action.energy_kwh),
            instance,
            n_slots=n_slots,
            cyclic=cyclic,
        )
    curve, start_energy, end_energy = curve_state
    duration = float(action.occupancy_minutes) * 60.0
    if duration <= 1e-12:
        return []
    start = float(action.charge_start_second)
    if not math.isfinite(start) or start < 0.0:
        raise ValueError(
            "charge_start_second is before the first carbon profile slot"
        )
    end = start + duration
    first_absolute_slot = math.floor(start / CARBON_SLOT_SECONDS)
    final_boundary_slot = math.ceil(end / CARBON_SLOT_SECONDS)
    if final_boundary_slot <= first_absolute_slot:
        final_boundary_slot = first_absolute_slot + 1
    boundaries = tuple(
        float(slot) * CARBON_SLOT_SECONDS
        for slot in range(first_absolute_slot, final_boundary_slot + 1)
    )
    energies = slot_energy_kwh(
        curve,
        start_energy_kwh=start_energy,
        end_energy_kwh=end_energy,
        charging_start_seconds=start,
        slot_boundaries_seconds=boundaries,
    )
    slot_count = CARBON_N_SLOTS if n_slots is None else int(n_slots)
    if slot_count <= 0:
        raise ValueError("charging slot count must be positive")
    rows: list[ChargingSlot] = []
    for offset, energy in enumerate(energies):
        absolute_slot = first_absolute_slot + offset
        left = boundaries[offset]
        right = boundaries[offset + 1]
        overlap = max(0.0, min(end, right) - max(start, left))
        if overlap <= 1e-12:
            continue
        if cyclic:
            slot_index = absolute_slot % slot_count
        else:
            if not 0 <= absolute_slot < slot_count:
                raise ValueError(
                    "non-cyclic charging action exceeds the carbon horizon"
                )
            slot_index = absolute_slot
        rows.append(ChargingSlot(slot_index, overlap, float(energy)))
    if abs(sum(row.y_skt_kwh for row in rows) - float(action.energy_kwh)) > 1e-7:
        raise ValueError("charging action slot energy does not close")
    return rows


def best_charging_action_start(
    action: ChargingAction,
    *,
    earliest_start_second: float,
    latest_start_second: float,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
    intensity_field: str = "actual_gco2_per_kwh",
) -> float:
    """Choose the exact minimum-carbon start for one fixed charging action."""

    earliest = float(earliest_start_second)
    latest = float(latest_start_second)
    if latest < earliest - 1e-9:
        raise ValueError("latest charging start precedes earliest start")
    if not carbon_profile or latest <= earliest + 1e-9:
        return earliest
    node_profile = time_profile_rows_for_node(
        instance,
        action.station_id,
        carbon_profile,
    )
    curve_state = charging_curve_for_action(action, instance, prices)
    duration = float(action.occupancy_minutes) * 60.0
    phase_boundaries = {0.0, duration}
    if curve_state is not None:
        curve, start_energy, end_energy = curve_state
        for phase in curve.phases(start_energy, end_energy):
            phase_boundaries.add(float(phase.relative_start_seconds))
            phase_boundaries.add(float(phase.relative_end_seconds))
    candidates = {earliest, latest}
    first_grid = math.floor(earliest / CARBON_SLOT_SECONDS) - 1
    final_grid = math.ceil((latest + duration) / CARBON_SLOT_SECONDS) + 1
    for index in range(first_grid, final_grid + 1):
        boundary = float(index) * CARBON_SLOT_SECONDS
        for phase_boundary in phase_boundaries:
            candidate = boundary - phase_boundary
            if earliest - 1e-9 <= candidate <= latest + 1e-9:
                candidates.add(min(latest, max(earliest, candidate)))

    def weighted_carbon(start: float) -> float:
        total = 0.0
        shifted = replace(action, charge_start_second=float(start))
        for slot in charging_action_slot_breakdown(
            shifted,
            instance,
            prices,
            n_slots=len(node_profile),
            cyclic=True,
        ):
            row = carbon_profile_row_for_slot(
                node_profile,
                slot.slot_index,
            )
            if intensity_field not in row:
                raise ValueError(
                    f"carbon profile is missing timing field "
                    f"{intensity_field!r}"
                )
            total += float(slot.y_skt_kwh) * float(row[intensity_field])
        return total

    return min(
        candidates,
        key=lambda start: (weighted_carbon(float(start)), float(start)),
    )


def charging_action_emissions_kg(
    action: ChargingAction,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
) -> float:
    """Return exact indirect emissions for one validated charging action."""

    total = 0.0
    node_profile = time_profile_rows_for_node(
        instance,
        action.station_id,
        carbon_profile,
    )
    for slot in charging_action_slot_breakdown(
        action,
        instance,
        prices,
        n_slots=len(node_profile),
        cyclic=True,
    ):
        row = carbon_profile_row_for_slot(
            node_profile,
            slot.slot_index,
        )
        total += (
            float(slot.y_skt_kwh)
            * float(row["actual_gco2_per_kwh"])
            / GCO2_PER_KGCO2
        )
    return total


def route_departure_second(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Return the route's natural current-day depot departure time.

    v2026-06-12: S0 uses this as the anchor for next-day depot charging. The
    route departs no earlier than the origin ready/service time and, when the
    first successor has a ready time, no later than needed to arrive there at
    that ready time.
    """

    if not route.node_sequence:
        return 0.0
    node_lookup = {node.node_id: node for node in instance.nodes}
    first = node_lookup[route.node_sequence[0]]
    departure = float(first.ready_time) + float(first.service_time)
    successor_id = None
    for node_id in route.node_sequence[1:]:
        if node_id in node_lookup and node_lookup[node_id].node_type.lower() not in {"d", "f"}:
            successor_id = node_id
            break
    if successor_id is None and len(route.node_sequence) > 1 and route.node_sequence[1] in node_lookup:
        successor_id = route.node_sequence[1]
    if successor_id is not None:
        successor = node_lookup[successor_id]
        _, travel, _ = instance.arc_metrics(
            route.node_sequence[0],
            successor_id,
            route.vehicle_type,
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        departure = max(departure, float(successor.ready_time) - travel)
    return max(0.0, departure)


def route_return_arrival_without_charging(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Return arrival time at the closing depot without charging actions."""

    schedule = route_node_schedule(route, instance, prices, charging_actions=[])
    if not schedule:
        return 0.0
    return float(schedule[-1].t_arrive)


def route_next_day_departure_second(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    period_seconds: float = 86_400.0,
) -> float:
    """Return the next cyclic departure after the route has returned.

    v2026-06-12: S0 depot charging window is [previous return, next departure].
    The default period is a 24h day; tests with shorter synthetic carbon tables
    can pass a shorter period.
    """

    base = route_departure_second(route, instance, prices)
    return_time = route_return_arrival_without_charging(route, instance, prices)
    period = float(period_seconds)
    if period <= 0.0:
        raise ValueError("period_seconds must be positive")
    departure = base + period
    while departure <= return_time + 1e-9:
        departure += period
    return departure


def is_overnight_depot_charge(
    action: ChargingAction,
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> bool:
    """Return True for a pre-horizon action or one after same-day return."""

    if not route.node_sequence or action.station_id != route.node_sequence[0]:
        return False
    if int(action.charge_day_offset) < 0:
        return True
    return float(action.charge_start_second) >= route_return_arrival_without_charging(route, instance, prices) - 1e-9


def _charging_actions_for_route(
    vehicle_id: str,
    charging_actions: list[ChargingAction],
) -> dict[str, list[ChargingAction]]:
    out: dict[str, list[ChargingAction]] = {}
    for action in charging_actions:
        if action.vehicle_id != vehicle_id:
            continue
        out.setdefault(action.station_id, []).append(action)
    return out


def _arc_loads(node_sequence: list[str], node_lookup: dict[str, Node]) -> list[float]:
    if len(node_sequence) < 2:
        return []
    loads = [0.0] * (len(node_sequence) - 1)
    remaining_demand = 0.0
    for idx in range(len(node_sequence) - 1, 0, -1):
        node = node_lookup[node_sequence[idx]]
        if node.node_type.lower() == "c":
            remaining_demand += float(node.demand)
        loads[idx - 1] = remaining_demand
    return loads


def _mechanical_power_w(load_kg: float, prices: PriceParameters | dict[str, float] | Any) -> float:
    drag_force = 0.5 * _price(prices, "c_d") * _price(prices, "rho_a") * _price(prices, "A_frontal") * _price(prices, "v_speed_ms") ** 2
    rolling_force = (_price(prices, "m_curb") + _price(prices, "m_unit") * load_kg) * _price(prices, "g0") * _price(prices, "c_r")
    return (drag_force + rolling_force) * _price(prices, "v_speed_ms")


def _fuel_liters(power_w: float, time_s: float, prices: PriceParameters | dict[str, float] | Any) -> float:
    # P_M is computed in W and converted to kJ/s here so it matches the k_engine term.
    power_kj_per_s = power_w / 1000.0
    fuel_rate_lps = (
        _price(prices, "xi_fuel_air")
        / (_price(prices, "kappa_heat") * _price(prices, "psi_conv"))
        * (
            _price(prices, "k_engine") * _price(prices, "N_engine") * _price(prices, "D_displace")
            + power_kj_per_s / (_price(prices, "eta_diesel") * _price(prices, "eta_tf"))
        )
    )
    return max(fuel_rate_lps, 0.0) * time_s


def _ev_drive_kwh(power_w: float, time_s: float, prices: PriceParameters | dict[str, float] | Any) -> float:
    return _price(prices, "alpha_e") * power_w * time_s / 3_600_000.0


def _profile_mechanical_energy_j(
    distance_m: float,
    sum_v2d_m3_s2: float,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    instance: Instance | None = None,
    vehicle_type: str | None = None,
) -> float:
    vehicle = (
        None
        if instance is None or vehicle_type is None
        else instance.vehicle_profile(vehicle_type)
    )
    drag = (
        _price(prices, "c_d")
        if vehicle is None
        else float(vehicle.drag_coefficient)
    )
    frontal_area = (
        _price(prices, "A_frontal")
        if vehicle is None
        else float(vehicle.frontal_area_m2)
    )
    curb_mass = (
        _price(prices, "m_curb")
        if vehicle is None
        else float(vehicle.curb_mass_kg)
    )
    rolling_resistance = (
        _price(prices, "c_r")
        if vehicle is None
        else float(vehicle.rolling_resistance_coefficient)
    )
    load_mass_kg = (
        _price(prices, "m_unit") * float(load_kg)
        if instance is None
        else instance.load_mass_kg(
            load_kg,
            fallback_mass_per_unit_kg=_price(prices, "m_unit"),
        )
    )
    drag_coefficient = (
        0.5
        * drag
        * _price(prices, "rho_a")
        * frontal_area
    )
    rolling_force = (
        curb_mass
        + load_mass_kg
    ) * _price(prices, "g0") * rolling_resistance
    return (
        drag_coefficient * float(sum_v2d_m3_s2)
        + rolling_force * float(distance_m)
    )


def _profile_arc_fuel_liters(
    distance_m: float,
    duration_s: float,
    sum_v2d_m3_s2: float,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    instance: Instance | None = None,
    vehicle_type: str = "cv",
) -> float:
    vehicle = (
        None
        if instance is None
        else instance.vehicle_profile(vehicle_type)
    )
    engine_friction = (
        _price(prices, "k_engine")
        if vehicle is None
        else float(vehicle.engine_friction_kj_per_rev_l)
    )
    engine_speed = (
        _price(prices, "N_engine")
        if vehicle is None
        else float(vehicle.engine_speed_rev_per_s)
    )
    engine_displacement = (
        _price(prices, "D_displace")
        if vehicle is None
        else float(vehicle.engine_displacement_l)
    )
    mechanical_energy_kj = (
        _profile_mechanical_energy_j(
            distance_m,
            sum_v2d_m3_s2,
            load_kg,
            prices,
            instance=instance,
            vehicle_type=vehicle_type,
        )
        / 1000.0
    )
    fuel = (
        _price(prices, "xi_fuel_air")
        / (_price(prices, "kappa_heat") * _price(prices, "psi_conv"))
        * (
            engine_friction
            * engine_speed
            * engine_displacement
            * float(duration_s)
            + mechanical_energy_kj
            / (
                _price(prices, "eta_diesel")
                * _price(prices, "eta_tf")
            )
        )
    )
    return max(fuel, 0.0)


def cv_instance_arc_fuel_liters(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Return CV fuel for one arc under the instance's frozen road profile."""

    if instance.road_profiles is None:
        distance_m = instance.distance(from_node_id, to_node_id)
        duration_s = distance_m / _price(prices, "v_speed_ms")
        return _fuel_liters(
            _mechanical_power_w(load_kg, prices),
            duration_s,
            prices,
        )
    distance_m, duration_s, sum_v2d = instance.arc_metrics(
        from_node_id,
        to_node_id,
        "cv",
        fallback_speed_mps=_price(prices, "v_speed_ms"),
    )
    return _profile_arc_fuel_liters(
        distance_m,
        duration_s,
        sum_v2d,
        load_kg,
        prices,
        instance=instance,
        vehicle_type="cv",
    )


def ev_profile_arc_energy_kwh(
    distance_m: float,
    sum_v2d_m3_s2: float,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Return exact EV traction energy from distance and sum(v^2 d)."""

    return (
        _price(prices, "alpha_e")
        * _profile_mechanical_energy_j(
            distance_m,
            sum_v2d_m3_s2,
            load_kg,
            prices,
        )
        / 3_600_000.0
    )


def ev_arc_energy_kwh(
    distance_m: float,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    time_s = float(distance_m) / _price(prices, "v_speed_ms")
    power_w = _mechanical_power_w(float(load_kg), prices)
    return _ev_drive_kwh(power_w, time_s, prices)


def ev_instance_arc_energy_kwh(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Return EV energy using a frozen EV road profile when one exists."""

    if instance.road_profiles is None:
        return ev_arc_energy_kwh(
            instance.distance(from_node_id, to_node_id),
            load_kg,
            prices,
        )
    distance, _, sum_v2d = instance.arc_metrics(
        from_node_id,
        to_node_id,
        "ev",
        fallback_speed_mps=_price(prices, "v_speed_ms"),
    )
    return (
        _price(prices, "alpha_e")
        * _profile_mechanical_energy_j(
            distance,
            sum_v2d,
            load_kg,
            prices,
            instance=instance,
            vehicle_type="ev",
        )
        / 3_600_000.0
    )


def _ev_indirect_emissions(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any,
) -> float:
    total = 0.0
    for action in solution.charging_actions:
        total += charging_action_emissions_kg(
            action,
            instance,
            carbon_profile,
            prices,
        )
    return total


def _charging_electricity_cost(
    solution: Solution,
    instance: Instance,
    time_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    return sum(
        charging_action_electricity_cost(
            action,
            instance,
            time_profile,
            prices,
        )
        for action in solution.charging_actions
    )


def charging_action_electricity_cost(
    action: ChargingAction,
    instance: Instance,
    time_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Settle one charge against city-specific time-of-use prices."""

    node_lookup = {node.node_id: node for node in instance.nodes}
    node = node_lookup.get(action.station_id)
    node_profile = time_profile_rows_for_node(
        instance,
        action.station_id,
        time_profile,
    )
    has_time_varying_price = any(
        "depot_energy_cny_per_kwh" in row
        or "public_total_cny_per_kwh" in row
        for row in node_profile
    )
    has_complete_time_varying_price = bool(node_profile) and all(
        "depot_energy_cny_per_kwh" in row
        and "public_total_cny_per_kwh" in row
        for row in node_profile
    )
    if has_time_varying_price and not has_complete_time_varying_price:
        raise ValueError(
            "time-varying charging profile has partial price fields"
        )
    if has_complete_time_varying_price:
        price_field = (
            "depot_energy_cny_per_kwh"
            if node is not None and node.node_type.lower() == "d"
            else "public_total_cny_per_kwh"
        )
        return sum(
            float(slot.y_skt_kwh)
            * float(
                carbon_profile_row_for_slot(
                    node_profile,
                    slot.slot_index,
                )[price_field]
            )
            for slot in charging_action_slot_breakdown(
                action,
                instance,
                prices,
                n_slots=len(node_profile),
                cyclic=True,
            )
        )
    unit_price = (
        _price(prices, "depot_electricity_price")
        if node is not None and node.node_type.lower() == "d"
        else _price(prices, "station_electricity_price")
    )
    return float(action.energy_kwh) * unit_price


def _charging_occupancy_cost(
    solution: Solution,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    total = 0.0
    for action in solution.charging_actions:
        node = node_lookup.get(action.station_id)
        if node and node.node_type.lower() == "d":
            continue
        total += float(action.occupancy_minutes) * _price(prices, "occupancy_fee")
    return total


def _e5_route_time_seconds(
    solution: Solution,
    instance: Instance,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    travel = sum(
        instance.arc_metrics(
            left,
            right,
            route.vehicle_type,
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )[1]
        for route in solution.routes
        for left, right in zip(route.node_sequence, route.node_sequence[1:])
    )
    enroute_charge = sum(
        float(action.occupancy_minutes) * 60.0
        for action in solution.charging_actions
        if node_lookup.get(action.station_id) is not None
        and node_lookup[action.station_id].node_type.lower() == "f"
    )
    return travel + enroute_charge


def _charging_energy_by_node_type(
    solution: Solution,
    node_lookup: dict[str, Node],
    node_types: set[str],
) -> float:
    return sum(
        float(action.energy_kwh)
        for action in solution.charging_actions
        if (node_lookup.get(action.station_id) and node_lookup[action.station_id].node_type.lower() in node_types)
    )


def _carbon_row_for_slot_index(carbon_profile: list[dict[str, Any]], slot_index: int) -> dict[str, Any]:
    # v2026-06-11: slot-index lookup reuses previous-hold carbon semantics at each slot start.
    return carbon_profile_row_for_slot(carbon_profile, slot_index)


def _previous_hold_carbon_row(carbon_profile: list[dict[str, Any]], second: float) -> dict[str, Any]:
    if not carbon_profile:
        raise ValueError("carbon_profile is required when charging actions are present")
    rows, starts = _sorted_carbon_profile_rows(carbon_profile)
    idx = bisect_right(starts, second) - 1
    if idx < 0:
        raise ValueError("charge_start_second is before the first carbon profile slot")
    return rows[idx]


def _sorted_carbon_profile_rows(carbon_profile: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[float]]:
    cached = _CARBON_PROFILE_SORT_CACHE.get(id(carbon_profile))
    if cached is not None and cached[0] is carbon_profile:
        return cached[1], cached[2]
    rows = sorted(carbon_profile, key=lambda row: float(row["horizon_second_start"]))
    starts = [float(row["horizon_second_start"]) for row in rows]
    _CARBON_PROFILE_SORT_CACHE[id(carbon_profile)] = (carbon_profile, rows, starts)
    return rows, starts


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _optional_price(
    prices: PriceParameters | dict[str, float] | Any,
    name: str,
) -> float:
    if isinstance(prices, dict):
        return float(prices.get(name, 0.0))
    return float(getattr(prices, name, 0.0))
