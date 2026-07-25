#!/usr/bin/env python3
"""Independently replay the sealed HGS-ILS-XD G0 evidence without search."""

from __future__ import annotations

import csv
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (REPO / "solver/src", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import (  # noqa: E402
    INPUT_MANIFEST,
    OUT,
    REGISTRATION,
    file_sha256,
    load_complete_solution,
    load_route_skeleton,
    read_json,
    source_hashes,
    write_json,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)


def _check_exact_solution(
    payload: dict[str, Any],
    instance_id: str,
) -> float:
    bundle = load_china81_bundle(REPO, instance_id)
    solution = load_complete_solution(payload)
    objective, _, violations = exact_china81_score(solution, bundle)
    independent = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if violations or independent:
        raise RuntimeError(
            f"{instance_id} independent replay found violations"
        )
    return float(objective)


def main() -> int:
    manifest = read_json(INPUT_MANIFEST)
    decision = read_json(OUT / "decision.json")
    metadata = read_json(OUT / "metadata.json")
    with (OUT / "raw_runs.csv").open(
        newline="",
        encoding="utf-8",
    ) as handle:
        raw = list(csv.DictReader(handle))
    tasks = [
        read_json(path)
        for path in sorted((OUT / "tasks").glob("*.json"))
    ]
    if len(raw) != 6 or len(tasks) != 6:
        raise RuntimeError("G0 evidence must contain exactly six tasks")
    if metadata["source_hashes_start"] != metadata["source_hashes_end"]:
        raise RuntimeError("sealed G0 source hashes drifted")
    if metadata["source_hashes_end"] != source_hashes():
        raise RuntimeError("current protected/source hashes drifted")
    if metadata["registration_sha256"] != file_sha256(REGISTRATION):
        raise RuntimeError("registration hash mismatch")
    if metadata["input_manifest_sha256"] != file_sha256(INPUT_MANIFEST):
        raise RuntimeError("input manifest hash mismatch")

    replay_rows: list[dict[str, Any]] = []
    for task in tasks:
        instance_id = str(task["instance_id"])
        item = manifest["instances"][instance_id]
        bundle = load_china81_bundle(REPO, instance_id)
        if task["start_kind"] == "warm":
            payload = read_json(
                REPO / item["warm_start_witness_path"]
            )[item["warm_start_label"]]
            start_objective = _check_exact_solution(payload, instance_id)
        else:
            skeleton = load_route_skeleton(
                read_json(REPO / item["common_initial_path"])
            )
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
            )
            start_objective, _, violations = exact_china81_score(
                completion.solution,
                bundle,
            )
            independent = check_solution(
                completion.solution,
                bundle.instance,
                bundle.prices,
            )
            if violations or independent:
                raise RuntimeError(
                    f"{instance_id} cold start is not feasible"
                )
        if abs(start_objective - task["start_exact_objective"]) > 1.0e-6:
            raise RuntimeError(f"{instance_id} start objective mismatch")

        replayed_best = None
        if task["best_witness"] is not None:
            replayed_best = _check_exact_solution(
                task["best_witness"],
                instance_id,
            )
            if (
                abs(replayed_best - task["best_exact_objective"])
                > 1.0e-6
            ):
                raise RuntimeError(
                    f"{instance_id} best objective mismatch"
                )
        replay_rows.append(
            {
                "instance_id": instance_id,
                "start_kind": task["start_kind"],
                "start_exact_objective": float(start_objective),
                "best_exact_objective": replayed_best,
                "independently_feasible": True,
            }
        )

    exact_feasible = sum(
        row["best_exact_objective"] is not None for row in replay_rows
    )
    warm_improved = sum(
        row["start_kind"] == "warm"
        and row["best_exact_objective"] is not None
        and row["best_exact_objective"]
        < row["start_exact_objective"] - 1.0e-9
        for row in replay_rows
    )
    if exact_feasible != decision["exact_feasible_tasks"]:
        raise RuntimeError("decision exact-feasible count mismatch")
    if warm_improved != decision["warm_instances_strictly_improved"]:
        raise RuntimeError("decision warm-improvement count mismatch")
    if decision["pass"] or decision["verdict"] != (
        "STOP_HGS_ILS_XD_G0_NO_FEASIBLE_COMPLEMENTARITY"
    ):
        raise RuntimeError("unexpected G0 decision")

    write_json(
        OUT / "independent_replay.json",
        {
            "schema": "resetp.hgs-ils-xd.g0-independent-replay.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "search_runs": 0,
            "tasks_replayed": len(replay_rows),
            "exact_feasible_generated_witnesses_replayed": exact_feasible,
            "warm_starts_strictly_improved": warm_improved,
            "source_hashes_closed": True,
            "registration_and_manifest_hashes_closed": True,
            "decision_recomputed": True,
            "verdict": decision["verdict"],
            "rows": replay_rows,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
