from __future__ import annotations

import json
import os

import numpy as np

from baselines.e3_ablation.e3_v3_runner import (
    _cooperation_mobility_row_ok,
    _assert_phase_preconditions,
    default_budget,
    fairness_rejection_count,
    _load_frozen_asset_manifest,
    phase_plans,
    prices_for,
    score_counts,
    summarize_phase,
    task_fingerprint,
)
from setp_solver.algorithms.resetp_alns.kernel.alns_core import (
    AlnsState,
    SearchPolicy,
    cross_depot_boundary_removal,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorSet,
    _forced_cross_depot_pair,
    _selector_coupling_contract,
)
from setp_solver.algorithms.resetp_alns.operators.feasible_repair import repair_removed_customers
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES, UK_2025_PRICES
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Route, Solution


def test_formal_matrix_is_seed_first_and_has_exactly_seventy_rows() -> None:
    plans = phase_plans("formal70", 4000)
    assert len(plans) == 5
    assert sum(len(plan["specs"]) for plan in plans) == 70
    for seed, plan in enumerate(plans, start=1):
        assert plan["seed"] == seed
        assert plan["specs"][0]["layer"] == "M0"
        assert plan["specs"][0]["size"] == "200c"
        assert sum(spec["size"] == "100c" for spec in plan["specs"]) == 4
        assert sum(spec["fee"] > 0 for spec in plan["specs"]) == 4


def test_preflight_separates_plain_cooperation_from_fair_cooperation() -> None:
    specs = phase_plans("preflight", 200)[0]["specs"]
    assert [spec["layer"] for spec in specs] == ["M0", "M1", "M5", "M5"]
    assert [spec["fee"] for spec in specs] == [0.0, 0.0, 0.0, 95.0]


def test_promotion_matrix_is_exactly_thirty_rows() -> None:
    plans = phase_plans("promote100", 4000)
    assert [plan["seed"] for plan in plans] == [6, 7, 8, 9, 10]
    assert sum(len(plan["specs"]) for plan in plans) == 30


def test_short_gate_budgets_are_intentionally_small() -> None:
    assert default_budget("smoke") == 8
    assert default_budget("preflight") == 200
    assert default_budget("rehearsal") == 400
    assert default_budget("model_gate") == 4000


def test_fee_is_an_in_memory_override_only() -> None:
    prices = prices_for("M5", 95.0)
    assert prices.cross_site_cost == 95.0
    assert DEFAULT_PRICES.cross_site_cost == 0.0
    assert prices.B_battery_kwh == 280.0
    assert prices.initial_ev_battery_kwh == 0.0


def test_score_count_aggregation_does_not_double_count_best_phase() -> None:
    result = {
        "operator_counts": {
            "score_counts": {"candidate": 9},
            "staged_chain": {
                "phase_operator_counts": [
                    {"score_counts": {"candidate": 3, "cross_site_complete_candidates": 1}},
                    {"score_counts": {"candidate": 5, "cross_site_complete_candidates": 2}},
                ]
            },
        }
    }
    assert score_counts(result) == {"candidate": 8, "cross_site_complete_candidates": 3}


def test_fairness_rejection_ledger_reads_the_current_precise_key() -> None:
    assert fairness_rejection_count({"strict_reject_profit_fairness": 73}) == 73
    assert fairness_rejection_count({"strict_reject_fairness": 2}) == 2


def test_cross_depot_repair_forces_one_alternate_depot_when_feasible() -> None:
    nodes = [
        Node("D0", "d", 0, 0, due_time=100_000),
        Node("D1", "d", 10, 0, due_time=100_000),
        Node("C1", "c", 1, 0, demand=10, due_time=100_000),
        Node("C2", "c", 9, 0, demand=10, due_time=100_000),
        Node("C3", "c", 2, 0, demand=10, due_time=100_000),
    ]
    matrix = [[0.0 if i == j else 1_000.0 for j in range(len(nodes))] for i in range(len(nodes))]
    instance = Instance(nodes, matrix)
    partial = Solution(routes=[
        Route("CV0", "cv", "D0", ["D0", "C1", "D0"]),
        Route("CV1", "cv", "D1", ["D1", "C2", "D1"]),
    ])
    context = EvaluationContext(
        instance,
        [],
        customer_home_depot={"C1": "D0", "C2": "D1", "C3": "D0"},
    )
    repaired = repair_removed_customers(
        partial,
        ["C3"],
        context,
        SearchPolicy(),
        mode="cross_depot",
    )
    assert repaired is not None
    assert any(route.home_depot_id == "D1" and "C3" in route.node_sequence for route in repaired.routes)
    assert context.score_counts["cross_depot_forced_insertions"] == 1


