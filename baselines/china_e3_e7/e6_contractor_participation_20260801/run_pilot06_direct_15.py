#!/usr/bin/env python3
"""E6 direct-order scene: all 15 coalitions with singleton-union incumbents."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import numpy as np
from e6_methods import (
    coalition_revenue,
    coalitions,
    core_allocation,
    core_violations,
    shapley,
    subset_bundle,
)
from route_pool_sp import (
    RoutePoolRecord,
    _route_pool_records,
    run_hgs_route_pool_recombination,
)
from scipy.optimize import Bounds, LinearConstraint, milp
from setp_solver.china81_completion import (
    _single_route_cost,
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.profit import calculate_depot_profits
from setp_solver.solution import (
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)

from baselines.china_e3_e7.e3_scattered_ownership_20260801 import (
    run_e3_capacity_rank_aligned as e3,
)

INSTANCE = e3.INSTANCE
SEED = 1
ITERATIONS = 100
ARCHIVE = 8
SP_SECONDS = 5.0
THETA_STEP = 0.05
OUTPUT = HERE / "pilot06_direct_15_20260801"
COMMON_OUTPUT = HERE / "pilot09_direct_15_independent_initial_20260801"
E3_METADATA = e3.OUTPUT / "metadata.json"
E3_RAW = e3.OUTPUT / "raw_runs.csv"
PILOT04 = HERE / "pilot04_rank_aligned_direct_screen_20260801"
PILOT05 = HERE / "pilot05_grand_coalition_recovery_20260801"
PROTECTED = tuple(e3.base.PROTECTED)
REVENUE_ASSIGNMENT = "REVENUE_TO_SERVING_CONTRACTOR"
MULTI_MEMBER_INITIAL_UNION = "union"
MULTI_MEMBER_INITIAL_COMMON = "common"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def verify_manifest(directory: Path) -> bool:
    payload = json.loads((directory / "artifact_hashes.json").read_text())
    artifacts = payload.get("artifacts", payload)
    return all(
        sha256(directory / name) == expected
        for name, expected in artifacts.items()
        if name != "schema"
    )


def source_audit() -> dict[str, Any]:
    expected = json.loads(E3_METADATA.read_text())["source_hashes"]
    observed = {name: sha256(REPO / name) for name in expected}
    if any(observed[name] != value for name, value in expected.items()):
        raise RuntimeError("E3-02 source or protected hash changed")
    if not verify_manifest(PILOT04) or not verify_manifest(PILOT05):
        raise RuntimeError("pilot04 or pilot05 artifact hash changed")
    current_sources = (
        Path(__file__),
        HERE / "e6_methods.py",
        PROTOTYPE / "route_pool_sp.py",
        Path(e3.__file__),
        E3_RAW,
    )
    return {
        "e3_expected": expected,
        "e3_observed": observed,
        "e3_all_match": True,
        "pilot04_all_match": True,
        "pilot05_all_match": True,
        "current_source_hashes": {
            str(path.relative_to(REPO)): sha256(path) for path in current_sources
        },
    }


def load_base(
    instance_id: str = INSTANCE,
    expected_mapping_sha256: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    bundle, info = e3.prepare(instance_id)
    bundle = replace(bundle, prices=replace(bundle.prices, cross_site_cost=0.0))
    if expected_mapping_sha256 is None and instance_id == INSTANCE:
        with E3_RAW.open(encoding="utf-8", newline="") as handle:
            expected_mapping = {row["mapping_sha256"] for row in csv.DictReader(handle)}
        expected_mapping_sha256 = (
            next(iter(expected_mapping)) if len(expected_mapping) == 1 else ""
        )
    if (
        expected_mapping_sha256 is not None
        and expected_mapping_sha256 != info["mapping_sha256"]
    ):
        raise RuntimeError("mapping hash differs from E3-02")
    original = e3.base.load_bundle(instance_id)
    if {depot: dict(row) for depot, row in bundle.fleet_caps_by_depot.items()} != {
        depot: dict(row) for depot, row in original.fleet_caps_by_depot.items()
    }:
        raise RuntimeError("fleet differs from original China81 caps")
    return bundle, info


def coalition_slug(group: tuple[str, ...]) -> str:
    return "__".join(member.removeprefix("D_") for member in group)


def union_singleton_solutions(
    bundle: Any,
    singleton_solutions: dict[str, Solution],
    members: tuple[str, ...],
) -> Solution:
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for member in members:
        solution = singleton_solutions[member]
        base_ids: dict[tuple[str, str], str] = {}
        full_ids: dict[str, str] = {}
        counts: Counter[str] = Counter()
        for route in solution.routes:
            old_base = physical_vehicle_id(route.vehicle_id)
            key = (route.vehicle_type.lower(), old_base)
            if key not in base_ids:
                counts[route.vehicle_type.lower()] += 1
                base_ids[key] = (
                    f"UNION-{member.removeprefix('D_')}-"
                    f"{route.vehicle_type.upper()}-{counts[route.vehicle_type.lower()]:03d}"
                )
            suffix = route.vehicle_id[len(old_base) :]
            new_id = base_ids[key] + suffix
            full_ids[route.vehicle_id] = new_id
            routes.append(replace(route, vehicle_id=new_id))
        for action in solution.charging_actions:
            actions.append(replace(action, vehicle_id=full_ids[action.vehicle_id]))
    return annotate_cross_site_services(
        Solution(routes=routes, charging_actions=actions),
        bundle.customer_home_depot,
    )


def build_multi_member_initial(
    bundle: Any,
    singleton_solutions: dict[str, Solution],
    members: tuple[str, ...],
    mode: str,
) -> tuple[Solution, str]:
    if mode == MULTI_MEMBER_INITIAL_UNION:
        return (
            union_singleton_solutions(bundle, singleton_solutions, members),
            "UNION_OF_MEMBER_SINGLETON_FINALS",
        )
    if mode == MULTI_MEMBER_INITIAL_COMMON:
        return e3.base.build_common_initial(bundle)[0], "COALITION_COMMON_INITIAL"
    raise ValueError(f"unknown multi-member initial mode: {mode}")


def solution_records(
    bundle: Any, solution: Solution, source: str
) -> tuple[RoutePoolRecord, ...]:
    customers = set(bundle.customer_home_depot)
    actions: dict[str, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        actions.setdefault(action.vehicle_id, []).append(action)
    return tuple(
        RoutePoolRecord(
            route=route,
            actions=tuple(actions.get(route.vehicle_id, ())),
            customers=tuple(node for node in route.node_sequence if node in customers),
            route_cost=_single_route_cost(
                route, tuple(actions.get(route.vehicle_id, ())), bundle
            ),
            source_view=source,
            source_rank=rank,
        )
        for rank, route in enumerate(solution.routes)
    )


def record_key(record: RoutePoolRecord) -> tuple[Any, ...]:
    return (
        record.route.vehicle_type.lower(),
        record.route.home_depot_id,
        record.customers,
        tuple(
            (
                action.station_id,
                round(float(action.energy_kwh), 9),
                round(float(action.charge_start_second), 9),
                action.charging_curve_id,
            )
            for action in record.actions
        ),
    )


def augmented_records(
    bundle: Any, run: Any, initial: Solution
) -> tuple[RoutePoolRecord, ...]:
    unique: dict[tuple[Any, ...], RoutePoolRecord] = {}
    for record in (
        *_route_pool_records(bundle, run.view_epochs),
        *solution_records(bundle, initial, "coalition_initial_incumbent"),
    ):
        key = record_key(record)
        if key not in unique or record.route_cost < unique[key].route_cost:
            unique[key] = record
    return tuple(unique.values())


def run_search(
    bundle: Any,
    initial: Solution,
    *,
    seed: int = SEED,
    iterations: int = ITERATIONS,
    archive: int = ARCHIVE,
    sp_seconds: float = SP_SECONDS,
) -> dict[str, Any]:
    initial_cost, _, initial_violations = exact_china81_score(initial, bundle)
    if initial_violations:
        raise RuntimeError("coalition initial solution is not legal")
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=archive,
        max_archive_candidates_per_view=archive,
        sp_time_limit_seconds=sp_seconds,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=iterations,
        wallclock_safety_seconds_per_view=180.0,
        exact_checkpoint_interval_iterations=None,
    )
    search_cost, _, search_violations = exact_china81_score(run.solution, bundle)
    if search_violations or not math.isclose(
        search_cost, run.completion.objective, abs_tol=1e-6
    ):
        raise RuntimeError("search result failed complete-model verification")
    if search_cost < initial_cost:
        final, final_cost, selected = (
            run.solution,
            search_cost,
            "SEARCH_STRICT_IMPROVEMENT",
        )
    else:
        final, final_cost, selected = initial, initial_cost, "INCUMBENT_RETAINED"
    checked_cost, breakdown, violations = exact_china81_score(final, bundle)
    if violations or not math.isclose(checked_cost, final_cost, abs_tol=1e-6):
        raise RuntimeError("retained coalition solution failed final verification")
    return {
        "run": run,
        "initial": initial,
        "initial_cost": initial_cost,
        "search_cost": search_cost,
        "solution": final,
        "cost": final_cost,
        "breakdown": breakdown,
        "selected_source": selected,
        "records": augmented_records(bundle, run, initial),
    }


def solution_payload(
    bundle: Any,
    group: tuple[str, ...],
    result: dict[str, Any],
    *,
    instance_id: str = INSTANCE,
    seed: int = SEED,
) -> dict[str, Any]:
    _, breakdown, violations = exact_china81_score(result["solution"], bundle)
    return {
        "schema": "resetp.e6-direct-coalition-solution.v1",
        "instance_id": instance_id,
        "coalition": list(group),
        "seed": seed,
        "objective_cny": result["cost"],
        "selected_source": result["selected_source"],
        "solution_sha256": e3.base.solution_sha256(result["solution"]),
        "breakdown": breakdown,
        "violations": [asdict(item) for item in violations],
        "solution": asdict(result["solution"]),
    }


def route_pool_payload(
    group: tuple[str, ...], records: tuple[RoutePoolRecord, ...]
) -> dict[str, Any]:
    counts = Counter(record.source_view for record in records)
    return {
        "schema": "resetp.e6-direct-coalition-route-pool.v1",
        "coalition": list(group),
        "summary": {
            "record_count": len(records),
            "records_by_source": dict(sorted(counts.items())),
            "minimum_route_cost_cny": min(record.route_cost for record in records),
            "maximum_route_cost_cny": max(record.route_cost for record in records),
        },
        "records": [
            {
                "source_view": record.source_view,
                "source_rank": record.source_rank,
                "route_cost_cny": record.route_cost,
                "customers": list(record.customers),
                "route": asdict(record.route),
                "charging_actions": [asdict(action) for action in record.actions],
            }
            for record in records
        ],
    }


def transfer_metrics(bundle: Any, solution: Solution) -> tuple[int, float]:
    customers = {item.customer_id for item in solution.cross_site_services}
    demand = {
        node.node_id: float(node.demand)
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    return len(customers), sum(demand[customer] for customer in customers)


def owned_revenue(bundle: Any) -> dict[str, float]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    rho = float(bundle.prices.revenue_per_kg)
    return {
        depot: sum(
            float(nodes[customer].demand) * rho
            for customer, owner in bundle.customer_home_depot.items()
            if owner == depot
        )
        for depot in sorted(bundle.fleet_caps_by_depot)
    }


def contractor_profits(bundle: Any, solution: Solution) -> dict[str, float]:
    ledger = calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )
    return {depot: float(row.profit) for depot, row in ledger.items()}


def permutation_shapley(
    values: dict[tuple[str, ...], float], members: tuple[str, ...]
) -> dict[str, float]:
    allocation = {member: 0.0 for member in members}
    permutations = tuple(itertools.permutations(members))
    for order in permutations:
        group: tuple[str, ...] = ()
        before = 0.0
        for member in order:
            group = tuple(sorted((*group, member)))
            after = values[group]
            allocation[member] += after - before
            before = after
    return {member: value / len(permutations) for member, value in allocation.items()}


def theta_values() -> tuple[float, ...]:
    return tuple(
        round(index * THETA_STEP, 10) for index in range(round(1.0 / THETA_STEP) + 1)
    )


def solve_profit_floor(
    bundle: Any,
    records: tuple[RoutePoolRecord, ...],
    standalone: dict[str, float],
    theta: float,
) -> tuple[Solution | None, dict[str, Any]]:
    customers = tuple(bundle.customer_home_depot)
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    customer_index = {customer: index for index, customer in enumerate(customers)}
    cover = np.zeros((len(customers), len(records)))
    for column, record in enumerate(records):
        for customer in record.customers:
            cover[customer_index[customer], column] = 1.0
    constraints: list[LinearConstraint] = [
        LinearConstraint(cover, np.ones(len(customers)), np.ones(len(customers)))
    ]
    for vehicle_type, limit in (
        ("cv", bundle.instance.num_cv),
        ("ev", bundle.instance.num_ev),
    ):
        row = np.array(
            [record.route.vehicle_type.lower() == vehicle_type for record in records]
        )
        constraints.append(LinearConstraint(row, -np.inf, float(limit)))
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    rho = float(bundle.prices.revenue_per_kg)
    for depot in depots:
        for vehicle_type in ("cv", "ev"):
            row = np.array(
                [
                    record.route.home_depot_id == depot
                    and record.route.vehicle_type.lower() == vehicle_type
                    for record in records
                ]
            )
            constraints.append(
                LinearConstraint(
                    row,
                    -np.inf,
                    float(bundle.fleet_caps_by_depot[depot][f"num_{vehicle_type}"]),
                )
            )
        margin = np.array(
            [
                (
                    sum(float(nodes[c].demand) * rho for c in record.customers)
                    - record.route_cost
                )
                if record.route.home_depot_id == depot
                else 0.0
                for record in records
            ]
        )
        constraints.append(LinearConstraint(margin, theta * standalone[depot], np.inf))

    costs = np.array([record.route_cost for record in records])
    result = milp(
        c=costs,
        integrality=np.ones(len(records)),
        bounds=Bounds(np.zeros(len(records)), np.ones(len(records))),
        constraints=constraints,
        options={"time_limit": SP_SECONDS},
    )
    stats = {
        "feasible": result.x is not None,
        "solver_status": int(result.status),
        "solver_message": str(result.message),
        "objective_cny": None,
        "profits_cny": {},
        "solution_sha256": "",
    }
    if result.x is None:
        return None, stats
    vector = np.rint(np.asarray(result.x))
    if not np.allclose(result.x, vector, atol=1e-7) or not np.allclose(
        cover @ vector, np.ones(len(customers)), atol=1e-7
    ):
        raise RuntimeError("profit-floor MIP returned an invalid incumbent")
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for index, record in enumerate(
        (item for item, take in zip(records, vector, strict=True) if take > 0.5),
        start=1,
    ):
        vehicle_id = f"PF-SERVE-{record.route.vehicle_type.upper()}-{index:04d}"
        routes.append(replace(record.route, vehicle_id=vehicle_id))
        actions.extend(
            replace(action, vehicle_id=vehicle_id) for action in record.actions
        )
    solution = annotate_cross_site_services(
        Solution(routes=routes, charging_actions=actions), bundle.customer_home_depot
    )
    objective, _, violations = exact_china81_score(solution, bundle)
    if violations or not math.isclose(objective, float(result.fun), abs_tol=1e-6):
        raise RuntimeError("profit-floor solution failed complete-model verification")
    profits = contractor_profits(bundle, solution)
    if any(profits[depot] < theta * standalone[depot] - 1e-6 for depot in depots):
        raise RuntimeError("profit-floor solution violates its contractor floor")
    stats.update(
        objective_cny=objective,
        profits_cny=profits,
        solution_sha256=e3.base.solution_sha256(solution),
        profit_closure_abs_cny=abs(
            sum(profits.values()) - (coalition_revenue(bundle) - objective)
        ),
    )
    return solution, stats


def method_a_results(
    bundle: Any,
    members: tuple[str, ...],
    coalition_results: dict[tuple[str, ...], dict[str, Any]],
) -> dict[str, Any]:
    costs = {group: result["cost"] for group, result in coalition_results.items()}
    values = {
        group: coalition_revenue(result["bundle"]) - result["cost"]
        for group, result in coalition_results.items()
    }
    standalone = {member: values[(member,)] for member in members}
    profit_shapley = shapley(values, members)
    profit_shapley_check = permutation_shapley(values, members)
    cost_shapley = shapley(costs, members)
    cost_shapley_check = permutation_shapley(costs, members)
    max_shapley_gap = max(
        abs(profit_shapley[m] - profit_shapley_check[m]) for m in members
    )
    max_cost_shapley_gap = max(
        abs(cost_shapley[m] - cost_shapley_check[m]) for m in members
    )
    if max(max_shapley_gap, max_cost_shapley_gap) > 1e-7:
        raise RuntimeError("independent Shapley recomputation differs")
    core_nonempty, core_witness = core_allocation(values, members)
    if core_witness is not None and core_violations(core_witness, values, members):
        raise RuntimeError("reported core witness violates a coalition bound")

    owned = owned_revenue(bundle)
    relation_gap = max(
        abs(profit_shapley[m] - (owned[m] - cost_shapley[m])) for m in members
    )
    if relation_gap > 1e-7:
        raise RuntimeError("profit and cost Shapley identities do not close")
    return {
        "standalone_profit_cny": standalone,
        "coalition_cost_cny": {
            "+".join(group): value for group, value in costs.items()
        },
        "coalition_profit_cny": {
            "+".join(group): value for group, value in values.items()
        },
        "method_A": {
            "shapley_cost_share_cny": cost_shapley,
            "shapley_profit_cny": profit_shapley,
            "independent_profit_shapley_max_abs_gap_cny": max_shapley_gap,
            "independent_cost_shapley_max_abs_gap_cny": max_cost_shapley_gap,
            "profit_cost_identity_max_abs_gap_cny": relation_gap,
            "core_nonempty": core_nonempty,
            "one_core_profit_allocation_cny": core_witness,
            "shapley_in_core": not core_violations(profit_shapley, values, members),
            "shapley_core_violations_cny": {
                "+".join(group): gap
                for group, gap in core_violations(
                    profit_shapley, values, members
                ).items()
            },
        },
        "revenue_assignment": REVENUE_ASSIGNMENT,
    }


def method_results(
    bundle: Any,
    members: tuple[str, ...],
    coalition_results: dict[tuple[str, ...], dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], Solution | None]:
    settlement = method_a_results(bundle, members, coalition_results)
    standalone = settlement["standalone_profit_cny"]
    profit_shapley = settlement["method_A"]["shapley_profit_cny"]
    grand = coalition_results[members]
    natural = contractor_profits(bundle, grand["solution"])
    serving_assignment = {
        "natural_profit_cny": natural,
        "natural_minus_standalone_cny": {
            member: natural[member] - standalone[member] for member in members
        },
        "members_below_standalone_without_settlement": sum(
            natural[member] < standalone[member] - 1e-7 for member in members
        ),
        "method_A_target_shapley_profit_cny": profit_shapley,
        "method_A_internal_settlement_cny": {
            member: profit_shapley[member] - natural[member] for member in members
        },
        "method_A_all_members_meet_standalone": all(
            profit_shapley[member] >= standalone[member] - 1e-7 for member in members
        ),
    }

    diagnostic_trace: list[dict[str, Any]] = []
    theta_one_solution: Solution | None = None
    for theta in theta_values():
        solution, stats = solve_profit_floor(
            bundle, grand["records"], standalone, theta
        )
        diagnostic_trace.append(
            {
                "theta": theta,
                "feasible": stats["feasible"],
                "system_cost_cny": stats["objective_cny"],
                "profits_cny": json.dumps(stats["profits_cny"], sort_keys=True),
                "solution_sha256": stats["solution_sha256"],
                "profit_closure_abs_cny": stats.get("profit_closure_abs_cny", ""),
                "solver_status": stats["solver_status"],
                "solver_message": stats["solver_message"],
            }
        )
        if theta == 1.0:
            theta_one_solution = solution
    feasible = [row for row in diagnostic_trace if row["feasible"]]
    serving_assignment["method_B"] = {
        "trace_role": "LOW_COST_DIAGNOSTIC_NOT_FORMAL_FRONTIER_OR_SUCCESS_GATE",
        "theta_step": THETA_STEP,
        "tested_points": len(diagnostic_trace),
        "feasible_points": len(feasible),
        "highest_feasible_theta": max((row["theta"] for row in feasible), default=None),
        "minimum_system_cost_cny": min(
            (row["system_cost_cny"] for row in feasible), default=None
        ),
        "theta_1_system_cost_cny": next(
            (
                row["system_cost_cny"]
                for row in diagnostic_trace
                if row["theta"] == 1.0 and row["feasible"]
            ),
            None,
        ),
    }

    settlement["serving_assignment"] = serving_assignment
    return settlement, diagnostic_trace, theta_one_solution


def report_text(
    decision: dict[str, Any],
    settlement: dict[str, Any],
    multi_member_initial: str,
    *,
    seed: int = SEED,
    iterations: int = ITERATIONS,
    archive: int = ARCHIVE,
    sp_seconds: float = SP_SECONDS,
    evidence_role: str = "PILOT",
) -> str:
    if multi_member_initial == MULTI_MEMBER_INITIAL_COMMON:
        initial_text = (
            "15 个联盟都从本联盟自己的合法基础方案出发。"
            "这只替换搜索起点，不改单干基准、客户、车队上限、"
            "充电规则、费用或收入归属。旧 pilot06 停在运行前，"
            "是因为当时自加了“单干结果原样合并必须合法”的起点规则，"
            "不是 Shapley 结算或合作博弈本身的要求。"
        )
    else:
        initial_text = "多成员联盟以成员单干最终方案的合法并集为起点。"
    lines = [
        (
            "# E6-A formal unit"
            if evidence_role == "FORMAL_PANEL_UNIT"
            else (
                "# E6-A smoke"
                if evidence_role == "SMOKE_ONLY"
                else "# E6 direct-order 15-coalition pilot"
            )
        ),
        "",
        f"状态：{decision['status']}。",
        "",
        (
            f"15 个非空联盟均使用 seed {seed}、{iterations} 次/视角、"
            f"archive {archive} 与 {sp_seconds:g} s 路线池组合。"
            "只保留合法且严格更便宜的搜索结果。"
        ),
        initial_text,
        (
            f"大联盟成本 {decision['grand_cost_cny']:.3f} 元，四家单干成本合计 "
            f"{decision['singleton_cost_sum_cny']:.3f} 元，节省 "
            f"{decision['grand_saving_cny']:.3f} 元（{decision['grand_saving_percent']:.3f}%）。"
        ),
        (
            f"大联盟有 {decision['grand_cross_contractor_customers']} 个跨承包商客户，"
            f"对应 {decision['grand_cross_contractor_quantity_kg']:.3f} kg。"
        ),
        "",
        (
            f"利润博弈的核={'非空' if settlement['method_A']['core_nonempty'] else '为空'}；"
            f"Shapley {'在核内' if settlement['method_A']['shapley_in_core'] else '不在核内'}。"
        ),
    ]
    if "serving_assignment" not in settlement:
        lines.extend(
            [
                "",
                "合作系统节省按 Shapley 分配，核用于检验联盟稳定性。",
            ]
        )
        return "\n".join(lines) + "\n"

    row = settlement["serving_assignment"]
    method_b = row["method_B"]
    lines.extend(
        [
            "",
            "| 收入归属 | 不结算时低于单干的承包商数 | 方法A全员达到单干 | 方法B诊断可行点/全部点 | theta=1成本/元 |",
            "|---|---:|---|---:|---:|",
            (
                f"| {REVENUE_ASSIGNMENT} | "
                f"{row['members_below_standalone_without_settlement']} | "
                f"{'yes' if row['method_A_all_members_meet_standalone'] else 'no'} | "
                f"{method_b['feasible_points']}/{method_b['tested_points']} | "
                f"{method_b['theta_1_system_cost_cny']} |"
            ),
            "",
            (
                "收入按实际配送方归属。方法A事后 Shapley 结算与方法B搜索内利润底线均已核算；"
                "21 个 theta 取值只是低成本诊断轨迹，不是正式前沿或成功门槛。"
                "本报告不选择正文故事。"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def preflight_union() -> dict[str, Any]:
    base, info = load_base()
    members = tuple(sorted(base.fleet_caps_by_depot))[:2]
    singleton_solutions = {}
    for member in members:
        bundle = subset_bundle(base, (member,))
        singleton_solutions[member] = e3.base.build_common_initial(bundle)[0]
    coalition_bundle = subset_bundle(base, members)
    union = union_singleton_solutions(coalition_bundle, singleton_solutions, members)
    cost, _, violations = exact_china81_score(union, coalition_bundle)
    return {
        "mapping_sha256": info["mapping_sha256"],
        "members": members,
        "union_cost_cny": cost,
        "violations": len(violations),
        "unique_vehicle_ids": len({route.vehicle_id for route in union.routes})
        == len(union.routes),
    }


def run(
    output: Path = OUTPUT,
    multi_member_initial: str = MULTI_MEMBER_INITIAL_UNION,
    *,
    instance_id: str = INSTANCE,
    seed: int = SEED,
    iterations: int = ITERATIONS,
    archive: int = ARCHIVE,
    sp_seconds: float = SP_SECONDS,
    audit_fn: Callable[[], dict[str, Any]] | None = None,
    expected_mapping_sha256: str | None = None,
    include_method_b: bool = True,
    evidence_role: str = "PILOT",
    resume: bool = False,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    audit = (audit_fn or source_audit)()
    base, info = load_base(instance_id, expected_mapping_sha256)
    members = tuple(sorted(base.fleet_caps_by_depot))
    groups = coalitions(members)
    run_config = {
        "instance_id": instance_id,
        "seed": seed,
        "iterations_per_view": iterations,
        "archive_candidates_per_view": archive,
        "route_pool_sp_seconds": sp_seconds,
        "multi_member_initial": multi_member_initial,
        "settlement_method": (
            "A_POSTHOC_SHAPLEY_WITH_CORE_CHECK"
            if not include_method_b
            else "A_AND_B_PILOT_DIAGNOSTIC"
        ),
        "evidence_role": evidence_role,
    }
    singleton_solutions: dict[str, Solution] = {}
    coalition_results: dict[tuple[str, ...], dict[str, Any]] = {}
    raw_rows: list[dict[str, Any]] = []
    completed: dict[str, dict[str, Any]] = {}
    progress_path = output / "progress.json"
    raw_path = output / "raw_runs.csv"

    if resume and progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("run_config") != run_config:
            raise RuntimeError("existing partial output uses a different run config")
        if raw_path.exists():
            with raw_path.open(encoding="utf-8", newline="") as handle:
                completed = {row["coalition"]: row for row in csv.DictReader(handle)}
        if completed and include_method_b:
            raise RuntimeError("pilot Method B does not support coalition resume")
    elif resume and any(output.iterdir()):
        raise RuntimeError("existing output has no resumable progress record")

    def write_progress(settlement_complete: bool = False) -> None:
        write_json(
            progress_path,
            {
                "run_config": run_config,
                "completed_coalitions": [row["coalition"] for row in raw_rows],
                "completed_count": len(raw_rows),
                "total_count": len(groups),
                "settlement_complete": settlement_complete,
            },
        )

    if resume and not progress_path.exists():
        write_progress()

    for group in groups:
        bundle = subset_bundle(base, group)
        coalition_name = "+".join(group)
        slug = coalition_slug(group)
        if coalition_name in completed:
            if not all(
                path.exists()
                for path in (
                    output / "solutions" / f"{slug}.json",
                    output / "route_pools" / f"{slug}.json",
                )
            ):
                raise RuntimeError(f"incomplete saved coalition: {coalition_name}")
            row = completed[coalition_name]
            coalition_results[group] = {
                "bundle": bundle,
                "cost": float(row["final_cost_cny"]),
            }
            raw_rows.append(row)
            continue

        if len(group) == 1:
            initial, _ = e3.base.build_common_initial(bundle)
            initial_source = "SINGLETON_COMMON_INITIAL"
        else:
            initial, initial_source = build_multi_member_initial(
                bundle, singleton_solutions, group, multi_member_initial
            )
        result = run_search(
            bundle,
            initial,
            seed=seed,
            iterations=iterations,
            archive=archive,
            sp_seconds=sp_seconds,
        )
        result["bundle"] = bundle
        coalition_results[group] = result
        if len(group) == 1:
            singleton_solutions[group[0]] = result["solution"]

        solution = solution_payload(
            bundle,
            group,
            result,
            instance_id=instance_id,
            seed=seed,
        )
        pool = route_pool_payload(group, result["records"])
        write_json(output / "solutions" / f"{slug}.json", solution)
        write_json(output / "route_pools" / f"{slug}.json", pool)
        cross_customers, cross_quantity = transfer_metrics(bundle, result["solution"])
        raw_rows.append(
            {
                "instance_id": instance_id,
                "seed": seed,
                "mapping_sha256": info["mapping_sha256"],
                "coalition": coalition_name,
                "coalition_member_count": len(group),
                "initial_source": initial_source,
                "initial_sha256": e3.base.solution_sha256(initial),
                "initial_cost_cny": result["initial_cost"],
                "search_candidate_cost_cny": result["search_cost"],
                "final_cost_cny": result["cost"],
                "saving_from_initial_cny": result["initial_cost"] - result["cost"],
                "selected_source": result["selected_source"],
                "cross_contractor_customers": cross_customers,
                "cross_contractor_quantity_kg": cross_quantity,
                "used_cv": int(result["breakdown"]["n_veh_cv"]),
                "used_ev": int(result["breakdown"]["n_veh_ev"]),
                "route_pool_records": len(result["records"]),
                "complete_candidate_evaluations": result["run"].stats[
                    "complete_candidate_evaluation_attempts"
                ],
                "elapsed_seconds": result["run"].elapsed_seconds,
                "solution_sha256": solution["solution_sha256"],
                "status": "PASS",
                "violation_count": 0,
            }
        )
        write_rows(raw_path, raw_rows)
        write_progress()

    if include_method_b:
        settlement, diagnostic_trace, theta_one_solution = method_results(
            base, members, coalition_results
        )
    else:
        settlement = method_a_results(base, members, coalition_results)
        diagnostic_trace = []
        theta_one_solution = None
    write_json(output / "settlement_results.json", settlement)
    if diagnostic_trace:
        write_rows(output / "profit_floor_diagnostic_trace.csv", diagnostic_trace)
    if theta_one_solution is not None:
        cost, breakdown, violations = exact_china81_score(theta_one_solution, base)
        write_json(
            output / "method_b_theta_1_solution.json",
            {
                "schema": "resetp.e6-direct-method-b-endpoint.v1",
                "revenue_assignment": REVENUE_ASSIGNMENT,
                "theta": 1.0,
                "objective_cny": cost,
                "solution_sha256": e3.base.solution_sha256(theta_one_solution),
                "breakdown": breakdown,
                "violations": [asdict(item) for item in violations],
                "solution": asdict(theta_one_solution),
            },
        )

    singleton_cost_sum = sum(coalition_results[(member,)]["cost"] for member in members)
    grand = coalition_results[members]
    grand_row = next(row for row in raw_rows if row["coalition"] == "+".join(members))
    grand_cross = int(float(grand_row["cross_contractor_customers"]))
    grand_quantity = float(grand_row["cross_contractor_quantity_kg"])
    monotone_to_singletons = {
        "+".join(group): coalition_results[group]["cost"]
        <= sum(coalition_results[(member,)]["cost"] for member in group) + 1e-7
        for group in groups
    }
    decision = {
        "status": (
            "PASS_E6A_FORMAL_UNIT"
            if evidence_role == "FORMAL_PANEL_UNIT"
            else (
                "PASS_E6A_SMOKE_ONLY"
                if evidence_role == "SMOKE_ONLY"
                else "PASS_E6_DIRECT_15_CREDIBLE_COSTS"
            )
        ),
        "formal_story": (
            "USER_APPROVED_COLLABORATIVE_SURPLUS_ALLOCATION"
            if evidence_role == "FORMAL_PANEL_UNIT"
            else (
                "NOT_FORMAL_EVIDENCE"
                if evidence_role == "SMOKE_ONLY"
                else "AWAITING_USER_DECISION"
            )
        ),
        "multi_member_initial": multi_member_initial,
        "instance_id": instance_id,
        "seed": seed,
        "mapping_sha256": info["mapping_sha256"],
        "coalitions_solved": len(coalition_results),
        "all_coalitions_legal": all(row["status"] == "PASS" for row in raw_rows),
        "all_coalitions_no_worse_than_member_singletons": all(
            monotone_to_singletons.values()
        ),
        "coalition_no_worse_checks": monotone_to_singletons,
        "singleton_cost_sum_cny": singleton_cost_sum,
        "grand_cost_cny": grand["cost"],
        "grand_saving_cny": singleton_cost_sum - grand["cost"],
        "grand_saving_percent": 100.0
        * (singleton_cost_sum - grand["cost"])
        / singleton_cost_sum,
        "grand_cross_contractor_customers": grand_cross,
        "grand_cross_contractor_quantity_kg": grand_quantity,
        "method_A_core_nonempty": settlement["method_A"]["core_nonempty"],
        "method_A_shapley_in_core": settlement["method_A"]["shapley_in_core"],
    }
    if include_method_b:
        decision["method_B_diagnostic"] = settlement["serving_assignment"]["method_B"]
    metadata = {
        "schema": (
            "resetp.e6a-formal-unit.v1"
            if evidence_role == "FORMAL_PANEL_UNIT"
            else (
                "resetp.e6a-smoke.v1"
                if evidence_role == "SMOKE_ONLY"
                else "resetp.e6-direct-15.v2"
            )
        ),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "evidence_role": evidence_role,
        "instance_id": instance_id,
        "seed": seed,
        "iterations_per_view": iterations,
        "archive_candidates_per_view": archive,
        "route_pool_sp_seconds": sp_seconds,
        "cross_site_system_cost_cny": base.prices.cross_site_cost,
        "mapping_sha256": info["mapping_sha256"],
        "label_to_depot": info["label_to_depot"],
        "fleet_caps_by_depot": {
            depot: dict(row) for depot, row in base.fleet_caps_by_depot.items()
        },
        "multi_member_initial": multi_member_initial,
        "incumbent_rule": "retain search result only when legal and strictly cheaper",
        "revenue_assignment": REVENUE_ASSIGNMENT,
        "settlement_methods": (
            ["A_POSTHOC_SHAPLEY_WITH_CORE_CHECK"]
            if not include_method_b
            else ["A_POSTHOC_SHAPLEY", "B_IN_SEARCH_PROFIT_FLOOR"]
        ),
        "hash_audit": audit,
        "protected_hashes": {
            str(path.relative_to(REPO)): sha256(path) for path in PROTECTED
        },
    }
    if include_method_b:
        metadata["profit_floor_diagnostic_theta_step"] = THETA_STEP
    write_rows(raw_path, raw_rows)
    write_json(output / "decision.json", decision)
    write_json(output / "metadata.json", metadata)
    (output / "report.md").write_text(
        report_text(
            decision,
            settlement,
            multi_member_initial,
            seed=seed,
            iterations=iterations,
            archive=archive,
            sp_seconds=sp_seconds,
            evidence_role=evidence_role,
        ),
        encoding="utf-8",
    )
    write_progress(settlement_complete=True)
    artifacts = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
    }
    write_json(
        output / "artifact_hashes.json",
        {"schema": "resetp.artifact-hashes.v1", "artifacts": artifacts},
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--multi-member-initial",
        choices=(MULTI_MEMBER_INITIAL_UNION, MULTI_MEMBER_INITIAL_COMMON),
        default=MULTI_MEMBER_INITIAL_UNION,
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    output = args.output or (
        COMMON_OUTPUT
        if args.multi_member_initial == MULTI_MEMBER_INITIAL_COMMON
        else OUTPUT
    )
    result = (
        preflight_union()
        if args.preflight_only
        else run(output, args.multi_member_initial)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
