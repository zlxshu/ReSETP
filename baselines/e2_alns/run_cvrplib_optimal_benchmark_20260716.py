#!/usr/bin/env python3
"""Run the frozen six-instance CVRPLIB optimal benchmark for E2.

Formal defaults are 6 instances x 10 seeds x 4000 complete evaluations.
The runner is resumable at whole-task granularity and never reads the public
solution routes during search; only the published optimum scalar is used when
computing the post-run gap.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

AUDIT_PATH = REPO / "baselines/e2_alns/audit_cvrplib_optimal_adapter_20260716.py"
AUDIT_SPEC = importlib.util.spec_from_file_location("cvrplib_adapter_audit", AUDIT_PATH)
if AUDIT_SPEC is None or AUDIT_SPEC.loader is None:
    raise RuntimeError(f"cannot import adapter audit: {AUDIT_PATH}")
AUDIT = importlib.util.module_from_spec(AUDIT_SPEC)
sys.modules[AUDIT_SPEC.name] = AUDIT
AUDIT_SPEC.loader.exec_module(AUDIT)

from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_staged_alns_lns_hybrid,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402


DEFAULT_OUT = REPO / "baselines/e2_alns/cvrplib_optimal_search_formal_20260716"
BUNDLE_ROOT = REPO / "baselines/e2_alns/cvrplib_optimal_formal_bundles_20260716"
BKS_MANIFEST = REPO / "baselines/e2_alns/cvrplib_official_bks_manifest_20260716.json"
OFFICIAL_PAGE_SNAPSHOT = REPO / "baselines/e2_alns/cvrplib_official_page_snapshot_20260716.json"
WINNER_PATH = SOLVER_SRC / "setp_solver/algorithms/resetp_alns/kernel/winner.py"
WINNER_RESULT_FIELDS = (
    "candidate_scores",
    "repair_scores",
    "repair_delta_count",
)
FORMAL_INSTANCES = tuple(AUDIT.INSTANCES)
FORMAL_SEEDS = tuple(range(1, 11))
FORMAL_EVAL_BUDGET = 4000
FORMAL_WORKERS = 4
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
CONTRACT_SCHEMA = "resetp.e2.cvrplib-optimal-search-contract.v2"
TASK_SCHEMA = "resetp.e2.cvrplib-optimal-task.v2"
TOL = 1.0e-9


class FormalRunError(RuntimeError):
    pass


class ContractMismatchError(FormalRunError):
    pass


class TaskCheckpointError(FormalRunError):
    pass


def winner_result_contract_failures(
    source: str | None = None,
) -> list[str]:
    """Fail before search when the frozen winner does not expose real score counts."""
    text = WINNER_PATH.read_text(encoding="utf-8") if source is None else source
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"winner.py cannot be parsed: {exc}"]
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_run_staged_hybrid_entry"
        ),
        None,
    )
    if target is None:
        return ["winner.py lacks _run_staged_hybrid_entry"]
    returned_keys: set[str] = set()
    for node in ast.walk(target):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                returned_keys.add(key.value)
    missing = [field for field in WINNER_RESULT_FIELDS if field not in returned_keys]
    return [f"winner result field missing: {field}" for field in missing]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
    )


def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    _atomic_write_text(path, buffer.getvalue())


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


def verify_gold_environment() -> None:
    if str(Path(sys.executable).resolve()) != str(Path(GOLD_PYTHON).resolve()):
        raise FormalRunError(f"gold Python required: {GOLD_PYTHON}; got {sys.executable}")
    if np.__version__ != GOLD_NUMPY:
        raise FormalRunError(f"gold NumPy required: {GOLD_NUMPY}; got {np.__version__}")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise FormalRunError("PYTHONHASHSEED=0 must be set before the parent interpreter starts")


def _visible_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [item for item in path.iterdir() if not item.name.startswith("._") and ".tmp-" not in item.name]


def prepare_bundle(name: str) -> Path:
    problem = AUDIT.parse_instance(AUDIT.RAW / f"{name}.vrp")
    customer_nodes = sorted(node for node in problem.coordinates if node != problem.depot)
    ordered = [problem.depot, *customer_nodes]
    bundle = BUNDLE_ROOT / name
    bundle.mkdir(parents=True, exist_ok=True)
    node_rows: list[dict[str, Any]] = []
    for position, raw_node in enumerate(ordered):
        is_depot = raw_node == problem.depot
        node_rows.append(
            {
                "node_id": "D0" if is_depot else f"C{position}",
                "node_type": "d" if is_depot else "c",
                "x": problem.coordinates[raw_node][0],
                "y": problem.coordinates[raw_node][1],
                "demand": float(problem.demands[raw_node]),
                "ready_time": 0.0,
                "due_time": 1.0e12,
                "service_time": 0.0,
            }
        )
    payload = {
        "schema_version": "resetp.cvrplib-distance-only.v1",
        "metadata": {
            "source_instance": name,
            "source_url": AUDIT.SOURCE_URL,
            "num_ev": 0,
            "distance_rule": "floor(Euclidean+0.5)",
            "objective": "total_distance_only",
        },
        "nodes": node_rows,
    }
    (bundle / "instance.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    matrix = np.asarray(
        [[float(AUDIT.distance(problem, source, target)) for target in ordered] for source in ordered],
        dtype=float,
    )
    np.save(bundle / "distance_matrix.npy", matrix)
    with (bundle / "carbon_profile.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "time_index",
                "datetime_utc",
                "actual_gco2_per_kwh",
                "forecast_gco2_per_kwh",
                "index_label",
                "index_code",
                "horizon_second_start",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "time_index": 0,
                "datetime_utc": "2026-07-16T00:00:00Z",
                "actual_gco2_per_kwh": 0,
                "forecast_gco2_per_kwh": 0,
                "index_label": "not_applicable",
                "index_code": 0,
                "horizon_second_start": 0,
            }
        )
    return bundle


def bundle_hashes(bundle: Path) -> dict[str, str]:
    expected = ("instance.json", "distance_matrix.npy", "carbon_profile.csv")
    missing = [name for name in expected if not (bundle / name).is_file()]
    if missing:
        raise FormalRunError(f"bundle is incomplete at {bundle}: {missing}")
    return {name: sha256(bundle / name) for name in expected}


def prepare_all_bundles(
    instances: tuple[str, ...], *, allow_create: bool = True
) -> dict[str, dict[str, str]]:
    hashes: dict[str, dict[str, str]] = {}
    for name in instances:
        bundle = BUNDLE_ROOT / name
        existing = _visible_files(bundle)
        if existing:
            try:
                hashes[name] = bundle_hashes(bundle)
            except FormalRunError as exc:
                raise FormalRunError(
                    f"existing formal bundle is incomplete and will not be overwritten: {bundle}"
                ) from exc
            continue
        if not allow_create:
            raise FormalRunError(
                f"formal resume requires the original read-only bundle: {bundle}"
            )
        bundle = prepare_bundle(name)
        hashes[name] = bundle_hashes(bundle)
    return hashes


def load_bks_manifest() -> dict[str, Any]:
    payload = json.loads(BKS_MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "resetp.e2.cvrplib-official-bks.v1":
        raise FormalRunError("official BKS manifest schema differs")
    rows = payload.get("instances")
    if not isinstance(rows, dict) or set(rows) != set(FORMAL_INSTANCES):
        raise FormalRunError("official BKS manifest does not contain the frozen six instances")
    if (
        payload.get("official_page_snapshot")
        != str(OFFICIAL_PAGE_SNAPSHOT.relative_to(REPO))
        or payload.get("official_page_snapshot_sha256") != sha256(OFFICIAL_PAGE_SNAPSHOT)
    ):
        raise FormalRunError("official CVRPLIB page snapshot is missing or differs")
    snapshot = json.loads(OFFICIAL_PAGE_SNAPSHOT.read_text(encoding="utf-8"))
    if snapshot.get("schema_version") != "resetp.e2.cvrplib-official-page-snapshot.v1":
        raise FormalRunError("official CVRPLIB page snapshot schema differs")
    snapshot_rows = snapshot.get("instances")
    if not isinstance(snapshot_rows, dict) or set(snapshot_rows) != set(FORMAL_INSTANCES):
        raise FormalRunError("official CVRPLIB page snapshot does not contain the frozen six instances")
    for name, row in rows.items():
        if not bool(row.get("official_opt")) or int(row.get("published_optimum", 0)) <= 0:
            raise FormalRunError(f"official BKS is not sealed for {name}")
        snapshot_row = snapshot_rows[name]
        if (
            snapshot_row.get("opt") != "yes"
            or int(snapshot_row.get("upper_bound", 0)) != int(row["published_optimum"])
        ):
            raise FormalRunError(f"official page snapshot differs from BKS manifest for {name}")
        vrp = AUDIT.RAW / f"{name}.vrp"
        sol = AUDIT.RAW / f"{name}.sol"
        if sha256(vrp) != row.get("instance_sha256") or sha256(sol) != row.get("solution_sha256"):
            raise FormalRunError(f"official source hash differs for {name}")
    return payload


def official_optimum(manifest: dict[str, Any], name: str) -> int:
    return int(manifest["instances"][name]["published_optimum"])


def _source_paths() -> tuple[Path, ...]:
    fixed_paths = (
        Path(__file__).resolve(),
        AUDIT_PATH.resolve(),
        BKS_MANIFEST.resolve(),
        OFFICIAL_PAGE_SNAPSHOT.resolve(),
    )
    solver_sources = tuple(
        sorted((REPO / "solver/src/setp_solver").rglob("*.py"), key=lambda path: str(path))
    )
    paths = fixed_paths + solver_sources
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FormalRunError(f"formal source file is missing: {missing}")
    return paths


def build_contract(
    *,
    instances: tuple[str, ...],
    seeds: tuple[int, ...],
    eval_budget: int,
    workers: int,
    max_runtime_seconds: float,
    bundles: dict[str, dict[str, str]],
) -> dict[str, Any]:
    if not 1 <= workers <= FORMAL_WORKERS:
        raise FormalRunError(f"workers must be between 1 and {FORMAL_WORKERS}")
    if eval_budget <= 0 or max_runtime_seconds <= 0:
        raise FormalRunError("evaluation budget and runtime must be positive")
    if len(set(instances)) != len(instances) or len(set(seeds)) != len(seeds):
        raise FormalRunError("instances and seeds must be unique")
    bks = load_bks_manifest()
    body = {
        "schema_version": CONTRACT_SCHEMA,
        "instances": list(instances),
        "seeds": list(seeds),
        "eval_budget": int(eval_budget),
        "workers": int(workers),
        "max_runtime_seconds": float(max_runtime_seconds),
        "environment": {
            "python_executable": GOLD_PYTHON,
            "numpy_version": GOLD_NUMPY,
            "pythonhashseed": "0",
        },
        "algorithm": {
            "name": "TVCI-ALNS base path-search core",
            "kernel": "staged ALNS-LNS hybrid",
            "enable_staged_search": True,
            "require_charging_signal": False,
            "carbon_aware_operators": False,
            "refined_carbon_operators": False,
            "test_set_no_tuning": True,
        },
        "objective": "CVRPLIB rounded-Euclidean total distance only",
        "bks_manifest_sha256": sha256(BKS_MANIFEST),
        "bks_scalars": {name: official_optimum(bks, name) for name in instances},
        "bundle_hashes": bundles,
        "source_file_hashes": {
            str(path.relative_to(REPO)): sha256(path) for path in _source_paths()
        },
        "claim_boundary": "base CVRP path-search core only",
        "evidence_boundary": "All tasks, failures, timeouts, and unfavorable gaps are retained.",
    }
    return {**body, "contract_sha256": canonical_sha256(body)}


def ensure_contract(out: Path, contract: dict[str, Any]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "contract.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        comparable = {k: v for k, v in existing.items() if k not in {"created_at_utc", "source_commit_at_start"}}
        if comparable != contract:
            raise ContractMismatchError("existing output contract differs from requested contract")
        return existing
    if _visible_files(out):
        raise ContractMismatchError("output directory is non-empty but has no formal contract")
    stored = {
        **contract,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit_at_start": git_head(),
    }
    atomic_write_json(path, stored)
    return stored


def task_key(name: str, seed: int) -> str:
    return f"{name}__seed{seed}"


def solution_payload(solution: Any) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def pure_cvrp_recompute(
    solution: dict[str, Any],
    *,
    node_ids: list[str],
    demands: dict[str, float],
    capacity: float,
    depot_id: str,
    distance_matrix: list[list[float]],
) -> dict[str, Any]:
    """Pure CVRP audit: no generic checker, evaluator, or BKS route is used."""

    index = {node_id: position for position, node_id in enumerate(node_ids)}
    expected = {node_id for node_id in node_ids if node_id != depot_id}
    visited: list[str] = []
    route_costs: list[float] = []
    route_loads: list[float] = []
    failures: list[str] = []
    for route_index, route in enumerate(solution.get("routes", []), start=1):
        sequence = list(route.get("node_sequence", []))
        if len(sequence) < 2 or sequence[0] != depot_id or sequence[-1] != depot_id:
            failures.append(f"route {route_index} does not start and end at {depot_id}")
            continue
        unknown = [node for node in sequence if node not in index]
        if unknown:
            failures.append(f"route {route_index} contains unknown nodes {unknown}")
            continue
        interior = sequence[1:-1]
        if depot_id in interior:
            failures.append(f"route {route_index} revisits the depot internally")
        visited.extend(interior)
        load = sum(float(demands[node]) for node in interior if node in demands)
        route_loads.append(load)
        if load > capacity + TOL:
            failures.append(f"route {route_index} exceeds capacity: {load}>{capacity}")
        route_costs.append(
            sum(
                float(distance_matrix[index[source]][index[target]])
                for source, target in zip(sequence, sequence[1:])
            )
        )
    if set(visited) != expected or len(visited) != len(expected) or len(visited) != len(set(visited)):
        failures.append("customer coverage is not exactly once")
    return {
        "total_distance": float(sum(route_costs)),
        "route_costs": route_costs,
        "route_loads": route_loads,
        "visited_customer_count": len(visited),
        "expected_customer_count": len(expected),
        "failures": failures,
        "passed": not failures,
    }


def expected_task(name: str, seed: int, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_key": task_key(name, seed),
        "instance": name,
        "seed": int(seed),
        "eval_budget": int(contract["eval_budget"]),
        "max_runtime_seconds": float(contract["max_runtime_seconds"]),
        "bundle_dir": str(BUNDLE_ROOT / name),
        "bundle_hashes": dict(contract["bundle_hashes"][name]),
        "published_optimum": int(contract["bks_scalars"][name]),
    }


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    verify_gold_environment()
    name = str(task["instance"])
    seed = int(task["seed"])
    eval_budget = int(task["eval_budget"])
    max_runtime_seconds = float(task["max_runtime_seconds"])
    started_utc = datetime.now(timezone.utc).isoformat()
    began = time.perf_counter()
    try:
        bundle_dir = Path(str(task["bundle_dir"]))
        if bundle_hashes(bundle_dir) != task["bundle_hashes"]:
            raise FormalRunError(f"bundle hash differs for {name}")
        problem = AUDIT.parse_instance(AUDIT.RAW / f"{name}.vrp")
        prices = AUDIT.distance_only_prices(problem.capacity)
        config = WinnerKernelConfig(
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            require_charging_signal=False,
            carbon_aware_operators=False,
            refined_carbon_operators=False,
        )
        result = run_staged_alns_lns_hybrid(
            bundle_dir,
            config=config,
            prices=prices,
            carbon_weight=1.0,
            carbon_quota_kg=math.inf,
            enable_staged_search=True,
        )
        bundle = load_search_bundle(bundle_dir)
        solution = result["best_solution"]
        violations = check_solution(solution, bundle.instance, prices)
        reevaluated = evaluate(solution, bundle.instance, [], prices, carbon_quota_kg=math.inf)
        best_cost = float(result["best_cost"])
        generic_cost = float(reevaluated["total_cost"])
        payload = solution_payload(solution)
        node_ids = [node.node_id for node in bundle.instance.nodes]
        depot_ids = [node.node_id for node in bundle.instance.nodes if node.node_type == "d"]
        if len(depot_ids) != 1:
            raise FormalRunError(f"expected one depot, got {depot_ids}")
        pure = pure_cvrp_recompute(
            payload,
            node_ids=node_ids,
            demands={node.node_id: float(node.demand) for node in bundle.instance.nodes},
            capacity=float(problem.capacity),
            depot_id=depot_ids[0],
            distance_matrix=np.asarray(bundle.instance.distance_matrix, dtype=float).tolist(),
        )
        pure_cost = float(pure["total_distance"])
        optimum = int(task["published_optimum"])
        candidate_scores = int(result["candidate_scores"])
        repair_delta_count = int(result["repair_delta_count"])
        failure_codes: list[str] = []
        if int(result["evaluations"]) != eval_budget:
            failure_codes.append("INVALID_EVALUATION_COUNT")
        if candidate_scores != eval_budget:
            failure_codes.append("INVALID_CANDIDATE_SCORE_COUNT")
        if repair_delta_count < 0:
            failure_codes.append("INVALID_REPAIR_DELTA_COUNT")
        if not (bool(result["feasible"]) and not violations and bool(pure["passed"])):
            failure_codes.append("INFEASIBLE")
        if abs(best_cost - generic_cost) > TOL:
            failure_codes.append("SEARCH_GENERIC_OBJECTIVE_MISMATCH")
        if abs(best_cost - pure_cost) > TOL:
            failure_codes.append("SEARCH_PURE_OBJECTIVE_MISMATCH")
        if abs(generic_cost - pure_cost) > TOL:
            failure_codes.append("GENERIC_PURE_OBJECTIVE_MISMATCH")
        row: dict[str, Any] = {
            "task_key": task_key(name, seed),
            "instance": name,
            "seed": int(seed),
            "customers": problem.dimension - 1,
            "eval_budget": int(eval_budget),
            "evaluations": int(result["evaluations"]),
            "best_cost": best_cost,
            "generic_cost": generic_cost,
            "pure_cost": pure_cost,
            "independent_cost": pure_cost,
            "published_optimum": optimum,
            "gap_pct": 100.0 * (pure_cost - optimum) / optimum,
            "elapsed_seconds": time.perf_counter() - began,
            "feasible": bool(result["feasible"]) and not violations and bool(pure["passed"]),
            "violation_count": len(violations) + len(pure["failures"]),
            "route_count": len(solution.routes),
            "status": "OK" if not failure_codes else ";".join(failure_codes),
            "failure_codes": failure_codes,
            "started_at_utc": started_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "objective_match": not any("OBJECTIVE_MISMATCH" in code for code in failure_codes),
            "solution": payload,
            "pure_recomputation": pure,
            "operator_counts": result.get("operator_counts", {}),
            "score_counts": result.get("score_counts", {}),
            "candidate_scores": candidate_scores,
            "repair_delta_count": repair_delta_count,
        }
    except Exception as exc:  # preserve every failed task as evidence
        row = {
            "task_key": task_key(name, seed),
            "instance": name,
            "seed": int(seed),
            "customers": "",
            "eval_budget": int(eval_budget),
            "evaluations": 0,
            "best_cost": "",
            "generic_cost": "",
            "pure_cost": "",
            "independent_cost": "",
            "published_optimum": int(task["published_optimum"]),
            "gap_pct": "",
            "elapsed_seconds": time.perf_counter() - began,
            "feasible": False,
            "violation_count": "",
            "route_count": "",
            "status": f"ERROR:{type(exc).__name__}:{exc}",
            "failure_codes": [f"ERROR:{type(exc).__name__}"],
            "started_at_utc": started_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "objective_match": False,
            "solution": {},
            "pure_recomputation": {},
            "operator_counts": {},
            "score_counts": {},
            "candidate_scores": 0,
            "repair_delta_count": 0,
        }
    return row


def _task_path(tasks_dir: Path, task: dict[str, Any]) -> Path:
    return tasks_dir / f"{task['task_key']}.json"


def _save_task_checkpoint(path: Path, contract_sha: str, task: dict[str, Any], row: dict[str, Any]) -> None:
    envelope = {
        "schema_version": TASK_SCHEMA,
        "contract_sha256": contract_sha,
        "task": task,
        "status": "completed",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload_sha256": canonical_sha256(row),
        "payload": row,
    }
    atomic_write_json(path, envelope)


def validate_task_row(task: dict[str, Any], row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    identity = {
        "task_key": task["task_key"],
        "instance": task["instance"],
        "seed": int(task["seed"]),
        "eval_budget": int(task["eval_budget"]),
        "published_optimum": int(task["published_optimum"]),
    }
    for field, expected in identity.items():
        actual = row.get(field)
        if field in {"seed", "eval_budget", "published_optimum"}:
            try:
                actual = int(actual)
            except (TypeError, ValueError):
                pass
        if actual != expected:
            failures.append(f"{field} differs: expected {expected!r}, got {actual!r}")
    if row.get("status") == "OK":
        if int(row.get("evaluations", -1)) != int(task["eval_budget"]):
            failures.append("OK row does not use the full evaluation budget")
        if int(row.get("candidate_scores", -1)) != int(task["eval_budget"]):
            failures.append("OK row does not contain the full candidate-score count")
        try:
            repair_delta_count = int(row.get("repair_delta_count", -1))
        except (TypeError, ValueError):
            repair_delta_count = -1
        if repair_delta_count < 0:
            failures.append("OK row has no valid repair-delta count")
        if not bool(row.get("feasible")) or int(row.get("violation_count", -1)) != 0:
            failures.append("OK row is not independently feasible")
        if not bool(row.get("objective_match")):
            failures.append("OK row does not have three-way objective agreement")
        try:
            costs = [float(row[field]) for field in ("best_cost", "generic_cost", "pure_cost")]
        except (KeyError, TypeError, ValueError):
            failures.append("OK row has missing or non-numeric objective values")
        else:
            if not all(math.isfinite(value) for value in costs):
                failures.append("OK row has non-finite objective values")
            if max(costs) - min(costs) > TOL:
                failures.append("OK row objective values differ")
        pure = row.get("pure_recomputation")
        if not isinstance(pure, dict) or not bool(pure.get("passed")) or pure.get("failures"):
            failures.append("OK row has no passing pure CVRP recomputation")
    return failures


def _load_task_checkpoint(path: Path, contract_sha: str, task: dict[str, Any]) -> dict[str, Any]:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskCheckpointError(f"cannot read checkpoint {path}: {exc}") from exc
    if envelope.get("schema_version") != TASK_SCHEMA:
        raise TaskCheckpointError(f"checkpoint schema differs: {path}")
    if envelope.get("contract_sha256") != contract_sha:
        raise ContractMismatchError(f"checkpoint contract differs: {path}")
    if envelope.get("task") != task or envelope.get("status") != "completed":
        raise TaskCheckpointError(f"checkpoint identity differs: {path}")
    row = envelope.get("payload")
    if not isinstance(row, dict) or envelope.get("payload_sha256") != canonical_sha256(row):
        raise TaskCheckpointError(f"checkpoint payload hash differs: {path}")
    failures = validate_task_row(task, row)
    if failures:
        raise TaskCheckpointError(f"checkpoint payload is invalid at {path}: {'; '.join(failures)}")
    return row


def load_completed(tasks_dir: Path, contract: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    expected_paths = {_task_path(tasks_dir, task): task for task in tasks}
    unexpected = [
        path for path in tasks_dir.glob("*.json")
        if not path.name.startswith("._") and path not in expected_paths
    ]
    if unexpected:
        raise ContractMismatchError(f"unexpected task checkpoints: {unexpected}")
    completed: dict[str, dict[str, Any]] = {}
    for path, task in expected_paths.items():
        if path.is_file():
            completed[task["task_key"]] = _load_task_checkpoint(
                path, str(contract["contract_sha256"]), task
            )
    return completed


def write_outputs(out: Path, rows: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    public_fields = [
        "task_key",
        "instance",
        "seed",
        "customers",
        "eval_budget",
        "evaluations",
        "candidate_scores",
        "repair_delta_count",
        "best_cost",
        "generic_cost",
        "pure_cost",
        "independent_cost",
        "published_optimum",
        "gap_pct",
        "elapsed_seconds",
        "feasible",
        "violation_count",
        "route_count",
        "status",
        "started_at_utc",
        "finished_at_utc",
        "objective_match",
        "failure_codes",
    ]
    csv_rows = [
        {
            **row,
            "failure_codes": json.dumps(row.get("failure_codes", []), ensure_ascii=False),
        }
        for row in rows
    ]
    atomic_write_csv(out / "raw_runs.csv", csv_rows, public_fields)
    atomic_write_json(out / "metadata.json", contract)
    atomic_write_json(
        out / "solutions_and_independent_recomputation.json",
        {
            row["task_key"]: {
                "solution": row.get("solution", {}),
                "pure_recomputation": row.get("pure_recomputation", {}),
                "generic_cost": row.get("generic_cost", ""),
                "search_cost": row.get("best_cost", ""),
            }
            for row in rows
        },
    )
    expected_keys = {
        task_key(name, seed)
        for name in contract["instances"]
        for seed in contract["seeds"]
    }
    observed_keys = [str(row.get("task_key", "")) for row in rows]
    matrix_complete = (
        len(observed_keys) == len(expected_keys)
        and len(set(observed_keys)) == len(observed_keys)
        and set(observed_keys) == expected_keys
    )
    complete = matrix_complete
    all_valid = complete and all(row.get("status") == "OK" for row in rows)
    formal_contract = (
        tuple(contract["instances"]) == FORMAL_INSTANCES
        and tuple(contract["seeds"]) == FORMAL_SEEDS
        and int(contract["eval_budget"]) == FORMAL_EVAL_BUDGET
        and int(contract["workers"]) == FORMAL_WORKERS
        and float(contract["max_runtime_seconds"]) == 1800.0
        and contract.get("environment", {}).get("python_executable") == GOLD_PYTHON
        and contract.get("environment", {}).get("numpy_version") == GOLD_NUMPY
        and contract.get("environment", {}).get("pythonhashseed") == "0"
    )
    if all_valid and formal_contract:
        verdict = "E2_CVRPLIB_FORMAL_COMPLETE"
    elif all_valid:
        verdict = "E2_CVRPLIB_NONFORMAL_SMOKE_COMPLETE"
    else:
        verdict = "E2_CVRPLIB_INCOMPLETE_OR_INVALID"
    decision = {
        "verdict": verdict,
        "complete": complete,
        "all_valid": all_valid,
        "matrix_complete": matrix_complete,
        "formal_contract": formal_contract,
        "task_count": len(rows),
        "expected_task_count": len(contract["instances"]) * len(contract["seeds"]),
        "claim_boundary": "base CVRP path-search core only",
    }
    atomic_write_json(out / "decision.json", decision)
    tier_by_instance = {
        "X-n101-k25": "small",
        "X-n120-k6": "small",
        "X-n200-k36": "medium",
        "X-n214-k11": "medium",
        "X-n313-k71": "large",
        "X-n322-k28": "large",
    }
    summary_fields = [
        "group", "task_count", "valid_count", "best_objective", "mean_objective",
        "best_gap_pct", "mean_gap_pct", "std_gap_pct", "mean_evaluations",
        "mean_candidate_scores", "mean_repair_delta_count", "mean_elapsed_seconds", "feasible_rate",
    ]

    def summarize(label: str, group: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [row for row in group if row.get("status") == "OK"]
        if not valid:
            return {"group": label, "task_count": len(group), "valid_count": 0}
        objectives = np.asarray([float(row["pure_cost"]) for row in valid], dtype=float)
        gaps = np.asarray([float(row["gap_pct"]) for row in valid], dtype=float)
        return {
            "group": label,
            "task_count": len(group),
            "valid_count": len(valid),
            "best_objective": float(objectives.min()),
            "mean_objective": float(objectives.mean()),
            "best_gap_pct": float(gaps.min()),
            "mean_gap_pct": float(gaps.mean()),
            "std_gap_pct": float(gaps.std(ddof=1)) if len(gaps) > 1 else 0.0,
            "mean_evaluations": float(np.mean([float(row["evaluations"]) for row in valid])),
            "mean_candidate_scores": float(np.mean([float(row["candidate_scores"]) for row in valid])),
            "mean_repair_delta_count": float(np.mean([float(row["repair_delta_count"]) for row in valid])),
            "mean_elapsed_seconds": float(np.mean([float(row["elapsed_seconds"]) for row in valid])),
            "feasible_rate": sum(bool(row["feasible"]) for row in group) / len(group),
        }

    instance_summaries = [summarize(name, [row for row in rows if row["instance"] == name]) for name in contract["instances"]]
    tier_summaries = [
        summarize(tier, [row for row in rows if tier_by_instance[row["instance"]] == tier])
        for tier in ("small", "medium", "large")
    ]
    atomic_write_csv(out / "summary_by_instance.csv", instance_summaries, summary_fields)
    atomic_write_csv(out / "summary_by_tier.csv", tier_summaries, summary_fields)
    lines = [
        "# E2 CVRPLIB公开最优算例正式搜索",
        "",
        f"判决：`{decision['verdict']}`。正式结果不得在全部任务有效完成前进入论文。",
        "",
        "| 算例 | 有效次数 | 最好Gap(%) | 平均Gap(%) | 标准差 | 平均时间(s) | 可行率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in contract["instances"]:
        group = [row for row in rows if row["instance"] == name and row.get("status") == "OK"]
        if group:
            gaps = np.asarray([float(row["gap_pct"]) for row in group], dtype=float)
            elapsed = np.asarray([float(row["elapsed_seconds"]) for row in group], dtype=float)
            feasible_rate = sum(bool(row["feasible"]) for row in group) / len(group)
            lines.append(
                f"| {name} | {len(group)} | {gaps.min():.4f} | {gaps.mean():.4f} | "
                f"{gaps.std(ddof=1) if len(gaps) > 1 else 0.0:.4f} | {elapsed.mean():.2f} | {feasible_rate:.1%} |"
            )
        else:
            lines.append(f"| {name} | 0 | -- | -- | -- | -- | 0% |")
    lines.extend(
        [
            "",
            "## 规模分层",
            "",
            "| 规模 | 任务数 | 有效数 | 最好Gap(%) | 平均Gap(%) | 标准差 | 平均时间(s) | 可行率 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for summary in tier_summaries:
        if int(summary.get("valid_count", 0)):
            lines.append(
                f"| {summary['group']} | {int(summary['task_count'])} | "
                f"{int(summary['valid_count'])} | {float(summary['best_gap_pct']):.4f} | "
                f"{float(summary['mean_gap_pct']):.4f} | {float(summary['std_gap_pct']):.4f} | "
                f"{float(summary['mean_elapsed_seconds']):.2f} | {float(summary['feasible_rate']):.1%} |"
            )
        else:
            lines.append(
                f"| {summary['group']} | {int(summary['task_count'])} | 0 | -- | -- | -- | -- | 0% |"
            )
    failed_rows = [row for row in rows if row.get("status") != "OK"]
    lines.extend(["", "## 失败与异常任务", ""])
    if failed_rows:
        lines.extend(
            [
                "| 任务 | 算例 | 种子 | 状态 | 耗时(s) |",
                "|---|---|---:|---|---:|",
            ]
        )
        for row in sorted(failed_rows, key=lambda item: str(item.get("task_key", ""))):
            elapsed = row.get("elapsed_seconds", "")
            elapsed_text = f"{float(elapsed):.2f}" if elapsed not in (None, "") else "--"
            lines.append(
                f"| {row.get('task_key', '')} | {row.get('instance', '')} | "
                f"{row.get('seed', '')} | {row.get('status', '')} | {elapsed_text} |"
            )
    else:
        lines.append("无；全60项任务均为OK且通过独立可行性与目标值复算。")
    lines.extend(
        [
            "",
            "本表只评价标准CVRP上的基础路径搜索内核。任何Gap较大、波动或失败均须原样保留，不能由完整模型结果替代。",
        ]
    )
    _atomic_write_text(out / "report.md", "\n".join(lines) + "\n")
    hashes = {
        str(path.relative_to(out)): sha256(path)
        for path in sorted(out.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and ".tmp-" not in path.name
        and ".tasks" not in path.parts
    }
    atomic_write_json(out / "artifact_hashes.json", hashes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--instances", nargs="+", default=list(FORMAL_INSTANCES))
    parser.add_argument("--seeds", nargs="+", type=int, default=list(FORMAL_SEEDS))
    parser.add_argument("--eval-budget", type=int, default=FORMAL_EVAL_BUDGET)
    parser.add_argument("--workers", type=int, default=FORMAL_WORKERS)
    parser.add_argument("--max-runtime-seconds", type=float, default=1800.0)
    return parser.parse_args()


def failure_row(task: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    return {
        "task_key": task["task_key"],
        "instance": task["instance"],
        "seed": task["seed"],
        "customers": "",
        "eval_budget": task["eval_budget"],
        "evaluations": 0,
        "candidate_scores": 0,
        "repair_delta_count": 0,
        "best_cost": "",
        "generic_cost": "",
        "pure_cost": "",
        "independent_cost": "",
        "published_optimum": task["published_optimum"],
        "gap_pct": "",
        "elapsed_seconds": 0.0,
        "feasible": False,
        "violation_count": "",
        "route_count": "",
        "status": f"ERROR:{type(exc).__name__}:{exc}",
        "failure_codes": [f"ERROR:{type(exc).__name__}"],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "objective_match": False,
        "solution": {},
        "pure_recomputation": {},
        "operator_counts": {},
        "score_counts": {},
    }


def main() -> int:
    args = parse_args()
    verify_gold_environment()
    metric_contract_failures = winner_result_contract_failures()
    if metric_contract_failures:
        raise FormalRunError(
            "winner metrics contract is not active; apply and verify "
            "docs/handoff/patches/e2_cvrplib_winner_metrics_20260716.patch "
            "after E7 releases the shared kernel: "
            + "; ".join(metric_contract_failures)
        )
    invalid = sorted(set(args.instances) - set(FORMAL_INSTANCES))
    if invalid:
        raise ValueError(f"instances outside frozen six-instance set: {invalid}")
    if not 1 <= int(args.workers) <= FORMAL_WORKERS:
        raise FormalRunError(f"workers must be between 1 and {FORMAL_WORKERS}")
    instances = tuple(args.instances)
    seeds = tuple(args.seeds)
    resuming = (args.out / "contract.json").is_file()
    bundles = prepare_all_bundles(instances, allow_create=not resuming)
    requested_contract = build_contract(
        instances=instances,
        seeds=seeds,
        eval_budget=int(args.eval_budget),
        workers=int(args.workers),
        max_runtime_seconds=float(args.max_runtime_seconds),
        bundles=bundles,
    )
    contract = ensure_contract(args.out, requested_contract)
    tasks_dir = args.out / ".tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks = [
        expected_task(name, seed, contract)
        for name in contract["instances"]
        for seed in contract["seeds"]
    ]
    completed = load_completed(tasks_dir, contract, tasks)
    pending = [task for task in tasks if task["task_key"] not in completed]
    if pending and int(args.workers) == 1:
        for task in pending:
            try:
                row = run_task(task)
            except BaseException as exc:
                row = failure_row(task, exc)
            _save_task_checkpoint(
                _task_path(tasks_dir, task), str(contract["contract_sha256"]), task, row
            )
            print(
                json.dumps(
                    {key: row.get(key) for key in ("task_key", "status", "gap_pct", "elapsed_seconds")},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    elif pending:
        with ProcessPoolExecutor(max_workers=int(args.workers)) as executor:
            futures = {
                executor.submit(run_task, task): task for task in pending
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    row = future.result()
                except BaseException as exc:
                    row = failure_row(task, exc)
                _save_task_checkpoint(
                    _task_path(tasks_dir, task), str(contract["contract_sha256"]), task, row
                )
                print(json.dumps({key: row.get(key) for key in ("task_key", "status", "gap_pct", "elapsed_seconds")}, ensure_ascii=False), flush=True)
    rows = sorted(
        load_completed(tasks_dir, contract, tasks).values(),
        key=lambda row: (str(row["instance"]), int(row["seed"])),
    )
    write_outputs(args.out, rows, contract)
    decision = json.loads((args.out / "decision.json").read_text(encoding="utf-8"))
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["all_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
