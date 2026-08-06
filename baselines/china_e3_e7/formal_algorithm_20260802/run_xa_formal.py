#!/opt/anaconda3/bin/python3.13
"""XA formal algorithm experiment for paper Sections 4.2 and 4.3.

The ``prepare`` command creates the immutable pre-search metadata.  The
``run`` command refuses source drift, executes all 80 preregistered tasks,
keeps one complete solution per task, and materialises the five required
record surfaces plus paper-ready tables.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
import platform
import statistics
import subprocess
import sys
import time
import traceback
import concurrent.futures.process as futures_process
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
DISTANCE_ADAPTER = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_vs_opensource_20260727/pyvrp_adapter.py"
)
PYVRP_SITE = (
    REPO
    / "build/python_envs/pyvrp-hgs-0.12.2/"
    "lib/python3.13/site-packages"
)
for _path in reversed((PROTOTYPE, SOLVER_SRC, MODELS_SRC, PYVRP_SITE)):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from epochal_hgs import _run_exact_epoch, build_pyvrp_problem  # noqa: E402
from route_pool_sp import (  # noqa: E402
    _accepted_mip_completion,
    _route_pool_records,
    _solve_set_partitioning,
    run_hgs_route_pool_recombination,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    _physicalize_multitrip_solution,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.model_config import (  # noqa: E402
    ModelConfig,
    model_config_scope,
)
from setp_solver.solution import Route, Solution  # noqa: E402


SCHEMA = "resetp.xa-formal-algorithm.v1"
INSTANCE_ID = "cn-prd-100c-01-V2-LOCATIONS"
FLEET_AUTHORITY = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802"
)
FLEET_EVIDENCE = (
    REPO / "baselines/china_e3_e7/fleet_authority_v3_20260802"
)
MODEL_CONFIG = ModelConfig(
    strict_multitrip=True,
    depot_charger_capacity_mode="unbounded",
)
SEEDS = tuple(range(2026080201, 2026080211))
MAX_HGS_ITERATIONS = 2000
MAX_NO_IMPROVEMENT = 150
MAX_COMPLETE_SEARCH_EVALUATIONS = 100
WALLCLOCK_SAFETY_SECONDS_PER_VIEW = 7200.0
SP_TIME_LIMIT_SECONDS = 10.0
MAX_WORKERS = 4
MV_ITERATIONS = {
    "cv_only": 600,
    "naive_ev": 600,
    "mechanism_ev": 800,
}
MV_CHECKPOINTS = {
    "cv_only": 100,
    "naive_ev": 100,
    "mechanism_ev": 100,
}
MV_NO_IMPROVEMENT = {mode: MAX_NO_IMPROVEMENT for mode in MV_ITERATIONS}
MV_SP_ARCHIVES = {mode: 24 for mode in MV_ITERATIONS}
MV_NO_SP_ARCHIVES = {
    "cv_only": 25,
    "naive_ev": 25,
    "mechanism_ev": 24,
}
SINGLE_ARCHIVE = 18
SINGLE_SP_ARCHIVE = 16
SINGLE_CHECKPOINT = 25

GROUP1_ARMS = (
    ("PYVRP_HGS", "PyVRP-HGS", "distance_only"),
    ("HGS_F", "HGS-F", "cv_only"),
    ("HGS_E", "HGS-E", "naive_ev"),
    ("HGS_M", "HGS-M", "mechanism_ev"),
    ("MV_HGS_SP", "MV-HGS-SP", "mv_sp"),
)
GROUP2_ARMS = (
    ("MV_HGS_SP_FULL", "MV-HGS-SP full", "mv_sp"),
    ("HGS_M_SP_NO_MULTIVIEW", "HGS-M-SP (-multi-view)", "single_sp"),
    ("MV_HGS_NO_SP", "MV-HGS (-timed MIP recombination)", "mv_no_sp"),
)

RAW_FIELDS = (
    "task_id",
    "group",
    "instance_id",
    "arm_id",
    "algorithm",
    "seed",
    "terminal_status",
    "feasible",
    "objective_cny",
    "hgs_iterations_actual",
    "complete_search_evaluations_actual",
    "complete_search_evaluations_max",
    "post_search_certificate_evaluations",
    "max_hgs_iterations",
    "max_no_improvement_iterations",
    "stop_reason",
    "cpu_seconds",
    "cpu_minutes",
    "wall_seconds",
    "violation_count",
    "solution_path",
    "solution_sha256",
    "common_initial_solution_sha256",
    "route_count",
    "physical_vehicle_count",
    "sp_status",
    "sp_mip_gap",
    "per_view_json",
    "error_type",
    "error_message",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_json_new(path: Path, payload: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))


def _write_json_replace(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO))


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def _load_distance_adapter() -> Any:
    name = "_xa_distance_only_adapter"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, DISTANCE_ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load distance adapter: {DISTANCE_ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _bundle() -> Any:
    return load_china81_bundle(
        REPO,
        INSTANCE_ID,
        fleet_authority=FLEET_AUTHORITY,
        model_config=MODEL_CONFIG,
    )


def _common_initial(bundle: Any) -> Any:
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
                            f"XA-INITIAL-{depot_id}-{registered_type.upper()}-"
                            f"{index:03d}"
                        ),
                        vehicle_type=registered_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *[str(item) for item in row["customers"]],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def _solution_dict(solution: Any) -> dict[str, Any]:
    return asdict(solution)


def _solution_semantic_sha256(solution: Any) -> str:
    return _sha256_bytes(_json_bytes(_solution_dict(solution)))


def _task_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for seed in SEEDS:
        for arm_id, algorithm, implementation in GROUP1_ARMS:
            specs.append(
                {
                    "task_id": f"G1__{arm_id}__S{seed}",
                    "group": "4.2_five_algorithm_comparison",
                    "arm_id": arm_id,
                    "algorithm": algorithm,
                    "implementation": implementation,
                    "seed": seed,
                }
            )
    for seed in SEEDS:
        for arm_id, algorithm, implementation in GROUP2_ARMS:
            specs.append(
                {
                    "task_id": f"G2__{arm_id}__S{seed}",
                    "group": "4.3_one_factor_ablation",
                    "arm_id": arm_id,
                    "algorithm": algorithm,
                    "implementation": implementation,
                    "seed": seed,
                }
            )
    return specs


def _source_paths(bundle: Any) -> list[Path]:
    paths = sorted((SOLVER_SRC / "setp_solver").rglob("*.py"))
    paths.extend(
        [
            PROTOTYPE / "epochal_hgs.py",
            PROTOTYPE / "pyvrp_adapter.py",
            PROTOTYPE / "route_pool_sp.py",
            DISTANCE_ADAPTER,
            Path(__file__).resolve(),
            FLEET_AUTHORITY / "fleet_caps.csv",
            FLEET_AUTHORITY / "manifest.json",
            FLEET_AUTHORITY / "zero_search_certification.csv",
            FLEET_AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json",
            FLEET_EVIDENCE / "decision.json",
            FLEET_EVIDENCE / "metadata.json",
        ]
    )
    for value in bundle.source_paths.values():
        candidate = Path(str(value))
        if not candidate.is_absolute():
            candidate = REPO / candidate
        if candidate.is_file():
            paths.append(candidate.resolve())
    return sorted({path.resolve() for path in paths if path.is_file()})


def _hardware() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "hostname": platform.node(),
        "logical_cpu_count": os.cpu_count(),
        "python": sys.version,
        "python_executable": sys.executable,
        "max_parallel_workers": MAX_WORKERS,
        "native_thread_limits": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
    }


def prepare() -> None:
    metadata_path = OUT / "metadata.json"
    if metadata_path.exists():
        raise FileExistsError(
            "metadata already exists; preregistration is immutable"
        )
    with model_config_scope(MODEL_CONFIG):
        bundle = _bundle()
        common = _common_initial(bundle)
        completion = complete_china81_route_skeleton(common, bundle)
        physicalized, certificate = _physicalize_multitrip_solution(
            completion.solution,
            bundle,
        )
        objective, _, violations = exact_china81_score(physicalized, bundle)
    if violations:
        raise RuntimeError("fixed initial solution failed complete verification")
    if len(
        [node for node in bundle.instance.nodes if node.node_type.lower() == "c"]
    ) != 100:
        raise RuntimeError("selected instance does not have exactly 100 customers")
    if abs(float(bundle.prices.vehicle_fixed_cost) - 170.0) > 1e-9:
        raise RuntimeError("active fixed cost is not c_fix=170")
    if any(
        str(row.get("depot_charger_capacity_mode", "")).upper()
        not in {"", "UNBOUNDED"}
        for row in bundle.fleet_caps_by_depot.values()
    ):
        raise RuntimeError("fleet authority is not depot-unbounded")

    source_hashes = {
        _relative(path): _sha256_path(path) for path in _source_paths(bundle)
    }
    dirty = _git("status", "--porcelain=v1")
    initial_payload = {
        "solution": _solution_dict(physicalized),
        "multitrip_certificate": certificate.as_dict(),
        "objective_cny": objective,
    }
    initial_hash = _sha256_bytes(_json_bytes(initial_payload["solution"]))
    initial_skeleton_hash = _solution_semantic_sha256(common)
    metadata = {
        "schema_version": SCHEMA,
        "task_id": "XA",
        "metadata_status": "PREREGISTERED_BEFORE_FORMAL_SEARCH",
        "preregistration_locked": True,
        "created_at_utc": _utc_now(),
        "formal_search_started_at_metadata_creation": False,
        "git": {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "worktree_dirty": bool(dirty),
            "status_porcelain_sha256": _sha256_bytes(dirty.encode("utf-8")),
            "status_porcelain": dirty.splitlines(),
        },
        "source_sha256": source_hashes,
        "selected_instance": {
            "instance_id": INSTANCE_ID,
            "customer_count": 100,
            "fixed_before_search": True,
            "only_instance_run": True,
            "selection_reason": (
                "100 customers lies inside the preregistered 51--149 band; "
                "it is the central listed scale rather than a boundary case; "
                "its two-depot PRD structure is nontrivial; fleet authority v3 "
                "has zero-search CERTIFIED witnesses for all five EV shares."
            ),
            "authority_v3_certification_rows": (
                "baselines/china_e3_e7/fleet_authority_v3_20260802/"
                "raw_runs.csv rows for ev_share 0/25/50/75/100 are CERTIFIED"
            ),
            "active_depot_caps": {
                depot_id: dict(caps)
                for depot_id, caps in bundle.fleet_caps_by_depot.items()
            },
            "common_initial_solution_sha256": initial_hash,
            "common_initial_route_skeleton_sha256": initial_skeleton_hash,
            "common_initial_route_skeleton_source": (
                "fleet authority v3 zero-search witness, active 25-percent "
                "level; route groups and order only, re-completed and rechecked "
                "by the shared evaluator before use"
            ),
            "common_initial_objective_cny_preflight_only": objective,
        },
        "shared_model_contract": {
            **MODEL_CONFIG.as_metadata(),
            "multi_trip": "ON_EXPLICIT",
            "fixed_cost_cny": 170.0,
            "fixed_cost_billing_basis": "distinct physical vehicle ids",
            "model_change_registration": "MC-W1-F2-DEPOT-CONCURRENCY-01",
            "depot_charging_concurrency": "UNBOUNDED",
            "public_station_concurrency": "INSTANCE_FINITE",
            "fleet_authority_version": "fleet_authority_v3_20260802",
            "fleet_authority_runtime_path": _relative(FLEET_AUTHORITY),
            "fleet_authority_evidence_path": _relative(FLEET_EVIDENCE),
            "china81_total_fleet_authority": 943,
            "selected_instance_total_fleet_cap": sum(
                int(caps["total_fleet_cap"])
                for caps in bundle.fleet_caps_by_depot.values()
            ),
            "superseded_rule_forbidden": "num_ev=max(1,ceil(0.25R_d))",
        },
        "shared_protocol": {
            "same_batch": True,
            "same_machine": True,
            "same_initial_solution_per_seed_and_arm": True,
            "same_seed_set": list(SEEDS),
            "maximum_hgs_iterations_total_per_run": MAX_HGS_ITERATIONS,
            "no_improvement_limit_per_active_hgs_population": (
                MAX_NO_IMPROVEMENT
            ),
            "stopping_rule": (
                "Each active HGS population stops at the first of its "
                "preregistered iteration allocation, 150 consecutive proxy "
                "iterations without improvement, or a 7200-second technical "
                "safety cap. Multi-view allocations sum to 2000. A safety-cap "
                "trigger is a technical HALT, not a scientific result."
            ),
            "complete_search_evaluation_budget_max": (
                MAX_COMPLETE_SEARCH_EVALUATIONS
            ),
            "budget_counting_rule": (
                "Count each completed common decoder invocation presented to "
                "the search selection ledger. Post-search independent solution "
                "certification is recorded separately and cannot affect search."
            ),
            "single_view_budget": {
                "iterations": 2000,
                "checkpoint_interval": SINGLE_CHECKPOINT,
                "checkpoint_max": 80,
                "terminal_archive_max": SINGLE_ARCHIVE,
                "common_and_proxy": 2,
                "maximum_total": 100,
            },
            "multi_view_sp_budget": {
                "iterations_by_view": MV_ITERATIONS,
                "checkpoint_interval_by_view": MV_CHECKPOINTS,
                "checkpoint_max_total": 20,
                "terminal_archive_by_view": MV_SP_ARCHIVES,
                "common_and_proxy_total": 6,
                "route_pool_and_certificate": 2,
                "maximum_total": 100,
            },
            "single_view_sp_budget": {
                "iterations": 2000,
                "checkpoint_max": 80,
                "terminal_archive_max": SINGLE_SP_ARCHIVE,
                "common_and_proxy": 2,
                "route_pool_and_certificate": 2,
                "maximum_total": 100,
            },
            "multi_view_no_sp_budget": {
                "iterations_by_view": MV_ITERATIONS,
                "checkpoint_max_total": 20,
                "terminal_archive_by_view": MV_NO_SP_ARCHIVES,
                "common_and_proxy_total": 6,
                "maximum_total": 100,
            },
            "route_pool_mip_time_limit_seconds": SP_TIME_LIMIT_SECONDS,
            "route_pool_mip_role": (
                "search surrogate for customer exact cover; physical fleet "
                "assignment, fixed cost and final acceptance are exclusively "
                "decided by the shared complete evaluator"
            ),
            "adverse_results_policy": (
                "retain every terminal run; no rerun, seed replacement, rescue "
                "tuning, instance switching, or post-search parameter change"
            ),
        },
        "groups": {
            "4.2": {
                "runs": 50,
                "arms": [item[1] for item in GROUP1_ARMS],
                "table_fields": [
                    "algorithm",
                    "Best",
                    "Avg",
                    "Gap=100*(Avg-Best)/Best",
                    "actual HGS iterations",
                    "complete search evaluations",
                    "CPU minutes",
                    "feasible runs",
                ],
            },
            "4.3": {
                "runs": 30,
                "arms": [item[1] for item in GROUP2_ARMS],
                "one_factor_rule": (
                    "Only multi-view generation or timed MIP route-pool "
                    "recombination is removed; all shared settings stay fixed."
                ),
                "table_fields": [
                    "arm",
                    "Best",
                    "Avg",
                    "stability Gap=100*(Avg-Best)/Best",
                    "seed-paired mean cost difference from full arm in CNY",
                    "seed-paired mean percent difference from full arm",
                    "CPU minutes",
                ],
            },
        },
        "preregistered_falsification_criteria": {
            "group_4_2_cost_advantage": (
                "If MV-HGS-SP does not have a strictly lower 10-seed Avg than "
                "every comparator, the experiment does not support a cost-"
                "advantage claim on this instance."
            ),
            "group_4_2_stable_feasibility": (
                "If MV-HGS-SP yields fewer than 10 feasible terminal runs, the "
                "experiment does not support stable feasibility on this instance."
            ),
            "group_4_3_multiview_contribution": (
                "If the seed-paired mean cost difference HGS-M-SP minus full "
                "MV-HGS-SP is non-positive, this experiment does not support a "
                "positive multi-view contribution."
            ),
            "group_4_3_route_pool_contribution": (
                "If the seed-paired mean cost difference MV-HGS minus full "
                "MV-HGS-SP is non-positive, this experiment does not support a "
                "positive timed-MIP route-pool contribution."
            ),
            "protocol_validity": (
                "Any source drift, task omission, seed substitution, budget "
                "excess, safety-cap trigger, or failure to save and hash a full "
                "terminal solution causes technical HALT rather than a claim."
            ),
            "immutability": (
                "This entire preregistered_falsification_criteria object is "
                "written before formal search and must never be modified."
            ),
        },
        "literature_protocol_sources": [
            "陈婉茹等 (2023), p.3328 and p.3331 Table 8",
            "陈雨蝶等 (2025), pp.13--14 Table 6",
        ],
        "preflight_verification": {
            "targeted_algorithm_proxy_tests": "12 passed in 9.05s",
            "authoritative_full_command": (
                "PYTHONPATH=solver/src:models/src:.:/opt/anaconda3/lib/"
                "python3.13/site-packages:build/python_envs/"
                "pyvrp-hgs-0.12.2/lib/python3.13/site-packages "
                "PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest "
                "solver/tests -q --tb=short"
            ),
            "authoritative_full_result": (
                "3 failed, 909 passed, 1 skipped in 298.08s"
            ),
            "new_real_regressions": 0,
            "remaining_failures": [
                "solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables",
                "solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts",
                "solver/tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps",
            ],
            "selected_instance_complete_preflight_violation_count": 0,
        },
        "task_manifest": _task_specs(),
        "task_count": 80,
        "hardware": _hardware(),
    }
    _write_json_new(metadata_path, metadata)
    _write_json_new(OUT / "preflight_common_initial_solution.json", initial_payload)
    print(json.dumps({"status": "PREREGISTERED", "metadata": str(metadata_path)}))


def _verify_frozen_metadata() -> dict[str, Any]:
    metadata = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("metadata_status") != "PREREGISTERED_BEFORE_FORMAL_SEARCH":
        raise RuntimeError("metadata is not the frozen XA preregistration")
    if metadata.get("preregistration_locked") is not True:
        raise RuntimeError("metadata preregistration lock is absent")
    drift: list[str] = []
    for relative, expected in metadata["source_sha256"].items():
        path = REPO / relative
        actual = _sha256_path(path) if path.is_file() else "MISSING"
        if actual != expected:
            drift.append(f"{relative}: expected={expected} actual={actual}")
    if drift:
        raise RuntimeError("frozen source drift:\n" + "\n".join(drift))
    if metadata["task_manifest"] != _task_specs():
        raise RuntimeError("task manifest drift")
    return metadata


def _view_summary(epoch: Any, allocation: int) -> dict[str, Any]:
    actual = int(epoch.stats["hgs_iterations"])
    if bool(epoch.stats["wallclock_safety_triggered"]):
        stop = "WALLCLOCK_SAFETY"
    elif actual >= int(allocation):
        stop = "MAX_ITERATIONS"
    else:
        stop = "NO_IMPROVEMENT_150"
    return {
        "hgs_iterations": actual,
        "iteration_allocation": int(allocation),
        "no_improvement_limit": MAX_NO_IMPROVEMENT,
        "stop_reason": stop,
        "complete_search_evaluations": int(
            epoch.stats["complete_candidate_evaluation_attempts"]
        ),
        "wallclock_safety_triggered": bool(
            epoch.stats["wallclock_safety_triggered"]
        ),
    }


def _run_single(bundle: Any, common: Any, seed: int, mode: str) -> tuple[Any, dict[str, Any]]:
    if mode == "distance_only":
        problem = _load_distance_adapter().build_pyvrp_problem(
            bundle,
            route_proxy_mode="distance_only",
        )
    else:
        problem = build_pyvrp_problem(bundle, route_proxy_mode=mode)
    epoch = _run_exact_epoch(
        bundle,
        problem,
        common,
        seed=seed,
        runtime_seconds=None,
        warm_elites=(),
        exact_elite_count=8,
        max_archive_candidates=SINGLE_ARCHIVE,
        max_hgs_iterations=MAX_HGS_ITERATIONS,
        max_no_improvement_iterations=MAX_NO_IMPROVEMENT,
        wallclock_safety_seconds=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
        exact_checkpoint_interval_iterations=SINGLE_CHECKPOINT,
        collect_historical_population_archive=True,
    )
    candidates = [*epoch.elite_completions, epoch.proxy_best_completion]
    completion = min(candidates, key=lambda item: item.objective)
    view = {mode: _view_summary(epoch, MAX_HGS_ITERATIONS)}
    return completion, {
        "hgs_iterations": int(epoch.stats["hgs_iterations"]),
        "complete_search_evaluations": int(
            epoch.stats["complete_candidate_evaluation_attempts"]
        ),
        "safety_triggered": bool(epoch.stats["wallclock_safety_triggered"]),
        "per_view": view,
        "trace": epoch.stats,
        "sp": None,
    }


def _run_mv_sp(bundle: Any, common: Any, seed: int) -> tuple[Any, dict[str, Any]]:
    run = run_hgs_route_pool_recombination(
        bundle,
        common,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=8,
        max_archive_candidates_per_view=MV_SP_ARCHIVES,
        sp_time_limit_seconds=SP_TIME_LIMIT_SECONDS,
        max_hgs_iterations_per_view=MV_ITERATIONS,
        max_no_improvement_iterations_per_view=MV_NO_IMPROVEMENT,
        wallclock_safety_seconds_per_view=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
        exact_checkpoint_interval_iterations=MV_CHECKPOINTS,
        preserve_base_pool_recombination=False,
    )
    per_view = {
        mode: _view_summary(epoch, MV_ITERATIONS[mode])
        for mode, epoch in run.view_epochs.items()
    }
    return run.completion, {
        "hgs_iterations": sum(item["hgs_iterations"] for item in per_view.values()),
        "complete_search_evaluations": int(
            run.stats["complete_candidate_evaluation_attempts"]
        ),
        "safety_triggered": bool(run.stats["wallclock_safety_triggered"]),
        "per_view": per_view,
        "trace": run.stats,
        "sp": run.stats["route_pool_mip"],
    }


def _run_single_sp(bundle: Any, common: Any, seed: int) -> tuple[Any, dict[str, Any]]:
    mode = "mechanism_ev"
    problem = build_pyvrp_problem(bundle, route_proxy_mode=mode)
    epoch = _run_exact_epoch(
        bundle,
        problem,
        common,
        seed=seed,
        runtime_seconds=None,
        warm_elites=(),
        exact_elite_count=8,
        max_archive_candidates=SINGLE_SP_ARCHIVE,
        max_hgs_iterations=MAX_HGS_ITERATIONS,
        max_no_improvement_iterations=MAX_NO_IMPROVEMENT,
        wallclock_safety_seconds=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
        exact_checkpoint_interval_iterations=SINGLE_CHECKPOINT,
        collect_historical_population_archive=True,
    )
    parent = min(
        [*epoch.elite_completions, epoch.proxy_best_completion],
        key=lambda item: item.objective,
    )
    records = _route_pool_records(bundle, {mode: epoch})
    recombined, sp_stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=SP_TIME_LIMIT_SECONDS,
    )
    candidates = [parent]
    if recombined is not None:
        candidates.append(_accepted_mip_completion(recombined, bundle, sp_stats))
    completion = min(candidates, key=lambda item: item.objective)
    # The two fixed route-pool ledger entries are candidate-or-parent and the
    # final independent search certificate, matching the full arm accounting.
    exact_china81_score(completion.solution, bundle)
    per_view = {mode: _view_summary(epoch, MAX_HGS_ITERATIONS)}
    attempts = int(epoch.stats["complete_candidate_evaluation_attempts"]) + 2
    return completion, {
        "hgs_iterations": int(epoch.stats["hgs_iterations"]),
        "complete_search_evaluations": attempts,
        "safety_triggered": bool(epoch.stats["wallclock_safety_triggered"]),
        "per_view": per_view,
        "trace": {
            "view": epoch.stats,
            "route_pool_mip": sp_stats,
            "complete_candidate_evaluation_attempts": attempts,
        },
        "sp": sp_stats,
    }


def _run_mv_no_sp(bundle: Any, common: Any, seed: int) -> tuple[Any, dict[str, Any]]:
    epochs: dict[str, Any] = {}
    candidates: list[Any] = []
    for mode in MV_ITERATIONS:
        problem = build_pyvrp_problem(bundle, route_proxy_mode=mode)
        epoch = _run_exact_epoch(
            bundle,
            problem,
            common,
            seed=seed,
            runtime_seconds=None,
            warm_elites=(),
            exact_elite_count=8,
            max_archive_candidates=MV_NO_SP_ARCHIVES[mode],
            max_hgs_iterations=MV_ITERATIONS[mode],
            max_no_improvement_iterations=MAX_NO_IMPROVEMENT,
            wallclock_safety_seconds=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
            exact_checkpoint_interval_iterations=MV_CHECKPOINTS[mode],
            collect_historical_population_archive=True,
        )
        epochs[mode] = epoch
        candidates.extend(epoch.elite_completions)
        candidates.append(epoch.proxy_best_completion)
    completion = min(candidates, key=lambda item: item.objective)
    per_view = {
        mode: _view_summary(epoch, MV_ITERATIONS[mode])
        for mode, epoch in epochs.items()
    }
    return completion, {
        "hgs_iterations": sum(item["hgs_iterations"] for item in per_view.values()),
        "complete_search_evaluations": sum(
            int(epoch.stats["complete_candidate_evaluation_attempts"])
            for epoch in epochs.values()
        ),
        "safety_triggered": any(
            bool(epoch.stats["wallclock_safety_triggered"])
            for epoch in epochs.values()
        ),
        "per_view": per_view,
        "trace": {mode: epoch.stats for mode, epoch in epochs.items()},
        "sp": None,
    }


def _terminal_error_row(spec: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    return {
        "task_id": spec["task_id"],
        "group": spec["group"],
        "instance_id": INSTANCE_ID,
        "arm_id": spec["arm_id"],
        "algorithm": spec["algorithm"],
        "seed": spec["seed"],
        "terminal_status": "ERROR",
        "feasible": False,
        "objective_cny": "",
        "hgs_iterations_actual": "",
        "complete_search_evaluations_actual": "",
        "complete_search_evaluations_max": MAX_COMPLETE_SEARCH_EVALUATIONS,
        "post_search_certificate_evaluations": 0,
        "max_hgs_iterations": MAX_HGS_ITERATIONS,
        "max_no_improvement_iterations": MAX_NO_IMPROVEMENT,
        "stop_reason": "ERROR",
        "cpu_seconds": "",
        "cpu_minutes": "",
        "wall_seconds": "",
        "violation_count": "",
        "solution_path": "",
        "solution_sha256": "",
        "common_initial_solution_sha256": "",
        "route_count": "",
        "physical_vehicle_count": "",
        "sp_status": "",
        "sp_mip_gap": "",
        "per_view_json": "",
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }


def _run_unit(spec: dict[str, Any], expected_initial_hash: str) -> dict[str, Any]:
    unit_dir = OUT / "units" / spec["task_id"]
    result_path = unit_dir / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    unit_dir.mkdir(parents=True, exist_ok=True)
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    try:
        with model_config_scope(MODEL_CONFIG):
            bundle = _bundle()
            common = _common_initial(bundle)
            actual_initial_hash = _solution_semantic_sha256(common)
            frozen_metadata = json.loads(
                (OUT / "metadata.json").read_text(encoding="utf-8")
            )
            if actual_initial_hash != frozen_metadata["selected_instance"][
                "common_initial_route_skeleton_sha256"
            ]:
                raise RuntimeError("common initial route skeleton drift")
            # The preflight file stores the physicalized completed seed.  Use
            # the same canonical route skeleton check below for all tasks.
            preflight = json.loads(
                (OUT / "preflight_common_initial_solution.json").read_text(
                    encoding="utf-8"
                )
            )
            preregistered_initial_hash = _sha256_bytes(
                _json_bytes(preflight["solution"])
            )
            if preregistered_initial_hash != expected_initial_hash:
                raise RuntimeError("preflight common-initial artifact drift")
            if spec["implementation"] in {
                "distance_only",
                "cv_only",
                "naive_ev",
                "mechanism_ev",
            }:
                completion, run_stats = _run_single(
                    bundle,
                    common,
                    int(spec["seed"]),
                    str(spec["implementation"]),
                )
            elif spec["implementation"] == "mv_sp":
                completion, run_stats = _run_mv_sp(
                    bundle, common, int(spec["seed"])
                )
            elif spec["implementation"] == "single_sp":
                completion, run_stats = _run_single_sp(
                    bundle, common, int(spec["seed"])
                )
            elif spec["implementation"] == "mv_no_sp":
                completion, run_stats = _run_mv_no_sp(
                    bundle, common, int(spec["seed"])
                )
            else:
                raise ValueError(f"unknown implementation {spec['implementation']}")

            physicalized, certificate = _physicalize_multitrip_solution(
                completion.solution,
                bundle,
            )
            objective, breakdown, violations = exact_china81_score(
                physicalized,
                bundle,
            )
        solution_payload = {
            "schema_version": "resetp.xa-full-solution.v1",
            "task_id": spec["task_id"],
            "group": spec["group"],
            "arm_id": spec["arm_id"],
            "algorithm": spec["algorithm"],
            "seed": spec["seed"],
            "instance_id": INSTANCE_ID,
            "model_config": MODEL_CONFIG.as_metadata(),
            "objective_cny": objective,
            "breakdown": breakdown,
            "violations": [
                asdict(item) if is_dataclass(item) else str(item)
                for item in violations
            ],
            "multitrip_certificate": certificate.as_dict(),
            "solution": _solution_dict(physicalized),
        }
        solution_bytes = _json_bytes(solution_payload)
        solution_path = unit_dir / "solution.json"
        if solution_path.exists():
            raise FileExistsError("refusing to replace an existing unit solution")
        solution_path.write_bytes(solution_bytes)
        solution_sha = _sha256_bytes(solution_bytes)
        trace_path = unit_dir / "search_trace.json"
        _write_json_new(trace_path, run_stats["trace"])

        attempts = int(run_stats["complete_search_evaluations"])
        safety = bool(run_stats["safety_triggered"])
        budget_excess = attempts > MAX_COMPLETE_SEARCH_EVALUATIONS
        feasible = not violations
        if safety:
            terminal_status = "HALT_WALLCLOCK_SAFETY"
        elif budget_excess:
            terminal_status = "HALT_BUDGET_EXCESS"
        elif feasible:
            terminal_status = "PASS_FEASIBLE"
        else:
            terminal_status = "PASS_INFEASIBLE_ADVERSE"
        stop_reasons = sorted(
            {item["stop_reason"] for item in run_stats["per_view"].values()}
        )
        sp = run_stats.get("sp") or {}
        result = {
            "task_id": spec["task_id"],
            "group": spec["group"],
            "instance_id": INSTANCE_ID,
            "arm_id": spec["arm_id"],
            "algorithm": spec["algorithm"],
            "seed": spec["seed"],
            "terminal_status": terminal_status,
            "feasible": feasible,
            "objective_cny": float(objective),
            "hgs_iterations_actual": int(run_stats["hgs_iterations"]),
            "complete_search_evaluations_actual": attempts,
            "complete_search_evaluations_max": MAX_COMPLETE_SEARCH_EVALUATIONS,
            "post_search_certificate_evaluations": 1,
            "max_hgs_iterations": MAX_HGS_ITERATIONS,
            "max_no_improvement_iterations": MAX_NO_IMPROVEMENT,
            "stop_reason": "+".join(stop_reasons),
            "cpu_seconds": time.process_time() - cpu_started,
            "cpu_minutes": (time.process_time() - cpu_started) / 60.0,
            "wall_seconds": time.perf_counter() - wall_started,
            "violation_count": len(violations),
            "solution_path": _relative(solution_path),
            "solution_sha256": solution_sha,
            "common_initial_solution_sha256": expected_initial_hash,
            "worker_common_skeleton_sha256": actual_initial_hash,
            "route_count": len(physicalized.routes),
            "physical_vehicle_count": sum(certificate.vehicle_counts.values()),
            "sp_status": sp.get("status_class", ""),
            "sp_mip_gap": sp.get("mip_gap", ""),
            "per_view_json": json.dumps(
                run_stats["per_view"], ensure_ascii=False, sort_keys=True
            ),
            "error_type": "",
            "error_message": "",
            "search_trace_path": _relative(trace_path),
        }
    except BaseException as exc:
        error_payload = {
            "task": spec,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "created_at_utc": _utc_now(),
        }
        error_path = unit_dir / "error.json"
        if not error_path.exists():
            _write_json_new(error_path, error_payload)
        result = _terminal_error_row(spec, exc)
        result["wall_seconds"] = time.perf_counter() - wall_started
        result["cpu_seconds"] = time.process_time() - cpu_started
        result["cpu_minutes"] = float(result["cpu_seconds"]) / 60.0
        result["error_path"] = _relative(error_path)
    _write_json_new(result_path, result)
    return result


def _all_results() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in _task_specs():
        path = OUT / "units" / spec["task_id"] / "result.json"
        if path.is_file():
            results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def _materialize_raw() -> list[dict[str, Any]]:
    results = _all_results()
    path = OUT / "raw_runs.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({key: row.get(key, "") for key in RAW_FIELDS})
    return results


def _mean(values: list[float]) -> float:
    return float(statistics.fmean(values))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _summarise(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    group1: list[dict[str, Any]] = []
    for arm_id, algorithm, _ in GROUP1_ARMS:
        rows = [row for row in results if row["group"].startswith("4.2") and row["arm_id"] == arm_id]
        feasible = [row for row in rows if bool(row["feasible"])]
        costs = [float(row["objective_cny"]) for row in feasible]
        best = min(costs) if costs else None
        avg = _mean(costs) if costs else None
        group1.append(
            {
                "algorithm": algorithm,
                "Best_cny": best,
                "Avg_cny": avg,
                "Gap_percent": None if not costs else 100.0 * (avg - best) / best,
                "hgs_iterations_mean": _mean([float(row["hgs_iterations_actual"]) for row in rows]),
                "complete_search_evaluations_mean": _mean([float(row["complete_search_evaluations_actual"]) for row in rows]),
                "CPU_minutes_mean": _mean([float(row["cpu_minutes"]) for row in rows]),
                "CPU_minutes_total": sum(float(row["cpu_minutes"]) for row in rows),
                "feasible_runs": len(feasible),
                "terminal_runs": len(rows),
            }
        )
    full_by_seed = {
        int(row["seed"]): float(row["objective_cny"])
        for row in results
        if row["group"].startswith("4.3")
        and row["arm_id"] == "MV_HGS_SP_FULL"
        and bool(row["feasible"])
    }
    group2: list[dict[str, Any]] = []
    for arm_id, algorithm, _ in GROUP2_ARMS:
        rows = [row for row in results if row["group"].startswith("4.3") and row["arm_id"] == arm_id]
        feasible = [row for row in rows if bool(row["feasible"])]
        costs = [float(row["objective_cny"]) for row in feasible]
        best = min(costs) if costs else None
        avg = _mean(costs) if costs else None
        pairs = [
            (float(row["objective_cny"]), full_by_seed[int(row["seed"])])
            for row in feasible
            if int(row["seed"]) in full_by_seed
        ]
        paired_cny = _mean([left - right for left, right in pairs]) if pairs else None
        paired_pct = _mean([100.0 * (left - right) / right for left, right in pairs]) if pairs else None
        group2.append(
            {
                "algorithm_arm": algorithm,
                "Best_cny": best,
                "Avg_cny": avg,
                "stability_Gap_percent": None if not costs else 100.0 * (avg - best) / best,
                "paired_mean_cost_diff_vs_full_cny": paired_cny,
                "paired_mean_cost_diff_vs_full_percent": paired_pct,
                "paired_seed_count": len(pairs),
                "CPU_minutes_mean": _mean([float(row["cpu_minutes"]) for row in rows]),
                "CPU_minutes_total": sum(float(row["cpu_minutes"]) for row in rows),
                "feasible_runs": len(feasible),
                "terminal_runs": len(rows),
            }
        )
    return group1, group2


def _finalize(results: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    specs = _task_specs()
    expected_ids = {item["task_id"] for item in specs}
    actual_ids = {item["task_id"] for item in results}
    errors = [row for row in results if row["terminal_status"] == "ERROR"]
    halts = [row for row in results if str(row["terminal_status"]).startswith("HALT_")]
    missing = sorted(expected_ids - actual_ids)
    complete = not errors and not halts and not missing and len(results) == 80
    group1, group2 = _summarise(results) if not missing else ([], [])
    if group1:
        _write_csv(OUT / "table_4_2_five_algorithms.csv", list(group1[0]), group1)
        _write_csv(OUT / "table_4_3_component_ablation.csv", list(group2[0]), group2)

    claims: dict[str, Any] = {}
    if group1 and group2:
        mv = next(row for row in group1 if row["algorithm"] == "MV-HGS-SP")
        comparators = [row for row in group1 if row["algorithm"] != "MV-HGS-SP"]
        claims["group_4_2_cost_advantage_supported"] = bool(
            mv["Avg_cny"] is not None
            and all(
                row["Avg_cny"] is not None and mv["Avg_cny"] < row["Avg_cny"]
                for row in comparators
            )
        )
        claims["group_4_2_stable_feasibility_supported"] = mv["feasible_runs"] == 10
        no_mv = next(row for row in group2 if row["algorithm_arm"].startswith("HGS-M-SP"))
        no_sp = next(row for row in group2 if row["algorithm_arm"].startswith("MV-HGS ("))
        claims["group_4_3_multiview_contribution_supported"] = bool(
            no_mv["paired_mean_cost_diff_vs_full_cny"] is not None
            and no_mv["paired_mean_cost_diff_vs_full_cny"] > 0.0
        )
        claims["group_4_3_route_pool_contribution_supported"] = bool(
            no_sp["paired_mean_cost_diff_vs_full_cny"] is not None
            and no_sp["paired_mean_cost_diff_vs_full_cny"] > 0.0
        )
    status = "XA_ALGORITHM_FORMAL_COMPLETE" if complete else "HALT_XA_ALGORITHM_FORMAL_INCOMPLETE"
    decision = {
        "schema_version": SCHEMA,
        "task_id": "XA",
        "status": status,
        "technical_completion": complete,
        "terminal_run_count": len(results),
        "expected_run_count": 80,
        "missing_task_ids": missing,
        "error_task_ids": [row["task_id"] for row in errors],
        "halt_task_ids": [row["task_id"] for row in halts],
        "scientific_claim_assessment": claims,
        "preregistration_falsification_criteria_sha256": _sha256_bytes(
            _json_bytes(metadata["preregistered_falsification_criteria"])
        ),
        "adverse_results_retained": True,
        "created_at_utc": _utc_now(),
    }
    _write_json_replace(OUT / "decision.json", decision)

    report_lines = [
        "# XA 算法有效性正式实验",
        "",
        f"状态：`{status}`。",
        "",
        f"固定实例：`{INSTANCE_ID}`（100 客户）。本轮没有运行其他实例。",
        "",
        "共同合同：严格多趟开启；固定成本按实体车计费，c_fix=170 元；车场充电并发不设上限；fleet authority v3；每次总 HGS 迭代最多 2000，各活动种群连续 150 次无改善停止；完整搜索候选评价最多 100 次。",
        "",
        "## 4.2 五算法同协议比较",
        "",
    ]
    if group1:
        report_lines.extend(
            [
                "|算法|Best|Avg|Gap(%)|迭代均值|完整评价均值|CPU分钟均值|可行/10|",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in group1:
            report_lines.append(
                f"|{row['algorithm']}|{row['Best_cny']:.6f}|{row['Avg_cny']:.6f}|{row['Gap_percent']:.6f}|{row['hgs_iterations_mean']:.1f}|{row['complete_search_evaluations_mean']:.1f}|{row['CPU_minutes_mean']:.4f}|{row['feasible_runs']}/10|"
            )
    report_lines.extend(["", "## 4.3 一因素组件消融", ""])
    if group2:
        report_lines.extend(
            [
                "|算法臂|Best|Avg|稳定性Gap(%)|配对成本差(元)|配对差(%)|CPU分钟均值|可行/10|",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in group2:
            report_lines.append(
                f"|{row['algorithm_arm']}|{row['Best_cny']:.6f}|{row['Avg_cny']:.6f}|{row['stability_Gap_percent']:.6f}|{row['paired_mean_cost_diff_vs_full_cny']:.6f}|{row['paired_mean_cost_diff_vs_full_percent']:.6f}|{row['CPU_minutes_mean']:.4f}|{row['feasible_runs']}/10|"
            )
    report_lines.extend(
        [
            "",
            "## 判定边界",
            "",
            "科学主张是否获支持完全按 metadata 中跑前锁定的否定条件判定；不利结果保留，不触发重跑、换种子或调参。路线池 MIP 仅作覆盖组合代理，最终成本、实体车计费与可行性均以共享完整评价器和验解器为准。",
            "",
            "完整逐次结果见 `raw_runs.csv`，逐解文件和搜索轨迹见 `units/`，每个解的字节级 SHA-256 已写入逐次结果。",
        ]
    )
    (OUT / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    artifact_hashes: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(OUT)
        if path.name == "artifact_hashes.json":
            continue
        if path.name.startswith("._"):
            continue
        if "__pycache__" in relative.parts or ".pytest_cache" in relative.parts:
            continue
        if ".experiment-monitor" in relative.parts:
            continue
        artifact_hashes[str(relative)] = _sha256_path(path)
    _write_json_replace(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                ".experiment-monitor",
            ],
            "artifacts": artifact_hashes,
        },
    )
    _write_json_replace(
        OUT / "done.json",
        {
            "status": status,
            "terminal_run_count": len(results),
            "completed_at_utc": _utc_now(),
        },
    )


def run() -> None:
    metadata = _verify_frozen_metadata()
    if (OUT / "done.json").exists():
        raise FileExistsError("formal experiment already has a terminal done.json")
    expected_hash = metadata["selected_instance"]["common_initial_solution_sha256"]
    completed = {row["task_id"] for row in _all_results()}
    pending = [spec for spec in _task_specs() if spec["task_id"] not in completed]
    _materialize_raw()
    try:
        os.sysconf("SC_SEM_NSEMS_MAX")
    except PermissionError:
        # The managed macOS sandbox denies this read-only sysconf query even
        # though multiprocessing semaphores are available (verified in the XA
        # startup audit for both spawn and fork contexts).  Bypass only the
        # standard-library preflight probe; semaphore construction and all
        # ProcessPoolExecutor behaviour remain unchanged.
        futures_process._check_system_limits = lambda: None
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=MAX_WORKERS, mp_context=context) as pool:
        futures = {
            pool.submit(_run_unit, spec, expected_hash): spec for spec in pending
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
                print(
                    json.dumps(
                        {
                            "task_id": spec["task_id"],
                            "terminal_status": result["terminal_status"],
                            "objective_cny": result.get("objective_cny"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except BaseException as exc:
                print(
                    json.dumps(
                        {
                            "task_id": spec["task_id"],
                            "executor_error": type(exc).__name__,
                            "message": str(exc),
                        }
                    ),
                    flush=True,
                )
            _materialize_raw()
    results = _materialize_raw()
    _finalize(results, metadata)
    print(json.dumps(json.loads((OUT / "done.json").read_text(encoding="utf-8"))))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "run"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        run()


if __name__ == "__main__":
    main()
