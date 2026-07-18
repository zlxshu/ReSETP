"""One continuous ALNS with sparse model-specific expert prescriptions.

This candidate keeps one current solution, one best solution, one generic
ALNS selector, one acceptance rule, and one random stream for the whole run.
At fixed sparse checkpoints, a cheap current-solution symptom may nominate
one of three exact project experts:

* multi-depot responsibility handover,
* fixed-route fleet and charging choice,
* fixed-route charging-time retiming.

The nominated expert first works on route-local or separable accounts.  Only
when it finds a different strict-improvement proposal is that complete solution
submitted once through the shared search candidate scorer.  A false diagnosis
costs no complete candidate evaluation and the ordinary ALNS move proceeds in
the same iteration.  No search chunk, selector, acceptance state, or RNG is
restarted.

Current-state-conditioned operator choice is supported as a general direction
by Johnn et al. (2023, arXiv:2302.14678) and by the contextual-state interface
of Wouda and Lan (2023, doi:10.21105/joss.05028).  The ReSETP symptom metrics,
expert mapping, and continuous interleaving are project-specific hypotheses,
not borrowed performance guarantees.
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
from setp_solver.algorithms.resetp_alns.support.mechanism_prescription import (  # noqa: E402
    CARBON_TIME,
    FLEET_CHARGE,
    MECHANISM_ORDER,
    RESPONSIBILITY,
    MechanismPrescription,
    MechanismPrescriptionController,
    PrescriptionControllerConfig,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from terminal_completion import apply_terminal_completion  # noqa: E402
from v5_carbon_retiming_solver import carbon_aware_depot_retime  # noqa: E402
from v6_monotone_mechanism_solver import (  # noqa: E402
    exact_joint_fleet_charge_decode,
)
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
    exact_cross_depot_responsibility_decode,
)


TOL = 1.0e-9


@dataclass(frozen=True)
class ContextualExpertConfig:
    """Frozen controls for the stage-one behaviour and short comparison gates."""

    total_eval_budget: int = 100
    runtime_cap_seconds: float = 3600.0
    enable_prescriptions: bool = True
    assessment_interval: int = 20
    per_mechanism_cooldown: int = 60
    enabled_mechanisms: tuple[str, ...] = MECHANISM_ORDER
    responsibility_exact_candidates: int = 8

    def __post_init__(self) -> None:
        if int(self.total_eval_budget) < 0:
            raise ValueError("total_eval_budget must be non-negative")
        if float(self.runtime_cap_seconds) <= 0.0:
            raise ValueError("runtime_cap_seconds must be positive")
        if int(self.assessment_interval) < 1:
            raise ValueError("assessment_interval must be positive")
        if int(self.per_mechanism_cooldown) < 0:
            raise ValueError(
                "per_mechanism_cooldown must be non-negative"
            )
        if int(self.responsibility_exact_candidates) < 1:
            raise ValueError(
                "responsibility_exact_candidates must be positive"
            )
        unknown = set(self.enabled_mechanisms) - set(MECHANISM_ORDER)
        if unknown:
            raise ValueError(
                f"unknown mechanisms: {sorted(unknown)}"
            )


class ExactMechanismExpertController(
    MechanismPrescriptionController
):
    """Build exact mechanism proposals after the cheap symptom nomination."""

    def __init__(self, config: ContextualExpertConfig) -> None:
        super().__init__(
            PrescriptionControllerConfig(
                assessment_interval=int(config.assessment_interval),
                per_mechanism_cooldown=int(
                    config.per_mechanism_cooldown
                ),
                enabled_mechanisms=tuple(config.enabled_mechanisms),
            )
        )
        self.exact_config = config

    def propose(
        self,
        prescription: MechanismPrescription,
        *,
        current_solution: Solution,
        best_solution: Solution,
        current_objective: float,
        best_objective: float,
        context: Any,
    ) -> dict[str, Any]:
        """Return one strict-improvement proposal without candidate scoring."""

        del best_solution, best_objective
        mechanism_id = prescription.mechanism_id
        if mechanism_id == RESPONSIBILITY:
            owners = dict(context.customer_home_depot or {})
            source = annotate_cross_site_services(
                current_solution,
                owners,
            )
            solution, estimated, activity = (
                exact_cross_depot_responsibility_decode(
                    source,
                    context,
                    incumbent_objective=float(current_objective),
                    owners=owners,
                    max_rounds=1,
                    max_exact_candidates_per_round=int(
                        self.exact_config.responsibility_exact_candidates
                    ),
                    top_insertions=2,
                    independent_final_replay=False,
                )
            )
        elif mechanism_id == FLEET_CHARGE:
            solution, estimated, activity = (
                exact_joint_fleet_charge_decode(
                    current_solution,
                    context,
                    incumbent_objective=float(current_objective),
                )
            )
        elif mechanism_id == CARBON_TIME:
            solution, estimated, activity = carbon_aware_depot_retime(
                current_solution,
                context,
                incumbent_objective=float(current_objective),
                consume_complete_evaluation=False,
            )
        else:
            raise ValueError(
                f"unsupported mechanism prescription: {mechanism_id}"
            )

        changed = solution_signature_hash(
            solution
        ) != solution_signature_hash(current_solution)
        strict_proxy_improvement = (
            float(estimated) < float(current_objective) - TOL
        )
        activity = {
            **dict(activity),
            "mechanism_id": mechanism_id,
            "proposal_signature_changed": bool(changed),
            "strict_local_or_separable_improvement": bool(
                strict_proxy_improvement
            ),
            "current_objective": float(current_objective),
            "estimated_objective": float(estimated),
            "complete_candidate_evaluations_before_submission": 0,
        }
        if not changed or not strict_proxy_improvement:
            return {
                "solution": None,
                "estimated_objective": float(current_objective),
                "activity": activity,
            }
        return {
            "solution": solution,
            "estimated_objective": float(estimated),
            "activity": activity,
        }


def run_contextual_expert_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: ContextualExpertConfig | None = None,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run the continuous candidate or its exact same-loop control."""

    cfg = config or ContextualExpertConfig()
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
    flags = winner_variant_flags(include_route_elimination=False)
    controller = (
        ExactMechanismExpertController(cfg)
        if cfg.enable_prescriptions
        else None
    )
    kernel_config = WinnerKernelConfig(
        seed=int(seed),
        eval_budget=int(cfg.total_eval_budget),
        max_runtime_seconds=float(cfg.runtime_cap_seconds),
        require_charging_signal=False,
        split_selector_rng=False,
    )

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
            "contextual expert ALNS complete-candidate ledger did not close"
        )
    if not bool(selector.get("selection_count_closed", False)):
        raise RuntimeError("contextual expert selector count did not close")

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
            "mechanism move and complete-candidate ledgers disagree: "
            f"{mechanism_evaluations} != {mechanism_moves}"
        )
    if int(selector.get("selector_sample_count", 0)) + mechanism_moves != budget:
        raise RuntimeError(
            "generic plus mechanism moves do not close the total budget"
        )

    raw_solution = run.best_solution
    raw_cost = independent_cost(bundle_dir, raw_solution, prices)
    if abs(float(raw_cost) - float(run.best_obj)) > 1.0e-7:
        raise RuntimeError(
            f"raw kernel objective replay mismatch: {run.best_obj} != {raw_cost}"
        )
    completed = apply_terminal_completion(
        bundle_dir,
        raw_solution,
        prices=prices,
    )
    if not completed.feasible:
        raise RuntimeError(
            "contextual expert terminal completion returned infeasible"
        )
    final_cost = independent_cost(
        bundle_dir,
        completed.solution,
        prices,
    )
    if abs(float(final_cost) - float(completed.cost)) > 1.0e-7:
        raise RuntimeError(
            "terminal completion objective replay mismatch"
        )
    violations = check_solution(
        completed.solution,
        bundle.instance,
        prices,
    )
    if violations:
        raise RuntimeError(
            f"contextual expert result is infeasible: {violations[:8]}"
        )

    history_payload = [
        {
            key: row[key]
            for key in ("eval", "best_cost", "best_obj", "operator")
            if key in row
        }
        for row in run.history
    ]
    completion_activity = dict(completed.activity)
    return ArmResult(
        algorithm=(
            "context_gated_exact_mechanism_alns"
            if cfg.enable_prescriptions
            else "continuous_default_alpha_alns_control"
        ),
        best_solution=completed.solution,
        best_cost=float(final_cost),
        evaluations=int(run.evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(completed.solution.routes),
        feasible=True,
        mechanism_activity={
            "continuous_main_search": True,
            "search_loop_count": 1,
            "search_restart_count": 0,
            "hgs_calls": 0,
            "prescriptions_enabled": bool(
                cfg.enable_prescriptions
            ),
            "enabled_mechanisms": list(cfg.enabled_mechanisms),
            "complete_search_candidate_evaluations": int(
                run.evaluations
            ),
            "generic_candidate_evaluations": int(
                budget - mechanism_evaluations
            ),
            "mechanism_candidate_evaluations": int(
                mechanism_evaluations
            ),
            "candidate_scores": int(run.candidate_scores),
            "actual_moves": int(run.actual_moves),
            "score_counts": score_counts,
            "selector_diagnostics": selector,
            "mechanism_diagnostics": mechanism,
            "raw_cost": float(raw_cost),
            "raw_signature": solution_signature_hash(raw_solution),
            "completed_cost": float(final_cost),
            "completed_signature": solution_signature_hash(
                completed.solution
            ),
            "main_search_history_fingerprint": _sha_json(
                history_payload
            ),
            "terminal_reference_replays": int(
                completion_activity.get("full_solution_replays", 0)
            ),
            "raw_search_elapsed_seconds": float(raw_elapsed),
            "terminal_completion_elapsed_seconds": float(
                max(
                    0.0,
                    time.perf_counter() - started - raw_elapsed,
                )
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
