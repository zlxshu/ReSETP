from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import setp_solver.algorithms.problem_hgs.education as education_module
from setp_solver.algorithms.problem_hgs.contracts import (
    CandidateOutcome,
    CandidateStatus,
    SearchAccounting,
)
from setp_solver.algorithms.problem_hgs.education import (
    _meaningfully_better,
    educate_best_improvement,
)


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
    breakdown: dict = None
    participation_margin: dict = None
    accounting: dict = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "breakdown", {} if self.breakdown is None else self.breakdown)
        object.__setattr__(
            self,
            "participation_margin",
            {} if self.participation_margin is None else self.participation_margin,
        )
        object.__setattr__(
            self,
            "accounting",
            {} if self.accounting is None else self.accounting,
        )


class _Evaluator:
    context = SimpleNamespace(
        bundle=SimpleNamespace(instance=object()),
        dynamic_state=None,
    )


@dataclass(frozen=True)
class _Move:
    action_id: str
    changed_duty_ids: frozenset[str] = frozenset({"D0"})


class _FiniteProposalEngine:
    source_id = "education-depth-test"

    def __init__(self, move_count: int) -> None:
        self._move_count = move_count
        self.calls = 0

    def propose(self, *_args, **_kwargs):
        if self.calls >= self._move_count:
            return ()
        move = _Move(f"move-{self.calls}")
        self.calls += 1
        return (move,)


class _IncrementalEvaluator:
    def __init__(self, _evaluator) -> None:
        pass

    def seed(self, _individual) -> int:
        return 0


def _run(monkeypatch, *, move_count: int, max_education_rounds: int | None):
    def fake_evaluate_move(current, move, **_kwargs):
        candidate = _Individual(move.action_id, current.cost - 1.0)
        return CandidateOutcome(
            action_id=move.action_id,
            channel="test",
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=move.changed_duty_ids,
            candidate=candidate,
            evaluation=_Evaluation(candidate.fingerprint, candidate.cost),
            wall_seconds=0.1,
        )

    monkeypatch.setattr(education_module, "evaluate_move", fake_evaluate_move)
    monkeypatch.setattr(
        education_module,
        "DutyIncrementalEvaluator",
        _IncrementalEvaluator,
    )
    initial = _Individual("initial", 10.0)
    initial_evaluation = _Evaluation(initial.fingerprint, initial.cost)
    accounting = SearchAccounting()
    engine = _FiniteProposalEngine(move_count)
    result = educate_best_improvement(
        initial,
        evaluator=_Evaluator(),
        charging_policy=object(),
        arm="test",
        iteration=1,
        accounting=accounting,
        penalized_cost=lambda evaluation: evaluation.total_cost,
        initial_evaluation=initial_evaluation,
        proposal_engine=engine,
        record_trajectory=False,
        max_education_rounds=max_education_rounds,
    )
    return result, accounting, engine


def test_education_depth_cap_stops_after_n_rounds_and_records_boundary(
    monkeypatch,
):
    (individual, evaluation, _rows), accounting, engine = _run(
        monkeypatch,
        move_count=5,
        max_education_rounds=2,
    )

    assert individual.fingerprint == "move-1"
    assert evaluation.total_cost == 8.0
    assert accounting.education_rounds == 2
    assert accounting.education_depth_cap_triggers == 1
    assert accounting.education_depth_cap_triggers_while_improving == 1
    assert engine.calls == 2


def test_unlimited_education_keeps_existing_stop_behavior(monkeypatch):
    (individual, evaluation, _rows), accounting, engine = _run(
        monkeypatch,
        move_count=2,
        max_education_rounds=None,
    )

    assert individual.fingerprint == "move-1"
    assert evaluation.total_cost == 8.0
    assert accounting.education_depth_cap_triggers == 0
    assert accounting.education_depth_cap_triggers_while_improving == 0
    assert engine.calls == 2


def test_education_depth_limit_must_be_positive(monkeypatch):
    with pytest.raises(ValueError, match="maximum education rounds"):
        _run(monkeypatch, move_count=1, max_education_rounds=0)


def test_education_rejects_float_noise_as_an_improvement() -> None:
    incumbent = 2615.8448349767523

    assert not _meaningfully_better(2615.8448349767520, incumbent)
    assert _meaningfully_better(2615.8448349747520, incumbent)
