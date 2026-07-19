#!/usr/bin/env python3
"""Result-blind two-instance warning gate for SEG-GEN-01."""

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
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from segment_generation_alns import (  # noqa: E402
    SegmentAlnsConfig,
    run_segment_generation_alns,
)
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


BUNDLES = HERE / "fresh_donor03_segment_bundles"
TASKS = (
    "DEV-seggen-donor03-25c",
    "DEV-seggen-donor03-50c",
)
ARMS = ("control", "mechanism", "distance")
ARM_MODES = {
    "control": "disabled",
    "mechanism": "mechanism",
    "distance": "distance",
}
OUT = HERE / "segment_generation_fresh_warning_gate"
LOCK = HERE / "segment_generation_fresh_warning_blind_lock.json"
BEHAVIOR = HERE / "mechanism_segment_generation_behavior_gate"
SEED = 1
BUDGET = 100
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
TOL = 1.0e-9
WORKER_SENTINEL = "SEG_GEN_WORKER_JSON="
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
)
SOURCES = (
    Path(__file__).resolve(),
    HERE / "mechanism_segment_generator.py",
    HERE / "segment_generation_alns.py",
    HERE / "build_fresh_donor03_segment_bundles.py",
    HERE / "run_mechanism_segment_behavior_gate.py",
    REPO
    / "docs/handoff/generation_side_segment_trial_contract_20260719.md",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        return _worker()
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    lock = _verify_lock()
    _verify_behavior()
    source_hashes = _hash_map(SOURCES)
    protected_hashes = _hash_map(PROTECTED)
    input_hashes = _input_hashes()
    shared_starts = {
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
    for task, arm in run_order:
        payloads[(task, arm)] = _invoke_worker(
            BUNDLES / task,
            arm=arm,
            shared_start=shared_starts[task],
        )

    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    for task in TASKS:
        witnesses[task] = {
            "shared_start": asdict(shared_starts[task]),
            "start_signature": solution_signature_hash(
                shared_starts[task]
            ),
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

    comparisons = _comparisons(rows)
    drift = {
        "sources_unchanged": source_hashes == _hash_map(SOURCES),
        "protected_unchanged": (
            protected_hashes == _hash_map(PROTECTED)
        ),
        "inputs_unchanged": input_hashes == _input_hashes(),
    }
    decision = _decision(rows, comparisons, drift)
    metadata = {
        "schema_version": "resetp.seg-gen-01.fresh-warning.v1",
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
        "blind_lock": lock,
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "input_hashes": input_hashes,
        "claim_boundary": (
            "Two-instance one-seed result-blind development warning only. "
            "It is not formal, benchmark, stage-two, or manuscript evidence."
        ),
    }

    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(OUT / "comparisons.json", comparisons)
    _write_json(OUT / "solution_witnesses.json", witnesses)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_text(OUT / "report.md", _report(comparisons, decision))
    _write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: _sha(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not decision["execution_failures"] else 1


def _worker() -> int:
    request = json.loads(sys.stdin.read())
    arm = str(request["arm"])
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    bundle_dir = Path(request["bundle"])
    start = _solution_from_payload(request["shared_start"])
    result = run_segment_generation_alns(
        bundle_dir,
        seed=SEED,
        prices=PRICES,
        initial_solution=start,
        config=SegmentAlnsConfig(
            total_eval_budget=BUDGET,
            runtime_cap_seconds=3600.0,
            mode=ARM_MODES[arm],
            assessment_interval=20,
            cooldown_evaluations=100,
            min_segment_length=2,
            max_segment_length=3,
            max_source_segments=10_000,
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
    payload["worker_process_elapsed_seconds"] = (
        time.perf_counter() - started
    )
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
    accepted = sum(
        int(value)
        for value in dict(
            diagnostics.get("accepted", {})
        ).values()
    )
    improved = sum(
        int(value)
        for value in dict(
            diagnostics.get("best_improved", {})
        ).values()
    )
    attempts = sum(
        int(value)
        for value in dict(
            diagnostics.get("attempts", {})
        ).values()
    )
    selected_distance_worse = any(
        event.get("proposal_built")
        and float(
            (
                event.get("activity", {}).get("selected")
                or {}
            )
            .get("distance_delta", -1.0)
        )
        > TOL
        for event in events
    )
    selected_segment_length = max(
        (
            int(
                (
                    event.get("activity", {}).get("selected")
                    or {}
                )
                .get("segment_length", 0)
            )
            for event in events
        ),
        default=0,
    )
    objective_match = (
        abs(
            float(payload["claimed_final_cost"])
            - float(payload["worker_recomputed_cost"])
        )
        <= 1.0e-7
        and abs(
            float(payload["claimed_final_cost"])
            - float(parent_replay)
        )
        <= 1.0e-7
    )
    ledger_closed = (
        int(payload["evaluations"]) == BUDGET
        and int(
            activity["complete_search_candidate_evaluations"]
        )
        == BUDGET
        and int(activity["candidate_scores"]) == BUDGET
        and int(activity["actual_moves"]) == BUDGET
    )
    row = {
        "task": bundle_dir.name,
        "arm": str(payload["arm"]),
        "algorithm": str(payload["algorithm"]),
        "seed": SEED,
        "budget": BUDGET,
        "start_signature": str(payload["start_signature"]),
        "start_cost": float(payload["start_cost"]),
        "evaluations": int(payload["evaluations"]),
        "generic_candidate_evaluations": int(
            activity["generic_candidate_evaluations"]
        ),
        "segment_candidate_evaluations": int(
            activity["segment_candidate_evaluations"]
        ),
        "segment_attempts": attempts,
        "segment_accepted": accepted,
        "segment_best_improved": improved,
        "selected_distance_worse": bool(
            selected_distance_worse
        ),
        "selected_segment_length": selected_segment_length,
        "raw_cost": float(activity["raw_cost"]),
        "claimed_final_cost": float(
            payload["claimed_final_cost"]
        ),
        "worker_recomputed_cost": float(
            payload["worker_recomputed_cost"]
        ),
        "parent_recomputed_cost": float(parent_replay),
        "elapsed_seconds": float(payload["elapsed_seconds"]),
        "worker_process_elapsed_seconds": float(
            payload["worker_process_elapsed_seconds"]
        ),
        "final_signature": solution_signature_hash(solution),
        "worker_feasible": bool(payload["worker_feasible"]),
        "parent_feasible": not violations,
        "parent_violation_count": len(violations),
        "objective_match": bool(objective_match),
        "ledger_closed": bool(ledger_closed),
        "events_json": json.dumps(
            events,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }
    return row, solution


def _comparisons(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {
        (row["task"], row["arm"]): row
        for row in rows
    }
    comparisons = []
    for task in TASKS:
        control = by_key[(task, "control")]
        mechanism = by_key[(task, "mechanism")]
        distance = by_key[(task, "distance")]
        mechanism_cost = float(
            mechanism["parent_recomputed_cost"]
        )
        control_cost = float(control["parent_recomputed_cost"])
        distance_cost = float(distance["parent_recomputed_cost"])
        comparisons.append(
            {
                "task": task,
                "control_cost": control_cost,
                "mechanism_cost": mechanism_cost,
                "distance_cost": distance_cost,
                "mechanism_minus_control": (
                    mechanism_cost - control_cost
                ),
                "mechanism_minus_distance": (
                    mechanism_cost - distance_cost
                ),
                "mechanism_strict_win_control": (
                    mechanism_cost < control_cost - TOL
                ),
                "mechanism_nonloss_control": (
                    mechanism_cost <= control_cost + TOL
                ),
                "mechanism_strict_win_distance": (
                    mechanism_cost < distance_cost - TOL
                ),
                "mechanism_segment_accepted": (
                    int(mechanism["segment_accepted"]) > 0
                ),
                "distance_worse_generation_chain": bool(
                    mechanism["selected_distance_worse"]
                    and int(mechanism["segment_accepted"]) > 0
                ),
                "mechanism_wall_ratio": (
                    float(mechanism["elapsed_seconds"])
                    / max(
                        float(control["elapsed_seconds"]),
                        1.0e-9,
                    )
                ),
                "same_start_all_arms": len(
                    {
                        by_key[(task, arm)]["start_signature"]
                        for arm in ARMS
                    }
                )
                == 1,
            }
        )
    return comparisons


def _decision(
    rows: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    drift: dict[str, bool],
) -> dict[str, Any]:
    failures = [
        f"{row['task']}:{row['arm']}"
        for row in rows
        if not row["worker_feasible"]
        or not row["parent_feasible"]
        or not row["objective_match"]
        or not row["ledger_closed"]
    ]
    control_wins = sum(
        item["mechanism_strict_win_control"]
        for item in comparisons
    )
    control_nonloss = sum(
        item["mechanism_nonloss_control"]
        for item in comparisons
    )
    distance_wins = sum(
        item["mechanism_strict_win_distance"]
        for item in comparisons
    )
    chains = sum(
        item["distance_worse_generation_chain"]
        for item in comparisons
    )
    wall_ratios = [
        float(item["mechanism_wall_ratio"])
        for item in comparisons
    ]
    checks = {
        "two_of_two_nonloss_vs_control": control_nonloss == 2,
        "at_least_one_strict_win_vs_control": control_wins >= 1,
        "at_least_one_strict_win_vs_distance": distance_wins >= 1,
        "distance_worse_generation_chain_present": chains >= 1,
        "same_start_all_arms": all(
            item["same_start_all_arms"]
            for item in comparisons
        ),
        "median_wall_ratio_at_most_1_25": (
            median(wall_ratios) <= 1.25
        ),
        "maximum_wall_ratio_at_most_1_50": (
            max(wall_ratios) <= 1.50
        ),
        "all_drift_checks_pass": all(drift.values()),
        "no_execution_failures": not failures,
    }
    passed = all(checks.values())
    return {
        "verdict": (
            "GO_THREE_SEED_DEVELOPMENT_WARNING"
            if passed
            else "STOP_SEGMENT_GENERATOR_NO_RESCUE"
        ),
        "passed": bool(passed),
        "checks": checks,
        "strict_win_count_vs_control": control_wins,
        "nonloss_count_vs_control": control_nonloss,
        "strict_win_count_vs_distance": distance_wins,
        "distance_worse_generation_chain_count": chains,
        "median_wall_ratio": median(wall_ratios),
        "maximum_wall_ratio": max(wall_ratios),
        "execution_failures": failures,
        "drift_checks": drift,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "next_allowed_step": (
            "stop_for_user_recap_before_any_three_seed_or_stage_two_work"
            if passed
            else "freeze_SEG_GEN_01_without_rescue_tuning"
        ),
    }


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
            f"infeasible shared start: {bundle_dir.name}: "
            f"{violations[:8]}"
        )
    return start


def _verify_behavior() -> None:
    decision = _read_json(BEHAVIOR / "decision.json")
    if decision.get("verdict") != "PASS_SEGMENT_GENERATOR_BEHAVIOR":
        raise RuntimeError("behaviour prerequisite did not pass")
    hashes = _read_json(BEHAVIOR / "artifact_hashes.json")
    for name, digest in hashes.items():
        if _sha(BEHAVIOR / name) != digest:
            raise RuntimeError(
                f"behaviour artifact hash mismatch: {name}"
            )


def _verify_lock() -> dict[str, Any]:
    lock = _read_json(LOCK)
    if lock.get("status") != "LOCKED_BEFORE_RESULTS":
        raise RuntimeError("fresh warning lock is not active")
    if lock.get("tasks") != list(TASKS):
        raise RuntimeError("fresh warning task lock drifted")
    if lock.get("arms") != list(ARMS):
        raise RuntimeError("fresh warning arm lock drifted")
    if int(lock.get("seed", -1)) != SEED:
        raise RuntimeError("fresh warning seed lock drifted")
    if int(lock.get("budget", -1)) != BUDGET:
        raise RuntimeError("fresh warning budget lock drifted")
    expected = dict(lock.get("source_hashes", {}))
    actual = _hash_map(SOURCES)
    if expected != actual:
        raise RuntimeError("fresh warning source hashes drifted")
    if lock.get("bundle_manifest_sha256") != _sha(
        BUNDLES / "manifest.json"
    ):
        raise RuntimeError("fresh warning bundle manifest drifted")
    return lock


def _input_hashes() -> dict[str, str]:
    return _hash_map(
        tuple(
            path
            for task in TASKS
            for path in sorted((BUNDLES / task).iterdir())
            if path.is_file()
        )
    )


def _hash_map(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for path in paths
    }


def _sha(path: Path) -> str:
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
        "# 成段生成新题最小性能预警门",
        "",
        f"结论：`{decision['verdict']}`。",
        "",
        "|题|v7 等价控制|机制成段|里程删减|机制-v7|机制-里程|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in comparisons:
        lines.append(
            "|{task}|{control_cost:.6f}|{mechanism_cost:.6f}|"
            "{distance_cost:.6f}|{mechanism_minus_control:.6f}|"
            "{mechanism_minus_distance:.6f}|".format(**row)
        )
    lines.extend(
        [
            "",
            "本门只有两个结果盲开发题、一个种子。通过也只是一条"
            "三种子开发预警，不授权正式试验或阶段二。",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}"
    )
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, payload: Any) -> None:
    _write_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    _write_text(path, buffer.getvalue())


if __name__ == "__main__":
    raise SystemExit(main())
