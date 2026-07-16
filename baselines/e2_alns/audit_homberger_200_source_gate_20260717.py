#!/usr/bin/env python3
"""Freeze and audit the 12 Homberger-200 development instances.

This is a zero-search data-source gate.  It downloads only the official
instance archive and the instance-format documentation, then verifies the
selected files' structure.  It deliberately does not fetch, parse, or persist
best-known-solution values or routes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile


REPO = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = (
    REPO / "baselines/e2_alns/reference_snapshots/homberger_200_20260717"
)
DEFAULT_OUTPUT = REPO / "baselines/e2_alns/e2_homberger_200_source_gate_20260717_v2"
INSTANCE_URL = (
    "https://www.sintef.no/globalassets/project/top/vrptw/homberger/200/"
    "homberger_200_customer_instances.zip"
)
DOCUMENTATION_URL = "https://www.sintef.no/projectweb/top/vrptw/documentation2/"
LANDING_PAGE_URL = "https://www.sintef.no/projectweb/top/vrptw/200-customers/"
EXPECTED_ARCHIVE_SHA256 = "79092cc627135f370a6381b0c64afc8403e4d4ff74afa8808d28d208ac784571"
EXPECTED_DOCUMENTATION_SHA256 = "e4c08998ec0831d28e659584904d26adc6c7a088a8dbb47a446b6534fee812df"
SELECTED = (
    "C1_2_1",
    "C1_2_8",
    "C2_2_1",
    "C2_2_8",
    "R1_2_1",
    "R1_2_8",
    "R2_2_1",
    "R2_2_8",
    "RC1_2_1",
    "RC1_2_8",
    "RC2_2_1",
    "RC2_2_8",
)
EXPECTED_CAPACITY = {
    "C1": 200,
    "C2": 700,
    "R1": 200,
    "R2": 1000,
    "RC1": 200,
    "RC2": 1000,
}


class SourceGateError(RuntimeError):
    """Raised when an official source or instance violates the contract."""


@dataclass(frozen=True)
class Node:
    idx: int
    x: int
    y: int
    demand: int
    ready: int
    due: int
    service: int


@dataclass(frozen=True)
class ParsedInstance:
    name: str
    vehicle_limit: int
    capacity: int
    nodes: tuple[Node, ...]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
    )


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    fields = list(rows[0]) if rows else []
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, buffer.getvalue())


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ReSETP-source-audit/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def ensure_frozen_source(path: Path, url: str, expected_sha256: str, *, offline: bool) -> None:
    if not path.is_file():
        if offline:
            raise SourceGateError(f"offline source is missing: {path}")
        atomic_bytes(path, fetch(url))
    actual = sha256_path(path)
    if actual != expected_sha256:
        raise SourceGateError(f"source hash differs for {path.name}: {actual}")


def instance_class(name: str) -> str:
    for prefix in ("RC1", "RC2", "C1", "C2", "R1", "R2"):
        if name.startswith(f"{prefix}_"):
            return prefix
    raise SourceGateError(f"unexpected instance family: {name}")


def parse_instance(payload: bytes) -> ParsedInstance:
    text = payload.decode("ascii")
    nonempty = [line.strip() for line in text.splitlines() if line.strip()]
    if not nonempty:
        raise SourceGateError("empty instance")
    name = nonempty[0].upper()
    try:
        vehicle_index = nonempty.index("NUMBER     CAPACITY")
    except ValueError as exc:
        raise SourceGateError(f"vehicle header missing in {name}") from exc
    vehicle_fields = nonempty[vehicle_index + 1].split()
    if len(vehicle_fields) != 2:
        raise SourceGateError(f"invalid vehicle row in {name}")
    vehicle_limit, capacity = map(int, vehicle_fields)
    nodes: list[Node] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 7 or not all(field.lstrip("-").isdigit() for field in fields):
            continue
        nodes.append(Node(*map(int, fields)))
    return ParsedInstance(name, vehicle_limit, capacity, tuple(nodes))


def audit_instance(instance: ParsedInstance, payload: bytes, member: str) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    family = instance_class(instance.name)
    ids = [node.idx for node in instance.nodes]
    customers = [node for node in instance.nodes if node.idx != 0]
    duplicate_id_count = len(ids) - len(set(ids))
    expected_ids = set(range(201))
    ids_contiguous = set(ids) == expected_ids and duplicate_id_count == 0
    tw_order_violations = sum(node.ready > node.due for node in instance.nodes)
    negative_demand_count = sum(node.demand < 0 for node in instance.nodes)
    demand_exceeds_capacity_count = sum(node.demand > instance.capacity for node in customers)
    negative_service_count = sum(node.service < 0 for node in instance.nodes)
    depot_rows = [node for node in instance.nodes if node.idx == 0]
    if len(customers) != 200:
        failures.append(f"{instance.name}: expected 200 customers, got {len(customers)}")
    if len(instance.nodes) != 201:
        failures.append(f"{instance.name}: expected 201 nodes, got {len(instance.nodes)}")
    if not ids_contiguous:
        failures.append(f"{instance.name}: node ids are not exactly 0..200")
    if instance.vehicle_limit != 50:
        failures.append(f"{instance.name}: vehicle limit is {instance.vehicle_limit}, expected 50")
    if instance.capacity != EXPECTED_CAPACITY[family]:
        failures.append(
            f"{instance.name}: capacity is {instance.capacity}, expected {EXPECTED_CAPACITY[family]}"
        )
    if tw_order_violations:
        failures.append(f"{instance.name}: {tw_order_violations} ready/due violations")
    if negative_demand_count or demand_exceeds_capacity_count or negative_service_count:
        failures.append(f"{instance.name}: invalid demand or service values")
    if len(depot_rows) != 1 or depot_rows[0].demand != 0 or depot_rows[0].service != 0:
        failures.append(f"{instance.name}: invalid depot row")
    depot = depot_rows[0] if len(depot_rows) == 1 else Node(0, 0, 0, 0, 0, 0, 0)
    widths = [node.due - node.ready for node in customers]
    row = {
        "instance": instance.name,
        "class": family,
        "series_member": int(instance.name.rsplit("_", 1)[1]),
        "source_member": member,
        "source_member_sha256": sha256_bytes(payload),
        "node_count": len(instance.nodes),
        "customer_count": len(customers),
        "customer_id_min": min((node.idx for node in customers), default=-1),
        "customer_id_max": max((node.idx for node in customers), default=-1),
        "duplicate_id_count": duplicate_id_count,
        "ids_contiguous_0_200": int(ids_contiguous),
        "vehicle_limit": instance.vehicle_limit,
        "capacity": instance.capacity,
        "total_customer_demand": sum(node.demand for node in customers),
        "demand_min": min((node.demand for node in customers), default=-1),
        "demand_max": max((node.demand for node in customers), default=-1),
        "demand_exceeds_capacity_count": demand_exceeds_capacity_count,
        "depot_ready": depot.ready,
        "depot_due": depot.due,
        "customer_ready_min": min((node.ready for node in customers), default=-1),
        "customer_due_max": max((node.due for node in customers), default=-1),
        "customer_tw_width_min": min(widths, default=-1),
        "customer_tw_width_max": max(widths, default=-1),
        "customer_tw_width_mean": f"{sum(widths) / len(widths):.6f}" if widths else "",
        "tw_order_violation_count": tw_order_violations,
        "negative_demand_count": negative_demand_count,
        "negative_service_count": negative_service_count,
        "x_min": min((node.x for node in instance.nodes), default=0),
        "x_max": max((node.x for node in instance.nodes), default=0),
        "y_min": min((node.y for node in instance.nodes), default=0),
        "y_max": max((node.y for node in instance.nodes), default=0),
        "source_gate_pass": int(not failures),
        "search_evaluations": 0,
    }
    return row, failures


def remove_appledouble(root: Path) -> None:
    executable = shutil.which("dot_clean")
    if executable is not None and root.exists():
        subprocess.run([executable, "-m", str(root)], check=True, capture_output=True, text=True)


def appledouble_files(*roots: Path) -> list[str]:
    paths: list[str] = []
    for root in roots:
        if root.exists():
            paths.extend(str(path) for path in root.rglob("._*"))
    return sorted(paths)


def relative_artifact_name(path: Path, output: Path) -> str:
    try:
        return str(path.relative_to(output))
    except ValueError:
        return str(path.relative_to(REPO))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and any(path for path in args.output.iterdir() if not path.name.startswith("._")):
        raise SystemExit(f"refuse to overwrite non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    archive_path = args.snapshot / "homberger_200_customer_instances.zip"
    documentation_path = args.snapshot / "sintef_vrptw_documentation_20260717.html"
    ensure_frozen_source(archive_path, INSTANCE_URL, EXPECTED_ARCHIVE_SHA256, offline=args.offline)
    ensure_frozen_source(
        documentation_path,
        DOCUMENTATION_URL,
        EXPECTED_DOCUMENTATION_SHA256,
        offline=args.offline,
    )

    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    extracted_root = args.snapshot / "instances"
    with ZipFile(archive_path) as archive:
        text_members = [name for name in archive.namelist() if name.upper().endswith(".TXT")]
        members = {Path(name).name.upper(): name for name in text_members}
        if len(text_members) != 60 or len(members) != 60:
            failures.append(f"official archive should contain 60 unique TXT files, got {len(members)}")
        for requested in SELECTED:
            member = members.get(f"{requested}.TXT")
            if member is None:
                failures.append(f"missing selected member: {requested}.TXT")
                continue
            payload = archive.read(member)
            target = extracted_root / f"{requested}.TXT"
            if target.is_file() and target.read_bytes() != payload:
                failures.append(f"frozen extracted member differs: {requested}.TXT")
            else:
                atomic_bytes(target, payload)
            parsed = parse_instance(payload)
            if parsed.name != requested:
                failures.append(f"instance name mismatch: {parsed.name} != {requested}")
            row, row_failures = audit_instance(parsed, payload, member)
            rows.append(row)
            failures.extend(row_failures)

    class_counts = Counter(str(row["class"]) for row in rows)
    if dict(class_counts) != {family: 2 for family in ("C1", "C2", "R1", "R2", "RC1", "RC2")}:
        failures.append(f"selected class counts differ: {dict(class_counts)}")
    if len(rows) != 12 or len({row["instance"] for row in rows}) != 12:
        failures.append(f"expected 12 unique selected instances, got {len(rows)}")

    source_provenance = {
        "schema_version": "resetp.e2.homberger-200-source-provenance.v1",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "publisher": "SINTEF Transportation Optimization Portal",
        "landing_page_url": LANDING_PAGE_URL,
        "instance_archive_url": INSTANCE_URL,
        "documentation_url": DOCUMENTATION_URL,
        "instance_archive_sha256": sha256_path(archive_path),
        "documentation_sha256": sha256_path(documentation_path),
        "selected_instances": list(SELECTED),
        "contains_bks_values": False,
        "contains_detailed_solution_routes": False,
    }
    provenance_path = args.snapshot / "source_provenance.json"
    if provenance_path.is_file():
        frozen_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        comparable_frozen = {key: value for key, value in frozen_provenance.items() if key != "retrieved_at_utc"}
        comparable_current = {key: value for key, value in source_provenance.items() if key != "retrieved_at_utc"}
        if comparable_frozen != comparable_current:
            failures.append("frozen source provenance differs from the current contract")
    else:
        atomic_json(provenance_path, source_provenance)
    selected_manifest = {
            "schema_version": "resetp.e2.homberger-200-development-set.v1",
            "role": "algorithm-development-only",
            "instance_count": len(rows),
            "search_evaluations": 0,
            "bks_materialized": False,
            "instances": [
                {
                    "instance": row["instance"],
                    "class": row["class"],
                    "member_sha256": row["source_member_sha256"],
                    "customer_count": row["customer_count"],
                    "vehicle_limit": row["vehicle_limit"],
                    "capacity": row["capacity"],
                }
                for row in rows
            ],
        }
    manifest_path = args.snapshot / "selected_instance_manifest.json"
    if manifest_path.is_file():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != selected_manifest:
            failures.append("frozen selected-instance manifest differs from the current contract")
    else:
        atomic_json(manifest_path, selected_manifest)
    atomic_csv(args.output / "raw_runs.csv", rows)
    metadata = {
        "schema_version": "resetp.e2.homberger-200-zero-search-source-gate.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "freeze the 12-instance Homberger-200 ALNS development set",
        "source_snapshot": str(args.snapshot),
        "source_archive_sha256": sha256_path(archive_path),
        "documentation_sha256": sha256_path(documentation_path),
        "selected_instances": list(SELECTED),
        "class_counts": dict(class_counts),
        "search_performed": False,
        "search_evaluations": 0,
        "bks_materialized": False,
        "bks_or_solution_routes_available_to_development": False,
        "python": sys.version,
        "platform": platform.platform(),
    }
    atomic_json(args.output / "metadata.json", metadata)
    verdict = (
        "PASS_HOMBERGER_200_ZERO_SEARCH_SOURCE_GATE"
        if not failures
        else "FAIL_HOMBERGER_200_ZERO_SEARCH_SOURCE_GATE"
    )
    decision = {
        "verdict": verdict,
        "failures": failures,
        "instances_verified": len(rows),
        "classes_verified": dict(class_counts),
        "search_evaluations": 0,
        "bks_materialized": False,
        "formal_search_authorized": False,
        "next_gate": "E7 closeout and ALNS budget-closure tests before any Homberger development search",
    }
    atomic_json(args.output / "decision.json", decision)
    report = [
        "# Homberger 200客户开发集零搜索来源门",
        "",
        f"判定：`{verdict}`。",
        "",
        f"已从SINTEF官方压缩包核对 {len(rows)}/12 个预注册开发实例；路径搜索评价次数为0。",
        "每例均检查节点编号0--200、200个客户、车辆上限、分组容量、需求、服务时间和时间窗先后关系。",
        "冻结材料仅含实例原文与SINTEF格式说明，不保存BKS数值或详细解路线，避免开发阶段接触最终评价信息。",
        "这些实例只用于ALNS组件开发，不进入Solomon 56例最终测试主表。",
    ]
    if failures:
        report.extend(["", "## 失败项", "", *[f"- {item}" for item in failures]])
    atomic_text(args.output / "report.md", "\n".join(report) + "\n")

    remove_appledouble(args.snapshot)
    remove_appledouble(args.output)
    sidecars = appledouble_files(args.snapshot, args.output)
    if sidecars:
        decision["failures"].append(f"AppleDouble files remain: {len(sidecars)}")
        decision["verdict"] = "FAIL_HOMBERGER_200_ZERO_SEARCH_SOURCE_GATE"
        verdict = decision["verdict"]
        atomic_json(args.output / "decision.json", decision)

    artifacts_to_hash = [
        args.output / "metadata.json",
        args.output / "raw_runs.csv",
        args.output / "decision.json",
        args.output / "report.md",
        archive_path,
        documentation_path,
        args.snapshot / "source_provenance.json",
        args.snapshot / "selected_instance_manifest.json",
        *sorted(extracted_root.glob("*.TXT")),
        Path(__file__),
        REPO / "solver/tests/test_homberger_200_source_gate_20260717.py",
    ]
    artifacts = {
        relative_artifact_name(path, args.output): sha256_path(path)
        for path in artifacts_to_hash
        if path.is_file() and not path.name.startswith("._")
    }
    atomic_json(args.output / "artifact_hashes.json", artifacts)
    remove_appledouble(args.snapshot)
    remove_appledouble(args.output)
    final_sidecars = appledouble_files(args.snapshot, args.output)
    if final_sidecars:
        raise SourceGateError(f"AppleDouble cleanup failed: {len(final_sidecars)} files remain")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if verdict.startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
