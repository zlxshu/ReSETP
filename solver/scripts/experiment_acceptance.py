"""Shared result assessment and output helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


NORMAL_PROBLEM_HGS_TERMINATIONS = frozenset({"STOPPED_BY_CALLER"})


@dataclass(frozen=True)
class RunAcceptance:
    accepted: bool
    verdict: str
    failure_reasons: tuple[str, ...]

    def row_fields(self) -> dict[str, Any]:
        return {
            "acceptance_passed": self.accepted,
            "acceptance_verdict": self.verdict,
            "acceptance_failure_reasons": json.dumps(
                self.failure_reasons,
                ensure_ascii=False,
            ),
        }


def assess_run(
    *,
    termination_ok: bool | None,
    feasible_ok: bool | None,
    customers_complete: bool | None,
    demand_complete: bool | None,
    extra_failure_reasons: Iterable[str] = (),
    success_verdict: str = "RUN_COMPLETE",
    failure_verdict: str = "RUN_FAILED",
) -> RunAcceptance:
    checks = (
        (termination_ok, "termination was not normal"),
        (feasible_ok, "complete evaluation was not feasible"),
        (customers_complete, "not all customers were served"),
        (demand_complete, "not all demand was served"),
    )
    reasons = [reason for passed, reason in checks if passed is not True]
    reasons.extend(str(reason) for reason in extra_failure_reasons if str(reason))
    failure_reasons = tuple(dict.fromkeys(reasons))
    accepted = not failure_reasons
    return RunAcceptance(
        accepted=accepted,
        verdict=success_verdict if accepted else failure_verdict,
        failure_reasons=failure_reasons,
    )


def result_exit_code(acceptance: RunAcceptance) -> int:
    return 0 if acceptance.accepted else 2


def row_is_accepted(row: Mapping[str, Any]) -> bool:
    return row.get("acceptance_passed") is True


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def finalize_run_output(
    output: Path,
    *,
    acceptance: RunAcceptance,
    metadata: Mapping[str, Any],
    decision: Mapping[str, Any],
    report_text: str,
    complete_status: str = "COMPLETE",
    failed_status: str = "FAILED",
) -> None:
    metadata_payload = dict(metadata)
    metadata_payload.update(
        {
            "status": complete_status if acceptance.accepted else failed_status,
            "acceptance_passed": acceptance.accepted,
            "acceptance_verdict": acceptance.verdict,
            "acceptance_failure_reasons": list(acceptance.failure_reasons),
        }
    )
    decision_payload = dict(decision)
    decision_payload.update(
        {
            "verdict": acceptance.verdict,
            "accepted": acceptance.accepted,
            "failure_reasons": list(acceptance.failure_reasons),
        }
    )
    _write_json(output / "metadata.json", metadata_payload)
    _write_json(output / "decision.json", decision_payload)
    (output / "report.md").write_text(report_text, encoding="utf-8")
