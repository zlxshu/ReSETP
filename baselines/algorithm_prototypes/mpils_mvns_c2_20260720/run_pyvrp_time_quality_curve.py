#!/usr/bin/env python3
"""Run the frozen PyVRP V13 mother time-quality diagnostic."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
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
    / "docs/handoff/pyvrp_v13_time_quality_curve_contract_20260720.md"
)
PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
FOUNDATION = (
    REPO
    / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
)
INSTANCE_ROOT = FOUNDATION / "sources/normalised_instances"
TARGETS = FOUNDATION / "opponent_targets.csv"
OUTPUT = (
    REPO
    / "baselines/algorithm_foundation/"
    "pyvrp_v13_time_quality_curve_20260720"
)
INSTANCES = ("PR11B", "PR17B", "PR21B")
RUNTIMES = (8.5, 60.0, 300.0)
SEED = 1


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
        routes[vehicle] = [int(client) for client in record["visits"]]
    return routes


def load_bks() -> dict[str, int]:
    with TARGETS.open(encoding="utf-8", newline="") as stream:
        rows = csv.DictReader(stream)
        return {
            row["instance"]: int(
                round(float(row["current_verified_bks"]) * 1000)
            )
            for row in rows
            if row["instance"] in INSTANCES
        }


def run_one(
    instance: Path,
    runtime: float,
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
        str(runtime),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=runtime + 90,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"{instance.stem}/{runtime}s failed: "
            f"stdout={completed.stdout} stderr={completed.stderr}"
        )
    return json.loads(completed.stdout), elapsed


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUTPUT}")
    if git("status", "--porcelain"):
        raise RuntimeError("diagnostic must start from a clean commit")

    started = datetime.now(timezone.utc)
    run_dir = OUTPUT / "runs"
    run_dir.mkdir(parents=True)
    bks = load_bks()
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
        normalised = parse_normalised(
            instance.read_text(encoding="utf-8")
        )
        for runtime in RUNTIMES:
            output, wall_seconds = run_one(instance, runtime, env)
            label = str(runtime).replace(".", "p")
            write_json(run_dir / f"{name}__{label}s.json", output)
            independent = validate_solution_independently(
                normalised,
                assign_routes_to_vehicles(normalised, output["routes"]),
                int(output["distance"]),
            )
            objective = int(output["cost"])
            target = bks[name]
            rows.append(
                {
                    "instance": name,
                    "seed": SEED,
                    "runtime_budget_seconds": runtime,
                    "objective": objective,
                    "bks": target,
                    "gap_percent": 100 * (objective - target) / target,
                    "iterations": int(output["iterations_completed"]),
                    "solver_runtime_seconds": float(output["runtime_seconds"]),
                    "end_to_end_seconds": wall_seconds,
                    "complete": str(output["complete"]).lower(),
                    "feasible": str(output["feasible"]).lower(),
                    "independent_valid": str(
                        independent["all_checks_pass"]
                    ).lower(),
                }
            )

    with (OUTPUT / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    valid = all(
        row["complete"] == "true"
        and row["feasible"] == "true"
        and row["independent_valid"] == "true"
        for row in rows
    )
    curves: dict[str, Any] = {}
    both_improve = 0
    late_flat = 0
    for name in INSTANCES:
        points = sorted(
            (row for row in rows if row["instance"] == name),
            key=lambda row: float(row["runtime_budget_seconds"]),
        )
        costs = [int(point["objective"]) for point in points]
        target = bks[name]
        first_gain = costs[0] - costs[1]
        second_gain = costs[1] - costs[2]
        both_improve += int(first_gain > 0 and second_gain > 0)
        late_flat += int(second_gain <= 0)
        initial_excess = costs[0] - target
        curves[name] = {
            "objectives": costs,
            "gaps_percent": [
                float(point["gap_percent"]) for point in points
            ],
            "gain_8p5_to_60": first_gain,
            "gain_60_to_300": second_gain,
            "initial_bks_excess": initial_excess,
            "closed_initial_gap_fraction_at_300": (
                (costs[0] - costs[2]) / initial_excess
                if initial_excess > 0
                else None
            ),
        }

    if not valid:
        verdict = "HALT_INVALID_TIME_QUALITY_DIAGNOSTIC"
    elif both_improve == len(INSTANCES):
        verdict = "TIME_CONTINUES_HELPING_ALL_THREE"
    elif late_flat >= 2:
        verdict = "PLATEAU_SIGNAL_AT_FIVE_MINUTES"
    else:
        verdict = "MIXED_TIME_HEADROOM_SIGNAL"

    decision = {
        "verdict": verdict,
        "all_solutions_independently_valid": valid,
        "curves": curves,
        "algorithm_change_made": False,
        "parameter_tuning_made": False,
        "full_v13_authorized": False,
        "china81_authorized": False,
    }
    write_json(OUTPUT / "decision.json", decision)
    metadata = {
        "contract": "PYVRP-V13-TIME-QUALITY-CURVE",
        "contract_path": CONTRACT.relative_to(REPO).as_posix(),
        "contract_sha256": sha256_file(CONTRACT),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git("rev-parse", "HEAD"),
        "host": {
            "platform": platform.platform(),
            "solver_python": str(PYTHON.relative_to(REPO)),
        },
        "input": {
            "instances": list(INSTANCES),
            "instance_hashes": {
                name: sha256_file(INSTANCE_ROOT / f"{name}.vrp")
                for name in INSTANCES
            },
            "seed": SEED,
            "runtime_seconds": list(RUNTIMES),
            "arm": "unmodified_pyvrp_0.13.4_ils_only",
        },
        "counts": {
            "mother_runs": len(rows),
            "candidate_runs": 0,
            "full_v13_runs": 0,
            "china81_runs": 0,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)

    table = "\n".join(
        "|{instance}|{runtime_budget_seconds:g}|{objective}|"
        "{gap_percent:.3f}%|{iterations}|{end_to_end_seconds:.3f}|"
        "{independent_valid}|".format(**row)
        for row in rows
    )
    report = f"""# PyVRP V13 原装母体时间—质量曲线

判定：`{verdict}`。

|题|预算秒|目标值|距BKS|迭代|端到端秒|独立有效|
|---|---:|---:|---:|---:|---:|---|
{table}

本门只运行原装 PyVRP 0.13.4 ILS 默认参数，没有算法改动或参数扫描。
结论只用于判断时间增加是否继续带来质量改善，不是正式 V13-28 结果，也不授权
China81、C2、阶段二或论文优胜主张。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(
        OUTPUT / "artifact_hashes.json",
        build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if valid else 3


if __name__ == "__main__":
    raise SystemExit(main())
