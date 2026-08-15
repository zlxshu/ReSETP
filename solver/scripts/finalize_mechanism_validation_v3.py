#!/usr/bin/env python3
"""Assemble the completed mechanism-v3 evidence package without new search."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).parents[2]
OUTPUT = ROOT / "solver/reports/mechanism_validation_v3_20260811"
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _source_hashes(paths: list[Path]) -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in paths
    }


def main() -> int:
    report = OUTPUT / "report.md"
    if report.read_text(encoding="utf-8").splitlines()[0] != "MECHANISM_V3_DONE":
        raise ValueError("final report must carry MECHANISM_V3_DONE before hashing")

    root_raw = OUTPUT / "raw_runs.csv"
    step_c_rows = [
        row for row in _read_csv(root_raw)
        if str(row.get("record_type", "")).startswith("step_c_")
    ]
    rows: list[dict[str, Any]] = []
    for row in step_c_rows:
        row["source_artifact"] = (
            "solver/reports/mechanism_validation_v3_20260811/raw_runs.csv"
        )
        rows.append(row)

    preflight_path = OUTPUT / "preflight_seed11/raw_runs.csv"
    for row in _read_csv(preflight_path):
        row.update(
            {
                "record_type": "step_b_preflight_search",
                "evidence_label": "FACT",
                "source_artifact": str(preflight_path.relative_to(ROOT)),
                "scientific_run_started": True,
            }
        )
        rows.append(row)

    replay_path = OUTPUT / "preflight_truth_replay.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay_row = dict(replay)
    replay_row.update(
        {
            "record_type": "step_b_preflight_truth_replay",
            "evidence_label": "FACT",
            "source_artifact": str(replay_path.relative_to(ROOT)),
            "scientific_run_started": False,
            "hard_violations_json": json.dumps(
                replay_row.pop("hard_violations"),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "protected_file_hashes_json": json.dumps(
                replay_row.pop("protected_file_hashes"),
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
    )
    rows.append(replay_row)

    factorial_path = OUTPUT / "factorial_2seed_30s/raw_runs.csv"
    for row in _read_csv(factorial_path):
        row.update(
            {
                "record_type": "step_direction_factorial",
                "evidence_label": "FACT",
                "source_artifact": str(factorial_path.relative_to(ROOT)),
                "scientific_run_started": True,
            }
        )
        rows.append(row)

    preferred = ["record_type", "evidence_label", "source_artifact"]
    fields = preferred + sorted(
        set().union(*(row.keys() for row in rows)).difference(preferred)
    )
    with root_raw.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    factorial_rows = _read_csv(factorial_path)
    actual_walls = [float(row["total_algorithm_wall_seconds"]) for row in factorial_rows]
    sources = [
        OUTPUT / "charge_strategy_by_vehicle.csv",
        OUTPUT / "vehicle_threshold_by_vehicle.csv",
        preflight_path,
        replay_path,
        factorial_path,
        OUTPUT / "factorial_2seed_30s/report.md",
        OUTPUT / "factorial_2seed_30s/metadata.json",
        OUTPUT / "factorial_2seed_30s/artifact_hashes.json",
    ]
    metadata = {
        "schema": "resetp.mechanism-validation-v3.complete.v1",
        "status": "MECHANISM_V3_DONE",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "instance_id": "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS",
        "formal_search_allowed": True,
        "fairness_enabled": False,
        "pi0_used_in_objective_or_constraints": False,
        "ev_daily_fixed_premium_cny": 50.0,
        "route_volume_capacity_m3": 7.2,
        "am_forced_return_clock": "11:00",
        "preflight": {
            "seed": 11,
            "declared_wall_clock_seconds": 30.0,
            "completed_generations": 324,
            "full_evaluation_feasible": True,
            "customers_served": 50,
            "customers_total": 50,
            "demand_served": 12223.0,
            "demand_total": 12223.0,
        },
        "direction_factorial": {
            "seeds": [1, 2],
            "components": ["route_local_search", "vehicle_type_exchange"],
            "arm_count": 4,
            "declared_wall_clock_seconds_per_arm": 30.0,
            "actual_algorithm_wall_seconds_min": min(actual_walls),
            "actual_algorithm_wall_seconds_max": max(actual_walls),
            "serial_execution": True,
            "result_rows": len(factorial_rows),
            "failed_rows": sum(
                row["run_status"] == "FAILED" for row in factorial_rows
            ),
            "post_write_cleanup_terminated": True,
            "post_write_wrapper_exit_code": 143,
            "pre_termination_artifact_hashes_verified": True,
            "post_termination_artifact_hashes_verified": True,
        },
        "final_relevant_tests": "41 passed in 4.56s",
        "protected_file_hashes": {
            path: _sha256(ROOT / path) for path in PROTECTED
        },
        "source_artifact_hashes": _source_hashes(sources),
    }
    _write_json(OUTPUT / "metadata.json", metadata)

    decision = {
        "status": "MECHANISM_V3_DONE",
        "search_direction_stopped": True,
        "additional_seed_or_budget_run_started": False,
        "component_type_exchange_not_constant_zero": True,
        "component_synergy_preregistered_expectation": "NOT_MET_WEAKER_THAN_OLD_INSTANCE",
        "old_instance_6p5_to_8p6_percent_paper_eligibility": "REJECTED_NOT_GENERALIZED",
        "mixed_fleet_endpoint": "MIXED_FOUND_IN_SHORT_BEST_SOLUTIONS",
        "monotone_low_mileage_cv_high_mileage_ev_pattern": "NOT_SUPPORTED",
        "pure_endpoint_threshold_scan_required": False,
        "charging_main_account_outcome": (
            "COST_PLUS_CARBON_LOWERS_MONETARY_ACCOUNT_BUT_RAISES_CHARGING_EMISSIONS"
        ),
        "formal_confirmation_round_authorized": False,
    }
    _write_json(OUTPUT / "decision.json", decision)

    hashes: dict[str, str] = {}
    for path in sorted(OUTPUT.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "artifact_hashes.json" or path.name.startswith("._"):
            continue
        if path.suffix in {".log", ".rc"}:
            continue
        hashes[str(path.relative_to(ROOT))] = _sha256(path)
    _write_json(OUTPUT / "artifact_hashes.json", hashes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
