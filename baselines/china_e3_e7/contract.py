"""Shared contract and manifest helpers for the China E3--E7 adapter."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v4_20260723.json"
)


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_contract(repo_root: Path = ROOT) -> dict[str, Any]:
    path = repo_root / CONTRACT_PATH.relative_to(ROOT)
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def catalog_rows(repo_root: Path = ROOT) -> list[dict[str, str]]:
    contract = load_contract(repo_root)
    return read_csv(repo_root / contract["data"]["catalog"])


def instance_rows(repo_root: Path = ROOT) -> list[dict[str, str]]:
    return sorted(catalog_rows(repo_root), key=lambda row: row["instance_id"])


def customer_size(row: dict[str, str]) -> int:
    return int(row["customer_count"])


def map_index(row: dict[str, str]) -> int:
    match = re.search(r"-(\d\d)-V2-LOCATIONS$", row["instance_id"])
    if match is None:
        raise ValueError(f"cannot parse China81 map index: {row['instance_id']}")
    return int(match.group(1))


def primary_cell_id(row: dict[str, str]) -> str:
    return f"{row['region'].strip().lower()}__{customer_size(row)}"


def family_by_id(contract: dict[str, Any], family_id: str) -> dict[str, Any]:
    for family in contract["families"]:
        if family["id"] == family_id:
            return family
    raise KeyError(f"unknown China E3-E7 family: {family_id}")


def all_source_paths(contract: dict[str, Any]) -> list[str]:
    paths: list[str] = [contract_path for contract_path in contract["source_contracts"].values()]
    paths.extend(
        [
            contract["data"]["catalog"],
            contract["data"]["orders"],
            contract["source_contracts"]["calendar_machine_decision"],
            contract["source_contracts"]["calendar_panel"],
            contract["source_contracts"]["parameter_lock_machine"],
            "data/ChinaInstances/china81_g1_independent_frozen_v2_20260718/decision.json",
            "baselines/model_verification/china81_vehicle_road_profiles_nl3b_20260720/decision.json",
            "docs/paper_v2/paper_main.tex",
        ]
    )
    return list(dict.fromkeys(paths))


def source_hashes(
    contract: dict[str, Any],
    repo_root: Path = ROOT,
    *,
    include_instance_nodes: bool = True,
) -> dict[str, str]:
    """Hash relevant frozen inputs while excluding AppleDouble and caches."""

    paths = [repo_root / relative for relative in all_source_paths(contract)]
    if include_instance_nodes:
        static_root = repo_root / contract["data"]["static_root"] / "instances"
        paths.extend(sorted(static_root.glob("*/nodes.csv")))
    hashes: dict[str, str] = {}
    for path in paths:
        if not path.is_file() or path.name.startswith("._"):
            continue
        hashes[str(path.relative_to(repo_root))] = file_sha256(path)
    return hashes


def task_id(
    family_id: str,
    instance_id: str,
    seed: int,
    arm_id: str,
) -> str:
    return f"{family_id}__{instance_id}__seed{seed}__{arm_id}"


def pair_id(family_id: str, instance_id: str, seed: int) -> str:
    return f"{family_id}__{instance_id}__seed{seed}"


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
