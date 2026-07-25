"""Independent full-model replay of sealed G0 candidate witnesses."""

from __future__ import annotations

from typing import Any

from .common import (
    G0_OUT,
    exact_replay,
    load_bundle,
    load_solution,
    read_json,
    write_json,
)


def replay_all() -> list[dict[str, Any]]:
    payload = read_json(G0_OUT / "solution_witnesses.json")
    rows: list[dict[str, Any]] = []
    for task_id in sorted(payload):
        row = payload[task_id]
        bundle = load_bundle(row["instance_id"])
        solution = load_solution(row["solution"])
        objective = exact_replay(
            solution,
            bundle,
            f"{task_id} independent replay",
        )
        expected = float(row["final_cost"])
        if abs(objective - expected) > 1.0e-6:
            raise RuntimeError(
                f"{task_id}: independent replay {objective} != {expected}"
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
    write_json(G0_OUT / "independent_replay.json", rows)
    return rows


if __name__ == "__main__":
    print(f"replayed {len(replay_all())} witnesses")
