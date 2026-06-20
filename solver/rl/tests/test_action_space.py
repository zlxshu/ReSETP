import pytest

from dr_alns_ppo.action_space import (
    BLOCK_ACTION_NVECS,
    BLOCK_DESTROY_IDS,
    BLOCK_REPAIR_IDS,
    DESTROY_IDS,
    REDUCED_ACTION_NVECS,
    REPAIR_IDS,
    decode_action,
    decode_block_action,
)


def test_decode_action_maps_multi_discrete_components() -> None:
    action = decode_action([5, 2, 9, 99], base_temperature=100.0)

    assert len(DESTROY_IDS) == 6
    assert len(REPAIR_IDS) == 3
    assert action.destroy_id == "vehicle_type_swap"
    assert action.repair_id == "regret3_insert_repair"
    assert abs(action.q_ratio - 0.40) < 1e-12
    assert abs(action.threshold_ratio - 0.02) < 1e-12
    assert action.control_mode == "ppo_full"


def test_decode_action_has_lower_q_bound_not_fixed_one_customer() -> None:
    action = decode_action([0, 0, 0, 0], base_temperature=100.0)

    assert action.destroy_id == "random_customer_removal"
    assert action.repair_id == "greedy_insert_repair"
    assert abs(action.q_ratio - 0.10) < 1e-12
    assert action.threshold_ratio == 0.0


def test_decode_action_preserves_raw_tuple_after_coercion() -> None:
    action = decode_action((1, 2, 3, 4), base_temperature=50.0)

    assert action.raw == (1, 2, 3, 4)


def test_decode_action_accepts_numpy_array_input_if_available() -> None:
    np = pytest.importorskip("numpy")

    action = decode_action(np.array([2, 1, 6, 50]), base_temperature=100.0)

    assert action.destroy_id == "shaw_related_removal"
    assert action.repair_id == "regret2_insert_repair"
    assert action.raw == (2, 1, 6, 50)


def test_decode_action_operator_only_uses_two_components_and_kernel_defaults() -> None:
    action = decode_action([5, 2], base_temperature=100.0, control_mode="operator_only")

    assert action.destroy_id == "vehicle_type_swap"
    assert action.repair_id == "regret3_insert_repair"
    assert action.q_ratio is None
    assert action.threshold_ratio == 0.0
    assert action.raw == (5, 2)
    assert action.control_mode == "operator_only"


def test_decode_action_reduced_full_uses_coarse_q_and_threshold() -> None:
    action = decode_action([5, 1, 2, 2], base_temperature=100.0, control_mode="reduced_full")

    assert REDUCED_ACTION_NVECS == (6, 3, 3, 3)
    assert action.destroy_id == "vehicle_type_swap"
    assert action.repair_id == "regret2_insert_repair"
    assert action.q_ratio == 0.40
    assert action.threshold_ratio == 0.02
    assert action.raw == (5, 1, 2, 2)
    assert action.control_mode == "reduced_full"


def test_decode_action_rejects_invalid_length() -> None:
    with pytest.raises(ValueError, match="Expected 4 action components"):
        decode_action([0, 0, 0], base_temperature=100.0)


def test_decode_action_rejects_out_of_range_component() -> None:
    with pytest.raises(ValueError, match="destroy index out of range"):
        decode_action([6, 0, 0, 0], base_temperature=100.0)


def test_decode_action_rejects_non_integer_float_component() -> None:
    with pytest.raises(ValueError, match="action component must be an integer value"):
        decode_action([0, 1.2, 0, 0], base_temperature=100.0)


def test_decode_block_action_maps_online_controller_components() -> None:
    action = decode_block_action([6, 3, 4, 3, 2], block_size=256)

    assert BLOCK_ACTION_NVECS == (7, 4, 5, 4, 4)
    assert BLOCK_DESTROY_IDS[-1] == "alpha_ucb"
    assert BLOCK_REPAIR_IDS[-1] == "alpha_ucb"
    assert action.destroy_id == "alpha_ucb"
    assert action.repair_id == "alpha_ucb"
    assert action.q_ratio == 0.40
    assert action.threshold_ratio == 0.02
    assert action.exploration_ratio == 0.15
    assert action.block_size == 256
    assert action.control_mode == "block_ppo"


def test_decode_block_action_rejects_invalid_shape() -> None:
    with pytest.raises(ValueError, match="Expected 5 block action components"):
        decode_block_action([0, 0, 0, 0])
