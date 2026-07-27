"""P0: how much of the depot assignment is obvious in the best known solution?

Pure geometry plus reading the frozen BKS route files.  No solver, no search.

The design under test claims that large MDVRPTW is hard because of the
depot-assignment boundary rather than the routing, and that a computable margin
identifies which customers are genuinely contested.  Two things have to be true
for that to hold:

1.  in the BKS, most customers are served by their nearest depot -- so the
    assignment is mostly forced and only a minority is really open;
2.  a nearest/second-nearest margin predicts which customers are the exception
    -- so the contested set can be found without solving anything.

If (1) fails the decomposition has no interior to exploit.  If (2) fails the
margin is the wrong handle and a different one is needed.  Either way this
costs minutes and settles it before any development.
"""

from __future__ import annotations

import json
import math
import statistics
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

    coords: dict[int, tuple[float, float]] = {}
    for row in sections["NODE_COORD_SECTION"]:
        parts = row.split()
        coords[int(parts[0])] = (float(parts[1]), float(parts[2]))

    depots = {int(row.split()[0]) for row in sections["DEPOT_SECTION"] if row.strip() and row.strip() != "-1"}
    return {
        "name": name,
        "dimension": int(header["DIMENSION"]),
        "coords": coords,
        "depots": sorted(depots),
        "vehicle_depot": sections.get("VEHICLES_DEPOT_SECTION", []),
    }


def read_bks_routes(name: str) -> list[list[int]]:
    routes = []
    for line in (SRC / "current_bks" / f"{name}.sol").read_text().splitlines():
        if not line.startswith("Route"):
            continue
        _, body = line.split(":", 1)
        nodes = [int(tok) for tok in body.split()]
        if nodes:
            routes.append(nodes)
    return routes


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def analyse(name: str) -> dict:
    inst = read_instance(name)
    routes = read_bks_routes(name)
    coords, depots = inst["coords"], inst["depots"]

    # VEHICLES_DEPOT_SECTION rows are "<vehicle_id> <depot_node_id>"; the route
    # numbering in the .sol file follows the same vehicle order.
    vehicle_depot = [
        int(row.split()[1]) for row in inst["vehicle_depot"] if row.strip()
    ]

    customers = [n for n in coords if n not in set(depots)]
    ranked: dict[int, list[tuple[float, int]]] = {}
    for customer in customers:
        pairs = sorted(
            (dist(coords[customer], coords[depot]), depot) for depot in depots
        )
        ranked[customer] = pairs

    # depot actually serving each customer in the BKS
    served_by: dict[int, int] = {}
    for index, route in enumerate(routes):
        depot = (
            vehicle_depot[index]
            if index < len(vehicle_depot)
            else None
        )
        for node in route:
            if node in ranked:
                served_by[node] = depot

    covered = [c for c in customers if served_by.get(c) is not None]
    nearest_hits = 0
    margins_nearest, margins_other = [], []
    rank_of_served = []
    for customer in covered:
        depot = served_by[customer]
        pairs = ranked[customer]
        d1, d2 = pairs[0][0], pairs[1][0]
        margin = (d2 - d1) / d1 if d1 > 0 else float("inf")
        order = [p[1] for p in pairs]
        rank = order.index(depot) + 1 if depot in order else -1
        rank_of_served.append(rank)
        if rank == 1:
            nearest_hits += 1
            margins_nearest.append(margin)
        else:
            margins_other.append(margin)

    def band(threshold: float) -> dict:
        contested = [
            c
            for c in covered
            if (ranked[c][1][0] - ranked[c][0][0]) / ranked[c][0][0] < threshold
        ]
        contested_set = set(contested)
        # how many of the non-nearest-served customers are inside this band
        caught = sum(
            1
            for c, r in zip(covered, rank_of_served)
            if r != 1 and c in contested_set
        )
        non_nearest = sum(1 for r in rank_of_served if r != 1)
        return {
            "threshold": threshold,
            "band_size": len(contested),
            "band_pct": round(len(contested) / len(covered) * 100, 2),
            "non_nearest_caught": caught,
            "recall_pct": round(caught / non_nearest * 100, 2) if non_nearest else None,
        }

    return {
        "instance": name,
        "customers": len(customers),
        "customers_in_bks_routes": len(covered),
        "depots": len(depots),
        "routes": len(routes),
        "served_by_nearest_depot": nearest_hits,
        "served_by_nearest_pct": round(nearest_hits / len(covered) * 100, 2),
        "served_by_2nd_nearest": sum(1 for r in rank_of_served if r == 2),
        "served_by_3rd_or_worse": sum(1 for r in rank_of_served if r >= 3),
        "median_margin_when_nearest": round(statistics.median(margins_nearest), 4)
        if margins_nearest
        else None,
        "median_margin_when_not_nearest": round(
            statistics.median(margins_other), 4
        )
        if margins_other
        else None,
        "bands": [band(t) for t in (0.05, 0.10, 0.15, 0.20, 0.30, 0.50)],
    }


def main() -> None:
    names = ["PR11A", "PR16A", "PR16B", "PR20A", "PR24A", "PR17B", "PR21B"]
    results = []
    for name in names:
        try:
            results.append(analyse(name))
        except Exception as exc:  # noqa: BLE001
            results.append({"instance": name, "error": str(exc)[:200]})

    (OUT / "p0_summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for row in results:
        if "error" in row:
            print(f"{row['instance']:<8} ERROR {row['error']}")
            continue
        print(
            f"{row['instance']:<8} n={row['customers']:<5} depots={row['depots']:<3} "
            f"最近车场服务={row['served_by_nearest_pct']:>6.2f}%  "
            f"第二近={row['served_by_2nd_nearest']:<4} 更远={row['served_by_3rd_or_worse']}"
        )
    print()
    print("争议带阈值 -> 带内客户占比 / 捕获非最近车场客户的比例:")
    for row in results:
        if "error" in row:
            continue
        cells = "  ".join(
            f"{b['threshold']:.2f}:{b['band_pct']:>5.1f}%/{b['recall_pct'] or 0:>5.1f}%"
            for b in row["bands"]
        )
        print(f"  {row['instance']:<8} {cells}")


if __name__ == "__main__":
    main()
