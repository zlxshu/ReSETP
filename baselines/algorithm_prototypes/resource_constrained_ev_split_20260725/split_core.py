"""Exact non-dominated label setting for one frozen customer order.

The routine is intentionally model-agnostic.  The China81 adapter supplies
route-segment choices whose fleet and charger resource increments have
already passed route-local hard checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

ChargerUse = tuple[tuple[str, int, int, int], ...]


class ResourceLimitError(RuntimeError):
    """The exact non-dominated label set exceeded a frozen safety limit."""


@dataclass(frozen=True)
class SegmentChoice:
    start: int
    end: int
    cost: float
    fleet_delta: tuple[int, ...]
    charger_delta: ChargerUse
    payload: Any
    source: str = "generated"


@dataclass(frozen=True)
class _Label:
    position: int
    cost: float
    fleet_use: tuple[int, ...]
    charger_use: ChargerUse
    choices: tuple[SegmentChoice, ...]


@dataclass(frozen=True)
class SplitResult:
    choices: tuple[SegmentChoice, ...]
    cost: float
    fleet_use: tuple[int, ...]
    charger_use: ChargerUse
    generated_labels: int
    dominated_labels: int
    duplicate_labels: int
    labels_by_position: tuple[int, ...]


def solve_resource_constrained_split(
    customer_count: int,
    choices_by_start: Mapping[int, tuple[SegmentChoice, ...]],
    *,
    fleet_caps: tuple[int, ...],
    charger_caps: Mapping[str, int],
    max_labels_per_position: int = 50_000,
    max_generated_labels: int = 500_000,
) -> SplitResult:
    """Find the cheapest resource-feasible path from position 0 to n.

    No beam or objective-dependent truncation is used.  Labels are removed
    only by exact duplicate replacement or componentwise safe dominance.
    """

    if customer_count < 1:
        raise ValueError("customer_count must be positive")
    if not fleet_caps or any(cap < 0 for cap in fleet_caps):
        raise ValueError("fleet caps must be a non-empty nonnegative tuple")
    if max_labels_per_position < 1 or max_generated_labels < 1:
        raise ValueError("label safety limits must be positive")

    labels: list[list[_Label]] = [[] for _ in range(customer_count + 1)]
    labels[0].append(
        _Label(
            position=0,
            cost=0.0,
            fleet_use=tuple(0 for _ in fleet_caps),
            charger_use=(),
            choices=(),
        )
    )
    generated = 1
    dominated = 0
    duplicates = 0

    for position in range(customer_count):
        for label in tuple(labels[position]):
            for choice in choices_by_start.get(position, ()):
                if choice.start != position or not (
                    position < choice.end <= customer_count
                ):
                    raise ValueError("segment choice has invalid boundaries")
                if len(choice.fleet_delta) != len(fleet_caps):
                    raise ValueError("segment fleet dimension mismatch")
                fleet_use = tuple(
                    used + delta
                    for used, delta in zip(
                        label.fleet_use,
                        choice.fleet_delta,
                        strict=True,
                    )
                )
                if any(
                    used > cap
                    for used, cap in zip(
                        fleet_use,
                        fleet_caps,
                        strict=True,
                    )
                ):
                    continue
                charger_use = merge_charger_use(
                    label.charger_use,
                    choice.charger_delta,
                )
                if not charger_use_within_caps(
                    charger_use,
                    charger_caps,
                ):
                    continue
                generated += 1
                if generated > max_generated_labels:
                    raise ResourceLimitError(
                        "total generated-label safety limit exceeded"
                    )
                candidate = _Label(
                    position=choice.end,
                    cost=label.cost + float(choice.cost),
                    fleet_use=fleet_use,
                    charger_use=charger_use,
                    choices=(*label.choices, choice),
                )
                accepted, removed, duplicate = _insert_label(
                    labels[choice.end],
                    candidate,
                )
                dominated += removed + (0 if accepted else 1)
                duplicates += int(duplicate)
                if (
                    accepted
                    and len(labels[choice.end])
                    > max_labels_per_position
                ):
                    raise ResourceLimitError(
                        "per-position non-dominated-label safety limit "
                        f"exceeded at {choice.end}"
                    )

    if not labels[customer_count]:
        raise ValueError("no complete resource-feasible split path")
    winner = min(
        labels[customer_count],
        key=lambda item: (
            item.cost,
            item.fleet_use,
            item.charger_use,
            tuple(
                (
                    choice.start,
                    choice.end,
                    choice.source,
                    repr(choice.payload),
                )
                for choice in item.choices
            ),
        ),
    )
    return SplitResult(
        choices=winner.choices,
        cost=float(winner.cost),
        fleet_use=winner.fleet_use,
        charger_use=winner.charger_use,
        generated_labels=generated,
        dominated_labels=dominated,
        duplicate_labels=duplicates,
        labels_by_position=tuple(len(rows) for rows in labels),
    )


def merge_charger_use(
    current: ChargerUse,
    added: ChargerUse,
) -> ChargerUse:
    counts = {
        (station, day, slot): int(count)
        for station, day, slot, count in current
    }
    for station, day, slot, count in added:
        key = (station, int(day), int(slot))
        counts[key] = counts.get(key, 0) + int(count)
    return tuple(
        (station, day, slot, count)
        for (station, day, slot), count in sorted(counts.items())
        if count
    )


def charger_use_within_caps(
    use: ChargerUse,
    caps: Mapping[str, int],
) -> bool:
    return all(
        count <= int(caps.get(station, 1))
        for station, _, _, count in use
    )


def _insert_label(
    bucket: list[_Label],
    candidate: _Label,
) -> tuple[bool, int, bool]:
    """Insert candidate unless an existing label safely dominates it."""

    candidate_key = (candidate.fleet_use, candidate.charger_use)
    for index, existing in enumerate(bucket):
        existing_key = (existing.fleet_use, existing.charger_use)
        if existing_key == candidate_key:
            if existing.cost <= candidate.cost + 1.0e-12:
                return False, 0, True
            bucket[index] = candidate
            return True, 1, True
        if _dominates(existing, candidate):
            return False, 0, False

    retained: list[_Label] = []
    removed = 0
    for existing in bucket:
        if _dominates(candidate, existing):
            removed += 1
        else:
            retained.append(existing)
    retained.append(candidate)
    bucket[:] = retained
    return True, removed, False


def _dominates(left: _Label, right: _Label) -> bool:
    if left.cost > right.cost + 1.0e-12:
        return False
    if any(
        a > b
        for a, b in zip(
            left.fleet_use,
            right.fleet_use,
            strict=True,
        )
    ):
        return False
    left_slots = {
        (station, day, slot): count
        for station, day, slot, count in left.charger_use
    }
    right_slots = {
        (station, day, slot): count
        for station, day, slot, count in right.charger_use
    }
    if any(
        left_slots.get(key, 0) > count
        for key, count in right_slots.items()
    ):
        return False
    if any(
        count > right_slots.get(key, 0)
        for key, count in left_slots.items()
        if key not in right_slots
    ):
        return False
    return (
        left.cost < right.cost - 1.0e-12
        or left.fleet_use != right.fleet_use
        or left.charger_use != right.charger_use
    )
