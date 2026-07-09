"""Canonical formal instance registry for ReSETP.

Decision (2026-07-09): formal default is L-main 9-step **threeshift-only** ladder
(sizes 10/15/20/25/50/75/100/150/200, donor -01).

All formal E2 and subsequent experiment runners should resolve instances through
this module. Archive sets remain on disk but are not in FORMAL_INSTANCE_ORDER.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

L_MAIN_THREESHIFT_SIZES: tuple[int, ...] = (10, 15, 20, 25, 50, 75, 100, 150, 200)

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
