#!/usr/bin/env python3
"""Run the pre-registered six-instance ReMIX development gate."""

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
CORE_WORKER = HERE / "core_worker.py"
HYBRID_WORKER = HERE / "hybrid_worker.py"
HGS_PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
ILS_PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
INSTANCE_ROOT = (
    REPO
    / "baselines/algorithm_foundation/"
    "mdvrptw_v13_comparison_20260719/"
    "sources/normalised_instances"
)
TARGETS = (
    REPO
    / "baselines/algorithm_foundation/"
    "mdvrptw_v13_comparison_20260719/opponent_targets.csv"
)
OUTPUT = (
    REPO
    / "baselines/algorithm_foundation/"
    "remix_v13_six_instance_development_20260719"
)
INSTANCES = ("PR11A", "PR11B", "PR17A", "PR17B", "PR21A", "PR21B")
ARMS = ("hgs", "ils", "remix")
SEED = 1
INTERNAL_RUNTIME_SECONDS = 8.5
END_TO_END_LIMIT_SECONDS = 10.0
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


def load_targets() -> dict[str, dict[str, str]]:
    with TARGETS.open(encoding="utf-8", newline="") as stream:
        return {
            row["instance"]: row
            for row in csv.DictReader(stream)
            if row["instance"] in INSTANCES
        }


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
            raise ValueError("solution exceeds depot vehicle availability")
        vehicle = available[depot][position]
        used[depot] += 1
        routes[vehicle] = [int(client) for client in record["visits"]]
    return routes


