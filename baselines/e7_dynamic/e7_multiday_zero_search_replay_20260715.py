#!/usr/bin/env python3
"""Replay E7 full-day charging on 28 grid days without route search.

The formal dynamic run supplies the executed full-day solution and the final
effective node set.  This script reconstructs that instance once per formal
task and changes charging start times only.  Routes, vehicle identities,
served customers and charging energy are hash-locked across the immediate and
forecast-aware schedules.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import statistics
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e4_e5 import e4_multiday_forecast_probe_20260713 as e4
from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as full
from setp_solver.instance_loader import Node
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
    validate_multitrip_certificate,
)


FORMAL = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
OUT = ROOT / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715"
OPERATING_DAYS = e4.OPERATING_DAYS
TOL = 1e-9
SOURCE_FILES = (
    Path(__file__).resolve(),
    ROOT / "baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "baselines/e4_e5/e4_multiday_forecast_probe_20260713.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty evidence table: {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return statistics.fmean(materialized) if materialized else 0.0


def pct(delta: float, baseline: float) -> float:
    return 100.0 * delta / baseline if abs(baseline) > TOL else 0.0


def completed_tasks() -> tuple[
    list[tuple[Path, dict[str, Any]]], list[dict[str, Any]]
]:
    paths = sorted(
        path for path in (FORMAL / ".tasks").glob("*.json") if not path.name.startswith("._")
    )
    if len(paths) != 120:
        raise RuntimeError(f"expected 120 formal E7 checkpoints, found {len(paths)}")
    rows: list[tuple[Path, dict[str, Any]]] = []
    failures: list[dict[str, Any]] = []
    for path in paths:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        if wrapper.get("status") != "completed":
            raise RuntimeError(f"incomplete formal task: {path.name}")
        payload = wrapper["payload"]
        if payload.get("execution_status") == "HALT_NO_EXECUTABLE_CONTINUATION":
            failures.append(
                {
                    "task_id": wrapper["task"]["task_id"],
                    "network": payload["network"],
                    "condition": payload["responsibility_condition"],
                    "stream": payload["stream_seed"],
                    "arm": payload["arm"],
                    "failed_stage": payload["failed_stage"],
                    "failure_error": payload["failure_error"],
                }
            )
            continue
        if payload.get("execution_status") != "PASS":
            raise RuntimeError(f"unknown formal task status: {path.name}")
        if "full_day_solution" not in payload or "full_day_instance_nodes" not in payload:
            raise RuntimeError(f"formal task lacks zero-search replay payload: {path.name}")
        if canonical_sha256(payload) != wrapper["payload_sha256"]:
            raise RuntimeError(f"formal task payload hash mismatch: {path.name}")
        rows.append((path, wrapper))
    return rows, failures


def charging_kwh(solution: Any) -> float:
    return sum(float(action.energy_kwh) for action in solution.charging_actions)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for required in ("metadata.json", "decision.json", "artifact_hashes.json"):
        if not (FORMAL / required).is_file():
            raise RuntimeError(f"formal E7 evidence is not sealed: missing {required}")

    carbon_rows = e4.load_national_rows()
    profiles_by_day = {
        day.isoformat(): e4.profiles_for_operating_day(carbon_rows, day)
        for day in OPERATING_DAYS
    }
    raw_rows: list[dict[str, Any]] = []
    task_inventory: list[dict[str, Any]] = []

    replay_tasks, formal_failures = completed_tasks()
    for task_path, wrapper in replay_tasks:
        task = wrapper["task"]
        payload = wrapper["payload"]
        network = str(task["network"])
        condition = str(task["condition"])
        stream = int(task["stream"])
        arm = str(task["arm"])
        sources, _ = full._sources_for_day(condition, network)
        _, owners, _, _ = full._stream_for_condition(stream, condition, network)
        nodes = [Node(**row) for row in payload["full_day_instance_nodes"]]
        instance = full.base.gate._rebuild_instance_matrix(sources["bundle"].instance, nodes)
        source_solution = full.base.solution_from_dict(payload["full_day_solution"])
        prepared, certificate = prepare_multitrip_solution(
            source_solution,
            instance,
            sources["prices"],
        )
        validate_multitrip_certificate(certificate, list(prepared.routes), sources["prices"])
        source_route_hash = full.route_hash(source_solution)
        source_energy_hash = full.energy_hash(source_solution)
        if full.route_hash(prepared) != source_route_hash:
            raise RuntimeError(f"preparation changed routes: {task['task_id']}")
        if full.energy_hash(prepared) != source_energy_hash:
            raise RuntimeError(f"preparation changed charging energy: {task['task_id']}")
        ledger = full._profit_closure(prepared, instance, sources, owners)
        direct = float(ledger["direct_emissions_kg"])
        demand = float(payload["full_day_execution"]["completed_demand"])

        for day in OPERATING_DAYS:
            day_key = day.isoformat()
            profiles = profiles_by_day[day_key]
            immediate = reschedule_between_trip_charging(
                prepared,
                certificate,
                instance,
                profiles[0],
                strategy="naive",
                carbon_profiles_by_day_offset=profiles,
                intensity_field="forecast_gco2_per_kwh",
            )
            aware = reschedule_between_trip_charging(
                prepared,
                certificate,
                instance,
                profiles[0],
                strategy="aware",
                carbon_profiles_by_day_offset=profiles,
                intensity_field="forecast_gco2_per_kwh",
            )
            comparison = full._timing_comparison(immediate, aware, instance, profiles)
            for variant in (immediate, aware):
                if full.route_hash(variant) != source_route_hash:
                    raise RuntimeError(f"zero-search replay changed routes: {task['task_id']}")
                if full.energy_hash(variant) != source_energy_hash:
                    raise RuntimeError(f"zero-search replay changed energy: {task['task_id']}")
            immediate_actual = float(comparison["immediate_actual_charging_emissions_kg"])
            aware_actual = float(comparison["aware_actual_charging_emissions_kg"])
            saving = immediate_actual - aware_actual
            raw_rows.append(
                {
                    "network": network,
                    "condition": condition,
                    "stream": stream,
                    "arm": arm,
                    "operating_day": day_key,
                    "route_sha256": source_route_hash,
                    "energy_sha256": source_energy_hash,
                    "charging_kwh": charging_kwh(prepared),
                    "completed_demand": demand,
                    "direct_emissions_kg": direct,
                    "immediate_actual_charging_emissions_kg": immediate_actual,
                    "aware_actual_charging_emissions_kg": aware_actual,
                    "actual_charging_saving_kg": saving,
                    "charging_reduction_pct": pct(saving, immediate_actual),
                    "total_operational_reduction_pct": pct(saving, direct + immediate_actual),
                    "timing_shifted_action_count": int(comparison["timing_shifted_action_count"]),
                    "route_hash_preserved": True,
                    "energy_hash_preserved": True,
                }
            )
        task_inventory.append(
            {
                "task_id": task["task_id"],
                "checkpoint_path": str(task_path.relative_to(ROOT)),
                "checkpoint_sha256": sha256(task_path),
                "route_sha256": source_route_hash,
                "energy_sha256": source_energy_hash,
                "node_count": len(nodes),
            }
        )

    expected_rows = len(replay_tasks) * len(OPERATING_DAYS)
    if len(raw_rows) != expected_rows:
        raise RuntimeError(f"expected {expected_rows} paired day rows, found {len(raw_rows)}")
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        groups[(row["network"], row["condition"], row["arm"])].append(row)
    summary_rows: list[dict[str, Any]] = []
    for (network, condition, arm), rows in sorted(groups.items()):
        savings = [float(row["actual_charging_saving_kg"]) for row in rows]
        immediate = sum(float(row["immediate_actual_charging_emissions_kg"]) for row in rows)
        direct_total = sum(float(row["direct_emissions_kg"]) for row in rows)
        summary_rows.append(
            {
                "network": network,
                "condition": condition,
                "arm": arm,
                "stream_day_count": len(rows),
                "pooled_charging_reduction_pct": pct(sum(savings), immediate),
                "pooled_total_operational_reduction_pct": pct(
                    sum(savings), direct_total + immediate
                ),
                "mean_day_task_charging_reduction_pct": mean(
                    float(row["charging_reduction_pct"]) for row in rows
                ),
                "improved": sum(value > TOL for value in savings),
                "worsened": sum(value < -TOL for value in savings),
                "tied": sum(abs(value) <= TOL for value in savings),
            }
        )

    write_csv(OUT / "raw_runs.csv", raw_rows)
    write_csv(OUT / "summary.csv", summary_rows)
    write_json(OUT / "task_inventory.json", task_inventory)
    metadata = {
        "schema": "setp.e7.multiday_zero_search_replay.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_evidence_root": str(FORMAL.relative_to(ROOT)),
        "formal_metadata_sha256": sha256(FORMAL / "metadata.json"),
        "formal_decision_sha256": sha256(FORMAL / "decision.json"),
        "formal_artifact_hashes_sha256": sha256(FORMAL / "artifact_hashes.json"),
        "operating_days": [day.isoformat() for day in OPERATING_DAYS],
        "task_count": 120,
        "replayed_full_day_task_count": len(replay_tasks),
        "excluded_no_continuation_task_count": len(formal_failures),
        "paired_day_row_count": len(raw_rows),
        "route_search_evaluations": 0,
        "changed_dimension": "charging_start_time_only",
        "source_files": {
            str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES
        },
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "status": "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY",
        "task_count": 120,
        "replayed_full_day_task_count": len(replay_tasks),
        "excluded_no_continuation_task_count": len(formal_failures),
        "excluded_formal_tasks": formal_failures,
        "operating_day_count": len(OPERATING_DAYS),
        "paired_day_row_count": len(raw_rows),
        "route_hash_failures": sum(not row["route_hash_preserved"] for row in raw_rows),
        "energy_hash_failures": sum(not row["energy_hash_preserved"] for row in raw_rows),
        "route_search_evaluations": 0,
    }
    write_json(OUT / "decision.json", decision)
    report = (
        "# E7动态排班的28日零搜索充电重排\n\n"
        "状态：`PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY`。对三张网络、两类客户责任、"
        f"五条冻结序列和四个机制臂中完成全日执行的{len(replay_tasks)}份方案，逐一重放28个电网日，共形成"
        f" {len(raw_rows)} 组配对结果。\n\n"
        "后处理不调用路径搜索，只在同一多趟充电可行窗口内比较有空即充与按预测碳强度择时。"
        "每组的路径哈希和充电电量哈希均保持不变；减排按实际碳强度结算。\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
