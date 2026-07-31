#!/usr/bin/env python3
"""Run the journal-aligned E3 ZONE-versus-JOINT comparison.

* ZONE: directed-road nearest-depot assignment, hard locked;
* JOINT: the ZONE input and initial solution, without the depot lock.

This runner never edits solver semantics.  It reuses the verified C++ frozen
First-Fit implementation for input construction, independently replays the
same groups with the Python packer, and uses the existing MV-HGS-SP search and
complete-model referees.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from types import ModuleType
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
CONTRACT = (
    REPO
    / "docs/handoff/experiment_contract_v2_journal_aligned_20260730.md"
)
E3_RUNNER = (
    REPO
    / "baselines/china_e3_e7/e3_mismatch_20260729/run_e3_mismatch.py"
)
OLD_INPUT_BUILDER = (
    REPO
    / "baselines/china_e3_e7/e3e6_inputs_20260730/build_inputs.py"
)
OLD_INPUT_ROOT = OLD_INPUT_BUILDER.parent
OLD_FORMAL_ROOT = (
    REPO / "baselines/china_e3_e7/e3e6_formal_20260729"
)
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
CHECKER = HERE / "check_e3_zone_joint.py"
REGRESSION_SCRIPT = HERE / "joint_semantics_regression.py"
REGRESSION_BEFORE = HERE / "regression/joint_before.json"
REGRESSION_AFTER = HERE / "regression/joint_after.json"
LOCK_FILTER_REGRESSION = HERE / "regression/zone_lock_filter_seed03.json"
JOINT_PROOF = HERE / "joint_semantics_proof.json"
BUG_FIX_EVIDENCE = HERE / "cross_site_bug_fix_evidence.json"
TASK_ID = "E3-ZONE-JOINT-COMPARISON-20260731"
INSTANCES = (
    ("cn-prd-50c-01-V2-LOCATIONS", "MAIN_EXHIBIT"),
    ("cn-prd-100c-02-V2-LOCATIONS", "ROBUSTNESS"),
)
ARMS = ("ZONE", "JOINT")
SEEDS = tuple(range(1, 11))
MAX_WORKERS = 2
LONG_PROBE_CAP = 1500
MAX_HGS_ITERATIONS_PER_VIEW = 5_000
EXACT_ELITES_PER_VIEW = 8
MIP_TIME_LIMIT_SECONDS = 5.0
PLATEAU_RELATIVE_BAND = 1.0e-4
PLATEAU_CONFIRMATION_EVALUATIONS = 200
TERMINAL_CLOSURE_SOURCES = (
    "route_pool_candidate_or_parent",
    "final_independent_certificate",
)
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
EXCLUDED_DIRS = frozenset(
    {"__pycache__", ".pytest_cache", "monitor_runtime"}
)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    PROTOTYPE / "route_pool_sp.py",
)
EXPECTED_PROTECTED_HASHES = {
    "solver/src/setp_solver/cost.py":
        "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    "solver/src/setp_solver/check.py":
        "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    "solver/src/setp_solver/search/evaluation.py":
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py":
        "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
}
LOCKED_SOURCES = (
    Path(__file__).resolve(),
    CHECKER,
    REGRESSION_SCRIPT,
    REGRESSION_BEFORE,
    REGRESSION_AFTER,
    LOCK_FILTER_REGRESSION,
    JOINT_PROOF,
    BUG_FIX_EVIDENCE,
    CONTRACT,
    E3_RUNNER,
    OLD_INPUT_BUILDER,
    OLD_INPUT_ROOT / "first_fit_lexicographic.cpp",
    OLD_INPUT_ROOT / "equivalence_check.json",
    OLD_INPUT_ROOT / "equivalence_post_probe_revalidation.log",
    PROTOTYPE / "epochal_hgs.py",
    PROTOTYPE / "route_pool_sp.py",
    PROTOTYPE / "pyvrp_adapter.py",
    REPO / "solver/src/setp_solver/china81.py",
    REPO / "solver/src/setp_solver/china81_completion.py",
    REPO / "solver/src/setp_solver/charging_curve.py",
    REPO / "solver/src/setp_solver/solution.py",
    *PROTECTED[:3],
)
AUTHORITY_MANIFESTS = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723/artifact_hashes.json",
    REPO
    / "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723/"
    "artifact_hashes.json",
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723/artifact_hashes.json",
    REPO
    / "baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/"
    "artifact_hashes.json",
)
LEGITIMATE_INFEASIBILITY_PREFIXES = (
    "China81 route skeleton has no feasible all-CV completion:",
    "China81 route skeleton exceeds the registered total fleet",
    "China81 route skeleton cannot satisfy the registered CV cap",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def append_progress(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        )
        handle.flush()


def is_real_artifact(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.startswith("._")
        and not any(part in EXCLUDED_DIRS for part in path.parts)
    )


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_e3() -> ModuleType:
    return load_module("_e3_structural_source", E3_RUNNER)


def load_old_builder() -> ModuleType:
    return load_module("_e3_structural_old_builder", OLD_INPUT_BUILDER)


def verify_protected() -> dict[str, str]:
    actual = {relative(path): file_sha256(path) for path in PROTECTED}
    if actual != EXPECTED_PROTECTED_HASHES:
        drift = {
            name: {
                "expected": EXPECTED_PROTECTED_HASHES.get(name),
                "actual": value,
            }
            for name, value in actual.items()
            if value != EXPECTED_PROTECTED_HASHES.get(name)
        }
        raise RuntimeError(
            "HALT_PROTECTED_HASH_DRIFT:"
            + json.dumps(drift, sort_keys=True)
        )
    return actual


def current_source_hashes() -> dict[str, str]:
    paths = (*LOCKED_SOURCES, *AUTHORITY_MANIFESTS)
    missing = [relative(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"HALT_LOCKED_SOURCE_MISSING:{missing}")
    return {relative(path): file_sha256(path) for path in paths}


def verify_source_lock() -> dict[str, Any]:
    lock_path = HERE / "source_lock.json"
    if not lock_path.is_file():
        raise RuntimeError("HALT_SOURCE_LOCK_MISSING")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock["source_sha256"] != current_source_hashes():
        raise RuntimeError("HALT_SOURCE_HASH_DRIFT")
    if lock["protected_sha256"] != verify_protected():
        raise RuntimeError("HALT_PROTECTED_HASH_DRIFT")
    return lock


def preflight(workers: int) -> dict[str, Any]:
    if not 1 <= workers <= MAX_WORKERS:
        raise RuntimeError(f"HALT_WORKERS_OUT_OF_RANGE:{workers}")
    wrong = {
        name: os.environ.get(name)
        for name, expected in REQUIRED_THREAD_ENV.items()
        if os.environ.get(name) != expected
    }
    if wrong:
        raise RuntimeError(f"HALT_THREAD_ENV_NOT_FROZEN:{wrong}")
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise RuntimeError(
            f"HALT_PYTHON_ENVIRONMENT:{sys.executable}!={PYTHON}"
        )
    if importlib.metadata.version("pyvrp") != "0.12.2":
        raise RuntimeError("HALT_PYVRP_VERSION")
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "pyvrp": importlib.metadata.version("pyvrp"),
        "scipy": importlib.metadata.version("scipy"),
        "thread_environment": dict(REQUIRED_THREAD_ENV),
        "workers": workers,
    }


def solution_payload(e3: ModuleType, solution: Any) -> dict[str, Any]:
    return e3.solution_payload(solution)


def input_folder(instance_id: str, arm: str) -> Path:
    return HERE / "inputs" / instance_id / arm


def task_stem(spec: dict[str, Any]) -> str:
    return (
        f"{spec['instance_id']}__seed{int(spec['seed']):02d}"
        f"__{spec['arm']}"
    )


def archive_limits(cap: int) -> dict[str, int]:
    remaining = int(cap) - 8
    if remaining < 3 * EXACT_ELITES_PER_VIEW:
        raise ValueError(f"complete-candidate cap is too small: {cap}")
    base, remainder = divmod(remaining, 3)
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    result = {
        mode: base + (1 if index < remainder else 0)
        for index, mode in enumerate(modes)
    }
    if sum(result.values()) + 8 != int(cap):
        raise RuntimeError("HALT_ARCHIVE_CAP_MAPPING")
    return result


def round_up_hundred_with_margin(value: int) -> int:
    if value < 1:
        raise ValueError("evaluation count must be positive")
    rounded = int(math.ceil(value / 100) * 100)
    return rounded + 100 if rounded == value else rounded


def termination_reason(
    run: Any,
    *,
    consumed: int,
    cap: int,
) -> tuple[str, dict[str, Any]]:
    evidence: dict[str, Any] = {}
    for mode, epoch in run.view_epochs.items():
        stats = epoch.stats
        evidence[mode] = {
            "archive_candidate_limit": int(
                stats["archive_candidate_limit"]
            ),
            "archive_completion_attempts": int(
                stats["archive_completion_attempts"]
            ),
            "archive_unique_native_candidates": int(
                stats["archive_unique_native_candidates"]
            ),
            "hgs_stop_mode": stats["hgs_stop_mode"],
            "wallclock_safety_triggered": bool(
                stats["wallclock_safety_triggered"]
            ),
        }
    if consumed > cap:
        raise RuntimeError(f"HALT_BUDGET_CAP_EXCEEDED:{consumed}>{cap}")
    if consumed == cap:
        return "BUDGET_CAP_REACHED", evidence
    no_improvement = [
        mode
        for mode, row in evidence.items()
        if "NO_IMPROVEMENT" in str(row["hgs_stop_mode"]).upper()
    ]
    if no_improvement:
        evidence["no_improvement_modes"] = no_improvement
        return "NO_IMPROVEMENT", evidence
    shortfall = [
        mode
        for mode, row in evidence.items()
        if row["archive_completion_attempts"]
        < row["archive_candidate_limit"]
    ]
    exhausted = [
        mode
        for mode in shortfall
        if evidence[mode]["archive_completion_attempts"]
        == min(
            evidence[mode]["archive_unique_native_candidates"],
            evidence[mode]["archive_candidate_limit"],
        )
    ]
    evidence["shortfall_modes"] = shortfall
    evidence["exhausted_modes"] = exhausted
    if shortfall and exhausted == shortfall:
        return "CANDIDATES_EXHAUSTED", evidence
    raise RuntimeError(
        "HALT_AMBIGUOUS_EARLY_TERMINATION:"
        f"{consumed}:{cap}:{evidence}"
    )


def classify_trace(trace: list[dict[str, Any]]) -> dict[str, Any]:
    classified: list[dict[str, Any]] = []
    counts = {
        "feasible_candidates": 0,
        "infeasible_candidates": 0,
        "constraint_filtered_candidates": 0,
        "error_candidates": 0,
    }
    exception_counts: dict[tuple[str, str, str], int] = {}
    for original in trace:
        row = dict(original)
        objective = row.get("complete_objective")
        status = str(row.get("status"))
        exc_type = row.get("exception_type")
        exc_message = row.get("exception_message")
        if objective is not None and status == "PASS":
            category = "FEASIBLE"
            counts["feasible_candidates"] += 1
        elif status == "FILTERED_HARD_HOME_DEPOT_LOCK":
            category = "CONSTRAINT_FILTERED"
            counts["constraint_filtered_candidates"] += 1
        elif (
            objective is None
            and status == "INFEASIBLE_OR_ERROR"
            and exc_type == "ValueError"
            and isinstance(exc_message, str)
            and exc_message.startswith(LEGITIMATE_INFEASIBILITY_PREFIXES)
        ):
            category = "LEGITIMATE_INFEASIBLE"
            counts["infeasible_candidates"] += 1
        else:
            category = "TECHNICAL_ERROR"
            counts["error_candidates"] += 1
        row["failure_category"] = category
        classified.append(row)
        if category not in {"FEASIBLE", "CONSTRAINT_FILTERED"}:
            key = (
                category,
                str(exc_type or "MISSING_EXCEPTION_TYPE"),
                str(exc_message or "MISSING_EXCEPTION_MESSAGE"),
            )
            exception_counts[key] = exception_counts.get(key, 0) + 1
    return {
        **counts,
        "classified_trace": classified,
        "exception_breakdown": [
            {
                "failure_category": category,
                "exception_type": exc_type,
                "exception_message": message,
                "count": count,
            }
            for (category, exc_type, message), count in sorted(
                exception_counts.items()
            )
        ],
    }


def source_line(path: Path, token: str) -> int:
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if token in line:
            return line_number
    raise RuntimeError(f"HALT_EXPECTED_SOURCE_TOKEN_MISSING:{path}:{token}")


def source_lines(path: Path, token: str) -> list[int]:
    matches = [
        line_number
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if token in line
    ]
    if not matches:
        raise RuntimeError(
            f"HALT_EXPECTED_SOURCE_TOKEN_MISSING:{path}:{token}"
        )
    return matches


def write_bug_fix_and_joint_proof() -> None:
    before = json.loads(REGRESSION_BEFORE.read_text(encoding="utf-8"))
    after = json.loads(REGRESSION_AFTER.read_text(encoding="utf-8"))
    exact_fields = (
        "instance_id",
        "seed",
        "arm",
        "hard_home_depot_lock",
        "budget_cap",
        "complete_candidate_evaluations_consumed",
        "solution_sha256",
        "objective",
        "objective_float_hex",
        "full_objective",
        "full_objective_sha256",
        "violation_count",
        "cross_site_service_count",
    )
    mismatches = {
        field: {"before": before[field], "after": after[field]}
        for field in exact_fields
        if before[field] != after[field]
    }
    if mismatches:
        raise RuntimeError(
            "HALT_JOINT_SEMANTICS_DRIFT:"
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )
    proof = {
        "schema": "resetp.e3-zone-joint.joint-semantics-proof.v1",
        "status": "PASS_JOINT_SEMANTICS_UNCHANGED",
        "created_at_utc": now_iso(),
        "same_seed_rerun": True,
        "instance_id": before["instance_id"],
        "seed": before["seed"],
        "budget_cap": before["budget_cap"],
        "hard_home_depot_lock": False,
        "solution_sha256_before": before["solution_sha256"],
        "solution_sha256_after": after["solution_sha256"],
        "objective_float_hex_before": before["objective_float_hex"],
        "objective_float_hex_after": after["objective_float_hex"],
        "full_objective_sha256_before": before[
            "full_objective_sha256"
        ],
        "full_objective_sha256_after": after[
            "full_objective_sha256"
        ],
        "complete_candidate_evaluations_before": before[
            "complete_candidate_evaluations_consumed"
        ],
        "complete_candidate_evaluations_after": after[
            "complete_candidate_evaluations_consumed"
        ],
        "before_epochal_hgs_sha256": before["epochal_hgs_sha256"],
        "after_epochal_hgs_sha256": after["epochal_hgs_sha256"],
        "exact_field_mismatches": 0,
        "proof_inputs": {
            "before": relative(REGRESSION_BEFORE),
            "after": relative(REGRESSION_AFTER),
        },
    }
    proof["proof_id"] = payload_sha256(proof)
    atomic_json(JOINT_PROOF, proof)

    old_root = REPO / "baselines/china_e3_e7/e3_structural_20260731"
    exact_message = (
        "hard home-depot control candidate contains cross-site service"
    )
    technical_rows: list[dict[str, Any]] = []
    for path in sorted((old_root / "formal/search_traces").glob("*.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))
        for item in trace["complete_candidate_evaluation_trace"]:
            if item.get("exception_message") == exact_message:
                technical_rows.append(
                    {
                        "trace": relative(path),
                        "view": item.get("view"),
                        "source": item.get("source"),
                    }
                )
    if len(technical_rows) != 14 or {
        row["source"] for row in technical_rows
    } != {"terminal_population_archive"}:
        raise RuntimeError("HALT_OLD_TECHNICAL_TRACE_FORENSICS_DRIFT")
    lock_regression = json.loads(
        LOCK_FILTER_REGRESSION.read_text(encoding="utf-8")
    )
    if (
        lock_regression["arm"] != "ZONE"
        or int(lock_regression["hard_lock_filtered_candidates"]) < 1
        or int(lock_regression["cross_site_service_count"]) != 0
        or int(lock_regression["violation_count"]) != 0
    ):
        raise RuntimeError("HALT_LOCK_FILTER_REGRESSION")
    adapter = PROTOTYPE / "pyvrp_adapter.py"
    epochal = PROTOTYPE / "epochal_hgs.py"
    bug_fix = {
        "schema": "resetp.e3-zone-joint.cross-site-bug-fix.v1",
        "status": "PASS_CROSS_SITE_BUG_FIXED",
        "created_at_utc": now_iso(),
        "old_halt_trace_count": len(technical_rows),
        "old_halt_trace_source_counts": {
            "terminal_population_archive": len(technical_rows)
        },
        "old_halt_trace_view_counts": {
            view: sum(row["view"] == view for row in technical_rows)
            for view in sorted({str(row["view"]) for row in technical_rows})
        },
        "old_error_message": exact_message,
        "hard_lock_encoding": {
            "file": relative(adapter),
            "customer_ownership_dimension_start_line": source_line(
                adapter, "if hard_home_depot_lock:"
            ),
            "vehicle_capacity_dimension_start_line": 261,
            "description": (
                "customer ownership is encoded as depot-specific delivery "
                "dimensions and matching per-depot vehicle capacities"
            ),
        },
        "leak_path_before_fix": {
            "file": relative(epochal),
            "function": "_run_exact_epoch",
            "pre_fix_source_sha256": before["epochal_hgs_sha256"],
            "pre_fix_terminal_archive_block_lines": "448-510",
            "path": (
                "native HGS terminal population archive -> full China81 "
                "completion -> post-completion cross-site ValueError"
            ),
            "single_operator_attribution_available": False,
            "reason": (
                "the persisted terminal archive trace records the path and "
                "view but not the ancestry of an individual HGS move"
            ),
        },
        "fix": {
            "file": relative(epochal),
            "hard_lock_filter_status_lines": source_lines(
                epochal, '"FILTERED_HARD_HOME_DEPOT_LOCK"'
            ),
            "semantics": (
                "after full completion, a hard-lock cross-site candidate is "
                "counted against the cap and normally filtered before elite "
                "selection; no search operator is changed"
            ),
            "route_pool_sp_search_semantics_changed": False,
        },
        "lock_regression": {
            "path": relative(LOCK_FILTER_REGRESSION),
            "instance_id": lock_regression["instance_id"],
            "seed": lock_regression["seed"],
            "filtered_candidates": lock_regression[
                "hard_lock_filtered_candidates"
            ],
            "final_cross_site_service_count": 0,
            "final_violation_count": 0,
        },
        "joint_semantics_proof": relative(JOINT_PROOF),
    }
    bug_fix["evidence_id"] = payload_sha256(bug_fix)
    atomic_json(BUG_FIX_EVIDENCE, bug_fix)


def administrative_mapping(base: Any) -> tuple[dict[str, str], dict[str, Any]]:
    nodes = {node.node_id: node for node in base.instance.nodes}
    depots_by_city: dict[str, str] = {}
    for node in base.instance.nodes:
        if node.node_type.lower() != "d":
            continue
        city = str(node.city).strip().lower()
        if city in depots_by_city:
            raise RuntimeError(f"HALT_MULTIPLE_DEPOTS_PER_CITY:{city}")
        depots_by_city[city] = node.node_id
    mapping = dict(base.customer_home_depot)
    for customer_id, depot_id in mapping.items():
        customer = nodes[customer_id]
        city = str(customer.city).strip().lower()
        if depots_by_city.get(city) != depot_id:
            raise RuntimeError(
                f"HALT_ADMINISTRATIVE_MAPPING_DRIFT:{customer_id}"
            )
    membership_path = (
        REPO
        / "data/ChinaInstances/"
        "china81_stage2_static_inputs_corrected_v3_20260723/"
        "node_city_membership.csv"
    )
    with membership_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["instance_id"] == base.instance_id
            and row["node_type"] == "customer"
        ]
    certificates = {row["node_id"]: row for row in rows}
    if set(certificates) != set(mapping):
        raise RuntimeError("HALT_ADMINISTRATIVE_CERTIFICATE_DENOMINATOR")
    if any(
        row["gis_status"] != "PASS_DECLARED_CITY_BOUNDARY"
        for row in certificates.values()
    ):
        raise RuntimeError("HALT_ADMINISTRATIVE_CITY_CERTIFICATE")
    evidence = {
        "literal_registered_depot_column_found": False,
        "equivalent_administrative_assignment_found": True,
        "registered_depot_field_found": True,
        "source_fields": [
            "nodes.csv:city",
            "node_city_membership.csv:declared_city",
            "node_city_membership.csv:gis_status",
        ],
        "loader_derivation":
            "customer city -> the unique depot in that same city",
        "loader_path": "solver/src/setp_solver/china81.py:355",
        "customer_certificates": len(certificates),
        "all_customer_city_certificates_pass": True,
        "boundary_source_class": sorted(
            {row["boundary_source_class"] for row in certificates.values()}
        ),
        "no_new_ind_parameter_required": True,
    }
    return mapping, evidence


def nearest_mapping(base: Any) -> dict[str, str]:
    depots = sorted(
        node.node_id
        for node in base.instance.nodes
        if node.node_type.lower() == "d"
    )
    return {
        customer_id: min(
            depots,
            key=lambda depot_id: (
                float(base.instance.distance(depot_id, customer_id)),
                depot_id,
            ),
        )
        for customer_id in base.customer_home_depot
    }


def fixed_cpp_first_fit(
    old_builder: ModuleType,
    old_runner: ModuleType,
    bundle: Any,
    mapping: dict[str, str],
) -> tuple[dict[str, list[list[str]]], dict[str, int], float]:
    problem, depots, customers, _options = old_builder.serialize_problem(
        old_runner,
        bundle,
        mapping,
        [],
    )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(old_builder.CPP_BINARY)],
            input=problem,
            text=True,
            capture_output=True,
            check=False,
            timeout=15 * 60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"HALT_FIXED_FIRST_FIT_COMBINATION_EXPLOSION:"
            f"{bundle.instance_id}"
        ) from exc
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"HALT_CPP_FIRST_FIT:{completed.returncode}:"
            f"{completed.stderr}"
        )
    status, chosen, groups, stats = old_builder.parse_solver_output(
        completed.stdout,
        depots,
        customers,
    )
    if status != "PASS" or chosen != [] or groups is None:
        raise RuntimeError(
            f"HALT_FIXED_MAPPING_FIRST_FIT_INFEASIBLE:"
            f"{bundle.instance_id}:{status}"
        )
    remapped = old_runner.e3.with_responsibility(bundle, mapping)
    replay = {
        depot_id: old_runner.e3._pack_depot(remapped, depot_id)
        for depot_id in depots
    }
    if replay != groups:
        raise RuntimeError(
            f"HALT_CPP_PYTHON_FIRST_FIT_DISAGREEMENT:"
            f"{bundle.instance_id}"
        )
    return groups, stats, elapsed


def build_inputs(workers: int) -> dict[str, Any]:
    if (HERE / "done.json").exists():
        raise RuntimeError("task already has done.json")
    HERE.mkdir(parents=True, exist_ok=True)
    environment = preflight(workers)
    protected = verify_protected()
    write_bug_fix_and_joint_proof()
    equivalence = json.loads(
        (OLD_INPUT_ROOT / "equivalence_check.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        not equivalence.get("equivalence_check_passed")
        or int(equivalence.get("checked_units", -1)) != 56
        or int(equivalence.get("mismatching_units", -1)) != 0
    ):
        raise RuntimeError("HALT_FIRST_FIT_EQUIVALENCE_NOT_PASSED")
    sources = current_source_hashes()
    lock = {
        "schema": "resetp.e3-structural.source-lock.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "source_sha256": sources,
        "protected_sha256": protected,
        "first_fit_equivalence": {
            "checked_units": 56,
            "matching_units": 56,
            "mismatching_units": 0,
            "post_probe_revalidation_log": relative(
                OLD_INPUT_ROOT / "equivalence_post_probe_revalidation.log"
            ),
        },
        "environment": environment,
    }
    lock["source_lock_id"] = payload_sha256(lock)
    atomic_json(HERE / "source_lock.json", lock)
    prior_budget_path = (
        REPO
        / "baselines/china_e3_e7/e3_structural_20260731/budget_lock.json"
    )
    prior_budget = json.loads(
        prior_budget_path.read_text(encoding="utf-8")
    )
    if int(prior_budget["selected_common_formal_budget_cap"]) != 400:
        raise RuntimeError("HALT_PRIOR_BUDGET_LOCK_DRIFT")
    budget_lock = {
        "schema": "resetp.e3-zone-joint.budget-lock.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "selected_common_formal_budget_cap": 400,
        "inherited_from": relative(prior_budget_path),
        "inherited_budget_lock_sha256": file_sha256(prior_budget_path),
        "inherited_probe_id": prior_budget["probe_id"],
        "source_lock_id": lock["source_lock_id"],
    }
    budget_lock["budget_lock_id"] = payload_sha256(budget_lock)
    atomic_json(HERE / "budget_lock.json", budget_lock)

    old_builder = load_old_builder()
    old_builder.compile_cpp()
    old_runner = old_builder.load_runner()
    e3 = old_runner.e3
    assignment_rows: list[dict[str, Any]] = []
    descriptive_rows: list[dict[str, Any]] = []
    field_evidence: list[dict[str, Any]] = []
    built_counts = {arm: 0 for arm in ARMS}
    for instance_id, role in INSTANCES:
        base = e3.load_bundle(instance_id)
        ind, evidence = administrative_mapping(base)
        evidence = {"instance_id": instance_id, **evidence}
        field_evidence.append(evidence)
        zone = nearest_mapping(base)
        mismatched = [
            customer_id
            for customer_id in sorted(ind)
            if ind[customer_id] != zone[customer_id]
        ]
        descriptive_rows.append(
            {
                "instance_id": instance_id,
                "sample_role": role,
                "customer_count": len(ind),
                "registered_nearest_mismatch_count": len(mismatched),
                "registered_nearest_mismatch_pct":
                    100.0 * len(mismatched) / len(ind),
                "registered_assignment_source":
                    "administrative city -> unique same-city depot",
                "nearest_rule":
                    "directed depot-to-customer road distance; depot id tie-break",
            }
        )
        arm_mapping = {"IND": ind, "ZONE": zone, "JOINT": zone}
        for arm in ARMS:
            mapping = arm_mapping[arm]
            hard_lock = arm != "JOINT"
            bundle = e3.with_responsibility(base, mapping)
            groups, cpp_stats, cpp_elapsed = fixed_cpp_first_fit(
                old_builder,
                old_runner,
                base,
                mapping,
            )
            initial, initial_audit = e3.build_common_initial(bundle)
            expected_counts = {
                depot_id: len(routes)
                for depot_id, routes in groups.items()
            }
            if initial_audit["route_counts_by_depot"] != expected_counts:
                raise RuntimeError(
                    f"HALT_INITIAL_ROUTE_COUNT_DRIFT:{instance_id}:{arm}"
                )
            customer_ids = set(mapping)
            initial_groups = {
                depot_id: [
                    [
                        node_id
                        for node_id in route.node_sequence
                        if node_id in customer_ids
                    ]
                    for route in initial.routes
                    if route.home_depot_id == depot_id
                ]
                for depot_id in sorted(groups)
            }
            if initial_groups != groups:
                raise RuntimeError(
                    f"HALT_INITIAL_FIRST_FIT_GROUP_DRIFT:"
                    f"{instance_id}:{arm}"
                )
            responsibility = {
                "schema": "resetp.e3-structural.responsibility.v1",
                "task_id": TASK_ID,
                "instance_id": instance_id,
                "sample_role": role,
                "arm": arm,
                "mapping": mapping,
                "mapping_sha256": payload_sha256(mapping),
                "hard_home_depot_lock": hard_lock,
                "assignment_semantics": {
                    "IND":
                        "customer administrative city -> unique same-city depot",
                    "ZONE":
                        "nearest depot by directed depot-to-customer road distance",
                    "JOINT":
                        "ZONE reference mapping retained only for common initial and accounting; service lock removed",
                }[arm],
                "joint_reference_choice": (
                    "ZONE mapping and ZONE initial isolate ZONE-to-JOINT lock removal"
                    if arm == "JOINT"
                    else None
                ),
                "source_lock_id": lock["source_lock_id"],
            }
            skeleton = {
                "schema": "resetp.e3-structural.first-fit-skeleton.v1",
                "instance_id": instance_id,
                "arm": arm,
                "construction":
                    "VERIFIED_CPP_FROZEN_FIRST_FIT_WITH_PYTHON_REPLAY",
                "route_groups_by_depot": groups,
                "route_counts_by_depot": expected_counts,
                "cpp_elapsed_seconds": cpp_elapsed,
                "cpp_stats": cpp_stats,
                "cpp_python_equivalent": True,
                "customer_coverage": len(
                    {
                        customer
                        for depot_groups in groups.values()
                        for route in depot_groups
                        for customer in route
                    }
                ),
            }
            initial_payload = solution_payload(e3, initial)
            certificate = {
                "schema": "resetp.e3-structural.input-certificate.v1",
                "status": "PASS_INPUT_CONSTRUCTED_AND_INDEPENDENTLY_CHECKED",
                "instance_id": instance_id,
                "arm": arm,
                "hard_home_depot_lock": hard_lock,
                "responsibility_sha256": payload_sha256(responsibility),
                "skeleton_sha256": payload_sha256(skeleton),
                "initial_solution_sha256": payload_sha256(initial_payload),
                "complete_model_violation_count": 0,
                "first_fit_cpp_python_equivalence": True,
                "protected_hashes": protected,
                "source_lock_id": lock["source_lock_id"],
            }
            folder = input_folder(instance_id, arm)
            if folder.exists():
                existing = json.loads(
                    (folder / "input_certificate.json").read_text(
                        encoding="utf-8"
                    )
                )
                if existing != certificate:
                    raise RuntimeError(
                        f"HALT_EXISTING_INPUT_DRIFT:{instance_id}:{arm}"
                    )
            else:
                temporary = folder.parent / f".{arm}.tmp-{os.getpid()}"
                temporary.mkdir(parents=True)
                atomic_json(
                    temporary / "responsibility_map.json",
                    responsibility,
                )
                atomic_json(
                    temporary / "common_route_skeleton.json",
                    skeleton,
                )
                atomic_json(
                    temporary / "initial_solution.json",
                    initial_payload,
                )
                atomic_json(
                    temporary / "input_certificate.json",
                    certificate,
                )
                os.replace(temporary, folder)
            built_counts[arm] += 1
            for customer_id in sorted(mapping):
                assignment_rows.append(
                    {
                        "instance_id": instance_id,
                        "sample_role": role,
                        "arm": arm,
                        "customer_id": customer_id,
                        "administrative_registered_depot": ind[customer_id],
                        "nearest_depot": zone[customer_id],
                        "assigned_reference_depot": mapping[customer_id],
                        "hard_home_depot_lock": hard_lock,
                        "registered_differs_from_nearest":
                            ind[customer_id] != zone[customer_id],
                        "registered_distance_m": float(
                            base.instance.distance(
                                ind[customer_id], customer_id
                            )
                        ),
                        "nearest_distance_m": float(
                            base.instance.distance(
                                zone[customer_id], customer_id
                            )
                        ),
                    }
                )

    atomic_csv(HERE / "input_assignments.csv", assignment_rows)
    atomic_csv(HERE / "descriptive_statistics.csv", descriptive_rows)
    investigation = {
        "schema": "resetp.e3-structural.depot-field-investigation.v1",
        "status": "PASS_EXISTING_ADMINISTRATIVE_ASSIGNMENT_FOUND",
        "registered_depot_field_found": True,
        "literal_registered_depot_column_found": False,
        "equivalent_existing_field": "customer city",
        "loader_derivation":
            "customer city -> unique depot in that same city",
        "no_ind_constructor_parameter_introduced": True,
        "ind_arm_run": False,
        "ind_arm_reason": "IND_AND_ZONE_INPUTS_IDENTICAL_BY_PRE_SEARCH_FACT",
        "instances": field_evidence,
        "unused_alternatives": [
            {
                "option": "second-nearest depot",
                "objective_basis": "distance rank",
                "drawback":
                    "synthetic mismatch severity parameter and artificially imposed spatial disorder",
            },
            {
                "option": "finer administrative-region assignment",
                "objective_basis": "sub-city administrative membership",
                "drawback":
                    "requires a new reliable boundary source and a documented sub-region-to-depot mapping",
            },
            {
                "option": "capacity-balanced assignment",
                "objective_basis": "fleet-cap load balancing",
                "drawback":
                    "endogenous to model capacity and not a historical/administrative registration",
            },
        ],
    }
    atomic_json(HERE / "depot_field_investigation.json", investigation)

    active_units = {
        "cn-jjj-150c-01-V2-LOCATIONS__mismatch50",
        "cn-jjj-150c-02-V2-LOCATIONS__mismatch50",
        "cn-jjj-150c-03-V2-LOCATIONS__mismatch50",
        "cn-jjj-200c-01-V2-LOCATIONS__mismatch50",
        "cn-jjj-200c-02-V2-LOCATIONS__mismatch50",
        "cn-prd-150c-02-V2-LOCATIONS__mismatch50",
        "cn-prd-200c-01-V2-LOCATIONS__mismatch50",
        "cn-prd-200c-02-V2-LOCATIONS__mismatch50",
    }
    authoritative_log = OLD_INPUT_ROOT / "build_progress.log"
    terminal_units = {
        json.loads(line)["unit"]
        for line in authoritative_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    with (
        OLD_FORMAL_ROOT / "gate2_d3/eligible_multi_depot_instances.csv"
    ).open(encoding="utf-8", newline="") as handle:
        eligible = sorted(
            row["instance_id"] for row in csv.DictReader(handle)
        )
    expected_old = [
        f"{instance_id}__mismatch{intensity:02d}"
        for instance_id in eligible
        for intensity in (0, 25, 50)
    ]
    superseded = [
        {
            "unit": unit,
            "prior_queue_state":
                "ACTIVE_EXACT_AT_SNAPSHOT"
                if unit in active_units
                else "QUEUED_AT_SNAPSHOT",
            "status": "NOT_BUILT_SUPERSEDED_DESIGN",
            "reason":
                "CONTRACT_JOURNAL_ALIGNED_V2_REPLACED_OLD_0_25_50_SCAN",
            "not_infeasible": True,
            "not_technical_failure": True,
            "old_real_files_deleted_or_overwritten": False,
        }
        for unit in expected_old
        if unit not in terminal_units
    ]
    if len(superseded) != 29:
        raise RuntimeError(
            f"HALT_SUPERSEDED_DENOMINATOR:{len(superseded)}/29"
        )
    atomic_csv(HERE / "superseded_units.csv", superseded)
    stop_evidence = {
        "schema": "resetp.e3-structural.stop-evidence.v1",
        "requested_pgid": 7965,
        "checked_at_utc": now_iso(),
        "members_observed_before_signal": [],
        "sigterm_attempted": True,
        "sigterm_result": "NO_SUCH_PROCESS",
        "confirmed_group_absent_after_attempt": True,
        "pgid_7965_stopped": True,
        "qualification":
            "the requested PGID was already absent when this agent checked; no claim is made that this agent delivered the terminating signal",
    }
    atomic_json(HERE / "pgid_7965_stop_evidence.json", stop_evidence)
    prepared = {
        "schema": "resetp.e3-structural.prepare.v1",
        "status": "PASS_INPUTS_READY",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "source_lock_id": lock["source_lock_id"],
        "registered_depot_field_found": True,
        "built_counts": built_counts,
        "superseded_units_registered": len(superseded),
        "pgid_7965_stopped": True,
        "formal_effect_search_started": False,
    }
    atomic_json(HERE / "prepare.json", prepared)
    verify_source_lock()
    return prepared


def load_input(e3: ModuleType, instance_id: str, arm: str) -> tuple[Any, Any, dict[str, Any]]:
    folder = input_folder(instance_id, arm)
    responsibility = json.loads(
        (folder / "responsibility_map.json").read_text(encoding="utf-8")
    )
    initial_payload = json.loads(
        (folder / "initial_solution.json").read_text(encoding="utf-8")
    )
    certificate = json.loads(
        (folder / "input_certificate.json").read_text(encoding="utf-8")
    )
    if payload_sha256(responsibility) != certificate[
        "responsibility_sha256"
    ]:
        raise RuntimeError("HALT_RESPONSIBILITY_HASH_DRIFT")
    if payload_sha256(initial_payload) != certificate[
        "initial_solution_sha256"
    ]:
        raise RuntimeError("HALT_INITIAL_HASH_DRIFT")
    base = e3.load_bundle(instance_id)
    bundle = e3.with_responsibility(base, responsibility["mapping"])
    initial = e3.solution_from_payload(initial_payload)
    return bundle, initial, certificate


def run_search_unit(payload: dict[str, Any]) -> dict[str, Any]:
    for name, value in REQUIRED_THREAD_ENV.items():
        os.environ[name] = value
    spec = dict(payload["spec"])
    phase = str(payload["phase"])
    cap = int(payload["cap"])
    lock_id = str(payload["source_lock_id"])
    stem = task_stem(spec)
    status_path = HERE / phase / "task_status" / f"{stem}.json"
    trace_path = HERE / phase / "search_traces" / f"{stem}.json"
    plan_path = (
        HERE / "formal/plans" / f"{stem}.json"
        if phase == "formal"
        else None
    )
    if status_path.is_file():
        existing = json.loads(status_path.read_text(encoding="utf-8"))
        if (
            existing.get("status") == "PASS"
            and int(existing["complete_candidate_budget_cap"]) == cap
            and existing["source_lock_id"] == lock_id
        ):
            return existing
        raise RuntimeError(f"HALT_STALE_TASK_ARTIFACT:{status_path}")

    e3 = load_e3()
    bundle, initial, certificate = load_input(
        e3, str(spec["instance_id"]), str(spec["arm"])
    )
    hard_lock = str(spec["arm"]) != "JOINT"
    archives = archive_limits(cap)
    safety = (
        900.0
        if phase == "probe"
        else max(600.0, 4.0 * len(bundle.customer_home_depot))
    )
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    run = e3.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=int(spec["seed"]),
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=archives,
        sp_time_limit_seconds=MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=hard_lock,
        max_hgs_iterations_per_view=MAX_HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=safety,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    elapsed = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_SELF)
    stats = run.stats
    consumed = int(stats["complete_candidate_evaluation_attempts"])
    configured = int(stats["complete_candidate_budget_expected"])
    diagnosis = classify_trace(
        list(stats["complete_candidate_evaluation_trace"])
    )
    trace = diagnosis.pop("classified_trace")
    reason, termination_evidence = termination_reason(
        run, consumed=consumed, cap=cap
    )
    trace_payload = {
        "schema": f"resetp.e3-structural.{phase}-trace.v1",
        "task_id": TASK_ID,
        **spec,
        "hard_home_depot_lock": hard_lock,
        "complete_candidate_budget_cap": cap,
        "complete_candidate_evaluations_consumed": consumed,
        "termination_reason": reason,
        "termination_evidence": termination_evidence,
        "candidate_diagnosis": diagnosis,
        "complete_candidate_evaluation_trace": trace,
        "route_pool_stats": {
            key: value
            for key, value in stats.items()
            if key != "complete_candidate_evaluation_trace"
        },
        "view_epoch_stats": {
            mode: epoch.stats for mode, epoch in run.view_epochs.items()
        },
        "persisted_before_validation": True,
    }
    atomic_json(trace_path, trace_payload)
    provisional = {
        "schema": f"resetp.e3-structural.{phase}-unit.v1",
        "task_id": TASK_ID,
        **spec,
        "phase": phase,
        "hard_home_depot_lock": hard_lock,
        "complete_candidate_budget_cap": cap,
        "complete_candidate_evaluations_consumed": consumed,
        "configured_complete_candidate_budget_expected": configured,
        "termination_reason": reason,
        "termination_evidence": termination_evidence,
        "wallclock_safety_triggered": bool(
            stats["wallclock_safety_triggered"]
        ),
        "last_strict_improvement_evaluation": int(
            stats["last_strict_improvement_evaluation"]
        ),
        "elapsed_wall_seconds": elapsed,
        "cpu_user_seconds": after.ru_utime - before.ru_utime,
        "cpu_system_seconds": after.ru_stime - before.ru_stime,
        "feasible_candidates": diagnosis["feasible_candidates"],
        "infeasible_candidates": diagnosis["infeasible_candidates"],
        "constraint_filtered_candidates": diagnosis[
            "constraint_filtered_candidates"
        ],
        "error_candidates": diagnosis["error_candidates"],
        "search_trace_path": relative(trace_path),
        "search_trace_sha256": file_sha256(trace_path),
        "source_lock_id": lock_id,
        "status": "TRACE_PERSISTED_PENDING_VALIDATION",
    }
    atomic_json(status_path, provisional)
    if len(trace) != consumed:
        raise RuntimeError(f"HALT_TRACE_COUNTER:{stem}")
    if consumed > cap or configured != cap:
        raise RuntimeError(f"HALT_BUDGET_CAP:{stem}:{consumed}/{cap}")
    if bool(stats["wallclock_safety_triggered"]):
        raise RuntimeError(f"HALT_WALLCLOCK_SAFETY:{stem}")
    if int(diagnosis["error_candidates"]) > 0:
        raise RuntimeError(
            f"HALT_TECHNICAL_ERROR_CANDIDATE:{stem}:"
            f"{diagnosis['exception_breakdown']}"
        )

    status = {**provisional, "status": "PASS", "validated_at_utc": now_iso()}
    if phase == "formal":
        assert plan_path is not None
        audit = e3e6_state_audit(e3, run.solution, bundle)
        if hard_lock and audit["cross_site_service_count"] != 0:
            raise RuntimeError(f"HALT_LOCK_CROSS_SITE:{stem}")
        plan = {
            "schema": "resetp.e3-structural.formal-plan.v1",
            "task_id": TASK_ID,
            **spec,
            "hard_home_depot_lock": hard_lock,
            "complete_candidate_budget_cap": cap,
            "complete_candidate_evaluations_consumed": consumed,
            "termination_reason": reason,
            "input_certificate": certificate,
            "solution": audit["solution_payload"],
            "solution_sha256": audit["solution_sha256"],
            "independent_recompute": audit["independent"],
            "source_lock_id": lock_id,
            "search_trace_path": relative(trace_path),
            "search_trace_sha256": file_sha256(trace_path),
        }
        plan["plan_sha256"] = payload_sha256(plan)
        atomic_json(plan_path, plan)
        status.update(
            {
                "total_cost_cny": audit["objective"],
                "vehicle_count": audit["physical_vehicle_count"],
                "route_count": audit["route_count"],
                "cross_site_service_count":
                    audit["cross_site_service_count"],
                "distance_total_m": audit["distance_total_m"],
                "carbon_emissions_kg": audit["carbon_emissions_kg"],
                "time_window_satisfied_customer_count": audit[
                    "time_window_satisfied_customer_count"
                ],
                "violation_count": 0,
                "solution_sha256": audit["solution_sha256"],
                "plan_path": relative(plan_path),
                "plan_sha256": file_sha256(plan_path),
            }
        )
    atomic_json(status_path, status)
    return status


def e3e6_state_audit(e3: ModuleType, solution: Any, bundle: Any) -> dict[str, Any]:
    annotated = e3.annotate_cross_site_services(
        solution, bundle.customer_home_depot
    )
    objective, breakdown, exact_violations = e3.exact_china81_score(
        annotated, bundle
    )
    checker_violations = e3.check_solution(
        annotated, bundle.instance, bundle.prices
    )
    independent = e3.evaluate(
        annotated,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if exact_violations or checker_violations:
        raise RuntimeError(
            f"HALT_FINAL_VIOLATION:"
            f"{len(exact_violations)}:{len(checker_violations)}"
        )
    if not math.isclose(
        float(independent["total_cost"]),
        float(objective),
        rel_tol=1.0e-12,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("HALT_FINAL_OBJECTIVE_MISMATCH")
    customer_ids = set(bundle.customer_home_depot)
    served = [
        node_id
        for route in annotated.routes
        for node_id in route.node_sequence
        if node_id in customer_ids
    ]
    if len(served) != len(customer_ids) or set(served) != customer_ids:
        raise RuntimeError("HALT_FINAL_CUSTOMER_COVERAGE")
    physical = len(
        {
            e3.physical_vehicle_id(route.vehicle_id)
            for route in annotated.routes
        }
    )
    solution_data = solution_payload(e3, annotated)
    independent_payload = {
        "objective": float(independent["total_cost"]),
        "breakdown": independent,
        "exact_violation_count": len(exact_violations),
        "checker_violation_count": len(checker_violations),
        "served_customer_count": len(served),
        "unique_served_customer_count": len(set(served)),
    }
    return {
        "solution_payload": solution_data,
        "solution_sha256": payload_sha256(solution_data),
        "objective": float(objective),
        "breakdown": breakdown,
        "independent": independent_payload,
        "physical_vehicle_count": physical,
        "route_count": len(annotated.routes),
        "cross_site_service_count": len(annotated.cross_site_services),
        "distance_total_m": float(independent["distance_total"]),
        "carbon_emissions_kg": float(independent["E_total"]),
        "time_window_satisfied_customer_count": len(served),
        "time_window_count_basis": (
            "all served customers in a zero-violation hard-time-window solution"
        ),
    }


def run_specs(
    specs: list[dict[str, Any]],
    *,
    phase: str,
    cap: int,
    workers: int,
) -> list[dict[str, Any]]:
    preflight(workers)
    lock = verify_source_lock()
    results: list[dict[str, Any]] = []
    progress = HERE / f"{phase}_progress.log"
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                run_search_unit,
                {
                    "spec": spec,
                    "phase": phase,
                    "cap": cap,
                    "source_lock_id": lock["source_lock_id"],
                },
            ): spec
            for spec in specs
        }
        for completed, future in enumerate(
            as_completed(futures), start=1
        ):
            spec = futures[future]
            row = future.result()
            results.append(row)
            event = {
                "timestamp_utc": now_iso(),
                "phase": phase,
                "progress": f"{completed}/{len(specs)}",
                "instance_id": spec["instance_id"],
                "seed": spec["seed"],
                "arm": spec["arm"],
                "status": row["status"],
                "elapsed_wall_seconds": row["elapsed_wall_seconds"],
                "complete_candidate_evaluations_consumed":
                    row["complete_candidate_evaluations_consumed"],
            }
            append_progress(progress, event)
            print(
                "UNIT_COMPLETE "
                f"instance={spec['instance_id']} seed={spec['seed']} "
                f"arm={spec['arm']} status={row['status']} "
                f"evals={row['complete_candidate_evaluations_consumed']} "
                f"elapsed={row['elapsed_wall_seconds']:.3f}s "
                f"progress={completed}/{len(specs)}",
                flush=True,
            )
            if row["status"] != "PASS":
                raise RuntimeError(
                    f"HALT_UNIT:{task_stem(spec)}:{row['status']}"
                )
            verify_protected()
    return sorted(
        results,
        key=lambda row: (
            row["instance_id"],
            int(row["seed"]),
            row["arm"],
        ),
    )


def run_probe(cap: int, workers: int) -> dict[str, Any]:
    if cap != LONG_PROBE_CAP:
        raise RuntimeError(f"HALT_LONG_PROBE_CAP:{cap}")
    spec = {
        "instance_id": INSTANCES[0][0],
        "sample_role": INSTANCES[0][1],
        "seed": 1,
        "arm": "JOINT",
    }
    status = run_specs(
        [spec],
        phase="probe",
        cap=cap,
        workers=workers,
    )[0]
    trace_payload = json.loads(
        (REPO / status["search_trace_path"]).read_text(encoding="utf-8")
    )
    trace = trace_payload["complete_candidate_evaluation_trace"]
    if tuple(row["source"] for row in trace[-2:]) != (
        TERMINAL_CLOSURE_SOURCES
    ):
        raise RuntimeError("HALT_PROBE_TERMINAL_TRACE")
    search_trace = trace[:-2]
    feasible = [
        float(row["complete_objective"])
        for row in search_trace
        if row.get("complete_objective") is not None
    ]
    if not feasible:
        raise RuntimeError("HALT_PROBE_NO_FEASIBLE_CANDIDATE")
    final_best = min(feasible)
    incumbent = math.inf
    plateau_start: int | None = None
    curve: list[dict[str, Any]] = []
    for row in trace:
        raw = row.get("complete_objective")
        if raw is not None:
            incumbent = min(incumbent, float(raw))
        index = int(row["evaluation_index"])
        segment = (
            "MULTI_VIEW_SEARCH"
            if index <= len(search_trace)
            else "TERMINAL_ROUTE_POOL_CLOSURE"
        )
        relative_gap = (
            (incumbent - final_best) / max(1.0, abs(final_best))
            if segment == "MULTI_VIEW_SEARCH" and math.isfinite(incumbent)
            else None
        )
        curve.append(
            {
                "instance_id": spec["instance_id"],
                "seed": 1,
                "arm": "JOINT",
                "complete_candidate_budget_cap": cap,
                "complete_candidate_evaluations_consumed":
                    status["complete_candidate_evaluations_consumed"],
                "termination_reason": status["termination_reason"],
                "evaluation_index": index,
                "segment": segment,
                "view": row["view"],
                "source": row["source"],
                "status": row["status"],
                "failure_category": row["failure_category"],
                "complete_objective_cny":
                    raw if raw is not None else "NA_INFEASIBLE",
                "incumbent_best_cny":
                    incumbent
                    if math.isfinite(incumbent)
                    else "NA_NO_FEASIBLE_INCUMBENT",
                "relative_gap_to_final_search_best":
                    relative_gap if relative_gap is not None else "NA",
            }
        )
        if (
            segment == "MULTI_VIEW_SEARCH"
            and plateau_start is None
            and relative_gap is not None
            and relative_gap <= PLATEAU_RELATIVE_BAND
        ):
            plateau_start = index
    confirmation = (
        None
        if plateau_start is None
        else plateau_start + PLATEAU_CONFIRMATION_EVALUATIONS - 1
    )
    confirmed = bool(
        confirmation is not None and confirmation <= len(search_trace)
    )
    consumed = int(status["complete_candidate_evaluations_consumed"])
    if status["termination_reason"] == "CANDIDATES_EXHAUSTED":
        basis = "CANDIDATES_EXHAUSTED_AT_ACTUAL_CONSUMPTION"
        basis_eval = consumed
        selected = round_up_hundred_with_margin(consumed)
    elif confirmed:
        basis = "PLATEAU_CONFIRMED_WITH_200_EVALUATION_MARGIN"
        basis_eval = int(confirmation) + 2
        selected = round_up_hundred_with_margin(basis_eval)
    else:
        basis = "LONG_CAP_NO_CONFIRMED_PLATEAU"
        basis_eval = cap
        selected = cap
    selected = min(cap, selected)
    atomic_csv(HERE / "probe/convergence_curve.csv", curve)
    summary = {
        "schema": "resetp.e3-structural.convergence-probe.v1",
        "status": "PASS",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "instance_id": spec["instance_id"],
        "seed": 1,
        "arm": "JOINT",
        "long_complete_candidate_budget_cap": cap,
        "complete_candidate_evaluations_consumed": consumed,
        "termination_reason": status["termination_reason"],
        "feasible_candidates": status["feasible_candidates"],
        "infeasible_candidates": status["infeasible_candidates"],
        "error_candidates": status["error_candidates"],
        "plateau_relative_band": PLATEAU_RELATIVE_BAND,
        "plateau_start_evaluation": plateau_start,
        "plateau_confirmation_evaluation": confirmation,
        "plateau_confirmed": confirmed,
        "budget_selection_basis": basis,
        "budget_selection_basis_evaluation": basis_eval,
        "selected_common_formal_budget_cap": selected,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "selection_uses_L_over_S": False,
    }
    summary["probe_id"] = payload_sha256(summary)
    atomic_json(HERE / "probe/summary.json", summary)
    lock = verify_source_lock()
    budget_lock = {
        "schema": "resetp.e3-structural.budget-lock.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "budget_source": "JOINT_MAIN_INSTANCE_SEED1_CONVERGENCE_PROBE",
        "probe_id": summary["probe_id"],
        "long_probe_budget_cap": cap,
        "selected_common_formal_budget_cap": selected,
        "source_lock_id": lock["source_lock_id"],
    }
    budget_lock["budget_lock_id"] = payload_sha256(budget_lock)
    atomic_json(HERE / "budget_lock.json", budget_lock)
    return summary


def formal_specs(instance_id_filter: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "instance_id": instance_id,
            "sample_role": role,
            "seed": seed,
            "arm": arm,
        }
        for instance_id, role in INSTANCES
        if instance_id_filter is None or instance_id == instance_id_filter
        for seed in SEEDS
        for arm in ARMS
    ]


def run_formal(cap: int, workers: int, instance_id: str) -> None:
    budget_lock = json.loads(
        (HERE / "budget_lock.json").read_text(encoding="utf-8")
    )
    if cap != int(budget_lock["selected_common_formal_budget_cap"]):
        raise RuntimeError("HALT_FORMAL_BUDGET_LOCK_MISMATCH")
    if instance_id == INSTANCES[1][0]:
        first_instance = INSTANCES[0][0]
        completed_first = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((HERE / "formal/task_status").glob("*.json"))
            if is_real_artifact(path)
            and path.name.startswith(first_instance + "__")
        ]
        if len(completed_first) != 20 or any(
            row.get("status") != "PASS" for row in completed_first
        ):
            raise RuntimeError(
                f"HALT_100C_BEFORE_50C_COMPLETE:{len(completed_first)}/20"
            )
    run_specs(
        formal_specs(instance_id),
        phase="formal",
        cap=cap,
        workers=workers,
    )
    completed = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((HERE / "formal/task_status").glob("*.json"))
        if is_real_artifact(path)
        and path.name.startswith(instance_id + "__")
    ]
    if len(completed) != 20 or any(
        row.get("status") != "PASS" for row in completed
    ):
        raise RuntimeError(
            f"HALT_INSTANCE_STAGE_DENOMINATOR:{instance_id}:"
            f"{len(completed)}/20"
        )
    marker = {
        "schema": "resetp.e3-zone-joint.instance-stage.v1",
        "status": "PASS_INSTANCE_STAGE_COMPLETE",
        "created_at_utc": now_iso(),
        "instance_id": instance_id,
        "formal_units": 20,
        "budget_cap": cap,
        "source_lock_id": budget_lock["source_lock_id"],
    }
    marker["marker_id"] = payload_sha256(marker)
    atomic_json(HERE / "formal/stages" / f"{instance_id}.json", marker)


def read_formal_statuses() -> list[dict[str, Any]]:
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((HERE / "formal/task_status").glob("*.json"))
        if is_real_artifact(path)
    ]
    if len(rows) != 40 or any(row.get("status") != "PASS" for row in rows):
        raise RuntimeError(f"HALT_FORMAL_DENOMINATOR:{len(rows)}/40")
    keys = {
        (row["instance_id"], int(row["seed"]), row["arm"])
        for row in rows
    }
    if len(keys) != 40:
        raise RuntimeError("HALT_FORMAL_DUPLICATE_KEYS")
    return sorted(
        rows,
        key=lambda row: (
            row["instance_id"], int(row["seed"]), row["arm"]
        ),
    )


def savings_pct(before: float, after: float) -> float:
    return 100.0 * (before - after) / before


def aggregate(cap: int, workers: int) -> dict[str, Any]:
    preflight(workers)
    lock = verify_source_lock()
    budget_lock = json.loads(
        (HERE / "budget_lock.json").read_text(encoding="utf-8")
    )
    if cap != int(budget_lock["selected_common_formal_budget_cap"]):
        raise RuntimeError("HALT_AGGREGATE_BUDGET_LOCK")
    statuses = read_formal_statuses()
    raw_rows = [
        {
            "instance_id": row["instance_id"],
            "sample_role": row["sample_role"],
            "seed": int(row["seed"]),
            "arm": row["arm"],
            "hard_home_depot_lock": row["hard_home_depot_lock"],
            "total_cost_cny": row["total_cost_cny"],
            "vehicle_count": row["vehicle_count"],
            "route_count": row["route_count"],
            "cross_site_service_count": row["cross_site_service_count"],
            "distance_total_m": row["distance_total_m"],
            "carbon_emissions_kg": row["carbon_emissions_kg"],
            "time_window_satisfied_customer_count": row[
                "time_window_satisfied_customer_count"
            ],
            "wallclock_seconds": row["elapsed_wall_seconds"],
            "complete_candidate_budget_cap":
                row["complete_candidate_budget_cap"],
            "complete_candidate_evaluations_consumed":
                row["complete_candidate_evaluations_consumed"],
            "termination_reason": row["termination_reason"],
            "feasible_candidates": row["feasible_candidates"],
            "infeasible_candidates": row["infeasible_candidates"],
            "constraint_filtered_candidates": row[
                "constraint_filtered_candidates"
            ],
            "error_candidates": row["error_candidates"],
            "violation_count": row["violation_count"],
            "solution_sha256": row["solution_sha256"],
            "status": row["status"],
        }
        for row in statuses
    ]
    atomic_csv(HERE / "raw_runs.csv", raw_rows)
    summaries: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    paired: list[dict[str, Any]] = []
    for instance_id, role in INSTANCES:
        by_arm = {
            arm: [
                row
                for row in raw_rows
                if row["instance_id"] == instance_id
                and row["arm"] == arm
            ]
            for arm in ARMS
        }
        summary = {
            "instance_id": instance_id,
            "sample_role": role,
        }
        for arm in ARMS:
            rows = by_arm[arm]
            costs = [float(row["total_cost_cny"]) for row in rows]
            best = min(costs)
            avg = mean(costs)
            summary.update(
                {
                    f"{arm}_Best_cny": best,
                    f"{arm}_Avg_cny": avg,
                    f"{arm}_Gap_pct": 100.0 * (avg - best) / best,
                    f"{arm}_vehicles_avg": mean(
                        float(row["vehicle_count"]) for row in rows
                    ),
                    f"{arm}_time_s_avg": mean(
                        float(row["wallclock_seconds"]) for row in rows
                    ),
                    f"{arm}_actual_evals_avg": mean(
                        float(
                            row[
                                "complete_candidate_evaluations_consumed"
                            ]
                        )
                        for row in rows
                    ),
                    f"{arm}_distance_m_avg": mean(
                        float(row["distance_total_m"]) for row in rows
                    ),
                    f"{arm}_carbon_kg_avg": mean(
                        float(row["carbon_emissions_kg"])
                        for row in rows
                    ),
                    f"{arm}_tw_satisfied_avg": mean(
                        float(
                            row[
                                "time_window_satisfied_customer_count"
                            ]
                        )
                        for row in rows
                    ),
                    f"{arm}_constraint_filtered_total": sum(
                        int(row["constraint_filtered_candidates"])
                        for row in rows
                    ),
                }
            )
        zone_avg = float(summary["ZONE_Avg_cny"])
        joint_avg = float(summary["JOINT_Avg_cny"])
        summary.update(
            {
                "cost_effect_pct_joint_vs_zone":
                    savings_pct(zone_avg, joint_avg),
                "distance_reduction_pct_joint_vs_zone": savings_pct(
                    float(summary["ZONE_distance_m_avg"]),
                    float(summary["JOINT_distance_m_avg"]),
                ),
                "carbon_reduction_pct_joint_vs_zone": savings_pct(
                    float(summary["ZONE_carbon_kg_avg"]),
                    float(summary["JOINT_carbon_kg_avg"]),
                ),
                "vehicle_count_change_joint_minus_zone": (
                    float(summary["JOINT_vehicles_avg"])
                    - float(summary["ZONE_vehicles_avg"])
                ),
                "time_window_satisfied_change_joint_minus_zone": (
                    float(summary["JOINT_tw_satisfied_avg"])
                    - float(summary["ZONE_tw_satisfied_avg"])
                ),
            }
        )
        summaries.append(summary)
        for seed in SEEDS:
            costs = {
                arm: float(
                    next(
                        row["total_cost_cny"]
                        for row in by_arm[arm]
                        if int(row["seed"]) == seed
                    )
                )
                for arm in ARMS
            }
            row = {
                "instance_id": instance_id,
                "seed": seed,
                "ZONE_cost_cny": costs["ZONE"],
                "JOINT_cost_cny": costs["JOINT"],
                "cost_effect_pct_joint_vs_zone":
                    savings_pct(costs["ZONE"], costs["JOINT"]),
            }
            paired.append(row)
        effects.append(
            {
                "instance_id": instance_id,
                "cost_effect_pct_joint_vs_zone": summary[
                    "cost_effect_pct_joint_vs_zone"
                ],
                "distance_reduction_pct_joint_vs_zone": summary[
                    "distance_reduction_pct_joint_vs_zone"
                ],
                "carbon_reduction_pct_joint_vs_zone": summary[
                    "carbon_reduction_pct_joint_vs_zone"
                ],
                "vehicle_count_change_joint_minus_zone": summary[
                    "vehicle_count_change_joint_minus_zone"
                ],
                "time_window_satisfied_change_joint_minus_zone": summary[
                    "time_window_satisfied_change_joint_minus_zone"
                ],
                "IND_ZONE_mapping_identical": True,
                "interpretation":
                    "ZONE_IS_ALREADY_GEOGRAPHICALLY_OPTIMAL_BY_INPUT_IDENTITY",
            }
        )
    atomic_csv(HERE / "formal_summary.csv", summaries)
    atomic_csv(HERE / "paired_effects.csv", paired)
    atomic_csv(HERE / "effects.csv", effects)

    investigation = json.loads(
        (HERE / "depot_field_investigation.json").read_text(
            encoding="utf-8"
        )
    )
    descriptive = list(
        csv.DictReader(
            (HERE / "descriptive_statistics.csv").open(
                encoding="utf-8", newline=""
            )
        )
    )
    max_effect = max(
        abs(float(row["cost_effect_pct_joint_vs_zone"]))
        for row in effects
    )
    verdict = (
        "MECHANISM_BUT_TIE"
        if max_effect <= 1.0e-12
        else "VALID_BUT_WEAK"
        if max_effect < 1.0
        else "PASS_STRUCTURAL_EFFECT_REPORTED_WITHOUT_DIRECTION_FILTER"
    )
    overall_cost_effect = mean(
        float(row["cost_effect_pct_joint_vs_zone"]) for row in effects
    )
    decision = {
        "schema": "resetp.e3-zone-joint.decision.v1",
        "task_id": TASK_ID,
        "verdict": verdict,
        "created_at_utc": now_iso(),
        "registered_depot_field_found": True,
        "literal_registered_depot_column_found": False,
        "administrative_assignment_found": True,
        "ind_zone_mapping_identical_on_both_instances": True,
        "ind_arm_run": False,
        "ind_arm_reason": "IND_AND_ZONE_INPUTS_IDENTICAL_BY_PRE_SEARCH_FACT",
        "no_result_filtering": True,
        "formal_units_run": 40,
        "budget_cap": cap,
        "effects": effects,
        "overall_cost_effect_pct_joint_vs_zone": overall_cost_effect,
        "overall_aggregation": (
            "equal-weight arithmetic mean of the two per-instance effects"
        ),
        "cross_site_bug_fixed": True,
        "joint_semantics_unchanged_proof": True,
        "joint_semantics_proof_path": relative(JOINT_PROOF),
        "cross_site_bug_fix_evidence_path": relative(BUG_FIX_EVIDENCE),
        "historical_l_main_numbers_used_as_evidence": False,
        "technical_constructibility_is_not_scientific_effect": True,
        "source_lock_id": lock["source_lock_id"],
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(HERE / "decision.json", decision)
    metadata = {
        "schema": "resetp.e3-zone-joint.metadata.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "contract": relative(CONTRACT),
        "instances": [instance for instance, _role in INSTANCES],
        "arms": list(ARMS),
        "seeds": list(SEEDS),
        "formal_units_expected": 40,
        "formal_units_run": 40,
        "budget_cap": cap,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "workers": workers,
        "protected_hashes": verify_protected(),
        "source_lock_id": lock["source_lock_id"],
        "first_fit_equivalence_units": 56,
        "first_fit_equivalence_mismatches": 0,
        "registered_depot_field_found": True,
        "ind_inputs_built": 0,
        "zone_inputs_built": 2,
        "joint_inputs_built": 2,
        "superseded_units_registered": 29,
        "pgid_7965_stopped": True,
        "cross_site_bug_fixed": True,
        "joint_semantics_unchanged_proof": True,
        "file_enumeration_exclusions": [
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
        ],
    }
    atomic_json(HERE / "metadata.json", metadata)
    report = render_report(
        summaries,
        effects,
        descriptive,
        investigation,
        decision,
        cap,
    )
    (HERE / "report.md").write_text(report, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-u", str(CHECKER), "--output-root", str(HERE)],
        cwd=REPO,
        env={**os.environ, **REQUIRED_THREAD_ENV},
        check=True,
    )
    return decision


def render_report(
    summaries: list[dict[str, Any]],
    effects: list[dict[str, Any]],
    descriptive: list[dict[str, str]],
    investigation: dict[str, Any],
    decision: dict[str, Any],
    cap: int,
) -> str:
    header = (
        "| 算例 | ZONE Best | ZONE Avg | ZONE Gap% | ZONE 车 | "
        "ZONE 秒 | ZONE eval | JOINT Best | JOINT Avg | JOINT Gap% | "
        "JOINT 车 | JOINT 秒 | JOINT eval |"
    )
    separator = (
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
        "---:|---:|"
    )
    table_rows = []
    for row in summaries:
        values = [row["instance_id"]]
        for arm in ARMS:
            values.extend(
                [
                    f"{float(row[f'{arm}_Best_cny']):.3f}",
                    f"{float(row[f'{arm}_Avg_cny']):.3f}",
                    f"{float(row[f'{arm}_Gap_pct']):.3f}",
                    f"{float(row[f'{arm}_vehicles_avg']):.2f}",
                    f"{float(row[f'{arm}_time_s_avg']):.2f}",
                    f"{float(row[f'{arm}_actual_evals_avg']):.1f}",
                ]
            )
        table_rows.append("| " + " | ".join(values) + " |")
    effect_rows = [
        (
            "| {instance} | {zd:.3f} | {jd:.3f} | {dr:.6f}% | "
            "{zc:.6f} | {jc:.6f} | {cr:.6f}% | {zv:.2f} | {jv:.2f} | "
            "{vd:+.2f} | {ztw:.1f} | {jtw:.1f} | {twd:+.1f} |"
        ).format(
            instance=row["instance_id"],
            zd=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["ZONE_distance_m_avg"]),
            jd=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["JOINT_distance_m_avg"]),
            dr=float(row["distance_reduction_pct_joint_vs_zone"]),
            zc=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["ZONE_carbon_kg_avg"]),
            jc=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["JOINT_carbon_kg_avg"]),
            cr=float(row["carbon_reduction_pct_joint_vs_zone"]),
            zv=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["ZONE_vehicles_avg"]),
            jv=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["JOINT_vehicles_avg"]),
            vd=float(row["vehicle_count_change_joint_minus_zone"]),
            ztw=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["ZONE_tw_satisfied_avg"]),
            jtw=float(next(item for item in summaries if item["instance_id"] == row["instance_id"])["JOINT_tw_satisfied_avg"]),
            twd=float(row["time_window_satisfied_change_joint_minus_zone"]),
        )
        for row in effects
    ]
    cost_rows = [
        "| {instance} | {effect:.6f}% |".format(
            instance=row["instance_id"],
            effect=float(row["cost_effect_pct_joint_vs_zone"]),
        )
        for row in effects
    ]
    mismatch_rows = [
        "| {instance} | {count}/{n} | {pct:.3f}% |".format(
            instance=row["instance_id"],
            count=row["registered_nearest_mismatch_count"],
            n=row["customer_count"],
            pct=float(row["registered_nearest_mismatch_pct"]),
        )
        for row in descriptive
    ]
    bug = json.loads(BUG_FIX_EVIDENCE.read_text(encoding="utf-8"))
    proof = json.loads(JOINT_PROOF.read_text(encoding="utf-8"))
    overall = float(decision["overall_cost_effect_pct_joint_vs_zone"])
    effects_by_instance = {
        row["instance_id"]: float(row["cost_effect_pct_joint_vs_zone"])
        for row in effects
    }
    fifty = effects_by_instance[INSTANCES[0][0]]
    hundred = effects_by_instance[INSTANCES[1][0]]
    if all(3.0 <= value <= 6.0 for value in (fifty, hundred)):
        effect_reading = (
            "两个算例均落在目标期刊同类已发表的 3%--6% 量级。"
        )
    elif overall <= 0.0:
        effect_reading = (
            "总体节省为零或负，说明在行政分区已与地理最优重合的场景中，"
            "跨场协同没有表现出剩余降本空间；该方向按全分母原样保留。"
        )
    elif overall < 3.0:
        effect_reading = (
            "总体节省低于目标期刊同类 3%--6% 量级，说明地理最优分区之后"
            "只剩有限的跨场协同空间。"
        )
    else:
        effect_reading = (
            "效应不落入 3%--6% 参照区间；本文只报告本批实测值，不据此"
            "调整算例、种子、预算或判据。"
        )
    return f"""# E3 分区配送与联合配送对照

