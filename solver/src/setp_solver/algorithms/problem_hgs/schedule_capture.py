"""Opt-in raw-candidate capture for DSS step-1 paired technical questions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .evaluation import DutyEvaluationContext
from .model import DutyIndividual


@dataclass(frozen=True)
class ScheduleCaptureRecord:
    channel: str
    action_id: str
    iteration: int | None
    reference: DutyIndividual
    raw_candidate: DutyIndividual
    changed_duty_ids: frozenset[str]
    context: DutyEvaluationContext
    a0_status: str
    a0_error_type: str | None
    a0_error: str | None


ScheduleCaptureSink = Callable[[ScheduleCaptureRecord], None]
_SINK: ContextVar[ScheduleCaptureSink | None] = ContextVar(
    "problem_hgs_schedule_capture_sink",
    default=None,
)


@contextmanager
def schedule_capture_sink(sink: ScheduleCaptureSink) -> Iterator[None]:
    """Install one local sink without changing the algorithm's decisions."""

    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


def emit_schedule_capture(
    *,
    channel: str,
    action_id: str,
    iteration: int | None,
    reference: DutyIndividual,
    raw_candidate: DutyIndividual,
    changed_duty_ids: frozenset[str],
    context: DutyEvaluationContext,
    a0_status: str,
    error: Exception | None,
) -> None:
    sink = _SINK.get()
    if sink is None:
        return
    sink(
        ScheduleCaptureRecord(
            channel=str(channel),
            action_id=str(action_id),
            iteration=None if iteration is None else int(iteration),
            reference=reference,
            raw_candidate=raw_candidate,
            changed_duty_ids=frozenset(changed_duty_ids),
            context=context,
            a0_status=str(a0_status),
            a0_error_type=None if error is None else type(error).__name__,
            a0_error=None if error is None else str(error),
        )
    )

