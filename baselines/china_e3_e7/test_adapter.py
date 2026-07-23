"""Low-cost regression tests for the China E3--E7 foundation adapter."""

from __future__ import annotations

from pathlib import Path

from baselines.china_e3_e7.adapter import ROOT, build_task_manifest, preflight
from baselines.china_e3_e7.contract import instance_rows, load_contract
from baselines.china_e3_e7.tables import render_tables
from baselines.china_e3_e7.statistics import RAW_FIELDS, aggregate_raw


def test_manifest_is_china_only_and_formal_held() -> None:
    contract = load_contract(ROOT)
    manifest = build_task_manifest(contract, instance_rows(ROOT))
    assert manifest["status"] == "PLANNING_ONLY_FORMAL_SEARCH_HELD"
    assert manifest["formal_search_allowed"] is False
    assert manifest["search_evaluations"] == 0
    assert manifest["task_count_e3_to_e6"] == 3_240
    assert manifest["seed_expansion_projection"]["e3_to_e6_task_count_at_blind_cap"] == 4_536
    assert manifest["seed_expansion_projection"]["e7_task_count_at_blind_cap"] == 2_835
    assert manifest["e7_full_matrix_projection"]["task_count"] == 2_025
    assert manifest["e7_result_blind_gate_projection"]["task_count"] == 75
    assert all(task["algorithm_id"] == "MV-HGS-SP" for task in manifest["tasks"])
    assert all("uk" not in task["instance_id"].lower() for task in manifest["tasks"])


def test_preflight_loads_all_china_bundles_without_search() -> None:
    result = preflight(ROOT)
    assert result["status"] == "PASS_FOUNDATION_PREFLIGHT_FORMAL_HELD"
    assert result["runtime_bundle_join"]["loaded"] == 81
    assert result["runtime_bundle_join"]["search_evaluations"] == 0
    assert result["runtime_bundle_join"]["formal_search_allowed"] is False


def test_empty_raw_aggregate_is_not_a_scientific_result(tmp_path: Path) -> None:
    raw = tmp_path / "raw_runs.csv"
    raw.write_text(",".join(RAW_FIELDS) + "\n", encoding="utf-8")
    decision = aggregate_raw(raw, tmp_path / "aggregate", repo_root=ROOT)
    assert decision["status"] == "NO_FORMAL_RESULTS"
    assert decision["formal_rows"] == 0
    assert decision["search_evaluations"] == 0
    assert decision["scientific_claim_allowed"] is False


def test_empty_aggregate_keeps_paper_tables_closed(tmp_path: Path) -> None:
    raw = tmp_path / "raw_runs.csv"
    raw.write_text(",".join(RAW_FIELDS) + "\n", encoding="utf-8")
    aggregate_dir = tmp_path / "aggregate"
    aggregate_raw(raw, aggregate_dir, repo_root=ROOT)
    decision = render_tables(aggregate_dir, tmp_path / "paper_tables", repo_root=ROOT)
    assert decision["status"] == "NO_TABLES"
    assert decision["independent_recalc_complete"] is False
    assert not list((tmp_path / "paper_tables").glob("*.tex"))
