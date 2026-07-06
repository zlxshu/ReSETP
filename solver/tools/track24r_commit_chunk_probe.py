from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dr_alns_ppo.track24_breakthrough_audit import build_stage3_action_specs
from dr_alns_ppo.track24_breakthrough_audit import build_track24_dynamic_policy
from setp_solver.check import check_solution
from setp_solver.cost import route_node_schedule
from setp_solver.search import dynamic as dynamic_module
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.dynamic import RollingParameters
from setp_solver.search.dynamic import _solution_for_customer_subset
from setp_solver.search.dynamic import _subinstance_for_customers
from setp_solver.solution import Solution
from setp_solver.solution import Route


BUNDLE_DIR = Path("models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h")
OUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track24r_dynamic_legality/debug")
OUT_JSON = OUT_DIR / "commit_chunk_c32_probe.json"


def _route_with_customer(solution: Solution, customer_id: str) -> Any:
    for route in solution.routes:
        if customer_id in route.node_sequence:
            return route
    return None


def _schedule_row(route: Any, instance: Any, customer_id: str) -> dict[str, Any]:
    if route is None:
        return {}
    for row in route_node_schedule(route, instance):
        if row.node_id == customer_id:
            return {
                "node_id": row.node_id,
                "t_arrive": float(row.t_arrive),
                "t_start": float(row.t_start),
                "t_depart": float(row.t_depart),
            }
    return {}


def _node_state(instance: Any, customer_id: str) -> dict[str, Any]:
    node = next(node for node in instance.nodes if node.node_id == customer_id)
    return {
        "node_id": node.node_id,
        "demand": float(node.demand),
        "ready_time": float(node.ready_time),
        "due_time": float(node.due_time),
        "x": float(node.x),
        "y": float(node.y),
    }


def _violation_rows(violations: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": getattr(violation, "type", ""),
            "vehicle_id": getattr(violation, "vehicle_id", ""),
            "location": getattr(violation, "location", ""),
            "detail": getattr(violation, "detail", ""),
            "severity": getattr(violation, "severity", ""),
        }
        for violation in violations
    ]


