"""Versioned physical-vehicle scheduling contract for new E3--E7 evidence.

This module is deliberately additive.  It does not alter the legacy route-level
checker used by frozen E1/E2 artifacts. V1 is retained as the historical
full-recharge audit rule; V2 treats every Route as one trip, assigns
non-overlapping trips to real vehicles, and carries battery between trips.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any

from ..charge_timing import (
    ChargeTimingContexts,
    DEFAULT_CHARGE_TIMING_POLICY,
    charge_timing_objective_value,
    select_charge_timing_start,
    validate_charge_timing_policy,
)
from ..charging_curve import (
    L100_CONTROL,
    ChargingCurveError,
    PiecewiseChargingCurve,
    curve_for_charging_node,
    pack_trip_chain,
)
from ..cost import (
    _arc_loads,
    _price,
    best_charging_action_start,
    carbon_profile_row_for_slot,
    charging_curve_for_action,
    charging_slot_breakdown,
    ev_instance_arc_energy_kwh,
    route_departure_second,
    time_profile_rows_for_node,
)
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import (
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
    route_trip_vehicle_id,
)

LEGACY_CONTRACT_ID = "E3_STRICT_MULTITRIP_V1"
CONTRACT_ID = "E3_STRICT_MULTITRIP_V2"
NONLINEAR_CONTRACT_ID = "E3_STRICT_MULTITRIP_V3_NL"
E4_CONTINUOUS_SOC_CONTRACT_ID = "E4_SOC_60_20_80_NEXT_DAY_60_V1"
CHARGE_MODE_FULL = "full"
CHARGE_MODE_PARTIAL = "partial"
CHARGE_MODE_ON_DEMAND = "on_demand"
STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET = -1
STATIC_PREHORIZON_SECONDS = 86_400.0
DEPOT_CHARGE_WINDOW_MODES = frozenset(
    {
        "prev_night",
        "same_day_predeparture",
        "full_gap",
    }
)
DEFAULT_DEPOT_CHARGE_WINDOW_MODE = "same_day_predeparture"
_TOL = 1e-6


@dataclass(frozen=True)
class TripTiming:
    route_id: str
    vehicle_type: str
    home_depot_id: str
    earliest_departure_second: float
    return_second: float
    drive_energy_kwh: float
    public_charge_energy_kwh: float = 0.0
    required_departure_battery_kwh: float | None = None


@dataclass(frozen=True)
class ScheduledTrip:
    route_id: str
    physical_vehicle_id: str
    trip_index: int
    vehicle_type: str
    home_depot_id: str
    departure_second: float
    return_second: float
    recharge_end_second: float
    start_battery_kwh: float | None
    end_battery_kwh: float | None
    charge_start_second: float | None = None
    charge_energy_kwh: float | None = None
    in_route_charge_energy_kwh: float = 0.0
    fixed_departure_battery_kwh: float | None = None


@dataclass(frozen=True)
class ContinuousSOCContract:
    """An additive shifted-SOC contract carried by a saved-solution adapter.

    The generic solver continues to use physical battery kWh.  ``soc_min`` is
    subtracted only for this continuity ledger, matching E4's existing
    20%-reserve implementation without changing the shared cost/check modules.
    ``terminal_charges`` must be the rows saved by the experiment scorer.
    """

    contract_id: str
    soc_initial: float
    soc_min: float
    soc_max: float
    soc_final_minimum: float
    terminal_charges: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class DepotChargeLedgerEntry:
    """One charge between a certified trip and its following departure."""

    after_route_id: str
    before_route_id: str | None
    physical_vehicle_id: str
    station_id: str
    relation: str
    energy_kwh: float
    start_battery_kwh: float
    end_battery_kwh: float
    charge_start_second: float
    charge_end_second: float
    next_departure_second: float
    charge_day_offset: int
    saved_charge_start_second: float
    saved_charge_end_second: float
    electricity_cost_cny: float
    emissions_kg: float


@dataclass(frozen=True)
class MultiTripCertificate:
    contract_id: str
    status: str
    vehicle_counts: dict[str, int]
    trips: tuple[ScheduledTrip, ...]
    recharge_mode: str
    depot_charge_power_kw: float
    first_trip_charge_day_offset: int = STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET
    charging_curve_id: str = L100_CONTROL.curve_id
    charging_curve_parameter_sha256: str = L100_CONTROL.parameter_sha256
    battery_capacity_kwh: float | None = None
    charging_curve_physical_sha256: str | None = None
    initial_battery_kwh: float | None = None
    continuous_soc_contract_id: str | None = None
    soc_initial: float | None = None
    soc_min: float | None = None
    soc_max: float | None = None
    soc_final_minimum: float | None = None
    depot_charge_ledger: tuple[DepotChargeLedgerEntry, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def multitrip_certificate_from_dict(
    payload: Mapping[str, Any],
) -> MultiTripCertificate:
    """Load historical V2 and current curve-aware certificate JSON."""

    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={
            str(key): int(value)
            for key, value in dict(payload["vehicle_counts"]).items()
        },
        trips=tuple(
            ScheduledTrip(**dict(row)) for row in payload.get("trips", ())
        ),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(
            payload.get(
                "first_trip_charge_day_offset",
                STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
            )
        ),
        charging_curve_id=str(
            payload.get("charging_curve_id", L100_CONTROL.curve_id)
        ),
        charging_curve_parameter_sha256=str(
            payload.get(
                "charging_curve_parameter_sha256",
                L100_CONTROL.parameter_sha256,
            )
        ),
        battery_capacity_kwh=(
            None
            if payload.get("battery_capacity_kwh") is None
            else float(payload["battery_capacity_kwh"])
        ),
        charging_curve_physical_sha256=(
            None
            if payload.get("charging_curve_physical_sha256") is None
            else str(payload["charging_curve_physical_sha256"])
        ),
        initial_battery_kwh=(
            None
            if payload.get("initial_battery_kwh") is None
            else float(payload["initial_battery_kwh"])
        ),
        continuous_soc_contract_id=(
            None
            if payload.get("continuous_soc_contract_id") is None
            else str(payload["continuous_soc_contract_id"])
        ),
        soc_initial=(
            None
            if payload.get("soc_initial") is None
            else float(payload["soc_initial"])
        ),
        soc_min=(
            None if payload.get("soc_min") is None else float(payload["soc_min"])
        ),
        soc_max=(
            None if payload.get("soc_max") is None else float(payload["soc_max"])
        ),
        soc_final_minimum=(
            None
            if payload.get("soc_final_minimum") is None
            else float(payload["soc_final_minimum"])
        ),
        depot_charge_ledger=tuple(
            DepotChargeLedgerEntry(**dict(row))
            for row in payload.get("depot_charge_ledger", ())
        ),
    )


def _curve_for_prices(
    prices: PriceParameters | dict[str, Any] | Any,
    instance: Instance | None = None,
) -> PiecewiseChargingCurve:
    try:
        return curve_for_charging_node(
            prices,
            node_type="d",
            capacity_kwh=(
                _price(prices, "B_battery_kwh")
                if instance is None
                else instance.battery_capacity_kwh(
                    fallback=_price(prices, "B_battery_kwh"),
                )
            ),
            reference_power_kw=_price(prices, "depot_charge_power_kw"),
        )
    except ChargingCurveError as exc:
        raise ValueError(f"{NONLINEAR_CONTRACT_ID}: {exc}") from exc


def _certificate_curve(
    certificate: MultiTripCertificate,
    prices: PriceParameters | dict[str, Any] | Any,
    instance: Instance | None = None,
) -> PiecewiseChargingCurve:
    curve = _curve_for_prices(prices, instance)
    if certificate.contract_id == CONTRACT_ID:
        if curve.curve_id != L100_CONTROL.curve_id:
            raise ValueError(
                f"{NONLINEAR_CONTRACT_ID}: V2 certificates are linear-only"
            )
    elif certificate.contract_id != NONLINEAR_CONTRACT_ID:
        raise ValueError("unknown multi-trip contract")
    if certificate.charging_curve_id != curve.curve_id:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: certificate curve id disagrees with prices"
        )
    if certificate.charging_curve_parameter_sha256 != curve.parameter_sha256:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: certificate curve hash disagrees with prices"
        )
    if (
        certificate.contract_id == NONLINEAR_CONTRACT_ID
        or (
            instance is not None
            and instance.vehicle_parameters is not None
        )
        or certificate.battery_capacity_kwh is not None
        or certificate.charging_curve_physical_sha256 is not None
    ):
        if certificate.battery_capacity_kwh is None or (
            abs(
                float(certificate.battery_capacity_kwh)
                - curve.capacity_kwh
            )
            > _TOL
        ):
            raise ValueError(
                f"{NONLINEAR_CONTRACT_ID}: certificate battery capacity "
                "disagrees with the scaled curve"
            )
        if (
            certificate.charging_curve_physical_sha256
            != curve.physical_parameter_sha256
        ):
            raise ValueError(
                f"{NONLINEAR_CONTRACT_ID}: certificate physical curve hash "
                "disagrees with the scaled curve"
            )
    return curve


def _canonical_curve_energy(
    curve: PiecewiseChargingCurve,
    value: float,
    *,
    label: str,
) -> float:
    """Clamp floating-point dust while rejecting real battery-bound violations."""

    energy = float(value)
    if energy < -_TOL or energy > curve.capacity_kwh + _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: {label} lies outside battery bounds"
        )
    return min(curve.capacity_kwh, max(0.0, energy))


def _validate_action_curve_metadata(
    action: ChargingAction,
    *,
    start_energy_kwh: float,
    end_energy_kwh: float,
    curve: PiecewiseChargingCurve,
    require_explicit: bool,
) -> None:
    values = (
        action.start_energy_kwh,
        action.end_energy_kwh,
        action.charging_curve_id,
    )
    if not require_explicit and all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action has incomplete curve metadata"
        )
    if action.charging_curve_id != curve.curve_id:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action curve id disagrees"
        )
    expected_start = _canonical_curve_energy(
        curve,
        start_energy_kwh,
        label="expected charging start energy",
    )
    expected_end = _canonical_curve_energy(
        curve,
        end_energy_kwh,
        label="expected charging end energy",
    )
    actual_start = _canonical_curve_energy(
        curve,
        float(action.start_energy_kwh),
        label="recorded charging start energy",
    )
    actual_end = _canonical_curve_energy(
        curve,
        float(action.end_energy_kwh),
        label="recorded charging end energy",
    )
    if abs(actual_start - expected_start) > _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action start energy disagrees"
        )
    if abs(actual_end - expected_end) > _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action end energy disagrees"
        )
    duration = curve.duration_seconds(expected_start, expected_end)
    if abs(float(action.occupancy_minutes) * 60.0 - duration) > _TOL:
        raise ValueError(
            f"{NONLINEAR_CONTRACT_ID}: charging action duration disagrees with curve"
        )


def route_timing(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    charging_actions: list[ChargingAction] | None = None,
    validate_battery: bool = True,
    forced_departure_second: float | None = None,
    minimum_departure_second: float | None = None,
) -> TripTiming:
    """Compute one legal route-to-trip interval without changing route schema.

    The frozen route representation has no departure-time field.  We therefore
    choose a feasible clock that removes avoidable customer waiting.  This is
    deliberately one reproducible witness clock, not a proof that no other
    clock could make a fixed route set use fewer physical vehicles.
    """

    if len(route.node_sequence) < 2:
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} has no trip")
    if route.node_sequence[0] != route.home_depot_id or route.node_sequence[-1] != route.home_depot_id:
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} does not return to its home depot")
    nodes = instance.node_lookup
    if any(node_id not in nodes for node_id in route.node_sequence):
        raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} references an unknown node")
    route_actions = [
        action
        for action in (charging_actions or [])
        if action.vehicle_id == route.vehicle_id
    ]
    public_actions: dict[str, list[ChargingAction]] = {}
    for action in route_actions:
        station = nodes.get(action.station_id)
        if (
            station is None
            or station.node_type.lower() != "f"
            or action.station_id not in route.node_sequence
        ):
            continue
        if route.node_sequence.count(action.station_id) != 1:
            raise ValueError(
                f"{CONTRACT_ID}: route {route.vehicle_id} repeats public "
                "station without an occurrence index"
            )
        if int(action.charge_day_offset) != 0:
            raise ValueError(
                f"{CONTRACT_ID}: in-route public charging must use day 0"
            )
        public_actions.setdefault(action.station_id, []).append(action)
    for actions in public_actions.values():
        actions.sort(
            key=lambda action: (
                float(action.charge_start_second),
                float(action.occupancy_minutes),
            )
        )

    origin = nodes[route.home_depot_id]
    departure_floor = float(origin.ready_time) + float(origin.service_time)
    if minimum_departure_second is not None:
        requested_floor = float(minimum_departure_second)
        if not math.isfinite(requested_floor):
            raise ValueError(
                f"{CONTRACT_ID}: route {route.vehicle_id} has a non-finite "
                "minimum departure"
            )
        departure_floor = max(departure_floor, requested_floor)
    # A trip has no departure field in the frozen Route schema. Compute the
    # latest feasible origin service time by the standard backward time-window
    # recursion, then replay forward. The former "remove all waiting" shortcut
    # could push an early-due customer past its deadline on mixed-shift routes.
    if forced_departure_second is not None:
        depart = float(forced_departure_second)
        if not math.isfinite(depart):
            raise ValueError(
                f"{CONTRACT_ID}: route {route.vehicle_id} has a non-finite "
                "forced departure"
            )
        if depart < departure_floor - _TOL:
            raise ValueError(
                f"{CONTRACT_ID}: route {route.vehicle_id} departs before its "
                "minimum departure"
            )
        depot_charge_ends = [
            float(action.charge_start_second)
            + float(action.occupancy_minutes) * 60.0
            for action in route_actions
            if action.station_id == route.home_depot_id
            and int(action.charge_day_offset) == 0
        ]
        if depot_charge_ends and max(depot_charge_ends) > depart + _TOL:
            raise ValueError(
                f"{CONTRACT_ID}: route {route.vehicle_id} departs before its "
                "depot charge ends"
            )
    elif public_actions:
        # Existing public-charge clocks are part of the solution witness.
        # Keep their clocks fixed and verify them; do not move or recreate a
        # station action inside the certificate.  A same-day depot charge is
        # also part of that witness, so the route cannot depart before it ends.
        first_public_start = min(
            float(action.charge_start_second)
            for actions in public_actions.values()
            for action in actions
        )
        depot_charge_ends = [
            float(action.charge_start_second)
            + float(action.occupancy_minutes) * 60.0
            for action in route_actions
            if action.station_id == route.home_depot_id
            and int(action.charge_day_offset) == 0
            and float(action.charge_start_second)
            + float(action.occupancy_minutes) * 60.0
            <= first_public_start + _TOL
        ]
        depart = max(
            [
                departure_floor,
                *depot_charge_ends,
            ]
        )
    else:
        elapsed = float(origin.service_time)
        departure_candidates = [departure_floor]
        for from_id, to_id in zip(
            route.node_sequence,
            route.node_sequence[1:],
        ):
            _, travel, _ = instance.arc_metrics(
                from_id,
                to_id,
                route.vehicle_type,
                fallback_speed_mps=_price(prices, "v_speed_ms"),
            )
            elapsed += travel
            departure_candidates.append(
                float(nodes[to_id].ready_time) - elapsed
            )
            elapsed += float(nodes[to_id].service_time)
        preferred_departure = max(departure_candidates)

        latest_start = float(nodes[route.node_sequence[-1]].due_time)
        for index in range(len(route.node_sequence) - 2, -1, -1):
            node = nodes[route.node_sequence[index]]
            next_id = route.node_sequence[index + 1]
            _, travel, _ = instance.arc_metrics(
                route.node_sequence[index],
                next_id,
                route.vehicle_type,
                fallback_speed_mps=_price(prices, "v_speed_ms"),
            )
            latest_start = min(
                float(node.due_time),
                latest_start - float(node.service_time) - travel,
            )
        latest_departure = latest_start + float(origin.service_time)
        if latest_departure < departure_floor - _TOL:
            raise ValueError(
                f"{CONTRACT_ID}: route {route.vehicle_id} has no feasible "
                "departure time"
            )
        depart = min(preferred_departure, latest_departure)
    earliest_departure = depart
    loads = _arc_loads(route.node_sequence, nodes)
    energy = 0.0
    public_energy = 0.0
    required_departure: float | None = None
    for idx, (from_id, to_id) in enumerate(zip(route.node_sequence, route.node_sequence[1:])):
        _, travel, _ = instance.arc_metrics(
            from_id,
            to_id,
            route.vehicle_type,
            fallback_speed_mps=_price(prices, "v_speed_ms"),
        )
        arrive = depart + travel
        node = nodes[to_id]
        start = max(arrive, float(node.ready_time))
        if start > float(node.due_time) + 1e-6:
            raise ValueError(f"{CONTRACT_ID}: route {route.vehicle_id} misses {to_id}'s time window")
        if route.vehicle_type.lower() == "ev":
            energy += ev_instance_arc_energy_kwh(
                instance,
                from_id,
                to_id,
                loads[idx],
                prices,
            )
        station_actions = public_actions.get(to_id, [])
        if station_actions:
            previous_end = start
            for action in station_actions:
                action_start = float(action.charge_start_second)
                action_end = (
                    action_start
                    + float(action.occupancy_minutes) * 60.0
                )
                if action_start < previous_end - _TOL:
                    raise ValueError(
                        f"{CONTRACT_ID}: public charge for {route.vehicle_id} "
                        f"starts before arrival or a prior session ends"
                    )
                curve_state = charging_curve_for_action(
                    action,
                    instance,
                    prices,
                )
                if curve_state is None:
                    raise ValueError(
                        f"{CONTRACT_ID}: strict public charging requires "
                        "explicit nonlinear energy-state metadata"
                    )
                _, action_start_energy, _ = curve_state
                candidate_departure = (
                    action_start_energy + energy - public_energy
                )
                if required_departure is None:
                    required_departure = candidate_departure
                elif abs(required_departure - candidate_departure) > _TOL:
                    raise ValueError(
                        f"{CONTRACT_ID}: public charging SOC metadata does "
                        "not close to one departure battery"
                    )
                public_energy += float(action.energy_kwh)
                previous_end = action_end
            depart = previous_end
        else:
            depart = start + float(node.service_time)
    battery = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    if route.vehicle_type.lower() == "ev":
        if not validate_battery:
            return TripTiming(
                route.vehicle_id,
                route.vehicle_type.lower(),
                route.home_depot_id,
                earliest_departure,
                depart,
                energy,
                public_energy,
                required_departure,
            )
        if required_departure is None:
            if energy > battery + 1e-6:
                raise ValueError(
                    f"{CONTRACT_ID}: route {route.vehicle_id} exceeds one "
                    "full battery"
                )
        else:
            if (
                required_departure < -_TOL
                or required_departure > battery + _TOL
            ):
                raise ValueError(
                    f"{CONTRACT_ID}: route {route.vehicle_id} has an invalid "
                    "public-charge departure battery"
                )
            route_battery = required_departure
            for idx, (from_id, to_id) in enumerate(
                zip(route.node_sequence, route.node_sequence[1:])
            ):
                route_battery -= ev_instance_arc_energy_kwh(
                    instance,
                    from_id,
                    to_id,
                    loads[idx],
                    prices,
                )
                if route_battery < -_TOL:
                    raise ValueError(
                        f"{CONTRACT_ID}: route {route.vehicle_id} runs out "
                        f"of battery before {to_id}"
                    )
                for action in public_actions.get(to_id, []):
                    if (
                        action.start_energy_kwh is None
                        or action.end_energy_kwh is None
                    ):
                        raise ValueError(
                            f"{CONTRACT_ID}: public charging has incomplete "
                            "energy-state metadata"
                        )
                    if (
                        abs(
                            route_battery
                            - float(action.start_energy_kwh)
                        )
                        > _TOL
                    ):
                        raise ValueError(
                            f"{CONTRACT_ID}: public charging SOC start does "
                            "not match the route battery"
                        )
                    route_battery += float(action.energy_kwh)
                    if route_battery > battery + _TOL:
                        raise ValueError(
                            f"{CONTRACT_ID}: public charging exceeds battery "
                            "capacity"
                        )
            expected_end = required_departure + public_energy - energy
            if abs(route_battery - expected_end) > _TOL:
                raise ValueError(
                    f"{CONTRACT_ID}: public charging battery ledger does not "
                    "close"
                )
    return TripTiming(
        route.vehicle_id,
        route.vehicle_type.lower(),
        route.home_depot_id,
        earliest_departure,
        depart,
        energy,
        public_energy,
        required_departure,
    )


def validate_depot_charge_window_mode(mode: str) -> str:
    """Validate and return one of the three registered depot-window modes."""

    if mode not in DEPOT_CHARGE_WINDOW_MODES:
        raise ValueError(
            "unknown depot charging window mode: "
            f"{mode!r}; expected one of "
            f"{sorted(DEPOT_CHARGE_WINDOW_MODES)}"
        )
    return mode


def certified_depot_charge_window(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    occupancy_seconds: float,
    mode: str = DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    charging_actions: list[ChargingAction] | None = None,
) -> tuple[float, float, int]:
    """Return a depot window from the authoritative route clock.

    The returned tuple is ``(earliest, latest, fixed_day_offset)``.  For
    ``full_gap`` the day offset is only a fallback for callers that do not
    provide a day-keyed calendar; calendar-aware callers may split the window
    over actual day offsets themselves.
    """

    validate_depot_charge_window_mode(mode)
    if float(occupancy_seconds) < 0.0:
        raise ValueError("depot charging occupancy must be non-negative")
    timing = route_timing(
        route,
        instance,
        prices,
        charging_actions=charging_actions,
        validate_battery=False,
    )
    # The protected checker anchors depot charging to this same route clock.
    # Keep route_timing for the return-side gap, but do not use its witness
    # departure as the charging-window upper bound.
    departure_second = float(route_departure_second(route, instance, prices))
    occupancy = float(occupancy_seconds)
    if mode == "prev_night":
        return 0.0, STATIC_PREHORIZON_SECONDS - occupancy, -1
    if mode == "same_day_predeparture":
        return 0.0, departure_second - occupancy, 0

    next_departure = (
        departure_second + STATIC_PREHORIZON_SECONDS
    )
    while next_departure <= float(timing.return_second) + _TOL:
        next_departure += STATIC_PREHORIZON_SECONDS
    return (
        float(timing.return_second),
        next_departure - occupancy,
        0,
    )


def select_certified_depot_charge_start(
    action: ChargingAction,
    earliest_second: float,
    latest_second: float,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    base_profile: list[dict[str, Any]],
    *,
    mode: str,
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    timing_contexts: ChargeTimingContexts | None = None,
) -> tuple[float, int]:
    """Choose one actual-day slot inside a certified depot window.

    ``charge_start_second`` remains local to the selected calendar day and the
    returned offset records that day relative to the route day.  This is the
    only generator-side bridge from the certificate window to the existing
    charging-action schema; prices and carbon rows are never synthesized.
    """

    validate_depot_charge_window_mode(mode)
    validate_charge_timing_policy(charge_timing_policy)
    earliest = float(earliest_second)
    latest = float(latest_second)
    occupancy = float(action.occupancy_minutes) * 60.0
    if latest + _TOL < earliest:
        raise ValueError("no feasible depot charging window")

    if mode == "prev_night":
        offsets = (-1,)
    elif mode == "same_day_predeparture":
        offsets = (0,)
    elif carbon_profiles_by_day_offset is None:
        offsets = (0,)
    else:
        first = int(earliest // STATIC_PREHORIZON_SECONDS)
        last = int(latest // STATIC_PREHORIZON_SECONDS)
        offsets = tuple(range(first, last + 1))

    candidates: list[tuple[float, float, float, int]] = []
    for offset in offsets:
        day_start = float(offset) * STATIC_PREHORIZON_SECONDS
        local_earliest = max(0.0, earliest - day_start)
        local_latest = min(
            STATIC_PREHORIZON_SECONDS - occupancy,
            latest - day_start,
        )
        if local_latest + _TOL < local_earliest:
            continue
        if carbon_profiles_by_day_offset is None:
            profile = base_profile
        else:
            try:
                profile = carbon_profiles_by_day_offset[offset]
            except KeyError as exc:
                raise ValueError(
                    "missing registered carbon/price profile for depot "
                    f"day offset {offset}"
                ) from exc
        raw_profile = profile
        if timing_contexts is None:
            station_profile = time_profile_rows_for_node(
                instance,
                action.station_id,
                raw_profile,
            )
        else:
            timing_context = timing_contexts.for_profile(
                instance,
                raw_profile,
                prices,
            )
            station_profile = timing_context.profile_for(action.station_id).rows

        if charge_timing_policy == "carbon_min" and strategy == "legacy":
            local_start, gamma = _lowest_profile_slot_start(
                local_earliest,
                local_latest,
                station_profile,
            )
            score = float(gamma)
        else:
            local_action = replace(action, charge_start_second=local_earliest)
            local_start = select_charge_timing_start(
                local_action,
                earliest_start_second=local_earliest,
                latest_start_second=local_latest,
                instance=instance,
                carbon_profile=raw_profile,
                prices=prices,
                charge_timing_policy=charge_timing_policy,
                timing_contexts=timing_contexts,
            )
            shifted = replace(action, charge_start_second=local_start)
            score = charge_timing_objective_value(
                shifted,
                instance,
                raw_profile,
                prices,
                charge_timing_policy=charge_timing_policy,
                timing_contexts=timing_contexts,
            )
        absolute_start = day_start + float(local_start)
        candidates.append(
            (
                float(score),
                absolute_start,
                float(local_start),
                int(offset),
            )
        )

    if not candidates:
        raise ValueError("no feasible depot charging window on registered calendar days")
    if charge_timing_policy == "carbon_min":
        _, _, start, offset = min(
            candidates,
            key=lambda item: (item[0], item[2], item[3]),
        )
    else:
        _, _, start, offset = min(candidates, key=lambda item: item)
    return start, offset


def _lowest_profile_slot_start(
    earliest: float,
    latest: float,
    profile: list[dict[str, Any]],
) -> tuple[float, float]:
    candidates = [
        (
            float(row["actual_gco2_per_kwh"]),
            float(row["horizon_second_start"]),
        )
        for row in profile
        if earliest - _TOL <= float(row["horizon_second_start"]) <= latest + _TOL
    ]
    if not candidates:
        slot = min(
            max(0.0, float(earliest)),
            float(latest),
        )
        rows = profile or []
        if not rows:
            raise ValueError("carbon profile must be non-empty")
        wrapped = slot % STATIC_PREHORIZON_SECONDS
        row = min(
            rows,
            key=lambda item: abs(
                float(item["horizon_second_start"]) - wrapped
            ),
        )
        return slot, float(row["actual_gco2_per_kwh"])
    gamma, start = min(candidates, key=lambda item: (item[0], item[1]))
    return start, gamma


def _validate_continuous_soc_contract(
    contract: ContinuousSOCContract,
) -> None:
    values = (
        float(contract.soc_min),
        float(contract.soc_initial),
        float(contract.soc_final_minimum),
        float(contract.soc_max),
    )
    if not contract.contract_id:
        raise ValueError("continuous SOC contract id is empty")
    if not (0.0 <= values[0] <= values[1] <= values[3] <= 1.0):
        raise ValueError(
            f"{contract.contract_id}: require "
            "0 <= soc_min <= soc_initial <= soc_max <= 1"
        )
    if not (values[0] <= values[2] <= values[3]):
        raise ValueError(
            f"{contract.contract_id}: final SOC minimum is outside bounds"
        )


def _shifted_soc_energy(
    soc: float,
    soc_min: float,
    physical_capacity_kwh: float,
) -> float:
    return (float(soc) - float(soc_min)) * float(physical_capacity_kwh)


def _terminal_row_number(
    row: Mapping[str, Any],
    key: str,
    contract_id: str,
) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{contract_id}: terminal charge has invalid {key}"
        ) from exc


def _validate_continuous_soc_route_bounds(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    charging_actions: list[ChargingAction],
    *,
    start_battery_kwh: float,
    upper_battery_kwh: float,
    contract_id: str,
) -> None:
    nodes = instance.node_lookup
    loads = _arc_loads(route.node_sequence, nodes)
    actions_by_station: dict[str, list[ChargingAction]] = {}
    for action in charging_actions:
        if action.vehicle_id == route.vehicle_id:
            actions_by_station.setdefault(action.station_id, []).append(action)
    battery = float(start_battery_kwh)
    for index, (left, right) in enumerate(
        zip(route.node_sequence, route.node_sequence[1:])
    ):
        battery -= ev_instance_arc_energy_kwh(
            instance,
            left,
            right,
            loads[index],
            prices,
        )
        if battery < -_TOL:
            raise ValueError(
                f"{contract_id}: route {route.vehicle_id} falls below soc_min"
            )
        for action in actions_by_station.get(right, ()):
            battery += float(action.energy_kwh)
            if battery > upper_battery_kwh + _TOL:
                raise ValueError(
                    f"{contract_id}: route {route.vehicle_id} exceeds soc_max"
                )


def _attach_continuous_soc_ledger(
    certificate: MultiTripCertificate,
    routes: list[Route],
    contract: ContinuousSOCContract,
    charging_curve: PiecewiseChargingCurve,
) -> MultiTripCertificate:
    """Bind saved terminal rows to the certified trip chain without repricing."""

    physical_capacity = float(certificate.battery_capacity_kwh or 0.0)
    target = _shifted_soc_energy(
        contract.soc_final_minimum,
        contract.soc_min,
        physical_capacity,
    )
    trips = {trip.route_id: trip for trip in certificate.trips}
    route_lookup = {route.vehicle_id: route for route in routes}
    rows_by_route: dict[str, list[Mapping[str, Any]]] = {}
    for row in contract.terminal_charges:
        route_id = str(row.get("vehicle_id", ""))
        rows_by_route.setdefault(route_id, []).append(row)
    unknown = sorted(set(rows_by_route) - set(route_lookup))
    if unknown:
        raise ValueError(
            f"{contract.contract_id}: terminal charges reference unknown routes "
            f"{unknown}"
        )
    repeated = sorted(
        route_id for route_id, rows in rows_by_route.items() if len(rows) != 1
    )
    if repeated:
        raise ValueError(
            f"{contract.contract_id}: terminal charge is not unique for {repeated}"
        )

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    next_trip: dict[str, ScheduledTrip] = {}
    for chain in by_vehicle.values():
        ordered = sorted(chain, key=lambda item: item.trip_index)
        for previous, current in zip(ordered, ordered[1:]):
            next_trip[previous.route_id] = current

    ledger: list[DepotChargeLedgerEntry] = []
    for route_id, route in route_lookup.items():
        if route.vehicle_type.lower() != "ev":
            if route_id in rows_by_route:
                raise ValueError(
                    f"{contract.contract_id}: CV route {route_id} has a terminal charge"
                )
            continue
        trip = trips[route_id]
        end_battery = float(trip.end_battery_kwh or 0.0)
        expected_energy = max(0.0, target - end_battery)
        rows = rows_by_route.get(route_id, [])
        if expected_energy <= _TOL:
            if rows and abs(
                _terminal_row_number(
                    rows[0], "energy_kwh", contract.contract_id
                )
            ) > _TOL:
                raise ValueError(
                    f"{contract.contract_id}: route {route_id} has surplus "
                    "terminal energy"
                )
            continue
        if not rows:
            raise ValueError(
                f"{contract.contract_id}: route {route_id} is missing terminal charge"
            )
        row = rows[0]
        energy = _terminal_row_number(row, "energy_kwh", contract.contract_id)
        start_soc = _terminal_row_number(row, "start_soc", contract.contract_id)
        end_soc = _terminal_row_number(row, "end_soc", contract.contract_id)
        saved_start = _terminal_row_number(
            row, "start_second_absolute", contract.contract_id
        )
        saved_end = _terminal_row_number(
            row, "end_second_absolute", contract.contract_id
        )
        row_start_energy = _shifted_soc_energy(
            start_soc,
            contract.soc_min,
            physical_capacity,
        )
        row_end_energy = _shifted_soc_energy(
            end_soc,
            contract.soc_min,
            physical_capacity,
        )
        if abs(energy - expected_energy) > _TOL:
            raise ValueError(
                f"{contract.contract_id}: route {route_id} terminal energy "
                "does not restore the registered final SOC"
            )
        if (
            abs(row_start_energy - end_battery) > _TOL
            or abs(row_end_energy - (end_battery + energy)) > _TOL
            or end_soc + _TOL < contract.soc_final_minimum
        ):
            raise ValueError(
                f"{contract.contract_id}: route {route_id} terminal SOC "
                "does not close to the certified battery"
            )
        # E4's existing action builder tolerates round-off immediately below
        # the shifted 20% floor, then clamps that start to zero before asking
        # the curve for a duration.  Reproduce that boundary operation exactly.
        curve_start_energy = min(
            physical_capacity,
            max(0.0, row_start_energy),
        )
        curve_end_energy = min(
            physical_capacity,
            max(curve_start_energy, row_start_energy + energy),
        )
        expected_duration = charging_curve.duration_seconds(
            curve_start_energy,
            curve_end_energy,
        )
        if abs(saved_end - saved_start - expected_duration) > _TOL:
            raise ValueError(
                f"{contract.contract_id}: route {route_id} terminal duration "
                "disagrees with the charging curve"
            )
        station_id = str(row.get("station_id", ""))
        if station_id != route.home_depot_id:
            raise ValueError(
                f"{contract.contract_id}: route {route_id} terminal charge "
                "is not at its home depot"
            )

        following = next_trip.get(route_id)
        if following is None:
            actual_start = saved_start
            actual_end = saved_end
            next_departure = _terminal_row_number(
                row, "latest_second_absolute", contract.contract_id
            ) + expected_duration
            relation = "between_trip_next_day_cycle"
            before_route_id = None
            day_offset = int(row.get("day_offset", int(saved_start // 86_400.0)))
            if (
                actual_start < trip.return_second - _TOL
                or actual_end > next_departure + _TOL
            ):
                raise ValueError(
                    f"{contract.contract_id}: route {route_id} terminal charge "
                    "is outside its return-to-next-day window"
                )
        else:
            actual_start = float(trip.charge_start_second or 0.0)
            actual_end = float(trip.recharge_end_second)
            next_departure = float(following.departure_second)
            relation = "between_solution_trips"
            before_route_id = following.route_id
            day_offset = 0
            if (
                abs(float(trip.charge_energy_kwh or 0.0) - energy) > _TOL
                or actual_start < trip.return_second - _TOL
                or actual_end > next_departure + _TOL
            ):
                raise ValueError(
                    f"{contract.contract_id}: route {route_id} terminal charge "
                    "does not fit before its packed next trip"
                )
        ledger.append(
            DepotChargeLedgerEntry(
                after_route_id=route_id,
                before_route_id=before_route_id,
                physical_vehicle_id=trip.physical_vehicle_id,
                station_id=station_id,
                relation=relation,
                energy_kwh=energy,
                start_battery_kwh=(
                    0.0 if abs(end_battery) <= _TOL else end_battery
                ),
                end_battery_kwh=(
                    (0.0 if abs(end_battery) <= _TOL else end_battery)
                    + energy
                ),
                charge_start_second=actual_start,
                charge_end_second=actual_end,
                next_departure_second=next_departure,
                charge_day_offset=day_offset,
                saved_charge_start_second=saved_start,
                saved_charge_end_second=saved_end,
                electricity_cost_cny=_terminal_row_number(
                    row, "electricity_cost_cny", contract.contract_id
                ),
                emissions_kg=_terminal_row_number(
                    row, "emissions_kg", contract.contract_id
                ),
            )
        )
    if len(ledger) != len(contract.terminal_charges):
        raise ValueError(
            f"{contract.contract_id}: terminal charge count does not close"
        )
    return replace(
        certificate,
        depot_charge_ledger=tuple(ledger),
    )


def build_multitrip_certificate(
    routes: list[Route],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    recharge_mode: str = CHARGE_MODE_ON_DEMAND,
    initial_departure_battery_by_route: dict[str, float] | None = None,
    charging_actions: list[ChargingAction] | None = None,
    continuous_soc_contract: ContinuousSOCContract | None = None,
    minimum_departure_second_by_route: Mapping[str, float] | None = None,
) -> MultiTripCertificate:
    """Build a reproducible physical-vehicle schedule for one fixed route set.

    This is a *feasibility witness*, not a proof of the minimum vehicle count.
    It deliberately reads depot charging power from the same ``prices`` object
    used by the route checker. ``on_demand`` is the formal V2 rule: carry the
    battery across trips and add only the energy needed to make the next trip.
    ``partial`` remains a backward-compatible spelling for old diagnostic files.
    ``full`` is retained only for replaying the historical V1 audit rule.
    """

    if recharge_mode not in {CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND}:
        raise ValueError(f"unknown recharge_mode={recharge_mode!r}")
    depot_charge_power_kw = _price(prices, "depot_charge_power_kw")
    if depot_charge_power_kw <= 0:
        raise ValueError("depot_charge_power_kw must be positive")
    battery_kwh = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    charging_curve = _curve_for_prices(prices, instance)
    ledger_initial_battery = _price(prices, "initial_ev_battery_kwh")
    ledger_upper_battery = battery_kwh
    fixed_departure_battery_by_route: dict[str, float] = {}
    if continuous_soc_contract is not None:
        _validate_continuous_soc_contract(continuous_soc_contract)
        ledger_initial_battery = _shifted_soc_energy(
            continuous_soc_contract.soc_initial,
            continuous_soc_contract.soc_min,
            battery_kwh,
        )
        ledger_upper_battery = _shifted_soc_energy(
            continuous_soc_contract.soc_max,
            continuous_soc_contract.soc_min,
            battery_kwh,
        )
        fixed_departure_battery_by_route = {
            route.vehicle_id: ledger_initial_battery
            for route in routes
            if route.vehicle_type.lower() == "ev"
        }
    timings = [
        route_timing(
            route,
            instance,
            prices,
            charging_actions=charging_actions,
            minimum_departure_second=(
                None
                if minimum_departure_second_by_route is None
                else minimum_departure_second_by_route.get(route.vehicle_id)
            ),
        )
        for route in routes
    ]
    if fixed_departure_battery_by_route:
        fixed_timings: list[TripTiming] = []
        for timing in timings:
            fixed = fixed_departure_battery_by_route.get(timing.route_id)
            if fixed is None:
                fixed_timings.append(timing)
                continue
            if (
                timing.required_departure_battery_kwh is not None
                and abs(timing.required_departure_battery_kwh - fixed) > _TOL
            ):
                raise ValueError(
                    f"{continuous_soc_contract.contract_id}: route "
                    f"{timing.route_id} public-charge ledger does not depart "
                    "at the registered SOC"
                )
            fixed_timings.append(
                replace(timing, required_departure_battery_kwh=fixed)
            )
        timings = fixed_timings
        for route in routes:
            fixed = fixed_departure_battery_by_route.get(route.vehicle_id)
            if fixed is None:
                continue
            _validate_continuous_soc_route_bounds(
                route,
                instance,
                prices,
                list(charging_actions or ()),
                start_battery_kwh=fixed,
                upper_battery_kwh=ledger_upper_battery,
                contract_id=continuous_soc_contract.contract_id,
            )
    scheduled: list[ScheduledTrip] = []
    counts = {"cv": 0, "ev": 0}
    for (depot, vehicle_type) in sorted({(t.home_depot_id, t.vehicle_type) for t in timings}):
        group = sorted(
            (t for t in timings if t.home_depot_id == depot and t.vehicle_type == vehicle_type),
            key=lambda t: (t.earliest_departure_second, t.return_second, t.route_id),
        )
        if vehicle_type == "cv":
            group_trips, group_count = _schedule_cv_group(group, depot)
        else:
            group_trips, group_count = _schedule_ev_group(
                group,
                depot,
                battery_kwh=ledger_upper_battery,
                charging_curve=charging_curve,
                recharge_mode=recharge_mode,
                initial_departure_battery_by_route=initial_departure_battery_by_route or {},
            )
        scheduled.extend(group_trips)
        counts[vehicle_type] += group_count
    certificate = MultiTripCertificate(
        (
            CONTRACT_ID
            if charging_curve.curve_id == L100_CONTROL.curve_id
            else NONLINEAR_CONTRACT_ID
        ),
        "PASS",
        counts,
        tuple(sorted(scheduled, key=lambda x: x.route_id)),
        recharge_mode,
        depot_charge_power_kw,
        STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
        charging_curve.curve_id,
        charging_curve.parameter_sha256,
        battery_kwh,
        charging_curve.physical_parameter_sha256,
        ledger_initial_battery,
        (
            None
            if continuous_soc_contract is None
            else continuous_soc_contract.contract_id
        ),
        None if continuous_soc_contract is None else continuous_soc_contract.soc_initial,
        None if continuous_soc_contract is None else continuous_soc_contract.soc_min,
        None if continuous_soc_contract is None else continuous_soc_contract.soc_max,
        (
            None
            if continuous_soc_contract is None
            else continuous_soc_contract.soc_final_minimum
        ),
    )
    if continuous_soc_contract is not None:
        certificate = _attach_continuous_soc_ledger(
            certificate,
            routes,
            continuous_soc_contract,
            charging_curve,
        )
    validate_multitrip_certificate(
        certificate,
        routes,
        prices,
        instance=instance,
    )
    return certificate


@dataclass
class _EVVehicleState:
    local_id: int
    trip_index: int
    available_second: float
    battery_kwh: float
    previous_route_id: str | None


def _schedule_cv_group(group: list[TripTiming], depot: str) -> tuple[list[ScheduledTrip], int]:
    available: list[tuple[float, int, int]] = []
    next_local_id = 0
    scheduled: list[ScheduledTrip] = []
    for timing in group:
        if available and available[0][0] <= timing.earliest_departure_second + _TOL:
            _, local_id, trip_index = heapq.heappop(available)
            trip_index += 1
        else:
            next_local_id += 1
            local_id, trip_index = next_local_id, 1
        physical_id = f"CV_{depot}_{local_id}"
        heapq.heappush(available, (timing.return_second, local_id, trip_index))
        scheduled.append(ScheduledTrip(
            timing.route_id, physical_id, trip_index, "cv", depot,
            timing.earliest_departure_second, timing.return_second, timing.return_second,
            None, None,
        ))
    return scheduled, next_local_id


def _schedule_ev_group(
    group: list[TripTiming],
    depot: str,
    *,
    battery_kwh: float,
    charging_curve: PiecewiseChargingCurve,
    recharge_mode: str,
    initial_departure_battery_by_route: dict[str, float],
) -> tuple[list[ScheduledTrip], int]:
    """Greedily build one valid EV schedule, retaining the actual battery path."""

    states: list[_EVVehicleState] = []
    scheduled: dict[str, ScheduledTrip] = {}
    next_local_id = 0
    for timing in group:
        candidates: list[tuple[float, float, _EVVehicleState, float]] = []
        for state in states:
            gap_seconds = timing.earliest_departure_second - state.available_second
            if gap_seconds < -_TOL:
                continue
            fixed_departure = timing.required_departure_battery_kwh
            if fixed_departure is not None:
                maximum_departure = charging_curve.reachable_energy_kwh(
                    state.battery_kwh,
                    max(0.0, gap_seconds),
                )
                if (
                    state.battery_kwh > fixed_departure + _TOL
                    or maximum_departure + _TOL < fixed_departure
                ):
                    continue
                departure_battery = fixed_departure
                charge_energy = departure_battery - state.battery_kwh
            elif recharge_mode == CHARGE_MODE_FULL:
                # Under the V1 contract the previous trip was replenished to
                # full before the vehicle became available again.
                departure_battery = battery_kwh
                charge_energy = 0.0
            else:
                departure_battery = charging_curve.reachable_energy_kwh(
                    state.battery_kwh,
                    max(0.0, gap_seconds),
                )
                charge_energy = departure_battery - state.battery_kwh
            required_net_energy = (
                timing.drive_energy_kwh
                - timing.public_charge_energy_kwh
            )
            if departure_battery + _TOL < required_net_energy:
                continue
            candidates.append((departure_battery, -state.available_second, state, charge_energy))
        if candidates:
            _, _, state, charge_energy = max(candidates, key=lambda item: (item[0], item[1], -item[2].local_id))
            if recharge_mode in {CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND} and state.previous_route_id is not None:
                previous = scheduled[state.previous_route_id]
                charge_seconds = (
                    charging_curve.duration_seconds(
                        state.battery_kwh, state.battery_kwh + charge_energy
                    )
                    if charge_energy > _TOL
                    else 0.0
                )
                charge_start = timing.earliest_departure_second - charge_seconds
                scheduled[state.previous_route_id] = replace(
                    previous,
                    recharge_end_second=charge_start + charge_seconds,
                    charge_start_second=charge_start if charge_energy > _TOL else None,
                    charge_energy_kwh=charge_energy,
                )
            state.trip_index += 1
            start_battery = battery_kwh if recharge_mode == CHARGE_MODE_FULL else state.battery_kwh + charge_energy
        else:
            next_local_id += 1
            if timing.required_departure_battery_kwh is not None:
                start_battery = timing.required_departure_battery_kwh
            else:
                start_battery = (
                    battery_kwh
                    if recharge_mode == CHARGE_MODE_FULL
                    else float(
                        initial_departure_battery_by_route.get(
                            timing.route_id,
                            battery_kwh,
                        )
                    )
                )
            if start_battery > battery_kwh + _TOL:
                raise ValueError(f"{CONTRACT_ID}: route {timing.route_id} starts above battery capacity")
            if (
                start_battery
                + timing.public_charge_energy_kwh
                + _TOL
                < timing.drive_energy_kwh
            ):
                raise ValueError(f"{CONTRACT_ID}: route {timing.route_id} has insufficient first-trip departure battery")
            state = _EVVehicleState(next_local_id, 1, timing.earliest_departure_second, start_battery, None)
        end_battery = (
            start_battery
            + timing.public_charge_energy_kwh
            - timing.drive_energy_kwh
        )
        physical_id = f"EV_{depot}_{state.local_id}"
        charge_energy_after = (
            battery_kwh - end_battery
            if recharge_mode == CHARGE_MODE_FULL
            else 0.0
        )
        charge_seconds_after = (
            charging_curve.duration_seconds(end_battery, battery_kwh)
            if charge_energy_after > _TOL
            else 0.0
        )
        scheduled[timing.route_id] = ScheduledTrip(
            timing.route_id,
            physical_id,
            state.trip_index,
            "ev",
            depot,
            timing.earliest_departure_second,
            timing.return_second,
            timing.return_second + charge_seconds_after,
            start_battery,
            end_battery,
            timing.return_second if charge_energy_after > _TOL else None,
            charge_energy_after if charge_energy_after > _TOL else None,
            timing.public_charge_energy_kwh,
            timing.required_departure_battery_kwh,
        )
        state.available_second = timing.return_second + charge_seconds_after if recharge_mode == CHARGE_MODE_FULL else timing.return_second
        state.battery_kwh = battery_kwh if recharge_mode == CHARGE_MODE_FULL else end_battery
        state.previous_route_id = timing.route_id
        if state not in states:
            states.append(state)
    result = list(scheduled.values())
    if (
        recharge_mode in {CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND}
        and all(
            trip.fixed_departure_battery_kwh is None
            for trip in result
        )
    ):
        result = _minimize_ev_chain_charging(result, charging_curve)
    return result, next_local_id


def _minimize_ev_chain_charging(
    trips: list[ScheduledTrip],
    charging_curve: PiecewiseChargingCurve,
) -> list[ScheduledTrip]:
    """Remove surplus energy after max-charge feasibility packing.

    Backward recursion computes the least departure battery needed at every
    trip while retaining enough room to survive any later short charging gap.
    Total charged energy then equals driving energy plus the final residual.
    """

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    updated: dict[str, ScheduledTrip] = {}
    for chain in by_vehicle.values():
        ordered = sorted(chain, key=lambda item: item.trip_index)
        energies = [float(trip.start_battery_kwh or 0.0) - float(trip.end_battery_kwh or 0.0) for trip in ordered]
        gaps = [
            max(
                0.0,
                ordered[index + 1].departure_second
                - ordered[index].return_second,
            )
            for index in range(len(ordered) - 1)
        ]
        try:
            packed = pack_trip_chain(charging_curve, energies, gaps)
        except ChargingCurveError as exc:
            raise ValueError(
                f"{NONLINEAR_CONTRACT_ID}: packed EV chain cannot be supported"
            ) from exc
        for index, (trip, row) in enumerate(zip(ordered, packed, strict=True)):
            charge_start = (
                ordered[index + 1].departure_second
                - row.charge_duration_seconds
                if row.charge_energy_kwh > _TOL
                else None
            )
            recharge_end = (
                charge_start + row.charge_duration_seconds
                if charge_start is not None
                else trip.return_second
            )
            if (
                charge_start is not None
                and charge_start < trip.return_second - _TOL
            ):
                # ``pack_trip_chain`` can identify the required energy while
                # not being able to place that energy inside the actual gap.
                # Keep the already feasible greedy ledger in that case; it
                # carries more battery into the trip instead of moving charge
                # into the preceding outside interval.
                return trips
            updated[trip.route_id] = replace(
                trip,
                start_battery_kwh=row.departure_energy_kwh,
                end_battery_kwh=row.return_energy_kwh,
                charge_energy_kwh=(
                    row.charge_energy_kwh
                    if row.charge_energy_kwh > _TOL
                    else None
                ),
                charge_start_second=charge_start,
                recharge_end_second=recharge_end,
            )
    return [updated[trip.route_id] for trip in trips]


def _continuous_soc_battery_upper(
    certificate: MultiTripCertificate,
    physical_capacity_kwh: float,
) -> float:
    if certificate.continuous_soc_contract_id is None:
        if certificate.depot_charge_ledger:
            raise ValueError(
                f"{CONTRACT_ID}: depot charge ledger has no continuous SOC contract"
            )
        return physical_capacity_kwh
    fields = (
        certificate.soc_initial,
        certificate.soc_min,
        certificate.soc_max,
        certificate.soc_final_minimum,
        certificate.initial_battery_kwh,
    )
    if any(value is None for value in fields):
        raise ValueError(
            f"{certificate.continuous_soc_contract_id}: incomplete SOC contract"
        )
    contract = ContinuousSOCContract(
        certificate.continuous_soc_contract_id,
        float(certificate.soc_initial),
        float(certificate.soc_min),
        float(certificate.soc_max),
        float(certificate.soc_final_minimum),
        (),
    )
    _validate_continuous_soc_contract(contract)
    expected_initial = _shifted_soc_energy(
        contract.soc_initial,
        contract.soc_min,
        physical_capacity_kwh,
    )
    if abs(float(certificate.initial_battery_kwh) - expected_initial) > _TOL:
        raise ValueError(
            f"{contract.contract_id}: initial battery disagrees with registered SOC"
        )
    return _shifted_soc_energy(
        contract.soc_max,
        contract.soc_min,
        physical_capacity_kwh,
    )


def _validate_depot_charge_ledger(
    certificate: MultiTripCertificate,
    charging_curve: PiecewiseChargingCurve,
) -> None:
    if certificate.continuous_soc_contract_id is None:
        return
    trips = {trip.route_id: trip for trip in certificate.trips}
    if len(certificate.depot_charge_ledger) != len(
        {entry.after_route_id for entry in certificate.depot_charge_ledger}
    ):
        raise ValueError(
            f"{certificate.continuous_soc_contract_id}: duplicate depot ledger route"
        )
    for entry in certificate.depot_charge_ledger:
        trip = trips.get(entry.after_route_id)
        if trip is None or trip.vehicle_type != "ev":
            raise ValueError(
                f"{certificate.continuous_soc_contract_id}: depot ledger is detached"
            )
        if (
            entry.physical_vehicle_id != trip.physical_vehicle_id
            or entry.station_id != trip.home_depot_id
        ):
            raise ValueError(
                f"{certificate.continuous_soc_contract_id}: depot ledger binding drifted"
            )
        start = float(entry.start_battery_kwh)
        end = float(entry.end_battery_kwh)
        energy = float(entry.energy_kwh)
        if (
            energy <= _TOL
            or abs(start - float(trip.end_battery_kwh or 0.0)) > _TOL
            or abs(end - start - energy) > _TOL
        ):
            raise ValueError(
                f"{certificate.continuous_soc_contract_id}: depot ledger energy is discontinuous"
            )
        duration = charging_curve.duration_seconds(start, end)
        if abs(
            float(entry.charge_end_second)
            - float(entry.charge_start_second)
            - duration
        ) > _TOL:
            raise ValueError(
                f"{certificate.continuous_soc_contract_id}: depot ledger duration drifted"
            )
        if (
            float(entry.charge_start_second) < trip.return_second - _TOL
            or float(entry.charge_end_second)
            > float(entry.next_departure_second) + _TOL
        ):
            raise ValueError(
                f"{certificate.continuous_soc_contract_id}: depot ledger leaves its trip gap"
            )
        if entry.relation == "between_solution_trips":
            following = trips.get(str(entry.before_route_id))
            if (
                following is None
                or following.physical_vehicle_id != trip.physical_vehicle_id
                or following.trip_index != trip.trip_index + 1
                or abs(
                    float(entry.next_departure_second)
                    - float(following.departure_second)
                )
                > _TOL
                or abs(float(trip.charge_energy_kwh or 0.0) - energy) > _TOL
            ):
                raise ValueError(
                    f"{certificate.continuous_soc_contract_id}: packed-trip depot ledger drifted"
                )
        elif entry.relation != "between_trip_next_day_cycle":
            raise ValueError(
                f"{certificate.continuous_soc_contract_id}: unknown depot ledger relation"
            )


def validate_multitrip_certificate(
    certificate: MultiTripCertificate,
    routes: list[Route],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    instance: Instance | None = None,
) -> None:
    charging_curve = _certificate_curve(certificate, prices, instance)
    battery_kwh = (
        _price(prices, "B_battery_kwh")
        if instance is None
        else instance.battery_capacity_kwh(
            fallback=_price(prices, "B_battery_kwh"),
        )
    )
    ledger_battery_upper = _continuous_soc_battery_upper(
        certificate,
        battery_kwh,
    )
    if certificate.recharge_mode not in {CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL, CHARGE_MODE_ON_DEMAND}:
        raise ValueError(f"{CONTRACT_ID}: unknown recharge mode")
    expected_power_kw = _price(prices, "depot_charge_power_kw")
    if certificate.depot_charge_power_kw <= _TOL:
        raise ValueError(f"{CONTRACT_ID}: depot charge power must be positive")
    if abs(certificate.depot_charge_power_kw - expected_power_kw) > _TOL:
        raise ValueError(f"{CONTRACT_ID}: certificate depot charge power disagrees with prices")
    if len(certificate.trips) != len(routes) or {trip.route_id for trip in certificate.trips} != {route.vehicle_id for route in routes}:
        raise ValueError(f"{CONTRACT_ID}: certificate does not cover every route exactly once")
    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    for vehicle_id, trips in by_vehicle.items():
        ordered = sorted(trips, key=lambda trip: trip.trip_index)
        if [trip.trip_index for trip in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError(f"{CONTRACT_ID}: {vehicle_id} has a broken trip sequence")
        if len({(trip.home_depot_id, trip.vehicle_type) for trip in ordered}) != 1:
            raise ValueError(f"{CONTRACT_ID}: {vehicle_id} changes depot or vehicle type")
        for previous, current in zip(ordered, ordered[1:]):
            if current.departure_second + 1e-6 < previous.recharge_end_second:
                raise ValueError(
                    f"{CONTRACT_ID}: {vehicle_id} has adjacent-trip overlap "
                    "or insufficient turnaround"
                )
            if current.vehicle_type == "ev":
                if (
                    previous.charge_start_second is not None
                    and previous.charge_start_second
                    < previous.return_second - _TOL
                ):
                    raise ValueError(
                        f"{CONTRACT_ID}: {vehicle_id} charges before the "
                        "previous trip returns"
                    )
                if certificate.recharge_mode == CHARGE_MODE_FULL:
                    if abs(float(current.start_battery_kwh or 0.0) - battery_kwh) > _TOL:
                        raise ValueError(f"{CONTRACT_ID}: {vehicle_id} does not depart full")
                elif abs(float(current.start_battery_kwh or 0.0) - (float(previous.end_battery_kwh or 0.0) + float(previous.charge_energy_kwh or 0.0))) > _TOL:
                    raise ValueError(f"{CONTRACT_ID}: {vehicle_id} battery ledger is discontinuous")
        if ordered and ordered[0].vehicle_type == "ev":
            first_start = float(ordered[0].start_battery_kwh or 0.0)
            if certificate.recharge_mode == CHARGE_MODE_FULL and abs(first_start - battery_kwh) > _TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} first trip does not depart full")
            if certificate.recharge_mode != CHARGE_MODE_FULL and not (-_TOL <= first_start <= battery_kwh + _TOL):
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} first-trip departure battery is outside capacity")
        for trip in ordered:
            if trip.vehicle_type != "ev":
                continue
            start_battery = float(trip.start_battery_kwh or 0.0)
            end_battery = float(trip.end_battery_kwh or 0.0)
            if end_battery < -_TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} has negative battery")
            if end_battery > ledger_battery_upper + _TOL:
                raise ValueError(
                    f"{CONTRACT_ID}: {vehicle_id} returns above battery capacity"
                )
            if start_battery > ledger_battery_upper + _TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} exceeds battery capacity at departure")
            if (
                trip.fixed_departure_battery_kwh is not None
                and abs(
                    start_battery
                    - float(trip.fixed_departure_battery_kwh)
                )
                > _TOL
            ):
                raise ValueError(
                    f"{CONTRACT_ID}: {vehicle_id} public-charge departure "
                    "battery is not preserved"
                )
            if float(trip.in_route_charge_energy_kwh) < -_TOL:
                raise ValueError(
                    f"{CONTRACT_ID}: {vehicle_id} has negative in-route charge"
                )
            energy = float(trip.charge_energy_kwh or 0.0)
            if certificate.recharge_mode == CHARGE_MODE_FULL:
                needed = battery_kwh - end_battery
                if abs(energy - needed) > _TOL:
                    raise ValueError(f"{CONTRACT_ID}: {vehicle_id} full recharge does not replenish used energy")
            elif end_battery + energy > ledger_battery_upper + _TOL:
                raise ValueError(f"{CONTRACT_ID}: {vehicle_id} partial recharge exceeds battery capacity")
            if energy > _TOL:
                if trip.charge_start_second is None:
                    raise ValueError(f"{CONTRACT_ID}: {vehicle_id} charge has no start time")
                start_energy = min(
                    charging_curve.capacity_kwh,
                    max(0.0, float(trip.end_battery_kwh or 0.0)),
                )
                end_energy = min(
                    charging_curve.capacity_kwh,
                    max(0.0, start_energy + energy),
                )
                expected_end = (
                    float(trip.charge_start_second)
                    + charging_curve.duration_seconds(
                        start_energy, end_energy
                    )
                )
                if abs(expected_end - trip.recharge_end_second) > _TOL:
                    raise ValueError(
                        f"{NONLINEAR_CONTRACT_ID}: {vehicle_id} charge duration "
                        "disagrees with charging curve"
                    )
    _validate_depot_charge_ledger(certificate, charging_curve)


def strict_multitrip_violations(
    routes: list[Route],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    recharge_mode: str = CHARGE_MODE_ON_DEMAND,
) -> list[str]:
    """Return new-contract failures without changing the legacy checker."""

    try:
        certificate = build_multitrip_certificate(routes, instance, prices, recharge_mode=recharge_mode)
    except ValueError as exc:
        return [str(exc)]
    failures: list[str] = []
    if instance.num_cv is not None and certificate.vehicle_counts["cv"] > int(instance.num_cv):
        failures.append(f"{CONTRACT_ID}: needs {certificate.vehicle_counts['cv']} CV but cap is {instance.num_cv}")
    if instance.num_ev is not None and certificate.vehicle_counts["ev"] > int(instance.num_ev):
        failures.append(f"{CONTRACT_ID}: needs {certificate.vehicle_counts['ev']} EV but cap is {instance.num_ev}")
    return failures


def certificate_charging_actions(certificate: MultiTripCertificate) -> list[ChargingAction]:
    """Convert every between-trip V2 charge into the canonical cost/carbon ledger.

    The action is attached to the following trip id because it raises that
    trip's departure battery.  This helper does not mutate a search solution;
    the E3 runner must explicitly merge these actions before formal evidence.
    """

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    actions: list[ChargingAction] = []
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        for previous, current in zip(ordered, ordered[1:]):
            recorded_energy = float(previous.charge_energy_kwh or 0.0)
            if recorded_energy <= _TOL:
                continue
            if previous.charge_start_second is None:
                raise ValueError(f"{CONTRACT_ID}: between-trip charge has no start")
            start_energy = float(previous.end_battery_kwh or 0.0)
            end_energy = start_energy + recorded_energy
            actions.append(
                ChargingAction(
                    vehicle_id=current.route_id,
                    station_id=current.home_depot_id,
                    energy_kwh=recorded_energy,
                    occupancy_minutes=(
                        previous.recharge_end_second
                        - float(previous.charge_start_second)
                    )
                    / 60.0,
                    charge_start_second=float(previous.charge_start_second),
                    start_energy_kwh=start_energy,
                    end_energy_kwh=end_energy,
                    charging_curve_id=certificate.charging_curve_id,
                )
            )
    return actions


def prepare_multitrip_solution(
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    continuous_soc_contract: ContinuousSOCContract | None = None,
    depot_charge_window_mode: str = "prev_night",
    minimum_departure_second_by_route: Mapping[str, float] | None = None,
) -> tuple[Solution, MultiTripCertificate]:
    """Attach the V2 physical schedule and its real charging ledger.

    Legacy route ids are replaced by the physical-vehicle/trip ids certified
    here. First trips keep their existing depot precharge. Later trips replace
    the legacy route-level precharge with exactly the between-trip energy from
    the V2 battery chain. Public-station actions are never dropped; V2 stops
    earlier in ``route_timing`` if such a route is not yet supported.
    """

    validate_depot_charge_window_mode(depot_charge_window_mode)
    already_prepared = bool(solution.routes) and all(
        "#T" in route.vehicle_id
        and physical_vehicle_id(route.vehicle_id).startswith(("CV_", "EV_"))
        for route in solution.routes
    )
    if already_prepared and continuous_soc_contract is not None:
        raise ValueError(
            f"{continuous_soc_contract.contract_id}: repeated preparation must "
            "reuse the returned certificate because saved terminal rows use "
            "preparation-input route ids"
        )
    if already_prepared:
        certificate = _certificate_from_prepared_solution(
            solution,
            instance,
            prices,
            minimum_departure_second_by_route=(
                minimum_departure_second_by_route
            ),
        )
    else:
        certificate = None

    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    charging_curve = _curve_for_prices(prices, instance)
    inherited_value = _price(prices, "initial_ev_battery_kwh")
    if continuous_soc_contract is not None:
        _validate_continuous_soc_contract(continuous_soc_contract)
        inherited_value = _shifted_soc_energy(
            continuous_soc_contract.soc_initial,
            continuous_soc_contract.soc_min,
            battery_cap,
        )
    inherited = _canonical_curve_energy(
        charging_curve,
        inherited_value,
        label="initial EV battery",
    )
    initial_departure: dict[str, float] = {}
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            continue
        depot_energy = sum(
            float(action.energy_kwh)
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id and action.station_id == route.home_depot_id
        )
        initial_departure[route.vehicle_id] = min(
            battery_cap,
            inherited + depot_energy if already_prepared and depot_energy > _TOL else battery_cap,
        )

    if certificate is None:
        certificate = build_multitrip_certificate(
            list(solution.routes),
            instance,
            prices,
            recharge_mode=CHARGE_MODE_ON_DEMAND,
            initial_departure_battery_by_route=initial_departure,
            charging_actions=list(solution.charging_actions),
            continuous_soc_contract=continuous_soc_contract,
            minimum_departure_second_by_route=(
                minimum_departure_second_by_route
            ),
        )
        certificate = _reuse_existing_between_trip_times(
            certificate,
            solution,
            instance,
            prices,
        )
    scheduled_by_old_id = {trip.route_id: trip for trip in certificate.trips}
    id_map = {
        old_id: route_trip_vehicle_id(trip.physical_vehicle_id, trip.trip_index)
        for old_id, trip in scheduled_by_old_id.items()
    }
    prepared_routes = [replace(route, vehicle_id=id_map[route.vehicle_id]) for route in solution.routes]

    prepared_actions: list[ChargingAction] = []
    first_trip_depot_action: dict[str, ChargingAction] = {}
    for action in solution.charging_actions:
        trip = scheduled_by_old_id.get(action.vehicle_id)
        if trip is None:
            continue
        is_origin_depot = action.station_id == trip.home_depot_id
        if is_origin_depot and trip.trip_index > 1:
            continue
        if is_origin_depot and trip.trip_index == 1:
            first_trip_depot_action[trip.route_id] = action
            continue
        prepared_actions.append(replace(action, vehicle_id=id_map[action.vehicle_id]))

    prepared_first_trip_charge_day_offsets: set[int] = set()
    for trip in certificate.trips:
        if trip.vehicle_type != "ev" or trip.trip_index != 1:
            continue
        target_energy = _canonical_curve_energy(
            charging_curve,
            float(trip.start_battery_kwh or 0.0),
            label="first-trip departure energy",
        )
        energy = max(0.0, target_energy - inherited)
        if energy <= _TOL:
            continue
        duration = charging_curve.duration_seconds(inherited, target_energy)
        if depot_charge_window_mode == "same_day_predeparture":
            latest_start = float(trip.departure_second) - duration
            first_trip_charge_day_offset = 0
        else:
            latest_start = STATIC_PREHORIZON_SECONDS - duration
            first_trip_charge_day_offset = STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET
        if latest_start < -_TOL:
            raise ValueError(f"{CONTRACT_ID}: first-trip depot precharge exceeds the pre-horizon day")
        old_action = first_trip_depot_action.get(trip.route_id)
        old_start = (
            float(old_action.charge_start_second) % STATIC_PREHORIZON_SECONDS
            if old_action is not None and float(old_action.charge_start_second) >= 0.0
            else None
        )
        start = (
            old_start
            if old_start is not None
            and old_start <= latest_start + _TOL
            else latest_start
        )
        if depot_charge_window_mode == "full_gap" and old_action is not None:
            first_trip_charge_day_offset = int(old_action.charge_day_offset)
        prepared_first_trip_charge_day_offsets.add(first_trip_charge_day_offset)
        prepared_actions.append(
            ChargingAction(
                vehicle_id=id_map[trip.route_id],
                station_id=trip.home_depot_id,
                energy_kwh=energy,
                occupancy_minutes=duration / 60.0,
                charge_start_second=start,
                charge_day_offset=first_trip_charge_day_offset,
                start_energy_kwh=inherited,
                end_energy_kwh=target_energy,
                charging_curve_id=certificate.charging_curve_id,
            )
        )

    remapped_trips = tuple(
        replace(trip, route_id=id_map[trip.route_id])
        for trip in certificate.trips
    )
    remapped_ledger = tuple(
        replace(
            entry,
            after_route_id=id_map[entry.after_route_id],
            before_route_id=(
                None
                if entry.before_route_id is None
                else id_map[entry.before_route_id]
            ),
        )
        for entry in certificate.depot_charge_ledger
    )
    if len(prepared_first_trip_charge_day_offsets) > 1:
        raise ValueError(
            f"{CONTRACT_ID}: first-trip depot charges use inconsistent day offsets"
        )
    prepared_first_trip_charge_day_offset = next(
        iter(prepared_first_trip_charge_day_offsets),
        certificate.first_trip_charge_day_offset,
    )
    remapped_certificate = replace(
        certificate,
        trips=remapped_trips,
        depot_charge_ledger=remapped_ledger,
        first_trip_charge_day_offset=prepared_first_trip_charge_day_offset,
    )
    prepared_actions.extend(certificate_charging_actions(remapped_certificate))
    prepared_actions.sort(
        key=lambda action: (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
    )
    prepared = Solution(
        routes=prepared_routes,
        charging_actions=prepared_actions,
        cross_site_services=solution.cross_site_services,
    )
    return prepared, remapped_certificate


def _certificate_from_prepared_solution(
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    minimum_departure_second_by_route: Mapping[str, float] | None = None,
) -> MultiTripCertificate:
    power = _price(prices, "depot_charge_power_kw")
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    inherited = _price(prices, "initial_ev_battery_kwh")
    charging_curve = _curve_for_prices(prices, instance)
    require_explicit = charging_curve.curve_id != L100_CONTROL.curve_id
    actions: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        actions.setdefault(action.vehicle_id, []).append(action)
    by_vehicle: dict[str, list[Route]] = {}
    for route in solution.routes:
        by_vehicle.setdefault(physical_vehicle_id(route.vehicle_id), []).append(route)
    timings: dict[str, TripTiming] = {}
    for chain_routes in by_vehicle.values():
        previous_return: float | None = None
        for route in sorted(
            chain_routes,
            key=lambda item: int(item.vehicle_id.rsplit("#T", 1)[1]),
        ):
            departure_floor = (
                None
                if minimum_departure_second_by_route is None
                else minimum_departure_second_by_route.get(route.vehicle_id)
            )
            same_day_charge_ends = [
                float(action.charge_start_second)
                + float(action.occupancy_minutes) * 60.0
                for action in actions.get(route.vehicle_id, ())
                if action.station_id == route.home_depot_id
                and int(action.charge_day_offset) == 0
            ]
            origin = instance.node_lookup[route.home_depot_id]
            floors = [
                value
                for value in (
                    float(origin.ready_time) + float(origin.service_time),
                    departure_floor,
                    previous_return,
                    *same_day_charge_ends,
                )
                if value is not None
            ]
            timing = route_timing(
                route,
                instance,
                prices,
                charging_actions=list(solution.charging_actions),
                forced_departure_second=max(floors),
            )
            timings[route.vehicle_id] = timing
            previous_return = timing.return_second
    routes = {route.vehicle_id: route for route in solution.routes}
    scheduled: list[ScheduledTrip] = []
    counts = {"cv": 0, "ev": 0}
    first_trip_charge_day_offsets: set[int] = set()
    for physical_id, chain_routes in sorted(by_vehicle.items()):
        ordered = sorted(chain_routes, key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]))
        vehicle_type = ordered[0].vehicle_type.lower()
        counts[vehicle_type] += 1
        previous_end: float | None = None
        chain: list[ScheduledTrip] = []
        for position, route in enumerate(ordered):
            trip_index = int(route.vehicle_id.rsplit("#T", 1)[1])
            timing = timings[route.vehicle_id]
            depot_actions = [action for action in actions.get(route.vehicle_id, []) if action.station_id == route.home_depot_id]
            public_actions = [
                action
                for action in actions.get(route.vehicle_id, [])
                if action.station_id != route.home_depot_id
            ]
            depot_energy = sum(float(action.energy_kwh) for action in depot_actions)
            public_energy = sum(
                float(action.energy_kwh)
                for action in public_actions
            )
            if vehicle_type == "ev":
                start_battery = inherited + depot_energy if position == 0 else float(previous_end or 0.0) + depot_energy
                if (
                    start_battery > battery_cap + _TOL
                    or start_battery + public_energy + _TOL
                    < timing.drive_energy_kwh
                ):
                    raise ValueError(f"{CONTRACT_ID}: prepared route {route.vehicle_id} has a broken battery ledger")
                if (
                    timing.required_departure_battery_kwh is not None
                    and abs(
                        start_battery
                        - timing.required_departure_battery_kwh
                    )
                    > _TOL
                ):
                    raise ValueError(
                        f"{CONTRACT_ID}: prepared public-charge route "
                        f"{route.vehicle_id} has a shifted departure battery"
                    )
                end_battery = (
                    start_battery
                    + public_energy
                    - timing.drive_energy_kwh
                )
                if depot_energy > _TOL:
                    if position == 0:
                        first_trip_charge_day_offsets.update(
                            int(action.charge_day_offset)
                            for action in depot_actions
                        )
                    if require_explicit and len(depot_actions) != 1:
                        raise ValueError(
                            f"{NONLINEAR_CONTRACT_ID}: prepared route "
                            f"{route.vehicle_id} must have one explicit depot action"
                        )
                    action_start = inherited if position == 0 else float(previous_end or 0.0)
                    for action in depot_actions:
                        _validate_action_curve_metadata(
                            action,
                            start_energy_kwh=action_start,
                            end_energy_kwh=start_battery,
                            curve=charging_curve,
                            require_explicit=require_explicit,
                        )
            else:
                start_battery = end_battery = None
            chain.append(
                ScheduledTrip(
                    route.vehicle_id,
                    physical_id,
                    trip_index,
                    vehicle_type,
                    route.home_depot_id,
                    timing.earliest_departure_second,
                    timing.return_second,
                    timing.return_second,
                    start_battery,
                    end_battery,
                    in_route_charge_energy_kwh=public_energy,
                    fixed_departure_battery_kwh=(
                        timing.required_departure_battery_kwh
                    ),
                )
            )
            if position > 0 and vehicle_type == "ev" and depot_energy > _TOL:
                if len(depot_actions) != 1:
                    raise ValueError(f"{CONTRACT_ID}: prepared route {route.vehicle_id} must have one depot gap action")
                action = depot_actions[0]
                duration = float(action.occupancy_minutes) * 60.0
                previous = chain[-2]
                chain[-2] = replace(
                    previous,
                    charge_start_second=float(action.charge_start_second),
                    charge_energy_kwh=depot_energy,
                    recharge_end_second=float(action.charge_start_second) + duration,
                )
            previous_end = end_battery
        scheduled.extend(chain)
    if len(first_trip_charge_day_offsets) > 1:
        raise ValueError(
            f"{CONTRACT_ID}: prepared first-trip depot charges use "
            "inconsistent day offsets"
        )
    first_trip_charge_day_offset = next(
        iter(first_trip_charge_day_offsets),
        STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
    )
    certificate = MultiTripCertificate(
        (
            CONTRACT_ID
            if charging_curve.curve_id == L100_CONTROL.curve_id
            else NONLINEAR_CONTRACT_ID
        ),
        "PASS",
        counts,
        tuple(scheduled),
        CHARGE_MODE_ON_DEMAND,
        power,
        first_trip_charge_day_offset,
        charging_curve.curve_id,
        charging_curve.parameter_sha256,
        battery_cap,
        charging_curve.physical_parameter_sha256,
        inherited,
    )
    validate_multitrip_certificate(
        certificate,
        list(routes.values()),
        prices,
        instance=instance,
    )
    return certificate


def _reuse_existing_between_trip_times(
    certificate: MultiTripCertificate,
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> MultiTripCertificate:
    """Keep an already-valid aware/naive gap placement on repeated scoring."""

    charging_curve = _certificate_curve(certificate, prices, instance)
    require_explicit = charging_curve.curve_id != L100_CONTROL.curve_id
    actions_by_route: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        actions_by_route.setdefault(action.vehicle_id, []).append(action)
    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    replacements: dict[str, ScheduledTrip] = {}
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        for previous, current in zip(ordered, ordered[1:]):
            expected = float(previous.charge_energy_kwh or 0.0)
            if expected <= _TOL:
                continue
            depot_actions = [
                action
                for action in actions_by_route.get(current.route_id, [])
                if action.station_id == current.home_depot_id
            ]
            if len(depot_actions) != 1:
                continue
            action = depot_actions[0]
            if abs(float(action.energy_kwh) - expected) > _TOL:
                continue
            if require_explicit and (
                action.start_energy_kwh is None
                or action.end_energy_kwh is None
                or action.charging_curve_id is None
            ):
                continue
            _validate_action_curve_metadata(
                action,
                start_energy_kwh=float(previous.end_battery_kwh or 0.0),
                end_energy_kwh=(
                    float(previous.end_battery_kwh or 0.0) + expected
                ),
                curve=charging_curve,
                require_explicit=require_explicit,
            )
            duration = float(action.occupancy_minutes) * 60.0
            start = float(action.charge_start_second)
            end = start + duration
            if start < previous.return_second - _TOL or end > current.departure_second + _TOL:
                continue
            replacements[previous.route_id] = replace(
                previous,
                charge_start_second=start,
                recharge_end_second=end,
            )
    if not replacements:
        return certificate
    updated = replace(
        certificate,
        trips=tuple(replacements.get(trip.route_id, trip) for trip in certificate.trips),
    )
    validate_multitrip_certificate(
        updated,
        list(solution.routes),
        prices,
        instance=instance,
    )
    return updated


def reschedule_between_trip_charging(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    *,
    strategy: str,
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    intensity_field: str = "actual_gco2_per_kwh",
) -> Solution:
    """Move fixed charging energy within its legal gap without new route search.

    Historical callers pass one repeated daily profile and therefore retain the
    sealed behaviour.  Calendar-aware replays can instead provide one profile
    per ``charge_day_offset`` (for example ``-1`` for the preceding night and
    ``0`` for the operating day) and choose whether timing decisions use the
    forecast or actual carbon-intensity field.  Cost evaluation remains a
    separate concern, so a forecast-timed solution can still be settled against
    actual carbon intensity.
    """

    if strategy not in {"aware", "naive"}:
        raise ValueError(f"unknown between-trip charging strategy {strategy!r}")
    _certificate_curve(certificate, prices, instance)

    def profile_for(day_offset: int) -> list[dict[str, Any]]:
        if carbon_profiles_by_day_offset is None:
            return carbon_profile
        try:
            return carbon_profiles_by_day_offset[int(day_offset)]
        except KeyError as exc:
            raise ValueError(f"missing carbon profile for charge_day_offset={day_offset}") from exc

    by_vehicle: dict[str, list[ScheduledTrip]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    routes_by_id = {route.vehicle_id: route for route in solution.routes}
    selected_starts: dict[str, float] = {}
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        first = ordered[0]
        if first.vehicle_type == "ev":
            first_actions = [
                action
                for action in solution.charging_actions
                if action.vehicle_id == first.route_id and action.station_id == first.home_depot_id
            ]
            if len(first_actions) == 1 and float(first_actions[0].energy_kwh) > _TOL:
                action = first_actions[0]
                first_route = routes_by_id.get(first.route_id)
                if first_route is None:
                    raise ValueError(
                        f"{CONTRACT_ID}: certificate references a missing route"
                    )
                duration = float(action.occupancy_minutes) * 60.0
                earliest = 0.0
                day_offset = int(action.charge_day_offset)
                latest = min(
                    STATIC_PREHORIZON_SECONDS - duration,
                    float(first.departure_second)
                    - day_offset * STATIC_PREHORIZON_SECONDS
                    - duration,
                    route_departure_second(
                        first_route,
                        instance,
                        prices,
                    )
                    - day_offset * STATIC_PREHORIZON_SECONDS
                    - duration,
                )
                if latest < earliest - _TOL:
                    raise ValueError(
                        f"{CONTRACT_ID}: first-trip depot precharge has no "
                        "legal predeparture window"
                    )
                selected_starts[first.route_id] = (
                    earliest
                    if strategy == "naive"
                    else best_charging_action_start(
                        action,
                        earliest_start_second=earliest,
                        latest_start_second=latest,
                        instance=instance,
                        carbon_profile=profile_for(
                            day_offset
                        ),
                        prices=prices,
                        intensity_field=intensity_field,
                    )
                )
        for previous, current in zip(ordered, ordered[1:]):
            if float(previous.charge_energy_kwh or 0.0) <= _TOL:
                continue
            if previous.charge_start_second is None:
                raise ValueError(f"{CONTRACT_ID}: between-trip charge has no start")
            gap_actions = [
                action
                for action in solution.charging_actions
                if action.vehicle_id == current.route_id
                and action.station_id == current.home_depot_id
            ]
            if len(gap_actions) != 1:
                raise ValueError(
                    f"{CONTRACT_ID}: {current.route_id} has no unique gap action"
                )
            action = gap_actions[0]
            duration = float(action.occupancy_minutes) * 60.0
            earliest = float(previous.return_second)
            latest = float(current.departure_second) - duration
            if latest < earliest - _TOL:
                raise ValueError(f"{CONTRACT_ID}: no legal gap for {current.route_id}")
            selected_starts[current.route_id] = (
                earliest
                if strategy == "naive"
                else best_charging_action_start(
                    action,
                    earliest_start_second=earliest,
                    latest_start_second=latest,
                    instance=instance,
                    carbon_profile=profile_for(0),
                    prices=prices,
                    intensity_field=intensity_field,
                )
            )
    actions: list[ChargingAction] = []
    for action in solution.charging_actions:
        if action.vehicle_id in selected_starts and action.station_id in {
            trip.home_depot_id for trip in certificate.trips if trip.route_id == action.vehicle_id
        }:
            actions.append(replace(action, charge_start_second=selected_starts[action.vehicle_id]))
        else:
            actions.append(action)
    return replace(solution, charging_actions=actions)


def _lowest_carbon_gap_start(
    earliest: float,
    latest: float,
    duration: float,
    energy: float,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    *,
    intensity_field: str = "actual_gco2_per_kwh",
) -> float:
    """Legacy L100 timing helper retained until the NL3 dynamic migration.

    New static and multi-trip actions use :func:`best_charging_action_start`,
    which integrates their physical charging curve.  The dynamic continuation
    module still imports this historical uniform-rate helper; keeping it here
    preserves that sealed L100 path without pretending it supports nonlinear
    charging.
    """

    if not carbon_profile or latest <= earliest + _TOL:
        return earliest
    candidates = {earliest, latest}
    slot_seconds = 1800.0
    first_slot = int(earliest // slot_seconds) - 1
    last_slot = int((latest + duration) // slot_seconds) + 1
    for slot_index in range(first_slot, last_slot + 1):
        boundary = slot_index * slot_seconds
        for candidate in (boundary, boundary - duration):
            if earliest - _TOL <= candidate <= latest + _TOL:
                candidates.add(min(latest, max(earliest, candidate)))

    def emissions(start: float) -> float:
        total = 0.0
        for slot in charging_slot_breakdown(
            start,
            duration,
            energy,
            instance,
            n_slots=len(carbon_profile),
            cyclic=True,
        ):
            row = carbon_profile_row_for_slot(
                carbon_profile,
                slot.slot_index,
            )
            if intensity_field not in row:
                raise ValueError(
                    f"carbon profile is missing timing field "
                    f"{intensity_field!r}"
                )
            total += (
                slot.y_skt_kwh
                * float(row[intensity_field])
            )
        return total

    return min(candidates, key=lambda start: (emissions(start), start))
