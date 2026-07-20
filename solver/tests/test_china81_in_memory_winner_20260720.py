from __future__ import annotations

from pathlib import Path

from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_winner_kernel_in_memory,
)
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle


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
        customer_home_depot=dict(bundle.customer_home_depot),
    )

    assert run.best_solution is not None
    assert run.evaluations <= 24
    assert not check_solution(
        run.best_solution,
        bundle.instance,
        bundle.prices,
    )
