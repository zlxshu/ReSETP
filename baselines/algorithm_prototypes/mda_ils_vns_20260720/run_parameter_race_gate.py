#!/usr/bin/env python3
"""Run the pre-registered MDA-ILS-VNS bounded parameter race."""

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

from racing_configs import RACE_CONFIGS  # noqa: E402


HERE = Path(__file__).resolve().parent
OLD_WORKER = HERE / "run_worker.py"
WORKER = HERE / "run_racing_worker.py"
CONTRACT = REPO / "docs/handoff/mda_ils_vns_parameter_race_contract_20260720.md"
PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
FOUNDATION = REPO / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_ROOT = FOUNDATION / "sources/normalised_instances"
TARGETS = FOUNDATION / "opponent_targets.csv"
OUTPUT = REPO / "baselines/algorithm_foundation/mda_ils_vns_parameter_race_20260720"
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
SCREEN_SEED = 5
SCREEN_RUNTIME = 12.0
REPLAY_SEED = 6
REPLAY_RUNTIME = 30.0
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


def assign_routes(
    normalised: Any,
    records: list[dict[str, Any]],
) -> dict[int, list[int]]:
    routes = {vehicle: [] for vehicle in range(1, normalised.num_vehicles + 1)}
    available: dict[int, list[int]] = {}
    for vehicle, depot in normalised.vehicle_depots.items():
        available.setdefault(depot - 1, []).append(vehicle)
    used = {depot: 0 for depot in available}
    for record in records:
        depot = int(record["start_depot"])
        vehicle = available[depot][used[depot]]
        used[depot] += 1
        routes[vehicle] = [int(client) for client in record["visits"]]
    return routes


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


def static_checks() -> dict[str, Any]:
    names = (
        "racing_configs.py",
        "run_racing_worker.py",
        "run_parameter_race_gate.py",
        "test_racing_configs.py",
    )
    commands = {
        "unittest": [
            str(PYTHON),
            "-m",
            "unittest",
            "-v",
            "test_racing_configs.py",
        ],
        "ruff": ["ruff", "check", *names],
        "format": ["ruff", "format", "--check", *names],
        "audit": [
            sys.executable,
            "/Users/zhouleixishu/.codex/skills/audit-code/scripts/audit_code.py",
            str(HERE),
        ],
    }
    output: dict[str, Any] = {}
    for name, command in commands.items():
        completed = subprocess.run(
            command,
            cwd=HERE,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        output[name] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    output["all_passed"] = all(
        row["returncode"] == 0 for name, row in output.items() if name != "all_passed"
    )
    return output


def behaviour_checks() -> dict[str, Any]:
    output_dir = OUTPUT / "runs/behaviour"
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = (
        "cost",
        "distance",
        "duration",
        "iterations_completed",
        "routes",
        "rng_state",
    )
    checks = []
    for iterations in BEHAVIOUR_ITERATIONS:
        old = run_process(
            worker_command(
                OLD_WORKER,
                "swapstar_best",
                BEHAVIOUR_INSTANCE,
                1,
                iterations=iterations,
            ),
            120,
        )
        new = run_process(
            worker_command(
                WORKER,
                "foundation",
                BEHAVIOUR_INSTANCE,
                1,
                iterations=iterations,
            ),
            120,
        )
        write_json(output_dir / f"old__iter{iterations}.json", old)
        write_json(output_dir / f"new__iter{iterations}.json", new)
        equality = {field: old[field] == new[field] for field in fields}
        old_diagnostics = {
            key: value
            for key, value in old["search_diagnostics"].items()
            if key != "route_seconds"
        }
        new_diagnostics = {
            key: value
            for key, value in new["search_diagnostics"].items()
            if key != "route_seconds"
        }
        equality["deterministic_search_diagnostics"] = (
            old_diagnostics == new_diagnostics
        )
        checks.append(
            {
                "iterations": iterations,
                "field_equality": equality,
                "all_equal": all(equality.values()),
            }
        )
    return {
        "checks": checks,
        "all_equal": all(check["all_equal"] for check in checks),
    }


def execute_task(task: dict[str, Any]) -> tuple[dict[str, Any], float]:
    command = worker_command(
        WORKER,
        str(task["config"]),
        str(task["instance"]),
        int(task["seed"]),
        runtime=float(task["runtime"]),
    )
    started = time.perf_counter()
    result = run_process(command, float(task["runtime"]) + 180)
    return result, time.perf_counter() - started


def run_tasks(
    tasks: Iterable[dict[str, Any]],
    phase: str,
    bks: dict[str, int],
    rows: list[dict[str, Any]],
) -> None:
    output_dir = OUTPUT / "runs" / phase
    output_dir.mkdir(parents=True, exist_ok=True)
    task_list = list(tasks)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(task_list))) as pool:
        futures = {pool.submit(execute_task, task): task for task in task_list}
        for future in as_completed(futures):
            task = futures[future]
            output, end_to_end = future.result()
            filename = f"{task['instance']}__{task['config']}__seed{task['seed']}.json"
            write_json(output_dir / filename, output)
            path = INSTANCE_ROOT / f"{task['instance']}.vrp"
            normalised = parse_normalised(path.read_text(encoding="utf-8"))
            independent = validate_solution_independently(
                normalised,
                assign_routes(normalised, output["routes"]),
                int(output["distance"]),
            )
            objective = int(output["cost"])
            target = bks[str(task["instance"])]
            diagnostics = output["search_diagnostics"]
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
                    "route_calls": int(diagnostics["route_calls"]),
                    "route_improvements": int(diagnostics["route_improvements"]),
                    "route_gain": int(diagnostics["route_gain"]),
                    "route_seconds": float(diagnostics["route_seconds"]),
                }
            )


