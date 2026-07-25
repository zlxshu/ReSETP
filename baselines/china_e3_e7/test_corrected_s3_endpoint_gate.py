"""Tests for the preregistered Chen-style mechanism endpoint gate."""

from __future__ import annotations

from baselines.e2_final_campaign_20260720.corrected_china81_rerun_20260723.run_corrected_s3 import (
    mechanism_endpoint_checks,
)


def _passing_inputs() -> tuple[
    dict[str, dict[str, int]],
    dict[str, dict[str, float]],
]:
    pairwise = {
        "HGS-F": {"wins": 10, "ties": 0, "losses": 0},
        "HGS-E": {"wins": 8, "ties": 2, "losses": 0},
        "HGS-M": {"wins": 7, "ties": 3, "losses": 0},
    }
    summary = {
        "HGS-F": {"mean_cost": 105.0},
        "HGS-E": {"mean_cost": 103.0},
        "HGS-M": {"mean_cost": 101.0},
        "MV-HGS-SP": {"mean_cost": 100.0},
    }
    return pairwise, summary


def test_mechanism_endpoint_gate_accepts_only_the_registered_pattern() -> None:
    pairwise, summary = _passing_inputs()
    checks = mechanism_endpoint_checks(pairwise, summary)
    assert checks
    assert all(checks.values())


def test_mechanism_endpoint_gate_rejects_a_loss() -> None:
    pairwise, summary = _passing_inputs()
    pairwise["HGS-M"] = {"wins": 7, "ties": 2, "losses": 1}
    checks = mechanism_endpoint_checks(pairwise, summary)
    assert checks["zero_losses_vs_HGS-M"] is False
    assert all(
        passed
        for name, passed in checks.items()
        if name != "zero_losses_vs_HGS-M"
    )


def test_mechanism_endpoint_gate_rejects_too_few_wins_or_equal_mean() -> None:
    pairwise, summary = _passing_inputs()
    pairwise["HGS-E"] = {"wins": 7, "ties": 3, "losses": 0}
    summary["HGS-M"]["mean_cost"] = 100.0
    checks = mechanism_endpoint_checks(pairwise, summary)
    assert checks["at_least_8_wins_vs_HGS-E"] is False
    assert checks["mean_below_HGS-M"] is False
