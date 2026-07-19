"""Run the zero-search behavior gate for electrification relocate-resize."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback
from typing import Any
import unittest
from unittest.mock import patch


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

import electrification_relocate_resize_solver as solver  # noqa: E402
import prototype as prototype_module  # noqa: E402
from prototype import independent_cost  # noqa: E402
import v4_mechanism_alns_solver as v4_module  # noqa: E402
import v5_carbon_retiming_solver as v5_module  # noqa: E402
import v6_monotone_mechanism_solver as v6_module  # noqa: E402
import v7_responsibility_solver as v7_module  # noqa: E402
import setp_solver.algorithms.resetp_alns.kernel.winner as winner_module  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
ARCHIVE = (
    REPO
    / "models/data_bundle/generated_instances/"
    "L-main_size_preserving_v2_archive_20260710"
)
WITNESSES = HERE / (
    "contextual_expert_p1_training_gate/solution_witnesses.json"
)
INPUT_MANIFEST = HERE / (
    "electrification_relocate_resize_input_manifest_20260719.json"
)
TEST_MANIFEST = HERE / (
    "electrification_relocate_resize_zero_search_tests_20260719.json"
)
CANONICAL_OUTPUT = (
    HERE / "electrification_relocate_resize_behavior_gate"
)
SCENARIOS = (
    (
        "binding_saved_v7_20c",
        "L-main-threeshift-20c-01",
        "control",
    ),
    (
        "nonbinding_saved_v7_25c_all_ev",
        "L-main-threeshift-25c-01",
        "control",
    ),
)
PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
)
STATIC_SOURCE_FILES = (
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "run_electrification_relocate_resize_behavior_gate.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "electrification_relocate_resize_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "test_electrification_relocate_resize_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "contextual_expert_fixtures.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "electrification_relocate_resize_input_manifest_20260719.json",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "electrification_relocate_resize_zero_search_tests_20260719.json",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "terminal_completion.py",
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
    "docs/handoff/electrification_relocate_resize_contract_20260719.md",
    "docs/handoff/algorithm_source_and_license_register_20260719.md",
)
TEST_COMMAND = (
    "python3",
    "-m",
    "unittest",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "test_electrification_relocate_resize_solver.py",
)
TEST_SOURCE_FILES = (
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "electrification_relocate_resize_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "run_electrification_relocate_resize_behavior_gate.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "test_electrification_relocate_resize_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "contextual_expert_fixtures.py",
    "docs/handoff/electrification_relocate_resize_contract_20260719.md",
)
EXPECTED_TEST_COVERAGE = (
    "duplicate JSON keys are rejected before witness selection",
    "duplicate witness appends a use without overwriting content",
    "top-level list reordering changes ordered full hash but not semantic hash",
    "one-trillionth floating-point change creates a distinct witness",
    "candidate exists but fails the joint cost-and-electrification test and returns the exact source",
    "saved all-EV solution is an exact no-op",
    "declared adjacent transfer is proved before and after terminal completion",
    "formal entry rejects every non-frozen configuration",
    "the behavior-time guard blocks a mature ALNS route-search entrypoint",
)
ARTIFACT_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "solution_witnesses.json",
    "report.md",
    "appledouble_seal.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    _freeze_environment()
    _require_expected_module_origins()
    source_files = _all_source_files()
    _require_clean_sources(source_files)
    _require_registered_inputs()
    test_recheck = _require_test_manifest()
    _require_clean_sources(source_files)
    _require_registered_inputs()
    if not _test_manifest_valid():
        raise RuntimeError(
            "zero-search tests changed a frozen source or manifest"
        )
    source_hashes = {
        path: _sha256(REPO / path) for path in source_files
    }
    protected_hashes = {
        path: _sha256(REPO / path) for path in PROTECTED_FILES
    }
    input_hashes = _input_hashes()
    frozen_git_head = _git("rev-parse", "HEAD")
    source_solutions = {
        scenario: _saved_final(instance, arm)
        for scenario, instance, arm in SCENARIOS
    }
    preflight = {
        "passed": True,
        "output_written": False,
        "scoring_started": False,
        "route_search_started": False,
        "source_file_count": len(source_hashes),
        "protected_file_count": len(protected_hashes),
        "input_file_count": len(input_hashes),
        "scenario_source_hashes": {
            scenario: _runner_full_content_hash(solution)
            for scenario, solution in source_solutions.items()
        },
        "git_head": frozen_git_head,
        "registered_input_manifest_sha256": _sha256(INPUT_MANIFEST),
        "zero_search_test_manifest_sha256": _sha256(TEST_MANIFEST),
        "zero_search_test_runtime_recheck": test_recheck,
    }
    if args.preflight_only:
        if CANONICAL_OUTPUT.exists():
            raise FileExistsError(
                f"behavior output already exists: {CANONICAL_OUTPUT}"
            )
        print(json.dumps(preflight, indent=2, sort_keys=True))
        return 0

    try:
        CANONICAL_OUTPUT.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(
            "behavior gate is one-shot and its canonical output exists"
        ) from exc

    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    all_route_search_attempts: list[str] = []
    try:
        for scenario, instance, arm in SCENARIOS:
            bundle_dir = ARCHIVE / instance
            source = source_solutions[scenario]
            with _forbid_route_search(
                all_route_search_attempts
            ) as source_validation_guard:
                source_cost = independent_cost(
                    bundle_dir,
                    source,
                    PRICES,
                )
                source_violations = check_solution(
                    source,
                    _load_instance(bundle_dir),
                    PRICES,
                )
            if source_violations:
                raise RuntimeError(
                    f"{scenario} source infeasible: {source_violations[:8]}"
                )
            _add_witness(
                witnesses,
                source,
                {
                    "scenario": scenario,
                    "kind": "source",
                    "instance": instance,
                    "arm": arm,
                },
            )
            with _forbid_route_search(
                all_route_search_attempts
            ) as route_search_guard:
                result = solver.apply_electrification_relocate_resize(
                    bundle_dir,
                    source,
                    prices=PRICES,
                )
            with _forbid_route_search(
                all_route_search_attempts
            ) as final_validation_guard:
                recomputed = independent_cost(
                    bundle_dir,
                    result.solution,
                    PRICES,
                )
                violations = check_solution(
                    result.solution,
                    _load_instance(bundle_dir),
                    PRICES,
                )
            if abs(recomputed - result.cost) > 1.0e-7:
                raise RuntimeError(
                    f"{scenario} independent cost mismatch: "
                    f"{result.cost} != {recomputed}"
                )
            _add_witness(
                witnesses,
                result.solution,
                {
                    "scenario": scenario,
                    "kind": "final",
                    "instance": instance,
                    "arm": arm,
                },
            )
            activity = result.activity
            with _forbid_route_search(
                all_route_search_attempts
            ) as proof_search_guard:
                proof_audit = _audit_accepted_move_proofs(
                    activity,
                    bundle_dir,
                    PRICES,
                )
            ledger_audit = _audit_activity_ledgers(activity)
            for summary in activity["round_summaries"]:
                snapshot = summary.get(
                    "counterfactual_solution_snapshot"
                )
                if snapshot is not None:
                    _add_witness(
                        witnesses,
                        _solution_from_payload(snapshot),
                        {
                            "scenario": scenario,
                            "kind": "source_only_counterfactual",
                            "round": int(summary["round"]),
                            "instance": instance,
                        },
                    )
            for move in activity["accepted_moves"]:
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        move["source_solution_snapshot"]
                    ),
                    {
                        "scenario": scenario,
                        "kind": "accepted_round_source",
                        "round": int(move["round"]),
                        "instance": instance,
                    },
                )
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        move["neutral_solution_snapshot"]
                    ),
                    {
                        "scenario": scenario,
                        "kind": "accepted_neutral",
                        "round": int(move["round"]),
                        "instance": instance,
                    },
                )
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        move["completed_solution_snapshot"]
                    ),
                    {
                        "scenario": scenario,
                        "kind": "accepted_completed",
                        "round": int(move["round"]),
                        "instance": instance,
                    },
                )
            improvement = (
                (source_cost - recomputed) / source_cost * 100.0
                if source_cost
                else 0.0
            )
            row = {
                "scenario": scenario,
                "instance": instance,
                "source_arm": arm,
                "source_cost": float(source_cost),
                "final_cost": float(recomputed),
                "objective_delta": float(recomputed - source_cost),
                "improvement_percent": float(improvement),
                "source_cv_routes": int(
                    activity["source_cv_route_count"]
                ),
                "final_cv_routes": int(
                    activity["final_cv_route_count"]
                ),
                "cv_route_reduction": int(
                    activity["source_cv_route_count"]
                    - activity["final_cv_route_count"]
                ),
                "changed": bool(result.changed),
                "feasible": bool(not violations and result.feasible),
                "enumerated_moves": int(
                    activity["enumerated_moves"]
                ),
                "neutral_feasible_moves": int(
                    activity["neutral_feasible_moves"]
                ),
                "unique_neutral_moves": int(
                    activity["unique_neutral_moves"]
                ),
                "prescored_moves": int(activity["prescored_moves"]),
                "prescore_selected_moves": int(
                    activity["prescore_selected_moves"]
                ),
                "terminal_completion_calls": int(
                    activity["terminal_completion_calls"]
                ),
                "counterfactual_terminal_completion_calls": int(
                    activity[
                        "counterfactual_terminal_completion_calls"
                    ]
                ),
                "total_terminal_completion_calls": int(
                    activity["total_terminal_completion_calls"]
                ),
                "terminal_full_solution_replays": int(
                    activity["terminal_full_solution_replays"]
                ),
                "terminal_route_local_exact_evaluations": int(
                    activity[
                        "terminal_route_local_exact_evaluations"
                    ]
                ),
                "terminal_route_proxy_evaluations": int(
                    activity["terminal_route_proxy_evaluations"]
                ),
                "terminal_route_local_schedule_evaluations": int(
                    activity[
                        "terminal_route_local_schedule_evaluations"
                    ]
                ),
                "terminal_feasibility_checks": int(
                    activity["terminal_feasibility_checks"]
                ),
                "counterfactual_full_solution_replays": int(
                    activity[
                        "counterfactual_full_solution_replays"
                    ]
                ),
                "counterfactual_feasibility_checks": int(
                    activity["counterfactual_feasibility_checks"]
                ),
                "counterfactual_independent_replays": int(
                    activity["counterfactual_independent_replays"]
                ),
                "exact_candidate_independent_replays": int(
                    activity["exact_candidate_independent_replays"]
                ),
                "exact_candidate_feasibility_checks": int(
                    activity["exact_candidate_feasibility_checks"]
                ),
                "source_full_solution_replays": int(
                    activity["source_full_solution_replays"]
                ),
                "source_feasibility_checks": int(
                    activity["source_feasibility_checks"]
                ),
                "neutral_candidate_attempts": int(
                    activity["neutral_candidate_attempts"]
                ),
                "neutral_feasibility_checks": int(
                    activity["neutral_feasibility_checks"]
                ),
                "neutral_normalization_failures": int(
                    activity["neutral_normalization_failures"]
                ),
                "final_independent_replays": int(
                    activity["final_independent_replays"]
                ),
                "final_feasibility_checks": int(
                    activity["final_feasibility_checks"]
                ),
                "total_full_solution_replays": int(
                    activity["total_full_solution_replays"]
                ),
                "total_feasibility_checks": int(
                    activity["total_feasibility_checks"]
                ),
                "accepted_move_count": len(
                    activity["accepted_moves"]
                ),
                "accepted_structure_change_count": sum(
                    move["route_structure_before_sha256"]
                    != move["route_structure_after_sha256"]
                    for move in activity["accepted_moves"]
                ),
                "accepted_segment_lengths_json": json.dumps(
                    [
                        len(move["segment"])
                        for move in activity["accepted_moves"]
                    ],
                    separators=(",", ":"),
                ),
                "accepted_all_declared_transfer_verified": all(
                    bool(
                        move[
                            "declared_transfer_verified_before_completion"
                        ]
                    )
                    for move in activity["accepted_moves"]
                ),
                "accepted_all_completed_transfer_verified": all(
                    bool(move["completed_transfer_verified"])
                    for move in activity["accepted_moves"]
                ),
                "accepted_all_source_cv_to_ev": all(
                    move["source_route_vehicle_type_before"] == "cv"
                    and move["source_route_vehicle_type_after"] == "ev"
                    for move in activity["accepted_moves"]
                ),
                "accepted_all_counterfactual_source_stays_cv": all(
                    bool(move["counterfactual_source_stays_cv"])
                    for move in activity["accepted_moves"]
                ),
                "accepted_all_beat_source_only_counterfactual": all(
                    float(move["counterfactual_cost_delta"])
                    < -1.0e-9
                    and int(move["cv_routes_after"])
                    <= int(move["cv_routes_counterfactual"]) - 1
                    for move in activity["accepted_moves"]
                ),
                "accepted_all_independent_replays_close": all(
                    float(move["independent_replay_error"])
                    <= 1.0e-7
                    for move in activity["accepted_moves"]
                ),
                "candidate_fail_closed_count": len(
                    activity["candidate_fail_closed"]
                ),
                "enumeration_fail_closed_count": len(
                    activity["enumeration_fail_closed"]
                ),
                "counterfactual_fail_closed_count": sum(
                    "counterfactual_error" in summary
                    for summary in activity["round_summaries"]
                ),
                "nonfinite_prescore_rejections": int(
                    activity["nonfinite_prescore_rejections"]
                ),
                "terminal_activity_record_count": len(
                    activity["terminal_activity_records"]
                ),
                "counterfactual_activity_record_count": len(
                    activity["counterfactual_activity_records"]
                ),
                "round_caps_closed": all(
                    int(summary["prescore_selected"]) <= 12
                    and int(summary["exact_attempted"]) <= 3
                    for summary in activity["round_summaries"]
                ),
                "actual_round_caps_closed": bool(
                    ledger_audit["per_round_caps_closed"]
                ),
                "activity_ledgers_reconciled": bool(
                    ledger_audit["passed"]
                ),
                "activity_ledger_audit_json": json.dumps(
                    ledger_audit,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "runner_proof_audit_passed": bool(
                    proof_audit["passed"]
                ),
                "runner_proof_audit_json": json.dumps(
                    proof_audit,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "runner_outer_full_solution_replays": 2,
                "runner_outer_feasibility_checks": 2,
                "runner_proof_full_solution_replays": int(
                    proof_audit["full_solution_replays"]
                ),
                "runner_proof_feasibility_checks": int(
                    proof_audit["feasibility_checks"]
                ),
                "runner_total_validation_replays": (
                    2 + int(proof_audit["full_solution_replays"])
                ),
                "runner_total_validation_checks": (
                    2 + int(proof_audit["feasibility_checks"])
                ),
                "complete_route_search_evaluations": int(
                    activity["complete_route_search_evaluations"]
                ),
                "route_search_guard_attempts": len(
                    route_search_guard["attempts"]
                )
                + len(proof_search_guard["attempts"])
                + len(source_validation_guard["attempts"])
                + len(final_validation_guard["attempts"]),
                "route_search_guard_installed": bool(
                    route_search_guard["installed"]
                    and proof_search_guard["installed"]
                    and source_validation_guard["installed"]
                    and final_validation_guard["installed"]
                ),
                "source_full_content_sha256": (
                    _runner_full_content_hash(source)
                ),
                "final_full_content_sha256": (
                    _runner_full_content_hash(result.solution)
                ),
                "elapsed_seconds": float(
                    activity["elapsed_seconds"]
                ),
                "objective_match": bool(
                    abs(recomputed - result.cost) <= 1.0e-7
                ),
                "activity_json": json.dumps(
                    activity,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            _require_finite_row(row)
            rows.append(row)

        if len(all_route_search_attempts) != sum(
            int(row["route_search_guard_attempts"]) for row in rows
        ):
            raise RuntimeError(
                "route-search guard attempt ledger did not close"
            )
        checks = _gate_checks(
            rows,
            source_solutions,
            source_hashes,
            protected_hashes,
            input_hashes,
        )
        _assert_frozen_closure(
            source_files,
            source_hashes,
            protected_hashes,
            input_hashes,
            frozen_git_head,
        )
        passed = all(checks.values())
        decision = {
            "schema_version": (
                "resetp.electrification-relocate-resize-behavior.v1"
            ),
            "verdict": (
                "PASS_ELECTRIFICATION_RELOCATE_RESIZE_BEHAVIOR"
                if passed
                else "STOP_ELECTRIFICATION_RELOCATE_RESIZE_BEHAVIOR"
            ),
            "passed": passed,
            "gate_checks": checks,
            "old_three_zero_search_replay_allowed": passed,
            "fresh_d3_allowed": False,
            "formal_search_allowed": False,
            "stage2_allowed": False,
            "full_experiment_allowed": False,
        }
        metadata = {
            "schema_version": (
                "resetp.electrification-relocate-resize-behavior-meta.v1"
            ),
            "created_at_utc": _now(),
            "git_head": frozen_git_head,
            "route_search_started": any(
                int(row["route_search_guard_attempts"]) > 0
                or int(
                    row["complete_route_search_evaluations"]
                )
                > 0
                for row in rows
            ),
            "complete_route_search_evaluations": sum(
                int(row["complete_route_search_evaluations"])
                for row in rows
            ),
            "route_search_guard_attempts": sum(
                int(row["route_search_guard_attempts"])
                for row in rows
            ),
            "all_route_search_attempts": list(
                all_route_search_attempts
            ),
            "alns_evaluations": sum(
                int(row["complete_route_search_evaluations"])
                for row in rows
            ),
            "hgs_calls": sum(
                int(row["route_search_guard_attempts"])
                for row in rows
            ),
            "prices": {
                "B_battery_kwh": float(PRICES.B_battery_kwh),
            },
            "config": asdict(
                solver.ElectrificationRelocateResizeConfig()
            ),
            "source_hashes": source_hashes,
            "protected_hashes": protected_hashes,
            "input_hashes": input_hashes,
            "scenario_count": len(rows),
            "formal_claim_allowed": False,
            "zero_search_test_runtime_recheck": test_recheck,
        }
        _write_json(CANONICAL_OUTPUT / "metadata.json", metadata)
        _write_csv(CANONICAL_OUTPUT / "raw_runs.csv", rows)
        _write_json(CANONICAL_OUTPUT / "decision.json", decision)
        _write_json(
            CANONICAL_OUTPUT / "solution_witnesses.json",
            witnesses,
        )
        (CANONICAL_OUTPUT / "report.md").write_text(
            _report(rows, decision),
            encoding="utf-8",
        )
        contamination = _appledouble_paths(CANONICAL_OUTPUT)
        cleanup = _clean_appledouble(CANONICAL_OUTPUT)
        if _appledouble_paths(CANONICAL_OUTPUT):
            raise RuntimeError("AppleDouble cleanup did not close")
        _write_json(
            CANONICAL_OUTPUT / "appledouble_seal.json",
            {
                "schema_version": (
                    "resetp.electrification-relocate-resize-"
                    "appledouble.v1"
                ),
                "transient_contamination": contamination,
                "cleanup": cleanup,
                "final_status": "CLEANED_AND_READY_TO_REHASH",
            },
        )
        _clean_appledouble(CANONICAL_OUTPUT)
        if _appledouble_paths(CANONICAL_OUTPUT):
            raise RuntimeError("AppleDouble returned before hashing")
        artifacts = {
            name: _sha256(CANONICAL_OUTPUT / name)
            for name in ARTIFACT_FILES
        }
        _write_json(
            CANONICAL_OUTPUT / "artifact_hashes.json",
            {
                "schema_version": (
                    "resetp.electrification-relocate-resize-"
                    "artifacts.v1"
                ),
                "artifacts": artifacts,
            },
        )
        _clean_appledouble(CANONICAL_OUTPUT)
        if _appledouble_paths(CANONICAL_OUTPUT):
            raise RuntimeError("AppleDouble present after final seal")
        for name, expected in artifacts.items():
            actual = _sha256(CANONICAL_OUTPUT / name)
            if actual != expected:
                raise RuntimeError(
                    f"artifact drift after seal: {name}"
                )
        _assert_frozen_closure(
            source_files,
            source_hashes,
            protected_hashes,
            input_hashes,
            frozen_git_head,
        )
        return 0 if passed else 1
    except Exception as exc:
        _seal_execution_failure(
            exc,
            rows=rows,
            source_hashes=source_hashes,
            protected_hashes=protected_hashes,
            input_hashes=input_hashes,
            route_search_attempts=all_route_search_attempts,
        )
        return 2


def _audit_activity_ledgers(
    activity: dict[str, Any],
) -> dict[str, Any]:
    candidate = list(activity["terminal_activity_records"])
    counterfactual = list(
        activity["counterfactual_activity_records"]
    )
    record_fields = (
        "full_solution_replays",
        "route_local_exact_evaluations",
        "route_proxy_evaluations",
        "route_local_schedule_evaluations",
        "feasibility_checks",
        "complete_route_search_evaluations",
    )

    def total(rows: list[dict[str, Any]], field: str) -> int:
        return sum(int(row[field]) for row in rows)

    summaries = {
        int(row["round"]): row
        for row in activity["round_summaries"]
    }
    unique_rounds = (
        len(summaries) == len(activity["round_summaries"])
        and set(summaries).issubset({1, 2})
    )
    per_round_rows: list[dict[str, Any]] = []
    per_round_ok = unique_rounds
    for round_index, summary in sorted(summaries.items()):
        candidate_count = sum(
            int(row["round"]) == round_index for row in candidate
        )
        counterfactual_count = sum(
            int(row["round"]) == round_index
            for row in counterfactual
        )
        expected_counterfactual = int(
            bool(summary.get("counterfactual_started"))
        )
        row_ok = bool(
            int(summary["prescore_selected"]) <= 12
            and int(summary["exact_attempted"]) <= 3
            and candidate_count <= 3
            and counterfactual_count <= 1
            and candidate_count == int(summary["exact_attempted"])
            and counterfactual_count == expected_counterfactual
        )
        per_round_ok = per_round_ok and row_ok
        per_round_rows.append(
            {
                "round": round_index,
                "candidate_records": candidate_count,
                "counterfactual_records": counterfactual_count,
                "summary_exact_attempted": int(
                    summary["exact_attempted"]
                ),
                "summary_counterfactual_started": bool(
                    summary.get("counterfactual_started")
                ),
                "passed": row_ok,
            }
        )

    checks = {
        "all_record_fields_present": all(
            all(field in row for field in record_fields)
            for row in (*candidate, *counterfactual)
        ),
        "all_record_values_nonnegative": all(
            all(int(row[field]) >= 0 for field in record_fields)
            for row in (*candidate, *counterfactual)
        ),
        "candidate_record_count_closes": (
            len(candidate)
            == int(activity["terminal_completion_calls"])
        ),
        "counterfactual_record_count_closes": (
            len(counterfactual)
            == int(
                activity[
                    "counterfactual_terminal_completion_calls"
                ]
            )
        ),
        "candidate_terminal_ledgers_close": all(
            (
                total(candidate, source)
                == int(activity[target])
            )
            for source, target in (
                (
                    "full_solution_replays",
                    "terminal_full_solution_replays",
                ),
                (
                    "route_local_exact_evaluations",
                    "terminal_route_local_exact_evaluations",
                ),
                (
                    "route_proxy_evaluations",
                    "terminal_route_proxy_evaluations",
                ),
                (
                    "route_local_schedule_evaluations",
                    "terminal_route_local_schedule_evaluations",
                ),
                (
                    "feasibility_checks",
                    "terminal_feasibility_checks",
                ),
            )
        ),
        "counterfactual_terminal_ledgers_close": all(
            (
                total(counterfactual, source)
                + (
                    int(
                        activity[
                            "counterfactual_independent_replays"
                        ]
                    )
                    if source == "full_solution_replays"
                    else (
                        int(
                            activity[
                                "counterfactual_terminal_completion_calls"
                            ]
                        )
                        if source == "feasibility_checks"
                        else 0
                    )
                )
                == int(activity[target])
            )
            for source, target in (
                (
                    "full_solution_replays",
                    "counterfactual_full_solution_replays",
                ),
                (
                    "route_local_exact_evaluations",
                    "counterfactual_route_local_exact_evaluations",
                ),
                (
                    "route_proxy_evaluations",
                    "counterfactual_route_proxy_evaluations",
                ),
                (
                    "route_local_schedule_evaluations",
                    "counterfactual_route_local_schedule_evaluations",
                ),
                (
                    "feasibility_checks",
                    "counterfactual_feasibility_checks",
                ),
            )
        ),
        "independent_candidate_ledgers_close": (
            int(activity["exact_candidate_independent_replays"])
            == len(candidate)
            == int(activity["exact_candidate_feasibility_checks"])
        ),
        "independent_counterfactual_ledger_closes": (
            int(activity["counterfactual_independent_replays"])
            == len(counterfactual)
        ),
        "route_search_ledger_closes": (
            total(
                [*candidate, *counterfactual],
                "complete_route_search_evaluations",
            )
            == int(activity["complete_route_search_evaluations"])
        ),
        "neutral_ledger_closes": (
            int(activity["neutral_candidate_attempts"])
            == int(activity["neutral_feasibility_checks"])
            + int(activity["neutral_normalization_failures"])
        ),
        "aggregate_full_replay_ledger_closes": (
            int(activity["total_full_solution_replays"])
            == sum(
                int(activity[name])
                for name in (
                    "source_full_solution_replays",
                    "terminal_full_solution_replays",
                    "counterfactual_full_solution_replays",
                    "exact_candidate_independent_replays",
                    "final_independent_replays",
                )
            )
        ),
        "aggregate_feasibility_ledger_closes": (
            int(activity["total_feasibility_checks"])
            == sum(
                int(activity[name])
                for name in (
                    "source_feasibility_checks",
                    "neutral_feasibility_checks",
                    "terminal_feasibility_checks",
                    "counterfactual_feasibility_checks",
                    "exact_candidate_feasibility_checks",
                    "final_feasibility_checks",
                )
            )
        ),
        "terminal_call_totals_close": (
            int(activity["total_terminal_completion_calls"])
            == len(candidate) + len(counterfactual)
            and len(candidate) <= 6
            and len(counterfactual) <= 2
            and len(candidate) + len(counterfactual) <= 8
        ),
        "per_round_caps_closed": per_round_ok,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "per_round": per_round_rows,
    }


def _audit_accepted_move_proofs(
    activity: dict[str, Any],
    bundle_dir: Path,
    prices: Any,
) -> dict[str, Any]:
    instance = _load_instance(bundle_dir)
    summaries = {
        int(row["round"]): row
        for row in activity["round_summaries"]
    }
    proof_rows: list[dict[str, Any]] = []
    replay_count = 0
    feasibility_count = 0
    for move in activity["accepted_moves"]:
        try:
            round_index = int(move["round"])
            summary = summaries[round_index]
            source = _solution_from_payload(
                move["source_solution_snapshot"]
            )
            neutral = _solution_from_payload(
                move["neutral_solution_snapshot"]
            )
            completed = _solution_from_payload(
                move["completed_solution_snapshot"]
            )
            counterfactual = _solution_from_payload(
                summary["counterfactual_solution_snapshot"]
            )
            solutions = {
                "source": source,
                "neutral": neutral,
                "completed": completed,
                "counterfactual": counterfactual,
            }
            costs: dict[str, float] = {}
            feasible: dict[str, bool] = {}
            for name, candidate in solutions.items():
                replay_count += 1
                costs[name] = float(
                    independent_cost(bundle_dir, candidate, prices)
                )
                feasibility_count += 1
                feasible[name] = not check_solution(
                    candidate,
                    instance,
                    prices,
                )
            source_index = int(move["source_index"])
            target_index = int(move["target_index"])
            segment = tuple(str(item) for item in move["segment"])
            exact_matches = [
                row
                for row in activity["exact_candidates"]
                if int(row.get("round", -1)) == round_index
                and int(row.get("source_index", -1)) == source_index
                and int(row.get("target_index", -1)) == target_index
                and tuple(row.get("segment", ())) == segment
                and int(row.get("insertion_position", -1))
                == int(move["insertion_position"])
                and row.get("completed_full_content_sha256")
                == move["completed_full_content_sha256"]
                and bool(row.get("eligible"))
            ]
            hashes_close = bool(
                _runner_full_content_hash(source)
                == move["source_full_content_sha256"]
                and _runner_semantic_hash(source)
                == move["source_semantic_sha256"]
                and _runner_full_content_hash(neutral)
                == move["neutral_full_content_sha256"]
                and _runner_semantic_hash(neutral)
                == move["neutral_semantic_sha256"]
                and _runner_full_content_hash(completed)
                == move["completed_full_content_sha256"]
                and _runner_semantic_hash(completed)
                == move["completed_semantic_sha256"]
                and _runner_full_content_hash(counterfactual)
                == summary[
                    "counterfactual_full_content_sha256"
                ]
                and _runner_semantic_hash(counterfactual)
                == summary["counterfactual_semantic_sha256"]
                and all(
                    _runner_full_content_hash(candidate)
                    == solver._full_content_hash(candidate)
                    and _runner_semantic_hash(candidate)
                    == solver._semantic_hash(candidate)
                    for candidate in solutions.values()
                )
            )
            declared_transfer = _runner_declared_transfer_holds(
                source,
                neutral,
                instance,
                source_index,
                target_index,
                int(move["segment_start"]),
                segment,
                int(move["insertion_position"]),
            )
            completed_transfer = _runner_completed_transfer_holds(
                completed,
                instance,
                source_index,
                target_index,
                segment,
            )
            route_types_close = bool(
                _runner_route_type(source, source_index) == "cv"
                and _runner_route_type(
                    counterfactual,
                    source_index,
                )
                == "cv"
                and _runner_route_type(completed, source_index)
                == "ev"
            )
            cv_counts = {
                name: _runner_cv_count(candidate)
                for name, candidate in solutions.items()
            }
            costs_close = bool(
                all(math.isfinite(value) for value in costs.values())
                and abs(costs["source"] - float(move["cost_before"]))
                <= 1.0e-7
                and abs(costs["completed"] - float(move["cost_after"]))
                <= 1.0e-7
                and abs(
                    costs["completed"]
                    - float(move["completed_cost"])
                )
                <= 1.0e-7
                and abs(
                    costs["counterfactual"]
                    - float(summary["counterfactual_cost"])
                )
                <= 1.0e-7
                and costs["completed"] < costs["source"] - 1.0e-9
                and costs["completed"]
                < costs["counterfactual"] - 1.0e-9
            )
            cv_counts_close = bool(
                cv_counts["source"] == int(move["cv_routes_before"])
                and cv_counts["completed"]
                == int(move["cv_routes_after"])
                and cv_counts["counterfactual"]
                == int(move["cv_routes_counterfactual"])
                and cv_counts["completed"]
                <= cv_counts["source"] - 1
                and cv_counts["completed"]
                <= cv_counts["counterfactual"] - 1
            )
            checks = {
                "all_snapshots_feasible": all(feasible.values()),
                "all_hashes_close": hashes_close,
                "declared_transfer_exact_before_completion": (
                    declared_transfer
                ),
                "declared_transfer_survives_completion": (
                    completed_transfer
                ),
                "declared_source_converts_cv_to_ev": (
                    route_types_close
                ),
                "costs_independently_close_and_improve": costs_close,
                "cv_counts_independently_close_and_improve": (
                    cv_counts_close
                ),
                "exact_candidate_has_one_eligible_match": (
                    len(exact_matches) == 1
                ),
            }
            proof_rows.append(
                {
                    "round": round_index,
                    "source_index": source_index,
                    "target_index": target_index,
                    "segment": list(segment),
                    "costs": costs,
                    "cv_counts": cv_counts,
                    "checks": checks,
                    "passed": all(checks.values()),
                }
            )
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as exc:
            proof_rows.append(
                {
                    "round": move.get("round"),
                    "passed": False,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    return {
        "passed": all(row["passed"] for row in proof_rows),
        "accepted_move_count": len(activity["accepted_moves"]),
        "proof_row_count": len(proof_rows),
        "full_solution_replays": replay_count,
        "feasibility_checks": feasibility_count,
        "rows": proof_rows,
    }


def _runner_declared_transfer_holds(
    before: Solution,
    neutral: Solution,
    instance: Any,
    source_index: int,
    target_index: int,
    segment_start: int,
    segment: tuple[str, ...],
    insertion_position: int,
) -> bool:
    if (
        source_index == target_index
        or source_index < 0
        or target_index < 0
        or len(before.routes) != len(neutral.routes)
        or source_index >= len(before.routes)
        or target_index >= len(before.routes)
        or _runner_route_type(before, source_index) != "cv"
        or _runner_route_type(neutral, source_index) != "cv"
        or _runner_route_type(neutral, target_index) != "cv"
    ):
        return False
    before_customers = [
        _runner_customer_ids(route, instance)
        for route in before.routes
    ]
    neutral_customers = [
        _runner_customer_ids(route, instance)
        for route in neutral.routes
    ]
    declared = list(segment)
    source_before = before_customers[source_index]
    if (
        not declared
        or source_before[
            segment_start : segment_start + len(declared)
        ]
        != declared
    ):
        return False
    expected_source = (
        source_before[:segment_start]
        + source_before[segment_start + len(declared) :]
    )
    target_before = before_customers[target_index]
    if not 0 <= insertion_position <= len(target_before):
        return False
    expected_target = list(target_before)
    expected_target[insertion_position:insertion_position] = declared
    for index, after in enumerate(neutral_customers):
        expected = before_customers[index]
        if index == source_index:
            expected = expected_source
        elif index == target_index:
            expected = expected_target
        if after != expected:
            return False
        if (
            before.routes[index].home_depot_id
            != neutral.routes[index].home_depot_id
        ):
            return False
    return True


def _runner_completed_transfer_holds(
    completed: Solution,
    instance: Any,
    source_index: int,
    target_index: int,
    segment: tuple[str, ...],
) -> bool:
    if (
        source_index == target_index
        or source_index < 0
        or target_index < 0
        or source_index >= len(completed.routes)
        or target_index >= len(completed.routes)
        or not segment
    ):
        return False
    source = _runner_customer_ids(
        completed.routes[source_index],
        instance,
    )
    target = _runner_customer_ids(
        completed.routes[target_index],
        instance,
    )
    declared = list(segment)
    return bool(
        not any(customer in source for customer in declared)
        and any(
            target[index : index + len(declared)] == declared
            for index in range(len(target) - len(declared) + 1)
        )
        and all(target.count(customer) == 1 for customer in declared)
    )


def _runner_customer_ids(route: Route, instance: Any) -> list[str]:
    nodes = {str(node.node_id): node for node in instance.nodes}
    return [
        str(node_id)
        for node_id in route.node_sequence
        if str(node_id) in nodes
        and str(nodes[str(node_id)].node_type).lower() == "c"
    ]


def _runner_route_type(solution: Solution, index: int) -> str:
    if index < 0 or index >= len(solution.routes):
        return "__missing__"
    return solution.routes[index].vehicle_type.lower()


def _runner_cv_count(solution: Solution) -> int:
    return sum(
        route.vehicle_type.lower() == "cv" for route in solution.routes
    )


def _gate_checks(
    rows: list[dict[str, Any]],
    sources: dict[str, Solution],
    source_hashes: dict[str, str],
    protected_hashes: dict[str, str],
    input_hashes: dict[str, str],
) -> dict[str, bool]:
    by_name = {row["scenario"]: row for row in rows}
    binding = by_name["binding_saved_v7_20c"]
    nonbinding = by_name["nonbinding_saved_v7_25c_all_ev"]
    return {
        "both_scenarios_feasible": all(
            bool(row["feasible"]) for row in rows
        ),
        "all_objectives_match": all(
            bool(row["objective_match"]) for row in rows
        ),
        "binding_strictly_improves": (
            float(binding["objective_delta"]) < -1.0e-9
        ),
        "binding_reduces_cv_route_count": (
            int(binding["cv_route_reduction"]) >= 1
        ),
        "binding_accepts_move": int(
            binding["accepted_move_count"]
        )
        >= 1,
        "binding_route_structure_changes": int(
            binding["accepted_structure_change_count"]
        )
        >= 1,
        "binding_declared_transfer_survives_completion": bool(
            binding["accepted_all_declared_transfer_verified"]
        )
        and bool(binding["accepted_all_completed_transfer_verified"]),
        "binding_declared_source_converts_cv_to_ev": bool(
            binding["accepted_all_source_cv_to_ev"]
        ),
        "binding_beats_source_only_v7_counterfactual": bool(
            binding[
                "accepted_all_counterfactual_source_stays_cv"
            ]
        )
        and bool(
            binding[
                "accepted_all_beat_source_only_counterfactual"
            ]
        )
        and int(
            binding["counterfactual_terminal_completion_calls"]
        )
        >= 1,
        "accepted_candidate_replays_close": all(
            bool(row["accepted_all_independent_replays_close"])
            for row in rows
        ),
        "runner_independently_reconstructs_all_accepted_moves": all(
            bool(row["runner_proof_audit_passed"])
            for row in rows
        ),
        "accepted_segments_respect_frozen_lengths": all(
            all(
                int(length) in {1, 2}
                for length in json.loads(
                    row["accepted_segment_lengths_json"]
                )
            )
            for row in rows
        ),
        "binding_terminal_calls_bounded": int(
            binding["terminal_completion_calls"]
        )
        <= 6
        and int(
            binding["counterfactual_terminal_completion_calls"]
        )
        <= 2
        and int(binding["total_terminal_completion_calls"]) <= 8,
        "nonbinding_exact_content_unchanged": (
            nonbinding["source_full_content_sha256"]
            == nonbinding["final_full_content_sha256"]
            == _runner_full_content_hash(
                sources["nonbinding_saved_v7_25c_all_ev"]
            )
        ),
        "nonbinding_cost_unchanged": abs(
            float(nonbinding["objective_delta"])
        )
        <= 1.0e-12,
        "nonbinding_zero_terminal_calls": int(
            nonbinding["terminal_completion_calls"]
        )
        == 0
        and int(
            nonbinding["counterfactual_terminal_completion_calls"]
        )
        == 0,
        "prescore_caps_respected": all(
            int(row["prescore_selected_moves"]) <= 24
            and bool(row["round_caps_closed"])
            and bool(row["actual_round_caps_closed"])
            for row in rows
        ),
        "activity_ledgers_independently_reconciled": all(
            bool(row["activity_ledgers_reconciled"])
            for row in rows
        ),
        "zero_complete_route_search_evaluations": all(
            int(row["complete_route_search_evaluations"]) == 0
            and int(row["route_search_guard_attempts"]) == 0
            and bool(row["route_search_guard_installed"])
            for row in rows
        ),
        "terminal_call_ledgers_close": all(
            int(row["terminal_activity_record_count"])
            == int(row["terminal_completion_calls"])
            and int(row["counterfactual_activity_record_count"])
            == int(
                row["counterfactual_terminal_completion_calls"]
            )
            for row in rows
        ),
        "no_exact_or_enumeration_failure": all(
            int(row["candidate_fail_closed_count"]) == 0
            and int(row["enumeration_fail_closed_count"]) == 0
            and int(row["counterfactual_fail_closed_count"]) == 0
            and int(row["nonfinite_prescore_rejections"]) == 0
            for row in rows
        ),
        "source_and_final_ledgers_close": all(
            int(row["source_full_solution_replays"]) == 1
            and int(row["source_feasibility_checks"]) == 1
            and int(row["final_independent_replays"]) == 1
            and int(row["final_feasibility_checks"]) == 1
            and int(row["counterfactual_independent_replays"])
            == int(
                row["counterfactual_terminal_completion_calls"]
            )
            for row in rows
        ),
        "runner_validation_ledgers_close": all(
            int(row["runner_outer_full_solution_replays"]) == 2
            and int(row["runner_outer_feasibility_checks"]) == 2
            and int(row["runner_proof_full_solution_replays"])
            == 4 * int(row["accepted_move_count"])
            and int(row["runner_proof_feasibility_checks"])
            == 4 * int(row["accepted_move_count"])
            and int(row["runner_total_validation_replays"])
            == int(row["runner_outer_full_solution_replays"])
            + int(row["runner_proof_full_solution_replays"])
            and int(row["runner_total_validation_checks"])
            == int(row["runner_outer_feasibility_checks"])
            + int(row["runner_proof_feasibility_checks"])
            for row in rows
        ),
        "neutral_candidate_ledger_closes": all(
            int(row["neutral_candidate_attempts"])
            == int(row["neutral_feasibility_checks"])
            + int(row["neutral_normalization_failures"])
            for row in rows
        ),
        "candidate_exact_ledger_closes": all(
            int(row["exact_candidate_independent_replays"])
            == int(row["terminal_completion_calls"])
            and int(row["exact_candidate_feasibility_checks"])
            == int(row["terminal_completion_calls"])
            for row in rows
        ),
        "aggregate_ledgers_close": all(
            int(row["total_full_solution_replays"])
            == (
                int(row["source_full_solution_replays"])
                + int(row["terminal_full_solution_replays"])
                + int(
                    row["counterfactual_full_solution_replays"]
                )
                + int(
                    row["exact_candidate_independent_replays"]
                )
                + int(row["final_independent_replays"])
            )
            and int(row["total_feasibility_checks"])
            == (
                int(row["source_feasibility_checks"])
                + int(row["neutral_feasibility_checks"])
                + int(row["terminal_feasibility_checks"])
                + int(
                    row["counterfactual_feasibility_checks"]
                )
                + int(
                    row["exact_candidate_feasibility_checks"]
                )
                + int(row["final_feasibility_checks"])
            )
            for row in rows
        ),
        "source_files_unchanged": all(
            _sha256(REPO / path) == expected
            for path, expected in source_hashes.items()
        ),
        "protected_files_unchanged": all(
            _sha256(REPO / path) == expected
            for path, expected in protected_hashes.items()
        ),
        "input_files_unchanged": _input_hashes() == input_hashes,
        "input_files_match_preregistered_manifest": (
            _input_hashes() == _registered_input_hashes()
        ),
        "zero_search_regression_tests_registered": (
            _test_manifest_valid()
        ),
    }


def _saved_final(instance: str, arm: str) -> Solution:
    payload = json.loads(
        WITNESSES.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    matches: list[Solution] = []
    matching_use_count = 0
    for key, row in payload.items():
        solution = _solution_from_payload(row["solution"])
        recomputed_full = _runner_full_content_hash(solution)
        recomputed_semantic = _runner_semantic_hash(solution)
        if str(key) != recomputed_full:
            raise RuntimeError(
                "saved witness key does not match ordered full hash"
            )
        if row.get("full_content_sha256") not in {
            None,
            recomputed_full,
        }:
            raise RuntimeError(
                "saved witness full hash field does not close"
            )
        recorded_semantic = row.get(
            "semantic_order_insensitive_sha256"
        )
        if recorded_semantic is not None and (
            str(recorded_semantic) != recomputed_semantic
        ):
            raise RuntimeError(
                "saved witness semantic hash field does not close"
            )
        legacy_semantic = row.get("semantic_exact_sha256")
        if legacy_semantic is not None and (
            str(legacy_semantic)
            != _legacy_semantic_hash(solution)
        ):
            raise RuntimeError(
                "saved witness legacy semantic hash does not close"
            )
        row_matches = sum(
            use.get("kind") == "final"
            and use.get("instance") == instance
            and use.get("arm") == arm
            for use in row.get("uses", [])
        )
        if row_matches:
            matches.append(solution)
            matching_use_count += int(row_matches)
    if len(matches) != 1 or matching_use_count != 1:
        raise RuntimeError(
            "saved final must have exactly one row and one use: "
            f"{instance}/{arm}; rows={len(matches)}; "
            f"uses={matching_use_count}"
        )
    return matches[0]


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


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


def _add_witness(
    witnesses: dict[str, Any],
    solution: Solution,
    use: dict[str, Any],
) -> None:
    full = _runner_full_content_hash(solution)
    snapshot = asdict(solution)
    if full in witnesses and witnesses[full]["solution"] != snapshot:
        raise RuntimeError("true full-content SHA collision")
    row = witnesses.setdefault(
        full,
        {
            "full_content_sha256": full,
            "semantic_order_insensitive_sha256": (
                _runner_semantic_hash(solution)
            ),
            "legacy_semantic_exact_sha256": (
                _legacy_semantic_hash(solution)
            ),
            "solution": snapshot,
            "uses": [],
        },
    )
    row["uses"].append(use)


def _legacy_semantic_hash(solution: Solution) -> str:
    payload = {
        "routes": sorted(
            (
                str(route.vehicle_id),
                str(route.vehicle_type).lower(),
                str(route.home_depot_id),
                tuple(str(node) for node in route.node_sequence),
            )
            for route in solution.routes
        ),
        "charging_actions": sorted(
            (
                str(action.vehicle_id),
                str(action.station_id),
                float(action.energy_kwh).hex(),
                float(action.occupancy_minutes).hex(),
                float(action.charge_start_second).hex(),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        ),
        "cross_site_services": sorted(
            (
                str(item.customer_id),
                str(item.served_by_depot_id),
            )
            for item in solution.cross_site_services
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _runner_full_content_hash(solution: Solution) -> str:
    encoded = json.dumps(
        asdict(solution),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _runner_semantic_hash(solution: Solution) -> str:
    payload = asdict(solution)
    for key in (
        "routes",
        "charging_actions",
        "cross_site_services",
    ):
        payload[key] = sorted(
            payload[key],
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _input_hashes() -> dict[str, str]:
    paths = [WITNESSES]
    for _, instance, _ in SCENARIOS:
        paths.extend(
            item
            for item in (ARCHIVE / instance).rglob("*")
            if item.is_file() and not item.name.startswith("._")
        )
    return {
        _relative(path): _sha256(path)
        for path in sorted(set(paths))
    }


def _registered_input_hashes() -> dict[str, str]:
    payload = json.loads(
        INPUT_MANIFEST.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    if payload.get("schema_version") != (
        "resetp.electrification-relocate-resize-inputs.v1"
    ):
        raise RuntimeError("unexpected registered input manifest schema")
    if payload.get("status") != "FROZEN_BEFORE_BEHAVIOR":
        raise RuntimeError("input manifest is not frozen")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("registered input manifest is empty")
    return {str(path): str(value) for path, value in files.items()}


def _require_registered_inputs() -> None:
    expected = _registered_input_hashes()
    actual = _input_hashes()
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(
            path
            for path in set(actual) & set(expected)
            if actual[path] != expected[path]
        )
        raise RuntimeError(
            "behavior inputs differ from preregistered manifest: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )


def _test_manifest_valid() -> bool:
    try:
        payload = json.loads(
            TEST_MANIFEST.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
        if payload.get("schema_version") != (
            "resetp.electrification-relocate-resize-tests.v1"
        ):
            return False
        if not bool(payload.get("passed")):
            return False
        if bool(payload.get("scoring_started")):
            return False
        if bool(payload.get("route_search_started")):
            return False
        if int(payload.get("test_count", 0)) != 7:
            return False
        if tuple(payload.get("command", ())) != TEST_COMMAND:
            return False
        if tuple(payload.get("coverage", ())) != (
            EXPECTED_TEST_COVERAGE
        ):
            return False
        source_hashes = payload.get("source_hashes")
        protected_hashes = payload.get("protected_hashes")
        if not isinstance(source_hashes, dict) or set(
            source_hashes
        ) != set(TEST_SOURCE_FILES):
            return False
        if not isinstance(protected_hashes, dict) or set(
            protected_hashes
        ) != set(PROTECTED_FILES):
            return False
        for path, expected in source_hashes.items():
            if _sha256(REPO / path) != str(expected):
                return False
        for path, expected in protected_hashes.items():
            if _sha256(REPO / path) != str(expected):
                return False
        return True
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False


def _require_test_manifest() -> dict[str, Any]:
    if not _test_manifest_valid():
        raise RuntimeError(
            "zero-search regression test manifest is missing or stale"
        )
    payload = json.loads(
        TEST_MANIFEST.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    expected_count = int(payload["test_count"])
    test_path = (
        HERE / "test_electrification_relocate_resize_solver.py"
    )
    module_name = "_electrification_zero_search_runtime_recheck"
    spec = importlib.util.spec_from_file_location(
        module_name,
        test_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load registered zero-search tests")
    module = importlib.util.module_from_spec(spec)
    stream = io.StringIO()
    with _forbid_route_search() as guard:
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            suite = unittest.defaultTestLoader.loadTestsFromModule(
                module
            )
            result = unittest.TextTestRunner(
                stream=stream,
                verbosity=1,
            ).run(suite)
        finally:
            sys.modules.pop(module_name, None)
    output = stream.getvalue()
    if (
        not result.wasSuccessful()
        or result.testsRun != expected_count
        or guard["attempts"]
        or f"Ran {expected_count} tests" not in output
        or "OK" not in output
    ):
        raise RuntimeError(
            "registered zero-search tests failed runtime recheck: "
            f"tests_run={result.testsRun}; "
            f"failures={len(result.failures)}; "
            f"errors={len(result.errors)}; "
            f"guard_attempts={guard['attempts']}; "
            f"output={output[-2000:]}"
        )
    return {
        "command": list(TEST_COMMAND),
        "returncode": 0,
        "test_count": expected_count,
        "output_sha256": hashlib.sha256(
            output.encode("utf-8")
        ).hexdigest(),
        "scoring_started": False,
        "route_search_started": bool(guard["attempts"]),
        "route_search_guard_installed": bool(guard["installed"]),
    }


def _all_source_files() -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "--", "solver/src", "models/src"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    )
    tracked_python = [
        line
        for line in completed.stdout.splitlines()
        if line.endswith(".py")
    ]
    filesystem_python = [
        _relative(path)
        for root in (REPO / "solver/src", REPO / "models/src")
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        and not path.name.startswith("._")
    ]
    return tuple(
        sorted(
            {
                *STATIC_SOURCE_FILES,
                *tracked_python,
                *filesystem_python,
            }
        )
    )


def _require_expected_module_origins() -> None:
    expected = {
        solver: HERE / "electrification_relocate_resize_solver.py",
        prototype_module: LEGACY / "prototype.py",
        v4_module: LEGACY / "v4_mechanism_alns_solver.py",
        v5_module: LEGACY / "v5_carbon_retiming_solver.py",
        v6_module: LEGACY / "v6_monotone_mechanism_solver.py",
        v7_module: LEGACY / "v7_responsibility_solver.py",
        winner_module: (
            REPO
            / "solver/src/setp_solver/algorithms/resetp_alns/"
            "kernel/winner.py"
        ),
    }
    terminal = sys.modules.get("terminal_completion")
    if terminal is None:
        raise RuntimeError("terminal completion module is not loaded")
    expected[terminal] = HERE / "terminal_completion.py"
    failures = []
    for module, path in expected.items():
        actual = Path(str(getattr(module, "__file__", ""))).resolve()
        if actual != path.resolve():
            failures.append(
                f"{module.__name__}:{actual}!={path.resolve()}"
            )
    if failures:
        raise RuntimeError(
            "unexpected imported module origin: "
            + ", ".join(failures)
        )


def _assert_frozen_closure(
    source_files: tuple[str, ...],
    source_hashes: dict[str, str],
    protected_hashes: dict[str, str],
    input_hashes: dict[str, str],
    frozen_git_head: str,
) -> None:
    _require_expected_module_origins()
    current_source_files = _all_source_files()
    if current_source_files != source_files:
        raise RuntimeError("source file set drifted during behavior gate")
    _require_clean_sources(source_files)
    if {
        path: _sha256(REPO / path) for path in source_files
    } != source_hashes:
        raise RuntimeError("source hash drift during behavior gate")
    if {
        path: _sha256(REPO / path) for path in PROTECTED_FILES
    } != protected_hashes:
        raise RuntimeError("protected hash drift during behavior gate")
    if _input_hashes() != input_hashes:
        raise RuntimeError("input hash drift during behavior gate")
    _require_registered_inputs()
    if not _test_manifest_valid():
        raise RuntimeError("test manifest drift during behavior gate")
    if _git("rev-parse", "HEAD") != frozen_git_head:
        raise RuntimeError("git HEAD drift during behavior gate")


def _load_instance(bundle_dir: Path) -> Any:
    from setp_solver.search.bundle import load_search_bundle

    return load_search_bundle(bundle_dir).instance


def _require_clean_sources(paths: tuple[str, ...]) -> None:
    failures: list[str] = []
    for path in (*paths, *PROTECTED_FILES):
        absolute = REPO / path
        if not absolute.is_file():
            failures.append(f"missing:{path}")
            continue
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0:
            failures.append(f"untracked:{path}")
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
            "behavior sources must be committed first: "
            + ", ".join(failures)
        )


@contextmanager
def _forbid_route_search(
    global_attempts: list[str] | None = None,
) -> Any:
    """Fail immediately if this zero-search gate reaches a search entry."""

    state: dict[str, Any] = {
        "installed": True,
        "attempts": [],
    }

    def blocker(label: str) -> Any:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            state["attempts"].append(label)
            if global_attempts is not None:
                global_attempts.append(label)
            raise RuntimeError(
                f"zero-search behavior gate blocked route search: {label}"
            )

        return blocked

    entrypoints = {
        getattr(module, name)
        for module, name in (
            (winner_module, "run_winner_kernel"),
            (prototype_module, "run_outer_search"),
            (prototype_module, "run_pure_alns"),
            (prototype_module, "run_combined"),
            (prototype_module, "run_memetic_combined"),
            (prototype_module, "run_mechanism_intensified"),
            (v4_module, "run_mechanism_alns_v4"),
            (v4_module, "run_mechanism_alns_v4_without_depot"),
            (v4_module, "run_mechanism_alns_v4_without_joint"),
            (v5_module, "run_mechanism_alns_v5"),
            (v5_module, "run_mechanism_alns_v5_without_carbon"),
            (v6_module, "run_mechanism_alns_v6"),
            (v6_module, "run_mechanism_alns_v6_without_joint"),
            (v6_module, "run_mechanism_alns_v6_without_carbon"),
            (v7_module, "run_mechanism_alns_v7"),
            (
                v7_module,
                "run_mechanism_alns_v7_without_responsibility",
            ),
        )
    }
    entrypoint_ids = {id(item) for item in entrypoints}
    aliases: list[tuple[Any, str, str]] = []
    seen: set[tuple[int, str]] = set()
    for module in list(sys.modules.values()):
        if module is None:
            continue
        try:
            attributes = list(vars(module).items())
        except TypeError:
            continue
        for name, value in attributes:
            if id(value) not in entrypoint_ids:
                continue
            key = (id(module), name)
            if key in seen:
                continue
            seen.add(key)
            aliases.append(
                (
                    module,
                    name,
                    f"{getattr(module, '__name__', '?')}.{name}",
                )
            )
    with ExitStack() as stack:
        for module, name, label in aliases:
            stack.enter_context(
                patch.object(module, name, blocker(label))
            )
        stack.enter_context(
            patch.object(
                subprocess,
                "Popen",
                blocker("external_process"),
            )
        )
        stack.enter_context(
            patch.object(os, "system", blocker("os_system"))
        )
        yield state


def _require_finite_row(row: dict[str, Any]) -> None:
    for key in (
        "source_cost",
        "final_cost",
        "objective_delta",
        "improvement_percent",
        "elapsed_seconds",
    ):
        if not math.isfinite(float(row[key])):
            raise RuntimeError(f"non-finite row value: {key}")


def _report(
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# 燃油长路线减负—电动化联动搬移：零搜索行为门",
        "",
        f"判定：`{decision['verdict']}`。",
        "",
        "本门只回放仓库已有 v7 最终解，没有启动 ALNS、HGS、阶段二或正式实验。",
        "",
        "| 场景 | 原成本 | 新成本 | 改善 | 燃油路线变化 | 完整收尾调用 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['scenario']} | {row['source_cost']:.9f} | "
            f"{row['final_cost']:.9f} | "
            f"{row['improvement_percent']:.6f}% | "
            f"{row['source_cv_routes']}→{row['final_cv_routes']} | "
            f"{row['terminal_completion_calls']} |"
        )
    lines.extend(
        [
            "",
            "本结果只决定是否值得回放另外两个已保存 v7 解；不构成公开算例、",
            "HGS/ALNS 对比或论文性能证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _seal_execution_failure(
    exc: Exception,
    *,
    rows: list[dict[str, Any]],
    source_hashes: dict[str, str],
    protected_hashes: dict[str, str],
    input_hashes: dict[str, str],
    route_search_attempts: list[str],
) -> None:
    """Turn a burned one-shot attempt into a complete sealed failure set."""

    failure = {
        "schema_version": (
            "resetp.electrification-relocate-resize-"
            "behavior-failure.v2"
        ),
        "failed_at_utc": _now(),
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "completed_scenario_count": len(rows),
        "rerun_same_canonical_output_allowed": False,
        "old_three_zero_search_replay_allowed": False,
        "fresh_d3_allowed": False,
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": (
            "resetp.electrification-relocate-resize-"
            "behavior-failure-meta.v1"
        ),
        "created_at_utc": _now(),
        "git_head": _git("rev-parse", "HEAD"),
        "status": "INCONCLUSIVE_EXECUTION_FAILURE",
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "input_hashes": input_hashes,
        "completed_scenario_count": len(rows),
        "completed_row_route_search_guard_attempts": sum(
            int(row.get("route_search_guard_attempts", 0))
            for row in rows
        ),
        "route_search_guard_attempts": len(route_search_attempts),
        "all_route_search_attempts": list(route_search_attempts),
        "complete_route_search_evaluations": sum(
            int(
                row.get(
                    "complete_route_search_evaluations",
                    0,
                )
            )
            for row in rows
        ),
    }
    decision = {
        "schema_version": (
            "resetp.electrification-relocate-resize-"
            "behavior.v1"
        ),
        "verdict": "INCONCLUSIVE_EXECUTION_FAILURE",
        "passed": False,
        "failure": {
            "exception_type": type(exc).__name__,
            "message": str(exc),
        },
        "old_three_zero_search_replay_allowed": False,
        "fresh_d3_allowed": False,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "full_experiment_allowed": False,
    }
    _write_json(CANONICAL_OUTPUT / "execution_failure.json", failure)
    _write_json(CANONICAL_OUTPUT / "metadata.json", metadata)
    _write_csv(
        CANONICAL_OUTPUT / "raw_runs.csv",
        rows
        or [
            {
                "status": "INCONCLUSIVE_EXECUTION_FAILURE",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        ],
    )
    _write_json(CANONICAL_OUTPUT / "decision.json", decision)
    (CANONICAL_OUTPUT / "report.md").write_text(
        "# 燃油长路线减负—电动化联动搬移：执行失败封存\n\n"
        "判定：`INCONCLUSIVE_EXECUTION_FAILURE`。\n\n"
        "这次一次性行为门已经消耗，但没有形成可用成绩；不得从部分输出"
        "推断算法好坏，也不得在同一目录救援重跑。\n\n"
        f"失败类型：`{type(exc).__name__}`。信息：`{exc}`。\n",
        encoding="utf-8",
    )
    _clean_appledouble(CANONICAL_OUTPUT)
    if _appledouble_paths(CANONICAL_OUTPUT):
        raise RuntimeError("AppleDouble remained during failure seal")
    artifact_hashes = {
        path.name: _sha256(path)
        for path in sorted(CANONICAL_OUTPUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(
        CANONICAL_OUTPUT / "artifact_hashes.json",
        {
            "schema_version": (
                "resetp.electrification-relocate-resize-"
                "failure-artifacts.v1"
            ),
            "artifacts": artifact_hashes,
        },
    )
    _clean_appledouble(CANONICAL_OUTPUT)
    if _appledouble_paths(CANONICAL_OUTPUT):
        raise RuntimeError("AppleDouble returned after failure seal")
    for name, expected in artifact_hashes.items():
        if _sha256(CANONICAL_OUTPUT / name) != expected:
            raise RuntimeError(
                f"failure artifact drift after seal: {name}"
            )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _appledouble_paths(output_dir: Path) -> list[str]:
    paths = [
        _relative(path)
        for path in output_dir.rglob("._*")
        if path.exists()
    ]
    companion = output_dir.parent / f"._{output_dir.name}"
    if companion.exists():
        paths.append(_relative(companion))
    return sorted(paths)


def _clean_appledouble(output_dir: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["dot_clean", "-m", str(output_dir)],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    companion = output_dir.parent / f"._{output_dir.name}"
    if companion.exists():
        companion.unlink()
    return {
        "returncode": int(completed.returncode),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _freeze_environment() -> None:
    os.environ["PYTHONHASHSEED"] = "0"
    os.environ["SETP_E3_STRICT_MULTITRIP"] = "0"
    os.environ["SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC"] = "0"
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = ""


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"electrification relocate-resize behavior failure: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
