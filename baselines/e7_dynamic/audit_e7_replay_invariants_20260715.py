#!/usr/bin/env python3
"""Independently verify hard invariants of the sealed E7 charging replay.

This audit does not search for routes.  It reconstructs the two charging
schedules from the sealed full-day sessions, verifies the frozen rolling-state
windows and shared charger capacity, and ties every recomputed task/day row to
the sealed 28-day replay package.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import os
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT, ROOT / "solver/src", ROOT / "models/src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e7_dynamic import e7_multiday_zero_search_replay_20260715 as replay
from baselines.e7_dynamic import e7_replay_invariants_20260715 as invariants


FORMAL = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
REPLAY = ROOT / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715"
OUT = ROOT / "baselines/e7_dynamic/e7_replay_invariants_audit_20260715"
TOL = 1e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty invariant table: {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_manifest(root: Path) -> list[str]:
    manifest = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))
    observed = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and ".tasks" not in path.parts
    }
    failures = [f"unlisted:{name}" for name in sorted(observed - set(manifest))]
    failures.extend(f"missing:{name}" for name in sorted(set(manifest) - observed))
    for relative, expected in manifest.items():
        path = root / relative
        if path.is_file() and sha256(path) != expected:
            failures.append(f"hash:{relative}")
    return failures


def replay_key(row: dict[str, Any]) -> tuple[str, str, int, str, str]:
    return (
        str(row["network"]),
        str(row["condition"]),
        int(row["stream"]),
        str(row["arm"]),
        str(row["operating_day"]),
    )


def close(left: float, right: float) -> bool:
    return abs(left - right) <= TOL * max(1.0, abs(left), abs(right))


def build_audit_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    formal_manifest_failures = verify_manifest(FORMAL)
    replay_manifest_failures = verify_manifest(REPLAY)
    if formal_manifest_failures or replay_manifest_failures:
        raise RuntimeError(
            "sealed E7 input manifest failed: "
            f"formal={formal_manifest_failures}, replay={replay_manifest_failures}"
        )

    sealed_rows = read_csv(REPLAY / "raw_runs.csv")
    sealed_by_key: dict[tuple[str, str, int, str, str], dict[str, str]] = {}
    duplicate_keys: list[tuple[str, str, int, str, str]] = []
    for row in sealed_rows:
        key = replay_key(row)
        if key in sealed_by_key:
            duplicate_keys.append(key)
        sealed_by_key[key] = row
    if duplicate_keys:
        raise RuntimeError(f"sealed replay has duplicate row keys: {duplicate_keys[:5]}")

    carbon_rows = replay.e4.load_national_rows()
    profiles_by_day = {
        day.isoformat(): replay.e4.profiles_for_operating_day(carbon_rows, day)
        for day in replay.OPERATING_DAYS
    }
    task_rows: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []
    computed_keys: set[tuple[str, str, int, str, str]] = set()

    replay_tasks, _formal_failures = replay.completed_tasks()
    for task_id, payload in replay_tasks:
        network = str(payload["network"])
        condition = str(payload["responsibility_condition"])
        stream = int(payload["stream_seed"])
        arm = str(payload["arm"])
        sources, _ = replay.full._sources_for_day(condition, network)
        nodes = [replay.Node(**row) for row in payload["full_day_instance_nodes"]]
        instance = replay._rebuild_instance_matrix(sources["bundle"].instance, nodes)
        source_solution = replay.full.base.solution_from_dict(payload["full_day_solution"])
        source_route_hash = replay.full.route_hash(source_solution)
        source_energy_hash = replay.full.energy_hash(source_solution)
        witnesses = list(payload["full_day_charging_windows"])
        trigger_seconds = [float(row["trigger_second"]) for row in payload["rows"]]
        window_failures = invariants.charging_window_boundary_violations(
            witnesses, trigger_seconds
        )
        task_rows.append(
            {
                "task_id": task_id,
                "network": network,
                "condition": condition,
                "stream": stream,
                "arm": arm,
                "trigger_count": len(trigger_seconds),
                "charging_window_count": len(witnesses),
                "window_violation_count": len(window_failures),
                "window_violations": " | ".join(window_failures),
            }
        )

        for day in replay.OPERATING_DAYS:
            day_key = day.isoformat()
            profiles = profiles_by_day[day_key]
            immediate_actions = []
            aware_actions = []
            for witness in witnesses:
                earliest = float(witness["earliest_start_second"])
                latest = float(witness["latest_start_second"])
                duration = float(witness["occupancy_minutes"]) * 60.0
                energy = float(witness["energy_kwh"])
                day_offset = int(witness["charge_day_offset"])
                aware_start = replay._lowest_carbon_gap_start(
                    earliest,
                    latest,
                    duration,
                    energy,
                    instance,
                    profiles[day_offset],
                    intensity_field="forecast_gco2_per_kwh",
                )
                immediate_actions.append(replay.action_from_witness(witness, earliest))
                aware_actions.append(replay.action_from_witness(witness, aware_start))
            immediate = replace(source_solution, charging_actions=immediate_actions)
            aware = replace(source_solution, charging_actions=aware_actions)
            key = (network, condition, stream, arm, day_key)
            computed_keys.add(key)
            sealed = sealed_by_key.get(key)
            if sealed is None:
                raise RuntimeError(f"sealed replay row is missing: {key}")

            immediate_actual = replay.full._charging_emissions_kg(
                immediate, instance, profiles, "actual_gco2_per_kwh"
            )
            aware_actual = replay.full._charging_emissions_kg(
                aware, instance, profiles, "actual_gco2_per_kwh"
            )
            immediate_capacity = invariants.station_capacity_violation_count(
                immediate, instance
            )
            aware_capacity = invariants.station_capacity_violation_count(aware, instance)
            route_hash_pass = (
                replay.full.route_hash(immediate)
                == replay.full.route_hash(aware)
                == source_route_hash
                == sealed["route_sha256"]
            )
            energy_hash_pass = (
                replay.full.energy_hash(immediate)
                == replay.full.energy_hash(aware)
                == source_energy_hash
                == sealed["energy_sha256"]
            )
            immediate_residual = immediate_actual - float(
                sealed["immediate_actual_charging_emissions_kg"]
            )
            aware_residual = aware_actual - float(
                sealed["aware_actual_charging_emissions_kg"]
            )
            day_rows.append(
                {
                    "network": network,
                    "condition": condition,
                    "stream": stream,
                    "arm": arm,
                    "operating_day": day_key,
                    "window_violation_count": len(window_failures),
                    "immediate_station_capacity_violation_count": immediate_capacity,
                    "aware_station_capacity_violation_count": aware_capacity,
                    "route_hash_preserved": route_hash_pass,
                    "energy_hash_preserved": energy_hash_pass,
                    "immediate_emissions_residual_kg": immediate_residual,
                    "aware_emissions_residual_kg": aware_residual,
                    "emissions_recalculation_pass": close(immediate_actual, float(sealed["immediate_actual_charging_emissions_kg"]))
                    and close(aware_actual, float(sealed["aware_actual_charging_emissions_kg"])),
                }
            )

    if computed_keys != set(sealed_by_key):
        missing = sorted(set(sealed_by_key) - computed_keys)
        extra = sorted(computed_keys - set(sealed_by_key))
        raise RuntimeError(f"replay row identity differs: unverified={missing[:5]}, extra={extra[:5]}")

    counts = {
        "formal_manifest_failure_count": len(formal_manifest_failures),
        "replay_manifest_failure_count": len(replay_manifest_failures),
        "full_task_count": len(task_rows),
        "task_day_row_count": len(day_rows),
        "window_violation_count": sum(int(row["window_violation_count"]) for row in task_rows),
        "station_capacity_violation_count": sum(
            int(row["immediate_station_capacity_violation_count"])
            + int(row["aware_station_capacity_violation_count"])
            for row in day_rows
        ),
        "route_hash_failure_count": sum(not row["route_hash_preserved"] for row in day_rows),
        "energy_hash_failure_count": sum(not row["energy_hash_preserved"] for row in day_rows),
        "emissions_recalculation_failure_count": sum(
            not row["emissions_recalculation_pass"] for row in day_rows
        ),
        "route_search_evaluations": 0,
    }
    return task_rows, day_rows, counts


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite existing invariant evidence: {OUT}")
    if OUT.exists():
        OUT.rmdir()
    temporary = OUT.with_name(f".{OUT.name}.tmp-{os.getpid()}")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    try:
        task_rows, day_rows, counts = build_audit_rows()
        checks = {
            "full_task_count_30": counts["full_task_count"] == 30,
            "task_day_row_count_840": counts["task_day_row_count"] == 840,
            "charging_windows_respect_rolling_boundaries": counts["window_violation_count"] == 0,
            "shared_charger_capacity_pass": counts["station_capacity_violation_count"] == 0,
            "route_hashes_preserved": counts["route_hash_failure_count"] == 0,
            "energy_hashes_preserved": counts["energy_hash_failure_count"] == 0,
            "sealed_emissions_recalculate": counts["emissions_recalculation_failure_count"] == 0,
            "route_search_evaluations_zero": counts["route_search_evaluations"] == 0,
        }
        if not all(checks.values()):
            raise RuntimeError(f"E7 replay invariant audit failed: {checks}, counts={counts}")

        write_csv(temporary / "raw_runs.csv", day_rows)
        write_csv(temporary / "task_windows.csv", task_rows)
        write_json(
            temporary / "metadata.json",
            {
                "schema": "setp.e7.replay_invariants_audit.v1",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "formal_root": str(FORMAL.relative_to(ROOT)),
                "replay_root": str(REPLAY.relative_to(ROOT)),
                "formal_artifact_hashes_sha256": sha256(FORMAL / "artifact_hashes.json"),
                "replay_artifact_hashes_sha256": sha256(REPLAY / "artifact_hashes.json"),
                "source_files": {
                    str(path.relative_to(ROOT)): sha256(path)
                    for path in (
                        Path(__file__).resolve(),
                        Path(replay.__file__).resolve(),
                        Path(invariants.__file__).resolve(),
                        ROOT / "solver/src/setp_solver/check.py",
                    )
                },
            },
        )
        write_json(
            temporary / "decision.json",
            {
                "status": "PASS_E7_REPLAY_INVARIANTS_AUDIT",
                "checks": checks,
                **counts,
            },
        )
        (temporary / "report.md").write_text(
            "# E7 28日电网日重放不变量独立审计\n\n"
            "状态：`PASS_E7_REPLAY_INVARIANTS_AUDIT`。审计对30份完整机制全日方案与28个电网日的840个配对逐行复算，"
            "不调用路径搜索；相邻滚动触发充电窗口、共享充电桩容量、路线与电量哈希以及已封存排放值均通过。\n",
            encoding="utf-8",
        )
        hashes = {
            str(path.relative_to(temporary)): sha256(path)
            for path in sorted(temporary.rglob("*"))
            if path.is_file() and path.name != "artifact_hashes.json"
        }
        write_json(temporary / "artifact_hashes.json", hashes)
        temporary.replace(OUT)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
