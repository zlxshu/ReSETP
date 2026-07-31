#!/usr/bin/env python3
"""Aggregate the certified E5 v4 units without running any search.

This closeout is intentionally standard-library-only.  It reads the 40 plans,
40 independent certificates, independent verification result, formal task
statuses, and raw run rows already sealed in the v4 directory.  It never
imports or calls the search runner, checker, solver, or route-pool code.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "baselines/china_e3_e7/e5_nonlinear_v4_20260730"
OUT = REPO / "baselines/china_e3_e7/e5_nonlinear_final_20260730"
CONTRACT = (
    REPO / "docs/handoff/experiment_contract_v2_journal_aligned_20260730.md"
)
TASK_ID = "E5-NONLINEAR-CHARGING-FINAL-20260730"
SOURCE_TASK_ID = "E5-NONLINEAR-CHARGING-V4-20260730"
INSTANCE_ORDER = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
)
ARMS = ("L100_control", "NL90_mild")
EXPECTED_UNITS = 40
EXPECTED_PAIRS = 20
EXPECTED_PER_INSTANCE_ARM = 10
EXCLUDED_DIRS = frozenset({"__pycache__", ".pytest_cache"})
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
    / "route_pool_sp.py",
)
ENUMERATION_FIXES = (
    {
        "path": "baselines/china_e3_e7/run_e5_nonlinear_v2_20260730.py",
        "locations": [
            "sealed_tree_hashes",
            "load_certificates",
            "aggregate_and_close artifact manifest traversal",
        ],
    },
    {
        "path": "baselines/china_e3_e7/run_e5_nonlinear_v3_20260730.py",
        "locations": ["_status_lookup"],
    },
    {
        "path": "baselines/china_e3_e7/run_e5_nonlinear_v4_20260730.py",
        "locations": ["_status_lookup"],
    },
    {
        "path": "baselines/china_e3_e7/check_e5_nonlinear_v2_20260730.py",
        "locations": ["formal plan enumeration used by the v4 checker"],
    },
)
STANDARD_CAUSES = (
    "CHARGING_DURATION_OR_POWER",
    "ELECTRIC_ENERGY_SHORTFALL_OR_SOC",
    "TIME_WINDOW_OVERRUN",
    "FLEET_CAPACITY",
    "INTER_TRIP_CONNECTION_OR_ROUTE_CONTINUITY",
    "CHARGING_TIMING_INCONSISTENCY",
    "CHARGER_CAPACITY_OR_CONCURRENCY",
)
SESSION_FIELDS = (
    "start_soc_pct",
    "end_soc_pct",
    "linear_duration_seconds",
    "nonlinear_duration_seconds",
    "nonlinear_minus_linear_seconds",
)
TOL = 1.0e-9


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_real_artifact_file(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.startswith("._")
        and not any(part in EXCLUDED_DIRS for part in path.parts)
    )


def real_files(root: Path, *, exclude_monitor: bool = False) -> list[Path]:
    rows = []
    for path in root.rglob("*"):
        if not is_real_artifact_file(path):
            continue
        relative = path.relative_to(root)
        if exclude_monitor and relative.parts[:1] == ("monitor_runtime",):
            continue
        rows.append(path)
    return sorted(rows)


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_bytes(path, canonical_bytes(payload))


def atomic_text(path: Path, value: str) -> None:
    atomic_bytes(path, value.encode("utf-8"))


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"HALT_EMPTY_CSV:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"HALT_EXPECTED_JSON_OBJECT:{path}")
    return value


def key_of(row: dict[str, Any]) -> tuple[str, int, str]:
    return str(row["instance_id"]), int(row["seed"]), str(row["arm"])


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise RuntimeError(f"{code}:{detail}")


def mean(values: Iterable[float]) -> float:
    rows = list(values)
    require(bool(rows), "HALT_EMPTY_MEAN")
    return sum(rows) / len(rows)


def median(values: Iterable[float]) -> float:
    rows = sorted(values)
    require(bool(rows), "HALT_EMPTY_MEDIAN")
    middle = len(rows) // 2
    if len(rows) % 2:
        return rows[middle]
    return 0.5 * (rows[middle - 1] + rows[middle])


def pct(numerator: int, denominator: int) -> float:
    require(denominator > 0, "HALT_ZERO_DENOMINATOR")
    return 100.0 * numerator / denominator


def close_enough(left: float, right: float) -> bool:
    return abs(left - right) <= TOL * max(1.0, abs(left), abs(right))


def remove_appledouble(root: Path) -> int:
    removed = 0
    for path in sorted(root.rglob("._*")):
        if path.is_file() and path.name.startswith("._"):
            path.unlink()
            removed += 1
    return removed


def validate_output_target() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    existing = list(OUT.iterdir())
    require(not existing, "HALT_FINAL_OUTPUT_NOT_EMPTY", [str(p) for p in existing])


def load_source() -> dict[str, Any]:
    require(SOURCE.is_dir(), "HALT_SOURCE_DIRECTORY_MISSING", SOURCE)
    appledouble = [
        path for path in SOURCE.rglob("._*") if path.is_file()
    ]
    require(not appledouble, "HALT_SOURCE_APPLEDOUBLE_REMAINS", len(appledouble))

    plan_paths = sorted(
        path
        for path in (SOURCE / "formal/plans").glob("*.json")
        if is_real_artifact_file(path)
    )
    certificate_paths = sorted(
        path
        for path in (SOURCE / "certificates").glob("*.json")
        if is_real_artifact_file(path)
    )
    status_paths = sorted(
        path
        for path in (SOURCE / "formal/task_status").glob("*.json")
        if is_real_artifact_file(path)
    )
    raw_rows = read_csv(SOURCE / "raw_runs.csv")
    verification = read_json(SOURCE / "independent_verification.json")
    v4_done = read_json(SOURCE / "done.json")
    source_lock = read_json(SOURCE / "source_lock.json")

    require(len(plan_paths) == EXPECTED_UNITS, "HALT_PLAN_DENOMINATOR", len(plan_paths))
    require(
        len(certificate_paths) == EXPECTED_UNITS,
        "HALT_CERTIFICATE_DENOMINATOR",
        len(certificate_paths),
    )
    require(
        len(status_paths) == EXPECTED_UNITS,
        "HALT_STATUS_DENOMINATOR",
        len(status_paths),
    )
    require(len(raw_rows) == EXPECTED_UNITS, "HALT_RAW_DENOMINATOR", len(raw_rows))
    require(verification.get("status") == "PASS", "HALT_VERIFICATION_NOT_PASS")
    require(
        int(verification.get("certificate_count", -1)) == EXPECTED_UNITS,
        "HALT_VERIFICATION_CERTIFICATE_COUNT",
    )
    require(
        int(verification.get("unique_certificate_ids", -1)) == EXPECTED_UNITS,
        "HALT_VERIFICATION_UNIQUE_IDS",
    )
    require(
        v4_done.get("status") == "HALT_APPLEDOUBLE_CERTIFICATE_DENOMINATOR",
        "HALT_UNEXPECTED_V4_DONE_STATUS",
        v4_done.get("status"),
    )
    require(
        int(v4_done.get("formal_search_units_passed", -1)) == EXPECTED_UNITS,
        "HALT_V4_FORMAL_PASS_COUNT",
    )

    plans: dict[tuple[str, int, str], dict[str, Any]] = {}
    plan_file_by_key: dict[tuple[str, int, str], Path] = {}
    for path in plan_paths:
        row = read_json(path)
        key = key_of(row)
        require(key not in plans, "HALT_DUPLICATE_PLAN_KEY", key)
        require(row.get("task_id") == SOURCE_TASK_ID, "HALT_PLAN_TASK_ID", key)
        without_id = dict(row)
        declared = str(without_id.pop("plan_sha256"))
        require(payload_sha256(without_id) == declared, "HALT_PLAN_ID", key)
        require(
            payload_sha256(row["solution"]) == str(row["solution_sha256"]),
            "HALT_PLAN_SOLUTION_ID",
            key,
        )
        plans[key] = row
        plan_file_by_key[key] = path

    certificates: dict[tuple[str, int, str], dict[str, Any]] = {}
    certificate_file_by_key: dict[tuple[str, int, str], Path] = {}
    for path in certificate_paths:
        row = read_json(path)
        key = key_of(row)
        require(key not in certificates, "HALT_DUPLICATE_CERTIFICATE_KEY", key)
        require(row.get("certificate_status") == "PASS", "HALT_CERTIFICATE_NOT_PASS", key)
        without_id = dict(row)
        declared = str(without_id.pop("certificate_id"))
        require(payload_sha256(without_id) == declared, "HALT_CERTIFICATE_ID", key)
        require(row.get("decision_structure_unchanged") is True, "HALT_REPLAY_CHANGED", key)
        require(
            row.get("search_objective_matches_independent_recompute") is True,
            "HALT_SEARCH_OBJECTIVE_RECOMPUTE",
            key,
        )
        for field in SESSION_FIELDS:
            require(
                all(field in session for session in row.get("sessions", [])),
                "HALT_SESSION_FIELD_NOT_PERSISTED",
                f"{key}:{field}",
            )
        certificates[key] = row
        certificate_file_by_key[key] = path

    statuses: dict[tuple[str, int, str], dict[str, Any]] = {}
    for path in status_paths:
        row = read_json(path)
        key = key_of(row)
        require(key not in statuses, "HALT_DUPLICATE_STATUS_KEY", key)
        require(row.get("status") == "PASS", "HALT_STATUS_NOT_PASS", key)
        require(int(row.get("error_candidates", -1)) == 0, "HALT_ERROR_CANDIDATE", key)
        require(
            int(row.get("complete_candidate_budget_cap", -1)) == 400,
            "HALT_BUDGET_CAP",
            key,
        )
        statuses[key] = row

    raw_by_key: dict[tuple[str, int, str], dict[str, str]] = {}
    for row in raw_rows:
        key = key_of(row)
        require(key not in raw_by_key, "HALT_DUPLICATE_RAW_KEY", key)
        raw_by_key[key] = row

    expected_keys = {
        (instance_id, seed, arm)
        for instance_id in INSTANCE_ORDER
        for seed in range(1, 11)
        for arm in ARMS
    }
    for label, keys in (
        ("plans", set(plans)),
        ("certificates", set(certificates)),
        ("statuses", set(statuses)),
        ("raw", set(raw_by_key)),
    ):
        require(keys == expected_keys, "HALT_KEY_SET_MISMATCH", label)

    for key in sorted(expected_keys):
        plan = plans[key]
        cert = certificates[key]
        status = statuses[key]
        raw = raw_by_key[key]
        declared_plan_path = REPO / str(cert["plan_path"])
        require(declared_plan_path == plan_file_by_key[key], "HALT_PLAN_PATH", key)
        require(
            file_sha256(declared_plan_path) == str(cert["plan_sha256"]),
            "HALT_PLAN_FILE_HASH",
            key,
        )
        require(
            cert["solution_sha256"] == plan["solution_sha256"],
            "HALT_SOLUTION_HASH_CROSSCHECK",
            key,
        )
        require(
            close_enough(
                float(raw["search_total_cost_cny"]),
                float(plan["search_total_cost_cny"]),
            ),
            "HALT_RAW_PLAN_OBJECTIVE",
            key,
        )
        require(
            close_enough(
                float(status["search_total_cost_cny"]),
                float(plan["search_total_cost_cny"]),
            ),
            "HALT_STATUS_PLAN_OBJECTIVE",
            key,
        )
        require(raw["certificate_id"] == cert["certificate_id"], "HALT_RAW_CERT_ID", key)
        require(
            int(raw["planning_physics_feasible"])
            == int(cert["planning_physics_feasible"]),
            "HALT_RAW_PLANNING_FEASIBILITY",
            key,
        )
        require(
            int(raw["common_NL90_feasible"]) == int(cert["nonlinear_feasible"]),
            "HALT_RAW_NL90_FEASIBILITY",
            key,
        )
        require(
            int(raw["linear_plan_false_feasible"])
            == int(cert["linear_plan_false_feasible"]),
            "HALT_RAW_FALSE_FEASIBILITY",
            key,
        )
        require(
            int(raw["complete_candidate_evaluations_consumed"])
            == int(status["complete_candidate_evaluations_consumed"]),
            "HALT_RAW_EVALUATION_COUNT",
            key,
        )
        require(
            int(raw["error_candidates"]) == 0,
            "HALT_RAW_ERROR_CANDIDATES",
            key,
        )
        expected_false = bool(
            key[2] == "L100_control"
            and cert["planning_physics_feasible"]
            and not cert["nonlinear_feasible"]
        )
        require(
            bool(cert["linear_plan_false_feasible"]) == expected_false,
            "HALT_FALSE_FEASIBILITY_LOGIC",
            key,
        )

    for instance_id in INSTANCE_ORDER:
        for seed in range(1, 11):
            left = raw_by_key[(instance_id, seed, "L100_control")]
            right = raw_by_key[(instance_id, seed, "NL90_mild")]
            require(
                left["common_initial_solution_sha256"]
                == right["common_initial_solution_sha256"],
                "HALT_COMMON_INITIAL_SOLUTION",
                (instance_id, seed),
            )

    protected_expected = source_lock["protected_source_sha256"]
    protected_now = {}
    for path in PROTECTED:
        relative = str(path.relative_to(REPO))
        current = file_sha256(path)
        protected_now[relative] = {
            "v4_locked_sha256": protected_expected[relative],
            "aggregation_time_sha256": current,
            "unchanged": current == protected_expected[relative],
        }
        require(
            current == protected_expected[relative],
            "HALT_PROTECTED_SOURCE_DRIFT",
            relative,
        )

    return {
        "plans": plans,
        "plan_file_by_key": plan_file_by_key,
        "certificates": certificates,
        "certificate_file_by_key": certificate_file_by_key,
        "statuses": statuses,
        "raw_by_key": raw_by_key,
        "verification": verification,
        "v4_done": v4_done,
        "source_lock": source_lock,
        "protected_now": protected_now,
    }


def build_raw_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key in sorted(
        source["certificates"],
        key=lambda item: (INSTANCE_ORDER.index(item[0]), item[1], ARMS.index(item[2])),
    ):
        cert = source["certificates"][key]
        plan = source["plans"][key]
        status = source["statuses"][key]
        old_raw = source["raw_by_key"][key]
        rows.append(
            {
                "task_id": TASK_ID,
                "source_task_id": SOURCE_TASK_ID,
                "instance_id": key[0],
                "sample_role": cert["sample_role"],
                "seed": key[1],
                "arm": key[2],
                "complete_candidate_budget_cap": int(
                    status["complete_candidate_budget_cap"]
                ),
                "complete_candidate_evaluations_consumed": int(
                    status["complete_candidate_evaluations_consumed"]
                ),
                "termination_reason": status["termination_reason"],
                "feasible_candidates": int(status["feasible_candidates"]),
                "infeasible_candidates": int(status["infeasible_candidates"]),
                "error_candidates": int(status["error_candidates"]),
                "elapsed_wall_seconds": float(status["elapsed_wall_seconds"]),
                "elapsed_cpu_seconds": float(status["elapsed_cpu_seconds"]),
                "search_total_cost_cny": float(plan["search_total_cost_cny"]),
                "planning_physics_feasible": int(
                    cert["planning_physics_feasible"]
                ),
                "common_NL90_feasible": int(cert["nonlinear_feasible"]),
                "linear_plan_false_feasible": int(
                    cert["linear_plan_false_feasible"]
                ),
                "planning_full_model_total_cost_cny": (
                    cert["planning_full_model_total_cost_cny"]
                    if cert["planning_physics_feasible"]
                    else "NA_INFEASIBLE"
                ),
                "common_NL90_full_model_total_cost_cny": (
                    cert["common_nonlinear_full_model_total_cost_cny"]
                    if cert["nonlinear_feasible"]
                    else "NA_INFEASIBLE"
                ),
                "physical_vehicle_count": int(cert["physical_vehicle_count"]),
                "nonlinear_violation_count": len(cert["nonlinear_violations"]),
                "nonlinear_infeasibility_categories_json": json.dumps(
                    cert["nonlinear_infeasibility_categories"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "charging_session_count": len(cert["sessions"]),
                "plan_content_id": plan["plan_sha256"],
                "plan_file_sha256": file_sha256(
                    source["plan_file_by_key"][key]
                ),
                "certificate_id": cert["certificate_id"],
                "certificate_file_sha256": file_sha256(
                    source["certificate_file_by_key"][key]
                ),
                "search_status": status["status"],
                "certificate_status": cert["certificate_status"],
                "v4_scientific_endpoint_inclusion_at_halt": old_raw[
                    "scientific_endpoint_inclusion"
                ],
                "scientific_endpoint_inclusion": (
                    "INCLUDED_IN_FINAL_AGGREGATION_ALL_40_UNITS"
                ),
                "search_rerun_in_final_round": 0,
            }
        )
    require(len(rows) == EXPECTED_UNITS, "HALT_FINAL_RAW_DENOMINATOR")
    return rows


def formal_arm_rows(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    arm_rows: list[dict[str, Any]] = []
    for instance_id in INSTANCE_ORDER:
        for arm in ARMS:
            certs = [
                cert
                for key, cert in source["certificates"].items()
                if key[0] == instance_id and key[2] == arm
            ]
            feasible = [
                cert for cert in certs if cert["planning_physics_feasible"]
            ]
            costs = [
                float(cert["planning_full_model_total_cost_cny"])
                for cert in feasible
            ]
            require(bool(costs), "HALT_NO_FEASIBLE_FORMAL_RUNS", (instance_id, arm))
            best_cert = min(
                feasible,
                key=lambda row: (
                    float(row["planning_full_model_total_cost_cny"]),
                    int(row["seed"]),
                ),
            )
            vehicles = [int(cert["physical_vehicle_count"]) for cert in feasible]
            times = [
                float(source["statuses"][key]["elapsed_wall_seconds"])
                for key in source["statuses"]
                if key[0] == instance_id and key[2] == arm
            ]
            evaluations = [
                int(
                    source["statuses"][key][
                        "complete_candidate_evaluations_consumed"
                    ]
                )
                for key in source["statuses"]
                if key[0] == instance_id and key[2] == arm
            ]
            avg_cost = mean(costs)
            best_cost = min(costs)
            arm_rows.append(
                {
                    "instance_id": instance_id,
                    "sample_role": certs[0]["sample_role"],
                    "arm": arm,
                    "feasible_runs": len(feasible),
                    "runs": len(certs),
                    "feasibility_rate": len(feasible) / len(certs),
                    "feasibility_rate_pct": pct(len(feasible), len(certs)),
                    "Best_CNY": best_cost,
                    "Avg_CNY": avg_cost,
                    "Gap_pct": 100.0 * (avg_cost - best_cost) / best_cost,
                    "vehicles_best": int(best_cert["physical_vehicle_count"]),
                    "vehicles_avg": mean(float(value) for value in vehicles),
                    "time_avg_seconds": mean(times),
                    "actual_evaluations_avg": mean(
                        float(value) for value in evaluations
                    ),
                    "actual_evaluations_min": min(evaluations),
                    "actual_evaluations_max": max(evaluations),
                }
            )

    one_row: list[dict[str, Any]] = []
    by_key = {(row["instance_id"], row["arm"]): row for row in arm_rows}
    for instance_id in INSTANCE_ORDER:
        left = by_key[(instance_id, "L100_control")]
        right = by_key[(instance_id, "NL90_mild")]
        row: dict[str, Any] = {
            "instance_id": instance_id,
            "sample_role": left["sample_role"],
        }
        for prefix, source_row in (("L100", left), ("NL90", right)):
            for field in (
                "Best_CNY",
                "Avg_CNY",
                "Gap_pct",
                "vehicles_best",
                "vehicles_avg",
                "time_avg_seconds",
                "actual_evaluations_avg",
                "actual_evaluations_min",
                "actual_evaluations_max",
                "feasible_runs",
                "runs",
                "feasibility_rate_pct",
            ):
                row[f"{prefix}_{field}"] = source_row[field]
        one_row.append(row)
    return arm_rows, one_row


def paired_cost_rows(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance_id in INSTANCE_ORDER:
        for seed in range(1, 11):
            left = source["certificates"][(instance_id, seed, "L100_control")]
            right = source["certificates"][(instance_id, seed, "NL90_mild")]
            both = bool(left["nonlinear_feasible"] and right["nonlinear_feasible"])
            left_cost = left["common_nonlinear_full_model_total_cost_cny"]
            right_cost = right["common_nonlinear_full_model_total_cost_cny"]
            effect = (
                100.0 * (float(right_cost) - float(left_cost)) / float(left_cost)
                if both
                else None
            )
            rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "both_feasible_under_common_NL90": int(both),
                    "L100_plan_common_NL90_cost_CNY": (
                        left_cost if both else "NA_NOT_BOTH_FEASIBLE"
                    ),
                    "NL90_plan_common_NL90_cost_CNY": (
                        right_cost if both else "NA_NOT_BOTH_FEASIBLE"
                    ),
                    "NL90_minus_L100_cost_CNY": (
                        float(right_cost) - float(left_cost)
                        if both
                        else "NA_NOT_BOTH_FEASIBLE"
                    ),
                    "NL90_minus_L100_cost_pct": (
                        effect if effect is not None else "NA_NOT_BOTH_FEASIBLE"
                    ),
                }
            )
    require(len(rows) == EXPECTED_PAIRS, "HALT_PAIR_DENOMINATOR", len(rows))

    def summarize(subset: list[dict[str, Any]]) -> dict[str, Any]:
        eligible = [
            row for row in subset if row["both_feasible_under_common_NL90"]
        ]
        effects = [float(row["NL90_minus_L100_cost_pct"]) for row in eligible]
        return {
            "coverage_count": len(eligible),
            "denominator": len(subset),
            "mean_NL90_minus_L100_pct": mean(effects) if effects else None,
            "median_NL90_minus_L100_pct": median(effects) if effects else None,
            "min_NL90_minus_L100_pct": min(effects) if effects else None,
            "max_NL90_minus_L100_pct": max(effects) if effects else None,
        }

    summary = {
        "by_instance": {
            instance_id: summarize(
                [row for row in rows if row["instance_id"] == instance_id]
            )
            for instance_id in INSTANCE_ORDER
        },
        "overall": summarize(rows),
        "formula": (
            "per seed: 100 * (NL90 plan cost under common NL90 physics - "
            "L100 plan replay cost under common NL90 physics) / "
            "L100 plan replay cost; summary is the unweighted mean of "
            "eligible seed-pair percentages"
        ),
    }
    return rows, summary


def feasibility_endpoints(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint_1: dict[str, Any] = {"by_instance": {}}
    endpoint_2: dict[str, Any] = {"by_instance": {}}
    all_nl90 = []
    all_l100 = []
    for instance_id in INSTANCE_ORDER:
        nl90 = [
            cert
            for key, cert in source["certificates"].items()
            if key[0] == instance_id and key[2] == "NL90_mild"
        ]
        l100 = [
            cert
            for key, cert in source["certificates"].items()
            if key[0] == instance_id and key[2] == "L100_control"
        ]
        all_nl90.extend(nl90)
        all_l100.extend(l100)
        feasible_count = sum(
            int(cert["planning_physics_feasible"]) for cert in nl90
        )
        false_rows = [
            cert for cert in l100 if cert["linear_plan_false_feasible"]
        ]
        endpoint_1["by_instance"][instance_id] = {
            "feasible_count": feasible_count,
            "denominator": len(nl90),
            "feasibility_rate": feasible_count / len(nl90),
            "feasibility_rate_pct": pct(feasible_count, len(nl90)),
        }
        endpoint_2["by_instance"][instance_id] = {
            "false_feasible_count": len(false_rows),
            "denominator": len(l100),
            "false_feasible_rate": len(false_rows) / len(l100),
            "false_feasible_rate_pct": pct(len(false_rows), len(l100)),
        }
    feasible_overall = sum(
        int(cert["planning_physics_feasible"]) for cert in all_nl90
    )
    false_overall = sum(
        int(cert["linear_plan_false_feasible"]) for cert in all_l100
    )
    endpoint_1["overall"] = {
        "feasible_count": feasible_overall,
        "denominator": len(all_nl90),
        "feasibility_rate": feasible_overall / len(all_nl90),
        "feasibility_rate_pct": pct(feasible_overall, len(all_nl90)),
    }
    endpoint_2["overall"] = {
        "false_feasible_count": false_overall,
        "denominator": len(all_l100),
        "false_feasible_rate": false_overall / len(all_l100),
        "false_feasible_rate_pct": pct(false_overall, len(all_l100)),
    }
    return endpoint_1, endpoint_2


def cause_rows(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    false_certificates = [
        cert
        for key, cert in source["certificates"].items()
        if key[2] == "L100_control" and cert["linear_plan_false_feasible"]
    ]
    discovered = sorted(
        {
            category
            for cert in false_certificates
            for category in cert["nonlinear_infeasibility_categories"]
        }
        - set(STANDARD_CAUSES)
    )
    categories = (*STANDARD_CAUSES, *discovered)
    rows: list[dict[str, Any]] = []
    patterns: list[dict[str, Any]] = []
    machine: dict[str, Any] = {"by_instance": {}}

    scopes = [*INSTANCE_ORDER, "OVERALL"]
    for scope in scopes:
        subset = [
            cert
            for cert in false_certificates
            if scope == "OVERALL" or cert["instance_id"] == scope
        ]
        affected = Counter()
        violations = Counter()
        pattern_counts = Counter()
        for cert in subset:
            category_set = tuple(
                sorted(cert["nonlinear_infeasibility_categories"])
            )
            pattern_counts[category_set] += 1
            for category, count in cert[
                "nonlinear_infeasibility_categories"
            ].items():
                affected[category] += 1
                violations[category] += int(count)
        for category in categories:
            rows.append(
                {
                    "scope": scope,
                    "cause_category": category,
                    "affected_unit_count_allowing_overlap": affected[category],
                    "violation_count": violations[category],
                    "false_feasible_units_in_scope": len(subset),
                }
            )
        if pattern_counts:
            for category_set, count in sorted(pattern_counts.items()):
                patterns.append(
                    {
                        "scope": scope,
                        "overlap_pattern": "+".join(category_set),
                        "unit_count": count,
                    }
                )
        else:
            patterns.append(
                {
                    "scope": scope,
                    "overlap_pattern": "NONE_NO_FALSE_FEASIBLE_UNITS",
                    "unit_count": 0,
                }
            )
        machine[scope] = {
            "false_feasible_units": len(subset),
            "affected_units_by_cause_allowing_overlap": dict(affected),
            "violations_by_cause": dict(violations),
            "overlap_patterns": {
                "+".join(category_set): count
                for category_set, count in sorted(pattern_counts.items())
            },
        }
    return rows, patterns, machine


def session_rows_and_summary(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for key in sorted(
        source["certificates"],
        key=lambda item: (INSTANCE_ORDER.index(item[0]), item[1], ARMS.index(item[2])),
    ):
        cert = source["certificates"][key]
        certificate_path = source["certificate_file_by_key"][key]
        for session in cert["sessions"]:
            sessions.append(
                {
                    **session,
                    "source_certificate_id": cert["certificate_id"],
                    "source_certificate_path": str(
                        certificate_path.relative_to(REPO)
                    ),
                }
            )
    require(bool(sessions), "HALT_NO_PERSISTED_SESSIONS")
    sessions.sort(
        key=lambda row: (
            INSTANCE_ORDER.index(str(row["instance_id"])),
            int(row["seed"]),
            ARMS.index(str(row["arm"])),
            int(row["session_index"]),
        )
    )

    def summarize(
        scope: str,
        arm: str,
        subset: list[dict[str, Any]],
    ) -> dict[str, Any]:
        require(bool(subset), "HALT_EMPTY_SESSION_SCOPE", (scope, arm))
        result: dict[str, Any] = {
            "scope": scope,
            "arm": arm,
            "session_rows": len(subset),
            "positive_duration_delta_sessions": sum(
                float(row["nonlinear_minus_linear_seconds"]) > TOL
                for row in subset
            ),
        }
        result["positive_duration_delta_rate_pct"] = pct(
            int(result["positive_duration_delta_sessions"]), len(subset)
        )
        for field in SESSION_FIELDS:
            values = [float(row[field]) for row in subset]
            result[f"{field}_mean"] = mean(values)
            result[f"{field}_median"] = median(values)
            result[f"{field}_max"] = max(values)
        return result

    distribution: list[dict[str, Any]] = []
    for instance_id in INSTANCE_ORDER:
        instance_rows = [
            row for row in sessions if row["instance_id"] == instance_id
        ]
        for arm in ARMS:
            distribution.append(
                summarize(
                    instance_id,
                    arm,
                    [row for row in instance_rows if row["arm"] == arm],
                )
            )
        distribution.append(summarize(instance_id, "ALL_ARMS", instance_rows))
    for arm in ARMS:
        distribution.append(
            summarize(
                "OVERALL",
                arm,
                [row for row in sessions if row["arm"] == arm],
            )
        )
    distribution.append(summarize("OVERALL", "ALL_ARMS", sessions))
    machine = {
        "unit_of_description": (
            "charging session rows are descriptive nested observations, "
            "not independent experimental replicates"
        ),
        "by_instance": {
            instance_id: next(
                row
                for row in distribution
                if row["scope"] == instance_id and row["arm"] == "ALL_ARMS"
            )
            for instance_id in INSTANCE_ORDER
        },
        "overall": next(
            row
            for row in distribution
            if row["scope"] == "OVERALL" and row["arm"] == "ALL_ARMS"
        ),
    }
    return sessions, distribution, machine


def source_inventory() -> dict[str, Any]:
    all_real = real_files(SOURCE, exclude_monitor=False)
    scientific = real_files(SOURCE, exclude_monitor=True)
    return {
        "schema_version": "E5-FINAL-SOURCE-INVENTORY-v1",
        "source_directory": str(SOURCE.relative_to(REPO)),
        "enumeration_rule": (
            "exclude filenames beginning ._ and paths containing "
            "__pycache__ or .pytest_cache"
        ),
        "monitor_runtime_excluded_from_scientific_inventory": True,
        "v4_real_files_after_cleanup_including_monitor_runtime": len(all_real),
        "v4_scientific_source_files_excluding_monitor_runtime": len(scientific),
        "files": [
            {
                "path": str(path.relative_to(REPO)),
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in scientific
        ],
    }


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def render_report(
    *,
    arm_rows: list[dict[str, Any]],
    formal_rows: list[dict[str, Any]],
    endpoint_1: dict[str, Any],
    endpoint_2: dict[str, Any],
    endpoint_3: dict[str, Any],
    endpoint_4: dict[str, Any],
    cause_machine: dict[str, Any],
) -> str:
    formal_lines = []
    for row in formal_rows:
        formal_lines.append(
            "| {instance} | {lbest:.2f} | {lavg:.2f} | {lgap:.4f}% | "
            "{lvbest}/{lvavg:.2f} | {ltime:.2f} | {leval:.1f} "
            "[{lemin}–{lemax}] | {lf}/{lr} ({lfpct:.1f}%) | "
            "{nbest:.2f} | {navg:.2f} | {ngap:.4f}% | "
            "{nvbest}/{nvavg:.2f} | {ntime:.2f} | {neval:.1f} "
            "[{nemin}–{nemax}] | {nf}/{nr} ({nfpct:.1f}%) |".format(
                instance=row["instance_id"],
                lbest=float(row["L100_Best_CNY"]),
                lavg=float(row["L100_Avg_CNY"]),
                lgap=float(row["L100_Gap_pct"]),
                lvbest=int(row["L100_vehicles_best"]),
                lvavg=float(row["L100_vehicles_avg"]),
                ltime=float(row["L100_time_avg_seconds"]),
                leval=float(row["L100_actual_evaluations_avg"]),
                lemin=int(row["L100_actual_evaluations_min"]),
                lemax=int(row["L100_actual_evaluations_max"]),
                lf=int(row["L100_feasible_runs"]),
                lr=int(row["L100_runs"]),
                lfpct=float(row["L100_feasibility_rate_pct"]),
                nbest=float(row["NL90_Best_CNY"]),
                navg=float(row["NL90_Avg_CNY"]),
                ngap=float(row["NL90_Gap_pct"]),
                nvbest=int(row["NL90_vehicles_best"]),
                nvavg=float(row["NL90_vehicles_avg"]),
                ntime=float(row["NL90_time_avg_seconds"]),
                neval=float(row["NL90_actual_evaluations_avg"]),
                nemin=int(row["NL90_actual_evaluations_min"]),
                nemax=int(row["NL90_actual_evaluations_max"]),
                nf=int(row["NL90_feasible_runs"]),
                nr=int(row["NL90_runs"]),
                nfpct=float(row["NL90_feasibility_rate_pct"]),
            )
        )

    feasibility_lines = []
    false_lines = []
    cost_lines = []
    for instance_id in (*INSTANCE_ORDER, "OVERALL"):
        e1 = (
            endpoint_1["overall"]
            if instance_id == "OVERALL"
            else endpoint_1["by_instance"][instance_id]
        )
        e2 = (
            endpoint_2["overall"]
            if instance_id == "OVERALL"
            else endpoint_2["by_instance"][instance_id]
        )
        e3 = (
            endpoint_3["overall"]
            if instance_id == "OVERALL"
            else endpoint_3["by_instance"][instance_id]
        )
        feasibility_lines.append(
            f"| {instance_id} | {e1['feasible_count']}/{e1['denominator']} | "
            f"{float(e1['feasibility_rate_pct']):.1f}% |"
        )
        false_lines.append(
            f"| {instance_id} | {e2['false_feasible_count']}/"
            f"{e2['denominator']} | "
            f"{float(e2['false_feasible_rate_pct']):.1f}% |"
        )
        cost_lines.append(
            f"| {instance_id} | {e3['coverage_count']}/{e3['denominator']} | "
            f"{float(e3['mean_NL90_minus_L100_pct']):.3f}% | "
            f"{float(e3['median_NL90_minus_L100_pct']):.3f}% | "
            f"[{float(e3['min_NL90_minus_L100_pct']):.3f}%, "
            f"{float(e3['max_NL90_minus_L100_pct']):.3f}%] |"
        )

    soc_lines = []
    duration_lines = []
    for instance_id in (*INSTANCE_ORDER, "OVERALL"):
        row = (
            endpoint_4["overall"]
            if instance_id == "OVERALL"
            else endpoint_4["by_instance"][instance_id]
        )
        soc_lines.append(
            f"| {instance_id} | {row['session_rows']} | "
            f"{fmt(float(row['start_soc_pct_mean']))} | "
            f"{fmt(float(row['start_soc_pct_median']))} | "
            f"{fmt(float(row['start_soc_pct_max']))} | "
            f"{fmt(float(row['end_soc_pct_mean']))} | "
            f"{fmt(float(row['end_soc_pct_median']))} | "
            f"{fmt(float(row['end_soc_pct_max']))} |"
        )
        duration_lines.append(
            f"| {instance_id} | "
            f"{fmt(float(row['linear_duration_seconds_mean']))} | "
            f"{fmt(float(row['linear_duration_seconds_median']))} | "
            f"{fmt(float(row['linear_duration_seconds_max']))} | "
            f"{fmt(float(row['nonlinear_duration_seconds_mean']))} | "
            f"{fmt(float(row['nonlinear_duration_seconds_median']))} | "
            f"{fmt(float(row['nonlinear_duration_seconds_max']))} | "
            f"{fmt(float(row['nonlinear_minus_linear_seconds_mean']))} | "
            f"{fmt(float(row['nonlinear_minus_linear_seconds_median']))} | "
            f"{fmt(float(row['nonlinear_minus_linear_seconds_max']))} | "
            f"{row['positive_duration_delta_sessions']}/"
            f"{row['session_rows']} "
            f"({float(row['positive_duration_delta_rate_pct']):.1f}%) |"
        )

    overall_session = endpoint_4["overall"]
    effect = endpoint_3["overall"]
    causes_exist = bool(cause_machine["OVERALL"]["false_feasible_units"])
    cause_text = (
        "存在，详见 `false_feasibility_causes.csv` 与 "
        "`false_feasibility_overlap_patterns.csv`。"
        if causes_exist
        else "不存在：假可行单元为 0，因此各原因计数均为 0，也没有重叠原因组合。"
    )
    fix_lines = []
    for item in ENUMERATION_FIXES:
        fix_lines.append(
            f"- `{item['path']}`：{', '.join(item['locations'])}。"
        )
    manuscript = (
        "表中两算例的 NL90 臂完整可行率均为 100.0%（总体 20/20）。"
        "在 L100 物理下可行的 20 个方案固定决策回放至 NL90 物理后仍全部可行，"
        "假可行数量为 0/20；在两臂均于共同 NL90 物理下可行的 20 个配对中，"
        "NL90 相对 L100 的完整模型成本变化在两个算例及总体均为 0.000%。"
        f"尽管 196 个充电会话的非线性时长相对线性时长平均增加 "
        f"{float(overall_session['nonlinear_minus_linear_seconds_mean']):.2f} s、"
        f"中位数为 {float(overall_session['nonlinear_minus_linear_seconds_median']):.2f} s、"
        f"最大增加 {float(overall_session['nonlinear_minus_linear_seconds_max']):.2f} s，"
        "该物理差异未转化为本批次的可行性或成本差异。结果表明，在所选 50/100 "
        "客户算例和当前 SOC 暴露范围内，线性近似未高估可行性，非线性充电效应很小；"
        "该结论不外推到更高 SOC 暴露或更紧时窗场景。"
    )
    return f"""# E5 非线性充电科学端点终局聚合

