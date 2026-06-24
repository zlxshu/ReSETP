#!/usr/bin/env python3
"""09q source-bound battery x operational-constraint mix map.

This diagnostic is deliberately broader than the 09o 280kWh pilot.  It keeps
promoted parameters, generated bundles, cost/check/evaluation semantics, and
algorithm code frozen.  Battery capacity is an in-memory PriceParameters
override, while operational constraints are diagnostic search/temporary-bundle
probes.  Passing this runner is evidence for a next modelling decision, not a
model change by itself.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable

import battery_spectrum_transition as b9k
import charging_infrastructure_operational_pilot as g09o
import fleet_cap_operational_gate as g09n
import numpy as np
import source_bound_mixed_band_gate as g09l

from setp_solver.check import STATION_CAPACITY, check_solution
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Node
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.feasible_repair import route_customers, route_distance
from setp_solver.search.fleet import FleetLimits, UNBOUNDED_FLEET, route_ev_energy_summary
from setp_solver.search.winner_operators import e2_alns_throughput_flags
from setp_solver.solution import Solution


CARBON_PRICE = 0.05034
BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/source_bound_operational_mix_map_data")
DEFAULT_REPORT = Path("baselines/e2_alns/source_bound_operational_mix_map.md")
DEFAULT_PROMPT = Path("docs/handoff/codex_prompts/09q_source_bound_operational_mix_map.md")

FULL_GRADIENT_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
FAMILIES = ("vanilla", "multidepot", "threeshift")
VARIANT_ORDER = ("free_mixed", "cv_shell", "ev_shell")
SOURCE_BOUND_BATTERIES = (
    60.0,
    81.0,
    82.6,
    89.0,
    100.0,
    113.0,
    123.9,
    140.0,
    141.0,
    150.0,
    176.0,
    180.0,
    194.0,
    200.0,
    210.0,
    240.0,
    280.0,
    282.0,
    291.0,
)
REFERENCE_BATTERIES = (80.0,)
DEFAULT_CONSTRAINT_SCENARIOS = (
    "unbounded_reference",
    "goeke_ev_cap_only",
    "goeke_total_cap",
    "depot_chargers_manifest_ev_diagnostic",
    "depot_chargers_manifest_total_diagnostic",
    "public_charging_disabled_diagnostic",
    "depot_manifest_ev_no_public_diagnostic",
)
SOURCE_PROMOTABLE_SCENARIOS = set()
SOURCE_BACKED_DIAGNOSTIC_SCENARIOS = {"goeke_ev_cap_only", "goeke_total_cap"}
DIAGNOSTIC_SCENARIOS = {
    "depot_chargers_manifest_ev_diagnostic",
    "depot_chargers_manifest_total_diagnostic",
    "public_charging_disabled_diagnostic",
    "depot_manifest_ev_no_public_diagnostic",
}
REFERENCE_SCENARIOS = {"unbounded_reference"}
TERMINAL_STATUSES = {
    "OK",
    "VIOLATION",
    "CAP_VIOLATION",
    "INIT_INFEASIBLE",
    "TIMEOUT",
    "ERROR",
    "JSON_PARSE_ERROR",
    "SUBPROCESS_NONZERO",
}
COLLECTION_FAILURE_STATUSES = {"TIMEOUT", "ERROR", "JSON_PARSE_ERROR", "SUBPROCESS_NONZERO"}
PRACTICAL_LOW = 0.20
PRACTICAL_HIGH = 0.80
NEAR_PASS_FRACTION = 0.75


@dataclass(frozen=True)
class ConstraintSpec:
    scenario: str
    max_cv: int
    max_ev: int
    depot_chargers: int | None
    public_chargers: int | None
    source_class: str
    mechanism: str
    promotable: bool
    interpretation: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--phase1-only", action="store_true")
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    parser.add_argument("--stage-c", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retry-timeouts", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--battery-values", nargs="*", type=float, default=[])
    parser.add_argument("--constraint-scenarios", nargs="*", default=list(DEFAULT_CONSTRAINT_SCENARIOS))
    parser.add_argument("--stage-a-seeds", nargs="*", type=int, default=[1])
    parser.add_argument("--stage-b-seeds", nargs="*", type=int, default=[1, 2, 3])
    parser.add_argument("--stage-c-seeds", nargs="*", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument("--stage-a-eval-budget", type=int, default=1000)
    parser.add_argument("--stage-b-eval-budget", type=int, default=3000)
    parser.add_argument("--stage-c-eval-budget", type=int, default=16000)
    parser.add_argument("--runtime-small", type=float, default=120.0)
    parser.add_argument("--runtime-medium", type=float, default=240.0)
    parser.add_argument("--runtime-large", type=float, default=480.0)
    parser.add_argument("--runtime-confirm-small", type=float, default=300.0)
    parser.add_argument("--runtime-confirm-medium", type=float, default=600.0)
    parser.add_argument("--runtime-confirm-large", type=float, default=900.0)
    parser.add_argument("--task-timeout-buffer", type=float, default=90.0)
    parser.add_argument("--single-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-phase", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-category", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-instance", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-variant", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-battery-kwh", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--single-constraint-scenario", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-eval-budget", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-runtime-cap", type=float, default=0.0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.single_run:
        return single_run_cli(repo_root, args)

    started = time.perf_counter()
    output_dir = repo_root / args.output_dir
    report_path = repo_root / args.report_path
    output_dir.mkdir(parents=True, exist_ok=True)

    batteries = selected_batteries(args)
    evidence_rows = build_evidence_matrix(args)
    battery_rows = battery_candidate_rows(args)
    raw_fleet_rows = raw_goeke_fleet_rows(repo_root)
    generated_fleet_rows = generated_fleet_rows_all(repo_root)
    meta_by_instance = g09n.fleet_meta_by_instance(repo_root, raw_fleet_rows, generated_fleet_rows)
    constraint_rows = constraint_matrix_rows(meta_by_instance, args.constraint_scenarios)
    phase0 = phase0_audit(repo_root, batteries, args.constraint_scenarios, meta_by_instance)
    phase1_rows = phase1_existing_map(repo_root, meta_by_instance)
    phase1_summary = phase1_summary_rows(phase1_rows)
    metadata = build_metadata(repo_root, args, batteries, started)

    b9k.write_csv(output_dir / "evidence_matrix.csv", evidence_rows)
    b9k.write_csv(output_dir / "battery_candidate_set.csv", battery_rows)
    b9k.write_csv(output_dir / "raw_goeke_fleet_counts.csv", raw_fleet_rows)
    b9k.write_csv(output_dir / "generated_fleet_metadata.csv", generated_fleet_rows)
    b9k.write_csv(output_dir / "operational_constraint_matrix.csv", constraint_rows)
    b9k.write_json(output_dir / "phase0_audit.json", phase0)
    b9k.write_csv(output_dir / "phase1_existing_failure_map.csv", phase1_rows)
    b9k.write_csv(output_dir / "phase1_existing_summary.csv", phase1_summary)

    stage_a_rows: list[dict[str, Any]] = []
    stage_a_winners: list[dict[str, Any]] = []
    stage_a_summary: list[dict[str, Any]] = []
    stage_a_by_scale: list[dict[str, Any]] = []
    stage_a_failures: list[dict[str, Any]] = []
    stage_b_rows: list[dict[str, Any]] = []
    stage_b_winners: list[dict[str, Any]] = []
    stage_b_summary: list[dict[str, Any]] = []
    stage_b_by_scale: list[dict[str, Any]] = []
    stage_b_failures: list[dict[str, Any]] = []
    stage_c_rows: list[dict[str, Any]] = []
    stage_c_winners: list[dict[str, Any]] = []
    stage_c_summary: list[dict[str, Any]] = []
    stage_c_by_scale: list[dict[str, Any]] = []
    stage_c_failures: list[dict[str, Any]] = []

    if phase0.get("status") == "OK" and not args.phase0_only and not args.phase1_only and args.stage_a:
        stage_a_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_a",
            instances=smoke_instances(repo_root) if args.smoke else focus_instances(repo_root, reps=(1,)),
            batteries=batteries,
            constraint_scenarios=list(args.constraint_scenarios),
            seeds=list(args.stage_a_seeds),
            eval_budget=int(args.stage_a_eval_budget),
            runtime_caps=(float(args.runtime_small), float(args.runtime_medium), float(args.runtime_large)),
        )
        b9k.write_csv(output_dir / "stage_a_raw_runs.csv", stage_a_rows)
        stage_a_winners = winner_rows_from_raw(stage_a_rows)
        b9k.write_csv(output_dir / "stage_a_winners.csv", stage_a_winners)
        stage_a_by_scale = by_scale_rows(stage_a_winners, "stage_a")
        b9k.write_csv(output_dir / "stage_a_by_scale.csv", stage_a_by_scale)
        stage_a_summary = scenario_summary_rows(stage_a_winners, stage_a_by_scale, stage_a_rows, "stage_a")
        b9k.write_csv(output_dir / "stage_a_scenario_summary.csv", stage_a_summary)
        stage_a_failures = failure_instance_rows(stage_a_winners, "stage_a")
        b9k.write_csv(output_dir / "stage_a_failure_instances.csv", stage_a_failures)
    elif (output_dir / "stage_a_scenario_summary.csv").exists():
        stage_a_summary = read_existing_csv(output_dir / "stage_a_scenario_summary.csv")

    stage_b_pairs = triggered_pairs(stage_a_summary)
    if phase0.get("status") == "OK" and not args.phase0_only and args.stage_b and stage_b_pairs:
        stage_b_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_b",
            instances=focus_instances(repo_root, reps=(1, 2, 3)),
            batteries=sorted({battery for battery, _scenario in stage_b_pairs}),
            constraint_scenarios=sorted({scenario for _battery, scenario in stage_b_pairs}),
            seeds=list(args.stage_b_seeds),
            eval_budget=int(args.stage_b_eval_budget),
            runtime_caps=(float(args.runtime_small), float(args.runtime_medium), float(args.runtime_large)),
            allowed_pairs=stage_b_pairs,
        )
        b9k.write_csv(output_dir / "stage_b_raw_runs.csv", stage_b_rows)
        stage_b_winners = winner_rows_from_raw(stage_b_rows)
        b9k.write_csv(output_dir / "stage_b_winners.csv", stage_b_winners)
        stage_b_by_scale = by_scale_rows(stage_b_winners, "stage_b")
        b9k.write_csv(output_dir / "stage_b_by_scale.csv", stage_b_by_scale)
        stage_b_summary = scenario_summary_rows(stage_b_winners, stage_b_by_scale, stage_b_rows, "stage_b")
        b9k.write_csv(output_dir / "stage_b_scenario_summary.csv", stage_b_summary)
        stage_b_failures = failure_instance_rows(stage_b_winners, "stage_b")
        b9k.write_csv(output_dir / "stage_b_failure_instances.csv", stage_b_failures)
    elif (output_dir / "stage_b_scenario_summary.csv").exists():
        stage_b_summary = read_existing_csv(output_dir / "stage_b_scenario_summary.csv")

    stage_c_pairs = triggered_pairs(stage_b_summary)
    if phase0.get("status") == "OK" and not args.phase0_only and args.stage_c and stage_c_pairs:
        stage_c_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_c",
            instances=focus_instances(repo_root, reps=(1, 2, 3)),
            batteries=sorted({battery for battery, _scenario in stage_c_pairs}),
            constraint_scenarios=sorted({scenario for _battery, scenario in stage_c_pairs}),
            seeds=list(args.stage_c_seeds),
            eval_budget=int(args.stage_c_eval_budget),
            runtime_caps=(float(args.runtime_confirm_small), float(args.runtime_confirm_medium), float(args.runtime_confirm_large)),
            allowed_pairs=stage_c_pairs,
        )
        b9k.write_csv(output_dir / "stage_c_raw_runs.csv", stage_c_rows)
        stage_c_winners = winner_rows_from_raw(stage_c_rows)
        b9k.write_csv(output_dir / "stage_c_winners.csv", stage_c_winners)
        stage_c_by_scale = by_scale_rows(stage_c_winners, "stage_c")
        b9k.write_csv(output_dir / "stage_c_by_scale.csv", stage_c_by_scale)
        stage_c_summary = scenario_summary_rows(stage_c_winners, stage_c_by_scale, stage_c_rows, "stage_c")
        b9k.write_csv(output_dir / "stage_c_scenario_summary.csv", stage_c_summary)
        stage_c_failures = failure_instance_rows(stage_c_winners, "stage_c")
        b9k.write_csv(output_dir / "stage_c_failure_instances.csv", stage_c_failures)

    all_raw = [*stage_a_rows, *stage_b_rows, *stage_c_rows]
    all_winners = [*stage_a_winners, *stage_b_winners, *stage_c_winners]
    b9k.write_csv(output_dir / "raw_runs.csv", all_raw)
    b9k.write_csv(output_dir / "winners.csv", all_winners)
    metadata["elapsed_seconds"] = time.perf_counter() - started
    metadata["stage_b_triggered_pairs"] = [f"{battery}:{scenario}" for battery, scenario in stage_b_pairs]
    metadata["stage_c_triggered_pairs"] = [f"{battery}:{scenario}" for battery, scenario in stage_c_pairs]
    conclusion = summarize_conclusion(args, phase0, all_raw, stage_a_summary, stage_b_summary, stage_c_summary)
    b9k.write_json(output_dir / "metadata.json", metadata)
    b9k.write_json(output_dir / "conclusion.json", conclusion)
    report_path.write_text(
        render_report(
            metadata,
            phase0,
            battery_rows,
            constraint_rows,
            phase1_summary,
            stage_a_summary,
            stage_a_by_scale,
            stage_a_failures,
            stage_b_summary,
            stage_b_by_scale,
            stage_b_failures,
            stage_c_summary,
            stage_c_by_scale,
            stage_c_failures,
            conclusion,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "schema_version": "setp-09q-source-bound-operational-map.v1",
                "verdict": conclusion["verdict"],
                "report": str(args.report_path),
                "output_dir": str(args.output_dir),
                "stage_a_rows": len(stage_a_rows),
                "stage_b_rows": len(stage_b_rows),
                "stage_c_rows": len(stage_c_rows),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2 if str(conclusion["verdict"]).startswith("HALT_") else 0


def selected_batteries(args: argparse.Namespace) -> list[float]:
    if args.battery_values:
        values = [float(value) for value in args.battery_values]
    else:
        values = list(SOURCE_BOUND_BATTERIES)
    return sorted({round(float(value), 6) for value in values if round(float(value), 6) not in REFERENCE_BATTERIES})


def build_evidence_matrix(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in b9k.evidence_matrix_rows():
        value = float(row["battery_kwh"])
        rows.append(
            {
                "evidence_kind": "battery_capacity",
                "source_id": row["source_id"],
                "source_type": row["source_type"],
                "value": value,
                "unit": "kWh",
                "evidence_tier": row["evidence_tier"],
                "promotable_in_09q": value not in REFERENCE_BATTERIES and value in SOURCE_BOUND_BATTERIES,
                "scenario_relevance": row.get("vehicle_or_scenario", ""),
                "path_or_url": row.get("path_or_url", ""),
                "caveat": row.get("caveat", ""),
            }
        )
    for row in g09n.evidence_matrix_rows():
        rows.append(
            {
                "evidence_kind": "operational_constraint",
                "source_id": row["source_id"],
                "source_type": row["source_type"],
                "value": row.get("cap_value_rule", ""),
                "unit": "rule",
                "evidence_tier": "source_backed" if truthy(row.get("explicit_numeric_cap")) else "context_only",
                "promotable_in_09q": False,
                "scenario_relevance": row.get("scenario_relevance", ""),
                "path_or_url": row.get("path_or_url", ""),
                "caveat": row.get("caveat", ""),
            }
        )
    rows.append(
        {
            "evidence_kind": "operational_constraint",
            "source_id": "ReSETPGeneratedDepotChargers",
            "source_type": "generated_instance_metadata",
            "value": "depot station_chargers currently default to customer_count_route_upper_bound",
            "unit": "rule",
            "evidence_tier": "diagnostic_reference",
            "promotable_in_09q": False,
            "scenario_relevance": "Explains why 09o 280kWh winners can depot-charge many EV routes.",
            "path_or_url": str(BENCHMARK_ROOT),
            "caveat": "This is the current generated assumption, not a real-world charger-count source.",
        }
    )
    rows.append(
        {
            "evidence_kind": "operational_constraint",
            "source_id": "09qNoPublicChargingDiagnostic",
            "source_type": "diagnostic_counterfactual",
            "value": "set public station_chargers to 0 in temporary bundles",
            "unit": "rule",
            "evidence_tier": "diagnostic_only",
            "promotable_in_09q": False,
            "scenario_relevance": "Tests whether lower battery candidates rely on public charging.",
            "path_or_url": "",
            "caveat": "Cannot become a main scenario without public-charger availability evidence.",
        }
    )
    return rows


def battery_candidate_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    ns = argparse.Namespace(battery_values=list(args.battery_values or []))
    rows = g09l.candidate_rows_from_evidence(b9k.evidence_matrix_rows(), ns)
    out: list[dict[str, Any]] = []
    selected = set(selected_batteries(args))
    for row in rows:
        value = float(row["battery_kwh"])
        out.append({**row, "selected_for_09q": value in selected, "reference_only_09q": value in REFERENCE_BATTERIES})
    return out


def constraint_matrix_rows(meta_by_instance: dict[str, g09n.FleetMeta], scenarios: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in focus_instances_from_meta(meta_by_instance):
        meta = meta_by_instance[key]
        for scenario in scenarios:
            spec = constraint_for_scenario(meta, scenario)
            rows.append(
                {
                    "category": meta.category,
                    "instance": meta.instance,
                    "size": meta.size,
                    "replicate": meta.replicate,
                    "constraint_scenario": scenario,
                    "mechanism": spec.mechanism,
                    "source_class": spec.source_class,
                    "promotable": spec.promotable,
                    "max_cv": spec.max_cv,
                    "max_ev": spec.max_ev,
                    "depot_chargers": "" if spec.depot_chargers is None else spec.depot_chargers,
                    "public_chargers": "" if spec.public_chargers is None else spec.public_chargers,
                    "manifest_num_cv": meta.manifest_num_cv,
                    "manifest_num_ev": meta.manifest_num_ev,
                    "depots": meta.depots,
                    "interpretation": spec.interpretation,
                }
            )
    return rows


def raw_goeke_fleet_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = repo_root / g09n.RAW_GOEEKE_ROOT
    for size in FULL_GRADIENT_SIZES:
        for path in sorted(root.glob(f"E-UK{size}_*.txt")):
            text = path.read_text(errors="ignore")
            num_veh = g09n.regex_int(text, r"numVeh\s*/([0-9]+)/")
            num_cv = g09n.regex_int(text, r"numPetrolVeh\s*/([0-9]+)/")
            num_ev = g09n.regex_int(text, r"numElectroVeh\s*/([0-9]+)/")
            rep = g09n.regex_int(path.name, rf"E-UK{size}_(\d+)\.txt") or 0
            rows.append(
                {
                    "source_file": str(path.relative_to(repo_root)),
                    "raw_instance": path.name,
                    "size": size,
                    "replicate": rep,
                    "numVeh": num_veh,
                    "numPetrolVeh": num_cv,
                    "numElectroVeh": num_ev,
                    "sum_cv_ev": (num_cv or 0) + (num_ev or 0),
                }
            )
    return rows


def generated_fleet_rows_all(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in focus_instances(repo_root, reps=(1, 2, 3)):
        category, instance = key.split("/", 1)
        bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
        data = json.loads((bundle_dir / "instance.json").read_text(encoding="utf-8"))
        manifest = json.loads((bundle_dir / "scenario_manifest.json").read_text(encoding="utf-8"))
        meta = data.get("metadata", {})
        cfg = manifest.get("config", {})
        nodes = data.get("nodes", [])
        rows.append(
            {
                "category": category,
                "instance": instance,
                "size": b9k.customer_count(instance),
                "replicate": replicate_number(instance),
                "depots": sum(1 for node in nodes if str(node.get("node_type", "")).lower() == "d"),
                "stations": sum(1 for node in nodes if str(node.get("node_type", "")).lower() == "f"),
                "manifest_num_cv": meta.get("num_cv", cfg.get("num_cv", "")),
                "manifest_num_ev": meta.get("num_ev", cfg.get("num_ev", "")),
                "station_strategy": cfg.get("station_strategy", ""),
                "depot_strategy": cfg.get("depot_strategy", ""),
            }
        )
    return rows


def phase0_audit(
    repo_root: Path,
    batteries: list[float],
    scenarios: Iterable[str],
    meta_by_instance: dict[str, g09n.FleetMeta],
) -> dict[str, Any]:
    battery_audit = b9k.phase0_override_audit(repo_root, sorted(set([*batteries[:2], 100.0, 280.0])))
    probe_key = "multidepot/e2-multidepot-100c-01"
    station_audit: dict[str, Any] = {"status": "SKIPPED", "reason": "probe missing"}
    if probe_key in meta_by_instance:
        meta = meta_by_instance[probe_key]
        bundle_dir = repo_root / BENCHMARK_ROOT / meta.category / meta.instance
        spec = constraint_for_scenario(meta, "depot_chargers_manifest_ev_diagnostic")
        try:
            with temporary_bundle_with_station_caps(bundle_dir, spec) as tmp_dir:
                original = load_search_bundle(bundle_dir)
                overridden = load_search_bundle(tmp_dir)
                original_depots = [node.station_chargers for node in original.instance.nodes if node.node_type.lower() == "d"]
                override_depots = [node.station_chargers for node in overridden.instance.nodes if node.node_type.lower() == "d"]
                station_audit = {
                    "status": "OK" if override_depots and set(override_depots) == {spec.depot_chargers} else "HALT",
                    "probe_instance": probe_key,
                    "original_depot_chargers_min": min(original_depots) if original_depots else "",
                    "original_depot_chargers_max": max(original_depots) if original_depots else "",
                    "override_depot_chargers": spec.depot_chargers,
                    "loaded_override_depot_values": sorted(set(override_depots)),
                }
        except Exception as exc:  # noqa: BLE001
            station_audit = {"status": "HALT", "probe_instance": probe_key, "error_type": type(exc).__name__, "error": str(exc)}
    supported = {
        "unbounded_reference",
        "goeke_ev_cap_only",
        "goeke_total_cap",
        "depot_chargers_manifest_ev_diagnostic",
        "depot_chargers_manifest_total_diagnostic",
        "public_charging_disabled_diagnostic",
        "depot_manifest_ev_no_public_diagnostic",
    }
    unknown = sorted(set(scenarios) - supported)
    status = "OK" if battery_audit.get("status") == "OK" and station_audit.get("status") in {"OK", "SKIPPED"} and not unknown else "HALT"
    return {"status": status, "battery_override_audit": battery_audit, "station_override_audit": station_audit, "unknown_scenarios": unknown}


def phase1_existing_map(repo_root: Path, meta_by_instance: dict[str, g09n.FleetMeta]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stage_a_path = repo_root / "baselines/e2_alns/source_bound_mixed_band_gate_data/stage_a_winners.csv"
    if stage_a_path.exists() and stage_a_path.stat().st_size > 0:
        for row in b9k.read_csv(stage_a_path):
            if row.get("winner_status") != "OK":
                continue
            key = f"{row['category']}/{row['instance']}"
            meta = meta_by_instance.get(key)
            ev_routes = int(float(row.get("winner_ev_route_count", 0) or 0))
            cv_routes = int(float(row.get("winner_cv_route_count", 0) or 0))
            rows.append(
                {
                    "source_artifact": "09l_stage_a",
                    "battery_kwh": float(row["battery_kwh"]),
                    "category": row["category"],
                    "instance": row["instance"],
                    "size": b9k.customer_count(str(row["instance"])),
                    "constraint_scenario": "unbounded_reference",
                    "winner_composition": row.get("winner_composition", ""),
                    "winner_ev_route_share": float(row.get("winner_ev_route_share", 0.0)),
                    "winner_ev_customer_share": float(row.get("winner_ev_customer_share", math.nan)),
                    "winner_ev_demand_share": float(row.get("winner_ev_demand_share", math.nan)),
                    "winner_ev_distance_share": float(row.get("winner_ev_distance_share", math.nan)),
                    "winner_cv_route_count": cv_routes,
                    "winner_ev_route_count": ev_routes,
                    "manifest_num_cv": meta.manifest_num_cv if meta else "",
                    "manifest_num_ev": meta.manifest_num_ev if meta else "",
                    "ev_over_manifest": bool(meta and ev_routes > meta.manifest_num_ev),
                    "cv_over_manifest": bool(meta and cv_routes > meta.manifest_num_cv),
                    "in_practical_band": in_band(float(row.get("winner_ev_route_share", 0.0))),
                    "fake_balance": fake_balance(
                        float(row.get("winner_ev_route_share", math.nan)),
                        float(row.get("winner_ev_customer_share", math.nan)),
                        float(row.get("winner_ev_demand_share", math.nan)),
                        float(row.get("winner_ev_distance_share", math.nan)),
                    ),
                }
            )
    charging_path = repo_root / "baselines/e2_alns/charging_infrastructure_operational_pilot_data/winners.csv"
    if charging_path.exists() and charging_path.stat().st_size > 0:
        for row in b9k.read_csv(charging_path):
            rows.append(
                {
                    "source_artifact": "09o_pilot",
                    "battery_kwh": 280.0,
                    "category": row["category"],
                    "instance": row["instance"],
                    "size": b9k.customer_count(str(row["instance"])),
                    "constraint_scenario": "unbounded_reference",
                    "winner_composition": row.get("winner_composition", ""),
                    "winner_ev_route_share": float(row.get("winner_ev_route_share", 0.0)),
                    "winner_ev_customer_share": "",
                    "winner_ev_demand_share": "",
                    "winner_ev_distance_share": "",
                    "winner_cv_route_count": int(float(row.get("winner_cv_route_count", 0) or 0)),
                    "winner_ev_route_count": int(float(row.get("winner_ev_route_count", 0) or 0)),
                    "depot_charging_energy_share": row.get("winner_depot_charging_energy_share", ""),
                    "public_charging_energy_share": row.get("winner_public_charging_energy_share", ""),
                    "depot_peak_concurrent": row.get("winner_depot_peak_concurrent_at_one_depot", ""),
                    "depot_peak_capacity": row.get("winner_depot_peak_capacity", ""),
                    "in_practical_band": in_band(float(row.get("winner_ev_route_share", 0.0))),
                    "fake_balance": "",
                }
            )
    return b9k.sorted_rows(rows)


def phase1_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("source_artifact") != "09l_stage_a":
            continue
        groups[(str(row["category"]), float(row["battery_kwh"]))].append(row)
    out: list[dict[str, Any]] = []
    for (category, battery), items in sorted(groups.items()):
        out.append(
            {
                "source_artifact": "09l_stage_a",
                "category": category,
                "battery_kwh": battery,
                "rows": len(items),
                "in_band_rows": sum(truthy(row.get("in_practical_band")) for row in items),
                "fake_balance_rows": sum(truthy(row.get("fake_balance")) for row in items),
                "ev_over_manifest_rows": sum(truthy(row.get("ev_over_manifest")) for row in items),
                "mean_ev_route_share": mean(float(row.get("winner_ev_route_share", math.nan)) for row in items),
                "mean_ev_customer_share": mean(float_or_nan(row.get("winner_ev_customer_share")) for row in items),
                "mean_ev_demand_share": mean(float_or_nan(row.get("winner_ev_demand_share")) for row in items),
                "mean_ev_distance_share": mean(float_or_nan(row.get("winner_ev_distance_share")) for row in items),
            }
        )
    return out


def build_metadata(repo_root: Path, args: argparse.Namespace, batteries: list[float], started: float) -> dict[str, Any]:
    return {
        "schema_version": "setp-09q-source-bound-operational-map.v1",
        "repo_root": str(repo_root),
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "HEAD"),
        "git_status_short": b9k.git_output(repo_root, "status", "--short", "--untracked-files=all"),
        "python": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "numpy": np.__version__,
        "command": " ".join([sys.executable, *sys.argv]),
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "default_B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "tested_battery_values": batteries,
        "constraint_scenarios": list(args.constraint_scenarios),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "practical_band": [PRACTICAL_LOW, PRACTICAL_HIGH],
        "phase0_only": bool(args.phase0_only),
        "phase1_only": bool(args.phase1_only),
        "stage_a_requested": bool(args.stage_a),
        "stage_b_requested": bool(args.stage_b),
        "stage_c_requested": bool(args.stage_c),
        "smoke": bool(args.smoke),
        "stage_a_full_gradient_instance_count": len(focus_instances(repo_root, reps=(1,))),
        "stage_b_c_full_gradient_instance_count": len(focus_instances(repo_root, reps=(1, 2, 3))),
        "stage_a_full_default_task_count": len(SOURCE_BOUND_BATTERIES)
        * len(DEFAULT_CONSTRAINT_SCENARIOS)
        * len(focus_instances(repo_root, reps=(1,)))
        * len(VARIANT_ORDER),
        "resume": bool(args.resume),
        "retry_timeouts": bool(args.retry_timeouts),
        "workers": int(args.workers),
        "started_perf_counter": started,
        "diagnostic_artifact_commit": "PENDING_COMMIT",
    }


def run_task_grid(
    repo_root: Path,
    output_dir: Path,
    args: argparse.Namespace,
    *,
    phase: str,
    instances: list[str],
    batteries: list[float],
    constraint_scenarios: list[str],
    seeds: list[int],
    eval_budget: int,
    runtime_caps: tuple[float, float, float],
    allowed_pairs: set[tuple[float, str]] | None = None,
) -> list[dict[str, Any]]:
    tasks = build_tasks(phase, instances, batteries, constraint_scenarios, seeds, eval_budget, runtime_caps, allowed_pairs=allowed_pairs)
    completed = load_completed_rows(output_dir, phase, retry_timeouts=bool(args.retry_timeouts)) if args.resume else {}
    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for task in tasks:
        existing = completed.get(task_key(task))
        if existing is None:
            pending.append(task)
        else:
            rows.append(existing)
    b9k.write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, pending))
    b9k.write_csv(output_dir / f"{phase}_raw_runs.partial.csv", b9k.sorted_rows(rows))
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    workers = max(1, int(args.workers))
    if workers == 1:
        for task in pending:
            row = execute_task(repo_root, args, flags, task)
            rows.append(row)
            completed[task_key(row)] = row
            refresh_queue(output_dir, phase, tasks, completed, rows)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(execute_task, repo_root, args, flags, task): task for task in pending}
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                completed[task_key(row)] = row
                refresh_queue(output_dir, phase, tasks, completed, rows)
    return b9k.sorted_rows(rows)


def build_tasks(
    phase: str,
    instances: list[str],
    batteries: list[float],
    constraint_scenarios: list[str],
    seeds: list[int],
    eval_budget: int,
    runtime_caps: tuple[float, float, float],
    *,
    allowed_pairs: set[tuple[float, str]] | None = None,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for battery in batteries:
        for scenario in constraint_scenarios:
            pair = (round(float(battery), 6), str(scenario))
            if allowed_pairs is not None and pair not in allowed_pairs:
                continue
            for item in instances:
                category, instance = item.split("/", 1)
                cap = runtime_cap(instance, runtime_caps)
                for seed in seeds:
                    for variant in VARIANT_ORDER:
                        tasks.append(
                            {
                                "phase": phase,
                                "battery_kwh": float(battery),
                                "constraint_scenario": str(scenario),
                                "category": category,
                                "instance": instance,
                                "seed": int(seed),
                                "variant": variant,
                                "eval_budget": int(eval_budget),
                                "runtime_cap_seconds": float(cap),
                            }
                        )
    return tasks


def execute_task(repo_root: Path, args: argparse.Namespace, flags: dict[str, str], task: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--repo-root",
        str(repo_root),
        "--single-run",
        "--single-phase",
        str(task["phase"]),
        "--single-category",
        str(task["category"]),
        "--single-instance",
        str(task["instance"]),
        "--single-variant",
        str(task["variant"]),
        "--single-seed",
        str(task["seed"]),
        "--single-battery-kwh",
        str(task["battery_kwh"]),
        "--single-constraint-scenario",
        str(task["constraint_scenario"]),
        "--single-eval-budget",
        str(task["eval_budget"]),
        "--single-runtime-cap",
        str(task["runtime_cap_seconds"]),
    ]
    timeout = float(task["runtime_cap_seconds"]) + float(args.task_timeout_buffer)
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return timeout_row(repo_root, task, timeout, time.perf_counter() - started, exc)
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except Exception as exc:  # noqa: BLE001
        return subprocess_error_row(repo_root, task, "JSON_PARSE_ERROR", completed.returncode, time.perf_counter() - started, stdout, completed.stderr, repr(exc))
    if completed.returncode != 0 and payload.get("status") not in {"INIT_INFEASIBLE", "CAP_VIOLATION"}:
        return subprocess_error_row(repo_root, task, "SUBPROCESS_NONZERO", completed.returncode, time.perf_counter() - started, stdout, completed.stderr, "")
    payload.setdefault("subprocess_returncode", int(completed.returncode))
    payload.setdefault("subprocess_stdout_tail", b9k.tail_text(stdout))
    payload.setdefault("subprocess_stderr_tail", b9k.tail_text(completed.stderr))
    return payload


def single_run_cli(repo_root: Path, args: argparse.Namespace) -> int:
    row = run_one(
        repo_root,
        str(args.single_phase),
        str(args.single_category),
        str(args.single_instance),
        str(args.single_variant),
        int(args.single_seed),
        float(args.single_battery_kwh),
        str(args.single_constraint_scenario),
        int(args.single_eval_budget),
        float(args.single_runtime_cap),
        e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False),
    )
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 1 if row.get("status") in COLLECTION_FAILURE_STATUSES else 0


def run_one(
    repo_root: Path,
    phase: str,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    battery_kwh: float,
    constraint_scenario: str,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    original_bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
    meta = g09n.single_fleet_meta(repo_root, category, instance)
    spec = constraint_for_scenario(meta, constraint_scenario)
    prices = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=float(battery_kwh))
    row = base_run_row(repo_root, phase, category, instance, variant, seed, battery_kwh, spec, eval_budget, runtime_cap_seconds, flags)
    try:
        with temporary_bundle_with_station_caps(original_bundle_dir, spec) as bundle_dir:
            bundle = load_search_bundle(bundle_dir)
            policy = policy_for_variant(variant, spec)
            cv_seed = build_initial_solution(
                bundle.instance,
                bundle.carbon_profile,
                prices,
                fleet_limits=FleetLimits(cv=UNBOUNDED_FLEET, ev=0, source="09q cv precheck"),
                introduce_ev=False,
                require_charging_signal=False,
            )
            cv_seed_counts = route_counts(cv_seed)
            row.update(
                {
                    "cap_precheck_cv_seed_routes": cv_seed_counts["route_count"],
                    "cap_precheck_cv_seed_cv_routes": cv_seed_counts["cv_route_count"],
                }
            )
            precheck = cap_precheck_error(variant, spec, cv_seed_counts["route_count"])
            if precheck:
                raise ValueError(precheck)
            warm = build_initial_solution(
                bundle.instance,
                bundle.carbon_profile,
                prices,
                fleet_limits=FleetLimits(cv=policy.max_cv, ev=policy.max_ev, source=f"09q {constraint_scenario} {variant}"),
                introduce_ev=variant != "cv_shell" and policy.max_ev > 0,
                require_charging_signal=False,
            )
            warm_counts = route_counts(warm)
            row.update(
                {
                    "warm_route_count": warm_counts["route_count"],
                    "warm_cv_route_count": warm_counts["cv_route_count"],
                    "warm_ev_route_count": warm_counts["ev_route_count"],
                }
            )
            if warm_counts["cv_route_count"] > policy.max_cv or warm_counts["ev_route_count"] > policy.max_ev:
                raise ValueError(
                    "cap-aware warm start exceeds cap "
                    f"(cv={warm_counts['cv_route_count']}/{policy.max_cv}, ev={warm_counts['ev_route_count']}/{policy.max_ev})"
                )
            with b9k.temporary_env(flags):
                result = run_alns_wouda(
                    bundle_dir,
                    iterations=None,
                    seed=seed,
                    eval_budget=eval_budget,
                    max_runtime_seconds=runtime_cap_seconds,
                    policy=policy,
                    initial_solution=warm,
                    prices=prices,
                )
            solution = result.best_solution
            metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
            violations = check_solution(solution, bundle.instance, prices)
            counts = route_counts(solution)
            cap_violation = counts["cv_route_count"] > policy.max_cv or counts["ev_route_count"] > policy.max_ev
            row.update(b9k.metric_subset(metrics))
            row.update(g09l.solution_share_metrics(solution, bundle))
            row.update(charging_and_route_audit(solution, bundle, prices))
            row.update(
                {
                    "status": "CAP_VIOLATION" if cap_violation else ("OK" if not violations else "VIOLATION"),
                    "elapsed_seconds": time.perf_counter() - started,
                    "actual_evals": int(result.evaluations),
                    "best_penalized_obj": float(result.best_obj),
                    "solver_reported_feasible": bool(result.feasible),
                    "violation_count": len(violations),
                    "station_capacity_violation_count": sum(1 for violation in violations if violation.type == STATION_CAPACITY),
                    "route_count": counts["route_count"],
                    "cv_route_count": counts["cv_route_count"],
                    "ev_route_count": counts["ev_route_count"],
                    "composition": classify_composition(counts["cv_route_count"], counts["ev_route_count"]),
                    "ev_route_share": safe_div(counts["ev_route_count"], counts["route_count"]),
                    "cv_route_share": safe_div(counts["cv_route_count"], counts["route_count"]),
                    "cap_violation": cap_violation,
                }
            )
    except ValueError as exc:
        message = str(exc)
        status = "INIT_INFEASIBLE" if infeasible_message(message) else "ERROR"
        row.update(
            {
                "status": status,
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": 0,
                "violation_count": -1,
                "station_capacity_violation_count": -1,
                "route_count": 0,
                "cv_route_count": 0,
                "ev_route_count": 0,
                "composition": "infeasible" if status == "INIT_INFEASIBLE" else "error",
                "total_cost": math.inf,
                "cap_violation": False,
                "error_type": type(exc).__name__,
                "error": message,
            }
        )
    except Exception as exc:  # noqa: BLE001
        row.update(
            {
                "status": "ERROR",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": 0,
                "violation_count": -1,
                "station_capacity_violation_count": -1,
                "route_count": 0,
                "cv_route_count": 0,
                "ev_route_count": 0,
                "composition": "error",
                "total_cost": math.inf,
                "cap_violation": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return row


@contextmanager
def temporary_bundle_with_station_caps(bundle_dir: Path, spec: ConstraintSpec) -> Iterable[Path]:
    if spec.depot_chargers is None and spec.public_chargers is None:
        yield bundle_dir
        return
    with tempfile.TemporaryDirectory(prefix="setp_09q_bundle_") as tmp:
        tmp_dir = Path(tmp)
        data = json.loads((bundle_dir / "instance.json").read_text(encoding="utf-8"))
        for node in data.get("nodes", []):
            node_type = str(node.get("node_type", "")).lower()
            if node_type == "d" and spec.depot_chargers is not None:
                node["station_chargers"] = int(spec.depot_chargers)
                node["station_capacity"] = int(spec.depot_chargers)
            if node_type == "f" and spec.public_chargers is not None:
                node["station_chargers"] = int(spec.public_chargers)
                node["station_capacity"] = int(spec.public_chargers)
        (tmp_dir / "instance.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        for name in ("distance_matrix.npy", "carbon_profile.csv", "scenario_manifest.json"):
            src = bundle_dir / name
            if src.exists():
                try:
                    os.symlink(src, tmp_dir / name)
                except OSError:
                    shutil.copy2(src, tmp_dir / name)
        yield tmp_dir


def constraint_for_scenario(meta: g09n.FleetMeta, scenario: str) -> ConstraintSpec:
    if scenario == "unbounded_reference":
        return ConstraintSpec(scenario, UNBOUNDED_FLEET, UNBOUNDED_FLEET, None, None, "reference_only", "none", False, "Current solver/search-shell reference.")
    if scenario == "goeke_ev_cap_only":
        return ConstraintSpec(scenario, UNBOUNDED_FLEET, meta.manifest_num_ev, None, None, "source_backed_diagnostic", "ev_fleet_capital", False, "Cap EV route count by Goeke/ReSETP metadata; CV remains flexible.")
    if scenario == "goeke_total_cap":
        return ConstraintSpec(scenario, meta.manifest_num_cv, meta.manifest_num_ev, None, None, "source_backed_diagnostic", "fleet_capital", False, "Cap CV and EV route count by Goeke/ReSETP metadata.")
    if scenario == "depot_chargers_manifest_ev_diagnostic":
        return ConstraintSpec(scenario, UNBOUNDED_FLEET, UNBOUNDED_FLEET, max(1, meta.manifest_num_ev), None, "diagnostic_only", "depot_charging_capacity", False, "Set each depot's chargers to manifest EV count; diagnostic proxy only.")
    if scenario == "depot_chargers_manifest_total_diagnostic":
        return ConstraintSpec(scenario, UNBOUNDED_FLEET, UNBOUNDED_FLEET, max(1, meta.manifest_num_cv + meta.manifest_num_ev), None, "diagnostic_only", "depot_charging_capacity", False, "Set each depot's chargers to manifest total vehicle count; diagnostic proxy only.")
    if scenario == "public_charging_disabled_diagnostic":
        return ConstraintSpec(scenario, UNBOUNDED_FLEET, UNBOUNDED_FLEET, None, 0, "diagnostic_only", "public_charging_availability", False, "Set public station chargers to zero to test public charging dependency.")
    if scenario == "depot_manifest_ev_no_public_diagnostic":
        return ConstraintSpec(scenario, UNBOUNDED_FLEET, UNBOUNDED_FLEET, max(1, meta.manifest_num_ev), 0, "diagnostic_only", "charging_capacity_combo", False, "Combine manifest-EV depot charger proxy with no public charging.")
    raise ValueError(f"unknown constraint scenario: {scenario}")


def policy_for_variant(variant: str, spec: ConstraintSpec) -> SearchPolicy:
    if variant == "cv_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=spec.max_cv, max_ev=0)
    if variant == "ev_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=0, max_ev=spec.max_ev)
    if variant == "free_mixed":
        return SearchPolicy(require_charging_signal=False, max_cv=spec.max_cv, max_ev=spec.max_ev)
    raise ValueError(f"unknown variant: {variant}")


def cap_precheck_error(variant: str, spec: ConstraintSpec, cv_seed_routes: int) -> str:
    if spec.scenario == "unbounded_reference":
        return ""
    if variant == "cv_shell" and spec.max_cv < cv_seed_routes:
        return f"cap precheck infeasible: cv_shell cap {spec.max_cv} < deterministic CV seed route count {cv_seed_routes}"
    if variant == "ev_shell" and spec.max_ev < cv_seed_routes:
        return f"cap precheck infeasible: ev_shell cap {spec.max_ev} < deterministic CV seed route count {cv_seed_routes}"
    if variant == "free_mixed" and (spec.max_cv + spec.max_ev) < cv_seed_routes:
        return f"cap precheck infeasible: total cap {spec.max_cv + spec.max_ev} < deterministic CV seed route count {cv_seed_routes}"
    return ""


def charging_and_route_audit(solution: Solution, bundle: SearchBundle, prices: PriceParameters) -> dict[str, Any]:
    audit = g09o.charging_audit(solution, bundle.instance)
    distances = []
    ev_distances = []
    ev_kwh = []
    ev_needs_charge = 0
    public_ev_ids = set()
    depot_ev_ids = set()
    for action in solution.charging_actions:
        node = {node.node_id: node for node in bundle.instance.nodes}.get(action.station_id)
        if node and node.node_type.lower() == "f":
            public_ev_ids.add(action.vehicle_id)
        if node and node.node_type.lower() == "d":
            depot_ev_ids.add(action.vehicle_id)
    for route in solution.routes:
        distance = float(route_distance(route, bundle.instance))
        distances.append(distance)
        if route.vehicle_type.lower() == "ev":
            ev_distances.append(distance)
            summary = route_ev_energy_summary(route, bundle.instance, prices)
            ev_kwh.append(float(summary.ev_kwh))
            ev_needs_charge += int(bool(summary.needs_charge))
    audit.update(
        {
            "mean_route_distance_m": mean(distances),
            "max_route_distance_m": max(distances) if distances else 0.0,
            "mean_ev_route_distance_m": mean(ev_distances),
            "max_ev_route_distance_m": max(ev_distances) if ev_distances else 0.0,
            "mean_ev_drive_kwh": mean(ev_kwh),
            "max_ev_drive_kwh": max(ev_kwh) if ev_kwh else 0.0,
            "ev_routes_drive_kwh_over_battery": ev_needs_charge,
        }
    )
    return audit


def base_run_row(
    repo_root: Path,
    phase: str,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    battery_kwh: float,
    spec: ConstraintSpec,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    return {
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "phase": phase,
        "battery_kwh": float(battery_kwh),
        "constraint_scenario": spec.scenario,
        "constraint_source_class": spec.source_class,
        "constraint_mechanism": spec.mechanism,
        "constraint_promotable": spec.promotable,
        "max_cv": spec.max_cv,
        "max_ev": spec.max_ev,
        "depot_chargers_override": "" if spec.depot_chargers is None else spec.depot_chargers,
        "public_chargers_override": "" if spec.public_chargers is None else spec.public_chargers,
        "category": category,
        "instance": instance,
        "size": b9k.customer_count(instance),
        "variant": variant,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": CARBON_PRICE,
        "active_flags": json.dumps(flags, sort_keys=True),
    }


def winner_rows_from_raw(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, float, str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                str(row["phase"]),
                round(float(row["battery_kwh"]), 6),
                str(row["constraint_scenario"]),
                str(row["category"]),
                str(row["instance"]),
                int(row["seed"]),
            )
        ].append(row)
    winners: list[dict[str, Any]] = []
    for (phase, battery, scenario, category, instance, seed), candidates in sorted(grouped.items()):
        feasible = [row for row in candidates if row.get("status") == "OK" and int(float(row.get("violation_count", 999))) == 0]
        if not feasible:
            winners.append(
                {
                    "phase": phase,
                    "battery_kwh": battery,
                    "constraint_scenario": scenario,
                    "category": category,
                    "instance": instance,
                    "seed": seed,
                    "size": b9k.customer_count(instance),
                    "winner_status": "NO_FEASIBLE_ROW",
                    "no_feasible_statuses": ";".join(sorted({str(row.get("status", "")) for row in candidates})),
                }
            )
            continue
        best = min(feasible, key=lambda row: float(row["total_cost"]))
        winner = {
            "phase": phase,
            "battery_kwh": battery,
            "constraint_scenario": scenario,
            "constraint_source_class": best.get("constraint_source_class", ""),
            "constraint_mechanism": best.get("constraint_mechanism", ""),
            "constraint_promotable": truthy(best.get("constraint_promotable")),
            "category": category,
            "instance": instance,
            "seed": seed,
            "size": b9k.customer_count(instance),
            "winner_status": "OK",
            "winner_variant": best["variant"],
            "winner_total_cost": float(best["total_cost"]),
            "winner_composition": best["composition"],
            "winner_route_count": int(float(best["route_count"])),
            "winner_cv_route_count": int(float(best["cv_route_count"])),
            "winner_ev_route_count": int(float(best["ev_route_count"])),
            "winner_ev_route_share": float(best.get("ev_route_share", 0.0)),
            "winner_ev_customer_share": float(best.get("ev_customer_share", math.nan)),
            "winner_ev_demand_share": float(best.get("ev_demand_share", math.nan)),
            "winner_ev_distance_share": float(best.get("ev_distance_share", math.nan)),
            "winner_depot_charging_energy_share": float(best.get("depot_charging_energy_share", 0.0)),
            "winner_public_charging_energy_share": float(best.get("public_charging_energy_share", 0.0)),
            "winner_ev_routes_with_public_charge": int(float(best.get("ev_routes_with_public_charge", 0) or 0)),
            "winner_depot_peak_concurrent_at_one_depot": int(float(best.get("depot_peak_concurrent_at_one_depot", 0) or 0)),
            "winner_depot_peak_capacity": best.get("depot_peak_capacity", ""),
            "winner_public_peak_concurrent_at_one_station": int(float(best.get("public_peak_concurrent_at_one_station", 0) or 0)),
            "winner_station_capacity_violation_count": int(float(best.get("station_capacity_violation_count", 0) or 0)),
            "winner_max_ev_route_distance_m": float(best.get("max_ev_route_distance_m", math.nan)),
            "winner_max_ev_drive_kwh": float(best.get("max_ev_drive_kwh", math.nan)),
            "winner_ev_routes_drive_kwh_over_battery": int(float(best.get("ev_routes_drive_kwh_over_battery", 0) or 0)),
        }
        for row in feasible:
            prefix = str(row["variant"])
            winner[f"{prefix}_cost"] = float(row["total_cost"])
            winner[f"{prefix}_composition"] = row["composition"]
            winner[f"{prefix}_ev_route_share"] = float(row.get("ev_route_share", 0.0))
        winners.append(winner)
    return winners


def by_scale_rows(winners: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    groups: dict[tuple[float, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        groups[(float(row["battery_kwh"]), str(row["constraint_scenario"]), str(row["category"]), int(float(row.get("size", 0))))].append(row)
    rows: list[dict[str, Any]] = []
    for (battery, scenario, category, size), items in sorted(groups.items()):
        ok = [row for row in items if row.get("winner_status") == "OK"]
        route = [float(row["winner_ev_route_share"]) for row in ok]
        customer = [float(row["winner_ev_customer_share"]) for row in ok]
        demand = [float(row["winner_ev_demand_share"]) for row in ok]
        distance = [float(row["winner_ev_distance_share"]) for row in ok]
        mean_route = mean(route)
        mean_customer = mean(customer)
        mean_demand = mean(demand)
        mean_distance = mean(distance)
        counts = composition_counts(ok)
        rows.append(
            {
                "phase": phase,
                "battery_kwh": battery,
                "constraint_scenario": scenario,
                "category": category,
                "size": size,
                "winner_count": len(ok),
                "expected_winner_rows": len(items),
                "missing_or_infeasible_winner_rows": len(items) - len(ok),
                "mean_ev_route_share": csv_number(mean_route),
                "mean_ev_customer_share": csv_number(mean_customer),
                "mean_ev_demand_share": csv_number(mean_demand),
                "mean_ev_distance_share": csv_number(mean_distance),
                "route_share_in_practical_band": in_band(mean_route),
                "fake_balance_flag": fake_balance(mean_route, mean_customer, mean_demand, mean_distance),
                "all_ev_count": counts.get("all_ev", 0),
                "ev_heavy_count": counts.get("ev_heavy_mixed", 0),
                "balanced_count": counts.get("balanced_mixed", 0),
                "cv_heavy_count": counts.get("cv_heavy_mixed", 0),
                "all_cv_count": counts.get("all_cv", 0),
                "mean_depot_charging_energy_share": csv_number(mean(float(row.get("winner_depot_charging_energy_share", 0.0)) for row in ok)),
                "mean_public_charging_energy_share": csv_number(mean(float(row.get("winner_public_charging_energy_share", 0.0)) for row in ok)),
                "max_depot_peak_concurrent": max((int(float(row.get("winner_depot_peak_concurrent_at_one_depot", 0) or 0)) for row in ok), default=0),
                "public_charge_route_total": sum(int(float(row.get("winner_ev_routes_with_public_charge", 0) or 0)) for row in ok),
            }
        )
    return rows


def scenario_summary_rows(
    winners: list[dict[str, Any]],
    by_scale: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    phase: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[float, str], list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        grouped[(float(row["battery_kwh"]), str(row["constraint_scenario"]))].append(row)
    scale_grouped: dict[tuple[float, str], list[dict[str, Any]]] = defaultdict(list)
    for row in by_scale:
        scale_grouped[(float(row["battery_kwh"]), str(row["constraint_scenario"]))].append(row)
    raw_grouped: dict[tuple[float, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        raw_grouped[(float(row["battery_kwh"]), str(row["constraint_scenario"]))].append(row)
    rows: list[dict[str, Any]] = []
    for (battery, scenario), items in sorted(grouped.items()):
        ok = [row for row in items if row.get("winner_status") == "OK"]
        raw = raw_grouped.get((battery, scenario), [])
        scale_rows = scale_grouped.get((battery, scenario), [])
        route = [float(row["winner_ev_route_share"]) for row in ok]
        customer = [float(row["winner_ev_customer_share"]) for row in ok]
        demand = [float(row["winner_ev_demand_share"]) for row in ok]
        distance = [float(row["winner_ev_distance_share"]) for row in ok]
        counts = composition_counts(ok)
        instance_pass = instance_majority_pass_count(ok)
        scale_pass = sum(truthy(row.get("route_share_in_practical_band")) for row in scale_rows)
        fake_count = sum(truthy(row.get("fake_balance_flag")) for row in scale_rows)
        total_instances = len({(str(row["category"]), str(row["instance"])) for row in items})
        expected_winners = len(items)
        source_class = next((str(row.get("constraint_source_class", "")) for row in ok if row.get("constraint_source_class")), source_class_for_scenario(scenario))
        status = stage_status(len(ok), expected_winners, instance_pass, total_instances, scale_pass, len(scale_rows), fake_count)
        rows.append(
            {
                "phase": phase,
                "battery_kwh": battery,
                "constraint_scenario": scenario,
                "constraint_source_class": source_class,
                "constraint_mechanism": mechanism_for_scenario(scenario),
                "scenario_stage_status": status,
                "promotable": scenario in SOURCE_PROMOTABLE_SCENARIOS,
                "winner_count": len(ok),
                "expected_winner_rows": expected_winners,
                "total_instances": total_instances,
                "instance_majority_pass_count": instance_pass,
                "instance_majority_fail_count": max(0, total_instances - instance_pass),
                "scale_bucket_pass_count": scale_pass,
                "scale_bucket_fail_count": max(0, len(scale_rows) - scale_pass),
                "scale_bucket_count": len(scale_rows),
                "fake_balance_bucket_count": fake_count,
                "mean_ev_route_share": csv_number(mean(route)),
                "mean_ev_customer_share": csv_number(mean(customer)),
                "mean_ev_demand_share": csv_number(mean(demand)),
                "mean_ev_distance_share": csv_number(mean(distance)),
                "min_ev_route_share": csv_number(min(route) if route else math.nan),
                "max_ev_route_share": csv_number(max(route) if route else math.nan),
                "all_ev_winner_count": counts.get("all_ev", 0),
                "ev_heavy_winner_count": counts.get("ev_heavy_mixed", 0),
                "balanced_winner_count": counts.get("balanced_mixed", 0),
                "cv_heavy_winner_count": counts.get("cv_heavy_mixed", 0),
                "all_cv_winner_count": counts.get("all_cv", 0),
                "raw_rows": len(raw),
                "raw_ok_rows": sum(row.get("status") == "OK" for row in raw),
                "raw_init_infeasible_rows": sum(row.get("status") == "INIT_INFEASIBLE" for row in raw),
                "raw_cap_violation_rows": sum(row.get("status") == "CAP_VIOLATION" for row in raw),
                "raw_timeout_error_rows": sum(row.get("status") in COLLECTION_FAILURE_STATUSES for row in raw),
            }
        )
    return rows


def failure_instance_rows(winners: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    groups: dict[tuple[float, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        groups[(float(row["battery_kwh"]), str(row["constraint_scenario"]), str(row["category"]), str(row["instance"]))].append(row)
    rows: list[dict[str, Any]] = []
    for (battery, scenario, category, instance), items in sorted(groups.items()):
        ok = [row for row in items if row.get("winner_status") == "OK"]
        in_band_count = sum(1 for row in ok if in_band(float(row["winner_ev_route_share"])))
        required = math.floor(len(ok) / 2) + 1 if ok else 1
        mean_route = mean(float(row["winner_ev_route_share"]) for row in ok)
        mean_customer = mean(float(row["winner_ev_customer_share"]) for row in ok)
        mean_demand = mean(float(row["winner_ev_demand_share"]) for row in ok)
        mean_distance = mean(float(row["winner_ev_distance_share"]) for row in ok)
        is_fake = fake_balance(mean_route, mean_customer, mean_demand, mean_distance)
        if ok and in_band_count >= required and not is_fake:
            continue
        rows.append(
            {
                "phase": phase,
                "battery_kwh": battery,
                "constraint_scenario": scenario,
                "category": category,
                "instance": instance,
                "size": b9k.customer_count(instance),
                "winner_count": len(ok),
                "in_band_count": in_band_count,
                "required_majority": required,
                "mean_ev_route_share": csv_number(mean_route),
                "mean_ev_customer_share": csv_number(mean_customer),
                "mean_ev_demand_share": csv_number(mean_demand),
                "mean_ev_distance_share": csv_number(mean_distance),
                "reason": "missing_or_infeasible" if not ok else ("fake_balance" if is_fake else "route_share_outside_practical_band"),
            }
        )
    return rows


def summarize_conclusion(
    args: argparse.Namespace,
    phase0: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    stage_a_summary: list[dict[str, Any]],
    stage_b_summary: list[dict[str, Any]],
    stage_c_summary: list[dict[str, Any]],
) -> dict[str, Any]:
    if phase0.get("status") != "OK":
        return {"verdict": "HALT_OVERRIDE_NOT_TRUSTWORTHY", "interpretation": "Battery or temporary station-capacity override audit failed.", "phase0": phase0}
    failures = [row for row in raw_rows if row.get("status") in COLLECTION_FAILURE_STATUSES]
    if failures:
        return {"verdict": "HALT_COLLECTION_COST", "interpretation": "At least one required optimization task timed out or errored; do not draw a scientific conclusion.", "failed_rows": len(failures)}
    cap_violations = [row for row in raw_rows if row.get("status") == "CAP_VIOLATION"]
    if cap_violations:
        return {"verdict": "HALT_OVERRIDE_NOT_TRUSTWORTHY", "interpretation": "At least one final solution exceeded its diagnostic fleet cap.", "cap_violation_rows": len(cap_violations)}
    if args.phase0_only:
        return {"verdict": "PHASE0_ONLY", "interpretation": "Only evidence and override audits were run."}
    if args.phase1_only or not raw_rows:
        return {"verdict": "PHASE1_ONLY", "interpretation": "Only existing 09l/09n/09o evidence was mapped; no new optimization rows were run."}
    if args.smoke:
        return {
            "verdict": "SMOKE_ONLY",
            "interpretation": "Smoke optimization rows completed; this validates the runner path but is not a scientific gate conclusion.",
            "raw_rows": len(raw_rows),
        }

    decision = stage_c_summary or stage_b_summary or stage_a_summary
    decision_stage = "stage_c" if stage_c_summary else ("stage_b" if stage_b_summary else "stage_a")
    pass_rows = [row for row in decision if str(row.get("scenario_stage_status")) == "pass"]
    promotable_pass = [row for row in pass_rows if truthy(row.get("promotable"))]
    diagnostic_pass = [row for row in pass_rows if not truthy(row.get("promotable"))]
    near_rows = [row for row in decision if str(row.get("scenario_stage_status")) == "near_pass"]
    if promotable_pass and decision_stage == "stage_c":
        verdict = "SOURCE_BOUND_OPERATIONAL_MIX_FOUND"
        interpretation = "A source-promotable battery plus operational constraint passed the Stage C 10-200 full-gradient stability gate."
    elif pass_rows and decision_stage == "stage_c":
        verdict = "ONLY_DIAGNOSTIC_NO_SOURCE"
        interpretation = "Only diagnostic/non-promotable constraints passed Stage C; do not formalize without better evidence."
    elif pass_rows or near_rows:
        verdict = "SOURCE_BOUND_OPERATIONAL_NEAR_NEEDS_CONFIRMATION"
        interpretation = "Stage screen found pass/near-pass combinations, but they are not yet a Stage C promotable conclusion."
    elif decision:
        verdict = "BATTERY_OPERATION_COMBINATION_INSUFFICIENT"
        interpretation = "No tested battery x operational-constraint combination kept the required 10-200 full-gradient screen inside the practical mixed band."
    else:
        verdict = "HALT_COLLECTION_COST"
        interpretation = "No decision-stage summary was produced."
    return {
        "verdict": verdict,
        "interpretation": interpretation,
        "decision_stage": decision_stage,
        "passing_pairs": [f"{row['battery_kwh']}:{row['constraint_scenario']}" for row in pass_rows],
        "promotable_passing_pairs": [f"{row['battery_kwh']}:{row['constraint_scenario']}" for row in promotable_pass],
        "diagnostic_passing_pairs": [f"{row['battery_kwh']}:{row['constraint_scenario']}" for row in diagnostic_pass],
        "near_pairs": [f"{row['battery_kwh']}:{row['constraint_scenario']}" for row in near_rows],
        "raw_rows": len(raw_rows),
        "stage_a_rows": len([row for row in raw_rows if row.get("phase") == "stage_a"]),
        "stage_b_rows": len([row for row in raw_rows if row.get("phase") == "stage_b"]),
        "stage_c_rows": len([row for row in raw_rows if row.get("phase") == "stage_c"]),
    }


def render_report(
    metadata: dict[str, Any],
    phase0: dict[str, Any],
    battery_rows: list[dict[str, Any]],
    constraint_rows: list[dict[str, Any]],
    phase1_summary: list[dict[str, Any]],
    stage_a_summary: list[dict[str, Any]],
    stage_a_by_scale: list[dict[str, Any]],
    stage_a_failures: list[dict[str, Any]],
    stage_b_summary: list[dict[str, Any]],
    stage_b_by_scale: list[dict[str, Any]],
    stage_b_failures: list[dict[str, Any]],
    stage_c_summary: list[dict[str, Any]],
    stage_c_by_scale: list[dict[str, Any]],
    stage_c_failures: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09q Source-Bound Battery x Operational-Constraint Mix Map",
        "",
        f"Commit: `{metadata['commit_hash'][:8]}`.",
        f"Python: `{metadata['python']}`; NumPy: `{metadata['numpy']}`.",
        f"Frozen defaults: `B_battery_kwh={metadata['default_B_battery_kwh']}`, `v_speed_ms={metadata['v_speed_ms']}`, `carbon_price={metadata['carbon_price']}`.",
        "This runner does not change `prices.py`, generated bundles, `cost.py`, `check.py`, `evaluation.py`, or algorithm semantics.",
        f"Command: `{metadata['command']}`.",
        "",
        "## Verdict",
        "",
        f"`{conclusion['verdict']}`.",
        "",
        conclusion.get("interpretation", ""),
        "",
        "Plain reading: 09o was a useful but narrow 280kWh clue. This report treats it as one row in a broader map; the decision unit is now a battery value plus an operational mechanism across the available 10-200 full-gradient stability instances.",
        "",
        "## Phase 0/1 Checks",
        "",
        f"- Override audit: `{phase0.get('status')}`.",
        f"- Battery candidates selected: `{', '.join(str(v) for v in metadata['tested_battery_values'])}`.",
        f"- Constraint scenarios selected: `{', '.join(metadata['constraint_scenarios'])}`.",
        f"- Full Stage A default task count: `{metadata['stage_a_full_default_task_count']}` child tasks over `{metadata['stage_a_full_gradient_instance_count']}` `-01` instances.",
        f"- Full Stage B/C default instance count: `{metadata['stage_b_c_full_gradient_instance_count']}` stability instances.",
        "- `80kWh` remains a historical reference only and is not a main candidate in this runner.",
        "",
        "## Existing Evidence Recap",
        "",
    ]
    if phase1_summary:
        lines.append("| source | category | battery | rows | in-band | fake balance | EV over manifest | mean EV route |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for row in phase1_summary[:60]:
            lines.append(
                f"| {row['source_artifact']} | {row['category']} | {fmt(row['battery_kwh'])} | {row['rows']} | "
                f"{row['in_band_rows']} | {row['fake_balance_rows']} | {row['ev_over_manifest_rows']} | {fmt(row['mean_ev_route_share'])} |"
            )
    else:
        lines.append("No existing 09l/09o rows were available to summarize.")
    lines.extend(["", "## Battery Sources", ""])
    lines.append("| battery | eligible | secondary | source ids |")
    lines.append("|---:|---|---|---|")
    for row in battery_rows:
        if not truthy(row.get("selected_for_09q")) and not truthy(row.get("reference_only_09q")):
            continue
        lines.append(
            f"| {fmt(row['battery_kwh'])} | {row.get('main_candidate_eligible')} | {row.get('secondary_only')} | {row.get('source_ids', '')} |"
        )
    lines.extend(["", "## Operational Constraint Scenarios", ""])
    compact_constraints = unique_constraint_rows(constraint_rows)
    lines.append("| scenario | mechanism | source class | promotable | max/charger rule |")
    lines.append("|---|---|---|---|---|")
    for row in compact_constraints:
        rule = f"max_cv={row['max_cv']}, max_ev={row['max_ev']}, depot_chargers={row['depot_chargers']}, public_chargers={row['public_chargers']}"
        lines.append(f"| {row['constraint_scenario']} | {row['mechanism']} | {row['source_class']} | {row['promotable']} | {rule} |")
    append_stage(lines, "Stage A", stage_a_summary, stage_a_by_scale, stage_a_failures)
    append_stage(lines, "Stage B", stage_b_summary, stage_b_by_scale, stage_b_failures)
    append_stage(lines, "Stage C", stage_c_summary, stage_c_by_scale, stage_c_failures)
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- `{metadata['output_dir']}/metadata.json`",
            f"- `{metadata['output_dir']}/evidence_matrix.csv`",
            f"- `{metadata['output_dir']}/battery_candidate_set.csv`",
            f"- `{metadata['output_dir']}/operational_constraint_matrix.csv`",
            f"- `{metadata['output_dir']}/phase1_existing_failure_map.csv`",
            f"- `{metadata['output_dir']}/stage_a_raw_runs.csv` / `stage_a_winners.csv` / `stage_a_scenario_summary.csv` if Stage A was run",
            f"- `{metadata['output_dir']}/conclusion.json`",
            "",
            "## Next Rule",
            "",
            "Only a Stage C pass with a source-promotable operational constraint can justify a later formal model/TeX change. Diagnostic-only passes are useful for direction, but they are not a thesis parameter by themselves.",
            "",
        ]
    )
    return "\n".join(lines)


def append_stage(lines: list[str], title: str, summary: list[dict[str, Any]], by_scale: list[dict[str, Any]], failures: list[dict[str, Any]]) -> None:
    lines.extend(["", f"## {title}", ""])
    if not summary:
        lines.append("Not run or no rows collected.")
        return
    lines.append("| battery | constraint | status | winners | pass inst | pass buckets | fake buckets | mean route/customer/demand/distance | composition counts |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---|---|")
    for row in sorted(summary, key=lambda r: (float(r["battery_kwh"]), str(r["constraint_scenario"])))[:120]:
        shares = f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
        counts = f"allCV={row['all_cv_winner_count']}, bal={row['balanced_winner_count']}, evH={row['ev_heavy_winner_count']}, allEV={row['all_ev_winner_count']}"
        lines.append(
            f"| {fmt(row['battery_kwh'])} | {row['constraint_scenario']} | {row['scenario_stage_status']} | "
            f"{row['winner_count']}/{row['expected_winner_rows']} | {row['instance_majority_pass_count']} | "
            f"{row['scale_bucket_pass_count']}/{row['scale_bucket_count']} | {row['fake_balance_bucket_count']} | {shares} | {counts} |"
        )
    if failures:
        lines.extend(["", "Top failure rows:", ""])
        lines.append("| battery | constraint | instance | reason | mean EV route/customer/demand/distance |")
        lines.append("|---:|---|---|---|---|")
        for row in failures[:40]:
            shares = f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
            lines.append(f"| {fmt(row['battery_kwh'])} | {row['constraint_scenario']} | {row['category']}/{row['instance']} | {row['reason']} | {shares} |")


def triggered_pairs(summary: list[dict[str, Any]]) -> set[tuple[float, str]]:
    pairs: set[tuple[float, str]] = set()
    for row in summary:
        status = str(row.get("scenario_stage_status"))
        if status in {"pass", "near_pass"}:
            pairs.add((round(float(row["battery_kwh"]), 6), str(row["constraint_scenario"])))
    return pairs


def stage_status(
    ok_count: int,
    expected_winners: int,
    instance_pass: int,
    total_instances: int,
    scale_pass: int,
    total_scales: int,
    fake_count: int,
) -> str:
    if ok_count < expected_winners:
        return "incomplete"
    if fake_count:
        return "fail_fake_balance"
    if total_instances and instance_pass == total_instances and total_scales and scale_pass == total_scales:
        return "pass"
    if (
        total_instances
        and instance_pass >= math.ceil(total_instances * NEAR_PASS_FRACTION)
        and total_scales
        and scale_pass >= math.ceil(total_scales * NEAR_PASS_FRACTION)
    ):
        return "near_pass"
    return "fail"


def focus_instances(repo_root: Path, reps: tuple[int, ...]) -> list[str]:
    root = repo_root / BENCHMARK_ROOT
    refs: list[str] = []
    for category in FAMILIES:
        for size in FULL_GRADIENT_SIZES:
            for rep in reps:
                name = f"e2-{category}-{size}c-{rep:02d}"
                if (root / category / name / "instance.json").exists():
                    refs.append(f"{category}/{name}")
    return refs


def smoke_instances(repo_root: Path) -> list[str]:
    candidates = ["multidepot/e2-multidepot-100c-01", "threeshift/e2-threeshift-200c-01"]
    return [item for item in candidates if (repo_root / BENCHMARK_ROOT / item / "instance.json").exists()]


def focus_instances_from_meta(meta_by_instance: dict[str, g09n.FleetMeta]) -> list[str]:
    return sorted(key for key, meta in meta_by_instance.items() if meta.size in FULL_GRADIENT_SIZES and meta.replicate in {1, 2, 3})


def replicate_number(instance: str) -> int:
    match = re.search(r"-(\d+)$", instance)
    return int(match.group(1)) if match else 0


def route_counts(solution: Solution) -> dict[str, int]:
    cv = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
    ev = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    return {"route_count": len(solution.routes), "cv_route_count": cv, "ev_route_count": ev}


def classify_composition(cv_count: int, ev_count: int) -> str:
    total = int(cv_count) + int(ev_count)
    if total <= 0:
        return "empty"
    if ev_count == 0:
        return "all_cv"
    if cv_count == 0:
        return "all_ev"
    ev_share = ev_count / total
    cv_share = cv_count / total
    if ev_share >= PRACTICAL_HIGH:
        return "ev_heavy_mixed"
    if cv_share >= PRACTICAL_HIGH:
        return "cv_heavy_mixed"
    return "balanced_mixed"


def composition_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get("winner_composition") or row.get("composition") or "")] += 1
    return dict(counts)


def instance_majority_pass_count(rows: list[dict[str, Any]]) -> int:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["category"]), str(row["instance"]))].append(row)
    count = 0
    for items in grouped.values():
        in_band_count = sum(in_band(float(row["winner_ev_route_share"])) for row in items)
        required = math.floor(len(items) / 2) + 1 if items else 1
        if items and in_band_count >= required:
            count += 1
    return count


def fake_balance(route_share: float, customer_share: float, demand_share: float, distance_share: float) -> bool:
    if not in_band(route_share):
        return False
    shares = [customer_share, demand_share, distance_share]
    usable = [value for value in shares if not math.isnan(value)]
    return any(value < PRACTICAL_LOW or value > PRACTICAL_HIGH for value in usable)


def in_band(value: float) -> bool:
    try:
        val = float(value)
    except Exception:  # noqa: BLE001
        return False
    return PRACTICAL_LOW <= val <= PRACTICAL_HIGH


def source_class_for_scenario(scenario: str) -> str:
    if scenario in REFERENCE_SCENARIOS:
        return "reference_only"
    if scenario in SOURCE_BACKED_DIAGNOSTIC_SCENARIOS:
        return "source_backed_diagnostic"
    if scenario in DIAGNOSTIC_SCENARIOS:
        return "diagnostic_only"
    return "unknown"


def mechanism_for_scenario(scenario: str) -> str:
    if scenario == "unbounded_reference":
        return "none"
    if scenario == "goeke_ev_cap_only":
        return "ev_fleet_capital"
    if scenario == "goeke_total_cap":
        return "fleet_capital"
    if "depot" in scenario and "public" in scenario:
        return "charging_capacity_combo"
    if "depot" in scenario:
        return "depot_charging_capacity"
    if "public" in scenario:
        return "public_charging_availability"
    return "unknown"


def runtime_cap(instance: str, caps: tuple[float, float, float]) -> float:
    n = b9k.customer_count(instance)
    if n >= 150:
        return float(caps[2])
    if n >= 100:
        return float(caps[1])
    return float(caps[0])


def refresh_queue(output_dir: Path, phase: str, tasks: list[dict[str, Any]], completed: dict[tuple[Any, ...], dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    b9k.write_csv(output_dir / f"{phase}_raw_runs.partial.csv", b9k.sorted_rows(rows))
    pending = [task for task in tasks if task_key(task) not in completed]
    b9k.write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, pending))


def task_queue_rows(tasks: list[dict[str, Any]], completed: dict[tuple[Any, ...], dict[str, Any]], pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending_keys = {task_key(task) for task in pending}
    rows: list[dict[str, Any]] = []
    for task in tasks:
        key = task_key(task)
        existing = completed.get(key)
        rows.append({**task, "queue_status": "pending" if key in pending_keys else "complete", "row_status": existing.get("status", "") if existing else ""})
    return rows


def load_completed_rows(output_dir: Path, phase: str, *, retry_timeouts: bool) -> dict[tuple[Any, ...], dict[str, Any]]:
    completed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for name in (f"{phase}_raw_runs.csv", f"{phase}_raw_runs.partial.csv", "raw_runs.csv"):
        path = output_dir / name
        if not path.exists() or path.stat().st_size == 0:
            continue
        for row in b9k.read_csv(path):
            if str(row.get("phase", "")) != phase:
                continue
            if row.get("status") == "TIMEOUT" and retry_timeouts:
                continue
            if row.get("status") in TERMINAL_STATUSES:
                completed[task_key(row)] = row
    return completed


def task_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row["phase"]),
        round(float(row["battery_kwh"]), 6),
        str(row["constraint_scenario"]),
        str(row["category"]),
        str(row["instance"]),
        int(row["seed"]),
        str(row["variant"]),
        int(row["eval_budget"]),
    )


def timeout_row(repo_root: Path, task: dict[str, Any], timeout: float, elapsed: float, exc: subprocess.TimeoutExpired) -> dict[str, Any]:
    return {
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "--short", "HEAD"),
        **task,
        "status": "TIMEOUT",
        "elapsed_seconds": float(elapsed),
        "task_timeout_seconds": float(timeout),
        "v_speed_ms": DEFAULT_PRICES.v_speed_ms,
        "carbon_price": CARBON_PRICE,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "ev_route_share": 0.0,
        "composition": "timeout",
        "total_cost": float("inf"),
        "subprocess_stdout_tail": b9k.tail_text(exc.stdout),
        "subprocess_stderr_tail": b9k.tail_text(exc.stderr),
    }


def subprocess_error_row(
    repo_root: Path,
    task: dict[str, Any],
    status: str,
    returncode: int,
    elapsed: float,
    stdout: str,
    stderr: str,
    error: str,
) -> dict[str, Any]:
    return {
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "--short", "HEAD"),
        **task,
        "status": status,
        "elapsed_seconds": float(elapsed),
        "subprocess_returncode": int(returncode),
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "ev_route_share": 0.0,
        "composition": "error",
        "total_cost": float("inf"),
        "subprocess_stdout_tail": b9k.tail_text(stdout),
        "subprocess_stderr_tail": b9k.tail_text(stderr),
        "error": error,
    }


def unique_constraint_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        seen.setdefault(str(row["constraint_scenario"]), row)
    return [seen[key] for key in sorted(seen)]


def read_existing_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(b9k.read_csv(path))


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def bool_value(value: Any) -> bool:
    return truthy(value)


def mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values if not math.isnan(float(value))]
    return sum(items) / len(items) if items else float("nan")


def float_or_nan(value: Any) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return float("nan")


def safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if float(denominator) else 0.0


def csv_number(value: Any) -> float | str:
    try:
        val = float(value)
    except Exception:  # noqa: BLE001
        return ""
    if math.isnan(val) or math.isinf(val):
        return ""
    return val


def fmt(value: Any) -> str:
    try:
        val = float(value)
    except Exception:  # noqa: BLE001
        return "" if value is None else str(value)
    if math.isnan(val):
        return ""
    if math.isinf(val):
        return "inf"
    return f"{val:.3f}"


def infeasible_message(message: str) -> bool:
    lowered = message.lower()
    return any(
        text in lowered
        for text in (
            "warm start",
            "unable to build",
            "unable to satisfy",
            "cap precheck infeasible",
            "exceeds cap",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
