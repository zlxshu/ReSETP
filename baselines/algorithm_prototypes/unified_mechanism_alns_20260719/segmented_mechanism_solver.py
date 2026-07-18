"""Mechanism ALNS with the classical score-per-use segmented roulette.

The route search remains one uninterrupted winner-kernel run.  Inside each
fixed-length segment, destroy and repair probabilities do not change.  At a
segment boundary, each used operator is judged by its average reward per use,
then blended with its previous weight.  This directly addresses the observed
"called more, therefore accumulated more reward, therefore called more"
feedback loop without inventing a new optimizer.

After route search, the unchanged v7 responsibility, fleet/charging, and
carbon-time experts complete the result.  HGS is not called and no search
state is restarted.

Method anchors:

* Ropke and Pisinger (2006), doi:10.1287/trsc.1050.0135.
* Pisinger and Ropke (2007), doi:10.1016/j.cor.2005.09.012.
* Wouda and Lan (2023), doi:10.21105/joss.05028.

The selector is established ALNS machinery, not a claimed paper novelty.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_signature_hash  # noqa: E402
from prototype import ArmResult, independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    AVERAGED_SEGMENTED_ROULETTE_FLAG,
    SELECTOR_FLAGS,
    WinnerKernelConfig,
    _run_winner_variant,
    winner_variant_flags,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from terminal_completion import apply_terminal_completion  # noqa: E402


@dataclass(frozen=True)
class SegmentedMechanismConfig:
    total_eval_budget: int = 400
    runtime_cap_seconds: float = 3600.0
    enable_segmented_roulette: bool = True
    reaction: float = 0.1
    segment_length: int = 100
    split_selector_rng: bool = True

    def __post_init__(self) -> None:
        if int(self.total_eval_budget) < 0:
            raise ValueError("total_eval_budget must be non-negative")
        if float(self.runtime_cap_seconds) <= 0.0:
            raise ValueError("runtime_cap_seconds must be positive")
        if not 0.0 <= float(self.reaction) <= 1.0:
            raise ValueError("reaction must lie in [0, 1]")
        if int(self.segment_length) < 1:
            raise ValueError("segment_length must be positive")


def run_segmented_mechanism_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: SegmentedMechanismConfig | None = None,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run the locked segmented selector and frozen mechanism completion."""

    cfg = config or SegmentedMechanismConfig()
    flags = winner_variant_flags(include_route_elimination=False)
    for selector_flag in SELECTOR_FLAGS:
        flags.setdefault(selector_flag, "0")
    flags[AVERAGED_SEGMENTED_ROULETTE_FLAG] = (
        "1" if cfg.enable_segmented_roulette else "0"
    )
    enabled_selectors = [
        flag
        for flag in SELECTOR_FLAGS
        if str(flags.get(flag, "0")).lower()
        not in {"", "0", "false", "no", "off"}
    ]
    expected_count = 1 if cfg.enable_segmented_roulette else 0
    if len(enabled_selectors) != expected_count:
        raise RuntimeError(
            f"selector flag conflict: {enabled_selectors}"
        )

    started = time.perf_counter()
    raw = _run_winner_variant(
        bundle_dir,
        WinnerKernelConfig(
            seed=int(seed),
            eval_budget=int(cfg.total_eval_budget),
            max_runtime_seconds=float(cfg.runtime_cap_seconds),
            require_charging_signal=False,
            segmented_roulette_reaction=float(cfg.reaction),
            segmented_roulette_length=int(cfg.segment_length),
            split_selector_rng=bool(cfg.split_selector_rng),
        ),
        initial_solution=initial_solution,
        prices=prices,
        variant_flags=flags,
        variant_id=(
            "averaged_segmented_roulette_mechanism_search"
            if cfg.enable_segmented_roulette
            else "default_alpha_mechanism_control"
        ),
    )
    raw_elapsed = time.perf_counter() - started
    budget = int(cfg.total_eval_budget)
    operator_counts = dict(raw.get("operator_counts", {}))
    score_counts = dict(operator_counts.get("score_counts", {}))
    selector = dict(operator_counts.get("selector", {}))
    destroy_counts = {
        str(name): sum(int(value) for value in outcomes)
        for name, outcomes in dict(
            operator_counts.get("destroy", {})
        ).items()
    }
    repair_counts = {
        str(name): sum(int(value) for value in outcomes)
        for name, outcomes in dict(
            operator_counts.get("repair", {})
        ).items()
    }
    actual_moves = int(raw.get("actual_moves", 0))
    candidate_scores = int(raw.get("candidate_scores", 0))
    if not (
        int(raw["evaluations"])
        == candidate_scores
        == int(score_counts.get("candidate", 0))
        == actual_moves
        == int(selector.get("selection_count", 0))
        == budget
    ):
        raise RuntimeError("segmented ALNS budget ledger did not close")
    if not bool(selector.get("selection_count_closed", False)):
        raise RuntimeError("selector count did not close")
    if sum(destroy_counts.values()) != budget:
        raise RuntimeError("destroy selections did not close")
    if sum(repair_counts.values()) != budget:
        raise RuntimeError("repair selections did not close")

    completion_started = time.perf_counter()
    completed = apply_terminal_completion(
        bundle_dir,
        raw["best_solution"],
        prices=prices,
    )
    completion_elapsed = time.perf_counter() - completion_started
    if not completed.feasible:
        raise RuntimeError("terminal mechanism completion was infeasible")
    final_cost = independent_cost(
        bundle_dir,
        completed.solution,
        prices,
    )
    if abs(float(final_cost) - float(completed.cost)) > 1.0e-7:
        raise RuntimeError("terminal objective replay mismatch")
    bundle = load_search_bundle(bundle_dir)
    violations = check_solution(
        completed.solution,
        bundle.instance,
        prices,
    )
    if violations:
        raise RuntimeError(
            f"segmented mechanism result is infeasible: {violations[:8]}"
        )

    activity = dict(completed.activity)
    return ArmResult(
        algorithm=(
            "mechanism_alns_averaged_segmented_roulette"
            if cfg.enable_segmented_roulette
            else "mechanism_alns_default_alpha_control"
        ),
        best_solution=completed.solution,
        best_cost=float(final_cost),
        evaluations=int(raw["evaluations"]),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(completed.solution.routes),
        feasible=True,
        mechanism_activity={
            "continuous_main_search": True,
            "search_restart_count": 0,
            "hgs_calls": 0,
            "selector": (
                "averaged_segmented_roulette"
                if cfg.enable_segmented_roulette
                else "default_alpha_ucb"
            ),
            "enabled_selector_flags": enabled_selectors,
            "all_variant_flags": dict(flags),
            "complete_search_candidate_evaluations": int(
                raw["evaluations"]
            ),
            "candidate_scores": candidate_scores,
            "actual_moves": actual_moves,
            "score_counts": score_counts,
            "selector_diagnostics": selector,
            "destroy_selection_counts": destroy_counts,
            "repair_selection_counts": repair_counts,
            "distinct_destroy_families_used": sum(
                count > 0 for count in destroy_counts.values()
            ),
            "raw_cost": float(raw["best_cost"]),
            "raw_signature": solution_signature_hash(
                raw["best_solution"]
            ),
            "completed_signature": solution_signature_hash(
                completed.solution
            ),
            "responsibility_updates": int(
                activity.get("responsibility", {}).get(
                    "exact_decoder_updates",
                    0,
                )
            ),
            "fleet_charge_updates": int(
                activity.get("joint", {}).get(
                    "exact_decoder_updates",
                    0,
                )
            ),
            "carbon_time_updates": int(
                activity.get("carbon", {}).get(
                    "exact_decoder_updates",
                    0,
                )
            ),
            "terminal_reference_replays": int(
                activity.get("full_solution_replays", 0)
            ),
            "raw_search_elapsed_seconds": float(raw_elapsed),
            "terminal_completion_elapsed_seconds": float(
                completion_elapsed
            ),
        },
    )
