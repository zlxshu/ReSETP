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
