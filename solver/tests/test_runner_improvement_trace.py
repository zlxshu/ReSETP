"""The kernel-native runner records its in-round improvement curve.

2026-09-05.  ``convergence.csv`` only gets one row per outer round, so a
seven-minute run leaves two to four points and the round's own improvement
history is invisible.  The runner now wraps the kernel's stopping criterion:
``GeneticAlgorithm.run`` evaluates ``while not stop(cost(best))`` once per
iteration, so the wrapper sees every best cost the kernel reaches, at O(1)
per iteration and without drawing a single random number.

Two claims are tested here.  First, that the wrapper leaves the search
bit-for-bit alone -- proved on a fixed-seed standalone kernel problem, because
the private route engine seeds itself from ``SystemRandom`` and cannot be
replayed.  Second, that the recorded trace is well formed on the real
kernel-native path, with a test-fixture patience that keeps the run short.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
from setp_hgs_kernel import Model, RandomNumberGenerator, Solution
from setp_hgs_kernel.GeneticAlgorithm import (
    GeneticAlgorithm,
    GeneticAlgorithmParams,
)
from setp_hgs_kernel.PenaltyManager import PenaltyManager
from setp_hgs_kernel.Population import Population
from setp_hgs_kernel.crossover import selective_route_exchange
from setp_hgs_kernel.diversity import broken_pairs_distance
from setp_hgs_kernel.search import LocalSearch, compute_neighbours
from setp_hgs_kernel.solve import SolveParams
from setp_hgs_kernel.stop import NoImprovement


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
    _parameters,
    _policy,
    _write_kernel_trace_csvs,
)
from setp_solver.algorithms.problem_hgs.contracts import (  # noqa: E402
    SearchAccounting,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    KERNEL_INFEASIBLE_COST,
    ProblemHGSSearchParameters,
    _KernelImprovementTrace,
    run_kernel_native_problem_hgs,
)


# --------------------------------------------------------------------------
# 1. The trace does not perturb the kernel.
# --------------------------------------------------------------------------


_A_B_PATIENCE = 50


def _standalone_kernel_data():
    """A small fixed CVRP the copied kernel can search deterministically."""

    model = Model()
    depot = model.add_depot(0, 0)
    coordinates = [
        (10, 0),
        (20, 5),
        (15, 20),
        (0, 25),
        (-15, 15),
        (-20, 0),
        (-10, -15),
        (5, -20),
        (25, -10),
        (30, 10),
        (-5, 30),
        (-30, -10),
    ]
    clients = [model.add_client(x, y, delivery=1) for x, y in coordinates]
    locations = [depot, *clients]
    for left in locations:
        for right in locations:
            distance = int(abs(left.x - right.x) + abs(left.y - right.y))
            model.add_edge(left, right, distance, distance)
    model.add_vehicle_type(
        num_available=4,
        capacity=4,
        start_depot=depot,
        end_depot=depot,
    )
    return model.data()


def _run_standalone(data, wrap: bool):
    """Run the copied kernel once, with or without the trace wrapper."""

    params = SolveParams()
    rng = RandomNumberGenerator(seed=42)
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for operator in params.node_ops:
        if operator.supports(data):
            local_search.add_node_operator(operator(data))
    for operator in params.route_ops:
        if operator.supports(data):
            local_search.add_route_operator(operator(data))
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    initial = [
        Solution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        selective_route_exchange,
        initial,
        GeneticAlgorithmParams(
            repair_probability=params.genetic.repair_probability,
            num_iters_no_improvement=10**9,
        ),
    )
    criterion = NoImprovement(_A_B_PATIENCE)
    trace = (
        _KernelImprovementTrace(criterion, round_index=1) if wrap else None
    )
    result = algorithm.run(trace or criterion, collect_stats=False)
    return result, trace


def test_improvement_trace_leaves_the_kernel_bit_for_bit_identical():
    """Same seed, same data: wrapping the criterion changes nothing."""

    data = _standalone_kernel_data()
    plain, _none = _run_standalone(data, wrap=False)
    traced, trace = _run_standalone(data, wrap=True)

    assert traced.num_iterations == plain.num_iterations
    assert traced.cost() == plain.cost()
    assert str(traced.best) == str(plain.best)
    assert traced.best.distance() == plain.best.distance()
    assert traced.best.duration() == plain.best.duration()

    # The wrapper stopped the run at exactly the same point the bare
    # criterion would have, and it saw the run's whole improvement curve.
    assert traced.num_iterations >= _A_B_PATIENCE
    assert trace is not None
    assert trace.events
    assert trace.best_cost is not None
    costs = [float(event["kernel_best_cost"]) for event in trace.events]
    assert costs == sorted(costs, reverse=True)
    assert all(cost < KERNEL_INFEASIBLE_COST for cost in costs)
    assert trace.best_cost == costs[-1]
    assert all(int(event["round"]) == 1 for event in trace.events)
    iterations = [int(event["iteration"]) for event in trace.events]
    assert iterations == sorted(iterations)
    assert len(set(iterations)) == len(iterations)
    assert iterations[-1] <= traced.num_iterations


def test_improvement_trace_never_records_the_infeasible_sentinel():
    """``CostEvaluator.cost`` returns int64 max while the best is infeasible."""

    trace = _KernelImprovementTrace(NoImprovement(10), round_index=3)
    assert trace(float(KERNEL_INFEASIBLE_COST)) is False
    assert trace(float(KERNEL_INFEASIBLE_COST)) is False
    assert trace.events == []
    assert trace(100.0) is False
    assert trace(100.0) is False
    assert trace(80.0) is False
    assert trace.events == [
        {"round": 3, "iteration": 2, "kernel_best_cost": 100.0},
        {"round": 3, "iteration": 4, "kernel_best_cost": 80.0},
    ]


def test_improvement_trace_returns_the_delegate_verdict():
    """The wrapper is a pass-through: the kernel stops when the rule says so."""

    criterion = NoImprovement(2)
    trace = _KernelImprovementTrace(criterion, round_index=1)
    assert trace(10.0) is False  # first call sets the target
    assert trace(10.0) is False  # one non-improving call
    assert trace(10.0) is True  # two non-improving calls: stop
    assert len(trace.events) == 1


# --------------------------------------------------------------------------
# 2. The runner publishes the trace and the honest stopping bookkeeping.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def formal():
    repo = Path(__file__).parents[2]
    bundle, initial, _neutral, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    evaluator = DutyFullEvaluator(context)
    return bundle, initial, context, evaluator, _policy(evaluator)


def test_kernel_native_run_records_an_improvement_trace(formal):
    _bundle, initial, context, evaluator, policy = formal

    def make_engine(**extra):
        return IndependentKernelDutyRouteProposalEngine(
            context,
            initial,
            stream_role="main_route",
            depot_assignment_operator_enabled=True,
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
            **extra,
        )

    base = _parameters()
    parameters = ProblemHGSSearchParameters(
        population=base.population,
        # Test fixture, not a solver setting: the delivery runs use 20,000.
        stagnation_patience=200,
        objective_mode=base.objective_mode,
    )
    reference = evaluator.evaluate(initial)
    states = []
    result = run_kernel_native_problem_hgs(
        (initial, initial, initial, initial),
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        stop=lambda state: states.append(state) or False,
        arm="kernel-native-improvement-trace-test",
        route_engine=make_engine(),
        route_engine_factory=make_engine,
        initial_evaluations=(reference, reference, reference, reference),
        charging_prescreen_enabled=True,
        include_charging_candidates=False,
        # As in the delivery batch.  The round count is stochastic here: the
        # route engine seeds itself from ``SystemRandom``, and a draw whose
        # best plan buys no electricity skips the priced second phase before
        # the confirming rule is consulted.  Observed 2026-09-05 on this
        # fixture: both one-round and two-round runs, so assert neither.
        confirming_round=True,
    )
    accounting = result.accounting

    # (b) ``restarts`` is the round count under a historical misnomer.
    assert accounting.rounds == accounting.restarts
    assert accounting.rounds >= 1
    # (c) the whole-run stopping rule, not the per-round one.  2026-09-05:
    # confirming rounds are sized from the run's own measured improvement
    # gaps by default, so the rule now names its clamp.  On this fixture the
    # cap (200) sits below the floor (5000) and the cap wins, so every round
    # still gets exactly 200 -- which is what keeps the per-round iteration
    # assertions below valid.
    assert accounting.round_patience_mode == "adaptive"
    assert accounting.round_patience_by_round == [200] * accounting.rounds
    # 2026-09-05 二改：确认轮的停机由"任一轮无改善即停"改为"连续 N 轮无改善才
    # 停"（默认 2），并第一次给轮次循环加了硬上限，两者都写进这句语义串。
    assert accounting.stop_semantics_actual == (
        "round 1: NoImprovement(200); confirming rounds: adaptive patience ="
        " max improvement gap of round 1, floor 5000, cap 200"
        "; stop after 2 consecutive non-improving rounds, at most 8 rounds"
    )
    assert accounting.stop_after_nonimproving_rounds == 2
    assert accounting.max_outer_rounds == 8
    assert len(accounting.round_improved_by_round) == accounting.rounds
    assert accounting.outer_stop_callback_effective is False

    summaries = accounting.kernel_round_summaries
    assert [summary["round"] for summary in summaries] == list(
        range(1, accounting.rounds + 1)
    )
    assert sum(int(s["iterations"]) for s in summaries) == result.iterations
    assert all(int(s["iterations"]) >= 200 for s in summaries)
    assert all(float(s["runtime_seconds"]) > 0.0 for s in summaries)

    # (1) the in-round improvement events.  ``CostEvaluator.cost`` reports the
    # int64 sentinel while the kernel's incumbent is infeasible, so a round
    # that never reaches a proxy-feasible best records nothing -- and then it
    # must have run exactly ``patience`` iterations, because the kernel's own
    # no-improvement rule reads that same value.  Both outcomes are real data;
    # the deterministic A/B test above pins the non-empty case.
    events = accounting.improvement_events
    if not events:
        assert all(int(s["iterations"]) == 200 for s in summaries)
        return
    rounds_seen = [int(event["round"]) for event in events]
    assert min(rounds_seen) == 1  # round numbers start at 1
    assert max(rounds_seen) <= accounting.rounds
    assert rounds_seen == sorted(rounds_seen)
    iterations_by_round = {
        int(summary["round"]): int(summary["iterations"])
        for summary in summaries
    }
    for round_index in sorted(set(rounds_seen)):
        in_round = [
            event for event in events if int(event["round"]) == round_index
        ]
        costs = [float(event["kernel_best_cost"]) for event in in_round]
        # Monotone non-increasing inside the round, and never the sentinel.
        assert costs == sorted(costs, reverse=True)
        assert all(cost < KERNEL_INFEASIBLE_COST for cost in costs)
        cycles = [int(event["iteration"]) for event in in_round]
        assert cycles == sorted(cycles)
        assert len(set(cycles)) == len(cycles)
        assert cycles[-1] <= iterations_by_round[round_index]
    assert sum(int(s["improvements"]) for s in summaries) == len(events)

    # (a) the search state now carries a real no-improvement count.
    # (a) the search state carries the real count of kernel iterations since
    # the exact best last improved, not the 0 it used to hardcode.  The
    # expected value is recomputable from outside: a round that lowered the
    # exact best resets it, a round that did not adds its kernel iterations.
    assert len(states) == accounting.rounds
    previous_best = float(reference.total_cost)
    expected = 0
    for state, summary in zip(states, summaries, strict=True):
        round_improved = float(state.best_cost) < previous_best - 1e-9
        expected = 0 if round_improved else expected + int(summary["iterations"])
        assert state.iterations_without_improvement == expected
        assert state.iterations_without_improvement <= state.iterations
        previous_best = float(state.best_cost)

    # The search itself is untouched: the exact answer is still feasible and
    # no worse than the reference it started from.
    assert result.termination_status == "STOPPED_BY_CALLER"
    assert result.best_evaluation.feasible
    assert not result.best.unserved_customers
    assert result.best_evaluation.total_cost <= reference.total_cost + 1e-9


# --------------------------------------------------------------------------
# 3. The five trace fields are declared, serialised and written to CSV.
# --------------------------------------------------------------------------


TRACE_KEYS = (
    "rounds",
    "stop_semantics_actual",
    "outer_stop_callback_effective",
    "improvement_events",
    "kernel_round_summaries",
)


def _accounting_with_a_trace() -> SearchAccounting:
    """One recorded round with a cost, one round that never left the sentinel."""

    accounting = SearchAccounting()
    accounting.restarts = 2
    accounting.rounds = 2
    accounting.stop_semantics_actual = (
        "per-round NoImprovement(patience) x rounds"
    )
    accounting.outer_stop_callback_effective = False
    accounting.improvement_events = [
        {"round": 1, "iteration": 0, "kernel_best_cost": 12.5},
        {"round": 1, "iteration": 3, "kernel_best_cost": 11.25},
    ]
    accounting.kernel_round_summaries = [
        {
            "round": 1,
            "iterations": 5,
            "runtime_seconds": 1.5,
            "improvements": 2,
            "kernel_best_cost": 11.25,
        },
        {
            "round": 2,
            "iterations": 5,
            "runtime_seconds": 1.25,
            "improvements": 0,
            "kernel_best_cost": None,
        },
    ]
    return accounting


def test_search_accounting_declares_and_serialises_the_trace_fields():
    """The runner's five trace attributes are fields, not stray ``setattr``.

    2026-09-05: the runner recorded them, but ``to_dict`` is an explicit
    literal, so nothing reached ``metadata.json``.
    """

    payload = SearchAccounting().to_dict()
    assert all(key in payload for key in TRACE_KEYS)
    assert payload["rounds"] == 0
    assert payload["restarts"] == 0
    # ``None`` reads as "this search path recorded nothing".  ``False`` would
    # be a claim the integrated path -- which does honour the outer stop
    # callback -- never made.
    assert payload["stop_semantics_actual"] is None
    assert payload["outer_stop_callback_effective"] is None
    assert payload["improvement_events"] == []
    assert payload["kernel_round_summaries"] == []
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_round_summary_admits_a_missing_kernel_best_cost():
    """A round whose kernel best stayed infeasible has no cost to report."""

    payload = _accounting_with_a_trace().to_dict()
    assert payload["rounds"] == 2
    assert payload["outer_stop_callback_effective"] is False
    assert payload["stop_semantics_actual"].startswith("per-round NoImprovement")
    assert payload["improvement_events"] == [
        {"round": 1, "iteration": 0, "kernel_best_cost": 12.5},
        {"round": 1, "iteration": 3, "kernel_best_cost": 11.25},
    ]
    summaries = payload["kernel_round_summaries"]
    assert summaries[0]["kernel_best_cost"] == 11.25
    assert summaries[1]["kernel_best_cost"] is None
    # ``_json`` writes run metadata with ``allow_nan=False``; the missing cost
    # must survive that, which it would not as a float NaN.
    restored = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    assert restored["kernel_round_summaries"][1]["kernel_best_cost"] is None


def test_kernel_trace_csvs_are_written_from_the_accounting(tmp_path):
    trace_path, rounds_path = _write_kernel_trace_csvs(
        tmp_path, _accounting_with_a_trace()
    )
    assert trace_path == tmp_path / "improvement_trace.csv"
    assert rounds_path == tmp_path / "kernel_rounds.csv"

    trace_rows = list(
        csv.DictReader(trace_path.read_text(encoding="utf-8").splitlines())
    )
    assert [row["round"] for row in trace_rows] == ["1", "1"]
    assert [row["iteration"] for row in trace_rows] == ["0", "3"]
    assert [float(row["kernel_best_cost"]) for row in trace_rows] == [12.5, 11.25]

    round_rows = list(
        csv.DictReader(rounds_path.read_text(encoding="utf-8").splitlines())
    )
    assert list(round_rows[0]) == [
        "round",
        "iterations",
        "runtime_seconds",
        "improvements",
        "kernel_best_cost",
    ]
    assert float(round_rows[0]["kernel_best_cost"]) == 11.25
    # An empty cell, never the string "None".
    assert round_rows[1]["kernel_best_cost"] == ""


def test_kernel_trace_csvs_are_header_only_without_a_trace(tmp_path):
    """Search paths that record nothing still leave readable, empty files."""

    trace_path, rounds_path = _write_kernel_trace_csvs(
        tmp_path / "run", SearchAccounting()
    )
    assert trace_path.read_text(encoding="utf-8") == (
        "round,iteration,kernel_best_cost\n"
    )
    assert rounds_path.read_text(encoding="utf-8") == (
        "round,iterations,runtime_seconds,improvements,kernel_best_cost\n"
    )
