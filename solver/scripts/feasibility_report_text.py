"""Shared wording for structured full-evaluation feasibility results."""

from __future__ import annotations


def _format_full_evaluation_result(
    *,
    feasible: bool,
    violation_count: int,
) -> str:
    status = "可行" if feasible else "不可行"
    return f"完整评价判定{status}，违规数为 {violation_count}"
