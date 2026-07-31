#!/usr/bin/env python3
"""Run and close the preregistered E5 fast-charge exploratory probe."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
import statistics

PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
for path in (SCRIPT_DIR, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import e5_fastcharge_config_20260731 as cfg
import run_e5_nonlinear_v4_20260730 as v4
from setp_solver.charging_curve import L100_CONTROL

OUT = cfg.OUT
TASK_ID = cfg.TASK_ID
EXCLUDED_DIRS = frozenset({"__pycache__", ".pytest_cache"})
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO / "solver/src/setp_solver/profit.py",
    PROTOTYPE / "route_pool_sp.py",
    PROTOTYPE / "epochal_hgs.py",
)
SOURCE_FILES = (
    Path(__file__).resolve(),
    cfg.CHECKER,
    REPO / "baselines/china_e3_e7/e5_fastcharge_config_20260731.py",
    cfg.PREREG,
    REPO / "baselines/china_e3_e7/run_e5_nonlinear_v4_20260730.py",
    REPO / "baselines/china_e3_e7/run_e5_nonlinear_v3_20260730.py",
    REPO / "baselines/china_e3_e7/run_e5_nonlinear_v2_20260730.py",
    REPO / "baselines/china_e3_e7/check_e5_nonlinear_20260729.py",
    REPO / "docs/handoff/experiment_contract_v2_journal_aligned_20260730.md",
    REPO / "docs/handoff/china_parameter_lock_and_v2_freeze_contract_20260718.md",
    REPO / "docs/handoff/china_public_charger_parameter_evidence_20260718.md",
    REPO / "data/ChinaPrices/china_2025_02_tariff_register_v2.json",
    REPO / "data/ChinaPrices/china_2025_02_tariff_register_v3.json",
    REPO
    / "data/ChinaPrices/official_snapshots/china_2025_02_nine_city"
    / "guangdong_2025_02_api.json",
    REPO
    / "data/ChinaPrices/official_snapshots/china_2025_02_nine_city"
    / "shenzhen_2025_02_api.json",
    REPO
    / "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723"
    / "effect_thresholds.json",
    REPO / "tmp/e5_literature_curve/montoya-et-al-2017.zip",
    Path(
        "/Users/zhouleixishu/Zotero/storage/72THJGSQ/"
        "Montoya 等 _ 2017 _ The electric vehicle routing problem "
        "with nonlinear charging function.pdf"
    ),
    *PROTECTED,
)


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


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(payload))
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def append_progress(payload: dict[str, Any]) -> None:
    path = OUT / "progress.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO))
    except ValueError:
        return f"EXTERNAL::{resolved}"


def is_real_file(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.startswith("._")
        and not any(part in EXCLUDED_DIRS for part in path.parts)
    )


def source_hashes() -> dict[str, str]:
    missing = [path for path in SOURCE_FILES if not path.is_file()]
    if missing:
        raise RuntimeError(f"HALT_E5_FAST_MISSING_SOURCE:{missing}")
    return {relative(path): file_sha256(path) for path in SOURCE_FILES}


def protected_hashes() -> dict[str, str]:
    return {relative(path): file_sha256(path) for path in PROTECTED}


def old_e5_tree_hashes() -> dict[str, str]:
    rows: dict[str, str] = {}
    parent = REPO / "baselines/china_e3_e7"
    for root in sorted(parent.glob("e5_*")):
        if not root.is_dir() or root.resolve() == OUT.resolve():
            continue
        for path in sorted(root.rglob("*")):
            if is_real_file(path) and "monitor_runtime" not in path.parts:
                rows[str(path.relative_to(REPO))] = file_sha256(path)
    if not rows:
        raise RuntimeError("HALT_E5_FAST_OLD_E5_EVIDENCE_MISSING")
    return rows


def input_hashes() -> dict[str, str]:
    base = v4.base
    rows: dict[str, str] = {}
    for spec in cfg.INSTANCE_SPECS:
        bundle = base.load_china81_bundle(
            REPO, str(spec["instance_id"])
        )
        for path, digest in base.input_hashes(bundle).items():
            if path in rows and rows[path] != digest:
                raise RuntimeError(
                    f"HALT_E5_FAST_INPUT_HASH_CONFLICT:{path}"
                )
            rows[path] = digest
    return dict(sorted(rows.items()))


def configure_v4() -> None:
    """Bind the verified v4 search executor to the frozen fast scenario."""

    base = v4.base
    v4.TASK_ID = TASK_ID
    v4.OUT = OUT
    base.TASK_ID = TASK_ID
    base.OUT = OUT
    base.ARMS = cfg.ARMS
    base.NL90_MILD = cfg.FAST_CURVE
    base.curve_bundle = cfg.apply_fastcharge_overlay
    base.atomic_json = atomic_json
    base.atomic_csv = atomic_csv


def environment_snapshot(workers: int) -> dict[str, Any]:
    if workers != 1:
        raise RuntimeError("HALT_E5_FAST_REQUIRES_ONE_WORKER")
    wrong = {
        name: os.environ.get(name)
        for name, expected in cfg.THREAD_ENV.items()
        if os.environ.get(name) != expected
    }
    if wrong:
        raise RuntimeError(
            f"HALT_E5_FAST_THREAD_ENV_NOT_FROZEN:{wrong}"
        )
    pyvrp_version = version("pyvrp")
    if pyvrp_version != "0.12.2":
        raise RuntimeError(
            f"HALT_E5_FAST_PYVRP_VERSION:{pyvrp_version}"
        )
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "pyvrp": pyvrp_version,
        "scipy": version("scipy"),
        "workers": workers,
        "thread_environment": dict(cfg.THREAD_ENV),
    }


def prepare(workers: int) -> None:
    configure_v4()
    if (OUT / "done.json").exists():
        raise RuntimeError("HALT_E5_FAST_ALREADY_TERMINAL")
    prereg = json.loads(cfg.PREREG.read_text(encoding="utf-8"))
    if not prereg["decision_timing"]["parameters_frozen_before_new_search"]:
        raise RuntimeError("HALT_E5_FAST_PREREG_NOT_FROZEN")
    if prereg["decision_timing"]["new_fastcharge_search_started"]:
        raise RuntimeError("HALT_E5_FAST_PREREG_TIMING_INVALID")
    environment = environment_snapshot(workers)
    lock = {
        "schema_version": "E5-FASTCHARGE-SOURCE-LOCK-v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "pre_registration_sha256": file_sha256(cfg.PREREG),
        "source_sha256": source_hashes(),
        "protected_source_sha256": protected_hashes(),
        "input_sha256": input_hashes(),
        "old_e5_file_sha256": old_e5_tree_hashes(),
    }
    lock["lock_id"] = payload_sha256(lock)
    task_card = {
        "schema_version": "E5-FASTCHARGE-TASK-CARD-v1",
        "task_id": TASK_ID,
        "study_status": "EXPLORATORY_PROBE_NOT_FOR_MAIN_TEXT",
        "prepared_at_utc": now_iso(),
        "pre_registration": relative(cfg.PREREG),
        "pre_registration_sha256": file_sha256(cfg.PREREG),
        "instances": [
            {
                "instance_id": spec["instance_id"],
                "sample_role": spec["sample_role"],
                "seeds": list(spec["seeds"]),
            }
            for spec in cfg.INSTANCE_SPECS
        ],
        "arms": {
            L100_CONTROL.curve_id: asdict(L100_CONTROL),
            cfg.FAST_CURVE.curve_id: asdict(cfg.FAST_CURVE),
        },
        "depot_charge_power_kw": cfg.DEPOT_POWER_KW,
        "public_charge_power_kw": cfg.PUBLIC_POWER_KW,
        "budget_cap": cfg.BUDGET_CAP,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "formal_expected_units": 40,
        "formal_expected_pairs": 20,
        "common_initial_solution": True,
        "common_seed_within_pair": True,
        "environment": environment,
    }
    atomic_json(OUT / "source_lock.json", lock)
    atomic_json(OUT / "task_card.json", task_card)
    print(
        f"PREPARED task={TASK_ID} prereg_sha256="
        f"{lock['pre_registration_sha256']} old_files="
        f"{len(lock['old_e5_file_sha256'])}",
        flush=True,
    )


def verify_source_lock() -> dict[str, Any]:
    lock_path = OUT / "source_lock.json"
    if not lock_path.is_file():
        raise RuntimeError("HALT_E5_FAST_SOURCE_LOCK_MISSING")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    checks = (
        ("PREREG", file_sha256(cfg.PREREG), lock["pre_registration_sha256"]),
        ("SOURCE", source_hashes(), lock["source_sha256"]),
        ("PROTECTED", protected_hashes(), lock["protected_source_sha256"]),
        ("INPUT", input_hashes(), lock["input_sha256"]),
        ("OLD_E5", old_e5_tree_hashes(), lock["old_e5_file_sha256"]),
    )
    for label, current, expected in checks:
        if current != expected:
            raise RuntimeError(f"HALT_E5_FAST_{label}_CHANGED")
    return lock


def spec_for(instance_id: str, seed: int, arm: str) -> dict[str, Any]:
    matches = [
        row for row in cfg.INSTANCE_SPECS
        if row["instance_id"] == instance_id
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown fast-charge instance: {instance_id}")
    source = matches[0]
    if seed not in source["seeds"] or arm not in cfg.ARMS:
        raise ValueError(f"invalid unit: {instance_id}/{seed}/{arm}")
    return {
        "instance_id": instance_id,
        "sample_role": source["sample_role"],
        "seed": seed,
        "arm": arm,
    }


def task_stem(spec: dict[str, Any]) -> str:
    return (
        f"{spec['instance_id']}__seed-{int(spec['seed']):02d}"
        f"__{spec['arm']}"
    )


def run_internal_unit(
    instance_id: str,
    seed: int,
    arm: str,
    lock_id: str,
) -> int:
    configure_v4()
    lock = verify_source_lock()
    if lock["lock_id"] != lock_id:
        raise RuntimeError("HALT_E5_FAST_LOCK_ID_MISMATCH")
    payload = {
        "spec": spec_for(instance_id, seed, arm),
        "phase": "formal",
        "budget": cfg.BUDGET_CAP,
        "lock_id": lock_id,
        "output_root": str(OUT),
    }
    row = v4.run_search_unit(payload)
    if row["status"] != "PASS":
        raise RuntimeError(
            f"{row['status']}:{instance_id}:{seed}:{arm}"
        )
    return 0


def run_formal(instance_id: str, workers: int) -> None:
    configure_v4()
    environment_snapshot(workers)
    lock = verify_source_lock()
    matches = [
        row for row in cfg.INSTANCE_SPECS
        if row["instance_id"] == instance_id
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown formal instance: {instance_id}")
    specs = [
        spec_for(instance_id, seed, arm)
        for seed in matches[0]["seeds"]
        for arm in cfg.ARMS
    ]
    for completed, spec in enumerate(specs, start=1):
        command = [
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "_unit",
            "--instance-id",
            instance_id,
            "--seed",
            str(spec["seed"]),
            "--arm",
            str(spec["arm"]),
            "--lock-id",
            str(lock["lock_id"]),
        ]
        subprocess.run(
            command,
            cwd=REPO,
            env={**os.environ, **cfg.THREAD_ENV},
            check=True,
        )
        status_path = (
            OUT / "formal/task_status" / f"{task_stem(spec)}.json"
        )
        status = json.loads(status_path.read_text(encoding="utf-8"))
        append_progress(
            {
                "event": "UNIT_COMPLETE",
                "recorded_at_utc": now_iso(),
                "instance_id": instance_id,
                "seed": int(spec["seed"]),
                "arm": spec["arm"],
                "status": status["status"],
                "complete_candidate_evaluations_consumed": status[
                    "complete_candidate_evaluations_consumed"
                ],
                "termination_reason": status["termination_reason"],
                "elapsed_wall_seconds": status["elapsed_wall_seconds"],
                "phase_progress_completed": completed,
                "phase_progress_total": len(specs),
            }
        )
        print(
            "UNIT_COMPLETE "
            f"instance={instance_id} seed={int(spec['seed'])} "
            f"arm={spec['arm']} status={status['status']} "
            f"consumed={status['complete_candidate_evaluations_consumed']}"
            f"/{cfg.BUDGET_CAP} "
            f"termination={status['termination_reason']} "
            f"elapsed_seconds={float(status['elapsed_wall_seconds']):.3f} "
            f"progress={completed}/{len(specs)}",
            flush=True,
        )
    marker = {
        "schema_version": "E5-FASTCHARGE-PHASE-COMPLETE-v1",
        "task_id": TASK_ID,
        "instance_id": instance_id,
        "status": "PASS",
        "completed_at_utc": now_iso(),
        "units": len(specs),
        "source_lock_id": lock["lock_id"],
    }
    scale = "50c" if "50c-" in instance_id else "100c"
    atomic_json(OUT / f"phase_{scale}_complete.json", marker)
    append_progress(
        {
            "event": "PHASE_COMPLETE",
            "recorded_at_utc": now_iso(),
            **marker,
        }
    )
    print(
        f"PHASE_COMPLETE instance={instance_id} units={len(specs)}",
        flush=True,
    )


def formal_statuses() -> list[dict[str, Any]]:
    paths = sorted(
        path
        for path in (OUT / "formal/task_status").glob("*.json")
        if is_real_file(path)
    )
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if len(rows) != 40:
        raise RuntimeError(
            f"HALT_E5_FAST_STATUS_DENOMINATOR:{len(rows)}!=40"
        )
    if any(
        row.get("status") != "PASS"
        or int(row["complete_candidate_budget_cap"]) != cfg.BUDGET_CAP
        for row in rows
    ):
        raise RuntimeError("HALT_E5_FAST_NONPASS_STATUS")
    return rows


def load_certificates() -> list[dict[str, Any]]:
    paths = sorted(
        path
        for path in (OUT / "certificates").glob("*.json")
        if is_real_file(path)
    )
    if len(paths) != 40:
        raise RuntimeError(
            f"HALT_E5_FAST_CERTIFICATE_DENOMINATOR:{len(paths)}!=40"
        )
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if any(row.get("certificate_status") != "PASS" for row in rows):
        raise RuntimeError("HALT_E5_FAST_CERTIFICATE_FAILED")
    return rows


def paired_rows(certs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for cert in certs:
        groups.setdefault(
            (str(cert["instance_id"]), int(cert["seed"])), {}
        )[str(cert["arm"])] = cert
    rows: list[dict[str, Any]] = []
    for (instance_id, seed), pair in sorted(groups.items()):
        if set(pair) != set(cfg.ARMS):
            raise RuntimeError(
                f"HALT_E5_FAST_PAIR_ARMS:{instance_id}:{seed}"
            )
        linear = pair[L100_CONTROL.curve_id]
        nonlinear = pair[cfg.FAST_CURVE.curve_id]
        both = bool(
            linear["nonlinear_feasible"]
            and nonlinear["nonlinear_feasible"]
        )
        left = linear["common_nonlinear_full_model_total_cost_cny"]
        right = nonlinear["common_nonlinear_full_model_total_cost_cny"]
        rows.append(
            {
                "instance_id": instance_id,
                "seed": seed,
                "both_feasible_under_fast_nonlinear": int(both),
                "L100_plan_replayed_fast_nonlinear_cost_cny": (
                    left if both else "NA_NOT_BOTH_FEASIBLE"
                ),
                "fast_nonlinear_plan_cost_cny": (
                    right if both else "NA_NOT_BOTH_FEASIBLE"
                ),
                "fast_nonlinear_minus_L100_cost_cny": (
                    float(right) - float(left)
                    if both else "NA_NOT_BOTH_FEASIBLE"
                ),
                "fast_nonlinear_minus_L100_cost_pct": (
                    100.0 * (float(right) - float(left)) / float(left)
                    if both else "NA_NOT_BOTH_FEASIBLE"
                ),
            }
        )
    if len(rows) != 20:
        raise RuntimeError("HALT_E5_FAST_PAIR_DENOMINATOR")
    return rows


def summary_stats(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def build_endpoints(
    certs: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    nonlinear = [
        row for row in certs if row["arm"] == cfg.FAST_CURVE.curve_id
    ]
    linear = [
        row for row in certs if row["arm"] == L100_CONTROL.curve_id
    ]
    false = [
        row for row in linear if row["linear_plan_false_feasible"]
    ]
    causes: dict[str, dict[str, int]] = {}
    for cert in false:
        for category, count in cert[
            "nonlinear_infeasibility_categories"
        ].items():
            entry = causes.setdefault(
                category, {"affected_units": 0, "violations": 0}
            )
            entry["affected_units"] += 1
            entry["violations"] += int(count)
    common = [
        row for row in pairs
        if row["both_feasible_under_fast_nonlinear"]
    ]
    effects = [
        float(row["fast_nonlinear_minus_L100_cost_pct"])
        for row in common
    ]
    deltas = [
        float(row["nonlinear_minus_linear_seconds"])
        for row in sessions
    ]
    exposed = [
        row for row in sessions if int(row["entered_taper_zone"]) == 1
    ]
    by_instance: dict[str, Any] = {}
    for spec in cfg.INSTANCE_SPECS:
        instance_id = str(spec["instance_id"])
        inst_nl = [
            row for row in nonlinear
            if row["instance_id"] == instance_id
        ]
        inst_linear = [
            row for row in linear if row["instance_id"] == instance_id
        ]
        inst_false = [
            row for row in inst_linear
            if row["linear_plan_false_feasible"]
        ]
        inst_pairs = [
            row for row in pairs if row["instance_id"] == instance_id
        ]
        inst_common = [
            row for row in inst_pairs
            if row["both_feasible_under_fast_nonlinear"]
        ]
        inst_effects = [
            float(row["fast_nonlinear_minus_L100_cost_pct"])
            for row in inst_common
        ]
        inst_sessions = [
            row for row in sessions
            if row["instance_id"] == instance_id
        ]
        inst_exposed = [
            row for row in inst_sessions
            if int(row["entered_taper_zone"]) == 1
        ]
        by_instance[instance_id] = {
            "fast_nonlinear_feasible_count": sum(
                int(row["planning_physics_feasible"]) for row in inst_nl
            ),
            "fast_nonlinear_denominator": len(inst_nl),
            "L100_false_feasible_count": len(inst_false),
            "L100_denominator": len(inst_linear),
            "common_feasible_pairs": len(inst_common),
            "pair_denominator": len(inst_pairs),
            "cost_effect_pct": summary_stats(inst_effects),
            "session_rows": len(inst_sessions),
            "taper_exposed_sessions": len(inst_exposed),
            "taper_exposed_session_pct": (
                100.0 * len(inst_exposed) / len(inst_sessions)
                if inst_sessions else None
            ),
        }
    return {
        "endpoint_1_fast_nonlinear_complete_feasibility": {
            "feasible_count": sum(
                int(row["planning_physics_feasible"]) for row in nonlinear
            ),
            "denominator": len(nonlinear),
            "feasibility_rate": (
                sum(
                    int(row["planning_physics_feasible"])
                    for row in nonlinear
                )
                / len(nonlinear)
            ),
        },
        "endpoint_2_L100_false_feasibility": {
            "false_feasible_count": len(false),
            "denominator": len(linear),
            "false_feasible_rate": len(false) / len(linear),
            "causes_allow_overlap": causes,
        },
        "endpoint_3_common_feasible_cost_effect": {
            "coverage_count": len(common),
            "denominator": len(pairs),
            "formula": (
                "100 * (fast nonlinear plan cost under common fast "
                "nonlinear physics - fast L100 plan replay cost under "
                "common fast nonlinear physics) / fast L100 replay cost"
            ),
            "fast_nonlinear_minus_L100_pct": summary_stats(effects),
        },
        "endpoint_4_sessions": {
            "session_rows": len(sessions),
            "taper_exposed_sessions": len(exposed),
            "actual_exposed_session_pct": (
                100.0 * len(exposed) / len(sessions)
            ),
            "nonlinear_minus_linear_seconds": summary_stats(deltas),
            "unit_boundary": (
                "session rows are nested descriptive observations, "
                "not independent experimental replicates"
            ),
        },
        "by_instance": by_instance,
    }


def formal_table(
    certs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    status_by_key = {
        (row["instance_id"], int(row["seed"]), row["arm"]): row
        for row in statuses
    }
    rows: list[dict[str, Any]] = []
    for spec in cfg.INSTANCE_SPECS:
        instance_id = str(spec["instance_id"])
        for arm in cfg.ARMS:
            subset = [
                row for row in certs
                if row["instance_id"] == instance_id
                and row["arm"] == arm
            ]
            feasible = [
                row for row in subset
                if row["planning_physics_feasible"]
            ]
            costs = [
                float(row["planning_full_model_total_cost_cny"])
                for row in feasible
            ]
            times = [
                float(
                    status_by_key[
                        (instance_id, int(row["seed"]), arm)
                    ]["elapsed_wall_seconds"]
                )
                for row in subset
            ]
            consumed = [
                int(
                    status_by_key[
                        (instance_id, int(row["seed"]), arm)
                    ]["complete_candidate_evaluations_consumed"]
                )
                for row in subset
            ]
            rows.append(
                {
                    "instance_id": instance_id,
                    "sample_role": spec["sample_role"],
                    "arm": arm,
                    "feasible_runs": len(feasible),
                    "runs": len(subset),
                    "Best_CNY": min(costs) if costs else "NA_INFEASIBLE",
                    "Avg_CNY": (
                        statistics.fmean(costs)
                        if costs else "NA_INFEASIBLE"
                    ),
                    "Gap_pct": (
                        100.0
                        * (statistics.fmean(costs) - min(costs))
                        / min(costs)
                        if costs else "NA_INFEASIBLE"
                    ),
                    "time_avg_seconds": statistics.fmean(times),
                    "actual_evaluations_min": min(consumed),
                    "actual_evaluations_avg": statistics.fmean(consumed),
                    "actual_evaluations_max": max(consumed),
                }
            )
    return rows


def render_report(
    endpoints: dict[str, Any],
    table: list[dict[str, Any]],
    effect_observed: bool,
    promotion_items: list[str],
) -> str:
    def fmt(value: Any, digits: int = 3) -> str:
        if value is None or isinstance(value, str):
            return "NA" if value is None else value
        return f"{float(value):.{digits}f}"

    e1 = endpoints["endpoint_1_fast_nonlinear_complete_feasibility"]
    e2 = endpoints["endpoint_2_L100_false_feasibility"]
    e3 = endpoints["endpoint_3_common_feasible_cost_effect"]
    e4 = endpoints["endpoint_4_sessions"]
    effect = e3["fast_nonlinear_minus_L100_pct"]["mean"]
    table_lines = []
    for row in table:
        table_lines.append(
            f"| {row['instance_id']} | {row['arm']} | "
            f"{row['feasible_runs']}/{row['runs']} | "
            f"{fmt(row['Best_CNY'])} | {fmt(row['Avg_CNY'])} | "
            f"{fmt(row['Gap_pct'])}% | "
            f"{fmt(row['time_avg_seconds'], 1)} | "
            f"{row['actual_evaluations_min']}/"
            f"{fmt(row['actual_evaluations_avg'], 1)}/"
            f"{row['actual_evaluations_max']} |"
        )
    by_instance_lines = []
    for instance_id, row in endpoints["by_instance"].items():
        mean_effect = row["cost_effect_pct"]["mean"]
        by_instance_lines.append(
            f"| {instance_id} | "
            f"{row['fast_nonlinear_feasible_count']}/"
            f"{row['fast_nonlinear_denominator']} | "
            f"{row['L100_false_feasible_count']}/"
            f"{row['L100_denominator']} | "
            f"{row['common_feasible_pairs']}/"
            f"{row['pair_denominator']} | "
            f"{fmt(mean_effect, 6)}% | "
            f"{row['taper_exposed_sessions']}/"
            f"{row['session_rows']} "
            f"({row['taper_exposed_session_pct']:.3f}%) |"
        )
    causes = e2["causes_allow_overlap"]
    cause_text = (
        "无"
        if not causes
        else "；".join(
            f"{key}: {value['affected_units']} 单元/"
            f"{value['violations']} 条违反"
            for key, value in sorted(causes.items())
        )
    )
    effect_display = fmt(effect, 6)
    if effect_observed:
        conclusion = (
            "快充下产生了达到预注册阈值的可观测机制效应。"
            "这支持提出升格，但不自动把摸底结果写入正文。"
        )
        checklist = "\n".join(
            f"{index}. {item}"
            for index, item in enumerate(promotion_items, start=1)
        )
        promotion_section = f"""## 升格清单与代价