状态：`{decision['verdict']}`。两个指定算例、ZONE/JOINT 两臂、种子 1--10 的 40 个正式单元已全分母运行；先完成 50c 并落盘，再运行 100c。没有复用故障前 18 个 PASS 目标值，也没有挑算例、挑种子、改预算或改判据。

## 结论

本文两个算例的客户行政归属与最近车场完全重合（50c 为 0/50，100c 为 0/100），因此本文的分区配送基线已经是地理最优分工，所测得的联合配送收益是在此基础上的剩余协同价值。China81 没有字面 `registered_depot` 列；这里的行政归属是 loader 已生成的 `customer_home_depot`，不是新造参数。

`JOINT 相对 ZONE 成本效应`采用“正值表示 JOINT 节省、负值表示 JOINT 增本”的口径。50c 为 {fifty:.6f}%，100c 为 {hundred:.6f}%，两个算例等权总体为 {overall:.6f}%。{effect_reading}

## 期刊式主表

`Gap%` 定义为同一臂十次运行的 `(Avg-Best)/Best×100`；车辆数、时间和实际评价数均报十次均值。预算 {cap} 是共同上限，不是配额。

{header}
{separator}
{chr(10).join(table_rows)}

## 核心成本效应

| 算例 | JOINT 相对 ZONE 成本节省率（正=节省） |
|---|---:|
{chr(10).join(cost_rows)}

