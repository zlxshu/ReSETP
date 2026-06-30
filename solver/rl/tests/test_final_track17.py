from __future__ import annotations

from dr_alns_ppo.final_track17 import _summarize_final, _track17_method_summary


def test_track17_method_summary_allows_plain_alns_as_main_when_components_drop() -> None:
    rows = [
        _row("plain_alns", 100.0),
        _row("winner_kernel", 101.0),
        _row("winner_kernel_local_search", 103.0),
    ]

    summary = _track17_method_summary(rows)

    assert summary["verdict"] == "MAIN_METHOD_SELECTED"
    assert summary["chosen_main_method"] == "plain_alns"
    assert summary["retention"]["winner_kernel_local_search"]["decision"] == "drop"


def test_track17_method_summary_keeps_individually_beneficial_component() -> None:
    rows = [
        _row("plain_alns", 100.0),
        _row("winner_kernel", 98.0),
        _row("winner_kernel_local_search", 95.0),
        _row("winner_kernel_charging_required", 99.0),
    ]

    summary = _track17_method_summary(rows)

    assert summary["chosen_main_method"] == "winner_kernel_local_search"
    assert summary["chosen_gain_vs_plain_pct"] == 5.0
    assert summary["retention"]["winner_kernel_local_search"]["decision"] == "keep"
    assert summary["retention"]["winner_kernel_charging_required"]["decision"] == "drop"


def test_track17_final_summary_uses_margin_real() -> None:
    status, reason = _summarize_final({"fair_comparison": {"verdict": "MARGIN_REAL", "reason": "true margin"}})

    assert status == "MARGIN_REAL"
    assert reason == "true margin"


def _row(name: str, cost: float) -> dict[str, object]:
    return {
        "algorithm": name,
        "role": "method",
        "best_cost": cost,
        "feasible": True,
        "violation_count": 0,
    }
