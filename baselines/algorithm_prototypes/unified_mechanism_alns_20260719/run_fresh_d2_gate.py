#!/usr/bin/env python3
"""Run the frozen one-seed D2 gate and emit an immutable evidence package.

This runner is deliberately stricter than a normal development script.  It
locks the actual bundle bytes, all reachable project/source trees, both
third-party engines, the run order, parameters, environment, and protected
model files before the first algorithm score is generated.  Any arm failure
closes the package as invalid rather than leaving a restartable half-run.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import traceback
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
REFERENCE_ALNS = REPO / "Reference Algorithm/ALNS-7.0.0@N-Wouda"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dual_basin_solver import (  # noqa: E402
    SELECTOR_RAW,
    DualBasinConfig,
    build_v7_warm,
    run_dual_basin_mechanism_alns,
)
from build_fresh_d2_bundles import structural_checks  # noqa: E402
from initial_pool import solution_payload, solution_signature_hash  # noqa: E402
from official_hgs_resetp_adapter import (  # noqa: E402
    INSTALL_MANIFEST,
    OFFICIAL_COMMIT,
    OFFICIAL_LIBRARY,
    OFFICIAL_LIBRARY_SHA256,
    REBUILD_SCRIPT,
    TRACKED_LICENSE,
    verify_official_install,
)
from prototype import independent_cost, run_pure_alns  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from terminal_completion import apply_terminal_completion  # noqa: E402
from v2_solver import (  # noqa: E402
    run_official_hgs_neutral,
    run_original_n_wouda_alns_neutral,
)
from v7_responsibility_solver import run_mechanism_alns_v7  # noqa: E402


BUNDLES = HERE / "fresh_d2_bundles"
OUT = HERE / "fresh_d2_gate"
CONTRACT = REPO / (
    "docs/handoff/dual_basin_mechanism_alns_fresh_gate_contract_20260719.md"
)
LICENSE_REGISTER = REPO / (
    "docs/handoff/algorithm_source_and_license_register_20260719.md"
)
SEED = 1
BUDGET = 100
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
STRICT_TOL = 1.0e-9
MIN_MEDIAN_IMPROVEMENT_PERCENT = 0.5
MAX_MID_ABLATION_REGRESSION_PERCENT = 0.25
MAX_WALL_RATIO = 1.25

CANDIDATE = "mechanism_judged_dual_basin_alns"
V7 = "mechanism_alns_v7"
PROJECT_ALNS = "current_project_pure_alns"
OFFICIAL_HGS = "official_hgs_route_source_plus_common_completion"
ORIGINAL_ALNS = "original_n_wouda_alns_plus_common_completion"
RAW_SELECTOR = "raw_cost_dual_basin_ablation"
NO_MID = "mechanism_judged_dual_basin_no_mid_ablation"
ARMS = (
    CANDIDATE,
    V7,
    PROJECT_ALNS,
    OFFICIAL_HGS,
    ORIGINAL_ALNS,
    RAW_SELECTOR,
    NO_MID,
)
STRONG_CONTROLS = (V7, PROJECT_ALNS, OFFICIAL_HGS, ORIGINAL_ALNS)

RUNNER_AND_CONTRACT_FILES = (
    Path(__file__).resolve(),
    CONTRACT,
    LICENSE_REGISTER,
)
PROTECTED_FILES = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)
REQUIRED_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "fresh_d2_gate",
}
REFERENCE_SUFFIXES = {".py", ".md", ".toml", ".cff"}

RAW_FIELDS = (
    "instance_id",
    "dataset_role",
    "source_scale",
    "actual_customer_count",
    "actual_depot_count",
    "seed",
    "budget",
    "arm",
    "reported_algorithm",
    "reported_cost",
    "recomputed_cost",
    "cost_match",
    "evaluations",
    "budget_exact",
    "complete_resetp_candidate_budget_equalized",
    "total_compute_equalized",
    "elapsed_seconds",
    "timing_scope",
    "route_count",
    "ev_route_count",
    "charging_action_count",
    "feasible",
    "violation_count",
    "selected_basin",
    "solution_signature",
    "total_emissions_kg",
    "charging_emissions_kg",
    "hgs_native_calls_reported",
    "hgs_native_cpu_seconds_reported",
    "hgs_native_wall_seconds_reported",
    "route_proxy_evaluations_reported",
    "route_local_exact_evaluations_reported",
    "route_local_schedule_evaluations_reported",
    "algorithm_reference_replays_reported",
    "reporting_full_replays",
    "total_reference_replays_reported",
    "mechanism_activity_json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO.resolve()))
    except ValueError:
        return str(resolved)


def file_manifest(paths: Iterable[Path]) -> list[dict[str, str]]:
    rows = [
        {"path": _repo_path(path), "sha256": sha256(path)}
        for path in paths
    ]
    return sorted(rows, key=lambda row: row["path"])


def tree_manifest(
    root: Path,
    *,
    suffixes: set[str] | None = None,
) -> list[dict[str, str]]:
    rows: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRECTORY_NAMES for part in relative_parts):
            continue
        if path.name in IGNORED_FILE_NAMES or path.name.startswith("._"):
            continue
        if path.suffix == ".pyc":
            continue
        if suffixes is not None and path.suffix.lower() not in suffixes:
            continue
        rows.append(path)
    return file_manifest(rows)


def _tree_lock(
    root: Path,
    *,
    suffixes: set[str] | None = None,
) -> dict[str, Any]:
    files = tree_manifest(root, suffixes=suffixes)
    return {
        "root": _repo_path(root),
        "file_count": len(files),
        "tree_sha256": sha_json(files),
        "files": files,
    }


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: Iterable[str],
) -> None:
    fields = list(fieldnames)
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=fields,
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, stream.getvalue())


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return str(value)


def validate_environment() -> None:
    mismatches = {
        key: {"expected": expected, "actual": os.environ.get(key)}
        for key, expected in REQUIRED_ENVIRONMENT.items()
        if os.environ.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(
            f"single-thread/replay environment is not frozen: {mismatches}"
        )


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in ("alns", "numpy", "scipy"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "NOT_INSTALLED_AS_DISTRIBUTION"
    return versions


def _official_install_snapshot() -> dict[str, Any]:
    manifest = json.loads(INSTALL_MANIFEST.read_text(encoding="utf-8"))
    verified = verify_official_install()
    binary = Path(str(verified["binary"]))
    source_license = Path(str(verified["source_dir"])) / "LICENSE"
    if not source_license.is_file():
        raise FileNotFoundError(source_license)
    if sha256(source_license) != str(verified["license_sha256"]):
        raise RuntimeError("official HGS license hash drift")
    return {
        "official_commit": OFFICIAL_COMMIT,
        "manifest_declared_commit": manifest.get("pinned_commit"),
        "install_manifest": {
            "path": _repo_path(INSTALL_MANIFEST),
            "sha256": sha256(INSTALL_MANIFEST),
        },
        "binary": {
            "path": _repo_path(binary),
            "sha256": sha256(binary),
            "manifest_sha256": verified.get("binary_sha256"),
        },
        "shared_library": {
            "path": _repo_path(OFFICIAL_LIBRARY),
            "sha256": sha256(OFFICIAL_LIBRARY),
            "expected_sha256": OFFICIAL_LIBRARY_SHA256,
        },
        "source_license": {
            "path": _repo_path(source_license),
            "sha256": sha256(source_license),
            "manifest_sha256": verified.get("license_sha256"),
        },
        "tracked_license": {
            "path": _repo_path(TRACKED_LICENSE),
            "sha256": sha256(TRACKED_LICENSE),
            "manifest_sha256": verified.get("tracked_license_sha256"),
        },
        "rebuild_script": {
            "path": _repo_path(REBUILD_SCRIPT),
            "sha256": sha256(REBUILD_SCRIPT),
            "manifest_sha256": verified.get("rebuild_script_sha256"),
        },
        "verified": True,
    }


def _all_manifest_instances(
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        *list(manifest.get("instances", [])),
        *list(manifest.get("backup_instances", [])),
    ]


def verify_bundle_files(
    manifest: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    content_rows: list[dict[str, Any]] = []
    declared_checks = (
        ("builder_repo_relative", "builder_sha256"),
        ("generator_repo_relative", "generator_sha256"),
        ("contract_repo_relative", "contract_sha256"),
    )
    for path_key, hash_key in declared_checks:
        relative = str(manifest.get(path_key, ""))
        path = REPO / relative
        if not relative or not path.is_file():
            failures.append(f"missing_manifest_dependency:{path_key}:{relative}")
        elif sha256(path) != str(manifest.get(hash_key, "")):
            failures.append(f"manifest_dependency_hash:{relative}")

    for item in _all_manifest_instances(manifest):
        instance_id = str(item["instance_id"])
        bundle_dir = BUNDLES / instance_id
        declared = {
            str(name): str(value)
            for name, value in dict(item.get("bundle_files", {})).items()
        }
        actual_names = {
            path.name
            for path in bundle_dir.iterdir()
            if path.is_file()
            and path.name not in IGNORED_FILE_NAMES
            and not path.name.startswith("._")
        } if bundle_dir.is_dir() else set()
        if set(declared) != actual_names:
            failures.append(
                "bundle_file_set:"
                f"{instance_id}:declared={sorted(declared)}:"
                f"actual={sorted(actual_names)}"
            )
        actual_hashes: dict[str, str] = {}
        for name, expected in sorted(declared.items()):
            path = bundle_dir / name
            if not path.is_file():
                failures.append(f"bundle_missing:{instance_id}:{name}")
                continue
            actual = sha256(path)
            actual_hashes[name] = actual
            if actual != expected:
                failures.append(f"bundle_hash:{instance_id}:{name}")

        source_rows: list[dict[str, str]] = []
        source_ids = list(item.get("source_ids", []))
        source_paths = list(item.get("source_paths_repo_relative", []))
        source_hashes = dict(item.get("source_sha256", {}))
        if len(source_ids) != len(source_paths):
            failures.append(f"source_path_count:{instance_id}")
        for source_id, relative in zip(source_ids, source_paths):
            path = REPO / str(relative)
            expected = str(source_hashes.get(source_id, ""))
            if not path.is_file():
                failures.append(f"source_missing:{instance_id}:{source_id}")
                actual = "MISSING"
            else:
                actual = sha256(path)
                if actual != expected:
                    failures.append(f"source_hash:{instance_id}:{source_id}")
            source_rows.append(
                {
                    "source_id": str(source_id),
                    "path": str(relative),
                    "sha256": actual,
                }
            )

        witness = item.get("cross_depot_feasible_witness")
        movable = item.get("movable_charge_witness")
        if (
            item.get("structure_pass") is not True
            or not isinstance(witness, dict)
            or witness.get("full_solution_feasible") is not True
            or not isinstance(movable, dict)
            or float(movable.get("movable_slack_seconds", 0.0)) <= 0.0
        ):
            failures.append(f"structure_witness:{instance_id}")
        try:
            independently_recomputed_structure = structural_checks(
                bundle_dir
            )
        except Exception as error:
            failures.append(
                "structure_recompute_failed:"
                f"{instance_id}:{type(error).__name__}:{error}"
            )
            independently_recomputed_structure = {}
        for key, actual in independently_recomputed_structure.items():
            if sha_json(item.get(key)) != sha_json(actual):
                failures.append(
                    f"structure_recompute_mismatch:{instance_id}:{key}"
                )
        content_rows.append(
            {
                "instance_id": instance_id,
                "role": str(item.get("role", "")),
                "bundle_files": actual_hashes,
                "source_files": source_rows,
                "independently_recomputed_structure": (
                    independently_recomputed_structure
                ),
            }
        )
    snapshot = {
        "instances": sorted(
            content_rows,
            key=lambda row: row["instance_id"],
        )
    }
    snapshot["content_sha256"] = sha_json(snapshot["instances"])
    return sorted(set(failures)), snapshot


def _dependency_snapshot() -> dict[str, Any]:
    return {
        "solver_src": _tree_lock(REPO / "solver/src"),
        "models_src": _tree_lock(REPO / "models/src"),
        "current_prototype_python": _tree_lock(HERE, suffixes={".py"}),
        "legacy_mechanism_prototype_python": _tree_lock(
            LEGACY,
            suffixes={".py"},
        ),
        "reference_n_wouda_alns_source_and_license": _tree_lock(
            REFERENCE_ALNS,
            suffixes=REFERENCE_SUFFIXES,
        ),
    }


def make_blind_lock(
    manifest: dict[str, Any],
    primary_run_order: list[dict[str, str]],
    backup_run_order: list[dict[str, str]],
) -> dict[str, Any]:
    dataset_failures, dataset_snapshot = verify_bundle_files(manifest)
    if dataset_failures:
        raise RuntimeError(
            f"dataset prelock verification failed: {dataset_failures}"
        )
    parameters = {
        "seed": SEED,
        "complete_candidate_budget": BUDGET,
        "battery_kwh": PRICES.B_battery_kwh,
        "hgs_no_improvement_iterations": 100,
        "hgs_time_window_weight": 1.0,
        "tail_share": 0.30,
        "strict_tolerance": STRICT_TOL,
        "minimum_median_improvement_percent": (
            MIN_MEDIAN_IMPROVEMENT_PERCENT
        ),
        "maximum_mid_ablation_regression_percent": (
            MAX_MID_ABLATION_REGRESSION_PERCENT
        ),
        "maximum_wall_ratio": MAX_WALL_RATIO,
    }
    return {
        "schema_version": "resetp.dual-basin-alns.d2-blind-lock.v2",
        "created_before_algorithm_scores": True,
        "parameters": parameters,
        "parameter_sha256": sha_json(parameters),
        "dataset_manifest": {
            "path": _repo_path(BUNDLES / "manifest.json"),
            "sha256": sha256(BUNDLES / "manifest.json"),
        },
        "dataset_content": dataset_snapshot,
        "primary_instance_ids": [
            str(item["instance_id"])
            for item in manifest["instances"]
        ],
        "backup_instance_ids": [
            str(item["instance_id"])
            for item in manifest["backup_instances"]
        ],
        "freshness_label": manifest["freshness_label"],
        "seeds": [SEED],
        "arms": list(ARMS),
        "primary_run_order": primary_run_order,
        "primary_run_order_sha256": sha_json(primary_run_order),
        "backup_run_order": backup_run_order,
        "backup_run_order_sha256": sha_json(backup_run_order),
        "environment": dict(REQUIRED_ENVIRONMENT),
        "runtime": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "platform": platform.platform(),
            "package_versions": _package_versions(),
        },
        "protected_file_sha256": {
            _repo_path(path): sha256(path)
            for path in PROTECTED_FILES
        },
        "runner_and_contract_files": file_manifest(
            RUNNER_AND_CONTRACT_FILES
        ),
        "dependency_trees": _dependency_snapshot(),
        "official_hgs_install": _official_install_snapshot(),
        "compute_comparability": {
            "complete_resetp_candidate_evaluations_equalized": True,
            "total_compute_equalized": False,
            "reason": (
                "official HGS control performs 100 native HGS calls while "
                "the candidate performs one; native work and wall clock are "
                "reported separately"
            ),
        },
    }


def validate_lock(
    lock: dict[str, Any],
    manifest: dict[str, Any],
    primary_run_order: list[dict[str, str]],
    backup_run_order: list[dict[str, str]],
) -> list[str]:
    try:
        expected = make_blind_lock(
            manifest,
            primary_run_order,
            backup_run_order,
        )
    except Exception as error:
        return [
            "lock_recompute_failed:"
            f"{type(error).__name__}:{error}"
        ]
    if sha_json(lock) == sha_json(expected):
        return []
    failures = ["blind_lock_full_payload_mismatch"]
    for key in sorted(set(lock) | set(expected)):
        if sha_json(lock.get(key)) != sha_json(expected.get(key)):
            failures.append(f"blind_lock_field:{key}")
    return failures


def run_arm(arm: str, bundle_dir: Path) -> Any:
    """Run one locked arm with a common end-to-end timing boundary."""

    started = time.perf_counter()
    if arm == CANDIDATE:
        result = run_dual_basin_mechanism_alns(
            bundle_dir,
            seed=SEED,
            config=DualBasinConfig(total_eval_budget=BUDGET),
            prices=PRICES,
        )
        return _retime(result, started)
    if arm == RAW_SELECTOR:
        result = run_dual_basin_mechanism_alns(
            bundle_dir,
            seed=SEED,
            config=DualBasinConfig(
                total_eval_budget=BUDGET,
                selector_mode=SELECTOR_RAW,
            ),
            prices=PRICES,
        )
        return _retime(result, started)
    if arm == NO_MID:
        result = run_dual_basin_mechanism_alns(
            bundle_dir,
            seed=SEED,
            config=DualBasinConfig(
                total_eval_budget=BUDGET,
                enable_mid_completion=False,
            ),
            prices=PRICES,
        )
        return _retime(result, started)
    if arm == V7:
        result = run_mechanism_alns_v7(
            bundle_dir,
            seed=SEED,
            eval_budget=BUDGET,
            prices=PRICES,
        )
        return _retime(result, started)
    if arm == PROJECT_ALNS:
        result = run_pure_alns(
            bundle_dir,
            seed=SEED,
            eval_budget=BUDGET,
            prices=PRICES,
        )
        return _retime(result, started)
    if arm == OFFICIAL_HGS:
        warm = build_v7_warm(load_search_bundle(bundle_dir), prices=PRICES)
        base = run_official_hgs_neutral(
            bundle_dir,
            seed=SEED,
            eval_budget=BUDGET,
            prices=PRICES,
            initial_solution=warm,
        )
        completion = apply_terminal_completion(
            bundle_dir,
            base.best_solution,
            prices=PRICES,
        )
        result = _DerivedResult(
            algorithm=OFFICIAL_HGS,
            best_solution=completion.solution,
            best_cost=completion.cost,
            evaluations=base.evaluations,
            elapsed_seconds=0.0,
            route_count=len(completion.solution.routes),
            feasible=completion.feasible,
            mechanism_activity={
                "route_source": base.mechanism_activity,
                "common_completion": completion.activity,
            },
        )
        return _retime(result, started)
    if arm == ORIGINAL_ALNS:
        warm = build_v7_warm(load_search_bundle(bundle_dir), prices=PRICES)
        base = run_original_n_wouda_alns_neutral(
            bundle_dir,
            seed=SEED,
            eval_budget=BUDGET,
            prices=PRICES,
            initial_solution=warm,
        )
        completion = apply_terminal_completion(
            bundle_dir,
            base.best_solution,
            prices=PRICES,
        )
        result = _DerivedResult(
            algorithm=ORIGINAL_ALNS,
            best_solution=completion.solution,
            best_cost=completion.cost,
            evaluations=base.evaluations,
            elapsed_seconds=0.0,
            route_count=len(completion.solution.routes),
            feasible=completion.feasible,
            mechanism_activity={
                "route_source": base.mechanism_activity,
                "common_completion": completion.activity,
            },
        )
        return _retime(result, started)
    raise ValueError(f"unknown arm {arm!r}")


class _DerivedResult:
    def __init__(
        self,
        *,
        algorithm: str,
        best_solution: Any,
        best_cost: float,
        evaluations: int,
        elapsed_seconds: float,
        route_count: int,
        feasible: bool,
        mechanism_activity: dict[str, Any],
        selected_basin: str = "",
    ) -> None:
        self.algorithm = algorithm
        self.best_solution = best_solution
        self.best_cost = float(best_cost)
        self.evaluations = int(evaluations)
        self.elapsed_seconds = float(elapsed_seconds)
        self.route_count = int(route_count)
        self.feasible = bool(feasible)
        self.mechanism_activity = mechanism_activity
        self.selected_basin = str(selected_basin)


def _retime(result: Any, started: float) -> _DerivedResult:
    return _DerivedResult(
        algorithm=str(result.algorithm),
        best_solution=result.best_solution,
        best_cost=float(result.best_cost),
        evaluations=int(result.evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=int(result.route_count),
        feasible=bool(result.feasible),
        mechanism_activity=dict(result.mechanism_activity),
        selected_basin=str(getattr(result, "selected_basin", "")),
    )


def _activity_metric(payload: Any, keys: set[str]) -> float:
    """Sum reported aggregate metrics without double-counting their children."""

    if isinstance(payload, dict):
        for key in sorted(keys):
            value = payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return sum(_activity_metric(value, keys) for value in payload.values())
    if isinstance(payload, (list, tuple)):
        return sum(_activity_metric(value, keys) for value in payload)
    return 0.0


def _native_cpu_seconds(activity: dict[str, Any]) -> float:
    seconds = _activity_metric(activity, {"native_cpu_seconds"})
    milliseconds = _activity_metric(
        activity,
        {"hgs_native_cpu_milliseconds"},
    )
    return float(seconds + milliseconds / 1_000.0)


def _native_wall_seconds(activity: dict[str, Any]) -> float:
    seconds = _activity_metric(activity, {"wall_seconds"})
    milliseconds = _activity_metric(
        activity,
        {"hgs_adapter_wall_milliseconds"},
    )
    return float(seconds + milliseconds / 1_000.0)


def _reference_replays(activity: dict[str, Any]) -> int:
    def count(payload: Any) -> int:
        if isinstance(payload, dict):
            ledger = payload.get("reference_replay_ledger")
            if isinstance(ledger, dict) and isinstance(
                ledger.get("total_reported"),
                (int, float),
            ):
                return int(ledger["total_reported"])
            if isinstance(
                payload.get("full_solution_replays"),
                (int, float),
            ):
                # This field is the declared aggregate for the whole
                # completion subtree, so its children must not be counted.
                return int(payload["full_solution_replays"])
            direct = 0
            reference = payload.get("reference_replays")
            if isinstance(reference, (int, float)):
                direct += int(reference)
            independent = payload.get("independent_final_replays")
            if isinstance(independent, (int, float)):
                direct += int(independent)
            if not isinstance(reference, (int, float)):
                score_counts = payload.get("score_counts")
                if isinstance(score_counts, dict) and isinstance(
                    score_counts.get("reference"),
                    (int, float),
                ):
                    direct += int(score_counts["reference"])
            ignored = {
                "reference_replay_ledger",
                "full_solution_replays",
                "reference_replays",
                "independent_final_replays",
                "score_counts",
            }
            return direct + sum(
                count(value)
                for key, value in payload.items()
                if key not in ignored
            )
        if isinstance(payload, (list, tuple)):
            return sum(count(value) for value in payload)
        return 0

    return count(activity)


def normalize_row(
    *,
    arm: str,
    instance_row: dict[str, Any],
    bundle_dir: Path,
    result: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = load_search_bundle(bundle_dir)
    recomputed = independent_cost(bundle_dir, result.best_solution, PRICES)
    violations = check_solution(
        result.best_solution,
        bundle.instance,
        PRICES,
    )
    metrics = evaluate(
        result.best_solution,
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
    )
    signature = solution_signature_hash(result.best_solution)
    activity = _jsonable(result.mechanism_activity)
    algorithm_reference_replays = _reference_replays(activity)
    reporting_full_replays = 2
    row = {
        "instance_id": instance_row["instance_id"],
        "dataset_role": instance_row["role"],
        "source_scale": int(instance_row["source_scale"]),
        "actual_customer_count": int(instance_row["actual_customer_count"]),
        "actual_depot_count": int(instance_row["actual_depot_count"]),
        "seed": SEED,
        "budget": BUDGET,
        "arm": arm,
        "reported_algorithm": str(result.algorithm),
        "reported_cost": float(result.best_cost),
        "recomputed_cost": float(recomputed),
        "cost_match": (
            abs(float(result.best_cost) - float(recomputed)) <= 1.0e-7
        ),
        "evaluations": int(result.evaluations),
        "budget_exact": int(result.evaluations) == BUDGET,
        "complete_resetp_candidate_budget_equalized": True,
        "total_compute_equalized": False,
        "elapsed_seconds": float(result.elapsed_seconds),
        "timing_scope": (
            "runner_arm_entry_through_return_including_warm_and_any_completion"
        ),
        "route_count": len(result.best_solution.routes),
        "ev_route_count": sum(
            route.vehicle_type.lower() == "ev"
            for route in result.best_solution.routes
        ),
        "charging_action_count": len(result.best_solution.charging_actions),
        "feasible": not violations and bool(result.feasible),
        "violation_count": len(violations),
        "selected_basin": str(getattr(result, "selected_basin", "")),
        "solution_signature": signature,
        "total_emissions_kg": float(metrics["E_total"]),
        "charging_emissions_kg": float(metrics["E_ev_indirect"]),
        "hgs_native_calls_reported": int(
            _activity_metric(activity, {"native_calls", "hgs_native_calls"})
        ),
        "hgs_native_cpu_seconds_reported": _native_cpu_seconds(activity),
        "hgs_native_wall_seconds_reported": _native_wall_seconds(activity),
        "route_proxy_evaluations_reported": int(
            _activity_metric(activity, {"route_proxy_evaluations"})
        ),
        "route_local_exact_evaluations_reported": int(
            _activity_metric(activity, {"route_local_exact_evaluations"})
        ),
        "route_local_schedule_evaluations_reported": int(
            _activity_metric(
                activity,
                {"route_local_schedule_evaluations"},
            )
        ),
        "algorithm_reference_replays_reported": algorithm_reference_replays,
        "reporting_full_replays": reporting_full_replays,
        "total_reference_replays_reported": (
            algorithm_reference_replays + reporting_full_replays
        ),
        "mechanism_activity_json": json.dumps(
            activity,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }
    witness = {
        "instance_id": instance_row["instance_id"],
        "dataset_role": instance_row["role"],
        "arm": arm,
        "seed": SEED,
        "budget": BUDGET,
        "reported_cost": float(result.best_cost),
        "recomputed_cost": float(recomputed),
        "reporting_full_replays": reporting_full_replays,
        "metrics": _jsonable(metrics),
        "solution_signature": signature,
        "solution": solution_payload(result.best_solution),
        "mechanism_activity": activity,
    }
    return row, witness


def _invalid_decision(
    *,
    failures: list[str],
    run_failures: list[dict[str, Any]],
    dataset_role: str,
    backup_activated: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "resetp.dual-basin-alns.d2-decision.v2",
        "verdict": "INVALID_D2_GATE",
        "go": False,
        "stage2_activated": False,
        "formal_experiment_activated": False,
        "decision_dataset_role": dataset_role,
        "backup_activated": backup_activated,
        "validity_failures": sorted(set(failures)),
        "run_failure_count": len(run_failures),
        "comparisons": {},
        "all_saturated": False,
        "saturated_instances": [],
    }


def build_decision(
    rows: list[dict[str, Any]],
    active_instances: list[dict[str, Any]],
    lock_failures: list[str],
    *,
    dataset_role: str,
) -> dict[str, Any]:
    by_key = {(row["instance_id"], row["arm"]): row for row in rows}
    instance_ids = [str(item["instance_id"]) for item in active_instances]
    validity_failures: list[str] = list(lock_failures)
    missing = [
        f"missing:{instance_id}:{arm}"
        for instance_id in instance_ids
        for arm in ARMS
        if (instance_id, arm) not in by_key
    ]
    validity_failures.extend(missing)
    for row in rows:
        if row["instance_id"] not in instance_ids:
            continue
        if not row["feasible"]:
            validity_failures.append(
                f"infeasible:{row['instance_id']}:{row['arm']}"
            )
        if not row["cost_match"]:
            validity_failures.append(
                f"cost_mismatch:{row['instance_id']}:{row['arm']}"
            )
        if not row["budget_exact"]:
            validity_failures.append(
                f"budget:{row['instance_id']}:{row['arm']}"
            )
    if validity_failures:
        return _invalid_decision(
            failures=validity_failures,
            run_failures=[],
            dataset_role=dataset_role,
            backup_activated=dataset_role == "saturation_backup",
        )

    comparisons: dict[str, Any] = {}
    strict_wins: dict[str, int] = {}
    median_improvements: dict[str, float] = {}
    for control in (*STRONG_CONTROLS, RAW_SELECTOR, NO_MID):
        values: list[float] = []
        wins = 0
        nonlosses = 0
        for instance_id in instance_ids:
            candidate = float(
                by_key[(instance_id, CANDIDATE)]["recomputed_cost"]
            )
            baseline = float(
                by_key[(instance_id, control)]["recomputed_cost"]
            )
            improvement = (baseline - candidate) / baseline * 100.0
            values.append(float(improvement))
            wins += int(candidate < baseline - STRICT_TOL)
            nonlosses += int(candidate <= baseline + STRICT_TOL)
        strict_wins[control] = wins
        median_improvements[control] = float(statistics.median(values))
        comparisons[control] = {
            "improvement_percent_by_instance": dict(
                zip(instance_ids, values, strict=True)
            ),
            "strict_wins": wins,
            "nonlosses": nonlosses,
            "median_improvement_percent": float(statistics.median(values)),
        }

    strong_pass = all(
        strict_wins[control] == len(instance_ids)
        and median_improvements[control]
        >= MIN_MEDIAN_IMPROVEMENT_PERCENT - 1.0e-12
        for control in STRONG_CONTROLS
    )
    selector_pass = bool(
        strict_wins[RAW_SELECTOR] >= 1
        and comparisons[RAW_SELECTOR]["nonlosses"] == len(instance_ids)
        and median_improvements[RAW_SELECTOR]
        >= MIN_MEDIAN_IMPROVEMENT_PERCENT - 1.0e-12
    )
    mid_regressions = [
        -value
        for value in comparisons[NO_MID][
            "improvement_percent_by_instance"
        ].values()
        if value < 0.0
    ]
    mid_safety_pass = bool(
        not mid_regressions
        or max(mid_regressions)
        <= MAX_MID_ABLATION_REGRESSION_PERCENT + 1.0e-12
    )
    mid_contribution_proven = bool(
        strict_wins[NO_MID] >= 1
        and comparisons[NO_MID]["nonlosses"] == len(instance_ids)
    )
    if mid_contribution_proven:
        mid_contribution_status = "PROVEN_ON_THIS_D2_GATE"
    elif mid_safety_pass:
        mid_contribution_status = "SAFE_BUT_NOT_PROVEN"
    else:
        mid_contribution_status = "FAILED_SAFETY_LIMIT"

    wall_ratios: dict[str, float] = {}
    control_wall_medians: dict[str, float] = {}
    for instance_id in instance_ids:
        control_median = float(
            statistics.median(
                float(by_key[(instance_id, arm)]["elapsed_seconds"])
                for arm in STRONG_CONTROLS
            )
        )
        control_wall_medians[instance_id] = control_median
        candidate_wall = float(
            by_key[(instance_id, CANDIDATE)]["elapsed_seconds"]
        )
        wall_ratios[instance_id] = (
            candidate_wall / control_median
            if control_median > 0.0
            else float("inf")
        )
    wall_ratio_median = float(statistics.median(wall_ratios.values()))
    wall_pass = bool(
        all(
            ratio <= MAX_WALL_RATIO + 1.0e-12
            for ratio in wall_ratios.values()
        )
        and wall_ratio_median <= MAX_WALL_RATIO + 1.0e-12
    )

    saturation_details: dict[str, Any] = {}
    saturated_instances: list[str] = []
    for instance_id in instance_ids:
        costs = [
            float(by_key[(instance_id, arm)]["recomputed_cost"])
            for arm in ARMS
        ]
        signatures = {
            str(by_key[(instance_id, arm)]["solution_signature"])
            for arm in ARMS
        }
        cost_equal = max(costs) - min(costs) <= STRICT_TOL
        signature_equal = len(signatures) == 1
        saturation_details[instance_id] = {
            "cost_equal": cost_equal,
            "solution_signature_equal": signature_equal,
        }
        if cost_equal and signature_equal:
            saturated_instances.append(instance_id)
    all_saturated = len(saturated_instances) == len(instance_ids)

    if all_saturated:
        verdict = "INCONCLUSIVE_SATURATED_SMALL_D2"
        go = False
    elif strong_pass and selector_pass and mid_safety_pass and wall_pass:
        verdict = "GO_SMALL_MULTI_SEED_CONFIRMATION"
        go = True
    else:
        verdict = "STOP_DUAL_BASIN_MECHANISM_ALNS_D2"
        go = False
    return {
        "schema_version": "resetp.dual-basin-alns.d2-decision.v2",
        "verdict": verdict,
        "go": go,
        "stage2_activated": False,
        "formal_experiment_activated": False,
        "decision_dataset_role": dataset_role,
        "backup_activated": dataset_role == "saturation_backup",
        "active_instance_ids": instance_ids,
        "validity_failures": [],
        "comparisons": comparisons,
        "strong_control_pass": strong_pass,
        "mechanism_selector_ablation_pass": selector_pass,
        "mid_completion_safety_pass": mid_safety_pass,
        "mid_completion_contribution_proven": mid_contribution_proven,
        "mid_completion_contribution_status": mid_contribution_status,
        "wall_control_median_seconds_by_instance": control_wall_medians,
        "candidate_wall_ratio_by_instance": wall_ratios,
        "candidate_wall_ratio_median": wall_ratio_median,
        "wall_pass": wall_pass,
        "saturation_details": saturation_details,
        "saturated_instances": saturated_instances,
        "all_saturated": all_saturated,
        "thresholds": {
            "strict_win_each_fresh_instance": True,
            "minimum_median_improvement_percent": (
                MIN_MEDIAN_IMPROVEMENT_PERCENT
            ),
            "maximum_mid_ablation_regression_percent": (
                MAX_MID_ABLATION_REGRESSION_PERCENT
            ),
            "maximum_wall_ratio_each_instance_and_median": MAX_WALL_RATIO,
            "saturation_requires_cost_and_solution_signature_equality": True,
        },
    }


def report_text(
    decision: dict[str, Any],
    rows: list[dict[str, Any]],
    run_failures: list[dict[str, Any]],
) -> str:
    lines = [
        "# 机制裁决双盆地 ALNS：D2 新组合开发门",
        "",
        f"- 结论：`{decision['verdict']}`",
        "- 范围：阶段一隔离开发；未进入阶段二，未启动正式实验。",
        "- 数据：新组合三班完整模型包；原始 Goeke 文件并非首次出现。",
        f"- 最终裁决数据档：`{decision.get('decision_dataset_role', '-')}`。",
        f"- 完整候选预算：每个带搜索臂 {BUDGET} 次。",
        (
            "- 公平边界：完整 ReSETP 候选评价数相同；总算力不相同。"
            "官方 HGS 的额外原生调用与墙钟单独报告。"
        ),
        "- 每个完成臂另做 2 次只用于报告的完整成本复算。",
        "",
        "## 成本与选择",
        "",
        "| 数据档 | 实例 | 算法臂 | 成本 | 盆地 | 秒 | HGS原生调用 |",
        "|---|---|---|---:|---|---:|---:|",
    ]
    for row in sorted(
        rows,
        key=lambda item: (
            item["dataset_role"],
            item["instance_id"],
            item["arm"],
        ),
    ):
        lines.append(
            f"| {row['dataset_role']} | {row['instance_id']} | "
            f"{row['arm']} | {row['recomputed_cost']:.9f} | "
            f"{row['selected_basin'] or '-'} | "
            f"{row['elapsed_seconds']:.3f} | "
            f"{row['hgs_native_calls_reported']} |"
        )
    if run_failures:
        lines.extend(["", "## 运行失败", ""])
        for failure in run_failures:
            lines.append(
                f"- `{failure.get('phase')}` / "
                f"`{failure.get('instance_id')}` / "
                f"`{failure.get('arm')}`："
                f"`{failure.get('exception_type')}`，"
                f"{failure.get('message')}"
            )
    comparisons = decision.get("comparisons", {})
    if comparisons:
        lines.extend(["", "## 预注册判断", ""])
        denominator = len(decision.get("active_instance_ids", []))
        for control, comparison in comparisons.items():
            lines.append(
                f"- 对 `{control}`：严格胜 "
                f"{comparison['strict_wins']}/{denominator}，中位改善 "
                f"{comparison['median_improvement_percent']:.3f}%。"
            )
        for instance_id, ratio in decision.get(
            "candidate_wall_ratio_by_instance",
            {},
        ).items():
            lines.append(
                f"- `{instance_id}` 的候选/同题强对手中位墙钟比："
                f"{ratio:.3f}。"
            )
        lines.append(
            "- 墙钟比中位数："
            f"{decision['candidate_wall_ratio_median']:.3f}，"
            f"每题及中位门槛均不超过 {MAX_WALL_RATIO:.2f}。"
        )
        lines.append(
            "- 中段机制校正："
            f"`{decision['mid_completion_contribution_status']}`。"
        )
    if decision.get("validity_failures"):
        lines.extend(["", "## 有效性失败", ""])
        lines.extend(
            f"- `{failure}`"
            for failure in decision["validity_failures"]
        )
    lines.extend(
        [
            "",
            "本报告只是一颗种子的开发门，不是论文性能结论。",
            "",
        ]
    )
    return "\n".join(lines)


def _run_order(
    instances: list[dict[str, Any]],
    *,
    phase: str,
) -> list[dict[str, str]]:
    return sorted(
        (
            {
                "phase": phase,
                "instance_id": str(item["instance_id"]),
                "arm": arm,
            }
            for item in instances
            for arm in ARMS
        ),
        key=sha_json,
    )


def _execute_order(
    order: list[dict[str, str]],
    instance_rows: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    witnesses: list[dict[str, Any]],
    run_failures: list[dict[str, Any]],
) -> bool:
    for item in order:
        instance_id = item["instance_id"]
        arm = item["arm"]
        try:
            result = run_arm(arm, BUNDLES / instance_id)
            row, witness = normalize_row(
                arm=arm,
                instance_row=instance_rows[instance_id],
                bundle_dir=BUNDLES / instance_id,
                result=result,
            )
            rows.append(row)
            witnesses.append(witness)
        except Exception as error:
            run_failures.append(
                {
                    "phase": item["phase"],
                    "instance_id": instance_id,
                    "arm": arm,
                    "exception_type": type(error).__name__,
                    "message": str(error),
                    "traceback": traceback.format_exc(),
                }
            )
            return False
    return True


def _finalize(
    *,
    rows: list[dict[str, Any]],
    witnesses: list[dict[str, Any]],
    run_failures: list[dict[str, Any]],
    metadata: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    sorted_rows = sorted(
        rows,
        key=lambda item: (
            item["dataset_role"],
            item["instance_id"],
            item["arm"],
        ),
    )
    sorted_witnesses = sorted(
        witnesses,
        key=lambda item: (
            item["dataset_role"],
            item["instance_id"],
            item["arm"],
        ),
    )
    atomic_csv(OUT / "raw_runs.csv", sorted_rows, fieldnames=RAW_FIELDS)
    atomic_json(OUT / "solution_witnesses.json", sorted_witnesses)
    atomic_json(OUT / "run_failures.json", run_failures)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        report_text(decision, sorted_rows, run_failures),
    )
    artifact_paths = sorted(
        path
        for path in OUT.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    atomic_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "files": {
                path.name: sha256(path)
                for path in artifact_paths
            },
        },
    )


def main() -> int:
    validate_environment()
    if OUT.exists():
        raise FileExistsError(
            f"refusing to overwrite frozen D2 gate output: {OUT}"
        )
    manifest_path = BUNDLES / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    primary_instances = list(manifest["instances"])
    backup_instances = list(manifest["backup_instances"])
    primary_order = _run_order(primary_instances, phase="primary")
    backup_order = _run_order(backup_instances, phase="saturation_backup")

    # Build and verify the full deterministic lock before creating the output
    # directory.  A preflight failure therefore cannot consume the blind gate.
    lock = make_blind_lock(manifest, primary_order, backup_order)
    preflight_failures = validate_lock(
        lock,
        manifest,
        primary_order,
        backup_order,
    )
    if preflight_failures:
        raise RuntimeError(
            f"blind-lock preflight failed: {preflight_failures}"
        )

    OUT.mkdir(parents=True)
    atomic_json(OUT / "blind_lock.json", lock)
    persisted_lock = json.loads(
        (OUT / "blind_lock.json").read_text(encoding="utf-8")
    )
    if sha_json(persisted_lock) != sha_json(lock):
        raise RuntimeError(
            "persisted blind_lock.json differs from the pre-score lock"
        )
    lock = persisted_lock
    persisted_lock_failures = validate_lock(
        lock,
        manifest,
        primary_order,
        backup_order,
    )
    if persisted_lock_failures:
        raise RuntimeError(
            "persisted blind-lock validation failed before scores: "
            f"{persisted_lock_failures}"
        )
    gate_started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    run_failures: list[dict[str, Any]] = []
    all_instances = {
        str(item["instance_id"]): item
        for item in [*primary_instances, *backup_instances]
    }
    backup_activated = False
    decision_role = "primary"

    primary_completed = _execute_order(
        primary_order,
        all_instances,
        rows,
        witnesses,
        run_failures,
    )
    primary_lock_failures = validate_lock(
        lock,
        manifest,
        primary_order,
        backup_order,
    )
    if run_failures or primary_lock_failures or not primary_completed:
        failures = [
            *primary_lock_failures,
            *(
                f"arm_failure:{item['phase']}:{item['instance_id']}:{item['arm']}"
                for item in run_failures
            ),
        ]
        decision = _invalid_decision(
            failures=failures,
            run_failures=run_failures,
            dataset_role=decision_role,
            backup_activated=False,
        )
    else:
        primary_decision = build_decision(
            rows,
            primary_instances,
            [],
            dataset_role="primary",
        )
        if primary_decision["all_saturated"]:
            backup_activated = True
            decision_role = "saturation_backup"
            backup_completed = _execute_order(
                backup_order,
                all_instances,
                rows,
                witnesses,
                run_failures,
            )
            backup_lock_failures = validate_lock(
                lock,
                manifest,
                primary_order,
                backup_order,
            )
            if run_failures or backup_lock_failures or not backup_completed:
                failures = [
                    *backup_lock_failures,
                    *(
                        "arm_failure:"
                        f"{item['phase']}:{item['instance_id']}:{item['arm']}"
                        for item in run_failures
                    ),
                ]
                decision = _invalid_decision(
                    failures=failures,
                    run_failures=run_failures,
                    dataset_role=decision_role,
                    backup_activated=True,
                )
            else:
                backup_rows = [
                    row
                    for row in rows
                    if row["dataset_role"] == "saturation_backup"
                ]
                decision = build_decision(
                    backup_rows,
                    backup_instances,
                    [],
                    dataset_role="saturation_backup",
                )
                decision["primary_saturation_decision"] = primary_decision
        else:
            decision = primary_decision

    final_lock_failures = validate_lock(
        lock,
        manifest,
        primary_order,
        backup_order,
    )
    if final_lock_failures:
        decision = _invalid_decision(
            failures=[
                *final_lock_failures,
                *list(decision.get("validity_failures", [])),
            ],
            run_failures=run_failures,
            dataset_role=decision_role,
            backup_activated=backup_activated,
        )

    metadata = {
        "schema_version": "resetp.dual-basin-alns.d2-metadata.v2",
        "purpose": "stage1_isolated_development_gate_only",
        "freshness_label": manifest["freshness_label"],
        "primary_instance_ids": [
            str(item["instance_id"]) for item in primary_instances
        ],
        "backup_instance_ids": [
            str(item["instance_id"]) for item in backup_instances
        ],
        "backup_activated": backup_activated,
        "decision_dataset_role": decision_role,
        "arms": list(ARMS),
        "seed": SEED,
        "budget": BUDGET,
        "prices": {"B_battery_kwh": PRICES.B_battery_kwh},
        "environment": dict(REQUIRED_ENVIRONMENT),
        "blind_lock_sha256": sha256(OUT / "blind_lock.json"),
        "complete_resetp_candidate_evaluations_equalized": True,
        "total_compute_equalized": False,
        "reporting_full_replays_per_completed_arm": 2,
        "completed_arm_count": len(rows),
        "run_failure_count": len(run_failures),
        "gate_elapsed_seconds": time.perf_counter() - gate_started,
        "stage2_activated": False,
        "formal_experiment_activated": False,
    }
    _finalize(
        rows=rows,
        witnesses=witnesses,
        run_failures=run_failures,
        metadata=metadata,
        decision=decision,
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if decision["go"]:
        return 0
    if decision["verdict"] == "INVALID_D2_GATE":
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
