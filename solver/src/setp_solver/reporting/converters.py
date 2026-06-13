from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SOLUTION_KEYS = (
    "A_carbon_on",
    "B_carbon_weight_zero",
    "baseline_A_carbon_on",
    "carbon_aware",
    "naive_earliest",
    "naive_return_charge",
    "fairness_off",
    "fairness_on",
)


def convert_legacy_reports(reports_dir: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """把旧版 solver/reports JSON 产物转换为统一 schema。"""

    root = Path(reports_dir)
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("._"):
            continue
        data = _read_json(path)
        nested_count = 0
        for key in SOLUTION_KEYS:
            value = data.get(key)
            if isinstance(value, dict):
                nested_count += 1
                records.append(_record_from_solution(path, data, key, value))
        depots = data.get("depots")
        if isinstance(depots, dict):
            for depot_id, depot_node in depots.items():
                if isinstance(depot_node, dict):
                    nested_count += 1
                    records.append(_record_from_solution(path, data, f"pi_d0_{depot_id}", depot_node))
        if nested_count == 0 and _looks_like_top_level_solution(data):
            records.append(_record_from_solution(path, data, "report", data))
        if nested_count == 0 and not _looks_like_top_level_solution(data):
            warnings.append(f"跳过非解类诊断报告：{path.name}")
    return records, warnings


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _looks_like_top_level_solution(data: dict[str, Any]) -> bool:
    return any(key in data for key in ("total_cost", "best_obj", "total_emissions_kg", "feasible", "metrics"))


def _record_from_solution(path: Path, parent: dict[str, Any], label: str, node: dict[str, Any]) -> dict[str, Any]:
    metrics = _metrics(node)
    bundle_dir = parent.get("bundle_dir") or node.get("bundle_dir") or ""
    instance = Path(str(bundle_dir)).name if bundle_dir else ""
    elapsed_seconds = _elapsed_for_label(parent, label)
    total_carbon = _first(metrics, "E_total", default=_first(node, "total_carbon_kg", "total_emissions_kg"))
    charging_carbon = _first(
        metrics,
        "E_ev_indirect",
        default=_first(node, "charging_carbon_kg", "charge_carbon_kg", "ev_charging_emissions_kg"),
    )
    stake = _first(
        node,
        "stake_ev_charging_carbon_over_total_carbon",
        "stake_ev_charge_carbon_over_total_carbon",
    )
    if stake == "" and charging_carbon != "" and total_carbon not in ("", 0, "0"):
        try:
            stake = float(charging_carbon) / float(total_carbon)
        except (TypeError, ValueError, ZeroDivisionError):
            stake = ""
    return {
        "experiment_id": f"{path.stem}__{label}",
        "instance": instance,
        "algorithm": _algorithm_name(path, label),
        "seed": _first(node, "seed", default=parent.get("seed", "")),
        "budget": _first(node, "eval_budget", default=parent.get("eval_budget", "")),
        "cost_fixed": _first(metrics, "cost_fix"),
        "cost_distance": _first(metrics, "cost_km"),
        "cost_fuel": _first(metrics, "cost_fuel"),
        "cost_electricity": _first(metrics, "cost_elec"),
        "cost_occupancy": _first(metrics, "cost_occ"),
        "cost_cross_site": _first(metrics, "cost_transship"),
        "cost_carbon_trading": _first(metrics, "cost_carbon"),
        "total_cost": _first(metrics, "total_cost", default=_first(node, "total_cost", "best_obj")),
        "diesel_carbon_kg": _first(metrics, "E_cv_direct"),
        "charging_carbon_kg": charging_carbon,
        "total_carbon_kg": total_carbon,
        "stake": stake,
        "ev_count": _first(metrics, "n_veh_ev", default=_first(node, "ev_route_count", "ev_routes", "base_ev_route_count")),
        "cv_count": _first(metrics, "n_veh_cv", default=_first(node, "cv_route_count", "cv_routes", "base_cv_route_count")),
        "cross_site_customers": _first(node, "cross_site_customers", default=""),
        "profit_by_depot_json": json.dumps(_profit_payload(node, label), ensure_ascii=False),
        "feasible": _first(node, "feasible", default=parent.get("feasible", "")),
        "elapsed_seconds": _first(node, "elapsed_seconds", default=elapsed_seconds),
        "evals": _first(node, "evaluations", default=parent.get("evaluations", "")),
        "source_report_path": str(path),
    }


def _algorithm_name(path: Path, label: str) -> str:
    if path.name.startswith("pi_d0"):
        return "独立车场ALNS"
    if label == "fairness_off":
        return "ALNS-Wouda（公平关闭）"
    if label == "fairness_on":
        return "ALNS-Wouda（公平开启）"
    if "ablation" in path.name or label in {"carbon_aware", "naive_earliest", "naive_return_charge"}:
        return "ALNS-Wouda（重放）"
    if label == "B_carbon_weight_zero":
        return "ALNS-Wouda（碳权重为零）"
    if "smoke" in path.name:
        return "ALNS-Wouda（烟雾测试）"
    return "ALNS-Wouda"


def _first(mapping: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return default


def _metrics(node: dict[str, Any]) -> dict[str, Any]:
    for key in ("cost_metrics", "metrics"):
        value = node.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _elapsed_for_label(parent: dict[str, Any], label: str) -> Any:
    elapsed = parent.get("elapsed_seconds", "")
    if isinstance(elapsed, dict):
        return elapsed.get(label, "")
    return elapsed


def _profit_payload(node: dict[str, Any], label: str) -> dict[str, Any]:
    if isinstance(node.get("profit_by_depot"), dict):
        return _compact_profit_by_depot(node["profit_by_depot"])
    profit = node.get("profit")
    if isinstance(profit, dict):
        if "profit" in profit and "depot_id" in profit:
            return {profit["depot_id"]: profit["profit"]}
        return _compact_profit_by_depot(profit)
    if profit is not None and label.startswith("pi_d0_"):
        return {label.removeprefix("pi_d0_"): profit}
    if profit is not None:
        return {"合计": profit}
    if label.startswith("pi_d0_"):
        return {label.removeprefix("pi_d0_"): {}}
    return {}


def _compact_profit_by_depot(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for depot_id, value in payload.items():
        if isinstance(value, dict) and "profit" in value:
            compact[str(depot_id)] = value["profit"]
        else:
            compact[str(depot_id)] = value
    return compact
