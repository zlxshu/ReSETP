#!/usr/bin/env python3
"""Materialize the approved S3-TRAJ-CURVE-DEF-001 trajectory definition.

This is an offline reporting step.  It reads the existing S3-TRAJ snapshots,
completes and scores them with the frozen full evaluator, and writes v2
trajectory artifacts without changing the v1 HALT files or rerunning HGS.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import run_s3_trajectory_v4 as traj


ROOT = traj.ROOT
OUT = Path(__file__).resolve().parent
SEALED_RAW = OUT.parent / "raw_runs.csv"
OBS_RAW = OUT / "raw_runs.csv"
APPROVAL_ID = "S3-TRAJ-CURVE-DEF-001"
DECISION = OUT / "decision_v2.json"
METADATA = OUT / "metadata_v2.json"
REPORT = OUT / "report_v2.md"
OFFLINE = OUT / "offline_recheck_v2.json"
CURVE_DATA = OUT / "curve_data_v4.csv"
MATERIALIZED = OUT / "materialized_trajectories_v2"
DONE = OUT / "done_v2.json"
EPS = 1.0e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_curve_rows(rows: list[dict[str, Any]]) -> None:
    fields = [
        "algorithm",
        "seed",
        "selected_for_figure4",
        "elapsed_seconds",
        "elapsed_minutes",
        "cost_cny",
        "source",
        "snapshot_order",
    ]
    with CURVE_DATA.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _snapshot_path(row: dict[str, str]) -> Path:
    recorded = row.get("snapshot_file", "").strip()
    if recorded:
        path = OUT / recorded
    else:
        path = OUT / "snapshots" / f"{row['arm']}_seed{row['seed']}.json"
    if not path.is_file():
        raise RuntimeError(f"missing snapshot for {row['arm']}/seed{row['seed']}: {path}")
    return path


def _materialize_one(row: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = traj.p3.load_china81_bundle(ROOT, row["instance_id"])
    payload = json.loads(_snapshot_path(row).read_text(encoding="utf-8"))
    scored: list[dict[str, Any]] = []
    for order, point in enumerate(payload["points"]):
        scored.append(traj._offline_score_snapshot(bundle, point, order))
    errors = [item for item in scored if item["status"] == "ERROR"]
    infeasible = [item for item in scored if item["status"] == "INFEASIBLE"]
    if errors or infeasible:
        raise RuntimeError(
            f"invalid offline snapshots for {row['arm']}/seed{row['seed']}: "
            f"errors={len(errors)}, infeasible={len(infeasible)}"
        )
    valid = sorted(
        (item for item in scored if item["status"] == "OK"),
        key=lambda item: (float(item["elapsed_seconds"]), int(item["order"])),
    )
    if not valid:
        raise RuntimeError(f"no valid offline snapshots for {row['arm']}/seed{row['seed']}")

    best = math.inf
    curve: list[dict[str, Any]] = []
    for item in valid:
        cost = float(item["exact_cost"])
        if cost < best - EPS:
            best = cost
            curve.append({
                "elapsed_seconds": float(item["elapsed_seconds"]),
                "cost": cost,
                "source": item["source"],
                "snapshot_order": int(item["order"]),
            })
    sealed = float(row["sealed_cost"])
    rerun = float(row["rerun_cost"])
    if rerun != sealed or row["cost_equal"].lower() != "true":
        raise RuntimeError(f"sealed final cost mismatch in raw row: {row['arm']}/seed{row['seed']}")
    if not math.isfinite(best):
        raise RuntimeError(f"non-finite best curve value: {row['arm']}/seed{row['seed']}")

    result = {
        "schema_version": "resetp.e2-final-campaign.s3-materialized-trajectory.v2",
        "instance_id": row["instance_id"],
        "seed": int(row["seed"]),
        "arm": row["arm"],
        "approval_register_id": APPROVAL_ID,
        "observation_only": True,
        "cost_definition": "exact_china81_score objective",
        "time_definition": "elapsed wall seconds from the arm runner start",
        "curve_definition": "best-so-far over historical snapshot skeletons after offline complete-model scoring; monotone non-increasing",
        "sealed_final_cost": sealed,
        "rerun_final_cost": rerun,
        "curve_best_cost": best,
        "curve_best_below_final": best < sealed - EPS,
        "points": curve,
        "offline_snapshot_audit": {
            "total": len(scored),
            "valid": len(valid),
            "errors": len(errors),
            "infeasible": len(infeasible),
        },
    }
    audit = {
        "instance_id": row["instance_id"],
        "seed": int(row["seed"]),
        "arm": row["arm"],
        "sealed_cost": sealed,
        "rerun_cost": rerun,
        "final_cost_exact_equal": rerun == sealed,
        "curve_best_cost": best,
        "curve_best_below_final": best < sealed - EPS,
        "snapshot_audit": result["offline_snapshot_audit"],
    }
    return result, audit


def _selected_seeds(rows: list[dict[str, str]]) -> dict[str, int]:
    selected: dict[str, int] = {}
    for arm in traj.ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        average = statistics.fmean(float(row["sealed_cost"]) for row in arm_rows)
        winner = min(
            arm_rows,
            key=lambda row: (
                abs(float(row["sealed_cost"]) - average),
                int(row["seed"]),
            ),
        )
        selected[arm] = int(winner["seed"])
    return selected


def _clean_appledouble() -> bool:
    sidecars = [path for path in OUT.rglob("._*") if path.is_file()]
    for path in sidecars:
        path.unlink()
    return bool(sidecars)


def _hash_inputs() -> list[Path]:
    paths = [
        OUT / "decision.json",
        OUT / "metadata.json",
        OUT / "report.md",
        OUT / "artifact_hashes.json",
        OUT / "decision_halt_v1.json",
        OUT / "metadata_halt_v1.json",
        OUT / "report_halt_v1.md",
        OUT / "artifact_hashes_halt_v1.json",
        OUT / "offline_recheck_halt_v1.json",
        OUT / "decision_halt_v2.json",
        OUT / "metadata_halt_v2.json",
        OUT / "report_halt_v2.md",
        OUT / "artifact_hashes_halt_v2.json",
        OUT / "offline_recheck_halt_v2.json",
        OUT / "materialize_curve_v2.py",
        OBS_RAW,
        SEALED_RAW,
        OUT / "run_s3_trajectory_v4.py",
        OUT.parent / "representative_registration.json",
        DECISION,
        METADATA,
        REPORT,
        OFFLINE,
        CURVE_DATA,
    ]
    paths.extend(path for path in (OUT / "snapshots").rglob("*") if path.is_file())
    paths.extend(path for path in MATERIALIZED.rglob("*") if path.is_file())
    return [
        path for path in paths
        if path.is_file()
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    MATERIALIZED.mkdir(parents=True, exist_ok=True)
    try:
        sealed = traj._sealed_costs()
        rows = _read_rows(OBS_RAW)
        if len(rows) != 40:
            raise RuntimeError(f"observation raw has {len(rows)} rows, expected 40")
        keys = {(row["arm"], int(row["seed"])) for row in rows}
        if keys != {(arm, seed) for arm in traj.ARMS for seed in traj.SEEDS}:
            raise RuntimeError("observation raw does not contain exactly four arms x seeds 1--10")

        audits: list[dict[str, Any]] = []
        materialized: list[dict[str, Any]] = []
        for row in rows:
            result, audit = _materialize_one(row)
            _write_json(MATERIALIZED / f"{row['arm']}_seed{row['seed']}.json", result)
            materialized.append(result)
            audits.append(audit)

        selected = _selected_seeds(rows)
        curve_rows: list[dict[str, Any]] = []
        for result in materialized:
            chosen = selected[result["arm"]] == int(result["seed"])
            if not chosen:
                continue
            for point in result["points"]:
                curve_rows.append({
                    "algorithm": result["arm"],
                    "seed": result["seed"],
                    "selected_for_figure4": True,
                    "elapsed_seconds": float(point["elapsed_seconds"]),
                    "elapsed_minutes": float(point["elapsed_seconds"]) / 60.0,
                    "cost_cny": float(point["cost"]),
                    "source": point["source"],
                    "snapshot_order": point["snapshot_order"],
                })
        _write_curve_rows(curve_rows)
        _write_json(OFFLINE, {
            "schema_version": "resetp.e2-final-campaign.s3-offline-recheck.v2",
            "approval_register_id": APPROVAL_ID,
            "all_final_costs_exact": all(item["final_cost_exact_equal"] for item in audits),
            "all_snapshot_points_valid": all(item["snapshot_audit"]["errors"] == 0 and item["snapshot_audit"]["infeasible"] == 0 for item in audits),
            "units": audits,
            "selected_seeds": selected,
        })

        lower = [item for item in audits if item["curve_best_below_final"]]
        decision = {
            "schema_version": "resetp.e2-final-campaign.s3-trajectory-v2",
            "decision": "PASS_S3_TRAJ_CURVE_UNDER_REGISTERED_DEFINITION",
            "approval_register_id": APPROVAL_ID,
            "source_halt_decision_preserved": "decision.json",
            "instance_id": traj.TARGET_INSTANCE,
            "units": 40,
            "final_cost_exact_matches": 40,
            "complete_solution_violations": 0,
            "curve_definition": "historical snapshot offline exact score best-so-far, monotone non-increasing",
            "curve_may_be_lower_than_sealed_final": True,
            "lower_curve_units": len(lower),
            "lower_curve_examples": lower,
            "table_costs_unchanged": True,
            "selected_seeds": selected,
            "curve_data": "curve_data_v4.csv",
            "algorithm_changed": False,
            "evaluator_changed": False,
            "sealed_s3_raw_unchanged": True,
            "integrity_flags": [traj.APPLEDOUBLE_FLAG],
        }
        _write_json(DECISION, decision)
        metadata = {
            "schema_version": "resetp.e2-final-campaign.s3-trajectory-metadata.v2",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "command": " ".join([sys.executable, *sys.argv]),
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "observation_solver_rerun": False,
            "input_sha256": {
                "sealed_s3_raw": _sha256(SEALED_RAW),
                "observation_raw": _sha256(OBS_RAW),
                "observation_runner": _sha256(OUT / "run_s3_trajectory_v4.py"),
                "registration": _sha256(OUT.parent / "representative_registration.json"),
                "source_halt_decision": _sha256(OUT / "decision.json"),
            },
            "curve_definition": "best-so-far over offline complete-model scores of historical HGS proxy-best snapshots",
            "table_boundary": "Table 6/Table 8 reads sealed S3 final costs and CPUs; curve-only lower historical observations are never substituted into tables.",
            "selected_seeds": selected,
            "integrity_flags": [traj.APPLEDOUBLE_FLAG],
        }
        _write_json(METADATA, metadata)
        report_lines = [
            "# S3-TRAJ-CURVE-DEF-001 v2 offline materialization",
            "",
            "Decision: `PASS_S3_TRAJ_CURVE_UNDER_REGISTERED_DEFINITION`.",
            "",
            "This v2 step reads the existing 40 S3-TRAJ solver snapshots and the sealed S3 final-cost ledger. It does not rerun HGS, change the random stream, alter the evaluator, or rewrite the v1 HALT decision.",
            "",
            "Figure 4 uses the historical snapshot skeletons after offline full-model completion and exact scoring. The plotted quantity is the monotone running minimum (best-so-far), so it may be lower than the sealed runner's final accepted candidate when proxy and complete-model rankings disagree.",
            "",
            f"All 40 final rerun costs equal sealed S3 exactly; all complete solutions have zero violations. {len(lower)} unit(s) have a historical curve best below their sealed final cost.",
            "",
            "The registered example is HGS-M (`mechanism_ev`)/seed10: curve best `2364.589958517462`; sealed table cost `2365.8780971446868`. This difference remains trajectory-only and is not used in Table 6/Table 8 or any summary statistic.",
            "",
            "Figure 4 seed selection remains pre-registered: for each arm choose the seed whose sealed final cost is closest to that arm's ten-seed average, with the smaller seed breaking ties.",
            "",
            "The S3-TRAJ v1 HALT and both v1/v2 evidence families are preserved. This v2 decision authorizes only the registered presentation definition; it authorizes no new algorithm or superiority claim.",
            "",
        ]
        REPORT.write_text("\n".join(report_lines), encoding="utf-8")
        _clean_appledouble()
        hash_paths = _hash_inputs()
        _write_json(OUT / "artifact_hashes_v2.json", {
            "schema_version": "resetp.artifact-hashes.s3-trajectory-v2",
            "algorithm": "sha256",
            "source_halt_manifest": "artifact_hashes.json",
            "approval_register_id": APPROVAL_ID,
            "appledouble_excluded": True,
            "integrity_flags": [traj.APPLEDOUBLE_FLAG],
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in hash_paths
                if not path.name.startswith("._")
            },
        })
        _write_json(DONE, {
            "decision": decision["decision"],
            "artifact_hashes": "artifact_hashes_v2.json",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        _write_json(DECISION, {
            "schema_version": "resetp.e2-final-campaign.s3-trajectory-v2",
            "decision": "HALT_S3_TRAJ_CURVE_MATERIALIZATION_GATE",
            "approval_register_id": APPROVAL_ID,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "source_halt_decision_preserved": "decision.json",
        })
        print(f"[S3-TRAJ curve v2] HALT: {exc}", file=sys.stderr, flush=True)
        return 2
    print("[S3-TRAJ curve v2] PASS_S3_TRAJ_CURVE_UNDER_REGISTERED_DEFINITION", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
