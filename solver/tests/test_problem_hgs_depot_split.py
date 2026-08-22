"""Native incremental cross-depot duty assignment tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from setp_hgs_kernel import (
    CostEvaluator,
    Model,
    RandomNumberGenerator,
    Route,
    Solution,
    Trip,
)
from setp_hgs_kernel.search import DepotSplit, LocalSearch, compute_neighbours


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import _build_context, _policy  # noqa: E402
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
    _migration_components,
)
from setp_solver.algorithms.problem_hgs.operators import (  # noqa: E402
    DutySkeletonMove,
    OpenTripMove,
    RelocateMove,
    WholeTripExchangeMove,
)
from setp_solver.algorithms.problem_hgs.proposals import (  # noqa: E402
    MechanismProposalEngine,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"


@pytest.fixture(scope="module")
def rebuilt_context():
    repo = Path(__file__).parents[2]
    return _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )


def _customer_depot_by_id(individual) -> dict[str, str]:
    return {
        customer_id: duty.home_depot_id
        for duty in individual.duties
        for trip in duty.trips
        for customer_id in trip.customer_ids
    }


def _depot_split_candidate(rebuilt_context):
    bundle, initial, _neutral, context = rebuilt_context
    duties = {duty.physical_vehicle_id: duty for duty in initial.duties}
    source = duties["CV_D_guangzhou_4"]
    target = duties["CV_D_foshan_3"]
    assert len(source.trips) == 1
    assert not target.trips

    misplaced = DutySkeletonMove(
        action_id="fixture-misplace-gz-customers-at-fs",
        channel="test_fixture",
        replacements=(
            (source.physical_vehicle_id, ()),
            (
                target.physical_vehicle_id,
                (tuple(source.trips[0].customer_ids),),
            ),
        ),
    ).apply(initial)
    engine = IndependentKernelDutyRouteProposalEngine(
        context,
        misplaced,
        random_seed=11,
        depot_assignment_operator_enabled=True,
    )
    local_search = LocalSearch(
        engine.data,
        RandomNumberGenerator(seed=11),
        compute_neighbours(engine.data),
    )
    operator = DepotSplit(
        engine.data,
        list(engine.depot_assignment_compatible_vehicle_groups),
    )
    local_search.add_node_operator(operator)
    improved = local_search(
        engine.project(misplaced),
        engine.penalty_manager.booster_cost_evaluator(),
    )
    replacements = engine.decode_replacements(misplaced, improved)
    replacement_by_id = dict(replacements)
    moved_customers = set(source.trips[0].customer_ids)
    target_id = next(
        duty.physical_vehicle_id
        for duty in misplaced.duties
        if duty.home_depot_id == source.home_depot_id
        and moved_customers.intersection(
            customer_id
            for trip in replacement_by_id.get(
                duty.physical_vehicle_id,
                (),
            )
            for customer_id in trip
        )
    )
    depot_replacements = (
        (
            target.physical_vehicle_id,
            replacement_by_id[target.physical_vehicle_id],
        ),
        (target_id, replacement_by_id[target_id]),
    )
    candidate = DutySkeletonMove(
        action_id="native-depot-split",
        channel="depot_assignment",
        replacements=depot_replacements,
    ).apply(misplaced)
    return bundle, misplaced, candidate, operator


def _multi_trip_depot_split_candidate(rebuilt_context):
    bundle, initial, _neutral, context = rebuilt_context
    duties = {duty.physical_vehicle_id: duty for duty in initial.duties}
    source = duties["CV_D_foshan_1"]
    foreign = duties["CV_D_guangzhou_4"]
    assert len(source.trips) == 2
    assert len(foreign.trips) == 1

    fixture = WholeTripExchangeMove(
        action_id="fixture-put-guangzhou-trip-on-multi-trip-foshan-duty",
        channel="test_fixture",
        left_duty_id=source.physical_vehicle_id,
        left_trip_index=1,
        right_duty_id=foreign.physical_vehicle_id,
        right_trip_index=1,
    ).apply(initial)
    foreign_customers = set(foreign.trips[0].customer_ids)
    fixture_source = next(
        duty
        for duty in fixture.duties
        if duty.physical_vehicle_id == source.physical_vehicle_id
    )
    assert len(fixture_source.trips) == 2
    assert set(fixture_source.trips[0].customer_ids) == foreign_customers

    engine = IndependentKernelDutyRouteProposalEngine(
        context,
        fixture,
        random_seed=11,
        depot_assignment_operator_enabled=True,
    )
    local_search = LocalSearch(
        engine.data,
        RandomNumberGenerator(seed=11),
        compute_neighbours(engine.data),
    )
    operator = DepotSplit(
        engine.data,
        list(engine.depot_assignment_compatible_vehicle_groups),
    )
    local_search.add_node_operator(operator)
    improved = local_search(
        engine.project(fixture),
        engine.penalty_manager.booster_cost_evaluator(),
    )
    components = _migration_components(
        fixture,
        engine.decode_replacements(fixture, improved),
    )
    candidate = next(
        DutySkeletonMove(
            action_id="native-multi-trip-depot-split",
            channel="depot_assignment",
            replacements=component,
        ).apply(fixture)
        for component in components
        if foreign_customers.issubset(
            {
                customer_id
                for duty_id, chain in component
                if duties[duty_id].home_depot_id == "D_guangzhou"
                for trip in chain
                for customer_id in trip
            }
        )
    )
    return bundle, fixture, candidate, operator, foreign_customers


def test_depot_split_uses_incremental_route_segments() -> None:
    model = Model()
    depot_left = model.add_depot(0, 0)
    depot_right = model.add_depot(100, 0)
    clients = [
        model.add_client(90, 0, delivery=1),
        model.add_client(95, 0, delivery=1),
    ]
    locations = [depot_left, depot_right, *clients]
    for left in locations:
        for right in locations:
            distance = int(abs(left.x - right.x))
            model.add_edge(left, right, distance, distance)
    model.add_vehicle_type(
        num_available=1,
        capacity=10,
        start_depot=depot_left,
        end_depot=depot_left,
    )
    model.add_vehicle_type(
        num_available=1,
        capacity=10,
        start_depot=depot_right,
        end_depot=depot_right,
    )
    data = model.data()
    solution = Solution(data, [Route(data, [2, 3], 0)])
    evaluator = CostEvaluator([0], 0, 0)
    local_search = LocalSearch(
        data,
        RandomNumberGenerator(seed=11),
        compute_neighbours(data),
    )
    operator = DepotSplit(data, [0, 0])
    local_search.add_node_operator(operator)

    improved = local_search(solution, evaluator)

    assert evaluator.cost(solution) == 190
    assert evaluator.cost(improved) == 20
    assert operator.statistics.num_evaluations > 0
    assert operator.statistics.num_applications == 1
    assert improved.is_complete()
    assert improved.is_feasible()
    assert {
        (route.start_depot(), tuple(route.visits()))
        for route in improved.routes()
    } == {(1, (2, 3))}


def test_depot_split_moves_segment_from_multi_trip_source() -> None:
    model = Model()
    depot_left = model.add_depot(0, 0)
    depot_right = model.add_depot(100, 0)
    clients = [
        model.add_client(90, 0, delivery=1),
        model.add_client(95, 0, delivery=1),
        model.add_client(5, 0, delivery=1),
    ]
    locations = [depot_left, depot_right, *clients]
    for left in locations:
        for right in locations:
            distance = int(abs(left.x - right.x))
            model.add_edge(left, right, distance, distance)
    model.add_vehicle_type(
        num_available=1,
        capacity=10,
        start_depot=depot_left,
        end_depot=depot_left,
        reload_depots=[depot_left],
        max_reloads=2,
    )
    model.add_vehicle_type(
        num_available=1,
        capacity=10,
        start_depot=depot_right,
        end_depot=depot_right,
        reload_depots=[depot_right],
        max_reloads=2,
    )
    data = model.data()
    source = Route(
        data,
        [
            Trip(data, [2, 3], 0, start_depot=0, end_depot=0),
            Trip(data, [4], 0, start_depot=0, end_depot=0),
        ],
        0,
    )
    solution = Solution(data, [source])
    evaluator = CostEvaluator([0], 0, 0)
    local_search = LocalSearch(
        data,
        RandomNumberGenerator(seed=11),
        compute_neighbours(data),
    )
    operator = DepotSplit(data, [0, 0])
    local_search.add_node_operator(operator)

    improved = local_search(solution, evaluator)

    assert evaluator.cost(solution) == 200
    assert evaluator.cost(improved) == 30
    assert operator.statistics.num_evaluations > 0
    assert operator.statistics.num_applications == 1
    assert improved.is_complete()
    assert improved.is_feasible()
    assert {
        (route.start_depot(), tuple(route.visits()))
        for route in improved.routes()
    } == {(0, (4,)), (1, (2, 3))}








