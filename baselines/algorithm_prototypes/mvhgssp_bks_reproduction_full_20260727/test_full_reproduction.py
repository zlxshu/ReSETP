import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_full_reproduction",
        HERE / "run_full_reproduction.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_target_table_has_18_unique_certified_targets():
    module = _module()
    targets = module._targets()
    assert len(targets) == 18
    assert len(set(targets)) == 18
    assert all(values["target"] < values["bks_2013"] for values in targets.values())


def test_frozen_prior_is_exactly_two_targets():
    module = _module()
    assert module.SEALED == {"PR19A", "PR23A"}
    assert module.SEALED < set(module._targets())
