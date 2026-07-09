"""Experiment / artifact registry for the control console."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


EXPERIMENT_ORDER: tuple[str, ...] = ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "PAPER")

ARTIFACT_ORDER: tuple[str, ...] = (
    "T1",
    "T3",
    "T4",
    "T5",
    "T6",
    "T7",
    "T8",
    "T9",
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F5b",
    "F6",
    "F7",
)

ARTIFACT_KIND: dict[str, str] = {
    **{a: "table" for a in ARTIFACT_ORDER if a.startswith("T")},
    **{a: "figure" for a in ARTIFACT_ORDER if a.startswith("F")},
}

# Blueprint mapping: experiment → typical artifacts
DEFAULT_EXPERIMENT_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "E1": ("T4", "F1"),
    "E2": ("T3", "F2"),
    "E3": ("T5",),
    "E4": ("T1",),
    "E5": ("T6", "F3", "F4"),
    "E6": ("T8", "F6"),
    "E7": ("T9", "F7"),
    "PAPER": tuple(ARTIFACT_ORDER),
}


@dataclass(frozen=True)
class Job:
    experiment: str
    artifact: str
    instances: tuple[str, ...]
    job_id: str = ""

    @property
    def kind(self) -> str:
        return ARTIFACT_KIND.get(self.artifact, "unknown")


def _index(order: tuple[str, ...], item: str, label: str) -> int:
    try:
        return order.index(item)
    except ValueError as exc:
        raise ValueError(f"Unknown {label} id {item!r}. Allowed: {', '.join(order)}") from exc


def expand_range(start: str, end: str, order: tuple[str, ...], label: str) -> tuple[str, ...]:
    i = _index(order, start, label)
    j = _index(order, end, label)
    if i > j:
        raise ValueError(f"{label} range inverted: {start} > {end}")
    return order[i : j + 1]


def normalize_artifacts(items: Iterable[str] | None, experiment: str | None = None) -> tuple[str, ...]:
    if not items:
        if experiment and experiment in DEFAULT_EXPERIMENT_ARTIFACTS:
            return DEFAULT_EXPERIMENT_ARTIFACTS[experiment]
        return ()
    out: list[str] = []
    for raw in items:
        token = str(raw).strip().upper()
        if token == "ALL":
            out.extend(ARTIFACT_ORDER)
            continue
        if token not in ARTIFACT_ORDER:
            raise ValueError(f"Unknown artifact id {raw!r}. Allowed: {', '.join(ARTIFACT_ORDER)} or ALL")
        out.append(token)
    # preserve order, unique
    seen: set[str] = set()
    uniq: list[str] = []
    for a in out:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return tuple(uniq)


def normalize_experiments(items: Iterable[str] | None) -> tuple[str, ...]:
    if not items:
        return ()
    out: list[str] = []
    for raw in items:
        token = str(raw).strip().upper()
        if token not in EXPERIMENT_ORDER:
            raise ValueError(f"Unknown experiment id {raw!r}. Allowed: {', '.join(EXPERIMENT_ORDER)}")
        out.append(token)
    seen: set[str] = set()
    uniq: list[str] = []
    for e in out:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return tuple(uniq)
