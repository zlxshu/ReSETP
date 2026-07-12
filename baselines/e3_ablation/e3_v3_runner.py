#!/usr/bin/env python3
"""Strict physical-vehicle E3 runner with resumable seed-first execution."""

from __future__ import annotations

import argparse
import concurrent.futures
from contextlib import contextmanager
import csv
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e2_alns import e2_final_closure as closure
from baselines.e3_ablation.e3_multitrip_structure_gate import _short_trips
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_staged_alns_lns_hybrid,
    run_tvci_alns,
    run_tvci_carbon_schedule_pair,
)
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import calculate_depot_profits, infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.search.fairness import _subinstance_for_depot, _write_subbundle
from setp_solver.search.formal_runner import _derive_carbon_profile
from setp_solver.search.multitrip_schedule import CONTRACT_ID, MultiTripCertificate
from setp_solver.search.submission_contract import FULL_MODEL_LANE, load_submission_contract
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution, physical_vehicle_id


DEFAULT_OUT = ROOT / "baselines/e3_ablation/e3_v3_clean_20260713"
CONTRACT_DIR = ROOT / "baselines/contract_audit/submission_contract_candidate_20260711"
CONTRACT_PATH = CONTRACT_DIR / "submission_contract.proposed.json"
OWNER_ROWS = CONTRACT_DIR / "customer_owner_rows.csv"
STRUCTURE_200 = ROOT / "baselines/e3_ablation/e3_multitrip_structure_gate_v2_20260713"
INSTANCE_NAMES = {
    "100c": "L-main-threeshift-100c-01",
    "200c": "L-main-threeshift-200c-01",
}
LAYERS = ("M0", "M1", "M2", "M3", "M4", "M5")
METRIC_KEYS = (
    "total_cost",
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
    "E_total",
    "E_cv_direct",
    "E_ev_indirect",
    "electricity_kwh",
    "distance_total",
)
EXECUTION_SOURCE_PATHS = (
    "baselines/e3_ablation/e3_v3_runner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
    "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    "solver/src/setp_solver/search/multitrip_schedule.py",
    "solver/src/setp_solver/search/submission_contract.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(service) for service in solution.cross_site_services],
    }


def solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in payload.get("cross_site_services", [])],
    )


