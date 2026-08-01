#!/usr/bin/env python3
"""E6 C2 screen on the E3 capacity-rank-aligned ownership mapping."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from e6_methods import (
    coalition_revenue,
    coalitions,
    core_allocation,
    core_violations,
    shapley,
    solve_profit_floor,
    subset_bundle,
    theta_grid,
)
from route_pool_sp import _route_pool_records
from run_smoke import optimize
from setp_solver.china81_completion import exact_china81_score
from setp_solver.profit import calculate_depot_profits

from baselines.china_e3_e7.e3_scattered_ownership_20260801 import (
    run_e3_capacity_rank_aligned as e3,
)

INSTANCE = e3.INSTANCE
SEED = 1
ITERATIONS = 10
ARCHIVE = 2
MIP_SECONDS = 2.0
OUTPUT = HERE / "pilot04_rank_aligned_direct_screen_20260801"
E3_RESULT = e3.OUTPUT / "raw_runs.csv"
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(
    path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None
) -> None:
    fieldnames = fields or list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_input() -> tuple[Any, dict[str, Any]]:
    bundle, info = e3.prepare(INSTANCE)
    bundle = replace(bundle, prices=replace(bundle.prices, cross_site_cost=0.0))
    with E3_RESULT.open(encoding="utf-8", newline="") as handle:
        expected = next(csv.DictReader(handle))["mapping_sha256"]
    if info["mapping_sha256"] != expected:
        raise ValueError("E6 mapping differs from the completed E3-02 pilot")
    return bundle, info


def quick_groups(members: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple((member,) for member in members) + (members,)


def solve_group(
    base: Any, group: tuple[str, ...], mapping_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = subset_bundle(base, group)
    result = optimize(bundle, SEED, ITERATIONS, ARCHIVE)
    cost, breakdown, violations = exact_china81_score(result.solution, bundle)
    if violations or not math.isclose(cost, result.completion.objective, abs_tol=1e-6):
        raise RuntimeError(f"complete-model check failed: violations={len(violations)}")
    revenue = coalition_revenue(bundle)
    row = {
        "record_type": "COALITION",
        "instance_id": INSTANCE,
        "seed": SEED,
        "mapping_sha256": mapping_sha256,
        "business_scenario": "DIRECT_SERVICE_RIGHT",
        "coalition": "+".join(group),
        "coalition_member_count": len(group),
        "theta": "",
        "contractor": "",
        "status": "PASS",
        "search_evaluations": result.stats["complete_candidate_evaluation_attempts"],
        "used_cv": int(breakdown["n_veh_cv"]),
        "used_ev": int(breakdown["n_veh_ev"]),
        "cost_cny": cost,
        "revenue_cny": revenue,
        "profit_cny": revenue - cost,
        "distance_km": float(breakdown["distance_total"]) / 1000.0,
        "emissions_kg": float(breakdown["E_total"]),
        "cross_contractor_customers": len(result.solution.cross_site_services),
        "standalone_profit_cny": "",
        "natural_profit_cny": "",
        "difference_from_standalone_cny": "",
        "shapley_profit_cny": "",
        "settlement_cny": "",
        "individually_rational": "",
        "feasible": True,
        "profit_by_contractor": "",
        "solution_sha256": e3.base.solution_sha256(result.solution),
        "status_reason": "",
    }
    return row, {
        "bundle": bundle,
        "run": result,
        "cost": cost,
        "revenue": revenue,
        "profit": revenue - cost,
    }


def transfer_rows(bundle: Any, solution: Any) -> list[dict[str, Any]]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    observed: dict[tuple[str, str], list[float]] = {}
    for route in solution.routes:
        serving = route.home_depot_id
        for customer in route.node_sequence:
            if customer not in bundle.customer_home_depot:
                continue
            owner = bundle.customer_home_depot[customer]
            if owner != serving:
                row = observed.setdefault((owner, serving), [0.0, 0.0])
                row[0] += float(nodes[customer].demand)
                row[1] += 1
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    return [
        {
            "original_owner": owner,
            "actual_service_depot": serving,
            "quantity_kg": observed.get((owner, serving), [0.0, 0.0])[0],
            "customer_count": int(observed.get((owner, serving), [0.0, 0.0])[1]),
            "directed_road_distance_km": bundle.instance.distance(owner, serving)
            / 1000.0,
        }
        for owner in depots
        for serving in depots
        if owner != serving
    ]


def _not_run_row(
    group: tuple[str, ...], mapping_sha256: str, reason: str
) -> dict[str, Any]:
    return {
        "record_type": "COALITION",
        "instance_id": INSTANCE,
        "seed": SEED,
        "mapping_sha256": mapping_sha256,
        "business_scenario": "DIRECT_SERVICE_RIGHT",
        "coalition": "+".join(group),
        "coalition_member_count": len(group),
        "status": "NOT_RUN_AFTER_HALT",
        "feasible": "",
        "status_reason": reason,
    }


def report_text(decision: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# E6 rank-aligned direct-service screen",
        "",
        f"技术状态：{decision['status']}。",
        "",
        "本轮完全复用 E3-02 的客户归属：标签 0/1/2/3 分别对应深圳、广州、东莞、佛山。",
        "客户、需求、时窗以及各车场 CV/EV 上限未变；收入归实际配送车场，运营成本归实际车辆所属车场，跨场系统费用为 0。",
        "",
    ]
    if decision["status"] != "PASS_E6_C2_DIRECT_SCREEN":
        lines.extend([f"停止原因：{decision['failure']}", ""])
        return "\n".join(lines)

    method_a = decision["method_A"]
    diagnostic = decision["grand_coalition_diagnostic"]
    lines.extend(
        [
            f"科学候选结论：{decision['scientific_status']}。",
            "",
            "15 个非空联盟均得到合法路线，这只说明技术上能算。",
            (
                f"无约束大联盟的跨承包商客户数为 "
                f"{diagnostic['cross_contractor_customers']}，转移货量为 "
                f"{diagnostic['cross_contractor_quantity_kg']:.3f} kg。"
            ),
            (
                f"四家单干成本合计 {diagnostic['standalone_cost_sum_cny']:.3f} 元，"
                f"大联盟成本 {diagnostic['grand_cost_cny']:.3f} 元，"
                f"多 {diagnostic['grand_minus_standalone_cost_cny']:.3f} 元"
                f"（{diagnostic['grand_cost_increase_percent']:.3f}%）。"
            ),
            (
                f"四家单干利润合计 {diagnostic['standalone_profit_sum_cny']:.3f} 元，"
                f"大联盟利润 {diagnostic['grand_profit_cny']:.3f} 元，"
                f"少 {abs(diagnostic['grand_minus_standalone_profit_cny']):.3f} 元。"
            ),
            f"大联盟自然经营中有 {method_a['members_below_standalone']} 家低于单干。",
            "",
            "| 承包商 | 单干利润/元 | 自然经营利润/元 | 相对单干差额/元 | Shapley利润/元 | 结算额/元 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for depot in decision["members"]:
        lines.append(
            f"| {depot} | {method_a['standalone_profit_cny'][depot]:.3f} | "
            f"{method_a['natural_profit_cny'][depot]:.3f} | "
            f"{method_a['natural_minus_standalone_cny'][depot]:.3f} | "
            f"{method_a['shapley_profit_cny'][depot]:.3f} | "
            f"{method_a['settlement_cny'][depot]:.3f} |"
        )
    method_b = decision["method_B"]
    lines.extend(
        [
            "",
            (
                f"Shapley 个体理性={'是' if method_a['shapley_individually_rational'] else '否'}；"
                f"核={'非空' if method_a['core_nonempty'] else '为空'}。"
            ),
            f"方法 B 完整保留 0.00--1.00 的 21 个利润底线点，其中 {method_b['feasible_points']} 个可行，最高可行值为 {method_b['highest_feasible_theta']}。",
            "Shapley 和利润底线结果留作诊断，本轮未产生合作效应。",
            "",
            "`transfer_quantity_by_pair.csv` 仅记录大联盟中跨承包商服务的货量、客户数和车场间有向道路距离；没有计算转运费。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(output: Path, quick_status: Path | None = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    base, info = load_input()
    members = tuple(sorted(base.fleet_caps_by_depot))
    quick = quick_groups(members)
    all_groups = coalitions(members)
    rows: list[dict[str, Any]] = []
    solved: dict[tuple[str, ...], dict[str, Any]] = {}
    failure = ""

    for index, group in enumerate(quick):
        try:
            row, result = solve_group(base, group, info["mapping_sha256"])
        except Exception as exc:  # noqa: BLE001 - preserve the failed coalition
            failure = f"{'+'.join(group)}: {type(exc).__name__}: {exc}"
            row = _not_run_row(group, info["mapping_sha256"], failure)
            row["status"] = "HALT_INVALID_QUICK_COALITION"
        rows.append(row)
        if failure:
            rows.extend(
                _not_run_row(item, info["mapping_sha256"], failure)
                for item in quick[index + 1 :]
            )
            break
        solved[group] = result

    quick_payload = {
        "status": "PASS_FIVE_QUICK_COALITIONS"
        if not failure
        else "HALT_FIVE_QUICK_COALITIONS",
        "solved": ["+".join(group) for group in solved],
        "failure": failure,
    }
    if quick_status is not None:
        write_json(quick_status, quick_payload)

    if not failure:
        for group in (item for item in all_groups if item not in solved):
            try:
                row, result = solve_group(base, group, info["mapping_sha256"])
            except Exception as exc:  # noqa: BLE001 - preserve the failed coalition
                failure = f"{'+'.join(group)}: {type(exc).__name__}: {exc}"
                row = _not_run_row(group, info["mapping_sha256"], failure)
                row["status"] = "HALT_INVALID_COALITION"
            rows.append(row)
            if failure:
                remaining = [
                    item for item in all_groups if item not in solved and item != group
                ]
                rows.extend(
                    _not_run_row(item, info["mapping_sha256"], failure)
                    for item in remaining
                )
                break
            solved[group] = result

    transfer: list[dict[str, Any]] = []
    decision: dict[str, Any] = {
        "status": "HALT_E6_C2_DIRECT_SCREEN" if failure else "PASS_E6_C2_DIRECT_SCREEN",
        "candidate_screen_only": True,
        "formal_story": "AWAITING_USER_DECISION",
        "instance_id": INSTANCE,
        "seed": SEED,
        "members": list(members),
        "mapping_sha256": info["mapping_sha256"],
        "quick_check": quick_payload,
        "coalitions_solved": len(solved),
        "failure": failure,
    }

    if not failure:
        values = {group: result["profit"] for group, result in solved.items()}
        grand = solved[members]
        ledger = calculate_depot_profits(
            grand["run"].solution,
            grand["bundle"].instance,
            grand["bundle"].time_profile,
            grand["bundle"].prices,
            customer_home_depot=dict(grand["bundle"].customer_home_depot),
            carbon_quota_kg=0.0,
        )
        standalone = {depot: values[(depot,)] for depot in members}
        natural = {depot: float(ledger[depot].profit) for depot in members}
        differences = {depot: natural[depot] - standalone[depot] for depot in members}
        allocation = shapley(values, members)
        settlement = {depot: allocation[depot] - natural[depot] for depot in members}
        core_nonempty, core_witness = core_allocation(values, members)
        shapley_core_gaps = core_violations(allocation, values, members)
        for depot in members:
            common = {
                "instance_id": INSTANCE,
                "seed": SEED,
                "mapping_sha256": info["mapping_sha256"],
                "business_scenario": "DIRECT_SERVICE_RIGHT",
                "coalition": "+".join(members),
                "coalition_member_count": 4,
                "contractor": depot,
                "status": "PASS",
                "feasible": True,
            }
            rows.append(
                {
                    **common,
                    "record_type": "NATURAL_OPERATION",
                    "standalone_profit_cny": standalone[depot],
                    "natural_profit_cny": natural[depot],
                    "difference_from_standalone_cny": differences[depot],
                }
            )
            rows.append(
                {
                    **common,
                    "record_type": "METHOD_A_SHAPLEY",
                    "standalone_profit_cny": standalone[depot],
                    "natural_profit_cny": natural[depot],
                    "shapley_profit_cny": allocation[depot],
                    "settlement_cny": settlement[depot],
                    "individually_rational": allocation[depot]
                    >= standalone[depot] - 1e-7,
                }
            )

        records = _route_pool_records(grand["bundle"], grand["run"].view_epochs)
        theta_rows = []
        for theta in theta_grid(0.05):
            solution, stats = solve_profit_floor(
                grand["bundle"], records, standalone, theta, MIP_SECONDS
            )
            row = {
                "record_type": "METHOD_B_PROFIT_FLOOR",
                "instance_id": INSTANCE,
                "seed": SEED,
                "mapping_sha256": info["mapping_sha256"],
                "business_scenario": "DIRECT_SERVICE_RIGHT",
                "coalition": "+".join(members),
                "coalition_member_count": 4,
                "theta": theta,
                "contractor": "",
                "status": "PASS_FEASIBLE" if stats["feasible"] else "INFEASIBLE",
                "feasible": stats["feasible"],
                "cost_cny": stats["objective"] if stats["feasible"] else "",
                "profit_by_contractor": json.dumps(
                    stats.get("profit") or {}, sort_keys=True
                ),
                "solution_sha256": ""
                if solution is None
                else e3.base.solution_sha256(solution),
                "status_reason": "" if stats["feasible"] else stats["message"],
            }
            rows.append(row)
            theta_rows.append(row)

        transfer = transfer_rows(grand["bundle"], grand["run"].solution)
        standalone_cost_sum = sum(solved[(depot,)]["cost"] for depot in members)
        standalone_profit_sum = sum(standalone.values())
        transferred_quantity = sum(float(row["quantity_kg"]) for row in transfer)
        transferred_customers = sum(int(row["customer_count"]) for row in transfer)
        closure = {
            "natural_cost_abs_cny": abs(
                sum(float(item.cost_total) for item in ledger.values()) - grand["cost"]
            ),
            "natural_profit_abs_cny": abs(
                sum(natural.values()) - (grand["revenue"] - grand["cost"])
            ),
            "shapley_efficiency_abs_cny": abs(
                sum(allocation.values()) - values[members]
            ),
            "settlement_balance_abs_cny": abs(sum(settlement.values())),
        }
        decision.update(
            scientific_candidate_success=False,
            scientific_status=(
                "HALT_NO_CROSS_CONTRACTOR_ACTION_AND_DOMINATED_GRAND_COALITION"
            ),
            grand_coalition_diagnostic={
                "cross_contractor_customers": transferred_customers,
                "cross_contractor_quantity_kg": transferred_quantity,
                "standalone_cost_sum_cny": standalone_cost_sum,
                "grand_cost_cny": grand["cost"],
                "grand_minus_standalone_cost_cny": grand["cost"]
                - standalone_cost_sum,
                "grand_cost_increase_percent": 100.0
                * (grand["cost"] / standalone_cost_sum - 1.0),
                "standalone_profit_sum_cny": standalone_profit_sum,
                "grand_profit_cny": grand["profit"],
                "grand_minus_standalone_profit_cny": grand["profit"]
                - standalone_profit_sum,
            },
            method_A={
                "standalone_profit_cny": standalone,
                "natural_profit_cny": natural,
                "natural_minus_standalone_cny": differences,
                "members_below_standalone": sum(
                    value < -1e-7 for value in differences.values()
                ),
                "shapley_profit_cny": allocation,
                "settlement_cny": settlement,
                "shapley_individually_rational": all(
                    allocation[depot] >= standalone[depot] - 1e-7 for depot in members
                ),
                "shapley_in_core": not shapley_core_gaps,
                "shapley_core_violations_cny": {
                    "+".join(group): value for group, value in shapley_core_gaps.items()
                },
                "core_nonempty": core_nonempty,
                "one_core_profit_allocation_cny": core_witness,
            },
            method_B={
                "route_pool_size": len(records),
                "theta_values": list(theta_grid(0.05)),
                "feasible_points": sum(bool(row["feasible"]) for row in theta_rows),
                "highest_feasible_theta": max(
                    (float(row["theta"]) for row in theta_rows if row["feasible"]),
                    default=None,
                ),
            },
            account_closure=closure,
        )

    metadata = {
        "schema": "resetp.e6-rank-aligned-direct-screen.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": INSTANCE,
        "seed": SEED,
        "iterations_per_view": ITERATIONS,
        "archive_candidates_per_view": ARCHIVE,
        "mip_seconds_per_theta": MIP_SECONDS,
        "mapping_rule": e3.FAMILY,
        "mapping_sha256": info["mapping_sha256"],
        "label_to_depot": info["label_to_depot"],
        "fleet_caps_by_depot": {
            depot: dict(base.fleet_caps_by_depot[depot]) for depot in members
        },
        "business_scenario": {
            "service_right": "revenue follows actual serving depot",
            "operating_cost": "charged to the actual route home depot",
            "cross_site_system_cost_cny": 0.0,
        },
        "source_hashes": {
            str(path.relative_to(REPO)): sha256(path)
            for path in (
                Path(__file__),
                HERE / "e6_methods.py",
                HERE / "run_smoke.py",
                Path(e3.__file__),
                E3_RESULT,
                *PROTECTED,
            )
        },
    }
    write_json(output / "metadata.json", metadata)
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    write_csv(
        output / "transfer_quantity_by_pair.csv",
        transfer,
        [
            "original_owner",
            "actual_service_depot",
            "quantity_kg",
            "customer_count",
            "directed_road_distance_km",
        ],
    )
    (output / "report.md").write_text(report_text(decision, rows), encoding="utf-8")
    write_json(
        output / "artifact_hashes.json",
        {
            name: sha256(output / name)
            for name in (
                "metadata.json",
                "raw_runs.csv",
                "decision.json",
                "transfer_quantity_by_pair.csv",
                "report.md",
            )
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--quick-status", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.output, args.quick_status), ensure_ascii=False, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
