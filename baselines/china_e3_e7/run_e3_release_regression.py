#!/usr/bin/env python3
"""Run and classify the pre-E3 release regression suite."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from xml.etree import ElementTree


REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "e3_release_regression_20260723"
EXPECTED = {
    "solver/tests/test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit": "EXPECTED_HISTORICAL_FROZEN_HASH_ALARM",
    "solver/tests/test_e2_alns_throughput.py::E2AlnsThroughputTest::test_runner_smoke_outputs_finite_zero_violation_rows": "EXPECTED_LEGACY_ENVIRONMENT_GUARD",
    "solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables": "EXPECTED_HISTORICAL_E5_EVIDENCE_DEFECT",
    "solver/tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts": "EXPECTED_HISTORICAL_E5_EVIDENCE_DEFECT",
    "solver/tests/test_external_baseline_freeze_builder_20260717.py::test_candidate_probe_is_bound_to_current_adapter": "EXPECTED_HISTORICAL_FROZEN_HASH_ALARM",
    "solver/tests/test_metaheuristic_baselines.py::MetaheuristicBaselineTest::test_gold_environment": "EXPECTED_LEGACY_ENVIRONMENT_GUARD",
    "solver/tests/test_metaheuristic_baselines.py::MetaheuristicBaselineTest::test_runner_writes_profile_and_convergence_outputs": "EXPECTED_LEGACY_ENVIRONMENT_GUARD",
    "solver/tests/test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact": "EXPECTED_HISTORICAL_FROZEN_HASH_ALARM",
    "solver/tests/test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately": "EXPECTED_HISTORICAL_FROZEN_HASH_ALARM",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        list(rows[0])
        if rows
        else ["test_id", "classification", "registered", "message"]
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _junit_counts(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    junit = OUT / "pytest-junit.xml"
    stdout = OUT / "pytest-output.txt"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        f"--junitxml={junit}",
        "solver/tests",
        "baselines/china_e3_e7/test_adapter.py",
        "baselines/china_e3_e7/test_formal_e3_runner.py",
        "baselines/china_e3_e7/test_spatiotemporal_settlement.py",
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = "solver/src"
    started = perf_counter()
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = perf_counter() - started
    stdout.write_text(completed.stdout, encoding="utf-8")
    counts = _junit_counts(junit)
    failed = set(
        re.findall(r"^FAILED (.+?) - ", completed.stdout, flags=re.MULTILINE)
    )
    # Some pytest versions omit the trailing explanation after the node id.
    failed.update(
        re.findall(r"^FAILED ([^\n]+)$", completed.stdout, flags=re.MULTILINE)
    )
    failed = {item.strip() for item in failed}
    rows = [
        {
            "test_id": test_id,
            "classification": EXPECTED.get(
                test_id,
                "UNREGISTERED_RELEASE_REGRESSION",
            ),
            "registered": test_id in EXPECTED,
            "message": (
                "historical or legacy boundary retained fail-closed; "
                "not evidence of current E3 path success"
                if test_id in EXPECTED
                else "new or changed failure blocks E3"
            ),
        }
        for test_id in sorted(failed)
    ]
    write_csv(OUT / "raw_runs.csv", rows)
    exact_expected = failed == set(EXPECTED)
    no_errors = counts["errors"] == 0
    passed = exact_expected and no_errors
    decision = {
        "schema": "resetp.e3-release-regression.decision.v1",
        "verdict": (
            "PASS_E3_RELEASE_REGRESSION_WITH_REGISTERED_HISTORICAL_BOUNDARIES"
            if passed
            else "HALT_E3_RELEASE_REGRESSION"
        ),
        "pytest_exit_code": completed.returncode,
        "counts": counts,
        "registered_failure_count": len(EXPECTED),
        "observed_failure_count": len(failed),
        "missing_registered_failures": sorted(set(EXPECTED) - failed),
        "unregistered_failures": sorted(failed - set(EXPECTED)),
        "new_implementation_regressions": len(failed - set(EXPECTED)),
        "release_interpretation": (
            "The current E3 repaired path may proceed only because every "
            "observed failure is an already registered historical freeze, "
            "legacy environment guard, or held E5 evidence defect. These "
            "failures remain red and their historical claims are not reused."
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e3-release-regression.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "command": command,
            "cwd": str(REPO),
            "python": sys.version,
            "duration_seconds": elapsed,
            "expected_failure_registry": EXPECTED,
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    REPO
                    / "baselines/china_e3_e7/"
                    "contract.py",
                    REPO
                    / "baselines/china_e3_e7/"
                    "formal_e3_runner.py",
                    REPO
                    / "baselines/china_e3_e7/"
                    "run_e3_independent_recalc.py",
                    REPO
                    / "baselines/china_e3_e7/statistics.py",
                    REPO
                    / "baselines/china_e3_e7/charts.py",
                    REPO
                    / "baselines/china_e3_e7/tables.py",
                    REPO
                    / "baselines/china_e3_e7/test_adapter.py",
                    REPO
                    / "baselines/china_e3_e7/"
                    "test_formal_e3_runner.py",
                    REPO
                    / "baselines/china_e3_e7/"
                    "test_spatiotemporal_settlement.py",
                    REPO
                    / "data/ChinaInstances/"
                    "china_e3_formal_release_contract_v4_20260723.json",
                    REPO
                    / "baselines/china_e3_e7/"
                    "build_formal_release_contract_v4.py",
                    REPO
                    / "baselines/china_e3_e7/"
                    "pre_e3_full_chain_audit_20260723/"
                    "regression_test_classification.csv",
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# E3 release regression\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        f"Collected {counts['tests']} tests: "
        f"{counts['failures']} failed, {counts['errors']} errors and "
        f"{counts['skipped']} skipped in {elapsed:.2f}s. "
        "A PASS here does not paint the registered historical red lights "
        "green: it means only that no new failure appeared in the current E3 "
        "release path and that the old affected claims remain held.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
