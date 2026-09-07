"""Paper-aligned mixed dynamic events for the selected China81 instance.

The paper event table is the source of truth. This module loads that table,
groups its events with the paper's time/quantity rule, and projects the result
into the existing in-memory China81 bundle.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node, RoadProfileMatrices
from setp_solver.instance_subset import rebuild_instance_matrix
from setp_solver.solution import Solution


C8_BASE_INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
C8_RECEPTION_START_SECOND = 8 * 60 * 60
C8_RECEPTION_END_SECOND = 10 * 60 * 60
C8_TRIGGER_INTERVAL_SECOND = 30 * 60
C8_TRIGGER_DEMAND_THRESHOLD_KG = 500.0
C8_DYNAMIC_EVENT_COUNT = 10
_TOL = 1.0e-9


@dataclass(frozen=True)
class C8Protocol:
    """The time/quantity trigger and event types stated in the paper."""

    policy_id: str = "PAPER_Q500_T30_MIXED_EVENTS"
    reception_start_second: float = C8_RECEPTION_START_SECOND
    reception_end_second: float = C8_RECEPTION_END_SECOND
    trigger_interval_second: float = C8_TRIGGER_INTERVAL_SECOND
    trigger_demand_threshold_kg: float = C8_TRIGGER_DEMAND_THRESHOLD_KG
    event_types: tuple[str, ...] = (
        "add",
        "cancel",
        "demand_change",
        "time_window_change",
    )


@dataclass(frozen=True)
class C8DynamicEvent:
    """One row from the dynamic-event table printed in the paper."""

    sequence: int
    customer_id: str
    event_type: str
    appearance_second: float
    longitude: float
    latitude: float
    old_ready_second: float
    old_due_second: float
    new_ready_second: float
    new_due_second: float
    old_demand_kg: float
    new_demand_kg: float
    service_minutes: float
    source_customer_id: str
    generator_component: str

    def __post_init__(self) -> None:
        if self.event_type not in C8Protocol().event_types:
            raise ValueError(f"unsupported dynamic event: {self.event_type}")

    @property
    def event_id(self) -> str:
        return f"event-{self.sequence}"

    @property
    def trigger_demand_kg(self) -> float:
        """Only newly arrived demand contributes to the quantity trigger."""

        return float(self.new_demand_kg) if self.event_type == "add" else 0.0


@dataclass(frozen=True)
class C8TriggerBatch:
    batch_index: int
    trigger_second: float
    cause: str
    event_ids: tuple[str, ...]
    customer_ids: tuple[str, ...]
    demand_kg: float


@dataclass(frozen=True)
class C8DynamicStream:
    base_instance_id: str
    protocol: C8Protocol
    events: tuple[C8DynamicEvent, ...]
    stream_directory: Path

    @property
    def added_customer_ids(self) -> frozenset[str]:
        return frozenset(
            event.customer_id for event in self.events if event.event_type == "add"
        )

    @property
    def trigger_batches(self) -> tuple[C8TriggerBatch, ...]:
        return _trigger_batches(self.events, self.protocol)


def load_c8_stream(
    path: Path,
    *,
    expected_base_instance_id: str = C8_BASE_INSTANCE_ID,
) -> C8DynamicStream:
    """Load the paper's mixed-event TSV without a seed or identity sidecar."""

    source = path / "events.tsv" if path.is_dir() else path
    with source.open(newline="", encoding="utf-8") as handle:
        rows = tuple(csv.DictReader(handle, delimiter="\t"))
    events = tuple(
        C8DynamicEvent(
            sequence=int(row["sequence"]),
            customer_id=row["customer_id"],
            event_type=row["event_type"],
            appearance_second=float(row["appearance_second"]),
            longitude=float(row["longitude"]),
            latitude=float(row["latitude"]),
            old_ready_second=float(row["old_ready_second"]),
            old_due_second=float(row["old_due_second"]),
            new_ready_second=float(row["new_ready_second"]),
            new_due_second=float(row["new_due_second"]),
            old_demand_kg=float(row["old_demand_kg"]),
            new_demand_kg=float(row["new_demand_kg"]),
            service_minutes=float(row["service_minutes"]),
            source_customer_id=row["source_customer_id"],
            generator_component=row["generator_component"],
        )
        for row in rows
    )
    if len(events) != C8_DYNAMIC_EVENT_COUNT:
        raise ValueError("the paper dynamic stream must contain ten events")
    return C8DynamicStream(
        base_instance_id=expected_base_instance_id,
        protocol=C8Protocol(),
        events=events,
        stream_directory=source.parent,
    )


def _trigger_batches(
    events: Sequence[C8DynamicEvent],
    protocol: C8Protocol,
) -> tuple[C8TriggerBatch, ...]:
    """Apply the paper's 500 kg / 30 minute first-arrival rule."""

    ordered = sorted(events, key=lambda event: (event.appearance_second, event.sequence))
    pending: list[C8DynamicEvent] = []
    batches: list[C8TriggerBatch] = []
    deadline = float(protocol.reception_start_second + protocol.trigger_interval_second)

    def flush(trigger_second: float, cause: str) -> None:
        nonlocal pending
        if not pending:
            return
        batches.append(
            C8TriggerBatch(
                batch_index=len(batches) + 1,
                trigger_second=float(trigger_second),
                cause=cause,
                event_ids=tuple(event.event_id for event in pending),
                customer_ids=tuple(event.customer_id for event in pending),
                demand_kg=sum(event.trigger_demand_kg for event in pending),
            )
        )
        pending = []

    for event in ordered:
        while deadline < event.appearance_second - _TOL:
            flush(deadline, "maximum_wait")
            deadline = min(
                deadline + float(protocol.trigger_interval_second),
                float(protocol.reception_end_second),
            )
        pending.append(event)
        if sum(item.trigger_demand_kg for item in pending) >= (
            float(protocol.trigger_demand_threshold_kg) - _TOL
        ):
            flush(event.appearance_second, "demand_threshold")
            deadline = min(
                event.appearance_second + float(protocol.trigger_interval_second),
                float(protocol.reception_end_second),
            )
    flush(
        min(deadline, float(protocol.reception_end_second)),
        "window_end" if deadline >= protocol.reception_end_second else "maximum_wait",
    )
    return tuple(batches)


