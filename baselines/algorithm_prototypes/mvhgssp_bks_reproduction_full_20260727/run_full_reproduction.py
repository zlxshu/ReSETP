"""Extend the frozen MV-HGS-SP warm-start reproduction from 2/18 to 18/18."""

from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from importlib.metadata import version
from pathlib import Path
from time import perf_counter, process_time, sleep
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BOUNDARY = ROOT / "baselines/algorithm_prototypes/boundary_probe_20260726"
OLD = ROOT / "baselines/algorithm_prototypes/mvhgssp_bks_reproduction_20260727"
INSTANCES = (
    ROOT
    / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
    / "sources/normalised_instances"
)
TARGET_TABLE = BOUNDARY / "NEW_BKS_TABLE.csv"
RAW = HERE / "raw_runs.json"
PROGRESS = HERE / "progress.json"
TASKS = HERE / "tasks"
SCALE = 1000.0
EPOCHS = 3
ITERATIONS = 12_000
SP_SECONDS = 180.0
EPS = 0.5
WORKERS = 6
SEALED = {"PR19A", "PR23A"}
ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

sys.path.insert(0, str(BOUNDARY))
from k1_depot_reassign_killtest import read_bks_solution
from pyvrp import read
from pyvrp._pyvrp import (
    RandomNumberGenerator,
)
from pyvrp._pyvrp import (
    Route as NativeRoute,
)
from pyvrp._pyvrp import (
    Solution as NativeSolution,
)
from pyvrp.crossover import (
    ordered_crossover,
    selective_route_exchange,
)
from pyvrp.diversity import broken_pairs_distance
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _targets() -> dict[str, dict[str, float]]:
    with TARGET_TABLE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 18:
        raise RuntimeError(f"expected 18 targets, found {len(rows)}")
    return {
        row["instance"]: {
            "bks_2013": float(row["bks_2013"]),
            "target": float(row["new_best"]),
        }
        for row in rows
    }


def _route_key(route: NativeRoute) -> str:
    return f"{route.vehicle_type()}|" + ",".join(
        str(client) for client in route.visits()
    )


def _cost(solution: NativeSolution) -> float:
    return float(sum(route.distance() for route in solution.routes()))


def _epoch(data, warm: NativeSolution, seed: int):
    params = SolveParams()
    rng = RandomNumberGenerator(seed=seed)
    fills = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size - 1)
    ]
    search = LocalSearch(
        data,
        rng,
        compute_neighbours(data, params.neighbourhood),
    )
    for operator in params.node_ops:
        if operator.supports(data):
            search.add_node_operator(operator(data))
    for operator in params.route_ops:
        if operator.supports(data):
            search.add_route_operator(operator(data))
    penalties = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    crossover = selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    algorithm = GeneticAlgorithm(
        data,
        penalties,
        rng,
        population,
        search,
        crossover,
        [warm, *fills],
        params.genetic,
    )
    result = algorithm.run(
        MaxIterations(ITERATIONS),
        collect_stats=False,
        display=False,
    )
    return result.best, [solution for solution in population if solution.is_feasible()]


def _assemble(data, pool: dict[str, float]) -> NativeSolution | None:
    records = []
    for route_key, cost in pool.items():
        vehicle_type, visits = route_key.split("|", 1)
        records.append(
            (
                (
                    int(vehicle_type),
                    tuple(int(value) for value in visits.split(",") if value),
                ),
                cost,
            )
        )
    clients = list(range(data.num_depots, data.num_locations))
    client_idx = {client: idx for idx, client in enumerate(clients)}
    rows: list[int] = []
    cols: list[int] = []
    for col, ((_, visits), _) in enumerate(records):
        for client in visits:
            rows.append(client_idx[client])
            cols.append(col)
    cover = csc_matrix(
        (np.ones(len(rows)), (rows, cols)),
        shape=(len(clients), len(records)),
    )
    vehicle_types = [record[0][0] for record in records]
    vehicle = csc_matrix(
        (
            np.ones(len(vehicle_types)),
            (vehicle_types, range(len(records))),
        ),
        shape=(data.num_vehicle_types, len(records)),
    )
    upper = np.array(
        [
            float(data.vehicle_type(idx).num_available)
            for idx in range(data.num_vehicle_types)
        ]
    )
    result = milp(
        c=np.array([cost for _, cost in records]),
        integrality=np.ones(len(records)),
        bounds=Bounds(np.zeros(len(records)), np.ones(len(records))),
        constraints=[
            LinearConstraint(
                cover,
                lb=np.ones(len(clients)),
                ub=np.ones(len(clients)),
            ),
            LinearConstraint(
                vehicle,
                lb=-np.inf * np.ones(len(upper)),
                ub=upper,
            ),
        ],
        options={"time_limit": SP_SECONDS},
    )
    if result.x is None:
        return None
    chosen = [records[idx] for idx, value in enumerate(result.x) if value > 0.5]
    solution = NativeSolution(
        data,
        [
            NativeRoute(data, list(visits), vehicle_type)
            for (vehicle_type, visits), _ in chosen
        ],
    )
    return solution if solution.is_feasible() else None