def route_signature(solution: Solution) -> str:
    payload = sorted(
        (route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence))
        for route in solution.routes
    )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def owner_map(instance_name: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    with OWNER_ROWS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["instance"] == instance_name:
                rows[row["customer_id"]] = row["home_depot_id"]
    if not rows:
        raise ValueError(f"no frozen owner rows for {instance_name}")
    return rows


def annotate_cross_site(solution: Solution, owners: dict[str, str]) -> Solution:
    services = [
        CrossSiteService(customer_id=node_id, served_by_depot_id=route.home_depot_id)
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if owners.get(node_id) != route.home_depot_id
    ]
    return replace(solution, cross_site_services=services)


def write_derived_bundles(source_dir: Path, target_root: Path) -> dict[str, str]:
    source = load_search_bundle(source_dir)
    result: dict[str, str] = {}
    for mode in ("zero_gamma", "mean_gamma", "actual_gamma"):
        target = target_root / mode
        target.mkdir(parents=True, exist_ok=True)
        for name in ("instance.json", "distance_matrix.npy", "scenario_manifest.json"):
            shutil.copyfile(source_dir / name, target / name)
        profile = _derive_carbon_profile(source.carbon_profile, mode)
        with (target / "carbon_profile.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(profile[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(profile)
        result[mode] = str(target.relative_to(ROOT))
    return result


def _structure_routes(size: str, instance: Instance, prices: Any) -> tuple[list[Route], list[Route]]:
    if size == "200c" and STRUCTURE_200.exists():
        independent = read_json(STRUCTURE_200 / "solo_business_partial_certificate.json")["routes"]
        shared = read_json(STRUCTURE_200 / "shared_business_partial_certificate.json")["routes"]
        return [Route(**row) for row in independent], [Route(**row) for row in shared]
    return (
        _short_trips(instance, independent=True, prices=prices),
        _short_trips(instance, independent=False, prices=prices),
    )


def _depot_counts(certificate: MultiTripCertificate) -> dict[str, dict[str, int]]:
    seen: dict[tuple[str, str], set[str]] = {}
    for trip in certificate.trips:
        seen.setdefault((trip.home_depot_id, trip.vehicle_type), set()).add(trip.physical_vehicle_id)
    depots = sorted({trip.home_depot_id for trip in certificate.trips})
    return {
        depot: {kind: len(seen.get((depot, kind), set())) for kind in ("cv", "ev")}
        for depot in depots
    }


@contextmanager
def strict_mode(caps: dict[str, dict[str, int]] | None = None) -> Iterable[None]:
    old_flag = os.environ.get("SETP_E3_STRICT_MULTITRIP")
    old_caps = os.environ.get("SETP_E3_DEPOT_ASSET_CAPS_JSON")
    os.environ["SETP_E3_STRICT_MULTITRIP"] = "1"
    if caps is None:
        os.environ.pop("SETP_E3_DEPOT_ASSET_CAPS_JSON", None)
    else:
        os.environ["SETP_E3_DEPOT_ASSET_CAPS_JSON"] = json.dumps(caps, sort_keys=True)
    try:
        yield
    finally:
        if old_flag is None:
            os.environ.pop("SETP_E3_STRICT_MULTITRIP", None)
        else:
            os.environ["SETP_E3_STRICT_MULTITRIP"] = old_flag
        if old_caps is None:
            os.environ.pop("SETP_E3_DEPOT_ASSET_CAPS_JSON", None)
        else:
            os.environ["SETP_E3_DEPOT_ASSET_CAPS_JSON"] = old_caps


def prepare_assets(out: Path, size: str) -> dict[str, Any]:
    instance_name = INSTANCE_NAMES[size]
    target = out / "assets" / size
    manifest_path = target / "asset_manifest.json"
    source_dir = closure._resolve_bundle_dir("threeshift", instance_name)
    source = load_search_bundle(source_dir)
    owners = owner_map(instance_name)
    if owners != infer_customer_home_depots(source.instance):
        raise ValueError(f"frozen owner map drifted for {instance_name}")
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=280.0)
    independent_routes, shared_routes = _structure_routes(size, source.instance, prices)
    with strict_mode():
        context = EvaluationContext(source.instance, source.carbon_profile, prices=prices)
        independent, independent_certificate = prepare_solution(Solution(routes=independent_routes), context)
        shared, shared_certificate = prepare_solution(Solution(routes=shared_routes), context)
    if independent_certificate is None or shared_certificate is None:
        raise ValueError("strict preparation did not emit certificates")
    base_caps = _depot_counts(independent_certificate)
    if independent_certificate.vehicle_counts["cv"] > 14 or independent_certificate.vehicle_counts["ev"] > 14:
        raise ValueError("independent structural start exceeds 14/14")
    if shared_certificate.vehicle_counts["cv"] > 14 or shared_certificate.vehicle_counts["ev"] > 14:
        raise ValueError("shared structural start exceeds 14/14")
    target.mkdir(parents=True, exist_ok=True)
    # Persist the raw constructor outputs, not the certificate-labelled copies.
    # Every run must rebuild its own battery ledger under that run's prices.
    write_json(target / "independent_start.json", solution_to_dict(Solution(routes=independent_routes)))
    write_json(target / "shared_start.json", solution_to_dict(Solution(routes=shared_routes)))
    derived = write_derived_bundles(source_dir, target / "derived_bundles")
    subbundles: dict[str, str] = {}
    for depot, caps in base_caps.items():
        subinstance = replace(
            _subinstance_for_depot(source.instance, depot, owners),
            num_cv=int(caps["cv"]),
            num_ev=int(caps["ev"]),
        )
        path = target / "independent_subbundles" / depot
        _write_subbundle(path, subinstance, source_dir, depot)
        payload = read_json(path / "instance.json")
        payload.setdefault("metadata", {}).update({"num_cv": int(caps["cv"]), "num_ev": int(caps["ev"])})
        write_json(path / "instance.json", payload)
        subbundles[depot] = str(path.relative_to(ROOT))
    manifest = {
        "schema": "setp.e3.assets.v1",
        "size": size,
        "instance": instance_name,
        "source_bundle": str(source_dir.relative_to(ROOT)),
        "derived_bundles": derived,
        "subbundles": subbundles,
        "base_caps": base_caps,
        "customer_count": len(owners),
        "owner_rows_sha256": sha256(OWNER_ROWS),
        "contract_sha256": sha256(CONTRACT_PATH),
        "independent_start": str((target / "independent_start.json").relative_to(ROOT)),
        "shared_start": str((target / "shared_start.json").relative_to(ROOT)),
        "strict_contract_id": CONTRACT_ID,
        "source_commit": closure.git_head(),
    }
    write_json(manifest_path, manifest)
    return manifest


def layer_settings(layer: str) -> dict[str, Any]:
    mode = "zero_gamma" if layer in {"M0", "M1"} else "mean_gamma" if layer == "M2" else "actual_gamma"
    return {
        "profile_mode": mode,
        "carbon_price": 0.0 if layer in {"M0", "M1", "M2", "M3"} else float(DEFAULT_PRICES.carbon_price),
        "carbon_weight": 0.0 if layer in {"M0", "M1"} else 1.0,
        "fairness_enabled": layer == "M5",
        "charging_strategy": "naive" if layer in {"M0", "M1", "M2"} else "aware",
        "paired_charging": layer in {"M3", "M4", "M5"},
    }


def _aggregate_named_counts(value: Any, output: dict[str, int]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "score_counts" and isinstance(item, dict):
                for name, count in item.items():
                    if isinstance(count, (int, float)):
                        output[name] = output.get(name, 0) + int(count)
            _aggregate_named_counts(item, output)
    elif isinstance(value, list):
        for item in value:
            _aggregate_named_counts(item, output)


def score_counts(result: dict[str, Any]) -> dict[str, int]:
    output: dict[str, int] = {}
    operator_counts = result.get("operator_counts", {})
    staged = operator_counts.get("staged_chain", {}) if isinstance(operator_counts, dict) else {}
    phase_counts = staged.get("phase_operator_counts") if isinstance(staged, dict) else None
    _aggregate_named_counts(phase_counts if isinstance(phase_counts, list) else operator_counts, output)
    return output


def prices_for(layer: str, fee: float) -> Any:
    settings = layer_settings(layer)
    return replace(
        DEFAULT_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        cross_site_cost=float(fee),
        carbon_price=float(settings["carbon_price"]),
    )


def _profit_values(solution: Solution, bundle: Any, prices: Any, owners: dict[str, str]) -> dict[str, float]:
    rows = calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        customer_home_depot=owners,
        carbon_quota_kg=0.0,
    )
    return {depot: float(row.profit) for depot, row in rows.items()}


def _certificate_stats(certificate: MultiTripCertificate) -> dict[str, Any]:
    by_vehicle: dict[str, list[Any]] = {}
    for trip in certificate.trips:
        by_vehicle.setdefault(trip.physical_vehicle_id, []).append(trip)
    work = 0.0
    gap = 0.0
    for trips in by_vehicle.values():
        ordered = sorted(trips, key=lambda item: item.trip_index)
        work += max(item.return_second for item in ordered) - min(item.departure_second for item in ordered)
        gap += sum(max(0.0, right.departure_second - left.return_second) for left, right in zip(ordered, ordered[1:]))
    return {
        "physical_cv": int(certificate.vehicle_counts["cv"]),
        "physical_ev": int(certificate.vehicle_counts["ev"]),
        "physical_total": int(certificate.vehicle_counts["cv"] + certificate.vehicle_counts["ev"]),
        "depot_vehicle_counts_json": json.dumps(_depot_counts(certificate), sort_keys=True),
        "trip_count": len(certificate.trips),
        "vehicle_work_hours": work / 3600.0,
        "between_trip_gap_hours": gap / 3600.0,
        "max_trips_per_vehicle": max((trip.trip_index for trip in certificate.trips), default=0),
    }


def _metric_row(solution: Solution, bundle: Any, prices: Any) -> tuple[dict[str, Any], float]:
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=0.0)
    component_sum = sum(float(metrics[key]) for key in (
        "cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ", "cost_transship", "cost_carbon"
    ))
    return {key: metrics[key] for key in METRIC_KEYS}, abs(component_sum - float(metrics["total_cost"]))


