#!/usr/bin/env python3
"""Run the registered strong-solution direct-improvement behavior gate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import resource
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
FAILED_PACKAGE = (
    REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
)
REGISTRATION = PACKAGE / "direct_improvement_registration_v1.json"
OUTPUT = PACKAGE / "direct_improvement_gate_v1"
AUTHORITY = FAILED_PACKAGE / "g0_real_bundle_preregistration_v1.json"
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
    FAILED_PACKAGE,
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fge_vnd import FgeConfig, run_fge_vnd
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

TOL = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            ChargingAction(**row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [
            asdict(action) for action in solution.charging_actions
        ],
        "cross_site_services": [
            asdict(service) for service in solution.cross_site_services
        ],
    }


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if registration.get("status") != "FROZEN_BEFORE_EXECUTION":
        raise RuntimeError("direct registration is not frozen")
    for relative, expected in registration["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    for row in registration["inputs"]:
        path = REPO / row["witness_path"]
        if not path.is_file() or sha256(path) != row["witness_sha256"]:
            raise RuntimeError(f"registered witness drift: {path}")
    g0 = registration["g0_evidence"]
    if sha256(REPO / g0["decision_path"]) != g0["decision_sha256"]:
        raise RuntimeError("G0 decision drift")
    if (
        sha256(REPO / g0["artifact_hashes_path"])
        != g0["artifact_hashes_sha256"]
    ):
        raise RuntimeError("G0 artifact manifest drift")
    authority = registration["authority_registration"]
    if sha256(REPO / authority["path"]) != authority["sha256"]:
        raise RuntimeError("authority registration drift")
    return registration


def load_bundle(instance_id: str) -> Any:
    authority = read_json(AUTHORITY)
    inputs = authority["authorities"]
    return load_china81_bundle(
        REPO,
        instance_id,
        date=authority["scenario_date"],
        static_input_authority=inputs["static_inputs"]["path"],
        road_matrix_authority=inputs["road_matrices"]["path"],
        runtime_parameter_authority=inputs["runtime_parameters"]["path"],
        fleet_authority=inputs["finite_fleet"]["path"],
    )


def run_one(spec: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    for key, value in THREAD_ENV.items():
        os.environ[key] = value
    instance_id = str(spec["instance_id"])
    bundle = load_bundle(instance_id)
    witness = read_json(REPO / spec["witness_path"])
    solution = load_solution(witness[str(spec["witness_key"])])
    input_objective, _, input_exact_violations = exact_china81_score(
        solution,
        bundle,
    )
    input_direct_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if input_exact_violations or input_direct_violations:
        raise RuntimeError(f"{instance_id}: frozen input infeasible")
    if not math.isclose(
        input_objective,
        float(spec["expected_objective"]),
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError(f"{instance_id}: frozen input objective mismatch")

    run = run_fge_vnd(
        bundle,
        solution,
        initial_objective=input_objective,
        config=FgeConfig(
            complete_evaluation_limit=int(
                frozen["complete_evaluation_limit_per_instance"]
            ),
            inspection_limit_per_local_neighborhood=int(
                frozen["inspection_limit_per_local_neighborhood"]
            ),
            feasible_structures_per_neighborhood=int(
                frozen["feasible_structures_per_neighborhood"]
            ),
            assignment_candidates_per_structure=int(
                frozen["assignment_candidates_per_structure"]
            ),
            assignment_beam_per_state=int(
                frozen["assignment_beam_per_state"]
            ),
            block_seed_limit=int(frozen["block_seed_limit"]),
            rebuild_beam_width=int(frozen["rebuild_beam_width"]),
            nearest_anchor_count=int(frozen["nearest_anchor_count"]),
            improvement_tolerance=float(frozen["improvement_tolerance"]),
        ),
    )
    final_objective, final_breakdown, final_exact_violations = (
        exact_china81_score(run.best_solution, bundle)
    )
    final_direct_violations = check_solution(
        run.best_solution,
        bundle.instance,
        bundle.prices,
    )
    if final_exact_violations or final_direct_violations:
        raise RuntimeError(f"{instance_id}: final solution infeasible")
    if not math.isclose(
        final_objective,
        run.best_objective,
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError(f"{instance_id}: final replay mismatch")

    duplicate_count = sum(
        record.duplicate_of_index is not None
        for record in run.ledger.records
    )
    duplicate_fraction = (
        duplicate_count / run.ledger.consumed
        if run.ledger.consumed
        else 0.0
    )
    result = {
        "instance_id": instance_id,
        "seed": int(spec["seed"]),
        "task_id": spec["task_id"],
        "input_objective": input_objective,
        "final_objective": final_objective,
        "improved": final_objective < input_objective - TOL,
        "improvement_pct": (
            100.0 * (input_objective - final_objective) / input_objective
        ),
        "complete_evaluations": run.ledger.consumed,
        "complete_evaluation_limit": run.ledger.limit,
        "duplicate_count": duplicate_count,
        "duplicate_fraction": duplicate_fraction,
        "incomplete_candidate_evaluations": (
            run.incomplete_candidate_evaluations
        ),
        "elapsed_seconds": run.elapsed_seconds,
        "peak_rss_raw": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "stop_reason": run.stop_reason,
        "neighborhood_stats": run.neighborhood_stats,
        "improvements_by_neighborhood": run.improvements_by_neighborhood,
        "accepted_path": list(run.accepted_path),
        "route_local_cache": run.route_local_cache_stats,
        "final_breakdown": final_breakdown,
        "input_direct_violations": len(input_direct_violations),
        "input_exact_violations": len(input_exact_violations),
        "final_direct_violations": len(final_direct_violations),
        "final_exact_violations": len(final_exact_violations),
        "ledger": run.ledger.as_dict(),
        "trace": list(run.trace),
        "solution": solution_payload(run.best_solution),
    }
    return result


def artifact_hashes() -> dict[str, str]:
    return {
        path.relative_to(OUTPUT).as_posix(): sha256(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"direct output already exists: {OUTPUT}")
    registration = verify_registration()
    OUTPUT.mkdir(parents=True)
    frozen = registration["config"]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=int(frozen["workers"]),
    ) as executor:
        futures = {
            executor.submit(run_one, spec, frozen): spec
            for spec in registration["inputs"]
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["instance_id"])

    traces_dir = OUTPUT / "traces"
    witnesses_dir = OUTPUT / "witnesses"
    traces_dir.mkdir()
    witnesses_dir.mkdir()
    compact_rows: list[dict[str, Any]] = []
    for row in results:
        instance_id = row["instance_id"]
        write_json(
            traces_dir / f"{instance_id}.json",
            {
                "neighborhood_stats": row["neighborhood_stats"],
                "improvements_by_neighborhood": (
                    row["improvements_by_neighborhood"]
                ),
                "accepted_path": row["accepted_path"],
                "route_local_cache": row["route_local_cache"],
                "ledger": row["ledger"],
                "trace": row["trace"],
            },
        )
        write_json(
            witnesses_dir / f"{instance_id}.json",
            row["solution"],
        )
        compact_rows.append(
            {
                key: value
                for key, value in row.items()
                if key not in {
                    "accepted_path",
                    "final_breakdown",
                    "ledger",
                    "neighborhood_stats",
                    "route_local_cache",
                    "solution",
                    "trace",
                }
            }
        )

    improved_count = sum(bool(row["improved"]) for row in results)
    large_names = set(frozen["large_neighborhoods"])
    large_improvement = any(
        any(
            name in large_names and int(count) > 0
            for name, count in row["improvements_by_neighborhood"].items()
        )
        for row in results
    )
    all_visited = all(
        any(
            bool(row["neighborhood_stats"][name]["visited"])
            for row in results
        )
        for name in (
            "relocate",
            "swap",
            "two_opt",
            "two_opt_star",
            "ejection_rebuild",
        )
    )
    max_duplicate = max(
        float(row["duplicate_fraction"]) for row in results
    )
    all_complete = all(
        int(row["incomplete_candidate_evaluations"]) == 0
        and int(row["complete_evaluations"])
        <= int(frozen["complete_evaluation_limit_per_instance"])
        for row in results
    )
    all_feasible = all(
        int(row["final_direct_violations"]) == 0
        and int(row["final_exact_violations"]) == 0
        for row in results
    )
    passed = bool(
        all_feasible
        and improved_count >= int(frozen["required_improved_instances"])
        and large_improvement
        and all_visited
        and all_complete
        and max_duplicate <= float(frozen["duplicate_fraction_limit"])
    )
    verdict = (
        "PASS_FGE_VNS_DIRECT_IMPROVEMENT_GATE"
        if passed
        else "STOP_FGE_VNS_NO_DIRECT_IMPROVEMENT_SIGNAL"
    )

    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.fge-vns-direct-metadata.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_path": REGISTRATION.relative_to(REPO).as_posix(),
            "registration_sha256": sha256(REGISTRATION),
            "python": sys.version,
            "platform": platform.platform(),
            "thread_environment": THREAD_ENV,
            "workers": frozen["workers"],
        },
    )
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        fieldnames = [
            "instance_id",
            "seed",
            "task_id",
            "input_objective",
            "final_objective",
            "improved",
            "improvement_pct",
            "complete_evaluations",
            "complete_evaluation_limit",
            "duplicate_count",
            "duplicate_fraction",
            "incomplete_candidate_evaluations",
            "elapsed_seconds",
            "peak_rss_raw",
            "stop_reason",
            "input_direct_violations",
            "input_exact_violations",
            "final_direct_violations",
            "final_exact_violations",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(compact_rows)
    decision = {
        "schema": "resetp.fge-vns-direct-decision.v1",
        "verdict": verdict,
        "passed": passed,
        "improved_instances": improved_count,
        "required_improved_instances": frozen[
            "required_improved_instances"
        ],
        "large_neighborhood_improvement": large_improvement,
        "all_neighborhoods_visited": all_visited,
        "all_outputs_feasible": all_feasible,
        "all_complete_evaluation_ledgers_valid": all_complete,
        "max_duplicate_fraction": max_duplicate,
        "next_step_authorized": (
            "PREREGISTER_UNSEEN_A_B_A_PLUS_B_MICRO_GATE"
            if passed
            else "NONE_STOP_CANDIDATE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "decision.json", decision)
    report = [
        "# FEASIBILITY-GUIDED-EJECTION-VNS 强解直接改善门",
        "",
        f"判定：`{verdict}`。",
        "",
        (
            f"严格改善 {improved_count}/3；"
            f"大邻域直接改善={large_improvement}；"
            f"全部输出可行={all_feasible}；"
            f"最高重复比例={max_duplicate:.6f}。"
        ),
        "",
        *[
            (
                f"- {row['instance_id']}: "
                f"{row['input_objective']:.12f} -> "
                f"{row['final_objective']:.12f}，"
                f"改善 {row['improvement_pct']:.6f}%，"
                f"完整评价 {row['complete_evaluations']}，"
                f"用时 {row['elapsed_seconds']:.3f} 秒。"
            )
            for row in results
        ],
        "",
        (
            "边界：本门只验证独立算法能否改善封存强解；"
            "通过也只授权另立未见题 A/B/A+B 小门，"
            "不授权 E3、正式 China81、BKS、SOTA 或论文结论。"
        ),
    ]
    (OUTPUT / "report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes())
    print(verdict)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
