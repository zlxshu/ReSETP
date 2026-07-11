"""Offline route-block complementarity audit for the final bounded E2 recovery decision."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix, vstack


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns.e2_loss_recovery_gate import DEVELOPMENT_PAIRS, GUARD_PAIRS
from setp_solver.algorithms.resetp_alns.support.fleet import (
    infer_fleet_limits,
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.search.metaheuristic_baselines import solution_from_dict, solution_to_dict
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution


PARENT_LOCATIONS = {
    "staged": ("true_lns_middle_gate", "staged"),
    "LNS": ("true_lns_middle_gate", "LNS"),
    "restarted": ("short_gate_formal_start", "restarted"),
    "true_lns_middle": ("true_lns_middle_gate", "true_lns_middle"),
    "proportional_true_lns_middle": (
        "proportional_true_lns_middle_gate",
        "proportional_true_lns_middle",
    ),
}
PARENT_ORDER = tuple(PARENT_LOCATIONS)


@dataclass(frozen=True)
class RouteBlock:
    source: str
    route: Route
    actions: tuple[ChargingAction, ...]
    cross_site_services: tuple[CrossSiteService, ...]
    customers: tuple[str, ...]
    structural_signature: str
    full_signature: str
    isolated_cost: float


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_payload(payload: Any) -> str:
    return _sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def structural_route_signature(route: Route) -> str:
    return _hash_payload(
        {
            "vehicle_type": route.vehicle_type.lower(),
            "home_depot_id": route.home_depot_id,
            "node_sequence": list(route.node_sequence),
        }
    )


def classify_headroom(rows: list[dict[str, Any]], *, parents_clean: bool) -> str:
    development = [row for row in rows if row["pair_role"] == "development"]
    feasible_mixed = sum(int(row["feasible_mixed_partitions"]) > 0 for row in development)
    material = sum(float(row["best_mixed_gain_vs_best_parent_pct"]) >= 0.25 - 1e-9 for row in development)
    converted = sum(
        float(row["best_mixed_gain_vs_best_parent_pct"]) >= 0.25 - 1e-9
        and float(row["best_mixed_cost"]) < float(row["lns_cost"]) - 1e-9
        for row in development
    )
    if parents_clean and feasible_mixed >= 3 and material >= 2 and converted >= 2:
        return "ROUTE_BLOCK_HEADROOM_SUPPORTED"
    return "ROUTE_BLOCK_HEADROOM_NOT_SUPPORTED"


def _solution_path(evidence_root: Path, instance: str, seed: int, source: str) -> Path:
    directory, algorithm = PARENT_LOCATIONS[source]
    return evidence_root / directory / "solutions" / f"{instance}__seed{seed}__{algorithm}.json"


def _load_parents(
    evidence_root: Path,
    instance: str,
    seed: int,
    context: EvaluationContext,
) -> tuple[dict[str, Solution], list[dict[str, Any]]]:
    parents: dict[str, Solution] = {}
    audit_rows: list[dict[str, Any]] = []
    for source in PARENT_ORDER:
        path = _solution_path(evidence_root, instance, seed, source)
        if not path.exists():
            raise RuntimeError(f"MISSING_PARENT_SOLUTION:{path}")
        solution = solution_from_dict(_read_json(path))
        violations = check_solution(solution, context.instance, context.prices)
        cost = float(model_cost(solution, context))
        audit_rows.append(
            {
                "instance": instance,
                "seed": seed,
                "source": source,
                "path": str(path.relative_to(REPO_ROOT)),
                "cost": cost,
                "routes": len(solution.routes),
                "violations": len(violations),
                "solution_sha256": _sha256_bytes(path.read_bytes()),
            }
        )
        if violations:
            raise RuntimeError(f"INVALID_PARENT:{instance}:{seed}:{source}:{violations}")
        parents[source] = solution
    return parents, audit_rows


def _route_blocks(parents: dict[str, Solution], context: EvaluationContext) -> list[RouteBlock]:
    customer_ids = {node.node_id for node in context.instance.nodes if node.node_type.lower() == "c"}
    blocks: list[RouteBlock] = []
    seen: set[tuple[str, str]] = set()
    for source, solution in parents.items():
        cross_by_customer = {item.customer_id: item for item in solution.cross_site_services}
        for route in solution.routes:
            customers = tuple(node for node in route.node_sequence if node in customer_ids)
            if not customers:
                continue
            actions = tuple(action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id)
            cross = tuple(cross_by_customer[customer] for customer in customers if customer in cross_by_customer)
            structural = structural_route_signature(route)
            full = _hash_payload(
                {
                    "structural": structural,
                    "actions": [
                        {
                            "station": action.station_id,
                            "energy": round(action.energy_kwh, 9),
                            "occupancy": round(action.occupancy_minutes, 9),
                            "start": round(action.charge_start_second, 9),
                        }
                        for action in actions
                    ],
                    "cross": [(item.customer_id, item.served_by_depot_id) for item in cross],
                }
            )
            key = (source, full)
            if key in seen:
                continue
            seen.add(key)
            isolated = Solution(routes=[route], charging_actions=list(actions), cross_site_services=list(cross))
            blocks.append(
                RouteBlock(
                    source=source,
                    route=route,
                    actions=actions,
                    cross_site_services=cross,
                    customers=customers,
                    structural_signature=structural,
                    full_signature=full,
                    isolated_cost=float(model_cost(isolated, context)),
                )
            )
    return blocks


def _jaccard_rows(instance: str, seed: int, blocks: list[RouteBlock]) -> list[dict[str, Any]]:
    signatures = {
        source: {block.structural_signature for block in blocks if block.source == source}
        for source in PARENT_ORDER
    }
    rows = []
    for left, right in itertools.combinations(PARENT_ORDER, 2):
        union = signatures[left] | signatures[right]
        rows.append(
            {
                "instance": instance,
                "seed": seed,
                "left": left,
                "right": right,
                "left_routes": len(signatures[left]),
                "right_routes": len(signatures[right]),
                "shared_routes": len(signatures[left] & signatures[right]),
                "route_jaccard": len(signatures[left] & signatures[right]) / len(union) if union else 1.0,
            }
        )
    return rows


def _enumerate_partitions(
    blocks: list[RouteBlock],
    customer_ids: list[str],
    *,
    max_partitions: int,
    time_limit_seconds: float,
) -> list[tuple[int, ...]]:
    customer_index = {customer: idx for idx, customer in enumerate(customer_ids)}
    coverage = np.zeros((len(customer_ids), len(blocks)), dtype=float)
    for column, block in enumerate(blocks):
        for customer in block.customers:
            coverage[customer_index[customer], column] = 1.0
    constraints_matrix = csr_matrix(coverage)
    lower = np.ones(len(customer_ids), dtype=float)
    upper = np.ones(len(customer_ids), dtype=float)
    objective = np.asarray([block.isolated_cost for block in blocks], dtype=float)
    if objective.size:
        objective = objective + np.arange(objective.size, dtype=float) * 1e-10
    partitions: list[tuple[int, ...]] = []
    for _ in range(max(1, int(max_partitions))):
        result = milp(
            c=objective,
            integrality=np.ones(len(blocks), dtype=int),
            bounds=Bounds(np.zeros(len(blocks)), np.ones(len(blocks))),
            constraints=LinearConstraint(constraints_matrix, lower, upper),
            options={"time_limit": float(time_limit_seconds), "presolve": True},
        )
        if not result.success or result.x is None:
            break
        selected = tuple(int(idx) for idx in np.flatnonzero(result.x > 0.5))
        if not selected or selected in partitions:
            break
        partitions.append(selected)
        no_good = np.zeros((1, len(blocks)), dtype=float)
        no_good[0, list(selected)] = 1.0
        constraints_matrix = vstack((constraints_matrix, csr_matrix(no_good)), format="csr")
        lower = np.concatenate((lower, np.asarray([-math.inf])))
        upper = np.concatenate((upper, np.asarray([len(selected) - 1.0])))
    return partitions


def _mixed_solution(
    selected: tuple[int, ...],
    blocks: list[RouteBlock],
    context: EvaluationContext,
    bundle_dir: Path,
) -> tuple[Solution | None, list[str]]:
    chosen = [blocks[idx] for idx in selected]
    orderings = (
        chosen,
        sorted(chosen, key=lambda block: (block.source, block.structural_signature)),
        sorted(
            chosen,
            key=lambda block: (
                block.route.vehicle_type.lower(),
                block.route.home_depot_id,
                min(context.instance.node_index[node] for node in block.customers),
            ),
        ),
    )
    limits = infer_fleet_limits(bundle_dir)
    failure_reasons: list[str] = []
    seen_orders: set[tuple[str, ...]] = set()
    for ordering in orderings:
        order_signature = tuple(block.full_signature for block in ordering)
        if order_signature in seen_orders:
            continue
        seen_orders.add(order_signature)
        routes: list[Route] = []
        actions: list[ChargingAction] = []
        cross: dict[tuple[str, str], CrossSiteService] = {}
        for position, block in enumerate(ordering):
            temporary_id = f"RB{position + 1}_{block.source}_{block.route.vehicle_id}"
            routes.append(replace(block.route, vehicle_id=temporary_id))
            actions.extend(replace(action, vehicle_id=temporary_id) for action in block.actions)
            for item in block.cross_site_services:
                cross[(item.customer_id, item.served_by_depot_id)] = item
        try:
            candidate = normalize_solution_vehicle_trips(
                Solution(routes=routes, charging_actions=actions, cross_site_services=list(cross.values())),
                context.instance,
                max_cv=limits.cv,
                max_ev=limits.ev,
            )
        except ValueError as exc:
            failure_reasons.append(str(exc))
            continue
        violations = check_solution(candidate, context.instance, context.prices)
        if not violations:
            return candidate, []
        failure_reasons.extend(str(item) for item in violations[:8])
    return None, failure_reasons


def _audit_pair(payload: tuple[str, str, int, int, float]) -> dict[str, Any]:
    evidence_root_text, instance, seed, max_partitions, time_limit_seconds = payload
    evidence_root = Path(evidence_root_text)
    bundle_dir = instance_abs_dir(REPO_ROOT, instance)
    bundle = load_search_bundle(bundle_dir)
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=replace(DEFAULT_PRICES, B_battery_kwh=280.0))
    parents, parent_rows = _load_parents(evidence_root, instance, seed, context)
    blocks = _route_blocks(parents, context)
    customer_ids = sorted(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c")
    partitions = _enumerate_partitions(
        blocks,
        customer_ids,
        max_partitions=max_partitions,
        time_limit_seconds=time_limit_seconds,
    )
    attempts: list[dict[str, Any]] = []
    best_solution: Solution | None = None
    best_cost = math.inf
    for partition_index, selected in enumerate(partitions, start=1):
        sources = sorted({blocks[idx].source for idx in selected})
        mixed = len(sources) >= 2
        candidate: Solution | None = None
        reasons: list[str] = []
        if mixed:
            candidate, reasons = _mixed_solution(selected, blocks, context, bundle_dir)
        feasible = candidate is not None
        cost = float(model_cost(candidate, context)) if candidate is not None else math.inf
        if feasible and cost < best_cost:
            best_cost = cost
            best_solution = candidate
        attempts.append(
            {
                "instance": instance,
                "seed": seed,
                "partition_index": partition_index,
                "selected_routes": len(selected),
                "sources": "|".join(sources),
                "mixed_sources": mixed,
                "feasible": feasible,
                "cost": cost if math.isfinite(cost) else "",
                "failure_reason": " | ".join(dict.fromkeys(reasons))[:1000],
                "selected_block_indices": "|".join(str(idx) for idx in selected),
            }
        )
    parent_costs = {row["source"]: float(row["cost"]) for row in parent_rows}
    best_parent_source = min(parent_costs, key=parent_costs.get)
    best_parent_cost = parent_costs[best_parent_source]
    lns_cost = parent_costs["LNS"]
    feasible_mixed = sum(bool(row["mixed_sources"]) and bool(row["feasible"]) for row in attempts)
    summary = {
        "instance": instance,
        "seed": seed,
        "pair_role": "development" if (instance, seed) in DEVELOPMENT_PAIRS else "guard",
        "parents": len(parents),
        "parent_routes_total": sum(len(solution.routes) for solution in parents.values()),
        "unique_structural_routes": len({block.structural_signature for block in blocks}),
        "route_blocks": len(blocks),
        "enumerated_partitions": len(partitions),
        "feasible_mixed_partitions": feasible_mixed,
        "best_parent_source": best_parent_source,
        "best_parent_cost": best_parent_cost,
        "lns_cost": lns_cost,
        "best_mixed_cost": best_cost if math.isfinite(best_cost) else "",
        "best_mixed_gain_vs_best_parent_pct": (
            (best_parent_cost - best_cost) / best_parent_cost * 100.0 if math.isfinite(best_cost) else -math.inf
        ),
        "best_mixed_beats_lns": math.isfinite(best_cost) and best_cost < lns_cost - 1e-9,
    }
    route_rows = [
        {
            "instance": instance,
            "seed": seed,
            "block_index": idx,
            "source": block.source,
            "vehicle_type": block.route.vehicle_type,
            "home_depot_id": block.route.home_depot_id,
            "customers": len(block.customers),
            "customer_ids": "|".join(block.customers),
            "structural_signature": block.structural_signature,
            "full_signature": block.full_signature,
            "isolated_cost": block.isolated_cost,
        }
        for idx, block in enumerate(blocks)
    ]
    return {
        "summary": summary,
        "parent_rows": parent_rows,
        "route_rows": route_rows,
        "jaccard_rows": _jaccard_rows(instance, seed, blocks),
        "attempt_rows": attempts,
        "best_solution": solution_to_dict(best_solution) if best_solution is not None else None,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    evidence_root = repo_root / args.evidence_root
    output_dir = repo_root / args.output_dir
    solution_dir = output_dir / "best_mixed_solutions"
    output_dir.mkdir(parents=True, exist_ok=True)
    solution_dir.mkdir(parents=True, exist_ok=True)
    pairs = (*DEVELOPMENT_PAIRS, *GUARD_PAIRS)
    payloads = [
        (str(evidence_root), instance, seed, int(args.max_partitions), float(args.milp_time_limit_seconds))
        for instance, seed in pairs
    ]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, min(3, int(args.workers)))) as executor:
        futures = {executor.submit(_audit_pair, payload): payload for payload in payloads}
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: (item["summary"]["instance"], int(item["summary"]["seed"])))

    summaries = [item["summary"] for item in results]
    parent_rows = [row for item in results for row in item["parent_rows"]]
    route_rows = [row for item in results for row in item["route_rows"]]
    jaccard_rows = [row for item in results for row in item["jaccard_rows"]]
    attempt_rows = [row for item in results for row in item["attempt_rows"]]
    for item in results:
        payload = item["best_solution"]
        if payload is not None:
            summary = item["summary"]
            _atomic_json(
                solution_dir / f"{summary['instance']}__seed{summary['seed']}__best_mixed.json",
                payload,
            )
    _atomic_csv(output_dir / "pair_summary.csv", summaries)
    _atomic_csv(output_dir / "parent_recompute.csv", parent_rows)
    _atomic_csv(output_dir / "route_blocks.csv", route_rows)
    _atomic_csv(output_dir / "route_jaccard.csv", jaccard_rows)
    _atomic_csv(output_dir / "candidate_attempts.csv", attempt_rows)

    parents_clean = len(parent_rows) == 45 and all(int(row["violations"]) == 0 for row in parent_rows)
    verdict = classify_headroom(summaries, parents_clean=parents_clean)
    development = [row for row in summaries if row["pair_role"] == "development"]
    decision = {
        "verdict": verdict,
        "parents_clean": parents_clean,
        "pairs": len(summaries),
        "parent_solutions": len(parent_rows),
        "development_pairs_with_feasible_mixed_partition": sum(
            int(row["feasible_mixed_partitions"]) > 0 for row in development
        ),
        "development_pairs_with_material_headroom": sum(
            float(row["best_mixed_gain_vs_best_parent_pct"]) >= 0.25 - 1e-9 for row in development
        ),
        "development_pairs_converted_below_lns": sum(
            float(row["best_mixed_gain_vs_best_parent_pct"]) >= 0.25 - 1e-9
            and bool(row["best_mixed_beats_lns"])
            for row in development
        ),
        "new_search_runs": 0,
        "next_action": (
            "implement one bounded route-block population candidate"
            if verdict == "ROUTE_BLOCK_HEADROOM_SUPPORTED"
            else "close E2 loss recovery and start the preregistered 80 kWh robustness attempt"
        ),
    }
    _atomic_json(output_dir / "decision.json", decision)
    metadata = {
        "schema_version": "setp-e2-route-block-headroom-audit.v1",
        "diagnostic_only": True,
        "new_search_runs": 0,
        "battery_kwh": 280.0,
        "parent_locations": {key: list(value) for key, value in PARENT_LOCATIONS.items()},
        "pairs": [list(pair) for pair in pairs],
        "max_partitions_per_pair": int(args.max_partitions),
        "milp_time_limit_seconds": float(args.milp_time_limit_seconds),
        "workers": min(3, int(args.workers)),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True
        ).stdout.strip(),
    }
    _atomic_json(output_dir / "metadata.json", metadata)
    (output_dir / "report.md").write_text(
        "# E2 route-block complementarity audit\n\n"
        f"Verdict: `{verdict}`. No new ALNS/LNS search was run. "
        f"Clean parents: {parents_clean}. "
        f"Development pairs with feasible mixed partitions: "
        f"{decision['development_pairs_with_feasible_mixed_partition']}/6; "
        f"with >=0.25% headroom: {decision['development_pairs_with_material_headroom']}/6; "
        f"converted below LNS: {decision['development_pairs_converted_below_lns']}/6.\n",
        encoding="utf-8",
    )
    hashes = {
        str(path.relative_to(output_dir)): _sha256_bytes(path.read_bytes())
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    _atomic_json(output_dir / "artifact_hashes.json", hashes)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--evidence-root",
        default="baselines/e2_alns/e2_loss_recovery_20260711",
    )
    parser.add_argument(
        "--output-dir",
        default="baselines/e2_alns/e2_loss_recovery_20260711/route_block_headroom_audit",
    )
    parser.add_argument("--max-partitions", type=int, default=50)
    parser.add_argument("--milp-time-limit-seconds", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