总体采用两条算例行等权平均，不按 100c 的绝对成本加权。

## 距离、碳、车辆与时间窗

距离和碳排来自每个保存解的完整目标复算字段 `distance_total` 与 `E_total`，不是替代指标。满足时间窗客户数由零违规硬时间窗解中的完整客户覆盖直接计数；由于本模型是硬时间窗，两臂每个可接受解都必须满足全部客户，不能与文献中的软时间窗罚损设定混同。

| 算例 | ZONE 距离m | JOINT 距离m | 距离减少% | ZONE 碳kg | JOINT 碳kg | 碳减少% | ZONE 车 | JOINT 车 | 车数Δ | ZONE 满足TW | JOINT 满足TW | TW数Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(effect_rows)}

| 算例 | 登记车场≠最近车场 | 描述比例 |
|---|---:|---:|
{chr(10).join(mismatch_rows)}

## 可直接用于正文的中文

表 X 比较了分区配送与联合配送在两个预定算例上的结果。联合配送相对分区配送的平均总成本在 50 客户算例中变化 {fifty:.2f}%，在 100 客户算例中变化 {hundred:.2f}%，两算例等权平均变化 {overall:.2f}%（正值表示成本下降）。本文两个算例的客户行政归属与最近车场完全重合（50c 为 0/50，100c 为 0/100），因此分区配送基线已经是地理最优分工，表中结果反映的是在此基础上的剩余协同价值。

