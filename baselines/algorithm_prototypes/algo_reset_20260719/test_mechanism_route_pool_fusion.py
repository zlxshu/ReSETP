from __future__ import annotations

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
MECHANISM_DIR = HERE.parent / "mechanism_hgs_alns_20260718"
for path in (HERE, MECHANISM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mechanism_route_pool_fusion import route_pool_records  # noqa: E402
from mechanism_normalized_alns import (  # noqa: E402
    run_mechanism_normalized_alns,
)
from prototype import run_pure_alns  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel import alns_core  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402


REPO = HERE.parents[2]
BUNDLE = (
    REPO
    / "models/data_bundle/generated_instances/L-main_mixed23_archive_20260709"
    / "L-main-multidepot-10c-01"
)


def test_route_pool_records_cover_parent_customers() -> None:
    result = run_pure_alns(
        BUNDLE,
        seed=1,
        eval_budget=0,
        prices=DEFAULT_PRICES,
    )
    records = route_pool_records(
        BUNDLE,
        result.best_solution,
        source="test",
        prices=DEFAULT_PRICES,
    )
    covered = set().union(*(record.customers for record in records))
    assert covered
    assert len(covered) == 10
    assert all(record.source == "test" for record in records)
    assert all(record.additive_score >= 0.0 for record in records)


def test_mechanism_normalized_alns_closes_budget_and_restores_patch() -> None:
    original = alns_core.score_search_candidate
    result = run_mechanism_normalized_alns(
        BUNDLE,
        seed=1,
        eval_budget=5,
        prices=DEFAULT_PRICES,
    )
    assert result.evaluations == 5
    assert result.feasible
    assert result.mechanism_activity["normalizer_calls"] > 0
    assert result.mechanism_activity["normalizer_improvements"] > 0
    assert alns_core.score_search_candidate is original
