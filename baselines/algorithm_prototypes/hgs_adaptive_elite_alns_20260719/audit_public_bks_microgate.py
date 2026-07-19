#!/usr/bin/env python3
"""Independent zero-search audit for the HGS-AEALNS-03 public microgate."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EVIDENCE = HERE / "public_bks_microgate"
OUT = HERE / "public_bks_microgate_independent_audit"
BUNDLES = (
    REPO
    / "baselines/e2_alns/"
    "solomon_sintef_formal_bundles_20260717_v3"
)
INSTANCES = ("C106", "C205", "R109", "R208", "RC105", "RC205")
PURE_HGS = "pyvrp_0_12_2_hgs"
HYBRID = "hgs_adaptive_elite_alns_03"
ALGORITHMS = (PURE_HGS, HYBRID)
TOL = 1.0e-8


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    checks: list[dict[str, Any]] = []
    rows = _csv(EVIDENCE / "raw_runs.csv")
    solutions = _json(EVIDENCE / "solutions.json")
    decision = _json(EVIDENCE / "decision.json")
    metadata = _json(EVIDENCE / "metadata.json")

    _check(
        checks,
        "five_piece_present",
        all(
            (EVIDENCE / name).is_file()
            for name in (
                "metadata.json",
                "raw_runs.csv",
                "decision.json",
                "artifact_hashes.json",
                "report.md",
            )
        ),
        str(EVIDENCE.relative_to(REPO)),
    )
    _check(
        checks,
        "artifact_hash_manifest",
        _verify_hash_manifest(EVIDENCE),
        "all recorded artifact hashes",
    )
    _check(
        checks,
        "row_scope",
        len(rows) == 12
        and {row["instance"] for row in rows} == set(INSTANCES)
        and {row["algorithm"] for row in rows} == set(ALGORITHMS),
        f"rows={len(rows)}",
    )
    _check(
        checks,
        "solution_scope",
        set(solutions)
        == {
            f"{instance}::{algorithm}"
            for instance in INSTANCES
            for algorithm in ALGORITHMS
        },
        f"solutions={len(solutions)}",
    )

    for row in rows:
        key = f"{row['instance']}::{row['algorithm']}"
        payload = solutions[key]
        recomputed = _recompute_solution(
            BUNDLES / row["instance"],
            payload,
        )
        _check(
            checks,
            f"{key}.coverage_capacity_time",
            bool(recomputed["feasible"]),
            json.dumps(
                {
                    "coverage": recomputed["coverage"],
                    "capacity": recomputed["capacity"],
                    "time_windows": recomputed["time_windows"],
                    "route_limit": recomputed["route_limit"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        _check(
            checks,
            f"{key}.route_count",
            int(row["route_count"]) == int(recomputed["route_count"]),
            (
                f"recorded={row['route_count']}; "
                f"recomputed={recomputed['route_count']}"
            ),
        )
        _check(
            checks,
            f"{key}.distance",
            abs(
                float(row["distance_double"])
                - float(recomputed["distance_double"])
            )
            <= TOL,
            (
                f"recorded={row['distance_double']}; "
                f"recomputed={recomputed['distance_double']}"
            ),
        )
        payload_sha = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        _check(
            checks,
            f"{key}.solution_sha",
            payload_sha == row["solution_sha256"],
            payload_sha,
        )

    recomputed_pairwise = _pairwise(rows)
    _check(
        checks,
        "pairwise_recomputed",
        recomputed_pairwise
        == decision.get("pairwise_vs_pure_hgs"),
        json.dumps(recomputed_pairwise, sort_keys=True),
    )
    hgs_excess = sum(
        int(row["vehicle_excess_vs_bks"])
        for row in rows
        if row["algorithm"] == PURE_HGS
    )
    hybrid_excess = sum(
        int(row["vehicle_excess_vs_bks"])
        for row in rows
        if row["algorithm"] == HYBRID
    )
    _check(
        checks,
        "bks_vehicle_excess_recomputed",
        decision.get("bks_vehicle_excess")
        == {PURE_HGS: hgs_excess, HYBRID: hybrid_excess},
        f"pure={hgs_excess}; hybrid={hybrid_excess}",
    )
    _check(
        checks,
        "decision_recomputed",
        recomputed_pairwise
        == {"hybrid_wins": 2, "ties": 2, "hybrid_losses": 2}
        and hybrid_excess > hgs_excess
        and decision.get("verdict")
        == "STOP_HGS_AEALNS_03_ANY_LOSS"
        and decision.get("strong_positive") is False,
        str(decision.get("verdict")),
    )
    _check(
        checks,
        "time_and_activation",
        decision.get("time_checks", {}).get("pass") is True
        and all(
            int(row["education_triggers"]) > 0
            and int(row["education_removed_customers"]) > 0
            and float(row["education_seconds"]) > 0.0
            for row in rows
            if row["algorithm"] == HYBRID
        ),
        "all six hybrid runs triggered under accepted time limits",
    )
    _check(
        checks,
        "common_initial_per_instance",
        all(
            len(
                {
                    row["common_initial_sha256"]
                    for row in rows
                    if row["instance"] == instance
                }
            )
            == 1
            for instance in INSTANCES
        ),
        "same initial hash in both arms",
    )
    _check(
        checks,
        "bks_blind_solver_inputs",
        int(metadata.get("solver_visible_bks_fields", -1)) == 0
        and all(
            "bks"
            not in (
                (BUNDLES / instance / "instance.json")
                .read_text(encoding="utf-8")
                .lower()
            )
            for instance in INSTANCES
        ),
        str(metadata.get("bks_association_timing")),
    )
    _check(
        checks,
        "source_input_protected_hashes",
        _verify_metadata_hashes(metadata),
        "all paths still match the pre-run SHA-256 values",
    )
    _check(
        checks,
        "scope_stays_closed",
        decision.get("additional_public_run_allowed") is False
        and decision.get("formal_56_instance_run_allowed") is False
        and decision.get("china81_run_allowed") is False
        and decision.get("stage2_allowed") is False,
        "all escalation flags false",
    )

    failures = [row for row in checks if not bool(row["passed"])]
    audit_decision = {
        "verdict": (
            "PASS_HGS_AEALNS_03_ZERO_SEARCH_AUDIT_STOP_PRESERVED"
            if not failures
            else "FAIL_HGS_AEALNS_03_ZERO_SEARCH_AUDIT"
        ),
        "checks": len(checks),
        "passed": len(checks) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "search_evaluations": 0,
        "solver_reruns": 0,
        "microgate_verdict_preserved": (
            "STOP_HGS_AEALNS_03_ANY_LOSS"
            if not failures
            else None
        ),
        "public_hybrid_goal_achieved": False,
        "china81_run_allowed": False,
        "stage2_allowed": False,
    }
    audit_metadata = {
        "schema_version": "resetp.hgs-aealns-03-zero-search-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "audit_script_sha256": _sha(Path(__file__).resolve()),
        "evidence_decision_sha256": _sha(EVIDENCE / "decision.json"),
        "evidence_raw_runs_sha256": _sha(EVIDENCE / "raw_runs.csv"),
        "search_evaluations": 0,
        "solver_reruns": 0,
        "claim_boundary": (
            "This audit independently recomputes route coverage, capacity, "
            "time windows, route counts, distances, solution hashes, "
            "pairwise outcomes and the stop decision. It performs no search."
        ),
    }
    report = "\n".join(
        [
            "# HGS-AEALNS-03 独立零搜索审计",
            "",
            f"- 判决：`{audit_decision['verdict']}`",
            f"- 检查：{audit_decision['passed']}/{audit_decision['checks']} 通过。",
            "- 新增搜索与求解器重跑：0。",
            "- 独立复算确认：2胜、2平、2负；候选必须停止。",
            "- RC105 的 23 路结果合法但明显劣于纯 HGS 的 15 路，"
            "不是记录、距离或可行性检查错误。",
            "- China81、阶段二和公开全量仍未放行。",
            "",
        ]
    )
    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", checks)
    _write_json(OUT / "metadata.json", audit_metadata)
    _write_json(OUT / "decision.json", audit_decision)
    (OUT / "report.md").write_text(report, encoding="utf-8")
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
    print(json.dumps(audit_decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


def _recompute_solution(bundle: Path, payload: dict[str, Any]) -> dict[str, Any]:
    raw = _json(bundle / "instance.json")
    nodes = raw["nodes"]
    node_index = {
        str(node["node_id"]): index
        for index, node in enumerate(nodes)
    }
    customer_ids = {
        str(node["node_id"])
        for node in nodes
        if str(node["node_type"]).lower() == "c"
    }
    matrix = np.load(bundle / "distance_matrix.npy", allow_pickle=False)
    capacity_limit = float(raw["metadata"]["vehicle_capacity"])
    route_limit = int(raw["metadata"]["num_cv"])
    visits: list[str] = []
    total_distance = 0.0
    capacity_pass = True
    time_pass = True
    depot_id = str(nodes[0]["node_id"])
    for route in payload["routes"]:
        sequence = [str(value) for value in route["node_sequence"]]
        if (
            len(sequence) < 2
            or sequence[0] != depot_id
            or sequence[-1] != depot_id
        ):
            time_pass = False
            continue
        route_load = 0.0
        current_time = float(nodes[0]["ready_time"])
        for source_id, target_id in zip(sequence, sequence[1:]):
            source = node_index[source_id]
            target = node_index[target_id]
            travel = float(matrix[source, target])
            total_distance += travel
            current_time += travel
            target_node = nodes[target]
            current_time = max(
                current_time,
                float(target_node["ready_time"]),
            )
            if current_time > float(target_node["due_time"]) + TOL:
                time_pass = False
            current_time += float(target_node["service_time"])
            if target_id in customer_ids:
                visits.append(target_id)
                route_load += float(target_node["demand"])
        if route_load > capacity_limit + TOL:
            capacity_pass = False
    coverage_pass = (
        len(visits) == len(customer_ids)
        and len(set(visits)) == len(customer_ids)
        and set(visits) == customer_ids
    )
    route_count = len(payload["routes"])
    route_limit_pass = route_count <= route_limit
    return {
        "coverage": coverage_pass,
        "capacity": capacity_pass,
        "time_windows": time_pass,
        "route_limit": route_limit_pass,
        "feasible": (
            coverage_pass
            and capacity_pass
            and time_pass
            and route_limit_pass
        ),
        "route_count": route_count,
        "distance_double": total_distance,
    }


def _pairwise(rows: list[dict[str, str]]) -> dict[str, int]:
    wins = ties = losses = 0
    for instance in INSTANCES:
        arms = {
            row["algorithm"]: (
                int(row["route_count"]),
                float(row["distance_double"]),
            )
            for row in rows
            if row["instance"] == instance
        }
        wins += int(arms[HYBRID] < arms[PURE_HGS])
        ties += int(arms[HYBRID] == arms[PURE_HGS])
        losses += int(arms[HYBRID] > arms[PURE_HGS])
    return {
        "hybrid_wins": wins,
        "ties": ties,
        "hybrid_losses": losses,
    }


def _verify_hash_manifest(root: Path) -> bool:
    expected = _json(root / "artifact_hashes.json")
    return all(
        (root / name).is_file()
        and _sha(root / name) == digest
        for name, digest in expected.items()
    )


def _verify_metadata_hashes(metadata: dict[str, Any]) -> bool:
    for field in ("source_hashes", "protected_hashes", "input_hashes"):
        for relative, expected in metadata.get(field, {}).items():
            path = REPO / relative
            if not path.is_file() or _sha(path) != expected:
                return False
    return True


def _check(
    rows: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: str,
) -> None:
    rows.append(
        {
            "check": name,
            "passed": bool(passed),
            "detail": detail,
            "search_evaluations": 0,
        }
    )


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    return list(
        csv.DictReader(path.open(encoding="utf-8", newline=""))
    )


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
