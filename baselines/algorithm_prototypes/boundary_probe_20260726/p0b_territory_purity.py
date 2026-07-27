"""P0b: are best-known routes confined to one depot's territory?

The earlier probe needed a route->depot mapping that the .sol files do not
carry, so it is replaced by a question that needs no such mapping.

Label every customer by its nearest depot -- that is its "territory".  Then for
each route in the frozen BKS, look at the territory labels of the customers it
visits.  A route whose customers all share one label sits inside a single
territory; a route with mixed labels crosses a boundary.

If most BKS routes are territory-pure, then most of the depot-assignment
decision is forced by geometry and the real combinatorial action is confined to
a minority of customers near territory boundaries.  That is the premise the
proposed decomposition rests on, and this settles it with no solver at all.

The margin column asks the second question: are the customers that actually
cross territories the ones a nearest/second-nearest margin would flag?
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = (
    ROOT
    / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/sources"
)
OUT = Path(__file__).resolve().parent


def read_instance(name: str) -> dict:
    lines = (SRC / "normalised_instances" / f"{name}.vrp").read_text().splitlines()
    header, sections, current = {}, {}, None
    for line in lines:
        line = line.rstrip()
        if not line or line == "EOF":
            continue
        if line.endswith("SECTION"):
            current = line
            sections[current] = []
            continue
        if current is None:
            if ":" in line:
                key, value = line.split(":", 1)
                header[key.strip()] = value.strip()
            continue
        sections[current].append(line)

    coords = {}
    for row in sections["NODE_COORD_SECTION"]:
        parts = row.split()
        coords[int(parts[0])] = (float(parts[1]), float(parts[2]))
    depots = sorted(
        int(row.split()[0])
        for row in sections["DEPOT_SECTION"]
        if row.strip() and row.strip() != "-1"
    )
    return {"name": name, "coords": coords, "depots": depots}


def read_bks_routes(name: str) -> list[list[int]]:
    routes = []
    for line in (SRC / "current_bks" / f"{name}.sol").read_text().splitlines():
        if line.startswith("Route"):
            nodes = [int(t) for t in line.split(":", 1)[1].split()]
            if nodes:
                routes.append(nodes)
    return routes


def analyse(name: str) -> dict:
    inst = read_instance(name)
    routes = read_bks_routes(name)
    coords, depots = inst["coords"], set(inst["depots"])

    territory, margin = {}, {}
    for node, point in coords.items():
        if node in depots:
            continue
        pairs = sorted(
            (math.hypot(point[0] - coords[d][0], point[1] - coords[d][1]), d)
            for d in inst["depots"]
        )
        territory[node] = pairs[0][1]
        d1, d2 = pairs[0][0], pairs[1][0]
        margin[node] = (d2 - d1) / d1 if d1 > 0 else float("inf")

    pure_routes = 0
    crossing_customers: list[int] = []
    minority_counts = []
    for route in routes:
        labels = [territory[n] for n in route if n in territory]
        if not labels:
            continue
        counts = Counter(labels)
        majority, majority_n = counts.most_common(1)[0]
        if len(counts) == 1:
            pure_routes += 1
        minority_counts.append(len(labels) - majority_n)
        crossing_customers.extend(
            n for n in route if n in territory and territory[n] != majority
        )

    covered = [n for r in routes for n in r if n in territory]
    crossing = set(crossing_customers)

    margins_crossing = [margin[n] for n in crossing]
    margins_interior = [
        margin[n] for n in covered if n not in crossing
    ]

    def band(threshold: float) -> dict:
        in_band = [n for n in covered if margin[n] < threshold]
        caught = sum(1 for n in in_band if n in crossing)
        return {
            "threshold": threshold,
            "band_pct_of_customers": round(len(in_band) / len(covered) * 100, 2),
            "recall_of_crossing_pct": round(caught / len(crossing) * 100, 2)
            if crossing
            else None,
        }

    return {
        "instance": name,
        "customers": len(covered),
        "depots": len(depots),
        "routes": len(routes),
        "territory_pure_routes": pure_routes,
        "territory_pure_route_pct": round(pure_routes / len(routes) * 100, 2),
        "median_minority_customers_per_route": statistics.median(minority_counts)
        if minority_counts
        else None,
        "crossing_customers": len(crossing),
        "crossing_customer_pct": round(len(crossing) / len(covered) * 100, 2),
        "median_margin_crossing": round(statistics.median(margins_crossing), 4)
        if margins_crossing
        else None,
        "median_margin_interior": round(statistics.median(margins_interior), 4)
        if margins_interior
        else None,
        "bands": [band(t) for t in (0.05, 0.10, 0.20, 0.30, 0.50)],
    }


def main() -> None:
    names = ["PR11A", "PR11B", "PR16A", "PR16B", "PR20A", "PR24A", "PR17B", "PR21B"]
    results = [analyse(n) for n in names]
    (OUT / "p0b_summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"{'题':<8}{'客户':>6}{'车场':>5}{'路线':>6}{'纯地盘路线':>11}{'跨界客户':>11}")
    for r in results:
        print(
            f"{r['instance']:<8}{r['customers']:>6}{r['depots']:>5}{r['routes']:>6}"
            f"{r['territory_pure_route_pct']:>10.1f}%{r['crossing_customer_pct']:>10.1f}%"
        )
    print()
    print("跨界客户 vs 内部客户的争议度中位数（越小越靠近边界）:")
    for r in results:
        print(
            f"  {r['instance']:<8} 跨界 {r['median_margin_crossing']:<8} "
            f"内部 {r['median_margin_interior']}"
        )
    print()
    print("争议带阈值 -> 带内客户占比 / 捕获跨界客户比例:")
    for r in results:
        cells = "  ".join(
            f"{b['threshold']:.2f}:{b['band_pct_of_customers']:>5.1f}%/"
            f"{b['recall_of_crossing_pct'] or 0:>5.1f}%"
            for b in r["bands"]
        )
        print(f"  {r['instance']:<8} {cells}")


if __name__ == "__main__":
    main()
