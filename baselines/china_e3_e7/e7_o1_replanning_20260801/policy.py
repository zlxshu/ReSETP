"""O1 streams and trigger batches over the approved 06:00--22:00 day."""

from __future__ import annotations

import math
from statistics import fmean
from typing import Callable, Sequence

from baselines.china_e3_e7.e7_h0_g2_foundation_20260801.stream import (
    build_h0_g2_stream,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    DynamicOrder,
    DynamicStream,
    TriggerBatch,
)
from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
)
from setp_solver.instance_loader import Instance

PER_ORDER = "per_order"
FIXED_30_MINUTES = "fixed_30_minutes"
HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES = "hybrid_two_mean_orders_or_30_minutes"
HYBRID_COUNT_10_PERCENT_OR_30_MINUTES = "hybrid_count_10_percent_or_30_minutes"
HYBRID_COUNT_20_PERCENT_OR_30_MINUTES = "hybrid_count_20_percent_or_30_minutes"
MASS_POLICIES = (
    PER_ORDER,
    FIXED_30_MINUTES,
    HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES,
)
COUNT_POLICIES = (
    PER_ORDER,
    FIXED_30_MINUTES,
    HYBRID_COUNT_10_PERCENT_OR_30_MINUTES,
    HYBRID_COUNT_20_PERCENT_OR_30_MINUTES,
)
# Keep the first exploratory runner reproducible.
POLICIES = MASS_POLICIES
INTERVAL_SECONDS = 30.0 * 60.0
COUNT_SHARES = {
    HYBRID_COUNT_10_PERCENT_OR_30_MINUTES: 0.10,
    HYBRID_COUNT_20_PERCENT_OR_30_MINUTES: 0.20,
}


def demand_threshold_kg(instance: Instance) -> float:
    """Transfer Qiu's roughly two-average-order threshold to one instance."""

    demands = [
        float(node.demand)
        for node in instance.nodes
        if node.node_type.lower() == "c"
    ]
    if not demands:
        raise ValueError("instance has no customers")
    return 2.0 * fmean(demands)


def order_count_threshold(dynamic_order_count: int, policy: str) -> int:
    """Return Ninikas--Minis' share of all dynamic orders as an integer count."""

    if dynamic_order_count <= 0:
        raise ValueError("dynamic_order_count must be positive")
    try:
        share = COUNT_SHARES[policy]
    except KeyError as exc:
        raise ValueError(f"policy {policy!r} has no order-count threshold") from exc
    return max(1, math.ceil(share * dynamic_order_count))


def build_o1_stream(
    instance: Instance,
    *,
    instance_id: str,
    stream_seed: int,
) -> DynamicStream:
    source = build_h0_g2_stream(
        instance,
        instance_id=instance_id,
        stream_seed=stream_seed,
    )
    additions = tuple(
        DynamicOrder(
            event_id=event.event_id,
            customer_id=str(event.customer_id),
            appearance_second=float(event.t_appear),
            demand_kg=float(event.new_demand),
            x=float(event.x),
            y=float(event.y),
            ready_second=float(event.new_ready_time),
            due_second=float(event.new_due_time),
            service_second=float(event.new_service_time),
            city=None,
        )
        for event in source.events
    )
    return DynamicStream(
        instance_id=source.instance_id,
        stream_seed=source.stream_seed,
        initial_customer_ids=source.initial_customer_ids,
        events=additions,
    )


