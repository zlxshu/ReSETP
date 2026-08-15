from __future__ import annotations

import importlib.util
from dataclasses import asdict
import json
from pathlib import Path
import random
import sys

import pytest

from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Solution
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import UK_2025_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.algorithms.resetp_alns.kernel.alns_core import run_alns_wouda
from setp_solver.algorithms.resetp_alns.operators.carbon_operators import _solution_carbon_kg
from setp_solver.algorithms.resetp_alns.support.fleet_charge_corepair import (
    propose_fleet_charge_corepair,
)
from setp_solver.algorithms.resetp_alns.support.global_order_repack import (
    propose_global_order_repack,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    SearchBudgetExhausted,
    cached_or_reference_model_cost,
    score_reference_solution,
    score_search_candidate,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "baselines/e2_alns/audit_alns_budget_g0_20260718.py"
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_alns_budget_g0_20260718", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_scorers(monkeypatch: pytest.MonkeyPatch):
    import setp_solver.search.e3_multitrip_runtime as runtime

    calls = {"candidate": 0, "reference": 0, "model": 0}

    def candidate(solution, context):
        calls["candidate"] += 1
        context.score_counts["candidate"] = int(context.score_counts.get("candidate", 0)) + 1
        if context.budget is not None:
            context.budget.record()
        context.score_breakdowns[id(solution)] = {"raw_cost": 10.0, "objective": 10.0}
        return solution, 10.0

    def reference(solution, context):
        calls["reference"] += 1
        context.score_breakdowns[id(solution)] = {"raw_cost": 10.0, "objective": 10.0}
        return solution, 10.0

    def model(solution, context):
        calls["model"] += 1
        return solution, 10.0

    monkeypatch.setattr(runtime, "prepare_and_score_candidate", candidate)
    monkeypatch.setattr(runtime, "prepare_and_score_reference", reference)
    monkeypatch.setattr(runtime, "prepared_model_cost", model)
    return calls


@pytest.mark.parametrize("target", [0, 1, 2, 3, 7])
def test_candidate_precheck_never_enters_target_plus_one(target: int, fake_scorers) -> None:
    context = EvaluationContext(object(), [], budget=EvalBudget(limit=target, target=target))
    solution = Solution()
    for _ in range(target):
        score_search_candidate(solution, context, channel="test")
    assert context.budget is not None
    assert context.budget.count == target
    assert context.score_counts.get("candidate", 0) == target
    assert fake_scorers["candidate"] == target
    with pytest.raises(SearchBudgetExhausted):
        score_search_candidate(solution, context, channel="test")
    assert context.budget.count == target
    assert fake_scorers["candidate"] == target


def test_reference_phases_and_cache_do_not_consume_candidate_budget(fake_scorers) -> None:
    context = EvaluationContext(object(), [], budget=EvalBudget(limit=0, target=0))
    solution = Solution()
    score_reference_solution(solution, context, phase="initial")
    assert cached_or_reference_model_cost(solution, context, phase="history") == 10.0
    score_reference_solution(solution, context, phase="final")
    assert context.budget is not None and context.budget.count == 0
    assert context.score_counts["reference"] == 2
    assert context.score_counts["reference_phase:initial"] == 1
    assert context.score_counts["reference_phase:final"] == 1
    assert context.score_counts["reference_cache_hit:history"] == 1


def test_g0_static_audit_has_zero_blockers_and_five_surfaces(tmp_path: Path) -> None:
    module = _load_audit()
    output = tmp_path / "g0"
    decision = module.run_audit(output)
    assert decision["verdict"] == "PASS_ALNS_BUDGET_G0_STATIC_CLOSURE"
    assert decision["closure_blocker_call_sites"] == 0
    assert decision["unclassified_call_sites"] == 0
    assert all(decision["required_channels_present"].values())
    assert {path.name for path in output.iterdir()} == {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "report.md",
        "artifact_hashes.json",
    }
    manifest = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"metadata.json", "raw_runs.csv", "decision.json", "report.md"}


@pytest.mark.parametrize("target", [0, 1, 2, 3, 7])
def test_real_alns_targets_close_exactly_and_final_solution_rechecks(target: int) -> None:
    result = run_alns_wouda(
        VERIFY_BUNDLE,
        iterations=None,
        eval_budget=target,
        max_runtime_seconds=20.0,
        seed=17,
        prices=UK_2025_PRICES,
    )
    assert result.evaluations == target
    assert result.candidate_scores == target
    assert 0 <= result.actual_moves <= target
    bundle = load_search_bundle(VERIFY_BUNDLE)
    assert check_solution(result.best_solution, bundle.instance, UK_2025_PRICES) == []
    independent = evaluate(
        result.best_solution,
        bundle.instance,
        bundle.carbon_profile,
        UK_2025_PRICES,
    )["total_cost"]
    assert independent == pytest.approx(result.best_obj)


def test_same_seed_and_budget_replay_same_solution_and_stop() -> None:
    left = run_alns_wouda(
        VERIFY_BUNDLE,
        iterations=None,
        eval_budget=7,
        max_runtime_seconds=20.0,
        seed=29,
        prices=UK_2025_PRICES,
    )
    right = run_alns_wouda(
        VERIFY_BUNDLE,
        iterations=None,
        eval_budget=7,
        max_runtime_seconds=20.0,
        seed=29,
        prices=UK_2025_PRICES,
    )
    assert asdict(left.best_solution) == asdict(right.best_solution)
    assert (left.evaluations, left.candidate_scores, left.actual_moves) == (
        right.evaluations,
        right.candidate_scores,
        right.actual_moves,
    )


def test_route_sum_carbon_feature_matches_complete_evaluator() -> None:
    bundle = load_search_bundle(VERIFY_BUNDLE)
    solution = make_shared_initial_solution(bundle, UK_2025_PRICES)
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES)
    expected = evaluate(
        solution,
        bundle.instance,
        bundle.carbon_profile,
        UK_2025_PRICES,
        carbon_quota_kg=0.0,
    )["E_total"]
    assert _solution_carbon_kg(solution, context) == pytest.approx(expected)


@pytest.mark.parametrize("component", ["global_repack", "fleet_charge"])
def test_structural_components_stop_cleanly_at_one_remaining_score(component: str) -> None:
    bundle = load_search_bundle(VERIFY_BUNDLE)
    solution = make_shared_initial_solution(bundle, UK_2025_PRICES)
    reference = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES)
    current_objective = evaluate(
        solution,
        bundle.instance,
        bundle.carbon_profile,
        UK_2025_PRICES,
    )["total_cost"]
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=UK_2025_PRICES,
        budget=EvalBudget(limit=1, target=1),
    )
    if component == "global_repack":
        outcome = propose_global_order_repack(
            solution,
            solution,
            context,
            random.Random(5),
            current_objective=current_objective,
        )
    else:
        outcome = propose_fleet_charge_corepair(
            solution,
            context,
            max_attempts=16,
            current_objective=current_objective,
        )
    _ = reference
    assert context.budget is not None
    assert context.budget.count <= 1
    assert outcome.evaluations_used <= 1
