from __future__ import annotations

import json
from pathlib import Path

import pytest

from baselines.e2_alns import run_cvrplib_optimal_benchmark_20260716 as runner
from baselines.paper_story import build_e2_cvrplib_paper_evidence_20260716 as paper_builder


def _contract(eval_budget: int = 4000) -> dict:
    return {
        "contract_sha256": "frozen-contract",
        "eval_budget": eval_budget,
        "max_runtime_seconds": 10.0,
        "bundle_hashes": {"X-n101-k25": {"instance.json": "a"}},
        "bks_scalars": {"X-n101-k25": 27591},
    }


def _task(eval_budget: int = 4000) -> dict:
    return runner.expected_task("X-n101-k25", 1, _contract(eval_budget))


def _row(task: dict) -> dict:
    return {
        "task_key": task["task_key"],
        "instance": task["instance"],
        "seed": task["seed"],
        "eval_budget": task["eval_budget"],
        "published_optimum": task["published_optimum"],
        "evaluations": task["eval_budget"],
        "candidate_scores": task["eval_budget"],
        "repair_delta_count": 10,
        "best_cost": 30000.0,
        "generic_cost": 30000.0,
        "pure_cost": 30000.0,
        "feasible": True,
        "violation_count": 0,
        "objective_match": True,
        "pure_recomputation": {"passed": True, "failures": []},
        "status": "OK",
    }


def test_formal_matrix_is_exactly_six_by_ten_by_4000() -> None:
    assert len(runner.FORMAL_INSTANCES) == 6
    assert runner.FORMAL_SEEDS == tuple(range(1, 11))
    assert runner.FORMAL_EVAL_BUDGET == 4000
    assert len(
        [
            (instance, seed)
            for instance in runner.FORMAL_INSTANCES
            for seed in runner.FORMAL_SEEDS
        ]
    ) == 60


def test_worker_limit_is_hard_gate(monkeypatch) -> None:
    monkeypatch.setattr(runner, "load_bks_manifest", lambda: {"instances": {}})
    with pytest.raises(runner.FormalRunError, match="workers"):
        runner.build_contract(
            instances=(), seeds=(1,), eval_budget=4000, workers=5,
            max_runtime_seconds=1.0, bundles={}
        )


def test_gold_environment_requires_parent_hashseed(monkeypatch) -> None:
    monkeypatch.setattr(runner.sys, "executable", runner.GOLD_PYTHON)
    monkeypatch.setattr(runner.np, "__version__", runner.GOLD_NUMPY)
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    with pytest.raises(runner.FormalRunError, match="before the parent"):
        runner.verify_gold_environment()


def test_winner_metrics_contract_fails_before_search_when_fields_are_missing() -> None:
    valid_source = """
def _run_staged_hybrid_entry():
    return {
        "candidate_scores": 1,
        "repair_scores": 1,
        "repair_delta_count": 1,
    }
"""
    assert runner.winner_result_contract_failures(valid_source) == []

    invalid_source = """
def _run_staged_hybrid_entry():
    return {"history": []}
"""
    assert runner.winner_result_contract_failures(invalid_source) == [
        "winner result field missing: candidate_scores",
        "winner result field missing: repair_scores",
        "winner result field missing: repair_delta_count",
    ]


def test_pure_recompute_checks_distance_coverage_and_capacity() -> None:
    solution = {"routes": [{"node_sequence": ["D0", "C1", "C2", "D0"]}]}
    valid = runner.pure_cvrp_recompute(
        solution,
        node_ids=["D0", "C1", "C2"],
        demands={"D0": 0.0, "C1": 2.0, "C2": 3.0},
        capacity=5.0,
        depot_id="D0",
        distance_matrix=[[0, 1, 4], [1, 0, 2], [4, 2, 0]],
    )
    assert valid["passed"] is True
    assert valid["total_distance"] == 7.0

    invalid = runner.pure_cvrp_recompute(
        solution,
        node_ids=["D0", "C1", "C2"],
        demands={"D0": 0.0, "C1": 2.0, "C2": 3.0},
        capacity=4.0,
        depot_id="D0",
        distance_matrix=[[0, 1, 4], [1, 0, 2], [4, 2, 0]],
    )
    assert invalid["passed"] is False
    assert any("capacity" in failure for failure in invalid["failures"])


