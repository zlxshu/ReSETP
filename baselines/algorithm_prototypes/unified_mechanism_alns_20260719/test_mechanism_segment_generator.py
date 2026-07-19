from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mechanism_segment_generator import (  # noqa: E402
    SegmentGeneratorConfig,
    propose_segment_move,
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
DONOR = (
    REPO
    / "baselines/algorithm_prototypes/algo_reset_20260719/"
    "fresh_donor02_mechanism_bundles/"
    "DEV-fullsource-donor02-25c"
)
SINGLE_DEPOT = (
    REPO
    / "models/data_bundle/generated_instances/"
    "L-main_mixed23_archive_20260709/"
    "L-main-vanilla-100c-01"
)


def _fixture(bundle_dir: Path):
    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    solution = annotate_cross_site_services(solution, owners)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=PRICES,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    return bundle, owners, solution, context


def test_mechanism_segment_generator_keeps_distance_worse_move() -> None:
    bundle, owners, source, context = _fixture(DONOR)
    candidate, activity = propose_segment_move(
        source,
        context,
        owners,
        config=SegmentGeneratorConfig(),
    )
    assert candidate is not None
    selected = activity["selected"]
    ledger = activity["ledger"]
    assert selected["segment_length"] >= 2
    assert selected["distance_delta"] > 0.0
    assert selected["local_model_delta"] < 0.0
    assert (
        ledger["distance_worse_model_better_candidates"]
        >= 1
    )
    assert (
        ledger[
            "complete_candidate_evaluations_before_submission"
        ]
        == 0
    )
    assert not check_solution(candidate, bundle.instance, PRICES)
    assert independent_cost(DONOR, candidate, PRICES) < (
        independent_cost(DONOR, source, PRICES)
    )


def test_distance_ablation_vetoes_binding_witness() -> None:
    _, owners, source, context = _fixture(DONOR)
    candidate, activity = propose_segment_move(
        source,
        context,
        owners,
        config=SegmentGeneratorConfig(
            mode="distance",
        ),
    )
    assert candidate is None
    assert activity["selected"] is None
    assert (
        activity["ledger"][
            "complete_candidate_evaluations_before_submission"
        ]
        == 0
    )


def test_nonbinding_single_depot_is_exact_noop() -> None:
    _, owners, source, context = _fixture(SINGLE_DEPOT)
    candidate, activity = propose_segment_move(
        source,
        context,
        owners,
        config=SegmentGeneratorConfig(),
    )
    assert candidate is None
    assert activity["selected"] is None
    assert activity["ledger"]["candidate_build_attempts"] == 0


def test_configuration_rejects_inverted_segment_lengths() -> None:
    try:
        SegmentGeneratorConfig(
            min_segment_length=3,
            max_segment_length=2,
        )
    except ValueError as error:
        assert "min_segment_length" in str(error)
    else:
        raise AssertionError("inverted segment bounds were accepted")
