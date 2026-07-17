"""Capture operation-source evidence for the nine China depot-site candidates.

This downloader is deliberately separate from the identity-source package.  It
records every URL and failure, tries urllib first and curl second, and never
converts map coordinates or authorises instance generation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "docs/handoff/china_facility_manifest_v2_20260718.json"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china_operational_site_sources_v2_20260718"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ReSETP-China-evidence/1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_rows() -> list[dict[str, str | int]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows: list[dict[str, str | int]] = []
    for record in manifest["records"]:
        site = record.get("preferred_operational_site") or {}
        for index, url in enumerate(site.get("official_operation_sources") or [], start=1):
            rows.append(
                {
                    "facility_id": record["facility_id"],
                    "city": record["city"],
                    "site_name_zh": site.get("name_zh", ""),
                    "source_index": index,
                    "source_url": url,
                    "evidence_scope": site.get("evidence_scope", ""),
                }
            )
    return rows


def capture(row: dict[str, str | int], raw: Path, timeout: float) -> dict[str, object]:
    stem = f"{row['facility_id']}__{int(row['source_index']):02d}"
    output = raw / f"{stem}.bin"
    error_path = raw / f"{stem}.error.txt"
    url = str(row["source_url"])
    started = time.monotonic()
    urllib_error = ""
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"})
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            if int(response.status) == 200 and body:
                output.write_bytes(body)
                error_path.unlink(missing_ok=True)
                return {
                    **row,
                    "capture_status": "CAPTURED_URLLIB",
                    "http_status": int(response.status),
                    "content_type": str(response.headers.get("Content-Type", "")),
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "capture_path": str(output.relative_to(REPO)),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "error": "",
                }
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        urllib_error = f"{type(exc).__name__}: {exc}"

    curl = subprocess.run(
        [
            "curl",
            "--location",
            "--fail-with-body",
            "--silent",
            "--show-error",
            "--max-time",
            str(max(1, int(timeout))),
            "--user-agent",
            USER_AGENT,
            "--output",
            str(output),
            "--write-out",
            "%{http_code}|%{content_type}",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    status_text, _, content_type = curl.stdout.strip().partition("|")
    status = int(status_text) if status_text.isdigit() else None
    if curl.returncode == 0 and status == 200 and output.is_file() and output.stat().st_size:
        error_path.unlink(missing_ok=True)
        return {
            **row,
            "capture_status": "CAPTURED_CURL_FALLBACK",
            "http_status": status,
            "content_type": content_type,
            "bytes": output.stat().st_size,
            "sha256": sha256(output),
            "capture_path": str(output.relative_to(REPO)),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": urllib_error,
        }
    # Shenzhen's current government host presents a TLS curve that this
    # machine's command-line OpenSSL rejects with BAD_ECPOINT.  Its same-host
    # HTTP endpoint is therefore an explicit, narrow transport fallback.  The
    # canonical HTTPS URL remains the evidence identity and the downgrade is
    # recorded; this is not generalized to any other host.
    if url.startswith("https://www.sz.gov.cn/"):
        fallback_url = "http://" + url.removeprefix("https://")
        fallback = subprocess.run(
            [
                "curl",
                "--location",
                "--fail-with-body",
                "--silent",
                "--show-error",
                "--max-time",
                str(max(1, int(timeout))),
                "--user-agent",
                USER_AGENT,
                "--output",
                str(output),
                "--write-out",
                "%{http_code}|%{content_type}|%{url_effective}",
                fallback_url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        fallback_status_text, _, remainder = fallback.stdout.strip().partition("|")
        fallback_content_type, _, effective_url = remainder.partition("|")
        fallback_status = int(fallback_status_text) if fallback_status_text.isdigit() else None
        if (
            fallback.returncode == 0
            and fallback_status == 200
            and output.is_file()
            and output.stat().st_size
        ):
            error_path.unlink(missing_ok=True)
            return {
                **row,
                "capture_status": "CAPTURED_HTTP_TRANSPORT_FALLBACK",
                "http_status": fallback_status,
                "content_type": fallback_content_type,
                "bytes": output.stat().st_size,
                "sha256": sha256(output),
                "capture_path": str(output.relative_to(REPO)),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error": urllib_error or curl.stderr.strip(),
                "transport_fallback_url": fallback_url,
                "effective_url": effective_url,
                "transport_boundary": "canonical source is HTTPS; local bytes used the same-host HTTP endpoint after BAD_ECPOINT",
            }
    output.unlink(missing_ok=True)
    combined_error = f"urllib={urllib_error}; curl={curl.stderr.strip()}; http={status}"
    error_path.write_text(combined_error + "\n", encoding="utf-8")
    return {
        **row,
        "capture_status": "CAPTURE_FAILED",
        "http_status": status,
        "content_type": content_type,
        "bytes": 0,
        "sha256": "",
        "capture_path": "",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "error": combined_error,
        "transport_fallback_url": "",
        "effective_url": "",
        "transport_boundary": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output: {output}")
    raw = output / "raw"
    raw.mkdir(parents=True)
    generated_at = utc_now()
    rows = [capture(row, raw, args.timeout) for row in source_rows()]
    captured = [row for row in rows if str(row["capture_status"]).startswith("CAPTURED")]
    failed = [row for row in rows if row["capture_status"] == "CAPTURE_FAILED"]
    cities_with_capture = {str(row["city"]) for row in captured}

    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = sorted({key for row in rows for key in row})
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    decision = {
        "schema": "resetp.china.operational-site-source-capture.decision.v1",
        "generated_at": generated_at,
        "verdict": "PASS_OPERATION_SOURCE_CAPTURE_9_OF_9_CITIES" if len(cities_with_capture) == 9 else "HALT_OPERATION_SOURCE_CAPTURE_INCOMPLETE",
        "formal_search_allowed": False,
        "url_count": len(rows),
        "captured_url_count": len(captured),
        "failed_url_count": len(failed),
        "cities_with_at_least_one_capture": sorted(cities_with_capture),
        "failed_urls": [str(row["source_url"]) for row in failed],
        "boundary": "Local source bytes support operation-source reproducibility only; they do not prove a freight entrance, access hours, parking capacity, or charging capacity.",
    }
    write_json(output / "decision.json", decision)
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china.operational-site-source-capture.metadata.v1",
            "generated_at": generated_at,
            "manifest": str(MANIFEST.relative_to(REPO)),
            "manifest_sha256": sha256(MANIFEST),
            "coordinate_policy": "BD09MC remains raw source data and is never written into formal WGS84 fields by this task.",
            "search_evaluations": 0,
        },
    )
    report = [
        "# 中国九城运营场址来源快照",
        "",
        f"判决：`{decision['verdict']}`。共尝试 `{len(rows)}` 条运营来源 URL，保存 `{len(captured)}` 条，覆盖 `{len(cities_with_capture)}/9` 城。",
        "",
        "本包只保存来源字节。它不证明货车入口、营业时间、停车容量或充电能力，`formal_search_allowed=false`。",
        "",
        "| 城市 | 场址 | URL序号 | 状态 | SHA-256 |",
        "|---|---|---:|---|---|",
    ]
    report.extend(
        f"| {row['city']} | {row['site_name_zh']} | {row['source_index']} | `{row['capture_status']}` | `{row['sha256'] or '—'}` |"
        for row in rows
    )
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    artifacts = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(
        output / "artifact_hashes.json",
        {"hash_algorithm": "SHA-256", "generated_at": generated_at, "artifacts": artifacts},
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if len(cities_with_capture) == 9 else 2


if __name__ == "__main__":
    raise SystemExit(main())