def test_checkpoint_is_atomic_hash_checked_and_budget_bound(tmp_path) -> None:
    tasks_dir = tmp_path / ".tasks"
    tasks_dir.mkdir()
    task = _task(4000)
    path = runner._task_path(tasks_dir, task)
    runner._save_task_checkpoint(path, "frozen-contract", task, _row(task))
    assert not list(tasks_dir.glob("*.tmp-*"))
    assert runner._load_task_checkpoint(path, "frozen-contract", task)["eval_budget"] == 4000

    smoke_task = _task(1000)
    with pytest.raises(runner.TaskCheckpointError, match="identity differs"):
        runner._load_task_checkpoint(path, "frozen-contract", smoke_task)

    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["status"] = "tampered"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(runner.TaskCheckpointError, match="hash differs"):
        runner._load_task_checkpoint(path, "frozen-contract", task)


def test_checkpoint_rejects_payload_identity_or_false_ok(tmp_path) -> None:
    tasks_dir = tmp_path / ".tasks"
    tasks_dir.mkdir()
    task = _task()
    wrong_identity = {**_row(task), "seed": 9}
    path = runner._task_path(tasks_dir, task)
    runner._save_task_checkpoint(path, "frozen-contract", task, wrong_identity)
    with pytest.raises(runner.TaskCheckpointError, match="seed differs"):
        runner._load_task_checkpoint(path, "frozen-contract", task)

    false_ok = {**_row(task), "pure_cost": 30001.0}
    runner._save_task_checkpoint(path, "frozen-contract", task, false_ok)
    with pytest.raises(runner.TaskCheckpointError, match="objective values differ"):
        runner._load_task_checkpoint(path, "frozen-contract", task)

    false_count = {**_row(task), "candidate_scores": 3999}
    runner._save_task_checkpoint(path, "frozen-contract", task, false_count)
    with pytest.raises(runner.TaskCheckpointError, match="candidate-score count"):
        runner._load_task_checkpoint(path, "frozen-contract", task)


def test_load_completed_rejects_unexpected_checkpoint(tmp_path) -> None:
    tasks_dir = tmp_path / ".tasks"
    tasks_dir.mkdir()
    (tasks_dir / "foreign.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(runner.ContractMismatchError, match="unexpected"):
        runner.load_completed(tasks_dir, _contract(), [_task()])


def test_contract_resume_rejects_source_or_budget_drift(tmp_path) -> None:
    contract = {"schema_version": runner.CONTRACT_SCHEMA, "contract_sha256": "one", "eval_budget": 4000}
    stored = {**contract, "created_at_utc": "now", "source_commit_at_start": "commit"}
    runner.atomic_write_json(tmp_path / "contract.json", stored)
    assert runner.ensure_contract(tmp_path, contract) == stored
    with pytest.raises(runner.ContractMismatchError, match="differs"):
        runner.ensure_contract(tmp_path, {**contract, "eval_budget": 1000})


def test_failure_row_retains_task_identity() -> None:
    task = _task()
    row = runner.failure_row(task, RuntimeError("boom"))
    assert row["task_key"] == task["task_key"]
    assert row["eval_budget"] == 4000
    assert row["status"].startswith("ERROR:RuntimeError")
    assert row["feasible"] is False


def test_bks_manifest_is_scalar_and_matches_frozen_sources() -> None:
    manifest = runner.load_bks_manifest()
    assert set(manifest["instances"]) == set(runner.FORMAL_INSTANCES)
    assert all(row["official_opt"] for row in manifest["instances"].values())
    assert all(isinstance(row["published_optimum"], int) for row in manifest["instances"].values())
    snapshot = json.loads(runner.OFFICIAL_PAGE_SNAPSHOT.read_text(encoding="utf-8"))
    assert set(snapshot["instances"]) == set(runner.FORMAL_INSTANCES)
    assert all(row["opt"] == "yes" for row in snapshot["instances"].values())


def test_contract_hashes_entire_solver_source_surface() -> None:
    paths = set(runner._source_paths())
    solver_root = runner.REPO / "solver/src/setp_solver"
    expected = set(solver_root.rglob("*.py"))
    assert expected <= paths
    assert runner.OFFICIAL_PAGE_SNAPSHOT.resolve() in paths
    assert solver_root / "prices.py" in paths
    assert solver_root / "algorithms/resetp_alns/kernel/winner.py" in paths


def test_formal_resume_never_creates_or_overwrites_bundle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "BUNDLE_ROOT", tmp_path / "bundles")
    with pytest.raises(runner.FormalRunError, match="original read-only bundle"):
        runner.prepare_all_bundles(("X-n101-k25",), allow_create=False)

    bundle = runner.BUNDLE_ROOT / "X-n101-k25"
    bundle.mkdir(parents=True)
    for filename in ("instance.json", "distance_matrix.npy", "carbon_profile.csv"):
        (bundle / filename).write_bytes(filename.encode("utf-8"))
    before = runner.bundle_hashes(bundle)
    monkeypatch.setattr(
        runner,
        "prepare_bundle",
        lambda _name: pytest.fail("resume attempted to rewrite a frozen bundle"),
    )
    observed = runner.prepare_all_bundles(("X-n101-k25",), allow_create=False)
    assert observed["X-n101-k25"] == before
    assert runner.bundle_hashes(bundle) == before


