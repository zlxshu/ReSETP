from __future__ import annotations

import math
from dataclasses import dataclass

import pytest
from setp_hgs_kernel.ExternalPopulation import (
    EvaluatedSolution,
    ExternalPopulation,
)
from setp_hgs_kernel._setp_hgs_kernel import PopulationParams

from setp_solver.algorithms.problem_hgs.bi_objective_population import (
    BI_OBJECTIVE,
    SINGLE_OBJECTIVE,
    BiObjectiveExternalPopulation,
    ObjectiveValues,
    PopulationPoint,
    RankedPoint,
    crowded_comparison_key,
    crowding_distances,
    dominates,
    fast_non_dominated_sort,
    make_private_population,
)
from setp_solver.algorithms.problem_hgs.population import (
    PenaltyParameters,
    PopulationParameters,
)
from setp_solver.algorithms.problem_hgs.runner import ProblemHGSSearchParameters


@dataclass(frozen=True)
class _Solution:
    name: str
    position: float = 0.0


@dataclass(frozen=True)
class _Evaluation:
    total_cost: float
    emissions_kg: float
    feasible: bool = True
    penalised: float | None = None
    certificate: str = "certificate"

    @property
    def penalised_cost(self) -> float:
        return (
            float(self.total_cost) if self.penalised is None else float(self.penalised)
        )


class _SequenceRng:
    def __init__(self, values: tuple[int, ...]) -> None:
        self._values = iter(values)

    def randint(self, high: int) -> int:
        return next(self._values) % int(high)


def _point(
    name: str,
    cost: float,
    emissions: float,
    *,
    feasible: bool = True,
    penalised: float | None = None,
) -> PopulationPoint[str]:
    return PopulationPoint(
        value=name,
        objectives=ObjectiveValues(cost, emissions),
        feasible=feasible,
        penalised_cost=cost if penalised is None else penalised,
        fingerprint=name,
    )


def _objectives(evaluation: _Evaluation) -> ObjectiveValues:
    return ObjectiveValues(evaluation.total_cost, evaluation.emissions_kg)


def _params() -> PopulationParams:
    return PopulationParams(
        min_pop_size=3,
        generation_size=1,
        num_elite=1,
        num_close=1,
        lb_diversity=0.0,
        ub_diversity=1.0,
    )


def test_fast_non_dominated_sort_returns_expected_layers() -> None:
    points = (
        _point("A", 1.0, 4.0),
        _point("B", 2.0, 2.0),
        _point("C", 4.0, 1.0),
        _point("D", 3.0, 4.0),
        _point("E", 5.0, 5.0),
    )

    fronts = fast_non_dominated_sort(points)

    assert tuple(tuple(point.value for point in front) for front in fronts) == (
        ("A", "B", "C"),
        ("D",),
        ("E",),
    )


def test_crowding_distance_uses_normalized_adjacent_differences() -> None:
    front = (
        _point("A", 0.0, 0.0),
        _point("B", 1.0, 2.0),
        _point("C", 3.0, 3.0),
        _point("D", 4.0, 6.0),
    )

    distances = crowding_distances(front)

    assert math.isinf(distances[0])
    assert distances[1] == pytest.approx((3.0 / 4.0) + (3.0 / 6.0))
    assert distances[2] == pytest.approx((3.0 / 4.0) + (4.0 / 6.0))
    assert math.isinf(distances[3])


def test_crowded_comparison_prefers_rank_then_larger_distance() -> None:
    low_crowding = RankedPoint(_point("low", 1.0, 3.0), 0, 0.25)
    high_crowding = RankedPoint(_point("high", 2.0, 2.0), 0, 1.5)
    lower_front = RankedPoint(_point("later", 3.0, 1.0), 1, math.inf)

    ordered = sorted(
        (lower_front, low_crowding, high_crowding),
        key=crowded_comparison_key,
    )

    assert [item.point.value for item in ordered] == ["high", "low", "later"]


def test_feasible_solution_dominates_every_infeasible_solution() -> None:
    feasible = _point("feasible", 100.0, 100.0, feasible=True)
    infeasible = _point(
        "infeasible",
        1.0,
        1.0,
        feasible=False,
        penalised=1.0,
    )
    lower_penalty = _point(
        "lower-penalty",
        100.0,
        100.0,
        feasible=False,
        penalised=2.0,
    )
    higher_penalty = _point(
        "higher-penalty",
        0.0,
        0.0,
        feasible=False,
        penalised=3.0,
    )

    assert dominates(feasible, infeasible)
    assert not dominates(infeasible, feasible)
    assert dominates(lower_penalty, higher_penalty)


