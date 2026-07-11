from __future__ import annotations

import inspect


def test_loss_recovery_gate_uses_the_formal_e2_start_contract() -> None:
    from baselines.e2_alns import e2_loss_recovery_gate as gate

    source = inspect.getsource(gate._run_task)
    assert "make_shared_initial_solution(bundle, prices=prices)" in source
    assert "common_flip_preprocess=True" in source
    assert "introduce_ev=False" not in source


def test_loss_recovery_gate_keeps_a_bounded_nine_pair_matrix() -> None:
    from baselines.e2_alns import e2_loss_recovery_gate as gate

    pairs = (*gate.DEVELOPMENT_PAIRS, *gate.GUARD_PAIRS)
    algorithms = ("staged", "true_lns_middle", "LNS")
    tasks = [(instance, seed, algorithm) for instance, seed in pairs for algorithm in algorithms]
    assert len(pairs) == 9
    assert len(tasks) == 27
    assert len(set(tasks)) == 27
    assert set(gate.CANDIDATE_ALGORITHMS) == {
        "restarted",
        "true_lns_middle",
        "proportional_true_lns_middle",
    }


def test_loss_recovery_verifier_accepts_any_registered_short_gate_candidate() -> None:
    from baselines.e2_alns.e2_loss_recovery_verify import _is_short_gate_decision

    assert _is_short_gate_decision("RESTART_SHORT_GATE_REJECTED")
    assert _is_short_gate_decision("TRUE_LNS_MIDDLE_SHORT_GATE_PROMOTED")
    assert not _is_short_gate_decision("HALT_INCOMPLETE")
