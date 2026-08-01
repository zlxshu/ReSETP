"""Approved E7 dynamic-demand stream and trigger mechanics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random
from typing import Mapping, Sequence

from setp_solver.instance_loader import Instance
from setp_solver.search.dynamic import DynamicEvent


PER_ORDER = "per_order"
FIXED_30_MINUTES = "fixed_30_minutes"
HYBRID_500KG_OR_30_MINUTES = "hybrid_500kg_or_30_minutes"
POLICIES = (PER_ORDER, FIXED_30_MINUTES, HYBRID_500KG_OR_30_MINUTES)

RECEPTION_START_SECOND = 8.0 * 3600.0
RECEPTION_END_SECOND = 10.0 * 3600.0
FIXED_INTERVAL_SECONDS = 30.0 * 60.0
HYBRID_DEMAND_THRESHOLD_KG = 500.0
_TOL = 1.0e-9

QIU_ADD_MINUTES = (8 * 60 + 3, 8 * 60 + 17, 8 * 60 + 59, 9 * 60 + 14, 9 * 60 + 43)
QIU_CANCEL_MINUTES = (8 * 60 + 35, 9 * 60 + 50)
QIU_REDUCE_MINUTE = 8 * 60 + 50
QIU_REDUCED_DEMAND_FACTOR = 180.0 / 215.0
SCALED_EVENT_COUNTS = {
    50: {"add": 10, "cancel": 4, "demand_change": 2},
    100: {"add": 20, "cancel": 8, "demand_change": 4},
    150: {"add": 30, "cancel": 12, "demand_change": 6},
}


@dataclass(frozen=True)
class DynamicOrder:
    event_id: str
    customer_id: str
    appearance_second: float
    demand_kg: float
    x: float
    y: float
    ready_second: float
    due_second: float
    service_second: float
    city: str | None

    def as_solver_event(self) -> DynamicEvent:
        return DynamicEvent(
            event_id=self.event_id,
            event_type="add",
            t_appear=self.appearance_second,
            customer_id=self.customer_id,
            old_demand=0.0,
            new_demand=self.demand_kg,
            x=self.x,
            y=self.y,
            new_ready_time=self.ready_second,
            new_due_time=self.due_second,
            new_service_time=self.service_second,
            demand_source="china81_original_order",
            time_window_source="china81_original_order",
            service_time_source="china81_original_order",
            donor_customer_id=self.customer_id,
            source="china81_original_order_reveal",
        )


@dataclass(frozen=True)
class DynamicUpdate:
    event_id: str
    event_type: str
    customer_id: str
    appearance_second: float
    old_demand_kg: float
    new_demand_kg: float

    def as_solver_event(self) -> DynamicEvent:
        return DynamicEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            t_appear=self.appearance_second,
            customer_id=self.customer_id,
            old_demand=self.old_demand_kg,
            new_demand=self.new_demand_kg,
            delta_demand=self.new_demand_kg - self.old_demand_kg,
            demand_source="qiu_scaled_existing_order",
            source="qiu_yingying_scaled_event",
        )


DemandEvent = DynamicOrder | DynamicUpdate


@dataclass(frozen=True)
class DynamicStream:
    instance_id: str
    stream_seed: int
    initial_customer_ids: tuple[str, ...]
    events: tuple[DemandEvent, ...]

    def as_solver_events(self) -> tuple[DynamicEvent, ...]:
        return tuple(event.as_solver_event() for event in self.events)


@dataclass(frozen=True)
class TriggerBatch:
    policy: str
    batch_index: int
    trigger_second: float
    cause: str
    event_ids: tuple[str, ...]
    customer_ids: tuple[str, ...]
    event_types: tuple[str, ...]
    demand_kg: float


def build_dynamic_orders(
    instance: Instance,
    appearance_second_by_customer: Mapping[str, float],
) -> tuple[DynamicOrder, ...]:
    """Copy selected China81 orders; selection and appearance times are inputs."""

    nodes = {node.node_id: node for node in instance.nodes}
    result: list[DynamicOrder] = []
    for customer_id, raw_appearance in appearance_second_by_customer.items():
        node = nodes.get(str(customer_id))
        if node is None or node.node_type.lower() != "c":
            raise ValueError(f"unknown China81 customer {customer_id!r}")
        appearance = float(raw_appearance)
        if not math.isfinite(appearance) or not (
            RECEPTION_START_SECOND <= appearance < RECEPTION_END_SECOND
        ):
            raise ValueError(f"appearance for {customer_id} must be in [08:00, 10:00)")
        if appearance >= float(node.due_time) - _TOL:
            raise ValueError(f"appearance for {customer_id} must be strictly before its due time")
        if float(node.demand) <= 0.0:
            raise ValueError(f"dynamic order {customer_id} has non-positive demand")
        result.append(
            DynamicOrder(
                event_id=f"ADD_{customer_id}",
                customer_id=str(customer_id),
                appearance_second=appearance,
                demand_kg=float(node.demand),
                x=float(node.x),
                y=float(node.y),
                ready_second=float(node.ready_time),
                due_second=float(node.due_time),
                service_second=float(node.service_time),
                city=node.city,
            )
        )
    return tuple(sorted(result, key=_order_key))


def dynamic_order_sha256(orders: Sequence[DynamicOrder]) -> str:
    encoded = json.dumps(
        [asdict(order) for order in sorted(orders, key=_order_key)],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_qiu_scaled_stream(
    instance: Instance,
    *,
    instance_id: str,
    stream_seed: int,
) -> DynamicStream:
    """Scale Qiu Yingying's 25-customer event pattern without changing the instance."""

    customers = sorted(
        (node for node in instance.nodes if node.node_type.lower() == "c"),
        key=lambda node: node.node_id,
    )
    counts = SCALED_EVENT_COUNTS.get(len(customers))
    if counts is None:
        raise ValueError("Qiu scaling is defined only for 50, 100, or 150 customers")

    seed_material = f"{instance_id}:{int(stream_seed)}".encode("utf-8")
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big"))
    pool = list(customers)
    rng.shuffle(pool)

    factor = counts["add"] // len(QIU_ADD_MINUTES)
    add_times = [minute * 60.0 for minute in QIU_ADD_MINUTES for _ in range(factor)]
    additions: list[DynamicOrder] = []
    for appearance in sorted(add_times, reverse=True):
        chosen_index = next(
            (
                index
                for index, node in enumerate(pool)
                if appearance < float(node.due_time) - _TOL
            ),
            None,
        )
        if chosen_index is None:
            raise ValueError("not enough customers whose due time follows their reveal time")
        node = pool.pop(chosen_index)
        additions.append(
            DynamicOrder(
                event_id=f"ADD_{node.node_id}",
                customer_id=node.node_id,
                appearance_second=appearance,
                demand_kg=float(node.demand),
                x=float(node.x),
                y=float(node.y),
                ready_second=float(node.ready_time),
                due_second=float(node.due_time),
                service_second=float(node.service_time),
                city=node.city,
            )
        )

    cancel_times = [minute * 60.0 for minute in QIU_CANCEL_MINUTES for _ in range(factor)]
    cancellations = [
        DynamicUpdate(
            event_id=f"CANCEL_{node.node_id}",
            event_type="cancel",
            customer_id=node.node_id,
            appearance_second=appearance,
            old_demand_kg=float(node.demand),
            new_demand_kg=0.0,
        )
        for node, appearance in zip(pool[: counts["cancel"]], cancel_times, strict=True)
    ]
    del pool[: counts["cancel"]]

    reductions = [
        DynamicUpdate(
            event_id=f"REDUCE_{node.node_id}",
            event_type="demand_change",
            customer_id=node.node_id,
            appearance_second=QIU_REDUCE_MINUTE * 60.0,
            old_demand_kg=float(node.demand),
            new_demand_kg=float(node.demand) * QIU_REDUCED_DEMAND_FACTOR,
        )
        for node in pool[: counts["demand_change"]]
    ]

    events: tuple[DemandEvent, ...] = tuple(
        sorted((*additions, *cancellations, *reductions), key=_event_key)
    )
    added_ids = {event.customer_id for event in additions}
    return DynamicStream(
        instance_id=str(instance_id),
        stream_seed=int(stream_seed),
        initial_customer_ids=tuple(
            node.node_id for node in customers if node.node_id not in added_ids
        ),
        events=events,
    )


