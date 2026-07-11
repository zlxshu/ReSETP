#!/usr/bin/env python3
"""Verify the M1 rolling planner's independent backend and live-state contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


SOURCE_FILES = (
    "baselines/e7_dynamic/m1_dynamic_truth_gate.py",
    "solver/src/setp_solver/search/dynamic.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/tests/test_dynamic_truth_gate.py",
    "solver/tests/test_formal_runner.py",
)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(root: Path, nodeids: list[str]) -> dict[str, Any]:
    command = ["/opt/anaconda3/bin/python3", "-m", "pytest", "-q", *nodeids]
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = f"{root / 'solver/src'}:{root / 'solver/rl'}"
    result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, check=False)
    output = result.stdout + result.stderr
    matches = re.findall(r"(\d+) passed", output)
    return {
        "check": "pytest",
        "command": " ".join(command),
        "returncode": result.returncode,
        "passed": sum(int(value) for value in matches),
        "output": output.strip(),
        "ok": result.returncode == 0,
    }


def artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    dynamic_source = (root / "solver/src/setp_solver/search/dynamic.py").read_text(encoding="utf-8")
    source_gate = {
        "check": "source_entry",
        "legacy_alns_reference_count": dynamic_source.count("run_alns_wouda"),
        "independent_entry_reference_count": dynamic_source.count("run_resetp_alns"),
        "backend_label_present": "setp_solver.algorithms.resetp_alns" in dynamic_source,
    }
    source_gate["ok"] = (
        source_gate["legacy_alns_reference_count"] == 0
        and source_gate["independent_entry_reference_count"] >= 3
        and source_gate["backend_label_present"]
    )

    dynamic_tests = run_pytest(root, ["solver/tests/test_dynamic_truth_gate.py", "solver/tests/test_check.py"])
    formal_test = run_pytest(
        root,
        ["solver/tests/test_formal_runner.py::FormalRunnerTests::test_dynamic_report_halts_when_final_dynamic_check_fails"],
    )

    replay_dir = output / "e2_replay_post_dynamic_port"
    replay_command = [
        "/opt/anaconda3/bin/python3",
        "baselines/contract_audit/e1_e7_submission_contract_audit.py",
        "--repo-root",
        str(root),
        "--output-dir",
        str(replay_dir),
    ]
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = f"{root / 'solver/src'}:{root / 'solver/rl'}"
    replay_result = subprocess.run(replay_command, cwd=root, env=env, text=True, capture_output=True, check=False)
    replay_decision_path = replay_dir / "decision.json"
    replay_decision = json.loads(replay_decision_path.read_text(encoding="utf-8")) if replay_decision_path.exists() else {}
    replay_gate = {
        "check": "frozen_e2_replay_after_dynamic_port",
        "returncode": replay_result.returncode,
        "rows": replay_decision.get("e2_rows_replayed", 0),
        "all_zero_violation_and_cost_match": replay_decision.get(
            "e2_all_current_checker_zero_violation_and_cost_match", False
        ),
        "internal_comparison_still_valid": replay_decision.get("e2_internal_algorithm_comparison_still_valid", False),
    }
    replay_gate["ok"] = (
        replay_gate["returncode"] == 0
        and replay_gate["rows"] == 270
        and replay_gate["all_zero_violation_and_cost_match"]
        and replay_gate["internal_comparison_still_valid"]
    )

    evidence_rows = [source_gate, dynamic_tests, formal_test, replay_gate]
    raw_fields = sorted({key for row in evidence_rows for key in row})
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=raw_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(evidence_rows)

    passed = all(bool(row["ok"]) for row in evidence_rows)
    decision = {
        "verdict": "M1_DYNAMIC_LIVE_STATE_CONTRACT_SUPPORTED" if passed else "HALT_M1_DYNAMIC_LIVE_STATE_CONTRACT",
        "all_checks_passed": passed,
        "legacy_alns_reference_count": source_gate["legacy_alns_reference_count"],
        "dynamic_and_checker_tests_passed": dynamic_tests["passed"],
        "formal_final_check_test_passed": formal_test["passed"],
        "frozen_e2_rows_replayed": replay_gate["rows"],
        "frozen_e2_still_zero_violation_and_cost_match": replay_gate["all_zero_violation_and_cost_match"],
        "claim_boundary": (
            "The rolling foundation now preserves live vehicle state and uses the independent ReSETP ALNS backend. "
            "This does not prove that dynamic demand improves cost or creates low-carbon charging windows."
        ),
    }
    execution_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    metadata = {
        "schema_version": "resetp.m1_dynamic_truth_gate.v1",
        "execution_commit": execution_commit,
        "zero_search": True,
        "source_hashes": {path: sha256(root / path) for path in SOURCE_FILES},
        "source_files": list(SOURCE_FILES),
    }
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    report = [
        "# M1 dynamic live-state truth gate",
        "",
        f"Verdict: `{decision['verdict']}`.",
        "",
        "大白话：动态滚动现在不会再偷偷调用旧 ALNS，也不会在每次重规划时把车辆当成回到车场、满电满载重新出发。",
        "车辆当前位置和在途进度、当前时间、剩余载重、剩余电量、正在进行的充电，以及已经锁定的客户和顺序，均进入检查与后续规划合同。最后收尾不再另起一套求解器重建路线；漏掉客户会明确停止。",
        "",
        f"动态实况和检查测试通过 {dynamic_tests['passed']} 项，最终检查停机测试通过 {formal_test['passed']} 项。",
        f"为了确认这次加强动态检查没有误伤冻结 E2，重新只读回放 {replay_gate['rows']} 行保存解；零违规且成本一致：{replay_gate['all_zero_violation_and_cost_match']}。",
        "",
        "边界：这一步只证明动态地基可信。它还没有证明动态需求比静态方案更便宜，也没有证明动态需求能够把充电推到低碳时段。后两项仍需独立机制实验。",
        "",
    ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    write_json(output / "artifact_hashes.json", artifact_hashes(output))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
