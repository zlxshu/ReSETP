from __future__ import annotations

import unittest
from pathlib import Path

from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import SearchBundle
from setp_solver.search import metaheuristic_baselines as mb
from setp_solver.solution import Solution


def _two_customer_bundle() -> SearchBundle:
    nodes = [
        Node("D0", "d", 0.0, 0.0, demand=0.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
        Node("C1", "c", 1000.0, 100.0, demand=10.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
        Node("C2", "c", 1100.0, 0.0, demand=10.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
    ]
    matrix = [
        [0.0, 1004.987562112089, 1100.0],
        [1004.987562112089, 0.0, 141.4213562373095],
        [1100.0, 141.4213562373095, 0.0],
    ]
    return SearchBundle(
        bundle_dir=Path("."),
        instance=Instance(nodes=nodes, distance_matrix=matrix, num_cv=3, num_ev=0),
        carbon_profile=[],
    )


def _absolute_distance_append(customer_id: str, plans: dict[str, list[list[str]]], session: mb._SearchSession) -> None:
    best: tuple[float, str, int | None] | None = None
    for depot_id in session.depots_by_customer[customer_id]:
        depot_plans = plans[depot_id]
        for idx, customer_ids in enumerate(depot_plans):
            candidate = (*customer_ids, customer_id)
            if mb._route_customer_plan_feasible_cached(depot_id, candidate, session):
                key = (mb._route_distance_cached(depot_id, candidate, session), depot_id, idx)
                if best is None or key < best:
                    best = key
        single = (customer_id,)
        if mb._route_customer_plan_feasible_cached(depot_id, single, session):
            key = (mb._route_distance_cached(depot_id, single, session), depot_id, None)
            if best is None or key < best:
                best = key
    if best is None:
        plans[session.depots_by_customer[customer_id][0]].append([customer_id])
        return
    _, depot_id, route_idx = best
    if route_idx is None:
        plans[depot_id].append([customer_id])
    else:
        plans[depot_id][route_idx].append(customer_id)


class DecoderMarginalRepairTest(unittest.TestCase):
    def test_absolute_distance_reproducer_splits_adjacent_customers(self) -> None:
        bundle = _two_customer_bundle()
        session = mb._SearchSession("GA", bundle, 1, 8, 120.0, Solution(), prices=DEFAULT_PRICES)
        plans: dict[str, list[list[str]]] = {"D0": []}

        for customer_id in ("C1", "C2"):
            _absolute_distance_append(customer_id, plans, session)

        self.assertEqual(plans["D0"], [["C1"], ["C2"]])

    def test_decoder_uses_marginal_route_cost_and_merges_adjacent_customers(self) -> None:
        bundle = _two_customer_bundle()
        session = mb._SearchSession("GA", bundle, 1, 8, 120.0, Solution(), prices=DEFAULT_PRICES)
        plans: dict[str, list[list[str]]] = {"D0": []}

        for customer_id in ("C1", "C2"):
            mb._append_customer_to_cached_plan(customer_id, plans, session)

        self.assertEqual(plans["D0"], [["C1", "C2"]])


if __name__ == "__main__":
    unittest.main()
