import json
import os
import subprocess
import sys
from pathlib import Path

from dr_alns_ppo.action_space import decode_action
from dr_alns_ppo.worker_client import WorkerClient, _worker_env

FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_worker_step_counts_one_candidate_eval() -> None:
    client = WorkerClient(FIXTURE_DIR, seed=1, max_evals=20)
    try:
        reset = client.reset()
        response = client.step(decode_action([0, 1, 3, 50], base_temperature=100.0))
    finally:
        client.close()

    assert reset["actual_evals"] == 0
    assert response["actual_evals"] == 1
    assert response["candidate_scores"] == 1
    assert response["repair_delta_count"] > 0
    assert response["trace"]["operator_base_id"] == "winner_kernel_v1"
    assert response["trace"]["winner_operator_module"] == "setp_solver.search.winner_operators"
    assert response["trace"]["destroy_id"] == "random_customer_removal"
    assert response["trace"]["repair_id"] == "regret2_insert_repair"
    assert response["trace"]["actual_evals_added"] == 1
    assert "D1" not in response["trace"].values()


def test_worker_refuses_steps_after_eval_budget_target() -> None:
    client = WorkerClient(FIXTURE_DIR, seed=1, max_evals=1)
    try:
        client.reset()
        first = client.step(decode_action([0, 1, 3, 50], base_temperature=100.0))
        second = client.step(decode_action([0, 1, 3, 50], base_temperature=100.0))
    finally:
        client.close()

    assert first["ok"] is True
    assert first["actual_evals"] == 1
    assert second["ok"] is False
    assert second["actual_evals"] == 1
    assert second["candidate_scores"] == 1
    assert "EvalBudget target reached" in second["error"]


def test_worker_rejects_non_finite_action_numbers_with_strict_json_response() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "solver" / "rl"),
            str(REPO_ROOT / "solver" / "src"),
            str(REPO_ROOT / "models" / "src"),
            env.get("PYTHONPATH", ""),
        ]
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dr_alns_ppo.worker",
            "--bundle-dir",
            str(REPO_ROOT / FIXTURE_DIR),
            "--seed",
            "1",
            "--max-evals",
            "5",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(
            '{"request_id":1,"op":"step","action":'
            '{"destroy_id":"D1","repair_id":"R1","q_ratio":NaN,"temperature":Infinity}}\n'
        )
        proc.stdin.flush()
        raw = proc.stdout.readline()
        response = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        proc.stdin.write('{"request_id":2,"op":"close"}\n')
        proc.stdin.flush()
        proc.stdout.readline()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)

    assert "Infinity" not in raw
    assert response["ok"] is False
    assert response["actual_evals"] == 0
    assert "invalid JSON constant" in response["error"]


def test_worker_rejects_non_finite_request_id_without_crashing_jsonl() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "solver" / "rl"),
            str(REPO_ROOT / "solver" / "src"),
            str(REPO_ROOT / "models" / "src"),
            env.get("PYTHONPATH", ""),
        ]
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dr_alns_ppo.worker",
            "--bundle-dir",
            str(REPO_ROOT / FIXTURE_DIR),
            "--seed",
            "1",
            "--max-evals",
            "5",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write('{"request_id":NaN,"op":"close"}\n')
        proc.stdin.flush()
        raw = proc.stdout.readline()
        response = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        proc.stdin.close()
        proc.wait(timeout=5)
        stderr = proc.stderr.read() if proc.stderr is not None else ""
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)

    assert response["request_id"] is None
    assert response["ok"] is False
    assert "invalid JSON constant" in response["error"]
    assert "Out of range float values" not in stderr


def test_worker_client_resolves_repo_relative_bundle_from_other_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = WorkerClient(FIXTURE_DIR, seed=1, max_evals=5)
    try:
        reset = client.reset()
        response = client.step(decode_action([0, 1, 3, 50], base_temperature=100.0))
    finally:
        client.close()

    assert reset["ok"] is True
    assert response["ok"] is True
    assert response["actual_evals"] == 1


def test_worker_operator_only_uses_kernel_default_q_and_zero_threshold() -> None:
    client = WorkerClient(FIXTURE_DIR, seed=1, max_evals=5)
    try:
        client.reset()
        response = client.step(decode_action([5, 2], base_temperature=100.0, control_mode="operator_only"))
    finally:
        client.close()

    assert response["ok"] is True
    assert response["trace"]["destroy_id"] == "vehicle_type_swap"
    assert response["trace"]["repair_id"] == "regret3_insert_repair"
    assert response["trace"]["remove_count_q"] is None
    assert response["trace"]["threshold"] == 0.0
    assert response["trace"]["control_mode"] == "operator_only"


def test_worker_client_does_not_inherit_pythonpath(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/tmp/should-not-leak")

    env = _worker_env(REPO_ROOT)

    assert "/tmp/should-not-leak" not in env["PYTHONPATH"]
    assert str(REPO_ROOT / "solver" / "rl") in env["PYTHONPATH"].split(os.pathsep)
    assert str(REPO_ROOT / "solver" / "src") in env["PYTHONPATH"].split(os.pathsep)


def test_worker_client_close_reaps_already_exited_worker() -> None:
    client = WorkerClient("models/data_bundle/generated_instances/does_not_exist", seed=1, max_evals=1)
    try:
        try:
            client.reset()
        except RuntimeError:
            pass
        response = client.close()
    finally:
        client.close()

    assert response is None
    assert client._proc.poll() is not None
