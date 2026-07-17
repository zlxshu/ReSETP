from __future__ import annotations

import importlib.util
import json
import sys
import time
import signal
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = load_script(
    "test_solomon_sintef_formal_runner",
    "baselines/e2_alns/run_solomon_sintef_formal_20260717.py",
)
audit = load_script(
    "test_solomon_sintef_formal_audit",
    "baselines/e2_alns/audit_solomon_sintef_bks_20260717.py",
)


def fake_contract() -> dict[str, object]:
    references = runner.read_references()
    return {
        "instances": list(runner.FORMAL_INSTANCES),
        "seeds": list(runner.FORMAL_SEEDS),
        "classes": {name: row["class"] for name, row in references.items()},
        "capacities": {name: row["capacity"] for name, row in references.items()},
        "eval_budget": runner.FORMAL_EVAL_BUDGET,
        "max_runtime_seconds": runner.FORMAL_MAX_RUNTIME_SECONDS,
        "big_m_proofs": {name: runner.bundle_bounds(name) for name in runner.FORMAL_INSTANCES},
        "bundle_hashes": {name: runner.bundle_hashes(name) for name in runner.FORMAL_INSTANCES},
        "algorithm_freeze_sha256": "freeze-hash",
        "algorithm_version": "test-version",
    }


def test_reference_inventory_is_exact_and_zero_search() -> None:
    references = runner.read_references()
    assert len(references) == 56
    assert set(references) == set(runner.FORMAL_INSTANCES)
    assert references["C101"]["bks_vehicle_count"] == 10
    assert references["C101"]["bks_distance_published_2dp"] == 828.94


def test_worker_module_does_not_load_bks_and_uses_bounded_killable_processes() -> None:
    source = (ROOT / "baselines/e2_alns/run_solomon_sintef_formal_20260717.py").read_text(
        encoding="utf-8"
    )
    assert "FORMAL_INSTANCES = tuple(sorted(read_references()))" not in source
    assert len(runner.FORMAL_INSTANCES) == 56
    assert len(set(runner.FORMAL_INSTANCES)) == 56
    assert "subprocess.Popen(" in source
    assert '"--worker-task"' in source
    assert "len(active) < FORMAL_WORKERS" in source
    assert "ProcessPoolExecutor" not in source
    assert "start_new_session=True" in source
    assert "os.killpg(" in source


def test_canonical_solution_record_is_jsonl_safe() -> None:
    record = {
        "task_key": "C101__seed1",
        "solution": {"routes": [{"node_sequence": ["D0", "C1", "D0"]}]},
        "operator_counts": {"跨场": 1},
    }
    encoded = runner.canonical_json(record)
    assert "\n" not in encoded
    assert json.loads(encoded) == record


def test_class_summary_does_not_publish_partial_cnv_or_ctd() -> None:
    references = runner.read_references()
    instance_rows = []
    for name in runner.FORMAL_INSTANCES:
        reference = references[name]
        instance_rows.append(
            {
                "instance": name,
                "class": reference["class"],
                "best_route_count": "" if name == "C101" else reference["bks_vehicle_count"],
                "best_distance": "" if name == "C101" else reference["bks_distance_published_2dp"],
                "avg_process_cpu_seconds": 1.0,
                "avg_elapsed_seconds": 2.0,
                "avg_time_to_best_seconds": 0.5,
                "runs": 10,
                "valid_runs": 0 if name == "C101" else 10,
            }
        )
    summaries = {row["class"]: row for row in runner.build_class_summary(instance_rows)}
    assert summaries["C1"]["complete_instance_count"] == 8
    assert summaries["C1"]["CNV"] == ""
    assert summaries["C1"]["CTD"] == ""
    assert summaries["C2"]["complete_instance_count"] == 8
    assert summaries["C2"]["CNV"] != ""


