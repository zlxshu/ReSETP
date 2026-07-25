#!/usr/bin/env python3
"""Recover the completed direct gate from traces/witnesses without search."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
FAILED_PACKAGE = (
    REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
)
REGISTRATION = PACKAGE / "direct_recovery_registration_v1.json"
ABORT = PACKAGE / "direct_improvement_gate_v1_abort_packaging"
OUTPUT = PACKAGE / "direct_improvement_gate_v2_recovered_no_search"
AUTHORITY = FAILED_PACKAGE / "g0_real_bundle_preregistration_v1.json"

for path in (
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    FAILED_PACKAGE,
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

TOL = 1.0e-9
UNRECOVERABLE = "NOT_RECOVERABLE_FROM_PERSISTED_ARTIFACTS"


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


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if (
        registration.get("status")
        != "FROZEN_BEFORE_ZERO_SEARCH_RECOVERY"
        or registration.get("search_executions") != 0
    ):
        raise RuntimeError("recovery registration is not frozen")
    for section in ("source_hashes", "abort_artifacts"):
        for relative, expected in registration[section].items():
            path = REPO / relative
            if not path.is_file() or sha256(path) != expected:
                raise RuntimeError(
                    f"registered {section} drift: {relative}"
                )
    original = registration["original_registration"]
    if sha256(REPO / original["path"]) != original["sha256"]:
        raise RuntimeError("original registration drift")
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


def recover_one(spec: dict[str, Any]) -> dict[str, Any]:
    instance_id = str(spec["instance_id"])
    bundle = load_bundle(instance_id)
    original_payload = read_json(REPO / spec["witness_path"])[
        str(spec["witness_key"])
    ]
    final_payload = read_json(ABORT / "witnesses" / f"{instance_id}.json")
    trace = read_json(ABORT / "traces" / f"{instance_id}.json")
    original = load_solution(original_payload)
    final = load_solution(final_payload)
    input_objective, _, input_exact = exact_china81_score(original, bundle)
    final_objective, final_breakdown, final_exact = exact_china81_score(
        final,
        bundle,
    )
    input_direct = check_solution(
        original,
        bundle.instance,
        bundle.prices,
    )
    final_direct = check_solution(
        final,
        bundle.instance,
        bundle.prices,
    )
    if input_exact or input_direct or final_exact or final_direct:
        raise RuntimeError(f"{instance_id}: recovery replay infeasible")
    if not math.isclose(
        input_objective,
        float(spec["expected_objective"]),
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError(f"{instance_id}: input replay mismatch")
    accepted = trace["accepted_path"]
    expected_final = (
        float(accepted[-1]["objective_after"])
        if accepted
        else input_objective
    )
    if not math.isclose(
        final_objective,
        expected_final,
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError(f"{instance_id}: final trace/witness mismatch")
    ledger = trace["ledger"]
    consumed = int(ledger["consumed"])
    duplicates = int(ledger["duplicates"])
    duplicate_fraction = duplicates / consumed if consumed else 0.0
    incomplete = sum(
        abs(
            int(row["decoded_count"])
            - (
                int(row["evaluations_after"])
                - int(row["evaluations_before"])
            )
        )
        for row in trace["trace"]
    )
    return {
        "instance_id": instance_id,
        "seed": int(spec["seed"]),
        "task_id": spec["task_id"],
        "input_objective": input_objective,
        "final_objective": final_objective,
        "improved": final_objective < input_objective - TOL,
        "improvement_pct": (
            100.0 * (input_objective - final_objective) / input_objective
        ),
        "complete_evaluations": consumed,
        "complete_evaluation_limit": int(ledger["limit"]),
        "duplicate_count": duplicates,
        "duplicate_fraction": duplicate_fraction,
        "incomplete_candidate_evaluations": incomplete,
        "elapsed_seconds": UNRECOVERABLE,
        "peak_rss": UNRECOVERABLE,
        "neighborhood_stats": trace["neighborhood_stats"],
        "improvements_by_neighborhood": (
            trace["improvements_by_neighborhood"]
        ),
        "accepted_path": accepted,
        "final_breakdown": final_breakdown,
        "input_direct_violations": len(input_direct),
        "input_exact_violations": len(input_exact),
        "final_direct_violations": len(final_direct),
        "final_exact_violations": len(final_exact),
        "trace_sha256": sha256(
            ABORT / "traces" / f"{instance_id}.json"
        ),
        "witness_sha256": sha256(
            ABORT / "witnesses" / f"{instance_id}.json"
        ),
    }


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
        raise RuntimeError(f"recovery output exists: {OUTPUT}")
    registration = verify_registration()
    OUTPUT.mkdir(parents=True)
    results = sorted(
        (recover_one(spec) for spec in registration["inputs"]),
        key=lambda row: row["instance_id"],
    )
    frozen = registration["config"]
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
    all_feasible = all(
        row["input_direct_violations"] == 0
        and row["input_exact_violations"] == 0
        and row["final_direct_violations"] == 0
        and row["final_exact_violations"] == 0
        for row in results
    )
    all_ledgers = all(
        row["incomplete_candidate_evaluations"] == 0
        and row["complete_evaluations"]
        <= int(frozen["complete_evaluation_limit_per_instance"])
        for row in results
    )
    max_duplicate = max(row["duplicate_fraction"] for row in results)
    passed = bool(
        all_feasible
        and improved_count >= int(frozen["required_improved_instances"])
        and large_improvement
        and all_visited
        and all_ledgers
        and max_duplicate <= float(frozen["duplicate_fraction_limit"])
    )
    verdict = (
        "PASS_FGE_VNS_DIRECT_IMPROVEMENT_GATE_RECOVERED_NO_SEARCH"
        if passed
        else "STOP_FGE_VNS_NO_DIRECT_IMPROVEMENT_SIGNAL_RECOVERED_NO_SEARCH"
    )
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.fge-vns-direct-recovered-metadata.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_path": REGISTRATION.relative_to(REPO).as_posix(),
            "registration_sha256": sha256(REGISTRATION),
            "search_executions": 0,
            "source_event": (
                "v1 algorithm completed; CSV packaging failed after traces "
                "and witnesses were persisted"
            ),
            "unrecoverable_fields": registration["unrecoverable_fields"],
            "python": sys.version,
            "platform": platform.platform(),
        },
    )
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
        "peak_rss",
        "input_direct_violations",
        "input_exact_violations",
        "final_direct_violations",
        "final_exact_violations",
        "trace_sha256",
        "witness_sha256",
    ]
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {key: row[key] for key in fieldnames}
            for row in results
        )
    write_json(
        OUTPUT / "recovery_details.json",
        results,
    )
    write_json(
        OUTPUT / "decision.json",
        {
            "schema": "resetp.fge-vns-direct-recovered-decision.v1",
            "verdict": verdict,
            "passed": passed,
            "search_executions_during_recovery": 0,
            "improved_instances": improved_count,
            "required_improved_instances": frozen[
                "required_improved_instances"
            ],
            "large_neighborhood_improvement": large_improvement,
            "all_neighborhoods_visited": all_visited,
            "all_outputs_feasible": all_feasible,
            "all_complete_evaluation_ledgers_valid": all_ledgers,
            "max_duplicate_fraction": max_duplicate,
            "runtime_fields_complete": False,
            "runtime_fields_status": UNRECOVERABLE,
            "next_step_authorized": (
                "PREREGISTER_UNSEEN_A_B_A_PLUS_B_MICRO_GATE"
                if passed
                else "NONE_STOP_CANDIDATE"
            ),
            "claim_boundary": registration["claim_boundary"],
        },
    )
    report = [
        "# FGE-VNS 强解直接改善门：零搜索恢复",
        "",
        f"判定：`{verdict}`。",
        "",
        (
            "v1 的算法计算、轨迹和最终解已经完成，但 CSV 打包失败；"
            "本 v2 只复算封存起点和最终解并恢复账本，搜索次数为 0。"
        ),
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
                f"完整评价 {row['complete_evaluations']}。"
            )
            for row in results
        ],
        "",
        (
            "每任务用时和峰值内存未被 v1 持久化，现记为 "
            f"`{UNRECOVERABLE}`，没有用文件时间或估算值替代。"
        ),
        (
            "边界：通过也只授权另立未见题 A/B/A+B 小门；"
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
