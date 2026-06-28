from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import Solution

from .action_space import BLOCK_Q_RATIOS, BLOCK_THRESHOLD_RATIOS, REPAIR_IDS
from .schemas import LearnedDestroyDecodedAction


LEARNED_DESTROY_CONTROL_MODE = "learned_destroy"
LEARNED_DESTROY_ID = "learned_customer_removal"
LEARNED_CUSTOMER_FEATURE_NAMES = (
    "x_norm",
    "y_norm",
    "demand_norm",
    "ready_norm",
    "due_norm",
    "time_window_width_norm",
    "service_time_norm",
    "route_index_norm",
    "position_norm",
    "route_customer_count_norm",
    "prev_arc_norm",
    "next_arc_norm",
    "removal_saving_norm",
    "nearest_depot_norm",
    "nearest_station_norm",
    "route_is_ev",
    "route_has_charge_action",
    "carbon_ready_intensity_norm",
)
LEARNED_CUSTOMER_FEATURE_DIM = len(LEARNED_CUSTOMER_FEATURE_NAMES)
LEARNED_GLOBAL_OBSERVATION_SIZE = 24


@dataclass(frozen=True)
class CustomerFeaturePayload:
    customer_ids: tuple[str, ...]
    feature_names: tuple[str, ...]
    features: tuple[tuple[float, ...], ...]
    mask: tuple[bool, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "customer_ids": list(self.customer_ids),
            "feature_names": list(self.feature_names),
            "features": [list(row) for row in self.features],
            "mask": [bool(value) for value in self.mask],
        }


def customer_feature_payload(solution: Solution, instance: Instance, carbon_profile: list[dict[str, Any]]) -> CustomerFeaturePayload:
    node_lookup = {node.node_id: node for node in instance.nodes}
    customers = [node for node in instance.nodes if node.node_type.lower() == "c"]
    customer_ids_in_solution, route_lookup = _customers_in_solution_order(solution, instance)
    missing = sorted(node.node_id for node in customers if node.node_id not in set(customer_ids_in_solution))
    ordered_ids = [*customer_ids_in_solution, *missing]
    if not ordered_ids:
        return CustomerFeaturePayload((), LEARNED_CUSTOMER_FEATURE_NAMES, (), ())

    max_abs_x = max(1.0, max(abs(float(node.x)) for node in instance.nodes))
    max_abs_y = max(1.0, max(abs(float(node.y)) for node in instance.nodes))
    max_demand = max(1.0, max(max(0.0, float(node.demand)) for node in customers))
    max_due = max(1.0, max(float(node.due_time) for node in instance.nodes))
    max_service = max(1.0, max(float(node.service_time) for node in customers))
    max_distance = _max_distance(instance)
    max_route_customers = max(1, max((len(_route_customer_ids(route, instance)) for route in solution.routes), default=1))
    carbon_min, carbon_span = _carbon_range(carbon_profile)
    station_ids = [node.node_id for node in instance.nodes if node.node_type.lower() == "f"]
    depot_ids = [node.node_id for node in instance.nodes if node.node_type.lower() == "d"]
    charged_vehicle_ids = {
        action.vehicle_id
        for action in solution.charging_actions
        if float(action.energy_kwh) > 1e-9
    }

    rows: list[tuple[float, ...]] = []
    mask: list[bool] = []
    for customer_id in ordered_ids:
        node = node_lookup[customer_id]
        route_info = route_lookup.get(customer_id)
        route_idx = route_info["route_idx"] if route_info else -1
        position_idx = route_info["position_idx"] if route_info else -1
        route_len = route_info["route_customer_count"] if route_info else 0
        route = route_info["route"] if route_info else None
        prev_node = route_info["prev_node"] if route_info else customer_id
        next_node = route_info["next_node"] if route_info else customer_id
        prev_arc = _distance(instance, prev_node, customer_id)
        next_arc = _distance(instance, customer_id, next_node)
        bypass = _distance(instance, prev_node, next_node)
        removal_saving = max(0.0, prev_arc + next_arc - bypass)
        nearest_depot = _nearest_distance(instance, customer_id, depot_ids)
        nearest_station = _nearest_distance(instance, customer_id, station_ids)
        carbon_value = _carbon_at_ready(carbon_profile, float(node.ready_time), carbon_min, carbon_span)
        route_count_denom = max(1, len(solution.routes) - 1)
        position_denom = max(1, int(route_len) - 1)
        row = (
            _clip(float(node.x) / max_abs_x),
            _clip(float(node.y) / max_abs_y),
            _clip(max(0.0, float(node.demand)) / max_demand),
            _clip(float(node.ready_time) / max_due),
            _clip(float(node.due_time) / max_due),
            _clip(max(0.0, float(node.due_time) - float(node.ready_time)) / max_due),
            _clip(float(node.service_time) / max_service),
            0.0 if route_idx < 0 else _clip(float(route_idx) / float(route_count_denom)),
            0.0 if position_idx < 0 else _clip(float(position_idx) / float(position_denom)),
            _clip(float(route_len) / float(max_route_customers)),
            _clip(prev_arc / max_distance),
            _clip(next_arc / max_distance),
            _clip(removal_saving / max_distance),
            _clip(nearest_depot / max_distance),
            _clip(nearest_station / max_distance),
            1.0 if route is not None and route.vehicle_type.lower() == "ev" else 0.0,
            1.0 if route is not None and route.vehicle_id in charged_vehicle_ids else 0.0,
            _clip(carbon_value),
        )
        rows.append(tuple(float(value) for value in row))
        mask.append(route_info is not None)
    return CustomerFeaturePayload(
        customer_ids=tuple(ordered_ids),
        feature_names=LEARNED_CUSTOMER_FEATURE_NAMES,
        features=tuple(rows),
        mask=tuple(mask),
    )


