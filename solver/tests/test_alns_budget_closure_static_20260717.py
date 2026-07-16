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


def test_static_contract_covers_every_current_scorer_call() -> None:
    module = _load_module()
    rows = module.classify_calls(module.scan_scorer_calls())
    assert len(rows) == len(module.EXPECTED_RULES)
    assert not [row for row in rows if row["phase"] == "unclassified"]
    assert any(
        row["source"] == "operators/local_search.py"
        and row["function"] == "_score_internal_solution"
        and row["closure_status"] == "BLOCK"
        for row in rows
    )
    assert any(
        row["source"] == "kernel/alns_core.py"
        and row["function"] == "_finalize_candidate_state"
        and row["closure_status"] == "PASS"
        for row in rows
    )


def test_zero_search_audit_writes_five_surfaces_and_halt(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "budget-audit"
    decision = module.run_audit(output)
    assert decision["verdict"] == "HALT_ALNS_BUDGET_CLOSURE_REQUIRED"
    assert decision["search_evaluations"] == 0
    assert decision["formal_benchmark_authorized"] is False
    expected = {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    }
    assert {path.name for path in output.iterdir()} == expected

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["audit_kind"] == "zero_search_static_source_audit"
    assert metadata["search_evaluations"] == 0
    assert metadata["experiments_started"] == 0

    with (output / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == decision["scorer_call_count"]
    assert sum(row["closure_status"] == "BLOCK" for row in rows) == decision["closure_blocker_call_sites"]

    manifest = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    for rel, expected_hash in manifest.items():
        path = output / rel.removeprefix("OUTPUT/") if rel.startswith("OUTPUT/") else REPO_ROOT / rel
        assert _sha256(path) == expected_hash
    assert not any(path.name.startswith("._") for path in output.rglob("*"))


def test_g0_contract_requires_one_to_one_runtime_evidence() -> None:
    module = _load_module()
    rows = module.classify_calls(module.scan_scorer_calls())
    blockers = [row for row in rows if row["closure_status"] == "BLOCK"]
    assert blockers
    assert any(row["accounting"] == "unbudgeted_direct_model_eval" for row in blockers)
    assert any(row["accounting"] == "unbudgeted_reference" for row in blockers)
