#!/usr/bin/env python3
"""Run the preregistered three-instance G1 A/B/A+B micro gate.

This runner is deliberately fail closed. It refuses to execute until the
protected E2 v7 release chain and the real-bundle G0 gate both pass. Every arm
starts from the same completed witness and receives exactly 80 complete-model
evaluations. Objective values are not printed while tasks are running.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable


REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PREREGISTRATION = PACKAGE / "g1_micro_preregistration_v1.json"
G0_PREREGISTRATION = PACKAGE / "g0_real_bundle_preregistration_v1.json"
G0_GATE = PACKAGE / "g0_real_bundle_gate_v1"
WORK = PACKAGE / "g1_micro_work_v1"
OUT = PACKAGE / "g1_micro_gate_v1"
FORMAL_CAMPAIGN = (
    REPO / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
RELEASE_DECISION = FORMAL_CAMPAIGN / "release_chain/decision.json"
RELEASE_VERDICT = "PASS_E2_STAGED_V7_RELEASE_CHAIN"
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

for path in (
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720",
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contracts import AlgorithmArm  # noqa: E402
from hybrid_orchestrator import (  # noqa: E402
    CooperativeConfig,
    run_cooperative_arm,
    run_hgs_arm,
    run_rr_arm,
)
from rr_engine import RrConfig  # noqa: E402
import run_g0_real_bundle_preflight as real_bundle_gate  # noqa: E402
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (  # noqa: E402
    solution_signature_hash,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)


ARM_RUNNERS: dict[AlgorithmArm, Callable[..., Any]] = {
    AlgorithmArm.HGS: run_hgs_arm,
    AlgorithmArm.RUIN_RECREATE: run_rr_arm,
    AlgorithmArm.COOPERATIVE: run_cooperative_arm,
}
ARM_ORDER = (
    AlgorithmArm.HGS,
    AlgorithmArm.RUIN_RECREATE,
    AlgorithmArm.COOPERATIVE,
)
TOL = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty G1 rows")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _clean_appledouble(root: Path) -> int:
    removed = 0
    if not root.exists():
        return removed
    for path in sorted(root.rglob("._*")):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def load_preregistration() -> dict[str, Any]:
    payload = read_json(PREREGISTRATION)
    if payload.get("schema") != "resetp.coop-hgs-rr-g1-preregistration.v1":
        raise RuntimeError("unexpected G1 preregistration schema")
    if payload.get("status") != "FROZEN_BEFORE_G0_REAL_AND_G1_RESULTS":
        raise RuntimeError("G1 preregistration status drift")
    return payload


def verify_source_hashes(preregistration: dict[str, Any]) -> dict[str, int]:
    entries = preregistration.get("source_hashes")
    if not isinstance(entries, dict) or not entries:
        raise RuntimeError("G1 preregistration has no source hashes")
    for relative, expected in entries.items():
        path = REPO / relative
        if not path.is_file():
            raise RuntimeError(f"G1 source is missing: {relative}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"G1 source hash mismatch: {relative}:{expected}:{actual}"
            )
    return {"verified_source_files": len(entries)}


def _verify_artifact_hashes(root: Path) -> dict[str, str]:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"artifact manifest is missing: {manifest_path}")
    manifest = read_json(manifest_path)
    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        raise RuntimeError(f"artifact manifest is empty: {manifest_path}")
    for relative, expected in entries.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"artifact is missing: {path}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"artifact hash mismatch: {path}:{expected}:{actual}")
    return {str(key): str(value) for key, value in entries.items()}


def readiness(preregistration: dict[str, Any]) -> dict[str, Any]:
    input_verification = real_bundle_gate.verify_preregistration_inputs(
        real_bundle_gate.load_preregistration()
    )
    resource_state = real_bundle_gate.formal_resource_state()
    release_state = "MISSING"
    if RELEASE_DECISION.is_file():
        release_state = str(read_json(RELEASE_DECISION).get("verdict", "UNKNOWN"))
    g0_state = "MISSING"
    g0_hashes_verified = 0
    if (G0_GATE / "decision.json").is_file():
        g0_hashes_verified = len(_verify_artifact_hashes(G0_GATE))
        g0_state = str(read_json(G0_GATE / "decision.json").get("decision", "UNKNOWN"))
    reasons = []
    if resource_state["formal_running"]:
        reasons.append("protected_v7_or_release_chain_running")
    if release_state != RELEASE_VERDICT:
        reasons.append("protected_v7_release_chain_not_passed")
    if g0_state != preregistration["required_g0_decision"]:
        reasons.append("real_bundle_g0_not_passed")
    return {
        "execute_allowed_now": not reasons,
        "blocking_reasons": reasons,
        "resource_state": resource_state,
        "release_chain_verdict": release_state,
        "g0_decision": g0_state,
        "g0_artifacts_verified": g0_hashes_verified,
        "verified_inputs": input_verification,
    }


def require_ready(preregistration: dict[str, Any]) -> dict[str, Any]:
    state = readiness(preregistration)
    if not state["execute_allowed_now"]:
        raise RuntimeError(
            "HALT_G1_PREREQUISITES:" + ",".join(state["blocking_reasons"])
        )
    return state


def _load_bundle(instance_id: str, g0: dict[str, Any]) -> Any:
    authorities = g0["authorities"]
    return load_china81_bundle(
        REPO,
        instance_id,
        date=g0["scenario_date"],
        static_input_authority=authorities["static_inputs"]["path"],
        road_matrix_authority=authorities["road_matrices"]["path"],
        runtime_parameter_authority=authorities["runtime_parameters"]["path"],
        fleet_authority=authorities["finite_fleet"]["path"],
    )


def _serialize_solution(solution: Any) -> dict[str, Any]:
    return {
        "routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": list(route.node_sequence),
            }
            for route in solution.routes
        ],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [
            asdict(service) for service in solution.cross_site_services
        ],
    }


def _peak_rss_mb() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return raw / (1024.0 * 1024.0)
    return raw / 1024.0


def _config(preregistration: dict[str, Any], customer_count: int) -> CooperativeConfig:
    frozen = preregistration["frozen_configuration"]
    safety = max(
        float(frozen["wallclock_safety_base_seconds"]),
        float(frozen["wallclock_safety_seconds_per_customer"]) * customer_count,
    )
    rr_payload = frozen["rr"]
    rr = RrConfig(
        assignment_beam_per_state=int(rr_payload["assignment_beam_per_state"]),
        assignment_shortlist_size=int(rr_payload["assignment_shortlist_size"]),
        max_segment_length=int(rr_payload["max_segment_length"]),
        time_window_candidate_pool=int(rr_payload["time_window_candidate_pool"]),
        cross_depot_pair_pool=int(rr_payload["cross_depot_pair_pool"]),
        start_worsening_fraction=float(rr_payload["start_worsening_fraction"]),
        start_acceptance_probability=float(rr_payload["start_acceptance_probability"]),
        end_worsening_fraction=float(rr_payload["end_worsening_fraction"]),
        end_acceptance_probability=float(rr_payload["end_acceptance_probability"]),
        wallclock_safety_seconds=safety,
    )
    return CooperativeConfig(
        complete_evaluation_budget=int(
            preregistration["complete_evaluation_budget_per_arm"]
        ),
        hgs_iterations_for_a=int(frozen["hgs_iterations_for_a"]),
        hgs_wallclock_safety_seconds_per_mode=safety,
        route_proxy_modes=tuple(frozen["route_proxy_modes"]),
        cooperative_hgs_fraction=float(frozen["cooperative_hgs_fraction"]),
        hgs_archive_candidates_per_mode=int(frozen["hgs_archive_candidates_per_mode"]),
        assignment_beam_per_state=int(frozen["assignment_beam_per_state"]),
        assignment_shortlist_per_skeleton=int(
            frozen["assignment_shortlist_per_skeleton"]
        ),
        max_hgs_padding_fraction=float(frozen["max_hgs_padding_fraction"]),
        rr=rr,
    )


def _hgs_summary(run: Any) -> list[dict[str, Any]]:
    return [
        {
            "epoch": epoch.epoch,
            "evaluated_candidates": epoch.evaluated_candidates,
            "feasible_candidates": epoch.feasible_candidates,
            "unique_candidate_signatures": epoch.unique_candidate_signatures,
            "duplicate_evaluations": epoch.duplicate_evaluations,
            "padding_rechecks": epoch.padding_rechecks,
            "elapsed_seconds": epoch.elapsed_seconds,
            "warm_signatures": list(epoch.warm_signatures),
            "direct_warm_descendant_count": len(epoch.direct_warm_descendants),
            "decode_failures": list(epoch.decode_failures),
            "archives": [
                {
                    "route_proxy_mode": archive.route_proxy_mode,
                    "seed": archive.seed,
                    "iterations": archive.iterations,
                    "elapsed_seconds": archive.elapsed_seconds,
                    "candidate_count": len(archive.candidates),
                    "stats": archive.stats,
                }
                for archive in epoch.archives
            ],
        }
        for epoch in run.hgs_epochs
    ]


def _rr_summary(run: Any) -> list[dict[str, Any]]:
    return [
        {
            "elapsed_seconds": phase.elapsed_seconds,
            "stop_reason": phase.stop_reason,
            "operator_attempts": phase.operator_attempts,
            "operator_accepted": phase.operator_accepted,
            "operator_best_improvements": phase.operator_best_improvements,
            "route_local_cache_stats": phase.route_local_cache_stats,
            "trace": [asdict(row) for row in phase.trace],
        }
        for phase in run.rr_phases
    ]


def _lineage_summary(run: Any) -> dict[str, Any] | None:
    if run.lineage is None:
        return None
    return run.lineage.as_dict()


def _task_id(instance_id: str, seed: int, arm: AlgorithmArm) -> str:
    return f"G1__{instance_id}__seed{int(seed)}__{arm.value}"


def _task_manifest(task_dir: Path) -> dict[str, str]:
    targets = [
        path
        for path in sorted(task_dir.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and not path.name.endswith(".tmp")
    ]
    return {path.name: sha256(path) for path in targets}


def _write_task(
    task_dir: Path,
    *,
    result: dict[str, Any],
    best_solution: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    trace: dict[str, Any] | None,
) -> None:
    temporary = task_dir.parent / f".{task_dir.name}.tmp-{os.getpid()}"
    if task_dir.exists() or temporary.exists():
        raise RuntimeError(f"task output already exists: {task_dir}")
    temporary.mkdir(parents=True)
    write_json(temporary / "result.json", result)
    if best_solution is not None:
        write_json(temporary / "best_solution.json", best_solution)
    if ledger is not None:
        write_json(temporary / "ledger.json", ledger)
    if trace is not None:
        write_json(temporary / "trace.json", trace)
    _clean_appledouble(temporary)
    write_json(
        temporary / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": _task_manifest(temporary),
        },
    )
    os.replace(temporary, task_dir)


def _validate_task(task_dir: Path, preregistration_sha: str) -> dict[str, Any]:
    _verify_artifact_hashes(task_dir)
    result = read_json(task_dir / "result.json")
    if result.get("schema") != "resetp.coop-hgs-rr-g1-task.v1":
        raise RuntimeError(f"unexpected task schema: {task_dir}")
    if result.get("preregistration_sha256") != preregistration_sha:
        raise RuntimeError(f"task preregistration drift: {task_dir}")
    return result


def _run_task(spec: dict[str, Any]) -> dict[str, Any]:
    for key, value in THREAD_ENV.items():
        os.environ[key] = value
    preregistration = load_preregistration()
    preregistration_sha = sha256(PREREGISTRATION)
    instance_id = str(spec["instance_id"])
    seed = int(spec["seed"])
    arm = AlgorithmArm(str(spec["arm"]))
    task_dir = WORK / "tasks" / _task_id(instance_id, seed, arm)
    if task_dir.exists():
        return _validate_task(task_dir, preregistration_sha)
    try:
        g0 = real_bundle_gate.load_preregistration()
        bundle = _load_bundle(instance_id, g0)
        customer_count = sum(
            node.node_type.lower() == "c" for node in bundle.instance.nodes
        )
        witness = real_bundle_gate._load_witness(  # noqa: SLF001
            instance_id,
            g0,
        )
        initial_completion = complete_china81_route_skeleton(witness, bundle)
        initial_solution = initial_completion.solution
        initial_objective, _, initial_violations = exact_china81_score(
            initial_solution,
            bundle,
        )
        initial_direct_violations = check_solution(
            initial_solution,
            bundle.instance,
            bundle.prices,
        )
        if initial_violations or initial_direct_violations:
            raise RuntimeError("shared completed witness is infeasible")
        if not math.isclose(
            float(initial_objective),
            float(initial_completion.objective),
            rel_tol=0.0,
            abs_tol=TOL,
        ):
            raise RuntimeError("shared initial completion cost mismatch")

        config = _config(preregistration, customer_count)
        runner = ARM_RUNNERS[arm]
        run = runner(
            bundle,
            initial_solution,
            seed=seed,
            config=config,
        )
        replay_objective, replay_breakdown, replay_violations = exact_china81_score(
            run.best_solution,
            bundle,
        )
        direct_violations = check_solution(
            run.best_solution,
            bundle.instance,
            bundle.prices,
        )
        if replay_violations or direct_violations:
            raise RuntimeError("returned best solution failed independent replay")
        if not math.isclose(
            float(replay_objective),
            float(run.best_objective),
            rel_tol=0.0,
            abs_tol=TOL,
        ):
            raise RuntimeError("returned and replayed best objectives disagree")
        run.ledger.assert_exactly_closed()
        wallclock_safety_triggered = any(
            phase.stop_reason == "WALLCLOCK_SAFETY_CAP" for phase in run.rr_phases
        ) or any(
            archive.iterations < int(archive.stats["max_iterations"])
            and (
                archive.elapsed_seconds
                >= float(archive.stats["wallclock_safety_seconds"]) - 0.25
            )
            for epoch in run.hgs_epochs
            for archive in epoch.archives
        )
        result = {
            "schema": "resetp.coop-hgs-rr-g1-task.v1",
            "preregistration_sha256": preregistration_sha,
            "status": "PASS",
            "detail": "",
            "instance_id": instance_id,
            "seed": seed,
            "arm": arm.value,
            "customer_count": customer_count,
            "initial_solution_signature": solution_signature_hash(initial_solution),
            "initial_objective": float(initial_objective),
            "best_solution_signature": solution_signature_hash(run.best_solution),
            "best_objective": float(run.best_objective),
            "replay_objective": float(replay_objective),
            "replay_total_emissions_kg": float(replay_breakdown["E_total"]),
            "direct_violation_count": len(direct_violations),
            "exact_violation_count": len(replay_violations),
            "complete_evaluation_budget": run.ledger.limit,
            "complete_evaluations_consumed": run.ledger.consumed,
            "feasible_evaluations": sum(row.feasible for row in run.ledger.records),
            "infeasible_evaluations": sum(
                not row.feasible for row in run.ledger.records
            ),
            "duplicate_evaluations": sum(
                row.duplicate_of_index is not None for row in run.ledger.records
            ),
            "hgs_iterations": sum(
                archive.iterations
                for epoch in run.hgs_epochs
                for archive in epoch.archives
            ),
            "rr_trace_iterations": sum(len(phase.trace) for phase in run.rr_phases),
            "elapsed_seconds": float(run.elapsed_seconds),
            "peak_rss_mb": _peak_rss_mb(),
            "stop_reason": run.stop_reason,
            "wallclock_safety_triggered": wallclock_safety_triggered,
            "lineage_transfer_count": (
                0 if run.lineage is None else len(run.lineage.transfers)
            ),
            "cooperative_gain_evidence_count": (
                0
                if run.lineage is None
                else run.lineage.cooperative_gain_evidence_count()
            ),
            "shared_initial_preparation_outside_arm_budget": True,
            "shared_initial_counted_once_inside_arm_budget": True,
        }
        _write_task(
            task_dir,
            result=result,
            best_solution=_serialize_solution(run.best_solution),
            ledger=run.ledger.as_dict(),
            trace={
                "schema": "resetp.coop-hgs-rr-g1-trace.v1",
                "budget_plan": asdict(run.budget_plan),
                "hgs_epochs": _hgs_summary(run),
                "rr_phases": _rr_summary(run),
                "lineage": _lineage_summary(run),
                "route_local_cache_stats": run.route_local_cache_stats,
            },
        )
        return result
    except Exception as exc:
        result = {
            "schema": "resetp.coop-hgs-rr-g1-task.v1",
            "preregistration_sha256": preregistration_sha,
            "status": "ERROR",
            "detail": f"{type(exc).__name__}:{exc}",
            "instance_id": instance_id,
            "seed": seed,
            "arm": arm.value,
        }
        _write_task(
            task_dir,
            result=result,
            best_solution=None,
            ledger=None,
            trace=None,
        )
        return result


def _task_specs(preregistration: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "instance_id": row["instance_id"],
            "seed": int(seed),
            "arm": arm.value,
        }
        for row in preregistration["instances"]
        for seed in preregistration["seeds"]
        for arm in ARM_ORDER
    ]


def _row(result: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "status",
        "detail",
        "instance_id",
        "seed",
        "arm",
        "customer_count",
        "initial_solution_signature",
        "initial_objective",
        "best_solution_signature",
        "best_objective",
        "replay_objective",
        "replay_total_emissions_kg",
        "direct_violation_count",
        "exact_violation_count",
        "complete_evaluation_budget",
        "complete_evaluations_consumed",
        "feasible_evaluations",
        "infeasible_evaluations",
        "duplicate_evaluations",
        "hgs_iterations",
        "rr_trace_iterations",
        "elapsed_seconds",
        "peak_rss_mb",
        "stop_reason",
        "wallclock_safety_triggered",
        "lineage_transfer_count",
        "cooperative_gain_evidence_count",
    )
    return {field: result.get(field, "") for field in fields}


def _decide(rows: list[dict[str, Any]]) -> dict[str, Any]:
    all_complete = len(rows) == 9 and all(row["status"] == "PASS" for row in rows)
    exact_budget = all(
        row["complete_evaluations_consumed"] == 80
        for row in rows
        if row["status"] == "PASS"
    )
    all_feasible = all(
        row["direct_violation_count"] == 0 and row["exact_violation_count"] == 0
        for row in rows
        if row["status"] == "PASS"
    )
    no_safety_cap = all(
        not row["wallclock_safety_triggered"] for row in rows if row["status"] == "PASS"
    )
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row["status"] != "PASS":
            continue
        grouped.setdefault(
            (str(row["instance_id"]), int(row["seed"])),
            {},
        )[str(row["arm"])] = row
    no_losses = True
    strict_over_both = 0
    paired_rows = 0
    for arms in grouped.values():
        if set(arms) != {arm.value for arm in ARM_ORDER}:
            no_losses = False
            continue
        paired_rows += 1
        a = float(arms[AlgorithmArm.HGS.value]["best_objective"])
        b = float(arms[AlgorithmArm.RUIN_RECREATE.value]["best_objective"])
        ab = float(arms[AlgorithmArm.COOPERATIVE.value]["best_objective"])
        no_losses = no_losses and ab <= a + TOL and ab <= b + TOL
        strict_over_both += int(ab < min(a, b) - TOL)
    cooperative_gain_runs = sum(
        int(row["cooperative_gain_evidence_count"] > 0)
        for row in rows
        if row["status"] == "PASS" and row["arm"] == AlgorithmArm.COOPERATIVE.value
    )
    gates = {
        "nine_runs_complete": all_complete,
        "all_final_solutions_feasible_and_replayed": all_feasible,
        "exactly_80_complete_evaluations_per_arm": exact_budget,
        "no_wallclock_safety_cap": no_safety_cap,
        "three_complete_pairs": paired_rows == 3,
        "ab_no_loss_against_a_or_b": no_losses,
        "ab_strictly_beats_min_a_b_on_at_least_two_instances": (strict_over_both >= 2),
        "at_least_one_direct_post_injection_gain": cooperative_gain_runs >= 1,
    }
    return {
        "schema": "resetp.coop-hgs-rr-g1-decision.v1",
        "decision": (
            "PASS_G1_COOPERATIVE_HYBRID_GAIN"
            if all(gates.values())
            else "STOP_G1_NO_HYBRID_GAIN"
        ),
        "gates": gates,
        "strict_over_both_instances": strict_over_both,
        "cooperative_gain_runs": cooperative_gain_runs,
        "claim_boundary": (
            "G1 is a three-development-instance, seed-1 micro gate. It cannot "
            "support formal China81, BKS, or SOTA claims."
        ),
    }


def _write_gate(
    preregistration: dict[str, Any],
    readiness_state: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite G1 gate: {OUT}")
    OUT.mkdir(parents=True)
    rows = [
        _row(row)
        for row in sorted(
            results,
            key=lambda item: (
                item["instance_id"],
                int(item["seed"]),
                item["arm"],
            ),
        )
    ]
    write_csv(OUT / "raw_runs.csv", rows)
    decision = _decide(rows)
    write_json(OUT / "decision.json", decision)
    metadata = {
        "schema": "resetp.coop-hgs-rr-g1-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
        ).strip(),
        "platform": platform.platform(),
        "python": sys.version,
        "preregistration_sha256": sha256(PREREGISTRATION),
        "g0_preregistration_sha256": sha256(G0_PREREGISTRATION),
        "readiness_at_start": readiness_state,
        "verified_sources": verify_source_hashes(preregistration),
        "thread_environment": THREAD_ENV,
        "task_count": len(results),
        "work_directory": str(WORK.relative_to(REPO)),
        "source_hashes": {
            relative: sha256(REPO / relative)
            for relative in preregistration["source_hashes"]
        },
    }
    write_json(OUT / "metadata.json", metadata)
    report_lines = [
        "# G1 cooperative HGS-RR micro gate",
        "",
        f"Decision: `{decision['decision']}`.",
        "",
        "This is the preregistered three-development-instance, seed-1 gate.",
        "Every arm started from the same completed witness and consumed exactly",
        "80 visible complete-model evaluations.",
        "",
        "Gate results:",
        "",
    ]
    report_lines.extend(
        f"- `{key}`: {value}" for key, value in decision["gates"].items()
    )
    report_lines.extend(
        [
            "",
            ("No BKS, SOTA, or formal China81 claim is authorized by this micro gate."),
            "",
        ]
    )
    (OUT / "report.md").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )
    _clean_appledouble(OUT)
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {
                path.name: sha256(path)
                for path in (
                    OUT / "metadata.json",
                    OUT / "raw_runs.csv",
                    OUT / "decision.json",
                    OUT / "report.md",
                )
            },
        },
    )
    return decision


def check_contract() -> int:
    preregistration = load_preregistration()
    verified_sources = verify_source_hashes(preregistration)
    state = readiness(preregistration)
    print(
        json.dumps(
            {
                "contract": "PASS",
                "verified_sources": verified_sources,
                "readiness": state,
                "task_count": len(_task_specs(preregistration)),
                "complete_evaluation_budget_per_arm": (
                    preregistration["complete_evaluation_budget_per_arm"]
                ),
                "claim_boundary": preregistration["claim_boundary"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def execute(workers: int) -> int:
    preregistration = load_preregistration()
    verify_source_hashes(preregistration)
    readiness_state = require_ready(preregistration)
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite G1 gate: {OUT}")
    WORK.mkdir(parents=True, exist_ok=True)
    tasks_root = WORK / "tasks"
    tasks_root.mkdir(parents=True, exist_ok=True)
    incomplete = sorted(WORK.glob(".G1__*.tmp-*"))
    if incomplete:
        raise RuntimeError(
            "incomplete G1 task directories require audit before resume: "
            + ",".join(path.name for path in incomplete)
        )
    specs = _task_specs(preregistration)
    results: list[dict[str, Any]] = []
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=int(workers),
        mp_context=context,
    ) as pool:
        futures = {pool.submit(_run_task, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            result = future.result()
            results.append(result)
            print(
                f"completed {spec['instance_id']} seed={spec['seed']} "
                f"arm={spec['arm']} status={result['status']}",
                flush=True,
            )
    decision = _write_gate(
        preregistration,
        readiness_state,
        results,
    )
    print(decision["decision"])
    return 0 if decision["decision"].startswith("PASS_") else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.check_contract:
        return check_contract()
    if not 1 <= int(args.workers) <= 3:
        raise ValueError("G1 workers must be between 1 and 3 on this 8 GB host")
    return execute(int(args.workers))


if __name__ == "__main__":
    raise SystemExit(main())
