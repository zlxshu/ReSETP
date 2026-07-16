#!/usr/bin/env python3
"""Build zero-search double-precision bundles for the SINTEF Solomon test set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

AUDIT_PATH = REPO / "baselines/e2_alns/audit_solomon_sintef_bks_20260717.py"
SPEC = importlib.util.spec_from_file_location("solomon_sintef_audit", AUDIT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {AUDIT_PATH}")
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


DEFAULT_ZIP = Path("/Volumes/移动硬盘（512G）/VRP/算例/solomon-100.zip")
DEFAULT_REFERENCE = REPO / "baselines/e2_alns/e2_solomon_sintef_bks_audit_20260717/raw_runs.csv"
DEFAULT_OUTPUT = REPO / "baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3"
TOL = 1e-12


def sha256(path: Path) -> str:
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


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    fields = list(rows[0]) if rows else []
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, buffer.getvalue())


def reference_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = {row["instance"]: row for row in csv.DictReader(handle)}
    if len(rows) != 56:
        raise RuntimeError(f"expected 56 audited SINTEF references, found {len(rows)}")
    if any(
        row["vehicle_match"] != "1"
        or row["distance_match"] != "1"
        or row["solution_feasible"] != "1"
        or row["search_evaluations"] != "0"
        for row in rows.values()
    ):
        raise RuntimeError("SINTEF BKS source audit is not fully passed")
    return rows


def source_members(archive: ZipFile) -> dict[str, str]:
    return {
        Path(member).stem.upper(): member
        for member in archive.namelist()
        if member.lower().endswith(".txt")
    }


def double_precision_matrix(nodes: list[Any]) -> np.ndarray:
    return np.asarray(
        [[math.hypot(left.x - right.x, left.y - right.y) for right in nodes] for left in nodes],
        dtype=np.float64,
    )


def bundle_payload(
    name: str,
    max_vehicles: int,
    capacity: int,
    nodes: list[Any],
) -> dict[str, Any]:
    return {
        "schema_version": "resetp.solomon-sintef-vrptw.v1",
        "metadata": {
            "source_instance": name,
            "source_family": "Solomon 100-customer VRPTW",
            "scoring_contract": "SINTEF hierarchical Solomon benchmark",
            "objective": ["minimize_vehicle_count", "then_minimize_total_distance"],
            "distance_rule": "double_precision_euclidean",
            "distance_reporting": "round total to two decimals",
            "num_cv": max_vehicles,
            "num_ev": 0,
            "vehicle_capacity": capacity,
            "time_unit": "Solomon abstract time unit",
            "distance_unit": "Solomon abstract distance unit",
        },
        "nodes": [
            {
                "node_id": "D0" if node.idx == 0 else f"C{node.idx}",
                "node_type": "d" if node.idx == 0 else "c",
                "x": node.x,
                "y": node.y,
                "demand": node.demand,
                "ready_time": node.ready,
                "due_time": node.due,
                "service_time": node.service,
            }
            for node in nodes
        ],
    }


def write_bundle(path: Path, payload: dict[str, Any], distances: np.ndarray) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(item for item in path.iterdir() if not item.name.startswith("._")):
        raise RuntimeError(f"refuse to overwrite non-empty bundle: {path}")
    atomic_json(path / "instance.json", payload)
    temporary = path / f".distance_matrix.npy.tmp-{os.getpid()}"
    try:
        with temporary.open("wb") as handle:
            np.save(handle, distances)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path / "distance_matrix.npy")
    finally:
        if temporary.exists():
            temporary.unlink()
    atomic_text(
        path / "carbon_profile.csv",
        "time_index,datetime_utc,actual_gco2_per_kwh,forecast_gco2_per_kwh,index_label,index_code,horizon_second_start\n"
        "0,2026-07-17T00:00:00Z,0,0,not_applicable,0,0\n",
    )


def verify_bundle(
    path: Path,
    max_vehicles: int,
    capacity: int,
    nodes: list[Any],
    distances: np.ndarray,
    reference: dict[str, str],
) -> list[str]:
    failures: list[str] = []
    raw = json.loads((path / "instance.json").read_text(encoding="utf-8"))
    loaded = load_search_bundle(path).instance
    metadata = raw["metadata"]
    if loaded.num_cv != max_vehicles or loaded.num_ev != 0:
        failures.append(f"fleet cap differs: cv={loaded.num_cv}, ev={loaded.num_ev}")
    if float(metadata["vehicle_capacity"]) != float(capacity):
        failures.append("capacity metadata differs")
    forbidden_bks_fields = {"bks_vehicle_count", "bks_distance", "bks_reference_code"} & set(metadata)
    if forbidden_bks_fields:
        failures.append(f"search-facing bundle leaks BKS fields: {sorted(forbidden_bks_fields)}")
    if len(loaded.nodes) != len(nodes):
        failures.append(f"node count differs: {len(loaded.nodes)} != {len(nodes)}")
        return failures
    for raw_node, converted in zip(nodes, loaded.nodes):
        expected = (
            "D0" if raw_node.idx == 0 else f"C{raw_node.idx}",
            "d" if raw_node.idx == 0 else "c",
            float(raw_node.x),
            float(raw_node.y),
            float(raw_node.demand),
            float(raw_node.ready),
            float(raw_node.due),
            float(raw_node.service),
        )
        actual = (
            converted.node_id,
            converted.node_type,
            converted.x,
            converted.y,
            converted.demand,
            converted.ready_time,
            converted.due_time,
            converted.service_time,
        )
        if actual != expected:
            failures.append(f"node {raw_node.idx} differs: {actual} != {expected}")
    loaded_matrix = np.asarray(loaded.distance_matrix, dtype=float)
    if loaded_matrix.shape != distances.shape or not np.allclose(loaded_matrix, distances, atol=TOL, rtol=0):
        failures.append("double-precision distance matrix differs after generic loading")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    refs = reference_rows(args.reference)
    args.output.mkdir(parents=True, exist_ok=True)
    if any(item for item in args.output.iterdir() if not item.name.startswith("._")):
        raise RuntimeError(f"refuse to overwrite non-empty output root: {args.output}")

    rows: list[dict[str, Any]] = []
    all_failures: list[str] = []
    with ZipFile(args.zip) as archive:
        members = source_members(archive)
        for name in sorted(refs):
            parsed_name, max_vehicles, capacity, node_map = AUDIT.parse_instance(archive.read(members[name]))
            if parsed_name != name:
                raise RuntimeError(f"source name mismatch: {parsed_name} != {name}")
            nodes = [node_map[idx] for idx in sorted(node_map)]
            distances = double_precision_matrix(nodes)
            path = args.output / name
            payload = bundle_payload(name, max_vehicles, capacity, nodes)
            write_bundle(path, payload, distances)
            failures = verify_bundle(path, max_vehicles, capacity, nodes, distances, refs[name])
            if failures:
                all_failures.extend(f"{name}: {failure}" for failure in failures)
            rows.append(
                {
                    "instance": name,
                    "class": refs[name]["class"],
                    "customers": len(nodes) - 1,
                    "max_vehicles": max_vehicles,
                    "capacity": capacity,
                    "bks_vehicles": int(refs[name]["bks_vehicles"]),
                    "bks_distance": float(refs[name]["bks_distance"]),
                    "bks_reference_code": refs[name]["reference_code"],
                    "source_solution_sha256": refs[name]["solution_sha256"],
                    "bundle_instance_sha256": sha256(path / "instance.json"),
                    "bundle_matrix_sha256": sha256(path / "distance_matrix.npy"),
                    "bundle_carbon_sha256": sha256(path / "carbon_profile.csv"),
                    "generic_loader_match": int(not failures),
                    "search_evaluations": 0,
                }
            )

    manifest = {
        "schema_version": "resetp.e2.solomon-sintef-bundles.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_zip": str(args.zip),
        "source_zip_sha256": sha256(args.zip),
        "source_audit_csv": str(args.reference.relative_to(REPO)),
        "source_audit_csv_sha256": sha256(args.reference),
        "builder_sha256": sha256(Path(__file__)),
        "bundle_count": len(rows),
        "all_generic_loader_matches": not all_failures,
        "search_performed": False,
        "objective": ["minimize vehicle count", "then minimize double-precision total distance"],
        "search_facing_bundles_contain_bks": False,
        "failures": all_failures,
        "rows": rows,
    }
    atomic_json(args.output / "manifest.json", manifest)
    atomic_csv(args.output / "raw_runs.csv", rows)
    atomic_json(
        args.output / "metadata.json",
        {
            key: value
            for key, value in manifest.items()
            if key not in {"rows", "failures"}
        }
        | {"failures": all_failures},
    )
    verdict = "PASS_SOLOMON_SINTEF_BUNDLE_GATE" if not all_failures and len(rows) == 56 else "FAIL_SOLOMON_SINTEF_BUNDLE_GATE"
    atomic_json(
        args.output / "decision.json",
        {
            "verdict": verdict,
            "bundle_count": len(rows),
            "search_evaluations": 0,
            "formal_search_authorized": False,
            "failures": all_failures,
        },
    )
    report = [
        "# Solomon/SINTEF双精度算例包适配门",
        "",
        f"判定：`{verdict}`。",
        "",
        f"共生成并经通用加载器复核{len(rows)}个100客户算例包；搜索评价次数为0。",
        "距离矩阵为双精度欧氏距离；目标元数据明确为先最少车辆、再最短距离。",
        "BKS只保存在根目录审计表与manifest中；搜索可读的instance.json不含车辆数、距离、参考代码或详细路线。",
    ]
    if all_failures:
        report.extend(["", "## 失败项", "", *[f"- {item}" for item in all_failures]])
    atomic_text(args.output / "report.md", "\n".join(report) + "\n")
    artifacts = {
        str(path.relative_to(args.output)): sha256(path)
        for path in sorted(args.output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    artifacts[str(Path(__file__).relative_to(REPO))] = sha256(Path(__file__))
    atomic_json(args.output / "artifact_hashes.json", artifacts)
    print(json.dumps({"verdict": verdict, "bundle_count": len(rows), "failures": all_failures}, ensure_ascii=False, indent=2))
    return 0 if verdict.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