def test_run_task_has_no_solution_file_read(monkeypatch) -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    function_source = source[source.index("def run_task("):source.index("def _task_path(")]
    assert "parse_solution" not in function_source
    assert '.sol' not in function_source


def test_artifact_hashes_exclude_internal_checkpoints(tmp_path) -> None:
    (tmp_path / ".tasks").mkdir()
    (tmp_path / ".tasks" / "task.json").write_text("checkpoint", encoding="utf-8")
    (tmp_path / "report.md").write_text("report", encoding="utf-8")
    hashes = {
        str(path.relative_to(tmp_path)): runner.sha256(path)
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file() and ".tasks" not in path.parts
    }
    assert hashes == {"report.md": runner.sha256(tmp_path / "report.md")}


def _formal_output_contract() -> dict:
    return {
        "contract_sha256": "formal-test-contract",
        "instances": list(runner.FORMAL_INSTANCES),
        "seeds": list(runner.FORMAL_SEEDS),
        "eval_budget": runner.FORMAL_EVAL_BUDGET,
        "workers": runner.FORMAL_WORKERS,
        "max_runtime_seconds": 1800.0,
        "environment": {
            "python_executable": runner.GOLD_PYTHON,
            "numpy_version": runner.GOLD_NUMPY,
            "pythonhashseed": "0",
        },
    }


def _formal_output_rows() -> list[dict]:
    optima = {
        "X-n101-k25": 27591,
        "X-n120-k6": 13332,
        "X-n200-k36": 58578,
        "X-n214-k11": 10856,
        "X-n313-k71": 94043,
        "X-n322-k28": 29834,
    }
    rows = []
    for instance in runner.FORMAL_INSTANCES:
        for seed in runner.FORMAL_SEEDS:
            optimum = optima[instance]
            objective = float(optimum + seed)
            rows.append(
                {
                    "task_key": runner.task_key(instance, seed),
                    "instance": instance,
                    "seed": seed,
                    "customers": 100,
                    "eval_budget": 4000,
                    "evaluations": 4000,
                    "candidate_scores": 4000,
                    "repair_delta_count": 10,
                    "best_cost": objective,
                    "generic_cost": objective,
                    "pure_cost": objective,
                    "independent_cost": objective,
                    "published_optimum": optimum,
                    "gap_pct": 100.0 * (objective - optimum) / optimum,
                    "elapsed_seconds": 1.0,
                    "feasible": True,
                    "violation_count": 0,
                    "route_count": 1,
                    "status": "OK",
                    "failure_codes": [],
                    "started_at_utc": "start",
                    "finished_at_utc": "finish",
                    "objective_match": True,
                    "solution": {},
                    "pure_recomputation": {"passed": True, "failures": []},
                }
            )
    return rows


