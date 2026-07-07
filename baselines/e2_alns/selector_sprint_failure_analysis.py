#!/usr/bin/env python3
"""Read-only failure analysis for the selector sprint residual gap.

This diagnostic consumes existing selector-sprint artifacts. It does not run
new algorithms and does not change solver behavior.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
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


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as fc


DEFAULT_A5_DIR = REPO_ROOT / "baselines/e2_alns/selector_sprint_probe_20260706"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/selector_sprint_failure_analysis_20260707"
A7_PROFILE = "A7_SOFTMAX_SELECTOR_LOCAL_SEARCH"
LNS_PROFILE = "LNS_REFERENCE"
PROTECTED_PATHS = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/feasible_repair.py",
    "docs/paper_submission_final/paper_main.tex",
    "paper_main.tex",
)
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a5-dir", default=str(DEFAULT_A5_DIR))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    a5_dir = fc.repo_path(Path(args.a5_dir))
    output_dir = fc.repo_path(Path(args.output_dir))
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs = output_dir / "logs/full_run.log"
    logs.parent.mkdir(parents=True, exist_ok=True)
    log_event(logs, "start", a5_dir=fc.rel(a5_dir), output_dir=fc.rel(output_dir))

    metadata = build_metadata(a5_dir, output_dir)
    fc.write_json(output_dir / "metadata.json", metadata)
    missing = missing_inputs(a5_dir)
    protected = protected_diff()
    if missing or protected:
        write_empty_outputs(output_dir)
        decision = build_decision(metadata=metadata, gap_rows=[], route_fixed_rows=[], missing=missing, protected_diff=protected)
        fc.write_json(output_dir / "decision.json", decision)
        (output_dir / "diagnosis.md").write_text(write_diagnosis(decision, [], []), encoding="utf-8")
        (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
        write_hashes(output_dir)
        log_event(logs, "halt", verdict=decision["verdict"], missing=missing, protected=protected)
        return 2

    raw_rows = fc.read_csv(a5_dir / "raw_runs.csv")
    decomposition_rows = fc.read_csv(a5_dir / "route_fixed_cost_decomposition_by_budget.csv")
    profile_rows = []
    for budget in (4000, 8000, 16000):
        path = a5_dir / f"profile_summary_{budget}.csv"
        if path.exists():
            profile_rows.extend(fc.read_csv(path))

    gap_rows = gap_by_family_size_budget(raw_rows, profiles=[A7_PROFILE, "A6_THOMPSON_SELECTOR_LOCAL_SEARCH", "A0_MAIN_LOCAL_SEARCH"])
    route_fixed_rows = route_fixed_gap_by_family_size_budget(decomposition_rows)
    trace_rows = selector_trace_failure_summary(profile_rows)
    decision = build_decision(metadata=metadata, gap_rows=gap_rows, route_fixed_rows=route_fixed_rows, missing=[], protected_diff=protected)

    fc.write_csv(output_dir / "gap_by_family_size_budget.csv", gap_rows)
    fc.write_csv(output_dir / "route_fixed_gap_by_family_size_budget.csv", route_fixed_rows)
    fc.write_csv(output_dir / "selector_trace_failure_summary.csv", trace_rows)
    fc.write_json(output_dir / "decision.json", decision)
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision, gap_rows, route_fixed_rows), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    (output_dir / "report.md").write_text(write_diagnosis(decision, gap_rows, route_fixed_rows), encoding="utf-8")
    write_hashes(output_dir)
    log_event(logs, "complete", verdict=decision["verdict"], rows=len(gap_rows))
    print(json.dumps({"phase": "selector_sprint_failure_analysis_complete", "verdict": decision["verdict"]}, ensure_ascii=False))
    return 0 if not decision["halt"] else 2


def build_metadata(a5_dir: Path, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-selector-sprint-failure-analysis-metadata.v1",
        "task": "selector_sprint_failure_analysis",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": fc.git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "a5_dir": fc.rel(a5_dir),
        "output_dir": fc.rel(output_dir),
        "protected_paths": list(PROTECTED_PATHS),
        "started_at_epoch": time.time(),
    }


def missing_inputs(a5_dir: Path) -> list[str]:
    required = [
        a5_dir / "decision.json",
        a5_dir / "raw_runs.csv",
        a5_dir / "raw_runs_16000.csv",
        a5_dir / "profile_summary_16000.csv",
        a5_dir / "route_fixed_cost_decomposition_by_budget.csv",
    ]
    return [fc.rel(path) for path in required if not path.exists()]


def gap_by_family_size_budget(raw_rows: list[dict[str, Any]], *, profiles: list[str]) -> list[dict[str, Any]]:
    lns_by_key = {
        (str(row.get("budget")), str(row.get("category")), str(row.get("instance")), str(row.get("seed"))): as_float(row.get("best_cost"))
        for row in raw_rows
        if row.get("profile") == LNS_PROFILE and row.get("status") == "OK"
    }
    buckets: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    for row in raw_rows:
        profile = str(row.get("profile", ""))
        if profile not in set(profiles) or row.get("status") != "OK":
            continue
        budget = str(row.get("budget"))
        category = str(row.get("category"))
        instance = str(row.get("instance"))
        family, size = parse_family_size(category, instance)
        lns = lns_by_key.get((budget, category, instance, str(row.get("seed"))))
        best = as_float(row.get("best_cost"))
        if lns and math.isfinite(lns) and math.isfinite(best):
            buckets[(budget, profile, family, size)].append((lns - best) / lns)
    out = []
    for (budget, profile, family, size), gaps in sorted(buckets.items()):
        out.append(
            {
                "budget": budget,
                "profile": profile,
                "family": family,
                "size": size,
                "rows": len(gaps),
                "mean_gap_vs_lns": mean(gaps),
                "loss_rows": sum(1 for gap in gaps if gap < -1e-12),
                "win_rows": sum(1 for gap in gaps if gap > 1e-12),
            }
        )
    return out


def route_fixed_gap_by_family_size_budget(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str], dict[str, list[float]]] = defaultdict(lambda: {"route": [], "fix": []})
    for row in rows:
        profile = str(row.get("profile", ""))
        if profile not in {A7_PROFILE, "A6_THOMPSON_SELECTOR_LOCAL_SEARCH", "A0_MAIN_LOCAL_SEARCH"}:
            continue
        family, size = parse_family_size(str(row.get("category", "")), str(row.get("instance", "")))
        key = (str(row.get("budget")), profile, family, size)
        route_delta = as_float(row.get("route_count_delta_vs_lns"))
        fix_delta = as_float(row.get("cost_fix_delta_vs_lns"))
        if math.isfinite(route_delta):
            buckets[key]["route"].append(route_delta)
        if math.isfinite(fix_delta):
            buckets[key]["fix"].append(fix_delta)
    out = []
    for (budget, profile, family, size), values in sorted(buckets.items()):
        out.append(
            {
                "budget": budget,
                "profile": profile,
                "family": family,
                "size": size,
                "rows": max(len(values["route"]), len(values["fix"])),
                "mean_route_count_delta_vs_lns": mean(values["route"]) if values["route"] else "UNKNOWN",
                "mean_cost_fix_delta_vs_lns": mean(values["fix"]) if values["fix"] else "UNKNOWN",
                "route_positive_rows": sum(1 for value in values["route"] if value > 1e-12),
                "cost_fix_positive_rows": sum(1 for value in values["fix"] if value > 1e-12),
            }
        )
    return out


def selector_trace_failure_summary(profile_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in profile_rows:
        out.append(
            {
                "budget": row.get("budget", ""),
                "profile": row.get("profile", ""),
                "mean_gap_vs_lns": row.get("mean_gap_vs_lns", ""),
                "mean_route_count": row.get("mean_route_count", ""),
                "mean_cost_fix": row.get("mean_cost_fix", ""),
                "normalized_pair_entropy": row.get("normalized_pair_entropy", ""),
                "top1_pair_share": row.get("top1_pair_share", ""),
                "top2_pair_share": row.get("top2_pair_share", ""),
                "best_improved_rate": row.get("best_improved_rate", ""),
            }
        )
    return out


def build_decision(
    *,
    metadata: dict[str, Any],
    gap_rows: list[dict[str, Any]],
    route_fixed_rows: list[dict[str, Any]],
    missing: list[str],
    protected_diff: str,
) -> dict[str, Any]:
    if missing or protected_diff:
        return {
            "schema": "setp-e2-selector-sprint-failure-analysis-decision.v1",
            "verdict": "HALT_SELECTOR_SPRINT_FAILURE_ANALYSIS",
            "halt": True,
            "diagnostic_only": True,
            "formal_t3": False,
            "algorithm_win_loss_claim": False,
            "missing_inputs": list(missing),
            "protected_diff": protected_diff,
            "metadata_head": metadata.get("head", ""),
        }
    a7_gap_16000 = [
        row
        for row in gap_rows
        if str(row.get("budget")) == "16000" and row.get("profile") == A7_PROFILE and as_float(row.get("mean_gap_vs_lns")) < -1e-12
    ]
    a7_rf_16000 = [
        row
        for row in route_fixed_rows
        if str(row.get("budget")) == "16000" and row.get("profile") == A7_PROFILE
    ]
    positive_route_fix_rows = [
        row
        for row in a7_rf_16000
        if as_float(row.get("mean_route_count_delta_vs_lns")) > 1e-12 and as_float(row.get("mean_cost_fix_delta_vs_lns")) > 1e-12
    ]
    supported = bool(a7_gap_16000) and bool(positive_route_fix_rows)
    return {
        "schema": "setp-e2-selector-sprint-failure-analysis-decision.v1",
        "verdict": "STRUCTURAL_RESCUE_PRECHECK_SUPPORTED" if supported else "STRUCTURAL_RESCUE_PRECHECK_NOT_SUPPORTED",
        "halt": False,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "a7_16000_loss_strata": len(a7_gap_16000),
        "a7_16000_route_fixed_positive_strata": len(positive_route_fix_rows),
        "route_fixed_residual_supported": bool(positive_route_fix_rows),
        "scale_or_family_pattern_supported": bool(a7_gap_16000),
        "metadata_head": metadata.get("head", ""),
    }


def parse_family_size(category: str, instance: str) -> tuple[str, str]:
    parts = str(instance).split("-")
    size = next((part for part in parts if part.endswith("c") and part[:-1].isdigit()), "UNKNOWN")
    family = str(category) if category else (parts[1] if len(parts) > 1 else "UNKNOWN")
    return family, size


def write_empty_outputs(output_dir: Path) -> None:
    fc.write_csv(output_dir / "gap_by_family_size_budget.csv", [])
    fc.write_csv(output_dir / "route_fixed_gap_by_family_size_budget.csv", [])
    fc.write_csv(output_dir / "selector_trace_failure_summary.csv", [])


def write_diagnosis(decision: dict[str, Any], gap_rows: list[dict[str, Any]], route_fixed_rows: list[dict[str, Any]]) -> str:
    verdict = decision.get("verdict", "UNKNOWN")
    return (
        f"# Selector Sprint Failure Analysis\n\n"
        f"Verdict: `{verdict}`.\n\n"
        f"This is diagnostic only, not formal T3. It checks whether A7 16000 residual loss is aligned with route_count / cost_fix and family/scale strata.\n\n"
        f"Gap strata rows: {len(gap_rows)}.\n"
        f"Route/fixed strata rows: {len(route_fixed_rows)}.\n"
    )


def write_next_action(decision: dict[str, Any]) -> str:
    if decision.get("verdict") == "STRUCTURAL_RESCUE_PRECHECK_SUPPORTED":
        return (
            "# Next Action\n\n"
            "Proceed to single-variable structural rescue probes A8/A9/A10. Keep diagnostic-only gates and do not run Tier1 automatically.\n"
        )
    if str(decision.get("verdict", "")).startswith("HALT_"):
        return "# Next Action\n\nStop. Resolve the HALT reason before any structural implementation.\n"
    return "# Next Action\n\nStop structural rescue. The A7 residual was not proven route/fixed dominated by this audit.\n"


def protected_diff() -> str:
    cmd = ["git", "diff", "--", *PROTECTED_PATHS]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def write_hashes(output_dir: Path) -> None:
    files: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(output_dir).as_posix()
        if path.name in HASH_EXCLUDE_NAMES or path.name.startswith("._"):
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in path.parts):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[rel] = digest
    fc.write_json(
        output_dir / "artifact_hashes.json",
        {
            "schema": "setp-e2-selector-sprint-failure-analysis-hashes.v1",
            "files": files,
        },
    )


def log_event(log_path: Path, event: str, **payload: Any) -> None:
    row = {"time": time.time(), "event": event, **payload}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def as_float(value: Any) -> float:
    try:
        if value in {"", None, "UNKNOWN"}:
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def mean(values: list[float]) -> float:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else math.nan


if __name__ == "__main__":
    raise SystemExit(main())
