"""Diagnostic-only route-packing reachability audit for E2 ALNS residual gap.

This script reads existing A7/LNS evidence and asks a narrow question:
can fixed-cost-aware order decoding reproduce LNS-like low route-count
structures from already-seen customer orders?  It does not run search and does
not implement A13/A14/hybrid follow-up work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import solution_signature_hash
from setp_solver.search.order_decoder import (
    OrderDecodeContext,
    complete_order,
    order_to_solution,
    route_type_hints,
    solution_order,
)
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

from baselines.e2_alns import e2_final_closure as fc

try:  # Diagnostic-only reuse of the baseline construction order.
    from setp_solver.search.metaheuristic_baselines import _angle_scan_order
except ImportError:  # pragma: no cover - defensive fallback for import drift.
    _angle_scan_order = None


SELECTOR_SPRINT_DIR = REPO_ROOT / "baselines/e2_alns/selector_sprint_probe_20260706"
GLOBAL_REPACK_DIR = REPO_ROOT / "baselines/e2_alns/global_repack_fleet_charge_probe_20260707"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/route_packing_reachability_audit_20260708"
INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark"

BASE_PROFILE = "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH"
LNS_PROFILE = "LNS_REFERENCE"
A11_PROFILE = "A11_GLOBAL_ORDER_REPACK"
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=16000)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(args.budget)
    fc.write_json(output_dir / "metadata.json", metadata)

    issues = preflight_issues(args.budget)
    if issues:
        decision = build_decision(metadata, issues, [])
        write_outputs(output_dir, metadata, [], [], decision)
        return 2

    delta_rows, decoder_rows = run_audit(args.budget)
    decision = build_decision(metadata, [], decoder_rows)
    write_outputs(output_dir, metadata, delta_rows, decoder_rows, decision)
    return 0 if decision["verdict"] == "ROUTE_PACKING_REACHABILITY_SUPPORTED" else 2


def build_metadata(budget: int) -> dict[str, Any]:
    return {
        "schema": "setp-e2-route-packing-reachability-metadata.v1",
        "budget": int(budget),
        "head": git_head(),
        "selector_sprint_dir": fc.rel(SELECTOR_SPRINT_DIR),
        "global_repack_dir": fc.rel(GLOBAL_REPACK_DIR),
        "profiles": [BASE_PROFILE, LNS_PROFILE],
        "a11_context_profile": A11_PROFILE,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
    }


def preflight_issues(budget: int) -> list[str]:
    issues: list[str] = []
    selector_raw = SELECTOR_SPRINT_DIR / "raw_runs.csv"
    if not selector_raw.exists():
        issues.append(f"MISSING:{fc.rel(selector_raw)}")
    if not any(row.get("budget") == str(int(budget)) for row in fc.read_csv(selector_raw)):
        issues.append(f"MISSING_BUDGET:{budget}")
    global_decision = GLOBAL_REPACK_DIR / "decision.json"
    if not global_decision.exists():
        issues.append(f"MISSING:{fc.rel(global_decision)}")
    else:
        verdict = str(fc.read_json(global_decision).get("verdict", ""))
        if verdict != "GLOBAL_REPACK_FLEET_CHARGE_4000_ONLY":
            issues.append(f"UNEXPECTED_A11_A12_VERDICT:{verdict}")
    issues.extend([f"PROTECTED_DIFF:{path}" for path in fc.protected_diff()])
    return issues


def run_audit(budget: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selector_rows = rows_by_key(fc.read_csv(SELECTOR_SPRINT_DIR / "raw_runs.csv"), budget=budget)
    a11_rows = rows_by_key(fc.read_csv(GLOBAL_REPACK_DIR / "raw_runs.csv"), budget=8000)
    delta_rows: list[dict[str, Any]] = []
    decoder_rows: list[dict[str, Any]] = []
    for key, profiles in sorted(selector_rows.items()):
        if BASE_PROFILE not in profiles or LNS_PROFILE not in profiles:
            continue
        a7_row = profiles[BASE_PROFILE]
        lns_row = profiles[LNS_PROFILE]
        if not ok_row(a7_row) or not ok_row(lns_row):
            continue
        a7_cost = as_float(a7_row.get("best_cost"))
        lns_cost = as_float(lns_row.get("best_cost"))
        if not (math.isfinite(a7_cost) and math.isfinite(lns_cost)):
            continue
        if a7_cost <= lns_cost + 1e-9:
            continue
        category, instance, seed = key
        bundle = load_search_bundle(INSTANCE_ROOT / category / instance)
        a7_solution = solution_for_row(a7_row)
        lns_solution = solution_for_row(lns_row)
        a11_solution = None
        if key in a11_rows and A11_PROFILE in a11_rows[key] and ok_row(a11_rows[key][A11_PROFILE]):
            a11_solution = solution_for_row(a11_rows[key][A11_PROFILE])
        delta_rows.append(structure_delta_row(category, instance, seed, a7_row, lns_row, a7_solution, lns_solution))
        decoder_rows.extend(decode_rows_for_pair(category, instance, seed, bundle, a7_row, lns_row, a7_solution, lns_solution, a11_solution))
    annotate_best_reachability(decoder_rows)
    return delta_rows, decoder_rows


def rows_by_key(rows: list[dict[str, str]], *, budget: int) -> dict[tuple[str, str, int], dict[str, dict[str, str]]]:
    grouped: dict[tuple[str, str, int], dict[str, dict[str, str]]] = {}
    for row in rows:
        if str(row.get("budget")) != str(int(budget)):
            continue
        key = (str(row.get("category")), str(row.get("instance")), as_int(row.get("seed")))
        grouped.setdefault(key, {})[str(row.get("profile"))] = row
    return grouped


def structure_delta_row(
    category: str,
    instance: str,
    seed: int,
    a7_row: dict[str, Any],
    lns_row: dict[str, Any],
    a7_solution: Solution,
    lns_solution: Solution,
) -> dict[str, Any]:
    return {
        "category": category,
        "instance": instance,
        "seed": int(seed),
        "a7_cost": as_float(a7_row.get("best_cost")),
        "lns_cost": as_float(lns_row.get("best_cost")),
        "a7_route_count": len(a7_solution.routes),
        "lns_route_count": len(lns_solution.routes),
        "route_count_delta": len(a7_solution.routes) - len(lns_solution.routes),
        "a7_cost_fix": as_float(a7_row.get("cost_fix")),
        "lns_cost_fix": as_float(lns_row.get("cost_fix")),
        "cost_fix_delta": as_float(a7_row.get("cost_fix")) - as_float(lns_row.get("cost_fix")),
        "a7_cv_route_count": route_type_count(a7_solution, "cv"),
        "lns_cv_route_count": route_type_count(lns_solution, "cv"),
        "a7_ev_route_count": route_type_count(a7_solution, "ev"),
        "lns_ev_route_count": route_type_count(lns_solution, "ev"),
        "charging_action_delta": len(a7_solution.charging_actions) - len(lns_solution.charging_actions),
        "customer_order_similarity": order_similarity(solution_order(a7_solution, load_search_bundle(INSTANCE_ROOT / category / instance).instance), solution_order(lns_solution, load_search_bundle(INSTANCE_ROOT / category / instance).instance)),
        "loss_bucket": loss_bucket(a7_row, lns_row),
    }


def decode_rows_for_pair(
    category: str,
    instance: str,
    seed: int,
    bundle: Any,
    a7_row: dict[str, Any],
    lns_row: dict[str, Any],
    a7_solution: Solution,
    lns_solution: Solution,
    a11_solution: Solution | None,
) -> list[dict[str, Any]]:
    context = OrderDecodeContext(bundle.instance, DEFAULT_PRICES, bundle.carbon_profile)
    candidates: list[tuple[str, list[str], dict[str, float] | None, Solution | None]] = [
        ("decode_a7_order", solution_order(a7_solution, bundle.instance), route_type_hints(a7_solution, bundle.instance), a7_solution),
        ("decode_lns_order", solution_order(lns_solution, bundle.instance), route_type_hints(lns_solution, bundle.instance), lns_solution),
        ("decode_mixed_route_blocks", mixed_route_block_order(a7_solution, lns_solution, bundle.instance, context), route_type_hints(lns_solution, bundle.instance), lns_solution),
        ("decode_angle_scan_order", angle_scan_order(bundle.instance, context), None, None),
    ]
    if a11_solution is not None:
        candidates.append(("decode_a11_8000_order", solution_order(a11_solution, bundle.instance), route_type_hints(a11_solution, bundle.instance), a11_solution))

    rows: list[dict[str, Any]] = []
    for label, order, hints, current_solution in candidates:
        decoded = order_to_solution(order, context, current_solution=current_solution, type_hints=hints)
        rows.append(decoder_result_row(category, instance, seed, label, decoded, bundle, a7_row, lns_row))
    return rows


def decoder_result_row(
    category: str,
    instance: str,
    seed: int,
    decoder: str,
    solution: Solution,
    bundle: Any,
    a7_row: dict[str, Any],
    lns_row: dict[str, Any],
) -> dict[str, Any]:
    violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES) if not violations else {}
    route_count = len(solution.routes)
    lns_route_count = as_int(lns_row.get("route_count"))
    a7_route_count = as_int(a7_row.get("route_count"))
    route_delta_before = a7_route_count - lns_route_count
    route_delta_after = route_count - lns_route_count
    route_count_match_lns = route_count <= lns_route_count
    route_delta_half_reduced = route_delta_before > 0 and route_delta_after <= route_delta_before / 2.0
    total_cost = as_float(metrics.get("total_cost"))
    a7_cost = as_float(a7_row.get("best_cost"))
    no_blowup = math.isfinite(total_cost) and total_cost <= a7_cost * 1.02
    reachable = (route_count_match_lns or route_delta_half_reduced) and not violations
    return {
        "category": category,
        "instance": instance,
        "seed": int(seed),
        "decoder": decoder,
        "feasible": not bool(violations),
        "violation_count": len(violations),
        "violation_sample": "; ".join(str(item) for item in violations[:3]),
        "route_count": route_count,
        "lns_route_count": lns_route_count,
        "a7_route_count": a7_route_count,
        "route_count_delta_vs_lns": route_delta_after,
        "route_delta_before": route_delta_before,
        "route_count_match_lns": route_count_match_lns,
        "route_delta_half_reduced": route_delta_half_reduced,
        "cost_fix": as_float(metrics.get("cost_fix")),
        "lns_cost_fix": as_float(lns_row.get("cost_fix")),
        "a7_cost_fix": as_float(a7_row.get("cost_fix")),
        "total_cost": total_cost,
        "lns_cost": as_float(lns_row.get("best_cost")),
        "a7_cost": a7_cost,
        "gap_vs_lns": safe_gap(total_cost, as_float(lns_row.get("best_cost"))),
        "gap_vs_a7": safe_gap(total_cost, a7_cost),
        "no_material_total_cost_blowup": no_blowup,
        "reachable_structure": reachable,
        "best_reachable": False,
        "best_no_blowup": False,
        "solution_signature": solution_signature_hash(solution),
    }


def annotate_best_reachability(rows: list[dict[str, Any]]) -> None:
    by_key: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault((str(row["category"]), str(row["instance"]), int(row["seed"])), []).append(row)
    for candidates in by_key.values():
        valid = [row for row in candidates if truthy(row.get("reachable_structure")) and truthy(row.get("no_material_total_cost_blowup"))]
        if not valid:
            continue
        best = min(valid, key=lambda row: (as_float(row.get("total_cost")), as_int(row.get("route_count"))))
        best["best_reachable"] = True
        best["best_no_blowup"] = True


def build_decision(metadata: dict[str, Any], issues: list[str], decoder_rows: list[dict[str, Any]]) -> dict[str, Any]:
    losing_keys = {decision_key(row, idx) for idx, row in enumerate(decoder_rows)}
    losing_rows = len(losing_keys)
    reachable_keys = {
        decision_key(row, idx)
        for idx, row in enumerate(decoder_rows)
        if truthy(row.get("best_reachable")) and truthy(row.get("best_no_blowup"))
    }
    reachable_rows = len(reachable_keys)
    reachable_fraction = reachable_rows / losing_rows if losing_rows else 0.0
    halt = bool(issues)
    if halt:
        verdict = "HALT_ROUTE_PACKING_REACHABILITY_PREFLIGHT"
    elif losing_rows == 0:
        verdict = "HALT_ROUTE_PACKING_REACHABILITY_NO_LOSING_ROWS"
        halt = True
    elif reachable_fraction >= 0.60:
        verdict = "ROUTE_PACKING_REACHABILITY_SUPPORTED"
    else:
        verdict = "ROUTE_PACKING_REACHABILITY_NOT_SUPPORTED"
    return {
        "schema": "setp-e2-route-packing-reachability-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "halt": halt,
        "issues": issues,
        "losing_rows": losing_rows,
        "reachable_rows": reachable_rows,
        "reachable_fraction": reachable_fraction,
        "pass_gate": verdict == "ROUTE_PACKING_REACHABILITY_SUPPORTED",
        "required_fraction": 0.60,
        "no_blowup_rule": "decoded_total_cost <= A7_best_cost * 1.02",
        "next_stage_allowed": "A13_LNS_POLICY_KERNEL" if verdict == "ROUTE_PACKING_REACHABILITY_SUPPORTED" else "",
    }


def decision_key(row: dict[str, Any], idx: int) -> tuple[str, str, int]:
    if row.get("category") is None or row.get("instance") is None or row.get("seed") is None:
        return ("synthetic", f"row-{idx}", idx)
    return (str(row.get("category")), str(row.get("instance")), as_int(row.get("seed"), idx))


def write_outputs(
    output_dir: Path,
    metadata: dict[str, Any],
    delta_rows: list[dict[str, Any]],
    decoder_rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> None:
    fc.write_json(output_dir / "metadata.json", metadata)
    fc.write_csv(output_dir / "lns_vs_a7_structure_delta.csv", delta_rows)
    fc.write_csv(output_dir / "decoder_reachability.csv", decoder_rows)
    fc.write_json(output_dir / "decision.json", decision)
    write_failure_modes(output_dir / "packing_failure_modes.md", decoder_rows, decision)
    write_diagnosis(output_dir / "diagnosis.md", decision)
    write_next_action(output_dir / "next_action.md", decision)
    if decision["verdict"] != "ROUTE_PACKING_REACHABILITY_SUPPORTED":
        write_stop_or_redefine(output_dir / "STOP_OR_REDEFINE.md", decision)
    write_hashes(output_dir)


def write_failure_modes(path: Path, rows: list[dict[str, Any]], decision: dict[str, Any]) -> None:
    infeasible = sum(1 for row in rows if not truthy(row.get("feasible")))
    reachable = sum(1 for row in rows if truthy(row.get("reachable_structure")))
    no_blowup = sum(1 for row in rows if truthy(row.get("no_material_total_cost_blowup")))
    lines = [
        "# Packing Failure Modes",
        "",
        "This is diagnostic-only evidence. It does not modify solver semantics or prove algorithm victory.",
        "",
        f"- verdict: `{decision.get('verdict')}`",
        f"- decoded candidates: {len(rows)}",
        f"- infeasible decoded candidates: {infeasible}",
        f"- reachable-structure candidates: {reachable}",
        f"- no-material-blowup candidates: {no_blowup}",
        "",
        "Main failure labels are available in `decoder_reachability.csv` via `violation_sample`, `route_count_match_lns`, `route_delta_half_reduced`, and `no_material_total_cost_blowup`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_diagnosis(path: Path, decision: dict[str, Any]) -> None:
    lines = [
        "# Route Packing Reachability Diagnosis",
        "",
        f"verdict -> `{decision.get('verdict')}`",
        f"losing_rows -> {decision.get('losing_rows')}",
        f"reachable_fraction -> {decision.get('reachable_fraction')}",
        "",
        "Boundary: this audit only checks whether LNS-like route-count structures are reachable through fixed-cost-aware order decoding. It does not implement A13/A14/hybrid.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_next_action(path: Path, decision: dict[str, Any]) -> None:
    if decision["verdict"] == "ROUTE_PACKING_REACHABILITY_SUPPORTED":
        remedy = "implement A13 LNS policy parity kernel; do not implement A14 until A13 parity passes"
    else:
        remedy = "stop A13/A14/hybrid implementation and decide whether to redefine the main algorithm or accept LNS first-tier reality"
    lines = [
        "# Next Action",
        "",
        "problem_symptom -> 16000 hard-subset A7 residual losses vs LNS",
        f"evidence -> decision `{decision.get('verdict')}` in decision.json",
        f"minimal_remedy -> {remedy}",
        "pass_gate -> reachability_fraction >= 0.60 with feasible decoded solutions and no material total-cost blowup",
        "fail_gate -> preflight issue, no losing rows, reachability_fraction < 0.60, protected diff, infeasible-only decoded candidates",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_stop_or_redefine(path: Path, decision: dict[str, Any]) -> None:
    lines = [
        "# STOP_OR_REDEFINE",
        "",
        f"verdict -> `{decision.get('verdict')}`",
        "",
        "The reachability gate did not authorize A13/A14/hybrid implementation. Do not continue winner-ALNS patching or implement the later stages from the plan in this run.",
        "",
        "Allowed next decisions:",
        "",
        "1. Accept LNS as the current first-tier method and revise the paper algorithm claim.",
        "2. Formally redefine the main algorithm as an HGS/LNS-style hybrid after a new user-approved plan.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def solution_for_row(row: dict[str, Any]) -> Solution:
    checkpoint = str(row.get("checkpoint_path") or "")
    if checkpoint:
        path = fc.repo_path(Path(checkpoint))
        payload = fc.read_json(path)
        if payload.get("solution"):
            return solution_from_json(payload["solution"])
    return solution_from_json(str(row.get("solution_json") or "{}"))


def solution_from_json(payload: str | dict[str, Any]) -> Solution:
    data = json.loads(payload) if isinstance(payload, str) else payload
    return Solution(
        routes=[Route(**route) for route in data.get("routes", [])],
        charging_actions=[ChargingAction(**action) for action in data.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**service) for service in data.get("cross_site_services", [])],
    )


def mixed_route_block_order(a7_solution: Solution, lns_solution: Solution, instance: Any, context: OrderDecodeContext) -> list[str]:
    blocks: list[list[str]] = []
    for left, right in zip(a7_solution.routes, lns_solution.routes):
        blocks.append(solution_route_order(left, instance))
        blocks.append(solution_route_order(right, instance))
    longer = a7_solution.routes if len(a7_solution.routes) > len(lns_solution.routes) else lns_solution.routes
    for route in longer[min(len(a7_solution.routes), len(lns_solution.routes)) :]:
        blocks.append(solution_route_order(route, instance))
    merged: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        for customer_id in block:
            if customer_id not in seen:
                merged.append(customer_id)
                seen.add(customer_id)
    return complete_order(merged, context)


def solution_route_order(route: Route, instance: Any) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [node_id for node_id in route.node_sequence if node_id in node_lookup and node_lookup[node_id].node_type.lower() == "c"]


def angle_scan_order(instance: Any, context: OrderDecodeContext) -> list[str]:
    if _angle_scan_order is not None:
        return list(_angle_scan_order(instance))
    depots = context.depots or []
    if not depots:
        return list(context.customer_ids or [])
    depot = depots[0]
    return sorted(
        context.customer_ids or [],
        key=lambda cid: math.atan2((context.node_lookup or {})[cid].y - depot.y, (context.node_lookup or {})[cid].x - depot.x),
    )


def route_type_count(solution: Solution, route_type: str) -> int:
    return sum(1 for route in solution.routes if route.vehicle_type.lower() == route_type)


def order_similarity(left: list[str], right: list[str]) -> float:
    if not left and not right:
        return 1.0
    left_pos = {customer_id: idx for idx, customer_id in enumerate(left)}
    right_pos = {customer_id: idx for idx, customer_id in enumerate(right)}
    common = [customer_id for customer_id in left if customer_id in right_pos]
    if not common:
        return 0.0
    displacement = sum(abs(left_pos[cid] - right_pos[cid]) for cid in common)
    max_disp = max(1, len(common) * max(len(left), len(right)))
    return max(0.0, 1.0 - displacement / max_disp)


def loss_bucket(a7_row: dict[str, Any], lns_row: dict[str, Any]) -> str:
    route_delta = as_int(a7_row.get("route_count")) - as_int(lns_row.get("route_count"))
    fix_delta = as_float(a7_row.get("cost_fix")) - as_float(lns_row.get("cost_fix"))
    if route_delta > 0 or fix_delta > 1e-9:
        return "route_fixed"
    return "non_route_fixed"


def write_hashes(output_dir: Path) -> None:
    files: dict[str, str] = {}
    clean_artifact_dir(output_dir)
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(output_dir)
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_NAMES:
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in rel_path.parts):
            continue
        files[str(rel_path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    fc.write_json(output_dir / "artifact_hashes.json", {"schema": "setp-artifact-hashes.v1", "root": fc.rel(output_dir), "files": files})
    clean_artifact_dir(output_dir)


def clean_artifact_dir(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_PARTS:
            if path.is_dir():
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def git_head() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def ok_row(row: dict[str, Any]) -> bool:
    return str(row.get("status")) == "OK" and str(row.get("feasible")).lower() in {"true", "1", "yes"}


def truthy(value: Any) -> bool:
    return str(value).lower() in {"true", "1", "yes"}


def safe_gap(cost: float, reference: float) -> float:
    return (reference - cost) / reference if math.isfinite(cost) and math.isfinite(reference) and abs(reference) > 1e-12 else math.nan


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
