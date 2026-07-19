#!/usr/bin/env python3
"""Freeze PyVRP 0.12.2 as a genuine HGS-era development tool.

This is an identity and API probe only. It opens no Solomon, Homberger,
China81, or E2--E7 experiment bundle.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from pyvrp import Model
from pyvrp.stop import MaxIterations


solve_module = importlib.import_module("pyvrp.solve")


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "baselines/e2_alns/pyvrp_hgs_0122_tool_freeze_20260719"
WHEEL = (
    REPO
    / "baselines/e2_alns/external_tools/pyvrp-0.12.2"
    / "pyvrp-0.12.2-cp313-cp313-macosx_11_0_arm64.whl"
)
EXPECTED_VERSION = "0.12.2"
EXPECTED_WHEEL_SHA256 = (
    "3725680fcb75dc4a424160460e5ba7e3a4ea9694ed4b3b196049047922d8f226"
)
EXPECTED_PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


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


def build_probe() -> Model:
    model = Model()
    depot = model.add_depot(x=0, y=0, tw_early=0, tw_late=1000, name="D")
    clients = [
        model.add_client(
            x=x,
            y=0,
            delivery=1,
            service_duration=0,
            tw_early=0,
            tw_late=1000,
            name=str(index),
        )
        for index, x in enumerate((1, 2, 3), start=1)
    ]
    model.add_vehicle_type(
        num_available=2,
        capacity=3,
        start_depot=depot,
        end_depot=depot,
        fixed_cost=100,
    )
    locations = [depot, *clients]
    for source_index, source in enumerate(locations):
        for target_index, target in enumerate(locations):
            distance = abs(source_index - target_index)
            model.add_edge(source, target, distance=distance, duration=distance)
    return model


def main() -> int:
    source = Path(inspect.getsourcefile(solve_module) or "").resolve()
    source_text = source.read_text(encoding="utf-8")
    version = importlib.metadata.version("pyvrp")
    executable = Path(sys.executable).resolve()
    thread_values = {name: os.environ.get(name, "") for name in THREAD_ENV}
    result = build_probe().solve(
        stop=MaxIterations(20),
        seed=1,
        display=False,
        collect_stats=True,
    )
    routes = [
        [int(client) for client in route]
        for route in result.best.routes()
    ]
    flattened = sorted(client for route in routes for client in route)
    checks = {
        "exact_version": version == EXPECTED_VERSION,
        "exact_python": executable == EXPECTED_PYTHON.resolve(),
        "official_wheel_hash": WHEEL.is_file()
        and sha256(WHEEL) == EXPECTED_WHEEL_SHA256,
        "single_thread_environment": all(
            value == "1" for value in thread_values.values()
        ),
        "genetic_algorithm_present": "GeneticAlgorithm" in source_text,
        "population_present": "Population" in source_text,
        "iterated_local_search_absent": "IteratedLocalSearch" not in source_text,
        "initial_solution_not_exposed": "initial_solution" not in str(
            inspect.signature(solve_module.solve)
        ),
        "synthetic_solution_feasible": bool(result.best.is_feasible()),
        "synthetic_route_complete": flattened == [1, 2, 3],
        "synthetic_objective_exact": int(result.cost()) == 106,
    }
    passed = all(checks.values())
    rows = [
        {
            "check": name,
            "passed": value,
            "formal_search_evaluations": 0,
            "synthetic_probe_iterations": 20,
        }
        for name, value in checks.items()
    ]
    metadata = {
        "schema_version": "resetp.pyvrp-hgs-0.12.2-tool-freeze.v1",
        "purpose": "development_tool_identity_only",
        "version": version,
        "python_executable": str(executable),
        "wheel": str(WHEEL.relative_to(REPO)),
        "wheel_sha256": sha256(WHEEL),
        "solve_source": str(source),
        "solve_source_sha256": sha256(source),
        "solve_signature": str(inspect.signature(solve_module.solve)),
        "thread_environment": thread_values,
        "synthetic_routes": routes,
        "synthetic_cost": int(result.cost()),
        "pip_freeze": subprocess.run(
            [str(executable), "-m", "pip", "freeze"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines(),
        "claim_boundary": (
            "This proves tool identity and a tiny API path only. "
            "It proves no algorithm performance."
        ),
    }
    decision = {
        "verdict": "PASS_GENUINE_HGS_TOOL_FREEZE" if passed else "FAIL_TOOL_FREEZE",
        "passed": passed,
        "checks": checks,
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / "metadata.json", metadata)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# PyVRP 0.12.2 HGS 工具冻结\n\n"
        + (
            "通过。这个独立环境里的 0.12.2 确实使用群体和遗传搜索，"
            "不是 0.13.4 的单一路线反复改进版本。小合成题可行且目标值精确。\n\n"
            if passed
            else "失败。至少一个身份、环境或小题检查未通过。\n\n"
        )
        + "边界：这里只证明工具身份和最小接口，不证明算法效果，也没有启动正式算例。\n",
    )
    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
