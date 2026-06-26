from __future__ import annotations

import unittest

from setp_solver.check import DynamicCheckContext, DynamicVehicleState, FairnessContext, Violation, check_solution, ev_arc_energy_kwh
from setp_solver.cost import ev_arc_energy_kwh as cost_ev_arc_energy_kwh
from setp_solver.cost import route_node_schedule
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.solution import ChargingAction, Route, Solution


def _instance(
    *,
    c1_demand: float = 500.0,
    c1_due: float = 10_000.0,
    c2_demand: float = 200.0,
    ev_distance_scale: float = 1.0,
) -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, demand=0.0, ready_time=0.0, due_time=10_000.0, service_time=0.0),
        Node("C1", "c", 1000.0, 0.0, demand=c1_demand, ready_time=0.0, due_time=c1_due, service_time=0.0),
        Node("C2", "c", 0.0, 1000.0, demand=c2_demand, ready_time=0.0, due_time=10_000.0, service_time=0.0),
        Node("F1", "f", 500.0, 500.0, demand=0.0, ready_time=0.0, due_time=10_000.0, service_time=0.0, charge_power_kw=60.0),
    ]
    ev = ev_distance_scale
    matrix = [
        [0.0, 1000.0, 1000.0 * ev, 500.0 * ev],
        [1000.0, 0.0, 1500.0, 1000.0],
        [1000.0 * ev, 1500.0, 0.0, 500.0 * ev],
        [500.0 * ev, 1000.0, 500.0 * ev, 0.0],
    ]
    return Instance(nodes=nodes, distance_matrix=matrix)


def _legal_solution() -> Solution:
    return Solution(
        routes=[
            Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
            Route("EV1", "ev", "D0", ["D0", "C2", "F1", "D0"]),
        ],
        charging_actions=[
            # v2026-06-12: S0 depot charge belongs to the overnight return-to-next-departure window.
            ChargingAction("EV1", "D0", energy_kwh=1.0, occupancy_minutes=3.0, charge_start_second=900.0),
            ChargingAction("EV1", "F1", energy_kwh=0.5, occupancy_minutes=5.0, charge_start_second=300.0),
        ],
    )


def _types(violations: list[Violation]) -> set[str]:
    return {violation.type for violation in violations}


def _assert_only_violation(testcase: unittest.TestCase, violations: list[Violation], expected_type: str) -> Violation:
    testcase.assertFalse(len(violations) == 0)
    testcase.assertEqual({violation.type for violation in violations}, {expected_type})
    return next(violation for violation in violations if violation.type == expected_type)


