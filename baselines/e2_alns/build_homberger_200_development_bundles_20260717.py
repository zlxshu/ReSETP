#!/usr/bin/env python3
"""Build zero-search ReSETP bundles for the frozen Homberger-200 development set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

SOURCE_AUDIT_PATH = REPO / "baselines/e2_alns/audit_homberger_200_source_gate_20260717.py"
SPEC = importlib.util.spec_from_file_location("homberger_source_audit", SOURCE_AUDIT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {SOURCE_AUDIT_PATH}")
SOURCE_AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SOURCE_AUDIT
SPEC.loader.exec_module(SOURCE_AUDIT)

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


DEFAULT_SNAPSHOT = REPO / "baselines/e2_alns/reference_snapshots/homberger_200_20260717"
DEFAULT_SOURCE_GATE = REPO / "baselines/e2_alns/e2_homberger_200_source_gate_20260717_v2"
DEFAULT_OUTPUT = REPO / "baselines/e2_alns/homberger_200_development_bundles_20260717"
TOL = 1e-12


class BundleGateError(RuntimeError):
    """Raised when the frozen source or generated development bundle drifts."""


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
        temporary.unlink(missing_ok=True)


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


def verify_source_gate(source_gate: Path, snapshot: Path) -> dict[str, Any]:
    decision_path = source_gate / "decision.json"
    manifest_path = snapshot / "selected_instance_manifest.json"
    if not decision_path.is_file() or not manifest_path.is_file():
        raise BundleGateError("Homberger source-gate records are missing")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if decision.get("verdict") != "PASS_HOMBERGER_200_ZERO_SEARCH_SOURCE_GATE":
        raise BundleGateError("Homberger source gate is not passed")
    if decision.get("search_evaluations") != 0:
        raise BundleGateError("Homberger source gate is not zero-search")
    if manifest.get("bks_materialized") is not False:
        raise BundleGateError("development-source manifest contains reference results")
    instances = manifest.get("instances")
    if not isinstance(instances, list) or len(instances) != len(SOURCE_AUDIT.SELECTED):
        raise BundleGateError("development-source manifest is incomplete")
    if {row.get("instance") for row in instances} != set(SOURCE_AUDIT.SELECTED):
        raise BundleGateError("development-source instance identity differs")
    return manifest


def distance_matrix(nodes: tuple[Any, ...]) -> np.ndarray:
    return np.asarray(
        [[math.hypot(left.x - right.x, left.y - right.y) for right in nodes] for left in nodes],
        dtype=np.float64,
    )


def bundle_payload(instance: Any) -> dict[str, Any]:
    return {
        "schema_version": "resetp.homberger-200-vrptw-development.v1",
        "metadata": {
            "source_instance": instance.name,
            "source_family": "Gehring-Homberger 200-customer VRPTW",
            "role": "algorithm-development-only",
            "objective": ["minimize_vehicle_count", "then_minimize_total_distance"],
            "distance_rule": "double_precision_euclidean",
            "num_cv": instance.vehicle_limit,
            "num_ev": 0,
            "vehicle_capacity": instance.capacity,
            "time_unit": "benchmark abstract time unit",
            "distance_unit": "benchmark abstract distance unit",
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
            for node in instance.nodes
        ],
    }


def write_bundle(path: Path, payload: dict[str, Any], matrix: np.ndarray) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(item for item in path.iterdir() if not item.name.startswith("._")):
        raise BundleGateError(f"refuse to overwrite non-empty bundle: {path}")
    atomic_json(path / "instance.json", payload)
    temporary = path / f".distance_matrix.npy.tmp-{os.getpid()}"
    try:
        with temporary.open("wb") as handle:
            np.save(handle, matrix)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path / "distance_matrix.npy")
    finally:
        temporary.unlink(missing_ok=True)
    atomic_text(
        path / "carbon_profile.csv",
        "time_index,datetime_utc,actual_gco2_per_kwh,forecast_gco2_per_kwh,index_label,index_code,horizon_second_start\n"
        "0,2026-07-17T00:00:00Z,0,0,not_applicable,0,0\n",
    )


def verify_bundle(path: Path, instance: Any, expected_matrix: np.ndarray) -> list[str]:
    failures: list[str] = []
    raw = json.loads((path / "instance.json").read_text(encoding="utf-8"))
    if "bks" in json.dumps(raw, ensure_ascii=False).lower():
        failures.append("search-facing bundle contains forbidden reference-result token")
    loaded = load_search_bundle(path).instance
    if loaded.num_cv != instance.vehicle_limit or loaded.num_ev != 0:
        failures.append("fleet differs after generic loading")
    if len(loaded.nodes) != 201:
        failures.append(f"node count differs after generic loading: {len(loaded.nodes)}")
        return failures
    for source, converted in zip(instance.nodes, loaded.nodes, strict=True):
        expected = (
            "D0" if source.idx == 0 else f"C{source.idx}",
            "d" if source.idx == 0 else "c",
            float(source.x),
            float(source.y),
            float(source.demand),
            float(source.ready),
            float(source.due),
            float(source.service),
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
            failures.append(f"node {source.idx} differs after generic loading")
    loaded_matrix = np.asarray(loaded.distance_matrix, dtype=np.float64)
    if loaded_matrix.shape != expected_matrix.shape or not np.allclose(
        loaded_matrix, expected_matrix, atol=TOL, rtol=0
    ):
        failures.append("double-precision distance matrix differs after generic loading")
    return failures


def build(snapshot: Path, source_gate: Path, output: Path) -> dict[str, Any]:
    manifest = verify_source_gate(source_gate, snapshot)
    output.mkdir(parents=True, exist_ok=True)
    if any(item for item in output.iterdir() if not item.name.startswith("._")):
        raise BundleGateError(f"refuse to overwrite non-empty output root: {output}")

    source_rows = {row["instance"]: row for row in manifest["instances"]}
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for name in SOURCE_AUDIT.SELECTED:
        source_path = snapshot / "instances" / f"{name}.TXT"
        if not source_path.is_file() or sha256(source_path) != source_rows[name]["member_sha256"]:
            raise BundleGateError(f"frozen source differs: {name}")
        instance = SOURCE_AUDIT.parse_instance(source_path.read_bytes())
        source_audit_row, source_failures = SOURCE_AUDIT.audit_instance(
            instance, source_path.read_bytes(), f"instances/{name}.TXT"
        )
        if source_failures:
            failures.extend(source_failures)
        matrix = distance_matrix(instance.nodes)
        bundle = output / name
        write_bundle(bundle, bundle_payload(instance), matrix)
        bundle_failures = verify_bundle(bundle, instance, matrix)
        failures.extend(f"{name}: {failure}" for failure in bundle_failures)
        rows.append(
            {
                "instance": name,
                "class": SOURCE_AUDIT.instance_class(name),
                "customers": 200,
                "max_vehicles": instance.vehicle_limit,
                "capacity": instance.capacity,
                "source_sha256": sha256(source_path),
                "bundle_instance_sha256": sha256(bundle / "instance.json"),
                "bundle_matrix_sha256": sha256(bundle / "distance_matrix.npy"),
                "bundle_carbon_sha256": sha256(bundle / "carbon_profile.csv"),
                "source_gate_pass": int(not source_failures),
                "generic_loader_match": int(not bundle_failures),
                "search_evaluations": 0,
            }
        )

    verdict = (
        "PASS_HOMBERGER_200_DEVELOPMENT_BUNDLE_GATE"
        if not failures and len(rows) == len(SOURCE_AUDIT.SELECTED)
        else "FAIL_HOMBERGER_200_DEVELOPMENT_BUNDLE_GATE"
    )
    root_manifest = {
        "schema_version": "resetp.e2.homberger-200-development-bundles.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "role": "algorithm-development-only",
        "source_gate": str(source_gate.relative_to(REPO)),
        "source_gate_decision_sha256": sha256(source_gate / "decision.json"),
        "selected_instance_manifest_sha256": sha256(snapshot / "selected_instance_manifest.json"),
        "builder_sha256": sha256(Path(__file__)),
        "bundle_count": len(rows),
        "search_performed": False,
        "search_evaluations": 0,
        "reference_results_materialized": False,
        "objective": ["minimize vehicle count", "then minimize double-precision total distance"],
        "failures": failures,
        "rows": rows,
    }
    atomic_json(output / "manifest.json", root_manifest)
    atomic_csv(output / "raw_runs.csv", rows)
    atomic_json(
        output / "metadata.json",
        {key: value for key, value in root_manifest.items() if key not in {"rows", "failures"}}
        | {"failures": failures},
    )
    atomic_json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failures": failures,
            "bundle_count": len(rows),
            "formal_search_authorized": False,
            "search_evaluations": 0,
            "next_gate": "E7 closeout and ALNS G0 before Homberger G1 development search",
        },
    )
    atomic_text(
        output / "report.md",
        "# Homberger 200客户开发bundle适配门\n\n"
        f"判定：`{verdict}`。12个预注册开发实例已转换为双精度通用bundle并由项目加载器逐字段回读；"
        "搜索评价为0，搜索可读文件不含公开参考结果。该开发集只用于G1/G2算法开发，不能进入Solomon最终测试表。\n",
    )
    subprocess.run(["dot_clean", "-m", str(output)], check=True)
    if list(output.rglob("._*")):
        raise BundleGateError("AppleDouble remains before artifact manifest")
    artifacts = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    artifacts[str(Path(__file__).relative_to(REPO))] = sha256(Path(__file__))
    artifacts[str((source_gate / "decision.json").relative_to(REPO))] = sha256(
        source_gate / "decision.json"
    )
    artifacts[str((snapshot / "selected_instance_manifest.json").relative_to(REPO))] = sha256(
        snapshot / "selected_instance_manifest.json"
    )
    atomic_json(output / "artifact_hashes.json", artifacts)
    subprocess.run(["dot_clean", "-m", str(output)], check=True)
    if list(output.rglob("._*")):
        raise BundleGateError("AppleDouble remains after artifact manifest")
    return {"verdict": verdict, "bundle_count": len(rows), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--source-gate", type=Path, default=DEFAULT_SOURCE_GATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build(args.snapshot, args.source_gate, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["verdict"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
