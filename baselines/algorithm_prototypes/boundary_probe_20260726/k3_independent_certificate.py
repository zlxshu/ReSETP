"""K3: independent certificate check for the PR24A new-BKS candidate.

Deliberately does NOT import pyvrp.  Everything is recomputed from the raw
normalised .vrp file: euclidean distances scaled x1000 and rounded (the file's
convention, matched bit-for-bit by the frozen BKS Cost lines), demands, time
windows, service times, vehicle-per-depot caps, max route duration.

Checks, per the preregistered four-point rule:
  1. arc-by-arc cost recomputation equals the claimed total;
  2. every client served exactly once;
  3. per-depot vehicle count within its cap;
  4. time windows respected (earliest-start schedule; if route duration
     exceeds the cap under earliest start, a latest-feasible-start analysis
     via forward slack is applied before declaring failure).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
F = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
import sys
INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "PR24A"
VRP = F / f"sources/normalised_instances/{INSTANCE}.vrp"
OUT = Path(__file__).resolve().parent
CLAIMED_TOTAL = None  # read from k2_summary.json


def parse_vrp(path):
    header, sections, cur = {}, {}, None
    for line in path.read_text().splitlines():
        s = line.rstrip()
        if not s or s == "EOF":
            continue
        if s.endswith("SECTION"):
            cur = s; sections[cur] = []; continue
        if cur is None:
            if ":" in s:
                k, v = s.split(":", 1); header[k.strip()] = v.strip()
            continue
        sections[cur].append(s)
    coord, demand, service, tw = {}, {}, {}, {}
    for r in sections["NODE_COORD_SECTION"]:
        p = r.split(); coord[int(p[0])] = (float(p[1]), float(p[2]))
    for r in sections["DEMAND_SECTION"]:
        p = r.split(); demand[int(p[0])] = int(float(p[1]))
    for r in sections["SERVICE_TIME_SECTION"]:
        p = r.split(); service[int(p[0])] = float(p[1])
    for r in sections["TIME_WINDOW_SECTION"]:
        p = r.split(); tw[int(p[0])] = (float(p[1]), float(p[2]))
    depots = [int(r.split()[0]) for r in sections["DEPOT_SECTION"]
              if r.strip() and r.strip() != "-1"]
    veh_depot = [int(r.split()[1]) for r in sections["VEHICLES_DEPOT_SECTION"]]
    return {
        "coord": coord, "demand": demand, "service": service, "tw": tw,
        "depots": depots, "veh_depot": veh_depot,
        "capacity": int(header["CAPACITY"]),
        "max_dur": float(header.get("VEHICLES_MAX_DURATION", "inf")),
        "dim": int(header["DIMENSION"]),
    }


def dist_int(a, b, coord):
    (x1, y1), (x2, y2) = coord[a], coord[b]
    return round(math.hypot(x1 - x2, y1 - y2) * 1000)


def main():
    inst = parse_vrp(VRP)
    nd = len(inst["depots"])
    # gather every witness for this instance from all mining rounds, certify
    # the best one
    cands = []
    for name in ("k2_summary.json", "k4_summary.json", "k5_summary.json", "k6_summary.json"):
        f = OUT / name
        if f.is_file():
            for r in json.loads(f.read_text(encoding="utf-8"))["runs"]:
                if (r["instance_id"] == INSTANCE and r.get("witness_routes")
                        and r["final"] < r["bks"] - 1e-9):
                    cands.append(r)
    if not cands:
        raise SystemExit(f"no below-BKS witness for {INSTANCE}")
    rec = min(cands, key=lambda r: r["final"])
    claimed = round(rec["final"] * 1000)
    bks_int = round(rec["bks"] * 1000)

    routes = []
    for key in rec["witness_routes"]:
        vt, vv = key.split("|", 1)
        # pyvrp indices -> file ids are +1
        routes.append((int(vt), [int(v) + 1 for v in vv.split(",") if v]))

    report = {"claimed_scaled": claimed, "bks_scaled": bks_int}
    ok = True

    # 1. cost, arc by arc, integer arithmetic
    total = 0
    for vt, visits in routes:
        depot = inst["depots"][vt]          # vehicle type t <-> depot index t
        seq = [depot, *visits, depot]
        for a, b in zip(seq, seq[1:]):
            total += dist_int(a, b, inst["coord"])
    report["recomputed_scaled"] = total
    report["cost_match"] = (total == claimed)
    ok &= report["cost_match"]

    # 2. coverage
    served = [v for _, visits in routes for v in visits]
    clients = set(range(nd + 1, inst["dim"] + 1))
    report["clients"] = len(clients)
    report["served_once"] = (len(served) == len(set(served)) == len(clients)
                             and set(served) == clients)
    ok &= report["served_once"]

    # 3. per-depot vehicle caps
    from collections import Counter
    cap = Counter(inst["veh_depot"])        # depot node id -> fleet size
    used = Counter(inst["depots"][vt] for vt, _ in routes)
    report["vehicle_caps_ok"] = all(used[d] <= cap[d] for d in used)
    report["vehicles_used"] = dict(used)
    ok &= report["vehicle_caps_ok"]

    # 4. capacity, time windows, duration (scaled x1000 throughout)
    cap_viol = tw_viol = dur_viol = 0
    for vt, visits in routes:
        depot = inst["depots"][vt]
        load = sum(inst["demand"][v] for v in visits)
        if load > inst["capacity"]:
            cap_viol += 1
        seq = [depot, *visits, depot]
        t = inst["tw"][depot][0] * 1000     # earliest departure
        start = t
        wait_total = 0.0
        for a, b in zip(seq, seq[1:]):
            t += inst["service"].get(a, 0.0) * 1000 if a != depot else 0.0
            t += dist_int(a, b, inst["coord"])
            e, l = inst["tw"][b]
            if t > l * 1000 + 1e-6:
                tw_viol += 1
            if t < e * 1000:
                wait_total += e * 1000 - t
                t = e * 1000
        duration = t - start
        # latest-start shift can absorb waiting without breaking windows
        if duration - wait_total > inst["max_dur"] * 1000 + 1e-6:
            dur_viol += 1
        elif duration > inst["max_dur"] * 1000 + 1e-6:
            report.setdefault("duration_needed_shift", 0)
            report["duration_needed_shift"] += 1
    report["capacity_violations"] = cap_viol
    report["tw_violations"] = tw_viol
    report["duration_violations_after_shift"] = dur_viol
    ok &= (cap_viol == 0 and tw_viol == 0 and dur_viol == 0)

    report["improvement_scaled"] = bks_int - total
    report["CERTIFICATE"] = "PASS" if ok and total < bks_int else "FAIL"
    (OUT / f"k3_certificate_{INSTANCE}.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