class CheckSolutionTests(unittest.TestCase):
    # v2026-06-11: normalize hard-constraint type names to the paper-facing enum strings.
    def test_legal_solution_has_no_hard_violations(self) -> None:
        self.assertEqual(check_solution(_legal_solution(), _instance()), [])

    def test_detects_overload(self) -> None:
        violations = check_solution(_legal_solution(), _instance(c1_demand=1700.0))
        self.assertIn("CAPACITY", _types(violations))
        self.assertTrue(any(v.vehicle_id == "CV1" and "initial load" in v.detail for v in violations))

    def test_detects_late_service(self) -> None:
        violations = check_solution(_legal_solution(), _instance(c1_due=10.0))
        self.assertIn("TIME_WINDOW", _types(violations))
        self.assertTrue(any(v.location == "C1" for v in violations))
        self.assertTrue(any("late by" in v.detail for v in violations if v.type == "TIME_WINDOW"))

    def test_detects_ev_battery_depletion(self) -> None:
        violations = check_solution(_legal_solution(), _instance(ev_distance_scale=500.0))
        self.assertIn("BATTERY", _types(violations))
        self.assertTrue(any(v.vehicle_id == "EV1" for v in violations))

    def test_detects_missing_customer(self) -> None:
        solution = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "C1", "D0"])])
        violations = check_solution(solution, _instance())
        self.assertIn("CUSTOMER_COVERAGE", _types(violations))
        self.assertTrue(any(v.location == "C2" and "not served" in v.detail for v in violations))

    def test_detects_duplicate_customer(self) -> None:
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("EV1", "ev", "D0", ["D0", "C1", "C2", "D0"]),
            ]
        )
        violations = check_solution(solution, _instance())
        self.assertIn("CUSTOMER_COVERAGE", _types(violations))
        self.assertTrue(any(v.location == "C1" and "served 2 times" in v.detail for v in violations))

    def test_detects_fleet_size_cap_violation(self) -> None:
        base = _instance()
        instance = Instance(nodes=base.nodes, distance_matrix=base.distance_matrix, num_cv=1, num_ev=1)
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("EV1", "ev", "D0", ["D0", "C2", "D0"]),
                Route("EV2", "ev", "D0", ["D0", "F1", "D0"]),
            ]
        )

        violations = check_solution(solution, instance)

        self.assertIn("FLEET_SIZE", _types(violations))
        self.assertTrue(any(v.location == "ev" and "exceed available electric vehicles" in v.detail for v in violations))

    # v2026-06-12: W2b rolling stages can start from inherited vehicle positions.
    def test_dynamic_context_allows_open_start_from_vehicle_position(self) -> None:
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["F1", "C1", "D0"]),
                Route("CV2", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )
        static_violations = check_solution(solution, _instance())
        self.assertIn("FLOW_BALANCE", _types(static_violations))

        dynamic = DynamicCheckContext(
            vehicle_states={
                "CV1": DynamicVehicleState(
                    vehicle_id="CV1",
                    position_node_id="F1",
                    current_time=0.0,
                    remaining_load_kg=500.0,
                    remaining_battery_kwh=0.0,
                )
            },
            allow_open_start=True,
        )

        dynamic_violations = check_solution(solution, _instance(), dynamic_context=dynamic)
        self.assertNotIn("FLOW_BALANCE", _types(dynamic_violations))

    # v2026-06-12: W2b frozen route prefixes are hard audit constraints.
    def test_dynamic_context_rejects_changed_frozen_prefix(self) -> None:
        dynamic = DynamicCheckContext(frozen_prefixes={"CV1": ("D0", "C2")})

        violations = check_solution(_legal_solution(), _instance(), dynamic_context=dynamic)

        self.assertIn("ROUTE_STRUCTURE", _types(violations))
        self.assertTrue(any("frozen prefix" in violation.detail for violation in violations))

    def test_ev_energy_matches_cost_module_for_same_arc(self) -> None:
        self.assertAlmostEqual(ev_arc_energy_kwh(1000.0, 200.0), cost_ev_arc_energy_kwh(1000.0, 200.0), places=9)

    # v2026-06-11: add shared route schedule coverage for service_time-aware time recursion.
    def test_schedule_correct(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, ready_time=100.0, due_time=10_000.0, service_time=0.0),
                Node("C1", "c", 0.0, 0.0, ready_time=200.0, due_time=10_000.0, service_time=600.0),
                Node("C2", "c", 0.0, 0.0, ready_time=0.0, due_time=10_000.0, service_time=120.0),
            ],
            distance_matrix=[
                [0.0, 250.0, 0.0],
                [250.0, 0.0, 500.0],
                [0.0, 500.0, 0.0],
            ],
        )
        schedule = route_node_schedule(Route("CV1", "cv", "D0", ["D0", "C1", "C2"]), instance)
        expected = [
            ("D0", 100.0, 100.0, 100.0),
            ("C1", 110.0, 200.0, 800.0),
            ("C2", 820.0, 820.0, 940.0),
        ]
        for row, (node_id, arrive, start, depart) in zip(schedule, expected):
            self.assertEqual(row.node_id, node_id)
            self.assertAlmostEqual(row.t_arrive, arrive, delta=1e-9)
            self.assertAlmostEqual(row.t_start, start, delta=1e-9)
            self.assertAlmostEqual(row.t_depart, depart, delta=1e-9)

    # v2026-06-11: prove customer service time pushes all downstream arrivals cumulatively.
    def test_service_time_applied(self) -> None:
        def make_instance(service_time: float) -> Instance:
            return Instance(
                nodes=[
                    Node("D0", "d", 0.0, 0.0, service_time=0.0),
                    Node("C1", "c", 0.0, 0.0, service_time=service_time),
                    Node("C2", "c", 0.0, 0.0, service_time=service_time),
                    Node("D1", "d", 0.0, 0.0, service_time=0.0),
                ],
                distance_matrix=[
                    [0.0, 250.0, 0.0, 0.0],
                    [250.0, 0.0, 250.0, 0.0],
                    [0.0, 250.0, 0.0, 250.0],
                    [0.0, 0.0, 250.0, 0.0],
                ],
            )

        route = Route("CV1", "cv", "D0", ["D0", "C1", "C2", "D1"])
        zero = route_node_schedule(route, make_instance(0.0))
        slow = route_node_schedule(route, make_instance(600.0))

        self.assertAlmostEqual(slow[2].t_arrive - zero[2].t_arrive, 600.0, delta=1e-9)
        self.assertAlmostEqual(slow[3].t_arrive - zero[3].t_arrive, 1200.0, delta=1e-9)

    # v2026-06-11: CHARGING_START rejects charging before physical station arrival.
    def test_charging_start_before_arrival(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, service_time=0.0),
                Node("F1", "f", 0.0, 0.0, service_time=0.0, charge_power_kw=60.0),
            ],
            distance_matrix=[
                [0.0, 1000.0],
                [1000.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=1.0, occupancy_minutes=1.0, charge_start_second=10.0)
            ],
        )

        violations = check_solution(solution, instance)

        self.assertIn("CHARGING_START", _types(violations))
        self.assertTrue(any(v.location == "F1" and "early by" in v.detail for v in violations))

    # v2026-06-11: CHARGING_POWER uses station charge_power_kw and shared slot split.
    def test_charging_power_cap(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, service_time=0.0),
                Node("F1", "f", 0.0, 0.0, service_time=0.0, charge_power_kw=60.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=40.0, occupancy_minutes=30.0, charge_start_second=0.0)
            ],
        )

        violations = check_solution(solution, instance)

        self.assertIn("CHARGING_POWER", _types(violations))
        self.assertTrue(any(v.location == "F1" and "exceeds" in v.detail for v in violations))

    # v2026-06-11: CHARGING_POWER under uniform-rate B-full semantics reports one violation per action.
    def test_charging_power_cap_reports_one_violation_per_action(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, service_time=0.0),
                Node("F1", "f", 0.0, 0.0, service_time=0.0, charge_power_kw=60.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=40.0, occupancy_minutes=30.0, charge_start_second=1790.0)
            ],
        )

        violations = [violation for violation in check_solution(solution, instance) if violation.type == "CHARGING_POWER"]

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].vehicle_id, "EV1")
        self.assertEqual(violations[0].location, "F1")
        self.assertIn("rate", violations[0].detail)

    # v2026-06-12: S0 depot overnight charge must finish before next-day departure.
    def test_depot_charging_must_finish_before_departure_deadline(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, service_time=0.0, due_time=100_000.0),
                Node("C1", "c", 0.0, 0.0, service_time=0.0, due_time=10_000.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "D0", energy_kwh=1.0, occupancy_minutes=1.0, charge_start_second=86_370.0)
            ],
        )

        violations = check_solution(solution, instance)

        self.assertIn("CHARGING_START", _types(violations))
        self.assertTrue(any(v.location == "D0" and "departure" in v.detail for v in violations))

    # v2026-06-12: S0 depot overnight charge cannot begin before the previous shift returns.
    def test_depot_charging_before_return_triggers(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, service_time=0.0, due_time=100_000.0),
                Node("C1", "c", 0.0, 0.0, service_time=0.0, due_time=10_000.0),
            ],
            distance_matrix=[
                [0.0, 1000.0],
                [1000.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "D0", energy_kwh=0.1, occupancy_minutes=1.0, charge_start_second=40.0)
            ],
        )

        violations = check_solution(solution, instance)

        self.assertIn("CHARGING_START", _types(violations))
        self.assertTrue(any(v.location == "D0" and "return" in v.detail for v in violations))

    # v2026-06-12: Q2 depot precharge uses pi_d=22 kW and start battery bbar + depot charge <= B.
    def test_depot_charging_power_and_battery_upper_bound(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, service_time=0.0, due_time=10_000.0),
                Node("C1", "c", 0.0, 0.0, service_time=0.0, due_time=10_000.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "D0", energy_kwh=281.0, occupancy_minutes=30.0, charge_start_second=0.0)
            ],
        )

        violations = check_solution(solution, instance)

        self.assertIn("CHARGING_POWER", _types(violations))
        self.assertIn("BATTERY", _types(violations))
        self.assertTrue(any(v.location == "D0" and "pi_d" in v.detail for v in violations))
        self.assertTrue(any(v.location == "D0" and "start battery" in v.detail for v in violations))

    # v2026-06-11: charging wait plus occupancy must push every downstream schedule time.
    def test_schedule_push_by_charging(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, service_time=0.0),
                Node("F1", "f", 0.0, 0.0, service_time=0.0, charge_power_kw=60.0),
                Node("C1", "c", 0.0, 0.0, service_time=0.0),
            ],
            distance_matrix=[
                [0.0, 500.0, 0.0],
                [500.0, 0.0, 1000.0],
                [0.0, 1000.0, 0.0],
            ],
        )
        route = Route("EV1", "ev", "D0", ["D0", "F1", "C1"])
        no_charge = route_node_schedule(route, instance)
        with_charge = route_node_schedule(
            route,
            instance,
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=1.0, occupancy_minutes=1.0, charge_start_second=120.0)
            ],
        )

        self.assertAlmostEqual(no_charge[2].t_arrive, 60.0, delta=1e-9)
        self.assertAlmostEqual(with_charge[2].t_arrive, 220.0, delta=1e-9)
        self.assertAlmostEqual(with_charge[2].t_arrive - no_charge[2].t_arrive, 160.0, delta=1e-9)

    # v2026-06-11: FLOW_BALANCE trigger coverage for the A-class hard constraint.
    def test_detects_flow_balance_violation(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
                Node("F1", "f", 0.0, 0.0, due_time=10_000.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "F1"])])

        violation = _assert_only_violation(self, check_solution(solution, instance), "FLOW_BALANCE")

        self.assertEqual(violation.vehicle_id, "CV1")
        self.assertIn(violation.location, {"F1", "D0->F1", "D0"})

    # v2026-06-12: fleet count is objective-penalized, not a hard feasibility cap.
    def test_fleet_size_is_not_a_hard_constraint(self) -> None:
        instance = Instance(nodes=[Node("D0", "d", 0.0, 0.0, due_time=10_000.0)], distance_matrix=[[0.0]])
        solution = Solution(routes=[Route(f"CV{i}", "cv", "D0", ["D0", "D0"]) for i in range(11)])

        violations = check_solution(solution, instance)

        self.assertNotIn("FLEET_SIZE", _types(violations))
        self.assertEqual(violations, [])

    # v2026-06-12: Z0b station capacity replaces the old one-visit shortcut.
    def test_repeated_station_visit_without_overlap_is_not_a_uniqueness_violation(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
                Node("F1", "f", 0.0, 0.0, due_time=10_000.0, charge_power_kw=60.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0", "F1", "D0"])])

        violations = check_solution(solution, instance)

        self.assertNotIn("CHARGING_STATION_UNIQUENESS", _types(violations))
        self.assertNotIn("STATION_CAPACITY", _types(violations))

    # v2026-06-12: Z0b public station C_s=1 catches simultaneous half-hour occupancy.
    def test_station_capacity_detects_same_slot_public_station_overlap(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
                Node("F1", "f", 0.0, 0.0, due_time=10_000.0, charge_power_kw=60.0, station_chargers=1),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[
                Route("EV1", "ev", "D0", ["D0", "F1", "D0"]),
                Route("EV2", "ev", "D0", ["D0", "F1", "D0"]),
            ],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=5.0, occupancy_minutes=30.0, charge_start_second=0.0),
                ChargingAction("EV2", "F1", energy_kwh=5.0, occupancy_minutes=30.0, charge_start_second=0.0),
            ],
        )

        violation = _assert_only_violation(self, check_solution(solution, instance), "STATION_CAPACITY")

        self.assertEqual(violation.location, "F1@slot0")
        self.assertIn("C_s=1", violation.detail)

    # v2026-06-12: Z0b capacity is slot-based, so separated public charging is feasible.
    def test_station_capacity_allows_different_slots(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
                Node("F1", "f", 0.0, 0.0, due_time=10_000.0, charge_power_kw=60.0, station_chargers=1),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[
                Route("EV1", "ev", "D0", ["D0", "F1", "D0"]),
                Route("EV2", "ev", "D0", ["D0", "F1", "D0"]),
            ],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=5.0, occupancy_minutes=30.0, charge_start_second=0.0),
                ChargingAction("EV2", "F1", energy_kwh=5.0, occupancy_minutes=30.0, charge_start_second=1800.0),
            ],
        )

        violations = check_solution(solution, instance)

        self.assertNotIn("STATION_CAPACITY", _types(violations))

    # v2026-06-12: Z0b a vehicle counts once per station-slot even with multiple action rows.
    def test_station_capacity_counts_same_vehicle_once_per_slot(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
                Node("F1", "f", 0.0, 0.0, due_time=10_000.0, charge_power_kw=60.0, station_chargers=1),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=1.0, occupancy_minutes=5.0, charge_start_second=0.0),
                ChargingAction("EV1", "F1", energy_kwh=1.0, occupancy_minutes=5.0, charge_start_second=600.0),
            ],
        )

        violations = check_solution(solution, instance)

        self.assertNotIn("STATION_CAPACITY", _types(violations))

    # v2026-06-12: Z0b depots default to a customer-count route upper bound.
    def test_depot_capacity_default_does_not_make_overnight_charging_scarce(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
                Node("C1", "c", 0.0, 0.0, due_time=10_000.0),
                Node("C2", "c", 0.0, 0.0, due_time=10_000.0),
            ],
            distance_matrix=[
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[
                Route("EV1", "ev", "D0", ["D0", "C1", "D0"]),
                Route("EV2", "ev", "D0", ["D0", "C2", "D0"]),
            ],
            charging_actions=[
                ChargingAction("EV1", "D0", energy_kwh=1.0, occupancy_minutes=10.0, charge_start_second=0.0),
                ChargingAction("EV2", "D0", energy_kwh=1.0, occupancy_minutes=10.0, charge_start_second=0.0),
            ],
        )

        violations = check_solution(solution, instance)

        self.assertNotIn("STATION_CAPACITY", _types(violations))

    # v2026-06-11: ROUTE_STRUCTURE trigger coverage for invalid node references.
    def test_detects_route_structure_violation(self) -> None:
        instance = Instance(nodes=[Node("D0", "d", 0.0, 0.0, due_time=10_000.0)], distance_matrix=[[0.0]])
        solution = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "X", "D0"])])

        violation = _assert_only_violation(self, check_solution(solution, instance), "ROUTE_STRUCTURE")

        self.assertEqual(violation.vehicle_id, "CV1")
        self.assertEqual(violation.location, "X")

    # v2026-06-11: BATTERY upper-bound trigger coverage for y_after > B after station charging.
    def test_detects_battery_upper_bound_after_charging(self) -> None:
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
                Node("F1", "f", 0.0, 0.0, due_time=10_000.0, charge_power_kw=60.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=1.0, occupancy_minutes=1.0, charge_start_second=0.0)
            ],
        )

        # v2026-06-12: station upper-bound regression explicitly fixes bbar at B;
        # the default solver state now starts from bbar=0 before depot precharge.
        prices = PriceParameters(B_battery_kwh=80.0, initial_ev_battery_kwh=80.0)
        violation = _assert_only_violation(self, check_solution(solution, instance, prices), "BATTERY")

        self.assertEqual(violation.vehicle_id, "EV1")
        self.assertEqual(violation.location, "F1")
        self.assertIn("after charging", violation.detail)

    # v2026-06-11: legal PASS_ALL regression for added A-class trigger checks.
    def test_legal_solution_still_feasible_after_a_class_coverage_tests(self) -> None:
        self.assertTrue(len(check_solution(_legal_solution(), _instance())) == 0)

    # v2026-06-11: PROFIT_FAIRNESS is frozen off by default; enabling it checks paper eq:fairness.
    def test_profit_fairness_default_frozen_and_enabled_context(self) -> None:
        unfair = FairnessContext(
            depot_profit={"D0": 80.0, "D1": 100.0},
            independent_profit={"D0": 100.0, "D1": 100.0},
            theta=0.9,
        )
        fair = FairnessContext(
            depot_profit={"D0": 95.0, "D1": 100.0},
            independent_profit={"D0": 100.0, "D1": 100.0},
            theta=0.9,
        )

        self.assertEqual(check_solution(_legal_solution(), _instance(), fairness_context=unfair), [])

        violations = check_solution(_legal_solution(), _instance(), fairness_context=unfair, fairness_enabled=True)
        self.assertIn("PROFIT_FAIRNESS", _types(violations))
        self.assertTrue(any(v.location == "D0" for v in violations))
        self.assertFalse(
            any(v.type == "PROFIT_FAIRNESS" for v in check_solution(_legal_solution(), _instance(), fairness_context=fair, fairness_enabled=True))
        )


if __name__ == "__main__":
    unittest.main()
