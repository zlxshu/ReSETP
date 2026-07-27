"""K2 kill-test: deepen directly from the 2013 BKS solutions (candidate eps).

Precedent: the POPMUSIC matheuristic literature obtained several of its new
best solutions by starting long runs from the published BKS.  Legitimate, and
reported as such -- warm-started BKS hunting is disclosed separately from the
cold-start main table.

This is simultaneously the sharpest measurement of the one unknown that rules
the whole gamble: how suboptimal the 2013 large-instance BKS actually are.  If
HGS warm-started *at* the BKS cannot improve it within 12,000 iterations, the
BKS is a deep local optimum w.r.t. modern neighbourhoods and the new-BKS goal
is effectively dead; any strict improvement, however small, is an immediate
new BKS candidate for independent certification.

Single process per instance, runs alongside D9's six workers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from k1_depot_reassign_killtest import read_bks_solution  # noqa: E402

from pyvrp import read  # noqa: E402
from pyvrp._pyvrp import RandomNumberGenerator, Solution as NativeSolution  # noqa: E402
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
ITERS = 12_000
EPS = 1.0e-9


def run(instance_id: str, seed: int = 1) -> dict:
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func="exact")
    bks_sol, _vts, bks_raw, cost_line = read_bks_solution(instance_id, data)
    assert abs(bks_raw - cost_line) < 0.5, "BKS verification failed"

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
                            [bks_sol, *fills], params.genetic)
    t0 = perf_counter()
    res = algo.run(MaxIterations(ITERS), collect_stats=False, display=False)
    final_raw = float(sum(r.distance() for r in res.best.routes()))
    improved = final_raw < bks_raw - EPS
    rec = {
        "instance_id": instance_id,
        "seed": seed,
        "bks": bks_raw / SCALE,
        "final": final_raw / SCALE,
        "gain": (bks_raw - final_raw) / SCALE,
        "improved": bool(improved),
        "iterations": int(res.num_iterations),
        "cpu_seconds": round(perf_counter() - t0, 1),
    }
    if improved:
        rec["witness_routes"] = [
            f"{r.vehicle_type()}|" + ",".join(str(v) for v in r.visits())
            for r in res.best.routes()
        ]
    return rec


def main():
    results = []
    for inst in sys.argv[1:] or ["PR24A", "PR16B"]:
        rec = run(inst)
        results.append(rec)
        print(f"  {inst}: BKS={rec['bks']:.3f} -> {rec['final']:.3f} "
              f"gain={rec['gain']:+.3f} iters={rec['iterations']} "
              f"cpu={rec['cpu_seconds']:.0f}s"
              f"{'   *** NEW BKS CANDIDATE ***' if rec['improved'] else ''}",
              flush=True)
    out = OUT / "k2_summary.json"
    existing = json.loads(out.read_text()) if out.is_file() else {"runs": []}
    existing["runs"].extend(results)
    out.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")


if __name__ == "__main__":
    main()
