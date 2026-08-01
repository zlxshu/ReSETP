#!/usr/bin/env python3
"""E6 C2 preflight with scattered owners and the original China81 fleet."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    canonical_sha256,
    load_bundle,
    write_csv,
    write_json,
)

INSTANCE = "cn-prd-150c-01-V2-LOCATIONS"
SEED = 1
FAMILIES = ("Uniform_Balanced", "Uniform_Unbalanced")
SCENARIOS = ("A_DIRECT_SERVICE_RIGHT", "B_PHYSICAL_TRANSFER")
METHODS = ("A_POSTHOC_SETTLEMENT", "B_IN_SEARCH_PROFIT_FLOOR")
E3 = HERE.parent / "e3_scattered_ownership_20260801"
HALT = "HALT_SINGLETON_CAPACITY_LOWER_BOUND_EXCEEDS_FLEET_SLOTS"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def read_sequences() -> dict[str, tuple[int, ...]]:
    with (E3 / "source_p_sequences.csv").open(encoding="utf-8", newline="") as handle:
        return {
            row["source_family"]: tuple(map(int, row["p_sequence"].split()))
            for row in csv.DictReader(handle)
            if row["replicate"] == "01" and row["source_family"] in FAMILIES
        }


def expected_mapping_hashes() -> dict[str, str]:
    with (E3 / "pilot/preflight_runs.csv").open(encoding="utf-8", newline="") as handle:
        return {
            row["source_family"]: row["mapping_sha256"]
            for row in csv.DictReader(handle)
            if row["instance_id"] == INSTANCE and row["source_family"] in FAMILIES
        }


def build_evidence() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    base = load_bundle(INSTANCE)
    nodes = {node.node_id: node for node in base.instance.nodes}
    customers = sorted(node.node_id for node in base.instance.nodes if node.node_type == "c")
    depots = tuple(sorted(base.fleet_caps_by_depot))
    sequences = read_sequences()
    expected_hashes = expected_mapping_hashes()
    payloads = {
        kind: float(base.instance.vehicle_profile(kind).payload_capacity_kg)
        for kind in ("cv", "ev")
    }
    max_payload = max(payloads.values())
    rows: list[dict[str, Any]] = []
    family_results: dict[str, Any] = {}

    for family in FAMILIES:
        mapping = {
            customer: depots[label]
            for customer, label in zip(customers, sequences[family][: len(customers)], strict=True)
        }
        mapping_hash = canonical_sha256(mapping)
        if mapping_hash != expected_hashes[family]:
            raise ValueError(f"{family} mapping does not match the approved E3 input")
        bundle = replace(base, customer_home_depot=MappingProxyType(mapping))
        owner_stats: dict[str, dict[str, Any]] = {}
        blocked: list[str] = []
        for depot in depots:
            owned = [customer for customer in customers if bundle.customer_home_depot[customer] == depot]
            demand = sum(
                base.instance.load_mass_kg(
                    nodes[customer].demand,
                    fallback_mass_per_unit_kg=1.0,
                )
                for customer in owned
            )
            caps = base.fleet_caps_by_depot[depot]
            route_lower_bound = math.ceil(demand / max_payload)
            fleet_cap = int(caps["total_fleet_cap"])
            owner_stats[depot] = {
                "customer_count": len(owned),
                "demand_kg": demand,
                "cv_cap": int(caps["num_cv"]),
                "ev_cap": int(caps["num_ev"]),
                "total_fleet_cap": fleet_cap,
                "capacity_route_lower_bound": route_lower_bound,
            }
            if route_lower_bound > fleet_cap:
                blocked.append(depot)

        family_results[family] = {
            "mapping_sha256": mapping_hash,
            "blocked_singletons": blocked,
            "owners": owner_stats,
        }
        quick_coalitions = tuple((depot,) for depot in depots) + (depots,)
        for scenario in SCENARIOS:
            for method in METHODS:
                for coalition in quick_coalitions:
                    stats = {
                        key: sum(owner_stats[depot][key] for depot in coalition)
                        for key in ("customer_count", "demand_kg", "cv_cap", "ev_cap", "total_fleet_cap")
                    }
                    route_lower_bound = math.ceil(stats["demand_kg"] / max_payload)
                    direct_block = len(coalition) == 1 and coalition[0] in blocked
                    rows.append(
                        {
                            "instance_id": INSTANCE,
                            "seed": SEED,
                            "owner_family": family,
                            "mapping_sha256": mapping_hash,
                            "business_scenario": scenario,
                            "method": method,
                            "coalition": "+".join(coalition),
                            "coalition_member_count": len(coalition),
                            **stats,
                            "max_payload_kg": max_payload,
                            "capacity_route_lower_bound": route_lower_bound,
                            "capacity_lower_bound_feasible": route_lower_bound <= stats["total_fleet_cap"],
                            "route_search_executed": False,
                            "search_evaluations": 0,
                            "actual_cv_used": "",
                            "actual_ev_used": "",
                            "cost_cny": "",
                            "profit_cny": "",
                            "cross_contractor_services": "",
                            "physical_transfer_cost_cny": "",
                            "status": HALT if direct_block else "NOT_RUN_SINGLETON_SET_INCOMPLETE",
                        }
                    )

    blocked = {
        family: result["blocked_singletons"]
        for family, result in family_results.items()
    }
    metadata = {
        "pilot_id": "E6-C2-PILOT03-SCATTERED-ORIGINAL-FLEET",
        "created_on": "2026-08-01",
        "instance_id": INSTANCE,
        "seed": SEED,
        "owner_assignment_source": str(E3 / "source_p_sequences.csv"),
        "owner_assignment_families": list(FAMILIES),
        "same_city_or_nearest_owner_used": False,
        "mapping_hashes_verified_against": str(E3 / "pilot/preflight_runs.csv"),
        "vehicle_payload_kg": payloads,
        "fleet_caps_by_depot": {
            depot: dict(base.fleet_caps_by_depot[depot]) for depot in depots
        },
        "fleet_cap_semantics": "one selected route consumes one vehicle slot",
        "fleet_constraint_source": "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py",
        "business_scenarios": list(SCENARIOS),
        "methods": list(METHODS),
        "quick_coalitions_per_family": 5,
        "raw_row_count": len(rows),
        "route_search_executed": False,
        "input_sha256": {
            "source_p_sequences.csv": file_sha256(E3 / "source_p_sequences.csv"),
            "e3_preflight_runs.csv": file_sha256(E3 / "pilot/preflight_runs.csv"),
            "run_c2_pilot.py": file_sha256(Path(__file__)),
        },
    }
    decision = {
        "status": "HALT_E6_C2_SINGLETON_BASELINES_NOT_FORMABLE",
        "scientific_result": False,
        "reason": (
            "At least one approved scattered-owner singleton needs more capacity-limited "
            "routes than its original China81 depot fleet supplies."
        ),
        "blocked_singletons": blocked,
        "family_details": family_results,
        "search_not_started": True,
        "scenario_and_method_comparison_available": False,
        "fifteen_coalitions_not_started": True,
        "fleet_caps_changed": False,
        "new_price_parameter_added": False,
    }
    return metadata, rows, decision


def report_text(decision: dict[str, Any]) -> str:
    details = decision["family_details"]
    lines = [
        "# E6 C2 pilot03：散乱归属 + 原始车队预检",
        "",
        "结论：本轮按预先约定的停止条件停下，没有形成 E6 方法效果结论，也没有启动路线搜索。",
        "",
        "两类客户归属均直接取自 E3 已核实的 Uniform_Balanced / Uniform_Unbalanced 序列；映射哈希与 E3 预检完全一致，没有使用同城或最近车场归属。车队保持 China81 原始上限，未放大、未固定油电比例。",
        "",
        "当前 E6 路线组合模型中，一条入选路线占用一个车辆名额。按较大的柴油车载重 1735 kg 计算最宽松下界，仍有以下单干承包商装不下：",
        "",
    ]
    for family in FAMILIES:
        lines.append(f"## {family}")
        lines.append("")
        for depot in details[family]["blocked_singletons"]:
            row = details[family]["owners"][depot]
            lines.append(
                f"{depot}：{row['customer_count']} 个客户、{row['demand_kg']:.0f} kg，"
                f"至少需要 {row['capacity_route_lower_bound']} 条路线，原车队只有 "
                f"{row['total_fleet_cap']} 辆（CV {row['cv_cap']} + EV {row['ev_cap']}）。"
            )
        lines.append("")
    lines.extend(
        [
            "因此四家单干基准不完整，合作总增益、自然分配下的亏损、方法 B 成本、Shapley 和核都没有合法比较基准。本轮没有执行场景 A/B，也没有计算场景 B 的实体转运费。raw_runs.csv 保留了两类归属 × 两种业务场景 × 两种方法 × 五个快速联盟的全部 40 行状态。",
            "",
            "本轮没有新增市场单价，没有改共享代码、论文、中央交接文件或审批文件。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    output = HERE / "pilot03"
    output.mkdir(parents=True, exist_ok=True)
    metadata, rows, decision = build_evidence()
    write_json(output / "metadata.json", metadata)
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(report_text(decision), encoding="utf-8")
    write_json(
        output / "artifact_hashes.json",
        {
            name: file_sha256(output / name)
            for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
        },
    )
    print(json.dumps({"output": str(output), "status": decision["status"], "rows": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
