"""Fairness experiment helpers.

v2026-06-12: V1 adds the independent-depot ``Pi_d0`` pipeline used before
turning the optional profit-fairness checker on. The pipeline writes ordinary
search bundles and reuses the same ALNS adapter/evaluator as cooperative runs.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from ..check import FairnessContext, PROFIT_FAIRNESS, check_solution
from ..cost import evaluate
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..profit import calculate_depot_profits, infer_customer_home_depots
from ..solution import ChargingAction, Route, Solution
from .alns_wouda import SearchPolicy, run_alns_wouda
from .bundle import load_search_bundle


def run_independent_profit_baselines(
    bundle_dir: str | Path,
    output_json_path: str | Path,
    *,
    eval_budget: int = 8000,
    max_runtime_seconds: float = 180.0,
    seed: int = 1,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    carbon_quota_kg: float = 0.0,
    force: bool = False,
) -> dict[str, Any]:
    """Compute ``Pi_d0`` by solving one fixed-customer subproblem per depot."""

    bundle_path = Path(bundle_dir)
    output_path = Path(output_json_path)
    bundle_hash = _bundle_hash(bundle_path)
    if output_path.exists() and not force:
        cached = json.loads(output_path.read_text(encoding="utf-8"))
        if _cache_matches(cached, bundle_path, bundle_hash, eval_budget, max_runtime_seconds, seed, prices, carbon_quota_kg):
            cached["cache_hit"] = True
            return cached

    bundle = load_search_bundle(bundle_path)
    owners = infer_customer_home_depots(bundle.instance)
    depots = sorted(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d")
    cache_root = output_path.parent / f"{output_path.stem}_subbundles"
    cache_root.mkdir(parents=True, exist_ok=True)
    carbon_weight = _carbon_price_weight(prices)

    depot_rows: dict[str, Any] = {}
    independent_profit: dict[str, float] = {}
    for depot_id in depots:
        subbundle_dir = cache_root / depot_id
        sub_instance = _subinstance_for_depot(bundle.instance, depot_id, owners)
        _write_subbundle(subbundle_dir, sub_instance, bundle_path, depot_id)
        result = run_alns_wouda(
            subbundle_dir,
            iterations=None,
            seed=seed,
            carbon_weight=carbon_weight,
            carbon_quota_kg=carbon_quota_kg,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            policy=SearchPolicy(require_charging_signal=False),
        )
        subbundle = load_search_bundle(subbundle_dir)
        sub_owners = {
            node.node_id: depot_id
            for node in subbundle.instance.nodes
            if node.node_type.lower() == "c"
        }
        breakdown = calculate_depot_profits(
            result.best_solution,
            subbundle.instance,
            subbundle.carbon_profile,
            prices,
            customer_home_depot=sub_owners,
            carbon_quota_kg=carbon_quota_kg,
        )[depot_id]
        metrics = evaluate(result.best_solution, subbundle.instance, subbundle.carbon_profile, prices, carbon_quota_kg=carbon_quota_kg)
        violations = check_solution(result.best_solution, subbundle.instance, prices)
        independent_profit[depot_id] = float(breakdown.profit)
        depot_rows[depot_id] = {
            "subbundle_dir": str(subbundle_dir),
            "customer_count": sum(1 for node in subbundle.instance.nodes if node.node_type.lower() == "c"),
            "total_demand_kg": sum(float(node.demand) for node in subbundle.instance.nodes if node.node_type.lower() == "c"),
            "seed": seed,
            "eval_budget": eval_budget,
            "max_runtime_seconds": max_runtime_seconds,
            "evaluations": result.evaluations,
            "feasible": bool(result.feasible and not violations),
            "violation_count": len(violations),
            "best_obj": result.best_obj,
            "route_count": len(result.best_solution.routes),
            "ev_routes": sum(1 for route in result.best_solution.routes if route.vehicle_type.lower() == "ev"),
            "cv_routes": sum(1 for route in result.best_solution.routes if route.vehicle_type.lower() == "cv"),
            "profit": breakdown.to_dict(),
            "metrics": metrics,
            "best_solution": _solution_to_dict(result.best_solution),
        }

    payload = {
        "schema_version": "setp-pi-d0.v1",
        "build_note": "v2026-06-12: V1 independent-depot baseline; same ALNS adapter/evaluator/budget as cooperative runs.",
        "bundle_dir": str(bundle_path),
        "bundle_hash": bundle_hash,
        "customer_home_depot_method": "nearest_depot_in_generated_instance",
        "eval_budget": eval_budget,
        "max_runtime_seconds": max_runtime_seconds,
        "seed": seed,
        "revenue_per_kg": _price(prices, "revenue_per_kg"),
        "fairness_theta": _price(prices, "fairness_theta"),
        "carbon_price": _price(prices, "carbon_price"),
        "carbon_quota_kg": float(carbon_quota_kg),
        "independent_profit": independent_profit,
        "all_independent_profit_positive": all(value > 0.0 for value in independent_profit.values()),
        "depots": depot_rows,
        "cache_hit": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def build_concatenated_independent_seed(
    bundle_dir: str | Path,
    pi_d0_report_path: str | Path,
    *,
    output_json_path: str | Path | None = None,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    carbon_quota_kg: float = 0.0,
) -> dict[str, Any]:
    """Merge cached independent-depot solutions into one cooperative seed."""

    bundle = load_search_bundle(bundle_dir)
    report = json.loads(Path(pi_d0_report_path).read_text(encoding="utf-8"))
    independent_profit = {depot_id: float(value) for depot_id, value in report["independent_profit"].items()}
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for depot_id, row in sorted(report["depots"].items()):
        if "best_solution" not in row:
            raise ValueError(f"Pi_d0 report for {depot_id} has no best_solution; rerun run_independent_profit_baselines with force=True")
        solution = _solution_from_dict(row["best_solution"])
        vehicle_id_map: dict[str, str] = {}
        for route in solution.routes:
            new_id = f"{depot_id}_{route.vehicle_id}"
            vehicle_id_map[route.vehicle_id] = new_id
            routes.append(
                Route(
                    vehicle_id=new_id,
                    vehicle_type=route.vehicle_type,
                    home_depot_id=route.home_depot_id,
                    node_sequence=list(route.node_sequence),
                )
            )
        for action in solution.charging_actions:
            actions.append(
                ChargingAction(
                    vehicle_id=vehicle_id_map.get(action.vehicle_id, f"{depot_id}_{action.vehicle_id}"),
                    station_id=action.station_id,
                    energy_kwh=action.energy_kwh,
                    occupancy_minutes=action.occupancy_minutes,
                    charge_start_second=action.charge_start_second,
                    charge_day_offset=action.charge_day_offset,
                )
            )
    seed = Solution(routes=routes, charging_actions=actions, cross_site_services=[])
    owners = infer_customer_home_depots(bundle.instance)
    breakdowns = calculate_depot_profits(seed, bundle.instance, bundle.carbon_profile, prices, customer_home_depot=owners, carbon_quota_kg=carbon_quota_kg)
    metrics = evaluate(seed, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=carbon_quota_kg)
    fairness_context = {
        "depot_profit": {depot_id: breakdowns[depot_id].profit for depot_id in independent_profit},
        "independent_profit": independent_profit,
        "theta": _price(prices, "fairness_theta"),
    }
    violations = check_solution(
        seed,
        bundle.instance,
        prices,
        fairness_context=FairnessContext(**fairness_context),
        fairness_enabled=True,
    )
    source_cost_sum = sum(float(row["metrics"]["total_cost"]) for row in report["depots"].values())
    ratio = {
        depot_id: breakdowns[depot_id].profit / independent_profit[depot_id]
        for depot_id in independent_profit
    }
    payload = {
        "schema_version": "setp-independent-concat-seed.v1",
        "build_note": "v2026-06-12: X0 concatenates independent-depot best solutions as the theta=1.0 cooperative seed.",
        "bundle_dir": str(Path(bundle_dir)),
        "pi_d0_report_path": str(Path(pi_d0_report_path)),
        "theta": _price(prices, "fairness_theta"),
        "carbon_price": _price(prices, "carbon_price"),
        "carbon_quota_kg": float(carbon_quota_kg),
        "feasible": len(violations) == 0,
        "violations": [violation.__dict__ for violation in violations],
        "independent_profit": independent_profit,
        "profit": {depot_id: row.to_dict() for depot_id, row in breakdowns.items()},
        "profit_ratio": ratio,
        "max_profit_ratio_abs_error_from_one": max((abs(value - 1.0) for value in ratio.values()), default=0.0),
        "metrics": metrics,
        "source_independent_total_cost_sum": source_cost_sum,
        "total_cost_abs_error_from_source_sum": abs(float(metrics["total_cost"]) - source_cost_sum),
        "solution": _solution_to_dict(seed),
    }
    if output_json_path is not None:
        output_path = Path(output_json_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def run_equal_budget_fairness_comparison(
    bundle_dir: str | Path,
    pi_d0_report_path: str | Path,
    seed_report_path: str | Path,
    *,
    output_json_path: str | Path | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 360.0,
    seed: int = 1,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> dict[str, Any]:
    """Run X1 fairness-on/off from the concatenated independent seed.

    v2026-06-12: X1 makes the fairness-enabled recipe constructive: start from
    the independent-depot concatenation and give the cooperative run the same
    total evaluation budget used to compute all depot baselines.
    """

    bundle = load_search_bundle(bundle_dir)
    pi_report = json.loads(Path(pi_d0_report_path).read_text(encoding="utf-8"))
    seed_report = json.loads(Path(seed_report_path).read_text(encoding="utf-8"))
    independent_profit = {depot_id: float(value) for depot_id, value in pi_report["independent_profit"].items()}
    initial_solution = _solution_from_dict(seed_report["solution"])
    owners = infer_customer_home_depots(bundle.instance)
    theta = _price(prices, "fairness_theta")

    baseline = _summarize_solution(
        "independent_concat_seed",
        initial_solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        independent_profit,
        owners,
        theta,
    )
    fairness_on = run_alns_wouda(
        bundle.bundle_dir,
        iterations=None,
        seed=seed,
        carbon_weight=1.0,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        policy=SearchPolicy(require_charging_signal=False),
        fairness_enabled=True,
        independent_profit=independent_profit,
        fairness_theta=theta,
        customer_home_depot=owners,
        initial_solution=initial_solution,
    )
    fairness_off = run_alns_wouda(
        bundle.bundle_dir,
        iterations=None,
        seed=seed,
        carbon_weight=1.0,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        policy=SearchPolicy(require_charging_signal=False),
        fairness_enabled=False,
        independent_profit=independent_profit,
        fairness_theta=theta,
        customer_home_depot=owners,
        initial_solution=initial_solution,
    )

    on_report = _summarize_run("fairness_on", fairness_on, bundle.instance, bundle.carbon_profile, prices, independent_profit, owners, theta)
    off_report = _summarize_run("fairness_off", fairness_off, bundle.instance, bundle.carbon_profile, prices, independent_profit, owners, theta)
    payload = {
        "schema_version": "setp-fairness-equal-budget-comparison.v1",
        "build_note": "v2026-06-12: X1 uses concatenated independent seed plus equal 16000-eval budget for theta=1.0 fairness.",
        "bundle_dir": str(bundle.bundle_dir),
        "pi_d0_report_path": str(Path(pi_d0_report_path)),
        "seed_report_path": str(Path(seed_report_path)),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "seed": int(seed),
        "theta": theta,
        "initial_seed": baseline,
        "fairness_on": on_report,
        "fairness_off": off_report,
        "fairness_constrained_saving_vs_seed": float(baseline["metrics"]["total_cost"]) - float(on_report["metrics"]["total_cost"]),
        "fairness_cost_vs_off": float(on_report["metrics"]["total_cost"]) - float(off_report["metrics"]["total_cost"]),
        "fairness_on_improves_or_matches_seed": float(on_report["metrics"]["total_cost"]) <= float(baseline["metrics"]["total_cost"]) + 1e-6,
        "fairness_on_feasible": bool(on_report["physical_feasible"] and on_report["fairness_feasible"]),
    }
    if output_json_path is not None:
        output_path = Path(output_json_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _subinstance_for_depot(instance: Instance, depot_id: str, owners: dict[str, str]) -> Instance:
    keep_ids = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "f"
        or node.node_id == depot_id
        or (node.node_type.lower() == "c" and owners.get(node.node_id) == depot_id)
    }
    nodes = [node for node in instance.nodes if node.node_id in keep_ids]
    old_index = instance.node_index
    indices = [old_index[node.node_id] for node in nodes]
    matrix = np.asarray(instance.distance_matrix, dtype=float)[np.ix_(indices, indices)].tolist()
    return Instance(nodes=nodes, distance_matrix=matrix)


def _write_subbundle(path: Path, instance: Instance, source_bundle_dir: Path, depot_id: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    instance_payload = {
        "scenario_id": f"{source_bundle_dir.name}__independent_{depot_id}",
        "seed": 0,
        "nodes": [_node_payload(node) for node in instance.nodes],
        "distance_unit": "meter",
        "time_unit": "second",
        "demand_unit": "kg",
        "metadata": {
            "source_bundle_dir": str(source_bundle_dir),
            "independent_depot_id": depot_id,
            "build_note": "v2026-06-12: V1 independent-depot Pi_d0 subbundle.",
        },
    }
    (path / "instance.json").write_text(json.dumps(instance_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    np.save(path / "distance_matrix.npy", np.asarray(instance.distance_matrix, dtype=float))
    shutil.copyfile(source_bundle_dir / "carbon_profile.csv", path / "carbon_profile.csv")
    manifest = {
        "schema_version": "setp-independent-depot-subbundle.v1",
        "source_bundle_dir": str(source_bundle_dir),
        "independent_depot_id": depot_id,
        "customer_count": sum(1 for node in instance.nodes if node.node_type.lower() == "c"),
    }
    (path / "scenario_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _node_payload(node: Node) -> dict[str, Any]:
    payload = asdict(node)
    if payload.get("charge_power_kw") is None:
        payload.pop("charge_power_kw", None)
    return payload


def _summarize_run(
    label: str,
    result: Any,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    independent_profit: dict[str, float],
    customer_home_depot: dict[str, str],
    theta: float,
) -> dict[str, Any]:
    summary = _summarize_solution(
        label,
        result.best_solution,
        instance,
        carbon_profile,
        prices,
        independent_profit,
        customer_home_depot,
        theta,
    )
    summary.update(
        {
            "initial_obj": float(result.initial_obj),
            "best_obj": float(result.best_obj),
            "evaluations": int(result.evaluations),
            "alns_reported_feasible": bool(result.feasible),
            "destroy_operator_counts": result.destroy_operator_counts,
            "repair_operator_counts": result.repair_operator_counts,
        }
    )
    return summary


def _summarize_solution(
    label: str,
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    independent_profit: dict[str, float],
    customer_home_depot: dict[str, str],
    theta: float,
) -> dict[str, Any]:
    breakdowns = calculate_depot_profits(
        solution,
        instance,
        carbon_profile,
        prices,
        customer_home_depot=customer_home_depot,
    )
    depot_profit = {depot_id: row.profit for depot_id, row in breakdowns.items()}
    fairness_context = FairnessContext(depot_profit=depot_profit, independent_profit=dict(independent_profit), theta=float(theta))
    physical_violations = check_solution(solution, instance, prices, fairness_enabled=False)
    all_violations = check_solution(solution, instance, prices, fairness_context=fairness_context, fairness_enabled=True)
    fairness_violations = [violation for violation in all_violations if violation.type == PROFIT_FAIRNESS]
    ratios = {
        depot_id: depot_profit.get(depot_id, 0.0) / baseline
        for depot_id, baseline in independent_profit.items()
    }
    metrics = evaluate(solution, instance, carbon_profile, prices)
    return {
        "label": label,
        "physical_feasible": len(physical_violations) == 0,
        "fairness_feasible": len(fairness_violations) == 0,
        "physical_violations": [violation.__dict__ for violation in physical_violations],
        "fairness_violations": [violation.__dict__ for violation in fairness_violations],
        "profit": {depot_id: row.to_dict() for depot_id, row in breakdowns.items()},
        "profit_ratio": ratios,
        "metrics": metrics,
        "route_count": len(solution.routes),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "charging_event_count": len(solution.charging_actions),
        "solution": _solution_to_dict(solution),
    }


def _bundle_hash(bundle_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in ("instance.json", "distance_matrix.npy", "carbon_profile.csv"):
        path = bundle_dir / name
        digest.update(name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _cache_matches(
    cached: dict[str, Any],
    bundle_dir: Path,
    bundle_hash: str,
    eval_budget: int,
    max_runtime_seconds: float,
    seed: int,
    prices: PriceParameters | dict[str, float] | Any,
    carbon_quota_kg: float,
) -> bool:
    return (
        cached.get("bundle_dir") == str(bundle_dir)
        and cached.get("bundle_hash") == bundle_hash
        and int(cached.get("eval_budget", -1)) == int(eval_budget)
        and abs(float(cached.get("max_runtime_seconds", -1.0)) - float(max_runtime_seconds)) <= 1e-9
        and int(cached.get("seed", -1)) == int(seed)
        and abs(float(cached.get("revenue_per_kg", -1.0)) - _price(prices, "revenue_per_kg")) <= 1e-12
        and abs(float(cached.get("carbon_price", -1.0)) - _price(prices, "carbon_price")) <= 1e-12
        and abs(float(cached.get("carbon_quota_kg", -1.0)) - float(carbon_quota_kg)) <= 1e-9
    )


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _carbon_price_weight(prices: PriceParameters | dict[str, float] | Any) -> float:
    # v2026-06-12: W2a makes Pi_d0 search follow the same p_car switch used by
    # its evaluator. This prevents no-trading ablations from searching under the
    # default carbon price and only zeroing the reporting pass afterward.
    default = float(DEFAULT_PRICES.carbon_price)
    return 0.0 if abs(default) <= 1e-12 else _price(prices, "carbon_price") / default


def _solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": list(route.node_sequence),
            }
            for route in solution.routes
        ],
        "charging_actions": [
            {
                "vehicle_id": action.vehicle_id,
                "station_id": action.station_id,
                "energy_kwh": float(action.energy_kwh),
                "occupancy_minutes": float(action.occupancy_minutes),
                "charge_start_second": float(action.charge_start_second),
                "charge_day_offset": int(action.charge_day_offset),
            }
            for action in solution.charging_actions
        ],
    }


def _solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(node_id) for node_id in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
                charge_day_offset=int(row.get("charge_day_offset", 0)),
            )
            for row in payload.get("charging_actions", [])
        ],
    )
