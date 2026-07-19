#!/usr/bin/env python3
"""Independent zero-search audit for HGS-SAFE-RECORD-LNS-04.

This script does not call a solver. It independently recomputes feasibility,
distance, result ordering, the frozen stop decision, and the attribution defect
caused by different results when the enhancement never triggered.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EVIDENCE = HERE / "public_bks_seed1_gate"
OUT = HERE / "public_bks_seed1_gate_independent_audit"
BUNDLES = (
    REPO
    / "baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3"
)
INSTANCES = ("C105", "C204", "R108", "R207", "RC104", "RC204")
PURE_HGS = "pyvrp_0_12_2_hgs"
HYBRID = "hgs_safe_record_lns_04"
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
        "all recorded evidence hashes",
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
        recomputed = _recompute_solution(BUNDLES / row["instance"], payload)
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

    pairwise = _pairwise(rows)
    _check(
        checks,
        "pairwise_recomputed",
        pairwise == decision.get("pairwise_vs_pure_hgs"),
        json.dumps(pairwise, sort_keys=True),
    )

    bks_excess = {
        algorithm: sum(
            int(row["vehicle_excess_vs_bks"])
            for row in rows
            if row["algorithm"] == algorithm
        )
        for algorithm in ALGORITHMS
    }
    _check(
        checks,
        "bks_vehicle_excess_recomputed",
        bks_excess == decision.get("bks_vehicle_excess"),
        json.dumps(bks_excess, sort_keys=True),
    )

    hybrid_rows = {
        row["instance"]: row
        for row in rows
        if row["algorithm"] == HYBRID
    }
    pure_rows = {
        row["instance"]: row
        for row in rows
        if row["algorithm"] == PURE_HGS
    }
    no_trigger_instances = sorted(
        instance
        for instance, row in hybrid_rows.items()
        if int(row["education_triggers"]) == 0
    )
    no_trigger_divergence = sorted(
        instance
        for instance in no_trigger_instances
        if _result_key(hybrid_rows[instance])
        != _result_key(pure_rows[instance])
        or hybrid_rows[instance]["solution_sha256"]
        != pure_rows[instance]["solution_sha256"]
    )
    _check(
        checks,
        "activation_contract_failed_as_recorded",
        decision.get("reasons", {}).get(
            "safe_education_activation_pass"
        )
        is False
        and no_trigger_instances == ["R108", "R207", "RC104", "RC204"],
        json.dumps(no_trigger_instances),
    )
    _check(
        checks,
        "no_effect_attribution_defect_recomputed",
        no_trigger_divergence == ["R207", "RC104"],
        json.dumps(no_trigger_divergence),
    )
    _check(
        checks,
        "decision_recomputed",
        pairwise == {"hybrid_wins": 1, "ties": 3, "hybrid_losses": 2}
        and bks_excess[HYBRID] == bks_excess[PURE_HGS] == 0
        and decision.get("verdict") == "STOP_SAFE_RECORD_LNS_INTEGRITY"
        and decision.get("strong_positive") is False,
        str(decision.get("verdict")),
    )
    _check(
        checks,
        "time_fairness",
        decision.get("time_checks", {}).get("pass") is True,
        "recorded time gate passed",
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
        "same recorded initial hash in both arms",
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
        "all protected paths still match pre-run hashes",
    )
    _check(
        checks,
        "scope_stays_closed",
        decision.get("seed_repeat_allowed") is False
        and decision.get("formal_56_instance_run_allowed") is False
        and decision.get("china81_run_allowed") is False
        and decision.get("stage2_allowed") is False,
        "all escalation flags false",
    )

    failures = [check for check in checks if not bool(check["passed"])]
    audit_decision = {
        "verdict": (
            "PASS_SAFE_RECORD_LNS_ZERO_SEARCH_AUDIT_"
            "STOP_AND_NONATTRIBUTION_PRESERVED"
            if not failures
            else "FAIL_SAFE_RECORD_LNS_ZERO_SEARCH_AUDIT"
        ),
        "checks": len(checks),
        "passed": len(checks) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "search_evaluations": 0,
        "solver_reruns": 0,
        "microgate_verdict_preserved": (
            "STOP_SAFE_RECORD_LNS_INTEGRITY" if not failures else None
        ),
        "pairwise_recomputed": pairwise,
        "no_trigger_instances": no_trigger_instances,
        "no_trigger_divergence_instances": no_trigger_divergence,
        "effect_attribution_valid": False,
        "public_hybrid_goal_achieved": False,
        "china81_run_allowed": False,
        "stage2_allowed": False,
    }
    audit_metadata = {
        "schema_version": "resetp.hgs-safe-record-lns-zero-search-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "audit_script_sha256": _sha(Path(__file__).resolve()),
        "evidence_decision_sha256": _sha(EVIDENCE / "decision.json"),
        "evidence_raw_runs_sha256": _sha(EVIDENCE / "raw_runs.csv"),
        "search_evaluations": 0,
        "solver_reruns": 0,
        "claim_boundary": (
            "This audit independently recomputes feasibility, distances, "
            "solution hashes, pairwise results, the frozen stop decision, "
            "and the no-trigger attribution defect. It performs no search."
        ),
    }
    report = "\n".join(
        [
            "# HGS-SAFE-RECORD-LNS-04 独立零搜索审计",
            "",
            f"- 判决：`{audit_decision['verdict']}`",
            f"- 检查：{audit_decision['passed']}/{audit_decision['checks']} 通过。",
            "- 新增搜索与求解器重跑：0。",
            "- 独立复算确认：1 胜、3 平、2 负；候选必须停止。",
            "- R207 与 RC104 的增强动作触发数均为 0，"
            "但两臂结果不同；因此名义上的 R207 胜利不能归因于增强算法。",
            "- 旧框架只能证明该候选未过门，不能证明增强件产生了哪次胜负。",
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
        str(node["node_id"]): index for index, node in enumerate(nodes)
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
            current_time = max(current_time, float(target_node["ready_time"]))
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


def _result_key(row: dict[str, str]) -> tuple[int, float]:
    return int(row["route_count"]), float(row["distance_double"])


def _pairwise(rows: list[dict[str, str]]) -> dict[str, int]:
    wins = ties = losses = 0
    for instance in INSTANCES:
        arms = {
            row["algorithm"]: _result_key(row)
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
        (root / name).is_file() and _sha(root / name) == digest
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
    return list(csv.DictReader(path.open(encoding="utf-8", newline="")))


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = (
        ["check", "passed", "detail", "search_evaluations"]
        if rows
        else []
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