def _preserved_prefix_chunk(plan: Solution, customer_ids: set[str]) -> Solution:
    routes: list[Route] = []
    vehicle_map: dict[str, str] = {}
    kept_nodes_by_vehicle: dict[str, set[str]] = {}
    for route in plan.routes:
        committed_positions = [idx for idx, node_id in enumerate(route.node_sequence) if node_id in customer_ids]
        if not committed_positions:
            continue
        last_idx = max(committed_positions)
        seq = list(route.node_sequence[: last_idx + 1])
        if seq[-1] != route.home_depot_id:
            seq.append(route.home_depot_id)
        vehicle_id = f"S2P_{len(routes) + 1}_{route.vehicle_id}"
        vehicle_map[route.vehicle_id] = vehicle_id
        kept_nodes_by_vehicle[route.vehicle_id] = set(seq)
        routes.append(Route(vehicle_id, route.vehicle_type, route.home_depot_id, seq))
    actions = [
        action.__class__(
            vehicle_map[action.vehicle_id],
            action.station_id,
            action.energy_kwh,
            action.occupancy_minutes,
            action.charge_start_second,
        )
        for action in plan.charging_actions
        if action.vehicle_id in vehicle_map and action.station_id in kept_nodes_by_vehicle[action.vehicle_id]
    ]
    return Solution(routes=routes, charging_actions=actions)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bundle = load_search_bundle(BUNDLE_DIR)
    stage_budget = 2000
    stage_runtime = 120.0
    spec = next(spec for spec in build_stage3_action_specs(stage_budget, stage_runtime) if spec["action_id"] == "stage_budget_event_density")
    captured: dict[str, Any] = {}
    original_run_stage_plan = dynamic_module._run_stage_plan
    original_solution_for_customer_subset = dynamic_module._solution_for_customer_subset

    def wrapped_run_stage_plan(*args: Any, **kwargs: Any) -> Any:
        result = original_run_stage_plan(*args, **kwargs)
        stage_bundle_dir = Path(args[3])
        if stage_bundle_dir.name == "stage_001":
            captured["previous_plan"] = result.solution
            captured["previous_instance"] = result.instance
            captured["stage_001_violations"] = list(result.violations)
        return result

    def wrapped_solution_for_customer_subset(*args: Any, **kwargs: Any) -> Solution:
        result = original_solution_for_customer_subset(*args, **kwargs)
        prefix = str(kwargs.get("prefix", ""))
        if prefix == "S2_":
            captured["commit_customer_ids"] = sorted(args[3])
            captured["commit_chunk"] = result
        return result

    dynamic_module._run_stage_plan = wrapped_run_stage_plan
    dynamic_module._solution_for_customer_subset = wrapped_solution_for_customer_subset
    try:
        payload = dynamic_module.run_rolling_reoptimization(
            BUNDLE_DIR,
            output_json_path=OUT_DIR / "seed907_stage_budget_event_density_probe_payload.json",
            seed=907,
            eval_budget=2000,
            max_runtime_seconds=180.0,
            stage_eval_budget=stage_budget,
            stage_max_runtime_seconds=stage_runtime,
            params=RollingParameters(stages=4),
            policy_callback=build_track24_dynamic_policy(spec),
        )
    finally:
        dynamic_module._run_stage_plan = original_run_stage_plan
        dynamic_module._solution_for_customer_subset = original_solution_for_customer_subset

    previous_plan = captured.get("previous_plan")
    previous_instance = captured.get("previous_instance")
    if previous_plan is None or previous_instance is None:
        summary = {"error": "missing stage_001 capture", "payload_gate": payload.get("gate", "")}
        OUT_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"phase": "probe_failed", "out": str(OUT_JSON)}, separators=(",", ":")))
        return 2

    original_route = _route_with_customer(previous_plan, "C32")
    chunk = captured.get("commit_chunk") or _solution_for_customer_subset(
        previous_plan,
        previous_instance,
        bundle.carbon_profile,
        {"C32"},
        prefix="S2_",
    )
    chunk_route = _route_with_customer(chunk, "C32")
    stage_violations = check_solution(previous_plan, previous_instance)
    commit_customer_ids = set(captured.get("commit_customer_ids", ["C32"]))
    chunk_violations = check_solution(chunk, _subinstance_for_customers(previous_instance, commit_customer_ids))
    preserved_chunk = _preserved_prefix_chunk(previous_plan, commit_customer_ids)
    preserved_chunk_violations = check_solution(preserved_chunk, _subinstance_for_customers(previous_instance, commit_customer_ids))
    summary = {
        "payload_gate": payload.get("gate", ""),
        "payload_first_bad_stage": payload.get("first_bad_stage", ""),
        "payload_violations": payload.get("violations", []),
        "stage_001_violation_count": len(stage_violations),
        "stage_001_violations_for_c32": [
            row for row in _violation_rows(stage_violations) if "C32" in str(row.get("location", "")) or "C32" in str(row.get("detail", ""))
        ],
        "original_route_id": getattr(original_route, "vehicle_id", ""),
        "original_vehicle_type": getattr(original_route, "vehicle_type", ""),
        "original_sequence": list(getattr(original_route, "node_sequence", [])),
        "chunk_route_id": getattr(chunk_route, "vehicle_id", ""),
        "chunk_vehicle_type": getattr(chunk_route, "vehicle_type", ""),
        "chunk_sequence": list(getattr(chunk_route, "node_sequence", [])),
        "commit_customer_count": len(captured.get("commit_customer_ids", [])),
        "commit_customer_ids": captured.get("commit_customer_ids", []),
        "commit_chunk_route_count": len(chunk.routes),
        "commit_chunk_routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "node_sequence": list(route.node_sequence),
            }
            for route in chunk.routes
        ],
        "preserved_chunk_route_count": len(preserved_chunk.routes),
        "preserved_chunk_routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "node_sequence": list(route.node_sequence),
            }
            for route in preserved_chunk.routes
        ],
        "preserved_chunk_violations": _violation_rows(preserved_chunk_violations),
        "previous_node_state": _node_state(previous_instance, "C32"),
        "base_node_state": _node_state(bundle.instance, "C32"),
        "original_c32_schedule": _schedule_row(original_route, previous_instance, "C32"),
        "chunk_c32_schedule": _schedule_row(chunk_route, previous_instance, "C32"),
        "chunk_violations": _violation_rows(chunk_violations),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "phase": "probe_done",
                "gate": summary["payload_gate"],
                "stage_violations": summary["stage_001_violation_count"],
                "chunk_violations": len(summary["chunk_violations"]),
                "out": str(OUT_JSON),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
