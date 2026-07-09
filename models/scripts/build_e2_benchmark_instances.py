from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import build_three_shift_instance as three_shift_base
from setp_instance_lab.config import ScenarioConfig
from setp_instance_lab.evrptwmf import pairwise_distances, parse_evrptwmf
from setp_instance_lab.generator import generate_scenario
from setp_instance_lab.io import sha256_file, write_scenario_bundle
from setp_instance_lab.models import Node, Scenario
from setp_instance_lab.validation import validate_scenario
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "models" / "data_bundle"
RAW_ROOT = DATA_ROOT / "raw_instances" / "goeke_uk"
E2_ROOT = DATA_ROOT / "generated_instances" / "e2_benchmark"
SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
THREESHIFT_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)  # 9-step formal ladder (2026-07-09)
DONORS = ("01", "02", "03")
HORIZON_SECONDS = 32_400.0
THREESHIFT_HORIZON_SECONDS = 86_400.0
SHIFT_SECONDS = (0.0, 9.0 * 3600.0, 18.0 * 3600.0)


@dataclass(frozen=True)
class RawMeta:
    base_id: str
    path: Path
    customer_count: int
    depot_count: int
    station_count: int
    num_cv: int
    num_ev: int
    nodes: tuple[Node, ...]


@dataclass(frozen=True)
class CountPlan:
    target: int
    child_counts: tuple[int, int, int]
    predicted_actual: int
    predicted_third_shift_kept: int
    exact_hit: bool


@dataclass
class BuildRow:
    instance_id: str
    category: str
    n_customers_target: int
    n_customers_actual: int
    n_depots: int
    n_stations: int
    num_cv: int
    num_ev: int
    donor_goeke_id: str
    bundle_dir: str
    generator_validation_passed: bool
    duplicate_coordinate_count: int
    three_shift_per_shift_counts: list[int] | None = None
    three_shift_child_bases: list[str] | None = None
    feasible_warmstart_cost: float | None = None
    warmstart_route_count: int | None = None
    warmstart_cv_route_count: int | None = None
    warmstart_ev_route_count: int | None = None
    warmstart_seconds: float | None = None
    violation_count: int | None = None
    status: str = "GENERATED"
    failure_reason: str = ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the E2 69-instance benchmark bundles.")
    parser.add_argument("--output-root", default=str(E2_ROOT))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-warmstart", action="store_true")
    args = parser.parse_args(argv)

    output_root = Path(args.output_root)
    if output_root.exists():
        if not args.overwrite:
            raise SystemExit(f"{output_root} already exists; rerun with --overwrite to rebuild E2 artifacts.")
        shutil.rmtree(output_root)
    for category in ("vanilla", "multidepot", "threeshift"):
        (output_root / category).mkdir(parents=True, exist_ok=True)

    raw_index = _raw_inventory()
    rows: list[BuildRow] = []
    for size in SIZES:
        for donor in DONORS:
            rows.append(_build_vanilla(raw_index, output_root, size, donor))
            rows.append(_build_multidepot(raw_index, output_root, size, donor))
    for size in THREESHIFT_SIZES:
        for donor in DONORS:
            rows.append(_build_threeshift(raw_index, output_root, size, donor))

    if not args.skip_warmstart:
        _validate_warmstarts(rows)
    else:
        for row in rows:
            row.status = "SKIPPED_WARMSTART"

    manifest = _manifest_payload(rows, raw_index, output_root, warmstart_skipped=args.skip_warmstart)
    _write_json(output_root / "e2_benchmark_manifest.json", manifest)
    (output_root / "README.md").write_text(_readme_text(manifest), encoding="utf-8")
    (output_root / "audit.md").write_text(_audit_text(manifest), encoding="utf-8")
    _write_json(output_root / "raw_inventory.json", _raw_inventory_payload(raw_index))

    expected_status = "SKIPPED_WARMSTART" if args.skip_warmstart else "OK"
    failures = [row for row in rows if row.status != expected_status]
    if failures:
        print(json.dumps({"gate": "HALT_E2_INSTANCE_GENERATION", "failures": [row.__dict__ for row in failures]}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"gate": manifest["gate"], "instances": len(rows), "manifest": str(output_root / "e2_benchmark_manifest.json")}, ensure_ascii=False, indent=2))
    return 0


