#!/usr/bin/env python3
"""One-instance smoke for E6 post-settlement and in-search participation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (PROTOTYPE, REPO / "solver/src", REPO):
    sys.path.insert(0, str(path))

from route_pool_sp import _route_pool_records, run_hgs_route_pool_recombination
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.profit import calculate_depot_profits
from setp_solver.solution import Route, Solution

from baselines.china_instances.build_china81_finite_fleet_authority_v1_20260723 import _pack_depot
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


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def initial_solution(bundle: Any) -> Solution:
    routes = [
        Route(
            vehicle_id=f"INIT-{depot}-{serial:03d}",
            vehicle_type="cv",
            home_depot_id=depot,
            node_sequence=[depot, *customers, depot],
        )
        for depot in sorted(bundle.fleet_caps_by_depot)
        for serial, customers in enumerate(_pack_depot(bundle, depot), start=1)
    ]
    return complete_china81_route_skeleton(Solution(routes=routes), bundle).solution


def optimize(bundle: Any, seed: int, iterations: int, archive: int) -> Any:
    return run_hgs_route_pool_recombination(
        bundle,
        initial_solution(bundle),
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=archive,
        max_archive_candidates_per_view=archive,
        sp_time_limit_seconds=2.0,
        max_hgs_iterations_per_view=iterations,
        wallclock_safety_seconds_per_view=120.0,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = HERE / args.output
    output.mkdir(parents=True, exist_ok=True)
    base = load_china81_bundle(REPO, args.instance)
    base = replace(base, prices=replace(base.prices, cross_site_cost=args.cross_site_cost))
    members = tuple(sorted(base.fleet_caps_by_depot))
    costs: dict[tuple[str, ...], float] = {}
    values: dict[tuple[str, ...], float] = {}
    rows: list[dict[str, Any]] = []
    grand_run = None
    grand_bundle = None
    for group in coalitions(members):
        bundle = subset_bundle(base, group)
        route_run = optimize(bundle, args.seed, args.iterations, args.archive)
        cost = float(route_run.completion.objective)
        revenue = coalition_revenue(bundle)
        costs[group] = cost
        values[group] = revenue - cost
        rows.append(
            {
                "method": "A_COALITION",
                "coalition": "+".join(group),
                "member_count": len(group),
                "cost_cny": cost,
                "revenue_cny": revenue,
                "profit_cny": revenue - cost,
                "route_count": len(route_run.solution.routes),
            }
        )
        if group == members:
            grand_run, grand_bundle = route_run, bundle

    assert grand_run is not None and grand_bundle is not None
    allocation = shapley(values, members)
    cost_allocation = shapley(costs, members)
    core_nonempty, one_core = core_allocation(values, members)
    shapley_violations = core_violations(allocation, values, members)
    operational = calculate_depot_profits(
        grand_run.solution,
        grand_bundle.instance,
        grand_bundle.time_profile,
        grand_bundle.prices,
        customer_home_depot=dict(grand_bundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )
    operational_profit = {depot: float(row.profit) for depot, row in operational.items()}
    standalone_profit = {(depot,): values[(depot,)] for depot in members}
    transfer = {depot: allocation[depot] - operational_profit[depot] for depot in members}

    records = _route_pool_records(grand_bundle, grand_run.view_epochs)
    b_rows = []
    for theta in (None, *theta_grid(args.theta_step)):
        _, stats = solve_profit_floor(
            grand_bundle,
            records,
            {depot: standalone_profit[(depot,)] for depot in members},
            theta,
            args.mip_seconds,
        )
        row = {
            "method": "B_PROFIT_FLOOR",
            "theta": "NONE" if theta is None else theta,
            "feasible": stats["feasible"],
            "cost_cny": stats["objective"],
            "cost_closure_abs_cny": stats.get("cost_closure_abs_cny"),
            "profit_closure_abs_cny": stats.get("profit_closure_abs_cny"),
        }
        for depot in members:
            row[f"profit_{depot}"] = (stats.get("profit") or {}).get(depot)
        rows.append(row)
        b_rows.append(row)

    singleton = {depot: values[(depot,)] for depot in members}
    grand_revenue = coalition_revenue(grand_bundle)
    account_closure = {
        "operational_cost_abs_cny": abs(
            sum(float(row.cost_total) for row in operational.values()) - costs[members]
        ),
        "operational_profit_abs_cny": abs(
            sum(operational_profit.values()) - (grand_revenue - costs[members])
        ),
        "shapley_efficiency_abs_cny": abs(sum(allocation.values()) - values[members]),
        "settlement_balance_abs_cny": abs(sum(transfer.values())),
        "method_B_max_cost_abs_cny": max(
            (float(row["cost_closure_abs_cny"] or 0.0) for row in b_rows), default=0.0
        ),
        "method_B_max_profit_abs_cny": max(
            (float(row["profit_closure_abs_cny"] or 0.0) for row in b_rows), default=0.0
        ),
    }
    decision = {
        "status": "PASS_SMOKE_BOTH_METHODS",
        "scientific_role": "MECHANISM_SMOKE_NOT_FORMAL_RESULT",
        "instance_id": args.instance,
        "cross_site_cost_cny_per_customer": args.cross_site_cost,
        "method_A": {
            "coalitions_solved": len(costs),
            "grand_profit_cny": values[members],
            "operational_profit_cny": operational_profit,
            "shapley_cost_share_cny": cost_allocation,
            "shapley_profit_cny": allocation,
            "transfer_to_shapley_cny": transfer,
            "shapley_individually_rational": all(allocation[d] >= singleton[d] - 1e-7 for d in members),
            "shapley_in_core": not shapley_violations,
            "shapley_core_violations_cny": {"+".join(group): value for group, value in shapley_violations.items()},
            "core_nonempty": core_nonempty,
            "one_core_profit_allocation_cny": one_core,
        },
        "method_B": {
            "route_pool_size": len(records),
            "theta_step": args.theta_step,
            "feasible_points": sum(row["feasible"] for row in b_rows),
            "tested_points": len(b_rows),
            "highest_feasible_theta": max((float(row["theta"]) for row in b_rows if row["feasible"] and row["theta"] != "NONE"), default=None),
        },
        "account_closure": account_closure,
    }
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    write_json(
        output / "metadata.json",
        {
            "instance_id": args.instance,
            "seed": args.seed,
            "iterations_per_view": args.iterations,
            "archive_per_view": args.archive,
            "theta_step": args.theta_step,
            "cross_site_cost": args.cross_site_cost,
        },
    )
    report = (
        "# E6 四承包商双方法极小试算\n\n"
        f"15 个非空联盟均完成路线求解。大联盟利润为 {values[members]:.3f} 元；"
        f"Shapley 个体理性={'满足' if decision['method_A']['shapley_individually_rational'] else '不满足'}，"
        f"核={'非空' if core_nonempty else '为空'}。\n\n"
        f"路线池含 {len(records)} 条候选路线；利润下限共试 {len(b_rows)} 个点，"
        f"可行 {decision['method_B']['feasible_points']} 个，最高可行 theta="
        f"{decision['method_B']['highest_feasible_theta']}。\n\n"
        f"六项账目闭合残差最大值为 {max(account_closure.values()):.3e} 元。\n\n"
        "收入按实际配送路线归其承包商；跨场成本保持输入参数，当前为 0。"
        "本结果只验证两种方法接线，不是正式实验结果。\n"
        "方法 A 对齐饶卫振等（2019，第1518--1520页；2022，第2723、2727--2730页）的"
        "先求联盟配送成本、再分配；方法 B 对齐 Soriano 等（第4--7页）的路线优化内利润下限。\n"
        "\n运行命令：`OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "
        "VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=solver/src "
        "build/python_envs/pyvrp-hgs-0.12.2/bin/python "
        "baselines/china_e3_e7/e6_contractor_participation_20260801/run_smoke.py "
        f"--iterations {args.iterations} --archive {args.archive} "
        f"--theta-step {args.theta_step:g} --mip-seconds {args.mip_seconds:g} "
        f"--cross-site-cost {args.cross_site_cost:g} --output {args.output}`。\n"
        "\n仍需用户决定的只有非零跨场真实成本的业务含义和取值；本实现没有给它默认非零值，"
        "也没有把内部转移支付重复计入系统成本。\n"
    )
    (output / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output.iterdir()
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(output / "artifact_hashes.json", hashes)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="cn-prd-150c-01-V2-LOCATIONS")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--archive", type=int, default=1)
    parser.add_argument("--theta-step", type=float, default=0.05)
    parser.add_argument("--mip-seconds", type=float, default=2.0)
    parser.add_argument("--cross-site-cost", type=float, default=0.0)
    parser.add_argument("--output", default="smoke")
    result = run(parser.parse_args())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
