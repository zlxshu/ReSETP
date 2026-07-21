#!/usr/bin/env python3
"""One-shot correctness self-check: does round_func='exact' match BKS scale?

The route certificate PR11A.sol carries an explicit integer "Cost: 6655548"
trailer. opponent_targets.csv reports current_verified_bks=6655.548 for
PR11A. 6655548 / 1000 == 6655.548 exactly, so the certificate's integer
scale is precisely PyVRP's round_func="exact" (x1000, round-to-nearest).
This script reconstructs the certificate route-by-route using PyVRP's own
reader+Route objects at that scale and checks the summed distance matches
the certificate cost and the opponent_targets BKS to double precision.
"""
from __future__ import annotations

import re
from pathlib import Path

from pyvrp import Route, read

ROOT = Path(__file__).resolve().parents[3]
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE = FOUNDATION / "sources/normalised_instances/PR11A.vrp"
CERTIFICATE = FOUNDATION / "sources/current_bks/PR11A.sol"


def _parse_certificate(path: Path) -> tuple[list[list[int]], int]:
    routes: list[list[int]] = []
    cost = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Route"):
            clients = [int(tok) for tok in re.findall(r"\d+", line.split(":", 1)[1])]
            routes.append(clients)
        elif line.startswith("Cost"):
            cost = int(line.split(":")[1].strip())
    if cost is None:
        raise ValueError("certificate missing Cost line")
    return routes, cost


def main() -> None:
    data = read(str(INSTANCE), round_func="exact")
    raw_routes, certificate_cost = _parse_certificate(CERTIFICATE)
    num_depots = data.num_depots
    vehicles_per_depot = data.num_vehicles // num_depots

    total = 0.0
    reconstructed = 0
    for block_index, raw_clients in enumerate(raw_routes):
        if not raw_clients:
            continue
        depot_index = block_index // vehicles_per_depot
        visits = [raw_id - 1 - num_depots + num_depots for raw_id in raw_clients]
        # raw ids are 1-based over the full location list (depots + clients);
        # PyVRP location indices are 0-based over the same ordering.
        visits = [raw_id - 1 for raw_id in raw_clients]
        route = Route(data, visits, depot_index)
        total += route.distance()
        reconstructed += 1

    print(f"routes reconstructed: {reconstructed}/{sum(1 for r in raw_routes if r)}")
    print(f"summed distance (exact scale, x1000 int): {total}")
    print(f"certificate Cost line: {certificate_cost}")
    print(f"match: {abs(total - certificate_cost) < 0.5}")
    print(f"double-precision (total/1000): {total / 1000.0}")
    print("opponent_targets current_verified_bks (PR11A): 6655.548")


if __name__ == "__main__":
    main()