def build_o1_batches(
    events: Sequence[DynamicOrder],
    policy: str,
    *,
    threshold_kg: float | None = None,
) -> tuple[TriggerBatch, ...]:
    ordered = sorted(events, key=lambda event: (event.appearance_second, event.event_id))
    if policy not in (*MASS_POLICIES, *COUNT_POLICIES):
        raise ValueError(f"unknown O1 policy {policy!r}")
    if policy == HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES and (
        threshold_kg is None or threshold_kg <= 0.0
    ):
        raise ValueError("threshold must be positive")
    for event in ordered:
        if not (
            CHINA81_HORIZON_START_SECOND
            <= event.appearance_second
            < CHINA81_HORIZON_END_SECOND
        ):
            raise ValueError(f"event {event.event_id} is outside 06:00--22:00")

    if policy == PER_ORDER:
        batches = [
            _batch(policy, index, event.appearance_second, "new_information", [event])
            for index, event in enumerate(ordered, start=1)
        ]
    elif policy == FIXED_30_MINUTES:
        batches = _fixed_batches(ordered)
    elif policy == HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES:
        assert threshold_kg is not None
        batches = _hybrid_batches(
            ordered,
            policy,
            lambda pending: sum(event.demand_kg for event in pending) >= threshold_kg,
            "demand_threshold",
        )
    else:
        threshold = order_count_threshold(len(ordered), policy)
        batches = _hybrid_batches(
            ordered,
            policy,
            lambda pending: len(pending) >= threshold,
            "order_count_threshold",
        )

    consumed = [event_id for batch in batches for event_id in batch.event_ids]
    if sorted(consumed) != sorted(event.event_id for event in ordered):
        raise AssertionError("O1 policy did not consume every event exactly once")
    return tuple(batches)


def _fixed_batches(events: Sequence[DynamicOrder]) -> list[TriggerBatch]:
    batches: list[TriggerBatch] = []
    pending: list[DynamicOrder] = []
    cursor = 0
    trigger = CHINA81_HORIZON_START_SECOND + INTERVAL_SECONDS
    while trigger <= CHINA81_HORIZON_END_SECOND:
        while cursor < len(events) and events[cursor].appearance_second <= trigger:
            pending.append(events[cursor])
            cursor += 1
        if pending:
            cause = (
                "window_end"
                if trigger == CHINA81_HORIZON_END_SECOND
                else "fixed_interval"
            )
            batches.append(_batch(FIXED_30_MINUTES, len(batches) + 1, trigger, cause, pending))
            pending = []
        trigger += INTERVAL_SECONDS
    return batches


def _hybrid_batches(
    events: Sequence[DynamicOrder],
    policy: str,
    threshold_reached: Callable[[Sequence[DynamicOrder]], bool],
    threshold_cause: str,
) -> list[TriggerBatch]:
    batches: list[TriggerBatch] = []
    pending: list[DynamicOrder] = []
    cursor = 0
    deadline = CHINA81_HORIZON_START_SECOND + INTERVAL_SECONDS
    while cursor < len(events):
        appearance = events[cursor].appearance_second
        while deadline < appearance:
            if pending:
                batches.append(
                    _batch(
                        policy,
                        len(batches) + 1,
                        deadline,
                        "maximum_wait",
                        pending,
                    )
                )
                pending = []
            deadline = min(
                deadline + INTERVAL_SECONDS, CHINA81_HORIZON_END_SECOND
            )
        while cursor < len(events) and events[cursor].appearance_second == appearance:
            pending.append(events[cursor])
            cursor += 1
        if threshold_reached(pending):
            batches.append(
                _batch(
                    policy,
                    len(batches) + 1,
                    appearance,
                    threshold_cause,
                    pending,
                )
            )
            pending = []
            deadline = min(
                appearance + INTERVAL_SECONDS, CHINA81_HORIZON_END_SECOND
            )

    if pending:
        trigger = min(deadline, CHINA81_HORIZON_END_SECOND)
        cause = "window_end" if trigger == CHINA81_HORIZON_END_SECOND else "maximum_wait"
        batches.append(
            _batch(
                policy,
                len(batches) + 1,
                trigger,
                cause,
                pending,
            )
        )
    return batches


def _batch(
    policy: str,
    index: int,
    trigger_second: float,
    cause: str,
    events: Sequence[DynamicOrder],
) -> TriggerBatch:
    ordered = sorted(events, key=lambda event: (event.appearance_second, event.event_id))
    return TriggerBatch(
        policy=policy,
        batch_index=index,
        trigger_second=float(trigger_second),
        cause=cause,
        event_ids=tuple(event.event_id for event in ordered),
        customer_ids=tuple(event.customer_id for event in ordered),
        event_types=tuple("add" for _ in ordered),
        demand_kg=sum(event.demand_kg for event in ordered),
    )
