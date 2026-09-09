from __future__ import annotations

from types import SimpleNamespace

import pytest

from setp_solver import main3b_backend
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)


def test_full_information_static_uses_one_hgs_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    individual = DutyIndividual(duties=(), source="test")
    evaluation = SimpleNamespace(
        feasible=True,
        prepared_solution=SimpleNamespace(routes=(), charging_actions=()),
        certificate=SimpleNamespace(trips=()),
    )
    stream = SimpleNamespace(
        events=(),
        added_customer_ids=frozenset(),
    )
    problem = SimpleNamespace(
        base_context=object(),
        base_bundle=object(),
        full_bundle=object(),
        base_initial=individual,
        static_customer_ids=frozenset(),
        dynamic_customer_ids=frozenset(),
        c8_stream=stream,
    )
    calls: list[str] = []

    class _Evaluator:
        def __init__(self, context: object) -> None:
            del context

        def evaluate(self, candidate: object) -> object:
            assert candidate.duties == individual.duties
            assert candidate.unserved_customers == individual.unserved_customers
            return evaluation

    def _one_hgs(
        self: object,
        candidate: object,
        context: object,
        *,
        arm: str,
        stage_index: int,
    ) -> tuple[object, object, object]:
        del self, context, stage_index
        assert candidate.duties == individual.duties
        assert candidate.unserved_customers == individual.unserved_customers
        calls.append(arm)
        return individual, evaluation, SimpleNamespace(
            termination_status="STOPPED_BY_CALLER"
        )

    monkeypatch.setattr(main3b_backend, "DutyFullEvaluator", _Evaluator)
    monkeypatch.setattr(
        main3b_backend,
        "subset_c8_bundle",
        lambda bundle, active, events=(): bundle,
    )
    monkeypatch.setattr(
        main3b_backend,
        "_static_context",
        lambda context, bundle: context,
    )
    monkeypatch.setattr(
        main3b_backend,
        "_context_with_bundle",
        lambda context, bundle, current_problem: context,
    )
    monkeypatch.setattr(main3b_backend.ProductionBackend, "_run_hgs", _one_hgs)

    state = main3b_backend.ProductionBackend().full_information_static(problem, ())

    assert state.evaluation is evaluation
    assert calls == ["full_information_static_reference"]


def test_cancelled_customer_is_removed_from_duty() -> None:
    individual = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_A",
                "cv",
                "D0",
                (DutyTrip(1, ("A", "B", "C")),),
            ),
        )
    )

    filtered = main3b_backend._without_customers(individual, ("B",))

    assert filtered.duties[0].trips[0].customer_ids == ("A", "C")


def test_route_change_stat_counts_removed_old_arc_and_changed_assets() -> None:
    before = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_A",
                "cv",
                "D0",
                (DutyTrip(1, ("A", "B", "C")),),
            ),
            PhysicalVehicleDuty(
                "CV_B",
                "cv",
                "D0",
                (DutyTrip(1, ("D",)),),
            ),
        ),
        unserved_customers=("X",),
    )
    after = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_A",
                "cv",
                "D0",
                (DutyTrip(1, ("A", "X", "B", "C", "D")),),
            ),
        )
    )
    old = {"A", "B", "C", "D"}

    before_arcs = main3b_backend._old_customer_arcs(before, old)
    after_arcs = main3b_backend._old_customer_arcs(after, old)
    before_assets = main3b_backend._customer_vehicle_assignment(before, old)
    after_assets = main3b_backend._customer_vehicle_assignment(after, old)

    assert before_arcs - after_arcs == {("A", "B")}
    assert before_assets["D"] == "CV_B"
    assert after_assets["D"] == "CV_A"


def test_production_backend_rejects_internal_error() -> None:
    abnormal = SimpleNamespace(
        termination_status="INTERNAL_ERROR",
        termination_error_type="RuntimeError",
        termination_error="boom",
    )
    with pytest.raises(main3b_backend.ProductionBackendHalt, match="INTERNAL_ERROR"):
        main3b_backend._require_normal_hgs_termination(
            abnormal,
            arm="rolling_dynamic",
        )


# --------------------------------------------------------------------------
# 2026-09-09: the opt-in deterministic per-stage cycle cap.
# --------------------------------------------------------------------------


