"""Approved E7 order-reveal and trigger mechanics; stream selection stays external."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
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
class TriggerBatch:
    policy: str
    batch_index: int
    trigger_second: float
    cause: str
    event_ids: tuple[str, ...]
    customer_ids: tuple[str, ...]
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


def build_trigger_batches(
    orders: Sequence[DynamicOrder],
    policy: str,
) -> tuple[TriggerBatch, ...]:
    """Partition one immutable order stream under an approved trigger policy."""

    ordered = _checked_orders(orders)
    if policy == PER_ORDER:
        batches = [
            _batch(policy, index + 1, order.appearance_second, "new_order", [order])
            for index, order in enumerate(ordered)
        ]
    elif policy == FIXED_30_MINUTES:
        batches = _fixed_batches(ordered)
    elif policy == HYBRID_500KG_OR_30_MINUTES:
        batches = _hybrid_batches(ordered)
    else:
        raise ValueError(f"unknown trigger policy {policy!r}")

    seen = [event_id for batch in batches for event_id in batch.event_ids]
    if sorted(seen) != sorted(order.event_id for order in ordered):
        raise AssertionError("trigger policy did not consume each event exactly once")
    return tuple(batches)


def _fixed_batches(orders: Sequence[DynamicOrder]) -> list[TriggerBatch]:
    batches: list[TriggerBatch] = []
    cursor = 0
    trigger = RECEPTION_START_SECOND + FIXED_INTERVAL_SECONDS
    while trigger <= RECEPTION_END_SECOND:
        pending: list[DynamicOrder] = []
        while cursor < len(orders) and orders[cursor].appearance_second <= trigger:
            pending.append(orders[cursor])
            cursor += 1
        if pending:
            cause = "window_end" if trigger == RECEPTION_END_SECOND else "fixed_interval"
            batches.append(_batch(FIXED_30_MINUTES, len(batches) + 1, trigger, cause, pending))
        trigger += FIXED_INTERVAL_SECONDS
    return batches


def _hybrid_batches(orders: Sequence[DynamicOrder]) -> list[TriggerBatch]:
    batches: list[TriggerBatch] = []
    pending: list[DynamicOrder] = []
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
        demand = sum(order.demand_kg for order in pending)
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
    orders: Sequence[DynamicOrder],
) -> TriggerBatch:
    ordered = sorted(orders, key=_order_key)
    return TriggerBatch(
        policy,
        index,
        trigger,
        cause,
        tuple(order.event_id for order in ordered),
        tuple(order.customer_id for order in ordered),
        sum(order.demand_kg for order in ordered),
    )


def _checked_orders(orders: Sequence[DynamicOrder]) -> list[DynamicOrder]:
    ordered = sorted(orders, key=_order_key)
    if len({order.event_id for order in ordered}) != len(ordered) or len(
        {order.customer_id for order in ordered}
    ) != len(ordered):
        raise ValueError("dynamic order ids are not unique")
    for order in ordered:
        if not math.isfinite(order.appearance_second) or not (
            RECEPTION_START_SECOND <= order.appearance_second < RECEPTION_END_SECOND
        ):
            raise ValueError(f"order {order.customer_id} appears outside [08:00, 10:00)")
        if order.appearance_second >= order.due_second - _TOL:
            raise ValueError(f"order {order.customer_id} is born expired")
        if not math.isfinite(order.demand_kg) or order.demand_kg <= 0.0:
            raise ValueError(f"order {order.customer_id} has invalid demand")
    return ordered


def _order_key(order: DynamicOrder) -> tuple[float, str, str]:
    return (order.appearance_second, order.event_id, order.customer_id)