def customer_feature_payload_json(solution: Solution, instance: Instance, carbon_profile: list[dict[str, Any]]) -> dict[str, Any]:
    return customer_feature_payload(solution, instance, carbon_profile).to_json()


def global_observation_from_response(
    response: dict[str, Any],
    *,
    eval_budget: int,
    bundle_dir: str,
    curriculum_phase: str = "route",
) -> np.ndarray:
    metrics = response.get("metrics", {}) or {}
    trace = response.get("trace", {}) or {}
    current_obj = _float(response.get("current_obj"), 0.0)
    best_obj = _float(response.get("best_obj"), current_obj)
    gap = (current_obj - best_obj) / max(abs(best_obj), 1.0)
    budget_progress = _float(response.get("actual_evals"), 0.0) / max(float(eval_budget), 1.0)

    block_iterations = max(1.0, _float(trace.get("block_iterations"), 1.0))
    accepted_rate = _float(trace.get("block_accepted_count"), 0.0) / block_iterations
    improved_current_rate = _float(trace.get("block_improved_current_count"), 0.0) / block_iterations
    improved_best_rate = _float(trace.get("block_improved_best_count"), 0.0) / block_iterations
    rejected_rate = _float(trace.get("block_rejected_count"), 0.0) / block_iterations

    best_delta = -_float(trace.get("block_best_delta"), 0.0) / max(abs(_float(trace.get("block_start_best_obj"), best_obj)), 1.0)
    current_delta = -_float(trace.get("block_current_delta"), 0.0) / max(abs(_float(trace.get("block_start_current_obj"), current_obj)), 1.0)
    route_count = _route_count(response)
    best_route_count = int(_float(trace.get("block_end_best_route_count"), route_count))
    lower_bound = int(_float(trace.get("capacity_route_lower_bound"), 0.0))
    route_gap = (best_route_count - lower_bound) / max(float(best_route_count), 1.0)
    route_delta = _float(trace.get("block_best_route_delta"), 0.0) / max(float(max(best_route_count, 1)), 1.0)
    cv_routes = _float(metrics.get("n_veh_cv"), 0.0)
    ev_routes = _float(metrics.get("n_veh_ev"), 0.0)
    ev_share = ev_routes / max(ev_routes + cv_routes, 1.0)
    charge_ratio = _charge_ratio(response)
    total_cost = _float(metrics.get("total_cost"), 0.0)
    fix_share = abs(_float(metrics.get("cost_fix"), 0.0)) / max(abs(total_cost), 1.0)
    km_share = abs(_float(metrics.get("cost_km"), 0.0)) / max(abs(total_cost), 1.0)

    values = np.array(
        [
            gap,
            budget_progress,
            best_delta,
            current_delta,
            accepted_rate,
            improved_current_rate,
            improved_best_rate,
            rejected_rate,
            route_gap,
            route_delta,
            ev_share,
            charge_ratio,
            fix_share,
            km_share,
            _float(trace.get("block_requested_q_ratio"), 0.0),
            _float(trace.get("block_requested_threshold_ratio"), 0.0) / 0.02,
            _float(trace.get("exploration_ratio"), 0.0),
            _float(trace.get("stagnation_steps"), 0.0) / max(float(eval_budget), 1.0),
            min(1.0, max(0.0, _float(response.get("violation_count"), 0.0))),
            _scale_feature(bundle_dir),
            _phase_feature(curriculum_phase),
            min(1.0, _float(trace.get("learned_destroy_selected_count"), 0.0) / 32.0),
            1.0 if str(trace.get("control_mode", "")) == LEARNED_DESTROY_CONTROL_MODE else 0.0,
            0.0,
        ],
        dtype=np.float32,
    )
    return np.clip(values, -10.0, 10.0).astype(np.float32)


