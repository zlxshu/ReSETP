#!/usr/bin/env python3
"""Formal E6 participation comparison under equal starts and equal budgets.

The independent baseline is solved separately for each depot (2,000 candidate
evaluations per depot).  The two depot solutions are then concatenated and
used byte-for-byte as the common start for two 4,000-evaluation cooperative
runs: unrestricted cooperation and cooperation subject to theta=1, meaning
that neither depot may earn less than in its own independent solution.

Execution is deliberately staged.  ``prepare`` writes the frozen contract and
assets without running a search.  ``probe`` runs only the 114-customer network
under the two pre-registered portfolio structures.  ``remaining`` is allowed
only after the probe passes mechanical checks; result direction is never an
execution gate.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e3_ablation.e3_paired_cost_formal_20260713 import (
    load_envelopes,
    load_owners,
)
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_tvci_alns
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations
from setp_solver.search.fairness import _subinstance_for_depot, _write_subbundle
from setp_solver.solution import ChargingAction, Route, Solution


E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
OUT = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
PROBE_INSTANCE = "L-main-threeshift-50c-01"
CONDITIONS = ("geographic", "mixed")
SEEDS = (1, 2, 3)
INDEPENDENT_BUDGET_PER_DEPOT = 2_000
COOPERATIVE_BUDGET = 4_000
THETA = 1.0
ARMS = (("unrestricted", False), ("no_loss", True))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fallback_fields: Iterable[str]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else list(fallback_fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def solution_payload(solution: Solution) -> dict[str, Any]:
    return legacy.solution_to_dict(solution)


def solution_copy(solution: Solution) -> Solution:
    return legacy.solution_from_dict(json.loads(canonical_bytes(solution_payload(solution))))


def depot_caps(instance: str, condition: str) -> dict[str, dict[str, int]]:
    meta_path = E3 / "assets" / instance / f"{condition}__common_start_meta.json"
    raw = read_json(meta_path).get("depot_vehicle_counts_json")
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, dict) or len(parsed) != 2:
        raise ValueError(f"invalid depot asset caps for {instance}/{condition}: {parsed!r}")
    result = {
        str(depot): {"cv": int(values["cv"]), "ev": int(values["ev"])}
        for depot, values in sorted(parsed.items())
    }
    if any(value < 0 for values in result.values() for value in values.values()):
        raise ValueError("negative depot asset cap")
    return result


def common_start(instance: str, condition: str) -> Solution:
    path = E3 / "assets" / instance / f"{condition}__common_start.json"
    return legacy.solution_from_dict(read_json(path))


def extract_depot_start(solution: Solution, depot_id: str) -> Solution:
    routes = [route for route in solution.routes if route.home_depot_id == depot_id]
    route_ids = {route.vehicle_id for route in routes}
    actions = [action for action in solution.charging_actions if action.vehicle_id in route_ids]
    if not routes:
        raise ValueError(f"common start has no routes for {depot_id}")
    return Solution(routes=routes, charging_actions=actions, cross_site_services=[])


def merge_depot_solutions(solutions: dict[str, Solution]) -> Solution:
    routes = [route for depot in sorted(solutions) for route in solutions[depot].routes]
    actions = [action for depot in sorted(solutions) for action in solutions[depot].charging_actions]
    route_ids = [route.vehicle_id for route in routes]
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("independent solutions contain duplicate trip identifiers")
    action_route_ids = {action.vehicle_id for action in actions}
    if not action_route_ids.issubset(set(route_ids)):
        raise ValueError("independent charging action is detached from its route")
    return Solution(routes=routes, charging_actions=actions, cross_site_services=[])


def _subbundle_dir(instance: str, condition: str, depot_id: str) -> Path:
    return OUT / "assets" / instance / condition / "independent_subbundles" / depot_id


def prepare_assets() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in load_envelopes():
        instance = str(item["instance"])
        full_dir = E3 / "assets" / instance / "bundle"
        full = load_search_bundle(full_dir)
        for condition in CONDITIONS:
            owners, owner_path = load_owners(instance, condition)
            caps = depot_caps(instance, condition)
            start_path = E3 / "assets" / instance / f"{condition}__common_start.json"
            start = common_start(instance, condition)
            served = {
                node_id
                for route in start.routes
                for node_id in route.node_sequence
                if node_id in owners
            }
            if served != set(owners):
                raise ValueError(f"common start customer coverage drifted for {instance}/{condition}")
            if legacy.annotate_cross_site(start, owners).cross_site_services:
                raise ValueError(f"common start is not ownership-fixed for {instance}/{condition}")
            for depot_id, local_caps in sorted(caps.items()):
                subinstance = replace(
                    _subinstance_for_depot(full.instance, depot_id, owners),
                    num_cv=int(local_caps["cv"]),
                    num_ev=int(local_caps["ev"]),
                )
                target = _subbundle_dir(instance, condition, depot_id)
                _write_subbundle(target, subinstance, full_dir, depot_id)
                payload = read_json(target / "instance.json")
                payload.setdefault("metadata", {}).update(
                    {
                        "num_cv": int(local_caps["cv"]),
                        "num_ev": int(local_caps["ev"]),
                        "ownership_condition": condition,
                        "ownership_sha256": sha256(owner_path),
                        "source_common_start_sha256": sha256(start_path),
                    }
                )
                write_json(target / "instance.json", payload)
                local_start = extract_depot_start(start, depot_id)
                local_customers = {
                    node_id
                    for route in local_start.routes
                    for node_id in route.node_sequence
                    if node_id in owners
                }
                expected = {customer for customer, owner in owners.items() if owner == depot_id}
                if local_customers != expected:
                    raise ValueError(f"subproblem start coverage drifted for {instance}/{condition}/{depot_id}")
                rows.append(
                    {
                        "instance": instance,
                        "condition": condition,
                        "depot_id": depot_id,
                        "customer_count": len(expected),
                        "cap_cv": local_caps["cv"],
                        "cap_ev": local_caps["ev"],
                        "ownership_sha256": sha256(owner_path),
                        "common_start_sha256": sha256(start_path),
                        "common_start_canonical_sha256": canonical_hash(solution_payload(start)),
                        "subbundle_instance_sha256": sha256(target / "instance.json"),
                        "subbundle_matrix_sha256": sha256(target / "distance_matrix.npy"),
                        "subbundle_carbon_sha256": sha256(target / "carbon_profile.csv"),
                        "status": "PASS",
                    }
                )
    if len(rows) != 36:
        raise ValueError(f"expected 36 depot assets, got {len(rows)}")
    write_csv(OUT / "asset_preflight.csv", rows, ("instance",))
    return rows


def _context(
    bundle: Any,
    prices: Any,
    owners: dict[str, str],
    *,
    allow_cross: bool,
    fairness_enabled: bool,
    independent_profit: dict[str, float] | None,
) -> EvaluationContext:
    return EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=0.0,
        carbon_quota_kg=0.0,
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit,
        fairness_theta=THETA if fairness_enabled else None,
        customer_home_depot=owners,
        allow_cross_depot=allow_cross,
    )


def _validate_solution(
    solution: Solution,
    bundle: Any,
    prices: Any,
    owners: dict[str, str],
    caps: dict[str, dict[str, int]],
    *,
    allow_cross: bool,
    fairness_enabled: bool,
    independent_profit: dict[str, float] | None,
) -> tuple[Solution, Any, list[Any], dict[str, Any], float]:
    context = _context(
        bundle,
        prices,
        owners,
        allow_cross=allow_cross,
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit,
    )
    with legacy.strict_mode(caps):
        prepared, certificate = prepare_solution(solution, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None:
        raise ValueError("strict validation emitted no physical-vehicle certificate")
    metrics, closure_error = legacy._metric_row(prepared, bundle, prices)
    return prepared, certificate, violations, metrics, float(closure_error)


def _profit_report(
    solution: Solution,
    bundle: Any,
    prices: Any,
    owners: dict[str, str],
    independent_profit: dict[str, float] | None = None,
) -> tuple[dict[str, Any], dict[str, float], dict[str, float], float]:
    breakdowns = calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        customer_home_depot=owners,
        carbon_quota_kg=0.0,
    )
    profits = {depot: float(row.profit) for depot, row in breakdowns.items()}
    ratios = {
        depot: profits[depot] / float(baseline)
        for depot, baseline in (independent_profit or profits).items()
        if abs(float(baseline)) > 1e-12
    }
    cost_sum = sum(float(row.cost_total) for row in breakdowns.values())
    return (
        {depot: row.to_dict() for depot, row in breakdowns.items()},
        profits,
        ratios,
        cost_sum,
    )


def _save_solution(run_id: str, solution: Solution, certificate: Any) -> tuple[Path, Path]:
    solution_path = OUT / "solutions" / f"{run_id}.json"
    certificate_path = OUT / "certificates" / f"{run_id}.json"
    write_json(solution_path, solution_payload(solution))
    write_json(certificate_path, certificate.as_dict())
    return solution_path, certificate_path


def _base_row(
    *,
    run_id: str,
    instance: str,
    condition: str,
    seed: int,
    arm: str,
    budget: int,
    evaluations: int,
    elapsed_seconds: float,
    solution: Solution,
    certificate: Any,
    metrics: dict[str, Any],
    closure_error: float,
    violations: list[Any],
    owners: dict[str, str],
    bundle: Any,
    prices: Any,
    independent_profit: dict[str, float],
    start_sha256: str,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    profit_rows, profits, ratios, allocated_cost = _profit_report(
        solution, bundle, prices, owners, independent_profit
    )
    solution_path, certificate_path = _save_solution(run_id, solution, certificate)
    return {
        "run_id": run_id,
        "instance": instance,
        "condition": condition,
        "seed": seed,
        "arm": arm,
        "budget": budget,
        "evaluations": evaluations,
        "elapsed_seconds": elapsed_seconds,
        "status": "PASS" if evaluations == budget and not violations and closure_error <= 1e-6 else "HALT",
        "violation_count": len(violations),
        "violations_json": json.dumps([asdict(item) if hasattr(item, "__dataclass_fields__") else str(item) for item in violations], ensure_ascii=False, sort_keys=True),
        "start_sha256": start_sha256,
        "solution_sha256": sha256(solution_path),
        "solution_canonical_sha256": canonical_hash(solution_payload(solution)),
        "certificate_sha256": sha256(certificate_path),
        "solution_path": str(solution_path.relative_to(ROOT)),
        "certificate_path": str(certificate_path.relative_to(ROOT)),
        "cost_component_error": closure_error,
        "profit_cost_allocation_error": abs(float(metrics["total_cost"]) - allocated_cost),
        "cross_site_customer_count": len(solution.cross_site_services),
        "profit_json": json.dumps(profit_rows, ensure_ascii=False, sort_keys=True),
        "profit_ratio_json": json.dumps(ratios, ensure_ascii=False, sort_keys=True),
        "minimum_profit_ratio": min(ratios.values()) if ratios else math.nan,
        "both_depots_no_worse": bool(ratios and min(ratios.values()) >= THETA - 1e-9),
        "search_score_counts_json": json.dumps(counts or {}, sort_keys=True),
        **legacy._certificate_stats(certificate),
        **metrics,
    }


def _run_independent_depot(
    instance: str,
    condition: str,
    seed: int,
    depot_id: str,
    local_caps: dict[str, int],
    owners: dict[str, str],
    prices: Any,
) -> tuple[Solution, Any, dict[str, Any], dict[str, int], float]:
    bundle_dir = _subbundle_dir(instance, condition, depot_id)
    bundle = load_search_bundle(bundle_dir)
    start = extract_depot_start(common_start(instance, condition), depot_id)
    subowners = {customer: depot_id for customer, owner in owners.items() if owner == depot_id}
    started = time.perf_counter()
    with legacy.strict_mode({depot_id: local_caps}):
        result = run_tvci_alns(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=seed * 100 + (0 if depot_id == sorted(set(owners.values()))[0] else 1),
                eval_budget=INDEPENDENT_BUDGET_PER_DEPOT,
                max_runtime_seconds=max(600.0, INDEPENDENT_BUDGET_PER_DEPOT * 0.5),
                require_charging_signal=False,
            ),
            initial_solution=start,
            prices=prices,
            charging_strategy="naive",
            policy=SearchPolicy(
                require_charging_signal=False,
                max_cv=int(local_caps["cv"]),
                max_ev=int(local_caps["ev"]),
                allow_cross_depot=False,
            ),
            carbon_weight=0.0,
            fairness_enabled=False,
            customer_home_depot=subowners,
        )
    best = legacy.annotate_cross_site(result["best_solution"], subowners)
    prepared, certificate, violations, metrics, closure_error = _validate_solution(
        best,
        bundle,
        prices,
        subowners,
        {depot_id: local_caps},
        allow_cross=False,
        fairness_enabled=False,
        independent_profit=None,
    )
    if int(result.get("evaluations", -1)) != INDEPENDENT_BUDGET_PER_DEPOT or violations or closure_error > 1e-6:
        raise ValueError(
            f"independent search failed for {instance}/{condition}/seed{seed}/{depot_id}: "
            f"evals={result.get('evaluations')}, violations={violations}, closure={closure_error}"
        )
    return prepared, certificate, metrics, legacy.score_counts(result), time.perf_counter() - started


def _run_cooperative_arm(
    instance: str,
    condition: str,
    seed: int,
    label: str,
    fairness_enabled: bool,
    initial: Solution,
    initial_hash: str,
    independent_profit: dict[str, float],
    caps: dict[str, dict[str, int]],
    owners: dict[str, str],
    prices: Any,
) -> dict[str, Any]:
    bundle_dir = E3 / "assets" / instance / "bundle"
    bundle = load_search_bundle(bundle_dir)
    started = time.perf_counter()
    with legacy.strict_mode(caps):
        result = run_tvci_alns(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=seed,
                eval_budget=COOPERATIVE_BUDGET,
                max_runtime_seconds=max(600.0, COOPERATIVE_BUDGET * 0.5),
                require_charging_signal=False,
            ),
            initial_solution=solution_copy(initial),
            prices=prices,
            charging_strategy="naive",
            policy=SearchPolicy(
                require_charging_signal=False,
                max_cv=int(bundle.instance.num_cv or 0),
                max_ev=int(bundle.instance.num_ev or 0),
                allow_cross_depot=True,
            ),
            carbon_weight=0.0,
            fairness_enabled=fairness_enabled,
            independent_profit=independent_profit if fairness_enabled else None,
            fairness_theta=THETA if fairness_enabled else None,
            customer_home_depot=owners,
        )
    best = legacy.annotate_cross_site(result["best_solution"], owners)
    prepared, certificate, violations, metrics, closure_error = _validate_solution(
        best,
        bundle,
        prices,
        owners,
        caps,
        allow_cross=True,
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit if fairness_enabled else None,
    )
    run_id = f"{instance}__{condition}__seed{seed}__{label}"
    return _base_row(
        run_id=run_id,
        instance=instance,
        condition=condition,
        seed=seed,
        arm=label,
        budget=COOPERATIVE_BUDGET,
        evaluations=int(result.get("evaluations", -1)),
        elapsed_seconds=time.perf_counter() - started,
        solution=prepared,
        certificate=certificate,
        metrics=metrics,
        closure_error=closure_error,
        violations=violations,
        owners=owners,
        bundle=bundle,
        prices=prices,
        independent_profit=independent_profit,
        start_sha256=initial_hash,
        counts=legacy.score_counts(result),
    )


def run_spec(spec: dict[str, Any], contract_sha256: str) -> dict[str, Any]:
    result_path = OUT / "pairs" / f"{spec['spec_id']}.json"
    if result_path.exists():
        cached = read_json(result_path)
        if cached.get("contract_sha256") == contract_sha256 and cached.get("pair_status") == "PASS":
            return cached
    instance = str(spec["instance"])
    condition = str(spec["condition"])
    seed = int(spec["seed"])
    try:
        full_bundle = load_search_bundle(E3 / "assets" / instance / "bundle")
        owners, _ = load_owners(instance, condition)
        caps = depot_caps(instance, condition)
        prices = legacy.prices_for("M1", 0.0)
        depot_solutions: dict[str, Solution] = {}
        depot_elapsed = 0.0
        depot_counts: dict[str, int] = {}
        sub_rows: list[dict[str, Any]] = []
        for depot_id, local_caps in sorted(caps.items()):
            solution, certificate, metrics, counts, elapsed = _run_independent_depot(
                instance, condition, seed, depot_id, local_caps, owners, prices
            )
            depot_solutions[depot_id] = solution
            depot_elapsed += elapsed
            for name, count in counts.items():
                depot_counts[name] = depot_counts.get(name, 0) + int(count)
            sub_run_id = f"{instance}__{condition}__seed{seed}__independent_{depot_id}"
            sub_solution_path, sub_certificate_path = _save_solution(sub_run_id, solution, certificate)
            sub_rows.append(
                {
                    "depot_id": depot_id,
                    "budget": INDEPENDENT_BUDGET_PER_DEPOT,
                    "evaluations": INDEPENDENT_BUDGET_PER_DEPOT,
                    "elapsed_seconds": elapsed,
                    "solution_path": str(sub_solution_path.relative_to(ROOT)),
                    "solution_sha256": sha256(sub_solution_path),
                    "certificate_path": str(sub_certificate_path.relative_to(ROOT)),
                    "certificate_sha256": sha256(sub_certificate_path),
                    **metrics,
                }
            )
        merged = merge_depot_solutions(depot_solutions)
        merged = legacy.annotate_cross_site(merged, owners)
        merged, merged_certificate, merged_violations, merged_metrics, merged_error = _validate_solution(
            merged,
            full_bundle,
            prices,
            owners,
            caps,
            allow_cross=False,
            fairness_enabled=False,
            independent_profit=None,
        )
        _, independent_profit, _, allocated_cost = _profit_report(
            merged, full_bundle, prices, owners
        )
        if any(value <= 1e-9 for value in independent_profit.values()):
            raise ValueError(f"independent profit must be positive: {independent_profit}")
        if abs(float(merged_metrics["total_cost"]) - allocated_cost) > 1e-6:
            raise ValueError("merged independent profit allocation does not close to system cost")
        merged_hash = canonical_hash(solution_payload(merged))
        independent_row = _base_row(
            run_id=f"{instance}__{condition}__seed{seed}__independent",
            instance=instance,
            condition=condition,
            seed=seed,
            arm="independent",
            budget=INDEPENDENT_BUDGET_PER_DEPOT * len(caps),
            evaluations=INDEPENDENT_BUDGET_PER_DEPOT * len(caps),
            elapsed_seconds=depot_elapsed,
            solution=merged,
            certificate=merged_certificate,
            metrics=merged_metrics,
            closure_error=merged_error,
            violations=merged_violations,
            owners=owners,
            bundle=full_bundle,
            prices=prices,
            independent_profit=independent_profit,
            start_sha256=canonical_hash(solution_payload(common_start(instance, condition))),
            counts=depot_counts,
        )
        cooperative_rows = [
            _run_cooperative_arm(
                instance,
                condition,
                seed,
                label,
                fairness_enabled,
                merged,
                merged_hash,
                independent_profit,
                caps,
                owners,
                prices,
            )
            for label, fairness_enabled in ARMS
        ]
        rows = [independent_row, *cooperative_rows]
        pair_status = "PASS" if (
            all(row["status"] == "PASS" for row in rows)
            and cooperative_rows[0]["start_sha256"] == cooperative_rows[1]["start_sha256"] == merged_hash
            and all(int(row["evaluations"]) == COOPERATIVE_BUDGET for row in cooperative_rows)
            and independent_row["both_depots_no_worse"]
            and cooperative_rows[1]["both_depots_no_worse"]
            and max(float(row["profit_cost_allocation_error"]) for row in rows) <= 1e-6
        ) else "HALT"
        payload = {
            "spec_id": spec["spec_id"],
            "contract_sha256": contract_sha256,
            "pair_status": pair_status,
            "depot_caps": caps,
            "independent_profit": independent_profit,
            "subproblem_rows": sub_rows,
            "rows": rows,
        }
    except Exception as exc:
        payload = {
            "spec_id": spec["spec_id"],
            "contract_sha256": contract_sha256,
            "pair_status": "HALT",
            "reason": f"{type(exc).__name__}: {exc}",
            "subproblem_rows": [],
            "rows": [],
        }
    write_json(result_path, payload)
    return payload


def exact_two_sided_sign_p(positive: int, negative: int) -> float:
    n = positive + negative
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(positive, negative) + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def aggregate(specs: list[dict[str, Any]], contract_sha256: str) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for spec in specs:
        path = OUT / "pairs" / f"{spec['spec_id']}.json"
        if path.exists():
            payload = read_json(path)
            if payload.get("contract_sha256") == contract_sha256:
                pairs.append(payload)
    rows = [row for pair in pairs for row in pair.get("rows", [])]
    write_csv(OUT / "raw_runs.csv", rows, ("run_id",))
    paired_rows: list[dict[str, Any]] = []
    for pair in pairs:
        if pair.get("pair_status") != "PASS" or len(pair.get("rows", [])) != 3:
            continue
        indexed = {row["arm"]: row for row in pair["rows"]}
        base = indexed["independent"]
        off = indexed["unrestricted"]
        fair = indexed["no_loss"]
        paired_rows.append(
            {
                "spec_id": pair["spec_id"],
                "instance": base["instance"],
                "condition": base["condition"],
                "seed": int(base["seed"]),
                "independent_total_cost": float(base["total_cost"]),
                "unrestricted_total_cost": float(off["total_cost"]),
                "no_loss_total_cost": float(fair["total_cost"]),
                "unrestricted_saving_vs_independent_pct": (float(base["total_cost"]) - float(off["total_cost"])) / float(base["total_cost"]) * 100.0,
                "no_loss_saving_vs_independent_pct": (float(base["total_cost"]) - float(fair["total_cost"])) / float(base["total_cost"]) * 100.0,
                "participation_cost_pct_points": (float(fair["total_cost"]) - float(off["total_cost"])) / float(base["total_cost"]) * 100.0,
                "unrestricted_minimum_profit_ratio": float(off["minimum_profit_ratio"]),
                "no_loss_minimum_profit_ratio": float(fair["minimum_profit_ratio"]),
                "unrestricted_both_depots_no_worse": bool(off["both_depots_no_worse"]),
                "no_loss_both_depots_no_worse": bool(fair["both_depots_no_worse"]),
                "unrestricted_cross_site_customer_count": int(off["cross_site_customer_count"]),
                "no_loss_cross_site_customer_count": int(fair["cross_site_customer_count"]),
            }
        )
    write_csv(OUT / "paired_results.csv", paired_rows, ("spec_id",))
    expected = len(specs)
    passed = sum(pair.get("pair_status") == "PASS" for pair in pairs)
    probe_ids = {
        spec["spec_id"]
        for spec in specs
        if spec["instance"] == PROBE_INSTANCE and int(spec["seed"]) == 1
    }
    passed_ids = {pair["spec_id"] for pair in pairs if pair.get("pair_status") == "PASS"}
    formal_complete = passed == expected == len(pairs)
    decision: dict[str, Any] = {
        "status": "FORMAL_COMPLETE" if formal_complete else "PROBE_CONTRACT_PASS" if probe_ids.issubset(passed_ids) else "IN_PROGRESS_OR_HALT",
        "contract_sha256": contract_sha256,
        "expected_specs": expected,
        "completed_specs": len(pairs),
        "passed_specs": passed,
        "probe_contract_complete": probe_ids.issubset(passed_ids),
        "formal_complete": formal_complete,
        "result_direction_used_as_execution_gate": False,
        "claim_guard": "A fixed-budget search that does not find a solution above theta is not a mathematical infeasibility proof.",
    }
    if formal_complete:
        network_rows: list[dict[str, Any]] = []
        for instance in sorted({row["instance"] for row in paired_rows}):
            for condition in CONDITIONS:
                selected = [row for row in paired_rows if row["instance"] == instance and row["condition"] == condition]
                network_rows.append(
                    {
                        "instance": instance,
                        "condition": condition,
                        "seed_count": len(selected),
                        "mean_unrestricted_saving_pct": sum(float(row["unrestricted_saving_vs_independent_pct"]) for row in selected) / len(selected),
                        "mean_no_loss_saving_pct": sum(float(row["no_loss_saving_vs_independent_pct"]) for row in selected) / len(selected),
                        "mean_participation_cost_pct_points": sum(float(row["participation_cost_pct_points"]) for row in selected) / len(selected),
                        "unrestricted_natural_participation_count": sum(bool(row["unrestricted_both_depots_no_worse"]) for row in selected),
                        "mean_unrestricted_min_profit_ratio": sum(float(row["unrestricted_minimum_profit_ratio"]) for row in selected) / len(selected),
                        "mean_no_loss_min_profit_ratio": sum(float(row["no_loss_minimum_profit_ratio"]) for row in selected) / len(selected),
                    }
                )
        write_csv(OUT / "network_summary.csv", network_rows, ("instance",))
        for condition in CONDITIONS:
            selected = [row for row in network_rows if row["condition"] == condition]
            cost_values = [float(row["mean_participation_cost_pct_points"]) for row in selected]
            saving_values = [float(row["mean_no_loss_saving_pct"]) for row in selected]
            pos_cost = sum(value > 1e-9 for value in cost_values)
            neg_cost = sum(value < -1e-9 for value in cost_values)
            pos_saving = sum(value > 1e-9 for value in saving_values)
            neg_saving = sum(value < -1e-9 for value in saving_values)
            decision[condition] = {
                "mean_participation_cost_pct_points": sum(cost_values) / len(cost_values),
                "mean_no_loss_saving_pct": sum(saving_values) / len(saving_values),
                "networks_with_positive_participation_cost": pos_cost,
                "participation_cost_sign_test_p_two_sided": exact_two_sided_sign_p(pos_cost, neg_cost),
                "networks_with_positive_no_loss_saving": pos_saving,
                "no_loss_saving_sign_test_p_two_sided": exact_two_sided_sign_p(pos_saving, neg_saving),
            }
    write_json(OUT / "decision.json", decision)
    return decision


def build_contract() -> tuple[list[dict[str, Any]], str]:
    OUT.mkdir(parents=True, exist_ok=True)
    asset_rows = prepare_assets()
    source_paths = (
        Path(__file__).resolve(),
        ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
        ROOT / "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
        ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
        ROOT / "solver/src/setp_solver/profit.py",
        ROOT / "solver/src/setp_solver/check.py",
    )
    metadata = {
        "schema": "setp.e6.participation_formal.v1",
        "question": "What system-cost premium is required to keep both depots at least as profitable as independent operation?",
        "instances": [str(item["instance"]) for item in load_envelopes()],
        "conditions": list(CONDITIONS),
        "seeds": list(SEEDS),
        "probe_instance": PROBE_INSTANCE,
        "independent_budget_per_depot": INDEPENDENT_BUDGET_PER_DEPOT,
        "independent_total_budget": 2 * INDEPENDENT_BUDGET_PER_DEPOT,
        "cooperative_budget_per_arm": COOPERATIVE_BUDGET,
        "cooperative_arms": {label: {"fairness_enabled": enabled, "theta": THETA if enabled else None} for label, enabled in ARMS},
        "common_start_rule": "each cooperative arm starts byte-identically from the concatenation of the two independently optimized depot solutions",
        "asset_rule": "per-depot CV/EV caps are inherited from the sealed E3 ownership-fixed common start for the same network and portfolio condition",
        "fairness_metric": "each depot profit divided by its profit in the paired independently optimized solution",
        "revenue_rule": "customer revenue is credited to the serving depot; operating costs are charged to the route home depot",
        "cross_site_fee": 0.0,
        "carbon_weight": 0.0,
        "charging_strategy": "immediate feasible",
        "statistical_unit": "base network; three seeds are averaged within network-condition",
        "execution_gate": "only mechanical contract checks gate expansion; result direction never gates expansion",
        "claim_guard": "failure to find a solution is not a proof of mathematical infeasibility",
        "upstream_e3_metadata_sha256": sha256(E3 / "metadata.json"),
        "upstream_e3_decision_sha256": sha256(E3 / "decision.json"),
        "asset_preflight_sha256": sha256(OUT / "asset_preflight.csv"),
        "source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip(),
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in source_paths},
    }
    contract_sha256 = canonical_hash(metadata)
    metadata["contract_sha256"] = contract_sha256
    write_json(OUT / "metadata.json", metadata)
    preflight_index = {
        (row["instance"], row["condition"]): row
        for row in asset_rows
        if row["depot_id"] == sorted(depot_caps(row["instance"], row["condition"]))[0]
    }
    specs = [
        {
            "spec_id": f"{item['instance']}__{condition}__seed{seed}",
            "instance": str(item["instance"]),
            "condition": condition,
            "seed": seed,
            "common_start_sha256": preflight_index[(str(item["instance"]), condition)]["common_start_sha256"],
            "ownership_sha256": preflight_index[(str(item["instance"]), condition)]["ownership_sha256"],
            "contract_sha256": contract_sha256,
        }
        for item in load_envelopes()
        for condition in CONDITIONS
        for seed in SEEDS
    ]
    write_csv(OUT / "task_manifest.csv", specs, ("spec_id",))
    return specs, contract_sha256


def report(decision: dict[str, Any]) -> str:
    lines = [
        "# 合作参与条件正式比较",
        "",
        f"状态：`{decision['status']}`。已完成 {decision['completed_specs']}/{decision['expected_specs']} 组，机械合同通过 {decision['passed_specs']} 组。",
        "",
        "每组先让两个车场分别在各自客户和资产内计算 2000 次，再把两份排班合成同一个合作起点。随后从完全相同的起点出发，分别计算不限制单方收益的合作方案，以及保证双方收益均不低于各自经营的合作方案；两个合作方案各计算 4000 次。",
        "",
        "是否继续扩展只由预算、起点、成本闭合、收益闭合和实体排班是否合法决定，不由节省方向决定。固定预算内没有找到某个方案，不等于数学上证明该方案不存在。",
    ]
    if decision.get("formal_complete"):
        for condition, label in (("geographic", "按地理关系组织客户"), ("mixed", "客户空间交错")):
            row = decision[condition]
            lines.extend(
                [
                    "",
                    f"{label}：保证双方不吃亏后，相对各自经营仍平均节省 {row['mean_no_loss_saving_pct']:.6f}%；相对不限制收益的合作方案，参与条件平均增加 {row['mean_participation_cost_pct_points']:.6f} 个百分点的系统成本。",
                ]
            )
    return "\n".join(lines) + "\n"


def artifact_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("prepare", "probe", "remaining", "all"), default="prepare")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.workers not in {1, 2}:
        raise SystemExit("workers must be 1 or 2")
    specs, contract_sha256 = build_contract()
    selected: list[dict[str, Any]] = []
    if args.stage in {"probe", "all"}:
        selected.extend(
            spec for spec in specs if spec["instance"] == PROBE_INSTANCE and int(spec["seed"]) == 1
        )
    if args.stage in {"remaining", "all"}:
        selected.extend(
            spec for spec in specs if not (spec["instance"] == PROBE_INSTANCE and int(spec["seed"]) == 1)
        )
    if selected:
        selected.sort(key=lambda row: (row["instance"], row["condition"], int(row["seed"])))
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_spec, spec, contract_sha256): spec for spec in selected}
            for future in as_completed(futures):
                payload = future.result()
                print(json.dumps({"spec_id": payload["spec_id"], "pair_status": payload["pair_status"], "reason": payload.get("reason", "")}, ensure_ascii=False), flush=True)
    decision = aggregate(specs, contract_sha256)
    (OUT / "report.md").write_text(report(decision), encoding="utf-8")
    write_json(OUT / "artifact_hashes.json", artifact_hashes())
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    if args.stage == "prepare":
        return 0
    if args.stage == "probe":
        return 0 if decision.get("probe_contract_complete") else 2
    return 0 if decision.get("formal_complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