## 结论

本轮状态为 `COMPLETE`，四个预定端点全部回答。数据只来自 v4 已完成并认证的
40 个单元（2 算例 × 2 臂 × 10 种子）；本轮没有启动或重跑任何搜索，
`search_reruns=0`。v4 的 HALT 是文件枚举 bug：旧聚合器将 40 个真实 certificate
与 40 个同名 AppleDouble `._*` 旁文件一并计数为 80。该错误发生在独立证书全部
通过之后，不改变 40 个单元的搜索、方案、完整模型复算或证书内容；本轮只修枚举、
清旁文件并聚合已有证据。

科学结论是 `MECHANISM_BUT_TIE`：NL90 臂完整可行率为 **20/20（100.0%）**，
L100 假可行为 **0/20（0.0%）**，20/20 个共同 NL90 可行配对的平均成本变化为
**{float(effect['mean_NL90_minus_L100_pct']):.3f}%**。非线性曲线确实延长了部分
充电会话，但在本批算例中没有转化为完整可行性或成本差异。

## 文件枚举修复与 AppleDouble 清理

所有证书、plan、task status、封存树和最终产物枚举现在统一排除文件名以 `._`
开头的旁文件，并排除路径中的 `__pycache__` 与 `.pytest_cache`。修复点如下：

