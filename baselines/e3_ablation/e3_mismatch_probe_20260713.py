#!/usr/bin/env python3
"""Minimum-cost 25% ownership-mismatch probe for the E3 branch."""

from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_staged_alns_lns_hybrid, run_tvci_carbon_schedule_pair
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations
from setp_solver.search.fairness import _subinstance_for_depot, _write_subbundle
from setp_solver.solution import ChargingAction, Route, Solution

V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
ZERO_BUNDLE = V11 / "assets/200c/derived_bundles/zero_gamma"
ACTUAL_BUNDLE = V11 / "assets/200c/derived_bundles/actual_gamma"
INSTANCE = "L-main-threeshift-200c-01"
OUT = ROOT / "baselines/e3_ablation/e3_mismatch_probe_20260713"
MAP_SEED = 20260713
M0_BUDGET_PER_DEPOT = 200
AB_BUDGET = 200
CAPS = {"D0": {"cv": 7, "ev": 7}, "D1": {"cv": 7, "ev": 7}}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owners_from_frozen() -> dict[str, str]:
    return legacy.owner_map(INSTANCE)


def generate_owners(base: dict[str, str]) -> dict[str, str]:
    rng = np.random.default_rng(MAP_SEED)
    by_depot = {depot: sorted(customer for customer, owner in base.items() if owner == depot) for depot in CAPS}
    take_each = min(len(by_depot["D0"]), len(by_depot["D1"])) // 4
    moved: dict[str, str] = {}
    for source, target in (("D0", "D1"), ("D1", "D0")):
        selected = sorted(rng.choice(by_depot[source], size=take_each, replace=False).tolist())
        for customer_id in selected:
            moved[customer_id] = target
    owners = dict(base)
    owners.update(moved)
    return owners


