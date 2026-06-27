from __future__ import annotations

import unittest

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.route_pool_sp import (
    RoutePoolEntry,
    build_route_pool,
    coverage_matrix,
    dedupe_route_pool,
    rebuild_solution_from_entries,
    single_route_cost,
    solve_route_pool_sp,
    station_capacity_matrix,
)
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id


def _instance(*, num_cv: int | None = 1, num_ev: int | None = 1) -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0, station_chargers=10),
        Node("C1", "c", 1.0, 0.0, demand=100.0, due_time=100_000.0),
        Node("C2", "c", 2.0, 0.0, demand=100.0, due_time=100_000.0),
        Node("F1", "f", 1.0, 1.0, due_time=100_000.0, charge_power_kw=60.0, station_chargers=1),
    ]
    matrix = [
        [0.0, 100.0, 200.0, 100.0],
        [100.0, 0.0, 100.0, 100.0],
        [200.0, 100.0, 0.0, 100.0],
        [100.0, 100.0, 100.0, 0.0],
    ]
    return Instance(nodes=nodes, distance_matrix=matrix, num_cv=num_cv, num_ev=num_ev)


def _profile() -> list[dict[str, float]]:
    return [
        {
            "time_index": idx,
            "horizon_second_start": float(idx * 1800),
            "actual_gco2_per_kwh": 100.0,
        }
        for idx in range(48)
    ]


def _entry(entry_id: str, customers: list[str], cost: float, *, vehicle_type: str = "cv", action: ChargingAction | None = None) -> RoutePoolEntry:
    route = Route(entry_id, vehicle_type, "D0", ["D0", *customers, "D0"])
    return RoutePoolEntry(
        entry_id=entry_id,
        route=route,
        charging_actions=() if action is None else (action,),
        customer_ids=tuple(customers),
        vehicle_type=vehicle_type,
        cost=float(cost),
        source="test",
    )


class RoutePoolSpTests(unittest.TestCase):
    def test_coverage_matrix_and_sp_choose_exact_cover_route(self) -> None:
        instance = _instance()
        entries = (
            _entry("r1", ["C1"], 10.0),
            _entry("r2", ["C2"], 10.0),
            _entry("r12", ["C1", "C2"], 15.0),
        )

        matrix = coverage_matrix(entries, ("C1", "C2")).toarray()
        result = solve_route_pool_sp(entries, instance, milp_time_limit_seconds=10.0)

        self.assertEqual(matrix.tolist(), [[1.0, 0.0, 1.0], [0.0, 1.0, 1.0]])
        self.assertEqual(tuple(entries[idx].entry_id for idx in result.selected_indices), ("r12",))

    def test_station_capacity_matrix_blocks_same_slot_public_charging(self) -> None:
        instance = _instance()
        action_1 = ChargingAction("EV1", "F1", 5.0, 30.0, 0.0)
        action_2 = ChargingAction("EV2", "F1", 5.0, 30.0, 0.0)
        entries = (
            _entry("ev_c1", ["C1"], 1.0, vehicle_type="ev", action=action_1),
            _entry("ev_c2", ["C2"], 1.0, vehicle_type="ev", action=action_2),
            _entry("cv_c2", ["C2"], 5.0),
        )

        cap_matrix, bounds = station_capacity_matrix(entries, instance)
        result = solve_route_pool_sp(entries, instance, milp_time_limit_seconds=10.0)

        self.assertEqual(cap_matrix.shape[0], 1)
        self.assertEqual(bounds, [1.0])
        self.assertEqual(set(entries[idx].entry_id for idx in result.selected_indices), {"ev_c1", "cv_c2"})

    def test_dedupe_keeps_cheapest_and_retains_alternate(self) -> None:
        expensive = _entry("expensive", ["C1"], 10.0)
        cheap = RoutePoolEntry(
            entry_id="cheap",
            route=Route("cheap", "cv", "D0", ["D0", "F1", "C1", "D0"]),
            charging_actions=(),
            customer_ids=("C1",),
            vehicle_type="cv",
            cost=5.0,
            source="test",
        )

        pool = dedupe_route_pool((expensive, cheap), raw_entry_count=2)

        self.assertEqual(len(pool.entries), 1)
        self.assertEqual(pool.entries[0].entry_id, "cheap")
        self.assertEqual(pool.alternates[pool.entries[0].key][0].entry_id, "expensive")

    def test_fallback_entries_make_empty_pool_coverable(self) -> None:
        instance = _instance()

        pool = build_route_pool([], instance, _profile(), DEFAULT_PRICES, include_fallback=True)
        result = solve_route_pool_sp(pool.entries, instance, milp_time_limit_seconds=10.0)

        self.assertEqual(pool.fallback_failed_customers, ())
        self.assertEqual(len(result.selected_indices), 2)
        self.assertEqual({pool.entries[idx].customer_ids[0] for idx in result.selected_indices}, {"C1", "C2"})

    def test_rebuild_retags_routes_to_physical_fleet_cap_and_checks(self) -> None:
        instance = _instance(num_cv=1, num_ev=0)
        entries = (
            _entry("r1", ["C1"], 10.0),
            _entry("r2", ["C2"], 10.0),
        )

        rebuilt = rebuild_solution_from_entries(entries, (0, 1), instance, _profile(), DEFAULT_PRICES)

        self.assertEqual(rebuilt.violations, ())
        physical_ids = {physical_vehicle_id(route.vehicle_id) for route in rebuilt.solution.routes}
        self.assertEqual(physical_ids, {"CV1"})
        self.assertEqual(check_solution(rebuilt.solution, instance, DEFAULT_PRICES), [])

    def test_single_route_cost_is_additive_under_zero_quota(self) -> None:
        instance = _instance(num_cv=2, num_ev=0)
        route_1 = Route("CV1", "cv", "D0", ["D0", "C1", "D0"])
        route_2 = Route("CV2", "cv", "D0", ["D0", "C2", "D0"])
        solution = Solution(routes=[route_1, route_2])

        full_cost = evaluate(solution, instance, _profile(), DEFAULT_PRICES, carbon_quota_kg=0.0)["total_cost"]
        route_cost = single_route_cost(route_1, (), instance, _profile(), DEFAULT_PRICES) + single_route_cost(route_2, (), instance, _profile(), DEFAULT_PRICES)

        self.assertAlmostEqual(full_cost, route_cost, places=9)


if __name__ == "__main__":
    unittest.main()