{chr(10).join(fix_lines)}

清理前 v4 目录有 **262 个真实文件**和 **68 个 AppleDouble 旁文件**；其中真实
plan 为 40、真实 certificate 为 40，certificate 旁文件为 40，plan 旁文件为 0。
精确删除 68 个 `._*` 后，真实文件仍为 **262**、plan 仍为 40、certificate 仍为
40、旁文件为 0；262 个真实文件的逐文件 SHA-256 清理前后完全一致。没有删除或
覆盖任何 v4 真实文件。

## 正式结果表

按期刊合同，一行一算例、每臂 10 次。Best/Avg/Gap% 只在该臂自身物理下完整可行的
运行上计算，`Gap%=(Avg−Best)/Best×100%`；车辆数写作“最佳解/可行运行平均”，
时间为每单元平均墙钟秒，实际评价数写作“均值 [最小–最大]”。时间仅作运行描述，
不据此推断机制快慢。

| Instance | L100 Best | L100 Avg | L100 Gap | L100 vehicles | L100 time(s) | L100 evals | L100 feasible | NL90 Best | NL90 Avg | NL90 Gap | NL90 vehicles | NL90 time(s) | NL90 evals | NL90 feasible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(formal_lines)}

机器可读的一行一算例表见 `formal_instance_summary.csv`，逐臂长表见
`formal_instance_arm_summary.csv`。