def test_default_single_objective_mode_uses_original_population_exactly() -> None:
    assert _search_parameters().objective_mode == SINGLE_OBJECTIVE
    params = PopulationParams(
        min_pop_size=2,
        generation_size=1,
        num_elite=1,
        num_close=1,
        lb_diversity=0.0,
        ub_diversity=1.0,
    )
    kwargs = {
        "is_feasible": lambda evaluation: evaluation.feasible,
        "penalised_cost": lambda evaluation: evaluation.penalised_cost,
        "fingerprint": lambda solution: solution.name,
        "params": params,
    }

    def diversity(left: _Solution, right: _Solution) -> float:
        return abs(left.position - right.position) / 10.0

    reference = ExternalPopulation(diversity, **kwargs)
    switched_off = make_private_population(
        diversity,
        objective_mode=SINGLE_OBJECTIVE,
        objectives=lambda _evaluation: (_ for _ in ()).throw(
            AssertionError("single-objective mode evaluated a second objective")
        ),
        **kwargs,
    )
    assert type(switched_off) is ExternalPopulation
    candidates = tuple(
        EvaluatedSolution(_Solution(name, position), _Evaluation(cost, cost))
        for name, position, cost in (
            ("A", 0.0, 4.0),
            ("B", 2.0, 1.0),
            ("C", 5.0, 3.0),
            ("D", 9.0, 2.0),
        )
    )

    reference_admissions = [reference.add(candidate) for candidate in candidates]
    switched_admissions = [switched_off.add(candidate) for candidate in candidates]
    reference_parents = reference.select(_SequenceRng((0, 1, 1, 0)))
    switched_parents = switched_off.select(_SequenceRng((0, 1, 1, 0)))

    assert switched_admissions == reference_admissions
    assert tuple(item.solution.name for item in switched_off) == tuple(
        item.solution.name for item in reference
    )
    assert tuple(item.solution.name for item in switched_parents) == tuple(
        item.solution.name for item in reference_parents
    )


def test_bi_objective_archive_contains_all_points_and_both_endpoints() -> None:
    population = make_private_population(
        lambda left, right: abs(left.position - right.position) / 10.0,
        objective_mode=BI_OBJECTIVE,
        is_feasible=lambda evaluation: evaluation.feasible,
        objectives=_objectives,
        penalised_cost=lambda evaluation: evaluation.penalised_cost,
        fingerprint=lambda solution: solution.name,
        params=_params(),
    )
    assert isinstance(population, BiObjectiveExternalPopulation)
    candidates = (
        EvaluatedSolution(
            _Solution("cost", 0.0),
            _Evaluation(1.0, 5.0, certificate="cost-certificate"),
        ),
        EvaluatedSolution(
            _Solution("middle", 5.0),
            _Evaluation(3.0, 3.0, certificate="middle-certificate"),
        ),
        EvaluatedSolution(
            _Solution("emissions", 10.0),
            _Evaluation(5.0, 1.0, certificate="emissions-certificate"),
        ),
        EvaluatedSolution(
            _Solution("dominated", 7.0),
            _Evaluation(4.0, 5.0, certificate="dominated-certificate"),
        ),
        EvaluatedSolution(
            _Solution("infeasible", 3.0),
            _Evaluation(
                0.0,
                0.0,
                feasible=False,
                penalised=0.5,
                certificate="infeasible-certificate",
            ),
        ),
    )
    for candidate in candidates:
        population.add(candidate)

    archive = population.archive()

    assert tuple(entry.fingerprint for entry in archive.entries) == (
        "cost",
        "middle",
        "emissions",
    )
    assert archive.cost_priority is not None
    assert archive.cost_priority.fingerprint == "cost"
    assert archive.cost_priority.candidate.evaluation.certificate == (
        "cost-certificate"
    )
    assert archive.emissions_priority is not None
    assert archive.emissions_priority.fingerprint == "emissions"
    assert archive.emissions_priority.candidate.evaluation.certificate == (
        "emissions-certificate"
    )


def _search_parameters() -> ProblemHGSSearchParameters:
    """Kept local so imported parameter classes remain exercised by this test."""

    return ProblemHGSSearchParameters(
        random_seed=1,
        population=PopulationParameters.copied_hgs_defaults(),
        penalties=PenaltyParameters(
            initial_penalty_per_unit=1.0,
            solutions_between_updates=1,
            penalty_increase=1.0,
            penalty_decrease=1.0,
            target_feasible=0.5,
            feasibility_tolerance=0.0,
            minimum_penalty=0.0,
            maximum_penalty=1.0,
        ),
    )
