"""Regression tests for family-local E3 capacity HALTs."""

from __future__ import annotations

import importlib.util
import csv
import hashlib
import json
import sys
import types
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run_e3_scattered_ownership.py")
RUNTIME_NAME = "baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime"
_STUBBED_MODULE_NAMES = (
    "route_pool_sp",
    "setp_solver.china81_completion",
    RUNTIME_NAME,
)
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _STUBBED_MODULE_NAMES}

ROUTE_POOL_SP = types.ModuleType("route_pool_sp")
ROUTE_POOL_SP.run_hgs_route_pool_recombination = lambda *args, **kwargs: None
sys.modules["route_pool_sp"] = ROUTE_POOL_SP

COMPLETION = types.ModuleType("setp_solver.china81_completion")
COMPLETION.exact_china81_score = lambda *args, **kwargs: None
sys.modules["setp_solver.china81_completion"] = COMPLETION

RUNTIME = types.ModuleType(RUNTIME_NAME)
RUNTIME.build_common_initial = lambda _bundle: (None, {})
RUNTIME.canonical_sha256 = lambda payload: hashlib.sha256(
    json.dumps(payload, sort_keys=True).encode()
).hexdigest()
RUNTIME.load_bundle = lambda _instance: None
RUNTIME.solution_sha256 = lambda _solution: ""


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


RUNTIME.write_json = _write_json
RUNTIME.write_csv = _write_csv
sys.modules[RUNTIME_NAME] = RUNTIME
SPEC = importlib.util.spec_from_file_location("run_e3_scattered_ownership", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
try:
    SPEC.loader.exec_module(RUNNER)
finally:
    for _name, _original in _ORIGINAL_MODULES.items():
        if _original is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _original


def _info(family: str, shortfall: float) -> dict[str, object]:
    return {
        "instance_id": "test-instance",
        "source_family": family,
        "fleet_caps_by_depot": {"D_test": {"num_cv": 1, "num_ev": 0}},
        "available_cv_total": 1,
        "available_ev_total": 0,
        "capacity_audit": {
            "D_test": {
                "assigned_demand_kg": 100.0 + shortfall,
                "available_payload_kg": 100.0,
                "capacity_shortfall_kg": shortfall,
            }
        },
        "mapping_sha256": f"mapping-{family}",
        "initial_sha256": f"initial-{family}",
    }


def test_capacity_halt_is_local_to_its_family(monkeypatch, tmp_path: Path) -> None:
    """A failed family records its HALT but cannot suppress another family's seeds."""

    monkeypatch.setattr(RUNNER, "FAMILIES", ("halted", "runnable"))
    monkeypatch.setattr(
        RUNNER,
        "prepare",
        lambda _instance, family: (
            f"bundle-{family}",
            f"initial-{family}",
            _info(family, 1.0 if family == "halted" else 0.0),
        ),
    )
    calls: list[tuple[str, int]] = []

    def fake_run_pair(bundle, _initial, _info, seed, _iterations, _archive):
        calls.append((bundle, seed))
        return []

    monkeypatch.setattr(RUNNER, "_run_pair", fake_run_pair)

    decision = RUNNER.run_pilot(tmp_path / "pilot")

    assert calls == [("bundle-runnable", 1), ("bundle-runnable", 2), ("bundle-runnable", 3)]
    assert decision["capacity_shortfalls"] == {"halted": _info("halted", 1.0)["capacity_audit"]}
    assert decision["attempted_seeds_by_family"] == {
        "halted": [1],
        "runnable": [1, 2, 3],
    }
    assert decision["not_started_seeds_by_family"] == {
        "halted": [2, 3],
        "runnable": [],
    }
    assert decision["search_started_families"] == ["runnable"]