def test_cross_depot_neighborhood_builds_reciprocal_exchange_when_opted_in() -> None:
    nodes = [
        Node("D0", "d", 0, 0, due_time=100_000),
        Node("D1", "d", 10, 0, due_time=100_000),
        Node("C0a", "c", 1, 0, demand=1000, due_time=100_000),
        Node("C0b", "c", 2, 0, demand=1000, due_time=100_000),
        Node("C1a", "c", 9, 0, demand=1000, due_time=100_000),
        Node("C1b", "c", 8, 0, demand=1000, due_time=100_000),
    ]
    matrix = [[0.0 if i == j else 1_000.0 for j in range(len(nodes))] for i in range(len(nodes))]
    instance = Instance(nodes, matrix)
    owners = {"C0a": "D0", "C0b": "D0", "C1a": "D1", "C1b": "D1"}
    source = Solution(
        routes=[
            Route("CV0", "cv", "D0", ["D0", "C0a", "C0b", "D0"]),
            Route("CV1", "cv", "D1", ["D1", "C1a", "C1b", "D1"]),
        ]
    )
    context = EvaluationContext(
        instance,
        [],
        prices=UK_2025_PRICES,
        fairness_enabled=True,
        independent_profit={"D0": 1.0, "D1": 1.0},
        fairness_theta=1.0,
        customer_home_depot=owners,
    )
    state = AlnsState(source, context, policy=SearchPolicy(reciprocal_cross_depot=True))
    destroyed = cross_depot_boundary_removal(state, np.random.default_rng(7))
    assert len(destroyed.removed_customers) == 2
    assert {owners[customer_id] for customer_id in destroyed.removed_customers} == {"D0", "D1"}
    repaired = repair_removed_customers(
        destroyed.solution,
        list(destroyed.removed_customers),
        context,
        SearchPolicy(reciprocal_cross_depot=True),
        mode="cross_depot",
        allow_new_route=False,
    )
    assert repaired is not None
    for customer_id in destroyed.removed_customers:
        owner = owners[customer_id]
        assert any(
            route.home_depot_id != owner and customer_id in route.node_sequence
            for route in repaired.routes
        )
    assert context.score_counts["reciprocal_cross_depot_pair_removals"] == 1
    assert context.score_counts["cross_depot_forced_insertions"] == 2


def test_cross_depot_operator_is_isolated_to_strict_e3(monkeypatch) -> None:
    monkeypatch.delenv("SETP_E3_STRICT_MULTITRIP", raising=False)
    assert "cross_depot_insert_repair" not in {name for name, _ in WinnerOperatorSet.create().repair_ops}
    assert "cross_depot_boundary_removal" not in {name for name, _ in WinnerOperatorSet.create().destroy_ops}
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")
    assert "cross_depot_insert_repair" in {name for name, _ in WinnerOperatorSet.create().repair_ops}
    assert "cross_depot_boundary_removal" in {name for name, _ in WinnerOperatorSet.create().destroy_ops}
    disabled = WinnerOperatorSet.create(
        allow_cross_depot=True,
        enable_cross_depot_operator=False,
    )
    assert "cross_depot_insert_repair" not in {name for name, _ in disabled.repair_ops}
    assert "cross_depot_boundary_removal" not in {name for name, _ in disabled.destroy_ops}
    assert os.environ["SETP_E3_STRICT_MULTITRIP"] == "1"
    operators = WinnerOperatorSet.create()
    coupling = _selector_coupling_contract(operators)
    destroy_names = [name for name, _ in operators.destroy_ops]
    repair_names = [name for name, _ in operators.repair_ops]
    destroy_idx = destroy_names.index("cross_depot_boundary_removal")
    repair_idx = repair_names.index("cross_depot_insert_repair")
    assert coupling[destroy_idx, repair_idx]
    assert coupling[:, repair_idx].sum() == 1
    assert coupling[destroy_idx, :].sum() == 1
    context = EvaluationContext(
        Instance(
            [Node("D0", "d", 0, 0), Node("D1", "d", 1, 0), Node("C1", "c", 0, 0)],
            [[0.0, 1.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]],
        ),
        [],
        budget=EvalBudget(limit=200, target=200),
        customer_home_depot={"C1": "D0"},
    )
    assert _forced_cross_depot_pair(operators, context) == (destroy_idx, repair_idx)
    context.score_counts["cross_depot_forced_operator_calls"] = 1
    assert _forced_cross_depot_pair(operators, context) is None
    context.budget.count = 100
    assert _forced_cross_depot_pair(operators, context) == (destroy_idx, repair_idx)


