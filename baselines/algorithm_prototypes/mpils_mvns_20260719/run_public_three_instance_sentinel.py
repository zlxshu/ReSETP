#!/usr/bin/env python3
"""Run the pre-registered three-instance MPILS-MVNS engineering sentinel."""

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
WORKER = HERE / "run_mpils_mvns_worker.py"
BEHAVIOUR_TESTS = HERE / "test_mpils_mvns_search.py"
PYTHON = REPO / "build/python_envs/pyvrp-0.13.4/bin/python"
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
    "mpils_mvns_three_instance_sentinel_20260719"
)
INSTANCES = ("PR11A", "PR17A", "PR21A")
ARMS = ("mother", "mpils_mvns")
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
MECHANISMS = (
    "multidepot_responsibility",
    "fleet_charge",
    "carbon_tariff_timing",
    "profit_fairness",
    "dynamic_replanning",
)
MISSING_PUBLIC_SEMANTICS = (
    "fleet_charge",
    "carbon_tariff_timing",
    "profit_fairness",
    "dynamic_replanning",
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


def run_behaviour_tests(env: dict[str, str]) -> str:
    completed = subprocess.run(
        [str(PYTHON), str(BEHAVIOUR_TESTS)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    transcript = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError(
            "MPILS-MVNS behaviour tests failed:\n" + transcript
        )
    return transcript


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


def mechanism_integrity(
    output: dict[str, Any],
) -> tuple[bool, int]:
    diagnostics = output.get("mechanism_diagnostics")
    if not diagnostics:
        return False, 0
    mechanisms = diagnostics.get("mechanisms", {})
    if (
        mechanisms.get("registry_policy")
        != "ALWAYS_RESIDENT_SEMANTIC_DISPATCH_NO_DISABLE_SWITCH"
    ):
        return False, 0
    calls = int(diagnostics.get("calls", 0))
    consultations = mechanisms.get("consultations", {})
    if calls <= 0 or any(
        int(consultations.get(mechanism, 0)) != calls
        for mechanism in MECHANISMS
    ):
        return False, 0
    statuses = mechanisms.get("status_counts", {})
    if any(
        int(
            statuses.get(mechanism, {}).get(
                "NOT_APPLICABLE_MISSING_INSTANCE_SEMANTICS",
                0,
            )
        )
        != calls
        for mechanism in MISSING_PUBLIC_SEMANTICS
    ):
        return False, 0
    responsibility_actions = int(
        statuses.get("multidepot_responsibility", {}).get(
            "APPLICABLE_ACTION_AVAILABLE",
            0,
        )
    )
    return True, responsibility_actions


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                "refusing to overwrite sentinel evidence: "
                f"{OUTPUT / filename}"
            )

    started = datetime.now(timezone.utc)
    targets = load_targets()
    if set(targets) != set(INSTANCES):
        raise ValueError("sentinel target table is incomplete")
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
    behaviour_transcript = run_behaviour_tests(env)
    (OUTPUT / "behaviour_tests.txt").write_text(
        behaviour_transcript,
        encoding="utf-8",
    )

    outputs: dict[tuple[str, str], dict[str, Any]] = {}
    elapsed: dict[tuple[str, str], float] = {}
    independent: dict[tuple[str, str], dict[str, Any]] = {}
    mechanism_ok: dict[str, bool] = {}
    responsibility_actions: dict[str, int] = {}
    rows: list[dict[str, Any]] = []

    for index, name in enumerate(INSTANCES):
        instance = INSTANCE_ROOT / f"{name}.vrp"
        order = (
            list(ARMS) if index % 2 == 0 else list(reversed(ARMS))
        )
        normalised = parse_normalised(
            instance.read_text(encoding="utf-8")
        )
        for arm in order:
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

        full_output = outputs[(name, "mpils_mvns")]
        mechanism_ok[name], responsibility_actions[name] = (
            mechanism_integrity(full_output)
        )
        mother_distance = int(outputs[(name, "mother")]["distance"])
        full_distance = int(full_output["distance"])
        relation = (
            "win"
            if full_distance < mother_distance
            else "tie"
            if full_distance == mother_distance
            else "loss"
        )
        target_scaled = int(
            round(float(targets[name]["strongest_known_target"]) * 1000)
        )
        diagnostics = full_output["mechanism_diagnostics"]
        rows.append(
            {
                "instance": name,
                "seed": SEED,
                "run_order": ">".join(order),
                "mother_distance": mother_distance,
                "mpils_mvns_distance": full_distance,
                "relation": relation,
                "improvement_percent": (
                    (mother_distance - full_distance)
                    / mother_distance
                    * 100
                ),
                "verified_bks": target_scaled,
                "mpils_mvns_gap_to_bks_percent": (
                    (full_distance - target_scaled)
                    / target_scaled
                    * 100
                ),
                "new_bks_candidate": str(
                    full_distance < target_scaled
                ).lower(),
                "mother_iterations": int(
                    outputs[(name, "mother")][
                        "iterations_completed"
                    ]
                ),
                "mpils_mvns_iterations": int(
                    full_output["iterations_completed"]
                ),
                "mother_wall_seconds": elapsed[(name, "mother")],
                "mpils_mvns_wall_seconds": elapsed[
                    (name, "mpils_mvns")
                ],
                "mother_independent_valid": str(
                    independent[(name, "mother")]["all_checks_pass"]
                ).lower(),
                "mpils_mvns_independent_valid": str(
                    independent[(name, "mpils_mvns")][
                        "all_checks_pass"
                    ]
                ).lower(),
                "mechanism_integrity": str(
                    mechanism_ok[name]
                ).lower(),
                "responsibility_action_candidates": (
                    responsibility_actions[name]
                ),
                "expert_triggers": int(
                    diagnostics["expert_triggers"]
                ),
                "expert_accepted": int(
                    diagnostics["expert_accepted"]
                ),
                "expert_seconds": float(
                    diagnostics["expert_seconds"]
                ),
                "population_unique_insertions": int(
                    diagnostics["populations"]["unique_insertions"]
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

    wins = sum(row["relation"] == "win" for row in rows)
    ties = sum(row["relation"] == "tie" for row in rows)
    losses = sum(row["relation"] == "loss" for row in rows)
    new_bks = sum(row["new_bks_candidate"] == "true" for row in rows)
    all_valid = all(
        output["complete"]
        and output["feasible"]
        and independent[key]["all_checks_pass"]
        for key, output in outputs.items()
    )
    all_within_time = all(
        value <= END_TO_END_LIMIT_SECONDS
        for value in elapsed.values()
    )
    all_mechanisms_resident = all(mechanism_ok.values())
    responsibility_generated = (
        sum(responsibility_actions.values()) > 0
    )
    protected_after = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    protected_unchanged = protected_before == protected_after
    integrity = (
        all_valid
        and all_within_time
        and all_mechanisms_resident
        and responsibility_generated
        and protected_unchanged
    )

    if not integrity or losses > 0:
        verdict = "STOP_ANY_LOSS_OR_INTEGRITY"
    elif wins >= 1:
        verdict = "GO_SENTINEL"
    else:
        verdict = "HOLD_NO_INCREMENT"

    decision = {
        "verdict": verdict,
        "wins_vs_mother": wins,
        "ties_vs_mother": ties,
        "losses_vs_mother": losses,
        "development_instances": len(INSTANCES),
        "new_public_bks_candidates": new_bks,
        "all_solutions_complete_feasible_independently_valid": all_valid,
        "all_end_to_end_wall_times_within_10_seconds": all_within_time,
        "all_five_mechanisms_resident_and_consulted": (
            all_mechanisms_resident
        ),
        "responsibility_generated_candidate": responsibility_generated,
        "responsibility_action_candidates_total": sum(
            responsibility_actions.values()
        ),
        "protected_files_unchanged": protected_unchanged,
        "confirmation_sentinels_authorized": verdict == "GO_SENTINEL",
        "china81_small_sample_authorized": (
            verdict == "GO_SENTINEL"
            and False
        ),
        "formal_public_run_authorized": False,
        "formal_china81_run_authorized": False,
        "paper_superiority_claim_allowed": False,
    }
    write_json(OUTPUT / "decision.json", decision)

    metadata = {
        "contract": "EA-MPILS-MVNS-001",
        "working_name": "MPILS-MVNS",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "runner_python": platform.python_version(),
            "pyvrp": version("pyvrp"),
            "solver_python": str(PYTHON.relative_to(REPO)),
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
            "behaviour_test_functions": 5,
            "solver_arms": len(outputs),
            "independent_validation_calls": len(independent),
            "confirmation_instance_calls": 0,
            "china81_calls": 0,
        },
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    write_json(OUTPUT / "metadata.json", metadata)

    table = "\n".join(
        "|{instance}|{mother_distance}|{mpils_mvns_distance}|"
        "{relation}|{improvement_percent:.3f}%|{verified_bks}|"
        "{mpils_mvns_gap_to_bks_percent:.3f}%|"
        "{responsibility_action_candidates}|{expert_accepted}|".format(
            **row
        )
        for row in rows
    )
    report = f"""# MPILS-MVNS 三题工程哨兵

判定：`{verdict}`。

|题|ILS母体|MPILS-MVNS|关系|改善|当前可验BKS|距BKS|责任候选|采纳|
|---|---:|---:|---|---:|---:|---:|---:|---:|
{table}

汇总：`{wins}` 胜、`{ties}` 平、`{losses}` 负；新公开 BKS 候选
`{new_bks}` 个。

完整性：全部解独立有效=`{all_valid}`；全部端到端不超过十秒=
`{all_within_time}`；五类机制常驻且逐次问询=`{all_mechanisms_resident}`；
多车场责任产生候选=`{responsibility_generated}`；保护文件未变化=
`{protected_unchanged}`。

本门只使用三道已经公开的开发题、单种子和短墙钟。`GO_SENTINEL` 也只允许进入
两道事前固定的公开确认哨兵；它不等于算法成功、公开新 BKS、China81 成功或论文
优越性结论。`HOLD` 或 `STOP` 均不得用增加算例数量来救援。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(
        OUTPUT / "artifact_hashes.json",
        build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if verdict == "GO_SENTINEL" else 3


if __name__ == "__main__":
    raise SystemExit(main())