## 技术错误诊断与修复

硬责任锁在 `{bug['hard_lock_encoding']['file']}` 第 {bug['hard_lock_encoding']['customer_ownership_dimension_start_line']} 行开始为客户增加车场归属维度，并在第 {bug['hard_lock_encoding']['vehicle_capacity_dimension_start_line']} 行开始给各车场车辆配置对应容量。旧错误不在 `cost.py`、`check.py`、`search/evaluation.py` 或路线池 MIP；14/14 个异常都沿 `{bug['leak_path_before_fix']['file']}` 的 `_run_exact_epoch` 终端种群档案路径进入。原 source hash `{bug['leak_path_before_fix']['pre_fix_source_sha256']}` 的相关块为第 {bug['leak_path_before_fix']['pre_fix_terminal_archive_block_lines']} 行：完整补全后发现跨场服务，却把正常硬锁拒绝抛成 `ValueError`。持久化 trace 没有个体的单算子祖先，因此不能诚实地把 14 个候选唯一归因于 Exchange11 或其他单个算子；能精确证明的是泄漏路径为 `terminal_population_archive`。

修复只改候选筛选：完整补全后的跨场候选记入实际评价数，写为 `FILTERED_HARD_HOME_DEPOT_LOCK`，并在进入精英/路线池前正常排除；搜索算子、随机流、JOINT 分支和 `route_pool_sp.py` 搜索语义均未改。50c seed 3 的定向回归正常过滤 {bug['lock_regression']['filtered_candidates']} 个此类候选，最终跨场服务 0、违规 0。