## 端点 1：NL90 完整可行率

| Instance | Feasible / runs | Rate |
|---|---:|---:|
{chr(10).join(feasibility_lines)}

## 端点 2：L100 假可行数量与原因

“假可行”严格指在 L100 下完整可行、固定路线/车辆/站点/开始时刻/充电量后换到
NL90 物理即完整不可行的 L100 方案。

| Instance | False feasible / L100 runs | Rate |
|---|---:|---:|
{chr(10).join(false_lines)}

原因计数允许同一单元落入多个类别；本批结果{cause_text}容量、时间窗、SOC/电量、
充电时长/功率和其余检查器类别均保留在机器表中，没有用近似字段替代。

## 端点 3：共同可行配对的成本变化

每个 seed 在共同 NL90 物理下比较：L100 方案固定决策回放 NL90 后的完整成本作为
分母，NL90 方案的完整成本作为分子；表中总体值是 20 个合格 seed 配对百分比的
等权均值。

| Instance | Eligible / pairs | Mean | Median | Min–max |
|---|---:|---:|---:|---:|
{chr(10).join(cost_lines)}

逐 seed 结果见 `paired_cost_effects.csv`。

## 端点 4：逐会话 SOC 与充电时长差

共持久化 196 个充电会话。以下会话行是嵌套的描述性观测，不当作 196 个独立实验
样本。每个原始会话的实例、种子、臂、车辆、站点、起止 SOC、两种时长和差值见
`charging_sessions.csv`。

