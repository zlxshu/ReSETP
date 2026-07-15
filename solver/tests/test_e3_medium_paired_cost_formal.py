from __future__ import annotations

import pytest

from baselines.e3_ablation import e3_medium_paired_cost_formal_20260715 as formal


def test_formal_contract_freezes_full_matrix() -> None:
    contract = formal.build_contract(
        mode="formal",
        eval_budget=formal.FORMAL_EVAL_BUDGET,
        instances=list(formal.FORMAL_INSTANCE_ORDER),
        seeds=list(formal.FORMAL_SEEDS),
    )

    assert contract["expected_pairs"] == 9 * 3
    assert contract["expected_search_runs"] == 9 * 3 * 2
    assert contract["eval_budget_per_arm"] == 4000
    assert contract["result_direction_used_as_execution_gate"] is False
    assert len(contract["formal_compatibility_gates"]) == 2


def test_pair_specs_share_start_within_each_seed_pair() -> None:
    starts = [
        {
            "instance": "network-a",
            "start_sha256": "start",
            "start_certificate_sha256": "certificate",
            "data_fingerprint_sha256": "data",
        }
    ]

    specs = formal.build_pair_specs(["network-a"], [1, 2], starts, "contract")

    assert len(specs) == 2
    assert {row["start_sha256"] for row in specs} == {"start"}
    assert {row["contract_sha256"] for row in specs} == {"contract"}


def test_report_keeps_raw_and_fallback_boundaries_visible() -> None:
    decision = {
        "status": "FORMAL_COMPLETE",
        "completed_pairs": 27,
        "expected_pairs": 27,
        "completed_search_runs": 54,
        "expected_search_runs": 54,
        "trend_inference_allowed": True,
        "medium_raw_search_network_mean_saving_pct": 3.0,
        "medium_selected_network_mean_saving_pct": 4.0,
    }

    text = formal.report_text(decision)

    assert "原始搜索结果" in text
    assert "合法保底" in text
    assert "不得只摘取" in text


def test_csv_integer_parser_rejects_non_integer() -> None:
    assert formal.parse_csv_ints("1,2,3") == [1, 2, 3]
    with pytest.raises(Exception):
        formal.parse_csv_ints("1,bad")
