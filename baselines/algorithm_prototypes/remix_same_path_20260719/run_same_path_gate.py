#!/usr/bin/env python3
"""Run and audit the ReMIX disabled-path equivalence gate."""

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


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.freeze_mdvrptw_v13_foundation_20260719 import (  # noqa: E402
    build_hash_manifest,
    parse_normalised,
    validate_solution_independently,
    write_json,
)


HERE = Path(__file__).resolve().parent
WORKER = HERE / "same_path_worker.py"
INSTANCE = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mdvrptw_v13_comparison_20260719"
    / "sources"
    / "normalised_instances"
    / "PR11A.vrp"
)
OUTPUT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "remix_same_path_equivalence_gate_20260719"
)
MODES = ("mother", "hybrid_disabled", "hybrid_zero_budget")
SEED = 1
ITERATIONS = 5
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


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
    used: dict[int, int] = {depot: 0 for depot in available}
    for record in route_records:
        depot = int(record["start_depot"])
        if int(record["end_depot"]) != depot:
            raise ValueError("generated route starts and ends at different depots")
        position = used[depot]
        if position >= len(available[depot]):
            raise ValueError("generated solution exceeds depot vehicle availability")
        vehicle = available[depot][position]
        used[depot] += 1
        routes[vehicle] = [int(client) for client in record["visits"]]
    return routes


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite existing gate evidence: {OUTPUT / filename}"
            )
    if not INSTANCE.is_file():
        raise FileNotFoundError(INSTANCE)
    started = datetime.now(timezone.utc)
    run_dir = OUTPUT / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": str(SEED),
        }
    )

    outputs: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        completed = subprocess.run(
            [
                sys.executable,
                str(WORKER),
                "--mode",
                mode,
                "--instance",
                str(INSTANCE),
                "--seed",
                str(SEED),
                "--iterations",
                str(ITERATIONS),
            ],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{mode} failed: stdout={completed.stdout} "
                f"stderr={completed.stderr}"
            )
        output = json.loads(completed.stdout)
        outputs[mode] = output
        write_json(run_dir / f"{mode}.json", output)

    signatures = {
        mode: output["deterministic_signature_sha256"]
        for mode, output in outputs.items()
    }
    all_signatures_equal = len(set(signatures.values())) == 1
    all_component_calls_zero = all(
        output["component_counters"]["total_component_calls"] == 0
        for output in outputs.values()
    )
    all_input_hashes_equal = len(
        {output["instance_sha256"] for output in outputs.values()}
    ) == 1
    all_versions_equal = len(
        {output["pyvrp_version"] for output in outputs.values()}
    ) == 1

    normalised = parse_normalised(INSTANCE.read_text(encoding="utf-8"))
    independent_checks: dict[str, dict[str, Any]] = {}
    for mode, output in outputs.items():
        payload = output["deterministic_payload"]
        vehicle_routes = assign_routes_to_vehicles(
            normalised,
            payload["routes"],
        )
        independent = validate_solution_independently(
            normalised,
            vehicle_routes,
            int(payload["distance"]),
        )
        if not independent["all_checks_pass"]:
            raise ValueError(f"{mode}: independent validation failed")
        independent_checks[mode] = independent

    raw_rows = []
    for mode, output in outputs.items():
        payload = output["deterministic_payload"]
        raw_rows.append(
            {
                "mode": mode,
                "seed": SEED,
                "iterations": ITERATIONS,
                "cost": payload["cost"],
                "distance": payload["distance"],
                "duration": payload["duration"],
                "routes": payload["num_routes"],
                "clients": payload["num_clients"],
                "feasible": str(payload["feasible"]).lower(),
                "complete": str(payload["complete"]).lower(),
                "component_calls": output["component_counters"][
                    "total_component_calls"
                ],
                "deterministic_signature_sha256": output[
                    "deterministic_signature_sha256"
                ],
                "runtime_s_non_comparable": output[
                    "runtime_s_non_comparable"
                ],
                "independent_validation": str(
                    independent_checks[mode]["all_checks_pass"]
                ).lower(),
            }
        )
    write_csv(OUTPUT / "raw_runs.csv", raw_rows)

    passed = (
        all_signatures_equal
        and all_component_calls_zero
        and all_input_hashes_equal
        and all_versions_equal
        and all(
            check["all_checks_pass"]
            for check in independent_checks.values()
        )
    )
    decision = {
        "verdict": (
            "PASS_REMIX_SAME_PATH_EQUIVALENCE"
            if passed
            else "FAIL_REMIX_SAME_PATH_EQUIVALENCE"
        ),
        "all_deterministic_signatures_equal": all_signatures_equal,
        "all_component_calls_zero": all_component_calls_zero,
        "all_input_hashes_equal": all_input_hashes_equal,
        "all_pyvrp_versions_equal": all_versions_equal,
        "all_independent_validations_pass": all(
            check["all_checks_pass"]
            for check in independent_checks.values()
        ),
        "performance_claim_allowed": False,
        "performance_search_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
        "honest_boundary": (
            "This proves disabled-path identity only, not algorithm quality."
        ),
    }
    write_json(OUTPUT / "decision.json", decision)
    finished = datetime.now(timezone.utc)
    metadata = {
        "contract": "ALGO-COMPARE-FOUNDATION-003",
        "purpose": "disabled and zero-budget same-path equivalence",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pyvrp": version("pyvrp"),
        },
        "input": {
            "instance": INSTANCE.relative_to(REPO).as_posix(),
            "instance_sha256": hashlib.sha256(INSTANCE.read_bytes()).hexdigest(),
            "seed": SEED,
            "iterations": ITERATIONS,
            "modes": list(MODES),
        },
        "thread_limits": {
            key: env[key]
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "counts": {
            "solver_wiring_calls": len(MODES),
            "performance_search_calls": 0,
            "component_calls": sum(
                output["component_counters"]["total_component_calls"]
                for output in outputs.values()
            ),
            "china81_calls": 0,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)
    report = f"""# ReMIX 同路径接线门

判定：`{decision["verdict"]}`。

在 `PR11A`、seed={SEED}、固定 {ITERATIONS} 次迭代下，纯母体、混合增强关闭和
混合增强开启但预算为 0 三个独立进程得到相同的路线、成本和逐迭代记录；所有增强
调用均为 0，三份解均通过独立复算。

这只证明混合外壳关闭时不会污染 PyVRP 0.13.4 母体。它不证明算法更强，不授权
性能搜索、China81 或阶段二。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(OUTPUT / "artifact_hashes.json", build_hash_manifest(OUTPUT))
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
