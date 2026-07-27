"""Can MV-HGS-SP itself reach the new BKS, or only plain warm-started HGS?

The 18 new best solutions came from warm-starting plain PyVRP HGS at the frozen
2013 BKS.  Warm starting is an experimental protocol, not an algorithm, so the
paper's own method is entitled to the same protocol -- but only if it actually
reproduces the result.  This checks that on the single biggest win (PR19A,
-21.543) and one mid win (PR23A, -7.050).

MV-HGS-SP on public instances is HGS plus a route pool and a set-partitioning
layer, so warm-started it should land at least where plain HGS did: the pool
always contains the incumbent's own routes, making the assembly step unable to
return anything worse.
"""
import json, sys
from pathlib import Path
from time import perf_counter
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix

sys.path.insert(0, "baselines/algorithm_prototypes/boundary_probe_20260726")
from k1_depot_reassign_killtest import read_bks_solution

from pyvrp import read
from pyvrp._pyvrp import RandomNumberGenerator, Route as NR, Solution as NS
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp.crossover import ordered_crossover, selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations

ID = Path("baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/sources/normalised_instances")
SCALE = 1000.0

def key(r): return f"{r.vehicle_type()}|" + ",".join(str(v) for v in r.visits())

def epoch(data, warm, seed, iters):
    p = SolveParams(); rng = RandomNumberGenerator(seed=seed)
    fills = [NS.make_random(data, rng) for _ in range(p.population.min_pop_size - 1)]
    ls = LocalSearch(data, rng, compute_neighbours(data, p.neighbourhood))
    for op in p.node_ops:
        if op.supports(data): ls.add_node_operator(op(data))
    for op in p.route_ops:
        if op.supports(data): ls.add_route_operator(op(data))
    pm = PenaltyManager.init_from(data, p.penalty)
    pop = Population(broken_pairs_distance, p.population)
    cx = selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    algo = GeneticAlgorithm(data, pm, rng, pop, ls, cx, [warm, *fills], p.genetic)
    res = algo.run(MaxIterations(iters), collect_stats=False, display=False)
    return res.best, [s for s in pop if s.is_feasible()]

def sp(data, pool, tl=180.0):
    recs = []
    for k, c in pool.items():
        vt, vv = k.split("|", 1)
        recs.append(((int(vt), tuple(int(v) for v in vv.split(",") if v)), c))
    cl = list(range(data.num_depots, data.num_locations)); idx = {c: i for i, c in enumerate(cl)}
    r_, c_ = [], []
    for col, ((_, vis), _) in enumerate(recs):
        for v in vis: r_.append(idx[v]); c_.append(col)
    cov = csc_matrix((np.ones(len(r_)), (r_, c_)), shape=(len(cl), len(recs)))
    vr = [x[0][0] for x in recs]
    veh = csc_matrix((np.ones(len(vr)), (vr, range(len(recs)))), shape=(data.num_vehicle_types, len(recs)))
    ub = np.array([float(data.vehicle_type(t).num_available) for t in range(data.num_vehicle_types)])
    res = milp(c=np.array([c for _, c in recs]), integrality=np.ones(len(recs)),
               bounds=Bounds(np.zeros(len(recs)), np.ones(len(recs))),
               constraints=[LinearConstraint(cov, lb=np.ones(len(cl)), ub=np.ones(len(cl))),
                            LinearConstraint(veh, lb=-np.inf*np.ones(len(ub)), ub=ub)],
               options={"time_limit": tl})
    if res.x is None: return None
    ch = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    s = NS(data, [NR(data, list(vis), vt) for (vt, vis), _ in ch])
    return s if s.is_feasible() else None

for inst, target in (("PR19A", 10499.569), ("PR23A", 9719.108)):
    data = read(str(ID / f"{inst}.vrp"), round_func="exact")
    bks_sol, _v, bks_raw, _c = read_bks_solution(inst, data)
    t0 = perf_counter()
    best, best_raw = bks_sol, bks_raw
    pool = {}
    for ep in range(3):
        s, popn = epoch(data, best, 1 + ep, 12000)
        for x in popn + [s]:
            for r in x.routes(): pool.setdefault(key(r), float(r.distance()))
        if float(sum(r.distance() for r in s.routes())) < best_raw:
            best = s; best_raw = float(sum(r.distance() for r in s.routes()))
        a = sp(data, pool)
        if a is not None:
            ac = float(sum(r.distance() for r in a.routes()))
            if ac < best_raw: best, best_raw = a, ac
    print(f"{inst}: 2013BKS={bks_raw/SCALE:.3f}  纯HGS热启动={target:.3f}  "
          f"MV-HGS-SP热启动={best_raw/SCALE:.3f}  "
          f"{'达标' if best_raw/SCALE <= target + 1e-6 else '未达标'}  "
          f"cpu={perf_counter()-t0:.0f}s", flush=True)