def run_arm(
    *,
    arm: str,
    instance: Path,
    scratch: Path,
    env: dict[str, str],
) -> tuple[dict[str, Any], float]:
    if arm == "remix":
        command = [
            str(ILS_PYTHON),
            str(HYBRID_WORKER),
            "--instance",
            str(instance),
            "--seed",
            str(SEED),
            "--runtime",
            str(INTERNAL_RUNTIME_SECONDS),
            "--scratch",
            str(scratch),
        ]
    else:
        python = HGS_PYTHON if arm == "hgs" else ILS_PYTHON
        command = [
            str(python),
            str(CORE_WORKER),
            "--core",
            arm,
            "--instance",
            str(instance),
            "--seed",
            str(SEED),
            "--runtime",
            str(INTERNAL_RUNTIME_SECONDS),
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
            f"{instance.stem}/{arm} failed: "
            f"stdout={completed.stdout} stderr={completed.stderr}"
        )
    return json.loads(completed.stdout), elapsed


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite development evidence: {OUTPUT / filename}"
            )
    started = datetime.now(timezone.utc)
    targets = load_targets()
    if set(targets) != set(INSTANCES):
        raise ValueError("development target table is incomplete")
    protected_before = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
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

    outputs: dict[tuple[str, str], dict[str, Any]] = {}
    elapsed: dict[tuple[str, str], float] = {}
    independent: dict[tuple[str, str], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(INSTANCES):
        instance = INSTANCE_ROOT / f"{name}.vrp"
        order = [
            ARMS[(index + offset) % len(ARMS)]
            for offset in range(len(ARMS))
        ]
        normalised = parse_normalised(instance.read_text(encoding="utf-8"))
        for arm in order:
            arm_started = time.perf_counter()
            output, _ = run_arm(
                arm=arm,
                instance=instance,
                scratch=run_dir / name / arm,
                env=env,
            )
            key = (name, arm)
            outputs[key] = output
            write_json(run_dir / f"{name}__{arm}.json", output)
            check = validate_solution_independently(
                normalised,
                assign_routes_to_vehicles(normalised, output["routes"]),
                int(output["distance"]),
            )
            independent[key] = check
            elapsed[key] = time.perf_counter() - arm_started

        hgs_distance = int(outputs[(name, "hgs")]["distance"])
        ils_distance = int(outputs[(name, "ils")]["distance"])
        remix_distance = int(outputs[(name, "remix")]["distance"])
        strongest_core = min(hgs_distance, ils_distance)
        relation = (
            "win"
            if remix_distance < strongest_core
            else "tie"
            if remix_distance == strongest_core
            else "loss"
        )
        target_scaled = int(
            round(float(targets[name]["strongest_known_target"]) * 1000)
        )
        rows.append(
            {
                "instance": name,
                "seed": SEED,
                "run_order": ">".join(order),
                "hgs_distance": hgs_distance,
                "ils_distance": ils_distance,
                "strongest_core_distance": strongest_core,
                "remix_distance": remix_distance,
                "remix_vs_strongest_core": relation,
                "remix_improvement_percent": (
                    (strongest_core - remix_distance)
                    / strongest_core
                    * 100
                ),
                "verified_bks": target_scaled,
                "remix_gap_to_bks_percent": (
                    (remix_distance - target_scaled)
                    / target_scaled
                    * 100
                ),
                "new_bks_candidate": str(
                    remix_distance < target_scaled
                ).lower(),
                "hgs_wall_seconds": elapsed[(name, "hgs")],
                "ils_wall_seconds": elapsed[(name, "ils")],
                "remix_wall_seconds": elapsed[(name, "remix")],
                "hgs_independent_valid": str(
                    independent[(name, "hgs")]["all_checks_pass"]
                ).lower(),
                "ils_independent_valid": str(
                    independent[(name, "ils")]["all_checks_pass"]
                ).lower(),
                "remix_independent_valid": str(
                    independent[(name, "remix")]["all_checks_pass"]
                ).lower(),
                "remix_best_source": outputs[(name, "remix")][
                    "best_source"
                ],
                "remix_route_pool_source_count": len(
                    outputs[(name, "remix")]["route_pool"][
                        "selected_sources"
                    ]
                ),
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

    wins = sum(row["remix_vs_strongest_core"] == "win" for row in rows)
    ties = sum(row["remix_vs_strongest_core"] == "tie" for row in rows)
    losses = sum(row["remix_vs_strongest_core"] == "loss" for row in rows)
    new_bks = sum(row["new_bks_candidate"] == "true" for row in rows)
    all_valid = all(
        check["all_checks_pass"]
        and outputs[key]["complete"]
        and outputs[key]["feasible"]
        for key, check in independent.items()
    )
    all_within_time = all(
        value <= END_TO_END_LIMIT_SECONDS
        for value in elapsed.values()
    )
    cross_source = any(
        int(row["remix_route_pool_source_count"]) >= 2
        for row in rows
    )
    protected_after = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    protected_unchanged = protected_before == protected_after
    integrity = all_valid and all_within_time and protected_unchanged
    if not integrity:
        verdict = "FAIL_INTEGRITY"
    elif wins == len(INSTANCES) and cross_source:
        verdict = "STRONG_GO_REMIX_V13_DEV"
    elif losses == 0 and wins >= 1:
        verdict = "PROMISING_BUT_NOT_TARGET"
    else:
        verdict = "HOLD_MIXED"

    decision = {
        "verdict": verdict,
        "wins_vs_best_runnable_core": wins,
        "ties_vs_best_runnable_core": ties,
        "losses_vs_best_runnable_core": losses,
        "development_instances": len(INSTANCES),
        "new_public_bks_candidates": new_bks,
        "all_solutions_complete_feasible_independently_valid": all_valid,
        "all_end_to_end_wall_times_within_10_seconds": all_within_time,
        "cross_source_route_pool_selection_observed": cross_source,
        "protected_files_unchanged": protected_unchanged,
        "user_target_6_of_6_strict_wins_achieved": (
            wins == len(INSTANCES)
        ),
        "confirmation_block_authorized": False,
        "formal_28_instance_run_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
        "paper_superiority_claim_allowed": False,
    }
    write_json(OUTPUT / "decision.json", decision)
    metadata = {
        "contract": "REMIX-V13-DEV-001",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "runner_python": platform.python_version(),
            "ils_pyvrp": version("pyvrp"),
            "hgs_python": str(HGS_PYTHON.relative_to(REPO)),
        },
        "input": {
            "instances": list(INSTANCES),
            "instance_hashes": {
                name: sha256_file(INSTANCE_ROOT / f"{name}.vrp")
                for name in INSTANCES
            },
            "target_table": TARGETS.relative_to(REPO).as_posix(),
            "target_table_sha256": sha256_file(TARGETS),
            "seed": SEED,
            "internal_runtime_seconds": INTERNAL_RUNTIME_SECONDS,
            "end_to_end_limit_seconds": END_TO_END_LIMIT_SECONDS,
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
            "solver_arms": len(outputs),
            "independent_validation_calls": len(independent),
            "formal_28_instance_calls": 0,
            "china81_calls": 0,
        },
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    write_json(OUTPUT / "metadata.json", metadata)
    table = "\n".join(
        "|{instance}|{hgs_distance}|{ils_distance}|{remix_distance}|"
        "{remix_vs_strongest_core}|{verified_bks}|"
        "{remix_gap_to_bks_percent:.3f}%|".format(**row)
        for row in rows
    )
    report = f"""# ReMIX V13 六题低成本开发门

判定：`{verdict}`。

|题|HGS|ILS|ReMIX|对较强核心|当前可验 BKS|ReMIX 距 BKS|
|---|---:|---:|---:|---|---:|---:|
{table}

汇总：`{wins}` 胜、`{ties}` 平、`{losses}` 负；新公开 BKS 候选
`{new_bks}` 个。

完整性：全部解独立有效=`{all_valid}`；全部端到端不超过十秒=
`{all_within_time}`；路线会审至少一次选中多个来源=`{cross_source}`；
保护文件未变化=`{protected_unchanged}`。

本门是六题单种子短时开发结果。它不能替代确认块、28 题正式表或 China81，
也不能据此写论文优越性结论。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(OUTPUT / "artifact_hashes.json", build_hash_manifest(OUTPUT))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if verdict == "STRONG_GO_REMIX_V13_DEV" else 3


if __name__ == "__main__":
    raise SystemExit(main())
