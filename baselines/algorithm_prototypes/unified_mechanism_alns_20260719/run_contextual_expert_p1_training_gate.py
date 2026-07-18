#!/usr/bin/env python3
"""Run the frozen P1 three-instance paired training gate.

This is a development screen on three already-burned instances.  It compares
the same continuous ALNS wrapper with model-specific prescriptions disabled or
enabled.  Both arms receive the exact same serialized start, seed, complete
candidate budget, price parameters, terminal completion, and independent
replay.  Each arm runs in a fresh child process so mutable caches cannot leak
between paired tasks.

Passing this gate only permits a fresh, still-small D3 check.  It is not a
paper result and never activates stage two or a formal benchmark run.
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
import platform
from statistics import median
import subprocess
import sys
import time
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for search_path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from contextual_expert_solver import (  # noqa: E402
    ContextualExpertConfig,
    run_contextual_expert_alns,
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


ARCHIVE = (
    REPO
    / "models/data_bundle/generated_instances/"
    "L-main_size_preserving_v2_archive_20260710"
)
INSTANCES = (
    "L-main-threeshift-20c-01",
    "L-main-threeshift-25c-01",
    "L-main-threeshift-50c-01",
)
ARMS = ("control", "candidate")
SEED = 1
BUDGET = 100
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
TOL = 1.0e-9
P0_DIR = HERE / "contextual_expert_behavior_gate"
WORKER_SENTINEL = "P1_WORKER_JSON="
OUTPUT_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "comparisons.json",
    "decision.json",
    "solution_witnesses.json",
    "report.md",
)
PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)
SOURCE_FILES = (
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "run_contextual_expert_p1_training_gate.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "contextual_expert_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "initial_pool.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "terminal_completion.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "prototype.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v4_mechanism_alns_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v5_carbon_retiming_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v6_monotone_mechanism_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v7_responsibility_solver.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/"
    "construction.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/"
    "mechanism_prescription.py",
    "solver/src/setp_solver/algorithms/resetp_alns/runtime/"
    "budgeted_scoring.py",
    "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    "docs/handoff/context_gated_exact_mechanism_contract_20260719.md",
)
FIXED_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "SETP_E3_STRICT_MULTITRIP": "0",
    "SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC": "0",
    "SETP_E2_ALNS_CHECKPOINT_PATH": "",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HERE / "contextual_expert_p1_training_gate",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    _freeze_environment()
    if args.worker:
        return _worker_main()

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(
            f"P1 output directory must not already exist: {output_dir}"
        )
    p0_preflight = _verify_p0()
    _require_clean_sources()
    source_hashes_before = {
        path: _sha256(REPO / path) for path in SOURCE_FILES
    }
    protected_hashes_before = {
        path: _sha256(REPO / path) for path in PROTECTED_FILES
    }
    input_hashes_before = _input_hashes(
        {ARCHIVE / instance for instance in INSTANCES}
    )

    shared_starts = {
        instance: _shared_start(ARCHIVE / instance)
        for instance in INSTANCES
    }
    run_order = sorted(
        (
            (instance, arm)
            for instance in INSTANCES
            for arm in ARMS
        ),
        key=lambda item: _sha_text(
            f"{item[0]}:{item[1]}:seed={SEED}:B={BUDGET}"
        ),
    )

    started = time.perf_counter()
    worker_payloads: dict[tuple[str, str], dict[str, Any]] = {}
    for instance, arm in run_order:
        worker_payloads[(instance, arm)] = _invoke_worker(
            ARCHIVE / instance,
            instance=instance,
            arm=arm,
            shared_start=shared_starts[instance],
        )

    rows: list[dict[str, Any]] = []
    witnesses: dict[str, dict[str, Any]] = {}
    for instance in INSTANCES:
        _add_witness(
            witnesses,
            shared_starts[instance],
            {
                "kind": "shared_start",
                "instance": instance,
                "used_by": list(ARMS),
            },
        )
        for arm in ARMS:
            payload = worker_payloads[(instance, arm)]
            row, final_solution = _normalize_worker_payload(
                ARCHIVE / instance,
                payload,
            )
            rows.append(row)
            _add_witness(
                witnesses,
                final_solution,
                {
                    "kind": "final",
                    "instance": instance,
                    "arm": arm,
                },
            )

    comparisons = _comparisons(rows)
    drift_failures = _detect_runtime_drift(
        source_hashes_before,
        protected_hashes_before,
        input_hashes_before,
    )
    decision = _decision(
        rows,
        comparisons,
        p0_preflight=p0_preflight,
        drift_failures=drift_failures,
    )
    metadata = {
        "schema_version": (
            "resetp.context-gated-exact-mechanism-p1-training.v1"
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "instances": list(INSTANCES),
        "arms": list(ARMS),
        "seed": SEED,
        "complete_candidate_budget_per_arm": BUDGET,
        "assessment_interval": 20,
        "per_mechanism_cooldown": 60,
        "run_order": [
            {"instance": instance, "arm": arm}
            for instance, arm in run_order
        ],
        "fixed_environment": dict(FIXED_ENVIRONMENT),
        "prices": asdict(PRICES),
        "elapsed_seconds": time.perf_counter() - started,
        "python": sys.version,
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "p0_preflight": p0_preflight,
        "source_hashes": source_hashes_before,
        "protected_file_hashes": protected_hashes_before,
        "input_hashes": input_hashes_before,
        "claim_boundary": (
            "Old three-instance, one-seed development training gate "
            "only; no formal performance, HGS, v7, or external ALNS "
            "claim."
        ),
        "formal_search_allowed": False,
        "stage2_activated": False,
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    _write_csv(output_dir / "raw_runs.csv", rows)
    _write_json(output_dir / "comparisons.json", comparisons)
    _write_json(output_dir / "decision.json", decision)
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "solution_witnesses.json", witnesses)
    _atomic_text(
        output_dir / "report.md",
        _report(comparisons, decision),
    )
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            name: _sha256(output_dir / name)
            for name in OUTPUT_FILES
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not drift_failures else 2


def _worker_main() -> int:
    request = json.loads(sys.stdin.read())
    bundle = Path(request["bundle"])
    arm = str(request["arm"])
    if arm not in ARMS:
        raise ValueError(f"unknown P1 arm: {arm}")
    start = _solution_from_payload(request["shared_start"])
    start_signature = solution_signature_hash(start)
    start_cost = independent_cost(bundle, start, PRICES)
    config = ContextualExpertConfig(
        total_eval_budget=BUDGET,
        runtime_cap_seconds=3600.0,
        enable_prescriptions=arm == "candidate",
        apply_terminal_completion=True,
        assessment_interval=20,
        per_mechanism_cooldown=60,
    )
    result = run_contextual_expert_alns(
        bundle,
        seed=SEED,
        prices=PRICES,
        initial_solution=start,
        config=config,
    )
    loaded = load_search_bundle(bundle)
    recomputed = independent_cost(
        bundle,
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
        "start_signature": start_signature,
        "start_cost": float(start_cost),
        "start_solution": asdict(start),
        "algorithm": result.algorithm,
        "evaluations": int(result.evaluations),
        "elapsed_seconds": float(result.elapsed_seconds),
        "claimed_final_cost": float(result.best_cost),
        "worker_recomputed_cost": float(recomputed),
        "worker_feasible": bool(result.feasible and not violations),
        "worker_violation_count": len(violations),
        "final_solution": asdict(result.best_solution),
        "mechanism_activity": dict(result.mechanism_activity),
    }
    print(
        WORKER_SENTINEL
        + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
    )
    return 0


def _shared_start(bundle_dir: Path) -> Solution:
    bundle = load_search_bundle(bundle_dir)
    start = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    start = annotate_cross_site_services(
        start,
        infer_customer_home_depots(bundle.instance),
    )
    violations = check_solution(start, bundle.instance, PRICES)
    if violations:
        raise RuntimeError(
            f"shared P1 start is infeasible for {bundle_dir.name}: "
            f"{violations[:8]}"
        )
    independent_cost(bundle_dir, start, PRICES)
    return start


def _invoke_worker(
    bundle_dir: Path,
    *,
    instance: str,
    arm: str,
    shared_start: Solution,
) -> dict[str, Any]:
    request = {
        "bundle": str(bundle_dir.resolve()),
        "instance": instance,
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
            f"P1 worker failed for {instance}:{arm} "
            f"with code {completed.returncode}\n"
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
            f"P1 worker returned {len(lines)} payloads for "
            f"{instance}:{arm}"
        )
    payload = json.loads(lines[0][len(WORKER_SENTINEL) :])
    payload["worker_process_elapsed_seconds"] = float(
        process_elapsed
    )
    return payload


def _normalize_worker_payload(
    bundle_dir: Path,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], Solution]:
    final_solution = _solution_from_payload(
        payload["final_solution"]
    )
    final_signature = solution_signature_hash(final_solution)
    parent_recomputed = independent_cost(
        bundle_dir,
        final_solution,
        PRICES,
    )
    loaded = load_search_bundle(bundle_dir)
    violations = check_solution(
        final_solution,
        loaded.instance,
        PRICES,
    )
    activity = dict(payload["mechanism_activity"])
    score_counts = {
        str(key): int(value)
        for key, value in dict(
            activity.get("score_counts", {})
        ).items()
    }
    candidate_channels = {
        key: value
        for key, value in score_counts.items()
        if key.startswith("candidate_channel:")
    }
    reference_channels = {
        key: value
        for key, value in score_counts.items()
        if key.startswith("reference_phase:")
    }
    reference_cache_channels = {
        key: value
        for key, value in score_counts.items()
        if key.startswith("reference_cache_hit:")
    }
    mechanism = dict(
        activity.get("mechanism_diagnostics", {})
    )
    mechanism_events = list(mechanism.get("events", []))
    mechanism_accepted = sum(
        int(value)
        for value in dict(
            mechanism.get("accepted", {})
        ).values()
    )
    scope_violations = sum(
        int(value)
        for value in dict(
            mechanism.get("scope_violations", {})
        ).values()
    )
    local_ledgers = _mechanism_local_ledgers(mechanism_events)
    candidate_channel_sum = sum(candidate_channels.values())
    reference_channel_sum = sum(reference_channels.values())
    mechanism_channel_count = sum(
        value
        for key, value in candidate_channels.items()
        if key.startswith(
            "candidate_channel:mechanism_prescription:"
        )
    )
    evaluations = int(payload["evaluations"])
    candidate_scores = int(activity["candidate_scores"])
    actual_moves = int(activity["actual_moves"])
    generic_evaluations = int(
        activity["generic_candidate_evaluations"]
    )
    mechanism_evaluations = int(
        activity["mechanism_candidate_evaluations"]
    )
    ledger_closed = (
        evaluations
        == candidate_scores
        == actual_moves
        == candidate_channel_sum
        == BUDGET
        == generic_evaluations + mechanism_evaluations
        and mechanism_channel_count == mechanism_evaluations
    )
    objective_match = (
        abs(
            float(payload["claimed_final_cost"])
            - float(payload["worker_recomputed_cost"])
        )
        <= 1.0e-7
        and abs(
            float(payload["claimed_final_cost"])
            - float(parent_recomputed)
        )
        <= 1.0e-7
    )
    selector = dict(
        activity.get("selector_diagnostics", {})
    )
    row = {
        "instance": bundle_dir.name,
        "arm": str(payload["arm"]),
        "algorithm": str(payload["algorithm"]),
        "seed": SEED,
        "budget": BUDGET,
        "start_signature": str(payload["start_signature"]),
        "start_cost": float(payload["start_cost"]),
        "evaluations": evaluations,
        "candidate_scores": candidate_scores,
        "actual_moves": actual_moves,
        "generic_candidate_evaluations": generic_evaluations,
        "mechanism_candidate_evaluations": mechanism_evaluations,
        "candidate_channel_sum": candidate_channel_sum,
        "candidate_channels_json": json.dumps(
            candidate_channels,
            sort_keys=True,
        ),
        "mechanism_channel_count": mechanism_channel_count,
        "reference_score_count": int(
            score_counts.get("reference", 0)
        ),
        "reference_channel_sum": reference_channel_sum,
        "reference_channels_json": json.dumps(
            reference_channels,
            sort_keys=True,
        ),
        "reference_cache_hit_count": int(
            score_counts.get("reference_cache_hit", 0)
        ),
        "reference_cache_channels_json": json.dumps(
            reference_cache_channels,
            sort_keys=True,
        ),
        "repair_delta_count": int(
            score_counts.get("repair_delta", 0)
        ),
        "mechanism_route_proxy_evaluations": int(
            local_ledgers["route_proxy_evaluations"]
        ),
        "mechanism_route_local_schedule_evaluations": int(
            local_ledgers["route_local_schedule_evaluations"]
        ),
        "mechanism_local_exact_evaluations": int(
            local_ledgers["local_exact_evaluations"]
        ),
        "mechanism_feasibility_checks": int(
            local_ledgers["feasibility_checks"]
        ),
        "mechanism_attempt_count": sum(
            int(value)
            for value in dict(
                mechanism.get("attempts", {})
            ).values()
        ),
        "mechanism_accepted_count": mechanism_accepted,
        "mechanism_scope_violation_count": scope_violations,
        "mechanism_events_json": json.dumps(
            mechanism_events,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "search_loop_count": int(
            activity["search_loop_count"]
        ),
        "search_restart_count": int(
            activity["search_restart_count"]
        ),
        "raw_search_signature": str(
            activity["raw_signature"]
        ),
        "raw_search_cost": float(activity["raw_cost"]),
        "terminal_completion_enabled": bool(
            activity["terminal_completion_enabled"]
        ),
        "terminal_selected_branch": str(
            activity["terminal_selected_branch"]
        ),
        "terminal_reference_replays": int(
            activity["terminal_reference_replays"]
        ),
        "post_search_full_solution_replays": int(
            activity["post_search_full_solution_replays"]
        ),
        "terminal_route_local_exact_evaluations": int(
            activity["terminal_route_local_exact_evaluations"]
        ),
        "terminal_route_proxy_evaluations": int(
            activity["terminal_route_proxy_evaluations"]
        ),
        "terminal_route_local_schedule_evaluations": int(
            activity[
                "terminal_route_local_schedule_evaluations"
            ]
        ),
        "raw_search_elapsed_seconds": float(
            activity["raw_search_elapsed_seconds"]
        ),
        "terminal_completion_elapsed_seconds": float(
            activity["terminal_completion_elapsed_seconds"]
        ),
        "total_solver_elapsed_seconds": float(
            payload["elapsed_seconds"]
        ),
        "worker_process_elapsed_seconds": float(
            payload["worker_process_elapsed_seconds"]
        ),
        "main_rng_final_state_sha256": str(
            selector.get("main_rng_final_state_sha256", "")
        ),
        "selector_rng_final_state_sha256": str(
            selector.get(
                "selector_rng_final_state_sha256",
                "",
            )
        ),
        "main_search_history_fingerprint": str(
            activity["main_search_history_fingerprint"]
        ),
        "claimed_final_cost": float(
            payload["claimed_final_cost"]
        ),
        "worker_recomputed_cost": float(
            payload["worker_recomputed_cost"]
        ),
        "parent_recomputed_cost": float(parent_recomputed),
        "final_signature": final_signature,
        "worker_feasible": bool(payload["worker_feasible"]),
        "parent_feasible": not violations,
        "parent_violation_count": len(violations),
        "objective_match": bool(objective_match),
        "ledger_closed": bool(ledger_closed),
        "reference_channel_closed": (
            int(score_counts.get("reference", 0))
            == reference_channel_sum
        ),
    }
    return row, final_solution


def _mechanism_local_ledgers(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    totals = {
        "route_proxy_evaluations": 0,
        "route_local_schedule_evaluations": 0,
        "local_exact_evaluations": 0,
        "feasibility_checks": 0,
    }
    for event in events:
        activity = dict(event.get("expert_activity", {}))
        totals["route_proxy_evaluations"] += int(
            activity.get("route_proxy_evaluations", 0)
        )
        totals["route_local_schedule_evaluations"] += int(
            activity.get(
                "route_local_schedule_evaluations",
                0,
            )
        )
        totals["local_exact_evaluations"] += int(
            activity.get("local_exact_evaluations", 0)
        )
        totals["feasibility_checks"] += int(
            activity.get("feasibility_checks", 0)
            + activity.get("full_feasibility_checks", 0)
        )
    return totals


def _comparisons(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    indexed = {
        (str(row["instance"]), str(row["arm"])): row
        for row in rows
    }
    comparisons: list[dict[str, Any]] = []
    for instance in INSTANCES:
        control = indexed[(instance, "control")]
        candidate = indexed[(instance, "candidate")]
        control_cost = float(control["parent_recomputed_cost"])
        candidate_cost = float(
            candidate["parent_recomputed_cost"]
        )
        delta = candidate_cost - control_cost
        improvement = (
            100.0 * (control_cost - candidate_cost) / control_cost
        )
        wall_ratio = (
            float(candidate["total_solver_elapsed_seconds"])
            / float(control["total_solver_elapsed_seconds"])
        )
        comparisons.append(
            {
                "instance": instance,
                "same_start": (
                    control["start_signature"]
                    == candidate["start_signature"]
                    and abs(
                        float(control["start_cost"])
                        - float(candidate["start_cost"])
                    )
                    <= 1.0e-9
                ),
                "start_signature": control["start_signature"],
                "control_raw_search_cost": float(
                    control["raw_search_cost"]
                ),
                "candidate_raw_search_cost": float(
                    candidate["raw_search_cost"]
                ),
                "control_final_cost": control_cost,
                "candidate_final_cost": candidate_cost,
                "candidate_minus_control": delta,
                "improvement_percent": improvement,
                "strict_win": delta < -TOL,
                "nonloss": delta <= TOL,
                "regression_percent": max(0.0, -improvement),
                "candidate_mechanism_accepted_count": int(
                    candidate["mechanism_accepted_count"]
                ),
                "mechanism_active": int(
                    candidate["mechanism_accepted_count"]
                )
                > 0,
                "control_elapsed_seconds": float(
                    control["total_solver_elapsed_seconds"]
                ),
                "candidate_elapsed_seconds": float(
                    candidate["total_solver_elapsed_seconds"]
                ),
                "wall_time_ratio": wall_ratio,
            }
        )
    return comparisons


def _decision(
    rows: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    *,
    p0_preflight: dict[str, Any],
    drift_failures: list[str],
) -> dict[str, Any]:
    failures = list(drift_failures)
    if not bool(p0_preflight.get("passed")):
        failures.append("p0_preflight_failed")
    if len(rows) != 6:
        failures.append(f"raw_row_count:{len(rows)}")
    for row in rows:
        tag = f"{row['instance']}:{row['arm']}"
        if not bool(row["ledger_closed"]):
            failures.append(f"{tag}:candidate_ledger")
        if not bool(row["reference_channel_closed"]):
            failures.append(f"{tag}:reference_ledger")
        if (
            not bool(row["worker_feasible"])
            or not bool(row["parent_feasible"])
            or not bool(row["objective_match"])
        ):
            failures.append(f"{tag}:replay_or_feasibility")
        if not bool(row["terminal_completion_enabled"]):
            failures.append(f"{tag}:terminal_disabled")
        if (
            int(row["post_search_full_solution_replays"])
            != 2 + int(row["terminal_reference_replays"])
        ):
            failures.append(f"{tag}:post_search_replay_ledger")
        if int(row["search_loop_count"]) != 1:
            failures.append(f"{tag}:search_loop_count")
        if int(row["search_restart_count"]) != 0:
            failures.append(f"{tag}:search_restart")
        if int(row["mechanism_scope_violation_count"]) != 0:
            failures.append(f"{tag}:mechanism_scope")
        if (
            row["arm"] == "control"
            and (
                int(row["mechanism_candidate_evaluations"]) != 0
                or int(row["mechanism_attempt_count"]) != 0
            )
        ):
            failures.append(f"{tag}:control_mechanism_activity")

    for comparison in comparisons:
        if not bool(comparison["same_start"]):
            failures.append(
                f"{comparison['instance']}:start_mismatch"
            )
    wins = sum(
        int(item["strict_win"]) for item in comparisons
    )
    nonlosses = sum(
        int(item["nonloss"]) for item in comparisons
    )
    active = sum(
        int(item["mechanism_active"]) for item in comparisons
    )
    improvements = [
        float(item["improvement_percent"])
        for item in comparisons
    ]
    regressions = [
        float(item["regression_percent"])
        for item in comparisons
    ]
    wall_ratios = [
        float(item["wall_time_ratio"])
        for item in comparisons
    ]
    median_improvement = (
        float(median(improvements)) if improvements else float("-inf")
    )
    max_regression = max(regressions, default=float("inf"))
    median_wall = (
        float(median(wall_ratios)) if wall_ratios else float("inf")
    )
    max_wall = max(wall_ratios, default=float("inf"))
    gate_checks = {
        "three_of_three_nonloss": nonlosses == 3,
        "strict_wins_at_least_two": wins >= 2,
        "median_improvement_at_least_one_percent": (
            median_improvement >= 1.0
        ),
        "maximum_regression_at_most_one_percent": (
            max_regression <= 1.0
        ),
        "mechanism_active_on_at_least_two_instances": (
            active >= 2
        ),
        "median_wall_ratio_at_most_1_25": median_wall <= 1.25,
        "maximum_wall_ratio_at_most_1_50": max_wall <= 1.50,
    }
    passed = not failures and all(gate_checks.values())
    return {
        "verdict": (
            "PASS_P1_OLD_THREE_INSTANCE_TRAINING_GATE"
            if passed
            else "STOP_P1_OLD_THREE_INSTANCE_TRAINING_GATE"
        ),
        "passed": bool(passed),
        "execution_failures": failures,
        "gate_checks": gate_checks,
        "strict_win_count": wins,
        "nonloss_count": nonlosses,
        "mechanism_active_instance_count": active,
        "median_improvement_percent": median_improvement,
        "maximum_regression_percent": max_regression,
        "median_wall_time_ratio": median_wall,
        "maximum_wall_time_ratio": max_wall,
        "next_allowed_step": (
            "lock_candidate_and_run_fresh_D3_minigate"
            if passed
            else "stop_20_60_context_schedule_without_rescue_tuning"
        ),
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }


def _verify_p0() -> dict[str, Any]:
    failures: list[str] = []
    required = (
        "artifact_hashes.json",
        "decision.json",
        "independent_audit.md",
        "metadata.json",
    )
    for name in required:
        if not (P0_DIR / name).is_file():
            failures.append(f"missing:{name}")
    if failures:
        raise RuntimeError(f"P0 evidence missing: {failures}")
    artifacts = json.loads(
        (P0_DIR / "artifact_hashes.json").read_text()
    )
    for name, expected in artifacts.items():
        actual = _sha256(P0_DIR / name)
        if actual != expected:
            failures.append(f"artifact_hash:{name}")
    if "independent_audit.md" not in artifacts:
        failures.append("independent_audit_not_hashed")
    decision = json.loads((P0_DIR / "decision.json").read_text())
    if (
        decision.get("verdict")
        != "PASS_CONTEXT_GATED_EXPERT_BEHAVIOUR"
        or not bool(decision.get("passed"))
    ):
        failures.append("p0_decision_not_pass")
    metadata = json.loads((P0_DIR / "metadata.json").read_text())
    for group in (
        "source_hashes",
        "protected_file_hashes",
        "input_hashes",
    ):
        for path, expected in dict(metadata.get(group, {})).items():
            actual = _sha256(REPO / path)
            if actual != expected:
                failures.append(f"{group}:{path}")
    evidence_head = str(metadata.get("git_head", ""))
    if not evidence_head:
        failures.append("p0_missing_git_head")
    else:
        ancestor = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                evidence_head,
                "HEAD",
            ],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
        if ancestor.returncode != 0:
            failures.append("p0_git_head_not_ancestor")
    if failures:
        raise RuntimeError(
            "P0 fail-closed preflight rejected P1: "
            + "; ".join(failures)
        )
    return {
        "passed": True,
        "verdict": decision["verdict"],
        "artifact_count": len(artifacts),
        "source_hash_count": len(
            metadata.get("source_hashes", {})
        ),
        "protected_hash_count": len(
            metadata.get("protected_file_hashes", {})
        ),
        "input_hash_count": len(
            metadata.get("input_hashes", {})
        ),
        "evidence_git_head": evidence_head,
        "artifact_manifest_sha256": _sha256(
            P0_DIR / "artifact_hashes.json"
        ),
    }


def _require_clean_sources() -> None:
    dirty: list[str] = []
    for path in SOURCE_FILES:
        status = _git("status", "--short", "--", path)
        if status.strip():
            dirty.append(f"{path}:{status.strip()}")
    if dirty:
        raise RuntimeError(
            "P1 source files must be committed before scoring: "
            + "; ".join(dirty)
        )


def _detect_runtime_drift(
    source_hashes: dict[str, str],
    protected_hashes: dict[str, str],
    input_hashes: dict[str, str],
) -> list[str]:
    failures: list[str] = []
    for label, hashes in (
        ("source", source_hashes),
        ("protected", protected_hashes),
        ("input", input_hashes),
    ):
        for path, expected in hashes.items():
            if _sha256(REPO / path) != expected:
                failures.append(f"runtime_{label}_drift:{path}")
    return failures


def _add_witness(
    witnesses: dict[str, dict[str, Any]],
    solution: Solution,
    use: dict[str, Any],
) -> None:
    signature = solution_signature_hash(solution)
    entry = witnesses.setdefault(
        signature,
        {
            "solution": asdict(solution),
            "uses": [],
        },
    )
    if entry["solution"] != asdict(solution):
        raise RuntimeError(
            f"solution signature collision: {signature}"
        )
    entry["uses"].append(use)


def _solution_from_payload(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(
                    row["charge_start_second"]
                ),
                charge_day_offset=int(
                    row.get("charge_day_offset", 0)
                ),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(
                    row["served_by_depot_id"]
                ),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def _report(
    comparisons: list[dict[str, Any]],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# 当前病灶驱动精确专家 P1 旧题训练门",
        "",
        f"结论：`{decision['verdict']}`。",
        "",
        "| 旧开发题 | 控制成本 | 候选成本 | 改善率 | 严格胜 | "
        "专家生效 | 墙钟比 |",
        "|---|---:|---:|---:|---|---|---:|",
    ]
    for item in comparisons:
        lines.append(
            "| {instance} | {control_final_cost:.9f} | "
            "{candidate_final_cost:.9f} | "
            "{improvement_percent:.4f}% | {strict_win} | "
            "{mechanism_active} | {wall_time_ratio:.4f} |".format(
                **item
            )
        )
    lines.extend(
        [
            "",
            "本门只使用三道已经看过的开发题和一个种子，作用是"
            "决定 20/60 的病灶调度是否值得锁定后进入新鲜小门。"
            "它不是论文性能证据，不比较 HGS、v7 或外部 ALNS，"
            "也不授权阶段二或正式全量试验。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(rows[0]),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    _atomic_text(path, buffer.getvalue())


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
    )


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}"
    )
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _input_hashes(bundle_dirs: set[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for bundle in sorted(bundle_dirs):
        for path in sorted(bundle.iterdir()):
            if path.is_file() and not path.name.startswith("._"):
                hashes[_relative(path)] = _sha256(path)
    return hashes


def _freeze_environment() -> None:
    for key, value in FIXED_ENVIRONMENT.items():
        os.environ[key] = value


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(
        f"not JSON serializable: {type(value).__name__}"
    )


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO.resolve()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)
    return digest.hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.rstrip()


if __name__ == "__main__":
    raise SystemExit(main())
