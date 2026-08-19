#!/usr/bin/env python3
"""Equal-time, one-seed route-core gate for genuine HGS -> project ALNS.

The six instances are a BKS-blind balanced subset of the already frozen
Homberger-200 development pool. The gate cannot authorise formal experiments.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO = Path(__file__).resolve().parents[3]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_variant_flags,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


HELPERS_PATH = REPO / "baselines/e2_alns/homberger_g1_helpers_20260718.py"
SPEC = importlib.util.spec_from_file_location("homberger_gate_helpers", HELPERS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {HELPERS_PATH}")
HELPERS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HELPERS
SPEC.loader.exec_module(HELPERS)

ROOT = REPO / "baselines/algorithm_prototypes/algo_reset_20260719"
WORKER = ROOT / "run_pyvrp_route_core_worker.py"
OUT = ROOT / "route_core_microgate"
BUNDLES = REPO / "baselines/e2_alns/homberger_200_development_bundles_20260717"
PY_HGS = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
PY_ILS = REPO / "build/python_envs/pyvrp-ils-0.13.4/bin/python"
INSTANCES = (
    "C1_2_1",
    "C2_2_1",
    "R1_2_1",
    "R2_2_1",
    "RC1_2_1",
    "RC2_2_1",
)
SEED = 1
TOTAL_SECONDS = 2.0
HYBRID_HGS_SECONDS = 1.0
HYBRID_ALNS_SECONDS = 1.0
SCALE = 1000
TOL = 1e-8
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
    )


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [
            asdict(service) for service in solution.cross_site_services
        ],
    }


def neutral_to_solution(payload: dict[str, Any], contract: dict[str, Any]) -> Solution:
    instance = contract["bundle"].instance
    nodes = [node.node_id for node in instance.nodes]
    depot = nodes[0]
    routes = []
    for index, visits in enumerate(payload["routes"], start=1):
        customers = [nodes[int(value)] for value in visits]
        routes.append(
            Route(
                f"CV{index}",
                "cv",
                depot,
                [depot, *customers, depot],
            )
        )
    return Solution(routes=routes)


def recompute(solution: Solution, contract: dict[str, Any]) -> dict[str, Any]:
    check = HELPERS.independent_vrptw_recompute(
        solution,
        bundle=contract["bundle"],
        capacity=contract["capacity"],
    )
    check["score"] = (
        float(contract["big_m"]) * int(check.get("route_count", 0))
        + float(check.get("distance_double", 0.0))
    )
    return check


def run_external(
    *,
    name: str,
    algorithm: str,
    python: Path,
    seconds: float,
    contract: dict[str, Any],
    initial: Solution,
    alns_education_evals: int = 0,
    educator: str = "none",
    education_interval: int = 1,
) -> tuple[dict[str, Any], Solution]:
    neutral_path = OUT / "neutral" / f"{name}__{algorithm}.json"
    nodes = [node.node_id for node in contract["bundle"].instance.nodes]
    node_to_index = {node_id: index for index, node_id in enumerate(nodes)}
    initial_path = OUT / "neutral" / f"{name}__common_initial.json"
    atomic_json(
        initial_path,
        {
            "routes": [
                [node_to_index[node_id] for node_id in route.node_sequence[1:-1]]
                for route in initial.routes
            ]
        },
    )
    command = [
        str(python),
        str(WORKER),
        "--bundle",
        str(BUNDLES / name),
        "--seed",
        str(SEED),
        "--seconds",
        str(seconds),
        "--scale",
        str(SCALE),
        "--fixed-cost",
        str(int(contract["big_m"] * SCALE)),
        "--initial-routes",
        str(initial_path),
        "--output",
        str(neutral_path),
    ]
    if alns_education_evals > 0:
        command.extend(
            ["--alns-education-evals", str(int(alns_education_evals))]
        )
    effective_educator = (
        "project_alns"
        if educator == "none" and alns_education_evals > 0
        else educator
    )
    if effective_educator != "none":
        command.extend(["--educator", effective_educator])
    if education_interval != 1:
        command.extend(["--education-interval", str(int(education_interval))])
    environment = os.environ.copy()
    environment.update(THREAD_ENV)
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=seconds + 30.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{algorithm} failed on {name}: {completed.stdout}\n{completed.stderr}"
        )
    neutral = json.loads(neutral_path.read_text(encoding="utf-8"))
    solution = neutral_to_solution(neutral, contract)
    independent = recompute(solution, contract)
    violations = check_solution(
        solution,
        contract["bundle"].instance,
        HELPERS.vrptw_prices(
            capacity=contract["capacity"],
            big_m=contract["big_m"],
        ),
    )
    row = {
        "instance": name,
        "seed": SEED,
        "algorithm": algorithm,
        "time_limit_seconds": seconds,
        "elapsed_seconds": float(neutral["elapsed_seconds"]),
        "route_count": int(independent["route_count"]),
        "distance_double": float(independent["distance_double"]),
        "lexicographic_score": float(independent["score"]),
        "evaluations": "",
        "feasible": bool(
            neutral["feasible"] and independent["passed"] and not violations
        ),
        "independent_recompute_pass": bool(independent["passed"]),
        "violation_count": len(violations),
        "solution_sha256": hashlib.sha256(
            json.dumps(
                solution_payload(solution),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "education": json.dumps(
            neutral.get("education", {}),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "status": "OK"
        if neutral["feasible"] and independent["passed"] and not violations
        else "FAIL",
    }
    return row, solution


def run_alns(
    *,
    name: str,
    algorithm: str,
    seconds: float,
    contract: dict[str, Any],
    initial: Solution,
) -> tuple[dict[str, Any], Solution]:
    prices = HELPERS.vrptw_prices(
        capacity=contract["capacity"],
        big_m=contract["big_m"],
    )
    initial_check = recompute(initial, contract)
    initial_violations = check_solution(initial, contract["bundle"].instance, prices)
    if not initial_check["passed"] or initial_violations:
        raise RuntimeError(f"invalid {algorithm} initial solution on {name}")
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=contract["max_vehicles"],
        max_ev=0,
        allow_cross_depot=False,
        enable_cross_depot_operator=False,
    )
    started = time.perf_counter()
    run = _run_winner_kernel_loop(
        initial,
        contract["bundle"].instance,
        contract["bundle"].carbon_profile,
        config=WinnerKernelConfig(
            seed=SEED,
            eval_budget=10_000_000,
            max_runtime_seconds=seconds,
        ),
        prices=prices,
        variant_flags=e2_alns_variant_flags(),
        policy=policy,
        carbon_weight=0.0,
        carbon_quota_kg=float("inf"),
    )
    elapsed = time.perf_counter() - started
    independent = recompute(run.best_solution, contract)
    violations = check_solution(
        run.best_solution,
        contract["bundle"].instance,
        prices,
    )
    objective_match = abs(float(run.best_obj) - float(independent["score"])) <= TOL
    feasible = bool(
        run.feasible and independent["passed"] and not violations and objective_match
    )
    row = {
        "instance": name,
        "seed": SEED,
        "algorithm": algorithm,
        "time_limit_seconds": seconds,
        "elapsed_seconds": elapsed,
        "route_count": int(independent["route_count"]),
        "distance_double": float(independent["distance_double"]),
        "lexicographic_score": float(independent["score"]),
        "evaluations": int(run.evaluations),
        "feasible": feasible,
        "independent_recompute_pass": bool(independent["passed"]),
        "violation_count": len(violations),
        "solution_sha256": hashlib.sha256(
            json.dumps(
                solution_payload(run.best_solution),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "status": "OK" if feasible else "FAIL",
    }
    return row, run.best_solution


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for name in INSTANCES:
        contract = HELPERS.bundle_contract(name)
        deterministic = HELPERS.deterministic_common_initial_solution(
            contract["bundle"].instance,
            capacity=contract["capacity"],
        )
        hgs_row, _ = run_external(
            name=name,
            algorithm="pyvrp_0_12_2_hgs",
            python=PY_HGS,
            seconds=TOTAL_SECONDS,
            contract=contract,
            initial=deterministic,
        )
        rows.append(hgs_row)
        alns_row, _ = run_alns(
            name=name,
            algorithm="project_alns",
            seconds=TOTAL_SECONDS,
            contract=contract,
            initial=deterministic,
        )
        rows.append(alns_row)
        seed_row, hgs_seed = run_external(
            name=name,
            algorithm="hybrid_hgs_seed",
            python=PY_HGS,
            seconds=HYBRID_HGS_SECONDS,
            contract=contract,
            initial=deterministic,
        )
        rows.append(seed_row)
        hybrid_row, _ = run_alns(
            name=name,
            algorithm="hgs_then_project_alns",
            seconds=HYBRID_ALNS_SECONDS,
            contract=contract,
            initial=hgs_seed,
        )
        hybrid_row["time_limit_seconds"] = TOTAL_SECONDS
        hybrid_row["elapsed_seconds"] = (
            float(seed_row["elapsed_seconds"]) + float(hybrid_row["elapsed_seconds"])
        )
        rows.append(hybrid_row)
        ils_row, _ = run_external(
            name=name,
            algorithm="pyvrp_0_13_4_ils",
            python=PY_ILS,
            seconds=TOTAL_SECONDS,
            contract=contract,
            initial=deterministic,
        )
        rows.append(ils_row)

    by_instance = {
        name: {
            str(row["algorithm"]): row
            for row in rows
            if row["instance"] == name
            and row["algorithm"] != "hybrid_hgs_seed"
        }
        for name in INSTANCES
    }
    comparisons = []
    for name, arms in by_instance.items():
        hybrid = float(arms["hgs_then_project_alns"]["lexicographic_score"])
        hgs = float(arms["pyvrp_0_12_2_hgs"]["lexicographic_score"])
        alns = float(arms["project_alns"]["lexicographic_score"])
        ils = float(arms["pyvrp_0_13_4_ils"]["lexicographic_score"])
        comparisons.append(
            {
                "instance": name,
                "hybrid_strictly_beats_hgs": hybrid < hgs - TOL,
                "hybrid_strictly_beats_alns": hybrid < alns - TOL,
                "hybrid_strictly_beats_both": hybrid < min(hgs, alns) - TOL,
                "hybrid_not_worse_than_ils": hybrid <= ils + TOL,
                "hybrid_score": hybrid,
                "hgs_score": hgs,
                "alns_score": alns,
                "ils_score": ils,
            }
        )
    failures = [
        f"{row['instance']}:{row['algorithm']}"
        for row in rows
        if row["status"] != "OK"
    ]
    double_wins = sum(item["hybrid_strictly_beats_both"] for item in comparisons)
    hgs_wins = sum(item["hybrid_strictly_beats_hgs"] for item in comparisons)
    alns_wins = sum(item["hybrid_strictly_beats_alns"] for item in comparisons)
    ils_nondegrade = sum(item["hybrid_not_worse_than_ils"] for item in comparisons)
    aggregate = {
        key: sum(
            float(arms[key]["lexicographic_score"])
            for arms in by_instance.values()
        )
        for key in (
            "pyvrp_0_12_2_hgs",
            "project_alns",
            "hgs_then_project_alns",
            "pyvrp_0_13_4_ils",
        )
    }
    strong_positive = (
        not failures
        and double_wins >= 4
        and hgs_wins >= 5
        and alns_wins >= 5
        and aggregate["hgs_then_project_alns"]
        < min(aggregate["pyvrp_0_12_2_hgs"], aggregate["project_alns"]) - TOL
        and ils_nondegrade >= 4
    )
    decision = {
        "verdict": (
            "GO_HOMBERGER_12X3"
            if strong_positive
            else "STOP_NO_STRONG_COMPLEMENTARITY"
        ),
        "strong_positive": strong_positive,
        "failure_tasks": failures,
        "pair_count": len(comparisons),
        "hybrid_double_win_count": double_wins,
        "hybrid_strict_hgs_win_count": hgs_wins,
        "hybrid_strict_alns_win_count": alns_wins,
        "hybrid_not_worse_ils_count": ils_nondegrade,
        "aggregate_scores": aggregate,
        "predeclared_gate": {
            "double_wins_minimum": 4,
            "strict_hgs_wins_minimum": 5,
            "strict_alns_wins_minimum": 5,
            "aggregate_strictly_beats_hgs_and_alns": True,
            "not_worse_than_ils_minimum": 4,
        },
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.algo-reset.route-core-microgate.v1",
        "instances": list(INSTANCES),
        "selection_rule": (
            "one BKS-blind _2_1 instance from each Homberger-200 family"
        ),
        "seed": SEED,
        "equal_total_wall_clock_seconds": TOTAL_SECONDS,
        "hybrid_split_seconds": [
            HYBRID_HGS_SECONDS,
            HYBRID_ALNS_SECONDS,
        ],
        "objective": "lexicographic vehicle count then double-precision distance",
        "algorithms": {
            "pyvrp_0_12_2_hgs": "genuine population HGS",
            "project_alns": "current project winner kernel from deterministic common start",
            "hgs_then_project_alns": "common start, one second HGS, then one second project ALNS",
            "pyvrp_0_13_4_ils": "separate strong open-source ILS from the same common start",
        },
        "claim_boundary": (
            "One-seed development screen only. It can stop a weak route-core "
            "combination or justify the approved 12x3 development gate; it "
            "cannot support a paper claim."
        ),
        "protected_files": [
            "solver/src/setp_solver/cost.py",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
        ],
    }
    atomic_json(OUT / "metadata.json", metadata)
    fields = list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "comparisons.json", comparisons)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# 真 HGS→项目 ALNS 最小路线门\n\n"
        f"结论：`{decision['verdict']}`。\n\n"
        f"六题中，组合同时严格胜 HGS 和 ALNS：{double_wins}/6；"
        f"严格胜 HGS：{hgs_wins}/6；严格胜 ALNS：{alns_wins}/6；"
        f"不差于 0.13.4 强对照：{ils_nondegrade}/6。\n\n"
        "这只是单种子开发筛选。没有读取 BKS，没有启动 Solomon、China81、"
        "E2--E7 或正式试验。只有强阳性才允许进入 Homberger 12×3。\n",
    )
    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
