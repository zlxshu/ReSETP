from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np

from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, score_reference
from setp_solver.search.fleet import UNBOUNDED_FLEET, infer_fleet_limits


MANIFEST = Path("solver/reports/alns_crush_v2/winner_operator_manifest.json")
FIXTURE_DIR = Path("models/data_bundle/generated_instances/verify_20251113")
E2_THREESHIFT_150C = Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-150c-01")


def test_winner_manifest_exposes_step_level_public_api() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    module = importlib.import_module(manifest["winner_operator_module"])

    public_api = set(manifest["public_api"])
    step_api_names = {
        "apply_winner_action",
        "WinnerOperatorAction",
        "WinnerOperatorSet",
        "decode_winner_action",
    }

    missing = sorted(step_api_names - public_api)
    assert not missing, f"HALT_NO_STEP_API missing public_api={missing}"
    for name in step_api_names:
        assert hasattr(module, name), f"HALT_NO_STEP_API module lacks {name}"


def test_winner_manifest_operator_base_id_matches_module() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    module = importlib.import_module(manifest["winner_operator_module"])

    assert manifest["operator_base_id"] == module.operator_base_id
    assert manifest["operator_base_id"] == "winner_kernel_v1"


def test_apply_winner_action_scores_exactly_one_candidate_and_traces_base() -> None:
    from setp_solver.search.winner_operators import (
        WinnerOperatorSet,
        apply_winner_action,
        decode_winner_action,
        operator_base_id,
        winner_operator_module,
    )

    bundle = load_search_bundle(FIXTURE_DIR)
    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        introduce_ev=False,
        require_charging_signal=False,
    )
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        budget=EvalBudget(limit=10, target=10),
    )
    current_obj = score_reference(solution, context)
    operator_set = WinnerOperatorSet.create(include_route_elimination=False)
    action = decode_winner_action(
        [0, 1, 0, 50],
        operator_set=operator_set,
        base_temperature=100.0,
        customer_count=sum(1 for node in bundle.instance.nodes if node.node_type.lower() == "c"),
    )

    result = apply_winner_action(
        solution,
        action,
        context,
        rng=np.random.default_rng(7),
        operator_set=operator_set,
        current_obj=current_obj,
        progress=0.0,
    )

    assert result["operator_base_id"] == operator_base_id
    assert result["trace"]["operator_base_id"] == operator_base_id
    assert result["trace"]["winner_operator_module"] == winner_operator_module
    limits = infer_fleet_limits(FIXTURE_DIR)
    assert result["trace"]["policy_max_cv"] == limits.cv
    assert result["trace"]["policy_max_ev"] == limits.ev
    assert result["trace"]["policy_max_cv"] < UNBOUNDED_FLEET
    assert result["trace"]["policy_max_ev"] < UNBOUNDED_FLEET
    assert result["actual_evals_added"] == 1
    assert context.budget.count == 1
    assert context.score_counts["candidate"] == 1


def test_vehicle_type_swap_default_policy_uses_instance_fleet_caps_and_can_improve() -> None:
    from setp_solver.search.winner_operators import WinnerOperatorAction, WinnerOperatorSet, apply_winner_action

    bundle = load_search_bundle(E2_THREESHIFT_150C)
    solution = make_shared_initial_solution(bundle)
    context = EvaluationContext(bundle.instance, bundle.carbon_profile)
    current_obj = score_reference(solution, context)
    operator_set = WinnerOperatorSet.create(include_route_elimination=False)
    action = WinnerOperatorAction(
        destroy_op_id="vehicle_type_swap",
        repair_op_id="greedy_insert_repair",
        raw_action=(5, 0, 0, 0),
    )

    result = apply_winner_action(
        solution,
        action,
        context,
        rng=np.random.default_rng(1),
        operator_set=operator_set,
        current_obj=current_obj,
        progress=0.0,
    )

    limits = infer_fleet_limits(E2_THREESHIFT_150C)
    assert result["trace"]["policy_max_cv"] == limits.cv
    assert result["trace"]["policy_max_ev"] == limits.ev
    assert result["trace"]["policy_max_cv"] < UNBOUNDED_FLEET
    assert result["trace"]["policy_max_ev"] < UNBOUNDED_FLEET
    assert result["trace"]["changed"] is True
    assert result["hard_violation_count"] == 0
    assert result["candidate_obj"] < current_obj
