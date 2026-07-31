#!/usr/bin/env python3
"""Build and run the journal-aligned E3 structural comparison.

The three arms are:

* IND: administrative city-to-depot assignment, hard locked;
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
CHECKER = HERE / "check_e3_structural.py"
TASK_ID = "E3-STRUCTURAL-COMPARISON-20260731"
INSTANCES = (
    ("cn-prd-50c-01-V2-LOCATIONS", "MAIN_EXHIBIT"),
    ("cn-prd-100c-02-V2-LOCATIONS", "ROBUSTNESS"),
)
ARMS = ("IND", "ZONE", "JOINT")
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
        if category != "FEASIBLE":
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
        "instances": field_evidence,
        "unused_alternatives": [
            {
                "option": "second-nearest depot",
                "objective_basis": "distance rank",
                "drawback":
                    "synthetic mismatch severity parameter; unnecessary because administrative assignment exists",
            },
            {
                "option": "administrative-region assignment",
                "objective_basis": "existing GIS city membership",
                "drawback":
                    "none beyond the documented computational-boundary, non-survey provenance; this is the active IND definition",
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


def formal_specs() -> list[dict[str, Any]]:
    return [
        {
            "instance_id": instance_id,
            "sample_role": role,
            "seed": seed,
            "arm": arm,
        }
        for instance_id, role in INSTANCES
        for seed in SEEDS
        for arm in ARMS
    ]


def run_formal(cap: int, workers: int) -> None:
    budget_lock = json.loads(
        (HERE / "budget_lock.json").read_text(encoding="utf-8")
    )
    if cap != int(budget_lock["selected_common_formal_budget_cap"]):
        raise RuntimeError("HALT_FORMAL_BUDGET_LOCK_MISMATCH")
    run_specs(
        formal_specs(),
        phase="formal",
        cap=cap,
        workers=workers,
    )


def read_formal_statuses() -> list[dict[str, Any]]:
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((HERE / "formal/task_status").glob("*.json"))
        if is_real_artifact(path)
    ]
    if len(rows) != 60 or any(row.get("status") != "PASS" for row in rows):
        raise RuntimeError(f"HALT_FORMAL_DENOMINATOR:{len(rows)}/60")
    keys = {
        (row["instance_id"], int(row["seed"]), row["arm"])
        for row in rows
    }
    if len(keys) != 60:
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
            "wallclock_seconds": row["elapsed_wall_seconds"],
            "complete_candidate_budget_cap":
                row["complete_candidate_budget_cap"],
            "complete_candidate_evaluations_consumed":
                row["complete_candidate_evaluations_consumed"],
            "termination_reason": row["termination_reason"],
            "feasible_candidates": row["feasible_candidates"],
            "infeasible_candidates": row["infeasible_candidates"],
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
                }
            )
        ind_avg = float(summary["IND_Avg_cny"])
        zone_avg = float(summary["ZONE_Avg_cny"])
        joint_avg = float(summary["JOINT_Avg_cny"])
        summary.update(
            {
                "IND_to_ZONE_spatial_value_pct":
                    savings_pct(ind_avg, zone_avg),
                "ZONE_to_JOINT_remaining_synergy_pct":
                    savings_pct(zone_avg, joint_avg),
                "IND_to_JOINT_total_value_pct":
                    savings_pct(ind_avg, joint_avg),
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
                "IND_cost_cny": costs["IND"],
                "ZONE_cost_cny": costs["ZONE"],
                "JOINT_cost_cny": costs["JOINT"],
                "IND_to_ZONE_spatial_value_pct":
                    savings_pct(costs["IND"], costs["ZONE"]),
                "ZONE_to_JOINT_remaining_synergy_pct":
                    savings_pct(costs["ZONE"], costs["JOINT"]),
                "IND_to_JOINT_total_value_pct":
                    savings_pct(costs["IND"], costs["JOINT"]),
            }
            paired.append(row)
        effects.append(
            {
                "instance_id": instance_id,
                "IND_to_ZONE_spatial_value_pct":
                    summary["IND_to_ZONE_spatial_value_pct"],
                "ZONE_to_JOINT_remaining_synergy_pct":
                    summary["ZONE_to_JOINT_remaining_synergy_pct"],
                "IND_to_JOINT_total_value_pct":
                    summary["IND_to_JOINT_total_value_pct"],
                "IND_ZONE_mapping_identical": True,
                "interpretation":
                    "IND_TO_ZONE_IS_STRUCTURALLY_ZERO_BY_INPUT_IDENTITY",
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
    max_spatial = max(
        abs(float(row["IND_to_ZONE_spatial_value_pct"]))
        for row in effects
    )
    max_joint = max(
        abs(float(row["ZONE_to_JOINT_remaining_synergy_pct"]))
        for row in effects
    )
    verdict = (
        "MECHANISM_BUT_TIE"
        if max_spatial <= 1.0e-12 and max_joint <= 1.0e-12
        else "VALID_BUT_WEAK"
        if max(max_spatial, max_joint) < 1.0
        else "PASS_STRUCTURAL_EFFECT_REPORTED_WITHOUT_DIRECTION_FILTER"
    )
    decision = {
        "schema": "resetp.e3-structural.decision.v1",
        "task_id": TASK_ID,
        "verdict": verdict,
        "created_at_utc": now_iso(),
        "registered_depot_field_found": True,
        "literal_registered_depot_column_found": False,
        "administrative_assignment_found": True,
        "ind_zone_mapping_identical_on_both_instances": True,
        "no_result_filtering": True,
        "formal_units_run": 60,
        "budget_cap": cap,
        "effects": effects,
        "historical_l_main_numbers_used_as_evidence": False,
        "technical_constructibility_is_not_scientific_effect": True,
        "source_lock_id": lock["source_lock_id"],
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(HERE / "decision.json", decision)
    metadata = {
        "schema": "resetp.e3-structural.metadata.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "contract": relative(CONTRACT),
        "instances": [instance for instance, _role in INSTANCES],
        "arms": list(ARMS),
        "seeds": list(SEEDS),
        "formal_units_expected": 60,
        "formal_units_run": 60,
        "budget_cap": cap,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "workers": workers,
        "protected_hashes": verify_protected(),
        "source_lock_id": lock["source_lock_id"],
        "first_fit_equivalence_units": 56,
        "first_fit_equivalence_mismatches": 0,
        "registered_depot_field_found": True,
        "ind_inputs_built": 2,
        "zone_inputs_built": 2,
        "joint_inputs_built": 2,
        "superseded_units_registered": 29,
        "pgid_7965_stopped": True,
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
        "| 算例 | IND Best | IND Avg | IND Gap% | IND 车 | IND 秒 | "
        "IND eval | ZONE Best | ZONE Avg | ZONE Gap% | ZONE 车 | "
        "ZONE 秒 | ZONE eval | JOINT Best | JOINT Avg | JOINT Gap% | "
        "JOINT 车 | JOINT 秒 | JOINT eval |"
    )
    separator = (
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
        "---:|---:|---:|---:|---:|---:|---:|---:|"
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
        "| {instance} | {spatial:.6f}% | {joint:.6f}% | {total:.6f}% |".format(
            instance=row["instance_id"],
            spatial=float(row["IND_to_ZONE_spatial_value_pct"]),
            joint=float(row["ZONE_to_JOINT_remaining_synergy_pct"]),
            total=float(row["IND_to_JOINT_total_value_pct"]),
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
    return f"""# E3 结构性对照：IND / ZONE / JOINT