def _run_instance(task: tuple[str, float]) -> dict[str, Any]:
    instance_id, target = task
    data = read(str(INSTANCES / f"{instance_id}.vrp"), round_func="exact")
    bks_solution, _, bks_raw, claimed_raw = read_bks_solution(instance_id, data)
    if abs(bks_raw - claimed_raw) >= EPS:
        raise RuntimeError(f"{instance_id}: frozen BKS witness cost mismatch")
    start_wall = perf_counter()
    start_cpu = process_time()
    best = bks_solution
    best_raw = bks_raw
    pool: dict[str, float] = {}
    epochs: list[dict[str, Any]] = []
    for epoch_index in range(EPOCHS):
        searched, population = _epoch(data, best, epoch_index + 1)
        for solution in [*population, searched]:
            for route in solution.routes():
                pool.setdefault(_route_key(route), float(route.distance()))
        searched_raw = _cost(searched)
        if searched_raw < best_raw:
            best, best_raw = searched, searched_raw
        assembled = _assemble(data, pool)
        assembled_raw = _cost(assembled) if assembled is not None else None
        if assembled is not None and assembled_raw < best_raw:
            best, best_raw = assembled, assembled_raw
        epochs.append(
            {
                "epoch": epoch_index + 1,
                "seed": epoch_index + 1,
                "iterations": ITERATIONS,
                "searched_scaled": round(searched_raw),
                "assembled_scaled": (
                    round(assembled_raw) if assembled_raw is not None else None
                ),
                "incumbent_scaled": round(best_raw),
                "pool_routes": len(pool),
            }
        )
    witness = {
        "instance_id": instance_id,
        "cost_scaled": round(best_raw),
        "routes": [_route_key(route) for route in best.routes()],
    }
    target_scaled = round(target * SCALE)
    return {
        "instance_id": instance_id,
        "bks_2013": bks_raw / SCALE,
        "target": target,
        "mvhgssp_result": best_raw / SCALE,
        "result_scaled": round(best_raw),
        "target_scaled": target_scaled,
        "met_target": round(best_raw) <= target_scaled,
        "feasible": best.is_feasible(),
        "epochs": epochs,
        "cpu_seconds": process_time() - start_cpu,
        "wallclock_seconds": perf_counter() - start_wall,
        "protocol": f"{EPOCHS}x{ITERATIONS}+SP{int(SP_SECONDS)}s",
        "runner_sha256": _sha(Path(__file__).resolve()),
        "witness": witness,
    }


def _preflight(_: int) -> dict[str, Any]:
    sleep(1)
    return {
        "pid": os.getpid(),
        "pyvrp": version("pyvrp"),
        "runner": str(Path(__file__).resolve()),
    }


def _existing() -> dict[str, dict[str, Any]]:
    if not RAW.is_file():
        return {}
    rows = json.loads(RAW.read_text(encoding="utf-8"))
    return {row["instance_id"]: row for row in rows}


