#!/usr/bin/env python3
"""Build the formal pre-settlement ledger from frozen E6 grand solutions."""

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

from baselines.china_e3_e7.e3_scattered_ownership_20260801 import (
    run_e3_capacity_rank_aligned as e3,
)
from setp_solver.profit import calculate_depot_profits
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

SOURCE = HERE / "formal_e6a_panel_20260801"
OUTPUT = HERE / "formal_e6_serving_revenue_ledger_20260801"
ASSIGNMENT = "REVENUE_TO_SERVING_CONTRACTOR"
TOL = 1.0e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[ChargingAction(**row) for row in payload["charging_actions"]],
        cross_site_services=[
            CrossSiteService(**row) for row in payload["cross_site_services"]
        ],
    )


def assert_close(left: float, right: float, label: str) -> float:
    gap = left - right
    if not math.isclose(left, right, rel_tol=0.0, abs_tol=TOL):
        raise RuntimeError(f"{label} does not close: {left} != {right}")
    return gap


def registered_input(unit: Path, relative: str) -> str:
    manifest = read_json(unit / "artifact_hashes.json")["artifacts"]
    expected = manifest.get(relative)
    if expected is None:
        raise RuntimeError(f"{unit}: input is not registered: {relative}")
    observed = sha256(unit / relative)
    if observed != expected:
        raise RuntimeError(f"{unit}: registered input hash differs: {relative}")
    return observed