def _prepared_checked(
    solution: Solution,
    bundle: Any,
    prices: Any,
    *,
    caps: dict[str, dict[str, int]],
    fairness_enabled: bool,
    independent_profit: dict[str, float] | None,
    owners: dict[str, str],
) -> tuple[Solution, MultiTripCertificate, list[Any]]:
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=float(layer_settings("M5" if fairness_enabled else "M3")["carbon_weight"]),
        carbon_quota_kg=0.0,
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit,
        fairness_theta=1.0 if fairness_enabled else None,
        customer_home_depot=owners,
    )
    with strict_mode(caps):
        prepared, certificate = prepare_solution(solution, context)
        violations = hard_violations(prepared, context)
    if certificate is None:
        raise ValueError("strict preparation returned no certificate")
    return prepared, certificate, violations


def _run_independent(spec: dict[str, Any], manifest: dict[str, Any], out: Path) -> dict[str, Any]:
    started = time.perf_counter()
    size = str(spec["size"])
    budget = int(spec["budget"])
    seed = int(spec["seed"])
    owners = owner_map(manifest["instance"])
    full_bundle = load_search_bundle(ROOT / manifest["derived_bundles"]["zero_gamma"])
    structural = solution_from_dict(read_json(ROOT / manifest["independent_start"]))
    merged_routes: list[Route] = []
    merged_actions: list[ChargingAction] = []
    evaluations = 0
    combined_counts: dict[str, int] = {}
    for index, depot in enumerate(sorted(manifest["base_caps"])):
        bundle_dir = ROOT / manifest["subbundles"][depot]
        bundle = load_search_bundle(bundle_dir)
        caps = {depot: dict(manifest["base_caps"][depot])}
        initial = Solution(
            routes=[route for route in structural.routes if route.home_depot_id == depot],
            charging_actions=[action for action in structural.charging_actions if any(
                route.vehicle_id == action.vehicle_id and route.home_depot_id == depot for route in structural.routes
            )],
        )
        sub_budget = budget // len(manifest["base_caps"])
        if index == len(manifest["base_caps"]) - 1:
            sub_budget = budget - evaluations
        prices = prices_for("M0", 0.0)
        with strict_mode(caps):
            result = run_staged_alns_lns_hybrid(
                bundle_dir,
                config=WinnerKernelConfig(
                    seed=seed * 100 + index,
                    eval_budget=sub_budget,
                    max_runtime_seconds=max(300.0, sub_budget * 0.5),
                    require_charging_signal=False,
                ),
                initial_solution=initial,
                prices=prices,
                policy=SearchPolicy(
                    require_charging_signal=False,
                    max_cv=int(caps[depot]["cv"]),
                    max_ev=int(caps[depot]["ev"]),
                ),
                carbon_weight=0.0,
            )
        if not result["feasible"] or int(result["evaluations"]) != sub_budget:
            raise ValueError(f"independent {depot} failed: {result['evaluations']}/{sub_budget}, feasible={result['feasible']}")
        evaluations += int(result["evaluations"])
        merged_routes.extend(result["best_solution"].routes)
        merged_actions.extend(result["best_solution"].charging_actions)
        for name, count in score_counts(result).items():
            combined_counts[name] = combined_counts.get(name, 0) + count
    prices = prices_for("M0", 0.0)
    merged = Solution(routes=merged_routes, charging_actions=merged_actions)
    prepared, certificate, violations = _prepared_checked(
        merged,
        full_bundle,
        prices,
        caps=manifest["base_caps"],
        fairness_enabled=False,
        independent_profit=None,
        owners=owners,
    )
    metrics, closure_error = _metric_row(prepared, full_bundle, prices)
    row = {
        **spec,
        "status": "OK" if not violations and evaluations == budget else "HALT_CONTRACT",
        "reason": "" if not violations else "; ".join(str(item) for item in violations),
        "actual_evals": evaluations,
        "elapsed_seconds": time.perf_counter() - started,
        "violation_count": len(violations),
        "cost_component_error": closure_error,
        "route_structure_signature": route_signature(prepared),
        "cross_site_customer_count": 0,
        "search_score_counts_json": json.dumps(combined_counts, sort_keys=True),
        "strict_search_win": "",
        "adopted_source": "independent_search",
        "search_total_cost": metrics["total_cost"],
        "independent_concat_total_cost": metrics["total_cost"],
        **_certificate_stats(certificate),
        **metrics,
    }
    _write_solution_artifacts(out, spec["run_id"], prepared, prepared, certificate, None)
    return row


