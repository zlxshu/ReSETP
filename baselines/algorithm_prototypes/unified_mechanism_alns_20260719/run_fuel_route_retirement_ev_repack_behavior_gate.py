"""One-shot zero-search behavior gate for fuel-route retirement.

The 20-customer result is training-only because that instance has already
been observed.  The 25-customer all-EV solution is a non-binding exact-noop
control.  This runner cannot authorize D3, formal search, or stage two.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from contextlib import contextmanager, ExitStack
import csv
from dataclasses import asdict
import hashlib
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
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import fuel_route_retirement_ev_repack_solver as solver  # noqa: E402
import prototype as prototype_module  # noqa: E402
import test_fuel_route_retirement_ev_repack_solver as test_module  # noqa: E402
import v4_mechanism_alns_solver as v4_module  # noqa: E402
import v5_carbon_retiming_solver as v5_module  # noqa: E402
import v6_monotone_mechanism_solver as v6_module  # noqa: E402
import v7_responsibility_solver as v7_module  # noqa: E402
from contextual_expert_fixtures import PRICES_280  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel import (  # noqa: E402
    winner as winner_module,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


OUTPUT_DIR = HERE / "fuel_route_retirement_ev_repack_behavior_gate"
DEPENDENCY_MANIFEST = (
    HERE / "fuel_route_retirement_ev_repack_dependency_manifest_20260719.json"
)
INPUT_MANIFEST = HERE / "electrification_relocate_resize_input_manifest_20260719.json"
WITNESSES = HERE / "contextual_expert_p1_training_gate/solution_witnesses.json"
BUNDLE_ROOT = (
    REPO / "models/data_bundle/generated_instances/"
    "L-main_size_preserving_v2_archive_20260710"
)
BINDING_BUNDLE = BUNDLE_ROOT / "L-main-threeshift-20c-01"
NONBINDING_BUNDLE = BUNDLE_ROOT / "L-main-threeshift-25c-01"
PROTECTED_FILES = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
)
FIXED_BINDING_SOURCE_COST = 621.0831141941019


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="validate locks and zero-search tests without creating output",
    )
    args = parser.parse_args()
    try:
        preflight = _preflight()
    except Exception as exc:  # noqa: BLE001
        print(f"PREFLIGHT_FAILED: {type(exc).__name__}: {exc}")
        return 2
    if args.preflight_only:
        print(json.dumps(preflight, indent=2, sort_keys=True))
        return 0
    return _run_once(preflight)


def _preflight() -> dict[str, Any]:
    if OUTPUT_DIR.exists():
        raise RuntimeError(f"one-shot output already exists: {OUTPUT_DIR}")
    status = _git(["status", "--porcelain"])
    if status.strip():
        raise RuntimeError("behavior gate requires a committed, clean worktree")
    dependency_lock = _read_json_strict(DEPENDENCY_MANIFEST)
    input_lock = _read_json_strict(INPUT_MANIFEST)
    _verify_hash_map(dependency_lock["files"])
    _verify_hash_map(input_lock["files"])
    tree_rows = []
    for tree in dependency_lock["source_trees"]:
        actual = _tree_lock(REPO / tree["root"])
        expected = {
            "root": tree["root"],
            "file_count": int(tree["file_count"]),
            "sha256": tree["sha256"],
        }
        if actual != expected:
            raise RuntimeError(
                f"source-tree lock mismatch: {tree['root']}: {actual} != {expected}"
            )
        tree_rows.append(actual)
    tracked = _git(
        [
            "ls-files",
            "--error-unmatch",
            *sorted(dependency_lock["files"]),
        ]
    ).splitlines()
    if len(tracked) != len(dependency_lock["files"]):
        raise RuntimeError("not every dependency-lock file is tracked")
    protected = {str(path.relative_to(REPO)): _sha256(path) for path in PROTECTED_FILES}
    expected_protected = {
        path: digest
        for path, digest in dependency_lock["files"].items()
        if path in {str(item.relative_to(REPO)) for item in PROTECTED_FILES}
    }
    if protected != expected_protected:
        raise RuntimeError("protected-file lock is incomplete or mismatched")

    global_attempts: list[str] = []
    test_stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_module)
    with _forbid_route_search(global_attempts):
        test_result = unittest.TextTestRunner(
            stream=test_stream,
            verbosity=2,
        ).run(suite)
    if not test_result.wasSuccessful():
        raise RuntimeError("zero-search unit tests failed:\n" + test_stream.getvalue())
    if global_attempts:
        raise RuntimeError(f"unit tests attempted route search: {global_attempts}")
    guard_probe: list[str] = []
    with _forbid_route_search(guard_probe):
        try:
            prototype_module.run_pure_alns(
                BINDING_BUNDLE,
                seed=1,
                eval_budget=1,
                prices=PRICES_280,
            )
        except RuntimeError as exc:
            if "blocked route search" not in str(exc):
                raise
        else:
            raise RuntimeError("route-search guard probe did not block the entrypoint")
    if len(guard_probe) != 1:
        raise RuntimeError(f"route-search guard probe drifted: {guard_probe}")
    _ledger_tamper_probe()
    return {
        "status": "PASS",
        "git_head": _git(["rev-parse", "HEAD"]).strip(),
        "git_clean": True,
        "output_absent": True,
        "dependency_file_count": len(dependency_lock["files"]),
        "input_file_count": len(input_lock["files"]),
        "source_tree_locks": tree_rows,
        "protected_hashes": protected,
        "unit_tests_run": test_result.testsRun,
        "unit_test_failures": len(test_result.failures),
        "unit_test_errors": len(test_result.errors),
        "route_search_guard_installed": True,
        "route_search_guard_probe_passed": True,
        "route_search_guard_probe": guard_probe,
        "ledger_tamper_probe_passed": True,
        "route_search_attempts": global_attempts,
        "unit_test_log": test_stream.getvalue(),
    }


def _run_once(preflight: dict[str, Any]) -> int:
    OUTPUT_DIR.mkdir(parents=False, exist_ok=False)
    route_search_attempts: list[str] = []
    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    try:
        binding_source = _saved_final(
            "L-main-threeshift-20c-01",
            "control",
        )
        nonbinding_source = _saved_final(
            "L-main-threeshift-25c-01",
            "control",
        )
        with _forbid_route_search(route_search_attempts):
            binding = solver.apply_fuel_route_retirement_ev_repack(
                BINDING_BUNDLE,
                binding_source,
                prices=PRICES_280,
            )
            nonbinding = solver.apply_fuel_route_retirement_ev_repack(
                NONBINDING_BUNDLE,
                nonbinding_source,
                prices=PRICES_280,
            )
        rows = [
            _result_row(
                "binding_seen_training_20c",
                BINDING_BUNDLE,
                binding_source,
                binding,
            ),
            _result_row(
                "all_ev_nonbinding_25c",
                NONBINDING_BUNDLE,
                nonbinding_source,
                nonbinding,
            ),
        ]
        for scenario, source, result in (
            ("binding_seen_training_20c", binding_source, binding),
            (
                "all_ev_nonbinding_25c",
                nonbinding_source,
                nonbinding,
            ),
        ):
            _add_witness(
                witnesses,
                source,
                {"scenario": scenario, "kind": "source"},
            )
            _add_witness(
                witnesses,
                result.solution,
                {"scenario": scenario, "kind": "final"},
            )
            for exact_index, exact in enumerate(
                result.activity.get("exact_candidates", []),
                start=1,
            ):
                for kind, key in (
                    ("neutral", "neutral_solution_snapshot"),
                    ("completed", "completed_solution_snapshot"),
                ):
                    snapshot = exact.get(key)
                    if snapshot is not None:
                        _add_witness(
                            witnesses,
                            _solution_from_dict(snapshot),
                            {
                                "scenario": scenario,
                                "kind": kind,
                                "exact_candidate": exact_index,
                            },
                        )
        decision = _decision(
            rows,
            route_search_attempts,
            preflight,
        )
        metadata = {
            "schema_version": ("resetp.fuel-route-retirement-behavior.v1"),
            "status": "SEALED_NORMAL_OUTCOME",
            "evidence_level": "TRAINING_BEHAVIOR_ONLY",
            "formal_search_allowed": False,
            "stage2_allowed": False,
            "fresh_d3_allowed": bool(
                decision["verdict"] == "GO_FRESH_D3_CONTRACT_PREPARATION_ONLY"
            ),
            "git_head": preflight["git_head"],
            "preflight": preflight,
            "route_search_attempts": route_search_attempts,
            "dependency_manifest": str(DEPENDENCY_MANIFEST.relative_to(REPO)),
            "dependency_manifest_sha256": _sha256(DEPENDENCY_MANIFEST),
            "input_manifest": str(INPUT_MANIFEST.relative_to(REPO)),
            "input_manifest_sha256": _sha256(INPUT_MANIFEST),
            "prices": {"battery_kwh": float(PRICES_280.B_battery_kwh)},
        }
        _write_normal_artifacts(
            rows,
            decision,
            metadata,
            witnesses,
        )
        _seal_and_verify()
        print(decision["verdict"])
        return (
            0 if decision["verdict"] == "GO_FRESH_D3_CONTRACT_PREPARATION_ONLY" else 1
        )
    except Exception as exc:  # noqa: BLE001
        _write_failure_artifacts(
            exc,
            rows,
            route_search_attempts,
            preflight,
        )
        _seal_and_verify()
        print(f"INCONCLUSIVE_EXECUTION_FAILURE: {type(exc).__name__}: {exc}")
        return 2


def _result_row(
    scenario: str,
    bundle_dir: Path,
    source: Solution,
    result: solver.FuelRouteRetirementResult,
) -> dict[str, Any]:
    bundle = load_search_bundle(bundle_dir)
    source_cost = _independent_cost(bundle, source)
    final_cost = _independent_cost(bundle, result.solution)
    source_violations = check_solution(
        source,
        bundle.instance,
        PRICES_280,
    )
    final_violations = check_solution(
        result.solution,
        bundle.instance,
        PRICES_280,
    )
    source_coverage = solver._customer_counter(
        source,
        bundle.instance,
    )
    final_coverage = solver._customer_counter(
        result.solution,
        bundle.instance,
    )
    activity = result.activity
    row = {
        "scenario": scenario,
        "bundle": str(bundle_dir.relative_to(REPO)),
        "source_cost": float(source_cost),
        "final_cost": float(final_cost),
        "objective_delta": float(final_cost - source_cost),
        "improvement_percent": float(100.0 * (source_cost - final_cost) / source_cost),
        "claimed_final_cost": float(result.cost),
        "claim_replay_error": abs(float(result.cost) - final_cost),
        "source_feasible": not source_violations,
        "final_feasible": not final_violations,
        "source_violation_count": len(source_violations),
        "final_violation_count": len(final_violations),
        "customer_coverage_closed": (source_coverage == final_coverage),
        "source_cv_routes": solver._cv_route_count(source),
        "final_cv_routes": solver._cv_route_count(result.solution),
        "source_route_count": len(source.routes),
        "final_route_count": len(result.solution.routes),
        "changed": bool(result.changed),
        "accepted_count": len(activity["accepted_moves"]),
        "repair_attempts": int(activity["repair_attempts"]),
        "one_level_ejection_attempts": int(activity["one_level_ejection_attempts"]),
        "unique_repack_candidates": int(activity["unique_repack_candidates"]),
        "candidate_completion_calls": int(activity["candidate_completion_calls"]),
        "counterfactual_completion_calls": int(
            activity["counterfactual_completion_calls"]
        ),
        "total_completion_calls": int(activity["total_completion_calls"]),
        "candidate_full_replays": int(activity["candidate_full_replays"]),
        "candidate_independent_replays": int(activity["candidate_independent_replays"]),
        "total_full_replays": int(activity["total_full_replays"]),
        "complete_route_search_evaluations": int(
            activity["complete_route_search_evaluations"]
        ),
        "source_full_content_sha256": solver._full_content_hash(source),
        "final_full_content_sha256": solver._full_content_hash(result.solution),
        "source_semantic_sha256": solver._semantic_solution_hash(source),
        "final_semantic_sha256": solver._semantic_solution_hash(result.solution),
        "source_route_skeleton_sha256": (
            solver._route_skeleton_hash(source, bundle.instance)
        ),
        "final_route_skeleton_sha256": (
            solver._route_skeleton_hash(
                result.solution,
                bundle.instance,
            )
        ),
        "exact_noop": asdict(source) == asdict(result.solution),
        "activity_ledgers_closed": _activity_ledgers_closed(activity),
        "accepted_nonvacuous": (
            len(activity["accepted_moves"]) > 0
            and all(bool(item.get("eligible")) for item in activity["accepted_moves"])
        ),
        "accepted_all_source_retired": (
            len(activity["accepted_moves"]) > 0
            and all(
                bool(item.get("source_route_retired"))
                for item in activity["accepted_moves"]
            )
        ),
        "completed_skeletons_all_fixed": (
            any(
                not item.get("candidate_failed_closed")
                for item in activity["exact_candidates"]
            )
            and all(
                bool(item.get("fixed_skeleton_preserved"))
                for item in activity["exact_candidates"]
                if not item.get("candidate_failed_closed")
            )
        ),
        "elapsed_seconds": float(activity["elapsed_seconds"]),
        "activity": activity,
    }
    for key in (
        "source_cost",
        "final_cost",
        "objective_delta",
        "improvement_percent",
        "claimed_final_cost",
        "claim_replay_error",
        "elapsed_seconds",
    ):
        if not math.isfinite(float(row[key])):
            raise RuntimeError(f"non-finite result field: {key}")
    return row


def _decision(
    rows: list[dict[str, Any]],
    route_search_attempts: list[str],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    binding, nonbinding = rows
    checks = {
        "preflight_passed": preflight["status"] == "PASS",
        "route_search_guard_quiet": not route_search_attempts,
        "reported_route_search_zero": all(
            row["complete_route_search_evaluations"] == 0 for row in rows
        ),
        "both_sources_and_finals_feasible": all(
            row["source_feasible"] and row["final_feasible"] for row in rows
        ),
        "both_replays_close": all(row["claim_replay_error"] <= 1.0e-7 for row in rows),
        "both_customer_coverages_close": all(
            row["customer_coverage_closed"] for row in rows
        ),
        "both_activity_ledgers_close": all(
            row["activity_ledgers_closed"] for row in rows
        ),
        "binding_source_cost_matches_frozen": abs(
            binding["source_cost"] - FIXED_BINDING_SOURCE_COST
        )
        <= 1.0e-7,
        "binding_strictly_improves": (
            binding["final_cost"] < FIXED_BINDING_SOURCE_COST - 1.0e-9
        ),
        "binding_cv_routes_drop_one_to_zero": (
            binding["source_cv_routes"] == 1 and binding["final_cv_routes"] == 0
        ),
        "binding_route_count_not_increased": (
            binding["final_route_count"] <= binding["source_route_count"]
        ),
        "binding_has_real_acceptance": (
            binding["accepted_count"] > 0 and binding["accepted_nonvacuous"]
        ),
        "binding_source_route_retired": (binding["accepted_all_source_retired"]),
        "binding_fixed_skeleton_completion": (binding["completed_skeletons_all_fixed"]),
        "binding_candidate_completion_cap": (
            binding["candidate_completion_calls"] <= 4
        ),
        "binding_counterfactual_completion_cap": (
            binding["counterfactual_completion_calls"] <= 1
        ),
        "binding_has_repack_candidate": (binding["unique_repack_candidates"] > 0),
        "nonbinding_source_all_ev": (nonbinding["source_cv_routes"] == 0),
        "nonbinding_exact_noop": nonbinding["exact_noop"],
        "nonbinding_zero_repair": (nonbinding["repair_attempts"] == 0),
        "nonbinding_zero_completion": (
            nonbinding["candidate_completion_calls"] == 0
            and nonbinding["counterfactual_completion_calls"] == 0
        ),
        "nonbinding_zero_candidate_replay": (
            nonbinding["candidate_full_replays"] == 0
            and nonbinding["candidate_independent_replays"] == 0
        ),
        "nonbinding_zero_acceptance": (nonbinding["accepted_count"] == 0),
    }
    passed = all(checks.values())
    return {
        "schema_version": ("resetp.fuel-route-retirement-decision.v1"),
        "verdict": (
            "GO_FRESH_D3_CONTRACT_PREPARATION_ONLY"
            if passed
            else "STOP_FUEL_ROUTE_RETIREMENT_EV_REPACK_BEHAVIOR"
        ),
        "passed": passed,
        "checks": checks,
        "evidence_level": "TRAINING_BEHAVIOR_ONLY",
        "fresh_d3_allowed": passed,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "full_benchmark_allowed": False,
    }


def _activity_ledgers_closed(activity: dict[str, Any]) -> bool:
    if not isinstance(activity, dict):
        return False
    count_names = (
        "source_cv_route_count",
        "source_full_replays",
        "source_feasibility_checks",
        "source_routes_considered",
        "repair_attempts",
        "one_level_ejection_attempts",
        "ejection_seed_scoring_attempts",
        "repair_failures",
        "coverage_rejections",
        "unchanged_repair_rejections",
        "ejection_return_rejections",
        "nonfinite_prescore_rejections",
        "repack_candidates_built",
        "duplicate_skeleton_candidates",
        "insertion_positions_evaluated",
        "coverage_invariant_checks",
        "new_route_attempts",
        "recursive_ejection_attempts",
        "route_plan_local_feasibility_checks",
        "route_plan_variant_calls",
        "route_plan_charge_repair_calls",
        "route_plan_proxy_evaluations",
        "route_plan_proxy_cache_hits",
        "unique_repack_candidates",
        "counterfactual_completion_calls",
        "candidate_completion_calls",
        "candidate_completion_failures",
        "completion_route_proxy_evaluations",
        "completion_route_local_schedule_evaluations",
        "completion_full_feasibility_checks",
        "counterfactual_full_replays",
        "candidate_full_replays",
        "candidate_independent_replays",
        "final_full_replays",
        "counterfactual_feasibility_checks",
        "candidate_feasibility_checks",
        "final_feasibility_checks",
        "complete_route_search_evaluations",
        "total_completion_calls",
        "total_full_replays",
        "total_feasibility_checks",
        "final_cv_route_count",
        "effective_ejection_seed_limit",
    )
    if any(
        name not in activity or not _is_nonnegative_int(activity[name])
        for name in count_names
    ):
        return False
    if (
        type(activity.get("changed")) is not bool
        or activity.get("config") != asdict(solver.FuelRouteRetirementConfig())
        or activity["effective_ejection_seed_limit"] not in {0, 8}
    ):
        return False
    list_names = (
        "completion_activity_records",
        "exact_candidates",
        "accepted_moves",
        "round_summaries",
        "enumeration_fail_closed",
        "round_fail_closed",
    )
    if any(not isinstance(activity.get(name), list) for name in list_names):
        return False
    if (
        activity["enumeration_fail_closed"]
        or activity["round_fail_closed"]
        or "final_fail_closed" in activity
        or "discarded_accepted_moves" in activity
    ):
        return False

    summaries = activity["round_summaries"]
    if not 1 <= len(summaries) <= 2:
        return False
    summary_exact: Counter[int] = Counter()
    summary_eligible: Counter[int] = Counter()
    accepted_summary_count = 0
    for expected_round, row in enumerate(summaries, start=1):
        if not isinstance(row, dict):
            return False
        required_counts = (
            "round",
            "source_cv_routes",
            "sources_considered",
            "repair_candidates",
            "exact_attempted",
            "eligible_candidates",
        )
        if any(
            key not in row or not _is_nonnegative_int(row[key])
            for key in required_counts
        ):
            return False
        if (
            row["round"] != expected_round
            or row["sources_considered"] > min(row["source_cv_routes"], 2)
            or row["exact_attempted"] != min(row["repair_candidates"], 4)
            or row["eligible_candidates"] > row["exact_attempted"]
            or type(row.get("accepted")) is not bool
            or row["accepted"] != (row["eligible_candidates"] > 0)
        ):
            return False
        prescore_selected = row.get("prescore_selected", 0)
        if not _is_nonnegative_int(prescore_selected) or prescore_selected != min(
            row["repair_candidates"], 10
        ):
            return False
        summary_exact[row["round"]] = row["exact_attempted"]
        summary_eligible[row["round"]] = row["eligible_candidates"]
        accepted_summary_count += int(row["accepted"])

    exact_rows = activity["exact_candidates"]
    exact_by_round: Counter[int] = Counter()
    eligible_by_round: Counter[int] = Counter()
    candidate_replay_attempts = 0
    candidate_independent_attempts = 0
    candidate_feasibility_attempts = 0
    candidate_failure_count = 0
    eligible_witnesses: Counter[tuple[int, str]] = Counter()
    for row in exact_rows:
        if not isinstance(row, dict):
            return False
        round_number = row.get("round")
        replay_attempts = row.get("candidate_full_replay_attempts")
        feasibility_attempts = row.get("candidate_feasibility_check_attempts")
        failed = row.get("candidate_failed_closed")
        eligible = row.get("eligible")
        if (
            not _is_nonnegative_int(round_number)
            or round_number not in summary_exact
            or not _is_nonnegative_int(replay_attempts)
            or replay_attempts > 2
            or not _is_nonnegative_int(feasibility_attempts)
            or feasibility_attempts > 1
            or type(failed) is not bool
            or type(eligible) is not bool
            or (failed and eligible)
        ):
            return False
        if not failed:
            replay_error = row.get("independent_replay_error")
            if (
                replay_attempts != 2
                or feasibility_attempts != 1
                or not _is_finite_number(replay_error)
                or float(replay_error) > 1.0e-7
                or not _is_finite_number(row.get("completed_cost"))
                or not _is_finite_number(row.get("independent_replay_cost"))
            ):
                return False
        candidate_failure_count += int(failed)
        exact_by_round[round_number] += 1
        eligible_by_round[round_number] += int(eligible)
        candidate_replay_attempts += replay_attempts
        candidate_independent_attempts += max(0, replay_attempts - 1)
        candidate_feasibility_attempts += feasibility_attempts
        if eligible:
            digest = row.get("completed_full_content_sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                return False
            eligible_witnesses[(round_number, digest)] += 1
    if exact_by_round != summary_exact:
        return False
    if eligible_by_round != summary_eligible:
        return False

    accepted_rows = activity["accepted_moves"]
    accepted_witnesses: Counter[tuple[int, str]] = Counter()
    for row in accepted_rows:
        if (
            not isinstance(row, dict)
            or row.get("eligible") is not True
            or row.get("candidate_failed_closed") is not False
            or not _is_nonnegative_int(row.get("round"))
        ):
            return False
        digest = row.get("completed_full_content_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            return False
        accepted_witnesses[(row["round"], digest)] += 1
    if (
        len(accepted_rows) != accepted_summary_count
        or any(
            accepted_witnesses[key] > eligible_witnesses[key]
            for key in accepted_witnesses
        )
        or activity["changed"] != bool(accepted_rows)
    ):
        return False

    completion_records = activity["completion_activity_records"]
    kind_counts: Counter[str] = Counter()
    completion_route_proxy_sum = 0
    completion_schedule_sum = 0
    completion_feasibility_sum = 0
    completion_route_search_sum = 0
    for record in completion_records:
        if not isinstance(record, dict):
            return False
        kind = record.get("kind")
        payload = record.get("activity")
        if kind not in {
            "counterfactual",
            "counterfactual_failure",
            "candidate",
            "candidate_failure",
        }:
            return False
        kind_counts[kind] += 1
        if kind.endswith("_failure"):
            if payload is not None:
                return False
            continue
        if not isinstance(payload, dict):
            return False
        nested_counts = (
            "route_proxy_evaluations",
            "route_local_schedule_evaluations",
            "full_feasibility_checks",
            "complete_candidate_evaluations",
            "complete_route_search_evaluations",
            "search_candidate_score_calls",
        )
        if any(
            key not in payload or not _is_nonnegative_int(payload[key])
            for key in nested_counts
        ):
            return False
        if not (
            payload["complete_candidate_evaluations"]
            == payload["complete_route_search_evaluations"]
            == payload["search_candidate_score_calls"]
        ):
            return False
        completion_route_proxy_sum += payload["route_proxy_evaluations"]
        completion_schedule_sum += payload["route_local_schedule_evaluations"]
        completion_feasibility_sum += payload["full_feasibility_checks"]
        completion_route_search_sum += payload["complete_route_search_evaluations"]

    expected_candidate_calls = sum(summary_exact.values())
    expected_counterfactual_calls = sum(value > 0 for value in summary_exact.values())
    repair_outcomes = sum(
        activity[name]
        for name in (
            "repair_failures",
            "coverage_rejections",
            "unchanged_repair_rejections",
            "ejection_return_rejections",
            "nonfinite_prescore_rejections",
            "repack_candidates_built",
        )
    )
    full_replay_sum = sum(
        activity[name]
        for name in (
            "source_full_replays",
            "counterfactual_full_replays",
            "candidate_full_replays",
            "final_full_replays",
        )
    )
    feasibility_sum = sum(
        activity[name]
        for name in (
            "source_feasibility_checks",
            "counterfactual_feasibility_checks",
            "candidate_feasibility_checks",
            "final_feasibility_checks",
            "completion_full_feasibility_checks",
        )
    )
    ejection_limit = activity["effective_ejection_seed_limit"]
    return bool(
        activity["source_full_replays"] == 1
        and activity["source_feasibility_checks"] == 1
        and activity["final_full_replays"] == 1
        and activity["final_feasibility_checks"] == 1
        and activity["source_routes_considered"]
        == sum(row["sources_considered"] for row in summaries)
        and activity["repair_attempts"]
        == activity["source_routes_considered"]
        + activity["one_level_ejection_attempts"]
        and activity["repair_attempts"] == repair_outcomes
        and activity["repack_candidates_built"]
        == activity["unique_repack_candidates"]
        + activity["duplicate_skeleton_candidates"]
        and activity["unique_repack_candidates"]
        == sum(row["repair_candidates"] for row in summaries)
        and activity["one_level_ejection_attempts"]
        <= activity["ejection_seed_scoring_attempts"]
        and activity["one_level_ejection_attempts"]
        <= activity["source_routes_considered"] * ejection_limit
        and (
            ejection_limit != 0
            or (
                activity["one_level_ejection_attempts"] == 0
                and activity["ejection_seed_scoring_attempts"] == 0
            )
        )
        and activity["candidate_completion_calls"] == expected_candidate_calls
        and activity["counterfactual_completion_calls"] == expected_counterfactual_calls
        and activity["total_completion_calls"]
        == activity["candidate_completion_calls"]
        + activity["counterfactual_completion_calls"]
        and len(exact_rows) == activity["candidate_completion_calls"]
        and len(completion_records) == activity["total_completion_calls"]
        and kind_counts["candidate"] + kind_counts["candidate_failure"]
        == activity["candidate_completion_calls"]
        and kind_counts["counterfactual"] + kind_counts["counterfactual_failure"]
        == activity["counterfactual_completion_calls"]
        and candidate_failure_count == activity["candidate_completion_failures"]
        and candidate_replay_attempts == activity["candidate_full_replays"]
        and candidate_independent_attempts == activity["candidate_independent_replays"]
        and candidate_feasibility_attempts == activity["candidate_feasibility_checks"]
        and completion_route_proxy_sum == activity["completion_route_proxy_evaluations"]
        and completion_schedule_sum
        == activity["completion_route_local_schedule_evaluations"]
        and completion_feasibility_sum == activity["completion_full_feasibility_checks"]
        and completion_route_search_sum == activity["complete_route_search_evaluations"]
        and full_replay_sum == activity["total_full_replays"]
        and feasibility_sum == activity["total_feasibility_checks"]
        and activity["new_route_attempts"] == 0
        and activity["recursive_ejection_attempts"] == 0
        and activity["complete_route_search_evaluations"] == 0
    )


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _ledger_tamper_probe() -> None:
    clean = solver._new_activity(Solution(routes=[]))
    clean["round_summaries"] = [
        {
            "round": 1,
            "source_cv_routes": 0,
            "sources_considered": 0,
            "repair_candidates": 0,
            "exact_attempted": 0,
            "eligible_candidates": 0,
            "accepted": False,
        }
    ]
    clean["final_full_replays"] = 1
    clean["final_feasibility_checks"] = 1
    clean["final_cv_route_count"] = 0
    clean["changed"] = False
    clean["config"] = asdict(solver.FuelRouteRetirementConfig())
    clean["effective_ejection_seed_limit"] = 8
    clean["total_completion_calls"] = 0
    clean["total_full_replays"] = 2
    clean["total_feasibility_checks"] = 2
    if not _activity_ledgers_closed(clean):
        raise RuntimeError("clean ledger probe did not close")

    zero_completion = {
        "route_proxy_evaluations": 0,
        "route_local_schedule_evaluations": 0,
        "full_feasibility_checks": 0,
        "complete_candidate_evaluations": 0,
        "complete_route_search_evaluations": 0,
        "search_candidate_score_calls": 0,
    }
    active = copy.deepcopy(clean)
    active.update(
        {
            "source_cv_route_count": 1,
            "source_routes_considered": 1,
            "repair_attempts": 1,
            "repack_candidates_built": 1,
            "unique_repack_candidates": 1,
            "counterfactual_completion_calls": 1,
            "candidate_completion_calls": 1,
            "candidate_full_replays": 2,
            "candidate_independent_replays": 1,
            "counterfactual_full_replays": 1,
            "counterfactual_feasibility_checks": 1,
            "candidate_feasibility_checks": 1,
            "final_cv_route_count": 1,
            "total_completion_calls": 2,
            "total_full_replays": 5,
            "total_feasibility_checks": 4,
            "round_summaries": [
                {
                    "round": 1,
                    "source_cv_routes": 1,
                    "sources_considered": 1,
                    "repair_candidates": 1,
                    "prescore_selected": 1,
                    "exact_attempted": 1,
                    "eligible_candidates": 0,
                    "accepted": False,
                }
            ],
            "completion_activity_records": [
                {
                    "kind": "counterfactual",
                    "activity": copy.deepcopy(zero_completion),
                },
                {
                    "kind": "candidate",
                    "activity": copy.deepcopy(zero_completion),
                },
            ],
            "exact_candidates": [
                {
                    "round": 1,
                    "candidate_failed_closed": False,
                    "eligible": False,
                    "candidate_full_replay_attempts": 2,
                    "candidate_feasibility_check_attempts": 1,
                    "completed_cost": 10.0,
                    "independent_replay_cost": 10.0,
                    "independent_replay_error": 0.0,
                    "completed_full_content_sha256": "0" * 64,
                }
            ],
        }
    )
    if not _activity_ledgers_closed(active):
        raise RuntimeError("active ledger probe did not close")

    mutations: list[dict[str, Any]] = []
    wrong_full = copy.deepcopy(clean)
    wrong_full["total_full_replays"] += 1
    mutations.append(wrong_full)
    fake_exact = copy.deepcopy(clean)
    fake_exact["exact_candidates"].append({"eligible": False})
    mutations.append(fake_exact)
    fake_completion = copy.deepcopy(clean)
    fake_completion["completion_activity_records"].append(
        {
            "kind": "fabricated",
            "activity": copy.deepcopy(zero_completion),
        }
    )
    mutations.append(fake_completion)
    bool_route_search = copy.deepcopy(clean)
    bool_route_search["complete_route_search_evaluations"] = False
    mutations.append(bool_route_search)
    bool_source_replay = copy.deepcopy(clean)
    bool_source_replay["source_full_replays"] = True
    mutations.append(bool_source_replay)
    bool_summary = copy.deepcopy(clean)
    bool_summary["round_summaries"][0]["exact_attempted"] = False
    mutations.append(bool_summary)
    fabricated_kinds = copy.deepcopy(active)
    for record in fabricated_kinds["completion_activity_records"]:
        record["kind"] = "fabricated"
    mutations.append(fabricated_kinds)
    if any(_activity_ledgers_closed(item) for item in mutations):
        raise RuntimeError("ledger tamper probe accepted a mutation")


def _write_normal_artifacts(
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
    metadata: dict[str, Any],
    witnesses: dict[str, Any],
) -> None:
    _write_json(OUTPUT_DIR / "metadata.json", metadata)
    _write_raw_runs(rows)
    _write_json(OUTPUT_DIR / "decision.json", decision)
    _write_json(
        OUTPUT_DIR / "solution_witnesses.json",
        witnesses,
    )
    (OUTPUT_DIR / "report.md").write_text(
        _report(rows, decision),
        encoding="utf-8",
    )


def _write_failure_artifacts(
    exc: Exception,
    rows: list[dict[str, Any]],
    route_search_attempts: list[str],
    preflight: dict[str, Any],
) -> None:
    metadata = {
        "schema_version": ("resetp.fuel-route-retirement-behavior.v1"),
        "status": "INCONCLUSIVE_EXECUTION_FAILURE",
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "fresh_d3_allowed": False,
        "git_head": preflight.get("git_head"),
        "preflight": preflight,
        "route_search_attempts": route_search_attempts,
    }
    decision = {
        "schema_version": ("resetp.fuel-route-retirement-decision.v1"),
        "verdict": "INCONCLUSIVE_EXECUTION_FAILURE",
        "passed": False,
        "fresh_d3_allowed": False,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "failure_type": type(exc).__name__,
        "failure_message": str(exc),
    }
    _write_json(OUTPUT_DIR / "metadata.json", metadata)
    _write_raw_runs(rows)
    _write_json(OUTPUT_DIR / "decision.json", decision)
    _write_json(OUTPUT_DIR / "solution_witnesses.json", {})
    _write_json(
        OUTPUT_DIR / "execution_failure.json",
        {
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "completed_scenario_count": len(rows),
            "route_search_attempts": route_search_attempts,
        },
    )
    (OUTPUT_DIR / "report.md").write_text(
        "# 燃油路线退役—电动重整：执行失败\n\n"
        "判定：`INCONCLUSIVE_EXECUTION_FAILURE`。\n\n"
        f"{type(exc).__name__}: {exc}\n",
        encoding="utf-8",
    )


def _write_raw_runs(rows: list[dict[str, Any]]) -> None:
    fields = [
        "scenario",
        "bundle",
        "source_cost",
        "final_cost",
        "objective_delta",
        "improvement_percent",
        "claimed_final_cost",
        "claim_replay_error",
        "source_feasible",
        "final_feasible",
        "customer_coverage_closed",
        "source_cv_routes",
        "final_cv_routes",
        "source_route_count",
        "final_route_count",
        "changed",
        "accepted_count",
        "repair_attempts",
        "one_level_ejection_attempts",
        "unique_repack_candidates",
        "candidate_completion_calls",
        "counterfactual_completion_calls",
        "total_completion_calls",
        "candidate_full_replays",
        "total_full_replays",
        "complete_route_search_evaluations",
        "source_full_content_sha256",
        "final_full_content_sha256",
        "source_semantic_sha256",
        "final_semantic_sha256",
        "source_route_skeleton_sha256",
        "final_route_skeleton_sha256",
        "exact_noop",
        "activity_ledgers_closed",
        "accepted_nonvacuous",
        "accepted_all_source_retired",
        "completed_skeletons_all_fixed",
        "elapsed_seconds",
        "activity_json",
    ]
    with (OUTPUT_DIR / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flat = {key: row.get(key) for key in fields}
            flat["activity_json"] = json.dumps(
                row["activity"],
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            writer.writerow(flat)


def _report(
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# 燃油路线退役—电动重整：零搜索行为门",
        "",
        f"判定：`{decision['verdict']}`。",
        "",
        "20客户题只作已见训练行为检查；25客户题只作全电零动作检查。",
        "本门没有启动ALNS、HGS、阶段二、正式算例或全量实验。",
        "",
        "| 场景 | 原成本 | 新成本 | 改善 | 燃油路线 | 接受 | 腾位尝试 | 完成调用 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['scenario']} | {row['source_cost']:.9f} | "
            f"{row['final_cost']:.9f} | "
            f"{row['improvement_percent']:.6f}% | "
            f"{row['source_cv_routes']}→{row['final_cv_routes']} | "
            f"{row['accepted_count']} | "
            f"{row['one_level_ejection_attempts']} | "
            f"{row['total_completion_calls']} |"
        )
    lines.extend(
        [
            "",
            "## 验收",
            "",
        ]
    )
    for name, passed in decision.get("checks", {}).items():
        lines.append(f"- `{name}`: `{bool(passed)}`")
    lines.extend(
        [
            "",
            "通过也只允许准备一张新的结果盲D3合同；不自动授权D3运行、正式算法比较或阶段二。",
            "",
        ]
    )
    return "\n".join(lines)


def _seal_and_verify() -> None:
    sidecars = sorted(
        str(path.relative_to(OUTPUT_DIR)) for path in OUTPUT_DIR.rglob("._*")
    )
    if sidecars:
        raise RuntimeError(f"AppleDouble sidecars found: {sidecars}")
    _write_json(
        OUTPUT_DIR / "appledouble_seal.json",
        {
            "schema_version": "resetp.appledouble-seal.v1",
            "sidecars": [],
            "passed": True,
        },
    )
    artifacts = {
        path.name: _sha256(path)
        for path in sorted(OUTPUT_DIR.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(
        OUTPUT_DIR / "artifact_hashes.json",
        {
            "schema_version": ("resetp.fuel-route-retirement-artifacts.v1"),
            "artifacts": artifacts,
        },
    )
    reread = _read_json_strict(OUTPUT_DIR / "artifact_hashes.json")
    if reread["artifacts"] != artifacts:
        raise RuntimeError("artifact hash manifest reread drifted")
    for name, digest in artifacts.items():
        path = OUTPUT_DIR / name
        if path.is_symlink() or _sha256(path) != digest:
            raise RuntimeError(f"artifact hash mismatch: {name}")
    for json_path in OUTPUT_DIR.glob("*.json"):
        _read_json_strict(json_path)


def _saved_final(instance: str, arm: str) -> Solution:
    payload = _read_json_strict(WITNESSES)
    for row in payload.values():
        if any(
            use.get("kind") == "final"
            and use.get("instance") == instance
            and use.get("arm") == arm
            for use in row.get("uses", [])
        ):
            return _solution_from_dict(row["solution"])
    raise RuntimeError(f"missing saved final: {instance}/{arm}")


def _solution_from_dict(raw: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                str(route["vehicle_id"]),
                str(route["vehicle_type"]),
                str(route["home_depot_id"]),
                [str(item) for item in route["node_sequence"]],
            )
            for route in raw.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                str(action["vehicle_id"]),
                str(action["station_id"]),
                float(action["energy_kwh"]),
                float(action["occupancy_minutes"]),
                float(action["charge_start_second"]),
                int(action.get("charge_day_offset", 0)),
            )
            for action in raw.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                str(item["customer_id"]),
                str(item["served_by_depot_id"]),
            )
            for item in raw.get("cross_site_services", [])
        ],
    )


def _add_witness(
    witnesses: dict[str, Any],
    solution: Solution,
    use: dict[str, Any],
) -> None:
    digest = solver._full_content_hash(solution)
    if digest not in witnesses:
        witnesses[digest] = {
            "solution": asdict(solution),
            "uses": [],
        }
    witnesses[digest]["uses"].append(use)


def _independent_cost(bundle: Any, solution: Solution) -> float:
    value = float(
        evaluate(
            solution,
            bundle.instance,
            bundle.carbon_profile,
            PRICES_280,
        )["total_cost"]
    )
    if not math.isfinite(value):
        raise RuntimeError("independent cost is non-finite")
    return value


@contextmanager
def _forbid_route_search(
    global_attempts: list[str],
) -> Any:
    state = {"installed": True, "attempts": []}

    def blocker(label: str) -> Any:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            state["attempts"].append(label)
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
            stack.enter_context(patch.object(module, name, blocker(label)))
        stack.enter_context(
            patch.object(
                subprocess,
                "Popen",
                blocker("external_process"),
            )
        )
        stack.enter_context(patch.object(os, "system", blocker("os_system")))
        yield state


def _verify_hash_map(files: dict[str, str]) -> None:
    for relative, expected in files.items():
        path = REPO / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"locked file missing or symlinked: {relative}")
        actual = _sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"locked file hash mismatch: {relative}: {actual} != {expected}"
            )


def _tree_lock(root: Path) -> dict[str, Any]:
    files = sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
    )
    lines = [f"{path.relative_to(REPO).as_posix()}:{_sha256(path)}" for path in files]
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    return {
        "root": root.relative_to(REPO).as_posix(),
        "file_count": len(files),
        "sha256": digest,
    }


def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _read_json_strict(path: Path) -> Any:
    def reject(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant: {value}")
        ),
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
