from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[2]
PREFLIGHT_PATH = REPO / "baselines/e2_alns/audit_solomon_external_strong_baseline_preflight_20260717.py"
RUNNER_PATH = REPO / "baselines/e2_alns/run_solomon_external_strong_baselines_20260717.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load("test_external_preflight", PREFLIGHT_PATH)
RUNNER = load("test_external_runner", RUNNER_PATH)


def test_current_preflight_is_zero_search_and_halts_on_missing_tool_freeze():
    metadata, rows, decision = PREFLIGHT.build_preflight()
    assert metadata["search_performed"] is False
    assert metadata["search_evaluations"] == 0
    assert metadata["e7_attestation_content_read"] is False
    assert metadata["tool_freeze_content_read"] is False
    assert decision["formal_search_authorized"] is False
    assert decision["verdict"] == "HALT_EXTERNAL_BASELINE_PREREQUISITES"
    assert "E7_STEPS_1_TO_6_ATTESTATION_MISSING" not in decision["failures"]
    assert "EXTERNAL_BASELINE_TOOL_FREEZE_MISSING" in decision["failures"]
    assert all(row["search_evaluations"] == 0 for row in rows)


def test_official_hgs_cvrp_is_not_silently_accepted(monkeypatch):
    monkeypatch.delenv("RESET_HGS_VRPTW_BINARY", raising=False)
    monkeypatch.setattr(PREFLIGHT.shutil, "which", lambda name: "/tmp/HGS" if name == "hgs" else None)
    row = PREFLIGHT.discover_hgs_vrptw()
    assert row["available"] is False
    assert row["compatibility"] == "OFFICIAL_HGS_CVRP_IS_NOT_A_VRPTW_BASELINE"


def test_search_tasks_cover_all_56_by_10_and_do_not_contain_bks():
    tasks = RUNNER.build_tasks({"distance_scale": 1_000_000, "wall_clock_seconds": 1800.0})
    assert len(tasks) == 560
    assert len({task["instance"] for task in tasks}) == 56
    assert {task["seed"] for task in tasks} == set(range(1, 11))
    assert all("bks" not in json.dumps(task, sort_keys=True).lower() for task in tasks)
    assert all(task["baseline_id"] == "PyVRP" for task in tasks)


def test_task_objective_proxy_uses_positive_proved_fixed_vehicle_cost():
    tasks = RUNNER.build_tasks({"distance_scale": 1_000_000, "wall_clock_seconds": 3.0})
    assert all(task["fixed_vehicle_cost_scaled"] > 0 for task in tasks)
    for task in tasks[::10]:
        bundle = RUNNER.BUNDLES / task["instance"]
        raw = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
        matrix = RUNNER.np.load(bundle / "distance_matrix.npy", allow_pickle=False)
        max_arcs = len(raw["nodes"]) - 1 + int(raw["metadata"]["num_cv"])
        max_integer_arc = max(RUNNER._scaled(float(value), task["distance_scale"]) for value in matrix.flat)
        upper = max_arcs * max_integer_arc
        assert task["max_route_arcs"] == max_arcs
        assert task["max_integer_arc_scaled"] == max_integer_arc
        assert task["all_route_distance_upper_scaled"] == upper
        assert task["fixed_vehicle_cost_scaled"] == upper + 1


def test_fixed_vehicle_cost_covers_per_arc_rounding_counterexample():
    scale = 1_000_000
    matrix = RUNNER.np.array([[0.0, 1.0000005], [1.0000005, 0.0]])
    proof = RUNNER.proved_fixed_vehicle_cost(matrix, customer_count=7, max_vehicles=3, scale=scale)
    old_aggregate_bound_plus_one = RUNNER.math.floor(10 * float(matrix.max()) * scale) + 1
    assert proof["max_integer_arc_scaled"] == 1_000_001
    assert proof["all_route_distance_upper_scaled"] == 10_000_010
    assert proof["fixed_vehicle_cost_scaled"] == 10_000_011
    assert old_aggregate_bound_plus_one < proof["fixed_vehicle_cost_scaled"]


def test_conditional_gap_join_preserves_vehicle_count_priority():
    ref = {"bks_vehicles": "10", "bks_distance": "828.94"}
    row = {
        "status": "OK",
        "route_count": 11,
        "distance_rounded_2": 700.0,
    }
    joined = RUNNER.join_reference(row, ref)
    assert joined["vehicle_excess"] == 1
    assert joined["distance_gap_pct"] == ""
    assert joined["full_bks_hit"] is False