def test_formal_task_matrix_is_exact_and_contains_no_bks() -> None:
    tasks = runner.build_search_tasks(fake_contract())
    assert len(tasks) == 560
    assert len({task["task_key"] for task in tasks}) == 560
    assert all("bks" not in json.dumps(task, sort_keys=True).lower() for task in tasks)
    assert all("reference" not in json.dumps(task, sort_keys=True).lower() for task in tasks)
    assert all(task["algorithm_freeze_sha256"] == "freeze-hash" for task in tasks)


def test_runtime_contract_rejects_bundle_or_freeze_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    task = runner.build_search_tasks(fake_contract())[0]
    monkeypatch.setattr(runner, "bundle_hashes", lambda _name: dict(task["bundle_hashes"]))
    monkeypatch.setattr(runner, "sha256", lambda _path: "freeze-hash")
    monkeypatch.setattr(
        runner,
        "require_algorithm_freeze",
        lambda: {"algorithm_version": "test-version"},
    )
    runner.verify_task_runtime_contract(task)
    monkeypatch.setattr(runner, "bundle_hashes", lambda _name: {"instance.json": "drift"})
    with pytest.raises(runner.FormalRunError, match="bundle hashes differ"):
        runner.verify_task_runtime_contract(task)


def test_worker_attempt_paths_never_reuse_incident_or_logs(tmp_path: Path) -> None:
    first = runner.worker_paths(tmp_path, "C101__seed1", "attempt-1")
    second = runner.worker_paths(tmp_path, "C101__seed1", "attempt-2")
    assert first["incident"] != second["incident"]
    assert first["stdout"] != second["stdout"]
    first["incident"].parent.mkdir(parents=True)
    first["incident"].write_text("preserved", encoding="utf-8")
    second["stdout"].parent.mkdir(parents=True)
    second["stdout"].write_text("new", encoding="utf-8")
    assert first["incident"].read_text(encoding="utf-8") == "preserved"


