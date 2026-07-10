"""Exact fixed-route fleet-composition map for the current M1 diagnosis.

For each saved scheduler solution with at most 12 routes, this diagnostic keeps
the depot and customer order fixed and enumerates every CV/EV assignment.  EV
routes go through the existing charging repair; every complete assignment goes
through the unchanged checker and evaluator.  The result answers whether a
mixed fleet is economically present on those routes before blaming search.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.algorithms.resetp_alns.support.charging import repair_route_charging
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits, normalize_solution_vehicle_trips
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.solution import CrossSiteService, Route, Solution


DEFAULT_INSTANCE = "L-main-threeshift-25c-01"
DEFAULT_SCHEDULER_DIR = Path("baselines/e2_alns/m1_scheduler_realization_20260710")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_fleet_opportunity_20260710")


def classify_composition(rows: Iterable[dict[str, Any]]) -> str:
    items = list(rows)
    if not items:
        return "FIXED_ROUTES_NO_FEASIBLE_ASSIGNMENT"
    labels = set()
    for row in items:
        routes = int(row["route_count"])
        ev = int(row["best_ev_routes"])
        labels.add("ALL_CV" if ev == 0 else "ALL_EV" if ev == routes else "MIXED")
    if len(labels) > 1:
        return "FIXED_ROUTES_ROUTING_DEPENDENT"
    label = next(iter(labels))
    return f"FIXED_ROUTES_{label}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_value(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _load_solution(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(node) for node in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        cross_site_services=[
            CrossSiteService(str(row["customer_id"]), str(row["served_by_depot_id"]))
            for row in payload.get("cross_site_services", [])
        ],
    )


def _best_sources(rows: list[dict[str, str]], profiles: set[str]) -> list[dict[str, str]]:
    selected: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if row.get("profile") not in profiles:
            continue
        key = (str(row["profile"]), str(row["start"]))
        if key not in selected or float(row["best_cost"]) < float(selected[key]["best_cost"]):
            selected[key] = row
    return [selected[key] for key in sorted(selected)]


def _customer_route(route: Route, instance: Any, index: int, vehicle_type: str) -> Route:
    node_lookup = {node.node_id: node for node in instance.nodes}
    customers = [
        node_id
        for node_id in route.node_sequence
        if node_id in node_lookup and node_lookup[node_id].node_type.lower() == "c"
    ]
    prefix = "EV_ENUM" if vehicle_type == "ev" else "CV_ENUM"
    return Route(
        vehicle_id=f"{prefix}_{index + 1}",
        vehicle_type=vehicle_type,
        home_depot_id=route.home_depot_id,
        node_sequence=[route.home_depot_id, *customers, route.home_depot_id],
    )


def _assignment(
    source: Solution,
    mask: int,
    bundle: Any,
    prices: Any,
) -> tuple[Solution | None, str]:
    routes: list[Route] = []
    actions = []
    for index, source_route in enumerate(source.routes):
        vehicle_type = "ev" if mask & (1 << index) else "cv"
        route = _customer_route(source_route, bundle.instance, index, vehicle_type)
        if vehicle_type == "ev":
            try:
                route, route_actions = repair_route_charging(
                    route,
                    bundle.instance,
                    bundle.carbon_profile,
                    prices,
                )
            except ValueError as exc:
                return None, f"charging_repair:{exc}"
            actions.extend(route_actions)
        routes.append(route)
    limits = infer_fleet_limits(bundle.bundle_dir)
    try:
        candidate = normalize_solution_vehicle_trips(
            Solution(
                routes=routes,
                charging_actions=actions,
                cross_site_services=list(source.cross_site_services),
            ),
            bundle.instance,
            max_cv=limits.cv,
            max_ev=limits.ev,
        )
    except ValueError as exc:
        return None, f"fleet_normalization:{exc}"
    violations = check_solution(candidate, bundle.instance, prices)
    if violations:
        return None, ";".join(f"{item.type}:{item.detail}" for item in violations[:3])
    return candidate, ""


def _enumerate_source(
    source_row: dict[str, str],
    source_solution: Solution,
    bundle: Any,
    battery_kwh: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    route_count = len(source_solution.routes)
    if route_count > 12:
        raise RuntimeError(f"fixed-route exact enumeration limited to 12 routes, got {route_count}")
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(battery_kwh))
    rows: list[dict[str, Any]] = []
    for mask in range(1 << route_count):
        candidate, reason = _assignment(source_solution, mask, bundle, prices)
        base = {
            "source_profile": source_row["profile"],
            "source_start": source_row["start"],
            "source_seed": int(source_row["seed"]),
            "source_solution_path": source_row["best_solution_path"],
            "battery_kwh": float(battery_kwh),
            "route_count": route_count,
            "mask": format(mask, f"0{route_count}b"),
            "ev_routes": mask.bit_count(),
        }
        if candidate is None:
            rows.append({**base, "feasible": False, "total_cost": "N/A", "E_total": "N/A", "failure_reason": reason})
            continue
        metrics = evaluate(candidate, bundle.instance, bundle.carbon_profile, prices)
        rows.append(
            {
                **base,
                "feasible": True,
                "total_cost": float(metrics["total_cost"]),
                "E_total": float(metrics["E_total"]),
                "cost_fix": float(metrics["cost_fix"]),
                "cost_fuel": float(metrics["cost_fuel"]),
                "cost_elec": float(metrics["cost_elec"]),
                "failure_reason": "",
            }
        )
    feasible = [row for row in rows if row["feasible"]]
    if not feasible:
        return rows, {
            "source_profile": source_row["profile"],
            "source_start": source_row["start"],
            "source_seed": int(source_row["seed"]),
            "battery_kwh": float(battery_kwh),
            "route_count": route_count,
            "feasible_assignment_count": 0,
            "best_cost": "N/A",
            "best_ev_routes": "N/A",
            "composition": "NO_FEASIBLE_ASSIGNMENT",
        }
    best = min(feasible, key=lambda row: (float(row["total_cost"]), int(row["ev_routes"]), str(row["mask"])))
    all_cv = next((row for row in feasible if int(row["ev_routes"]) == 0), None)
    all_ev = next((row for row in feasible if int(row["ev_routes"]) == route_count), None)
    mixed = [row for row in feasible if 0 < int(row["ev_routes"]) < route_count]
    best_mixed = min(mixed, key=lambda row: float(row["total_cost"])) if mixed else None
    best_ev_routes = int(best["ev_routes"])
    return rows, {
        "source_profile": source_row["profile"],
        "source_start": source_row["start"],
        "source_seed": int(source_row["seed"]),
        "source_solution_path": source_row["best_solution_path"],
        "battery_kwh": float(battery_kwh),
        "route_count": route_count,
        "feasible_assignment_count": len(feasible),
        "best_cost": float(best["total_cost"]),
        "best_E_total": float(best["E_total"]),
        "best_ev_routes": best_ev_routes,
        "best_mask": best["mask"],
        "composition": "ALL_CV" if best_ev_routes == 0 else "ALL_EV" if best_ev_routes == route_count else "MIXED",
        "all_cv_cost": float(all_cv["total_cost"]) if all_cv else "N/A",
        "all_ev_cost": float(all_ev["total_cost"]) if all_ev else "N/A",
        "best_mixed_cost": float(best_mixed["total_cost"]) if best_mixed else "N/A",
        "mixed_gap_pct": (
            (float(best_mixed["total_cost"]) - float(best["total_cost"])) / max(1e-9, float(best["total_cost"])) * 100.0
            if best_mixed
            else "N/A"
        ),
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    manifest = assert_formal_benchmark_ready(repo_root)
    bundle = load_search_bundle(instance_abs_dir(repo_root, args.instance))
    scheduler_dir = repo_root / args.scheduler_dir
    scheduler_rows = _read_csv(scheduler_dir / "raw_runs.csv")
    profiles = {item.strip() for item in str(args.profiles).split(",") if item.strip()}
    source_rows = _best_sources(scheduler_rows, profiles)
    if not source_rows:
        raise RuntimeError("no scheduler solution rows matched the requested profiles")
    batteries = [float(item) for item in str(args.batteries).split(",") if item.strip()]

    raw_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    input_paths: list[Path] = []
    for source_row in source_rows:
        source_path = repo_root / source_row["best_solution_path"]
        input_paths.append(source_path)
        source_solution = _load_solution(source_path)
        for battery in batteries:
            rows, summary = _enumerate_source(source_row, source_solution, bundle, battery)
            raw_rows.extend(rows)
            summary_rows.append(summary)

    per_battery = {
        str(battery): classify_composition(
            row for row in summary_rows if float(row["battery_kwh"]) == battery and row["best_ev_routes"] != "N/A"
        )
        for battery in batteries
    }
    target_verdict = per_battery.get(str(float(args.target_battery_kwh)), "TARGET_BATTERY_NOT_RUN")
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "raw_runs.csv", raw_rows)
    _write_csv(output_dir / "summary.csv", summary_rows)

    manifest_path = repo_root / "models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json"
    metadata = {
        "schema_version": "setp-m1-fleet-opportunity-map.v1",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "fixed_routes": True,
        "exact_enumeration": True,
        "repo_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "repo_dirty_at_run": bool(_git_value(repo_root, "status", "--porcelain")),
        "instance": args.instance,
        "actual_customer_count": sum(1 for node in bundle.instance.nodes if node.node_type.lower() == "c"),
        "batteries_kwh": batteries,
        "profiles": sorted(profiles),
        "source_solution_sha256": {str(path.relative_to(repo_root)): _sha256(path) for path in sorted(set(input_paths))},
        "formal_manifest_schema": manifest.get("schema_version"),
        "formal_manifest_sha256": _sha256(manifest_path),
    }
    decision = {
        "schema_version": "setp-m1-fleet-opportunity-decision.v1",
        "verdict": target_verdict,
        "target_battery_kwh": float(args.target_battery_kwh),
        "per_battery_verdict": per_battery,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "meaning": "This verdict is exact only for the saved route orders; it separates fixed-route fleet economics from route-search ability.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = [
        "# M1 fixed-route fleet opportunity map",
        "",
        f"Target verdict: `{target_verdict}` at `{args.target_battery_kwh}` kWh.",
        "",
        "Every CV/EV assignment was enumerated while keeping each saved depot/customer order fixed. "
        "EV routes used the existing charging repair; every complete solution used the unchanged checker and evaluator.",
        "",
    ]
    for row in summary_rows:
        report.append(
            f"- {row['battery_kwh']} kWh / {row['source_profile']} / {row['source_start']} / seed {row['source_seed']}: "
            f"best {row['best_cost']}, EV routes {row['best_ev_routes']}/{row['route_count']}, {row['composition']}, "
            f"best mixed gap {row['mixed_gap_pct']}%."
        )
    report.extend(
        [
            "",
            "Boundary: a fixed-route all-EV or all-CV result means a mixed target is absent on that route order. "
            "It does not prove that every possible routing has the same composition. Routing-dependent results mean search and fleet composition must be diagnosed together.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")

    targets = [
        Path(__file__).resolve(),
        manifest_path,
        *sorted(set(input_paths)),
        output_dir / "raw_runs.csv",
        output_dir / "summary.csv",
        output_dir / "metadata.json",
        output_dir / "decision.json",
        output_dir / "report.md",
    ]
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps({str(path.relative_to(repo_root)): _sha256(path) for path in targets}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"verdict": target_verdict, "per_battery": per_battery, "raw_rows": len(raw_rows), "summary_rows": len(summary_rows)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--scheduler-dir", default=DEFAULT_SCHEDULER_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profiles", default="DEFAULT_ALPHA_UCB,BALANCED_COVERAGE,MINIMUM_COVERAGE")
    parser.add_argument("--batteries", default="80,280")
    parser.add_argument("--target-battery-kwh", type=float, default=280.0)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_probe(parse_args()), indent=2, sort_keys=True))
