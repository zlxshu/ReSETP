from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from setp_solver.china81 import load_china81_bundle
from setp_solver.cost import (
    route_next_day_departure_second,
    route_node_schedule,
    route_departure_second,
    route_return_arrival_without_charging,
)
from setp_solver.instance_loader import load_carbon_profile
from setp_solver.prices import PriceParameters
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.charging import (
    _fixed_charge_window as b_fixed_charge_window,
    repair_route_charging as b_repair_route_charging,
)
from setp_solver.search.multitrip_schedule import (
    CHARGE_MODE_ON_DEMAND,
    build_multitrip_certificate,
    route_timing,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    _fixed_charge_window as c_fixed_charge_window,
    repair_route_charging as c_repair_route_charging,
)
from setp_solver.solution import ChargingAction, Route, Solution


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
E1_DIR = ROOT / "models/data_bundle/generated_instances/verify_20251113"
E2_WITNESS = ROOT / "docs/handoff/intertrip_charging_fix_20260804/solution_witnesses.json"
E2_ID = "cn-jjj-50c-01-V2-LOCATIONS"


def dump(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [dump(item) for item in value]
    if isinstance(value, tuple):
        return [dump(item) for item in value]
    if isinstance(value, dict):
        return {str(key): dump(item) for key, item in value.items()}
    return value


def action_from_dict(row: dict[str, object]) -> ChargingAction:
    return ChargingAction(
        vehicle_id=str(row["vehicle_id"]),
        station_id=str(row["station_id"]),
        energy_kwh=float(row["energy_kwh"]),
        occupancy_minutes=float(row["occupancy_minutes"]),
        charge_start_second=float(row["charge_start_second"]),
        charge_day_offset=int(row.get("charge_day_offset", 0)),
        start_energy_kwh=(
            None if row.get("start_energy_kwh") is None else float(row["start_energy_kwh"])
        ),
        end_energy_kwh=(
            None if row.get("end_energy_kwh") is None else float(row["end_energy_kwh"])
        ),
        charging_curve_id=(
            None if row.get("charging_curve_id") is None else str(row["charging_curve_id"])
        ),
    )


def window_b(route: Route, instance: object, prices: object, profile: list[dict[str, object]], action: ChargingAction) -> dict[str, object]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    idx = route.node_sequence.index(action.station_id)
    schedule = route_node_schedule(route, instance, prices, charging_actions=[action])
    arrival = next(item.t_arrive for item in schedule if item.node_id == action.station_id)
    earliest, latest = b_fixed_charge_window(
        idx, route, node_lookup, instance, prices,
        float(action.occupancy_minutes) * 60.0, arrival, len(profile),
    )
    return {"earliest": earliest, "latest": latest, "arrival_used": arrival}


def window_c(route: Route, instance: object, prices: object, profile: list[dict[str, object]], action: ChargingAction) -> dict[str, object]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    idx = route.node_sequence.index(action.station_id)
    schedule = route_node_schedule(route, instance, prices, charging_actions=[action])
    arrival = next(item.t_arrive for item in schedule if item.node_id == action.station_id)
    earliest, latest = c_fixed_charge_window(
        idx, route, node_lookup, instance, prices,
        float(action.occupancy_minutes) * 60.0, arrival, len(profile),
    )
    return {"earliest": earliest, "latest": latest, "arrival_used": arrival}


def main() -> None:
    trace: list[str] = []
    result: dict[str, object] = {"environment": {"PYTHONHASHSEED": "0", "PYTHONPATH": "solver/src:models/src"}}

    # E1: T13's deterministic minimal search fixture.
    e1 = load_search_bundle(E1_DIR)
    p1 = PriceParameters(B_battery_kwh=80.0)
    base1 = Route("EV_T14_E1", "ev", "D0", ["D0", "C3", "D0"])
    repaired1, actions1 = b_repair_route_charging(base1, e1.instance, e1.carbon_profile, p1)
    depot1 = next(action for action in actions1 if action.station_id == "D0")
    public1 = next(action for action in actions1 if action.station_id == "F2")
    a1 = route_timing(repaired1, e1.instance, p1, charging_actions=actions1)
    schedule1 = route_node_schedule(repaired1, e1.instance, p1, charging_actions=actions1)
    b_depot_window1 = window_b(repaired1, e1.instance, p1, e1.carbon_profile, depot1)
    b_public_window1 = window_b(repaired1, e1.instance, p1, e1.carbon_profile, public1)
    result["E1_T13_minimal_D0_F2_C3_D0"] = {
        "route_before_repair": dump(base1),
        "route_after_B_repair": dump(repaired1),
        "B_actions": dump(actions1),
        "A_route_timing": dump(a1),
        "shared_route_node_schedule_with_actions": dump(schedule1),
        "B_depot_window": b_depot_window1,
        "B_public_window": b_public_window1,
        "B_no_charge_return": route_return_arrival_without_charging(repaired1, e1.instance, p1),
        "B_next_day_departure": route_next_day_departure_second(
            repaired1, e1.instance, p1, period_seconds=len(e1.carbon_profile) * 1800.0
        ),
        "A_outside_interval": [a1.earliest_departure_second, a1.return_second],
        "B_outside_interval_from_route_node_schedule": [schedule1[0].t_arrive, schedule1[-1].t_arrive],
        "source_note_C": "not run on E1: China81 completion requires a China81Bundle",
    }
    trace.extend([
        "E1 repaired route=" + repr(repaired1.node_sequence),
        "E1 A timing=" + repr(dump(a1)),
        "E1 B depot window=" + repr(b_depot_window1),
        "E1 B public window=" + repr(b_public_window1),
    ])

    # E2: archived China81 witness, used because C requires a China81 bundle.
    witness = json.loads(E2_WITNESS.read_text(encoding="utf-8"))["runs"]["O_seed2_budget1000"]
    routes2 = [Route(str(row["vehicle_id"]), str(row["vehicle_type"]), str(row["home_depot_id"]), list(row["node_sequence"])) for row in witness["solution"]["routes"]]
    actions2 = [action_from_dict(row) for row in witness["solution"]["charging_actions"]]
    sol2 = Solution(routes=routes2, charging_actions=actions2)
    bundle2 = load_china81_bundle(ROOT, E2_ID, date="2025-02-12")
    cert2 = build_multitrip_certificate(routes2, bundle2.instance, bundle2.prices, recharge_mode=CHARGE_MODE_ON_DEMAND, charging_actions=actions2)
    ev_route2 = next(route for route in routes2 if route.vehicle_type.lower() == "ev" and route.home_depot_id == "D_beijing")
    b_repaired2, b_actions2 = b_repair_route_charging(
        ev_route2, bundle2.instance, bundle2.time_profile, bundle2.prices,
    )
    b_depot2 = next(action for action in b_actions2 if action.station_id == ev_route2.home_depot_id)
    b_timing2 = route_timing(b_repaired2, bundle2.instance, bundle2.prices, charging_actions=b_actions2)
    b_schedule2 = route_node_schedule(b_repaired2, bundle2.instance, bundle2.prices, charging_actions=b_actions2)
    b_window2 = window_b(b_repaired2, bundle2.instance, bundle2.prices, bundle2.time_profile, b_depot2)
    c_repaired2, c_actions2 = c_repair_route_charging(
        ev_route2, bundle2.instance, bundle2.time_profile, bundle2.prices,
        strategy="integrated", carbon_weight=0.0,
        depot_charge_window_mode="same_day_predeparture",
        charge_amount_strategy="just_enough",
    )
    c_depot2 = next(action for action in c_actions2 if action.station_id == ev_route2.home_depot_id)
    c_timing2 = route_timing(c_repaired2, bundle2.instance, bundle2.prices, charging_actions=c_actions2)
    c_schedule2 = route_node_schedule(c_repaired2, bundle2.instance, bundle2.prices, charging_actions=c_actions2)
    c_window2 = {
        "earliest": 0.0,
        "latest": route_departure_second(c_repaired2, bundle2.instance, bundle2.prices)
        - float(c_depot2.occupancy_minutes) * 60.0,
        "route_departure_anchor": route_departure_second(c_repaired2, bundle2.instance, bundle2.prices),
    }
    a_first_action2 = next(action for action in actions2 if action.station_id == "D_beijing")
    a_first_window2 = {
        "earliest": 0.0,
        "latest": 86400.0 - float(a_first_action2.occupancy_minutes) * 60.0,
        "duration_seconds": float(a_first_action2.occupancy_minutes) * 60.0,
    }
    a_chain2 = [dump(trip) for trip in sorted(cert2.trips, key=lambda item: (item.physical_vehicle_id, item.trip_index))]
    transition2 = []
    by_vehicle: dict[str, list[object]] = {}
    for trip in cert2.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    for vehicle_id, chain in sorted(by_vehicle.items()):
        ordered = sorted(chain, key=lambda item: item.trip_index)
        for previous, current in zip(ordered, ordered[1:]):
            transition2.append({
                "physical_vehicle_id": vehicle_id,
                "previous_route_id": previous.route_id,
                "previous_return_second": previous.return_second,
                "current_route_id": current.route_id,
                "current_departure_second": current.departure_second,
                "gap_seconds": current.departure_second - previous.return_second,
                "constraint_observed": previous.return_second <= current.departure_second + 1e-6,
            })
    result["E2_O_seed2_budget1000_China81"] = {
        "instance_id": E2_ID,
        "route_count": len(routes2),
        "A_certificate_trips": a_chain2,
        "A_transition_checks": transition2,
        "A_first_trip_depot_window_from_reschedule_contract": a_first_window2,
        "B_route": dump(b_repaired2),
        "B_actions": dump(b_actions2),
        "B_own_forward_clock": {
            "departure_second": b_schedule2[0].t_depart,
            "return_second": b_schedule2[-1].t_arrive,
        },
        "B_route_timing_with_shared_schedule_replay": dump(b_timing2),
        "B_depot_window_cyclic_overnight": b_window2,
        "B_public_station_window": "not calculated: this archived route has no public-station charging action",
        "C_route": dump(c_repaired2),
        "C_actions": dump(c_actions2),
        "C_own_forward_clock": {
            "departure_second": c_schedule2[0].t_depart,
            "return_second": c_schedule2[-1].t_arrive,
        },
        "C_route_timing_via_authoritative_certificate_clock": dump(c_timing2),
        "C_depot_window_same_day_predeparture": c_window2,
        "C_public_station_window": "not calculated: this archived route has no public-station charging action",
        "C_generated_charge_day_offset": c_depot2.charge_day_offset,
        "archived_witness_depot_action_offsets": [action.charge_day_offset for action in actions2 if action.station_id in {"D_beijing", "D_tianjin"}],
        "A_first_trip_charge_day_offset": cert2.first_trip_charge_day_offset,
        "C_completion_delegates_multitrip_physicalization": True,
        "C_exact_score_entrypoint": "setp_solver.china81_completion.exact_china81_score",
    }
    trace.extend([
        "E2 certificate trip count=" + str(len(cert2.trips)),
        "E2 transitions=" + repr(transition2),
        "E2 B timing=" + repr(dump(b_timing2)),
        "E2 B depot window=" + repr(b_window2),
        "E2 C timing=" + repr(dump(c_timing2)),
        "E2 C depot window=" + repr(c_window2),
    ])
    (OUT / "diagnostic_observations.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "diagnostic_trace.txt").write_text("\n".join(trace) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
