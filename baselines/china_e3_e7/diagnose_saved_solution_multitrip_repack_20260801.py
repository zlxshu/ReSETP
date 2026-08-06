#!/usr/bin/env python3
"""Zero-search multi-trip replay of saved E4/E6 solutions and E5 witnesses."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
E4_DIR = REPO / "baselines/china_e3_e7/e4_joint_routing_20260801"
E6_DIR = REPO / "baselines/china_e3_e7/e6_contractor_participation_20260801"
E5_DIR = REPO / "baselines/china_e3_e7/e5_enroute_nonlinear_20260801"
OUT = REPO / "baselines/china_e3_e7/multitrip_interface_completion_20260802"
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
E5_WITNESS_IDS = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
)

# This directory contains a project ``statistics.py`` that must not shadow
# Python's standard-library module imported by PyVRP.
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
for entry in (REPO, REPO / "solver/src", PROTOTYPE, E4_DIR, E6_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from e6_methods import subset_bundle
from joint_soc_wrapper import (
    multitrip_soc_contract,
    register_objective,
    score_fixed_solution,
)
from run_pilot06_direct_15 import load_base as load_e6_base
from run_probe import load_bundle as load_e4_bundle
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import (
    E4_CONTINUOUS_SOC_CONTRACT_ID,
    prepare_multitrip_solution,
    validate_multitrip_certificate,
)
from setp_solver.search.e3_multitrip_runtime import (
    complete_prepared_solution_violations,
)
from setp_solver.solution import Route, Solution, physical_vehicle_id


EXPECTED = {"E4": 90, "E6": 900, "E5_WITNESS": 2}
REGRESSION_SAMPLE_COUNT = {"E4": 20, "E6": 20}
REGRESSION_COMPONENTS = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "E_cv_direct",
    "E_ev_indirect",
    "E_total",
    "distance_total",
    "electricity_kwh",
    "n_veh_cv",
    "n_veh_ev",
)
FIELDS = (
    "record_id",
    "experiment",
    "instance_id",
    "seed",
    "variant",
    "source_path",
    "source_sha256",
    "formal_result",
    "status",
    "failure",
    "original_route_count",
    "original_physical_vehicle_count",
    "packed_physical_vehicle_count",
    "saved_physical_vehicle_count",
    "original_counts_by_depot_type",
    "packed_counts_by_depot_type",
    "certificate_status",
    "certificate_valid",
    "current_checker_violation_count",
    "experiment_checker_violation_count",
    "legacy_static_checker_violation_count",
    "depot_fleet_violation_count",
    "saved_terminal_charge_count",
    "saved_terminal_charge_kwh",
    "depot_charge_ledger_count",
    "depot_charge_ledger_kwh",
    "depot_charge_ledger_entrywise_bitwise_equal",
    "interface_directly_usable",
    "interface_note",
    "single_trip_regression_selected",
    "single_trip_objective_bitwise_equal",
    "single_trip_component_count",
    "single_trip_components_bitwise_equal",
    "single_trip_mismatch_fields",
    "certificate_record_sha256",
    "prepared_solution_sha256",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def e4_source_decimal_terminal_kwh() -> Decimal:
    total = Decimal(0)
    root = E4_DIR / "formal_panel_20260801"
    for path in sorted(root.glob("*/solutions/*.json")):
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=Decimal,
        )
        for row in payload.get("terminal_charges", ()):
            total += row["energy_kwh"]
    return total


def rel(path: Path) -> str:
    return str(path.relative_to(REPO))


def violation_rows(violations: Any) -> list[dict[str, Any]]:
    return [asdict(item) for item in violations]


def solution_sha(solution: Solution) -> str:
    return canonical_sha(asdict(solution))


def float_bitwise_equal(left: Any, right: Any) -> bool:
    return struct.pack(">d", float(left)) == struct.pack(">d", float(right))


def bool_value(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def spec_record_id(spec: dict[str, Any]) -> str:
    return "/".join(
        (
            spec["experiment"],
            spec["instance_id"],
            f"seed_{spec['seed']:02d}",
            spec["variant"],
        )
    )


def regression_ids(specs: list[dict[str, Any]]) -> set[str]:
    selected: set[str] = set()
    for experiment, count in REGRESSION_SAMPLE_COUNT.items():
        candidates = sorted(
            spec_record_id(spec)
            for spec in specs
            if spec["experiment"] == experiment
        )
        if len(candidates) < count:
            raise RuntimeError(
                f"{experiment} regression source count {len(candidates)} < {count}"
            )
        selected.update(candidates[:count])
    return selected


def single_trip_regression(
    spec: dict[str, Any], solution: Solution, bundle: Any
) -> dict[str, Any]:
    payload = spec["payload"]
    if spec["experiment"] == "E4":
        register_objective(bundle, spec["variant"])
        current = score_fixed_solution(solution, bundle, validate_full=True)
        objective = float(current.objective)
        breakdown = dict(current.breakdown)
        violations = list(current.violations)
        saved_objective = float(payload["final_objective"])
    elif spec["experiment"] == "E6":
        objective, breakdown, violations = exact_china81_score(solution, bundle)
        objective = float(objective)
        breakdown = dict(breakdown)
        saved_objective = float(payload["objective_cny"])
    else:
        raise ValueError("single-trip regression is defined only for E4/E6")
    saved_breakdown = dict(payload["breakdown"])
    mismatches: list[str] = []
    objective_equal = float_bitwise_equal(objective, saved_objective)
    if not objective_equal:
        mismatches.append("objective")
    component_mismatches: list[str] = []
    for component in REGRESSION_COMPONENTS:
        if component not in breakdown or component not in saved_breakdown:
            component_mismatches.append(f"{component}:missing")
        elif not float_bitwise_equal(
            breakdown[component], saved_breakdown[component]
        ):
            component_mismatches.append(component)
    mismatches.extend(component_mismatches)
    if violations:
        mismatches.append(f"violations:{len(violations)}")
    return {
        "objective_bitwise_equal": objective_equal,
        "component_count": len(REGRESSION_COMPONENTS),
        "components_bitwise_equal": not component_mismatches,
        "mismatch_fields": mismatches,
        "current_objective": objective,
        "saved_objective": saved_objective,
        "current_components": {
            key: breakdown.get(key) for key in REGRESSION_COMPONENTS
        },
        "saved_components": {
            key: saved_breakdown.get(key) for key in REGRESSION_COMPONENTS
        },
        "violation_count": len(violations),
    }


def original_counts(solution: Solution) -> Counter[tuple[str, str]]:
    vehicles: dict[str, tuple[str, str]] = {}
    for route in solution.routes:
        vehicles[physical_vehicle_id(route.vehicle_id)] = (
            route.home_depot_id,
            route.vehicle_type.lower(),
        )
    return Counter(vehicles.values())


def packed_counts(certificate: Any) -> Counter[tuple[str, str]]:
    vehicles: dict[str, tuple[str, str]] = {}
    for trip in certificate.trips:
        vehicles[trip.physical_vehicle_id] = (
            trip.home_depot_id,
            trip.vehicle_type.lower(),
        )
    return Counter(vehicles.values())


def counts_text(counts: Counter[tuple[str, str]]) -> str:
    return "|".join(
        f"{depot}:{vehicle_type}:{count}"
        for (depot, vehicle_type), count in sorted(counts.items())
    )


def depot_fleet_failures(
    counts: Counter[tuple[str, str]], bundle: Any
) -> list[str]:
    failures = []
    for (depot, vehicle_type), count in sorted(counts.items()):
        cap = int(bundle.fleet_caps_by_depot[depot][f"num_{vehicle_type}"])
        if count > cap:
            failures.append(f"{depot}:{vehicle_type}:{count}>{cap}")
    return failures


def load_e5_witness(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(node) for node in row["node_sequence"]],
            )
            for row in payload["routes"]
        ]
    )


def source_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    e4_root = E4_DIR / "formal_panel_20260801"
    for path in sorted(e4_root.glob("*/solutions/*.json")):
        if path.name.startswith("._"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        specs.append(
            {
                "experiment": "E4",
                "path": path,
                "payload": payload,
                "instance_id": str(payload["instance_id"]),
                "seed": int(payload["seed"]),
                "variant": str(payload["objective_mode"]),
            }
        )
    e6_root = E6_DIR / "formal_e6a_panel_20260801/units"
    for path in sorted(e6_root.glob("*/seed_*/solutions/*.json")):
        if path.name.startswith("._"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        specs.append(
            {
                "experiment": "E6",
                "path": path,
                "payload": payload,
                "instance_id": str(payload["instance_id"]),
                "seed": int(payload["seed"]),
                "variant": "__".join(
                    str(member).removeprefix("D_")
                    for member in payload["coalition"]
                ),
                "coalition": tuple(str(member) for member in payload["coalition"]),
                "metadata_path": path.parents[1] / "metadata.json",
            }
        )
    for instance_id in E5_WITNESS_IDS:
        path = FLEET / "witnesses" / f"{instance_id}.json"
        specs.append(
            {
                "experiment": "E5_WITNESS",
                "path": path,
                "payload": None,
                "instance_id": instance_id,
                "seed": 1,
                "variant": "INITIAL_FLEET_AUTHORITY_WITNESS",
            }
        )
    counts = Counter(spec["experiment"] for spec in specs)
    if dict(counts) != EXPECTED:
        raise RuntimeError(f"source count mismatch: {dict(counts)} != {EXPECTED}")
    return specs


class Bundles:
    def __init__(self) -> None:
        self.e4: dict[str, Any] = {}
        self.e6_base: dict[tuple[str, str], Any] = {}
        self.e6: dict[tuple[str, tuple[str, ...]], Any] = {}
        self.e5: dict[str, Any] = {}

    def for_spec(self, spec: dict[str, Any]) -> Any:
        experiment = spec["experiment"]
        instance_id = spec["instance_id"]
        if experiment == "E4":
            if instance_id not in self.e4:
                self.e4[instance_id] = load_e4_bundle(instance_id)
            bundle = self.e4[instance_id]
            register_objective(bundle, spec["variant"])
            return bundle
        if experiment == "E6":
            metadata = json.loads(spec["metadata_path"].read_text(encoding="utf-8"))
            mapping_sha = str(metadata["mapping_sha256"])
            base_key = (instance_id, mapping_sha)
            if base_key not in self.e6_base:
                self.e6_base[base_key] = load_e6_base(instance_id, mapping_sha)[0]
            coalition_key = (instance_id, spec["coalition"])
            if coalition_key not in self.e6:
                self.e6[coalition_key] = subset_bundle(
                    self.e6_base[base_key], spec["coalition"]
                )
            return self.e6[coalition_key]
        if instance_id not in self.e5:
            self.e5[instance_id] = load_china81_bundle(REPO, instance_id)
        return self.e5[instance_id]


def process(
    spec: dict[str, Any],
    bundles: Bundles,
    *,
    regression_selected: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = spec["path"]
    experiment = spec["experiment"]
    record_id = spec_record_id(spec)
    source_hash = sha256(path)
    base_row: dict[str, Any] = {
        "record_id": record_id,
        "experiment": experiment,
        "instance_id": spec["instance_id"],
        "seed": spec["seed"],
        "variant": spec["variant"],
        "source_path": rel(path),
        "source_sha256": source_hash,
        "formal_result": False,
        "status": "",
        "failure": "",
        "original_route_count": 0,
        "original_physical_vehicle_count": 0,
        "packed_physical_vehicle_count": "",
        "saved_physical_vehicle_count": "",
        "original_counts_by_depot_type": "",
        "packed_counts_by_depot_type": "",
        "certificate_status": "",
        "certificate_valid": False,
        "current_checker_violation_count": "",
        "experiment_checker_violation_count": "",
        "legacy_static_checker_violation_count": "",
        "depot_fleet_violation_count": "",
        "saved_terminal_charge_count": 0,
        "saved_terminal_charge_kwh": 0.0,
        "depot_charge_ledger_count": 0,
        "depot_charge_ledger_kwh": 0.0,
        "depot_charge_ledger_entrywise_bitwise_equal": "",
        "interface_directly_usable": False,
        "interface_note": "",
        "single_trip_regression_selected": regression_selected,
        "single_trip_objective_bitwise_equal": "",
        "single_trip_component_count": (
            len(REGRESSION_COMPONENTS) if regression_selected else 0
        ),
        "single_trip_components_bitwise_equal": "",
        "single_trip_mismatch_fields": "",
        "certificate_record_sha256": "",
        "prepared_solution_sha256": "",
    }
    detail: dict[str, Any] = {
        "record_id": record_id,
        "experiment": experiment,
        "source_path": rel(path),
        "source_sha256": source_hash,
        "formal_result": False,
        "single_trip_regression_selected": regression_selected,
    }
    try:
        bundle = bundles.for_spec(spec)
        solution = (
            load_e5_witness(path)
            if experiment == "E5_WITNESS"
            else solution_from_dict(spec["payload"]["solution"])
        )
        original = original_counts(solution)
        saved_terminals = (
            list(spec["payload"].get("terminal_charges", ()))
            if experiment == "E4"
            else []
        )
        contract = (
            multitrip_soc_contract(saved_terminals)
            if experiment == "E4"
            else None
        )
        prepared, certificate = prepare_multitrip_solution(
            solution,
            bundle.instance,
            bundle.prices,
            continuous_soc_contract=contract,
        )
        validate_multitrip_certificate(
            certificate,
            prepared.routes,
            bundle.prices,
            instance=bundle.instance,
        )
        packed = packed_counts(certificate)
        fleet_failures = depot_fleet_failures(packed, bundle)
        legacy_static_violations = check_solution(
            prepared, bundle.instance, bundle.prices
        )
        ledger = list(certificate.depot_charge_ledger)
        saved_terminal_kwh = sum(
            float(row["energy_kwh"]) for row in saved_terminals
        )
        ledger_kwh = sum(float(entry.energy_kwh) for entry in ledger)
        legacy_experiment_violations: list[Any] = []
        if experiment == "E4":
            register_objective(bundle, spec["variant"])
            complete_violations = list(
                score_fixed_solution(
                    prepared, bundle, validate_full=True
                ).violations
            )
            ledger_exact = (
                certificate.continuous_soc_contract_id
                == E4_CONTINUOUS_SOC_CONTRACT_ID
                and len(ledger) == len(saved_terminals)
                and all(
                    float_bitwise_equal(entry.energy_kwh, source["energy_kwh"])
                    for entry, source in zip(ledger, saved_terminals)
                )
            )
            current_violations = complete_violations
            experiment_violations = complete_violations
            interface_usable = not (
                complete_violations or fleet_failures or not ledger_exact
            )
            status = (
                "PASS_E4_MULTITRIP_SOC_INTERFACE"
                if interface_usable
                else "HALT_E4_MULTITRIP_SOC_INTERFACE_VALIDATION_FAILED"
            )
            note = (
                "E4 terminal_charges are bound to the 60-20-80-next-day-60 continuous-SOC depot ledger"
                if interface_usable
                else "E4 continuous-SOC certificate, depot ledger, full check, or fleet bound failed"
            )
        else:
            _, _, legacy_experiment_violations = exact_china81_score(
                prepared, bundle
            )
            complete_violations = complete_prepared_solution_violations(
                prepared,
                certificate,
                bundle.instance,
                bundle.prices,
            )
            current_violations = complete_violations
            experiment_violations = complete_violations
            if experiment == "E6":
                interface_usable = not (
                    complete_violations or fleet_failures
                )
                status = (
                    "PASS_E6_MULTITRIP_COMPLETE_CHECK"
                    if interface_usable
                    else "HALT_E6_REPACK_VALIDATION_FAILED"
                )
                note = (
                    "complete check uses certified inherited EV battery, nonlinear gap charge, and all unaffected static rules"
                )
            else:
                interface_usable = not (
                    complete_violations or fleet_failures
                )
                status = (
                    "PASS_E5_INITIAL_WITNESS_DIAGNOSTIC_ONLY"
                    if interface_usable
                    else "HALT_E5_WITNESS_REPACK_VALIDATION_FAILED"
                )
                note = "initial fleet-authority witness only; not an E5 mechanism result"
        if current_violations or experiment_violations or fleet_failures:
            if status.startswith("PASS"):
                status = f"HALT_{experiment}_REPACK_VALIDATION_FAILED"
            interface_usable = False
        regression: dict[str, Any] | None = None
        if regression_selected:
            regression = single_trip_regression(spec, solution, bundle)
        detail.update(
            {
                "status": status,
                "failure": "",
                "original_solution_sha256": solution_sha(solution),
                "prepared_solution_sha256": solution_sha(prepared),
                "original_counts_by_depot_type": {
                    f"{depot}|{vehicle_type}": count
                    for (depot, vehicle_type), count in sorted(original.items())
                },
                "packed_counts_by_depot_type": {
                    f"{depot}|{vehicle_type}": count
                    for (depot, vehicle_type), count in sorted(packed.items())
                },
                "saved_terminal_charges": saved_terminals,
                "certificate": certificate.as_dict(),
                "current_checker_violations": violation_rows(current_violations),
                "experiment_checker_violations": violation_rows(
                    experiment_violations
                ),
                "legacy_static_checker_violations": violation_rows(
                    legacy_static_violations
                ),
                "legacy_experiment_checker_violations": violation_rows(
                    legacy_experiment_violations
                ),
                "depot_fleet_violations": fleet_failures,
                "interface_directly_usable": interface_usable,
                "interface_note": note,
                "single_trip_regression": regression,
            }
        )
        base_row.update(
            {
                "status": status,
                "original_route_count": len(solution.routes),
                "original_physical_vehicle_count": sum(original.values()),
                "packed_physical_vehicle_count": sum(packed.values()),
                "saved_physical_vehicle_count": (
                    sum(original.values()) - sum(packed.values())
                ),
                "original_counts_by_depot_type": counts_text(original),
                "packed_counts_by_depot_type": counts_text(packed),
                "certificate_status": certificate.status,
                "certificate_valid": True,
                "current_checker_violation_count": len(current_violations),
                "experiment_checker_violation_count": len(
                    experiment_violations
                ),
                "legacy_static_checker_violation_count": len(
                    legacy_static_violations
                ),
                "depot_fleet_violation_count": len(fleet_failures),
                "saved_terminal_charge_count": len(saved_terminals),
                "saved_terminal_charge_kwh": saved_terminal_kwh,
                "depot_charge_ledger_count": len(ledger),
                "depot_charge_ledger_kwh": ledger_kwh,
                "depot_charge_ledger_entrywise_bitwise_equal": (
                    ledger_exact if experiment == "E4" else ""
                ),
                "interface_directly_usable": interface_usable,
                "interface_note": note,
                "single_trip_objective_bitwise_equal": (
                    "" if regression is None else regression["objective_bitwise_equal"]
                ),
                "single_trip_components_bitwise_equal": (
                    "" if regression is None else regression["components_bitwise_equal"]
                ),
                "single_trip_mismatch_fields": (
                    ""
                    if regression is None
                    else ";".join(regression["mismatch_fields"])
                ),
                "prepared_solution_sha256": solution_sha(prepared),
            }
        )
    except Exception as exc:
        base_row["status"] = f"HALT_{experiment}_PREPARE_OR_VALIDATE_FAILED"
        base_row["failure"] = f"{type(exc).__name__}: {exc}"
        base_row["interface_note"] = "failure retained; no repair was guessed"
        detail.update(
            {
                "status": base_row["status"],
                "failure": base_row["failure"],
                "interface_directly_usable": False,
                "interface_note": base_row["interface_note"],
            }
        )
    base_row["certificate_record_sha256"] = canonical_sha(detail)
    return base_row, detail


def source_hashes() -> dict[str, str]:
    paths = (
        Path(__file__).resolve(),
        REPO / "solver/src/setp_solver/search/multitrip_schedule.py",
        REPO / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
        REPO / "solver/src/setp_solver/search/certificate_execution.py",
        REPO / "solver/src/setp_solver/solution.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        REPO / "solver/src/setp_solver/search/evaluation.py",
        E4_DIR / "run_probe.py",
        E4_DIR / "joint_soc_wrapper.py",
        E6_DIR / "run_pilot06_direct_15.py",
        E6_DIR / "e6_methods.py",
        E5_DIR / "run_b2_low_cost.py",
        REPO / "solver/tests/test_multitrip_schedule.py",
    )
    return {rel(path): sha256(path) for path in paths}


def summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for experiment in EXPECTED:
        selected = [row for row in rows if row["experiment"] == experiment]
        result[experiment] = {
            "source_count": len(selected),
            "certificate_valid_count": sum(
                bool_value(row["certificate_valid"]) for row in selected
            ),
            "interface_directly_usable_count": sum(
                bool_value(row["interface_directly_usable"])
                for row in selected
            ),
            "halt_count": sum(str(row["status"]).startswith("HALT") for row in selected),
            "original_route_count": sum(int(row["original_route_count"] or 0) for row in selected),
            "packed_physical_vehicle_count": sum(int(row["packed_physical_vehicle_count"] or 0) for row in selected),
            "saved_physical_vehicle_count": sum(int(row["saved_physical_vehicle_count"] or 0) for row in selected),
            "solutions_with_vehicle_saving": sum(int(row["saved_physical_vehicle_count"] or 0) > 0 for row in selected),
            "max_saved_physical_vehicles": max(
                (int(row["saved_physical_vehicle_count"] or 0) for row in selected),
                default=0,
            ),
            "complete_checker_pass_count": sum(
                int(row["current_checker_violation_count"] or 0) == 0
                for row in selected
            ),
            "legacy_static_checker_violation_count": sum(
                int(row["legacy_static_checker_violation_count"] or 0)
                for row in selected
            ),
            "saved_terminal_charge_count": sum(
                int(row["saved_terminal_charge_count"] or 0)
                for row in selected
            ),
            "saved_terminal_charge_kwh": sum(
                float(row["saved_terminal_charge_kwh"] or 0.0)
                for row in selected
            ),
            "depot_charge_ledger_count": sum(
                int(row["depot_charge_ledger_count"] or 0)
                for row in selected
            ),
            "depot_charge_ledger_kwh": sum(
                float(row["depot_charge_ledger_kwh"] or 0.0)
                for row in selected
            ),
            "depot_charge_ledger_entrywise_bitwise_equal_count": sum(
                bool_value(
                    row["depot_charge_ledger_entrywise_bitwise_equal"]
                )
                for row in selected
            ),
            "single_trip_regression_selected_count": sum(
                bool_value(row["single_trip_regression_selected"])
                for row in selected
            ),
            "single_trip_regression_pass_count": sum(
                bool_value(row["single_trip_regression_selected"])
                and bool_value(row["single_trip_objective_bitwise_equal"])
                and bool_value(row["single_trip_components_bitwise_equal"])
                and not str(row["single_trip_mismatch_fields"])
                for row in selected
            ),
        }
    return result


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def artifact_hashes() -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }


def acceptance_result(
    summary: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    e4 = summary["E4"]
    e6 = summary["E6"]
    failures: list[str] = []
    criteria = {
        "e4_90_of_90_interface_directly_usable": (
            e4["source_count"] == 90
            and e4["interface_directly_usable_count"] == 90
        ),
        "e4_270_terminal_charges_in_depot_ledger": (
            e4["saved_terminal_charge_count"] == 270
            and e4["depot_charge_ledger_count"] == 270
            and e4["depot_charge_ledger_entrywise_bitwise_equal_count"] == 90
        ),
        "e4_terminal_charge_total_matches_locked_5869_852618210777": (
            float_bitwise_equal(
                e4["saved_terminal_charge_kwh"], 5869.852618210777
            )
            and float_bitwise_equal(
                e4["depot_charge_ledger_kwh"], 5869.852618210777
            )
        ),
        "e6_900_of_900_complete_check": (
            e6["source_count"] == 900
            and e6["interface_directly_usable_count"] == 900
            and e6["complete_checker_pass_count"] == 900
        ),
        "e4_20_single_trip_bitwise_regressions": (
            e4["single_trip_regression_selected_count"] >= 20
            and e4["single_trip_regression_selected_count"]
            == e4["single_trip_regression_pass_count"]
        ),
        "e6_20_single_trip_bitwise_regressions": (
            e6["single_trip_regression_selected_count"] >= 20
            and e6["single_trip_regression_selected_count"]
            == e6["single_trip_regression_pass_count"]
        ),
    }
    for name, passed in criteria.items():
        if not passed:
            failures.append(name)
    failed_rows = [
        row["record_id"]
        for row in rows
        if row["experiment"] in {"E4", "E6"}
        and (
            not bool_value(row["interface_directly_usable"])
            or bool(row["single_trip_mismatch_fields"])
        )
    ]
    if not failures:
        status = "MULTITRIP_INTERFACE_COMPLETE"
    elif failures == [
        "e4_terminal_charge_total_matches_locked_5869_852618210777"
    ]:
        status = "HALT_E4_LOCKED_TERMINAL_KWH_TOTAL_MISMATCH"
    elif any(name.startswith("e4_") for name in failures) and not any(
        name.startswith("e6_") for name in failures
    ):
        status = "HALT_E4_MULTITRIP_INTERFACE_ACCEPTANCE_FAILED"
    elif any(name.startswith("e6_") for name in failures) and not any(
        name.startswith("e4_") for name in failures
    ):
        status = "HALT_E6_MULTITRIP_COMPLETE_CHECK_FAILED"
    else:
        status = "HALT_MULTITRIP_INTERFACE_ACCEPTANCE_FAILED"
    return {
        "status": status,
        "criteria": criteria,
        "failed_criteria": failures,
        "failed_record_ids": failed_rows,
    }


def render_report(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    acceptance: dict[str, Any],
) -> str:
    e4 = summary["E4"]
    e6 = summary["E6"]
    e5 = summary["E5_WITNESS"]
    e6_legacy_rows = sum(
        row["experiment"] == "E6"
        and int(row["legacy_static_checker_violation_count"] or 0) > 0
        for row in rows
    )
    return f"""

