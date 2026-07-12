#!/usr/bin/env python3
"""Two 200-evaluation wiring checks before any formal E3 run."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    sys.path.insert(0, str(path))

from baselines.e2_alns import e2_final_closure as closure
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_staged_alns_lns_hybrid
from setp_solver.instance_loader import Instance
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.multitrip_schedule import build_multitrip_certificate, strict_multitrip_violations
from setp_solver.solution import Route, Solution


DEFAULT_OUT = ROOT / "baselines/e3_ablation/e3_multitrip_search_gate_20260712"
STRUCTURE = ROOT / "baselines/e3_ablation/e3_multitrip_structure_gate_20260712"
INSTANCE = "L-main-threeshift-200c-01"


@contextmanager
def _strict_mode():
    old = os.environ.get("SETP_E3_STRICT_MULTITRIP")
    os.environ["SETP_E3_STRICT_MULTITRIP"] = "1"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("SETP_E3_STRICT_MULTITRIP", None)
        else:
            os.environ["SETP_E3_STRICT_MULTITRIP"] = old


def _read_routes(name: str) -> list[Route]:
    data = json.loads((STRUCTURE / name).read_text(encoding="utf-8"))
    return [Route(**row) for row in data["routes"]]


def _subinstance(instance: Instance, depot_id: str, routes: list[Route], cv: int, ev: int) -> Instance:
    customer_ids = {node_id for route in routes for node_id in route.node_sequence[1:-1]}
    keep = customer_ids | {depot_id}
    nodes = [node for node in instance.nodes if node.node_id in keep]
    indices = [instance.node_index[node.node_id] for node in nodes]
    matrix = np.asarray(instance.distance_matrix)[np.ix_(indices, indices)].tolist()
    return Instance(nodes, matrix, num_cv=cv, num_ev=ev)


def _write_bundle(path: Path, instance: Instance, source: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "nodes": [asdict(node) for node in instance.nodes],
        "metadata": {"num_cv": instance.num_cv, "num_ev": instance.num_ev, "strict_multitrip": True},
    }
    (path / "instance.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    np.save(path / "distance_matrix.npy", np.asarray(instance.distance_matrix))
    shutil.copyfile(source / "carbon_profile.csv", path / "carbon_profile.csv")
    (path / "scenario_manifest.json").write_text(json.dumps({"source": str(source), "gate_only": True}, indent=2), encoding="utf-8")


def _run(bundle_dir: Path, initial: Solution, *, budget: int, seed: int) -> dict[str, object]:
    bundle = load_search_bundle(bundle_dir)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=280.0, carbon_price=0.0)
    started = time.perf_counter()
    cost_context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices, carbon_weight=0.0)
    initial_cost = model_cost(initial, cost_context)
    with _strict_mode():
        result = run_staged_alns_lns_hybrid(
            bundle_dir,
            config=WinnerKernelConfig(seed=seed, eval_budget=budget, max_runtime_seconds=max(300.0, budget * 0.3), require_charging_signal=False),
            initial_solution=initial,
            prices=prices,
            policy=SearchPolicy(require_charging_signal=False, max_cv=int(bundle.instance.num_cv), max_ev=int(bundle.instance.num_ev)),
            carbon_weight=0.0,
        )
    strict = strict_multitrip_violations(result["best_solution"].routes, bundle.instance, prices)
    return {
        "result": result,
        "strict_violations": strict,
        "wall_seconds": time.perf_counter() - started,
        "initial_cost": initial_cost,
        "best_cost": model_cost(result["best_solution"], cost_context),
        "status": "PASS" if result["feasible"] and int(result["evaluations"]) == budget and not strict else "HALT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=200)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    total_budget = int(args.budget)
    if total_budget < 2 or total_budget % 2:
        raise ValueError("budget must be an even integer of at least 2")
    global OUT
    OUT = Path(args.output_dir).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    source = closure._resolve_bundle_dir("threeshift", INSTANCE)
    full = load_search_bundle(source)
    solo_routes = _read_routes("solo_business_certificate.json")
    shared_routes = _read_routes("shared_business_certificate.json")
    rows: list[dict[str, object]] = []

    solo_best: list[Route] = []
    solo_evals = 0
    solo_wall = 0.0
    solo_initial_cost = 0.0
    solo_best_cost = 0.0
    solo_ok = True
    for index, depot_id in enumerate(sorted({route.home_depot_id for route in solo_routes})):
        routes = [route for route in solo_routes if route.home_depot_id == depot_id]
        cert = build_multitrip_certificate(routes, full.instance, replace(DEFAULT_PRICES, B_battery_kwh=280.0))
        cv, ev = cert.vehicle_counts["cv"], cert.vehicle_counts["ev"]
        instance = _subinstance(full.instance, depot_id, routes, cv, ev)
        subdir = OUT / "bundles" / f"solo_{depot_id}"
        _write_bundle(subdir, instance, source)
        outcome = _run(subdir, Solution(routes=routes), budget=total_budget // 2, seed=1 + index)
        result = outcome["result"]
        solo_best.extend(result["best_solution"].routes)
        solo_evals += int(result["evaluations"])
        solo_wall += float(outcome["wall_seconds"])
        solo_initial_cost += float(outcome["initial_cost"])
        solo_best_cost += float(outcome["best_cost"])
        solo_ok = solo_ok and outcome["status"] == "PASS"
    merged_strict = strict_multitrip_violations(
        solo_best, full.instance, replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=280.0)
    )
    solo_ok = solo_ok and not merged_strict
    rows.append({"case": "solo_business", "status": "PASS" if solo_ok else "HALT", "evaluations": solo_evals, "wall_seconds": solo_wall, "strict_violation_count": len(merged_strict), "initial_cost": solo_initial_cost, "best_cost": solo_best_cost, "improvement_percent": 100.0 * (solo_initial_cost - solo_best_cost) / solo_initial_cost})

    shared = _run(source, Solution(routes=shared_routes), budget=total_budget, seed=1)
    shared_result = shared["result"]
    rows.append({"case": "shared_business", "status": shared["status"], "evaluations": shared_result["evaluations"], "wall_seconds": shared["wall_seconds"], "strict_violation_count": len(shared["strict_violations"]), "initial_cost": shared["initial_cost"], "best_cost": shared["best_cost"], "improvement_percent": 100.0 * (float(shared["initial_cost"]) - float(shared["best_cost"])) / float(shared["initial_cost"])})

    for label, routes in (("solo_business", solo_best), ("shared_business", shared_result["best_solution"].routes)):
        (OUT / f"{label}_best_routes.json").write_text(json.dumps([asdict(route) for route in routes], ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    passed = all(row["status"] == "PASS" for row in rows)
    metadata = {"schema": "setp-e3-multitrip-search-gate.v1", "budget": total_budget, "formal_70_started": False, "model_changed": False, "source_structure_gate": str(STRUCTURE.relative_to(ROOT))}
    decision = {"verdict": "SEARCH_WIRING_PASS" if passed else "HALT_SEARCH_WIRING", "normal_budget_gate_authorized": passed, "formal_70_authorized": False, "rows": rows}
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text("# E3 strict scheduling search wiring gate\n\n" + ("PASS" if passed else "HALT") + ". The formal 70-run batch was not started.\n", encoding="utf-8")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(OUT.iterdir()) if path.is_file() and not path.name.startswith("._") and path.name != "artifact_hashes.json"}
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
