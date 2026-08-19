"""Read the shared Pi0 manifest used by private experiment runners.

declared_identity=PROJECT_ADAPTER
code_role=THIN_ADAPTER
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .mapping_identity import mapping_sha256


def load_pi0_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Validate and return the instance records in a Pi0 v1 manifest."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "resetp.formal_pi0.v1":
        raise ValueError("Pi0 manifest schema must be resetp.formal_pi0.v1")
    instances = payload.get("instances")
    if not isinstance(instances, dict):
        raise ValueError("Pi0 manifest requires an instances object")
    parsed: dict[str, dict[str, Any]] = {}
    for instance_id, record in instances.items():
        if not isinstance(record, dict) or not isinstance(
            record.get("values"), dict
        ):
            raise ValueError(f"Pi0 record is malformed: {instance_id}")
        values = {
            str(key): float(value)
            for key, value in record["values"].items()
        }
        if not values or any(
            not math.isfinite(value) or value <= 0.0
            for value in values.values()
        ):
            raise ValueError(f"Pi0 values must be positive: {instance_id}")
        value_sha256 = mapping_sha256(values)
        declared = record.get("value_sha256")
        if declared is not None and str(declared).lower() != value_sha256:
            raise ValueError(f"Pi0 value hash mismatch: {instance_id}")
        source_id = str(record.get("source_id", "")).strip()
        if not source_id:
            raise ValueError(f"Pi0 source_id is required: {instance_id}")
        package_hashes = _package_hashes(record, str(instance_id))
        run_kind = str(record.get("run_kind", "formal"))
        if run_kind not in {"formal", "probe"}:
            raise ValueError(f"Pi0 run_kind is invalid: {instance_id}")
        externally_frozen = bool(record.get("externally_frozen", True))
        formal_reuse_allowed = bool(
            record.get(
                "formal_reuse_allowed",
                run_kind == "formal" and externally_frozen,
            )
        )
        if formal_reuse_allowed and not externally_frozen:
            raise ValueError(
                "formal Pi0 reuse requires an externally frozen input: "
                f"{instance_id}"
            )
        parsed[str(instance_id)] = {
            "values": values,
            "value_sha256": value_sha256,
            "source_id": source_id,
            "selected_package_sha256_by_enterprise": package_hashes,
            "run_kind": run_kind,
            "externally_frozen": externally_frozen,
            "formal_reuse_allowed": formal_reuse_allowed,
        }
    return parsed


def _package_hashes(
    record: dict[str, Any],
    instance_id: str,
) -> dict[str, str] | None:
    raw = record.get("selected_package_sha256_by_enterprise")
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"ENT_A", "ENT_B"}:
        raise ValueError(
            "Pi0 selected package hashes must cover ENT_A and ENT_B exactly: "
            f"{instance_id}"
        )
    parsed = {str(key): str(value).lower() for key, value in raw.items()}
    if any(
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in parsed.values()
    ):
        raise ValueError(f"Pi0 selected package hash is invalid: {instance_id}")
    return parsed