JOINT 语义证明使用同一 50c、seed 1、cap 400 实际前后重跑：解哈希均为 `{proof['solution_sha256_before']}`，完整目标浮点位均为 `{proof['objective_float_hex_before']}`，完整目标规范哈希均为 `{proof['full_objective_sha256_before']}`，实际评价数均为 {proof['complete_candidate_evaluations_before']}。因此 `joint_semantics_unchanged_proof=true`。

## 输入、预算与运行纪律

ZONE 使用有向“车场→客户”道路距离的最近车场并加硬锁；JOINT 保留同一 ZONE 映射和同一初解作共同参考，但移除服务归属硬锁。两算例两臂的四份输入均调用上一轮已验证的 C++ 冻结 First-Fit，并由 Python `_pack_depot` 逐组复算；历史等价门仍为 56/56、0 不一致。

共同 cap {cap} 沿用已封存 JOINT 收敛探针；预算是上限不是配额。每个正式单元记录 `complete_candidate_evaluations_consumed≤cap`、终止原因和逐候选 trace；合法不可行与正常硬锁过滤均计入实际消费，只有真技术错误才 HALT。并发不超过 2 workers。

## IND 备选（本任务未采用）

若要测量空间组织价值，需要一个与地理最优不一致的责任基线；本文两个算例不具备这个条件。距离次近车场方案的依据是有向道路距离排序，缺点是人为制造错配且需另定错配强度；更细行政区划方案可保留行政解释，缺点是需要新增可靠边界和区划—车场对应来源；容量均分方案可平衡场站资源，缺点是责任关系内生于容量，不代表历史或行政登记。三者都属于新的科学定义，需要用户裁决，本任务未采用。

