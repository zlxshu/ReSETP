#!/usr/bin/env python3
"""Run and audit the preregistered staged-v7 iteration display case.

Seeds 1--5 are reused from the sealed 81-instance formal batch. Seeds 6--10
are fresh executions of the identical frozen algorithm. The displayed seed
for each algorithm is selected by the result-blind rule registered before the
formal batch: final cost closest to that algorithm's ten-seed mean.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing as mp
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_ROOT = REPO / "baselines/e2_final_campaign_20260720"
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v7_small_archive_ledger_20260724",
)
CAMPAIGN_CONFIGS = {
    "corrected_china81_rerun_v5_staged_portfolio_20260724": {
        "formal_preregistration": "formal_preregistration_v2.json",
        "case_registration": "s3_trajectory_case_registration.json",
        "execution_registration": (
            "s3_trajectory_execution_preregistration_v1.json"
        ),
        "operation": "STAGED_V5_S3_ITERATION_DISPLAY_GATE",
        "formal_verdict": "PASS_D6_CORRECTED_CHINA81_E2_STAGED_RAW",
        "runner": "v5",
    },
    "corrected_china81_rerun_v7_small_archive_ledger_20260724": {
        "formal_preregistration": "formal_preregistration_v4.json",
        "case_registration": "s3_trajectory_case_registration_v2.json",
        "execution_registration": (
            "s3_trajectory_execution_preregistration_v2.json"
        ),
        "operation": "STAGED_V7_S3_ITERATION_DISPLAY_GATE",
        "formal_verdict": (
            "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_"
            "SMALL_ARCHIVE_LEDGER"
        ),
        "runner": "v7",
    },
}
if CAMPAIGN_NAME not in CAMPAIGN_CONFIGS:
    raise RuntimeError(f"unsupported staged campaign: {CAMPAIGN_NAME!r}")
CAMPAIGN_CONFIG = CAMPAIGN_CONFIGS[CAMPAIGN_NAME]
os.environ["RESET_D6_CAMPAIGN_NAME"] = CAMPAIGN_NAME
CAMPAIGN = CAMPAIGN_ROOT / CAMPAIGN_NAME
FULL = CAMPAIGN / "full_gate"
STRENGTH = CAMPAIGN / "result_strength_gate"
CASE_REGISTRATION = CAMPAIGN / str(CAMPAIGN_CONFIG["case_registration"])
EXECUTION_REGISTRATION = (
    CAMPAIGN / str(CAMPAIGN_CONFIG["execution_registration"])
)
OUT = CAMPAIGN / "s3_trajectory_gate"
EXTRA = OUT / "extra_seed_tasks"
FORMAL_PREREGISTRATION = (
    CAMPAIGN / str(CAMPAIGN_CONFIG["formal_preregistration"])
)
for path in (CAMPAIGN_ROOT,):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

if CAMPAIGN_CONFIG["runner"] == "v7":
    import run_corrected_china81_d6_staged_portfolio_v6_budget_recheck as registered  # noqa: E402

    formal = registered.frozen
else:
    import run_corrected_china81_d6_staged_portfolio as formal  # noqa: E402

    registered = None


ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
FORMAL_SEEDS = (1, 2, 3, 4, 5)
EXTRA_SEEDS = (6, 7, 8, 9, 10)
ALL_SEEDS = (*FORMAL_SEEDS, *EXTRA_SEEDS)
EPS = 1.0e-9
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def verify_manifest(root: Path) -> None:
    manifest = json.loads(
        (root / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    for relative, expected in manifest["artifacts"].items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def _registration() -> tuple[dict[str, Any], dict[str, Any]]:
    case = json.loads(CASE_REGISTRATION.read_text(encoding="utf-8"))
    execution = json.loads(
        EXECUTION_REGISTRATION.read_text(encoding="utf-8")
    )
    if (
        execution.get("operation")
        != CAMPAIGN_CONFIG["operation"]
        or execution.get("campaign_name") != CAMPAIGN_NAME
        or execution.get("case_registration_sha256")
        != sha256(CASE_REGISTRATION)
        or execution.get("formal_preregistration_sha256")
        != sha256(FORMAL_PREREGISTRATION)
        or execution.get("result_rows_read_before_freeze") != 0
    ):
        raise RuntimeError("S3 execution registration mismatch")
    for relative, expected in execution["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"S3 registered source drift: {relative}")
    if (
        case.get("selected_instance_id")
        != execution.get("selected_instance_id")
        or tuple(case.get("seeds", ())) != ALL_SEEDS
    ):
        raise RuntimeError("S3 case and execution registrations disagree")
    return case, execution


def _require_upstream_pass() -> None:
    full = json.loads((FULL / "decision.json").read_text(encoding="utf-8"))
    strength = json.loads(
        (STRENGTH / "decision.json").read_text(encoding="utf-8")
    )
    if (
        full.get("verdict")
        != CAMPAIGN_CONFIG["formal_verdict"]
        or strength.get("verdict")
        != "PASS_E2_STAGED_PORTFOLIO_PAPER_STRENGTH"
        or not bool(strength.get("paper_strength_pass"))
    ):
        raise RuntimeError("S3 is blocked by the formal E2 strength gate")
    verify_manifest(FULL)
    verify_manifest(STRENGTH)


def _configure_formal_for_extra() -> None:
    formal.OUT = EXTRA
    formal.PREREGISTRATION = EXECUTION_REGISTRATION
    if registered is not None:
        registered.OUT = EXTRA
        registered.PREREGISTRATION = EXECUTION_REGISTRATION


def _run_extra_seed(instance_id: str, seed: int) -> dict[str, Any]:
    _configure_formal_for_extra()
    if registered is not None:
        return registered._run_unit_v6(instance_id, seed)
    return formal._run_unit(instance_id, seed)


def _extra_task_dir(instance_id: str, seed: int) -> Path:
    return EXTRA / "tasks" / formal._task_id(instance_id, seed)


def _formal_task_dir(instance_id: str, seed: int) -> Path:
    return FULL / "tasks" / formal._task_id(instance_id, seed)


def _run_extra(workers: int) -> None:
    case, _ = _registration()
    _require_upstream_pass()
    if any(
        os.environ.get(key) != value
        for key, value in REQUIRED_THREAD_ENV.items()
    ):
        raise RuntimeError("single-thread environment is not fully locked")
    instance_id = str(case["selected_instance_id"])
    pending = [
        seed
        for seed in EXTRA_SEEDS
        if not (
            _extra_task_dir(instance_id, seed) / "decision.json"
        ).is_file()
    ]
    if not pending:
        return
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
    ) as executor:
        futures = {
            executor.submit(_run_extra_seed, instance_id, seed): seed
            for seed in pending
        }
        try:
            for future in as_completed(futures):
                seed = futures[future]
                row = future.result()
                print(
                    f"[S3-STAGED] seed={seed} {row['status']}",
                    flush=True,
                )
        except Exception:
            for future in futures:
                future.cancel()
            raise


def _read_task_row(task_dir: Path) -> dict[str, str]:
    decision = json.loads(
        (task_dir / "decision.json").read_text(encoding="utf-8")
    )
    if decision.get("verdict") != "PASS_D6_E2_STAGED_PORTFOLIO_TASK":
        raise RuntimeError(f"task is not PASS: {task_dir.name}")
    manifest = json.loads(
        (task_dir / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    for relative, expected in manifest["artifacts"].items():
        path = task_dir / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"task artifact drift: {path}")
    rows = read_csv(task_dir / "raw_runs.csv")
    if len(rows) != 1:
        raise RuntimeError(f"task row count is not one: {task_dir.name}")
    row = rows[0]
    if row.get("status") != "PASS":
        raise RuntimeError(f"task row is not PASS: {task_dir.name}")
    return row


def _trajectory_payload(task_dir: Path, row: dict[str, str]) -> dict[str, Any]:
    path = task_dir / "trajectory_observations.json"
    if sha256(path) != row["trajectory_sha256"]:
        raise RuntimeError(f"trajectory hash mismatch: {task_dir.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "resetp.d6-e2-staged-trajectories.v1":
        raise RuntimeError(f"trajectory schema mismatch: {task_dir.name}")
    return payload


def _strict_curve(
    payload: dict[str, Any],
    arm: str,
    endpoint: float,
) -> tuple[list[dict[str, float]], int]:
    best = float(payload["initial_objective"])
    points = [{"elapsed_seconds": 0.0, "cost": best}]
    decreases = 0
    observations = sorted(
        payload["curves"][arm],
        key=lambda item: float(item["elapsed_seconds"]),
    )
    for observation in observations:
        cost = float(observation["objective"])
        elapsed = float(observation["elapsed_seconds"])
        if cost < best - EPS:
            best = cost
            decreases += 1
            points.append({"elapsed_seconds": elapsed, "cost": cost})
    if abs(best - endpoint) > EPS:
        raise RuntimeError(
            f"{arm} curve endpoint {best} != sealed cost {endpoint}"
        )
    endpoint_time = max(
        float(item["elapsed_seconds"]) for item in observations
    )
    if endpoint_time > points[-1]["elapsed_seconds"] + EPS:
        points.append(
            {"elapsed_seconds": endpoint_time, "cost": endpoint}
        )
    return points, decreases


def _closest_seed(
    rows_by_seed: dict[int, dict[str, str]],
    arm: str,
) -> tuple[int, float]:
    mean_cost = statistics.fmean(
        float(rows_by_seed[seed][f"{arm}_cost"])
        for seed in ALL_SEEDS
    )
    selected = min(
        ALL_SEEDS,
        key=lambda seed: (
            abs(
                float(rows_by_seed[seed][f"{arm}_cost"])
                - mean_cost
            ),
            seed,
        ),
    )
    return selected, mean_cost


def _finalize() -> dict[str, Any]:
    case, execution = _registration()
    _require_upstream_pass()
    instance_id = str(case["selected_instance_id"])
    rows_by_seed: dict[int, dict[str, str]] = {}
    task_dirs: dict[int, Path] = {}
    for seed in ALL_SEEDS:
        task_dir = (
            _formal_task_dir(instance_id, seed)
            if seed in FORMAL_SEEDS
            else _extra_task_dir(instance_id, seed)
        )
        row = _read_task_row(task_dir)
        if (
            row["instance_id"] != instance_id
            or int(row["seed"]) != seed
            or int(row["complete_candidate_attempts"]) != 280
            or int(row["total_iterations_per_view"]) != 25_000
        ):
            raise RuntimeError(f"S3 task contract mismatch: {task_dir.name}")
        rows_by_seed[seed] = row
        task_dirs[seed] = task_dir

    table_rows = [
        {
            "instance_id": instance_id,
            "seed": seed,
            **{
                f"{arm}_cost": float(
                    rows_by_seed[seed][f"{arm}_cost"]
                )
                for arm in ARMS
            },
            **{
                f"{arm}_cpu_seconds": float(
                    rows_by_seed[seed][f"{arm}_cpu_seconds"]
                )
                for arm in ARMS
            },
            "status": "PASS",
        }
        for seed in ALL_SEEDS
    ]
    write_csv(OUT / "raw_runs.csv", table_rows)

    selected_seeds: dict[str, int] = {}
    ten_seed_means: dict[str, float] = {}
    curve_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    minimum_points = int(execution["trajectory_gate"]["minimum_points"])
    minimum_decreases = int(
        execution["trajectory_gate"]["minimum_strict_decreases"]
    )
    for arm in ARMS:
        seed, mean_cost = _closest_seed(rows_by_seed, arm)
        selected_seeds[arm] = seed
        ten_seed_means[arm] = mean_cost
        row = rows_by_seed[seed]
        endpoint = float(row[f"{arm}_cost"])
        payload = _trajectory_payload(task_dirs[seed], row)
        curve, decreases = _strict_curve(payload, arm, endpoint)
        registered_points = int(row[f"{arm}_curve_points"])
        registered_decreases = int(row[f"{arm}_strict_decreases"])
        if registered_decreases != decreases:
            raise RuntimeError(
                f"{arm} strict-decrease ledger mismatch for seed {seed}"
            )
        point_gate = registered_points >= minimum_points
        decrease_gate = registered_decreases >= minimum_decreases
        endpoint_gate = abs(curve[-1]["cost"] - endpoint) <= EPS
        checks[f"{arm}:minimum_points"] = point_gate
        checks[f"{arm}:minimum_strict_decreases"] = decrease_gate
        checks[f"{arm}:endpoint_exact"] = endpoint_gate
        audit_rows.append(
            {
                "algorithm": arm,
                "selected_seed": seed,
                "ten_seed_mean_cost": mean_cost,
                "selected_seed_final_cost": endpoint,
                "registered_curve_points": registered_points,
                "registered_strict_decreases": registered_decreases,
                "displayed_rows": len(curve),
                "minimum_points_required": minimum_points,
                "minimum_strict_decreases_required": minimum_decreases,
                "point_gate": point_gate,
                "decrease_gate": decrease_gate,
                "endpoint_gate": endpoint_gate,
            }
        )
        for sequence, point in enumerate(curve):
            curve_rows.append(
                {
                    "algorithm": arm,
                    "seed": seed,
                    "sequence": sequence,
                    "elapsed_seconds": point["elapsed_seconds"],
                    "elapsed_minutes": point["elapsed_seconds"] / 60.0,
                    "cost_cny": point["cost"],
                    "observed_online": True,
                    "interpolated_or_smoothed": False,
                }
            )

    write_csv(OUT / "trajectory_audit.csv", audit_rows)
    write_csv(OUT / "curve_data.csv", curve_rows)
    pass_gate = all(checks.values())
    verdict = (
        "PASS_S3_STAGED_GENUINE_ITERATION_CURVES"
        if pass_gate
        else "HOLD_S3_STAGED_CURVES_NOT_CHEN_LIKE"
    )
    decision = {
        "schema": "resetp.e2-staged-s3-trajectory-decision.v1",
        "verdict": verdict,
        "trajectory_gate_pass": pass_gate,
        "selected_instance_id": instance_id,
        "selected_seeds": selected_seeds,
        "ten_seed_mean_costs": ten_seed_means,
        "checks": checks,
        "formal_seed_rows_reused": 5,
        "fresh_extra_seed_rows": 5,
        "algorithm_or_evaluator_changed_for_s3": False,
        "smoothing_or_interpolation_used": False,
        "broken_axis_used": False,
        "case_or_seed_selected_from_curve_shape": False,
        "formal_e3_search_allowed": False,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e2-staged-s3-trajectory-metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "campaign_name": CAMPAIGN_NAME,
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    FORMAL_PREREGISTRATION,
                    CASE_REGISTRATION,
                    EXECUTION_REGISTRATION,
                    FULL / "raw_runs.csv",
                    FULL / "decision.json",
                    FULL / "artifact_hashes.json",
                    STRENGTH / "decision.json",
                    STRENGTH / "artifact_hashes.json",
                    Path(__file__).resolve(),
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# Staged-v7 S3 iteration display gate\n\n"
        f"Decision: `{verdict}`.\n\n"
        f"The input-only registered display case is `{instance_id}`. "
        "Seeds 1--5 were reused from the sealed formal E2 matrix and seeds "
        "6--10 used the identical frozen staged-v7 algorithm. Each plotted "
        "line uses the preregistered mean-nearest seed for that algorithm, "
        "actual online complete-model observations, and ordinary straight "
        "segments only. No smoothing, interpolation, broken axis, curve-"
        "shape seed selection, or offline discarded-candidate scoring was "
        "used. A failed shape criterion blocks Figure 4 and E3.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name not in {
                "artifact_hashes.json",
                "done.json",
            }
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
                "__pycache__",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e2-staged-s3-trajectory-done.v1",
            "verdict": verdict,
            "decision_sha256": sha256(OUT / "decision.json"),
            "curve_data_sha256": sha256(OUT / "curve_data.csv"),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    if not args.finalize_only:
        _run_extra(args.workers)
    decision = _finalize()
    return 0 if decision["trajectory_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
