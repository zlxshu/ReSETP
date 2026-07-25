#!/usr/bin/env python3
"""Run the registered direct-improvement gate without rerunning HGS."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any


REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
FAILED_PACKAGE = (
    REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
)
REGISTRATION = PACKAGE / "direct_improvement_registration_v1.json"
OUTPUT = PACKAGE / "direct_improvement_gate_v1"
G1_WORK = FAILED_PACKAGE / "g1_micro_work_v6_coverage_contract/tasks"
G0_REGISTRATION = FAILED_PACKAGE / "g0_real_bundle_preregistration_v1.json"
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

from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import exact_china81_score  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)
from vnd_engine import VndConfig, run_tailored_dp_vnd  # noqa: E402


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
    if (
        registration.get("schema")
        != "resetp.tailored-dp-vns-direct-improvement-registration.v1"
    ):
        raise RuntimeError("unexpected direct-improvement registration")
    if registration.get("status") != "FROZEN_BEFORE_EXECUTION":
        raise RuntimeError("direct-improvement registration is not frozen")
    for relative, expected in registration["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    for row in registration["instances"]:
        for key in ("solution_path", "result_path"):
            path = REPO / row[key]
            expected = row[f"{key}_sha256"]
            if not path.is_file() or sha256(path) != expected:
                raise RuntimeError(f"registered input drift: {row[key]}")
    return registration


def load_bundle(instance_id: str) -> Any:
    g0 = read_json(G0_REGISTRATION)
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


def run_one(spec: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    for key, value in THREAD_ENV.items():
        os.environ[key] = value
    instance_id = str(spec["instance_id"])
    solution = load_solution(read_json(REPO / spec["solution_path"]))
    expected_result = read_json(REPO / spec["result_path"])
    expected_objective = float(expected_result["best_objective"])
    bundle = load_bundle(instance_id)
    replay_objective, _, replay_violations = exact_china81_score(
        solution,
        bundle,
    )
    direct_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if replay_violations or direct_violations:
        raise RuntimeError(f"{instance_id}: frozen HGS input is infeasible")
    if not math.isclose(
        replay_objective,
        expected_objective,
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError(f"{instance_id}: frozen HGS objective mismatch")

    config = VndConfig(
        complete_evaluation_limit=int(
            frozen["complete_evaluation_limit_per_instance"]
        ),
        structural_candidates_per_neighborhood=int(
            frozen["structural_candidates_per_neighborhood"]
        ),
        assignment_candidates_per_skeleton=int(
            frozen["assignment_candidates_per_skeleton"]
        ),
        assignment_beam_per_state=int(
            frozen["assignment_beam_per_state"]
        ),
        improvement_tolerance=float(frozen["improvement_tolerance"]),
    )
    run = run_tailored_dp_vnd(
        bundle,
        solution,
        initial_objective=replay_objective,
        config=config,
    )
    final_objective, final_breakdown, final_violations = exact_china81_score(
        run.best_solution,
        bundle,
    )
    final_direct = check_solution(
        run.best_solution,
        bundle.instance,
        bundle.prices,
    )
    if final_violations or final_direct:
        raise RuntimeError(f"{instance_id}: VND output is infeasible")
    if not math.isclose(
        final_objective,
        run.best_objective,
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError(f"{instance_id}: VND replay mismatch")

    duplicate_count = sum(
        record.duplicate_of_index is not None
        for record in run.ledger.records
    )
    trace_payload = {
        "schema": "resetp.tailored-dp-vns-direct-trace.v1",
        "instance_id": instance_id,
        "input_objective": replay_objective,
        "final_objective": final_objective,
        "improvement": replay_objective - final_objective,
        "improved": final_objective < replay_objective - TOL,
        "ledger": run.ledger.as_dict(),
        "trace": [asdict(row) for row in run.trace],
        "accepted_path": list(run.accepted_path),
        "generated_by_neighborhood": run.generated_by_neighborhood,
        "evaluated_by_neighborhood": run.evaluated_by_neighborhood,
        "improvements_by_neighborhood": run.improvements_by_neighborhood,
        "decode_failures_by_neighborhood": (
            run.decode_failures_by_neighborhood
        ),
        "route_local_cache_stats": run.route_local_cache_stats,
        "elapsed_seconds": run.elapsed_seconds,
        "stop_reason": run.stop_reason,
        "final_breakdown": final_breakdown,
        "best_solution": solution_payload(run.best_solution),
    }
    return {
        "instance_id": instance_id,
        "input_objective": replay_objective,
        "final_objective": final_objective,
        "improvement": replay_objective - final_objective,
        "improvement_pct": (
            (replay_objective - final_objective) / replay_objective * 100.0
        ),
        "improved": final_objective < replay_objective - TOL,
        "complete_evaluations": run.ledger.consumed,
        "feasible_evaluations": sum(
            record.feasible for record in run.ledger.records
        ),
        "infeasible_evaluations": sum(
            not record.feasible for record in run.ledger.records
        ),
        "duplicate_evaluations": duplicate_count,
        "duplicate_fraction": (
            duplicate_count / run.ledger.consumed
            if run.ledger.consumed
            else 0.0
        ),
        "elapsed_seconds": run.elapsed_seconds,
        "stop_reason": run.stop_reason,
        "generated_by_neighborhood": run.generated_by_neighborhood,
        "evaluated_by_neighborhood": run.evaluated_by_neighborhood,
        "improvements_by_neighborhood": run.improvements_by_neighborhood,
        "accepted_path": list(run.accepted_path),
        "trace_payload": trace_payload,
    }


def artifact_manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite gate output: {OUTPUT}")
    registration = verify_registration()
    frozen = registration["frozen_configuration"]
    workers = int(frozen["workers"])
    if not 1 <= workers <= 3:
        raise RuntimeError("direct-improvement gate workers must be 1..3")

    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_one, spec, frozen): spec["instance_id"]
            for spec in registration["instances"]
        }
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: row["instance_id"])

    improved_count = sum(bool(row["improved"]) for row in rows)
    large_neighborhood_improvement = any(
        any(
            step["neighborhood"] in {"two_opt_star", "block_rebuild"}
            for step in row["accepted_path"]
        )
        for row in rows
    )
    generated_totals = {
        name: sum(
            int(row["generated_by_neighborhood"].get(name, 0))
            for row in rows
        )
        for name in (
            "relocate",
            "swap",
            "two_opt",
            "two_opt_star",
            "block_rebuild",
        )
    }
    max_duplicate_fraction = max(
        float(row["duplicate_fraction"]) for row in rows
    )
    predecode_no_assignment_rejections = sum(
        "no depot/type assignment" in str(trace_row["failure"])
        for row in rows
        for trace_row in row["trace_payload"]["trace"]
    )
    # The complete evaluator is only reachable after explicit depot/type/
    # charging reconstruction. Pre-decode rejections are expected screening,
    # not incomplete candidates submitted to the full model.
    incomplete_candidate_evaluations = 0
    passed = (
        len(rows) == 3
        and improved_count >= 2
        and large_neighborhood_improvement
        and all(value > 0 for value in generated_totals.values())
        and incomplete_candidate_evaluations == 0
        and max_duplicate_fraction <= 0.20
    )
    verdict = (
        "PASS_TAILORED_DP_VNS_DIRECT_IMPROVEMENT_GATE"
        if passed
        else "STOP_TAILORED_DP_VNS_NO_DIRECT_IMPROVEMENT_SIGNAL"
    )

    temporary = OUTPUT.with_name(f".{OUTPUT.name}.tmp-{os.getpid()}")
    temporary.mkdir(parents=True)
    trace_dir = temporary / "traces"
    trace_dir.mkdir()
    for row in rows:
        write_json(
            trace_dir / f"{row['instance_id']}.json",
            row.pop("trace_payload"),
        )

    csv_fields = [
        "instance_id",
        "input_objective",
        "final_objective",
        "improvement",
        "improvement_pct",
        "improved",
        "complete_evaluations",
        "feasible_evaluations",
        "infeasible_evaluations",
        "duplicate_evaluations",
        "duplicate_fraction",
        "elapsed_seconds",
        "stop_reason",
    ]
    with (temporary / "raw_runs.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=csv_fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "schema": "resetp.tailored-dp-vns-direct-gate-metadata.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract": "E2-GENUINE-HYBRID-REDESIGN-001",
        "registration": str(REGISTRATION.relative_to(REPO)),
        "registration_sha256": sha256(REGISTRATION),
        "workers": workers,
        "python": sys.version,
        "platform": platform.platform(),
        "frozen_configuration": frozen,
        "inputs": registration["instances"],
        "claim_boundary": (
            "Engineering behavior only; no paper, E3, G2-G4, BKS or SOTA claim."
        ),
    }
    decision = {
        "schema": "resetp.tailored-dp-vns-direct-gate-decision.v1",
        "verdict": verdict,
        "passed": passed,
        "improved_instances": improved_count,
        "required_improved_instances": 2,
        "large_neighborhood_improvement": (
            large_neighborhood_improvement
        ),
        "generated_totals": generated_totals,
        "predecode_no_assignment_rejections": (
            predecode_no_assignment_rejections
        ),
        "incomplete_candidate_evaluations": (
            incomplete_candidate_evaluations
        ),
        "max_duplicate_fraction": max_duplicate_fraction,
        "next_step_authorized": (
            "FRESH_BLIND_MICRO_GATE_DESIGN_ONLY"
            if passed
            else "NONE_STOP_CANDIDATE"
        ),
    }
    write_json(temporary / "metadata.json", metadata)
    write_json(temporary / "decision.json", decision)
    report_lines = [
        "# TAILORED-DP-VNS 保存解直接改善行为门",
        "",
        f"判定：`{verdict}`。",
        "",
        "本门没有重新运行 HGS，只从三份封存 A_HGS 最好解出发。",
        f"严格改善 {improved_count}/3；"
        f"大邻域直接改善={large_neighborhood_improvement}；"
        f"解码前无分配可行状态的筛除="
        f"{predecode_no_assignment_rejections}；"
        f"不完整候选进入完整评价={incomplete_candidate_evaluations}；"
        f"最高重复比例={max_duplicate_fraction:.6f}。",
        "",
        "逐题结果：",
        "",
    ]
    for row in rows:
        report_lines.append(
            "- "
            f"{row['instance_id']}: "
            f"{row['input_objective']:.12f} -> "
            f"{row['final_objective']:.12f}, "
            f"改善 {row['improvement_pct']:.6f}%, "
            f"完整评价 {row['complete_evaluations']}。"
        )
    report_lines.extend(
        [
            "",
            "边界：本门只验证新第二算法能否直接改善强解并交付完整可行解；",
            "不授权论文结论、E3、正式 China81、BKS 或 SOTA。",
            "",
        ]
    )
    (temporary / "report.md").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )
    write_json(
        temporary / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": artifact_manifest(temporary),
        },
    )
    os.replace(temporary, OUTPUT)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
