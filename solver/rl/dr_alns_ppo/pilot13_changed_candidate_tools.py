from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import numpy as np

from setp_solver.check import check_solution
from setp_solver.search.alns_wouda import (
    AlnsState,
    SearchPolicy,
    _solution_changed,
    _try_cv_to_ev_candidates,
)
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, score_candidate, score_reference
from setp_solver.search.feasible_repair import enumerate_feasible_insertions, repair_removed_customers
from setp_solver.search.winner_operators import WinnerOperatorSet
from setp_solver.solution import Solution


THREESHIFT_PROBE_BUNDLES: tuple[dict[str, str], ...] = (
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-01",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-01",
    },
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-02",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-02",
    },
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-03",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-03",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-01",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-01",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-02",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-02",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-03",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-03",
    },
)

REPAIR_MODES = ("greedy", "regret2", "regret3")

EVIDENCE_ITEMS: tuple[dict[str, str], ...] = (
    {
        "source": "docs/handoff/dr_alns_project_rhythm_manual.md:19,90-92",
        "claim": "The current learner lacks route, customer, vehicle, charging, repair-insertion, and acceptance/search-temperature context.",
        "resetp_implication": "Pilot13 must inspect repair and charging control points before another training run.",
    },
    {
        "source": "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot12/pilot12_final_diagnostic_report.md",
        "claim": "Pilot12 found zero accepted moves because the step-level neighborhood produced unchanged candidates on three-shift warm starts.",
        "resetp_implication": "The next diagnostic must split destroy, repair, and EV conversion before blaming PPO.",
    },
    {
        "source": "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/literature_materials/dr_alns_deep_read_master_20260626.md:319-333",
        "claim": "Reference PPO-ALNS methods expose repair, acceptance, stop, and richer state rather than only flat block operator choice.",
        "resetp_implication": "A learning-worthy interface needs a changed candidate stream or a deeper repair/charging action.",
    },
    {
        "source": "Reference Algorithm/ppo-alns-main and CEVRP DRL-ALNS reference code",
        "claim": "Reference implementations route learning through construction/repair/search-control decisions.",
        "resetp_implication": "Pilot13 checks whether ReSETP has a viable repair/charging landing point for such decisions.",
    },
)


@dataclass(frozen=True)
class BundleSpec:
    bundle_role: str
    bundle_name: str
    bundle_path: str


def threeshift_probe_bundles() -> list[dict[str, str]]:
    return [dict(row) for row in THREESHIFT_PROBE_BUNDLES]


def paired_relative_percent(*, candidate_cost: float, baseline_cost: float) -> float:
    baseline = float(baseline_cost)
    candidate = float(candidate_cost)
    if not math.isfinite(baseline) or baseline == 0.0:
        raise ValueError(f"baseline_cost must be finite and non-zero: {baseline_cost!r}")
    if not math.isfinite(candidate):
        raise ValueError(f"candidate_cost must be finite: {candidate_cost!r}")
    return (baseline - candidate) / baseline * 100.0


