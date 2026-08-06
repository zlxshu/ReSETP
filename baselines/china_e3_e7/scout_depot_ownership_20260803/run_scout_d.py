#!/opt/anaconda3/bin/python3.13
"""SCOUT-D depot-ownership reassignment probe under the 2026-08-03 contract.

This is exploratory evidence only.  It never writes paper sources.  The
random-label baseline is halted before search when the public four-label
sequence cannot be mapped one-to-one to the selected two-depot instance.
The nearest-depot baseline continues independently, as required by the task
stop rule.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import multiprocessing as mp
import os
import platform
import statistics
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any


for _thread_var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_thread_var, "1")


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOLVER_SRC = REPO / "solver/src"
MODELS_SRC = REPO / "models/src"
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
PYVRP_SITE = (
    REPO
    / "build/python_envs/pyvrp-hgs-0.12.2/"
    "lib/python3.13/site-packages"
)
OLD_E3 = REPO / "baselines/china_e3_e7/e3_scattered_ownership_20260801"
SOURCE_SEQUENCE = OLD_E3 / "source_p_sequences.csv"
CAPACITY_ALIGNMENT_SOURCE = OLD_E3 / "run_e3_capacity_rank_aligned.py"
FLEET_AUTHORITY = (
    REPO
    / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
)
FLEET_EVIDENCE = REPO / "baselines/china_e3_e7/fleet_authority_v3_20260802"

for _path in reversed((REPO, PROTOTYPE, SOLVER_SRC, MODELS_SRC, PYVRP_SITE)):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    _physicalize_multitrip_solution,
    exact_china81_score,
)
from setp_solver.model_config import (  # noqa: E402
    ModelConfig,
    model_config_scope,
)
from setp_solver.solution import (  # noqa: E402
    Route,
    Solution,
    physical_vehicle_id,
)
from baselines.china_e3_e7.e3_scattered_ownership_20260801.run_e3_capacity_rank_aligned import (  # noqa: E402,E501
    capacity_rank_alignment,
)


SCHEMA = "resetp.scout-d-depot-ownership.v1"
INSTANCE_ID = "cn-cy-100c-01-V2-LOCATIONS"
SEEDS = tuple(range(1, 11))
ARMS = ("BASELINE_LOCKED", "TREATMENT_REALLOCATION")
BASELINES = ("baseline_random", "baseline_nearest")
SOURCE_FAMILY = "Uniform_Unbalanced"
MODEL_CONFIG = ModelConfig(
    strict_multitrip=True,
    depot_charger_capacity_mode="unbounded",
)
ITERATIONS_PER_VIEW = 25_000
EXACT_ELITES_PER_VIEW = 8
ARCHIVE_CANDIDATES_PER_VIEW = 24
SP_TIME_LIMIT_SECONDS = 5.0
WALLCLOCK_SAFETY_SECONDS_PER_VIEW = 7_200.0
MAX_WORKERS = 4
EPS = 1.0e-9
REQUIRED_ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
RAW_FIELDS = (
    "baseline_type",
    "instance_id",
    "seed",
    "arm",
    "status",
    "status_reason",
    "total_cost_cny",
    "total_distance_km",
    "system_emissions_kg",
    "physical_vehicle_count",
    "route_count",
    "cross_contractor_customer_count",
    "customer_count",
    "cross_contractor_customer_share",
    "paired_cost_improvement_cny",
    "paired_cost_improvement_pct",
    "paired_distance_improvement_km",
    "paired_distance_improvement_pct",
    "paired_emissions_improvement_kg",
    "paired_emissions_improvement_pct",
    "paired_physical_vehicle_improvement",
    "paired_physical_vehicle_improvement_pct",
    "paired_route_improvement",
    "paired_route_improvement_pct",
    "hgs_iterations_cv_only",
    "hgs_iterations_naive_ev",
    "hgs_iterations_mechanism_ev",
    "wallclock_safety_triggered",
    "complete_candidate_evaluations",
    "elapsed_seconds",
    "mapping_sha256",
    "initial_solution_sha256",
    "solution_path",
    "solution_sha256",
    "routing_sha256",
    "search_trace_path",
    "violation_count",
    "error_type",
    "error_message",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    return sha256_bytes(canonical_bytes(payload))


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO.resolve()))


def write_json_atomic(path: Path, payload: Any, *, replace_ok: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace_ok:
        raise FileExistsError(f"refusing to replace {path}")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(json_bytes(payload))
    temporary.replace(path)


def write_text_atomic(path: Path, text: str, *, replace_ok: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace_ok:
        raise FileExistsError(f"refusing to replace {path}")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RAW_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in RAW_FIELDS})
    temporary.replace(path)


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def load_bundle() -> Any:
    return load_china81_bundle(
        REPO,
        INSTANCE_ID,
        fleet_authority=FLEET_AUTHORITY,
        model_config=MODEL_CONFIG,
    )


def source_sequences() -> dict[tuple[str, str], tuple[int, ...]]:
    with SOURCE_SEQUENCE.open(encoding="utf-8", newline="") as handle:
        rows = {
            (row["source_family"], row["replicate"]): tuple(
                int(value) for value in row["p_sequence"].split()
            )
            for row in csv.DictReader(handle)
        }
    if len(rows) != 6 or any(len(values) != 200 for values in rows.values()):
        raise ValueError("source_p_sequences.csv is not the frozen six-row source")
    return rows


def source_replicate(instance_id: str) -> str:
    matches = [value for value in ("01", "02", "03") if f"c-{value}-" in instance_id]
    if len(matches) != 1:
        raise ValueError(f"cannot resolve source replicate for {instance_id}")
    return matches[0]


def build_random_mapping(bundle: Any) -> tuple[dict[str, str], dict[str, Any]]:
    """Apply the old four-label rule literally; never invent a 4-to-2 fold."""

    customers = sorted(bundle.customer_home_depot)
    labels = source_sequences()[(SOURCE_FAMILY, source_replicate(INSTANCE_ID))][
        : len(customers)
    ]
    label_to_depot, label_stats, depot_capacity = capacity_rank_alignment(
        bundle,
        customers,
        labels,
    )
    mapping = {
        customer: label_to_depot[label]
        for customer, label in zip(customers, labels, strict=True)
    }
    return mapping, {
        "source_family": SOURCE_FAMILY,
        "source_replicate": source_replicate(INSTANCE_ID),
        "distinct_source_labels": sorted(set(labels)),
        "label_to_depot": label_to_depot,
        "label_stats": label_stats,
        "depot_capacity": depot_capacity,
    }


def build_nearest_mapping(bundle: Any) -> tuple[dict[str, str], dict[str, Any]]:
    """Assign each customer to the nearest depot by directed road distance."""

    customers = sorted(bundle.customer_home_depot)
    depots = sorted(bundle.fleet_caps_by_depot)
    mapping = {
        customer: min(
            depots,
            key=lambda depot: (
                float(bundle.instance.distance(depot, customer)),
                depot,
            ),
        )
        for customer in customers
    }
    distances = {
        customer: float(bundle.instance.distance(mapping[customer], customer))
        for customer in customers
    }
    return mapping, {
        "distance_rule": "directed road distance depot_to_customer",
        "tie_break": "lexicographic depot_id",
        "capacity_rank_alignment_applied": False,
        "capacity_rank_alignment_reason": (
            "nearest assignment returns a concrete depot_id for every customer; "
            "there are no anonymous groups left to align, and re-ranking would "
            "change the requested nearest-depot rule"
        ),
        "nearest_distance_m_by_customer": distances,
    }


def bundle_with_mapping(bundle: Any, mapping: dict[str, str]) -> Any:
    return replace(
        bundle,
        customer_home_depot=MappingProxyType(dict(mapping)),
        formal_search_allowed=False,
    )


def common_initial(bundle: Any) -> Solution:
    witness_path = FLEET_AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json"
    witness = json.loads(witness_path.read_text(encoding="utf-8"))
    level = witness["levels"]["25"]
    routes: list[Route] = []
    for depot_id, depot_payload in sorted(level["depots"].items()):
        for registered_type in ("cv", "ev"):
            for index, row in enumerate(
                depot_payload[f"{registered_type}_routes"],
                start=1,
            ):
                routes.append(
                    Route(
                        vehicle_id=(
                            f"SCOUT-D-INITIAL-{depot_id}-"
                            f"{registered_type.upper()}-{index:03d}"
                        ),
                        vehicle_type=registered_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *[str(value) for value in row["customers"]],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def solution_dict(solution: Solution) -> dict[str, Any]:
    return asdict(solution)


def routing_sha256(solution: Solution) -> str:
    payload = [
        {
            "vehicle_id": route.vehicle_id,
            "vehicle_type": route.vehicle_type,
            "home_depot_id": route.home_depot_id,
            "node_sequence": route.node_sequence,
        }
        for route in solution.routes
    ]
    return canonical_sha256(payload)


def mapping_counts(mapping: dict[str, str]) -> dict[str, int]:
    return {
        depot: sum(owner == depot for owner in mapping.values())
        for depot in sorted(set(mapping.values()))
    }


def mapping_demands(bundle: Any, mapping: dict[str, str]) -> dict[str, float]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    return {
        depot: sum(
            float(nodes[customer].demand)
            for customer, owner in mapping.items()
            if owner == depot
        )
        for depot in sorted(set(mapping.values()))
    }


def source_paths(bundle: Any) -> list[Path]:
    paths = list((SOLVER_SRC / "setp_solver").rglob("*.py"))
    paths.extend(PROTOTYPE.glob("*.py"))
    paths.extend(
        [
            Path(__file__).resolve(),
            OUT / "test_scout_d.py",
            OUT / "monitor.json",
            SOURCE_SEQUENCE,
            CAPACITY_ALIGNMENT_SOURCE,
            FLEET_AUTHORITY / "fleet_caps.csv",
            FLEET_AUTHORITY / "manifest.json",
            FLEET_AUTHORITY / "zero_search_certification.csv",
            FLEET_AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json",
            FLEET_EVIDENCE / "decision.json",
            FLEET_EVIDENCE / "metadata.json",
        ]
    )
    for value in bundle.source_paths.values():
        path = Path(str(value))
        if not path.is_absolute():
            path = REPO / path
        if path.is_file():
            paths.append(path)
    return sorted({path.resolve() for path in paths if path.is_file()})


def source_hashes(bundle: Any) -> dict[str, str]:
    return {relative(path): sha256_path(path) for path in source_paths(bundle)}


def implementation_locations() -> dict[str, Any]:
    return {
        "random_grouping_wrapper": {
            "path": relative(Path(__file__)),
            "start_line": inspect.getsourcelines(build_random_mapping)[1],
            "end_line": inspect.getsourcelines(build_random_mapping)[1]
            + len(inspect.getsourcelines(build_random_mapping)[0])
            - 1,
        },
        "random_capacity_rank_alignment": {
            "path": relative(CAPACITY_ALIGNMENT_SOURCE),
            "start_line": inspect.getsourcelines(capacity_rank_alignment)[1],
            "end_line": inspect.getsourcelines(capacity_rank_alignment)[1]
            + len(inspect.getsourcelines(capacity_rank_alignment)[0])
            - 1,
            "requested_reference_lines": "31-65",
        },
        "nearest_grouping": {
            "path": relative(Path(__file__)),
            "start_line": inspect.getsourcelines(build_nearest_mapping)[1],
            "end_line": inspect.getsourcelines(build_nearest_mapping)[1]
            + len(inspect.getsourcelines(build_nearest_mapping)[0])
            - 1,
        },
    }


def verify_environment() -> None:
    mismatches = {
        key: {"expected": value, "actual": os.environ.get(key)}
        for key, value in REQUIRED_ENV.items()
        if os.environ.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"required deterministic environment mismatch: {mismatches}")


def verify_frozen_sources() -> None:
    metadata = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    with model_config_scope(MODEL_CONFIG):
        actual = source_hashes(load_bundle())
    if actual != metadata["source_sha256"]:
        expected_keys = set(metadata["source_sha256"])
        actual_keys = set(actual)
        changed = sorted(
            key
            for key in expected_keys & actual_keys
            if metadata["source_sha256"][key] != actual[key]
        )
        raise RuntimeError(
            "HALT_SOURCE_SHA256_DRIFT:"
            f"changed={changed},added={sorted(actual_keys-expected_keys)},"
            f"removed={sorted(expected_keys-actual_keys)}"
        )


def blank_row(baseline_type: str, seed: int, arm: str) -> dict[str, Any]:
    return {
        field: ""
        for field in RAW_FIELDS
    } | {
        "baseline_type": baseline_type,
        "instance_id": INSTANCE_ID,
        "seed": seed,
        "arm": arm,
        "customer_count": 100,
        "violation_count": 0,
    }


def random_halt_rows(reason: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        for arm in ARMS:
            row = blank_row("baseline_random", seed, arm)
            row.update(
                status="HALT_PRESEARCH_RANDOM_LABEL_DEPOT_CARDINALITY_MISMATCH",
                status_reason=reason,
                error_type="ValueError",
                error_message=reason,
            )
            rows.append(row)
    return rows


def preflight() -> dict[str, Any]:
    with model_config_scope(MODEL_CONFIG):
        base = load_bundle()
        customer_count = len(base.customer_home_depot)
        if customer_count != 100:
            raise RuntimeError(f"expected 100 customers, got {customer_count}")
        if abs(float(base.prices.vehicle_fixed_cost) - 170.0) > EPS:
            raise RuntimeError("active c_fix is not 170")
        if MODEL_CONFIG.depot_charger_capacity_mode != "unbounded":
            raise RuntimeError("depot charging is not unbounded")
        if not MODEL_CONFIG.strict_multitrip:
            raise RuntimeError("strict multitrip is not enabled")

        random_error: dict[str, str] | None = None
        random_detail: dict[str, Any]
        labels = source_sequences()[(SOURCE_FAMILY, source_replicate(INSTANCE_ID))][
            :customer_count
        ]
        try:
            _, random_detail = build_random_mapping(base)
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            random_error = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            random_detail = {
                "source_family": SOURCE_FAMILY,
                "source_replicate": source_replicate(INSTANCE_ID),
                "distinct_source_labels": sorted(set(labels)),
                "source_label_count": len(set(labels)),
                "depot_ids": sorted(base.fleet_caps_by_depot),
                "depot_count": len(base.fleet_caps_by_depot),
                "unapproved_transformations_not_applied": [
                    "modulo folding",
                    "label dropping",
                    "label merging",
                    "new random draw",
                ],
            }
        if random_error is None:
            raise RuntimeError(
                "random preflight unexpectedly succeeded; review the frozen rule"
            )

        nearest_mapping, nearest_detail = build_nearest_mapping(base)
        nearest_bundle = bundle_with_mapping(base, nearest_mapping)
        initial = common_initial(nearest_bundle)
        physicalized, certificate = _physicalize_multitrip_solution(
            initial,
            nearest_bundle,
        )
        objective, breakdown, violations = exact_china81_score(
            physicalized,
            nearest_bundle,
        )
        if violations:
            raise RuntimeError(
                f"nearest preflight initial has {len(violations)} violations"
            )
        original_mapping = dict(base.customer_home_depot)
        differing = sorted(
            customer
            for customer in nearest_mapping
            if nearest_mapping[customer] != original_mapping[customer]
        )
        if differing:
            raise RuntimeError(
                "authority witness cannot be a common locked initial because "
                f"nearest differs for {len(differing)} customers"
            )

    initial_payload = {
        "schema": "resetp.scout-d-preflight-solution.v1",
        "instance_id": INSTANCE_ID,
        "objective_cny": objective,
        "breakdown": breakdown,
        "multitrip_certificate": certificate.as_dict(),
        "solution": solution_dict(physicalized),
    }
    initial_sha = canonical_sha256(initial_payload["solution"])
    return {
        "schema": "resetp.scout-d-preflight.v1",
        "created_at_utc": utc_now(),
        "random": {
            "status": "HALT_PRESEARCH_RANDOM_LABEL_DEPOT_CARDINALITY_MISMATCH",
            "error": random_error,
            "detail": random_detail,
        },
        "nearest": {
            "status": "PASS_PREFLIGHT_READY_FOR_SEARCH",
            "detail": nearest_detail,
            "mapping": nearest_mapping,
            "mapping_sha256": canonical_sha256(nearest_mapping),
            "owner_counts": mapping_counts(nearest_mapping),
            "assigned_demand_kg": mapping_demands(base, nearest_mapping),
            "equals_original_customer_home_depot": True,
            "initial_solution_sha256": initial_sha,
            "initial_payload": initial_payload,
        },
    }


def prepare() -> None:
    verify_environment()
    metadata_path = OUT / "metadata.json"
    if metadata_path.exists():
        raise FileExistsError("metadata.json already exists; prepare is immutable")
    probe = preflight()
    with model_config_scope(MODEL_CONFIG):
        bundle = load_bundle()
        hashes = source_hashes(bundle)
        sources = {key: str(value) for key, value in bundle.source_paths.items()}
        fleet_caps = {
            depot: dict(values)
            for depot, values in bundle.fleet_caps_by_depot.items()
        }
    metadata = {
        "schema": SCHEMA,
        "task_id": "SCOUT-D",
        "formal_result": False,
        "paper_eligible": False,
        "status": "PREREGISTERED_BEFORE_SEARCH_WITH_RANDOM_TECHNICAL_HALT",
        "created_at_utc": utc_now(),
        "git_commit": git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(git("status", "--porcelain=v1")),
        "instance_id": INSTANCE_ID,
        "seeds": list(SEEDS),
        "budget": {
            "rule": "V7_FIXED_25000_ITERATIONS_PER_VIEW",
            "iterations_per_view": ITERATIONS_PER_VIEW,
            "views": ["cv_only", "naive_ev", "mechanism_ev"],
            "max_no_improvement_iterations_per_view": None,
            "explicitly_not_used": [2000, 150],
            "archive_candidates_per_view": ARCHIVE_CANDIDATES_PER_VIEW,
            "exact_elites_per_view": EXACT_ELITES_PER_VIEW,
            "sp_time_limit_seconds": SP_TIME_LIMIT_SECONDS,
            "wallclock_safety_seconds_per_view": WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
        },
        "contract": {
            "strict_multitrip": True,
            "vehicle_fixed_cost_cny": 170.0,
            "fixed_cost_counting_basis": "distinct physical_vehicle_id",
            "depot_charger_capacity_mode": "unbounded",
            "fleet_authority_version": "china81_finite_fleet_authority_v3_20260802",
            "fleet_authority_path": relative(FLEET_AUTHORITY),
            "fleet_evidence_path": relative(FLEET_EVIDENCE),
            "treatment": "hard_home_depot_lock=false",
            "baseline": "hard_home_depot_lock=true",
            "only_arm_difference": "hard_home_depot_lock",
        },
        "baselines": {
            "baseline_random": {
                "rule": (
                    "Uniform_Unbalanced public source p labels, then unchanged "
                    "demand/capacity rank alignment"
                ),
                "preflight_status": probe["random"]["status"],
                "preflight_error": probe["random"]["error"],
                "no_unapproved_4_to_2_transformation": True,
            },
            "baseline_nearest": {
                "rule": (
                    "minimum directed road distance from depot to customer; "
                    "lexicographic depot_id tie break"
                ),
                "capacity_rank_alignment_applied": False,
                "reason_alignment_not_needed": probe["nearest"]["detail"][
                    "capacity_rank_alignment_reason"
                ],
                "mapping_sha256": probe["nearest"]["mapping_sha256"],
                "equals_original_mapping": True,
            },
        },
        "implementation_locations": implementation_locations(),
        "fleet_caps_by_depot": fleet_caps,
        "bundle_source_paths": sources,
        "source_sha256": hashes,
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "python": sys.version,
            "python_executable": sys.executable,
            "max_workers": MAX_WORKERS,
            "thread_environment": {
                key: os.environ.get(key) for key in REQUIRED_ENV
            },
        },
        "artifact_hash_exclusions": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "__pycache__",
            ".experiment.monitor",
            "*.tmp-*",
        ],
        "prohibited_files_unchanged_by_runner": [
            "docs/paper_v2/paper_main.tex",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
        ],
    }
    write_json_atomic(metadata_path, metadata, replace_ok=False)
    write_json_atomic(OUT / "preflight.json", probe, replace_ok=False)
    write_json_atomic(
        OUT / "preflight_common_initial_solution.json",
        probe["nearest"]["initial_payload"],
        replace_ok=False,
    )
    for baseline in BASELINES:
        baseline_metadata = {
            **metadata,
            "baseline_scope": baseline,
            "baseline_contract": metadata["baselines"][baseline],
        }
        write_json_atomic(
            OUT / baseline / "metadata.json",
            baseline_metadata,
            replace_ok=False,
        )
    reason = (
        f"{probe['random']['error']['type']}: "
        f"{probe['random']['error']['message']}; frozen source has "
        f"{probe['random']['detail']['source_label_count']} labels but instance has "
        f"{probe['random']['detail']['depot_count']} depots; no approved 4-to-2 rule"
    )
    random_rows = random_halt_rows(reason)
    write_csv_atomic(OUT / "baseline_random/raw_runs.csv", random_rows)
    write_csv_atomic(OUT / "baseline_nearest/raw_runs.csv", [])
    write_csv_atomic(OUT / "raw_runs.csv", random_rows)
    write_json_atomic(
        OUT / "status.json",
        {
            "status": "PREPARED_RANDOM_HALTED_NEAREST_READY",
            "completed_units": 0,
            "expected_nearest_units": len(SEEDS) * len(ARMS),
            "updated_at_utc": utc_now(),
        },
    )
    print("SCOUT-D prepared: random HALT retained; nearest ready", flush=True)


def result_path(seed: int, arm: str) -> Path:
    return OUT / "baseline_nearest/units" / f"seed-{seed:02d}__{arm}" / "result.json"


def task_specs() -> list[dict[str, Any]]:
    return [
        {"seed": seed, "arm": arm}
        for seed in SEEDS
        for arm in ARMS
    ]


def completed_result(spec: dict[str, Any]) -> dict[str, Any] | None:
    path = result_path(int(spec["seed"]), str(spec["arm"]))
    if not path.is_file():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    solution_path_value = result.get("solution_path")
    solution_sha = result.get("solution_sha256")
    if result.get("status") == "PASS" and solution_path_value and solution_sha:
        solution_path = REPO / str(solution_path_value)
        if not solution_path.is_file() or sha256_path(solution_path) != solution_sha:
            raise RuntimeError(f"resume solution drift: {solution_path}")
    return result


def run_unit(spec: dict[str, Any]) -> dict[str, Any]:
    verify_environment()
    verify_frozen_sources()
    existing = completed_result(spec)
    if existing is not None:
        return existing
    seed = int(spec["seed"])
    arm = str(spec["arm"])
    unit_dir = result_path(seed, arm).parent
    unit_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        with model_config_scope(MODEL_CONFIG):
            base = load_bundle()
            mapping, _ = build_nearest_mapping(base)
            bundle = bundle_with_mapping(base, mapping)
            initial = common_initial(bundle)
            initial_sha = canonical_sha256(solution_dict(initial))
            run = run_hgs_route_pool_recombination(
                bundle,
                initial,
                seed=seed,
                hgs_seconds_per_view=None,
                exact_elites_per_view=EXACT_ELITES_PER_VIEW,
                max_archive_candidates_per_view=ARCHIVE_CANDIDATES_PER_VIEW,
                sp_time_limit_seconds=SP_TIME_LIMIT_SECONDS,
                hard_home_depot_lock=arm == "BASELINE_LOCKED",
                max_hgs_iterations_per_view=ITERATIONS_PER_VIEW,
                max_no_improvement_iterations_per_view=None,
                wallclock_safety_seconds_per_view=(
                    WALLCLOCK_SAFETY_SECONDS_PER_VIEW
                ),
                exact_checkpoint_interval_iterations=None,
            )
            physicalized, certificate = _physicalize_multitrip_solution(
                run.solution,
                bundle,
            )
            objective, breakdown, violations = exact_china81_score(
                physicalized,
                bundle,
            )
        view_iterations = {
            mode: int(epoch.stats["hgs_iterations"])
            for mode, epoch in run.view_epochs.items()
        }
        safety = bool(run.stats["wallclock_safety_triggered"])
        budget_ok = all(
            value == ITERATIONS_PER_VIEW for value in view_iterations.values()
        )
        if safety:
            raise RuntimeError("HALT_WALLCLOCK_SAFETY")
        if not budget_ok:
            raise RuntimeError(
                f"HALT_ITERATION_BUDGET_NOT_CONSUMED:{view_iterations}"
            )
        if violations:
            raise RuntimeError(
                f"HALT_INFEASIBLE_COMPLETE_SOLUTION:{len(violations)}"
            )
        cross_customers = {
            item.customer_id for item in physicalized.cross_site_services
        }
        if arm == "BASELINE_LOCKED" and cross_customers:
            raise RuntimeError("locked baseline contains reassigned customers")
        used = {
            physical_vehicle_id(route.vehicle_id)
            for route in physicalized.routes
        }
        solution_payload = {
            "schema": "resetp.scout-d-full-solution.v1",
            "baseline_type": "baseline_nearest",
            "instance_id": INSTANCE_ID,
            "seed": seed,
            "arm": arm,
            "formal_result": False,
            "model_config": MODEL_CONFIG.as_metadata(),
            "objective_cny": objective,
            "breakdown": breakdown,
            "violations": [
                asdict(item) if is_dataclass(item) else str(item)
                for item in violations
            ],
            "multitrip_certificate": certificate.as_dict(),
            "solution": solution_dict(physicalized),
        }
        solution_path = unit_dir / "solution.json"
        write_json_atomic(solution_path, solution_payload, replace_ok=False)
        solution_sha = sha256_path(solution_path)
        trace_path = unit_dir / "search_trace.json"
        write_json_atomic(trace_path, run.stats, replace_ok=False)
        row = blank_row("baseline_nearest", seed, arm)
        row.update(
            status="PASS",
            status_reason="",
            total_cost_cny=float(objective),
            total_distance_km=float(breakdown["distance_total"]) / 1000.0,
            system_emissions_kg=float(breakdown["E_total"]),
            physical_vehicle_count=len(used),
            route_count=len(physicalized.routes),
            cross_contractor_customer_count=len(cross_customers),
            cross_contractor_customer_share=len(cross_customers) / 100.0,
            hgs_iterations_cv_only=view_iterations["cv_only"],
            hgs_iterations_naive_ev=view_iterations["naive_ev"],
            hgs_iterations_mechanism_ev=view_iterations["mechanism_ev"],
            wallclock_safety_triggered=False,
            complete_candidate_evaluations=int(
                run.stats["complete_candidate_evaluation_attempts"]
            ),
            elapsed_seconds=time.perf_counter() - started,
            mapping_sha256=canonical_sha256(mapping),
            initial_solution_sha256=initial_sha,
            solution_path=relative(solution_path),
            solution_sha256=solution_sha,
            routing_sha256=routing_sha256(physicalized),
            search_trace_path=relative(trace_path),
            violation_count=0,
            error_type="",
            error_message="",
        )
    except BaseException as exc:
        error_path = unit_dir / "error.json"
        error = {
            "schema": "resetp.scout-d-error.v1",
            "spec": spec,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "created_at_utc": utc_now(),
        }
        write_json_atomic(error_path, error, replace_ok=False)
        row = blank_row("baseline_nearest", seed, arm)
        row.update(
            status="HALT_TECHNICAL",
            status_reason=str(exc),
            elapsed_seconds=time.perf_counter() - started,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    write_json_atomic(result_path(seed, arm), row, replace_ok=False)
    return row


def load_nearest_results() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in task_specs():
        result = completed_result(spec)
        if result is not None:
            rows.append(result)
    return sorted(rows, key=lambda row: (int(row["seed"]), str(row["arm"])))


def add_pair_differences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_seed: dict[int, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_seed.setdefault(int(row["seed"]), {})[str(row["arm"])] = row
    metric_pairs = (
        ("total_cost_cny", "paired_cost_improvement_cny", "paired_cost_improvement_pct"),
        ("total_distance_km", "paired_distance_improvement_km", "paired_distance_improvement_pct"),
        ("system_emissions_kg", "paired_emissions_improvement_kg", "paired_emissions_improvement_pct"),
        ("physical_vehicle_count", "paired_physical_vehicle_improvement", "paired_physical_vehicle_improvement_pct"),
        ("route_count", "paired_route_improvement", "paired_route_improvement_pct"),
    )
    for arms in by_seed.values():
        if set(arms) != set(ARMS) or any(arms[arm]["status"] != "PASS" for arm in ARMS):
            continue
        baseline = arms["BASELINE_LOCKED"]
        treatment = arms["TREATMENT_REALLOCATION"]
        for metric, diff_field, pct_field in metric_pairs:
            baseline_value = float(baseline[metric])
            treatment_value = float(treatment[metric])
            difference = baseline_value - treatment_value
            percentage = (
                "" if abs(baseline_value) <= EPS else 100.0 * difference / baseline_value
            )
            for row in arms.values():
                row[diff_field] = difference
                row[pct_field] = percentage
    return rows


def run_nearest(workers: int) -> None:
    verify_environment()
    verify_frozen_sources()
    specs = [spec for spec in task_specs() if completed_result(spec) is None]
    write_json_atomic(
        OUT / "status.json",
        {
            "status": "RUNNING_NEAREST",
            "completed_units": len(task_specs()) - len(specs),
            "expected_nearest_units": len(task_specs()),
            "updated_at_utc": utc_now(),
        },
    )
    if specs:
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            futures = {pool.submit(run_unit, spec): spec for spec in specs}
            for future in as_completed(futures):
                spec = futures[future]
                row = future.result()
                nearest = add_pair_differences(load_nearest_results())
                random_rows = load_csv_rows(OUT / "baseline_random/raw_runs.csv")
                write_csv_atomic(OUT / "baseline_nearest/raw_runs.csv", nearest)
                write_csv_atomic(OUT / "raw_runs.csv", [*random_rows, *nearest])
                write_json_atomic(
                    OUT / "status.json",
                    {
                        "status": "RUNNING_NEAREST",
                        "last_completed": spec,
                        "last_terminal_status": row["status"],
                        "completed_units": len(nearest),
                        "expected_nearest_units": len(task_specs()),
                        "updated_at_utc": utc_now(),
                    },
                )
                print(
                    f"completed seed={spec['seed']} arm={spec['arm']} "
                    f"status={row['status']} ({len(nearest)}/{len(task_specs())})",
                    flush=True,
                )
    nearest = add_pair_differences(load_nearest_results())
    random_rows = load_csv_rows(OUT / "baseline_random/raw_runs.csv")
    write_csv_atomic(OUT / "baseline_nearest/raw_runs.csv", nearest)
    write_csv_atomic(OUT / "raw_runs.csv", [*random_rows, *nearest])
    print("nearest execution terminal", flush=True)


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def numeric_mean(rows: list[dict[str, Any]], field: str) -> float:
    return statistics.mean(float(row[field]) for row in rows)


def paired_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [row for row in rows if row["status"] == "PASS"]
    baseline = [row for row in passed if row["arm"] == "BASELINE_LOCKED"]
    treatment = [row for row in passed if row["arm"] == "TREATMENT_REALLOCATION"]
    paired_seeds = sorted(set(int(row["seed"]) for row in baseline) & set(int(row["seed"]) for row in treatment))
    paired_baseline = [row for row in baseline if int(row["seed"]) in paired_seeds]
    paired_treatment = [row for row in treatment if int(row["seed"]) in paired_seeds]
    if len(paired_seeds) != len(SEEDS):
        return {
            "status": "HALT_NEAREST_INCOMPLETE",
            "paired_seed_count": len(paired_seeds),
            "paired_seeds": paired_seeds,
        }
    metrics = {
        "total_cost_cny": "cost",
        "total_distance_km": "distance",
        "system_emissions_kg": "emissions",
        "physical_vehicle_count": "physical_vehicles",
        "route_count": "routes",
    }
    summary: dict[str, Any] = {}
    for field, label in metrics.items():
        base_mean = numeric_mean(paired_baseline, field)
        treat_mean = numeric_mean(paired_treatment, field)
        improvement = base_mean - treat_mean
        pair_pcts = [
            100.0 * (float(b[field]) - float(t[field])) / float(b[field])
            for b, t in zip(
                sorted(paired_baseline, key=lambda row: int(row["seed"])),
                sorted(paired_treatment, key=lambda row: int(row["seed"])),
                strict=True,
            )
            if abs(float(b[field])) > EPS
        ]
        summary[label] = {
            "baseline_mean": base_mean,
            "treatment_mean": treat_mean,
            "paired_mean_improvement": improvement,
            "relative_improvement_pct_of_baseline_mean": (
                100.0 * improvement / base_mean if abs(base_mean) > EPS else None
            ),
            "mean_of_seedwise_relative_improvement_pct": (
                statistics.mean(pair_pcts) if pair_pcts else None
            ),
        }
    summary["reassignment"] = {
        "baseline_mean_customer_count": numeric_mean(
            paired_baseline, "cross_contractor_customer_count"
        ),
        "treatment_mean_customer_count": numeric_mean(
            paired_treatment, "cross_contractor_customer_count"
        ),
        "treatment_mean_share": numeric_mean(
            paired_treatment, "cross_contractor_customer_share"
        ),
        "treatment_mean_share_pct": 100.0
        * numeric_mean(paired_treatment, "cross_contractor_customer_share"),
        "customer_denominator": 100,
    }
    return {
        "status": "SCOUT_DEPOT_NEAREST_COMPLETE",
        "paired_seed_count": len(paired_seeds),
        "paired_seeds": paired_seeds,
        "metrics": summary,
    }


def random_report(reason: str) -> str:
    return f"""# SCOUT-D：随机归属基准

