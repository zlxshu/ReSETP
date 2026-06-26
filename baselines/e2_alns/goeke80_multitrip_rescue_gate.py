#!/usr/bin/env python3
"""09s Goeke-80 + physical-fleet multi-trip rescue gate.

This runner does not claim that the algorithm comparison is fixed.  It first
checks the corrected baseline semantics: Goeke payload Q=3650, Goeke battery
B=80, speed/carbon/economics unchanged, and num_cv/num_ev interpreted as hard
physical-vehicle caps rather than route/trip caps.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.e2_alns_throughput import run_gate
from setp_solver.solution import physical_vehicle_id


BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
OUTPUT_DIR = Path("baselines/e2_alns/goeke80_multitrip_rescue_gate_data")
REPORT_PATH = Path("baselines/e2_alns/goeke80_multitrip_rescue_gate.md")
VANILLA_MULTIDEPOT_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
THREESHIFT_SIZES = (50, 75, 100, 150, 200)
REPLICATES = (1, 2, 3)
REPRESENTATIVE_ROWS = (
    ("vanilla", "e2-vanilla-10c-01", 180.0),
    ("vanilla", "e2-vanilla-25c-01", 180.0),
    ("vanilla", "e2-vanilla-75c-01", 240.0),
    ("vanilla", "e2-vanilla-100c-01", 300.0),
    ("vanilla", "e2-vanilla-150c-01", 600.0),
    ("vanilla", "e2-vanilla-200c-01", 900.0),
    ("multidepot", "e2-multidepot-10c-01", 180.0),
    ("multidepot", "e2-multidepot-25c-01", 180.0),
    ("multidepot", "e2-multidepot-75c-01", 240.0),
    ("multidepot", "e2-multidepot-100c-01", 300.0),
    ("multidepot", "e2-multidepot-150c-01", 600.0),
    ("multidepot", "e2-multidepot-200c-01", 900.0),
    ("threeshift", "e2-threeshift-50c-01", 240.0),
    ("threeshift", "e2-threeshift-75c-01", 300.0),
    ("threeshift", "e2-threeshift-100c-01", 300.0),
    ("threeshift", "e2-threeshift-150c-01", 900.0),
    ("threeshift", "e2-threeshift-200c-01", 900.0),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--phase1-only", action="store_true")
    parser.add_argument("--phase2-smoke", action="store_true")
    parser.add_argument("--seeds", nargs="*", type=int, default=[1])
    parser.add_argument("--eval-budget", type=int, default=300)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--artifact-commit-hash", default="")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    report_path = repo_root / args.report_path
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    metadata = build_metadata(repo_root, args)
    phase0 = phase0_audit(repo_root)
    write_json(output_dir / "phase0_params.json", phase0)
    if args.phase0_only:
        conclusion = decide([], phase0, phase2=None, elapsed=time.perf_counter() - started)
        write_json(output_dir / "conclusion.json", conclusion)
        write_json(output_dir / "metadata.json", metadata | {"elapsed_seconds": round(time.perf_counter() - started, 6), "verdict": conclusion["verdict"]})
        report_path.write_text(render_report(metadata, phase0, [], [], conclusion), encoding="utf-8")
        print(json.dumps(conclusion, ensure_ascii=False, indent=2))
        return 0 if not conclusion["verdict"].startswith("HALT") else 2

    rows = phase1_warm_start_gate(repo_root)
    write_csv(output_dir / "phase1_warm_start_gate.csv", rows)
    summary = summarize(rows)
    write_csv(output_dir / "phase1_summary.csv", summary)

    phase2_result: dict[str, Any] | None = None
    phase2_rows: list[dict[str, Any]] = []
    if args.phase2_smoke and not any(row["status"] != "OK" for row in rows):
        phase2_dir = output_dir / "phase2_smoke"
        phase2_result = run_gate(
            repo_root,
            phase2_dir,
            seeds=list(args.seeds),
            eval_budget=int(args.eval_budget),
            workers=int(args.workers),
            instance_rows=REPRESENTATIVE_ROWS,
            command_name="goeke80_multitrip_smoke",
        )
        raw_path = phase2_dir / "throughput_goeke80_multitrip_smoke_raw_runs.csv"
        if raw_path.exists():
            phase2_rows = list(csv.DictReader(raw_path.open(newline="", encoding="utf-8")))
    conclusion = decide(rows, phase0, phase2=phase2_result, elapsed=time.perf_counter() - started)
    metadata["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    metadata["verdict"] = conclusion["verdict"]
    metadata["phase2_smoke_requested"] = bool(args.phase2_smoke)
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "conclusion.json", conclusion)
    report_path.write_text(render_report(metadata, phase0, rows, summary, conclusion, phase2_result, phase2_rows), encoding="utf-8")
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))
    return 0 if not conclusion["verdict"].startswith("HALT") else 2


def build_metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "script": "baselines/e2_alns/goeke80_multitrip_rescue_gate.py",
        "command": " ".join(sys.argv),
        "repo_root": str(repo_root),
        "head": git_output(repo_root, "rev-parse", "HEAD"),
        "artifact_commit_hash": args.artifact_commit_hash or "pending",
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
    }


def phase0_audit(repo_root: Path) -> dict[str, Any]:
    tex = (repo_root / "docs/paper_submission_final/paper_main.tex").read_text(encoding="utf-8", errors="ignore")
    return {
        "Q_capacity": float(DEFAULT_PRICES.Q_capacity),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(DEFAULT_PRICES.carbon_price),
        "paper_has_q3650": "3\\,650" in tex or "3650" in tex,
        "paper_has_b80": "$B$ & 电池容量 & 80 & kWh" in tex,
        "paper_marks_280_as_diagnostic": "280 kWh情景" in tex and "不作为本轮Goeke基线默认参数" in tex,
    }


def phase1_warm_start_gate(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category, sizes in (("vanilla", VANILLA_MULTIDEPOT_SIZES), ("multidepot", VANILLA_MULTIDEPOT_SIZES), ("threeshift", THREESHIFT_SIZES)):
        for size in sizes:
            for rep in REPLICATES:
                instance = f"e2-{category}-{size}c-{rep:02d}"
                bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
                started = time.perf_counter()
                base = {"category": category, "instance": instance, "size": size, "replicate": rep, "bundle_dir": str(bundle_dir.relative_to(repo_root))}
                try:
                    bundle = load_search_bundle(bundle_dir)
                    solution = build_initial_solution(bundle.instance, bundle.carbon_profile, prices=DEFAULT_PRICES, require_charging_signal=False)
                    violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
                    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
                    row = base | composition_fields(solution) | {
                        "status": "OK" if not violations else "VIOLATION",
                        "violation_count": len(violations),
                        "violation_types": ";".join(sorted({v.type for v in violations})),
                        "total_cost": round(float(metrics["total_cost"]), 6) if not violations else math.inf,
                        "Q_capacity": float(DEFAULT_PRICES.Q_capacity),
                        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
                        "num_cv_cap": bundle.instance.num_cv,
                        "num_ev_cap": bundle.instance.num_ev,
                        "elapsed_seconds": round(time.perf_counter() - started, 6),
                    }
                except Exception as exc:  # noqa: BLE001 - preserve HALT evidence.
                    row = base | {
                        "status": "ERROR",
                        "error": repr(exc),
                        "violation_count": -1,
                        "elapsed_seconds": round(time.perf_counter() - started, 6),
                    }
                rows.append(row)
    return rows


def composition_fields(solution: Any) -> dict[str, Any]:
    cv_routes = [route for route in solution.routes if route.vehicle_type.lower() == "cv"]
    ev_routes = [route for route in solution.routes if route.vehicle_type.lower() == "ev"]
    cv_physical = {physical_vehicle_id(route.vehicle_id) for route in cv_routes}
    ev_physical = {physical_vehicle_id(route.vehicle_id) for route in ev_routes}
    trip_counts = Counter(physical_vehicle_id(route.vehicle_id) for route in solution.routes)
    route_count = len(solution.routes)
    return {
        "route_count": route_count,
        "cv_route_count": len(cv_routes),
        "ev_route_count": len(ev_routes),
        "cv_physical_vehicle_count": len(cv_physical),
        "ev_physical_vehicle_count": len(ev_physical),
        "total_physical_vehicle_count": len(cv_physical | ev_physical),
        "ev_route_share": len(ev_routes) / route_count if route_count else 0.0,
        "max_trips_per_physical_vehicle": max(trip_counts.values()) if trip_counts else 0,
        "reused_physical_vehicle_count": sum(1 for value in trip_counts.values() if value > 1),
    }


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("category")), int(row.get("size", 0)))].append(row)
    out: list[dict[str, Any]] = []
    for (category, size), items in sorted(groups.items()):
        ok = [row for row in items if row.get("status") == "OK"]
        out.append(
            {
                "category": category,
                "size": size,
                "instances": len(items),
                "ok": len(ok),
                "failures": len(items) - len(ok),
                "mean_ev_route_share": mean(float(row.get("ev_route_share", 0.0)) for row in ok),
                "mean_cv_physical": mean(float(row.get("cv_physical_vehicle_count", 0.0)) for row in ok),
                "mean_ev_physical": mean(float(row.get("ev_physical_vehicle_count", 0.0)) for row in ok),
                "mean_max_trips_per_vehicle": mean(float(row.get("max_trips_per_physical_vehicle", 0.0)) for row in ok),
            }
        )
    return out


def decide(rows: list[dict[str, Any]], phase0: dict[str, Any], *, phase2: dict[str, Any] | None, elapsed: float) -> dict[str, Any]:
    phase0_ok = (
        abs(float(phase0["Q_capacity"]) - 3650.0) <= 1e-9
        and abs(float(phase0["B_battery_kwh"]) - 80.0) <= 1e-9
        and abs(float(phase0["v_speed_ms"]) - 25.0) <= 1e-9
        and abs(float(phase0["carbon_price"]) - 0.05034) <= 1e-9
        and bool(phase0["paper_has_q3650"])
        and bool(phase0["paper_has_b80"])
    )
    if not phase0_ok:
        verdict = "HALT_PARAM_MISMATCH"
        reason = "DEFAULT_PRICES or TeX parameter table is not aligned with Goeke Q=3650, B=80, v=25, carbon=0.05034."
    elif not rows:
        verdict = "PHASE0_OK"
        reason = "Parameter audit passed; Phase 1 not requested."
    elif any(row.get("status") != "OK" for row in rows):
        verdict = "HALT_MULTITRIP_WARM_START"
        reason = "At least one E2 warm start is infeasible or failed under physical-fleet trip retagging."
    elif phase2 is None:
        verdict = "RESCUE_FEASIBILITY_READY"
        reason = "All Phase 1 E2 warm starts are zero-violation under Goeke-80 and physical-vehicle caps; algorithm smoke not yet run."
    else:
        gate = str(phase2.get("gate", ""))
        if gate.startswith("HALT"):
            verdict = "HALT_ALGORITHM_SMOKE"
            reason = f"Phase 2 algorithm smoke halted with {gate}; do not enter formal E2/T3."
        else:
            verdict = "RESCUE_SMOKE_COMPLETE"
            reason = f"Phase 2 algorithm smoke completed with {gate}; inspect paired ALNS/LNS rows before formal T3."
    return {"verdict": verdict, "reason": reason, "elapsed_seconds": round(float(elapsed), 6)}


def render_report(
    metadata: dict[str, Any],
    phase0: dict[str, Any],
    rows: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    conclusion: dict[str, Any],
    phase2: dict[str, Any] | None = None,
    phase2_rows: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        "# 09s Goeke-80 Multi-Trip Rescue Gate",
        "",
        f"Verdict: `{conclusion['verdict']}`",
        "",
        conclusion["reason"],
        "",
        "## Plain Reading",
        "",
        plain_reading(conclusion, rows, phase2),
        "",
        "## Phase 0 Parameter Audit",
        "",
        f"- Q_capacity: `{phase0['Q_capacity']}` kg",
        f"- B_battery_kwh: `{phase0['B_battery_kwh']}` kWh",
        f"- v_speed_ms: `{phase0['v_speed_ms']}`",
        f"- carbon_price: `{phase0['carbon_price']}`",
        f"- TeX table has B=80: `{phase0['paper_has_b80']}`",
        f"- 280kWh retained only as diagnostic text: `{phase0['paper_marks_280_as_diagnostic']}`",
        "",
        "## Phase 1 Warm-Start Gate",
        "",
        f"- Rows: `{len(rows)}`",
        f"- OK: `{sum(1 for row in rows if row.get('status') == 'OK')}`",
        f"- Failures: `{sum(1 for row in rows if row.get('status') != 'OK')}`",
        "",
        "| category | size | ok/instances | mean EV route share | mean CV physical | mean EV physical | mean max trips/vehicle |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['category']} | {row['size']} | {row['ok']}/{row['instances']} | "
            f"{float(row['mean_ev_route_share']):.3f} | {float(row['mean_cv_physical']):.2f} | "
            f"{float(row['mean_ev_physical']):.2f} | {float(row['mean_max_trips_per_vehicle']):.2f} |"
        )
    if phase2 is not None:
        lines.extend(
            [
                "",
                "## Phase 2 Algorithm Smoke",
                "",
                f"- Gate: `{phase2.get('gate')}`",
                f"- Rows: `{phase2.get('rows')}`",
                f"- Elapsed seconds: `{phase2.get('elapsed_seconds')}`",
            ]
        )
        if phase2_rows:
            ok = sum(1 for row in phase2_rows if row.get("gate_status") == "OK")
            lines.append(f"- OK rows: `{ok}/{len(phase2_rows)}`")
            paired = paired_wins(phase2_rows)
            lines.append(f"- Paired wins: `ALNS {paired['ALNS']} / LNS {paired['LNS']} / tie {paired['TIE']}`")
            lines.append(
                "- Interpretation: smoke confirms zero-violation comparability, but identical paired costs at this budget are not proof that ALNS beats LNS/GLNS."
            )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Data dir: `{metadata['output_dir']}`",
            f"- Report: `{metadata['report_path']}`",
            f"- HEAD: `{metadata['head']}`",
            f"- Artifact commit hash: `{metadata['artifact_commit_hash']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def plain_reading(conclusion: dict[str, Any], rows: list[dict[str, Any]], phase2: dict[str, Any] | None) -> str:
    verdict = conclusion["verdict"]
    if verdict == "RESCUE_FEASIBILITY_READY":
        max_trip = max(float(row.get("max_trips_per_physical_vehicle", 0.0)) for row in rows)
        return (
            "大白话：参数和代码语义已经先对齐到了 Goeke 基线。69 个 E2 warm start 在“实体车辆可多趟”的硬上限解释下都可行，"
            f"最大单车趟次数为 {max_trip:.0f}。这只说明卡点从“代码把 route 当车”解除，不说明 ALNS 已经赢。"
        )
    if verdict == "RESCUE_SMOKE_COMPLETE":
        return "大白话：轻量算法 smoke 已经跑完，但还不能代替正式 E2/T3；下一步要看 ALNS/LNS 配对表是否真的有改善。"
    if verdict.startswith("HALT"):
        return "大白话：这一步没有过门。不要拿旧结论或半截结果救故事，先看失败行修语义或数据。"
    return "大白话：只完成了参数审计，后续可行性和算法对比还没有证据。"


def paired_wins(rows: list[dict[str, Any]]) -> dict[str, int]:
    by_instance: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_instance[str(row.get("instance", ""))][str(row.get("algorithm", ""))] = row
    wins = {"ALNS": 0, "LNS": 0, "TIE": 0}
    for paired in by_instance.values():
        alns = paired.get("alns_e2_throughput")
        lns = paired.get("LNS")
        if alns is None or lns is None:
            continue
        try:
            alns_cost = float(alns.get("best_cost", math.inf))
            lns_cost = float(lns.get("best_cost", math.inf))
        except (TypeError, ValueError):
            continue
        if alns_cost < lns_cost - 1e-9:
            wins["ALNS"] += 1
        elif lns_cost < alns_cost - 1e-9:
            wins["LNS"] += 1
        else:
            wins["TIE"] += 1
    return wins


def expected_instance_count() -> int:
    return 2 * len(VANILLA_MULTIDEPOT_SIZES) * len(REPLICATES) + len(THREESHIFT_SIZES) * len(REPLICATES)


def mean(values: Any) -> float:
    data = list(values)
    return sum(data) / len(data) if data else 0.0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def git_output(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