固定功率情景仍使用现有外生参数 `π_s`，TeX 公式结构不需要改；若改成同场慢快设备由算法选择，则公式必须另行建模，本轮没有授权。

{checklist}

代价是重新闭合参数、曲线和设施证据，并重跑所有受车场充电功率、时长或两部制电价影响的封存结果；不能只替换 E5 表格。
"""
    else:
        conclusion = (
            "快充下没有达到预注册阈值的可观测机制效应。"
            "本轮不升格，也不再追加更极端功率或更早折点。"
        )
        promotion_section = """## 升格判断

没有升格清单：效应未达到预注册的 10 个百分点假可行或 2% 共同可行成本改善阈值。根因按实际会话证据解释，不继续调参凑效应。
"""
    return f"""# E5 快充非线性充电摸底

状态：`COMPLETE`。本轮是结果前冻结的敏感性摸底，不计入正文。结论：**{conclusion}**

## 预注册情景

车场功率冻结为每次充电动作 120 kW，公共站仍为 60 kW。两臂均使用同一快充功率与同一电价覆盖：`L100_control` 对照 `M17_FAST_SHAPE_SCALED_120KW_PWL`。曲线取 Montoya et al. (2017) 第 13 页 fast 函数，原始节点为 `(0 h,0 kWh)`、`(0.31 h,13.6 kWh)`、`(0.39 h,15.2 kWh)`、`(0.51 h,16.0 kWh)`，折点为 85%/95%/100%；其无量纲形状缩放到 120 kW。完整参数和结果前时间戳见 `pre_registration.json`。

