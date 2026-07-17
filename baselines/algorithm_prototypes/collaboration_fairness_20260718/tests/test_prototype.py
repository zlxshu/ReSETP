from __future__ import annotations

import ast
import csv
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from independent_recompute import recompute  # noqa: E402
from prototype import (  # noqa: E402
    ARMS,
    build_micro_problem,
    candidate_assignments,
    deficit_magnitude_witness,
    evaluate_assignment,
    proximity_removal_order,
    run_arm,
)


def test_all_four_arms_run_all_preregistered_budgets() -> None:
    problem = build_micro_problem()
    for arm in ARMS:
        for budget in (0, 1, 2, 5):
            result = run_arm(problem, arm, budget)
            assert result["complete_evaluations"] == budget
            assert result["budget_respected"] is True


def test_budget_zero_does_not_evaluate_a_candidate() -> None:
    result = run_arm(build_micro_problem(), ARMS[3], 0)
    assert result["complete_evaluations"] == 0
    assert result["candidate_count"] == 0
    assert result["moves"] == []


def test_proximity_removal_changes_customer_order() -> None:
    problem = build_micro_problem()
    base_order = sorted(problem.customer_by_id)
    proximity_order = proximity_removal_order(problem, problem.initial_assignment)
    assert proximity_order != base_order
    base_first = next(candidate_assignments(problem, ARMS[0]))
    proximity_first = next(candidate_assignments(problem, ARMS[1]))
    assert base_first[:2] != proximity_first[:2]


def test_fairness_modified_insertion_changes_recipient_order() -> None:
    problem = build_micro_problem()
    base_first = next(candidate_assignments(problem, ARMS[0]))
    fairness_first = next(candidate_assignments(problem, ARMS[2]))
    assert base_first[0] == fairness_first[0]
    assert base_first[1] != fairness_first[1]


def test_deficit_magnitude_changes_selection() -> None:
    assert deficit_magnitude_witness() == {
        "larger_B_deficit_choice": "B",
        "larger_C_deficit_choice": "C",
    }


def test_independent_recompute_matches_primary_evaluator() -> None:
    problem = build_micro_problem()
    customer_rows = [
        {
            "customer_id": customer.customer_id,
            "revenue": customer.revenue,
            "service_cost": customer.service_cost,
        }
        for customer in problem.customers
    ]
    for arm in ARMS:
        for _, _, assignment in candidate_assignments(problem, arm):
            primary = evaluate_assignment(problem, assignment)
            replay = recompute(
                customer_rows=customer_rows,
                assignment=assignment,
                standalone_profit=problem.standalone_profit,
                theta=problem.theta,
            )
            assert replay["feasible"] is True
            assert replay["total_cost"] == primary.total_cost
            assert replay["profit"] == primary.profit
            assert replay["deficit"] == primary.deficit
            assert replay["total_deficit"] == primary.total_deficit


def test_incomplete_assignment_is_rejected_by_both_evaluators() -> None:
    problem = build_micro_problem()
    incomplete = dict(problem.initial_assignment)
    incomplete.pop("c4")
    primary = evaluate_assignment(problem, incomplete)
    rows = [
        {
            "customer_id": customer.customer_id,
            "revenue": customer.revenue,
            "service_cost": customer.service_cost,
        }
        for customer in problem.customers
    ]
    replay = recompute(
        customer_rows=rows,
        assignment=incomplete,
        standalone_profit=problem.standalone_profit,
        theta=problem.theta,
    )
    assert primary.feasible is False
    assert replay == {"feasible": False}


def test_packaged_rows_and_hashes_close() -> None:
    with (ROOT / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 16
    assert {(row["arm_id"], int(row["budget_limit"])) for row in rows} == {
        (arm.arm_id, budget) for arm in ARMS for budget in (0, 1, 2, 5)
    }
    assert all(
        int(row["complete_evaluations"]) <= int(row["budget_limit"])
        for row in rows
    )

    manifest = json.loads((ROOT / "artifact_hashes.json").read_text(encoding="utf-8"))
    for relative_path, expected in manifest["files"].items():
        actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        assert actual == expected


def test_isolated_sources_do_not_import_formal_solver_or_e7() -> None:
    for filename in ("prototype.py", "independent_recompute.py", "run_probe.py"):
        source = (ROOT / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert all(not name.startswith("setp_solver") for name in imported)
        assert all(not name.startswith("baselines.e7_dynamic") for name in imported)
