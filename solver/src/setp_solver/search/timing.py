"""Opt-in timing helpers for search diagnostics.

The timing ledger is attached dynamically to an ``EvaluationContext`` by
diagnostic runners. Normal solver paths do not create one, so these helpers are
effectively no-ops outside profiling gates.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import time
from typing import Any, Iterator


@dataclass
class TimingLedger:
    rows: dict[str, dict[str, float]] = field(default_factory=dict)

    def record(self, label: str, seconds: float, *, count: int = 1) -> None:
        row = self.rows.setdefault(str(label), {"seconds": 0.0, "count": 0.0})
        row["seconds"] += float(seconds)
        row["count"] += float(count)

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {label: {"seconds": float(row["seconds"]), "count": float(row["count"])} for label, row in sorted(self.rows.items())}


def attach_timing_ledger(context: Any, ledger: TimingLedger | None = None) -> TimingLedger:
    active = ledger or TimingLedger()
    setattr(context, "_timing_ledger", active)
    return active


def get_timing_ledger(context: Any) -> TimingLedger | None:
    return getattr(context, "_timing_ledger", None)


@contextmanager
def timed_section(context: Any, label: str) -> Iterator[None]:
    ledger = get_timing_ledger(context)
    if ledger is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        ledger.record(label, time.perf_counter() - started)


def record_timing(context: Any, label: str, seconds: float, *, count: int = 1) -> None:
    ledger = get_timing_ledger(context)
    if ledger is not None:
        ledger.record(label, seconds, count=count)
