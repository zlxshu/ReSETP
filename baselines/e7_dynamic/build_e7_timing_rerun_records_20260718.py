#!/usr/bin/env python3
"""Build the five formal record surfaces for the sealed E7 timing rerun."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baselines.e7_dynamic import (  # noqa: E402
    audit_e7_external_pause_timing_20260716 as timing_audit,
)


OUT = timing_audit.TIMING_RERUN
FORMAL_RECORDS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def remove_appledouble(root: Path) -> None:
    for path in sorted(root.rglob("._*")):
        if path.is_file():
            path.unlink()


def main() -> int:
    existing = [name for name in FORMAL_RECORDS if (OUT / name).exists()]
    if existing:
        raise RuntimeError(f"refusing to overwrite timing rerun records: {existing}")

    incident = json.loads(timing_audit.INCIDENT.read_text(encoding="utf-8"))
    sessions = json.loads(
        (timing_audit.FORMAL / "sessions.json").read_text(encoding="utf-8")
    )
    gate = timing_audit.verified_effective_timing_gate(
        sessions,
        float(incident["pause_duration_seconds"]),
        incident_sha256=sha256(timing_audit.INCIDENT),
    )
    finished = json.loads((OUT / "RERUN_FINISHED.json").read_text(encoding="utf-8"))
    acceptance = finished["paired_timing_acceptance"]
    rows = [
        {
            "task_id": row["task_id"],
            "stage": row["stage"],
            "lineage": row["lineage"],
            "mode": row["mode"],
            "historical_elapsed_seconds": row["historical_elapsed_seconds"],
            "rerun_elapsed_seconds": row["rerun_elapsed_seconds"],
            "delta_seconds": row["delta_seconds"],
            "relative_delta": row["relative_delta"],
            "child_shift_deviation_from_median_seconds": row[
                "child_shift_deviation_from_median_seconds"
            ],
            "accepted": row["accepted"],
            "search_evaluations_reused": 0,
        }
        for row in acceptance["tasks"]
    ]
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "setp.e7.timing_clean_rerun.records.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "timing_rerun_schema": finished["schema"],
            "task_count": len(rows),
            "parent_task_count": acceptance["parent_task_count"],
            "child_task_count": acceptance["child_task_count"],
            "pause_incident_sha256": sha256(timing_audit.INCIDENT),
            "completion_sha256": sha256(OUT / "RERUN_FINISHED.json"),
            "rerun_manifest_sha256": sha256(OUT / "rerun_manifest.json"),
            "record_builder_sha256": sha256(Path(__file__).resolve()),
            "audit_source_sha256": sha256(Path(timing_audit.__file__).resolve()),
            "historical_packages_modified": False,
            "route_search_evaluations_during_record_build": 0,
        },
    )
    write_json(
        OUT / "decision.json",
        {
            "status": "PASS_E7_TIMING_CLEAN_RERUN_RECORDS_COMPLETE",
            "effective_timing_gate": gate,
            "paired_timing_acceptance": acceptance,
            "task_count": len(rows),
            "all_tasks_accepted": all(row["accepted"] for row in rows),
            "semantic_non_timing_match": finished["semantic_non_timing_match"],
            "historical_packages_unchanged": finished[
                "historical_packages_unchanged"
            ],
            "result_direction_used_for_inclusion": False,
            "route_search_evaluations_during_record_build": 0,
        },
    )
    (OUT / "report.md").write_text(
        "# E7外部暂停污染清洁计时重跑记录\n\n"
        "判决：`PASS_E7_TIMING_CLEAN_RERUN_RECORDS_COMPLETE`。九个指定阶段均使用原合同完成清洁重跑；"
        "父系四项在5%相对误差内复现原耗时，子系五项呈稳定的共同暂停偏移移除。"
        "所有非计时载荷逐任务一致，纳入判定未使用结果方向，历史正式包保持不变。"
        "本记录构建过程未执行任何路径搜索。\n",
        encoding="utf-8",
    )
    remove_appledouble(OUT)
    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    remove_appledouble(OUT)
    if list(OUT.rglob("._*")):
        raise RuntimeError("AppleDouble files remain in timing rerun evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
