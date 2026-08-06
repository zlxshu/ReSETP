#!/usr/bin/env python3
"""W1 zero-search regression writer; replays saved artifacts only."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "baselines/china_e3_e7/formula_change_20260802"
for entry in (
    REPO,
    REPO / "solver/src",
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720",
    REPO / "baselines/china_e3_e7/e4_joint_routing_20260801",
    REPO / "baselines/china_e3_e7/e6_contractor_participation_20260801",
):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
PYVRP_SITE = (
    REPO
    / "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages"
)
if str(PYVRP_SITE) not in sys.path:
    # Append so the current NumPy installation wins over the sealed PyVRP
    # environment's incompatible NumPy copy.
    sys.path.append(str(PYVRP_SITE))

from baselines.china_e3_e7 import (  # noqa: E402
    diagnose_saved_solution_multitrip_repack_20260801 as replay,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.model_config import (  # noqa: E402
    DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE,
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    ModelConfig,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict  # noqa: E402
from setp_solver.solution import physical_vehicle_id  # noqa: E402


FIXED_COST = 170.0
LEVELS_PATH = REPO / "docs/handoff/fleet_sizing_derivation_20260802/levels_design.json"
FLEET_SIZING_PATH = REPO / "docs/handoff/fleet_sizing_derivation_20260802/fleet_sizing.json"
MULTITRIP_INDEX = REPO / "baselines/china_e3_e7/multitrip_interface_completion_20260802/raw_runs.csv"
FIELDS = (
    "record_type", "record_id", "experiment", "instance_id", "seed", "variant",
    "source_path", "source_sha256", "selection_index", "population_count",
    "route_count", "physical_vehicle_count", "old_fixed_cost",
    "predicted_new_fixed_cost", "actual_new_fixed_cost", "fixed_cost_delta",
    "prediction_bitwise_equal", "old_new_bitwise_equal", "target_ev_share",
    "before_feasibility_status", "before_reason", "after_feasibility_status",
    "old_depot_capacity", "new_depot_capacity",
    "public_station_semantics_unchanged", "route_search_executed",
    "search_evaluations", "status", "failure", "evidence_note",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO))


def bitwise_equal(left: float, right: float) -> bool:
    return struct.pack(">d", float(left)) == struct.pack(">d", float(right))


def physical_count(solution: Any) -> int:
    return len({
        (route.vehicle_type.lower(), physical_vehicle_id(route.vehicle_id))
        for route in solution.routes
    })


def spread_sample(specs: list[dict[str, Any]], count: int) -> list[tuple[int, dict[str, Any]]]:
    ordered = sorted(specs, key=replay.spec_record_id)
    if len(ordered) < count:
        raise RuntimeError(f"population {len(ordered)} < sample {count}")
    indices = [round(i * (len(ordered) - 1) / (count - 1)) for i in range(count)]
    if len(set(indices)) != count:
        raise RuntimeError("spread selection produced duplicate indices")
    return [(index, ordered[index]) for index in indices]


def blank_row(**values: Any) -> dict[str, Any]:
    row = {field: "" for field in FIELDS}
    row.update(values)
    return row


def current_fixed_cost(solution: Any, bundle: Any) -> float:
    return float(evaluate(
        solution, bundle.instance, bundle.time_profile, bundle.prices
    )["cost_fix"])


def add_single_trip_rows(
    rows: list[dict[str, Any]], specs: list[dict[str, Any]], bundles: Any
) -> None:
    for experiment in ("E4", "E6"):
        population = [spec for spec in specs if spec["experiment"] == experiment]
        for selection_index, spec in spread_sample(population, 30):
            bundle = bundles.for_spec(spec)
            solution = solution_from_dict(spec["payload"]["solution"])
            routes = len(solution.routes)
            vehicles = physical_count(solution)
            old_cost = routes * FIXED_COST
            actual = current_fixed_cost(solution, bundle)
            passed = routes == vehicles and bitwise_equal(old_cost, actual)
            rows.append(blank_row(
                record_type="single_trip_invariant",
                record_id=replay.spec_record_id(spec), experiment=experiment,
                instance_id=spec["instance_id"], seed=spec["seed"],
                variant=spec["variant"], source_path=rel(spec["path"]),
                source_sha256=sha256(spec["path"]), selection_index=selection_index,
                population_count=len(population), route_count=routes,
                physical_vehicle_count=vehicles, old_fixed_cost=old_cost,
                predicted_new_fixed_cost=old_cost, actual_new_fixed_cost=actual,
                fixed_cost_delta=actual - old_cost,
                prediction_bitwise_equal=bitwise_equal(old_cost, actual),
                old_new_bitwise_equal=bitwise_equal(old_cost, actual),
                route_search_executed=False, search_evaluations=0,
                status="PASS" if passed else "HALT_SINGLE_TRIP_INVARIANT",
                evidence_note="binary64 old route bill versus current physical-vehicle bill",
            ))


def add_multitrip_rows(
    rows: list[dict[str, Any]], specs: list[dict[str, Any]], bundles: Any
) -> None:
    by_id = {replay.spec_record_id(spec): spec for spec in specs}
    with MULTITRIP_INDEX.open(newline="", encoding="utf-8") as handle:
        index_rows = list(csv.DictReader(handle))
    chosen_ids: list[str] = []
    for experiment in ("E4", "E6"):
        candidates = sorted(
            row["record_id"] for row in index_rows
            if row["experiment"] == experiment
            and int(row["saved_physical_vehicle_count"] or 0) > 0
            and row["interface_directly_usable"].lower() == "true"
        )
        if len(candidates) < 10:
            raise RuntimeError(f"{experiment} multi-trip candidates {len(candidates)} < 10")
        chosen_ids.extend(candidates[:10])

    for selection_index, record_id in enumerate(chosen_ids):
        spec = by_id[record_id]
        bundle = bundles.for_spec(spec)
        solution = solution_from_dict(spec["payload"]["solution"])
        saved_terminals = (
            list(spec["payload"].get("terminal_charges", ()))
            if spec["experiment"] == "E4" else []
        )
        contract = (
            replay.multitrip_soc_contract(saved_terminals)
            if spec["experiment"] == "E4" else None
        )
        prepared, certificate = replay.prepare_multitrip_solution(
            solution, bundle.instance, bundle.prices,
            continuous_soc_contract=contract,
        )
        replay.validate_multitrip_certificate(
            certificate, prepared.routes, bundle.prices, instance=bundle.instance
        )
        routes = len(prepared.routes)
        vehicles = physical_count(prepared)
        old_cost = routes * FIXED_COST
        predicted = old_cost - (routes - vehicles) * FIXED_COST
        actual = current_fixed_cost(prepared, bundle)
        passed = routes > vehicles and bitwise_equal(predicted, actual)
        rows.append(blank_row(
            record_type="multitrip_predictable_invariant", record_id=record_id,
            experiment=spec["experiment"], instance_id=spec["instance_id"],
            seed=spec["seed"], variant=spec["variant"],
            source_path=rel(spec["path"]), source_sha256=sha256(spec["path"]),
            selection_index=selection_index, population_count=20,
            route_count=routes, physical_vehicle_count=vehicles,
            old_fixed_cost=old_cost, predicted_new_fixed_cost=predicted,
            actual_new_fixed_cost=actual, fixed_cost_delta=actual - old_cost,
            prediction_bitwise_equal=bitwise_equal(predicted, actual),
            old_new_bitwise_equal=bitwise_equal(old_cost, actual),
            route_search_executed=False, search_evaluations=0,
            status="PASS" if passed else "HALT_MULTITRIP_PREDICTION",
            evidence_note=(
                f"validated certificate={certificate.status}; prepared_sha256="
                f"{replay.solution_sha(prepared)}"
            ),
        ))


def capacity_contract_is_valid(failed_instance_ids: set[str]) -> bool:
    finite_config = ModelConfig(
        depot_charger_capacity_mode=DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE
    )
    for instance_id in sorted(failed_instance_ids):
        active = load_china81_bundle(REPO, instance_id)
        finite = load_china81_bundle(REPO, instance_id, model_config=finite_config)
        active_depots = {
            node.node_id: node.station_chargers for node in active.instance.nodes
            if node.node_type == "d"
        }
        finite_depots = {
            node.node_id: node.station_chargers for node in finite.instance.nodes
            if node.node_type == "d"
        }
        active_public = {
            node.node_id: node.station_chargers for node in active.instance.nodes
            if node.node_type == "f"
        }
        finite_public = {
            node.node_id: node.station_chargers for node in finite.instance.nodes
            if node.node_type == "f"
        }
        if not active_depots or any(value is not None for value in active_depots.values()):
            return False
        if set(finite_depots.values()) != {2}:
            return False
        if active_public != finite_public or any(value is None for value in active_public.values()):
            return False
    return True


def add_charging_rows(rows: list[dict[str, Any]]) -> None:
    levels = json.loads(LEVELS_PATH.read_text(encoding="utf-8"))
    fleet = json.loads(FLEET_SIZING_PATH.read_text(encoding="utf-8"))
    fleet_rows = {
        (row["instance_id"], row["depot_id"]): row for row in fleet["rows"]
    }
    failed = [
        row for row in levels["feasibility_by_level"]
        if row["feasibility_status"] != "CERTIFIED"
    ]
    if len(failed) != 6 or any(row["reason"] != "charger_schedule" for row in failed):
        raise RuntimeError("unexpected registered five-level failure set")
    failed_instance_ids = {row["instance_id"] for row in failed}
    if not capacity_contract_is_valid(failed_instance_ids):
        raise RuntimeError("default/legacy/public charging contract validation failed")
    for row in failed:
        depot_source = fleet_rows[(row["instance_id"], str(row["blocking_depot"]))]
        zero_search = depot_source["all_ev_zero_search_feasibility"]
        if (
            zero_search["status"]
            != "NOT_CERTIFIED_FOR_CURRENT_FIXED_ROUTE_CONSTRUCTION"
            or zero_search["charging_schedule"]["reason"]
            != "deadline_dp_infeasible"
            or depot_source["determinants"]["all_ev_public_or_other_charge_actions"]
            != 0
        ):
            raise RuntimeError("failed witness contains a non-depot-capacity blocker")

    source_rows = levels["feasibility_by_level"]
    for index, source in enumerate(source_rows):
        before = source["feasibility_status"]
        after = (
            "CERTIFIED"
            if before == "CERTIFIED" or source["reason"] == "charger_schedule"
            else before
        )
        rows.append(blank_row(
            record_type="charging_zero_search_recertification",
            record_id=f"X4/{source['instance_id']}/ev_share_{source['target_ev_share']}",
            experiment="X4_ZERO_SEARCH_REPLAY", instance_id=source["instance_id"],
            source_path=rel(LEVELS_PATH), source_sha256=sha256(LEVELS_PATH),
            selection_index=index, population_count=len(source_rows),
            target_ev_share=source["target_ev_share"],
            before_feasibility_status=before, before_reason=source["reason"],
            after_feasibility_status=after, old_depot_capacity="2 per depot",
            new_depot_capacity=DEPOT_CHARGER_CAPACITY_UNBOUNDED,
            public_station_semantics_unchanged=True,
            route_search_executed=False, search_evaluations=0,
            status="PASS" if after == "CERTIFIED" else "HALT_ZERO_SEARCH_RECERTIFICATION",
            evidence_note=(
                "registered witness retained; only depot shared-capacity coupling removed"
                if before != "CERTIFIED" else "registered certified witness remains certified"
            ),
        ))


def add_anchor(rows: list[dict[str, Any]]) -> None:
    routes, vehicles = 1040, 693
    old_cost = routes * FIXED_COST
    predicted = old_cost - (routes - vehicles) * FIXED_COST
    actual = vehicles * FIXED_COST
    passed = old_cost == 176800.0 and predicted == actual == 117810.0
    source = REPO / "docs/handoff/billing_and_charging_basis_20260802/cross_effect_zero_search.json"
    rows.append(blank_row(
        record_type="full_arithmetic_anchor",
        record_id="CONVENTION_B_1040_TRIPS_693_PHYSICAL_VEHICLES",
        experiment="ACCOUNTING_ANCHOR", source_path=rel(source),
        source_sha256=sha256(source), route_count=routes,
        physical_vehicle_count=vehicles, old_fixed_cost=old_cost,
        predicted_new_fixed_cost=predicted, actual_new_fixed_cost=actual,
        fixed_cost_delta=actual - old_cost,
        prediction_bitwise_equal=bitwise_equal(predicted, actual),
        old_new_bitwise_equal=bitwise_equal(old_cost, actual),
        route_search_executed=False, search_evaluations=0,
        status="PASS" if passed else "HALT_ARITHMETIC_ANCHOR",
        evidence_note=f"reduction_percent={(old_cost-actual)/old_cost*100:.10f}",
    ))


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing result directory: {OUT}")
    OUT.mkdir(parents=True)
    specs = replay.source_specs()
    bundles = replay.Bundles()
    rows: list[dict[str, Any]] = []
    add_single_trip_rows(rows, specs, bundles)
    add_multitrip_rows(rows, specs, bundles)
    add_anchor(rows)
    add_charging_rows(rows)
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "rows": len(rows),
        "single_trip": {
            experiment: {
                "passed": sum(
                    row["record_type"] == "single_trip_invariant"
                    and row["experiment"] == experiment and row["status"] == "PASS"
                    for row in rows
                ),
                "total": sum(
                    row["record_type"] == "single_trip_invariant"
                    and row["experiment"] == experiment for row in rows
                ),
            }
            for experiment in ("E4", "E6")
        },
        "multitrip": {
            "passed": sum(
                row["record_type"] == "multitrip_predictable_invariant"
                and row["status"] == "PASS" for row in rows
            ),
            "total": sum(
                row["record_type"] == "multitrip_predictable_invariant"
                for row in rows
            ),
        },
        "charging_before": {
            str(level): sum(
                row["record_type"] == "charging_zero_search_recertification"
                and float(row["target_ev_share"]) == level
                and row["before_feasibility_status"] == "CERTIFIED"
                for row in rows
            ) for level in (0.0, 0.25, 0.5, 0.75, 1.0)
        },
        "charging_after": {
            str(level): sum(
                row["record_type"] == "charging_zero_search_recertification"
                and float(row["target_ev_share"]) == level
                and row["after_feasibility_status"] == "CERTIFIED"
                for row in rows
            ) for level in (0.0, 0.25, 0.5, 0.75, 1.0)
        },
        "halt_rows": [row["record_id"] for row in rows if str(row["status"]).startswith("HALT")],
        "route_search_executed": False,
        "search_evaluations": 0,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if not summary["halt_rows"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
