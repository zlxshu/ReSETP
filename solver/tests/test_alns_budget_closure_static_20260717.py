from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "baselines/e2_alns/audit_alns_budget_closure_20260717.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_alns_budget_closure_20260717", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_historical_budget_diagnosis_is_hash_verified_and_rederived() -> None:
    module = _load_module()
    result = module.verify_historical_inputs()
    assert all(row["match"] for row in result["surface_hash_checks"].values())
    assert result["derived"] == {
        "run_count": 9,
        "hidden_full_solution_scores_total": 11547,
        "hidden_full_solution_scores_min": 760,
        "hidden_full_solution_scores_max": 2164,
        "effective_to_official_ratio_mean": 13.83,
    }


def test_historical_halt_five_surfaces_remain_hash_sealed() -> None:
    root = REPO_ROOT / "baselines/e2_alns/e2_alns_budget_closure_static_20260717"
    decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "HALT_ALNS_BUDGET_CLOSURE_REQUIRED"
    manifest = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))
    for rel, expected_hash in manifest.items():
        if not (
            rel.startswith("baselines/e2_alns/e2_alns_budget_closure_static_20260717/")
            or rel.startswith("baselines/e2_alns/m1_local_search_budget_20260710/")
            or rel == "baselines/e2_alns/audit_alns_budget_closure_20260717.py"
        ):
            continue
        path = root / rel.removeprefix("OUTPUT/") if rel.startswith("OUTPUT/") else REPO_ROOT / rel
        assert _sha256(path) == expected_hash
