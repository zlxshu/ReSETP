"""09k evidence-bound battery spectrum transition gate.

This diagnostic asks whether the 80kWh -> all-CV and 280kWh -> EV-dominant
endpoints contain an evidence-supported balanced-mixed band. It keeps promoted
model defaults and solver semantics untouched: every battery value is an
in-memory ``dataclasses.replace`` override and every reported solution is
independently replayed through ``evaluate/check`` with the same override.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from contextlib import contextmanager
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np

import largescale_allcv_diagnostic as d9f

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.solution import Route, Solution
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.fleet import FleetLimits, UNBOUNDED_FLEET
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.winner_operators import e2_alns_throughput_flags


CARBON_PRICE = 0.05034
BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
CHECKPOINT_DIR = Path("baselines/e2_alns/checkpoints")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/battery_spectrum_transition_data")
DEFAULT_REPORT = Path("baselines/e2_alns/battery_spectrum_transition.md")

REPRESENTATIVE_INSTANCES = (
    "vanilla/e2-vanilla-25c-01",
    "vanilla/e2-vanilla-50c-01",
    "vanilla/e2-vanilla-75c-01",
    "vanilla/e2-vanilla-100c-01",
    "vanilla/e2-vanilla-150c-01",
    "vanilla/e2-vanilla-200c-01",
    "multidepot/e2-multidepot-25c-01",
    "multidepot/e2-multidepot-50c-01",
    "multidepot/e2-multidepot-75c-01",
    "multidepot/e2-multidepot-100c-01",
    "multidepot/e2-multidepot-150c-01",
    "multidepot/e2-multidepot-200c-01",
    "threeshift/e2-threeshift-50c-01",
    "threeshift/e2-threeshift-75c-01",
    "threeshift/e2-threeshift-100c-01",
    "threeshift/e2-threeshift-150c-01",
    "threeshift/e2-threeshift-200c-01",
)

SCREEN_INSTANCES = (
    "vanilla/e2-vanilla-25c-01",
    "vanilla/e2-vanilla-100c-01",
    "vanilla/e2-vanilla-200c-01",
    "multidepot/e2-multidepot-100c-01",
    "multidepot/e2-multidepot-200c-01",
    "threeshift/e2-threeshift-50c-01",
    "threeshift/e2-threeshift-100c-01",
    "threeshift/e2-threeshift-200c-01",
)

SMOKE_INSTANCES = (
    "vanilla/e2-vanilla-25c-01",
    "threeshift/e2-threeshift-100c-01",
)

VARIANT_ORDER = ("free_mixed", "cv_shell", "ev_shell")
TERMINAL_STATUSES = {
    "OK",
    "VIOLATION",
    "INIT_INFEASIBLE",
    "TIMEOUT",
    "ERROR",
    "JSON_PARSE_ERROR",
    "SUBPROCESS_NONZERO",
}
COLLECTION_FAILURE_STATUSES = {"TIMEOUT", "ERROR", "JSON_PARSE_ERROR", "SUBPROCESS_NONZERO"}
MAIN_SCENARIO_TIERS = {"strong_current_vehicle_class", "conditional_van", "literature_benchmark"}
SCREEN_TRIGGER_MIN = 0.20
SCREEN_TRIGGER_MAX = 0.85
BALANCED_MIN = 0.30
BALANCED_MAX = 0.70
SENSITIVITY_MIN = 0.20
SENSITIVITY_MAX = 0.80


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--screen-only", action="store_true")
    parser.add_argument("--full-gate", action="store_true", help="Run full representative gate for triggered batteries.")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retry-timeouts", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--screen-seeds", nargs="*", type=int, default=[1])
    parser.add_argument("--full-seeds", nargs="*", type=int, default=[1, 2, 3])
    parser.add_argument("--screen-eval-budget", type=int, default=1000)
    parser.add_argument("--full-eval-budget", type=int, default=3000)
    parser.add_argument("--full-battery-values", nargs="*", type=float, default=[])
    parser.add_argument("--screen-runtime-small", type=float, default=60.0)
    parser.add_argument("--screen-runtime-medium", type=float, default=120.0)
    parser.add_argument("--screen-runtime-large", type=float, default=180.0)
    parser.add_argument("--full-runtime-small", type=float, default=180.0)
    parser.add_argument("--full-runtime-medium", type=float, default=300.0)
    parser.add_argument("--full-runtime-large", type=float, default=900.0)
    parser.add_argument("--task-timeout-buffer", type=float, default=60.0)
    parser.add_argument("--battery-values", nargs="*", type=float, default=[])
    parser.add_argument("--include-future-heavy", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--single-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-phase", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-category", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-instance", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-variant", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-battery-kwh", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--single-eval-budget", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-runtime-cap", type=float, default=0.0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.single_run:
        return single_run_cli(repo_root, args)

    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = repo_root / args.report_path
    started = time.perf_counter()

    evidence_rows = evidence_matrix_rows()
    candidate_rows = candidate_rows_from_evidence(evidence_rows, args)
    batteries = [float(row["battery_kwh"]) for row in candidate_rows if bool(row["scan_by_default"])]
    metadata = build_metadata(repo_root, args, batteries)

    write_csv(output_dir / "evidence_matrix.csv", evidence_rows)
    write_csv(output_dir / "battery_candidate_set.csv", candidate_rows)
    phase0 = phase0_override_audit(repo_root, batteries)
    write_json(output_dir / "phase1_override_audit.json", phase0)

    fixed_rows: list[dict[str, Any]] = []
    screen_rows: list[dict[str, Any]] = []
    screen_winners: list[dict[str, Any]] = []
    screen_summary: list[dict[str, Any]] = []
    trigger_rows: list[dict[str, Any]] = []
    full_rows: list[dict[str, Any]] = []
    full_winners: list[dict[str, Any]] = []
    full_summary: list[dict[str, Any]] = []

    if not args.phase0_only and phase0["status"] == "OK":
        fixed_rows = checkpoint_fixed_replay(repo_root, batteries)
        write_csv(output_dir / "fixed_replay.csv", fixed_rows)
        screen_instances = list(SMOKE_INSTANCES if args.smoke else SCREEN_INSTANCES)
        screen_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="screen",
            instances=screen_instances,
            batteries=batteries,
            seeds=list(args.screen_seeds),
            eval_budget=int(args.screen_eval_budget),
            runtime_caps=(float(args.screen_runtime_small), float(args.screen_runtime_medium), float(args.screen_runtime_large)),
        )
        write_csv(output_dir / "screen_raw_runs.csv", screen_rows)
        screen_winners = winner_rows_from_raw(screen_rows)
        write_csv(output_dir / "screen_winners.csv", screen_winners)
        screen_summary = transition_summary_rows(screen_winners, candidate_rows, phase="screen")
        write_csv(output_dir / "screen_transition_summary.csv", screen_summary)
        trigger_rows = full_gate_triggers(screen_summary, candidate_rows)
        write_csv(output_dir / "full_gate_triggers.csv", trigger_rows)

    if (
        not args.phase0_only
        and not args.screen_only
        and args.full_gate
        and phase0["status"] == "OK"
        and trigger_rows
    ):
        full_batteries = full_battery_values(args, trigger_rows)
        full_rows = run_task_grid(
            repo_root,
            output_dir,
            args,
            phase="full",
            instances=list(REPRESENTATIVE_INSTANCES),
            batteries=full_batteries,
            seeds=list(args.full_seeds),
            eval_budget=int(args.full_eval_budget),
            runtime_caps=(float(args.full_runtime_small), float(args.full_runtime_medium), float(args.full_runtime_large)),
        )
        write_csv(output_dir / "full_gate_raw_runs.csv", full_rows)
        full_winners = winner_rows_from_raw(full_rows)
        write_csv(output_dir / "full_gate_winners.csv", full_winners)
        full_summary = transition_summary_rows(full_winners, candidate_rows, phase="full")
        write_csv(output_dir / "full_gate_transition_summary.csv", full_summary)
    else:
        ensure_csv(output_dir / "full_gate_raw_runs.csv")
        ensure_csv(output_dir / "full_gate_winners.csv")
        ensure_csv(output_dir / "full_gate_transition_summary.csv")

    conclusion = summarize_conclusion(metadata, phase0, fixed_rows, screen_rows, screen_summary, trigger_rows, full_rows, full_summary, args)
    metadata["elapsed_seconds"] = time.perf_counter() - started
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "conclusion.json", conclusion)
    report_path.write_text(
        render_report(metadata, evidence_rows, candidate_rows, phase0, fixed_rows, screen_summary, trigger_rows, full_summary, conclusion),
        encoding="utf-8",
    )
    summary = {
        "schema_version": "setp-09k-battery-spectrum-stdout.v1",
        "verdict": conclusion["verdict"],
        "report": args.report_path,
        "output_dir": args.output_dir,
        "candidate_count": len(candidate_rows),
        "screen_rows": len(screen_rows),
        "full_rows": len(full_rows),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 2 if str(conclusion["verdict"]).startswith("HALT_") else 0


def evidence_matrix_rows() -> list[dict[str, Any]]:
    rows = [
        evidence("Qiu2024", 2024, "local_pdf", 60.0, "literature_benchmark", True, "mixed ICEV/EV benchmark fleet", "5/10/15/100 customers; speed 60km/h", "/Users/zhouleixishu/Zotero/storage/5EKAGHKW/Qiu 等 _ 2024 _ Routing a mixed fleet...pdf", "Post-2020 literature anchor; not a truck-product default."),
        evidence("Goeke2015", 2015, "local_pdf", 80.0, "literature_benchmark", True, "E-VRPTWMF benchmark truck", "10-200 customers; speed 90km/h", "/Users/zhouleixishu/Zotero/storage/PGY3QPNT/Goeke和Schneider _ 2015 _ Routing...pdf", "Historical physical lineage; current default was promoted away from this value."),
        evidence("Chen2023", 2023, "local_pdf", 80.0, "literature_benchmark", True, "urban medium distribution trucks", "48/4 to 288/6; speed 30-60km/h", "/Users/zhouleixishu/Zotero/storage/392IDBJI/陈婉茹 等 _ 2023 _ 碳交易机制下多中心混合车队配送路径和速度优化研究.pdf", "Urban/multidepot literature anchor."),
        evidence("MercedesESprinter", 2026, "official_web", 81.0, "conditional_van", True, "large electric van", "usable battery option", "https://www.mbvans.com/en/esprinter", "Conditional: van class is lighter than the current truck-like calibration."),
        evidence("MercedesESprinter", 2026, "official_web", 113.0, "conditional_van", True, "large electric van", "usable battery option", "https://www.mbvans.com/en/esprinter", "Conditional upper van option."),
        evidence("FusoECanter", 2024, "secondary_web", 82.6, "strong_current_vehicle_class", True, "light/medium electric distribution truck", "M battery configuration", "https://insideevs.com/news/609794/mitsubishi-fuso-next-generation-ecanter/", "Exact kWh from secondary coverage; official product page confirms S/M/L battery configurations but does not expose text kWh in the local scrape. Verify official spec before promotion."),
        evidence("FusoECanter", 2024, "secondary_web", 123.9, "strong_current_vehicle_class", True, "light/medium electric distribution truck", "L battery configuration", "https://insideevs.com/news/609794/mitsubishi-fuso-next-generation-ecanter/", "Exact kWh from secondary coverage; official product page confirms S/M/L battery configurations but does not expose text kWh in the local scrape. Verify official spec before promotion."),
        evidence("FordETransit2025", 2025, "official_pdf", 89.0, "conditional_van", True, "large electric van", "usable battery", "https://www.fromtheroad.ford.com/content/dam/fordmediasite/us/en/library/2025/specs/2025-Transit-Technical-Specs.pdf", "Conditional van evidence."),
        evidence("IsuzuNRREV", 2024, "official_web", 60.0, "strong_current_vehicle_class", True, "medium-duty box truck", "battery configuration", "https://www.isuzucv.com/en/nrrev", "Exact product configuration; use as class-compatible anchor if source remains current."),
        evidence("IsuzuNRREV", 2024, "official_web", 100.0, "strong_current_vehicle_class", True, "medium-duty box truck", "battery configuration", "https://www.isuzucv.com/en/nrrev", "Exact product configuration; use as class-compatible anchor if source remains current."),
        evidence("IsuzuNRREV", 2024, "official_web", 140.0, "strong_current_vehicle_class", True, "medium-duty box truck", "battery configuration", "https://www.isuzucv.com/en/nrrev", "Exact product configuration; use as class-compatible anchor if source remains current."),
        evidence("IsuzuNRREV", 2024, "official_web", 180.0, "strong_current_vehicle_class", True, "medium-duty box truck", "battery configuration", "https://www.isuzucv.com/en/nrrev", "Exact product configuration; use as class-compatible anchor if source remains current."),
        evidence("DAFXBElectric", 2025, "official_web", 141.0, "strong_current_vehicle_class", True, "distribution truck", "battery option", "https://www.daf.com/en/news-and-media/news-articles/global/2023/q4/new-daf-xb-electric-range-for-clean-urban-distribution", "Distribution-truck battery option."),
        evidence("DAFXBElectric", 2025, "official_web", 210.0, "strong_current_vehicle_class", True, "distribution truck", "battery option", "https://www.daf.com/en/news-and-media/news-articles/global/2023/q4/new-daf-xb-electric-range-for-clean-urban-distribution", "Distribution-truck battery option."),
        evidence("DAFXBElectric", 2025, "official_web", 282.0, "strong_current_vehicle_class", True, "distribution truck", "battery option", "https://www.daf.com/en/news-and-media/news-articles/global/2023/q4/new-daf-xb-electric-range-for-clean-urban-distribution", "Distribution-truck upper option; near Volvo 280."),
        evidence("MackMDElectric", 2025, "official_web", 150.0, "strong_current_vehicle_class", True, "medium-duty truck", "battery option", "https://www.macktrucks.com/trucks/md-electric/", "Medium-duty truck option."),
        evidence("MackMDElectric", 2025, "official_web", 240.0, "strong_current_vehicle_class", True, "medium-duty truck", "battery option", "https://www.macktrucks.com/trucks/md-electric/", "Medium-duty truck option."),
        evidence("FreightlinerEM2", 2025, "official_web", 194.0, "strong_current_vehicle_class", True, "medium-duty truck", "battery option", "https://freightliner.com/trucks/em2/", "Medium-duty electric truck option."),
        evidence("FreightlinerEM2", 2025, "official_web", 291.0, "strong_current_vehicle_class", True, "medium-duty truck", "battery option", "https://freightliner.com/trucks/em2/", "Medium-duty electric truck option above 280; kept for transition shape."),
        evidence("InternationalEMV", 2025, "official_web", 210.0, "strong_current_vehicle_class", True, "medium-duty truck", "battery capacity", "https://www.internationaltrucks.com/trucks/emv-series", "Medium-duty truck anchor."),
        evidence("RenaultTrucksETechD", 2025, "official_web", 176.0, "strong_current_vehicle_class", True, "medium-duty distribution truck", "battery option", "https://www.renault-trucks.co.uk/static/documents/renault-trucks-e-tech-d-d-wide-uk.pdf", "Distribution-truck option from official brochure."),
        evidence("RenaultTrucksETechD", 2025, "official_web", 200.0, "strong_current_vehicle_class", True, "medium-duty distribution truck", "battery option", "https://www.renault-trucks.co.uk/static/documents/renault-trucks-e-tech-d-d-wide-uk.pdf", "Distribution-truck option from official brochure."),
        evidence("VolvoFLFE2023", 2023, "official_web", 280.0, "strong_current_vehicle_class", True, "medium distribution truck", "lower-bound FL/FE battery", "https://www.volvotrucks.com/en-en/news-stories/press-releases/2023/jun/volvo-presents-electric-trucks-with-longer-range.html", "09h strong modern distribution-truck candidate; now known EV-dominant in Stage1 gate."),
        evidence("DiagnosticBridge160", 2026, "diagnostic", 160.0, "diagnostic_threshold", True, "not a source-backed product value", "09f/09h near-flip bridge", "baselines/e2_alns/parameter_evidence_review.md", "Included only to locate the transition; not eligible as a main scenario without new evidence."),
        evidence("VolvoFHElectric", 2026, "official_web", 360.0, "future_heavy_class", False, "heavy electric truck", "battery range lower endpoint", "https://www.volvotrucks.com/en-en/trucks/electric/volvo-fh-electric.html", "Requires vehicle-class recalibration."),
        evidence("VolvoFHElectric", 2026, "official_web", 540.0, "future_heavy_class", False, "heavy electric truck", "battery range upper endpoint", "https://www.volvotrucks.com/en-en/trucks/electric/volvo-fh-electric.html", "Requires vehicle-class recalibration."),
        evidence("DaimlerEActros600", 2026, "official_web", 621.0, "future_heavy_class", False, "heavy long-haul truck", "installed capacity", "https://www.daimlertruck.com/en/newsroom/pressrelease/full-charge-for-the-future-the-first-eactros-600-on-the-road-in-europes-fleets-53166796", "Long-haul class; not a battery-only override."),
    ]
    return rows


def evidence(
    source_id: str,
    year: int,
    source_type: str,
    battery_kwh: float,
    tier: str,
    scan_by_default: bool,
    vehicle_class: str,
    scale_or_config: str,
    path_or_url: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "year": int(year),
        "source_type": source_type,
        "battery_kwh": float(battery_kwh),
        "evidence_tier": tier,
        "main_scenario_eligible": tier in MAIN_SCENARIO_TIERS,
        "scan_by_default": bool(scan_by_default),
        "vehicle_class": vehicle_class,
        "scale_or_config": scale_or_config,
        "path_or_url": path_or_url,
        "notes": notes,
    }


def candidate_rows_from_evidence(evidence_rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    include_future = bool(args.include_future_heavy)
    requested = {round(float(value), 6) for value in args.battery_values}
    by_value: dict[float, list[dict[str, Any]]] = {}
    for row in evidence_rows:
        value = round(float(row["battery_kwh"]), 6)
        if requested and value not in requested:
            continue
        if not include_future and row["evidence_tier"] == "future_heavy_class" and not requested:
            continue
        if not bool(row["scan_by_default"]) and row["evidence_tier"] != "diagnostic_threshold" and not requested:
            continue
        by_value.setdefault(value, []).append(row)
    rows = []
    for value, sources in sorted(by_value.items()):
        tiers = sorted({str(row["evidence_tier"]) for row in sources})
        source_ids = sorted({str(row["source_id"]) for row in sources})
        eligible = any(bool(row["main_scenario_eligible"]) for row in sources)
        diagnostic_only = all(str(row["evidence_tier"]) == "diagnostic_threshold" for row in sources)
        scan_by_default = any(bool(row["scan_by_default"]) for row in sources) or bool(requested)
        rows.append(
            {
                "battery_kwh": float(value),
                "source_ids": ";".join(source_ids),
                "evidence_tiers": ";".join(tiers),
                "main_scenario_eligible": eligible and not diagnostic_only,
                "diagnostic_only": diagnostic_only,
                "scan_by_default": scan_by_default,
                "source_count": len(sources),
            }
        )
    return rows


def build_metadata(repo_root: Path, args: argparse.Namespace, batteries: list[float]) -> dict[str, Any]:
    return {
        "schema_version": "setp-09k-battery-spectrum-transition.v1",
        "repo_root": str(repo_root),
        "commit_hash": git_output(repo_root, "rev-parse", "HEAD"),
        "git_status_short": git_output(repo_root, "status", "--short", "--untracked-files=all"),
        "python": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "numpy": np.__version__,
        "command": " ".join([sys.executable, *sys.argv]),
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "default_B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "battery_values": batteries,
        "screen_seeds": list(args.screen_seeds),
        "full_seeds": list(args.full_seeds),
        "screen_eval_budget": int(args.screen_eval_budget),
        "full_eval_budget": int(args.full_eval_budget),
        "full_battery_values": list(args.full_battery_values),
        "resume": bool(args.resume),
        "retry_timeouts": bool(args.retry_timeouts),
        "workers": int(args.workers),
        "phase0_only": bool(args.phase0_only),
        "screen_only": bool(args.screen_only),
        "full_gate_requested": bool(args.full_gate),
        "diagnostic_artifact_commit": "PENDING_COMMIT",
    }


def phase0_override_audit(repo_root: Path, batteries: list[float]) -> dict[str, Any]:
    bundle = load_search_bundle(repo_root / BENCHMARK_ROOT / "vanilla/e2-vanilla-25c-01")
    low = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=80.0)
    high = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=280.0)
    tiny = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=0.1)
    one_ev = _one_ev_warm(bundle, high)
    high_violations = check_solution(one_ev, bundle.instance, high)
    tiny_violations = check_solution(one_ev, bundle.instance, tiny)
    route = one_ev.routes[0]
    low_repair_status = "OK"
    high_repair_status = "OK"
    try:
        repair_route_charging(route, bundle.instance, bundle.carbon_profile, low)
    except Exception as exc:  # noqa: BLE001 - diagnostics preserve the status.
        low_repair_status = type(exc).__name__
    try:
        repair_route_charging(route, bundle.instance, bundle.carbon_profile, high)
    except Exception as exc:  # noqa: BLE001
        high_repair_status = type(exc).__name__
    solver_status = solver_override_probe(bundle, low, high)
    ok = (
        len(high_violations) != len(tiny_violations)
        and solver_status.get("status") == "OK"
        and bool(solver_status.get("objective_or_cost_changed"))
        and float(DEFAULT_PRICES.carbon_price) == CARBON_PRICE
    )
    return {
        "status": "OK" if ok else "HALT_OVERRIDE_NOT_TRUSTWORTHY",
        "audited_battery_values": batteries,
        "carbon_price_pinned": float(CARBON_PRICE),
        "default_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "check_high_battery_violation_count": len(high_violations),
        "check_tiny_battery_violation_count": len(tiny_violations),
        "check_battery_override_changes_feasibility": len(high_violations) != len(tiny_violations),
        "repair_low_status": low_repair_status,
        "repair_high_status": high_repair_status,
        "solver_probe": solver_status,
        "note": "Main task runs pass explicit override warm starts because run_alns_wouda default initial construction does not pass prices through to build_initial_solution.",
    }


def solver_override_probe(bundle: SearchBundle, low: PriceParameters, high: PriceParameters) -> dict[str, Any]:
    try:
        warm_low = mixed_warm(bundle, low)
        warm_high = mixed_warm(bundle, high)
        low_run = run_alns_wouda(
            bundle.bundle_dir,
            iterations=None,
            seed=1,
            eval_budget=20,
            max_runtime_seconds=5.0,
            policy=SearchPolicy(require_charging_signal=False),
            initial_solution=warm_low,
            prices=low,
        )
        high_run = run_alns_wouda(
            bundle.bundle_dir,
            iterations=None,
            seed=1,
            eval_budget=20,
            max_runtime_seconds=5.0,
            policy=SearchPolicy(require_charging_signal=False),
            initial_solution=warm_high,
            prices=high,
        )
        low_cost = float(evaluate(low_run.best_solution, bundle.instance, bundle.carbon_profile, low)["total_cost"])
        high_cost = float(evaluate(high_run.best_solution, bundle.instance, bundle.carbon_profile, high)["total_cost"])
        return {
            "status": "OK",
            "low_best_obj": float(low_run.best_obj),
            "high_best_obj": float(high_run.best_obj),
            "low_total_cost": low_cost,
            "high_total_cost": high_cost,
            "objective_or_cost_changed": abs(float(low_run.best_obj) - float(high_run.best_obj)) > 1e-9 or abs(low_cost - high_cost) > 1e-9,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "HALT_SOLVER_PROBE_ERROR", "error": repr(exc)}


def checkpoint_fixed_replay(repo_root: Path, batteries: list[float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((repo_root / CHECKPOINT_DIR).glob("*.json")):
        parsed = parse_checkpoint_name(path.name)
        if parsed is None:
            continue
        category, instance, algorithm, seed = parsed
        bundle = load_search_bundle(repo_root / BENCHMARK_ROOT / category / instance)
        payload = json.loads(path.read_text(encoding="utf-8"))
        solution = solution_from_dict(payload["solution"])
        role = "allcv" if algorithm == "LNS" else "mixed"
        for battery in batteries:
            prices = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=float(battery))
            row = {
                "phase": "fixed_replay",
                "battery_kwh": float(battery),
                "category": category,
                "instance": instance,
                "algorithm": algorithm,
                "role": role,
                "seed": int(seed),
                "checkpoint_path": str(path.relative_to(repo_root)),
            }
            try:
                replayed = solution if role == "allcv" else d9f._replay_solution_for_prices(solution, bundle, prices)
                metrics = evaluate(replayed, bundle.instance, bundle.carbon_profile, prices)
                violations = check_solution(replayed, bundle.instance, prices)
                cv_count = sum(1 for route in replayed.routes if route.vehicle_type.lower() == "cv")
                ev_count = sum(1 for route in replayed.routes if route.vehicle_type.lower() == "ev")
                row.update(metric_subset(metrics))
                row.update(
                    {
                        "status": "OK" if not violations else "HALT_REPLAY_INFEASIBLE",
                        "violation_count": len(violations),
                        "route_count": len(replayed.routes),
                        "cv_route_count": cv_count,
                        "ev_route_count": ev_count,
                        "composition": classify_composition(cv_count, ev_count),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                row.update({"status": "HALT_REPLAY_ERROR", "error": repr(exc), "total_cost": math.inf, "violation_count": math.nan})
            rows.append(row)
    return rows


def parse_checkpoint_name(name: str) -> tuple[str, str, str, int] | None:
    match = re.match(r"(e2-(vanilla|multidepot|threeshift)-\d+c-\d+)__(.+)__seed(\d+)\.json$", name)
    if not match:
        return None
    instance = match.group(1)
    category = match.group(2)
    algorithm = match.group(3)
    seed = int(match.group(4))
    return category, instance, algorithm, seed


def run_task_grid(
    repo_root: Path,
    output_dir: Path,
    args: argparse.Namespace,
    *,
    phase: str,
    instances: list[str],
    batteries: list[float],
    seeds: list[int],
    eval_budget: int,
    runtime_caps: tuple[float, float, float],
) -> list[dict[str, Any]]:
    tasks = build_tasks(phase, instances, batteries, seeds, eval_budget, runtime_caps)
    completed = load_completed_rows(output_dir, phase, retry_timeouts=bool(args.retry_timeouts)) if args.resume else {}
    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for task in tasks:
        existing = completed.get(task_key(task))
        if existing is None:
            pending.append(task)
        else:
            rows.append(existing)
    write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, pending))
    write_csv(output_dir / f"{phase}_raw_runs.partial.csv", sorted_rows(rows))
    workers = max(1, int(args.workers))
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    if workers <= 1:
        for task in pending:
            row = execute_task(repo_root, args, flags, task)
            rows.append(row)
            completed[task_key(row)] = row
            write_csv(output_dir / f"{phase}_raw_runs.partial.csv", sorted_rows(rows))
            write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, [item for item in pending if task_key(item) not in completed]))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(execute_task, repo_root, args, flags, task): task for task in pending}
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                completed[task_key(row)] = row
                write_csv(output_dir / f"{phase}_raw_runs.partial.csv", sorted_rows(rows))
                write_csv(output_dir / f"{phase}_task_queue.csv", task_queue_rows(tasks, completed, [item for item in pending if task_key(item) not in completed]))
    return sorted_rows(rows)


def build_tasks(
    phase: str,
    instances: list[str],
    batteries: list[float],
    seeds: list[int],
    eval_budget: int,
    runtime_caps: tuple[float, float, float],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for battery in batteries:
        for item in instances:
            category, instance = item.split("/", 1)
            cap = runtime_cap(instance, runtime_caps)
            for seed in seeds:
                for variant in VARIANT_ORDER:
                    tasks.append(
                        {
                            "phase": phase,
                            "battery_kwh": float(battery),
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
    if completed.returncode != 0 and payload.get("status") not in {"INIT_INFEASIBLE"}:
        return subprocess_error_row(repo_root, task, "SUBPROCESS_NONZERO", time.perf_counter() - started, completed.returncode, stdout, completed.stderr, "")
    payload.setdefault("subprocess_returncode", int(completed.returncode))
    payload.setdefault("subprocess_stdout_tail", tail_text(stdout))
    payload.setdefault("subprocess_stderr_tail", tail_text(completed.stderr))
    return payload


def single_run_cli(repo_root: Path, args: argparse.Namespace) -> int:
    category = str(args.single_category)
    instance = str(args.single_instance)
    bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    row = run_one(
        repo_root,
        bundle_dir,
        str(args.single_phase),
        category,
        instance,
        str(args.single_variant),
        int(args.single_seed),
        float(args.single_battery_kwh),
        int(args.single_eval_budget),
        float(args.single_runtime_cap),
        flags,
    )
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 1 if row.get("status") in COLLECTION_FAILURE_STATUSES else 0


def run_one(
    repo_root: Path,
    bundle_dir: Path,
    phase: str,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    battery_kwh: float,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    prices = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE, B_battery_kwh=float(battery_kwh))
    row: dict[str, Any] = base_run_row(repo_root, phase, category, instance, variant, seed, battery_kwh, eval_budget, runtime_cap_seconds, flags)
    try:
        bundle = load_search_bundle(bundle_dir)
        warm = warm_for_variant(bundle, prices, variant)
        policy = policy_for_variant(variant)
        with temporary_env(flags):
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
        cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
        ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
        row.update(metric_subset(metrics))
        row.update(
            {
                "status": "OK" if not violations else "VIOLATION",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "solver_reported_feasible": bool(result.feasible),
                "violation_count": len(violations),
                "route_count": len(solution.routes),
                "cv_route_count": cv_count,
                "ev_route_count": ev_count,
                "composition": classify_composition(cv_count, ev_count),
                "ev_route_share": ev_count / len(solution.routes) if solution.routes else 0.0,
                "cv_route_share": cv_count / len(solution.routes) if solution.routes else 0.0,
            }
        )
    except ValueError as exc:
        message = str(exc)
        status = "INIT_INFEASIBLE" if "warm start" in message.lower() or "unable to build" in message.lower() else "ERROR"
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
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return row


def warm_for_variant(bundle: SearchBundle, prices: PriceParameters, variant: str) -> Solution:
    if variant == "cv_shell":
        return cv_warm(bundle, prices)
    if variant == "ev_shell":
        return all_ev_warm(bundle, prices)
    if variant == "free_mixed":
        return mixed_warm(bundle, prices)
    raise ValueError(f"unknown variant: {variant}")


def policy_for_variant(variant: str) -> SearchPolicy:
    if variant == "cv_shell":
        return SearchPolicy(require_charging_signal=False, max_ev=0)
    if variant == "ev_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=0)
    if variant == "free_mixed":
        return SearchPolicy(require_charging_signal=False)
    raise ValueError(f"unknown variant: {variant}")


def cv_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    return build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=FleetLimits(cv=UNBOUNDED_FLEET, ev=0, source="09k cv_shell"),
        introduce_ev=False,
        require_charging_signal=False,
    )


def mixed_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    cv = cv_warm(bundle, prices)
    try:
        one_ev = one_ev_warm(bundle, prices)
        if not check_solution(one_ev, bundle.instance, prices):
            cv_cost = float(evaluate(cv, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
            ev_cost = float(evaluate(one_ev, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
            return one_ev if ev_cost < cv_cost else cv
    except Exception:
        return cv
    return cv


def one_ev_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    cv = cv_warm(bundle, prices)
    candidates: list[tuple[float, Solution]] = []
    for idx, route in enumerate(cv.routes, start=1):
        ev_route = Route(f"EV_WARM_{idx}", "ev", route.home_depot_id, list(route.node_sequence))
        try:
            repaired, route_actions = repair_route_charging(ev_route, bundle.instance, bundle.carbon_profile, prices)
        except ValueError:
            continue
        routes = [repaired if pos == idx - 1 else old_route for pos, old_route in enumerate(cv.routes)]
        candidate = Solution(routes=routes, charging_actions=list(route_actions), cross_site_services=cv.cross_site_services)
        if check_solution(candidate, bundle.instance, prices):
            continue
        cost = float(evaluate(candidate, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
        candidates.append((cost, candidate))
    if not candidates:
        raise ValueError("Unable to build one-EV warm start under supplied prices")
    return min(candidates, key=lambda item: item[0])[1]


def _one_ev_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    return one_ev_warm(bundle, prices)


def all_ev_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    cv = cv_warm(bundle, prices)
    routes: list[Route] = []
    actions = []
    for idx, route in enumerate(cv.routes, start=1):
        ev_route = Route(f"EV{idx}", "ev", route.home_depot_id, list(route.node_sequence))
        try:
            repaired, route_actions = repair_route_charging(ev_route, bundle.instance, bundle.carbon_profile, prices)
        except ValueError as exc:
            raise ValueError(f"Unable to build all-EV warm start: {exc}") from exc
        routes.append(repaired)
        actions.extend(route_actions)
    solution = Solution(routes=routes, charging_actions=actions, cross_site_services=cv.cross_site_services)
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        details = "; ".join(f"{v.type}:{v.vehicle_id}:{v.location}:{v.detail}" for v in violations[:8])
        raise ValueError(f"Unable to build all-EV warm start: {details}")
    return solution


def winner_rows_from_raw(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, float, str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["phase"]), float(row["battery_kwh"]), str(row["category"]), str(row["instance"]), int(row["seed"])), []).append(row)
    winners = []
    for key, candidates in sorted(grouped.items()):
        phase, battery, category, instance, seed = key
        feasible = [row for row in candidates if row.get("status") == "OK" and int(row.get("violation_count", 999)) == 0]
        if not feasible:
            winners.append({"phase": phase, "battery_kwh": battery, "category": category, "instance": instance, "seed": seed, "winner_status": "NO_FEASIBLE_ROW"})
            continue
        best = min(feasible, key=lambda row: float(row["total_cost"]))
        winner = {
            "phase": phase,
            "battery_kwh": battery,
            "category": category,
            "instance": instance,
            "seed": seed,
            "winner_status": "OK",
            "winner_variant": best["variant"],
            "winner_total_cost": float(best["total_cost"]),
            "winner_composition": best["composition"],
            "winner_route_count": int(best["route_count"]),
            "winner_cv_route_count": int(best["cv_route_count"]),
            "winner_ev_route_count": int(best["ev_route_count"]),
            "winner_ev_route_share": float(best["ev_route_share"]),
        }
        for row in feasible:
            prefix = str(row["variant"])
            winner[f"{prefix}_cost"] = float(row["total_cost"])
            winner[f"{prefix}_composition"] = row["composition"]
            winner[f"{prefix}_cv_routes"] = int(row["cv_route_count"])
            winner[f"{prefix}_ev_routes"] = int(row["ev_route_count"])
        winners.append(winner)
    return winners


def transition_summary_rows(winners: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], *, phase: str) -> list[dict[str, Any]]:
    candidate_by_value = {float(row["battery_kwh"]): row for row in candidate_rows}
    grouped: dict[float, list[dict[str, Any]]] = {}
    for row in winners:
        grouped.setdefault(float(row["battery_kwh"]), []).append(row)
    out = []
    for battery, rows in sorted(grouped.items()):
        ok = [row for row in rows if row.get("winner_status") == "OK"]
        counts: dict[str, int] = {}
        for row in ok:
            counts[str(row["winner_composition"])] = counts.get(str(row["winner_composition"]), 0) + 1
        candidate = candidate_by_value.get(battery, {})
        mean_ev_share = mean(float(row["winner_ev_route_share"]) for row in ok) if ok else math.nan
        out.append(
            {
                "phase": phase,
                "battery_kwh": battery,
                "winner_count": len(ok),
                "total_winner_rows": len(rows),
                "all_ev_winner_count": counts.get("all_ev", 0),
                "ev_heavy_winner_count": counts.get("ev_heavy_mixed", 0),
                "balanced_winner_count": counts.get("balanced_mixed", 0),
                "cv_heavy_winner_count": counts.get("cv_heavy_mixed", 0),
                "all_cv_winner_count": counts.get("all_cv", 0),
                "mean_winner_ev_share": mean_ev_share,
                "mean_winner_cv_routes": mean(float(row["winner_cv_route_count"]) for row in ok) if ok else math.nan,
                "mean_winner_ev_routes": mean(float(row["winner_ev_route_count"]) for row in ok) if ok else math.nan,
                "balanced_band_30_70": BALANCED_MIN <= mean_ev_share <= BALANCED_MAX if ok else False,
                "sensitivity_band_20_80": SENSITIVITY_MIN <= mean_ev_share <= SENSITIVITY_MAX if ok else False,
                "main_scenario_eligible": bool(candidate.get("main_scenario_eligible", False)),
                "diagnostic_only": bool(candidate.get("diagnostic_only", False)),
                "source_ids": candidate.get("source_ids", ""),
                "evidence_tiers": candidate.get("evidence_tiers", ""),
            }
        )
    return out


def full_gate_triggers(screen_summary: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_by_value = {float(row["battery_kwh"]): row for row in candidate_rows}
    summaries = sorted(screen_summary, key=lambda row: float(row["battery_kwh"]))
    trigger_values: set[float] = set()
    for row in summaries:
        value = float(row["battery_kwh"])
        mean_ev_share = float(row.get("mean_winner_ev_share", math.nan))
        candidate = candidate_by_value.get(value, {})
        if not math.isfinite(mean_ev_share):
            continue
        if SCREEN_TRIGGER_MIN <= mean_ev_share <= SCREEN_TRIGGER_MAX:
            trigger_values.add(value)
        if int(row.get("balanced_winner_count", 0)) > 0:
            trigger_values.add(value)
        if bool(candidate.get("diagnostic_only", False)) and not (BALANCED_MIN <= mean_ev_share <= BALANCED_MAX):
            trigger_values.discard(value)
    for prev, current in zip(summaries, summaries[1:]):
        prev_share = float(prev.get("mean_winner_ev_share", math.nan))
        cur_share = float(current.get("mean_winner_ev_share", math.nan))
        if not (math.isfinite(prev_share) and math.isfinite(cur_share)):
            continue
        if (prev_share < BALANCED_MIN and cur_share > BALANCED_MAX) or (prev_share > BALANCED_MAX and cur_share < BALANCED_MIN):
            trigger_values.add(float(prev["battery_kwh"]))
            trigger_values.add(float(current["battery_kwh"]))
    rows = []
    for row in summaries:
        value = float(row["battery_kwh"])
        candidate = candidate_by_value.get(value, {})
        rows.append(
            {
                "battery_kwh": value,
                "run_full_gate": value in trigger_values,
                "screen_mean_ev_share": row.get("mean_winner_ev_share", ""),
                "screen_balanced_winner_count": row.get("balanced_winner_count", 0),
                "main_scenario_eligible": bool(candidate.get("main_scenario_eligible", False)),
                "diagnostic_only": bool(candidate.get("diagnostic_only", False)),
                "source_ids": candidate.get("source_ids", ""),
                "evidence_tiers": candidate.get("evidence_tiers", ""),
            }
        )
    return rows


def full_battery_values(args: argparse.Namespace, trigger_rows: list[dict[str, Any]]) -> list[float]:
    if args.full_battery_values:
        requested = {round(float(value), 6) for value in args.full_battery_values}
        return [float(row["battery_kwh"]) for row in trigger_rows if round(float(row["battery_kwh"]), 6) in requested]
    return [float(row["battery_kwh"]) for row in trigger_rows if bool(row["run_full_gate"])]


def summarize_conclusion(
    metadata: dict[str, Any],
    phase0: dict[str, Any],
    fixed_rows: list[dict[str, Any]],
    screen_rows: list[dict[str, Any]],
    screen_summary: list[dict[str, Any]],
    trigger_rows: list[dict[str, Any]],
    full_rows: list[dict[str, Any]],
    full_summary: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if phase0.get("status") != "OK":
        return {"verdict": "HALT_OVERRIDE_NOT_TRUSTWORTHY", "interpretation": "Battery override propagation was not trustworthy.", "phase0_status": phase0.get("status")}
    failed_screen = [row for row in screen_rows if row.get("status") in COLLECTION_FAILURE_STATUSES]
    failed_full = [row for row in full_rows if row.get("status") in COLLECTION_FAILURE_STATUSES]
    if failed_screen or failed_full:
        return {
            "verdict": "HALT_COLLECTION_COST",
            "interpretation": "At least one required optimization task timed out or errored; do not infer a battery band.",
            "failed_screen_rows": len(failed_screen),
            "failed_full_rows": len(failed_full),
        }
    if bool(args.phase0_only):
        return {"verdict": "PHASE0_ONLY", "interpretation": "Only evidence and override audit were run."}
    if bool(args.screen_only) or not bool(args.full_gate):
        return {
            "verdict": "SCREEN_ONLY",
            "interpretation": "Screen data were collected; full representative gate was not requested, so no final scientific verdict is made.",
            "trigger_count": sum(1 for row in trigger_rows if bool(row.get("run_full_gate"))),
        }
    if trigger_rows and not full_rows and any(bool(row.get("run_full_gate")) for row in trigger_rows):
        return {"verdict": "HALT_COLLECTION_COST", "interpretation": "Full gate was requested but triggered batteries were not collected."}
    eligible_balanced = [
        row
        for row in full_summary
        if bool(row.get("main_scenario_eligible"))
        and not bool(row.get("diagnostic_only"))
        and bool(row.get("balanced_band_30_70"))
        and (int(row.get("all_ev_winner_count", 0)) + int(row.get("ev_heavy_winner_count", 0))) < max(1, int(row.get("winner_count", 0))) / 2
    ]
    diagnostic_balanced = [row for row in full_summary if bool(row.get("diagnostic_only")) and bool(row.get("balanced_band_30_70"))]
    modern_rows = [row for row in full_summary if bool(row.get("main_scenario_eligible")) and not bool(row.get("diagnostic_only"))]
    vehicle_rows = [row for row in modern_rows if has_vehicle_evidence(row)]
    vehicle_balanced = [row for row in eligible_balanced if has_vehicle_evidence(row)]
    literature_balanced = [row for row in eligible_balanced if not has_vehicle_evidence(row)]
    ev_dominant = [
        row
        for row in modern_rows
        if int(row.get("winner_count", 0)) > 0
        and (int(row.get("all_ev_winner_count", 0)) + int(row.get("ev_heavy_winner_count", 0))) >= max(1, int(row.get("winner_count", 0))) / 2
    ]
    vehicle_ev_dominant = [row for row in ev_dominant if has_vehicle_evidence(row)]
    near_boundary_ev_heavy = [
        row
        for row in vehicle_rows
        if bool(row.get("balanced_band_30_70"))
        and (int(row.get("all_ev_winner_count", 0)) + int(row.get("ev_heavy_winner_count", 0))) >= max(1, int(row.get("winner_count", 0))) / 2
    ]
    if eligible_balanced:
        verdict = "BALANCED_EVIDENCE_BAND_FOUND"
        if vehicle_balanced:
            interpretation = "At least one current vehicle-class battery candidate produced a balanced-mixed full gate."
        else:
            interpretation = "The only strict balanced full-gate candidate is a literature benchmark anchor; full-gated current vehicle-class anchors were EV-dominant or near-boundary, so do not promote a modern default battery from this verdict alone."
    elif diagnostic_balanced:
        verdict = "ONLY_DIAGNOSTIC_BALANCED_NO_EVIDENCE"
        interpretation = "Only diagnostic/non-source battery values produced a balanced band; do not promote them as the main scenario."
    elif modern_rows and len(ev_dominant) == len(modern_rows):
        verdict = "MODERN_BATTERY_EV_DOMINANT"
        interpretation = "Evidence-eligible modern batteries collected in the full gate were EV-dominant."
    else:
        verdict = "NO_REALISTIC_BALANCED_BATTERY"
        interpretation = "The collected evidence-backed spectrum did not reveal a stable balanced-mixed battery value."
    return {
        "verdict": verdict,
        "interpretation": interpretation,
        "fixed_replay_rows": len(fixed_rows),
        "screen_rows": len(screen_rows),
        "full_rows": len(full_rows),
        "full_summary_rows": len(full_summary),
        "eligible_balanced_candidates": [float(row["battery_kwh"]) for row in eligible_balanced],
        "vehicle_balanced_candidates": [float(row["battery_kwh"]) for row in vehicle_balanced],
        "literature_balanced_candidates": [float(row["battery_kwh"]) for row in literature_balanced],
        "diagnostic_balanced_candidates": [float(row["battery_kwh"]) for row in diagnostic_balanced],
        "modern_ev_dominant_candidates": [float(row["battery_kwh"]) for row in ev_dominant],
        "vehicle_ev_dominant_candidates": [float(row["battery_kwh"]) for row in vehicle_ev_dominant],
        "near_boundary_ev_heavy_candidates": [float(row["battery_kwh"]) for row in near_boundary_ev_heavy],
    }


def has_vehicle_evidence(row: dict[str, Any]) -> bool:
    tiers = {item.strip() for item in str(row.get("evidence_tiers", "")).split(";") if item.strip()}
    return bool(tiers & {"strong_current_vehicle_class", "conditional_van"})


def render_report(
    metadata: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    phase0: dict[str, Any],
    fixed_rows: list[dict[str, Any]],
    screen_summary: list[dict[str, Any]],
    trigger_rows: list[dict[str, Any]],
    full_summary: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09k Evidence-Bound Battery Spectrum Gate",
        "",
        f"Commit: `{metadata['commit_hash'][:8]}`.",
        f"Python: `{metadata['python']}`; NumPy: `{metadata['numpy']}`.",
        f"Frozen parameters: `v_speed_ms={metadata['v_speed_ms']}`, `carbon_price={metadata['carbon_price']}`. Battery is varied only through in-memory overrides.",
        f"Command: `{metadata['command']}`.",
        "",
        "## Verdict",
        "",
        f"`{conclusion['verdict']}`.",
        "",
        str(conclusion["interpretation"]),
        "",
        f"Strict balanced candidates: `{', '.join(str(v) for v in conclusion.get('eligible_balanced_candidates', [])) or 'none'}`.",
        f"Current vehicle-class balanced candidates: `{', '.join(str(v) for v in conclusion.get('vehicle_balanced_candidates', [])) or 'none'}`.",
        f"Literature-only balanced candidates: `{', '.join(str(v) for v in conclusion.get('literature_balanced_candidates', [])) or 'none'}`.",
        f"Near-boundary but EV-heavy candidates: `{', '.join(str(v) for v in conclusion.get('near_boundary_ev_heavy_candidates', [])) or 'none'}`.",
        f"Vehicle-class EV-dominant candidates: `{', '.join(str(v) for v in conclusion.get('vehicle_ev_dominant_candidates', [])) or 'none'}`.",
        "",
        "## Override Audit",
        "",
        f"Phase 0 status: `{phase0.get('status')}`.",
        "",
        "The runner uses explicit override warm starts because the base `run_alns_wouda` default construction path does not pass the override `prices` into `build_initial_solution`. Final rows are still independently `evaluate/check` replayed with the same override.",
        "",
        "## Evidence Candidate Set",
        "",
        "| battery kWh | eligible | diagnostic | tiers | sources |",
        "|---:|---|---|---|---|",
    ]
    for row in candidate_rows:
        lines.append(f"| {float(row['battery_kwh']):.1f} | {row['main_scenario_eligible']} | {row['diagnostic_only']} | {row['evidence_tiers']} | {row['source_ids']} |")
    lines.extend(["", "Source URLs and PDF paths are preserved in `evidence_matrix.csv`; values are exact source/configuration values, not equal-spaced guesses. Capacity basis follows each source (usable/installed/gross where stated) and is not silently normalized.", ""])
    if fixed_rows:
        ok_fixed = sum(1 for row in fixed_rows if row.get("status") == "OK")
        lines.extend(
            [
                "## Fixed Replay Scope",
                "",
                f"Checkpoint fixed replay rows: {ok_fixed}/{len(fixed_rows)} OK.",
                "",
                "This replay is limited to existing 09d/09f checkpoint JSON coverage, not the full 17-instance representative gate. It is therefore a screen, not the final fleet-composition verdict.",
                "",
            ]
        )
    if screen_summary:
        lines.extend(["## Screen Transition", "", "| battery | winners | all-EV | EV-heavy | balanced | CV-heavy | all-CV | mean EV share | eligible | sources |", "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"])
        for row in screen_summary:
            lines.append(summary_markdown_row(row))
        lines.append("")
    if trigger_rows:
        selected = [row for row in trigger_rows if bool(row.get("run_full_gate"))]
        requested = metadata.get("full_battery_values") or []
        lines.extend(
            [
                "## Full-Gate Triggers",
                "",
                f"Triggered batteries: `{', '.join(str(row['battery_kwh']) for row in selected) if selected else 'none'}`.",
                f"Full-gate battery values actually requested: `{', '.join(str(value) for value in requested) if requested else 'all triggered'}`.",
                "",
            ]
        )
    if full_summary:
        lines.extend(["## Full Gate Transition", "", "| battery | winners | all-EV | EV-heavy | balanced | CV-heavy | all-CV | mean EV share | eligible | sources |", "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"])
        for row in full_summary:
            lines.append(summary_markdown_row(row))
        lines.append("")
    lines.extend(
        [
            "## Output Files",
            "",
            f"- `{metadata['output_dir']}/metadata.json`",
            f"- `{metadata['output_dir']}/evidence_matrix.csv`",
            f"- `{metadata['output_dir']}/battery_candidate_set.csv`",
            f"- `{metadata['output_dir']}/phase1_override_audit.json`",
            f"- `{metadata['output_dir']}/fixed_replay.csv`",
            f"- `{metadata['output_dir']}/screen_raw_runs.csv`",
            f"- `{metadata['output_dir']}/screen_winners.csv`",
            f"- `{metadata['output_dir']}/screen_transition_summary.csv`",
            f"- `{metadata['output_dir']}/full_gate_triggers.csv`",
            f"- `{metadata['output_dir']}/full_gate_raw_runs.csv`",
            f"- `{metadata['output_dir']}/full_gate_winners.csv`",
            f"- `{metadata['output_dir']}/full_gate_transition_summary.csv`",
            f"- `{metadata['output_dir']}/conclusion.json`",
            "",
            "## Decision Boundary",
            "",
            "Do not promote a battery value from this report automatically. If the only strict balanced value is a legacy literature anchor, treat it as a transition reference rather than a modern default. If no current vehicle-class value produces a stable balanced band, the next honest route is an operational-constraint scenario such as charging capacity, EV capital limit, or long-route eligibility, not more battery tuning.",
            "",
        ]
    )
    return "\n".join(lines)


def summary_markdown_row(row: dict[str, Any]) -> str:
    ev_share = float(row["mean_winner_ev_share"])
    ev_text = f"{ev_share:.3f}" if math.isfinite(ev_share) else ""
    return (
        f"| {float(row['battery_kwh']):.1f} | {row['winner_count']} | {row['all_ev_winner_count']} | "
        f"{row['ev_heavy_winner_count']} | {row['balanced_winner_count']} | {row['cv_heavy_winner_count']} | "
        f"{row['all_cv_winner_count']} | {ev_text} | {row['main_scenario_eligible']} | {row['source_ids']} |"
    )


def base_run_row(
    repo_root: Path,
    phase: str,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    battery_kwh: float,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    return {
        "commit_hash": git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "phase": phase,
        "category": category,
        "instance": instance,
        "variant": variant,
        "seed": int(seed),
        "battery_kwh": float(battery_kwh),
        "B_battery_kwh": float(battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(CARBON_PRICE),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "active_flags": json.dumps(flags, sort_keys=True),
    }


def task_key(row: dict[str, Any]) -> tuple[str, float, str, str, int, str, int]:
    return (
        str(row["phase"]),
        round(float(row["battery_kwh"]), 6),
        str(row["category"]),
        str(row["instance"]),
        int(row["seed"]),
        str(row["variant"]),
        int(row["eval_budget"]),
    )


def load_completed_rows(output_dir: Path, phase: str, *, retry_timeouts: bool) -> dict[tuple[str, float, str, str, int, str, int], dict[str, Any]]:
    completed: dict[tuple[str, float, str, str, int, str, int], dict[str, Any]] = {}
    for name in (f"{phase}_raw_runs.csv", f"{phase}_raw_runs.partial.csv"):
        path = output_dir / name
        if not path.exists() or path.stat().st_size == 0:
            continue
        for row in read_csv(path):
            status = str(row.get("status", ""))
            if status == "TIMEOUT" and retry_timeouts:
                continue
            if status in TERMINAL_STATUSES:
                completed[task_key(row)] = row
    return completed


def task_queue_rows(tasks: list[dict[str, Any]], completed: dict[tuple[str, float, str, str, int, str, int], dict[str, Any]], pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("phase", "")),
            float(row.get("battery_kwh", 0.0)),
            str(row.get("category", "")),
            str(row.get("instance", "")),
            int(row.get("seed", 0)),
            variant_index(str(row.get("variant", ""))),
        ),
    )


def variant_index(variant: str) -> int:
    try:
        return VARIANT_ORDER.index(variant)
    except ValueError:
        return len(VARIANT_ORDER)


def timeout_row(repo_root: Path, task: dict[str, Any], timeout: float, elapsed: float, exc: subprocess.TimeoutExpired) -> dict[str, Any]:
    row = base_run_row(repo_root, str(task["phase"]), str(task["category"]), str(task["instance"]), str(task["variant"]), int(task["seed"]), float(task["battery_kwh"]), int(task["eval_budget"]), float(task["runtime_cap_seconds"]), {})
    row.update(
        {
            "status": "TIMEOUT",
            "elapsed_seconds": float(elapsed),
            "subprocess_timeout_seconds": float(timeout),
            "actual_evals": 0,
            "violation_count": -1,
            "route_count": 0,
            "cv_route_count": 0,
            "ev_route_count": 0,
            "composition": "timeout",
            "total_cost": math.inf,
            "subprocess_stdout_tail": tail_text(exc.stdout or ""),
            "subprocess_stderr_tail": tail_text(exc.stderr or ""),
            "error": f"subprocess exceeded {timeout:.1f}s",
        }
    )
    return row


def subprocess_error_row(repo_root: Path, task: dict[str, Any], status: str, elapsed: float, returncode: int, stdout: str, stderr: str, error: str) -> dict[str, Any]:
    row = base_run_row(repo_root, str(task["phase"]), str(task["category"]), str(task["instance"]), str(task["variant"]), int(task["seed"]), float(task["battery_kwh"]), int(task["eval_budget"]), float(task["runtime_cap_seconds"]), {})
    row.update(
        {
            "status": status,
            "elapsed_seconds": float(elapsed),
            "subprocess_returncode": int(returncode),
            "actual_evals": 0,
            "violation_count": -1,
            "route_count": 0,
            "cv_route_count": 0,
            "ev_route_count": 0,
            "composition": "error",
            "total_cost": math.inf,
            "subprocess_stdout_tail": tail_text(stdout),
            "subprocess_stderr_tail": tail_text(stderr),
            "error": error,
        }
    )
    return row


def classify_composition(cv_count: int, ev_count: int) -> str:
    total = int(cv_count) + int(ev_count)
    if total == 0:
        return "empty"
    if ev_count == 0:
        return "all_cv"
    if cv_count == 0:
        return "all_ev"
    ev_share = ev_count / total
    cv_share = cv_count / total
    if ev_share >= 0.80:
        return "ev_heavy_mixed"
    if cv_share >= 0.80:
        return "cv_heavy_mixed"
    return "balanced_mixed"


def metric_subset(metrics: dict[str, Any]) -> dict[str, float]:
    keys = [
        "total_cost",
        "cost_fix",
        "cost_km",
        "cost_fuel",
        "cost_elec",
        "cost_occ",
        "cost_transship",
        "cost_carbon",
        "E_total",
        "E_cv_direct",
        "E_ev_indirect",
        "fuel_liters",
        "ev_drive_kwh",
        "depot_charging_kwh",
        "station_charging_kwh",
    ]
    return {key: float(metrics.get(key, 0.0)) for key in keys}


def runtime_cap(instance: str, caps: tuple[float, float, float]) -> float:
    small, medium, large = caps
    n = customer_count(instance)
    if n >= 150:
        return float(large)
    if n >= 100:
        return float(medium)
    return float(small)


def customer_count(instance: str) -> int:
    match = re.search(r"-(\d+)c-", instance)
    return int(match.group(1)) if match else 0


def mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else math.nan


@contextmanager
def temporary_env(flags: dict[str, str]):
    old = {key: os.environ.get(key) for key in flags}
    try:
        for key, value in flags.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys() if not key.startswith("_")})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(value) for key, value in row.items() if not key.startswith("_")})


def ensure_csv(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else "-inf"
    return value


def tail_text(text: str, limit: int = 1200) -> str:
    value = str(text or "")
    return value[-limit:]


def git_output(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:  # noqa: BLE001
        return f"git_error:{exc}"


if __name__ == "__main__":
    raise SystemExit(main())
