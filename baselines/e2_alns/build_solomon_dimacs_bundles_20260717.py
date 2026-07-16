#!/usr/bin/env python3
"""Build and verify ReSETP bundles for the frozen Solomon/DIMACS test set.

This script performs no route construction or optimisation.  It only converts
the audited source data and proves that the generic ReSETP bundle loader sees
the same nodes, fleet cap, time windows, service times, and truncated distance
matrix.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
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

AUDIT_PATH = REPO / "baselines/e2_alns/audit_solomon_dimacs_adapter_20260717.py"
SPEC = importlib.util.spec_from_file_location("solomon_dimacs_audit", AUDIT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {AUDIT_PATH}")
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


DEFAULT_ZIP = Path("/Volumes/移动硬盘（512G）/VRP/算例/solomon-100.zip")
DEFAULT_REFERENCE = REPO / "baselines/e2_alns/e2_solomon_dimacs_adapter_20260717/raw_runs.csv"
DEFAULT_OUTPUT = REPO / "baselines/e2_alns/solomon_dimacs_formal_bundles_20260717"
FILES = ("instance.json", "distance_matrix.npy", "carbon_profile.csv")
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
    atomic_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def reference_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = {row["instance"]: row for row in csv.DictReader(handle)}
    if len(rows) != 56:
        raise RuntimeError(f"expected 56 audited references, found {len(rows)}")
    if any(row["official_byte_equal"] != "1" or row["node_structure_ok"] != "1" for row in rows.values()):
        raise RuntimeError("source adapter audit is not fully passed")
    return rows


def source_members(archive: ZipFile) -> dict[str, str]:
    return {
        Path(member).stem.upper(): member
        for member in archive.namelist()
        if member.lower().endswith(".txt")
    }


def matrix(nodes: list[Any]) -> np.ndarray:
    return np.asarray(
        [[AUDIT.truncated_distance(left, right) for right in nodes] for left in nodes],
        dtype=np.float64,
    )


def bundle_payload(name: str, max_vehicles: int, capacity: int, nodes: list[Any]) -> dict[str, Any]:
    return {
        "schema_version": "resetp.solomon-dimacs-vrptw.v1",
        "metadata": {
            "source_instance": name,
            "source_family": "Solomon 100-customer VRPTW",
            "scoring_contract": "12th DIMACS VRPTW track",
            "objective": "total_distance_only",
            "distance_rule": "floor(10*euclidean)/10",
            "time_unit": "Solomon/DIMACS abstract time unit",
            "distance_unit": "Solomon/DIMACS abstract distance unit",
            "num_cv": max_vehicles,
            "num_ev": 0,
            "vehicle_capacity": capacity,
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
    if any(path.iterdir()):
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
    carbon = (
        "time_index,datetime_utc,actual_gco2_per_kwh,forecast_gco2_per_kwh,"
        "index_label,index_code,horizon_second_start\n"
        "0,2026-07-17T00:00:00Z,0,0,not_applicable,0,0\n"
    )
    atomic_text(path / "carbon_profile.csv", carbon)


def verify_bundle(path: Path, max_vehicles: int, nodes: list[Any], distances: np.ndarray) -> list[str]:
    failures: list[str] = []
    loaded = load_search_bundle(path).instance
    if loaded.num_cv != max_vehicles or loaded.num_ev != 0:
        failures.append(f"fleet cap differs: cv={loaded.num_cv}, ev={loaded.num_ev}")
    if len(loaded.nodes) != len(nodes):
        failures.append(f"node count differs: {len(loaded.nodes)} != {len(nodes)}")
        return failures
    for raw, converted in zip(nodes, loaded.nodes):
        expected_id = "D0" if raw.idx == 0 else f"C{raw.idx}"
        expected_type = "d" if raw.idx == 0 else "c"
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
        expected = (
            expected_id,
            expected_type,
            float(raw.x),
            float(raw.y),
            float(raw.demand),
            float(raw.ready),
            float(raw.due),
            float(raw.service),
        )
        if actual != expected:
            failures.append(f"node {raw.idx} differs: {actual} != {expected}")
    loaded_matrix = np.asarray(loaded.distance_matrix, dtype=float)
    if loaded_matrix.shape != distances.shape or not np.allclose(loaded_matrix, distances, atol=TOL, rtol=0):
        failures.append("distance matrix differs after generic bundle loading")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    refs = reference_rows(args.reference)
    args.output.mkdir(parents=True, exist_ok=True)
    visible = [path for path in args.output.iterdir() if not path.name.startswith("._")]
    if visible:
        raise RuntimeError(f"refuse to overwrite non-empty output root: {args.output}")

    rows: list[dict[str, Any]] = []
    all_failures: list[str] = []
    with ZipFile(args.zip) as archive:
        members = source_members(archive)
        for name in sorted(refs):
            data = archive.read(members[name])
            parsed_name, max_vehicles, capacity, nodes = AUDIT.parse_instance(data)
            if parsed_name != name:
                raise RuntimeError(f"source name mismatch: {parsed_name} != {name}")
            distances = matrix(nodes)
            path = args.output / name
            write_bundle(path, bundle_payload(name, max_vehicles, capacity, nodes), distances)
            failures = verify_bundle(path, max_vehicles, nodes, distances)
            if failures:
                all_failures.extend(f"{name}: {failure}" for failure in failures)
            row = {
                "instance": name,
                "class": refs[name]["class"],
                "customers": len(nodes) - 1,
                "max_vehicles": max_vehicles,
                "capacity": capacity,
                "reference_value": refs[name]["reference_value"],
                "optimal_flag": refs[name]["optimal_flag"],
                "source_instance_sha256": refs[name]["instance_sha256"],
                "source_distance_matrix_sha256": refs[name]["distance_matrix_sha256"],
                "bundle_instance_sha256": sha256(path / "instance.json"),
                "bundle_matrix_sha256": sha256(path / "distance_matrix.npy"),
                "bundle_carbon_sha256": sha256(path / "carbon_profile.csv"),
                "generic_loader_match": int(not failures),
                "search_evaluations": 0,
            }
            rows.append(row)

    manifest = {
        "schema_version": "resetp.e2.solomon-dimacs-bundles.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_zip": str(args.zip),
        "source_zip_sha256": sha256(args.zip),
        "source_audit_csv": str(args.reference.relative_to(REPO)),
        "source_audit_csv_sha256": sha256(args.reference),
        "builder_sha256": sha256(Path(__file__)),
        "bundle_count": len(rows),
        "all_generic_loader_matches": not all_failures,
        "search_performed": False,
        "failures": all_failures,
        "rows": rows,
    }
    atomic_json(args.output / "manifest.json", manifest)
    verdict = "PASS_SOLOMON_DIMACS_BUNDLE_GATE" if not all_failures and len(rows) == 56 else "FAIL_SOLOMON_DIMACS_BUNDLE_GATE"
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
    print(json.dumps({"verdict": verdict, "bundle_count": len(rows), "failures": all_failures}, ensure_ascii=False, indent=2))
    return 0 if verdict.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
