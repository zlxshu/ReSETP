#!/usr/bin/env python3
"""Zero-search static audit of ReSETP ALNS evaluation-budget accounting.

This audit deliberately does not import or execute the solver.  It parses the
current ALNS sources, classifies every call into a model/full-solution scorer,
and joins that static evidence to the sealed 2026-07-10 local-search diagnosis.
It therefore cannot certify runtime closure; it can only prove that the current
source is not ready for a fair formal benchmark when blocking call sites remain.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
ALNS_ROOT = REPO_ROOT / "solver/src/setp_solver/algorithms/resetp_alns"
HISTORICAL_DIR = REPO_ROOT / "baselines/e2_alns/m1_local_search_budget_20260710"
DEFAULT_OUTPUT = REPO_ROOT / "baselines/e2_alns/e2_alns_budget_closure_static_20260717"

SCORER_NAMES = {
    "evaluate",
    "model_cost",
    "penalized_obj",
    "prepare_and_score_candidate",
    "prepare_and_score_reference",
    "score_candidate",
    "score_reference",
}


@dataclass(frozen=True)
class Rule:
    phase: str
    solution_scope: str
    accounting: str
    closure_status: str
    rationale: str


@dataclass(frozen=True)
class CallSite:
    source: str
    function: str
    callee: str
    occurrence: int
    line: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.source, self.function, self.callee, self.occurrence)


def _rule(
    phase: str,
    scope: str,
    accounting: str,
    status: str,
    rationale: str,
) -> Rule:
    return Rule(phase, scope, accounting, status, rationale)


# The key excludes line numbers so harmless line shifts do not invalidate the
# audit.  Any added/removed scorer call becomes an explicit unclassified row.
EXPECTED_RULES: dict[tuple[str, str, str, int], Rule] = {
    # Independent ALNS shell.
    ("kernel/alns_core.py", "objective", "score_reference", 0): _rule(
        "search_state_fallback", "complete_solution", "unbudgeted_reference",
        "BLOCK", "A search state can obtain an objective without EvalBudget.record().",
    ),
    ("kernel/alns_core.py", "run_alns_wouda", "prepare_and_score_reference", 0): _rule(
        "initial_reference", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Initial reference scoring may be outside the search budget, but it has no explicit reference counter.",
    ),
    ("kernel/alns_core.py", "_run_adaptive_sa_alns", "prepare_and_score_reference", 0): _rule(
        "search_candidate_reprepare", "complete_solution", "unbudgeted_reference",
        "BLOCK", "A prepared search candidate is rescored through the non-budget reference path.",
    ),
    ("kernel/alns_core.py", "_finalize_candidate_state", "prepare_and_score_candidate", 0): _rule(
        "search_candidate_selection", "complete_solution", "eval_budget_recorded",
        "PASS", "The candidate scorer records one complete search evaluation.",
    ),
    ("kernel/alns_core.py", "_repair_solution_delta_score", "score_reference", 0): _rule(
        "repair_full_solution_score", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Exact repair scoring evaluates a complete Solution without charging EvalBudget.",
    ),
    ("kernel/alns_core.py", "_repair_solution_delta_score", "evaluate", 0): _rule(
        "repair_full_solution_score", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "Fast repair scoring calls the full model evaluator without charging EvalBudget.",
    ),
    # Winner kernel and staged wrappers.
    ("kernel/winner.py", "apply_winner_action", "prepare_and_score_candidate", 0): _rule(
        "search_candidate_selection", "complete_solution", "eval_budget_recorded",
        "PASS", "The candidate scorer records one complete search evaluation.",
    ),
    ("kernel/winner.py", "run_true_lns_middle_alns_hybrid", "model_cost", 0): _rule(
        "stage_winner_selection", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "Three stage winners are compared using unbudgeted complete-solution model costs.",
    ),
    ("kernel/winner.py", "run_true_lns_middle_alns_hybrid", "model_cost", 1): _rule(
        "final_reporting", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Final reporting may stay outside the search budget, but it has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_run_staged_hybrid_entry", "model_cost", 0): _rule(
        "final_reporting", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Final reporting has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_reschedule_staged_result", "model_cost", 0): _rule(
        "final_reporting", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Post-schedule reporting has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_run_winner_variant", "model_cost", 0): _rule(
        "final_reporting", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Final reporting has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_run_winner_kernel_loop", "prepare_and_score_reference", 0): _rule(
        "initial_reference", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Initial reference scoring has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_run_winner_kernel_loop", "prepare_and_score_candidate", 0): _rule(
        "search_candidate_selection", "complete_solution", "eval_budget_recorded",
        "PASS", "The candidate scorer records one complete search evaluation.",
    ),
    ("kernel/winner.py", "_run_winner_kernel_loop", "prepare_and_score_candidate", 1): _rule(
        "search_candidate_selection", "complete_solution", "eval_budget_recorded",
        "PASS", "The candidate scorer records one complete search evaluation.",
    ),
    ("kernel/winner.py", "_run_winner_kernel_loop", "prepare_and_score_reference", 1): _rule(
        "final_reference", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Final reference scoring may be outside the search budget, but it has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_winner_history_entry", "model_cost", 0): _rule(
        "history_reporting", "complete_solution", "unbudgeted_reference",
        "BLOCK", "History reporting has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_candidate_change_and_violations", "prepare_and_score_reference", 0): _rule(
        "search_candidate_reprepare", "complete_solution", "unbudgeted_reference",
        "BLOCK", "A changed complete candidate is rescored through the non-budget reference path.",
    ),
    ("kernel/winner.py", "_candidate_change_and_violations", "prepare_and_score_reference", 1): _rule(
        "local_search_candidate", "complete_solution", "unbudgeted_reference",
        "BLOCK", "A locally improved candidate is rescored through the non-budget reference path.",
    ),
    ("kernel/winner.py", "_maybe_write_e2_checkpoint", "model_cost", 0): _rule(
        "checkpoint_reporting", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Checkpoint reporting has no explicit reference counter.",
    ),
    ("kernel/winner.py", "_scan_restart_state", "prepare_and_score_candidate", 0): _rule(
        "search_candidate_selection", "complete_solution", "eval_budget_recorded",
        "PASS", "The scan/restart candidate scorer records one complete search evaluation.",
    ),
    # Operators and structural components.
    ("operators/local_search.py", "_score_internal_solution", "score_reference", 0): _rule(
        "local_search_candidate", "complete_solution", "unbudgeted_reference",
        "BLOCK", "Every local-search incumbent and neighbor uses a non-budget full score.",
    ),
    ("operators/carbon_operators.py", "_route_carbon_kg", "evaluate", 0): _rule(
        "route_feature", "single_route", "non_full_repair_or_feature",
        "PASS", "This is a route-local feature, outside the complete-solution budget gate.",
    ),
    ("operators/carbon_operators.py", "_solution_carbon_kg", "evaluate", 0): _rule(
        "search_feature", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "A complete-solution carbon feature calls the model evaluator during search without budget accounting.",
    ),
    ("operators/feasible_repair.py", "_solution_cost", "evaluate", 0): _rule(
        "repair_full_solution_fallback", "complete_or_intermediate_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "Repair fallback invokes the full model evaluator without one-to-one EvalBudget accounting.",
    ),
    ("operators/repair_scoring.py", "route_model_cost", "evaluate", 0): _rule(
        "route_delta", "single_route", "repair_delta_channel",
        "PASS", "Route-local insertion deltas are not complete candidate evaluations and use the repair-delta channel.",
    ),
    ("support/fleet_charge_corepair.py", "propose_fleet_charge_corepair", "evaluate", 0): _rule(
        "structural_candidate_metrics", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "The structural search evaluates the current complete solution outside EvalBudget.",
    ),
    ("support/fleet_charge_corepair.py", "propose_fleet_charge_corepair", "evaluate", 1): _rule(
        "structural_candidate_metrics", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "Each feasible structural candidate is evaluated outside EvalBudget.",
    ),
    ("support/fleet_charge_corepair.py", "propose_fleet_charge_corepair", "evaluate", 2): _rule(
        "structural_candidate_metrics", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "The selected structural candidate is evaluated outside EvalBudget.",
    ),
    ("support/fleet_charge_corepair.py", "_feasible_model_cost", "model_cost", 0): _rule(
        "structural_candidate_selection", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "Structural candidate selection compares complete model costs outside EvalBudget.",
    ),
    ("support/global_order_repack.py", "_feasible_model_cost", "model_cost", 0): _rule(
        "structural_candidate_selection", "complete_solution", "unbudgeted_direct_model_eval",
        "BLOCK", "Global-order repack candidate selection compares complete model costs outside EvalBudget.",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip())
    return commit, dirty


def _callee_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def scan_scorer_calls() -> list[CallSite]:
    rows: list[CallSite] = []
    for path in sorted(ALNS_ROOT.rglob("*.py")):
        if path.name.startswith("._"):
            continue
        source = path.relative_to(ALNS_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        function_stack: list[str] = []
        counts: dict[tuple[str, str], int] = {}

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                function_stack.append(node.name)
                self.generic_visit(node)
                function_stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node: ast.Call) -> None:
                callee = _callee_name(node)
                if callee in SCORER_NAMES:
                    function = function_stack[-1] if function_stack else "<module>"
                    count_key = (function, callee)
                    occurrence = counts.get(count_key, 0)
                    counts[count_key] = occurrence + 1
                    rows.append(CallSite(source, function, callee, occurrence, node.lineno))
                self.generic_visit(node)

        Visitor().visit(tree)
    return sorted(rows, key=lambda row: (row.source, row.line, row.callee))


def verify_historical_inputs() -> dict[str, Any]:
    manifest_path = HISTORICAL_DIR / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    checks: dict[str, dict[str, Any]] = {}
    for name in required:
        path = HISTORICAL_DIR / name
        rel = path.relative_to(REPO_ROOT).as_posix()
        actual = sha256(path)
        expected = manifest.get(rel)
        checks[name] = {"expected_sha256": expected, "actual_sha256": actual, "match": actual == expected}
    if not all(item["match"] for item in checks.values()):
        raise RuntimeError("sealed historical budget evidence failed hash verification")

    with (HISTORICAL_DIR / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    current = [row for row in rows if row["profile"] == "CURRENT_T3"]
    if len(current) != 9:
        raise RuntimeError(f"expected 9 CURRENT_T3 historical rows, found {len(current)}")
    hidden = [int(row["hidden_full_solution_scores"]) for row in current]
    ratios = [float(row["effective_to_official_ratio"]) for row in current]
    derived = {
        "run_count": len(current),
        "hidden_full_solution_scores_total": sum(hidden),
        "hidden_full_solution_scores_min": min(hidden),
        "hidden_full_solution_scores_max": max(hidden),
        "effective_to_official_ratio_mean": round(sum(ratios) / len(ratios), 3),
    }
    expected_derived = {
        "run_count": 9,
        "hidden_full_solution_scores_total": 11547,
        "hidden_full_solution_scores_min": 760,
        "hidden_full_solution_scores_max": 2164,
        "effective_to_official_ratio_mean": 13.83,
    }
    if derived != expected_derived:
        raise RuntimeError(f"historical budget evidence derived values drifted: {derived}")
    return {"surface_hash_checks": checks, "derived": derived}


def classify_calls(calls: list[CallSite]) -> list[dict[str, Any]]:
    actual_keys = {call.key for call in calls}
    missing = sorted(set(EXPECTED_RULES) - actual_keys)
    if missing:
        raise RuntimeError(f"expected scorer call sites disappeared; contract requires review: {missing}")
    rows: list[dict[str, Any]] = []
    for call in calls:
        rule = EXPECTED_RULES.get(call.key)
        if rule is None:
            rule = _rule(
                "unclassified", "unknown", "unknown", "BLOCK",
                "New or moved scorer call is not covered by the static accounting contract.",
            )
        rows.append({**asdict(call), **asdict(rule)})
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "source", "function", "callee", "occurrence", "line", "phase",
        "solution_scope", "accounting", "closure_status", "rationale",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact_key(path: Path, output_dir: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return f"OUTPUT/{path.relative_to(output_dir).as_posix()}"


def run_audit(output_dir: Path) -> dict[str, Any]:
    historical = verify_historical_inputs()
    calls = scan_scorer_calls()
    rows = classify_calls(calls)
    blockers = [row for row in rows if row["closure_status"] == "BLOCK"]
    unclassified = [row for row in rows if row["phase"] == "unclassified"]
    budgeted = [row for row in rows if row["accounting"] == "eval_budget_recorded"]
    commit, dirty = git_state()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(path.name.startswith("._") for path in output_dir.rglob("*")):
        raise RuntimeError("HASH_CONTAMINATED_APPLEDOUBLE")

    _write_csv(output_dir / "raw_runs.csv", rows)
    metadata = {
        "schema_version": "setp-e2-alns-budget-closure-static.v1",
        "audit_kind": "zero_search_static_source_audit",
        "search_evaluations": 0,
        "experiments_started": 0,
        "repo_commit": commit,
        "repo_dirty_at_audit": dirty,
        "source_root": ALNS_ROOT.relative_to(REPO_ROOT).as_posix(),
        "historical_evidence": HISTORICAL_DIR.relative_to(REPO_ROOT).as_posix(),
        "historical_surface_hash_checks": historical["surface_hash_checks"],
        "scorer_names": sorted(SCORER_NAMES),
    }
    decision = {
        "schema_version": "setp-e2-alns-budget-closure-decision.v1",
        "verdict": "HALT_ALNS_BUDGET_CLOSURE_REQUIRED",
        "formal_benchmark_authorized": False,
        "algorithm_win_loss_claim": False,
        "search_evaluations": 0,
        "scorer_call_count": len(rows),
        "budgeted_complete_candidate_call_sites": len(budgeted),
        "closure_blocker_call_sites": len(blockers),
        "unclassified_call_sites": len(unclassified),
        "historical_diagnosis": historical["derived"],
        "g0_post_e7_acceptance": {
            "search_complete_solution_scores": "Each candidate-selection, local-search, repair, or structural complete-solution score records exactly one EvalBudget evaluation.",
            "reference_scores": "Initial, final, history, and checkpoint scores remain outside the search budget only if separately counted as reference_full_solution scores.",
            "route_or_incomplete_deltas": "Route-local or incomplete repair deltas remain outside the complete-solution budget only if separately counted and never used as an uncharged complete-candidate selector.",
            "static_closure": "Every scorer call is classified; no BLOCK or unclassified call site remains.",
            "runtime_closure": "After E7 closes, zero/tiny-budget tests prove one-to-one candidate count and EvalBudget count before any formal benchmark.",
        },
    }
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "decision.json", decision)

    source_blockers = sorted({f"{row['source']}:{row['function']}" for row in blockers})
    report = "\n".join(
        [
            "# ALNS 评价预算闭合静态审计（零搜索）",
            "",
            "判定：`HALT_ALNS_BUDGET_CLOSURE_REQUIRED`。",
            "",
            "本任务没有启动求解器、没有运行算例、没有读取 E7 中间结果，`search_evaluations=0`。审计仅解析当前 `resetp_alns` 源码，并复核 2026-07-10 封存诊断的四个输入表面哈希。",
            "",
            "## 已确认的不利证据",
            "",
            f"历史 9 次 CURRENT_T3 运行产生 {historical['derived']['hidden_full_solution_scores_total']} 次未计入正式预算的完整解评分；单次为 {historical['derived']['hidden_full_solution_scores_min']}--{historical['derived']['hidden_full_solution_scores_max']} 次，实际/报告评价数均值比为 {historical['derived']['effective_to_official_ratio_mean']:.3f}。这些数值由封存 `raw_runs.csv` 重新计算，不是从旧报告抄写。",
            "",
            f"当前源码共识别 {len(rows)} 个相关评分调用点，其中 {len(budgeted)} 个明确走预算化完整候选通道，{len(blockers)} 个仍不满足 G0 闭合标准，未分类调用点 {len(unclassified)} 个。",
            "",
            "阻断位置（按函数去重）：",
            "",
            *[f"- `{item}`" for item in source_blockers],
            "",
            "`raw_runs.csv` 逐行区分：搜索期完整候选、初始/终局/历史/断点参考评分、路线局部增量以及结构搜索评分。允许留在正式搜索预算之外的参考评分目前也没有独立计数，因此仍不能宣称预算口径闭合。",
            "",
            "## E7 后 G0 验收标准",
            "",
            "1. 每次参与候选选择、局部搜索、修复或结构重组的完整解评分，恰好调用一次 `EvalBudget.record()`。",
            "2. 初始、终局、历史和断点复算可不占搜索预算，但必须进入独立的 `reference_full_solution` 计数。",
            "3. 路线局部或未完成修复增量必须进入独立计数，且不得被用作未收费的完整候选选择器。",
            "4. 静态审计不得残留 `BLOCK` 或未分类调用点；随后用零/极小预算行为测试验证候选计数与预算一一对应。",
            "5. 上述标准全部通过前，不得启动正式 Solomon/Homberger 算法胜负测试，也不得声称算法性能领先。",
            "",
            "本次 HALT 是口径门禁，不是算法胜负结论。共享算法内核未在本任务中修改。",
            "",
        ]
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    hash_targets = [
        Path(__file__).resolve(),
        HISTORICAL_DIR / "artifact_hashes.json",
        HISTORICAL_DIR / "metadata.json",
        HISTORICAL_DIR / "raw_runs.csv",
        HISTORICAL_DIR / "decision.json",
        HISTORICAL_DIR / "report.md",
        output_dir / "metadata.json",
        output_dir / "raw_runs.csv",
        output_dir / "decision.json",
        output_dir / "report.md",
        *sorted(path for path in ALNS_ROOT.rglob("*.py") if not path.name.startswith("._")),
    ]
    hashes = {
        _artifact_key(path, output_dir): sha256(path)
        for path in hash_targets
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = run_audit(args.output_dir.resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
