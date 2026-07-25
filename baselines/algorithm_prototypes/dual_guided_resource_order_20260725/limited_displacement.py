"""Deterministic k-limited customer-order DP with a movable route boundary."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any, Callable


ArcCost = Callable[[str, str, int], float]
TravelTime = Callable[[str, str, int], float]


@dataclass(frozen=True)
class OrderCandidate:
    first: tuple[str, ...]
    second: tuple[str, ...]
    proxy_cost: float
    split: int
    direction: int
    states_expanded: int


@dataclass(frozen=True)
class _Label:
    path: tuple[int, ...]
    cost: float
    arrival: float
    first_load: float
    second_load: float


def _advance_base(base: int, mask: int, n: int) -> tuple[int, int]:
    next_base = base + 1
    shifted = mask
    while next_base < n and shifted & 1:
        next_base += 1
        shifted >>= 1
    shifted >>= 1
    return next_base, shifted


def _eligible(base: int, mask: int, n: int, k: int) -> tuple[int, ...]:
    rows = [base]
    for offset in range(1, k + 1):
        index = base + offset
        if index >= n:
            break
        if not (mask & (1 << (offset - 1))):
            rows.append(index)
    return tuple(rows)


def generate_limited_displacement_orders(
    order: tuple[str, ...],
    *,
    direction: int,
    k: int,
    top_n: int,
    state_limit: int,
    demands: dict[str, float],
    max_payload: float,
    ready: dict[str, float],
    due: dict[str, float],
    service: dict[str, float],
    first_depot: str,
    second_depot: str,
    arc_cost: ArcCost,
    travel_time: TravelTime,
) -> tuple[tuple[OrderCandidate, ...], int]:
    """Return the best distinct order/split structures under N_k precedence."""

    if len(order) < 2 or len(set(order)) != len(order):
        raise ValueError("order must contain at least two unique customers")
    if k < 1 or top_n < 1 or state_limit < 1:
        raise ValueError("invalid DP limit")
    n = len(order)
    all_candidates: list[OrderCandidate] = []
    total_expanded = 0
    for split in range(1, n):
        states: dict[tuple[int, int, int], list[_Label]] = {
            (0, 0, -1): [
                _Label(
                    path=(),
                    cost=0.0,
                    arrival=0.0,
                    first_load=0.0,
                    second_load=0.0,
                )
            ]
        }
        for position in range(n):
            next_states: dict[tuple[int, int, int], list[_Label]] = {}
            phase = 0 if position < split else 1
            for (base, mask, last), labels in states.items():
                for label in labels:
                    for index in _eligible(base, mask, n, k):
                        customer = order[index]
                        demand = float(demands[customer])
                        first_load = label.first_load + (demand if phase == 0 else 0.0)
                        second_load = label.second_load + (demand if phase == 1 else 0.0)
                        if (
                            first_load > max_payload + 1.0e-9
                            or second_load > max_payload + 1.0e-9
                        ):
                            continue
                        depot = first_depot if phase == 0 else second_depot
                        if position == 0:
                            previous = depot
                            arrival_base = 0.0
                            edge_cost = arc_cost(previous, customer, phase)
                            travel = travel_time(previous, customer, phase)
                        elif position == split:
                            previous = order[last]
                            arrival_base = 0.0
                            edge_cost = (
                                arc_cost(previous, first_depot, 0)
                                + arc_cost(second_depot, customer, 1)
                            )
                            travel = travel_time(second_depot, customer, 1)
                        else:
                            previous = order[last]
                            arrival_base = label.arrival + float(service[previous])
                            edge_cost = arc_cost(previous, customer, phase)
                            travel = travel_time(previous, customer, phase)
                        arrival = max(
                            float(ready[customer]),
                            arrival_base + travel,
                        )
                        if arrival > float(due[customer]) + 1.0e-9:
                            continue
                        if index == base:
                            new_base, new_mask = _advance_base(base, mask, n)
                        else:
                            new_base = base
                            new_mask = mask | (1 << (index - base - 1))
                        key = (new_base, new_mask, index)
                        candidate = _Label(
                            path=(*label.path, index),
                            cost=label.cost + edge_cost,
                            arrival=arrival,
                            first_load=first_load,
                            second_load=second_load,
                        )
                        bucket = next_states.setdefault(key, [])
                        bucket.append(candidate)
                        bucket.sort(
                            key=lambda item: (
                                item.cost,
                                item.arrival,
                                item.path,
                            )
                        )
                        del bucket[top_n:]
            total_expanded += sum(
                len(labels) for labels in next_states.values()
            )
            if total_expanded > state_limit:
                raise RuntimeError(
                    f"DP state cap exceeded: {total_expanded}>{state_limit}"
                )
            states = next_states
            if not states:
                break
        for labels in states.values():
            for label in labels:
                if len(label.path) != n:
                    continue
                sequence = tuple(order[index] for index in label.path)
                tail = sequence[-1]
                phase = 1
                total_cost = label.cost + arc_cost(tail, second_depot, phase)
                all_candidates.append(
                    OrderCandidate(
                        first=sequence[:split],
                        second=sequence[split:],
                        proxy_cost=float(total_cost),
                        split=split,
                        direction=direction,
                        states_expanded=total_expanded,
                    )
                )
    unique: dict[tuple[tuple[str, ...], tuple[str, ...]], OrderCandidate] = {}
    for item in sorted(
        all_candidates,
        key=lambda row: (
            row.proxy_cost,
            row.first,
            row.second,
        ),
    ):
        unique.setdefault((item.first, item.second), item)
    return tuple(list(unique.values())[:top_n]), total_expanded


def internal_adjacencies(route: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    return frozenset(zip(route, route[1:]))


def is_material_order_and_membership_change(
    candidate: OrderCandidate,
    original_first: tuple[str, ...],
    original_second: tuple[str, ...],
) -> bool:
    """Require both changed route membership and changed internal adjacency."""

    membership_changed = {
        frozenset(candidate.first),
        frozenset(candidate.second),
    } != {
        frozenset(original_first),
        frozenset(original_second),
    }
    old_adjacencies = (
        internal_adjacencies(original_first)
        | internal_adjacencies(original_second)
    )
    new_adjacencies = (
        internal_adjacencies(candidate.first)
        | internal_adjacencies(candidate.second)
    )
    return membership_changed and new_adjacencies != old_adjacencies