def classify_changed_candidate_headroom(
    repair_rows: list[dict[str, Any]],
    charging_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    charging_rows = charging_rows or []
    if not repair_rows:
        return {"status": "HALT_NO_CHANGED_CANDIDATE_HEADROOM", "reason": "no repair rows"}

    destroy_changed = sum(int(bool(row.get("destroy_changed"))) for row in repair_rows)
    destroyed_removed = sum(int(row.get("destroy_removed_count", 0)) for row in repair_rows)
    option_total = sum(int(row.get("repair_options_total", 0)) for row in repair_rows)
    default_changed = sum(int(row.get("default_changed_any", 0)) for row in repair_rows)
    alternative_changed = sum(int(row.get("alternative_changed_count", 0)) for row in repair_rows)
    alternative_improving = sum(int(row.get("alternative_improving_count", 0)) for row in repair_rows)
    charging_candidates = sum(int(row.get("cv_to_ev_candidate_count", 0)) for row in charging_rows)
    charging_changed = sum(int(row.get("changed_cv_to_ev_count", 0)) for row in charging_rows)
    charging_feasible = sum(int(row.get("feasible_cv_to_ev_count", 0)) for row in charging_rows)

    best_alt_relative = max(
        (float(row.get("best_alternative_relative_percent", -math.inf)) for row in repair_rows),
        default=-math.inf,
    )
    best_ev_relative = max(
        (float(row.get("best_cv_to_ev_relative_percent", -math.inf)) for row in charging_rows),
        default=-math.inf,
    )

    base = {
        "destroy_changed_rows": destroy_changed,
        "destroy_removed_total": destroyed_removed,
        "repair_options_total": option_total,
        "default_changed_rows": default_changed,
        "alternative_changed_count": alternative_changed,
        "alternative_improving_count": alternative_improving,
        "cv_to_ev_candidate_count": charging_candidates,
        "changed_cv_to_ev_count": charging_changed,
        "feasible_cv_to_ev_count": charging_feasible,
        "best_alternative_relative_percent": None if not math.isfinite(best_alt_relative) else best_alt_relative,
        "best_cv_to_ev_relative_percent": None if not math.isfinite(best_ev_relative) else best_ev_relative,
    }
    if destroy_changed == 0 or destroyed_removed == 0:
        return {**base, "status": "HALT_DESTROY_NO_REMOVAL", "reason": "destroy operators did not remove customers"}
    if option_total == 0:
        return {**base, "status": "HALT_REPAIR_NO_OPTIONS", "reason": "removed customers had no feasible insertion options"}
    if alternative_improving > 0:
        return {**base, "status": "PASS_REPAIR_IMPROVING_HEADROOM"}
    if alternative_changed > 0 or default_changed > 0:
        return {**base, "status": "PASS_REPAIR_CHANGED_DIVERSITY"}
    if charging_changed > 0 and charging_feasible > 0:
        return {**base, "status": "PASS_CHARGING_LANDING_POINT"}
    if charging_candidates == 0 or charging_feasible == 0:
        return {**base, "status": "HALT_NO_CHANGED_CANDIDATE_HEADROOM", "charging_gate": "HALT_CHARGING_NO_LANDING_POINT"}
    return {**base, "status": "HALT_NO_CHANGED_CANDIDATE_HEADROOM"}


def run_probe(
    *,
    output_dir: Path,
    seeds: Iterable[int],
    bundle_names: set[str] | None = None,
    remove_fraction: float = 0.40,
    max_removed_customers: int = 5,
    max_alternatives_per_destroy: int = 8,
    include_route_elimination: bool = False,
    initial_mode: str = "worker_cv",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_specs = _selected_bundles(bundle_names)
    if not bundle_specs:
        raise ValueError("no bundles selected")

    repair_rows: list[dict[str, Any]] = []
    charging_rows: list[dict[str, Any]] = []
    partial_repair = output_dir / "pilot13_repair_rows.partial.csv"
    partial_charging = output_dir / "pilot13_charging_rows.partial.csv"
    for bundle in bundle_specs:
        for seed in seeds:
            result = probe_bundle(
                bundle=bundle,
                seed=int(seed),
                remove_fraction=float(remove_fraction),
                max_removed_customers=int(max_removed_customers),
                max_alternatives_per_destroy=int(max_alternatives_per_destroy),
                include_route_elimination=bool(include_route_elimination),
                initial_mode=str(initial_mode),
            )
            repair_rows.extend(result["repair_rows"])
            charging_rows.append(result["charging_row"])
            write_rows_csv(partial_repair, repair_rows)
            write_rows_csv(partial_charging, charging_rows)

    gate = classify_changed_candidate_headroom(repair_rows, charging_rows)
    repair_summary = summarize_repair_rows(repair_rows)
    charging_summary = summarize_charging_rows(charging_rows)
    write_rows_csv(output_dir / "pilot13_repair_rows.csv", repair_rows)
    write_rows_csv(output_dir / "pilot13_charging_rows.csv", charging_rows)
    write_rows_csv(output_dir / "pilot13_repair_summary.csv", repair_summary)
    write_rows_csv(output_dir / "pilot13_charging_summary.csv", charging_summary)
    summary = {
        "scope": "no-training changed-candidate headroom diagnostic",
        "bundle_names": [bundle.bundle_name for bundle in bundle_specs],
        "seeds": [int(seed) for seed in seeds],
        "remove_fraction": float(remove_fraction),
        "max_removed_customers": int(max_removed_customers),
        "max_alternatives_per_destroy": int(max_alternatives_per_destroy),
        "include_route_elimination": bool(include_route_elimination),
        "initial_mode": str(initial_mode),
        "repair_row_count": len(repair_rows),
        "charging_row_count": len(charging_rows),
        "gate": gate,
        "repair_summary": repair_summary,
        "charging_summary": charging_summary,
    }
    (output_dir / "pilot13_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "pilot13_changed_candidate_report.md").write_text(
        render_report(summary=summary, repair_rows=repair_rows, charging_rows=charging_rows),
        encoding="utf-8",
    )
    return summary


def probe_bundle(
    *,
    bundle: BundleSpec,
    seed: int,
    remove_fraction: float,
    max_removed_customers: int,
    max_alternatives_per_destroy: int,
    include_route_elimination: bool,
    initial_mode: str,
) -> dict[str, Any]:
    start = time.perf_counter()
    search_bundle = load_search_bundle(bundle.bundle_path)
    context = EvaluationContext(
        search_bundle.instance,
        search_bundle.carbon_profile,
        budget=EvalBudget(limit=1_000_000, target=1_000_000),
    )
    introduce_ev, require_charging_signal = _initial_mode_flags(initial_mode)
    initial = build_initial_solution(
        search_bundle.instance,
        search_bundle.carbon_profile,
        introduce_ev=introduce_ev,
        require_charging_signal=require_charging_signal,
    )
    initial_obj = score_reference(initial, context)
    policy = SearchPolicy(require_charging_signal=False)
    state = AlnsState(initial, context, objective_value=initial_obj, policy=policy)
    customer_count = _customer_count(initial, context)
    remove_count_q = max(1, int(math.ceil(float(remove_fraction) * max(1, customer_count))))
    op_set = WinnerOperatorSet.create(include_route_elimination=include_route_elimination)
    repair_rows: list[dict[str, Any]] = []
    for destroy_index, (destroy_id, destroy_op) in enumerate(op_set.destroy_ops):
        if destroy_id == "vehicle_type_swap":
            continue
        rng = np.random.default_rng(int(seed) * 10_000 + destroy_index)
        destroyed = destroy_op(state, rng, progress=0.0, remove_count_q=remove_count_q)
        row = _probe_destroy_repair(
            bundle=bundle,
            seed=int(seed),
            destroy_id=destroy_id,
            destroyed=destroyed,
            state=state,
            initial_obj=float(initial_obj),
            remove_count_q=int(remove_count_q),
            initial_mode=str(initial_mode),
            max_removed_customers=int(max_removed_customers),
            max_alternatives_per_destroy=int(max_alternatives_per_destroy),
        )
        repair_rows.append(row)
    charging_row = _probe_charging_landing_point(
        bundle=bundle,
        seed=int(seed),
        state=state,
        initial_obj=float(initial_obj),
        initial_mode=str(initial_mode),
        elapsed_seconds=time.perf_counter() - start,
    )
    return {"repair_rows": repair_rows, "charging_row": charging_row}


def summarize_repair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["bundle_role"]), []).append(row)
    summary: list[dict[str, Any]] = []
    for role, values in sorted(grouped.items()):
        summary.append(
            {
                "bundle_role": role,
                "rows": len(values),
                "destroy_removed_total": sum(int(row["destroy_removed_count"]) for row in values),
                "destroy_changed_rows": sum(int(bool(row["destroy_changed"])) for row in values),
                "repair_options_total": sum(int(row["repair_options_total"]) for row in values),
                "default_changed_rows": sum(int(row["default_changed_any"]) for row in values),
                "alternative_changed_count": sum(int(row["alternative_changed_count"]) for row in values),
                "alternative_improving_count": sum(int(row["alternative_improving_count"]) for row in values),
                "best_alternative_relative_percent": max(float(row["best_alternative_relative_percent"]) for row in values),
            }
        )
    return summary


