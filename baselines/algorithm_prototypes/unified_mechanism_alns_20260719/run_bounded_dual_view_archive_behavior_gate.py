"""Run the pre-registered 0/1/2/5 bounded-archive behaviour gate."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bounded_dual_view_archive_solver as solver  # noqa: E402
from contextual_expert_fixtures import (  # noqa: E402
    PLATEAU_BUNDLE,
    PRICES_280,
    RESPONSIBILITY_BUNDLE,
    all_cv_plateau,
    fast_nonbinding_solution,
    plateau_solution,
    responsibility_binding_solution,
    responsibility_nonbinding_solution,
)
from fast_mechanism_completion import (  # noqa: E402
    apply_fast_route_local_completion,
)
from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_winner_kernel,
)
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import (  # noqa: E402
    EvalBudget,
    EvaluationContext,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
    exact_cross_depot_responsibility_decode,
)


BUDGETS = (0, 1, 2, 5)
SEED = 1
FIXTURE = (
    REPO
    / "models/data_bundle/generated_instances/verify_20251113"
)
PRICES = PRICES_280
WORKER_SENTINEL = "RESET_BOUNDED_ARCHIVE_WORKER="
OUTPUT_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "archive_candidates.json",
    "solution_witnesses.json",
    "report.md",
)
PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)
SOURCE_FILES = (
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "run_bounded_dual_view_archive_behavior_gate.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "bounded_dual_view_archive_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "test_bounded_dual_view_archive_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "fast_mechanism_completion.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "terminal_completion.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "contextual_expert_fixtures.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "initial_pool.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "prototype.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v4_mechanism_alns_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v5_carbon_retiming_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v6_monotone_mechanism_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v7_responsibility_solver.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/"
    "construction.py",
    "solver/src/setp_solver/algorithms/resetp_alns/runtime/"
    "budgeted_scoring.py",
    "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    "docs/handoff/bounded_dual_view_archive_contract_20260719.md",
)
FIXED_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "SETP_E3_STRICT_MULTITRIP": "0",
    "SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC": "0",
    "SETP_E2_ALNS_CHECKPOINT_PATH": "",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HERE / "bounded_dual_view_archive_behavior_gate",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    _freeze_environment()
    if args.worker:
        return _worker_main()

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(
            f"behaviour output directory must not exist: {output_dir}"
        )
    _require_clean_sources()
    source_hashes_before = {
        path: _sha256(REPO / path) for path in SOURCE_FILES
    }
    protected_hashes_before = {
        path: _sha256(REPO / path) for path in PROTECTED_FILES
    }
    input_hashes_before = _input_hashes(
        (FIXTURE, PLATEAU_BUNDLE, RESPONSIBILITY_BUNDLE)
    )
    shared_start = _shared_start(FIXTURE)
    started = time.perf_counter()

    payloads: dict[tuple[str, int, bool], dict[str, Any]] = {}
    for budget in BUDGETS:
        for capture in (False, True):
            payloads[("capture", budget, capture)] = _invoke_worker(
                {
                    "mode": "capture",
                    "bundle": str(FIXTURE.resolve()),
                    "budget": budget,
                    "enabled": capture,
                    "shared_start": asdict(shared_start),
                }
            )
        for enabled in (False, True):
            payloads[("archive", budget, enabled)] = _invoke_worker(
                {
                    "mode": "archive",
                    "bundle": str(FIXTURE.resolve()),
                    "budget": budget,
                    "enabled": enabled,
                    "shared_start": asdict(shared_start),
                }
            )

    component_probes = _component_probes()
    rows = _raw_rows(payloads)
    witnesses: dict[str, Any] = {}
    _add_witness(
        witnesses,
        shared_start,
        {"kind": "shared_start", "budgets": list(BUDGETS)},
    )
    archive_candidates: dict[str, Any] = {}
    parent_audits: dict[str, Any] = {}
    for budget in BUDGETS:
        for enabled in (False, True):
            payload = payloads[("archive", budget, enabled)]
            label = f"B{budget}:{'enabled' if enabled else 'control'}"
            activity = dict(payload["activity"])
            parent_audit = _parent_archive_audit(FIXTURE, payload)
            parent_audits[label] = parent_audit
            archive_candidates[label] = {
                "prescore_rows": activity.get("prescore_rows", []),
                "archive_entries": activity.get("archive_entries", []),
                "parent_audit": parent_audit,
            }
            _add_witness(
                witnesses,
                _solution_from_payload(payload["final_solution"]),
                {
                    "kind": "solver_final",
                    "budget": budget,
                    "archive_enabled": enabled,
                },
            )
            for entry_index, entry in enumerate(
                activity.get("archive_entries", [])
            ):
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["raw_solution_snapshot"]
                    ),
                    {
                        "kind": "archive_raw",
                        "budget": budget,
                        "archive_enabled": enabled,
                        "entry_index": entry_index,
                    },
                )
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["completed_solution_snapshot"]
                    ),
                    {
                        "kind": "archive_completed",
                        "budget": budget,
                        "archive_enabled": enabled,
                        "entry_index": entry_index,
                    },
                )
            for entry_index, entry in enumerate(
                activity.get("prescore_rows", [])
            ):
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["raw_solution_snapshot"]
                    ),
                    {
                        "kind": "prescore_raw",
                        "budget": budget,
                        "archive_enabled": enabled,
                        "entry_index": entry_index,
                    },
                )
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["fast_completed_solution_snapshot"]
                    ),
                    {
                        "kind": "prescore_fast_completed",
                        "budget": budget,
                        "archive_enabled": enabled,
                        "entry_index": entry_index,
                    },
                )

    failures = _gate_failures(
        payloads,
        component_probes,
        parent_audits,
    )
    drift_failures = _drift_failures(
        source_hashes_before,
        protected_hashes_before,
        input_hashes_before,
    )
    failures.extend(drift_failures)
    decision = {
        "schema_version": "resetp.bounded-dual-view-archive-behaviour.v1",
        "verdict": (
            "PASS_BOUNDED_DUAL_VIEW_ARCHIVE_BEHAVIOUR"
            if not failures
            else "FAIL_BOUNDED_DUAL_VIEW_ARCHIVE_BEHAVIOUR"
        ),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "strength_claim_allowed": False,
        "old_three_instance_gate_allowed": not failures,
        "fresh_d3_allowed": False,
        "stage2_activated": False,
    }
    metadata = {
        "schema_version": "resetp.bounded-dual-view-archive-behaviour.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "budgets": list(BUDGETS),
        "seed": SEED,
        "fixture": _relative(FIXTURE),
        "fixed_environment": dict(FIXED_ENVIRONMENT),
        "prices": asdict(PRICES),
        "prescore_capacity": solver.PRESCORE_CAPACITY,
        "archive_capacity": solver.ARCHIVE_CAPACITY,
        "source_hashes": source_hashes_before,
        "protected_file_hashes": protected_hashes_before,
        "input_hashes": input_hashes_before,
        "elapsed_seconds": time.perf_counter() - started,
        "python": sys.version,
        "platform": platform.platform(),
        "claim_boundary": (
            "Behaviour, accounting, replay, non-feedback, and monotone "
            "envelope only. No algorithm-strength or stage-two claim."
        ),
        "prior_execution_incidents": [
            {
                "attempt": 1,
                "status": "INVALID_UNCOMMITTED_BEHAVIOUR_ATTEMPT",
                "reason": (
                    "The archive-disabled control still performed cheap "
                    "historical prescoring. It did not affect search or final "
                    "cost, but it inflated control wall time and could bias a "
                    "later wall-clock ratio in favour of the candidate. The "
                    "attempt was retained under an explicit invalid directory; "
                    "the control was changed to skip all prescoring and this "
                    "gate was rerun before any strength test."
                ),
            },
            {
                "attempt": 2,
                "status": "INVALID_UNCOMMITTED_BEHAVIOUR_ATTEMPT",
                "reason": (
                    "The solver counted only the selected terminal branch's "
                    "route-local work and omitted the raw-search independent "
                    "replay from positive-budget post-search totals. The gate "
                    "also did not independently reconstruct all ledgers. The "
                    "attempt was retained under an explicit invalid directory; "
                    "no strength instance was run."
                ),
            },
            {
                "attempt": 3,
                "status": "NO_OUTPUT_PRODUCED",
                "reason": (
                    "The zero-budget activity payload omitted explicit zero "
                    "values for three route-local ledger fields. Summary "
                    "normalization raised KeyError before the output directory "
                    "was created. Only the missing zero fields were added; no "
                    "strength instance was run."
                ),
            },
        ],
        "formal_search_allowed": False,
        "stage2_activated": False,
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    _write_csv(output_dir / "raw_runs.csv", rows)
    _write_json(output_dir / "decision.json", decision)
    _write_json(
        output_dir / "archive_candidates.json",
        {
            "runs": archive_candidates,
            "component_probes": component_probes,
        },
    )
    _write_json(output_dir / "solution_witnesses.json", witnesses)
    _write_json(output_dir / "metadata.json", metadata)
    _atomic_text(output_dir / "report.md", _report(decision, rows))
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            name: _sha256(output_dir / name)
            for name in OUTPUT_FILES
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def _worker_main() -> int:
    request = json.loads(sys.stdin.read())
    mode = str(request["mode"])
    bundle_dir = Path(request["bundle"])
    budget = int(request["budget"])
    enabled = bool(request["enabled"])
    start = _solution_from_payload(request["shared_start"])
    start_exact = solver._exact_solution_hash(start)
    start_cost = independent_cost(bundle_dir, start, PRICES)
    _require_finite("worker_start_cost", start_cost)
    worker_started = time.perf_counter()
    if mode == "capture":
        raw = run_winner_kernel(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=SEED,
                eval_budget=budget,
                max_runtime_seconds=3600.0,
                require_charging_signal=False,
                capture_best_solutions=enabled,
            ),
            initial_solution=start,
            prices=PRICES,
        )
        final = raw["best_solution"]
        score_counts = dict(
            raw.get("operator_counts", {}).get("score_counts", {})
        )
        selector = dict(
            raw.get("operator_counts", {}).get("selector", {})
        )
        history = list(raw.get("history", []))
        scalar_history = [
            {
                key: row[key]
                for key in ("eval", "best_cost", "best_obj", "operator")
            }
            for row in history
        ]
        stable_counts = {
            key: value
            for key, value in raw.get("operator_counts", {}).items()
            if key not in {
                "timing",
                "candidate_trace",
                "final_rng_state",
            }
        }
        recomputed = independent_cost(bundle_dir, final, PRICES)
        _require_finite(
            "capture_worker_cost",
            float(raw["best_cost"]),
            float(recomputed),
        )
        payload = {
            "mode": mode,
            "enabled": enabled,
            "budget": budget,
            "start_exact_signature": start_exact,
            "start_cost": float(start_cost),
            "evaluations": int(raw["evaluations"]),
            "candidate_scores": int(raw["candidate_scores"]),
            "actual_moves": int(raw["actual_moves"]),
            "score_counts": score_counts,
            "selector_selection_count": int(
                selector.get("selection_count", 0)
            ),
            "selector_selection_count_closed": bool(
                selector.get("selection_count_closed", False)
            ),
            "raw_cost": float(raw["best_cost"]),
            "worker_recomputed_cost": float(recomputed),
            "raw_algorithm_signature": solution_signature_hash(final),
            "raw_exact_signature": solver._exact_solution_hash(final),
            "raw_skeleton_signature": solver._route_skeleton_hash(
                final,
                load_search_bundle(bundle_dir).instance,
            ),
            "history_length": len(history),
            "snapshot_row_count": sum(
                int("solution_snapshot" in row) for row in history
            ),
            "history_fingerprint": solver._sha_json(scalar_history),
            "stable_operator_fingerprint": solver._sha_json(
                stable_counts
            ),
            "main_rng_final_state_sha256": str(
                selector.get("main_rng_final_state_sha256", "")
            ),
            "selector_rng_final_state_sha256": str(
                selector.get("selector_rng_final_state_sha256", "")
            ),
            "final_solution": asdict(final),
        }
    elif mode == "archive":
        result = solver.run_bounded_dual_view_archive_alns(
            bundle_dir,
            seed=SEED,
            config=solver.BoundedDualViewArchiveConfig(
                total_eval_budget=budget,
                enable_archive=enabled,
                runtime_cap_seconds=3600.0,
            ),
            prices=PRICES,
            initial_solution=start,
        )
        final = result.best_solution
        violations = check_solution(
            final,
            load_search_bundle(bundle_dir).instance,
            PRICES,
        )
        recomputed = independent_cost(bundle_dir, final, PRICES)
        _require_finite(
            "archive_worker_cost",
            float(result.best_cost),
            float(recomputed),
        )
        payload = {
            "mode": mode,
            "enabled": enabled,
            "budget": budget,
            "start_exact_signature": start_exact,
            "start_cost": float(start_cost),
            "algorithm": result.algorithm,
            "evaluations": int(result.evaluations),
            "claimed_final_cost": float(result.best_cost),
            "worker_recomputed_cost": float(recomputed),
            "worker_feasible": bool(result.feasible and not violations),
            "worker_violation_count": len(violations),
            "final_algorithm_signature": solution_signature_hash(final),
            "final_exact_signature": solver._exact_solution_hash(final),
            "final_solution": asdict(final),
            "activity": result.mechanism_activity,
        }
    else:
        raise ValueError(f"unknown worker mode: {mode}")
    payload["worker_elapsed_seconds"] = (
        time.perf_counter() - worker_started
    )
    print(
        WORKER_SENTINEL
        + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
    )
    return 0


def _shared_start(bundle_dir: Path) -> Solution:
    bundle = load_search_bundle(bundle_dir)
    start = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    start = annotate_cross_site_services(
        start,
        infer_customer_home_depots(bundle.instance),
    )
    violations = check_solution(start, bundle.instance, PRICES)
    if violations:
        raise RuntimeError(
            f"shared behaviour start is infeasible: {violations[:8]}"
        )
    independent_cost(bundle_dir, start, PRICES)
    return start


def _component_probes() -> dict[str, Any]:
    plateau_bundle = load_search_bundle(PLATEAU_BUNDLE)
    probes: dict[str, Any] = {}
    for label, source in (
        ("fleet_charge_binding", all_cv_plateau()),
        ("carbon_time_binding", plateau_solution()),
    ):
        source_cost = independent_cost(
            PLATEAU_BUNDLE,
            source,
            PRICES_280,
        )
        outcome = apply_fast_route_local_completion(
            source,
            plateau_bundle,
            prices=PRICES_280,
        )
        completed_cost = independent_cost(
            PLATEAU_BUNDLE,
            outcome.solution,
            PRICES_280,
        )
        expected = (
            source_cost
            + float(outcome.activity["projected_objective_delta"])
        )
        _require_finite(
            label,
            source_cost,
            completed_cost,
            expected,
        )
        probes[label] = {
            "source_cost": float(source_cost),
            "completed_cost": float(completed_cost),
            "changed": bool(outcome.changed),
            "cost_closure_error": abs(completed_cost - expected),
            "source_exact_signature": solver._exact_solution_hash(
                source
            ),
            "completed_exact_signature": solver._exact_solution_hash(
                outcome.solution
            ),
            "activity": outcome.activity,
        }

    fixed_point_source = fast_nonbinding_solution()
    fixed_point = apply_fast_route_local_completion(
        fixed_point_source,
        plateau_bundle,
        prices=PRICES_280,
    )
    probes["fast_nonbinding_fixed_point"] = {
        "changed": bool(fixed_point.changed),
        "source_exact_signature": solver._exact_solution_hash(
            fixed_point_source
        ),
        "completed_exact_signature": solver._exact_solution_hash(
            fixed_point.solution
        ),
        "cost_difference": (
            independent_cost(
                PLATEAU_BUNDLE,
                fixed_point.solution,
                PRICES_280,
            )
            - independent_cost(
                PLATEAU_BUNDLE,
                fixed_point_source,
                PRICES_280,
            )
        ),
        "activity": fixed_point.activity,
    }

    responsibility_bundle = load_search_bundle(RESPONSIBILITY_BUNDLE)
    owners = infer_customer_home_depots(
        responsibility_bundle.instance
    )
    responsibility_context = EvaluationContext(
        responsibility_bundle.instance,
        responsibility_bundle.carbon_profile,
        prices=PRICES_280,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    for label, source in (
        ("responsibility_binding", responsibility_binding_solution()),
        (
            "responsibility_nonbinding",
            responsibility_nonbinding_solution(),
        ),
    ):
        source = annotate_cross_site_services(source, owners)
        source_cost = independent_cost(
            RESPONSIBILITY_BUNDLE,
            source,
            PRICES_280,
        )
        completed, completed_cost, activity = (
            exact_cross_depot_responsibility_decode(
                source,
                responsibility_context,
                incumbent_objective=source_cost,
                owners=owners,
            )
        )
        replayed = independent_cost(
            RESPONSIBILITY_BUNDLE,
            completed,
            PRICES_280,
        )
        _require_finite(
            label,
            source_cost,
            completed_cost,
            replayed,
        )
        violations = check_solution(
            completed,
            responsibility_bundle.instance,
            PRICES_280,
        )
        probes[label] = {
            "source_cost": float(source_cost),
            "completed_cost": float(completed_cost),
            "replayed_cost": float(replayed),
            "feasible": not violations,
            "source_exact_signature": solver._exact_solution_hash(
                source
            ),
            "completed_exact_signature": solver._exact_solution_hash(
                completed
            ),
            "activity": activity,
        }
    return probes


def _parent_archive_audit(
    bundle_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    bundle = load_search_bundle(bundle_dir)
    activity = dict(payload["activity"])
    final = _solution_from_payload(payload["final_solution"])
    final_cost = independent_cost(bundle_dir, final, PRICES)
    if not _all_finite(
        final_cost,
        payload["claimed_final_cost"],
        payload["worker_recomputed_cost"],
    ):
        failures.append("nonfinite_final")
    if abs(final_cost - float(payload["claimed_final_cost"])) > 1.0e-7:
        failures.append("parent_final_cost")
    if solver._exact_solution_hash(final) != payload[
        "final_exact_signature"
    ]:
        failures.append("parent_final_signature")
    if check_solution(final, bundle.instance, PRICES):
        failures.append("parent_final_infeasible")

    prescore_replays = 0
    for index, row in enumerate(activity.get("prescore_rows", [])):
        raw = _solution_from_payload(row["raw_solution_snapshot"])
        fast = _solution_from_payload(
            row["fast_completed_solution_snapshot"]
        )
        raw_cost = independent_cost(bundle_dir, raw, PRICES)
        fast_cost = independent_cost(bundle_dir, fast, PRICES)
        prescore_replays += 2
        expected = (
            raw_cost
            + float(
                row["fast_activity"]["projected_objective_delta"]
            )
        )
        if not _all_finite(
            raw_cost,
            fast_cost,
            expected,
            row["raw_cost"],
            row["fast_completed_cost"],
        ):
            failures.append(f"prescore:{index}:nonfinite")
        if abs(raw_cost - float(row["raw_cost"])) > 1.0e-7:
            failures.append(f"prescore:{index}:raw_cost")
        if (
            abs(fast_cost - float(row["fast_completed_cost"]))
            > 1.0e-7
        ):
            failures.append(f"prescore:{index}:fast_cost")
        if abs(fast_cost - expected) > 1.0e-7:
            failures.append(f"prescore:{index}:closure")
        if solver._exact_solution_hash(raw) != row["exact_signature"]:
            failures.append(f"prescore:{index}:raw_signature")
        if (
            solver._exact_solution_hash(fast)
            != row["fast_completed_exact_signature"]
        ):
            failures.append(f"prescore:{index}:fast_signature")
        if (
            solver._route_skeleton_hash(raw, bundle.instance)
            != row["skeleton_signature"]
        ):
            failures.append(f"prescore:{index}:skeleton")
        if check_solution(raw, bundle.instance, PRICES):
            failures.append(f"prescore:{index}:raw_infeasible")
        if check_solution(fast, bundle.instance, PRICES):
            failures.append(f"prescore:{index}:fast_infeasible")

    archive_replays = 0
    entries = list(activity.get("archive_entries", []))
    for index, row in enumerate(entries):
        raw = _solution_from_payload(row["raw_solution_snapshot"])
        completed = _solution_from_payload(
            row["completed_solution_snapshot"]
        )
        raw_cost = independent_cost(bundle_dir, raw, PRICES)
        completed_cost = independent_cost(
            bundle_dir,
            completed,
            PRICES,
        )
        archive_replays += 2
        if not _all_finite(
            raw_cost,
            completed_cost,
            row["raw_cost"],
            row["completed_cost"],
        ):
            failures.append(f"archive:{index}:nonfinite")
        if abs(raw_cost - float(row["raw_cost"])) > 1.0e-7:
            failures.append(f"archive:{index}:raw_cost")
        if (
            abs(completed_cost - float(row["completed_cost"]))
            > 1.0e-7
        ):
            failures.append(f"archive:{index}:completed_cost")
        if solver._exact_solution_hash(raw) != row["exact_signature"]:
            failures.append(f"archive:{index}:raw_signature")
        if (
            solver._exact_solution_hash(completed)
            != row["completed_exact_signature"]
        ):
            failures.append(f"archive:{index}:completed_signature")
        if (
            solver._route_skeleton_hash(raw, bundle.instance)
            != row["skeleton_signature"]
        ):
            failures.append(f"archive:{index}:skeleton")
        if check_solution(raw, bundle.instance, PRICES):
            failures.append(f"archive:{index}:raw_infeasible")
        if check_solution(completed, bundle.instance, PRICES):
            failures.append(f"archive:{index}:completed_infeasible")
        if completed_cost > raw_cost + solver.TOL:
            failures.append(f"archive:{index}:terminal_regression")

    if int(payload["budget"]) > 0:
        ordinary = [
            row for row in entries if row["is_main_search_final"]
        ]
        if len(ordinary) != 1:
            failures.append("ordinary_count")
        else:
            if (
                ordinary[0]["exact_signature"]
                != activity["raw_search_exact_signature"]
            ):
                failures.append("ordinary_raw_not_search_final")
            if (
                ordinary[0]["completed_exact_signature"]
                != activity[
                    "ordinary_final_completed_exact_signature"
                ]
            ):
                failures.append("ordinary_completed_signature")

        ranked = sorted(
            activity.get("prescore_rows", []),
            key=lambda row: (
                float(row["fast_completed_cost"]),
                float(row["raw_cost"]),
                -int(row["eval"]),
                str(row["skeleton_signature"]),
                str(row["exact_signature"]),
            ),
        )
        expected_nonfinal = (
            [
                str(row["exact_signature"])
                for row in ranked[: solver.ARCHIVE_CAPACITY - 1]
            ]
            if bool(payload["enabled"])
            else []
        )
        actual_nonfinal = [
            str(row["exact_signature"])
            for row in entries
            if not row["is_main_search_final"]
        ]
        if actual_nonfinal != expected_nonfinal:
            failures.append("archive_ranking")

        selected = min(
            entries,
            key=lambda row: (
                float(row["completed_cost"]),
                0 if row["is_main_search_final"] else 1,
                -int(row["eval"]),
                str(row["skeleton_signature"]),
                str(row["completed_exact_signature"]),
            ),
        )
        if (
            selected["completed_exact_signature"]
            != payload["final_exact_signature"]
        ):
            failures.append("selected_branch")
    elif entries:
        failures.append("zero_budget_archive_entries")

    return {
        "passed": not failures,
        "failures": failures,
        "parent_final_replays": 1,
        "parent_prescore_solution_replays": prescore_replays,
        "parent_archive_solution_replays": archive_replays,
    }


def _gate_failures(
    payloads: dict[tuple[str, int, bool], dict[str, Any]],
    probes: dict[str, Any],
    parent_audits: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    for budget in BUDGETS:
        off = payloads[("capture", budget, False)]
        on = payloads[("capture", budget, True)]
        tag = f"capture:B{budget}"
        for field in (
            "start_exact_signature",
            "start_cost",
            "evaluations",
            "candidate_scores",
            "actual_moves",
            "score_counts",
            "selector_selection_count",
            "selector_selection_count_closed",
            "raw_cost",
            "worker_recomputed_cost",
            "raw_algorithm_signature",
            "raw_exact_signature",
            "raw_skeleton_signature",
            "history_length",
            "history_fingerprint",
            "stable_operator_fingerprint",
            "main_rng_final_state_sha256",
            "selector_rng_final_state_sha256",
        ):
            if off[field] != on[field]:
                failures.append(f"{tag}:{field}_drift")
        if not _all_finite(
            on["start_cost"],
            on["raw_cost"],
            on["worker_recomputed_cost"],
            on["worker_elapsed_seconds"],
        ):
            failures.append(f"{tag}:nonfinite")
        if int(off["snapshot_row_count"]) != 0:
            failures.append(f"{tag}:capture_off_has_snapshots")
        if int(on["snapshot_row_count"]) != int(on["history_length"]):
            failures.append(f"{tag}:capture_on_missing_snapshots")
        if not (
            int(on["evaluations"])
            == int(on["candidate_scores"])
            == int(on["actual_moves"])
            == int(on["selector_selection_count"])
            == budget
        ):
            failures.append(f"{tag}:budget_ledger")
        if abs(
            float(on["raw_cost"])
            - float(on["worker_recomputed_cost"])
        ) > 1.0e-7:
            failures.append(f"{tag}:objective_replay")
        if budget == 0:
            if (
                on["start_exact_signature"] != on["raw_exact_signature"]
                or abs(
                    float(on["start_cost"]) - float(on["raw_cost"])
                )
                > 1.0e-7
            ):
                failures.append(f"{tag}:zero_budget_changed")

        control = payloads[("archive", budget, False)]
        candidate = payloads[("archive", budget, True)]
        left = dict(control["activity"])
        right = dict(candidate["activity"])
        tag = f"archive:B{budget}"
        for field in (
            "start_exact_signature",
            "evaluations",
        ):
            if control[field] != candidate[field]:
                failures.append(f"{tag}:{field}_drift")
        for field in (
            "raw_search_cost",
            "raw_search_signature",
            "raw_search_exact_signature",
            "raw_search_skeleton_signature",
            "main_search_history_fingerprint",
            "main_search_operator_fingerprint",
            "main_rng_final_state_sha256",
            "selector_rng_final_state_sha256",
            "candidate_scores",
            "actual_moves",
            "score_counts",
        ):
            if left[field] != right[field]:
                failures.append(f"{tag}:{field}_drift")
        for activity, arm in ((left, "control"), (right, "candidate")):
            prefix = f"{tag}:{arm}"
            score_counts = dict(activity["score_counts"])
            candidate_channels = sum(
                int(value)
                for key, value in score_counts.items()
                if str(key).startswith("candidate_channel:")
            )
            if not (
                int(activity["complete_search_candidate_evaluations"])
                == int(activity["candidate_scores"])
                == int(activity["actual_moves"])
                == int(activity["generic_candidate_evaluations"])
                == int(score_counts.get("candidate", 0))
                == int(candidate_channels)
                == budget
            ):
                failures.append(f"{prefix}:budget_ledger")
            if int(activity["mechanism_candidate_evaluations"]) != 0:
                failures.append(f"{prefix}:hidden_mechanism_candidate")
            if bool(activity["archive_feedback_into_search"]):
                failures.append(f"{prefix}:archive_feedback")
            if bool(activity["second_route_search_started"]):
                failures.append(f"{prefix}:second_route_search")
            prescore_rows = list(activity.get("prescore_rows", []))
            archive_entries = list(
                activity.get("archive_entries", [])
            )
            if not (
                int(activity["prescore_candidate_count"])
                == int(activity["prescore_reference_replays"])
                == len(prescore_rows)
            ):
                failures.append(f"{prefix}:prescore_ledger")
            if int(activity["prescore_candidate_count"]) > (
                solver.PRESCORE_CAPACITY
            ):
                failures.append(f"{prefix}:prescore_capacity")
            if not (
                int(activity["archive_entry_count"])
                == int(activity["archive_completion_call_count"])
                == len(archive_entries)
            ):
                failures.append(f"{prefix}:archive_call_ledger")
            if int(activity["archive_entry_count"]) > (
                solver.ARCHIVE_CAPACITY
            ):
                failures.append(f"{prefix}:archive_capacity")
            terminal_replays = sum(
                int(
                    row["activity"].get(
                        "full_solution_replays",
                        0,
                    )
                )
                for row in archive_entries
            )
            if terminal_replays != int(
                activity["archive_completion_reference_replays"]
            ):
                failures.append(f"{prefix}:terminal_replay_ledger")
            expected_independent = 1 if budget == 0 else 2
            if not (
                int(activity["raw_search_independent_replays"]) == 1
                and int(
                    activity["selected_final_independent_replays"]
                )
                == (0 if budget == 0 else 1)
                and int(activity["independent_final_replays"])
                == expected_independent
            ):
                failures.append(f"{prefix}:independent_replay_ledger")
            if int(activity["post_search_full_solution_replays"]) != (
                len(prescore_rows)
                + terminal_replays
                + expected_independent
            ):
                failures.append(f"{prefix}:post_search_replay_ledger")

            route_exact = sum(
                int(
                    row["activity"].get(
                        "route_local_exact_evaluations",
                        0,
                    )
                )
                for row in archive_entries
            )
            route_proxy = sum(
                int(
                    row["activity"].get(
                        "route_proxy_evaluations",
                        0,
                    )
                )
                for row in archive_entries
            ) + sum(
                int(
                    row["fast_activity"].get(
                        "route_proxy_evaluations",
                        0,
                    )
                )
                for row in prescore_rows
            )
            route_schedule = sum(
                int(
                    row["activity"].get(
                        "route_local_schedule_evaluations",
                        0,
                    )
                )
                for row in archive_entries
            ) + sum(
                int(
                    row["fast_activity"].get(
                        "route_local_schedule_evaluations",
                        0,
                    )
                )
                for row in prescore_rows
            )
            feasibility = sum(
                int(
                    row["activity"].get(
                        "full_feasibility_checks",
                        0,
                    )
                )
                for row in archive_entries
            ) + sum(
                int(
                    row["fast_activity"].get(
                        "full_feasibility_checks",
                        0,
                    )
                )
                for row in prescore_rows
            )
            if route_exact != int(
                activity["route_local_exact_evaluations"]
            ):
                failures.append(f"{prefix}:route_exact_ledger")
            if route_proxy != int(activity["route_proxy_evaluations"]):
                failures.append(f"{prefix}:route_proxy_ledger")
            if route_schedule != int(
                activity["route_local_schedule_evaluations"]
            ):
                failures.append(f"{prefix}:route_schedule_ledger")
            if feasibility != int(
                activity["mechanism_feasibility_checks"]
            ):
                failures.append(f"{prefix}:feasibility_ledger")

            skeletons = [
                row["skeleton_signature"]
                for row in archive_entries
            ]
            if len(skeletons) != len(set(skeletons)):
                failures.append(f"{prefix}:duplicate_skeleton")
            ordinary = [
                row
                for row in archive_entries
                if row["is_main_search_final"]
            ]
            if budget > 0:
                if len(ordinary) != 1:
                    failures.append(f"{prefix}:ordinary_count")
                elif (
                    ordinary[0]["exact_signature"]
                    != activity["raw_search_exact_signature"]
                ):
                    failures.append(
                        f"{prefix}:ordinary_raw_signature"
                    )
            elif ordinary:
                failures.append(f"{prefix}:zero_budget_ordinary")
            if not _all_finite(
                control["start_cost"],
                activity["raw_search_cost"],
                activity["ordinary_final_completed_cost"],
                activity["selected_completed_cost"],
                (
                    payloads[("archive", budget, arm == "candidate")][
                        "claimed_final_cost"
                    ]
                ),
            ):
                failures.append(f"{prefix}:nonfinite")
            audit_label = (
                f"B{budget}:"
                f"{'enabled' if arm == 'candidate' else 'control'}"
            )
            if not bool(parent_audits[audit_label]["passed"]):
                failures.extend(
                    f"{prefix}:parent:{failure}"
                    for failure in parent_audits[audit_label]["failures"]
                )
        if int(left["prescore_candidate_count"]) != 0:
            failures.append(f"{tag}:control_performed_prescore")
        if budget == 0:
            if any(
                int(right[field]) != 0
                for field in (
                    "prescore_candidate_count",
                    "archive_entry_count",
                    "archive_completion_reference_replays",
                )
            ):
                failures.append(f"{tag}:zero_budget_mechanism_work")
            for payload, activity, arm in (
                (control, left, "control"),
                (candidate, right, "candidate"),
            ):
                if not (
                    payload["start_exact_signature"]
                    == activity["raw_search_exact_signature"]
                    == payload["final_exact_signature"]
                    and abs(
                        float(payload["start_cost"])
                        - float(payload["claimed_final_cost"])
                    )
                    <= 1.0e-7
                    and int(
                        activity["post_search_full_solution_replays"]
                    )
                    == 1
                ):
                    failures.append(f"{tag}:{arm}:zero_budget_changed")
        else:
            if not (
                bool(left["ordinary_final_forced"])
                and bool(right["ordinary_final_forced"])
            ):
                failures.append(f"{tag}:ordinary_final_not_forced")
            if int(left["archive_entry_count"]) != 1:
                failures.append(f"{tag}:control_not_single_terminal")
            if abs(
                float(left["selected_completed_cost"])
                - float(right["ordinary_final_completed_cost"])
            ) > 1.0e-7:
                failures.append(f"{tag}:ordinary_branch_drift")
            left_rows = [
                row
                for row in left["archive_entries"]
                if row["is_main_search_final"]
            ]
            right_rows = [
                row
                for row in right["archive_entries"]
                if row["is_main_search_final"]
            ]
            if len(left_rows) == 1 and len(right_rows) == 1:
                left_ordinary = left_rows[0]
                right_ordinary = right_rows[0]
                if not (
                    left_ordinary["exact_signature"]
                    == right_ordinary["exact_signature"]
                    == left["raw_search_exact_signature"]
                    == right["raw_search_exact_signature"]
                ):
                    failures.append(
                        f"{tag}:ordinary_raw_signature_drift"
                    )
                if not (
                    left_ordinary["completed_exact_signature"]
                    == right_ordinary["completed_exact_signature"]
                    == control["final_exact_signature"]
                ):
                    failures.append(
                        f"{tag}:ordinary_completed_signature_drift"
                    )
            if (
                float(candidate["claimed_final_cost"])
                > float(right["ordinary_final_completed_cost"]) + 1.0e-9
            ):
                failures.append(f"{tag}:monotone_envelope")
        for payload, arm in (
            (control, "control"),
            (candidate, "candidate"),
        ):
            if not bool(payload["worker_feasible"]):
                failures.append(f"{tag}:{arm}_infeasible")
            if abs(
                float(payload["claimed_final_cost"])
                - float(payload["worker_recomputed_cost"])
            ) > 1.0e-7:
                failures.append(f"{tag}:{arm}_objective_replay")

    for label in ("fleet_charge_binding", "carbon_time_binding"):
        row = probes[label]
        if not _all_finite(
            row["source_cost"],
            row["completed_cost"],
            row["cost_closure_error"],
        ):
            failures.append(f"component:{label}:nonfinite")
        if not bool(row["changed"]):
            failures.append(f"component:{label}:not_changed")
        if (
            float(row["completed_cost"])
            > float(row["source_cost"]) + solver.TOL
        ):
            failures.append(f"component:{label}:regressed")
        if float(row["cost_closure_error"]) > 1.0e-7:
            failures.append(f"component:{label}:closure")
    fleet = probes["fleet_charge_binding"]
    if int(
        fleet["activity"]["joint"].get("exact_decoder_updates", 0)
    ) < 1:
        failures.append("component:fleet_charge_binding:joint_inactive")
    carbon = probes["carbon_time_binding"]
    if int(
        carbon["activity"]["joint"].get("exact_decoder_updates", 0)
    ) != 0:
        failures.append("component:carbon_time_binding:joint_masquerade")
    if int(
        carbon["activity"]["carbon"].get("exact_decoder_updates", 0)
    ) < 1:
        failures.append("component:carbon_time_binding:carbon_inactive")

    fixed = probes["fast_nonbinding_fixed_point"]
    if not _all_finite(fixed["cost_difference"]):
        failures.append("component:fast_nonbinding:nonfinite")
    if bool(fixed["changed"]):
        failures.append("component:fast_nonbinding:changed")
    if (
        fixed["source_exact_signature"]
        != fixed["completed_exact_signature"]
    ):
        failures.append("component:fast_nonbinding:signature")
    if abs(float(fixed["cost_difference"])) > 1.0e-7:
        failures.append("component:fast_nonbinding:cost")

    responsibility = probes["responsibility_binding"]
    if not _all_finite(
        responsibility["source_cost"],
        responsibility["completed_cost"],
        responsibility["replayed_cost"],
    ):
        failures.append("component:responsibility_binding:nonfinite")
    if not bool(responsibility["feasible"]):
        failures.append("component:responsibility_binding:infeasible")
    if int(
        responsibility["activity"].get(
            "exact_decoder_updates",
            0,
        )
    ) < 1:
        failures.append("component:responsibility_binding:no_update")
    if (
        float(responsibility["completed_cost"])
        > float(responsibility["source_cost"]) + solver.TOL
    ):
        failures.append("component:responsibility_binding:regressed")

    nonbinding = probes["responsibility_nonbinding"]
    if not _all_finite(
        nonbinding["source_cost"],
        nonbinding["completed_cost"],
        nonbinding["replayed_cost"],
    ):
        failures.append("component:responsibility_nonbinding:nonfinite")
    if not bool(nonbinding["feasible"]):
        failures.append("component:responsibility_nonbinding:infeasible")
    if (
        float(nonbinding["completed_cost"])
        > float(nonbinding["source_cost"]) + solver.TOL
    ):
        failures.append("component:responsibility_nonbinding:regressed")
    if (
        nonbinding["source_exact_signature"]
        != nonbinding["completed_exact_signature"]
        or abs(
            float(nonbinding["source_cost"])
            - float(nonbinding["completed_cost"])
        )
        > 1.0e-7
        or int(
            nonbinding["activity"].get("exact_decoder_updates", 0)
        )
        != 0
        or list(nonbinding["activity"].get("accepted_moves", []))
    ):
        failures.append("component:responsibility_nonbinding:changed")
    return failures


def _raw_rows(
    payloads: dict[tuple[str, int, bool], dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (mode, budget, enabled), payload in sorted(
        payloads.items(),
        key=lambda item: (
            item[0][1],
            item[0][0],
            item[0][2],
        ),
    ):
        if mode == "capture":
            rows.append(
                {
                    "mode": mode,
                    "budget": budget,
                    "enabled": enabled,
                    "start_cost": payload["start_cost"],
                    "evaluations": payload["evaluations"],
                    "candidate_scores": payload["candidate_scores"],
                    "actual_moves": payload["actual_moves"],
                    "raw_cost": payload["raw_cost"],
                    "final_cost": payload["raw_cost"],
                    "raw_exact_signature": payload[
                        "raw_exact_signature"
                    ],
                    "raw_skeleton_signature": payload[
                        "raw_skeleton_signature"
                    ],
                    "history_fingerprint": payload[
                        "history_fingerprint"
                    ],
                    "operator_fingerprint": payload[
                        "stable_operator_fingerprint"
                    ],
                    "main_rng_fingerprint": payload[
                        "main_rng_final_state_sha256"
                    ],
                    "selector_rng_fingerprint": payload[
                        "selector_rng_final_state_sha256"
                    ],
                    "prescore_count": 0,
                    "prescore_reference_replays": 0,
                    "archive_count": 0,
                    "archive_completion_call_count": 0,
                    "archive_completion_reference_replays": 0,
                    "raw_search_independent_replays": 0,
                    "selected_final_independent_replays": 0,
                    "independent_final_replays": 0,
                    "post_search_full_solution_replays": 0,
                    "route_local_exact_evaluations": 0,
                    "route_proxy_evaluations": 0,
                    "route_local_schedule_evaluations": 0,
                    "mechanism_feasibility_checks": 0,
                    "mechanism_candidate_evaluations": 0,
                    "worker_recomputed_cost": payload[
                        "worker_recomputed_cost"
                    ],
                    "worker_elapsed_seconds": payload[
                        "worker_elapsed_seconds"
                    ],
                }
            )
        else:
            activity = dict(payload["activity"])
            rows.append(
                {
                    "mode": mode,
                    "budget": budget,
                    "enabled": enabled,
                    "start_cost": payload["start_cost"],
                    "evaluations": payload["evaluations"],
                    "candidate_scores": activity["candidate_scores"],
                    "actual_moves": activity["actual_moves"],
                    "raw_cost": activity["raw_search_cost"],
                    "final_cost": payload["claimed_final_cost"],
                    "raw_exact_signature": activity[
                        "raw_search_exact_signature"
                    ],
                    "raw_skeleton_signature": activity[
                        "raw_search_skeleton_signature"
                    ],
                    "history_fingerprint": activity[
                        "main_search_history_fingerprint"
                    ],
                    "operator_fingerprint": activity[
                        "main_search_operator_fingerprint"
                    ],
                    "main_rng_fingerprint": activity[
                        "main_rng_final_state_sha256"
                    ],
                    "selector_rng_fingerprint": activity[
                        "selector_rng_final_state_sha256"
                    ],
                    "prescore_count": activity[
                        "prescore_candidate_count"
                    ],
                    "prescore_reference_replays": activity[
                        "prescore_reference_replays"
                    ],
                    "archive_count": activity["archive_entry_count"],
                    "archive_completion_call_count": activity[
                        "archive_completion_call_count"
                    ],
                    "archive_completion_reference_replays": activity[
                        "archive_completion_reference_replays"
                    ],
                    "raw_search_independent_replays": activity[
                        "raw_search_independent_replays"
                    ],
                    "selected_final_independent_replays": activity[
                        "selected_final_independent_replays"
                    ],
                    "independent_final_replays": activity[
                        "independent_final_replays"
                    ],
                    "post_search_full_solution_replays": activity[
                        "post_search_full_solution_replays"
                    ],
                    "route_local_exact_evaluations": activity[
                        "route_local_exact_evaluations"
                    ],
                    "route_proxy_evaluations": activity[
                        "route_proxy_evaluations"
                    ],
                    "route_local_schedule_evaluations": activity[
                        "route_local_schedule_evaluations"
                    ],
                    "mechanism_feasibility_checks": activity[
                        "mechanism_feasibility_checks"
                    ],
                    "mechanism_candidate_evaluations": activity[
                        "mechanism_candidate_evaluations"
                    ],
                    "worker_recomputed_cost": payload[
                        "worker_recomputed_cost"
                    ],
                    "worker_elapsed_seconds": payload[
                        "worker_elapsed_seconds"
                    ],
                }
            )
    return rows


def _report(decision: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 有界双视图档案行为门",
        "",
        f"判定：`{decision['verdict']}`",
        "",
        "本门只检查路线搜索不受档案影响、预算与复算闭合、档案容量、普通终局"
        "保底和三个现有机制夹具。它不证明算法更强。",
        "",
        "| 模式 | B | 开启 | 完整候选 | 原始成本 | 最终成本 | 预筛数 | 终局数 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {mode} | {budget} | {enabled} | {evaluations} | "
            "{raw_cost:.9f} | {final_cost:.9f} | {prescore_count} | "
            "{archive_count} |".format(**row)
        )
    if decision["failures"]:
        lines.extend(["", "失败项："])
        lines.extend(f"- `{failure}`" for failure in decision["failures"])
    return "\n".join(lines) + "\n"


def _invoke_worker(request: dict[str, Any]) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.update(FIXED_ENVIRONMENT)
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        cwd=REPO,
        env=environment,
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "bounded archive worker failed: "
            f"rc={completed.returncode}\n{completed.stderr[-4000:]}"
        )
    lines = [
        row
        for row in completed.stdout.splitlines()
        if row.startswith(WORKER_SENTINEL)
    ]
    if len(lines) != 1:
        raise RuntimeError(
            "bounded archive worker must emit exactly one sentinel: "
            f"{len(lines)}"
        )
    return json.loads(lines[0][len(WORKER_SENTINEL) :])


def _require_clean_sources() -> None:
    failures: list[str] = []
    for path in SOURCE_FILES:
        if not (REPO / path).is_file():
            failures.append(f"missing:{path}")
            continue
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        ).returncode == 0
        if not tracked:
            failures.append(f"untracked:{path}")
            continue
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--", path],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
        if status:
            failures.append(f"dirty:{path}")
    if failures:
        raise RuntimeError(
            "behaviour-gate sources must be committed first: "
            + ", ".join(failures)
        )


def _drift_failures(
    source_hashes: dict[str, str],
    protected_hashes: dict[str, str],
    input_hashes: dict[str, str],
) -> list[str]:
    failures: list[str] = []
    for path, expected in source_hashes.items():
        if _sha256(REPO / path) != expected:
            failures.append(f"source_drift:{path}")
    for path, expected in protected_hashes.items():
        if _sha256(REPO / path) != expected:
            failures.append(f"protected_drift:{path}")
    current_inputs = _input_hashes(
        (FIXTURE, PLATEAU_BUNDLE, RESPONSIBILITY_BUNDLE)
    )
    if current_inputs != input_hashes:
        failures.append("input_drift")
    return failures


def _input_hashes(bundle_dirs: tuple[Path, ...]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for bundle_dir in bundle_dirs:
        for path in sorted(
            item for item in bundle_dir.rglob("*") if item.is_file()
        ):
            hashes[_relative(path)] = _sha256(path)
    return hashes


def _add_witness(
    witnesses: dict[str, Any],
    solution: Solution,
    metadata: dict[str, Any],
) -> None:
    exact = solver._exact_solution_hash(solution)
    snapshot = asdict(solution)
    if exact in witnesses and witnesses[exact]["solution"] != snapshot:
        raise RuntimeError(
            "full-content witness hash collision with unequal payloads"
        )
    row = witnesses.setdefault(
        exact,
        {
            "full_content_sha256": exact,
            "algorithm_signature": solution_signature_hash(solution),
            "solution": snapshot,
            "uses": [],
        },
    )
    row["uses"].append(metadata)


def _solution_from_payload(payload: dict[str, Any]) -> Solution:
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
        charging_actions=[
            ChargingAction(
                str(row["vehicle_id"]),
                str(row["station_id"]),
                float(row["energy_kwh"]),
                float(row["occupancy_minutes"]),
                float(row["charge_start_second"]),
                int(row.get("charge_day_offset", 0)),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                str(row["customer_id"]),
                str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def _freeze_environment() -> None:
    for key, value in FIXED_ENVIRONMENT.items():
        os.environ[key] = value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("refusing to write an empty behaviour CSV")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
    )


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO.resolve()))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _all_finite(*values: Any) -> bool:
    try:
        return all(math.isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        return False


def _require_finite(label: str, *values: Any) -> None:
    if not _all_finite(*values):
        raise RuntimeError(f"{label} contains a non-finite value: {values}")


if __name__ == "__main__":
    raise SystemExit(main())
