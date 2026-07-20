from __future__ import annotations

from pathlib import Path

from hybrid import (
    run_adaptive_multiview_hybrid,
    run_homogeneous_hgs_alns_ensemble,
    run_multiview_mechanism_hybrid,
    run_project_alns,
    run_staged_mechanism_hybrid,
)
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import (
    complete_china81_route_skeleton,
    exact_china81_score,
)


ROOT = Path(__file__).resolve().parents[3]
INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"


def _fixture():
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    skeleton = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    initial = complete_china81_route_skeleton(skeleton, bundle)
    return bundle, initial


def test_project_alns_uses_in_memory_instance_and_shared_completion() -> None:
    bundle, initial = _fixture()

    run = run_project_alns(
        bundle,
        initial.solution,
        seed=1,
        runtime_seconds=0.10,
        mechanism_mode=False,
        eval_budget=100,
    )

    objective, _, violations = exact_china81_score(
        run.completion.solution,
        bundle,
    )
    assert not violations
    assert objective == run.completion.objective
    assert run.evaluations <= 100


def test_staged_hybrid_never_discards_its_hgs_incumbent() -> None:
    bundle, initial = _fixture()

    run = run_staged_mechanism_hybrid(
        bundle,
        initial.solution,
        seed=1,
        runtime_seconds=0.20,
        hgs_share=0.70,
    )

    objective, _, violations = exact_china81_score(
        run.solution,
        bundle,
    )
    assert not violations
    assert objective == run.completion.objective
    assert objective <= run.hgs_stage.completion.objective + 1.0e-9
    assert run.stats["algorithm"] == "PMA-HGS-ALNS-VNS"


def test_multiview_hybrid_retains_every_population_elite() -> None:
    bundle, initial = _fixture()

    run = run_multiview_mechanism_hybrid(
        bundle,
        initial.solution,
        seed=1,
        population_seconds=0.10,
        alns_seconds=0.05,
    )

    objective, _, violations = exact_china81_score(
        run.solution,
        bundle,
    )
    assert not violations
    assert objective == run.completion.objective
    assert objective <= min(
        view.completion.objective
        for view in run.view_runs.values()
    ) + 1.0e-9
    assert run.stats["algorithm"] == "MVHGS-ALNS"


def test_homogeneous_control_uses_the_same_population_budget() -> None:
    bundle, initial = _fixture()

    run = run_homogeneous_hgs_alns_ensemble(
        bundle,
        initial.solution,
        base_seed=1,
        route_proxy_mode="cv_only",
        population_seconds=0.10,
        alns_seconds=0.05,
        population_count=3,
        max_workers=3,
    )

    objective, _, violations = exact_china81_score(
        run.solution,
        bundle,
    )
    assert not violations
    assert objective == run.completion.objective
    assert len(run.population_runs) == 3
    assert objective <= min(
        item.completion.objective
        for item in run.population_runs
    ) + 1.0e-9


def test_adaptive_multiview_reallocates_equal_hgs_compute() -> None:
    bundle, initial = _fixture()

    run = run_adaptive_multiview_hybrid(
        bundle,
        initial.solution,
        base_seed=1,
        population_seconds=0.10,
        alns_seconds=0.05,
        scout_share=0.20,
        exploitation_population_count=3,
        max_workers=3,
    )

    objective, _, violations = exact_china81_score(
        run.solution,
        bundle,
    )
    assert not violations
    assert objective == run.completion.objective
    assert len(run.scout_runs) == 3
    assert len(run.exploitation_runs) == 3
    assert run.stats["hgs_cpu_search_seconds"] == 0.30
    assert objective <= min(
        *(
            item.completion.objective
            for item in run.scout_runs.values()
        ),
        *(
            item.completion.objective
            for item in run.exploitation_runs
        ),
    ) + 1.0e-9
