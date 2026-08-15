#!/usr/bin/env python3
"""Zero-search contract audit across the current E1-E7 submission lanes."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import calculate_depot_profits, infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution


E2_RAW = Path("baselines/e2_alns/e2_submission_20260711/carbon_280/raw_runs.csv")
E3_RAW = Path("baselines/e3_ablation/e3_submission_20260711/formal/raw_runs.csv")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def solution_from_json(text: str) -> Solution:
    payload = json.loads(text)
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in payload.get("cross_site_services", [])],
    )


def annotate_cross_site(solution: Solution, instance: Any, owners: dict[str, str]) -> Solution:
    customer_ids = {node.node_id for node in instance.nodes if node.node_type.lower() == "c"}
    services = [
        CrossSiteService(customer_id=node_id, served_by_depot_id=route.home_depot_id)
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in customer_ids and owners.get(node_id) != route.home_depot_id
    ]
    return replace(solution, cross_site_services=services)


def e2_replay(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = read_csv(repo_root / E2_RAW)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)
    bundle_cache: dict[str, Any] = {}
    replay: list[dict[str, Any]] = []
    for row in rows:
        instance_name = row["instance"]
        if instance_name not in bundle_cache:
            bundle_cache[instance_name] = load_search_bundle(
                repo_root / "models/data_bundle/generated_instances/L-main" / instance_name
            )
        bundle = bundle_cache[instance_name]
        solution = solution_from_json(row["solution_json"])
        owners = infer_customer_home_depots(bundle.instance)
        annotated = annotate_cross_site(solution, bundle.instance, owners)
        original_metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=0.0)
        annotated_metrics = evaluate(annotated, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=0.0)
        violations = check_solution(solution, bundle.instance, prices)
        replay.append(
            {
                "algorithm": row["algorithm"],
                "instance": instance_name,
                "seed": int(row["seed"]),
                "reported_cost": float(row["best_cost"]),
                "replayed_free_cross_site_cost": float(original_metrics["total_cost"]),
                "free_cost_match": abs(float(row["best_cost"]) - float(original_metrics["total_cost"])) <= 1e-7,
                "current_checker_violation_count": len(violations),
                "cross_site_customer_count": len(annotated.cross_site_services),
                "cross_site_cost_if_enabled": float(annotated_metrics["cost_transship"]),
                "what_if_total_cost_with_cross_site_fee": float(annotated_metrics["total_cost"]),
                "what_if_cost_delta": float(annotated_metrics["total_cost"] - original_metrics["total_cost"]),
                "original_cross_site_list_count": len(solution.cross_site_services),
            }
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in replay:
        grouped.setdefault(str(row["algorithm"]), []).append(row)
    summary = [
        {
            "algorithm": algorithm,
            "run_count": len(group),
            "current_checker_violation_runs": sum(int(row["current_checker_violation_count"] > 0) for row in group),
            "free_cost_mismatch_runs": sum(int(not row["free_cost_match"]) for row in group),
            "cross_site_customer_total": sum(int(row["cross_site_customer_count"]) for row in group),
            "reported_cost_total": sum(float(row["reported_cost"]) for row in group),
            "what_if_cost_total_with_cross_site_fee": sum(float(row["what_if_total_cost_with_cross_site_fee"]) for row in group),
        }
        for algorithm, group in sorted(grouped.items())
    ]
    return replay, summary


def e2_200c_fairness(repo_root: Path, replay_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    e2_rows = read_csv(repo_root / E2_RAW)
    e3_rows = read_csv(repo_root / E3_RAW)
    bundle = load_search_bundle(repo_root / "models/data_bundle/generated_instances/L-main/L-main-threeshift-200c-01")
    owners = infer_customer_home_depots(bundle.instance)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)
    e2_index = {(row["algorithm"], int(row["seed"])): row for row in e2_rows if row["instance"] == "L-main-threeshift-200c-01"}
    m0_index = {int(row["seed"]): row for row in e3_rows if row["variant"] == "M0"}
    hybrid_emissions = {
        int(row["seed"]): float(row["E_total"])
        for row in e2_rows
        if row["instance"] == "L-main-threeshift-200c-01" and row["algorithm"] == "staged_hybrid_carbon_aware"
    }
    out: list[dict[str, Any]] = []
    for (algorithm, seed), row in sorted(e2_index.items(), key=lambda item: (item[0][0], item[0][1])):
        quota = 0.8 * hybrid_emissions[seed]
        m0_solution = solution_from_json(m0_index[seed]["solution_json"])
        baseline_rows = calculate_depot_profits(
            m0_solution,
            bundle.instance,
            bundle.carbon_profile,
            prices,
            customer_home_depot=owners,
            carbon_quota_kg=quota,
        )
        baseline = {depot_id: float(value.profit) for depot_id, value in baseline_rows.items()}
        solution = annotate_cross_site(solution_from_json(row["solution_json"]), bundle.instance, owners)
        profit_rows = calculate_depot_profits(
            solution,
            bundle.instance,
            bundle.carbon_profile,
            prices,
            customer_home_depot=owners,
            carbon_quota_kg=quota,
        )
        profits = {depot_id: float(value.profit) for depot_id, value in profit_rows.items()}
        ratios = {depot_id: profits[depot_id] / value for depot_id, value in baseline.items() if value > 1e-12}
        out.append(
            {
                "algorithm": algorithm,
                "seed": seed,
                "quota_kg": quota,
                "baseline_profits": json.dumps(baseline, sort_keys=True),
                "cooperative_profits_with_fee": json.dumps(profits, sort_keys=True),
                "profit_ratios": json.dumps(ratios, sort_keys=True),
                "min_profit_ratio": min(ratios.values()) if ratios else "",
                "theta_1_feasible": bool(ratios) and min(ratios.values()) >= 1.0 - 1e-9,
                "cross_site_customer_count": next(
                    int(item["cross_site_customer_count"])
                    for item in replay_rows
                    if item["algorithm"] == algorithm and item["instance"] == "L-main-threeshift-200c-01" and int(item["seed"]) == seed
                ),
            }
        )
    return out


def hybrid_fee_sensitivity(repo_root: Path) -> list[dict[str, Any]]:
    """Read-only fairness diagnostic over the saved 200c hybrid solutions."""

    e2_rows = read_csv(repo_root / E2_RAW)
    e3_rows = read_csv(repo_root / E3_RAW)
    bundle = load_search_bundle(repo_root / "models/data_bundle/generated_instances/L-main/L-main-threeshift-200c-01")
    owners = infer_customer_home_depots(bundle.instance)
    output: list[dict[str, Any]] = []
    for fee in (0.0, 10.0, 25.0, 50.0, 95.0):
        prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034, cross_site_cost=fee)
        for seed in range(1, 6):
            e2_row = next(
                row for row in e2_rows
                if row["instance"] == "L-main-threeshift-200c-01"
                and row["algorithm"] == "staged_hybrid_carbon_aware"
                and int(row["seed"]) == seed
            )
            m0_row = next(row for row in e3_rows if row["variant"] == "M0" and int(row["seed"]) == seed)
            quota = 0.8 * float(e2_row["E_total"])
            baseline_rows = calculate_depot_profits(
                solution_from_json(m0_row["solution_json"]), bundle.instance, bundle.carbon_profile, prices,
                customer_home_depot=owners, carbon_quota_kg=quota,
            )
            baseline = {depot_id: float(value.profit) for depot_id, value in baseline_rows.items()}
            candidate = annotate_cross_site(solution_from_json(e2_row["solution_json"]), bundle.instance, owners)
            profit_rows = calculate_depot_profits(
                candidate, bundle.instance, bundle.carbon_profile, prices,
                customer_home_depot=owners, carbon_quota_kg=quota,
            )
            ratios = {
                depot_id: float(profit_rows[depot_id].profit) / value
                for depot_id, value in baseline.items() if value > 1e-12
            }
            output.append(
                {
                    "cross_site_fee": fee,
                    "seed": seed,
                    "cross_site_customer_count": len(candidate.cross_site_services),
                    "min_profit_ratio": min(ratios.values()),
                    "theta_1_feasible": min(ratios.values()) >= 1.0 - 1e-9,
                    "profit_ratios": json.dumps(ratios, sort_keys=True),
                    "diagnostic_only": True,
                }
            )
    return output


def contract_matrix() -> list[dict[str, Any]]:
    return [
        {"experiment": "E1 current M1", "formal_status": "partial formal", "battery_kwh": 280, "cross_site_fee": "off in reused E2/search rows", "fairness": "off", "carbon_quota": "0", "carbon_price": "default", "paper_ready": "no", "reason": "mixed rows inherit E2 free-cross-site contract; counterfactual search also omits owners"},
        {"experiment": "E2 frozen submission", "formal_status": "formal internal algorithm comparison", "battery_kwh": 280, "cross_site_fee": "off", "fairness": "off", "carbon_quota": "0", "carbon_price": 0.05034, "paper_ready": "only as relaxed-contract algorithm comparison", "reason": "270 rows are internally fair but do not implement the full paper contract"},
        {"experiment": "E3 current M1", "formal_status": "partial formal", "battery_kwh": 280, "cross_site_fee": "M0 off; M1-M5 on", "fairness": "M5 theta=1 only", "carbon_quota": "M0-M3 0; M4-M5 0.8*E2", "carbon_price": "M0-M3 0; M4-M5 default", "paper_ready": "partial", "reason": "mechanism ladder is executable but its base contract differs from E1/E2"},
        {"experiment": "E4 legacy formal runner", "formal_status": "not rerun on M1 contract", "battery_kwh": 80, "cross_site_fee": "off", "fairness": "off", "carbon_quota": "grid from default baseline", "carbon_price": "0.5-4x default", "paper_ready": "no", "reason": "old runner and old story do not match the 280 kWh positive scenario or refined carbon search"},
        {"experiment": "E5 legacy replay", "formal_status": "not rerun on M1 contract", "battery_kwh": 80, "cross_site_fee": "source dependent", "fairness": "off", "carbon_quota": "source dependent", "carbon_price": "default", "paper_ready": "no", "reason": "fixed-route replay is useful as a mechanism control but source report is stale"},
        {"experiment": "E6 legacy formal runner", "formal_status": "not rerun on M1 contract", "battery_kwh": 80, "cross_site_fee": "profit layer on", "fairness": "on", "carbon_quota": "runner dependent", "carbon_price": "default", "paper_ready": "no", "reason": "theta grid misses the observed binding region and the collaboration fee contract is unsettled"},
        {"experiment": "E7 legacy dynamic runner", "formal_status": "not final", "battery_kwh": 80, "cross_site_fee": "off/unclear in rolling search", "fairness": "off", "carbon_quota": "not closed", "carbon_price": "default", "paper_ready": "no", "reason": "dynamic state work exists, but full collaboration-fairness-carbon interaction is not closed"},
        {"experiment": "paper_main.tex declared main", "formal_status": "manuscript declaration", "battery_kwh": 80, "cross_site_fee": 95, "fairness": "theta=1", "carbon_quota": "0.8*Ebase", "carbon_price": "default", "paper_ready": "declaration only", "reason": "does not match the current 280 kWh E1-E3 execution contracts"},
    ]


def artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    replay, summary = e2_replay(root)
    fairness = e2_200c_fairness(root, replay)
    fee_sensitivity = hybrid_fee_sensitivity(root)
    matrix = contract_matrix()
    write_csv(output / "e2_replay_rows.csv", replay)
    write_csv(output / "e2_algorithm_summary.csv", summary)
    write_csv(output / "e2_200c_fairness.csv", fairness)
    write_csv(output / "e2_200c_hybrid_fee_sensitivity.csv", fee_sensitivity)
    write_csv(output / "e1_e7_contract_matrix.csv", matrix)
    all_replayed_clean = len(replay) == 270 and all(
        bool(row["free_cost_match"]) and int(row["current_checker_violation_count"]) == 0 for row in replay
    )
    algorithms = {row["algorithm"]: row for row in summary}
    hybrid = algorithms.get("staged_hybrid_carbon_aware", {})
    lns = algorithms.get("LNS", {})
    fairness_hybrid = [row for row in fairness if row["algorithm"] == "staged_hybrid_carbon_aware"]
    decision = {
        "verdict": "BLOCK_FORMAL_E4_E7_PENDING_SUBMISSION_CONTRACT_DECISION",
        "zero_new_search": True,
        "e2_rows_replayed": len(replay),
        "e2_all_current_checker_zero_violation_and_cost_match": all_replayed_clean,
        "hybrid_cross_site_customer_total": hybrid.get("cross_site_customer_total"),
        "lns_cross_site_customer_total": lns.get("cross_site_customer_total"),
        "e2_200c_hybrid_theta1_feasible_runs_with_fee_and_e3_baseline": sum(bool(row["theta_1_feasible"]) for row in fairness_hybrid),
        "e2_200c_hybrid_theta1_checked_runs": len(fairness_hybrid),
        "e2_200c_hybrid_theta1_feasible_runs_even_at_zero_cross_site_fee": sum(
            bool(row["theta_1_feasible"]) for row in fee_sensitivity if float(row["cross_site_fee"]) == 0.0
        ),
        "e2_internal_algorithm_comparison_still_valid": all_replayed_clean,
        "e2_full_paper_model_claim_valid": False,
        "formal_4000_refined_carbon_authorized": False,
        "required_user_decision": "Freeze one submission contract for battery, customer ownership/cross-site fee, fairness, and carbon quota before more formal search.",
    }
    metadata = {
        "schema_version": "resetp.e1_e7_submission_contract_audit.v1",
        "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "sources": [str(E2_RAW), str(E3_RAW), "solver/src/setp_solver/search/formal_runner.py", "docs/paper_submission_final/RETIRED_paper_main.tex"],
        "customer_owner_rule": "nearest depot using infer_customer_home_depots; pending final user approval",
        "no_search": True,
    }
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    report = [
        "# E1-E7 submission contract audit",
        "",
        f"Verdict: `{decision['verdict']}`.",
        "",
        f"The frozen E2 280 kWh table remains internally valid: {len(replay)}/270 saved rows replayed under the current checker, with zero violations and matching free-cross-site costs: {all_replayed_clean}.",
        f"However, nearest-depot annotation finds {hybrid.get('cross_site_customer_total')} cross-site customers for the hybrid and {lns.get('cross_site_customer_total')} for LNS across 45 runs. Those services were not charged in the frozen E2 objective.",
        f"For the five 200c hybrid rows, theta=1 feasibility after enabling the 95 GBP cross-site fee and using the seed-matched E3 independent baseline holds in {decision['e2_200c_hybrid_theta1_feasible_runs_with_fee_and_e3_baseline']}/{decision['e2_200c_hybrid_theta1_checked_runs']} rows.",
        "",
        "Therefore E2 can be reported as a same-contract algorithm comparison, but not yet as the final full-model result. E4-E7 formal search stays blocked until one paper submission contract is frozen.",
        "",
        "The detailed rows and the E1-E7 switch matrix are stored beside this report. What-if costs are diagnostics only; they are not legal replacement scores because the algorithms did not optimize under the added fee.",
        "",
    ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    write_json(output / "artifact_hashes.json", artifact_hashes(output))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
