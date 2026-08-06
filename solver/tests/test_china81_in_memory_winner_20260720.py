from __future__ import annotations

from pathlib import Path

import pytest

from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_winner_kernel_in_memory,
)
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.model_config import (
    MissingModelConfigError,
    ModelConfig,
    legacy_model_config_from_environment,
    model_config_scope,
    strict_multitrip_enabled,
)


ROOT = Path(__file__).resolve().parents[2]


def test_china81_bundle_runs_through_the_shared_winner_loop() -> None:
    bundle = load_china81_bundle(
        ROOT,
        "cn-jjj-10c-01-V2-LOCATIONS",
    )
    initial = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )

    run = run_winner_kernel_in_memory(
        initial,
        bundle.instance,
        bundle.time_profile,
        config=WinnerKernelConfig(
            seed=1,
            eval_budget=24,
            max_runtime_seconds=5.0,
            require_charging_signal=False,
        ),
        prices=bundle.prices,
        model_config=ModelConfig(),
        customer_home_depot=dict(bundle.customer_home_depot),
    )

    assert run.best_solution is not None
    assert run.evaluations <= 24
    assert run.model_config == ModelConfig().as_metadata()
    assert not check_solution(
        run.best_solution,
        bundle.instance,
        bundle.prices,
    )


def test_china81_mainline_requires_model_config_and_scenario_prices() -> None:
    with pytest.raises(MissingModelConfigError, match="explicit model_config"):
        run_winner_kernel_in_memory(None, None, [], prices=object())
    with pytest.raises(ValueError, match="explicit scenario prices"):
        run_winner_kernel_in_memory(None, None, [], model_config=ModelConfig())


def test_model_config_defaults_on_and_legacy_boundary_preserves_zero_one(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ModelConfig().strict_multitrip is True
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "0")
    assert legacy_model_config_from_environment().strict_multitrip is False
    with model_config_scope(ModelConfig(strict_multitrip=True)):
        assert strict_multitrip_enabled() is True
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")
    assert legacy_model_config_from_environment().strict_multitrip is True
