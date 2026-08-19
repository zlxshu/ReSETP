#!/usr/bin/env python3
"""Small fairness-aware mismatch probe with an explicit measurement baseline."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e3_ablation.e3_mismatch_probe_20260713 import owners_from_frozen, write_owner_map
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_staged_alns_lns_hybrid, run_tvci_carbon_schedule_pair
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations
from baselines.e3_ablation._legacy_subbundle import (
    _subinstance_for_depot,
    _write_subbundle,
)
from setp_solver.search.multitrip_schedule import build_multitrip_certificate
from setp_solver.solution import Route, Solution

V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
ZERO_BUNDLE = V11 / "assets/200c/derived_bundles/zero_gamma"
ACTUAL_BUNDLE = V11 / "assets/200c/derived_bundles/actual_gamma"
OUT = ROOT / "baselines/e3_ablation/e3_mismatch_probe_20260713"
ORIGINAL_CAPS = {"D0": {"cv": 7, "ev": 7}, "D1": {"cv": 7, "ev": 7}}
M0_BUDGET = 200
COOP_BUDGET = 200
DEFAULT_SHARE = 0.25
DEFAULT_MAP_SEED = 20260713


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_owners_at_share(base: dict[str, str], share: float, map_seed: int) -> dict[str, str]:
    if share not in {0.25, 0.5}:
        raise ValueError("only the pre-registered 25% and 50% levels are allowed")
    rng = np.random.default_rng(map_seed)
    by_depot = {
        depot: sorted(customer for customer, owner in base.items() if owner == depot)
        for depot in ORIGINAL_CAPS
    }
    take_each = int(min(len(by_depot["D0"]), len(by_depot["D1"])) * share)
    owners = dict(base)
    for source, target in (("D0", "D1"), ("D1", "D0")):
        for customer_id in sorted(rng.choice(by_depot[source], size=take_each, replace=False).tolist()):
            owners[customer_id] = target
    return owners


def score_counts(result: dict[str, object]) -> dict[str, int]:
    out: dict[str, int] = {}
    def visit(value: object) -> None:
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


def profit_values(solution: Solution, bundle: object, prices: object, owners: dict[str, str]) -> dict[str, float]:
    rows = calculate_depot_profits(solution, bundle.instance, bundle.carbon_profile, prices, customer_home_depot=owners, carbon_quota_kg=0.0)
    return {depot: float(row.profit) for depot, row in rows.items()}


def prefixed(solution: Solution, depot: str) -> Solution:
    mapping = {route.vehicle_id: f"{depot}_{route.vehicle_id}" for route in solution.routes}
    return Solution(
        routes=[replace(route, vehicle_id=mapping[route.vehicle_id]) for route in solution.routes],
        charging_actions=[replace(action, vehicle_id=mapping.get(action.vehicle_id, f"{depot}_{action.vehicle_id}")) for action in solution.charging_actions],
        cross_site_services=[],
    )


def build_measurement_start(
    owners: dict[str, str],
    *,
    search_seed: int = 1,
    out_root: Path | None = None,
) -> tuple[Solution, dict[str, dict[str, int]]]:
    prices = legacy.prices_for("M0", 0.0)
    zero = load_search_bundle(ZERO_BUNDLE)
    meas_caps: dict[str, dict[str, int]] = {}
    output_root = out_root or OUT
    root = output_root / "measurement_subbundles"
    merged_routes: list[Route] = []
    merged_actions = []
    sub_rows: dict[str, object] = {}
    for index, depot in enumerate(sorted(ORIGINAL_CAPS)):
        subinstance = replace(_subinstance_for_depot(zero.instance, depot, owners), num_cv=None, num_ev=None)
        raw_routes = legacy._short_trips(subinstance, independent=True, prices=prices)
        raw_cert = build_multitrip_certificate(raw_routes, subinstance, prices)
        caps = {"cv": int(raw_cert.vehicle_counts["cv"]), "ev": int(raw_cert.vehicle_counts["ev"])}
        meas_caps[depot] = caps
        sub_path = root / depot
        _write_subbundle(sub_path, replace(subinstance, num_cv=caps["cv"], num_ev=caps["ev"]), ZERO_BUNDLE, depot)
        result = None
        with legacy.strict_mode({depot: caps}):
            result = run_staged_alns_lns_hybrid(
                sub_path,
                config=WinnerKernelConfig(seed=search_seed * 1000 + 301 + index, eval_budget=M0_BUDGET, max_runtime_seconds=600.0),
                initial_solution=Solution(routes=raw_routes),
                prices=prices,
                policy=SearchPolicy(max_cv=caps["cv"], max_ev=caps["ev"], allow_cross_depot=False),
            )
        if not result.get("feasible") or int(result.get("evaluations", -1)) != M0_BUDGET:
            raise RuntimeError(f"measurement M0 failed at {depot}: {result.get('evaluations')}/{M0_BUDGET}")
        found = prefixed(result["best_solution"], depot)
        merged_routes.extend(found.routes)
        merged_actions.extend(found.charging_actions)
        sub_rows[depot] = {
            "raw_route_count": len(raw_routes),
            "raw_physical_cv": int(raw_cert.vehicle_counts["cv"]),
            "raw_physical_ev": int(raw_cert.vehicle_counts["ev"]),
            "search_evaluations": int(result["evaluations"]),
            "search_cost": float(result.get("best_cost", 0.0)),
        }
    merged = Solution(routes=merged_routes, charging_actions=merged_actions)
    # The measurement baseline is intentionally allowed to use more vehicles than
    # the sealed cooperation fleet.  It is a cost/profit reference, not a new
    # formal asset setting, so do not force it through the original 14+14 cap.
    total_physical = {
        "cv": sum(caps["cv"] for caps in meas_caps.values()),
        "ev": sum(caps["ev"] for caps in meas_caps.values()),
    }
    write_json(output_root / "measurement_subruns.json", sub_rows)
    write_json(output_root / "measurement_caps.json", meas_caps)
    write_json(output_root / "measurement_start.json", legacy.solution_to_dict(merged))
    write_json(output_root / "measurement_certificate.json", {"measurement_only": True, "vehicle_counts": total_physical})
    return merged, meas_caps


def run_cooperation(
    start: Solution,
    owners: dict[str, str],
    *,
    search_seed: int = 1,
    out_root: Path | None = None,
    budget: int | None = None,
) -> dict[str, object]:
    actual = load_search_bundle(ACTUAL_BUNDLE)
    prices = legacy.prices_for("M5", 0.0)
    output_root = out_root or OUT
    run_budget = budget if budget is not None else COOP_BUDGET
    independent_profit = profit_values(start, actual, prices, owners)
    independent_metrics = legacy._metric_row(start, actual, prices)[0]
    shared = legacy.solution_from_dict(json.loads((V11 / "assets/200c/shared_start.json").read_text(encoding="utf-8")))
    context = EvaluationContext(actual.instance, actual.carbon_profile, prices=prices, carbon_weight=1.0, fairness_enabled=True, independent_profit=independent_profit, fairness_theta=1.0, customer_home_depot=owners, allow_cross_depot=True)
    with legacy.strict_mode(ORIGINAL_CAPS):
        shared_prepared, shared_certificate = prepare_solution(shared, context)
    shared_profit = profit_values(shared_prepared, actual, prices, owners)
    shared_ratios = {depot: shared_profit[depot] / independent_profit[depot] for depot in independent_profit}
    if shared_certificate is None:
        raise RuntimeError("shared starting solution has no strict certificate")
    started = time.perf_counter()
    with legacy.strict_mode(ORIGINAL_CAPS):
        result = run_tvci_carbon_schedule_pair(
            ACTUAL_BUNDLE,
            config=WinnerKernelConfig(seed=search_seed, eval_budget=run_budget, max_runtime_seconds=600.0),
            initial_solution=shared_prepared,
            prices=prices,
            policy=SearchPolicy(max_cv=14, max_ev=14, allow_cross_depot=True),
            carbon_weight=1.0,
            fairness_enabled=True,
            independent_profit=independent_profit,
            fairness_theta=1.0,
            customer_home_depot=owners,
        )
    with legacy.strict_mode(ORIGINAL_CAPS):
        prepared, certificate = prepare_solution(result["best_solution"], context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    counts = score_counts(result)
    profits = profit_values(prepared, actual, prices, owners)
    ratios = {depot: profits[depot] / independent_profit[depot] for depot in independent_profit}
    cross_service_count = len(prepared.cross_site_services)
    cross_unique_count = len({service.customer_id for service in prepared.cross_site_services})
    independent_cost = float(independent_metrics["total_cost"])
    cooperative_metrics = legacy._metric_row(prepared, actual, prices)[0]
    cooperative_cost = float(cooperative_metrics["total_cost"])
    component_keys = [
        "cost_km", "cost_fuel", "cost_elec", "cost_fix", "cost_occ",
        "cost_carbon", "cost_transship", "total_cost",
    ]
    row = {
        "status": "OK" if int(result.get("evaluations", -1)) == run_budget and not violations else "HALT_CONTRACT",
        "reason": "; ".join(str(item) for item in violations),
        "actual_evals": int(result.get("evaluations", -1)),
        "elapsed_seconds": time.perf_counter() - started,
        "search_seed": search_seed,
        "budget": run_budget,
        "independent_profit": independent_profit,
        "independent_cost": independent_cost,
        "independent_cost_components": {key: float(independent_metrics.get(key, 0.0)) for key in component_keys},
        "shared_start_profit_ratios": shared_ratios,
        "total_cost": cooperative_cost,
        "cooperative_cost_components": {key: float(cooperative_metrics.get(key, 0.0)) for key in component_keys},
        "saving_pct_vs_measurement_start": (independent_cost - cooperative_cost) / independent_cost * 100.0,
        "cross_site_service_count": cross_service_count,
        "cross_site_customer_count": cross_unique_count,
        "cross_site_attempted_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        "fairness_rejected_candidates": int(counts.get("strict_reject_profit_fairness", 0)),
        "final_profit_ratios": ratios,
        "fairness_ok": all(value >= 1.0 - 1e-9 for value in ratios.values()),
        "physical_total": certificate.vehicle_counts["cv"] + certificate.vehicle_counts["ev"] if certificate else None,
    }
    write_json(output_root / "measurement_cooperation_probe.json", row)
    write_json(output_root / "measurement_cooperation_solution.json", legacy.solution_to_dict(prepared))
    if certificate:
        write_json(output_root / "measurement_cooperation_certificate.json", certificate.as_dict())
    return row


def main() -> int:
    import argparse

    global OUT, COOP_BUDGET
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--share", type=float, choices=(0.25, 0.5), default=DEFAULT_SHARE)
    parser.add_argument("--map-seed", type=int, default=DEFAULT_MAP_SEED)
    parser.add_argument("--budget", type=int, default=COOP_BUDGET)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    OUT = ROOT / args.output if not args.output.is_absolute() else args.output
    COOP_BUDGET = args.budget
    owners = generate_owners_at_share(owners_from_frozen(), args.share, args.map_seed)
    base = owners_from_frozen()
    OUT.mkdir(parents=True, exist_ok=True)
    write_owner_map(OUT / f"ownership_{int(args.share * 100)}.csv", owners, base)
    write_json(OUT / "ownership_generator.json", {
        "schema": "setp.e3.synthetic_ownership.v1",
        "share": args.share,
        "map_seed": args.map_seed,
        "selection": "sorted customers, equal reciprocal swaps, fixed before search, no result-based selection",
        "moved_count": sum(owners[c] != base[c] for c in owners),
        "base_owner_rows_sha256": sha256(legacy.OWNER_ROWS),
    })
    # The remaining functions use the module-level output root by design.
    start, meas_caps = build_measurement_start(owners, search_seed=1)
    coop = run_cooperation(start, owners, search_seed=1)
    decision = {
        "schema": "setp.e3.mismatch_fair_probe.decision.v1",
        "verdict": "E3_MISMATCH_FAIR_PROBE_PASS" if coop["status"] == "OK" else "HALT_E3_MISMATCH_FAIR_PROBE",
        "share": args.share,
        "map_seed": args.map_seed,
        "budget": args.budget,
        "measurement_caps": meas_caps,
        "cooperation": coop,
        "cross_space_opened": bool(coop["cross_site_legal_candidates"] > 0 or coop["cross_site_customer_count"] > 0),
        "next_step": "只有跨场空间打开才值得设计完整错配矩阵" if coop["cross_site_legal_candidates"] > 0 else "错配仍未打开公平合作空间，停止扩展",
    }
    write_json(OUT / "measurement_decision.json", decision)
    (OUT / "measurement_report.md").write_text(
        f"# {args.share:.0%}错配公平测量探针\n\n"
        "独立臂使用测量模式记录所需资产；合作臂仍锁定原始 7+7 资产。该探针不是正式统计。\n\n"
        f"错配比例：{args.share:.0%}；测量资产：{json.dumps(meas_caps, ensure_ascii=False, sort_keys=True)}\n"
        f"合作臂：尝试 {coop['cross_site_attempted_candidates']}，合法 {coop['cross_site_legal_candidates']}，采纳 {coop['cross_site_accepted_candidates']}，最终换场客户 {coop['cross_site_customer_count']}（服务记录 {coop['cross_site_service_count']}）。\n"
        f"下一步：{decision['next_step']}。\n",
        encoding="utf-8",
    )
    hashes = {str(path.relative_to(OUT)): sha256(path) for path in sorted(OUT.rglob("*")) if path.is_file()}
    write_json(OUT / "measurement_artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
