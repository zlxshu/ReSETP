#!/usr/bin/env python3
"""E7 v2 execution entrypoint.

This module deliberately reuses the preregistered E7 runner and changes only
the China81 source adapter that caused the startup KeyError in the first run.
The scientific arm definitions, event streams, search calls, and aggregation
logic remain in the prior runner.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LEGACY_RUNNER_PATH = (
    ROOT / "baselines/china_e3_e7/e7_dynamic_20260731/run_e7_dynamic.py"
)


def _load_legacy_runner():
    spec = importlib.util.spec_from_file_location(
        "resetp_e7_dynamic_preregistered_runner",
        LEGACY_RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load preregistered runner: {LEGACY_RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY = _load_legacy_runner()
LEGACY.HERE = HERE
LEGACY.TASK_ID = "E7-DYNAMIC-V2-20260731"
LEGACY.SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *LEGACY.SOURCE_FILES,
            Path(__file__).resolve(),
            LEGACY_RUNNER_PATH.resolve(),
        )
    )
)

EXPECTED_CHINA81_SOURCE_KEYS = {
    "catalog",
    "facilities",
    "finite_fleet_authority",
    "nodes",
    "orders",
    "road_matrices",
    "tariff_carbon_calendar",
    "vehicle_parameter_lock",
}


def _tree_sha256(path: Path) -> str:
    """Hash a directory from relative file names and file hashes."""
    rows: list[dict[str, str]] = []
    for child in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = child.relative_to(path)
        if any(
            part.startswith("._")
            or part in {"__pycache__", ".pytest_cache"}
            for part in relative.parts
        ):
            continue
        rows.append(
            {
                "relative_path": relative.as_posix(),
                "sha256": LEGACY.sha256(child),
            }
        )
    if not rows:
        raise RuntimeError(f"HALT_EMPTY_CHINA81_SOURCE_DIRECTORY:{path}")
    return LEGACY.canonical_sha256(rows)


def _source_sha256(path: Path) -> str:
    if path.is_file():
        return LEGACY.sha256(path)
    if path.is_dir():
        return _tree_sha256(path)
    raise RuntimeError(f"HALT_MISSING_CHINA81_SOURCE:{path}")


def _resolved_china81_sources(bundle: Any) -> dict[str, Path]:
    observed = set(bundle.source_paths)
    if observed != EXPECTED_CHINA81_SOURCE_KEYS:
        missing = sorted(EXPECTED_CHINA81_SOURCE_KEYS - observed)
        extra = sorted(observed - EXPECTED_CHINA81_SOURCE_KEYS)
        raise RuntimeError(
            "HALT_CHINA81_SOURCE_CONTRACT_DRIFT:"
            f"missing={missing}:extra={extra}"
        )
    resolved: dict[str, Path] = {}
    for key, raw_path in sorted(bundle.source_paths.items()):
        path = Path(raw_path)
        if not path.is_absolute():
            path = LEGACY.ROOT / path
        path = path.resolve()
        try:
            path.relative_to(LEGACY.ROOT.resolve())
        except ValueError as exc:
            raise RuntimeError(
                f"HALT_CHINA81_SOURCE_OUTSIDE_PROJECT:{key}:{path}"
            ) from exc
        if not path.exists():
            raise RuntimeError(f"HALT_MISSING_CHINA81_SOURCE:{key}:{path}")
        resolved[key] = path
    return resolved


def current_sources(
    condition: str = "baseline",
    network: str = "50c",
):
    """Return the preregistered sources using the real China81 multi-file contract."""
    del condition
    scale = str(network)
    if scale not in LEGACY.SCALES:
        raise ValueError(f"unknown scale {scale}")
    bundle = LEGACY.e3_module().load_bundle(LEGACY.INSTANCE_BY_SCALE[scale])
    solution = LEGACY.solution_from_plan(scale, LEGACY._CURRENT_ALGORITHM_SEED)
    prepared, certificate = LEGACY.prepare_multitrip_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    LEGACY.validate_multitrip_certificate(
        certificate,
        list(prepared.routes),
        bundle.prices,
    )
    LEGACY._BASE_CHINA_BUNDLE = bundle
    LEGACY._BASE_INSTANCE = bundle.instance
    LEGACY._ALIAS_BY_NODE_ID = {
        node.node_id: node.node_id for node in bundle.instance.nodes
    }
    solution_path = LEGACY.nominal_plan_path(
        scale,
        LEGACY._CURRENT_ALGORITHM_SEED,
    )
    search_bundle = LEGACY.SearchBundle(
        bundle_dir=solution_path.parent,
        instance=bundle.instance,
        carbon_profile=list(bundle.time_profile),
    )
    source_paths = _resolved_china81_sources(bundle)
    sources = {
        "case": (
            f"{LEGACY.INSTANCE_BY_SCALE[scale]}"
            f"__seed{LEGACY._CURRENT_ALGORITHM_SEED}"
        ),
        "bundle": search_bundle,
        "prices": bundle.prices,
        "solution": prepared,
        "certificate": certificate,
        "solution_path": solution_path,
        "certificate_path": solution_path,
        "instance_source_paths": source_paths,
        "instance_source_sha256": {
            key: _source_sha256(path)
            for key, path in sorted(source_paths.items())
        },
    }
    return sources, {0: list(bundle.time_profile)}


# The reused install_adapter() resolves this module global at call time.
LEGACY.current_sources = current_sources


def main() -> None:
    LEGACY.main()


if __name__ == "__main__":
    main()
