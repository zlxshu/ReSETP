"""E5 charging-strategy ablation and EV-adoption diagnostics.

v2026-06-12: R1/R2 redefine E5 around a fixed-route charging-policy
ablation. The route set comes from the prior real-budget A solution; this
module only replays charging actions or single-route EV flips for diagnosis.
"""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..check import check_solution
from ..cost import (
    _arc_loads,
    carbon_slot_index,
    charging_action_slot_breakdown,
    evaluate,
    ev_arc_energy_kwh,
    route_node_schedule,
)
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Route, Solution, charging_action_from_dict
from .bundle import load_search_bundle
from .charging import (
    _curve_aware_action,
    repair_route_charging,
    replay_fixed_route_charging,
)


COST_DELTA_KEYS = (
    "total_cost",
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_carbon",
    "E_total",
    "E_cv_direct",
    "E_ev_indirect",
    "fuel_liters",
    "electricity_kwh",
    "depot_charging_kwh",
    "station_charging_kwh",
)


def run_e5_charging_ablation(
    bundle_dir: str | Path,
    source_report_path: str | Path,
    *,
    output_json_path: str | Path | None = None,
    output_csv_path: str | Path | None = None,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    halt_on_zero_delta: bool = True,
) -> dict[str, Any]:
    """Replay prior A routes with carbon-aware vs return-immediate charging."""

    bundle = load_search_bundle(bundle_dir)
    source_report = _load_report(source_report_path)
    fixed_routes = _solution_from_report(source_report, include_actions=False)
    aware = replay_fixed_route_charging(fixed_routes, bundle.instance, bundle.carbon_profile, prices, strategy="aware")
    naive = replay_fixed_route_charging(fixed_routes, bundle.instance, bundle.carbon_profile, prices, strategy="naive")

    payload = {
        "source_report_path": str(Path(source_report_path)),
        "bundle_dir": str(Path(bundle_dir)),
        "slot_count": len(bundle.carbon_profile),
        "carbon_aware": _scenario_payload("carbon_aware", aware, bundle.instance, bundle.carbon_profile, prices),
        "naive_return_charge": _scenario_payload("naive_return_charge", naive, bundle.instance, bundle.carbon_profile, prices),
        "action_start_comparison": _action_start_comparison(aware, naive, bundle.carbon_profile),
    }
    payload["delta_intensity_gco2_per_kwh_naive_minus_aware"] = (
        payload["naive_return_charge"]["mean_intensity_gco2_per_kwh"] - payload["carbon_aware"]["mean_intensity_gco2_per_kwh"]
    )
    payload["delta_carbon_kg_naive_minus_aware"] = (
        payload["naive_return_charge"]["charging_carbon_kg"] - payload["carbon_aware"]["charging_carbon_kg"]
    )

    if output_json_path is not None:
        _write_json(output_json_path, payload)
    if output_csv_path is not None:
        _write_slot_csv(output_csv_path, payload)
    if halt_on_zero_delta and (
        abs(float(payload["delta_intensity_gco2_per_kwh_naive_minus_aware"])) <= 1e-12
        or abs(float(payload["delta_carbon_kg_naive_minus_aware"])) <= 1e-12
    ):
        raise RuntimeError("HALT_R1: charging ablation has zero delta; inspect action_start_comparison in the emitted payload")
    return payload


