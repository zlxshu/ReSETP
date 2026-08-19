"""Fail-closed loading of the registered enterprise ownership assignment."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


ASSIGNMENT_CONTRACT_ERROR = "ASSIGNMENT_CONTRACT_ERROR"
_REQUIRED_FIELDS = frozenset(
    {
        "instance_id",
        "customer_id",
        "enterprise_id",
        "enterprise_depot_osm",
        "rule_id",
    }
)


class AssignmentContractError(ValueError):
    """A typed failure for an invalid enterprise assignment input."""

    code = ASSIGNMENT_CONTRACT_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


@dataclass(frozen=True)
class EnterpriseAssignment:
    """The immutable, normalized ownership mapping consumed by a bundle."""

    customer_home_depot: Mapping[str, str]
    enterprise_by_customer: Mapping[str, str]
    source_path: str
    source_sha256: str
    normalized_mapping_sha256: str
    rule_ids: tuple[str, ...]


def normalize_enterprise_depot_id(source_identity: str) -> str:
    """Convert a registered ``way/<id>`` identity to the node identity."""

    value = str(source_identity).strip()
    prefix, separator, osm_id = value.partition("/")
    if prefix != "way" or not separator or not osm_id.isdigit():
        raise AssignmentContractError(
            f"enterprise depot identity is not way/<digits>: {value!r}"
        )
    return f"D_OSM_WAY_{osm_id}"


def load_enterprise_assignment(
    assignment_path: Path,
    nodes_path: Path,
    *,
    expected_instance_id: str,
    expected_customer_ids: Iterable[str],
) -> EnterpriseAssignment:
    """Load, validate, normalize, and hash one registered assignment file."""

    if not assignment_path.is_file():
        raise AssignmentContractError(
            f"assignment file is missing: {assignment_path}"
        )
    if not nodes_path.is_file():
        raise AssignmentContractError(f"nodes file is missing: {nodes_path}")

    expected_customers = {str(customer_id) for customer_id in expected_customer_ids}
    rows = _read_csv(assignment_path)
    if not rows:
        raise AssignmentContractError("assignment file has no customer rows")
    missing_fields = sorted(_REQUIRED_FIELDS.difference(rows[0]))
    if missing_fields:
        raise AssignmentContractError(
            "assignment file is missing fields: " + ", ".join(missing_fields)
        )

    node_by_id, depot_by_source_identity = _read_depot_nodes(nodes_path)
    home_by_customer: dict[str, str] = {}
    enterprise_by_customer: dict[str, str] = {}
    enterprise_depot: dict[str, str] = {}
    rule_ids: set[str] = set()
    for row in rows:
        instance_id = str(row.get("instance_id", "")).strip()
        customer_id = str(row.get("customer_id", "")).strip()
        enterprise_id = str(row.get("enterprise_id", "")).strip()
        source_identity = str(row.get("enterprise_depot_osm", "")).strip()
        rule_id = str(row.get("rule_id", "")).strip()
        if instance_id != expected_instance_id:
            raise AssignmentContractError(
                f"assignment instance mismatch for {customer_id!r}: "
                f"{instance_id!r} != {expected_instance_id!r}"
            )
        if not customer_id or customer_id in home_by_customer:
            raise AssignmentContractError(
                f"duplicate or empty customer_id: {customer_id!r}"
            )
        if not enterprise_id or not rule_id:
            raise AssignmentContractError(
                f"enterprise_id and rule_id are required for {customer_id!r}"
            )
        rule_ids.add(rule_id)
        normalized_depot_id = normalize_enterprise_depot_id(source_identity)
        node = node_by_id.get(normalized_depot_id)
        if node is None or depot_by_source_identity.get(source_identity) != node:
            raise AssignmentContractError(
                f"unknown enterprise depot identity {source_identity!r} "
                f"for {customer_id!r}"
            )
        previous_depot = enterprise_depot.setdefault(enterprise_id, normalized_depot_id)
        if previous_depot != normalized_depot_id:
            raise AssignmentContractError(
                f"enterprise {enterprise_id!r} maps to multiple depots"
            )
        home_by_customer[customer_id] = normalized_depot_id
        enterprise_by_customer[customer_id] = enterprise_id

    if set(home_by_customer) != expected_customers:
        missing = sorted(expected_customers.difference(home_by_customer))
        extra = sorted(set(home_by_customer).difference(expected_customers))
        raise AssignmentContractError(
            f"customer set disagrees; missing={missing}, extra={extra}"
        )

    normalized_payload = {
        "customer_home_depot": sorted(home_by_customer.items()),
        "enterprise_by_customer": sorted(enterprise_by_customer.items()),
    }
    normalized_hash = hashlib.sha256(
        json.dumps(
            normalized_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return EnterpriseAssignment(
        customer_home_depot=MappingProxyType(home_by_customer),
        enterprise_by_customer=MappingProxyType(enterprise_by_customer),
        source_path=str(assignment_path),
        source_sha256=_sha256(assignment_path),
        normalized_mapping_sha256=normalized_hash,
        rule_ids=tuple(sorted(rule_ids)),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise AssignmentContractError(f"cannot read {path}: {exc}") from exc


def _read_depot_nodes(
    path: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    rows = _read_csv(path)
    by_id: dict[str, dict[str, str]] = {}
    by_source_identity: dict[str, dict[str, str]] = {}
    for row in rows:
        node_id = str(row.get("node_id", "")).strip()
        source_identity = str(row.get("source_identity", "")).strip()
        node_type = str(row.get("node_type", "")).strip().lower()
        if not node_id or node_id in by_id:
            raise AssignmentContractError(f"duplicate or empty node_id: {node_id!r}")
        if node_type != "depot" or not source_identity:
            continue
        if source_identity in by_source_identity:
            raise AssignmentContractError(
                f"duplicate depot source_identity: {source_identity!r}"
            )
        by_id[node_id] = row
        by_source_identity[source_identity] = row
    return by_id, by_source_identity


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