120 kW 离散档由[南方电网专项采购公告](https://www.bidding.csg.cn/zbhxrgs/1200360903.jhtml)支持；它是设备规格证据，不是全国默认。315 kVA 及以上两部制资格来自[发改价格〔2023〕526号](https://zfxxgk.ndrc.gov.cn/wap/iteminfo.jsp?id=20233)。广州车场电量价换为封存的珠三角两部制行；基本费按 `36.1×最大需量(kW)` 或 `22.6×变压器容量(kVA)` 元/月计算，315 kVA 示例为 7119 元/月。深圳采用独立计量充电设施行并按专项规则免收基本费。固定月基本费不随两臂变化，未进入边际路线目标，另行列示。

搜索前以慢充完成批次的 196 个会话行预算，预计 36/196（18.367%）跨过 85% 折减点。这个比例没有因功率改变而上升；变化的是跨折点会话的时长扰动。预注册估计跨折点会话平均增加 933.156 秒。

## 四个端点

| 端点 | 快充结果 | 22 kW 慢充封存结果 |
|---|---:|---:|
| 非线性臂完整可行率 | {e1['feasible_count']}/{e1['denominator']} = {100.0*e1['feasibility_rate']:.3f}% | 20/20 = 100% |
| L100 假可行 | {e2['false_feasible_count']}/{e2['denominator']}；成因：{cause_text} | 0/20 |
| 共同可行配对成本变化 | 覆盖 {e3['coverage_count']}/{e3['denominator']}；均值 {effect_display}% | 0.000% |
| 实际进入折减区会话 | {e4['taper_exposed_sessions']}/{e4['session_rows']} = {e4['actual_exposed_session_pct']:.3f}% | 36/196 = 18.367% |

成本变化定义为共同快充非线性物理下，`100×(非线性搜索方案成本−L100 固定方案回放成本)/L100 回放成本`；负值表示非线性搜索带来成本改善。逐会话起止 SOC、线性/非线性时长及差值在 `charging_sessions.csv`，逐种子配对在 `paired_cost_effects.csv`。

| Instance | 快充 NL 完整可行 | L100 假可行 | 共同可行 | 成本变化均值 | 折减区会话 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(by_instance_lines)}