def learned_destroy_reward(response: dict[str, Any], *, initial_obj: float | None, eval_budget: int, terminated: bool) -> float:
    trace = response.get("trace", {}) or {}
    start_best = _float(trace.get("block_start_best_obj"), response.get("best_obj", 0.0))
    end_best = _float(trace.get("block_end_best_obj"), response.get("best_obj", start_best))
    start_current = _float(trace.get("block_start_current_obj"), response.get("current_obj", 0.0))
    end_current = _float(trace.get("block_end_current_obj"), response.get("current_obj", start_current))
    best_gain = max(0.0, (start_best - end_best) / max(abs(start_best), 1.0))
    current_gain = max(0.0, (start_current - end_current) / max(abs(start_current), 1.0))
    accepted = 1.0 if response.get("accepted") else 0.0
    candidate_violations = _float(trace.get("candidate_violation_count"), response.get("violation_count", 0.0))
    reward = 120.0 * best_gain + 20.0 * current_gain + 0.05 * accepted
    if candidate_violations > 0:
        reward -= min(5.0, candidate_violations)
    if terminated and initial_obj is not None:
        final_gain = max(0.0, (float(initial_obj) - end_best) / max(abs(float(initial_obj)), 1.0))
        reward += min(10.0, 100.0 * final_gain)
    if int(response.get("actual_evals", 0)) >= int(eval_budget) and int(response.get("violation_count", 0)) != 0:
        reward -= 10.0
    return float(reward)


def decode_learned_destroy_action(
    raw: dict[str, Any],
    *,
    customer_ids: list[str] | tuple[str, ...],
    block_size: int = 1,
) -> LearnedDestroyDecodedAction:
    repair_idx = int(raw.get("repair_idx", 0))
    q_idx = int(raw.get("q_idx", 0))
    threshold_idx = int(raw.get("threshold_idx", 0))
    selected_indices = [int(value) for value in raw.get("selected_indices", [])]
    selected_count = int(raw.get("selected_count", len(selected_indices)))
    if not 0 <= repair_idx < len(REPAIR_IDS):
        raise ValueError(f"learned repair index out of range: {repair_idx}")
    if not 0 <= q_idx < len(BLOCK_Q_RATIOS):
        raise ValueError(f"learned q index out of range: {q_idx}")
    if not 0 <= threshold_idx < len(BLOCK_THRESHOLD_RATIOS):
        raise ValueError(f"learned threshold index out of range: {threshold_idx}")
    if int(block_size) != 1:
        raise ValueError("learned_destroy requires block_size=1 so the policy sees fresh customer features")
    ids = tuple(str(customer_ids[idx]) for idx in selected_indices[:selected_count] if 0 <= idx < len(customer_ids))
    if not ids:
        raise ValueError("learned_destroy requires at least one selected customer")
    return LearnedDestroyDecodedAction(
        repair_id=REPAIR_IDS[repair_idx],
        q_ratio=float(BLOCK_Q_RATIOS[q_idx]),
        threshold_ratio=float(BLOCK_THRESHOLD_RATIOS[threshold_idx]),
        block_size=1,
        remove_customer_ids=ids,
        raw=(repair_idx, q_idx, threshold_idx, *selected_indices[:selected_count]),
    )


def customer_arrays(payload: dict[str, Any], *, max_customers: int | None = None) -> tuple[np.ndarray, np.ndarray, list[str]]:
    ids = [str(value) for value in payload.get("customer_ids", [])]
    features = np.asarray(payload.get("features", []), dtype=np.float32)
    if features.ndim == 1:
        features = features.reshape((0, LEARNED_CUSTOMER_FEATURE_DIM))
    mask = np.asarray(payload.get("mask", []), dtype=bool)
    if max_customers is None:
        max_customers = max(1, int(features.shape[0]))
    padded_features = np.zeros((int(max_customers), LEARNED_CUSTOMER_FEATURE_DIM), dtype=np.float32)
    padded_mask = np.zeros((int(max_customers),), dtype=bool)
    n = min(int(max_customers), int(features.shape[0]), len(ids), int(mask.shape[0]))
    if n > 0:
        padded_features[:n, :] = features[:n, :LEARNED_CUSTOMER_FEATURE_DIM]
        padded_mask[:n] = mask[:n]
    if not bool(padded_mask.any()) and n > 0:
        padded_mask[0] = True
    return padded_features, padded_mask, ids[:n]