def dynamic_stream_sha256(stream: DynamicStream) -> str:
    encoded = json.dumps(
        asdict(stream),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_trigger_batches(
    orders: Sequence[DemandEvent],
    policy: str,
) -> tuple[TriggerBatch, ...]:
    """Partition one immutable order stream under an approved trigger policy."""

    ordered = _checked_events(orders)
    if policy == PER_ORDER:
        batches = _arrival_batches(ordered)
    elif policy == FIXED_30_MINUTES:
        batches = _fixed_batches(ordered)
    elif policy == HYBRID_500KG_OR_30_MINUTES:
        batches = _hybrid_batches(ordered)
    else:
        raise ValueError(f"unknown trigger policy {policy!r}")

    seen = [event_id for batch in batches for event_id in batch.event_ids]
    if sorted(seen) != sorted(event.event_id for event in ordered):
        raise AssertionError("trigger policy did not consume each event exactly once")
    return tuple(batches)


def _arrival_batches(events: Sequence[DemandEvent]) -> list[TriggerBatch]:
    batches: list[TriggerBatch] = []
    cursor = 0
    while cursor < len(events):
        appearance = events[cursor].appearance_second
        end = cursor + 1
        while end < len(events) and events[end].appearance_second == appearance:
            end += 1
        batches.append(_batch(PER_ORDER, len(batches) + 1, appearance, "new_information", events[cursor:end]))
        cursor = end
    return batches


def _fixed_batches(orders: Sequence[DemandEvent]) -> list[TriggerBatch]:
    batches: list[TriggerBatch] = []
    cursor = 0
    trigger = RECEPTION_START_SECOND + FIXED_INTERVAL_SECONDS
    while trigger <= RECEPTION_END_SECOND:
        pending: list[DemandEvent] = []
        while cursor < len(orders) and orders[cursor].appearance_second <= trigger:
            pending.append(orders[cursor])
            cursor += 1
        if pending:
            cause = "window_end" if trigger == RECEPTION_END_SECOND else "fixed_interval"
            batches.append(_batch(FIXED_30_MINUTES, len(batches) + 1, trigger, cause, pending))
        trigger += FIXED_INTERVAL_SECONDS
    return batches


def _hybrid_batches(orders: Sequence[DemandEvent]) -> list[TriggerBatch]:
    batches: list[TriggerBatch] = []
    pending: list[DemandEvent] = []
    cursor = 0
    deadline = RECEPTION_START_SECOND + FIXED_INTERVAL_SECONDS

    while cursor < len(orders):
        appearance = orders[cursor].appearance_second
        while deadline < appearance:
            if pending:
                batches.append(_batch(HYBRID_500KG_OR_30_MINUTES, len(batches) + 1, deadline, "maximum_wait", pending))
                pending = []
            deadline = min(deadline + FIXED_INTERVAL_SECONDS, RECEPTION_END_SECOND)

        while cursor < len(orders) and orders[cursor].appearance_second == appearance:
            pending.append(orders[cursor])
            cursor += 1
        demand = sum(_added_demand(event) for event in pending)
        if demand >= HYBRID_DEMAND_THRESHOLD_KG:
            batches.append(_batch(HYBRID_500KG_OR_30_MINUTES, len(batches) + 1, appearance, "demand_threshold", pending))
            pending = []
            deadline = min(appearance + FIXED_INTERVAL_SECONDS, RECEPTION_END_SECOND)
        elif appearance == deadline:
            batches.append(_batch(HYBRID_500KG_OR_30_MINUTES, len(batches) + 1, deadline, "maximum_wait", pending))
            pending = []
            deadline = min(deadline + FIXED_INTERVAL_SECONDS, RECEPTION_END_SECOND)

    if pending:
        cause = "window_end" if deadline == RECEPTION_END_SECOND else "maximum_wait"
        batches.append(_batch(HYBRID_500KG_OR_30_MINUTES, len(batches) + 1, deadline, cause, pending))
    return batches


def _batch(
    policy: str,
    index: int,
    trigger: float,
    cause: str,
    orders: Sequence[DemandEvent],
) -> TriggerBatch:
    ordered = sorted(orders, key=_event_key)
    return TriggerBatch(
        policy,
        index,
        trigger,
        cause,
        tuple(order.event_id for order in ordered),
        tuple(order.customer_id for order in ordered),
        tuple(_event_type(order) for order in ordered),
        sum(_added_demand(order) for order in ordered),
    )


def _checked_events(events: Sequence[DemandEvent]) -> list[DemandEvent]:
    ordered = sorted(events, key=_event_key)
    if len({event.event_id for event in ordered}) != len(ordered):
        raise ValueError("dynamic event ids are not unique")
    for event in ordered:
        if not math.isfinite(event.appearance_second) or not (
            RECEPTION_START_SECOND <= event.appearance_second < RECEPTION_END_SECOND
        ):
            raise ValueError(f"event {event.event_id} appears outside [08:00, 10:00)")
        if isinstance(event, DynamicOrder):
            if event.appearance_second >= event.due_second - _TOL:
                raise ValueError(f"order {event.customer_id} is born expired")
            if not math.isfinite(event.demand_kg) or event.demand_kg <= 0.0:
                raise ValueError(f"order {event.customer_id} has invalid demand")
        elif event.event_type not in {"cancel", "demand_change"}:
            raise ValueError(f"unsupported update type {event.event_type!r}")
    return ordered


def _order_key(order: DynamicOrder) -> tuple[float, str, str]:
    return (order.appearance_second, order.event_id, order.customer_id)


def _event_key(event: DemandEvent) -> tuple[float, str, str]:
    return (event.appearance_second, event.event_id, event.customer_id)


def _event_type(event: DemandEvent) -> str:
    return "add" if isinstance(event, DynamicOrder) else event.event_type


def _added_demand(event: DemandEvent) -> float:
    return event.demand_kg if isinstance(event, DynamicOrder) else 0.0