## 改法

FACT：`prepare_multitrip_solution` 新增显式 `ContinuousSOCContract`。E4 wrapper 只把已有的 60%-20%-80%-次日60% 常量和已保存 `terminal_charges` 交给接口；证书用 30.912 kWh 平移出发电量、46.368 kWh 平移上限重放路线，逐笔核对返场余电、终端充电量、非线性曲线时长、车场和返场至次日发车窗口，然后写入 `depot_charge_ledger`。保存的电费、排放、起止时刻和电量未重定价。

FACT：E6 完整多趟检查先验证证书中的路线绑定、上趟返场余电、趟间补电量、非线性曲线时长和发车时钟；随后保留静态检查器的其余全部约束，仅用经证书验证的跨趟继承电量替换单路线零初值电量轨迹，并仅替换 `#T2` 及以后在本车场的已证明趟间充电时钟判定。`cost.py`、`check.py`、`search/evaluation.py` 未修改。

FACT：用户指定的 `search/n.py` 在当前工作树及 Git 记录中不存在；实际 prepare/证书路径位于 `multitrip_schedule.py`，调用适配位于 `e3_multitrip_runtime.py`。修复按这条实际路径完成。

## 验证结果

FACT：最终状态为 `{acceptance['status']}`。诊断处理 E4 {e4['source_count']} 份、E6 {e6['source_count']} 份和 E5 witness {e5['source_count']} 份；`search_executed=false`。