def test_improved_tuple_is_preserved_as_bks_conflict_candidate():
    ref = {"bks_vehicles": "10", "bks_distance": "828.94"}
    joined = RUNNER.join_reference(
        {"status": "OK", "route_count": 10, "distance_rounded_2": 828.93},
        ref,
    )
    assert joined["bks_conflict_candidate"] is True
    assert joined["distance_gap_pct"] < 0


def test_time_to_best_is_first_timestamp_reaching_final_cost():
    result = SimpleNamespace(
        cost=lambda: 100.0,
        stats=[
            SimpleNamespace(runtime=0.1, feas=SimpleNamespace(best=120.0)),
            SimpleNamespace(runtime=0.4, feas=SimpleNamespace(best=100.0)),
            SimpleNamespace(runtime=0.8, feas=SimpleNamespace(best=100.0)),
        ],
    )
    assert RUNNER.extract_time_to_best(result) == pytest.approx(0.4)


def test_pyvrp_0134_time_to_best_uses_cumulative_runtime_deltas():
    stats = SimpleNamespace(
        data=[
            SimpleNamespace(best_cost=120, best_feas=True),
            SimpleNamespace(best_cost=100, best_feas=True),
            SimpleNamespace(best_cost=100, best_feas=True),
        ],
        runtimes=[0.1, 0.3, 0.4],
        num_iterations=3,
    )
    result = SimpleNamespace(cost=lambda: 100.0, stats=stats)
    assert RUNNER.extract_time_to_best(result) == pytest.approx(0.4)


def test_pyvrp_0134_statistics_length_mismatch_fails_closed():
    stats = SimpleNamespace(
        data=[SimpleNamespace(best_cost=100, best_feas=True)],
        runtimes=[],
        num_iterations=1,
    )
    result = SimpleNamespace(cost=lambda: 100.0, stats=stats)
    with pytest.raises(RUNNER.ExternalBaselineError, match="lengths differ"):
        RUNNER.extract_time_to_best(result)


def test_unknown_time_to_best_statistics_fail_closed():
    result = SimpleNamespace(cost=lambda: 100.0, stats=[SimpleNamespace(runtime=0.1)])
    with pytest.raises(RUNNER.ExternalBaselineError, match="best-feasible"):
        RUNNER.extract_time_to_best(result)


def test_formal_execution_requires_exact_authorisation_before_any_gate(monkeypatch, tmp_path):
    called = False

    def forbidden():
        nonlocal called
        called = True
        raise AssertionError("preflight must not run before authorisation check")

    monkeypatch.setattr(RUNNER.PREFLIGHT, "build_preflight", forbidden)
    with pytest.raises(RUNNER.ExternalBaselineError, match="authorisation"):
        RUNNER.execute_formal(tmp_path, "not-authorised")
    assert called is False


def test_freeze_template_is_non_authorising_and_separates_axes(monkeypatch):
    template = json.loads(
        (REPO / "docs/handoff/templates/e2_external_baseline_freeze_template_20260717.json").read_text(
            encoding="utf-8"
        )
    )
    assert template["formal_search_authorized"] is False
    assert template["single_thread_per_solver"] is True
    assert template["workers"] == 4
    assert template["time_to_best_extractor_verified"] is False
    monkeypatch.setattr(RUNNER, "sha256", lambda path: "frozen-hash")
    assert "same-machine single-thread wall-clock" in RUNNER.build_contract(
        {
            **template,
            "version": "test",
            "formal_search_authorized": True,
            "tool_source_hashes": {"a": "b"},
            "interface_source_hashes": {"c": "d"},
        },
        {"search_version": "test"},
    )["fairness_axis"]


def _self_hashed_tool_freeze(source: Path) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "resetp.e2.external-baseline-freeze.v1",
        "formal_search_authorized": True,
        "baseline_id": "PyVRP",
        "version": "0.13.4",
        "python_executable": sys.executable,
        "workers": 4,
        "single_thread_per_solver": True,
        "seeds": list(range(1, 11)),
        "wall_clock_seconds": 3.0,
        "distance_scale": 1_000_000,
        "time_to_best_extractor_verified": True,
        "tool_source_hashes": {str(source): RUNNER.sha256(source)},
        "interface_source_hashes": {str(source): RUNNER.sha256(source)},
    }
    return {**body, "freeze_payload_sha256": RUNNER.canonical_sha256(body)}