def run_ev_adoption_diagnostic(
    bundle_dir: str | Path,
    source_report_path: str | Path,
    *,
    output_json_path: str | Path | None = None,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> dict[str, Any]:
    """Flip short/mid/long CV routes to EV and report economics."""

    bundle = load_search_bundle(bundle_dir)
    source_report = _load_report(source_report_path)
    # v2026-06-12: S0 replays the prior A route set under the new overnight
    # depot charging semantics before comparing any CV->EV flip.
    base_solution = replay_fixed_route_charging(
        _solution_from_report(source_report, include_actions=False),
        bundle.instance,
        bundle.carbon_profile,
        prices,
        strategy="aware",
    )
    base_metrics = evaluate(base_solution, bundle.instance, bundle.carbon_profile, prices)
    selected = _select_cv_routes(base_solution, bundle.instance)
    rows = [
        _flip_cv_route_row(sample, route, base_solution, base_metrics, bundle.instance, bundle.carbon_profile, prices)
        for sample, route in selected
    ]
    payload = {
        "source_report_path": str(Path(source_report_path)),
        "bundle_dir": str(Path(bundle_dir)),
        "base_cv_route_count": sum(1 for route in base_solution.routes if route.vehicle_type.lower() == "cv"),
        "base_ev_route_count": sum(1 for route in base_solution.routes if route.vehicle_type.lower() == "ev"),
        "vehicle_type_swap_counts": _vehicle_type_swap_counts(source_report),
        "cv_route_flips": rows,
    }
    if output_json_path is not None:
        _write_json(output_json_path, payload)
    return payload


def _scenario_payload(
    label: str,
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> dict[str, Any]:
    metrics = evaluate(solution, instance, carbon_profile, prices)
    total_kwh = float(metrics["electricity_kwh"])
    charge_carbon = float(metrics["E_ev_indirect"])
    violations = check_solution(solution, instance, prices)
    return {
        "label": label,
        "feasible": len(violations) == 0,
        "violations": [violation.__dict__ for violation in violations],
        "charging_total_kwh": total_kwh,
        "charging_carbon_kg": charge_carbon,
        "mean_intensity_gco2_per_kwh": 0.0 if total_kwh <= 1e-12 else charge_carbon * 1000.0 / total_kwh,
        "depot_charging_kwh": float(metrics["depot_charging_kwh"]),
        "station_charging_kwh": float(metrics["station_charging_kwh"]),
        "slot_y_skt": _slot_split_rows(
            solution,
            instance,
            carbon_profile,
            prices,
        ),
        "charging_actions": [action.__dict__ for action in solution.charging_actions],
        "cost_metrics": metrics,
    }


def _slot_split_rows(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any,
) -> list[dict[str, float]]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    rows = [
        {
            "slot_index": idx,
            "horizon_second_start": float(row["horizon_second_start"]),
            "gamma_gco2_per_kwh": float(row["actual_gco2_per_kwh"]),
            "depot_kwh": 0.0,
            "station_kwh": 0.0,
            "other_kwh": 0.0,
            "total_kwh": 0.0,
        }
        for idx, row in enumerate(carbon_profile)
    ]
    for action in solution.charging_actions:
        node = node_lookup.get(action.station_id)
        node_type = node.node_type.lower() if node is not None else ""
        bucket = "depot_kwh" if node_type == "d" else "station_kwh" if node_type == "f" else "other_kwh"
        for slot in charging_action_slot_breakdown(
            action,
            instance,
            prices,
            n_slots=len(carbon_profile),
            cyclic=True,
        ):
            rows[slot.slot_index][bucket] += float(slot.y_skt_kwh)
            rows[slot.slot_index]["total_kwh"] += float(slot.y_skt_kwh)
    return rows


def _action_start_comparison(aware: Solution, naive: Solution, carbon_profile: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for idx, (aware_action, naive_action) in enumerate(zip(aware.charging_actions, naive.charging_actions)):
        aware_slot = carbon_slot_index(aware_action.charge_start_second, n_slots=len(carbon_profile), cyclic=True)
        naive_slot = carbon_slot_index(naive_action.charge_start_second, n_slots=len(carbon_profile), cyclic=True)
        comparisons.append(
            {
                "action_index": idx,
                "vehicle_id": aware_action.vehicle_id,
                "station_id": aware_action.station_id,
                "energy_kwh": float(aware_action.energy_kwh),
                "aware_start_second": float(aware_action.charge_start_second),
                "aware_slot": aware_slot,
                "aware_gamma": float(carbon_profile[aware_slot]["actual_gco2_per_kwh"]),
                "naive_start_second": float(naive_action.charge_start_second),
                "naive_slot": naive_slot,
                "naive_gamma": float(carbon_profile[naive_slot]["actual_gco2_per_kwh"]),
            }
        )
    return comparisons


def _select_cv_routes(solution: Solution, instance: Instance) -> list[tuple[str, Route]]:
    cv_routes = sorted(
        (route for route in solution.routes if route.vehicle_type.lower() == "cv"),
        key=lambda route: (_route_distance(route, instance), route.vehicle_id),
    )
    if len(cv_routes) < 3:
        raise ValueError("R2 diagnostic requires at least three CV routes")
    return [("short", cv_routes[0]), ("mid", cv_routes[len(cv_routes) // 2]), ("long", cv_routes[-1])]


def _flip_cv_route_row(
    sample: str,
    route: Route,
    base_solution: Solution,
    base_metrics: dict[str, float],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> dict[str, Any]:
    ev_route = replace(route, vehicle_id=f"EV_DIAG_{route.vehicle_id}", vehicle_type="ev")
    insertion_diagnostic = _charging_insertion_diagnostic(ev_route, instance, prices)
    try:
        repaired_route, actions = repair_route_charging(ev_route, instance, carbon_profile, prices)
    except ValueError as exc:
        return {
            "sample": sample,
            "route_id": route.vehicle_id,
            "distance_m": _route_distance(route, instance),
            "customer_count": sum(1 for node_id in route.node_sequence if node_id.startswith("C")),
            "feasible": False,
            "repair_error": str(exc),
            "root_cause": insertion_diagnostic["root_cause"],
            "battery_trajectory": insertion_diagnostic["battery_trajectory"],
            "station_insertion_diagnostics": insertion_diagnostic["station_insertion_diagnostics"],
            "cost_delta": {key: None for key in COST_DELTA_KEYS},
        }
    candidate = replace(
        base_solution,
        routes=[repaired_route if item.vehicle_id == route.vehicle_id else item for item in base_solution.routes],
        charging_actions=[*base_solution.charging_actions, *actions],
    )
    violations = check_solution(candidate, instance, prices)
    candidate_metrics = evaluate(candidate, instance, carbon_profile, prices)
    return {
        "sample": sample,
        "route_id": route.vehicle_id,
        "ev_route_id": repaired_route.vehicle_id,
        "distance_m": _route_distance(route, instance),
        "customer_count": sum(1 for node_id in route.node_sequence if node_id.startswith("C")),
        "feasible": len(violations) == 0,
        "violations": [violation.__dict__ for violation in violations],
        "added_charging_actions": [action.__dict__ for action in actions],
        "root_cause": "flip_feasible" if len(violations) == 0 else insertion_diagnostic["root_cause"],
        "battery_trajectory": insertion_diagnostic["battery_trajectory"],
        "station_insertion_diagnostics": insertion_diagnostic["station_insertion_diagnostics"],
        "cost_delta": {key: float(candidate_metrics[key] - base_metrics[key]) for key in COST_DELTA_KEYS},
    }


def _charging_insertion_diagnostic(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> dict[str, Any]:
    trajectory = _full_battery_trajectory(route, instance, prices)
    first_infeasible = next((row for row in trajectory if row["infeasible"]), None)
    if first_infeasible is None:
        return {
            "root_cause": "flip_feasible",
            "battery_trajectory": trajectory,
            "station_insertion_diagnostics": [],
        }
    rows = _station_insertion_rows(route, instance, prices, int(first_infeasible["arc_index"]), trajectory)
    feasible_insertions = [row for row in rows if row["candidate_feasible"]]
    if feasible_insertions:
        root_cause = "repair_logic_defect"
    elif any(row["can_reach_station"] and row["covers_first_infeasible_arc"] for row in rows):
        root_cause = "time_window_too_tight"
    else:
        root_cause = "station_too_few_or_far"
    return {
        "root_cause": root_cause,
        "first_infeasible_arc": first_infeasible,
        "battery_trajectory": trajectory,
        "station_insertion_diagnostics": rows,
    }


def _full_battery_trajectory(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> list[dict[str, Any]]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    loads = _arc_loads(route.node_sequence, node_lookup)
    battery_cap = _price(prices, "B_battery_kwh")
    battery = battery_cap
    rows: list[dict[str, Any]] = []
    first_seen = False
    for idx, ((from_node_id, to_node_id), load_kg) in enumerate(zip(zip(route.node_sequence, route.node_sequence[1:]), loads)):
        use_kwh = ev_arc_energy_kwh(instance.distance(from_node_id, to_node_id), load_kg, prices)
        before = battery
        after = before - use_kwh
        infeasible = after < -1e-9 and not first_seen
        if infeasible:
            first_seen = True
        rows.append(
            {
                "arc_index": idx,
                "from_node": from_node_id,
                "to_node": to_node_id,
                "load_kg": float(load_kg),
                "battery_before_kwh": float(before),
                "arc_energy_kwh": float(use_kwh),
                "battery_after_kwh": float(after),
                "infeasible": infeasible,
                "deficit_kwh": float(max(0.0, -after)),
            }
        )
        battery = after
    return rows


def _station_insertion_rows(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    failing_arc_index: int,
    trajectory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    stations = [node for node in instance.nodes if node.node_type.lower() == "f"]
    schedule = route_node_schedule(route, instance, prices, charging_actions=[])
    rows: list[dict[str, Any]] = []
    for arc_index in range(failing_arc_index + 1):
        current = route.node_sequence[arc_index]
        target = route.node_sequence[arc_index + 1]
        arc_row = trajectory[arc_index]
        load_kg = float(arc_row["load_kg"])
        battery_before = float(arc_row["battery_before_kwh"])
        depart_current = float(schedule[arc_index].t_depart)
        for station in stations:
            rows.append(
                _station_insertion_row(
                    route,
                    current,
                    target,
                    arc_index,
                    failing_arc_index,
                    station,
                    load_kg,
                    battery_before,
                    depart_current,
                    instance,
                    node_lookup,
                    prices,
                )
            )
    return rows


def _station_insertion_row(
    route: Route,
    current: str,
    target: str,
    arc_index: int,
    failing_arc_index: int,
    station: Node,
    load_kg: float,
    battery_before: float,
    depart_current: float,
    instance: Instance,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
) -> dict[str, Any]:
    battery_cap = _price(prices, "B_battery_kwh")
    to_station_m = instance.distance(current, station.node_id)
    station_to_target_m = instance.distance(station.node_id, target)
    direct_m = instance.distance(current, target)
    energy_to_station = ev_arc_energy_kwh(to_station_m, load_kg, prices)
    can_reach = energy_to_station <= battery_before + 1e-9
    battery_at_station = battery_before - energy_to_station if can_reach else None
    energy_station_to_target = ev_arc_energy_kwh(station_to_target_m, load_kg, prices)
    station_to_target_within_battery = energy_station_to_target <= battery_cap + 1e-9
    energy_to_cover_failure = _energy_from_station_through_arc(
        station.node_id,
        route,
        arc_index,
        failing_arc_index,
        instance,
        node_lookup,
        prices,
    )
    covers_first_infeasible_arc = energy_to_cover_failure <= battery_cap + 1e-9
    energy_needed = None
    duration_sec = None
    tw_break_node = None
    late_by = 0.0
    time_window_feasible = False
    if can_reach and covers_first_infeasible_arc and station.charge_power_kw and station.charge_power_kw > 0:
        energy_needed = max(0.0, energy_to_cover_failure - float(battery_at_station))
        duration_sec = (
            _curve_aware_action(
                vehicle_id=route.vehicle_id,
                station_id=station.node_id,
                start_energy_kwh=float(battery_at_station),
                energy_kwh=energy_needed,
                reference_power_kw=float(station.charge_power_kw),
                prices=prices,
            ).occupancy_minutes
            * 60.0
        )
        tw_break_node, late_by = _first_time_window_break_after_insert(
            route,
            arc_index,
            station,
            duration_sec,
            depart_current,
            instance,
            node_lookup,
            prices,
        )
        time_window_feasible = tw_break_node is None
    candidate_feasible = bool(can_reach and covers_first_infeasible_arc and time_window_feasible)
    return {
        "arc_index": arc_index,
        "arc": f"{current}->{target}",
        "station_id": station.node_id,
        "detour_distance_m": float(to_station_m + station_to_target_m - direct_m),
        "can_reach_station": bool(can_reach),
        "energy_to_station_kwh": float(energy_to_station),
        "battery_at_station_kwh": None if battery_at_station is None else float(battery_at_station),
        "station_to_target_energy_kwh": float(energy_station_to_target),
        "station_to_target_within_battery": bool(station_to_target_within_battery),
        "energy_to_cover_first_infeasible_arc_kwh": float(energy_to_cover_failure),
        "covers_first_infeasible_arc": bool(covers_first_infeasible_arc),
        "charge_needed_kwh": None if energy_needed is None else float(energy_needed),
        "charge_duration_sec": None if duration_sec is None else float(duration_sec),
        "time_window_feasible": bool(time_window_feasible),
        "time_window_break_node": tw_break_node,
        "late_by_seconds": float(late_by),
        "candidate_feasible": candidate_feasible,
    }


def _energy_from_station_through_arc(
    station_id: str,
    route: Route,
    inserted_before_arc_index: int,
    failing_arc_index: int,
    instance: Instance,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    path = [station_id, *route.node_sequence[inserted_before_arc_index + 1 : failing_arc_index + 2]]
    remaining_customers = [
        node_id
        for node_id in route.node_sequence[inserted_before_arc_index + 1 :]
        if node_lookup[node_id].node_type.lower() == "c"
    ]
    total = 0.0
    for from_node_id, to_node_id in zip(path, path[1:]):
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in remaining_customers)
        total += ev_arc_energy_kwh(instance.distance(from_node_id, to_node_id), load_kg, prices)
        if node_lookup[to_node_id].node_type.lower() == "c" and to_node_id in remaining_customers:
            remaining_customers.remove(to_node_id)
    return total


def _first_time_window_break_after_insert(
    route: Route,
    arc_index: int,
    station: Node,
    charge_duration_sec: float,
    depart_current: float,
    instance: Instance,
    node_lookup: dict[str, Node],
    prices: PriceParameters | dict[str, float] | Any,
) -> tuple[str | None, float]:
    speed = _price(prices, "v_speed_ms")
    current = route.node_sequence[arc_index]
    target = route.node_sequence[arc_index + 1]
    arrive_station = depart_current + instance.distance(current, station.node_id) / speed
    charge_start = max(arrive_station, float(station.ready_time))
    if charge_start > float(station.due_time) + 1e-9:
        return station.node_id, charge_start - float(station.due_time)
    depart_station = charge_start + charge_duration_sec
    arrive = depart_station + instance.distance(station.node_id, target) / speed
    for idx in range(arc_index + 1, len(route.node_sequence)):
        node_id = route.node_sequence[idx]
        node = node_lookup[node_id]
        start = max(arrive, float(node.ready_time))
        if start > float(node.due_time) + 1e-9:
            return node_id, start - float(node.due_time)
        depart = start + float(node.service_time)
        if idx + 1 >= len(route.node_sequence):
            break
        arrive = depart + instance.distance(node_id, route.node_sequence[idx + 1]) / speed
    return None, 0.0


def _vehicle_type_swap_counts(source_report: dict[str, Any]) -> dict[str, Any]:
    raw = source_report.get("A_carbon_on", {}).get("destroy_operator_counts", {}).get("vehicle_type_swap", [0, 0, 0, 0])
    raw = [int(value) for value in raw]
    return {
        "raw_outcome_order": ["BEST", "BETTER", "ACCEPT", "REJECT"],
        "raw": raw,
        "attempts": sum(raw),
        "improves": raw[0] + raw[1],
        "accepted": raw[0] + raw[1] + raw[2],
        "rejected": raw[3],
    }


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _route_distance(route: Route, instance: Instance) -> float:
    return sum(instance.distance(left, right) for left, right in zip(route.node_sequence, route.node_sequence[1:]))


def _solution_from_report(source_report: dict[str, Any], *, include_actions: bool) -> Solution:
    scenario = source_report["A_carbon_on"]
    routes = [
        Route(
            vehicle_id=str(row["vehicle_id"]),
            vehicle_type=str(row["vehicle_type"]),
            home_depot_id=str(row["home_depot_id"]),
            node_sequence=[str(node_id) for node_id in row["node_sequence"]],
        )
        for row in scenario["routes"]
    ]
    actions = []
    if include_actions:
        actions = [
            charging_action_from_dict(row)
            for row in scenario["charging_actions"]
        ]
    return Solution(routes=routes, charging_actions=actions)


def _load_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_slot_csv(path: str | Path, payload: dict[str, Any]) -> None:
    fieldnames = [
        "scenario",
        "slot_index",
        "horizon_second_start",
        "gamma_gco2_per_kwh",
        "depot_kwh",
        "station_kwh",
        "other_kwh",
        "total_kwh",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for scenario_key in ("carbon_aware", "naive_return_charge"):
            for row in payload[scenario_key]["slot_y_skt"]:
                writer.writerow({"scenario": scenario_key, **row})
