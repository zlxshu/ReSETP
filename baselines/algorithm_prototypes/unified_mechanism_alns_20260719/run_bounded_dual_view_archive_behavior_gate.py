"""Run the pre-registered 0/1/2/5 bounded-archive behaviour gate."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
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
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)
from terminal_completion import apply_terminal_completion  # noqa: E402
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
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
    for budget in BUDGETS:
        for enabled in (False, True):
            payload = payloads[("archive", budget, enabled)]
            label = f"B{budget}:{'enabled' if enabled else 'control'}"
            activity = dict(payload["activity"])
            archive_candidates[label] = {
                "prescore_rows": activity.get("prescore_rows", []),
                "archive_entries": activity.get("archive_entries", []),
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

    failures = _gate_failures(payloads, component_probes)
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
        payload = {
            "mode": mode,
            "enabled": enabled,
            "budget": budget,
            "start_exact_signature": start_exact,
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
            "worker_recomputed_cost": float(
                independent_cost(bundle_dir, final, PRICES)
            ),
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
        payload = {
            "mode": mode,
            "enabled": enabled,
            "budget": budget,
            "start_exact_signature": start_exact,
            "algorithm": result.algorithm,
            "evaluations": int(result.evaluations),
            "claimed_final_cost": float(result.best_cost),
            "worker_recomputed_cost": float(
                independent_cost(bundle_dir, final, PRICES)
            ),
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
        probes[label] = {
            "source_cost": float(source_cost),
            "completed_cost": float(completed_cost),
            "changed": bool(outcome.changed),
            "cost_closure_error": abs(completed_cost - expected),
            "activity": outcome.activity,
        }

    fixed_point_source = apply_fast_route_local_completion(
        all_cv_plateau(),
        plateau_bundle,
        prices=PRICES_280,
    ).solution
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

    for label, source in (
        ("responsibility_binding", responsibility_binding_solution()),
        (
            "responsibility_nonbinding",
            responsibility_nonbinding_solution(),
        ),
    ):
        outcome = apply_terminal_completion(
            RESPONSIBILITY_BUNDLE,
            source,
            prices=PRICES_280,
        )
        probes[label] = {
            "source_cost": float(outcome.source_cost),
            "completed_cost": float(outcome.cost),
            "feasible": bool(outcome.feasible),
            "selected_branch": str(outcome.selected_branch),
            "activity": outcome.activity,
        }
    return probes


def _gate_failures(
    payloads: dict[tuple[str, int, bool], dict[str, Any]],
    probes: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    for budget in BUDGETS:
        off = payloads[("capture", budget, False)]
        on = payloads[("capture", budget, True)]
        tag = f"capture:B{budget}"
        for field in (
            "start_exact_signature",
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
            if not (
                int(activity["complete_search_candidate_evaluations"])
                == int(activity["candidate_scores"])
                == int(activity["actual_moves"])
                == budget
            ):
                failures.append(f"{tag}:{arm}_budget_ledger")
            if int(activity["mechanism_candidate_evaluations"]) != 0:
                failures.append(f"{tag}:{arm}_hidden_mechanism_candidate")
            if bool(activity["archive_feedback_into_search"]):
                failures.append(f"{tag}:{arm}_archive_feedback")
            if bool(activity["second_route_search_started"]):
                failures.append(f"{tag}:{arm}_second_route_search")
            if int(activity["prescore_candidate_count"]) > (
                solver.PRESCORE_CAPACITY
            ):
                failures.append(f"{tag}:{arm}_prescore_capacity")
            if int(activity["archive_entry_count"]) > (
                solver.ARCHIVE_CAPACITY
            ):
                failures.append(f"{tag}:{arm}_archive_capacity")
            skeletons = [
                row["skeleton_signature"]
                for row in activity.get("archive_entries", [])
            ]
            if len(skeletons) != len(set(skeletons)):
                failures.append(f"{tag}:{arm}_duplicate_skeleton")
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
        else:
            if not bool(right["ordinary_final_forced"]):
                failures.append(f"{tag}:ordinary_final_not_forced")
            if int(left["archive_entry_count"]) != 1:
                failures.append(f"{tag}:control_not_single_terminal")
            if abs(
                float(left["selected_completed_cost"])
                - float(right["ordinary_final_completed_cost"])
            ) > 1.0e-7:
                failures.append(f"{tag}:ordinary_branch_drift")
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
        if not bool(row["changed"]):
            failures.append(f"component:{label}:not_changed")
        if (
            float(row["completed_cost"])
            > float(row["source_cost"]) + solver.TOL
        ):
            failures.append(f"component:{label}:regressed")
        if float(row["cost_closure_error"]) > 1.0e-7:
            failures.append(f"component:{label}:closure")
    fixed = probes["fast_nonbinding_fixed_point"]
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
    if not bool(responsibility["feasible"]):
        failures.append("component:responsibility_binding:infeasible")
    if int(
        responsibility["activity"]["responsibility"].get(
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
    if not bool(nonbinding["feasible"]):
        failures.append("component:responsibility_nonbinding:infeasible")
    if (
        float(nonbinding["completed_cost"])
        > float(nonbinding["source_cost"]) + solver.TOL
    ):
        failures.append("component:responsibility_nonbinding:regressed")
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
                    "archive_count": 0,
                    "mechanism_candidate_evaluations": 0,
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
                    "archive_count": activity["archive_entry_count"],
                    "mechanism_candidate_evaluations": activity[
                        "mechanism_candidate_evaluations"
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
    line = next(
        (
            row
            for row in reversed(completed.stdout.splitlines())
            if row.startswith(WORKER_SENTINEL)
        ),
        None,
    )
    if line is None:
        raise RuntimeError("bounded archive worker emitted no sentinel")
    return json.loads(line[len(WORKER_SENTINEL) :])


def _require_clean_sources() -> None:
    failures: list[str] = []
    for path in SOURCE_FILES:
        if not (REPO / path).is_file():
            failures.append(f"missing:{path}")
            continue
        unstaged = subprocess.run(
            ["git", "diff", "--quiet", "--", path],
            cwd=REPO,
            check=False,
        ).returncode
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", path],
            cwd=REPO,
            check=False,
        ).returncode
        if unstaged or staged:
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
    row = witnesses.setdefault(
        exact,
        {
            "full_content_sha256": exact,
            "algorithm_signature": solution_signature_hash(solution),
            "solution": asdict(solution),
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


if __name__ == "__main__":
    raise SystemExit(main())
