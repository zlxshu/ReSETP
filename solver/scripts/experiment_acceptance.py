"""Shared fail-closed acceptance and five-file package helpers.

Carriers keep ownership of their scientific fields and comparison semantics.
This module only records whether their already-computed checks all passed,
then makes the package status, decision verdict, hashes, and exit code agree.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


FIVE_FILE_PACKAGE = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)

NORMAL_PROBLEM_HGS_TERMINATIONS = frozenset(
    {"STOPPED_BY_CALLER", "CONVERGED_NO_IMPROVEMENT"}
)


@dataclass(frozen=True)
class RunAcceptance:
    """The single acceptance fact consumed by writers and controllers."""

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
    audit_ok: bool | None = True,
    extra_failure_reasons: Iterable[str] = (),
    success_verdict: str = "RUN_COMPLETE",
    failure_verdict: str = "RUN_FAILED",
) -> RunAcceptance:
    """Combine carrier-owned checks without inventing thresholds or tolerances."""

    checks = (
        (termination_ok, "termination was not normal"),
        (feasible_ok, "complete evaluation was not feasible"),
        (customers_complete, "not all customers were served"),
        (demand_complete, "not all demand was served"),
        (audit_ok, "required audit did not pass"),
    )
    reasons = [reason for passed, reason in checks if passed is not True]
    reasons.extend(str(reason) for reason in extra_failure_reasons if str(reason))
    deduplicated = tuple(dict.fromkeys(reasons))
    accepted = not deduplicated
    return RunAcceptance(
        accepted=accepted,
        verdict=success_verdict if accepted else failure_verdict,
        failure_reasons=deduplicated,
    )


def package_exit_code(acceptance: RunAcceptance) -> int:
    return 0 if acceptance.accepted else 2


def row_is_accepted(row: Mapping[str, Any]) -> bool:
    return row.get("acceptance_passed") is True


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_text(
        path,
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def finalize_five_file_package(
    output: Path,
    *,
    acceptance: RunAcceptance,
    metadata: Mapping[str, Any],
    decision: Mapping[str, Any],
    report_text: str,
    complete_status: str = "COMPLETE",
    failed_status: str = "FAILED",
) -> dict[str, str]:
    """Write and verify the canonical five files after raw rows are durable."""

    raw_runs = output / "raw_runs.csv"
    if not raw_runs.is_file() or raw_runs.stat().st_size == 0:
        raise RuntimeError(f"missing nonempty raw_runs.csv: {output}")

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
    _atomic_text(output / "report.md", report_text)

    hashes = {
        str(path.relative_to(output)): file_sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and path.name != "DONE"
        and not path.name.startswith("._")
    }
    _write_json(output / "artifact_hashes.json", hashes)

    missing = [
        name
        for name in FIVE_FILE_PACKAGE
        if not (output / name).is_file() or (output / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(f"incomplete five-file package {output}: {missing}")
    return hashes


def validate_five_file_package(
    output: Path,
    *,
    expected_success_verdict: str | None = None,
    require_accepted: bool = True,
) -> dict[str, Any]:
    """Recompute package hashes and, by default, reject failed verdicts."""

    missing = [
        name
        for name in FIVE_FILE_PACKAGE
        if not (output / name).is_file() or (output / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(f"incomplete five-file package {output}: {missing}")
    metadata = json.loads((output / "metadata.json").read_text("utf-8"))
    decision = json.loads((output / "decision.json").read_text("utf-8"))
    recorded_hashes = json.loads(
        (output / "artifact_hashes.json").read_text("utf-8")
    )
    actual_hashes = {
        str(path.relative_to(output)): file_sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and path.name != "DONE"
        and not path.name.startswith("._")
    }
    if recorded_hashes != actual_hashes:
        missing_keys = sorted(set(actual_hashes) - set(recorded_hashes))
        extra_keys = sorted(set(recorded_hashes) - set(actual_hashes))
        changed_keys = sorted(
            key
            for key in set(recorded_hashes) & set(actual_hashes)
            if recorded_hashes[key] != actual_hashes[key]
        )
        raise RuntimeError(
            "artifact hash map mismatch: "
            f"missing={missing_keys}, extra={extra_keys}, changed={changed_keys}"
        )
    if require_accepted:
        if metadata.get("acceptance_passed") is not True:
            raise RuntimeError(f"package metadata is not accepted: {output}")
        if decision.get("accepted") is not True:
            raise RuntimeError(f"package decision is not accepted: {output}")
        if (
            expected_success_verdict is not None
            and decision.get("verdict") != expected_success_verdict
        ):
            raise RuntimeError(
                f"unexpected decision verdict in {output}: "
                f"{decision.get('verdict')!r}"
            )
    return {
        "metadata": metadata,
        "decision": decision,
        "artifact_hashes": recorded_hashes,
    }