def selected_rows(
    rows: list[dict[str, Any]],
    phase: str,
    config: str,
) -> list[dict[str, Any]]:
    return [row for row in rows if row["phase"] == phase and row["config"] == config]


def rank_key(
    rows: list[dict[str, Any]],
    phase: str,
    config: str,
) -> tuple[float, float, int, str]:
    values = selected_rows(rows, phase, config)
    return (
        statistics.fmean(float(row["gap_percent"]) for row in values),
        max(float(row["gap_percent"]) for row in values),
        sum(int(row["objective"]) for row in values),
        config,
    )


def make_pair(
    rows: list[dict[str, Any]],
    phase: str,
    instance: str,
    seed: int,
    candidate: str,
) -> dict[str, Any]:
    pair = {
        row["config"]: row
        for row in rows
        if row["phase"] == phase
        and row["instance"] == instance
        and int(row["seed"]) == seed
    }
    mother = pair["foundation"]
    child = pair[candidate]
    gain = int(mother["objective"]) - int(child["objective"])
    return {
        "instance": instance,
        "seed": seed,
        "mother": int(mother["objective"]),
        "candidate": int(child["objective"]),
        "candidate_gain": gain,
        "candidate_gain_percent": (100 * gain / int(mother["objective"])),
        "mother_iterations": int(mother["iterations"]),
        "candidate_iterations": int(child["iterations"]),
        "iteration_ratio": (int(child["iterations"]) / int(mother["iterations"])),
    }


def pair_summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pairs": pairs,
        "wins": sum(pair["candidate_gain"] > 0 for pair in pairs),
        "ties": sum(pair["candidate_gain"] == 0 for pair in pairs),
        "losses": sum(pair["candidate_gain"] < 0 for pair in pairs),
        "total_mother": sum(pair["mother"] for pair in pairs),
        "total_candidate": sum(pair["candidate"] for pair in pairs),
    }


def mean_gap(
    rows: list[dict[str, Any]],
    phase: str,
    config: str,
) -> float:
    return statistics.fmean(
        float(row["gap_percent"]) for row in selected_rows(rows, phase, config)
    )


