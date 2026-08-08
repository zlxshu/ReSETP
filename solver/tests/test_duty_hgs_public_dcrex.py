"""One-iteration public-interface test for the formal project algorithm."""

import random
from pathlib import Path

from pyvrp import read
from setp_solver.algorithms.duty_hgs.dcrex import InsertionOperator, RouteGene
from setp_solver.algorithms.duty_hgs.public import (
    _apply_public_insertion_move,
    _evaluate_public_moves,
    _insert_public_customers,
    _public_insertion_moves,
    _public_route_penalised_cost,
    _PublicInsertionWorkspace,
    _solution_genes,
    build_public_dcrex_hgs,
)


def test_public_dcrex_runs_through_pyvrp_local_search() -> None:
    repo = Path(__file__).resolve().parents[2]
    instance = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances/PR17A.vrp"
    )
    data = read(instance, round_func="round")
    result = build_public_dcrex_hgs(
        data,
        seed=11,
        max_iterations=1,
    ).run()
    assert result.iterations == 1
    assert result.termination_status == "MAX_ITERATIONS"
    assert result.best.is_complete()
    assert result.best.is_feasible()
    assert result.best.num_clients() == data.num_clients
    assert result.trajectory[0].insertion_operator in {
        "FBI",
        "IBI",
        "FRI",
        "IRI",
        "RI",
    }


def test_public_dcrex_stops_instead_of_restarting_after_stagnation() -> None:
    repo = Path(__file__).resolve().parents[2]
    instance = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances/PR17A.vrp"
    )
    data = read(instance, round_func="round")
    result = build_public_dcrex_hgs(
        data,
        seed=11,
        max_iterations=100,
        stagnation_patience=1,
    ).run()
    assert result.termination_status == "CONVERGED_NO_IMPROVEMENT"
    assert result.iterations < 100
    assert tuple(row.iteration for row in result.trajectory) == tuple(
        range(1, result.iterations + 1)
    )


def test_compiled_public_insertion_delta_matches_full_route_rebuild() -> None:
    repo = Path(__file__).resolve().parents[2]
    instance = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances/PR17A.vrp"
    )
    data = read(instance, round_func="round")
    algorithm = build_public_dcrex_hgs(
        data,
        seed=11,
        max_iterations=1,
    )
    vehicle = data.vehicle_type(0)
    first_customer = data.num_depots
    routes = (
        RouteGene(
            "r0",
            tuple(range(first_customer, first_customer + 5)),
            int(vehicle.start_depot),
            int(vehicle.end_depot),
            0,
        ),
    )
    inserted = first_customer + 5
    moves = _public_insertion_moves(
        data,
        routes,
        inserted,
        allow_new=False,
    )
    rows = _evaluate_public_moves(
        data,
        moves,
        inserted,
        routes,
        algorithm.cost_evaluator,
    )
    base_cost = _public_route_penalised_cost(
        data,
        routes[0],
        algorithm.cost_evaluator,
    )[1]
    for row in rows:
        rebuilt = _apply_public_insertion_move(routes, row[3])[0]
        feasible, candidate_cost = _public_route_penalised_cost(
            data,
            rebuilt,
            algorithm.cost_evaluator,
        )
        assert row[1] is feasible
        assert row[2] == candidate_cost - base_cost


def test_reused_public_insertion_workspace_preserves_dcrex_choices() -> None:
    repo = Path(__file__).resolve().parents[2]
    instance = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances/PR17A.vrp"
    )
    data = read(instance, round_func="round")
    algorithm = build_public_dcrex_hgs(
        data,
        seed=11,
        max_iterations=1,
    )
    genes = _solution_genes(algorithm.initial_solutions[0])
    removed = {
        customer
        for gene in genes
        for customer in gene.customer_ids
        if customer % 17 == 0
    }
    trimmed = tuple(
        RouteGene(
            gene.route_id,
            tuple(
                customer for customer in gene.customer_ids if customer not in removed
            ),
            gene.start_depot,
            gene.end_depot,
            gene.vehicle_type,
        )
        for gene in genes
        if any(customer not in removed for customer in gene.customer_ids)
    )
    missing = tuple(sorted(removed))
    expected = _insert_public_customers(
        data,
        trimmed,
        missing,
        InsertionOperator.FRI,
        random.Random(19),
        algorithm.cost_evaluator,
    )
    workspace = _PublicInsertionWorkspace(data, algorithm.cost_evaluator)
    actual = _insert_public_customers(
        data,
        trimmed,
        missing,
        InsertionOperator.FRI,
        random.Random(19),
        algorithm.cost_evaluator,
        workspace=workspace,
    )
    workspace.close()
    assert actual == expected
