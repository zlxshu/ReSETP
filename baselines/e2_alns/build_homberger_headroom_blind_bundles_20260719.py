#!/usr/bin/env python3
"""Select six unseen Homberger-200 instances by hash and build blind bundles."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile


REPO = Path(__file__).resolve().parents[2]
BUILDER_PATH = REPO / "baselines/e2_alns/build_homberger_200_development_bundles_20260717.py"
SPEC = importlib.util.spec_from_file_location("homberger_builder", BUILDER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {BUILDER_PATH}")
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)

ARCHIVE = (
    REPO
    / "baselines/e2_alns/reference_snapshots/homberger_200_20260717"
    / "homberger_200_customer_instances.zip"
)
OUT = REPO / "baselines/e2_alns/homberger_headroom_blind_bundles_20260719"
EXPECTED_ARCHIVE_SHA256 = "79092cc627135f370a6381b0c64afc8403e4d4ff74afa8808d28d208ac784571"
PATTERN = re.compile(r"^(C1|C2|R1|R2|RC1|RC2)_2_([2-7])\.TXT$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: object) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def main() -> int:
    if sha256(ARCHIVE) != EXPECTED_ARCHIVE_SHA256:
        raise RuntimeError("frozen Homberger archive hash differs")
    OUT.mkdir(parents=True, exist_ok=True)
    if any(OUT.iterdir()):
        raise RuntimeError(f"refuse to overwrite non-empty output: {OUT}")

    candidates: dict[str, list[tuple[str, str, bytes]]] = {}
    with zipfile.ZipFile(ARCHIVE) as archive:
        for member in archive.namelist():
            match = PATTERN.match(member)
            if not match:
                continue
            payload = archive.read(member)
            candidates.setdefault(match.group(1), []).append(
                (sha256_bytes(payload), member, payload)
            )

    selected = {
        family: min(rows, key=lambda item: (item[0], item[1]))
        for family, rows in candidates.items()
    }
    if set(selected) != {"C1", "C2", "R1", "R2", "RC1", "RC2"}:
        raise RuntimeError("blind family selection is incomplete")

    rows = []
    failures: list[str] = []
    for family in ("C1", "C2", "R1", "R2", "RC1", "RC2"):
        source_hash, member, source = selected[family]
        name = Path(member).stem
        instance = BUILDER.SOURCE_AUDIT.parse_instance(source)
        matrix = BUILDER.distance_matrix(instance.nodes)
        bundle = OUT / "bundles" / name
        BUILDER.write_bundle(bundle, BUILDER.bundle_payload(instance), matrix)
        bundle_failures = BUILDER.verify_bundle(bundle, instance, matrix)
        failures.extend(f"{name}:{failure}" for failure in bundle_failures)
        rows.append(
            {
                "family": family,
                "instance": name,
                "selection_rule": "minimum_source_sha256_among_members_2_to_7",
                "candidate_count": len(candidates[family]),
                "source_member": member,
                "source_sha256": source_hash,
                "bundle_instance_sha256": sha256(bundle / "instance.json"),
                "bundle_matrix_sha256": sha256(bundle / "distance_matrix.npy"),
                "bundle_carbon_sha256": sha256(bundle / "carbon_profile.csv"),
                "generic_loader_match": int(not bundle_failures),
                "search_evaluations": 0,
            }
        )

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    metadata = {
        "schema_version": "resetp.homberger-headroom-blind-bundles.v1",
        "source_archive": str(ARCHIVE.relative_to(REPO)),
        "source_archive_sha256": EXPECTED_ARCHIVE_SHA256,
        "selection_before_search": True,
        "selection_rule": "per family minimum SHA-256 among official members 2..7",
        "excluded_members": ["*_2_1", "*_2_8", "*_2_9", "*_2_10"],
        "bks_read": False,
        "search_evaluations": 0,
    }
    decision = {
        "verdict": (
            "PASS_BLIND_HEADROOM_BUNDLES_READY"
            if not failures
            else "FAIL_BLIND_HEADROOM_BUNDLES"
        ),
        "selected_instances": [row["instance"] for row in rows],
        "failures": failures,
        "formal_test_set": False,
        "development_only": True,
    }
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# Homberger-200新开发题结果盲选择\n\n"
        f"判定：`{decision['verdict']}`。每类只在官方压缩包第2至7号成员中，"
        "按源文件SHA-256最小值选择一题；选择时不读取BKS或算法结果。"
        "该六题仅用于检查短时搜索是否仍有改进空间，不是正式测试集。\n",
    )
    files = [
        path
        for path in OUT.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    ]
    atomic_json(
        OUT / "artifact_hashes.json",
        {
            str(path.relative_to(OUT)): sha256(path)
            for path in sorted(files)
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
