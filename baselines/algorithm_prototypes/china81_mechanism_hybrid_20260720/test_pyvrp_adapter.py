from __future__ import annotations

from pathlib import Path

from pyvrp import Solution as PyVRPSolution

from pyvrp_adapter import (
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
    run_pyvrp_hgs_skeleton,
)
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score


ROOT = Path(__file__).resolve().parents[3]
INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"


def _fixture():
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    initial = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    return bundle, initial


def test_initial_projection_round_trip_preserves_customer_service() -> None:
    bundle, initial = _fixture()
    problem = build_pyvrp_problem(bundle)
    data = problem.model.data()

    projected = _project_initial_solution(initial, data, problem)
    assert isinstance(projected, PyVRPSolution)
    restored = _translate_solution(projected, problem)

    expected = sorted(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    observed = sorted(
        node_id
        for route in restored.routes
        for node_id in route.node_sequence[1:-1]
    )
    assert observed == expected


def test_pyvrp_result_passes_shared_full_completion() -> None:
    bundle, initial = _fixture()

    run = run_pyvrp_hgs_skeleton(
        bundle,
        initial,
        seed=1,
        runtime_seconds=0.10,
    )

    objective, breakdown, violations = exact_china81_score(
        run.completion.solution,
        bundle,
    )
    assert run.pyvrp_feasible
    assert not violations
    assert objective == run.completion.objective
    assert breakdown == run.completion.breakdown
    assert run.stats["shared_completion_schema"] == (
        "resetp.china81-shared-completion.v1"
    )


def test_hard_home_depot_lock_is_encoded_in_capacity_dimensions() -> None:
    bundle = load_china81_bundle(
        ROOT,
        "cn-prd-50c-01-V2-LOCATIONS",
    )
    unlocked = build_pyvrp_problem(
        bundle,
        hard_home_depot_lock=False,
    ).model.data()
    locked = build_pyvrp_problem(
        bundle,
        hard_home_depot_lock=True,
    ).model.data()
    depots = list(locked.depots())
    depot_index = {
        depot.name: index
        for index, depot in enumerate(depots)
    }

    assert unlocked.num_load_dimensions == 1
    assert locked.num_load_dimensions == 1 + len(depots)
    for client in locked.clients():
        owner = bundle.customer_home_depot[client.name]
        owner_dimension = 1 + depot_index[owner]
        assert client.delivery[owner_dimension] == 1
        assert sum(client.delivery[1:]) == 1

    for vehicle_type in locked.vehicle_types():
        home_depot = depots[vehicle_type.start_depot].name
        assert vehicle_type.start_depot == vehicle_type.end_depot
        for depot_id, index in depot_index.items():
            capacity = vehicle_type.capacity[1 + index]
            assert (capacity > 0) == (depot_id == home_depot)