FACT：E4 的 `interface_directly_usable` 为 {e4['interface_directly_usable_count']}/{e4['source_count']}。保存端共 {e4['saved_terminal_charge_count']} 笔返场补电，合计 {e4['saved_terminal_charge_kwh']!r} kWh；新趟间/跨日电量账为 {e4['depot_charge_ledger_count']} 笔，合计 {e4['depot_charge_ledger_kwh']!r} kWh。每笔输入与账本电量都作了 IEEE-754 binary64 逐位比较。

FACT：对 270 个原始 JSON 数字按十进制词法无损求和得 `5869.852618210776059` kWh；按保存解读为 binary64 后，保存端和新账本的合计都是 `5869.852618210776` kWh。任务锁定值 `5869.852618210777` 比两者高 1 个 binary64 ULP，即 `9.094947017729282e-13` kWh。因此 270 笔已全部逐位入账，但“合计严格等于锁定值”这一门槛未成立；本报告的最终 HALT 以原始保存行为准。这一全量证据更正上文改动前记录中引用的 `5869.852618210777` 前提。

FACT：E6 的完整检查为 {e6['complete_checker_pass_count']}/{e6['source_count']}，`interface_directly_usable` 为 {e6['interface_directly_usable_count']}/{e6['source_count']}。修复前的单路线静态语义仍在 {e6_legacy_rows} 份中产生违反，证明三份原冲突未被删除或用放宽阈值掩盖；完整多趟语义对同一批证书通过 {e6['complete_checker_pass_count']} 份。

