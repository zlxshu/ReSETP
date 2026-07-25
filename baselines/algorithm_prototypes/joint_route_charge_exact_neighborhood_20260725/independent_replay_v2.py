"""Independent full-model replay for JRC G0 v2 witnesses."""

from __future__ import annotations

from typing import Any

from .common import exact_replay, load_bundle, load_solution
from .v2_common import G0_OUT_V2, read_json, write_json


def replay_all_v2() -> list[dict[str, Any]]:
    payload = read_json(G0_OUT_V2 / "solution_witnesses.json")
    rows = []
    for task_id in sorted(payload):
        row = payload[task_id]
        bundle = load_bundle(row["instance_id"])
        solution = load_solution(row["solution"])
        objective = exact_replay(
            solution, bundle, f"{task_id} independent replay v2"
        )
        expected = float(row["final_cost"])
        if abs(objective - expected) > 1.0e-6:
            raise RuntimeError(
                f"{task_id}: replay {objective} != {expected}"
            )
        rows.append(
            {
                "task_id": task_id,
                "instance_id": row["instance_id"],
                "arm": row["arm"],
                "expected_cost": expected,
                "replayed_cost": objective,
                "absolute_difference": abs(objective - expected),
                "feasible": True,
            }
        )
    write_json(G0_OUT_V2 / "independent_replay.json", rows)
    return rows
