from dr_alns_ppo.final_track19 import track19_status


def _row(**overrides):
    base = {
        "feasible": True,
        "violation_count": 0,
        "eval_ratio": 1.0,
        "unique_solution_count": 10,
        "best_cost": 90.0,
        "warm_start_cost": 100.0,
        "solution_hash": "new",
        "warm_hash": "warm",
    }
    base.update(overrides)
    return base


def test_track19_status_healthy_requires_improvement_and_hash_change():
    assert track19_status(_row()) == "HEALTHY"
    assert track19_status(_row(best_cost=100.0, solution_hash="warm")) == "VALID_BUT_WEAK"
    assert track19_status(_row(best_cost=110.0, solution_hash="other")) == "VALID_BUT_WEAK"


def test_track19_status_blocks_starved_or_unexplored_rows():
    assert track19_status(_row(eval_ratio=0.5)) == "INVALID_NOT_RUN"
    assert track19_status(_row(unique_solution_count=1)) == "INVALID_NOT_RUN"
    assert track19_status(_row(violation_count=1)) == "INVALID_VIOLATION"


def test_track19_status_uses_operator_attempts_as_method_exploration_proxy():
    row = _row(
        unique_solution_count=1,
        best_cost=100.0,
        solution_hash="warm",
        operator_counts='{"destroy":{"random_customer_removal":[0,0,0,16000]}}',
    )
    assert track19_status(row) == "VALID_BUT_WEAK"
