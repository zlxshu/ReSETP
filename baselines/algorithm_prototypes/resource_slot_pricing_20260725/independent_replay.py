#!/usr/bin/env python3
"""Independent G0 witness replay and one-shot frozen decision."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median

from common import (
    OUTPUT,
    REPO,
    artifact_hashes,
    load_bundle,
    load_solution,
    read_json,
    verify_registration,
    write_csv,
    write_json,
)
from setp_solver.check import check_solution
from setp_solver.china81_completion import exact_china81_score


def replay(payload: dict, bundle: object, expected: float, label: str) -> float:
    solution = load_solution(payload)
    objective, _, exact_violations = exact_china81_score(solution, bundle)
    direct_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if exact_violations or direct_violations:
        raise RuntimeError(
            f"{label} replay infeasible: exact={len(exact_violations)}, "
            f"direct={len(direct_violations)}"
        )
    if not math.isclose(
        float(objective),
        float(expected),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError(
            f"{label} replay objective drift: {objective} != {expected}"
        )
    return float(objective)


def main() -> int:
    registration = verify_registration()
    with (OUTPUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 6 or any(row["status"] != "OK" for row in rows):
        raise RuntimeError("G0 did not produce six OK rows")
    replay_rows = []
    for row in rows:
        witness = read_json(REPO / row["witness_path"])
        bundle = load_bundle(row["instance_id"])
        start = replay(
            witness["start"],
            bundle,
            float(row["start_objective"]),
            f"{row['task_id']} start",
        )
        output = replay(
            witness["output"],
            bundle,
            float(row["output_objective"]),
            f"{row['task_id']} output",
        )
        replay_rows.append(
            {
                "task_id": row["task_id"],
                "instance_id": row["instance_id"],
                "lane": row["lane"],
                "start_objective": start,
                "output_objective": output,
                "violation_count": 0,
                "status": "PASS",
            }
        )
    write_csv(OUTPUT / "independent_replay.csv", replay_rows)
    by_instance = {}
    for row in rows:
        by_instance.setdefault(row["instance_id"], {})[row["lane"]] = row
    resource = [lanes["RESOURCE-SLOT"] for lanes in by_instance.values()]
    selected_external = sum(
        int(row["selected_negative_routes"]) > 0
        and int(row["selected_changed_adjacency_routes"]) > 0
        for row in resource
    )
    improving = sum(row["strict_improvement"] == "True" for row in resource)
    improvement_005 = sum(float(row["improvement_pct"]) >= 0.05 for row in resource)
    rsp_beats_local = sum(
        float(lanes["RESOURCE-SLOT"]["output_objective"])
        < float(lanes["LOCAL"]["output_objective"]) - 1.0e-9
        for lanes in by_instance.values()
    )
    rsp_losses = sum(
        float(lanes["RESOURCE-SLOT"]["output_objective"])
        > float(lanes["LOCAL"]["output_objective"]) + 1.0e-9
        for lanes in by_instance.values()
    )
    attribution = sum(
        int(row["selected_resource_rank_changed_routes"]) > 0 for row in resource
    )
    ratios = [
        float(lanes["RESOURCE-SLOT"]["wall_seconds"])
        / max(float(lanes["LOCAL"]["wall_seconds"]), 1.0e-9)
        for lanes in by_instance.values()
    ]
    caps_ok = all(
        int(row["label_extensions"])
        <= int(registration["config"]["max_label_extensions"])
        and int(row["generated_routes"])
        <= int(registration["config"]["max_generated_routes"])
        and int(row["complete_candidate_evaluations"]) == 1
        and float(row["wall_seconds"])
        <= float(registration["config"]["task_wall_seconds"])
        for row in rows
    )
    passed = bool(
        selected_external >= 2
        and improving >= 2
        and improvement_005 >= 1
        and rsp_beats_local >= 2
        and rsp_losses == 0
        and attribution >= 1
        and median(ratios) <= 1.25
        and max(ratios) <= 1.50
        and caps_ok
    )
    verdict = (
        "PASS_RESOURCE_SLOT_PRICING_LOW_COST_G0"
        if passed
        else "STOP_RESOURCE_SLOT_PRICING_NO_LOW_COST_STRONG_HGS_HEADROOM"
    )
    decision = {
        "schema": "resetp.resource-slot-pricing-decision.v1",
        "verdict": verdict,
        "pass": passed,
        "six_outputs_independently_replayed": True,
        "selected_external_negative_routes_instances": selected_external,
        "resource_slot_improving_instances": improving,
        "resource_slot_improvements_at_least_005_pct": improvement_005,
        "resource_slot_beats_local_instances": rsp_beats_local,
        "resource_slot_loses_to_local_instances": rsp_losses,
        "selected_resource_price_attribution_instances": attribution,
        "wall_ratio_median": median(ratios),
        "wall_ratio_max": max(ratios),
        "all_caps_respected": caps_ok,
        "next_step": (
            "ELIGIBLE_ONLY_FOR_SEPARATELY_REGISTERED_UNSEEN_A_B_AB_GATE"
            if passed
            else "FINAL_STOP_NO_RESCUE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "decision.json", decision)
    (OUTPUT / "report.md").write_text(
        "# Resource-slot pricing G0\n\n"
        f"Verdict: `{verdict}`.\n\n"
        f"Resource-slot improvements: {improving}/3; improvements at least "
        f"0.05%: {improvement_005}/3; wins over matched LOCAL: "
        f"{rsp_beats_local}/3; losses: {rsp_losses}/3; independently replayed "
        "outputs: 6/6.\n\n"
        "This is one frozen low-cost falsification gate. It is not a China81 "
        "full result, public benchmark, BKS/SOTA result, E3 release, or paper "
        "performance claim.\n",
        encoding="utf-8",
    )
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes(OUTPUT))
    write_json(
        OUTPUT / "done.json",
        {
            "verdict": verdict,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
