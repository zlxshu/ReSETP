#!/usr/bin/env python3
"""Run the pre-registered MDA-ILS-VNS adaptive-control gate."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import platform
import statistics
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

from adaptive_ils import ADAPTIVE_ARMS  # noqa: E402


HERE = Path(__file__).resolve().parent
OLD_WORKER = HERE / "run_worker.py"
WORKER = HERE / "run_adaptive_worker.py"
CONTRACT = REPO / "docs/handoff/mda_ils_vns_adaptive_contract_20260720.md"
PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
FOUNDATION = REPO / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_ROOT = FOUNDATION / "sources/normalised_instances"
TARGETS = FOUNDATION / "opponent_targets.csv"
OUTPUT = REPO / "baselines/algorithm_foundation/mda_ils_vns_adaptive_20260720"
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO / "solver/src/setp_solver/prices.py",
    REPO / "docs/paper_submission_final/paper_main.tex",
)
BEHAVIOUR_INSTANCE = "PR11A"
BEHAVIOUR_ITERATIONS = (5, 100, 1000)
DEVELOPMENT = ("PR11A", "PR17A", "PR21A")
DEVELOPMENT_SEED = 3
DEVELOPMENT_RUNTIME = 30.0
CONFIRMATION = ("PR16A", "PR20A", "PR24A")
CONFIRMATION_SEEDS = (1, 2)
CONFIRMATION_RUNTIME = 60.0
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


def load_bks() -> dict[str, int]:
    selected = set(DEVELOPMENT) | set(CONFIRMATION)
    with TARGETS.open(encoding="utf-8", newline="") as stream:
        return {
            row["instance"]: int(round(float(row["current_verified_bks"]) * 1000))
            for row in csv.DictReader(stream)
            if row["instance"] in selected
        }


def assign_routes_to_vehicles(
    normalised: Any,
    route_records: list[dict[str, Any]],
) -> dict[int, list[int]]:
    routes = {vehicle: [] for vehicle in range(1, normalised.num_vehicles + 1)}
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


def run_process(command: list[str], timeout: float) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=REPO,
        text=True,
        capture_output=True,
        env=environment(),
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command}; "
            f"stdout={completed.stdout}; stderr={completed.stderr}"
        )
    return json.loads(completed.stdout)


def worker_command(
    worker: Path,
    config: str,
    instance: str,
    seed: int,
    *,
    runtime: float | None = None,
    iterations: int | None = None,
) -> list[str]:
    command = [
        str(PYTHON),
        str(worker),
        "--config",
        config,
        "--instance",
        str(INSTANCE_ROOT / f"{instance}.vrp"),
        "--seed",
        str(seed),
    ]
    if runtime is not None:
        command.extend(["--runtime", str(runtime)])
    elif iterations is not None:
        command.extend(["--iterations", str(iterations)])
    else:
        raise ValueError("missing stopping criterion")
    return command


def behaviour_equivalence() -> dict[str, Any]:
    result_dir = OUTPUT / "runs/behaviour"
    result_dir.mkdir(parents=True, exist_ok=True)
    comparisons = []
    fields = (
        "cost",
        "distance",
        "duration",
        "iterations_completed",
        "routes",
        "rng_state",
    )
    for iterations in BEHAVIOUR_ITERATIONS:
        old = run_process(
            worker_command(
                OLD_WORKER,
                "swapstar_best",
                BEHAVIOUR_INSTANCE,
                1,
                iterations=iterations,
            ),
            timeout=120,
        )
        new = run_process(
            worker_command(
                WORKER,
                "foundation",
                BEHAVIOUR_INSTANCE,
                1,
                iterations=iterations,
            ),
            timeout=120,
        )
        write_json(result_dir / f"old__iter{iterations}.json", old)
        write_json(result_dir / f"new__iter{iterations}.json", new)
        equality = {field: old[field] == new[field] for field in fields}
        comparisons.append(
            {
                "iterations": iterations,
                "field_equality": equality,
                "all_equal": all(equality.values()),
            }
        )
    return {
        "comparisons": comparisons,
        "all_equal": all(row["all_equal"] for row in comparisons),
    }


def static_checks() -> dict[str, Any]:
    commands = {
        "unittest": [
            str(PYTHON),
            "-m",
            "unittest",
            "-v",
            "test_adaptive_ils.py",
        ],
        "ruff_check": [
            "ruff",
            "check",
            "adaptive_ils.py",
            "run_adaptive_worker.py",
            "run_adaptive_gate.py",
            "test_adaptive_ils.py",
        ],
        "ruff_format": [
            "ruff",
            "format",
            "--check",
            "adaptive_ils.py",
            "run_adaptive_worker.py",
            "run_adaptive_gate.py",
            "test_adaptive_ils.py",
        ],
        "audit_code": [
            sys.executable,
            "/Users/zhouleixishu/.codex/skills/audit-code/scripts/audit_code.py",
            str(HERE),
        ],
    }
    results: dict[str, Any] = {}
    for name, command in commands.items():
        completed = subprocess.run(
            command,
            cwd=HERE,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        results[name] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    results["all_passed"] = all(
        row["returncode"] == 0 for name, row in results.items() if name != "all_passed"
    )
    return results


def execute_task(task: dict[str, Any]) -> tuple[dict[str, Any], float]:
    command = worker_command(
        WORKER,
        str(task["config"]),
        str(task["instance"]),
        int(task["seed"]),
        runtime=float(task["runtime"]),
    )
    started = time.perf_counter()
    result = run_process(
        command,
        timeout=float(task["runtime"]) + 180,
    )
    return result, time.perf_counter() - started


def diagnostics(output: dict[str, Any]) -> dict[str, Any]:
    search = output["search_diagnostics"]
    if output["config"] == "foundation":
        record = search
        return {
            "adaptive_updates": 0,
            "sample_seconds": 0.0,
            "final_strength": "",
            "route_calls": int(record["route_calls"]),
            "route_improvements": int(record["route_improvements"]),
        }
    record = search["record_search"]
    return {
        "adaptive_updates": int(search["num_updates"]),
        "sample_seconds": float(search["sample_seconds"]),
        "final_strength": int(search["current_strength"]),
        "route_calls": int(record["route_calls"]),
        "route_improvements": int(record["route_improvements"]),
    }


def run_tasks(
    tasks: Iterable[dict[str, Any]],
    phase: str,
    bks: dict[str, int],
    rows: list[dict[str, Any]],
) -> None:
    phase_dir = OUTPUT / "runs" / phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    task_list = list(tasks)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(task_list))) as pool:
        futures = {pool.submit(execute_task, task): task for task in task_list}
        for future in as_completed(futures):
            task = futures[future]
            output, end_to_end = future.result()
            filename = f"{task['instance']}__{task['config']}__seed{task['seed']}.json"
            write_json(phase_dir / filename, output)
            instance = INSTANCE_ROOT / f"{task['instance']}.vrp"
            normalised = parse_normalised(instance.read_text(encoding="utf-8"))
            independent = validate_solution_independently(
                normalised,
                assign_routes_to_vehicles(
                    normalised,
                    output["routes"],
                ),
                int(output["distance"]),
            )
            diag = diagnostics(output)
            objective = int(output["cost"])
            target = bks[str(task["instance"])]
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
                    "solver_runtime_seconds": float(output["runtime_seconds"]),
                    "end_to_end_seconds": end_to_end,
                    "complete": bool(output["complete"]),
                    "feasible": bool(output["feasible"]),
                    "independent_valid": bool(independent["all_checks_pass"]),
                    **diag,
                }
            )


def arm_rows(
    rows: list[dict[str, Any]],
    phase: str,
    config: str,
) -> list[dict[str, Any]]:
    return [row for row in rows if row["phase"] == phase and row["config"] == config]


def mean_gap(
    rows: list[dict[str, Any]],
    phase: str,
    config: str,
) -> float:
    selected = arm_rows(rows, phase, config)
    return statistics.fmean(float(row["gap_percent"]) for row in selected)


def compare_pair(
    rows: list[dict[str, Any]],
    phase: str,
    instance: str,
    seed: int,
    candidate_name: str,
) -> dict[str, Any]:
    pair = {
        row["config"]: row
        for row in rows
        if row["phase"] == phase
        and row["instance"] == instance
        and int(row["seed"]) == seed
    }
    mother = pair["foundation"]
    candidate = pair[candidate_name]
    gain = int(mother["objective"]) - int(candidate["objective"])
    return {
        "instance": instance,
        "seed": seed,
        "mother": int(mother["objective"]),
        "candidate": int(candidate["objective"]),
        "candidate_gain": gain,
        "candidate_gain_percent": (100 * gain / int(mother["objective"])),
        "mother_iterations": int(mother["iterations"]),
        "candidate_iterations": int(candidate["iterations"]),
        "iteration_ratio": (int(candidate["iterations"]) / int(mother["iterations"])),
    }


def write_csv(rows: list[dict[str, Any]]) -> None:
    if not rows:
        (OUTPUT / "raw_runs.csv").write_text("", encoding="utf-8")
        return
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUTPUT}")
    if git("status", "--porcelain"):
        raise RuntimeError("adaptive gate must start from a clean commit")

    OUTPUT.mkdir(parents=True)
    started = datetime.now(timezone.utc)
    git_head = git("rev-parse", "HEAD")
    before = {
        path.relative_to(REPO).as_posix(): sha256_file(path) for path in PROTECTED
    }
    bks = load_bks()
    rows: list[dict[str, Any]] = []
    verdict = "HALT_MDA_ILS_VNS_ADAPTIVE_UNCLASSIFIED"
    selected: str | None = None
    behaviour: dict[str, Any] = {}
    checks: dict[str, Any] = {}
    development: dict[str, Any] = {}
    confirmation: dict[str, Any] = {}
    error: str | None = None

    try:
        checks = static_checks()
        behaviour = behaviour_equivalence()
        if not checks["all_passed"] or not behaviour["all_equal"]:
            raise RuntimeError("behaviour or static gate failed")

        development_tasks = [
            {
                "instance": instance,
                "config": config,
                "seed": DEVELOPMENT_SEED,
                "runtime": DEVELOPMENT_RUNTIME,
            }
            for instance in DEVELOPMENT
            for config in ADAPTIVE_ARMS
        ]
        run_tasks(development_tasks, "development", bks, rows)
        adaptive_names = [name for name in ADAPTIVE_ARMS if name != "foundation"]
        selected = min(
            adaptive_names,
            key=lambda name: (
                mean_gap(rows, "development", name),
                sum(
                    int(row["objective"]) for row in arm_rows(rows, "development", name)
                ),
                name,
            ),
        )
        development_pairs = [
            compare_pair(
                rows,
                "development",
                instance,
                DEVELOPMENT_SEED,
                selected,
            )
            for instance in DEVELOPMENT
        ]
        development_wins = sum(pair["candidate_gain"] > 0 for pair in development_pairs)
        development_losses = sum(
            pair["candidate_gain"] < 0 for pair in development_pairs
        )
        development_total_mother = sum(pair["mother"] for pair in development_pairs)
        development_total_candidate = sum(
            pair["candidate"] for pair in development_pairs
        )
        development_passed = (
            development_total_candidate < development_total_mother
            and development_wins >= 2
            and development_losses <= 1
        )
        development = {
            "selected_adaptive_arm": selected,
            "mean_gap_by_arm": {
                name: mean_gap(rows, "development", name) for name in ADAPTIVE_ARMS
            },
            "pairs": development_pairs,
            "wins": development_wins,
            "losses": development_losses,
            "total_mother": development_total_mother,
            "total_candidate": development_total_candidate,
            "passed": development_passed,
        }

        if not development_passed:
            verdict = "STOP_ADAPTIVE_LAYER_KEEP_FOUNDATION"
        else:
            confirmation_tasks = [
                {
                    "instance": instance,
                    "config": config,
                    "seed": seed,
                    "runtime": CONFIRMATION_RUNTIME,
                }
                for instance in CONFIRMATION
                for seed in CONFIRMATION_SEEDS
                for config in ("foundation", selected)
            ]
            run_tasks(
                confirmation_tasks,
                "confirmation",
                bks,
                rows,
            )
            pairs = [
                compare_pair(
                    rows,
                    "confirmation",
                    instance,
                    seed,
                    selected,
                )
                for instance in CONFIRMATION
                for seed in CONFIRMATION_SEEDS
            ]
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
            mother_gap = mean_gap(
                rows,
                "confirmation",
                "foundation",
            )
            candidate_gap = mean_gap(
                rows,
                "confirmation",
                selected,
            )
            gap_gain = mother_gap - candidate_gap
            iteration_ratio = statistics.median(
                float(pair["iteration_ratio"]) for pair in pairs
            )
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
                and iteration_ratio >= 0.95
            )
            verdict = (
                "PASS_MDA_ILS_VNS_ADAPTIVE_CONFIRMATION"
                if passed
                else "STOP_ADAPTIVE_LAYER_KEEP_FOUNDATION"
            )
            confirmation = {
                "pairs": pairs,
                "wins": wins,
                "ties": ties,
                "losses": losses,
                "total_mother": total_mother,
                "total_candidate": total_candidate,
                "mean_bks_gap_foundation": mother_gap,
                "mean_bks_gap_candidate": candidate_gap,
                "gap_gain_percentage_points": gap_gain,
                "max_pair_loss_percent": max_loss,
                "median_iteration_ratio": iteration_ratio,
                "all_solutions_independently_valid": valid,
                "protected_files_unchanged": protected_clean,
                "passed": passed,
            }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        verdict = "HALT_MDA_ILS_VNS_ADAPTIVE_EXECUTION_ERROR"

    write_csv(rows)
    after = {path.relative_to(REPO).as_posix(): sha256_file(path) for path in PROTECTED}
    decision = {
        "verdict": verdict,
        "behaviour": behaviour,
        "static_checks_passed": checks.get("all_passed", False),
        "selected_adaptive_arm": selected,
        "development": development,
        "confirmation": confirmation,
        "execution_error": error,
        "new_bks_count": sum(int(row["objective"]) < int(row["bks"]) for row in rows),
        "full_v13_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
    }
    write_json(OUTPUT / "decision.json", decision)
    metadata = {
        "contract": "MDA-ILS-VNS-A1-001",
        "contract_path": CONTRACT.relative_to(REPO).as_posix(),
        "contract_sha256": sha256_file(CONTRACT),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "host": platform.platform(),
        "python": PYTHON.relative_to(REPO).as_posix(),
        "adaptive_arms": {
            name: {
                "d_max": arm.d_max,
                "d_min": arm.d_min,
                "adaptive_acceptance": arm.adaptive_acceptance,
            }
            for name, arm in ADAPTIVE_ARMS.items()
        },
        "behaviour_iterations": list(BEHAVIOUR_ITERATIONS),
        "development": {
            "instances": list(DEVELOPMENT),
            "seed": DEVELOPMENT_SEED,
            "runtime_seconds": DEVELOPMENT_RUNTIME,
        },
        "confirmation": {
            "instances": list(CONFIRMATION),
            "seeds": list(CONFIRMATION_SEEDS),
            "runtime_seconds": CONFIRMATION_RUNTIME,
        },
        "static_checks": checks,
        "source_hashes": {
            path.relative_to(REPO).as_posix(): sha256_file(path)
            for path in (
                OLD_WORKER,
                WORKER,
                HERE / "adaptive_ils.py",
                HERE / "selective_route_vns.py",
                HERE / "test_adaptive_ils.py",
                Path(__file__).resolve(),
            )
        },
        "protected_hashes_before": before,
        "protected_hashes_after": after,
    }
    write_json(OUTPUT / "metadata.json", metadata)
    report = f"""# MDA-ILS-VNS 自适应控制门

判定：`{verdict}`。

行为等价门：`{behaviour.get("all_equal", False)}`；静态检查：
`{checks.get("all_passed", False)}`。A组选择的自适应臂为
`{selected or "未形成"}`，A组判定：
`{development.get("passed", False)}`。

未见确认块结果：{confirmation.get("wins", 0)}胜、
{confirmation.get("ties", 0)}平、{confirmation.get("losses", 0)}负；基础母体与候选
总目标分别为 {confirmation.get("total_mother", "NA")} 与
{confirmation.get("total_candidate", "NA")}；平均BKS gap改善
{confirmation.get("gap_gain_percentage_points", "NA")}个百分点；吞吐中位比
{confirmation.get("median_iteration_ratio", "NA")}。新BKS数为
{decision["new_bks_count"]}。

本包只判断AILS-II思想改写的自适应控制能否继续增强已通过的强母体。STOP只淘汰该
自适应层，不推翻基础门；PASS也不等于完整28题、China81、阶段二或最终算法完成。
执行错误：`{error or "none"}`。
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
