#!/usr/bin/env python3
"""Deterministic E7 cross-depot opportunity probe.

This diagnostic does not run the stochastic E7 search.  For stream 1 and the
first two frozen rolling stages, it takes the deterministic owner-fixed future
plan, removes each newly arrived customer in turn, and enumerates every
capacity- and route-time-feasible insertion position on an open route of the
other depot.  Every surviving complete plan is then checked and costed by the
same inherited-asset dynamic scheduler used by E7.

The probe is deliberately separate from the monitored formal runner.  Its
result may justify wiring a dynamic cross-depot neighbourhood, but it is not a
formal cooperation-effect result and cannot authorize a full E7 expansion.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as base
from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as gate
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
)
from setp_solver.solution import Solution


OUT = ROOT / "baselines/e7_dynamic/e7_cross_depot_opportunity_probe_20260715"
CONDITIONS = ("geographic", "historical_mixed")
STREAM_SEED = 1
STAGES = (1, 2)
TOL = 1e-6
SOURCE_FILES = (
    Path(__file__).resolve(),
    Path(base.__file__).resolve(),
    Path(gate.__file__).resolve(),
    ROOT / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _stage_context(condition: str, requested_stage: int) -> dict[str, Any]:
    sources, profiles = gate._sources_for_day(condition)
    events, owners, event_path, owner_path = gate._stream_for_condition(
        STREAM_SEED, condition
    )
    batches = base._validated_trigger_batches(STREAM_SEED, events)
    if requested_stage < 1 or requested_stage > len(batches):
        raise ValueError(f"invalid stage {requested_stage}")

    current_solution, current_certificate, _ = gate._initial_plan(
        "full", sources, profiles
    )
    current_instance = sources["bundle"].instance
    inherited_states = None
    inherited_locked_actions = ()
    previous_stage_start = None
    committed_customers: set[str] = set()
    committed_routes: dict[str, Any] = {}

    for stage_index, batch in enumerate(batches[:requested_stage], start=1):
        trigger = float(batch["trigger_time"])
        if stage_index == 1:
            cut = cut_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                trigger_second=trigger,
            )
        else:
            cut = cut_dynamic_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                inherited_asset_states=inherited_states,
                previous_stage_start_second=float(previous_stage_start),
                trigger_second=trigger,
                inherited_locked_charging_actions=inherited_locked_actions,
            )

        locked_ids = [*cut.completed_route_ids, *cut.in_progress_route_ids]
        for route in base.gate._cut_routes(current_solution, locked_ids):
            if route.vehicle_id not in committed_routes:
                committed_customers.update(
                    base.p2.route_customers(route, current_instance)
                )
                committed_routes[route.vehicle_id] = route

        construction = base.gate.build_open_stage(
            base.gate._cut_routes(current_solution, cut.editable_route_ids),
            current_instance,
            batch["events"],
            trigger,
            committed_customers,
            owners,
            sources["prices"],
            stage_index=stage_index,
            isolate_changed_customers=True,
        )
        base._validate_stage_application(construction, batch["events"])
        owner_fixed = base.asset_aware_future_repack_candidate(
            construction,
            owners,
            sources["prices"],
            asset_states=cut.asset_states,
            stage_start_second=trigger,
            allow_cross_depot=False,
        )
        if owner_fixed is None:
            raise RuntimeError("deterministic owner-fixed future plan was not built")
        prepared, certificate, reference_cost = base.exact_candidate(
            owner_fixed, construction, sources, cut, trigger
        )

        if stage_index == requested_stage:
            return {
                "sources": sources,
                "owners": owners,
                "event_path": event_path,
                "owner_path": owner_path,
                "batch": batch,
                "construction": construction,
                "cut": cut,
                "trigger": trigger,
                "owner_fixed": owner_fixed,
                "reference_cost": float(reference_cost),
            }

        inherited_states = cut.asset_states
        inherited_locked_actions = cut.locked_charging_actions
        previous_stage_start = trigger
        current_solution = prepared
        current_certificate = certificate
        current_instance = construction.effective_instance

    raise AssertionError("requested stage was not reached")


def _candidate_without_customer(
    solution: Solution,
    customer_id: str,
    instance: Any,
) -> list[Any]:
    routes = []
    for route in solution.routes:
        sequence = [node_id for node_id in route.node_sequence if node_id != customer_id]
        candidate = replace(route, node_sequence=sequence)
        if base.p2.route_customers(candidate, instance):
            routes.append(candidate)
    return routes


def _probe_customer(task: tuple[str, int, str]) -> dict[str, Any]:
    condition, stage_index, customer_id = task
    context = _stage_context(condition, stage_index)
    sources = context["sources"]
    owners = context["owners"]
    construction = context["construction"]
    instance = construction.effective_instance
    reference = context["owner_fixed"]
    reference_cost = float(context["reference_cost"])
    owner = owners[customer_id]

    containing = [
        route
        for route in reference.routes
        if customer_id in base.p2.route_customers(route, instance)
    ]
    if len(containing) != 1:
        raise RuntimeError(
            f"{customer_id} occurs in {len(containing)} owner-fixed routes"
        )
    source_route = containing[0]
    base_routes = _candidate_without_customer(reference, customer_id, instance)
    expected_customers = sorted(
        customer
        for route in reference.routes
        for customer in base.p2.route_customers(route, instance)
    )

    counts: Counter[str] = Counter()
    exact_failures: Counter[str] = Counter()
    feasible: list[dict[str, Any]] = []
    for route_index, route in enumerate(base_routes):
        if route.home_depot_id == owner:
            continue
        for insert_at in range(1, len(route.node_sequence)):
            counts["opposite_positions"] += 1
            sequence = list(route.node_sequence)
            sequence.insert(insert_at, customer_id)
            changed = replace(route, node_sequence=sequence)
            if (
                base.gate._route_load(changed, instance)
                > float(sources["prices"].Q_capacity) + TOL
            ):
                counts["capacity_rejected"] += 1
                continue
            try:
                base.gate.route_timing(changed, instance, sources["prices"])
            except ValueError as exc:
                counts["route_time_rejected"] += 1
                exact_failures[f"route_time:{exc}"] += 1
                continue

            counts["static_feasible"] += 1
            routes = list(base_routes)
            routes[route_index] = changed
            candidate_customers = sorted(
                customer
                for candidate_route in routes
                for customer in base.p2.route_customers(candidate_route, instance)
            )
            if candidate_customers != expected_customers:
                raise RuntimeError("candidate customer accounting changed")
            candidate = Solution(
                routes=routes,
                charging_actions=[],
                cross_site_services=base.p2.annotate_cross_site(
                    routes, instance, owners
                ),
            )
            try:
                prepared, _certificate, cost = base.exact_candidate(
                    candidate,
                    construction,
                    sources,
                    context["cut"],
                    float(context["trigger"]),
                )
            except (RuntimeError, ValueError) as exc:
                counts["dynamic_rejected"] += 1
                exact_failures[f"{type(exc).__name__}:{exc}"] += 1
                continue

            cross_ids = base._cross_site_ids_for_routes(
                prepared.routes, instance, owners
            )
            if customer_id not in cross_ids:
                raise RuntimeError("exactly checked candidate lost the intended cross service")
            counts["dynamic_feasible"] += 1
            feasible.append(
                {
                    "cost": float(cost),
                    "target_depot": route.home_depot_id,
                    "target_route_id": route.vehicle_id,
                    "insert_position": insert_at,
                    "cross_customer_count": len(cross_ids),
                }
            )

    best = min(
        feasible,
        key=lambda row: (
            row["cost"],
            row["target_depot"],
            row["target_route_id"],
            row["insert_position"],
        ),
        default=None,
    )
    best_cost = float(best["cost"]) if best is not None else math.nan
    return {
        "responsibility_condition": condition,
        "stream_seed": STREAM_SEED,
        "stage": stage_index,
        "customer_id": customer_id,
        "owner_depot_id": owner,
        "source_route_id": source_route.vehicle_id,
        "source_depot_id": source_route.home_depot_id,
        "reference_future_cost": reference_cost,
        "opposite_position_count": counts["opposite_positions"],
        "capacity_rejected_count": counts["capacity_rejected"],
        "route_time_rejected_count": counts["route_time_rejected"],
        "static_feasible_position_count": counts["static_feasible"],
        "dynamic_rejected_count": counts["dynamic_rejected"],
        "dynamic_feasible_count": counts["dynamic_feasible"],
        "best_cross_future_cost": "" if best is None else best_cost,
        "best_cross_saving_amount": (
            "" if best is None else reference_cost - best_cost
        ),
        "best_cross_saving_pct": (
            "" if best is None else 100.0 * (reference_cost - best_cost) / reference_cost
        ),
        "best_target_depot_id": "" if best is None else best["target_depot"],
        "best_target_route_id": "" if best is None else best["target_route_id"],
        "best_insert_position": "" if best is None else best["insert_position"],
        "best_cross_customer_count": (
            "" if best is None else best["cross_customer_count"]
        ),
        "failure_reasons_json": json.dumps(
            dict(exact_failures), ensure_ascii=False, sort_keys=True
        ),
        "event_sha256": sha256(context["event_path"]),
        "owner_sha256": sha256(context["owner_path"]),
    }


def _artifact_hashes() -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }


def main() -> int:
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    if args.workers <= 0:
        raise ValueError("workers must be positive")
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)

    tasks: list[tuple[str, int, str]] = []
    for condition in CONDITIONS:
        events, _owners, _event_path, _owner_path = gate._stream_for_condition(
            STREAM_SEED, condition
        )
        batches = base._validated_trigger_batches(STREAM_SEED, events)
        for stage_index in STAGES:
            added = sorted(
                event.customer_id
                for event in batches[stage_index - 1]["events"]
                if event.event_type.lower() == "add"
            )
            tasks.extend((condition, stage_index, customer_id) for customer_id in added)

    with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as executor:
        rows = list(executor.map(_probe_customer, tasks))
    rows.sort(
        key=lambda row: (
            row["responsibility_condition"],
            int(row["stage"]),
            row["customer_id"],
        )
    )
    write_csv(OUT / "raw_runs.csv", rows)

    by_condition: dict[str, dict[str, Any]] = {}
    by_cell: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        selected = [row for row in rows if row["responsibility_condition"] == condition]
        by_condition[condition] = {
            "new_customer_count": len(selected),
            "dynamic_feasible_count": sum(
                int(row["dynamic_feasible_count"]) for row in selected
            ),
            "customers_with_feasible_cross_position": sum(
                int(row["dynamic_feasible_count"]) > 0 for row in selected
            ),
            "customers_with_cost_improving_cross_position": sum(
                row["best_cross_saving_pct"] != ""
                and float(row["best_cross_saving_pct"]) > TOL
                for row in selected
            ),
        }
        for stage_index in STAGES:
            cell = [row for row in selected if int(row["stage"]) == stage_index]
            key = f"{condition}__stage{stage_index}"
            by_cell[key] = {
                "new_customer_count": len(cell),
                "dynamic_feasible_count": sum(
                    int(row["dynamic_feasible_count"]) for row in cell
                ),
                "best_cross_saving_pct": max(
                    (
                        float(row["best_cross_saving_pct"])
                        for row in cell
                        if row["best_cross_saving_pct"] != ""
                    ),
                    default=None,
                ),
            }

    feasibility_by_condition = {
        condition: values["dynamic_feasible_count"] > 0
        for condition, values in by_condition.items()
    }
    headroom_by_condition = {
        condition: values["customers_with_cost_improving_cross_position"] > 0
        for condition, values in by_condition.items()
    }
    failures = []
    if not all(feasibility_by_condition.values()):
        failures.append("at least one responsibility condition has no exact-feasible cross insertion")
    verdict = (
        "E7_NEW_ORDER_CROSS_OPPORTUNITY_PRESENT"
        if not failures
        else "E7_NEW_ORDER_CROSS_OPPORTUNITY_NOT_ESTABLISHED"
    )
    decision = {
        "verdict": verdict,
        "formal_expansion_allowed": False,
        "search_runner_patch_allowed": not failures,
        "specialist_operator_evidence_by_condition": headroom_by_condition,
        "failures": failures,
        "checks": {
            "responsibility_conditions": list(CONDITIONS),
            "stream_seed": STREAM_SEED,
            "stages": list(STAGES),
            "new_customer_count": len(rows),
            "opposite_position_count": sum(
                int(row["opposite_position_count"]) for row in rows
            ),
            "static_feasible_position_count": sum(
                int(row["static_feasible_position_count"]) for row in rows
            ),
            "dynamic_feasible_count": sum(
                int(row["dynamic_feasible_count"]) for row in rows
            ),
            "by_condition": by_condition,
            "by_condition_stage": by_cell,
        },
        "interpretation_guard": (
            "This is a deterministic local-opportunity diagnostic. It does not estimate "
            "the cooperation effect and does not authorize a formal E7 batch."
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "contract_id": "E7_NEW_ORDER_CROSS_OPPORTUNITY_V1",
            "git_head": git_head(),
            "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES},
            "workers": min(args.workers, len(tasks)),
            "selection_rule": (
                "stream 1, frozen stages 1-2, both preregistered responsibility "
                "conditions, all add events, all opposite-depot open-route insertion positions"
            ),
            "reference": (
                "deterministic owner-fixed asset-aware future plan; no stochastic search"
            ),
        },
    )
    (OUT / "report.md").write_text(
        "# E7 新订单跨场机会确定性检查\n\n"
        f"- 判定：`{verdict}`\n"
        f"- 新增订单：{len(rows)} 个；另一车场的开放路线插入位置："
        f"{decision['checks']['opposite_position_count']} 个。\n"
        f"- 通过载重和单路线时间检查："
        f"{decision['checks']['static_feasible_position_count']} 个；再通过完整实体车连续排班："
        f"{decision['checks']['dynamic_feasible_count']} 个。\n"
        "- 边界：本检查只回答‘搜索是否有可挖的局部机会’，不回答‘合作平均节省多少’。\n",
        encoding="utf-8",
    )
    write_json(OUT / "artifact_hashes.json", _artifact_hashes())
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
