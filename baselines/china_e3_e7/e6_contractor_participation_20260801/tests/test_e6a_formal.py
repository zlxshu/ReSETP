#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_e6a_formal as formal
import run_pilot06_direct_15 as runner
from e6_methods import coalition_revenue, coalitions, subset_bundle


def test_formal_source_audit_matches_current_approved_sources() -> None:
    audit = formal.source_audit()
    assert audit["all_sources_match"]
    assert audit["approved_pilot_manifest_match"]


def test_method_a_contains_shapley_and_core_only() -> None:
    instance_id = "cn-prd-150c-01-V2-LOCATIONS"
    base, _ = runner.load_base(instance_id, formal.APPROVED_MAPPING_SHA256[instance_id])
    members = tuple(sorted(base.fleet_caps_by_depot))
    member_cost = {member: 100.0 + index for index, member in enumerate(members)}
    results = {}
    for group in coalitions(members):
        bundle = subset_bundle(base, group)
        results[group] = {
            "bundle": bundle,
            "cost": sum(member_cost[member] for member in group),
        }
        assert coalition_revenue(bundle) > results[group]["cost"]

    settlement = runner.method_a_results(base, members, results)
    assert set(settlement) == {
        "standalone_profit_cny",
        "coalition_cost_cny",
        "coalition_profit_cny",
        "method_A",
        "revenue_assignment",
    }
    assert settlement["method_A"]["core_nonempty"]
    assert settlement["method_A"]["shapley_in_core"]


def test_run_unit_delegates_only_approved_method(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run(output, initial, **kwargs):
        captured.update(output=output, initial=initial, **kwargs)
        return {"status": "PASS_TEST"}

    monkeypatch.setattr(runner, "run", fake_run)
    result = formal.run_unit(
        tmp_path / "unit",
        instance_id="cn-prd-150c-01-V2-LOCATIONS",
        seed=7,
    )
    assert result == {"status": "PASS_TEST"}
    assert captured["initial"] == runner.MULTI_MEMBER_INITIAL_COMMON
    assert captured["include_method_b"] is False
    assert captured["evidence_role"] == "FORMAL_PANEL_UNIT"
    assert captured["resume"] is True
    assert captured["seed"] == 7
    assert captured["iterations"] == formal.FORMAL_ITERATIONS
    assert captured["archive"] == formal.FORMAL_ARCHIVE
    assert captured["sp_seconds"] == formal.FORMAL_SP_SECONDS


def test_pilot_output_is_protected() -> None:
    with pytest.raises(ValueError, match="must not overwrite"):
        formal.run_unit(
            runner.COMMON_OUTPUT,
            instance_id="cn-prd-150c-01-V2-LOCATIONS",
            seed=1,
        )