**结论：HALT_PRESEARCH_RANDOM_LABEL_DEPOT_CARDINALITY_MISMATCH。**

FACT：旧正式规则读取 `source_p_sequences.csv` 的 `Uniform_Unbalanced`、replicate 01；本算例前 100 个标签包含 0、1、2、3 四组。目标算例 `{INSTANCE_ID}` 只有 `D_chengdu`、`D_chongqing` 两个车场。旧 `capacity_rank_alignment` 使用 `zip(..., strict=True)` 将需求排序组与容量排序车场一一配对，直接执行得到：`{reason}`。

DECISION：未采用取模、丢组、合组或重新抽签，因为这些都是任务未批准的新分组规则。本基准及其处理臂 10 个种子均未启动搜索；20 条计划行原样保留在 `raw_runs.csv`。

HALT：因此本基准无法给出“处理后比未处理好多少”。这不是不利数值，而是输入规则与算例车场数不相容的技术停止。
"""


def nearest_report(summary: dict[str, Any]) -> str:
    if summary["status"] != "SCOUT_DEPOT_NEAREST_COMPLETE":
        return f"""# SCOUT-D：就近归属基准

**结论：{summary['status']}。**

完整配对种子数为 {summary['paired_seed_count']}/10。缺失或技术失败证据保留在 `raw_runs.csv` 与各 unit 的 `error.json`，未删行、未补跑不同种子。
"""
    metric = summary["metrics"]
    lines = [
        "# SCOUT-D：就近归属基准",
        "",
        "**结论：SCOUT_DEPOT_NEAREST_COMPLETE；以下均为探路结果，formal_result=false，不进正文。**",
        "",
        "就近规则采用车场到客户的有向路网距离；同距按 depot_id 排序。本算例的就近映射与原始 customer_home_depot 逐客户相同，因此无需容量排序对齐：规则已经直接给出具体车场，再对齐会改写‘就近’定义。两臂使用相同 authority-v3 初始解、相同种子和相同 25,000 次/视角预算，唯一差异是 hard_home_depot_lock。",
        "",
        "| 指标（10 种子均值） | 基准臂 | 处理臂 | 改善（基准-处理） | 改善/% |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = (
        ("cost", "总成本/元", 3),
        ("distance", "里程/km", 3),
        ("emissions", "系统排放/kg", 3),
        ("physical_vehicles", "实体车数", 3),
        ("routes", "路线数", 3),
    )
    for key, label, digits in labels:
        item = metric[key]
        lines.append(
            f"| {label} | {item['baseline_mean']:.{digits}f} | "
            f"{item['treatment_mean']:.{digits}f} | "
            f"{item['paired_mean_improvement']:.{digits}f} | "
            f"{item['relative_improvement_pct_of_baseline_mean']:.3f}% |"
        )
    reassignment = metric["reassignment"]
    lines.extend(
        [
            "",
            f"处理臂平均跨承包商改派 {reassignment['treatment_mean_customer_count']:.3f}/100 个客户，即 {reassignment['treatment_mean_share_pct']:.3f}%；基准臂为 0。旧 121.58/175=69.5% 只作历史比对，不混入本轮分母。",
            "",
            "每种子完整解、search trace、solution_sha256、配对差和逐种子百分比均在本目录保留。未做敏感性、调参、换种子或换算例。",
        ]
    )
    return "\n".join(lines) + "\n"


def artifact_manifest(root: Path) -> dict[str, Any]:
    artifacts: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_to_root = path.relative_to(root)
        if any(part == "__pycache__" for part in relative_to_root.parts):
            continue
        if any(part == ".experiment.monitor" for part in relative_to_root.parts):
            continue
        if path.name.startswith("._") or path.name == "artifact_hashes.json":
            continue
        if path.name == "done.json" or ".tmp-" in path.name:
            continue
        artifacts[str(relative_to_root)] = sha256_path(path)
    return {
        "schema": "resetp.scout-d-artifact-hashes.v1",
        "created_at_utc": utc_now(),
        "root": relative(root),
        "exclusions": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "**/__pycache__/**",
            ".experiment.monitor",
            "*.tmp-*",
        ],
        "artifacts": artifacts,
    }


def finalize() -> None:
    verify_environment()
    verify_frozen_sources()
    nearest_rows = add_pair_differences(load_nearest_results())
    if len(nearest_rows) != len(task_specs()):
        raise RuntimeError(
            f"cannot finalize: nearest has {len(nearest_rows)}/{len(task_specs())} rows"
        )
    write_csv_atomic(OUT / "baseline_nearest/raw_runs.csv", nearest_rows)
    random_rows = load_csv_rows(OUT / "baseline_random/raw_runs.csv")
    write_csv_atomic(OUT / "raw_runs.csv", [*random_rows, *nearest_rows])
    nearest_summary = paired_summary(nearest_rows)
    preflight_payload = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    random_reason = (
        f"{preflight_payload['random']['error']['type']}: "
        f"{preflight_payload['random']['error']['message']}"
    )
    random_decision = {
        "schema": SCHEMA,
        "task_id": "SCOUT-D/baseline_random",
        "formal_result": False,
        "status": "HALT_PRESEARCH_RANDOM_LABEL_DEPOT_CARDINALITY_MISMATCH",
        "reason": random_reason,
        "planned_seed_count": 10,
        "executed_search_units": 0,
        "retained_planned_rows": len(random_rows),
        "effect_estimate": None,
        "unapproved_transformations_not_applied": preflight_payload["random"][
            "detail"
        ]["unapproved_transformations_not_applied"],
    }
    nearest_decision = {
        "schema": SCHEMA,
        "task_id": "SCOUT-D/baseline_nearest",
        "formal_result": False,
        **nearest_summary,
        "old_random_reassignment_reference": {
            "numerator": 121.58,
            "denominator": 175,
            "share_pct": 69.5,
            "use": "comparison_only",
        },
    }
    root_status = (
        "SCOUT_DEPOT_PARTIAL_RANDOM_HALT_NEAREST_COMPLETE"
        if nearest_summary["status"] == "SCOUT_DEPOT_NEAREST_COMPLETE"
        else "SCOUT_DEPOT_HALT_RANDOM_AND_NEAREST_INCOMPLETE"
    )
    root_decision = {
        "schema": SCHEMA,
        "task_id": "SCOUT-D",
        "formal_result": False,
        "paper_eligible": False,
        "status": root_status,
        "baseline_random": random_decision,
        "baseline_nearest": nearest_decision,
        "improvement_magnitude_difference_between_baselines": None,
        "difference_status": (
            "NOT_ESTIMABLE_RANDOM_BASELINE_TECHNICAL_HALT"
        ),
        "stop_rule_application": (
            "random baseline halted with evidence; nearest baseline continued"
        ),
        "completed_at_utc": utc_now(),
    }
    write_json_atomic(OUT / "baseline_random/decision.json", random_decision)
    write_json_atomic(OUT / "baseline_nearest/decision.json", nearest_decision)
    write_json_atomic(OUT / "decision.json", root_decision)
    write_text_atomic(
        OUT / "baseline_random/report.md",
        random_report(random_reason),
    )
    write_text_atomic(
        OUT / "baseline_nearest/report.md",
        nearest_report(nearest_summary),
    )
    if nearest_summary["status"] == "SCOUT_DEPOT_NEAREST_COMPLETE":
        nearest_metrics = nearest_summary["metrics"]
        cost = nearest_metrics["cost"]
        distance = nearest_metrics["distance"]
        emissions = nearest_metrics["emissions"]
        vehicles = nearest_metrics["physical_vehicles"]
        routes = nearest_metrics["routes"]
        reassignment = nearest_metrics["reassignment"]
        nearest_direct_answer = f"""就近分组基准（10 种子均值）：处理臂相对基准臂总成本改善 {cost['paired_mean_improvement']:.3f} 元（{cost['relative_improvement_pct_of_baseline_mean']:.3f}%），从 {cost['baseline_mean']:.3f} 元降至 {cost['treatment_mean']:.3f} 元；里程改善 {distance['paired_mean_improvement']:.3f} km（{distance['relative_improvement_pct_of_baseline_mean']:.3f}%）；系统排放改善 {emissions['paired_mean_improvement']:.3f} kg（{emissions['relative_improvement_pct_of_baseline_mean']:.3f}%）；实体车数改善 {vehicles['paired_mean_improvement']:.3f}（{vehicles['relative_improvement_pct_of_baseline_mean']:.3f}%）；路线数改善 {routes['paired_mean_improvement']:.3f}（{routes['relative_improvement_pct_of_baseline_mean']:.3f}%）。处理臂平均改派 {reassignment['treatment_mean_customer_count']:.3f}/100 个客户（{reassignment['treatment_mean_share_pct']:.3f}%），基准臂为 0。"""
    else:
        nearest_direct_answer = (
            f"就近分组基准：{nearest_summary['status']}，完整配对 "
            f"{nearest_summary['paired_seed_count']}/10，不能形成完整效应。"
        )
    root_report = f"""# SCOUT-D：多车场客户归属重分效应探路

