#!/usr/bin/env python3
"""E2-G0 closure evidence hygiene.

This script is intentionally narrow: it removes macOS AppleDouble/cache files
outside ``.git`` and regenerates clean artifact hashes for the evidence
directories referenced by the E2-G0 closure task. It does not run solvers and it
does not modify raw evidence data other than replacing contaminated hash
manifests with clean manifests after preserving the old file.
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
DEFAULT_OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/e2_g0_closure_hygiene_data"
HASH_EXCLUDE_NAMES = {
    ".DS_Store",
    "artifact_hashes.json",
}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}
EVIDENCE_DIRS = [
    REPO_ROOT / "baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data",
    REPO_ROOT / "baselines/e2_alns/e2_g0_same_value_platform_audit_data",
    REPO_ROOT / "baselines/e2_alns/native_channel_autopsy_data",
    REPO_ROOT / "baselines/e2_alns/decoder_fix_validation_data",
    REPO_ROOT / "baselines/e2_alns/bridge_fix_validation_data",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = repo_path(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = build_metadata(args)
    write_json(output_dir / "metadata.json", metadata)
    cleanup_rows = cleanup_repo(dry_run=bool(args.dry_run))
    write_csv(output_dir / "cleanup_manifest.csv", cleanup_rows)
    refresh_rows = refresh_evidence_hashes(dry_run=bool(args.dry_run))
    write_csv(output_dir / "hash_refresh.csv", refresh_rows)
    decision = decide(metadata, cleanup_rows, refresh_rows)
    write_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(render_report(metadata, decision, cleanup_rows, refresh_rows), encoding="utf-8")
    clean_output_appledouble(output_dir)
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir))
    clean_output_appledouble(output_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"] == "C0_HYGIENE_COMPLETE" else 2


def build_metadata(args: argparse.Namespace) -> dict[str, Any]:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8") if (REPO_ROOT / ".gitignore").exists() else ""
    return {
        "schema": "setp-e2-g0-closure-hygiene.v1",
        "task": "E2-G0 Phase A C0 evidence hygiene",
        "head": git_head(),
        "python": sys.executable,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "dry_run": bool(args.dry_run),
        "started_at_epoch": time.time(),
        "gitignore_has_appledouble": "._*" in gitignore,
        "gitignore_has_pycache": "__pycache__/" in gitignore,
        "gitignore_has_pytest_cache": ".pytest_cache/" in gitignore,
        "evidence_dirs": [rel(path) for path in EVIDENCE_DIRS],
        "protected_files": protected_diff(),
    }


def cleanup_repo(*, dry_run: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        rel_text = rel(path)
        if rel_text == ".git" or rel_text.startswith(".git/"):
            if path.name.startswith("._"):
                rows.append({"path": rel_text, "kind": "appledouble_in_git_registered_not_touched", "removed": False})
            continue
        if path.is_dir() and path.name in HASH_EXCLUDE_PARTS:
            rows.append({"path": rel_text, "kind": "cache_dir", "removed": not dry_run})
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
            continue
        if path.is_file() and path.name.startswith("._"):
            rows.append({"path": rel_text, "kind": "appledouble", "removed": not dry_run})
            if not dry_run:
                path.unlink(missing_ok=True)
    return rows


def clean_output_appledouble(output_dir: Path) -> None:
    for path in sorted(output_dir.rglob("._*")):
        if path.is_file():
            path.unlink(missing_ok=True)


def refresh_evidence_hashes(*, dry_run: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for evidence_dir in EVIDENCE_DIRS:
        if not evidence_dir.exists():
            rows.append({"evidence_dir": rel(evidence_dir), "status": "MISSING"})
            continue
        hash_path = evidence_dir / "artifact_hashes.json"
        backup = evidence_dir / "artifact_hashes.contaminated_appledouble_20260702.json"
        old_contaminated = hash_manifest_contaminated(hash_path) or backup.exists()
        backup_path = ""
        if old_contaminated and hash_path.exists():
            backup_path = rel(backup)
            if not dry_run and not backup.exists():
                shutil.copy2(hash_path, backup)
        clean_hashes = artifact_hashes(evidence_dir)
        if not dry_run:
            write_json(hash_path, clean_hashes)
        rows.append(
            {
                "evidence_dir": rel(evidence_dir),
                "status": "REFRESHED",
                "old_hash_contaminated": old_contaminated,
                "old_hash_backup": backup_path,
                "clean_entry_count": len(clean_hashes.get("files", {})),
                "contains_appledouble_after": hash_manifest_contaminated(hash_path) if not dry_run else False,
            }
        )
    return rows


def hash_manifest_contaminated(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
        return "/._" in text or '"._' in text or "._artifact_hashes" in text
    candidates: list[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("files"), dict):
        candidates.extend(str(key) for key in payload["files"])
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) == "exclude":
                continue
            candidates.append(str(key))
            if isinstance(value, str):
                candidates.append(value)
    return any(is_appledouble_path(text) for text in candidates)


def is_appledouble_path(text: str) -> bool:
    parts = Path(text).parts
    return any(part.startswith("._") for part in parts)


def artifact_hashes(root: Path) -> dict[str, Any]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_NAMES or any(part in HASH_EXCLUDE_PARTS for part in rel_parts):
            continue
        entries[str(path.relative_to(root))] = sha256_file(path)
    return {
        "schema": "setp-artifact-hashes.v1",
        "root": rel(root),
        "generated_at_epoch": time.time(),
        "exclude": sorted([*HASH_EXCLUDE_NAMES, *HASH_EXCLUDE_PARTS, "._*"]),
        "files": entries,
    }


def decide(metadata: dict[str, Any], cleanup_rows: list[dict[str, Any]], refresh_rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if metadata.get("protected_files"):
        failures.append({"failure_bucket": "protected_file_diff", "paths": metadata.get("protected_files")})
    if not metadata.get("gitignore_has_appledouble") or not metadata.get("gitignore_has_pycache") or not metadata.get("gitignore_has_pytest_cache"):
        failures.append({"failure_bucket": "gitignore_hygiene_entries_missing"})
    missing = [row for row in refresh_rows if row.get("status") == "MISSING"]
    if missing:
        failures.append({"failure_bucket": "evidence_dir_missing", "rows": missing})
    contaminated_after = [row for row in refresh_rows if bool(row.get("contains_appledouble_after"))]
    if contaminated_after:
        failures.append({"failure_bucket": "hash_still_contaminated", "rows": contaminated_after})
    return {
        "schema": "setp-e2-g0-closure-hygiene-decision.v1",
        "verdict": "HALT_COLLECTION_COST" if failures else "C0_HYGIENE_COMPLETE",
        "head": metadata.get("head"),
        "removed_or_registered_count": len(cleanup_rows),
        "evidence_hash_dirs": len(refresh_rows),
        "old_hash_contaminated_dirs": [row["evidence_dir"] for row in refresh_rows if bool(row.get("old_hash_contaminated"))],
        "failure_count": len(failures),
        "failure_sample": failures[:20],
    }


def render_report(
    metadata: dict[str, Any],
    decision: dict[str, Any],
    cleanup_rows: list[dict[str, Any]],
    refresh_rows: list[dict[str, Any]],
) -> str:
    removed = [row for row in cleanup_rows if row.get("removed") is True]
    git_registered = [row for row in cleanup_rows if row.get("kind") == "appledouble_in_git_registered_not_touched"]
    lines = [
        "# E2-G0 Phase A C0 Hygiene",
        "",
        "本阶段只做证据卫生：清理非 `.git` AppleDouble/cache，登记 `.git` 内 AppleDouble 但不触碰，重生涉证目录 clean hash。",
        "",
        f"Verdict: `{decision.get('verdict')}`",
        "",
        f"- HEAD: `{metadata.get('head')}`",
        f"- removed non-git hygiene artifacts: `{len(removed)}`",
        f"- registered .git AppleDouble artifacts not touched: `{len(git_registered)}`",
        f"- refreshed evidence hash dirs: `{len(refresh_rows)}`",
        "",
        "## Hash Refresh",
        "",
        "| evidence dir | status | old hash contaminated | old backup | clean entries |",
        "|---|---|---:|---|---:|",
    ]
    for row in refresh_rows:
        lines.append(
            f"| {row.get('evidence_dir')} | {row.get('status')} | {row.get('old_hash_contaminated', '')} | "
            f"{row.get('old_hash_backup', '')} | {row.get('clean_entry_count', '')} |"
        )
    if decision.get("failure_sample"):
        lines.extend(["", "## Failure Sample", "", "```json", json.dumps(decision["failure_sample"], ensure_ascii=False, indent=2), "```"])
    lines.append("")
    return "\n".join(lines)


def protected_diff() -> list[str]:
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
        "solver/src/setp_solver/search/feasible_repair.py",
        "solver/src/setp_solver/search/resetp_alns",
        "solver/src/setp_solver/search/alns_wouda.py",
        "solver/src/setp_solver/search/winner_operators.py",
        "solver/src/setp_solver/search/carbon_operators.py",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, text=True, capture_output=True)
    return proc.stdout.strip()


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
