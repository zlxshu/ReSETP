#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    sys.path.insert(0, str(path))

import run_pilot04_rank_aligned_direct as runner
from setp_solver.solution import Route, Solution


def test_e6_reuses_e3_rank_aligned_mapping_and_original_fleet() -> None:
    bundle, info = runner.load_input()
    original = runner.e3.base.load_bundle(runner.INSTANCE)
    with runner.E3_RESULT.open(encoding="utf-8", newline="") as handle:
        expected_hash = next(csv.DictReader(handle))["mapping_sha256"]

    assert info["label_to_depot"] == {
        0: "D_shenzhen",
        1: "D_guangzhou",
        2: "D_dongguan",
        3: "D_foshan",
    }
    assert info["mapping_sha256"] == expected_hash
    assert {
        depot: dict(caps) for depot, caps in bundle.fleet_caps_by_depot.items()
    } == {depot: dict(caps) for depot, caps in original.fleet_caps_by_depot.items()}
    assert bundle.prices.cross_site_cost == 0.0


def test_quick_five_precede_all_fifteen_coalitions() -> None:
    members = ("A", "B", "C", "D")
    assert runner.quick_groups(members) == (
        ("A",),
        ("B",),
        ("C",),
        ("D",),
        members,
    )
    assert len(runner.coalitions(members)) == 15


def test_theta_grid_is_exactly_zero_to_one_by_point_zero_five() -> None:
    grid = runner.theta_grid(0.05)
    assert len(grid) == 21
    assert grid[0] == 0.0
    assert grid[-1] == 1.0


def test_transfer_diagnostic_reports_quantities_without_a_price() -> None:
    bundle, _ = runner.load_input()
    owner = "D_shenzhen"
    serving = "D_guangzhou"
    customer = next(
        customer
        for customer, depot in bundle.customer_home_depot.items()
        if depot == owner
    )
    route = Route("TEST-CV", "cv", serving, [serving, customer, serving])
    rows = runner.transfer_rows(bundle, Solution(routes=[route]))
    positive = [row for row in rows if row["customer_count"]]
    demand = next(
        node.demand for node in bundle.instance.nodes if node.node_id == customer
    )

    assert len(rows) == 12
    assert positive == [
        {
            "original_owner": owner,
            "actual_service_depot": serving,
            "quantity_kg": float(demand),
            "customer_count": 1,
            "directed_road_distance_km": bundle.instance.distance(owner, serving)
            / 1000.0,
        }
    ]
    assert all("cost" not in key and "price" not in key for key in rows[0])
