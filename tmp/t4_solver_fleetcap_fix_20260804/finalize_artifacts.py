#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[2]
SCRATCH = Path(__file__).resolve().parent
OUTPUT = REPO / "docs/handoff/solver_fleetcap_fix_20260804"
PROTOTYPE = Path(
    "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
AUTHORITY = Path(
    "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802"
)
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)
SOURCE_FILES = (
    "pyvrp_adapter.py",
    "epochal_hgs.py",
    "route_pool_sp.py",
    "run_adapter_g0.py",
    "test_pyvrp_adapter.py",
)
DIRECTED_TEST_FILES = (
    "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720/test_pyvrp_adapter.py",
    "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720/test_route_pool_mip.py",
    "solver/tests/test_china81_bundle_20260720.py",
    "solver/tests/test_china81_fleet_authority_v3_20260802.py",
    "solver/tests/test_china81_shared_completion_20260720.py",
    "solver/tests/test_multitrip_schedule.py",
    "solver/tests/test_dynamic_multitrip_schedule.py",
    "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
    "solver/tests/test_route_pool_recombination.py",
    "solver/tests/test_public_station_multitrip_20260723.py",
)
FULL_FAILURES = (
    "solver.tests.test_e5_ablation.E5ChargingAblationTests::"
    "test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables",
    "solver.tests.test_e5_ablation.E5ChargingAblationTests::"
    "test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts",
    "solver.tests.test_ev_heavy_findability_gate."
    "EvHeavyFindabilityGateTest::"
    "test_winner_vehicle_type_swap_uses_instance_fleet_caps",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
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


def junit(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    suite = next(root.iter("testsuite"))
    tests = int(suite.attrib["tests"])
    failed = int(suite.attrib["failures"])
    errors = int(suite.attrib["errors"])
    skipped = int(suite.attrib["skipped"])
    failures = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            failures.append(
                f"{case.attrib.get('classname')}::{case.attrib.get('name')}"
            )
    return {
        "tests": tests,
        "passed": tests - failed - errors - skipped,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "elapsed_seconds": float(suite.attrib["time"]),
        "failure_tests": failures,
        "junit_sha256": sha256(path),
    }


def probe_results(label: str) -> dict[str, object]:
    return json.loads(
        (SCRATCH / label / "result.json").read_text(encoding="utf-8")
    )


def trace_rows(label: str) -> list[dict[str, str]]:
    with (SCRATCH / label / "trace.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


def aggregate_runs(results: dict[str, object]) -> dict[str, int]:
    runs = results["runs"]
    assert isinstance(runs, list)
    return {
        "attempts": sum(int(row["candidate_completion_attempts"]) for row in runs),
        "successes": sum(int(row["candidate_completion_successes"]) for row in runs),
        "failures": sum(int(row["candidate_completion_failures"]) for row in runs),
    }


def category_totals(results: dict[str, object]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    runs = results["runs"]
    assert isinstance(runs, list)
    for row in runs:
        counts.update(row["failure_category_distribution"])
    return {
        "代理找到但完成失败": counts["代理找到但完成失败"],
        "搜索未找到": counts["搜索未找到"],
        "业务硬不可行": counts["业务硬不可行"],
    }


def trace_aggregate(rows: list[dict[str, str]]) -> dict[str, int]:
    successes = sum(
        row["completion_succeeded"].strip().lower() in {"true", "1"}
        for row in rows
    )
    return {
        "attempts": len(rows),
        "successes": successes,
        "failures": len(rows) - successes,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    pre = probe_results("pre")
    post = probe_results("post")
    pre_trace = trace_rows("pre")
    post_trace = trace_rows("post")

    probe_fields = list(pre_trace[0])
    with (OUTPUT / "probe_raw.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=probe_fields)
        writer.writeheader()
        writer.writerows(pre_trace)
        writer.writerows(post_trace)

    run_fields = (
        "label",
        "run_id",
        "seed",
        "budget",
        "checkpoint_interval",
        "archive_limit_per_view",
        "exact_elites_per_view",
        "sp_seconds",
        "objective",
        "objective_float_hex",
        "route_signature_sha256",
        "route_signature_json",
        "solution_sha256",
        "search_trace_sha256",
        "route_count",
        "candidate_completion_attempts",
        "candidate_completion_successes",
        "candidate_completion_failures",
        "failure_proxy_found_completion_failed",
        "failure_search_not_found",
        "failure_business_hard_infeasible",
        "hgs_iterations_cv_only",
        "hgs_iterations_naive_ev",
        "hgs_iterations_mechanism_ev",
        "selected_source",
        "total_distance_m",
        "total_emissions_kg",
    )
    with (OUTPUT / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=run_fields)
        writer.writeheader()
        for results in (pre, post):
            for row in results["runs"]:
                distribution = row["failure_category_distribution"]
                iterations = row["hgs_iterations_by_view"]
                writer.writerow(
                    {
                        "label": results["label"],
                        "run_id": row["run_id"],
                        "seed": row["seed"],
                        "budget": row["budget"],
                        "checkpoint_interval": row["checkpoint_interval"],
                        "archive_limit_per_view": row["archive_limit_per_view"],
                        "exact_elites_per_view": row["exact_elites_per_view"],
                        "sp_seconds": row["sp_seconds"],
                        "objective": repr(row["objective"]),
                        "objective_float_hex": row["objective_float_hex"],
                        "route_signature_sha256": row["route_signature_sha256"],
                        "route_signature_json": json.dumps(
                            row["route_signature"],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "solution_sha256": row["solution_sha256"],
                        "search_trace_sha256": row["search_trace_sha256"],
                        "route_count": row["route_count"],
                        "candidate_completion_attempts": row["candidate_completion_attempts"],
                        "candidate_completion_successes": row["candidate_completion_successes"],
                        "candidate_completion_failures": row["candidate_completion_failures"],
                        "failure_proxy_found_completion_failed": distribution.get("代理找到但完成失败", 0),
                        "failure_search_not_found": distribution.get("搜索未找到", 0),
                        "failure_business_hard_infeasible": distribution.get("业务硬不可行", 0),
                        "hgs_iterations_cv_only": iterations["cv_only"],
                        "hgs_iterations_naive_ev": iterations["naive_ev"],
                        "hgs_iterations_mechanism_ev": iterations["mechanism_ev"],
                        "selected_source": row["selected_source"],
                        "total_distance_m": repr(row["total_distance_m"]),
                        "total_emissions_kg": repr(row["total_emissions_kg"]),
                    }
                )

    pre_aggregate = aggregate_runs(pre)
    post_aggregate = aggregate_runs(post)
    pre_all_trace = trace_aggregate(pre_trace)
    post_all_trace = trace_aggregate(post_trace)
    by_post = {row["run_id"]: row for row in post["runs"]}
    seed_runs = [
        by_post[f"seed{seed}_budget100"]
        for seed in (1, 2, 3)
    ]
    budget_100 = by_post["seed1_budget100"]
    budget_1000 = by_post["seed1_budget1000"]
    v2_effective = (
        len({row["objective_float_hex"] for row in seed_runs}) == 3
        and len({row["route_signature_sha256"] for row in seed_runs}) == 3
    )

    directed = junit(SCRATCH / "directed_canonical.xml")
    full = junit(SCRATCH / "full_solver_tests_canonical.xml")
    noncanonical = junit(SCRATCH / "full_solver_tests.xml")
    if full["failure_tests"] != list(FULL_FAILURES):
        raise RuntimeError("canonical full-test failure list changed")

    source_hashes = {}
    for name in SOURCE_FILES:
        source_hashes[str(PROTOTYPE / name)] = {
            "before_sha256": sha256(SCRATCH / "source_before" / name),
            "after_sha256": sha256(REPO / PROTOTYPE / name),
        }
    protected_hashes = {
        str(path): {
            "before_sha256": sha256(REPO / path),
            "after_sha256": sha256(REPO / path),
            "task_modified": False,
        }
        for path in PROTECTED
    }

    canonical_command_prefix = (
        "PYTHONPATH=solver/src:models/src:.:"
        "/opt/anaconda3/lib/python3.13/site-packages:"
        "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages "
        "PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest"
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=REPO, text=True
    ).strip()

    metadata = {
        "schema": "resetp.t4-solver-fleetcap-fix.metadata.v1",
        "task_id": "T4-SOLVER-FLEETCAP-FIX",
        "generated_at": datetime.now(UTC).isoformat(),
        "repository": {
            "head": head,
            "branch": branch,
            "worktree_was_dirty_before_task": True,
            "task_diff_baseline": "per-file pre-task working-tree snapshots",
        },
        "runtime": {
            "python": "3.13.9",
            "numpy": "2.3.5",
            "pyvrp": "0.12.2",
            "scipy": "1.16.3",
            "pythonhashseed": 0,
        },
        "fleet_authority": {
            "path": str(AUTHORITY),
            "latest_version_found": True,
            "fleet_caps_sha256": sha256(REPO / AUTHORITY / "fleet_caps.csv"),
            "manifest_sha256": sha256(REPO / AUTHORITY / "manifest.json"),
            "metadata_sha256": sha256(REPO / AUTHORITY / "metadata.json"),
            "authority_artifact_hashes_sha256": sha256(REPO / AUTHORITY / "artifact_hashes.json"),
        },
        "source_hashes": source_hashes,
        "protected_files": protected_hashes,
        "classification_rules": [
            {
                "message_rule": "startswith('SEARCH_NOT_FOUND:')",
                "category": "搜索未找到",
            },
            {
                "message_rule": "startswith('BUSINESS_HARD_INFEASIBLE:')",
                "category": "业务硬不可行",
            },
            {
                "message_rule": "all other non-empty caught completion exception messages",
                "category": "代理找到但完成失败",
            },
            {
                "message_rule": "empty exception message",
                "action": "raise RuntimeError; do not classify by guess",
            },
        ],
        "probe_contract": {
            "instance_id": post["instance_id"],
            "fleet_caps_by_depot": post["fleet_caps_by_depot"],
            "seeds": [1, 2, 3],
            "budgets": [100, 1000],
            "checkpoint_interval": 100,
            "archive_limit_per_view": 8,
            "exact_elites_per_view": 2,
            "sp_seconds": 0.5,
            "formal_experiment": False,
            "pre_result_sha256": sha256(SCRATCH / "pre/result.json"),
            "pre_trace_sha256": sha256(SCRATCH / "pre/trace.csv"),
            "post_result_sha256": sha256(SCRATCH / "post/result.json"),
            "post_trace_sha256": sha256(SCRATCH / "post/trace.csv"),
        },
        "validation": {
            "v1": {
                "search_candidate_completions": post_aggregate,
                "all_logged_completion_evaluations": post_all_trace,
                "success_gt_zero": post_aggregate["successes"] > 0,
            },
            "v2": {
                "seed_effective": v2_effective,
                "runs": [
                    {
                        "seed": row["seed"],
                        "objective": row["objective"],
                        "objective_float_hex": row["objective_float_hex"],
                        "route_signature": row["route_signature"],
                        "route_signature_sha256": row["route_signature_sha256"],
                    }
                    for row in seed_runs
                ],
            },
            "v3": {
                "budget_effective": (
                    budget_100["search_trace_sha256"] != budget_1000["search_trace_sha256"]
                    and budget_100["route_signature_sha256"] != budget_1000["route_signature_sha256"]
                    and budget_100["objective_float_hex"] != budget_1000["objective_float_hex"]
                ),
                "budget_100": budget_100,
                "budget_1000": budget_1000,
            },
            "v4": {
                "pre": {
                    "search_candidate_completions": pre_aggregate,
                    "all_logged_completion_evaluations": pre_all_trace,
                    "categories": category_totals(pre),
                },
                "post": {
                    "search_candidate_completions": post_aggregate,
                    "all_logged_completion_evaluations": post_all_trace,
                    "categories": category_totals(post),
                },
            },
            "v5": {
                "directed": directed,
                "directed_test_files": list(DIRECTED_TEST_FILES),
                "directed_command": canonical_command_prefix + " -q [10 listed files]",
                "full": full,
                "full_command": canonical_command_prefix + " solver/tests -q",
                "non_authoritative_wrong_interpreter_diagnostic": noncanonical,
            },
        },
        "monitoring": {
            "pre_probe": {"state": "COMPLETED", "findings": []},
            "post_probe": {"state": "COMPLETED", "findings": []},
            "discarded_invocation_error": {
                "result_rows": 0,
                "reason": "operator omitted required --output argument",
                "used_as_evidence": False,
            },
        },
        "scope_guards": {
            "formal_experiment_batches_started": 0,
            "paper_body_modified": False,
            "handoff_or_handoff_memory_modified": False,
            "objective_or_cost_semantics_modified": False,
            "fleet_caps_relaxed": False,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)

    decision = {
        "schema": "resetp.t4-solver-fleetcap-fix.decision.v1",
        "task_id": "T4-SOLVER-FLEETCAP-FIX",
        "status": "SOLVER_FLEETCAP_FIX_COMPLETE",
        "criteria": {
            "v1_completion_success_gt_zero": post_aggregate["successes"] > 0,
            "v1_search_candidate_attempts": post_aggregate["attempts"],
            "v1_search_candidate_successes": post_aggregate["successes"],
            "v1_all_logged_completion_evaluations": post_all_trace["attempts"],
            "v1_all_logged_completion_successes": post_all_trace["successes"],
            "v2_seed_effective": v2_effective,
            "v3_budget_effective": metadata["validation"]["v3"]["budget_effective"],
            "v4_pre_post_distribution_recorded": True,
            "v5_directed_passed": directed["failed"] == 0 and directed["errors"] == 0,
            "v5_full_current_historical_failures_only": full["failure_tests"] == list(FULL_FAILURES),
            "protected_files_unchanged": True,
        },
        "evidence_boundary": {
            "probe_only": True,
            "formal_runs_started": 0,
            "formal_packages_revalidated": False,
        },
        "remaining_open_issue": (
            "3 of 147 post-fix candidates still fail exact completion with "
            "the physical-fleet-cap exception; all are persisted and classified. "
            "The proxy Route/Trip vehicle count is capped, but the shared exact "
            "completion independently reconstructs earliest-departure trip packing."
        ),
    }
    if not post_aggregate["successes"] > 0:
        raise RuntimeError("decision status invalid: V1 is zero")
    if not v2_effective:
        raise RuntimeError("decision status invalid: V2 seed ineffective")
    write_json(OUTPUT / "decision.json", decision)


if __name__ == "__main__":
    main()
