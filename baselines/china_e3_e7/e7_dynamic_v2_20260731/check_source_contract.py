#!/usr/bin/env python3
"""Zero-search regression check for the E7 v2 source adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path

import run_e7_dynamic as runner


REQUIRED_THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def main() -> None:
    for name in REQUIRED_THREAD_ENV:
        if os.environ.get(name) != "1":
            raise RuntimeError(f"HALT_THREAD_ENV:{name}={os.environ.get(name)!r}")
    runner.LEGACY._CURRENT_ALGORITHM_SEED = 1
    sources, _ = runner.current_sources(network="50c")
    paths = sources["instance_source_paths"]
    hashes = sources["instance_source_sha256"]
    if set(paths) != runner.EXPECTED_CHINA81_SOURCE_KEYS:
        raise RuntimeError("HALT_SOURCE_KEY_SET_MISMATCH")
    if set(hashes) != runner.EXPECTED_CHINA81_SOURCE_KEYS:
        raise RuntimeError("HALT_SOURCE_HASH_SET_MISMATCH")
    if "instance_path" in sources:
        raise RuntimeError("HALT_LEGACY_INSTANCE_PATH_STILL_PRESENT")
    if any(not path.is_absolute() or not path.exists() for path in paths.values()):
        raise RuntimeError("HALT_SOURCE_PATH_NOT_RESOLVED")
    payload = {
        "status": "PASS_ZERO_SEARCH_SOURCE_CONTRACT",
        "search_evaluations": 0,
        "legacy_expected_key": "instance_json",
        "legacy_adapter_field": "instance_path",
        "china81_source_keys": sorted(paths),
        "instance_source_paths": {
            key: str(path) for key, path in sorted(paths.items())
        },
        "instance_source_sha256": dict(sorted(hashes.items())),
    }
    output = runner.HERE / "source_contract_check.json"
    runner.LEGACY.atomic_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
