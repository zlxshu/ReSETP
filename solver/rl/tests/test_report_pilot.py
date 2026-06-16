from dr_alns_ppo.report_pilot import SYSTEM_WORKER_PYTHON, build_pilot_report, reward_trend


def test_reward_trend_detects_upward_learning_signal() -> None:
    rows = [{"r": str(value)} for value in (100.0, 110.0, 120.0, 130.0, 160.0, 180.0)]

    trend = reward_trend(rows)

    assert trend["reward_up"] is True
    assert trend["episode_count"] == 6
    assert trend["last_third_mean"] > trend["first_third_mean"]


def test_pilot_report_promising_when_reward_and_10001_close_alpha() -> None:
    report = build_pilot_report(
        monitor_rows=_upward_monitor(),
        train_rows=_comparison_rows(ppo=103.0, alpha=100.0, random=130.0),
        formal_10001_rows=_comparison_rows(ppo=104.0, alpha=100.0, random=130.0),
        held_out_rows=_comparison_rows(ppo=104.0, alpha=100.0, random=130.0),
    )

    assert report["verdict"] == "PROMISING"
    assert report["formal_10001_summary"]["ppo_close_to_alpha"] is True
    assert report["integrity"]["ok"] is True


def test_pilot_report_data_limited_when_train_close_but_10001_not_close() -> None:
    report = build_pilot_report(
        monitor_rows=_upward_monitor(),
        train_rows=_comparison_rows(ppo=103.0, alpha=100.0, random=130.0),
        formal_10001_rows=_comparison_rows(ppo=120.0, alpha=100.0, random=130.0),
        held_out_rows=_comparison_rows(ppo=120.0, alpha=100.0, random=130.0),
    )

    assert report["verdict"] == "DATA_LIMITED"
    assert report["train_summary"]["ppo_close_to_alpha"] is True
    assert report["formal_10001_summary"]["ppo_close_to_alpha"] is False


def test_pilot_report_weak_when_reward_flat_or_train_not_close() -> None:
    report = build_pilot_report(
        monitor_rows=[{"r": "100.0"}, {"r": "100.0"}, {"r": "99.0"}],
        train_rows=_comparison_rows(ppo=120.0, alpha=100.0, random=130.0),
        formal_10001_rows=_comparison_rows(ppo=120.0, alpha=100.0, random=130.0),
        held_out_rows=_comparison_rows(ppo=120.0, alpha=100.0, random=130.0),
    )

    assert report["verdict"] == "WEAK"
    assert report["reward_trend"]["reward_up"] is False


def test_pilot_report_halts_on_non_system_worker_or_violation() -> None:
    rows = _comparison_rows(ppo=103.0, alpha=100.0, random=130.0)
    rows[0]["worker_python_executable"] = "/tmp/venv/bin/python"
    rows[1]["violation_count"] = 1

    report = build_pilot_report(
        monitor_rows=_upward_monitor(),
        train_rows=rows,
        formal_10001_rows=_comparison_rows(ppo=104.0, alpha=100.0, random=130.0),
        held_out_rows=_comparison_rows(ppo=104.0, alpha=100.0, random=130.0),
    )

    assert report["verdict"] == "HALT_INTEGRITY"
    assert report["integrity"]["ok"] is False
    assert report["integrity"]["non_system_worker"]
    assert report["integrity"]["violations"]


def _upward_monitor() -> list[dict[str, str]]:
    return [{"r": str(value)} for value in (100.0, 110.0, 120.0, 130.0, 160.0, 180.0)]


def _comparison_rows(*, ppo: float, alpha: float, random: float) -> list[dict]:
    return [
        _row("alpha_ucb_env", 1, alpha),
        _row("ppo_full", 1, ppo),
        _row("random_full", 1, random),
        _row("alpha_ucb_env", 2, alpha),
        _row("ppo_full", 2, ppo),
        _row("random_full", 2, random),
    ]


def _row(algorithm: str, seed: int, best_obj: float) -> dict:
    return {
        "algorithm": algorithm,
        "bundle": "bundle-a",
        "seed": seed,
        "eval_budget": 16000,
        "best_obj": best_obj,
        "actual_evals": 16000,
        "candidate_scores": 16000,
        "repair_delta_count": 1,
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "ppo_full" if algorithm == "ppo_full" else "kernel_default",
        "violation_count": 0,
        "feasible": True,
        "solution_signature_hash": "hash",
        "operator_counts": {},
        "destroy_counts": {},
        "repair_counts": {},
        "q_ratio_counts": {},
        "worker_python_executable": SYSTEM_WORKER_PYTHON,
        "worker_python_version": "3.13.9",
        "worker_numpy_version": "2.3.5",
    }
