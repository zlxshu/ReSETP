#!/usr/bin/env python3
"""Check whether blind Homberger-200 development tasks still have short-run headroom."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from typing import Any


BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
GATE_PATH = BASE / "run_route_core_microgate.py"
SPEC = importlib.util.spec_from_file_location("route_core_gate", GATE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {GATE_PATH}")
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)

BUNDLE_GATE = REPO / "baselines/e2_alns/homberger_headroom_blind_bundles_20260719"
BUNDLES = BUNDLE_GATE / "bundles"
OUT = BASE / "homberger_headroom_audit"
SHORT_SECONDS = 2.0
LONG_SECONDS = 10.0
TOL = 1e-8


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
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def run_instance(name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = GATE.HELPERS.bundle_contract(name)
    initial = GATE.HELPERS.deterministic_common_initial_solution(
        contract["bundle"].instance,
        capacity=contract["capacity"],
    )
    rows = []
    for seconds, label in (
        (SHORT_SECONDS, "pyvrp_hgs_short"),
        (LONG_SECONDS, "pyvrp_hgs_long"),
    ):
        row, _ = GATE.run_external(
            name=name,
            algorithm=label,
            python=GATE.PY_HGS,
            seconds=seconds,
            contract=contract,
            initial=initial,
        )
        rows.append(row)
    short, long = rows
    short_key = (int(short["route_count"]), float(short["distance_double"]))
    long_key = (int(long["route_count"]), float(long["distance_double"]))
    headroom = long_key[0] < short_key[0] or (
        long_key[0] == short_key[0] and long_key[1] < short_key[1] - TOL
    )
    comparison = {
        "instance": name,
        "short_route_count": short_key[0],
        "short_distance": short_key[1],
        "long_route_count": long_key[0],
        "long_distance": long_key[1],
        "strict_headroom": headroom,
        "short_elapsed_seconds": float(short["elapsed_seconds"]),
        "long_elapsed_seconds": float(long["elapsed_seconds"]),
        "both_feasible": short["status"] == "OK" and long["status"] == "OK",
    }
    return rows, comparison


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refuse to overwrite non-empty output: {OUT}")
    bundle_decision = json.loads(
        (BUNDLE_GATE / "decision.json").read_text(encoding="utf-8")
    )
    if bundle_decision.get("verdict") != "PASS_BLIND_HEADROOM_BUNDLES_READY":
        raise RuntimeError("blind bundle gate is not passed")
    instances = list(bundle_decision["selected_instances"])
    GATE.BUNDLES = BUNDLES
    GATE.HELPERS.BUNDLES = BUNDLES
    GATE.OUT = OUT

    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(instances)) as executor:
        for instance_rows, comparison in executor.map(run_instance, instances):
            rows.extend(instance_rows)
            comparisons.append(comparison)

    failures = [
        f"{row['instance']}:{row['algorithm']}"
        for row in rows
        if row["status"] != "OK"
    ]
    headroom_count = sum(item["strict_headroom"] for item in comparisons)
    decision = {
        "verdict": (
            "GO_ROUTE_POOL_EXACT_RECOMBINATION_MICROGATE"
            if not failures and headroom_count >= 3
            else "STOP_SHORT_HOMBERGER_STRICT_WIN_PURSUIT"
        ),
        "strict_headroom_instance_count": headroom_count,
        "minimum_headroom_instances": 3,
        "failures": failures,
        "bks_read": False,
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.homberger-headroom-audit.v1",
        "instances": instances,
        "seed": GATE.SEED,
        "short_seconds": SHORT_SECONDS,
        "long_seconds": LONG_SECONDS,
        "single_thread_per_task": True,
        "parallel_tasks": len(instances),
        "selection_gate_sha256": sha256(BUNDLE_GATE / "decision.json"),
        "selection_was_results_blind": True,
        "bks_read": False,
        "purpose": (
            "Diagnose whether a strict-win development gate has room to improve; "
            "not an algorithm comparison."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "comparisons.json", comparisons)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# Homberger-200短时改进空间审计\n\n"
        f"判定：`{decision['verdict']}`。六个按源文件哈希结果盲选的新开发题中，"
        f"纯HGS从{SHORT_SECONDS:g}秒延长到{LONG_SECONDS:g}秒后有"
        f"{headroom_count}/6题按“先车辆数、再距离”严格改善。"
        "本包只回答是否存在可赢空间，不比较候选算法，也不读取BKS。\n",
    )
    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
