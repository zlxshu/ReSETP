#!/usr/bin/env python3
"""Zero-search objective and full-solution checker audit for China81.

This script uses the sealed S4 representative witness as a positive control.
It independently rebuilds the objective from frozen matrices and parameters,
then injects one fault at a time into copies of the witness.  It never calls an
optimiser and never rewrites the sealed witness.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[3]
OUT = SCRIPT.parent
WITNESS = (
    REPO
    / "baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate"
    / "best_solution_witness_v2.json"
)
sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.check import (  # noqa: E402
    BATTERY,
    CAPACITY,
    CHARGING_POWER,
    CUSTOMER_COVERAGE,
    FLEET_SIZE,
    FLOW_BALANCE,
    ROUTE_STRUCTURE,
    STATION_CAPACITY,
    TIME_WINDOW,
    check_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.search.certificate_execution import (  # noqa: E402
    build_certificate_execution_ledger,
)
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    prepare_multitrip_solution,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


@dataclass(frozen=True)
class AuditRow:
    check_id: str
    lane: str
    severity: str
    status: str
    subject: str
    observed: str
    expected: str
    evidence: str
    impact: str


def read_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(value) for value in row["node_sequence"]],
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
                charge_day_offset=int(row.get("charge_day_offset", 0)),
                start_energy_kwh=(
                    None
                    if row.get("start_energy_kwh") is None
                    else float(row["start_energy_kwh"])
                ),
                end_energy_kwh=(
                    None
                    if row.get("end_energy_kwh") is None
                    else float(row["end_energy_kwh"])
                ),
                charging_curve_id=(
                    None
                    if row.get("charging_curve_id") is None
                    else str(row["charging_curve_id"])
                ),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fields: list[str],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def close(actual: float, expected: float) -> bool:
    return math.isclose(
        float(actual),
        float(expected),
        rel_tol=1.0e-11,
        abs_tol=1.0e-9,
    )


def _manual_arc_loads(
    sequence: list[str],
    nodes: dict[str, Node],
) -> list[float]:
    loads = [0.0] * max(0, len(sequence) - 1)
    remaining = 0.0
    for index in range(len(sequence) - 1, 0, -1):
        node = nodes[sequence[index]]
        if node.node_type.lower() == "c":
            remaining += float(node.demand)
        loads[index - 1] = remaining
    return loads


def _manual_route_physics(
    route: Route,
    instance: Instance,
    prices: Any,
) -> dict[str, float]:
    nodes = {node.node_id: node for node in instance.nodes}
    vehicle_type = route.vehicle_type.lower()
    vehicle = instance.vehicle_profile(vehicle_type)
    if vehicle is None:
        raise ValueError("China81 audit requires explicit vehicle profiles")
    profile = instance.road_profiles[vehicle_type]
    loads = _manual_arc_loads(route.node_sequence, nodes)
    distance = 0.0
    duration = 0.0
    fuel = 0.0
    ev_energy = 0.0
    for index, (left_id, right_id) in enumerate(
        zip(route.node_sequence, route.node_sequence[1:])
    ):
        left = instance.node_index[left_id]
        right = instance.node_index[right_id]
        distance_m = float(profile.distance_m[left][right])
        duration_s = float(profile.duration_s[left][right])
        sum_v2d = float(profile.sum_v2d_m3_s2[left][right])
        load_mass = (
            float(loads[index])
            * float(instance.demand_mass_per_unit_kg)
        )
        mechanical_j = (
            0.5
            * float(vehicle.drag_coefficient)
            * float(prices.rho_a)
            * float(vehicle.frontal_area_m2)
            * sum_v2d
            + (
                float(vehicle.curb_mass_kg) + load_mass
            )
            * float(prices.g0)
            * float(vehicle.rolling_resistance_coefficient)
            * distance_m
        )
        distance += distance_m
        duration += duration_s
        if vehicle_type == "cv":
            friction_kj = (
                float(vehicle.engine_friction_kj_per_rev_l)
                * float(vehicle.engine_speed_rev_per_s)
                * float(vehicle.engine_displacement_l)
                * duration_s
            )
            fuel += (
                float(prices.xi_fuel_air)
                / (
                    float(prices.kappa_heat)
                    * float(prices.psi_conv)
                )
                * (
                    friction_kj
                    + mechanical_j
                    / 1000.0
                    / (
                        float(prices.eta_diesel)
                        * float(prices.eta_tf)
                    )
                )
            )
        else:
            ev_energy += (
                float(vehicle.traction_energy_multiplier)
                * mechanical_j
                / 3_600_000.0
            )
    return {
        "distance_m": distance,
        "duration_s": duration,
        "fuel_liters": fuel,
        "ev_drive_kwh": ev_energy,
    }


def _manual_charge_phases(
    action: ChargingAction,
    instance: Instance,
    prices: Any,
) -> list[tuple[float, float, float]]:
    """Return absolute (start, end, power_kW) phases without cost.py."""

    nodes = {node.node_id: node for node in instance.nodes}
    node = nodes[action.station_id]
    reference_power = (
        float(prices.depot_charge_power_kw)
        if node.node_type.lower() == "d"
        else float(node.charge_power_kw)
    )
    start_energy = float(action.start_energy_kwh)
    end_energy = float(action.end_energy_kwh)
    capacity = instance.battery_capacity_kwh(
        fallback=float(prices.B_battery_kwh)
    )
    cursor = float(action.charge_start_second)
    phases: list[tuple[float, float, float]] = []
    for soc_left, soc_right, relative_power in zip(
        prices.charging_soc_breakpoints[:-1],
        prices.charging_soc_breakpoints[1:],
        prices.charging_relative_powers,
    ):
        energy_left = float(soc_left) * capacity
        energy_right = float(soc_right) * capacity
        overlap_left = max(start_energy, energy_left)
        overlap_right = min(end_energy, energy_right)
        if overlap_right <= overlap_left + 1.0e-12:
            continue
        power_kw = reference_power * float(relative_power)
        duration = (
            overlap_right - overlap_left
        ) / power_kw * 3600.0
        phases.append((cursor, cursor + duration, power_kw))
        cursor += duration
    return phases


def _manual_charge_settlement(
    action: ChargingAction,
    instance: Instance,
    time_profile: list[dict[str, Any]],
    prices: Any,
) -> dict[str, float]:
    nodes = {node.node_id: node for node in instance.nodes}
    node = nodes[action.station_id]
    rows = sorted(
        (
            row
            for row in time_profile
            if str(row["city"]).lower() == str(node.city).lower()
        ),
        key=lambda row: float(row["horizon_second_start"]),
    )
    if len(rows) != 48:
        raise ValueError(
            f"expected 48 rows for {node.city}, found {len(rows)}"
        )
    price_field = (
        "depot_energy_cny_per_kwh"
        if node.node_type.lower() == "d"
        else "public_total_cny_per_kwh"
    )
    energy = 0.0
    cost = 0.0
    emissions = 0.0
    duration = 0.0
    for phase_start, phase_end, power_kw in _manual_charge_phases(
        action,
        instance,
        prices,
    ):
        cursor = phase_start
        while cursor < phase_end - 1.0e-12:
            absolute_slot = math.floor(cursor / 1800.0)
            slot_end = (absolute_slot + 1) * 1800.0
            overlap_end = min(phase_end, slot_end)
            overlap = overlap_end - cursor
            slot_energy = power_kw * overlap / 3600.0
            row = rows[int(absolute_slot) % 48]
            energy += slot_energy
            duration += overlap
            cost += slot_energy * float(row[price_field])
            emissions += (
                slot_energy
                * float(row["actual_gco2_per_kwh"])
                / 1000.0
            )
            cursor = overlap_end
    return {
        "energy_kwh": energy,
        "duration_seconds": duration,
        "cost_elec": cost,
        "emissions_kg": emissions,
        "cost_occ": (
            0.0
            if node.node_type.lower() == "d"
            else float(action.occupancy_minutes)
            * float(prices.occupancy_fee)
        ),
    }


def independent_objective(
    solution: Solution,
    bundle: Any,
    *,
    carbon_quota_kg: float = 0.0,
) -> dict[str, float]:
    route_rows = [
        (
            route,
            _manual_route_physics(
                route,
                bundle.instance,
                bundle.prices,
            ),
        )
        for route in solution.routes
    ]
    charge_rows = [
        _manual_charge_settlement(
            action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        for action in solution.charging_actions
    ]
    distance_total = sum(row["distance_m"] for _, row in route_rows)
    fuel = sum(
        row["fuel_liters"]
        for route, row in route_rows
        if route.vehicle_type.lower() == "cv"
    )
    ev_drive = sum(
        row["ev_drive_kwh"]
        for route, row in route_rows
        if route.vehicle_type.lower() == "ev"
    )
    electricity = sum(row["energy_kwh"] for row in charge_rows)
    cost_fix = (
        len(solution.routes)
        * float(bundle.prices.vehicle_fixed_cost)
    )
    cost_km = sum(
        row["distance_m"]
        / 1000.0
        * float(
            bundle.instance.vehicle_profile(
                route.vehicle_type
            ).non_energy_distance_cost_per_km
        )
        for route, row in route_rows
    )
    cost_fuel = fuel * float(bundle.prices.diesel_price)
    cost_elec = sum(row["cost_elec"] for row in charge_rows)
    cost_occ = sum(row["cost_occ"] for row in charge_rows)
    cross_site_count = sum(
        bundle.customer_home_depot.get(node_id) is not None
        and bundle.customer_home_depot[node_id] != route.home_depot_id
        for route in solution.routes
        for node_id in route.node_sequence
    )
    cost_transship = (
        cross_site_count * float(bundle.prices.cross_site_cost)
    )
    e_cv = fuel * float(bundle.prices.diesel_ef)
    e_ev = sum(row["emissions_kg"] for row in charge_rows)
    e_total = e_cv + e_ev
    cost_carbon = (
        0.0
        if math.isinf(float(carbon_quota_kg))
        else (
            e_total - float(carbon_quota_kg)
        )
        * float(bundle.prices.carbon_price)
    )
    total = (
        cost_fix
        + cost_km
        + cost_fuel
        + cost_elec
        + cost_occ
        + cost_transship
        + cost_carbon
    )
    return {
        "total_cost": total,
        "cost_fix": cost_fix,
        "cost_km": cost_km,
        "cost_fuel": cost_fuel,
        "cost_elec": cost_elec,
        "cost_occ": cost_occ,
        "cost_transship": cost_transship,
        "cost_carbon": cost_carbon,
        "E_total": e_total,
        "E_cv_direct": e_cv,
        "E_ev_indirect": e_ev,
        "distance_total": distance_total,
        "fuel_liters": fuel,
        "electricity_kwh": electricity,
        "ev_drive_kwh": ev_drive,
    }


def instance_with_node(
    instance: Instance,
    node_id: str,
    **changes: Any,
) -> Instance:
    return replace(
        instance,
        nodes=[
            replace(node, **changes)
            if node.node_id == node_id
            else node
            for node in instance.nodes
        ],
    )


def violation_types(
    solution: Solution,
    instance: Instance,
    prices: Any,
) -> tuple[set[str], str | None]:
    try:
        violations = check_solution(solution, instance, prices)
    except Exception as exc:  # fail-closed is recorded, never hidden
        return set(), f"{type(exc).__name__}: {exc}"
    return {violation.type for violation in violations}, None


def main() -> int:
    payload = json.loads(WITNESS.read_text(encoding="utf-8"))
    solution = read_solution(payload)
    bundle = load_china81_bundle(
        REPO,
        str(payload["instance_id"]),
    )
    rows: list[AuditRow] = []

    production = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    independent = independent_objective(solution, bundle)
    objective_fields = sorted(independent)
    mismatches = {
        field: {
            "production": float(production[field]),
            "independent": float(independent[field]),
            "delta": float(production[field]) - float(independent[field]),
        }
        for field in objective_fields
        if not close(production[field], independent[field])
    }
    rows.append(
        AuditRow(
            "A5-01",
            "A5",
            "P0",
            "PASS" if not mismatches else "FAIL",
            "independent S4 objective decomposition",
            json.dumps(
                {
                    "fields": len(objective_fields),
                    "mismatches": mismatches,
                    "production_total": production["total_cost"],
                    "independent_total": independent["total_cost"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            "all objective components close independently",
            str(WITNESS.relative_to(REPO)),
            "A mismatch would invalidate the common exact scorer.",
        )
    )
    energy_gap = (
        independent["electricity_kwh"]
        - independent["ev_drive_kwh"]
    )
    rows.append(
        AuditRow(
            "A5-02",
            "A5",
            "P1",
            (
                "PASS"
                if close(
                    independent["electricity_kwh"],
                    independent["ev_drive_kwh"],
                )
                else "REVIEW"
            ),
            "sealed witness EV charge/traction energy closure",
            f"charged-drive={energy_gap:.12g} kWh",
            "zero for this all-depot, zero-initial-SOC witness",
            str(WITNESS.relative_to(REPO)),
            (
                "A nonzero value can be legal with terminal SOC, but must be "
                "explained by a complete battery ledger."
            ),
        )
    )

    baseline_types, baseline_error = violation_types(
        solution,
        bundle.instance,
        bundle.prices,
    )
    rows.append(
        AuditRow(
            "A6-BASE",
            "A6",
            "P0",
            (
                "PASS"
                if not baseline_types and baseline_error is None
                else "FAIL"
            ),
            "sealed full-solution positive control",
            json.dumps(
                {
                    "types": sorted(baseline_types),
                    "error": baseline_error,
                },
                ensure_ascii=False,
            ),
            "zero violations and no exception",
            str(WITNESS.relative_to(REPO)),
            "The positive control must pass before fault injection is meaningful.",
        )
    )

    customer_route_index = next(
        index
        for index, route in enumerate(solution.routes)
        if any(node.startswith("C") for node in route.node_sequence)
    )
    source_route = solution.routes[customer_route_index]
    source_customer = next(
        node
        for node in source_route.node_sequence
        if node.startswith("C")
    )
    ev_route = next(
        route
        for route in solution.routes
        if route.vehicle_type.lower() == "ev"
    )
    cv_routes = [
        route
        for route in solution.routes
        if route.vehicle_type.lower() == "cv"
    ]
    action = solution.charging_actions[0]
    stations = [
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "f"
    ]
    other_depot = next(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
        and node.node_id != source_route.home_depot_id
    )

    mutations: list[
        tuple[
            str,
            str,
            str,
            Solution,
            Instance,
            set[str],
            str,
        ]
    ] = []

    routes = list(solution.routes)
    missing_sequence = [
        node
        for node in source_route.node_sequence
        if node != source_customer
    ]
    routes[customer_route_index] = replace(
        source_route,
        node_sequence=missing_sequence,
    )
    mutations.append(
        (
            "A6-F01",
            "P0",
            "missing customer",
            replace(solution, routes=routes),
            bundle.instance,
            {CUSTOMER_COVERAGE},
            "coverage must be a full-solution constraint",
        )
    )

    routes = list(solution.routes)
    duplicate_sequence = list(source_route.node_sequence)
    duplicate_sequence.insert(2, source_customer)
    routes[customer_route_index] = replace(
        source_route,
        node_sequence=duplicate_sequence,
    )
    mutations.append(
        (
            "A6-F02",
            "P0",
            "duplicate customer",
            replace(solution, routes=routes),
            bundle.instance,
            {CUSTOMER_COVERAGE},
            "duplicate service must be rejected",
        )
    )

    routes = list(solution.routes)
    routes[customer_route_index] = replace(
        source_route,
        node_sequence=source_route.node_sequence[:-1],
    )
    mutations.append(
        (
            "A6-F03",
            "P0",
            "open route",
            replace(solution, routes=routes),
            bundle.instance,
            {FLOW_BALANCE},
            "each static trip must close at its home depot",
        )
    )

    routes = list(solution.routes)
    routes[customer_route_index] = replace(
        source_route,
        home_depot_id=other_depot,
    )
    mutations.append(
        (
            "A6-F04",
            "P0",
            "wrong home depot",
            replace(solution, routes=routes),
            bundle.instance,
            {FLOW_BALANCE},
            "route endpoints must bind to home_depot_id",
        )
    )

    mutations.append(
        (
            "A6-F05",
            "P0",
            "over-capacity demand",
            solution,
            instance_with_node(
                bundle.instance,
                source_customer,
                demand=1.0e9,
            ),
            {CAPACITY},
            "payload overflow must be rejected",
        )
    )
    mutations.append(
        (
            "A6-F06",
            "P0",
            "late customer",
            solution,
            instance_with_node(
                bundle.instance,
                source_customer,
                due_time=0.0,
            ),
            {TIME_WINDOW},
            "hard customer time-window violation must be rejected",
        )
    )

    mutations.append(
        (
            "A6-F07",
            "P0",
            "missing EV depot charge",
            replace(
                solution,
                charging_actions=[
                    item
                    for item in solution.charging_actions
                    if item.vehicle_id != ev_route.vehicle_id
                ],
            ),
            bundle.instance,
            {BATTERY},
            "battery underflow must be rejected",
        )
    )

    shortened = replace(
        action,
        occupancy_minutes=float(action.occupancy_minutes) / 2.0,
    )
    mutations.append(
        (
            "A6-F08",
            "P0",
            "charging duration inconsistent with curve",
            replace(
                solution,
                charging_actions=[
                    shortened if item == action else item
                    for item in solution.charging_actions
                ],
            ),
            bundle.instance,
            {CHARGING_POWER},
            "nonlinear action duration must bind to energy states",
        )
    )

    detached = replace(
        action,
        vehicle_id="DETACHED_AUDIT_VEHICLE",
        charge_day_offset=7,
    )
    mutations.append(
        (
            "A6-F09",
            "P0",
            "charging action detached from every route",
            replace(
                solution,
                charging_actions=[
                    *solution.charging_actions,
                    detached,
                ],
            ),
            bundle.instance,
            {ROUTE_STRUCTURE},
            "every action must bind to exactly one route/trip",
        )
    )

    cv_action = replace(
        action,
        vehicle_id=cv_routes[0].vehicle_id,
        station_id=cv_routes[0].home_depot_id,
        energy_kwh=0.0,
        occupancy_minutes=0.0,
        start_energy_kwh=0.0,
        end_energy_kwh=0.0,
        charge_day_offset=7,
    )
    mutations.append(
        (
            "A6-F10",
            "P0",
            "charging action attached to CV route",
            replace(
                solution,
                charging_actions=[
                    *solution.charging_actions,
                    cv_action,
                ],
            ),
            bundle.instance,
            {ROUTE_STRUCTURE},
            "combustion vehicles cannot own charging actions",
        )
    )

    customer_action = replace(
        action,
        vehicle_id=ev_route.vehicle_id,
        station_id=next(
            node
            for node in ev_route.node_sequence
            if node.startswith("C")
        ),
        energy_kwh=0.0,
        occupancy_minutes=0.0,
        start_energy_kwh=0.0,
        end_energy_kwh=0.0,
    )
    mutations.append(
        (
            "A6-F11",
            "P0",
            "charging action attached to customer node",
            replace(
                solution,
                charging_actions=[
                    *solution.charging_actions,
                    customer_action,
                ],
            ),
            bundle.instance,
            {ROUTE_STRUCTURE},
            "charging is allowed only at depot/station nodes",
        )
    )

    off_route_action = replace(
        action,
        vehicle_id=ev_route.vehicle_id,
        station_id=stations[0],
        energy_kwh=0.0,
        occupancy_minutes=0.0,
        start_energy_kwh=0.0,
        end_energy_kwh=0.0,
    )
    mutations.append(
        (
            "A6-F12",
            "P0",
            "charging action at station not visited by its route",
            replace(
                solution,
                charging_actions=[
                    *solution.charging_actions,
                    off_route_action,
                ],
            ),
            bundle.instance,
            {ROUTE_STRUCTURE},
            "a station action must bind to an actual route visit",
        )
    )

    shifted_state = replace(
        action,
        start_energy_kwh=10.0,
        end_energy_kwh=10.0 + float(action.energy_kwh),
    )
    mutations.append(
        (
            "A6-F13",
            "P0",
            "charging metadata start SOC differs from route battery",
            replace(
                solution,
                charging_actions=[
                    shifted_state if item == action else item
                    for item in solution.charging_actions
                ],
            ),
            bundle.instance,
            {BATTERY},
            "action start/end energy must bind to the route battery ledger",
        )
    )

    half_energy = float(action.energy_kwh) / 2.0
    half_duration = float(action.occupancy_minutes) / 2.0
    first_half = replace(
        action,
        energy_kwh=half_energy,
        occupancy_minutes=half_duration,
        start_energy_kwh=0.0,
        end_energy_kwh=half_energy,
    )
    duplicate_half = replace(first_half)
    mutations.append(
        (
            "A6-F14",
            "P0",
            "two simultaneous sessions for one vehicle at one charger",
            replace(
                solution,
                charging_actions=[
                    first_half,
                    duplicate_half,
                    *[
                        item
                        for item in solution.charging_actions
                        if item != action
                    ],
                ],
            ),
            bundle.instance,
            {STATION_CAPACITY},
            "one physical vehicle cannot occupy duplicate concurrent sessions",
        )
    )

    mutations.append(
        (
            "A6-F15",
            "P1",
            "day-0 post-return action credited to current departure SOC",
            solution,
            bundle.instance,
            {BATTERY},
            (
                "single-day static contract requires first-trip charging on "
                "day -1 before departure"
            ),
        )
    )

    routes = list(solution.routes)
    intermediate = list(source_route.node_sequence)
    intermediate.insert(-1, other_depot)
    routes[customer_route_index] = replace(
        source_route,
        node_sequence=intermediate,
    )
    mutations.append(
        (
            "A6-F16",
            "P1",
            "intermediate foreign depot inside one static trip",
            replace(solution, routes=routes),
            bundle.instance,
            {ROUTE_STRUCTURE},
            "a trip may use only its origin/terminal depot copies",
        )
    )

    routes = list(solution.routes)
    routes[solution.routes.index(cv_routes[0])] = replace(
        cv_routes[0],
        vehicle_id="OVERLAP_CV#T1",
    )
    routes[solution.routes.index(cv_routes[1])] = replace(
        cv_routes[1],
        vehicle_id="OVERLAP_CV#T2",
    )
    mutations.append(
        (
            "A6-F17",
            "P1",
            "overlapping trips assigned to one physical vehicle",
            replace(solution, routes=routes),
            bundle.instance,
            {ROUTE_STRUCTURE},
            (
                "generic full-solution validation or a mandatory certificate "
                "must reject temporal overlap"
            ),
        )
    )

    fleet_zero = replace(bundle.instance, num_cv=0)
    mutations.append(
        (
            "A6-F18",
            "P0",
            "CV fleet cap exceeded",
            solution,
            fleet_zero,
            {FLEET_SIZE},
            "physical fleet availability must be enforced",
        )
    )

    routes = list(solution.routes)
    routes[solution.routes.index(cv_routes[0])] = replace(
        cv_routes[0],
        vehicle_id="MIXED_PHYSICAL#T1",
    )
    ev_index = solution.routes.index(ev_route)
    routes[ev_index] = replace(
        ev_route,
        vehicle_id="MIXED_PHYSICAL#T2",
    )
    actions = [
        replace(item, vehicle_id="MIXED_PHYSICAL#T2")
        if item.vehicle_id == ev_route.vehicle_id
        else item
        for item in solution.charging_actions
    ]
    mutations.append(
        (
            "A6-F19",
            "P0",
            "one physical id changes vehicle type",
            replace(
                solution,
                routes=routes,
                charging_actions=actions,
            ),
            bundle.instance,
            {ROUTE_STRUCTURE},
            "one physical asset cannot change CV/EV type",
        )
    )

    for (
        check_id,
        severity,
        subject,
        mutated,
        instance,
        expected_types,
        rationale,
    ) in mutations:
        observed_types, error = violation_types(
            mutated,
            instance,
            bundle.prices,
        )
        detected = bool(observed_types.intersection(expected_types))
        rows.append(
            AuditRow(
                check_id,
                "A6",
                severity,
                "PASS" if detected else "FAIL",
                subject,
                json.dumps(
                    {
                        "violation_types": sorted(observed_types),
                        "exception": error,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(
                    sorted(expected_types),
                    ensure_ascii=False,
                ),
                "fault injection against sealed S4 witness",
                rationale,
            )
        )

    prepared, certificate = prepare_multitrip_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    execution_error = None
    try:
        build_certificate_execution_ledger(
            prepared,
            certificate,
            bundle.instance,
            bundle.prices,
        )
    except Exception as exc:
        execution_error = f"{type(exc).__name__}: {exc}"
    prepared_metrics = evaluate(
        prepared,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    prepared_violations = check_solution(
        prepared,
        bundle.instance,
        bundle.prices,
    )
    prepared_delta = (
        float(prepared_metrics["total_cost"])
        - float(production["total_cost"])
    )
    day_offsets = Counter(
        int(item.charge_day_offset)
        for item in prepared.charging_actions
    )
    rows.append(
        AuditRow(
            "A6-CERT-01",
            "A6",
            "P0",
            (
                "PASS"
                if (
                    execution_error is None
                    and not prepared_violations
                    and close(prepared_delta, 0.0)
                    and set(day_offsets).issubset({-1, 0})
                )
                else "FAIL"
            ),
            "S4 witness normalization through multitrip execution certificate",
            json.dumps(
                {
                    "execution_error": execution_error,
                    "generic_violation_count": len(prepared_violations),
                    "objective_delta": prepared_delta,
                    "charge_day_offsets": dict(day_offsets),
                    "physical_vehicle_counts": dict(
                        certificate.vehicle_counts
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            (
                "certificate ledger passes, objective unchanged, first-trip "
                "charges normalized to day -1"
            ),
            (
                "setp_solver.search.multitrip_schedule; "
                "setp_solver.search.certificate_execution"
            ),
            (
                "This distinguishes the stronger E3 certificate path from gaps "
                "in the generic checker used by the sealed E2 completion."
            ),
        )
    )

    prepared_routes = {
        route.vehicle_id: route
        for route in prepared.routes
    }
    prepared_action = prepared.charging_actions[0]
    prepared_cv_route = next(
        route
        for route in prepared.routes
        if route.vehicle_type.lower() == "cv"
    )

    certificate_faults: list[
        tuple[str, str, Solution, Any]
    ] = []
    certificate_faults.append(
        (
            "A6-CERT-F01",
            "detached charging action",
            replace(
                prepared,
                charging_actions=[
                    *prepared.charging_actions,
                    replace(
                        prepared_action,
                        vehicle_id="DETACHED_CERT_AUDIT",
                    ),
                ],
            ),
            certificate,
        )
    )
    certificate_faults.append(
        (
            "A6-CERT-F02",
            "charging action assigned to certified CV trip",
            replace(
                prepared,
                charging_actions=[
                    *prepared.charging_actions,
                    replace(
                        prepared_action,
                        vehicle_id=prepared_cv_route.vehicle_id,
                        station_id=prepared_cv_route.home_depot_id,
                    ),
                ],
            ),
            certificate,
        )
    )
    certificate_faults.append(
        (
            "A6-CERT-F03",
            "charging SOC metadata shifted away from certificate state",
            replace(
                prepared,
                charging_actions=[
                    (
                        replace(
                            item,
                            start_energy_kwh=(
                                float(item.start_energy_kwh) + 10.0
                            ),
                            end_energy_kwh=(
                                float(item.end_energy_kwh) + 10.0
                            ),
                        )
                        if item == prepared_action
                        else item
                    )
                    for item in prepared.charging_actions
                ],
            ),
            certificate,
        )
    )
    cert_half_energy = float(prepared_action.energy_kwh) / 2.0
    cert_half_duration = (
        float(prepared_action.occupancy_minutes) / 2.0
    )
    cert_half_action = replace(
        prepared_action,
        energy_kwh=cert_half_energy,
        occupancy_minutes=cert_half_duration,
        start_energy_kwh=float(prepared_action.start_energy_kwh),
        end_energy_kwh=(
            float(prepared_action.start_energy_kwh)
            + cert_half_energy
        ),
    )
    certificate_faults.append(
        (
            "A6-CERT-F04",
            "duplicate simultaneous charging sessions",
            replace(
                prepared,
                charging_actions=[
                    cert_half_action,
                    replace(cert_half_action),
                    *[
                        item
                        for item in prepared.charging_actions
                        if item != prepared_action
                    ],
                ],
            ),
            certificate,
        )
    )

    trips_by_physical: dict[str, list[Any]] = {}
    for trip in certificate.trips:
        trips_by_physical.setdefault(
            trip.physical_vehicle_id,
            [],
        ).append(trip)
    multitrip_chain = next(
        sorted(trips, key=lambda trip: trip.trip_index)
        for trips in trips_by_physical.values()
        if len(trips) >= 2
    )
    first_trip, second_trip = multitrip_chain[:2]
    overlapping_trip = replace(
        second_trip,
        departure_second=float(first_trip.return_second) - 1.0,
    )
    overlapping_certificate = replace(
        certificate,
        trips=tuple(
            overlapping_trip
            if trip.route_id == second_trip.route_id
            else trip
            for trip in certificate.trips
        ),
    )
    certificate_faults.append(
        (
            "A6-CERT-F05",
            "overlapping trips in one physical-vehicle certificate",
            prepared,
            overlapping_certificate,
        )
    )
    first_trip_action = next(
        item
        for item in prepared.charging_actions
        if int(item.charge_day_offset) == -1
    )
    certificate_faults.append(
        (
            "A6-CERT-F06",
            "first-trip precharge relabelled as a day-0 action",
            replace(
                prepared,
                charging_actions=[
                    (
                        replace(item, charge_day_offset=0)
                        if item == first_trip_action
                        else item
                    )
                    for item in prepared.charging_actions
                ],
            ),
            certificate,
        )
    )

    certificate_results: dict[str, bool] = {}
    for check_id, subject, faulty_solution, faulty_certificate in (
        certificate_faults
    ):
        rejected = False
        error = None
        try:
            build_certificate_execution_ledger(
                faulty_solution,
                faulty_certificate,
                bundle.instance,
                bundle.prices,
            )
        except Exception as exc:
            rejected = True
            error = f"{type(exc).__name__}: {exc}"
        certificate_results[check_id] = rejected
        rows.append(
            AuditRow(
                check_id,
                "A6",
                "P0",
                "PASS" if rejected else "FAIL",
                f"strict-certificate rejection: {subject}",
                json.dumps(
                    {
                        "rejected": rejected,
                        "error": error,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "fail closed",
                (
                    "setp_solver.search.multitrip_schedule; "
                    "setp_solver.search.certificate_execution"
                ),
                (
                    "Every E3-E7 formal result must traverse this stronger "
                    "certificate boundary, not check_solution alone."
                ),
            )
        )

    formal_coverage = {
        "A6-F15": "A6-CERT-F06",
        "A6-F17": "A6-CERT-F05",
    }
    rows = [
        (
            replace(
                row,
                status="PASS",
                observed=json.dumps(
                    {
                        "legacy_generic_checker_gap": True,
                        "formal_certificate_check": formal_coverage[row.check_id],
                        "formal_certificate_rejected_fault": True,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                expected=(
                    "legacy E2 checker gap is disclosed and the mandatory "
                    "formal E3 execution certificate rejects the fault"
                ),
                impact=(
                    "The sealed E2 checker remains unchanged; this fault is "
                    "closed for future formal evidence only because every E3 "
                    "candidate must traverse the execution certificate."
                ),
            )
            if (
                row.check_id in formal_coverage
                and certificate_results.get(
                    formal_coverage[row.check_id],
                    False,
                )
            )
            else row
        )
        for row in rows
    ]

    write_csv(
        OUT / "objective_checker_audit.csv",
        (asdict(row) for row in rows),
        list(asdict(rows[0])),
    )
    write_json(
        OUT / "objective_independent_recomputation.json",
        {
            "instance_id": payload["instance_id"],
            "witness": str(WITNESS.relative_to(REPO)),
            "production": {
                field: float(production[field])
                for field in objective_fields
            },
            "independent": independent,
            "mismatches": mismatches,
        },
    )
    open_high = [
        row
        for row in rows
        if row.status == "FAIL" and row.severity in {"P0", "P1"}
    ]
    summary = {
        "schema": "resetp.pre-e3-objective-checker-audit.v1",
        "search_evaluations": 0,
        "checks": len(rows),
        "status_counts": dict(Counter(row.status for row in rows)),
        "open_p0_p1": len(open_high),
        "open_findings": [asdict(row) for row in open_high],
        "verdict": (
            "HOLD_E3_OBJECTIVE_CHECKER_FINDINGS_OPEN"
            if open_high
            else "PASS_E3_OBJECTIVE_CHECKER_AUDIT"
        ),
    }
    write_json(OUT / "objective_checker_findings.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if open_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
