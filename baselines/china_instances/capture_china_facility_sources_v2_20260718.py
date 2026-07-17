"""Capture the official-source layer for the nine named China depot candidates.

This is a source-capture task only.  It does not geocode, infer an operator,
select a depot entrance, infer chargers, build instances, or run the solver.
An HTTP success is recorded as a local source capture, not as proof that the
facility is a usable depot for the formal model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "docs/handoff/china_facility_manifest_v2_20260718.json"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china_facility_sources_v2_20260718"
USER_AGENT = "ReSETP-China-facility-source-capture/1.0 (academic reproducibility)"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_records() -> list[dict[str, object]]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = data.get("records")
    if not isinstance(records, list) or len(records) != 9:
        raise ValueError("facility manifest must contain exactly nine candidate records")
    return records


def capture_one(record: dict[str, object], raw_dir: Path, retries: int, timeout: float) -> dict[str, object]:
    facility_id = str(record["facility_id"])
    url = str(record["source_url"])
    raw_path = raw_dir / f"{facility_id}.bin"
    error_path = raw_dir / f"{facility_id}.error.txt"
    last_error = ""
    for attempt in range(1, retries + 1):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"})
        started = time.monotonic()
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
                status = int(response.status)
                content_type = str(response.headers.get("Content-Type", ""))
                raw_path.write_bytes(body)
                error_path.unlink(missing_ok=True)
                return {
                    "facility_id": facility_id,
                    "source_url": url,
                    "attempt": attempt,
                    "status": "CAPTURED" if status == 200 and body else "HTTP_NON_200_OR_EMPTY",
                    "http_status": status,
                    "content_type": content_type,
                    "bytes": len(body),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "capture_path": str(raw_path.relative_to(DEFAULT_OUTPUT.parent.parent.parent)) if raw_path.is_relative_to(DEFAULT_OUTPUT.parent.parent.parent) else str(raw_path),
                    "sha256": sha256_bytes(body),
                    "error": "",
                }
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(min(2.0 * attempt, 5.0))
    error_path.write_text(last_error + "\n", encoding="utf-8")
    return {
        "facility_id": facility_id,
        "source_url": url,
        "attempt": retries,
        "status": "CAPTURE_FAILED",
        "http_status": None,
        "content_type": "",
        "bytes": 0,
        "elapsed_seconds": None,
        "capture_path": None,
        "sha256": None,
        "error": last_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    raw_dir.mkdir()
    records = load_records()
    generated_at = utc_now()
    runs = [capture_one(record, raw_dir, max(1, args.retries), args.timeout) for record in records]
    captured = [row for row in runs if row["status"] == "CAPTURED"]
    failed = [row for row in runs if row["status"] != "CAPTURED"]

    evidence_fields = [
        "facility_id",
        "source_url",
        "source_title",
        "government_source_authority",
        "source_scope",
        "evidence_boundary",
        "capture_status",
        "capture_path",
        "sha256",
        "http_status",
        "content_type",
        "bytes",
    ]
    by_id = {str(record["facility_id"]): record for record in records}
    with (output / "source_evidence.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=evidence_fields)
        writer.writeheader()
        for run in runs:
            record = by_id[str(run["facility_id"])]
            writer.writerow(
                {
                    "facility_id": run["facility_id"],
                    "source_url": record["source_url"],
                    "source_title": record["source_title"],
                    "government_source_authority": record["government_source_authority"],
                    "source_scope": record["source_scope"],
                    "evidence_boundary": "Official-source page capture only; no depot coordinate, operator, operating status, or charger capacity is inferred.",
                    "capture_status": run["status"],
                    "capture_path": run["capture_path"] or "",
                    "sha256": run["sha256"] or "",
                    "http_status": run["http_status"] or "",
                    "content_type": run["content_type"],
                    "bytes": run["bytes"],
                }
            )

    decision = {
        "schema": "resetp.china.facility-source-capture.decision.v1",
        "generated_at": generated_at,
        "search_evaluations": 0,
        "verdict": "PASS_OFFICIAL_SOURCE_CAPTURE_LAYER" if not failed else "PARTIAL_OFFICIAL_SOURCE_CAPTURE",
        "formal_search_allowed": False,
        "captured_count": len(captured),
        "failed_count": len(failed),
        "blocking_conditions": [
            "source capture does not establish a usable depot entrance",
            "operator, operating status, map identity and depot charger contract remain separate gates",
        ],
        "failed_sources": [row["facility_id"] for row in failed],
    }
    write_json(output / "decision.json", decision)
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china.facility-source-capture.metadata.v1",
            "generated_at": generated_at,
            "manifest": str(MANIFEST.relative_to(REPO)),
            "source_policy": "URLs are taken from the candidate manifest; no search result or unofficial mirror is substituted.",
            "request_user_agent": USER_AGENT,
            "retries": args.retries,
            "timeout_seconds": args.timeout,
            "search_evaluations": 0,
        },
    )
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = sorted({key for row in runs for key in row})
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(runs)

    report_lines = [
        "# 中国九城官方物流设施来源快照",
        "",
        f"生成时间：`{generated_at}`。本任务 `search_evaluations=0`，不构造算例、不运行优化。",
        "",
        f"当前判决：`{decision['verdict']}`；成功保存 `{len(captured)}/9` 个官方 URL 响应。",
        "",
        "即使网页成功抓取，也只证明来源网页可复核，不证明该设施可以作为车辆出发车场。具体入口坐标、地图/运营编号、运营状态、客户—车场道路距离和车场充电桩合同仍必须另行核验。",
        "",
        "| 设施 | 状态 | 字节数 | SHA-256 |",
        "|---|---|---:|---|",
    ]
    for row in runs:
        report_lines.append(f"| `{row['facility_id']}` | `{row['status']}` | {row['bytes']} | `{row['sha256'] or '—'}` |")
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    hash_paths = [
        path
        for path in output.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and not any(part.startswith("._") for part in path.relative_to(output).parts)
    ]
    write_json(
        output / "artifact_hashes.json",
        {
            "hash_algorithm": "SHA-256",
            "generated_at": generated_at,
            "scope": "official facility source captures only",
            "artifacts": {str(path.relative_to(output)): sha256_file(path) for path in sorted(hash_paths)},
            "excluded": ["._*", "__pycache__", ".pytest_cache", "artifact_hashes.json"],
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
