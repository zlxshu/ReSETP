from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
UNIFIED = (
    REPO
    / "baselines/algorithm_prototypes/unified_mechanism_alns_20260719"
)
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    UNIFIED,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bounded_segment_generator import (  # noqa: E402
    BoundedSegmentGeneratorConfig,
    _round_robin_union,
    propose_bounded_segment_move,
)
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import (  # noqa: E402
    EvalBudget,
    EvaluationContext,
)
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
)


PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
BINDING = (
    REPO
    / "baselines/algorithm_prototypes/algo_reset_20260719/"
    "fresh_donor02_mechanism_bundles/"
    "DEV-fullsource-donor02-25c"
)
NONBINDING = (
    REPO
    / "models/data_bundle/generated_instances/"
    "L-main_mixed23_archive_20260709/"
    "L-main-vanilla-100c-01"
)


def _fixture(bundle_dir: Path):
    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    source = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    source = annotate_cross_site_services(source, owners)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=PRICES,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    return bundle, owners, source, context


def test_bounded_mechanism_keeps_non_distance_improvement() -> None:
    bundle, owners, source, context = _fixture(BINDING)
    candidate, activity = propose_bounded_segment_move(
        source,
        context,
        owners,
        config=BoundedSegmentGeneratorConfig(),
    )
    assert candidate is not None
    selected = activity["selected"]
    ledger = activity["ledger"]
    assert selected["segment_length"] in {2, 3}
    assert selected["distance_delta"] > 0.0
    assert selected["local_model_delta"] < 0.0
    assert not check_solution(candidate, bundle.instance, PRICES)
    assert independent_cost(BINDING, candidate, PRICES) < (
        independent_cost(BINDING, source, PRICES)
    )
    assert ledger["source_segments_shortlisted"] <= 64
    assert ledger["maximum_positions_for_one_source"] <= 6
    assert ledger["candidate_build_attempts"] <= 64 * 6
    assert ledger["exact_candidates_shortlisted"] <= 48
    assert ledger["completion_candidates_screened"] <= 12
    assert (
        ledger["complete_candidate_evaluations_before_submission"]
        == 0
    )


def test_distance_ablation_does_not_use_local_exact_screening() -> None:
    _, owners, source, context = _fixture(BINDING)
    _, activity = propose_bounded_segment_move(
        source,
        context,
        owners,
        config=BoundedSegmentGeneratorConfig(mode="distance"),
    )
    ledger = activity["ledger"]
    assert ledger["source_segments_shortlisted"] <= 64
    assert ledger["maximum_positions_for_one_source"] <= 6
    assert ledger["candidate_build_attempts"] <= 64 * 6
    assert (
        ledger["complete_candidate_evaluations_before_submission"]
        == 0
    )


def test_single_depot_is_exact_noop() -> None:
    _, owners, source, context = _fixture(NONBINDING)
    candidate, activity = propose_bounded_segment_move(
        source,
        context,
        owners,
        config=BoundedSegmentGeneratorConfig(),
    )
    assert candidate is None
    assert activity["selected"] is None
    assert activity["ledger"]["candidate_build_attempts"] == 0


def test_round_robin_union_cannot_be_monopolised_by_one_view() -> None:
    selected, counts = _round_robin_union(
        {
            "geometry": [1, 2, 3, 4],
            "mechanism": [5, 6, 7, 8],
            "diversity": [9, 10, 11, 12],
        },
        6,
        key=int,
    )
    assert selected == [1, 5, 9, 2, 6, 10]
    assert counts == {
        "geometry": 2,
        "mechanism": 2,
        "diversity": 2,
    }


def test_invalid_bounds_are_rejected() -> None:
    for kwargs, fragment in (
        (
            {
                "min_segment_length": 3,
                "max_segment_length": 2,
            },
            "min_segment_length",
        ),
        ({"max_source_segments": 0}, "max_source_segments"),
        ({"max_positions_per_source": 0}, "max_positions_per_source"),
    ):
        try:
            BoundedSegmentGeneratorConfig(**kwargs)
        except ValueError as error:
            assert fragment in str(error)
        else:
            raise AssertionError(f"invalid config accepted: {kwargs}")