def summarize_charging_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["bundle_role"]), []).append(row)
    summary: list[dict[str, Any]] = []
    for role, values in sorted(grouped.items()):
        summary.append(
            {
                "bundle_role": role,
                "rows": len(values),
                "initial_cv_routes_mean": mean(float(row["initial_cv_routes"]) for row in values),
                "initial_ev_routes_mean": mean(float(row["initial_ev_routes"]) for row in values),
                "initial_charging_actions_mean": mean(float(row["initial_charging_actions"]) for row in values),
                "cv_to_ev_candidate_count": sum(int(row["cv_to_ev_candidate_count"]) for row in values),
                "changed_cv_to_ev_count": sum(int(row["changed_cv_to_ev_count"]) for row in values),
                "feasible_cv_to_ev_count": sum(int(row["feasible_cv_to_ev_count"]) for row in values),
                "best_cv_to_ev_relative_percent": max(float(row["best_cv_to_ev_relative_percent"]) for row in values),
            }
        )
    return summary


def render_report(
    *,
    summary: dict[str, Any],
    repair_rows: list[dict[str, Any]],
    charging_rows: list[dict[str, Any]],
) -> str:
    gate = summary["gate"]
    lines = [
        "# Pilot13 Changed-Candidate Headroom Diagnostic",
        "",
        f"Gate: `{gate.get('status', 'UNKNOWN')}`",
        "",
        "Scope: no training, no policy evaluation claim, no protected solver semantic changes.",
        "",
        "Human reading: Pilot12 showed accept/stop cannot help if the search never creates a different candidate. Pilot13 splits the chain into destroy, repair insertion, and EV/charging conversion.",
        "",
        "Instance rule: three-shift 50c/75c probes first; 100c is not used for this diagnostic.",
        "",
        "## Evidence Used",
        "",
    ]
    for item in EVIDENCE_ITEMS:
        lines.append(f"- `{item['source']}`: {item['resetp_implication']}")
    lines.extend(
        [
            "",
            "## Gate Detail",
            "",
            "```json",
            json.dumps(gate, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Repair Summary",
            "",
        ]
    )
    for row in summary.get("repair_summary", []):
        lines.append(
            "- {role}: destroy_changed={changed}/{rows}, options={options}, default_changed={default}, alt_changed={alt}, alt_improving={improve}, best_alt_rel={rel:.4f}%".format(
                role=row["bundle_role"],
                changed=int(row["destroy_changed_rows"]),
                rows=int(row["rows"]),
                options=int(row["repair_options_total"]),
                default=int(row["default_changed_rows"]),
                alt=int(row["alternative_changed_count"]),
                improve=int(row["alternative_improving_count"]),
                rel=float(row["best_alternative_relative_percent"]),
            )
        )
    lines.extend(["", "## Charging Summary", ""])
    for row in summary.get("charging_summary", []):
        lines.append(
            "- {role}: initial_cv_mean={cv:.2f}, initial_ev_mean={ev:.2f}, charging_actions_mean={actions:.2f}, cv_to_ev_candidates={cand}, changed={changed}, feasible={feasible}, best_ev_rel={rel:.4f}%".format(
                role=row["bundle_role"],
                cv=float(row["initial_cv_routes_mean"]),
                ev=float(row["initial_ev_routes_mean"]),
                actions=float(row["initial_charging_actions_mean"]),
                cand=int(row["cv_to_ev_candidate_count"]),
                changed=int(row["changed_cv_to_ev_count"]),
                feasible=int(row["feasible_cv_to_ev_count"]),
                rel=float(row["best_cv_to_ev_relative_percent"]),
            )
        )
    if repair_rows:
        lines.extend(["", "## First Repair Rows", ""])
        for row in repair_rows[: min(8, len(repair_rows))]:
            lines.append(
                "- {bundle}/{seed}/{destroy}: removed={removed}, options={options}, default_changed={default}, alt_changed={alt}, best_alt_rel={rel:.4f}%".format(
                    bundle=row["bundle_name"],
                    seed=row["seed"],
                    destroy=row["destroy_id"],
                    removed=row["destroy_removed_count"],
                    options=row["repair_options_total"],
                    default=row["default_changed_any"],
                    alt=row["alternative_changed_count"],
                    rel=float(row["best_alternative_relative_percent"]),
                )
            )
    if charging_rows:
        lines.extend(["", "## First Charging Rows", ""])
        for row in charging_rows[: min(6, len(charging_rows))]:
            lines.append(
                "- {bundle}/{seed}: CV={cv}, EV={ev}, charging_actions={actions}, cv_to_ev_candidates={cand}, changed={changed}, best_ev_rel={rel:.4f}%".format(
                    bundle=row["bundle_name"],
                    seed=row["seed"],
                    cv=row["initial_cv_routes"],
                    ev=row["initial_ev_routes"],
                    actions=row["initial_charging_actions"],
                    cand=row["cv_to_ev_candidate_count"],
                    changed=row["changed_cv_to_ev_count"],
                    rel=float(row["best_cv_to_ev_relative_percent"]),
                )
            )
    lines.extend(
        [
            "",
            "## Decision Meaning",
            "",
            _decision_text(str(gate.get("status", "UNKNOWN"))),
        ]
    )
    return "\n".join(lines) + "\n"


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _probe_destroy_repair(
    *,
    bundle: BundleSpec,
    seed: int,
    destroy_id: str,
    destroyed: AlnsState,
    state: AlnsState,
    initial_obj: float,
    remove_count_q: int,
    initial_mode: str,
    max_removed_customers: int,
    max_alternatives_per_destroy: int,
) -> dict[str, Any]:
    removed_customers = list(destroyed.removed_customers)
    option_stats = _repair_option_stats(
        destroyed=destroyed,
        removed_customers=removed_customers,
        max_removed_customers=max_removed_customers,
    )
    default_changed: dict[str, bool] = {}
    default_obj: dict[str, float] = {}
    for mode in REPAIR_MODES:
        repaired = repair_removed_customers(
            destroyed.solution,
            removed_customers,
            destroyed.context,
            destroyed.policy,
            mode=mode,
            allow_new_route=destroyed.allow_new_route_repair,
        )
        if repaired is None:
            default_changed[mode] = False
            default_obj[mode] = math.inf
            continue
        default_changed[mode] = _solution_changed(state.solution, repaired)
        default_obj[mode] = _score_if_feasible(repaired, destroyed.context)
    alternatives = _alternative_repair_candidates(
        initial_solution=state.solution,
        destroyed=destroyed,
        removed_customers=removed_customers,
        max_removed_customers=max_removed_customers,
        max_alternatives_per_destroy=max_alternatives_per_destroy,
    )
    changed_alts = [item for item in alternatives if item["changed"]]
    improving_alts = [item for item in changed_alts if float(item["objective"]) < float(initial_obj) - 1e-9]
    best_alt_obj = min((float(item["objective"]) for item in changed_alts), default=math.inf)
    best_alt_rel = -math.inf if not math.isfinite(best_alt_obj) else paired_relative_percent(candidate_cost=best_alt_obj, baseline_cost=initial_obj)
    return {
        "bundle_role": bundle.bundle_role,
        "bundle_name": bundle.bundle_name,
        "bundle_path": bundle.bundle_path,
        "seed": int(seed),
        "initial_mode": str(initial_mode),
        "driver_python_executable": sys.executable,
        "driver_numpy_version": np.__version__,
        "destroy_id": str(destroy_id),
        "remove_count_q": int(remove_count_q),
        "initial_obj": float(initial_obj),
        "destroy_changed": bool(_solution_changed(state.solution, destroyed.solution)),
        "destroy_removed_count": int(len(removed_customers)),
        "destroy_allow_new_route_repair": bool(destroyed.allow_new_route_repair),
        "repair_options_total": int(option_stats["repair_options_total"]),
        "repair_option_customer_count": int(option_stats["repair_option_customer_count"]),
        "repair_option_route_targets": int(option_stats["repair_option_route_targets"]),
        "repair_option_positions": int(option_stats["repair_option_positions"]),
        "new_route_option_count": int(option_stats["new_route_option_count"]),
        "ev_option_count": int(option_stats["ev_option_count"]),
        "option_score_spread": float(option_stats["option_score_spread"]),
        "default_greedy_changed": bool(default_changed["greedy"]),
        "default_regret2_changed": bool(default_changed["regret2"]),
        "default_regret3_changed": bool(default_changed["regret3"]),
        "default_changed_any": bool(any(default_changed.values())),
        "default_greedy_obj": float(default_obj["greedy"]),
        "default_regret2_obj": float(default_obj["regret2"]),
        "default_regret3_obj": float(default_obj["regret3"]),
        "alternative_candidate_count": int(len(alternatives)),
        "alternative_changed_count": int(len(changed_alts)),
        "alternative_improving_count": int(len(improving_alts)),
        "best_alternative_obj": float(best_alt_obj),
        "best_alternative_relative_percent": float(best_alt_rel),
    }


def _probe_charging_landing_point(
    *,
    bundle: BundleSpec,
    seed: int,
    state: AlnsState,
    initial_obj: float,
    initial_mode: str,
    elapsed_seconds: float,
) -> dict[str, Any]:
    rng = np.random.default_rng(int(seed) * 99991 + 17)
    candidates = _try_cv_to_ev_candidates(state, rng)
    feasible = []
    changed = []
    for candidate in candidates:
        violations = check_solution(candidate, state.context.instance, state.context.prices)
        if not violations:
            feasible.append(candidate)
        if _solution_changed(state.solution, candidate):
            changed.append(candidate)
    scored = [(candidate, _score_if_feasible(candidate, state.context)) for candidate in feasible if _solution_changed(state.solution, candidate)]
    best_obj = min((obj for _, obj in scored), default=math.inf)
    best_rel = -math.inf if not math.isfinite(best_obj) else paired_relative_percent(candidate_cost=best_obj, baseline_cost=initial_obj)
    return {
        "bundle_role": bundle.bundle_role,
        "bundle_name": bundle.bundle_name,
        "bundle_path": bundle.bundle_path,
        "seed": int(seed),
        "initial_mode": str(initial_mode),
        "driver_python_executable": sys.executable,
        "driver_numpy_version": np.__version__,
        "initial_obj": float(initial_obj),
        "initial_cv_routes": int(sum(1 for route in state.solution.routes if route.vehicle_type.lower() == "cv")),
        "initial_ev_routes": int(sum(1 for route in state.solution.routes if route.vehicle_type.lower() == "ev")),
        "initial_charging_actions": int(len(state.solution.charging_actions)),
        "cv_to_ev_candidate_count": int(len(candidates)),
        "changed_cv_to_ev_count": int(len(changed)),
        "feasible_cv_to_ev_count": int(len(feasible)),
        "best_cv_to_ev_obj": float(best_obj),
        "best_cv_to_ev_relative_percent": float(best_rel),
        "elapsed_seconds": float(elapsed_seconds),
    }


def _repair_option_stats(
    *,
    destroyed: AlnsState,
    removed_customers: list[str],
    max_removed_customers: int,
) -> dict[str, Any]:
    option_count = 0
    route_targets: set[str] = set()
    positions: set[tuple[str, int | None]] = set()
    new_route_count = 0
    ev_count = 0
    scores: list[float] = []
    option_customer_count = 0
    for customer_id in removed_customers[: max(0, int(max_removed_customers))]:
        options = enumerate_feasible_insertions(
            destroyed.solution,
            customer_id,
            destroyed.context,
            destroyed.policy,
            allow_new_route=destroyed.allow_new_route_repair,
        )
        if options:
            option_customer_count += 1
        option_count += len(options)
        for option in options:
            route_targets.add("new" if option.route_idx is None else f"route:{option.route_idx}")
            positions.add((str(customer_id), option.position))
            new_route_count += int(bool(option.opened_new_route))
            ev_count += int(option.vehicle_type.lower() == "ev")
            scores.append(float(option.score))
    spread = 0.0 if len(scores) < 2 else max(scores) - min(scores)
    return {
        "repair_options_total": option_count,
        "repair_option_customer_count": option_customer_count,
        "repair_option_route_targets": len(route_targets),
        "repair_option_positions": len(positions),
        "new_route_option_count": new_route_count,
        "ev_option_count": ev_count,
        "option_score_spread": spread,
    }


def _alternative_repair_candidates(
    *,
    initial_solution: Solution,
    destroyed: AlnsState,
    removed_customers: list[str],
    max_removed_customers: int,
    max_alternatives_per_destroy: int,
) -> list[dict[str, Any]]:
    alternatives: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    limit = max(0, int(max_alternatives_per_destroy))
    if limit == 0:
        return alternatives
    for customer_id in removed_customers[: max(0, int(max_removed_customers))]:
        options = enumerate_feasible_insertions(
            destroyed.solution,
            customer_id,
            destroyed.context,
            destroyed.policy,
            allow_new_route=destroyed.allow_new_route_repair,
        )
        selected = _selected_option_indices(len(options))
        for rank in selected:
            if len(alternatives) >= limit:
                return alternatives
            option = options[rank]
            remaining = [item for item in removed_customers if item != customer_id]
            if remaining:
                repaired = repair_removed_customers(
                    option.solution,
                    remaining,
                    destroyed.context,
                    destroyed.policy,
                    mode="greedy",
                    allow_new_route=destroyed.allow_new_route_repair,
                )
            else:
                repaired = option.solution
            if repaired is None:
                continue
            key = _solution_signature(repaired)
            if key in seen:
                continue
            seen.add(key)
            violations = check_solution(repaired, destroyed.context.instance, destroyed.context.prices)
            if violations:
                continue
            objective = score_candidate(repaired, destroyed.context)
            alternatives.append(
                {
                    "customer_id": customer_id,
                    "option_rank": int(rank),
                    "objective": float(objective),
                    "changed": bool(_solution_changed(initial_solution, repaired)),
                }
            )
    return alternatives


def _score_if_feasible(solution: Solution, context: EvaluationContext) -> float:
    violations = check_solution(solution, context.instance, context.prices)
    if violations:
        return math.inf
    try:
        return float(score_candidate(solution, context))
    except Exception:
        return math.inf


def _selected_option_indices(count: int) -> list[int]:
    if count <= 0:
        return []
    candidates = [0]
    if count > 1:
        candidates.append(1)
    if count > 2:
        candidates.append(count - 1)
    return sorted(set(candidates))


def _customer_count(solution: Solution, context: EvaluationContext) -> int:
    node_types = {node.node_id: node.node_type.lower() for node in context.instance.nodes}
    return sum(1 for route in solution.routes for node_id in route.node_sequence if node_types.get(node_id) == "c")


def _solution_signature(solution: Solution) -> tuple[Any, ...]:
    return (
        tuple((route.vehicle_id, route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence)) for route in solution.routes),
        tuple(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.charge_start_second), 6),
                round(float(action.energy_kwh), 6),
            )
            for action in solution.charging_actions
        ),
    )