class _StubState:
    """The two fields the stage stop rule reads off ProblemHGSSearchState."""

    def __init__(self, iterations: int, iterations_without_improvement: int):
        self.iterations = iterations
        self.iterations_without_improvement = iterations_without_improvement
        self.best_cost = 1.0


def _run_stub_stage(
    *,
    cycle_cap: int | None,
    patience: int = 20_000,
    improves_every_cycle: bool = True,
    max_cycles: int = 200,
) -> tuple[int | None, list[bool]]:
    """Drive the stop rule over a stub stage; return the stopping cycle."""

    hits: list[bool] = []
    stop = main3b_backend._stage_stop_rule(
        arm="rolling_dynamic",
        stage_index=4,
        patience=patience,
        cycle_cap=cycle_cap,
        on_cap_hit=lambda: hits.append(True),
        clock=lambda: 0.0,
    )
    for cycle in range(max_cycles + 1):
        noimp = 0 if improves_every_cycle else cycle
        if stop(_StubState(cycle, noimp)):
            return cycle, hits
    return None, hits


def test_stage_cycle_cap_stops_a_stage_that_improves_every_cycle() -> None:
    stopped_at, hits = _run_stub_stage(cycle_cap=25)
    assert stopped_at == 25
    assert hits == [True]


def test_stage_cycle_cap_off_leaves_the_patience_rule_alone() -> None:
    # Improving every cycle: patience never fires, and without a cap the
    # stage has no upper bound at all -- the behaviour this option gates.
    stopped_at, hits = _run_stub_stage(cycle_cap=None, max_cycles=100_000)
    assert stopped_at is None
    assert hits == []
    # Stagnating: the patience rule fires at exactly the patience value.
    stopped_at, hits = _run_stub_stage(
        cycle_cap=None,
        patience=30,
        improves_every_cycle=False,
    )
    assert stopped_at == 30
    assert hits == []


def test_stage_cycle_cap_never_outlives_patience() -> None:
    # A cap looser than patience must not extend a stagnating stage.
    stopped_at, hits = _run_stub_stage(
        cycle_cap=100,
        patience=30,
        improves_every_cycle=False,
    )
    assert stopped_at == 30
    assert hits == []


def test_capped_stop_is_a_normal_termination() -> None:
    # The cap returns True from the same stop callback as patience, so the
    # stage still finishes STOPPED_BY_CALLER and the audit sees it as normal.
    main3b_backend._require_normal_hgs_termination(
        SimpleNamespace(termination_status="STOPPED_BY_CALLER"),
        arm="rolling_dynamic",
    )
    assert "STOPPED_BY_CALLER" in main3b_backend.NORMAL_PROBLEM_HGS_TERMINATIONS


def test_reference_arms_ignore_the_rolling_cap() -> None:
    backend = main3b_backend.ProductionBackend(stage_cycle_cap=25)
    assert backend._cycle_cap_for("rolling_dynamic") == 25
    assert backend._cycle_cap_for("initial_plan") is None
    assert backend._cycle_cap_for("full_information_static_reference") is None
    reference = main3b_backend.ProductionBackend(reference_cycle_cap=7)
    assert reference._cycle_cap_for("rolling_dynamic") is None
    assert reference._cycle_cap_for("initial_plan") == 7
    assert reference._cycle_cap_for("full_information_static_reference") == 7


def test_cap_diagnostics_absent_when_the_switch_is_off() -> None:
    off = main3b_backend.ProductionBackend()
    assert off._stage_cap_diagnostics("rolling_dynamic", 4) == {}
    on = main3b_backend.ProductionBackend(stage_cycle_cap=25)
    on._stage_cap_hits[("rolling_dynamic", 4)] = False
    assert on._stage_cap_diagnostics("rolling_dynamic", 4) == {
        "stage_cycle_cap_hit": False
    }
    on._stage_cap_hits[("rolling_dynamic", 5)] = True
    assert on._stage_cap_diagnostics("rolling_dynamic", 5) == {
        "stage_cycle_cap_hit": True
    }
    # Draining is what keeps consecutive stages apart: once read, the
    # flag is gone, so the next stage starts from no entry at all.
    assert on._stage_cap_diagnostics("rolling_dynamic", 5) == {}


def test_non_positive_cycle_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="stage_cycle_cap"):
        main3b_backend.ProductionBackend(stage_cycle_cap=0)
    with pytest.raises(ValueError, match="reference_cycle_cap"):
        main3b_backend.ProductionBackend(reference_cycle_cap=-1)
