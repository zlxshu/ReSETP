#!/usr/bin/env python3
"""Orchestrate the frozen six-task TARC G0 without outcome-driven changes."""

from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from baselines.algorithm_prototypes.type_aware_resource_chromosome_20260725.g0_gate.worker import (  # noqa: E402
    NUM_CANDIDATES,
    REPO_ROOT as WORKER_REPO_ROOT,
    run_task,
)


GATE_DIR = Path(__file__).resolve().parent
CONTRACT = (
    REPO_ROOT
    / "docs/handoff/e2_type_aware_resource_chromosome_contract_20260725.md"
)
T0_DECISION = (
    REPO_ROOT
    / "baselines/algorithm_prototypes/"
    "type_aware_resource_chromosome_20260725/t0_engineering_gate/"
    "decision.json"
)
T0_INPUT_HASHES = T0_DECISION.parent / "input_hashes.csv"
V7_ROOT = (
    REPO_ROOT
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
    "full_gate"
)
INSTANCES = (
    "cn-prd-50c-02-V2-LOCATIONS",
    "cn-jjj-100c-02-V2-LOCATIONS",
    "cn-prd-200c-01-V2-LOCATIONS",
)
ARMS = ("ORDER_ONLY", "ORDER_PLUS_TYPE")
WORKERS = 6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def freeze_registration(tasks: list[dict[str, str]]) -> dict[str, Any]:
    source_paths = [
        Path(__file__).resolve(),
        GATE_DIR / "worker.py",
        CONTRACT,
        T0_DECISION,
        T0_INPUT_HASHES,
        V7_ROOT / "raw_runs.csv",
        REPO_ROOT / "solver/src/setp_solver/cost.py",
        REPO_ROOT / "solver/src/setp_solver/check.py",
        REPO_ROOT / "solver/src/setp_solver/search/evaluation.py",
        REPO_ROOT / "solver/src/setp_solver/prices.py",
        REPO_ROOT / "solver/src/setp_solver/china81_completion.py",
    ]
    for instance_id in INSTANCES:
        for seed in (3, 4):
            source_paths.append(
                V7_ROOT
                / "tasks"
                / f"D6-E2-STAGED__{instance_id}__seed{seed}"
                / "solution_witnesses.json"
            )
    payload = {
        "contract_id": "E2-TARC-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
        "workers": WORKERS,
        "candidates_per_task": NUM_CANDIDATES,
        "parent_seeds": [3, 4],
        "instances": list(INSTANCES),
        "arms": list(ARMS),
        "source_hashes": {
            str(path.relative_to(REPO_ROOT)): sha256(path)
            for path in source_paths
        },
        "scientific_limits": {
            "no_iterative_acceptance": True,
            "full_candidate_evaluations_per_task": 32,
            "safety_seconds_per_task": 90.0,
            "charging_strategy": "integrated",
            "carbon_weight": 1.0,
            "depot_charge_window_mode": "same_day_predeparture",
        },
    }
    registration_path = GATE_DIR / "g0_registration.json"
    if registration_path.exists():
        existing = json.loads(registration_path.read_text(encoding="utf-8"))
        comparable = dict(existing)
        comparable.pop("created_at_utc", None)
        candidate = dict(payload)
        candidate.pop("created_at_utc", None)
        if comparable != candidate:
            raise RuntimeError("existing G0 registration does not match")
        return existing
    write_json(registration_path, payload)
    return payload


