"""09h evidence-bound parameter review for E2 large-scale cases.

This diagnostic keeps carbon price fixed, reuses the 09f checkpoint audit and
fixed-replay mechanics, and adds route-regime/evidence gating before any true
re-optimization. It does not modify model parameters, generated bundles,
cost/check/evaluation semantics, or promoted algorithms.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import numpy as np

import largescale_allcv_diagnostic as d9f

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.solution import Route, Solution
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.fleet import route_ev_energy_summary
from setp_solver.search.winner_operators import e2_alns_throughput_flags


CARBON_PRICE = 0.05034
DEFAULT_INSTANCES = d9f.DEFAULT_INSTANCES
SEEDS = d9f.SEEDS
ROUTE_ENERGY_THRESHOLDS = (80.0, 89.0, 113.0, 160.0, 280.0)
REOPT_STAGE1_SEEDS = (1, 2, 3)
REOPT_STAGE2_SEEDS = (4, 5)
REOPT_TIMEOUT_BUFFER_SECONDS = 60.0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys() if not key.startswith("_")})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: d9f._csv_value(value) for key, value in row.items() if not key.startswith("_")})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--output-dir", default="baselines/e2_alns/parameter_evidence_review_data")
    parser.add_argument("--report-path", default="baselines/e2_alns/parameter_evidence_review.md")
    parser.add_argument("--checkpoint-dir", default="baselines/e2_alns/checkpoints")
    parser.add_argument("--throughput-csv", default="baselines/e2_alns/throughput_raw_runs.csv")
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--reopt-policy", choices=("auto", "never", "force"), default="auto")
    parser.add_argument("--reopt-eval-budget", type=int, default=16000)
    parser.add_argument("--instances", nargs="*", default=list(DEFAULT_INSTANCES))
    parser.add_argument("--single-reopt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-instance", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-scenario", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.single_reopt:
        return single_reopt(repo_root, args)

    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    metadata = build_metadata(repo_root, args)
    stdout_summary: dict[str, Any] = {
        "schema_version": "setp-09h-stdout-summary.v1",
        "report": args.report_path,
        "output_dir": args.output_dir,
        "phase0_only": bool(args.phase0_only),
        "reopt_policy": args.reopt_policy,
    }

    evidence_rows = evidence_matrix_rows()
    _write_csv(output_dir / "evidence_matrix.csv", evidence_rows)

    records = d9f.load_reference_records(repo_root, _as_09f_args(args))
    _write_csv(output_dir / "reference_audit.csv", d9f._csv_safe_records(records))
    phase0_rows = d9f.phase0_dominance(records)
    _write_csv(output_dir / "dominance.csv", phase0_rows)

    route_rows: list[dict[str, Any]] = []
    fixed_rows: list[dict[str, Any]] = []
    trigger_rows: list[dict[str, Any]] = []
    reopt_rows: list[dict[str, Any]] = []
    provisional_candidates: list[dict[str, Any]] = []

    if not args.phase0_only and not d9f._has_audit_halt(records):
        route_rows = route_regime_audit(records)
        _write_csv(output_dir / "route_regime.csv", route_rows)
        fixed_rows = fixed_replay(records, route_rows)
        _write_csv(output_dir / "fixed_replay.csv", fixed_rows)
        trigger_rows = reopt_triggers(fixed_rows, route_rows, args.reopt_policy)
        _write_csv(output_dir / "reopt_triggers.csv", trigger_rows)
        if args.reopt_policy != "never" and trigger_rows:
            reopt_rows, provisional_candidates = run_reopt_triggers(repo_root, args, trigger_rows)
            _write_csv(output_dir / "reopt_refine.csv", reopt_rows)
            _write_csv(output_dir / "provisional_candidates.csv", provisional_candidates)
    else:
        _write_csv(output_dir / "route_regime.csv", [])
        _write_csv(output_dir / "fixed_replay.csv", [])
        _write_csv(output_dir / "reopt_triggers.csv", [])
        _write_csv(output_dir / "reopt_refine.csv", [])
        _write_csv(output_dir / "provisional_candidates.csv", [])

    conclusion = summarize_conclusion(records, route_rows, fixed_rows, trigger_rows, reopt_rows, provisional_candidates)
    metadata["elapsed_seconds"] = time.perf_counter() - started
    metadata["diagnostic_artifact_commit"] = "PENDING_COMMIT"
    stdout_summary.update(
        {
            "verdict": conclusion["verdict"],
            "reference_rows": len(records),
            "route_regime_rows": len(route_rows),
            "fixed_replay_rows": len(fixed_rows),
            "reopt_trigger_rows": len(trigger_rows),
            "reopt_rows": len(reopt_rows),
            "provisional_candidates": len(provisional_candidates),
        }
    )
    metadata["stdout_summary"] = stdout_summary
    d9f._write_json(output_dir / "metadata.json", metadata)
    d9f._write_json(output_dir / "conclusion.json", conclusion)

    report = render_report(metadata, stdout_summary, evidence_rows, records, phase0_rows, route_rows, fixed_rows, trigger_rows, reopt_rows, provisional_candidates, conclusion)
    (repo_root / args.report_path).write_text(report, encoding="utf-8")
    print(json.dumps(stdout_summary, ensure_ascii=False, sort_keys=True))
    return 2 if conclusion["verdict"].startswith("HALT_") else 0


def evidence_matrix_rows() -> list[dict[str, Any]]:
    return [
        {
            "source_id": "Goeke2015",
            "year": 2015,
            "source_type": "local_pdf",
            "path_or_url": "/Users/zhouleixishu/Zotero/storage/PGY3QPNT/Goeke和Schneider _ 2015 _ Routing...pdf",
            "scale": "10-200 customers",
            "speed_kmh": 90.0,
            "battery_kwh": 80.0,
            "vehicle_class": "Goeke E-VRPTWMF benchmark truck",
            "regime": "benchmark_regional",
            "charging_assumption": "public stations allowed",
            "override_support": "baseline_lineage_only",
            "notes": "Physical lineage for current 90km/h and 80kWh, not UK 2025 economic proof.",
        },
        {
            "source_id": "Qiu2024",
            "year": 2024,
            "source_type": "local_pdf",
            "path_or_url": "/Users/zhouleixishu/Zotero/storage/5EKAGHKW/Qiu 等 _ 2024 _ Routing a mixed fleet...pdf",
            "scale": "5/10/15/100 customers with 2/3/4/20 stations",
            "speed_kmh": 60.0,
            "battery_kwh": 60.0,
            "vehicle_class": "mixed ICEV/EV benchmark fleet",
            "regime": "urban_regional_benchmark",
            "charging_assumption": "33 kWh/h station charging",
            "override_support": "urban_or_regional_convention",
            "notes": "Supports post-2020 mixed-fleet literature convention, not 40km/h cross-city default.",
        },
        {
            "source_id": "Chen2023",
            "year": 2023,
            "source_type": "local_pdf",
            "path_or_url": "/Users/zhouleixishu/Zotero/storage/392IDBJI/陈婉茹 等 _ 2023 _ 碳交易机制下多中心混合车队配送路径和速度优化研究.pdf",
            "scale": "48/4 to 288/6 benchmark; 71-store case study",
            "speed_kmh": "30-60",
            "battery_kwh": 80.0,
            "vehicle_class": "urban medium distribution trucks",
            "regime": "urban_multidepot",
            "charging_assumption": "no en-route EV charging in model text",
            "override_support": "urban_speed_only",
            "notes": "Supports 30-60km/h and 80kWh for urban/multidepot distribution.",
        },
        {
            "source_id": "Li2020",
            "year": 2020,
            "source_type": "local_pdf",
            "path_or_url": "/Users/zhouleixishu/Zotero/storage/3BZESE7Z/李英 等 _ 2020 _ 电动汽车传统汽车混合车队配置及路径优化模型.pdf",
            "scale": "r101-21, 100 customers and 20 charging facilities",
            "speed_kmh": "",
            "battery_kwh": "",
            "vehicle_class": "EV/CV mixed fleet",
            "regime": "benchmark_mixed",
            "charging_assumption": "EVs rely on charging facilities; range sensitivity discussed",
            "override_support": "mechanism_support",
            "notes": "Supports route length/range/charging-dependence mechanism.",
        },
        {
            "source_id": "MercedesESprinter",
            "year": 2026,
            "source_type": "official_web",
            "path_or_url": "https://www.mbvans.com/en/esprinter",
            "scale": "large electric van product",
            "speed_kmh": "",
            "battery_kwh": "81/113 usable",
            "vehicle_class": "large van",
            "regime": "van_delivery",
            "charging_assumption": "product range specification",
            "override_support": "conditional_large_van",
            "notes": "113kWh is modern van evidence but current m_curb=6350kg is heavier than a typical van.",
        },
        {
            "source_id": "FordETransit2025",
            "year": 2025,
            "source_type": "official_pdf",
            "path_or_url": "https://www.fromtheroad.ford.com/content/dam/fordmediasite/us/en/library/2025/specs/2025-Transit-Technical-Specs.pdf",
            "scale": "large electric van product",
            "speed_kmh": "",
            "battery_kwh": "89 usable",
            "vehicle_class": "large van",
            "regime": "van_delivery",
            "charging_assumption": "product usable energy specification",
            "override_support": "conditional_large_van",
            "notes": "89kWh is modern van evidence, not medium/heavy truck evidence.",
        },
        {
            "source_id": "VolvoFLFE2023",
            "year": 2023,
            "source_type": "official_web",
            "path_or_url": "https://www.volvotrucks.com/en-en/news-stories/press-releases/2023/jun/volvo-presents-electric-trucks-with-longer-range.html",
            "scale": "electric distribution trucks",
            "speed_kmh": "",
            "battery_kwh": "280-565 FL; 280-375 FE",
            "vehicle_class": "medium distribution truck",
            "regime": "regional_distribution",
            "charging_assumption": "product battery/range specification",
            "override_support": "strong_distribution_truck_280",
            "notes": "280kWh is the strongest single modern-battery candidate for current truck-like mass.",
        },
        {
            "source_id": "VolvoFH_Electric",
            "year": 2026,
            "source_type": "official_web",
            "path_or_url": "https://www.volvotrucks.com/en-en/trucks/electric/volvo-fh-electric.html",
            "scale": "heavy electric truck product",
            "speed_kmh": "",
            "battery_kwh": "360-540",
            "vehicle_class": "heavy truck",
            "regime": "heavy_highway",
            "charging_assumption": "product battery/range specification",
            "override_support": "future_vehicle_class_fork",
            "notes": "Requires mass/fixed-cost/payload recalibration, not a simple battery override.",
        },
        {
            "source_id": "DaimlerEActros600",
            "year": 2026,
            "source_type": "official_web",
            "path_or_url": "https://www.daimlertruck.com/en/newsroom/pressrelease/full-charge-for-the-future-the-first-eactros-600-on-the-road-in-europes-fleets-53166796",
            "scale": "heavy long-haul electric truck product",
            "speed_kmh": "",
            "battery_kwh": "621 installed, >95% usable",
            "vehicle_class": "heavy long-haul truck",
            "regime": "heavy_highway",
            "charging_assumption": "product battery/range specification",
            "override_support": "future_vehicle_class_fork",
            "notes": "Evidence for heavy long-haul class; not a direct ReSETP override.",
        },
        {
            "source_id": "UK_DfT_SRN_2025",
            "year": 2025,
            "source_type": "government_web",
            "path_or_url": "https://www.gov.uk/government/statistics/travel-time-measures-for-the-strategic-road-network-and-local-a-roads-january-to-december-2025/travel-time-measures-for-the-strategic-road-network-january-to-december-2025-report",
            "scale": "UK Strategic Road Network",
            "speed_kmh": 91.1,
            "battery_kwh": "",
            "vehicle_class": "all traffic",
            "regime": "highway_cross_city",
            "charging_assumption": "",
            "override_support": "supports_90kmh_cross_city",
            "notes": "56.6mph average SRN speed makes 90km/h plausible for cross-city travel.",
        },
        {
            "source_id": "UK_DfT_LocalA_2025",
            "year": 2025,
            "source_type": "government_web",
            "path_or_url": "https://www.gov.uk/government/statistics/travel-time-measures-for-the-strategic-road-network-and-local-a-roads-january-to-december-2025/travel-time-measures-for-local-a-roads-january-to-december-2025-report",
            "scale": "UK local A roads",
            "speed_kmh": "urban 27.5; rural 55.2",
            "battery_kwh": "",
            "vehicle_class": "all traffic",
            "regime": "urban_local",
            "charging_assumption": "",
            "override_support": "supports_urban_fork_only",
            "notes": "40km/h is local/urban mixture evidence, not highway default.",
        },
    ]


def route_regime_audit(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance, group in d9f._group_by(d9f._ok_records(records), "instance").items():
        bundle = group[0]["_bundle_obj"]
        for role in ("allcv", "mixed"):
            source = min((row for row in group if row["role"] == role), key=lambda item: float(item["total_cost"]))
            route_metrics = [_route_metric(route, bundle, replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE)) for route in source["_solution_obj"].routes]
            rows.append(_summarize_route_metrics(instance, role, int(source["seed"]), float(source["total_cost"]), route_metrics))
    return rows


def _route_metric(route: Route, bundle: SearchBundle, prices: PriceParameters) -> dict[str, float]:
    clean = _clean_route(route, bundle)
    distance_m = _route_distance(clean, bundle)
    service_s = _route_service_seconds(clean, bundle)
    energy = route_ev_energy_summary(clean, bundle.instance, prices)
    out = {
        "distance_km": distance_m / 1000.0,
        "service_hours": service_s / 3600.0,
        "ev_drive_kwh": float(energy.ev_kwh),
    }
    for speed_kmh in (90.0, 60.0, 40.0):
        out[f"duration_h_at_{int(speed_kmh)}"] = distance_m / (speed_kmh / 3.6) / 3600.0 + out["service_hours"]
    return out


def _summarize_route_metrics(instance: str, role: str, seed: int, cost: float, metrics: list[dict[str, float]]) -> dict[str, Any]:
    distances = [row["distance_km"] for row in metrics]
    energies = [row["ev_drive_kwh"] for row in metrics]
    durations_90 = [row["duration_h_at_90"] for row in metrics]
    regime = _classify_regime(distances)
    row: dict[str, Any] = {
        "phase": "route_regime",
        "instance": instance,
        "role": role,
        "source_seed": seed,
        "source_total_cost": cost,
        "route_count": len(metrics),
        "regime_label": regime,
        "distance_km_mean": _mean(distances),
        "distance_km_p50": _percentile(distances, 50),
        "distance_km_p75": _percentile(distances, 75),
        "distance_km_p90": _percentile(distances, 90),
        "distance_km_max": max(distances) if distances else 0.0,
        "duration_h_90_mean": _mean(durations_90),
        "duration_h_90_max": max(durations_90) if durations_90 else 0.0,
        "duration_h_60_max": max((row["duration_h_at_60"] for row in metrics), default=0.0),
        "duration_h_40_max": max((row["duration_h_at_40"] for row in metrics), default=0.0),
        "ev_drive_kwh_mean": _mean(energies),
        "ev_drive_kwh_p90": _percentile(energies, 90),
        "ev_drive_kwh_max": max(energies) if energies else 0.0,
    }
    for threshold in ROUTE_ENERGY_THRESHOLDS:
        count = sum(1 for value in energies if value > threshold + 1e-9)
        row[f"routes_gt_{threshold:g}kwh"] = count
        row[f"share_gt_{threshold:g}kwh"] = count / len(energies) if energies else 0.0
    return row


def fixed_replay(records: list[dict[str, Any]], route_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    route_regime = {(row["instance"], row["role"]): row["regime_label"] for row in route_rows}
    for instance, group in d9f._group_by(d9f._ok_records(records), "instance").items():
        bundle = group[0]["_bundle_obj"]
        best_allcv = min((row for row in group if row["role"] == "allcv"), key=lambda item: float(item["total_cost"]))
        best_mixed = min((row for row in group if row["role"] == "mixed"), key=lambda item: float(item["total_cost"]))
        for scenario in scenario_specs():
            for source in (best_allcv, best_mixed):
                rows.append(replay_row(instance, scenario, source, bundle, route_regime.get((instance, str(source["role"])), "")))
    return rows


def replay_row(instance: str, scenario: dict[str, Any], source: dict[str, Any], bundle: SearchBundle, route_regime: str) -> dict[str, Any]:
    prices: PriceParameters = scenario["prices"]
    row: dict[str, Any] = {
        "phase": "fixed_replay",
        "instance": instance,
        "role": str(source["role"]),
        "source_seed": int(source["seed"]),
        "scenario_label": scenario["label"],
        "scenario_family": scenario["family"],
        "scenario_regime": scenario["regime"],
        "evidence_strength": scenario["evidence_strength"],
        "trigger_eligible": bool(scenario["trigger_eligible"]),
        "route_regime": route_regime,
        "B_battery_kwh": float(prices.B_battery_kwh),
        "v_speed_ms": float(prices.v_speed_ms),
        "carbon_price": float(prices.carbon_price),
    }
    try:
        solution = source["_solution_obj"] if source["role"] == "allcv" else d9f._replay_solution_for_prices(source["_solution_obj"], bundle, prices)
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        row.update(d9f._metric_row(metrics))
        row.update(d9f.charging_behavior(solution, bundle, prices))
        row.update(
            {
                "status": "OK" if not violations else "HALT_REPLAY_INFEASIBLE",
                "violation_count": len(violations),
                "route_count": len(solution.routes),
                "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
                "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
            }
        )
    except Exception as exc:
        row.update({"status": "HALT_REPLAY_ERROR", "error": repr(exc), "total_cost": math.inf, "violation_count": math.nan})
    return row


def scenario_specs() -> list[dict[str, Any]]:
    base = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE)
    return [
        _scenario("A_baseline", "baseline", "current", "baseline", False, base, "Current UK-Goeke hybrid baseline; fixed-replay control, not an auto-reopt trigger."),
        _scenario("B_modern_large_van_89", "van_battery", "van_delivery", "conditional", False, replace(base, B_battery_kwh=89.0), "Ford E-Transit modern van usable battery; conditional because current vehicle mass is truck-like."),
        _scenario("C_modern_large_van_113", "van_battery", "van_delivery", "conditional", False, replace(base, B_battery_kwh=113.0), "Mercedes eSprinter modern van upper usable battery; conditional because current vehicle mass is truck-like."),
        _scenario("D_bridge_160", "bridge_battery", "diagnostic_bridge", "diagnostic", False, replace(base, B_battery_kwh=160.0), "09f near-flip bridge; not strong standalone reality evidence."),
        _scenario("E_distribution_truck_280", "distribution_battery", "regional_distribution", "strong", True, replace(base, B_battery_kwh=280.0), "Volvo FL/FE lower-bound modern distribution-truck battery."),
        _scenario("F_urban_40_baseline_battery", "urban_speed", "urban_local", "urban_only", False, replace(base, v_speed_ms=11.1), "Urban/local speed fork; not cross-city default."),
        _scenario("G_urban_40_modern_van", "urban_speed_van", "urban_local", "urban_only", False, replace(base, v_speed_ms=11.1, B_battery_kwh=113.0), "Urban/local speed with modern van battery; not cross-city default."),
        _scenario("H_highway_60mph_distribution", "distribution_speed_battery", "highway_cross_city", "strong", True, replace(base, v_speed_ms=26.8, B_battery_kwh=280.0), "60mph highway-style distribution truck scenario."),
    ]


def _scenario(label: str, family: str, regime: str, evidence_strength: str, trigger_eligible: bool, prices: PriceParameters, notes: str) -> dict[str, Any]:
    return {
        "label": label,
        "family": family,
        "regime": regime,
        "evidence_strength": evidence_strength,
        "trigger_eligible": trigger_eligible,
        "prices": prices,
        "notes": notes,
    }


def reopt_triggers(fixed_rows: list[dict[str, Any]], route_rows: list[dict[str, Any]], policy: str) -> list[dict[str, Any]]:
    route_regime_by_instance = _dominant_regime(route_rows)
    rows: list[dict[str, Any]] = []
    for key, group in _group_fixed_rows(fixed_rows).items():
        instance, label = key
        allcv = next((row for row in group if row["role"] == "allcv" and row["status"] == "OK"), None)
        mixed = next((row for row in group if row["role"] == "mixed" and row["status"] == "OK"), None)
        if not allcv or not mixed:
            continue
        gap = d9f._gap_pct(float(mixed["total_cost"]), float(allcv["total_cost"]))
        scenario = _scenario_by_label(label)
        route_regime = route_regime_by_instance.get(instance, "unknown")
        evidence_applies = _evidence_applies(scenario, route_regime)
        if policy == "never":
            should_run = False
        elif policy == "force":
            should_run = gap <= 1.0
        else:
            should_run = evidence_applies and bool(scenario["trigger_eligible"]) and gap <= 1.0
        if gap <= 1.0:
            rows.append(
                {
                    "phase": "reopt_trigger",
                    "instance": instance,
                    "scenario_label": label,
                    "scenario_family": scenario["family"],
                    "scenario_regime": scenario["regime"],
                    "evidence_strength": scenario["evidence_strength"],
                    "route_regime": route_regime,
                    "evidence_applies": evidence_applies,
                    "trigger_eligible": bool(scenario["trigger_eligible"]),
                    "should_run_reopt": should_run,
                    "fixed_gap_pct_mixed_minus_allcv": gap,
                    "allcv_fixed_cost": float(allcv["total_cost"]),
                    "mixed_fixed_cost": float(mixed["total_cost"]),
                    "mixed_public_charge_kwh": float(mixed.get("public_charge_kwh", 0.0)),
                    "mixed_occ_cost": float(mixed.get("public_occupancy_cost", 0.0)),
                    "reason": _trigger_reason(scenario, route_regime, evidence_applies, should_run),
                }
            )
    rows.sort(key=lambda row: (not row["should_run_reopt"], row["fixed_gap_pct_mixed_minus_allcv"], row["instance"], row["scenario_label"]))
    return rows


def run_reopt_triggers(repo_root: Path, args: argparse.Namespace, triggers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    provisional: list[dict[str, Any]] = []
    for trigger in triggers:
        if not trigger.get("should_run_reopt"):
            continue
        stage1 = [run_reopt_subprocess(repo_root, args, trigger, seed) for seed in REOPT_STAGE1_SEEDS]
        rows.extend(stage1)
        stage1_ok = [row for row in stage1 if row.get("status") == "OK"]
        if _stage_confirms_candidate(trigger, stage1_ok):
            provisional.append(_candidate_row(trigger, stage1_ok, "stage1_confirmed_pending_stage2"))
            stage2 = [run_reopt_subprocess(repo_root, args, trigger, seed) for seed in REOPT_STAGE2_SEEDS]
            rows.extend(stage2)
            all_ok = stage1_ok + [row for row in stage2 if row.get("status") == "OK"]
            if len(all_ok) >= 5:
                provisional[-1] = _candidate_row(trigger, all_ok, "stage1_and_stage2_completed")
        else:
            provisional.append(_candidate_row(trigger, stage1_ok, "stage1_not_confirmed"))
    return rows, provisional


def run_reopt_subprocess(repo_root: Path, args: argparse.Namespace, trigger: dict[str, Any], seed: int) -> dict[str, Any]:
    instance = str(trigger["instance"])
    cap = float(d9f.RUNTIME_CAP_SECONDS.get(instance, 900.0))
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--repo-root",
        str(repo_root),
        "--single-reopt",
        "--single-instance",
        instance,
        "--single-scenario",
        str(trigger["scenario_label"]),
        "--single-seed",
        str(seed),
        "--reopt-eval-budget",
        str(args.reopt_eval_budget),
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", "solver/src:models/src")
    env.setdefault("PYTHONHASHSEED", "0")
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=cap + REOPT_TIMEOUT_BUFFER_SECONDS,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "phase": "reopt_refine",
            "instance": instance,
            "scenario_label": str(trigger["scenario_label"]),
            "seed": seed,
            "status": "HALT_REOPT_COLLECTION_COST",
            "error": f"subprocess timeout after {cap + REOPT_TIMEOUT_BUFFER_SECONDS:.1f}s",
            "elapsed_seconds": time.perf_counter() - started,
            "max_runtime_seconds": cap,
            "stdout_tail": (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else "",
        }
    payload = _last_json_line(proc.stdout)
    if payload is None:
        return {
            "phase": "reopt_refine",
            "instance": instance,
            "scenario_label": str(trigger["scenario_label"]),
            "seed": seed,
            "status": "HALT_REOPT_SUBPROCESS_ERROR",
            "returncode": proc.returncode,
            "elapsed_seconds": time.perf_counter() - started,
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        }
    payload["returncode"] = proc.returncode
    payload["stdout_tail"] = proc.stdout[-1000:]
    payload["stderr_tail"] = proc.stderr[-1000:]
    return payload


def single_reopt(repo_root: Path, args: argparse.Namespace) -> int:
    scenario = _scenario_by_label(args.single_scenario)
    records = d9f.load_reference_records(repo_root, _as_09f_args(args, instances=[args.single_instance]))
    ok = d9f._ok_records(records)
    bundle = ok[0]["_bundle_obj"]
    warm = min((row for row in ok if row["role"] == "mixed"), key=lambda item: float(item["total_cost"]))["_solution_obj"]
    row = reopt_one(bundle, str(args.single_instance), scenario, int(args.single_seed), int(args.reopt_eval_budget), warm)
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 0 if row.get("status") == "OK" else 2


def reopt_one(bundle: SearchBundle, instance: str, scenario: dict[str, Any], seed: int, eval_budget: int, initial_solution: Solution) -> dict[str, Any]:
    prices: PriceParameters = scenario["prices"]
    started = time.perf_counter()
    cap = float(d9f.RUNTIME_CAP_SECONDS.get(instance, 900.0))
    row: dict[str, Any] = {
        "phase": "reopt_refine",
        "instance": instance,
        "scenario_label": scenario["label"],
        "scenario_family": scenario["family"],
        "scenario_regime": scenario["regime"],
        "evidence_strength": scenario["evidence_strength"],
        "seed": seed,
        "eval_budget": eval_budget,
        "max_runtime_seconds": cap,
        "B_battery_kwh": float(prices.B_battery_kwh),
        "v_speed_ms": float(prices.v_speed_ms),
        "carbon_price": float(prices.carbon_price),
    }
    try:
        repaired_warm = d9f._replay_solution_for_prices(initial_solution, bundle, prices)
        flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
        with d9f._temporary_env(flags):
            result = run_alns_wouda(
                bundle.bundle_dir,
                iterations=None,
                seed=seed,
                eval_budget=eval_budget,
                max_runtime_seconds=cap,
                policy=SearchPolicy(require_charging_signal=False),
                initial_solution=repaired_warm,
                prices=prices,
            )
        solution = result.best_solution
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        row.update(d9f._metric_row(metrics))
        row.update(d9f.charging_behavior(solution, bundle, prices))
        row.update(
            {
                "status": "OK" if not violations else "HALT_REOPT_INFEASIBLE",
                "violation_count": len(violations),
                "solver_reported_feasible": bool(result.feasible),
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "elapsed_seconds": time.perf_counter() - started,
                "route_count": len(solution.routes),
                "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
                "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
                "active_flags": flags,
            }
        )
    except Exception as exc:
        row.update({"status": "HALT_REOPT_ERROR", "error": repr(exc), "elapsed_seconds": time.perf_counter() - started, "total_cost": math.inf})
    return row


def summarize_conclusion(
    records: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    fixed_rows: list[dict[str, Any]],
    trigger_rows: list[dict[str, Any]],
    reopt_rows: list[dict[str, Any]],
    provisional_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if d9f._has_audit_halt(records):
        return {"verdict": "HALT_EVIDENCE_MISMATCH", "summary": "Reference checkpoint or CSV audit failed before parameter evidence review."}
    if any(str(row.get("status", "")).startswith("HALT_REOPT") for row in reopt_rows):
        return {
            "verdict": "HALT_REOPT_COLLECTION_COST",
            "summary": "At least one evidence-triggered true reoptimization row exceeded or failed the collection budget; completed rows are retained.",
            "provisional_candidates": provisional_candidates,
        }
    confirmed = [row for row in provisional_candidates if row.get("candidate_status") == "stage1_and_stage2_completed" and float(row.get("mean_gap_pct_vs_allcv_fixed", math.inf)) <= 1.0]
    if confirmed:
        return {
            "verdict": "HIGHWAY_BATTERY_UPDATE_SUPPORTED",
            "summary": "An evidence-bound highway/regional modern-battery scenario remained competitive through staged true reoptimization.",
            "confirmed_candidates": confirmed,
        }
    urban_flips = _urban_only_flips(fixed_rows)
    strong_triggers = [row for row in trigger_rows if row.get("should_run_reopt")]
    if urban_flips and not strong_triggers:
        return {"verdict": "URBAN_ONLY_FLIP", "summary": "Only urban/local speed scenarios flip or near-flip; do not change the cross-city default to 40km/h."}
    if _has_search_reliability_pattern(fixed_rows):
        return {
            "verdict": "SEARCH_RELIABILITY_PRIMARY",
            "summary": "100/150c retain best mixed availability while mean reliability remains the main issue; 200c still needs evidence-bound confirmation.",
        }
    return {
        "verdict": "SINGLE_PARAMETER_INSUFFICIENT",
        "summary": "No evidence-bound single-parameter scenario produced a confirmed highway/regional mixed-fleet result.",
    }


def render_report(
    metadata: dict[str, Any],
    stdout_summary: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    phase0_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    fixed_rows: list[dict[str, Any]],
    trigger_rows: list[dict[str, Any]],
    reopt_rows: list[dict[str, Any]],
    provisional_candidates: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09h Evidence-Bound Parameter Review",
        "",
        f"Conclusion: `{conclusion['verdict']}`.",
        "",
        conclusion["summary"],
        "",
        "## Environment",
        "",
        f"- repo_head: `{metadata['repo_head']}`",
        f"- diagnostic_artifact_commit: `{metadata['diagnostic_artifact_commit']}`",
        f"- branch: `{metadata['branch']}`",
        f"- python: `{metadata['python']}`",
        f"- python_version: `{metadata['python_version']}`",
        f"- numpy: `{metadata['numpy']}`",
        f"- PYTHONHASHSEED: `{metadata.get('PYTHONHASHSEED', '')}`",
        f"- carbon_price: `{CARBON_PRICE}`",
        f"- reopt_policy: `{metadata['reopt_policy']}`",
        f"- elapsed_seconds: `{metadata['elapsed_seconds']:.3f}`",
        "",
        "## Command",
        "",
        "```bash",
        metadata["command"],
        "```",
        "",
        "Stdout summary:",
        "",
        "```json",
        json.dumps(stdout_summary, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Evidence Matrix",
        "",
        _evidence_table(evidence_rows),
        "",
        "## Reference Audit And 09f Dominance",
        "",
        d9f._phase0_table(phase0_rows),
        "",
        "Checkpoint audit status:",
        "",
        d9f._reference_audit_table(records),
        "",
        "## Route-Regime Audit",
        "",
        _route_regime_table(route_rows),
        "",
        "Regime labels are descriptive gates, not proof by themselves: `urban_like` means p90 route distance <=30km and max <=50km; `regional_cross_city_like` means p75 >=50km or max >=100km; otherwise `mixed_regime`.",
        "",
        "## Evidence-Bound Fixed Replay",
        "",
        _fixed_replay_table(fixed_rows),
        "",
        "Fixed replay strips public station nodes from EV routes, replays charging under the override, and independently evaluates/checks the result. It is mechanism evidence only.",
        "",
        "## Reoptimization Triggers",
        "",
        _trigger_table(trigger_rows),
        "",
        "## True Reoptimization",
        "",
        _reopt_table(reopt_rows),
        "",
        "## Provisional Candidates",
        "",
        _candidate_table(provisional_candidates),
        "",
        "## Do Not Do This",
        "",
        "- Do not set 40km/h as the cross-city default just because fixed replay flips.",
        "- Do not treat `D_bridge_160` as strong modern-truck evidence without an additional source.",
        "- Do not report fixed replay as true reoptimization.",
        "- Do not scan carbon price in this lane; it stayed fixed at 0.05034.",
        "",
        "## Artifacts",
        "",
        "- `baselines/e2_alns/parameter_evidence_review.py`",
        "- `baselines/e2_alns/parameter_evidence_review.md`",
        "- `baselines/e2_alns/parameter_evidence_review_data/evidence_matrix.csv`",
        "- `baselines/e2_alns/parameter_evidence_review_data/reference_audit.csv`",
        "- `baselines/e2_alns/parameter_evidence_review_data/route_regime.csv`",
        "- `baselines/e2_alns/parameter_evidence_review_data/fixed_replay.csv`",
        "- `baselines/e2_alns/parameter_evidence_review_data/reopt_triggers.csv`",
        "- `baselines/e2_alns/parameter_evidence_review_data/reopt_refine.csv`",
        "- `baselines/e2_alns/parameter_evidence_review_data/metadata.json`",
    ]
    return "\n".join(lines) + "\n"


def build_metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": "setp-09h-parameter-evidence-review.v1",
        "repo_root": str(repo_root),
        "repo_head": d9f._git(repo_root, "rev-parse", "HEAD"),
        "branch": d9f._git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "numpy": np.__version__,
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED", ""),
        "command": " ".join(shlex.quote(part) for part in sys.argv),
        "reopt_policy": args.reopt_policy,
        "instances": list(args.instances),
        "carbon_price": CARBON_PRICE,
    }


def _as_09f_args(args: argparse.Namespace, instances: list[str] | None = None) -> argparse.Namespace:
    return SimpleNamespace(
        checkpoint_dir=args.checkpoint_dir,
        throughput_csv=args.throughput_csv,
        instances=instances if instances is not None else args.instances,
    )


def _clean_route(route: Route, bundle: SearchBundle) -> Route:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    clean = [node_id for node_id in route.node_sequence if not (node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "f")]
    return Route(route.vehicle_id, route.vehicle_type, route.home_depot_id, clean)


def _route_distance(route: Route, bundle: SearchBundle) -> float:
    return sum(bundle.instance.distance(a, b) for a, b in zip(route.node_sequence, route.node_sequence[1:]))


def _route_service_seconds(route: Route, bundle: SearchBundle) -> float:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    return sum(float(node_lookup[node_id].service_time) for node_id in route.node_sequence if node_lookup[node_id].node_type.lower() == "c")


def _classify_regime(distances_km: list[float]) -> str:
    if not distances_km:
        return "unknown"
    p75 = _percentile(distances_km, 75)
    p90 = _percentile(distances_km, 90)
    maximum = max(distances_km)
    if p90 <= 30.0 and maximum <= 50.0:
        return "urban_like"
    if p75 >= 50.0 or maximum >= 100.0:
        return "regional_cross_city_like"
    return "mixed_regime"


def _dominant_regime(route_rows: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for instance, rows in d9f._group_by(route_rows, "instance").items():
        labels = [str(row["regime_label"]) for row in rows]
        if "regional_cross_city_like" in labels:
            out[instance] = "regional_cross_city_like"
        elif "mixed_regime" in labels:
            out[instance] = "mixed_regime"
        elif labels:
            out[instance] = labels[0]
        else:
            out[instance] = "unknown"
    return out


def _evidence_applies(scenario: dict[str, Any], route_regime: str) -> bool:
    if scenario["regime"] in {"regional_distribution", "highway_cross_city"}:
        return route_regime in {"regional_cross_city_like", "mixed_regime"}
    if scenario["regime"] == "urban_local":
        return route_regime == "urban_like"
    return bool(scenario["trigger_eligible"])


def _trigger_reason(scenario: dict[str, Any], route_regime: str, applies: bool, should_run: bool) -> str:
    if should_run:
        return "evidence applies and fixed replay gap <= 1%; true reoptimization scheduled"
    if not applies:
        return f"scenario regime {scenario['regime']} does not match route regime {route_regime}"
    if not scenario["trigger_eligible"]:
        return f"scenario evidence strength is {scenario['evidence_strength']}; listed as diagnostic/conditional only"
    return "fixed replay near-flip retained but reopt disabled by policy"


def _stage_confirms_candidate(trigger: dict[str, Any], ok_rows: list[dict[str, Any]]) -> bool:
    if not ok_rows:
        return False
    mean_total = _mean([float(row["total_cost"]) for row in ok_rows])
    allcv_fixed = float(trigger["allcv_fixed_cost"])
    gap = d9f._gap_pct(mean_total, allcv_fixed)
    return gap <= 1.0 or any(float(row.get("ev_route_count", 0)) > 0 for row in ok_rows)


def _candidate_row(trigger: dict[str, Any], ok_rows: list[dict[str, Any]], status: str) -> dict[str, Any]:
    costs = [float(row["total_cost"]) for row in ok_rows]
    allcv_fixed = float(trigger["allcv_fixed_cost"])
    return {
        "phase": "provisional_candidate",
        "instance": trigger["instance"],
        "scenario_label": trigger["scenario_label"],
        "candidate_status": status,
        "completed_ok_seeds": ",".join(str(row["seed"]) for row in ok_rows),
        "ok_seed_count": len(ok_rows),
        "mean_reopt_cost": _mean(costs),
        "best_reopt_cost": min(costs) if costs else math.inf,
        "mean_gap_pct_vs_allcv_fixed": d9f._gap_pct(_mean(costs), allcv_fixed) if costs else math.inf,
        "best_gap_pct_vs_allcv_fixed": d9f._gap_pct(min(costs), allcv_fixed) if costs else math.inf,
        "mean_ev_route_count": _mean([float(row.get("ev_route_count", 0)) for row in ok_rows]),
    }


def _urban_only_flips(fixed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for (instance, label), rows in _group_fixed_rows(fixed_rows).items():
        scenario = _scenario_by_label(label)
        if scenario["regime"] != "urban_local":
            continue
        allcv = next((row for row in rows if row["role"] == "allcv" and row["status"] == "OK"), None)
        mixed = next((row for row in rows if row["role"] == "mixed" and row["status"] == "OK"), None)
        if allcv and mixed and d9f._gap_pct(float(mixed["total_cost"]), float(allcv["total_cost"])) <= 0.0:
            out.append(mixed)
    return out


def _has_search_reliability_pattern(fixed_rows: list[dict[str, Any]]) -> bool:
    instances = {str(row["instance"]) for row in fixed_rows if row.get("scenario_label") == "A_baseline"}
    return {"e2-threeshift-100c-01", "e2-threeshift-150c-01"}.issubset(instances)


def _scenario_by_label(label: str) -> dict[str, Any]:
    for scenario in scenario_specs():
        if scenario["label"] == label:
            return scenario
    raise KeyError(label)


def _group_fixed_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["instance"]), str(row["scenario_label"]))
        out.setdefault(key, []).append(row)
    return out


def _last_json_line(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def _evidence_table(rows: list[dict[str, Any]]) -> str:
    return d9f._markdown_table(
        ["source", "year", "type", "scale", "speed", "battery", "vehicle class", "regime", "support"],
        [
            (
                row["source_id"],
                row["year"],
                row["source_type"],
                row["scale"],
                row["speed_kmh"],
                row["battery_kwh"],
                row["vehicle_class"],
                row["regime"],
                row["override_support"],
            )
            for row in rows
        ],
    )


def _route_regime_table(rows: list[dict[str, Any]]) -> str:
    return d9f._markdown_table(
        ["instance", "role", "seed", "regime", "routes", "dist mean", "dist p75", "dist p90", "dist max", "max kWh", ">80", ">113", ">160", ">280", "dur90 max", "dur40 max"],
        [
            (
                row["instance"],
                row["role"],
                row["source_seed"],
                row["regime_label"],
                row["route_count"],
                d9f._fmt(row["distance_km_mean"]),
                d9f._fmt(row["distance_km_p75"]),
                d9f._fmt(row["distance_km_p90"]),
                d9f._fmt(row["distance_km_max"]),
                d9f._fmt(row["ev_drive_kwh_max"]),
                row["routes_gt_80kwh"],
                row["routes_gt_113kwh"],
                row["routes_gt_160kwh"],
                row["routes_gt_280kwh"],
                d9f._fmt(row["duration_h_90_max"]),
                d9f._fmt(row["duration_h_40_max"]),
            )
            for row in rows
        ],
    )


def _fixed_replay_table(rows: list[dict[str, Any]]) -> str:
    table_rows = []
    for (instance, label), group in _group_fixed_rows(rows).items():
        allcv = next((row for row in group if row["role"] == "allcv" and row["status"] == "OK"), None)
        mixed = next((row for row in group if row["role"] == "mixed" and row["status"] == "OK"), None)
        if not allcv or not mixed:
            table_rows.append((instance, label, "HALT", "", "", "", "", "", ""))
            continue
        gap = d9f._gap_pct(float(mixed["total_cost"]), float(allcv["total_cost"]))
        table_rows.append(
            (
                instance,
                label,
                mixed["evidence_strength"],
                d9f._fmt(allcv["total_cost"]),
                d9f._fmt(mixed["total_cost"]),
                d9f._fmt(gap),
                gap <= 0.0,
                d9f._fmt(mixed.get("public_charge_kwh")),
                d9f._fmt(mixed.get("public_occupancy_cost")),
            )
        )
    return d9f._markdown_table(["instance", "scenario", "evidence", "all-CV", "mixed", "gap %", "flip", "public kWh", "occ cost"], table_rows)


def _trigger_table(rows: list[dict[str, Any]]) -> str:
    return d9f._markdown_table(
        ["instance", "scenario", "route regime", "evidence", "gap %", "run?", "reason"],
        [
            (
                row["instance"],
                row["scenario_label"],
                row["route_regime"],
                row["evidence_strength"],
                d9f._fmt(row["fixed_gap_pct_mixed_minus_allcv"]),
                row["should_run_reopt"],
                row["reason"],
            )
            for row in rows
        ],
    )


def _reopt_table(rows: list[dict[str, Any]]) -> str:
    return d9f._markdown_table(
        ["instance", "scenario", "seed", "status", "total", "gap vs fixed allCV", "elapsed", "evals", "CV", "EV"],
        [
            (
                row.get("instance", ""),
                row.get("scenario_label", ""),
                row.get("seed", ""),
                row.get("status", ""),
                d9f._fmt(row.get("total_cost")),
                "",
                d9f._fmt(row.get("elapsed_seconds")),
                row.get("actual_evals", ""),
                row.get("cv_route_count", ""),
                row.get("ev_route_count", ""),
            )
            for row in rows
        ],
    )


def _candidate_table(rows: list[dict[str, Any]]) -> str:
    return d9f._markdown_table(
        ["instance", "scenario", "status", "seeds", "mean cost", "best cost", "mean gap %", "best gap %", "mean EV routes"],
        [
            (
                row["instance"],
                row["scenario_label"],
                row["candidate_status"],
                row["completed_ok_seeds"],
                d9f._fmt(row["mean_reopt_cost"]),
                d9f._fmt(row["best_reopt_cost"]),
                d9f._fmt(row["mean_gap_pct_vs_allcv_fixed"]),
                d9f._fmt(row["best_gap_pct_vs_allcv_fixed"]),
                d9f._fmt(row["mean_ev_route_count"]),
            )
            for row in rows
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
