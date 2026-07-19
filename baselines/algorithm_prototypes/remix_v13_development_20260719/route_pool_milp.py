#!/usr/bin/env python3
"""Time-bounded exact route-pool recombination for the V13 gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def solve(payload: dict[str, Any]) -> dict[str, Any]:
    clients = [int(client) for client in payload["clients"]]
    routes = payload["routes"]
    client_index = {client: idx for idx, client in enumerate(clients)}
    incidence = np.zeros((len(clients), len(routes)), dtype=float)
    for column, route in enumerate(routes):
        for client in route["visits"]:
            incidence[client_index[int(client)], column] = 1.0

    constraints: list[LinearConstraint] = [
        LinearConstraint(
            incidence,
            np.ones(len(clients)),
            np.ones(len(clients)),
        )
    ]
    limits = {
        int(key): int(value)
        for key, value in payload["vehicle_limits"].items()
    }
    ordered_types = sorted(limits)
    vehicle_rows = np.zeros((len(ordered_types), len(routes)), dtype=float)
    for row, vehicle_type in enumerate(ordered_types):
        for column, route in enumerate(routes):
            if int(route["vehicle_type"]) == vehicle_type:
                vehicle_rows[row, column] = 1.0
    constraints.append(
        LinearConstraint(
            vehicle_rows,
            np.zeros(len(ordered_types)),
            np.asarray([limits[key] for key in ordered_types], dtype=float),
        )
    )

    result = milp(
        c=np.asarray([int(route["distance"]) for route in routes], dtype=float),
        integrality=np.ones(len(routes), dtype=int),
        bounds=Bounds(np.zeros(len(routes)), np.ones(len(routes))),
        constraints=constraints,
        options={
            "time_limit": max(
                0.05,
                float(payload["time_limit_seconds"]),
            )
        },
    )
    selected = []
    if result.x is not None:
        selected = [
            idx
            for idx, value in enumerate(result.x)
            if float(value) >= 0.5
        ]
    return {
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "objective": (
            float(result.fun)
            if result.fun is not None
            else None
        ),
        "selected_indices": selected,
        "selected_sources": sorted(
            {str(routes[idx]["source"]) for idx in selected}
        ),
        "selected_route_count": len(selected),
        "candidate_route_count": len(routes),
    }


def main() -> int:
    args = parse_args()
    result = solve(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if result["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