def write_owner_map(path: Path, owners: dict[str, str], base: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance", "customer_id", "home_depot_id", "base_home_depot_id", "moved"])
        writer.writeheader()
        for customer_id in sorted(owners):
            writer.writerow({
                "instance": INSTANCE,
                "customer_id": customer_id,
                "home_depot_id": owners[customer_id],
                "base_home_depot_id": base[customer_id],
                "moved": int(owners[customer_id] != base[customer_id]),
            })


def make_subbundles(owners: dict[str, str], root: Path) -> None:
    source_bundle = load_search_bundle(ZERO_BUNDLE)
    for depot, caps in CAPS.items():
        subinstance = _subinstance_for_depot(source_bundle.instance, depot, owners)
        subinstance = replace(subinstance, num_cv=caps["cv"], num_ev=caps["ev"])
        path = root / "subbundles" / depot
        _write_subbundle(path, subinstance, ZERO_BUNDLE, depot)
        payload = json.loads((path / "instance.json").read_text(encoding="utf-8"))
        payload.setdefault("metadata", {}).update({"num_cv": caps["cv"], "num_ev": caps["ev"], "owner_map_sha256": sha256(root / "ownership_25.csv")})
        (path / "instance.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def prefixed_solution(solution: Solution, depot: str) -> Solution:
    mapping = {route.vehicle_id: f"{depot}_{route.vehicle_id}" for route in solution.routes}
    routes = [replace(route, vehicle_id=mapping[route.vehicle_id]) for route in solution.routes]
    actions = [replace(action, vehicle_id=mapping.get(action.vehicle_id, f"{depot}_{action.vehicle_id}")) for action in solution.charging_actions]
    return Solution(routes=routes, charging_actions=actions, cross_site_services=[])


def profit_values(solution: Solution, bundle: Any, prices: Any, owners: dict[str, str]) -> dict[str, float]:
    rows = calculate_depot_profits(solution, bundle.instance, bundle.carbon_profile, prices, customer_home_depot=owners, carbon_quota_kg=0.0)
    return {depot: float(row.profit) for depot, row in rows.items()}


def score_counts(result: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "score_counts" and isinstance(item, dict):
                    for name, count in item.items():
                        if isinstance(count, (int, float)):
                            out[name] = out.get(name, 0) + int(count)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(result.get("operator_counts", {}))
    return out


def build_independent_start(owners: dict[str, str], root: Path) -> tuple[Solution, dict[str, Any]]:
    prices = legacy.prices_for("M0", 0.0)
    merged_routes: list[Route] = []
    merged_actions: list[ChargingAction] = []
    rows: dict[str, Any] = {}
    for index, depot in enumerate(sorted(CAPS)):
        sub_path = root / "subbundles" / depot
        bundle = load_search_bundle(sub_path)
        routes = legacy._short_trips(bundle.instance, independent=True, prices=prices)
        routes = legacy._assign_types_within_assets(routes, bundle.instance, prices)
        initial = Solution(routes=routes)
        with legacy.strict_mode({depot: CAPS[depot]}):
            result = run_staged_alns_lns_hybrid(
                sub_path,
                config=WinnerKernelConfig(seed=100 + index, eval_budget=M0_BUDGET_PER_DEPOT, max_runtime_seconds=600.0),
                initial_solution=initial,
                prices=prices,
                policy=SearchPolicy(max_cv=CAPS[depot]["cv"], max_ev=CAPS[depot]["ev"], allow_cross_depot=False),
            )
        if not result.get("feasible") or int(result.get("evaluations", -1)) != M0_BUDGET_PER_DEPOT:
            raise RuntimeError(f"M0 subproblem failed for {depot}: {result.get('evaluations')}/{M0_BUDGET_PER_DEPOT}")
        found = prefixed_solution(result["best_solution"], depot)
        merged_routes.extend(found.routes)
        merged_actions.extend(found.charging_actions)
        rows[depot] = {
            "evaluations": int(result["evaluations"]),
            "route_count": len(found.routes),
            "customer_count": sum(1 for route in found.routes for node_id in route.node_sequence[1:-1] if node_id.startswith("C")),
            "cost": float(result.get("best_cost", 0.0)),
        }
    merged = Solution(routes=merged_routes, charging_actions=merged_actions)
    full_bundle = load_search_bundle(ZERO_BUNDLE)
    context = EvaluationContext(full_bundle.instance, full_bundle.carbon_profile, prices=prices, customer_home_depot=owners, allow_cross_depot=False)
    with legacy.strict_mode(CAPS):
        prepared, certificate = prepare_solution(merged, context)
        violations = hard_violations(prepared, context)
    if certificate is None or violations:
        raise RuntimeError(f"merged mismatch M0 failed strict check: {violations}")
    rows["merged"] = {
        "physical_cv": certificate.vehicle_counts["cv"],
        "physical_ev": certificate.vehicle_counts["ev"],
        "physical_total": certificate.vehicle_counts["cv"] + certificate.vehicle_counts["ev"],
        "trip_count": len(certificate.trips),
    }
    write_json(root / "m0_start_certificate.json", certificate.as_dict())
    write_json(root / "m0_subruns.json", rows)
    write_json(root / "m0_start.json", legacy.solution_to_dict(prepared))
    return prepared, rows


def run_arm(start: Solution, owners: dict[str, str], arm: str, root: Path) -> dict[str, Any]:
    bundle = load_search_bundle(ACTUAL_BUNDLE)
    prices = legacy.prices_for("M5", 0.0)
    independent_profit = profit_values(start, bundle, prices, owners)
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices, carbon_weight=1.0, fairness_enabled=True, independent_profit=independent_profit, fairness_theta=1.0, customer_home_depot=owners, allow_cross_depot=arm == "B_cross")
    policy = SearchPolicy(max_cv=14, max_ev=14, allow_cross_depot=arm == "B_cross")
    started = time.perf_counter()
    with legacy.strict_mode(CAPS):
        result = run_tvci_carbon_schedule_pair(
            ACTUAL_BUNDLE,
            config=WinnerKernelConfig(seed=1, eval_budget=AB_BUDGET, max_runtime_seconds=600.0),
            initial_solution=start,
            prices=prices,
            policy=policy,
            carbon_weight=1.0,
            fairness_enabled=True,
            independent_profit=independent_profit,
            fairness_theta=1.0,
            customer_home_depot=owners,
        )
    with legacy.strict_mode(CAPS):
        prepared, certificate = prepare_solution(result["best_solution"], context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None:
        raise RuntimeError(f"{arm} returned no certificate")
    metrics = legacy._metric_row(prepared, bundle, prices)[0]
    counts = score_counts(result)
    row = {
        "arm": arm,
        "status": "OK" if int(result.get("evaluations", -1)) == AB_BUDGET and not violations else "HALT_CONTRACT",
        "reason": "; ".join(str(item) for item in violations),
        "actual_evals": int(result.get("evaluations", -1)),
        "elapsed_seconds": time.perf_counter() - started,
        "total_cost": float(metrics["total_cost"]),
        "cross_site_customer_count": len(prepared.cross_site_services),
        "cross_site_attempted_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        "fairness_rejected_candidates": int(counts.get("strict_reject_profit_fairness", 0)),
        "physical_total": certificate.vehicle_counts["cv"] + certificate.vehicle_counts["ev"],
        "min_profit_ratio": min((profit_values(prepared, bundle, prices, owners)[depot] / independent_profit[depot]) for depot in independent_profit),
    }
    write_json(root / f"{arm}.json", row)
    write_json(root / f"{arm}_solution.json", legacy.solution_to_dict(prepared))
    write_json(root / f"{arm}_certificate.json", certificate.as_dict())
    return row


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base = owners_from_frozen()
    owners = generate_owners(base)
    write_owner_map(OUT / "ownership_25.csv", owners, base)
    write_json(OUT / "ownership_25_generator.json", {
        "schema": "setp.e3.synthetic_ownership.v1",
        "instance": INSTANCE,
        "share": 0.25,
        "map_seed": MAP_SEED,
        "selection": "sorted customers, equal reciprocal swaps from D0 and D1, no result-based selection",
        "moved_count": sum(owners[c] != base[c] for c in owners),
        "base_owner_rows_sha256": sha256(legacy.OWNER_ROWS),
    })
    make_subbundles(owners, OUT)
    start, m0_rows = build_independent_start(owners, OUT)
    a = run_arm(start, owners, "A_no_cross", OUT)
    b = run_arm(start, owners, "B_cross", OUT)
    decision = {
        "schema": "setp.e3.mismatch_probe.decision.v1",
        "verdict": "E3_MISMATCH_PROBE_PASS" if a["status"] == b["status"] == "OK" else "HALT_E3_MISMATCH_PROBE",
        "m0_budget_per_depot": M0_BUDGET_PER_DEPOT,
        "ab_budget": AB_BUDGET,
        "a": a,
        "b": b,
        "cross_space_opened": bool(b["cross_site_legal_candidates"] > 0 or b["cross_site_customer_count"] > 0),
        "next_step": "允许设计完整错配矩阵" if b["cross_site_legal_candidates"] > 0 or b["cross_site_customer_count"] > 0 else "停止错配扩展，保留v11边界结论",
    }
    write_json(OUT / "decision.json", decision)
    lines = [
        "# E3 25%归属错配最小探针",
        "",
        f"判决：`{decision['verdict']}`。这不是正式统计，只判断错配是否打开公平合作的合法空间。",
        "",
        f"归属表固定随机种子 {MAP_SEED}，共 {sum(owners[c] != base[c] for c in owners)} 个客户换到另一车场；原始归属文件和v11封存目录未改。",
        f"A臂：跨场关闭，成本 {a['total_cost']:.6f}，跨场客户 {a['cross_site_customer_count']}。",
        f"B臂：跨场开启，成本 {b['total_cost']:.6f}，尝试 {b['cross_site_attempted_candidates']}，合法 {b['cross_site_legal_candidates']}，采纳 {b['cross_site_accepted_candidates']}，跨场客户 {b['cross_site_customer_count']}。",
        "",
        decision["next_step"],
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hashes = {str(path.relative_to(OUT)): sha256(path) for path in sorted(OUT.rglob("*")) if path.is_file()}
    write_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
