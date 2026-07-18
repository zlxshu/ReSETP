"""Continuous mechanism ALNS with non-monopolistic operator selection.

The frozen v7 route search uses an AlphaUCB selector.  On one stage-one
development instance that selector assigned every one of 100 moves to a
single destroy family.  This candidate changes only that selection rule:
legal destroy/repair pairs are sampled from their learned AlphaUCB values
with a cooling softmax distribution.  Better pairs remain more likely, while
every legal alternative keeps a positive sampling probability at positive
temperature.  That does not guarantee finite-run coverage or improvement.

After the uninterrupted route search, the unchanged v7 responsibility,
fleet/charging, and carbon-time experts complete the best route structure.
There is no HGS hand-off, cold restart, hidden complete-solution evaluation,
or search feedback from the terminal experts.

The softmax rule itself is established exploration machinery, not a claimed
ReSETP invention.  The project contribution, if later gates support it, is
the complete mechanism-driven ALNS design and its problem-specific experts.

Method anchors:

* Ropke and Pisinger (2006), doi:10.1287/trsc.1050.0135.
* Auer et al. (2002), doi:10.1023/A:1013689704352.
* Cesa-Bianchi et al. (2017), arXiv:1705.10257.
* Wouda and Lan (2023), doi:10.21105/joss.05028.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
    SELECTOR_FLAGS,
    SOFTMAX_SELECTOR_FLAG,
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
class SoftmaxMechanismConfig:
    """Fixed stage-one controls for the mechanism-balanced candidate."""

    total_eval_budget: int = 100
    runtime_cap_seconds: float = 3600.0
    enable_softmax: bool = True
    temperature_start: float = 1.0
    temperature_end: float = 0.1
    split_selector_rng: bool = True

    def __post_init__(self) -> None:
        if int(self.total_eval_budget) < 0:
            raise ValueError("total_eval_budget must be non-negative")
        if float(self.runtime_cap_seconds) <= 0.0:
            raise ValueError("runtime_cap_seconds must be positive")
        if float(self.temperature_start) <= 0.0:
            raise ValueError("temperature_start must be positive")
        if float(self.temperature_end) <= 0.0:
            raise ValueError("temperature_end must be positive")


def run_softmax_mechanism_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: SoftmaxMechanismConfig | None = None,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run one uninterrupted ALNS and the frozen terminal mechanism stack."""

    cfg = config or SoftmaxMechanismConfig()
    budget = int(cfg.total_eval_budget)
    flags = winner_variant_flags(include_route_elimination=False)
    for selector_flag in SELECTOR_FLAGS:
        flags.setdefault(selector_flag, "0")
    flags[SOFTMAX_SELECTOR_FLAG] = "1" if cfg.enable_softmax else "0"
    enabled_selectors = [
        flag
        for flag in SELECTOR_FLAGS
        if _flag_enabled(flags.get(flag, "0"))
    ]
    expected_selector_count = 1 if cfg.enable_softmax else 0
    if len(enabled_selectors) != expected_selector_count:
        raise RuntimeError(
            "selector contract mismatch: "
            f"{enabled_selectors} != expected count {expected_selector_count}"
        )

    started = time.perf_counter()
    raw = _run_winner_variant(
        bundle_dir,
        WinnerKernelConfig(
            seed=int(seed),
            eval_budget=budget,
            max_runtime_seconds=float(cfg.runtime_cap_seconds),
            require_charging_signal=False,
            softmax_temperature_start=float(cfg.temperature_start),
            softmax_temperature_end=float(cfg.temperature_end),
            split_selector_rng=bool(cfg.split_selector_rng),
        ),
        initial_solution=initial_solution,
        prices=prices,
        variant_flags=flags,
        variant_id=(
            "softmax_mechanism_route_search"
            if cfg.enable_softmax
            else "default_alpha_mechanism_control"
        ),
    )
    raw_elapsed = time.perf_counter() - started
    if int(raw["evaluations"]) != budget:
        raise RuntimeError(
            "mechanism-balanced ALNS did not close the complete-candidate "
            f"budget: {raw['evaluations']} != {budget}"
        )

    completion_started = time.perf_counter()
    completed = apply_terminal_completion(
        bundle_dir,
        raw["best_solution"],
        prices=prices,
    )
    completion_elapsed = time.perf_counter() - completion_started
    if not completed.feasible:
        raise RuntimeError("terminal mechanism completion returned infeasible")

    final_cost = independent_cost(bundle_dir, completed.solution, prices)
    if abs(float(final_cost) - float(completed.cost)) > 1.0e-7:
        raise RuntimeError(
            "independent objective replay disagrees with terminal completion: "
            f"{final_cost} != {completed.cost}"
        )
    bundle = load_search_bundle(bundle_dir)
    violations = check_solution(completed.solution, bundle.instance, prices)
    if violations:
        raise RuntimeError(
            f"mechanism-balanced result is infeasible: {violations[:8]}"
        )

    operator_counts = dict(raw.get("operator_counts", {}))
    selector_diagnostics = dict(
        operator_counts.get("selector", {})
    )
    destroy_counts = _selection_totals(
        dict(operator_counts.get("destroy", {}))
    )
    repair_counts = _selection_totals(
        dict(operator_counts.get("repair", {}))
    )
    actual_moves = int(raw.get("actual_moves", 0))
    if actual_moves != sum(destroy_counts.values()):
        raise RuntimeError(
            "reported ALNS moves disagree with destroy selections: "
            f"{actual_moves} != {sum(destroy_counts.values())}"
        )
    score_counts = dict(operator_counts.get("score_counts", {}))
    candidate_scores = int(raw.get("candidate_scores", 0))
    if candidate_scores != int(raw["evaluations"]):
        raise RuntimeError(
            "candidate score count does not close the evaluation budget: "
            f"{candidate_scores} != {raw['evaluations']}"
        )
    if int(score_counts.get("candidate", 0)) != int(raw["evaluations"]):
        raise RuntimeError(
            "candidate channel ledger does not close the evaluation budget: "
            f"{score_counts.get('candidate', 0)} != {raw['evaluations']}"
        )
    if not bool(selector_diagnostics.get("selection_count_closed", False)):
        raise RuntimeError("selector selections do not close ALNS moves")

    history = [
        {
            key: row[key]
            for key in ("eval", "best_cost", "best_obj", "operator")
            if key in row
        }
        for row in raw.get("history", [])
    ]
    activity = dict(completed.activity)
    label = (
        "mechanism_balanced_alns_softmax"
        if cfg.enable_softmax
        else "mechanism_alns_default_alpha_control"
    )
    return ArmResult(
        algorithm=label,
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
                "softmax_alpha_ucb"
                if cfg.enable_softmax
                else "default_alpha_ucb"
            ),
            "enabled_selector_flags": enabled_selectors,
            "all_variant_flags": dict(flags),
            "complete_search_candidate_evaluations": int(
                raw["evaluations"]
            ),
            "candidate_scores": candidate_scores,
            "repair_scores": int(raw.get("repair_scores", 0)),
            "repair_delta_count": int(
                raw.get("repair_delta_count", 0)
            ),
            "alns_actual_moves": actual_moves,
            "score_counts": score_counts,
            "selector_diagnostics": selector_diagnostics,
            "destroy_selection_counts": destroy_counts,
            "repair_selection_counts": repair_counts,
            "distinct_destroy_families_used": sum(
                count > 0 for count in destroy_counts.values()
            ),
            "distinct_repair_families_used": sum(
                count > 0 for count in repair_counts.values()
            ),
            "raw_cost": float(raw["best_cost"]),
            "raw_signature": solution_signature_hash(
                raw["best_solution"]
            ),
            "completed_cost": float(final_cost),
            "completed_signature": solution_signature_hash(
                completed.solution
            ),
            "main_search_history_fingerprint": _sha_json(history),
            "selected_terminal_branch": str(
                completed.selected_branch
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
            "terminal_route_local_exact_evaluations": int(
                activity.get("route_local_exact_evaluations", 0)
            ),
            "terminal_route_proxy_evaluations": int(
                activity.get("route_proxy_evaluations", 0)
            ),
            "terminal_route_schedule_evaluations": int(
                activity.get(
                    "route_local_schedule_evaluations",
                    0,
                )
            ),
            "raw_search_elapsed_seconds": float(raw_elapsed),
            "terminal_completion_elapsed_seconds": float(
                completion_elapsed
            ),
        },
    )


def _selection_totals(
    rows: dict[str, Any],
) -> dict[str, int]:
    return {
        str(name): sum(int(value) for value in outcomes)
        for name, outcomes in rows.items()
    }


def _flag_enabled(value: Any) -> bool:
    return str(value).strip().lower() not in {
        "",
        "0",
        "false",
        "no",
        "off",
    }


def _sha_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
