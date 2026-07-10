from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .evrptwmf import parse_evrptwmf
from .io import ensure_data_roots, sha256_file


CATALOG_NAME = "goeke_instances.json"


def migrate_goeke_instances(source_dir: str | Path, data_root: str | Path, *, overwrite: bool = False) -> dict[str, Any]:
    src = Path(source_dir)
    if not src.is_dir():
        raise FileNotFoundError(f"Goeke source directory not found: {src}")
    root = Path(data_root)
    roots = ensure_data_roots(root)
    raw_dir = roots["raw_instances"] / "goeke_uk"
    raw_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    for source_path in sorted(src.glob("E-UK*.txt")):
        target_path = raw_dir / source_path.name
        if overwrite or not target_path.exists():
            shutil.copy2(source_path, target_path)
        nodes, matrix = parse_evrptwmf(target_path)
        instance_id = target_path.stem
        entries.append(
            {
                "instance_id": instance_id,
                "dataset_family": "GOEKE_UK_EVRPTWMF",
                "format": "EVRPTWMF_TXT",
                "relative_path": str(target_path.relative_to(root)),
                "source_migration_path": str(source_path),
                "sha256": sha256_file(target_path),
                "node_count": len(nodes),
                "customer_count": sum(node.node_type == "c" for node in nodes),
                "depot_count": sum(node.node_type == "d" for node in nodes),
                "station_count": sum(node.node_type == "f" for node in nodes),
                "distance_matrix_shape": list(matrix.shape),
            }
        )

    catalog = {
        "schema_version": "setp-instance-lab.catalog.v1",
        "data_root": str(root),
        "raw_instance_root": str(raw_dir.relative_to(root)),
        "entry_count": len(entries),
        "entries": entries,
    }
    catalog_path = roots["catalog"] / CATALOG_NAME
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return catalog


def load_goeke_catalog(data_root: str | Path) -> dict[str, Any]:
    root = Path(data_root)
    catalog_path = root / "catalog" / CATALOG_NAME
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Goeke catalog not found: {catalog_path}; run migrate-goeke first")
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def resolve_goeke_instance(data_root: str | Path, instance_id: str) -> Path:
    root = Path(data_root)
    catalog = load_goeke_catalog(root)
    for entry in catalog.get("entries", []):
        if str(entry.get("instance_id", "")).lower() == instance_id.lower():
            return root / entry["relative_path"]
    raise KeyError(f"Goeke instance id not found in catalog: {instance_id}")


def donor_instance_paths(data_root: str | Path, exclude_instance_id: str, *, limit: int | None = None) -> tuple[str, ...]:
    root = Path(data_root)
    catalog = load_goeke_catalog(root)
    paths: list[str] = []
    for entry in catalog.get("entries", []):
        if str(entry.get("instance_id", "")).lower() == exclude_instance_id.lower():
            continue
        paths.append(str(root / entry["relative_path"]))
        if limit is not None and len(paths) >= limit:
            break
    return tuple(paths)
