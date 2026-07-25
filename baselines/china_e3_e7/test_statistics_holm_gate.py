"""Tests for the preregistered five-family Holm release boundary."""

from __future__ import annotations

import pytest

from baselines.china_e3_e7.statistics import (
    _apply_registered_familywise_holm,
)


def test_e3_alone_does_not_receive_a_fake_familywise_adjustment() -> None:
    rows = [{"family": "E3", "randomization_p": 0.01}]
    status = _apply_registered_familywise_holm(
        rows,
        active_families={"E3"},
        registered_families={"E3", "E4", "E5", "E6", "E7"},
        expected_primary_families=5,
    )
    assert status == (
        "PENDING_UNTIL_ALL_FIVE_PRIMARY_FAMILIES_EXIST"
    )
    assert rows[0]["holm_adjusted_p"] is None


def test_all_five_families_receive_the_registered_holm_adjustment() -> None:
    families = {"E3", "E4", "E5", "E6", "E7"}
    rows = [
        {"family": family, "randomization_p": value}
        for family, value in zip(
            sorted(families),
            (0.001, 0.01, 0.02, 0.04, 0.2),
        )
    ]
    status = _apply_registered_familywise_holm(
        rows,
        active_families=families,
        registered_families=families,
        expected_primary_families=5,
    )
    assert status == "PASS_FIVE_FAMILY_HOLM_COMPLETE"
    adjusted = [
        float(row["holm_adjusted_p"]) for row in rows
    ]
    assert adjusted == pytest.approx(
        (0.005, 0.04, 0.06, 0.08, 0.2)
    )
