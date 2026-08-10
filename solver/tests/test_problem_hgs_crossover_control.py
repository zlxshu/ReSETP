from __future__ import annotations

import pytest

from setp_solver.algorithms.problem_hgs.crossover_control import (
    CrossoverAction,
    RuntimeAwareCrossoverController,
)
from setp_solver.algorithms.problem_hgs.education import _meaningfully_better


def test_runtime_controller_gives_no_credit_to_a_damaging_action() -> None:
    controller = RuntimeAwareCrossoverController()

    fast = controller.update(CrossoverAction.FAST, -10.0, 1.0)
    expensive = controller.update(CrossoverAction.DCREX, -10.0, 10.0)

    assert fast.raw_reward == pytest.approx(-10.0)
    assert expensive.raw_reward == pytest.approx(-10.0)
    assert fast.credited_reward == pytest.approx(0.0)
    assert expensive.credited_reward == pytest.approx(0.0)
    assert fast.reward_per_relative_cost == pytest.approx(0.0)
    assert expensive.reward_per_relative_cost == pytest.approx(0.0)


def test_runtime_controller_divides_positive_credit_by_observed_cost() -> None:
    controller = RuntimeAwareCrossoverController()

    fast = controller.update(CrossoverAction.FAST, 10.0, 1.0)
    expensive = controller.update(CrossoverAction.DCREX, 10.0, 10.0)

    assert fast.credited_reward == pytest.approx(10.0)
    assert expensive.credited_reward == pytest.approx(10.0)
    assert fast.relative_execution_cost == pytest.approx(1.0)
    assert expensive.relative_execution_cost == pytest.approx(10.0)
    assert fast.reward_per_relative_cost == pytest.approx(10.0)
    assert expensive.reward_per_relative_cost == pytest.approx(1.0)


def test_education_rejects_float_noise_as_an_improvement() -> None:
    incumbent = 2615.8448349767523

    assert not _meaningfully_better(2615.8448349767520, incumbent)
    assert _meaningfully_better(2615.8448349747520, incumbent)
