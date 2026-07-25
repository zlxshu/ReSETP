#!/usr/bin/env python3
"""Run the pre-registered six-task HGS-ILS-XD complementarity gate."""

from __future__ import annotations

import csv
import multiprocessing as mp
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import (
    INPUT_MANIFEST,
    OUT,
    REGISTRATION,
    THREAD_ENV,
    file_sha256,
    payload_sha256,
    read_json,
    source_hashes,
    task_id,
    write_json,
)
from g0_worker import resource_probe, run_task


def _memory_free_ratio() -> float:
    completed = subprocess.run(
        ["memory_pressure", "-Q"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    match = re.search(
        r"System-wide memory free percentage:\s*([0-9.]+)%",
        completed.stdout + completed.stderr,
    )
    if match:
        return float(match.group(1)) / 100.0

    total = int(
        subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    )
    vm = subprocess.run(
        ["vm_stat"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    page_match = re.search(r"page size of (\d+) bytes", vm)
    if not page_match:
        raise RuntimeError("cannot parse vm_stat page size")
    page_size = int(page_match.group(1))
    available_pages = 0
    for label in (
        "Pages free",
        "Pages inactive",
        "Pages speculative",
        "Pages purgeable",
    ):
        row = re.search(
            rf"^{re.escape(label)}:\s+([0-9]+)\.",
            vm,
            flags=re.MULTILINE,
        )
        if row:
            available_pages += int(row.group(1))
    return min(1.0, available_pages * page_size / total)


def _tasks(
    registration: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    budget = registration["budget"]
    for instance_id in registration["instances"]:
        instance_manifest = manifest["instances"][instance_id]
        for start_kind in ("cold", "warm"):
            tasks.append(
                {
                    "task_id": task_id(instance_id, start_kind),
                    "instance_id": instance_id,
                    "start_kind": start_kind,
                    "instance_manifest": instance_manifest,
                    "seed": int(budget["pyvrp_seed_per_task"]),
                    "iterations": int(
                        budget["ils_outer_iterations_per_task"]
                    ),
                    "candidate_limit": int(
                        budget[
                            "maximum_distinct_complete_evaluations_per_task"
                        ]
                    ),
                    "safety_seconds": float(
                        budget["wall_clock_safety_seconds_per_task"]
                    ),
                    "probe_hold_seconds": 2.0,
                }
            )
    return tasks


def _parallel_map(
    function: Callable[[Mapping[str, Any]], dict[str, Any]],
    tasks: list[dict[str, Any]],
    workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    context = mp.get_context("spawn")
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
    ) as pool:
        futures = {
            pool.submit(function, task): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                result["task_id"] = task["task_id"]
                results.append(result)
            except Exception as exc:  # noqa: BLE001 - persist worker evidence
                errors.append(
                    {
                        "task_id": str(task["task_id"]),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    return sorted(results, key=lambda row: row["task_id"]), sorted(
        errors,
        key=lambda row: row["task_id"],
    )


def _probe_attempt(
    tasks: list[dict[str, Any]],
    workers: int,
) -> dict[str, Any]:
    before = _memory_free_ratio()
    results, errors = _parallel_map(resource_probe, tasks, workers)
    after = _memory_free_ratio()
    peak_by_pid: dict[int, float] = {}
    for row in results:
        pid = int(row["pid"])
        peak_by_pid[pid] = max(
            peak_by_pid.get(pid, 0.0),
            float(row["peak_rss_mib"]),
        )
    combined = sum(peak_by_pid.values())
    all_loads = (
        len(results) == len(tasks)
        and not errors
        and all(row["engine_family"] == "ILS" for row in results)
        and all(bool(row["initial_complete"]) for row in results)
    )
    if workers == 6:
        all_loads = all_loads and len(peak_by_pid) == 6
    return {
        "workers": workers,
        "tasks": results,
        "errors": errors,
        "distinct_worker_pids": len(peak_by_pid),
        "free_memory_ratio_before": before,
        "free_memory_ratio_after": after,
        "minimum_free_memory_ratio": min(before, after),
        "combined_peak_rss_mib": combined,
        "all_loads_pass": all_loads,
    }


def _choose_workers(
    tasks: list[dict[str, Any]],
    registration: Mapping[str, Any],
) -> tuple[int | None, dict[str, Any]]:
    gate = registration["parallelism"]["resource_gate"]
    min_free = float(gate["minimum_free_memory_ratio"])
    max_rss = float(gate["maximum_combined_peak_rss_mib"])
    attempts = [_probe_attempt(tasks, 6)]
    first = attempts[0]
    first_pass = (
        first["all_loads_pass"]
        and first["minimum_free_memory_ratio"] >= min_free
        and first["combined_peak_rss_mib"] <= max_rss
    )
    if first_pass:
        return 6, {"attempts": attempts, "selected_workers": 6}

    attempts.append(_probe_attempt(tasks, 3))
    fallback = attempts[1]
    fallback_pass = (
        fallback["all_loads_pass"]
        and fallback["minimum_free_memory_ratio"] >= min_free
        and fallback["combined_peak_rss_mib"] <= max_rss
    )
    return (
        3 if fallback_pass else None,
        {
            "attempts": attempts,
            "selected_workers": 3 if fallback_pass else None,
        },
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "task_id",
        "instance_id",
        "start_kind",
        "seed",
        "status",
        "iterations_completed",
        "search_calls",
        "distinct_proxy_feasible_generated_candidates",
        "selected_complete_evaluation_attempts",
        "exact_feasible_generated_candidates",
        "official_final_differs_from_start",
        "has_route_outside_v7_reference_pool",
        "has_exact_feasible_adjacency_change",
        "start_exact_objective",
        "best_exact_objective",
        "strictly_improves_start",
        "improvement_over_start",
        "runtime_seconds",
        "peak_rss_mib",
    ]
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})
    temporary.replace(path)


def _write_artifact_hashes() -> None:
    artifacts = {
        str(path.relative_to(OUT)): file_sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "artifacts": artifacts,
        },
    )


def _write_report(
    decision: Mapping[str, Any],
    workers: int | None,
) -> None:
    lines = [
        "# HGS-ILS-XD G0 complementarity preflight",
        "",
        f"Verdict: `{decision['verdict']}`",
        "",
        f"Selected workers: {workers}",
        "",
        (
            "This gate tests only whether independent ILS creates full-model-"
            "feasible customer orders outside the sealed v7 HGS-family route "
            "pool and adds value after an HGS handoff. It is not a "
            "performance, BKS, SOTA, paper, or E3 result."
        ),
        "",
        "## Gate counts",
        "",
        f"- exact-feasible tasks: {decision['exact_feasible_tasks']}/6",
        (
            f"- cold-start feasible instances: "
            f"{decision['cold_start_feasible_instances']}/3"
        ),
        (
            f"- instances with a route outside the sealed reference pool: "
            f"{decision['instances_with_route_outside_pool']}/3"
        ),
        (
            f"- warm-start instances with changed customer adjacency: "
            f"{decision['warm_instances_with_adjacency_change']}/3"
        ),
        (
            f"- warm-start instances strictly improved by ILS: "
            f"{decision['warm_instances_strictly_improved']}/3"
        ),
        (
            f"- instances where warm ILS beats cold ILS: "
            f"{decision['warm_beats_cold_instances']}/3"
        ),
        "",
        (
            "No parameter, instance, seed, completion, scorer, or stop rule "
            "was changed after results."
        ),
    ]
    (OUT / "report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _finalize_resource_halt(
    registration: Mapping[str, Any],
    manifest: Mapping[str, Any],
    probe: Mapping[str, Any],
    source_start: Mapping[str, str],
) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "resource_probe.json", probe)
    _write_csv(OUT / "raw_runs.csv", [])
    source_end = source_hashes()
    decision = {
        "schema": "resetp.hgs-ils-xd.g0-decision.v1",
        "pass": False,
        "verdict": "HALT_HGS_ILS_XD_G0_RESOURCE_GATE",
        "reason": "Neither the six-worker gate nor the registered three-worker fallback proved safe.",
        "exact_feasible_tasks": 0,
        "cold_start_feasible_instances": 0,
        "instances_with_route_outside_pool": 0,
        "warm_instances_with_adjacency_change": 0,
        "warm_instances_strictly_improved": 0,
        "warm_beats_cold_instances": 0,
        "source_drift": source_start != source_end,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.hgs-ils-xd.g0-metadata.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "registration_sha256": file_sha256(REGISTRATION),
            "input_manifest_sha256": file_sha256(INPUT_MANIFEST),
            "registration": registration,
            "input_manifest_identity": payload_sha256(manifest),
            "source_hashes_start": source_start,
            "source_hashes_end": source_end,
            "search_task_count": 0,
        },
    )
    _write_report(decision, None)
    _write_artifact_hashes()
    return 2


def main() -> int:
    for key, value in THREAD_ENV.items():
        if os.environ.get(key, value) != value:
            raise RuntimeError(f"{key} must equal {value}")
        os.environ[key] = value
    if OUT.exists():
        raise RuntimeError(
            f"G0 output already exists and will not be overwritten: {OUT}"
        )
    registration = read_json(REGISTRATION)
    manifest = read_json(INPUT_MANIFEST)
    if manifest["registration_sha256"] != file_sha256(REGISTRATION):
        raise RuntimeError("input manifest registration hash drift")
    source_start = source_hashes()
    tasks = _tasks(registration, manifest)
    if len(tasks) != 6:
        raise RuntimeError(f"expected six tasks, found {len(tasks)}")

    workers, probe = _choose_workers(tasks, registration)
    if workers is None:
        return _finalize_resource_halt(
            registration,
            manifest,
            probe,
            source_start,
        )

    results, errors = _parallel_map(run_task, tasks, workers)
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "resource_probe.json", probe)
    task_dir = OUT / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    for row in results:
        write_json(task_dir / f"{row['task_id']}.json", row)
    if errors:
        write_json(OUT / "task_errors.json", errors)

    raw_rows: list[dict[str, Any]] = []
    for row in results:
        raw_rows.append(
            {
                **row,
                "status": (
                    "EXACT_FEASIBLE"
                    if row["has_exact_feasible_output"]
                    else "NO_EXACT_FEASIBLE_GENERATED_CANDIDATE"
                ),
            }
        )
    _write_csv(OUT / "raw_runs.csv", raw_rows)

    exact_feasible = sum(
        bool(row["has_exact_feasible_output"]) for row in results
    )
    cold_feasible = sum(
        row["start_kind"] == "cold"
        and bool(row["has_exact_feasible_output"])
        for row in results
    )
    outside_instances = {
        row["instance_id"]
        for row in results
        if row["has_route_outside_v7_reference_pool"]
    }
    warm_changed = sum(
        row["start_kind"] == "warm"
        and row["has_exact_feasible_adjacency_change"]
        for row in results
    )
    warm_improved = sum(
        row["start_kind"] == "warm"
        and bool(row["strictly_improves_start"])
        for row in results
    )
    by_instance = {
        instance_id: {
            row["start_kind"]: row
            for row in results
            if row["instance_id"] == instance_id
        }
        for instance_id in registration["instances"]
    }
    warm_beats_cold_instances = [
        instance_id
        for instance_id, lanes in by_instance.items()
        if set(lanes) == {"cold", "warm"}
        and lanes["warm"]["best_exact_objective"] is not None
        and lanes["cold"]["best_exact_objective"] is not None
        and float(lanes["warm"]["best_exact_objective"])
        < float(lanes["cold"]["best_exact_objective"]) - 1.0e-9
    ]
    budget_ok = all(
        int(row["iterations_completed"]) == 128
        and int(row["selected_complete_evaluation_attempts"]) <= 8
        for row in results
    )
    source_end = source_hashes()
    source_drift = source_start != source_end
    passed = (
        not errors
        and len(results) == 6
        and exact_feasible == 6
        and cold_feasible == 3
        and len(outside_instances) >= 2
        and warm_changed >= 2
        and warm_improved >= 2
        and len(warm_beats_cold_instances) >= 2
        and budget_ok
        and not source_drift
    )
    decision = {
        "schema": "resetp.hgs-ils-xd.g0-decision.v1",
        "pass": passed,
        "verdict": (
            "PASS_HGS_ILS_XD_G0_FEASIBLE_COMPLEMENTARITY"
            if passed
            else "STOP_HGS_ILS_XD_G0_NO_FEASIBLE_COMPLEMENTARITY"
        ),
        "claim_boundary": (
            "Complementarity engineering signal only. No performance, "
            "paper, E3, China81 full-campaign, BKS, or SOTA claim."
        ),
        "selected_workers": workers,
        "task_results": len(results),
        "task_errors": errors,
        "exact_feasible_tasks": exact_feasible,
        "cold_start_feasible_instances": cold_feasible,
        "instances_with_route_outside_pool": len(outside_instances),
        "route_outside_pool_instances": sorted(outside_instances),
        "warm_instances_with_adjacency_change": warm_changed,
        "warm_instances_strictly_improved": warm_improved,
        "warm_beats_cold_instances": len(warm_beats_cold_instances),
        "warm_beats_cold_instance_ids": warm_beats_cold_instances,
        "budget_ok": budget_ok,
        "source_drift": source_drift,
        "next_step": (
            "IMPLEMENT_PREREGISTERED_MATCHED_BUDGET_G1"
            if passed
            else "FREEZE_CANDIDATE__NO_TUNING_OR_RERUN"
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.hgs-ils-xd.g0-metadata.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "registration_sha256": file_sha256(REGISTRATION),
            "input_manifest_sha256": file_sha256(INPUT_MANIFEST),
            "registration": registration,
            "input_manifest_identity": payload_sha256(manifest),
            "source_hashes_start": source_start,
            "source_hashes_end": source_end,
            "search_task_count": len(results),
            "resource_probe": probe,
        },
    )
    _write_report(decision, workers)
    _write_artifact_hashes()
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
