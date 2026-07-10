"""Canonical formal instance registry for ReSETP.

Decision (2026-07-09): formal default is L-main 9-step **threeshift-only** ladder
(sizes 10/15/20/25/50/75/100/150/200, donor -01).

All formal E2 and subsequent experiment runners should resolve instances through
this module. Archive sets remain on disk but are not in FORMAL_INSTANCE_ORDER.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

L_MAIN_THREESHIFT_SIZES: tuple[int, ...] = (10, 15, 20, 25, 50, 75, 100, 150, 200)
FORMAL_MANIFEST_NAME = "resetp-l-main-main-benchmark.v3.json"
FORMAL_AUDIT_DECISION_REL_PATH = Path("baselines/e2_alns/l_main_v3_activation/decision.json")

FORMAL_INSTANCE_ORDER: tuple[str, ...] = tuple(
    f"L-main-threeshift-{size}c-01" for size in L_MAIN_THREESHIFT_SIZES
)

# Backward-compatible aliases used by older e2_* runners / CSV archives.
E2_TO_LMAIN_ALIAS: dict[str, str] = {
    f"e2-threeshift-{size}c-01": f"L-main-threeshift-{size}c-01" for size in L_MAIN_THREESHIFT_SIZES
}
LMAIN_TO_E2_ALIAS: dict[str, str] = {v: k for k, v in E2_TO_LMAIN_ALIAS.items()}

INSTANCE_REL_DIRS: dict[str, Path] = {
    name: Path("models/data_bundle/generated_instances/L-main") / name
    for name in FORMAL_INSTANCE_ORDER
}

ARCHIVE_NOTE = (
    "ARCHIVE_ONLY sets: L-main_mixed23_archive_20260709, L-main_legacy_pre_23, "
    "e2_benchmark vanilla/multidepot, 100-01-24h historical anchor lineage."
)


def formal_instance_names() -> tuple[str, ...]:
    return FORMAL_INSTANCE_ORDER


def resolve_instance_name(name: str) -> str:
    """Map legacy e2-* threeshift -01 names to L-main formal ids; pass through otherwise."""
    return E2_TO_LMAIN_ALIAS.get(name, name)


def instance_rel_dir(name: str) -> Path:
    resolved = resolve_instance_name(name)
    if resolved not in INSTANCE_REL_DIRS:
        raise KeyError(
            f"Unknown formal instance {name!r} (resolved {resolved!r}). "
            f"Formal set is 9 threeshift L-main -01 ladders only. {ARCHIVE_NOTE}"
        )
    return INSTANCE_REL_DIRS[resolved]


def instance_abs_dir(repo_root: str | Path, name: str) -> Path:
    return Path(repo_root) / instance_rel_dir(name)


def iter_formal_bundles(repo_root: str | Path) -> Iterable[tuple[str, Path]]:
    root = Path(repo_root)
    for name in FORMAL_INSTANCE_ORDER:
        path = root / INSTANCE_REL_DIRS[name]
        if not path.is_dir():
            raise FileNotFoundError(f"Missing formal instance bundle: {path}")
        yield name, path


def assert_formal_benchmark_ready(repo_root: str | Path) -> dict:
    """Reject formal runs unless the active v3 manifest has a matching ready audit."""

    root = Path(repo_root)
    manifest_path = root / "models/data_bundle/generated_instances/L-main" / FORMAL_MANIFEST_NAME
    if not manifest_path.is_file():
        raise RuntimeError(f"formal L-main v3 manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "resetp-l-main-main-benchmark.v3":
        raise RuntimeError("formal L-main manifest is not v3")
    if manifest.get("formal_default") is not True or manifest.get("activation_requires_verdict") != "LMAIN_V3_READY":
        raise RuntimeError("formal L-main v3 activation contract is missing")
    instance_ids = tuple(str(item.get("instance_id", "")) for item in manifest.get("instances", []))
    if instance_ids != FORMAL_INSTANCE_ORDER:
        raise RuntimeError(f"formal L-main v3 instance order mismatch: {instance_ids}")
    sidecars = [
        f"{item.get('instance_id')}:{name}"
        for item in manifest.get("instances", [])
        for name in item.get("bundle_file_hashes", {})
        if str(name).startswith("._")
    ]
    if sidecars:
        raise RuntimeError(f"formal L-main v3 manifest contains AppleDouble hashes: {sidecars[:3]}")

    decision_path = root / FORMAL_AUDIT_DECISION_REL_PATH
    if not decision_path.is_file():
        raise RuntimeError(f"matching LMAIN_V3_READY audit is missing: {decision_path}")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if decision.get("verdict") != "LMAIN_V3_READY" or decision.get("manifest_sha256") != manifest_sha256:
        raise RuntimeError("LMAIN_V3_READY audit does not match the active formal manifest")
    return manifest
