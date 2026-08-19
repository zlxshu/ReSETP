from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from setp_hgs_kernel import (
    CostEvaluator,
    Model,
    RandomNumberGenerator,
    Route,
    Solution,
)
from setp_hgs_kernel.search import (
    DepotSplit,
    Exchange10,
    Exchange11,
    LocalSearch,
    compute_neighbours,
)

import setp_solver.algorithms.problem_hgs.education as education_module
from setp_solver.algorithms.problem_hgs.contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
)
from setp_solver.algorithms.problem_hgs.education import (
    educate_best_improvement,
)


def test_native_shortlist_is_bounded_ranked_and_does_not_mutate_base() -> None:
    model = Model()
    depot_left = model.add_depot(0, 0)
    depot_right = model.add_depot(100, 0)
    clients = (
        model.add_client(90, 0, delivery=1),
        model.add_client(95, 0, delivery=1),
    )
    locations = (depot_left, depot_right, *clients)
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
    base = Solution(data, [Route(data, [2, 3], 0)])
    evaluator = CostEvaluator([0], 0, 0)
    local_search = LocalSearch(
        data,
        RandomNumberGenerator(seed=11),
        compute_neighbours(data),
    )
    local_search.add_node_operator(DepotSplit(data, [0, 0]))
    base_routes = tuple(
        (route.vehicle_type(), tuple(route.visits())) for route in base.routes()
    )

    candidates = local_search.promising_candidates(base, evaluator, limit=1)
    statistics = local_search.candidate_statistics

    assert len(candidates) == 1
    assert candidates[0].proxy_delta < 0
    assert evaluator.cost(candidates[0].solution) < evaluator.cost(base)
    assert tuple(
        (route.vehicle_type(), tuple(route.visits())) for route in base.routes()
    ) == base_routes
    assert statistics.num_evaluated > 0
    assert statistics.num_promising > 0
    assert statistics.num_materialised > 0
    assert statistics.num_returned == 1


def test_native_shortlist_limit_three_is_stably_ranked_and_unique() -> None:
    model = Model()
    depot = model.add_depot(0, 0)
    clients = tuple(
        model.add_client(x, 0, delivery=1)
        for x in (10, 20, 30, 40, 50, 60)
    )
    locations = (depot, *clients)
    for left in locations:
        for right in locations:
            distance = int(abs(left.x - right.x))
            model.add_edge(left, right, distance, distance)
    model.add_vehicle_type(
        num_available=2,
        capacity=10,
        start_depot=depot,
        end_depot=depot,
    )
    data = model.data()
    base = Solution(data, [Route(data, [1, 6, 2, 5, 3, 4], 0)])
    evaluator = CostEvaluator([0], 0, 0)
    local_search = LocalSearch(
        data,
        RandomNumberGenerator(seed=11),
        compute_neighbours(data),
    )
    local_search.add_node_operator(Exchange10(data))
    local_search.add_node_operator(Exchange11(data))
    base_routes = tuple(
        (route.vehicle_type(), tuple(route.visits())) for route in base.routes()
    )

    candidates = local_search.promising_candidates(base, evaluator, limit=3)
    ordering_keys = tuple(
        (candidate.proxy_delta, candidate.scan_ordinal)
        for candidate in candidates
    )
    fingerprints = tuple(
        tuple(
            (route.vehicle_type(), tuple(route.visits()))
            for route in candidate.solution.routes()
        )
        for candidate in candidates
    )

    assert len(candidates) == 3
    assert ordering_keys == tuple(sorted(ordering_keys))
    assert len(set(fingerprints)) == len(fingerprints)
    assert all(
        evaluator.cost(candidate.solution) < evaluator.cost(base)
        for candidate in candidates
    )
    assert tuple(
        (route.vehicle_type(), tuple(route.visits())) for route in base.routes()
    ) == base_routes
    assert local_search.candidate_statistics.num_returned == 3


@dataclass(frozen=True)
class _Individual:
    label: str
    cost: float
    duties: tuple = ()

    @property
    def fingerprint(self) -> str:
        return self.label


@dataclass(frozen=True)
class _Evaluation:
    individual_fingerprint: str
    total_cost: float
    violations: tuple = ()
    breakdown: dict | None = None
    participation_margin: dict | None = None
    accounting: dict | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "breakdown", self.breakdown or {})
        object.__setattr__(
            self,
            "participation_margin",
            self.participation_margin or {},
        )
        object.__setattr__(self, "accounting", self.accounting or {})


class _Evaluator:
    context = SimpleNamespace(
        bundle=SimpleNamespace(instance=object()),
        dynamic_state=None,
        incremental_full_truth_sentinel_enabled=False,
    )


@dataclass(frozen=True)
class _Move:
    action_id: str
    channel: str
    proxy_rank: int | None = None
    proxy_delta: int | None = None
    changed_duty_ids: frozenset[str] = frozenset({"D0"})


class _OneBatchEngine:
    source_id = "p31-truth-shortlist-test"
    identity_sha256 = "1" * 64

    def __init__(self, moves: tuple[_Move, ...]) -> None:
        self.moves = moves
        self.calls = 0

    def propose(self, *_args, **_kwargs):
        self.calls += 1
        return self.moves if self.calls == 1 else ()


