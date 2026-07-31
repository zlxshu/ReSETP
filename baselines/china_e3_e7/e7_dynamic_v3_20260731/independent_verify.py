#!/usr/bin/env python3
"""Independent task-matrix, final-cost, profit, feasibility, and budget audit."""

from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any

import run_e7_dynamic as runner


def task_results() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for scale in runner.LEGACY.SCALES:
        for seed in range(1, 11):
            for arm in runner.LEGACY.ARMS:
                path = runner.LEGACY.task_path(scale, seed, arm)
                if not path.is_file():
                    raise RuntimeError(f"HALT_INDEPENDENT_TASK_MISSING:{path}")
                task = json.loads(path.read_text(encoding="utf-8"))
                if task.get("status") not in {"PASS", "LEGAL_INFEASIBLE"}:
                    raise RuntimeError(f"HALT_INDEPENDENT_NONTERMINAL:{path}")
                tasks.append(task)
    return tasks


def reconstructed_instance(base: Any, node_rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> Any:
    donor_by_added = {
        str(row["customer_id"]): str(row["donor_customer_id"])
        for row in events
        if row["event_type"] == "add"
    }
    base_index = base.node_index
    nodes = [runner.LEGACY.Node(**row) for row in node_rows]
    aliases = [
        node.node_id
        if node.node_id in base_index
        else donor_by_added[node.node_id]
        for node in nodes
    ]
    matrix = [
        [
            float(base.distance(left, right))
            for right in aliases
        ]
        for left in aliases
    ]
    road_profiles = None
    if base.road_profiles is not None:
        road_profiles = {
            profile: runner.LEGACY.RoadProfileMatrices(
                distance_m=tuple(
                    tuple(
                        float(matrices.distance_m[base_index[left]][base_index[right]])
                        for right in aliases
                    )
                    for left in aliases
                ),
                duration_s=tuple(
                    tuple(
                        float(matrices.duration_s[base_index[left]][base_index[right]])
                        for right in aliases
                    )
                    for left in aliases
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(
                        float(matrices.sum_v2d_m3_s2[base_index[left]][base_index[right]])
                        for right in aliases
                    )
                    for left in aliases
                ),
            )
            for profile, matrices in base.road_profiles.items()
        }
    return runner.LEGACY.Instance(
        nodes=nodes,
        distance_matrix=matrix,
        diesel_l_per_meter=base.diesel_l_per_meter,
        ev_kwh_per_meter=base.ev_kwh_per_meter,
        unit_distance_cost_per_meter=base.unit_distance_cost_per_meter,
        num_cv=base.num_cv,
        num_ev=base.num_ev,
        road_profiles=road_profiles,
        vehicle_parameters=base.vehicle_parameters,
        demand_mass_per_unit_kg=base.demand_mass_per_unit_kg,
    )


def main() -> None:
    runner.verify_protected_and_inputs()
    tasks = task_results()
    if len(tasks) != 120:
        raise RuntimeError(f"HALT_INDEPENDENT_MATRIX:{len(tasks)}")
    max_cost_diff = 0.0
    max_profit_diff = 0.0
    feasibility_count = 0
    cost_count = 0
    profit_count = 0
    legal_infeasible_count = 0
    rows: list[dict[str, Any]] = []
    for task in tasks:
        scale = str(task["scale"])
        seed = int(task["algorithm_seed"])
        stream_seed = int(task["stream_seed"])
        runner.LEGACY._CURRENT_ALGORITHM_SEED = seed
        sources, _ = runner.current_sources(network=scale)
        event_payload = runner.LEGACY.load_event_payload(scale, stream_seed)
        claimed_hash = str(task["result_sha256"])
        unhashed = dict(task)
        unhashed.pop("result_sha256")
        if runner.canonical_sha256(unhashed) != claimed_hash:
            raise RuntimeError(
                f"HALT_INDEPENDENT_TASK_HASH:{scale}:{seed}:{task['arm']}"
            )
        if task["protected_hashes"] != runner.ORIGINAL_VERIFY_PROTECTED():
            raise RuntimeError(
                f"HALT_INDEPENDENT_PROTECTED_HASH:{scale}:{seed}:{task['arm']}"
            )
        cap = int(task["per_stage_total_cap"])
        actual = int(task["actual_evaluations"])
        if task["status"] == "LEGAL_INFEASIBLE":
            attempted = int(task["attempted_stage_count"])
            null_fields = (
                "final_total_cost",
                "final_total_profit",
                "final_depot_profit",
                "final_actual_emissions_kg",
                "final_actual_charging_emissions_kg",
                "final_charging_energy_kwh",
                "vehicle_count",
                "payload",
            )
            if any(task[field] is not None for field in null_fields):
                raise RuntimeError(
                    f"HALT_INDEPENDENT_INFEASIBLE_NON_NULL:{scale}:{seed}:{task['arm']}"
                )
            if not any(
                signature in str(task["legal_infeasibility_reason"])
                for signature in (
                    "no feasible vehicle type assignment for separate event trips",
                    "stage search found no executable continuation",
                )
            ):
                raise RuntimeError(
                    f"HALT_INDEPENDENT_INFEASIBLE_SIGNATURE:{scale}:{seed}:{task['arm']}"
                )
            if actual > cap * attempted:
                raise RuntimeError(
                    f"HALT_INDEPENDENT_BUDGET:{scale}:{seed}:{task['arm']}"
                )
            legal_infeasible_count += 1
            rows.append(
                {
                    "scale": scale,
                    "seed": seed,
                    "arm": task["arm"],
                    "status": task["status"],
                    "cost_abs_diff": None,
                    "profit_abs_diff": None,
                    "hard_violation_count": None,
                    "actual_evaluations": actual,
                    "allowed_evaluations": cap * attempted,
                }
            )
            continue
        instance = reconstructed_instance(
            sources["bundle"].instance,
            task["payload"]["full_day_instance_nodes"],
            event_payload["events"],
        )
        solution = runner.PROBE.base.solution_from_dict(
            task["payload"]["full_day_solution"]
        )
        violations = runner.check_solution(
            solution,
            instance,
            sources["prices"],
        )
        if violations:
            raise RuntimeError(
                "HALT_INDEPENDENT_FEASIBILITY:"
                f"{scale}:{seed}:{task['arm']}:"
                + json.dumps(
                    [asdict(row) for row in violations[:10]],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        feasibility_count += 1
        recomputed = runner.PROBE.base.evaluate_parts(
            solution.routes,
            solution.charging_actions,
            instance,
            sources,
        )
        cost = float(recomputed["total_cost"])
        cost_diff = abs(cost - float(task["final_total_cost"]))
        max_cost_diff = max(max_cost_diff, cost_diff)
        if cost_diff > runner.TOL:
            raise RuntimeError(
                f"HALT_INDEPENDENT_COST:{scale}:{seed}:{task['arm']}:{cost_diff}"
            )
        cost_count += 1
        owners = runner.LEGACY.load_owners(scale, stream_seed)
        closure = runner.PROBE._profit_closure(
            solution,
            instance,
            sources,
            owners,
        )
        profit_diff = abs(
            float(closure["total_profit"]) - float(task["final_total_profit"])
        )
        max_profit_diff = max(max_profit_diff, profit_diff)
        if profit_diff > runner.TOL:
            raise RuntimeError(
                f"HALT_INDEPENDENT_PROFIT:{scale}:{seed}:{task['arm']}:{profit_diff}"
            )
        profit_count += 1
        stages = int(task["stage_count"])
        if actual > cap * stages:
            raise RuntimeError(
                f"HALT_INDEPENDENT_BUDGET:{scale}:{seed}:{task['arm']}"
            )
        if any(
            int(row["main_evaluations"]) + int(row["shadow_evaluations"]) > cap
            for row in task["payload"]["rows"]
        ):
            raise RuntimeError(
                f"HALT_INDEPENDENT_STAGE_BUDGET:{scale}:{seed}:{task['arm']}"
            )
        if not all(
            bool(row["customer_accounting_pass"])
            for row in task["payload"]["rows"]
        ):
            raise RuntimeError(
                f"HALT_INDEPENDENT_CUSTOMER_ACCOUNTING:{scale}:{seed}:{task['arm']}"
            )
        if not math.isfinite(cost) or not math.isfinite(float(closure["total_profit"])):
            raise RuntimeError(
                f"HALT_INDEPENDENT_NONFINITE:{scale}:{seed}:{task['arm']}"
            )
        rows.append(
            {
                "scale": scale,
                "seed": seed,
                "arm": task["arm"],
                "status": task["status"],
                "cost_abs_diff": cost_diff,
                "profit_abs_diff": profit_diff,
                "hard_violation_count": 0,
                "actual_evaluations": actual,
                "allowed_evaluations": cap * stages,
            }
        )
    payload = {
        "schema": "resetp.china81.e7.independent-verification.v1",
        "task_id": runner.TASK_ID,
        "status": "PASS_INDEPENDENT_RECOMPUTATION",
        "created_at_utc": runner.LEGACY.now_iso(),
        "task_count": len(tasks),
        "feasible_task_count": len(tasks) - legal_infeasible_count,
        "legal_infeasible_task_count": legal_infeasible_count,
        "recomputed_cost_count": cost_count,
        "recomputed_profit_count": profit_count,
        "feasibility_check_count": feasibility_count,
        "customer_accounting_check_count": len(tasks),
        "budget_check_count": len(tasks),
        "task_hash_check_count": len(tasks),
        "protected_hash_check_count": len(tasks),
        "max_cost_abs_diff": max_cost_diff,
        "max_profit_abs_diff": max_profit_diff,
        "rows_sha256": runner.canonical_sha256(rows),
        "protected_hashes": runner.ORIGINAL_VERIFY_PROTECTED(),
    }
    payload["verification_sha256"] = runner.canonical_sha256(payload)
    runner.LEGACY.atomic_json(
        runner.HERE / "independent_verification.json",
        payload,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
