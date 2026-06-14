#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: merge_r2_manifests.py <ATTEMPT_DIR>", file=sys.stderr)
        return 1

    attempt_dir = Path(sys.argv[1])
    combined_dir = attempt_dir / "combined"
    (combined_dir / "tables").mkdir(parents=True, exist_ok=True)
    (combined_dir / "figures").mkdir(parents=True, exist_ok=True)

    manifest_paths = sorted(attempt_dir.glob("units/*/formal_runner_manifest.json"))
    if not manifest_paths:
        print(f"No per-unit manifests found under {attempt_dir / 'units'}", file=sys.stderr)
        return 1

    merged: dict[str, dict] = {}
    unit_dirs: set[Path] = set()
    for manifest_path in manifest_paths:
        unit_dirs.add(manifest_path.parent)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for run in payload.get("runs", []):
            key_id = run.get("key_id")
            if not key_id:
                continue
            merged[str(key_id)] = run

    combined_manifest = {
        "schema_version": "setp-formal-runner-ledger.v1",
        "build_note": "merged from parallel units by merge_r2_manifests.py",
        "runs": list(merged.values()),
    }
    (combined_dir / "formal_runner_manifest.json").write_text(
        json.dumps(combined_manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    quota_target = combined_dir / "carbon_quota_L-main.json"
    if not quota_target.exists():
        for candidate in (
            attempt_dir / "units" / "e3_s1" / "carbon_quota_L-main.json",
            attempt_dir / "units" / "e3_s2" / "carbon_quota_L-main.json",
            attempt_dir / "units" / "e4_s1" / "carbon_quota_L-main.json",
            attempt_dir / "units" / "e4_s2" / "carbon_quota_L-main.json",
        ):
            if candidate.exists():
                shutil.copy2(candidate, quota_target)
                break
        else:
            print("WARNING: carbon_quota_L-main.json not found in expected unit dirs")

    statuses = Counter(str(run.get("status", "")) for run in merged.values())
    experiments = Counter(str(run.get("key", {}).get("experiment", "")) for run in merged.values())
    print(f"Merged {len(manifest_paths)} manifests from {len(unit_dirs)} unit dirs")
    print(f"Total runs in combined manifest: {len(merged)}")
    print(f"Completed: {statuses.get('completed', 0)}  Failed: {statuses.get('failed', 0)}  (by status)")
    print(f"Experiments: {dict(sorted(experiments.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