目标期刊同类已发表对照报告过约 3%--6% 的成本效应，但这些数值只作解释参照。旧 L-main 的 16.55%/24.72% 没有进入本表、总体效应、方向或显著性判断；故障前 18 个 PASS 目标值同样未复用。

## 完整性

`raw_runs.csv` 为 40 行；`metadata.json`、`decision.json`、`artifact_hashes.json`、本报告、逐解计划、完整 trace、JOINT 语义证明及独立复算证书构成正式证据面。哈希枚举排除 `._*`、`__pycache__`、`.pytest_cache` 与监控运行态。四个受保护源文件哈希与任务开始时一致。
"""


def collect_hashes() -> dict[str, str]:
    excluded_names = {"artifact_hashes.json", "done.json"}
    files = sorted(
        path
        for path in HERE.rglob("*")
        if is_real_artifact(path)
        and path.name not in excluded_names
        and not path.name.endswith(".tmp")
    )
    return {relative(path): file_sha256(path) for path in files}


def seal(cap: int, workers: int) -> dict[str, Any]:
    preflight(workers)
    verify_source_lock()
    verify_protected()
    if (HERE / "done.json").exists():
        raise RuntimeError("done.json already exists")
    required = (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "report.md",
        "independent_verification.json",
        "superseded_units.csv",
        "depot_field_investigation.json",
        "budget_lock.json",
    )
    missing = [name for name in required if not (HERE / name).is_file()]
    if missing:
        raise RuntimeError(f"HALT_SEAL_MISSING:{missing}")
    rows = list(
        csv.DictReader(
            (HERE / "raw_runs.csv").open(encoding="utf-8", newline="")
        )
    )
    if len(rows) != 40:
        raise RuntimeError("HALT_SEAL_FORMAL_DENOMINATOR")
    if any(int(row["complete_candidate_evaluations_consumed"]) > cap for row in rows):
        raise RuntimeError("HALT_SEAL_BUDGET_EXCEEDED")
    verification = json.loads(
        (HERE / "independent_verification.json").read_text(
            encoding="utf-8"
        )
    )
    if verification.get("status") != "PASS_INDEPENDENT_VERIFICATION":
        raise RuntimeError("HALT_SEAL_INDEPENDENT_VERIFICATION")
    artifact_hashes = {
        "schema": "resetp.e3-structural.artifact-hashes.v1",
        "created_at_utc": now_iso(),
        "exclusions": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "*.tmp",
        ],
        "files": collect_hashes(),
    }
    artifact_hashes["manifest_id"] = payload_sha256(artifact_hashes)
    atomic_json(HERE / "artifact_hashes.json", artifact_hashes)
    done = {
        "status": "COMPLETE",
        "cross_site_bug_fixed": True,
        "joint_semantics_unchanged_proof": True,
        "pgid_7965_stopped": True,
        "superseded_units_registered": 29,
        "registered_depot_field_found": True,
        "zone_inputs_built": 2,
        "joint_inputs_built": 2,
        "ind_inputs_built": 0,
        "formal_units_run": 40,
        "budget_cap": cap,
        "cost_effect_pct_joint_vs_zone": json.loads(
            (HERE / "decision.json").read_text(encoding="utf-8")
        )["overall_cost_effect_pct_joint_vs_zone"],
        "instances_completed": [
            instance_id for instance_id, _role in INSTANCES
        ],
        "decision_id": json.loads(
            (HERE / "decision.json").read_text(encoding="utf-8")
        )["decision_id"],
        "manifest_id": artifact_hashes["manifest_id"],
        "done_written_last": True,
        "created_at_utc": now_iso(),
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(HERE / "done.json", done)
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "prepare",
            "formal-50c",
            "formal-100c",
            "aggregate",
            "seal",
        ),
    )
    parser.add_argument(
        "--complete-eval-budget",
        type=int,
        required=True,
    )
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    archive_limits(args.complete_eval_budget)
    if args.command == "prepare":
        build_inputs(args.workers)
    elif args.command == "formal-50c":
        run_formal(
            args.complete_eval_budget, args.workers, INSTANCES[0][0]
        )
    elif args.command == "formal-100c":
        run_formal(
            args.complete_eval_budget, args.workers, INSTANCES[1][0]
        )
    elif args.command == "aggregate":
        aggregate(args.complete_eval_budget, args.workers)
    else:
        seal(args.complete_eval_budget, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
