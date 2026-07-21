#!/usr/bin/env python3
"""P4: long-budget BKS sprint on pre-registered public V13 targets.

Targets (pre-registered before any sprint run, from P1 formal results):
  close-the-table set (hybrid best did not yet beat the strongest
  literature value): PR12A PR13A PR15A PR16A PR16B PR17A PR20A PR22A
  PR23A PR24A
  new-BKS hunt set (nearest to current verified BKS): PR17B PR21B PR21A
  PR11B PR12B

Fresh seeds 11-12 (never used in G-DEV/G-CONFIRM/P1). The engine is the
IDENTICAL frozen MV-HGS-SP procedure used by the official public table
(P1) and the China81 experiment (P3): mother HGS to convergence, then
repeated exact set-partitioning recombination epochs until stall. The
ONLY differences here are (a) larger per-run compute budgets (higher
NoImprovement patience + longer MaxRuntime caps + a higher epoch ceiling)
and (b) fresh seeds. Running the same method with a larger budget is the
standard, honest way to chase a best-known solution; it is NOT an
algorithm change, so any solution found here is attributable to the same
MV-HGS-SP presented in the tables. No extra stage, no imported mechanism.

Every unit saves a route witness (vehicle_type + visits + raw cost) so a
strict new-BKS candidate can be independently verified route-by-route.
"""
from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
OPPONENT_CSV = FOUNDATION / "opponent_targets.csv"
OUT = PACKAGE / "p4_bks_sprint"

try:
    from scipy.optimize import Bounds, LinearConstraint, milp  # noqa: F401
except ModuleNotFoundError:
    system_site = Path("/opt/anaconda3/lib/python3.13/site-packages")
    if system_site.exists():
        sys.path.append(str(system_site))

if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from pyvrp import read  # noqa: E402
from pyvrp._pyvrp import RandomNumberGenerator  # noqa: E402
from pyvrp._pyvrp import Solution as NativeSolution  # noqa: E402
from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp.stop import MaxRuntime, MultipleCriteria, NoImprovement  # noqa: E402

from run_p1_formal_public import (  # noqa: E402
    _build_algorithm,
    _harvest_elites,
    _pool_add,
    _solution_cost,
    _solution_key,
    _solve_sp,
)

ROUND_FUNC = "exact"
SCALE = 1000.0
SEEDS = (11, 12)
TARGETS = (
    "PR12A", "PR13A", "PR15A", "PR16A", "PR16B", "PR17A", "PR20A",
    "PR22A", "PR23A", "PR24A",
    "PR17B", "PR21B", "PR21A", "PR11B", "PR12B",
)
# Same knobs as P1's frozen engine (K_MOTHER=4000/CAP=240, K_EPOCH=2000/
# CAP=60, MAX_EPOCHS=4, STALL=2, SP_TIME=10), scaled UP for a longer run of
# the IDENTICAL procedure. STALL_EPOCHS is the real stop; MAX_EPOCHS is just
# a raised ceiling so it may keep going while it keeps improving.
K_MOTHER = 8000
CAP_MOTHER = 600.0
K_EPOCH = 4000
CAP_EPOCH = 180.0
MAX_EPOCHS = 8
STALL_EPOCHS = 3
SP_TIME = 15.0
WORKERS = 2
EPS = 1.0e-6


def _opponent_targets() -> dict[str, dict[str, str]]:
    with OPPONENT_CSV.open(encoding="utf-8") as handle:
        return {row["instance"]: row for row in csv.DictReader(handle)}