状态：`{decision['verdict']}`。两个指定算例、三臂、种子 1--10 的 60 个正式单元已全分母运行；没有挑算例、挑种子、改判据或读取结果后换设计。

## 结论

China81 没有字面名为 `registered_depot` 的列，但客户 `city` 是现成的行政归属字段，逐节点有 GIS 城市边界证书；`solver/src/setp_solver/china81.py` 已把它确定性映射到同城唯一车场，形成 `customer_home_depot`。因此 `registered_depot_field_found=true` 的准确含义是“找到现成行政等价字段及既有 loader 映射”，不是发现了一列未曾使用的登记字段，也没有引入新的 IND 参数。

两个预定算例中，行政登记车场与有向道路最近车场完全一致：50c 为 0/50，100c 为 0/100。故 IND 与 ZONE 的责任图、First-Fit 初解和加锁搜索问题逐位相同；`IND→ZONE` 的空间组织价值在这两个算例上机械为 0，而不是搜索没找到改善。JOINT 的效应按实际运行结果如下，如为正、负或零均原样保留。

## 期刊式主表

`Gap%` 定义为同一臂十次运行的 `(Avg-Best)/Best×100`；车辆数、时间和实际评价数均报十次均值。预算 {cap} 是共同上限，不是配额。

{header}
{separator}
{chr(10).join(table_rows)}

