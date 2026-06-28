from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecodedAction:
    destroy_id: str
    repair_id: str
    q_ratio: float | None
    threshold_ratio: float
    raw: tuple[int, ...]
    control_mode: str = "ppo_full"


@dataclass(frozen=True)
class BlockDecodedAction:
    destroy_id: str
    repair_id: str
    q_ratio: float
    threshold_ratio: float
    exploration_ratio: float
    block_size: int
    raw: tuple[int, ...]
    control_mode: str = "block_ppo"
    candidate_generator: str = "default"
    search_control: str = "continue"


@dataclass(frozen=True)
class LearnedDestroyDecodedAction:
    repair_id: str
    q_ratio: float
    threshold_ratio: float
    block_size: int
    remove_customer_ids: tuple[str, ...]
    raw: tuple[int, ...] = ()
    control_mode: str = "learned_destroy"


@dataclass(frozen=True)
class WorkerRequest:
    request_id: int
    op: str
    action: dict[str, Any]
    current_solution: dict[str, Any] | None = None


@dataclass(frozen=True)
class CandidateResponse:
    request_id: int
    ok: bool
    accepted: bool
    improved_current: bool
    improved_best: bool
    actual_evals: int
    current_obj: float
    best_obj: float
    candidate_obj: float
    violation_count: int
    metrics: dict[str, float] = field(default_factory=dict)
    solution: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    error: str = ""
