"""K4: epsilon expansion -- iterate the warm-start mining.

Two certified new BKS came out of single 12,000-iteration warm starts (PR24A
-4.153, PR16A -1.661).  This round mines deeper: restart from the NEW solutions
(the vein may continue), and give the two unmoved instances (PR16B, PR20A) a
deeper, differently-seeded attempt.  Two workers alongside D9's six.
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
SCALE = 1000.0
EPS = 1.0e-9

# (instance, start: "bks"|"best_witness", seed, iters)
TASKS = [
    ("PR24A", "best_witness", 2, 24_000),
    ("PR16A", "best_witness", 2, 24_000),
    ("PR16B", "bks", 2, 36_000),
    ("PR20A", "bks", 2, 36_000),
]


def best_witness(instance_id, data):
    """Best improved witness recorded so far (k2 + k4 summaries)."""
    cands = []
    for name in ("k2_summary.json", "k4_summary.json"):
        f = OUT / name
        if f.is_file():
            for r in json.loads(f.read_text(encoding="utf-8"))["runs"]:
                if r["instance_id"] == instance_id and r.get("witness_routes"):
                    cands.append(r)
    if not cands:
        return None, None
    rec = min(cands, key=lambda r: r["final"])
    routes = []
    for key in rec["witness_routes"]:
        vt, vv = key.split("|", 1)
        routes.append(NativeRoute(data, [int(v) for v in vv.split(",") if v],
                                  int(vt)))
    return NativeSolution(data, routes), rec["final"] * SCALE


def run(task):
    instance_id, start, seed, iters = task
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func="exact")
    if start == "best_witness":
        sol, start_raw = best_witness(instance_id, data)
        if sol is None:
            start = "bks"
    if start == "bks":
        sol, _vts, start_raw, cl = read_bks_solution(instance_id, data)
        assert abs(start_raw - cl) < 0.5
    bks_sol, _v, bks_raw, _c = read_bks_solution(instance_id, data)

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
    improved_vs_bks = final_raw < bks_raw - EPS
    rec = {
        "instance_id": instance_id, "start": start, "seed": seed,
        "iters": iters, "start_cost": start_raw / SCALE,
        "bks": bks_raw / SCALE, "final": final_raw / SCALE,
        "gain_vs_start": (start_raw - final_raw) / SCALE,
        "gain_vs_bks": (bks_raw - final_raw) / SCALE,
        "improved_vs_bks": bool(improved_vs_bks),
        "cpu_seconds": round(perf_counter() - t0, 1),
    }
    if final_raw < start_raw - EPS or improved_vs_bks:
        rec["witness_routes"] = [
            f"{r.vehicle_type()}|" + ",".join(str(v) for v in r.visits())
            for r in res.best.routes()]
    return rec


def main():
    results = []
    with ProcessPoolExecutor(max_workers=2) as ex:
        for rec in ex.map(run, TASKS):
            results.append(rec)
            print(f"  {rec['instance_id']} {rec['start']}/s{rec['seed']}/"
                  f"{rec['iters']}: start={rec['start_cost']:.3f} -> "
                  f"final={rec['final']:.3f}  vsBKS={rec['gain_vs_bks']:+.3f}"
                  f"{'   *** BELOW BKS ***' if rec['improved_vs_bks'] else ''}",
                  flush=True)
    out = OUT / "k4_summary.json"
    existing = json.loads(out.read_text()) if out.is_file() else {"runs": []}
    existing["runs"].extend(results)
    out.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")


if __name__ == "__main__":
    main()
