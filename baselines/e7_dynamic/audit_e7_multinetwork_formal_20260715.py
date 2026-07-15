#!/usr/bin/env python3
"""Independently audit the sealed E7 formal matrix and 28-day replay."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import statistics
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FORMAL = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
REPLAY = ROOT / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715"
OUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715"
ARMS = ("full", "no_cooperation", "no_participation", "simple_insertion")
TOL = 1e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty audit table: {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_manifest(root: Path) -> tuple[int, list[str]]:
    manifest = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))
    bad = []
    for relative, expected in manifest.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            bad.append(relative)
    return len(manifest), bad


def mean(rows: list[dict[str, Any]], field: str) -> float:
    return statistics.fmean(float(row[field]) for row in rows) if rows else 0.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    formal_hash_count, formal_hash_failures = verify_manifest(FORMAL)
    replay_hash_count, replay_hash_failures = verify_manifest(REPLAY)
    sessions = json.loads((FORMAL / "sessions.json").read_text(encoding="utf-8"))
    task_rows: list[dict[str, Any]] = []
    payloads: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for payload in sessions:
        key = (
            str(payload["network"]),
            str(payload["responsibility_condition"]),
            int(payload["stream_seed"]),
            str(payload["arm"]),
        )
        payloads[key] = payload
        task_rows.append(
            {
                "network": key[0],
                "condition": key[1],
                "stream": key[2],
                "arm": key[3],
                "execution_status": payload["execution_status"],
                "completed_stage_count": int(payload.get("stages", 0)),
                "charging_window_count": int(
                    payload.get("full_day_execution", {}).get("charging_window_count", 0)
                ),
            }
        )

    pair_rows: list[dict[str, Any]] = []
    for network, condition, stream in sorted(
        {(key[0], key[1], key[2]) for key in payloads}
    ):
        group = {arm: payloads[(network, condition, stream, arm)] for arm in ARMS}
        executable = all(row["execution_status"] == "PASS" for row in group.values())
        pair: dict[str, Any] = {
            "network": network,
            "condition": condition,
            "stream": stream,
            "all_four_arms_executable": executable,
        }
        if executable:
            full = group["full"]
            no_coop = group["no_cooperation"]
            no_part = group["no_participation"]
            simple = group["simple_insertion"]
            full_profit = float(full["final_running"]["total_profit"])
            no_coop_profit = float(no_coop["final_running"]["total_profit"])
            no_part_profit = float(no_part["final_running"]["total_profit"])
            full_depot = full["final_running"]["depot_profit"]
            no_coop_depot = no_coop["final_running"]["depot_profit"]
            pair.update(
                {
                    "full_minus_no_cooperation_net_profit": full_profit - no_coop_profit,
                    "full_minus_no_cooperation_revenue": float(
                        full["final_running"]["total_revenue"]
                    )
                    - float(no_coop["final_running"]["total_revenue"]),
                    "full_minus_no_cooperation_cost": float(
                        full["final_running"]["total_cost"]
                    )
                    - float(no_coop["final_running"]["total_cost"]),
                    "full_minus_no_cooperation_completed_customer_count": int(
                        full["full_day_execution"]["completed_customer_count"]
                    )
                    - int(no_coop["full_day_execution"]["completed_customer_count"]),
                    "full_minus_no_cooperation_completed_demand": float(
                        full["full_day_execution"]["completed_demand"]
                    )
                    - float(no_coop["full_day_execution"]["completed_demand"]),
                    "full_minus_no_participation_net_profit": full_profit - no_part_profit,
                    "full_minus_no_participation_system_cost": float(
                        full["final_running"]["total_cost"]
                    )
                    - float(no_part["final_running"]["total_cost"]),
                    "simple_insertion_minus_full_actual_total_emissions_kg": float(
                        simple["final_running"]["total_actual_emissions_kg"]
                    )
                    - float(full["final_running"]["total_actual_emissions_kg"]),
                    "full_day_participation_floor_met": all(
                        float(full_depot[depot]) + TOL >= float(no_coop_depot[depot])
                        for depot in ("D0", "D1")
                    ),
                }
            )
        else:
            pair.update(
                {
                    "full_minus_no_cooperation_net_profit": "",
                    "full_minus_no_cooperation_revenue": "",
                    "full_minus_no_cooperation_cost": "",
                    "full_minus_no_cooperation_completed_customer_count": "",
                    "full_minus_no_cooperation_completed_demand": "",
                    "full_minus_no_participation_net_profit": "",
                    "full_minus_no_participation_system_cost": "",
                    "simple_insertion_minus_full_actual_total_emissions_kg": "",
                    "full_day_participation_floor_met": "",
                }
            )
        pair_rows.append(pair)

    paired_summary: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        groups[(row["network"], row["condition"])].append(row)
    for (network, condition), rows in sorted(groups.items()):
        complete = [row for row in rows if row["all_four_arms_executable"]]
        paired_summary.append(
            {
                "network": network,
                "condition": condition,
                "expected_stream_count": len(rows),
                "paired_complete_stream_count": len(complete),
                "paired_incomplete_stream_count": len(rows) - len(complete),
                "full_day_participation_floor_met_count": sum(
                    bool(row["full_day_participation_floor_met"]) for row in complete
                ),
                "full_minus_no_cooperation_net_profit_mean": mean(
                    complete, "full_minus_no_cooperation_net_profit"
                ),
                "full_minus_no_cooperation_revenue_mean": mean(
                    complete, "full_minus_no_cooperation_revenue"
                ),
                "full_minus_no_cooperation_cost_mean": mean(
                    complete, "full_minus_no_cooperation_cost"
                ),
                "full_minus_no_cooperation_completed_customer_count_mean": mean(
                    complete, "full_minus_no_cooperation_completed_customer_count"
                ),
                "full_minus_no_cooperation_completed_demand_mean": mean(
                    complete, "full_minus_no_cooperation_completed_demand"
                ),
                "full_minus_no_participation_net_profit_mean": mean(
                    complete, "full_minus_no_participation_net_profit"
                ),
                "full_minus_no_participation_system_cost_mean": mean(
                    complete, "full_minus_no_participation_system_cost"
                ),
                "simple_insertion_minus_full_actual_total_emissions_kg_mean": mean(
                    complete, "simple_insertion_minus_full_actual_total_emissions_kg"
                ),
            }
        )

    replay_rows = read_csv(REPLAY / "raw_runs.csv")
    replay_summary = read_csv(REPLAY / "summary.csv")
    replay_failures = [
        index
        for index, row in enumerate(replay_rows, start=2)
        if row["route_hash_preserved"] != "True"
        or row["energy_hash_preserved"] != "True"
    ]
    full_payloads = [
        payload
        for key, payload in payloads.items()
        if key[3] == "full" and payload["execution_status"] == "PASS"
    ]
    stage_floor_failures = sum(
        float(stage["minimum_profit_margin"]) < -TOL
        for payload in full_payloads
        for stage in payload["rows"]
    )
    no_cooperation_cross_failures = sum(
        int(stage["cross_site_customer_count"]) != 0
        for key, payload in payloads.items()
        if key[3] == "no_cooperation" and payload["execution_status"] == "PASS"
        for stage in payload["rows"]
    )
    checks = {
        "formal_artifact_hashes_pass": not formal_hash_failures,
        "replay_artifact_hashes_pass": not replay_hash_failures,
        "formal_session_count_120": len(sessions) == 120,
        "full_mechanism_task_count_30": len(full_payloads) == 30,
        "full_stage_participation_floor_pass": stage_floor_failures == 0,
        "no_cooperation_cross_service_zero": no_cooperation_cross_failures == 0,
        "replay_row_count_840": len(replay_rows) == 30 * 28,
        "replay_route_and_energy_hashes_pass": not replay_failures,
    }
    if not all(checks.values()):
        raise RuntimeError(f"independent E7 audit failed: {checks}")

    write_csv(OUT / "raw_runs.csv", pair_rows)
    write_csv(OUT / "task_status.csv", task_rows)
    write_csv(OUT / "paired_summary.csv", paired_summary)
    write_csv(OUT / "replay_summary.csv", replay_summary)
    metadata = {
        "schema": "setp.e7.multinetwork_independent_audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_root": str(FORMAL.relative_to(ROOT)),
        "replay_root": str(REPLAY.relative_to(ROOT)),
        "formal_artifact_hash_count": formal_hash_count,
        "replay_artifact_hash_count": replay_hash_count,
        "formal_decision_sha256": sha256(FORMAL / "decision.json"),
        "replay_decision_sha256": sha256(REPLAY / "decision.json"),
        "audit_source_sha256": sha256(Path(__file__).resolve()),
    }
    write_json(OUT / "metadata.json", metadata)
    write_json(
        OUT / "decision.json",
        {
            "verdict": "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT",
            "checks": checks,
            "formal_hash_failures": formal_hash_failures,
            "replay_hash_failures": replay_hash_failures,
            "replay_row_failures": replay_failures,
            "stage_floor_failure_count": stage_floor_failures,
            "no_cooperation_cross_failure_count": no_cooperation_cross_failures,
        },
    )
    (OUT / "report.md").write_text(
        "# E7三网络正式矩阵与28日复算独立审计\n\n"
        "判决：`PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT`。"
        "审计重新读取已封存并列入哈希清单的120份最终会话载荷，只在四臂均可执行的网络—责任—订单流单元计算成对差；"
        "同时复核完整机制30份全日方案在28日电网日形成的840行零搜索充电重放。"
        "程序报告的受控不可执行臂仍留在任务状态表，不进入四臂成对均值。\n",
        encoding="utf-8",
    )
    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
