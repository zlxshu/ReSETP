#!/usr/bin/env python3
"""Run the pre-registered MPD-ILS-VNS dual-regime gate."""

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

from multi_stage_regimes import ARMS, EXPERTS  # noqa: E402


HERE = Path(__file__).resolve().parent
OLD_WORKER = HERE / "run_worker.py"
WORKER = HERE / "run_multi_stage_worker.py"
CONTRACT = REPO / "docs/handoff/mpd_ils_vns_dual_regime_contract_20260720.md"
PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
FOUNDATION = REPO / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_ROOT = FOUNDATION / "sources/normalised_instances"
TARGETS = FOUNDATION / "opponent_targets.csv"
OUTPUT = REPO / "baselines/algorithm_foundation/mpd_ils_vns_dual_regime_20260720"
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
DEVELOPMENT_SEED = 7
DEVELOPMENT_RUNTIME = 60.0
CONFIRMATION = ("PR16B", "PR20B", "PR24B")
CONFIRMATION_SEEDS = (1, 2)
CONFIRMATION_RUNTIME = 90.0
COMPONENTS = ("foundation", "wide")
HYBRIDS = ("wide70_fast30", "fast20_wide60_fast20")
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
    arm: str,
    instance: str,
    seed: int,
    *,
    runtime: float | None = None,
    iterations: int | None = None,
) -> list[str]:
    flag = "--config" if worker == OLD_WORKER else "--arm"
    command = [
        str(PYTHON),
        str(worker),
        flag,
        arm,
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
        "multi_stage_regimes.py",
        "run_multi_stage_worker.py",
        "run_dual_regime_gate.py",
        "test_multi_stage_regimes.py",
    )
    commands = {
        "unittest": [
            str(PYTHON),
            "-m",
            "unittest",
            "-v",
            "test_multi_stage_regimes.py",
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
        ledger = new["mechanism_expert_ledger"]
        ledger_ok = (
            len(ledger) == len(EXPERTS)
            and {row["expert"] for row in ledger} == set(EXPERTS)
            and all(row["queried"] for row in ledger)
            and all(not row["applicable"] for row in ledger)
            and all(row["action_count"] == 0 for row in ledger)
        )
        checks.append(
            {
                "iterations": iterations,
                "field_equality": equality,
                "mechanism_ledger_valid": ledger_ok,
                "all_equal": all(equality.values()) and ledger_ok,
            }
        )
    return {
        "checks": checks,
        "all_equal": all(check["all_equal"] for check in checks),
    }


def execute_task(task: dict[str, Any]) -> tuple[dict[str, Any], float]:
    command = worker_command(
        WORKER,
        str(task["arm"]),
        str(task["instance"]),
        int(task["seed"]),
        runtime=float(task["runtime"]),
    )
    started = time.perf_counter()
    result = run_process(command, float(task["runtime"]) + 180)
    return result, time.perf_counter() - started


def ledger_valid(output: dict[str, Any]) -> bool:
    ledger = output["mechanism_expert_ledger"]
    phases = len(output["phase_outputs"])
    return (
        len(ledger) == phases * len(EXPERTS)
        and all(row["queried"] for row in ledger)
        and all(not row["applicable"] for row in ledger)
        and all(row["action_count"] == 0 for row in ledger)
        and all(
            {row["expert"] for row in ledger if row["phase_index"] == phase}
            == set(EXPERTS)
            for phase in range(1, phases + 1)
        )
    )


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
            filename = f"{task['instance']}__{task['arm']}__seed{task['seed']}.json"
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
            rows.append(
                {
                    "phase": phase,
                    "instance": task["instance"],
                    "arm": task["arm"],
                    "seed": int(task["seed"]),
                    "runtime_budget_seconds": float(task["runtime"]),
                    "objective": objective,
                    "bks": target,
                    "gap_percent": 100 * (objective - target) / target,
                    "iterations": int(output["iterations_completed"]),
                    "algorithm_runtime_seconds": float(output["runtime_seconds"]),
                    "end_to_end_seconds": end_to_end,
                    "complete": bool(output["complete"]),
                    "feasible": bool(output["feasible"]),
                    "independent_valid": bool(independent["all_checks_pass"]),
                    "phase_count": len(output["phase_outputs"]),
                    "mechanism_query_count": len(output["mechanism_expert_ledger"]),
                    "mechanism_action_count": sum(
                        int(row["action_count"])
                        for row in output["mechanism_expert_ledger"]
                    ),
                    "mechanism_ledger_valid": ledger_valid(output),
                    "within_runtime_tolerance": float(output["runtime_seconds"])
                    <= float(task["runtime"]) + 2.0,
                }
            )


def selected_rows(
    rows: list[dict[str, Any]],
    phase: str,
    arm: str,
) -> list[dict[str, Any]]:
    return [row for row in rows if row["phase"] == phase and row["arm"] == arm]


def rank_key(
    rows: list[dict[str, Any]],
    phase: str,
    arm: str,
) -> tuple[float, float, int, str]:
    values = selected_rows(rows, phase, arm)
    return (
        statistics.fmean(float(row["gap_percent"]) for row in values),
        max(float(row["gap_percent"]) for row in values),
        sum(int(row["objective"]) for row in values),
        arm,
    )


def mean_gap(
    rows: list[dict[str, Any]],
    phase: str,
    arm: str,
) -> float:
    return statistics.fmean(
        float(row["gap_percent"]) for row in selected_rows(rows, phase, arm)
    )


def make_pair(
    rows: list[dict[str, Any]],
    phase: str,
    instance: str,
    seed: int,
    candidate: str,
    comparator: str,
) -> dict[str, Any]:
    matched = {
        row["arm"]: row
        for row in rows
        if row["phase"] == phase
        and row["instance"] == instance
        and int(row["seed"]) == seed
    }
    base = matched[comparator]
    child = matched[candidate]
    gain = int(base["objective"]) - int(child["objective"])
    return {
        "instance": instance,
        "seed": seed,
        "comparator": comparator,
        "comparator_objective": int(base["objective"]),
        "candidate_objective": int(child["objective"]),
        "candidate_gain": gain,
        "candidate_gain_percent": (100 * gain / int(base["objective"])),
    }


def comparison_summary(
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "pairs": pairs,
        "wins": sum(pair["candidate_gain"] > 0 for pair in pairs),
        "ties": sum(pair["candidate_gain"] == 0 for pair in pairs),
        "losses": sum(pair["candidate_gain"] < 0 for pair in pairs),
        "total_comparator": sum(pair["comparator_objective"] for pair in pairs),
        "total_candidate": sum(pair["candidate_objective"] for pair in pairs),
        "max_loss_percent": max(
            (
                -float(pair["candidate_gain_percent"])
                for pair in pairs
                if pair["candidate_gain"] < 0
            ),
            default=0.0,
        ),
    }


def make_comparisons(
    rows: list[dict[str, Any]],
    phase: str,
    instances: tuple[str, ...],
    seeds: tuple[int, ...],
    candidate: str,
) -> dict[str, Any]:
    return {
        comparator: comparison_summary(
            [
                make_pair(
                    rows,
                    phase,
                    instance,
                    seed,
                    candidate,
                    comparator,
                )
                for instance in instances
                for seed in seeds
            ]
        )
        for comparator in COMPONENTS
    }


def integrity_ok(
    rows: list[dict[str, Any]],
    phase: str,
) -> bool:
    return all(
        bool(row["complete"])
        and bool(row["feasible"])
        and bool(row["independent_valid"])
        and bool(row["mechanism_ledger_valid"])
        and bool(row["within_runtime_tolerance"])
        for row in rows
        if row["phase"] == phase
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
        raise RuntimeError("dual-regime gate must start from a clean commit")

    OUTPUT.mkdir(parents=True)
    started = datetime.now(timezone.utc)
    git_head = git("rev-parse", "HEAD")
    before = {
        path.relative_to(REPO).as_posix(): sha256_file(path) for path in PROTECTED
    }
    bks = load_bks()
    rows: list[dict[str, Any]] = []
    verdict = "HALT_MPD_ILS_VNS_UNCLASSIFIED"
    checks: dict[str, Any] = {}
    behaviour: dict[str, Any] = {}
    development: dict[str, Any] = {}
    confirmation: dict[str, Any] = {}
    selected: str | None = None
    error: str | None = None

    try:
        checks = static_checks()
        behaviour = behaviour_checks()
        if not checks["all_passed"] or not behaviour["all_equal"]:
            raise RuntimeError("static or behaviour gate failed")

        development_tasks = [
            {
                "instance": instance,
                "arm": arm,
                "seed": DEVELOPMENT_SEED,
                "runtime": DEVELOPMENT_RUNTIME,
            }
            for instance in DEVELOPMENT
            for arm in ARMS
        ]
        run_tasks(
            development_tasks,
            "development",
            bks,
            rows,
        )
        selected = min(
            HYBRIDS,
            key=lambda arm: rank_key(
                rows,
                "development",
                arm,
            ),
        )
        dev_comparisons = make_comparisons(
            rows,
            "development",
            DEVELOPMENT,
            (DEVELOPMENT_SEED,),
            selected,
        )
        development = {
            "selected": selected,
            "mean_gap_by_arm": {
                arm: mean_gap(rows, "development", arm) for arm in ARMS
            },
            "comparisons": dev_comparisons,
            "integrity_passed": integrity_ok(
                rows,
                "development",
            ),
        }
        development["passed"] = development["integrity_passed"] and all(
            summary["total_candidate"] < summary["total_comparator"]
            and summary["wins"] >= 2
            and summary["losses"] <= 1
            for summary in dev_comparisons.values()
        )
        if not development["passed"]:
            verdict = "STOP_MPD_ILS_VNS_PUBLIC_ARCHITECTURE__PIVOT_CHINA81"
        else:
            confirmation_tasks = [
                {
                    "instance": instance,
                    "arm": arm,
                    "seed": seed,
                    "runtime": CONFIRMATION_RUNTIME,
                }
                for instance in CONFIRMATION
                for seed in CONFIRMATION_SEEDS
                for arm in (*COMPONENTS, selected)
            ]
            run_tasks(
                confirmation_tasks,
                "confirmation",
                bks,
                rows,
            )
            confirm_comparisons = make_comparisons(
                rows,
                "confirmation",
                CONFIRMATION,
                CONFIRMATION_SEEDS,
                selected,
            )
            best_component_gap = min(
                mean_gap(rows, "confirmation", component) for component in COMPONENTS
            )
            candidate_gap = mean_gap(
                rows,
                "confirmation",
                selected,
            )
            after_now = {
                path.relative_to(REPO).as_posix(): sha256_file(path)
                for path in PROTECTED
            }
            confirmation = {
                "comparisons": confirm_comparisons,
                "mean_gap_by_arm": {
                    arm: mean_gap(rows, "confirmation", arm)
                    for arm in (*COMPONENTS, selected)
                },
                "gap_gain_over_best_component": (best_component_gap - candidate_gap),
                "integrity_passed": integrity_ok(
                    rows,
                    "confirmation",
                ),
                "protected_files_unchanged": before == after_now,
            }
            confirmation["passed"] = (
                confirmation["integrity_passed"]
                and confirmation["protected_files_unchanged"]
                and confirmation["gap_gain_over_best_component"] >= 0.10
                and all(
                    summary["total_candidate"] < summary["total_comparator"]
                    and summary["wins"] >= 4
                    and summary["losses"] <= 1
                    and summary["max_loss_percent"] <= 0.25
                    for summary in confirm_comparisons.values()
                )
            )
            verdict = (
                "PASS_MPD_ILS_VNS_DUAL_REGIME_VALIDATED_GAIN"
                if confirmation["passed"]
                else ("STOP_MPD_ILS_VNS_PUBLIC_ARCHITECTURE__PIVOT_CHINA81")
            )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        verdict = "HALT_MPD_ILS_VNS_EXECUTION_ERROR"

    write_csv(rows)
    after = {path.relative_to(REPO).as_posix(): sha256_file(path) for path in PROTECTED}
    decision = {
        "verdict": verdict,
        "selected_hybrid": selected,
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
        "contract": "MPD-ILS-VNS-D1-001",
        "contract_path": CONTRACT.relative_to(REPO).as_posix(),
        "contract_sha256": sha256_file(CONTRACT),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "host": platform.platform(),
        "python": PYTHON.relative_to(REPO).as_posix(),
        "arms": list(ARMS),
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
        "behaviour_checks": behaviour,
        "source_hashes": {
            path.relative_to(REPO).as_posix(): sha256_file(path)
            for path in (
                WORKER,
                HERE / "multi_stage_regimes.py",
                HERE / "selective_route_vns.py",
            )
        },
        "protected_hashes_before": before,
        "protected_hashes_after": after,
    }
    write_json(OUTPUT / "metadata.json", metadata)

    report = f"""# MPD-ILS-VNS 多阶段双节奏整机门

判定：`{verdict}`。

A组唯一多阶段候选：`{selected or "未形成"}`。相对foundation：
{development.get("comparisons", {}).get("foundation", {}).get("wins", 0)}胜、
{development.get("comparisons", {}).get("foundation", {}).get("ties", 0)}平、
{development.get("comparisons", {}).get("foundation", {}).get("losses", 0)}负；
相对wide：
{development.get("comparisons", {}).get("wide", {}).get("wins", 0)}胜、
{development.get("comparisons", {}).get("wide", {}).get("ties", 0)}平、
{development.get("comparisons", {}).get("wide", {}).get("losses", 0)}负。

B组相对foundation：
{confirmation.get("comparisons", {}).get("foundation", {}).get("wins", 0)}胜、
{confirmation.get("comparisons", {}).get("foundation", {}).get("ties", 0)}平、
{confirmation.get("comparisons", {}).get("foundation", {}).get("losses", 0)}负；
相对wide：
{confirmation.get("comparisons", {}).get("wide", {}).get("wins", 0)}胜、
{confirmation.get("comparisons", {}).get("wide", {}).get("ties", 0)}平、
{confirmation.get("comparisons", {}).get("wide", {}).get("losses", 0)}负。
相对更强单体的平均BKS gap改善
{confirmation.get("gap_gain_over_best_component", "NA")}个百分点；新BKS数
{decision["new_bks_count"]}。

本包只判断分阶段整机能否在未见B组同时胜两个单体。它不等于完整28题、China81、
阶段二或论文正式结论。执行错误：`{error or "none"}`。
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
