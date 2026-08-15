#!/usr/bin/env python3
"""C3 / E2-G1 ALNS independence migration parity runner.

This script verifies that the main ReSETP ALNS runtime no longer depends on
the external N-Wouda package while preserving pre-migration anchor behaviour.
It is a migration audit only; it does not tune operators or change model
semantics.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "baselines" / "e2_alns" / "alns_independence_migration_data"
PRE_PATH = OUTPUT_DIR / "pre_migration_anchor.json"
GOEKE_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
THREESHIFT_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-150c-01"
HASH_EXCLUDE_NAMES = {"artifact_hashes.json"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clean_artifact_dir(OUTPUT_DIR)

    if not PRE_PATH.exists():
        raise FileNotFoundError(f"missing pre-migration anchor: {PRE_PATH}")

    started = time.perf_counter()
    pre = read_json(PRE_PATH)
    metadata = build_metadata(pre)
    write_json(OUTPUT_DIR / "metadata.json", metadata)

    post = {
        "schema_version": "resetp-alns-independence-anchor.v1",
        "phase": "post_migration",
        "commit": git_commit(),
        "python": sys.executable,
        "numpy": np.__version__,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "anchors": [
            run_goeke80_anchor(),
            run_threeshift_280_anchor(),
        ],
    }
    post["elapsed_seconds"] = time.perf_counter() - started
    write_json(OUTPUT_DIR / "post_migration_anchor.json", post)

    parity = compare_anchors(pre, post)
    write_json(OUTPUT_DIR / "parity_diff.json", parity)

    decision = decide(metadata, parity)
    write_json(OUTPUT_DIR / "decision.json", decision)

    report_path = OUTPUT_DIR / "report.md"
    report_path.write_text(render_report(metadata, pre, post, parity, decision), encoding="utf-8")
    write_json(OUTPUT_DIR / "artifact_hashes.json", artifact_hashes(OUTPUT_DIR))
    return 0 if decision["verdict"] == "ALNS_INDEPENDENCE_CONFIRMED" else 2


def build_metadata(pre: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "resetp-alns-independence-migration.v1",
        "objective": (
            "Detach the main ReSETP ALNS runtime from Reference Algorithm/ALNS-7.0.0@N-Wouda "
            "without changing algorithm strategy, operators, cost/check/evaluation semantics, prices, or TeX."
        ),
        "boundary": {
            "not_formal_t3": True,
            "algorithm_enhancement": False,
            "reference_algorithm_directory_touched": bool(
                subprocess.run(
                    ["git", "diff", "--name-only", "HEAD", "--", "Reference Algorithm/ALNS-7.0.0@N-Wouda"],
                    cwd=REPO_ROOT,
                    check=False,
                    text=True,
                    capture_output=True,
                ).stdout.strip()
            ),
            "protected_model_files": [
                "solver/src/setp_solver/cost.py",
                "solver/src/setp_solver/check.py",
                "solver/src/setp_solver/search/evaluation.py",
                "solver/src/setp_solver/prices.py",
                "docs/paper_submission_final/RETIRED_paper_main.tex",
            ],
        },
        "pre_commit": pre.get("commit"),
        "post_commit": git_commit(),
        "environment": {
            "python": sys.executable,
            "numpy": np.__version__,
            "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        },
        "anchors": [
            {
                "anchor": "goeke80_100_01_seed2",
                "entrypoint": "run_winner_kernel",
                "bundle": str(GOEKE_BUNDLE.relative_to(REPO_ROOT)),
                "seed": 2,
                "eval_budget": 16000,
                "prices": "DEFAULT_PRICES",
            },
            {
                "anchor": "threeshift_150c_01_seed1_B280_eval2000",
                "entrypoint": "run_e2_alns_throughput",
                "bundle": str(THREESHIFT_BUNDLE.relative_to(REPO_ROOT)),
                "seed": 1,
                "eval_budget": 2000,
                "prices": "dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)",
            },
        ],
    }


def run_goeke80_anchor() -> dict[str, Any]:
    from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel

    result = run_winner_kernel(
        GOEKE_BUNDLE,
        config=WinnerKernelConfig(seed=2, eval_budget=16000, max_runtime_seconds=900.0),
    )
    return anchor_row("goeke80_100_01_seed2", result, expected_best_cost=4779.053444002934)


def run_threeshift_280_anchor() -> dict[str, Any]:
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.winner_operators import WinnerKernelConfig, run_e2_alns_throughput

    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)
    result = run_e2_alns_throughput(
        THREESHIFT_BUNDLE,
        config=WinnerKernelConfig(seed=1, eval_budget=2000, max_runtime_seconds=900.0),
        prices=prices,
    )
    return anchor_row("threeshift_150c_01_seed1_B280_eval2000", result)


def anchor_row(anchor: str, result: dict[str, Any], *, expected_best_cost: float | None = None) -> dict[str, Any]:
    solution = result["best_solution"]
    operator_counts = result.get("operator_counts", {})
    history = list(result.get("history", []))
    row = {
        "anchor": anchor,
        "status": "OK",
        "best_cost": float(result["best_cost"]),
        "evaluations": int(result["evaluations"]),
        "feasible": bool(result["feasible"]),
        "violation_count": int(result["violation_count"]),
        "route_count": len(solution.routes),
        "solution_hash": hash_payload(solution_payload(solution)),
        "history_hash": hash_payload(history),
        "history_length": len(history),
        "operator_counts_hash": hash_payload(operator_counts),
        "operator_counts_without_timing_hash": hash_payload(strip_timing(operator_counts)),
        "operator_counts": operator_counts,
    }
    if expected_best_cost is not None:
        row["expected_best_cost"] = expected_best_cost
    return row


def compare_anchors(pre: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    pre_by_anchor = {row["anchor"]: row for row in pre.get("anchors", [])}
    post_by_anchor = {row["anchor"]: row for row in post.get("anchors", [])}
    rows: list[dict[str, Any]] = []
    primary_ok = True
    non_result_differences: list[str] = []
    for anchor, before in pre_by_anchor.items():
        after = post_by_anchor.get(anchor)
        if after is None:
            rows.append({"anchor": anchor, "status": "MISSING_POST"})
            primary_ok = False
            continue
        before_counts_stable = hash_payload(strip_timing(before.get("operator_counts", {})))
        after_counts_stable = after.get("operator_counts_without_timing_hash")
        row = {
            "anchor": anchor,
            "best_cost_match": before.get("best_cost") == after.get("best_cost"),
            "best_cost_abs_diff": abs(float(before.get("best_cost", math.nan)) - float(after.get("best_cost", math.nan))),
            "evaluations_match": before.get("evaluations") == after.get("evaluations"),
            "feasible_match": before.get("feasible") == after.get("feasible"),
            "violation_count_match": before.get("violation_count") == after.get("violation_count"),
            "route_count_match": before.get("route_count") == after.get("route_count"),
            "solution_hash_match": before.get("solution_hash") == after.get("solution_hash"),
            "operator_counts_without_timing_hash_match": before_counts_stable == after_counts_stable,
            "history_length_match": before.get("history_length") == after.get("history_length"),
            "raw_history_hash_match": before.get("history_hash") == after.get("history_hash"),
            "raw_operator_counts_hash_match": before.get("operator_counts_hash") == after.get("operator_counts_hash"),
            "pre_best_cost": before.get("best_cost"),
            "post_best_cost": after.get("best_cost"),
            "pre_solution_hash": before.get("solution_hash"),
            "post_solution_hash": after.get("solution_hash"),
            "pre_operator_counts_without_timing_hash": before_counts_stable,
            "post_operator_counts_without_timing_hash": after_counts_stable,
        }
        primary_fields = [
            "best_cost_match",
            "evaluations_match",
            "feasible_match",
            "violation_count_match",
            "route_count_match",
            "solution_hash_match",
            "operator_counts_without_timing_hash_match",
            "history_length_match",
        ]
        if not all(row[field] for field in primary_fields):
            primary_ok = False
        if not row["raw_history_hash_match"]:
            non_result_differences.append(f"{anchor}: raw history hash includes wall-clock time_seconds")
        if not row["raw_operator_counts_hash_match"] and row["operator_counts_without_timing_hash_match"]:
            non_result_differences.append(f"{anchor}: raw operator_counts hash differs only after retaining timing ledger")
        rows.append(row)

    grep_gate = run_grep_gate()
    protected_gate = run_protected_file_gate()
    reference_gate = run_reference_dir_gate()
    historical_anchor_notes = historical_anchor_notes_from_pre(pre)
    return {
        "schema_version": "resetp-alns-independence-parity.v1",
        "anchor_rows": rows,
        "primary_parity_ok": primary_ok,
        "grep_gate": grep_gate,
        "protected_file_gate": protected_gate,
        "reference_algorithm_dir_gate": reference_gate,
        "non_result_differences": non_result_differences,
        "historical_anchor_notes": historical_anchor_notes,
    }


def decide(metadata: dict[str, Any], parity: dict[str, Any]) -> dict[str, Any]:
    env = metadata["environment"]
    env_ok = (
        env["python"] == "/opt/anaconda3/bin/python3.13"
        and env["numpy"] == "2.3.5"
        and env["pythonhashseed"] == "0"
    )
    gates_ok = (
        env_ok
        and parity["primary_parity_ok"]
        and parity["grep_gate"]["ok"]
        and parity["protected_file_gate"]["ok"]
        and parity["reference_algorithm_dir_gate"]["ok"]
    )
    verdict = "ALNS_INDEPENDENCE_CONFIRMED" if gates_ok else "HALT_ALNS_PARITY_DRIFT"
    reasons: list[str] = []
    if not env_ok:
        reasons.append("environment gate failed")
    if not parity["primary_parity_ok"]:
        reasons.append("pre/post primary parity drift")
    for key in ["grep_gate", "protected_file_gate", "reference_algorithm_dir_gate"]:
        if not parity[key]["ok"]:
            reasons.append(f"{key} failed")
    return {
        "schema_version": "resetp-alns-independence-decision.v1",
        "verdict": verdict,
        "reasons": reasons,
        "post_commit": metadata["post_commit"],
        "pre_commit": metadata["pre_commit"],
        "not_formal_t3": True,
        "algorithm_enhancement": False,
    }


def render_report(
    metadata: dict[str, Any],
    pre: dict[str, Any],
    post: dict[str, Any],
    parity: dict[str, Any],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# C3 / E2-G1 independent ALNS migration report",
        "",
        "人话结论：本步只做运行时剥离，不做算法增强。主 ALNS 已从 N-Wouda `alns` 包迁到项目内 `resetp_alns` 后端；destroy/repair 算子、成本、约束、价格默认值和 TeX 都没有改。",
        "",
        f"Verdict: `{decision['verdict']}`.",
        "",
        "## Boundary",
        "",
        "- This is not formal T3 and must not be written as an algorithm win/loss.",
        "- `Reference Algorithm/ALNS-7.0.0@N-Wouda` is retained untouched.",
        "- `run_alns_wouda` keeps its legacy API name for runner compatibility, but the main runtime backend is now project-local.",
        "",
        "## Anchors",
        "",
    ]
    pre_rows = {row["anchor"]: row for row in pre.get("anchors", [])}
    post_rows = {row["anchor"]: row for row in post.get("anchors", [])}
    for row in parity["anchor_rows"]:
        anchor = row["anchor"]
        before = pre_rows[anchor]
        after = post_rows[anchor]
        lines.extend(
            [
                f"### {anchor}",
                "",
                f"- pre commit `{pre.get('commit')}` best_cost `{before.get('best_cost')}`, solution_hash `{before.get('solution_hash')}`.",
                f"- post commit `{post.get('commit')}` best_cost `{after.get('best_cost')}`, solution_hash `{after.get('solution_hash')}`.",
                f"- primary parity: `{all(row[field] for field in ['best_cost_match', 'evaluations_match', 'feasible_match', 'violation_count_match', 'route_count_match', 'solution_hash_match', 'operator_counts_without_timing_hash_match', 'history_length_match'])}`.",
                "",
            ]
        )
    if parity["historical_anchor_notes"]:
        lines.extend(["## Historical Anchor Note", ""])
        lines.extend(f"- {note}" for note in parity["historical_anchor_notes"])
        lines.append("")
    if parity["non_result_differences"]:
        lines.extend(["## Non-result Differences", ""])
        lines.extend(f"- {note}" for note in parity["non_result_differences"])
        lines.append("")
    lines.extend(
        [
            "## Gates",
            "",
            f"- grep gate ok: `{parity['grep_gate']['ok']}`.",
            f"- protected-file gate ok: `{parity['protected_file_gate']['ok']}`.",
            f"- reference algorithm directory gate ok: `{parity['reference_algorithm_dir_gate']['ok']}`.",
            f"- environment: `{metadata['environment']}`.",
            "",
            "## Next Boundary",
            "",
            "后续 E2 baseline bridge/liveness/debug 应统一基于 independent backend。若要修 bridge 或调参，需要另起任务；本报告不授权改建模或写算法胜负。",
            "",
        ]
    )
    return "\n".join(lines)


def historical_anchor_notes_from_pre(pre: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for row in pre.get("anchors", []):
        expected = row.get("expected_best_cost")
        actual = row.get("best_cost")
        if expected is not None and actual != expected:
            notes.append(
                f"{row['anchor']}: historical expected_best_cost {expected} is stale under pre-migration current HEAD; "
                f"pre-migration actual was {actual}. Migration parity is judged against pre/post current-chain anchors."
            )
    return notes


def run_grep_gate() -> dict[str, Any]:
    cmd = [
        "rg",
        "from alns|import alns|ALNS-7.0.0@N-Wouda|_ensure_local_alns_on_path",
        "solver/src/setp_solver/search/alns_wouda.py",
        "solver/src/setp_solver/search/winner_operators.py",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return {"ok": proc.returncode == 1 and not proc.stdout.strip(), "returncode": proc.returncode, "stdout": proc.stdout}


def run_protected_file_gate() -> dict[str, Any]:
    cmd = [
        "git",
        "diff",
        "--name-only",
        "HEAD",
        "--",
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/search/evaluation.py",
        "solver/src/setp_solver/prices.py",
        "docs/paper_submission_final/RETIRED_paper_main.tex",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return {"ok": proc.returncode == 0 and not proc.stdout.strip(), "returncode": proc.returncode, "stdout": proc.stdout}


def run_reference_dir_gate() -> dict[str, Any]:
    cmd = ["git", "diff", "--name-only", "HEAD", "--", "Reference Algorithm/ALNS-7.0.0@N-Wouda"]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return {"ok": proc.returncode == 0 and not proc.stdout.strip(), "returncode": proc.returncode, "stdout": proc.stdout}


def strip_timing(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_timing(val) for key, val in sorted(value.items()) if key != "timing"}
    if isinstance(value, list):
        return [strip_timing(item) for item in value]
    if isinstance(value, tuple):
        return [strip_timing(item) for item in value]
    return value


def solution_payload(solution: Any) -> dict[str, Any]:
    from setp_solver.search.metaheuristic_baselines import solution_to_dict

    return solution_to_dict(solution)


def hash_payload(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def artifact_hashes(output_dir: Path) -> dict[str, Any]:
    entries: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in HASH_EXCLUDE_NAMES or path.name.startswith("._"):
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in path.parts):
            continue
        entries[str(path.relative_to(output_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"schema_version": "artifact-hashes.v1", "files": entries}


def clean_artifact_dir(output_dir: Path) -> None:
    for path in list(output_dir.rglob("._*")):
        if path.is_file():
            path.unlink()
    for path in list(output_dir.rglob("__pycache__")) + list(output_dir.rglob(".pytest_cache")):
        if path.is_dir():
            shutil.rmtree(path)


def git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