def _initial_for_cooperation(
    manifest: dict[str, Any],
    bundle: Any,
    prices: Any,
    caps: dict[str, dict[str, int]],
    owners: dict[str, str],
    fairness_enabled: bool,
    independent_profit: dict[str, float] | None,
) -> tuple[Solution, str]:
    candidates = [
        (solution_from_dict(read_json(ROOT / manifest["shared_start"])), "shared_short_constructor"),
        (solution_from_dict(read_json(ROOT / manifest["independent_start"])), "owner_short_constructor_fallback"),
    ]
    for solution, label in candidates:
        solution = annotate_cross_site(solution, owners)
        _, _, violations = _prepared_checked(
            solution,
            bundle,
            prices,
            caps=caps,
            fairness_enabled=fairness_enabled,
            independent_profit=independent_profit,
            owners=owners,
        )
        if not violations:
            return solution, label
    raise ValueError("neither independently constructed short-route start satisfies the frozen assets and fairness contract")


def _run_cooperative(
    spec: dict[str, Any],
    manifest: dict[str, Any],
    independent_row: dict[str, Any],
    out: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    layer = str(spec["layer"])
    settings = layer_settings(layer)
    bundle = load_search_bundle(ROOT / manifest["derived_bundles"][settings["profile_mode"]])
    owners = owner_map(manifest["instance"])
    prices = prices_for(layer, float(spec["fee"]))
    independent_solution = solution_from_dict(read_json(out / "solutions" / f"{independent_row['run_id']}__adopted.json"))
    baseline_metrics, _ = _metric_row(independent_solution, bundle, prices)
    independent_profit = _profit_values(independent_solution, bundle, prices, owners)
    caps = json.loads(str(independent_row["depot_vehicle_counts_json"]))
    initial, start_source = _initial_for_cooperation(
        manifest,
        bundle,
        prices,
        caps,
        owners,
        bool(settings["fairness_enabled"]),
        independent_profit if settings["fairness_enabled"] else None,
    )
    runner = run_tvci_carbon_schedule_pair if settings["paired_charging"] else run_tvci_alns
    kwargs: dict[str, Any] = {
        "config": WinnerKernelConfig(
            seed=int(spec["seed"]),
            eval_budget=int(spec["budget"]),
            max_runtime_seconds=max(600.0, int(spec["budget"]) * 0.5),
            require_charging_signal=False,
        ),
        "initial_solution": initial,
        "prices": prices,
        "policy": SearchPolicy(require_charging_signal=False, max_cv=14, max_ev=14),
        "carbon_weight": float(settings["carbon_weight"]),
        "carbon_quota_kg": 0.0,
        "fairness_enabled": bool(settings["fairness_enabled"]),
        "independent_profit": independent_profit if settings["fairness_enabled"] else None,
        "fairness_theta": 1.0 if settings["fairness_enabled"] else None,
        "customer_home_depot": owners,
    }
    if not settings["paired_charging"]:
        kwargs["charging_strategy"] = settings["charging_strategy"]
    with strict_mode(caps):
        result = runner(bundle.bundle_dir, **kwargs)
    counts = score_counts(result)
    search = annotate_cross_site(result["best_solution"], owners)
    search, search_certificate, violations = _prepared_checked(
        search,
        bundle,
        prices,
        caps=caps,
        fairness_enabled=bool(settings["fairness_enabled"]),
        independent_profit=independent_profit if settings["fairness_enabled"] else None,
        owners=owners,
    )
    search_metrics, search_error = _metric_row(search, bundle, prices)
    strict_win = float(search_metrics["total_cost"]) < float(baseline_metrics["total_cost"]) - 1e-9
    adopted = search if strict_win else independent_solution
    adopted_source = "cooperative_search" if strict_win else "independent_concat_fallback"
    adopted = annotate_cross_site(adopted, owners)
    adopted, adopted_certificate, adopted_violations = _prepared_checked(
        adopted,
        bundle,
        prices,
        caps=caps,
        fairness_enabled=bool(settings["fairness_enabled"]),
        independent_profit=independent_profit if settings["fairness_enabled"] else None,
        owners=owners,
    )
    adopted_metrics, adopted_error = _metric_row(adopted, bundle, prices)
    profits = _profit_values(search, bundle, prices, owners)
    ratios = {
        depot: profits[depot] / value
        for depot, value in independent_profit.items()
        if abs(value) > 1e-12
    }
    naive_metrics: dict[str, Any] | None = None
    naive_solution: Solution | None = None
    naive_result = result.get("charging_ablation_result")
    if isinstance(naive_result, dict) and naive_result.get("best_solution") is not None:
        naive_solution = annotate_cross_site(naive_result["best_solution"], owners)
        naive_solution, _, naive_violations = _prepared_checked(
            naive_solution,
            bundle,
            prices,
            caps=caps,
            fairness_enabled=bool(settings["fairness_enabled"]),
            independent_profit=independent_profit if settings["fairness_enabled"] else None,
            owners=owners,
        )
        if naive_violations:
            violations.extend(naive_violations)
        naive_metrics, _ = _metric_row(naive_solution, bundle, prices)
        if route_signature(naive_solution) != route_signature(search):
            violations.append("aware/naive route signatures differ")
        if abs(float(naive_metrics["electricity_kwh"]) - float(search_metrics["electricity_kwh"])) > 1e-6:
            violations.append("aware/naive electricity differs")
    public_hits = int(counts.get("strict_public_station_incompatibility", 0))
    if public_hits:
        violations.append(f"public-station incompatibility encountered {public_hits} times")
    all_violations = [*violations, *adopted_violations]
    row = {
        **spec,
        "status": "OK" if not all_violations and int(result["evaluations"]) == int(spec["budget"]) else "HALT_CONTRACT",
        "reason": "" if not all_violations else "; ".join(str(item) for item in all_violations),
        "actual_evals": int(result["evaluations"]),
        "elapsed_seconds": time.perf_counter() - started,
        "violation_count": len(all_violations),
        "cost_component_error": max(search_error, adopted_error),
        "start_source": start_source,
        "route_structure_signature": route_signature(adopted),
        "search_route_structure_signature": route_signature(search),
        "cross_site_customer_count": len(adopted.cross_site_services),
        "search_cross_site_customer_count": len(search.cross_site_services),
        "cross_site_attempted_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        "search_score_counts_json": json.dumps(counts, sort_keys=True),
        "fairness_enabled": bool(settings["fairness_enabled"]),
        "fairness_search_active_evidence": json.dumps({
            "enabled": bool(settings["fairness_enabled"]),
            "rejected_candidates": int(counts.get("strict_reject_fairness", 0)),
            "final_profit_ratios": ratios,
        }, sort_keys=True),
        "profit_ratios_json": json.dumps(ratios, sort_keys=True),
        "min_profit_ratio": min(ratios.values(), default=""),
        "strict_search_win": strict_win,
        "adopted_source": adopted_source,
        "search_total_cost": search_metrics["total_cost"],
        "independent_concat_total_cost": baseline_metrics["total_cost"],
        "naive_same_route_E_ev_indirect": "" if naive_metrics is None else naive_metrics["E_ev_indirect"],
        "naive_same_route_electricity_kwh": "" if naive_metrics is None else naive_metrics["electricity_kwh"],
        **_certificate_stats(adopted_certificate),
        **adopted_metrics,
    }
    _write_solution_artifacts(out, spec["run_id"], search, adopted, adopted_certificate, naive_solution)
    return row


def _write_solution_artifacts(
    out: Path,
    run_id: str,
    search: Solution,
    adopted: Solution,
    certificate: MultiTripCertificate,
    naive: Solution | None,
) -> None:
    write_json(out / "solutions" / f"{run_id}__search.json", solution_to_dict(search))
    write_json(out / "solutions" / f"{run_id}__adopted.json", solution_to_dict(adopted))
    write_json(out / "certificates" / f"{run_id}.json", certificate.as_dict())
    if naive is not None:
        write_json(out / "solutions" / f"{run_id}__naive.json", solution_to_dict(naive))


def task_fingerprint(spec: dict[str, Any], manifest: dict[str, Any]) -> str:
    source_hashes = {path: sha256(ROOT / path) for path in EXECUTION_SOURCE_PATHS}
    payload = {
        "spec": spec,
        "source_commit": closure.git_head(),
        "source_hashes": source_hashes,
        "contract_sha256": sha256(CONTRACT_PATH),
        "asset_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "strict_contract_id": CONTRACT_ID,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def run_row(spec: dict[str, Any], manifest: dict[str, Any], out: Path, independent_row: dict[str, Any] | None) -> dict[str, Any]:
    row_path = out / "runs" / f"{spec['run_id']}.json"
    fingerprint = task_fingerprint(spec, manifest)
    if row_path.exists():
        existing = read_json(row_path)
        if existing.get("task_fingerprint") == fingerprint and existing.get("status") == "OK":
            return existing
        raise ValueError(f"stale or failed resumable row exists: {row_path}")
    row = (
        _run_independent(spec, manifest, out)
        if spec["layer"] == "M0"
        else _run_cooperative(spec, manifest, independent_row or {}, out)
    )
    row.update({
        "task_fingerprint": fingerprint,
        "source_commit": closure.git_head(),
        "source_hashes_json": json.dumps(
            {path: sha256(ROOT / path) for path in EXECUTION_SOURCE_PATHS}, sort_keys=True
        ),
        "contract_sha256": sha256(CONTRACT_PATH),
        "strict_contract_id": CONTRACT_ID,
        "battery_kwh": 280.0,
        "depot_charge_power_kw": 22.0,
        "carbon_quota_kg": 0.0,
        "machine": "M1",
        "scenario_role": "main_280",
    })
    write_json(row_path, row)
    return row


def run_seed_plan(plan: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    manifests = {size: read_json(out / "assets" / size / "asset_manifest.json") for size in plan["sizes"]}
    rows: list[dict[str, Any]] = []
    independent_by_size: dict[str, dict[str, Any]] = {}
    for spec in plan["specs"]:
        size = str(spec["size"])
        row = run_row(spec, manifests[size], out, independent_by_size.get(size))
        rows.append(row)
        if spec["layer"] == "M0":
            independent_by_size[size] = row
        if row.get("status") != "OK":
            raise ValueError(f"{row['run_id']} stopped: {row.get('reason', '')}")
    return rows


def _spec(size: str, layer: str, seed: int, budget: int, fee: float = 0.0) -> dict[str, Any]:
    fee_text = str(int(fee)) if float(fee).is_integer() else str(fee).replace(".", "p")
    return {
        "run_id": f"E3__{size}__{layer}__seed{seed}__fee{fee_text}__eval{budget}",
        "size": size,
        "instance": INSTANCE_NAMES[size],
        "layer": layer,
        "seed": int(seed),
        "fee": float(fee),
        "budget": int(budget),
    }


def phase_plans(phase: str, budget: int) -> list[dict[str, Any]]:
    if phase in {"smoke", "preflight", "model_gate", "rehearsal"}:
        seed = 99 if phase == "rehearsal" else 1
        if phase == "preflight":
            specs = [_spec("200c", "M0", seed, budget), _spec("200c", "M5", seed, budget), _spec("200c", "M5", seed, budget, 95.0)]
        else:
            specs = [_spec("200c", "M0", seed, budget), _spec("200c", "M1", seed, budget)]
        return [{"seed": seed, "sizes": ["200c"], "specs": specs}]
    seeds = range(1, 6) if phase == "formal70" else range(6, 11)
    plans: list[dict[str, Any]] = []
    for seed in seeds:
        specs = [_spec("200c", layer, seed, budget) for layer in LAYERS]
        sizes = ["200c"]
        if phase == "formal70":
            specs.extend(_spec("100c", layer, seed, budget) for layer in ("M0", "M1", "M3", "M5"))
            specs.extend(_spec("200c", "M5", seed, budget, fee) for fee in (10.0, 25.0, 50.0, 95.0))
            sizes.append("100c")
        plans.append({"seed": seed, "sizes": sizes, "specs": specs})
    return plans


def default_budget(phase: str) -> int:
    return {"smoke": 8, "preflight": 200, "model_gate": 4000, "rehearsal": 400, "formal70": 4000, "promote100": 4000}[phase]


def summarize_phase(out: Path, phase: str, plans: list[dict[str, Any]]) -> dict[str, Any]:
    run_ids = [spec["run_id"] for plan in plans for spec in plan["specs"]]
    rows = [read_json(out / "runs" / f"{run_id}.json") for run_id in run_ids]
    phase_dir = out / phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with (phase_dir / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    all_ok = all(
        row["status"] == "OK"
        and int(row["actual_evals"]) == int(row["budget"])
        and int(row["violation_count"]) == 0
        and float(row["cost_component_error"]) <= 1e-6
        for row in rows
    )
    fairness_ok = all(
        row.get("fairness_search_active_evidence") not in (None, "")
        for row in rows
        if row["layer"] == "M5"
    )
    verdict = f"E3_{phase.upper()}_PASS" if all_ok and fairness_ok else f"HALT_E3_{phase.upper()}"
    decision = {
        "verdict": verdict,
        "phase": phase,
        "row_count": len(rows),
        "ok_rows": sum(row["status"] == "OK" for row in rows),
        "all_budget_closed": all_ok,
        "fairness_evidence_complete": fairness_ok,
        "formal_70_authorized": phase in {"model_gate", "rehearsal"} and all_ok and fairness_ok,
        "promotion_authorized": phase == "formal70" and all_ok and fairness_ok,
    }
    metadata = {
        "schema": "setp.e3.phase.v1",
        "phase": phase,
        "source_commit": closure.git_head(),
        "contract_sha256": sha256(CONTRACT_PATH),
        "strict_contract_id": CONTRACT_ID,
        "plans": plans,
    }
    write_json(phase_dir / "metadata.json", metadata)
    write_json(phase_dir / "decision.json", decision)
    (phase_dir / "report.md").write_text(
        f"# E3 {phase}\n\n判决：{verdict}。完成 {len(rows)} 行，其中 {decision['ok_rows']} 行通过。"
        "这一步只按预先写死的数据质量规则验收，不按结果好不好看决定。\n",
        encoding="utf-8",
    )
    with (phase_dir / "task_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        specs = [spec for plan in plans for spec in plan["specs"]]
        writer = csv.DictWriter(handle, fieldnames=list(specs[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(specs)
    hashes = {
        str(path.relative_to(phase_dir)): sha256(path)
        for path in sorted(phase_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(phase_dir / "artifact_hashes.json", hashes)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("smoke", "preflight", "model_gate", "rehearsal", "formal70", "promote100"), required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--budget", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed-plan-json", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    load_submission_contract(CONTRACT_PATH, repo_root=ROOT, require_frozen=True, lane=FULL_MODEL_LANE)
    if args.seed_plan_json:
        run_seed_plan(read_json(Path(args.seed_plan_json)), out)
        return 0
    budget = int(args.budget) if int(args.budget) > 0 else default_budget(args.phase)
    plans = phase_plans(args.phase, budget)
    sizes = sorted({size for plan in plans for size in plan["sizes"]})
    for size in sizes:
        prepare_assets(out, size)
    plan_dir = out / ".seed_plans" / args.phase
    commands: list[list[str]] = []
    for plan in plans:
        path = plan_dir / f"seed{plan['seed']}.json"
        write_json(path, plan)
        commands.append([
            sys.executable,
            str(Path(__file__).resolve()),
            "--phase",
            args.phase,
            "--output-dir",
            str(out),
            "--seed-plan-json",
            str(path),
        ])

    def launch(command: list[str]) -> None:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout)[-4000:])

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max(1, int(args.workers)), len(commands))) as pool:
        list(pool.map(launch, commands))
    decision = summarize_phase(out, args.phase, plans)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
