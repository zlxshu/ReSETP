"""Recover the sealed behavior verdict without rerunning the algorithm.

The one-shot gate completed both scenarios and wrote ``raw_runs.csv`` before
macOS created AppleDouble sidecars.  The original runner then conservatively
overwrote its summary files with an execution-failure verdict.  This script
only audits the preserved raw rows, independently replays their saved
solutions, reconstructs witnesses and the deterministic decision, and seals
the same directory after targeted AppleDouble cleanup.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_fuel_route_retirement_ev_repack_behavior_gate as gate  # noqa: E402


OUTPUT_DIR = gate.OUTPUT_DIR
INCIDENT_HASHES = OUTPUT_DIR / "appledouble_incident_raw_hashes_20260719.json"
RAW_RUNS = OUTPUT_DIR / "raw_runs.csv"
EXECUTION_FAILURE = OUTPUT_DIR / "execution_failure.json"
RECOVERY_ATTESTATION = OUTPUT_DIR / "recovery_attestation.json"
ARTIFACT_HASHES = OUTPUT_DIR / "artifact_hashes.json"
DOT_CLEAN = Path("/usr/sbin/dot_clean")

FLOAT_FIELDS = {
    "source_cost",
    "final_cost",
    "objective_delta",
    "improvement_percent",
    "claimed_final_cost",
    "claim_replay_error",
    "elapsed_seconds",
}
INT_FIELDS = {
    "source_cv_routes",
    "final_cv_routes",
    "source_route_count",
    "final_route_count",
    "accepted_count",
    "repair_attempts",
    "one_level_ejection_attempts",
    "unique_repack_candidates",
    "candidate_completion_calls",
    "counterfactual_completion_calls",
    "total_completion_calls",
    "candidate_full_replays",
    "total_full_replays",
    "complete_route_search_evaluations",
}
BOOL_FIELDS = {
    "source_feasible",
    "final_feasible",
    "customer_coverage_closed",
    "changed",
    "exact_noop",
    "activity_ledgers_closed",
    "accepted_nonvacuous",
    "accepted_all_source_retired",
    "completed_skeletons_all_fixed",
}
HASH_FIELDS = {
    "source_full_content_sha256",
    "final_full_content_sha256",
    "source_semantic_sha256",
    "final_semantic_sha256",
    "source_route_skeleton_sha256",
    "final_route_skeleton_sha256",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="verify the preserved rows without writing recovery files",
    )
    args = parser.parse_args()
    audit = _audit_preserved_run()
    if args.audit_only:
        print(json.dumps(audit["summary"], indent=2, sort_keys=True))
        return 0
    if gate._git(["status", "--porcelain"]).strip():
        raise RuntimeError(
            "recovery requires its source committed and a clean worktree"
        )
    if RECOVERY_ATTESTATION.exists() or ARTIFACT_HASHES.exists():
        raise RuntimeError("recovery is one-shot and is already sealed")
    _write_recovery(audit)
    _seal_recovery()
    print(audit["decision"]["verdict"])
    return 0


def _audit_preserved_run() -> dict[str, Any]:
    incident = gate._read_json_strict(INCIDENT_HASHES)
    if incident.get("algorithm_rerun") is not False:
        raise RuntimeError("incident record does not forbid an algorithm rerun")
    for name, expected in incident["original_failure_files"].items():
        actual = gate._sha256(OUTPUT_DIR / name)
        if actual != expected:
            raise RuntimeError(
                f"preserved incident file drifted: {name}: {actual} != {expected}"
            )
    failure = gate._read_json_strict(EXECUTION_FAILURE)
    if (
        failure.get("exception_type") != "RuntimeError"
        or "AppleDouble sidecars found" not in str(failure.get("message"))
        or failure.get("completed_scenario_count") != 2
        or failure.get("route_search_attempts") != []
    ):
        raise RuntimeError("execution failure is not the frozen sidecar incident")
    failure_metadata = gate._read_json_strict(OUTPUT_DIR / "metadata.json")
    preflight = failure_metadata.get("preflight")
    if (
        not isinstance(preflight, dict)
        or preflight.get("status") != "PASS"
        or preflight.get("route_search_attempts") != []
        or preflight.get("ledger_tamper_probe_passed") is not True
    ):
        raise RuntimeError("preserved preflight is incomplete")

    rows = _read_typed_rows()
    if [row["scenario"] for row in rows] != [
        "binding_seen_training_20c",
        "all_ev_nonbinding_25c",
    ]:
        raise RuntimeError("preserved scenario order drifted")

    witnesses: dict[str, Any] = {}
    independent_replays = 0
    sources = {
        "binding_seen_training_20c": gate._saved_final(
            "L-main-threeshift-20c-01",
            "control",
        ),
        "all_ev_nonbinding_25c": gate._saved_final(
            "L-main-threeshift-25c-01",
            "control",
        ),
    }
    exact_candidate_count = 0
    cv_zero_candidate_count = 0
    completed_costs: list[float] = []
    for row in rows:
        activity = row["activity"]
        if not gate._activity_ledgers_closed(activity):
            raise RuntimeError(f"activity ledger reopened: {row['scenario']}")
        if row["activity_ledgers_closed"] is not True:
            raise RuntimeError("raw row did not record a closed ledger")
        if (
            row["candidate_independent_replays"]
            != activity["candidate_independent_replays"]
        ):
            raise RuntimeError("candidate replay count drifted")
        if row["complete_route_search_evaluations"] != 0:
            raise RuntimeError("preserved row reports route search")
        if row["exact_noop"] is not True:
            raise RuntimeError(
                "this recovery only permits the preserved exact-noop outcome"
            )

        source = sources[row["scenario"]]
        final = source
        bundle_dir = REPO / row["bundle"]
        bundle = gate.load_search_bundle(bundle_dir)
        for kind, solution, cost_key, full_key, semantic_key, skeleton_key in (
            (
                "source",
                source,
                "source_cost",
                "source_full_content_sha256",
                "source_semantic_sha256",
                "source_route_skeleton_sha256",
            ),
            (
                "final",
                final,
                "final_cost",
                "final_full_content_sha256",
                "final_semantic_sha256",
                "final_route_skeleton_sha256",
            ),
        ):
            replay = gate._independent_cost(bundle, solution)
            independent_replays += 1
            if abs(replay - row[cost_key]) > 1.0e-7:
                raise RuntimeError(f"{row['scenario']} {kind} cost replay drifted")
            if gate.check_solution(
                solution,
                bundle.instance,
                gate.PRICES_280,
            ):
                raise RuntimeError(f"{row['scenario']} {kind} became infeasible")
            if (
                gate.solver._full_content_hash(solution) != row[full_key]
                or gate.solver._semantic_solution_hash(solution) != row[semantic_key]
                or gate.solver._route_skeleton_hash(
                    solution,
                    bundle.instance,
                )
                != row[skeleton_key]
            ):
                raise RuntimeError(f"{row['scenario']} {kind} hashes drifted")
            gate._add_witness(
                witnesses,
                solution,
                {
                    "scenario": row["scenario"],
                    "kind": kind,
                    "recovered_without_algorithm_rerun": True,
                },
            )

        for exact_index, exact in enumerate(
            activity["exact_candidates"],
            start=1,
        ):
            exact_candidate_count += 1
            if exact.get("candidate_failed_closed") is not False:
                raise RuntimeError("failed exact candidate cannot be recovered")
            for kind, snapshot_key, full_key, semantic_key in (
                (
                    "source",
                    "source_solution_snapshot",
                    "source_full_content_sha256",
                    "source_semantic_sha256",
                ),
                (
                    "counterfactual",
                    "counterfactual_solution_snapshot",
                    "counterfactual_full_content_sha256",
                    "counterfactual_semantic_sha256",
                ),
                (
                    "neutral",
                    "neutral_solution_snapshot",
                    "neutral_full_content_sha256",
                    "neutral_semantic_sha256",
                ),
                (
                    "completed",
                    "completed_solution_snapshot",
                    "completed_full_content_sha256",
                    "completed_semantic_sha256",
                ),
            ):
                solution = gate._solution_from_dict(exact[snapshot_key])
                if (
                    gate.solver._full_content_hash(solution) != exact[full_key]
                    or gate.solver._semantic_solution_hash(solution)
                    != exact[semantic_key]
                ):
                    raise RuntimeError(
                        f"exact candidate {exact_index} {kind} hash drifted"
                    )
                gate._add_witness(
                    witnesses,
                    solution,
                    {
                        "scenario": row["scenario"],
                        "kind": kind,
                        "exact_candidate": exact_index,
                        "recovered_without_algorithm_rerun": True,
                    },
                )
                if kind == "completed":
                    if gate.check_solution(
                        solution,
                        bundle.instance,
                        gate.PRICES_280,
                    ):
                        raise RuntimeError(
                            f"exact candidate {exact_index} is infeasible"
                        )
                    replay = gate._independent_cost(bundle, solution)
                    independent_replays += 1
                    if (
                        abs(replay - float(exact["completed_cost"])) > 1.0e-7
                        or abs(replay - float(exact["independent_replay_cost"]))
                        > 1.0e-7
                        or float(exact["independent_replay_error"]) > 1.0e-7
                    ):
                        raise RuntimeError(
                            f"exact candidate {exact_index} replay drifted"
                        )
                    actual_cv_routes = gate.solver._cv_route_count(solution)
                    if actual_cv_routes != exact["cv_routes_after"]:
                        raise RuntimeError(
                            f"exact candidate {exact_index} CV count drifted"
                        )
                    completed_costs.append(replay)
                    cv_zero_candidate_count += int(actual_cv_routes == 0)

    decision = gate._decision(rows, [], preflight)
    if (
        decision["verdict"] != "STOP_FUEL_ROUTE_RETIREMENT_EV_REPACK_BEHAVIOR"
        or decision["passed"] is not False
        or decision["fresh_d3_allowed"] is not False
    ):
        raise RuntimeError("preserved rows do not reproduce the frozen STOP verdict")
    summary = {
        "algorithm_rerun": False,
        "decision": decision["verdict"],
        "exact_candidate_count": exact_candidate_count,
        "cv_zero_candidate_count": cv_zero_candidate_count,
        "independent_replays": independent_replays,
        "minimum_completed_candidate_cost": min(completed_costs),
        "raw_runs_sha256": gate._sha256(RAW_RUNS),
        "route_search_attempts": [],
        "source_cost": rows[0]["source_cost"],
    }
    return {
        "decision": decision,
        "incident": incident,
        "preflight": preflight,
        "rows": rows,
        "summary": summary,
        "witnesses": witnesses,
    }


def _read_typed_rows() -> list[dict[str, Any]]:
    with RAW_RUNS.open(encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    if len(raw_rows) != 2:
        raise RuntimeError(f"expected two preserved rows, got {len(raw_rows)}")
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if key in FLOAT_FIELDS:
                parsed = float(value)
                if not math.isfinite(parsed):
                    raise RuntimeError(f"non-finite CSV field: {key}")
                row[key] = parsed
            elif key in INT_FIELDS:
                if not value.isdigit():
                    raise RuntimeError(f"invalid integer CSV field: {key}")
                row[key] = int(value)
            elif key in BOOL_FIELDS:
                if value not in {"True", "False"}:
                    raise RuntimeError(f"invalid boolean CSV field: {key}")
                row[key] = value == "True"
            elif key in HASH_FIELDS:
                if len(value) != 64:
                    raise RuntimeError(f"invalid hash CSV field: {key}")
                row[key] = value
            elif key == "activity_json":
                row["activity"] = json.loads(value)
            else:
                row[key] = value
        row["candidate_independent_replays"] = row["activity"][
            "candidate_independent_replays"
        ]
        rows.append(row)
    return rows


def _write_recovery(audit: dict[str, Any]) -> None:
    current_head = gate._git(["rev-parse", "HEAD"]).strip()
    original_wrapper_names = (
        "decision.json",
        "metadata.json",
        "report.md",
        "solution_witnesses.json",
    )
    for source_name in original_wrapper_names:
        source = OUTPUT_DIR / source_name
        target = OUTPUT_DIR / f"incident_original_{source_name}"
        if target.exists():
            raise RuntimeError(f"incident wrapper copy already exists: {target.name}")
        target.write_bytes(source.read_bytes())
        expected = audit["incident"]["original_failure_files"][source_name]
        if gate._sha256(target) != expected:
            raise RuntimeError(f"incident wrapper copy drifted: {target.name}")

    decision = dict(audit["decision"])
    decision["recovery"] = {
        "algorithm_rerun": False,
        "incident_preserved": True,
        "method": "RAW_ROWS_AND_SOLUTION_SNAPSHOTS_ONLY",
        "recovery_git_head": current_head,
    }
    metadata = {
        "schema_version": "resetp.fuel-route-retirement-behavior.v1",
        "status": "SEALED_RECOVERED_AFTER_APPLEDOUBLE",
        "evidence_level": "TRAINING_BEHAVIOR_ONLY",
        "algorithm_rerun": False,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "fresh_d3_allowed": False,
        "original_gate_git_head": audit["preflight"]["git_head"],
        "recovery_git_head": current_head,
        "preflight": audit["preflight"],
        "route_search_attempts": [],
        "incident_file": EXECUTION_FAILURE.name,
        "incident_hash_file": INCIDENT_HASHES.name,
        "incident_original_wrapper_files": [
            f"incident_original_{name}" for name in original_wrapper_names
        ],
        "raw_runs_sha256": gate._sha256(RAW_RUNS),
        "recovery_summary": audit["summary"],
    }
    gate._write_json(OUTPUT_DIR / "decision.json", decision)
    gate._write_json(OUTPUT_DIR / "metadata.json", metadata)
    gate._write_json(
        OUTPUT_DIR / "solution_witnesses.json",
        audit["witnesses"],
    )
    gate._write_json(
        RECOVERY_ATTESTATION,
        {
            "schema_version": ("resetp.fuel-route-retirement-recovery-attestation.v1"),
            "passed": True,
            "algorithm_rerun": False,
            "original_execution_failure_preserved": True,
            "summary": audit["summary"],
            "decision_reproduced": audit["decision"],
            "recovery_git_head": current_head,
        },
    )
    binding = audit["rows"][0]
    activity = binding["activity"]
    exact = activity["exact_candidates"]
    lines = [
        "# 燃油路线退役—电动重整：零搜索行为门",
        "",
        "判定：`STOP_FUEL_ROUTE_RETIREMENT_EV_REPACK_BEHAVIOR`。",
        "",
        "算法已在首次调用中完成；本报告只从保留的原始两行、候选快照和"
        "独立复算恢复，未重新运行算法。",
        "",
        "20客户题形成9个重整骨架，对前4个做了完整完成与两次复算，"
        "但没有一个同时满足成本下降和燃油路线减少。",
        f"最便宜候选为 `{min(float(x['completed_cost']) for x in exact):.9f}`，"
        f"高于原解 `{binding['source_cost']:.9f}`；"
        f"其中 `{audit['summary']['cv_zero_candidate_count']}` 个候选"
        "把燃油路线降为0，但成本仍更高。",
        "",
        "25客户全电控制逐位不变；候选、完成、候选复算和接受均为0。",
        "路线搜索尝试为0。D3、正式算法比较、阶段二和全量实验均不获授权。",
        "",
        "首次封存被移动硬盘自动生成的AppleDouble旁文件拦截；"
        "`execution_failure.json`和原始哈希记录继续保留。本恢复只修封存，"
        "不改变算法结果。",
        "",
    ]
    (OUTPUT_DIR / "report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _seal_recovery() -> None:
    _targeted_dot_clean()
    before_seal = _sidecars()
    if before_seal:
        raise RuntimeError(f"sidecars remain before seal: {before_seal}")
    gate._write_json(
        OUTPUT_DIR / "appledouble_seal.json",
        {
            "schema_version": "resetp.appledouble-seal.v1",
            "cleanup": "/usr/sbin/dot_clean -m <output_dir>",
            "sidecars": [],
            "passed": True,
        },
    )
    _targeted_dot_clean()
    artifacts = {
        path.name: gate._sha256(path)
        for path in sorted(OUTPUT_DIR.iterdir())
        if path.is_file()
        and path.name != ARTIFACT_HASHES.name
        and not path.name.startswith("._")
    }
    gate._write_json(
        ARTIFACT_HASHES,
        {
            "schema_version": ("resetp.fuel-route-retirement-artifacts.v1"),
            "artifacts": artifacts,
        },
    )
    _targeted_dot_clean()
    if _sidecars():
        raise RuntimeError("sidecars reappeared after final cleanup")
    reread = gate._read_json_strict(ARTIFACT_HASHES)
    if reread["artifacts"] != artifacts:
        raise RuntimeError("artifact manifest reread drifted")
    for name, expected in artifacts.items():
        path = OUTPUT_DIR / name
        if path.is_symlink() or gate._sha256(path) != expected:
            raise RuntimeError(f"artifact hash mismatch: {name}")
    for path in OUTPUT_DIR.glob("*.json"):
        gate._read_json_strict(path)


def _targeted_dot_clean() -> None:
    if not DOT_CLEAN.is_file():
        raise RuntimeError(f"missing AppleDouble cleanup tool: {DOT_CLEAN}")
    result = subprocess.run(
        [str(DOT_CLEAN), "-m", str(OUTPUT_DIR)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"targeted dot_clean failed: {result.stderr.strip()}")


def _sidecars() -> list[str]:
    return sorted(str(path.relative_to(OUTPUT_DIR)) for path in OUTPUT_DIR.rglob("._*"))


if __name__ == "__main__":
    raise SystemExit(main())
