"""K1 kill-test: exact route-depot reassignment (candidate delta).

Finding that motivates this: PyVRP 0.12.2 disables its only depot-changing
node operator (RelocateWithDepot, supports=False) on the V13 instances, so
depot assignment is explored solely through crossover accidents.  Depot choice
is the one dimension that makes MDVRPTW different from plain VRP.

The move: keep every route's client sequence fixed; re-decide which depot each
route hangs on, as a capacity-constrained assignment solved exactly (tiny MILP,
33 routes x 12 depots).  One step jumps across 12^33 combinations.

Targets, in order of prize size:
  1. the frozen 2013 BKS solutions of the four large instances -- any strict
     improvement here is an immediate new BKS;
  2. the current best D9 solution (PR24A seed4) -- tests whether the mechanism
     has bite on our own solutions even if the BKS is depot-optimal.

Read-only; seconds of compute; every cost re-verified through PyVRP routes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix

from pyvrp import read
from pyvrp._pyvrp import Route as NativeRoute, Solution as NativeSolution

ROOT = Path(__file__).resolve().parents[3]
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
BKS_DIR = FOUNDATION / "sources/current_bks"
OUT = Path(__file__).resolve().parent
SCALE = 1000.0
EPS = 1.0e-9

LARGE = ["PR16A", "PR16B", "PR20A", "PR24A"]


def read_bks_solution(instance_id, data):
    """Parse .sol into (routes as PyVRP visits, vehicle_type per route)."""
    lines = (BKS_DIR / f"{instance_id}.sol").read_text().splitlines()
    routes, cost_line = [], None
    for line in lines:
        if line.startswith("Route"):
            routes.append([int(t) for t in line.split(":", 1)[1].split()])
        elif line.lower().startswith("cost"):
            cost_line = float(line.split()[-1])
    # vehicle k <-> route k; VEHICLES_DEPOT_SECTION maps vehicle -> depot node
    vrp = (INSTANCE_DIR / f"{instance_id}.vrp").read_text().splitlines()
    vehicle_depot, in_sec = [], False
    for line in vrp:
        s = line.strip()
        if s == "VEHICLES_DEPOT_SECTION":
            in_sec = True; continue
        if in_sec:
            if s.endswith("SECTION") or s == "EOF":
                break
            parts = s.split()
            if len(parts) >= 2:
                vehicle_depot.append(int(parts[1]))
    # .sol may number clients 1..n_clients (client ordinal) or by file node id
    # (depots first).  Try both offsets; the one whose total matches the Cost
    # line bit-for-bit wins.
    nd = data.num_depots
    best = None
    # PyVRP-normalised .sol files use PyVRP indices directly (offset 0);
    # keep the other offsets as fallbacks for older formats.
    for offset in (0, nd - 1, -1):
        try:
            native, vts = [], []
            for k, sol_route in enumerate(routes):
                if not sol_route:          # empty Route line: vehicle unused
                    continue
                visits = [v + offset for v in sol_route]
                vt = vehicle_depot[k] - 1
                native.append(NativeRoute(data, visits, vt))
                vts.append(vt)
            sol = NativeSolution(data, native)
            total = float(sum(r.distance() for r in sol.routes()))
            if abs(total - cost_line) < 0.5:
                return sol, vts, total, cost_line
            if best is None:
                best = (sol, vts, total, cost_line)
        except ValueError:
            continue
    if best is None:
        raise ValueError(f"no offset maps {instance_id} onto valid clients")
    return best


def reassign(data, route_visits, current_vts):
    """Exact capacity-constrained route->depot assignment. Returns new cost."""
    n_routes = len(route_visits)
    n_types = data.num_vehicle_types
    cost = np.full((n_routes, n_types), np.inf)
    for i, visits in enumerate(route_visits):
        for t in range(n_types):
            r = NativeRoute(data, visits, t)
            if r.is_feasible():
                cost[i, t] = float(r.distance())
    # milp over x[i,t]
    nv = n_routes * n_types
    c = cost.flatten()
    big = np.isinf(c)
    c[big] = 1e15
    rows_a, cols_a = [], []
    for i in range(n_routes):
        for t in range(n_types):
            rows_a.append(i); cols_a.append(i * n_types + t)
    A_assign = csc_matrix((np.ones(len(rows_a)), (rows_a, cols_a)),
                          shape=(n_routes, nv))
    rows_c, cols_c = [], []
    for i in range(n_routes):
        for t in range(n_types):
            rows_c.append(t); cols_c.append(i * n_types + t)
    A_cap = csc_matrix((np.ones(len(rows_c)), (rows_c, cols_c)),
                       shape=(n_types, nv))
    caps = np.array([float(data.vehicle_type(t).num_available)
                     for t in range(n_types)])
    ub = np.ones(nv)
    ub[big] = 0.0
    res = milp(c=c, integrality=np.ones(nv),
               bounds=Bounds(np.zeros(nv), ub),
               constraints=[
                   LinearConstraint(A_assign, lb=np.ones(n_routes), ub=np.ones(n_routes)),
                   LinearConstraint(A_cap, lb=-np.inf * np.ones(n_types), ub=caps)],
               options={"time_limit": 60.0})
    if res.x is None:
        return None, None
    x = res.x.reshape(n_routes, n_types)
    new_vts = [int(np.argmax(row)) for row in x]
    new_cost = float(sum(cost[i, new_vts[i]] for i in range(n_routes)))
    return new_cost, new_vts


def main():
    results = {}
    print("=== delta on 2013 BKS solutions (any improvement = NEW BKS) ===")
    for inst in LARGE:
        data = read(str(INSTANCE_DIR / f"{inst}.vrp"), round_func="exact")
        sol, vts, total, cost_line = read_bks_solution(inst, data)
        ok = abs(total - cost_line) < 0.5 and sol.is_feasible()
        visits = [list(r.visits()) for r in sol.routes()]
        new_cost, new_vts = reassign(data, visits, vts)
        gain = total - new_cost if new_cost else 0.0
        moved = sum(1 for a, b in zip(vts, new_vts) if a != b) if new_vts else 0
        results[inst] = {"bks_verify_ok": bool(ok), "bks_cost": total / SCALE,
                         "reassigned_cost": new_cost / SCALE if new_cost else None,
                         "gain": gain / SCALE, "routes_moved": moved}
        print(f"  {inst}: 复算={'OK' if ok else 'FAIL'} "
              f"BKS={total/SCALE:.3f} 再分配后={new_cost/SCALE:.3f} "
              f"赚={gain/SCALE:+.3f} 移动路线数={moved}"
              f"{'   *** NEW BKS ***' if gain > EPS else ''}")

    print("\n=== delta on current D9 best (PR24A seed4) ===")
    f = OUT / "d9_runs" / "PR24A__s4.json"
    if f.is_file():
        rec = json.loads(f.read_text(encoding="utf-8"))
        data = read(str(INSTANCE_DIR / "PR24A.vrp"), round_func="exact")
        visits, vts = [], []
        for key in rec["best_routes"]:
            vt, vv = key.split("|", 1)
            visits.append([int(v) for v in vv.split(",") if v])
            vts.append(int(vt))
        base = sum(float(NativeRoute(data, v, t).distance())
                   for v, t in zip(visits, vts))
        new_cost, new_vts = reassign(data, visits, vts)
        gain = base - new_cost if new_cost else 0.0
        moved = sum(1 for a, b in zip(vts, new_vts) if a != b) if new_vts else 0
        results["D9_PR24A_s4"] = {"base": base / SCALE,
                                  "reassigned": new_cost / SCALE if new_cost else None,
                                  "gain": gain / SCALE, "routes_moved": moved}
        print(f"  base={base/SCALE:.3f} 再分配后={new_cost/SCALE:.3f} "
              f"赚={gain/SCALE:+.3f} 移动路线数={moved}")

    (OUT / "k1_summary.json").write_text(
        json.dumps({"schema": "resetp.killtest.k1-depot-reassign.v1", **results},
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