def main() -> None:
    started = time.perf_counter()
    if REPO_ROOT != WORKER_REPO_ROOT:
        raise RuntimeError("orchestrator/worker project roots differ")
    t0 = json.loads(T0_DECISION.read_text(encoding="utf-8"))
    if (
        t0.get("decision")
        != "PASS_TARC_ZERO_OBJECTIVE_REPRESENTATION_AND_DECODER_GATE"
    ):
        raise RuntimeError("T0 is not formally PASS")

    tasks = [
        {"instance_id": instance_id, "arm": arm}
        for instance_id in INSTANCES
        for arm in ARMS
    ]
    registration = freeze_registration(tasks)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=WORKERS,
        mp_context=context,
    ) as executor:
        futures = {executor.submit(run_task, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # terminal evidence, never an auto-retry
                errors.append(
                    {
                        "instance_id": futures[future]["instance_id"],
                        "arm": futures[future]["arm"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    results.sort(key=lambda row: (row["instance_id"], row["arm"]))
    current_hashes = {
        relative: sha256(REPO_ROOT / relative)
        for relative in registration["source_hashes"]
    }
    drift = {
        relative: {
            "before": registration["source_hashes"][relative],
            "after": current_hashes[relative],
        }
        for relative in registration["source_hashes"]
        if current_hashes[relative] != registration["source_hashes"][relative]
    }
    if errors or drift:
        verdict = "STOP_TARC_G0_EXECUTION_OR_DECODER_FAILURE"
        write_json(
            GATE_DIR / "decision.json",
            {
                "decision": verdict,
                "contract_id": "E2-TARC-001",
                "completed_tasks": len(results),
                "errors": errors,
                "protected_or_registered_drift": drift,
                "next_action": "FINAL_STOP_NO_RESCUE",
            },
        )
        write_json(
            GATE_DIR / "metadata.json",
            {
                "task_id": "E2-TARC-G0-001",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "workers": WORKERS,
                "wall_seconds": time.perf_counter() - started,
                "registration": registration,
                "protected_files_modified": bool(drift),
            },
        )
        (GATE_DIR / "report.md").write_text(
            "\n".join(
                [
                    "# TARC frozen six-task G0",
                    "",
                    f"Decision: `{verdict}`.",
                    "",
                    f"- completed tasks: {len(results)}/6",
                    f"- terminal errors: {len(errors)}",
                    f"- registered hash drift: {len(drift)}",
                    "",
                    "No task was retried and no algorithmic limit was changed.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        artifact_paths = sorted(
            path
            for path in GATE_DIR.iterdir()
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
        write_json(
            GATE_DIR / "artifact_hashes.json",
            {
                str(path.relative_to(GATE_DIR)): sha256(path)
                for path in artifact_paths
            },
        )
        return

    expected_worker_file = str((GATE_DIR / "worker.py").resolve())
    if len({int(row["worker_pid"]) for row in results}) != WORKERS:
        raise RuntimeError("G0 did not use six distinct task workers")
    if any(row["worker_file"] != expected_worker_file for row in results):
        raise RuntimeError("G0 worker resolved the wrong file")
    if any(row["candidate_attempts"] != NUM_CANDIDATES for row in results):
        raise RuntimeError("G0 candidate ledger is incomplete")

    candidate_rows = [
        candidate
        for result in results
        for candidate in result["candidate_rows"]
    ]
    with (GATE_DIR / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(candidate_rows[0]),
        )
        writer.writeheader()
        writer.writerows(candidate_rows)
    with (GATE_DIR / "task_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fields = [
            "instance_id",
            "arm",
            "status",
            "wall_seconds",
            "candidate_attempts",
            "complete_evaluations",
            "feasible_candidates",
            "best_objective",
            "best_candidate_index",
            "parent_objective",
            "strictly_improves_parent",
            "worker_pid",
            "worker_module",
            "worker_file",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {field: result[field] for field in fields}
            for result in results
        )

    by_key = {
        (result["instance_id"], result["arm"]): result
        for result in results
    }
    typed_parent_wins = 0
    typed_control_wins = 0
    typed_control_losses = 0
    attributable_wins = 0
    wall_ratios: list[float] = []
    comparison_rows: list[dict[str, Any]] = []
    for instance_id in INSTANCES:
        control = by_key[(instance_id, "ORDER_ONLY")]
        typed = by_key[(instance_id, "ORDER_PLUS_TYPE")]
        control_best = control["best_objective"]
        typed_best = typed["best_objective"]
        if typed["strictly_improves_parent"]:
            typed_parent_wins += 1
        if typed_best is not None and control_best is not None:
            if typed_best < control_best - 1e-9:
                typed_control_wins += 1
            elif typed_best > control_best + 1e-9:
                typed_control_losses += 1
        best_typed_rows = [
            row
            for row in candidate_rows
            if row["instance_id"] == instance_id
            and row["arm"] == "ORDER_PLUS_TYPE"
            and row["feasible"]
            and typed_best is not None
            and abs(float(row["objective"]) - float(typed_best)) <= 1e-9
        ]
        attributable = any(
            row["labels_differ_from_stronger_parent"]
            and row["strictly_improves_parent"]
            for row in best_typed_rows
        )
        attributable_wins += int(attributable)
        ratio = float(typed["wall_seconds"]) / float(control["wall_seconds"])
        wall_ratios.append(ratio)
        comparison_rows.append(
            {
                "instance_id": instance_id,
                "parent_objective": typed["parent_objective"],
                "order_only_best": control_best,
                "order_plus_type_best": typed_best,
                "typed_improves_parent": typed["strictly_improves_parent"],
                "typed_beats_control": (
                    typed_best is not None
                    and control_best is not None
                    and typed_best < control_best - 1e-9
                ),
                "typed_loses_control": (
                    typed_best is not None
                    and control_best is not None
                    and typed_best > control_best + 1e-9
                ),
                "attributable_label_change": attributable,
                "wall_ratio": ratio,
            }
        )
    with (GATE_DIR / "comparisons.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(comparison_rows[0]),
        )
        writer.writeheader()
        writer.writerows(comparison_rows)

    sorted_ratios = sorted(wall_ratios)
    median_ratio = sorted_ratios[1]
    max_ratio = max(wall_ratios)
    ledger_closed = (
        len(results) == 6
        and len(candidate_rows) == 6 * NUM_CANDIDATES
        and all(result["complete_evaluations"] == NUM_CANDIDATES for result in results)
    )
    pass_gate = (
        ledger_closed
        and typed_parent_wins >= 2
        and typed_control_wins >= 2
        and typed_control_losses == 0
        and attributable_wins >= 1
        and median_ratio <= 1.25
        and max_ratio <= 1.50
    )
    verdict = (
        "PASS_TARC_LOW_COST_CAUSAL_GATE"
        if pass_gate
        else "STOP_TARC_NO_VERIFIED_JOINT_ORDER_RESOURCE_GAIN"
    )
    decision = {
        "decision": verdict,
        "contract_id": "E2-TARC-001",
        "registration_sha256": sha256(GATE_DIR / "g0_registration.json"),
        "ledger_closed": ledger_closed,
        "tasks": len(results),
        "candidate_rows": len(candidate_rows),
        "typed_improves_parent_instances": typed_parent_wins,
        "typed_beats_order_only_instances": typed_control_wins,
        "typed_loses_order_only_instances": typed_control_losses,
        "attributable_label_change_instances": attributable_wins,
        "wall_ratio_median": median_ratio,
        "wall_ratio_max": max_ratio,
        "pass_conditions": {
            "typed_improves_parent_at_least_2_of_3": typed_parent_wins >= 2,
            "typed_beats_control_at_least_2_of_3": typed_control_wins >= 2,
            "typed_zero_loss": typed_control_losses == 0,
            "attributable_label_change_at_least_1": attributable_wins >= 1,
            "median_wall_ratio_at_most_1_25": median_ratio <= 1.25,
            "max_wall_ratio_at_most_1_50": max_ratio <= 1.50,
        },
        "next_action": (
            "If STOP, freeze without rescue. If PASS, only a separately "
            "registered matched-budget A/A+T/A-long gate is authorized."
        ),
    }
    write_json(GATE_DIR / "decision.json", decision)
    write_json(
        GATE_DIR / "metadata.json",
        {
            "task_id": "E2-TARC-G0-001",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": WORKERS,
            "wall_seconds": time.perf_counter() - started,
            "registration": registration,
            "protected_files_modified": False,
        },
    )
    (GATE_DIR / "report.md").write_text(
        "\n".join(
            [
                "# TARC frozen six-task G0",
                "",
                f"Decision: `{verdict}`.",
                "",
                f"- tasks: {len(results)}/6",
                f"- candidate evaluations: {len(candidate_rows)}/"
                f"{6 * NUM_CANDIDATES}",
                f"- ORDER_PLUS_TYPE improves stronger parent: "
                f"{typed_parent_wins}/3",
                f"- ORDER_PLUS_TYPE beats ORDER_ONLY: "
                f"{typed_control_wins}/3; losses {typed_control_losses}/3",
                f"- attributable label-change wins: {attributable_wins}/3",
                f"- wall ratio median/max: "
                f"{median_ratio:.6f}/{max_ratio:.6f}",
                "",
                "No iterative acceptance, long run, public benchmark, E3, "
                "paper claim, or parameter rescue was performed.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    artifact_paths = sorted(
        path
        for path in GATE_DIR.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    write_json(
        GATE_DIR / "artifact_hashes.json",
        {
            str(path.relative_to(GATE_DIR)): sha256(path)
            for path in artifact_paths
        },
    )


if __name__ == "__main__":
    main()