def test_write_outputs_requires_exact_matrix_and_builds_all_evidence_surfaces(tmp_path) -> None:
    out = tmp_path / "formal"
    out.mkdir()
    runner.write_outputs(out, _formal_output_rows(), _formal_output_contract())
    decision = json.loads((out / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "E2_CVRPLIB_FORMAL_COMPLETE"
    assert decision["matrix_complete"] is True
    required = {
        "raw_runs.csv",
        "metadata.json",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
        "summary_by_instance.csv",
        "summary_by_tier.csv",
        "solutions_and_independent_recomputation.json",
    }
    assert required <= {path.name for path in out.iterdir()}
    hashes = json.loads((out / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert "report.md" in hashes
    assert "solutions_and_independent_recomputation.json" in hashes
    assert not any(path.startswith(".tasks/") for path in hashes)
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "## 规模分层" in report
    assert "| small | 20 | 20 |" in report
    assert "## 失败与异常任务" in report
    assert "全60项任务均为OK" in report

    duplicate_out = tmp_path / "duplicate"
    duplicate_out.mkdir()
    rows = _formal_output_rows()
    rows[-1] = dict(rows[0])
    runner.write_outputs(duplicate_out, rows, _formal_output_contract())
    duplicate_decision = json.loads((duplicate_out / "decision.json").read_text(encoding="utf-8"))
    assert duplicate_decision["matrix_complete"] is False
    assert duplicate_decision["verdict"] == "E2_CVRPLIB_INCOMPLETE_OR_INVALID"


def test_write_outputs_reports_every_failed_task(tmp_path) -> None:
    out = tmp_path / "failed"
    out.mkdir()
    rows = _formal_output_rows()
    rows[0] = {
        **rows[0],
        "status": "ERROR:RuntimeError",
        "feasible": False,
        "failure_codes": ["ERROR:RuntimeError"],
    }
    runner.write_outputs(out, rows, _formal_output_contract())
    report = (out / "report.md").read_text(encoding="utf-8")
    assert rows[0]["task_key"] in report
    assert "ERROR:RuntimeError" in report
    decision = json.loads((out / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "E2_CVRPLIB_INCOMPLETE_OR_INVALID"


def test_paper_builder_requires_complete_formal_matrix_and_renders_table(tmp_path) -> None:
    source = tmp_path / "formal"
    output = tmp_path / "paper"
    source.mkdir()
    runner.write_outputs(source, _formal_output_rows(), _formal_output_contract())

    provenance = paper_builder.build(source, output)

    table = (output / paper_builder.TABLE_NAME).read_text(encoding="utf-8")
    interpretation = (output / paper_builder.INTERPRETATION_NAME).read_text(
        encoding="utf-8"
    )
    assert all(instance in table for instance in runner.FORMAL_INSTANCES)
    assert table.count("/10") == 7  # one header plus six instance rows
    assert "小、中和大规模" in interpretation
    assert "60项任务均通过" in interpretation
    assert provenance["source_matrix_complete"] is True
    assert provenance["source_all_valid"] is True


def test_paper_builder_preserves_failed_task_instead_of_demanding_rescue(tmp_path) -> None:
    source = tmp_path / "formal"
    output = tmp_path / "paper"
    source.mkdir()
    rows = _formal_output_rows()
    rows[0] = {
        **rows[0],
        "status": "ERROR:RuntimeError",
        "feasible": False,
        "failure_codes": ["ERROR:RuntimeError"],
    }
    runner.write_outputs(source, rows, _formal_output_contract())

    provenance = paper_builder.build(source, output)

    table = (output / paper_builder.TABLE_NAME).read_text(encoding="utf-8")
    interpretation = (output / paper_builder.INTERPRETATION_NAME).read_text(
        encoding="utf-8"
    )
    assert "9/10 & 1" in table
    assert "有1项失败或无效" in interpretation
    assert provenance["source_all_valid"] is False


def test_paper_builder_rejects_unsealed_source(tmp_path) -> None:
    source = tmp_path / "formal"
    source.mkdir()
    with pytest.raises(paper_builder.E2PaperEvidenceError, match="missing"):
        paper_builder.build(source, tmp_path / "paper")
