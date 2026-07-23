#!/usr/bin/env python3
"""Build the fail-closed GO gate for corrected formal E3 search."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
OUT = BASE / "e3_go_gate_20260723"
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v2_20260723"
)
FULL = CAMPAIGN / "full_gate"
S3 = CAMPAIGN / "representative_gate"
TRAJ = S3 / "trajectories"
S4 = CAMPAIGN / "table4_gate"
S5 = CAMPAIGN / "artifacts"
PUBLIC = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_20260723/"
    "public_p1_no_search_replay"
)
FULL_REPLAY = CAMPAIGN / "full_witness_replay"
RUNTIME = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
SETTLEMENT = (
    REPO
    / "data/ChinaInstances/"
    "china81_spatiotemporal_settlement_authority_v1_20260723"
)
ARM = BASE / "e3_arm_semantics_gate_v4_20260723"
PILOT = BASE / "e3_budget_pilot_v3_20260723"
REGRESSION = BASE / "e3_release_regression_20260723"
ENVIRONMENT = BASE / "e3_environment_authority_20260723"
PARAMETERS = BASE / "e3_parameter_coherence_gate_v2_20260723"
CONTRACT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v4_20260723.json"
)
CONTRACT_BUILDER = BASE / "build_formal_release_contract_v4.py"
FORMAL_RUNNER = BASE / "formal_e3_runner.py"
POST_RUN_SOURCES = (
    BASE / "contract.py",
    BASE / "run_e3_independent_recalc.py",
    BASE / "statistics.py",
    BASE / "charts.py",
    BASE / "tables.py",
)
APPROVAL = (
    REPO
    / "docs/handoff/"
    "model_change_approval_register_20260718.md"
)
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
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["check_id", "status", "observed", "required"],
        )
        writer.writeheader()
        writer.writerows(rows)


def decision(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def add(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    observed: Any,
    required: Any,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "observed": json.dumps(
                observed,
                ensure_ascii=False,
                sort_keys=True,
            )
            if isinstance(observed, (dict, list))
            else str(observed),
            "required": str(required),
        }
    )


def verify_task_manifests() -> dict[str, Any]:
    task_dirs = sorted(
        path
        for path in (FULL / "tasks").iterdir()
        if path.is_dir() and not path.name.startswith("._")
    )
    failures: list[str] = []
    source_hash_sets: set[str] = set()
    for task_dir in task_dirs:
        task_decision = decision(task_dir / "decision.json")
        if task_decision.get("verdict") != "PASS_D6_E2_TASK":
            failures.append(f"{task_dir.name}:decision")
            continue
        metadata = decision(task_dir / "metadata.json")
        for relative, recorded in metadata["source_hashes"].items():
            source = REPO / relative
            if (
                not source.is_file()
                or sha256(source) != recorded
            ):
                failures.append(
                    f"{task_dir.name}:source:{relative}"
                )
        source_hash_sets.add(
            json.dumps(
                metadata["source_hashes"],
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        manifest = decision(task_dir / "artifact_hashes.json")
        for name, expected in manifest["artifacts"].items():
            path = task_dir / name
            if not path.is_file() or sha256(path) != expected:
                failures.append(f"{task_dir.name}:{name}")
    return {
        "task_directory_count": len(task_dirs),
        "manifest_failure_count": len(failures),
        "manifest_failures": failures[:20],
        "source_hash_set_count": len(source_hash_sets),
        "passed": (
            len(task_dirs) == 405
            and not failures
            and len(source_hash_sets) == 1
        ),
    }


def verify_gate_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        return {
            "root": str(root.relative_to(REPO)),
            "entry_count": 0,
            "failures": ["artifact_hashes.json=missing"],
            "passed": False,
        }
    manifest = decision(manifest_path)
    entries = manifest.get("artifacts", manifest.get("files", {}))
    failures: list[str] = []
    for name, expected in entries.items():
        raw = Path(name)
        candidates = (
            [raw]
            if raw.is_absolute()
            else [root / raw, REPO / raw]
        )
        path = next(
            (candidate for candidate in candidates if candidate.is_file()),
            None,
        )
        if path is None:
            failures.append(f"{name}=missing")
        elif sha256(path) != expected:
            failures.append(f"{name}=hash_mismatch")
    return {
        "root": str(root.relative_to(REPO)),
        "entry_count": len(entries),
        "failures": failures[:20],
        "passed": bool(entries) and not failures,
    }


def _resolve_manifest_entry(root: Path, name: str) -> Path:
    raw = Path(name)
    candidates = [raw] if raw.is_absolute() else [root / raw, REPO / raw]
    path = next(
        (candidate for candidate in candidates if candidate.is_file()),
        None,
    )
    if path is None:
        raise FileNotFoundError(f"release artifact is missing: {name}")
    resolved = path.resolve()
    if not resolved.is_relative_to(REPO.resolve()):
        raise ValueError(f"release artifact escapes repository: {name}")
    return resolved


def build_release_evidence_lock(
    manifest_roots: tuple[Path, ...],
    explicit_paths: tuple[Path, ...],
) -> dict[str, Any]:
    """Lock every byte that the GO verdict depends on."""

    locked: dict[str, str] = {}

    def add_path(path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"release evidence missing: {path}")
        if not resolved.is_relative_to(REPO.resolve()):
            raise ValueError(f"release evidence escapes repository: {path}")
        locked[str(resolved.relative_to(REPO.resolve()))] = sha256(
            resolved
        )

    for root in manifest_roots:
        manifest_path = root / "artifact_hashes.json"
        add_path(manifest_path)
        manifest = decision(manifest_path)
        for name in manifest.get(
            "artifacts",
            manifest.get("files", {}),
        ):
            add_path(_resolve_manifest_entry(root, name))
        metadata_path = root / "metadata.json"
        if metadata_path.is_file():
            metadata = decision(metadata_path)
            for relative, recorded in metadata.get(
                "source_hashes",
                {},
            ).items():
                source = _resolve_manifest_entry(REPO, relative)
                if sha256(source) != recorded:
                    raise RuntimeError(
                        f"authority source drift: {relative}"
                    )
                add_path(source)

    task_root = FULL / "tasks"
    for task_dir in sorted(
        path
        for path in task_root.iterdir()
        if path.is_dir() and not path.name.startswith("._")
    ):
        manifest_path = task_dir / "artifact_hashes.json"
        add_path(manifest_path)
        manifest = decision(manifest_path)
        for name in manifest.get("artifacts", {}):
            add_path(_resolve_manifest_entry(task_dir, name))
        metadata = decision(task_dir / "metadata.json")
        for relative, recorded in metadata.get(
            "source_hashes",
            {},
        ).items():
            source = _resolve_manifest_entry(REPO, relative)
            if sha256(source) != recorded:
                raise RuntimeError(
                    f"D6 task source drift: {relative}"
                )
            add_path(source)

    regression_metadata = decision(REGRESSION / "metadata.json")
    for relative, recorded in regression_metadata.get(
        "source_hashes",
        {},
    ).items():
        path = _resolve_manifest_entry(REPO, relative)
        if sha256(path) != recorded:
            raise RuntimeError(
                f"release regression source drift: {relative}"
            )
        add_path(path)

    for path in explicit_paths:
        add_path(path)
    return {
        "schema": "resetp.china-e3-release-evidence-lock.v1",
        "policy": "FAIL_CLOSED_ON_ANY_MISSING_OR_HASH_DRIFT",
        "file_count": len(locked),
        "files": dict(sorted(locked.items())),
    }


def write_gate_package(
    *,
    verdict: dict[str, Any],
    checks: list[dict[str, Any]],
    authorities: tuple[tuple[str, Path, str], ...],
    created_at_utc: str,
) -> None:
    write_json(OUT / "decision.json", verdict)
    write_csv(OUT / "raw_runs.csv", checks)
    source_paths = (
        CONTRACT,
        FORMAL_RUNNER,
        *POST_RUN_SOURCES,
        APPROVAL,
        Path(__file__).resolve(),
    )
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china-e3-go-gate.metadata.v1",
            "created_at_utc": created_at_utc,
            "search_evaluations": 0,
            "release_evidence_lock_sha256": sha256(
                OUT / "release_evidence_lock.json"
            ),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for _, path, _ in authorities
            }
            | {
                str(path.relative_to(REPO)): sha256(path)
                for path in source_paths
            },
        },
    )
    (OUT / "report.md").write_text(
        "# Corrected China81 E3 GO gate\n\n"
        f"Decision: `{verdict['verdict']}`.\n\n"
        f"{len(checks)} release checks were evaluated; "
        f"{len(verdict['failed_checks'])} failed. The gate binds corrected "
        "geography, directed roads, explicit city/date/slot electricity and "
        "carbon, city diesel, finite fleet and charger scenario, executable "
        "paired-arm semantics, the 80-attempt primary budget, time-limited "
        "MIP disclosure, corrected D6 E2/S3--S5 evidence, no-search public P1 "
        "preservation and the classified regression suite. The release "
        "evidence lock is revalidated by the formal runner before every task. "
        "A GO authorizes only formal E3 raw execution; it does not "
        "pre-authorize an effect claim.\n",
        encoding="utf-8",
    )
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )


def verify_full_raw() -> dict[str, Any]:
    with (FULL / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        rows = list(csv.DictReader(handle))
    keys = {(row["instance_id"], int(row["seed"])) for row in rows}
    mip_fields = (
        "mip_status",
        "mip_status_class",
        "mip_message",
        "mip_incumbent_available",
        "mip_objective",
        "mip_dual_bound",
        "mip_gap",
        "mip_node_count",
        "mip_time_limit_seconds",
        "mip_optimality_proven",
    )
    result = {
        "row_count": len(rows),
        "unique_task_count": len(keys),
        "instance_count": len({row["instance_id"] for row in rows}),
        "seed_set": sorted({int(row["seed"]) for row in rows}),
        "all_status_pass": all(row["status"] == "PASS" for row in rows),
        "all_budget_80": all(
            int(row["complete_candidate_attempts"]) == 80 for row in rows
        ),
        "wallclock_safety_trigger_count": sum(
            row["wallclock_safety_triggered"].lower() == "true"
            for row in rows
        ),
        "all_mip_fields_present": all(
            all(row.get(field, "") != "" for field in mip_fields)
            for row in rows
        ),
        "mip_status_classes": sorted(
            {row["mip_status_class"] for row in rows}
        ),
        "all_charging_on_registered_date": all(
            row.get(
                "all_charging_on_registered_date",
                "",
            ).lower()
            == "true"
            for row in rows
        ),
        "all_depot_charging_before_departure": all(
            row.get(
                "all_depot_charging_finishes_before_departure",
                "",
            ).lower()
            == "true"
            for row in rows
        ),
    }
    result["passed"] = (
        result["row_count"] == 405
        and result["unique_task_count"] == 405
        and result["instance_count"] == 81
        and result["seed_set"] == [1, 2, 3, 4, 5]
        and result["all_status_pass"]
        and result["all_budget_80"]
        and result["wallclock_safety_trigger_count"] == 0
        and result["all_mip_fields_present"]
        and result["all_charging_on_registered_date"]
        and result["all_depot_charging_before_departure"]
    )
    return result


def run_formal_preflight() -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = (
        "solver/src:"
        "baselines/algorithm_prototypes/"
        "china81_mechanism_hybrid_20260720"
    )
    environment.update(REQUIRED_THREAD_ENV)
    completed = subprocess.run(
        [sys.executable, str(FORMAL_RUNNER), "preflight"],
        cwd=REPO,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        payload = {
            "status": "HOLD_E3_FORMAL_RUNNER",
            "parse_error": completed.stdout,
        }
    payload["subprocess_exit_code"] = completed.returncode
    return payload


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stale_preflight = OUT / "formal_runner_preflight.json"
    if stale_preflight.is_file():
        stale_preflight.unlink()
    checks: list[dict[str, Any]] = []
    authorities = (
        (
            "formal_environment",
            ENVIRONMENT / "decision.json",
            "PASS_E3_FORMAL_ENVIRONMENT_AUTHORITY",
        ),
        (
            "runtime_authority",
            RUNTIME / "decision.json",
            "PASS_CITY_DATE_SLOT_PARAMETER_AUTHORITY",
        ),
        (
            "parameter_coherence",
            PARAMETERS / "decision.json",
            "PASS_E3_PARAMETER_COHERENCE_ZERO_SEARCH",
        ),
        (
            "finite_fleet_authority",
            FLEET / "decision.json",
            "PASS_FINITE_FLEET_ZERO_SEARCH_WITNESSES",
        ),
        (
            "settlement_authority",
            SETTLEMENT / "decision.json",
            "PASS_FAIL_CLOSED_SPATIOTEMPORAL_SETTLEMENT_AUTHORITY",
        ),
        (
            "e3_arm_semantics",
            ARM / "decision.json",
            "PASS_E3_ARM_SEMANTICS_ZERO_SEARCH",
        ),
        (
            "result_blind_budget",
            PILOT / "decision.json",
            "PASS_RESULT_BLIND_BUDGET_80",
        ),
        (
            "d6_corrected_private_e2",
            FULL / "decision.json",
            "PASS_D6_CORRECTED_CHINA81_E2_RAW",
        ),
        (
            "d6_corrected_s3",
            S3 / "decision.json",
            "PASS_D6_CORRECTED_S3_REPRESENTATIVE",
        ),
        (
            "d6_corrected_trajectories",
            TRAJ / "decision.json",
            "PASS_D6_CORRECTED_S3_TRAJECTORIES",
        ),
        (
            "d6_corrected_s4",
            S4 / "decision.json",
            "PASS_D6_CORRECTED_S4_ROUTE_DETAIL",
        ),
        (
            "d6_corrected_s5",
            S5 / "decision.json",
            "PASS_D6_CORRECTED_S5_ARTIFACTS",
        ),
        (
            "public_p1_no_search",
            PUBLIC / "decision.json",
            "PASS_PUBLIC_P1_PRESERVATION_NO_SEARCH",
        ),
        (
            "d6_full_witness_replay",
            FULL_REPLAY / "decision.json",
            "PASS_D6_CORRECTED_FULL_WITNESS_REPLAY",
        ),
        (
            "release_regression",
            REGRESSION / "decision.json",
            "PASS_E3_RELEASE_REGRESSION_WITH_REGISTERED_HISTORICAL_BOUNDARIES",
        ),
    )
    for check_id, path, expected in authorities:
        payload = decision(path)
        observed = payload.get("verdict")
        add(checks, check_id, observed == expected, observed, expected)
    manifest_roots = (
        ENVIRONMENT,
        RUNTIME,
        FLEET,
        SETTLEMENT,
        PARAMETERS,
        ARM,
        PILOT,
        FULL,
        S3,
        TRAJ,
        S4,
        S5,
        PUBLIC,
        FULL_REPLAY,
        REGRESSION,
    )
    manifest_results = [
        verify_gate_manifest(root) for root in manifest_roots
    ]
    add(
        checks,
        "all_release_gate_artifact_manifests",
        all(item["passed"] for item in manifest_results),
        manifest_results,
        "all authority and corrected D6/S3-S5 manifests verify",
    )
    contract = decision(CONTRACT)
    add(
        checks,
        "formal_release_contract_frozen",
        contract.get("formal_search_allowed") is False
        and contract.get("formal_execution", {}).get(
            "complete_candidate_budget"
        )
        == 80,
        {
            "formal_search_allowed": contract.get(
                "formal_search_allowed"
            ),
            "complete_candidate_budget": contract.get(
                "formal_execution",
                {},
            ).get(
                "complete_candidate_budget"
            ),
        },
        "pre-GO false and budget 80",
    )
    approval_text = APPROVAL.read_text(encoding="utf-8")
    add(
        checks,
        "d1_d6_approval_registered",
        "CHINA-E3-FORMAL-RELEASE-001" in approval_text,
        "CHINA-E3-FORMAL-RELEASE-001"
        in approval_text,
        True,
    )
    full_raw = verify_full_raw()
    add(
        checks,
        "d6_full_raw_integrity",
        full_raw["passed"],
        full_raw,
        "405 unique PASS rows; budget 80; no safety trigger; MIP fields",
    )
    manifests = verify_task_manifests()
    add(
        checks,
        "d6_task_manifest_integrity",
        manifests["passed"],
        manifests,
        "405 valid task manifests and one frozen source-hash set",
    )
    replay_decision = decision(FULL_REPLAY / "decision.json")
    add(
        checks,
        "d6_full_replay_semantics",
        (
            replay_decision.get("search_executions") == 0
            and replay_decision.get("solution_count") == 1620
            and replay_decision.get(
                "instance_input_manifest_count"
            )
            == 81
            and replay_decision.get("all_costs_reproduced") is True
            and replay_decision.get("all_emissions_reproduced")
            is True
            and replay_decision.get("all_full_model_feasible")
            is True
            and replay_decision.get(
                "all_static_charge_day_offsets_zero"
            )
            is True
            and replay_decision.get(
                "all_static_charging_within_registered_day"
            )
            is True
            and replay_decision.get(
                "all_depot_charging_finishes_before_departure"
            )
            is True
            and replay_decision.get(
                "all_depot_fleet_caps_respected"
            )
            is True
        ),
        replay_decision,
        (
            "zero search; 1620 feasible exact replays; 81 input-byte "
            "manifests; all charging stays on 2025-02-12 and depot "
            "charging finishes before route departure; "
            "all depot-by-powertrain physical fleet caps hold"
        ),
    )
    replay_metadata = decision(FULL_REPLAY / "metadata.json")
    replay_source_binding = {
        relative: {
            "recorded": recorded,
            "current": (
                sha256(REPO / relative)
                if (REPO / relative).is_file()
                else None
            ),
        }
        for relative, recorded in replay_metadata.get(
            "source_hashes",
            {},
        ).items()
    }
    add(
        checks,
        "d6_full_replay_sources_current",
        bool(replay_source_binding)
        and all(
            values["recorded"] == values["current"]
            for values in replay_source_binding.values()
        ),
        replay_source_binding,
        "all independent replay sources still equal their recorded hashes",
    )
    regression_metadata = decision(REGRESSION / "metadata.json")
    regression_sources = regression_metadata.get(
        "source_hashes",
        {},
    )
    post_run_source_binding = {}
    for relative, recorded in regression_sources.items():
        path = REPO / relative
        post_run_source_binding[relative] = {
            "current": sha256(path) if path.is_file() else None,
            "regression": recorded,
        }
    add(
        checks,
        "all_release_regression_sources_current",
        bool(post_run_source_binding)
        and all(
            values["current"] == values["regression"]
            for values in post_run_source_binding.values()
        ),
        post_run_source_binding,
        "all current hashes equal release-regression source hashes",
    )
    settlement_decision = decision(SETTLEMENT / "decision.json")
    with (
        SETTLEMENT / "city_date_slot_parameter_binding.csv"
    ).open(newline="", encoding="utf-8-sig") as handle:
        settlement_rows = list(csv.DictReader(handle))
    expected_cities = {
        "beijing",
        "tianjin",
        "shijiazhuang",
        "guangzhou",
        "shenzhen",
        "foshan",
        "dongguan",
        "chongqing",
        "chengdu",
    }
    observed_cities = {row["city"] for row in settlement_rows}
    add(
        checks,
        "joint_spatiotemporal_key",
        (
            settlement_decision.get("scenario_date") == "2025-02-12"
            and settlement_decision.get("active_city_count") == 9
            and observed_cities == expected_cities
            and {
                row["scenario_date"] for row in settlement_rows
            }
            == {"2025-02-12"}
            and {
                row["joint_key_status"] for row in settlement_rows
            }
            == {"PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY"}
            and settlement_decision.get("city_group_fallback_allowed")
            is False
            and settlement_decision.get("missing_or_mixed_key_policy")
            == "FAIL_CLOSED"
        ),
        {
            "date": settlement_decision.get("scenario_date"),
            "cities": sorted(observed_cities),
            "binding_rows": len(settlement_rows),
            "fallback": settlement_decision.get(
                "city_group_fallback_allowed"
            ),
            "missing_key": settlement_decision.get(
                "missing_or_mixed_key_policy"
            ),
        },
        "2025-02-12; 9 cities; no fallback; fail closed",
    )
    preflight_ready_without_go = all(
        row["status"] == "PASS" for row in checks
    )
    release_lock = build_release_evidence_lock(
        manifest_roots,
        (
            CONTRACT,
            CONTRACT_BUILDER,
            FORMAL_RUNNER,
            *POST_RUN_SOURCES,
            APPROVAL,
            Path(__file__).resolve(),
        ),
    )
    write_json(OUT / "release_evidence_lock.json", release_lock)
    release_lock_sha256 = sha256(
        OUT / "release_evidence_lock.json"
    )
    created_at_utc = datetime.now(UTC).isoformat()
    provisional = {
        "schema": "resetp.china-e3-go-gate.decision.v1",
        "verdict": (
            "GO_E3_FORMAL_SEARCH"
            if preflight_ready_without_go
            else "HOLD_E3_FORMAL_SEARCH"
        ),
        "formal_search_allowed": preflight_ready_without_go,
        "created_at_utc": created_at_utc,
        "approval_id": "CHINA-E3-FORMAL-RELEASE-001",
        "release_evidence_lock_sha256": release_lock_sha256,
        "release_evidence_file_count": release_lock["file_count"],
        "check_count": len(checks),
        "failed_checks": [
            row["check_id"]
            for row in checks
            if row["status"] != "PASS"
        ],
        "complete_candidate_budget_per_task": 80,
        "wallclock_role": "safety cap only",
        "scenario_date": "2025-02-12",
        "joint_parameter_key": (
            "instance/node -> explicit city/price area/carbon column/diesel "
            "zone -> 2025-02-12 -> half-hour slot"
        ),
        "public_p1_boundary": (
            "280-row ledger replayed without search; P1 route witnesses were "
            "not historically persisted and were not fabricated"
        ),
        "registered_red_boundaries_retained": True,
        "scientific_effect_claim_allowed": False,
        "next_authorized_action": (
            "run formal E3 paired raw campaign only; statistics and claim "
            "audit remain separate later gates"
        ),
    }
    write_gate_package(
        verdict=provisional,
        checks=checks,
        authorities=authorities,
        created_at_utc=created_at_utc,
    )
    formal_preflight = run_formal_preflight()
    write_json(OUT / "formal_runner_preflight.json", formal_preflight)
    runner_ready = (
        formal_preflight.get("status")
        == "PASS_E3_FORMAL_RUNNER_READY"
        and formal_preflight.get("formal_search_allowed") is True
        and formal_preflight.get("subprocess_exit_code") == 0
    )
    add(
        checks,
        "formal_runner_preflight_after_go",
        runner_ready,
        formal_preflight,
        "PASS_E3_FORMAL_RUNNER_READY",
    )
    final_pass = all(row["status"] == "PASS" for row in checks)
    final = {
        **provisional,
        "verdict": (
            "GO_E3_FORMAL_SEARCH"
            if final_pass
            else "HOLD_E3_FORMAL_SEARCH"
        ),
        "formal_search_allowed": final_pass,
        "check_count": len(checks),
        "failed_checks": [
            row["check_id"]
            for row in checks
            if row["status"] != "PASS"
        ],
        "formal_runner_preflight": formal_preflight,
    }
    write_gate_package(
        verdict=final,
        checks=checks,
        authorities=authorities,
        created_at_utc=created_at_utc,
    )
    print(json.dumps(final, ensure_ascii=False, sort_keys=True))
    return 0 if final_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
