#!/usr/bin/env python3
"""Read-only T13 diagnostics for the five remaining targeted failures.

This file is deliberately isolated under the T13 artifact directory.  It
loads frozen witnesses and constructs the two test fixtures in memory; it
does not edit repository source, tests, or any pre-existing result directory.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging as refined_repair_route_charging,
)
from setp_solver.check import check_solution
import setp_solver.check as check_module
from setp_solver.cost import (
    evaluate,
    route_departure_second,
    route_next_day_departure_second,
    route_return_arrival_without_charging,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.alns_wouda import SearchPolicy
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import (
    _customer_ids,
    _depot_ids,
    _next_vehicle_id,
    _replace_customer_with_ev,
    build_initial_solution,
)
from setp_solver.search.charging import repair_route_charging as search_repair_route_charging
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.search.fleet import FleetLimits, normalize_solution_vehicle_trips, route_ev_energy_summary
from setp_solver.search.multitrip_schedule import route_timing
from setp_solver.solution import Route, Solution
from setp_solver.station_copies import physical_station_id


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
FIXTURE = REPO / "models/data_bundle/generated_instances/verify_20251113"


def profile_refined() -> list[dict[str, object]]:
    return [
        {
            "time_index": index,
            "horizon_second_start": float(index * 1800),
            "actual_gco2_per_kwh": float(gamma),
            "forecast_gco2_per_kwh": float(gamma),
        }
        for index, gamma in enumerate([300.0, 250.0, 200.0, 50.0, 100.0, *([150.0] * 13)])
    ]


def refined_instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=20_000.0),
            Node("C1", "c", 0.0, 0.0, demand=100.0, due_time=20_000.0),
            Node("F1", "f", 0.0, 0.0, due_time=20_000.0, charge_power_kw=60.0),
        ],
        distance_matrix=[
            [0.0, 100_000.0, 20_000.0],
            [100_000.0, 0.0, 20_000.0],
            [20_000.0, 20_000.0, 0.0],
        ],
    )


def action_row(action: Any, instance: Instance, route: Route, trip: Any | None = None) -> dict[str, Any]:
    node = next((item for item in instance.nodes if item.node_id == action.station_id), None)
    station_type = None if node is None else node.node_type
    physical = None if node is None else physical_station_id(node)
    start = float(action.charge_start_second)
    end = start + float(action.occupancy_minutes) * 60.0
    skip = bool(
        node is not None
        and node.node_type.lower() == "f"
        and action.station_id in route.node_sequence
        and int(action.charge_day_offset) == 0
    )
    return {
        "vehicle_id": action.vehicle_id,
        "station_id": action.station_id,
        "node_type": station_type,
        "physical_station_id": physical,
        "route_node_sequence": list(route.node_sequence),
        "station_id_in_route_node_sequence": action.station_id in route.node_sequence,
        "charge_day_offset": int(action.charge_day_offset),
        "charge_start_second": start,
        "charge_end_second": end,
        "occupancy_minutes": float(action.occupancy_minutes),
        "energy_kwh": float(action.energy_kwh),
        "skip_public_station_branch": skip,
        "trip_interval": None
        if trip is None
        else [float(trip.earliest_departure_second), float(trip.return_second)],
        "overlap_seconds": None
        if trip is None
        else max(
            0.0,
            min(end, float(trip.return_second))
            - max(start + int(action.charge_day_offset) * 86400.0, float(trip.earliest_departure_second)),
        ),
    }


def diagnose_refined() -> dict[str, Any]:
    instance = refined_instance()
    profile = profile_refined()
    prices = PriceParameters(B_battery_kwh=80.0)
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    repaired, actions = refined_repair_route_charging(
        route, instance, profile, prices, strategy="integrated"
    )
    timing = route_timing(repaired, instance, prices, charging_actions=actions)
    solution = Solution(routes=[repaired], charging_actions=actions)
    violations = check_solution(solution, instance, prices)
    rows = [action_row(action, instance, repaired, timing) for action in actions]

    context = EvaluationContext(
        instance, profile, prices=prices, budget=EvalBudget(limit=1, target=1)
    )
    legacy_route, legacy_actions = refined_repair_route_charging(
        route, instance, profile, prices, strategy="legacy"
    )
    legacy_solution = Solution(routes=[legacy_route], charging_actions=legacy_actions)
    operators = WinnerOperatorSet.create(refined_carbon=True, refined_carbon_weight=1.0)
    candidate_result = apply_winner_action(
        legacy_solution,
        WinnerOperatorAction(
            "charging_station_reset_destroy", "integrated_carbon_reconstruction_repair"
        ),
        context,
        rng=np.random.default_rng(7),
        operator_set=operators,
        current_obj=float(evaluate(legacy_solution, instance, profile, prices)["total_cost"]),
    )
    candidate = candidate_result["candidate_solution"]
    candidate_timing = route_timing(
        candidate.routes[0], instance, prices, charging_actions=candidate.charging_actions
    )
    candidate_rows = [
        action_row(action, instance, candidate.routes[0], candidate_timing)
        for action in candidate.charging_actions
    ]
    return {
        "fixture": {
            "nodes": [
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "physical_station_id": physical_station_id(node),
                }
                for node in instance.nodes
            ]
        },
        "integrated_route_repair": {
            "route_node_sequence": list(repaired.node_sequence),
            "route_timing": {
                "earliest_departure_second": float(timing.earliest_departure_second),
                "return_second": float(timing.return_second),
            },
            "actions": rows,
            "violations": [
                {"type": v.type, "vehicle_id": v.vehicle_id, "location": v.location, "detail": v.detail}
                for v in violations
            ],
        },
        "refined_reset_reconstruction": {
            "route_node_sequence": list(candidate.routes[0].node_sequence),
            "route_timing": {
                "earliest_departure_second": float(candidate_timing.earliest_departure_second),
                "return_second": float(candidate_timing.return_second),
            },
            "actions": candidate_rows,
            "violations": [
                {"type": v.type, "vehicle_id": v.vehicle_id, "location": v.location, "detail": v.detail}
                for v in check_solution(candidate, instance, prices)
            ],
            "candidate_result": {
                "actual_evals_added": candidate_result.get("actual_evals_added"),
                "hard_violation_count": candidate_result.get("hard_violation_count"),
            },
        },
    }


def enumerate_search_candidates(
    bundle: Any,
    prices: PriceParameters,
    *,
    fleet_limits: FleetLimits | None = None,
) -> dict[str, Any]:
    seed = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    limits = fleet_limits or FleetLimits(
        cv=int(bundle.instance.num_cv) if bundle.instance.num_cv is not None else 10**9,
        ev=int(bundle.instance.num_ev) if bundle.instance.num_ev is not None else 10**9,
        source="diagnostic",
    )
    rows: list[dict[str, Any]] = []
    for customer_id in _customer_ids(seed, bundle.instance):
        for depot_id in _depot_ids(bundle.instance):
            ev_id = _next_vehicle_id(seed, "EV")
            base_route = Route(ev_id, "ev", depot_id, [depot_id, customer_id, depot_id])
            energy = route_ev_energy_summary(base_route, bundle.instance, prices).ev_kwh
            row: dict[str, Any] = {
                "customer_id": customer_id,
                "depot_id": depot_id,
                "base_route": list(base_route.node_sequence),
                "direct_energy_kwh": float(energy),
                "battery_kwh": float(bundle.instance.battery_capacity_kwh(fallback=prices.B_battery_kwh)),
            }
            if energy <= prices.B_battery_kwh + 1e-9:
                row["generation_stage"] = "skipped_energy_not_over_battery"
                rows.append(row)
                continue
            try:
                repaired, actions = search_repair_route_charging(
                    base_route, bundle.instance, bundle.carbon_profile, prices
                )
                candidate = normalize_solution_vehicle_trips(
                    _replace_customer_with_ev(seed, customer_id, repaired, actions),
                    bundle.instance,
                    max_cv=limits.cv,
                    max_ev=limits.ev,
                )
                row.update(
                    {
                        "generation_stage": "candidate_built",
                        "repaired_route": [
                            list(item.node_sequence) for item in candidate.routes if item.vehicle_type.lower() == "ev"
                        ],
                        "actions": [action_row(action, bundle.instance, next(item for item in candidate.routes if item.vehicle_id == action.vehicle_id)) for action in candidate.charging_actions if action.vehicle_id in {item.vehicle_id for item in candidate.routes if item.vehicle_type.lower() == "ev"}],
                        "action_count": len([action for action in candidate.charging_actions if action.vehicle_id in {item.vehicle_id for item in candidate.routes if item.vehicle_type.lower() == "ev"}]),
                    }
                )
                current_violations = check_solution(candidate, bundle.instance, prices)
                row["current_checker_violations"] = [
                    {"type": v.type, "vehicle_id": v.vehicle_id, "location": v.location, "detail": v.detail}
                    for v in current_violations
                ]
                original_overlap = check_module._check_charging_trip_overlap
                check_module._check_charging_trip_overlap = lambda *args, **kwargs: []
                try:
                    old_violations = check_solution(candidate, bundle.instance, prices)
                finally:
                    check_module._check_charging_trip_overlap = original_overlap
                row["pre_T10_checker_simulation_violations"] = [
                    {"type": v.type, "vehicle_id": v.vehicle_id, "location": v.location, "detail": v.detail}
                    for v in old_violations
                ]
                row["current_candidate_passes"] = not current_violations
                row["pre_T10_checker_candidate_passes"] = not old_violations
            except Exception as exc:  # evidence of the exact generation branch
                row.update({"generation_stage": "repair_exception", "exception": f"{type(exc).__name__}: {exc}"})
            rows.append(row)
    return {"candidate_rows": rows, "candidate_count": len(rows)}


def search_window_comparison(bundle: Any) -> dict[str, Any]:
    """Print the exact pre/post window values for the deterministic C3 witness.

    The T10 diff does not change ``search/charging.py``'s window formulas;
    the post-T10 difference is the checker observing the public-charge-expanded
    route interval in ``route_timing``.
    """

    prices = PriceParameters(B_battery_kwh=80.0)
    base_route = Route("EV1", "ev", "D0", ["D0", "C3", "D0"])
    repaired, actions = search_repair_route_charging(
        base_route, bundle.instance, bundle.carbon_profile, prices
    )
    depot_action = next(action for action in actions if action.station_id == "D0")
    public_action = next(action for action in actions if action.station_id == "F2")
    depot_earliest = route_return_arrival_without_charging(base_route, bundle.instance, prices)
    period = float(len(bundle.carbon_profile)) * 1800.0
    depot_latest = (
        route_next_day_departure_second(
            base_route, bundle.instance, prices, period_seconds=period
        )
        - float(depot_action.occupancy_minutes) * 60.0
    )
    current = "D0"
    target = "C3"
    station = "F2"
    load_kg = next(node.demand for node in bundle.instance.nodes if node.node_id == target)
    _, to_station_seconds, _ = bundle.instance.arc_metrics(
        current, station, "ev", fallback_speed_mps=prices.v_speed_ms
    )
    _, station_to_target_seconds, _ = bundle.instance.arc_metrics(
        station, target, "ev", fallback_speed_mps=prices.v_speed_ms
    )
    public_earliest = max(float(to_station_seconds), 0.0)
    public_latest = min(
        float(next(node.due_time for node in bundle.instance.nodes if node.node_id == station)),
        float(next(node.due_time for node in bundle.instance.nodes if node.node_id == target))
        - float(public_action.occupancy_minutes) * 60.0
        - float(station_to_target_seconds),
    )
    timing = route_timing(
        repaired, bundle.instance, prices, charging_actions=actions
    )
    return {
        "route": list(base_route.node_sequence),
        "depot_open_ready_second": float(next(node.ready_time for node in bundle.instance.nodes if node.node_id == "D0")),
        "route_due_second": float(next(node.due_time for node in bundle.instance.nodes if node.node_id == "D0")),
        "customer_ready_due": {
            "C3_ready": float(next(node.ready_time for node in bundle.instance.nodes if node.node_id == "C3")),
            "C3_due": float(next(node.due_time for node in bundle.instance.nodes if node.node_id == "C3")),
        },
        "direct_energy_kwh": float(route_ev_energy_summary(base_route, bundle.instance, prices).ev_kwh),
        "battery_capacity_kwh": float(bundle.instance.battery_capacity_kwh(fallback=prices.B_battery_kwh)),
        "route_clock_without_public_charge": {
            "departure_second": float(route_departure_second(base_route, bundle.instance, prices)),
            "return_second": float(route_return_arrival_without_charging(base_route, bundle.instance, prices)),
        },
        "generated_windows": {
            "pre_T10": {
                "depot": [float(depot_earliest), float(depot_latest)],
                "public_F2": [float(public_earliest), float(public_latest)],
            },
            "post_T10": {
                "depot": [float(depot_earliest), float(depot_latest)],
                "public_F2": [float(public_earliest), float(public_latest)],
            },
            "formula_diff": "none in search/charging.py; current git diff only moves _curve_aware_action import",
        },
        "chosen_actions": [
            {
                "station_id": action.station_id,
                "start_second": float(action.charge_start_second),
                "end_second": float(action.charge_start_second + action.occupancy_minutes * 60.0),
                "energy_kwh": float(action.energy_kwh),
            }
            for action in actions
        ],
        "post_T10_route_timing_with_public_action": {
            "departure_second": float(timing.earliest_departure_second),
            "return_second": float(timing.return_second),
            "interval": [float(timing.earliest_departure_second), float(timing.return_second)],
        },
        "window_widths": {
            "depot_seconds": float(depot_latest - depot_earliest),
            "public_F2_seconds": float(public_latest - public_earliest),
        },
    }


def diagnose_search() -> dict[str, Any]:
    bundle = load_search_bundle(FIXTURE)
    legacy_prices = PriceParameters(B_battery_kwh=80.0)
    outcomes: dict[str, Any] = {}
    for label, kwargs in (
        ("h2", {"prices": legacy_prices}),
        ("h3", {"prices": legacy_prices}),
        ("m0", {"fleet_limits": FleetLimits(cv=3, ev=8, source="test"), "prices": PriceParameters()}),
    ):
        try:
            solution = build_initial_solution(
                bundle.instance,
                bundle.carbon_profile,
                prices=kwargs["prices"],
                fleet_limits=kwargs.get("fleet_limits"),
                require_charging_signal=True,
            )
            outcomes[label] = {"status": "returned", "solution_charge_kwh": sum(action.energy_kwh for action in solution.charging_actions)}
        except Exception as exc:
            outcomes[label] = {"status": "exception", "exception": f"{type(exc).__name__}: {exc}"}
    enumerated = enumerate_search_candidates(bundle, legacy_prices)
    return {
        "fixture_path": str(FIXTURE),
        "instance": {
            "num_cv": bundle.instance.num_cv,
            "num_ev": bundle.instance.num_ev,
            "battery_capacity_kwh": bundle.instance.battery_capacity_kwh(fallback=legacy_prices.B_battery_kwh),
            "depot_nodes": [
                {"node_id": node.node_id, "ready_time": node.ready_time, "due_time": node.due_time}
                for node in bundle.instance.nodes if node.node_type.lower() == "d"
            ],
            "station_nodes": [
                {"node_id": node.node_id, "node_type": node.node_type, "ready_time": node.ready_time, "due_time": node.due_time, "charge_power_kw": node.charge_power_kw, "physical_station_id": physical_station_id(node)}
                for node in bundle.instance.nodes if node.node_type.lower() == "f"
            ],
        },
        "test_entry_outcomes": outcomes,
        "deterministic_C3_window_comparison": search_window_comparison(bundle),
        "enumeration": enumerated,
    }


def main() -> None:
    result = {
        "environment": {
            "PYTHONHASHSEED": "0",
            "PYTHONPATH_contract": "solver/src:models/src",
            "repository": str(REPO),
        },
        "refined": diagnose_refined(),
        "search": diagnose_search(),
    }
    (OUT / "diagnostic_observations.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