**终态：{root_status}。本轮是探路，formal_result=false，不进正文。**

## 直接回答

随机分组基准：搜索前技术 HALT，不能估计处理改善。冻结的公共序列含四个标签组，目标算例只有两个车场，旧容量排序函数要求严格一一对应；仓库没有批准的 4→2 映射。本轮未用取模、合组、删组或新抽签替代。

{nearest_direct_answer}

两种基准改善幅度之差：**不可估计**，因为随机基准没有合法执行值；不得把技术 HALT 填成 0，也不得借此选择更有利的基准。

## 证据边界

FACT：就近映射与该算例原始归属逐客户相同；authority v3 初始解可被两臂共同使用。随机标签基准的失败发生在搜索前，完整错误、四件套、20 条计划行均保留。

DECISION：按用户停止条件让就近基准继续；不修改 paper_main.tex、check.py、search/evaluation.py，不做敏感性，不换种子/算例，不覆盖旧 E3 目录。

HALT：只有随机基准的 4 标签→2 车场转换得到用户批准后，才可能补齐两基准改善幅度差；本包不代替用户做该规则决定。
"""
    write_text_atomic(OUT / "report.md", root_report)
    write_json_atomic(
        OUT / "status.json",
        {
            "status": root_status,
            "completed_units": len(nearest_rows),
            "expected_nearest_units": len(task_specs()),
            "completion_marker": relative(OUT / "done.json"),
            "updated_at_utc": utc_now(),
        },
    )
    write_json_atomic(
        OUT / "baseline_random/artifact_hashes.json",
        artifact_manifest(OUT / "baseline_random"),
    )
    write_json_atomic(
        OUT / "baseline_nearest/artifact_hashes.json",
        artifact_manifest(OUT / "baseline_nearest"),
    )
    write_json_atomic(OUT / "artifact_hashes.json", artifact_manifest(OUT))
    verify_frozen_sources()
    done = {
        "schema": "resetp.scout-d-completion.v1",
        "task_id": "SCOUT-D",
        "status": root_status,
        "terminal": True,
        "nearest_complete": (
            nearest_summary["status"] == "SCOUT_DEPOT_NEAREST_COMPLETE"
        ),
        "random_technical_halt": True,
        "completed_at_utc": utc_now(),
        "decision_sha256": sha256_path(OUT / "decision.json"),
        "artifact_hashes_sha256": sha256_path(OUT / "artifact_hashes.json"),
    }
    write_json_atomic(OUT / "done.json", done, replace_ok=False)
    print(root_status, flush=True)


def command_all(workers: int) -> None:
    if not (OUT / "metadata.json").exists():
        prepare()
    run_nearest(workers)
    finalize()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    subparsers.add_parser("finalize")
    all_parser = subparsers.add_parser("all")
    all_parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "run":
        if not (OUT / "metadata.json").exists():
            raise RuntimeError("run requires immutable prepare first")
        run_nearest(int(args.workers))
        finalize()
    elif args.command == "finalize":
        finalize()
    elif args.command == "all":
        command_all(int(args.workers))
    else:
        raise AssertionError(args.command)


if __name__ == "__main__":
    main()
