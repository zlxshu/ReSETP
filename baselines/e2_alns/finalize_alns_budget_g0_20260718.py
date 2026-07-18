#!/usr/bin/env python3
"""Build the combined static-and-behavior G0 evidence package."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from baselines.e2_alns.audit_alns_budget_g0_20260718 import REPO_ROOT, scan


OUTPUT = REPO_ROOT / "baselines/e2_alns/e2_alns_budget_g0_20260718"
ALNS_ROOT = REPO_ROOT / "solver/src/setp_solver/algorithms/resetp_alns"
PRE_CHANGE_HASHES = {
    "kernel/alns_core.py": "23704471495016a59ed63c0f0bb24840528a9736c495ee24ccb0a4be27dc96bb",
    "kernel/winner.py": "0eb31fd5c90aaf923db4edd511f4cb102487887f6b213740db9c93e8ec02101b",
    "operators/local_search.py": "bfeb4151a3d9bfcfb839b1ac9b92ab5152e83fe4b1277cb1c7115bf014229009",
    "operators/carbon_operators.py": "5daf625fd0dc8a07a0166fc4258f54b1d359685858ce25671385f0af71de2329",
    "operators/feasible_repair.py": "21a50ca7340bec698e33151956e0d5c50ed73f8e502833bbe30d40942a411da1",
    "support/global_order_repack.py": "96eb95bfa52a97f6c409517b8b85556d2c79ee918ece49010d06334f27405425",
    "support/fleet_charge_corepair.py": "2f91fd93c2d5f8b43507240764d2cb5d31a2ca0c6986dade68b977094895c160",
    "operators/repair_scoring.py": "1f688804aba9a6613426fc7ef3e1198343deff28329cf2905e8ef6616d10a847",
}
TESTS = (
    "solver/tests/test_alns_budget_accounting_g0_20260718.py",
    "solver/tests/test_alns_budget_closure_static_20260717.py",
    "solver/tests/test_alns_crush.py",
    "solver/tests/test_fleet_charge_corepair.py",
    "solver/tests/test_global_order_repack.py",
    "solver/tests/test_search.py",
    "solver/tests/test_m1_joint_repack_fleet_headroom.py",
    "solver/tests/test_e2_alns_throughput.py",
    "solver/tests/test_strong_bridge_backend_alignment.py",
    "solver/tests/test_lns_acceptance_scheduler_trace.py",
    "solver/tests/test_multitrip_schedule.py",
    "solver/tests/test_e3_v3_runner.py",
    "solver/tests/test_e2b_component_ablation_probe.py",
    "solver/tests/test_e2b_component_ablation_formal.py",
    "solver/tests/test_resetp_alns_independence.py",
    "solver/tests/test_resetp_alns_full_independence.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output: Path = OUTPUT) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    static_rows = scan()
    blockers = [row for row in static_rows if row["closure_status"] == "BLOCK"]
    unclassified = [row for row in static_rows if row["channel"] == "unclassified_direct"]
    command = [
        "/opt/anaconda3/bin/python3.13",
        "-m",
        "pytest",
        "-q",
        *TESTS,
    ]
    test_env = dict(os.environ)
    test_env["PYTHONPATH"] = ".:solver/src"
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=test_env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    match = re.search(r"(\d+) passed", combined)
    passed = int(match.group(1)) if match else 0
    post_hashes = {
        path.relative_to(ALNS_ROOT).as_posix(): sha256(path)
        for path in sorted(ALNS_ROOT.rglob("*.py"))
        if not path.name.startswith("._")
    }
    verdict = (
        "PASS_ALNS_BUDGET_G0_COMPLETE"
        if not blockers and not unclassified and completed.returncode == 0 and passed > 0
        else "HALT_ALNS_BUDGET_CLOSURE_REQUIRED"
    )
    metadata = {
        "schema": "resetp.alns-budget-g0.metadata.v1",
        "contract": "docs/handoff/e2_alns_budget_g0_patch_plan_20260717.md",
        "historical_halt_package": "baselines/e2_alns/e2_alns_budget_closure_static_20260717",
        "search_experiments_started": 0,
        "test_command": command,
        "pre_change_source_hashes": PRE_CHANGE_HASHES,
        "post_change_source_hashes": post_hashes,
    }
    decision = {
        "schema": "resetp.alns-budget-g0.decision.v1",
        "verdict": verdict,
        "static_blockers": len(blockers),
        "static_unclassified": len(unclassified),
        "behavior_test_returncode": int(completed.returncode),
        "behavior_tests_passed": passed,
        "candidate_reference_repair_channels_visible": True,
        "target_plus_one_observed": False,
        "homberger_g1_development_authorized": verdict == "PASS_ALNS_BUDGET_G0_COMPLETE",
        "formal_solomon_or_china_benchmark_authorized": False,
        "next_gate": "Homberger G1 development" if verdict == "PASS_ALNS_BUDGET_G0_COMPLETE" else "continue G0 repair",
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["kind", "source", "function", "callee", "line", "channel", "status", "detail"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in static_rows:
            writer.writerow(
                {
                    "kind": "static_callsite",
                    "source": row["source"],
                    "function": row["function"],
                    "callee": row["callee"],
                    "line": row["line"],
                    "channel": row["channel"],
                    "status": row["closure_status"],
                    "detail": "",
                }
            )
        writer.writerow(
            {
                "kind": "behavior_suite",
                "source": "pytest",
                "function": "",
                "callee": "",
                "line": "",
                "channel": "candidate_reference_repair_and_regression",
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "detail": combined.replace("\n", " | "),
            }
        )
    (output / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        "# ALNS complete-solution budget G0\n\n"
        f"Verdict: `{verdict}`.\n\n"
        f"Static blockers={len(blockers)}, unclassified={len(unclassified)}. "
        f"Behavior/regression tests={passed} passed, returncode={completed.returncode}. "
        "Candidate limits are prechecked before the legacy scorer; reference phases and "
        "repair deltas remain separately visible. No formal search experiment was run.\n\n"
        "The sealed 2026-07-17 HALT package is retained unchanged as the adverse baseline. "
        "This patch changes budget semantics and therefore does not rehabilitate old E2 "
        "comparisons or permit mixing old and new algorithm results.\n",
        encoding="utf-8",
    )
    artifacts = {
        name: sha256(output / name)
        for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    }
    (output / "artifact_hashes.json").write_text(
        json.dumps(artifacts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return decision


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
