#!/usr/bin/env python3
"""09n fleet-cap operational gate.

This diagnostic asks whether the 280kWh EV-dominant result is partly caused by
an unbounded fleet assumption.  It does not change promoted defaults, generated
bundles, cost/check/evaluation semantics, or the mathematical model.  Fleet
limits here are search-shell probes passed through ``SearchPolicy`` and audited
again after every run.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
import json
import math
import re
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable

import battery_spectrum_transition as b9k
import source_bound_mixed_band_gate as g09l
import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.fleet import FleetLimits, UNBOUNDED_FLEET
from setp_solver.search.winner_operators import e2_alns_throughput_flags
from setp_solver.solution import Solution


CARBON_PRICE = 0.05034
BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
RAW_GOEEKE_ROOT = Path("models/data_bundle/raw_instances/goeke_uk")
STRUCTURAL_JOIN = Path("baselines/e2_alns/structural_mixed_band_investigation_data/stage_a_75_200_joined.csv")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/fleet_cap_operational_gate_data")
DEFAULT_REPORT = Path("baselines/e2_alns/fleet_cap_operational_gate.md")
DEFAULT_PROMPT = Path("docs/handoff/codex_prompts/09n_fleet_cap_operational_gate.md")

FOCUS_SIZES = (75, 100, 150, 200)
FAMILIES = ("vanilla", "multidepot", "threeshift")
VARIANT_ORDER = ("free_mixed", "cv_shell", "ev_shell")
DEFAULT_CAP_SCENARIOS = ("goeke_total_cap", "goeke_ev_cap_only", "depot_scaled_cap")
REFERENCE_CAP_SCENARIOS = {"unbounded_reference"}
SOURCE_BACKED_SCENARIOS = {"goeke_total_cap", "goeke_ev_cap_only"}
DIAGNOSTIC_ONLY_SCENARIOS = {"depot_scaled_cap", "unbounded_reference"}
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
NEAR_PASS_FRACTION = 0.90


@dataclass(frozen=True)
class FleetMeta:
    category: str
    instance: str
    size: int
    replicate: int
    depots: int
    manifest_num_cv: int
    manifest_num_ev: int
    raw_num_cv: int | None
    raw_num_ev: int | None
    raw_source: str


@dataclass(frozen=True)
class CapSpec:
    scenario: str
    max_cv: int
    max_ev: int
    source_class: str
    interpretation: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    parser.add_argument("--stage-c", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retry-timeouts", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--cap-scenarios", nargs="*", default=list(DEFAULT_CAP_SCENARIOS))
    parser.add_argument("--stage-a-seeds", nargs="*", type=int, default=[1])
    parser.add_argument("--stage-b-seeds", nargs="*", type=int, default=[1, 2, 3])
    parser.add_argument("--stage-c-seeds", nargs="*", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument("--stage-a-eval-budget", type=int, default=1000)
    parser.add_argument("--stage-b-eval-budget", type=int, default=3000)
    parser.add_argument("--stage-c-eval-budget", type=int, default=16000)
    parser.add_argument("--runtime-small", type=float, default=120.0)
    parser.add_argument("--runtime-medium", type=float, default=180.0)
    parser.add_argument("--runtime-large", type=float, default=300.0)
    parser.add_argument("--runtime-confirm-small", type=float, default=300.0)
    parser.add_argument("--runtime-confirm-medium", type=float, default=600.0)
    parser.add_argument("--runtime-confirm-large", type=float, default=900.0)
    parser.add_argument("--task-timeout-buffer", type=float, default=60.0)
    parser.add_argument("--single-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-phase", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-category", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-instance", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-variant", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-cap-scenario", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-battery-kwh", type=float, default=280.0, help=argparse.SUPPRESS)
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

    raw_rows = raw_goeke_fleet_rows(repo_root)
    generated_rows = generated_fleet_rows(repo_root)
    meta_by_instance = fleet_meta_by_instance(repo_root, raw_rows, generated_rows)
    evidence_rows = evidence_matrix_rows()
    cap_rows = cap_scenario_rows(meta_by_instance, args.cap_scenarios)
    existing_audit = existing_unbounded_winner_audit(repo_root, meta_by_instance)
    phase1_summary = phase1_unbounded_summary(existing_audit)
    cap_proxy = cap_proxy_audit(repo_root, meta_by_instance, args)
    metadata = build_metadata(repo_root, args, started)

    b9k.write_csv(output_dir / "evidence_matrix.csv", evidence_rows)
    b9k.write_csv(output_dir / "raw_goeke_fleet_counts.csv", raw_rows)
    b9k.write_csv(output_dir / "generated_fleet_metadata.csv", generated_rows)
    b9k.write_csv(output_dir / "cap_scenarios.csv", cap_rows)
    b9k.write_csv(output_dir / "existing_unbounded_winner_audit.csv", existing_audit)
    b9k.write_csv(output_dir / "phase1_unbounded_summary.csv", phase1_summary)
    b9k.write_json(output_dir / "cap_proxy_audit.json", cap_proxy)

    stage_a_rows: list[dict[str, Any]] = []
    stage_b_rows: list[dict[str, Any]] = []
    stage_c_rows: list[dict[str, Any]] = []
    stage_a_winners: list[dict[str, Any]] = []
    stage_b_winners: list[dict[str, Any]] = []
    stage_c_winners: list[dict[str, Any]] = []
    stage_a_summary: list[dict[str, Any]] = []
    stage_b_summary: list[dict[str, Any]] = []
    stage_c_summary: list[dict[str, Any]] = []
    stage_a_by_scale: list[dict[str, Any]] = []
    stage_b_by_scale: list[dict[str, Any]] = []
    stage_c_by_scale: list[dict[str, Any]] = []
    stage_a_failures: list[dict[str, Any]] = []
    stage_b_failures: list[dict[str, Any]] = []
    stage_c_failures: list[dict[str, Any]] = []

    if not args.phase0_only and args.stage_a:
        stage_a_instances = smoke_instances(repo_root) if args.smoke else focus_instances(repo_root, reps=(1,))
        stage_a_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_a",
            instances=stage_a_instances,
            cap_scenarios=list(args.cap_scenarios),
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

    stage_b_scenarios = triggered_scenarios(stage_a_summary, args.cap_scenarios)
    if not args.phase0_only and args.stage_b and stage_b_scenarios:
        stage_b_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_b",
            instances=focus_instances(repo_root, reps=(1, 2, 3)),
            cap_scenarios=stage_b_scenarios,
            seeds=list(args.stage_b_seeds),
            eval_budget=int(args.stage_b_eval_budget),
            runtime_caps=(float(args.runtime_small), float(args.runtime_medium), float(args.runtime_large)),
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

    stage_c_scenarios = triggered_scenarios(stage_b_summary, stage_b_scenarios)
    if not args.phase0_only and args.stage_c and stage_c_scenarios:
        stage_c_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="stage_c",
            instances=focus_instances(repo_root, reps=(1, 2, 3)),
            cap_scenarios=stage_c_scenarios,
            seeds=list(args.stage_c_seeds),
            eval_budget=int(args.stage_c_eval_budget),
            runtime_caps=(float(args.runtime_confirm_small), float(args.runtime_confirm_medium), float(args.runtime_confirm_large)),
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

    conclusion = summarize_conclusion(
        args,
        cap_proxy,
        phase1_summary,
        all_raw,
        stage_a_summary,
        stage_b_summary,
        stage_c_summary,
        stage_b_scenarios,
        stage_c_scenarios,
    )
    metadata["elapsed_seconds"] = time.perf_counter() - started
    metadata["stage_b_triggered_scenarios"] = stage_b_scenarios
    metadata["stage_c_triggered_scenarios"] = stage_c_scenarios
    b9k.write_json(output_dir / "metadata.json", metadata)
    b9k.write_json(output_dir / "conclusion.json", conclusion)
    report_path.write_text(
        render_report(
            metadata,
            evidence_rows,
            cap_rows,
            phase1_summary,
            cap_proxy,
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
                "schema_version": "setp-09n-fleet-cap-operational-gate.v1",
                "verdict": conclusion["verdict"],
                "report": args.report_path,
                "output_dir": args.output_dir,
                "stage_a_rows": len(stage_a_rows),
                "stage_b_rows": len(stage_b_rows),
                "stage_c_rows": len(stage_c_rows),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2 if str(conclusion["verdict"]).startswith("HALT_") else 0


def raw_goeke_fleet_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = repo_root / RAW_GOEEKE_ROOT
    for size in FOCUS_SIZES:
        for path in sorted(root.glob(f"E-UK{size}_*.txt")):
            text = path.read_text(errors="ignore")
            num_veh = regex_int(text, r"numVeh\s*/([0-9]+)/")
            num_cv = regex_int(text, r"numPetrolVeh\s*/([0-9]+)/")
            num_ev = regex_int(text, r"numElectroVeh\s*/([0-9]+)/")
            rep = regex_int(path.name, rf"E-UK{size}_(\d+)\.txt") or 0
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


def generated_fleet_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in focus_instances(repo_root, reps=(1, 2, 3)):
        category, instance = key.split("/", 1)
        bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
        data = json.loads((bundle_dir / "instance.json").read_text())
        manifest = json.loads((bundle_dir / "scenario_manifest.json").read_text())
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


def fleet_meta_by_instance(repo_root: Path, raw_rows: list[dict[str, Any]], generated_rows: list[dict[str, Any]]) -> dict[str, FleetMeta]:
    raw_by_size_rep = {
        (int(row["size"]), int(row["replicate"])): row
        for row in raw_rows
        if row.get("numPetrolVeh") not in {"", None} and row.get("numElectroVeh") not in {"", None}
    }
    out: dict[str, FleetMeta] = {}
    for row in generated_rows:
        size = int(row["size"])
        rep = int(row["replicate"])
        raw = raw_by_size_rep.get((size, rep))
        raw_cv = int(raw["numPetrolVeh"]) if raw else None
        raw_ev = int(raw["numElectroVeh"]) if raw else None
        manifest_cv = int(float(row.get("manifest_num_cv") or raw_cv or 0))
        manifest_ev = int(float(row.get("manifest_num_ev") or raw_ev or 0))
        key = f"{row['category']}/{row['instance']}"
        out[key] = FleetMeta(
            category=str(row["category"]),
            instance=str(row["instance"]),
            size=size,
            replicate=rep,
            depots=int(row["depots"]),
            manifest_num_cv=manifest_cv,
            manifest_num_ev=manifest_ev,
            raw_num_cv=raw_cv,
            raw_num_ev=raw_ev,
            raw_source=str(raw["source_file"]) if raw else "",
        )
    return out


def evidence_matrix_rows() -> list[dict[str, Any]]:
    return [
        {
            "source_id": "GoekeSchneider2015Raw",
            "source_type": "benchmark_raw_instance",
            "supports": "goeke_total_cap;goeke_ev_cap_only",
            "explicit_numeric_cap": True,
            "cap_value_rule": "numPetrolVeh/numElectroVeh per raw E-UK instance",
            "scenario_relevance": "original mixed-fleet benchmark vehicle availability",
            "caveat": "May be incompatible with ReSETP one-route-per-vehicle interpretation if route count exceeds numVeh.",
            "path_or_url": str(RAW_GOEEKE_ROOT),
        },
        {
            "source_id": "ReSETPGeneratedMetadata",
            "source_type": "generated_instance_metadata",
            "supports": "goeke_total_cap;goeke_ev_cap_only",
            "explicit_numeric_cap": True,
            "cap_value_rule": "metadata num_cv/num_ev copied from Goeke donor",
            "scenario_relevance": "current E2 generated bundles",
            "caveat": "Current solver/checker intentionally do not enforce these values.",
            "path_or_url": str(BENCHMARK_ROOT),
        },
        {
            "source_id": "Chen2023SharedCharging",
            "source_type": "paper_reference",
            "supports": "multidepot_shared_charging_context",
            "explicit_numeric_cap": False,
            "cap_value_rule": "",
            "scenario_relevance": "supports multidepot/shared charging as a scenario, not a numeric fleet cap by itself",
            "caveat": "Do not generate evidence_ratio_cap from this source without extracting explicit fleet-count data.",
            "path_or_url": "docs/paper_submission_final/RETIRED_paper_main.tex ref:7",
        },
        {
            "source_id": "Wang2024ResourceSharing",
            "source_type": "paper_reference",
            "supports": "resource_sharing_context",
            "explicit_numeric_cap": False,
            "cap_value_rule": "",
            "scenario_relevance": "supports shared resources in multidepot routing",
            "caveat": "Context source only for this runner.",
            "path_or_url": "docs/paper_submission_final/RETIRED_paper_main.tex ref:25",
        },
        {
            "source_id": "Qiu2024MixedFleet",
            "source_type": "local_pdf_reference",
            "supports": "mixed_fleet_literature_context",
            "explicit_numeric_cap": False,
            "cap_value_rule": "",
            "scenario_relevance": "post-2020 mixed CV/EV routing literature",
            "caveat": "Battery evidence was used in 09h/09k; no fleet cap ratio is promoted here without extraction.",
            "path_or_url": "/Users/zhouleixishu/Zotero/storage/5EKAGHKW/Qiu 等 _ 2024 _ Routing a mixed fleet...pdf",
        },
        {
            "source_id": "Li2020FleetConfiguration",
            "source_type": "local_pdf_reference",
            "supports": "fleet_configuration_mechanism",
            "explicit_numeric_cap": False,
            "cap_value_rule": "",
            "scenario_relevance": "supports treating fleet configuration as a real operational mechanism",
            "caveat": "No numeric cap is generated unless the source is explicitly extracted later.",
            "path_or_url": "/Users/zhouleixishu/Zotero/storage/3BZESE7Z/李英 等 _ 2020 _ 电动汽车传统汽车混合车队配置及路径优化模型.pdf",
        },
        {
            "source_id": "GOVUKCommercialEVFleets2024",
            "source_type": "official_web",
            "supports": "finite_ev_adoption_and_barriers_context",
            "explicit_numeric_cap": False,
            "cap_value_rule": "",
            "scenario_relevance": "real fleets face adoption, charging, and capital barriers",
            "caveat": "Qualitative/industry context only unless an explicit fleet ratio is extracted.",
            "path_or_url": "https://www.gov.uk/government/publications/commercial-electric-vans-and-fleets-adoption-smart-charging-and-barriers",
        },
    ]


def cap_scenario_rows(meta_by_instance: dict[str, FleetMeta], scenarios: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in focus_instances_from_meta(meta_by_instance):
        meta = meta_by_instance[key]
        for scenario in scenarios:
            cap = cap_for_scenario(meta, scenario)
            rows.append(
                {
                    "category": meta.category,
                    "instance": meta.instance,
                    "size": meta.size,
                    "replicate": meta.replicate,
                    "cap_scenario": scenario,
                    "max_cv": cap.max_cv,
                    "max_ev": cap.max_ev,
                    "source_class": cap.source_class,
                    "interpretation": cap.interpretation,
                    "raw_num_cv": meta.raw_num_cv,
                    "raw_num_ev": meta.raw_num_ev,
                    "manifest_num_cv": meta.manifest_num_cv,
                    "manifest_num_ev": meta.manifest_num_ev,
                    "depots": meta.depots,
                }
            )
    return rows


def existing_unbounded_winner_audit(repo_root: Path, meta_by_instance: dict[str, FleetMeta]) -> list[dict[str, Any]]:
    path = repo_root / STRUCTURAL_JOIN
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for row in b9k.read_csv(path):
        instance_key = f"{row['category']}/{row['instance']}"
        meta = meta_by_instance.get(instance_key)
        if not meta:
            continue
        ev_routes = int(float(row.get("winner_ev_route_count", 0) or 0))
        cv_routes = int(float(row.get("winner_cv_route_count", 0) or 0))
        rows.append(
            {
                "battery_kwh": float(row["battery_kwh"]),
                "category": row["category"],
                "instance": row["instance"],
                "size": int(float(row["size"])),
                "winner_composition": row["winner_composition"],
                "winner_route_count": int(float(row["winner_route_count"])),
                "winner_cv_route_count": cv_routes,
                "winner_ev_route_count": ev_routes,
                "winner_ev_route_share": float(row["winner_ev_route_share"]),
                "manifest_num_cv": meta.manifest_num_cv,
                "manifest_num_ev": meta.manifest_num_ev,
                "raw_num_cv": meta.raw_num_cv,
                "raw_num_ev": meta.raw_num_ev,
                "winner_cv_over_manifest": cv_routes > meta.manifest_num_cv,
                "winner_ev_over_manifest": ev_routes > meta.manifest_num_ev,
                "winner_total_over_manifest_sum": (cv_routes + ev_routes) > (meta.manifest_num_cv + meta.manifest_num_ev),
            }
        )
    return rows


def phase1_unbounded_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[float, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(float(row["battery_kwh"]), str(row["category"]))].append(row)
    out: list[dict[str, Any]] = []
    for (battery, category), items in sorted(groups.items()):
        out.append(
            {
                "battery_kwh": battery,
                "category": category,
                "rows": len(items),
                "ev_over_manifest_rows": sum(bool_value(row["winner_ev_over_manifest"]) for row in items),
                "cv_over_manifest_rows": sum(bool_value(row["winner_cv_over_manifest"]) for row in items),
                "total_over_manifest_rows": sum(bool_value(row["winner_total_over_manifest_sum"]) for row in items),
                "mean_ev_route_share": mean(row["winner_ev_route_share"] for row in items),
                "max_ev_route_count": max(int(row["winner_ev_route_count"]) for row in items) if items else 0,
                "max_manifest_ev": max(int(row["manifest_num_ev"]) for row in items) if items else 0,
            }
        )
    return out


def cap_proxy_audit(repo_root: Path, meta_by_instance: dict[str, FleetMeta], args: argparse.Namespace) -> dict[str, Any]:
    probe_key = "multidepot/e2-multidepot-100c-01"
    if probe_key not in meta_by_instance:
        return {"status": "HALT", "reason": "probe instance missing"}
    meta = meta_by_instance[probe_key]
    cap = cap_for_scenario(meta, "goeke_ev_cap_only")
    prices = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=float(args.battery_kwh))
    try:
        bundle = load_search_bundle(repo_root / BENCHMARK_ROOT / meta.category / meta.instance)
        policy = SearchPolicy(require_charging_signal=False, max_cv=cap.max_cv, max_ev=cap.max_ev)
        warm = cap_aware_warm(bundle, prices, policy, "free_mixed", "goeke_ev_cap_only")
        counts = route_counts(warm)
        status = "OK" if counts["ev_route_count"] <= cap.max_ev else "HALT"
        return {
            "status": status,
            "probe_instance": probe_key,
            "cap_scenario": "goeke_ev_cap_only",
            "warm_cv_route_count": counts["cv_route_count"],
            "warm_ev_route_count": counts["ev_route_count"],
            "max_cv": cap.max_cv,
            "max_ev": cap.max_ev,
            "interpretation": "SearchPolicy cap can be used as a diagnostic only if warm and final rows are audited.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "HALT", "probe_instance": probe_key, "error_type": type(exc).__name__, "error": str(exc)}


def build_metadata(repo_root: Path, args: argparse.Namespace, started: float) -> dict[str, Any]:
    return {
        "schema_version": "setp-09n-fleet-cap-operational-gate.v1",
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
        "tested_B_battery_kwh": float(args.battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "cap_scenarios": list(args.cap_scenarios),
        "practical_band": [PRACTICAL_LOW, PRACTICAL_HIGH],
        "stage_a_requested": bool(args.stage_a),
        "stage_b_requested": bool(args.stage_b),
        "stage_c_requested": bool(args.stage_c),
        "phase0_only": bool(args.phase0_only),
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
    cap_scenarios: list[str],
    seeds: list[int],
    eval_budget: int,
    runtime_caps: tuple[float, float, float],
) -> list[dict[str, Any]]:
    tasks = build_tasks(phase, instances, cap_scenarios, seeds, eval_budget, runtime_caps)
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
    b9k.write_csv(output_dir / f"{phase}_raw_runs.partial.csv", sorted_rows(rows))
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    workers = max(1, int(args.workers))
    if workers == 1:
        for task in pending:
            row = execute_task(repo_root, args, flags, task)
            rows.append(row)
            completed[task_key(row)] = row
            refresh_queue(output_dir, phase, tasks, completed, pending, rows)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(execute_task, repo_root, args, flags, task): task for task in pending}
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                completed[task_key(row)] = row
                refresh_queue(output_dir, phase, tasks, completed, pending, rows)
    return sorted_rows(rows)


def build_tasks(
    phase: str,
    instances: list[str],
    cap_scenarios: list[str],
    seeds: list[int],
    eval_budget: int,
    runtime_caps: tuple[float, float, float],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for scenario in cap_scenarios:
        for item in instances:
            category, instance = item.split("/", 1)
            cap = runtime_cap(instance, runtime_caps)
            for seed in seeds:
                for variant in VARIANT_ORDER:
                    tasks.append(
                        {
                            "phase": phase,
                            "cap_scenario": scenario,
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
        "--single-cap-scenario",
        str(task["cap_scenario"]),
        "--single-battery-kwh",
        str(args.battery_kwh),
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
        return subprocess_error_row(repo_root, task, "JSON_PARSE_ERROR", time.perf_counter() - started, completed.returncode, stdout, completed.stderr, repr(exc))
    if completed.returncode != 0 and payload.get("status") not in {"INIT_INFEASIBLE", "CAP_VIOLATION"}:
        return subprocess_error_row(repo_root, task, "SUBPROCESS_NONZERO", time.perf_counter() - started, completed.returncode, stdout, completed.stderr, "")
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
        str(args.single_cap_scenario),
        float(args.single_battery_kwh),
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
    cap_scenario: str,
    battery_kwh: float,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
    meta = single_fleet_meta(repo_root, category, instance)
    cap = cap_for_scenario(meta, cap_scenario)
    prices = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=float(battery_kwh))
    row = base_run_row(repo_root, phase, category, instance, variant, seed, cap_scenario, cap, battery_kwh, eval_budget, runtime_cap_seconds, flags)
    try:
        bundle = load_search_bundle(bundle_dir)
        policy = policy_for_variant(variant, cap)
        baseline_seed = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            prices,
            fleet_limits=FleetLimits(cv=UNBOUNDED_FLEET, ev=0, source="09n cap precheck cv seed"),
            introduce_ev=False,
            require_charging_signal=False,
        )
        baseline_counts = route_counts(baseline_seed)
        row.update(
            {
                "cap_precheck_cv_seed_routes": baseline_counts["route_count"],
                "cap_precheck_cv_seed_cv_routes": baseline_counts["cv_route_count"],
            }
        )
        precheck_error = cap_precheck_error(variant, cap, baseline_counts["route_count"])
        if precheck_error:
            raise ValueError(precheck_error)
        warm = cap_aware_warm(bundle, prices, policy, variant, cap_scenario)
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
        row.update(
            {
                "status": "CAP_VIOLATION" if cap_violation else ("OK" if not violations else "VIOLATION"),
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "solver_reported_feasible": bool(result.feasible),
                "violation_count": len(violations),
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


def cap_aware_warm(bundle: SearchBundle, prices: PriceParameters, policy: SearchPolicy, variant: str, cap_scenario: str) -> Solution:
    introduce_ev = variant != "cv_shell" and policy.max_ev > 0
    return build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=FleetLimits(cv=policy.max_cv, ev=policy.max_ev, source=f"09n {cap_scenario} {variant}"),
        introduce_ev=introduce_ev,
        require_charging_signal=False,
    )


def cap_precheck_error(variant: str, cap: CapSpec, cv_seed_routes: int) -> str:
    """Cheap proxy guard before expensive EV-heavy warm construction.

    This is not a mathematical infeasibility proof.  It is a diagnostic guard:
    if the deterministic feasible CV seed already needs more routes than a
    proposed one-route-per-vehicle cap can hold, the cap scenario is marked
    too restrictive for this shell instead of spending minutes in repair.
    """

    if cap.scenario == "unbounded_reference":
        return ""
    if variant == "cv_shell" and cap.max_cv < cv_seed_routes:
        return f"cap precheck infeasible: cv_shell cap {cap.max_cv} < deterministic CV seed route count {cv_seed_routes}"
    if variant == "ev_shell" and cap.max_ev < cv_seed_routes:
        return f"cap precheck infeasible: ev_shell cap {cap.max_ev} < deterministic CV seed route count {cv_seed_routes}"
    if variant == "free_mixed" and (cap.max_cv + cap.max_ev) < cv_seed_routes:
        return (
            "cap precheck infeasible: total cap "
            f"{cap.max_cv + cap.max_ev} < deterministic CV seed route count {cv_seed_routes}"
        )
    return ""


def policy_for_variant(variant: str, cap: CapSpec) -> SearchPolicy:
    if variant == "cv_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=cap.max_cv, max_ev=0)
    if variant == "ev_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=0, max_ev=cap.max_ev)
    if variant == "free_mixed":
        return SearchPolicy(require_charging_signal=False, max_cv=cap.max_cv, max_ev=cap.max_ev)
    raise ValueError(f"unknown variant: {variant}")


def cap_for_scenario(meta: FleetMeta, scenario: str) -> CapSpec:
    if scenario == "goeke_total_cap":
        return CapSpec(scenario, meta.manifest_num_cv, meta.manifest_num_ev, "source_backed", "Use Goeke/ReSETP metadata as total available CV/EV vehicles.")
    if scenario == "goeke_ev_cap_only":
        return CapSpec(scenario, UNBOUNDED_FLEET, meta.manifest_num_ev, "source_backed_diagnostic", "Only cap EV stock from Goeke metadata; keep CV flexible to isolate infinite-EV effects.")
    if scenario == "depot_scaled_cap":
        return CapSpec(scenario, meta.manifest_num_cv * meta.depots, meta.manifest_num_ev * meta.depots, "diagnostic_only", "Scale donor fleet by depot count; not promotable without multidepot source support.")
    if scenario == "unbounded_reference":
        return CapSpec(scenario, UNBOUNDED_FLEET, UNBOUNDED_FLEET, "reference_only", "Current unbounded search-shell reference.")
    raise ValueError(f"unknown cap scenario: {scenario}")


def winner_rows_from_raw(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["phase"]), str(row["cap_scenario"]), str(row["category"]), str(row["instance"]), int(row["seed"]))].append(row)
    winners: list[dict[str, Any]] = []
    for (phase, scenario, category, instance, seed), candidates in sorted(grouped.items()):
        feasible = [row for row in candidates if row.get("status") == "OK" and int(float(row.get("violation_count", 999))) == 0]
        if not feasible:
            winners.append(
                {
                    "phase": phase,
                    "cap_scenario": scenario,
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
            "cap_scenario": scenario,
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
            "max_cv": int(float(best.get("max_cv", UNBOUNDED_FLEET))),
            "max_ev": int(float(best.get("max_ev", UNBOUNDED_FLEET))),
            "source_class": best.get("cap_source_class", ""),
        }
        for row in feasible:
            prefix = str(row["variant"])
            winner[f"{prefix}_cost"] = float(row["total_cost"])
            winner[f"{prefix}_composition"] = row["composition"]
            winner[f"{prefix}_ev_route_share"] = float(row.get("ev_route_share", 0.0))
            winner[f"{prefix}_ev_customer_share"] = float(row.get("ev_customer_share", math.nan))
            winner[f"{prefix}_ev_demand_share"] = float(row.get("ev_demand_share", math.nan))
            winner[f"{prefix}_ev_distance_share"] = float(row.get("ev_distance_share", math.nan))
        winners.append(winner)
    return winners


def by_scale_rows(winners: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        groups[(str(row["cap_scenario"]), str(row["category"]), int(float(row.get("size", b9k.customer_count(str(row["instance"]))))))].append(row)
    rows: list[dict[str, Any]] = []
    for (scenario, category, size), items in sorted(groups.items()):
        ok = [row for row in items if row.get("winner_status") == "OK"]
        route = [float(row["winner_ev_route_share"]) for row in ok]
        customer = [float(row["winner_ev_customer_share"]) for row in ok]
        demand = [float(row["winner_ev_demand_share"]) for row in ok]
        distance = [float(row["winner_ev_distance_share"]) for row in ok]
        counts = composition_counts(ok)
        mean_route = mean(route)
        mean_customer = mean(customer)
        mean_demand = mean(demand)
        mean_distance = mean(distance)
        rows.append(
            {
                "phase": phase,
                "cap_scenario": scenario,
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
                "all_ev_count": counts.get("all_ev", 0),
                "ev_heavy_count": counts.get("ev_heavy_mixed", 0),
                "balanced_count": counts.get("balanced_mixed", 0),
                "cv_heavy_count": counts.get("cv_heavy_mixed", 0),
                "all_cv_count": counts.get("all_cv", 0),
                "fake_balance_flag": fake_balance(mean_route, mean_customer, mean_demand, mean_distance),
            }
        )
    return rows


def scenario_summary_rows(winners: list[dict[str, Any]], by_scale: list[dict[str, Any]], raw_rows: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        grouped[str(row["cap_scenario"])].append(row)
    scale_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in by_scale:
        scale_grouped[str(row["cap_scenario"])].append(row)
    raw_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        raw_grouped[str(row["cap_scenario"])].append(row)

    rows: list[dict[str, Any]] = []
    for scenario in sorted(grouped):
        items = grouped[scenario]
        ok = [row for row in items if row.get("winner_status") == "OK"]
        raw = raw_grouped.get(scenario, [])
        counts = composition_counts(ok)
        route = [float(row["winner_ev_route_share"]) for row in ok]
        customer = [float(row["winner_ev_customer_share"]) for row in ok]
        demand = [float(row["winner_ev_demand_share"]) for row in ok]
        distance = [float(row["winner_ev_distance_share"]) for row in ok]
        instance_pass = instance_majority_pass_count(ok)
        scale_rows = scale_grouped.get(scenario, [])
        scale_pass = sum(1 for row in scale_rows if bool_value(row.get("route_share_in_practical_band")))
        fake_count = sum(1 for row in scale_rows if bool_value(row.get("fake_balance_flag")))
        total_instances = len({(str(row["category"]), str(row["instance"])) for row in items})
        expected_winners = len(items)
        status = scenario_stage_status(len(ok), expected_winners, instance_pass, total_instances, scale_pass, len(scale_rows), fake_count)
        rows.append(
            {
                "phase": phase,
                "cap_scenario": scenario,
                "scenario_stage_status": status,
                "source_class": source_class_for_scenario(scenario),
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
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in winners:
        groups[(str(row["cap_scenario"]), str(row["category"]), str(row["instance"]))].append(row)
    rows: list[dict[str, Any]] = []
    for (scenario, category, instance), items in sorted(groups.items()):
        ok = [row for row in items if row.get("winner_status") == "OK"]
        in_band_count = sum(1 for row in ok if in_band(float(row["winner_ev_route_share"])))
        required = math.floor(len(ok) / 2) + 1 if ok else 1
        mean_route = mean(float(row["winner_ev_route_share"]) for row in ok)
        mean_customer = mean(float(row["winner_ev_customer_share"]) for row in ok)
        mean_demand = mean(float(row["winner_ev_demand_share"]) for row in ok)
        mean_distance = mean(float(row["winner_ev_distance_share"]) for row in ok)
        pass_instance = bool(ok) and in_band_count >= required and not fake_balance(mean_route, mean_customer, mean_demand, mean_distance)
        if pass_instance:
            continue
        rows.append(
            {
                "phase": phase,
                "cap_scenario": scenario,
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
                "reason": "missing_or_infeasible" if not ok else ("fake_balance" if fake_balance(mean_route, mean_customer, mean_demand, mean_distance) else "route_share_outside_practical_band"),
            }
        )
    return rows


def summarize_conclusion(
    args: argparse.Namespace,
    cap_proxy: dict[str, Any],
    phase1_summary: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    stage_a_summary: list[dict[str, Any]],
    stage_b_summary: list[dict[str, Any]],
    stage_c_summary: list[dict[str, Any]],
    stage_b_scenarios: list[str],
    stage_c_scenarios: list[str],
) -> dict[str, Any]:
    if cap_proxy.get("status") != "OK":
        return {"verdict": "CAP_PROXY_NOT_TRUSTWORTHY", "interpretation": "The cap-aware warm-start audit failed; do not trust SearchPolicy cap probes.", "cap_proxy": cap_proxy}
    failures = [row for row in raw_rows if row.get("status") in COLLECTION_FAILURE_STATUSES]
    if failures:
        return {"verdict": "HALT_COLLECTION_COST", "interpretation": "At least one required optimization task timed out or errored.", "failed_rows": len(failures)}
    cap_violations = [row for row in raw_rows if row.get("status") == "CAP_VIOLATION"]
    if cap_violations:
        return {"verdict": "CAP_PROXY_NOT_TRUSTWORTHY", "interpretation": "At least one final solution exceeded its diagnostic cap.", "cap_violation_rows": len(cap_violations)}
    if args.phase0_only:
        return {"verdict": "PHASE0_ONLY", "interpretation": "Only evidence, metadata, and existing unbounded audit were collected."}

    decision_summary = stage_c_summary or stage_b_summary or stage_a_summary
    decision_stage = "stage_c" if stage_c_summary else ("stage_b" if stage_b_summary else ("stage_a" if stage_a_summary else "none"))
    if not decision_summary:
        return {"verdict": "PHASE0_ONLY", "interpretation": "No optimization stage was requested.", "decision_stage": decision_stage}

    pass_rows = [
        row
        for row in decision_summary
        if str(row.get("scenario_stage_status")) == "pass" and str(row.get("cap_scenario")) in SOURCE_BACKED_SCENARIOS
    ]
    near_rows = [
        row
        for row in decision_summary
        if str(row.get("scenario_stage_status")) == "near_pass" and str(row.get("cap_scenario")) in SOURCE_BACKED_SCENARIOS
    ]
    if pass_rows and decision_stage == "stage_c":
        return {
            "verdict": "FLEET_CAP_PRIMARY_DRIVER",
            "interpretation": "A source-backed finite fleet-cap probe passed Stage C across 75-200 stability instances. Treat this as diagnostic support; formal model changes still need a separate plan.",
            "decision_stage": decision_stage,
            "passing_scenarios": [row["cap_scenario"] for row in pass_rows],
        }
    if pass_rows or near_rows:
        return {
            "verdict": "OPERATIONAL_CONSTRAINTS_NEEDED",
            "interpretation": "A source-backed cap is promising before final confirmation, but it has not passed Stage C. Do not formalize it yet.",
            "decision_stage": decision_stage,
            "stage_b_triggered_scenarios": stage_b_scenarios,
            "stage_c_triggered_scenarios": stage_c_scenarios,
            "pass_or_near_scenarios": [row["cap_scenario"] for row in [*pass_rows, *near_rows]],
        }

    source_rows = [row for row in decision_summary if str(row.get("cap_scenario")) in SOURCE_BACKED_SCENARIOS]
    if source_rows and all(int(row.get("raw_init_infeasible_rows", 0)) >= max(1, int(row.get("raw_rows", 0))) // 2 for row in source_rows):
        verdict = "FLEET_CAP_TOO_RESTRICTIVE"
        interpretation = "Source-backed caps produced too many infeasible rows under the current one-route-per-vehicle diagnostic interpretation."
    elif source_rows and any(
        int(row.get("ev_heavy_winner_count", 0)) + int(row.get("all_ev_winner_count", 0)) >= max(1, int(row.get("winner_count", 0))) / 2
        for row in source_rows
    ):
        verdict = "FINITE_CAP_STILL_EV_DOMINANT"
        interpretation = "Finite source-backed EV caps did not remove EV dominance in the collected decision stage."
    else:
        verdict = "OPERATIONAL_CONSTRAINTS_NEEDED"
        interpretation = "Fleet-cap probes did not produce a stable source-backed practical mixed band; test other operational mechanisms next."
    return {
        "verdict": verdict,
        "interpretation": interpretation,
        "decision_stage": decision_stage,
        "stage_b_triggered_scenarios": stage_b_scenarios,
        "stage_c_triggered_scenarios": stage_c_scenarios,
        "phase1_unbounded_summary_rows": len(phase1_summary),
        "scenario_status": {str(row["cap_scenario"]): str(row["scenario_stage_status"]) for row in decision_summary},
    }


def render_report(
    metadata: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    cap_rows: list[dict[str, Any]],
    phase1_summary: list[dict[str, Any]],
    cap_proxy: dict[str, Any],
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
        "# 09n Fleet-Cap Operational Gate",
        "",
        f"Commit: `{metadata['commit_hash'][:8]}`.",
        f"Diagnostic artifact commit: `{metadata.get('diagnostic_artifact_commit', 'PENDING_COMMIT')}`.",
        f"Python: `{metadata['python']}`; NumPy: `{metadata['numpy']}`.",
        f"Frozen defaults: `B_battery_kwh={metadata['default_B_battery_kwh']}`, `v_speed_ms={metadata['v_speed_ms']}`, `carbon_price={metadata['carbon_price']}`.",
        "This is a diagnostic search-shell gate only. It does not edit `prices.py`, `cost.py`, `check.py`, `evaluation.py`, generated bundles, or formal model semantics.",
        f"Command: `{metadata['command']}`.",
        "",
        "## Verdict",
        "",
        f"`{conclusion['verdict']}`.",
        "",
        str(conclusion.get("interpretation", "")),
        "",
        "Plain reading: this report tests whether the apparent 280kWh EV dominance is partly an unlimited-EV-availability artifact. A passing diagnostic cap would still need a separate formal-model plan before the paper can claim it.",
        "",
        "## Evidence Matrix",
        "",
        "| source | type | explicit numeric cap | supports | rule | caveat |",
        "|---|---|---|---|---|---|",
    ]
    for row in evidence_rows:
        lines.append(
            f"| {row['source_id']} | {row['source_type']} | {row['explicit_numeric_cap']} | "
            f"{row['supports']} | {row['cap_value_rule']} | {row['caveat']} |"
        )
    lines.extend(
        [
            "",
        "## Cap Scenarios",
        "",
        "The cap values are instance-specific. `goeke_total_cap` and `goeke_ev_cap_only` use raw/generated `numPetrolVeh/numElectroVeh`; `depot_scaled_cap` is diagnostic only.",
        "Before expensive EV-heavy warm construction, the runner applies a cheap proxy guard: if the deterministic feasible CV seed already needs more routes than the proposed one-route-per-vehicle cap can hold, that task is recorded as `INIT_INFEASIBLE`. This is a diagnostic collection guard, not a mathematical proof of model infeasibility.",
        "",
        "| scenario | rows | source class | min/max CV cap | min/max EV cap |",
            "|---|---:|---|---:|---:|",
        ]
    )
    cap_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cap_rows:
        cap_groups[str(row["cap_scenario"])].append(row)
    for scenario, rows in sorted(cap_groups.items()):
        lines.append(
            f"| {scenario} | {len(rows)} | {rows[0]['source_class']} | "
            f"{min(int(r['max_cv']) for r in rows)}-{max(int(r['max_cv']) for r in rows)} | "
            f"{min(int(r['max_ev']) for r in rows)}-{max(int(r['max_ev']) for r in rows)} |"
        )
    lines.extend(
        [
            "",
            "## Phase 1: Did We Exceed Recorded Fleet Counts?",
            "",
            "| battery | family | rows | EV routes > manifest EV | CV routes > manifest CV | total routes > manifest sum | mean EV share | max EV routes / max manifest EV |",
            "|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in phase1_summary:
        lines.append(
            f"| {float(row['battery_kwh']):.1f} | {row['category']} | {row['rows']} | "
            f"{row['ev_over_manifest_rows']} | {row['cv_over_manifest_rows']} | {row['total_over_manifest_rows']} | "
            f"{fmt(row['mean_ev_route_share'])} | {row['max_ev_route_count']}/{row['max_manifest_ev']} |"
        )
    lines.extend(
        [
            "",
            "## Cap Proxy Audit",
            "",
            f"`{cap_proxy.get('status')}`: {cap_proxy}",
            "",
        ]
    )
    append_stage(lines, "Stage A Screen", stage_a_summary, stage_a_by_scale, stage_a_failures)
    append_stage(lines, "Stage B Stability Gate", stage_b_summary, stage_b_by_scale, stage_b_failures)
    append_stage(lines, "Stage C Confirmation", stage_c_summary, stage_c_by_scale, stage_c_failures)
    lines.extend(
        [
            "## Output Files",
            "",
            f"- `{metadata['output_dir']}/metadata.json`",
            f"- `{metadata['output_dir']}/evidence_matrix.csv`",
            f"- `{metadata['output_dir']}/raw_goeke_fleet_counts.csv`",
            f"- `{metadata['output_dir']}/generated_fleet_metadata.csv`",
            f"- `{metadata['output_dir']}/cap_scenarios.csv`",
            f"- `{metadata['output_dir']}/existing_unbounded_winner_audit.csv`",
            f"- `{metadata['output_dir']}/phase1_unbounded_summary.csv`",
            f"- `{metadata['output_dir']}/cap_proxy_audit.json`",
            f"- `{metadata['output_dir']}/stage_a_task_queue.csv`",
            f"- `{metadata['output_dir']}/stage_a_raw_runs.csv`",
            f"- `{metadata['output_dir']}/stage_a_winners.csv`",
            f"- `{metadata['output_dir']}/stage_a_scenario_summary.csv`",
            f"- `{metadata['output_dir']}/stage_a_by_scale.csv`",
            f"- `{metadata['output_dir']}/stage_a_failure_instances.csv`",
            f"- `{metadata['output_dir']}/raw_runs.csv`",
            f"- `{metadata['output_dir']}/winners.csv`",
            f"- `{metadata['output_dir']}/conclusion.json`",
            "",
            "## Decision Boundary",
            "",
            "If this gate cannot produce a source-backed practical mixed band, do not tune battery values further. Move to charger capacity, public-station scarcity, route eligibility, or explicit EV capital-budget mechanisms, with the same evidence-first rule.",
            "",
        ]
    )
    return "\n".join(lines)


def append_stage(lines: list[str], title: str, summary: list[dict[str, Any]], by_scale: list[dict[str, Any]], failures: list[dict[str, Any]]) -> None:
    lines.extend([f"## {title}", ""])
    if not summary:
        lines.extend(["Not collected.", ""])
        return
    lines.extend(
        [
            "| scenario | status | winners | instance pass/fail | scale pass/fail | fake-balance buckets | mean route/customer/demand/distance EV share | composition counts | raw statuses |",
            "|---|---|---:|---|---|---:|---|---|---|",
        ]
    )
    for row in summary:
        shares = f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
        counts = (
            f"allEV={row['all_ev_winner_count']}, EVheavy={row['ev_heavy_winner_count']}, "
            f"balanced={row['balanced_winner_count']}, CVheavy={row['cv_heavy_winner_count']}, allCV={row['all_cv_winner_count']}"
        )
        raw = f"OK={row['raw_ok_rows']}, init={row['raw_init_infeasible_rows']}, cap={row['raw_cap_violation_rows']}, timeout/error={row['raw_timeout_error_rows']}"
        lines.append(
            f"| {row['cap_scenario']} | {row['scenario_stage_status']} | {row['winner_count']}/{row['expected_winner_rows']} | "
            f"{row['instance_majority_pass_count']}/{row['instance_majority_fail_count']} | "
            f"{row['scale_bucket_pass_count']}/{row['scale_bucket_fail_count']} | {row['fake_balance_bucket_count']} | "
            f"{shares} | {counts} | {raw} |"
        )
    lines.append("")
    bad_scale = [row for row in by_scale if not bool_value(row.get("route_share_in_practical_band")) or bool_value(row.get("fake_balance_flag"))]
    if bad_scale:
        lines.extend(["By-scale failures or fake-balance buckets:", "", "| scenario | family | size | route/customer/demand/distance EV share | reason |", "|---|---|---:|---|---|"])
        for row in bad_scale[:80]:
            shares = f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
            reason = "fake_balance" if bool_value(row.get("fake_balance_flag")) else "route_share_outside_band"
            lines.append(f"| {row['cap_scenario']} | {row['category']} | {row['size']} | {shares} | {reason} |")
        if len(bad_scale) > 80:
            lines.append(f"| ... | ... | ... | {len(bad_scale) - 80} more rows in CSV | ... |")
        lines.append("")
    if failures:
        lines.extend(["Failure instances:", "", "| scenario | family | instance | reason | route/customer/demand/distance EV share |", "|---|---|---|---|---|"])
        for row in failures[:80]:
            shares = f"{fmt(row['mean_ev_route_share'])}/{fmt(row['mean_ev_customer_share'])}/{fmt(row['mean_ev_demand_share'])}/{fmt(row['mean_ev_distance_share'])}"
            lines.append(f"| {row['cap_scenario']} | {row['category']} | {row['instance']} | {row['reason']} | {shares} |")
        if len(failures) > 80:
            lines.append(f"| ... | ... | ... | {len(failures) - 80} more rows in CSV | ... |")
        lines.append("")


def focus_instances(repo_root: Path, *, reps: tuple[int, ...]) -> list[str]:
    keys: list[str] = []
    root = repo_root / BENCHMARK_ROOT
    for category in FAMILIES:
        for size in FOCUS_SIZES:
            for rep in reps:
                instance = f"e2-{category}-{size}c-{rep:02d}"
                if (root / category / instance / "instance.json").exists():
                    keys.append(f"{category}/{instance}")
    return keys


def focus_instances_from_meta(meta_by_instance: dict[str, FleetMeta]) -> list[str]:
    return sorted(meta_by_instance, key=instance_sort_key)


def smoke_instances(repo_root: Path) -> list[str]:
    candidates = [
        "vanilla/e2-vanilla-100c-01",
        "threeshift/e2-threeshift-200c-01",
    ]
    available = set(focus_instances(repo_root, reps=(1,)))
    return [item for item in candidates if item in available]


def single_fleet_meta(repo_root: Path, category: str, instance: str) -> FleetMeta:
    raw_rows = raw_goeke_fleet_rows(repo_root)
    generated_rows = generated_fleet_rows(repo_root)
    key = f"{category}/{instance}"
    meta = fleet_meta_by_instance(repo_root, raw_rows, generated_rows).get(key)
    if meta is None:
        raise ValueError(f"missing fleet metadata for {key}")
    return meta


def runtime_cap(instance: str, caps: tuple[float, float, float]) -> float:
    small, medium, large = caps
    n = b9k.customer_count(instance)
    if n >= 150:
        return float(large)
    if n >= 100:
        return float(medium)
    return float(small)


def load_completed_rows(output_dir: Path, phase: str, *, retry_timeouts: bool) -> dict[tuple[str, str, str, str, int, str, int], dict[str, Any]]:
    completed: dict[tuple[str, str, str, str, int, str, int], dict[str, Any]] = {}
    for name in (f"{phase}_raw_runs.csv", f"{phase}_raw_runs.partial.csv"):
        path = output_dir / name
        if not path.exists() or path.stat().st_size == 0:
            continue
        for row in b9k.read_csv(path):
            status = str(row.get("status", ""))
            if status == "TIMEOUT" and retry_timeouts:
                continue
            if status in TERMINAL_STATUSES:
                completed[task_key(row)] = row
    return completed


def refresh_queue(
    output_dir: Path,
    phase: str,
    tasks: list[dict[str, Any]],
    completed: dict[tuple[str, str, str, str, int, str, int], dict[str, Any]],
    pending: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    b9k.write_csv(output_dir / f"{phase}_raw_runs.partial.csv", sorted_rows(rows))
    b9k.write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, [task for task in pending if task_key(task) not in completed]))


def task_queue_rows(
    tasks: list[dict[str, Any]],
    completed: dict[tuple[str, str, str, str, int, str, int], dict[str, Any]],
    pending: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pending_keys = {task_key(row) for row in pending}
    rows = []
    for task in tasks:
        key = task_key(task)
        existing = completed.get(key)
        rows.append(
            {
                **task,
                "queue_status": "pending" if key in pending_keys else "terminal",
                "run_status": existing.get("status", "") if existing else "",
                "total_cost": existing.get("total_cost", "") if existing else "",
                "composition": existing.get("composition", "") if existing else "",
            }
        )
    return rows


def task_key(row: dict[str, Any]) -> tuple[str, str, str, str, int, str, int]:
    return (
        str(row["phase"]),
        str(row["cap_scenario"]),
        str(row["category"]),
        str(row["instance"]),
        int(row["seed"]),
        str(row["variant"]),
        int(row["eval_budget"]),
    )


def sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("phase", "")),
            str(row.get("cap_scenario", "")),
            instance_sort_key(f"{row.get('category', '')}/{row.get('instance', '')}"),
            int(float(row.get("seed", 0))),
            variant_index(str(row.get("variant", ""))),
        ),
    )


def instance_sort_key(key: str) -> tuple[int, int, int, str]:
    category, instance = key.split("/", 1)
    family_rank = {"vanilla": 0, "multidepot": 1, "threeshift": 2}.get(category, 9)
    return family_rank, b9k.customer_count(instance), replicate_number(instance), instance


def variant_index(variant: str) -> int:
    try:
        return VARIANT_ORDER.index(variant)
    except ValueError:
        return len(VARIANT_ORDER)


def triggered_scenarios(summary: list[dict[str, Any]], requested: Iterable[str]) -> list[str]:
    if not summary:
        return []
    triggered = [
        str(row["cap_scenario"])
        for row in summary
        if str(row.get("cap_scenario")) in set(requested)
        and str(row.get("scenario_stage_status")) in {"pass", "near_pass"}
        and str(row.get("cap_scenario")) not in REFERENCE_CAP_SCENARIOS
    ]
    return sorted(set(triggered))


def scenario_stage_status(
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
    if total_instances and instance_pass == total_instances and total_scales and scale_pass == total_scales and fake_count == 0:
        return "pass"
    if (
        total_instances
        and instance_pass >= math.ceil(total_instances * NEAR_PASS_FRACTION)
        and total_scales
        and scale_pass >= math.ceil(total_scales * NEAR_PASS_FRACTION)
        and fake_count == 0
    ):
        return "near_pass"
    return "fail"


def instance_majority_pass_count(rows: list[dict[str, Any]]) -> int:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["category"]), str(row["instance"]))].append(row)
    count = 0
    for items in grouped.values():
        in_band_count = sum(1 for row in items if in_band(float(row["winner_ev_route_share"])))
        route = mean(float(row["winner_ev_route_share"]) for row in items)
        customer = mean(float(row["winner_ev_customer_share"]) for row in items)
        demand = mean(float(row["winner_ev_demand_share"]) for row in items)
        distance = mean(float(row["winner_ev_distance_share"]) for row in items)
        if items and in_band_count >= math.floor(len(items) / 2) + 1 and not fake_balance(route, customer, demand, distance):
            count += 1
    return count


def composition_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("winner_composition", ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def base_run_row(
    repo_root: Path,
    phase: str,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    cap_scenario: str,
    cap: CapSpec,
    battery_kwh: float,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    return {
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "phase": phase,
        "cap_scenario": cap_scenario,
        "category": category,
        "instance": instance,
        "size": b9k.customer_count(instance),
        "variant": variant,
        "seed": int(seed),
        "battery_kwh": float(battery_kwh),
        "B_battery_kwh": float(battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "max_cv": int(cap.max_cv),
        "max_ev": int(cap.max_ev),
        "cap_source_class": cap.source_class,
        "cap_interpretation": cap.interpretation,
        "active_flags": json.dumps(flags, sort_keys=True),
    }


def timeout_row(repo_root: Path, task: dict[str, Any], timeout: float, elapsed: float, exc: subprocess.TimeoutExpired) -> dict[str, Any]:
    row = {
        **task,
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "elapsed_seconds": float(elapsed),
        "task_timeout_seconds": float(timeout),
        "status": "TIMEOUT",
        "actual_evals": 0,
        "violation_count": -1,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "composition": "timeout",
        "total_cost": math.inf,
        "subprocess_stdout_tail": b9k.tail_text(exc.stdout),
        "subprocess_stderr_tail": b9k.tail_text(exc.stderr),
    }
    return row


def subprocess_error_row(repo_root: Path, task: dict[str, Any], status: str, elapsed: float, returncode: int, stdout: str, stderr: str, error: str) -> dict[str, Any]:
    return {
        **task,
        "commit_hash": b9k.git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "elapsed_seconds": float(elapsed),
        "status": status,
        "subprocess_returncode": int(returncode),
        "actual_evals": 0,
        "violation_count": -1,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "composition": "error",
        "total_cost": math.inf,
        "subprocess_stdout_tail": b9k.tail_text(stdout),
        "subprocess_stderr_tail": b9k.tail_text(stderr),
        "error": error,
    }


def route_counts(solution: Solution) -> dict[str, int]:
    cv = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
    ev = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    return {"route_count": len(solution.routes), "cv_route_count": cv, "ev_route_count": ev}


def classify_composition(cv_count: int, ev_count: int) -> str:
    total = int(cv_count) + int(ev_count)
    if total == 0:
        return "empty"
    if ev_count == 0:
        return "all_cv"
    if cv_count == 0:
        return "all_ev"
    share = ev_count / total
    if share > PRACTICAL_HIGH:
        return "ev_heavy_mixed"
    if share < PRACTICAL_LOW:
        return "cv_heavy_mixed"
    return "balanced_mixed"


def source_class_for_scenario(scenario: str) -> str:
    if scenario in SOURCE_BACKED_SCENARIOS:
        return "source_backed"
    if scenario in DIAGNOSTIC_ONLY_SCENARIOS:
        return "diagnostic_only"
    return "unknown"


def in_band(value: float) -> bool:
    return math.isfinite(value) and PRACTICAL_LOW <= value <= PRACTICAL_HIGH


def fake_balance(route: float, customer: float, demand: float, distance: float) -> bool:
    if not in_band(route):
        return False
    return any(math.isfinite(value) and not in_band(value) for value in (customer, demand, distance))


def mean(values: Iterable[Any]) -> float:
    items = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            items.append(number)
    return sum(items) / len(items) if items else math.nan


def safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if float(denominator) else 0.0


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:.3f}" if math.isfinite(number) else ""


def csv_number(value: float) -> float | str:
    return value if math.isfinite(value) else ""


def regex_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def replicate_number(instance: str) -> int:
    match = re.search(r"-(\d+)$", instance)
    return int(match.group(1)) if match else 0


def infeasible_message(message: str) -> bool:
    lower = message.lower()
    return any(token in lower for token in ("infeasible", "unable to build", "cap-aware warm", "halt_m0", "initial solution"))


if __name__ == "__main__":
    raise SystemExit(main())
