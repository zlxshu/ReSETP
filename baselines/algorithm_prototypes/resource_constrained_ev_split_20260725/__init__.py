"""Resource-constrained EV-aware Split research prototype."""

from .split_core import (
    ResourceLimitError,
    SegmentChoice,
    SplitResult,
    solve_resource_constrained_split,
)

__all__ = [
    "ResourceLimitError",
    "SegmentChoice",
    "SplitResult",
    "solve_resource_constrained_split",
]