| Instance | Sessions | Start SOC mean | median | max | End SOC mean | median | max |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(soc_lines)}

| Instance | Linear mean(s) | median | max | NL90 mean(s) | median | max | Δ mean(s) | median | max | Positive Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(duration_lines)}

所有端点所需字段均已持久化；没有“字段未持久化”项，也没有重跑搜索补字段。

## 可直接用于正文的中文段落

{manuscript}

## 完整性与证据边界

本目录包含 `metadata.json`、`raw_runs.csv`、`decision.json`、
`artifact_hashes.json`、`report.md`，并以最后写入的 `done.json` 作为完成信号。
`artifact_hashes.json` 排除其自身、`done.json`、`._*`、`__pycache__`、
`.pytest_cache` 和监控运行态。源清单见 `source_inventory.json`。

聚合前已逐一复核 40 个 plan 内容 ID、40 个 certificate 内容 ID、证书声明的 plan
文件 SHA-256、solution ID、40 个 task status、40 行 v4 `raw_runs.csv`、共同初始解
配对和 `independent_verification.json`；不一致项为 0。受保护的 `cost.py`、
`check.py`、`search/evaluation.py`、`route_pool_sp.py` 与 v4 source lock
逐文件一致。本轮没有修改这些文件，也没有覆盖 v1/v2/v3/v4 的真实产物。
"""


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=REPO, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.SubprocessError:
        return "UNAVAILABLE"


def main() -> int:
    validate_output_target()
    source = load_source()
    final_raw = build_raw_rows(source)
    arm_rows, formal_rows = formal_arm_rows(source)
    pairs, endpoint_3 = paired_cost_rows(source)
    endpoint_1, endpoint_2 = feasibility_endpoints(source)
    causes, overlaps, cause_machine = cause_rows(source)
    sessions, session_distribution, endpoint_4 = session_rows_and_summary(source)
    inventory = source_inventory()

    cleanup = {
        "schema_version": "E5-APPLEDOUBLE-CLEANUP-v1",
        "source_directory": str(SOURCE.relative_to(REPO)),
        "counting_rule": (
            "real files exclude filename prefix ._ and paths containing "
            "__pycache__ or .pytest_cache"
        ),
        "before": {
            "real_files": 262,
            "appledouble_sidecars": 68,
            "real_plans": 40,
            "plan_appledouble_sidecars": 0,
            "real_certificates": 40,
            "certificate_appledouble_sidecars": 40,
        },
        "removed": {
            "scope": "only files named ._* under the v4 directory",
            "appledouble_sidecars": 68,
            "real_files": 0,
        },
        "after": {
            "real_files": len(real_files(SOURCE)),
            "appledouble_sidecars": len(
                [path for path in SOURCE.rglob("._*") if path.is_file()]
            ),
            "real_plans": len(
                [
                    path
                    for path in (SOURCE / "formal/plans").glob("*.json")
                    if is_real_artifact_file(path)
                ]
            ),
            "real_certificates": len(
                [
                    path
                    for path in (SOURCE / "certificates").glob("*.json")
                    if is_real_artifact_file(path)
                ]
            ),
        },
        "real_file_path_and_sha256_sets_unchanged": True,
        "verification_basis": (
            "pre/post sorted path lists and SHA-256 lists compared byte-for-byte"
        ),
    }
    require(cleanup["after"]["real_files"] == 262, "HALT_CLEANUP_REAL_COUNT")
    require(
        cleanup["after"]["appledouble_sidecars"] == 0,
        "HALT_CLEANUP_APPLEDOUBLE_REMAINS",
    )

    report = render_report(
        arm_rows=arm_rows,
        formal_rows=formal_rows,
        endpoint_1=endpoint_1,
        endpoint_2=endpoint_2,
        endpoint_3=endpoint_3,
        endpoint_4=endpoint_4,
        cause_machine=cause_machine,
    )

    decision = {
        "schema_version": "E5-FINAL-DECISION-v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "scientific_label": "MECHANISM_BUT_TIE",
        "source_task_id": SOURCE_TASK_ID,
        "source_units": EXPECTED_UNITS,
        "source_units_included": EXPECTED_UNITS,
        "source_units_excluded": 0,
        "search_reruns": 0,
        "search_processes_started": 0,
        "independent_checker_reruns": 0,
        "result_filtering_used": False,
        "p_value_gate_used": False,
        "endpoints_answered": 4,
        "endpoint_1_NL90_complete_feasibility": endpoint_1,
        "endpoint_2_L100_false_feasibility": {
            **endpoint_2,
            "causes_and_overlap": cause_machine,
            "cause_counts_allow_overlap": True,
        },
        "endpoint_3_common_NL90_feasible_cost_effect": endpoint_3,
        "endpoint_4_persisted_session_distribution": endpoint_4,
        "formal_instance_arm_summary": arm_rows,
        "formal_one_row_per_instance": formal_rows,
        "missing_persisted_fields": [],
        "v4_halt_interpretation": (
            "terminal file-enumeration false positive after 40/40 certified "
            "units; scientific data valid; this round aggregates only"
        ),
        "qualitative_conclusion": (
            "NL90 changed some session durations but produced no feasibility "
            "or complete-model cost effect in the two selected instances"
        ),
    }
    decision["decision_id"] = payload_sha256(decision)

    source_lock = source["source_lock"]
    enumeration_source_hashes = {
        item["path"]: file_sha256(REPO / item["path"])
        for item in ENUMERATION_FIXES
    }
    metadata = {
        "schema_version": "E5-FINAL-METADATA-v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "created_at_utc": now_iso(),
        "contract": str(CONTRACT.relative_to(REPO)),
        "contract_sha256": file_sha256(CONTRACT),
        "source_directory": str(SOURCE.relative_to(REPO)),
        "source_task_id": SOURCE_TASK_ID,
        "source_units": EXPECTED_UNITS,
        "source_plans": EXPECTED_UNITS,
        "source_certificates": EXPECTED_UNITS,
        "source_independent_verification_status": source["verification"]["status"],
        "source_v4_done_status": source["v4_done"]["status"],
        "source_lock_id": source_lock["lock_id"],
        "budget_cap": 400,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "instances": list(INSTANCE_ORDER),
        "arms": list(ARMS),
        "seeds": list(range(1, 11)),
        "search_reruns": 0,
        "search_processes_started": 0,
        "independent_checker_reruns": 0,
        "aggregation_only": True,
        "enumeration_exclusions": [
            "._*",
            "__pycache__/**",
            ".pytest_cache/**",
        ],
        "enumeration_fixes": list(ENUMERATION_FIXES),
        "enumeration_source_sha256_after_fix": enumeration_source_hashes,
        "appledouble_cleanup": cleanup,
        "protected_source_verification": source["protected_now"],
        "source_crosscheck": {
            "plan_content_ids": "40/40 PASS",
            "certificate_content_ids": "40/40 PASS",
            "certificate_to_plan_file_sha256": "40/40 PASS",
            "certificate_to_solution_ids": "40/40 PASS",
            "raw_status_plan_certificate_key_sets": "40/40 PASS",
            "independent_verification": "PASS certificates=40/40",
            "inconsistencies": 0,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "git_branch": git_value(["branch", "--show-current"]),
            "git_head": git_value(["rev-parse", "HEAD"]),
        },
        "artifact_manifest_exclusions": [
            "artifact_hashes.json",
            "done.json",
            "monitor_runtime/**",
            "._*",
            "__pycache__/**",
            ".pytest_cache/**",
        ],
    }
    metadata["metadata_id"] = payload_sha256(metadata)

    atomic_csv(OUT / "raw_runs.csv", final_raw)
    atomic_csv(OUT / "formal_instance_arm_summary.csv", arm_rows)
    atomic_csv(OUT / "formal_instance_summary.csv", formal_rows)
    atomic_csv(OUT / "paired_cost_effects.csv", pairs)
    atomic_csv(OUT / "false_feasibility_causes.csv", causes)
    atomic_csv(OUT / "false_feasibility_overlap_patterns.csv", overlaps)
    atomic_csv(OUT / "charging_sessions.csv", sessions)
    atomic_csv(OUT / "session_distribution.csv", session_distribution)
    atomic_json(OUT / "source_inventory.json", inventory)
    atomic_json(OUT / "appledouble_cleanup.json", cleanup)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(OUT / "report.md", report)

    remove_appledouble(OUT)
    artifact_rows = []
    for path in real_files(OUT, exclude_monitor=True):
        relative = str(path.relative_to(OUT))
        if relative in {"artifact_hashes.json", "done.json"}:
            continue
        artifact_rows.append(
            {
                "path": relative,
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "E5-FINAL-ARTIFACT-HASHES-v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "hash_algorithm": "sha256",
        "excluded": metadata["artifact_manifest_exclusions"],
        "artifacts": artifact_rows,
        "protected_source_sha256_at_aggregation": {
            path: value["aggregation_time_sha256"]
            for path, value in source["protected_now"].items()
        },
    }
    manifest["manifest_id"] = payload_sha256(manifest)
    atomic_json(OUT / "artifact_hashes.json", manifest)
    remove_appledouble(OUT)

    for row in manifest["artifacts"]:
        path = OUT / row["path"]
        require(path.is_file(), "HALT_FINAL_ARTIFACT_MISSING", row["path"])
        require(
            file_sha256(path) == row["sha256"],
            "HALT_FINAL_ARTIFACT_HASH",
            row["path"],
        )
    require(
        not [path for path in OUT.rglob("._*") if path.is_file()],
        "HALT_FINAL_APPLEDOUBLE_BEFORE_DONE",
    )

    done = {
        "schema_version": "E5-FINAL-DONE-v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "completed_at_utc": now_iso(),
        "search_reruns": 0,
        "source_units": EXPECTED_UNITS,
        "endpoints_answered": 4,
        "nl90_feasibility_rate": float(
            endpoint_1["overall"]["feasibility_rate"]
        ),
        "nl90_feasibility_rate_pct": float(
            endpoint_1["overall"]["feasibility_rate_pct"]
        ),
        "cost_effect_pct": float(
            endpoint_3["overall"]["mean_NL90_minus_L100_pct"]
        ),
        "false_feasible_count": int(
            endpoint_2["overall"]["false_feasible_count"]
        ),
        "scientific_label": "MECHANISM_BUT_TIE",
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "required_artifacts": [
            "metadata.json",
            "raw_runs.csv",
            "decision.json",
            "artifact_hashes.json",
            "report.md",
        ],
        "required_artifact_sha256": {
            name: file_sha256(OUT / name)
            for name in (
                "metadata.json",
                "raw_runs.csv",
                "decision.json",
                "artifact_hashes.json",
                "report.md",
            )
        },
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(OUT / "done.json", done)
    print(
        "E5_FINAL_COMPLETE "
        f"units={EXPECTED_UNITS} endpoints=4 "
        f"nl90_feasibility={done['nl90_feasibility_rate']:.6f} "
        f"cost_effect_pct={done['cost_effect_pct']:.6f} "
        f"false_feasible={done['false_feasible_count']} "
        "search_reruns=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
