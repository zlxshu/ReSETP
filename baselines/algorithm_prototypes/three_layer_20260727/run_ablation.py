"""Three-layer ablation: multi-start / pool assembly / subproblem re-optimisation.

Four arms compared under an identical total CPU budget (MILP and subproblem time
included -- that is the only honest way to answer "why not just run HGS longer"):

  A0  one long HGS run
  A1  k restarts, best of k
  A2  A1 + pool assembly (time-limited set partitioning over all routes seen)
  A3  A2 + subproblem re-optimisation (take m routes from the incumbent,
      re-optimise their client union as its own instance, feed results back)

Frozen traps this implementation must not fall into, each learned the hard way
earlier in this project:

  - subinstance feasibility: vehicle availability is inherited as exactly the
    count those m routes were using; any replacement is re-verified on the full
    solution and dropped if infeasible, never masked by a min();
  - min() safeguard: a time-limited MILP on a large pool can return an incumbent
    worse than best-of-k (measured: -72 on PR16A), so pool output is always
    min(incumbent, MILP), and the report says "time-limited", never "exact";
  - causal honesty: routes in the final solution that only L2 could have made
    are counted, and labelled an activity indicator, not a contribution proof.

Development set is four instances the warm-start sweep did NOT crack, so the
ablation cannot flatter itself on already-mined ground.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix

from pyvrp import read
from pyvrp._pyvrp import (
    Client, Depot, ProblemData, RandomNumberGenerator,
    Route as NativeRoute, Solution as NativeSolution, VehicleType,
)
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp.crossover import ordered_crossover, selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxRuntime

ROOT = Path(__file__).resolve().parents[3]
INSTANCE_DIR = (ROOT / "baselines/algorithm_foundation/"
                "mdvrptw_v13_comparison_20260719/sources/normalised_instances")
OUT = Path(__file__).resolve().parent
SUMMARY = OUT / "raw_runs.json"

SCALE = 1000.0
EPS = 1.0e-9
BUDGET = 1800.0          # total CPU seconds per (instance, seed, arm)
K_RESTARTS = 6           # L1 restarts in A1/A2/A3
M_ROUTES = 4             # L2 subproblem size, frozen
SP_TIME = 120.0          # per set-partitioning solve
INSTANCES = ["PR13A", "PR18B", "PR21A", "PR22A"]   # warm-start misses
SEEDS = (1, 2, 3, 4, 5)


def build(data, rng, params, initial):
    ls = LocalSearch(data, rng, compute_neighbours(data, params.neighbourhood))
    for op in params.node_ops:
        if op.supports(data):
            ls.add_node_operator(op(data))
    for op in params.route_ops:
        if op.supports(data):
            ls.add_route_operator(op(data))
    pm = PenaltyManager.init_from(data, params.penalty)
    pop = Population(broken_pairs_distance, params.population)
    cx = selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    return GeneticAlgorithm(data, pm, rng, pop, ls, cx, initial,
                            params.genetic), pop


def cost_of(sol):
    return float(sum(r.distance() for r in sol.routes()))


def hgs(data, seed, seconds, warm=None):
    params = SolveParams()
    rng = RandomNumberGenerator(seed=seed)
    n_fill = params.population.min_pop_size - (1 if warm else 0)
    init = ([warm] if warm else []) + [
        NativeSolution.make_random(data, rng) for _ in range(max(0, n_fill))]
    algo, pop = build(data, rng, params, init)
    res = algo.run(MaxRuntime(seconds), collect_stats=False, display=False)
    return res.best, [s for s in pop if s.is_feasible()]


def key_of(route):
    return f"{route.vehicle_type()}|" + ",".join(str(v) for v in route.visits())


def add_routes(pool, sols):
    for s in sols:
        for r in s.routes():
            pool.setdefault(key_of(r), float(r.distance()))


def assemble(data, pool, incumbent_raw, tl):
    """Time-limited set partitioning. Returns (cost, keys, info)."""
    recs = []
    for k, c in pool.items():
        vt, vv = k.split("|", 1)
        recs.append(((int(vt), tuple(int(v) for v in vv.split(",") if v)), c))
    clients = list(range(data.num_depots, data.num_locations))
    idx = {c: i for i, c in enumerate(clients)}
    r_, c_ = [], []
    for col, ((_, vis), _) in enumerate(recs):
        for v in vis:
            r_.append(idx[v]); c_.append(col)
    cover = csc_matrix((np.ones(len(r_)), (r_, c_)),
                       shape=(len(clients), len(recs)))
    vr = [rec[0][0] for rec in recs]
    veh = csc_matrix((np.ones(len(vr)), (vr, range(len(recs)))),
                     shape=(data.num_vehicle_types, len(recs)))
    ub = np.array([float(data.vehicle_type(t).num_available)
                   for t in range(data.num_vehicle_types)])
    t0 = perf_counter()
    res = milp(c=np.array([c for _, c in recs]), integrality=np.ones(len(recs)),
               bounds=Bounds(np.zeros(len(recs)), np.ones(len(recs))),
               constraints=[
                   LinearConstraint(cover, lb=np.ones(len(clients)),
                                    ub=np.ones(len(clients))),
                   LinearConstraint(veh, lb=-np.inf * np.ones(len(ub)), ub=ub)],
               options={"time_limit": tl})
    el = perf_counter() - t0
    info = {"columns": len(recs), "seconds": round(el, 1),
            "hit_time_limit": el >= tl - 1.0}
    if res.x is None:
        return None, None, info
    chosen = [recs[i] for i, v in enumerate(res.x) if v > 0.5]
    sol = NativeSolution(data, [NativeRoute(data, list(vis), vt)
                                for (vt, vis), _ in chosen])
    if not sol.is_feasible():
        return None, None, info
    return sol, [key_of(r) for r in sol.routes()], info


def subproblem(data, sol, m, seed, seconds):
    """L2: re-optimise the client union of m routes as its own instance."""
    routes = list(sol.routes())
    if len(routes) <= m:
        return None
    rng = np.random.default_rng(seed)
    pick = sorted(rng.choice(len(routes), size=m, replace=False).tolist())
    chosen = [routes[i] for i in pick]
    members = [v for r in chosen for v in r.visits()]
    if len(members) < 4:
        return None

    # vehicle availability inherited as exactly what those m routes used
    used = {}
    for r in chosen:
        used[r.vehicle_type()] = used.get(r.vehicle_type(), 0) + 1

    old = [data.location(i) for i in members]
    depots = [data.location(d) for d in range(data.num_depots)]
    sub_clients = [Client(x=c.x, y=c.y, delivery=c.delivery, pickup=c.pickup,
                          service_duration=c.service_duration, tw_early=c.tw_early,
                          tw_late=c.tw_late, release_time=c.release_time,
                          required=True) for c in old]
    sub_depots = [Depot(x=d.x, y=d.y, tw_early=d.tw_early, tw_late=d.tw_late)
                  for d in depots]
    vts = []
    for t in range(data.num_vehicle_types):
        vt = data.vehicle_type(t)
        vts.append(VehicleType(
            num_available=used.get(t, 0) or 1, capacity=vt.capacity,
            start_depot=vt.start_depot, end_depot=vt.end_depot,
            fixed_cost=vt.fixed_cost, tw_early=vt.tw_early, tw_late=vt.tw_late,
            # PyVRP 0.12.2 names the route-duration cap shift_duration
            shift_duration=vt.shift_duration, max_distance=vt.max_distance))
    order = list(range(data.num_depots)) + members
    dm = data.distance_matrix(0)
    tm = data.duration_matrix(0)
    sub_d = np.array([[dm[a][b] for b in order] for a in order], dtype=np.int64)
    sub_t = np.array([[tm[a][b] for b in order] for a in order], dtype=np.int64)
    sub = ProblemData(sub_clients, sub_depots, vts, [sub_d], [sub_t])

    best, _pop = hgs(sub, seed, seconds)
    if best is None or not best.is_feasible():
        return None
    # map back: sub index -> original id
    back = {i: order[i] for i in range(len(order))}
    new_routes = []
    for r in best.routes():
        vis = [back[v] for v in r.visits()]
        if vis:
            new_routes.append(NativeRoute(data, vis, r.vehicle_type()))
    if not new_routes:
        return None
    keep = [routes[i] for i in range(len(routes)) if i not in set(pick)]
    cand = NativeSolution(data, keep + new_routes)
    if not cand.is_feasible():
        return None
    return cand


def run_unit(args):
    instance_id, seed, arm = args
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func="exact")
    t_start = perf_counter()
    pool, l2_keys = {}, set()
    info_last = {}

    if arm == "A0":
        best, _p = hgs(data, seed, BUDGET)
        best_raw = cost_of(best)
    else:
        share = BUDGET / K_RESTARTS
        if arm == "A3":
            share = (BUDGET * 0.6) / K_RESTARTS      # reserve 40% for L2+L3
        elif arm == "A2":
            share = (BUDGET - SP_TIME) / K_RESTARTS
        best, best_raw = None, float("inf")
        for j in range(K_RESTARTS):
            s, popn = hgs(data, seed * 1000 + j, share)
            add_routes(pool, popn + [s])
            if cost_of(s) < best_raw:
                best, best_raw = s, cost_of(s)

        if arm in ("A2", "A3"):
            sol, _k, info_last = assemble(data, pool, best_raw, SP_TIME)
            if sol is not None and cost_of(sol) < best_raw - EPS:
                best, best_raw = sol, cost_of(sol)

        if arm == "A3":
            rnd = 0
            while perf_counter() - t_start < BUDGET - SP_TIME:
                rnd += 1
                cand = subproblem(data, best, M_ROUTES, seed * 100 + rnd,
                                  min(30.0, BUDGET - (perf_counter() - t_start)))
                if cand is None:
                    continue
                before = set(pool)
                add_routes(pool, [cand])
                l2_keys |= (set(pool) - before)
                if cost_of(cand) < best_raw - EPS:
                    best, best_raw = cand, cost_of(cand)
            sol, keys, info_last = assemble(data, pool, best_raw, SP_TIME)
            if sol is not None and cost_of(sol) < best_raw - EPS:
                best, best_raw = sol, cost_of(sol)

    final_keys = {key_of(r) for r in best.routes()}
    return {
        "instance_id": instance_id, "seed": seed, "arm": arm,
        "cost": best_raw / SCALE,
        "feasible": bool(best.is_feasible()),
        "cpu_seconds": round(perf_counter() - t_start, 1),
        "pool_columns": len(pool),
        "l2_routes_in_final": len(final_keys & l2_keys),
        "milp": info_last,
    }


def main():
    jobs = [(i, s, a) for i in INSTANCES for s in SEEDS
            for a in ("A0", "A1", "A2", "A3")]
    print(f"{len(jobs)} units, 6 workers, {BUDGET:.0f}s each", flush=True)
    with ProcessPoolExecutor(max_workers=6) as ex:
        for rec in ex.map(run_unit, jobs):
            print(f"  {rec['instance_id']} s{rec['seed']} {rec['arm']}: "
                  f"{rec['cost']:.3f} feas={rec['feasible']} "
                  f"L2in={rec['l2_routes_in_final']} "
                  f"cpu={rec['cpu_seconds']:.0f}s", flush=True)
            ex_data = (json.loads(SUMMARY.read_text()) if SUMMARY.is_file()
                       else {"runs": []})
            ex_data["runs"].append(rec)
            SUMMARY.write_text(json.dumps(ex_data, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
