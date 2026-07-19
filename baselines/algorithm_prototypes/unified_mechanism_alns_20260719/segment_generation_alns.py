"""One continuous ALNS with an optional generation-side segment controller."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Literal


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_signature_hash  # noqa: E402
from mechanism_segment_generator import (  # noqa: E402
    SegmentGenerationController,
    SegmentGeneratorConfig,
)
from prototype import ArmResult, independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    _search_policy_for_instance,
    winner_variant_flags,
)
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from terminal_completion import apply_terminal_completion  # noqa: E402


ArmMode = Literal["disabled", "mechanism", "distance"]


@dataclass(frozen=True)
class SegmentAlnsConfig:
    total_eval_budget: int = 100
    runtime_cap_seconds: float = 3600.0
    mode: ArmMode = "mechanism"
    assessment_interval: int = 20
    cooldown_evaluations: int = 100
    min_segment_length: int = 2
    max_segment_length: int = 3
    max_source_segments: int = 10_000
    apply_terminal_completion: bool = True

    def __post_init__(self) -> None:
        if int(self.total_eval_budget) < 0:
            raise ValueError("total_eval_budget must be non-negative")
        if float(self.runtime_cap_seconds) <= 0.0:
            raise ValueError("runtime_cap_seconds must be positive")
        if self.mode not in {"disabled", "mechanism", "distance"}:
            raise ValueError(f"unknown arm mode: {self.mode}")


def run_segment_generation_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: SegmentAlnsConfig | None = None,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run one same-loop control, mechanism, or distance-ablation arm."""

    cfg = config or SegmentAlnsConfig()
    bundle = load_search_bundle(bundle_dir)
    policy = _search_policy_for_instance(
        bundle.instance,
        require_charging_signal=False,
    )
    warm = initial_solution or build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    owners = infer_customer_home_depots(bundle.instance)
    controller = None
    if cfg.mode != "disabled":
        controller = SegmentGenerationController(
            SegmentGeneratorConfig(
                mode=cfg.mode,
                min_segment_length=int(cfg.min_segment_length),
                max_segment_length=int(cfg.max_segment_length),
                max_source_segments=int(cfg.max_source_segments),
                assessment_interval=int(cfg.assessment_interval),
                cooldown_evaluations=int(
                    cfg.cooldown_evaluations
                ),
                apply_route_local_completion=True,
            )
        )
    kernel_config = WinnerKernelConfig(
        seed=int(seed),
        eval_budget=int(cfg.total_eval_budget),
        max_runtime_seconds=float(cfg.runtime_cap_seconds),
        require_charging_signal=False,
        split_selector_rng=False,
    )
    flags = winner_variant_flags(include_route_elimination=False)

    started = time.perf_counter()
    run = _run_winner_kernel_loop(
        warm,
        bundle.instance,
        bundle.carbon_profile,
        config=kernel_config,
        prices=prices,
        variant_flags=flags,
        policy=policy,
        customer_home_depot=owners,
        mechanism_controller=controller,
    )
    raw_elapsed = time.perf_counter() - started
    budget = int(cfg.total_eval_budget)
    operator_counts = dict(run.operator_counts)
    score_counts = dict(operator_counts.get("score_counts", {}))
    selector = dict(operator_counts.get("selector", {}))
    mechanism = dict(
        operator_counts.get("mechanism_prescriptions", {})
    )
    if not (
        int(run.evaluations)
        == int(run.candidate_scores)
        == int(score_counts.get("candidate", 0))
        == int(run.actual_moves)
        == int(selector.get("selection_count", 0))
        == budget
    ):
        raise RuntimeError(
            "segment-generation complete-candidate ledger did not close"
        )
    if not bool(selector.get("selection_count_closed", False)):
        raise RuntimeError(
            "segment-generation selector count did not close"
        )

    mechanism_evaluations = sum(
        int(value)
        for value in dict(
            mechanism.get("complete_candidate_evaluations", {})
        ).values()
    )
    mechanism_moves = int(
        selector.get("mechanism_prescription_count", 0)
    )
    if mechanism_evaluations != mechanism_moves:
        raise RuntimeError(
            "segment-generation move and evaluation ledgers disagree"
        )
    if (
        int(selector.get("selector_sample_count", 0))
        + mechanism_moves
        != budget
    ):
        raise RuntimeError(
            "generic plus segment-generation moves do not close budget"
        )

    raw_solution = run.best_solution
    raw_cost = independent_cost(bundle_dir, raw_solution, prices)
    if abs(float(raw_cost) - float(run.best_obj)) > 1.0e-7:
        raise RuntimeError(
            f"raw objective replay mismatch: {run.best_obj} != {raw_cost}"
        )

    completion_started = time.perf_counter()
    if cfg.apply_terminal_completion:
        completed = apply_terminal_completion(
            bundle_dir,
            raw_solution,
            prices=prices,
        )
        if not completed.feasible:
            raise RuntimeError(
                "segment-generation terminal completion infeasible"
            )
        final_solution = completed.solution
        final_cost = float(completed.cost)
        completion_activity = dict(completed.activity)
        selected_branch = str(completed.selected_branch)
    else:
        final_solution = raw_solution
        final_cost = float(raw_cost)
        completion_activity = {
            "full_solution_replays": 0,
            "disabled": True,
        }
        selected_branch = "disabled"
    completion_elapsed = time.perf_counter() - completion_started

    replay = independent_cost(
        bundle_dir,
        final_solution,
        prices,
    )
    if abs(float(final_cost) - float(replay)) > 1.0e-7:
        raise RuntimeError("final objective replay mismatch")
    violations = check_solution(
        final_solution,
        bundle.instance,
        prices,
    )
    if violations:
        raise RuntimeError(
            f"segment-generation final infeasible: {violations[:8]}"
        )

    history_payload = [
        {
            key: row[key]
            for key in ("eval", "best_cost", "best_obj", "operator")
            if key in row
        }
        for row in run.history
    ]
    return ArmResult(
        algorithm={
            "disabled": "continuous_v7_equivalent_control",
            "mechanism": "segment_generation_mechanism_alns",
            "distance": "segment_generation_distance_ablation",
        }[cfg.mode],
        best_solution=final_solution,
        best_cost=float(replay),
        evaluations=int(run.evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(final_solution.routes),
        feasible=True,
        mechanism_activity={
            "continuous_main_search": True,
            "search_loop_count": 1,
            "search_restart_count": 0,
            "mode": cfg.mode,
            "complete_search_candidate_evaluations": int(
                run.evaluations
            ),
            "generic_candidate_evaluations": int(
                budget - mechanism_evaluations
            ),
            "segment_candidate_evaluations": int(
                mechanism_evaluations
            ),
            "candidate_scores": int(run.candidate_scores),
            "actual_moves": int(run.actual_moves),
            "score_counts": score_counts,
            "selector_diagnostics": selector,
            "segment_diagnostics": mechanism,
            "raw_cost": float(raw_cost),
            "raw_signature": solution_signature_hash(raw_solution),
            "completed_cost": float(replay),
            "completed_signature": solution_signature_hash(
                final_solution
            ),
            "terminal_completion_enabled": bool(
                cfg.apply_terminal_completion
            ),
            "terminal_selected_branch": selected_branch,
            "terminal_activity": completion_activity,
            "main_search_history_fingerprint": _sha_json(
                history_payload
            ),
            "raw_search_elapsed_seconds": float(raw_elapsed),
            "terminal_completion_elapsed_seconds": float(
                completion_elapsed
            ),
        },
    )


def _sha_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
