"""C8-1 independent dynamic-order stream and in-memory adapter.

The stream in this module is deliberately outside the frozen China81 instance
package.  A generated customer is represented in the runtime only by copying
the directed CV/EV matrix row and column of a registered target customer.  The
proxy identity is recorded in the stream, so the construction cannot be
mistaken for a new observed road-network measurement.

This module does not change an instance file and does not run a search.  It
contains only the reproducible stream contract, the protocol trigger rule,
the serviceability audit, and the in-memory bundle overlay used by the C8
minimum wiring trial.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node, RoadProfileMatrices
from setp_solver.instance_subset import rebuild_instance_matrix
from setp_solver.solution import Solution


C8_STREAM_SCHEMA = "resetp.c8-independent-dynamic-stream.v1"
C8_BASE_INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
C8_PROTOCOL_ID = "QIU_P59_RECEPTION_0800_1000_Q500_T30_TRANSFER"
C8_RECEPTION_START_SECOND = 8 * 60 * 60
C8_RECEPTION_END_SECOND = 10 * 60 * 60
C8_TRIGGER_INTERVAL_SECOND = 30 * 60
C8_TRIGGER_DEMAND_THRESHOLD_KG = 500.0
C8_DYNAMIC_ORDER_COUNT = 10
C8_STATIC_CUSTOMER_COUNT = 50
_TOL = 1.0e-9


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_file_hashes(package_dir: Path) -> dict[str, str]:
    """Hash every file in a source instance without modifying it."""

    package_dir = package_dir.resolve()
    if not package_dir.is_dir():
        raise FileNotFoundError(package_dir)
    paths = sorted(
        path
        for path in package_dir.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    return {
        str(path.relative_to(package_dir)).replace("\\", "/"): _sha256_file(path)
        for path in paths
    }


def package_content_sha256(file_hashes: Mapping[str, str]) -> str:
    return _sha256_bytes(
        _canonical_bytes([[name, file_hashes[name]] for name in sorted(file_hashes)])
    )


@dataclass(frozen=True)
class C8Protocol:
    """The user-approved transferred Qiu protocol."""

    protocol_id: str = C8_PROTOCOL_ID
    reception_start_second: float = C8_RECEPTION_START_SECOND
    reception_end_second: float = C8_RECEPTION_END_SECOND
    trigger_interval_second: float = C8_TRIGGER_INTERVAL_SECOND
    trigger_demand_threshold_kg: float = C8_TRIGGER_DEMAND_THRESHOLD_KG
    event_types: tuple[str, ...] = (
        "new_customer",
        "cancel_delivery",
        "demand_reduction",
    )
    transfer_note: str = (
        "Qiu Yingying thesis p.59 table 5.6: reception starts 08:00; "
        "08:00-10:00 window; 500 kg or 30 minutes first; event enum "
        "new customer/cancel delivery/demand reduction. The thresholds are "
        "a protocol transfer, not a local calibration."
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_types", tuple(self.event_types))


@dataclass(frozen=True)
class C8DynamicEvent:
    """One independent dynamic order event."""

    event_id: str
    customer_id: str
    event_type: str
    appearance_second: float
    demand_kg: float
    volume_m3: float
    service_minutes: float
    ready_second: float
    due_second: float
    shift_id: str
    home_depot_id: str
    city: str
    latitude: float
    longitude: float
    coordinate_proxy_customer_id: str
    demand_source_customer_id: str
    source_distribution: str
    trigger_batch_index: int
    trigger_second: float
    trigger_cause: str
    direct_travel_second: float
    direct_return_second: float
    reveal_serviceable: bool
    trigger_serviceable: bool
    serviceability_reason: str

    def __post_init__(self) -> None:
        if self.event_type not in C8Protocol().event_types:
            raise ValueError(f"unsupported C8 event type: {self.event_type}")
        if not str(self.event_id) or not str(self.customer_id):
            raise ValueError("C8 event and customer ids cannot be empty")
        if not (
            C8_RECEPTION_START_SECOND
            <= float(self.appearance_second)
            < C8_RECEPTION_END_SECOND
        ):
            raise ValueError("C8 appearance is outside the reception window")
        if float(self.demand_kg) <= 0.0 or float(self.volume_m3) < 0.0:
            raise ValueError("C8 demand and volume are invalid")
        if float(self.due_second) < float(self.ready_second):
            raise ValueError("C8 time window is inverted")


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
    """Loaded or generated stream plus its immutable source identity."""

    base_instance_id: str
    source_instance_sha256: str
    stream_content_sha256: str
    seed: int
    seed_mode: str
    generation_attempt: int
    protocol: C8Protocol
    events: tuple[C8DynamicEvent, ...]
    source_instance_file_hashes: Mapping[str, str]
    stream_directory: Path | None = None

    def __post_init__(self) -> None:
        if self.base_instance_id != C8_BASE_INSTANCE_ID:
            raise ValueError(
                "C8-1 accepts only the selected unified DEPOTSEARCH instance"
            )
        if "GZ-FS" in self.base_instance_id or "china81_finite_fleet_authority" in self.base_instance_id:
            raise ValueError("retired GZ-FS or finite-fleet stream identity is forbidden")
        if len(self.events) != C8_DYNAMIC_ORDER_COUNT:
            raise ValueError("C8-1 requires exactly ten dynamic events")
        customer_ids = [event.customer_id for event in self.events]
        event_ids = [event.event_id for event in self.events]
        if len(set(customer_ids)) != len(customer_ids):
            raise ValueError("C8 dynamic customer ids must be unique")
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("C8 event ids must be unique")
        if not self.stream_content_sha256 or len(self.stream_content_sha256) != 64:
            raise ValueError("C8 stream content identity must be SHA-256")

    @property
    def dynamic_customer_ids(self) -> frozenset[str]:
        return frozenset(event.customer_id for event in self.events)

    @property
    def trigger_batches(self) -> tuple[C8TriggerBatch, ...]:
        grouped: dict[int, list[C8DynamicEvent]] = {}
        for event in self.events:
            grouped.setdefault(int(event.trigger_batch_index), []).append(event)
        return tuple(
            C8TriggerBatch(
                batch_index=index,
                trigger_second=float(events[0].trigger_second),
                cause=str(events[0].trigger_cause),
                event_ids=tuple(event.event_id for event in events),
                customer_ids=tuple(event.customer_id for event in events),
                demand_kg=sum(float(event.demand_kg) for event in events),
            )
            for index, events in sorted(grouped.items())
        )


def _trigger_batches(
    events: Sequence[C8DynamicEvent],
    protocol: C8Protocol,
) -> tuple[C8TriggerBatch, ...]:
    """Apply q=500 kg or T=30 min, whichever comes first."""

    ordered = sorted(
        events,
        key=lambda event: (float(event.appearance_second), str(event.event_id)),
    )
    pending: list[C8DynamicEvent] = []
    batches: list[C8TriggerBatch] = []
    cursor = 0
    deadline = (
        float(protocol.reception_start_second)
        + float(protocol.trigger_interval_second)
    )
    while cursor < len(ordered):
        appearance = float(ordered[cursor].appearance_second)
        while deadline < appearance - _TOL:
            if pending:
                batches.append(
                    C8TriggerBatch(
                        batch_index=len(batches) + 1,
                        trigger_second=deadline,
                        cause="maximum_wait",
                        event_ids=tuple(event.event_id for event in pending),
                        customer_ids=tuple(event.customer_id for event in pending),
                        demand_kg=sum(float(event.demand_kg) for event in pending),
                    )
                )
                pending = []
            deadline = min(
                deadline + float(protocol.trigger_interval_second),
                float(protocol.reception_end_second),
            )
        while cursor < len(ordered) and abs(
            float(ordered[cursor].appearance_second) - appearance
        ) <= _TOL:
            pending.append(ordered[cursor])
            cursor += 1
        if sum(float(event.demand_kg) for event in pending) >= float(
            protocol.trigger_demand_threshold_kg
        ) - _TOL:
            batches.append(
                C8TriggerBatch(
                    batch_index=len(batches) + 1,
                    trigger_second=appearance,
                    cause="demand_threshold",
                    event_ids=tuple(event.event_id for event in pending),
                    customer_ids=tuple(event.customer_id for event in pending),
                    demand_kg=sum(float(event.demand_kg) for event in pending),
                )
            )
            pending = []
            deadline = min(
                appearance + float(protocol.trigger_interval_second),
                float(protocol.reception_end_second),
            )
        elif abs(appearance - deadline) <= _TOL:
            batches.append(
                C8TriggerBatch(
                    batch_index=len(batches) + 1,
                    trigger_second=deadline,
                    cause="maximum_wait",
                    event_ids=tuple(event.event_id for event in pending),
                    customer_ids=tuple(event.customer_id for event in pending),
                    demand_kg=sum(float(event.demand_kg) for event in pending),
                )
            )
            pending = []
            deadline = min(
                deadline + float(protocol.trigger_interval_second),
                float(protocol.reception_end_second),
            )
    if pending:
        trigger = min(deadline, float(protocol.reception_end_second))
        batches.append(
            C8TriggerBatch(
                batch_index=len(batches) + 1,
                trigger_second=trigger,
                cause=("window_end" if trigger == protocol.reception_end_second else "maximum_wait"),
                event_ids=tuple(event.event_id for event in pending),
                customer_ids=tuple(event.customer_id for event in pending),
                demand_kg=sum(float(event.demand_kg) for event in pending),
            )
        )
    consumed = [event_id for batch in batches for event_id in batch.event_ids]
    if sorted(consumed) != sorted(event.event_id for event in ordered):
        raise ValueError("C8 trigger rule did not consume every event once")
    return tuple(batches)


def _source_seed(source_instance_sha256: str) -> int:
    # The vendored HGS RNG accepts a signed native integer.  Eight hex digits
    # keep the derived seed deterministic while staying inside that ABI.
    return int(source_instance_sha256[:8], 16)


def _pm_rows(order_rows: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    rows = [
        {str(key): str(value) for key, value in row.items()}
        for row in order_rows
        if str(row.get("shift_id", "")).strip().upper() == "PM"
    ]
    rows.sort(key=lambda row: str(row["customer_id"]))
    if len(rows) < C8_DYNAMIC_ORDER_COUNT:
        raise ValueError("unified target has fewer than ten PM distribution rows")
    return rows


def _direct_serviceability(
    *,
    bundle: China81Bundle,
    home_depot_id: str,
    proxy_customer_id: str,
    appearance_second: float,
    trigger_second: float,
    ready_second: float,
    due_second: float,
    service_second: float,
    demand_kg: float,
    volume_m3: float,
) -> tuple[bool, bool, float, float, str]:
    distance, direct, _ = bundle.instance.arc_metrics(
        home_depot_id,
        proxy_customer_id,
        "cv",
        fallback_speed_mps=1.0,
    )
    _ = distance
    back = bundle.instance.arc_metrics(
        proxy_customer_id,
        home_depot_id,
        "cv",
        fallback_speed_mps=1.0,
    )[1]
    depot = next(
        node for node in bundle.instance.nodes if node.node_id == home_depot_id
    )
    reasons: list[str] = []
    payload = 1_735.0
    if bundle.instance.vehicle_parameters is not None:
        payload = float(
            bundle.instance.vehicle_parameters["cv"].payload_capacity_kg
        )
    reveal_arrival = float(appearance_second) + float(direct)
    trigger_arrival = float(trigger_second) + float(direct)
    reveal_start = max(reveal_arrival, float(ready_second))
    trigger_start = max(trigger_arrival, float(ready_second))
    reveal_return = reveal_start + float(service_second) + float(back)
    trigger_return = trigger_start + float(service_second) + float(back)
    capacity_pass = float(demand_kg) <= payload + _TOL and float(volume_m3) <= 7.2 + _TOL
    if not capacity_pass:
        reasons.append("capacity_exceeds_cv_contract")
    reveal_pass = (
        capacity_pass
        and reveal_start <= float(due_second) + _TOL
        and reveal_return <= float(depot.due_time) + _TOL
    )
    trigger_pass = (
        capacity_pass
        and trigger_start <= float(due_second) + _TOL
        and trigger_return <= float(depot.due_time) + _TOL
    )
    if not reveal_pass:
        reasons.append("not_reveal_serviceable")
    if not trigger_pass:
        reasons.append("not_trigger_serviceable")
    return (
        bool(reveal_pass),
        bool(trigger_pass),
        float(direct),
        float(back),
        "PASS" if not reasons else ";".join(reasons),
    )


def c8_generation_rules(protocol: C8Protocol = C8Protocol()) -> dict[str, Any]:
    """Return the rules recorded in both the stream and its report."""

    return {
        "coordinate_rule": (
            "sample ten distinct PM customer coordinate rows from the unified "
            "target orders.csv, keyed by coordinate_proxy_customer_id"
        ),
        "demand_rule": (
            "sample ten PM demand/volume rows independently with replacement "
            "from the same unified target orders.csv"
        ),
        "time_window_rule": (
            "copy PM shift, window, service time and home depot from the sampled "
            "coordinate row; no old GZ-FS stream is read"
        ),
        "matrix_rule": (
            "copy the unified target directed CV/EV matrix row and column of the "
            "coordinate proxy in memory only"
        ),
        "serviceability_rule": (
            "reject deterministic candidate attempts only when direct CV service "
            "after the trigger is outside the time/capacity contract; no objective "
            "or search result is inspected"
        ),
        "dynamic_order_count": C8_DYNAMIC_ORDER_COUNT,
        "static_customer_count": C8_STATIC_CUSTOMER_COUNT,
        "doD": "10/50=0.20, as approved in P10",
        "protocol_transfer": protocol.transfer_note,
    }


def generate_c8_stream(
    *,
    bundle: China81Bundle,
    order_rows: Sequence[Mapping[str, str]],
    source_instance_dir: Path,
    seed: int | None = None,
    dynamic_order_count: int = C8_DYNAMIC_ORDER_COUNT,
    protocol: C8Protocol = C8Protocol(),
) -> C8DynamicStream:
    """Generate ten independent events from the selected target distribution.

    Coordinates are sampled without replacement from the target's PM customer
    coordinates.  demand/volume are sampled independently with replacement
    from the same target PM empirical rows.  The deterministic attempt loop
    rejects only direct-serviceability failures; it never observes cost or
    search output.
    """

    if bundle.instance_id != C8_BASE_INSTANCE_ID:
        raise ValueError("C8 generator source is not the selected unified instance")
    if dynamic_order_count != C8_DYNAMIC_ORDER_COUNT:
        raise ValueError("C8-1 fixes the dynamic order count at ten")
    source_file_hashes = package_file_hashes(source_instance_dir)
    source_hash = package_content_sha256(source_file_hashes)
    actual_seed = _source_seed(source_hash) if seed is None else int(seed)
    seed_mode = "derived_from_source_instance_sha256" if seed is None else "explicit_cli_seed"
    pm = _pm_rows(order_rows)
    base_node_ids = {node.node_id for node in bundle.instance.nodes}
    for row in pm:
        if row["customer_id"] not in base_node_ids:
            raise ValueError(f"order row is not in the unified bundle: {row['customer_id']}")

    selected: tuple[list[dict[str, str]], list[dict[str, str]], int, list[C8DynamicEvent]] | None = None
    for attempt in range(64):
        rng = random.Random(actual_seed + attempt)
        coordinate_rows = rng.sample(pm, dynamic_order_count)
        demand_rows = [rng.choice(pm) for _ in range(dynamic_order_count)]
        draft: list[C8DynamicEvent] = []
        for index, (coordinate_row, demand_row) in enumerate(
            zip(coordinate_rows, demand_rows, strict=True),
            start=1,
        ):
            appearance = float(
                protocol.reception_start_second
                + rng.randrange(
                    int(protocol.reception_end_second - protocol.reception_start_second)
                )
            )
            customer_id = f"C8_D{index:03d}"
            event_id = f"C8_ADD_{index:03d}"
            home = str(coordinate_row["home_depot_id"])
            ready = float(coordinate_row["time_window_early_minute"]) * 60.0
            due = float(coordinate_row["time_window_late_minute"]) * 60.0
            service_minutes = float(coordinate_row["service_minutes"])
            demand = float(demand_row["demand_kg"])
            volume = float(demand_row["source_volume_m3"])
            reveal_pass, trigger_pass, direct, back, reason = _direct_serviceability(
                bundle=bundle,
                home_depot_id=home,
                proxy_customer_id=str(coordinate_row["customer_id"]),
                appearance_second=appearance,
                trigger_second=protocol.reception_end_second,
                ready_second=ready,
                due_second=due,
                service_second=service_minutes * 60.0,
                demand_kg=demand,
                volume_m3=volume,
            )
            draft.append(
                C8DynamicEvent(
                    event_id=event_id,
                    customer_id=customer_id,
                    event_type="new_customer",
                    appearance_second=appearance,
                    demand_kg=demand,
                    volume_m3=volume,
                    service_minutes=service_minutes,
                    ready_second=ready,
                    due_second=due,
                    shift_id=str(coordinate_row["shift_id"]),
                    home_depot_id=home,
                    city=str(coordinate_row["city"]).lower(),
                    latitude=float(coordinate_row["latitude"]),
                    longitude=float(coordinate_row["longitude"]),
                    coordinate_proxy_customer_id=str(coordinate_row["customer_id"]),
                    demand_source_customer_id=str(demand_row["customer_id"]),
                    source_distribution=(
                        f"{C8_BASE_INSTANCE_ID}:PM_empirical_bootstrap"
                    ),
                    trigger_batch_index=0,
                    trigger_second=0.0,
                    trigger_cause="",
                    direct_travel_second=direct,
                    direct_return_second=back,
                    reveal_serviceable=reveal_pass,
                    trigger_serviceable=trigger_pass,
                    serviceability_reason=reason,
                )
            )
        batches = _trigger_batches(draft, protocol)
        batch_by_event = {
            event_id: batch
            for batch in batches
            for event_id in batch.event_ids
        }
        finalized = tuple(
            replace(
                event,
                trigger_batch_index=batch_by_event[event.event_id].batch_index,
                trigger_second=batch_by_event[event.event_id].trigger_second,
                trigger_cause=batch_by_event[event.event_id].cause,
            )
            for event in sorted(draft, key=lambda item: item.event_id)
        )
        trigger_ok = all(event.trigger_serviceable for event in finalized)
        if trigger_ok:
            selected = (coordinate_rows, demand_rows, attempt, list(finalized))
            break
        if selected is None:
            selected = (coordinate_rows, demand_rows, attempt, list(finalized))
    assert selected is not None
    _, _, attempt, events = selected
    event_payload = [asdict(event) for event in events]
    rules = c8_generation_rules(protocol)
    content_payload = {
        "schema": C8_STREAM_SCHEMA,
        "base_instance_id": bundle.instance_id,
        "source_instance_sha256": source_hash,
        "seed": actual_seed,
        "seed_mode": seed_mode,
        "generation_attempt": attempt,
        "protocol": asdict(protocol),
        "rules": rules,
        "events": event_payload,
    }
    content_hash = _sha256_bytes(_canonical_bytes(content_payload))
    return C8DynamicStream(
        base_instance_id=bundle.instance_id,
        source_instance_sha256=source_hash,
        stream_content_sha256=content_hash,
        seed=actual_seed,
        seed_mode=seed_mode,
        generation_attempt=attempt,
        protocol=protocol,
        events=tuple(events),
        source_instance_file_hashes=MappingProxyType(dict(source_file_hashes)),
    )


def _event_csv_fields() -> tuple[str, ...]:
    return (
        "event_id",
        "customer_id",
        "event_type",
        "appearance_second",
        "demand_kg",
        "volume_m3",
        "service_minutes",
        "ready_second",
        "due_second",
        "shift_id",
        "home_depot_id",
        "city",
        "latitude",
        "longitude",
        "coordinate_proxy_customer_id",
        "demand_source_customer_id",
        "source_distribution",
        "trigger_batch_index",
        "trigger_second",
        "trigger_cause",
        "direct_travel_second",
        "direct_return_second",
        "reveal_serviceable",
        "trigger_serviceable",
        "serviceability_reason",
    )


def _metadata(stream: C8DynamicStream, rules: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": C8_STREAM_SCHEMA,
        "base_instance_id": stream.base_instance_id,
        "source_instance_sha256": stream.source_instance_sha256,
        "source_instance_file_hashes": dict(stream.source_instance_file_hashes),
        "stream_content_sha256": stream.stream_content_sha256,
        "seed": stream.seed,
        "seed_mode": stream.seed_mode,
        "generation_attempt": stream.generation_attempt,
        "protocol": asdict(stream.protocol),
        "supported_event_types": list(stream.protocol.event_types),
        "generated_event_type_counts": {
            event_type: sum(event.event_type == event_type for event in stream.events)
            for event_type in stream.protocol.event_types
        },
        "static_customer_count": C8_STATIC_CUSTOMER_COUNT,
        "dynamic_customer_count": len(stream.events),
        "dynamic_share": len(stream.events) / C8_STATIC_CUSTOMER_COUNT,
        "rules": dict(rules),
        "trigger_batches": [asdict(batch) for batch in stream.trigger_batches],
    }


def write_c8_stream(
    stream: C8DynamicStream,
    output_dir: Path,
    *,
    generator_source: Path,
    rules: Mapping[str, Any],
) -> Path:
    """Write a self-contained independent stream directory."""

    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    event_rows = [asdict(event) for event in stream.events]
    events_path = output_dir / "events.csv"
    with events_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_event_csv_fields())
        writer.writeheader()
        writer.writerows(event_rows)
    serviceability_path = output_dir / "serviceability_check.csv"
    service_fields = (
        "event_id",
        "customer_id",
        "appearance_second",
        "trigger_batch_index",
        "trigger_second",
        "due_second",
        "direct_travel_second",
        "direct_return_second",
        "reveal_serviceable",
        "trigger_serviceable",
        "serviceability_reason",
    )
    with serviceability_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=service_fields)
        writer.writeheader()
        writer.writerows(
            {
                key: row[key]
                for key in service_fields
            }
            for row in event_rows
        )
    (output_dir / "generation_rules.json").write_text(
        json.dumps(dict(rules), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(generator_source, output_dir / generator_source.name)
    (output_dir / "metadata.json").write_text(
        json.dumps(_metadata(stream, rules), ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    artifact_hashes = {
        path.name: _sha256_file(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps(artifact_hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_dir


def _event_from_row(row: Mapping[str, str]) -> C8DynamicEvent:
    boolean = lambda value: str(value).strip().lower() in {"1", "true", "yes"}
    integer_fields = {"trigger_batch_index"}
    float_fields = {
        "appearance_second",
        "demand_kg",
        "volume_m3",
        "service_minutes",
        "ready_second",
        "due_second",
        "latitude",
        "longitude",
        "trigger_second",
        "direct_travel_second",
        "direct_return_second",
    }
    payload: dict[str, Any] = dict(row)
    for key in integer_fields:
        payload[key] = int(row[key])
    for key in float_fields:
        payload[key] = float(row[key])
    for key in ("reveal_serviceable", "trigger_serviceable"):
        payload[key] = boolean(row[key])
    return C8DynamicEvent(**payload)


def load_c8_stream(path: Path, *, expected_base_instance_id: str = C8_BASE_INSTANCE_ID) -> C8DynamicStream:
    path = path.resolve()
    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("base_instance_id") != expected_base_instance_id:
        raise ValueError("C8 stream base_instance_id is not the unified target")
    if "GZ-FS" in str(metadata.get("base_instance_id", "")):
        raise ValueError("retired GZ-FS stream is forbidden")
    with (path / "events.csv").open(newline="", encoding="utf-8") as handle:
        events = tuple(_event_from_row(row) for row in csv.DictReader(handle))
    protocol = C8Protocol(**metadata["protocol"])
    source_hashes = MappingProxyType(dict(metadata["source_instance_file_hashes"]))
    event_payload = [asdict(event) for event in events]
    content_payload = {
        "schema": metadata["schema"],
        "base_instance_id": metadata["base_instance_id"],
        "source_instance_sha256": metadata["source_instance_sha256"],
        "seed": int(metadata["seed"]),
        "seed_mode": metadata["seed_mode"],
        "generation_attempt": int(metadata["generation_attempt"]),
        "protocol": asdict(protocol),
        "rules": metadata["rules"],
        "events": event_payload,
    }
    actual_content_hash = _sha256_bytes(_canonical_bytes(content_payload))
    if actual_content_hash != metadata["stream_content_sha256"]:
        raise ValueError("C8 stream content hash does not match events/metadata")
    stream = C8DynamicStream(
        base_instance_id=str(metadata["base_instance_id"]),
        source_instance_sha256=str(metadata["source_instance_sha256"]),
        stream_content_sha256=str(metadata["stream_content_sha256"]),
        seed=int(metadata["seed"]),
        seed_mode=str(metadata["seed_mode"]),
        generation_attempt=int(metadata["generation_attempt"]),
        protocol=protocol,
        events=events,
        source_instance_file_hashes=source_hashes,
        stream_directory=path,
    )
    expected_batches = json.loads(
        _canonical_bytes([asdict(batch) for batch in stream.trigger_batches])
    )
    recorded_batches = json.loads(
        _canonical_bytes(metadata.get("trigger_batches", []))
    )
    if expected_batches != recorded_batches:
        raise ValueError("C8 stream trigger batch record is inconsistent")
    return stream


def _expanded_instance(bundle: China81Bundle, events: Sequence[C8DynamicEvent]) -> Instance:
    base = bundle.instance
    base_ids = set(base.node_index)
    if base_ids.intersection(event.customer_id for event in events):
        raise ValueError("C8 dynamic customer id collides with unified instance")
    proxy_ids = [event.coordinate_proxy_customer_id for event in events]
    if any(proxy_id not in base_ids for proxy_id in proxy_ids):
        raise ValueError("C8 coordinate proxy is absent from the unified instance")
    nodes = list(base.nodes)
    for event in events:
        proxy = base.nodes[base.node_index[event.coordinate_proxy_customer_id]]
        nodes.append(
            Node(
                node_id=event.customer_id,
                node_type="c",
                x=float(event.longitude),
                y=float(event.latitude),
                demand=float(event.demand_kg),
                ready_time=float(event.ready_second),
                due_time=float(event.due_second),
                service_time=float(event.service_minutes) * 60.0,
                city=event.city or proxy.city,
            )
        )
    dynamic_proxy_index = {
        event.customer_id: base.node_index[event.coordinate_proxy_customer_id]
        for event in events
    }
    source_indices = [
        base.node_index[node.node_id]
        if node.node_id in base.node_index
        else dynamic_proxy_index[node.node_id]
        for node in nodes
    ]
    matrix = [
        [float(base.distance_matrix[left][right]) for right in source_indices]
        for left in source_indices
    ]
    profiles = None
    if base.road_profiles is not None:
        profiles = {
            profile: RoadProfileMatrices(
                distance_m=tuple(
                    tuple(float(matrices.distance_m[left][right]) for right in source_indices)
                    for left in source_indices
                ),
                duration_s=tuple(
                    tuple(float(matrices.duration_s[left][right]) for right in source_indices)
                    for left in source_indices
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(float(matrices.sum_v2d_m3_s2[left][right]) for right in source_indices)
                    for left in source_indices
                ),
            )
            for profile, matrices in base.road_profiles.items()
        }
    return Instance(
        nodes=nodes,
        distance_matrix=matrix,
        diesel_l_per_meter=base.diesel_l_per_meter,
        ev_kwh_per_meter=base.ev_kwh_per_meter,
        unit_distance_cost_per_meter=base.unit_distance_cost_per_meter,
        num_cv=base.num_cv,
        num_ev=base.num_ev,
        road_profiles=profiles,
        vehicle_parameters=base.vehicle_parameters,
        demand_mass_per_unit_kg=base.demand_mass_per_unit_kg,
    )


def overlay_c8_bundle(bundle: China81Bundle, stream: C8DynamicStream | None) -> China81Bundle:
    """Return the unchanged bundle for ``None``; otherwise overlay in memory."""

    if stream is None:
        return bundle
    if bundle.instance_id != stream.base_instance_id:
        raise ValueError("C8 stream and runtime bundle instance ids disagree")
    instance = _expanded_instance(bundle, stream.events)
    home = dict(bundle.customer_home_depot)
    owners = dict(bundle.enterprise_assignment_by_customer)
    for event in stream.events:
        home[event.customer_id] = event.home_depot_id
        if event.coordinate_proxy_customer_id in owners:
            owners[event.customer_id] = owners[event.coordinate_proxy_customer_id]
    source_paths = {
        **dict(bundle.source_paths),
        "c8_dynamic_stream": str(stream.stream_directory or "<in-memory-c8-stream>"),
        "c8_dynamic_stream_content_sha256": stream.stream_content_sha256,
    }
    return replace(
        bundle,
        instance=instance,
        source_paths=MappingProxyType(source_paths),
        customer_home_depot=MappingProxyType(home),
        enterprise_assignment_by_customer=MappingProxyType(owners),
        enterprise_assignment_mapping_sha256=_sha256_bytes(
            _canonical_bytes([[key, owners[key]] for key in sorted(owners)])
        ),
    )


def subset_c8_bundle(bundle: China81Bundle, active_customer_ids: Iterable[str]) -> China81Bundle:
    active = {str(customer_id) for customer_id in active_customer_ids}
    all_customers = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    if not active.issubset(all_customers):
        raise ValueError("C8 active customer set contains an unknown customer")
    instance = rebuild_instance_matrix(
        bundle.instance,
        [
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() in {"d", "f"}
            or node.node_id in active
        ],
    )
    home = {
        customer_id: bundle.customer_home_depot[customer_id]
        for customer_id in active
    }
    owners = {
        customer_id: bundle.enterprise_assignment_by_customer[customer_id]
        for customer_id in active
        if customer_id in bundle.enterprise_assignment_by_customer
    }
    return replace(
        bundle,
        instance=instance,
        customer_home_depot=MappingProxyType(home),
        enterprise_assignment_by_customer=MappingProxyType(owners),
    )


def extend_route_contract(contract: Any, stream: C8DynamicStream, active_customer_ids: Iterable[str]) -> Any:
    """Add dynamic shift/volume rows to the existing in-memory contract."""

    active = {str(customer_id) for customer_id in active_customer_ids}
    shifts = dict(contract.customer_shift_by_id)
    volumes = dict(contract.customer_volume_m3_by_id)
    for event in stream.events:
        if event.customer_id in active:
            shifts[event.customer_id] = event.shift_id
            volumes[event.customer_id] = float(event.volume_m3)
    return replace(
        contract,
        source_id=(
            f"{contract.source_id}+C8_STREAM_{stream.stream_content_sha256[:16]}"
        ),
        customer_shift_by_id=MappingProxyType(shifts),
        customer_volume_m3_by_id=MappingProxyType(volumes),
    )


def served_customer_ids(solution: Solution, bundle: China81Bundle) -> frozenset[str]:
    customer_ids = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    return frozenset(
        node_id
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    )


def event_payload_sha256(event: C8DynamicEvent) -> str:
    return _sha256_bytes(_canonical_bytes(asdict(event)))
