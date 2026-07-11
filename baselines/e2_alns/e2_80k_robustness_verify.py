#!/usr/bin/env python3
"""Independent verifier and preregistered decision for the 80 kWh mirror gate."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as closure
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import solution_signature_hash
from setp_solver.search.feasible_repair import route_customers, route_distance
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.solution import physical_vehicle_id


FROZEN_COMMIT = "0124623e347cd2a6a5548e07e0af66e16d3b634b"
DEFAULT_PHASE_DIR = REPO_ROOT / "baselines/e2_alns/e2_80k_robustness_20260711/formal"
EXPECTED_INSTANCES = tuple(f"L-main-threeshift-{size}c-01" for size in (15, 50, 100, 200))
EXPECTED_ALGORITHMS = ("staged_hybrid_carbon_aware", "staged_hybrid_carbon_naive", "LNS")
TOLERANCE = 1e-6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase-dir", default=str(DEFAULT_PHASE_DIR))
    parser.add_argument("--execution-commit", default=FROZEN_COMMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    phase_dir = Path(args.phase_dir).resolve()
    metadata = closure.read_json(phase_dir / "metadata.json")
    task_rows = closure.read_csv(phase_dir / "task_runs.csv")
    rows = closure.read_csv(phase_dir / "raw_runs.csv")
    verified, failures = verify_rows(phase_dir, rows, str(args.execution_commit))
    closure.write_csv(phase_dir / "verified_runs.csv", verified)
    closure.write_json(phase_dir / "verification_failures.json", failures)
    paired = performance_pairs(verified)
    scale_summary = performance_scale_summary(paired)
    mechanism_summary = mechanism_scale_summary(verified)
    closure.write_csv(phase_dir / "verified_paired_comparisons.csv", paired)
    closure.write_csv(phase_dir / "verified_per_instance_summary.csv", scale_summary)
    closure.write_csv(phase_dir / "mechanism_summary.csv", mechanism_summary)
    decision = decide(metadata, task_rows, rows, verified, failures, paired, scale_summary, mechanism_summary)
    closure.write_json(phase_dir / "decision.json", decision)
    write_report(phase_dir, decision, scale_summary, mechanism_summary)
    closure.write_hashes(phase_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["technical_contract_ok"] else 2


def verify_rows(
    phase_dir: Path,
    rows: list[dict[str, Any]],
    execution_commit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    bundle_cache: dict[str, Any] = {}
    seen: set[str] = set()
    for row in rows:
        run_id = str(row.get("run_id", ""))
        row_failures: list[str] = []
        if not run_id or run_id in seen:
            row_failures.append("missing or duplicate run_id")
        seen.add(run_id)
        instance_name = str(row.get("instance", ""))
        algorithm = str(row.get("algorithm", ""))
        seed = int(closure.as_float(row.get("seed"), -1))
        if instance_name not in EXPECTED_INSTANCES:
            row_failures.append(f"unexpected instance {instance_name}")
        if algorithm not in EXPECTED_ALGORITHMS:
            row_failures.append(f"unexpected algorithm {algorithm}")
        if seed not in {1, 2, 3}:
            row_failures.append(f"unexpected seed {seed}")
        if str(row.get("scenario_type")) != "formal_goeke80":
            row_failures.append("scenario is not formal_goeke80")
        if str(row.get("head")) != execution_commit:
            row_failures.append("row execution commit mismatch")
        if str(row.get("gate_status")) != "OK":
            row_failures.append(f"gate_status={row.get('gate_status')}")
        if int(closure.as_float(row.get("actual_evals"), -1)) != int(closure.as_float(row.get("eval_budget"), -2)):
            row_failures.append("evaluation budget not closed")
        if int(closure.as_float(row.get("violation_count"), -1)) != 0:
            row_failures.append("recorded violation count is not zero")

        solution_path = phase_dir / "solutions" / f"{run_id}.json"
        payload: dict[str, Any] = {}
        if not solution_path.is_file():
            row_failures.append("saved solution file missing")
        else:
            try:
                payload = json.loads(solution_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                row_failures.append(f"saved solution unreadable: {exc}")
        if not payload:
            failures.append({"run_id": run_id, "failures": row_failures or ["empty solution"]})
            continue

        if instance_name not in bundle_cache:
            bundle_cache[instance_name] = load_search_bundle(
                REPO_ROOT / "models/data_bundle/generated_instances/L-main" / instance_name
            )
        bundle = bundle_cache[instance_name]
        solution = solution_from_dict(payload)
        violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
        signature = solution_signature_hash(solution)
        if violations:
            row_failures.append(f"recomputed violations={len(violations)}")
        recorded_cost = closure.as_float(row.get("best_cost"), math.nan)
        recomputed_cost = float(metrics["total_cost"])
        if not math.isclose(recorded_cost, recomputed_cost, rel_tol=0.0, abs_tol=TOLERANCE):
            row_failures.append(f"cost mismatch recorded={recorded_cost} recomputed={recomputed_cost}")
        if str(row.get("best_signature")) != signature:
            row_failures.append("solution signature mismatch")
        composition = composition_metrics(solution, bundle)
        mechanism_signal = (
            sum(
                float(composition[key]) >= 0.10
                for key in ("ev_customer_share", "ev_demand_share", "ev_distance_share")
            )
            >= 2
            and int(composition["charging_action_count_audit"]) >= 2
            and float(composition["charging_energy_kwh_audit"]) > 0.0
        )
        verified.append(
            {
                "run_id": run_id,
                "instance": instance_name,
                "size": closure.instance_size(instance_name),
                "seed": seed,
                "algorithm": algorithm,
                "scenario_type": row.get("scenario_type"),
                "battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
                "execution_commit": row.get("head"),
                "eval_budget": int(closure.as_float(row.get("eval_budget"), -1)),
                "actual_evals": int(closure.as_float(row.get("actual_evals"), -1)),
                "recorded_cost": recorded_cost,
                "recomputed_cost": recomputed_cost,
                "cost_abs_diff": abs(recorded_cost - recomputed_cost),
                "recorded_signature": row.get("best_signature"),
                "recomputed_signature": signature,
                "recomputed_violation_count": len(violations),
                "solution_file": str(solution_path.relative_to(phase_dir)),
                "structural_ev_status": (
                    "STRUCTURAL_NO_EV_AVAILABLE"
                    if int(bundle.instance.num_ev) == 0
                    else "EV_AVAILABLE"
                ),
                "mechanism_signal": mechanism_signal if int(bundle.instance.num_ev) > 0 else False,
                **{key: metrics.get(key, "") for key in (
                    "cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ", "cost_transship", "cost_carbon",
                    "E_total", "E_cv_direct", "E_ev_indirect", "distance_total", "distance_cv", "distance_ev",
                    "fuel_liters", "electricity_kwh", "depot_charging_kwh", "station_charging_kwh",
                )},
                **composition,
                "verification_status": "OK" if not row_failures else "HALT",
                "verification_failures": " | ".join(row_failures),
            }
        )
        if row_failures:
            failures.append({"run_id": run_id, "failures": row_failures})
    return closure.sorted_rows(verified), {
        "schema": "setp-e2-80k-verification-failures.v1",
        "failure_count": len(failures),
        "failures": failures,
    }


def composition_metrics(solution: Any, bundle: Any) -> dict[str, Any]:
    cv_routes = [route for route in solution.routes if route.vehicle_type.lower() == "cv"]
    ev_routes = [route for route in solution.routes if route.vehicle_type.lower() == "ev"]
    cv_physical = {physical_vehicle_id(route.vehicle_id) for route in cv_routes}
    ev_physical = {physical_vehicle_id(route.vehicle_id) for route in ev_routes}
    trips = Counter(physical_vehicle_id(route.vehicle_id) for route in solution.routes)
    totals = {kind: {"customers": 0, "demand": 0.0, "distance": 0.0} for kind in ("cv", "ev")}
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    for route in solution.routes:
        kind = route.vehicle_type.lower()
        customers = route_customers(route, bundle.instance)
        totals[kind]["customers"] += len(customers)
        totals[kind]["demand"] += sum(
            float(node_lookup[customer_id].demand)
            for customer_id in customers
            if customer_id in node_lookup
        )
        totals[kind]["distance"] += float(route_distance(route, bundle.instance))
    total_customers = sum(float(value["customers"]) for value in totals.values())
    total_demand = sum(float(value["demand"]) for value in totals.values())
    total_distance = sum(float(value["distance"]) for value in totals.values())
    charge_energy = sum(float(action.energy_kwh) for action in solution.charging_actions)
    depot_energy = sum(
        float(action.energy_kwh)
        for action in solution.charging_actions
        if action.station_id in node_lookup and node_lookup[action.station_id].node_type.lower() == "d"
    )
    public_energy = charge_energy - depot_energy
    return {
        "route_count_audit": len(solution.routes),
        "cv_route_count_audit": len(cv_routes),
        "ev_route_count_audit": len(ev_routes),
        "ev_route_share": safe_div(len(ev_routes), len(solution.routes)),
        "cv_physical_vehicle_count": len(cv_physical),
        "ev_physical_vehicle_count": len(ev_physical),
        "total_physical_vehicle_count": len(cv_physical | ev_physical),
        "max_trips_per_physical_vehicle": max(trips.values()) if trips else 0,
        "reused_physical_vehicle_count": sum(value > 1 for value in trips.values()),
        "cv_customer_count": totals["cv"]["customers"],
        "ev_customer_count": totals["ev"]["customers"],
        "ev_customer_share": safe_div(totals["ev"]["customers"], total_customers),
        "cv_demand": totals["cv"]["demand"],
        "ev_demand": totals["ev"]["demand"],
        "ev_demand_share": safe_div(totals["ev"]["demand"], total_demand),
        "cv_distance_m": totals["cv"]["distance"],
        "ev_distance_m": totals["ev"]["distance"],
        "ev_distance_share": safe_div(totals["ev"]["distance"], total_distance),
        "charging_action_count_audit": len(solution.charging_actions),
        "charging_energy_kwh_audit": charge_energy,
        "depot_charging_energy_kwh_audit": depot_energy,
        "public_charging_energy_kwh_audit": public_energy,
    }


def performance_pairs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aware = {
        (str(row["instance"]), int(row["seed"])): row
        for row in rows
        if row.get("algorithm") == "staged_hybrid_carbon_aware" and row.get("verification_status") == "OK"
    }
    lns = {
        (str(row["instance"]), int(row["seed"])): row
        for row in rows
        if row.get("algorithm") == "LNS" and row.get("verification_status") == "OK"
    }
    out: list[dict[str, Any]] = []
    for key in sorted(set(aware) & set(lns)):
        left = aware[key]
        right = lns[key]
        left_cost = float(left["recomputed_cost"])
        right_cost = float(right["recomputed_cost"])
        gain = 100.0 * safe_div(right_cost - left_cost, right_cost)
        out.append(
            {
                "instance": key[0],
                "size": closure.instance_size(key[0]),
                "seed": key[1],
                "aware_cost": left_cost,
                "lns_cost": right_cost,
                "aware_gain_pct": gain,
                "outcome": "WIN" if gain > 1e-9 else "LOSS" if gain < -1e-9 else "TIE",
            }
        )
    return out


def performance_scale_summary(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        grouped[str(row["instance"])].append(row)
    out: list[dict[str, Any]] = []
    for instance in EXPECTED_INSTANCES:
        items = grouped.get(instance, [])
        gains = [float(row["aware_gain_pct"]) for row in items]
        out.append(
            {
                "instance": instance,
                "size": closure.instance_size(instance),
                "pairs": len(items),
                "mean_gain_pct": statistics.fmean(gains) if gains else math.nan,
                "median_gain_pct": statistics.median(gains) if gains else math.nan,
                "wins": sum(value > 1e-9 for value in gains),
                "ties": sum(abs(value) <= 1e-9 for value in gains),
                "losses": sum(value < -1e-9 for value in gains),
            }
        )
    return out


def mechanism_scale_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aware = [
        row
        for row in rows
        if row.get("algorithm") == "staged_hybrid_carbon_aware" and row.get("verification_status") == "OK"
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in aware:
        grouped[str(row["instance"])].append(row)
    out: list[dict[str, Any]] = []
    for instance in EXPECTED_INSTANCES:
        items = grouped.get(instance, [])
        structural_no_ev = bool(items) and all(row.get("structural_ev_status") == "STRUCTURAL_NO_EV_AVAILABLE" for row in items)
        signal_count = sum(bool(row.get("mechanism_signal")) for row in items)
        out.append(
            {
                "instance": instance,
                "size": closure.instance_size(instance),
                "rows": len(items),
                "structural_no_ev": structural_no_ev,
                "signal_seed_count": signal_count,
                "majority_seed_signal": False if structural_no_ev else signal_count >= 2,
                "mean_ev_customer_share": mean_field(items, "ev_customer_share"),
                "mean_ev_demand_share": mean_field(items, "ev_demand_share"),
                "mean_ev_distance_share": mean_field(items, "ev_distance_share"),
                "mean_charging_actions": mean_field(items, "charging_action_count_audit"),
                "mean_charging_energy_kwh": mean_field(items, "charging_energy_kwh_audit"),
            }
        )
    return out


def decide(
    metadata: dict[str, Any],
    task_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    verified: list[dict[str, Any]],
    failures: dict[str, Any],
    pairs: list[dict[str, Any]],
    scale_summary: list[dict[str, Any]],
    mechanism_summary: list[dict[str, Any]],
) -> dict[str, Any]:
    phase = str(metadata.get("phase", ""))
    preflight = phase == "preflight"
    expected_tasks = int(metadata.get("expected_tasks", 0))
    expected_rows = int(metadata.get("expected_evidence_rows", 0))
    expected_budget = int(metadata.get("eval_budget", 0))
    expected_per_evidence_algorithm = len(metadata.get("instances", [])) * len(metadata.get("seeds", []))
    exact_algorithm_counts = Counter(str(row.get("algorithm")) for row in raw_rows)
    technical_ok = (
        metadata.get("scenario_type") == "formal_goeke80"
        and float(metadata.get("battery_kwh", math.nan)) == 80.0
        and metadata.get("frozen_execution_commit") == FROZEN_COMMIT
        and len(task_rows) == expected_tasks
        and all(
            str(row.get("gate_status")) == "OK"
            and int(closure.as_float(row.get("actual_evals"), -1)) == expected_budget
            and int(closure.as_float(row.get("violation_count"), -1)) == 0
            and str(row.get("head")) == FROZEN_COMMIT
            for row in task_rows
        )
        and len(raw_rows) == expected_rows
        and len(verified) == expected_rows
        and int(failures.get("failure_count", -1)) == 0
        and all(row.get("verification_status") == "OK" for row in verified)
        and exact_algorithm_counts == Counter(
            {algorithm: expected_per_evidence_algorithm for algorithm in EXPECTED_ALGORITHMS}
        )
        and len(pairs) == expected_per_evidence_algorithm
    )
    gains = [float(row["aware_gain_pct"]) for row in pairs]
    overall_mean = statistics.fmean(gains) if gains else math.nan
    overall_median = statistics.median(gains) if gains else math.nan
    wins = sum(value > 1e-9 for value in gains)
    ties = sum(abs(value) <= 1e-9 for value in gains)
    losses = sum(value < -1e-9 for value in gains)
    scale_means = [float(row["mean_gain_pct"]) for row in scale_summary if int(row["pairs"]) == 3]
    nonlosing_scales = sum(value >= -1e-9 for value in scale_means)
    worst_scale = min(scale_means) if scale_means else math.nan
    algorithm_supported = (
        not preflight
        and technical_ok
        and overall_mean >= -1e-9
        and overall_median >= -1e-9
        and nonlosing_scales >= 3
        and worst_scale >= -2.0 - 1e-9
        and wins >= losses
    )
    eligible_mechanism = [
        row
        for row in mechanism_summary
        if int(row["size"]) in {50, 100, 200}
        and int(row["rows"]) == 3
        and not bool(row["structural_no_ev"])
    ]
    signal_scales = sum(bool(row["majority_seed_signal"]) for row in eligible_mechanism)
    mechanism_visible = not preflight and technical_ok and len(eligible_mechanism) == 3 and signal_scales >= 2
    if preflight and technical_ok:
        verdict = "E2_80K_PREFLIGHT_VERIFIED"
        next_action = "commit the runner and verifier, then start the preregistered 24-task formal gate"
    elif not technical_ok:
        verdict = "HALT_E2_80K_VERIFICATION"
        next_action = "repair collection/verification only; do not interpret performance"
    elif algorithm_supported and mechanism_visible:
        verdict = "E2_80K_ROBUSTNESS_AND_MECHANISM_SUPPORTED"
        next_action = "80 kWh may advance to a bounded nine-scale robustness expansion"
    elif algorithm_supported:
        verdict = "E2_80K_ALGORITHM_ROBUST_MECHANISM_WEAK"
        next_action = "stop expansion; report 80 kWh as an algorithm-robust but carbon-mechanism-weak boundary"
    elif mechanism_visible:
        verdict = "E2_80K_MECHANISM_VISIBLE_ALGORITHM_NOT_ROBUST"
        next_action = "stop expansion and retain 80 kWh as a sensitivity result"
    else:
        verdict = "E2_80K_ORIGINAL_BOUNDARY_ONLY"
        next_action = "stop expansion; retain 80 kWh only as the original physical boundary"
    return {
        "schema": "setp-e2-80k-robustness-decision.v1",
        "verdict": verdict,
        "phase": phase,
        "technical_contract_ok": technical_ok,
        "algorithm_stability_supported": algorithm_supported,
        "mechanism_visibility_supported": mechanism_visible,
        "expected_search_tasks": expected_tasks,
        "observed_search_tasks": len(task_rows),
        "expected_evidence_rows": expected_rows,
        "observed_evidence_rows": len(raw_rows),
        "verified_evidence_rows": len(verified),
        "verification_failure_count": failures.get("failure_count"),
        "execution_commit": FROZEN_COMMIT,
        "battery_kwh": 80.0,
        "paired_mean_gain_pct": overall_mean,
        "paired_median_gain_pct": overall_median,
        "paired_wins_ties_losses": [wins, ties, losses],
        "nonlosing_scale_count": nonlosing_scales,
        "worst_scale_mean_gain_pct": worst_scale,
        "mechanism_signal_scale_count_excluding_15c": signal_scales,
        "mechanism_eligible_scale_count": len(eligible_mechanism),
        "fifteen_customer_mechanism_status": (
            "STRUCTURAL_NO_EV_AVAILABLE" if "L-main-threeshift-15c-01" in metadata.get("instances", []) else "NOT_IN_PHASE"
        ),
        "preregistered_algorithm_gate": {
            "paired_mean_nonnegative": overall_mean >= -1e-9 if gains else False,
            "paired_median_nonnegative": overall_median >= -1e-9 if gains else False,
            "at_least_three_of_four_scale_means_nonnegative": nonlosing_scales >= 3,
            "no_scale_mean_below_minus_2pct": worst_scale >= -2.0 - 1e-9 if scale_means else False,
            "wins_not_less_than_losses": wins >= losses,
        },
        "preregistered_mechanism_gate": {
            "definition": "majority of seeds have >=10% EV share in at least two of customer/demand/distance, >=2 charges, and positive charging energy",
            "required_signal_scales_excluding_15c": 2,
            "observed_signal_scales_excluding_15c": signal_scales,
        },
        "next_action": next_action,
    }


def write_report(
    phase_dir: Path,
    decision: dict[str, Any],
    scale_summary: list[dict[str, Any]],
    mechanism_summary: list[dict[str, Any]],
) -> None:
    if decision.get("phase") == "preflight" and decision["technical_contract_ok"]:
        plain = "接线短门已独立复算通过；这一步只证明入口、预算和解文件正确，不判断算法输赢。"
    elif not decision["technical_contract_ok"]:
        plain = "技术验收没有通过，当前结果不能解释，也不能继续扩跑。"
    elif decision["algorithm_stability_supported"] and decision["mechanism_visibility_supported"]:
        plain = "80 kWh下算法表现和电车/充电机制都过门，可以考虑有界扩展。"
    elif decision["algorithm_stability_supported"]:
        plain = "80 kWh下算法还算稳，但电车和充电太弱，不适合承担时变碳正面故事。"
    elif decision["mechanism_visibility_supported"]:
        plain = "80 kWh仍能看到电车和充电，但算法相对LNS不够稳，只能作为敏感性结果。"
    else:
        plain = "80 kWh既没有证明算法稳健，也没有形成足够的电车充电机制，只保留为原始参数边界。"
    lines = [
        "# E2 80 kWh稳健性镜像门",
        "",
        f"判决：`{decision['verdict']}`",
        "",
        f"人话：{plain}",
        "",
        (
            f"12组正式候选/LNS配对：平均优势{fmt(decision['paired_mean_gain_pct'])}% ，"
            f"中位优势{fmt(decision['paired_median_gain_pct'])}% ，"
            f"胜/平/负={decision['paired_wins_ties_losses']}."
        ),
        "",
        "## 各规模算法表现",
        "",
        "| 规模 | 配对 | 平均优势% | 中位优势% | 胜/平/负 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in scale_summary:
        lines.append(
            f"| {row['size']}c | {row['pairs']} | {fmt(row['mean_gain_pct'])} | {fmt(row['median_gain_pct'])} | "
            f"{row['wins']}/{row['ties']}/{row['losses']} |"
        )
    lines.extend(
        [
            "",
            "## 电车与充电机制",
            "",
            "15c实例结构上没有EV，只参加算法性能比较，不参加机制判决。",
            "",
            "| 规模 | EV客户/需求/距离均值 | 平均充电次数 | 平均充电量kWh | 多数种子有信号 |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in mechanism_summary:
        lines.append(
            f"| {row['size']}c | {fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])} | "
            f"{fmt(row['mean_charging_actions'])} | {fmt(row['mean_charging_energy_kwh'])} | "
            f"{'不适用' if row['structural_no_ev'] else ('是' if row['majority_seed_signal'] else '否')} |"
        )
    lines.extend(["", f"下一步：{decision['next_action']}。"])
    (phase_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def mean_field(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows if row.get(field) not in {"", None}]
    return statistics.fmean(values) if values else math.nan


def safe_div(numerator: Any, denominator: Any) -> float:
    value = float(denominator)
    return float(numerator) / value if abs(value) > 1e-12 else 0.0


def fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return "NA" if not math.isfinite(number) else f"{number:.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