def _raw_inventory() -> dict[str, RawMeta]:
    out: dict[str, RawMeta] = {}
    for size in SIZES:
        for donor in DONORS:
            base_id = f"E-UK{size}_{donor}"
            out[base_id] = _raw_meta(base_id)
    return out


def _raw_meta(base_id: str) -> RawMeta:
    path = RAW_ROOT / f"{base_id}.txt"
    nodes, _ = parse_evrptwmf(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    return RawMeta(
        base_id=base_id,
        path=path,
        customer_count=sum(1 for node in nodes if node.node_type == "c"),
        depot_count=sum(1 for node in nodes if node.node_type == "d"),
        station_count=sum(1 for node in nodes if node.node_type == "f"),
        num_cv=_extract_fleet_value(text, "numPetrolVeh"),
        num_ev=_extract_fleet_value(text, "numElectroVeh"),
        nodes=tuple(nodes),
    )


def _extract_fleet_value(text: str, key: str) -> int:
    marker = f"m {key} /"
    for line in text.splitlines():
        if line.strip().startswith(marker):
            return int(line.split("/", 2)[1])
    raise ValueError(f"Missing fleet field {key}")


def _build_vanilla(raw_index: dict[str, RawMeta], output_root: Path, size: int, donor: str) -> BuildRow:
    base_id = f"E-UK{size}_{donor}"
    meta = raw_index[base_id]
    instance_id = f"e2-vanilla-{size}c-{donor}"
    config = _base_config(
        instance_id,
        meta,
        n_depots=1,
        n_stations=meta.station_count,
        n_customers=meta.customer_count,
        seed=100_000 + size * 10 + int(donor),
        horizon_seconds=HORIZON_SECONDS,
    )
    scenario = generate_scenario(config)
    _assert_exact_vanilla(meta, scenario)
    output_dir = output_root / "vanilla" / instance_id
    _write_bundle(scenario, output_dir, config, {"e2_category": "vanilla", "donor_goeke_id": base_id})
    return _row(instance_id, "vanilla", size, meta.customer_count, meta, output_dir, scenario)


def _build_multidepot(raw_index: dict[str, RawMeta], output_root: Path, size: int, donor: str) -> BuildRow:
    base_id = f"E-UK{size}_{donor}"
    meta = raw_index[base_id]
    instance_id = f"e2-multidepot-{size}c-{donor}"
    config = _base_config(
        instance_id,
        meta,
        n_depots=2,
        n_stations=meta.station_count,
        n_customers=meta.customer_count,
        seed=200_000 + size * 10 + int(donor),
        horizon_seconds=HORIZON_SECONDS,
    )
    scenario = generate_scenario(config)
    _assert_original_depot_preserved(meta, scenario)
    output_dir = output_root / "multidepot" / instance_id
    _write_bundle(scenario, output_dir, config, {"e2_category": "multidepot", "donor_goeke_id": base_id})
    return _row(instance_id, "multidepot", size, meta.customer_count, meta, output_dir, scenario)


def _build_threeshift(raw_index: dict[str, RawMeta], output_root: Path, size: int, donor: str) -> BuildRow:
    child_donors = _rotated_donors(donor)
    child_base_ids = [f"E-UK{size}_{item}" for item in child_donors]
    metas = [raw_index[base_id] for base_id in child_base_ids]
    plan = _choose_child_counts(size, metas[2])
    instance_id = f"e2-threeshift-{size}c-{donor}"
    child_rows: list[dict[str, Any]] = []
    facility_layout: dict[str, Node] | None = None

    for idx, (meta, child_count, shift_seconds) in enumerate(zip(metas, plan.child_counts, SHIFT_SECONDS, strict=True)):
        config = _base_config(
            f"{instance_id}__shift{idx + 1}_{meta.base_id}_n{child_count}",
            meta,
            n_depots=2,
            n_stations=metas[0].station_count,
            n_customers=child_count,
            seed=300_000 + size * 100 + int(donor) * 10 + idx,
            horizon_seconds=HORIZON_SECONDS,
        )
        raw_scenario = generate_scenario(config)
        if facility_layout is None:
            facility_layout = {
                node.node_id: node
                for node in raw_scenario.nodes
                if node.node_type.lower() in {"d", "f"}
            }
            scenario = raw_scenario
        else:
            scenario = _with_shared_facility_layout(raw_scenario, config, facility_layout, child_rows[0]["scenario_id"])
        child_rows.append(
            {
                "base_id": meta.base_id,
                "scenario_id": config.scenario_id,
                "n_customers": child_count,
                "shift_seconds": shift_seconds,
                "scenario": scenario,
                "validation": scenario.validation,
            }
        )

    assert facility_layout is not None
    scenario, three_shift_manifest = _merge_three_shift(
        instance_id,
        child_rows,
        metas[0],
        plan,
        facility_layout,
    )
    output_dir = output_root / "threeshift" / instance_id
    payload = {
        "e2_category": "threeshift",
        "donor_goeke_id": f"E-UK{size}_{donor}",
        "three_shift_manifest": three_shift_manifest,
    }
    _write_bundle(scenario, output_dir, _three_shift_config(instance_id, metas[0], scenario, len(facility_layout)), payload)
    manifest_path = output_dir / "three_shift_manifest.json"
    _write_json(manifest_path, three_shift_manifest)
    _attach_extra_file_to_manifest(output_dir, "three_shift_manifest_json", manifest_path)
    row = _row(instance_id, "threeshift", size, _customer_count(scenario), metas[0], output_dir, scenario)
    row.three_shift_per_shift_counts = list(plan.child_counts)
    row.three_shift_child_bases = child_base_ids
    return row


def _base_config(
    scenario_id: str,
    meta: RawMeta,
    *,
    n_depots: int,
    n_stations: int,
    n_customers: int,
    seed: int,
    horizon_seconds: float,
) -> ScenarioConfig:
    return ScenarioConfig(
        scenario_id=scenario_id,
        seed=int(seed),
        base_instance_path=str(meta.path),
        n_depots=int(n_depots),
        n_stations=int(n_stations),
        n_customers=int(n_customers),
        num_cv=meta.num_cv,
        num_ev=meta.num_ev,
        coord_mode="empirical",
        demand_mode="empirical",
        time_window_mode="empirical",
        empirical_exact_base=True,
        horizon_start=0.0,
        horizon_end=float(horizon_seconds),
        depot_due_time=float(horizon_seconds),
        carbon_alignment_mode="fixed_utc_anchor",
        carbon_time_anchor_utc=three_shift_base.CARBON_ANCHOR_UTC,
        carbon_profile_path=str(three_shift_base.CARBON_SOURCE),
    )


def _three_shift_config(instance_id: str, meta: RawMeta, scenario: Scenario, facility_count: int) -> ScenarioConfig:
    return ScenarioConfig(
        scenario_id=instance_id,
        seed=400_000 + _customer_count(scenario),
        n_depots=2,
        n_stations=facility_count - 2,
        n_customers=_customer_count(scenario),
        num_cv=meta.num_cv,
        num_ev=meta.num_ev,
        coord_mode="three_shift_merge",
        demand_mode="empirical",
        time_window_mode="empirical_shifted",
        empirical_exact_base=True,
        horizon_start=0.0,
        horizon_end=THREESHIFT_HORIZON_SECONDS,
        depot_due_time=THREESHIFT_HORIZON_SECONDS,
        carbon_alignment_mode="fixed_utc_anchor",
        carbon_time_anchor_utc=three_shift_base.CARBON_ANCHOR_UTC,
        carbon_profile_path=str(three_shift_base.CARBON_SOURCE),
    )


def _write_bundle(scenario: Scenario, output_dir: Path, config: ScenarioConfig, extra_config: dict[str, Any]) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    payload = config.to_dict()
    payload.update(extra_config)
    write_scenario_bundle(scenario, output_dir, config=payload, export_dynamic=False)


def _row(
    instance_id: str,
    category: str,
    target: int,
    actual: int,
    meta: RawMeta,
    output_dir: Path,
    scenario: Scenario,
) -> BuildRow:
    return BuildRow(
        instance_id=instance_id,
        category=category,
        n_customers_target=int(target),
        n_customers_actual=int(actual),
        n_depots=sum(1 for node in scenario.nodes if node.node_type.lower() == "d"),
        n_stations=sum(1 for node in scenario.nodes if node.node_type.lower() == "f"),
        num_cv=meta.num_cv,
        num_ev=meta.num_ev,
        donor_goeke_id=meta.base_id,
        bundle_dir=str(output_dir),
        generator_validation_passed=bool(scenario.validation.get("passed", False)),
        duplicate_coordinate_count=int(scenario.validation.get("duplicate_coordinate_count", 0)),
    )


def _assert_exact_vanilla(meta: RawMeta, scenario: Scenario) -> None:
    _assert_original_depot_preserved(meta, scenario)
    raw_stations = [node for node in meta.nodes if node.node_type == "f"]
    got_stations = [node for node in scenario.nodes if node.node_type == "f"]
    if len(raw_stations) != len(got_stations):
        raise RuntimeError(f"{meta.base_id}: station count changed")
    for raw, got in zip(raw_stations, got_stations, strict=True):
        _assert_node_values(meta.base_id, raw, got, include_demand=False)
    raw_customers = [node for node in meta.nodes if node.node_type == "c"]
    got_customers = [node for node in scenario.nodes if node.node_type == "c"]
    if len(raw_customers) != len(got_customers):
        raise RuntimeError(f"{meta.base_id}: customer count changed")
    for raw, got in zip(raw_customers, got_customers, strict=True):
        _assert_node_values(meta.base_id, raw, got, include_demand=True)


def _assert_original_depot_preserved(meta: RawMeta, scenario: Scenario) -> None:
    raw_depots = [node for node in meta.nodes if node.node_type == "d"]
    got_depots = [node for node in scenario.nodes if node.node_type == "d"]
    if not raw_depots or not got_depots:
        raise RuntimeError(f"{meta.base_id}: missing depot")
    _assert_node_values(meta.base_id, raw_depots[0], got_depots[0], include_demand=False)


def _assert_node_values(base_id: str, raw: Node, got: Node, *, include_demand: bool) -> None:
    checks = [
        ("x", raw.x, got.x),
        ("y", raw.y, got.y),
        ("ready_time", raw.ready_time, got.ready_time),
        ("due_time", raw.due_time, got.due_time),
        ("service_time", raw.service_time, got.service_time),
    ]
    if include_demand:
        checks.append(("demand", raw.demand, got.demand))
    for field, expected, actual in checks:
        if abs(float(expected) - float(actual)) > 1e-6:
            raise RuntimeError(f"{base_id}: {field} changed for raw {raw.node_id}: {expected} != {actual}")


def _rotated_donors(anchor: str) -> tuple[str, str, str]:
    start = DONORS.index(anchor)
    return tuple(DONORS[start:] + DONORS[:start])


def _choose_child_counts(target: int, third_meta: RawMeta) -> CountPlan:
    max_child_n = int(target)
    preferred = max(1, min(max_child_n, round(int(target) / 2.27)))
    exact: list[tuple[tuple[int, int, int, int], tuple[int, int, int], int, int]] = []
    nearest: list[tuple[tuple[int, int, int, int], tuple[int, int, int], int, int]] = []
    for n3 in range(1, max_child_n + 1):
        kept3 = _third_shift_kept_count(third_meta, n3)
        needed = int(target) - kept3
        if 2 <= needed <= 2 * max_child_n:
            n1 = max(1, min(max_child_n, needed // 2))
            n2 = needed - n1
            if n2 > max_child_n:
                n2 = max_child_n
                n1 = needed - n2
            if 1 <= n1 <= max_child_n and 1 <= n2 <= max_child_n:
                score = (abs(n1 - preferred) + abs(n2 - preferred) + abs(n3 - preferred), abs(n1 - n2), abs(n3 - preferred), n3)
                exact.append((score, (n1, n2, n3), int(target), kept3))
        for n1 in (max(1, min(max_child_n, needed // 2)), preferred):
            n1 = max(1, min(max_child_n, int(n1)))
            n2 = max(1, min(max_child_n, int(target) - kept3 - n1))
            predicted = n1 + n2 + kept3
            score = (abs(predicted - int(target)) * 1000 + abs(n1 - preferred) + abs(n2 - preferred) + abs(n3 - preferred), abs(n1 - n2), abs(n3 - preferred), n3)
            nearest.append((score, (n1, n2, n3), predicted, kept3))
    if exact:
        _, counts, predicted, kept3 = min(exact, key=lambda item: item[0])
        return CountPlan(int(target), counts, int(predicted), int(kept3), True)
    _, counts, predicted, kept3 = min(nearest, key=lambda item: item[0])
    return CountPlan(int(target), counts, int(predicted), int(kept3), False)


def _third_shift_kept_count(meta: RawMeta, n_customers: int) -> int:
    customers = [node for node in meta.nodes if node.node_type == "c"][: int(n_customers)]
    return sum(1 for node in customers if float(node.due_time) + SHIFT_SECONDS[2] <= THREESHIFT_HORIZON_SECONDS + 1e-9)


def _with_shared_facility_layout(
    scenario: Scenario,
    config: ScenarioConfig,
    facility_layout: dict[str, Node],
    source_scenario_id: str,
) -> Scenario:
    nodes: list[Node] = []
    for node in scenario.nodes:
        if node.node_type.lower() in {"d", "f"}:
            if node.node_id not in facility_layout:
                raise RuntimeError(f"Facility {node.node_id} missing from shared layout")
            source = facility_layout[node.node_id]
            nodes.append(
                replace(
                    node,
                    x=source.x,
                    y=source.y,
                    ready_time=source.ready_time,
                    due_time=source.due_time,
                    service_time=source.service_time,
                    station_capacity=source.station_capacity,
                    station_chargers=source.station_chargers,
                    charge_power_kw=source.charge_power_kw,
                    carbon_region=source.carbon_region,
                )
            )
        else:
            nodes.append(node)
    matrix = _distance_matrix(nodes)
    out = Scenario(
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        nodes=nodes,
        distance_matrix=matrix,
        depot_scores=scenario.depot_scores,
        station_scores=scenario.station_scores,
        dynamic_events=scenario.dynamic_events,
        metadata={
            **scenario.metadata,
            "facility_layout_source": source_scenario_id,
            "facility_layout_policy": "E2 three-shift children reuse first-shift depots/stations",
        },
    )
    out.validation = validate_scenario(nodes, matrix, config)
    return out


def _merge_three_shift(
    instance_id: str,
    child_rows: list[dict[str, Any]],
    meta: RawMeta,
    plan: CountPlan,
    facility_layout: dict[str, Node],
) -> tuple[Scenario, dict[str, Any]]:
    nodes: list[Node] = []
    for node_id in sorted((node_id for node_id in facility_layout if node_id.startswith("D")), key=_natural_key):
        nodes.append(replace(facility_layout[node_id], ready_time=0.0, due_time=THREESHIFT_HORIZON_SECONDS, service_time=0.0))

    kept_customers: list[dict[str, Any]] = []
    deleted_customers: list[dict[str, Any]] = []
    customer_idx = 1
    for row in child_rows:
        scenario: Scenario = row["scenario"]
        for customer in [node for node in scenario.nodes if node.node_type.lower() == "c"]:
            shifted_ready = float(customer.ready_time) + float(row["shift_seconds"])
            shifted_due = float(customer.due_time) + float(row["shift_seconds"])
            if shifted_due > THREESHIFT_HORIZON_SECONDS + 1e-9:
                deleted_customers.append(
                    {
                        "source_base_id": row["base_id"],
                        "source_scenario_id": row["scenario_id"],
                        "source_node_id": customer.node_id,
                        "shift_seconds": row["shift_seconds"],
                        "shifted_ready_time": shifted_ready,
                        "shifted_due_time": shifted_due,
                        "reason": "shifted_due_time_exceeds_24h",
                    }
                )
                continue
            new_id = f"C{customer_idx:03d}"
            nodes.append(Node(new_id, "c", customer.x, customer.y, customer.demand, shifted_ready, shifted_due, customer.service_time))
            kept_customers.append(
                {
                    "new_node_id": new_id,
                    "source_base_id": row["base_id"],
                    "source_scenario_id": row["scenario_id"],
                    "source_node_id": customer.node_id,
                    "shift_seconds": row["shift_seconds"],
                    "ready_time": customer.ready_time,
                    "due_time": customer.due_time,
                    "shifted_ready_time": shifted_ready,
                    "shifted_due_time": shifted_due,
                }
            )
            customer_idx += 1

    for node_id in sorted((node_id for node_id in facility_layout if node_id.startswith("F")), key=_natural_key):
        nodes.append(replace(facility_layout[node_id], ready_time=0.0, due_time=THREESHIFT_HORIZON_SECONDS, service_time=0.0))

    matrix = _distance_matrix(nodes)
    config = ScenarioConfig(
        scenario_id=instance_id,
        seed=400_000 + len(kept_customers),
        n_depots=2,
        n_stations=sum(1 for node in nodes if node.node_type.lower() == "f"),
        n_customers=len(kept_customers),
        num_cv=meta.num_cv,
        num_ev=meta.num_ev,
        coord_mode="three_shift_merge",
        demand_mode="empirical",
        time_window_mode="empirical_shifted",
        empirical_exact_base=True,
        horizon_start=0.0,
        horizon_end=THREESHIFT_HORIZON_SECONDS,
        depot_due_time=THREESHIFT_HORIZON_SECONDS,
        carbon_alignment_mode="fixed_utc_anchor",
        carbon_time_anchor_utc=three_shift_base.CARBON_ANCHOR_UTC,
        carbon_profile_path=str(three_shift_base.CARBON_SOURCE),
    )
    validation = validate_scenario(nodes, matrix, config)
    manifest = {
        "name": instance_id,
        "build_note": "E2 three-shift merge; customer windows are shifted and only >24h third-shift tail is dropped.",
        "count_plan": {
            "target": plan.target,
            "child_counts": list(plan.child_counts),
            "predicted_actual": plan.predicted_actual,
            "predicted_third_shift_kept": plan.predicted_third_shift_kept,
            "exact_hit": plan.exact_hit,
        },
        "source_children": [
            {
                "source_base_id": row["base_id"],
                "scenario_id": row["scenario_id"],
                "shift_seconds": row["shift_seconds"],
                "n_customers": row["n_customers"],
                "validation": row["validation"],
            }
            for row in child_rows
        ],
        "facility_layout_source": child_rows[0]["scenario_id"],
        "deleted_customers": deleted_customers,
        "deleted_customer_count": len(deleted_customers),
        "kept_customer_count": len(kept_customers),
        "total_demand": sum(float(node.demand) for node in nodes if node.node_type.lower() == "c"),
        "return_deadline_seconds": THREESHIFT_HORIZON_SECONDS,
        "validation": validation,
        "kept_customers": kept_customers,
    }
    scenario = Scenario(
        scenario_id=instance_id,
        seed=config.seed,
        nodes=nodes,
        distance_matrix=matrix,
        depot_scores=child_rows[0]["scenario"].depot_scores,
        station_scores=child_rows[0]["scenario"].station_scores,
        metadata={
            "source": "e2_three_shift_merge",
            "three_shift_manifest": manifest,
            "num_cv": meta.num_cv,
            "num_ev": meta.num_ev,
            "carbon_time_anchor_utc": three_shift_base.CARBON_ANCHOR_UTC,
        },
    )
    scenario.validation = validation
    return scenario, manifest


def _validate_warmstarts(rows: list[BuildRow]) -> None:
    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        started = time.perf_counter()
        print(f"[{idx:02d}/{total}] warmstart {row.instance_id}", file=sys.stderr, flush=True)
        try:
            bundle = load_search_bundle(row.bundle_dir)
            solution = make_shared_initial_solution(bundle)
            violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
            row.violation_count = len(violations)
            if violations:
                row.status = "HALT_WARMSTART_VIOLATIONS"
                row.failure_reason = "; ".join(f"{item.type}:{item.location}:{item.detail}" for item in violations[:8])
                continue
            metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
            row.feasible_warmstart_cost = float(metrics["total_cost"])
            row.warmstart_route_count = len(solution.routes)
            row.warmstart_cv_route_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
            row.warmstart_ev_route_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
            row.status = "OK"
        except Exception as exc:
            row.status = "HALT_WARMSTART_EXCEPTION"
            row.failure_reason = f"{type(exc).__name__}: {exc}"
        finally:
            row.warmstart_seconds = time.perf_counter() - started
            print(
                f"[{idx:02d}/{total}] {row.status} {row.instance_id} "
                f"{row.warmstart_seconds:.3f}s",
                file=sys.stderr,
                flush=True,
            )


def _manifest_payload(
    rows: list[BuildRow],
    raw_index: dict[str, RawMeta],
    output_root: Path,
    *,
    warmstart_skipped: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "setp-e2-benchmark.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator_code_commit": _git("rev-parse", "HEAD"),
        "generator_code_commit_short": _git("rev-parse", "--short", "HEAD"),
        "python_executable": sys.executable,
        "numpy_version": np.__version__,
        "data_root": str(DATA_ROOT),
        "raw_root": str(RAW_ROOT),
        "output_root": str(output_root),
        "carbon_source": str(three_shift_base.CARBON_SOURCE),
        "carbon_anchor_utc": three_shift_base.CARBON_ANCHOR_UTC,
        "categories": {
            "vanilla": "Goeke exact customers, depot, stations; generator-normalized node ids.",
            "multidepot": "Goeke exact customers, depot, stations plus one generated second depot.",
            "threeshift": "Three shifted multidepot children; target count controlled before merge, no post-hoc deletion except >24h shifted tail.",
        },
        "raw_inventory_summary": _raw_inventory_payload(raw_index),
        "instances": [row.__dict__ for row in rows],
        "gate": (
            "SKIPPED_WARMSTART"
            if warmstart_skipped and all(row.status == "SKIPPED_WARMSTART" for row in rows)
            else "OK"
            if all(row.status == "OK" for row in rows)
            else "HALT_E2_INSTANCE_GENERATION"
        ),
    }


def _raw_inventory_payload(raw_index: dict[str, RawMeta]) -> dict[str, Any]:
    by_size: dict[str, list[dict[str, Any]]] = {}
    for meta in raw_index.values():
        size = "".join(ch for ch in meta.base_id.split("_", 1)[0] if ch.isdigit())
        by_size.setdefault(size, []).append(
            {
                "base_id": meta.base_id,
                "customer_count": meta.customer_count,
                "depot_count": meta.depot_count,
                "station_count": meta.station_count,
                "num_cv": meta.num_cv,
                "num_ev": meta.num_ev,
                "path": str(meta.path),
            }
        )
    return {size: sorted(rows, key=lambda row: row["base_id"]) for size, rows in sorted(by_size.items(), key=lambda item: int(item[0]))}


def _readme_text(manifest: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# E2 Benchmark Instances",
            "",
            "This directory contains the E2 69-instance benchmark for formal algorithm comparison.",
            "",
            "- Categories: vanilla, multidepot, threeshift.",
            "- Counts: 27 vanilla + 27 multidepot + 15 threeshift = 69 bundles.",
            "- Scoring protocol: ReSETP UK cost and two-layer carbon accounting; no external BKS is attached.",
            f"- Gate: {manifest['gate']}.",
            f"- Generator commit: {manifest['generator_code_commit_short']}.",
            "",
            "Use `e2_benchmark_manifest.json` as the source of truth for bundle paths, donor Goeke ids, fleet metadata, warm-start cost, and validation status.",
            "",
        ]
    )


def _audit_text(manifest: dict[str, Any]) -> str:
    rows = manifest["instances"]
    ok = sum(1 for row in rows if row["status"] == "OK")
    lines = [
        "# E2 Instance Generation Audit",
        "",
        f"Gate: {manifest['gate']}.",
        f"Generated instances: {len(rows)} total, {ok} warm-start OK.",
        f"Python: `{manifest['python_executable']}`; numpy: `{manifest['numpy_version']}`.",
        f"Generator commit: `{manifest['generator_code_commit']}`.",
        "",
        "## Key facts",
        "",
        "- Vanilla uses `--base-id` semantics with `empirical_exact_base=True` and no `synthetic-only`; this switches coord/demand/time-window modes to empirical and preserves Goeke customer values.",
        "- The generator now preserves exact Goeke depot/station coordinates in exact-base mode. For multidepot, D0 is preserved and only the second depot is generated.",
        "- Raw Goeke files contain duplicate coordinates such as D0/S0 and station/customer overlaps, so generated-scenario validation relaxes the duplicate-coordinate and isolated-share synthetic guards only when `empirical_exact_base=True`.",
        "- Fleet metadata uses `numPetrolVeh`/`numElectroVeh` from each Goeke donor. Current solver feasibility does not use these counts as hard caps; vehicle fixed cost remains the usage pressure.",
        "- Three-shift variants rotate `_01/_02/_03` donors by anchor id, reuse first-shift facilities, shift customer windows by 0h/9h/18h, and drop only customers whose shifted due time exceeds 24h.",
        "",
        "## Counts by category",
        "",
    ]
    for category in ("vanilla", "multidepot", "threeshift"):
        cat_rows = [row for row in rows if row["category"] == category]
        lines.append(f"- {category}: {len(cat_rows)} instances; OK={sum(1 for row in cat_rows if row['status'] == 'OK')}.")
    lines.extend(["", "## Three-shift count plans", ""])
    for row in rows:
        if row["category"] == "threeshift":
            lines.append(
                f"- {row['instance_id']}: target={row['n_customers_target']}, actual={row['n_customers_actual']}, "
                f"child_counts={row['three_shift_per_shift_counts']}, bases={row['three_shift_child_bases']}."
            )
    failures = [row for row in rows if row["status"] != "OK"]
    if failures:
        lines.extend(["", "## HALT failures", ""])
        for row in failures:
            lines.append(f"- {row['instance_id']}: {row['status']} {row['failure_reason']}")
    return "\n".join(lines) + "\n"


def _attach_extra_file_to_manifest(output_dir: Path, key: str, path: Path) -> None:
    manifest_path = output_dir / "scenario_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files", {})[key] = path.name
    manifest.setdefault("hashes", {})[key] = sha256_file(path)
    _write_json(manifest_path, manifest)


def _distance_matrix(nodes: list[Node]) -> np.ndarray:
    return pairwise_distances(np.asarray([(node.x, node.y) for node in nodes], dtype=float))


def _customer_count(scenario: Scenario) -> int:
    return sum(1 for node in scenario.nodes if node.node_type.lower() == "c")


def _natural_key(value: str) -> tuple[str, int]:
    prefix = "".join(ch for ch in value if not ch.isdigit())
    digits = "".join(ch for ch in value if ch.isdigit())
    return prefix, int(digits or 0)


def _write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
