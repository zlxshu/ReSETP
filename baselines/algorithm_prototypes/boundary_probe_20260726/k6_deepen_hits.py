"""K6: second-pass deepening on instances already below BKS.

PR16A proved the vein continues: a second warm start from the *new* solution
took it from 13991.020 to 13987.948.  This re-mines every certified hit the
same way, using the two cores K5's six workers leave idle.

Each pass warm-starts from the best witness recorded across all rounds, with a
fresh seed and a deeper budget, and appends to k6_summary.json incrementally so
a process restart cannot lose the work.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from k1_depot_reassign_killtest import read_bks_solution  # noqa: E402

from pyvrp import read  # noqa: E402
from pyvrp._pyvrp import (  # noqa: E402
    RandomNumberGenerator, Route as NativeRoute, Solution as NativeSolution,
)
from pyvrp.GeneticAlgorithm import GeneticAlgorithm  # noqa: E402
from pyvrp.PenaltyManager import PenaltyManager  # noqa: E402
from pyvrp.Population import Population  # noqa: E402
from pyvrp.crossover import ordered_crossover, selective_route_exchange  # noqa: E402
from pyvrp.diversity import broken_pairs_distance  # noqa: E402
from pyvrp.search import LocalSearch, compute_neighbours  # noqa: E402
from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp.stop import MaxIterations  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
INSTANCE_DIR = (ROOT / "baselines/algorithm_foundation/"
                "mdvrptw_v13_comparison_20260719/sources/normalised_instances")
OUT = Path(__file__).resolve().parent
SUMMARY = OUT / "k6_summary.json"
SCALE = 1000.0
EPS = 1.0e-9
SUMMARIES = ("k2_summary.json", "k4_summary.json", "k5_summary.json",
             "k6_summary.json")


def best_witness(instance_id, data):
    best = None
    for name in SUMMARIES:
        f = OUT / name
        if not f.is_file():
            continue
        for r in json.loads(f.read_text(encoding="utf-8"))["runs"]:
            if r["instance_id"] == instance_id and r.get("witness_routes"):
                if best is None or r["final"] < best["final"]:
                    best = r
    if best is None:
        return None, None
    routes = [NativeRoute(data, [int(v) for v in vv.split(",") if v], int(vt))
              for vt, vv in (k.split("|", 1) for k in best["witness_routes"])]
    return NativeSolution(data, routes), best["final"] * SCALE


def run(task):
    instance_id, seed, iters = task
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func="exact")
    sol, start_raw = best_witness(instance_id, data)
    if sol is None:
        sol, _v, start_raw, _c = read_bks_solution(instance_id, data)
    _bs, _v2, bks_raw, _c2 = read_bks_solution(instance_id, data)

    params = SolveParams()
    rng = RandomNumberGenerator(seed=seed)
    fills = [NativeSolution.make_random(data, rng)
             for _ in range(max(0, params.population.min_pop_size - 1))]
    ls = LocalSearch(data, rng, compute_neighbours(data, params.neighbourhood))
    for op in params.node_ops:
        if op.supports(data):
            ls.add_node_operator(op(data))
    for op in params.route_ops:
        if op.supports(data):
            ls.add_route_operator(op(data))
    pm = PenaltyManager.init_from(data, params.penalty)
    pop = Population(broken_pairs_distance, params.population)
    crossover = (selective_route_exchange
                 if data.num_vehicles > 1 else ordered_crossover)
    algo = GeneticAlgorithm(data, pm, rng, pop, ls, crossover,
                            [sol, *fills], params.genetic)
    t0 = perf_counter()
    res = algo.run(MaxIterations(iters), collect_stats=False, display=False)
    final_raw = float(sum(r.distance() for r in res.best.routes()))
    rec = {
        "instance_id": instance_id, "seed": seed, "iters": iters,
        "start_cost": start_raw / SCALE, "bks": bks_raw / SCALE,
        "final": min(final_raw, start_raw) / SCALE,
        "gain_vs_start": (start_raw - final_raw) / SCALE,
        "gain_vs_bks": (bks_raw - min(final_raw, start_raw)) / SCALE,
        "improved_vs_bks": bool(min(final_raw, start_raw) < bks_raw - EPS),
        "cpu_seconds": round(perf_counter() - t0, 1),
    }
    if final_raw < start_raw - EPS:
        rec["witness_routes"] = [
            f"{r.vehicle_type()}|" + ",".join(str(v) for v in r.visits())
            for r in res.best.routes()]
    return rec


def main():
    hits = ["PR14A", "PR16A", "PR24A", "PR14B", "PR13B", "PR20A", "PR16B",
            "PR12A"]
    tasks = [(i, 3, 40_000) for i in hits]
    print(f"K6 deepening {len(tasks)} certified hits, 2 workers", flush=True)
    with ProcessPoolExecutor(max_workers=2) as ex:
        for rec in ex.map(run, tasks):
            tag = ("  *** DEEPER ***" if rec["gain_vs_start"] > EPS else "")
            print(f"  {rec['instance_id']:<7} start={rec['start_cost']:>10.3f}"
                  f" -> {rec['final']:>10.3f}  vsBKS={rec['gain_vs_bks']:+8.3f}"
                  f"{tag}", flush=True)
            ex_data = (json.loads(SUMMARY.read_text(encoding="utf-8"))
                       if SUMMARY.is_file() else {"runs": []})
            ex_data["runs"].append(rec)
            SUMMARY.write_text(
                json.dumps(ex_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")


if __name__ == "__main__":
    main()