def _customers_in_solution_order(solution: Solution, instance: Instance) -> tuple[list[str], dict[str, dict[str, Any]]]:
    seen: set[str] = set()
    ordered: list[str] = []
    lookup: dict[str, dict[str, Any]] = {}
    for route_idx, route in enumerate(solution.routes):
        customers = _route_customer_ids(route, instance)
        route_positions = {customer_id: idx for idx, customer_id in enumerate(customers)}
        for seq_idx, node_id in enumerate(route.node_sequence):
            if node_id not in route_positions or node_id in seen:
                continue
            seen.add(node_id)
            ordered.append(node_id)
            lookup[node_id] = {
                "route": route,
                "route_idx": route_idx,
                "position_idx": route_positions[node_id],
                "route_customer_count": len(customers),
                "prev_node": route.node_sequence[max(0, seq_idx - 1)],
                "next_node": route.node_sequence[min(len(route.node_sequence) - 1, seq_idx + 1)],
            }
    return ordered, lookup


def _route_customer_ids(route: Any, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [
        str(node_id)
        for node_id in route.node_sequence
        if node_lookup.get(str(node_id)) is not None and node_lookup[str(node_id)].node_type.lower() == "c"
    ]


def _max_distance(instance: Instance) -> float:
    best = 1.0
    for row in instance.distance_matrix:
        for value in row:
            if math.isfinite(float(value)):
                best = max(best, float(value))
    return best


def _distance(instance: Instance, left: str, right: str) -> float:
    try:
        value = float(instance.distance(left, right))
    except Exception:
        return 0.0
    return value if math.isfinite(value) else 0.0


def _nearest_distance(instance: Instance, customer_id: str, target_ids: list[str]) -> float:
    if not target_ids:
        return 0.0
    return min(_distance(instance, customer_id, target_id) for target_id in target_ids)


def _carbon_range(carbon_profile: list[dict[str, Any]]) -> tuple[float, float]:
    values = [_carbon_intensity(row) for row in carbon_profile]
    values = [value for value in values if math.isfinite(value)]
    if not values:
        return 0.0, 1.0
    return min(values), max(max(values) - min(values), 1.0)


def _carbon_at_ready(carbon_profile: list[dict[str, Any]], ready_time: float, carbon_min: float, carbon_span: float) -> float:
    if not carbon_profile:
        return 0.0
    row = min(
        carbon_profile,
        key=lambda item: abs(float(item.get("horizon_second_start", 0.0)) - float(ready_time)),
    )
    return (_carbon_intensity(row) - carbon_min) / carbon_span


def _carbon_intensity(row: dict[str, Any]) -> float:
    return float(row.get("forecast_gco2_per_kwh", row.get("actual_gco2_per_kwh", 0.0)) or 0.0)


def _route_count(response: dict[str, Any]) -> int:
    solution = response.get("solution", {}) if isinstance(response, dict) else {}
    routes = solution.get("routes", []) if isinstance(solution, dict) else []
    return len(routes) if isinstance(routes, list) else 0


def _charge_ratio(response: dict[str, Any]) -> float:
    route_count = max(float(_route_count(response)), 1.0)
    solution = response.get("solution", {}) if isinstance(response, dict) else {}
    actions = solution.get("charging_actions", []) if isinstance(solution, dict) else []
    return float(len(actions) if isinstance(actions, list) else 0) / route_count


def _scale_feature(bundle_dir: str) -> float:
    lowered = str(bundle_dir).lower()
    for customers in (200, 150, 100, 75, 50, 25):
        if f"{customers}c" in lowered or f"uk{customers}" in lowered:
            return min(1.0, float(customers) / 200.0)
    return 0.0


def _phase_feature(phase: str) -> float:
    phases = ("route", "energy", "carbon", "dynamic")
    try:
        return float(phases.index(str(phase))) / max(float(len(phases) - 1), 1.0)
    except ValueError:
        return 0.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(result):
        return float(default)
    return result


def _clip(value: float) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return max(-10.0, min(10.0, float(value)))


__all__ = [
    "CustomerFeaturePayload",
    "LEARNED_CUSTOMER_FEATURE_DIM",
    "LEARNED_CUSTOMER_FEATURE_NAMES",
    "LEARNED_DESTROY_CONTROL_MODE",
    "LEARNED_DESTROY_ID",
    "LEARNED_GLOBAL_OBSERVATION_SIZE",
    "customer_arrays",
    "customer_feature_payload",
    "customer_feature_payload_json",
    "decode_learned_destroy_action",
    "global_observation_from_response",
    "learned_destroy_reward",
]
