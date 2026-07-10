from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
INDEPENDENT_PACKAGE = REPO_ROOT / "solver/src/setp_solver/algorithms/resetp_alns"
E2_CHAIN = REPO_ROOT / "solver/rl/independent_dr_alns/chain.py"
_LOCAL_FIXTURE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"
FIXTURE_DIR = (
    _LOCAL_FIXTURE
    if (_LOCAL_FIXTURE / "instance.json").is_file()
    else Path(r"D:\ReSETP\models\data_bundle\generated_instances\verify_20251113")
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_e2_uses_the_m1_independent_kernel_and_no_legacy_alns() -> None:
    assert (INDEPENDENT_PACKAGE / "kernel/alns_core.py").is_file()
    assert (INDEPENDENT_PACKAGE / "kernel/winner.py").is_file()
    assert E2_CHAIN.is_file()

    banned = {
        "alns",
        "setp_solver.search.alns_wouda",
        "setp_solver.search.winner_operators",
    }
    for path in [*INDEPENDENT_PACKAGE.rglob("*.py"), E2_CHAIN]:
        imports = _imports(path)
        offenders = sorted(
            name
            for name in imports
            if name in banned or name.startswith("alns.")
        )
        assert offenders == [], f"{path.relative_to(REPO_ROOT)} imports {offenders}"


def test_one_model_action_is_the_one_operator_pair_actually_executed() -> None:
    from independent_dr_alns.chain import DrAction, IndependentDrSession

    session = IndependentDrSession(FIXTURE_DIR, seed=1, max_evals=4)
    action = DrAction(
        destroy_id=session.destroy_ids[0],
        repair_id=session.repair_ids[0],
        remove_fraction=0.10,
        threshold_ratio=0.0,
    )

    result = session.step(action)

    assert result["requested_action"] == result["executed_action"]
    assert result["executed_action"]["destroy_id"] == action.destroy_id
    assert result["executed_action"]["repair_id"] == action.repair_id
    assert result["actual_evals_added"] >= 1
    assert result["before"]["solution_hash"] != ""
    assert result["candidate"]["solution_hash"] != ""
    assert result["reward"] == pytest.approx(
        (result["before"]["best_obj"] - result["after"]["best_obj"])
        / max(abs(result["initial_obj"]), 1.0)
    )


def test_invalid_action_is_rejected_instead_of_silently_replaced() -> None:
    from independent_dr_alns.chain import DrAction, IndependentDrSession

    session = IndependentDrSession(FIXTURE_DIR, seed=1, max_evals=4)
    with pytest.raises(ValueError, match="unknown destroy_id"):
        session.step(DrAction("not-an-operator", session.repair_ids[0], 0.10, 0.0))


def test_all_cv_start_does_not_mask_the_vehicle_type_operator() -> None:
    from independent_dr_alns.chain import IndependentDrSession

    session = IndependentDrSession(FIXTURE_DIR, seed=1, max_evals=4)
    assert session.initial_summary["metrics"]["n_veh_ev"] == 0
    assert session.action_mask()["vehicle_type_swap"] is True


def test_carbon_action_opens_only_after_real_ev_signal_and_reward_tracks_cost() -> None:
    from independent_dr_alns.chain import DrAction, IndependentDrSession

    session = IndependentDrSession(FIXTURE_DIR, seed=1, max_evals=10)
    assert session.action_mask()["carbon_related_removal"] is False

    ev_step = session.step(DrAction("vehicle_type_swap", "greedy_insert_repair", 0.10, 0.0))
    assert ev_step["accepted"] is True
    assert ev_step["after"]["metrics"]["n_veh_ev"] == 1
    assert ev_step["after"]["charging_action_count"] == 1
    assert session.action_mask()["carbon_related_removal"] is True

    carbon_step = session.step(DrAction("carbon_related_removal", "low_carbon_charging_repair", 0.10, 0.0))
    assert carbon_step["requested_action"] == carbon_step["executed_action"]
    assert carbon_step["accepted"] is True
    assert carbon_step["after"]["objective"] < carbon_step["before"]["objective"]
    assert carbon_step["reward"] > 0.0
    assert carbon_step["after"]["charging_action_count"] == 2


def test_micro_learning_env_keeps_action_identity_and_cost_reward_direction() -> None:
    from independent_dr_alns.micro_env import IndependentDrMicroEnv

    random_env = IndependentDrMicroEnv(FIXTURE_DIR, seed=1)
    random_env.reset(seed=1)
    _, random_reward, random_done, _, random_info = random_env.step(0)

    vehicle_env = IndependentDrMicroEnv(FIXTURE_DIR, seed=1)
    vehicle_env.reset(seed=1)
    _, vehicle_reward, vehicle_done, _, vehicle_info = vehicle_env.step(1)

    assert random_done is True and vehicle_done is True
    assert random_info["requested_action"] == random_info["executed_action"]
    assert vehicle_info["requested_action"] == vehicle_info["executed_action"]
    assert random_info["after"]["best_obj"] == pytest.approx(random_info["before"]["best_obj"])
    assert vehicle_info["after"]["best_obj"] < vehicle_info["before"]["best_obj"]
    assert random_reward == pytest.approx(0.0)
    assert vehicle_reward > random_reward


def test_context_env_keeps_three_fixed_action_meanings() -> None:
    from independent_dr_alns.micro_env import CONTEXT_ACTIONS, IndependentDrContextEnv

    env = IndependentDrContextEnv([FIXTURE_DIR], seed=1)
    assert env.action_space.n == 3
    assert [action.destroy_id for action in CONTEXT_ACTIONS] == [
        "worst_customer_removal",
        "vehicle_type_swap",
        "shaw_related_removal",
    ]
    env.reset(seed=1)
    _, _, done, _, info = env.step(0)
    assert done is True
    assert info["requested_action"] == info["executed_action"] == {
        "destroy_id": "worst_customer_removal",
        "repair_id": "regret2_insert_repair",
        "remove_fraction": 0.10,
        "threshold_ratio": 0.0,
    }


def test_context_training_reward_can_be_scaled_per_training_instance() -> None:
    from independent_dr_alns.micro_env import IndependentDrContextEnv

    unscaled = IndependentDrContextEnv([FIXTURE_DIR], seed=1)
    unscaled.reset(seed=1)
    _, raw_reward, _, _, _ = unscaled.step(1)

    scaled = IndependentDrContextEnv([FIXTURE_DIR], seed=1, reward_scales={str(FIXTURE_DIR): 2.0})
    scaled.reset(seed=1)
    _, reward, _, _, info = scaled.step(1)

    assert info["raw_cost_reward"] == pytest.approx(raw_reward)
    assert info["training_reward_scale"] == pytest.approx(2.0)
    assert reward == pytest.approx(raw_reward / 2.0)


def test_multistep_search_reselects_one_exact_action_per_evaluation() -> None:
    from independent_dr_alns.micro_env import IndependentDrSearchEnv, SEARCH_ACTIONS

    env = IndependentDrSearchEnv([FIXTURE_DIR], horizon=3, seed=1)
    observation, _ = env.reset(seed=1)
    vehicle_action = next(
        index
        for index, action in enumerate(SEARCH_ACTIONS)
        if action.destroy_id == "vehicle_type_swap"
        and action.repair_id == "regret2_insert_repair"
        and action.remove_fraction == 0.10
    )
    next_observation, _, done, _, info = env.step(vehicle_action)

    assert done is False
    assert info["action_index"] == vehicle_action
    assert info["requested_action"] == info["executed_action"]
    assert info["actual_evals_added"] == 1
    assert observation.shape == next_observation.shape == env.observation_space.shape
    assert next_observation.tolist() != observation.tolist()


def test_multistep_reward_telescopes_to_final_full_evaluator_gain() -> None:
    from independent_dr_alns.micro_env import IndependentDrSearchEnv, SEARCH_ACTIONS

    env = IndependentDrSearchEnv([FIXTURE_DIR], horizon=3, seed=1)
    env.reset(seed=1)
    vehicle_action = next(
        index
        for index, action in enumerate(SEARCH_ACTIONS)
        if action.destroy_id == "vehicle_type_swap"
        and action.repair_id == "regret2_insert_repair"
        and action.remove_fraction == 0.10
    )
    rewards = []
    done = False
    while not done:
        _, reward, done, _, info = env.step(vehicle_action)
        rewards.append(reward)

    assert env.session is not None
    expected = 100.0 * (env.session.initial_obj - env.session.best_obj) / max(abs(env.session.initial_obj), 1.0)
    assert sum(rewards) == pytest.approx(expected)
    assert info["after"]["violation_count"] == 0


def test_training_curriculum_exposes_mid_search_state_without_changing_action_contract() -> None:
    from independent_dr_alns.micro_env import IndependentDrSearchEnv, SEARCH_ACTIONS

    vehicle_action = next(
        index
        for index, action in enumerate(SEARCH_ACTIONS)
        if action.destroy_id == "vehicle_type_swap"
        and action.repair_id == "regret2_insert_repair"
        and action.remove_fraction == 0.10
    )
    env = IndependentDrSearchEnv(
        [FIXTURE_DIR],
        horizon=4,
        seed=1,
        training_warmup_action_indices=[vehicle_action, vehicle_action],
    )
    observation, reset_info = env.reset(seed=1)

    assert reset_info["training_warmup_steps"] == 2
    assert env.steps == 2
    assert env.session is not None and env.session.context.budget is not None
    assert env.session.context.budget.count == 2
    assert observation[5] == pytest.approx(0.5)

    _, _, done, _, info = env.step(vehicle_action)
    assert done is False
    assert info["requested_action"] == info["executed_action"]


def test_independent_cache_path_preserves_exact_solution_and_cost() -> None:
    from independent_dr_alns.chain import DrAction, IndependentDrSession

    action = DrAction("worst_customer_removal", "regret2_insert_repair", 0.20, 0.02)
    cached = IndependentDrSession(FIXTURE_DIR, seed=3, max_evals=3, enable_caches=True)
    uncached = IndependentDrSession(FIXTURE_DIR, seed=3, max_evals=3, enable_caches=False)

    cached_rows = [cached.step(action) for _ in range(3)]
    uncached_rows = [uncached.step(action) for _ in range(3)]

    assert [row["after"]["solution_hash"] for row in cached_rows] == [
        row["after"]["solution_hash"] for row in uncached_rows
    ]
    assert [row["after"]["best_obj"] for row in cached_rows] == pytest.approx(
        [row["after"]["best_obj"] for row in uncached_rows]
    )


def test_reused_current_summary_matches_a_fresh_full_recalculation() -> None:
    from independent_dr_alns.chain import DrAction, IndependentDrSession

    session = IndependentDrSession(FIXTURE_DIR, seed=5, max_evals=2)
    session.step(DrAction("worst_customer_removal", "regret2_insert_repair", 0.20, 0.02))

    reused = session.current_summary
    fresh = session._summary(session.current_solution, session.current_obj, best_obj=session.best_obj)
    assert reused["solution_hash"] == fresh["solution_hash"]
    assert reused["violation_count"] == fresh["violation_count"]
    assert reused["objective"] == pytest.approx(fresh["objective"])
    assert reused["metrics"] == pytest.approx(fresh["metrics"])
