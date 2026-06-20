from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .schemas import BlockDecodedAction, DecodedAction

from setp_solver.search.winner_operators import WinnerOperatorSet


_OPERATOR_SET = WinnerOperatorSet.create()
DESTROY_IDS = tuple(name for name, _ in _OPERATOR_SET.destroy_ops)
REPAIR_IDS = tuple(name for name, _ in _OPERATOR_SET.repair_ops)
FULL_ACTION_NVECS = (len(DESTROY_IDS), len(REPAIR_IDS), 10, 100)
REDUCED_ACTION_NVECS = (len(DESTROY_IDS), len(REPAIR_IDS), 3, 3)
OPERATOR_ONLY_NVECS = (len(DESTROY_IDS), len(REPAIR_IDS))
MAX_THRESHOLD_RATIO = 0.02
REDUCED_Q_RATIOS = (0.10, 0.25, 0.40)
REDUCED_THRESHOLD_RATIOS = (0.0, 0.005, 0.02)
ALPHA_UCB_CHOICE = "alpha_ucb"
BLOCK_DESTROY_IDS = (*DESTROY_IDS, ALPHA_UCB_CHOICE)
BLOCK_REPAIR_IDS = (*REPAIR_IDS, ALPHA_UCB_CHOICE)
BLOCK_Q_RATIOS = (0.10, 0.16, 0.23, 0.30, 0.40)
BLOCK_THRESHOLD_RATIOS = (0.0, 0.0025, 0.0075, 0.02)
BLOCK_EXPLORATION_RATIOS = (0.0, 0.05, 0.15, 0.30)
BLOCK_ACTION_NVECS = (
    len(BLOCK_DESTROY_IDS),
    len(BLOCK_REPAIR_IDS),
    len(BLOCK_Q_RATIOS),
    len(BLOCK_THRESHOLD_RATIOS),
    len(BLOCK_EXPLORATION_RATIOS),
)


def _coerce_action_component(value: Any) -> int:
    integer_value = int(value)
    if value != integer_value:
        raise ValueError(f"action component must be an integer value: {value!r}")
    return integer_value


def decode_action(raw: Sequence[int], *, base_temperature: float, control_mode: str = "ppo_full") -> DecodedAction:
    _ = base_temperature
    mode = str(control_mode)
    expected_len = 2 if mode in {"operator_only", "kernel_default"} else 4
    if len(raw) != expected_len:
        raise ValueError(f"Expected {expected_len} action components, got {len(raw)}")
    values = [_coerce_action_component(value) for value in raw]
    d_idx, r_idx = values[:2]
    if not 0 <= d_idx < len(DESTROY_IDS):
        raise ValueError(f"destroy index out of range: {d_idx}")
    if not 0 <= r_idx < len(REPAIR_IDS):
        raise ValueError(f"repair index out of range: {r_idx}")
    if mode in {"operator_only", "kernel_default"}:
        return DecodedAction(
            destroy_id=DESTROY_IDS[d_idx],
            repair_id=REPAIR_IDS[r_idx],
            q_ratio=None,
            threshold_ratio=0.0,
            raw=tuple(values),
            control_mode=mode,
        )
    q_idx, t_idx = values[2:]
    if mode == "reduced_full":
        if not 0 <= q_idx < len(REDUCED_Q_RATIOS):
            raise ValueError(f"reduced q index out of range: {q_idx}")
        if not 0 <= t_idx < len(REDUCED_THRESHOLD_RATIOS):
            raise ValueError(f"reduced threshold index out of range: {t_idx}")
        q_ratio = REDUCED_Q_RATIOS[q_idx]
        threshold_ratio = REDUCED_THRESHOLD_RATIOS[t_idx]
    else:
        if not 0 <= q_idx < 10:
            raise ValueError(f"q index out of range: {q_idx}")
        if not 0 <= t_idx < 100:
            raise ValueError(f"threshold index out of range: {t_idx}")
        q_ratio = 0.10 + (0.30 * q_idx / 9.0)
        threshold_ratio = MAX_THRESHOLD_RATIO * t_idx / 99.0
    return DecodedAction(
        destroy_id=DESTROY_IDS[d_idx],
        repair_id=REPAIR_IDS[r_idx],
        q_ratio=float(q_ratio),
        threshold_ratio=float(threshold_ratio),
        raw=tuple(values),
        control_mode=mode,
    )


def decode_block_action(raw: Sequence[int], *, block_size: int = 128) -> BlockDecodedAction:
    if len(raw) != 5:
        raise ValueError(f"Expected 5 block action components, got {len(raw)}")
    values = [_coerce_action_component(value) for value in raw]
    d_idx, r_idx, q_idx, t_idx, exploration_idx = values
    if not 0 <= d_idx < len(BLOCK_DESTROY_IDS):
        raise ValueError(f"block destroy index out of range: {d_idx}")
    if not 0 <= r_idx < len(BLOCK_REPAIR_IDS):
        raise ValueError(f"block repair index out of range: {r_idx}")
    if not 0 <= q_idx < len(BLOCK_Q_RATIOS):
        raise ValueError(f"block q index out of range: {q_idx}")
    if not 0 <= t_idx < len(BLOCK_THRESHOLD_RATIOS):
        raise ValueError(f"block threshold index out of range: {t_idx}")
    if not 0 <= exploration_idx < len(BLOCK_EXPLORATION_RATIOS):
        raise ValueError(f"block exploration index out of range: {exploration_idx}")
    if int(block_size) < 1:
        raise ValueError("block_size must be >= 1")
    return BlockDecodedAction(
        destroy_id=BLOCK_DESTROY_IDS[d_idx],
        repair_id=BLOCK_REPAIR_IDS[r_idx],
        q_ratio=float(BLOCK_Q_RATIOS[q_idx]),
        threshold_ratio=float(BLOCK_THRESHOLD_RATIOS[t_idx]),
        exploration_ratio=float(BLOCK_EXPLORATION_RATIOS[exploration_idx]),
        block_size=int(block_size),
        raw=tuple(values),
    )