def test_preflight_cannot_pass_when_cooperation_never_makes_a_legal_move(tmp_path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    plans = [{
        "seed": 1,
        "sizes": ["200c"],
        "specs": [
            {"run_id": "independent", "layer": "M0", "budget": 2},
            {"run_id": "cooperative", "layer": "M1", "budget": 2},
        ],
    }]
    common = {
        "status": "OK",
        "actual_evals": 2,
        "budget": 2,
        "violation_count": 0,
        "cost_component_error": 0.0,
        "fee_override_verified": True,
        "search_cross_site_fee_error": 0.0,
    }
    (runs / "independent.json").write_text(
        json.dumps({**common, "run_id": "independent", "layer": "M0"}),
        encoding="utf-8",
    )
    cooperative = {
        **common,
        "run_id": "cooperative",
        "layer": "M1",
        "cross_site_attempted_candidates": 1,
        "cross_site_legal_candidates": 0,
    }
    cooperative_path = runs / "cooperative.json"
    cooperative_path.write_text(json.dumps(cooperative), encoding="utf-8")
    assert summarize_phase(tmp_path, "preflight", plans)["verdict"] == "HALT_E3_PREFLIGHT"
    cooperative["cross_site_legal_candidates"] = 1
    cooperative_path.write_text(json.dumps(cooperative), encoding="utf-8")
    assert summarize_phase(tmp_path, "preflight", plans)["verdict"] == "E3_PREFLIGHT_PASS"
    hashes = json.loads((tmp_path / "preflight" / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert "runs/independent.json" in hashes
    assert "runs/cooperative.json" in hashes


def test_fair_cooperation_may_reject_unfair_moves_but_must_record_why() -> None:
    row = {
        "cross_site_attempted_candidates": 3,
        "cross_site_legal_candidates": 0,
        "fairness_enabled": True,
        "fairness_search_active_evidence": json.dumps({"rejected_candidates": 3}),
    }
    assert _cooperation_mobility_row_ok(row)
    row["fairness_search_active_evidence"] = json.dumps({"rejected_candidates": 0})
    assert not _cooperation_mobility_row_ok(row)


def test_formal_phase_requires_every_prior_gate(tmp_path) -> None:
    for phase in ("preflight", "model_gate", "rehearsal"):
        phase_dir = tmp_path / phase
        phase_dir.mkdir()
        (phase_dir / "decision.json").write_text(
            json.dumps({"verdict": f"E3_{phase.upper()}_PASS"}),
            encoding="utf-8",
        )
    _assert_phase_preconditions(tmp_path, "formal70")
    (tmp_path / "rehearsal" / "decision.json").write_text(
        json.dumps({"verdict": "HALT_E3_REHEARSAL"}), encoding="utf-8"
    )
    try:
        _assert_phase_preconditions(tmp_path, "formal70")
    except ValueError as exc:
        assert "did not pass" in str(exc)
    else:
        raise AssertionError("formal phase bypassed a failed rehearsal gate")


def test_frozen_asset_manifest_rejects_file_drift(tmp_path, monkeypatch) -> None:
    from baselines.e3_ablation import e3_v3_runner as runner

    asset = tmp_path / "asset.json"
    asset.write_text("stable\n", encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "CONTRACT_PATH", tmp_path / "contract.json")
    monkeypatch.setattr(runner, "OWNER_ROWS", tmp_path / "owners.csv")
    runner.CONTRACT_PATH.write_text("{}\n", encoding="utf-8")
    runner.OWNER_ROWS.write_text("owner\n", encoding="utf-8")
    manifest = {
        "schema": "setp.e3.assets.v2",
        "size": "200c",
        "instance": runner.INSTANCE_NAMES["200c"],
        "contract_sha256": runner.sha256(runner.CONTRACT_PATH),
        "owner_rows_sha256": runner.sha256(runner.OWNER_ROWS),
        "strict_contract_id": runner.CONTRACT_ID,
        "asset_hashes": {"asset.json": runner.sha256(asset)},
    }
    manifest_path = tmp_path / "asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert _load_frozen_asset_manifest(manifest_path, "200c") == manifest
    asset.write_text("changed\n", encoding="utf-8")
    try:
        _load_frozen_asset_manifest(manifest_path, "200c")
    except ValueError as exc:
        assert "asset changed" in str(exc)
    else:
        raise AssertionError("changed frozen asset was accepted")


def test_task_fingerprint_ignores_evidence_only_git_commits(monkeypatch) -> None:
    manifest = {"schema": "setp.e3.assets.v2", "asset_hashes": {"x": "y"}}
    spec = {"run_id": "same-run", "layer": "M1", "budget": 2}
    monkeypatch.setattr("baselines.e3_ablation.e3_v3_runner.closure.git_head", lambda: "commit-a")
    first = task_fingerprint(spec, manifest)
    monkeypatch.setattr("baselines.e3_ablation.e3_v3_runner.closure.git_head", lambda: "commit-b")
    assert task_fingerprint(spec, manifest) == first
