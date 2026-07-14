#!/usr/bin/env python3
"""Read-only E7 value comparison based on reconstructed full-day service ledgers.

The script deliberately does not trust the already-computed paired cost percentage.
For each stream and arm it rebuilds the served-customer ledger from the frozen
initial instance, recorded event dispositions, cumulative locked routes, and the
final future plan.  A direct cost percentage is emitted only when the two arms
served exactly the same workload and both cost ledgers close.

This audit is intentionally independent of the formal runner.  It uses only the
Python standard library and never writes into the input run directory.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
from typing import Any, Iterable, Mapping, Sequence


REVENUE_PER_KG = Decimal("0.18936")
EXPECTED_ARMS = ("cooperative", "independent")
EXPECTED_STREAMS = (1, 2, 3, 4, 5)
EXPECTED_EVENTS_PER_STREAM = 55
FORMAL_RUN_RELATIVE_PATH = Path(
    "baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix"
)
FORMAL_CONTRACT_ID = "E7_PAIRED_DYNAMIC_VALUE_V4_UNIQUE_EVENT_ROUTE_IDS"
FROZEN_INSTANCE_RELATIVE_PATH = Path(
    "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets/"
    "L-main-threeshift-100c-01/bundle/instance.json"
)
FROZEN_INSTANCE_SHA256 = (
    "59696be304ad9f3c484820439e1cbdb027945e20ad7ecbdb8542dfde7e0d6225"
)
FROZEN_PRICE_RELATIVE_PATH = Path("solver/src/setp_solver/prices.py")
EVENT_ROOT_RELATIVE_PATH = Path(
    "baselines/e7_dynamic/e7_v2_20260714/event_streams"
)
EVENT_MANIFEST_RELATIVE_PATH = EVENT_ROOT_RELATIVE_PATH / "manifest.json"
E6_INITIAL_CASE = "L-main-threeshift-100c-01__geographic__seed1__independent"
E6_INITIAL_ROOT_RELATIVE_PATH = Path(
    "baselines/e6_fairness/e6_participation_formal_20260714"
)
TOLERANCE = Decimal("0.000001")
COST_COMPONENTS = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
)


class EvidenceError(RuntimeError):
    """Raised when frozen evidence cannot support a defensible comparison."""


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise EvidenceError(f"{label} is not a finite decimal: {value!r}") from exc


def _close(left: Decimal, right: Decimal, tolerance: Decimal = TOLERANCE) -> bool:
    scale = max(Decimal("1"), abs(left), abs(right))
    return abs(left - right) <= tolerance * scale


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def current_git_commit(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise EvidenceError("cannot read the audit source commit") from exc


def validate_audit_source(repo_root: Path) -> dict[str, dict[str, str]]:
    commit = current_git_commit(repo_root)
    paths = (
        Path(__file__).resolve(),
        (Path(__file__).resolve().parent / "validate_e7_records_independent_20260714.py").resolve(),
    )
    evidence: dict[str, dict[str, str]] = {}
    for path in paths:
        relative = _relative_to(path, repo_root, "audit source")
        if not path.is_file():
            raise EvidenceError(f"audit source is missing: {relative}")
        working_hash = file_sha256(path)
        committed_hash = bytes_sha256(_git_blob(repo_root, commit, relative))
        if working_hash != committed_hash:
            raise EvidenceError(
                f"audit source differs from HEAD and cannot produce formal evidence: {relative}"
            )
        evidence[relative.as_posix()] = {
            "commit": commit,
            "sha256": working_hash,
        }
    return evidence


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _relative_to(path: Path, root: Path, label: str) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise EvidenceError(f"{label} escapes the repository: {path}") from exc


def _git_blob(repo_root: Path, commit: str, relative_path: Path) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EvidenceError(f"run source commit is not a full SHA-1: {commit!r}")
    try:
        object_type = subprocess.check_output(
            ["git", "cat-file", "-t", commit],
            cwd=repo_root,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
        if object_type != "commit":
            raise EvidenceError(f"run source object is not a commit: {commit}")
        return subprocess.check_output(
            ["git", "show", f"{commit}:{relative_path.as_posix()}"],
            cwd=repo_root,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        if isinstance(exc.stderr, bytes):
            detail = exc.stderr.decode("utf-8", errors="replace")
        else:
            detail = str(exc.stderr or "")
        raise EvidenceError(
            f"cannot read {relative_path.as_posix()} from run commit {commit}: {detail.strip()}"
        ) from exc


def _single_numeric_assignment(source: str, variable: str) -> Decimal:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise EvidenceError("frozen prices.py cannot be parsed") from exc
    values: list[Decimal] = []
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if not any(isinstance(target, ast.Name) and target.id == variable for target in targets):
            continue
        value = statement.value
        if not isinstance(value, ast.Constant) or isinstance(value.value, bool) or not isinstance(
            value.value, (int, float)
        ):
            raise EvidenceError(f"{variable} in frozen prices.py is not a numeric literal")
        segment = ast.get_source_segment(source, value)
        if segment is None:
            raise EvidenceError(f"cannot recover the literal for {variable} in frozen prices.py")
        values.append(_decimal(segment, f"frozen prices.py {variable}"))
    if len(values) != 1:
        raise EvidenceError(
            f"frozen prices.py must assign {variable} exactly once, found {len(values)}"
        )
    return values[0]


def validate_revenue_source(
    repo_root: Path, metadata: Mapping[str, Any]
) -> dict[str, str]:
    source_commit = str(metadata.get("source_commit", ""))
    if str(metadata.get("run_start_commit", "")) != source_commit:
        raise EvidenceError("source_commit and run_start_commit differ")
    blob = _git_blob(repo_root, source_commit, FROZEN_PRICE_RELATIVE_PATH)
    value = _single_numeric_assignment(blob.decode("utf-8"), "revenue_per_kg")
    if value != REVENUE_PER_KG:
        raise EvidenceError(
            f"run-commit revenue_per_kg is {value}, expected {REVENUE_PER_KG}"
        )
    return {
        "path": FROZEN_PRICE_RELATIVE_PATH.as_posix(),
        "commit": source_commit,
        "sha256": bytes_sha256(blob),
        "revenue_per_kg": str(value),
    }


def require_formal_streams(streams: Sequence[int]) -> None:
    if tuple(int(value) for value in streams) != EXPECTED_STREAMS:
        raise EvidenceError(
            f"formal post-processing requires streams {EXPECTED_STREAMS}, got {tuple(streams)}"
        )


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def validate_new_output_directory(
    output_dir: Path, protected_directories: Iterable[Path]
) -> None:
    output_dir = output_dir.resolve()
    for protected in protected_directories:
        protected = protected.resolve()
        if _paths_overlap(output_dir, protected):
            raise EvidenceError(
                f"output directory overlaps an input or sealed directory: {protected}"
            )
    if output_dir.exists():
        raise EvidenceError("output directory must be new and must not already exist")


def split_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return [item for item in str(value).split(";") if item]


@dataclass(frozen=True)
class NodeState:
    node_id: str
    node_type: str
    demand: Decimal
    ready_time: Decimal
    due_time: Decimal
    service_time: Decimal
    x: Decimal
    y: Decimal

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "NodeState":
        return cls(
            node_id=str(payload["node_id"]),
            node_type=str(payload["node_type"]).lower(),
            demand=_decimal(payload.get("demand", 0), "node demand"),
            ready_time=_decimal(payload.get("ready_time", 0), "node ready_time"),
            due_time=_decimal(payload.get("due_time", 0), "node due_time"),
            service_time=_decimal(payload.get("service_time", 0), "node service_time"),
            x=_decimal(payload.get("x", 0), "node x"),
            y=_decimal(payload.get("y", 0), "node y"),
        )

    def with_event(self, event: Mapping[str, Any]) -> "NodeState":
        event_type = str(event["event_type"]).lower()
        if event_type in {"demand_change", "change"}:
            new_demand = event.get("new_demand")
            if new_demand in (None, ""):
                new_demand = self.demand + _decimal(
                    event.get("delta_demand", 0), "event delta_demand"
                )
            return NodeState(
                **{
                    **asdict(self),
                    "demand": _decimal(new_demand, "event new_demand"),
                }
            )
        if event_type in {"time_window_change", "time_change"}:
            return NodeState(
                **{
                    **asdict(self),
                    "ready_time": _decimal(
                        event.get("new_ready_time", self.ready_time),
                        "event new_ready_time",
                    ),
                    "due_time": _decimal(
                        event.get("new_due_time", self.due_time),
                        "event new_due_time",
                    ),
                    "service_time": _decimal(
                        event.get("new_service_time", self.service_time),
                        "event new_service_time",
                    ),
                }
            )
        raise EvidenceError(f"unsupported modifying event type: {event_type}")


@dataclass(frozen=True)
class ServiceRecord:
    customer_id: str
    demand_kg: Decimal
    ready_time: Decimal
    due_time: Decimal
    service_time: Decimal
    historical_owner: str
    serving_depot: str
    route_id: str
    booked_at_stage: int
    source: str

    def workload_payload(self) -> dict[str, str]:
        """Treatment-free fields used to decide whether costs are comparable."""
        return {
            "customer_id": self.customer_id,
            "demand_kg": str(self.demand_kg),
            "ready_time": str(self.ready_time),
            "due_time": str(self.due_time),
            "service_time": str(self.service_time),
        }

    def audit_payload(self) -> dict[str, Any]:
        payload = self.workload_payload()
        payload.update(
            {
                "historical_owner": self.historical_owner,
                "serving_depot": self.serving_depot,
                "route_id": self.route_id,
                "booked_at_stage": self.booked_at_stage,
                "source": self.source,
            }
        )
        return payload


@dataclass
class EventDisposition:
    event_id: str
    customer_id: str
    event_type: str
    stage: int
    status: str


@dataclass
class ArmLedger:
    stream_seed: int
    arm: str
    records: dict[str, ServiceRecord]
    event_dispositions: list[EventDisposition]
    final_total_cost: Decimal
    full_day_revenue: Decimal
    full_day_operating_net_benefit: Decimal
    workload_fingerprint: str
    audit_ledger_fingerprint: str
    cost_closure_pass: bool
    cost_closure_error: Decimal
    component_closure_error: Decimal
    evidence_errors: list[str] = field(default_factory=list)

    @property
    def served_customer_count(self) -> int:
        return len(self.records)

    @property
    def served_demand_kg(self) -> Decimal:
        return sum((record.demand_kg for record in self.records.values()), Decimal("0"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "stream_seed": self.stream_seed,
            "arm": self.arm,
            "revenue_per_kg": str(REVENUE_PER_KG),
            "served_customer_count": self.served_customer_count,
            "served_demand_kg": str(self.served_demand_kg),
            "full_day_revenue": str(self.full_day_revenue),
            "final_total_cost": str(self.final_total_cost),
            "full_day_operating_net_benefit": str(
                self.full_day_operating_net_benefit
            ),
            "workload_fingerprint": self.workload_fingerprint,
            "audit_ledger_fingerprint": self.audit_ledger_fingerprint,
            "cost_closure_pass": self.cost_closure_pass,
            "cost_closure_error": str(self.cost_closure_error),
            "component_closure_error": str(self.component_closure_error),
            "evidence_errors": list(self.evidence_errors),
            "service_records": [
                record.audit_payload()
                for record in sorted(self.records.values(), key=lambda item: item.customer_id)
            ],
            "event_dispositions": [asdict(item) for item in self.event_dispositions],
        }


def load_initial_nodes(instance_payload: Mapping[str, Any]) -> dict[str, NodeState]:
    nodes: dict[str, NodeState] = {}
    for raw in instance_payload.get("nodes", []):
        node = NodeState.from_payload(raw)
        if node.node_id in nodes:
            raise EvidenceError(f"duplicate node in initial instance: {node.node_id}")
        nodes[node.node_id] = node
    if not nodes:
        raise EvidenceError("initial instance has no nodes")
    return nodes


def _event_map(event_payload: Any) -> dict[str, Mapping[str, Any]]:
    raw_events = event_payload.get("events", []) if isinstance(event_payload, Mapping) else event_payload
    result: dict[str, Mapping[str, Any]] = {}
    for event in raw_events:
        event_id = str(event["event_id"])
        if event_id in result:
            raise EvidenceError(f"duplicate event id: {event_id}")
        result[event_id] = event
    return result


def _owner_map(owner_rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in owner_rows:
        customer_id = str(row["customer_id"])
        if customer_id in result:
            raise EvidenceError(f"duplicate owner row: {customer_id}")
        result[customer_id] = str(row["owner_depot_id"])
    return result


def _route_id(route: Mapping[str, Any]) -> str:
    for key in ("vehicle_id", "route_id"):
        if key in route and str(route[key]):
            return str(route[key])
    raise EvidenceError("route has neither vehicle_id nor route_id")


def _route_customer_ids(
    route: Mapping[str, Any], nodes: Mapping[str, NodeState]
) -> list[str]:
    result: list[str] = []
    for node_id in route.get("node_sequence", []):
        node_id = str(node_id)
        node = nodes.get(node_id)
        if node is not None and node.node_type == "c":
            result.append(node_id)
    if len(result) != len(set(result)):
        raise EvidenceError(f"route {_route_id(route)} repeats a customer")
    return result


def _book_routes(
    *,
    records: dict[str, ServiceRecord],
    routes: Sequence[Mapping[str, Any]],
    nodes: Mapping[str, NodeState],
    owners: Mapping[str, str],
    stage: int,
    source: str,
) -> None:
    for route in routes:
        route_id = _route_id(route)
        serving_depot = str(route.get("home_depot_id", ""))
        for customer_id in _route_customer_ids(route, nodes):
            if customer_id in records:
                raise EvidenceError(f"customer served twice: {customer_id}")
            node = nodes[customer_id]
            records[customer_id] = ServiceRecord(
                customer_id=customer_id,
                demand_kg=node.demand,
                ready_time=node.ready_time,
                due_time=node.due_time,
                service_time=node.service_time,
                historical_owner=str(owners.get(customer_id, "")),
                serving_depot=serving_depot,
                route_id=route_id,
                booked_at_stage=stage,
                source=source,
            )


def apply_recorded_events(
    *,
    nodes: dict[str, NodeState],
    event_by_id: Mapping[str, Mapping[str, Any]],
    event_ids: Sequence[str],
    applied_ids: Sequence[str],
    ignored_ids: Sequence[str],
    committed_customers: set[str],
    stage: int,
) -> list[EventDisposition]:
    event_set = set(event_ids)
    applied_set = set(applied_ids)
    ignored_set = set(ignored_ids)
    if applied_set & ignored_set:
        raise EvidenceError(f"stage {stage}: event marked both applied and ignored")
    if applied_set | ignored_set != event_set:
        raise EvidenceError(f"stage {stage}: event disposition does not close")
    if len(event_ids) != len(event_set):
        raise EvidenceError(f"stage {stage}: duplicate event id in batch")

    dispositions: list[EventDisposition] = []
    for event_id in event_ids:
        if event_id not in event_by_id:
            raise EvidenceError(f"stage {stage}: unknown event {event_id}")
        event = event_by_id[event_id]
        customer_id = str(event["customer_id"])
        event_type = str(event["event_type"]).lower()
        status = "applied" if event_id in applied_set else "ignored_locked"
        dispositions.append(
            EventDisposition(event_id, customer_id, event_type, stage, status)
        )

        if status == "ignored_locked":
            if customer_id not in committed_customers:
                raise EvidenceError(
                    f"stage {stage}: ignored event {event_id} is not locked by service"
                )
            if event_type == "add":
                raise EvidenceError(f"stage {stage}: add event cannot be ignored as locked")
            continue

        if customer_id in committed_customers:
            raise EvidenceError(
                f"stage {stage}: applied event {event_id} changes a served customer"
            )
        if event_type == "add":
            if customer_id in nodes:
                raise EvidenceError(f"stage {stage}: add duplicates {customer_id}")
            node = NodeState.from_payload(
                {
                    "node_id": customer_id,
                    "node_type": "c",
                    "demand": event.get("new_demand", event.get("delta_demand", 0)),
                    "ready_time": event.get("new_ready_time", 0),
                    "due_time": event.get("new_due_time", 0),
                    "service_time": event.get("new_service_time", 0),
                    "x": event.get("x", 0),
                    "y": event.get("y", 0),
                }
            )
            if node.service_time <= 0:
                raise EvidenceError(f"stage {stage}: added customer has no service time")
            nodes[customer_id] = node
        elif event_type == "cancel":
            node = nodes.get(customer_id)
            if node is None or node.node_type != "c":
                raise EvidenceError(f"stage {stage}: cancel target absent: {customer_id}")
            del nodes[customer_id]
        elif event_type in {
            "demand_change",
            "change",
            "time_window_change",
            "time_change",
        }:
            node = nodes.get(customer_id)
            if node is None or node.node_type != "c":
                raise EvidenceError(f"stage {stage}: change target absent: {customer_id}")
            nodes[customer_id] = node.with_event(event)
        else:
            raise EvidenceError(f"stage {stage}: unsupported event type {event_type}")
    return dispositions


def validate_event_coverage(
    event_by_id: Mapping[str, Mapping[str, Any]],
    dispositions: Sequence[EventDisposition],
    *,
    expected_count: int,
) -> None:
    if len(event_by_id) != expected_count:
        raise EvidenceError(
            f"frozen stream must contain {expected_count} events, found {len(event_by_id)}"
        )
    counts = Counter(item.event_id for item in dispositions)
    missing = sorted(set(event_by_id) - set(counts))
    extra = sorted(set(counts) - set(event_by_id))
    repeated = sorted(event_id for event_id, count in counts.items() if count != 1)
    if missing or extra or repeated or len(dispositions) != expected_count:
        raise EvidenceError(
            "event coverage does not close exactly once: "
            f"missing={missing}, extra={extra}, non_single={repeated}, "
            f"recorded={len(dispositions)}, expected={expected_count}"
        )


def _verify_payload_hash(payload: Mapping[str, Any], value_key: str) -> None:
    hash_key = f"{value_key}_sha256"
    if hash_key in payload and str(payload[hash_key]) != canonical_sha256(payload[value_key]):
        raise EvidenceError(f"recorded hash does not match {value_key}")


def _latest_stage_cost(stage_payload: Mapping[str, Any]) -> tuple[Decimal, Decimal]:
    breakdown = stage_payload.get("cost_breakdown")
    if not isinstance(breakdown, Mapping) or "total_cost" not in breakdown:
        raise EvidenceError("final stage has no total cost breakdown")
    total = _decimal(breakdown["total_cost"], "stage total_cost")
    missing = [key for key in COST_COMPONENTS if key not in breakdown]
    if missing:
        raise EvidenceError(f"final stage cost breakdown misses {','.join(missing)}")
    component_sum = sum(
        (_decimal(breakdown[key], f"stage {key}") for key in COST_COMPONENTS),
        Decimal("0"),
    )
    return total, abs(component_sum - total)


def reconstruct_arm_ledger(
    *,
    stream_seed: int,
    arm: str,
    instance_payload: Mapping[str, Any],
    event_payload: Any,
    owner_rows: Sequence[Mapping[str, Any]],
    raw_stage_rows: Sequence[Mapping[str, Any]],
    stage_evidence: Sequence[Mapping[str, Any]],
    final_solution: Mapping[str, Any],
    session_row: Mapping[str, Any],
    expected_event_count: int | None = None,
) -> ArmLedger:
    if arm not in EXPECTED_ARMS:
        raise EvidenceError(f"unknown arm: {arm}")
    if not stage_evidence:
        raise EvidenceError("session has no stage evidence")
    raw_by_stage = {int(row["stage"]): row for row in raw_stage_rows}
    if len(raw_by_stage) != len(raw_stage_rows):
        raise EvidenceError("duplicate raw stage row")
    if set(raw_by_stage) != set(range(1, len(stage_evidence) + 1)):
        raise EvidenceError("raw/evidence stage index mismatch")

    nodes = load_initial_nodes(instance_payload)
    owners = _owner_map(owner_rows)
    events = _event_map(event_payload)
    records: dict[str, ServiceRecord] = {}
    dispositions: list[EventDisposition] = []
    booked_route_signatures: dict[str, str] = {}

    for expected_stage, payload in enumerate(stage_evidence, start=1):
        if int(payload["stage"]) != expected_stage:
            raise EvidenceError("stage evidence is out of order")
        if int(payload["stream_seed"]) != stream_seed or str(payload["arm"]) != arm:
            raise EvidenceError("stage evidence belongs to another session")
        raw = raw_by_stage[expected_stage]
        if int(raw["stream_seed"]) != stream_seed or str(raw["arm"]) != arm:
            raise EvidenceError("raw row belongs to another session")

        for key in (
            "locked_routes",
            "active_customer_ids",
            "committed_customer_ids",
            "future_customer_ids",
            "solution",
            "certificate",
        ):
            if key in payload:
                _verify_payload_hash(payload, key)

        new_locked_routes: list[Mapping[str, Any]] = []
        for route in payload.get("locked_routes", []):
            route_id = _route_id(route)
            signature = canonical_sha256(route)
            previous = booked_route_signatures.get(route_id)
            if previous is None:
                booked_route_signatures[route_id] = signature
                new_locked_routes.append(route)
            elif previous != signature:
                raise EvidenceError(f"locked route changed after booking: {route_id}")

        # The formal runner books newly locked routes before applying this stage's
        # events.  Repeating that order is essential for late cancels and changes.
        _book_routes(
            records=records,
            routes=new_locked_routes,
            nodes=nodes,
            owners=owners,
            stage=expected_stage,
            source="locked_before_event",
        )
        committed_customers = set(records)

        event_ids = split_ids(raw.get("event_ids"))
        dispositions.extend(
            apply_recorded_events(
                nodes=nodes,
                event_by_id=events,
                event_ids=event_ids,
                applied_ids=split_ids(raw.get("applied_event_ids")),
                ignored_ids=split_ids(raw.get("ignored_locked_event_ids")),
                committed_customers=committed_customers,
                stage=expected_stage,
            )
        )

        recorded_committed = {str(item) for item in payload["committed_customer_ids"]}
        if recorded_committed != committed_customers:
            raise EvidenceError(f"stage {expected_stage}: committed ledger mismatch")
        active_customers = {
            node_id for node_id, node in nodes.items() if node.node_type == "c"
        }
        recorded_active = {str(item) for item in payload["active_customer_ids"]}
        if recorded_active != active_customers:
            raise EvidenceError(f"stage {expected_stage}: active customer mismatch")
        recorded_future = {str(item) for item in payload["future_customer_ids"]}
        if committed_customers & recorded_future:
            raise EvidenceError(f"stage {expected_stage}: committed/future overlap")
        if committed_customers | recorded_future != active_customers:
            raise EvidenceError(f"stage {expected_stage}: customer accounting does not close")

    if expected_event_count is not None:
        validate_event_coverage(
            events,
            dispositions,
            expected_count=expected_event_count,
        )

    final_payload = stage_evidence[-1]
    if final_solution != final_payload.get("solution"):
        raise EvidenceError("final solution does not equal the last recorded stage solution")
    final_future = {str(item) for item in final_payload["future_customer_ids"]}
    _book_routes(
        records=records,
        routes=final_solution.get("routes", []),
        nodes=nodes,
        owners=owners,
        stage=len(stage_evidence) + 1,
        source="final_future_plan",
    )
    if set(records) != {node_id for node_id, node in nodes.items() if node.node_type == "c"}:
        raise EvidenceError("full-day service ledger does not cover the final active set")
    if {key for key, value in records.items() if value.source == "final_future_plan"} != final_future:
        raise EvidenceError("final future service ledger differs from recorded future set")

    workload_payload = [
        record.workload_payload()
        for record in sorted(records.values(), key=lambda item: item.customer_id)
    ]
    audit_payload = [
        record.audit_payload()
        for record in sorted(records.values(), key=lambda item: item.customer_id)
    ]
    total_demand = sum((record.demand_kg for record in records.values()), Decimal("0"))
    revenue = total_demand * REVENUE_PER_KG
    total_cost = _decimal(session_row["final_total_cost"], "session final_total_cost")
    stage_total, component_error = _latest_stage_cost(final_payload)
    cost_error = abs(stage_total - total_cost)
    closure_pass = _close(stage_total, total_cost) and _close(
        component_error, Decimal("0")
    )
    errors: list[str] = []
    if not _close(stage_total, total_cost):
        errors.append("final session cost differs from final stage ledger")
    if not _close(component_error, Decimal("0")):
        errors.append("final cost components do not sum to total")

    return ArmLedger(
        stream_seed=stream_seed,
        arm=arm,
        records=records,
        event_dispositions=dispositions,
        final_total_cost=total_cost,
        full_day_revenue=revenue,
        full_day_operating_net_benefit=revenue - total_cost,
        workload_fingerprint=canonical_sha256(workload_payload),
        audit_ledger_fingerprint=canonical_sha256(audit_payload),
        cost_closure_pass=closure_pass,
        cost_closure_error=cost_error,
        component_closure_error=component_error,
        evidence_errors=errors,
    )


def _event_disposition_index(ledger: ArmLedger) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for item in ledger.event_dispositions:
        index.setdefault(item.customer_id, []).append(asdict(item))
    return index


def explain_workload_difference(
    cooperative: ArmLedger, independent: ArmLedger
) -> dict[str, Any]:
    cooperative_ids = set(cooperative.records)
    independent_ids = set(independent.records)
    cooperative_events = _event_disposition_index(cooperative)
    independent_events = _event_disposition_index(independent)
    reasons: list[dict[str, Any]] = []
    for customer_id in sorted(cooperative_ids | independent_ids):
        left = cooperative.records.get(customer_id)
        right = independent.records.get(customer_id)
        differences: list[str] = []
        if left is None:
            differences.append("served_only_by_independent")
        elif right is None:
            differences.append("served_only_by_cooperative")
        else:
            if left.demand_kg != right.demand_kg:
                differences.append("served_demand_differs")
            if (
                left.ready_time,
                left.due_time,
                left.service_time,
            ) != (
                right.ready_time,
                right.due_time,
                right.service_time,
            ):
                differences.append("service_contract_differs")
        if differences:
            reasons.append(
                {
                    "customer_id": customer_id,
                    "differences": differences,
                    "cooperative_events": cooperative_events.get(customer_id, []),
                    "independent_events": independent_events.get(customer_id, []),
                }
            )
    return {"customers": reasons}


def compare_stream(cooperative: ArmLedger, independent: ArmLedger) -> dict[str, Any]:
    if cooperative.stream_seed != independent.stream_seed:
        raise EvidenceError("cannot compare different stream seeds")
    workload_equal = (
        cooperative.workload_fingerprint == independent.workload_fingerprint
    )
    closure_pass = cooperative.cost_closure_pass and independent.cost_closure_pass
    status = "COMPARABLE_SAME_WORKLOAD" if workload_equal else "DIFFERENT_WORKLOAD"
    if not closure_pass:
        status = "INCOMPARABLE_COST_LEDGER_OPEN"

    cost_change_percent: str | None = None
    net_benefit_change: str | None = None
    net_benefit_change_percent: str | None = None
    if closure_pass and workload_equal:
        if independent.final_total_cost == 0:
            status = "INCOMPARABLE_ZERO_INDEPENDENT_COST"
        else:
            cost_change_percent = str(
                Decimal("100")
                * (independent.final_total_cost - cooperative.final_total_cost)
                / independent.final_total_cost
            )
    elif closure_pass:
        net_benefit_change = str(
            cooperative.full_day_operating_net_benefit
            - independent.full_day_operating_net_benefit
        )
        if independent.full_day_operating_net_benefit != 0:
            net_benefit_change_percent = str(
                Decimal("100")
                * (
                    cooperative.full_day_operating_net_benefit
                    - independent.full_day_operating_net_benefit
                )
                / independent.full_day_operating_net_benefit
            )

    difference = explain_workload_difference(cooperative, independent)
    return {
        "stream_seed": cooperative.stream_seed,
        "status": status,
        "workload_equal": workload_equal,
        "cooperative_customer_count": cooperative.served_customer_count,
        "independent_customer_count": independent.served_customer_count,
        "customer_count_difference": (
            cooperative.served_customer_count - independent.served_customer_count
        ),
        "cooperative_demand_kg": str(cooperative.served_demand_kg),
        "independent_demand_kg": str(independent.served_demand_kg),
        "demand_difference_kg": str(
            cooperative.served_demand_kg - independent.served_demand_kg
        ),
        "cooperative_workload_fingerprint": cooperative.workload_fingerprint,
        "independent_workload_fingerprint": independent.workload_fingerprint,
        "cooperative_audit_ledger_fingerprint": cooperative.audit_ledger_fingerprint,
        "independent_audit_ledger_fingerprint": independent.audit_ledger_fingerprint,
        "cooperative_full_day_revenue": str(cooperative.full_day_revenue),
        "independent_full_day_revenue": str(independent.full_day_revenue),
        "cooperative_final_total_cost": str(cooperative.final_total_cost),
        "independent_final_total_cost": str(independent.final_total_cost),
        "cooperative_full_day_operating_net_benefit": str(
            cooperative.full_day_operating_net_benefit
        ),
        "independent_full_day_operating_net_benefit": str(
            independent.full_day_operating_net_benefit
        ),
        "cost_change_percent": cost_change_percent,
        "net_benefit_change": net_benefit_change,
        "net_benefit_change_percent": net_benefit_change_percent,
        "cooperative_cost_closure_pass": cooperative.cost_closure_pass,
        "independent_cost_closure_pass": independent.cost_closure_pass,
        "difference_reason_json": json.dumps(
            difference, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    }


def retain_all_streams(
    paired_by_seed: Mapping[int, Mapping[str, Any]],
    expected_streams: Sequence[int] = EXPECTED_STREAMS,
) -> list[dict[str, Any]]:
    """Never drop an unfavourable or incomplete stream from the final table."""
    rows: list[dict[str, Any]] = []
    for stream_seed in expected_streams:
        if stream_seed in paired_by_seed:
            rows.append(dict(paired_by_seed[stream_seed]))
        else:
            rows.append(
                {
                    "stream_seed": stream_seed,
                    "status": "MISSING_EVIDENCE",
                    "workload_equal": None,
                    "cost_change_percent": None,
                    "net_benefit_change": None,
                    "difference_reason_json": json.dumps(
                        {"reason": "one or both arms are missing"},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
    return rows


def overall_decision_status(
    *,
    failures: Mapping[tuple[int, str], str],
    cost_closure_failures: Sequence[str],
    ledger_count: int,
    complete_event_coverage: bool,
) -> str:
    passed = (
        not failures
        and not cost_closure_failures
        and ledger_count == len(EXPECTED_STREAMS) * len(EXPECTED_ARMS)
        and complete_event_coverage
    )
    return "PASS" if passed else "FAIL"


def _resolve_recorded_path(root: Path, recorded: str) -> Path:
    path = Path(recorded)
    if path.is_absolute():
        raise EvidenceError(f"recorded path must be repository-relative: {recorded}")
    resolved = (root / path).resolve()
    _relative_to(resolved, root, "recorded path")
    return resolved


def _verify_recorded_file(
    root: Path,
    row: Mapping[str, Any],
    path_key: str,
    hash_key: str,
    *,
    expected_relative_path: Path | None = None,
) -> Path:
    recorded = Path(str(row[path_key]))
    if expected_relative_path is not None and recorded != expected_relative_path:
        raise EvidenceError(
            f"{path_key} differs from the frozen path: {recorded} != {expected_relative_path}"
        )
    path = _resolve_recorded_path(root, str(recorded))
    if not path.is_file():
        raise EvidenceError(f"recorded file is missing: {path}")
    if hash_key not in row or not str(row[hash_key]):
        raise EvidenceError(f"recorded file has no required hash: {hash_key}")
    if file_sha256(path) != str(row[hash_key]):
        raise EvidenceError(f"recorded file hash differs: {path_key}")
    return path


def _verify_commit_bound_file(
    repo_root: Path,
    source_commit: str,
    relative_path: Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, str]:
    path = (repo_root / relative_path).resolve()
    _relative_to(path, repo_root, "frozen input")
    if not path.is_file():
        raise EvidenceError(f"frozen input is missing: {relative_path}")
    current_hash = file_sha256(path)
    blob_hash = bytes_sha256(_git_blob(repo_root, source_commit, relative_path))
    if current_hash != blob_hash:
        raise EvidenceError(
            f"frozen input differs from run commit: {relative_path.as_posix()}"
        )
    if expected_sha256 is not None and current_hash != expected_sha256:
        raise EvidenceError(
            f"frozen input hash differs: {relative_path.as_posix()}"
        )
    return {
        "path": relative_path.as_posix(),
        "commit": source_commit,
        "sha256": current_hash,
    }


def validate_artifact_manifest(
    repo_root: Path, run_dir: Path
) -> dict[str, Any]:
    manifest_path = run_dir / "artifact_hashes.json"
    if not manifest_path.is_file():
        raise EvidenceError("formal batch has no artifact_hashes.json")
    payload = load_json(manifest_path)
    if payload.get("algorithm") != "sha256":
        raise EvidenceError("formal artifact manifest does not use sha256")
    entries = payload.get("artifacts")
    if not isinstance(entries, list):
        raise EvidenceError("formal artifact manifest has no artifact list")

    listed: dict[Path, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise EvidenceError("formal artifact manifest contains a non-object entry")
        relative = Path(str(entry.get("path", "")))
        if relative.is_absolute():
            raise EvidenceError("formal artifact manifest contains an absolute path")
        path = (repo_root / relative).resolve()
        _relative_to(path, run_dir, "formal artifact")
        if path in listed:
            raise EvidenceError(f"formal artifact is listed twice: {relative}")
        if not path.is_file() or path.is_symlink():
            raise EvidenceError(f"formal artifact is missing or is a symlink: {relative}")
        if str(entry.get("sha256", "")) != file_sha256(path):
            raise EvidenceError(f"formal artifact hash differs: {relative}")
        if int(entry.get("bytes", -1)) != path.stat().st_size:
            raise EvidenceError(f"formal artifact byte count differs: {relative}")
        listed[path] = entry

    actual = {
        path.resolve()
        for path in run_dir.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    if set(listed) != actual:
        missing = sorted(str(path) for path in actual - set(listed))
        extra = sorted(str(path) for path in set(listed) - actual)
        raise EvidenceError(
            f"formal artifact manifest does not exactly close: missing={missing}, extra={extra}"
        )
    required_names = {"metadata.json", "session_summary.csv", "raw_runs.csv"}
    if not required_names <= {path.name for path in listed}:
        raise EvidenceError("formal artifact manifest omits a required batch file")
    return {
        "path": _relative_to(manifest_path, repo_root, "artifact manifest").as_posix(),
        "sha256": file_sha256(manifest_path),
        "artifact_count": len(listed),
    }


def validate_formal_input_contract(
    *,
    run_dir: Path,
    repo_root: Path,
    instance_path: Path,
    metadata: Mapping[str, Any],
    sessions: Sequence[Mapping[str, Any]],
    raw_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], set[Path]]:
    repo_root = repo_root.resolve()
    run_dir = run_dir.resolve()
    instance_path = instance_path.resolve()
    expected_run_dir = (repo_root / FORMAL_RUN_RELATIVE_PATH).resolve()
    if run_dir != expected_run_dir:
        raise EvidenceError(
            f"run directory is not the frozen formal batch: {run_dir} != {expected_run_dir}"
        )
    expected_instance = (repo_root / FROZEN_INSTANCE_RELATIVE_PATH).resolve()
    if instance_path != expected_instance:
        raise EvidenceError(
            "instance path is not the frozen 221-customer instance: "
            f"{instance_path} != {expected_instance}"
        )

    exact_metadata = {
        "contract_id": FORMAL_CONTRACT_ID,
        "scope": "formal",
        "network": "L-main-threeshift-100c-01",
        "customer_count": 221,
        "arms": list(EXPECTED_ARMS),
        "streams": list(EXPECTED_STREAMS),
        "evaluations_per_stage": 400,
        "maximum_stages": None,
        "trigger_mode": "batched",
        "q_bar": 8,
        "delta_t": 10800.0,
        "delta_t_seconds": 10800.0,
        "workers": 6,
        "shared_initial_plan": True,
        "treatment_difference": "cross-depot service permission only",
        "result_direction_used_to_continue": False,
    }
    for key, expected in exact_metadata.items():
        if metadata.get(key) != expected:
            raise EvidenceError(
                f"formal metadata {key} differs: {metadata.get(key)!r} != {expected!r}"
            )
    source_commit = str(metadata.get("source_commit", ""))
    if str(metadata.get("run_start_commit", "")) != source_commit:
        raise EvidenceError("formal metadata does not bind one run-start commit")

    manifest_evidence = validate_artifact_manifest(repo_root, run_dir)
    revenue_evidence = validate_revenue_source(repo_root, metadata)
    instance_evidence = _verify_commit_bound_file(
        repo_root,
        source_commit,
        FROZEN_INSTANCE_RELATIVE_PATH,
        expected_sha256=FROZEN_INSTANCE_SHA256,
    )
    event_manifest_evidence = _verify_commit_bound_file(
        repo_root,
        source_commit,
        EVENT_MANIFEST_RELATIVE_PATH,
    )
    event_manifest = load_json(repo_root / EVENT_MANIFEST_RELATIVE_PATH)
    if event_manifest.get("contract_id") != "E7_EVENT_STREAM_FREEZE_V3_SERVICE_TIME":
        raise EvidenceError("event manifest contract is not the frozen V3 contract")
    manifest_streams = event_manifest.get("streams")
    if not isinstance(manifest_streams, list) or [
        int(row.get("seed", -1)) for row in manifest_streams
    ] != list(EXPECTED_STREAMS):
        raise EvidenceError("event manifest does not contain streams 1-5 exactly once")

    expected_keys = {
        (stream_seed, arm)
        for stream_seed in EXPECTED_STREAMS
        for arm in EXPECTED_ARMS
    }
    session_keys = [
        (int(row["stream_seed"]), str(row["arm"])) for row in sessions
    ]
    if len(session_keys) != len(set(session_keys)) or set(session_keys) != expected_keys:
        raise EvidenceError("session summary is not exactly the ten formal stream-arm sessions")
    raw_keys = {(int(row["stream_seed"]), str(row["arm"])) for row in raw_rows}
    if raw_keys != expected_keys:
        raise EvidenceError("raw stage rows are not exactly from the ten formal sessions")

    manifest_by_seed = {int(row["seed"]): row for row in manifest_streams}
    protected_directories: set[Path] = {
        run_dir,
        run_dir.parent,
        instance_path.parent,
        (repo_root / EVENT_ROOT_RELATIVE_PATH).resolve(),
        (repo_root / E6_INITIAL_ROOT_RELATIVE_PATH).resolve(),
    }
    frozen_inputs: dict[str, dict[str, str]] = {
        "instance": instance_evidence,
        "event_manifest": event_manifest_evidence,
    }
    for stream_seed in EXPECTED_STREAMS:
        manifest_row = manifest_by_seed[stream_seed]
        expected_event = EVENT_ROOT_RELATIVE_PATH / f"stream_seed{stream_seed}.events.json"
        expected_owner = EVENT_ROOT_RELATIVE_PATH / f"stream_seed{stream_seed}.owners.csv"
        if Path(str(manifest_row.get("events_json", ""))) != expected_event:
            raise EvidenceError(f"stream {stream_seed} event manifest path differs")
        if Path(str(manifest_row.get("owners_csv", ""))) != expected_owner:
            raise EvidenceError(f"stream {stream_seed} owner manifest path differs")
        event_evidence = _verify_commit_bound_file(
            repo_root, source_commit, expected_event
        )
        owner_evidence = _verify_commit_bound_file(
            repo_root, source_commit, expected_owner
        )
        if event_evidence["sha256"] != str(manifest_row.get("events_json_sha256", "")):
            raise EvidenceError(f"stream {stream_seed} event manifest hash differs")
        if owner_evidence["sha256"] != str(manifest_row.get("owners_csv_sha256", "")):
            raise EvidenceError(f"stream {stream_seed} owner manifest hash differs")
        if len(_event_map(load_json(repo_root / expected_event))) != EXPECTED_EVENTS_PER_STREAM:
            raise EvidenceError(f"stream {stream_seed} does not contain exactly 55 events")
        frozen_inputs[f"stream{stream_seed}_events"] = event_evidence
        frozen_inputs[f"stream{stream_seed}_owners"] = owner_evidence

    initial_solution = (
        E6_INITIAL_ROOT_RELATIVE_PATH / "solutions" / f"{E6_INITIAL_CASE}.json"
    )
    initial_certificate = (
        E6_INITIAL_ROOT_RELATIVE_PATH / "certificates" / f"{E6_INITIAL_CASE}.json"
    )
    frozen_inputs["initial_solution"] = _verify_commit_bound_file(
        repo_root, source_commit, initial_solution
    )
    frozen_inputs["initial_certificate"] = _verify_commit_bound_file(
        repo_root, source_commit, initial_certificate
    )

    for session in sessions:
        stream_seed = int(session["stream_seed"])
        arm = str(session["arm"])
        stem = f"stream{stream_seed}__{arm}"
        if str(session.get("trigger_mode", "")) != "batched":
            raise EvidenceError(f"{stem} trigger mode is not batched")
        if int(session.get("evaluations_per_stage", -1)) != 400:
            raise EvidenceError(f"{stem} stage budget is not 400")
        expected_paths = {
            "event_path": EVENT_ROOT_RELATIVE_PATH / f"stream_seed{stream_seed}.events.json",
            "owner_path": EVENT_ROOT_RELATIVE_PATH / f"stream_seed{stream_seed}.owners.csv",
            "initial_solution_path": initial_solution,
            "initial_certificate_path": initial_certificate,
            "final_solution_path": FORMAL_RUN_RELATIVE_PATH / "solutions" / f"{stem}.json",
            "final_certificate_path": FORMAL_RUN_RELATIVE_PATH / "certificates" / f"{stem}.json",
            "stage_evidence_path": FORMAL_RUN_RELATIVE_PATH / "stage_evidence" / f"{stem}.json",
        }
        for path_key, expected_path in expected_paths.items():
            hash_key = path_key.replace("_path", "_sha256")
            path = _verify_recorded_file(
                repo_root,
                session,
                path_key,
                hash_key,
                expected_relative_path=expected_path,
            )
            protected_directories.add(path.parent)
    return (
        {
            "formal_run_path": FORMAL_RUN_RELATIVE_PATH.as_posix(),
            "source_commit": source_commit,
            "artifact_manifest": manifest_evidence,
            "revenue_source": revenue_evidence,
            "frozen_inputs": frozen_inputs,
            "streams": list(EXPECTED_STREAMS),
            "events_per_stream": EXPECTED_EVENTS_PER_STREAM,
        },
        protected_directories,
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _raw_ledger_rows(ledgers: Mapping[tuple[int, str], ArmLedger]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (stream_seed, arm), ledger in sorted(ledgers.items()):
        status_counts = Counter(item.status for item in ledger.event_dispositions)
        rows.append(
            {
                "stream_seed": stream_seed,
                "arm": arm,
                "served_customer_count": ledger.served_customer_count,
                "served_demand_kg": str(ledger.served_demand_kg),
                "full_day_revenue": str(ledger.full_day_revenue),
                "full_day_total_cost": str(ledger.final_total_cost),
                "full_day_operating_net_benefit": str(
                    ledger.full_day_operating_net_benefit
                ),
                "event_disposition_count": len(ledger.event_dispositions),
                "applied_event_count": status_counts.get("applied", 0),
                "ignored_locked_event_count": status_counts.get("ignored_locked", 0),
                "workload_fingerprint": ledger.workload_fingerprint,
                "audit_ledger_fingerprint": ledger.audit_ledger_fingerprint,
                "cost_closure_pass": ledger.cost_closure_pass,
                "cost_closure_error": str(ledger.cost_closure_error),
                "component_closure_error": str(ledger.component_closure_error),
            }
        )
    return rows


def _paper_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    percentages = [
        _decimal(row["net_benefit_change_percent"], "net benefit change percent")
        for row in rows
        if row.get("net_benefit_change_percent") not in (None, "")
    ]
    amounts = [
        _decimal(row["net_benefit_change"], "net benefit change")
        for row in rows
        if row.get("net_benefit_change") not in (None, "")
    ]
    if len(percentages) != len(EXPECTED_STREAMS) or len(amounts) != len(EXPECTED_STREAMS):
        raise EvidenceError("the five paired net-benefit comparisons are incomplete")
    positive = sum(value > 0 for value in percentages)
    return {
        "paired_stream_count": len(percentages),
        "positive_stream_count": positive,
        "negative_stream_count": sum(value < 0 for value in percentages),
        "zero_stream_count": sum(value == 0 for value in percentages),
        "mean_net_benefit_change_gbp": str(sum(amounts) / Decimal(len(amounts))),
        "median_net_benefit_change_gbp": str(statistics.median(amounts)),
        "mean_net_benefit_change_percent": str(
            sum(percentages) / Decimal(len(percentages))
        ),
        "median_net_benefit_change_percent": str(statistics.median(percentages)),
        "minimum_net_benefit_change_percent": str(min(percentages)),
        "maximum_net_benefit_change_percent": str(max(percentages)),
        "all_pairs_had_different_realized_workload": all(
            str(row.get("workload_equal", "")).lower() == "false" for row in rows
        ),
    }


def _write_report(
    output_dir: Path,
    *,
    decision: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    summary = decision["paper_summary"]
    detail = []
    for row in rows:
        detail.append(
            "| {seed} | {amount:.3f} | {percent:.3f}% |".format(
                seed=int(row["stream_seed"]),
                amount=float(row["net_benefit_change"]),
                percent=float(row["net_benefit_change_percent"]),
            )
        )
    lines = [
        "# E7 全日经营结果复核",
        "",
        "## 判定",
        "",
        "复核通过。五条预先冻结的订单变化序列、两种经营方式和全部550条事件记录均已逐项对齐，成本分项能够闭合，独立重放检查也通过。",
        "",
        "两种经营方式在同一条事件序列中不一定完成完全相同的工作。一方已经发车后到来的取消或需求变化不能再改动，另一方尚未发车时则可以执行，因此直接比较两边总成本会把工作量差异误当成合作效果。本报告只在工作量完全相同时给出成本降幅；本批五组工作量均有差异，故改用全日经营净收益，即完成订单形成的收入减去全天成本。",
        "",
        "合作经营在{positive}/5条序列中取得更高的全日经营净收益，平均变化{mean:.3f}%，中位数{median:.3f}%；最低为{minimum:.3f}%，最高为{maximum:.3f}%。这说明合作收益在多数动态序列中得以保留，但不能写成每条序列都改善。".format(
            positive=int(summary["positive_stream_count"]),
            mean=float(summary["mean_net_benefit_change_percent"]),
            median=float(summary["median_net_benefit_change_percent"]),
            minimum=float(summary["minimum_net_benefit_change_percent"]),
            maximum=float(summary["maximum_net_benefit_change_percent"]),
        ),
        "",
        "| 订单变化序列 | 合作经营净收益变化/英镑 | 相对变化 |",
        "|---:|---:|---:|",
        *detail,
        "",
        "## 证据边界",
        "",
        "本批结果用于说明动态订单到来时合作经营价值是否仍能保留，不用于证明合作在每一种变化下都更省钱。经营净收益采用冻结的单位货物收入计算；收入规则、事件序列、初始方案、算例、价格参数和运行源码均由文件指纹绑定。碳排放与双方参与条件另行检查，不由本报告代替。",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_artifact_hashes(output_dir: Path, repo_root: Path) -> None:
    artifacts = []
    for path in sorted(output_dir.rglob("*")):
        if (
            not path.is_file()
            or path.name == "artifact_hashes.json"
            or path.name.startswith("._")
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
        ):
            continue
        artifacts.append(
            {
                "path": _relative_to(path, repo_root, "audit artifact").as_posix(),
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            "algorithm": "sha256",
            "excluded": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
            "artifacts": artifacts,
        },
    )


def postprocess(
    *,
    run_dir: Path,
    repo_root: Path,
    instance_path: Path,
    output_dir: Path,
    expected_streams: Sequence[int] = EXPECTED_STREAMS,
) -> list[dict[str, Any]]:
    run_dir = run_dir.resolve()
    repo_root = repo_root.resolve()
    instance_path = instance_path.resolve()
    output_dir = output_dir.resolve()
    require_formal_streams(expected_streams)
    metadata = load_json(run_dir / "metadata.json")
    sessions = read_csv_rows(run_dir / "session_summary.csv")
    raw_rows = read_csv_rows(run_dir / "raw_runs.csv")
    input_evidence, protected_directories = validate_formal_input_contract(
        run_dir=run_dir,
        repo_root=repo_root,
        instance_path=instance_path,
        metadata=metadata,
        sessions=sessions,
        raw_rows=raw_rows,
    )
    audit_source = validate_audit_source(repo_root)
    try:
        from validate_e7_records_independent_20260714 import validate_formal_run

        independent_validation = validate_formal_run(repo_root, run_dir)
    except Exception as exc:
        raise EvidenceError(f"independent record replay failed: {exc}") from exc
    if independent_validation.get("verdict") != "RECORD_LAYER_PASS":
        raise EvidenceError("independent record replay did not pass")
    validate_new_output_directory(output_dir, protected_directories)
    instance_payload = load_json(instance_path)
    session_by_key = {
        (int(row["stream_seed"]), str(row["arm"])): row for row in sessions
    }
    raw_by_key: dict[tuple[int, str], list[Mapping[str, Any]]] = {}
    for row in raw_rows:
        raw_by_key.setdefault((int(row["stream_seed"]), str(row["arm"])), []).append(row)

    ledgers: dict[tuple[int, str], ArmLedger] = {}
    failures: dict[tuple[int, str], str] = {}
    for stream_seed in expected_streams:
        for arm in EXPECTED_ARMS:
            key = (stream_seed, arm)
            try:
                session = session_by_key[key]
                event_path = _verify_recorded_file(
                    repo_root, session, "event_path", "event_sha256"
                )
                owner_path = _verify_recorded_file(
                    repo_root, session, "owner_path", "owner_sha256"
                )
                evidence_path = _verify_recorded_file(
                    repo_root,
                    session,
                    "stage_evidence_path",
                    "stage_evidence_sha256",
                )
                solution_path = _verify_recorded_file(
                    repo_root,
                    session,
                    "final_solution_path",
                    "final_solution_sha256",
                )
                ledgers[key] = reconstruct_arm_ledger(
                    stream_seed=stream_seed,
                    arm=arm,
                    instance_payload=instance_payload,
                    event_payload=load_json(event_path),
                    owner_rows=read_csv_rows(owner_path),
                    raw_stage_rows=raw_by_key[key],
                    stage_evidence=load_json(evidence_path),
                    final_solution=load_json(solution_path),
                    session_row=session,
                    expected_event_count=EXPECTED_EVENTS_PER_STREAM,
                )
            except (EvidenceError, KeyError, OSError, ValueError) as exc:
                failures[key] = str(exc)

    paired: dict[int, dict[str, Any]] = {}
    for stream_seed in expected_streams:
        cooperative = ledgers.get((stream_seed, "cooperative"))
        independent = ledgers.get((stream_seed, "independent"))
        if cooperative is not None and independent is not None:
            paired[stream_seed] = compare_stream(cooperative, independent)
        else:
            paired[stream_seed] = {
                "stream_seed": stream_seed,
                "status": "MISSING_OR_INVALID_EVIDENCE",
                "workload_equal": None,
                "cost_change_percent": None,
                "net_benefit_change": None,
                "difference_reason_json": json.dumps(
                    {
                        "cooperative": failures.get((stream_seed, "cooperative")),
                        "independent": failures.get((stream_seed, "independent")),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
    rows = retain_all_streams(paired, expected_streams)

    expected_ledger_count = len(EXPECTED_STREAMS) * len(EXPECTED_ARMS)
    expected_disposition_count = (
        EXPECTED_EVENTS_PER_STREAM * len(EXPECTED_STREAMS) * len(EXPECTED_ARMS)
    )
    recorded_disposition_count = sum(
        len(ledger.event_dispositions) for ledger in ledgers.values()
    )
    cost_closure_failures = [
        f"stream{stream_seed}__{arm}"
        for (stream_seed, arm), ledger in sorted(ledgers.items())
        if not ledger.cost_closure_pass
    ]
    complete_event_coverage = (
        len(ledgers) == expected_ledger_count
        and recorded_disposition_count == expected_disposition_count
        and all(
            len(ledger.event_dispositions) == EXPECTED_EVENTS_PER_STREAM
            for ledger in ledgers.values()
        )
    )
    overall_status = overall_decision_status(
        failures=failures,
        cost_closure_failures=cost_closure_failures,
        ledger_count=len(ledgers),
        complete_event_coverage=complete_event_coverage,
    )

    output_dir.mkdir(parents=True, exist_ok=False)
    ledger_dir = output_dir / "service_ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    for (stream_seed, arm), ledger in ledgers.items():
        (ledger_dir / f"stream{stream_seed}__{arm}.json").write_text(
            json.dumps(ledger.to_payload(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
    _write_csv(output_dir / "paired_value_summary.csv", rows)
    _write_csv(output_dir / "raw_runs.csv", _raw_ledger_rows(ledgers))
    _write_json(output_dir / "independent_validation.json", independent_validation)
    paper_summary = _paper_summary(rows)
    metadata = {
        "contract_id": "E7_FULL_DAY_VALUE_AUDIT_V1",
        "scope": "formal_read_only_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_run": FORMAL_RUN_RELATIVE_PATH.as_posix(),
        "source_run_commit": input_evidence["source_commit"],
        "audit_commit": current_git_commit(repo_root),
        "audit_source": audit_source,
        "streams": list(EXPECTED_STREAMS),
        "arms": list(EXPECTED_ARMS),
        "revenue_per_kg": str(REVENUE_PER_KG),
        "comparison_rule": (
            "compare cost only for identical full-day workloads; otherwise compare "
            "full-day operating net benefit (revenue minus cost)"
        ),
        "result_direction_used_to_continue": False,
    }
    _write_json(output_dir / "metadata.json", metadata)
    decision = {
        "status": overall_status,
        "expected_streams": list(expected_streams),
        "reported_streams": [int(row["stream_seed"]) for row in rows],
        "all_streams_retained": [int(row["stream_seed"]) for row in rows]
        == list(expected_streams),
        "frozen_revenue_per_kg": str(REVENUE_PER_KG),
        "input_contract": input_evidence,
        "event_coverage": {
            "events_per_stream": EXPECTED_EVENTS_PER_STREAM,
            "stream_count": len(EXPECTED_STREAMS),
            "arm_count": len(EXPECTED_ARMS),
            "expected_disposition_count": expected_disposition_count,
            "recorded_disposition_count": recorded_disposition_count,
            "every_event_covered_exactly_once_per_arm": complete_event_coverage,
        },
        "cost_closure_failures": cost_closure_failures,
        "cost_percentage_rule": (
            "filled only when full-day workload fingerprints match and both cost ledgers close"
        ),
        "different_workload_rule": (
            "cost percentage left blank; compare full-day operating net benefit"
        ),
        "independent_record_replay": independent_validation["verdict"],
        "paper_summary": paper_summary,
        "failures": {
            f"stream{seed}__{arm}": message
            for (seed, arm), message in sorted(failures.items())
        },
    }
    _write_json(output_dir / "decision.json", decision)
    _write_report(output_dir, decision=decision, rows=rows)
    _write_artifact_hashes(output_dir, repo_root)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--instance-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        postprocess(
            run_dir=args.run_dir,
            repo_root=args.repo_root,
            instance_path=args.instance_json,
            output_dir=args.output_dir,
            expected_streams=EXPECTED_STREAMS,
        )
    except EvidenceError as exc:
        raise SystemExit(f"HALT: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
