from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    _apply_joint_pi0_record,
    _load_registered_initial_solution,
    main,
)
from setp_solver.mapping_identity import mapping_sha256  # noqa: E402


@dataclass(frozen=True)
class _Context:
    independent_profit: dict[str, float]
    independent_profit_identity: object
    theta: float
    fairness_enabled: bool


def _bundle():
    return SimpleNamespace(
        instance=SimpleNamespace(
            nodes=(
                SimpleNamespace(node_id="D0", node_type="d"),
                SimpleNamespace(node_id="D1", node_type="d"),
                SimpleNamespace(node_id="C1", node_type="c"),
            )
        )
    )


def test_joint_pi0_record_opens_real_participation_context() -> None:
    values = {"D0": 100.0, "D1": 200.0}
    context = _Context({}, object(), 0.0, False)

    pi0, wired = _apply_joint_pi0_record(
        _bundle(),
        context,
        {
            "values": values,
            "source_id": "standalone-one-seed",
            "value_sha256": mapping_sha256(values),
            "externally_frozen": True,
        },
    )

    assert pi0 == values
    assert wired.independent_profit == values
    assert wired.fairness_enabled is True
    assert wired.theta == 1.0
    assert wired.independent_profit_identity.externally_frozen is True
    assert wired.independent_profit_identity.source_id == "standalone-one-seed"
    assert wired.independent_profit_identity.value_sha256 == mapping_sha256(values)


def test_joint_pi0_record_rejects_wrong_depot_set() -> None:
    values = {"D0": 100.0}
    with pytest.raises(ValueError, match="depot set differs"):
        _apply_joint_pi0_record(
            _bundle(),
            _Context({}, object(), 0.0, False),
            {
                "values": values,
                "source_id": "source",
                "value_sha256": mapping_sha256(values),
                "externally_frozen": True,
            },
        )


def test_private_runner_rejects_enterprise_and_pi0_together(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_problem_hgs_private_technical.py",
            str(tmp_path / "output"),
            "--enterprise-id",
            "ENT_A",
            "--pi0-manifest",
            str(tmp_path / "pi0.json"),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2


def test_saved_solution_is_loaded_and_registered(monkeypatch, tmp_path) -> None:
    solution_path = tmp_path / "warmstart.json"
    solution_path.write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "vehicle_id": "CV_D0_1#T1",
                        "vehicle_type": "cv",
                        "home_depot_id": "D0",
                        "node_sequence": ["D0", "C1", "D0"],
                    }
                ],
                "charging_actions": [],
                "cross_site_services": [],
            }
        ),
        encoding="utf-8",
    )
    captured = {}
    monkeypatch.setattr(
        "run_problem_hgs_private_technical.register_all_vehicle_slots",
        lambda individual, bundle: captured.setdefault("individual", individual),
    )

    loaded = _load_registered_initial_solution(solution_path, _bundle())

    assert loaded is captured["individual"]
    assert {
        customer
        for duty in loaded.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    } == {"C1"}
    assert loaded.source.startswith("external-initial/")
