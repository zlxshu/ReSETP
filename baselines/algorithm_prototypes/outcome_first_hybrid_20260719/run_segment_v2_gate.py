#!/usr/bin/env python3
"""Cancelled donor03 performance gate for SEG-GEN-02.

The user subsequently restricted private performance evidence to China81.
This file is retained to document the never-run plan and fails closed before
starting any worker.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
UNIFIED = (
    REPO
    / "baselines/algorithm_prototypes/unified_mechanism_alns_20260719"
)
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    UNIFIED,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bounded_segment_generation_alns import (  # noqa: E402
    BoundedSegmentAlnsConfig,
    run_bounded_segment_generation_alns,
)
from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
)


BUNDLES = HERE / "fresh_segment_v2_bundles"
TASKS = (
    "DEV-seggen-v2-donor03-100c",
    "DEV-seggen-v2-donor03-150c",
)
ARMS = ("control", "mechanism", "distance")
ARM_MODES = {
    "control": "disabled",
    "mechanism": "mechanism",
    "distance": "distance",
}
OUT = HERE / "segment_v2_fresh_warning_gate"
SEED = 1
BUDGET = 100
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
TOL = 1.0e-9
WORKER_SENTINEL = "SEG_GEN_02_WORKER_JSON="
FIXED_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "SETP_E3_STRICT_MULTITRIP": "0",
    "SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC": "0",
    "SETP_E2_ALNS_CHECKPOINT_PATH": "",
}
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    UNIFIED / "mechanism_segment_generator.py",
    UNIFIED / "segment_generation_alns.py",
)
SOURCES = (
    Path(__file__).resolve(),
    HERE / "bounded_segment_generator.py",
    HERE / "bounded_segment_generation_alns.py",
    HERE / "build_fresh_segment_v2_bundles.py",
    HERE / "test_bounded_segment_generator.py",
    REPO
    / "docs/handoff/outcome_first_multiengine_hybrid_contract_20260719.md",
)
SCOPE_CANCELLED = True


def main() -> int:
    if SCOPE_CANCELLED:
        raise RuntimeError(
            "CANCELLED_SCOPE_PRIVATE_PERFORMANCE_CHINA81_ONLY"
        )
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        return _worker()
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    _verify_bundle_manifest()
    source_hashes = _hash_map(SOURCES)
    protected_hashes = _hash_map(PROTECTED)
    input_hashes = _input_hashes()
    starts = {
        task: _shared_start(BUNDLES / task)
        for task in TASKS
    }
    run_order = sorted(
        (
            (task, arm)
            for task in TASKS
            for arm in ARMS
        ),
        key=lambda item: _sha_text(
            f"{item[0]}:{item[1]}:seed={SEED}:B={BUDGET}"
        ),
    )

    payloads: dict[tuple[str, str], dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    for task, arm in run_order:
        try:
            payloads[(task, arm)] = _invoke_worker(
                BUNDLES / task,
                arm=arm,
                shared_start=starts[task],
            )
        except Exception as error:  # preserve the gate rather than hide it
            failures.append(
                {
                    "task": task,
                    "arm": arm,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    if not failures:
        for task in TASKS:
            witnesses[task] = {
                "shared_start": asdict(starts[task]),
                "start_signature": solution_signature_hash(starts[task]),
                "arms": {},
            }
            for arm in ARMS:
                row, solution = _normalize(
                    BUNDLES / task,
                    payloads[(task, arm)],
                )
                rows.append(row)
                witnesses[task]["arms"][arm] = {
                    "solution": asdict(solution),
                    "signature": row["final_signature"],
                    "cost": row["parent_recomputed_cost"],
                }

    comparisons = (
        _comparisons(rows)
        if not failures
        else {"tasks": {}, "speed_ratios": []}
    )
    drift = {
        "sources_unchanged": source_hashes == _hash_map(SOURCES),
        "protected_unchanged": (
            protected_hashes == _hash_map(PROTECTED)
        ),
        "inputs_unchanged": input_hashes == _input_hashes(),
    }
    decision = _decision(rows, comparisons, drift, failures)
    metadata = {
        "schema_version": "resetp.seg-gen-02.fresh-warning.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "tasks": list(TASKS),
        "arms": list(ARMS),
        "seed": SEED,
        "complete_candidate_budget_per_arm": BUDGET,
        "prices": asdict(PRICES),
        "run_order": [
            {"task": task, "arm": arm}
            for task, arm in run_order
        ],
        "fixed_environment": FIXED_ENVIRONMENT,
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "input_hashes": input_hashes,
        "bundle_manifest_sha256": _sha(BUNDLES / "manifest.json"),
        "inventory_correction": (
            "The planned 75 source scale does not exist. Before any "
            "performance run it was replaced with untouched raw scales "
            "100 and 150; no synthetic scaling was introduced."
        ),
        "claim_boundary": (
            "Two fresh scales, one seed, development warning only. "
            "Not formal benchmark, stage-two, China81, or manuscript evidence."
        ),
    }

    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", rows, failures=failures)
    _write_json(OUT / "comparisons.json", comparisons)
    _write_json(OUT / "solution_witnesses.json", witnesses)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_text(
        OUT / "report.md",
        _report(rows, comparisons, decision),
    )
    _write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: _sha(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


def _worker() -> int:
    request = json.loads(sys.stdin.read())
    arm = str(request["arm"])
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    bundle_dir = Path(request["bundle"])
    start = _solution_from_payload(request["shared_start"])
    result = run_bounded_segment_generation_alns(
        bundle_dir,
        seed=SEED,
        prices=PRICES,
        initial_solution=start,
        config=BoundedSegmentAlnsConfig(
            total_eval_budget=BUDGET,
            runtime_cap_seconds=3600.0,
            mode=ARM_MODES[arm],
            assessment_interval=20,
            cooldown_evaluations=100,
            min_segment_length=2,
            max_segment_length=3,
            max_source_segments=64,
            max_positions_per_source=6,
            max_local_exact_candidates=48,
            max_completed_candidates=12,
            apply_terminal_completion=True,
        ),
    )
    loaded = load_search_bundle(bundle_dir)
    replay = independent_cost(
        bundle_dir,
        result.best_solution,
        PRICES,
    )
    violations = check_solution(
        result.best_solution,
        loaded.instance,
        PRICES,
    )
    payload = {
        "arm": arm,
        "algorithm": result.algorithm,
        "start_signature": solution_signature_hash(start),
        "start_cost": independent_cost(
            bundle_dir,
            start,
            PRICES,
        ),
        "evaluations": int(result.evaluations),
        "elapsed_seconds": float(result.elapsed_seconds),
        "claimed_final_cost": float(result.best_cost),
        "worker_recomputed_cost": float(replay),
        "worker_feasible": bool(
            result.feasible and not violations
        ),
        "worker_violation_count": len(violations),
        "final_solution": asdict(result.best_solution),
        "activity": result.mechanism_activity,
    }
    print(
        WORKER_SENTINEL
        + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    )
    return 0


def _invoke_worker(
    bundle_dir: Path,
    *,
    arm: str,
    shared_start: Solution,
) -> dict[str, Any]:
    request = {
        "bundle": str(bundle_dir.resolve()),
        "arm": arm,
        "shared_start": asdict(shared_start),
    }
    environment = dict(os.environ)
    environment.update(FIXED_ENVIRONMENT)
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        cwd=REPO,
        env=environment,
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=4000,
        check=False,
    )
    process_elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"worker failed: {bundle_dir.name}:{arm}\n"
            f"stdout:\n{completed.stdout[-4000:]}\n"
            f"stderr:\n{completed.stderr[-4000:]}"
        )
    lines = [
        line
        for line in completed.stdout.splitlines()
        if line.startswith(WORKER_SENTINEL)
    ]
    if len(lines) != 1:
        raise RuntimeError(
            f"worker payload count {len(lines)}: "
            f"{bundle_dir.name}:{arm}"
        )
    payload = json.loads(lines[0][len(WORKER_SENTINEL) :])
    payload["worker_process_elapsed_seconds"] = process_elapsed
    return payload


def _normalize(
    bundle_dir: Path,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], Solution]:
    solution = _solution_from_payload(payload["final_solution"])
    loaded = load_search_bundle(bundle_dir)
    parent_replay = independent_cost(
        bundle_dir,
        solution,
        PRICES,
    )
    violations = check_solution(
        solution,
        loaded.instance,
        PRICES,
    )
    activity = dict(payload["activity"])
    diagnostics = dict(
        activity.get("segment_diagnostics", {})
    )
    events = list(diagnostics.get("events", []))
    accepted_events = [
        event for event in events if bool(event.get("accepted", False))
    ]
    distance_worse_chain = any(
        event.get("activity", {}).get("selected") is not None
        and float(
            event["activity"]["selected"].get(
                "distance_delta",
                0.0,
            )
        )
        > TOL
        and float(event.get("objective_delta", 0.0)) < -TOL
        for event in accepted_events
    )
    bounds_ok = all(
        _event_bounds_ok(event)
        for event in events
        if event.get("activity")
    )
    row = {
        "task": bundle_dir.name,
        "arm": str(payload["arm"]),
        "algorithm": str(payload["algorithm"]),
        "seed": SEED,
        "complete_candidate_budget": BUDGET,
        "start_signature": str(payload["start_signature"]),
        "start_cost": float(payload["start_cost"]),
        "evaluations": int(payload["evaluations"]),
        "algorithm_elapsed_seconds": float(
            payload["elapsed_seconds"]
        ),
        "worker_process_elapsed_seconds": float(
            payload["worker_process_elapsed_seconds"]
        ),
        "claimed_final_cost": float(payload["claimed_final_cost"]),
        "worker_recomputed_cost": float(
            payload["worker_recomputed_cost"]
        ),
        "parent_recomputed_cost": float(parent_replay),
        "cost_replay_match": (
            abs(
                float(payload["claimed_final_cost"])
                - float(parent_replay)
            )
            <= 1.0e-7
        ),
        "feasible": bool(
            payload["worker_feasible"] and not violations
        ),
        "violation_count": len(violations),
        "final_signature": solution_signature_hash(solution),
        "segment_attempt_count": int(
            dict(diagnostics.get("attempts", {})).get(
                "responsibility_segment_generation",
                0,
            )
        ),
        "segment_accept_count": int(
            dict(diagnostics.get("accepted", {})).get(
                "responsibility_segment_generation",
                0,
            )
        ),
        "distance_worse_full_cost_better_chain": bool(
            distance_worse_chain
        ),
        "bounds_ok": bool(bounds_ok),
        "events_json": json.dumps(
            events,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }
    return row, solution


def _event_bounds_ok(event: dict[str, Any]) -> bool:
    activity = event.get("activity", {})
    ledger = activity.get("ledger")
    if not isinstance(ledger, dict):
        return True
    return (
        int(ledger.get("source_segments_shortlisted", 0)) <= 64
        and int(ledger.get("maximum_positions_for_one_source", 0))
        <= 6
        and int(ledger.get("candidate_build_attempts", 0))
        <= 64 * 6
        and int(ledger.get("exact_candidates_shortlisted", 0))
        <= 48
        and int(ledger.get("completion_candidates_screened", 0))
        <= 12
        and int(
            ledger.get(
                "complete_candidate_evaluations_before_submission",
                0,
            )
        )
        == 0
    )


def _comparisons(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {
        (str(row["task"]), str(row["arm"])): row
        for row in rows
    }
    task_rows: dict[str, Any] = {}
    speed_ratios = []
    for task in TASKS:
        control = by_key[(task, "control")]
        mechanism = by_key[(task, "mechanism")]
        distance = by_key[(task, "distance")]
        mechanism_cost = float(mechanism["parent_recomputed_cost"])
        control_cost = float(control["parent_recomputed_cost"])
        distance_cost = float(distance["parent_recomputed_cost"])
        ratio = float(
            mechanism["worker_process_elapsed_seconds"]
        ) / max(
            TOL,
            float(control["worker_process_elapsed_seconds"]),
        )
        speed_ratios.append(ratio)
        task_rows[task] = {
            "control_cost": control_cost,
            "mechanism_cost": mechanism_cost,
            "distance_cost": distance_cost,
            "mechanism_minus_control": (
                mechanism_cost - control_cost
            ),
            "mechanism_minus_distance": (
                mechanism_cost - distance_cost
            ),
            "mechanism_nonloss_vs_control": (
                mechanism_cost <= control_cost + TOL
            ),
            "mechanism_strict_win_vs_control": (
                mechanism_cost < control_cost - TOL
            ),
            "mechanism_strict_win_vs_distance": (
                mechanism_cost < distance_cost - TOL
            ),
            "mechanism_wall_ratio_vs_control": ratio,
            "distance_worse_full_cost_better_chain": bool(
                mechanism[
                    "distance_worse_full_cost_better_chain"
                ]
            ),
        }
    return {
        "tasks": task_rows,
        "speed_ratios": speed_ratios,
        "median_mechanism_wall_ratio": float(median(speed_ratios)),
        "max_mechanism_wall_ratio": float(max(speed_ratios)),
    }


def _decision(
    rows: list[dict[str, Any]],
    comparisons: dict[str, Any],
    drift: dict[str, bool],
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    if failures:
        return {
            "verdict": "STOP_SEG_GEN_02_EXECUTION_FAILURE",
            "passed": False,
            "execution_failures": failures,
            "formal_search_allowed": False,
            "stage2_allowed": False,
            "three_seed_development_repeat_allowed": False,
        }
    task_rows = list(comparisons["tasks"].values())
    integrity = (
        len(rows) == len(TASKS) * len(ARMS)
        and all(bool(row["cost_replay_match"]) for row in rows)
        and all(bool(row["feasible"]) for row in rows)
        and all(int(row["evaluations"]) == BUDGET for row in rows)
        and all(bool(row["bounds_ok"]) for row in rows)
        and all(drift.values())
        and all(
            len(
                {
                    row["start_signature"]
                    for row in rows
                    if row["task"] == task
                }
            )
            == 1
            for task in TASKS
        )
    )
    quality = (
        all(
            bool(item["mechanism_nonloss_vs_control"])
            for item in task_rows
        )
        and any(
            bool(item["mechanism_strict_win_vs_control"])
            for item in task_rows
        )
        and any(
            bool(item["mechanism_strict_win_vs_distance"])
            for item in task_rows
        )
        and any(
            bool(item["distance_worse_full_cost_better_chain"])
            for item in task_rows
        )
    )
    speed = (
        float(comparisons["median_mechanism_wall_ratio"])
        <= 1.25 + TOL
        and float(comparisons["max_mechanism_wall_ratio"])
        <= 1.50 + TOL
    )
    passed = bool(integrity and quality and speed)
    if passed:
        verdict = "STRONG_POSITIVE_SEG_GEN_02_ALLOW_THREE_SEED_DEV"
    elif not integrity:
        verdict = "STOP_SEG_GEN_02_INTEGRITY"
    elif not quality:
        verdict = "STOP_SEG_GEN_02_QUALITY_NO_RESCUE"
    else:
        verdict = "STOP_SEG_GEN_02_SPEED_NO_RESCUE"
    return {
        "verdict": verdict,
        "passed": passed,
        "integrity_gate_pass": bool(integrity),
        "quality_gate_pass": bool(quality),
        "speed_gate_pass": bool(speed),
        "median_mechanism_wall_ratio_limit": 1.25,
        "max_mechanism_wall_ratio_limit": 1.50,
        "execution_failures": [],
        "drift_checks": drift,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "three_seed_development_repeat_allowed": passed,
        "next_action": (
            "three_seed_development_repeat_only"
            if passed
            else "freeze_SEG_GEN_02_without_result_based_rescue"
        ),
    }


def _shared_start(bundle_dir: Path) -> Solution:
    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    return annotate_cross_site_services(solution, owners)


def _solution_from_payload(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[
                    str(value) for value in row["node_sequence"]
                ],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
                charge_day_offset=int(row.get("charge_day_offset", 0)),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def _verify_bundle_manifest() -> None:
    payload = json.loads(
        (BUNDLES / "manifest.json").read_text(encoding="utf-8")
    )
    ids = [
        str(row["instance_id"])
        for row in payload.get("instances", [])
    ]
    if ids != list(TASKS):
        raise RuntimeError(
            f"bundle manifest does not match frozen tasks: {ids}"
        )


def _report(
    rows: list[dict[str, Any]],
    comparisons: dict[str, Any],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# SEG-GEN-02 新鲜规模质量—速度门",
        "",
        f"- 判决：`{decision['verdict']}`",
        "- 边界：donor03 未运行过的 100/150 原始档、共同 seed 1、"
        "每臂100次完整候选评价；不是正式试验。",
        "",
    ]
    if rows:
        lines.extend(
            [
                "|题|控制|有界机制|里程删减|机制-控制|墙钟比|",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for task in TASKS:
            item = comparisons["tasks"][task]
            lines.append(
                f"|{task}|{item['control_cost']:.6f}|"
                f"{item['mechanism_cost']:.6f}|"
                f"{item['distance_cost']:.6f}|"
                f"{item['mechanism_minus_control']:.6f}|"
                f"{item['mechanism_wall_ratio_vs_control']:.3f}|"
            )
        lines.extend(
            [
                "",
                f"墙钟中位比={comparisons['median_mechanism_wall_ratio']:.3f}，"
                f"最大比={comparisons['max_mechanism_wall_ratio']:.3f}。",
            ]
        )
    if decision.get("execution_failures"):
        lines.extend(
            [
                "",
                "执行失败：",
                "```json",
                json.dumps(
                    decision["execution_failures"],
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "合同规定：任何质量、速度或完整性失败都冻结本候选，"
            "不得在这两题上调参救援。",
            "",
        ]
    )
    return "\n".join(lines)


def _input_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for task in TASKS
        for path in sorted((BUNDLES / task).iterdir())
        if path.is_file() and not path.name.startswith("._")
    } | {
        str((BUNDLES / "manifest.json").relative_to(REPO)): _sha(
            BUNDLES / "manifest.json"
        )
    }


def _hash_map(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for path in paths
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    failures: list[dict[str, str]],
) -> None:
    if rows:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(buffer.getvalue(), encoding="utf-8")
        return
    fields = ("task", "arm", "error")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(failures)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