## 搜索与独立认证

每个算例每臂种子 1–10，共 40 单元；完整候选评价预算 400 是上限，不是配额。两臂共用相同初始解、种子、功率、电价和公共站设置。合法完整模型不可行按正常预算消费记录，技术错误才停止。所有单元由独立进程重建，并核对 `check_solution`/`evaluate` 与 `exact_china81_score` 的违反台账和成本分解。

| Instance | Arm | Feasible | Best CNY | Avg CNY | Gap | Avg s | Evaluations min/avg/max |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(table_lines)}

{promotion_section}
## 证据边界

Montoya 曲线证明公开 E-VRP-NL 测试集中存在 44 kW fast 的分段形状；缩放到本项目 120 kW 是摸底建模迁移，不是 77.28 kWh 车辆的实车标定。中国官方采购证明 120 kW 设备档存在，不证明九个命名车场的实际设备占比。全国物流车场慢充/快充部署比例仍为 `null`。
"""


def finalize(workers: int) -> None:
    configure_v4()
    environment = environment_snapshot(workers)
    lock = verify_source_lock()
    statuses = formal_statuses()
    subprocess.run(
        [
            sys.executable,
            "-u",
            str(cfg.CHECKER),
            "--output-root",
            str(OUT),
        ],
        cwd=REPO,
        env={**os.environ, **cfg.THREAD_ENV},
        check=True,
    )
    certs = load_certificates()
    status_by_key = {
        (row["instance_id"], int(row["seed"]), row["arm"]): row
        for row in statuses
    }
    raw_rows: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    for cert in sorted(
        certs,
        key=lambda row: (
            row["instance_id"], int(row["seed"]), row["arm"]
        ),
    ):
        status = status_by_key[
            (cert["instance_id"], int(cert["seed"]), cert["arm"])
        ]
        raw_rows.append(
            {
                "task_id": TASK_ID,
                "instance_id": cert["instance_id"],
                "sample_role": cert["sample_role"],
                "seed": cert["seed"],
                "arm": cert["arm"],
                "complete_candidate_budget_cap": cfg.BUDGET_CAP,
                "complete_candidate_evaluations_consumed": status[
                    "complete_candidate_evaluations_consumed"
                ],
                "termination_reason": status["termination_reason"],
                "elapsed_wall_seconds": status["elapsed_wall_seconds"],
                "elapsed_cpu_seconds": status["elapsed_cpu_seconds"],
                "search_total_cost_cny": status["search_total_cost_cny"],
                "planning_physics_feasible": int(
                    cert["planning_physics_feasible"]
                ),
                "common_fast_nonlinear_feasible": int(
                    cert["nonlinear_feasible"]
                ),
                "linear_plan_false_feasible": int(
                    cert["linear_plan_false_feasible"]
                ),
                "planning_full_model_total_cost_cny": (
                    cert["planning_full_model_total_cost_cny"]
                    if cert["planning_physics_feasible"]
                    else "NA_INFEASIBLE"
                ),
                "common_fast_nonlinear_total_cost_cny": (
                    cert["common_nonlinear_full_model_total_cost_cny"]
                    if cert["nonlinear_feasible"]
                    else "NA_INFEASIBLE"
                ),
                "physical_vehicle_count": cert[
                    "physical_vehicle_count"
                ],
                "nonlinear_violation_count": len(
                    cert["nonlinear_violations"]
                ),
                "nonlinear_infeasibility_categories_json": json.dumps(
                    cert["nonlinear_infeasibility_categories"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "charging_session_count": len(cert["sessions"]),
                "certificate_id": cert["certificate_id"],
                "certificate_status": cert["certificate_status"],
            }
        )
        sessions.extend(cert["sessions"])
    if len(raw_rows) != 40 or not sessions:
        raise RuntimeError("HALT_E5_FAST_CLOSEOUT_DENOMINATOR")
    atomic_csv(OUT / "raw_runs.csv", raw_rows)
    atomic_csv(
        OUT / "charging_sessions.csv",
        sorted(
            sessions,
            key=lambda row: (
                row["instance_id"],
                int(row["seed"]),
                row["arm"],
                int(row["session_index"]),
            ),
        ),
    )
    pairs = paired_rows(certs)
    atomic_csv(OUT / "paired_cost_effects.csv", pairs)
    table = formal_table(certs, statuses)
    atomic_csv(OUT / "formal_instance_arm_summary.csv", table)
    endpoints = build_endpoints(certs, pairs, sessions)
    false_count = int(
        endpoints["endpoint_2_L100_false_feasibility"][
            "false_feasible_count"
        ]
    )
    cost_effect = endpoints[
        "endpoint_3_common_feasible_cost_effect"
    ]["fast_nonlinear_minus_L100_pct"]["mean"]
    effect_observed = bool(
        false_count >= 2
        or (
            cost_effect is not None
            and float(cost_effect) <= -2.0
        )
    )
    promotion_items = [
        "参数表把车场功率、曲线 ID、85/95/100% 折点和相对功率作为同一情景块更新。",
        "情景文字把 22 kW 交流主情景与 120 kW 直流正式敏感性分开，禁止写成全国默认。",
        "固定功率下保留现有 π_s 公式；只有同场设备类型由算法选择时才新增索引和约束。",
        "补车辆侧 120 kW 接受能力和适配本车型的 SOC—功率曲线证据，Montoya 仅作形状依据。",
        "补车场设备数、共享功率、报装容量或最大需量及独立计量合同依据。",
        "将广州两部制基本费和深圳豁免口径纳入参数与总成本披露。",
        "若快充升为主情景，重跑所有受充电功率、时长和电价影响的 E1–E7 中国封存结果。",
        "若仅升为正式敏感性，至少完整重跑 E5 两臂并复核 E4 固定路线充电时段成本/排放。",
        "更新输入来源账、主张—证据矩阵、HANDOFF 和实验目录哈希，不覆盖慢充证据。",
        "渲染 PDF 后逐页验收参数表、情景边界、慢快并列表和结论措辞。",
    ]
    decision = {
        "schema_version": "E5-FASTCHARGE-DECISION-v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "study_status": "EXPLORATORY_PROBE_NOT_FOR_MAIN_TEXT",
        "budget_cap": cfg.BUDGET_CAP,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "endpoints": endpoints,
        "slowcharge_reference": {
            "source": (
                "baselines/china_e3_e7/"
                "e5_nonlinear_final_20260730/decision.json"
            ),
            "NL90_feasibility_rate": 1.0,
            "false_feasible_count": 0,
            "common_feasible_cost_effect_pct": 0.0,
            "exposed_sessions": 36,
            "session_rows": 196,
            "exposed_session_pct": 18.367346938775512,
        },
        "effect_rule": {
            "false_feasible_count_min": 2,
            "paired_cost_reduction_pct_min": 2.0,
        },
        "effect_observed": effect_observed,
        "promotion_authorized": False,
        "promotion_checklist": (
            promotion_items if effect_observed else []
        ),
        "post_result_retuning_used": False,
        "result_filtering_used": False,
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(OUT / "decision.json", decision)
    metadata = {
        "schema_version": "E5-FASTCHARGE-METADATA-v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "completed_at_utc": now_iso(),
        "study_status": "EXPLORATORY_PROBE_NOT_FOR_MAIN_TEXT",
        "pre_registration": relative(cfg.PREREG),
        "pre_registration_sha256": file_sha256(cfg.PREREG),
        "source_lock_id": lock["lock_id"],
        "instances": [
            str(row["instance_id"]) for row in cfg.INSTANCE_SPECS
        ],
        "seeds": list(range(1, 11)),
        "arms": list(cfg.ARMS),
        "depot_charge_power_kw": cfg.DEPOT_POWER_KW,
        "public_charge_power_kw": cfg.PUBLIC_POWER_KW,
        "curve": asdict(cfg.FAST_CURVE),
        "tariff_scenario": (
            "AT_OR_ABOVE_315_KVA_TWO_PART_HIGH_POWER_DC_DEPOT_CHARGING"
        ),
        "formal_units": len(raw_rows),
        "formal_pairs": len(pairs),
        "budget_cap": cfg.BUDGET_CAP,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "independent_checker": {
            "path": relative(cfg.CHECKER),
            "independent_process": True,
            "verification_path": relative(
                OUT / "independent_verification.json"
            ),
        },
        "environment": environment,
        "protected_source_verification": {
            path: {
                "locked_sha256": digest,
                "closeout_sha256": protected_hashes()[path],
                "unchanged": digest == protected_hashes()[path],
            }
            for path, digest in lock[
                "protected_source_sha256"
            ].items()
        },
    }
    atomic_json(OUT / "metadata.json", metadata)
    report = render_report(
        endpoints, table, effect_observed, promotion_items
    )
    atomic_text(OUT / "report.md", report)
    verify_source_lock()

    excluded = {"artifact_hashes.json", "done.json"}
    artifacts: list[dict[str, Any]] = []
    for path in sorted(OUT.rglob("*")):
        if not is_real_file(path):
            continue
        rel = str(path.relative_to(OUT))
        if (
            rel in excluded
            or rel.startswith("monitor_runtime/")
        ):
            continue
        artifacts.append(
            {
                "path": rel,
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "E5-FASTCHARGE-ARTIFACT-HASHES-v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "hash_algorithm": "sha256",
        "excluded": [
            "artifact_hashes.json",
            "done.json",
            "monitor_runtime/**",
            "._*",
            "__pycache__/**",
            ".pytest_cache/**",
        ],
        "artifacts": artifacts,
        "protected_source_sha256_at_closeout": protected_hashes(),
        "old_e5_tree_id_at_closeout": payload_sha256(
            old_e5_tree_hashes()
        ),
    }
    manifest["manifest_id"] = payload_sha256(manifest)
    atomic_json(OUT / "artifact_hashes.json", manifest)
    required = (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
        "pre_registration.json",
    )
    if any(not (OUT / name).is_file() for name in required):
        raise RuntimeError("HALT_E5_FAST_REQUIRED_ARTIFACT_MISSING")

    actual_pct = float(
        endpoints["endpoint_4_sessions"][
            "actual_exposed_session_pct"
        ]
    )
    feasibility_rate = float(
        endpoints[
            "endpoint_1_fast_nonlinear_complete_feasibility"
        ]["feasibility_rate"]
    )
    done = {
        "status": "COMPLETE",
        "charger_power_kw": cfg.DEPOT_POWER_KW,
        "curve_name": cfg.FAST_CURVE.curve_id,
        "curve_source": (
            "Montoya et al. (2017), Transportation Research Part B "
            "103:87-110, doi:10.1016/j.trb.2017.02.004, p.13 fast "
            "curve; normalized shape scaled to 120 kW"
        ),
        "predicted_exposed_session_pct": 18.367346938775512,
        "actual_exposed_session_pct": actual_pct,
        "feasibility_rate": feasibility_rate,
        "false_feasible_count": false_count,
        "cost_effect_pct": (
            float(cost_effect) if cost_effect is not None else None
        ),
        "effect_observed": effect_observed,
        "promotion_checklist_items": (
            len(promotion_items) if effect_observed else 0
        ),
        "completed_at_utc": now_iso(),
        "manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
        "required_artifact_sha256": {
            name: file_sha256(OUT / name) for name in required
        },
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(OUT / "done.json", done)
    print(
        f"DONE path={OUT / 'done.json'} status=COMPLETE "
        f"effect_observed={str(effect_observed).lower()}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("prepare", "formal", "finalize", "_unit")
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--instance-id",
        choices=tuple(
            str(row["instance_id"]) for row in cfg.INSTANCE_SPECS
        ),
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument("--arm", choices=cfg.ARMS)
    parser.add_argument("--lock-id")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.workers)
    elif args.command == "formal":
        if args.instance_id is None:
            parser.error("--instance-id is required for formal")
        run_formal(args.instance_id, args.workers)
    elif args.command == "finalize":
        finalize(args.workers)
    else:
        if (
            args.instance_id is None
            or args.seed is None
            or args.arm is None
            or args.lock_id is None
        ):
            parser.error(
                "_unit requires --instance-id --seed --arm --lock-id"
            )
        return run_internal_unit(
            args.instance_id, args.seed, args.arm, args.lock_id
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