def _run_unit(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, seed = args
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC)
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    started = perf_counter()

    initial = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    algorithm, population, penalty_manager = _build_algorithm(data, rng, params, initial)
    stop = MultipleCriteria([NoImprovement(K_MOTHER), MaxRuntime(CAP_MOTHER)])
    result = algorithm.run(stop, collect_stats=False, display=False)
    global_best_raw = _solution_cost(result.best)
    best_solution = result.best
    pool: dict[tuple[int, tuple[int, ...]], float] = {}
    elites = _harvest_elites(population, penalty_manager, result.best)
    _pool_add(pool, elites)
    stall = 0
    epochs_run = 0
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        sp_solution, _stats = _solve_sp(data, pool, SP_TIME)
        if sp_solution is not None:
            sp_cost_raw = _solution_cost(sp_solution)
            if sp_cost_raw < global_best_raw - EPS:
                global_best_raw = sp_cost_raw
                best_solution = sp_solution
                improved = True
        warm = [best_solution, *elites]
        unique_warm: dict[tuple[Any, ...], NativeSolution] = {}
        for native in warm:
            unique_warm.setdefault(_solution_key(native), native)
        warm_list = list(unique_warm.values())
        epoch_rng = RandomNumberGenerator(seed=int(seed) + 1009 * (epoch_index + 1))
        random_fill = [
            NativeSolution.make_random(data, epoch_rng)
            for _ in range(max(0, params.population.min_pop_size - len(warm_list)))
        ]
        algorithm, population, penalty_manager = _build_algorithm(
            data, epoch_rng, params, [*warm_list, *random_fill]
        )
        epoch_stop = MultipleCriteria([NoImprovement(K_EPOCH), MaxRuntime(CAP_EPOCH)])
        epoch_result = algorithm.run(epoch_stop, collect_stats=False, display=False)
        epoch_cost_raw = _solution_cost(epoch_result.best)
        if epoch_cost_raw < global_best_raw - EPS:
            global_best_raw = epoch_cost_raw
            best_solution = epoch_result.best
            improved = True
        elites = _harvest_elites(population, penalty_manager, epoch_result.best)
        _pool_add(pool, elites)
        epochs_run += 1
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break

    elapsed = perf_counter() - started
    witness = {
        "instance_id": instance_id,
        "seed": seed,
        "raw_cost_x1000": global_best_raw,
        "cost_double": global_best_raw / SCALE,
        "routes": [
            {
                "vehicle_type": route.vehicle_type(),
                "start_depot": route.start_depot(),
                "visits": list(route.visits()),
                "distance_x1000": float(route.distance()),
            }
            for route in best_solution.routes()
        ],
    }
    witness_path = OUT / f"witness_{instance_id}_seed{seed}.json"
    witness_path.write_text(
        json.dumps(witness, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {
        "instance_id": instance_id,
        "seed": seed,
        "n_clients": data.num_clients,
        "sprint_cost": global_best_raw / SCALE,
        "cpu_seconds": elapsed,
        "epochs_run": epochs_run,
        "witness_file": witness_path.name,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _completed_units(csv_path: Path) -> set[tuple[str, int]]:
    if not csv_path.exists():
        return set()
    with csv_path.open(encoding="utf-8") as handle:
        return {(row["instance_id"], int(row["seed"])) for row in csv.DictReader(handle)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "raw_runs.csv"
    done = _completed_units(csv_path)
    tasks = [
        (instance_id, seed)
        for instance_id in TARGETS
        for seed in SEEDS
        if (instance_id, seed) not in done
    ]
    print(
        f"[P4-SPRINT] {len(done)} done; {len(tasks)} remaining across "
        f"{WORKERS} workers ({len(TARGETS)} targets x {len(SEEDS)} seeds)",
        flush=True,
    )
    fieldnames = [
        "instance_id", "seed", "n_clients", "sprint_cost", "cpu_seconds",
        "epochs_run", "witness_file",
    ]
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        handle.flush()
        if tasks:
            with mp.Pool(processes=WORKERS) as pool:
                for row in pool.imap_unordered(_run_unit, tasks):
                    writer.writerow(row)
                    handle.flush()
                    print(
                        f"[P4-SPRINT] {row['instance_id']} seed={row['seed']} "
                        f"cost={row['sprint_cost']:.3f} cpu={row['cpu_seconds']:.0f}s",
                        flush=True,
                    )
    _finalize(csv_path)
    return 0


def _finalize(csv_path: Path) -> None:
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    targets = _opponent_targets()
    summary: list[dict[str, Any]] = []
    for instance_id in TARGETS:
        matching = [row for row in rows if row["instance_id"] == instance_id]
        if not matching:
            continue
        sprint_best = min(float(row["sprint_cost"]) for row in matching)
        target = targets[instance_id]
        bks = float(target["current_verified_bks"])
        lit_best = min(
            float(target["vcgp_best_2013"]),
            float(target["mdfiha_best_2026"]),
            float(target["mdfiha_etga_best_2026"]),
        )
        summary.append({
            "instance": instance_id,
            "sprint_best": sprint_best,
            "current_verified_bks": bks,
            "strongest_literature": lit_best,
            "beats_literature": sprint_best < lit_best - EPS,
            "new_bks_candidate": sprint_best < bks - EPS,
            "gap_to_bks_pct": 100.0 * (sprint_best - bks) / bks,
        })
    new_bks = [row["instance"] for row in summary if row["new_bks_candidate"]]
    beats_lit = [row["instance"] for row in summary if row["beats_literature"]]
    decision = {
        "schema_version": "resetp.e2-final-campaign.p4-bks-sprint.v1",
        "decision": "P4_BKS_SPRINT_COMPLETE" if len(summary) == len(TARGETS) else "P4_BKS_SPRINT_PARTIAL",
        "targets_complete": len(summary),
        "targets_total": len(TARGETS),
        "new_bks_candidates": new_bks,
        "beats_strongest_literature": beats_lit,
        "summary": summary,
        "claim_boundary": (
            "Sprint uses the IDENTICAL frozen MV-HGS-SP procedure as P1/P3, "
            "differing only in larger compute budget and fresh seeds 11-12 "
            "(no extra stage, no imported mechanism), so any solution is "
            "attributable to the same algorithm in the tables. "
            "new_bks_candidate still requires independent route-certificate "
            "verification (witness JSONs saved per unit) before any formal "
            "new-BKS claim."
        ),
    }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.p4-bks-sprint-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workers": WORKERS,
        "seeds": list(SEEDS),
        "constants": {
            "K_MOTHER": K_MOTHER, "CAP_MOTHER": CAP_MOTHER,
            "K_EPOCH": K_EPOCH, "CAP_EPOCH": CAP_EPOCH,
            "MAX_EPOCHS": MAX_EPOCHS, "STALL_EPOCHS": STALL_EPOCHS,
            "SP_TIME": SP_TIME,
        },
        "engine_note": (
            "Identical frozen MV-HGS-SP procedure as P1/P3; only per-run "
            "compute budget and seeds differ. No extra stage."
        ),
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(
        "\n".join([
            "# P4 BKS 冲刺（预注册目标题，新种子，同一算法长预算版）",
            "",
            "引擎与 P1/P3 完全同构（母体收敛→SP重组轮次），只放大算力预算与种子，非算法改动。",
            "",
            f"机器结论：`{decision['decision']}`。",
            f"压过最强文献值的题：{beats_lit if beats_lit else '无新增'}",
            f"新 BKS 候选：{new_bks if new_bks else '无'}（须路线证书独立复算）。",
            "",
        ]), encoding="utf-8",
    )
    files = [Path(__file__), csv_path, OUT / "metadata.json", OUT / "decision.json", OUT / "report.md"]
    (OUT / "artifact_hashes.json").write_text(
        json.dumps({
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {str(p.relative_to(ROOT)): _sha256(p) for p in files},
        }, ensure_ascii=False, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
