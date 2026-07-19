#!/usr/bin/env python3
"""Measure one A-group mother batch and derive the single revised W."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
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
WORKER = HERE / "run_g1_worker.py"
CONTRACT = (
    REPO
    / "docs/handoff/"
    "mpils_mvns_c2_a_constant_diagnosis_contract_20260720.md"
)
PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
INSTANCE_ROOT = (
    REPO
    / "baselines/algorithm_foundation/"
    "mdvrptw_v13_comparison_20260719/"
    "sources/normalised_instances"
)
OUTPUT = (
    REPO
    / "baselines/algorithm_foundation/"
    "mpils_mvns_c2_a_constant_diagnosis_20260720"
)
INSTANCES = ("PR11A", "PR17A", "PR21A")
SEED = 1
RUNTIME_SECONDS = 8.5
END_TO_END_LIMIT_SECONDS = 10.0


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


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
        vehicle = available[depot][position]
        used[depot] += 1
        routes[vehicle] = [
            int(client) for client in record["visits"]
        ]
    return routes


def run_mother(
    instance: Path,
    env: dict[str, str],
) -> tuple[dict[str, Any], float]:
    command = [
        str(PYTHON),
        str(WORKER),
        "--algorithm",
        "mother",
        "--instance",
        str(instance),
        "--seed",
        str(SEED),
        "--runtime",
        str(RUNTIME_SECONDS),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=END_TO_END_LIMIT_SECONDS + 15,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"{instance.stem}/mother failed: "
            f"stdout={completed.stdout} stderr={completed.stderr}"
        )
    return json.loads(completed.stdout), elapsed


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUTPUT}")
    if git("status", "--porcelain"):
        raise RuntimeError("diagnosis must start from a clean commit")

    started = datetime.now(timezone.utc)
    run_dir = OUTPUT / "runs"
    run_dir.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": str(SEED),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    rows: list[dict[str, Any]] = []
    for name in INSTANCES:
        instance = INSTANCE_ROOT / f"{name}.vrp"
        output, wall_seconds = run_mother(instance, env)
        write_json(run_dir / f"{name}__mother.json", output)
        normalised = parse_normalised(
            instance.read_text(encoding="utf-8")
        )
        independent = validate_solution_independently(
            normalised,
            assign_routes_to_vehicles(
                normalised,
                output["routes"],
            ),
            int(output["distance"]),
        )
        rows.append(
            {
                "instance": name,
                "seed": SEED,
                "objective": int(output["cost"]),
                "iterations": int(output["iterations_completed"]),
                "runtime_seconds": float(output["runtime_seconds"]),
                "end_to_end_seconds": wall_seconds,
                "complete": str(output["complete"]).lower(),
                "feasible": str(output["feasible"]).lower(),
                "independent_valid": str(
                    independent["all_checks_pass"]
                ).lower(),
            }
        )

    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    iteration_values = [int(row["iterations"]) for row in rows]
    median_iterations = int(statistics.median(iteration_values))
    revised_w = int(round(0.15 * median_iterations))
    all_valid = all(
        row["complete"] == "true"
        and row["feasible"] == "true"
        and row["independent_valid"] == "true"
        for row in rows
    )
    all_within_time = all(
        float(row["end_to_end_seconds"]) <= END_TO_END_LIMIT_SECONDS
        for row in rows
    )
    passed = all_valid and all_within_time and revised_w > 128
    verdict = (
        "PASS_A_CONSTANT_DIAGNOSIS__ONE_W_REVISION_ALLOWED"
        if passed
        else "STOP_A_CONSTANT_DIAGNOSIS_INVALID"
    )
    decision = {
        "verdict": verdict,
        "iteration_values": iteration_values,
        "median_iterations": median_iterations,
        "frozen_formula": "round(0.15 * median_iterations)",
        "revised_trigger_after": revised_w,
        "revised_cooldown": revised_w,
        "strength_rule_changed": False,
        "all_solutions_independently_valid": all_valid,
        "all_end_to_end_wall_times_within_10_seconds": all_within_time,
        "b_group_second_fire_authorized": passed,
        "additional_parameter_sweeps_authorized": False,
    }
    write_json(OUTPUT / "decision.json", decision)
    metadata = {
        "contract": "MPILS-MVNS-C2-A-CONSTANT-DIAGNOSIS",
        "contract_path": CONTRACT.relative_to(REPO).as_posix(),
        "contract_sha256": sha256_file(CONTRACT),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git("rev-parse", "HEAD"),
        "host": {
            "platform": platform.platform(),
            "runner_python": platform.python_version(),
            "solver_python": str(PYTHON.relative_to(REPO)),
            "pyvrp": version("pyvrp"),
        },
        "input": {
            "instances": list(INSTANCES),
            "instance_hashes": {
                name: sha256_file(INSTANCE_ROOT / f"{name}.vrp")
                for name in INSTANCES
            },
            "seed": SEED,
            "runtime_seconds": RUNTIME_SECONDS,
            "arm": "mother_only",
        },
        "counts": {
            "mother_runs": len(rows),
            "candidate_runs": 0,
            "b_group_runs": 0,
            "confirmation_runs": 0,
            "china81_runs": 0,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)
    table = "\n".join(
        "|{instance}|{objective}|{iterations}|{end_to_end_seconds:.3f}|"
        "{independent_valid}|".format(**row)
        for row in rows
    )
    report = f"""# MPILS-MVNS-C2 A组一次常数诊断

判定：`{verdict}`。

|题|母体目标值|8.5秒迭代|端到端秒|独立有效|
|---|---:|---:|---:|---|
{table}

三题迭代中位数为 `{median_iterations}`。按运行前冻结公式
`round(0.15 × 中位迭代数)`，唯一修订常数为 `W={revised_w}`；
第二发的 `trigger_after` 与 `cooldown` 同时取该值。没有运行候选、B组、确认题或
China81，没有测试多个W，也没有修改强度规则。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(
        OUTPUT / "artifact_hashes.json",
        build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
