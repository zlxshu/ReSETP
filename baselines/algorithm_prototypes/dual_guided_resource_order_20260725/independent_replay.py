#!/usr/bin/env python3
"""Independent zero-search replay and final G0 decision."""

from __future__ import annotations

import csv
import json
import math
import statistics
from datetime import datetime, timezone

from common import (
    OUTPUT,
    REPO,
    artifact_hashes,
    load_bundle,
    load_solution,
    read_json,
    verify_registration,
    write_json,
)
from setp_solver.check import check_solution
from setp_solver.china81_completion import exact_china81_score


def replay(payload: dict, bundle: object, label: str) -> float:
    solution = load_solution(payload)
    objective, _, violations = exact_china81_score(solution, bundle)
    direct = check_solution(solution, bundle.instance, bundle.prices)
    if violations or direct:
        raise RuntimeError(
            f"{label} replay infeasible: exact={len(violations)}, direct={len(direct)}"
        )
    return float(objective)


def main() -> int:
    registration = verify_registration()
    config = registration["config"]
    with (OUTPUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_instance = {row["instance_id"]: row for row in rows}
    replay_rows = []
    failures = []
    for spec in registration["inputs"]:
        instance_id = spec["instance_id"]
        row = by_instance.get(instance_id)
        if row is None or row["status"] != "OK":
            failures.append(f"{instance_id}: missing successful search row")
            continue
        try:
            witness = read_json(REPO / row["witness_path"])
            bundle = load_bundle(instance_id)
            start = replay(witness["start"], bundle, "start")
            output = replay(witness["output"], bundle, "output")
            if not math.isclose(
                start,
                float(row["start_objective"]),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ) or not math.isclose(
                output,
                float(row["output_objective"]),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise RuntimeError("recorded/replayed objective mismatch")
            replay_rows.append(
                {
                    "instance_id": instance_id,
                    "start_objective": start,
                    "output_objective": output,
                    "closed": True,
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{instance_id}: {type(exc).__name__}: {exc}")
    ok_rows = [row for row in rows if row["status"] == "OK"]
    improving = [
        row for row in ok_rows if row["strict_improvement"].lower() == "true"
    ]
    improve_005 = [
        row
        for row in improving
        if float(row["relative_improvement_pct"]) >= 0.05 - 1.0e-12
    ]
    outside = [
        row
        for row in improving
        if row["accepted_outside_v7_pool_adjacency"].lower() == "true"
    ]
    fractions = [
        float(row["operator_hgs_cpu_fraction"]) for row in ok_rows
    ]
    mechanical = bool(
        not failures
        and len(ok_rows) == len(registration["inputs"])
        and len(replay_rows) == len(registration["inputs"])
        and all(
            int(row["complete_candidate_evaluations"])
            <= int(config["max_complete_evaluations_per_instance"])
            and int(row["dp_states"])
            <= int(config["max_dp_states_per_instance"])
            and row["material_order_and_membership_change"].lower() == "true"
            for row in ok_rows
        )
    )
    effect = bool(
        mechanical
        and len(improving) >= int(config["required_improving_instances"])
        and len(improve_005)
        >= int(config["required_improvements_at_least_005_pct"])
        and len(outside)
        >= int(config["required_accepted_outside_pool_adjacency"])
        and statistics.median(fractions)
        <= float(config["operator_median_hgs_cpu_fraction_max"])
        and max(fractions)
        <= float(config["operator_max_hgs_cpu_fraction_max"])
    )
    verdict = (
        "PASS_DUAL_GUIDED_RESOURCE_ORDER_LOW_COST_HEADROOM"
        if effect
        else "STOP_DUAL_GUIDED_RESOURCE_ORDER_NO_LOW_COST_HEADROOM"
    )
    decision = {
        "schema": "resetp.dual-guided-resource-order-g0-decision.v1",
        "verdict": verdict,
        "pass": effect,
        "mechanical_integrity_pass": mechanical,
        "independent_replay_closed": len(replay_rows),
        "expected_replays": len(registration["inputs"]),
        "strictly_improving_instances": len(improving),
        "improvements_at_least_005_pct": len(improve_005),
        "accepted_outputs_outside_v7_pool_adjacency": len(outside),
        "median_operator_hgs_cpu_fraction": (
            statistics.median(fractions) if fractions else None
        ),
        "max_operator_hgs_cpu_fraction": max(fractions) if fractions else None,
        "failures": failures,
        "next_step": (
            "STOP_AFTER_G0__COORDINATOR_DECISION_REQUIRED"
            if effect
            else "FREEZE_FAILURE__NO_PARAMETER_RESCUE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "independent_replay.json", {"rows": replay_rows})
    write_json(OUTPUT / "decision.json", decision)
    lines = [
        "# Dual-guided resource-order G0",
        "",
        f"Verdict: `{verdict}`",
        "",
        "| instance | start | output | improve % | evals | states | wall/HGS |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ok_rows:
        lines.append(
            f"| {row['instance_id']} | {float(row['start_objective']):.6f} | "
            f"{float(row['output_objective']):.6f} | "
            f"{float(row['relative_improvement_pct']):.6f} | "
            f"{row['complete_candidate_evaluations']} | {row['dp_states']} | "
            f"{float(row['operator_hgs_cpu_fraction']):.3f} |"
        )
    lines.extend(
        [
            "",
            (
                "This is one frozen low-cost falsification gate. It makes no "
                "paper, E3, China81-full, public BKS or SOTA claim."
            ),
        ]
    )
    (OUTPUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for path in OUTPUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes(OUTPUT))
    write_json(
        OUTPUT / "done.json",
        {
            "verdict": verdict,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

