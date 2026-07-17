from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / "baselines/e2_alns/build_final_external_baseline_freeze_20260717.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("external_freeze_builder_test", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_probe_is_bound_to_current_adapter() -> None:
    module = load_builder()
    metadata = module.verify_probe()
    assert metadata["pyvrp_version"] == "0.13.4"
    assert metadata["adapter_sha256"] == module.sha256(module.RUNNER)
    assert metadata["probe_sha256"] == module.sha256(module.PROBE_SOURCE)


def test_wall_clock_derivation_is_explicit_and_reproducible() -> None:
    module = load_builder()
    assert module.STANDARDIZED_SECONDS == 720.0
    assert math.isclose(module.LOCAL_SECONDS, 720.0 / 1.837, rel_tol=0, abs_tol=1e-12)


def test_hash_map_fails_closed_on_drift(tmp_path: Path) -> None:
    module = load_builder()
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("original", encoding="utf-8")
    hashes = {artifact.name: module.sha256(artifact)}
    module.verify_hash_map(tmp_path, hashes)
    artifact.write_text("changed", encoding="utf-8")
    with pytest.raises(module.FreezeError, match="artifact hash differs"):
        module.verify_hash_map(tmp_path, hashes)