def _selected_bundles(bundle_names: set[str] | None) -> list[BundleSpec]:
    specs = [BundleSpec(**row) for row in threeshift_probe_bundles()]
    if bundle_names:
        specs = [spec for spec in specs if spec.bundle_name in bundle_names]
    return specs


def _initial_mode_flags(initial_mode: str) -> tuple[bool, bool]:
    mode = str(initial_mode)
    if mode == "worker_cv":
        return False, False
    if mode == "ev_optional":
        return True, False
    if mode == "ev_required":
        return True, True
    raise ValueError(f"unknown initial_mode: {initial_mode}")


def _parse_seeds(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _decision_text(status: str) -> str:
    if status.startswith("PASS_REPAIR"):
        return "Repair can create changed feasible candidates. The next implementation step should target a deeper repair/insertion action, then require it to beat best static meta before training is trusted."
    if status == "PASS_CHARGING_LANDING_POINT":
        return "EV/charging conversion has a feasible landing point. The next implementation step should expose charging strategy only after repair headroom is separated from EV retagging."
    if status == "HALT_DESTROY_NO_REMOVAL":
        return "The current destroy layer is not removing customers on these probes, so repair learning has no input."
    if status == "HALT_REPAIR_NO_OPTIONS":
        return "Destroy removes customers, but the existing repair layer cannot find feasible insertion options."
    return "No changed-candidate control surface was found in this diagnostic. Do not train another same-shape DR policy until candidate generation itself is redesigned."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pilot13 changed-candidate headroom diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="Run no-training changed-candidate diagnostics")
    probe.add_argument("--output-dir", type=Path, required=True)
    probe.add_argument("--seeds", default="1")
    probe.add_argument("--bundle-names", default="")
    probe.add_argument("--remove-fraction", type=float, default=0.40)
    probe.add_argument("--max-removed-customers", type=int, default=5)
    probe.add_argument("--max-alternatives-per-destroy", type=int, default=8)
    probe.add_argument("--include-route-elimination", action="store_true")
    probe.add_argument("--initial-mode", choices=("worker_cv", "ev_optional", "ev_required"), default="worker_cv")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "probe":
        bundle_names = {item.strip() for item in args.bundle_names.split(",") if item.strip()} or None
        summary = run_probe(
            output_dir=args.output_dir,
            seeds=_parse_seeds(args.seeds),
            bundle_names=bundle_names,
            remove_fraction=args.remove_fraction,
            max_removed_customers=args.max_removed_customers,
            max_alternatives_per_destroy=args.max_alternatives_per_destroy,
            include_route_elimination=args.include_route_elimination,
            initial_mode=args.initial_mode,
        )
        print(json.dumps({"gate": summary["gate"], "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))
        return 0
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
