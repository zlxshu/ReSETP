#!/usr/bin/env python3
"""Cheap, results-blind reconnaissance gate for the official HGS-CVRP.

This is a development-only diagnostic.  It deliberately excludes the six
frozen CVRPLIB instances and all Solomon/Homberger/China instances.  Passing
only authorizes an isolated HGS engineering lane; it does not authorize a
formal benchmark rerun, a solver replacement, or project Stage 2.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
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
FORMAL_PATH = REPO / "baselines/e2_alns/run_cvrplib_optimal_benchmark_20260716.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AUDIT = load_module("hgs_b_adapter", AUDIT_PATH)
FORMAL = load_module("hgs_b_formal_helpers", FORMAL_PATH)

from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_staged_alns_lns_hybrid,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402


SCHEMA = "resetp.algorithm.hgs-b-recon.v1"
DEFAULT_UPSTREAM = Path("/private/tmp/resetp-hgs-official-b-20260718")
DEFAULT_OUT = REPO / "baselines/e2_alns/official_hgs_b_gate_20260718"
UPSTREAM_COMMIT = "1a927955cd2861a29d978f0d359d6e647db9319c"
OFFICIAL_REPO = "https://github.com/vidalt/HGS-CVRP.git"
FROZEN_SIX = {
    "X-n101-k25",
    "X-n120-k6",
    "X-n200-k36",
    "X-n214-k11",
    "X-n313-k71",
    "X-n322-k28",
}
INSTANCES = {
    "X-n110-k13": 14971,
    "X-n157-k13": 16876,
    "X-n190-k8": 16980,
}
SEEDS = (1, 2, 3)
WALL_SECONDS = 3.0
ALNS_EVAL_CEILING = 1_000_000
TOL = 1.0e-9

# Results-blind strong-positive gate, frozen before any shared comparison:
# 1) all upstream tests and all 18 shared tasks are valid;
# 2) HGS median gap to the published optimum is <= 1% on every instance and
#    pooled median HGS gap is <= 0.5%;
# 3) HGS median cost beats current ALNS by >= 2% on at least two of three
#    instances and is not worse by > 0.5% on any instance.
MAX_HGS_INSTANCE_MEDIAN_GAP_PCT = 1.0
MAX_HGS_POOLED_MEDIAN_GAP_PCT = 0.5
MIN_CLEAR_ADVANTAGE_PCT = 2.0
MAX_ALLOWED_DISADVANTAGE_PCT = 0.5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def prepare_bundle(problem: Any, source_path: Path, bundle: Path) -> None:
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    customers = sorted(node for node in problem.coordinates if node != problem.depot)
    ordered = [problem.depot, *customers]
    node_rows = []
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
            "source_instance": problem.name,
            "source_repo": OFFICIAL_REPO,
            "source_commit": UPSTREAM_COMMIT,
            "source_sha256": sha256(source_path),
            "num_ev": 0,
            "distance_rule": "floor(Euclidean+0.5)",
            "objective": "total_distance_only",
            "development_only": True,
        },
        "nodes": node_rows,
    }
    write_json(bundle / "instance.json", payload)
    matrix = np.asarray(
        [
            [float(AUDIT.distance(problem, source, target)) for target in ordered]
            for source in ordered
        ],
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
                "datetime_utc": "2026-07-18T00:00:00Z",
                "actual_gco2_per_kwh": 0,
                "forecast_gco2_per_kwh": 0,
                "index_label": "not_applicable",
                "index_code": 0,
                "horizon_second_start": 0,
            }
        )


def validate_hgs(problem: Any, solution_path: Path) -> dict[str, Any]:
    routes, announced_cost = AUDIT.parse_solution(solution_path)
    reconstructed, mapped = AUDIT.reconstruct(problem, routes)
    flat = [node for route in mapped for node in route]
    expected = sorted(node for node in problem.coordinates if node != problem.depot)
    loads = [sum(problem.demands[node] for node in route) for route in mapped]
    failures = []
    if sorted(flat) != expected or len(flat) != len(set(flat)):
        failures.append("CUSTOMER_COVERAGE_NOT_EXACTLY_ONCE")
    if any(load > problem.capacity for load in loads):
        failures.append("CAPACITY_EXCEEDED")
    if reconstructed != announced_cost:
        failures.append("ANNOUNCED_COST_MISMATCH")
    return {
        "cost": float(reconstructed),
        "announced_cost": float(announced_cost),
        "route_count": len(routes),
        "max_route_load": max(loads),
        "failures": failures,
        "passed": not failures,
    }


def run_hgs(
    binary: Path,
    source: Path,
    problem: Any,
    name: str,
    seed: int,
    optimum: int,
    out: Path,
) -> dict[str, Any]:
    solution_path = out / "solutions" / f"hgs__{name}__seed{seed}.sol"
    solution_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(binary),
        str(source),
        str(solution_path),
        "-t",
        str(WALL_SECONDS),
        "-seed",
        str(seed),
        "-round",
        "1",
        "-log",
        "0",
    ]
    began = time.perf_counter()
    completed = subprocess.run(command, text=True, capture_output=True, timeout=60, check=False)
    elapsed = time.perf_counter() - began
    if completed.returncode != 0 or not solution_path.is_file():
        return {
            "algorithm": "official_hgs",
            "instance": name,
            "seed": seed,
            "status": f"ERROR_RETURN_{completed.returncode}",
            "elapsed_seconds": elapsed,
            "cost": "",
            "gap_pct": "",
            "route_count": "",
            "feasible": False,
            "details": {"stdout": completed.stdout, "stderr": completed.stderr},
        }
    validation = validate_hgs(problem, solution_path)
    cost = float(validation["cost"])
    return {
        "algorithm": "official_hgs",
        "instance": name,
        "seed": seed,
        "status": "OK" if validation["passed"] else ";".join(validation["failures"]),
        "elapsed_seconds": elapsed,
        "cost": cost,
        "gap_pct": 100.0 * (cost - optimum) / optimum,
        "route_count": validation["route_count"],
        "feasible": bool(validation["passed"]),
        "details": {
            "command": command,
            "validation": validation,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "solution_sha256": sha256(solution_path),
        },
    }


def run_alns(
    bundle_dir: Path,
    problem: Any,
    name: str,
    seed: int,
    optimum: int,
) -> dict[str, Any]:
    prices = AUDIT.distance_only_prices(problem.capacity)
    began = time.perf_counter()
    try:
        result = run_staged_alns_lns_hybrid(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=seed,
                eval_budget=ALNS_EVAL_CEILING,
                max_runtime_seconds=WALL_SECONDS,
                require_charging_signal=False,
                carbon_aware_operators=False,
                refined_carbon_operators=False,
            ),
            prices=prices,
            carbon_weight=1.0,
            carbon_quota_kg=math.inf,
            enable_staged_search=True,
        )
        elapsed = time.perf_counter() - began
        bundle = load_search_bundle(bundle_dir)
        solution = result["best_solution"]
        violations = check_solution(solution, bundle.instance, prices)
        generic = float(evaluate(solution, bundle.instance, [], prices, carbon_quota_kg=math.inf)["total_cost"])
        payload = {
            "routes": [asdict(route) for route in solution.routes],
            "charging_actions": [asdict(item) for item in solution.charging_actions],
            "cross_site_services": [asdict(item) for item in solution.cross_site_services],
        }
        node_ids = [node.node_id for node in bundle.instance.nodes]
        depot = [node.node_id for node in bundle.instance.nodes if node.node_type == "d"]
        pure = FORMAL.pure_cvrp_recompute(
            payload,
            node_ids=node_ids,
            demands={node.node_id: float(node.demand) for node in bundle.instance.nodes},
            capacity=float(problem.capacity),
            depot_id=depot[0],
            distance_matrix=np.asarray(bundle.instance.distance_matrix, dtype=float).tolist(),
        )
        cost = float(pure["total_distance"])
        failures = list(pure["failures"])
        failures.extend(f"GENERIC:{item}" for item in violations)
        if abs(generic - cost) > TOL or abs(float(result["best_cost"]) - cost) > TOL:
            failures.append("OBJECTIVE_MISMATCH")
        return {
            "algorithm": "current_alns",
            "instance": name,
            "seed": seed,
            "status": "OK" if not failures else ";".join(failures),
            "elapsed_seconds": elapsed,
            "cost": cost,
            "gap_pct": 100.0 * (cost - optimum) / optimum,
            "route_count": len(solution.routes),
            "feasible": not failures,
            "details": {
                "evaluations": int(result["evaluations"]),
                "candidate_scores": int(result["candidate_scores"]),
                "generic_cost": generic,
                "best_cost": float(result["best_cost"]),
                "pure_recomputation": pure,
                "solution": payload,
            },
        }
    except Exception as exc:
        return {
            "algorithm": "current_alns",
            "instance": name,
            "seed": seed,
            "status": f"ERROR:{type(exc).__name__}:{exc}",
            "elapsed_seconds": time.perf_counter() - began,
            "cost": "",
            "gap_pct": "",
            "route_count": "",
            "feasible": False,
            "details": {"exception_type": type(exc).__name__, "exception": str(exc)},
        }


def decide(rows: list[dict[str, Any]], upstream_tests_passed: bool) -> dict[str, Any]:
    valid = all(row["status"] == "OK" and row["feasible"] for row in rows)
    summaries = {}
    advantages = []
    hgs_gaps = []
    for name in INSTANCES:
        hgs = [row for row in rows if row["instance"] == name and row["algorithm"] == "official_hgs"]
        alns = [row for row in rows if row["instance"] == name and row["algorithm"] == "current_alns"]
        if len(hgs) != len(SEEDS) or len(alns) != len(SEEDS) or not all(
            isinstance(row["cost"], (int, float)) for row in hgs + alns
        ):
            summaries[name] = {"complete": False}
            continue
        hgs_cost = statistics.median(float(row["cost"]) for row in hgs)
        alns_cost = statistics.median(float(row["cost"]) for row in alns)
        hgs_gap = 100.0 * (hgs_cost - INSTANCES[name]) / INSTANCES[name]
        advantage = 100.0 * (alns_cost - hgs_cost) / alns_cost
        hgs_gaps.extend(float(row["gap_pct"]) for row in hgs)
        advantages.append(advantage)
        summaries[name] = {
            "complete": True,
            "hgs_median_cost": hgs_cost,
            "alns_median_cost": alns_cost,
            "hgs_median_gap_pct": hgs_gap,
            "hgs_advantage_over_alns_pct": advantage,
            "hgs_median_routes": statistics.median(float(row["route_count"]) for row in hgs),
            "alns_median_routes": statistics.median(float(row["route_count"]) for row in alns),
        }
    hgs_near = (
        len(summaries) == len(INSTANCES)
        and all(
            row.get("complete")
            and float(row["hgs_median_gap_pct"]) <= MAX_HGS_INSTANCE_MEDIAN_GAP_PCT
            for row in summaries.values()
        )
        and bool(hgs_gaps)
        and statistics.median(hgs_gaps) <= MAX_HGS_POOLED_MEDIAN_GAP_PCT
    )
    clear_wins = sum(value >= MIN_CLEAR_ADVANTAGE_PCT for value in advantages)
    no_material_loss = len(advantages) == len(INSTANCES) and all(
        value >= -MAX_ALLOWED_DISADVANTAGE_PCT for value in advantages
    )
    strong_positive = upstream_tests_passed and valid and hgs_near and clear_wins >= 2 and no_material_loss
    return {
        "schema_version": SCHEMA,
        "decision": "GO_A_ENGINEERING_DISCOVERY" if strong_positive else "STOP_AFTER_B",
        "strong_positive": strong_positive,
        "upstream_tests_passed": upstream_tests_passed,
        "all_shared_tasks_valid": valid,
        "hgs_near_bks_gate_passed": hgs_near,
        "clear_win_instance_count": clear_wins,
        "no_material_loss_gate_passed": no_material_loss,
        "instance_summaries": summaries,
        "thresholds": {
            "max_hgs_instance_median_gap_pct": MAX_HGS_INSTANCE_MEDIAN_GAP_PCT,
            "max_hgs_pooled_median_gap_pct": MAX_HGS_POOLED_MEDIAN_GAP_PCT,
            "min_clear_advantage_pct": MIN_CLEAR_ADVANTAGE_PCT,
            "minimum_clear_win_instances": 2,
            "max_allowed_disadvantage_pct": MAX_ALLOWED_DISADVANTAGE_PCT,
        },
        "authorization_boundary": (
            "GO authorizes isolated HGS engineering discovery only; it does not authorize "
            "formal test-set use, China81, E2-E7 reruns, solver replacement, or project Stage 2."
        ),
    }


def write_report(out: Path, metadata: dict[str, Any], decision: dict[str, Any]) -> None:
    lines = [
        "# Official HGS-CVRP B gate",
        "",
        f"- Decision: **{decision['decision']}**",
        f"- Upstream commit: `{UPSTREAM_COMMIT}`",
        "- Budget: 3 development instances × 3 seeds × 3 seconds × 2 algorithms",
        f"- Upstream tests passed: `{decision['upstream_tests_passed']}`",
        f"- All shared tasks valid: `{decision['all_shared_tasks_valid']}`",
        f"- HGS near-BKS gate: `{decision['hgs_near_bks_gate_passed']}`",
        f"- Clear HGS wins: `{decision['clear_win_instance_count']}/3`",
        "",
        "## Shared development comparison",
        "",
        "| Instance | BKS | HGS median | ALNS median | HGS gap | HGS advantage | HGS routes | ALNS routes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in decision["instance_summaries"].items():
        if not row.get("complete"):
            lines.append(f"| {name} | {INSTANCES[name]} | incomplete | incomplete | -- | -- | -- | -- |")
            continue
        lines.append(
            f"| {name} | {INSTANCES[name]} | {row['hgs_median_cost']:.0f} | "
            f"{row['alns_median_cost']:.0f} | {row['hgs_median_gap_pct']:.3f}% | "
            f"{row['hgs_advantage_over_alns_pct']:.3f}% | {row['hgs_median_routes']:.0f} | "
            f"{row['alns_median_routes']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            "This is a CVRP-only development diagnostic. Official HGS-CVRP does not model "
            "ReSETP time windows, heterogeneous fleets, SOC, nonlinear charging, electricity "
            "prices, carbon, or fairness. A GO result therefore supports examining HGS search "
            "machinery in isolation; it is not evidence that HGS solves the full ReSETP problem.",
            "",
            "The upstream self-test touched frozen X-n101-k25 only as an unmodified official "
            "software reproduction test. It was not used for tuning, comparison, or this decision.",
            "",
            f"Generated at `{metadata['finished_at_utc']}`.",
        ]
    )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    upstream = Path(os.environ.get("RESET_HGS_UPSTREAM", str(DEFAULT_UPSTREAM))).resolve()
    out = Path(os.environ.get("RESET_HGS_B_OUT", str(DEFAULT_OUT))).resolve()
    binary = upstream / "build-resetp-b/hgs"
    instance_root = upstream / "Instances/CVRP"
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip() != UPSTREAM_COMMIT:
        raise RuntimeError("official HGS checkout commit differs from the preregistered commit")
    if not binary.is_file():
        raise RuntimeError(f"HGS binary missing: {binary}")
    if FROZEN_SIX.intersection(INSTANCES):
        raise RuntimeError("development set overlaps the frozen six")
    if out.exists():
        raise RuntimeError(f"refusing to overwrite existing evidence directory: {out}")
    out.mkdir(parents=True)

    contract = {
        "schema_version": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "official_repo": OFFICIAL_REPO,
        "official_commit": UPSTREAM_COMMIT,
        "license": "MIT",
        "instances": INSTANCES,
        "seeds": list(SEEDS),
        "wall_seconds_per_task": WALL_SECONDS,
        "algorithms": ["official_hgs", "current_alns"],
        "thresholds": {
            "max_hgs_instance_median_gap_pct": MAX_HGS_INSTANCE_MEDIAN_GAP_PCT,
            "max_hgs_pooled_median_gap_pct": MAX_HGS_POOLED_MEDIAN_GAP_PCT,
            "min_clear_advantage_pct": MIN_CLEAR_ADVANTAGE_PCT,
            "minimum_clear_win_instances": 2,
            "max_allowed_disadvantage_pct": MAX_ALLOWED_DISADVANTAGE_PCT,
        },
        "excluded": sorted(FROZEN_SIX),
        "stage_boundary": "development reconnaissance only; no project Stage 2",
        "script_sha256": sha256(Path(__file__)),
    }
    write_json(out / "contract.json", contract)

    test_run = subprocess.run(
        ["ctest", "--test-dir", str(upstream / "build-resetp-b"), "--output-on-failure"],
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    (out / "upstream_ctest.log").write_text(test_run.stdout + test_run.stderr, encoding="utf-8")
    upstream_tests_passed = test_run.returncode == 0 and "100% tests passed" in test_run.stdout

    raw_sources = out / "raw_sources"
    bundles = out / "bundles"
    rows: list[dict[str, Any]] = []
    task_details = out / "task_details"
    task_details.mkdir()
    for name, optimum in INSTANCES.items():
        source = instance_root / f"{name}.vrp"
        copied = raw_sources / source.name
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copied)
        problem = AUDIT.parse_instance(copied)
        bundle_dir = bundles / name
        prepare_bundle(problem, copied, bundle_dir)
        for seed in SEEDS:
            for row in (
                run_hgs(binary, copied, problem, name, seed, optimum, out),
                run_alns(bundle_dir, problem, name, seed, optimum),
            ):
                detail_path = task_details / f"{row['algorithm']}__{name}__seed{seed}.json"
                write_json(detail_path, row)
                rows.append({key: value for key, value in row.items() if key != "details"})
                print(
                    json.dumps(
                        {
                            "algorithm": row["algorithm"],
                            "instance": name,
                            "seed": seed,
                            "status": row["status"],
                            "cost": row["cost"],
                            "gap_pct": row["gap_pct"],
                            "elapsed_seconds": row["elapsed_seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    fields = [
        "algorithm",
        "instance",
        "seed",
        "status",
        "elapsed_seconds",
        "cost",
        "gap_pct",
        "route_count",
        "feasible",
    ]
    with (out / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    decision = decide(rows, upstream_tests_passed)
    decision["decided_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(out / "decision.json", decision)
    metadata = {
        "schema_version": SCHEMA,
        "started_at_utc": contract["created_at_utc"],
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "official_repo": OFFICIAL_REPO,
        "official_commit": UPSTREAM_COMMIT,
        "official_checkout_clean": not bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=upstream, text=True).strip()
        ),
        "hgs_binary_sha256": sha256(binary),
        "license_sha256": sha256(upstream / "LICENSE"),
        "upstream_ctest_returncode": test_run.returncode,
        "task_count": len(rows),
        "claim_boundary": decision["authorization_boundary"],
    }
    write_json(out / "metadata.json", metadata)
    write_report(out, metadata, decision)
    hashed = {}
    for path in sorted(out.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        ):
            hashed[str(path.relative_to(out))] = sha256(path)
    write_json(out / "artifact_hashes.json", {"schema_version": SCHEMA, "files": hashed})
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)
    return 0 if all(row["status"] == "OK" for row in rows) and upstream_tests_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
