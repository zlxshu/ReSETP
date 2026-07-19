"""Independent exhaustive oracle for the pair-resplit behaviour fixtures.

This module intentionally does not import the candidate solver.  It enumerates
the frozen two-route sequence/cut family again, constructs complete CV
solutions, and uses the authoritative ReSETP checker and evaluator.  Its
purpose is to detect a fixture or ranking bug before the one-shot behaviour
gate, not to act as a search component.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Iterable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mechanism_priced_pair_resplit_fixtures import (  # noqa: E402
    PairResplitFixture,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.search.evaluation import model_cost  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402
from v7_responsibility_solver import annotate_cross_site_services  # noqa: E402


@dataclass(frozen=True)
class OracleRecord:
    left_customers: tuple[str, ...]
    right_customers: tuple[str, ...]
    distance_score: float
    mechanism_score: float
    complete_cost: float
    solution_sha256: str


@dataclass(frozen=True)
class OracleResult:
    records: tuple[OracleRecord, ...]
    distance_order: tuple[OracleRecord, ...]
    mechanism_order: tuple[OracleRecord, ...]
    best_distance_top4: OracleRecord | None
    best_mechanism_top4: OracleRecord | None
    global_best: OracleRecord | None
    candidate_set_sha256: str


def exhaustive_fixture_oracle(
    fixture: PairResplitFixture,
) -> OracleResult:
    """Enumerate every unique frozen cut for the fixture's only route pair."""

    if len(fixture.source.routes) != 2:
        raise ValueError("fixture oracle requires exactly two routes")
    context = fixture.context
    owners = context.customer_home_depot or {}
    left_route, right_route = fixture.source.routes
    left_source = _customers(left_route, context.instance)
    right_source = _customers(right_route, context.instance)
    original = (left_source, right_source)
    records: list[OracleRecord] = []
    seen_cuts: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for sequence in _unique_sequences(left_source, right_source):
        for cut in range(1, len(sequence)):
            pair = (sequence[:cut], sequence[cut:])
            if pair == original or pair in seen_cuts:
                continue
            seen_cuts.add(pair)
            candidate = annotate_cross_site_services(
                Solution(
                    routes=[
                        Route(
                            "CV_ORACLE_LEFT#T1",
                            "cv",
                            left_route.home_depot_id,
                            [
                                left_route.home_depot_id,
                                *pair[0],
                                left_route.home_depot_id,
                            ],
                        ),
                        Route(
                            "CV_ORACLE_RIGHT#T1",
                            "cv",
                            right_route.home_depot_id,
                            [
                                right_route.home_depot_id,
                                *pair[1],
                                right_route.home_depot_id,
                            ],
                        ),
                    ]
                ),
                owners,
            )
            if check_solution(
                candidate,
                context.instance,
                context.prices,
            ):
                continue
            mechanism_score = (
                _route_local_cost(
                    left_route.home_depot_id,
                    pair[0],
                    fixture,
                )
                + _route_local_cost(
                    right_route.home_depot_id,
                    pair[1],
                    fixture,
                )
                + _cross_site_cost(
                    left_route.home_depot_id,
                    pair[0],
                    fixture,
                )
                + _cross_site_cost(
                    right_route.home_depot_id,
                    pair[1],
                    fixture,
                )
            )
            records.append(
                OracleRecord(
                    left_customers=pair[0],
                    right_customers=pair[1],
                    distance_score=(
                        _route_distance(
                            left_route.home_depot_id,
                            pair[0],
                            context.instance,
                        )
                        + _route_distance(
                            right_route.home_depot_id,
                            pair[1],
                            context.instance,
                        )
                    ),
                    mechanism_score=float(mechanism_score),
                    complete_cost=float(model_cost(candidate, context)),
                    solution_sha256=_solution_sha256(candidate),
                )
            )
    records = sorted(
        records,
        key=lambda item: (
            item.left_customers,
            item.right_customers,
        ),
    )
    distance_order = tuple(
        sorted(
            records,
            key=lambda item: (
                float(item.distance_score),
                item.left_customers,
                item.right_customers,
            ),
        )
    )
    mechanism_order = tuple(
        sorted(
            records,
            key=lambda item: (
                float(item.mechanism_score),
                item.left_customers,
                item.right_customers,
            ),
        )
    )
    distance_top4 = distance_order[:4]
    mechanism_top4 = mechanism_order[:4]
    return OracleResult(
        records=tuple(records),
        distance_order=distance_order,
        mechanism_order=mechanism_order,
        best_distance_top4=(
            None
            if not distance_top4
            else min(
                distance_top4,
                key=lambda item: (
                    float(item.complete_cost),
                    item.left_customers,
                    item.right_customers,
                ),
            )
        ),
        best_mechanism_top4=(
            None
            if not mechanism_top4
            else min(
                mechanism_top4,
                key=lambda item: (
                    float(item.complete_cost),
                    item.left_customers,
                    item.right_customers,
                ),
            )
        ),
        global_best=(
            None
            if not records
            else min(
                records,
                key=lambda item: (
                    float(item.complete_cost),
                    item.left_customers,
                    item.right_customers,
                ),
            )
        ),
        candidate_set_sha256=_candidate_set_sha256(records),
    )


def _unique_sequences(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    sequences: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for first, second in ((left, right), (right, left)):
        for reverse_first in (False, True):
            for reverse_second in (False, True):
                first_part = (
                    tuple(reversed(first)) if reverse_first else first
                )
                second_part = (
                    tuple(reversed(second)) if reverse_second else second
                )
                sequence = (*first_part, *second_part)
                if sequence in seen:
                    continue
                seen.add(sequence)
                sequences.append(sequence)
    return tuple(sequences)


def _customers(route: Route, instance: object) -> tuple[str, ...]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return tuple(
        node_id
        for node_id in route.node_sequence
        if node_lookup[node_id].node_type.lower() == "c"
    )


def _route_distance(
    home_depot_id: str,
    customers: Iterable[str],
    instance: object,
) -> float:
    sequence = (home_depot_id, *customers, home_depot_id)
    return float(
        sum(
            instance.distance(left, right)
            for left, right in zip(sequence, sequence[1:])
        )
    )


def _route_local_cost(
    home_depot_id: str,
    customers: tuple[str, ...],
    fixture: PairResplitFixture,
) -> float:
    route = Route(
        "CV_ORACLE_LOCAL#T1",
        "cv",
        home_depot_id,
        [home_depot_id, *customers, home_depot_id],
    )
    return float(
        model_cost(
            Solution(routes=[route]),
            fixture.context,
        )
    )


def _cross_site_cost(
    home_depot_id: str,
    customers: tuple[str, ...],
    fixture: PairResplitFixture,
) -> float:
    owners = fixture.context.customer_home_depot or {}
    prices = fixture.context.prices
    unit = (
        float(prices["cross_site_cost"])
        if isinstance(prices, dict)
        else float(getattr(prices, "cross_site_cost"))
    )
    return float(
        unit
        * sum(
            owners.get(customer) is not None
            and owners[customer] != home_depot_id
            for customer in customers
        )
    )


def _solution_sha256(solution: Solution) -> str:
    payload = json.dumps(
        asdict(solution),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _candidate_set_sha256(records: list[OracleRecord]) -> str:
    payload = json.dumps(
        [
            {
                "left_customers": list(record.left_customers),
                "right_customers": list(record.right_customers),
            }
            for record in records
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
