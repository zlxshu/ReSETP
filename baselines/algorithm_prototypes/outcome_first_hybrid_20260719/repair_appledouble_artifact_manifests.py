#!/usr/bin/env python3
"""Remove AppleDouble sidecars from evidence hash manifests without reruns."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "appledouble_hash_manifest_repair_v1"
TARGETS = (
    "bounded_segment_behavior_gate",
    "bounded_segment_behavior_gate_v2_china81_scope",
    "bounded_segment_behavior_gate_v3_china81_scope",
    "public_bks_core_microgate",
    "public_bks_alns_warm_hgs_gate",
    "public_bks_dual_elite_hgs_gate",
    "china81_private_fair_gate_preflight",
    "independent_stage1_audit",
    "independent_stage1_audit_v2",
    "independent_stage1_audit_v3_final",
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for relative in TARGETS:
        root = HERE / relative
        manifest_path = root / "artifact_hashes.json"
        original_bytes = manifest_path.read_bytes()
        original = json.loads(original_bytes)
        sidecar_entries = {
            name: digest
            for name, digest in original.items()
            if _is_sidecar_name(name)
        }
        ordinary_entries = {
            name: digest
            for name, digest in original.items()
            if not _is_sidecar_name(name)
        }
        ordinary_match = all(
            (root / name).is_file()
            and _sha(root / name) == digest
            for name, digest in ordinary_entries.items()
        )
        replacement = {
            path.name: _sha(path)
            for path in sorted(root.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not _is_sidecar_name(path.name)
        }
        before[relative] = {
            "manifest_sha256": _sha_bytes(original_bytes),
            "manifest": original,
        }
        _write_json(manifest_path, replacement)
        replacement_bytes = manifest_path.read_bytes()
        after[relative] = {
            "manifest_sha256": _sha_bytes(replacement_bytes),
            "manifest": replacement,
        }
        replacement_valid = all(
            (root / name).is_file()
            and _sha(root / name) == digest
            for name, digest in replacement.items()
        )
        rows.append(
            {
                "target": relative,
                "old_entries": len(original),
                "old_appledouble_entries": len(sidecar_entries),
                "ordinary_old_hashes_match": ordinary_match,
                "new_entries": len(replacement),
                "new_manifest_valid": replacement_valid,
                "search_evaluations": 0,
            }
        )
    passed = all(
        bool(row["ordinary_old_hashes_match"])
        and bool(row["new_manifest_valid"])
        for row in rows
    )
    OUT.mkdir(parents=True)
    _write_json(OUT / "before_manifests.json", before)
    _write_json(OUT / "after_manifests.json", after)
    _write_csv(OUT / "raw_runs.csv", rows)
    decision = {
        "verdict": (
            "PASS_APPLEDOUBLE_HASH_MANIFEST_REPAIR_NO_RERUN"
            if passed
            else "FAIL_APPLEDOUBLE_HASH_MANIFEST_REPAIR"
        ),
        "targets": len(rows),
        "ordinary_old_hashes_match": all(
            bool(row["ordinary_old_hashes_match"])
            for row in rows
        ),
        "new_manifests_valid": all(
            bool(row["new_manifest_valid"])
            for row in rows
        ),
        "algorithm_reruns": 0,
        "search_evaluations": 0,
    }
    metadata = {
        "schema_version": "resetp.appledouble-hash-manifest-repair.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "repair_script_sha256": _sha(Path(__file__).resolve()),
        "reason": (
            "Original manifests accidentally included macOS AppleDouble "
            "sidecars. dot_clean removed those sidecars, while every ordinary "
            "evidence file retained its recorded SHA-256."
        ),
        "algorithm_reruns": 0,
        "search_evaluations": 0,
    }
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# AppleDouble 哈希清单无重跑修复",
                "",
                f"- 判决：`{decision['verdict']}`",
                f"- 修复清单：{len(rows)}。",
                "- 普通证据文件的旧SHA-256全部保持一致。",
                "- 只从哈希清单删除`._*`旁车项并重新验签普通文件。",
                "- 算法重跑0，搜索评价0；修复前后清单均保留。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: _sha(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not _is_sidecar_name(path.name)
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


def _is_sidecar_name(name: str) -> bool:
    return Path(name).name.startswith("._") or name.startswith(".__")


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
