"""K5: sweep the warm-start mining across all 28 V13 instances.

Four for four on the large band, every one independently certified, and PR16A
kept giving on a second pass -- so the vein is not a large-instance quirk.  This
runs the same procedure over the whole benchmark: warm start from the frozen
2013 BKS, iterate from any improved witness, and record everything.

Per instance: two passes, seed 1 then seed 2, the second starting from the best
witness found so far.  Iterations scale with size so small instances are not
starved of the depth they need.
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
SUMMARY = OUT / "k5_summary.json"
SCALE = 1000.0
EPS = 1.0e-9

ALL = [f"PR{n:02d}{s}" for n in (11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                                 21, 22, 23, 24) for s in ("A", "B")]
# already mined in k2/k4
DONE = {"PR24A", "PR16A", "PR16B", "PR20A"}
import json as _json
if SUMMARY.is_file():
    DONE |= {r["instance_id"]
             for r in _json.loads(SUMMARY.read_text(encoding="utf-8"))["runs"]}
TARGETS = [i for i in ALL if i not in DONE]


def load_prior(instance_id, data):
    best = None
    for name in ("k2_summary.json", "k4_summary.json", "k5_summary.json"):
        f = OUT / name
        if not f.is_file():
            continue
        for r in json.loads(f.read_text(encoding="utf-8"))["runs"]:
            if r["instance_id"] == instance_id and r.get("witness_routes"):
                if best is None or r["final"] < best["final"]:
                    best = r
    if best is None:
        return None, None
    routes = []
    for key in best["witness_routes"]:
        vt, vv = key.split("|", 1)
        routes.append(NativeRoute(data, [int(v) for v in vv.split(",") if v],
                                  int(vt)))
    return NativeSolution(data, routes), best["final"] * SCALE


def one_pass(data, start_sol, seed, iters):
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
                            [start_sol, *fills], params.genetic)
    res = algo.run(MaxIterations(iters), collect_stats=False, display=False)
    return res.best, float(sum(r.distance() for r in res.best.routes()))


def run(instance_id):
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func="exact")
    bks_sol, _v, bks_raw, cl = read_bks_solution(instance_id, data)
    assert abs(bks_raw - cl) < 0.5, f"{instance_id} BKS verify failed"
    n = data.num_clients
    iters = 30_000 if n <= 500 else 18_000
    t0 = perf_counter()

    cur_sol, cur_raw = bks_sol, bks_raw
    out = []
    for seed in (1, 2):
        sol, raw = one_pass(data, cur_sol, seed, iters)
        if raw < cur_raw - EPS:
            cur_sol, cur_raw = sol, raw
        out.append((seed, raw))

    rec = {
        "instance_id": instance_id, "clients": n, "iters_per_pass": iters,
        "bks": bks_raw / SCALE, "final": cur_raw / SCALE,
        "gain_vs_bks": (bks_raw - cur_raw) / SCALE,
        "improved_vs_bks": bool(cur_raw < bks_raw - EPS),
        "passes": [{"seed": s, "cost": r / SCALE} for s, r in out],
        "cpu_seconds": round(perf_counter() - t0, 1),
    }
    if rec["improved_vs_bks"]:
        rec["witness_routes"] = [
            f"{r.vehicle_type()}|" + ",".join(str(v) for v in r.visits())
            for r in cur_sol.routes()]
    return rec


def main():
    print(f"K5 sweep over {len(TARGETS)} instances, 6 workers", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=6) as ex:
        for rec in ex.map(run, TARGETS):
            results.append(rec)
            print(f"  {rec['instance_id']:<7} n={rec['clients']:<4} "
                  f"BKS={rec['bks']:>10.3f} -> {rec['final']:>10.3f} "
                  f"gain={rec['gain_vs_bks']:+8.3f} "
                  f"cpu={rec['cpu_seconds']:.0f}s"
                  f"{'  *** BELOW BKS ***' if rec['improved_vs_bks'] else ''}",
                  flush=True)
            existing = (json.loads(SUMMARY.read_text(encoding="utf-8"))
                        if SUMMARY.is_file() else {"runs": []})
            existing["runs"].append(rec)
            SUMMARY.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
    hits = [r for r in results if r["improved_vs_bks"]]
    print(f"\n新 BKS 命中 {len(hits)}/{len(results)}")


if __name__ == "__main__":
    main()
