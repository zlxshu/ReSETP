from __future__ import annotations

from dataclasses import dataclass

from decoder_cache import RouteLocalDecoderCache
from feasible_moves import RawMove, collect_feasible_moves


@dataclass(frozen=True)
class _Skeleton:
    label: str


class _Bundle:
    pass


def test_infeasible_prefix_does_not_fill_feasible_shortlist(monkeypatch):
    moves = [
        RawMove(
            neighborhood="relocate",
            skeleton=_Skeleton(f"s{index}"),
            distance_delta=float(index),
            detail=f"m{index}",
        )
        for index in range(8)
    ]
    monkeypatch.setattr(
        "feasible_moves.solution_signature_hash",
        lambda skeleton: skeleton.label,
    )
    monkeypatch.setattr(
        "feasible_moves.customer_multiset",
        lambda skeleton, bundle: ("C1",),
    )

    def feasibility(skeleton, bundle):
        index = int(skeleton.label[1:])
        if index < 5:
            raise ValueError("infeasible prefix")
        return float(index), 1

    result = collect_feasible_moves(
        moves,
        _Bundle(),
        baseline_customers=("C1",),
        route_local_cache=RouteLocalDecoderCache(),
        inspection_limit=8,
        feasible_limit=2,
        feasibility_function=feasibility,
    )
    assert [move.detail for move in result.moves] == ["m5", "m6"]
    assert result.raw_inspected == 8
    assert result.infeasible_structures == 5


def test_inspection_safety_cap_is_explicit(monkeypatch):
    moves = [
        RawMove(
            neighborhood="swap",
            skeleton=_Skeleton(f"s{index}"),
            distance_delta=float(index),
            detail=f"m{index}",
        )
        for index in range(6)
    ]
    monkeypatch.setattr(
        "feasible_moves.solution_signature_hash",
        lambda skeleton: skeleton.label,
    )
    monkeypatch.setattr(
        "feasible_moves.customer_multiset",
        lambda skeleton, bundle: ("C1",),
    )
    result = collect_feasible_moves(
        moves,
        _Bundle(),
        baseline_customers=("C1",),
        route_local_cache=RouteLocalDecoderCache(),
        inspection_limit=3,
        feasible_limit=2,
        feasibility_function=lambda skeleton, bundle: (1.0, 1),
    )
    assert result.raw_inspected == 3
    assert result.inspection_limit_hit
    assert len(result.moves) == 2
