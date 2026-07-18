#!/usr/bin/env python3
"""Re-audit the frozen G1-independent China81 chain after fail-closed hardening."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from china81_artifact_integrity_20260719 import (
    load_json,
    require_decision,
    verify_artifact_package,
)


REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data/ChinaInstances"
OUT = DATA / "china81_fail_closed_review_v1_20260719"
AUTHORITY_FILES = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
PACKAGES = (
    (
        "road_graphs",
        DATA / "china_stage2_sparse_connected_osrm_graphs_v5_20260718",
        "PASS_CHINA81_SPARSE_CONNECTED_OSRM_GRAPHS",
        {
            "graph_count": 6,
            "all_distinct_points_matched_under_both_profiles": True,
            "formal_search_allowed": False,
        },
    ),
    (
        "static_inputs",
        DATA / "china81_stage2_static_inputs_v1_20260718",
        "PASS_G1_INDEPENDENT_STATIC_INPUTS_FROZEN",
        {"formal_experiment_authorized": False, "search_evaluations": 0},
    ),
    (
        "order_attributes",
        DATA / "china81_order_attributes_mc001_v1_20260718",
        "PASS_CHINA81_MC001_ORDER_ATTRIBUTE_LAYER_BUILT",
        {
            "instances": 81,
            "order_rows": 5_805,
            "joint_empirical_rows_preserved": True,
            "formal_search_allowed": False,
        },
    ),
    (
        "directed_matrices",
        DATA / "china81_local_directed_matrices_v9_20260718",
        "PASS_CHINA81_LOCAL_DIRECTED_THREE_MATRICES",
        {"ordered_pairs_complete": True, "unreachable_pairs": 0},
    ),
    (
        "matrix_diagnostics",
        DATA / "china81_matrix_diagnostics_v1_20260718",
        "PASS_CHINA81_MATRIX_DIAGNOSTICS_COMPLETE",
        {
            "all_six_route_counts_match": True,
            "materialized_ordered_pairs": 1_578_948,
            "materialized_ordered_pairs_complete": True,
        },
    ),
    (
        "g1_independent_freeze",
        DATA / "china81_g1_independent_frozen_v2_20260718",
        "PASS_CHINA81_G1_INDEPENDENT_DATA_FROZEN",
        {
            "passed_instances": 81,
            "failed_instances": 0,
            "package_violations": [],
            "observed_orders": 5_805,
            "formal_search_allowed": False,
        },
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for package_id, package, verdict_prefix, fields in PACKAGES:
        verified_files = verify_artifact_package(package, AUTHORITY_FILES)
        decision = require_decision(
            package / "decision.json",
            verdict_prefix,
            fields,
        )
        rows.append(
            {
                "package_id": package_id,
                "package": str(package.relative_to(REPO)),
                "verified_files": verified_files,
                "decision": decision.get("verdict", decision.get("decision")),
                "artifact_hashes_sha256": sha256(package / "artifact_hashes.json"),
                "status": "PASS",
            }
        )

    pipeline = load_json(DATA / "china81_stage2_road_pipeline_status_20260718.json")
    if (
        pipeline.get("phase") != "complete"
        or pipeline.get("state") != "PASS_FORMAL_ACCEPTANCE_HELD"
        or pipeline.get("formal_search_allowed") is not False
    ):
        raise RuntimeError("road pipeline is not complete with formal acceptance held")

    readiness = load_json(
        DATA
        / "china_stage2_g1_independent_readiness_v1_20260718"
        / "decision.json"
    )
    if (
        readiness.get("formal_search_allowed") is not False
        or readiness.get("open_blocker_ids") != ["G1-FREEZE-MERGE"]
    ):
        raise RuntimeError("G1 merge hold is missing or readiness gate drifted")

    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china81.fail-closed-review.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "G1-independent China81 package and decision integrity",
            "packages_checked": len(rows),
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    verdict = "PASS_CHINA81_FAIL_CLOSED_REVIEW__FORMAL_G1_GATE_REMAINS"
    write_json(
        OUT / "decision.json",
        {
            "verdict": verdict,
            "packages_checked": len(rows),
            "package_failures": 0,
            "g1_freeze_merge": "HELD_BY_DESIGN",
            "formal_experiment_authorized": False,
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    (OUT / "report.md").write_text(
        "# China81 失败关闭复核\n\n"
        "六个权威包的全部登记文件已逐项复算 SHA-256，四个关键记录面均在哈希"
        "清单中，关键判决字段与独立计数一致。道路流水线保持"
        "`PASS_FORMAL_ACCEPTANCE_HELD`，唯一开放项仍是"
        "`G1-FREEZE-MERGE=HELD_BY_DESIGN`。本复核没有运行算法搜索，也不构成"
        "正式 China81 验收。\n",
        encoding="utf-8",
    )
    hashes = {
        path.name: sha256(path)
        for path in OUT.iterdir()
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(OUT / "artifact_hashes.json", {"sha256": hashes})
    print(json.dumps({"verdict": verdict, "packages_checked": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
