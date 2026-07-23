#!/usr/bin/env python3
"""Rebuild China81 directed matrices for the GIS-corrected node authority.

The accepted OSRM graphs and existing route-response cache rows are reused
byte-for-byte. Only coordinate pairs absent from the old caches are queried
from the same local graph/profile. No optimiser or model search is invoked.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType
from typing import Any


REPO = Path(__file__).resolve().parents[2]
LEGACY_BUILDER = (
    REPO
    / "baselines/china_instances/"
    "build_china81_directed_matrices_20260718.py"
)
STATIC = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
OLD = (
    REPO
    / "data/ChinaInstances/"
    "china81_local_directed_matrices_v9_20260718"
)
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_legacy() -> ModuleType:
    sys.path.insert(0, str(LEGACY_BUILDER.parent))
    spec = importlib.util.spec_from_file_location(
        "resetp_legacy_matrix_builder",
        LEGACY_BUILDER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import builder: {LEGACY_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build() -> int:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite matrix authority: {OUT}")
    OUT.mkdir(parents=True)
    reused_cache_hashes = {}
    for region in ("jjj", "prd", "cy"):
        for profile in ("cv", "ev"):
            name = f"route_cache_{region}_{profile}.sqlite"
            source = OLD / name
            target = OUT / name
            if not source.is_file():
                raise RuntimeError(f"missing old accepted cache: {source}")
            expected = sha256(source)
            shutil.copy2(source, target)
            if sha256(target) != expected:
                raise RuntimeError(f"route-cache copy hash drift: {target}")
            reused_cache_hashes[name] = expected

    legacy = load_legacy()
    legacy.STATIC = STATIC
    legacy.OUT = OUT
    original_argv = sys.argv
    sys.argv = [
        str(LEGACY_BUILDER),
        "--workers",
        "6",
        "--router-threads",
        "2",
        "--timeout-s",
        "20",
    ]
    try:
        result = int(legacy.main())
    finally:
        sys.argv = original_argv
    if result != 0:
        return result

    metadata_path = OUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "schema": "resetp.china81-local-directed-matrices.v2",
            "repair_builder": str(Path(__file__).relative_to(REPO)),
            "repair_builder_sha256": sha256(Path(__file__)),
            "static_input_authority": str(STATIC.relative_to(REPO)),
            "static_input_authority_hash": sha256(
                STATIC / "artifact_hashes.json"
            ),
            "reused_cache_hashes": reused_cache_hashes,
            "cache_reuse_semantics": (
                "same WGS84 pair, same frozen OSRM graph and profile"
            ),
            "new_route_requests_are_data_build_not_solver_search": True,
            "formal_search_allowed": False,
        }
    )
    write_json(metadata_path, metadata)
    decision_path = OUT / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision.update(
        {
            "verdict": (
                "PASS_CHINA81_CORRECTED_LOCAL_DIRECTED_THREE_MATRICES__"
                "FORMAL_ACCEPTANCE_HELD"
            ),
            "node_authority": str(STATIC.relative_to(REPO)),
            "formal_experiment_authorized": False,
            "search_evaluations": 0,
        }
    )
    write_json(decision_path, decision)
    (OUT / "report.md").write_text(
        "# China81 GIS 修正版本地有向道路三矩阵\n\n"
        "81 个修正版实例的 CV/EV 距离、时间与 `Σ(v²d)` 均来自同一冻结"
        "OSRM 图和同一路线响应。原缓存仅按完全相同 WGS84 有向点对复用；"
        "新点对重新查询本地路由，禁止欧氏、对称或旧节点序号回填。"
        "本构建不运行求解器，正式搜索继续冻结。\n",
        encoding="utf-8",
    )
    artifacts = {}
    for path in sorted(OUT.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        ):
            artifacts[str(path.relative_to(OUT))] = sha256(path)
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "sha256": artifacts,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
