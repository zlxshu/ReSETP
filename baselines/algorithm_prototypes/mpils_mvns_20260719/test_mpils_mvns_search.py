"""Connection and behaviour tests for the first MPILS-MVNS candidate."""

from __future__ import annotations

import inspect
import math
from pathlib import Path
import sys

import pyvrp
from pyvrp import (
    IteratedLocalSearch,
    Model,
    PenaltyManager,
    RandomNumberGenerator,
    Route,
    Solution,
    SolveParams,
)
from pyvrp.stop import MaxIterations


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mpils_mvns_search import (  # noqa: E402
    MECHANISM_ORDER,
    NOT_APPLICABLE,
    MechanismContext,
    MechanismLedger,
    MPILSMVNSSearch,
    MultiPopulationArchive,
    ResponsibilitySegmentExpert,
    canonical_signature,
)
from run_mpils_mvns_worker import build_local_search  # noqa: E402


def make_data(*, multidepot: bool) -> pyvrp.ProblemData:
    model = Model()
    depots = [model.add_depot(0, 0, name="D0")]
    if multidepot:
        depots.append(model.add_depot(100, 0, name="D1"))

    if multidepot:
        coordinates = [(5, 0), (95, 0), (94, 2), (96, -2)]
    else:
        coordinates = [
            (5, 0),
            (10, 2),
            (15, -2),
            (20, 1),
            (25, -1),
            (30, 0),
        ]
    clients = [
        model.add_client(
            x,
            y,
            delivery=1,
            tw_early=0,
            tw_late=10_000,
            name=f"C{index}",
        )
        for index, (x, y) in enumerate(coordinates)
    ]

    for depot in depots:
        model.add_vehicle_type(
            num_available=3,
            capacity=5,
            start_depot=depot,
            end_depot=depot,
        )

    locations = [*depots, *clients]
    for source in locations:
        for target in locations:
            distance = int(
                round(
                    math.hypot(
                        float(source.x - target.x),
                        float(source.y - target.y),
                    )
                    * 10
                )
            )
            model.add_edge(
                source,
                target,
                distance=distance,
                duration=distance,
            )
    return model.data()


def make_multidepot_solutions(
    data: pyvrp.ProblemData,
) -> tuple[Solution, Solution]:
    wrong = Solution(
        data,
        [
            Route(data, [2, 4, 5], 0),
            Route(data, [3], 1),
        ],
    )
    corrected = Solution(
        data,
        [
            Route(data, [2], 0),
            Route(data, [3, 4, 5], 1),
        ],
    )
    assert wrong.is_complete() and wrong.is_feasible()
    assert corrected.is_complete() and corrected.is_feasible()
    return wrong, corrected


def run_fixed_iterations(
    data: pyvrp.ProblemData,
    *,
    full: bool,
    seed: int = 7,
) -> tuple[Solution, MPILSMVNSSearch | None]:
    params = SolveParams()
    rng = RandomNumberGenerator(seed=seed)
    base_search = build_local_search(data, rng, params)
    penalties = PenaltyManager.init_from(data, params.penalty)
    initial = base_search(
        Solution.make_random(data, rng),
        penalties.max_cost_evaluator(),
        exhaustive=True,
    )
    wrapper = None
    search_method = base_search
    if full:
        expert_rng = RandomNumberGenerator(seed=seed + 1_000_003)
        expert_search = build_local_search(
            data,
            expert_rng,
            params,
        )
        wrapper = MPILSMVNSSearch(
            base_search,
            expert_search,
            data=data,
            context=MechanismContext.from_public_v13(data),
            initial_solution=initial,
            stagnation_threshold=8,
        )
        search_method = wrapper
    result = IteratedLocalSearch(
        data,
        penalties,
        rng,
        search_method,
        initial,
        params.ils,
    ).run(
        MaxIterations(120),
        collect_stats=False,
        display=False,
        display_interval=params.display_interval,
    )
    return result.best, wrapper


def test_all_mechanisms_are_consulted_and_naturally_skip() -> None:
    data = make_data(multidepot=False)
    context = MechanismContext.from_public_v13(data)
    ledger = MechanismLedger()
    ledger.begin_call(context)
    ledger.finish_call()
    diagnostics = ledger.diagnostics(context)

    assert tuple(diagnostics["mechanism_order"]) == MECHANISM_ORDER
    assert all(
        diagnostics["consultations"][mechanism] == 1
        for mechanism in MECHANISM_ORDER
    )
    assert all(
        diagnostics["status_counts"][mechanism][NOT_APPLICABLE] == 1
        for mechanism in MECHANISM_ORDER
    )


def test_naturally_inapplicable_full_path_matches_mother() -> None:
    data = make_data(multidepot=False)
    mother, _ = run_fixed_iterations(data, full=False)
    full, wrapper = run_fixed_iterations(data, full=True)

    assert canonical_signature(full) == canonical_signature(mother)
    assert full.distance() == mother.distance()
    assert wrapper is not None
    diagnostics = wrapper.diagnostics()
    assert diagnostics["expert_triggers"] == 0
    assert all(
        count == diagnostics["calls"]
        for count in diagnostics["mechanisms"]["consultations"].values()
    )


def test_responsibility_expert_changes_depot_assignment() -> None:
    data = make_data(multidepot=True)
    wrong, _ = make_multidepot_solutions(data)
    evaluator = PenaltyManager.init_from(data).max_cost_evaluator()
    expert = ResponsibilitySegmentExpert(
        data,
        max_source_segments=12,
        max_target_routes=3,
    )
    candidate = expert.propose(
        wrong,
        evaluator,
        segment_length=2,
    )

    assert candidate is not None
    assert candidate.is_complete() and candidate.is_feasible()
    assert canonical_signature(candidate) != canonical_signature(wrong)
    moved = {
        client: route.start_depot()
        for route in candidate.routes()
        for client in route.visits()
    }
    assert moved[4] == 1
    assert moved[5] == 1
    assert sorted(moved) == [2, 3, 4, 5]


def test_three_populations_receive_unique_solutions() -> None:
    data = make_data(multidepot=True)
    wrong, corrected = make_multidepot_solutions(data)
    archive = MultiPopulationArchive(per_population_limit=4)

    assert archive.remember(wrong)
    assert archive.remember(corrected)
    assert not archive.remember(corrected)
    diagnostics = archive.diagnostics()
    assert diagnostics["unique_insertions"] == 2
    assert all(
        diagnostics["sizes"][population] >= 1
        for population in ("quality", "depot", "diversity")
    )


def test_full_constructor_has_no_mechanism_disable_switch() -> None:
    parameters = inspect.signature(MPILSMVNSSearch).parameters
    forbidden = {
        "mechanisms_enabled",
        "disable_mechanisms",
        "mechanism_switch",
    }
    assert forbidden.isdisjoint(parameters)


def main() -> int:
    tests = (
        test_all_mechanisms_are_consulted_and_naturally_skip,
        test_naturally_inapplicable_full_path_matches_mother,
        test_responsibility_expert_changes_depot_assignment,
        test_three_populations_receive_unique_solutions,
        test_full_constructor_has_no_mechanism_disable_switch,
    )
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
