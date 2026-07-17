#!/usr/bin/env python3
"""Freeze the local PyVRP 0.13.4 API with a tiny non-Solomon probe.

This is a tool-compatibility check, not a paper benchmark.  It builds one
three-client synthetic VRPTW, verifies the route and statistics interfaces,
and writes auditable evidence.  No Solomon bundle or BKS file is opened.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import importlib.util
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pyvrp import Model
from pyvrp.stop import MaxIterations


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v3"
PROBE = Path(__file__).resolve()
ADAPTER = REPO / "baselines/e2_alns/run_solomon_external_strong_baselines_20260717.py"
WHEEL = (
    REPO
    / "baselines/e2_alns/external_tools/pyvrp-0.13.4/"
    "pyvrp-0.13.4-cp313-cp313-macosx_11_0_arm64.whl"
)
EXPECTED_VERSION = "0.13.4"
EXPECTED_WHEEL_SHA256 = "49b84319fcfcd2206c05f55e970d090ab054d577a1d82cbac276d376fe89970c"
EXPECTED_PYTHON = Path("/Users/zhouleixishu/.codex/runtimes/resetp-pyvrp-0.13.4/bin/python")
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
SCHEMA = "resetp.e2.pyvrp-0.13.4-tool-probe.v1"


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
    atomic_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, buffer.getvalue())


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("pyvrp_0134_probe_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the external-baseline adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def installed_statistics_source() -> Path:
    spec = importlib.util.find_spec("pyvrp.Statistics")
    if spec is None or spec.origin is None:
        raise RuntimeError("cannot locate pyvrp.Statistics source")
    return Path(spec.origin).resolve()


def build_probe_model() -> Model:
    model = Model()
    depot = model.add_depot(x=0, y=0, tw_early=0, tw_late=1000, name="D")
    clients = [
        model.add_client(
            x=x,
            y=y,
            delivery=1,
            service_duration=0,
            tw_early=0,
            tw_late=1000,
            name=str(idx),
        )
        for idx, (x, y) in enumerate(((1, 0), (2, 0), (3, 0)), start=1)
    ]
    model.add_vehicle_type(
        num_available=2,
        capacity=3,
        start_depot=depot,
        end_depot=depot,
        fixed_cost=100,
    )
    locations = [depot, *clients]
    for i, frm in enumerate(locations):
        for j, to in enumerate(locations):
            model.add_edge(frm, to, distance=abs(i - j), duration=abs(i - j))
    return model


def solve_through_bundle_adapter(adapter: Any) -> Any:
    """Exercise the exact old-API branch used by the formal bundle adapter."""

    nodes = [
        {
            "node_id": "D",
            "x": 0.0,
            "y": 0.0,
            "demand": 0,
            "ready_time": 0.0,
            "due_time": 1000.0,
            "service_time": 0.0,
        },
        *[
            {
                "node_id": str(idx),
                "x": float(idx),
                "y": 0.0,
                "demand": 1,
                "ready_time": 0.0,
                "due_time": 1000.0,
                "service_time": 0.0,
            }
            for idx in range(1, 4)
        ],
    ]
    distances = np.abs(np.arange(4)[:, None] - np.arange(4)[None, :]).astype(float)
    payload = {"metadata": {"vehicle_capacity": 3, "num_cv": 2}, "nodes": nodes}
    with tempfile.TemporaryDirectory(prefix="resetp-pyvrp-probe-") as raw:
        bundle = Path(raw)
        (bundle / "instance.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        np.save(bundle / "distance_matrix.npy", distances, allow_pickle=False)
        model = adapter.build_pyvrp_model(bundle, scale=1000, fixed_cost=100000)
        return model.solve(stop=MaxIterations(20), seed=1, display=False, collect_stats=True)


def check_rows() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], str]:
    adapter = load_adapter()
    version = importlib.metadata.version("pyvrp")
    wheel_hash = sha256(WHEEL) if WHEEL.is_file() else ""
    thread_values = {name: os.environ.get(name, "") for name in THREAD_ENV}
    executable = Path(sys.executable).resolve()
    statistics_source = installed_statistics_source()

    model = build_probe_model()
    result = model.solve(stop=MaxIterations(20), seed=1, display=False, collect_stats=True)
    routes = adapter.extract_routes(result.best)
    time_to_best = float(adapter.extract_time_to_best(result))
    runtimes = [float(value) for value in result.stats.runtimes]
    runtime_sum = sum(runtimes)
    result_runtime = float(result.runtime)
    adapter_result = solve_through_bundle_adapter(adapter)
    adapter_routes = adapter.extract_routes(adapter_result.best)
    adapter_time_to_best = float(adapter.extract_time_to_best(adapter_result))

    checks = {
        "exact_version": version == EXPECTED_VERSION,
        "exact_python": executable == EXPECTED_PYTHON.resolve(),
        "official_wheel_hash": wheel_hash == EXPECTED_WHEEL_SHA256,
        "single_thread_environment": all(value == "1" for value in thread_values.values()),
        "old_model_api_detected": not hasattr(model, "add_location"),
        "synthetic_solution_feasible": bool(result.best.is_feasible()),
        "synthetic_route_complete": sorted(value for route in routes for value in route) == [1, 2, 3],
        "synthetic_objective_exact": int(result.cost()) == 106,
        "statistics_lengths_match": (
            len(result.stats.data) == len(runtimes) == int(result.stats.num_iterations) == 20
        ),
        "runtime_deltas_nonnegative": all(value >= 0.0 for value in runtimes),
        "runtime_sum_matches_result": abs(runtime_sum - result_runtime) <= max(1e-5, result_runtime * 0.05),
        "time_to_best_in_runtime": 0.0 <= time_to_best <= runtime_sum + 1e-9,
        "bundle_adapter_solution_feasible": bool(adapter_result.best.is_feasible()),
        "bundle_adapter_route_complete": (
            sorted(value for route in adapter_routes for value in route) == [1, 2, 3]
        ),
        "bundle_adapter_objective_exact": int(adapter_result.cost()) == 106000,
        "bundle_adapter_time_to_best_valid": (
            0.0 <= adapter_time_to_best <= float(adapter_result.runtime) + 1e-5
        ),
    }
    rows = [
        {
            "check": name,
            "passed": passed,
            "formal_solomon_search_evaluations": 0,
            "synthetic_probe_iterations": 40,
        }
        for name, passed in checks.items()
    ]
    failures = [name for name, passed in checks.items() if not passed]
    metadata = {
        "schema_version": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_only": True,
        "formal_search_authorized": False,
        "formal_solomon_search_evaluations": 0,
        "synthetic_probe_client_count": 3,
        "synthetic_probe_iterations": 40,
        "pyvrp_version": version,
        "python_executable": str(executable),
        "python_version": sys.version,
        "wheel_path": str(WHEEL.relative_to(REPO)),
        "wheel_sha256": wheel_hash,
        "adapter_path": str(ADAPTER.relative_to(REPO)),
        "adapter_sha256": sha256(ADAPTER),
        "probe_path": str(PROBE.relative_to(REPO)),
        "probe_sha256": sha256(PROBE),
        "statistics_source_path": str(statistics_source),
        "statistics_source_sha256": sha256(statistics_source),
        "thread_environment": thread_values,
        "model_api_signatures": {
            name: str(inspect.signature(getattr(model, name)))
            for name in ("add_depot", "add_client", "add_vehicle_type", "add_edge", "solve")
        },
        "statistics_layout": {
            "num_iterations": int(result.stats.num_iterations),
            "data_count": len(result.stats.data),
            "runtime_delta_count": len(runtimes),
            "runtime_delta_sum_seconds": runtime_sum,
            "result_runtime_seconds": result_runtime,
            "time_to_best_seconds": time_to_best,
        },
        "synthetic_result": {
            "objective": int(result.cost()),
            "routes": routes,
            "feasible": bool(result.best.is_feasible()),
        },
        "bundle_adapter_result": {
            "objective": int(adapter_result.cost()),
            "routes": adapter_routes,
            "feasible": bool(adapter_result.best.is_feasible()),
            "runtime_seconds": float(adapter_result.runtime),
            "time_to_best_seconds": adapter_time_to_best,
        },
    }
    decision = {
        "verdict": "PASS_PYVRP_0134_CANDIDATE_TOOL_PROBE" if not failures else "HALT_PYVRP_0134_TOOL_PROBE",
        "failures": failures,
        "formal_search_authorized": False,
        "formal_solomon_search_evaluations": 0,
        "time_to_best_extractor_verified": not failures,
    }
    freeze = subprocess.run(
        [str(executable), "-m", "pip", "freeze", "--all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return metadata, rows, decision, freeze


def write_evidence(
    metadata: dict[str, Any],
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
    freeze: str,
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if any(item for item in OUT.iterdir() if not item.name.startswith("._")):
        raise RuntimeError(f"refuse to overwrite non-empty output: {OUT}")
    atomic_json(OUT / "metadata.json", metadata)
    atomic_csv(OUT / "raw_runs.csv", rows)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(OUT / "environment_freeze.txt", freeze)
    atomic_text(
        OUT / "report.md",
        "# PyVRP 0.13.4 候选工具探针\n\n"
        f"判定：`{decision['verdict']}`。本探针只用一个3客户合成硬时间窗实例分别核验"
        "原生API与正式bundle适配器，"
        "没有读取Solomon算例或BKS，也没有授权正式搜索。\n\n"
        "已核对官方wheel哈希、独立Python环境、单线程变量、0.13.4建模API、路线读取、"
        "统计点与逐迭代耗时增量、bundle建模分支，并验证Tbest必须由耗时增量累加后取得。"
        "该证据只把PyVRP固定为候选外部强基线；E7步骤1—6证明和最终工具冻结完成前，"
        "正式Solomon搜索仍被禁止。\n",
    )
    subprocess.run(["dot_clean", "-m", str(OUT)], check=True)
    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    subprocess.run(["dot_clean", "-m", str(OUT)], check=True)
    if list(OUT.rglob("._*")):
        raise RuntimeError("AppleDouble sidecars remain")


def main() -> int:
    metadata, rows, decision, freeze = check_rows()
    write_evidence(metadata, rows, decision, freeze)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if decision["verdict"] == "PASS_PYVRP_0134_CANDIDATE_TOOL_PROBE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
