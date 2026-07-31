#!/usr/bin/env python3
"""Low-cost ZONE / JOINT / POOLED probe (E3 fleet-pooling direction check).

This script is NEW code written for the e3_pooling_probe_20260731 task. It
does not modify, and is not part of, the frozen e3_zone_joint_20260731
experiment or its runner. It reuses that experiment's already-verified,
UNMODIFIED input artifacts (responsibility maps + common initial solutions
for cn-prd-50c-01-V2-LOCATIONS, read-only) and the same unmodified solver
stack (setp_solver.check / setp_solver.cost / setp_solver.china81 /
setp_solver.china81_completion), reading them directly from their real
repository locations. It never writes to those locations.

The only intentionally modified source is a local, isolated copy of
route_pool_sp.py (isolated_copy/prototype/route_pool_sp.py), which adds one
new keyword-only parameter `pool_fleet` to `_solve_set_partitioning`. When
True, the set-partitioning MIP drops its per-depot vehicle-count
LinearConstraint and keeps only the existing global cross-depot cv/ev total
constraint that was already present in the frozen baseline
(bundle.instance.num_cv / num_ev). pyvrp_adapter.py is untouched (byte
identical to the frozen baseline; verified by freeze_manifest.json).

Three arms per seed:
  ZONE   -- hard_home_depot_lock=True,  pool_fleet=False (frozen baseline)
  JOINT  -- hard_home_depot_lock=False, pool_fleet=False (frozen baseline)
  POOLED -- hard_home_depot_lock=False, pool_fleet=True  (new, isolated-only)

Seeds 1-3, instance cn-prd-50c-01-V2-LOCATIONS only, budget cap=400 (same
cap already used by the sealed ZONE/JOINT formal run for comparability).
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
PROBE_DIR = HERE.parent
REPO = PROBE_DIR.parents[2]

PROTOTYPE_PATCHED = HERE / "prototype"
E3_MISMATCH_SOURCE = (
    REPO / "baselines/china_e3_e7/e3_mismatch_20260729/run_e3_mismatch.py"
)
FROZEN_INPUTS_ROOT = (
    REPO
    / "baselines/china_e3_e7/e3_zone_joint_20260731/inputs/"
    "cn-prd-50c-01-V2-LOCATIONS"
)

INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
SEEDS = (1, 2, 3)
ARMS = ("ZONE", "JOINT", "POOLED")
CAP = 400
EXACT_ELITES_PER_VIEW = 8
MAX_HGS_ITERATIONS_PER_VIEW = 5_000
MIP_TIME_LIMIT_SECONDS = 5.0
MAX_WORKERS = 1

REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

RAW_DIR = PROBE_DIR / "raw_units"


def archive_limits(cap: int) -> dict[str, int]:
    """Verbatim logic of run_e3_zone_joint.py's archive_limits (re-derived
    here, not imported, since this is new code, not a modification)."""
    remaining = int(cap) - EXACT_ELITES_PER_VIEW
    if remaining < 3 * EXACT_ELITES_PER_VIEW:
        raise ValueError(f"complete-candidate cap is too small: {cap}")
    base, remainder = divmod(remaining, 3)
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    result = {
        mode: base + (1 if index < remainder else 0)
        for index, mode in enumerate(modes)
    }
    if sum(result.values()) + EXACT_ELITES_PER_VIEW != int(cap):
        raise RuntimeError("archive-cap mapping does not close")
    return result


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _prepare_isolated_modules() -> tuple[ModuleType, ModuleType]:
    """Pre-populate sys.modules with the isolated, patched prototype under
    the SAME bare names ('epochal_hgs', 'pyvrp_adapter', 'route_pool_sp')
    that run_e3_mismatch.py imports at its own module top-level, BEFORE
    that (unmodified, original) module is loaded. Because Python checks
    sys.modules by name before touching sys.path, run_e3_mismatch.py's own
    `from route_pool_sp import ...` etc. will bind to these isolated,
    patched copies instead of the frozen originals -- without editing
    run_e3_mismatch.py or inserting the isolated dir ahead of the frozen
    prototype dir on sys.path (run_e3_mismatch.py inserts its own frozen
    PROTOTYPE path at sys.path[0] unconditionally; the sys.modules cache
    is what actually wins here, not path order).
    """
    for repo_path in (REPO / "solver/src", REPO):
        if str(repo_path) not in sys.path:
            sys.path.insert(0, str(repo_path))
    pyvrp_adapter = _load_module_from_path(
        "pyvrp_adapter", PROTOTYPE_PATCHED / "pyvrp_adapter.py"
    )
    epochal_hgs = _load_module_from_path(
        "epochal_hgs", PROTOTYPE_PATCHED / "epochal_hgs.py"
    )
    route_pool_sp = _load_module_from_path(
        "route_pool_sp", PROTOTYPE_PATCHED / "route_pool_sp.py"
    )
    return route_pool_sp, epochal_hgs, pyvrp_adapter


def sha256_of_json(payload: Any) -> str:
    import hashlib

    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_input(arm: str) -> tuple[dict[str, str], dict[str, Any]]:
    """Read-only load of the already-sealed ZONE/JOINT input artifacts.
    POOLED reuses the JOINT artifacts verbatim (same customer mapping,
    same common initial solution; only the fleet-pool switch differs)."""
    source_arm = "ZONE" if arm == "ZONE" else "JOINT"
    folder = FROZEN_INPUTS_ROOT / source_arm
    responsibility = json.loads(
        (folder / "responsibility_map.json").read_text(encoding="utf-8")
    )
    initial_payload = json.loads(
        (folder / "initial_solution.json").read_text(encoding="utf-8")
    )
    certificate = json.loads(
        (folder / "input_certificate.json").read_text(encoding="utf-8")
    )
    if sha256_of_json(responsibility) != certificate["responsibility_sha256"]:
        raise RuntimeError(f"HALT_RESPONSIBILITY_HASH_DRIFT:{arm}")
    if sha256_of_json(initial_payload) != certificate["initial_solution_sha256"]:
        raise RuntimeError(f"HALT_INITIAL_HASH_DRIFT:{arm}")
    return responsibility["mapping"], initial_payload


def run_unit(arm: str, seed: int) -> dict[str, Any]:
    for name, value in REQUIRED_THREAD_ENV.items():
        os.environ[name] = value

    route_pool_sp, _epochal_hgs, _pyvrp_adapter = _prepare_isolated_modules()
    e3_mismatch = _load_module_from_path(
        f"_pooling_probe_e3_mismatch_source_{os.getpid()}",
        E3_MISMATCH_SOURCE,
    )

    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate

    mapping, initial_payload = load_input(arm)
    base = e3_mismatch.load_bundle(INSTANCE_ID)
    bundle = e3_mismatch.with_responsibility(base, mapping)
    initial = e3_mismatch.solution_from_payload(initial_payload)

    hard_lock = arm == "ZONE"
    pool_fleet = arm == "POOLED"
    archives = archive_limits(CAP)
    safety_seconds = max(600.0, 4.0 * len(bundle.customer_home_depot))

    started = time.perf_counter()
    run = route_pool_sp.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=int(seed),
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=archives,
        sp_time_limit_seconds=MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=hard_lock,
        max_hgs_iterations_per_view=MAX_HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=safety_seconds,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
        pool_fleet=pool_fleet,
    )
    elapsed = time.perf_counter() - started

    solution = run.solution
    independent_violations = check_solution(
        solution, bundle.instance, bundle.prices
    )
    independent = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if not math.isclose(
        float(independent["total_cost"]),
        float(run.completion.objective),
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        raise RuntimeError(
            f"HALT_OBJECTIVE_MISMATCH:{arm}:seed{seed}:"
            f"independent={independent['total_cost']!r} "
            f"mip_layer={run.completion.objective!r}"
        )

    consumed = int(run.stats["complete_candidate_evaluation_attempts"])
    if consumed > CAP:
        raise RuntimeError(f"HALT_BUDGET_CAP_EXCEEDED:{arm}:seed{seed}:{consumed}>{CAP}")

    depot_route_counts: dict[str, dict[str, int]] = {}
    for route in solution.routes:
        by_depot = depot_route_counts.setdefault(
            route.home_depot_id, {"cv": 0, "ev": 0}
        )
        by_depot[route.vehicle_type.lower()] += 1

    result = {
        "arm": arm,
        "seed": int(seed),
        "instance_id": INSTANCE_ID,
        "hard_home_depot_lock": hard_lock,
        "pool_fleet": pool_fleet,
        "cap": CAP,
        "complete_candidate_evaluations_consumed": consumed,
        "elapsed_wall_seconds": elapsed,
        "wallclock_safety_triggered": bool(
            run.stats.get("wallclock_safety_triggered")
        ),
        "independent_violation_count": len(independent_violations),
        "independent_violations": [
            {
                "type": v.type,
                "vehicle_id": v.vehicle_id,
                "location": v.location,
                "detail": v.detail,
            }
            for v in independent_violations
        ],
        "cross_site_service_count": len(solution.cross_site_services),
        "total_cost": float(independent["total_cost"]),
        "distance_total_m": float(independent["distance_total"]),
        "E_total_kg": float(independent["E_total"]),
        "n_veh_cv": int(independent["n_veh_cv"]),
        "n_veh_ev": int(independent["n_veh_ev"]),
        "n_veh_total": int(independent["n_veh_cv"]) + int(independent["n_veh_ev"]),
        "depot_route_counts": depot_route_counts,
        "depot_fleet_caps_by_depot": {
            depot_id: dict(caps)
            for depot_id, caps in bundle.fleet_caps_by_depot.items()
        },
        "instance_num_cv": int(bundle.instance.num_cv),
        "instance_num_ev": int(bundle.instance.num_ev),
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{INSTANCE_ID}__seed{seed:02d}__{arm}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _run_unit_entry(args: tuple[str, int]) -> dict[str, Any]:
    arm, seed = args
    return run_unit(arm, seed)


def main() -> int:
    units = [(arm, seed) for arm in ARMS for seed in SEEDS]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_run_unit_entry, unit): unit for unit in units
        }
        for future in as_completed(futures):
            unit = futures[future]
            result = future.result()
            results.append(result)
            print(
                f"DONE arm={result['arm']} seed={result['seed']} "
                f"cost={result['total_cost']:.3f} "
                f"veh={result['n_veh_total']} "
                f"consumed={result['complete_candidate_evaluations_consumed']}"
            )
    results.sort(key=lambda r: (r["arm"], r["seed"]))
    (PROBE_DIR / "probe_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
