#!/usr/bin/env python3
"""Derive the approved actual-service revenue ledger from sealed E6 pilots."""

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

from e6_methods import subset_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.profit import calculate_depot_profits
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

from baselines.china_e3_e7.e3_scattered_ownership_20260801 import (
    run_e3_capacity_rank_aligned as e3,
)

PILOT05 = HERE / "pilot05_grand_coalition_recovery_20260801"
PILOT06 = HERE / "pilot06_direct_15_20260801"
OUTPUT = HERE / "pilot08_direct_natural_profit_ledger_20260801"
E3_METADATA = e3.OUTPUT / "metadata.json"
REVENUE_ASSIGNMENT = "REVENUE_TO_SERVING_CONTRACTOR"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def verify_manifest(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "artifact_hashes.json"
    payload = read_json(manifest_path)
    artifacts = payload.get("artifacts", payload)
    mismatches = {
        name: {"expected": expected, "observed": sha256(directory / name)}
        for name, expected in artifacts.items()
        if name != "schema" and sha256(directory / name) != expected
    }
    if mismatches:
        raise RuntimeError(f"artifact manifest mismatch: {directory}")
    return {
        "manifest_sha256": sha256(manifest_path),
        "artifact_count": len([name for name in artifacts if name != "schema"]),
        "all_match": True,
    }


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[
            ChargingAction(**row) for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def load_base() -> tuple[Any, dict[str, Any]]:
    bundle, info = e3.prepare(e3.INSTANCE)
    bundle = replace(bundle, prices=replace(bundle.prices, cross_site_cost=0.0))
    return bundle, info


def source_audit() -> dict[str, Any]:
    expected = read_json(E3_METADATA)["source_hashes"]
    observed: dict[str, str] = {}
    resolved_paths: dict[str, str] = {}
    for name, expected_hash in expected.items():
        path = REPO / name
        if sha256(path) != expected_hash and path.name == "run_e3_scattered_ownership.py":
            snapshot = path.parent / "source_snapshot" / path.name
            if snapshot.exists() and sha256(snapshot) == expected_hash:
                path = snapshot
        observed[name] = sha256(path)
        resolved_paths[name] = str(path.relative_to(REPO))
    if observed != expected:
        raise RuntimeError("sealed E3 source hash changed")
    sources = (
        Path(__file__),
        HERE / "e6_methods.py",
        PROTOTYPE / "route_pool_sp.py",
        REPO / "solver/src/setp_solver/profit.py",
    )
    return {
        "e3_sources": observed,
        "e3_source_paths": resolved_paths,
        "current_sources": {
            str(path.relative_to(REPO)): sha256(path) for path in sources
        },
        "protected_files": {
            str(path.relative_to(REPO)): sha256(path) for path in e3.base.PROTECTED
        },
    }


def checked_solution(payload: dict[str, Any], bundle: Any) -> tuple[Solution, float]:
    solution = load_solution(payload["solution"])
    cost, _, violations = exact_china81_score(solution, bundle)
    if violations or not math.isclose(cost, float(payload["objective_cny"]), abs_tol=1e-6):
        raise RuntimeError("sealed solution failed complete-model verification")
    if e3.base.solution_sha256(solution) != payload["solution_sha256"]:
        raise RuntimeError("sealed solution hash differs")
    return solution, cost


def derive() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    manifests = {
        "pilot05": verify_manifest(PILOT05),
        "pilot06": verify_manifest(PILOT06),
    }
    bundle, info = load_base()
    grand_payload = read_json(PILOT05 / "solution.json")
    if grand_payload["mapping_sha256"] != info["mapping_sha256"]:
        raise RuntimeError("pilot05 mapping differs")
    grand_solution, grand_cost = checked_solution(grand_payload, bundle)

    with (PILOT06 / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        singleton_raw = {
            row["coalition"]: row
            for row in csv.DictReader(handle)
            if row["record_type"] == "COMPLETED"
            and int(row["coalition_member_count"]) == 1
            and row["status"] == "PASS"
        }
    members = tuple(sorted(bundle.fleet_caps_by_depot))
    if set(singleton_raw) != set(members):
        raise RuntimeError("pilot06 does not contain exactly four completed singletons")

    nodes = {node.node_id: node for node in bundle.instance.nodes}
    rho = float(bundle.prices.revenue_per_kg)
    original_revenue = {
        member: sum(
            float(nodes[customer].demand) * rho
            for customer, owner in bundle.customer_home_depot.items()
            if owner == member
        )
        for member in members
    }
    standalone_cost: dict[str, float] = {}
    for member in members:
        path = PILOT06 / "solutions" / f"{member.removeprefix('D_')}.json"
        payload = read_json(path)
        if payload["coalition"] != [member]:
            raise RuntimeError("pilot06 singleton label differs")
        solution, cost = checked_solution(payload, subset_bundle(bundle, (member,)))
        raw = singleton_raw[member]
        if raw["solution_sha256"] != payload["solution_sha256"] or not math.isclose(
            float(raw["objective_cny"]), cost, abs_tol=1e-6
        ):
            raise RuntimeError("pilot06 singleton raw row differs from solution")
        ledger = calculate_depot_profits(
            solution,
            subset_bundle(bundle, (member,)).instance,
            bundle.time_profile,
            bundle.prices,
            customer_home_depot={
                customer: owner
                for customer, owner in bundle.customer_home_depot.items()
                if owner == member
            },
            carbon_quota_kg=0.0,
        )[member]
        if not math.isclose(ledger.revenue, original_revenue[member], abs_tol=1e-7):
            raise RuntimeError("singleton actual-service revenue does not close")
        if not math.isclose(ledger.cost_total, cost, abs_tol=1e-6):
            raise RuntimeError("singleton ledger cost does not close")
        standalone_cost[member] = cost

    grand_ledger = calculate_depot_profits(
        grand_solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )
    if not math.isclose(
        sum(row.cost_total for row in grand_ledger.values()), grand_cost, abs_tol=1e-6
    ):
        raise RuntimeError("grand-coalition ledger cost does not close")
    if not math.isclose(
        sum(row.revenue for row in grand_ledger.values()),
        sum(original_revenue.values()),
        abs_tol=1e-7,
    ):
        raise RuntimeError("grand-coalition actual-service revenue does not close")

    rows: list[dict[str, Any]] = []
    for member in members:
        standalone_profit = original_revenue[member] - standalone_cost[member]
        natural = grand_ledger[member]
        delta = natural.profit - standalone_profit
        rows.append(
            {
                "contractor": member,
                "original_customer_revenue_cny": original_revenue[member],
                "standalone_cost_cny": standalone_cost[member],
                "standalone_profit_cny": standalone_profit,
                "grand_actual_service_revenue_cny": natural.revenue,
                "grand_actual_service_cost_cny": natural.cost_total,
                "grand_natural_profit_cny": natural.profit,
                "grand_natural_minus_standalone_profit_cny": delta,
                "grand_natural_profit_below_standalone": delta < -1e-7,
            }
        )

    singleton_sum = sum(standalone_cost.values())
    summary = {
        "singleton_cost_sum_cny": singleton_sum,
        "grand_cost_cny": grand_cost,
        "saving_cny": singleton_sum - grand_cost,
        "saving_percent": 100.0 * (singleton_sum - grand_cost) / singleton_sum,
        "members_below_standalone": sum(
            row["grand_natural_profit_below_standalone"] for row in rows
        ),
    }
    audit = {
        "input_manifests": manifests,
        "source_hashes": source_audit(),
        "mapping_sha256": info["mapping_sha256"],
        "grand_solution_sha256": grand_payload["solution_sha256"],
        "singleton_solution_sha256": {
            member: singleton_raw[member]["solution_sha256"] for member in members
        },
    }
    return rows, summary, audit


def report_text(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# E6 直接订单转移：自然利润记账小试",
        "",
        "本表只把已封存方案按“收入归实际配送方”重新记账，没有搜索、调参或结算。",
        "",
        "| 承包商 | 原客户收入 | 单干成本 | 单干利润 | 合作后实际配送收入 | 合作后成本 | 自然利润 | 相对单干变化 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['contractor']} | {row['original_customer_revenue_cny']:.3f} | "
            f"{row['standalone_cost_cny']:.3f} | {row['standalone_profit_cny']:.3f} | "
            f"{row['grand_actual_service_revenue_cny']:.3f} | "
            f"{row['grand_actual_service_cost_cny']:.3f} | "
            f"{row['grand_natural_profit_cny']:.3f} | "
            f"{row['grand_natural_minus_standalone_profit_cny']:+.3f} |"
        )
    lines.extend(
        [
            "",
            (
                f"四家单干成本合计 {summary['singleton_cost_sum_cny']:.3f} 元，"
                f"大联盟成本 {summary['grand_cost_cny']:.3f} 元，节省 "
                f"{summary['saving_cny']:.3f} 元（{summary['saving_percent']:.3f}%）。"
            ),
            "",
        ]
    )
    if summary["members_below_standalone"] == 0:
        lines.append("本小试没有出现需要结算才能留下的亏损方。")
    else:
        lines.append(
            f"本小试有 {summary['members_below_standalone']} 家承包商的自然利润低于单干。"
        )
    lines.extend(["", "这是候选算例小试，不是正式实验结论。"])
    return "\n".join(lines) + "\n"


def run(output: Path = OUTPUT) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    rows, summary, audit = derive()
    decision = {
        "status": "PASS_CANDIDATE_PILOT_NATURAL_LEDGER_DERIVED",
        "formal_result": False,
        "revenue_assignment": REVENUE_ASSIGNMENT,
        "members_below_standalone": summary["members_below_standalone"],
        "all_members_better_without_settlement": summary["members_below_standalone"] == 0,
        **summary,
    }
    metadata = {
        "schema": "resetp.e6-direct-natural-ledger.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "derivation_only": True,
        "formal_result": False,
        "revenue_assignment": REVENUE_ASSIGNMENT,
        "inputs": {
            "grand_coalition": str(PILOT05.relative_to(REPO)),
            "singletons": str(PILOT06.relative_to(REPO)),
        },
        "audit": audit,
    }
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    write_json(output / "metadata.json", metadata)
    (output / "report.md").write_text(
        report_text(rows, summary), encoding="utf-8"
    )
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
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
