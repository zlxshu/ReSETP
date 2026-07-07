#!/usr/bin/env python3
"""Build a source-to-literature root audit for ALNS/LNS repair decisions."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/source_literature_root_audit_20260707"
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}

QUERIES = [
    ("ALNS original / operator selection", "adaptive large neighborhood search operator selection vehicle routing Ropke Pisinger"),
    ("DR-ALNS", "deep reinforcement learning adaptive large neighborhood search vehicle routing"),
    ("bandit LNS / Thompson", "multi armed bandit large neighborhood search Thompson sampling vehicle routing"),
    ("HGS / SWAP*", "hybrid genetic search vehicle routing SWAP* neighborhood Vidal"),
    ("route pool / set partitioning", "vehicle routing route pool set partitioning recombination"),
    ("heterogeneous fleet rich VRP", "heterogeneous fleet vehicle routing problem adaptive large neighborhood search"),
    ("EVRP charging repair / partial charging", "electric vehicle routing problem partial charging repair adaptive large neighborhood search"),
    ("carbon-aware charging", "carbon aware electric vehicle routing charging carbon emissions"),
]

SOURCE_MAPPING = {
    "ALNS original / operator selection": "solver/src/setp_solver/search/winner_operators.py; solver/src/setp_solver/search/resetp_alns/select.py",
    "DR-ALNS": "NO_SOURCE_MAPPING",
    "bandit LNS / Thompson": "solver/src/setp_solver/search/resetp_alns/select.py",
    "HGS / SWAP*": "solver/src/setp_solver/search/local_search.py",
    "route pool / set partitioning": "solver/src/setp_solver/search/route_pool.py",
    "heterogeneous fleet rich VRP": "solver/src/setp_solver/search/fleet_charge_corepair.py",
    "EVRP charging repair / partial charging": "solver/src/setp_solver/search/charging.py; solver/src/setp_solver/search/fleet_charge_corepair.py",
    "carbon-aware charging": "solver/src/setp_solver/search/carbon_operators.py; solver/src/setp_solver/search/fleet_charge_corepair.py",
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        rows = collect_rows(limit=300)
    except Exception as exc:  # pragma: no cover - network dependent
        write_no_web_access(exc)
        return 0
    if len(rows) < 300:
        (OUTPUT_DIR / "NO_WEB_ACCESS").write_text(f"OpenAlex returned only {len(rows)} unique rows.\n", encoding="utf-8")
    rows = rows[:300]
    write_matrix(rows)
    write_core(rows)
    write_mapping(rows)
    write_hashes(OUTPUT_DIR)
    return 0


def collect_rows(*, limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for category, query in QUERIES:
        for page in range(1, 5):
            for work in openalex_query(query, page=page):
                key = str(work.get("doi") or work.get("id") or work.get("title"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(work_row(category, query, work))
                if len(rows) >= limit:
                    return rows
            time.sleep(0.2)
    return rows


def openalex_query(query: str, *, page: int) -> list[dict[str, Any]]:
    params = urlencode({"search": query, "per-page": 50, "page": page, "sort": "cited_by_count:desc"})
    request = Request(
        f"https://api.openalex.org/works?{params}",
        headers={"User-Agent": "ReSETP literature root audit (mailto:no-reply@example.com)"},
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - public metadata API
        payload = json.loads(response.read().decode("utf-8"))
    return list(payload.get("results", []))


def work_row(category: str, query: str, work: dict[str, Any]) -> dict[str, Any]:
    authorships = work.get("authorships") or []
    authors = "; ".join(str((item.get("author") or {}).get("display_name", "")) for item in authorships[:6] if item.get("author"))
    source = work.get("primary_location", {}).get("source") or {}
    return {
        "category": category,
        "query": query,
        "title": work.get("title", ""),
        "publication_year": work.get("publication_year", ""),
        "authors": authors,
        "venue": source.get("display_name", ""),
        "doi": work.get("doi", ""),
        "openalex_id": work.get("id", ""),
        "url": work.get("doi") or work.get("id", ""),
        "cited_by_count": work.get("cited_by_count", 0),
        "abstract": abstract_text(work.get("abstract_inverted_index") or {}),
        "source_mapping": SOURCE_MAPPING.get(category, "NO_SOURCE_MAPPING"),
    }


def abstract_text(index: dict[str, list[int]]) -> str:
    if not index:
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        for pos in positions:
            words.append((int(pos), str(word)))
    words.sort()
    return " ".join(word for _pos, word in words)[:1200]


def write_matrix(rows: list[dict[str, Any]]) -> None:
    path = OUTPUT_DIR / "literature_matrix_300.csv"
    fieldnames = [
        "row_id",
        "category",
        "query",
        "title",
        "publication_year",
        "authors",
        "venue",
        "doi",
        "openalex_id",
        "url",
        "cited_by_count",
        "source_mapping",
        "abstract",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for idx, row in enumerate(rows, start=1):
            writer.writerow({"row_id": idx, **row})


def write_core(rows: list[dict[str, Any]]) -> None:
    selected = sorted(rows, key=lambda row: int(row.get("cited_by_count") or 0), reverse=True)[:30]
    lines = ["# Literature Core 30 Deepread", "", "Metadata and abstracts were collected from OpenAlex; source mappings are code-level audit anchors, not literature claims.", ""]
    for idx, row in enumerate(selected, start=1):
        lines.extend(
            [
                f"## {idx}. {row.get('title', '')}",
                "",
                f"- Category: {row.get('category', '')}",
                f"- Year: {row.get('publication_year', '')}",
                f"- Venue: {row.get('venue', '')}",
                f"- DOI/OpenAlex: {row.get('doi') or row.get('openalex_id')}",
                f"- Source mapping: {row.get('source_mapping', '')}",
                "",
                str(row.get("abstract", "") or "NO_ABSTRACT_AVAILABLE"),
                "",
            ]
        )
    (OUTPUT_DIR / "literature_core_30_deepread.md").write_text("\n".join(lines), encoding="utf-8")


def write_mapping(rows: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    lines = ["# Literature To Source Mapping", ""]
    for category, _query in QUERIES:
        lines.append(f"- {category}: {SOURCE_MAPPING.get(category, 'NO_SOURCE_MAPPING')} ({counts.get(category, 0)} rows)")
    (OUTPUT_DIR / "literature_to_source_mapping.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_no_web_access(exc: Exception) -> None:
    (OUTPUT_DIR / "NO_WEB_ACCESS").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
    (OUTPUT_DIR / "literature_matrix_300.csv").write_text("NO_WEB_ACCESS\n", encoding="utf-8")
    (OUTPUT_DIR / "literature_core_30_deepread.md").write_text("# NO_WEB_ACCESS\n", encoding="utf-8")
    (OUTPUT_DIR / "literature_to_source_mapping.md").write_text("# NO_WEB_ACCESS\n", encoding="utf-8")
    write_hashes(OUTPUT_DIR)


def write_hashes(output_dir: Path) -> None:
    output_dir = output_dir.resolve()
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
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema": "setp-artifact-hashes.v1",
                "root": str(output_dir.relative_to(REPO_ROOT)),
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