def test_stop_workers_uses_process_group_and_preserves_incident(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeProcess:
        pid = 4242
        returncode = None
        wait_calls = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls += 1
            if timeout is not None and self.wait_calls == 1:
                raise runner.subprocess.TimeoutExpired("worker", timeout)
            self.returncode = -signal.SIGKILL
            return self.returncode

    process = FakeProcess()
    paths = runner.worker_paths(tmp_path, "C101__seed1", "attempt-1")
    paths["task"].parent.mkdir(parents=True)
    paths["task"].write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    record = {
        "task": {"task_key": "C101__seed1"},
        "paths": paths,
        "process": process,
        "stdout_handle": None,
        "stderr_handle": None,
        "started_ns": time.perf_counter_ns(),
    }
    runner.stop_workers({"C101__seed1": record})
    assert calls == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
    incident = json.loads(paths["incident"].read_text(encoding="utf-8"))
    assert incident["code"] == "PARENT_ABORTED_INFLIGHT"


def test_stop_workers_terminates_a_real_dummy_process_group(tmp_path: Path) -> None:
    process = runner.subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    paths = runner.worker_paths(tmp_path, "dummy", "attempt-1")
    paths["task"].parent.mkdir(parents=True)
    paths["task"].write_text("{}", encoding="utf-8")
    record = {
        "task": {"task_key": "dummy"},
        "paths": paths,
        "process": process,
        "stdout_handle": None,
        "stderr_handle": None,
        "started_ns": time.perf_counter_ns(),
    }
    runner.stop_workers({"dummy": record})
    assert process.poll() is not None
    assert paths["incident"].is_file()


def test_all_instance_specific_big_m_values_prove_lexicographic_priority() -> None:
    for name in runner.FORMAL_INSTANCES:
        proof = runner.bundle_bounds(name)
        assert proof["big_m"] > proof["distance_upper_bound"]
        assert runner.lex_key(9, 10_000.0) < runner.lex_key(10, 1.0)


@pytest.mark.parametrize(
    ("vehicles", "distance", "expected_gap", "expected_excess", "expected_hit", "expected_conflict"),
    [
        (10, 828.94, 0.0, 0, True, False),
        (10, 838.94, 100.0 * 10.0 / 828.94, 0, False, False),
        (11, 700.00, "", 1, False, False),
        (9, 900.00, "", -1, False, True),
        (10, 828.93, 100.0 * -0.01 / 828.94, 0, False, True),
    ],
)
def test_conditional_gap_and_bks_conflict_rules(
    vehicles: int,
    distance: float,
    expected_gap: float | str,
    expected_excess: int,
    expected_hit: bool,
    expected_conflict: bool,
) -> None:
    result = runner.reference_assessment(vehicles, distance, 10, 828.94)
    assert result["vehicle_excess"] == expected_excess
    assert result["full_bks_hit"] is expected_hit
    assert result["bks_conflict_candidate"] is expected_conflict
    if expected_gap == "":
        assert result["distance_gap_pct"] == ""
    else:
        assert result["distance_gap_pct"] == pytest.approx(expected_gap)


def test_c101_reference_route_recomputes_through_search_bundle() -> None:
    routes = audit.parse_routes(audit.SOLUTIONS / "c101.txt")
    solution = {
        "routes": [
            {
                "vehicle_id": f"CV{index}",
                "vehicle_type": "cv",
                "home_depot_id": "D0",
                "node_sequence": ["D0", *[f"C{customer}" for customer in customers], "D0"],
            }
            for index, customers in enumerate(routes, start=1)
        ],
        "charging_actions": [],
        "cross_site_services": [],
    }
    result = runner.pure_vrptw_recompute(solution, runner.BUNDLES / "C101")
    assert result["passed"] is True
    assert result["route_count"] == 10
    assert result["distance_double"] == pytest.approx(828.936866942834)
    assert result["distance_rounded_2"] == 828.94


def test_repo_aware_bundle_manifest_closes_after_appledouble_cleanup() -> None:
    verified = runner.verify_repo_aware_manifest(runner.BUNDLES)
    assert len(verified) == 174
    assert not list(runner.BUNDLES.rglob("._*"))


def test_manifest_gate_rejects_tamper_and_appledouble(tmp_path: Path) -> None:
    for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    manifest = {name: runner.sha256(tmp_path / name) for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")}
    (tmp_path / "artifact_hashes.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert runner.verify_artifact_manifest(tmp_path)
    (tmp_path / "metadata.json").write_text("tamper", encoding="utf-8")
    with pytest.raises(runner.FormalRunError, match="hash differs"):
        runner.verify_artifact_manifest(tmp_path)
    (tmp_path / "metadata.json").write_text("metadata.json", encoding="utf-8")
    (tmp_path / "._metadata.json").write_text("sidecar", encoding="utf-8")
    with pytest.raises(runner.FormalRunError, match="AppleDouble"):
        runner.verify_artifact_manifest(tmp_path)


def test_checkpoint_identity_and_row_hash_are_both_enforced(tmp_path: Path) -> None:
    task = runner.build_search_tasks(fake_contract())[0]
    row = {"task_key": task["task_key"], "seed": task["seed"], "status": "OK"}
    path = tmp_path / "row.json"
    runner.save_checkpoint(path, "contract", task, row)
    assert runner.load_checkpoint(path, "contract", task) == row
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["row"]["status"] = "TAMPER"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(runner.CheckpointError, match="row hash"):
        runner.load_checkpoint(path, "contract", task)


def test_process_cpu_and_wall_time_are_distinct_measures() -> None:
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    time.sleep(0.03)
    cpu_delta = time.process_time() - cpu_start
    wall_delta = time.perf_counter() - wall_start
    assert wall_delta >= 0.025
    assert cpu_delta < wall_delta


def test_failed_preflight_creates_no_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "parse_args", lambda: type("Args", (), {"output": tmp_path / "out", "preflight_only": False})())
    monkeypatch.setattr(runner, "build_contract", lambda: (_ for _ in ()).throw(runner.FormalRunError("gate")))
    with pytest.raises(runner.FormalRunError, match="gate"):
        runner.main()
    assert not (tmp_path / "out").exists()