def write_csv(rows: list[dict[str, Any]]) -> None:
    if not rows:
        (OUTPUT / "raw_runs.csv").write_text("", encoding="utf-8")
        return
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUTPUT}")
    if git("status", "--porcelain"):
        raise RuntimeError("parameter race must start from a clean commit")

    OUTPUT.mkdir(parents=True)
    started = datetime.now(timezone.utc)
    git_head = git("rev-parse", "HEAD")
    before = {
        path.relative_to(REPO).as_posix(): sha256_file(path) for path in PROTECTED
    }
    bks = load_bks()
    rows: list[dict[str, Any]] = []
    verdict = "HALT_PARAMETER_RACE_UNCLASSIFIED"
    checks: dict[str, Any] = {}
    behaviour: dict[str, Any] = {}
    screen: dict[str, Any] = {}
    replay: dict[str, Any] = {}
    confirmation: dict[str, Any] = {}
    selected_top4: list[str] = []
    selected_candidate: str | None = None
    error: str | None = None

    try:
        checks = static_checks()
        behaviour = behaviour_checks()
        if not checks["all_passed"] or not behaviour["all_equal"]:
            raise RuntimeError("static or behaviour gate failed")

        screen_tasks = [
            {
                "instance": instance,
                "config": config,
                "seed": SCREEN_SEED,
                "runtime": SCREEN_RUNTIME,
            }
            for instance in DEVELOPMENT
            for config in RACE_CONFIGS
        ]
        run_tasks(screen_tasks, "screen", bks, rows)
        candidates = [name for name in RACE_CONFIGS if name != "foundation"]
        selected_top4 = sorted(
            candidates,
            key=lambda name: rank_key(rows, "screen", name),
        )[:4]
        screen = {
            "mean_gap_by_arm": {
                name: mean_gap(rows, "screen", name) for name in RACE_CONFIGS
            },
            "selected_top4": selected_top4,
        }

        replay_arms = ("foundation", *selected_top4)
        replay_tasks = [
            {
                "instance": instance,
                "config": config,
                "seed": REPLAY_SEED,
                "runtime": REPLAY_RUNTIME,
            }
            for instance in DEVELOPMENT
            for config in replay_arms
        ]
        run_tasks(replay_tasks, "replay", bks, rows)
        selected_candidate = min(
            selected_top4,
            key=lambda name: rank_key(rows, "replay", name),
        )
        replay_pairs = [
            make_pair(
                rows,
                "replay",
                instance,
                REPLAY_SEED,
                selected_candidate,
            )
            for instance in DEVELOPMENT
        ]
        replay = pair_summary(replay_pairs)
        replay["selected_candidate"] = selected_candidate
        replay["mean_gap_by_arm"] = {
            name: mean_gap(rows, "replay", name) for name in replay_arms
        }
        replay["passed"] = (
            replay["total_candidate"] < replay["total_mother"]
            and replay["wins"] >= 2
            and replay["losses"] <= 1
        )
        if not replay["passed"]:
            verdict = "STOP_PARAMETER_RACE_KEEP_FOUNDATION"
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
                for config in ("foundation", selected_candidate)
            ]
            run_tasks(
                confirmation_tasks,
                "confirmation",
                bks,
                rows,
            )
            confirmation_pairs = [
                make_pair(
                    rows,
                    "confirmation",
                    instance,
                    seed,
                    selected_candidate,
                )
                for instance in CONFIRMATION
                for seed in CONFIRMATION_SEEDS
            ]
            confirmation = pair_summary(confirmation_pairs)
            loss_sizes = [
                -float(pair["candidate_gain_percent"])
                for pair in confirmation_pairs
                if pair["candidate_gain"] < 0
            ]
            confirmation["max_loss_percent"] = max(
                loss_sizes,
                default=0.0,
            )
            confirmation["gap_gain_percentage_points"] = mean_gap(
                rows, "confirmation", "foundation"
            ) - mean_gap(
                rows,
                "confirmation",
                selected_candidate,
            )
            confirmation["median_iteration_ratio"] = statistics.median(
                pair["iteration_ratio"] for pair in confirmation_pairs
            )
            confirmation["all_solutions_independently_valid"] = all(
                bool(row["complete"])
                and bool(row["feasible"])
                and bool(row["independent_valid"])
                for row in rows
            )
            after_now = {
                path.relative_to(REPO).as_posix(): sha256_file(path)
                for path in PROTECTED
            }
            confirmation["protected_files_unchanged"] = before == after_now
            confirmation["passed"] = (
                confirmation["total_candidate"] < confirmation["total_mother"]
                and confirmation["wins"] >= 4
                and confirmation["losses"] <= 1
                and confirmation["max_loss_percent"] <= 0.25
                and confirmation["gap_gain_percentage_points"] >= 0.10
                and confirmation["median_iteration_ratio"] >= 0.95
                and confirmation["all_solutions_independently_valid"]
                and confirmation["protected_files_unchanged"]
            )
            verdict = (
                "PASS_PARAMETER_RACE_VALIDATED_GAIN"
                if confirmation["passed"]
                else "STOP_PARAMETER_RACE_KEEP_FOUNDATION"
            )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        verdict = "HALT_PARAMETER_RACE_EXECUTION_ERROR"

    write_csv(rows)
    after = {path.relative_to(REPO).as_posix(): sha256_file(path) for path in PROTECTED}
    decision = {
        "verdict": verdict,
        "selected_top4_after_screen": selected_top4,
        "selected_candidate_after_replay": selected_candidate,
        "screen": screen,
        "replay": replay,
        "confirmation": confirmation,
        "execution_error": error,
        "new_bks_count": sum(int(row["objective"]) < int(row["bks"]) for row in rows),
        "full_v13_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
    }
    write_json(OUTPUT / "decision.json", decision)
    metadata = {
        "contract": "MDA-ILS-VNS-P1-001",
        "contract_path": CONTRACT.relative_to(REPO).as_posix(),
        "contract_sha256": sha256_file(CONTRACT),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "host": platform.platform(),
        "python": PYTHON.relative_to(REPO).as_posix(),
        "configuration_names": list(RACE_CONFIGS),
        "screen": {
            "instances": list(DEVELOPMENT),
            "seed": SCREEN_SEED,
            "runtime_seconds": SCREEN_RUNTIME,
        },
        "replay": {
            "instances": list(DEVELOPMENT),
            "seed": REPLAY_SEED,
            "runtime_seconds": REPLAY_RUNTIME,
        },
        "confirmation": {
            "instances": list(CONFIRMATION),
            "seeds": list(CONFIRMATION_SEEDS),
            "runtime_seconds": CONFIRMATION_RUNTIME,
        },
        "static_checks": checks,
        "behaviour_checks": behaviour,
        "source_hashes": {
            path.relative_to(REPO).as_posix(): sha256_file(path)
            for path in (
                WORKER,
                HERE / "racing_configs.py",
                HERE / "selective_route_vns.py",
            )
        },
        "protected_hashes_before": before,
        "protected_hashes_after": after,
    }
    write_json(OUTPUT / "metadata.json", metadata)

    report = f"""# MDA-ILS-VNS 母体参数竞速

判定：`{verdict}`。

第一轮从16个结果前冻结配置中保留：
`{", ".join(selected_top4) if selected_top4 else "未形成"}`。
第二轮唯一候选：`{selected_candidate or "未形成"}`；
相对foundation为 {replay.get("wins", 0)}胜、
{replay.get("ties", 0)}平、{replay.get("losses", 0)}负。

未见确认：{confirmation.get("wins", 0)}胜、
{confirmation.get("ties", 0)}平、{confirmation.get("losses", 0)}负；
总目标为 {confirmation.get("total_mother", "NA")} 对
{confirmation.get("total_candidate", "NA")}；平均BKS gap改善
{confirmation.get("gap_gain_percentage_points", "NA")}个百分点；
新BKS数 {decision["new_bks_count"]}。

本包只判断有限参数竞速能否在未见题上稳定改善已通过强母体。它不等于完整28题、
China81、阶段二或最终论文结论。执行错误：`{error or "none"}`。
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