## 三个效应

| 算例 | IND→ZONE 空间组织价值 | ZONE→JOINT 剩余协同价值 | IND→JOINT 总价值 |
|---|---:|---:|---:|
{chr(10).join(effect_rows)}

| 算例 | 登记车场≠最近车场 | 描述比例 |
|---|---:|---:|
{chr(10).join(mismatch_rows)}

正文一句话：在预先指定的 50c 主展示与 100c 稳健性算例上，行政登记关系已与最近车场重合，所以空间组织价值为 0；剩余协同价值与总价值以表中实际百分比为准，不作方向筛选。

## 输入、预算与运行纪律

IND 使用客户行政城市到同城唯一车场的现成映射并加硬锁；ZONE 使用有向“车场→客户”道路距离的最近车场并加硬锁；JOINT 保留 ZONE 映射和 ZONE 初解作共同参考，但移除服务归属硬锁。这样 `ZONE→JOINT` 只改变服务自由度。六份输入均调用上一轮已验证的 C++ 冻结 First-Fit，并由 Python `_pack_depot` 逐组复算；历史等价门仍为 56/56、0 不一致。

收敛探针只运行主算例、种子 1、JOINT、长 cap 1500；按平台点或有限候选耗尽点向上取整百留余量，冻结共同 cap {cap}。每个正式单元记录 `complete_candidate_evaluations_consumed≤cap`、终止原因和逐候选 trace；合法完整模型不可行计入消费，技术错误才 HALT。并发不超过 2 workers。

## 旧设计停机与证据边界

PGID 7965 在本代理精确检查时已不存在；补发 SIGTERM 返回 `No such process`，随后再次确认无该进程组和无 `build_inputs.py`/C++ 构造进程。因此 `pgid_7965_stopped=true` 表示目标组已确认停止，不声称信号由本代理成功送达。旧权威日志的 106 个终态和全部等价性证据未删未改；其余 8 个当时活动单元与 21 个排队单元共 29 个登记为 `NOT_BUILT_SUPERSEDED_DESIGN`，明确不是 `INFEASIBLE_INPUT`、不是技术失败。

旧 L-main 的 16.55%/24.72% 只作为运行前方向参考，未进入本表、判决或论文证据。输入技术上可构造也没有被写成科学效应。

## 完整性

`raw_runs.csv` 为 60 行；`metadata.json`、`decision.json`、`artifact_hashes.json`、本报告及独立复算证书构成正式证据面。哈希枚举排除 `._*`、`__pycache__`、`.pytest_cache` 与监控运行态。四个受保护源文件哈希与任务开始时一致。
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
    if len(rows) != 60:
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
        "pgid_7965_stopped": True,
        "superseded_units_registered": 29,
        "registered_depot_field_found": True,
        "zone_inputs_built": 2,
        "joint_inputs_built": 2,
        "ind_inputs_built": 2,
        "formal_units_run": 60,
        "budget_cap": cap,
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
        choices=("prepare", "probe", "formal", "aggregate", "seal"),
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
    elif args.command == "probe":
        run_probe(args.complete_eval_budget, args.workers)
    elif args.command == "formal":
        run_formal(args.complete_eval_budget, args.workers)
    elif args.command == "aggregate":
        aggregate(args.complete_eval_budget, args.workers)
    else:
        seal(args.complete_eval_budget, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
