#!/usr/bin/env python3
"""Small, wiring-only probe for the clean E2b component comparison.

This runner deliberately schedules only three route searches per
instance/seed.  The fourth row reuses the third search result and changes only
the legal charging times.  It is a short preflight, not the formal 9 x 5
matrix and not paper evidence.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    _reschedule_staged_result,
    run_staged_alns_lns_hybrid,
)
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations


ASSET_ROOT = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
OWNERSHIP_ROOT = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713/ownership_maps"
DEFAULT_OUT = ROOT / "baselines/e2_alns/e2b_component_ablation_probe_20260715"
INSTANCE_LADDER = (
    "L-main-threeshift-10c-01",
    "L-main-threeshift-15c-01",
    "L-main-threeshift-20c-01",
    "L-main-threeshift-25c-01",
    "L-main-threeshift-50c-01",
    "L-main-threeshift-75c-01",
    "L-main-threeshift-100c-01",
    "L-main-threeshift-150c-01",
    "L-main-threeshift-200c-01",
)
DEFAULT_INSTANCES = ("L-main-threeshift-50c-01", "L-main-threeshift-100c-01")
MAX_PROBE_SEARCHES = 6
MAX_PROBE_BUDGET = 1000


@dataclass(frozen=True)
class SearchGroup:
    group_id: str
    label: str
    enable_staged_search: bool
    enable_cross_depot_operator: bool
    reciprocal_cross_depot: bool


SEARCH_GROUPS = (
    SearchGroup("A_continuous", "continuous ALNS", False, False, False),
    SearchGroup("B_staged", "400/middle/400 staged ALNS", True, False, False),
    SearchGroup("C_staged_cross", "staged ALNS plus dedicated cross-depot adjustment", True, True, True),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def load_owners(instance: str, condition: str) -> tuple[dict[str, str], Path]:
    path = OWNERSHIP_ROOT / f"{instance}__{condition}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        owners = {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}
    if not owners:
        raise ValueError(f"empty ownership map: {path}")
    return owners, path


def build_search_tasks(
    instances: Iterable[str],
    seeds: Iterable[int],
    *,
    eval_budget: int,
    condition: str,
) -> list[dict[str, Any]]:
    """Build only the three route-search tasks; group D is replayed from C."""

    tasks: list[dict[str, Any]] = []
    for instance in instances:
        if instance not in INSTANCE_LADDER:
            raise ValueError(f"unsupported probe instance: {instance}")
        bundle_dir = ASSET_ROOT / instance / "bundle"
        start_path = ASSET_ROOT / instance / f"{condition}__common_start.json"
        owner_path = OWNERSHIP_ROOT / f"{instance}__{condition}.csv"
        for required in (bundle_dir / "instance.json", start_path, owner_path):
            if not required.exists():
                raise FileNotFoundError(required)
        start_hash = sha256(start_path)
        for seed in seeds:
            for group in SEARCH_GROUPS:
                tasks.append(
                    {
                        "instance": instance,
                        "seed": int(seed),
                        "condition": condition,
                        "eval_budget": int(eval_budget),
                        "bundle_dir": str(bundle_dir),
                        "start_path": str(start_path),
                        "start_solution_sha256": start_hash,
                        "ownership_path": str(owner_path),
                        "ownership_sha256": sha256(owner_path),
                        **asdict(group),
                    }
                )
    validate_task_manifest(tasks)
    return tasks


def validate_task_manifest(tasks: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for task in tasks:
        grouped.setdefault((str(task["instance"]), int(task["seed"])), []).append(task)
    for key, rows in grouped.items():
        if {row["group_id"] for row in rows} != {group.group_id for group in SEARCH_GROUPS}:
            raise ValueError(f"incomplete E2b search groups for {key}")
        if len({row["start_solution_sha256"] for row in rows}) != 1:
            raise ValueError(f"start solution differs across groups for {key}")
        if len({int(row["eval_budget"]) for row in rows}) != 1:
            raise ValueError(f"search budget differs across groups for {key}")
        if any(not bool(row.get("enable_staged_search")) for row in rows if row["group_id"] != "A_continuous"):
            raise ValueError(f"staged switch drifted for {key}")
        if any(bool(row.get("enable_cross_depot_operator")) for row in rows if row["group_id"] != "C_staged_cross"):
            raise ValueError(f"dedicated cross-depot switch drifted for {key}")


def expected_staged_budgets(eval_budget: int) -> list[int]:
    total = max(0, int(eval_budget))
    opening = min(400, total)
    closing = min(400, max(0, total - opening))
    middle = max(0, total - opening - closing)
    return [opening, middle, closing]


def _operator_attempts(operator_counts: dict[str, Any], family: str, name: str) -> int:
    staged = operator_counts.get("staged_chain", {}) if isinstance(operator_counts, dict) else {}
    phases = staged.get("phase_operator_counts", []) if isinstance(staged, dict) else []
    total = 0
    for phase in phases if isinstance(phases, list) else []:
        values = phase.get(family, {}).get(name, ()) if isinstance(phase, dict) else ()
        if isinstance(values, (list, tuple)):
            total += sum(int(value) for value in values)
    return total


def _solution_sha(solution: Any) -> str:
    return sha256_bytes(canonical_bytes(legacy.solution_to_dict(solution)))


def _route_vehicle_sha(solution: Any) -> str:
    payload = sorted(
        (
            str(route.vehicle_id),
            str(route.vehicle_type).lower(),
            str(route.home_depot_id),
            tuple(route.node_sequence),
        )
        for route in solution.routes
    )
    return sha256_bytes(canonical_bytes(payload))


def _charging_identity_sha(solution: Any) -> str:
    payload = sorted(
        (
            str(action.vehicle_id),
            str(action.station_id),
            round(float(action.energy_kwh), 9),
            round(float(action.occupancy_minutes), 9),
            int(action.charge_day_offset),
        )
        for action in solution.charging_actions
    )
    return sha256_bytes(canonical_bytes(payload))


def _evidence_row(
    task: dict[str, Any],
    result: dict[str, Any],
    solution: Any,
    *,
    group_id: str,
    label: str,
    charging_strategy: str,
    search_performed: bool,
    source_group: str,
) -> dict[str, Any]:
    bundle = load_search_bundle(task["bundle_dir"])
    owners, _ = load_owners(str(task["instance"]), str(task["condition"]))
    prices = legacy.prices_for("M1", 0.0)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=0.0,
        fairness_enabled=False,
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    annotated = legacy.annotate_cross_site(solution, owners)
    prepared, certificate = prepare_solution(annotated, context)
    if certificate is None:
        raise RuntimeError(f"no strict multitrip certificate for {task['instance']}/{group_id}")
    violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    metrics, closure_error = legacy._metric_row(prepared, bundle, prices)
    counts = legacy.score_counts(result)
    operator_counts = result.get("operator_counts", {})
    staged = operator_counts.get("staged_chain", {}) if isinstance(operator_counts, dict) else {}
    row = {
        "instance": task["instance"],
        "seed": int(task["seed"]),
        "condition": task["condition"],
        "group_id": group_id,
        "group_label": label,
        "source_group": source_group,
        "search_performed": bool(search_performed),
        "configured_search_budget": int(task["eval_budget"]) if search_performed else 0,
        "actual_search_evals": int(result.get("evaluations", 0)) if search_performed else 0,
        "source_search_evals": int(result.get("evaluations", 0)),
        "start_solution_sha256": task["start_solution_sha256"],
        "ownership_sha256": task["ownership_sha256"],
        "route_signature": legacy.route_signature(prepared),
        "route_vehicle_sha256": _route_vehicle_sha(prepared),
        "solution_sha256": _solution_sha(prepared),
        "strict_multitrip": True,
        "allow_cross_depot": True,
        "enable_staged_search": bool(task["enable_staged_search"]) if search_performed else "",
        "enable_cross_depot_operator": bool(task["enable_cross_depot_operator"]) if search_performed else "",
        "reciprocal_cross_depot": bool(task["reciprocal_cross_depot"]) if search_performed else "",
        "stage_budgets_json": json.dumps(staged.get("budgets", [])),
        "phase_evaluations_json": json.dumps(staged.get("phase_evaluations", [])),
        "strong_phase_indexes_json": json.dumps(staged.get("strong_phase_indexes", [])),
        "dedicated_cross_destroy_attempts": _operator_attempts(
            operator_counts, "destroy", "cross_depot_boundary_removal"
        ),
        "dedicated_cross_repair_attempts": _operator_attempts(
            operator_counts, "repair", "cross_depot_insert_repair"
        ),
        "forced_cross_operator_calls": int(counts.get("cross_depot_forced_operator_calls", 0)),
        "cross_site_customer_count": len(prepared.cross_site_services),
        "charging_strategy": charging_strategy,
        "charging_action_count": len(prepared.charging_actions),
        "charging_energy_kwh": sum(
            float(action.energy_kwh) for action in prepared.charging_actions
        ),
        "charging_identity_sha256": _charging_identity_sha(prepared),
        "charging_actions_moved": int(result.get("charging_actions_moved_from_search_output", 0)),
        "violation_count": len(violations),
        "cost_component_error": float(closure_error),
        "valid": not violations and float(closure_error) <= 1e-6,
        **legacy._certificate_stats(certificate),
        **metrics,
        "_solution_payload": legacy.solution_to_dict(prepared),
        "_certificate_payload": certificate.as_dict(),
    }
    return row


def run_search_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    bundle = load_search_bundle(task["bundle_dir"])
    owners, owner_path = load_owners(str(task["instance"]), str(task["condition"]))
    if sha256(owner_path) != task["ownership_sha256"]:
        raise ValueError("ownership map changed after task creation")
    start_path = Path(task["start_path"])
    if sha256(start_path) != task["start_solution_sha256"]:
        raise ValueError("common start changed after task creation")
    start_payload = json.loads(start_path.read_text(encoding="utf-8"))
    start = legacy.solution_from_dict(json.loads(canonical_bytes(start_payload)))
    prices = legacy.prices_for("M1", 0.0)
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=int(bundle.instance.num_cv or 0),
        max_ev=int(bundle.instance.num_ev or 0),
        allow_cross_depot=True,
        enable_cross_depot_operator=bool(task["enable_cross_depot_operator"]),
        reciprocal_cross_depot=bool(task["reciprocal_cross_depot"]),
    )
    started = time.perf_counter()
    with legacy.strict_mode():
        raw = run_staged_alns_lns_hybrid(
            task["bundle_dir"],
            config=WinnerKernelConfig(
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=max(300.0, float(task["eval_budget"]) * 0.5),
                require_charging_signal=False,
            ),
            initial_solution=start,
            prices=prices,
            policy=policy,
            carbon_weight=0.0,
            fairness_enabled=False,
            customer_home_depot=owners,
            enable_staged_search=bool(task["enable_staged_search"]),
        )
        immediate = _reschedule_staged_result(
            raw,
            task["bundle_dir"],
            prices,
            "naive",
            carbon_weight=0.0,
            customer_home_depot=owners,
            allow_cross_depot=True,
        )
        rows = [
            _evidence_row(
                task,
                immediate,
                immediate["best_solution"],
                group_id=str(task["group_id"]),
                label=str(task["label"]),
                charging_strategy="naive",
                search_performed=True,
                source_group=str(task["group_id"]),
            )
        ]
        if task["group_id"] == "C_staged_cross":
            aware = _reschedule_staged_result(
                raw,
                task["bundle_dir"],
                prices,
                "aware",
                carbon_weight=0.0,
                customer_home_depot=owners,
                allow_cross_depot=True,
            )
            rows.append(
                _evidence_row(
                    task,
                    aware,
                    aware["best_solution"],
                    group_id="D_full",
                    label="group C routes plus carbon-aware charging replay",
                    charging_strategy="aware",
                    search_performed=False,
                    source_group="C_staged_cross",
                )
            )
    if len(rows) == 2:
        if rows[0]["route_vehicle_sha256"] != rows[1]["route_vehicle_sha256"]:
            raise RuntimeError("group D changed the group C routes or vehicles")
        if rows[0]["charging_identity_sha256"] != rows[1]["charging_identity_sha256"]:
            raise RuntimeError("group D changed charging actions or total energy")
    for row in rows:
        row["elapsed_seconds"] = time.perf_counter() - started
    return rows


def assess_probe(rows: list[dict[str, Any]], eval_budget: int) -> dict[str, Any]:
    reasons: list[str] = []
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["instance"]), int(row["seed"])), {})[str(row["group_id"])] = row
    expected_groups = {"A_continuous", "B_staged", "C_staged_cross", "D_full"}
    for key, arms in grouped.items():
        if set(arms) != expected_groups:
            reasons.append(f"{key}: missing comparison group")
            continue
        if len({arms[group]["start_solution_sha256"] for group in expected_groups}) != 1:
            reasons.append(f"{key}: starts differ")
        for group in ("A_continuous", "B_staged", "C_staged_cross"):
            row = arms[group]
            if int(row["actual_search_evals"]) != int(eval_budget):
                reasons.append(f"{key}/{group}: evaluation budget not exhausted")
            if not bool(row["valid"]) or not bool(row["strict_multitrip"]) or not bool(row["allow_cross_depot"]):
                reasons.append(f"{key}/{group}: strict feasibility contract failed")
        if json.loads(arms["A_continuous"]["stage_budgets_json"]) != [int(eval_budget)]:
            reasons.append(f"{key}/A: continuous switch did not yield one phase")
        if json.loads(arms["A_continuous"]["strong_phase_indexes_json"]) != []:
            reasons.append(f"{key}/A: strong middle phase leaked into continuous search")
        expected_staged = expected_staged_budgets(eval_budget)
        for group in ("B_staged", "C_staged_cross"):
            if json.loads(arms[group]["stage_budgets_json"]) != expected_staged:
                reasons.append(f"{key}/{group}: staged budget plan drifted")
            if json.loads(arms[group]["strong_phase_indexes_json"]) != [1]:
                reasons.append(f"{key}/{group}: strong middle phase index drifted")
        if int(arms["A_continuous"]["dedicated_cross_destroy_attempts"]) != 0:
            reasons.append(f"{key}/A: dedicated cross-depot adjustment leaked")
        if int(arms["B_staged"]["dedicated_cross_destroy_attempts"]) != 0:
            reasons.append(f"{key}/B: dedicated cross-depot adjustment leaked")
        if int(arms["C_staged_cross"]["dedicated_cross_destroy_attempts"]) <= 0:
            reasons.append(f"{key}/C: dedicated cross-depot adjustment was never exercised")
        if arms["C_staged_cross"].get("route_vehicle_sha256", arms["C_staged_cross"]["route_signature"]) != arms["D_full"].get("route_vehicle_sha256", arms["D_full"]["route_signature"]):
            reasons.append(f"{key}/D: charging replay changed routes or vehicles")
        if (
            "charging_identity_sha256" in arms["C_staged_cross"]
            and arms["C_staged_cross"]["charging_identity_sha256"]
            != arms["D_full"].get("charging_identity_sha256")
        ):
            reasons.append(f"{key}/D: charging replay changed energy or action identity")
        if bool(arms["D_full"]["search_performed"]) or int(arms["D_full"]["actual_search_evals"]) != 0:
            reasons.append(f"{key}/D: unexpected second route search")
        if not bool(arms["D_full"]["valid"]):
            reasons.append(f"{key}/D: charging replay is infeasible")
    return {
        "status": "PASS_WIRING_ONLY" if not reasons else "HALT_WIRING",
        "formal_inference_allowed": False,
        "reason": "short probe checks wiring only; it does not estimate component effects",
        "failures": reasons,
        "comparison_unit_count": len(grouped),
        "evidence_row_count": len(rows),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    clean = [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
    fieldnames = sorted({key for row in clean for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean)


def _write_artifact_hashes(out: Path) -> None:
    targets = [out / name for name in ("metadata.json", "task_manifest.csv", "raw_runs.csv", "decision.json", "report.md")]
    write_json(
        out / "artifact_hashes.json",
        {str(path.relative_to(out)): sha256(path) for path in targets if path.exists()},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", default=",".join(DEFAULT_INSTANCES))
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--condition", choices=("mixed", "geographic"), default="mixed")
    parser.add_argument("--eval-budget", type=int, default=MAX_PROBE_BUDGET)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    instances = tuple(item.strip() for item in args.instances.split(",") if item.strip())
    seeds = tuple(int(item) for item in args.seeds.split(",") if item.strip())
    if not 1 <= int(args.eval_budget) <= MAX_PROBE_BUDGET:
        raise ValueError(f"short probe budget must be in [1, {MAX_PROBE_BUDGET}]")
    tasks = build_search_tasks(instances, seeds, eval_budget=int(args.eval_budget), condition=str(args.condition))
    if len(tasks) > MAX_PROBE_SEARCHES:
        raise ValueError(f"short probe may schedule at most {MAX_PROBE_SEARCHES} searches, got {len(tasks)}")
    out = args.output_dir.resolve()
    if (out / "raw_runs.csv").exists():
        raise FileExistsError(f"refusing to overwrite an existing probe: {out}")
    out.mkdir(parents=True, exist_ok=True)
    solutions = out / "solutions"
    certificates = out / "certificates"
    solutions.mkdir(exist_ok=True)
    certificates.mkdir(exist_ok=True)

    _write_csv(out / "task_manifest.csv", tasks)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    workers = max(1, min(int(args.workers), len(tasks)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_search_task, task): task for task in tasks}
        for future in as_completed(futures):
            rows.extend(future.result())
    rows.sort(key=lambda row: (str(row["instance"]), int(row["seed"]), str(row["group_id"])))
    for row in rows:
        run_id = f"{row['instance']}__{row['condition']}__seed{row['seed']}__{row['group_id']}"
        solution_path = solutions / f"{run_id}.json"
        certificate_path = certificates / f"{run_id}.json"
        write_json(solution_path, row.pop("_solution_payload"))
        write_json(certificate_path, row.pop("_certificate_payload"))
        row["solution_path"] = display_path(solution_path)
        row["solution_file_sha256"] = sha256(solution_path)
        row["certificate_path"] = display_path(certificate_path)
        row["certificate_sha256"] = sha256(certificate_path)
    decision = assess_probe(rows, int(args.eval_budget))
    _write_csv(out / "raw_runs.csv", rows)
    write_json(
        out / "metadata.json",
        {
            "schema": "resetp.e2b.component-ablation-probe.v1",
            "purpose": "wiring-only short probe; no component-effect inference",
            "instances": list(instances),
            "seeds": list(seeds),
            "condition": args.condition,
            "search_groups": [asdict(group) for group in SEARCH_GROUPS],
            "fourth_group": "replay C routes with carbon-aware charging and zero route search",
            "eval_budget_per_search": int(args.eval_budget),
            "search_task_count": len(tasks),
            "workers": workers,
            "elapsed_seconds": time.perf_counter() - started,
            "strict_multitrip": True,
            "allow_cross_depot_in_all_search_groups": True,
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "source_file_hashes": {
                display_path(path): sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
                    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
                    ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
                    ROOT / "solver/src/setp_solver/cost.py",
                    ROOT / "solver/src/setp_solver/check.py",
                    ROOT / "solver/src/setp_solver/search/evaluation.py",
                )
            },
        },
    )
    write_json(out / "decision.json", decision)
    (out / "report.md").write_text(
        "# E2b component comparison short probe\n\n"
        f"Decision: `{decision['status']}`.\n\n"
        "This run checks only that the four rows differ in the intended places: one staged-search switch, "
        "one dedicated cross-depot-adjustment switch, and one zero-search charging replay. "
        "It is not the formal nine-network experiment and supports no paper conclusion.\n\n"
        f"Failures: {json.dumps(decision['failures'], ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    _write_artifact_hashes(out)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["status"] == "PASS_WIRING_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
