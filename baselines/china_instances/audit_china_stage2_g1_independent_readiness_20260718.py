#!/usr/bin/env python3
"""Build a result-blind readiness ledger for the G1-independent China lane."""

from __future__ import annotations

import hashlib
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PARAMETERS = REPO / "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
STATIC = (
    REPO
    / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
    / "decision.json"
)
STATISTICS = (
    REPO / "data/ChinaInstances/china_e3_e7_significance_contract_v2_20260718.json"
)
LOCATIONS = (
    REPO
    / "data/ChinaInstances/china81_customer_location_assignments_mc005_final_v2_20260718"
    / "decision.json"
)
ORDERS = (
    REPO
    / "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718"
    / "decision.json"
)
ROAD_GRAPHS = (
    REPO
    / "data/ChinaInstances/china_stage2_sparse_connected_osrm_graphs_v5_20260718"
    / "SPARSE_CONNECTED_OSRM_GRAPHS_COMPLETE.json"
)
ROAD_MATRICES = (
    REPO
    / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
    / "decision.json"
)
OUTPUT = (
    REPO / "data/ChinaInstances/china_stage2_g1_independent_readiness_v1_20260718"
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def item(
    item_id: str,
    area: str,
    state: str,
    blocking: bool,
    evidence: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "area": area,
        "state": state,
        "blocks_formal_acceptance": blocking,
        "evidence": evidence,
        "next_action": next_action,
    }


def build_items() -> list[dict[str, Any]]:
    parameters = load(PARAMETERS)
    static = load(STATIC)
    statistics = load(STATISTICS)
    locations = load(LOCATIONS)
    orders = load(ORDERS)
    graphs = load(ROAD_GRAPHS)
    matrices = load(ROAD_MATRICES)

    static_pass = static.get("verdict", "").startswith(
        "PASS_G1_INDEPENDENT_STATIC_INPUTS_FROZEN"
    )

    return [
        item(
            "DATA-LOCATIONS",
            "China81",
            "PASS" if locations.get("verdict", "").startswith("PASS_") else "DRIFT",
            False,
            str(LOCATIONS.relative_to(REPO)),
            "retain frozen mutually exclusive customer identities",
        ),
        item(
            "DATA-ORDERS",
            "China81",
            "PASS" if orders.get("verdict", "").startswith("PASS_") else "MISSING",
            False,
            str(ORDERS.relative_to(REPO)),
            "retain joint MC-001 empirical-row sampling and proxy boundary",
        ),
        item(
            "ROAD-GRAPHS",
            "roads",
            "PASS"
            if (graphs.get("decision") or graphs.get("verdict", "")).startswith("PASS_")
            else "RUNNING",
            True,
            str(ROAD_GRAPHS.relative_to(REPO)),
            "retain six APFS-built sparse-connected CV/EV graphs and archive hashes",
        ),
        item(
            "ROAD-MATRICES",
            "roads",
            "PASS"
            if matrices.get("verdict", "").startswith("PASS_CHINA81_LOCAL_DIRECTED")
            and matrices.get("ordered_pairs_complete") is True
            else "RUNNING",
            True,
            str(ROAD_MATRICES.relative_to(REPO)),
            "retain complete directed distance, duration and sum(v^2*d) matrices",
        ),
        item(
            "FACILITY-DEPOT-CHARGING",
            "infrastructure",
            "PASS" if static_pass else "UNRESOLVED",
            True,
            str(STATIC.relative_to(REPO)),
            "retain 22 kW x 2 gun planned-capacity scenario boundary",
        ),
        item(
            "FACILITY-PUBLIC-STATIONS",
            "infrastructure",
            "PASS" if static_pass else "UNRESOLVED",
            True,
            (
                "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718/"
                "facilities.csv"
            ),
            "retain identities and 60 kW x 1 gun scenario-proxy boundary",
        ),
        item(
            "COST-CHINA-CONTRACT",
            "parameters",
            "PASS" if static_pass else "UNRESOLVED",
            True,
            str(STATIC.relative_to(REPO)),
            "retain scenario-proxy labels and required sensitivities",
        ),
        item(
            "STATS-METHOD",
            "statistics",
            "PASS" if statistics.get("partial_approval", {}).get("whole_contract_frozen") else "DRIFT",
            False,
            str(STATISTICS.relative_to(REPO)),
            "keep 27 paired units, Holm correction and result-blind seed rule",
        ),
        item(
            "STATS-E5-MATERIAL-EFFECT",
            "statistics",
            "PASS" if static_pass else "UNRESOLVED",
            True,
            str(STATIC.relative_to(REPO)),
            "retain frozen 10 percentage-point and 2 percent E5 thresholds",
        ),
        item(
            "STATS-E7-MATERIAL-EFFECTS",
            "statistics",
            "PASS" if static_pass else "UNRESOLVED",
            True,
            str(STATIC.relative_to(REPO)),
            "retain frozen 2 percent cost/emissions and zero-violation E7 thresholds",
        ),
        item(
            "G1-FREEZE-MERGE",
            "governance",
            "HELD_BY_DESIGN",
            True,
            "docs/handoff/china_stage2_g1_independent_execution_contract_20260718.md",
            "merge and formally accept only after G1 and phase one are frozen",
        ),
    ]


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    items = build_items()
    blockers = [row for row in items if row["blocks_formal_acceptance"] and row["state"] != "PASS"]
    payload = {
        "schema": "resetp.china.stage2-g1-independent-readiness.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "INDEPENDENT_WORK_ACTIVE__FORMAL_ACCEPTANCE_HELD",
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "items": items,
        "open_blocker_count": len(blockers),
        "open_blocker_ids": [row["id"] for row in blockers],
    }
    decision_path = OUTPUT / "decision.json"
    decision_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metadata_path = OUTPUT / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": "resetp.china.stage2-g1-independent-readiness.metadata.v1",
                "created_at_utc": payload["created_at_utc"],
                "input_files": {
                    str(path.relative_to(REPO)): (
                        sha256(path) if path.is_file() else None
                    )
                    for path in (
                        PARAMETERS,
                        STATIC,
                        STATISTICS,
                        LOCATIONS,
                        ORDERS,
                        ROAD_GRAPHS,
                        ROAD_MATRICES,
                    )
                },
                "formal_search_allowed": False,
                "search_evaluations": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    raw_runs_path = OUTPUT / "raw_runs.csv"
    with raw_runs_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(items[0]))
        writer.writeheader()
        writer.writerows(items)
    lines = [
        "# 阶段二 G1 独立输入线就绪台账",
        "",
        "判决：`INDEPENDENT_WORK_ACTIVE__FORMAL_ACCEPTANCE_HELD`。",
        "",
        "本台账不读取算法结果，搜索评价次数为 0。它只区分已完成输入、待补证参数和必须等待 G1 的正式验收门。",
        "",
        "| ID | 领域 | 状态 | 阻断正式验收 | 下一动作 |",
        "|---|---|---|---:|---|",
    ]
    for row in items:
        lines.append(
            f"| {row['id']} | {row['area']} | {row['state']} | "
            f"{'是' if row['blocks_formal_acceptance'] else '否'} | {row['next_action']} |"
        )
    (OUTPUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hashes = {
        path.name: sha256(path)
        for path in (
            metadata_path,
            raw_runs_path,
            decision_path,
            OUTPUT / "report.md",
        )
    }
    (OUTPUT / "artifact_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