def _finalize(rows: list[dict[str, Any]], targets: dict[str, dict[str, float]]):
    by_id = {row["instance_id"]: row for row in rows}
    imported = json.loads((OLD / "decision.json").read_text(encoding="utf-8"))
    combined = {}
    for instance_id, values in targets.items():
        if instance_id in by_id:
            row = by_id[instance_id]
            combined[instance_id] = {
                "target": values["target"],
                "result": row["mvhgssp_result"],
                "met_target": bool(row["met_target"]),
                "source": "new_full_extension",
            }
        else:
            old = imported["results"].get(instance_id)
            if old is not None:
                combined[instance_id] = {
                    "target": values["target"],
                    "result": old["mvhgssp_result"],
                    "met_target": bool(old["bit_exact_match"]),
                    "source": "sealed_prior_2_of_18",
                }
    passed = sum(item["met_target"] for item in combined.values())
    decision = {
        "schema": "resetp.mvhgssp-bks-reproduction-full.decision.v1",
        "task_id": "E2-MVHGSSP-BKS-REPRODUCTION-FULL-002",
        "verdict": (
            "PASS_REPRODUCED_18_OF_18"
            if len(combined) == 18 and passed == 18
            else "STOP_NOT_ALL_TARGETS_REPRODUCED"
            if len(combined) == 18
            else "PARTIAL"
        ),
        "targets": 18,
        "evaluated": len(combined),
        "passed": passed,
        "failed": len(combined) - passed,
        "new_rows": len(rows),
        "sealed_prior_rows": len(combined) - len(rows),
        "results": combined,
        "claim_boundary": (
            "Reproduction does not prove superiority over plain HGS; "
            "it only establishes algorithm-name attribution under the same protocol."
        ),
    }
    _write_json(HERE / "decision.json", decision)
    _write_json(
        HERE / "metadata.json",
        {
            "schema": "resetp.mvhgssp-bks-reproduction-full.metadata.v1",
            "created_at_utc": __import__("datetime")
            .datetime.now(__import__("datetime").UTC)
            .isoformat(),
            "platform": platform.platform(),
            "python": sys.version,
            "pyvrp": version("pyvrp"),
            "environment": {key: os.environ.get(key) for key in ENV},
            "source_hashes": {
                str(path.relative_to(ROOT)): _sha(path)
                for path in (
                    Path(__file__).resolve(),
                    TARGET_TABLE,
                    OLD / "decision.json",
                )
            },
        },
    )
    report = [
        "# MV-HGS-SP full new-BKS reproduction",
        "",
        f"Decision: `{decision['verdict']}`.",
        "",
        (
            f"Evaluated {decision['evaluated']}/18; passed {passed}; "
            f"failed {decision['failed']}."
        ),
        (
            f"New extension rows: {len(rows)}; sealed prior rows: "
            f"{decision['sealed_prior_rows']}."
        ),
        "",
        (
            "This evidence does not show MV-HGS-SP beating plain HGS. It only "
            "tests whether the named method reproduces the same certified targets "
            "under the frozen warm-start protocol."
        ),
        "",
    ]
    (HERE / "report.md").write_text("\n".join(report), encoding="utf-8")
    artifacts = [
        RAW,
        PROGRESS,
        HERE / "decision.json",
        HERE / "metadata.json",
        HERE / "report.md",
        HERE / "resource_preflight.json",
    ]
    _write_json(
        HERE / "artifact_hashes.json",
        {
            "schema": "resetp.mvhgssp-bks-reproduction-full.hashes.v1",
            "algorithm": "sha256",
            "artifacts": {
                str(path.relative_to(HERE)): _sha(path)
                for path in artifacts
                if path.is_file()
            },
        },
    )
    return decision


def main() -> int:
    for key, value in ENV.items():
        if os.environ.get(key) != value:
            raise RuntimeError(f"required environment mismatch: {key}")
    targets = _targets()
    pending_targets = {
        instance_id: values
        for instance_id, values in targets.items()
        if instance_id not in SEALED
    }
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=context) as executor:
        probes = list(executor.map(_preflight, range(WORKERS)))
    if len({probe["pid"] for probe in probes}) != WORKERS:
        raise RuntimeError("six-distinct-PID preflight failed")
    _write_json(
        HERE / "resource_preflight.json", {"verdict": "PASS", "workers": probes}
    )
    existing = _existing()
    runner_hash = _sha(Path(__file__).resolve())
    for row in existing.values():
        if row.get("runner_sha256") != runner_hash:
            raise RuntimeError("existing row runner hash mismatch")
    pending = [
        (instance_id, values["target"])
        for instance_id, values in pending_targets.items()
        if instance_id not in existing
    ]
    _write_json(
        PROGRESS,
        {"status": "RUNNING", "completed": len(existing), "remaining": len(pending)},
    )
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=context) as executor:
        futures = {executor.submit(_run_instance, task): task[0] for task in pending}
        for future in as_completed(futures):
            instance_id = futures[future]
            payload = future.result()
            witness = payload.pop("witness")
            witness_path = TASKS / instance_id / "solution_witness.json"
            _write_json(witness_path, witness)
            payload["witness_path"] = str(witness_path.relative_to(ROOT))
            payload["witness_sha256"] = _sha(witness_path)
            existing[instance_id] = payload
            rows = sorted(existing.values(), key=lambda row: row["instance_id"])
            _write_json(RAW, rows)
            _write_json(
                PROGRESS,
                {
                    "status": "RUNNING",
                    "completed": len(rows),
                    "remaining": len(pending_targets) - len(rows),
                    "last": instance_id,
                },
            )
            print(
                f"{instance_id}: {'PASS' if payload['met_target'] else 'FAIL'} ({len(rows)}/{len(pending_targets)})",
                flush=True,
            )
    rows = sorted(existing.values(), key=lambda row: row["instance_id"])
    _write_json(
        PROGRESS, {"status": "COMPLETED", "completed": len(rows), "remaining": 0}
    )
    decision = _finalize(rows, targets)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