def test_tool_freeze_payload_hash_is_verified_before_formal_search(monkeypatch, tmp_path):
    source = tmp_path / "source.py"
    source.write_text("frozen = True\n", encoding="utf-8")
    freeze_path = tmp_path / "external_baseline_freeze.json"
    payload = _self_hashed_tool_freeze(source)
    RUNNER.atomic_json(freeze_path, payload)
    monkeypatch.setattr(RUNNER, "TOOL_FREEZE", freeze_path)
    monkeypatch.setattr(
        RUNNER.PREFLIGHT,
        "discover_pyvrp",
        lambda: {"available": True, "version": "0.13.4"},
    )
    assert RUNNER.require_tool_freeze()["freeze_payload_sha256"] == payload["freeze_payload_sha256"]

    RUNNER.atomic_json(freeze_path, {**payload, "wall_clock_seconds": 4.0})
    with pytest.raises(RUNNER.ExternalBaselineError, match="payload hash differs"):
        RUNNER.require_tool_freeze()


def _self_hashed_contract(**values):
    body = {"schema_version": "test.contract.v1", **values}
    return {**body, "contract_sha256": RUNNER.canonical_sha256(body)}


def _first_task(contract_sha256="contract-test"):
    task = RUNNER.build_tasks({"distance_scale": 1_000_000, "wall_clock_seconds": 3.0})[0]
    return {**task, "contract_sha256": contract_sha256}


def test_output_directory_resumes_only_identical_contract(tmp_path):
    contract = _self_hashed_contract(baseline_id="PyVRP")
    first = RUNNER.ensure_output(tmp_path, contract)
    second = RUNNER.ensure_output(tmp_path, contract)
    assert first == second == tmp_path / "contract.json"
    assert (tmp_path / ".tasks/attempts").is_dir()
    assert (tmp_path / ".tasks/checkpoints").is_dir()
    with pytest.raises(RUNNER.ExternalBaselineError, match="contract"):
        RUNNER.ensure_output(tmp_path, _self_hashed_contract(baseline_id="different"))


def test_runtime_freeze_checks_contract_tool_interface_and_bundle_hashes(monkeypatch, tmp_path):
    e7_attestation = tmp_path / "e7-attestation.json"
    tool_freeze = tmp_path / "tool-freeze.json"
    tool_source = tmp_path / "tool.py"
    interface_source = tmp_path / "interface.py"
    e7_attestation.write_text("{}\n", encoding="utf-8")
    tool_freeze.write_text("{}\n", encoding="utf-8")
    tool_source.write_text("tool = 1\n", encoding="utf-8")
    interface_source.write_text("interface = 1\n", encoding="utf-8")
    monkeypatch.setattr(RUNNER, "TOOL_FREEZE", tool_freeze)
    monkeypatch.setattr(RUNNER, "E7_ATTESTATION", e7_attestation)
    contract = _self_hashed_contract(
        e7_attestation_sha256=RUNNER.sha256(e7_attestation),
        tool_freeze_sha256=RUNNER.sha256(tool_freeze),
        tool_source_hashes={str(tool_source): RUNNER.sha256(tool_source)},
        interface_source_hashes={str(interface_source): RUNNER.sha256(interface_source)},
    )
    contract_path = tmp_path / "contract.json"
    RUNNER.atomic_json(contract_path, contract)
    task = _first_task(contract["contract_sha256"])
    assert RUNNER.verify_runtime_freeze(task, contract_path)["contract_sha256"] == contract["contract_sha256"]
    interface_source.write_text("interface = 2\n", encoding="utf-8")
    with pytest.raises(RUNNER.ExternalBaselineError, match="frozen source differs"):
        RUNNER.verify_runtime_freeze(task, contract_path)


def test_runtime_freeze_rejects_deleted_or_changed_e7_attestation_without_reading_it(monkeypatch, tmp_path):
    e7_attestation = tmp_path / "e7-attestation.json"
    tool_freeze = tmp_path / "tool-freeze.json"
    source = tmp_path / "source.py"
    e7_attestation.write_text("sealed-not-read\n", encoding="utf-8")
    tool_freeze.write_text("{}\n", encoding="utf-8")
    source.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(RUNNER, "E7_ATTESTATION", e7_attestation)
    monkeypatch.setattr(RUNNER, "TOOL_FREEZE", tool_freeze)
    contract = _self_hashed_contract(
        e7_attestation_sha256=RUNNER.sha256(e7_attestation),
        tool_freeze_sha256=RUNNER.sha256(tool_freeze),
        tool_source_hashes={str(source): RUNNER.sha256(source)},
        interface_source_hashes={str(source): RUNNER.sha256(source)},
    )
    contract_path = tmp_path / "contract.json"
    RUNNER.atomic_json(contract_path, contract)
    task = _first_task(contract["contract_sha256"])
    assert RUNNER.verify_runtime_freeze(task, contract_path)
    e7_attestation.write_text("changed\n", encoding="utf-8")
    with pytest.raises(RUNNER.ExternalBaselineError, match="E7 attestation differs"):
        RUNNER.verify_runtime_freeze(task, contract_path)


