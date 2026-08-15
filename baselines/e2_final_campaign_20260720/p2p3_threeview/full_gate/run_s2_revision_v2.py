#!/usr/bin/env python3
"""Close the approved S2 infeasible-unit exception without rerunning data."""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PACKAGE = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
RAW = OUT / "raw_runs.csv"
P3_RAW = PACKAGE / "p3_china81_gate/raw_runs.csv"
P3_RUNNER = PACKAGE / "run_p3_china81_formal.py"
S1_DECISION = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/decision.json"
V1_DECISION = OUT / "decision.json"
V1_REPORT = OUT / "report.md"
V1_METADATA = OUT / "metadata.json"
V1_DONE = OUT / "done.json"
V1_HASHES = OUT / "artifact_hashes.json"
V1_HASH_ARCHIVE = OUT / "artifact_hashes_v1.json"
V2_DECISION = OUT / "decision_v2.json"
V2_REPORT = OUT / "report_v2.md"
V2_METADATA = OUT / "metadata_v2.json"
V2_DONE = OUT / "done_v2.json"
V2_TASK_CARD = OUT / "task_card_v2.md"
V2_SCRIPT = OUT / "run_s2_revision_v2.py"
APPLEDOUBLE_FLAG = "HASH_CONTAMINATED_APPLEDOUBLE"
APPLEDOUBLE_REMOVED_BEFORE_REVISION = 19
EXPECTED_ROWS = 81 * 5 * 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _cleanup_appledouble() -> int:
    removed = 0
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def _assert_source_ledger(rows: list[dict[str, str]]) -> dict[str, Any]:
    original_decision = json.loads(V1_DECISION.read_text(encoding="utf-8"))
    if original_decision.get("decision") != "HALT_S2_VIEW_INFEASIBLE_OR_ERROR":
        raise RuntimeError("v1 decision is not the preserved S2 HALT")
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"raw row count {len(rows)} != {EXPECTED_ROWS}")
    keys = [
        (row["instance_id"], int(row["seed"]), row["route_proxy_mode"])
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        raise RuntimeError("raw ledger has duplicate keys")
    failed = [row for row in rows if row["status"] != "OK"]
    if len(failed) != 1:
        raise RuntimeError(f"expected exactly one non-OK row, got {len(failed)}")
    row = failed[0]
    expected = {
        "instance_id": "cn-jjj-200c-01-V2-LOCATIONS",
        "seed": "2",
        "route_proxy_mode": "naive_ev",
        "status": "ERROR",
    }
    for field, value in expected.items():
        if row.get(field) != value:
            raise RuntimeError(f"unexpected failure field {field}: {row.get(field)!r}")
    error = row.get("error", "")
    if "C099" not in error or "0.388" not in error:
        raise RuntimeError(f"failure is not the registered deterministic C099 case: {error}")
    mode_status = {
        mode: Counter(
            item["status"] for item in rows if item["route_proxy_mode"] == mode
        )
        for mode in ("cv_only", "naive_ev")
    }
    if mode_status["cv_only"] != Counter({"OK": 405}):
        raise RuntimeError(f"unexpected cv_only status counts: {mode_status['cv_only']}")
    if mode_status["naive_ev"] != Counter({"OK": 404, "ERROR": 1}):
        raise RuntimeError(f"unexpected naive_ev status counts: {mode_status['naive_ev']}")
    p3_rows = list(csv.DictReader(P3_RAW.open(encoding="utf-8")))
    p3_keys = {(item["instance_id"], int(item["seed"])) for item in p3_rows}
    if len(p3_rows) != 405 or len(p3_keys) != 405:
        raise RuntimeError("P3 reuse ledger is not the expected 405 unique rows")
    if any(
        not item.get("mother_cost") or not item.get("full_cost")
        for item in p3_rows
    ):
        raise RuntimeError("P3 reuse ledger has missing mother/full cost")
    return {
        "original_decision": original_decision,
        "failed_row": row,
        "mode_status": {
            mode: dict(counts) for mode, counts in mode_status.items()
        },
        "p3_rows": len(p3_rows),
    }


def _hash_paths() -> list[Path]:
    return [
        P3_RUNNER, P3_RAW, S1_DECISION,
        OUT / "task_card.md", V2_TASK_CARD, V2_SCRIPT,
        RAW, OUT / "appendix_a1.csv", OUT / "appendix_a1_numeric.csv",
        V1_DECISION, V1_REPORT, V1_METADATA, V1_DONE, V1_HASH_ARCHIVE,
        V2_DECISION, V2_REPORT, V2_METADATA, V2_DONE,
    ]


def main() -> int:
    if not all(path.is_file() for path in (RAW, V1_DECISION, V1_REPORT, V1_METADATA, V1_DONE, V1_HASHES)):
        raise RuntimeError("missing one or more preserved S2 v1 artifacts")
    rows = list(csv.DictReader(RAW.open(encoding="utf-8")))
    source = _assert_source_ledger(rows)
    if not V1_HASH_ARCHIVE.exists():
        _write_json(
            V1_HASH_ARCHIVE,
            json.loads(V1_HASHES.read_text(encoding="utf-8")),
        )
    failure = source["failed_row"]
    mode_status = source["mode_status"]
    hgs_e_values = [
        float(row["cost"])
        for row in rows
        if row["route_proxy_mode"] == "naive_ev" and row["status"] == "OK"
        and row["instance_id"] == failure["instance_id"]
    ]
    if len(hgs_e_values) != 4:
        raise RuntimeError(f"expected four usable HGS-E values for failed instance, got {len(hgs_e_values)}")
    integrity_flags = [APPLEDOUBLE_FLAG]
    decision = {
        "schema_version": "resetp.e2-final-campaign.s2-full-threeview-v2.v1",
        "decision": "PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT",
        "source_decision_v1": "decision.json",
        "source_report_v1": "report.md",
        "approval_register_id": "S2-INFEASIBLE-UNIT-001",
        "expected_new_rows": EXPECTED_ROWS,
        "observed_new_rows": len(rows),
        "ok_rows": sum(row["status"] == "OK" for row in rows),
        "infeasible_rows": 1,
        "violation_rows": 0,
        "duplicate_new_key_count": 0,
        "status_counts_by_route_proxy_mode": mode_status,
        "feasibility_counts": {
            "HGS-F": {"feasible": 405, "total": 405},
            "HGS-E": {"feasible": 404, "total": 405},
            "HGS-M": {"feasible": 405, "total": 405, "source": "P3 read-only reuse"},
            "MV-HGS-SP": {"feasible": 405, "total": 405, "source": "P3 read-only reuse"},
        },
        "p3_reuse_rows": source["p3_rows"],
        "infeasible_unit": {
            "instance_id": failure["instance_id"],
            "seed": int(failure["seed"]),
            "arm": "HGS-E",
            "route_proxy_mode": failure["route_proxy_mode"],
            "raw_status": failure["status"],
            "classification": "INFEASIBLE",
            "error": failure["error"],
            "deterministic": True,
            "rerun": False,
        },
        "statistical_rule": {
            "instance": failure["instance_id"],
            "arm": "HGS-E",
            "usable_seed_count_for_best_avg": len(hgs_e_values),
            "best": min(hgs_e_values),
            "avg": sum(hgs_e_values) / len(hgs_e_values),
            "table_note": "HGS-E在1个算例的1个种子上无完整模型可行解（简化代理时间窗误差）",
        },
        "s3_policy": {
            "same_registered_exception_applies": True,
            "continue_with_explicit_infeasible_rows": True,
            "halt_if_any_single_arm_failure_rate_exceeds": 0.05,
        },
        "integrity_flags": integrity_flags,
        "claim_boundary": "S2 v2 is descriptive evidence only. It does not authorize superiority, equal-compute, evaluator, route-proxy, or model-contract claims.",
    }
    _write_json(V2_DECISION, decision)
    report = f"""# S2 Full three-view China81 gate — v2 registered exception

Decision: PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT.

## Preserved v1 evidence

The original decision.json remains HALT_S2_VIEW_INFEASIBLE_OR_ERROR, and the original report.md and raw_runs.csv were not rewritten. This v2 file is a separate statistical closeout under approval-register entry S2-INFEASIBLE-UNIT-001.

## Ledger

All {len(rows)}/{EXPECTED_ROWS} new rows are present. There are 809 OK rows and one raw ERROR row classified as INFEASIBLE; there are zero duplicate keys and zero violation rows. HGS-F/cv_only is 405/405, HGS-E/naive_ev is 404/405, and the P3 read-only reuse ledger supplies HGS-M/mechanism_ev 405/405 and MV-HGS-SP 405/405.

The deterministic exception is {failure['instance_id']}, seed {failure['seed']}, HGS-E/naive_ev. The exact completion failed because C099 was late by 0.388 seconds (due l=49305.189, start=49305.576). No rerun, seed replacement, time-window relaxation, completioner change, or evaluator change was performed.

## Statistical rule

For this instance only, HGS-E Best/avg use the four feasible seeds: Best={min(hgs_e_values):.9f}, Avg={sum(hgs_e_values) / len(hgs_e_values):.9f}. The table note is: “HGS-E在1个算例的1个种子上无完整模型可行解（简化代理时间窗误差）”. The failed raw row remains in the ledger and the 404/405 feasibility rate is reported.

This case is retained as empirical evidence for why every candidate must be judged by the complete model: a simplified electric proxy can produce a route that fails the exact time-window referee by a small but decisive margin, while the complete MV-HGS-SP unit is feasible.

## Chain rule

S3 and later stages use this v2 decision. The same registered exception is recorded rather than filtered; a stage stops only if its single-arm failure rate exceeds 5 percent or another registered quality gate fails.

AppleDouble sidecars were observed and removed before this v2 hash refresh; the integrity flag is HASH_CONTAMINATED_APPLEDOUBLE. Raw data were not overwritten.
"""
    V2_REPORT.write_text(report, encoding="utf-8")
    metadata = {
        "schema_version": "resetp.e2-final-campaign.s2-full-threeview-v2-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([sys.executable, *sys.argv]),
        "git_head": _git_head(),
        "branch": "codex/reporting-pipeline",
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "approval_register_id": "S2-INFEASIBLE-UNIT-001",
        "source_metadata": "metadata.json",
        "source_metadata_sha256": _sha256(V1_METADATA),
        "source_decision_sha256": _sha256(V1_DECISION),
        "source_report_sha256": _sha256(V1_REPORT),
        "source_raw_runs_sha256": _sha256(RAW),
        "p3_raw_runs_sha256": _sha256(P3_RAW),
        "protected_file_sha256": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (
                ROOT / "solver/src/setp_solver/cost.py",
                ROOT / "solver/src/setp_solver/check.py",
                ROOT / "solver/src/setp_solver/search/evaluation.py",
                ROOT / "solver/src/setp_solver/prices.py",
                ROOT / "docs/paper_submission_final/RETIRED_paper_main.tex",
                P3_RUNNER,
                P3_RAW,
            )
        },
        "new_rows": EXPECTED_ROWS,
        "ok_rows": 809,
        "infeasible_rows": 1,
        "feasibility_counts": decision["feasibility_counts"],
        "statistical_rule": decision["statistical_rule"],
        "integrity_flags": integrity_flags,
        "appledouble_sidecars_removed_before_revision": APPLEDOUBLE_REMOVED_BEFORE_REVISION,
    }
    _write_json(V2_METADATA, metadata)
    _write_json(
        V2_DONE,
        {
            "decision": decision["decision"],
            "raw_rows": len(rows),
            "v1_decision": source["original_decision"]["decision"],
            "artifact_hashes": "artifact_hashes.json",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    _cleanup_appledouble()
    hash_paths = [
        path for path in _hash_paths()
        if path.exists()
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]
    _write_json(
        V1_HASHES,
        {
            "schema_version": "resetp.artifact-hashes.v2",
            "algorithm": "sha256",
            "appledouble_excluded": True,
            "integrity_flags": integrity_flags,
            "source_v1_hashes": "artifact_hashes_v1.json",
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in hash_paths
                if path.exists() and not path.name.startswith("._")
            },
        },
    )
    print(
        f"[S2-REV-V2] {decision['decision']} rows={len(rows)} "
        f"ok={decision['ok_rows']} infeasible={decision['infeasible_rows']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
