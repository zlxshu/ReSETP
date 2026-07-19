#!/usr/bin/env python3
"""Run the pre-registered MPILS-MVNS-C2 G1 B-group first fire."""

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
WORKER = HERE / "run_g1_worker.py"
CONTRACT = (
    REPO
    / "docs/handoff/"
    "mpils_mvns_c2_g1_b_first_fire_contract_20260720.md"
)
PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
FOUNDATION = (
    REPO
    / "baselines/algorithm_foundation/"
    "mdvrptw_v13_comparison_20260719"
)
INSTANCE_ROOT = FOUNDATION / "sources/normalised_instances"
TARGETS = FOUNDATION / "opponent_targets.csv"
OUTPUT = (
    REPO
    / "baselines/algorithm_foundation/"
    "mpils_mvns_c2_g1_b_first_fire_20260720"
)
INSTANCES = ("PR11B", "PR17B", "PR21B")
ARMS = ("mother", "mpils_mvns_c2")
RUN_ORDERS = {
    "PR11B": ("mother", "mpils_mvns_c2"),
    "PR17B": ("mpils_mvns_c2", "mother"),
    "PR21B": ("mother", "mpils_mvns_c2"),
}
SEED = 1
INTERNAL_RUNTIME_SECONDS = 8.5
END_TO_END_LIMIT_SECONDS = 10.0
G0_FREEZE_COMMIT = "2f434816"
EXPECTED_SOURCE_HASHES = {
    "c2_core.py": (
        "78308a199b1cb9ff0a96ba74086ddc49"
        "ba476f821d16964f2f006a15672c3a9f"
    ),
    "event_driven_ils.py": (
        "71590b0f493bdf8e6bc53330b2412a1"
        "c4646e98f88d9c40606a09ef59a456b18"
    ),
}
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO / "solver/src/setp_solver/prices.py",
    REPO / "docs/paper_submission_final/paper_main.tex",
)
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)
MECHANISMS = (
    "multidepot_responsibility",
    "fleet_charge",
    "carbon_tariff_timing",
    "profit_fairness",
    "dynamic_replanning",
)
MISSING_PUBLIC = (
    "fleet_charge",
    "carbon_tariff_timing",
    "profit_fairness",
    "dynamic_replanning",
)


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


def load_targets() -> dict[str, int]:
    with TARGETS.open(encoding="utf-8", newline="") as stream:
        selected = {
            row["instance"]: int(
                round(float(row["strongest_known_target"]) * 1000)
            )
            for row in csv.DictReader(stream)
            if row["instance"] in INSTANCES
        }
    if set(selected) != set(INSTANCES):
        raise ValueError("B-group target rows are incomplete")
    return selected


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
        if depot not in available:
            raise ValueError(f"unknown route start depot: {depot}")
        position = used[depot]
        if position >= len(available[depot]):
            raise ValueError("solution exceeds depot vehicle availability")
        vehicle = available[depot][position]
        used[depot] += 1
        routes[vehicle] = [
            int(client) for client in record["visits"]
        ]
    return routes


