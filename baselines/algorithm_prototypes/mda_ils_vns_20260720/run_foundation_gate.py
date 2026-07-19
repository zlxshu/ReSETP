#!/usr/bin/env python3
"""Run the pre-registered MDA-ILS-VNS strong-mother foundation gate."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.freeze_mdvrptw_v13_foundation_20260719 import (  # noqa: E402
    build_hash_manifest,
    parse_normalised,
    validate_solution_independently,
    write_json,
)

from selective_route_vns import CONFIGS  # noqa: E402


HERE = Path(__file__).resolve().parent
WORKER = HERE / "run_worker.py"
CONTRACT = (
    REPO / "docs/handoff/mda_ils_vns_foundation_contract_20260720.md"
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
    "mda_ils_vns_foundation_20260720"
)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO / "solver/src/setp_solver/prices.py",
    REPO / "docs/paper_submission_final/paper_main.tex",
)
SCREEN_INSTANCE = "PR17A"
DEVELOPMENT = ("PR11A", "PR17A", "PR21A")
VALIDATION = ("PR11B", "PR17B", "PR21B")
SCREEN_RUNTIME = 20.0
DEVELOPMENT_RUNTIME = 30.0
VALIDATION_RUNTIME = 60.0
VALIDATION_SEEDS = (1, 2)
MAX_WORKERS = 6


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


def load_bks() -> dict[str, int]:
    selected = set(DEVELOPMENT) | set(VALIDATION)
    with TARGETS.open(encoding="utf-8", newline="") as stream:
        return {
            row["instance"]: int(
                round(float(row["current_verified_bks"]) * 1000)
            )
            for row in csv.DictReader(stream)
            if row["instance"] in selected
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
        vehicle = available[depot][used[depot]]
        used[depot] += 1
        routes[vehicle] = [int(client) for client in record["visits"]]
    return routes


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def execute_task(task: dict[str, Any]) -> tuple[dict[str, Any], float]:
    instance = INSTANCE_ROOT / f"{task['instance']}.vrp"
    command = [
        str(PYTHON),
        str(WORKER),
        "--config",
        str(task["config"]),
        "--instance",
        str(instance),
        "--seed",
        str(task["seed"]),
        "--runtime",
        str(task["runtime"]),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=environment(),
        check=False,
        timeout=float(task["runtime"]) + 120,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"{task} failed: stdout={completed.stdout} "
            f"stderr={completed.stderr}"
        )
    return json.loads(completed.stdout), elapsed


def run_tasks(
    tasks: Iterable[dict[str, Any]],
    phase: str,
    bks: dict[str, int],
    rows: list[dict[str, Any]],
) -> None:
    phase_dir = OUTPUT / "runs" / phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    task_list = list(tasks)
    with ThreadPoolExecutor(
        max_workers=min(MAX_WORKERS, len(task_list))
    ) as pool:
        futures = {
            pool.submit(execute_task, task): task for task in task_list
        }
        for future in as_completed(futures):
            task = futures[future]
            output, end_to_end = future.result()
            name = (
                f"{task['instance']}__{task['config']}__"
                f"seed{task['seed']}.json"
            )
            write_json(phase_dir / name, output)
            instance = INSTANCE_ROOT / f"{task['instance']}.vrp"
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
            objective = int(output["cost"])
            target = bks[task["instance"]]
            diag = output["search_diagnostics"]
            rows.append(
                {
                    "phase": phase,
                    "instance": task["instance"],
                    "config": task["config"],
                    "seed": int(task["seed"]),
                    "runtime_budget_seconds": float(task["runtime"]),
                    "objective": objective,
                    "bks": target,
                    "gap_percent": 100 * (objective - target) / target,
                    "iterations": int(output["iterations_completed"]),
                    "solver_runtime_seconds": float(
                        output["runtime_seconds"]
                    ),
                    "end_to_end_seconds": end_to_end,
                    "complete": bool(output["complete"]),
                    "feasible": bool(output["feasible"]),
                    "independent_valid": bool(
                        independent["all_checks_pass"]
                    ),
                    "route_calls": int(diag["route_calls"]),
                    "route_improvements": int(
                        diag["route_improvements"]
                    ),
                    "route_gain": int(diag["route_gain"]),
                    "route_seconds": float(diag["route_seconds"]),
                }
            )


def mean_gap(
    rows: list[dict[str, Any]],
    phase: str,
    config: str,
) -> float:
    values = [
        float(row["gap_percent"])
        for row in rows
        if row["phase"] == phase and row["config"] == config
    ]
    if not values:
        return float("inf")
    return sum(values) / len(values)


def write_csv(rows: list[dict[str, Any]]) -> None:
    path = OUTPUT / "raw_runs.csv"
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUTPUT}")
    if git("status", "--porcelain"):
        raise RuntimeError("foundation gate must start from a clean commit")

    OUTPUT.mkdir(parents=True)
    started = datetime.now(timezone.utc)
    git_head = git("rev-parse", "HEAD")
    before = {path.relative_to(REPO).as_posix(): sha256_file(path) for path in PROTECTED}
    bks = load_bks()
    rows: list[dict[str, Any]] = []
    selected_top3: list[str] = []
    selected_candidate: str | None = None
    verdict = "HALT_MDA_ILS_VNS_FOUNDATION_UNCLASSIFIED"
    error: str | None = None
    validation_summary: dict[str, Any] = {}

    try:
        screen_tasks = [
            {
                "instance": SCREEN_INSTANCE,
                "config": config,
                "seed": 1,
                "runtime": SCREEN_RUNTIME,
            }
            for config in CONFIGS
        ]
        run_tasks(screen_tasks, "screen", bks, rows)
        selected_top3 = [
            row["config"]
            for row in sorted(
                (
                    row
                    for row in rows
                    if row["phase"] == "screen"
                ),
                key=lambda row: (
                    int(row["objective"]),
                    str(row["config"]),
                ),
            )[:3]
        ]
        development_configs = sorted(
            set(selected_top3) | {"default"}
        )
        development_tasks = [
            {
                "instance": instance,
                "config": config,
                "seed": 1,
                "runtime": DEVELOPMENT_RUNTIME,
            }
            for instance in DEVELOPMENT
            for config in development_configs
        ]
        run_tasks(development_tasks, "development", bks, rows)
        non_default = [
            config for config in development_configs if config != "default"
        ]
        selected_candidate = min(
            non_default,
            key=lambda config: (
                mean_gap(rows, "development", config),
                max(
                    float(row["gap_percent"])
                    for row in rows
                    if row["phase"] == "development"
                    and row["config"] == config
                ),
                sum(
                    int(row["objective"])
                    for row in rows
                    if row["phase"] == "development"
                    and row["config"] == config
                ),
                config,
            ),
        )
        validation_tasks = [
            {
                "instance": instance,
                "config": config,
                "seed": seed,
                "runtime": VALIDATION_RUNTIME,
            }
            for instance in VALIDATION
            for seed in VALIDATION_SEEDS
            for config in ("default", selected_candidate)
        ]
        run_tasks(validation_tasks, "validation", bks, rows)

        pairs: list[dict[str, Any]] = []
        for instance in VALIDATION:
            for seed in VALIDATION_SEEDS:
                pair = {
                    row["config"]: row
                    for row in rows
                    if row["phase"] == "validation"
                    and row["instance"] == instance
                    and int(row["seed"]) == seed
                }
                mother = pair["default"]
                candidate = pair[selected_candidate]
                delta = int(mother["objective"]) - int(
                    candidate["objective"]
                )
                relative = (
                    100 * delta / int(mother["objective"])
                )
                pairs.append(
                    {
                        "instance": instance,
                        "seed": seed,
                        "mother": int(mother["objective"]),
                        "candidate": int(candidate["objective"]),
                        "candidate_gain": delta,
                        "candidate_gain_percent": relative,
                    }
                )
        wins = sum(pair["candidate_gain"] > 0 for pair in pairs)
        ties = sum(pair["candidate_gain"] == 0 for pair in pairs)
        losses = sum(pair["candidate_gain"] < 0 for pair in pairs)
        total_mother = sum(pair["mother"] for pair in pairs)
        total_candidate = sum(pair["candidate"] for pair in pairs)
        max_loss = max(
            (
                -float(pair["candidate_gain_percent"])
                for pair in pairs
                if pair["candidate_gain"] < 0
            ),
            default=0.0,
        )
        mother_gap = mean_gap(rows, "validation", "default")
        candidate_gap = mean_gap(
            rows,
            "validation",
            selected_candidate,
        )
        gap_gain = mother_gap - candidate_gap
        valid = all(
            bool(row["complete"])
            and bool(row["feasible"])
            and bool(row["independent_valid"])
            for row in rows
        )
        after = {
            path.relative_to(REPO).as_posix(): sha256_file(path)
            for path in PROTECTED
        }
        protected_clean = before == after
        passed = (
            valid
            and protected_clean
            and total_candidate < total_mother
            and wins >= 4
            and losses <= 1
            and max_loss <= 0.25
            and gap_gain >= 0.10
        )
        verdict = (
            "PASS_MDA_ILS_VNS_FOUNDATION_VALIDATED_GAIN"
            if passed
            else "STOP_MDA_ILS_VNS_FOUNDATION_NO_VALIDATED_GAIN"
        )
        validation_summary = {
            "pairs": pairs,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "total_mother": total_mother,
            "total_candidate": total_candidate,
            "mean_bks_gap_default": mother_gap,
            "mean_bks_gap_candidate": candidate_gap,
            "gap_gain_percentage_points": gap_gain,
            "max_pair_loss_percent": max_loss,
            "all_solutions_independently_valid": valid,
            "protected_files_unchanged": protected_clean,
            "passed": passed,
        }
    except Exception as exc:  # evidence package must fail closed
        error = f"{type(exc).__name__}: {exc}"
        verdict = "HALT_MDA_ILS_VNS_FOUNDATION_EXECUTION_ERROR"

    write_csv(rows)
    after = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    decision = {
        "verdict": verdict,
        "selected_top3_after_screen": selected_top3,
        "selected_candidate_after_development": selected_candidate,
        "validation": validation_summary,
        "execution_error": error,
        "new_bks_count": sum(
            int(row["objective"]) < int(row["bks"]) for row in rows
        ),
        "full_v13_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
    }
    write_json(OUTPUT / "decision.json", decision)
    metadata = {
        "contract": "MDA-ILS-VNS-F0-001",
        "contract_path": CONTRACT.relative_to(REPO).as_posix(),
        "contract_sha256": sha256_file(CONTRACT),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "host": platform.platform(),
        "python": PYTHON.relative_to(REPO).as_posix(),
        "configuration_names": list(CONFIGS),
        "screen": {
            "instance": SCREEN_INSTANCE,
            "seed": 1,
            "runtime_seconds": SCREEN_RUNTIME,
        },
        "development": {
            "instances": list(DEVELOPMENT),
            "seed": 1,
            "runtime_seconds": DEVELOPMENT_RUNTIME,
        },
        "validation": {
            "instances": list(VALIDATION),
            "seeds": list(VALIDATION_SEEDS),
            "runtime_seconds": VALIDATION_RUNTIME,
        },
        "source_hashes": {
            path.relative_to(REPO).as_posix(): sha256_file(path)
            for path in (WORKER, HERE / "selective_route_vns.py")
        },
        "protected_hashes_before": before,
        "protected_hashes_after": after,
    }
    write_json(OUTPUT / "metadata.json", metadata)

    validation = validation_summary or {}
    report = f"""# MDA-ILS-VNS 强母体基础门

判定：`{verdict}`。

结果前冻结的八种配置先在 PR17A 筛选，前三名为
`{', '.join(selected_top3) if selected_top3 else '未形成'}`。三道 A 组开发题选出的
唯一候选为 `{selected_candidate or '未形成'}`。

B 组两种子验收结果：{validation.get('wins', 0)}胜、
{validation.get('ties', 0)}平、{validation.get('losses', 0)}负；default 与候选
六对总目标分别为 {validation.get('total_mother', 'NA')} 与
{validation.get('total_candidate', 'NA')}；平均 BKS gap 改善
{validation.get('gap_gain_percentage_points', 'NA')} 个百分点。新 BKS 数为
{decision['new_bks_count']}。

本包只判断选择性路线 VNS 和题族配置能否在小型未见验收块稳定改善原装母体。
它不等于完整 28 题、China81、阶段二或最终算法完成。执行错误：
`{error or 'none'}`。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(
        OUTPUT / "artifact_hashes.json",
        build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if verdict.startswith("PASS_") else 3


if __name__ == "__main__":
    raise SystemExit(main())