def derive(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    unit_dirs = sorted(path.parent for path in source.glob("units/*/seed_*/metadata.json"))
    if len(unit_dirs) != 60:
        raise RuntimeError(f"expected 60 formal units, found {len(unit_dirs)}")

    member_rows: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    input_hashes: dict[str, dict[str, str]] = {}
    formal_source_hashes: dict[str, str] | None = None
    bundles: dict[str, Any] = {}

    for unit in unit_dirs:
        try:
            metadata = read_json(unit / "metadata.json")
            instance_id = str(metadata["instance_id"])
            seed = int(metadata["seed"])
            if metadata["evidence_role"] != "FORMAL_PANEL_UNIT":
                raise RuntimeError("input is not a formal E6-A unit")
            if metadata["revenue_assignment"] != ASSIGNMENT:
                raise RuntimeError("formal revenue-assignment label differs")
            if float(metadata["cross_site_system_cost_cny"]) != 0.0:
                raise RuntimeError("formal cross-site system cost is not zero")

            observed_formal_sources = metadata["hash_audit"]["expected_source_hashes"]
            if formal_source_hashes is None:
                formal_source_hashes = observed_formal_sources
            elif observed_formal_sources != formal_source_hashes:
                raise RuntimeError("formal source hashes differ across units")

            if instance_id not in bundles:
                bundle, info = e3.prepare(instance_id)
                if info["mapping_sha256"] != metadata["mapping_sha256"]:
                    raise RuntimeError("customer-ownership mapping hash differs")
                bundles[instance_id] = replace(
                    bundle, prices=replace(bundle.prices, cross_site_cost=0.0)
                )
            bundle = bundles[instance_id]
            members = tuple(sorted(bundle.fleet_caps_by_depot))
            if len(members) != 4:
                raise RuntimeError(f"expected four contractors, found {len(members)}")
            grand_name = "+".join(members)
            grand_slug = "__".join(member.removeprefix("D_") for member in members)
            solution_rel = f"solutions/{grand_slug}.json"

            solution_hash = registered_input(unit, solution_rel)
            settlement_hash = registered_input(unit, "settlement_results.json")
            solution_payload = read_json(unit / solution_rel)
            if (
                solution_payload["instance_id"] != instance_id
                or int(solution_payload["seed"]) != seed
                or tuple(solution_payload["coalition"]) != members
            ):
                raise RuntimeError("grand-solution identity differs")
            solution = load_solution(solution_payload["solution"])
            if e3.base.solution_sha256(solution) != solution_payload["solution_sha256"]:
                raise RuntimeError("grand-solution payload hash differs")

            settlement = read_json(unit / "settlement_results.json")
            system_cost = float(settlement["coalition_cost_cny"][grand_name])
            system_profit = float(settlement["coalition_profit_cny"][grand_name])
            standalone_profit = {
                member: float(settlement["standalone_profit_cny"][member])
                for member in members
            }
            assert_close(
                float(solution_payload["objective_cny"]),
                system_cost,
                "saved grand cost",
            )
            expected_revenue = system_cost + system_profit

            ledger = calculate_depot_profits(
                solution,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                customer_home_depot=dict(bundle.customer_home_depot),
                carbon_quota_kg=0.0,
            )
            if tuple(sorted(ledger)) != members:
                raise RuntimeError("profit ledger does not contain the four contractors")

            nodes = {node.node_id: node for node in bundle.instance.nodes}
            rho = float(bundle.prices.revenue_per_kg)
            owned_revenue = {
                member: sum(
                    float(nodes[customer].demand) * rho
                    for customer, owner in bundle.customer_home_depot.items()
                    if owner == member
                )
                for member in members
            }
            for member in members:
                row = ledger[member]
                gain = row.profit - standalone_profit[member]
                member_rows.append(
                    {
                        "instance_id": instance_id,
                        "seed": seed,
                        "contractor": member,
                        "revenue_assignment": ASSIGNMENT,
                        "owned_customer_revenue_cny": owned_revenue[member],
                        "actual_service_revenue_cny": row.revenue,
                        "actual_minus_owned_revenue_cny": row.revenue - owned_revenue[member],
                        "actual_service_cost_cny": row.cost_total,
                        "pre_settlement_profit_cny": row.profit,
                        "standalone_profit_cny": standalone_profit[member],
                        "pre_settlement_gain_over_standalone_cny": gain,
                        "pre_settlement_below_standalone": gain < -TOL,
                        "customers_served": row.customers_served,
                        "demand_served_kg": row.demand_kg,
                        "cost_fixed_cny": row.cost_fixed,
                        "cost_distance_cny": row.cost_km,
                        "cost_fuel_cny": row.cost_fuel,
                        "cost_electricity_cny": row.cost_electricity,
                        "cost_occupancy_cny": row.cost_occupancy,
                        "cost_cross_site_cny": row.cost_transship,
                        "cost_carbon_cny": row.cost_carbon,
                    }
                )

            ledger_revenue = sum(row.revenue for row in ledger.values())
            ledger_cost = sum(row.cost_total for row in ledger.values())
            ledger_profit = sum(row.profit for row in ledger.values())
            demand_revenue = sum(owned_revenue.values())
            check_rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "contractor_count": len(ledger),
                    "ledger_revenue_cny": ledger_revenue,
                    "expected_demand_revenue_cny": demand_revenue,
                    "formal_game_revenue_cny": expected_revenue,
                    "revenue_gap_cny": assert_close(
                        ledger_revenue, expected_revenue, "grand revenue"
                    ),
                    "demand_revenue_gap_cny": assert_close(
                        ledger_revenue, demand_revenue, "demand revenue"
                    ),
                    "ledger_cost_cny": ledger_cost,
                    "formal_grand_cost_cny": system_cost,
                    "cost_gap_cny": assert_close(ledger_cost, system_cost, "grand cost"),
                    "ledger_profit_cny": ledger_profit,
                    "formal_grand_profit_cny": system_profit,
                    "profit_gap_cny": assert_close(
                        ledger_profit, system_profit, "grand profit"
                    ),
                    "status": "PASS",
                }
            )
            relative = str(unit.relative_to(source))
            input_hashes[relative] = {
                "unit_artifact_hashes_sha256": sha256(unit / "artifact_hashes.json"),
                "grand_solution_sha256": solution_hash,
                "settlement_results_sha256": settlement_hash,
            }
        except Exception as exc:
            raise RuntimeError(f"failed at {unit.relative_to(source)}: {exc}") from exc

    return member_rows, check_rows, {
        "formal_source_hashes": formal_source_hashes or {},
        "input_hashes": input_hashes,
    }


