#!/usr/bin/env python3
"""Nine-instance feasibility gate for the approved China81 vehicle pair."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import resource
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import median
from time import perf_counter, process_time
from typing import Any

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAMPAIGN = REPO / "baselines/e2_final_campaign_20260720"
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
PYVRP_SITE = REPO / "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages"
for path in reversed((PYVRP_SITE, PROTOTYPE, CAMPAIGN, REPO / "solver/src")):
    while str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))

import epochal_hgs  # noqa: E402
import route_pool_sp  # noqa: E402
import run_corrected_china81_d6 as corrected  # noqa: E402
from pyvrp.stop import NoImprovement  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import evaluate  # noqa: E402

K = 3_000
WORKERS = 6
SEED = 1
SP_SECONDS = 5.0
EXACT_ELITES = 8
ARCHIVE_CANDIDATES = 24
HISTORICAL_EV_CUSTOMER_BASELINE = 0.078
INSTANCES = (
    ("cn-jjj-25c-01-V2-LOCATIONS", "jjj", "small", 25),
    ("cn-jjj-100c-01-V2-LOCATIONS", "jjj", "medium", 100),
    ("cn-jjj-200c-01-V2-LOCATIONS", "jjj", "large", 200),
    ("cn-prd-25c-01-V2-LOCATIONS", "prd", "small", 25),
    ("cn-prd-100c-01-V2-LOCATIONS", "prd", "medium", 100),
    ("cn-prd-200c-01-V2-LOCATIONS", "prd", "large", 200),
    ("cn-cy-25c-01-V2-LOCATIONS", "cy", "small", 25),
    ("cn-cy-100c-01-V2-LOCATIONS", "cy", "medium", 100),
    ("cn-cy-200c-01-V2-LOCATIONS", "cy", "large", 200),
)
REQUIRED_ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)
CONTRACT_FILES = (
    REPO / "solver/src/setp_solver/china81.py",
    REPO / "solver/src/setp_solver/prices.py",
    REPO / "docs/handoff/model_change_approval_register_20260718.md",
)
RAW_FIELDS = (
    "instance_id", "region", "size_layer", "customer_count", "seed",
    "status", "feasible_rate", "final_cost", "violation_count",
    "battery_violation_count", "time_window_violation_count",
    "capacity_violation_count", "fleet_violation_count",
    "other_violation_count", "ev_customer_count", "served_customer_count",
    "ev_customer_share", "ev_route_count", "route_count", "ev_route_share",
    "charging_action_count", "cpu_seconds", "wallclock_seconds",
    "peak_rss_mib", "pid", "start_method", "selected_source",
    "view_stop_iterations_json", "view_last_improvements_json",
    "view_l_over_s_json", "price_binding_json", "witness_path",
    "witness_sha256", "error_type", "error_message",
)


def _canonical(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical(payload))
    temporary.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


class AuditedNoImprovement:
    def __init__(self, maximum: int):
        self.maximum = int(maximum)
        self._criterion = NoImprovement(self.maximum)
        self._best: float | None = None
        self._observations: list[dict[str, Any]] = []

    def __call__(self, best_cost: float) -> bool:
        value = float(best_cost)
        strict = self._best is None or value < self._best
        if strict:
            self._best = value
        stopped = bool(self._criterion(value))
        self._observations.append(
            {
                "iteration": len(self._observations),
                "best_proxy_cost": value,
                "strict_improvement": strict,
                "stop_triggered": stopped,
            }
        )
        return stopped

    @property
    def stop_iterations(self) -> int:
        return int(self._observations[-1]["iteration"])

    @property
    def last_improvement(self) -> int:
        return max(
            int(row["iteration"])
            for row in self._observations
            if row["strict_improvement"]
        )


def _patch_stop(criteria: list[AuditedNoImprovement]) -> tuple[Any, Any]:
    old = (epochal_hgs.MaxIterations, epochal_hgs.MultipleCriteria)

    def make(_ignored: int) -> AuditedNoImprovement:
        criterion = AuditedNoImprovement(K)
        criteria.append(criterion)
        return criterion

    epochal_hgs.MaxIterations = make
    epochal_hgs.MultipleCriteria = lambda items: items[0]
    return old


def _restore_stop(old: tuple[Any, Any]) -> None:
    epochal_hgs.MaxIterations, epochal_hgs.MultipleCriteria = old


def _peak_rss_mib() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024.0 * 1024.0) if sys.platform == "darwin" else raw / 1024.0


def _violation_counts(violations: list[Any]) -> dict[str, int]:
    counts = {
        "battery_violation_count": 0,
        "time_window_violation_count": 0,
        "capacity_violation_count": 0,
        "fleet_violation_count": 0,
        "other_violation_count": 0,
    }
    mapping = {
        "BATTERY": "battery_violation_count",
        "TIME_WINDOW": "time_window_violation_count",
        "CAPACITY": "capacity_violation_count",
        "FLEET_SIZE": "fleet_violation_count",
    }
    for violation in violations:
        key = mapping.get(str(violation.type), "other_violation_count")
        counts[key] += 1
    return counts


def _blank_row(spec: tuple[str, str, str, int]) -> dict[str, Any]:
    instance_id, region, size_layer, customer_count = spec
    return {
        "instance_id": instance_id,
        "region": region,
        "size_layer": size_layer,
        "customer_count": customer_count,
        "seed": SEED,
        **{field: "" for field in RAW_FIELDS[5:]},
    }


def _run_unit(spec: tuple[str, str, str, int]) -> dict[str, Any]:
    row = _blank_row(spec)
    instance_id = spec[0]
    task_dir = HERE / "tasks" / instance_id
    result_path = task_dir / "result.json"
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    started_wall = perf_counter()
    started_cpu = process_time()
    try:
        if any(os.environ.get(key) != value for key, value in REQUIRED_ENV.items()):
            raise RuntimeError("deterministic thread environment mismatch")
        if version("pyvrp") != "0.12.2":
            raise RuntimeError("PyVRP 0.12.2 is required")
        bundle = load_china81_bundle(REPO, instance_id)
        ev = bundle.instance.vehicle_parameters["ev"]
        if (
            ev.vehicle_type_id != "FOTON-AUMARK-ES1-EXPRESS-STAKE"
            or not math.isclose(ev.payload_capacity_kg, 1_700.0)
            or not math.isclose(ev.battery_kwh or 0.0, 77.28)
            or not math.isclose(ev.frontal_area_m2, 0.85 * 2.2 * 2.48)
        ):
            raise RuntimeError("approved EV contract is not active")
        initial = corrected._load_initial(instance_id)
        criteria: list[AuditedNoImprovement] = []
        old = _patch_stop(criteria)
        try:
            run = route_pool_sp.run_hgs_route_pool_recombination(
                bundle,
                initial,
                seed=SEED,
                hgs_seconds_per_view=None,
                exact_elites_per_view=EXACT_ELITES,
                max_archive_candidates_per_view=ARCHIVE_CANDIDATES,
                sp_time_limit_seconds=SP_SECONDS,
                hard_home_depot_lock=False,
                max_hgs_iterations_per_view=K,
                wallclock_safety_seconds_per_view=1.0,
            )
        finally:
            _restore_stop(old)
        if len(criteria) != 3:
            raise RuntimeError("MV preflight did not run three independent views")
        solution = annotate_cross_site_services(
            run.solution, bundle.customer_home_depot
        )
        objective, breakdown, violations = exact_china81_score(solution, bundle)
        independent_violations = check_solution(
            solution, bundle.instance, bundle.prices
        )
        independent_breakdown = evaluate(
            solution, bundle.instance, bundle.time_profile, bundle.prices
        )
        if independent_violations != violations:
            raise RuntimeError("independent checker disagrees with exact scorer")
        if not math.isclose(
            float(independent_breakdown["total_cost"]),
            float(objective),
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise RuntimeError("independent evaluator disagrees with exact scorer")
        customers = {
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type == "c"
        }
        ev_customers = {
            node_id
            for route in solution.routes
            if str(route.vehicle_type).lower() == "ev"
            for node_id in route.node_sequence[1:-1]
            if node_id in customers
        }
        served = {
            node_id
            for route in solution.routes
            for node_id in route.node_sequence[1:-1]
            if node_id in customers
        }
        ev_routes = sum(
            str(route.vehicle_type).lower() == "ev" for route in solution.routes
        )
        view_names = ("cv_only", "naive_ev", "mechanism_ev")
        stop_iterations = {
            name: criterion.stop_iterations
            for name, criterion in zip(view_names, criteria)
        }
        last_improvements = {
            name: criterion.last_improvement
            for name, criterion in zip(view_names, criteria)
        }
        l_over_s = {
            name: last_improvements[name] / stop_iterations[name]
            for name in view_names
        }
        witness_path = task_dir / "solution_witness.json"
        _write_json(
            witness_path,
            {
                "schema": "resetp.e2-rerun-unified-01.vehicle-preflight.witness.v1",
                "instance_id": instance_id,
                "seed": SEED,
                "solution": corrected._solution_payload(solution),
                "objective": objective,
                "breakdown": breakdown,
                "violations": [vars(item) for item in violations],
                "independent_check": {
                    "violation_count": len(independent_violations),
                    "objective": float(independent_breakdown["total_cost"]),
                },
            },
        )
        row.update(
            {
                "status": "PASS" if not violations else "INFEASIBLE",
                "feasible_rate": 1.0 if not violations else 0.0,
                "final_cost": objective,
                "violation_count": len(violations),
                **_violation_counts(violations),
                "ev_customer_count": len(ev_customers),
                "served_customer_count": len(served),
                "ev_customer_share": len(ev_customers) / len(served) if served else 0.0,
                "ev_route_count": ev_routes,
                "route_count": len(solution.routes),
                "ev_route_share": ev_routes / len(solution.routes) if solution.routes else 0.0,
                "charging_action_count": len(solution.charging_actions),
                "selected_source": str(run.stats["selected_source"]),
                "view_stop_iterations_json": json.dumps(stop_iterations, sort_keys=True),
                "view_last_improvements_json": json.dumps(last_improvements, sort_keys=True),
                "view_l_over_s_json": json.dumps(l_over_s, sort_keys=True),
                "price_binding_json": json.dumps(
                    dict(bundle.prices.diesel_price_by_city), sort_keys=True
                ),
                "witness_path": str(witness_path.relative_to(REPO)),
                "witness_sha256": _sha256(witness_path),
            }
        )
    except Exception as exc:
        row.update(
            {
                "status": "ERROR",
                "feasible_rate": 0.0,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        _write_json(
            task_dir / "error.json",
            {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
    row.update(
        {
            "cpu_seconds": process_time() - started_cpu,
            "wallclock_seconds": perf_counter() - started_wall,
            "peak_rss_mib": _peak_rss_mib(),
            "pid": os.getpid(),
            "start_method": mp.get_start_method(),
        }
    )
    _write_json(result_path, row)
    return row


HASH_EXCLUSION_RULES = (
    "artifact_hashes.json",
    "._*",
    ".DS_Store",
    "*.tmp",
    "*.temp",
    "*.lock",
    "*.checkpoint",
    "*.checkpoint.*",
    "checkpoint*",
    "__pycache__/",
    ".pytest_cache/",
    ".monitor/",
    "*.monitor/",
    ".experiment.monitor/",
    "monitor.json",
    "progress.json",
)


def _hash_exclusion_reason(path: Path) -> str | None:
    relative = path.relative_to(HERE)
    parts = relative.parts
    if path.name == "artifact_hashes.json":
        return "self"
    if any(part.startswith("._") for part in parts):
        return "AppleDouble"
    if any(part in {"__pycache__", ".pytest_cache"} for part in parts):
        return "cache"
    if any(
        part == ".monitor"
        or part == ".experiment.monitor"
        or part.endswith(".monitor")
        for part in parts
    ):
        return "monitoring state"
    if path.name in {".DS_Store", "monitor.json", "progress.json"}:
        return "non-paper runtime state"
    if any(
        fnmatch.fnmatch(path.name, pattern)
        for pattern in ("*.tmp", "*.temp", "*.lock", "*.checkpoint", "*.checkpoint.*", "checkpoint*")
    ):
        return "temporary checkpoint"
    return None


def _evidence_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and _hash_exclusion_reason(path) is None:
            result[str(path.relative_to(REPO))] = _sha256(path)
    return result


def _rehash_only() -> None:
    manifest_path = HERE / "artifact_hashes.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    _write_json(
        manifest_path,
        {
            "schema": "resetp.e2-rerun-unified-01.vehicle-preflight.hashes.v2",
            "algorithm": "sha256",
            "self_excluded": True,
            "scope": str(HERE.relative_to(REPO)),
            "exclusions": list(HASH_EXCLUSION_RULES),
            "files": _evidence_hashes(),
            "frozen_hashes_after": previous["frozen_hashes_after"],
            "frozen_hashes_preserved_from_preflight": True,
        },
    )


def _finalize(rows: list[dict[str, Any]], frozen_hashes: dict[str, str]) -> None:
    rows.sort(key=lambda row: row["instance_id"])
    _write_csv(HERE / "raw_runs.csv", rows)
    all_feasible = all(row["status"] == "PASS" for row in rows)
    shares = [float(row["ev_customer_share"] or 0.0) for row in rows]
    median_share = median(shares)
    improved = median_share > HISTORICAL_EV_CUSTOMER_BASELINE
    passed = all_feasible and improved
    verdict = (
        "PASS_NEW_VEHICLE_PAIR_FEASIBILITY_PREFLIGHT"
        if passed
        else "HALT_NEW_VEHICLE_PAIR_INFEASIBLE"
    )
    decision = {
        "schema": "resetp.e2-rerun-unified-01.vehicle-preflight.decision.v1",
        "task_id": "E2-RERUN-UNIFIED-01",
        "verdict": verdict,
        "planned_and_actual_units": [len(INSTANCES), len(rows)],
        "all_nine_complete_feasible": all_feasible,
        "ev_customer_share_median": median_share,
        "historical_baseline": HISTORICAL_EV_CUSTOMER_BASELINE,
        "strictly_above_historical_baseline": improved,
        "step2_authorized_by_gate": passed,
        "protected_files_modified": [],
    }
    _write_json(HERE / "decision.json", decision)
    _write_json(
        HERE / "metadata.json",
        {
            "schema": "resetp.e2-rerun-unified-01.vehicle-preflight.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.executable,
            "python_version": sys.version,
            "platform": platform.platform(),
            "pyvrp_version": version("pyvrp"),
            "workers": WORKERS,
            "start_method": "spawn",
            "seed": SEED,
            "instances": [item[0] for item in INSTANCES],
            "algorithm": "MV-HGS-SP single feasibility round",
            "stop_rule": "each of three views independently uses NoImprovement(3000)",
            "vehicle_contract": {
                "ev_vehicle_type_id": "FOTON-AUMARK-ES1-EXPRESS-STAKE",
                "payload_capacity_kg": 1700.0,
                "curb_mass_kg": 2600.0,
                "gross_mass_kg": 4495.0,
                "battery_kwh": 77.28,
                "frontal_area_m2": 0.85 * 2.2 * 2.48,
                "height_assumption": "HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE",
                "height_sensitivity_m": [2.48, 3.05, 3.25],
            },
            "frozen_hashes_before": frozen_hashes,
        },
    )
    table = [
        "| 算例 | 可行率 | EV客户占比 | EV路线占比 | 充电动作 | 电量/时窗/容量/车队违约 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        table.append(
            f"| {row['instance_id']} | {float(row['feasible_rate']):.0%} | "
            f"{float(row['ev_customer_share'] or 0.0):.2%} | "
            f"{float(row['ev_route_share'] or 0.0):.2%} | "
            f"{int(row['charging_action_count'] or 0)} | "
            f"{int(row['battery_violation_count'] or 0)}/"
            f"{int(row['time_window_violation_count'] or 0)}/"
            f"{int(row['capacity_violation_count'] or 0)}/"
            f"{int(row['fleet_violation_count'] or 0)} |"
        )
    (HERE / "report.md").write_text(
        "\n".join(
            [
                "# E2-RERUN-UNIFIED-01 新车型可行性预检",
                "",
                f"裁决：`{verdict}`。九题完整可行={all_feasible}；EV 承担客户比例中位数 "
                f"{median_share:.2%}，历史基线 {HISTORICAL_EV_CUSTOMER_BASELINE:.1%}。",
                "",
                *table,
                "",
                "每题由三个视角各自独立跑到 NoImprovement(3000)，再经限时 MIP 路线池重组与 min() 安全网。",
                "最终 witness 同时由 exact_china81_score 和直接 check_solution/evaluate 路径复核；失败行不删除。",
                "本门只判断新车型对是否可进入正式统一批，不作五臂胜负或等算力主张。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    current_hashes = {
        str(path.relative_to(REPO)): _sha256(path)
        for path in (*PROTECTED, *CONTRACT_FILES)
    }
    if current_hashes != frozen_hashes:
        raise RuntimeError("protected or experiment-contract file drift")
    _write_json(
        HERE / "artifact_hashes.json",
        {
            "schema": "resetp.e2-rerun-unified-01.vehicle-preflight.hashes.v1",
            "algorithm": "sha256",
            "self_excluded": True,
            "exclusions": list(HASH_EXCLUSION_RULES),
            "files": _evidence_hashes(),
            "frozen_hashes_after": current_hashes,
        },
    )
    _write_json(
        HERE / "done.json",
        {
            "status": "COMPLETED",
            "verdict": verdict,
            "units": len(rows),
            "created_at_utc": datetime.now(UTC).isoformat(),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rehash-only",
        action="store_true",
        help="single-process stable manifest rebuild; does not run the feasibility preflight",
    )
    args = parser.parse_args()
    if args.rehash_only:
        _rehash_only()
        return
    frozen_hashes = {
        str(path.relative_to(REPO)): _sha256(path)
        for path in (*PROTECTED, *CONTRACT_FILES)
    }
    existing: list[dict[str, Any]] = []
    for spec in INSTANCES:
        path = HERE / "tasks" / spec[0] / "result.json"
        if path.is_file():
            existing.append(json.loads(path.read_text(encoding="utf-8")))
    completed = {row["instance_id"] for row in existing}
    pending = [spec for spec in INSTANCES if spec[0] not in completed]
    rows = list(existing)
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=WORKERS,
        mp_context=context,
        max_tasks_per_child=1,
    ) as pool:
        futures = {pool.submit(_run_unit, spec): spec for spec in pending}
        for future in as_completed(futures):
            rows.append(future.result())
            _write_csv(HERE / "raw_runs.csv", sorted(rows, key=lambda row: row["instance_id"]))
            _write_json(
                HERE / "progress.json",
                {
                    "completed": len(rows),
                    "expected": len(INSTANCES),
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                },
            )
    if len(rows) != len(INSTANCES):
        raise RuntimeError("preflight did not return nine unique rows")
    _finalize(rows, frozen_hashes)


if __name__ == "__main__":
    main()