def run_arm(
    *,
    arm: str,
    instance: Path,
    env: dict[str, str],
) -> tuple[dict[str, Any], float]:
    command = [
        str(PYTHON),
        str(WORKER),
        "--algorithm",
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


def mechanism_integrity(output: dict[str, Any]) -> bool:
    diagnostics = output.get("event_diagnostics")
    if not diagnostics:
        return False
    mechanisms = diagnostics.get("mechanisms", {})
    consultations = mechanisms.get("consultations", {})
    if any(
        int(consultations.get(mechanism, 0)) <= 0
        for mechanism in MECHANISMS
    ):
        return False
    statuses = mechanisms.get("status_counts", {})
    return all(
        int(
            statuses.get(mechanism, {}).get(
                "NOT_APPLICABLE_MISSING_INSTANCE_SEMANTICS",
                0,
            )
        )
        == int(consultations[mechanism])
        for mechanism in MISSING_PUBLIC
    )


def caps_ok(output: dict[str, Any]) -> bool:
    search = output.get("search_diagnostics")
    if not search:
        return False
    operator = search["operator"]
    calls = int(operator["calls"])
    return all(
        (
            int(operator["source_segments_considered"])
            <= 64 * calls,
            int(operator["positions_shortlisted"])
            <= 64 * 6 * calls,
            int(operator["route_evaluations"])
            <= 48 * calls,
            int(operator["full_evaluations"])
            <= 12 * calls,
        )
    )


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite G1 evidence: {OUTPUT / filename}"
            )
    if git("status", "--porcelain"):
        raise RuntimeError("G1 must start from a clean committed worktree")
    head = git("rev-parse", "HEAD")
    git("merge-base", "--is-ancestor", G0_FREEZE_COMMIT, head)
    observed_sources = {
        filename: sha256_file(HERE / filename)
        for filename in EXPECTED_SOURCE_HASHES
    }
    if observed_sources != EXPECTED_SOURCE_HASHES:
        raise RuntimeError("frozen C2 source hashes do not match contract")

    started = datetime.now(timezone.utc)
    targets = load_targets()
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
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )

    outputs: dict[tuple[str, str], dict[str, Any]] = {}
    elapsed: dict[tuple[str, str], float] = {}
    independent: dict[tuple[str, str], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    for name in INSTANCES:
        instance = INSTANCE_ROOT / f"{name}.vrp"
        normalised = parse_normalised(
            instance.read_text(encoding="utf-8")
        )
        for arm in RUN_ORDERS[name]:
            output, wall_seconds = run_arm(
                arm=arm,
                instance=instance,
                env=env,
            )
            key = (name, arm)
            outputs[key] = output
            elapsed[key] = wall_seconds
            write_json(run_dir / f"{name}__{arm}.json", output)
            independent[key] = validate_solution_independently(
                normalised,
                assign_routes_to_vehicles(
                    normalised,
                    output["routes"],
                ),
                int(output["distance"]),
            )

        mother = outputs[(name, "mother")]
        candidate = outputs[(name, "mpils_mvns_c2")]
        mother_objective = int(mother["cost"])
        candidate_objective = int(candidate["cost"])
        relation = (
            "win"
            if candidate_objective < mother_objective
            else "tie"
            if candidate_objective == mother_objective
            else "loss"
        )
        events = candidate["event_diagnostics"]
        search = candidate["search_diagnostics"]
        operator = search["operator"]
        rows.append(
            {
                "instance": name,
                "seed": SEED,
                "run_order": ">".join(RUN_ORDERS[name]),
                "mother_objective": mother_objective,
                "candidate_objective": candidate_objective,
                "relation": relation,
                "improvement_percent": (
                    (mother_objective - candidate_objective)
                    / mother_objective
                    * 100
                ),
                "verified_bks": targets[name],
                "candidate_gap_to_bks_percent": (
                    (candidate_objective - targets[name])
                    / targets[name]
                    * 100
                ),
                "mother_iterations": int(
                    mother["iterations_completed"]
                ),
                "candidate_iterations": int(
                    candidate["iterations_completed"]
                ),
                "mother_wall_seconds": elapsed[(name, "mother")],
                "candidate_wall_seconds": elapsed[
                    (name, "mpils_mvns_c2")
                ],
                "mother_independent_valid": str(
                    independent[(name, "mother")]["all_checks_pass"]
                ).lower(),
                "candidate_independent_valid": str(
                    independent[(name, "mpils_mvns_c2")][
                        "all_checks_pass"
                    ]
                ).lower(),
                "mechanism_integrity": str(
                    mechanism_integrity(candidate)
                ).lower(),
                "caps_ok": str(caps_ok(candidate)).lower(),
                "triggers": int(events["triggers"]),
                "accepted_replacements": int(
                    events["accepted_replacements"]
                ),
                "best_replacements": int(
                    events["best_replacements"]
                ),
                "replacement_attempts": int(
                    search["replacement_attempts"]
                ),
                "replacement_successes": int(
                    search["replacement_successes"]
                ),
                "segment_moves_applied": int(
                    operator["segment_moves_applied"]
                ),
                "source_segments_considered": int(
                    operator["source_segments_considered"]
                ),
                "positions_shortlisted": int(
                    operator["positions_shortlisted"]
                ),
                "route_evaluations": int(
                    operator["route_evaluations"]
                ),
                "full_evaluations": int(
                    operator["full_evaluations"]
                ),
                "hook_seconds": float(events["hook_seconds"]),
                "bank_seconds": float(events["bank_seconds"]),
                "final_strength": int(events["final_strength"]),
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

    wins = sum(row["relation"] == "win" for row in rows)
    ties = sum(row["relation"] == "tie" for row in rows)
    losses = sum(row["relation"] == "loss" for row in rows)
    all_valid = all(
        output["complete"]
        and output["feasible"]
        and independent[key]["all_checks_pass"]
        for key, output in outputs.items()
    )
    all_within_time = all(
        seconds <= END_TO_END_LIMIT_SECONDS
        for seconds in elapsed.values()
    )
    all_mechanisms = all(
        mechanism_integrity(outputs[(name, "mpils_mvns_c2")])
        for name in INSTANCES
    )
    all_caps = all(
        caps_ok(outputs[(name, "mpils_mvns_c2")])
        for name in INSTANCES
    )
    protected_after = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    protected_unchanged = protected_before == protected_after
    integrity = (
        all_valid
        and all_within_time
        and all_mechanisms
        and all_caps
        and protected_unchanged
    )
    passed = integrity and losses == 0 and wins >= 1
    verdict = (
        "PASS_G1_B_FIRST_FIRE_ZERO_LOSS_AT_LEAST_ONE_WIN"
        if passed
        else "FAIL_G1_B_FIRST_FIRE__DIAGNOSIS_REQUIRED"
    )
    decision = {
        "verdict": verdict,
        "wins_vs_same_batch_mother": wins,
        "ties_vs_same_batch_mother": ties,
        "losses_vs_same_batch_mother": losses,
        "all_solutions_complete_feasible_independently_valid": all_valid,
        "all_end_to_end_wall_times_within_10_seconds": all_within_time,
        "all_five_mechanisms_resident_and_consulted": all_mechanisms,
        "all_four_operator_caps_respected": all_caps,
        "protected_files_unchanged": protected_unchanged,
        "g2_authorized": False,
        "a_group_diagnosis_automatically_authorized": False,
        "second_b_group_fire_used": False,
        "formal_28_instance_run_authorized": False,
        "china81_run_authorized": False,
        "paper_superiority_claim_allowed": False,
    }
    write_json(OUTPUT / "decision.json", decision)

    metadata = {
        "contract": "MPILS-MVNS-C2-G1-B-FIRST-FIRE",
        "contract_path": CONTRACT.relative_to(REPO).as_posix(),
        "contract_sha256": sha256_file(CONTRACT),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "git": {
            "head": head,
            "g0_freeze_commit": G0_FREEZE_COMMIT,
            "initial_worktree_clean": True,
        },
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
            "target_table": TARGETS.relative_to(REPO).as_posix(),
            "target_table_sha256": sha256_file(TARGETS),
            "seed": SEED,
            "internal_runtime_seconds": INTERNAL_RUNTIME_SECONDS,
            "end_to_end_limit_seconds": END_TO_END_LIMIT_SECONDS,
            "arms": list(ARMS),
            "run_orders": {
                name: list(order)
                for name, order in RUN_ORDERS.items()
            },
        },
        "source_hashes": observed_sources,
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
            "a_group_calls": 0,
            "confirmation_calls": 0,
            "china81_calls": 0,
        },
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    write_json(OUTPUT / "metadata.json", metadata)

    table = "\n".join(
        "|{instance}|{mother_objective}|{candidate_objective}|"
        "{relation}|{improvement_percent:.3f}%|{verified_bks}|"
        "{candidate_gap_to_bks_percent:.3f}%|{triggers}|"
        "{accepted_replacements}|{best_replacements}|".format(**row)
        for row in rows
    )
    report = f"""# MPILS-MVNS-C2 G1 B组首发

判定：`{verdict}`。

|题|同批母体|C2|关系|改善|当前可验BKS|距BKS|触发|采纳|刷新最好|
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
{table}

汇总：`{wins}` 胜、`{ties}` 平、`{losses}` 负。过线要求是零负且至少一胜。

完整性：六解独立有效=`{all_valid}`；六臂端到端不超过十秒=`{all_within_time}`；
五机制常驻=`{all_mechanisms}`；64/6/48/12限额全守=`{all_caps}`；
保护文件未变化=`{protected_unchanged}`。

本门只是一种子、三道未被第一候选看过的开发题。BKS 只用于报告差距，没有进入
搜索或胜负判定。即使通过，也不自动授权确认题、完整28题、China81、阶段二或论文
优越性主张；失败则先做死因判断，不得直接救援。
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