class _IncrementalEvaluator:
    def __init__(self, _evaluator) -> None:
        pass

    def seed(self, _individual) -> int:
        return 0


def _run_truth_batch(monkeypatch, costs: dict[str, float | None]):
    evaluated: list[str] = []

    def fake_evaluate_move(current, move, **_kwargs):
        evaluated.append(move.action_id)
        if costs[move.action_id] is None:
            return CandidateOutcome(
                action_id=move.action_id,
                channel=move.channel,
                status=CandidateStatus.REJECTED_CHARGING,
                changed_duty_ids=move.changed_duty_ids,
            )
        candidate = _Individual(move.action_id, costs[move.action_id])
        return CandidateOutcome(
            action_id=move.action_id,
            channel=move.channel,
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=move.changed_duty_ids,
            candidate=candidate,
            evaluation=_Evaluation(candidate.fingerprint, candidate.cost),
        )

    monkeypatch.setattr(education_module, "evaluate_move", fake_evaluate_move)
    monkeypatch.setattr(
        education_module,
        "DutyIncrementalEvaluator",
        _IncrementalEvaluator,
    )
    moves = (
        _Move("proxy-1", "route_kernel_truth", 1, -30),
        _Move("proxy-2", "route_kernel_truth", 2, -20),
        _Move("mechanism", "mechanism", None, None),
    )
    initial = _Individual("initial", 10.0)
    accounting = SearchAccounting()
    result = educate_best_improvement(
        initial,
        evaluator=_Evaluator(),
        charging_policy=object(),
        arm="test",
        iteration=1,
        accounting=accounting,
        penalized_cost=lambda evaluation: evaluation.total_cost,
        initial_evaluation=_Evaluation(initial.fingerprint, initial.cost),
        proposal_engine=_OneBatchEngine(moves),
        selection_policy="first",
        record_trajectory=False,
    )
    return result, accounting, evaluated


def test_truth_batch_strictly_reselects_before_mechanism(monkeypatch) -> None:
    (individual, _evaluation, _rows), accounting, evaluated = _run_truth_batch(
        monkeypatch,
        {"proxy-1": 8.0, "proxy-2": 7.0, "mechanism": 6.0},
    )

    assert individual.fingerprint == "proxy-2"
    assert evaluated == ["proxy-1", "proxy-2"]
    assert accounting.truth_shortlist_batches == 1
    assert accounting.truth_shortlist_exact_evaluations == 2
    assert accounting.truth_shortlist_accepted == 1
    assert accounting.truth_reselections == 1
    assert accounting.truth_reselection_reasons == {
        "strict_complete_penalised_cost": 1
    }
    assert accounting.truth_winner_proxy_ranks == {2: 1}


def test_truth_tie_preserves_proxy_order_and_is_not_a_reselection(
    monkeypatch,
) -> None:
    (individual, _evaluation, _rows), accounting, evaluated = _run_truth_batch(
        monkeypatch,
        {"proxy-1": 7.0, "proxy-2": 7.0, "mechanism": 6.0},
    )

    assert individual.fingerprint == "proxy-1"
    assert evaluated == ["proxy-1", "proxy-2"]
    assert accounting.truth_reselections == 0
    assert accounting.truth_winner_proxy_ranks == {1: 1}


def test_truth_feasibility_rejection_reselects_later_proxy_rank(
    monkeypatch,
) -> None:
    (individual, _evaluation, _rows), accounting, evaluated = _run_truth_batch(
        monkeypatch,
        {"proxy-1": None, "proxy-2": 7.0, "mechanism": 6.0},
    )

    assert individual.fingerprint == "proxy-2"
    assert evaluated == ["proxy-1", "proxy-2"]
    assert accounting.truth_reselections == 1
    assert accounting.truth_reselection_reasons == {
        "proxy_rank_one_rejected_by_complete_chain": 1
    }


def test_truth_veto_falls_through_to_existing_first_improvement(
    monkeypatch,
) -> None:
    (individual, _evaluation, _rows), accounting, evaluated = _run_truth_batch(
        monkeypatch,
        {"proxy-1": 11.0, "proxy-2": 12.0, "mechanism": 9.0},
    )

    assert individual.fingerprint == "mechanism"
    assert evaluated == ["proxy-1", "proxy-2", "mechanism"]
    assert accounting.truth_shortlist_accepted == 0
    assert accounting.truth_reselections == 0


def test_candidate_limit_requires_enabled_boundary() -> None:
    # The project engine performs the same validation; this small assertion
    # keeps the native boundary from silently accepting an unbounded request.
    model = Model()
    depot = model.add_depot(0, 0)
    client = model.add_client(1, 0, delivery=1)
    model.add_edge(depot, depot, 0, 0)
    model.add_edge(depot, client, 1, 1)
    model.add_edge(client, depot, 1, 1)
    model.add_edge(client, client, 0, 0)
    model.add_vehicle_type(
        num_available=1,
        capacity=1,
        start_depot=depot,
        end_depot=depot,
    )
    data = model.data()
    local_search = LocalSearch(
        data,
        RandomNumberGenerator(seed=1),
        compute_neighbours(data),
    )
    solution = Solution(data, [Route(data, [1], 0)])

    with pytest.raises(ValueError, match="positive"):
        local_search.promising_candidates(
            solution,
            CostEvaluator([0], 0, 0),
            limit=0,
        )
