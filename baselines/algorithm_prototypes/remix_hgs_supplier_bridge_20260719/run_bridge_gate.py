#!/usr/bin/env python3
"""Run and independently audit the ReMIX HGS supplier bridge."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyvrp
from pyvrp import Route, Solution


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.freeze_mdvrptw_v13_foundation_20260719 import (  # noqa: E402
    build_hash_manifest,
    parse_normalised,
    validate_solution_independently,
    write_json,
)


HERE = Path(__file__).resolve().parent
HGS_WORKER = HERE / "hgs_supplier_worker.py"
HGS_PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
INSTANCE = (
    REPO
    / "baselines/algorithm_foundation/"
    "mdvrptw_v13_comparison_20260719/"
    "sources/normalised_instances/PR17A.vrp"
)
OUTPUT = (
    REPO
    / "baselines/algorithm_foundation/"
    "remix_hgs_supplier_bridge_v2_20260719"
)
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assign_routes_to_vehicles(
    normalised: Any,
    route_records: list[dict[str, Any]],
) -> dict[int, list[int]]:
    routes = {
        vehicle: []
        for vehicle in range(1, normalised.num_vehicles + 1)
    }
    available: dict[int, list[int]] = {}
    for vehicle, depot in normalised.vehicle_depots.items():
        available.setdefault(depot - 1, []).append(vehicle)
    used = {depot: 0 for depot in available}
    for record in route_records:
        depot = int(record["start_depot"])
        position = used[depot]
        if position >= len(available[depot]):
            raise ValueError("HGS supplier exceeds vehicle availability")
        vehicle = available[depot][position]
        used[depot] += 1
        routes[vehicle] = [int(client) for client in record["visits"]]
    return routes


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite HGS bridge evidence: {OUTPUT / filename}"
            )
    started = datetime.now(timezone.utc)
    protected_before = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": "1",
        }
    )
    completed = subprocess.run(
        [
            str(HGS_PYTHON),
            str(HGS_WORKER),
            "--instance",
            str(INSTANCE),
            "--seed",
            "1",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"HGS supplier failed: {completed.stdout} {completed.stderr}"
        )
    supplier = json.loads(completed.stdout)
    data = pyvrp.read(INSTANCE, round_func="exact")
    rebuilt = Solution(
        data,
        [
            Route(
                data,
                record["visits"],
                int(record["vehicle_type"]),
            )
            for record in supplier["routes"]
        ],
    )
    rebuilt_routes = [
        {
            "vehicle_type": route.vehicle_type(),
            "start_depot": route.start_depot(),
            "end_depot": route.end_depot(),
            "visits": list(route.visits()),
            "distance": route.distance(),
            "duration": route.duration(),
            "feasible": route.is_feasible(),
        }
        for route in rebuilt.routes()
    ]
    normalised = parse_normalised(INSTANCE.read_text(encoding="utf-8"))
    independent = validate_solution_independently(
        normalised,
        assign_routes_to_vehicles(normalised, rebuilt_routes),
        rebuilt.distance(),
    )
    route_identity = sorted(
        (
            int(record["vehicle_type"]),
            tuple(int(client) for client in record["visits"]),
        )
        for record in supplier["routes"]
    ) == sorted(
        (
            int(record["vehicle_type"]),
            tuple(int(client) for client in record["visits"]),
        )
        for record in rebuilt_routes
    )
    distance_identity = supplier["distance"] == rebuilt.distance()
    complete_feasible = (
        supplier["complete"]
        and supplier["feasible"]
        and rebuilt.is_complete()
        and rebuilt.is_feasible()
        and independent["all_checks_pass"]
    )
    protected_after = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    passed = (
        route_identity
        and distance_identity
        and complete_feasible
        and protected_before == protected_after
    )
    verdict = (
        "PASS_REMIX_HGS_SUPPLIER_BRIDGE"
        if passed
        else "FAIL_REMIX_HGS_SUPPLIER_BRIDGE"
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    runs = OUTPUT / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    write_json(runs / "hgs_0122.json", supplier)
    write_json(
        runs / "rebuilt_0134.json",
        {
            "pyvrp_version": version("pyvrp"),
            "round_func": "exact",
            "complete": rebuilt.is_complete(),
            "feasible": rebuilt.is_feasible(),
            "distance": rebuilt.distance(),
            "num_clients": rebuilt.num_clients(),
            "num_routes": rebuilt.num_routes(),
            "routes": rebuilt_routes,
            "independent_validation": independent,
        },
    )
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "source_version",
                "target_version",
                "seed",
                "iterations_completed",
                "source_distance",
                "target_distance",
                "route_identity",
                "complete_feasible",
                "independent_valid",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "source_version": "0.12.2",
                "target_version": version("pyvrp"),
                "seed": 1,
                "iterations_completed": supplier["iterations_completed"],
                "source_distance": supplier["distance"],
                "target_distance": rebuilt.distance(),
                "route_identity": str(route_identity).lower(),
                "complete_feasible": str(complete_feasible).lower(),
                "independent_valid": str(
                    independent["all_checks_pass"]
                ).lower(),
            }
        )
    decision = {
        "verdict": verdict,
        "route_identity": route_identity,
        "distance_identity": distance_identity,
        "source_and_target_complete_feasible": complete_feasible,
        "independent_validation_pass": independent["all_checks_pass"],
        "protected_files_unchanged": protected_before == protected_after,
        "hgs_supplier_authorized_for_six_instance_development": passed,
        "performance_claim_allowed": False,
        "performance_search_calls": 0,
        "china81_authorized": False,
        "stage2_authorized": False,
    }
    write_json(OUTPUT / "decision.json", decision)
    metadata = {
        "contract": "REMIX-V13-DEV-001-PREREQUISITE-BRIDGE",
        "supersedes": (
            "baselines/algorithm_foundation/"
            "remix_hgs_supplier_bridge_20260719"
        ),
        "correction": (
            "v1 stopped after two iterations before first feasibility; "
            "v2 stops at first feasible solution or five seconds"
        ),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "runner_python": platform.python_version(),
            "source_pyvrp": supplier["pyvrp_version"],
            "target_pyvrp": version("pyvrp"),
        },
        "input": {
            "instance": INSTANCE.relative_to(REPO).as_posix(),
            "instance_sha256": sha256_file(INSTANCE),
            "seed": 1,
            "stop_rule": supplier["stop_rule"],
            "max_runtime_seconds": supplier["max_runtime_seconds"],
            "iterations_completed": supplier["iterations_completed"],
        },
        "counts": {
            "hgs_identity_bridge_calls": 1,
            "independent_validation_calls": 1,
            "performance_search_calls": 0,
            "china81_calls": 0,
        },
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    write_json(OUTPUT / "metadata.json", metadata)
    report = f"""# ReMIX HGS 供料桥

判定：`{verdict}`。

v1 在固定两次迭代时尚未找到可行解。本 v2 不调质量参数，只改为找到第一份可行解
即停，最多五秒，以回答路线桥本身是否成立。

- 0.12.2 与 0.13.4 路线逐条一致：`{route_identity}`。
- 重建前后整数距离一致：`{distance_identity}`。
- 两端完整可行且独立复算通过：`{complete_feasible}`。
- 保护文件未变化：`{protected_before == protected_after}`。

这里只证明 HGS 路线能无损进入共同路线库，不证明 HGS 或 ReMIX 的性能。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(OUTPUT / "artifact_hashes.json", build_hash_manifest(OUTPUT))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
