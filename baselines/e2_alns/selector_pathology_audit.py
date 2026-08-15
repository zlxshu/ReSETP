#!/usr/bin/env python3
"""Read-only audit for ALNS operator-selector pathology.

This diagnostic consumes existing A3 profile-alignment and LNS trace outputs.
It does not run a new algorithm experiment and does not change solver behavior.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as fc


DEFAULT_A3_DIR = REPO_ROOT / "baselines/e2_alns/strong_bridge_backend_probe_local_search_check_20260706"
DEFAULT_LNS_DIR = REPO_ROOT / "baselines/e2_alns/lns_acceptance_scheduler_audit_20260705"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/selector_pathology_audit_20260706"
ALNS_PROFILES = ("A0_MAIN_LOCAL_SEARCH", "A3_BACKEND_LOCAL_SEARCH")
LNS_PROFILE = "LNS_STRONG_BRIDGE"
PROTECTED_PATHS = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/feasible_repair.py",
    "docs/paper_submission_final/RETIRED_paper_main.tex",
)
REQUIRED_SOURCE_FILES = (
    REPO_ROOT / "solver/src/setp_solver/search/resetp_alns/select.py",
    REPO_ROOT / "solver/src/setp_solver/search/alns_wouda.py",
    REPO_ROOT / "solver/src/setp_solver/search/winner_operators.py",
)
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a3-dir", default=str(DEFAULT_A3_DIR))
    parser.add_argument("--lns-dir", default=str(DEFAULT_LNS_DIR))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    a3_dir = fc.repo_path(Path(args.a3_dir))
    lns_dir = fc.repo_path(Path(args.lns_dir))
    output_dir = fc.repo_path(Path(args.output_dir))
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs = output_dir / "logs/full_run.log"
    logs.parent.mkdir(parents=True, exist_ok=True)
    log_event(logs, "start", a3_dir=fc.rel(a3_dir), lns_dir=fc.rel(lns_dir))

    metadata = build_metadata(a3_dir, lns_dir, output_dir)
    fc.write_json(output_dir / "metadata.json", metadata)

    missing = missing_inputs(a3_dir, lns_dir)
    protected = protected_diff()
    if missing or protected:
        write_empty_outputs(output_dir)
        decision = build_decision(
            metadata=metadata,
            entropy_rows=[],
            usage_rows=[],
            value_bounds=[],
            protected=protected,
            missing=missing,
        )
        fc.write_json(output_dir / "decision.json", decision)
        write_hashes(output_dir)
        log_event(logs, "halt", missing=missing, protected=protected)
        return 2

    alns_trace = fc.read_csv(a3_dir / "alns_candidate_trace.csv")
    lns_trace = fc.read_csv(lns_dir / "lns_scheduler_trace.csv")
    raw_runs = fc.read_csv(a3_dir / "raw_runs.csv")

    usage_rows = selector_pair_usage([row for row in alns_trace if row.get("profile") in ALNS_PROFILES])
    expected_counts = expected_pair_counts(usage_rows)
    entropy_rows = selector_entropy_by_profile(usage_rows, expected_pair_count_by_profile=expected_counts)
    lns_usage = lns_strong_bridge_pair_usage(lns_trace)
    lns_entropy = selector_entropy_by_profile(
        lns_usage,
        expected_pair_count_by_profile={LNS_PROFILE: max(1, len({row["pair"] for row in lns_usage}))},
    )
    entropy_rows.extend(lns_entropy)
    distribution_rows = lns_vs_alns_pair_distribution(usage_rows, lns_usage)
    value_bounds = selector_value_bounds()
    concentration_rows = pair_concentration_vs_gap(alns_trace, raw_runs)
    decision = build_decision(
        metadata=metadata,
        entropy_rows=entropy_rows,
        usage_rows=usage_rows,
        value_bounds=value_bounds,
        protected=protected,
        missing=missing,
    )

    fc.write_csv(output_dir / "selector_pair_usage.csv", usage_rows)
    fc.write_csv(output_dir / "selector_entropy_by_profile.csv", entropy_rows)
    fc.write_csv(output_dir / "lns_vs_alns_pair_distribution.csv", distribution_rows)
    (output_dir / "selector_value_bound.md").write_text(write_selector_value_bound(value_bounds), encoding="utf-8")
    fc.write_csv(output_dir / "pair_concentration_vs_gap.csv", concentration_rows)
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision, entropy_rows, usage_rows, value_bounds), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    fc.write_json(output_dir / "decision.json", decision)
    write_hashes(output_dir)
    log_event(
        logs,
        "complete",
        verdict=decision["verdict"],
        pair_usage_rows=len(usage_rows),
        concentration_rows=len(concentration_rows),
    )
    print(json.dumps({"phase": "selector_pathology_audit_complete", "verdict": decision["verdict"]}, ensure_ascii=False))
    return 0 if not decision["halt"] else 2


def build_metadata(a3_dir: Path, lns_dir: Path, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-selector-pathology-audit-metadata.v1",
        "task": "selector_pathology_audit",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": fc.git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "a3_dir": fc.rel(a3_dir),
        "lns_dir": fc.rel(lns_dir),
        "output_dir": fc.rel(output_dir),
        "source_files_read": [fc.rel(path) for path in REQUIRED_SOURCE_FILES],
        "protected_paths": list(PROTECTED_PATHS),
        "selector_under_audit": "AlphaUCB([20.0, 8.0, 2.0, 0.05], alpha=0.08) with deterministic argmax",
        "started_at_epoch": time.time(),
    }


def missing_inputs(a3_dir: Path, lns_dir: Path) -> list[str]:
    required = [
        a3_dir / "decision.json",
        a3_dir / "profile_summary.csv",
        a3_dir / "raw_runs.csv",
        a3_dir / "alns_candidate_trace.csv",
        lns_dir / "lns_scheduler_trace.csv",
        lns_dir / "lns_path_contribution_summary.csv",
        *REQUIRED_SOURCE_FILES,
    ]
    return [fc.rel(path) for path in required if not path.exists()]


def selector_pair_usage(trace_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    route_deltas: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in trace_rows:
        profile = str(row.get("profile", "UNKNOWN") or "UNKNOWN")
        destroy = str(row.get("destroy_id", "UNKNOWN") or "UNKNOWN")
        repair = str(row.get("repair_id", "UNKNOWN") or "UNKNOWN")
        key = (profile, destroy, repair)
        bucket = buckets.setdefault(
            key,
            {
                "profile": profile,
                "destroy_id": destroy,
                "repair_id": repair,
                "pair": f"{destroy}+{repair}",
                "attempts": 0,
                "accepted_count": 0,
                "best_improved_count": 0,
                "unchanged_count": 0,
            },
        )
        bucket["attempts"] += 1
        if truthy(row.get("accepted")):
            bucket["accepted_count"] += 1
        if truthy(row.get("best_improved")):
            bucket["best_improved_count"] += 1
        if str(row.get("revert_reason")) == "unchanged":
            bucket["unchanged_count"] += 1
        delta = as_float(row.get("candidate_route_count_delta"))
        if math.isfinite(delta):
            route_deltas[key].append(delta)

    rows = []
    for key, bucket in buckets.items():
        attempts = int(bucket["attempts"])
        deltas = route_deltas.get(key, [])
        row = {
            **bucket,
            "accepted_rate": rate_count(bucket["accepted_count"], attempts),
            "best_improved_rate": rate_count(bucket["best_improved_count"], attempts),
            "unchanged_rate": rate_count(bucket["unchanged_count"], attempts),
            "mean_candidate_route_count_delta": mean(deltas) if deltas else "UNKNOWN",
        }
        rows.append(row)
    mark_best_improved_top_members(rows, top_n=3)
    return sorted(rows, key=lambda row: (str(row["profile"]), -as_int(row["attempts"]), str(row["pair"])))


def mark_best_improved_top_members(rows: list[dict[str, Any]], *, top_n: int) -> None:
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_profile[str(row.get("profile"))].append(row)
    for items in by_profile.values():
        top = {
            str(row.get("pair"))
            for row in sorted(items, key=lambda item: as_int(item.get("best_improved_count")), reverse=True)[:top_n]
        }
        for row in items:
            row["best_improved_top3_member"] = str(row.get("pair")) in top


def selector_entropy_by_profile(
    usage_rows: list[dict[str, Any]],
    *,
    expected_pair_count_by_profile: dict[str, int] | None = None,
    starvation_share: float = 0.01,
) -> list[dict[str, Any]]:
    expected_pair_count_by_profile = expected_pair_count_by_profile or {}
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in usage_rows:
        by_profile[str(row.get("profile", "UNKNOWN"))].append(row)

    out: list[dict[str, Any]] = []
    for profile, items in sorted(by_profile.items()):
        total = sum(as_int(row.get("attempts")) for row in items)
        counts = sorted((as_int(row.get("attempts")) for row in items), reverse=True)
        best_counts = sorted((as_int(row.get("best_improved_count")) for row in items), reverse=True)
        expected = max(int(expected_pair_count_by_profile.get(profile, len(items))), len(items), 1)
        missing_pairs = max(0, expected - len(items))
        shares = [(count / total) for count in counts if total > 0]
        entropy = -sum(share * math.log(share) for share in shares if share > 0.0)
        normalized = entropy / math.log(expected) if expected > 1 else 0.0
        best_total = sum(best_counts)
        row = {
            "profile": profile,
            "observed_pair_count": len(items),
            "expected_pair_count": expected,
            "total_attempts": total,
            "pair_entropy": entropy,
            "normalized_pair_entropy": normalized,
            "top1_pair_share": top_share(counts, total, 1),
            "top2_pair_share": top_share(counts, total, 2),
            "top3_pair_share": top_share(counts, total, 3),
            "starving_pair_count": missing_pairs + sum(1 for count in counts if total <= 0 or count / total < starvation_share),
            "best_improved_total": best_total,
            "best_improved_top1_share": top_share(best_counts, best_total, 1),
            "best_improved_top3_share": top_share(best_counts, best_total, 3),
        }
        out.append(row)
    return out


def lns_strong_bridge_pair_usage(lns_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in lns_rows:
        if str(row.get("trace_path")) != "strong_bridge":
            continue
        destroy = str(row.get("destroy", "UNKNOWN") or "UNKNOWN")
        repair = str(row.get("repair", "UNKNOWN") or "UNKNOWN")
        key = (destroy, repair)
        bucket = buckets.setdefault(
            key,
            {
                "profile": LNS_PROFILE,
                "destroy_id": destroy,
                "repair_id": repair,
                "pair": f"{destroy}+{repair}",
                "attempts": 0,
                "accepted_count": 0,
                "best_improved_count": 0,
                "unchanged_count": 0,
                "mean_candidate_route_count_delta": "UNKNOWN",
            },
        )
        bucket["attempts"] += 1
        if truthy(row.get("accepted")):
            bucket["accepted_count"] += 1
        if truthy(row.get("best_improved")):
            bucket["best_improved_count"] += 1
    rows = []
    for bucket in buckets.values():
        attempts = as_int(bucket["attempts"])
        rows.append(
            {
                **bucket,
                "accepted_rate": rate_count(bucket["accepted_count"], attempts),
                "best_improved_rate": rate_count(bucket["best_improved_count"], attempts),
                "unchanged_rate": 0.0,
            }
        )
    mark_best_improved_top_members(rows, top_n=3)
    return sorted(rows, key=lambda row: (-as_int(row["attempts"]), str(row["pair"])))


def lns_vs_alns_pair_distribution(
    alns_usage: list[dict[str, Any]],
    lns_usage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = [*alns_usage, *lns_usage]
    total_by_profile: dict[str, int] = defaultdict(int)
    best_by_profile: dict[str, int] = defaultdict(int)
    for row in rows:
        profile = str(row.get("profile"))
        total_by_profile[profile] += as_int(row.get("attempts"))
        best_by_profile[profile] += as_int(row.get("best_improved_count"))
    out = []
    for row in rows:
        profile = str(row.get("profile"))
        attempts = as_int(row.get("attempts"))
        best = as_int(row.get("best_improved_count"))
        out.append(
            {
                "profile": profile,
                "pair": row.get("pair", ""),
                "destroy_id": row.get("destroy_id", ""),
                "repair_id": row.get("repair_id", ""),
                "attempts": attempts,
                "attempt_share": rate_count(attempts, total_by_profile[profile]),
                "best_improved_count": best,
                "best_improved_share": rate_count(best, best_by_profile[profile]),
            }
        )
    return sorted(out, key=lambda row: (str(row["profile"]), -as_float(row["attempt_share"]), str(row["pair"])))


def selector_value_bounds(
    *,
    iterations: Iterable[int] = (100, 1000, 4000, 16000),
    alpha: float = 0.08,
    initial_average_reward: float = 1.0,
) -> list[dict[str, Any]]:
    rows = []
    for iteration in iterations:
        bonus = math.sqrt(alpha * math.log(1 + int(iteration)))
        untried = initial_average_reward + bonus
        rows.append(
            {
                "iteration": int(iteration),
                "alpha": float(alpha),
                "initial_average_reward": float(initial_average_reward),
                "untried_exploration_bonus": bonus,
                "untried_pair_value": untried,
                "reward8_pair_value": 8.0,
                "reward20_pair_value": 20.0,
                "reward8_dominates_untried": 8.0 > untried,
                "reward20_dominates_untried": 20.0 > untried,
            }
        )
    return rows


def pair_concentration_vs_gap(
    alns_trace_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lns_costs = {
        (str(row.get("category")), str(row.get("instance")), as_int(row.get("seed"))): as_float(row.get("best_cost"))
        for row in raw_rows
        if row.get("profile") == "LNS_TRACE_REFERENCE" and str(row.get("status")) == "OK"
    }
    alns_costs = {
        (str(row.get("category")), str(row.get("instance")), as_int(row.get("seed")), str(row.get("profile"))): as_float(row.get("best_cost"))
        for row in raw_rows
        if row.get("profile") in ALNS_PROFILES and str(row.get("status")) == "OK"
    }
    by_run: dict[tuple[str, str, int, str], Counter[str]] = defaultdict(Counter)
    best_by_run: dict[tuple[str, str, int, str], int] = defaultdict(int)
    for row in alns_trace_rows:
        profile = str(row.get("profile"))
        if profile not in ALNS_PROFILES:
            continue
        key = (str(row.get("category")), str(row.get("instance")), as_int(row.get("seed")), profile)
        pair = f"{row.get('destroy_id')}+{row.get('repair_id')}"
        by_run[key][pair] += 1
        if truthy(row.get("best_improved")):
            best_by_run[key] += 1

    out = []
    for key, counter in sorted(by_run.items()):
        category, instance, seed, profile = key
        total = sum(counter.values())
        counts = sorted(counter.values(), reverse=True)
        lns_cost = lns_costs.get((category, instance, seed), math.nan)
        best_cost = alns_costs.get(key, math.nan)
        gap = (lns_cost - best_cost) / lns_cost if math.isfinite(lns_cost) and lns_cost else math.nan
        out.append(
            {
                "category": category,
                "instance": instance,
                "seed": seed,
                "profile": profile,
                "total_attempts": total,
                "top1_pair_share": top_share(counts, total, 1),
                "top2_pair_share": top_share(counts, total, 2),
                "top3_pair_share": top_share(counts, total, 3),
                "best_improved_count": best_by_run.get(key, 0),
                "best_improved_rate": rate_count(best_by_run.get(key, 0), total),
                "final_gap_vs_lns": gap if math.isfinite(gap) else "UNKNOWN",
                "outcome_vs_lns": outcome_from_gap(gap),
            }
        )
    return out


def build_decision(
    *,
    metadata: dict[str, Any],
    entropy_rows: list[dict[str, Any]],
    usage_rows: list[dict[str, Any]],
    value_bounds: list[dict[str, Any]],
    protected: list[str],
    missing: list[str],
) -> dict[str, Any]:
    entropy = {str(row.get("profile")): row for row in entropy_rows}
    if protected or missing:
        return {
            "schema": "setp-e2-selector-pathology-audit-decision.v1",
            "verdict": "HALT_SELECTOR_PATHOLOGY_AUDIT",
            "diagnostic_only": True,
            "formal_t3": False,
            "algorithm_win_loss_claim": False,
            "head": metadata.get("head", ""),
            "halt": True,
            "protected_diff": protected,
            "missing": missing,
        }

    lns = entropy.get(LNS_PROFILE, {})
    a0 = entropy.get("A0_MAIN_LOCAL_SEARCH", {})
    a3 = entropy.get("A3_BACKEND_LOCAL_SEARCH", {})
    entropy_supported = (
        as_float(a0.get("normalized_pair_entropy")) <= as_float(lns.get("normalized_pair_entropy")) - 0.20
        and as_float(a3.get("normalized_pair_entropy")) <= as_float(lns.get("normalized_pair_entropy")) - 0.20
    )
    top_share_supported = (
        as_float(a0.get("top1_pair_share")) >= as_float(lns.get("top1_pair_share")) + 0.20
        and as_float(a3.get("top1_pair_share")) >= as_float(lns.get("top1_pair_share")) + 0.20
        and as_float(a0.get("top2_pair_share")) >= as_float(lns.get("top2_pair_share")) + 0.25
        and as_float(a3.get("top2_pair_share")) >= as_float(lns.get("top2_pair_share")) + 0.25
    )
    concentration_supported = best_improved_concentration_supported(usage_rows)
    value_bound_supported = bool(value_bounds) and all(bool(row.get("reward8_dominates_untried")) and bool(row.get("reward20_dominates_untried")) for row in value_bounds)
    supported = entropy_supported and top_share_supported and concentration_supported and value_bound_supported
    return {
        "schema": "setp-e2-selector-pathology-audit-decision.v1",
        "verdict": "SELECTOR_PATHOLOGY_SUPPORTED" if supported else "SELECTOR_PATHOLOGY_NOT_SUPPORTED",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "halt": False,
        "protected_diff": protected,
        "missing": missing,
        "support_gates": {
            "entropy_lower_than_lns": entropy_supported,
            "top_pair_share_higher_than_lns": top_share_supported,
            "a3_best_improved_concentrated": concentration_supported,
            "value_bound_exploration_too_small": value_bound_supported,
        },
        "entropy_by_profile": entropy_rows,
    }


def best_improved_concentration_supported(usage_rows: list[dict[str, Any]]) -> bool:
    shares: dict[str, float] = {}
    totals: dict[str, int] = defaultdict(int)
    top: dict[str, int] = defaultdict(int)
    for row in usage_rows:
        profile = str(row.get("profile"))
        count = as_int(row.get("best_improved_count"))
        totals[profile] += count
        if truthy(row.get("best_improved_top3_member")):
            top[profile] += count
    for profile, total in totals.items():
        shares[profile] = rate_count(top[profile], total)
    a0 = shares.get("A0_MAIN_LOCAL_SEARCH", 0.0)
    a3 = shares.get("A3_BACKEND_LOCAL_SEARCH", 0.0)
    return a3 >= 0.75 and a3 >= a0 - 0.05


def write_selector_value_bound(value_bounds: list[dict[str, Any]]) -> str:
    lines = [
        "# Selector Value Bound",
        "",
        "Static audit for `AlphaUCB([20.0, 8.0, 2.0, 0.05], alpha=0.08)` with initial average reward 1.",
        "",
        "| iteration | untried bonus | untried value | reward=8 dominates | reward=20 dominates |",
        "|---:|---:|---:|:---:|:---:|",
    ]
    for row in value_bounds:
        lines.append(
            f"| {row['iteration']} | {as_float(row['untried_exploration_bonus']):.6f} | "
            f"{as_float(row['untried_pair_value']):.6f} | {row['reward8_dominates_untried']} | "
            f"{row['reward20_dominates_untried']} |"
        )
    lines.extend(
        [
            "",
            "Interpretation: because the untried pair value remains far below reward 8 and reward 20, early high-reward pairs can dominate deterministic argmax selection.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_diagnosis(
    decision: dict[str, Any],
    entropy_rows: list[dict[str, Any]],
    usage_rows: list[dict[str, Any]],
    value_bounds: list[dict[str, Any]],
) -> str:
    gates = decision.get("support_gates", {})
    lines = [
        "# Selector Pathology Audit Diagnosis",
        "",
        f"Verdict: `{decision.get('verdict')}`.",
        "",
        "This is diagnostic only, not formal T3 and not an algorithm win/loss claim.",
        "",
        "Entropy summary:",
    ]
    for row in entropy_rows:
        lines.append(
            f"- {row.get('profile')}: normalized_entropy={row.get('normalized_pair_entropy')}, "
            f"top1={row.get('top1_pair_share')}, top2={row.get('top2_pair_share')}, "
            f"best_top3={row.get('best_improved_top3_share')}"
        )
    lines.extend(
        [
            "",
            "Support gates:",
            *[f"- {key}: {value}" for key, value in gates.items()],
            "",
            "Selector value bound:",
            *[
                f"- iter {row.get('iteration')}: untried value={row.get('untried_pair_value')}, reward8 dominates={row.get('reward8_dominates_untried')}"
                for row in value_bounds
            ],
            "",
            "If supported, the next action is a single-variable balanced-selector diagnostic. If not supported, stop scheduler changes and audit q-size or acceptance.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_next_action(decision: dict[str, Any]) -> str:
    if decision.get("verdict") == "SELECTOR_PATHOLOGY_SUPPORTED":
        remedy = "implement SETP_ALNS_CRUSH_BALANCED_SELECTOR=1 as a diagnostic-only scheduler probe"
        pass_gate = "A4 improves mean gap vs LNS, wins_vs_A0>=losses_vs_A0, entropy improves, top shares fall, and no HALT rows appear"
        fail_gate = "A4 fails any direction gate; stop scheduler tuning and audit q-size or acceptance"
    elif decision.get("verdict") == "SELECTOR_PATHOLOGY_NOT_SUPPORTED":
        remedy = "do not implement scheduler fix; move to q-size or acceptance source-level audit"
        pass_gate = "next one-variable audit identifies a supported root cause"
        fail_gate = "no supported root cause; stop and report uncertainty"
    else:
        remedy = "fix missing inputs or protected diff before any further diagnostic"
        pass_gate = "all required inputs present and protected diff is empty"
        fail_gate = "resume safety or protected diff cannot be confirmed"
    return "\n".join(
        [
            "# Next Action",
            "",
            "problem_symptom -> A3 best-improved rate increased but corrected main-profile gap worsened",
            "evidence -> see selector_entropy_by_profile.csv, selector_value_bound.md, and decision.json",
            f"minimal_remedy -> {remedy}",
            f"pass_gate -> {pass_gate}",
            f"fail_gate -> {fail_gate}",
            "",
            "Boundary: no Tier1/Tier2/Tier3, no LNS weakening, no STRONG_BRIDGE_BACKEND tuning, no RELAXED_ROUTE_COMPRESSION tuning.",
        ]
    )


def write_empty_outputs(output_dir: Path) -> None:
    fc.write_csv(output_dir / "selector_pair_usage.csv", [])
    fc.write_csv(output_dir / "selector_entropy_by_profile.csv", [])
    fc.write_csv(output_dir / "lns_vs_alns_pair_distribution.csv", [])
    (output_dir / "selector_value_bound.md").write_text("", encoding="utf-8")
    fc.write_csv(output_dir / "pair_concentration_vs_gap.csv", [])
    (output_dir / "diagnosis.md").write_text("", encoding="utf-8")
    (output_dir / "next_action.md").write_text("", encoding="utf-8")


def expected_pair_counts(usage_rows: list[dict[str, Any]]) -> dict[str, int]:
    by_profile: dict[str, set[str]] = defaultdict(set)
    for row in usage_rows:
        by_profile[str(row.get("profile"))].add(str(row.get("pair")))
    max_count = max((len(values) for values in by_profile.values()), default=0)
    return {profile: max(len(values), max_count) for profile, values in by_profile.items()}


def top_share(counts: list[int], total: int, n: int) -> float:
    return rate_count(sum(counts[:n]), total)


def rate_count(part: Any, total: Any) -> float:
    denominator = as_int(total)
    return as_float(part) / denominator if denominator > 0 else 0.0


def mean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return sum(finite) / len(finite) if finite else math.nan


def outcome_from_gap(gap: float) -> str:
    if not math.isfinite(gap):
        return "UNKNOWN"
    if gap > 1e-9:
        return "ALNS_BETTER_THAN_LNS"
    if gap < -1e-9:
        return "ALNS_WORSE_THAN_LNS"
    return "TIE"


def protected_diff() -> list[str]:
    changed: set[str] = set()
    for args in (["git", "diff", "--name-only", "--"], ["git", "diff", "--cached", "--name-only", "--"]):
        result = subprocess.run([*args, *PROTECTED_PATHS], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
        if result.stdout:
            changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(changed)


def write_hashes(output_dir: Path) -> None:
    files: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(output_dir)
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_NAMES:
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in rel.parts):
            continue
        files[str(rel)] = sha256_file(path)
    fc.write_json(
        output_dir / "artifact_hashes.json",
        {
            "schema": "setp-artifact-hashes.v1",
            "root": fc.rel(output_dir),
            "excluded_names": sorted(HASH_EXCLUDE_NAMES),
            "excluded_parts": sorted(HASH_EXCLUDE_PARTS),
            "files": files,
        },
    )


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def as_float(value: object) -> float:
    try:
        if value in (None, "", "UNKNOWN", "N/A"):
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def as_int(value: object) -> int:
    number = as_float(value)
    return int(number) if math.isfinite(number) else 0


def log_event(path: Path, event: str, **payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, "time": time.time(), **payload}, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
