import pytest

from dr_alns_ppo.train_ppo import build_env_specs


def test_build_env_specs_default_preserves_one_env_per_bundle() -> None:
    specs = build_env_specs(["bundle-a", "bundle-b", "bundle-c"], seed=10)

    assert [spec["bundle"] for spec in specs] == ["bundle-a", "bundle-b", "bundle-c"]
    assert [spec["seed"] for spec in specs] == [10, 11, 12]
    assert [spec["repeat"] for spec in specs] == [0, 0, 0]


def test_build_env_specs_repeats_training_bundles_with_distinct_seeds() -> None:
    specs = build_env_specs(["bundle-a", "bundle-b", "bundle-c"], seed=1, env_repeats=2)

    assert [spec["bundle"] for spec in specs] == [
        "bundle-a",
        "bundle-b",
        "bundle-c",
        "bundle-a",
        "bundle-b",
        "bundle-c",
    ]
    assert [spec["seed"] for spec in specs] == [1, 2, 3, 4, 5, 6]
    assert [spec["repeat"] for spec in specs] == [0, 0, 0, 1, 1, 1]


def test_build_env_specs_rejects_nonpositive_repeats() -> None:
    with pytest.raises(ValueError, match="env-repeats"):
        build_env_specs(["bundle-a"], seed=1, env_repeats=0)