def test_e7_attestation_must_be_bound_to_zero_search_builder(monkeypatch, tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    builder_hash = RUNNER.sha256(RUNNER.E7_ATTESTATION_BUILDER)
    builder_key = str(RUNNER.E7_ATTESTATION_BUILDER.relative_to(RUNNER.REPO))
    attestation = tmp_path / "attestation.json"
    payload = {
        "schema_version": "resetp.e7.steps-1-to-6-attestation.v1",
        "steps_1_to_6_complete": True,
        "search_version_closed": True,
        "search_version": "a" * 64,
        "builder_sha256": builder_hash,
        "evidence_hashes": {
            builder_key: builder_hash,
            str(evidence): RUNNER.sha256(evidence),
        },
    }
    RUNNER.atomic_json(attestation, payload)
    monkeypatch.setattr(RUNNER, "E7_ATTESTATION", attestation)
    assert RUNNER.require_e7_attestation()["search_version_closed"] is True
    RUNNER.atomic_json(attestation, {**payload, "builder_sha256": "0" * 64})
    with pytest.raises(RUNNER.ExternalBaselineError, match="zero-search builder"):
        RUNNER.require_e7_attestation()


def test_worker_checks_runtime_freeze_before_and_after_solver(monkeypatch, tmp_path):
    task_path = tmp_path / "task.json"
    output_path = tmp_path / "result.json"
    contract_path = tmp_path / "contract.json"
    RUNNER.atomic_json(task_path, {"task_key": "T"})
    contract_path.write_text("{}\n", encoding="utf-8")
    checks = []
    monkeypatch.setattr(RUNNER, "verify_runtime_freeze", lambda *args: checks.append(args) or {})
    monkeypatch.setattr(RUNNER, "run_pyvrp_worker", lambda task: {"task_key": task["task_key"]})
    assert RUNNER.worker_main(task_path, output_path, contract_path) == 0
    assert len(checks) == 2
    assert json.loads(output_path.read_text(encoding="utf-8"))["task_key"] == "T"


def test_hard_timeout_uses_new_process_group_term_then_kill(monkeypatch, tmp_path):
    task = _first_task()
    attempt = tmp_path / "attempt-0001"
    attempt.mkdir()
    calls = {}

    class FakeProcess:
        pid = 4242

        def __init__(self):
            self.wait_calls = 0

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls <= 2:
                raise RUNNER.subprocess.TimeoutExpired("fake", timeout)
            return -9

    process = FakeProcess()

    def fake_popen(*args, **kwargs):
        calls["start_new_session"] = kwargs.get("start_new_session")
        return process

    signals = []
    monkeypatch.setattr(RUNNER, "verify_runtime_freeze", lambda *args: {})
    monkeypatch.setattr(RUNNER.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(RUNNER.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    row = RUNNER.run_subprocess_attempt(
        task,
        attempt,
        {"python_executable": sys.executable},
        tmp_path / "contract.json",
    )
    assert calls["start_new_session"] is True
    assert signals == [(4242, RUNNER.signal.SIGTERM), (4242, RUNNER.signal.SIGKILL)]
    assert row["status"] == "INFRASTRUCTURE_TIMEOUT"
    assert row["failure_codes"] == ["HARD_WALL_TIMEOUT"]


def test_parent_recomputes_solution_and_rejects_identity_or_hash_tampering(monkeypatch):
    task = _first_task()
    recomputed = {
        "passed": True,
        "route_count": 1,
        "distance_double": 12.25,
        "distance_rounded_2": 12.25,
    }
    monkeypatch.setattr(RUNNER.FORMAL, "pure_vrptw_recompute", lambda *args: recomputed)
    solution = RUNNER._solution_from_routes([[1]])
    row = {
        "task_key": task["task_key"], "instance": task["instance"], "class": task["class"],
        "seed": task["seed"], "baseline_id": task["baseline_id"], "status": "OK",
        "failure_codes": [], "route_count": 1, "distance_double": 12.25,
        "distance_rounded_2": 12.25, "feasible": True, "routes": [[1]],
        "solution_sha256": RUNNER.canonical_sha256(solution),
        "independent_recomputation": recomputed,
    }
    validated = RUNNER.validate_result_identity_and_semantics(task, row)
    assert validated["parent_validation"].startswith("PARENT_IDENTITY")
    with pytest.raises(RUNNER.ExternalBaselineError, match="identity differs"):
        RUNNER.validate_result_identity_and_semantics(task, {**row, "seed": 999})
    with pytest.raises(RUNNER.ExternalBaselineError, match="solution hash differs"):
        RUNNER.validate_result_identity_and_semantics(task, {**row, "solution_sha256": "0" * 64})


def test_parent_rejects_incoherent_failure_semantics():
    task = _first_task()
    row = RUNNER._failure_result(task, "INFRASTRUCTURE_TIMEOUT", ["HARD_WALL_TIMEOUT"], 3.0)
    assert RUNNER.validate_result_identity_and_semantics(task, row)["status"] == "INFRASTRUCTURE_TIMEOUT"
    with pytest.raises(RUNNER.ExternalBaselineError, match="timeout failure semantics"):
        RUNNER.validate_result_identity_and_semantics(task, {**row, "failure_codes": ["WORKER_EXIT_1"]})
    with pytest.raises(RUNNER.ExternalBaselineError, match="unexpectedly contains routes"):
        RUNNER.validate_result_identity_and_semantics(task, {**row, "routes": [[1]]})


def test_per_task_checkpoint_is_sealed_and_resumable(monkeypatch, tmp_path):
    contract = _self_hashed_contract(baseline_id="PyVRP")
    contract_path = RUNNER.ensure_output(tmp_path, contract)
    task = _first_task(contract["contract_sha256"])
    checks = []
    monkeypatch.setattr(RUNNER, "verify_runtime_freeze", lambda *args: checks.append(args) or contract)
    monkeypatch.setattr(
        RUNNER,
        "run_subprocess_attempt",
        lambda task, attempt, freeze, contract_path: RUNNER._failure_result(
            task, "INFRASTRUCTURE_FAILURE", ["WORKER_EXIT_7"], 0.2
        ),
    )
    row = RUNNER.run_task_and_checkpoint(task, tmp_path, {}, contract_path)
    checkpoint = RUNNER.checkpoint_path(tmp_path, task["task_key"])
    assert checkpoint.is_file()
    loaded = RUNNER.load_task_checkpoint(task, tmp_path, contract_path)
    assert loaded == row
    assert len(checks) >= 3  # parent pre-seal, immediately pre-checkpoint, and resume
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    attempt = tmp_path / payload["attempt_relative_path"]
    assert (attempt / "task_artifact_hashes.json").is_file()
    assert payload["task_artifact_hashes_sha256"] == RUNNER.sha256(attempt / "task_artifact_hashes.json")


def test_checkpoint_tampering_halts_instead_of_silent_rerun(monkeypatch, tmp_path):
    contract = _self_hashed_contract(baseline_id="PyVRP")
    contract_path = RUNNER.ensure_output(tmp_path, contract)
    task = _first_task(contract["contract_sha256"])
    monkeypatch.setattr(RUNNER, "verify_runtime_freeze", lambda *args: contract)
    monkeypatch.setattr(
        RUNNER,
        "run_subprocess_attempt",
        lambda task, attempt, freeze, contract_path: RUNNER._failure_result(
            task, "INFRASTRUCTURE_FAILURE", ["WORKER_EXIT_9"], 0.1
        ),
    )
    RUNNER.run_task_and_checkpoint(task, tmp_path, {}, contract_path)
    checkpoint = json.loads(RUNNER.checkpoint_path(tmp_path, task["task_key"]).read_text(encoding="utf-8"))
    attempt = tmp_path / checkpoint["attempt_relative_path"]
    (attempt / "stdout.log").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RUNNER.ExternalBaselineError, match="artifact hashes differ"):
        RUNNER.load_task_checkpoint(task, tmp_path, contract_path)


def test_uncheckpointed_attempt_gets_new_independent_attempt_directory(tmp_path):
    first = RUNNER._next_attempt_dir(tmp_path, "R101__seed1")
    second = RUNNER._next_attempt_dir(tmp_path, "R101__seed1")
    assert first.name == "attempt-0001"
    assert second.name == "attempt-0002"
    assert first != second


@pytest.mark.parametrize("stop_signal", [RUNNER.signal.SIGINT, RUNNER.signal.SIGTERM])
def test_parent_signal_handler_only_sets_flag_then_main_drains_and_writes_incident(
    monkeypatch, tmp_path, stop_signal
):
    class DummyProcess:
        pid = 9876

        def wait(self, timeout=None):
            return -15

    process = DummyProcess()
    sent = []
    RUNNER._STOP_REQUESTED.clear()
    RUNNER._STOP_SIGNAL = None
    with RUNNER._ACTIVE_PROCESS_LOCK:
        RUNNER._ACTIVE_PROCESSES.clear()
    RUNNER._register_active_process(process)
    monkeypatch.setattr(RUNNER.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    RUNNER._parent_stop_signal_handler(stop_signal, None)
    assert RUNNER._STOP_REQUESTED.is_set()
    assert sent == []  # signal handler itself never performs process operations
    incident = RUNNER.handle_parent_stop_request(tmp_path, "contract", ["done"])
    assert sent == [(9876, RUNNER.signal.SIGTERM)]
    payload = json.loads(incident.read_text(encoding="utf-8"))
    assert payload["signal_name"] == RUNNER.signal.Signals(stop_signal).name
    assert payload["active_process_group_ids_at_stop"] == [9876]
    assert payload["checkpointed_task_keys_before_stop"] == ["done"]
    with RUNNER._ACTIVE_PROCESS_LOCK:
        assert RUNNER._ACTIVE_PROCESSES == {}
    RUNNER._STOP_REQUESTED.clear()
    RUNNER._STOP_SIGNAL = None


def test_stop_requested_before_launch_creates_no_attempt_or_checkpoint(tmp_path):
    task = _first_task()
    RUNNER._STOP_REQUESTED.set()
    try:
        with pytest.raises(RUNNER.ExternalBaselineError, match="before task launch"):
            RUNNER.run_task_and_checkpoint(task, tmp_path, {}, tmp_path / "contract.json")
        assert not (tmp_path / ".tasks/attempts" / task["task_key"]).exists()
        assert not RUNNER.checkpoint_path(tmp_path, task["task_key"]).exists()
    finally:
        RUNNER._STOP_REQUESTED.clear()


def test_global_task_index_binds_checkpoint_attempts_and_enters_main_manifest(monkeypatch, tmp_path):
    contract = _self_hashed_contract(
        baseline_id="PyVRP",
        baseline_version="test",
        fairness_axis="same-machine single-thread wall-clock",
        workers=4,
        wall_clock_seconds=3.0,
        instances=["R101"],
        seeds=[1],
    )
    contract_path = RUNNER.ensure_output(tmp_path, contract)
    task = _first_task(contract["contract_sha256"])
    monkeypatch.setattr(RUNNER, "verify_runtime_freeze", lambda *args: contract)
    monkeypatch.setattr(
        RUNNER,
        "run_subprocess_attempt",
        lambda task, attempt, freeze, contract_path: RUNNER._failure_result(
            task, "INFRASTRUCTURE_FAILURE", ["WORKER_EXIT_3"], 0.1
        ),
    )
    row = RUNNER.run_task_and_checkpoint(task, tmp_path, {}, contract_path)
    monkeypatch.setattr(RUNNER.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    RUNNER.write_final(tmp_path, contract, [row])
    index = json.loads((tmp_path / "task_artifact_hashes.json").read_text(encoding="utf-8"))
    assert index["task_count"] == 1
    assert index["checkpoint_count"] == 1
    assert index["tasks"][task["task_key"]]["attempts"][0]["sealed"] is True
    main_manifest = json.loads((tmp_path / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert main_manifest["task_artifact_hashes.json"] == RUNNER.sha256(tmp_path / "task_artifact_hashes.json")
    assert RUNNER.verify_global_task_artifact_index(tmp_path, contract)["task_count"] == 1
    attempt = tmp_path / index["tasks"][task["task_key"]]["attempts"][0]["relative_path"]
    (attempt / "parent_result.json").write_text("tampered after publication\n", encoding="utf-8")
    with pytest.raises(RUNNER.ExternalBaselineError, match="attempt artifact hash differs"):
        RUNNER.verify_global_task_artifact_index(tmp_path, contract)