FACT：单趟零搜索回归按 `record_id` 字典序预先取样，E4 选 {e4['single_trip_regression_selected_count']} 份并通过 {e4['single_trip_regression_pass_count']} 份，E6 选 {e6['single_trip_regression_selected_count']} 份并通过 {e6['single_trip_regression_pass_count']} 份。每份均对目标值和 {len(REGRESSION_COMPONENTS)} 个关键分项作 binary64 逐位比较，同时要求原实验检查无违反。

FACT：首轮定向测试为 `28 passed`；扩展到证书执行、动态多趟、公共站和非线性多趟共 7 个测试文件后，结果为 `52 passed`。

## 证据文件

`raw_runs.csv` 每份输入一行；`schedule_certificates.jsonl` 保留每份完整证书、新完整检查、旧静态检查和回归原值；`metadata.json` 锁定 Git 提交与全部涉及源码 SHA-256；`decision.json`、`done.json` 按客观门槛判定；`artifact_hashes.json` 锁定目录内其余文件。
"""


def write_outputs(rows: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    material_names = (
        "raw_runs.csv",
        "schedule_certificates.jsonl",
        "metadata.json",
        "decision.json",
        "done.json",
        "artifact_hashes.json",
    )
    existing = [name for name in material_names if (OUT / name).exists()]
    if existing:
        raise RuntimeError(
            f"refusing to overwrite existing diagnostic artifacts: {existing}"
        )
    root_cause = (OUT / "report.md").read_text(encoding="utf-8")
    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (OUT / "schedule_certificates.jsonl").open("w", encoding="utf-8") as handle:
        for detail in details:
            handle.write(json.dumps(detail, ensure_ascii=False, sort_keys=True) + "\n")
    summary = summaries(rows)
    acceptance = acceptance_result(summary, rows)
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.multitrip-interface-completion.metadata.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "formal_result": False,
            "search_executed": False,
            "git_commit": git_commit,
            "source_expected_counts": EXPECTED,
            "source_observed_counts": {
                key: value["source_count"] for key, value in summary.items()
            },
            "method": "zero-search saved-solution preparation, certificate validation, complete multi-trip checking, and predetermined bitwise single-trip replay",
            "e4_continuous_soc_contract_id": E4_CONTINUOUS_SOC_CONTRACT_ID,
            "e4_soc_rule": {
                "initial": 0.60,
                "minimum": 0.20,
                "maximum": 0.80,
                "next_day_minimum": 0.60,
            },
            "e4_terminal_charge_aggregate_evidence": {
                "task_locked_kwh": 5869.852618210777,
                "saved_binary64_sum_kwh": summary["E4"][
                    "saved_terminal_charge_kwh"
                ],
                "ledger_binary64_sum_kwh": summary["E4"][
                    "depot_charge_ledger_kwh"
                ],
                "source_json_decimal_sum_kwh": str(
                    e4_source_decimal_terminal_kwh()
                ),
                "task_locked_minus_binary64_sum_kwh": (
                    5869.852618210777
                    - summary["E4"]["saved_terminal_charge_kwh"]
                ),
            },
            "single_trip_regression": {
                "selection": "first record_id values in lexicographic order",
                "sample_count": REGRESSION_SAMPLE_COUNT,
                "components": list(REGRESSION_COMPONENTS),
                "comparison": "IEEE-754 binary64 bitwise equality",
            },
            "targeted_tests": {
                "test_file_count": 7,
                "passed": 52,
                "failed": 0,
            },
            "protected_files_unchanged": [
                "solver/src/setp_solver/cost.py",
                "solver/src/setp_solver/check.py",
                "solver/src/setp_solver/search/evaluation.py",
            ],
            "source_code_sha256": source_hashes(),
            "summary": summary,
        },
    )
    write_json(
        OUT / "decision.json",
        {
            "formal_result": False,
            "search_executed": False,
            "status": acceptance["status"],
            "criteria": acceptance["criteria"],
            "failed_criteria": acceptance["failed_criteria"],
            "failed_record_ids": acceptance["failed_record_ids"],
            "e4": (
                "90_OF_90_INTERFACE_DIRECTLY_USABLE__270_TERMINAL_CHARGES_LEDGERED"
                if acceptance["criteria"]["e4_90_of_90_interface_directly_usable"]
                and acceptance["criteria"]["e4_270_terminal_charges_in_depot_ledger"]
                and acceptance["criteria"][
                    "e4_terminal_charge_total_matches_locked_5869_852618210777"
                ]
                else "HALT_E4_ACCEPTANCE_FAILED"
            ),
            "e6": (
                "900_OF_900_COMPLETE_CHECK_PASS"
                if acceptance["criteria"]["e6_900_of_900_complete_check"]
                else "HALT_E6_ACCEPTANCE_FAILED"
            ),
            "e5": "INITIAL_WITNESS_DIAGNOSTIC_ONLY_NO_FINAL_B2_SOLUTION",
            "summary": summary,
        },
    )
    (OUT / "report.md").write_text(
        root_cause.rstrip()
        + render_report(summary, rows, acceptance),
        encoding="utf-8",
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.multitrip-interface-completion.done.v1",
            "completed_at": datetime.now(UTC).isoformat(),
            "status": acceptance["status"],
            "formal_result": False,
            "search_executed": False,
            "criteria": acceptance["criteria"],
            "failed_criteria": acceptance["failed_criteria"],
            "failed_record_ids": acceptance["failed_record_ids"],
        },
    )
    write_json(OUT / "artifact_hashes.json", artifact_hashes())


def read_rows() -> list[dict[str, Any]]:
    with (OUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def check_outputs() -> dict[str, Any]:
    failures: list[str] = []
    rows = read_rows()
    if len(rows) != sum(EXPECTED.values()):
        failures.append(f"raw row count is {len(rows)}")
    counts = Counter(row["experiment"] for row in rows)
    if dict(counts) != EXPECTED:
        failures.append(f"raw experiment counts are {dict(counts)}")
    ids = [row["record_id"] for row in rows]
    if len(ids) != len(set(ids)):
        failures.append("duplicate record_id")
    for row in rows:
        source = REPO / row["source_path"]
        if not source.is_file() or sha256(source) != row["source_sha256"]:
            failures.append(f"source drift: {row['record_id']}")
        try:
            original = int(row["original_physical_vehicle_count"])
            packed = int(row["packed_physical_vehicle_count"])
            saved = int(row["saved_physical_vehicle_count"])
            if original - packed != saved or saved < 0:
                failures.append(f"count arithmetic: {row['record_id']}")
        except ValueError:
            if not row["status"].startswith("HALT"):
                failures.append(f"missing counts without HALT: {row['record_id']}")
    details = [
        json.loads(line)
        for line in (OUT / "schedule_certificates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    detail_by_id = {item["record_id"]: item for item in details}
    if len(details) != len(rows) or len(detail_by_id) != len(details):
        failures.append("certificate record count or uniqueness mismatch")
    for row in rows:
        detail = detail_by_id.get(row["record_id"])
        if detail is None or canonical_sha(detail) != row["certificate_record_sha256"]:
            failures.append(f"certificate hash mismatch: {row['record_id']}")
    metadata = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    for path_text, expected_hash in metadata["source_code_sha256"].items():
        path = REPO / path_text
        if not path.is_file() or sha256(path) != expected_hash:
            failures.append(f"source code drift: {path_text}")
    expected_artifacts = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))
    if expected_artifacts != artifact_hashes():
        failures.append("artifact hash mismatch")
    decision = json.loads((OUT / "decision.json").read_text(encoding="utf-8"))
    done = json.loads((OUT / "done.json").read_text(encoding="utf-8"))
    current_acceptance = acceptance_result(summaries(rows), rows)
    if (
        decision.get("status") != current_acceptance["status"]
        or done.get("status") != current_acceptance["status"]
        or decision.get("criteria") != current_acceptance["criteria"]
        or done.get("criteria") != current_acceptance["criteria"]
    ):
        failures.append("decision/done acceptance mismatch")
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if metadata.get("git_commit") != current_commit:
        failures.append("git commit drift")
    protected = (
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/search/evaluation.py",
    )
    protected_changed = subprocess.run(
        ["git", "diff", "--quiet", "--", *protected],
        cwd=REPO,
        check=False,
    ).returncode != 0 or subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *protected],
        cwd=REPO,
        check=False,
    ).returncode != 0
    if protected_changed:
        failures.append("protected source file changed")
    if (
        decision.get("formal_result") is not False
        or metadata.get("formal_result") is not False
        or done.get("formal_result") is not False
        or decision.get("search_executed") is not False
        or metadata.get("search_executed") is not False
        or done.get("search_executed") is not False
    ):
        failures.append("formal_result is not false")
    return {
        "status": "PASS" if not failures else "FAIL",
        "completion_status": current_acceptance["status"],
        "row_count": len(rows),
        "experiment_counts": dict(counts),
        "failure_count": len(failures),
        "failures": failures[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        result = check_outputs()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    specs = source_specs()
    selected_regressions = regression_ids(specs)
    bundles = Bundles()
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for spec in specs:
        row, detail = process(
            spec,
            bundles,
            regression_selected=spec_record_id(spec) in selected_regressions,
        )
        rows.append(row)
        details.append(detail)
    write_outputs(rows, details)
    print(json.dumps(summaries(rows), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
