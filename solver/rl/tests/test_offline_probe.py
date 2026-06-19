from __future__ import annotations

from pathlib import Path

from dr_alns_ppo import offline_probe


def _row(episode: int, step: int, obs_00: float, action_destroy: int, reward: float) -> dict[str, object]:
    row: dict[str, object] = {
        "episode_index": episode,
        "collection_policy": "random_block" if episode == 0 else "stratified_random",
        "reward": reward,
        "action_destroy": action_destroy,
        "action_repair": step % 2,
        "action_q": step % 2,
        "action_threshold": step % 2,
        "action_exploration": step % 2,
    }
    for idx in range(19):
        row[f"obs_{idx:02d}"] = obs_00 if idx == 0 else float((episode + step + idx) % 3) / 10.0
    return row


def _context_predictable_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for episode in range(8):
        for step in range(24):
            obs_00 = 1.0 if step % 2 == 0 else -1.0
            reward = 1.0 if obs_00 > 0 else 0.0
            row = _row(episode, step, obs_00, 0, reward)
            row["action_repair"] = 0
            row["action_q"] = 0
            row["action_threshold"] = 0
            row["action_exploration"] = 0
            rows.append(row)
    return rows


def _context_independent_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for episode in range(8):
        for step in range(24):
            obs_00 = 1.0 if step % 2 == 0 else -1.0
            action_destroy = step % 2
            reward = 1.0 if action_destroy == 0 else 0.0
            rows.append(_row(episode, step, obs_00, action_destroy, reward))
    return rows


def _config() -> offline_probe.ProbeConfig:
    return offline_probe.ProbeConfig(seed=7, repeats=2, folds=3, bootstrap_samples=100, model_kind="gbr", run_ope=False)


def test_context_predictable_synthetic_rows_are_promising() -> None:
    report = offline_probe.analyze_rows(_context_predictable_rows(), config=_config())

    assert report["verdict"]["status"] == "PROMISING"
    assert report["probe_a_supervised_context"]["summary"]["r2_delta"]["ci95"][0] > 0.0


def test_context_independent_synthetic_rows_are_weak() -> None:
    report = offline_probe.analyze_rows(_context_independent_rows(), config=_config())

    assert report["verdict"]["status"] == "WEAK"
    assert report["probe_a_supervised_context"]["summary"]["r2_delta"]["ci95"][0] <= 0.0


def test_offline_probe_does_not_import_worker_environment() -> None:
    source = Path("solver/rl/dr_alns_ppo/offline_probe.py").read_text(encoding="utf-8")

    assert "BlockAlnsEnv" not in source
    assert "WorkerClient" not in source
    assert "SETP_WORKER_PYTHON" not in source