def report_text(decision: dict[str, Any]) -> str:
    worst = decision["worst_pre_settlement_result"]
    return (
        "# E6 实际配送方收入账本\n\n"
        "状态：PASS_E6_SERVING_REVENUE_LEDGER_COMPLETE。\n\n"
        "本步骤直接读取 E6-A 已封存的60个大联盟方案，把每条路线服务客户的收入记给该路线所属承包商，"
        "并把同一路线的运营成本记给该承包商。没有重新搜索路线，没有修改客户、车辆、充电安排、Shapley或核仁。\n\n"
        f"共得到 {decision['unit_count']} 个场景、{decision['member_rows']} 条公司账。"
        "每个场景的四家公司收入、成本和利润合计均分别与大联盟收入、成本和利润闭合；"
        f"三项最大绝对差为 {decision['maximum_abs_revenue_gap_cny']:.3g}、"
        f"{decision['maximum_abs_cost_gap_cny']:.3g} 和 "
        f"{decision['maximum_abs_profit_gap_cny']:.3g} 元。\n\n"
        f"结算前有 {decision['member_rows_below_standalone']}/{decision['member_rows']} 条公司账低于同一场景的单干利润，"
        f"涉及 {decision['units_with_member_below_standalone']}/{decision['unit_count']} 个场景。"
        f"最严重的一条为 {worst['instance_id']}、种子 {worst['seed']}、{worst['contractor']}，"
        f"比单干低 {abs(worst['gain_over_standalone_cny']):.3f} 元。\n\n"
        "该账本只补齐“收入随实际配送方归属”的结算前证据口径。正式合作节省和核仁分配结果保持不变。\n"
    )


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError(f"output already exists: {output}")
    member_rows, check_rows, audit = derive(source)
    output.mkdir(parents=False)
    write_csv(output / "raw_runs.csv", member_rows)
    write_csv(output / "ledger_checks.csv", check_rows)

    below = [row for row in member_rows if row["pre_settlement_below_standalone"]]
    worst = min(member_rows, key=lambda row: float(row["pre_settlement_gain_over_standalone_cny"]))
    decision = {
        "schema": "resetp.e6-serving-revenue-ledger-decision.v2",
        "status": "PASS_E6_SERVING_REVENUE_LEDGER_COMPLETE",
        "evidence_scope": "MECHANICAL_PRE_SETTLEMENT_ACCOUNTING_SUPPLEMENT_ONLY",
        "revenue_assignment": ASSIGNMENT,
        "unit_count": len(check_rows),
        "member_rows": len(member_rows),
        "member_rows_below_standalone": len(below),
        "units_with_member_below_standalone": len(
            {(row["instance_id"], row["seed"]) for row in below}
        ),
        "minimum_pre_settlement_gain_over_standalone_cny": float(
            worst["pre_settlement_gain_over_standalone_cny"]
        ),
        "worst_pre_settlement_result": {
            "instance_id": worst["instance_id"],
            "seed": worst["seed"],
            "contractor": worst["contractor"],
            "gain_over_standalone_cny": worst[
                "pre_settlement_gain_over_standalone_cny"
            ],
        },
        "standalone_profit_linked_from_registered_input": True,
        "all_units_closed": all(row["status"] == "PASS" for row in check_rows),
        "maximum_abs_revenue_gap_cny": max(abs(float(row["revenue_gap_cny"])) for row in check_rows),
        "maximum_abs_cost_gap_cny": max(abs(float(row["cost_gap_cny"])) for row in check_rows),
        "maximum_abs_profit_gap_cny": max(abs(float(row["profit_gap_cny"])) for row in check_rows),
        "route_search_executed": False,
        "solver_reruns": 0,
        "route_or_allocation_changed": False,
    }
    sources = (
        Path(__file__),
        REPO / "solver/src/setp_solver/profit.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/solution.py",
        Path(e3.__file__),
        Path(e3.base.__file__),
    )
    metadata = {
        "schema": "resetp.e6-serving-revenue-ledger-metadata.v2",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "input_panel": str(source.relative_to(REPO)),
        "input_panel_artifact_hashes_sha256": sha256(source / "artifact_hashes.json"),
        "input_units": audit["input_hashes"],
        "formal_run_source_hashes": audit["formal_source_hashes"],
        "postprocess_source_hashes": {
            str(path.relative_to(REPO)): sha256(path) for path in sources
        },
        "route_search_executed": False,
        "solver_reruns": 0,
        "allocation_recomputed": False,
        "route_solutions_modified": False,
        "accounting_function": "setp_solver.profit.calculate_depot_profits",
        "revenue_assignment": ASSIGNMENT,
        "standalone_profit_source": "each formal unit settlement_results.json",
    }
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(report_text(decision), encoding="utf-8")
    artifacts = {
        path.name: sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    write_json(
        output / "artifact_hashes.json",
        {"schema": "resetp.artifact-hashes.v1", "artifacts": artifacts},
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
