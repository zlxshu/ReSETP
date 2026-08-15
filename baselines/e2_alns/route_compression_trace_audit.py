#!/usr/bin/env python3
"""Trace audit for the E2 route-compression probe.

This is a read-only/lightweight diagnostic. It consumes existing probe outputs
and source histories, then writes compact audit tables. It does not run a new
formal experiment and does not change solver semantics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/route_compression_trace_audit_20260705"
PROBE_DIR = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705"
PHASE_D_DIR = REPO_ROOT / "baselines/e2_alns/e2_final_closure_20260703/phase_d_g5_t3_material"
REQUIRED_INPUTS = (
    PROBE_DIR / "decision.json",
    PROBE_DIR / "profile_summary.csv",
    PROBE_DIR / "cost_decomposition.csv",
    PROBE_DIR / "raw_runs.csv",
    PHASE_D_DIR / "raw_runs.csv",
)
REQUIRED_SOURCE_FILES = (
    REPO_ROOT / "solver/src/setp_solver/search/winner_operators.py",
    REPO_ROOT / "solver/src/setp_solver/search/alns_wouda.py",
    REPO_ROOT / "solver/src/setp_solver/search/metaheuristic_baselines.py",
    REPO_ROOT / "solver/src/setp_solver/search/local_search.py",
)
PROTECTED_PATHS = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/feasible_repair.py",
    "docs/paper_submission_final/RETIRED_paper_main.tex",
)
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}
LNS_DISPLAY = "LNS"
ALNS_DISPLAYS = (
    "alns_e2_throughput+LOCAL_SEARCH",
    "alns_e2_throughput+RELAXED_ROUTE_COMPRESSION",
    "alns_e2_throughput+RELAXED_ROUTE_COMPRESSION+LOCAL_SEARCH",
)
PROFILE_BY_DISPLAY = {
    "alns_e2_throughput+LOCAL_SEARCH": "A0_CURRENT",
    "alns_e2_throughput+RELAXED_ROUTE_COMPRESSION": "A1_RELAXED_ROUTE_COMPRESSION",
    "alns_e2_throughput+RELAXED_ROUTE_COMPRESSION+LOCAL_SEARCH": "A2_RELAXED_ROUTE_COMPRESSION_LOCAL_SEARCH",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = fc.repo_path(Path(args.output_dir))
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs = output_dir / "logs/full_run.log"
    logs.parent.mkdir(parents=True, exist_ok=True)

    def log(event: str, **payload: Any) -> None:
        with logs.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": event, "time": time.time(), **payload}, ensure_ascii=False, sort_keys=True) + "\n")

    metadata = build_metadata(output_dir)
    fc.write_json(output_dir / "metadata.json", metadata)
    log("start", head=metadata["head"])

    missing = [fc.rel(path) for path in (*REQUIRED_INPUTS, *REQUIRED_SOURCE_FILES) if not path.exists()]
    if protected_diff():
        missing.append("PROTECTED_DIFF:" + "|".join(protected_diff()))
    if missing:
        decision = {
            "schema": "setp-e2-route-compression-trace-audit-decision.v1",
            "verdict": "HALT_INPUT_OR_PROTECTED_DIFF",
            "missing_or_blocked": missing,
            "diagnostic_only": True,
        }
        write_empty_outputs(output_dir)
        fc.write_json(output_dir / "decision.json", decision)
        write_hashes(output_dir)
        print_status("trace_audit_halt", 0, 0, 0, len(missing), True, "inputs")
        return 2

    decision = fc.read_json(PROBE_DIR / "decision.json")
    profile_rows = fc.read_csv(PROBE_DIR / "profile_summary.csv")
    cost_rows = fc.read_csv(PROBE_DIR / "cost_decomposition.csv")
    raw_rows = fc.read_csv(PROBE_DIR / "raw_runs.csv")
    phase_d_rows = fc.read_csv(PHASE_D_DIR / "raw_runs.csv")
    hard_keys = hard_subset_keys(decision)

    support_rows = support_gate_breakdown(profile_rows)
    alns_rows = alns_operator_contribution(raw_rows, hard_keys)
    lns_rows = lns_best_update_sources(raw_rows, phase_d_rows, hard_keys)
    limits = trace_limitations()
    next_action = choose_next_action(support_rows, alns_rows, lns_rows)
    audit_decision = build_decision(decision, support_rows, alns_rows, lns_rows, next_action)

    fc.write_csv(output_dir / "support_gate_breakdown.csv", support_rows)
    fc.write_csv(output_dir / "alns_operator_contribution.csv", alns_rows)
    fc.write_csv(output_dir / "lns_best_update_sources.csv", lns_rows)
    (output_dir / "trace_limitations.md").write_text(limits, encoding="utf-8")
    (output_dir / "next_action.md").write_text(next_action, encoding="utf-8")
    fc.write_json(output_dir / "decision.json", audit_decision)
    write_hashes(output_dir)
    log("complete", alns_rows=len(alns_rows), lns_rows=len(lns_rows), support_rows=len(support_rows))
    print_status("trace_audit_complete", len(lns_rows), len(lns_rows), len(lns_rows), 0, False, "hard_subset")
    return 0


def build_metadata(output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-route-compression-trace-audit-metadata.v1",
        "task": "route_compression_probe_trace_audit",
        "boundary": "read-only/lightweight diagnostic; no new formal experiment; all unavailable fields reported as UNKNOWN",
        "head": fc.git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "output_dir": fc.rel(output_dir),
        "inputs": [fc.rel(path) for path in REQUIRED_INPUTS],
        "source_files_read": [fc.rel(path) for path in REQUIRED_SOURCE_FILES],
        "protected_paths": list(PROTECTED_PATHS),
        "started_at_epoch": time.time(),
    }


def support_gate_breakdown(profile_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in profile_rows:
        profile = row.get("profile", "")
        if profile not in {"A1_RELAXED_ROUTE_COMPRESSION", "A2_RELAXED_ROUTE_COMPRESSION_LOCAL_SEARCH"}:
            continue
        wins = as_int(row.get("wins_vs_lns"))
        losses = as_int(row.get("losses_vs_lns"))
        gates = {
            "mean_gap_positive": as_float(row.get("mean_gap_vs_lns")) > 0.0,
            "wins_at_least_losses": wins >= losses,
            "route_count_not_higher_than_a0": as_bool(row.get("route_count_not_higher_than_a0")),
            "no_under_eval": as_int(row.get("under_eval_rows")) == 0,
            "no_identity_halt": as_int(row.get("identity_halt_rows")) == 0,
            "no_infeasible": as_int(row.get("infeasible_rows")) == 0,
            "anchor_parity_ok": as_bool(row.get("anchor_parity_ok")),
            "root_cause_route_fixed_supported": as_bool(row.get("root_cause_route_fixed_supported")),
        }
        failed = [name for name, passed in gates.items() if not passed]
        rows.append(
            {
                "profile": profile,
                "mean_gap": as_float(row.get("mean_gap_vs_lns")),
                "wins_vs_lns": wins,
                "losses_vs_lns": losses,
                "ties_vs_lns": as_int(row.get("ties_vs_lns")),
                "route_count_delta_vs_a0": as_float(row.get("mean_route_count_delta_vs_a0")),
                "route_count_delta_vs_lns": as_float(row.get("mean_route_count_delta_vs_lns")),
                "under_eval": as_int(row.get("under_eval_rows")),
                "identity_halt": as_int(row.get("identity_halt_rows")),
                "infeasible": as_int(row.get("infeasible_rows")),
                "anchor_parity": as_bool(row.get("anchor_parity_ok")),
                "eligible_for_support": as_bool(row.get("eligible_for_support")),
                "failed_gates": "|".join(failed) if failed else "",
            }
        )
    return rows


def alns_operator_contribution(raw_rows: list[dict[str, str]], hard_keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in sorted(raw_rows, key=lambda item: (item.get("display_algorithm", ""), item.get("category", ""), item.get("instance", ""), int(float(item.get("seed", 0) or 0)))):
        key = (str(row.get("category")), str(row.get("instance")))
        if key not in hard_keys or row.get("display_algorithm") not in ALNS_DISPLAYS:
            continue
        history = parse_json_list(row.get("history_json"))
        counts = parse_json_dict(row.get("operator_counts_json"))
        scan = counts.get("scan", {}) if isinstance(counts.get("scan"), dict) else {}
        destroy = counts.get("destroy", {}) if isinstance(counts.get("destroy"), dict) else {}
        repair = counts.get("repair", {}) if isinstance(counts.get("repair"), dict) else {}
        timing = counts.get("timing", {}) if isinstance(counts.get("timing"), dict) else {}
        best_updates = [item for item in history if str(item.get("operator", "")) != "shared_warm_start"]
        best_operator_counts: dict[str, int] = {}
        best_operator_route_counts: dict[str, set[str]] = {}
        for item in best_updates:
            operator = str(item.get("operator", "UNKNOWN") or "UNKNOWN")
            best_operator_counts[operator] = best_operator_counts.get(operator, 0) + 1
            route_count = str(item.get("route_count", "UNKNOWN") or "UNKNOWN")
            best_operator_route_counts.setdefault(operator, set()).add(route_count)
        route_elim = list(map_ints(destroy.get("route_elimination_removal", [])))
        local_timing = summarize_timing(timing, "local_search")
        rows.append(
            {
                "category": row.get("category", ""),
                "instance": row.get("instance", ""),
                "seed": as_int(row.get("seed")),
                "profile": PROFILE_BY_DISPLAY.get(str(row.get("display_algorithm")), str(row.get("display_algorithm"))),
                "display_algorithm": row.get("display_algorithm", ""),
                "best_cost": as_float(row.get("best_cost")),
                "route_count": as_int(row.get("route_count")),
                "native_best_updates": as_int(row.get("native_best_updates")),
                "scan_restart_attempts": as_int(scan.get("restart_attempts")),
                "scan_restart_accepts": as_int(scan.get("restart_accepts")),
                "scan_rebuild_attempts": as_int(scan.get("rebuild_attempts")),
                "scan_rebuild_accepts": as_int(scan.get("rebuild_accepts")),
                "scan_infeasible": as_int(scan.get("infeasible")),
                "route_elimination_selected_count": sum(route_elim) if route_elim else 0,
                "route_elimination_best_improve_count": route_elim[0] if len(route_elim) > 0 else 0,
                "route_elimination_objective_improve_count": route_elim[1] if len(route_elim) > 1 else 0,
                "route_elimination_accepted_non_improve_count": route_elim[2] if len(route_elim) > 2 else 0,
                "route_elimination_rejected_or_reverted_count": route_elim[3] if len(route_elim) > 3 else 0,
                "route_elimination_route_count_drop_count": "UNKNOWN",
                "route_elimination_reverted_reason": "UNKNOWN",
                "local_search_call_count": local_timing["count"],
                "local_search_seconds": local_timing["seconds"],
                "local_search_improve_count": "UNKNOWN",
                "local_search_route_count_delta": "UNKNOWN",
                "best_update_operator_distribution": encode_counts(best_operator_counts),
                "best_update_operator_route_counts": encode_route_counts(best_operator_route_counts),
                "history_route_count_available": all("route_count" in item for item in best_updates) if best_updates else False,
                "destroy_operator_counts": encode_operator_counts(destroy),
                "repair_operator_counts": encode_operator_counts(repair),
            }
        )
    return rows


def lns_best_update_sources(
    probe_rows: list[dict[str, str]],
    phase_d_rows: list[dict[str, str]],
    hard_keys: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    indexed: dict[tuple[str, str, int], dict[str, str]] = {}
    for source, rows in (("probe", probe_rows), ("phase_d", phase_d_rows)):
        for row in rows:
            if row.get("display_algorithm") != LNS_DISPLAY:
                continue
            key = (str(row.get("category")), str(row.get("instance")), as_int(row.get("seed")))
            if (key[0], key[1]) not in hard_keys:
                continue
            indexed.setdefault(key, {**row, "_trace_source": source})

    out: list[dict[str, Any]] = []
    for key, row in sorted(indexed.items()):
        history = parse_json_list(row.get("history_json"))
        best_updates = [item for item in history if not item.get("is_reference")]
        for idx, item in enumerate(best_updates):
            operator = str(item.get("operator", "UNKNOWN") or "UNKNOWN")
            out.append(
                {
                    "category": key[0],
                    "instance": key[1],
                    "seed": key[2],
                    "trace_source": row.get("_trace_source", ""),
                    "update_index": idx,
                    "eval": item.get("eval", "UNKNOWN"),
                    "time_seconds": item.get("time_seconds", "UNKNOWN"),
                    "best_cost": item.get("best_cost", "UNKNOWN"),
                    "best_cost_before": item.get("best_cost_before", "UNKNOWN"),
                    "current_cost": item.get("current_cost", "UNKNOWN"),
                    "operator": operator,
                    "channel": item.get("channel", operator_channel(operator)),
                    "operator_family": operator_family(operator),
                    "route_count": item.get("route_count", "UNKNOWN"),
                    "signature": item.get("signature", "UNKNOWN"),
                }
            )
    return out


def trace_limitations() -> str:
    return "\n".join(
        [
            "# Trace Limitations",
            "",
            "This audit uses existing run outputs only. UNKNOWN means the current source history did not record the field; it is not inferred.",
            "",
            "- A0/A1/A2 winner history records eval, time, best_cost, best_obj, operator, and channel, but it does not record route_count for best updates.",
            "- Route-elimination counts expose four outcome buckets, but they do not record candidate route_count delta or exact revert reason.",
            "- LOCAL_SEARCH timing can be counted when timing ledger is enabled, but local_search_improve_count and local_search_route_count_delta are not recorded per candidate.",
            "- LNS history records route_count for best updates, so LNS source attribution is stronger than ALNS winner attribution.",
            "",
            "Minimal diagnostic instrumentation patch:",
            "",
            "1. Extend _winner_history_entry() with route_count and signature, matching baseline _SearchSession.score().",
            "2. Add candidate_route_count, previous_route_count, hard_violation_count, changed, accepted, and revert_reason to a diagnostic-only ALNS trace row.",
            "3. Around improve_solution_locally(), record before/after objective and route_count when SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC=1.",
            "4. Keep instrumentation behind a diagnostic flag and out of formal algorithm semantics.",
            "",
        ]
    )


def choose_next_action(support_rows: list[dict[str, Any]], alns_rows: list[dict[str, Any]], lns_rows: list[dict[str, Any]]) -> str:
    family_counts: dict[str, int] = {}
    for row in lns_rows:
        family = str(row.get("operator_family", "unknown"))
        if family not in {"shared_warm_start", "reference_flip_closure"}:
            family_counts[family] = family_counts.get(family, 0) + 1
    total_lns_updates = sum(family_counts.values()) or 1
    route_elim_selected = sum(as_int(row.get("route_elimination_selected_count")) for row in alns_rows if str(row.get("profile", "")).startswith("A1") or str(row.get("profile", "")).startswith("A2"))
    route_elim_best = sum(as_int(row.get("route_elimination_best_improve_count")) for row in alns_rows if str(row.get("profile", "")).startswith("A1") or str(row.get("profile", "")).startswith("A2"))
    scan_initial_share = family_counts.get("lns_scan_initial", 0) / total_lns_updates
    vehicle_share = family_counts.get("lns_vehicle_type_mutation", 0) / total_lns_updates
    repair_share = family_counts.get("lns_destroy_repair", 0) / total_lns_updates

    lines = [
        "# Next Action",
        "",
        "Boundary: recommendation is based only on existing trace evidence and UNKNOWN fields stay UNKNOWN.",
        "",
        f"LNS best-update family counts: {json.dumps(family_counts, ensure_ascii=False, sort_keys=True)}",
        f"A1/A2 route_elimination_selected_count: {route_elim_selected}",
        f"A1/A2 route_elimination_best_improve_count: {route_elim_best}",
        "",
    ]
    if scan_initial_share >= 0.5:
        lines.append("Recommended next step: compare A0 scan_all_cv_solution / scan restart-rebuild behavior against LNS _angle_scan_order and lns_scan_initial.")
    elif vehicle_share >= 0.35:
        lines.append("Recommended next step: audit EV/CV flip plus charging repair, because LNS best updates are materially coming from lns_vehicle_type_mutation.")
    elif repair_share >= 0.35:
        lines.append("Recommended next step: audit LNS destroy/repair acceptance and scheduler behavior, because lns_*destroy*repair updates dominate.")
    elif route_elim_selected > 0 and route_elim_best == 0:
        lines.append("Recommended next step: audit route selection and repair space for route_elimination_removal; current trace shows selections without best-update evidence.")
    else:
        lines.append("Recommended next step: add minimal diagnostic instrumentation first; existing ALNS trace is too sparse for a source-backed operator change.")
    lines.append("")
    lines.append("Do not recommend oracle/ejection-chain/cross-exchange here; this audit found no source-backed evidence for those designs.")
    lines.append("")
    return "\n".join(lines)


def build_decision(
    probe_decision: dict[str, Any],
    support_rows: list[dict[str, Any]],
    alns_rows: list[dict[str, Any]],
    lns_rows: list[dict[str, Any]],
    next_action: str,
) -> dict[str, Any]:
    lns_families: dict[str, int] = {}
    for row in lns_rows:
        family = str(row.get("operator_family", "unknown"))
        lns_families[family] = lns_families.get(family, 0) + 1
    return {
        "schema": "setp-e2-route-compression-trace-audit-decision.v1",
        "verdict": "TRACE_AUDIT_COMPLETE",
        "diagnostic_only": True,
        "formal_t3": False,
        "probe_verdict": probe_decision.get("verdict"),
        "support_gate_rows": len(support_rows),
        "alns_operator_rows": len(alns_rows),
        "lns_best_update_rows": len(lns_rows),
        "lns_best_update_family_counts": lns_families,
        "protected_diff": protected_diff(),
        "next_action_summary": first_recommended_line(next_action),
    }


def hard_subset_keys(decision: dict[str, Any]) -> set[tuple[str, str]]:
    values = decision.get("current_alns_vs_lns", {}).get("hard_subset_instances", [])
    out: set[tuple[str, str]] = set()
    for value in values:
        category, _, instance = str(value).partition("/")
        if category and instance:
            out.add((category, instance))
    return out


def write_empty_outputs(output_dir: Path) -> None:
    fc.write_csv(output_dir / "support_gate_breakdown.csv", [])
    fc.write_csv(output_dir / "alns_operator_contribution.csv", [])
    fc.write_csv(output_dir / "lns_best_update_sources.csv", [])
    (output_dir / "trace_limitations.md").write_text("", encoding="utf-8")
    (output_dir / "next_action.md").write_text("", encoding="utf-8")


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


def parse_json_list(text: object) -> list[dict[str, Any]]:
    try:
        payload = json.loads(str(text or "[]"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def parse_json_dict(text: object) -> dict[str, Any]:
    try:
        payload = json.loads(str(text or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def summarize_timing(timing: dict[str, Any], needle: str) -> dict[str, Any]:
    count = 0.0
    seconds = 0.0
    for key, value in timing.items():
        if needle not in str(key) or not isinstance(value, dict):
            continue
        count += as_float(value.get("count"))
        seconds += as_float(value.get("seconds"))
    return {"count": int(count), "seconds": seconds}


def operator_channel(operator: str) -> str:
    if operator == "lns_scan_initial":
        return "lns_scan_initial"
    if operator == "lns_vehicle_type_mutation":
        return "lns_vehicle_type_mutation"
    if operator.startswith("lns_"):
        return "lns_destroy_repair"
    return operator


def operator_family(operator: str) -> str:
    if operator == "shared_warm_start":
        return "shared_warm_start"
    if operator == "reference_flip_closure":
        return "reference_flip_closure"
    if operator == "lns_scan_initial":
        return "lns_scan_initial"
    if operator == "lns_vehicle_type_mutation":
        return "lns_vehicle_type_mutation"
    if operator.startswith("lns_"):
        return "lns_destroy_repair"
    return "other"


def first_recommended_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Recommended next step:"):
            return line
    return "UNKNOWN"


def encode_counts(counts: dict[str, int]) -> str:
    return "|".join(f"{key}:{counts[key]}" for key in sorted(counts))


def encode_route_counts(counts: dict[str, set[str]]) -> str:
    return "|".join(f"{key}:{','.join(sorted(values))}" for key, values in sorted(counts.items()))


def encode_operator_counts(counts: dict[str, Any]) -> str:
    pieces = []
    for name in sorted(counts):
        values = ",".join(str(item) for item in map_ints(counts[name]))
        pieces.append(f"{name}:{values}")
    return "|".join(pieces)


def map_ints(values: Any) -> list[int]:
    if not isinstance(values, (list, tuple)):
        return []
    return [as_int(item) for item in values]


def protected_diff() -> list[str]:
    changed: set[str] = set()
    for args in (["git", "diff", "--name-only", "--"], ["git", "diff", "--cached", "--name-only", "--"]):
        result = subprocess.run([*args, *PROTECTED_PATHS], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
        if result.stdout:
            changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(changed)


def print_status(phase: str, rows: int, expected: int, ok: int, fail: int, halt: bool, current: str) -> None:
    print(
        json.dumps(
            {
                "phase": phase,
                "rows": f"{rows}/{expected}",
                "ok": ok,
                "fail": fail,
                "halt": halt,
                "current_instance": current,
                "workers": 0,
                "decision_needed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_float(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def as_int(value: object) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
