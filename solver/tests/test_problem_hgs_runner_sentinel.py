from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    _sentinel_acceptance_classification,
    _sentinel_validation_failures,
)


def test_route_layer_acceptance_without_education_acceptance_passes_sentinel_gate() -> None:
    accepted = {"hgs_population": 2, "route_layer_crossover": 1}

    classification = _sentinel_acceptance_classification(accepted)

    assert classification == {
        "incremental_education": {},
        "full_evaluation": accepted,
    }
    assert _sentinel_validation_failures(
        accepted_actions=accepted,
        sentinel_enabled=True,
        sentinel_evaluations=0,
    ) == ()
    assert _sentinel_validation_failures(
        accepted_actions={"hgs_population": 2, "multi_trip": 1},
        sentinel_enabled=True,
        sentinel_evaluations=0,
    ) == (
        "an accepted education move was not replayed by the full-truth sentinel",
    )
