"""Auditable budget and bidirectional-transfer contracts for COOP-HGS-RR."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from typing import Any


class AlgorithmArm(str, Enum):
    HGS = "A_HGS"
    RUIN_RECREATE = "B_RR"
    COOPERATIVE = "AB_COOP_HGS_RR"


class CandidateSource(str, Enum):
    SHARED_INITIAL = "SHARED_INITIAL"
    HGS_ARCHIVE = "HGS_ARCHIVE"
    RUIN_RECREATE = "RUIN_RECREATE"
    HGS_DESCENDANT = "HGS_DESCENDANT"


class TransferDirection(str, Enum):
    HGS_TO_RR = "HGS_TO_RR"
    RR_TO_HGS = "RR_TO_HGS"


@dataclass(frozen=True)
class CompleteEvaluationRecord:
    index: int
    arm: AlgorithmArm
    signature: str
    source: CandidateSource
    feasible: bool
    objective: float | None
    violation_count: int
    duplicate_of_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CompleteEvaluationLedger:
    """Count every candidate submitted to the shared complete evaluator.

    Infeasible and duplicate candidates consume budget as required by the
    frozen comparison contract.  This class never scores a solution itself.
    """

    def __init__(self, *, arm: AlgorithmArm, limit: int) -> None:
        if limit < 1:
            raise ValueError("complete-evaluation limit must be positive")
        self.arm = arm
        self.limit = int(limit)
        self._records: list[CompleteEvaluationRecord] = []
        self._first_index_by_signature: dict[str, int] = {}

    @property
    def consumed(self) -> int:
        return len(self._records)

    @property
    def remaining(self) -> int:
        return self.limit - self.consumed

    @property
    def records(self) -> tuple[CompleteEvaluationRecord, ...]:
        return tuple(self._records)

    def register(
        self,
        *,
        signature: str,
        source: CandidateSource,
        feasible: bool,
        objective: float | None,
        violation_count: int,
        metadata: dict[str, Any] | None = None,
    ) -> CompleteEvaluationRecord:
        if self.remaining <= 0:
            raise RuntimeError(
                f"complete-evaluation budget exhausted for {self.arm.value}"
            )
        normalized_signature = str(signature).strip()
        if not normalized_signature:
            raise ValueError("candidate signature must be non-empty")
        if feasible:
            if objective is None or not math.isfinite(float(objective)):
                raise ValueError(
                    "feasible candidate requires a finite objective"
                )
            if int(violation_count) != 0:
                raise ValueError(
                    "feasible candidate cannot carry violations"
                )
        elif int(violation_count) < 1:
            raise ValueError(
                "infeasible candidate must report at least one violation"
            )
        index = self.consumed + 1
        duplicate = self._first_index_by_signature.get(
            normalized_signature
        )
        record = CompleteEvaluationRecord(
            index=index,
            arm=self.arm,
            signature=normalized_signature,
            source=source,
            feasible=bool(feasible),
            objective=(
                None if objective is None else float(objective)
            ),
            violation_count=int(violation_count),
            duplicate_of_index=duplicate,
            metadata=dict(metadata or {}),
        )
        self._records.append(record)
        self._first_index_by_signature.setdefault(
            normalized_signature,
            index,
        )
        return record

    def assert_exactly_closed(self) -> None:
        if self.consumed != self.limit:
            raise RuntimeError(
                "complete-evaluation ledger not closed: "
                f"arm={self.arm.value}, consumed={self.consumed}, "
                f"expected={self.limit}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm.value,
            "limit": self.limit,
            "consumed": self.consumed,
            "remaining": self.remaining,
            "feasible": sum(row.feasible for row in self._records),
            "infeasible": sum(
                not row.feasible for row in self._records
            ),
            "duplicates": sum(
                row.duplicate_of_index is not None
                for row in self._records
            ),
            "records": [
                {
                    **row.__dict__,
                    "arm": row.arm.value,
                    "source": row.source.value,
                }
                for row in self._records
            ],
        }


@dataclass(frozen=True)
class TransferRecord:
    sequence: int
    direction: TransferDirection
    parent_signature: str
    child_signature: str
    parent_objective: float
    child_objective: float
    complete_evaluation_index: int
    accepted_into_next_hgs_epoch: bool
    next_hgs_epoch: int | None


@dataclass(frozen=True)
class HgsDescendantRecord:
    epoch: int
    injected_rr_signature: str
    descendant_signature: str
    injected_objective: float
    descendant_objective: float
    complete_evaluation_index: int


class HybridLineageLedger:
    """Prove that A+B used two-way search transfer, not final selection."""

    def __init__(self) -> None:
        self._transfers: list[TransferRecord] = []
        self._descendants: list[HgsDescendantRecord] = []

    @property
    def transfers(self) -> tuple[TransferRecord, ...]:
        return tuple(self._transfers)

    @property
    def descendants(self) -> tuple[HgsDescendantRecord, ...]:
        return tuple(self._descendants)

    def add_transfer(
        self,
        *,
        direction: TransferDirection,
        parent_signature: str,
        child_signature: str,
        parent_objective: float,
        child_objective: float,
        complete_evaluation_index: int,
        accepted_into_next_hgs_epoch: bool,
        next_hgs_epoch: int | None,
    ) -> TransferRecord:
        if parent_signature == child_signature:
            raise ValueError("transfer must change the solution signature")
        if complete_evaluation_index < 1:
            raise ValueError("complete evaluation index must be positive")
        if direction == TransferDirection.RR_TO_HGS:
            if accepted_into_next_hgs_epoch and (
                next_hgs_epoch is None or next_hgs_epoch < 1
            ):
                raise ValueError(
                    "accepted RR-to-HGS transfer requires a next epoch"
                )
        elif accepted_into_next_hgs_epoch:
            raise ValueError(
                "HGS-to-RR transfer cannot be marked as HGS injection"
            )
        record = TransferRecord(
            sequence=len(self._transfers) + 1,
            direction=direction,
            parent_signature=parent_signature,
            child_signature=child_signature,
            parent_objective=float(parent_objective),
            child_objective=float(child_objective),
            complete_evaluation_index=int(
                complete_evaluation_index
            ),
            accepted_into_next_hgs_epoch=bool(
                accepted_into_next_hgs_epoch
            ),
            next_hgs_epoch=next_hgs_epoch,
        )
        self._transfers.append(record)
        return record

    def add_hgs_descendant(
        self,
        *,
        epoch: int,
        injected_rr_signature: str,
        descendant_signature: str,
        injected_objective: float,
        descendant_objective: float,
        complete_evaluation_index: int,
    ) -> HgsDescendantRecord:
        if epoch < 1 or complete_evaluation_index < 1:
            raise ValueError("epoch and evaluation index must be positive")
        if injected_rr_signature == descendant_signature:
            raise ValueError(
                "HGS descendant must differ from injected RR solution"
            )
        record = HgsDescendantRecord(
            epoch=int(epoch),
            injected_rr_signature=injected_rr_signature,
            descendant_signature=descendant_signature,
            injected_objective=float(injected_objective),
            descendant_objective=float(descendant_objective),
            complete_evaluation_index=int(
                complete_evaluation_index
            ),
        )
        self._descendants.append(record)
        return record

    def cooperative_gain_evidence_count(
        self,
        *,
        tolerance: float = 1.0e-9,
    ) -> int:
        accepted = {
            (
                row.child_signature,
                row.next_hgs_epoch,
            )
            for row in self._transfers
            if row.direction == TransferDirection.RR_TO_HGS
            and row.accepted_into_next_hgs_epoch
        }
        return sum(
            (row.injected_rr_signature, row.epoch) in accepted
            and row.descendant_objective
            < row.injected_objective - tolerance
            for row in self._descendants
        )

    def assert_genuine_cooperation(
        self,
        *,
        tolerance: float = 1.0e-9,
    ) -> None:
        directions = {row.direction for row in self._transfers}
        if TransferDirection.HGS_TO_RR not in directions:
            raise RuntimeError("missing HGS-to-RR transfer")
        if TransferDirection.RR_TO_HGS not in directions:
            raise RuntimeError("missing RR-to-HGS transfer")
        if not any(
            row.direction == TransferDirection.RR_TO_HGS
            and row.accepted_into_next_hgs_epoch
            for row in self._transfers
        ):
            raise RuntimeError(
                "RR solution was never injected into a later HGS epoch"
            )
        if self.cooperative_gain_evidence_count(
            tolerance=tolerance
        ) < 1:
            raise RuntimeError(
                "no post-injection HGS descendant improved its RR parent"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "transfers": [
                {
                    **row.__dict__,
                    "direction": row.direction.value,
                }
                for row in self._transfers
            ],
            "descendants": [
                row.__dict__ for row in self._descendants
            ],
            "cooperative_gain_evidence_count": (
                self.cooperative_gain_evidence_count()
            ),
        }


@dataclass(frozen=True)
class DecoderCacheKey:
    """Fail-closed cache key for route completion and mechanism decoding."""

    instance_id: str
    date: str
    region: str
    home_depot_id: str
    vehicle_type: str
    node_sequence: tuple[str, ...]
    dynamic_state_hash: str
    runtime_parameter_authority: str
    fleet_authority: str

    def digest(self) -> str:
        payload = json.dumps(
            self.__dict__,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
