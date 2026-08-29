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
            termination_status="CONVERGED_NO_IMPROVEMENT"
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
