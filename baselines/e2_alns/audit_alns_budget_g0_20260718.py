#!/usr/bin/env python3
"""Zero-search G0 audit for ALNS complete-solution accounting."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
ALNS_ROOT = REPO_ROOT / "solver/src/setp_solver/algorithms/resetp_alns"
DEFAULT_OUTPUT = REPO_ROOT / "baselines/e2_alns/e2_alns_budget_g0_static_20260718"

DIRECT_SCORERS = {
    "evaluate",
    "model_cost",
    "penalized_obj",
    "prepare_and_score_candidate",
    "prepare_and_score_reference",
    "score_candidate",
    "score_reference",
}
ACCOUNTED_CHANNELS = {
    "score_search_candidate": "candidate",
    "score_reference_solution": "reference",
    "reference_model_cost": "reference",
    "cached_or_reference_model_cost": "reference_or_cache",
    "record_repair_delta": "repair_delta",
}
ALLOWED_DIRECT = {
    ("runtime/budgeted_scoring.py", "score_search_candidate", "prepare_and_score_candidate"),
    ("runtime/budgeted_scoring.py", "score_reference_solution", "prepare_and_score_reference"),
    ("operators/carbon_operators.py", "_route_carbon_kg", "evaluate"),
    ("operators/repair_scoring.py", "route_model_cost", "evaluate"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _callee(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def scan() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(ALNS_ROOT.rglob("*.py")):
        if path.name.startswith("._"):
            continue
        source = path.relative_to(ALNS_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node: ast.Call) -> None:
                callee = _callee(node)
                if callee in DIRECT_SCORERS | set(ACCOUNTED_CHANNELS):
                    function = stack[-1] if stack else "<module>"
                    direct = callee in DIRECT_SCORERS
                    allowed_direct = (source, function, callee) in ALLOWED_DIRECT
                    if direct:
                        status = "PASS" if allowed_direct else "BLOCK"
                        channel = "route_delta_or_feature" if allowed_direct else "unclassified_direct"
                    else:
                        status = "PASS"
                        channel = ACCOUNTED_CHANNELS[callee]
                    rows.append(
                        {
                            "source": source,
                            "function": function,
                            "callee": callee,
                            "line": int(node.lineno),
                            "channel": channel,
                            "closure_status": status,
                        }
                    )
                self.generic_visit(node)

        Visitor().visit(tree)
    return rows


def run_audit(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    rows = scan()
    blockers = [row for row in rows if row["closure_status"] == "BLOCK"]
    unclassified = [row for row in rows if row["channel"] == "unclassified_direct"]
    required = {
        "candidate": any(row["channel"] == "candidate" for row in rows),
        "reference": any(row["channel"] in {"reference", "reference_or_cache"} for row in rows),
        "repair_delta": any(row["channel"] == "repair_delta" for row in rows),
    }
    verdict = (
        "PASS_ALNS_BUDGET_G0_STATIC_CLOSURE"
        if not blockers and not unclassified and all(required.values())
        else "HALT_ALNS_BUDGET_CLOSURE_REQUIRED"
    )
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "resetp.alns-budget-g0.metadata.v1",
        "audit_kind": "zero_search_static_source_audit",
        "search_evaluations": 0,
        "experiments_started": 0,
        "alns_root": str(ALNS_ROOT.relative_to(REPO_ROOT)),
        "historical_halt_package": "baselines/e2_alns/e2_alns_budget_closure_static_20260717",
    }
    decision = {
        "schema": "resetp.alns-budget-g0.decision.v1",
        "verdict": verdict,
        "search_evaluations": 0,
        "static_gate_passed": verdict == "PASS_ALNS_BUDGET_G0_STATIC_CLOSURE",
        "formal_benchmark_authorized": False,
        "scanned_call_sites": len(rows),
        "closure_blocker_call_sites": len(blockers),
        "unclassified_call_sites": len(unclassified),
        "required_channels_present": required,
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["source", "function", "callee", "line", "channel", "closure_status"],
        )
        writer.writeheader()
        writer.writerows(rows)
    (output / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        "# ALNS budget G0 static audit\n\n"
        f"Verdict: `{verdict}`.\n\n"
        f"Direct blockers: {len(blockers)}; unclassified: {len(unclassified)}; "
        "search evaluations: 0. Runtime behavior is certified separately.\n",
        encoding="utf-8",
    )
    artifacts = {
        name: _sha256(output / name)
        for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    }
    (output / "artifact_hashes.json").write_text(
        json.dumps(artifacts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return decision


if __name__ == "__main__":
    print(json.dumps(run_audit(), ensure_ascii=False, indent=2))
