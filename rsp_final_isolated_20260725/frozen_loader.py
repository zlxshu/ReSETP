"""Fail-closed exact loader for the frozen kernel and its dependencies."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

from . import runtime


REPO = runtime.REPO
OLD = REPO / "baselines/algorithm_prototypes/resource_slot_pricing_20260725"
EXACT_DEPENDENCIES = (
    ("contracts", "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/contracts.py"),
    ("evaluation", "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/evaluation.py"),
    ("decoder_cache", "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/decoder_cache.py"),
    ("reference_decoder", "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/reference_decoder.py"),
    ("fleet_assignment_dp", "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/fleet_assignment_dp.py"),
    ("mip_core", "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/mip_core.py"),
    ("china81_columns", "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/china81_columns.py"),
    ("pair_mip", "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/pair_mip.py"),
    ("pair_core", "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/pair_core.py"),
    ("lp_duals", "baselines/algorithm_prototypes/dual_guided_resource_order_20260725/lp_duals.py"),
    ("pyvrp_adapter", "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py"),
)


def _resolved_file(module: ModuleType) -> Path:
    value = getattr(module, "__file__", None)
    if not value:
        raise RuntimeError(f"module {module.__name__} has no file identity")
    return Path(value).resolve()


def _exact_load(name: str, path: Path) -> ModuleType:
    expected = path.resolve()
    existing = sys.modules.get(name)
    if existing is not None:
        if _resolved_file(existing) != expected:
            raise RuntimeError(
                f"module collision for {name}: {_resolved_file(existing)} != {expected}"
            )
        return existing
    spec = importlib.util.spec_from_file_location(name, expected)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create exact import spec for {expected}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    if _resolved_file(module) != expected:
        raise RuntimeError(f"exact import identity drift for {name}")
    return module


def load_frozen_stack() -> dict[str, Any]:
    common_existing = sys.modules.get("common")
    if common_existing is not None and common_existing is not runtime:
        raise RuntimeError("bare common alias was already occupied")
    sys.modules["common"] = runtime
    identities: dict[str, str] = {
        "worker_package": __package__ or "",
        "runtime_module": runtime.__name__,
        "runtime_file": str(Path(runtime.__file__).resolve()),
    }
    for name, relative in EXACT_DEPENDENCIES:
        module = _exact_load(name, REPO / relative)
        identities[f"{name}_module"] = module.__name__
        identities[f"{name}_file"] = str(_resolved_file(module))
    pricing = _exact_load("pricing_core", OLD / "pricing_core.py")
    runner = _exact_load(
        "rsp_final_isolated_20260725._frozen_g0_runner",
        OLD / "run_g0.py",
    )
    runner.ENGINEERING = runtime.ENGINEERING
    runner.OUTPUT = runtime.OUTPUT
    identities.update(
        {
            "pricing_module": pricing.__name__,
            "pricing_file": str(_resolved_file(pricing)),
            "runner_module": runner.__name__,
            "runner_file": str(_resolved_file(runner)),
        }
    )
    return {"pricing": pricing, "runner": runner, "identities": identities}

