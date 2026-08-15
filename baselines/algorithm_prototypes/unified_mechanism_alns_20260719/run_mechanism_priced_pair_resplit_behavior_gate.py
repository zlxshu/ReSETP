"""Preflight, blind-lock, and one-shot zero-search pair-resplit behaviour gate."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mechanism_priced_pair_resplit_fixtures import (  # noqa: E402
    binding_fixture,
    joint_station_conflict_fixture,
    nonbinding_fixture,
)
from mechanism_priced_pair_resplit_oracle import (  # noqa: E402
    exhaustive_fixture_oracle,
)
from mechanism_priced_pair_resplit_solver import (  # noqa: E402
    DISTANCE_ARM,
    MECHANISM_ARM,
    _assert_arm_caps,
    _candidate_invariants,
    joint_completion_probe,
    joint_feasibility_probe,
    prepare_pair_resplit,
    run_pair_resplit_arm,
    solution_sha256,
    verify_pair_resplit_result,
    verify_prepared_pool,
)
from setp_solver.search.evaluation import model_cost  # noqa: E402
from setp_solver.solution import Route  # noqa: E402


PREFLIGHT = HERE / "mechanism_priced_pair_resplit_preflight_20260719.json"
BLIND_LOCK = HERE / "mechanism_priced_pair_resplit_blind_lock_20260719.json"
OUTPUT = HERE / "mechanism_priced_pair_resplit_behavior_gate"
VERDICT_PASS = "PASS_MECHANISM_PRICED_PAIR_RESPLIT_BEHAVIOR"
VERDICT_STOP = "STOP_MECHANISM_PRICED_PAIR_RESPLIT_BEHAVIOR"

LOCKED_FILES = (
    "docs/handoff/mechanism_priced_pair_resplit_contract_20260719.md",
    "docs/handoff/algorithm_source_and_license_register_20260719.md",
    "docs/paper_submission_final/RETIRED_paper_main.tex",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_priced_pair_resplit_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_priced_pair_resplit_fixtures.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/mechanism_priced_pair_resplit_oracle.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/test_mechanism_priced_pair_resplit_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/run_mechanism_priced_pair_resplit_behavior_gate.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/v4_mechanism_alns_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/v5_carbon_retiming_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/v7_responsibility_solver.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/fleet.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--write-blind-lock", action="store_true")
    args = parser.parse_args()
    if args.preflight_only and args.write_blind_lock:
        raise SystemExit("choose one mode")
    if args.preflight_only:
        return _run_preflight()
    if args.write_blind_lock:
        return _write_blind_lock()
    return _run_one_shot_gate()


def _run_preflight() -> int:
    if OUTPUT.exists():
        raise RuntimeError("behaviour output already exists; preflight cannot reopen it")
    test_command = [
        sys.executable,
        "-m",
        "unittest",
        "-v",
        "test_mechanism_priced_pair_resplit_solver.PairResplitPreflightTests",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO / "solver/src"),
            str(REPO / "models/src"),
            str(LEGACY),
            str(HERE),
            str(REPO),
        ]
    )
    completed = subprocess.run(
        test_command,
        cwd=REPO,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "preflight tests failed:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    binding = binding_fixture()
    binding_oracle = exhaustive_fixture_oracle(binding)
    nonbinding = nonbinding_fixture()
    nonbinding_oracle = exhaustive_fixture_oracle(nonbinding)
    if binding_oracle.global_best is None:
        raise RuntimeError("binding oracle omitted global best")
    if binding_oracle.global_best in binding_oracle.distance_order[:4]:
        raise RuntimeError("binding fixture has no ranking separation")
    if binding_oracle.global_best not in binding_oracle.mechanism_order[:4]:
        raise RuntimeError("binding fixture mechanism top4 misses global best")
    payload = {
        "schema_version": 1,
        "status": "PASS_PREFLIGHT_ONLY_NO_CANDIDATE_ARM_EXECUTED",
        "generated_unix": time.time(),
        "python": sys.version,
        "test_command": test_command,
        "test_stdout": completed.stdout,
        "test_stderr": completed.stderr,
        "locked_file_sha256": _locked_hashes(),
        "protected_file_sha256": {
            path: _sha256_file(REPO / path)
            for path in LOCKED_FILES
            if path
            in {
                "solver/src/setp_solver/cost.py",
                "solver/src/setp_solver/check.py",
                "solver/src/setp_solver/search/evaluation.py",
                "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
            }
        },
        "binding_fixture": {
            "name": binding.name,
            "source_sha256": solution_sha256(binding.source),
            "source_cost": model_cost(binding.source, binding.context),
            "candidate_count": len(binding_oracle.records),
            "candidate_set_sha256": binding_oracle.candidate_set_sha256,
            "global_best_distance_rank": (
                binding_oracle.distance_order.index(
                    binding_oracle.global_best
                )
                + 1
            ),
            "global_best_cost": binding_oracle.global_best.complete_cost,
            "global_best_left": list(binding_oracle.global_best.left_customers),
            "global_best_right": list(binding_oracle.global_best.right_customers),
        },
        "nonbinding_fixture": {
            "name": nonbinding.name,
            "source_sha256": solution_sha256(nonbinding.source),
            "source_cost": model_cost(nonbinding.source, nonbinding.context),
            "candidate_count": len(nonbinding_oracle.records),
            "best_candidate_cost": (
                None
                if nonbinding_oracle.global_best is None
                else nonbinding_oracle.global_best.complete_cost
            ),
        },
        "route_search_attempts": [],
        "behaviour_arm_runs": 0,
    }
    _write_json(PREFLIGHT, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _write_blind_lock() -> int:
    if BLIND_LOCK.exists():
        raise RuntimeError("blind lock already exists")
    if not PREFLIGHT.exists():
        raise RuntimeError("preflight file is missing")
    if _git_status():
        raise RuntimeError("write blind lock only from a clean worktree")
    preflight = _read_json(PREFLIGHT)
    current_hashes = _locked_hashes()
    if current_hashes != preflight["locked_file_sha256"]:
        raise RuntimeError("locked inputs changed after preflight")
    code_commit = _git("rev-parse", "HEAD").strip()
    payload = {
        "schema_version": 1,
        "status": "BLIND_LOCKED_BEFORE_BEHAVIOR",
        "code_commit": code_commit,
        "preflight_sha256": _sha256_file(PREFLIGHT),
        "locked_file_sha256": current_hashes,
        "allowed_paths_after_code_commit": [
            str(BLIND_LOCK.relative_to(REPO)),
        ],
        "behaviour_output_must_not_exist": str(OUTPUT.relative_to(REPO)),
        "route_search_allowed": False,
        "formal_experiment_allowed": False,
        "stage2_allowed": False,
    }
    _write_json(BLIND_LOCK, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_one_shot_gate() -> int:
    _validate_blind_lock()
    if OUTPUT.exists():
        raise RuntimeError(
            f"one-shot output already exists: {OUTPUT}; rerun is forbidden"
        )
    if _git_status():
        raise RuntimeError("one-shot gate requires a clean worktree")
    OUTPUT.mkdir(parents=False)
    started = {
        "schema_version": 1,
        "started_unix": time.time(),
        "git_head": _git("rev-parse", "HEAD").strip(),
        "blind_lock_sha256": _sha256_file(BLIND_LOCK),
        "preflight_sha256": _sha256_file(PREFLIGHT),
        "locked_file_sha256": _locked_hashes(),
        "route_search_attempts": [],
    }
    _write_json(OUTPUT / "attempt_started.json", started)
    try:
        payload = _execute_behaviour_once()
        _seal_success_or_stop(payload)
        return 0 if payload["passed"] else 2
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "passed": False,
            "verdict": VERDICT_STOP,
            "reason": "execution_exception",
            "exception_type": type(exc).__name__,
            "exception": str(exc),
            "traceback": traceback.format_exc(),
            "route_search_attempts": [],
            "formal_search_allowed": False,
            "full_benchmark_allowed": False,
            "stage2_allowed": False,
        }
        _seal_execution_exception(failure, started)
        raise


def _execute_behaviour_once() -> dict[str, Any]:
    binding = binding_fixture()
    oracle = exhaustive_fixture_oracle(binding)
    prepared = prepare_pair_resplit(binding.source, binding.context)
    verify_prepared_pool(prepared)
    oracle_boundaries = {
        (record.left_customers, record.right_customers)
        for record in oracle.records
    }
    solver_boundaries = {
        (candidate.left_customers, candidate.right_customers)
        for candidate in prepared.candidates
    }
    oracle_scores = {
        (record.left_customers, record.right_customers): (
            record.distance_score,
            record.mechanism_score,
        )
        for record in oracle.records
    }
    solver_scores_match_oracle = all(
        (
            candidate.left_customers,
            candidate.right_customers,
        )
        in oracle_scores
        and abs(
            candidate.distance_score
            - oracle_scores[
                (candidate.left_customers, candidate.right_customers)
            ][0]
        )
        <= 1.0e-7
        and abs(
            candidate.mechanism_score
            - oracle_scores[
                (candidate.left_customers, candidate.right_customers)
            ][1]
        )
        <= 1.0e-7
        for candidate in prepared.candidates
    )
    cap_results = {
        cap: run_pair_resplit_arm(
            prepared,
            arm=MECHANISM_ARM,
            exact_candidate_capacity=cap,
        )
        for cap in (0, 1, 2, 4)
    }
    mechanism = cap_results[4]
    distance = run_pair_resplit_arm(
        prepared,
        arm=DISTANCE_ARM,
        exact_candidate_capacity=4,
    )
    nonbinding = nonbinding_fixture()
    nonbinding_prepared = prepare_pair_resplit(
        nonbinding.source,
        nonbinding.context,
    )
    nonbinding_mechanism = run_pair_resplit_arm(
        nonbinding_prepared,
        arm=MECHANISM_ARM,
    )
    nonbinding_distance = run_pair_resplit_arm(
        nonbinding_prepared,
        arm=DISTANCE_ARM,
    )
    conflict = joint_station_conflict_fixture()
    conflict_left = joint_completion_probe(
        conflict.left_only,
        conflict.context,
    )
    conflict_right = joint_completion_probe(
        conflict.right_only,
        conflict.context,
    )
    conflict_joint = joint_completion_probe(
        conflict.joint,
        conflict.context,
    )
    widened_nodes = [
        replace(node, due_time=3_600.0)
        if node.node_id == "F1"
        else node
        for node in conflict.context.instance.nodes
    ]
    resolvable_conflict_context = replace(
        conflict.context,
        instance=replace(
            conflict.context.instance,
            nodes=widened_nodes,
        ),
    )
    conflict_resolvable = joint_completion_probe(
        conflict.joint,
        resolvable_conflict_context,
    )
    tamper_checks = _tamper_checks(prepared, mechanism)
    all_results = [
        *cap_results.values(),
        distance,
        nonbinding_mechanism,
        nonbinding_distance,
    ]
    for result in [*cap_results.values(), distance]:
        verify_pair_resplit_result(result, prepared)
    for result in (nonbinding_mechanism, nonbinding_distance):
        verify_pair_resplit_result(result, nonbinding_prepared)
    route_search_total = sum(
        int(result.activity["complete_route_search_evaluations"])
        for result in all_results
    )
    route_search_total += sum(
        int(activity["complete_route_search_evaluations"])
        for activity in (
            prepared.preparation_activity,
            prepared.counterfactual.activity,
            nonbinding_prepared.preparation_activity,
            nonbinding_prepared.counterfactual.activity,
        )
    )
    route_search_total += sum(
        int(probe["complete_route_search_evaluations"])
        for probe in (
            conflict_left,
            conflict_right,
            conflict_joint,
            conflict_resolvable,
        )
    )
    checks = {
        "oracle_candidate_count_at_least_6": len(oracle.records) >= 6,
        "oracle_best_not_in_distance_top4": (
            oracle.global_best is not None
            and oracle.global_best not in oracle.distance_order[:4]
        ),
        "oracle_best_in_mechanism_top4": (
            oracle.global_best is not None
            and oracle.global_best in oracle.mechanism_order[:4]
        ),
        "solver_pool_matches_independent_oracle": (
            solver_boundaries == oracle_boundaries
        ),
        "solver_scores_match_independent_oracle": (
            solver_scores_match_oracle
        ),
        "caps_exact_0_1_2_4": all(
            cap_results[cap].activity["exact_candidates_completed"] == cap
            for cap in (0, 1, 2, 4)
        ),
        "cap_zero_exact_noop": not cap_results[0].changed,
        "mechanism_strictly_beats_source": (
            mechanism.changed and mechanism.cost < mechanism.source_cost - 1e-9
        ),
        "mechanism_strictly_beats_counterfactual": (
            mechanism.cost < mechanism.counterfactual_cost - 1e-9
        ),
        "mechanism_strictly_beats_distance_arm": (
            mechanism.cost < distance.cost - 1e-9
        ),
        "distance_arm_does_not_fake_improvement": not distance.changed,
        "same_candidate_pool_both_arms": (
            mechanism.activity["candidate_set_sha256"]
            == distance.activity["candidate_set_sha256"]
        ),
        "same_exact_capacity_both_arms": (
            mechanism.activity["exact_candidates_completed"]
            == distance.activity["exact_candidates_completed"]
            == 4
        ),
        "same_joint_work_binding_fixture": (
            mechanism.activity["vehicle_patterns"]
            == distance.activity["vehicle_patterns"]
            and mechanism.activity["joint_complete_replays"]
            == distance.activity["joint_complete_replays"]
            and mechanism.activity["joint_feasibility_checks"]
            == distance.activity["joint_feasibility_checks"]
        ),
        "mechanism_matches_independent_oracle": (
            oracle.global_best is not None
            and abs(mechanism.cost - oracle.global_best.complete_cost) <= 1e-7
        ),
        "mechanism_field_really_changes": (
            _cross_site_signature(binding.source)
            != _cross_site_signature(mechanism.solution)
        ),
        "nonbinding_mechanism_exact_noop": (
            not nonbinding_mechanism.changed
            and nonbinding_mechanism.solution == nonbinding.source
        ),
        "nonbinding_distance_exact_noop": (
            not nonbinding_distance.changed
            and nonbinding_distance.solution == nonbinding.source
        ),
        "joint_left_control_feasible": conflict_left["feasible"],
        "joint_right_control_feasible": conflict_right["feasible"],
        "joint_public_station_conflict_rejected": (
            not conflict_joint["feasible"]
            and conflict_joint["violation_types"] == ["STATION_CAPACITY"]
            and conflict_joint["joint_feasibility_checks"] >= 1
        ),
        "joint_public_station_actions_entered_completion": (
            conflict_joint["completion_activity"][
                "charge_actions_selected"
            ]
            == 2
            and conflict_joint["completion_activity"][
                "generated_charge_starts"
            ]
            >= 2
            and conflict_joint["completion_activity"][
                "retained_charge_starts"
            ]
            == 2
            and conflict_joint["completion_activity"][
                "local_start_evaluations"
            ]
            >= 2
        ),
        "public_station_retime_positive_control": (
            conflict_resolvable["feasible"]
            and conflict_resolvable["input_solution_sha256"]
            != conflict_resolvable["output_solution_sha256"]
            and conflict_resolvable["joint_feasibility_checks"] >= 2
        ),
        "all_tamper_checks_rejected": all(tamper_checks.values()),
        "zero_complete_route_search_evaluations": route_search_total == 0,
        "all_outputs_feasible": all(result.feasible for result in all_results),
        "protected_hashes_unchanged": (
            _locked_hashes()
            == _read_json(BLIND_LOCK)["locked_file_sha256"]
        ),
    }
    passed = all(bool(value) for value in checks.values())
    rows = [
        _result_row("binding", f"mechanism_cap_{cap}", result)
        for cap, result in sorted(cap_results.items())
    ]
    rows.extend(
        [
            _result_row("binding", "distance_cap_4", distance),
            _result_row(
                "nonbinding",
                "mechanism_cap_4",
                nonbinding_mechanism,
            ),
            _result_row(
                "nonbinding",
                "distance_cap_4",
                nonbinding_distance,
            ),
        ]
    )
    return {
        "schema_version": 1,
        "passed": passed,
        "verdict": VERDICT_PASS if passed else VERDICT_STOP,
        "checks": checks,
        "rows": rows,
        "binding": {
            "prepared_integrity_sha256": prepared.integrity_sha256,
            "candidate_set_sha256": prepared.candidate_set_sha256,
            "candidate_count": len(prepared.candidates),
            "source_cost": prepared.counterfactual.source_cost,
            "counterfactual_cost": prepared.counterfactual.cost,
            "mechanism_cost": mechanism.cost,
            "distance_cost": distance.cost,
            "oracle_global_best": (
                None if oracle.global_best is None else asdict(oracle.global_best)
            ),
            "oracle_distance_rank": (
                None
                if oracle.global_best is None
                else oracle.distance_order.index(oracle.global_best) + 1
            ),
            "preparation_activity": prepared.preparation_activity,
            "counterfactual_activity": prepared.counterfactual.activity,
            "mechanism_activity": mechanism.activity,
            "distance_activity": distance.activity,
        },
        "nonbinding": {
            "mechanism_activity": nonbinding_mechanism.activity,
            "distance_activity": nonbinding_distance.activity,
        },
        "joint_conflict": {
            "left_only": conflict_left,
            "right_only": conflict_right,
            "joint": conflict_joint,
            "widened_resolvable_joint": conflict_resolvable,
        },
        "tamper_checks": tamper_checks,
        "route_search_attempts": [],
        "complete_route_search_evaluations": route_search_total,
        "formal_search_allowed": False,
        "full_benchmark_allowed": False,
        "stage2_allowed": False,
        "witnesses": {
            "binding_source": asdict(binding.source),
            "binding_counterfactual": asdict(prepared.counterfactual.solution),
            "binding_mechanism": asdict(mechanism.solution),
            "binding_distance": asdict(distance.solution),
            "nonbinding_source": asdict(nonbinding.source),
            "nonbinding_mechanism": asdict(nonbinding_mechanism.solution),
            "joint_left_only": asdict(conflict.left_only),
            "joint_right_only": asdict(conflict.right_only),
            "joint_conflict": asdict(conflict.joint),
        },
    }


def _tamper_checks(prepared: Any, mechanism: Any) -> dict[str, bool]:
    checks: dict[str, bool] = {}

    def rejected(label: str, callback: Any) -> None:
        try:
            callback()
        except Exception:
            checks[label] = True
        else:
            checks[label] = False

    rejected(
        "candidate_set_hash",
        lambda: verify_prepared_pool(
            replace(prepared, candidate_set_sha256="0" * 64)
        ),
    )
    forged_activity = dict(prepared.preparation_activity)
    forged_activity["common_candidates"] = True
    rejected(
        "boolean_count",
        lambda: verify_prepared_pool(
            replace(prepared, preparation_activity=forged_activity)
        ),
    )
    rejected(
        "counterfactual_record",
        lambda: verify_prepared_pool(
            replace(
                prepared,
                counterfactual=replace(
                    prepared.counterfactual,
                    record_sha256="f" * 64,
                ),
            )
        ),
    )
    changed_context = copy.deepcopy(prepared.context)
    changed_context.carbon_weight = 2.0
    rejected(
        "context_hash",
        lambda: verify_prepared_pool(
            replace(prepared, context=changed_context)
        ),
    )
    rejected(
        "forged_arm_ledger",
        lambda: _assert_arm_caps(
            {
                **mechanism.activity,
                "accepted_moves": True,
            },
            prepared.config,
        ),
    )
    forged_completion = copy.deepcopy(mechanism.activity)
    forged_completion["records"][0]["completion"][
        "joint_complete_replays"
    ] += 1
    rejected(
        "forged_completion_record",
        lambda: verify_pair_resplit_result(
            replace(mechanism, activity=forged_completion),
            prepared,
        ),
    )
    rejected(
        "result_signature",
        lambda: verify_pair_resplit_result(
            replace(mechanism, result_sha256="0" * 64),
            prepared,
        ),
    )
    forged_replay_cost = copy.deepcopy(mechanism.activity)
    replay_cost_changed = False
    for candidate_record in forged_replay_cost["records"]:
        for pattern_record in candidate_record["completion"]["records"]:
            if pattern_record["feasible"]:
                pattern_record["complete_cost"] += 1.0
                replay_cost_changed = True
                break
        if replay_cost_changed:
            break
    if replay_cost_changed:
        rejected(
            "replay_cost_record",
            lambda: verify_pair_resplit_result(
                replace(mechanism, activity=forged_replay_cost),
                prepared,
            ),
        )
    else:
        checks["replay_cost_record"] = False
    first = mechanism.solution.routes[0]
    lost = replace(
        mechanism.solution,
        routes=[
            replace(
                first,
                node_sequence=first.node_sequence[:-2]
                + [first.node_sequence[-1]],
            ),
            *mechanism.solution.routes[1:],
        ],
    )
    lost_probe = joint_feasibility_probe(lost, prepared.context)
    checks["lost_customer"] = (
        not lost_probe["feasible"]
        and "CUSTOMER_COVERAGE" in lost_probe["violation_types"]
    )
    duplicate = replace(
        mechanism.solution,
        routes=[
            replace(
                first,
                node_sequence=(
                    first.node_sequence[:-1]
                    + [first.node_sequence[1], first.node_sequence[-1]]
                ),
            ),
            *mechanism.solution.routes[1:],
        ],
    )
    duplicate_probe = joint_feasibility_probe(
        duplicate,
        prepared.context,
    )
    checks["duplicate_customer"] = (
        not duplicate_probe["feasible"]
        and "CUSTOMER_COVERAGE" in duplicate_probe["violation_types"]
    )
    base = replace(
        prepared.counterfactual.solution,
        routes=[
            *prepared.counterfactual.solution.routes,
            Route("CV_SENTINEL#T1", "cv", "D0", ["D0", "D0"]),
        ],
    )
    drifted = replace(
        base,
        routes=[
            *base.routes[:-1],
            replace(
                base.routes[-1],
                home_depot_id="D1",
                node_sequence=["D1", "D1"],
            ),
        ],
    )
    invariants = _candidate_invariants(
        base,
        drifted,
        prepared.candidates[0],
        prepared.context,
    )
    checks["nonpair_drift"] = not invariants["nonpair_routes_unchanged"]
    return checks


def _cross_site_signature(solution: Any) -> tuple[str, ...]:
    return tuple(
        sorted(
            json.dumps(
                asdict(service),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for service in solution.cross_site_services
        )
    )


def _seal_success_or_stop(payload: dict[str, Any]) -> None:
    metadata = {
        "schema_version": 1,
        "gate": "mechanism_priced_pair_resplit_behavior",
        "executed_unix": time.time(),
        "git_head": _git("rev-parse", "HEAD").strip(),
        "blind_lock_sha256": _sha256_file(BLIND_LOCK),
        "preflight_sha256": _sha256_file(PREFLIGHT),
        "locked_file_sha256": _locked_hashes(),
        "route_search_attempts": [],
    }
    decision = {
        key: value
        for key, value in payload.items()
        if key not in {"rows", "witnesses"}
    }
    _write_json(OUTPUT / "metadata.json", metadata)
    _write_rows(OUTPUT / "raw_runs.csv", payload["rows"])
    _write_json(OUTPUT / "decision.json", decision)
    _write_json(OUTPUT / "solution_witnesses.json", payload["witnesses"])
    report = _report_text(payload)
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    _write_artifact_hashes()


def _seal_execution_exception(
    failure: dict[str, Any],
    started: dict[str, Any],
) -> None:
    metadata = {
        "schema_version": 1,
        "gate": "mechanism_priced_pair_resplit_behavior",
        "executed_unix": time.time(),
        "git_head": started["git_head"],
        "blind_lock_sha256": started["blind_lock_sha256"],
        "preflight_sha256": started["preflight_sha256"],
        "locked_file_sha256": started["locked_file_sha256"],
        "execution_status": "STOP_EXECUTION_EXCEPTION",
        "route_search_attempts": [],
    }
    raw_failure = {
        "fixture": "gate",
        "label": "execution_exception",
        "arm": "",
        "passed": False,
        "verdict": VERDICT_STOP,
        "exception_type": failure["exception_type"],
        "exception": failure["exception"],
        "complete_route_search_evaluations": 0,
        "formal_search_allowed": False,
        "full_benchmark_allowed": False,
        "stage2_allowed": False,
    }
    _write_json(OUTPUT / "metadata.json", metadata)
    _write_rows(OUTPUT / "raw_runs.csv", [raw_failure])
    _write_json(OUTPUT / "decision.json", failure)
    _write_json(OUTPUT / "solution_witnesses.json", {})
    (OUTPUT / "report.md").write_text(
        "# 双路线重切零搜索行为门\n\n"
        f"结论：`{VERDICT_STOP}`。\n\n"
        "执行异常："
        f"`{failure['exception_type']}: {failure['exception']}`。\n\n"
        "异常现场已封存为完整失败证据；未授权搜索、正式实验、"
        "全量算例或阶段二。\n",
        encoding="utf-8",
    )
    _write_artifact_hashes()


def _result_row(
    fixture: str,
    label: str,
    result: Any,
) -> dict[str, Any]:
    return {
        "fixture": fixture,
        "label": label,
        "arm": result.arm,
        "source_cost": result.source_cost,
        "counterfactual_cost": result.counterfactual_cost,
        "output_cost": result.cost,
        "changed": result.changed,
        "feasible": result.feasible,
        "exact_candidate_capacity": result.activity[
            "exact_candidate_capacity"
        ],
        "exact_candidates_completed": result.activity[
            "exact_candidates_completed"
        ],
        "vehicle_patterns": result.activity["vehicle_patterns"],
        "joint_feasibility_checks": result.activity[
            "joint_feasibility_checks"
        ],
        "joint_complete_replays": result.activity[
            "joint_complete_replays"
        ],
        "independent_replays": result.activity["independent_replays"],
        "accepted_moves": result.activity["accepted_moves"],
        "candidate_set_sha256": result.activity["candidate_set_sha256"],
        "accepted_candidate_sha256": result.accepted_candidate_sha256 or "",
        "result_sha256": result.result_sha256,
        "complete_route_search_evaluations": result.activity[
            "complete_route_search_evaluations"
        ],
    }


def _report_text(payload: dict[str, Any]) -> str:
    binding = payload["binding"]
    checks = payload["checks"]
    lines = [
        "# 双路线重切零搜索行为门",
        "",
        f"结论：`{payload['verdict']}`。",
        "",
        "本门只验证人工小夹具上的动作、归因、联合资源检查和账本；",
        "没有调用ALNS、HGS、正式winner或任何完整路线搜索。",
        "",
        "## 关键数字",
        "",
        f"- 输入成本：`{binding['source_cost']:.12f}`。",
        f"- 原骨架机制完成反事实：`{binding['counterfactual_cost']:.12f}`。",
        f"- 机制计价臂：`{binding['mechanism_cost']:.12f}`。",
        f"- 里程删减臂：`{binding['distance_cost']:.12f}`。",
        f"- 共同候选：`{binding['candidate_count']}`个。",
        f"- 独立穷举最优在里程排序中第`{binding['oracle_distance_rank']}`名。",
        "",
        "## 机械检查",
        "",
    ]
    lines.extend(
        f"- {'PASS' if value else 'FAIL'}：`{key}`。"
        for key, value in checks.items()
    )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "即使本门通过，也只允许为两道全新小题另立极小搜索合同。",
            "本证据不授权正式搜索、全量benchmark、China81、E2--E7重跑或阶段二。",
            "行为门使用两条改动路线各占一辆不同实体车的受限语义；",
            "可复用实体车的公共站多趟衔接尚未被本门证明。",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_blind_lock() -> None:
    if not BLIND_LOCK.exists() or not PREFLIGHT.exists():
        raise RuntimeError("preflight/blind lock is missing")
    lock = _read_json(BLIND_LOCK)
    if lock.get("status") != "BLIND_LOCKED_BEFORE_BEHAVIOR":
        raise RuntimeError("blind lock status is invalid")
    if _sha256_file(PREFLIGHT) != lock["preflight_sha256"]:
        raise RuntimeError("preflight hash drifted")
    if _locked_hashes() != lock["locked_file_sha256"]:
        raise RuntimeError("locked file hash drifted")
    changed = set(
        filter(
            None,
            _git(
                "diff",
                "--name-only",
                f"{lock['code_commit']}..HEAD",
            ).splitlines(),
        )
    )
    allowed = set(lock["allowed_paths_after_code_commit"])
    if not changed <= allowed:
        raise RuntimeError(
            f"locked code changed after code commit: {sorted(changed - allowed)}"
        )


def _write_artifact_hashes() -> None:
    excluded_appledouble = sorted(
        path.name
        for path in OUTPUT.iterdir()
        if path.is_file() and path.name.startswith("._")
    )
    rows = {
        path.name: _sha256_file(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(
        OUTPUT / "artifact_hashes.json",
        {
            "schema_version": 1,
            "algorithm": "sha256",
            "status": (
                "HASH_CONTAMINATED_APPLEDOUBLE"
                if excluded_appledouble
                else "CLEAN"
            ),
            "artifact_count": len(rows),
            "files": rows,
            "excluded_appledouble_files": excluded_appledouble,
        },
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError("raw run rows are empty")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _locked_hashes() -> dict[str, str]:
    missing = [path for path in LOCKED_FILES if not (REPO / path).is_file()]
    if missing:
        raise RuntimeError(f"locked files are missing: {missing}")
    return {path: _sha256_file(REPO / path) for path in LOCKED_FILES}


def _git_status() -> str:
    return _git("status", "--porcelain").strip()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