def active_customers_after_events(
    initial_customer_ids: Iterable[str],
    events: Sequence[C8DynamicEvent],
) -> frozenset[str]:
    """Apply add/cancel lifecycle changes; attribute changes keep membership."""

    active = set(map(str, initial_customer_ids))
    for event in events:
        if event.event_type == "add":
            active.add(event.customer_id)
        elif event.event_type == "cancel":
            active.discard(event.customer_id)
    return frozenset(active)


def _expanded_instance(
    bundle: China81Bundle,
    events: Sequence[C8DynamicEvent],
) -> Instance:
    """Add the five paper customers using their registered source rows."""

    base = bundle.instance
    add_events = [event for event in events if event.event_type == "add"]
    nodes = list(base.nodes)
    for event in add_events:
        source = base.nodes[base.node_index[event.source_customer_id]]
        nodes.append(
            Node(
                node_id=event.customer_id,
                node_type="c",
                x=event.longitude,
                y=event.latitude,
                demand=event.new_demand_kg,
                ready_time=event.new_ready_second,
                due_time=event.new_due_second,
                service_time=event.service_minutes * 60.0,
                city=source.city,
            )
        )
    proxies = {event.customer_id: event.source_customer_id for event in add_events}
    source_indices = [base.node_index[proxies.get(node.node_id, node.node_id)] for node in nodes]
    matrix = [
        [float(base.distance_matrix[left][right]) for right in source_indices]
        for left in source_indices
    ]
    profiles = None
    if base.road_profiles is not None:
        profiles = {
            profile: RoadProfileMatrices(
                distance_m=tuple(
                    tuple(matrices.distance_m[left][right] for right in source_indices)
                    for left in source_indices
                ),
                duration_s=tuple(
                    tuple(matrices.duration_s[left][right] for right in source_indices)
                    for left in source_indices
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(matrices.sum_v2d_m3_s2[left][right] for right in source_indices)
                    for left in source_indices
                ),
            )
            for profile, matrices in base.road_profiles.items()
        }
    return replace(base, nodes=nodes, distance_matrix=matrix, road_profiles=profiles)


def overlay_c8_bundle(
    bundle: China81Bundle,
    stream: C8DynamicStream | None,
) -> China81Bundle:
    """Overlay the five added customers; existing-customer changes are staged later."""

    if stream is None:
        return bundle
    source_paths = {
        **dict(bundle.source_paths),
        "dynamic_events": str(stream.stream_directory / "events.tsv"),
    }
    return replace(
        bundle,
        instance=_expanded_instance(bundle, stream.events),
        source_paths=MappingProxyType(source_paths),
    )


def subset_c8_bundle(
    bundle: China81Bundle,
    active_customer_ids: Iterable[str],
    events: Sequence[C8DynamicEvent] = (),
) -> China81Bundle:
    """Build one stage bundle after applying every event revealed so far."""

    active = set(map(str, active_customer_ids))
    nodes = dict(bundle.instance.node_lookup)
    for event in events:
        node = nodes[event.customer_id]
        if event.event_type == "demand_change":
            nodes[event.customer_id] = replace(node, demand=event.new_demand_kg)
        elif event.event_type == "time_window_change":
            nodes[event.customer_id] = replace(
                node,
                ready_time=event.new_ready_second,
                due_time=event.new_due_second,
            )
    instance = rebuild_instance_matrix(
        bundle.instance,
        [
            nodes[node.node_id]
            for node in bundle.instance.nodes
            if node.node_type.lower() in {"d", "f"} or node.node_id in active
        ],
    )
    home = {
        customer_id: bundle.customer_home_depot[customer_id]
        for customer_id in active
        if customer_id in bundle.customer_home_depot
    }
    return replace(
        bundle,
        instance=instance,
        customer_home_depot=MappingProxyType(home),
    )


def extend_route_contract(
    contract: Any,
    stream: C8DynamicStream,
    active_customer_ids: Iterable[str],
) -> Any:
    """Give added customers the shift and volume of their paper source row."""

    active = set(map(str, active_customer_ids))
    shifts = dict(contract.customer_shift_by_id)
    volumes = dict(contract.customer_volume_m3_by_id)
    for event in stream.events:
        if event.event_type != "add" or event.customer_id not in active:
            continue
        shifts[event.customer_id] = shifts[event.source_customer_id]
        volumes[event.customer_id] = volumes[event.source_customer_id]
    # A rolling stage carries only customers that still need service; the
    # stage bundle drops the rest, and the context validator requires the
    # contract's customer set to match the stage bundle exactly.
    shifts = {cid: value for cid, value in shifts.items() if cid in active}
    volumes = {cid: value for cid, value in volumes.items() if cid in active}
    return replace(
        contract,
        source_id=f"{contract.source_id}+paper-mixed-events",
        customer_shift_by_id=MappingProxyType(shifts),
        customer_volume_m3_by_id=MappingProxyType(volumes),
    )


def served_customer_ids(
    solution: Solution,
    bundle: China81Bundle,
) -> frozenset[str]:
    customers = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    return frozenset(
        node_id
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customers
    )
